#!/usr/bin/env python3
"""Index decompiled (and string-annotated) types by the literals they contain.

Every type in the editor assembly has a random name, so symbol names carry no
meaning. But the string literals recovered from the string table do: a type that
mentions "Resource\\Json\\Beyond\\Node" is about node resources, one that mentions
UI_BEYOND_ASSIST_EDITOR_BLUEPRINT_SAVE is about saving blueprints.

This script turns that into a searchable index: type -> literals, plus a reverse
index literal -> types. It is the basis for tagging anonymous types with a
subsystem, which is what makes an interface inventory possible at all.

Bounds
------
  * ``--src`` must be a tree carrying a ``.source.json`` that names a *known*
    source build (``string_table.PROFILES``) and records ``annotationOnly: true``
    -- i.e. the output of ``annotate-strings.py``.  An un-annotated decomp of an
    unknown build would silently index zero literals and look like a real result,
    so it is refused instead.
  * Every output path is explicit.  There is no implicit ``.runtime`` location
    and no hardcoded reverse-index path: the three outputs (``--json``, ``--tsv``,
    ``--reverse``) and their ``.source.json`` sidecars must all be new, must not
    overlap each other and must not sit inside ``--src``.
  * A run that finds no input files, or recovers no literal at all, is refused
    rather than reported as a success.
  * Each output gets a sidecar carrying the source build identity and the
    SHA-256 of the exact bytes written, so a consumer can pin the input.

Read-only with respect to the game install: inputs are never modified and the
assembly is never loaded or executed. The output is a reading aid derived from an
annotation-only copy, not a buildable or live-usable artifact.

Usage:
    python index-types.py --src DIR --json FILE --tsv FILE --reverse FILE
"""
from __future__ import annotations

import argparse
import json
import hashlib
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
    source_set_id,
)

# Literal as written by annotate-strings.py; the trailing comment is the contract
# between the two tools, so it is matched -- and nothing else is.
LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"\s*/\* string (\d+) \*/')
SHA_RE = re.compile(r"[0-9a-f]{64}")


def source_identity(src: Path) -> tuple[str, st.Profile, dict]:
    """Require an annotated ``.source.json`` naming a known source build."""
    meta_path = src / ".source.json"
    if not meta_path.is_file():
        raise CatalogError(
            f"--src has no .source.json: {meta_path}; refusing to index a decomp "
            "of unknown build (run annotate-strings.py --out first)"
        )
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"--src/.source.json is malformed: {exc}") from exc
    if not isinstance(meta, dict):
        raise CatalogError("--src/.source.json is not a JSON object")
    if meta.get("annotationOnly") is not True:
        raise CatalogError(
            "--src is not an annotated string copy (annotationOnly is not true); "
            "run annotate-strings.py --out first"
        )
    sha = str(meta.get("sourceSha256", "")).lower()
    if not SHA_RE.fullmatch(sha):
        raise CatalogError("--src/.source.json has no valid sourceSha256")
    profile = st.PROFILES.get(sha)
    if profile is None:
        raise CatalogError(f"unknown source profile for --src build {sha}")
    return sha, profile, meta


def ensure_fresh_outputs(outputs, inputs) -> list[Path]:
    """Refuse existing outputs, input/output overlap and output/output overlap.

    ``inputs`` is a sequence of ``(path, label)``.  Paths that are equal overlap
    each other, so a repeated output is refused here too.
    """
    resolved: list[tuple[Path, str]] = []
    for path in outputs:
        p = ensure_absent(path)
        for src, label in inputs:
            ensure_no_overlap(src, p, label, "output")
        for prior, prior_label in resolved:
            ensure_no_overlap(prior, p, prior_label, "output")
        resolved.append((p, str(path)))
    return [p for p, _ in resolved]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="annotated .cs tree (.source.json)")
    ap.add_argument("--json", required=True, help="type -> literals JSON (must not exist)")
    ap.add_argument("--tsv", required=True, help="type -> literals TSV (must not exist)")
    ap.add_argument("--reverse", required=True, help="literal -> types JSON (must not exist)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        src = resolve(args.src)
        if not src.is_dir():
            raise CatalogError(f"--src is not a directory: {src}")
        source_sha, profile, source_meta = source_identity(src)

        files = sorted(src.rglob("*.cs"))
        if not files:
            raise CatalogError(f"no .cs files under --src: {src}")

        declared = [args.json, args.tsv, args.reverse]
        # Sidecars are written too, so they take part in the same guards.
        ensure_fresh_outputs(
            declared + [str(path) + ".source.json" for path in declared],
            [(src, "--src")],
        )
    except CatalogError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    # Keep namespace-relative identity when several directories contain the same name.
    names = {}
    for path in files:
        names[path.stem] = names.get(path.stem, 0) + 1
    types: dict[str, list[str]] = {}
    input_pairs = []
    for f in files:
        data=f.read_bytes()
        try:
            text=data.decode("utf-8")
        except UnicodeDecodeError as exc:
            print(f"refused: invalid UTF-8 source {f}: {exc}", file=sys.stderr)
            return 2
        input_pairs.append((f.relative_to(src).as_posix(), hashlib.sha256(data).hexdigest()))
        lits = sorted({m.group(1) for m in LITERAL.finditer(text)})
        if lits:
            identity = f.stem if names[f.stem] == 1 else f.relative_to(src).with_suffix("").as_posix()
            types[identity] = lits
    actual_input_hash=source_set_id(input_pairs)
    if source_meta.get('outputSetSha256') != actual_input_hash:
        print("refused: source tree hash missing or changed; regenerate annotated inputs",file=sys.stderr)
        return 2
    if not types:
        print(
            f"refused: no recovered literals in {len(files)} .cs files under --src; "
            "refusing to write an empty index",
            file=sys.stderr,
        )
        return 2

    rev: dict[str, list[str]] = {}
    for t, lits in types.items():
        for s in lits:
            rev.setdefault(s, []).append(t)

    try:
        json_path = exclusive_write_text(
            args.json, json.dumps(types, ensure_ascii=False, indent=0)
        )
        tsv_path = exclusive_write_text(
            args.tsv,
            "".join(t + "\t" + " | ".join(lits) + "\n" for t, lits in sorted(types.items())),
        )
        rev_path = exclusive_write_text(
            args.reverse, json.dumps(rev, ensure_ascii=False, indent=0)
        )
        sidecar_base = {
            "tool": "index-types.py",
            "schema_version": 1,
            "annotationOnly": True,
            "liveAdapterCompatible": False,
            "sourceDir": str(src),
            "sourceSha256": source_sha,
            "profile": profile.label,
            "filesScanned": len(files),
            "typesIndexed": len(types),
            "inputSetSha256": source_set_id(input_pairs),
            "inputCompleteness": source_meta.get("inputCompleteness", {"complete": None, "reason": "not recorded by producer"}),
            "literalsIndexed": len(rev),
        }
        for path in (json_path, tsv_path, rev_path):
            exclusive_write_text(
                Path(str(path) + ".source.json"),
                json.dumps(
                    dict(sidecar_base, output=str(path), outputSha256=sha256_file(path)),
                    ensure_ascii=False,
                    indent=2,
                ),
                "output sidecar",
            )
    except CatalogError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(f"types with recovered literals: {len(types)}")
    print(f"distinct literals indexed: {len(rev)}")
    print(f"wrote {json_path}", file=sys.stderr)
    print(f"wrote {tsv_path}", file=sys.stderr)
    print(f"wrote {rev_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
