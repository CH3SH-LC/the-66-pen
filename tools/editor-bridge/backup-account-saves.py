#!/usr/bin/env python3
"""Bounded, hash-verified backup and restore of the Genshin account save set.

Scope, deliberately narrow:

* The account set is ``BeyondLocal/<uid>/**`` -- the 38 files this project has
  always treated as the formal account state. The multi-megabyte
  ``Beyond_Local_Save_Runtime*`` caches are NOT part of it and are not copied.
* Reads the game's userdata; never writes to it. Everything written lands under
  ``.runtime/editor-bridge/backups`` inside the project.
* Restore is BOUNDED: one named file, into a caller-supplied sandbox directory
  under ``.runtime``. This tool cannot restore over the live save, by design --
  a live restore under a running game is a different, separately reviewed action.

Subcommands:

    create  --label NAME            snapshot the account set; write manifest
    verify  --backup DIR            re-read every file and compare to manifest
    restore --backup DIR --only REL --dest DIR
                                    bounded restore of one file into a sandbox,
                                    then an independent hash read-back
    show    --backup DIR            print the manifest summary

``verify`` is the independent read-back: it does not trust the manifest's own
hashes for the copy, it re-hashes what is on disk. It is also the bad-backup
gate -- any missing, resized, or content-changed file refuses with a reason.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_ROOT = Path(os.environ['USERPROFILE']) / 'AppData/LocalLow/miHoYo/原神/BeyondLocal'
BACKUP_ROOT = ROOT / '.runtime/editor-bridge/backups'
SCHEMA = 1


class BackupError(ValueError):
    """Every refusal path raises this, so no caller can mistake it for success."""


def require(ok, reason):
    if not ok:
        raise BackupError(reason)


def sha256(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def account_uid_dir():
    """The single numeric uid directory that actually holds account state.

    Two numeric directories exist on this machine: the live account and an empty
    leftover from a previous install (0 files, untouched since 2026-08-22).
    A bare count test refuses on that pair, so emptiness is what decides:
    exactly one numeric directory must be non-empty. Two non-empty candidates
    still refuse -- silently picking one would let a backup run against the
    wrong account and report success anyway.

    Returns the chosen directory plus the numeric directories that were skipped,
    so the reason for the choice is recorded rather than assumed.
    """
    require(ACCOUNT_ROOT.is_dir(), 'ACCOUNT_ROOT_MISSING:' + str(ACCOUNT_ROOT))
    numeric = sorted(p for p in ACCOUNT_ROOT.iterdir() if p.is_dir() and p.name.isdigit())
    populated = [p for p in numeric if any(f.is_file() for f in p.rglob('*'))]
    require(len(populated) == 1, 'ACCOUNT_UID_CANDIDATES:' + ','.join(
        p.name for p in populated) + ' of ' + ','.join(p.name for p in numeric))
    skipped = [{'name': p.name, 'reason': 'empty-numeric-directory'}
               for p in numeric if p != populated[0]]
    return populated[0], skipped


def collect(uid_dir: Path):
    files = []
    for path in sorted(uid_dir.rglob('*')):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append({
            'relpath': path.relative_to(uid_dir).as_posix(),
            'size': stat.st_size,
            'mtimeNs': stat.st_mtime_ns,
            'sha256': sha256(path),
        })
    require(files, 'ACCOUNT_SET_EMPTY')
    return files


def cmd_create(args) -> dict:
    uid_dir, skipped = account_uid_dir()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest = BACKUP_ROOT / (stamp + '-' + args.label)
    require(not dest.exists(), 'BACKUP_DIR_EXISTS:' + str(dest))
    files = collect(uid_dir)
    dest.mkdir(parents=True)
    for entry in files:
        source = uid_dir / entry['relpath']
        target = dest / 'files' / entry['relpath']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        require(sha256(target) == entry['sha256'], 'COPY_HASH_MISMATCH:' + entry['relpath'])
    manifest = {
        'schemaVersion': SCHEMA,
        'createdUtc': utc_now(),
        'label': args.label,
        'source': str(uid_dir),
        'skippedNumericDirs': skipped,
        'fileCount': len(files),
        'totalBytes': sum(e['size'] for e in files),
        'files': files,
    }
    (dest / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'ok': True, 'action': 'create', 'backup': str(dest),
            'fileCount': len(files), 'totalBytes': manifest['totalBytes']}


def load_manifest(backup: Path) -> dict:
    path = Path(backup) / 'manifest.json'
    require(path.is_file(), 'MANIFEST_MISSING:' + str(path))
    manifest = json.loads(path.read_text(encoding='utf-8'))
    require(manifest.get('schemaVersion') == SCHEMA, 'MANIFEST_SCHEMA')
    require(isinstance(manifest.get('files'), list) and manifest['files'], 'MANIFEST_FILES')
    return manifest


def verify_backup(backup: Path) -> dict:
    """Re-hash every copied file against the manifest. Returns the failures.

    Never raises for a bad file: the caller decides. Raising here would make a
    corrupt backup indistinguishable from a missing one.
    """
    manifest = load_manifest(backup)
    missing, changed, ok = [], [], 0
    for entry in manifest['files']:
        path = Path(backup) / 'files' / entry['relpath']
        if not path.is_file():
            missing.append(entry['relpath'])
            continue
        stat = path.stat()
        if stat.st_size != entry['size'] or sha256(path) != entry['sha256']:
            changed.append(entry['relpath'])
            continue
        ok += 1
    return {'ok': not missing and not changed, 'verified': ok,
            'expected': len(manifest['files']), 'missing': missing, 'changed': changed}


def cmd_verify(args) -> dict:
    backup = Path(args.backup).resolve()
    result = verify_backup(backup)
    manifest = load_manifest(backup)
    return dict(result, action='verify', backup=str(backup),
                label=manifest.get('label'), createdUtc=manifest.get('createdUtc'))


def cmd_restore(args) -> dict:
    backup = Path(args.backup).resolve()
    sandbox = Path(args.dest).resolve()
    runtime = (ROOT / '.runtime').resolve()
    require(sandbox.is_relative_to(runtime), 'SANDBOX_OUTSIDE_RUNTIME:' + str(sandbox))
    gate = verify_backup(backup)
    require(gate['ok'], 'BAD_BACKUP_REFUSED:missing=%s:changed=%s'
            % (','.join(gate['missing']), ','.join(gate['changed'])))
    manifest = load_manifest(backup)
    entry = next((e for e in manifest['files'] if e['relpath'] == args.only), None)
    require(entry is not None, 'REL_NOT_IN_MANIFEST:' + str(args.only))
    source = backup / 'files' / entry['relpath']
    target = sandbox / Path(entry['relpath']).name
    require(not target.exists(), 'RESTORE_TARGET_EXISTS:' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    # Independent read-back: re-hash from disk and compare to the manifest value.
    restored = sha256(target)
    require(restored == entry['sha256'], 'RESTORE_READBACK_MISMATCH')
    return {'ok': True, 'action': 'restore', 'backup': str(backup), 'only': entry['relpath'],
            'restoredTo': str(target), 'bytes': target.stat().st_size,
            'sha256': restored, 'readbackVerified': True}


def cmd_show(args) -> dict:
    backup = Path(args.backup).resolve()
    manifest = load_manifest(backup)
    return {'ok': True, 'action': 'show', 'backup': str(backup),
            'label': manifest.get('label'), 'createdUtc': manifest.get('createdUtc'),
            'source': manifest.get('source'), 'fileCount': manifest.get('fileCount'),
            'totalBytes': manifest.get('totalBytes'),
            'relpaths': [e['relpath'] for e in manifest['files']]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('--label', required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('--backup', required=True)
    restore = sub.add_parser('restore')
    restore.add_argument('--backup', required=True)
    restore.add_argument('--only', required=True)
    restore.add_argument('--dest', required=True)
    show = sub.add_parser('show')
    show.add_argument('--backup', required=True)
    args = parser.parse_args()
    handlers = {'create': cmd_create, 'verify': cmd_verify,
                'restore': cmd_restore, 'show': cmd_show}
    try:
        result = handlers[args.command](args)
    except BackupError as error:
        print(json.dumps({'ok': False, 'action': args.command, 'error': str(error)},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    sys.exit(main())
