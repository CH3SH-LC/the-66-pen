#!/usr/bin/env python3
"""Attribute a write to the save files to a process, by measurement.

WHY THIS EXISTS
    The profile (.gip) is rewritten from some process's memory, and an external edit is
    simply overwritten. Which process that is decides where a durable registration has
    to happen. Three indirect routes all ran dry:

      * the editor's decompiled sources name no .gil/.gip path -- but its string
        literals are ConfuserEx-encrypted, so their absence proves nothing;
      * the game's global-metadata.dat is packed (header "MHY\\0", entropy 7.70), so it
        cannot be searched either;
      * no process holds the files open -- writes are open/write/close, so handle
        ownership cannot answer it either.

    What is left is to watch a write happen and see whose counter moves. This samples
    every process's cumulative write bytes and operations alongside the files' mtimes;
    at the moment a save file changes, exactly one process will have jumped.

    It therefore needs a write to occur while it runs. Start it, then create an archive
    in the editor -- the run will attribute the write.

    Read-only. It opens no file for writing and starts or stops nothing.

    python attribute-save-writes.py [--seconds 1800] [--interval 1.0] [--log FILE]
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_NAMES = ["BeyondEditor", "YuanShen"]


def save_root() -> Path:
    mihoyo = Path.home() / "AppData/LocalLow/miHoYo"
    for sub in mihoyo.iterdir():
        candidate = sub / "BeyondLocal"
        if candidate.is_dir():
            return candidate
    raise SystemExit(f"no BeyondLocal directory under {mihoyo}")


def watched(root: Path) -> list[Path]:
    files: list[Path] = []
    for uid in sorted(p for p in root.iterdir() if p.is_dir()):
        profile = uid / "Beyond_Local_Save_Player.gip"
        if profile.exists():
            files.append(profile)
        level_dir = uid / "Beyond_Local_Save_Level"
        if level_dir.is_dir():
            files.extend(sorted(level_dir.glob("*.gil")))
    return files


class Sampler:
    """One long-lived PowerShell, queried over stdin.

    The first version spawned a PowerShell per query -- one or two per second. Each is
    a fresh ~50 MB process, and that churn is a real load on a machine that may already
    be short of memory: the resident keeper was killed by the OS for low memory while
    this was running. Keep one shell alive and ask it repeatedly instead.
    """

    # A persistent shell fed over stdin is the obvious way to avoid the churn, and it
    # does not work here: PowerShell's `-Command -` mode rejects the writes (Errno 22).
    # So each query is its own short-lived process, and the cost is bounded by the poll
    # interval instead -- the default is deliberately slow for that reason.
    def ask(self, script: str) -> str:
        out = subprocess.run(["powershell", "-NoProfile", "-NoLogo", "-Command", script],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace").stdout
        return out.strip()

    def processes(self) -> dict[int, str]:
        script = (
            "Get-Process -Name " + ",".join(TARGET_NAMES) +
            " -ErrorAction SilentlyContinue | ForEach-Object { \"$($_.Id)|$($_.ProcessName)\" }"
        )
        found: dict[int, str] = {}
        while True:
            line = self.ask(script)
            if line == "":
                break
            parts = line.split("|")
            if len(parts) == 2 and parts[0].isdigit():
                # Keyed by PID: BeyondEditor runs as two processes, and keying by name
                # silently drops one of them.
                found[int(parts[0])] = parts[1]
        return found

    def io(self, pid: int) -> tuple[int, int]:
        script = (f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" "
                  "-ErrorAction SilentlyContinue; "
                  "if ($p) { \"$($p.WriteTransferCount)|$($p.WriteOperationCount)\" } else { \"0|0\" }")
        line = self.ask(script)
        try:
            a, b = line.split("|")
            return int(a), int(b)
        except ValueError:
            return 0, 0

    def close(self) -> None:
        return None


def snapshot(files: list[Path]) -> dict[str, tuple[int, int] | None]:
    out: dict[str, tuple[int, int] | None] = {}
    for p in files:
        try:
            st = p.stat()
            out[str(p)] = (st.st_size, st.st_mtime_ns)
        except OSError:
            out[str(p)] = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=1800)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--log", default=None)
    args = ap.parse_args()

    files = watched(save_root())
    sampler = Sampler()
    pids = sampler.processes()
    log_path = Path(args.log) if args.log else (ROOT / ".runtime" / "beyond-save" / "write-attribution.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = io.open(log_path, "a", encoding="utf-8")

    def say(line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        text = f"[{stamp}] {line}"
        print(text, flush=True)
        log_file.write(text + "\n")
        log_file.flush()

    say(f"watching {len(files)} save file(s); processes: {pids}")
    prev_files = snapshot(files)
    prev_io = {pid: sampler.io(pid) for pid in pids}
    baseline_io = dict(prev_io)

    start = time.time()
    attributed = 0
    try:
        while time.time() - start < args.seconds:
            time.sleep(args.interval)
            cur_files = snapshot(files)
            changed = [k for k in cur_files if cur_files[k] != prev_files.get(k)]

            live = sampler.processes()
            if set(live) != set(pids):
                say(f"process set changed: {pids} -> {live}")
                for pid in live:
                    prev_io.setdefault(pid, sampler.io(pid))
                    baseline_io.setdefault(pid, prev_io[pid])
                pids = live

            cur_io = {pid: sampler.io(pid) for pid in pids}
            delta = {pid: (cur_io[pid][0] - prev_io.get(pid, cur_io[pid])[0],
                           cur_io[pid][1] - prev_io.get(pid, cur_io[pid])[1]) for pid in pids}

            if changed:
                writers = {pid: d for pid, d in delta.items() if d[1] > 0}
                say(f"SAVE FILE CHANGED: {[Path(c).name for c in changed]}")
                say(f"    write deltas in the same tick: {delta}")
                if len(writers) == 1:
                    pid = next(iter(writers))
                    say(f"    => ATTRIBUTED to pid {pid} ({pids.get(pid)})")
                    attributed += 1
                elif not writers:
                    say("    => no process showed a write this tick; widen --interval")
                else:
                    say(f"    => ambiguous, {len(writers)} processes wrote this tick")

            prev_files = cur_files
            prev_io = cur_io
    except KeyboardInterrupt:
        say("interrupted")

    say(f"finished after {int(time.time() - start)}s; attributed writes: {attributed}")
    say("total writes since start:")
    for pid, name in pids.items():
        cur = sampler.io(pid)
        say(f"    pid={pid:<8} {name:<14} bytes={cur[0]-baseline_io.get(pid,(0,0))[0]:>12} "
            f"ops={cur[1]-baseline_io.get(pid,(0,0))[1]:>9}")
    sampler.close()
    log_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
