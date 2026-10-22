#!/usr/bin/env python3
"""Host-level probes shared by ``new-scope.py`` and ``load-bridge.py``.

These are the three things the two ``.ps1`` scripts got from the PowerShell host and
that have no direct line-for-line Python statement:

  1. the target process's *name*, *image path* and *start ticks*  (``Get-Process``);
  2. the Authenticode status of the injector binaries  (``Get-AuthenticodeSignature``);
  3. ``ConvertTo-Json`` / ``[IO.File]::WriteAllText`` byte shape for the run artifacts.

Everything else in the two scripts is ordinary control flow and lives in the scripts
themselves.  Nothing here starts, stops or signals any process; it only queries.

FIDELITY / STRENGTH NOTES
-------------------------
**Start ticks.**  ``$proc.StartTime.ToUniversalTime().Ticks`` on Windows is
``GetProcessTimes``' FILETIME (100 ns units since 1601-01-01) shifted to .NET's epoch
(100 ns units since 0001-01-01); the offset is a constant.  ``psutil`` would report
this as a float and window it through float64, which **loses low digits** -- measured
here, ``psutil`` returned a value one tick below the real one for the same process.
So :func:`process_start_utc_ticks` calls ``GetProcessTimes`` through ``ctypes`` and
keeps the exact 64-bit integer.  This is the same kernel source PowerShell reads.

**Authenticode.**  The .ps1 asks ``Get-AuthenticodeSignature ... .Status -ne 'Valid'``.
Two substitutes are provided and neither silently weakens the check:
  * ``cmdlet`` -- runs ``powershell.exe -NoProfile -NonInteractive -Command`` with the
    very same cmdlet.  This is *the same check*, not an analogue; execution policy
    does not apply to ``-Command`` (only to script files), and nothing here changes
    any execution policy.  The path is passed through an environment variable so no
    value is ever interpolated into the command text.
  * ``wintrust`` -- calls ``WinVerifyTrust`` (wintrust.dll) via ``ctypes``: the Win32
    API the cmdlet itself wraps.  Status is ``Valid`` iff the HRESULT is 0, i.e. the
    file is signed *and* its chain builds to a trusted root.  It maps the documented
    HRESULTs to the status names the cmdlet would print.  Strength: equal for
    signature/chain validity; it does not distinguish every cmdlet status string, so
    non-``Valid`` outcomes are reported as the closest named failure.
``auto`` (the default used by the scripts) prefers the cmdlet and falls back to
``wintrust`` only when no PowerShell host can be launched.  If neither is available
the caller refuses -- an unverifiable signature is never accepted.

**JSON shape.**  ``ConvertTo-Json`` (Windows PowerShell 5.1) writes ``{\r\n`` then
``    "key":  value`` -- four-space indent, **two** spaces after the colon, CRLF --
and escapes ``<>&'`` as ``\\u00XX``.  :func:`ps_convert_to_json` reproduces that byte
shape; :func:`write_json_file` mirrors ``[IO.File]::WriteAllText`` (UTF-8 **without**
BOM) and :func:`write_result_file` mirrors ``Set-Content -Encoding utf8`` (which does
add a BOM in 5.1).  Key *order* cannot be reproduced: PowerShell writes a hashtable in
bucket order, and this port writes insertion order.  JSON members are unordered to
every consumer here (``System.Text.Json`` with ``JsonUnmappedMemberHandling.Disallow``).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


class ProcessQueryError(RuntimeError):
    """The pid could not be opened or queried (``Get-Process -Id`` would have thrown)."""


class ImageUnreadableError(RuntimeError):
    """``$proc.MainModule.FileName`` threw; the .ps1 maps this to TARGET_IMAGE_UNREADABLE."""

    def __init__(self, process_name: str, cause: Exception):
        super().__init__("TARGET_IMAGE_UNREADABLE:" + process_name)
        self.process_name = process_name
        self.cause = cause


# ---------------------------------------------------------------------------
# 1. Process facts
# ---------------------------------------------------------------------------

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

#: .NET ticks at the FILETIME epoch.  ``datetime(1,1,1,UTC)`` is this many 100 ns
#: ticks before 1601-01-01, so ``dotnet_ticks = filetime + EPOCH_DIFF``.
_FILETIME_EPOCH_DIFF = 504911232000000000


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _open_query_handle(pid: int):
    handle = _kernel32().OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        raise ProcessQueryError(
            "Cannot find a process with the process identifier %d. (OpenProcess error %d)"
            % (int(pid), ctypes.get_last_error()))
    return handle


def _strip_exe(image: str) -> str:
    base = os.path.basename(image)
    stem, extension = os.path.splitext(base)
    return stem if extension else base


def process_name(pid: int) -> str:
    """``$proc.ProcessName`` -- the image base name **without** its extension.

    ``$proc.ProcessName`` is readable even for a process whose main module is not, so
    a ``QueryFullProcessImageNameW`` failure falls back to the process snapshot
    (``psutil``, the same source ``Get-Process`` uses) before refusing.  This keeps the
    .ps1's ordering intact: the allowed-name check reports
    ``TARGET_NOT_ALLOWED:process-name`` before anything tries to read the image path.
    """
    try:
        return _strip_exe(process_image_path(pid))
    except (ProcessQueryError, ImageUnreadableError) as unreadable:
        try:
            import psutil
            return _strip_exe(psutil.Process(int(pid)).name())
        except Exception:                                     # noqa: BLE001
            raise unreadable


def process_image_path(pid: int) -> str:
    """``$proc.MainModule.FileName`` -- the full image path.

    Raises :class:`ImageUnreadableError` (whose message is already the .ps1's
    ``TARGET_IMAGE_UNREADABLE:<name>`` refusal) when the path cannot be resolved.
    QueryFullProcessImageNameW returns the DOS path, matching what PS reports.
    """
    name_for_error = "pid-" + str(int(pid))
    handle = None
    try:
        handle = _open_query_handle(pid)
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(32768)
        ok = _kernel32().QueryFullProcessImageNameW(
            wintypes.HANDLE(handle), 0, buffer, ctypes.byref(size))
        if not ok:
            raise ImageUnreadableError(name_for_error, OSError(ctypes.get_last_error(), "QueryFullProcessImageNameW"))
        return buffer.value
    except ProcessQueryError:
        raise
    except ImageUnreadableError:
        raise
    except OSError as error:
        raise ImageUnreadableError(name_for_error, error)
    finally:
        if handle:
            _kernel32().CloseHandle(wintypes.HANDLE(handle))


def process_start_utc_ticks(pid: int) -> int:
    """``$proc.StartTime.ToUniversalTime().Ticks`` -- exact, as a 64-bit integer."""
    handle = None
    try:
        handle = _open_query_handle(pid)
        creation = _FILETIME()
        exit_time = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        ok = _kernel32().GetProcessTimes(
            wintypes.HANDLE(handle), ctypes.byref(creation), ctypes.byref(exit_time),
            ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            raise ProcessQueryError(
                "GetProcessTimes failed for pid %d (error %d)"
                % (int(pid), ctypes.get_last_error()))
        filetime = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return filetime + _FILETIME_EPOCH_DIFF
    finally:
        if handle:
            _kernel32().CloseHandle(wintypes.HANDLE(handle))


# ---------------------------------------------------------------------------
# 2. Authenticode
# ---------------------------------------------------------------------------

_KNOWN_HRESULTS = {
    0x800B0100: "NotSigned",            # TRUST_E_NOSIGNATURE
    0x80096010: "HashMismatch",         # TRUST_E_BAD_DIGEST
    0x800B0111: "NotTrusted",           # TRUST_E_EXPLICIT_DISTRUST
    0x800B0109: "UntrustedRoot",        # CERT_E_UNTRUSTEDROOT
    0x800B010A: "UntrustedRoot",        # CERT_E_CHAINING
    0x800B0101: "NotTrusted",           # CERT_E_EXPIRED
    0x80096005: "UnknownError",         # TRUST_E_TIME_STAMP
}

_PS_EXE_CANDIDATES = (
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    "powershell.exe",
)


def _authenticode_via_cmdlet(path: str):
    """``Get-AuthenticodeSignature`` through a one-shot ``-Command`` (no script file)."""
    executable = next((candidate for candidate in _PS_EXE_CANDIDATES
                       if candidate == "powershell.exe" or os.path.isfile(candidate)), None)
    if executable is None:
        return None
    environment = dict(os.environ)
    # Passed by environment variable: no caller value is interpolated into the
    # command text, so a path can never break out of the argument.
    environment["MILIASTRA_AUTHENTICODE_PATH"] = str(path)
    command = "(Get-AuthenticodeSignature -LiteralPath $env:MILIASTRA_AUTHENTICODE_PATH).Status"
    try:
        completed = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=120, env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    status_text = (completed.stdout or "").strip().splitlines()
    if completed.returncode != 0 or not status_text:
        return None
    return (status_text[-1].strip(), "Get-AuthenticodeSignature (-Command, same cmdlet as the .ps1)")


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class _WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
                ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.POINTER(_GUID))]


class _WINTRUST_DATA(ctypes.Structure):
    _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
                ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
                ("pFile", ctypes.c_void_p), ("dwStateAction", wintypes.DWORD),
                ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
                ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD),
                ("pSignatureSettings", ctypes.c_void_p)]


_WTD_UI_NONE = 2
_WTD_REVOKE_NONE = 0
_WTD_CHOICE_FILE = 1
_WTD_STATEACTION_VERIFY = 1
_WTD_STATEACTION_CLOSE = 2
_WTD_REVOCATION_CHECK_NONE = 0x10
_WINTRUST_ACTION_GENERIC_VERIFY_V2 = _GUID(
    0x00AAC56B, 0xCD44, 0x11D0,
    (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))


def _winverifytrust(path: str, provider_flags: int) -> int:
    wintrust = ctypes.WinDLL("wintrust")
    file_info = _WINTRUST_FILE_INFO()
    file_info.cbStruct = ctypes.sizeof(_WINTRUST_FILE_INFO)
    file_info.pcwszFilePath = str(path)
    file_info.hFile = None
    file_info.pgKnownSubject = None

    data = _WINTRUST_DATA()
    data.cbStruct = ctypes.sizeof(_WINTRUST_DATA)
    data.dwUIChoice = _WTD_UI_NONE
    data.fdwRevocationChecks = _WTD_REVOKE_NONE
    data.dwUnionChoice = _WTD_CHOICE_FILE
    data.pFile = ctypes.cast(ctypes.byref(file_info), ctypes.c_void_p)
    data.dwStateAction = _WTD_STATEACTION_VERIFY
    data.dwProvFlags = provider_flags

    result = wintrust.WinVerifyTrust(
        wintypes.HANDLE(0), ctypes.byref(_WINTRUST_ACTION_GENERIC_VERIFY_V2), ctypes.byref(data))

    # Release the state data even when verification failed.
    data.dwStateAction = _WTD_STATEACTION_CLOSE
    wintrust.WinVerifyTrust(
        wintypes.HANDLE(0), ctypes.byref(_WINTRUST_ACTION_GENERIC_VERIFY_V2), ctypes.byref(data))
    return result & 0xFFFFFFFF


def _authenticode_via_wintrust(path: str):
    """``WinVerifyTrust`` with the driver's default policy, then a no-revocation retry.

    The retry exists because a default-policy failure on a machine with no network is
    a *revocation lookup* failure, not a signature failure.  The returned detail names
    which way it went, so a reader can never mistake "could not check revocation" for
    "signature checked and good".
    """
    try:
        result = _winverifytrust(path, 0)
        if result == 0:
            return ("Valid", "WinVerifyTrust (driver default policy, revocation checked)")
        offline = _winverifytrust(path, _WTD_REVOCATION_CHECK_NONE)
        if offline == 0:
            return ("Valid", "WinVerifyTrust (revocation check disabled: default-policy "
                             "lookup failed with 0x%08x, likely no network)" % result)
        return (_KNOWN_HRESULTS.get(offline, "UnknownError"),
                "WinVerifyTrust (hr=0x%08x)" % offline)
    except OSError:
        return None


def authenticode_status(path, method: str = "auto"):
    """``(status, detail)`` for ``path``; ``status == 'Valid'`` is the pass condition.

    ``method`` is ``auto`` (cmdlet, then wintrust), ``cmdlet`` or ``wintrust``.  Raises
    ``RuntimeError`` when the requested method is unavailable -- an unverifiable
    signature must refuse, never pass.
    """
    if method in ("auto", "cmdlet"):
        found = _authenticode_via_cmdlet(path)
        if found is not None:
            return found
        if method == "cmdlet":
            raise RuntimeError("UPSTREAM_SIGNATURE_UNVERIFIABLE:no-powershell-host")
    if method in ("auto", "wintrust"):
        found = _authenticode_via_wintrust(path)
        if found is not None:
            return found
        raise RuntimeError("UPSTREAM_SIGNATURE_UNVERIFIABLE:no-wintrust")
    raise ValueError("method must be 'auto', 'cmdlet' or 'wintrust'")


# ---------------------------------------------------------------------------
# 3. ConvertTo-Json-shaped output
# ---------------------------------------------------------------------------

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
            "\n": "\\n", "\r": "\\r", "\t": "\\t"}
#: Windows PowerShell 5.1's ConvertTo-Json escapes these as \u00XX on purpose.
_ANGLE_ESCAPES = "<>&'"


def _ps_escape(text: str) -> str:
    out = []
    for character in text:
        if character in _ESCAPES:
            out.append(_ESCAPES[character])
        elif character in _ANGLE_ESCAPES or ord(character) < 0x20 or ord(character) > 0x7E:
            out.append("\\u%04x" % ord(character))
        else:
            out.append(character)
    return "".join(out)


def ps_convert_to_json(value, _depth: int = 0) -> str:
    """``ConvertTo-Json`` (Windows PowerShell 5.1) byte shape, CRLF and all."""
    pad = "    " * (_depth + 1)
    close_pad = "    " * _depth
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return '"' + _ps_escape(value) + '"'
    if isinstance(value, dict):
        if not value:
            return "{\r\n" + close_pad + "}"
        members = ["%s\"%s\":  %s" % (pad, _ps_escape(str(key)),
                                      ps_convert_to_json(item, _depth + 1))
                   for key, item in value.items()]
        return "{\r\n" + ",\r\n".join(members) + "\r\n" + close_pad + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[\r\n" + close_pad + "]"
        members = [pad + ps_convert_to_json(item, _depth + 1) for item in value]
        return "[\r\n" + ",\r\n".join(members) + "\r\n" + close_pad + "]"
    raise TypeError("cannot serialise %r" % type(value))


def write_json_file(path, value) -> None:
    """``[IO.File]::WriteAllText(path, json, UTF8Encoding($false))`` -- no BOM."""
    Path(path).write_bytes(ps_convert_to_json(value).encode("utf-8"))


def write_result_file(path, value) -> None:
    """``... | Set-Content -LiteralPath path -Encoding utf8`` -- 5.1 writes a BOM."""
    Path(path).write_bytes(b"\xef\xbb\xbf" + (ps_convert_to_json(value) + "\r\n").encode("utf-8"))


def write_captured_output(path, data: bytes) -> None:
    """``1> file`` / ``2> file`` -- Windows PowerShell 5.1 redirects as UTF-16LE + BOM.

    The launcher's bytes are decoded (UTF-8, then the ANSI code page) and re-encoded
    to UTF-16LE, matching the redirect's encoding.  For the ASCII the launcher emits
    this is byte-identical to PowerShell; only exotic non-ASCII console output could
    decode differently from PS's per-console code page.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("mbcs", errors="replace")
    Path(path).write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))


def read_json_file(path):
    """``Get-Content -LiteralPath <p> -Raw | ConvertFrom-Json``."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------------------
# 4. On-disk layout shared by new-scope.py and load-bridge.py
# ---------------------------------------------------------------------------

RUNS_RELATIVE = ".runtime/editor-bridge/runs"
BRIDGE_OUTPUT_RELATIVE = "tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows"
VENDOR_RELATIVE = ".runtime/editor-bridge/vendor/snoop-6.1.1"

BRIDGE_DLL_NAME = "Miliastra.EditorBridge.Net8R300.dll"
BOOTSTRAP_DLL_NAME = "Miliastra.Bootstrap.Net8R300.dll"
LAUNCHER_NAME = "Snoop.InjectorLauncher.x64.exe"
NATIVE_NAME = "Snoop.GenericInjector.x64.dll"

#: Present in the project tree and nowhere else.  ``Bootstrap/Entry.cs`` hard-codes the
#: real run root, so a scope written under a *different* root would be refused late --
#: by the injected payload, with exit code 21 -- instead of here with a readable reason.
PROJECT_ROOT_MARKER = "tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj"


def assert_project_root(root) -> Path:
    """Refuse a root that cannot be this project.

    The .ps1 derives its root from ``$PSScriptRoot`` and so does this port; if the file
    is copied somewhere else the derived root is silently wrong.  Checking the marker
    turns that into a loud refusal instead of a scope minted in a directory the bridge
    will never read.  ``--project-root`` is not checked: passing it is an explicit
    statement about where to read, and the offline tests point it at scratch trees.
    """
    marker = Path(root) / PROJECT_ROOT_MARKER
    if not marker.is_file():
        raise RuntimeError(
            "PROJECT_ROOT_NOT_RECOGNISED:%s: expected %s to exist; pass --project-root "
            "if this is deliberate" % (root, marker))
    return Path(root)


def run_directory(project_root, run_id) -> Path:
    """``Join-Path $projectRoot ('.runtime/editor-bridge/runs/' + $run)``."""
    return Path(project_root) / RUNS_RELATIVE / str(run_id)


def artifact_paths(project_root) -> dict:
    """The four frozen artifacts, in the .ps1's own order.

    ``$dll``, ``$launcher``, ``$native`` come from ``load-bridge.ps1`` and ``$bootstrap``
    from ``Split-Path $dll``.  ``new-scope.ps1`` hashes the same four.
    """
    bridge_dir = Path(project_root) / BRIDGE_OUTPUT_RELATIVE
    vendor_dir = Path(project_root) / VENDOR_RELATIVE
    return {
        "bootstrap": bridge_dir / BOOTSTRAP_DLL_NAME,
        "bridge": bridge_dir / BRIDGE_DLL_NAME,
        "launcher": vendor_dir / LAUNCHER_NAME,
        "native": vendor_dir / NATIVE_NAME,
    }


def launcher_command(launcher, bootstrap, settings_path, target_pid) -> list:
    """The injector command line, argument for argument as ``load-bridge.ps1`` builds it.

    ``& $launcher --targetPID ([string]$scope.pid) --assembly $bootstrap
       --className 'Miliastra.Bootstrap.Entry' --methodName 'Start'
       --settingsFile $settingsPath``

    ``--assembly`` is the **Bootstrap** dll: the launcher starts
    ``Miliastra.Bootstrap.Entry.Start``, which then loads the bridge payload from its
    own directory (see ``Bootstrap/Entry.cs``).
    """
    return [
        str(launcher),
        "--targetPID", "" if target_pid is None else str(target_pid),
        "--assembly", str(bootstrap),
        "--className", "Miliastra.Bootstrap.Entry",
        "--methodName", "Start",
        "--settingsFile", str(settings_path),
    ]


def quote_command_line(command: list) -> str:
    """A human-readable rendering; only for --dry-run review, never executed."""
    return " ".join('"%s"' % part if " " in str(part) else str(part) for part in command)


__all__ = [
    "ProcessQueryError", "ImageUnreadableError",
    "process_name", "process_image_path", "process_start_utc_ticks",
    "authenticode_status",
    "ps_convert_to_json", "write_json_file", "write_result_file",
    "write_captured_output", "read_json_file",
    "RUNS_RELATIVE", "BRIDGE_OUTPUT_RELATIVE", "VENDOR_RELATIVE",
    "BRIDGE_DLL_NAME", "BOOTSTRAP_DLL_NAME", "LAUNCHER_NAME", "NATIVE_NAME",
    "PROJECT_ROOT_MARKER", "assert_project_root",
    "run_directory", "artifact_paths", "launcher_command", "quote_command_line",
]
