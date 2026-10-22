"""Bounded Windows named-pipe client. This process never loads the executor DLL.

The caller supplies a trusted pipe name and a 32-byte token in memory. A response
only describes the remote adapter; it does not verify a game scene or GIL save.
No failed or uncertain submission is retried automatically.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import math
import os
import re
import struct
import threading
import time

from client import ExecutorError, Request, Result, STATES, request

MAGIC, VERSION = 0x31504547, 1
HELLO, SUBMIT, RESULT = 1, 2, 3
REQUEST_HEADER = struct.Struct('<IIII')
RESPONSE_HEADER = struct.Struct('<IIiI')
HELLO_PAYLOAD = struct.Struct('<IIII')
_NAME = re.compile(r'\\\\\.\\pipe\\Miliastra\.GameExecutor\.([1-9][0-9]*)\.([0-9a-fA-F]{16,64})\Z')
_INVALID = C.c_void_p(-1).value
_PENDING, _INCOMPLETE = 997, 996


class PipeTransportError(RuntimeError):
    """A transport failure; outcome_unknown forbids treating a submit as rejected."""
    def __init__(self, phase, *, winerror=None, outcome_unknown=False):
        self.phase = phase
        self.winerror = winerror
        self.outcome_unknown = outcome_unknown
        text = f'pipe transport {phase}'
        if winerror is not None:
            text += f' (Windows error {winerror})'
        if outcome_unknown:
            text += '; submission outcome is unknown, no automatic retry'
        super().__init__(text)


class _Overlapped(C.Structure):
    _fields_ = [('Internal', C.c_size_t), ('InternalHigh', C.c_size_t),
                ('Offset', W.DWORD), ('OffsetHigh', W.DWORD), ('hEvent', W.HANDLE)]


def _api():
    if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
        raise RuntimeError('Windows x64 is required')
    k = C.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateFileW': (W.HANDLE, [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]),
        'WaitNamedPipeW': (W.BOOL, [W.LPCWSTR, W.DWORD]),
        'GetNamedPipeServerProcessId': (W.BOOL, [W.HANDLE, C.POINTER(W.ULONG)]),
        'CreateEventW': (W.HANDLE, [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR]),
        'CloseHandle': (W.BOOL, [W.HANDLE]),
        'ReadFile': (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(_Overlapped)]),
        'WriteFile': (W.BOOL, [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(_Overlapped)]),
        'WaitForSingleObject': (W.DWORD, [W.HANDLE, W.DWORD]),
        'GetOverlappedResult': (W.BOOL, [W.HANDLE, C.POINTER(_Overlapped), C.POINTER(W.DWORD), W.BOOL]),
        'CancelIoEx': (W.BOOL, [W.HANDLE, C.POINTER(_Overlapped)]),
    }
    for name, (restype, argtypes) in signatures.items():
        fn = getattr(k, name)
        fn.restype, fn.argtypes = restype, argtypes
    return k


def _remaining(deadline):
    return max(0, int(math.ceil((deadline - time.monotonic()) * 1000)))


class _Connection:
    def __init__(self, api, name, pid, deadline):
        self.api, self.handle = api, None
        # Retry only a busy connection before sending any data, never a request.
        while True:
            if not _remaining(deadline):
                raise PipeTransportError('connect timeout')
            handle = api.CreateFileW(name, 0xC0000000, 0, None, 3,
                                     0x40000000 | 0x00100000, None)
            if handle != _INVALID:
                self.handle = handle
                break
            error = C.get_last_error()
            if error != 231:
                raise PipeTransportError('connect', winerror=error)
            if not api.WaitNamedPipeW(name, _remaining(deadline)):
                raise PipeTransportError('wait for connection', winerror=C.get_last_error())
        actual = W.ULONG()
        if not api.GetNamedPipeServerProcessId(self.handle, C.byref(actual)):
            error = C.get_last_error()
            self.close()
            raise PipeTransportError('server identity', winerror=error)
        self.pid = actual.value
        if self.pid != pid:
            self.close()
            raise PipeTransportError('server process identity mismatch')

    def close(self):
        if self.handle is not None:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def _retire_pending(self, event, ov, buffer):
        """Keep I/O memory alive without making the calling thread wait forever."""
        api, handle = self.api, self.handle
        api.CancelIoEx(handle, C.byref(ov))
        self.handle = None
        def finish():
            count = W.DWORD()
            # Capturing buffer is required even though the cleanup never reads it.
            keepalive = buffer
            api.GetOverlappedResult(handle, C.byref(ov), C.byref(count), True)
            api.CloseHandle(event)
            api.CloseHandle(handle)
            del keepalive
        threading.Thread(target=finish, name='pipe-cancel-cleanup', daemon=True).start()

    def transfer(self, value, *, write, deadline):
        length = len(value) if write else value
        if not length:
            return b''
        buffer = C.create_string_buffer(value, length) if write else C.create_string_buffer(length)
        completed = 0
        while completed < length:
            if not _remaining(deadline):
                raise PipeTransportError('write timeout' if write else 'read timeout')
            event = self.api.CreateEventW(None, True, False, None)
            if not event:
                raise PipeTransportError('create I/O event', winerror=C.get_last_error())
            ov = _Overlapped()
            ov.hEvent = event
            count = W.DWORD()
            fn = self.api.WriteFile if write else self.api.ReadFile
            immediate = fn(self.handle, C.byref(buffer, completed), length-completed,
                           C.byref(count), C.byref(ov))
            if not immediate:
                error = C.get_last_error()
                if error != _PENDING:
                    self.api.CloseHandle(event)
                    raise PipeTransportError('write' if write else 'read', winerror=error)
                waited = self.api.WaitForSingleObject(event, _remaining(deadline))
                if waited != 0:
                    self._retire_pending(event, ov, buffer)
                    raise PipeTransportError('write timeout' if write else 'read timeout')
                if not self.api.GetOverlappedResult(self.handle, C.byref(ov), C.byref(count), False):
                    error = C.get_last_error()
                    if error == _INCOMPLETE:
                        self._retire_pending(event, ov, buffer)
                    else:
                        self.api.CloseHandle(event)
                    raise PipeTransportError('I/O completion', winerror=error)
            self.api.CloseHandle(event)
            if not 0 < count.value <= length-completed:
                raise PipeTransportError('unexpected end of stream')
            completed += count.value
        return buffer.raw if not write else b''


class PipeClient:
    """Remote adapter client; each operation uses one authenticated connection.

    timeout applies to each HELLO/Submit/GetResult exchange, including connecting.
    The client owns no executor, adapter callbacks, game handle, or DLL lifecycle.
    Call result(request_id) explicitly after an uncertain submit if appropriate;
    there is no automatic resubmission, pump, or background polling.
    """
    def __init__(self, pipe_name: str, token: bytes, *, expected_pid=None, timeout=5.0):
        match = _NAME.fullmatch(pipe_name) if isinstance(pipe_name, str) else None
        if not match:
            raise ValueError('invalid project-local pipe name')
        named_pid = int(match.group(1))
        if named_pid > 0xFFFFFFFF:
            raise ValueError('invalid pipe process ID')
        if expected_pid is not None and (type(expected_pid) is not int or expected_pid != named_pid):
            raise ValueError('expected process ID does not match pipe name')
        if not isinstance(token, bytes) or len(token) != 32 or not any(token):
            raise ValueError('token must be exactly 32 nonzero-as-a-whole bytes')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('timeout must be in (0, 30] seconds')
        if C.sizeof(Request) != 88 or C.sizeof(Result) != 240:
            raise RuntimeError('local wire ABI layout mismatch')
        self._api = _api()
        self._name, self._token = pipe_name, token
        self._pid, self.timeout = named_pid, float(timeout)
        payload = self._exchange(HELLO, b'')
        if len(payload) != HELLO_PAYLOAD.size:
            raise PipeTransportError('HELLO size mismatch')
        remote_pid, abi, request_size, result_size = HELLO_PAYLOAD.unpack(payload)
        if remote_pid != self._pid or abi != 1 or (request_size, result_size) != (88, 240):
            raise PipeTransportError('HELLO ABI or process mismatch')
        self.host_pid = remote_pid

    def _exchange(self, operation, payload, *, version=VERSION):
        deadline = time.monotonic() + self.timeout
        connection = _Connection(self._api, self._name, self._pid, deadline)
        sent = False
        try:
            frame = REQUEST_HEADER.pack(MAGIC, version, operation, len(payload)) + self._token + payload
            sent = True
            connection.transfer(frame, write=True, deadline=deadline)
            raw = connection.transfer(RESPONSE_HEADER.size, write=False, deadline=deadline)
            magic, response_version, code, length = RESPONSE_HEADER.unpack(raw)
            expected = 16 if operation == HELLO else 240
            if magic != MAGIC or response_version != VERSION or length not in (0, expected):
                raise PipeTransportError('response frame mismatch')
            result = connection.transfer(length, write=False, deadline=deadline)
            if code:
                raise ExecutorError(code)
            if length != expected:
                raise PipeTransportError('successful response size mismatch')
            return result
        except PipeTransportError as exc:
            if operation == SUBMIT and sent:
                raise PipeTransportError(exc.phase, winerror=exc.winerror, outcome_unknown=True) from None
            raise
        finally:
            connection.close()

    def _receipt(self, raw, request_id, operation=None):
        r = Result.from_buffer_copy(raw)
        if (r.struct_size != C.sizeof(Result) or r.request_id != request_id or
                r.state >= len(STATES) or r.operation not in (1, 2) or
                (operation is not None and r.operation != operation)):
            raise PipeTransportError('result ABI or request identity mismatch',
                                     outcome_unknown=operation is not None)
        return {'request_id': r.request_id, 'operation': r.operation,
                'state': STATES[r.state], 'detail_code': r.detail_code,
                'scene_id': r.scene_id, 'scene_revision': r.scene_revision,
                'entity_id': r.entity_id,
                'message': bytes(r.message).decode('utf-8', errors='replace'),
                'host_pid': self.host_pid, 'verification_scope': 'remote_host_adapter',
                'game_runtime_verified': False, 'gil_save_verified': False}

    def submit(self, value: Request) -> dict:
        if not isinstance(value, Request):
            raise TypeError('a typed Request is required')
        owned = Request.from_buffer_copy(value)
        return self._receipt(self._exchange(SUBMIT, bytes(owned)), owned.request_id, owned.operation)

    def result(self, request_id: int) -> dict:
        if type(request_id) is not int or not 1 <= request_id < 1 << 64:
            raise ValueError('request_id must be a positive uint64')
        return self._receipt(self._exchange(RESULT, struct.pack('<Q', request_id)), request_id)
