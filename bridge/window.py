"""Read-only window binding, one PrintWindow capture, and one restore request.

This module exists so that ``mw.snapshot.capture`` and ``mw.window.restore`` can
act on *a window* without ever being told which window to act on. Nothing here
accepts an hwnd, a pid, an output path or a rectangle from a caller:

- the candidate process comes from the frozen ``game`` target and the existing
  CIM observation, and only a **strong** (executable-path) match is accepted;
- the window is whichever visible, titled, top-level window that process owns --
  and if it owns more than one, the answer is ``AMBIGUOUS_TARGET``, not a guess;
- the output path is derived from ``__file__``; the evidence directory is fixed.

What each verb does, and what it deliberately does not:

``--capture``
    ``PrintWindow`` asks the window to draw itself into a DC we own. A minimized
    window is reported as ``window-minimized`` before any drawing is attempted,
    because drawing one cannot produce anything useful. There is **no desktop
    BitBlt fallback**: a desktop grab would capture whatever is on screen,
    including other applications, which is a different and much broader act
    than the one this interface claims to perform.

``--restore``
    ``ShowWindowAsync(hwnd, SW_RESTORE)`` asks the window's own thread to
    un-minimize it. That is the whole effect. No key or mouse input, no
    ``SetForegroundWindow`` (so nothing is stolen from the user's focus), no
    elevation, no process started, no game or system setting changed. Only the
    one bound window is targeted. An already-restored window is left alone
    rather than being poked for no reason.

``PrintWindow`` is known to block indefinitely on some windows. Because of that
both verbs run in a **separate child process** (``python -m bridge.window
--capture|--restore <pid>``) that the parent kills on a timeout. A hung call
therefore costs one killed child, never a hung bridge.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import struct
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

BRIDGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BRIDGE_DIR.parent

#: Fixed output directory. Derived from ``__file__``, so neither cwd nor a
#: request can move it. Git-ignored, and the only place this module writes.
EVIDENCE_DIR = PROJECT_ROOT / ".runtime" / "bridge" / "evidence"

#: The one process this module will ever look at the windows of.
TARGET_KEY = "game"
TARGET_PROCESS_NAME = "YuanShen.exe"

PW_RENDERFULLCONTENT = 0x00000002
#: The only window command this module ever issues.
SW_RESTORE = 9
DIB_RGB_COLORS = 0
BI_RGB = 0

#: A hung PrintWindow is a known failure mode; the child gets this long, then dies.
CAPTURE_TIMEOUT_S = 20.0
#: ``ShowWindowAsync`` only queues work, so the read-back may need a moment. Both
#: bounds are finite: this observes, it does not wait indefinitely.
RESTORE_TIMEOUT_S = 20.0
RESTORE_MAX_WAIT_S = 1.2
RESTORE_POLL_INTERVAL_S = 0.1

MAX_TITLE_CHARS = 200
#: Fraction of near-black pixels above which the image is called blank.
BLANK_RATIO_THRESHOLD = 0.995
#: A channel value at or below this counts as "dark" when measuring blankness.
DARK_CHANNEL = 8

# --------------------------------------------------------------------------
# win32 bindings -- prototypes are explicit so no pointer is truncated on x64
# --------------------------------------------------------------------------

if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class RGBQUAD(ctypes.Structure):
        _fields_ = [
            ("rgbBlue", ctypes.c_ubyte),
            ("rgbGreen", ctypes.c_ubyte),
            ("rgbRed", ctypes.c_ubyte),
            ("rgbReserved", ctypes.c_ubyte),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]

else:  # pragma: no cover - the bridge only ever runs on Windows
    user32 = None
    gdi32 = None


# --------------------------------------------------------------------------
# candidates and selection -- pure, so the ambiguity rule is testable
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowCandidate:
    hwnd: int
    pid: int
    title: str
    class_name: str
    width: int
    height: int
    visible: bool = True
    #: A minimized window is still a candidate: it is exactly what restore exists
    #: for. Capture refuses it by name rather than by accident.
    is_minimized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": f"0x{self.hwnd:016X}",
            "pid": self.pid,
            "title": self.title[:MAX_TITLE_CHARS],
            "titleTruncated": len(self.title) > MAX_TITLE_CHARS,
            "className": self.class_name[:MAX_TITLE_CHARS],
            "width": self.width,
            "height": self.height,
            "visible": self.visible,
            "isMinimized": self.is_minimized,
        }


def select_window(
    candidates: Sequence[WindowCandidate], pid: int
) -> tuple[WindowCandidate | None, str, dict[str, Any]]:
    """Pick *the* window, or refuse to pick.

    Returns ``(window_or_None, reason, detail)``. Visible, titled, non-empty
    top-level windows belonging to ``pid`` are the only contenders. Zero
    contenders and more than one contender are both refusals: the second is
    exactly the case where guessing would silently capture or un-minimize the
    wrong surface.
    """
    considered = [
        c
        for c in candidates
        if c.pid == pid and c.visible and c.title.strip() and c.width > 0 and c.height > 0
    ]
    detail = {
        "pid": pid,
        "visibleTitledTopLevelWindows": len(considered),
        "rejected": [
            c.to_dict()
            for c in candidates
            if c.pid == pid and c not in considered
        ][:10],
    }
    if not considered:
        if any(c.pid == pid for c in candidates):
            return None, "no-visible-titled-window", detail
        return None, "no-window-for-pid", detail
    if len(considered) > 1:
        detail["candidates"] = [c.to_dict() for c in considered]
        return None, "ambiguous-window-count", detail
    return considered[0], "single-visible-titled-window", detail


# --------------------------------------------------------------------------
# pixel helpers -- real, and used by both the live worker and the mock
# --------------------------------------------------------------------------


def blank_ratio(width: int, height: int, pixels: bytes | bytearray) -> float:
    """Fraction of sampled pixels that are essentially black.

    Sampled rather than exhaustive: this is a sanity check on the capture, not
    image analysis. A window that rendered nothing gives ~1.0.
    """
    if width <= 0 or height <= 0:
        return 1.0
    stride = width * 4
    if len(pixels) < stride * height:
        return 1.0
    row_step = max(1, height // 64)
    pixel_step = max(1, width // 128)
    total = 0
    dark = 0
    for y in range(0, height, row_step):
        row = y * stride
        for x in range(0, width, pixel_step):
            i = row + x * 4
            if (
                pixels[i] <= DARK_CHANNEL
                and pixels[i + 1] <= DARK_CHANNEL
                and pixels[i + 2] <= DARK_CHANNEL
            ):
                dark += 1
            total += 1
    return dark / total if total else 1.0


def encode_bmp(width: int, height: int, pixels: bytes | bytearray) -> bytes:
    """Wrap a 32bpp top-down BGRA buffer as a bottom-up BI_RGB BMP.

    ``pixels`` is what ``GetDIBits`` produces for a positive ``biHeight``: rows
    from the bottom up. Writing it unchanged is what keeps the header honest.
    """
    expected = width * height * 4
    if width <= 0 or height <= 0:
        raise ValueError(f"refusing to encode a {width}x{height} bitmap")
    if len(pixels) != expected:
        raise ValueError(f"expected {expected} bytes for {width}x{height}, got {len(pixels)}")
    info = struct.pack(
        "<IiiHHIIiiII", 40, width, height, 1, 32, BI_RGB, len(pixels), 2835, 2835, 0, 0
    )
    offset = 14 + len(info)
    header = struct.pack("<2sIHHI", b"BM", offset + len(pixels), 0, 0, offset)
    return header + info + bytes(pixels)


def read_bmp_header(data: bytes) -> dict[str, Any] | None:
    """Parse just enough of a BMP header to say whether the file is what it claims."""
    if len(data) < 54 or data[:2] != b"BM":
        return None
    declared, = struct.unpack_from("<I", data, 2)
    offset, = struct.unpack_from("<I", data, 10)
    header_size, width, height, planes, bits = struct.unpack_from("<IiiHH", data, 14)
    return {
        "declaredFileSize": declared,
        "actualFileSize": len(data),
        "sizeMatches": declared == len(data),
        "pixelOffset": offset,
        "headerSize": header_size,
        "width": width,
        "height": height,
        "planes": planes,
        "bitsPerPixel": bits,
        "compression": struct.unpack_from("<I", data, 30)[0],
        "format": "bmp-32bpp-bi-rgb",
    }


def evidence_path(pid: int, hwnd: int) -> Path:
    """A unique, fixed-shape name inside the fixed evidence directory."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return EVIDENCE_DIR / f"snapshot-{stamp}-p{pid}-h{hwnd:X}-{uuid.uuid4().hex[:8]}.bmp"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------
# live enumeration and capture -- child process only
# --------------------------------------------------------------------------


def enumerate_top_level_windows(pids: frozenset[int] | None = None) -> list[WindowCandidate]:
    """Visible top-level windows only. ``EnumWindows`` yields nothing else."""
    if user32 is None:  # pragma: no cover
        raise RuntimeError("window enumeration requires win32")
    found: list[WindowCandidate] = []

    def _callback(hwnd: Any, _lparam: Any) -> bool:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pids is not None and pid.value not in pids:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 2)
        user32.GetWindowTextW(hwnd, title, length + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append(
            WindowCandidate(
                hwnd=int(hwnd) if hwnd else 0,
                pid=pid.value,
                title=title.value,
                class_name=cls.value,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                visible=True,
                is_minimized=bool(user32.IsIconic(hwnd)),
            )
        )
        return True

    callback = WNDENUMPROC(_callback)
    user32.EnumWindows(callback, 0)
    return found


def print_window_pixels(hwnd: int, width: int, height: int) -> tuple[bytes | None, str | None]:
    """``PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)`` into a fresh 32bpp DIB.

    Every GDI object created here is released in ``finally``. The bitmap is
    selected back out of the DC before ``GetDIBits`` (which requires it to be
    unselected) and before ``DeleteObject``.

    Returns ``(pixels, error)``. ``pixels`` is ``None`` when ``PrintWindow``
    refused to draw -- reported as a failure, never replaced by a desktop grab.
    """
    if user32 is None:  # pragma: no cover
        return None, "not-windows"
    if width <= 0 or height <= 0:
        return None, "empty-window-rect"

    hdc_window = user32.GetWindowDC(hwnd)
    if not hdc_window:
        return None, "getwindowdc-failed"
    hdc_mem = None
    bitmap = None
    previous = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
        if not hdc_mem:
            return None, "createcompatibledc-failed"
        bitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        if not bitmap:
            return None, "createcompatiblebitmap-failed"
        previous = gdi32.SelectObject(hdc_mem, bitmap)
        drawn = user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not drawn:
            return None, "printwindow-returned-false"
        gdi32.SelectObject(hdc_mem, previous)
        previous = None

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = height  # positive: bottom-up, as BMP wants
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        info.bmiHeader.biSizeImage = width * height * 4

        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(
            hdc_mem, bitmap, 0, height, buffer, ctypes.byref(info), DIB_RGB_COLORS
        )
        if copied == 0:
            return None, "getdibits-copied-nothing"
        return buffer.raw, None
    finally:
        if previous:
            gdi32.SelectObject(hdc_mem, previous)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)


def window_state(hwnd: int) -> dict[str, Any]:
    """Read back ``IsIconic`` and ``GetWindowRect``. Observation only."""
    if user32 is None:  # pragma: no cover
        return {"hwnd": f"0x{hwnd:016X}", "readable": False, "readAt": utc_now()}
    iconic = bool(user32.IsIconic(hwnd))
    rect = wintypes.RECT()
    read_ok = bool(user32.GetWindowRect(hwnd, ctypes.byref(rect)))
    state: dict[str, Any] = {
        "hwnd": f"0x{hwnd:016X}",
        "isIconic": iconic,
        # Same value, named for what the caller is asking. `IsIconic` is the API
        # this came from; `stillMinimized` is the answer.
        "stillMinimized": iconic,
        "rectRead": read_ok,
        "rect": (
            {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            }
            if read_ok
            else None
        ),
        "readAt": utc_now(),
    }
    return state


def wait_for_restore(
    hwnd: int,
    *,
    max_wait_s: float = RESTORE_MAX_WAIT_S,
    interval_s: float = RESTORE_POLL_INTERVAL_S,
) -> dict[str, Any]:
    """Wait, bounded, for ``IsIconic`` to clear after a restore request.

    ``ShowWindowAsync`` does not restore the window -- it posts the request to the
    thread that owns the window, which applies it whenever it next pumps messages.
    So an immediate read-back can legitimately still show ``IsIconic``. This polls
    a little and then reports what it actually saw, either way. It never reports a
    success it did not observe.
    """
    deadline = time.monotonic() + max_wait_s
    waited = 0.0
    state = window_state(hwnd)
    while state.get("stillMinimized") and waited < max_wait_s:
        time.sleep(interval_s)
        waited += interval_s
        state = window_state(hwnd)
    state["waitedMs"] = int(round(waited * 1000))
    state["observationNote"] = (
        "ShowWindowAsync only queues the request; the window's own thread applies it. "
        + (
            "IsIconic cleared within the bounded wait."
            if not state.get("stillMinimized")
            else "IsIconic was still set when the bounded wait expired; the owning "
            "thread has not applied the request yet (or refused it). No further "
            "attempt was made."
        )
    )
    return state


def perform_capture(pid: int) -> dict[str, Any]:
    """The whole live capture, run inside the child process. Never raises."""
    if user32 is None:  # pragma: no cover
        return {"status": "unavailable", "reason": "not-windows", "pid": pid}

    try:
        windows = enumerate_top_level_windows(frozenset({pid}))
    except OSError as exc:  # pragma: no cover - defensive
        return {"status": "unavailable", "reason": "enumeration-failed", "pid": pid,
                "error": f"{type(exc).__name__}: {exc}"}

    chosen, reason, detail = select_window(windows, pid)
    if chosen is None:
        return {
            "status": "unavailable",
            "reason": reason,
            "pid": pid,
            "selection": detail,
        }

    # Before anything is drawn: a minimized window cannot be captured. This is
    # named specifically so the caller gets "restore it first", not a vague
    # failure that looks like a broken capture path.
    if chosen.is_minimized:
        return {
            "status": "unavailable",
            "reason": "window-minimized",
            "pid": pid,
            "window": chosen.to_dict(),
            "selection": detail,
            "hint": (
                "The window is minimized, so PrintWindow cannot draw it. Call "
                "mw.window.restore with the same target, then capture again."
            ),
            "printWindowAttempted": False,
            "captureMethod": "printwindow-pw-renderfullcontent",
            "bitbltFallbackUsed": False,
        }

    pixels, error = print_window_pixels(chosen.hwnd, chosen.width, chosen.height)
    if pixels is None:
        return {
            "status": "unavailable",
            "reason": "printwindow-unavailable",
            "pid": pid,
            "window": chosen.to_dict(),
            "printWindowError": error,
            "captureMethod": "printwindow-pw-renderfullcontent",
            "bitbltFallbackUsed": False,
        }

    ratio = blank_ratio(chosen.width, chosen.height, pixels)
    blob = encode_bmp(chosen.width, chosen.height, pixels)
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = evidence_path(pid, chosen.hwnd)
        path.write_bytes(blob)
    except OSError as exc:
        return {
            "status": "unavailable",
            "reason": "evidence-write-failed",
            "pid": pid,
            "window": chosen.to_dict(),
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "status": "partial" if ratio >= BLANK_RATIO_THRESHOLD else "captured",
        "reason": "printwindow-blank" if ratio >= BLANK_RATIO_THRESHOLD else None,
        "pid": pid,
        "window": chosen.to_dict(),
        "selection": detail,
        "path": str(path),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "width": chosen.width,
        "height": chosen.height,
        "blankRatio": round(ratio, 6),
        "blank": ratio >= BLANK_RATIO_THRESHOLD,
        "captureMethod": "printwindow-pw-renderfullcontent",
        "renderFlag": PW_RENDERFULLCONTENT,
        "bitbltFallbackUsed": False,
        "capturedAt": utc_now(),
    }


def perform_restore(pid: int) -> dict[str, Any]:
    """Ask the one bound window to un-minimize. Run inside the child process.

    The effect is a single ``ShowWindowAsync`` call. An already-restored window is
    not poked at all -- there is nothing to un-minimize, and a needless window
    call is still a needless window call.
    """
    if user32 is None:  # pragma: no cover
        return {"status": "unavailable", "reason": "not-windows", "pid": pid}

    try:
        windows = enumerate_top_level_windows(frozenset({pid}))
    except OSError as exc:  # pragma: no cover - defensive
        return {"status": "unavailable", "reason": "enumeration-failed", "pid": pid,
                "error": f"{type(exc).__name__}: {exc}"}

    chosen, reason, detail = select_window(windows, pid)
    if chosen is None:
        return {"status": "unavailable", "reason": reason, "pid": pid, "selection": detail}

    base = {
        "pid": pid,
        "window": chosen.to_dict(),
        "selection": detail,
        "restoreMethod": "showwindowasync-sw-restore",
        "restoreCommand": SW_RESTORE,
        "inputSent": False,
        "foregroundForced": False,
        "elevated": False,
        "processStarted": False,
    }

    if not chosen.is_minimized:
        return {
            **base,
            "status": "already-restored",
            "reason": "already-restored",
            "requested": False,
            "windowBefore": chosen.to_dict(),
            "readBack": window_state(chosen.hwnd),
        }

    requested = bool(user32.ShowWindowAsync(chosen.hwnd, SW_RESTORE))
    read_back = wait_for_restore(chosen.hwnd)
    return {
        **base,
        "status": "requested" if requested else "request-failed",
        "reason": None if requested else "showwindowasync-returned-false",
        "requested": requested,
        "windowBefore": chosen.to_dict(),
        "readBack": read_back,
        "restoredAt": utc_now(),
    }


# --------------------------------------------------------------------------
# outcomes + backends
# --------------------------------------------------------------------------


@dataclass
class CaptureOutcome:
    status: str  # captured | partial | unavailable
    reason: str | None = None
    window: dict[str, Any] | None = None
    path: Path | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    capture_method: str | None = None
    blank_ratio: float | None = None
    read_back: dict[str, Any] | None = None
    simulated: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("captured", "partial")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "window": self.window,
            "path": str(self.path) if self.path else None,
            "sha256": self.sha256,
            "bytes": self.size_bytes,
            "captureMethod": self.capture_method,
            "blankRatio": self.blank_ratio,
            # Derived, not stored: a ratio at or above the threshold is what
            # "blank" means, so the two can never disagree.
            "blank": (
                self.blank_ratio is not None and self.blank_ratio >= BLANK_RATIO_THRESHOLD
            ),
            "readBack": self.read_back,
            "simulated": self.simulated,
            "detail": self.detail,
        }


@dataclass
class RestoreOutcome:
    status: str  # requested | already-restored | unavailable | request-failed
    requested: bool = False
    reason: str | None = None
    window: dict[str, Any] | None = None
    window_before: dict[str, Any] | None = None
    read_back: dict[str, Any] | None = None
    restore_method: str | None = "showwindowasync-sw-restore"
    simulated: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in ("requested", "already-restored")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "requested": self.requested,
            "reason": self.reason,
            "window": self.window,
            "windowBefore": self.window_before,
            "readBack": self.read_back,
            "restoreMethod": self.restore_method,
            "simulated": self.simulated,
            "detail": self.detail,
        }


def _is_under(path: Path, root: Path) -> bool:
    try:
        return root.resolve() in path.resolve().parents or path.resolve() == root.resolve()
    except OSError:  # pragma: no cover - defensive
        return False


def read_back_evidence(path: Path, expected_width: int, expected_height: int) -> dict[str, Any]:
    """Re-open the written file and describe what is actually on disk.

    The hash and the header come from the file, not from the buffer it was made
    from, so "the capture worked" is a claim about the artifact a reader can
    open -- not about a variable that has since gone out of scope.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    header = read_bmp_header(data)
    if header is None:
        return {"ok": False, "error": "not-a-bmp"}
    offset = header.get("pixelOffset") or 0
    body = data[offset:]
    return {
        "ok": bool(header["sizeMatches"]) and header["width"] == expected_width
        and header["height"] == expected_height,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "header": header,
        "dimensionsMatchRequested": header["width"] == expected_width
        and header["height"] == expected_height,
        "blankRatioFromFile": round(
            blank_ratio(header["width"], header["height"], body), 6
        ),
        "readAt": utc_now(),
    }


class RealWindowBackend:
    """Live capture and restore, each in a child process with a hard timeout."""

    kind = "win32-printwindow"
    simulated = False
    capture_method = "printwindow-pw-renderfullcontent"
    restore_method = "showwindowasync-sw-restore"

    def __init__(self, evidence_dir: Path = EVIDENCE_DIR, timeout_s: float = CAPTURE_TIMEOUT_S):
        # Fixed project paths. Not parameters of any method.
        self.evidence_dir = evidence_dir
        self.timeout_s = timeout_s
        self.last_error: str | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "simulated": self.simulated,
            "captureMethod": self.capture_method,
            "restoreMethod": self.restore_method,
            "evidenceDir": str(self.evidence_dir),
            "childProcess": [
                sys.executable, "-m", "bridge.window", "--capture|--restore", "<pid>"
            ],
            "timeoutSeconds": self.timeout_s,
            "bitbltFallback": False,
            "note": (
                "Both verbs run in a separate process so a blocking PrintWindow "
                "costs one killed child rather than a hung bridge."
            ),
        }

    def _run_worker(self, verb: str, pid: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        argv = [sys.executable, "-m", "bridge.window", verb, str(int(pid))]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.last_error = "worker-timeout"
            return None, {
                "reason": "worker-timeout",
                "detail": {
                    "timeoutSeconds": self.timeout_s,
                    "note": (
                        "The worker was killed. PrintWindow can block indefinitely on "
                        "some windows; this is reported as a failure, not retried "
                        "against the desktop."
                    ),
                },
            }
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None, {"reason": "worker-spawn-failed", "detail": {"error": self.last_error}}

        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line), {}
                except json.JSONDecodeError:
                    continue
        self.last_error = f"worker produced no JSON (exit {proc.returncode})"
        return None, {
            "reason": "worker-error",
            "detail": {
                "exitCode": proc.returncode,
                "stderr": proc.stderr.decode("utf-8", errors="replace")[-500:],
            },
        }

    def capture_target(self, pid: int) -> CaptureOutcome:
        if sys.platform != "win32":  # pragma: no cover
            return CaptureOutcome("unavailable", "not-windows", simulated=False)
        payload, failure = self._run_worker("--capture", pid)
        if payload is None:
            return CaptureOutcome("unavailable", failure["reason"], detail=failure["detail"])

        status = payload.get("status") or "unavailable"
        window = payload.get("window")
        path = Path(payload["path"]) if payload.get("path") else None
        outcome = CaptureOutcome(
            status=status,
            reason=payload.get("reason"),
            window=window,
            path=path,
            sha256=payload.get("sha256"),
            size_bytes=payload.get("bytes"),
            capture_method=payload.get("captureMethod"),
            blank_ratio=payload.get("blankRatio"),
            simulated=False,
            detail={
                k: payload[k]
                for k in (
                    "selection", "printWindowError", "renderFlag", "bitbltFallbackUsed",
                    "capturedAt", "hint", "printWindowAttempted",
                )
                if k in payload
            },
        )
        if path is None:
            return outcome

        # The child is told where to write only by its own code path; this check
        # makes sure of it, and would catch a compromised or mismatched worker.
        if not _is_under(path, self.evidence_dir):
            return CaptureOutcome(
                "unavailable",
                "evidence-path-outside-evidence-dir",
                window=window,
                detail={"reportedPath": str(path), "evidenceDir": str(self.evidence_dir)},
            )
        expected_w = int((window or {}).get("width") or 0)
        expected_h = int((window or {}).get("height") or 0)
        outcome.read_back = read_back_evidence(path, expected_w, expected_h)
        if outcome.read_back.get("sha256") != outcome.sha256:
            outcome.status = "unavailable"
            outcome.reason = "read-back-mismatch"
        return outcome

    def restore_target(self, pid: int) -> RestoreOutcome:
        if sys.platform != "win32":  # pragma: no cover
            return RestoreOutcome("unavailable", reason="not-windows")
        payload, failure = self._run_worker("--restore", pid)
        if payload is None:
            return RestoreOutcome("unavailable", reason=failure["reason"], detail=failure["detail"])
        return RestoreOutcome(
            status=payload.get("status") or "unavailable",
            requested=bool(payload.get("requested")),
            reason=payload.get("reason"),
            window=payload.get("windowBefore") or payload.get("window"),
            window_before=payload.get("windowBefore"),
            read_back=payload.get("readBack"),
            restore_method=payload.get("restoreMethod"),
            simulated=False,
            detail={
                k: payload[k]
                for k in (
                    "selection", "restoreCommand", "inputSent", "foregroundForced",
                    "elevated", "processStarted", "restoredAt",
                )
                if k in payload
            },
        )


class MockWindowBackend:
    """Simulated selection, capture and restore. Touches no window, no screen.

    The ambiguity rule, the bitmap encoding and the "already restored" rule
    exercised here are the *real* ones -- only ``EnumWindows``, ``PrintWindow``,
    ``IsIconic`` and ``ShowWindowAsync`` are replaced.
    """

    kind = "mock-window"
    simulated = True
    capture_method = "mock-printwindow"
    restore_method = "mock-showwindowasync-sw-restore"

    def __init__(
        self,
        windows: Sequence[WindowCandidate] = (),
        evidence_dir: Path | None = None,
        *,
        blank: bool = False,
        pixel: bytes = b"\x30\x50\xC8\x00",
        restore_ineffective: bool = False,
    ) -> None:
        self.windows = list(windows)
        self.evidence_dir = Path(evidence_dir) if evidence_dir else EVIDENCE_DIR
        self.blank = blank
        self.pixel = pixel
        #: Simulates a window whose owning thread never applies the request --
        #: the honest read-back case that must not be reported as a success.
        self.restore_ineffective = restore_ineffective
        self.restore_calls = 0

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "simulated": True,
            "captureMethod": self.capture_method,
            "restoreMethod": self.restore_method,
            "evidenceDir": str(self.evidence_dir),
            "note": "No window is enumerated and no screen is read.",
        }

    def capture_target(self, pid: int) -> CaptureOutcome:
        chosen, reason, detail = select_window(self.windows, pid)
        if chosen is None:
            # `window` keeps its default: there is no window to describe, only a
            # reason and the contenders that were rejected.
            return CaptureOutcome(
                "unavailable",
                reason,
                simulated=True,
                detail={"selection": detail, "bitbltFallbackUsed": False},
            )
        if chosen.is_minimized:
            return CaptureOutcome(
                "unavailable",
                "window-minimized",
                window=chosen.to_dict(),
                simulated=True,
                detail={
                    "selection": detail,
                    "bitbltFallbackUsed": False,
                    "printWindowAttempted": False,
                    "hint": (
                        "The window is minimized, so PrintWindow cannot draw it. Call "
                        "mw.window.restore with the same target, then capture again."
                    ),
                },
            )

        width, height = chosen.width, chosen.height
        pixels = bytes(width * height * 4) if self.blank else self.pixel * (width * height)
        blob = encode_bmp(width, height, pixels)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"snapshot-mock-p{pid}-h{chosen.hwnd:X}.bmp"
        path.write_bytes(blob)
        ratio = blank_ratio(width, height, pixels)
        outcome = CaptureOutcome(
            status="partial" if ratio >= BLANK_RATIO_THRESHOLD else "captured",
            reason="printwindow-blank" if ratio >= BLANK_RATIO_THRESHOLD else None,
            window=chosen.to_dict(),
            path=path,
            sha256=hashlib.sha256(blob).hexdigest(),
            size_bytes=len(blob),
            capture_method=self.capture_method,
            blank_ratio=round(ratio, 6),
            simulated=True,
            detail={"selection": detail, "bitbltFallbackUsed": False},
        )
        outcome.read_back = read_back_evidence(path, width, height)
        if outcome.read_back.get("sha256") != outcome.sha256:
            outcome.status = "unavailable"
            outcome.reason = "read-back-mismatch"
        return outcome

    def restore_target(self, pid: int) -> RestoreOutcome:
        chosen, reason, detail = select_window(self.windows, pid)
        common = {
            "simulated": True,
            "restore_method": self.restore_method,
            "detail": {
                "selection": detail,
                "restoreCommand": SW_RESTORE,
                "inputSent": False,
                "foregroundForced": False,
                "elevated": False,
                "processStarted": False,
            },
        }
        if chosen is None:
            return RestoreOutcome("unavailable", reason=reason, **common)

        if not chosen.is_minimized:
            return RestoreOutcome(
                "already-restored",
                requested=False,
                reason="already-restored",
                window=chosen.to_dict(),
                window_before=chosen.to_dict(),
                read_back={"isIconic": False, "stillMinimized": False, "waitedMs": 0,
                           "rectRead": True,
                           "rect": {"width": chosen.width, "height": chosen.height}},
                **common,
            )

        # Counted only when a window is actually asked: a refusal, an ambiguous
        # target or an already-restored window is not a restore request.
        self.restore_calls += 1

        if self.restore_ineffective:
            return RestoreOutcome(
                "requested",
                requested=True,
                window=chosen.to_dict(),
                window_before=chosen.to_dict(),
                read_back={
                    "isIconic": True,
                    "stillMinimized": True,
                    "waitedMs": int(RESTORE_MAX_WAIT_S * 1000),
                    "rectRead": True,
                    "observationNote": "mock: the owning thread never applied the request",
                },
                **common,
            )

        # The mock table is updated, so a later capture of this window succeeds --
        # which is what makes the restore/capture pair testable end to end.
        self.windows = [
            replace(c, is_minimized=False) if c.hwnd == chosen.hwnd else c
            for c in self.windows
        ]
        return RestoreOutcome(
            "requested",
            requested=True,
            window=chosen.to_dict(),
            window_before=chosen.to_dict(),
            read_back={"isIconic": False, "stillMinimized": False, "waitedMs": 200,
                       "rectRead": True,
                       "rect": {"width": chosen.width, "height": chosen.height}},
            **common,
        )


def build_window_backend(mode: str, evidence_dir: Path | None = None) -> Any:
    """``mock`` never touches a window; anything else is the live win32 path."""
    if mode == "mock":
        return MockWindowBackend(evidence_dir=evidence_dir)
    return RealWindowBackend(evidence_dir=evidence_dir or EVIDENCE_DIR)


# --------------------------------------------------------------------------
# child entry point
# --------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    verbs = {"--capture": perform_capture, "--restore": perform_restore}
    if len(args) != 2 or args[0] not in verbs:
        sys.stderr.write("usage: python -m bridge.window (--capture|--restore) <pid>\n")
        return 2
    try:
        pid = int(args[1])
    except ValueError:
        sys.stderr.write("bridge.window: pid must be an integer\n")
        return 2
    if pid <= 0:
        sys.stderr.write("bridge.window: pid must be positive\n")
        return 2
    try:
        result = verbs[args[0]](pid)
    except Exception as exc:  # noqa: BLE001 - the child always reports, never crashes
        result = {
            "status": "unavailable",
            "reason": "worker-exception",
            "pid": pid,
            "error": f"{type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
