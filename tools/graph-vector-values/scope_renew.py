"""Exclusive, journalled same-revision bridge renewal through the existing helper.

No helper startup, process restart, direct injection, revision bump or new-scope
call. A timeout is observed by calling renew again with EXACTLY the same binding.
The caller must already own and quiesce all work on this editor host.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RUNS = ROOT / '.runtime/editor-bridge/runs'
BASE = ROOT / '.runtime/graph-vector-values/renewals'
TRANSPORT = ROOT / 'tools/editor-bridge/elevated-request.py'


def _module(path):
    spec = importlib.util.spec_from_file_location('_scope_renew_' + uuid.uuid4().hex, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _module(HERE / 'release.py')


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('RENEW_JSON_NOT_OBJECT:' + str(path))
    return value


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(uuid.uuid4().hex + '.pending')
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('RENEW_CANONICAL_RUN_UUID_REQUIRED')
    return value


def _path(value, parent):
    path = Path(value)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    if path == parent or not path.is_relative_to(parent):
        raise ValueError('RENEW_PATH_OUTSIDE_ALLOWED_ROOT')
    return path


def _utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('RENEW_TIMEZONE_REQUIRED')
    return parsed


def _pins():
    return {str(p.relative_to(ROOT)): _hash(p) for p in
            (HERE / 'scope_renew.py', HERE / 'release.py', TRANSPORT)}


def _process_identity(pid):
    """Read-only limited-query Windows identity. No UI, injection or IPC."""
    if os.name != 'nt':
        raise ValueError('RENEW_WINDOWS_PROCESS_IDENTITY_REQUIRED')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        raise ValueError('RENEW_PROCESS_UNREADABLE:' + str(ctypes.get_last_error()))
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259:
            raise ValueError('RENEW_PROCESS_NOT_ACTIVE')
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            raise ValueError('RENEW_PROCESS_TIMES_UNREADABLE')
        image = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            raise ValueError('RENEW_PROCESS_EXE_UNREADABLE')
        ticks = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) + 504911232000000000
        return dict(pid=pid, startUtcTicks=str(ticks), expectedExe=image.value)
    finally:
        kernel.CloseHandle(handle)


def _check_process(binding, settings):
    actual = _process_identity(binding['targetPid'])
    if (actual['pid'] != binding['targetPid'] or
            actual['startUtcTicks'] != binding['targetStartUtcTicks'] or
            os.path.normcase(actual['expectedExe']) != os.path.normcase(settings['expectedExe'])):
        raise ValueError('RENEW_LIVE_PROCESS_IDENTITY_CHANGED')
    return actual


@contextmanager
def _host_lock(path):
    """Crash-released OS lock, shared by all callers of this production entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('RENEW_HOST_BUSY_NO_ACTION') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _scope(run_id):
    path = RUNS / _uuid(run_id)
    # Reject directory symlinks/junctions escaping the canonical run location.
    if path.resolve() != path:
        raise ValueError('RENEW_RUN_PATH_REDIRECTED')
    return path


def _binding(old_run, target_pid, target_start_ticks, queue_dir, game_session, owner_id, exclusive):
    if exclusive is not True:
        raise ValueError('RENEW_EXCLUSIVE_QUIESCED_OWNER_REQUIRED')
    if not isinstance(owner_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', owner_id):
        raise ValueError('RENEW_OWNER_ID_INVALID')
    if type(target_pid) is not int or target_pid <= 0:
        raise ValueError('RENEW_TARGET_PID_INVALID')
    if not isinstance(target_start_ticks, str) or not re.fullmatch(r'[1-9][0-9]{0,18}', target_start_ticks):
        raise ValueError('RENEW_START_TICKS_STRING_REQUIRED')
    queue = _path(queue_dir, ROOT / '.runtime/editor-bridge')
    session = _path(game_session, ROOT)
    if not queue.is_dir():
        raise ValueError('RENEW_EXISTING_QUEUE_REQUIRED')
    # This is the GAME identity document, not the editor bridge scope document.
    # Pin exact bytes; never rewrite it or infer undocumented game schema fields.
    if not _read(session):
        raise ValueError('RENEW_GAME_SESSION_EMPTY')
    return dict(oldRunId=_uuid(old_run), targetPid=target_pid, targetStartUtcTicks=target_start_ticks,
                queue=str(queue), session=str(session), sessionSha256=_hash(session),
                ownerId=owner_id, exclusiveQuiescedOwner=True)


def _old_identity(binding):
    path = _scope(binding['oldRunId'])
    identity = release._verify_run(path, allow_closed=True)
    settings = _read(path / 'bridge-settings.json')
    if (settings['pid'] != binding['targetPid'] or
            str(settings['startUtcTicks']) != binding['targetStartUtcTicks']):
        raise ValueError('RENEW_OLD_HOST_BINDING_MISMATCH')
    if not isinstance(settings.get('nonce'), str) or not settings['nonce']:
        raise ValueError('RENEW_OLD_NONCE_MISSING')
    return identity, settings


def _closed(path, pid):
    closure = path / 'lease-closed.json'
    if not closure.exists():
        return None
    try:
        value = _read(closure)
    except (OSError, ValueError):
        return None  # File publication may still be in progress; never load yet.
    if (value.get('pid') != pid or value.get('cleanupSucceeded') is not True or
            value.get('cleanupError') is not None or value.get('hostProcessTerminated') is not False):
        raise ValueError('RENEW_CLEANUP_FAILED_OR_UNKNOWN:' + path.name)
    return value


def _other_scopes(binding, allowed):
    for other in RUNS.iterdir():
        if not other.is_dir() or other.name in allowed:
            continue
        setting_file = other / 'bridge-settings.json'
        evidence = (other / 'loader.claim').exists() or (other / 'bridge-ready.json').exists()
        if not setting_file.exists():
            if evidence:
                raise ValueError('RENEW_OTHER_SCOPE_IDENTITY_UNKNOWN:' + other.name)
            continue
        try:
            settings = _read(setting_file)
        except (OSError, ValueError):
            if evidence:
                raise ValueError('RENEW_OTHER_SCOPE_IDENTITY_UNKNOWN:' + other.name)
            continue
        if (settings.get('pid') != binding['targetPid'] or
                str(settings.get('startUtcTicks')) != binding['targetStartUtcTicks']):
            continue
        ready_file = other / 'bridge-ready.json'
        if not ready_file.exists():
            if (other / 'loader.claim').exists():
                raise ValueError('RENEW_OTHER_LOAD_UNRESOLVED:' + other.name)
            continue
        ready = _read(ready_file)
        if ready.get('accepted') is False:
            continue
        if ready.get('accepted') is not True:
            raise ValueError('RENEW_OTHER_LOAD_UNRESOLVED:' + other.name)
        if _closed(other, binding['targetPid']) is None:
            raise ValueError('RENEW_OTHER_SCOPE_NOT_CLEAN:' + other.name)


def _queue_quiescent(binding, own_ids):
    """Do not close a scope while a known queued operation may still use it."""
    queue = Path(binding['queue'])
    paths = list(queue.glob('*.submission.json')) + list(queue.glob('*.request.json'))
    for path in paths:
        request_id = path.name.split('.')[0]
        if request_id in own_ids:
            continue
        payload = _read(path)
        affects_host = (payload.get('kind') == 'load' and payload.get('targetPid') == binding['targetPid'])
        affects_scope = payload.get('runId') == binding['oldRunId']
        if not affects_host and not affects_scope:
            continue
        response = queue / (request_id + '.response.json')
        if response.exists():
            answer = _read(response)
            if answer.get('outcomeUncertain') is not True and answer.get('pending') is not True:
                continue
        raise ValueError('RENEW_QUEUE_OPERATION_UNRESOLVED:' + request_id)


def _guard(journal):
    binding = journal['binding']
    if _pins() != journal['sourcePins']:
        raise ValueError('RENEW_SOURCE_CHANGED')
    if _hash(Path(binding['session'])) != binding['sessionSha256']:
        raise ValueError('RENEW_GAME_SESSION_CHANGED')
    identity, settings = _old_identity(binding)
    if identity['bridge'] != journal['oldIdentity']['bridge']:
        raise ValueError('RENEW_OLD_ASSEMBLY_CHANGED')
    path = _scope(binding['oldRunId'])
    if any(_hash(path / name) != digest for name, digest in journal['oldFiles'].items()):
        raise ValueError('RENEW_OLD_SCOPE_FILES_CHANGED')
    return settings


def _result(journal, code, *, pending=False, **extra):
    return dict(ok=False, code=code, pending=pending, outcomeUncertain=pending,
                retryAttempted=False, oldRunId=journal['binding']['oldRunId'],
                attemptId=journal['attemptId'], requestIds=journal['requestIds'],
                journal=str(BASE / journal['binding']['oldRunId'] / 'journal.json'),
                queue=journal['binding']['queue'], session=journal['binding']['session'],
                **extra)


def _exchange(journal, path, transport, phase, payload, deadline):
    """Write intent before one send. Recovery only polls, including pre-send crash."""
    entry = journal['requests'].get(phase)
    request_id = journal['requestIds'][phase]
    if entry is None:
        journal['requests'][phase] = dict(payload=payload, requestId=request_id,
                                         sendClaimedUtc=datetime.now(timezone.utc).isoformat())
        _write(path, journal)
        result = transport.send(payload, timeout=max(0, deadline - time.monotonic()), request_id=request_id)
    else:
        if entry['payload'] != payload or entry['requestId'] != request_id:
            raise ValueError('RENEW_REQUEST_BINDING_CHANGED')
        result = transport.poll_request(request_id, timeout=max(0, deadline - time.monotonic()))
    journal['requests'][phase]['lastReceipt'] = result
    _write(path.parent / 'observations' / (phase + '-' + uuid.uuid4().hex + '.json'),
           dict(observedUtc=datetime.now(timezone.utc).isoformat(), requestId=request_id, receipt=result))
    _write(path, journal)
    return result


def _fresh(journal, receipt):
    if (receipt.get('kind') != 'load' or receipt.get('accepted') is not True or
            receipt.get('readyFilePresent') is not True):
        raise ValueError('RENEW_LOAD_NOT_ACCEPTED')
    new_run = _uuid(receipt.get('runId'))
    binding = journal['binding']
    if new_run == binding['oldRunId']:
        raise ValueError('RENEW_LOAD_RETURNED_OLD_RUN')
    path = _scope(new_run)
    verified = release.verify_run(path)
    settings = _read(path / 'bridge-settings.json')
    ready = _read(path / 'bridge-ready.json')
    old_settings = _read(_scope(binding['oldRunId']) / 'bridge-settings.json')
    if (settings['pid'] != binding['targetPid'] or
            str(settings['startUtcTicks']) != binding['targetStartUtcTicks']):
        raise ValueError('RENEW_FRESH_HOST_CHANGED')
    if verified['bridge'] != journal['oldIdentity']['bridge']:
        raise ValueError('RENEW_FRESH_ASSEMBLY_CHANGED')
    if (not isinstance(settings.get('nonce'), str) or not settings['nonce'] or
            settings['nonce'] == old_settings['nonce'] or settings['pipeName'] == old_settings['pipeName']):
        raise ValueError('RENEW_SCOPE_IDENTITY_REUSED')
    if settings['expectedExe'] != old_settings['expectedExe']:
        raise ValueError('RENEW_FRESH_EXE_CHANGED')
    _check_process(binding, settings)
    _other_scopes(binding, {binding['oldRunId'], new_run})
    return dict(ok=True, code='RENEWED', freshRunId=new_run, runId=new_run, run=new_run,
                oldRunId=binding['oldRunId'], targetPid=binding['targetPid'],
                targetStartUtcTicks=binding['targetStartUtcTicks'], bridge=verified['bridge'],
                mvid=verified['bridge']['mvid'], sha256=verified['bridge']['sha256'],
                bridgePipe=ready['pipeName'], readyExpires=ready['settingsExpiresUtc'],
                runDirectory=str(path), readyPath=str(path / 'bridge-ready.json'),
                queue=binding['queue'], session=binding['session'],
                sessionSha256=binding['sessionSha256'], ownerId=binding['ownerId'],
                requestIds=journal['requestIds'], attemptId=journal['attemptId'],
                journal=str(BASE / binding['oldRunId'] / 'journal.json'),
                sameRevision=True, retryAttempted=False, hostProcessTerminated=False,
                runtimeVerified=False, persistentSaveVerified=False)


def _advance(journal, path, transport, deadline):
    binding = journal['binding']
    settings = _guard(journal)
    if journal.get('completed'):
        # Re-observing a completed attempt must not return a now-expired scope as usable.
        if (_closed(_scope(binding['oldRunId']), binding['targetPid']) is None or
                _hash(_scope(binding['oldRunId']) / 'lease-closed.json') != journal['closureSha256']):
            raise ValueError('RENEW_OLD_CLOSURE_CHANGED')
        return _fresh(journal, journal['requests']['load']['lastReceipt'])
    if 'load' in journal['requests']:
        receipt = _exchange(journal, path, transport, 'load',
                            dict(kind='load', targetPid=binding['targetPid']), deadline)
    else:
        _other_scopes(binding, {binding['oldRunId']})
        _queue_quiescent(binding, set(journal['requestIds'].values()))
        _check_process(binding, settings)
        closed = _closed(_scope(binding['oldRunId']), binding['targetPid'])
        if 'stop' in journal['requests'] or (closed is None and
                not (_scope(binding['oldRunId']) / 'lease-closed.json').exists() and
                _utc(settings['expiresUtc']) > datetime.now(timezone.utc)):
            # Even if closure arrived meanwhile, an unknown stop must be observed first.
            stopped = _exchange(journal, path, transport, 'stop',
                                dict(kind='call', runId=binding['oldRunId'], op='stop'), deadline)
            if stopped.get('pending') is True or stopped.get('outcomeUncertain') is True:
                return _result(journal, 'RENEW_STOP_OUTCOME_UNKNOWN', pending=True, receipt=stopped)
            if not (stopped.get('ok') is True and stopped.get('op') == 'stop' and
                    stopped.get('stopped') is True and stopped.get('cleanupComplete') is False and
                    stopped.get('hostProcessTerminated') is False):
                return _result(journal, 'RENEW_STOP_NOT_ACCEPTED', receipt=stopped)
        while closed is None:
            closed = _closed(_scope(binding['oldRunId']), binding['targetPid'])
            if closed is not None:
                break
            if time.monotonic() >= deadline:
                return _result(journal, 'RENEW_CLEANUP_PENDING', pending=True)
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        _guard(journal)
        _other_scopes(binding, {binding['oldRunId']})
        _queue_quiescent(binding, set(journal['requestIds'].values()))
        # Reuse the existing exact release/clean-closure gate, no duplicated load logic.
        journal['renewalStatus'] = release.renewal_status(_scope(binding['oldRunId']))
        journal['closureSha256'] = _hash(_scope(binding['oldRunId']) / 'lease-closed.json')
        _write(path, journal)
        _check_process(binding, settings)
        receipt = _exchange(journal, path, transport, 'load',
                            dict(kind='load', targetPid=binding['targetPid']), deadline)
    if receipt.get('pending') is True or receipt.get('outcomeUncertain') is True:
        return _result(journal, 'RENEW_LOAD_OUTCOME_UNKNOWN', pending=True, receipt=receipt)
    _guard(journal)
    if _closed(_scope(binding['oldRunId']), binding['targetPid']) is None:
        raise ValueError('RENEW_OLD_CLOSURE_DISAPPEARED')
    if _hash(_scope(binding['oldRunId']) / 'lease-closed.json') != journal['closureSha256']:
        raise ValueError('RENEW_OLD_CLOSURE_CHANGED')
    result = _fresh(journal, receipt)
    journal['completed'] = True
    journal['result'] = result
    _write(path, journal)
    return result


def renew(old_run: str, *, target_pid: int, target_start_ticks: str, queue_dir,
          game_session, owner_id: str, exclusive: bool, timeout: float = 45.0) -> dict:
    """One complete bounded attempt, or observation of its persisted request IDs.

    ``exclusive=True`` declares the caller already owns/quiesced this host. The
    local host lock serializes this API; it cannot lock unrelated author tools.
    Call again with the SAME arguments after pending; no stop/load is resubmitted.
    All file/queue paths are project-local. This API never changes game_session.
    """
    journal = None
    try:
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 55:
            raise ValueError('RENEW_TIMEOUT_RANGE_0_TO_55')
        binding = _binding(old_run, target_pid, target_start_ticks, queue_dir, game_session, owner_id, exclusive)
        deadline = time.monotonic() + timeout
        host = BASE / 'hosts' / (str(target_pid) + '-' + target_start_ticks)
        path = BASE / old_run / 'journal.json'
        with _host_lock(host.with_suffix('.lock')):
            head = _read(host.with_suffix('.json')) if host.with_suffix('.json').exists() else None
            if head and head['ownerId'] != owner_id:
                raise ValueError('RENEW_HOST_OWNED_BY_ANOTHER_OWNER')
            if head and head['oldRunId'] != old_run:
                previous = _read(BASE / _uuid(head['oldRunId']) / 'journal.json')
                if not previous.get('completed') or previous['result']['freshRunId'] != old_run:
                    raise ValueError('RENEW_HOST_HAS_OTHER_ATTEMPT')
                if any(previous['binding'][key] != binding[key] for key in ('queue', 'session', 'sessionSha256')):
                    raise ValueError('RENEW_CHAIN_BINDING_CHANGED')
            if path.exists():
                journal = _read(path)
                if journal['binding'] != binding:
                    raise ValueError('RENEW_BINDING_CHANGED')
            else:
                identity, settings = _old_identity(binding)
                _other_scopes(binding, {old_run})
                _queue_quiescent(binding, set())
                journal = dict(kind='bridge-scope-renewal-v1', attemptId=str(uuid.uuid4()),
                               binding=binding, sourcePins=_pins(), oldIdentity=identity,
                               oldFiles={name: _hash(_scope(old_run) / name) for name in
                                         ('bridge-settings.json', 'bridge-ready.json', 'frozen.json')},
                               requestIds=dict(stop=uuid.uuid4().hex, load=uuid.uuid4().hex), requests={},
                               completed=False, createdUtc=datetime.now(timezone.utc).isoformat())
                _write(path, journal)
            _write(host.with_suffix('.json'), dict(ownerId=owner_id, oldRunId=old_run, journal=str(path)))
            transport = _module(TRANSPORT)
            transport.QUEUE = Path(binding['queue'])
            result = _advance(journal, path, transport, deadline)
            _write(path.parent / 'last-result.json', result)
            return result
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = (_result(journal, str(error), blocked=True,
                          submittedRequestExists=bool(journal['requests']),
                          attemptCompleted=journal.get('completed', False),
                          previousFreshRunId=journal.get('result', {}).get('freshRunId')) if journal else
                  dict(ok=False, code=str(error), pending=False, outcomeUncertain=False, retryAttempted=False))
        if journal is not None and journal['requests'] and not journal.get('completed'):
            result['outcomeUncertain'] = True
        # Native rejection is never silently retried; retain unique IDs for inspection.
        if journal is not None:
            try:
                _write(BASE / journal['binding']['oldRunId'] / 'last-result.json', result)
            except OSError as persistence_error:
                result['receiptPersistenceError'] = str(persistence_error)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-run', required=True)
    parser.add_argument('--target-pid', required=True, type=int)
    parser.add_argument('--target-start-ticks', required=True)
    parser.add_argument('--queue-dir', required=True)
    parser.add_argument('--game-session', required=True)
    parser.add_argument('--owner-id', required=True)
    parser.add_argument('--exclusive', action='store_true', required=True,
                        help='Assert this owner holds the host and has quiesced all other dispatches')
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args(argv)
    result = renew(args.old_run, target_pid=args.target_pid, target_start_ticks=args.target_start_ticks,
                   queue_dir=args.queue_dir, game_session=args.game_session, owner_id=args.owner_id,
                   exclusive=args.exclusive, timeout=args.timeout)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get('ok') is True else (3 if result.get('pending') else 2)


if __name__ == '__main__':
    raise SystemExit(main())
