#!/usr/bin/env python3
"""Recover the editor's string literals in decompiled source.

The editor assembly is name-obfuscated and its string literals were removed from
the #US heap entirely.  A literal survives only as an int byte-offset into an
encrypted blob, reached through one obfuscated accessor call, e.g.

    PgdJdFPLK4PkoLedWk7c.RcDPXnUGLKY(0x52F599CD ^ 0x52F56847)
    OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(0x52F599CD ^ 0x52F56847,
                                     OfHnbKPAfwDjrwrhrnHS.UuIPAuUcgRX)

This script decodes the table (see ``string_table.py``) and rewrites only those
exact accessor calls whose offset argument is a bounded int literal or two
literals XORed into a real table offset, replacing the whole call with the
escaped C# string literal plus the original offset as a comment.

Deliberate limits
-----------------
  * **Only accessor calls are touched.**  An unrelated ``a ^ b`` anywhere else in
    the source is left byte-for-byte unchanged, even when ``a ^ b`` happens to
    equal a valid table offset.  The previous version matched every XOR literal
    pair in the tree; that is what this rewrite exists to stop.
  * The accessor call shape comes from the pinned profile, selected by the SHA-256
    of the source build.  Both the direct call and the method-proxy call form are
    recognised for the new 7.1 names and for the legacy names.
  * An accessor call whose argument is not a recoverable offset is preserved and
    counted as *unresolved*; it is never guessed at.
  * ``--src`` must carry a ``.source.json`` naming the source build, and the table
    must come from the matching build (a versioned table with its own sidecar, or
    a fresh decode of ``--dll``).  A legacy/new mix is refused, not annotated.
  * Source and output must not be identical or nested, and output directories that
    belong to another build are refused, so a bad invocation cannot run away.

Read-only with respect to the game install: inputs are never modified and the
assembly is never loaded or executed.  Output is an annotated copy, and its
``.source.json`` records ``annotationOnly: true`` / ``liveAdapterCompatible:
false`` -- this produces a reading aid, not a buildable or live-usable artifact.

Usage:
    python annotate-strings.py --src DIR --out DIR --table-json FILE
    python annotate-strings.py --src DIR --out DIR --dll BeyondEditor.dll
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
from catalog_inputs import source_set_id, exclusive_write_text

# --------------------------------------------------------------------------- #
# Offset-expression grammar (bounded int literal, or two literals XORed)        #
# --------------------------------------------------------------------------- #
_INT_LIT = r"-?(?:0[xX][0-9A-Fa-f]{1,8}|[0-9]{1,10})"
_EXPR_CORE = rf"(?:{_INT_LIT}\s*\^\s*{_INT_LIT}|{_INT_LIT})"
_EXPR = _EXPR_CORE
for _ in range(3):  # tolerate redundant parentheses, e.g. ((A ^ B))
    _EXPR = rf"(?:{_EXPR_CORE}|\(\s*{_EXPR}\s*\))"
_EXPR_FULL = re.compile(rf"\s*{_EXPR}\s*")

_CSHARP_SIMPLE = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\a": "\\a",
    "\b": "\\b",
    "\f": "\\f",
    "\v": "\\v",
}


def csharp_literal(value: str) -> str:
    """Render a string as a C# source literal (non-ASCII passes through as-is)."""
    out = []
    for ch in value:
        if ch in _CSHARP_SIMPLE:
            out.append(_CSHARP_SIMPLE[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def resolve_offset(expr: str) -> int | None:
    """Return the int32/XOR offset an expression denotes, or None if not literal.

    Only a single bounded int literal, or exactly two XORed int literals
    (optionally parenthesised), is accepted.  Anything else -- an identifier, a
    sum, a call, three literals -- is "unknown" and resolves to None.
    """
    if _EXPR_FULL.fullmatch(expr) is None:
        return None
    literals = re.findall(_INT_LIT, expr)
    if not 1 <= len(literals) <= 2:
        return None
    values = [int(v, 16 if "x" in v.lower() else 10) for v in literals]
    if any(v < -0x80000000 or v > 0xFFFFFFFF for v in values):
        return None
    value = values[0]
    if len(values) == 2:
        value ^= values[1]
    return value & 0xFFFFFFFF  # C# int XOR is int32; the offset is its unsigned read


# --------------------------------------------------------------------------- #
# Minimal C# lexical skipping (so '(' inside strings/comments is not a paren)   #
# --------------------------------------------------------------------------- #
def _skip_string(text: str, i: int) -> int:
    """text[i] == '"' -> index just past the closing quote."""
    verbatim = i > 0 and text[i - 1] == "@"
    n = len(text)
    i += 1
    while i < n:
        ch = text[i]
        if ch == "\\" and not verbatim:
            i += 2
            continue
        if ch == '"':
            if verbatim and i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return n


def _skip_char(text: str, i: int) -> int:
    """text[i] == "'" -> index just past the closing quote."""
    n = len(text)
    i += 1
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "'":
            return i + 1
        i += 1
    return n


def _skip_slash(text: str, i: int) -> int:
    """text[i] == '/' -> end of a comment, or i + 1 for a division operator."""
    n = len(text)
    if i + 1 < n and text[i + 1] == "/":
        end = text.find("\n", i)
        return n if end < 0 else end
    if i + 1 < n and text[i + 1] == "*":
        end = text.find("*/", i + 2)
        return n if end < 0 else end + 2
    return i + 1


def _find_call_end(text: str, open_idx: int) -> int | None:
    """Index of the ')' matching text[open_idx] == '(', or None if unbalanced."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i = _skip_string(text, i)
            continue
        if ch == "'":
            i = _skip_char(text, i)
            continue
        if ch == "/":
            j = _skip_slash(text, i)
            if j != i + 1:
                i = j
                continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _split_top_level(args: str) -> list[str]:
    """Split an argument list on top-level commas, dropping empty pieces."""
    parts: list[str] = []
    depth = 0
    start = 0
    i = 0
    n = len(args)
    while i < n:
        ch = args[i]
        if ch == '"':
            i = _skip_string(args, i)
            continue
        if ch == "'":
            i = _skip_char(args, i)
            continue
        if ch == "/":
            j = _skip_slash(args, i)
            if j != i + 1:
                i = j
                continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(args[start:i].strip())
            start = i + 1
        i += 1
    parts.append(args[start:].strip())
    return [part for part in parts if part]


# --------------------------------------------------------------------------- #
# The replacement itself                                                       #
# --------------------------------------------------------------------------- #
def accessor_signature(profile: st.Profile) -> re.Pattern[str]:
    """Compile the recogniser for this profile's two accessor call prefixes."""
    namespace = rf"(?:{re.escape(profile.direct_namespace)}\.)?" if profile.direct_namespace else ""
    direct = rf"{namespace}{re.escape(profile.direct_type)}\.{re.escape(profile.direct_method)}"
    proxy = rf"{re.escape(profile.proxy_type)}\.{re.escape(profile.proxy_method)}"
    return re.compile(
        r'(?P<dq>")'
        + r"|(?P<sq>')"
        + r"|(?P<slash>/)"
        + rf"|(?P<sig>(?<![\w.])(?:global::)?(?:{direct}|{proxy})\()"
    )


def _call_expression(kind: str, args: list[str], profile: st.Profile) -> str | None:
    """Return the offset argument if the arguments match the accessor shape."""
    if kind == "direct":
        return args[0] if len(args) == 1 else None
    if len(args) != 2:
        return None
    slot = f"{profile.proxy_type}.{profile.proxy_slot_field}"
    return args[0] if args[1] == slot else None


def annotate_text(
    text: str, table: dict[int, str], profile: st.Profile, signature=None
) -> tuple[str, dict[str, int]]:
    """Annotate accessor calls in one source text.

    Returns ``(new_text, {"replaced": n, "unresolved": m})``.  ``unresolved``
    counts calls that have the exact accessor shape but whose argument is not a
    recoverable offset; those calls are preserved verbatim.
    """
    if signature is None:
        signature = accessor_signature(profile)
    direct_prefix = f"{profile.direct_type}.{profile.direct_method}"
    proxy_prefix = f"{profile.proxy_type}.{profile.proxy_method}"

    out: list[str] = []
    replaced = unresolved = 0
    pos = 0
    while True:
        match = signature.search(text, pos)
        if match is None:
            out.append(text[pos:])
            break
        out.append(text[pos : match.start()])

        if match.group("sig") is not None:
            sig = match.group("sig").removeprefix("global::")
            if profile.direct_namespace:
                sig = sig.removeprefix(profile.direct_namespace + ".")
            kind = "proxy" if sig.startswith(proxy_prefix) else "direct"
            assert sig.startswith(direct_prefix) or sig.startswith(proxy_prefix)
            open_idx = match.end() - 1  # the '(' just consumed
            close_idx = _find_call_end(text, open_idx)
            expression = None
            if close_idx is not None:
                args = _split_top_level(text[open_idx + 1 : close_idx])
                expression = _call_expression(kind, args, profile)
            if close_idx is not None and expression is not None:
                offset = resolve_offset(expression)
                if offset is not None and offset in table:
                    out.append(
                        f"{csharp_literal(table[offset])} "
                        f"/* string {offset} */"
                    )
                    replaced += 1
                    pos = close_idx + 1
                    continue
            # Accessor-shaped but not recoverable: preserve the whole call.
            unresolved += 1
            out.append(text[match.start() : match.end()])
            pos = match.end()
            continue

        # A string, char or comment starts here: copy it through untouched.
        if match.group("dq") is not None:
            end = _skip_string(text, match.start())
        elif match.group("sq") is not None:
            end = _skip_char(text, match.start())
        else:
            end = _skip_slash(text, match.start())
        out.append(text[match.start() : end])
        pos = end

    return "".join(out), {"replaced": replaced, "unresolved": unresolved}


# --------------------------------------------------------------------------- #
# Source / metadata I/O                                                        #
# --------------------------------------------------------------------------- #
def _read_text(path: Path) -> str:
    # newline="" + surrogateescape: hand back exactly the bytes we read, so files
    # without a recovered call are copied byte-for-byte.
    with Path(path).open("r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        return fh.read()


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write(text)


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()


def _overlap(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _fail(message: str) -> int:
    print(f"refused: {message}", file=sys.stderr)
    return 2


def _load_versioned_table(
    table_path: Path, source_sha: str, profile: st.Profile
) -> tuple[dict[int, str], str, dict]:
    if not table_path.is_file():
        raise st.VerificationError(f"table JSON not found: {table_path}")
    meta = _read_json(Path(str(table_path) + ".source.json"))
    if not isinstance(meta, dict):
        raise st.VerificationError(
            f"{table_path} has no .source.json sidecar; an unversioned table is "
            "refused (run `string_table.py extract` first)"
        )
    if meta.get("sourceSha256") != source_sha:
        raise st.VerificationError(
            "table was decoded from a different source build than --src "
            f"({meta.get('sourceSha256')} != {source_sha})"
        )
    declared = meta.get("tableSha256")
    if not isinstance(declared, str) or not _SHA_RE.fullmatch(declared):
        raise st.VerificationError("table sidecar carries no valid tableSha256")

    raw = _read_json(table_path)
    table = st.parse_table_json(raw)
    rebuilt = st.plaintext_from_table(table)
    actual = hashlib.sha256(rebuilt).hexdigest()
    if actual != declared:
        raise st.VerificationError(
            "table JSON does not reproduce its declared tableSha256 "
            f"(declared {declared}, rebuilt {actual}); truncated or edited table"
        )
    if profile.plaintext_sha256 and actual != profile.plaintext_sha256:
        raise st.VerificationError("table does not match the known source profile")
    for offset, expected in profile.anchors:
        if table.get(offset) != expected:
            raise st.VerificationError("table anchor does not match the known source profile")
    declared_count = meta.get("entryCount")
    if declared_count is not None and declared_count != len(table):
        raise st.VerificationError(
            f"table entry count {len(table)} != sidecar entryCount {declared_count}"
        )
    if profile.entry_count is not None and len(table) != profile.entry_count:
        raise st.VerificationError(
            f"table entry count {len(table)} != profile expectation "
            f"{profile.entry_count}"
        )
    return table, declared, meta


def _decode_from_dll(
    dll: Path, source_sha: str, profile: st.Profile
) -> tuple[dict[int, str], str]:
    if not dll.is_file():
        raise st.VerificationError(f"--dll not found: {dll}")
    actual = st.hash_file(dll)
    if actual != source_sha:
        raise st.VerificationError(
            f"--dll sha256 {actual} does not match --src/.source.json {source_sha}; "
            "refusing to mix builds"
        )
    resource = st.load_resource(dll, profile.resource)
    decoded = st.decode_and_verify(resource, profile)
    if st.hash_file(dll) != source_sha:
        raise st.VerificationError("source DLL changed while decoding")
    return decoded.table, decoded.plaintext_sha256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", required=True, help="decompiled .cs tree")
    parser.add_argument("--out", required=True, help="annotated copy destination")
    parser.add_argument("--table-json", default=None, help="versioned table JSON")
    parser.add_argument("--dll", default=None, help="decode fresh from this DLL")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if (args.table_json is None) == (args.dll is None):
        return _fail("give exactly one of --table-json (reuse) or --dll (decode)")

    src = Path(args.src).resolve()
    out = Path(args.out).resolve()
    if not src.is_dir():
        return _fail(f"--src is not a directory: {src}")
    if _overlap(src, out):
        return _fail("--src and --out must not be identical or nested")

    files = sorted(src.rglob("*.cs"))
    if not files:
        return _fail("no .cs files under --src")

    src_meta = _read_json(src / ".source.json")
    if not isinstance(src_meta, dict):
        return _fail(
            "--src has no .source.json; refusing to annotate a decomp of unknown build"
        )
    source_sha = str(src_meta.get("sourceSha256", "")).lower()
    if not _SHA_RE.fullmatch(source_sha):
        return _fail("--src/.source.json has no valid sourceSha256")
    profile = st.PROFILES.get(source_sha)
    if profile is None:
        return _fail(f"unknown source profile for --src build {source_sha}")

    try:
        if args.table_json is not None:
            table, table_sha, _meta = _load_versioned_table(
                Path(args.table_json), source_sha, profile
            )
        else:
            table, table_sha = _decode_from_dll(Path(args.dll), source_sha, profile)
    except st.VerificationError as exc:
        return _fail(str(exc))

    if not table:
        return _fail("string table is empty")

    signature = accessor_signature(profile)

    # Pass 1: count only, so a run with nothing to recover writes nothing.
    replaced = unresolved = 0
    source_meta_sha=st.hash_file(src/'.source.json')
    input_hashes={}
    for path in files:
        text=_read_text(path)
        input_hashes[path.relative_to(src).as_posix()]=_sha256_of_text(text)
        _text, counts = annotate_text(text, table, profile, signature)
        replaced += counts["replaced"]
        unresolved += counts["unresolved"]
    if replaced == 0:
        return _fail(
            "no string accessor calls recovered from --src; refusing to write an "
            "annotation with no real replacements"
        )

    out_meta_path = out / ".source.json"
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        return _fail("--out already contains files; use a new output path")

    # Pass 2 binds each write to the exact bytes counted in pass 1.
    output_hashes=[]
    try:
        for path in files:
            relative=path.relative_to(src).as_posix()
            text=_read_text(path)
            if _sha256_of_text(text)!=input_hashes[relative]:
                return _fail("source changed between annotation passes: "+relative)
            annotated, _counts = annotate_text(text, table, profile, signature)
            _write_text(out / relative, annotated)
            output_hashes.append((relative,_sha256_of_text(annotated)))
        if sorted(src.rglob("*.cs"))!=files or st.hash_file(src/'.source.json')!=source_meta_sha:
            return _fail("source file set or identity changed during annotation")
        failed=src_meta.get('failedTypes')
        completeness=src_meta.get('inputCompleteness', {'complete':False if type(failed) is int and failed>0 else None,'failedTypes':failed,'scope':'decompiler-reported'})
        exclusive_write_text(out_meta_path,json.dumps({
            "tool":"annotate-strings.py","annotationOnly":True,"liveAdapterCompatible":False,
            "sourceDir":str(src),"sourceSha256":source_sha,"profile":profile.label,
            "tableSha256":table_sha,"entryCount":len(table),"filesScanned":len(files),
            "callsAnnotated":replaced,"callsUnresolved":unresolved,
            "inputSetSha256":source_set_id(input_hashes.items()),
            "outputSetSha256":source_set_id(output_hashes),"inputCompleteness":completeness,
        },ensure_ascii=False,indent=2))
    except (OSError, ValueError) as exc:
        return _fail("exclusive annotated output failed: "+str(exc))
    print(
        f"files={len(files)} literals_recovered={replaced} "
        f"left_unresolved={unresolved}",
        file=sys.stderr,
    )
    print(f"wrote {out}", file=sys.stderr)
    return 0


# Legacy import target: the old annotation script exported ``build_table()`` with
# no arguments.  Kept so existing callers keep importing successfully.
def build_table(blob: Path | None = None, key: Path | None = None) -> dict[int, str]:
    return st.build_table(blob, key)


if __name__ == "__main__":
    raise SystemExit(main())
