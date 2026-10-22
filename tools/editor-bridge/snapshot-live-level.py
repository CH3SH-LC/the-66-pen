#!/usr/bin/env python3
"""Read-only snapshot of the live level save (.gil) into a project snapshot directory.

Boundary
--------
* The source save is opened read-only and is never written, moved or replaced.
* The output directory must resolve inside the project root: this tool refuses to
  write anywhere else, so it can never stage a file into the game's LocalLow tree.
* An existing snapshot is never overwritten unless --allow-replace is given, and
  even then the previous file is compared and reported first.
* "stable" means N consecutive reads agreed on (size, mtime_ns, sha256). It does
  NOT mean the game has finished writing; a save that is stable-but-mid-write is
  not distinguishable by this tool alone.

Claim scope
-----------
Proves: the bytes in the snapshot equal the bytes in the live save at read time,
and that the file was quiescent across the observation window.
Does NOT prove: that the game flushed all in-memory level content, that the file
is the level currently open in the editor, or anything about runtime behaviour.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

GAME_LOCAL_LOW = Path(os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\miHoYo\原神'))
DEFAULT_SOURCE = GAME_LOCAL_LOW / 'BeyondLocal' / '100000001' / 'Beyond_Local_Save_Level' / '1073741825.gil'

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_UNSTABLE = 3
EXIT_USAGE = 4


class Refused(Exception):
    """Tool declined to act; never a silent success."""


def _sha256(path: Path) -> tuple[str, int, int]:
    """Stream one file read-only; returns (sha256, size, mtime_ns)."""
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    stat = path.stat()
    return digest.hexdigest(), stat.st_size, stat.st_mtime_ns


def observe(path: Path, rounds: int, gap_seconds: float) -> list[dict]:
    """Take `rounds` read-only observations, sleeping `gap_seconds` between them."""
    if not path.is_file():
        raise Refused(f'source save does not exist: {path}')
    observations = []
    for index in range(rounds):
        if index:
            time.sleep(gap_seconds)
        sha, size, mtime_ns = _sha256(path)
        observations.append({'round': index + 1, 'sha256': sha, 'bytes': size, 'mtimeNs': mtime_ns})
    return observations


def is_stable(observations: list[dict]) -> bool:
    if len(observations) < 2:
        return False
    first = observations[0]
    return all(o['sha256'] == first['sha256'] and o['bytes'] == first['bytes']
               and o['mtimeNs'] == first['mtimeNs'] for o in observations[1:])


def ensure_inside_project(directory: Path) -> Path:
    resolved = directory.resolve()
    if resolved != PROJECT_ROOT and PROJECT_ROOT not in resolved.parents:
        raise Refused(f'output directory must live inside the project root: {resolved}')
    return resolved


def snapshot(source: Path, output_dir: Path, rounds: int, gap_seconds: float,
             allow_replace: bool, destination_name: str) -> dict:
    """Copy the live save into the project snapshot directory after a stability check."""
    output_dir = ensure_inside_project(output_dir)
    observations = observe(source, rounds, gap_seconds)
    stable = is_stable(observations)
    latest = observations[-1]

    resolved_source = source.resolve()
    receipt = {
        'tool': 'snapshot-live-level.py',
        'source': str(source),
        'sourceInsideGameLocalLow': GAME_LOCAL_LOW.resolve() in resolved_source.parents,
        'sourceIsDefaultSave': resolved_source == DEFAULT_SOURCE.resolve(),
        'observations': observations,
        'stableRead': stable,
    }

    if not stable:
        receipt.update({'ok': False, 'reason': 'source changed across the observation window; nothing was written',
                        'output': None})
        return receipt

    destination = output_dir / destination_name
    if destination.exists() and not allow_replace:
        existing_sha, existing_bytes, _ = _sha256(destination)
        receipt.update({
            'ok': False,
            'reason': 'snapshot already exists; refusing to replace without --allow-replace',
            'output': str(destination),
            'existingSha256': existing_sha,
            'existingBytes': existing_bytes,
            'sourceEqualsExisting': existing_sha == latest['sha256'],
        })
        return receipt

    previous = None
    if destination.exists():
        previous_sha, previous_bytes, _ = _sha256(destination)
        previous = {'sha256': previous_sha, 'bytes': previous_bytes}

    output_dir.mkdir(parents=True, exist_ok=True)
    payload = source.read_bytes()
    with destination.open('wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())

    written_sha, written_bytes, _ = _sha256(destination)
    receipt.update({
        'ok': written_sha == latest['sha256'] and written_bytes == latest['bytes'],
        'reason': None,
        'output': str(destination),
        'outputSha256': written_sha,
        'outputBytes': written_bytes,
        'replacedPrevious': previous,
        'sourceUntouched': True,
    })
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Read-only snapshot of the live .gil level save.')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, required=True,
                        help='project-relative or absolute directory inside the project root')
    parser.add_argument('--name', default='level.gil', help='destination file name inside --output')
    parser.add_argument('--stable-rounds', type=int, default=3)
    parser.add_argument('--stable-gap', type=float, default=2.0)
    parser.add_argument('--allow-replace', action='store_true')
    parser.add_argument('--receipt', type=Path, default=None,
                        help='receipt path; defaults to <output>/snapshot-receipt.json')
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding='utf-8')
    if args.stable_rounds < 2:
        print(json.dumps({'ok': False, 'reason': '--stable-rounds must be >= 2'}, ensure_ascii=False))
        return EXIT_USAGE

    try:
        receipt = snapshot(args.source, args.output, args.stable_rounds, args.stable_gap,
                           args.allow_replace, args.name)
    except Refused as exc:
        print(json.dumps({'ok': False, 'refused': str(exc)}, ensure_ascii=False, indent=2))
        return EXIT_REFUSED
    except OSError as exc:
        print(json.dumps({'ok': False, 'refused': f'{exc.__class__.__name__}: {exc}'},
                         ensure_ascii=False, indent=2))
        return EXIT_REFUSED

    receipt_path = args.receipt or (ensure_inside_project(args.output) / 'snapshot-receipt.json')
    if receipt['ok'] or receipt.get('output'):
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))

    if receipt['ok']:
        return EXIT_OK
    return EXIT_UNSTABLE if not receipt.get('stableRead') else EXIT_REFUSED


if __name__ == '__main__':
    raise SystemExit(main())
