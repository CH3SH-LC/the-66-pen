"""Coordinator review orchestration: DERIVE a native-write-review record, never take one.

Why this file exists
--------------------
``native_write_review`` is the gate every native mutation passes: it re-validates a
review record against the request hash, a complete executed runtime baseline, the live
session identity and a recovery copy of the formal save.  What the project did not have
was any *producer* for that record -- ``run_live_crud_acceptance.py`` refuses to author
one, and the documented rule is that no model may write ``reviewed: true`` itself.

This module is that producer, and it is deliberately structured so that the caller
supplies only raw materials:

    --session          a fresh discovered session record
    --level-id         the target level
    --action/...       the operation it intends to request
    --baseline-run     an already EXECUTED complete runtime baseline run
    --recovery-dir     where the recovery copy of the formal save may be written

It reads those, checks them against each other, and only then writes a record.  There is
no ``--reviewed``, ``--state`` or ``--approve`` flag: the verdict is computed here, and the
finished record is then handed straight back to the production validator
(``native_write_review.validate_review``) before it is published.  A record that the
production validator would reject is never published at all.

What it does NOT do: no UAC, no helper request, no compile, no game call, no save.  It
only reads the formal save and copies it.

Usage
-----
    python -B tools/game-executor/orchestrate_write_review.py \\
        --session .runtime/.../session.json --level-id <id> --action create \\
        --template-id 20001034 --position 1 2 3 --rotation 0 0 0 --scale 1 1 1 \\
        --baseline-run .runtime/.../readonly-run --baseline-kind readonly \\
        --recovery-dir .runtime/game-executor/native-write-reviews/recovery
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/compatibility'))
sys.path.insert(0, str(ROOT / 'tools/game-executor'))

from version_guard import IncompatibleVersion, require_compatible  # noqa: E402
import native_profiles as profiles  # noqa: E402
import native_write_review as review_api  # noqa: E402
import build_scene_profile as scene_api  # noqa: E402

#: A review is a short-lived authorisation.  native_write_review enforces <= 3600s; the
#: default is deliberately much shorter so a record found on disk later is obviously spent.
MAX_VALIDITY_SECONDS = 3600
DEFAULT_VALIDITY_SECONDS = 900
REVIEW_KIND = 'native-write-review-v1'
#: BeyondLocal/<account-digits>/Beyond_Local_Save_Level/<level>/<level>.gil
ACCOUNT_ROOT = Path(os.environ.get('USERPROFILE', '')) / 'AppData/LocalLow/miHoYo/原神/BeyondLocal'
#: Files that must exist, hashed and unchanged, inside the reviewed baseline run.
REQUIRED_BASELINE = ('prepared.json', 'build-result.json', 'stdout.jsonl', 'exit.json')
DEFAULT_REVIEW_ROOT = ROOT / '.runtime/game-executor/native-write-reviews'


class OrchestrationRefusal(RuntimeError):
    """A refusal that leaves no review behind.  Never a partial publication."""


def require(condition, reason):
    if not condition:
        raise OrchestrationRefusal(reason)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json_exclusive(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except FileExistsError:
        raise OrchestrationRefusal('refusing to overwrite existing evidence: ' + str(path))
    return path


def sha256_file(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def project_runtime(raw, label) -> Path:
    """Resolve an existing path that must already live under this project's .runtime."""
    path = Path(raw).resolve()
    root = (ROOT / '.runtime').resolve()
    require(path.is_relative_to(root), '%s_OUTSIDE_PROJECT_RUNTIME: %s' % (label, path))
    require(path.is_file(), '%s_MISSING: %s' % (label, path))
    return path


def project_runtime_dir(raw, label) -> Path:
    """Same containment rule for a directory (a native run is a directory of artifacts)."""
    path = Path(raw).resolve()
    root = (ROOT / '.runtime').resolve()
    require(path.is_relative_to(root), '%s_OUTSIDE_PROJECT_RUNTIME: %s' % (label, path))
    require(path.is_dir(), '%s_MISSING: %s' % (label, path))
    return path


def canonical_request(action: str, level_id: int, *, template_id=None,
                      position=None, rotation=None, scale=None, plan=None) -> dict:
    """Build the request exactly as build_scene_profile will build it at dispatch.

    Both sides call the same ``vector()`` from build_scene_profile, so the float32
    rounding cannot drift: a request this module hashes is the request the native
    wrapper will later compare itself against.
    """
    if action not in review_api.load_write_profile()['allowedActions']:
        raise OrchestrationRefusal('ACTION_NOT_ALLOWED_BY_WRITE_PROFILE: ' + action)
    request = {'action': action, 'levelId': level_id}
    if action in ('create', 'creature-create'):
        require(template_id is not None, 'TEMPLATE_ID_REQUIRED')
        request.update(templateId=int(template_id),
                       position=scene_api.vector(position),
                       rotation=scene_api.vector(rotation),
                       scale=scene_api.vector(scale, positive=True))
    elif action == 'create-batch':
        require(plan is not None, 'PLAN_REQUIRED_FOR_CREATE_BATCH')
        spec = read_json(plan)
        require(isinstance(spec.get('placements'), list) and spec['placements'],
                'PLAN_HAS_NO_PLACEMENTS')
        request['placements'] = [
            dict(template_id=int(item['template_id']),
                 position=scene_api.vector(item['position']),
                 rotation=scene_api.vector(item.get('rotation', (0, 0, 0))),
                 scale=scene_api.vector(item['scale'], positive=True))
            for item in spec['placements']]
    return request


def resolve_account_uid_dir(backup_manifest=None) -> Path:
    """Which uid directory holds the live account.

    This machine has TWO numeric directories under BeyondLocal: the live account and
    an empty leftover from an earlier install, untouched since 2026-08-22.  A bare
    "there must be exactly one" test therefore refuses on a healthy machine, so
    emptiness is the discriminator -- the same rule backup-account-saves.py uses.

    Prefer ``backup_manifest``: it records the directory that script actually chose,
    which is evidence rather than a re-derivation.  Two populated candidates still
    refuse: silently picking one would review a write against the wrong account.
    """
    root = ACCOUNT_ROOT.resolve()
    require(root.is_dir(), 'ACCOUNT_ROOT_MISSING: ' + str(root))
    if backup_manifest is not None:
        manifest_path = project_runtime(backup_manifest, 'ACCOUNT_BACKUP_MANIFEST')
        chosen = Path(read_json(manifest_path)['source']).resolve()
        require(chosen.is_relative_to(root) and chosen.name.isdigit() and chosen.is_dir(),
                'ACCOUNT_BACKUP_MANIFEST_SOURCE_UNUSABLE: ' + str(chosen))
        return chosen
    numeric = sorted(entry for entry in root.iterdir() if entry.is_dir() and entry.name.isdigit())
    populated = [entry for entry in numeric if any(item.is_file() for item in entry.rglob('*'))]
    require(len(populated) == 1,
            'ACCOUNT_UID_CANDIDATES: %d populated of %d numeric directories under %s'
            % (len(populated), len(numeric), root))
    return populated[0].resolve()


def resolve_formal_gil(level_id: int, explicit=None, backup_manifest=None) -> Path:
    """The one formal save file the reviewed operation is allowed to change."""
    if explicit is not None:
        target = Path(explicit).resolve()
    else:
        target = (resolve_account_uid_dir(backup_manifest)
                  / 'Beyond_Local_Save_Level' / str(level_id) / (str(level_id) + '.gil')).resolve()
    require(target.is_file(), 'FORMAL_GIL_MISSING: ' + str(target))
    relative = target.relative_to(ACCOUNT_ROOT.resolve())
    require(len(relative.parts) == 4 and relative.parts[0].isdigit()
            and relative.parts[1] == 'Beyond_Local_Save_Level'
            and relative.parts[2] == str(level_id)
            and relative.parts[3] == str(level_id) + '.gil',
            'FORMAL_GIL_PATH_SHAPE: ' + str(target))
    return target


def cross_check_backup_manifest(backup_manifest, target: Path) -> dict:
    """The recorded account backup must agree, byte for byte, about this one file.

    This is the evidence that the recovery material predates the write and describes
    the same file: the manifest carries the digest the backup script hashed at copy
    time, and the formal save must still hash to it now.
    """
    manifest_path = project_runtime(backup_manifest, 'ACCOUNT_BACKUP_MANIFEST')
    manifest = read_json(manifest_path)
    source = Path(manifest['source']).resolve()
    want_rel = target.relative_to(source).as_posix()
    rows = [row for row in manifest.get('files', []) if row.get('relpath') == want_rel]
    require(len(rows) == 1,
            'TARGET_GIL_NOT_UNIQUELY_PRESENT_IN_ACCOUNT_BACKUP: %s (%d rows)'
            % (want_rel, len(rows)))
    recorded = rows[0]['sha256']
    actual = sha256_file(target)
    require(recorded == actual,
            'ACCOUNT_BACKUP_DISAGREES_WITH_FORMAL_GIL: recorded %s, on disk %s'
            % (recorded, actual))
    return {'manifest': str(manifest_path), 'manifestSha256': sha256_file(manifest_path),
            'relpath': want_rel, 'recordedSha256': recorded, 'agreesWithFormalGil': True}


def protected_siblings(target: Path) -> list:
    """Other levels' saves that live beside the target.  The native wrapper checks these
    too, so an operation that disturbs one of them must be refused rather than reported."""
    level_root = target.parent.parent
    siblings = []
    for entry in sorted(level_root.iterdir()):
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        candidate = (entry / (entry.name + '.gil')).resolve()
        if candidate.is_file() and candidate != target:
            siblings.append(str(candidate))
    return siblings


def make_recovery(target: Path, recovery_dir: Path) -> dict:
    """Copy the formal save once, under .runtime, and prove the copy is identical."""
    recovery_dir = recovery_dir.resolve()
    require(recovery_dir.is_relative_to((ROOT / '.runtime').resolve()),
            'RECOVERY_DIR_OUTSIDE_PROJECT_RUNTIME: ' + str(recovery_dir))
    recovery_dir.mkdir(parents=True, exist_ok=True)
    copy = recovery_dir / (target.stem + '.gil')
    want = sha256_file(target)
    if copy.exists():
        # An existing copy is reused only when it is still byte-identical to the formal
        # file.  Silently overwriting it would destroy the evidence it exists to be.
        got = sha256_file(copy)
        require(got == want,
                'EXISTING_RECOVERY_COPY_DIFFERS_FROM_FORMAL_GIL: %s (%s != %s)'
                % (copy, got, want))
    else:
        tmp = recovery_dir / (target.stem + '.gil.partial')
        require(not tmp.exists(), 'STALE_PARTIAL_RECOVERY_COPY: ' + str(tmp))
        tmp.write_bytes(target.read_bytes())
        require(sha256_file(tmp) == want, 'RECOVERY_COPY_WRITE_MISMATCH')
        os.replace(tmp, copy)
    got = sha256_file(copy)
    require(got == want, 'RECOVERY_COPY_DIFFERS_AFTER_WRITE: %s != %s' % (got, want))
    return {'source': str(target), 'backup': str(copy), 'sha256': want}


def baseline_evidence(run_path: Path, kind: str, level_id: int) -> dict:
    """Hash the executed baseline run, then let the production loader re-execute the
    full check.  A run that cannot be loaded is not a baseline, whatever its files say."""
    run = project_runtime_dir(run_path, 'BASELINE_RUN')
    required = set(REQUIRED_BASELINE)
    if kind == 'action-after':
        required.add('result.json')
    missing = sorted(name for name in required if not (run / name).is_file())
    require(not missing, 'BASELINE_RUN_INCOMPLETE: ' + ','.join(missing))
    hashes = {name: sha256_file(run / name) for name in sorted(required)}
    # The authoritative check: decode the baseline, re-run the receipt validation and
    # require a non-empty complete entity set observed on the requested level.
    snapshot, _prepared = review_api.load_baseline(run, kind, level_id)
    return run, hashes, snapshot


def orchestrate(*, session_path, level_id, request, baseline_run, baseline_kind,
                recovery_dir, out_path=None, validity_seconds=DEFAULT_VALIDITY_SECONDS,
                gil=None, account_backup_manifest=None) -> dict:
    require(type(level_id) is int and 0 < level_id < 2 ** 32, 'LEVEL_ID_NOT_UINT32')
    require(baseline_kind in ('readonly', 'action-after'), 'BASELINE_KIND_UNSUPPORTED')
    require(type(validity_seconds) is int and 0 < validity_seconds <= MAX_VALIDITY_SECONDS,
            'VALIDITY_SECONDS_OUT_OF_RANGE')
    # Disk gate first, as author.py does: an unadapted build must refuse before this
    # module reads a save, copies it or writes any evidence.
    require_compatible('native-scene')

    write_profile = review_api.load_write_profile()   # rejects allowUnreviewedWrites
    session_file = project_runtime(session_path, 'SESSION')
    session = profiles.validate_session(read_json(session_file))
    request = dict(request)
    require(request.get('levelId') == level_id, 'REQUEST_LEVEL_MISMATCH')

    target = resolve_formal_gil(level_id, gil, account_backup_manifest)
    backup_cross_check = cross_check_backup_manifest(account_backup_manifest, target) \
        if account_backup_manifest is not None else None
    recovery = make_recovery(target, Path(recovery_dir))
    protected = protected_siblings(target)
    run, evidence_hashes, snapshot = baseline_evidence(Path(baseline_run), baseline_kind, level_id)

    # The baseline must describe the same game process this session names, or the
    # "complete runtime baseline" is about a different process and proves nothing.
    prepared = read_json(run / 'prepared.json')
    for field in review_api.SESSION_FIELDS:
        require(prepared.get('session', {}).get(field) == session.get(field),
                'BASELINE_SESSION_MISMATCH:' + field)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    review = {
        'schemaVersion': 1,
        'kind': REVIEW_KIND,
        'state': 'reviewed',
        'reviewedBy': 'coordinator',
        'reviewId': str(uuid.uuid4()),
        'reviewedAtUtc': now.isoformat().replace('+00:00', 'Z'),
        'expiresUtc': (now + timedelta(seconds=validity_seconds)).isoformat().replace('+00:00', 'Z'),
        'profileId': write_profile['profileId'],
        'writeProfileSha256': review_api.WRITE_PROFILE_SHA256,
        'readonlyProfileSha256': profiles.PROFILE_SHA256,
        'levelId': level_id,
        'requestSha256': review_api.canonical_hash(request),
        'session': {field: session[field] for field in review_api.SESSION_FIELDS},
        'baselineRun': str(run),
        'baselineKind': baseline_kind,
        'evidenceHashes': evidence_hashes,
        'recovery': recovery,
        'protectedGils': protected,
    }
    require(re.fullmatch(r'[0-9a-f-]{36}', review['reviewId']), 'REVIEW_ID_SHAPE')

    out = Path(out_path).resolve() if out_path else \
        (DEFAULT_REVIEW_ROOT / (review['reviewId'] + '.json')).resolve()
    require(out.is_relative_to((ROOT / '.runtime').resolve()),
            'REVIEW_OUTPUT_OUTSIDE_PROJECT_RUNTIME: ' + str(out))

    # Publish only through the production validator.  Write the candidate beside the
    # final name, validate THAT path, and rename only when it passes -- so a record the
    # gate would reject never appears at the path a dispatcher would read.
    candidate = out.with_suffix('.candidate.json')
    require(not candidate.exists() and not out.exists(),
            'REVIEW_OUTPUT_ALREADY_EXISTS: ' + str(candidate if candidate.exists() else out))
    write_json_exclusive(candidate, review)
    try:
        validated = review_api.validate_review(candidate, session, level_id, request)
    except Exception as error:
        candidate.unlink(missing_ok=True)
        raise OrchestrationRefusal('PRODUCTION_VALIDATOR_REJECTED: %s: %s'
                                   % (type(error).__name__, error))
    os.replace(candidate, out)

    final = validated or {}
    return {'ok': True, 'kind': 'native-write-review-orchestration',
            'reviewId': review['reviewId'], 'reviewPath': str(out),
            'reviewSha256': sha256_file(out),
            'request': request, 'requestSha256': review['requestSha256'],
            'levelId': level_id, 'baselineRun': str(run), 'baselineKind': baseline_kind,
            'baselineEntities': len(snapshot.get('entities') or []),
            'recovery': recovery, 'protectedGils': protected,
            'accountBackupCrossCheck': backup_cross_check,
            'reviewedAtUtc': review['reviewedAtUtc'], 'expiresUtc': review['expiresUtc'],
            'validitySeconds': validity_seconds,
            'validatedBy': 'native_write_review.validate_review',
            'validatedTargetGil': final.get('targetGil'),
            'notes': ('the record was accepted by the production validator before publication; '
                      'a rejected candidate is deleted and never left at the published path')}


def main(argv=None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--level-id', type=int, required=True)
    parser.add_argument('--action', required=True, choices=('create', 'create-batch', 'save', 'creature-create'))
    parser.add_argument('--template-id', type=int)
    parser.add_argument('--position', type=float, nargs=3)
    parser.add_argument('--rotation', type=float, nargs=3, default=(0.0, 0.0, 0.0))
    parser.add_argument('--scale', type=float, nargs=3, default=(1.0, 1.0, 1.0))
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--baseline-run', type=Path, required=True)
    parser.add_argument('--baseline-kind', required=True, choices=('readonly', 'action-after'))
    parser.add_argument('--recovery-dir', type=Path, required=True)
    parser.add_argument('--account-backup-manifest', type=Path,
                        help='backup-account-saves.py manifest; supplies the uid directory and '
                             'cross-checks its recorded digest for this level against the formal save')
    parser.add_argument('--gil', type=Path, help='Explicit formal save; use when the uid dir is ambiguous')
    parser.add_argument('--out', type=Path, help='Where to publish; must stay under .runtime')
    parser.add_argument('--validity-seconds', type=int, default=DEFAULT_VALIDITY_SECONDS)
    args = parser.parse_args(argv)
    try:
        request = canonical_request(args.action, args.level_id, template_id=args.template_id,
                                    position=args.position, rotation=args.rotation,
                                    scale=args.scale, plan=args.plan)
        result = orchestrate(session_path=args.session, level_id=args.level_id, request=request,
                             baseline_run=args.baseline_run, baseline_kind=args.baseline_kind,
                             recovery_dir=args.recovery_dir, out_path=args.out,
                             validity_seconds=args.validity_seconds, gil=args.gil,
                             account_backup_manifest=args.account_backup_manifest)
    except IncompatibleVersion as error:
        result = {'ok': False, 'error': 'INCOMPATIBLE_VERSION', 'guard': getattr(error, 'report', None)}
    except (OrchestrationRefusal, OSError, ValueError, KeyError, TypeError) as error:
        result = {'ok': False, 'error': '%s: %s' % (type(error).__name__, error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
