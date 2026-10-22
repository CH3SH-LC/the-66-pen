"""Merge verified static scene fields into newdemo, with backup and readback.

Dry run by default. This updates disk only; it never claims live scene loading.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/compatibility'))
from version_guard import IncompatibleVersion, require_compatible

spec = importlib.util.spec_from_file_location('static_builder', Path(__file__).with_name('build-newdemo-static.py'))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def merge(current, baseline, candidate):
    h = builder.read_header(current)
    assert h.file_type == 2
    payload = current[20:-4]
    for field in (5, 6, 10):
        old = builder.only(baseline[20:-4], field)
        new = builder.only(candidate[20:-4], field)
        actual = builder.only(payload, field)
        if actual not in (old, new):
            raise ValueError(f'Concurrent or unexpected change in root field {field}')
        payload = builder.replace(payload, field, new)
    result = builder.wrap_payload(payload, h.file_type, h.version)
    assert [(f,r) for f,w,p,r in builder.raw.spans(current[20:-4]) if f not in (5,6,10)] == [(f,r) for f,w,p,r in builder.raw.spans(payload) if f not in (5,6,10)]
    return result


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('save', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        require_compatible('all')  # Before reading formal saves or preparing a write.
    target = args.save.resolve(strict=True)
    assert target.name == '1073741831.gil'
    doc = builder.parse_gi_file(target)
    assert doc.level_name.startswith('newdemo') and doc.node_graph_count == 3
    before = target.read_bytes()
    baseline = builder.SOURCE.read_bytes()
    candidate = (builder.OUT / 'newdemo-static-final-candidate.gil').read_bytes()
    after = merge(before, baseline, candidate)
    assert merge(after, baseline, candidate) == after
    digest = lambda data: hashlib.sha256(data).hexdigest()
    report = dict(applied=False, target=str(target), beforeSha256=digest(before), afterSha256=digest(after), changedRootFields=[5,6,10], bytes=len(after), liveSceneVerified=False)
    if args.apply and before != after:
        require_compatible('all')
        backup = builder.OUT / ('before-static-write-' + digest(before) + '.gil')
        if backup.exists():
            assert backup.read_bytes() == before
        else:
            with backup.open('xb') as stream:
                stream.write(before)
                stream.flush()
                os.fsync(stream.fileno())
        temp = None
        try:
            require_compatible('all')  # Before a temporary file is created beside the save.
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.tmp', delete=False) as stream:
                temp = Path(stream.name)
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            assert temp.read_bytes() == after
            if target.read_bytes() != before:
                raise ValueError('Save changed during preparation; no replacement performed')
            require_compatible('all')
            os.replace(temp, target)
            assert target.read_bytes() == after
            report.update(applied=True, backup=str(backup), readbackVerified=True)
        finally:
            if temp is not None and temp.exists():
                temp.unlink()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.apply:
        (builder.OUT / 'static-disk-write.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    try:
        _main()
        return 0
    except IncompatibleVersion as error:
        print(json.dumps(error.report, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
