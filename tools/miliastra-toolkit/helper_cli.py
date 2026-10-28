"""Explicit helper lifecycle; status and stop never elevate, start invokes the existing launcher once."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOOLKIT_CODE_DEPENDENCIES = ("tools/editor-bridge/start-elevated.ps1", "tools/editor-bridge/elevated-runner.ps1")


def queue_path(value):
    root = (ROOT / ".runtime/editor-bridge").resolve()
    result = (ROOT / value).resolve()
    if not result.is_relative_to(root) or result == root:
        raise ValueError("HELPER_QUEUE_OUTSIDE_EDITOR_BRIDGE")
    current = ROOT / value
    for parent in (current, *current.parents):
        if parent.is_symlink() or (parent.exists() and hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("HELPER_QUEUE_REPARSE_POINT")
    return result


def status(queue):
    path = queue / "runner.heartbeat"
    if not path.exists():
        return {"ok": True, "state": "absent", "heartbeatFresh": False, "processVerified": False}
    text = path.read_text(encoding="utf-8-sig").strip()
    try:
        stamp = datetime.fromisoformat(text.split()[0].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
    except (ValueError, IndexError):
        return {"ok": False, "error": "HELPER_HEARTBEAT_INVALID", "processVerified": False}
    return {"ok": True, "state": "heartbeat-fresh" if -5 <= age <= 30 else "stale",
            "ageSeconds": age, "heartbeatFresh": -5 <= age <= 30, "processVerified": False,
            "stopRequested": (queue / "STOP").exists()}


def remaining_minutes(deadline):
    stamp = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("HELPER_DEADLINE_TIMEZONE_REQUIRED")
    # Reserve 3 minutes for UAC/startup. Runner begins counting only after launch.
    remaining = int((stamp - datetime.now(timezone.utc)).total_seconds() // 60) - 3
    if not 1 <= remaining <= 1440:
        raise ValueError("HELPER_DEADLINE_MUST_LEAVE_4_TO_1443_MINUTES")
    return remaining


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("status", "stop", "start"):
        p = sub.add_parser(action)
        p.add_argument("--queue", type=Path, required=True)
        if action == "start":
            p.add_argument("--deadline-utc", required=True)
            p.add_argument("--config", type=Path, required=True)
            p.add_argument("--powershell", type=Path, required=True)
            p.add_argument("--operation-id", required=True)
    args = parser.parse_args()
    try:
        queue = queue_path(args.queue)
        if args.action == "status":
            result = status(queue)
        elif args.action == "stop":
            queue.mkdir(parents=True, exist_ok=True)
            (queue / "STOP").write_text("explicit tool stop; finish current operation then exit\n", encoding="utf-8")
            result = {"ok": True, "stopRequested": True, "processStopped": False, "nativeCalled": False}
        else:
            import re
            if not re.fullmatch("[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.operation_id):
                raise ValueError("HELPER_OPERATION_ID")
            minutes = remaining_minutes(args.deadline_utc)
            config = (ROOT / args.config).resolve()
            shell = args.powershell.resolve()
            if not config.is_relative_to(ROOT) or not config.is_file():
                raise ValueError("HELPER_CONFIG_PROJECT_FILE_REQUIRED")
            if shell.name.lower() not in ("pwsh.exe", "powershell.exe") or not shell.is_file():
                raise ValueError("HELPER_POWERSHELL_HOST_REQUIRED")
            before = status(queue)
            if before.get("heartbeatFresh"):
                raise ValueError("HELPER_ALREADY_FRESH_USE_EXISTING")
            claim = ROOT / ".runtime/miliastra-toolkit/helper-starts" / (args.operation_id + ".json")
            claim.parent.mkdir(parents=True, exist_ok=True)
            with claim.open("x", encoding="utf-8") as f:
                json.dump({"queue": str(queue), "deadlineUtc": args.deadline_utc,
                           "configSha256": hashlib.sha256(config.read_bytes()).hexdigest()}, f)
            command = [str(shell), "-NoProfile", "-NonInteractive", "-File",
                       str(ROOT / "tools/editor-bridge/start-elevated.ps1"),
                       "-LifetimeMinutes", str(minutes), "-WaitSeconds", "120",
                       "-QueueDir", str(queue), "-ConfigPath", str(config),
                       "-DeadlineUtc", args.deadline_utc]
            try:
                p = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=170,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                result = {"ok": p.returncode == 0, "exitCode": p.returncode,
                          "stdout": p.stdout, "stderr": p.stderr, "status": status(queue),
                          "outcomeUncertain": p.returncode != 0, "replayForbidden": True,
                          "nativeCalled": False, "mayHaveRequestedUAC": True}
            except subprocess.TimeoutExpired:
                result = {"ok": False, "error": "HELPER_START_TIMEOUT", "outcomeUncertain": True,
                          "replayForbidden": True, "nativeCalled": False}
            claim.with_suffix(".result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "nativeCalled": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
