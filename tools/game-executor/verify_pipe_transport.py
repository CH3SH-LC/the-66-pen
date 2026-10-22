"""Exercise a separate Python test host over the real Windows named-pipe server.

Run only after building the DLL: python verify_pipe_transport.py --out NEW_DIR
The host is this script with --host; only it loads the DLL. It binds and pumps on
its main thread. The JSON fixture is not a GIL file or a game-save validation.
No token is placed in command arguments, artifacts, or diagnostic output.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time

from client import DLL, ExecutorError, request
from pipe_client import (PipeClient, PipeTransportError, _Connection,
                         REQUEST_HEADER, MAGIC, HELLO, SUBMIT)


def emit(value):
    print(json.dumps(value), flush=True)


def host(out):
    # Importing client does not load a DLL. Only constructing this host does.
    from client import NativeExecutor
    initial = json.loads(sys.stdin.readline())
    token = bytes.fromhex(initial.pop('token'))
    nonce = initial['nonce']
    name = rf'\\.\pipe\Miliastra.GameExecutor.{os.getpid()}.{nonce}'
    owner = threading.get_ident()
    state = {'scene_id': 7, 'revision': 11, 'entities': [], 'calls': [],
             'callback_threads': [], 'main_thread': owner}
    saved = out / 'test-host-save.json'
    executor = NativeExecutor()
    server = C.c_void_p()
    token_buffer = (C.c_uint8 * 32).from_buffer_copy(token)
    native = executor._dll
    native.GE_PipeStart.argtypes = [C.c_void_p, C.c_wchar_p, C.POINTER(C.c_uint8), C.POINTER(C.c_void_p)]
    native.GE_PipeStart.restype = C.c_int32
    native.GE_PipeStop.argtypes = [C.c_void_p]
    native.GE_PipeStop.restype = C.c_int32

    def add(r):
        state['callback_threads'].append(threading.get_ident())
        if threading.get_ident() != owner:
            raise RuntimeError('callback was not on host owner thread')
        state['calls'].append({'operation': 'create', 'request_id': r.request_id})
        state['entities'].append({'entity_id': 1001, 'template_id': r.template_id,
            'position': list(r.position), 'rotation': list(r.rotation), 'scale': list(r.scale)})
        state['revision'] += 1
        return 1001

    def save(r):
        state['callback_threads'].append(threading.get_ident())
        if threading.get_ident() != owner:
            raise RuntimeError('callback was not on host owner thread')
        state['calls'].append({'operation': 'save', 'request_id': r.request_id})
        with saved.open('x', encoding='utf-8') as stream:
            json.dump({'scope': 'python_test_host_fixture', 'state': state}, stream, indent=2)
        return 0

    executor.bind_callbacks(read_scene=lambda: (state['scene_id'], state['revision']),
                            create_instance=add, save_level=save)
    code = native.GE_PipeStart(executor._handle, name, token_buffer, C.byref(server))
    if code:
        executor.close()
        raise ExecutorError(code)
    emit({'ready': True, 'pid': os.getpid(), 'pipe_name': name, 'scope': 'python_test_host'})
    try:
        for line in sys.stdin:
            command = json.loads(line)
            op = command['op']
            if op == 'status':
                emit({'state': state})
            elif op == 'pump':
                emit({'processed': executor.pump(), 'state': state})
            elif op == 'scene':
                state['scene_id'], state['revision'] = command['scene_id'], command['revision']
                emit({'state': state})
            elif op == 'stop':
                started = time.monotonic()
                code = native.GE_PipeStop(server)
                elapsed = time.monotonic() - started
                if code == 0:
                    server = C.c_void_p()
                emit({'stop_code': code, 'elapsed_seconds': elapsed, 'state': state})
                if code == 0:
                    break
            else:
                raise ValueError('unknown test control command')
    finally:
        # Never destroy an executor while the pipe worker can still use it.
        if server.value:
            for _ in range(3):
                if native.GE_PipeStop(server) == 0:
                    server = C.c_void_p()
                    break
        if not server.value:
            executor.close()
        else:
            # This disposable test process exits with its resources intact.
            # No executor Destroy/DLL unload is attempted while Stop is busy.
            os._exit(3)


class HostProcess:
    def __init__(self, out):
        self.token = secrets.token_bytes(32)
        self._lines = queue.Queue()
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
            '--host', '--out', str(out)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding='utf-8',
            creationflags=subprocess.CREATE_NO_WINDOW)
        self._errors = []
        def read_output():
            for line in self.process.stdout:
                self._lines.put(line)
            self._lines.put(None)
        def read_errors():
            for line in self.process.stderr:
                self._errors.append(line)
        threading.Thread(target=read_output, daemon=True).start()
        threading.Thread(target=read_errors, daemon=True).start()
        try:
            self.send({'token': self.token.hex(), 'nonce': secrets.token_hex(16)})
            self.ready = self.receive()
            if not self.ready.get('ready') or self.ready['pid'] != self.process.pid:
                raise RuntimeError('test host process identity mismatch')
        except BaseException:
            # __init__ has not returned, so the outer finally cannot own cleanup.
            self.process.stdin.close()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def receive(self, timeout=8):
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError('test host control timeout') from None
        if line is None:
            # Do not reflect arbitrary subprocess diagnostics or credentials.
            raise RuntimeError('test host exited before its control response')
        return json.loads(line)

    def command(self, op, **fields):
        self.send({'op': op, **fields})
        return self.receive()

    def finish(self):
        if self.process.poll() is None:
            try:
                self.command('stop')
            except (OSError, RuntimeError):
                pass
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            # This exact process was created by the test, never the game/editor.
            self.process.kill()
            self.process.wait(timeout=3)
            raise RuntimeError('isolated test host failed to stop')


def verify(out):
    if os.name != 'nt':
        raise RuntimeError('Windows x64 is required')
    out.mkdir(parents=True, exist_ok=False)
    checks, receipts = [], []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    def rejected(name, action):
        try:
            action()
        except ExecutorError as exc:
            check(name, exc.code == 1)
        else:
            raise AssertionError(name)

    h = None
    try:
        h = HostProcess(out)
        check('client_and_host_are_different_processes', h.process.pid != os.getpid())
        client = PipeClient(h.ready['pipe_name'], h.token, expected_pid=h.process.pid, timeout=3)
        check('HELLO_and_kernel_report_the_actual_host_pid', client.host_pid == h.process.pid)
        created = request(request_id=1, scene_id=7, scene_revision=11,
            operation='create_instance', template_id=42,
            position=(1, 2, 3), rotation=(0, 90, 0), scale=(2, 2, 2))
        queued = client.submit(created)
        receipts.append(queued)
        check('remote_submit_is_only_queued', queued['state'] == 'queued')
        check('receipt_uses_remote_pid_and_limited_scope', queued['host_pid'] == h.process.pid and
            queued['verification_scope'] == 'remote_host_adapter' and
            not queued['game_runtime_verified'] and not queued['gil_save_verified'])
        status = h.command('status')['state']
        check('no_effect_before_host_owner_pump', not status['calls'] and not status['entities'])
        check('repeat_before_pump_is_cached', client.submit(created)['state'] == 'queued')
        pumped = h.command('pump')
        check('host_owner_pump_executes_create_once', pumped['processed'] == 1 and
            len(pumped['state']['entities']) == 1 and len(pumped['state']['calls']) == 1)
        completed = client.result(1)
        receipts.append(completed)
        check('remote_create_result_reads_back', completed['state'] == 'completed' and completed['entity_id'] == 1001)
        check('duplicate_completed_create_does_not_requeue', client.submit(created)['state'] == 'completed' and
              h.command('pump')['processed'] == 0)
        saved = request(request_id=2, scene_id=7, scene_revision=12, operation='save_level')
        check('save_queues_without_creating_file', client.submit(saved)['state'] == 'queued' and
              not (out / 'test-host-save.json').exists())
        check('host_owner_pump_executes_save_once', h.command('pump')['processed'] == 1)
        receipts.append(client.result(2))
        check('save_receipt_completed', receipts[-1]['state'] == 'completed')
        check('duplicate_save_never_reexecutes', client.submit(saved)['state'] == 'completed' and
              h.command('pump')['processed'] == 0)
        fixture = json.loads((out / 'test-host-save.json').read_text(encoding='utf-8'))
        check('test_fixture_records_expected_transform', fixture['scope'] == 'python_test_host_fixture' and
            fixture['state']['entities'][0]['position'] == [1.0, 2.0, 3.0] and
            fixture['state']['entities'][0]['rotation'] == [0.0, 90.0, 0.0] and
            fixture['state']['entities'][0]['scale'] == [2.0, 2.0, 2.0])
        changed = request(request_id=3, scene_id=7, scene_revision=12,
            operation='create_instance', template_id=42)
        client.submit(changed)
        h.command('scene', scene_id=8, revision=1)
        h.command('pump')
        check('scene_change_rejects_queued_business_effect', client.result(3)['state'] == 'scene_changed' and
              len(h.command('status')['state']['calls']) == 2)
        rejected('wrong_token_is_rejected', lambda: PipeClient(h.ready['pipe_name'], bytes([h.token[0] ^ 1]) + h.token[1:], timeout=3))
        rejected('wrong_protocol_version_is_rejected', lambda: client._exchange(HELLO, b'', version=2))
        invalid_abi = request(request_id=4, scene_id=8, scene_revision=1,
            operation='create_instance', template_id=42)
        invalid_abi.struct_size = 87
        rejected('wrong_request_ABI_is_rejected', lambda: client.submit(invalid_abi))
        try:
            PipeClient(h.ready['pipe_name'], h.token, expected_pid=h.process.pid + 1)
        except ValueError:
            checks.append('caller_pid_mismatch_is_rejected_before_connect')
        else:
            raise AssertionError('caller_pid_mismatch_is_rejected_before_connect')
        status = h.command('status')['state']
        check('all_business_callbacks_ran_on_host_main_thread', status['callback_threads'] ==
              [status['main_thread'], status['main_thread']])
        check('invalid_frames_had_no_business_effect', len(status['calls']) == 2)
        half = _Connection(client._api, client._name, client._pid, time.monotonic() + 3)
        try:
            half.transfer(REQUEST_HEADER.pack(MAGIC, 1, SUBMIT, 88)[:4],
                          write=True, deadline=time.monotonic() + 3)
            stopped = h.command('stop')
            check('stop_cancels_a_partial_frame_without_hanging', stopped['stop_code'] == 0 and
                  stopped['elapsed_seconds'] < 3)
        finally:
            half.close()
        h.process.wait(timeout=5)
        check('isolated_host_exits_cleanly', h.process.returncode == 0)
        report = {'scope': 'two_process_named_pipe_test_host', 'client_pid': os.getpid(),
            'host_pid': h.process.pid, 'checks_passed': checks, 'receipts': receipts,
            'dll_sha256': hashlib.sha256(DLL.read_bytes()).hexdigest(),
            'game_runtime_verified': False, 'gil_save_verified': False,
            'limitations': ['The adapter belongs to a disposable Python test host.',
                'The saved JSON is a test fixture, not native GIL or a game save.',
                'No game loader, game thread adapter, or game connection was exercised.']}
        with (out / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
        emit({'passed': len(checks), 'scope': report['scope'], 'result': str(out / 'result.json')})
    finally:
        if h is not None:
            h.finish()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='New evidence directory; existing directory is refused')
    parser.add_argument('--host', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.host:
        host(args.out)
    else:
        verify(args.out)
