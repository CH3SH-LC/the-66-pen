#!/usr/bin/env python3
"""Reconstruct the editor's node-category tree from the decoded BeyondGlobal sample.

BeyondGlobal decodes (XOR 0xE5 -> protobuf wire) to a nested structure of
category nodes. Each carries a uint32 that resolves against the TextMap tables --
the same hash mechanism that resolves node names -- so the tree comes out with
readable Chinese category names rather than opaque ids.

The rendered tree is a candidate reconstruction; current UI category semantics
require separate verification.

Scope and status: the field->meaning mapping below (field 1 = index, field 2 =
children, field 3/4 = name hash) is a hypothesis about a historical file schema,
inferred from shapes present in the decoded samples and from TextMap hit rates.
It is format-level reasoning, not a verified or officially accepted semantic
reading, and it is not a statement about the currently installed live build.

Inputs come only from an explicit --decoded directory produced by
decode-mihoyobin.py, and the decoder's provenance is checked (source-set id,
per-file hashes, successful decode) before anything is read. Output paths must
not already exist; a provenance sidecar is written next to each output.

Read-only. Writes only the files named on the command line.

Usage:
    python build-category-tree.py --decoded DIR --out FILE [--lang CHS]
                                  [--beyond-global FILENAME]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog_inputs import (  # noqa: E402
    CatalogError,
    check_output_paths,
    exclusive_write_text,
    load_provenance,
    manifest_sha256,
    resolve,
    select_decoded_entries,
    sha256_file,
)


def load_textmap(files) -> dict[int, str]:
    tm: dict[int, str] = {}
    for f in files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        for rec in doc.get("fields", []):
            if rec["f"] != 2 or "m" not in rec:
                continue
            h = t = None
            for s in rec["m"]:
                if s["f"] == 2 and "v" in s:
                    h = s["v"]
                elif s["f"] == 3 and "s" in s:
                    t = s["s"]
            if h is not None and t is not None:
                tm[h] = t
    return tm


def node_shape(fields):
    """Classify a message as a tree node, or as a wrapper to descend through.

    Branch node: index in field 1, children as repeated field 2, name hash in field 4.
    Leaf node:   name hash in field 3 (optionally an index in field 1).
    Anything else is a wrapper -- the top of the file is nested two deep before
    the first real node appears -- so it is descended into rather than emitted.
    """
    idx = h1 = h3 = h4 = None
    children = []
    for r in fields:
        if r["f"] == 1 and "v" in r:
            h1 = r["v"]
        elif r["f"] == 3 and "v" in r:
            h3 = r["v"]
        elif r["f"] == 4 and "v" in r:
            h4 = r["v"]
        elif r["f"] == 2 and "m" in r:
            children.append(r["m"])
    if h4 is not None and (children or h1 is not None):
        return ("branch", h1, h4, children)
    if h3 is not None and not children:
        return ("leaf", h1, h3, [])
    return ("wrapper", None, None, [r["m"] for r in fields if "m" in r])


def render(fields, tm, depth, out):
    kind, idx, name_hash, children = node_shape(fields)
    if kind == "wrapper":
        for c in children:
            render(c, tm, depth, out)
        return
    name = tm.get(name_hash)
    label = "分类" if kind == "branch" else "条目"
    out.append(
        "  " * depth
        + f"- [{label}] {name or '(未解析)'}"
        + f"   [idx={idx} hash={name_hash}]"
    )
    for c in children:
        render(c, tm, depth + 1, out)


def pick_beyond_global(decoded: Path, prov: dict, explicit: str | None) -> str:
    known = {r.get("output") for r in prov["files"] if isinstance(r, dict)}
    if explicit:
        if "/" in explicit or "\\" in explicit or explicit in ("", ".", ".."):
            raise CatalogError("--beyond-global must be a plain filename inside --decoded")
        candidates = [decoded / explicit]
    else:
        candidates = sorted(decoded.glob("Beyond__BeyondGlobal__*.json"))
    candidates = [c for c in candidates if c.name in known]
    if len(candidates) != 1:
        raise CatalogError(
            "expected exactly one decoded BeyondGlobal sample, found "
            f"{len(candidates)}: {[c.name for c in candidates]}"
        )
    return candidates[0].name


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decoded", required=True, help="directory produced by decode-mihoyobin.py --out")
    ap.add_argument("--lang", default="CHS")
    ap.add_argument("--out", required=True, help="markdown output file (must not exist)")
    ap.add_argument("--beyond-global", default=None, help="explicit decoded sample filename")
    args = ap.parse_args()

    try:
        decoded = resolve(args.decoded)
        prov = load_provenance(decoded)
        check_output_paths([args.out, (str(args.out) + ".provenance.json") if args.out else None], decoded, prov)

        bg_name = pick_beyond_global(decoded, prov, args.beyond_global)
        bg_rec = select_decoded_entries(
            prov, decoded, lambda r: r.get("output") == bg_name, "BeyondGlobal"
        )[0]

        tm_records = select_decoded_entries(
            prov,
            decoded,
            lambda r: str(r.get("output", "")).startswith(f"TextMap__{args.lang}__"),
            f"TextMap[{args.lang}]",
        )
        tm = load_textmap([decoded / r["output"] for r in tm_records])
        if not tm:
            raise CatalogError(
                f"TextMap[{args.lang}] resolved to zero hashes; refusing to emit a nameless tree"
            )

        doc = json.loads((decoded / bg_name).read_text(encoding="utf-8"))
        roots = [r["m"] for r in doc.get("fields", []) if r["f"] == 1 and "m" in r]
        if not roots:
            raise CatalogError("BeyondGlobal has no field-1 roots; unknown tree shape")

        out: list[str] = ["# 编辑器节点分类树（BeyondGlobal 还原）", ""]
        for r in roots:
            render(r, tm, 0, out)

        # Report resolution quality rather than hiding misses.
        resolved = sum(1 for line in out if "(未解析)" not in line and line.startswith(("-", "  ")))
        unresolved = sum(1 for line in out if "(未解析)" in line)
        total = resolved + unresolved
        if total == 0:
            raise CatalogError("BeyondGlobal produced zero category nodes; unknown tree shape")
        if resolved == 0:
            raise CatalogError(
                f"zero of {total} category names resolved against TextMap[{args.lang}]; refusing"
            )
        out.insert(2, f"共 {resolved + unresolved} 个分类节点，已解析 {resolved} 个，未解析 {unresolved} 个。")
        out.insert(3, "")
        out.insert(4, "基于历史字段映射的候选分类；仅核验资源格式与名称命中，尚未验收当前编辑器语义。")
        out.insert(5, "")

        out_path = exclusive_write_text(args.out, "\n".join(out))

        sidecar = {
            "tool": "build-category-tree.py",
            "schema_version": 1,
                "interpretation_status": "historical-schema-hypothesis; format-only; live-semantics-unverified",
            "source_set_id": prov["source_set_sha256"],
            "decoded_manifest_sha256": manifest_sha256(decoded),
            "decoded_dir": str(decoded),
            "selected_inputs": [
                {
                    "source_relative_path": r["source_relative_path"],
                    "source_sha256": r["source_sha256"],
                }
                for r in tm_records + [bg_rec]
            ],
            "output": str(out_path),
            "output_sha256": sha256_file(out_path),
            "counts": {"nodes": total, "resolved": resolved, "unresolved": unresolved},
            "coverage": {"name_hit_rate": resolved / total},
        }
        exclusive_write_text(
            Path(str(out_path) + ".provenance.json"),
            json.dumps(sidecar, ensure_ascii=False, indent=1),
            "provenance sidecar",
        )
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        print(f"error: malformed decoded input: {exc}", file=sys.stderr)
        return 1

    print(f"category nodes={total} resolved={resolved} unresolved={unresolved} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
