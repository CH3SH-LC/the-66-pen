#!/usr/bin/env python3
"""Build the complete node catalogue for the Miliastra editor.

Input: the decoded Resource/Json/Beyond/Node/*.mihoyobin files (after XOR 0xE5),
which are protobuf wire streams, plus the TextMap tables that turn the uint32
hashes they carry into human-readable names.

What is established by evidence, and by what (historical schema hypotheses,
inferred from decoded samples; format-level, not verified against the currently
installed live build and not an official semantic claim):

  * every file under Resource/Json/Beyond/Node decodes with the proven XOR-0xE5
    transform and parses as a complete protobuf wire stream
    (.runtime/verification/resource-file-loader/file-loader.cs, message-reader.cs)
  * top-level field 206 - observed to hit TextMap/CHS at 799/799
  * pin name field 7 inside pin records - observed to carry the same kind of hash
  * pin class: the observed convention is field 100 = 输入执行 pin group,
    101 = 输出执行, 102 = 输入数据, 103 = 输出数据; each pin record's own
    field 3 sub-field 1 carries the same class number, so the two agree

Nothing beyond that is invented. Unknown field numbers are reported as unknown,
and names that do not resolve stay unresolved rather than being guessed.

Inputs come only from an explicit --decoded directory produced by
decode-mihoyobin.py, whose provenance (source-set id, per-file hashes,
successful decode) is verified before consumption. Output paths must not already
exist; a provenance sidecar is written next to --json.

Usage:
    python build-node-catalog.py --decoded DIR --json FILE [--lang CHS] [--md FILE]
"""
from __future__ import annotations

import argparse
import collections
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

# Pin group field number -> (class number, human label). The label is the
# observed editor convention, not an official enum name.
PIN_GROUPS = {
    100: (1, "输入执行"),
    101: (2, "输出执行"),
    102: (3, "输入数据"),
    103: (4, "输出数据"),
    104: (5, "未定-104"),
    106: (7, "未定-106"),
    107: (8, "未定-107"),
    108: (9, "未定-108"),
}


def load_textmap(files) -> dict[int, str]:
    by_hash: dict[int, str] = {}
    for f in files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        for rec in doc.get("fields", []):
            if rec["f"] != 2 or "m" not in rec:
                continue
            h = t = None
            for sub in rec["m"]:
                if sub["f"] == 2 and "v" in sub:
                    h = sub["v"]
                elif sub["f"] == 3 and "s" in sub:
                    t = sub["s"]
            if h is not None and t is not None:
                by_hash[h] = t
    return by_hash


def sub_of(rec: dict, num: int):
    if "m" not in rec:
        return None
    for s in rec["m"]:
        if s["f"] == num:
            return s
    return None


def val_of(rec: dict, num: int):
    s = sub_of(rec, num)
    return s.get("v") if s else None


def clean_pin(rec: dict, tm: dict[int, str]) -> dict:
    """Turn one pin record into {class, index, name, type-hint}."""
    cls = idx = None
    c3 = sub_of(rec, 3)
    if c3 is not None:
        cls = val_of(c3, 1)
        idx = val_of(c3, 2)
    name_hash = val_of(rec, 7)
    out = {
        "class": cls,
        "index": idx,
        "name_hash": name_hash,
        "name": tm.get(name_hash) if name_hash is not None else None,
    }
    # field 4 carries the value type descriptor; field 5 a secondary marker.
    t4 = sub_of(rec, 4)
    if t4 is not None:
        out["type_fields"] = [s["f"] for s in t4.get("m", [])]
        t4f1 = val_of(t4, 1)
        if t4f1 is not None:
            out["type_kind"] = t4f1
    t5 = sub_of(rec, 5)
    if t5 is not None:
        out["marker5"] = val_of(t5, 1)
    out["has_default"] = sub_of(rec, 4) is not None
    return out


def node_id_of(name: str) -> int:
    raw = name.split("__")[-1].replace(".mihoyobin.json", "")
    if not raw.isdigit():
        raise CatalogError(f"decoded node filename does not carry a numeric id: {name}")
    return int(raw)


def build_nodes(node_files, tm: dict[int, str]) -> tuple[list[dict], int]:
    nodes = []
    unresolved_names = 0
    for f in node_files:
        doc = json.loads(Path(f).read_text(encoding="utf-8"))
        entry: dict = {"id": node_id_of(Path(f).name), "pins": []}
        for rec in doc["fields"]:
            fn = rec["f"]
            if fn == 206:
                entry["name"] = tm.get(rec.get("v"))
                entry["name_hash"] = rec.get("v")
            elif fn in (203, 204, 205):
                entry[f"f{fn}"] = rec.get("v")
            elif fn == 4:
                # field 4 carries one or more 4-value category tuples, each nested
                # one message deep: {f:1 -> {1:10001, 2:20000, 3:22000, 5:...}}
                cats = []
                for outer in rec.get("m", []):
                    for inner in outer.get("m", []):
                        cats.append({s["f"]: s.get("v") for s in inner.get("m", [])})
                entry["category"] = cats
                entry["category_outer"] = [s["f"] for s in rec.get("m", [])]
            elif fn in PIN_GROUPS and "m" in rec:
                # One occurrence of a pin-group field IS one pin: its payload is a
                # message whose sub-fields are the pin's own attributes.
                pin = clean_pin(rec, tm)
                pin["group"] = fn
                entry["pins"].append(pin)
            elif fn == 208:
                entry.setdefault("extra208", []).append(rec.get("m"))
            elif fn == 1000:
                entry["oneof1000"] = rec.get("b", "")
            else:
                entry.setdefault("other_fields", []).append(fn)
        if not entry.get("name"):
            unresolved_names += 1
        nodes.append(entry)
    return nodes, unresolved_names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--decoded", required=True, help="directory produced by decode-mihoyobin.py --out")
    ap.add_argument("--lang", default="CHS")
    ap.add_argument("--json", required=True, help="catalogue output file (must not exist)")
    ap.add_argument("--md", default=None, help="optional markdown output file (must not exist)")
    args = ap.parse_args()

    try:
        decoded = resolve(args.decoded)
        prov = load_provenance(decoded)
        check_output_paths([args.json, (str(args.json) + ".provenance.json") if args.json else None, args.md, (str(args.md) + ".provenance.json") if args.md else None], decoded, prov)

        node_records = select_decoded_entries(
            prov, decoded, lambda r: str(r.get("output", "")).startswith("Beyond__Node__"),
            "Beyond__Node__",
        )
        if not node_records:
            raise CatalogError("no decoded Beyond__Node__ samples found")

        tm_records = select_decoded_entries(
            prov,
            decoded,
            lambda r: str(r.get("output", "")).startswith(f"TextMap__{args.lang}__"),
            f"TextMap[{args.lang}]",
        )
        tm = load_textmap([decoded / r["output"] for r in tm_records])
        if not tm:
            raise CatalogError(
                f"TextMap[{args.lang}] resolved to zero hashes; refusing a nameless catalogue"
            )

        node_files = sorted(decoded / r["output"] for r in node_records)
        nodes, unresolved_names = build_nodes(node_files, tm)
        if not nodes:
            raise CatalogError("zero node records decoded; refusing to claim a catalogue")

        named = sum(1 for n in nodes if n.get("name"))
        if named == 0:
            raise CatalogError(
                f"zero of {len(nodes)} node names resolved against TextMap[{args.lang}]; refusing"
            )

    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        print(f"error: malformed decoded input: {exc}", file=sys.stderr)
        return 1

    print(f"TextMap[{args.lang}] hashes: {len(tm)}")
    print(f"nodes={len(nodes)} named={named} unresolved={unresolved_names}")

    pin_named = pin_total = 0
    for n in nodes:
        for p in n["pins"]:
            pin_total += 1
            if p.get("name"):
                pin_named += 1
    print(f"pins={pin_total} named={pin_named} ({100.0*pin_named/max(pin_total,1):.1f}%)")

    # category histogram
    hist = collections.Counter()
    for n in nodes:
        hist[json.dumps(n.get("category"), sort_keys=True)] += 1
    for k, v in hist.most_common():
        print(f"  category {v:5d}  {k}")

    try:
        json_path = exclusive_write_text(
            args.json, json.dumps(nodes, ensure_ascii=False, indent=1)
        )
        print(f"wrote {json_path}")

        if args.md:
            lines = ["# 千星编辑器节点资源目录（候选字段解释）", "", f"节点总数：{len(nodes)}（已解析名称 {named} 个）", "", "基于历史字段映射；仅核验资源格式与名称命中，尚未验收当前编辑器语义。", ""]
            for n in sorted(nodes, key=lambda x: (json.dumps(x.get("category"), sort_keys=True), x.get("name") or "")):
                lines.append(f"## {n.get('name') or '(未命名)'}  `{n['id']}`")
                lines.append("")
                lines.append(f"- 分类：`{json.dumps(n.get('category'), ensure_ascii=False)}`")
                for p in n["pins"]:
                    g = PIN_GROUPS.get(p["group"], (None, "?"))[1]
                    lines.append(f"- [{g}] {p.get('name') or '(无名/执行引脚)'}  class={p.get('class')} idx={p.get('index')}")
                lines.append("")
            print(f"wrote {exclusive_write_text(args.md, '\n'.join(lines))}")

        sidecar = {
            "tool": "build-node-catalog.py",
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
            "output": str(json_path),
            "output_sha256": sha256_file(json_path),
            "counts": {
                "nodes": len(nodes),
                "named": named,
                "unresolved": unresolved_names,
                "pins": pin_total,
                "pins_named": pin_named,
            },
            "coverage": {"name_hit_rate": named / len(nodes)},
        }
        if args.md:
            md_sidecar = dict(sidecar)
            md_sidecar.update(output=str(resolve(args.md)), output_sha256=sha256_file(args.md))
            exclusive_write_text(str(args.md) + ".provenance.json", json.dumps(md_sidecar, ensure_ascii=False, indent=1))
        exclusive_write_text(
            Path(str(json_path) + ".provenance.json"),
            json.dumps(sidecar, ensure_ascii=False, indent=1),
            "provenance sidecar",
        )
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
