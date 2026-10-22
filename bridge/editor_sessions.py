"""Fixed launcher wrapper for the project editor-bridge session scripts.

Boundary: fixed absolute system powershell, fixed script paths and a fixed
action enum only. No shells or string commands, no arbitrary paths or actions,
no scope/nonce output, no automatic retries, no process termination, no quota
or global configuration edits. One request directory per requestId is the
idempotency guard: identical parameters never spawn twice, different
parameters are rejected, and a crash between mkdir and spawn yields unknown
instead of a retry. Directory isolation is not an operating-system sandbox.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
START_SESSION = PROJECT_ROOT / 'tools/editor-bridge/start-session.ps1'
SESSION_STATUS = PROJECT_ROOT / 'tools/editor-bridge/session-status.ps1'
REQUESTS_DIR = PROJECT_ROOT / '.runtime/editor-bridge/requests'
RUNS_DIR = PROJECT_ROOT / '.runtime/editor-bridge/runs'
ACTIONS = ('observe', 'inspect-sync', 'backup-course', 'restore-route')
SESSION_STATUS_KEYS = ('runId', 'action', 'targetPid', 'status', 'helperAlive', 'cleanupSucceeded',
                       'error', 'graphs', 'result', 'notice')
CREATE_NO_WINDOW = 0x08000000
MAX_PID = 2147483647
STATUS_TIMEOUT_SECONDS = 15

_live: dict[str, subprocess.Popen] = {}


class SessionError(Exception):
    """Native failure surfaced to the caller; never a fake success."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {'code': self.code, 'message': self.message}


def _validate(request_id: Any, target_pid: Any, action: Any) -> tuple[str, int, str]:
    if not isinstance(request_id, str):
        raise SessionError('REQUEST_ID_INVALID', 'requestId must be a UUID string')
    try:
        parsed = uuid.UUID(request_id)
    except ValueError:
        raise SessionError('REQUEST_ID_INVALID', 'requestId must be a UUID string') from None
    if isinstance(target_pid, bool) or not isinstance(target_pid, int) or not 0 < target_pid <= MAX_PID:
        raise SessionError('TARGET_PID_INVALID', f'targetPid must be a strict positive integer <= {MAX_PID}')
    if action not in ACTIONS:
        raise SessionError('ACTION_INVALID', 'action must be one of ' + ', '.join(ACTIONS))
    return str(parsed), target_pid, action


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, payload: dict) -> None:
    with path.open('w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def _powershell(script_args: list[str]) -> list[str]:
    return [str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', *script_args]


def _environment() -> dict[str, str]:
    # PowerShell 7 module paths inherited through Python break Windows
    # PowerShell 5's Utility module. Change this child's environment only.
    env = dict(os.environ)
    env['PSModulePath'] = str(POWERSHELL.parent / 'Modules')
    return env


def _alive(request_id: str) -> bool | None:
    """True/False from the retained launcher handle, None when no handle is retained."""
    proc = _live.get(request_id)
    return None if proc is None else proc.poll() is None


def _no_receipt(record: dict, spawned: bool, note: str) -> dict:
    alive = _alive(record['requestId'])
    proc = _live.get(record['requestId'])
    exit_code = None if proc is None else proc.poll()
    return {'requestId': record['requestId'], 'targetPid': record['targetPid'], 'action': record['action'],
            'requestStatus': record.get('status'), 'launcherPid': record.get('launcherPid'), 'runId': None,
            'spawned': spawned, 'processAlive': alive,
            'launcherExitCode': exit_code,
            'lifecycle': ('running' if alive is True else
                          'launcher-failed' if exit_code not in (None, 0) else 'unknown'),
            'note': note + ('; launcher retained and still alive' if alive is True else
                            '; no retained live process, state is unknown and is never retried')}


def _run_id_for(record: dict, directory: Path) -> str | None:
    """Sanitized read of the fixed launcher stdout: runId only, nothing else is echoed."""
    try:
        text = (directory / 'launcher-stdout.json').read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            run_id = str(uuid.UUID(str(data.get('runId'))))
        except (ValueError, TypeError):
            continue
        if data.get('targetPid') != record.get('targetPid') or data.get('action') != record.get('action'):
            continue
        if (RUNS_DIR / run_id / 'session-launch.json').is_file():
            return run_id
    return None


def _session_status(run_id: str) -> dict[str, Any]:
    """Run the fixed read-only status script once; never retried, never terminated."""
    try:
        proc = subprocess.Popen(_powershell([str(SESSION_STATUS), '-RunId', run_id]),
                                cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                shell=False, creationflags=CREATE_NO_WINDOW, env=_environment())
    except OSError as exc:
        raise SessionError('SESSION_STATUS_SPAWN_FAILED',
                           f'status script did not start ({exc.__class__.__name__})') from None
    try:
        out, _err = proc.communicate(timeout=STATUS_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {'status': 'unknown', 'reason': f'session-status exceeded {STATUS_TIMEOUT_SECONDS}s',
                'notice': 'read-only query left to finish on its own; not terminated and not retried'}
    if proc.returncode != 0:
        return {'status': 'unknown', 'reason': 'session-status query failed',
                'queryExitCode': proc.returncode}
    try:
        payload = json.loads(out.decode('utf-8', errors='replace'))
    except ValueError:
        return {'status': 'unknown', 'reason': 'session-status output was not readable JSON',
                'notice': 'read-only query only; not retried'}
    if not isinstance(payload, dict):
        return {'status': 'unknown', 'reason': 'session-status output was not a JSON object',
                'notice': 'read-only query only; not retried'}
    status = {key: payload[key] for key in SESSION_STATUS_KEYS if key in payload}
    status.setdefault('status', 'unknown')
    return status


def start(request_id: Any, target_pid: Any, action: Any) -> dict:
    """Record and launch one fixed session helper for an existing editor PID; returns immediately."""
    rid, pid, act = _validate(request_id, target_pid, action)
    directory = REQUESTS_DIR / rid
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        directory.mkdir()
    except FileExistsError:
        record = _load(directory / 'request.json')
        if record is None:
            return {'requestId': rid, 'targetPid': pid, 'action': act, 'requestStatus':
                    'request-directory-without-metadata', 'spawned': False, 'runId': None,
                    'processAlive': _alive(rid), 'lifecycle': 'unknown',
                    'note': 'guard directory retained without launch metadata; nothing is spawned again '
                            'and this request is never retried'}
        if record.get('targetPid') != pid or record.get('action') != act:
            raise SessionError('REQUEST_ID_CONFLICT',
                               'this requestId is already recorded with different targetPid or action; rejected')
        return status(rid)
    record = {'requestId': rid, 'targetPid': pid, 'action': act, 'status': 'launch-pending-unknown',
              'launcherPid': None}
    _write(directory / 'request.json', record)  # fixed metadata is durable before any spawn
    with open(directory / 'launcher-stdout.json', 'wb') as out, \
            open(directory / 'launcher-stderr.txt', 'wb') as err:
        try:
            proc = subprocess.Popen(
                _powershell([str(START_SESSION), '-TargetPid', str(pid), '-Action', act]),
                cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                shell=False, close_fds=True, creationflags=CREATE_NO_WINDOW, env=_environment())
        except OSError as exc:
            record['status'] = 'launch-failed-no-automatic-retry'
            _write(directory / 'request.json', record)
            raise SessionError('LAUNCH_SPAWN_FAILED',
                               f'launcher did not start ({exc.__class__.__name__}); not retried') from None
    _live[rid] = proc
    record['launcherPid'] = proc.pid
    record['status'] = 'launcher-started-receipt-pending'
    _write(directory / 'request.json', record)
    return _no_receipt(record, True, 'launcher started; evidence receipt is not yet verified')


def status(request_id: Any) -> dict:
    """Query a recorded request; may launch only the fixed read-only status script."""
    rid = _validate(request_id, 1, ACTIONS[0])[0]
    directory = REQUESTS_DIR / rid
    if not directory.is_dir():
        raise SessionError('REQUEST_UNKNOWN',
                           'no request directory for this requestId; it was not recorded by this server')
    record = _load(directory / 'request.json')
    if record is None:
        return {'requestId': rid, 'runId': None, 'spawned': False, 'processAlive': _alive(rid),
                'lifecycle': 'unknown',
                'note': 'guard directory retained without metadata; launch state is unknowable and never retried'}
    run_id = _run_id_for(record, directory)
    if run_id is None:
        return _no_receipt(record, False, 'no evidence receipt yet')
    return {'requestId': rid, 'runId': run_id, 'spawned': False, 'processAlive': _alive(rid),
            'requestStatus': record.get('status'), 'lifecycle': 'receipt-available',
            'sessionStatus': _session_status(run_id),
            'note': 'Session status is a read of the fixed read-only status script, not a game save, '
                    'scene visibility or playtest acceptance.'}
