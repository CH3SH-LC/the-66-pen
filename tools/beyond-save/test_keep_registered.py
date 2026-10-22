"""Does the keeper restore a registration the writer removed?

The whole point of keep_registered.py is behaviour over time: a single write is lost,
so the keeper has to notice the loss and put it back. That cannot be tested by calling
a function -- it needs the file to be clobbered while the keeper is running, which is
what this does, against a copy of the live save.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

# The keeper's log lines carry Chinese; a GBK console cannot print them back.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "beyond-save"))

from gil_container import decode_container, parse_profile  # noqa: E402

NAME = "MW_Demo_存档"
TAB = "MW_Demo"


def profile_names(uid_dir: Path) -> list[str]:
    payload = decode_container((uid_dir / "Beyond_Local_Save_Player.gip").read_bytes()).payload
    return [r.name for r in parse_profile(payload).levels]


def main() -> int:
    live = None
    for sub in (Path.home() / "AppData" / "LocalLow" / "miHoYo").iterdir():
        if (sub / "BeyondLocal").is_dir():
            live = sub / "BeyondLocal" / "100000001"
    if live is None or not live.is_dir():
        print("skip: no live save")
        return 0

    work = ROOT / ".runtime" / "beyond-save" / "keeper-test"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(live, work)

    original = (work / "Beyond_Local_Save_Player.gip").read_bytes()
    passed = 0
    failed = 0

    def check(name: str, ok: bool) -> None:
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}")

    print("before:", len(original), "bytes;", len(profile_names(work)), "archives")
    check("the copy starts without our archive", NAME not in profile_names(work))

    # Arm the keeper over the copy for a short window.
    keeper = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "tools" / "beyond-save" / "keep_registered.py"),
         "--uid-dir", str(work), "--name", NAME, "--tab", TAB,
         "--apply", "--seconds", "25", "--interval", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")

    time.sleep(6)
    check("keeper registered the archive", NAME in profile_names(work))

    # Clobber it exactly the way the real writer does: put the old bytes back.
    (work / "Beyond_Local_Save_Player.gip").write_bytes(original)
    check("the clobber removed the registration", NAME not in profile_names(work))

    time.sleep(8)
    check("keeper restored it after the clobber", NAME in profile_names(work))

    # And it must survive a second clobber.
    (work / "Beyond_Local_Save_Player.gip").write_bytes(original)
    time.sleep(8)
    check("keeper restored it a second time", NAME in profile_names(work))

    keeper.terminate()
    try:
        out = keeper.communicate(timeout=10)[0]
    except subprocess.TimeoutExpired:
        keeper.kill()
        out = ""
    print()
    print("keeper output (tail):")
    for line in out.strip().splitlines()[-8:]:
        print("   " + line)

    shutil.rmtree(work, ignore_errors=True)
    print(f"\npassed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
