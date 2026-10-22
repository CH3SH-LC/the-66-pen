"""Small shared helpers: UTC timestamps, canonical hashing, tolerant decoding."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """RFC3339 UTC with millisecond precision, e.g. ``2026-09-14T02:11:03.482Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def canonical_json(value: Any) -> str:
    """Deterministic JSON used for request hashing.

    Sort keys and drop whitespace so that two semantically identical requests
    hash identically regardless of key order or formatting.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decode_tolerantly(raw: bytes) -> str:
    """Decode OS command output.

    Windows PowerShell writes to a redirected stdout in whatever
    ``[Console]::OutputEncoding`` happens to be. The query script pins UTF-8,
    but a hostile locale or an older host can still emit something else, so
    fall through a small chain instead of crashing on one bad byte.
    """
    for encoding in ("utf-8-sig", "utf-8", "cp936"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")
