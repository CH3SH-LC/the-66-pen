#!/usr/bin/env python3
"""Decode the editor's obfuscated string table from a *known* source DLL.

The editor assembly keeps almost no readable string literals: a literal survives
only as an int byte-offset into an encrypted blob carried as an embedded manifest
resource.  The bytes at that offset are read back at run time as UTF-16LE text.
Method calls that recover such a literal appear in decompiled source as

    PgdJdFPLK4PkoLedWk7c.RcDPXnUGLKY(0x52F599CD ^ 0x52F56847)
    OfHnbKPAfwDjrwrhrnHS.vamPAss8BQY(0x52F599CD ^ 0x52F56847,
                                     OfHnbKPAfwDjrwrhrnHS.UuIPAuUcgRX)

i.e. the offset is itself written as two 32-bit literals XORed at run time.

This module carries a pure transcription of the editor's own byte transform (it
is a data-independent 4-byte-block XOR keystream, so the same routine both
decrypts the resource and, for any length divisible by 4, is its own inverse),
and one pinned decode profile per known source DLL SHA-256.

Scope / boundaries
------------------
  * Pure-Python and offline.  No runtime dependency is imported at module
    level; nothing here is read from the project's ``.runtime`` evidence dirs.
  * ``dnfile`` is imported lazily, inside the resource reader only, from the
    project-local dependency copy.  It parses the PE image as *data*: the
    assembly is never loaded, JITed, reflected over or executed, no process is
    touched, and no network is used.
  * A profile is selected solely by the SHA-256 of the ``--dll`` given on the
    command line.  An unknown build is refused, never guessed.
  * Profiles authorize offline resource decoding only.  They do not authorize a
    live adapter, an in-game call or any reflection, so every emitted sidecar
    records ``liveAdapterCompatible: false``.

Refusals (exit 2, nothing written)
----------------------------------
  * unknown or changed source DLL
  * missing / empty resource, or resource SHA-256 mismatch against the profile
  * key shorter than 4 bytes (the cipher would divide by zero)
  * any table walk that is not exact -- truncated length field, negative or odd
    length, entry overrun, or bytes that are not valid UTF-16LE.  There is no
    partial success: :func:`parse_table` never returns a prefix of the blob.
  * entry-count / plaintext-SHA-256 / anchor mismatch against the profile
  * output that already belongs to a different source build

Usage:
    python string_table.py extract --dll PATH --out FILE.json
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPS = ROOT / ".runtime/mvp/ipc-research/deps"
DEFAULT_DLL = Path(
    "D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/BeyondEditor.dll"
)

# Historical artifact pair, kept only so the legacy ``build_table()`` entry point
# (and any caller importing it) keeps working.
FOLLOWUP = ROOT / ".runtime/mvp/string-loader-followup"
LEGACY_BLOB = FOLLOWUP / "k0NMjJaUgmhZWiMRob.DuimXPmvaoLIiHCe8B.bin"
LEGACY_KEY = FOLLOWUP / "local1-key.bin"

_M32 = 0xFFFFFFFF
_MIN_KEY_BYTES = 4  # C# does `i % (len(key)//4)`; a shorter key divides by zero


# --------------------------------------------------------------------------- #
# Pure algorithm -- transcription of the editor's own routines.                #
# Not one of these functions reads a file, the network, or the assembly.       #
# --------------------------------------------------------------------------- #
def _u32(x: int) -> int:
    """C# unchecked uint32 wrap."""
    return x & _M32


def cFBYLsegA0V(P_0: int) -> int:
    """Transcription of the editor's 32-bit mixer."""
    num = _u32(P_0)
    num2 = 973202305
    num3 = 1582787682
    num4 = 1577548636
    num5 = 332884210
    num6 = _u32(num4 * 1313243236)  # uint expression wraps before ulong assign
    num6 |= 1
    num3 = _u32(_u32(num3 * num3) % num6)
    num7 = _u32(1907532890 * num4)
    if num7 == 0:
        num7 -= 1
    _ = 698203908 % num7  # discarded, as in the original
    num2 = _u32(-502326134 - num3)
    num8 = _u32(num3 * 183835789)
    num8 |= 1
    num4 = _u32(_u32(num4 * num4) % num8)
    num9 = _u32(_u32((num5 >> 6) | (num5 << 26)) ^ num3)
    num10 = num9 & 0x0F0F0F0F
    num5 = _u32(_u32((num9 & 0xF0F0F0F0) >> 4) | _u32(num10 << 4))
    num = _u32(num ^ _u32(num << 3))
    num = _u32(num + num2)
    num = _u32(num ^ _u32(num << 11))
    num = _u32(num + num4)
    num = _u32(num ^ (num >> 27))
    num = _u32(num + num5)
    return _u32(_u32(_u32(_u32(num2 << 11) - num3) ^ num4) - num)


def transform(data: bytes, key: bytes) -> bytes:
    """Transcription of the editor's resource transform.

    The keystream depends only on ``key`` (and the data length), so for a length
    divisible by 4 this is a plain byte-wise XOR: applying it twice with the same
    key restores the input.  A trailing partial block is handled by the original
    routine's partial-block branch; both aligned and non-aligned resources
    are parsed strictly after decryption.
    """
    if len(data) == 0:
        return b""

    num = len(data) % 4
    num2 = len(data) // 4
    array = bytearray(len(data))
    num3 = len(key) // 4
    if num3 == 0:
        raise ValueError(
            f"key must be >= {_MIN_KEY_BYTES} bytes (len(key)//4 == 0); "
            "the original would throw DivideByZeroException"
        )
    num4 = 0
    num5 = 0
    num6 = 0
    if num > 0:
        num2 += 1
    num7 = 0
    for i in range(num2):
        num8 = i % num3
        num9 = i * 4
        num7 = num8 * 4  # (uint)(num8 * 4)
        num5 = _u32(
            (key[num7 + 3] << 24)
            | (key[num7 + 2] << 16)
            | (key[num7 + 1] << 8)
            | key[num7]
        )
        if i == num2 - 1 and num > 0:
            num6 = 0
            num10 = 255
            num11 = 0
            for j in range(num):
                if j > 0:
                    num6 = _u32(num6 << 8)
                num6 |= data[len(data) - 1 - j]  # C# `P_0[^(1 + j)]`
            num4 = _u32(num4 + num5)
            num4 = _u32(num4 + cFBYLsegA0V(num4))
            num12 = _u32(num4 ^ num6)
            for k in range(num):
                if k > 0:
                    num10 = _u32(num10 << 8)
                    num11 += 8
                array[num9 + k] = (_u32(num12 & num10) >> num11) & 0xFF
        else:
            num7 = num9
            num6 = _u32(
                (data[num7 + 3] << 24)
                | (data[num7 + 2] << 16)
                | (data[num7 + 1] << 8)
                | data[num7]
            )
            num4 = _u32(num4 + num5)
            num4 = _u32(num4 + cFBYLsegA0V(num4))
            num13 = _u32(num4 ^ num6)
            array[num9] = num13 & 0xFF
            array[num9 + 1] = (_u32(num13 & 0xFF00) >> 8) & 0xFF
            array[num9 + 2] = (_u32(num13 & 0xFF0000) >> 16) & 0xFF
            array[num9 + 3] = (_u32(num13 & 0xFF000000) >> 24) & 0xFF
    return bytes(array)


# --------------------------------------------------------------------------- #
# Pinned profiles                                                              #
# --------------------------------------------------------------------------- #
class VerificationError(RuntimeError):
    """A decode/verification step refused to continue."""


@dataclasses.dataclass(frozen=True)
class Profile:
    """One known source build, its resource, and its string-accessor call shape.

    ``resource_sha256`` / ``plaintext_sha256`` / ``entry_count`` / ``anchors``
    are *published expectations*: where they are set they must match exactly.
    Where a build has no published expectation yet (``None`` / empty), the table
    is still parsed strictly and its own values are recorded, but nothing is
    claimed about them.
    """

    label: str
    resource: str
    key_hex: str
    direct_type: str
    direct_method: str
    proxy_type: str
    proxy_method: str
    proxy_slot_field: str
    resource_sha256: str | None = None
    plaintext_sha256: str | None = None
    entry_count: int | None = None
    anchors: tuple[tuple[int, str], ...] = ()
    direct_namespace: str = ""

    def key_bytes(self) -> bytes:
        try:
            return bytes.fromhex(self.key_hex)
        except ValueError as exc:  # pragma: no cover - profile typo guard
            raise VerificationError(f"{self.label}: bad key hex: {exc}") from exc


# The two constants blocks mirror the reviewed sibling tool
# ``resolve-proxy.py``: they are decode constants for an obfuscated third-party
# assembly, pin offline resource decoding only, and never authorize a live call.
PROFILES: dict[str, Profile] = {
    # Genshin 7.1 editor, the current build.
    "565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a": Profile(
        label="editor-7.1",
        resource="7ObTTdEd8bVVgdZyVy.SA0dOcRiWY2ZDNyWjq",
        key_hex="91862bd2074f91b4930ee6d5fe5ec147f6f64bf4393095d16a0dcf1b96a47437",
        direct_type="PgdJdFPLK4PkoLedWk7c",
        direct_method="RcDPXnUGLKY",
        proxy_type="OfHnbKPAfwDjrwrhrnHS",
        proxy_method="vamPAss8BQY",
        proxy_slot_field="UuIPAuUcgRX",
        resource_sha256=(
            "51384a70e1087c4121614f04811b49992816b3303e1283c8162cea0715993397"
        ),
        plaintext_sha256=(
            "ec0776068c00d3c8ec7dfe5bd6dd94613716f14f7b55efd9d3e35605e3233a74"
        ),
        entry_count=2985,
        direct_namespace="j8im30PLy4epfMBwN0Er",
    ),
    # Historical build, verified against the preserved original resource.
    "d4b429a371505ff5252e5a869a8fc250cd0924440a648fdb844a0eebed083841": Profile(
        label="editor-legacy",
        resource="k0NMjJaUgmhZWiMRob.DuimXPmvaoLIiHCe8B",
        key_hex="12fa9ff042a0a8caa5e4c5ef0fbcfe017a21715bc64c4b8bfc8e37641e303e76",
        direct_type="Y9F2H0YhZJ8wH9Xl5wuT",
        direct_method="cBVYLdhAhVY",
        proxy_type="YlKu2QYfNaDsptndNkxX",
        proxy_method="xyVYfsr3qg0",
        proxy_slot_field="EOHYfjqMv7P",
        anchors=((61834, "Resource\\Json\\Beyond\\Node"),),
        resource_sha256="60137d417c6f2fa74e538ef47adddb51828e7d6b08566fe0e53d2cf48cf6b04a",
        plaintext_sha256="89c5896d48b262a8eccd1473139b52b55501c3a129e76a65d4bd5c714134016b",
        entry_count=2830,
    ),
}


@dataclasses.dataclass(frozen=True)
class DecodedTable:
    """A verified decode result. ``table`` maps byte offset -> string."""

    table: dict[int, str]
    entry_count: int
    byte_length: int
    plaintext_sha256: str
    resource_sha256: str
    key_sha256: str
    profile_label: str


# --------------------------------------------------------------------------- #
# Hashing / resource access                                                    #
# --------------------------------------------------------------------------- #
def hash_file(path: Path) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def profile_for_dll(dll: Path) -> tuple[str, Profile | None]:
    """Return ``(sha256, profile)``; profile is None for an unknown build."""
    sha = hash_file(dll)
    return sha, PROFILES.get(sha)


def load_resource(dll: Path, resource_name: str) -> bytes:
    """Read one embedded manifest resource out of the PE image as data.

    ``dnfile`` is imported lazily so the module (and its tests) never need it.
    """
    deps = str(DEPS)
    if deps not in sys.path:
        sys.path.insert(0, deps)
    try:
        import dnfile  # noqa: PLC0415  (deliberately lazy: offline parse only)
    except ImportError as exc:  # pragma: no cover - environment guard
        raise VerificationError(f"dnfile unavailable under {DEPS}: {exc}") from exc

    pe = dnfile.dnPE(str(dll), clr_lazy_load=True)
    for entry in pe.net.resources:
        if str(entry.name) != resource_name:
            continue
        data = entry.data
        if isinstance(data, bytes) and data:
            return data
        raise VerificationError(f"resource {resource_name!r} is empty or unreadable")
    raise VerificationError(f"resource {resource_name!r} not found in {dll}")


# --------------------------------------------------------------------------- #
# Strict table parsing                                                         #
# --------------------------------------------------------------------------- #
def parse_table(plaintext: bytes) -> dict[int, str]:
    """Walk ``[int32 byte-length][UTF-16LE text]`` to the exact end of the blob.

    Every check is fatal.  There is no ``break`` on a bad entry and no
    ``errors="replace"`` on decode, so a truncated or malformed blob raises
    instead of yielding a plausible-looking prefix table.
    """
    table: dict[int, str] = {}
    pos = 0
    total = len(plaintext)
    while pos < total:
        if pos + 4 > total:
            raise VerificationError(f"truncated length field at offset {pos}")
        length = struct.unpack_from("<i", plaintext, pos)[0]
        if length < 0:
            raise VerificationError(f"negative entry length {length} at offset {pos}")
        if length % 2:
            raise VerificationError(f"odd entry length {length} at offset {pos}")
        end = pos + 4 + length
        if end > total:
            raise VerificationError(
                f"entry at offset {pos} needs {end} bytes but table ends at {total}"
            )
        raw = plaintext[pos + 4 : end]
        try:
            text = raw.decode("utf-16-le")
        except UnicodeDecodeError as exc:
            raise VerificationError(
                f"entry at offset {pos} is not valid UTF-16LE: {exc}"
            ) from exc
        table[pos] = text
        pos = end
    return table


def parse_table_json(obj: object) -> dict[int, str]:
    """Load the ``{"offset": "text"}`` form written by :func:`extract`."""
    if not isinstance(obj, dict):
        raise VerificationError("table JSON must be an object of offset -> string")
    table: dict[int, str] = {}
    for key, value in obj.items():
        if not isinstance(value, str):
            raise VerificationError(f"table entry {key!r} is not a string")
        try:
            offset = int(key)
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"table key {key!r} is not an integer") from exc
        if offset < 0:
            raise VerificationError(f"table key {key!r} is negative")
        if offset in table:
            raise VerificationError(f"duplicate table offset {offset}")
        table[offset] = value
    return table


def plaintext_from_table(table: dict[int, str]) -> bytes:
    """Rebuild the exact decoded blob from a table, to re-check its hash.

    Requires offsets to be contiguous from 0, which is what a complete strict
    walk produces; anything else means the JSON was truncated or edited.
    """
    buffer = bytearray()
    for offset in sorted(table):
        if offset != len(buffer):
            raise VerificationError(
                f"table offsets are not contiguous (expected {len(buffer)}, got {offset})"
            )
        try:
            raw = table[offset].encode("utf-16-le")
        except UnicodeEncodeError as exc:
            raise VerificationError(
                f"entry at offset {offset} cannot be re-encoded as UTF-16LE: {exc}"
            ) from exc
        buffer += struct.pack("<i", len(raw)) + raw
    return bytes(buffer)


def table_to_json_obj(table: dict[int, str]) -> dict[str, str]:
    return {str(offset): text for offset, text in sorted(table.items())}


# --------------------------------------------------------------------------- #
# Verify + decode                                                              #
# --------------------------------------------------------------------------- #
def decode_and_verify(resource: bytes, profile: Profile) -> DecodedTable:
    """Decrypt, walk strictly, and check every published expectation."""
    if not resource:
        raise VerificationError(f"{profile.label}: empty resource")

    resource_sha = hashlib.sha256(resource).hexdigest()
    if profile.resource_sha256 and resource_sha != profile.resource_sha256:
        raise VerificationError(
            f"{profile.label}: resource SHA-256 mismatch "
            f"(expected {profile.resource_sha256}, got {resource_sha})"
        )

    key = profile.key_bytes()
    if len(key) < _MIN_KEY_BYTES:
        raise VerificationError(f"{profile.label}: key is shorter than 4 bytes")

    try:
        plaintext = transform(resource, key)
    except ValueError as exc:
        raise VerificationError(f"{profile.label}: transform refused: {exc}") from exc
    if not plaintext:
        raise VerificationError(f"{profile.label}: decryption produced no bytes")

    table = parse_table(plaintext)  # strict: raises rather than truncating
    plain_sha = hashlib.sha256(plaintext).hexdigest()

    if profile.plaintext_sha256 and plain_sha != profile.plaintext_sha256:
        raise VerificationError(
            f"{profile.label}: plaintext SHA-256 mismatch "
            f"(expected {profile.plaintext_sha256}, got {plain_sha})"
        )
    if profile.entry_count is not None and len(table) != profile.entry_count:
        raise VerificationError(
            f"{profile.label}: entry count mismatch "
            f"(expected {profile.entry_count}, got {len(table)})"
        )
    for offset, expected in profile.anchors:
        actual = table.get(offset)
        if actual != expected:
            raise VerificationError(
                f"{profile.label}: anchor offset {offset} is {actual!r}, "
                f"expected {expected!r}"
            )

    return DecodedTable(
        table=table,
        entry_count=len(table),
        byte_length=len(plaintext),
        plaintext_sha256=plain_sha,
        resource_sha256=resource_sha,
        key_sha256=hashlib.sha256(key).hexdigest(),
        profile_label=profile.label,
    )


# --------------------------------------------------------------------------- #
# Legacy compatibility                                                         #
# --------------------------------------------------------------------------- #
def build_table(blob: Path | None = None, key: Path | None = None) -> dict[int, str]:
    """Legacy no-argument entry point: decode the historical artifact pair.

    Kept so callers that used to ``from annotate_strings import build_table`` (or
    the old module-level helper) still work. Unlike the old walker it is strict:
    it raises on a malformed blob instead of returning a prefix.
    """
    blob = Path(blob) if blob is not None else LEGACY_BLOB
    key = Path(key) if key is not None else LEGACY_KEY
    return parse_table(transform(blob.read_bytes(), key.read_bytes()))


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def _exclusive_text(path: Path, text: str, *, encoding="utf-8") -> None:
    with path.open("x", encoding=encoding) as stream:
        stream.write(text)


def extract(dll: Path, out: Path) -> int:
    dll = Path(dll)
    out = Path(out)
    if not dll.is_file():
        print(f"source DLL not found: {dll}", file=sys.stderr)
        return 2
    source_sha, profile = profile_for_dll(dll)
    if profile is None:
        print(
            "unsupported editor DLL for offline string decoding: " + source_sha,
            file=sys.stderr,
        )
        return 2

    try:
        resource = load_resource(dll, profile.resource)
        decoded = decode_and_verify(resource, profile)
    except VerificationError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    # Re-hash after reading: never label output with a SHA the file no longer has.
    if hash_file(dll) != source_sha:
        print("source DLL changed while decoding; refusing to write", file=sys.stderr)
        return 2

    sidecar = Path(str(out) + ".source.json")
    if out.exists() or sidecar.exists():
        print("output already exists; use a new output path", file=sys.stderr)
        return 2

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        _exclusive_text(out,
            json.dumps(table_to_json_obj(decoded.table), ensure_ascii=False),
            encoding="utf-8",
        )
        _exclusive_text(sidecar,
            json.dumps(
                {
                    "tool": "string_table.py",
                    "sourceDll": str(dll.resolve()),
                    "sourceSha256": source_sha,
                    "profile": decoded.profile_label,
                    "resource": profile.resource,
                    "resourceSha256": decoded.resource_sha256,
                    "keySha256": decoded.key_sha256,
                    "tableSha256": decoded.plaintext_sha256,
                    "tableByteLength": decoded.byte_length,
                    "entryCount": decoded.entry_count,
                    "annotationOnly": False,
                    "liveAdapterCompatible": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"refused: output could not be created exclusively: {exc}", file=sys.stderr)
        return 2

    print(
        f"{decoded.profile_label}: entries={decoded.entry_count} "
        f"bytes={decoded.byte_length} tableSha256={decoded.plaintext_sha256}",
        file=sys.stderr,
    )
    print(f"wrote {out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="decode the string table from a known DLL")
    ex.add_argument("--dll", default=str(DEFAULT_DLL))
    ex.add_argument("--out", required=True, help="table JSON path (must be new)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "extract":
        return extract(Path(args.dll), Path(args.out))
    return 2  # pragma: no cover - argparse rejects unknown commands


if __name__ == "__main__":
    raise SystemExit(main())
