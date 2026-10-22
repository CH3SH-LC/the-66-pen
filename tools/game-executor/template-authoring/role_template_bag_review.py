"""Validate coordinator-issued binding reviews. Never create a review or run a probe."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import uuid

import build_role_template_bag_candidate as candidate

requests = candidate.requests
profiles = candidate.profiles
ROOT = candidate.ROOT
HERE = candidate.HERE
CLAIMS = ROOT / '.runtime/template-authoring/review-claims'
FIELDS = {'schemaVersion', 'kind', 'state', 'reviewedBy', 'reviewId', 'reviewedAtUtc', 'expiresUtc',
          'action', 'requestPath', 'requestSha256', 'levelId', 'session', 'baselineRun', 'baselineKind',
          'evidenceHashes', 'recovery', 'readonlyProfileSha256', 'runtimeProfilePath',
          'runtimeProfileSha256', 'sourceHashes'}


def validate_request(value):
    """Validate closed intent only; never label caller IDs as runtime verified."""
    requests.exact_fields(value, requests.REQUEST_FIELDS, "request")
    requests.require(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1
            and value["kind"] == "role-template-bag-request-v1", "REQUEST_VERSION")
    try:
        identifier = uuid.UUID(value["requestId"])
    except (ValueError, TypeError, AttributeError):
        raise requests.RequestError("REQUEST_ID_MUST_BE_NONZERO_CANONICAL_UUID") from None
    requests.require(identifier.int != 0 and str(identifier) == value["requestId"],
            "REQUEST_ID_MUST_BE_NONZERO_CANONICAL_UUID")
    requests.require(isinstance(value["runId"], str) and
            __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value["runId"]) is not None,
            "INVALID_BASELINE_RUN_ID")
    requests.uint(value["levelId"], "levelId")
    session = value["session"]
    requests.exact_fields(session, requests.SESSION_FIELDS, "session")
    requests.require(type(session["schemaVersion"]) is int and session["schemaVersion"] == 1,
            "SESSION_VERSION")
    for name in ("pid", "tid"):
        requests.uint(session[name], "session." + name)
    for name in ("window", "processCreation", "threadCreation"):
        requests.uint(session[name], "session." + name, bits=64)
    requests.require(session["windowClass"] == "UnityWndClass", "SESSION_WINDOW_CLASS")
    requests.require(isinstance(session["image"], str) and bool(session["image"]) and
            "\0" not in session["image"], "SESSION_IMAGE_REQUIRED")
    requests.require(value['action'] == 'bind-role-template-bag', 'ROLE_TEMPLATE_BAG_ACTION_ONLY')
    requests.require(value['levelId'] == 1073741845, 'ROLE_TEMPLATE_BAG_EXPLICIT_AUTHORIZED_LEVEL')
    expected = {'rolePrefabId': 1090519041, 'sceneEntityId': 1090519041, 'bagId': 1119879169}
    requests.exact_fields(value['parameters'], set(expected), 'role-template-bag-parameters')
    requests.require(all(type(value['parameters'][key]) is int and value['parameters'][key] == val
                         for key, val in expected.items()), 'ROLE_TEMPLATE_BAG_FIXED_IDS')
    return __import__('json').loads(requests.canonical_bytes(value))


def make_request(*, run_id, level_id, session, parameters, request_id=None):
    return validate_request({'schemaVersion': 1, 'kind': 'role-template-bag-request-v1',
        'requestId': request_id or str(uuid.uuid4()), 'runId': run_id, 'levelId': level_id,
        'session': session, 'action': 'bind-role-template-bag', 'parameters': parameters})


def source_paths():
    paths = [candidate.EXECUTOR / 'native' / name for name in candidate.NATIVE_FILES]
    paths += [HERE / name for name in candidate.TEMPLATE_FILES]
    paths += [HERE / name for name in ('request.py', 'build_role_template_bag_candidate.py', 'role_template_bag_review.py',
                                      'prepare_role_template_bag.py', 'accept_role_template_bag.py', 'receipt.py', 'binding_receipt.py', 'component_receipt.py', 'snapshot_abi.py')]
    paths += [candidate.EXECUTOR / name for name in ('native_write_review.py', 'native_profiles.py',
        'build_readonly_profile.py', 'decode_context_snapshot.py', 'native_level_observation.py')]
    paths += [profiles.DEFAULT_PROFILE, requests.review_api.level_api.LEVEL_PROFILE, candidate.BASE_RUNTIME_PROFILE]
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
                     review['kind'] == 'role-template-bag-review-v1' and review['state'] == 'reviewed' and
                     review['reviewedBy'] == 'coordinator' and review['action'] == 'bind-role-template-bag',
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
    request = validate_request(requests.read_json(request_path))
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
            'run': str(requests.runtime_path(run)), 'claim': 'single-role-template-bag-compilation-no-auto-retry',
        })
    except FileExistsError:
        raise ValueError('BINDING_REVIEW_ALREADY_CLAIMED') from None
    return path
