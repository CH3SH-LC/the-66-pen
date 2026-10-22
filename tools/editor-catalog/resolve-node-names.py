#!/usr/bin/env python3
"""Resolve editor resource IDs to human names via the TextMap tables.

TextMap/<LANG> decodes to repeated {key:string, hash:uint32, text:string} entries.
Node resources carry two uint32 fields (206, 207) that are candidates for those
hashes. This script tests that hypothesis against the real data and reports the
match rate rather than assuming it -- an unmatched value is left unmatched and
never guessed.

The hypothesis itself is a historical-schema reading of decoded samples: it is
format-level and may be wrong, and it is not a claim of official or live-build
semantic acceptance.

Inputs come only from an explicit --decoded directory produced by
decode-mihoyobin.py, whose provenance (source-set id, per-file hashes,
successful decode) is verified before consumption. When --out is given it must
not already exist, and a provenance sidecar is written next to it; without --out
the rows go to stdout and no sidecar is produced.

Usage:
    python resolve-node-names.py --decoded DIR [--lang CHS] [--out FILE]
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


def load_textmap(files) -> tuple[dict[int, str], dict[str, str]]:
    by_hash: dict[int, str] = {}
    by_key: dict[str, str] = {}
    for f in files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        for rec in doc.get("fields", []):
            if rec["f"] != 2 or "m" not in rec:
                continue
            key = hash_ = text = None
            for sub in rec["m"]:
                if sub["f"] == 1 and "s" in sub:
                    key = sub["s"]
                elif sub["f"] == 2 and "v" in sub:
                    hash_ = sub["v"]
                elif sub["f"] == 3 and "s" in sub:
                    text = sub["s"]
            if hash_ is not None and text is not None:
                by_hash[hash_] = text
            if key is not None and text is not None:
                by_key[key] = text
    return by_hash, by_key


def node_fields(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict = {"file": path.name, "size": doc["size"]}
    for rec in doc.get("fields", []):
        if rec["f"] in (203, 204, 205, 206, 207) and "v" in rec:
            out[rec["f"]] = rec["v"]
        if rec["f"] == 4 and "m" in rec:
            out["cat"] = rec["m"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decoded", required=True, help="directory produced by decode-mihoyobin.py --out")
    ap.add_argument("--lang", default="CHS")
    ap.add_argument("--out", default=None, help="JSON rows output file (must not exist)")
    args = ap.parse_args()

    try:
        decoded = resolve(args.decoded)
        prov = load_provenance(decoded)
        check_output_paths([args.out, (str(args.out) + ".provenance.json") if args.out else None], decoded, prov)

        node_records = select_decoded_entries(
            prov, decoded, lambda r: str(r.get("output", "")).startswith("Beyond__Node__"),
            "Beyond__Node__",
        )
        tm_records = select_decoded_entries(
            prov,
            decoded,
            lambda r: str(r.get("output", "")).startswith(f"TextMap__{args.lang}__"),
            f"TextMap[{args.lang}]",
        )
        by_hash, by_key = load_textmap([decoded / r["output"] for r in tm_records])
        if not by_hash and not by_key:
            raise CatalogError(f"TextMap[{args.lang}] is empty; nothing to resolve against")

        nodes = sorted(decoded / r["output"] for r in node_records)
        hit206 = hit207 = neither = 0
        rows = []
        for n in nodes:
            nf = node_fields(n)
            n206, n207 = nf.get(206), nf.get(207)
            t206 = by_hash.get(n206) if n206 is not None else None
            t207 = by_hash.get(n207) if n207 is not None else None
            if t206:
                hit206 += 1
            if t207:
                hit207 += 1
            if not t206 and not t207:
                neither += 1
            rows.append(
                {
                    "file": n.name,
                    "name": n.name.split("__")[-1].replace(".mihoyobin.json", ""),
                    "f203": nf.get(203),
                    "f204": nf.get(204),
                    "f205": nf.get(205),
                    "f206": n206,
                    "f207": n207,
                    "text206": t206,
                    "text207": t207,
                }
            )

        if hit206 == 0 and hit207 == 0:
            raise CatalogError(
                f"zero of {len(rows)} nodes resolved against TextMap[{args.lang}]; refusing"
            )
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        print(f"error: malformed decoded input: {exc}", file=sys.stderr)
        return 1

    print(f"TextMap[{args.lang}]: {len(by_hash)} hashes, {len(by_key)} keys")
    print(f"nodes={len(nodes)} f206-resolved={hit206} f207-resolved={hit207} unresolved={neither}")
    for r in rows[:15]:
        print(f"  {r['name']:>22}  f206={r['f206']} -> {r['text206']!r}   f207={r['f207']} -> {r['text207']!r}")

    if args.out:
        try:
            out_path = exclusive_write_text(
                args.out, json.dumps(rows, ensure_ascii=False, indent=1)
            )
            sidecar = {
                "tool": "resolve-node-names.py",
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
                    for r in node_records + tm_records
                ],
                "output": str(out_path),
                "output_sha256": sha256_file(out_path),
                "counts": {
                    "nodes": len(rows),
                    "f206_resolved": hit206,
                    "f207_resolved": hit207,
                    "unresolved": neither,
                },
                "coverage": {"any_name_hit_rate": (len(rows) - neither) / len(rows)},
            }
            exclusive_write_text(
                Path(str(out_path) + ".provenance.json"),
                json.dumps(sidecar, ensure_ascii=False, indent=1),
                "provenance sidecar",
            )
            print(f"wrote {out_path}")
        except CatalogError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
