"""Read-only capture of the *user's* already-open 千星 editor window.

The editor is opened by the user, never by this project. There is no launch
method for it, no target key that starts it, and nothing in this module starts a
process, sends input, takes focus, changes a setting or reads the desktop. The
only write is the one evidence BMP under ``.runtime/``.

What "the editor window" means here is narrow, and the response never claims
more than was checked:

- the process is found by **name only** (``BeyondEditor.exe``). No install path
  is frozen for the editor, so an executable-path match is impossible and none is
  claimed: ``installationVerified`` is false in every response and the
  observation strength is reported as ``candidate``.
- the window is the single visible one whose title is *exactly* ``千星沙箱``
  **and** whose class name carries the WPF prefix ``HwndWrapper[BeyondEditor;``.
  Both are required. The title alone is a string any window can carry, and the
  class alone covers every window the editor's WPF process owns -- requiring both
  is what keeps an Explorer or helper window from being mistaken for the editor.
- the chosen pid and its creation date are re-read from the process table
  immediately before anything is drawn, because Windows reuses pids and a window
  found a moment ago proves nothing about the process holding that pid now.
- more than one window satisfying the rule is ``ambiguous-main-window-count``,
  never a guess; zero is a refusal too, and a refusal keeps the window metadata
  it saw so the failure is diagnosable.

``PrintWindow`` can block, so the enumeration and the drawing run in a child
process that is killed on a timeout -- exactly as ``bridge.window`` does. There
is no desktop BitBlt fallback: a screen grab would capture other applications too.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

from .window import (
    BLANK_RATIO_THRESHOLD,
    CAPTURE_TIMEOUT_S,
    EVIDENCE_DIR,
    PROJECT_ROOT,
    CaptureOutcome,
    MockWindowBackend,
    WindowCandidate,
    blank_ratio,
    encode_bmp,
    enumerate_top_level_windows,
    evidence_path,
    print_window_pixels,
    read_back_evidence,
    utc_now,
)

#: The ``target`` value ``mw.snapshot.capture`` accepts for this domain.
EDITOR_TARGET_KEY = "editor"
EDITOR_TARGET_LABEL = "千星沙箱 editor (BeyondEditor.exe)"

#: Matched by process *name*. The editor has no frozen install path, so a path
#: check is impossible and none is performed -- which is exactly why the
#: response says ``installationVerified: false`` instead of leaving it implied.
EDITOR_PROCESS_NAME = "BeyondEditor.exe"

#: The main-window rule, both halves of it. An exact title and the WPF class
#: prefix the editor's process gives its windows -- together, never either alone.
EDITOR_WINDOW_TITLE = "千星沙箱"
EDITOR_WINDOW_CLASS_PREFIX = "HwndWrapper[BeyondEditor;"

#: How the window was tied to a process: the user said which session is open,
#: and this bridge recognised that session. It is not a proof of installation.
EDITOR_BINDING_SOURCE = "user-confirmed-editor-session"
EDITOR_SELECTION_REASON = "single-editor-main-window"

CAPTURE_METHOD = "printwindow-pw-renderfullcontent"

EDITOR_MEANING = (
    "CAPTURE ONLY, EDITOR SESSION. This is a picture of one window of a running "
    "BeyondEditor.exe process, chosen because its title is exactly '千星沙箱' and "
    "its window class carries the WPF prefix 'HwndWrapper[BeyondEditor;'. That "
    "choice identifies which window the caller means; it is not evidence that the "
    "editor is in any particular mode, that a project is loaded, or that any "
    "Miliastra capability is available, and the bridge does not interpret the "
    "image, the title or the size. No install path is frozen for the editor, so "
    "installationVerified is false: the process was matched by name, and whether "
    "it is the installation the user means rests on the user's confirmation, not "
    "on an observation made here. PrintWindow only -- no desktop BitBlt, no "
    "keyboard or mouse input, no focus taken, no window command, and no process "
    "started by this project."
)


def select_editor_main_window(
    candidates: Sequence[WindowCandidate], pids: frozenset[int] | set[int]
) -> tuple[WindowCandidate | None, str, dict[str, Any]]:
    """Pick the editor's main window, or refuse to pick.

    Returns ``(window_or_None, reason, detail)``. A contender belongs to one of
    the candidate pids, is visible, has the exact title *and* the WPF class
    prefix. Zero contenders and more than one contender are both refusals: the
    second is precisely the case where picking one would silently capture the
    wrong surface.
    """
    pool = {int(p) for p in pids}
    considered = [
        c
        for c in candidates
        if c.pid in pool
        and c.visible
        and c.title.strip() == EDITOR_WINDOW_TITLE
        and c.class_name.startswith(EDITOR_WINDOW_CLASS_PREFIX)
    ]
    detail: dict[str, Any] = {
        "pids": sorted(pool),
        "mainWindows": len(considered),
        "matchRule": {
            "titleExact": EDITOR_WINDOW_TITLE,
            "classNamePrefix": EDITOR_WINDOW_CLASS_PREFIX,
        },
        # Every window seen for these pids, so a refusal explains itself: an
        # Explorer window is not in here at all, because only the candidate pids
        # are enumerated -- a window belonging to another process cannot make
        # this ambiguous.
        "observedWindows": [c.to_dict() for c in candidates if c.pid in pool][:10],
    }
    if not considered:
        return None, "no-editor-main-window", detail
    if len(considered) > 1:
        detail["candidates"] = [c.to_dict() for c in considered]
        return None, "ambiguous-main-window-count", detail
    return considered[0], EDITOR_SELECTION_REASON, detail


def editor_process_candidates(processes: Sequence[Any]) -> list[dict[str, Any]]:
    """Every running process named ``BeyondEditor.exe``, as a *candidate*.

    Matched by name only, so a candidate is always a candidate: the entry says
    ``installationVerified: false`` rather than dressing a name match up as a
    verified installation. A readable path, when there is one, is reported so a
    reader can see it, and is never used to accept or reject anything -- the
    editor is not a frozen target and has no path to compare against.
    """
    found: list[dict[str, Any]] = []
    for info in processes:
        entry = info.to_dict()
        if (entry.get("name") or "").casefold() != EDITOR_PROCESS_NAME.casefold():
            continue
        entry.update(
            {
                "matchKind": "process-name:editor",
                "matchStrength": "candidate",
                "installationVerified": False,
            }
        )
        found.append(entry)
    found.sort(key=lambda item: item.get("pid") or 0)
    return found


def _is_under(path: Path, root: Path) -> bool:
    try:
        return root.resolve() in path.resolve().parents or path.resolve() == root.resolve()
    except OSError:  # pragma: no cover - defensive
        return False


def perform_capture_editor(pids: Sequence[int]) -> dict[str, Any]:
    """The whole live editor capture, run inside the child process. Never raises."""
    pool = [int(p) for p in pids]
    if sys.platform != "win32":  # pragma: no cover - the bridge only runs on Windows
        return {"status": "unavailable", "reason": "not-windows", "pids": pool}

    try:
        windows = enumerate_top_level_windows(frozenset(pool))
    except OSError as exc:  # pragma: no cover - defensive
        return {
            "status": "unavailable",
            "reason": "enumeration-failed",
            "pids": pool,
            "error": f"{type(exc).__name__}: {exc}",
        }

    chosen, reason, detail = select_editor_main_window(windows, frozenset(pool))
    if chosen is None:
        return {
            "status": "unavailable",
            "reason": reason,
            "pids": pool,
            "selection": detail,
            "captureMethod": CAPTURE_METHOD,
            "bitbltFallbackUsed": False,
        }

    if chosen.is_minimized:
        return {
            "status": "unavailable",
            "reason": "window-minimized",
            "pids": pool,
            "window": chosen.to_dict(),
            "selection": detail,
            "hint": (
                "The editor window is minimized, so PrintWindow cannot draw it. "
                "Restore it in the editor itself -- this bridge issues no window "
                "commands for the editor -- then capture again."
            ),
            "printWindowAttempted": False,
            "captureMethod": CAPTURE_METHOD,
            "bitbltFallbackUsed": False,
        }

    pixels, error = print_window_pixels(chosen.hwnd, chosen.width, chosen.height)
    if pixels is None:
        return {
            "status": "unavailable",
            "reason": "printwindow-unavailable",
            "pids": pool,
            "window": chosen.to_dict(),
            "printWindowError": error,
            "selection": detail,
            "captureMethod": CAPTURE_METHOD,
            "bitbltFallbackUsed": False,
        }

    ratio = blank_ratio(chosen.width, chosen.height, pixels)
    blob = encode_bmp(chosen.width, chosen.height, pixels)
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = evidence_path(chosen.pid, chosen.hwnd)
        path.write_bytes(blob)
    except OSError as exc:
        return {
            "status": "unavailable",
            "reason": "evidence-write-failed",
            "pids": pool,
            "window": chosen.to_dict(),
            "selection": detail,
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "status": "partial" if ratio >= BLANK_RATIO_THRESHOLD else "captured",
        "reason": "printwindow-blank" if ratio >= BLANK_RATIO_THRESHOLD else None,
        "pids": pool,
        "window": chosen.to_dict(),
        "selection": detail,
        "path": str(path),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "bytes": len(blob),
        "width": chosen.width,
        "height": chosen.height,
        "blankRatio": round(ratio, 6),
        "blank": ratio >= BLANK_RATIO_THRESHOLD,
        "captureMethod": CAPTURE_METHOD,
        "renderFlag": 0x00000002,
        "bitbltFallbackUsed": False,
        "capturedAt": utc_now(),
    }


class RealEditorWindowBackend:
    """Live editor capture, in a child process with a hard timeout.

    Capture only: there is deliberately no restore verb here. A minimized editor
    window is reported as minimized and left alone -- this bridge commands no
    window of a session it did not start.
    """

    kind = "win32-printwindow-editor"
    simulated = False
    capture_method = CAPTURE_METHOD

    def __init__(self, evidence_dir: Path = EVIDENCE_DIR, timeout_s: float = CAPTURE_TIMEOUT_S):
        self.evidence_dir = Path(evidence_dir)
        self.timeout_s = timeout_s
        self.last_error: str | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "simulated": self.simulated,
            "captureMethod": self.capture_method,
            "evidenceDir": str(self.evidence_dir),
            "childProcess": [
                sys.executable,
                "-m",
                "bridge.editorwindow",
                "--capture-editor",
                "<pid>[,<pid>...]",
            ],
            "timeoutSeconds": self.timeout_s,
            "bitbltFallback": False,
            "windowCommands": False,
            "note": (
                "The editor is opened by the user, never by this project. This "
                "backend has no restore verb and sends no window command."
            ),
        }

    def capture_editor_target(self, pids: Sequence[int]) -> CaptureOutcome:
        argv = [
            sys.executable,
            "-m",
            "bridge.editorwindow",
            "--capture-editor",
            ",".join(str(int(p)) for p in pids),
        ]
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
            return CaptureOutcome(
                "unavailable",
                "worker-timeout",
                detail={
                    "timeoutSeconds": self.timeout_s,
                    "note": (
                        "The worker was killed. PrintWindow can block indefinitely on "
                        "some windows; this is reported as a failure, not retried "
                        "against the desktop."
                    ),
                },
            )
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return CaptureOutcome(
                "unavailable", "worker-spawn-failed", detail={"error": self.last_error}
            )

        payload: dict[str, Any] | None = None
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    payload = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if payload is None:
            self.last_error = f"worker produced no JSON (exit {proc.returncode})"
            return CaptureOutcome(
                "unavailable",
                "worker-error",
                detail={
                    "exitCode": proc.returncode,
                    "stderr": proc.stderr.decode("utf-8", errors="replace")[-500:],
                },
            )

        window = payload.get("window")
        path = Path(payload["path"]) if payload.get("path") else None
        outcome = CaptureOutcome(
            status=payload.get("status") or "unavailable",
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


class MockEditorWindowBackend:
    """Simulated editor capture. Touches no window and reads no screen.

    The *real* selection rule, bitmap encoding, blank measurement and read-back
    are exercised; only ``EnumWindows`` and ``PrintWindow`` are replaced. The
    drawing path is delegated to ``MockWindowBackend`` with a one-window table,
    so encoding and read-back are the same code the game capture is tested with.
    """

    kind = "mock-window-editor"
    simulated = True
    capture_method = "mock-printwindow"

    def __init__(
        self,
        windows: Sequence[WindowCandidate] = (),
        evidence_dir: Path | None = None,
        *,
        blank: bool = False,
        pixel: bytes = b"\x30\x50\xc8\x00",
    ) -> None:
        self.windows = list(windows)
        self.evidence_dir = Path(evidence_dir) if evidence_dir else EVIDENCE_DIR
        self.blank = blank
        self.pixel = pixel

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "simulated": True,
            "captureMethod": self.capture_method,
            "evidenceDir": str(self.evidence_dir),
            "windowCommands": False,
            "note": "No window is enumerated and no screen is read.",
        }

    def capture_editor_target(self, pids: Sequence[int]) -> CaptureOutcome:
        pool = frozenset(int(p) for p in pids)
        chosen, reason, detail = select_editor_main_window(self.windows, pool)
        if chosen is None:
            return CaptureOutcome(
                "unavailable",
                reason,
                simulated=True,
                detail={"selection": detail, "bitbltFallbackUsed": False},
            )
        if chosen.width <= 0 or chosen.height <= 0:
            return CaptureOutcome(
                "unavailable",
                "empty-window-rect",
                window=chosen.to_dict(),
                simulated=True,
                detail={"selection": detail, "bitbltFallbackUsed": False},
            )

        inner = MockWindowBackend(
            windows=[chosen],
            evidence_dir=self.evidence_dir,
            blank=self.blank,
            pixel=self.pixel,
        )
        outcome = inner.capture_target(chosen.pid)
        # The selection accounting stays the editor's own: the inner mock applied
        # the game rule only to reach the shared drawing code.
        outcome.detail["selection"] = detail
        outcome.detail["bitbltFallbackUsed"] = False
        if outcome.reason == "window-minimized":
            outcome.detail["hint"] = (
                "The editor window is minimized, so PrintWindow cannot draw it. "
                "Restore it in the editor itself -- this bridge issues no window "
                "commands for the editor -- then capture again."
            )
        return outcome


def _main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "--capture-editor":
        sys.stderr.write(
            "usage: python -m bridge.editorwindow --capture-editor <pid>[,<pid>...]\n"
        )
        return 2
    try:
        pids = [int(part) for part in args[1].split(",") if part.strip()]
    except ValueError:
        sys.stderr.write("bridge.editorwindow: pids must be integers\n")
        return 2
    if not pids or any(pid <= 0 for pid in pids):
        sys.stderr.write("bridge.editorwindow: pids must be positive\n")
        return 2
    try:
        result = perform_capture_editor(pids)
    except Exception as exc:  # noqa: BLE001 - the child always reports, never crashes
        result = {
            "status": "unavailable",
            "reason": "worker-exception",
            "pids": pids,
            "error": f"{type(exc).__name__}: {exc}",
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
