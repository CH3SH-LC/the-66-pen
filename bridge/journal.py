"""Append-only journal: the durable record of everything the bridge has done.

One JSON object per line, flushed and ``fsync``-ed on every append. The journal
is the single source of truth for the revision counter, the idempotency table
and the state of every operation, so that a process that dies mid-operation
leaves behind a readable account of what it had started.

Record kinds, in the order a successful mutation writes them:

``intent``   written *before* any external effect. Carries the idempotency key
             and request hash, so a replay after a crash is detectable.
``launched`` written after ``subprocess`` returned a PID. Absence of this
             record after an ``intent`` is the crash window.
``observed`` what the OS backend actually saw, including "nothing".
``terminal`` the final status plus the response ``data``, replayed verbatim to
             an identical later request.

Folding these records reconstructs state. An ``intent`` without a ``terminal``
is recovered as ``indeterminate`` -- never as success, and never silently
retried.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import utc_now

RECORD_KINDS = frozenset({"intent", "launched", "observed", "terminal"})


@dataclass
class FoldedState:
    """Result of replaying the journal."""

    revision: int = 0
    last_fence: int = 0
    operations: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: (method, idempotencyKey) -> record
    idempotency: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    record_count: int = 0
    skipped_lines: list[dict[str, Any]] = field(default_factory=list)
    #: Backend mode the journal was written under. ``None`` for an empty journal.
    mode: str | None = None
    modes_seen: set[str] = field(default_factory=set)

    @property
    def unresolved_operations(self) -> list[dict[str, Any]]:
        """Operations that were started and never reached a terminal record."""
        out = []
        for operation_id, op in sorted(self.operations.items()):
            if op.get("terminal") is None:
                out.append(
                    {
                        "operationId": operation_id,
                        "method": op.get("method"),
                        "effectState": op.get("effectState", "unknown"),
                        "startedAt": op.get("startedAt"),
                        "reason": (
                            "An intent record exists with no terminal record. The process "
                            "died (or the journal was truncated) between recording the "
                            "intent and recording the outcome, so the external effect is "
                            "unknown. It is reported as indeterminate and is never "
                            "replayed automatically."
                        ),
                    }
                )
        return out


def read_records(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the journal, tolerating a torn final line.

    A crash during ``write`` can leave a partial line. Only the *last*
    non-empty line is allowed to be malformed -- that is the crash signature.
    A malformed line anywhere else means genuine corruption and is reported as
    such, because silently skipping it could hide a lost terminal record.
    """
    if not path.exists():
        return [], []

    issues: list[dict[str, Any]] = []
    raw_lines: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [{"kind": "unreadable", "error": f"{type(exc).__name__}: {exc}"}]

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            raw_lines.append((number, line))

    records: list[dict[str, Any]] = []
    for index, (number, line) in enumerate(raw_lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            is_last = index == len(raw_lines) - 1
            issues.append(
                {
                    "kind": "torn-last-line" if is_last else "corrupt-line",
                    "line": number,
                    "error": str(exc),
                    "recovered": is_last,
                }
            )
            if not is_last:
                raise JournalCorrupt(f"journal line {number} is not valid JSON: {exc}") from exc
            continue
        if not isinstance(record, dict) or "seq" not in record or "kind" not in record:
            issues.append({"kind": "malformed-record", "line": number, "recovered": False})
            raise JournalCorrupt(f"journal line {number} is not a bridge record")
        records.append(record)

    return records, issues


class JournalCorrupt(Exception):
    """Raised when the journal cannot be trusted. Fail closed, do not guess."""


def fold(records: list[dict[str, Any]], issues: list[dict[str, Any]]) -> FoldedState:
    """Replay records into the state a fresh process needs."""
    state = FoldedState(record_count=len(records), skipped_lines=issues)

    for record in records:
        kind = record.get("kind")
        payload = record.get("data") or {}
        mode = record.get("mode")
        if mode:
            state.modes_seen.add(mode)
            state.mode = mode

        if kind == "intent":
            operation_id = payload["operationId"]
            state.operations[operation_id] = {
                "operationId": operation_id,
                "method": payload.get("method"),
                "target": payload.get("target"),
                "requestId": payload.get("requestId"),
                "startedAt": record.get("ts"),
                "fence": payload.get("fence"),
                "effectState": "not-started",
                "launched": None,
                "observed": None,
                "terminal": None,
            }
            state.last_fence = max(state.last_fence, int(payload.get("fence") or 0))
            key = payload.get("idempotencyKey")
            if key:
                state.idempotency[(payload["method"], key)] = {
                    "state": "in-progress",
                    "requestHash": payload.get("requestHash"),
                    "operationId": operation_id,
                    "recordedAt": record.get("ts"),
                }

        elif kind == "launched":
            op = state.operations.get(payload["operationId"])
            if op is not None:
                op["launched"] = payload
                op["effectState"] = "sent"

        elif kind == "observed":
            op = state.operations.get(payload["operationId"])
            if op is not None:
                op["observed"] = payload
                op["effectState"] = payload.get("effectState", "observed")

        elif kind == "terminal":
            operation_id = payload["operationId"]
            op = state.operations.get(operation_id)
            if op is not None:
                op["terminal"] = payload
                op["effectState"] = payload.get("effectState", op["effectState"])
            state.revision = max(state.revision, int(payload.get("revision") or 0))
            key = payload.get("idempotencyKey")
            method = payload.get("method")
            if key and method:
                state.idempotency[(method, key)] = {
                    "state": "completed",
                    "requestHash": payload.get("requestHash"),
                    "operationId": operation_id,
                    "status": payload.get("status"),
                    "envelope": payload.get("envelope") or {},
                    "error": payload.get("error"),
                    "revision": payload.get("revision"),
                    "recordedAt": record.get("ts"),
                }

    # Recovery: an intent with no terminal is an unknown outcome.
    for op in state.operations.values():
        if op["terminal"] is None:
            op["effectState"] = "indeterminate"
            key = None
            for (method, candidate), entry in state.idempotency.items():
                if entry.get("operationId") == op["operationId"]:
                    key = (method, candidate)
                    break
            if key is not None:
                state.idempotency[key]["state"] = "interrupted"

    return state


class Journal:
    """Append-only writer. Append only while holding the bridge write lock."""

    def __init__(self, path: Path, mode: str = "real") -> None:
        self.path = path
        self.mode = mode
        self._seq = 0
        self._fh = None

    def open(self, start_seq: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = start_seq
        self._fh = open(self.path, "a", encoding="utf-8", newline="\n")

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        if kind not in RECORD_KINDS:
            raise AssertionError(f"unknown journal record kind: {kind}")
        self._seq += 1
        # ``mode`` is stamped on every record so that a simulated outcome can
        # never be replayed later as if it had happened for real.
        record = {"seq": self._seq, "ts": utc_now(), "kind": kind, "mode": self.mode, "data": data}
        self._fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        return record

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
