#!/usr/bin/env python3
"""Annotate decompiled sources with the real target of every method-proxy slot.

The editor rewrites calls into `OwnerType.slotField` proxies. `resolve-proxy.py`
recovers the slot -> real-method mapping (34,728 entries). This script applies that
mapping to the decompiled C# so the sources become searchable by real method name:

    VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf /* -> ... */ ...
    Producer.mCglXsi0ijgrwvs0SPGh.snthqqZ3HCR /* -> tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh::Ikci0qkvMZX */

Only the fully-qualified `Owner.Field` pairs that actually appear in the map are
rewritten, and unannotated text is preserved byte-for-byte, so nothing is invented.

Bounds
------
  * ``--map`` is explicit and required.  Its ``.source.json`` sidecar must record
    ``tokenValidationPassed: true`` and a *known* source build SHA-256, and every
    row must be a well-formed ``owner.field`` + ``type``/``method`` pair with a
    unique slot.  A partial or hand-edited map is refused rather than applied.
  * ``--src`` must carry a ``.source.json`` naming the *same* known build.  Mixing
    an annotated tree from one editor version with a map from another is refused.
  * No guessing: a reference is rewritten only when its exact ``Owner.Field`` is a
    key in the map.  Nothing is inferred from a bare field name, and lexical
    context is honoured -- a reference inside a C# string literal, character
    literal or comment is copied through untouched (the skipping helpers are
    imported from ``annotate-strings.py`` so both tools share one lexer).
  * ``--out`` must be new or an empty directory, must not overlap ``--src`` or
    ``--map``, and must not already hold a sidecar.  An empty input file, or a run
    that rewrites zero references, is a refusal -- never a quiet success.
  * The output sidecar propagates the source build identity and records a hash of
    the whole written tree.

Read-only with respect to the game install: inputs are never modified and the
assembly is never loaded or executed.  The result is a reading aid, not a
buildable or live-usable artifact.

Usage:
    python annotate-proxies.py --src DIR --out DIR --map FILE
"""
from __future__ import annotations

import argparse
import importlib.util
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
    ensure_no_overlap,
    resolve,
    sha256_file,
    source_set_id,
    exclusive_write_text,
)

SHA_RE = re.compile(r"[0-9a-f]{64}")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LEXICAL = None


def _lexical():
    """Load ``annotate-strings.py`` once, for its C# string/comment/char skipping.

    Reusing that lexer instead of re-implementing it keeps the two annotation
    passes consistent about what counts as code and what counts as text.
    """
    global _LEXICAL
    if _LEXICAL is None:
        spec = importlib.util.spec_from_file_location(
            "annotate_strings_lexical", TOOL_DIR / "annotate-strings.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEXICAL = module
    return _LEXICAL


def _read_json(path) -> object | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ident_path(name: str) -> bool:
    return bool(name) and all(IDENT_RE.fullmatch(part) for part in name.split("."))


def load_map(map_path: Path) -> tuple[dict[str, dict[str, tuple[str, str]]], str]:
    """Validate the proxy map and group it as ``owner -> field -> (type, method)``."""
    if not map_path.is_file():
        raise CatalogError(f"--map not found: {map_path}")
    sidecar_path = Path(str(map_path) + ".source.json")
    sidecar = _read_json(sidecar_path)
    if not isinstance(sidecar, dict):
        raise CatalogError(
            f"--map has no .source.json sidecar: {sidecar_path}; refusing an "
            "unversioned proxy map"
        )
    if sidecar.get("tokenValidationPassed") is not True:
        raise CatalogError(
            "--map sidecar does not record tokenValidationPassed: true; the decoded "
            "map was not token-validated"
        )
    map_sha = str(sidecar.get("sourceSha256", "")).lower()
    if not SHA_RE.fullmatch(map_sha):
        raise CatalogError("--map sidecar has no valid sourceSha256")
    if map_sha not in st.PROFILES:
        raise CatalogError(f"unknown source profile for --map build {map_sha}")

    map_bytes=map_path.read_bytes()
    actual_map_sha=hashlib.sha256(map_bytes).hexdigest()
    if sidecar.get('outputSha256') != actual_map_sha:
        raise CatalogError("--map outputSha256 missing or changed; regenerate the map")
    rows=json.loads(map_bytes.decode('utf-8'))
    if not isinstance(rows, list) or not rows:
        raise CatalogError("--map holds no rows; refusing an empty proxy map")

    if sidecar.get('completeMap') is not True or sidecar.get('outputRows')!=len(rows) or sidecar.get('totalPairs')!=len(rows):
        raise CatalogError("--map must contain the complete token-validated row set")
    by_owner: dict[str, dict[str, tuple[str, str]]] = {}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogError(f"--map row {index} is not an object")
        owner, field = row.get("owner"), row.get("field")
        ttype, method = row.get("type"), row.get("method")
        for name, value in (
            ("owner", owner),
            ("field", field),
            ("type", ttype),
            ("method", method),
        ):
            if not isinstance(value, str) or not value:
                raise CatalogError(f"--map row {index} has no usable {name}")
        if not _ident_path(owner) or IDENT_RE.fullmatch(field) is None:
            raise CatalogError(
                f"--map row {index} has a non-identifier owner.field: {owner}.{field}"
            )
        slot = f"{owner}.{field}"
        if row.get("slot") != slot:
            raise CatalogError(
                f"--map row {index} slot {row.get('slot')!r} does not identify {slot!r}"
            )
        if slot in seen:
            raise CatalogError(f"--map has a duplicate slot: {slot}")
        seen.add(slot)
        by_owner.setdefault(owner, {})[field] = (ttype, method)
    return by_owner, map_sha, actual_map_sha


def read_source_identity(src: Path) -> tuple[str, dict]:
    """Require a ``.source.json`` naming a known source build."""
    meta = _read_json(src / ".source.json")
    if not isinstance(meta, dict):
        raise CatalogError(f"--src has no .source.json: {src / '.source.json'}")
    sha = str(meta.get("sourceSha256", "")).lower()
    if not SHA_RE.fullmatch(sha):
        raise CatalogError("--src/.source.json has no valid sourceSha256")
    if sha not in st.PROFILES:
        raise CatalogError(f"unknown source profile for --src build {sha}")
    return sha, meta


DOT_CHAIN_RE=re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def referenced_owners(text, by_owner):
    """Find only owners that can reach the exact reference matcher in this text."""
    found=set()
    for match in DOT_CHAIN_RE.finditer(text):
        parts=match.group(0).split('.')
        for length in range(1,len(parts)):
            candidate='.'.join(parts[:length])
            if candidate in by_owner:
                found.add(candidate)
    return sorted(found,key=lambda value:(-len(value),value))


def build_matcher(owners: list[str]) -> re.Pattern[str]:
    """One alternation over the owners this file actually mentions.

    Longer owner names come first so a namespaced owner wins over a shorter one
    that happens to be its suffix.  The property guard stops a match from starting
    inside a longer identifier or after a dot.
    """
    alternation = "|".join(re.escape(owner) for owner in owners)
    return re.compile(
        r'(?P<dq>")|(?P<sq>\')|(?P<slash>/)'
        r"|(?P<ref>(?<![\w.])(?:" + alternation + r")\.[A-Za-z_]\w*)"
    )


def annotate_text(
    text: str,
    matcher: re.Pattern[str],
    by_owner: dict[str, dict[str, tuple[str, str]]],
    lexical,
) -> tuple[str, int]:
    """Rewrite mapped ``Owner.Field`` references in one source text.

    Returns ``(new_text, replacements)``.  Text inside string/char literals and
    comments is copied verbatim, and an ``Owner.Field`` that is not an exact map
    key is left alone.
    """
    out: list[str] = []
    replaced = 0
    pos = 0
    while True:
        match = matcher.search(text, pos)
        if match is None:
            out.append(text[pos:])
            break
        out.append(text[pos : match.start()])

        if match.group("ref") is not None:
            owner, field = match.group("ref").rsplit(".", 1)
            target = by_owner.get(owner, {}).get(field)
            if target is None:  # never guess a target that the map does not name
                out.append(match.group(0))
                pos = match.end()
                continue
            ttype, method = target
            out.append(f"{match.group(0)} /* -> {ttype}::{method} */")
            replaced += 1
            pos = match.end()
            continue

        # A string, char or comment starts here: copy it through untouched.
        if match.group("dq") is not None:
            end = lexical._skip_string(text, match.start())
        elif match.group("sq") is not None:
            end = lexical._skip_char(text, match.start())
        else:
            end = lexical._skip_slash(text, match.start())
        out.append(text[match.start() : end])
        pos = end

    return "".join(out), replaced


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", required=True, help="decompiled .cs tree (.source.json)")
    ap.add_argument("--out", required=True, help="annotated copy destination")
    ap.add_argument("--map", required=True, help="proxy map JSON from resolve-proxy.py --all")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    try:
        src = resolve(args.src)
        out = resolve(args.out)
        map_path = resolve(args.map)
        if not src.is_dir():
            raise CatalogError(f"--src is not a directory: {src}")

        by_owner, map_sha, map_content_sha = load_map(map_path)
        source_sha, source_meta = read_source_identity(src)
        if source_sha != map_sha:
            raise CatalogError(
                f"cross-build annotation refused: --src is {source_sha} but --map is "
                f"{map_sha}"
            )
        ensure_no_overlap(src, out, "--src", "--out")
        ensure_no_overlap(map_path, out, "--map", "--out")
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise CatalogError("--out already contains files; use a new output path")

        files = sorted(src.rglob("*.cs"))
        if not files:
            raise CatalogError(f"no .cs files under --src: {src}")
        empty = [f for f in files if f.stat().st_size == 0]
        if empty:
            raise CatalogError(f"empty source file: {empty[0]}; refusing a partial tree")
    except (CatalogError, OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    lexical = _lexical()

    # Pass 1: count only, so a run with nothing to rewrite writes nothing.
    total = 0
    input_hashes={}
    source_meta_sha=sha256_file(src/'.source.json')
    for path in files:
        text = lexical._read_text(path)
        input_hashes[path.relative_to(src).as_posix()]=lexical._sha256_of_text(text)
        owners = referenced_owners(text,by_owner)
        if not owners:
            continue
        _annotated, count = annotate_text(
            text, build_matcher(owners), by_owner, lexical
        )
        total += count
    if source_meta.get('outputSetSha256')!=source_set_id(input_hashes.items()):
        print("refused: source tree hash missing or changed; regenerate annotated inputs",file=sys.stderr)
        return 2
    if total == 0:
        print(
            "refused: zero proxy references annotated; refusing to report an "
            "annotation with no real replacements",
            file=sys.stderr,
        )
        return 2

    written: list[tuple[Path, Path]] = []
    try:
        for path in files:
            text = lexical._read_text(path)
            if lexical._sha256_of_text(text)!=input_hashes[path.relative_to(src).as_posix()]:
                raise CatalogError("source changed between annotation passes")
            owners = referenced_owners(text,by_owner)
            annotated = text
            if owners:
                annotated, _count = annotate_text(
                    text, build_matcher(owners), by_owner, lexical
                )
            dest = out / path.relative_to(src)
            dest.parent.mkdir(parents=True, exist_ok=True)
            lexical._write_text(dest, annotated)
            written.append((dest, path.relative_to(src)))

        if sorted(src.rglob('*.cs'))!=files or sha256_file(src/'.source.json')!=source_meta_sha or sha256_file(map_path)!=map_content_sha:
            raise CatalogError("source file set, identity or proxy map changed during annotation")
        pairs = [(rel.as_posix(), sha256_file(dest)) for dest, rel in written]
        exclusive_write_text(
            out / ".source.json",
            json.dumps(
                {
                    "tool": "annotate-proxies.py",
                    "schema_version": 1,
                    "annotationOnly": True,
                    "liveAdapterCompatible": False,
                    "sourceDir": str(src),
                    "sourceSha256": source_sha,
                    "sourceWasAnnotated": source_meta.get("annotationOnly") is True,
                    "profile": st.PROFILES[source_sha].label,
                    "proxyMap": str(map_path),
                    "proxyMapSha256": map_content_sha,
                    "inputSetSha256":source_set_id(input_hashes.items()),
                    "inputCompleteness":source_meta.get('inputCompleteness',{'complete':None,'reason':'not recorded by producer'}),
                    "filesScanned": len(files),
                    "referencesAnnotated": total,
                    "outputSetSha256": source_set_id(pairs),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "output sidecar",
        )
    except (CatalogError, OSError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(f"files={len(files)} slot references annotated={total} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
