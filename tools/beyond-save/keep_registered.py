#!/usr/bin/env python3
"""Keep a registered archive present in the live profile, across the writer's rewrites.

WHY THIS EXISTS
    register_level.py writes a new archive into the player profile, and something else
    -- the game or the editor -- rewrites that profile from its own memory. A single
    write is therefore always lost: at 13:32 the file on disk held our 380-byte version
    and the writer replaced it with its own 323-byte one, which proves the writer does
    not re-read the file before writing.

    That kills a one-shot registration. It does not kill the goal. The writer only
    rewrites on its own events, and it has done so twice in ~12 hours. If the
    registration is re-applied whenever it is missing, then the file carries it at
    every moment the game might read it -- in particular at startup, which is when a
    profile store of this kind is loaded. The registration then takes effect on the
    next launch.

WHAT IT DOES NOT DO
    It is not a substitute for an editor API. Nothing here makes the running game see
    a new archive without a restart; it makes the registration durable on disk so that
    the restart finds it. It also cannot create the archive's geometry -- it re-applies
    the level descriptor and the profile entry, which is what registration is.

SAFETY
    Every write requires the fixed supported game/editor version. Registration is
    restored only when missing; concurrent writer atomicity is not guaranteed. Before the first write it
    takes a verified backup. The archive's own .gil file is written only if absent.
    --apply is required; without it the tool only reports what it would do.

    python keep_registered.py --plan
    python keep_registered.py --apply [--seconds 43200]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools/compatibility"))
from version_guard import IncompatibleVersion, require_compatible  # noqa: E402

from gil_container import (  # noqa: E402
    Container,
    Field,
    WIRE_LENGTH,
    WIRE_VARINT,
    add_level_to_profile,
    build_profile,
    decode_container,
    encode_container,
    encode_fields,
    parse_fields,
    parse_profile,
    read_level,
)

ROOT = HERE.parents[1]
DEFAULT_UID = "100000001"
STATE = ROOT / ".runtime" / "beyond-save" / "keep-registered.json"
BACKUP_ROOT = ROOT / ".runtime" / "beyond-save" / "backups"


def save_root() -> Path:
    mihoyo = Path.home() / "AppData" / "LocalLow" / "miHoYo"
    for sub in mihoyo.iterdir():
        candidate = sub / "BeyondLocal"
        if candidate.is_dir():
            return candidate
    raise SystemExit(f"no BeyondLocal directory under {mihoyo}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_state() -> dict | None:
    if not STATE.exists():
        return None
    return json.loads(STATE.read_text(encoding="utf-8"))


def build_registered_profile(uid_dir: Path, name: str, tab: str, level_id: int | None):
    """The profile as it should be: the live one, plus our archive, if it is missing."""
    profile_path = uid_dir / "Beyond_Local_Save_Player.gip"
    profile = parse_profile(decode_container(profile_path.read_bytes()).payload)

    existing_by_name = {r.name: r.level_id for r in profile.levels}
    if name in existing_by_name:
        return None, existing_by_name[name], "already-registered"

    files = sorted((uid_dir / "Beyond_Local_Save_Level").glob("*.gil"))
    if not files:
        raise SystemExit("no level files to derive an id from")

    if level_id is None:
        level_id = max(int(p.stem) for p in files) + 1
    if any(r.level_id == level_id for r in profile.levels):
        raise SystemExit(f"level id {level_id} is already listed in the profile")

    add_level_to_profile(profile, level_id, name, int(time.time()), tab_name=tab)
    return build_profile(profile), level_id, "built"


def build_level_payload(template_payload: bytes, level_id: int, name: str, uid: int) -> bytes:
    fields = [f for f in parse_fields(template_payload) if f.number not in (1, 2, 39, 40)]
    fields.append(Field(1, WIRE_VARINT, value=level_id))
    fields.append(Field(2, WIRE_LENGTH, data=name.encode("utf-8")))
    fields.append(Field(39, WIRE_VARINT, value=uid))
    fields.append(Field(40, WIRE_VARINT, value=int(time.time())))
    return encode_fields(sorted(fields, key=lambda f: f.number))


def ensure_registered(uid_dir: Path, name: str, tab: str, level_id: int, uid: str) -> str:
    """One bounded iteration; every actual write gets a fresh version check."""
    profile_path = uid_dir / "Beyond_Local_Save_Player.gip"
    level_dir = uid_dir / "Beyond_Local_Save_Level"
    level_path = level_dir / f"{level_id}.gil"
    profile = parse_profile(decode_container(profile_path.read_bytes()).payload)
    if any(r.name == name for r in profile.levels):
        return "present"
    rebuilt = build_registered_profile(uid_dir, name, tab, level_id)[0]
    if rebuilt is None:
        return "present"
    require_compatible("all")
    profile_path.write_bytes(encode_container(Container(subtype=1, payload=rebuilt)))
    if not level_path.exists():
        template = min(level_dir.glob("*.gil"), key=lambda p: p.stat().st_size)
        payload_lv = build_level_payload(
            decode_container(template.read_bytes()).payload, level_id, name, int(uid))
        require_compatible("all")
        level_path.write_bytes(encode_container(Container(subtype=2, payload=payload_lv)))
    return "re-applied"


def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="MW_Demo_存档")
    ap.add_argument("--tab", default="MW_Demo")
    ap.add_argument("--uid", default=DEFAULT_UID)
    ap.add_argument("--level-id", type=int, default=None)
    ap.add_argument("--uid-dir", default=None,
                    help="operate on this directory instead of the live save (for testing)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--seconds", type=int, default=43200)
    ap.add_argument("--interval", type=float, default=3.0)
    args = ap.parse_args()
    if args.apply:
        require_compatible("all")  # Refuse before live reads, backups, or loop setup.

    uid_dir = Path(args.uid_dir) if args.uid_dir else (save_root() / args.uid)
    profile_path = uid_dir / "Beyond_Local_Save_Player.gip"
    level_dir = uid_dir / "Beyond_Local_Save_Level"

    payload, level_id, why = build_registered_profile(uid_dir, args.name, args.tab, args.level_id)
    print(json.dumps({
        "uidDir": str(uid_dir), "levelId": level_id, "name": args.name, "tab": args.tab,
        "decision": why,
        "profileBytesIfWritten": len(payload) if payload else None,
    }, ensure_ascii=False, indent=1))

    if not args.apply:
        print("\nplan only -- nothing written. Re-run with --apply to arm the keeper.")
        return 0

    if payload is None:
        print("already present; nothing to do")
        return 0

    # Backup once, verified.
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    backup = BACKUP_ROOT / f"{stamp}-keep-registered"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(profile_path, backup / profile_path.name)
    if sha(backup / profile_path.name) != sha(profile_path):
        raise SystemExit("backup verification failed")
    shutil.copytree(level_dir, backup / "Beyond_Local_Save_Level")
    print(f"backup: {backup}")

    level_path = level_dir / f"{level_id}.gil"

    def ensure() -> str:
        return ensure_registered(uid_dir, args.name, args.tab, level_id, args.uid)

    state = {"name": args.name, "tab": args.tab, "levelId": level_id, "backup": str(backup)}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    (ROOT / ".runtime" / "beyond-save").mkdir(parents=True, exist_ok=True)

    log = ROOT / ".runtime" / "beyond-save" / "keep-registered.log"
    log_file = io.open(log, "a", encoding="utf-8")

    def say(text: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    say(f"armed: {args.name} (level {level_id}) under tab {args.tab}; window {args.seconds}s")
    applied = 0
    start = time.time()
    current = ensure()
    if current != "present":
        applied += 1
        say(f"initial: {current}")
    try:
        while time.time() - start < args.seconds:
            time.sleep(args.interval)
            action = ensure()
            if action != "present":
                applied += 1
                say(f"{action} -- the writer had removed it; registration restored")
    except KeyboardInterrupt:
        say("interrupted")
    say(f"finished after {int(time.time() - start)}s; restorations: {applied}")
    log_file.close()
    return 0


def main() -> int:
    try:
        return _main()
    except IncompatibleVersion as error:
        print(json.dumps(error.report, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
