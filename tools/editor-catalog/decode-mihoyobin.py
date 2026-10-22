#!/usr/bin/env python3
"""Decode the Miliastra editor's .mihoyobin resource files into readable structure.

The transform is proven, not guessed. It comes from the editor's own loader:

  file-loader.cs:245   File.ReadAllBytes(path)
  file-loader.cs:250   for (int i = 0; i < array.Length; i++) array[i] ^= 229;
  file-loader.cs:253   factory: return new T()
  file-loader.cs:254   new MemoryStream(array, writable: false)
  file-loader.cs:257   message-reader: MergeFrom(instance, stream)   -> protobuf wire

So: plain single-byte XOR with 0xE5, and the payload is a protobuf wire stream.
Evidence: .runtime/verification/resource-file-loader/ (file-loader.cs, message-reader.cs).

This script does NOT invent a schema. It walks the wire format generically and
labels every field by number and wire type, additionally showing a string when the
bytes decode as printable UTF-8 and a nested tree when they parse as a submessage.
Unknown stays unknown; it is never renamed into a business meaning. Any semantic
reading of these fields elsewhere in the pipeline is a hypothesis about a
historical file schema, not a verified or officially accepted meaning.

Integrity contract: every decoded output carries the source sha256, the decoded
sha256, the absolute source root, the source-relative path and a run-wide
source-set sha256. When --out is given, the same records plus each output file's
own sha256 are written to _provenance.json, which downstream consumers require.

Read-only with respect to the game install: input files are opened for reading only,
output goes to the directory given with --out.

Usage:
    python decode-mihoyobin.py <file-or-dir> [--out DIR] [--index FILE] [--max-bytes N]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catalog_inputs import (  # noqa: E402
    PROVENANCE_NAME,
    SCHEMA_VERSION,
    CatalogError,
    ensure_absent,
    ensure_fresh_dir,
    ensure_no_overlap,
    exclusive_write_text,
    is_within,
    resolve,
    sha256_file,
    source_set_id,
)

XOR_KEY = 0xE5

ROOT_PREFIX = "resource/json/"

FIELD_NUMBER_MAX = 2**29 - 1

STREAM_CHUNK = 1 << 20


class WireError(Exception):
    pass


def read_varint(buf: bytes, i: int) -> tuple[int, int]:
    """Read one protobuf varint, rejecting widths beyond 64 bits.

    A 64-bit varint is at most 10 bytes: shifts 0,7,...,63. The 10th byte
    (shift 63) may only contribute bit 63, so any of its upper payload bits set
    is a malformed encoding rather than a large number.
    """
    result = 0
    shift = 0
    while True:
        if i >= len(buf):
            raise WireError("varint runs past end")
        b = buf[i]
        i += 1
        if shift == 63 and (b & 0x7E):
            raise WireError("64-bit varint upper bits set")
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7
        if shift > 63:
            raise WireError("varint wider than 64 bits")


def try_utf8(b: bytes) -> str | None:
    if not b:
        return None
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Require it to look like text rather than coincidence.
    printable = sum(1 for c in s if c.isprintable() or c in "\n\r\t")
    if printable < len(s):
        return None
    return s


def parse_message(buf: bytes, depth: int = 0) -> list[dict]:
    """Parse a protobuf wire stream into a list of field records."""
    if depth > 12:
        raise WireError("nesting too deep")
    fields: list[dict] = []
    i = 0
    n = len(buf)
    while i < n:
        tag, i = read_varint(buf, i)
        fnum, wtype = tag >> 3, tag & 7
        if fnum == 0:
            raise WireError("field number 0")
        if fnum > FIELD_NUMBER_MAX:
            raise WireError(f"field number {fnum} exceeds {FIELD_NUMBER_MAX}")
        rec: dict = {"f": fnum, "w": wtype}
        if wtype == 0:
            v, i = read_varint(buf, i)
            rec["v"] = v
        elif wtype == 1:
            if i + 8 > n:
                raise WireError("fixed64 overrun")
            rec["v"] = int.from_bytes(buf[i : i + 8], "little")
            i += 8
        elif wtype == 2:
            ln, i = read_varint(buf, i)
            if i + ln > n:
                raise WireError("length-delimited overrun")
            payload = buf[i : i + ln]
            i += ln
            s = try_utf8(payload)
            sub = None
            if payload:
                try:
                    sub = parse_message(payload, depth + 1)
                except WireError:
                    sub = None
            if s is not None and sub is None:
                rec["s"] = s
            elif s is not None and sub is not None:
                # Both interpretations are legal; keep the tree, note the text.
                rec["m"] = sub
                if len(s) >= 2:
                    rec["s_alt"] = s
            elif sub is not None:
                rec["m"] = sub
            else:
                rec["b"] = payload.hex()
        elif wtype == 5:
            if i + 4 > n:
                raise WireError("fixed32 overrun")
            rec["v"] = int.from_bytes(buf[i : i + 4], "little")
            i += 4
        else:
            raise WireError(f"unsupported wire type {wtype}")
        fields.append(rec)
    return fields


def decode(path: Path, max_bytes: int) -> dict:
    """Decode one file, never reading more than --max-bytes from disk."""
    result: dict = {"path": str(path)}
    size = path.stat().st_size
    result["size"] = size
    if size == 0:
        result["ok"] = False
        result["error"] = "empty file"
        return result
    if size > max_bytes:
        result["ok"] = False
        result["error"] = f"larger than --max-bytes ({max_bytes}); not read"
        return result
    with path.open("rb") as fh:
        raw = fh.read(max_bytes + 1)
    if len(raw) != size or len(raw) > max_bytes:
        result.update(ok=False, error="source changed while reading")
        return result
    result["source_sha256"] = hashlib.sha256(raw).hexdigest()
    dec = bytes(b ^ XOR_KEY for b in raw)
    result["decoded_head_hex"] = dec[:16].hex()
    result["decoded_sha256"] = hashlib.sha256(dec).hexdigest()
    try:
        result["fields"] = parse_message(dec)
        result["ok"] = True
    except WireError as exc:
        result["ok"] = False
        result["error"] = str(exc)
    return result


def walk_strings(fields, out: list[str], path: str = ""):
    for r in fields:
        p = f"{path}.{r['f']}"
        if "s" in r:
            out.append(f"{p}\t{r['s']}")
        if "m" in r:
            walk_strings(r["m"], out, p)


def collect_files(target: Path) -> tuple[list[Path], Path]:
    if not target.exists():
        raise CatalogError(f"target does not exist: {target}")
    if target.is_dir():
        files = sorted(p for p in target.rglob("*.mihoyobin") if p.is_file())
        if not files:
            raise CatalogError(f"no .mihoyobin files under {target}")
        return files, target
    if target.is_file():
        return [target], target.parent
    raise CatalogError(f"target is neither file nor directory: {target}")


def flat_name(rel: Path) -> str:
    """Flatten a source-relative path with '__', identically on every platform."""
    return "__".join(rel.parts) + ".json"


def hash_sources(files: list[Path], rels: list[Path], max_bytes: int) -> dict:
    """sha256 per source file, skipping oversized files without reading them."""
    digests: dict[Path, str | None] = {}
    for path, rel in zip(files, rels):
        size = path.stat().st_size
        if size == 0 or size > max_bytes:
            digests[path] = None
            continue
        try:
            digests[path] = sha256_file(path)
        except OSError as exc:
            raise CatalogError(f"cannot read {rel}: {exc}") from exc
    return digests


def set_fingerprint(files: list[Path], rels: list[Path], digests: dict, sizes: dict) -> str:
    pairs = []
    for path, rel in zip(files, rels):
        digest = digests[path] if digests[path] else f"size:{sizes[path]}"
        pairs.append((str(rel).replace("\\", "/"), digest))
    return source_set_id(pairs)


def build_provenance(source_root, files, rels, records, set_sha, max_bytes) -> dict:
    return {
        "tool": "decode-mihoyobin.py",
        "schema_version": SCHEMA_VERSION,
        "source_root": str(source_root),
        "source_set_sha256": set_sha,
        "xor_key": XOR_KEY,
        "max_bytes": max_bytes,
        "counts": {
            "files": len(records),
            "ok": sum(1 for r in records if r.get("ok")),
            "failed": sum(1 for r in records if not r.get("ok")),
        },
        "files": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target")
    ap.add_argument("--out", default=None, help="write one .json per file here (must be fresh/empty)")
    ap.add_argument("--index", default=None, help="write a flat summary .jsonl here (must not exist)")
    ap.add_argument("--max-bytes", type=int, default=4 * 1024 * 1024)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.max_bytes <= 0:
        print("error: --max-bytes must be a positive integer", file=sys.stderr)
        return 2

    target = resolve(args.target)
    out = index = None
    try:
        files, source_root = collect_files(target)

        # Check every path precondition before touching the filesystem, so a
        # rejected run leaves nothing behind.
        out_path = resolve(args.out) if args.out else None
        index_path = resolve(args.index) if args.index else None
        if out_path is not None:
            ensure_no_overlap(source_root, out_path, "source", "output")
        if index_path is not None:
            ensure_no_overlap(source_root, index_path, "source", "index")
            if out_path is not None and is_within(index_path, out_path):
                raise CatalogError(
                    f"index path conflicts with output directory: {index_path}"
                )
        if index_path is not None:
            index = ensure_absent(index_path, "index")
            ensure_absent(str(index) + ".provenance.json", "index provenance")
        if out_path is not None:
            out = out_path

        rels = [p.relative_to(source_root) if target.is_dir() else Path(p.name) for p in files]
        flats = [flat_name(r) for r in rels]
        dupes = sorted(n for n, count in collections.Counter(flats).items() if count > 1)
        if dupes:
            raise CatalogError(f"duplicate flattened output names: {dupes}")
        if any(n == PROVENANCE_NAME for n in flats):
            raise CatalogError(f"a source file collides with the reserved name {PROVENANCE_NAME}")

        if out is not None:
            out = ensure_fresh_dir(out, "output directory")
        sizes = {p: p.stat().st_size for p in files}
        digests = hash_sources(files, rels, args.max_bytes)
        set_sha = set_fingerprint(files, rels, digests, sizes)
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    index_fh = None
    if index is not None:
        index.parent.mkdir(parents=True, exist_ok=True)
        index_fh = open(index, "x", encoding="utf-8", newline="\n")

    records: list[dict] = []
    index_buffer: list[str] = []
    ok = bad = 0
    try:
        for path, rel, flat in zip(files, rels, flats):
            r = decode(path, args.max_bytes)
            if r.get("source_sha256") != digests[path]:
                r.update(ok=False, error="source changed between inventory and decode")
            if r.get("ok"):
                ok += 1
            else:
                bad += 1
            r["source_root"] = str(source_root)
            r["source_path"] = str(path)
            r["source_relative_path"] = str(rel).replace("\\", "/")
            r["source_sha256"] = digests[path]
            r["source_set_sha256"] = set_sha

            if out is not None:
                dest = out / flat
                exclusive_write_text(dest, json.dumps(r, ensure_ascii=False, indent=1))
                r["output"] = flat
                r["output_sha256"] = sha256_file(dest)

            records.append({k: v for k, v in r.items() if k != "fields"})

            if index_fh is not None:
                entry = {
                    "path": str(path),
                    "source_root": str(source_root),
                    "source_relative_path": r["source_relative_path"],
                    "source_sha256": r["source_sha256"],
                    "decoded_sha256": r.get("decoded_sha256"),
                    "source_set_sha256": set_sha,
                    "size": r["size"],
                    "ok": r.get("ok", False),
                }
                if out is not None:
                    entry["output"] = flat
                if r.get("error"):
                    entry["error"] = r["error"]
                if r.get("ok"):
                    strs: list[str] = []
                    walk_strings(r["fields"], strs)
                    entry["strings"] = strs
                    entry["top_fields"] = sorted({x["f"] for x in r["fields"]})
                index_buffer.append(json.dumps(entry, ensure_ascii=False))
                if len(index_buffer) >= 200:
                    index_fh.write("\n".join(index_buffer) + "\n")
                    index_buffer = []

        if index_fh is not None and index_buffer:
            index_fh.write("\n".join(index_buffer) + "\n")
    finally:
        if index_fh is not None:
            index_fh.close()

    provenance = build_provenance(source_root, files, rels, records, set_sha, args.max_bytes)
    if out is not None:
        exclusive_write_text(
            out / PROVENANCE_NAME, json.dumps(provenance, ensure_ascii=False, indent=1),
            "provenance",
        )
    if index is not None:
        sidecar = dict(provenance)
        sidecar["index"] = str(index)
        sidecar["index_sha256"] = sha256_file(index)
        exclusive_write_text(
            Path(str(index) + ".provenance.json"),
            json.dumps(sidecar, ensure_ascii=False, indent=1),
            "provenance",
        )

    if not args.quiet:
        print(f"target={target} source_root={source_root} source_set_sha256={set_sha}")
        for r in records:
            if not r.get("ok"):
                print(f"  failed {r['source_relative_path']}: {r.get('error')}", file=sys.stderr)
        print(f"files={len(files)} ok={ok} failed={bad}", file=sys.stderr)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
