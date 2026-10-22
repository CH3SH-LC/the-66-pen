"""Host-local Python binding for our native executor; never attaches to a game.

Loading this DLL runs it inside the current Python process. It is not a game
connector. A host callback receipt does not verify a game scene or a GIL file.
"""
from __future__ import annotations

import ctypes as C
from contextlib import contextmanager
import math
import os
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parents[2]
DLL = ROOT / '.runtime/game-executor/build/game_executor.dll'
U64_MAX = (1 << 64) - 1
MAX_TTL_MS = 86_400_000
CREATE_INSTANCE, SAVE_LEVEL = 1, 2
STATES = ('queued', 'running', 'completed', 'failed', 'expired', 'scene_changed', 'unavailable')
CODES = ('ok', 'invalid', 'unavailable', 'wrong_thread', 'busy', 'queue_full',
         'history_full', 'not_found', 'id_conflict', 'internal')


class Request(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('operation', C.c_uint32),
                ('request_id', C.c_uint64), ('scene_id', C.c_uint64),
                ('scene_revision', C.c_uint64), ('ttl_ms', C.c_uint64),
                ('template_id', C.c_uint64), ('position', C.c_float * 3),
                ('rotation', C.c_float * 3), ('scale', C.c_float * 3)]


class Scene(C.Structure):
    _fields_ = [('scene_id', C.c_uint64), ('revision', C.c_uint64)]


class AdapterResult(C.Structure):
    _fields_ = [('entity_id', C.c_uint64), ('detail_code', C.c_int32), ('message', C.c_char * 192)]


ReadScene = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.POINTER(Scene))
Execute = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.POINTER(Request), C.POINTER(AdapterResult))


class Adapter(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('abi_version', C.c_uint32),
                ('context', C.c_void_p), ('read_scene', ReadScene),
                ('create_instance', Execute), ('save_level', Execute)]


class Result(C.Structure):
    _fields_ = [('struct_size', C.c_uint32), ('state', C.c_uint32),
                ('request_id', C.c_uint64), ('operation', C.c_uint32),
                ('detail_code', C.c_int32), ('scene_id', C.c_uint64),
                ('scene_revision', C.c_uint64), ('entity_id', C.c_uint64),
                ('message', C.c_char * 192)]


class ExecutorError(RuntimeError):
    def __init__(self, code: int):
        self.code = code
        self.reason = CODES[code] if 0 <= code < len(CODES) else f'unknown_{code}'
        super().__init__(self.reason)


def _u64(value, label: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= U64_MAX:
        raise ValueError(f'{label} must be an integer in [{minimum}, {U64_MAX}]')
    return value


def _vector(value, label: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f'{label} must contain three finite numbers')
    result = []
    for item in value:
        if type(item) not in (int, float):
            raise ValueError(f'{label} contains a non-number')
        number = float(item)
        if not math.isfinite(number) or not math.isfinite(C.c_float(number).value):
            raise ValueError(f'{label} must fit finite float32')
        result.append(number)
    return tuple(result)


def request(*, request_id: int, scene_id: int, scene_revision: int,
            operation: str, ttl_ms: int = 30_000, template_id: int = 0,
            position=None, rotation=None, scale=None) -> Request:
    """Build a typed request. Units/angles must match the bound host adapter."""
    r = Request()
    r.struct_size = C.sizeof(r)
    r.request_id = _u64(request_id, 'request_id', 1)
    r.scene_id = _u64(scene_id, 'scene_id', 1)
    r.scene_revision = _u64(scene_revision, 'scene_revision')
    r.ttl_ms = _u64(ttl_ms, 'ttl_ms', 1)
    if r.ttl_ms > MAX_TTL_MS:
        raise ValueError('ttl_ms exceeds one day')
    if operation == 'create_instance':
        r.operation = CREATE_INSTANCE
        r.template_id = _u64(template_id, 'template_id', 1)
        r.position[:] = _vector((0, 0, 0) if position is None else position, 'position')
        r.rotation[:] = _vector((0, 0, 0) if rotation is None else rotation, 'rotation')
        r.scale[:] = _vector((1, 1, 1) if scale is None else scale, 'scale')
        if any(v <= 0 for v in r.scale):
            raise ValueError('scale must be positive')
    elif operation == 'save_level':
        r.operation = SAVE_LEVEL
        if type(template_id) is not int or template_id != 0 or any(
                v is not None for v in (position, rotation, scale)):
            raise ValueError('save_level has no template or transform arguments')
    else:
        raise ValueError('unknown operation')
    return r


def _receipt(r: Result) -> dict:
    return {'request_id': r.request_id, 'operation': r.operation,
            'state': STATES[r.state] if r.state < len(STATES) else 'unknown',
            'detail_code': r.detail_code, 'scene_id': r.scene_id,
            'scene_revision': r.scene_revision, 'entity_id': r.entity_id,
            'message': bytes(r.message).decode('utf-8', errors='replace'),
            'host_pid': os.getpid(), 'verification_scope': 'current_process_adapter',
            'game_runtime_verified': False, 'gil_save_verified': False}


class NativeExecutor:
    """Protects handle lifetime without holding a Python lock across callbacks."""
    def __init__(self):
        if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
            raise RuntimeError('Windows x64 is required')
        if not DLL.is_file():
            raise FileNotFoundError(f'Build the project-local executor first: {DLL}')
        self._dll = C.CDLL(str(DLL))
        self._lock = threading.RLock()
        self._active = 0
        self._callbacks = None
        self._handle = C.c_void_p()
        signatures = {
            'GE_ApiVersion': (C.c_uint32, []),
            'GE_StructureSize': (C.c_uint32, [C.c_uint32]),
            'GE_Create': (C.c_int32, [C.POINTER(C.c_void_p)]),
            'GE_Destroy': (C.c_int32, [C.c_void_p]),
            'GE_Bind': (C.c_int32, [C.c_void_p, C.POINTER(Adapter)]),
            'GE_Unbind': (C.c_int32, [C.c_void_p]),
            'GE_Submit': (C.c_int32, [C.c_void_p, C.POINTER(Request), C.POINTER(Result)]),
            'GE_GetResult': (C.c_int32, [C.c_void_p, C.c_uint64, C.POINTER(Result)]),
            'GE_Pump': (C.c_int32, [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32)]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self._dll, name);fn.restype = result;fn.argtypes = args
        if self._dll.GE_ApiVersion() != 1:
            raise RuntimeError('native ABI version mismatch')
        for kind, cls in enumerate((Request, Result, Adapter, AdapterResult), 1):
            if self._dll.GE_StructureSize(kind) != C.sizeof(cls):
                raise RuntimeError(f'native ABI layout mismatch: {cls.__name__}')
        self._check(self._dll.GE_Create(C.byref(self._handle)))

    @staticmethod
    def _check(code):
        if code != 0:raise ExecutorError(code)

    def _live(self):
        if not self._handle.value:raise RuntimeError('executor is closed')

    @contextmanager
    def _use(self):
        with self._lock:
            self._live()
            self._active += 1
            handle = self._handle
        try:
            yield handle
        finally:
            with self._lock:self._active -= 1

    def bind_callbacks(self, *, read_scene, create_instance=None, save_level=None):
        """Bind trusted current-process host code, not a remote/game address.

        read_scene returns (scene_id, revision). Operations receive an owned Request copy and
        return an entity ID or zero. Exceptions are terminal callback failures.
        """
        def get_scene(_, out):
            try:
                scene_id, revision = read_scene()
                out.contents.scene_id = _u64(scene_id, 'scene_id', 1)
                out.contents.revision = _u64(revision, 'revision')
                return 0
            except BaseException:
                return -1

        def wrap(fn):
            if fn is None:return Execute()
            def execute(_, incoming, out):
                try:
                    value = fn(Request.from_buffer_copy(incoming.contents))
                    out.contents.entity_id = _u64(value, 'entity_id')
                    return 0
                except BaseException:
                    out.contents.detail_code = -1
                    out.contents.message = b'Python host callback failed; outcome may be partial'
                    return -1
            return Execute(execute)

        callbacks = (ReadScene(get_scene), wrap(create_instance), wrap(save_level))
        adapter = Adapter(C.sizeof(Adapter), 1, None, *callbacks)
        # Bind/Unbind never invoke callbacks: keep their native state transition
        # atomic with Python callback-reference ownership across competing threads.
        with self._lock:
            self._live()
            self._check(self._dll.GE_Bind(self._handle, C.byref(adapter)))
            self._callbacks = (callbacks, adapter)

    def submit(self, r: Request) -> dict:
        if not isinstance(r, Request):raise TypeError('a typed Request is required')
        r = Request.from_buffer_copy(r)
        with self._use() as handle:
            out = Result()
            self._check(self._dll.GE_Submit(handle, C.byref(r), C.byref(out)))
            return _receipt(out)

    def result(self, request_id: int) -> dict:
        request_id = _u64(request_id, 'request_id', 1)
        with self._use() as handle:
            out = Result()
            self._check(self._dll.GE_GetResult(handle, request_id, C.byref(out)))
            return _receipt(out)

    def pump(self, maximum: int = 32) -> int:
        if type(maximum) is not int or not 1 <= maximum <= 32:
            raise ValueError('maximum must be in [1, 32]')
        with self._use() as handle:
            processed = C.c_uint32()
            self._check(self._dll.GE_Pump(handle, maximum, C.byref(processed)))
            return processed.value

    def unbind(self):
        with self._lock:
            self._live()
            self._check(self._dll.GE_Unbind(self._handle))
            self._callbacks = None

    def close(self):
        with self._lock:
            if not self._handle.value:return
            if self._active:raise ExecutorError(4)
            self._check(self._dll.GE_Destroy(self._handle))
            self._handle = C.c_void_p();self._callbacks = None

    def __enter__(self):return self
    def __exit__(self, *_):self.close()
