"""Explicit elevation for one frozen target, via ``ShellExecuteExW`` verb=runas.

Elevation is opt-in and narrowly scoped. Only the frozen ``game`` target
(``YuanShen.exe``) may ask for it, and the request only chooses between two
fixed ways of starting the *same* allowlisted executable -- the caller still
supplies no path, no argv and no shell command. Those come from
:mod:`bridge.targets`, exactly as for an unelevated launch.

What this module deliberately does not do: it does not change UAC settings, the
registry or any ACL; it does not disable or bypass a security check; it does not
click, script or automate the consent prompt. ``verb="runas"`` is *asking*
Windows to prompt the interactive user. A declined prompt
(``ERROR_CANCELLED`` 1223) is an ordinary, structured outcome and is never
reported as a launch.

Nothing here touches the OS during tests: :func:`shell_execute_ex` is the only
function that calls into Windows, and the suite never hands it a real binary.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - platform guard, exercised on Windows only
    from ctypes import wintypes

    _HAVE_WINTYPES = True
except (ImportError, ValueError):  # pragma: no cover
    wintypes = None  # type: ignore[assignment]
    _HAVE_WINTYPES = False


ELEVATION_NONE = "none"
ELEVATION_REQUEST = "request"
ELEVATION_VALUES = frozenset({ELEVATION_NONE, ELEVATION_REQUEST})

#: Only these frozen targets may use explicit elevation. Kept beside the
#: implementation, not accepted from a request.
ELEVATION_TARGETS = frozenset({"game"})

VERB_RUNAS = "runas"

SEE_MASK_NOCLOSEPROCESS = 0x00000040
#: Without NOASYNC ShellExecuteEx may return before the child exists, which would
#: make the handle/PID meaningless.
SEE_MASK_NOASYNC = 0x00000100
SW_SHOWNORMAL = 1

ERROR_CANCELLED = 1223
#: Error kinds this module can produce. All of them mean "no process was
#: created", so none of them may be reported as a launch.
ELEVATION_ERROR_KINDS = frozenset(
    {"user-cancelled", "win32-error", "no-process-handle", "unsupported"}
)


@dataclass
class ElevationResult:
    returned: bool
    pid: int | None
    error: str | None
    error_kind: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "returned": self.returned,
            "pid": self.pid,
            "error": self.error,
            "errorKind": self.error_kind,
        }


def classify_failure(win_error: int) -> tuple[str, str]:
    """Map a Win32 error from the attempt onto a structured kind and message."""
    if win_error == ERROR_CANCELLED:
        return (
            "user-cancelled",
            "the user declined the Windows UAC prompt (ERROR_CANCELLED 1223); "
            "no process was created",
        )
    return ("win32-error", f"ShellExecuteExW failed with WinError {win_error}")


_STRUCTS: dict[str, Any] = {}


def shell_execute_info_struct() -> Any:
    """The declared ``SHELLEXECUTEINFOW``, built once.

    The layout is the 64-bit one. Declaring it with ``ctypes`` types (rather
    than padding by hand) is what makes the field offsets correct; the size is
    asserted at build time below.
    """
    if "info" not in _STRUCTS:
        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        size = ctypes.sizeof(SHELLEXECUTEINFOW)
        expected = 112 if ctypes.sizeof(ctypes.c_void_p) == 8 else 60
        if size != expected:
            raise RuntimeError(
                f"SHELLEXECUTEINFOW is {size} bytes, expected {expected} for this "
                f"pointer size; the declaration does not match the ABI in use"
            )
        _STRUCTS["info"] = SHELLEXECUTEINFOW
    return _STRUCTS["info"]


def _bind() -> tuple[Any, Any]:
    """Bind the three calls used, with full prototypes. No other API is bound."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(shell_execute_info_struct())]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.GetProcessId.argtypes = [wintypes.HANDLE]
    kernel32.GetProcessId.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return shell32, kernel32


def shell_execute_ex(
    executable_path: str, cwd: str, argv: tuple[str, ...] | list[str] = ()
) -> ElevationResult:
    """Start one already-allowlisted executable elevated, and step back.

    Fixed verb, fixed window state, no shell. The returned handle exists only to
    read the PID out of; it is closed before returning, so nothing is waited on
    and nothing is attached to.
    """
    if os.name != "nt" or not _HAVE_WINTYPES:
        return ElevationResult(
            False, None, "explicit elevation is implemented on Windows only", "unsupported"
        )
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        return ElevationResult(
            False,
            None,
            "this module declares the 64-bit SHELLEXECUTEINFOW layout only; refusing "
            "to call into a 32-bit ABI with it",
            "unsupported",
        )

    info = shell_execute_info_struct()()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.hwnd = None
    info.lpVerb = VERB_RUNAS
    info.lpFile = executable_path
    info.lpParameters = _command_line(argv)
    info.lpDirectory = cwd or None
    info.nShow = SW_SHOWNORMAL

    shell32, kernel32 = _bind()
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        kind, message = classify_failure(ctypes.get_last_error())
        return ElevationResult(False, None, message, kind)

    handle = info.hProcess
    if not handle:
        # TRUE with no handle means the process may not even have been created;
        # this is exactly the case that must never be dressed up as a launch.
        return ElevationResult(
            False,
            None,
            "ShellExecuteExW reported success but returned no process handle, so "
            "whether a process was created is unknown",
            "no-process-handle",
        )
    try:
        pid = int(kernel32.GetProcessId(handle))
    finally:
        kernel32.CloseHandle(handle)
    if not pid:
        return ElevationResult(
            False, None, "the process handle yielded pid 0; nothing was identified", "no-process-handle"
        )
    return ElevationResult(True, pid, None, None)


def _command_line(argv: tuple[str, ...] | list[str]) -> str | None:
    """Render the frozen argv with the standard quoting rules, or nothing."""
    if not argv:
        return None
    import subprocess

    return subprocess.list2cmdline([str(a) for a in argv])


def request_elevation(
    executable_path: str, cwd: str, argv: tuple[str, ...] | list[str] = ()
) -> ElevationResult:
    """Indirection point, so the OS call has exactly one named entry."""
    return shell_execute_ex(executable_path, cwd, argv)
