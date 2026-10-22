"""Project state: paths, the write-lock session, and read-only snapshots.

State lives under ``<project>/.runtime/bridge/``. That directory is inside the
project's ``.runtime/`` tree, which the repository already ignores, so journal
contents never enter version control.

**Simulated and real state are kept apart.** A launch performed by the mock
launcher returns a fabricated PID and a fabricated observation; if that outcome
were recorded in the same journal as real ones, a later idempotent replay would
hand back a simulated result as though it were real. So the two modes get
separate directories *and* the mode is stamped into every record, and a store
refuses to read a journal written under a different mode. Isolation is the
primary defence; the stamp is the backstop that catches a misconfiguration
rather than trusting that one never happens.

``locked()``
    Mutation path. Takes the cross-process write lock, folds the journal, opens
    it for append, and releases everything on exit.

``read_state()``
    Read path. No lock. A reader may catch a torn final line mid-append; the
    reader tolerates exactly that case and nothing else.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import BridgeError
from .journal import FoldedState, Journal, JournalCorrupt, fold, read_records
from .locking import FileWriteLock, LockHandle

STATE_MODES = ("real", "mock")


@dataclass
class Session:
    journal: Journal
    state: FoldedState
    lock: FileWriteLock
    lock_handle: LockHandle

    def set_fence(self, fence: int) -> None:
        self.lock_handle.fence = fence
        self.lock.persist_metadata(self.lock_handle)

    def next_fence(self) -> int:
        return self.state.last_fence + 1

    def next_operation_id(self) -> str:
        return f"op-{self.state.record_count + 1:012d}"

    def evidence(self, seq: int, kind: str, *, simulated: bool = False) -> dict[str, Any]:
        return {
            "artifactId": f"journal:{seq:012d}",
            "kind": kind,
            "simulated": simulated,
            "path": str(self.journal.path),
        }


@dataclass
class BridgePaths:
    root: Path
    #: Directory actually holding lock + journal for the selected mode.
    base: Path
    lock: Path
    journal: Path
    mock_dir: Path
    mock_processes: Path


class BridgeStore:
    def __init__(self, root: Path, mode: str = "real", lock_timeout_s: float = 5.0) -> None:
        if mode not in STATE_MODES:
            raise AssertionError(f"unknown state mode: {mode}")
        root = Path(root)
        self.mode = mode
        base = root if mode == "real" else root / "mock"
        self.paths = BridgePaths(
            root=root,
            base=base,
            lock=base / "write.lock",
            journal=base / "journal.jsonl",
            mock_dir=root / "mock",
            mock_processes=root / "mock" / "processes.json",
        )
        self.lock_timeout_s = lock_timeout_s

    def ensure_dirs(self) -> None:
        self.paths.base.mkdir(parents=True, exist_ok=True)
        self.paths.mock_dir.mkdir(parents=True, exist_ok=True)

    def _fold(self) -> tuple[FoldedState, list[dict[str, Any]]]:
        try:
            records, issues = read_records(self.paths.journal)
            state = fold(records, issues)
        except JournalCorrupt as exc:
            # A corrupt journal is never guessed at: fail closed rather than
            # silently starting a new history on top of a damaged one.
            raise BridgeError(
                "JOURNAL_CORRUPT",
                str(exc),
                phase="preflight",
                details={"journal": str(self.paths.journal)},
            ) from exc
        self._assert_mode_matches(state)
        return state, issues

    def _assert_mode_matches(self, state: FoldedState) -> None:
        """Refuse to run against a journal written by the other backend mode."""
        foreign = state.modes_seen - {self.mode}
        if not foreign:
            return
        raise BridgeError(
            "STATE_MODE_MISMATCH",
            f"this journal was written in mode(s) {sorted(foreign)} but the bridge is "
            f"running in mode {self.mode!r}; refusing to read or replay across modes",
            phase="preflight",
            details={
                "journal": str(self.paths.journal),
                "expectedMode": self.mode,
                "foundModes": sorted(state.modes_seen),
                "note": (
                    "Simulated and real outcomes must never share a journal: an "
                    "idempotent replay would otherwise return a fabricated result as "
                    "if it were real. Real state lives in .runtime/bridge/, mock state "
                    "in .runtime/bridge/mock/."
                ),
            },
        )

    def read_state(self) -> tuple[FoldedState, list[dict[str, Any]]]:
        """Lock-free snapshot for read-only methods."""
        return self._fold()

    @contextmanager
    def locked(self) -> Iterator[Session]:
        """Exclusive mutation context across processes."""
        self.ensure_dirs()
        lock = FileWriteLock(self.paths.lock, timeout_s=self.lock_timeout_s)
        handle = lock.acquire(fence=0)
        journal = Journal(self.paths.journal, mode=self.mode)
        try:
            state, _ = self._fold()
            # A torn final line was never a durable record, so the last parsed
            # record's seq -- which equals record_count -- is the right high-water
            # mark to continue from.
            journal.open(start_seq=state.record_count)
            yield Session(journal=journal, state=state, lock=lock, lock_handle=handle)
        finally:
            journal.close()
            lock.release()
