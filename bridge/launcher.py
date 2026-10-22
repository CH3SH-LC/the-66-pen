"""Process launching, deliberately narrow.

The launcher takes one argument: an absolute path that has *already* been
checked against the frozen allowlist in :mod:`bridge.targets`. It does not take
a command string, an argument vector, an environment, or a shell flag.

What this module does **not** do, on purpose:

* no ``shell=True`` anywhere -- there is no shell in the path at all;
* no UI Automation, no ``SendInput``, no window messages, no injection;
* no waiting, no killing, no attaching. It starts a process and steps back.

Elevation is a second, opt-in route on the same terms: ``elevation="request"``
asks Windows to prompt and start the *same* allowlisted executable as
administrator. It is only reachable for the frozen targets that
:mod:`bridge.elevation` permits, and the caller still supplies no path, no argv
and no shell command. A declined prompt creates nothing.

That last point is the honest core of the design. ``Popen`` returning a PID
means a process was created. It does not mean the sandbox loaded, a project was
opened, or anything is ready.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .elevation import ELEVATION_NONE, ELEVATION_REQUEST, request_elevation
from .util import utc_now


@dataclass
class LaunchResult:
    returned: bool
    pid: int | None
    error: str | None
    error_kind: str | None
    simulated: bool
    elevation: str = ELEVATION_NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "returned": self.returned,
            "pid": self.pid,
            "error": self.error,
            "errorKind": self.error_kind,
            "simulated": self.simulated,
            "elevation": self.elevation,
        }


class Launcher:
    kind = "abstract"
    simulated = False

    def launch(
        self,
        executable_path: str,
        cwd: str,
        argv: tuple[str, ...] | list[str] = (),
        elevation: str = ELEVATION_NONE,
    ) -> LaunchResult:  # pragma: no cover
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "simulated": self.simulated}


class RealLauncher(Launcher):
    kind = "subprocess.Popen"
    simulated = False

    def launch(
        self,
        executable_path: str,
        cwd: str,
        argv: tuple[str, ...] | list[str] = (),
        elevation: str = ELEVATION_NONE,
    ) -> LaunchResult:
        if elevation == ELEVATION_REQUEST:
            return self._launch_elevated(executable_path, cwd, argv)

        creationflags = 0
        if os.name == "nt":
            # Detach from this process's console and process group: the child
            # outlives us and must not receive our Ctrl+C.
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        try:
            process = subprocess.Popen(
                [executable_path, *argv],
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError as exc:
            return LaunchResult(
                returned=False,
                pid=None,
                error=f"{type(exc).__name__}: {exc}",
                error_kind="oserror",
                simulated=False,
            )
        except subprocess.SubprocessError as exc:
            return LaunchResult(
                returned=False,
                pid=None,
                error=f"{type(exc).__name__}: {exc}",
                error_kind="subprocess-error",
                simulated=False,
            )
        return LaunchResult(returned=True, pid=process.pid, error=None, error_kind=None, simulated=False)

    def _launch_elevated(
        self, executable_path: str, cwd: str, argv: tuple[str, ...] | list[str]
    ) -> LaunchResult:
        """``ShellExecuteExW`` verb=runas, with the handle closed immediately."""
        result = request_elevation(executable_path, cwd, argv)
        return LaunchResult(
            returned=result.returned,
            pid=result.pid,
            error=result.error,
            error_kind=result.error_kind,
            simulated=False,
            elevation=ELEVATION_REQUEST,
        )


class MockLauncher(Launcher):
    """Records the launch request; starts nothing.

    The simulated process is appended to a state file so that a later mock
    observation can "see" it. PIDs are drawn from a reserved range so nobody
    mistakes one for a real process id.

    An elevated mock is recorded with ``executablePath: None``, because that is
    what a real elevated game process looks like from here: its path cannot be
    read back, so the observation can only be a pid match.
    """

    kind = "mock"
    simulated = True
    MOCK_PID_BASE = 900000

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def launch(
        self,
        executable_path: str,
        cwd: str,
        argv: tuple[str, ...] | list[str] = (),
        elevation: str = ELEVATION_NONE,
    ) -> LaunchResult:
        elevated = elevation == ELEVATION_REQUEST
        state = {"processes": [], "note": "MOCK LAUNCHER - no process was started"}
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        processes = state.setdefault("processes", [])
        pid = self.MOCK_PID_BASE + len(processes) + 1
        processes.append(
            {
                "pid": pid,
                "name": os.path.basename(executable_path),
                "executablePath": None if elevated else executable_path,
                "creationDate": utc_now(),
                "argv": list(argv),
                "elevation": elevation,
                "simulated": True,
                "note": (
                    "SIMULATED - no such process exists on this machine"
                    + (
                        "; elevated, so its ExecutablePath is simulated as unreadable"
                        if elevated
                        else ""
                    )
                ),
            }
        )
        state["note"] = "MOCK LAUNCHER - no process was started"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return LaunchResult(
            returned=True, pid=pid, error=None, error_kind=None, simulated=True,
            elevation=elevation,
        )


def build_launcher(mode: str, mock_state_path: Path) -> Launcher:
    if mode == "mock":
        return MockLauncher(mock_state_path)
    return RealLauncher()
