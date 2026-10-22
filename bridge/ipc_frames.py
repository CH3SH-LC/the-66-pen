"""Pure offline codec for the Miliastra Wonderland editor IPC frame format.

Bytes in, bytes out. No sockets, no subprocess, no UI, no MCP send tools.
This module never transmits anything and never touches the game directory.

Wire layout, every integer big-endian::

    ushort  magic          = 0x0656
    ushort  message_id
    uint32  payload_length
    byte[]  payload        each byte XOR 0xEA
    ushort  magic          = 0x0666

8 bytes of header + 2 of tail = 10 bytes of overhead.

See IPC-FRAMES.md for the source evidence, the static derivation, and the
list of things that are deliberately *not* verified.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC_HEAD = 0x0656
MAGIC_TAIL = 0x0666
XOR_KEY = 0xEA
HEADER_SIZE = 8  # magic(2) + message_id(2) + payload_length(4)
TAIL_SIZE = 2
OVERHEAD = HEADER_SIZE + TAIL_SIZE  # 10

# Our own resource guard, NOT an official protocol limit. See IPC-FRAMES.md.
DEFAULT_MAX_PAYLOAD = 1 << 20  # 1 MiB

_HEADER = struct.Struct(">HHI")
_TAIL = struct.Struct(">H")

__all__ = [
    "Frame",
    "MAGIC_HEAD",
    "MAGIC_TAIL",
    "XOR_KEY",
    "HEADER_SIZE",
    "TAIL_SIZE",
    "OVERHEAD",
    "DEFAULT_MAX_PAYLOAD",
    "encode_frame",
    "decode_one",
]


@dataclass(frozen=True)
class Frame:
    """One decoded frame. ``payload`` is plaintext, already unmasked."""

    message_id: int
    payload: bytes


def _as_message_id(value: object) -> int:
    """Validate an outgoing message id. bool is rejected on purpose."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"message_id must be int, got {type(value).__name__}")
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"message_id out of ushort range: {value}")
    return value


def _as_max_payload(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"max_payload must be a non-negative int, got {value!r}")
    return value


def _as_bytes(value: object, what: str) -> bytes:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise ValueError(f"{what} must be bytes-like, got {type(value).__name__}")


def encode_frame(
    message_id: int, payload: bytes, max_payload: int = DEFAULT_MAX_PAYLOAD
) -> bytes:
    """Encode one frame. Raises ValueError on a bad id or oversized payload."""
    ident = _as_message_id(message_id)
    limit = _as_max_payload(max_payload)
    raw = _as_bytes(payload, "payload")
    if len(raw) > limit:
        raise ValueError(f"payload is {len(raw)} bytes, over the {limit}-byte limit")
    masked = bytes(b ^ XOR_KEY for b in raw)
    return _HEADER.pack(MAGIC_HEAD, ident, len(raw)) + masked + _TAIL.pack(MAGIC_TAIL)


def decode_one(data: bytes, max_payload: int = DEFAULT_MAX_PAYLOAD):
    """Decode the first frame in ``data``.

    Returns ``(Frame, consumed)``, or ``None`` when ``data`` holds only a prefix
    of a frame -- truncated header, body, or tail. Callers draining a stream
    should wait for more bytes and retry with the same buffer.

    Bytes past ``consumed`` belong to the next frame and are left untouched, so
    a concatenation of frames can be drained in a loop.

    Raises ValueError for a wrong head or tail magic, or for a declared length
    above ``max_payload``. The declared length is checked *before* the buffer is
    inspected for completeness, so a hostile 4 GiB claim is rejected outright
    instead of waited on. Message ids are never rejected here: an unknown id is
    kept as-is, because this module does not know or guess any id's meaning.
    """
    limit = _as_max_payload(max_payload)
    buf = _as_bytes(data, "data")
    if len(buf) < HEADER_SIZE:
        return None  # no complete header to judge yet
    magic, ident, length = _HEADER.unpack_from(buf, 0)
    if magic != MAGIC_HEAD:
        raise ValueError(f"bad head magic 0x{magic:04x}, expected 0x{MAGIC_HEAD:04x}")
    if length > limit:
        raise ValueError(f"declared payload length {length} exceeds the {limit}-byte limit")
    end = HEADER_SIZE + length
    if len(buf) < end + TAIL_SIZE:
        return None  # body and/or tail still missing
    tail = _TAIL.unpack_from(buf, end)[0]
    if tail != MAGIC_TAIL:
        raise ValueError(f"bad tail magic 0x{tail:04x}, expected 0x{MAGIC_TAIL:04x}")
    payload = bytes(b ^ XOR_KEY for b in buf[HEADER_SIZE:end])
    return Frame(ident, payload), end + TAIL_SIZE
