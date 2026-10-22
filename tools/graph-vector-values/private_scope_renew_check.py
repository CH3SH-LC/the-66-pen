"""Offline retained production-path check with a PRIVATE filesystem helper stub.

Uses real renew/release/send/poll/CLI/process identity and a real cross-process
lock. Native stop/load/ready/cleanup are explicitly fixture outputs. It never
addresses a real editor run or queue; no injection or desktop operations.
"""
from __future__ import annotations
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def module(path):
    spec = importlib.util.spec_from_file_location('private_production_renew', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    tool = module(HERE / 'scope_renew.py')
    if len(sys.argv) > 1 and sys.argv[1] == '--private-lock-child':
        lock, signal = Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
        allowed = ROOT / '.runtime/gvr'
        if not lock.is_relative_to(allowed) or not signal.is_relative_to(allowed):
            raise ValueError('PRIVATE_LOCK_PATH_REQUIRED')
        with tool._host_lock(lock):
            signal.write_text('held', encoding='utf-8')
            time.sleep(1.5)
        return 0
    # Nested real run/journal names must stay below Windows MAX_PATH.
    base = ROOT / '.runtime/gvr' / uuid.uuid4().hex[:8]
    base.mkdir(parents=True)
    source_set = tool.release.sources()
    for relative in source_set:
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    for relative in ('tools/graph-vector-values/scope_renew.py', 'tools/editor-bridge/elevated-request.py'):
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    # Real existing production candidate, no rebuild and no modification of its freeze.
    prior = ROOT / '.runtime/graph-vector-values/releases/30350ff13281ea35bed01d4c419e7d95cba44e94da068ca26b0bb137ec1cced7-9ec01d995090986d.json'
    manifest = json.loads(prior.read_text(encoding='utf-8-sig'))
    if manifest['sourceHashes'] != source_set:
        raise ValueError('PRIVATE_CHECK_PRIOR_FROZEN_SOURCES_CHANGED')
    for key in ('bridge', 'bootstrap'):
        original = Path(manifest[key]['path'])
        if tool._hash(original) != manifest[key]['sha256']:
            raise ValueError('PRIVATE_CHECK_FROZEN_BINARY_CHANGED')
        copied = base / 'binaries' / original.name
        copied.parent.mkdir(exist_ok=True)
        shutil.copyfile(original, copied)
        manifest[key]['path'] = str(copied)
    tool.ROOT = base
    tool.HERE = base / 'tools/graph-vector-values'
    tool.RUNS = base / '.runtime/editor-bridge/runs'
    tool.BASE = base / '.runtime/graph-vector-values/renewals'
    tool.TRANSPORT = base / 'tools/editor-bridge/elevated-request.py'
    tool.release.ROOT = base
    tool.release.RELEASES = base / 'releases'
    if tool.release.sources() != source_set:
        raise ValueError('PRIVATE_CHECK_SOURCE_COPY_MISMATCH')
    dump(tool.release.manifest_path(manifest['bridge']['sha256'], source_set), manifest)
    current = tool._process_identity(os.getpid())  # PRIVATE Python PID, never game/editor PID.
    queue = base / '.runtime/editor-bridge/private-stub-queue'
    queue.mkdir(parents=True)
    session = base / 'game-session-fixture.json'
    dump(session, dict(evidence='explicit private game identity fixture, no game connection'))
    identity = dict(manifest['bridge'], graphVector3Contract=1)
    scopes = {}

    def scope():
        run = str(uuid.uuid4())
        settings = dict(current, nonce=uuid.uuid4().hex + uuid.uuid4().hex,
                        pipeName='private-fixture-' + run,
                        expiresUtc=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat())
        path = tool.RUNS / run
        dump(path / 'bridge-settings.json', settings)
        dump(path / 'bridge-ready.json', dict(accepted=True, code=0, hostPid=current['pid'],
             settingsPid=current['pid'], hostStartUtcTicks=current['startUtcTicks'],
             settingsStartUtcTicks=current['startUtcTicks'], settingsExpectedExe=current['expectedExe'],
             pipeName=settings['pipeName'], settingsExpiresUtc=settings['expiresUtc'], bridgeAssembly=identity,
             fixtureOnly=True))
        dump(path / 'frozen.json', {k: manifest[k]['sha256'] for k in ('bridge', 'bootstrap')})
        scopes[run] = settings
        return run

    def close(run):
        dump(tool.RUNS / run / 'lease-closed.json', dict(pid=current['pid'], cleanupSucceeded=True,
             cleanupError=None, hostProcessTerminated=False, fixtureOnly=True))

    old = scope()
    kwargs = dict(target_pid=current['pid'], target_start_ticks=current['startUtcTicks'],
                  queue_dir=queue, game_session=session, owner_id='private-production-check', exclusive=True, timeout=5)
    lock = tool.BASE / 'hosts' / (str(current['pid']) + '-' + current['startUtcTicks'] + '.lock')
    signal = base / 'lock-held.txt'
    child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--private-lock-child', str(lock), str(signal)],
                             cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(100):
        if signal.exists() or child.poll() is not None:
            break
        time.sleep(.02)
    if not signal.exists():
        stdout, stderr = child.communicate(timeout=10)
        raise ValueError('PRIVATE_LOCK_CHILD_FAILED:' + stderr.decode(errors='replace'))
    blocked = tool.renew(old, **kwargs)
    assert blocked['code'] == 'RENEW_HOST_BUSY_NO_ACTION', blocked
    assert not list(queue.glob('*.request.json'))
    child_stdout, child_stderr = child.communicate(timeout=10)
    assert child.returncode == 0, child_stderr
    (base / 'lock-child.stdout').write_bytes(child_stdout)
    (base / 'lock-child.stderr').write_bytes(child_stderr)
    done = threading.Event()
    calls, failures = [], []

    def helper_stub():
        seen = set()
        try:
            while not done.is_set():
                for path in queue.glob('*.request.json'):
                    if path.name in seen:
                        continue
                    seen.add(path.name)
                    request = json.loads(path.read_text(encoding='utf-8-sig'))
                    calls.append(request)
                    if request == dict(kind='call', op='stop', runId=old):
                        close(old)
                        reply = dict(ok=True, op='stop', stopped=True, cleanupComplete=False,
                                     hostProcessTerminated=False)
                    elif request == dict(kind='load', targetPid=current['pid']):
                        reply = dict(kind='load', runId=scope(), readyFilePresent=True, accepted=True)
                    else:
                        raise AssertionError('Unexpected private helper request: ' + repr(request))
                    dump(path.with_name(path.name.replace('.request.json', '.response.json')), reply)
                done.wait(.01)
        except Exception as error:
            failures.append(repr(error))

    worker = threading.Thread(target=helper_stub)
    worker.start()
    try:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = tool.main(['--old-run', old, '--target-pid', str(current['pid']),
                              '--target-start-ticks', current['startUtcTicks'], '--queue-dir', str(queue),
                              '--game-session', str(session), '--owner-id', kwargs['owner_id'], '--exclusive', '--timeout', '5'])
        (base / 'cli.stdout.json').write_text(stdout.getvalue(), encoding='utf-8')
        fresh = json.loads(stdout.getvalue())
        assert code == 0 and fresh['ok'] is True, fresh
        assert [c['kind'] for c in calls] == ['call', 'load'], calls
        assert len(scopes) == 2
        assert fresh['queue'] == str(queue) and fresh['session'] == str(session)
        assert fresh['bridge']['sha256'] == manifest['bridge']['sha256']
        assert Path(fresh['runDirectory']) / 'bridge-ready.json' == Path(fresh['readyPath'])
        again = tool.renew(old, **kwargs)
        assert again == fresh and len(calls) == 2
        close(fresh['freshRunId'])
        stale = tool.renew(old, **kwargs)
        assert stale['ok'] is False and stale['code'] == 'VECTOR_RUN_EXPIRED_OR_CLOSED', stale
        assert stale['attemptCompleted'] is True and stale['previousFreshRunId'] == fresh['freshRunId']
        assert len(calls) == 2
        assert tool.release.sources() == source_set
        assert not failures, failures
    finally:
        done.set()
        worker.join(timeout=3)
    result = dict(ok=True, evidence='private-production-Python-path-with-explicit-native-helper-stub',
                  realProcessIdentity='current private Python PID only', crossProcessLockVerified=True,
                  actualSourceCopyAndReleaseVerifier=True, actualTransportSendPoll=True, actualCliParser=True,
                  singleStopCount=1, singleLoadCount=1, noAdditionalNewScope=True,
                  completedJournalRechecksLease=True, queueAndSessionPreserved=True,
                  nativeOutputs='fixture-only, not native renewal acceptance', gameConnected=False,
                  runtimeVerified=False, persistentSaveVerified=False, root=str(base),
                  sourceSetSha256=manifest['sourceSetSha256'], bridgeSha256=manifest['bridge']['sha256'],
                  fresh=fresh, stale=stale, lockRefusal=blocked)
    dump(base / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
