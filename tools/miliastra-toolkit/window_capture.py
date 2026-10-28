"""Capture explicit process windows using Windows APIs; no foreground, input or game memory."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]


def capture(pid, expected_image, output):
    if os.name != "nt":
        raise ValueError("WINDOWS_REQUIRED")
    user, gdi, kernel = c.WinDLL("user32", use_last_error=True), c.WinDLL("gdi32", use_last_error=True), c.WinDLL("kernel32", use_last_error=True)
    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, list(args)
        return fn
    open_process = bind(kernel, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
    close = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)
    query = bind(kernel, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
    process = open_process(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION, never VM_READ.
    if not process:
        raise ValueError("PROCESS_IDENTITY_UNAVAILABLE")
    try:
        size, buf = w.DWORD(32768), c.create_unicode_buffer(32768)
        if not query(process, 0, buf, c.byref(size)):
            raise ValueError("PROCESS_IMAGE_UNAVAILABLE")
        image_path = buf.value
        if Path(image_path).name.casefold() != expected_image.casefold():
            raise ValueError("PROCESS_IMAGE_MISMATCH")
        # Keep the handle open throughout capture so PID recycling cannot identify a replacement.
        callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        get_pid = bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
        visible = bind(user, "IsWindowVisible", w.BOOL, w.HWND)
        candidates = []
        @callback
        def visit(hwnd, _):
            owner = w.DWORD()
            get_pid(hwnd, c.byref(owner))
            if owner.value == pid and visible(hwnd):
                candidates.append(hwnd)
            return True
        bind(user, "EnumWindows", w.BOOL, callback, w.LPARAM)(visit, 0)
        if len(candidates) != 1:
            raise ValueError("WINDOW_NOT_FOUND_OR_AMBIGUOUS:" + str(len(candidates)))
        hwnd = candidates[0]
        if bind(user, "IsIconic", w.BOOL, w.HWND)(hwnd):
            raise ValueError("WINDOW_MINIMIZED_PIXEL_CAPTURE_UNAVAILABLE:does-not-imply-editor-API-unavailable")
        rect = w.RECT()
        if not bind(user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))(hwnd, c.byref(rect)):
            raise ValueError("WINDOW_RECT_FAILED")
        width, height = rect.right-rect.left, rect.bottom-rect.top
        if not (1 <= width <= 8192 and 1 <= height <= 8192):
            raise ValueError("WINDOW_DIMENSION")
        getdc = bind(user, "GetDC", w.HDC, w.HWND)
        release = bind(user, "ReleaseDC", c.c_int, w.HWND, w.HDC)
        screen = getdc(None)
        mem = bind(gdi, "CreateCompatibleDC", w.HDC, w.HDC)(screen)
        bitmap = bind(gdi, "CreateCompatibleBitmap", w.HBITMAP, w.HDC, c.c_int, c.c_int)(screen, width, height)
        select = bind(gdi, "SelectObject", w.HANDLE, w.HDC, w.HANDLE)
        old = select(mem, bitmap)
        try:
            if not bind(user, "PrintWindow", w.BOOL, w.HWND, w.HDC, w.UINT)(hwnd, mem, 2):
                raise ValueError("PRINTWINDOW_FAILED")
            class Header(c.Structure):
                _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                            ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                            ("image_size", w.DWORD), ("x", w.LONG), ("y", w.LONG),
                            ("colors", w.DWORD), ("important", w.DWORD)]
            header = Header(c.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
            pixels = c.create_string_buffer(width*height*4)
            select(mem, old)
            count = bind(gdi, "GetDIBits", c.c_int, w.HDC, w.HBITMAP, w.UINT, w.UINT,
                         c.c_void_p, c.c_void_p, w.UINT)(mem, bitmap, 0, height, pixels, c.byref(header), 0)
            if count != height:
                raise ValueError("WINDOW_PARTIAL_PIXELS")
            from PIL import Image
            image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
            if all(lo == hi for lo, hi in image.getextrema()):
                raise ValueError("WINDOW_BLANK_PIXELS")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                image.save(stream, format="PNG")
            return {"ok": True, "image": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "width": width, "height": height, "pid": pid, "processImage": image_path,
                    "foregroundChanged": False, "inputSent": False, "processMemoryRead": False,
                    "visualReviewPending": True, "nativeCalled": False}
        finally:
            select(mem, old)
            bind(gdi, "DeleteObject", w.BOOL, w.HANDLE)(bitmap)
            bind(gdi, "DeleteDC", w.BOOL, w.HDC)(mem)
            release(None, screen)
    finally:
        close(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--expected-image", required=True, help="Exact process basename from current OS inventory")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    try:
        output = (ROOT / args.out_dir).resolve()
        if not output.is_relative_to(ROOT / ".runtime") or not 1 <= args.frames <= 120 or not .5 <= args.interval <= 30:
            raise ValueError("CAPTURE_BOUND_OR_OUTPUT")
        receipts = []
        for i in range(args.frames):
            if i:
                time.sleep(args.interval)
            receipts.append(capture(args.pid, args.expected_image, output / f"frame-{i:04}.png"))
        result = {"ok": True, "frames": receipts, "nativeCalled": False}
        (output / "capture.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "nativeCalled": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
