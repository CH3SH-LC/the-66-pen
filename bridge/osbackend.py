"""Read-only process observation.

Two backends, and the difference between them is never hidden:

``WindowsCimProcessBackend``
    Runs a *fixed* PowerShell script -- ``Get-CimInstance Win32_Process`` -- and
    filters the result in Python. Nothing is interpolated into the script: no
    caller-supplied path, PID, name or flag ever reaches the command line. It
    only reads.

``MockProcessBackend``
    Simulates observations for tests and for demonstrating the flow without
    starting anything. Every record it produces is tagged ``simulated``, and
    any response built from it carries a loud warning.

There is no third mode, and no "auto" fallback from real to mock. A real
observation that fails is a failure, not a reason to invent one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import decode_tolerantly

#: Fixed query. No interpolation, no parameters, no user input of any kind.
#: ``Select-Object`` narrows the projection; filtering happens in Python so the
#: script text never varies with the request.
PS_QUERY_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "$OutputEncoding=[System.Text.Encoding]::UTF8;"
    "Get-CimInstance -ClassName Win32_Process"
    " | Select-Object -Property ProcessId,Name,ExecutablePath,CreationDate"
    " | ConvertTo-Json -Compress"
)

POWERSHELL = "powershell.exe"
QUERY_TIMEOUT_S = 20.0


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str | None
    executable_path: str | None
    creation_date: str | None
    source: str
    simulated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "name": self.name,
            "executablePath": self.executable_path,
            "creationDate": self.creation_date,
            "source": self.source,
            "simulated": self.simulated,
        }


@dataclass
class BackendStatus:
    kind: str
    simulated: bool
    available: bool
    label: str
    detail: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "simulated": self.simulated,
            "available": self.available,
            "label": self.label,
            "detail": self.detail,
            "checks": self.checks,
        }


class ProcessBackend:
    """Interface. ``list_processes`` must never raise for an ordinary failure."""

    kind = "abstract"
    simulated = False
    label = "abstract"

    def probe(self) -> BackendStatus:  # pragma: no cover - interface
        raise NotImplementedError

    def list_processes(self) -> list[ProcessInfo]:  # pragma: no cover - interface
        raise NotImplementedError

    def query(self) -> tuple[bool, list[ProcessInfo]]:
        """Return ``(succeeded, processes)``.

        The distinction matters: "the query succeeded and found nothing" and
        "the query failed, so we know nothing" are different claims, and code
        that conflates them will eventually report a process as absent when it
        merely could not be looked at.
        """
        try:
            return True, self.list_processes()
        except Exception:  # noqa: BLE001 - a query failure must not become a crash
            return False, []

    def describe(self) -> dict[str, Any]:
        return self.probe().to_dict()


class WindowsCimProcessBackend(ProcessBackend):
    kind = "windows-cim"
    simulated = False
    label = "Windows Get-CimInstance Win32_Process (read-only)"

    def __init__(self) -> None:
        self.last_error: str | None = None

    def probe(self) -> BackendStatus:
        checks: list[dict[str, Any]] = []
        powershell = shutil.which(POWERSHELL)
        checks.append({"check": "powershell-on-path", "ok": powershell is not None, "value": powershell})
        if powershell is None:
            return BackendStatus(
                kind=self.kind,
                simulated=False,
                available=False,
                label=self.label,
                detail=f"{POWERSHELL} not found on PATH; process observation is unavailable",
                checks=checks,
            )
        if os.name != "nt":
            return BackendStatus(
                kind=self.kind,
                simulated=False,
                available=False,
                label=self.label,
                detail="CIM process query is only available on Windows",
                checks=checks,
            )
        return BackendStatus(
            kind=self.kind, simulated=False, available=True, label=self.label, checks=checks
        )

    def list_processes(self) -> list[ProcessInfo]:
        ok, processes = self.query()
        return processes if ok else []

    def query(self) -> tuple[bool, list[ProcessInfo]]:
        try:
            completed = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", PS_QUERY_SCRIPT],
                capture_output=True,
                timeout=QUERY_TIMEOUT_S,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False, []
        if completed.returncode != 0:
            self.last_error = (
                f"powershell exited {completed.returncode}: "
                f"{decode_tolerantly(completed.stderr).strip()[:400]}"
            )
            return False, []
        self.last_error = None
        return True, parse_cim_output(decode_tolerantly(completed.stdout))


def parse_cim_output(text: str) -> list[ProcessInfo]:
    """Parse ``ConvertTo-Json`` output, which is an object when there is one row."""
    text = text.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows = payload if isinstance(payload, list) else [payload]
    out: list[ProcessInfo] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = row.get("ProcessId")
        if not isinstance(pid, int):
            continue
        creation = row.get("CreationDate")
        out.append(
            ProcessInfo(
                pid=pid,
                name=row.get("Name"),
                executable_path=row.get("ExecutablePath"),
                creation_date=creation,
                source="windows-cim",
                simulated=False,
            )
        )
    return out


class MockProcessBackend(ProcessBackend):
    """Simulated observation. Never starts anything, never touches the machine.

    If ``state_path`` is given, the process list is read from that file so that
    a mock launch in one CLI invocation is visible to the next one. Otherwise
    the in-memory list passed to the constructor is used.
    """

    kind = "mock"
    simulated = True
    label = "MOCK PROCESS BACKEND - NOT A REAL OS QUERY"

    def __init__(
        self,
        processes: list[ProcessInfo] | None = None,
        state_path: Path | None = None,
    ) -> None:
        self._processes = list(processes or [])
        self._state_path = state_path

    def probe(self) -> BackendStatus:
        return BackendStatus(
            kind=self.kind,
            simulated=True,
            available=True,
            label=self.label,
            detail=(
                "Simulated observations. Any 'pid', 'creationDate' or process list below "
                "is fabricated for testing and is NOT evidence about this machine."
            ),
            checks=[{"check": "mock-backend-selected", "ok": True, "value": str(self._state_path)}],
        )

    def list_processes(self) -> list[ProcessInfo]:
        if self._state_path is None:
            return list(self._processes)
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        out: list[ProcessInfo] = []
        for row in payload.get("processes", []):
            out.append(
                ProcessInfo(
                    pid=int(row["pid"]),
                    name=row.get("name"),
                    executable_path=row.get("executablePath"),
                    creation_date=row.get("creationDate"),
                    source="mock",
                    simulated=True,
                )
            )
        return out


def build_backend(mode: str, mock_state_path: Path | None = None) -> ProcessBackend:
    if mode == "mock":
        return MockProcessBackend(state_path=mock_state_path)
    return WindowsCimProcessBackend()
