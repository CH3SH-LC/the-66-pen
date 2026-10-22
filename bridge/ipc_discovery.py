"""mw.ipc.discover -- read-only discovery of the Miliastra editor IPC endpoint.

Reads the single IPC port DWORD under HKCU, validates it, and asks Windows
whether anything is bound to it. No window is opened or focused, the game is
never launched, the registry is never written, no packet is sent -- only a
registry read and kernel TCP state. The key name is derived, not guessed:
port_h<djb2-xor("port")>, djb2 with xor, seed 5381, uint32; the port is read
at runtime, so no port number is baked into this file. A listener is not
evidence the protocol works -- protocolVerified stays false and
gameControlAvailable stays "unknown" until something actually speaks to it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import winreg
from typing import Any

METHOD = "mw.ipc.discover"
REGISTRY_SOURCE = r"HKCU\Software\miHoYo\BeyondAssistEditor"
REG_ROOT = r"Software\miHoYo\BeyondAssistEditor"
PORT_FIELD = "port"
PORT_MIN, PORT_MAX = 1, 65535
QUERY_TIMEOUT_S = 10
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # never pop a console
UNKNOWN = "unknown"


def djb2_xor(text: str, seed: int = 5381) -> int:
    """djb2-xor over the field name, truncated to uint32."""
    h = seed
    for byte in text.encode("utf-8"):
        h = ((h * 33) ^ byte) & 0xFFFFFFFF
    return h


KEY_NAME = f"{PORT_FIELD}_h{djb2_xor(PORT_FIELD)}"


def read_port() -> tuple[int | None, str | None]:
    """Return (port, error). Read-only; touches exactly one registry value."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_ROOT, 0, winreg.KEY_READ) as key:
            raw, kind = winreg.QueryValueEx(key, KEY_NAME)
    except OSError as exc:
        return None, f"registry unavailable: {exc.__class__.__name__}"
    if kind != winreg.REG_DWORD:
        return None, f"{KEY_NAME} is not REG_DWORD"
    if not PORT_MIN <= int(raw) <= PORT_MAX:
        return None, f"{KEY_NAME} outside {PORT_MIN}..{PORT_MAX}"
    return int(raw), None


# CIM rather than Get-NetTCPConnection: "nothing bound" returns an empty set, not a
# non-terminating error, so empty and failure stay distinguishable. Still wrapped in
# try/catch + ConvertTo-Json; only rows matching this one port are emitted, so no
# address or unrelated endpoint ever reaches the report.
_PS_QUERY = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'Stop'
$port = %d
$status = 'ok'; $errorText = $null; $listeners = @(); $connections = @()
$names = 'Closed,Listen,SynSent,SynReceived,Established,FinWait1,FinWait2,CloseWait,Closing,LastAck,TimeWait,DeleteTcb,Bound'.Split(',')
try {
  $hits = @(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter "LocalPort=$port OR RemotePort=$port")
  $procs = @{}
  foreach ($p in @($hits | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)) {
    try { $procs[$p] = (Get-Process -Id $p -ErrorAction Stop).ProcessName } catch { $procs[$p] = 'unknown' }
  }
  foreach ($c in $hits) {
    $owner = [int]$c.OwningProcess
    $row = [ordered]@{ pid = $owner; process = $procs[$owner]; state = $names[[int]$c.State - 1]; match = $(if ([int]$c.LocalPort -eq $port) { 'local' } else { 'remote' }) }
    if ([int]$c.State -eq 2) { $listeners += $row } else { $connections += $row }
  }
} catch {
  $status = 'error'; $errorText = $_.Exception.GetType().Name
}
$r = [ordered]@{ status = $status; error = $errorText; listeners = $listeners; connections = $connections }
ConvertTo-Json -InputObject $r -Depth 5 -Compress
"""


def _rows(value: Any) -> list[dict[str, Any]]:
    """ConvertTo-Json can collapse a one-element array into a bare object."""
    rows = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
    return [row for row in rows if isinstance(row, dict)]


_FAILED: dict[str, Any] = {"status": "error", "listeners": [], "connections": []}


def query_endpoints(port: int) -> dict[str, Any]:
    """Ask Windows about this one port. Failure is reported, never silently empty."""
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _PS_QUERY % port],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=QUERY_TIMEOUT_S, stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**_FAILED, "error": f"probe did not run: {exc.__class__.__name__}"}
    try:
        parsed = json.loads(done.stdout.strip() or "{}")
    except ValueError:
        return {**_FAILED, "error": "probe produced unparseable output"}
    if not isinstance(parsed, dict) or parsed.get("status") != "ok":
        reason = parsed.get("error") if isinstance(parsed, dict) else None
        return {**_FAILED, "error": str(reason or "probe reported failure")}
    return {"status": "ok", "error": None, "listeners": _rows(parsed.get("listeners")),
            "connections": _rows(parsed.get("connections"))}


def discover() -> dict[str, Any]:
    """Never raises. A failed probe reports "unknown", never "no listener"."""
    port, error = read_port()
    result: dict[str, Any] = {
        "method": METHOD, "registrySource": REGISTRY_SOURCE, "keyName": KEY_NAME,
        "port": port, "listenerPresent": UNKNOWN, "listeners": [], "connections": [],
        "gameControlAvailable": UNKNOWN, "protocolVerified": False, "error": error,
    }
    if port is None:
        return result
    found = query_endpoints(port)
    if found["status"] != "ok":
        result["error"] = found["error"]
        return result
    result["listeners"], result["connections"] = found["listeners"], found["connections"]
    result["listenerPresent"] = bool(found["listeners"])
    return result


def main() -> int:
    print(json.dumps(discover(), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
