#!/usr/bin/env python3
"""Say which save is current, cheaply and read-only.

WHY THIS EXISTS
    Level ids and account ids are a function of whatever save is loaded, and the
    user changes saves. Anything pinned from a previous session is therefore
    worthless. Run this before any real-machine action and use what it prints.

WHAT IT TOUCHES
    Nothing but files, and only for reading. No game contact, no helper, no UAC,
    no network, no writes anywhere. It works with the game closed.

WHAT IT PRINTS
    1. every account directory found under the game's LocalLow store;
    2. the levels of the account that was written to most recently, with the
       level that was written to last called out;
    3. the most recent NATIVE observation, if any, with its age -- that is the
       only source that knows which level the running game actually has loaded;
    4. the elevated helper's recorded state and how old that record is.

    (2) is disk truth. (3) is what the game looked like at some past moment and
    may be stale; the age is printed so it can be judged rather than trusted.

USAGE
    python tools/game-executor/current-save.py
    python tools/game-executor/current-save.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "beyond-save"))

try:
    from gil_container import ContainerError, decode_container, parse_profile
except ImportError as exc:  # pragma: no cover - only when run from elsewhere
    raise SystemExit(f"cannot import gil_container from tools/beyond-save: {exc}")

LOCALLOW = pathlib.Path(os.environ.get("USERPROFILE", pathlib.Path.home())) / (
    "AppData/LocalLow/miHoYo")
LEVEL_DIR = "Beyond_Local_Save_Level"
PROFILE_FILE = "Beyond_Local_Save_Player.gip"
INSPECT_ROOT = ROOT / ".runtime/game-executor/scene-cli/inspect"
POINTER = ROOT / ".runtime/editor-bridge/current-elevated-session.json"
STALE_MINUTES = 60
_SKIPPED = [0]  # store directories seen but not counted as accounts


def human_age(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return f"{seconds:.0f}s ago"
    if seconds < 5400:
        return f"{seconds / 60:.0f}min ago"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


def newest_mtime(root: pathlib.Path, limit: int = 4000) -> float | None:
    """Newest mtime under root, bounded so a huge tree cannot stall the command."""
    newest: float | None = None
    seen = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                stamp = os.stat(os.path.join(dirpath, name)).st_mtime
            except OSError:
                continue
            seen += 1
            if newest is None or stamp > newest:
                newest = stamp
            if seen >= limit:
                return newest
    return newest


def read_profile(uid_dir: pathlib.Path) -> tuple[list[dict], str | None]:
    path = uid_dir / PROFILE_FILE
    if not path.is_file():
        return [], "no player profile file"
    try:
        profile = parse_profile(decode_container(path.read_bytes()).payload)
    except (ContainerError, OSError, ValueError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    rows = [{"levelId": r.level_id, "name": r.name, "registeredAt": r.timestamp}
            for r in profile.levels]
    return rows, None


def scan_accounts() -> list[dict]:
    """Every <game>/BeyondLocal/<uid> store on this machine.

    Only all-digit directory names are accounts; the store also holds sibling
    directories with ordinary names (exports, images, runtime caches), and those
    are counted separately rather than reported as empty accounts.
    """
    accounts: list[dict] = []
    skipped = 0
    if not LOCALLOW.is_dir():
        return accounts
    for game_dir in sorted(LOCALLOW.iterdir()):
        store = game_dir / "BeyondLocal"
        if not store.is_dir():
            continue
        for uid_dir in sorted(store.iterdir()):
            if not uid_dir.is_dir():
                continue
            if not uid_dir.name.isdigit():
                skipped += 1
                continue
            level_root = uid_dir / LEVEL_DIR
            rows, err = read_profile(uid_dir)
            by_id = {r["levelId"]: r for r in rows}
            levels: list[dict] = []
            if level_root.is_dir():
                for entry in sorted(level_root.iterdir()):
                    gil = entry / f"{entry.name}.gil" if entry.is_dir() else entry
                    if not gil.is_file() or gil.suffix != ".gil":
                        continue
                    level_id = int(gil.stem) if gil.stem.isdigit() else None
                    stat = gil.stat()
                    levels.append({
                        "levelId": level_id,
                        "name": (by_id.get(level_id) or {}).get("name"),
                        "registered": level_id in by_id,
                        "bytes": stat.st_size,
                        "writtenAt": stat.st_mtime,
                    })
            levels.sort(key=lambda r: r["writtenAt"], reverse=True)
            accounts.append({
                "game": game_dir.name,
                "uid": uid_dir.name,
                "path": str(uid_dir),
                "levels": levels,
                "profileError": err,
                "newestWrite": levels[0]["writtenAt"] if levels else None,
            })
    accounts.sort(key=lambda a: a["newestWrite"] or 0, reverse=True)
    _SKIPPED[0] = skipped
    return accounts


def last_native_observation() -> dict | None:
    """The newest successful native inspect: the only record of the LOADED level."""
    if not INSPECT_ROOT.is_dir():
        return None
    for run in sorted(INSPECT_ROOT.iterdir(), key=lambda p: p.name, reverse=True):
        result = run / "result.json"
        if not result.is_file():
            continue
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not data.get("ok"):
            continue
        return {
            "run": run.name,
            "levelId": data.get("levelId"),
            "entities": data.get("entities"),
            "action": data.get("action"),
            "ageSeconds": max(0.0, time.time() - result.stat().st_mtime),
        }
    return None


def helper_state() -> dict | None:
    if not POINTER.is_file():
        return None
    try:
        data = json.loads(POINTER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    age = max(0.0, time.time() - POINTER.stat().st_mtime)
    return {
        "helperPid": data.get("helperPid"),
        "status": data.get("status"),
        "deadlineUtc": data.get("deadlineUtc"),
        "pointerAgeSeconds": age,
    }


def collect() -> dict:
    accounts = scan_accounts()
    with_levels = [a for a in accounts if a["levels"]]
    return {
        "measuredAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "locallow": str(LOCALLOW),
        "accounts": accounts,
        "activeUid": with_levels[0]["uid"] if with_levels else None,
        "skippedStoreDirs": _SKIPPED[0],
        "lastNativeObservation": last_native_observation(),
        "helper": helper_state(),
        "staleMinutes": STALE_MINUTES,
    }


def render(data: dict) -> str:
    out: list[str] = []
    out.append(f"measured      : {data['measuredAt']}   (disk only; game not contacted)")

    if not data["accounts"]:
        out.append("accounts      : NONE -- looked under " + data["locallow"])
    else:
        out.append(f"accounts      : {len(data['accounts'])} found "
                   f"({data['skippedStoreDirs']} non-uid store dirs skipped)")
    for acc in data["accounts"]:
        mark = "  <- most recently written" if acc["uid"] == data["activeUid"] else ""
        out.append(f"  uid {acc['uid']:<12} {len(acc['levels'])} level(s){mark}")
        if not acc["levels"]:
            extra = f"  ({acc['profileError']})" if acc["profileError"] else ""
            out.append(f"      no levels on disk{extra}")
            continue
        for i, lv in enumerate(acc["levels"][:12]):
            tag = "last written" if i == 0 else "            "
            name = lv["name"] or ("(not in profile list)" if not lv["registered"] else "?")
            out.append(f"      {tag}  {lv['levelId']:<12} {name[:34]:<34} "
                       f"{lv['bytes']:>8} B  {human_age(time.time() - lv['writtenAt'])}")

    obs = data["lastNativeObservation"]
    out.append("")
    if obs is None:
        out.append("loaded level  : NO native observation on record. The running game's "
                   "level is UNKNOWN; only a native read can say.")
    else:
        age = obs["ageSeconds"]
        stale = "STALE" if age > data["staleMinutes"] * 60 else "fresh"
        out.append(f"loaded level  : {obs['levelId']} with {obs['entities']} entities "
                   f"({stale}, {human_age(age)}, run {obs['run']})")
        out.append("                ^ this is when the game was last READ, not necessarily now")

    helper = data["helper"]
    if helper is None:
        out.append("helper        : no pointer file -- elevated native writes unavailable")
    else:
        out.append(f"helper        : pid {helper['helperPid']} status={helper['status']} "
                   f"deadline={helper['deadlineUtc']} (pointer {human_age(helper['pointerAgeSeconds'])})")

    out.append("")
    out.append("rule          : level ids are a function of the loaded save. Re-run this "
               "before every real-machine action; do not reuse an id from a previous run.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    # Level names are Chinese; a cp936 console would otherwise garble them.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    data = collect()
    print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
