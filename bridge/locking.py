"""Cross-process write lock.

An OS advisory lock on a real file, not an in-process flag. Two bridge
invocations in different processes -- or in different sessions, or started by
different agents -- contend on the same primitive and one of them loses.

Windows uses ``msvcrt.locking``; POSIX uses ``fcntl.flock``. Both are released
by the kernel when the process dies, so a crash cannot leave a permanent
deadlock the way a hand-rolled "lock file exists" scheme would.

The lock is held for the duration of one request only. The fencing token and
owner metadata written alongside it are diagnostics: the OS lock is the
authority, the metadata only explains who held it.
"""

from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import BridgeError
from .util import utc_now

if os.name == "nt":  # pragma: no cover - platform branch
    import msvcrt
else:  # pragma: no cover - platform branch
    import fcntl


@dataclass
class LockHandle:
    path: Path
    pid: int
    host: str
    acquired_at: str
    fence: int
    wait_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "lockFile": str(self.path),
            "ownerPid": self.pid,
            "ownerHost": self.host,
            "acquiredAt": self.acquired_at,
            "fence": self.fence,
            "waitedMs": self.wait_ms,
        }


class FileWriteLock:
    """Exclusive inter-process lock backed by a byte-range lock on a file."""

    def __init__(self, path: Path, timeout_s: float = 5.0, poll_s: float = 0.05) -> None:
        self.path = path
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._fh = None

    def _try_acquire(self) -> bool:
        self._fh = open(self.path, "a+b")
        try:
            # Windows byte-range locks apply to a region; make sure it exists.
            self._fh.seek(0, os.SEEK_END)
            if self._fh.tell() == 0:
                self._fh.write(b"\0")
                self._fh.flush()
            self._fh.seek(0)
            if os.name == "nt":  # pragma: no cover - platform branch
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover - platform branch
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False

    def acquire(self, fence: int) -> LockHandle:
        started = time.monotonic()
        while True:
            if self._try_acquire():
                break
            if time.monotonic() - started >= self.timeout_s:
                raise BridgeError(
                    "LOCK_HELD",
                    "another bridge process holds the project write lock",
                    phase="authorize",
                    retryable=True,
                    details={"lockFile": str(self.path), "timeoutMs": int(self.timeout_s * 1000)},
                )
            time.sleep(self.poll_s)

        handle = LockHandle(
            path=self.path,
            pid=os.getpid(),
            host=socket.gethostname(),
            acquired_at=utc_now(),
            fence=fence,
            wait_ms=int((time.monotonic() - started) * 1000),
        )
        self.persist_metadata(handle)
        return handle

    def persist_metadata(self, handle: LockHandle) -> None:
        """Best-effort owner note. Informational only -- never used to decide."""
        try:
            self.path.with_suffix(".meta.json").write_text(
                json.dumps(handle.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            if os.name == "nt":  # pragma: no cover - platform branch
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - platform branch
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "FileWriteLock":
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()
