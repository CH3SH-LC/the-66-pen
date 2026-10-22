"""Read-only observation of a window the user already has open: one JSON line.

``python -m bridge.viewport [--target editor|game] [--focus]`` finds the target
window, refuses to act unless it is the foreground window, and grabs exactly its
rectangle with ``PIL.ImageGrab``. The method is ``screen-region`` -- composited
desktop pixels inside the window's rect -- and it is never interchanged with
``PrintWindow``. It starts no process, reads no launch journal, sends no key or
mouse input, minimizes nothing, restores nothing, calls no ``AttachThreadInput``,
and writes only inside the fixed evidence directory. ``--focus`` issues at most
one ``SetForegroundWindow`` on the window already chosen, and nothing else.
"""
import argparse, ctypes, json, struct, subprocess, sys, uuid

from bridge import window as win

EVIDENCE_DIR, CAPTURE_METHOD = win.EVIDENCE_DIR, "screen-region"
MAX_SIDE, MAX_PIXELS, PS_TIMEOUT_S = 16384, 40_000_000, 15.0
TARGETS = {"editor": ("BeyondEditor.exe", "千星沙箱"), "game": ("YuanShen.exe", "原神")}

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.GetForegroundWindow.restype = ctypes.c_void_p  # HWND is 64-bit
    _user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
else:
    _user32 = None


def _fail(report, reason, **extra):
    return {**report, "status": "unavailable", "reason": reason, **extra}


def _pids(image: str) -> list[int]:
    try:
        import psutil  # optional; not in the default environment
        return sorted(p.pid for p in psutil.process_iter(["name"])
                      if (p.info.get("name") or "").lower() == image.lower())
    except ImportError:
        pass
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-Process -Name '%s' -EA 0 | Select -Expand Id" % image[:-4]],
            capture_output=True, timeout=PS_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted({int(t) for t in done.stdout.decode("utf-8", "replace").split() if t.isdigit()})


def _choose(pids, title):
    found = win.enumerate_top_level_windows(frozenset(pids))
    hits = [c for c in found if c.visible and c.title.strip().startswith(title)]
    live = [c for c in hits if not c.is_minimized]
    if not hits:
        return None, "TARGET_NOT_FOUND", {"windows": [c.to_dict() for c in found][:10]}
    if not live:
        return None, "TARGET_MINIMIZED", {"window": hits[0].to_dict()}
    if len(live) > 1:
        return None, "AMBIGUOUS_TARGET", {"candidates": [c.to_dict() for c in live]}
    return live[0], None, {}


def observe(target_key: str, focus: bool) -> dict:
    image_name, title = TARGETS[target_key]
    try:  # per-monitor aware, so the rect we read is in real pixels
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        dpi = "per-monitor-aware"
    except (AttributeError, OSError):
        dpi = "unset"
    report = {"target": target_key, "processName": image_name, "expectedTitle": title,
              "captureMethod": CAPTURE_METHOD, "printWindowUsed": False, "dpiAwareness": dpi,
              "focusRequested": bool(focus), "inputSent": False, "processStarted": False,
              "observedAt": win.utc_now()}
    if sys.platform != "win32":
        return _fail(report, "not-windows")
    pids = report["pids"] = _pids(image_name)
    if not pids:
        return _fail(report, "TARGET_NOT_FOUND")
    chosen, reason, detail = _choose(pids, title)
    report["detail"] = detail
    if chosen is None:
        return _fail(report, reason)
    report.update({"pid": chosen.pid, "hwnd": "0x%016X" % chosen.hwnd, "windowTitle": chosen.title})
    fg = int(_user32.GetForegroundWindow() or 0)
    if fg != chosen.hwnd and focus:
        report["focusMethod"] = "setforegroundwindow-once"
        report["focusCallAccepted"] = bool(_user32.SetForegroundWindow(chosen.hwnd))
        fg = int(_user32.GetForegroundWindow() or 0)
    report["foregroundBeforeGrab"] = "0x%016X" % fg
    if fg != chosen.hwnd:
        return _fail(report, "NOT_FOREGROUND")
    rect = report["rectBefore"] = win.window_state(chosen.hwnd).get("rect")
    if not rect or min(rect["width"], rect["height"]) <= 0:
        return _fail(report, "NO_VALID_RECT")
    if max(rect["width"], rect["height"]) > MAX_SIDE or rect["width"] * rect["height"] > MAX_PIXELS:
        return _fail(report, "RECT_TOO_LARGE", maxSide=MAX_SIDE, maxPixels=MAX_PIXELS)
    try:
        from PIL import ImageGrab
    except ImportError:
        return _fail(report, "pil-unavailable")
    shot = ImageGrab.grab(bbox=(rect["left"], rect["top"], rect["right"], rect["bottom"]),
                          all_screens=True)
    after = win.window_state(chosen.hwnd)
    fg_after = report["foregroundAfterGrab"] = "0x%016X" % int(_user32.GetForegroundWindow() or 0)
    report["rectAfter"] = after.get("rect")
    if after.get("rect") != rect or fg_after != report["foregroundBeforeGrab"] or after["stillMinimized"]:
        return {**report, "status": "invalid", "evidenceWritten": False,
                "reason": "SCREEN_CHANGED_DURING_CAPTURE"}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / ("viewport-%s-p%d-h%X-%s.png" % (
        win.utc_now().replace(":", "").replace("-", ""), chosen.pid, chosen.hwnd, uuid.uuid4().hex[:8]))
    shot.save(path, format="PNG")
    head = path.read_bytes()[:24]
    size = struct.unpack(">II", head[16:24]) if (len(head) == 24 and head[:8] == b"\x89PNG\r\n\x1a\n") else None
    ratio = win.blank_ratio(shot.width, shot.height, shot.convert("RGBA").tobytes())
    return {**report, "status": "observed", "reason": None, "path": str(path),
            "bytes": path.stat().st_size,
            "actualPngDimensions": {"width": size[0], "height": size[1]} if size else None,
            "grabDimensions": {"width": shot.width, "height": shot.height},
            "dimensionsMatchRect": size == (rect["width"], rect["height"]),
            "blankRatio": round(ratio, 6), "blank": ratio >= win.BLANK_RATIO_THRESHOLD,
            "capturedAt": win.utc_now()}


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bridge.viewport")
    parser.add_argument("--target", choices=sorted(TARGETS), default="editor")
    parser.add_argument("--focus", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = observe(args.target, args.focus)
    except Exception as exc:  # noqa: BLE001 - the CLI always reports, never crashes
        report = _fail({"target": args.target}, "exception", error="%s: %s" % (type(exc).__name__, exc))
    sys.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n")
    return 0 if report.get("status") == "observed" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
