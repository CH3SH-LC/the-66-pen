#!/usr/bin/env python3
"""Summarise the decoded .mihoyobin index produced by decode-mihoyobin.py.

Reads the JSONL index (one record per resource file) and reports, per resource
directory: file count, the top-level protobuf field numbers actually used, and the
string literals found inside. This is what turns thousands of opaque files into a
readable inventory of what the editor can express.

The summary refuses to succeed silently: an empty index, a malformed line, a
failed decode record, a missing/short sha field, or a record whose source-set id
does not match the decoder provenance is reported and exits nonzero. Counts
include the failures.

Category grouping prefers each record's ``source_relative_path`` (so an explicit
decode root lays out correctly) and falls back to the older absolute-path
"/Json/" split when that field is absent.

Usage:
    python summarize-catalog.py <index.jsonl> [--provenance FILE]
                                [--category SUBSTR] [--strings] [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog_inputs import DECODER_TOOL, CatalogError, resolve, sha256_file, validate_provenance  # noqa: E402


def category_of(path: str) -> str:
    """Legacy grouping: split on the first '/Json/' segment."""
    p = path.replace("\\", "/")
    if "/Json/" not in p:
        return "(unknown)"
    tail = p.split("/Json/", 1)[1]
    parts = tail.split("/")
    return "/".join(parts[:-1]) or "(root)"


def category_of_entry(entry: dict) -> str:
    rel = entry.get("source_relative_path")
    if isinstance(rel, str) and rel:
        p = rel.replace("\\", "/")
        if "/Json/" in p:
            return category_of(p)
        head = p.rsplit("/", 1)[0] if "/" in p else ""
        return head or "(root)"
    return category_of(entry.get("path", ""))


def load_provenance(path: Path) -> dict:
    if not path.is_file():
        raise CatalogError(
            f"decoder provenance missing: {path}; decode with --index (writes <index>.provenance.json) "
            "or pass --provenance"
        )
    try:
        prov = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"decoder provenance is malformed: {path}: {exc}") from exc
    if not isinstance(prov, dict):
        raise CatalogError(f"decoder provenance is not a JSON object: {path}")
    if prov.get("tool") != DECODER_TOOL:
        raise CatalogError(f"provenance is not from {DECODER_TOOL}: {prov.get('tool')!r}")
    if not isinstance(prov.get("source_set_sha256"), str) or not prov["source_set_sha256"]:
        raise CatalogError("provenance has no usable source_set_sha256")
    validate_provenance(prov)
    return prov


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("index")
    ap.add_argument("--provenance", default=None,
                    help="decoder provenance for this index (default: <index>.provenance.json)")
    ap.add_argument("--category", default=None, help="only this category substring")
    ap.add_argument("--strings", action="store_true", help="dump strings for the category")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    index_path = resolve(args.index)
    try:
        if not index_path.is_file():
            raise CatalogError(f"index not found: {index_path}")
        prov_path = resolve(args.provenance) if args.provenance else Path(str(index_path) + ".provenance.json")
        prov = load_provenance(prov_path)
        sid = prov["source_set_sha256"]
        known_rels = {
            r.get("source_relative_path")
            for r in prov.get("files") or []
            if isinstance(r, dict) and isinstance(r.get("source_relative_path"), str)
        }

        records: list[tuple[int, dict]] = []
        malformed: list[tuple[int, str]] = []
        for lineno, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError as exc:
                malformed.append((lineno, str(exc)))
                continue
            if not isinstance(e, dict):
                malformed.append((lineno, "record is not a JSON object"))
                continue
            records.append((lineno, e))

        if not records:
            # Never silently succeed on an index we could not read: report the
            # malformed lines first, then fail.
            for lineno, msg in malformed:
                print(f"malformed index line {lineno}: {msg}", file=sys.stderr)
            raise CatalogError(f"index has no usable records: {index_path}")

        errors: list[str] = []
        if prov.get("index_sha256") != sha256_file(index_path):
            errors.append("index sha256 missing or mismatch")
        expected_records = {r["source_relative_path"]: r for r in prov["files"]}
        if len(records) != len(expected_records):
            errors.append("index record count differs from provenance")
        seen_rels: dict[str, int] = {}
        cats: dict[str, dict] = collections.defaultdict(
            lambda: {"n": 0, "failed": 0, "skipped": 0, "top": collections.Counter(),
                     "allstr": collections.Counter()}
        )
        for lineno, e in records:
            errs = []
            seen_rel = e.get("source_relative_path")
            if isinstance(seen_rel, str) and seen_rel:
                if seen_rel in seen_rels:
                    errs.append(
                        f"duplicate source_relative_path {seen_rel!r} "
                        f"(already seen at line {seen_rels[seen_rel]})"
                    )
                else:
                    seen_rels[seen_rel] = lineno
            if e.get("source_set_sha256") != sid:
                errs.append(f"source-set id mismatch/missing ({e.get('source_set_sha256')!r} != {sid!r})")
            if not isinstance(e.get("source_sha256"), str) or not e["source_sha256"]:
                errs.append("missing source_sha256")
            if e.get("output") and not isinstance(e.get("decoded_sha256"), str):
                errs.append("missing decoded_sha256")
            rel = e.get("source_relative_path")
            if isinstance(rel, str) and known_rels and rel not in known_rels:
                errs.append("source_relative_path not present in provenance")
            expected = expected_records.get(rel)
            if expected is None or e.get("source_sha256") != expected.get("source_sha256"):
                errs.append("source hash differs from provenance")
            if not e.get("ok"):
                errs.append(f"failed record: {e.get('error')!r}")
            if errs:
                errors.append(f"line {lineno}: " + "; ".join(errs))

            cat = category_of_entry(e)
            if args.category and args.category not in cat:
                continue
            c = cats[cat]
            c["n"] += 1
            if errs:
                c["failed"] += 1
            for f in e.get("top_fields") or []:
                c["top"][f] += 1
            for s in e.get("strings") or []:
                # strings record "path.field\tvalue"
                val = s.split("\t", 1)[1] if "\t" in s else s
                c["allstr"][val] += 1

        if not cats:
            raise CatalogError(
                f"no records matched (records={len(records)}, filter={args.category!r})"
            )
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for cat, c in sorted(cats.items()):
        print(f"### {cat}  files={c['n']}" + (f" failed={c['failed']}" if c["failed"] else ""))
        print(f"    top-level fields: {c['top'].most_common(20)}")
        print(f"    distinct strings: {len(c['allstr'])}")
        if args.strings:
            for s, n in c["allstr"].most_common(args.limit):
                print(f"      [{n:5d}] {s[:160]}")
        print()

    if malformed:
        for lineno, msg in malformed:
            print(f"malformed index line {lineno}: {msg}", file=sys.stderr)
    if errors:
        for msg in errors:
            print(f"bad index record {msg}", file=sys.stderr)
    print(
        f"records={len(records)} malformed={len(malformed)} bad={len(errors)}",
        file=sys.stderr,
    )
    return 1 if (malformed or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
