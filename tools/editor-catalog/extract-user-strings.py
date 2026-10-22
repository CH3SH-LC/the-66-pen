#!/usr/bin/env python3
"""Extract .NET user strings (#US heap, i.e. ldstr literals) from a PE assembly.

Why this exists: the editor's assemblies are name-obfuscated, but string
literals are left in plaintext. Those literals are the anchors that identify
what an otherwise randomly-named method actually does.

Stdlib only, and read-only: the file is parsed as *data*. Nothing is loaded,
JITed, reflected over or executed, no process is touched and no network is used.

Standard managed-PE layout, parsed strictly
-------------------------------------------
  * MZ + e_lfanew -> ``PE\\0\\0``, COFF header, optional header.
  * The optional-header magic selects the data-directory base: ``0x10b`` (PE32)
    uses ``+0x60``, ``0x20b`` (PE32+) uses ``+0x70``.  The ``0x70``/``0x80`` pair
    reads the wrong table entirely, so the CLI directory would come from
    unrelated bytes.
  * Section table entry layout: VirtualSize ``+8``, VirtualAddress ``+12``,
    SizeOfRawData ``+16``, PointerToRawData ``+20``.
  * CLI header (data directory 14, index 14) -> metadata root (``BSJB``) ->
    stream headers -> ``#US``.
  * ``#US`` blob: an ECMA-335 compressed unsigned length, then exactly that many
    bytes -- one flag byte plus ``length - 1`` UTF-16LE bytes.  The payload
    length must therefore be even; the old odd/even guess at the flag byte is
    gone.

Everything is bounds-checked, and a malformed or truncated file raises instead of
returning a plausible prefix.  An undecodable blob is fatal rather than silently
skipped.  Only trailing zero alignment padding is tolerated, because the runtime
writers really do emit it.

A known hash is *not* required: any managed DLL is accepted because ``#US`` is a
standard format.  When ``--out`` is given the sidecar records the source SHA-256
so a consumer can pin the exact input.

Usage:
    python extract-user-strings.py <assembly.dll> [--min-len N] [--out FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from catalog_inputs import (  # noqa: E402
    CatalogError,
    ensure_absent,
    ensure_no_overlap,
    exclusive_write_text,
    resolve,
    sha256_file,
)

PE32_MAGIC = 0x10B
PE32P_MAGIC = 0x20B
# Where the data directories start, per optional-header magic.
DIRECTORY_BASE = {PE32_MAGIC: 0x60, PE32P_MAGIC: 0x70}
# NumberOfRvaAndSizes sits at the end of the Windows-specific fields.
NUM_DIRECTORIES_OFFSET = {PE32_MAGIC: 0x5C, PE32P_MAGIC: 0x6C}
CLI_DIRECTORY_INDEX = 14
SECTION_HEADER_SIZE = 40


class PEError(Exception):
    """The image is not a well-formed managed PE; nothing may be reported."""


def _need(data: bytes, off: int, size: int, what: str) -> None:
    if off < 0 or size < 0 or off + size > len(data):
        raise PEError(
            f"{what} at {off:#x} needs {size} bytes but the file holds {len(data)}"
        )


def _u16(data: bytes, off: int, what: str) -> int:
    _need(data, off, 2, what)
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int, what: str) -> int:
    _need(data, off, 4, what)
    return struct.unpack_from("<I", data, off)[0]


def read_pe_metadata(path: Path):
    """Parse the PE/COFF/optional headers. Returns (data, cli_rva, cli_size, sections)."""
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PEError("not a PE file (missing MZ header)")

    pe_off = _u32(data, 0x3C, "e_lfanew")
    if pe_off + 24 > len(data) or data[pe_off : pe_off + 4] != b"PE\0\0":
        raise PEError(f"no PE signature at {pe_off:#x}")

    coff = pe_off + 4
    num_sections = _u16(data, coff + 2, "NumberOfSections")
    opt_size = _u16(data, coff + 16, "SizeOfOptionalHeader")
    opt = coff + 20

    magic = _u16(data, opt, "optional header magic")
    if magic not in DIRECTORY_BASE:
        raise PEError(f"unsupported optional header magic {magic:#x}")
    _need(data, opt, opt_size, "optional header")

    # Standard + Windows-specific fields, then the (CLI_DIRECTORY_INDEX + 1)-th
    # data directory, must all fit inside the declared optional header.
    required = max(
        NUM_DIRECTORIES_OFFSET[magic] + 4,
        DIRECTORY_BASE[magic] + (CLI_DIRECTORY_INDEX + 1) * 8,
    )
    if opt_size < required:
        raise PEError(
            f"optional header is {opt_size} bytes, needs {required} for the CLI directory"
        )

    num_dirs = _u32(data, opt + NUM_DIRECTORIES_OFFSET[magic], "NumberOfRvaAndSizes")
    if num_dirs <= CLI_DIRECTORY_INDEX:
        raise PEError(f"image declares {num_dirs} data directories; no CLI directory")

    dd_off = opt + DIRECTORY_BASE[magic] + CLI_DIRECTORY_INDEX * 8
    cli_rva = _u32(data, dd_off, "CLI directory RVA")
    cli_size = _u32(data, dd_off + 4, "CLI directory size")
    if cli_rva == 0:
        raise PEError("no CLI directory (not a managed assembly)")
    if cli_size < 0x10:
        raise PEError(f"CLI header size {cli_size} is too small")

    if num_sections == 0:
        raise PEError("image declares no sections")
    sec_off = opt + opt_size
    sections = []
    for i in range(num_sections):
        s = sec_off + i * SECTION_HEADER_SIZE
        virtual_size = _u32(data, s + 8, f"section {i} VirtualSize")
        virtual_address = _u32(data, s + 12, f"section {i} VirtualAddress")
        raw_size = _u32(data, s + 16, f"section {i} SizeOfRawData")
        raw_ptr = _u32(data, s + 20, f"section {i} PointerToRawData")
        if raw_size:
            _need(data, raw_ptr, raw_size, f"section {i} raw data")
        sections.append((virtual_address, virtual_size, raw_ptr, raw_size))
    return data, cli_rva, cli_size, sections


def rva_to_off(data: bytes, sections, rva: int, size: int, what: str) -> int:
    """Map an RVA to a file offset, requiring ``size`` readable bytes there."""
    for virtual_address, virtual_size, raw_ptr, raw_size in sections:
        if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
            delta = rva - virtual_address
            if delta + size > raw_size:
                raise PEError(
                    f"{what}: RVA {rva:#x} lives in virtual-only space "
                    f"(needs {size} bytes, section maps {raw_size})"
                )
            off = raw_ptr + delta
            _need(data, off, size, what)
            return off
    raise PEError(f"{what}: RVA {rva:#x} is not mapped by any section")


def find_us_heap(data: bytes, cli_rva: int, sections) -> bytes | None:
    """Return the raw ``#US`` stream, or None when the image has no such stream."""
    cli_off = rva_to_off(data, sections, cli_rva, 0x10, "CLI header")
    md_rva = _u32(data, cli_off + 8, "metadata RVA")
    md_size = _u32(data, cli_off + 12, "metadata size")
    if md_rva == 0 or md_size == 0:
        raise PEError("no metadata root (not a .NET image)")
    md_off = rva_to_off(data, sections, md_rva, md_size, "metadata root")
    _need(data, md_off, md_size, "metadata root")
    if data[md_off : md_off + 4] != b"BSJB":
        raise PEError(f"bad metadata signature at {md_off:#x}")

    if md_size < 20:
        raise PEError("metadata root is shorter than its fixed header")
    version_len = _u32(data, md_off + 12, "metadata version length")
    if version_len == 0 or version_len > 255 or version_len % 4:
        raise PEError(f"implausible metadata version length {version_len}")

    if 16 + version_len + 4 > md_size:
        raise PEError("metadata version and stream count escape metadata root")
    streams_count_off = md_off + 16 + version_len + 2
    num_streams = _u16(data, streams_count_off, "stream count")
    if num_streams == 0:
        raise PEError("metadata root declares no streams")

    p = md_off + 16 + version_len + 4
    md_end = md_off + md_size
    streams = {}
    ranges = []
    for _ in range(num_streams):
        if p + 8 > md_end:
            raise PEError("stream header escapes metadata root")
        offset = _u32(data, p, "stream offset")
        size = _u32(data, p + 4, "stream size")
        p += 8
        if offset + size > md_size:
            raise PEError(
                f"stream at offset {offset:#x} size {size} escapes the metadata root"
            )
        end = data.find(b"\0", p, md_end)
        if p >= md_end or end < 0:
            raise PEError("unterminated metadata stream name")
        try:
            name = data[p:end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise PEError(f"metadata stream name is not ASCII: {exc}") from exc
        p = (end + 1 + 3) & ~3  # names are padded to a 4-byte boundary
        if not name or len(name) > 31 or p > md_end:
            raise PEError("invalid metadata stream name or padding")
        if name in streams:
            raise PEError("duplicate metadata stream: " + name)
        streams[name] = (offset, size)
        if size:
            ranges.append((offset, offset + size))
    header_size = p - md_off
    previous_end = header_size
    for begin, end in sorted(ranges):
        if begin < previous_end:
            raise PEError("metadata streams overlap a header or another stream")
        previous_end = end
    if "#US" not in streams:
        return None
    offset, size = streams["#US"]
    return data[md_off + offset:md_off + offset + size]



def decode_compressed_uint(heap: bytes, i: int) -> tuple[int, int]:
    """ECMA-335 II.23.2 compressed unsigned integer. Returns (value, size)."""
    if i >= len(heap):
        raise PEError(f"#US: truncated compressed length at {i:#x}")
    first = heap[i]
    if first & 0x80 == 0:
        return first, 1
    if first & 0xC0 == 0x80:
        if i + 2 > len(heap):
            raise PEError(f"#US: truncated two-byte length at {i:#x}")
        return ((first & 0x3F) << 8) | heap[i + 1], 2
    if first & 0xE0 == 0xC0:
        if i + 4 > len(heap):
            raise PEError(f"#US: truncated four-byte length at {i:#x}")
        return (
            ((first & 0x1F) << 24) | (heap[i + 1] << 16) | (heap[i + 2] << 8) | heap[i + 3],
            4,
        )
    raise PEError(f"#US: invalid compressed length prefix {first:#x} at {i:#x}")


def iter_us_strings(heap: bytes):
    """Walk the ``#US`` heap, yielding one decoded literal per blob.

    A zero length is the empty-string sentinel / alignment padding.  Any other
    blob must fit exactly, and its payload (flag byte + UTF-16LE text) must have
    an even length and decode cleanly; otherwise this raises.
    """
    if heap[:1] != b"\x00":
        raise PEError("#US heap does not start with the empty-string sentinel")
    i = 1
    total = len(heap)
    while i < total:
        start = i
        length, header = decode_compressed_uint(heap, i)
        i += header
        if length == 0:
            continue
        if i + length > total:
            raise PEError(
                f"#US: blob at {start:#x} needs {length} bytes but the heap ends at {total}"
            )
        raw = heap[i : i + length - 1]  # ECMA-335: the flag is the LAST byte
        if heap[i + length - 1] not in (0, 1):
            raise PEError("#US: invalid trailing flag byte")
        i += length
        if len(raw) % 2:
            raise PEError(
                f"#US: blob at {start:#x} has an odd UTF-16 payload length "
                f"({len(raw)} bytes)"
            )
        try:
            yield raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise PEError(f"#US: blob at {start:#x} is not valid UTF-16LE: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("assembly", help="managed .NET assembly to read as data")
    ap.add_argument("--min-len", type=int, default=1, help="drop strings shorter than N")
    ap.add_argument("--out", default=None, help="text output file (must not exist)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    assembly = resolve(args.assembly)
    if not assembly.is_file():
        print(f"refused: assembly not found: {assembly}", file=sys.stderr)
        return 2
    if args.min_len < 0:
        print("refused: --min-len must not be negative", file=sys.stderr)
        return 2

    try:
        data, cli_rva, _cli_size, sections = read_pe_metadata(assembly)
        heap = find_us_heap(data, cli_rva, sections)
        if heap is None:
            print(
                f"no #US heap in {assembly.name}; nothing to extract (explicit no-strings exit)",
                file=sys.stderr,
            )
            return 1
        seen: set[str] = set()
        lines: list[str] = []
        for value in iter_us_strings(heap):
            if len(value) < args.min_len or value in seen:
                continue
            seen.add(value)
            lines.append(value)
    except (PEError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    if not lines:
        print(
            f"no user strings found in {assembly.name} "
            f"(--min-len {args.min_len}); nothing written",
            file=sys.stderr,
        )
        return 1
    lines.sort()
    text = "\n".join(lines)

    if args.out is None:
        print(text)
        return 0

    try:
        out = resolve(args.out)
        sidecar = Path(str(out) + ".source.json")
        ensure_absent(out)
        ensure_absent(sidecar)
        ensure_no_overlap(assembly, out, "assembly", "--out")
        ensure_no_overlap(assembly, sidecar, "assembly", "sidecar")
        if sha256_file(assembly) != hashlib.sha256(data).hexdigest():
            raise CatalogError("source assembly changed during extraction")
        written = exclusive_write_text(out, text)
        exclusive_write_text(
            Path(str(written) + ".source.json"),
            json.dumps(
                {
                    "tool": "extract-user-strings.py",
                    "schema_version": 1,
                    "liveAdapterCompatible": False,
                    "sourceAssembly": str(assembly),
                    "sourceSha256": hashlib.sha256(data).hexdigest(),
                    "usHeapBytes": len(heap),
                    "stringCount": len(lines),
                    "minLen": args.min_len,
                    "output": str(written),
                    "outputSha256": sha256_file(written),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "output sidecar",
        )
    except (CatalogError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(f"{len(lines)} distinct strings -> {written}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
