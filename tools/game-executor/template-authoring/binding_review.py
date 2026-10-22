"""Validate coordinator-issued binding reviews. Never create a review or run a probe."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

import build_binding_candidate as candidate

requests = candidate.requests
profiles = candidate.profiles
ROOT = candidate.ROOT
HERE = candidate.HERE
CLAIMS = ROOT / '.runtime/template-authoring/review-claims'
FIELDS = {'schemaVersion', 'kind', 'state', 'reviewedBy', 'reviewId', 'reviewedAtUtc', 'expiresUtc',
          'action', 'requestPath', 'requestSha256', 'levelId', 'session', 'baselineRun', 'baselineKind',
          'evidenceHashes', 'recovery', 'readonlyProfileSha256', 'runtimeProfilePath',
          'runtimeProfileSha256', 'sourceHashes'}


def source_paths():
    paths = [candidate.EXECUTOR / 'native' / name for name in candidate.NATIVE_FILES]
    paths += [HERE / name for name in candidate.TEMPLATE_FILES]
    paths += [HERE / name for name in ('request.py', 'build_binding_candidate.py', 'binding_review.py',
                                      'prepare_binding.py', 'receipt.py')]
    paths += [candidate.EXECUTOR / name for name in ('native_write_review.py', 'native_profiles.py',
        'build_readonly_profile.py', 'decode_context_snapshot.py', 'native_level_observation.py')]
    paths += [profiles.DEFAULT_PROFILE, requests.review_api.level_api.LEVEL_PROFILE]
    return {str(path.relative_to(ROOT)).replace('\\', '/'): path for path in paths}


def source_hashes():
    """Evidence collector only; the coordinator must decide whether to issue a review."""
    return {name: profiles.sha256(path) for name, path in source_paths().items()}


def utc_now():
    return datetime.now(timezone.utc)


def time_window(review, now=None, *, minimum_remaining=0):
    current = utc_now() if now is None else now
    try:
        start = datetime.fromisoformat(review['reviewedAtUtc'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(review['expiresUtc'].replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('REVIEW_TIME_INVALID') from None
    profiles.require(start.tzinfo is not None and end.tzinfo is not None and current.tzinfo is not None,
                     'REVIEW_TIMEZONE_REQUIRED')
    profiles.require(start <= current < end and 0 < (end - start).total_seconds() <= 3600 and
                     (end - current).total_seconds() >= minimum_remaining, 'REVIEW_EXPIRED_OR_WINDOW_TOO_SHORT')
    return end


def equal_files(first, second):
    """Compare recovery bytes, not merely a caller-provided digest."""
    with Path(first).open('rb') as a, Path(second).open('rb') as b:
        while True:
            left, right = a.read(1024 * 1024), b.read(1024 * 1024)
            if left != right:
                return False
            if not left:
                return True


def validate_review(review_path, *, now=None, minimum_remaining=0):
    path = requests.runtime_path(review_path)
    initial_hash = profiles.sha256(path)
    review = requests.read_json(path)
    requests.exact_fields(review, FIELDS, 'binding-review')
    profiles.require(type(review['schemaVersion']) is int and review['schemaVersion'] == 1 and
                     review['kind'] == 'template-binding-review-v1' and review['state'] == 'reviewed' and
                     review['reviewedBy'] == 'coordinator' and review['action'] in ('bind-shop', 'bind-bag'),
                     'BINDING_COORDINATOR_REVIEW_REQUIRED')
    try:
        identifier = uuid.UUID(review['reviewId'])
    except (ValueError, TypeError, AttributeError):
        raise ValueError('INVALID_REVIEW_ID') from None
    profiles.require(identifier.int != 0 and str(identifier) == review['reviewId'], 'INVALID_REVIEW_ID')
    time_window(review, now, minimum_remaining=minimum_remaining)
    profiles.require(review['readonlyProfileSha256'] == profiles.PROFILE_SHA256,
                     'REVIEW_READONLY_PROFILE_MISMATCH')
    profiles.load_profile()
    profiles.require(review['sourceHashes'] == source_hashes(), 'REVIEW_SOURCE_CHANGED_OR_INCOMPLETE')
    runtime_profile = requests.runtime_path(review['runtimeProfilePath'])
    profiles.require(profiles.sha256(runtime_profile) == review['runtimeProfileSha256'], 'REVIEW_RUNTIME_PROFILE_CHANGED')
    request_path = requests.runtime_path(review['requestPath'])
    request = requests.validate_request(requests.read_json(request_path))
    profiles.require(request_path.read_bytes() == requests.canonical_bytes(request) and
                     profiles.sha256(request_path) == review['requestSha256'], 'REVIEW_REQUEST_CHANGED')
    profiles.require(request['action'] == review['action'] and request['levelId'] == review['levelId'] and
                     request['session'] == review['session'], 'REVIEW_REQUEST_IDENTITY_MISMATCH')
    run = requests.runtime_path(review['baselineRun'])
    profiles.require(run.name == request['runId'] and review['baselineKind'] == 'readonly',
                     'REVIEW_BASELINE_IDENTITY_MISMATCH')
    hashes = requests._baseline_hashes(run, 'readonly')
    profiles.require(review['evidenceHashes'] == hashes, 'REVIEW_BASELINE_CHANGED_OR_INCOMPLETE')
    snapshot, baseline = requests.review_api.load_baseline(run, 'readonly', request['levelId'])
    for field in requests.SESSION_FIELDS:
        profiles.require(baseline['session'].get(field) == review['session'][field],
                         'REVIEW_BASELINE_SESSION_MISMATCH:' + field)
    recovery = review['recovery']
    requests.exact_fields(recovery, {'source', 'backup', 'sha256'}, 'recovery')
    official = (Path(os.environ['USERPROFILE']) / 'AppData/LocalLow/miHoYo/原神/BeyondLocal').resolve()
    profiles.require(Path(recovery['source']).is_absolute(), 'RECOVERY_SOURCE_ABSOLUTE_REQUIRED')
    target = Path(recovery['source']).resolve()
    relative = target.relative_to(official) if target.is_relative_to(official) else None
    level = str(request['levelId'])
    profiles.require(relative is not None and len(relative.parts) == 4 and relative.parts[0].isdigit() and
                     relative.parts[1:] == ('Beyond_Local_Save_Level', level, level + '.gil'),
                     'RECOVERY_FORMAL_LEVEL_PATH')
    backup = requests.runtime_path(recovery['backup'])
    profiles.require(equal_files(target, backup) and profiles.sha256(target) == recovery['sha256'] and
                     profiles.sha256(backup) == recovery['sha256'], 'RECOVERY_BYTES_OR_DIGEST_CHANGED')
    profiles.require(hashes == requests._baseline_hashes(run, 'readonly') and
                     initial_hash == profiles.sha256(path), 'REVIEW_INPUT_CHANGED_DURING_VALIDATION')
    return {'review': review, 'reviewPath': str(path), 'reviewSha256': initial_hash,
            'request': request, 'requestPath': str(request_path), 'baseline': snapshot,
            'baselineRun': str(run), 'targetGil': str(target), 'backup': str(backup),
            'runtimeProfilePath': str(runtime_profile)}


def claim_review(validated, run):
    """Consume the review for one compilation; a failed build never frees the claim."""
    claims = requests.runtime_path(CLAIMS)
    claims.mkdir(parents=True, exist_ok=True)
    path = claims / (validated['review']['reviewId'] + '.json')
    try:
        candidate.readonly.write_json(path, {
            'reviewSha256': validated['reviewSha256'], 'requestSha256': validated['review']['requestSha256'],
            'run': str(requests.runtime_path(run)), 'claim': 'single-binding-compilation-no-auto-retry',
        })
    except FileExistsError:
        raise ValueError('BINDING_REVIEW_ALREADY_CLAIMED') from None
    return path
