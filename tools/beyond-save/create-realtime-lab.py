"""Create an isolated lab from the user-confirmed blank newdemo baseline.

Writes a level and profile registration, not an in-game create/open command.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import register_level as reg
from version_guard import IncompatibleVersion, require_compatible

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.runtime/verification/realtime-injection-20260920'
NAME = 'MW_Realtime_Lab_20260920'


def atomic_replace(path, data, expected):
    require_compatible("all")  # Before creating a temporary file beside a live save.
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.', suffix='.tmp', delete=False) as f:
            temp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.read_bytes() != expected:
            raise RuntimeError('Concurrent profile change; no replacement performed')
        require_compatible("all")
        os.replace(temp, path)
        assert path.read_bytes() == data
    finally:
        if temp and temp.exists():
            temp.unlink()


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        require_compatible("all")
    profile_path = reg.GAME_DATA / reg.DEFAULT_UID / 'Beyond_Local_Save_Player.gip'
    profile_before = profile_path.read_bytes()
    profile = reg.parse_profile(reg.decode_container(profile_before).payload)
    if any(r.name == NAME for r in profile.levels):
        raise RuntimeError('Lab already registered; inspect it instead of creating duplicates')
    plan = reg.plan_registration(NAME, tab_name=NAME)
    template = ROOT / '.runtime/verification/newdemo-20260919/playable-user-baseline.gil'
    source = template.read_bytes()
    assert hashlib.sha256(source).hexdigest() == 'fadcd469920e81a5504bd33f6334c2c1dd7be607bd5176c6782e4c071c3d8058'
    plan.level_payload = reg.build_new_level(reg.decode_container(source).payload, plan.level_id, NAME, int(reg.DEFAULT_UID), int(time.time()))
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'plan':plan.describe(), 'staged':reg.stage_registration(plan, OUT / 'registration-candidate'), 'applied':False, 'gameLoaded':False}
    if args.apply:
        backup = reg.take_backup(plan)
        level_dir = plan.level_path.parent
        before = {p.name:p.read_bytes() for p in level_dir.glob('*.gil')}
        for name,data in before.items():
            assert (Path(backup['levels']) / name).read_bytes() == data
        assert plan.profile_path.read_bytes() == profile_before
        assert Path(backup['profile']).read_bytes() == profile_before
        level_data = reg.encode_container(reg.Container(2,plan.level_payload))
        require_compatible("all")
        with plan.level_path.open('xb') as f:
            f.write(level_data)
            f.flush()
            os.fsync(f.fileno())
        assert plan.level_path.read_bytes() == level_data
        atomic_replace(plan.profile_path,reg.encode_container(reg.Container(1,plan.profile_payload)),profile_before)
        assert all((level_dir / name).read_bytes() == data for name,data in before.items())
        report.update(applied=True,backup=backup,readback=reg.verify_registration(plan),existingLevelsUnchanged=True,levelSha256=hashlib.sha256(level_data).hexdigest())
    (OUT / ('registration-applied.json' if args.apply else 'registration-plan.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


def main():
    try:
        _main()
        return 0
    except IncompatibleVersion as error:
        print(json.dumps(error.report, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
