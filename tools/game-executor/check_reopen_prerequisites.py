"""Read-only reopen preflight, with raw evidence and explicit blocked stages.

live --queue-dir QUEUE --session SESSION [--output-root DIR]
analyze --run RUN [--output-root DIR]
poll --work WORK --request-id ID

Only 'live' submits an inspect. No command reopens, initializes, saves or retries
the game. A ready preflight is not a completed reopen acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import uuid

import build_readonly_profile as readonly
import native_profiles as profiles
import native_reopen_baseline as baseline
import native_scheduler_coroutines as scheduler
import native_write_review as reviews

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / '.runtime/verification/reopen-preflight'


def put(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def work_dir(root):
    root = reviews.project_evidence(root)
    root.mkdir(parents=True, exist_ok=True)
    work = root / uuid.uuid4().hex
    work.mkdir()
    return work


def client_module():
    path = ROOT / 'tools/editor-bridge/elevated-request.py'
    spec = importlib.util.spec_from_file_location('_reopen_preflight_queue', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def analyze_run(run_path):
    """Decode original receipt; a stale historical run can diagnose, never authorize."""
    run = reviews.project_evidence(run_path)
    prepared = reviews.read_json(run / 'prepared.json')
    built = reviews.read_json(run / 'build-result.json')
    exit_record = reviews.read_json(run / 'exit.json')
    hashes = {n: profiles.sha256(run / n) for n in
              ('prepared.json', 'build-result.json', 'stdout.jsonl', 'exit.json')}
    record, encoding = readonly.load_decoder().read_probe(run / 'stdout.jsonl')
    context = readonly.load_decoder().decode_snapshot(record)
    diagnostic = scheduler.diagnose_prerequisites(record, context)
    bindings_error = None
    try:
        baseline.validate_file_bindings(run, prepared, built)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        bindings_error = str(exc)
    eligibility_error = None
    eligible = False
    # load() also checks age, source pins, raw complete observations, guards and
    # unsaved changes. Add a current OS identity check before reporting ready.
    try:
        profiles.validate_session(prepared['session'])
        baseline.load(run, prepared['session'])
        eligible = bindings_error is None
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        eligibility_error = str(exc)
    native_read = (exit_record.get('executed') is True and
                   record.get('scope') == 'READ_ONLY_CONTEXT_RECEIPT' and
                   record.get('selfTestOnly') is False and
                   record.get('pid') == prepared['session']['pid'] and
                   record.get('tid') == prepared['session']['tid'])
    cleanup = (record.get('unhooked') is True and
               record.get('activeCallbacks') == 0 and
               record.get('callbackCount') == 1 and
               record.get('transportOk') is True)
    pending_path = ROOT / '.runtime/editor-bridge/native-dispatch/native-active.json'
    pending = pending_path.exists()
    eligible = eligible and native_read and cleanup and not pending
    return dict(schemaVersion=1, scope='reopen-prerequisites-only',
                status='ready' if eligible else 'blocked',
                preflightPassed=eligible, nativeReadObserved=native_read,
                hookCleanupVerified=cleanup, pendingReopenOwnership=pending,
                currentEligibilityError=eligibility_error,
                currentSourceBindingError=bindings_error, diagnostic=diagnostic,
                rawEvidence=dict(run=str(run), hashes=hashes, encoding=encoding),
                entityCount=len(context.get('entities', [])),
                levelObservation=context.get('levelObservation'),
                checkedUtc=datetime.now(timezone.utc).isoformat(),
                mutationAttempted=False, reopenInvoked=False, reopenVerified=False,
                retryAttempted=False,
                limits='Ready is a fresh preflight only. Blocked/skipped fields are not measured null values.')


def response_report(reply):
    if not isinstance(reply, dict):
        raise ValueError('PREFLIGHT_RESPONSE_NOT_OBJECT')
    if reply.get('pending') is True:
        return dict(status='pending', requestId=reply.get('requestId'),
                    reopenInvoked=False, reopenVerified=False, retryAttempted=False,
                    nextAction='poll the same request; do not run live again')
    if reply.get('run'):
        report = analyze_run(reply['run'])
        report['helperBusinessOk'] = reply.get('ok') is True
        report['observedDuringReopenRequestId'] = reply.get('observedDuringReopenRequestId')
        report['preflightPassed'] = (report['preflightPassed'] and
                                     report['helperBusinessOk'] and
                                     'observedDuringReopenRequestId' not in reply and
                                     reply.get('action') == 'inspect' and
                                     reply.get('levelId') == baseline.LEVEL and
                                     reply.get('cleanupVerified') is True and
                                     reply.get('outcomeUncertain') is not True)
        report['status'] = 'ready' if report['preflightPassed'] else 'blocked'
        return report
    return dict(status='unavailable', helperResponse=reply,
                preflightPassed=False, reopenInvoked=False, reopenVerified=False,
                retryAttempted=False)


def live(args):
    work = work_dir(args.output_root)
    session = reviews.project_evidence(args.session)
    queue = Path(args.queue_dir).resolve()
    if not queue.is_relative_to(ROOT / '.runtime/editor-bridge'):
        raise ValueError('PREFLIGHT_QUEUE_OUTSIDE_PROJECT')
    payload = dict(kind='native-scene', action='inspect', sessionPath=str(session),
                   levelId=baseline.LEVEL, reopenPrerequisites=True)
    put(work / 'intent.json', dict(queueDir=str(queue), sessionPath=str(session),
                                request=payload, createdUtc=datetime.now(timezone.utc).isoformat()))
    client = client_module()
    try:
        reply = client.send_native_scene(payload, timeout=120, queue_dir=queue)
        put(work / 'response.json', reply)
        report = response_report(reply)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        report = dict(status='unavailable', error=str(exc), retryAttempted=False,
                      reopenInvoked=False, reopenVerified=False,
                      nextAction='inspect preserved queue evidence; do not assume no read was submitted')
    put(work / 'report.json', report)
    return dict(report, work=str(work))


def analyze(args):
    report = analyze_run(args.run)
    work = work_dir(args.output_root)
    put(work / 'report.json', report)
    return dict(report, work=str(work))


def poll(args):
    work = reviews.project_evidence(args.work)
    intent = reviews.read_json(work / 'intent.json')
    original = reviews.read_json(work / 'response.json')
    if original.get('pending') is not True or original.get('requestId') != args.request_id:
        raise ValueError('PREFLIGHT_ORIGINAL_PENDING_REQUEST_REQUIRED')
    client = client_module()
    client.QUEUE = Path(intent['queueDir'])
    reply = client.poll_request(args.request_id, timeout=30)
    tag = uuid.uuid4().hex
    put(work / ('poll-' + tag + '.json'), reply)
    report = response_report(reply)
    put(work / ('report-' + tag + '.json'), report)
    return dict(report, work=str(work))


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('live')
    p.add_argument('--queue-dir', required=True, type=Path)
    p.add_argument('--session', required=True, type=Path)
    p.add_argument('--output-root', type=Path, default=OUTPUT)
    p = commands.add_parser('analyze')
    p.add_argument('--run', required=True, type=Path)
    p.add_argument('--output-root', type=Path, default=OUTPUT)
    p = commands.add_parser('poll')
    p.add_argument('--work', required=True, type=Path)
    p.add_argument('--request-id', required=True)
    args = parser.parse_args()
    try:
        result = {'live': live, 'analyze': analyze, 'poll': poll}[args.command](args)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        result = dict(status='unavailable', error=str(exc), reopenVerified=False,
                      retryAttempted=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('preflightPassed') is True else 2


if __name__ == '__main__':
    raise SystemExit(main())
