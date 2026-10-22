"""Coordinator evidence gate for already authorized level1843 template writes.

Collecting evidence does not authorize a write. Issuance requires the coordinator
to explicitly supply the source-set digest it has reviewed, then checks fresh
native baseline, real session, prepared request and byte-identical backup. This
is an internal evidence gate, not another user permission request.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch as card


def source_set(tool):
    card.require(tool in ('template-item', 'template-currency'), 'TEMPLATE_TOOL_REQUIRED')
    reviews = card.load_module(card.ROUTES[tool]['review'])
    sources = reviews.source_hashes()
    canonical = json.dumps(sources, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return reviews, sources, hashlib.sha256(canonical).hexdigest()


def issue(tool, request_path, baseline, target, backup, out, reviewed_source_sha):
    reviews, sources, source_sha = source_set(tool)
    card.require(reviewed_source_sha == source_sha, 'COORDINATOR_REVIEWED_SOURCE_SET_REQUIRED')
    requests, profiles = reviews.requests, reviews.profiles
    request_path = card.ordinary(request_path, card.ROOT / '.runtime')
    request = requests.validate_request(requests.read_json(request_path))
    expected_action = 'create-item' if tool == 'template-item' else 'create-currency'
    level = card.target_level(tool, request['levelId'])
    card.require(request['action'] == expected_action,
                 'ONLY_AUTHORIZED_TEST_LEVEL_AND_ACTION')
    card.require(request_path.read_bytes() == requests.canonical_bytes(request), 'CANONICAL_REQUEST_REQUIRED')
    baseline = card.ordinary(baseline, card.ROOT / '.runtime', directory=True)
    card.require(baseline.name == request['runId'], 'REQUEST_BASELINE_RUN_MISMATCH')
    before, prepared = requests.review_api.load_baseline(baseline, 'readonly', level)
    now = datetime.now(timezone.utc)
    finished = card.utc(card.read(baseline / 'exit.json')['finishedUtc'])
    card.require(0 <= (now - finished).total_seconds() < 900, 'FRESH_BASELINE_REQUIRED')
    for field in requests.SESSION_FIELDS:
        card.require(prepared['session'].get(field) == request['session'][field], 'REQUEST_BASELINE_SESSION_MISMATCH')
    profiles.validate_session(request['session'])
    # The ordinary builders also verify the prepared-not-dispatchable request,
    # exact disk image anchors, runtime profiles and baseline raw ABI.
    runtime = reviews.candidate.DEFAULT_RUNTIME_PROFILE
    reviews.candidate.load_inputs(request_path, baseline, runtime)
    target = card.ordinary(target)
    backup = card.ordinary(backup, card.ROOT / '.runtime')
    card.require(reviews.equal_files(target, backup), 'RECOVERY_BYTES_DIFFER')
    result = dict(schemaVersion=1, kind='template-item-review-v1' if tool == 'template-item' else 'template-currency-review-v1',
        state='reviewed', reviewedBy='coordinator', reviewId=str(uuid.uuid4()),
        reviewedAtUtc=now.isoformat(), expiresUtc=(now + timedelta(minutes=30)).isoformat(),
        action=expected_action, requestPath=str(request_path), requestSha256=card.digest(request_path),
        levelId=level, session=request['session'], baselineRun=str(baseline), baselineKind='readonly',
        evidenceHashes=requests._baseline_hashes(baseline, 'readonly'),
        recovery=dict(source=str(target), backup=str(backup), sha256=card.digest(target)),
        readonlyProfileSha256=profiles.PROFILE_SHA256, runtimeProfilePath=str(runtime.resolve()),
        runtimeProfileSha256=card.digest(runtime), sourceHashes=sources)
    if tool == 'template-item':
        service = reviews.candidate.DEFAULT_SERVICE_PROFILE.resolve()
        result['transitiveCurrencyProfile'] = dict(path=str(service), sha256=card.digest(service))
    out = Path(out).absolute()
    card.require(out.is_relative_to(card.ROOT / '.runtime') and out.name.endswith('.json'), 'REVIEW_OUTPUT_ROOT')
    out.parent.mkdir(parents=True, exist_ok=True)
    card.ordinary(out.parent, card.ROOT / '.runtime', directory=True)
    card.write(out, result)
    # The existing validators own the formal BeyondLocal target shape and exact
    # review schema. On failure preserve the written record as refused evidence;
    # callers may not dispatch a record that failed this validation.
    try:
        validated = reviews.validate_review(out, minimum_remaining=600 if tool == 'template-item' else 180)
    except Exception as error:
        card.write(out.with_suffix('.refused.json'), dict(ok=False, error=str(error), reviewSha256=card.digest(out)))
        raise
    card.require(source_set(tool)[2] == source_sha, 'SOURCE_CHANGED_DURING_REVIEW')
    return dict(ok=True, reviewPath=str(out), reviewSha256=validated['reviewSha256'],
                reviewedSourceSetSha256=source_sha, nativeCalled=False, levelId=level)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    collect = sub.add_parser('sources')
    collect.add_argument('--tool', choices=('template-item', 'template-currency'), required=True)
    create = sub.add_parser('issue')
    create.add_argument('--tool', choices=('template-item', 'template-currency'), required=True)
    for name in ('request', 'baseline', 'target-gil', 'backup', 'out'):
        create.add_argument('--' + name, type=Path, required=True)
    create.add_argument('--reviewed-source-set-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'sources':
            _, sources, digest = source_set(args.tool)
            result = dict(ok=True, reviewed=False, nativeCalled=False, sources=sources, sourceSetSha256=digest)
        else:
            result = issue(args.tool, args.request, args.baseline, args.target_gil,
                           args.backup, args.out, args.reviewed_source_set_sha256)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        result = dict(ok=False, error=str(error), nativeCalled=False)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
