#!/usr/bin/env python3
"""Group the recovered editor string literals into readable buckets.

Input is the decoded string table (offset -> text) produced while annotating the
decompiled sources. Path-like, constant-like and message-like strings are
separated because they answer different questions: paths show where the editor
reads and writes, constants show configuration keys, messages show behaviour and
failure modes.

Bounds
------
A table is only consumed together with the ``.source.json`` written by
``string_table.py extract``.  Both paths are explicit -- no implicit ``.runtime``
default -- and before anything is written the pair must agree:

  * the sidecar names a *known* source build (``string_table.PROFILES``),
  * the JSON rebuilds *exactly* the declared ``tableSha256`` (via
    ``parse_table_json`` + ``plaintext_from_table``), so a truncated, reordered
    or hand-edited table is refused, not summarised,
  * the rebuilt plaintext matches the profile's own plaintext SHA-256, anchors
    and entry count, so a table from another build cannot be passed off,
  * the table is non-empty.

The output and its sidecar must be new, must not overlap the table or its
sidecar, and the sidecar propagates the source build identity plus the SHA-256 of
the exact bytes written.

Usage:
    python categorize-strings.py --table FILE --out FILE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import string_table as st  # noqa: E402
from catalog_inputs import (  # noqa: E402
    CatalogError,
    ensure_absent,
    ensure_no_overlap,
    exclusive_write_text,
    resolve,
    sha256_file,
)

SLASHES = ("/", "\\")
CONST_RE = re.compile(r"[A-Z][A-Z0-9_]{6,}")
SHA_RE = re.compile(r"[0-9a-f]{64}")


def load_verified_table(table_path: Path) -> tuple[dict[int, str], st.Profile, str, str]:
    """Load a table JSON and re-prove it against its sidecar and its profile.

    Returns ``(table, profile, source_sha256, table_sha256)``.  The declared hash
    is recomputed from the JSON rather than trusted, so the sidecar and the table
    must both be intact for this to return.
    """
    if not table_path.is_file():
        raise CatalogError(f"--table not found: {table_path}")
    sidecar_path = Path(str(table_path) + ".source.json")
    if not sidecar_path.is_file():
        raise CatalogError(
            f"--table has no .source.json sidecar: {sidecar_path}; an unversioned "
            "table is refused (run `string_table.py extract` first)"
        )
    try:
        meta = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"table sidecar is malformed: {exc}") from exc
    if not isinstance(meta, dict):
        raise CatalogError("table sidecar is not a JSON object")

    source_sha = str(meta.get("sourceSha256", "")).lower()
    if not SHA_RE.fullmatch(source_sha):
        raise CatalogError("table sidecar has no valid sourceSha256")
    profile = st.PROFILES.get(source_sha)
    if profile is None:
        raise CatalogError(f"unknown source profile for table build {source_sha}")

    declared = str(meta.get("tableSha256", "")).lower()
    if not SHA_RE.fullmatch(declared):
        raise CatalogError("table sidecar carries no valid tableSha256")

    try:
        raw = json.loads(table_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"--table is malformed JSON: {exc}") from exc

    table = st.parse_table_json(raw)  # strict: gaps, dupes and bad types raise
    if not table:
        raise CatalogError("string table is empty; nothing to categorize")

    rebuilt = st.plaintext_from_table(table)
    actual = hashlib.sha256(rebuilt).hexdigest()
    if actual != declared:
        raise CatalogError(
            "table JSON does not reproduce its declared tableSha256 "
            f"(declared {declared}, rebuilt {actual}); truncated or edited table"
        )
    if profile.plaintext_sha256 and actual != profile.plaintext_sha256:
        raise CatalogError(
            f"table plaintext does not match profile {profile.label} "
            f"(expected {profile.plaintext_sha256}, got {actual}); cross-build table"
        )
    declared_count = meta.get("entryCount")
    if isinstance(declared_count, int) and declared_count != len(table):
        raise CatalogError(
            f"table entry count {len(table)} != sidecar entryCount {declared_count}"
        )
    if profile.entry_count is not None and len(table) != profile.entry_count:
        raise CatalogError(
            f"table entry count {len(table)} != profile expectation {profile.entry_count}"
        )
    for offset, expected in profile.anchors:
        if table.get(offset) != expected:
            raise CatalogError(
                f"table anchor offset {offset} is {table.get(offset)!r}, "
                f"expected {expected!r}"
            )
    return table, profile, source_sha, declared


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", required=True, help="versioned table JSON from string_table.py")
    ap.add_argument("--out", required=True, help="category listing (must not exist)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        table_path = resolve(args.table)
        table, profile, source_sha, table_sha = load_verified_table(table_path)

        out_path = ensure_absent(args.out)
        ensure_no_overlap(table_path, out_path, "--table", "--out")
        ensure_no_overlap(
            Path(str(table_path) + ".source.json"), out_path, "table sidecar", "--out"
        )
        sidecar_path = ensure_absent(str(out_path) + ".source.json")
        ensure_no_overlap(table_path, sidecar_path, "--table", "output sidecar")
        ensure_no_overlap(out_path, sidecar_path, "--out", "output sidecar")
    except (CatalogError, st.VerificationError, OSError, UnicodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    vals = sorted(set(table.values()))
    paths = [v for v in vals if any(s in v for s in SLASHES) and " " not in v]
    consts = [v for v in vals if CONST_RE.fullmatch(v) and not v.startswith("UI_")]
    ui = [v for v in vals if v.startswith("UI_")]
    rest = [v for v in vals if v not in set(paths) | set(consts) | set(ui)]

    lines: list[str] = []
    for title, items, cap in (
        ("PATHS", paths, 0),
        ("CONSTANT-LIKE KEYS", consts, 0),
        ("MESSAGES / OTHER", rest, 0),
        ("UI_ KEYS", ui, 400),
    ):
        shown = items if cap == 0 else items[:cap]
        lines.append(f"### {title}  (total {len(items)}, showing {len(shown)})")
        lines.extend(shown)
        lines.append("")

    try:
        out = exclusive_write_text(args.out, "\n".join(lines))
        exclusive_write_text(
            Path(str(out) + ".source.json"),
            json.dumps(
                {
                    "tool": "categorize-strings.py",
                    "schema_version": 1,
                    "annotationOnly": True,
                    "liveAdapterCompatible": False,
                    "tablePath": str(table_path),
                    "tableSha256": table_sha,
                    "sourceSha256": source_sha,
                    "profile": profile.label,
                    "entryCount": len(table),
                    "counts": {
                        "paths": len(paths),
                        "consts": len(consts),
                        "ui": len(ui),
                        "other": len(rest),
                        "distinct": len(vals),
                    },
                    "output": str(out),
                    "outputSha256": sha256_file(out),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "output sidecar",
        )
    except (CatalogError, st.VerificationError, OSError, UnicodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(f"paths={len(paths)} consts={len(consts)} ui={len(ui)} other={len(rest)} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
