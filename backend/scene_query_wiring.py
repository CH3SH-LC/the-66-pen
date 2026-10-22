"""W7: bind the T04 scene-query service to the REAL business backend.

WHAT THIS FILE IS
=================
``backend/scene_query_service.py`` (DS-09) is the model-facing query layer; its execution
layer is *injected*.  In DS-09's tests that injection was a test double, so the only thing
proven was "a synthetic port produces sane G01 results".  This module is the missing half:
the production binding of that injected port to the REAL ``backend/entity_server.py``
execution layer -- ``load_handle`` -> ``resolve_elevated_queue`` -> ``inspect_level``, the
same three calls ``mw_scene_read_entities`` already makes.

Nothing here is a new execution path.  It reuses the business entry point's own functions
so a query cannot reach the level by any route the existing read tool could not.

WHAT IT FIXES IN THE UN-APPLIED DS-09 REGISTRATION PATCH
========================================================
The DS-09 patch classified EVERY ``BusinessError`` as ``never-claimed``.  That is wrong for
the failures that happen *after* the native read was dispatched (``READBACK_FAILED``,
``READBACK_WRONG_LEVEL``, ``READBACK_NOT_ACCEPTED``): G01 requires a post-dispatch failure
to be ``known-failed`` / ``fail``, and reporting it as "no read reached the level"
(``blocked``) hides a real read that ran and was rejected.  Here the port carries a
``dispatched`` flag per stage, and the observer maps pre-dispatch -> ``never-claimed`` and
post-dispatch -> ``known-failed``.

THREE REAL READ-BACK SHAPES
===========================
The query surface answers complete / truncated / paginated reads without ever upgrading
what it has:

* COMPLETE  -- the projection's ``complete`` is true only when the receipt itself proves a
  whole set; the page carries ``complete``/``truncated`` verbatim.
* TRUNCATED -- a partially captured set keeps ``complete=false`` and names the invalidating
  refusals; ``rowsInSnapshot`` and ``snapshotTotalCount`` differ and the page says so.
* PAGED     -- bounded by items AND utf-8 bytes, one object never cut apart, and a
  continuation token bound to the snapshot it was minted for.

The adapter in the observer is *the* thing under test: a live read is presented to the
frozen ``scene-query/observer/v1`` interface, and a refusal is presented as the G01 state
its dispatch position actually justifies.

THIS MODULE NEVER RUNS ANYTHING BY ITSELF.  ``EntityServerReadPort`` is the production
binding; tests inject a stub port.  No module-level import of ``entity_server`` happens, so
importing this file starts no server and reads no receipt.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import uuid

try:  # the package import the server uses (ROOT already on sys.path)
    from backend import scene_query_service as _service
except ImportError:  # pragma: no cover - direct execution from inside backend/
    import scene_query_service as _service

try:  # the versioned profile this wiring publishes (W7)
    from backend import scene_query_contract_adapter as _adapter
except ImportError:  # pragma: no cover - direct execution from inside backend/
    import scene_query_contract_adapter as _adapter

__all__ = (
    'WIRING_VERSION',
    'INTERFACE_VERSION',
    'PRODUCTION_BINDING',
    'PRE_DISPATCH_CODES',
    'POST_DISPATCH_CODES',
    'AWAIT_HUMAN_CODES',
    'PortRefusal',
    'EntityServerReadPort',
    'SceneQueryObserver',
    'SceneQueryTools',
    'TOOL_METHODS',
    'build_service',
    'finalize_tool_result',
    'tool_surface',
    'wiring_manifest',
)

#: Version of THIS wiring (the tool-surface profile it exposes), independent of the frozen
#: v1 tool-result contract.  See ``scene_query_contract_adapter``.
WIRING_VERSION = 2
#: The injected-layer interface this observer speaks.  Frozen by DS-09; not redefined here.
INTERFACE_VERSION = _service.OBSERVER_INTERFACE_VERSION

#: The real symbols in ``backend/entity_server.py`` this wiring dispatches through.  Kept as
#: data so a test can prove the binding names exist in the frozen baseline by AST, rather
#: than trusting a docstring.  ``wiring_manifest()`` publishes it.
PRODUCTION_BINDING = {
    'module': 'backend/entity_server.py',
    #: Read once: resolve the handle, resolve the helper queue, run one read-only inspect.
    'dispatch': ('load_handle', 'resolve_elevated_queue', 'inspect_level'),
    #: Failure type the business entry point raises before dispatch or not at all.
    'errorType': 'BusinessError',
    #: The receipt read after a successful inspect (execution-layer read, never a tool arg).
    'receiptKeys': ('snapshotPath', 'run', 'entities'),
}

#: Refusals raised BEFORE anything reached the level.  ``load_handle`` re-verifies the
#: discovery receipt on disk; ``resolve_elevated_queue`` proves the helper against its own
#: status reply.  A failure here means no read was dispatched, so it is ``never-claimed``.
PRE_DISPATCH_CODES = frozenset({
    'LEVEL_HANDLE_INVALID', 'LEVEL_HANDLE_UNKNOWN', 'LEVEL_HANDLE_RECEIPT_CHANGED',
    'LEVEL_HANDLE_UNVERIFIED',
    'ELEVATED_POINTER_MISSING', 'ELEVATED_QUEUE_OUTSIDE_PROJECT_OR_MISSING',
    'ELEVATED_HEARTBEAT_ABSENT', 'ELEVATED_HELPER_NOT_USABLE', 'ELEVATED_HELPER_BLOCKED',
    'ELEVATED_HELPER_DEADLINE_PASSED', 'ELEVATED_QUEUE_NOT_FOUND', 'ELEVATED_QUEUE_AMBIGUOUS',
    'DISCOVERY_INTERPRETER_MISSING',
})

#: Refusals raised AFTER the native read was dispatched and answered.  These are
#: ``known-failed``: the level WAS read, the answer was rejected, and calling that
#: "no read reached the level" would hide a real dispatch.  This is the DS-09 patch defect.
POST_DISPATCH_CODES = frozenset({
    'READBACK_FAILED', 'READBACK_WRONG_LEVEL', 'READBACK_NOT_ACCEPTED',
    'READBACK_SNAPSHOT_UNREADABLE', 'READBACK_SNAPSHOT_CHANGED', 'BACKEND_NO_JSON_RECEIPT',
})

#: A subset of the pre-dispatch refusals that mean "the execution layer is not available",
#: not "your input is wrong".  G01 nextAction.await-human is the token for exactly this.
AWAIT_HUMAN_CODES = frozenset({
    'ELEVATED_POINTER_MISSING', 'ELEVATED_QUEUE_OUTSIDE_PROJECT_OR_MISSING',
    'ELEVATED_HEARTBEAT_ABSENT', 'ELEVATED_HELPER_NOT_USABLE', 'ELEVATED_HELPER_BLOCKED',
    'ELEVATED_HELPER_DEADLINE_PASSED', 'DISCOVERY_INTERPRETER_MISSING',
    'ELEVATED_QUEUE_NOT_FOUND', 'ELEVATED_QUEUE_AMBIGUOUS',
})

_OPERATION_ID_PREFIX = 'w7query'


class PortRefusal(RuntimeError):
    """A backend read refusal that knows WHICH SIDE of the dispatch it happened on.

    ``dispatched`` is the whole point.  A refusal before dispatch is a pre-dispatch refusal
    (``never-claimed``, ``blocked``, no side effect).  A refusal after dispatch is a
    post-dispatch failure (``known-failed``, ``fail``, the native read did run).  Collapsing
    the two is how a rejected read comes to look like a read that never happened.
    """

    def __init__(self, code, message, *, dispatched, detail=None):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.message = message
        self.dispatched = bool(dispatched)
        self.detail = dict(detail or {})


def _coerce_refusal(exc, *, dispatched):
    """Turn anything the backend raised into a ``PortRefusal`` without losing its code.

    ``BusinessError`` carries ``.code``/``.message``/``.extra``; anything else is reported
    as ``EXECUTION_LAYER_UNAVAILABLE`` rather than being rounded to a business code it did
    not have.
    """
    code = getattr(exc, 'code', None)
    message = getattr(exc, 'message', None)
    extra = getattr(exc, 'extra', None)
    if isinstance(code, str) and code:
        return PortRefusal(code, message or str(exc), dispatched=dispatched,
                           detail=extra if isinstance(extra, dict) else {})
    return PortRefusal('EXECUTION_LAYER_UNAVAILABLE', '%s: %s' % (type(exc).__name__, exc),
                       dispatched=dispatched, detail={})


class EntityServerReadPort:
    """Production binding: one read-only inspection through ``backend/entity_server.py``.

    The backend module is imported lazily on first use and then held, so importing this
    file starts no server, opens no receipt and reads no pointer.  Every dispatch goes
    through the business entry point's own functions; this class adds no execution path,
    accepts no path from a caller, and never mutates.
    """

    def __init__(self, server=None, *, request_prefix=_OPERATION_ID_PREFIX):
        self._server = server
        self._request_prefix = request_prefix

    def _backend(self):
        if self._server is None:
            try:
                from backend import entity_server as server
            except ImportError:  # pragma: no cover - direct execution from inside backend/
                import entity_server as server
            self._server = server
        return self._server

    def read_once(self, handle):
        """``load_handle`` -> ``resolve_elevated_queue`` -> ``inspect_level``.

        Returns ``(level, read)`` where ``read`` carries ``run``, ``entities``,
        ``snapshotPath`` and ``acceptancePath``.  Stage boundaries are preserved so the
        observer can report the correct G01 state for each failure.
        """
        server = self._backend()
        try:
            level = server.load_handle(handle)
        except Exception as exc:                       # noqa: BLE001 - re-raised typed below
            raise _coerce_refusal(exc, dispatched=False)
        try:
            queue, helper = server.resolve_elevated_queue()
        except Exception as exc:                       # noqa: BLE001
            raise _coerce_refusal(exc, dispatched=False)
        level['queue'] = queue
        level['helper'] = helper
        try:
            read = server.inspect_level(level, '%s%s' % (self._request_prefix,
                                                         uuid.uuid4().hex[:16]))
        except Exception as exc:                       # noqa: BLE001
            raise _coerce_refusal(exc, dispatched=True)
        return level, read

    def read_receipt(self, path):
        """Read the decoded receipt the native read produced and hash it.

        An execution-layer read of the receipt the inspect just wrote -- never a tool
        argument.  A failure here is post-dispatch: the read ran and its receipt is
        unreadable, which is a failure, not an absence of a read.
        """
        try:
            document = _load_json(path)
        except Exception as exc:                       # noqa: BLE001
            raise PortRefusal('READBACK_SNAPSHOT_UNREADABLE',
                              'the read-only receipt could not be decoded: %s' % exc,
                              dispatched=True)
        with Path(path).open('rb') as stream:
            snapshot_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        return document, snapshot_sha


def _load_json(path):
    import json
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


class SceneQueryObserver:
    """The injected execution layer for ``SceneQueryService``, over a read port.

    Speaks exactly the frozen ``scene-query/observer/v1`` interface and nothing more.  The
    port is injected, so the same object is what production binds to ``EntityServerReadPort``
    and what a test binds to a stub -- the adapter between the two is the code under test.
    """

    def __init__(self, port):
        self._port = port

    # -- G01 state mapping -------------------------------------------------- #

    @staticmethod
    def _refused(refusal):
        """A refusal that never reached the level: ``never-claimed``."""
        return {
            'interfaceVersion': INTERFACE_VERSION,
            'operationState': 'never-claimed',
            'readMode': 'live',
            'error': {'code': refusal.code, 'message': refusal.message,
                      'detail': dict(refusal.detail)},
            'nextActionHint': 'await-human' if refusal.code in AWAIT_HUMAN_CODES else None,
            'evidenceRef': [],
        }

    @staticmethod
    def _failed(refusal):
        """A refusal raised AFTER dispatch: ``known-failed``, with the run as evidence.

        The DS-09 patch sent this down the ``never-claimed`` path; that is the defect this
        module exists to correct.
        """
        run = refusal.detail.get('run')
        return {
            'interfaceVersion': INTERFACE_VERSION,
            'operationState': 'known-failed',
            'readMode': 'live',
            'error': {'code': refusal.code, 'message': refusal.message,
                      'detail': dict(refusal.detail)},
            'nextActionHint': None,
            'evidenceRef': [run] if isinstance(run, str) and run else [],
        }

    def _refusal_result(self, refusal):
        if refusal.dispatched or refusal.code in POST_DISPATCH_CODES:
            return self._failed(refusal)
        return self._refused(refusal)

    # -- the two interface methods ------------------------------------------ #

    def count(self, handle):
        try:
            level, read = self._port.read_once(handle)
        except PortRefusal as refusal:
            return self._refusal_result(refusal)
        run = read.get('run')
        return {
            'interfaceVersion': INTERFACE_VERSION,
            'operationState': 'known-complete',
            'readMode': 'live',
            'error': None,
            'nextActionHint': None,
            # HONEST-7: the run directory is the controlled reference; the count is the
            # answer and the snapshot path stays out of the business answer.
            'evidenceRef': [run] if isinstance(run, str) and run else [],
            'count': {'entityCount': read.get('entities'), 'levelId': level.get('levelId'),
                      'run': run},
        }

    def observe(self, handle):
        try:
            level, read = self._port.read_once(handle)
        except PortRefusal as refusal:
            return self._refusal_result(refusal)
        # The receipt read is post-dispatch by construction: the inspection already ran, so
        # an unreadable receipt is a FAILURE, not an absence of a read.  Its refusal is
        # returned here rather than raised, so the service's generic ""the layer threw""
        # wrapper cannot replace the code with OBSERVER_CALL_FAILED.
        try:
            snapshot_path = read.get('snapshotPath')
            if not snapshot_path:
                raise PortRefusal('READBACK_SNAPSHOT_UNREADABLE',
                                  'the inspection receipt named no snapshot to read',
                                  dispatched=True, detail={'run': read.get('run')})
            document, snapshot_sha = self._port.read_receipt(snapshot_path)
        except PortRefusal as refusal:
            return self._failed(refusal)
        run = read.get('run')
        return {
            'interfaceVersion': INTERFACE_VERSION,
            'operationState': 'known-complete',
            'readMode': 'live',
            'error': None,
            'nextActionHint': None,
            'evidenceRef': [run] if isinstance(run, str) and run else [],
            'document': document,
            'identity': {
                'targetHandle': handle,
                'levelId': level.get('levelId'),
                # A timestamp is a MEASUREMENT.  NULL rather than a minted one: neither the
                # business entry point nor the inspection receipt carries an observation
                # time, and "when we happened to look" is not an observation time.
                'observedAt': None,
                'receiptPath': str(snapshot_path),
                'receiptSha256': snapshot_sha,
                # G01 open item O-4: load_handle exposes no session process identity, so
                # these are null and the source says where they would have come from.
                'sessionPid': level.get('sessionPid'),
                'sessionCreation': level.get('sessionCreation'),
                'sessionSource': 'discovery-receipt',
            },
        }


def build_service(port=None):
    """A ``SceneQueryService`` over the production port (or an injected one)."""
    return _service.SceneQueryService(SceneQueryObserver(port or EntityServerReadPort()))


# --------------------------------------------------------------------------- #
# the tool surface (thin; the server patch supplies the @mcp.tool wrappers)
# --------------------------------------------------------------------------- #

def finalize_tool_result(body, capability_id):
    """Stamp the transport identity onto a service result.

    Two fields the service cannot know and the versioned layout requires:

    * ``method`` -- the raw registered tool name.  The frozen contract requires it and the
      service knows only its ``capabilityId``;
    * ``profileId`` -- which versioned result layout this is.  A version-gated consumer keys
      off it instead of guessing from the key set.

    Nothing else is added, removed or rewritten: the observation, the stages and the error
    object are the service's own.
    """
    body['method'] = TOOL_METHODS.get(capability_id, capability_id)
    body['profileId'] = _adapter.PROFILE_ID
    return body


def _tool_call(capability, handle, thunk):
    """Run one service call and turn a refusal into its G01 rejected result.

    A refusal here is always pre-dispatch (a query writes nothing), and the caller's own
    free-form extras are carried under ``detail.executionLayerDetail`` so a key named
    ``phase`` or ``next_action`` upstream cannot collide with this refusal's fields.
    """
    try:
        return finalize_tool_result(thunk(), capability)
    except _service.QueryRefusal as refusal:
        return finalize_tool_result(
            _service.refusal_result(refusal, capabilityId=capability, targetHandle=handle),
            capability)
    except PortRefusal as refusal:
        return finalize_tool_result(
            _service.refusal_result(
                _service.QueryRefusal.from_execution_layer(
                    refusal.code, refusal.message, detail=refusal.detail,
                    next_action='await-human' if refusal.code in AWAIT_HUMAN_CODES
                                else 'fix-input'),
                capabilityId=capability, targetHandle=handle),
            capability)


class SceneQueryTools:
    """The four query capabilities as plain functions returning G01 result bodies.

    No MCP types here on purpose: the server patch wraps these into ``CallToolResult`` so
    this class stays importable and testable without an MCP runtime.
    """

    def __init__(self, service=None):
        self.service = service or build_service()

    def observe(self, targetHandle, *, operationId=None, caseId=None, page=False,
                cursor=None, maxItems=None, maxBytes=None):
        return _tool_call('scene.observe', targetHandle, lambda: self.service.query_observe(
            targetHandle=targetHandle, operationId=operationId, caseId=caseId, page=page,
            cursor=cursor, maxItems=maxItems, maxBytes=maxBytes))

    def page(self, targetHandle, *, cursor=None, maxItems=None, maxBytes=None,
             operationId=None, caseId=None):
        return _tool_call('scene.page', targetHandle, lambda: self.service.query_page(
            targetHandle=targetHandle, operationId=operationId, caseId=caseId, cursor=cursor,
            maxItems=maxItems, maxBytes=maxBytes))

    def detail(self, targetHandle, entityId, *, operationId=None, caseId=None):
        return _tool_call('scene.detail', targetHandle, lambda: self.service.query_detail(
            targetHandle=targetHandle, entityId=entityId, operationId=operationId,
            caseId=caseId))

    def diff(self, targetHandle, *, beforeSnapshotId=None, afterSnapshotId=None,
             operationId=None, caseId=None):
        return _tool_call('scene.diff', targetHandle, lambda: self.service.query_diff(
            targetHandle=targetHandle, beforeSnapshotId=beforeSnapshotId,
            afterSnapshotId=afterSnapshotId, operationId=operationId, caseId=caseId))

    def count(self, targetHandle, *, operationId=None, caseId=None):
        return _tool_call('scene.count', targetHandle, lambda: self.service.query_count(
            targetHandle=targetHandle, operationId=operationId, caseId=caseId))


#: capabilityId -> the raw MCP method name the server registers it under.  The adapter uses
#: this to fill the frozen v1 contract's mandatory ``method`` field without inventing one.
TOOL_METHODS = {
    'scene.count': 'mw.scene.countEntities',
    'scene.observe': 'mw.scene.observeLevel',
    'scene.page': 'mw.scene.pageEntities',
    'scene.detail': 'mw.scene.entityDetail',
    'scene.diff': 'mw.scene.diffLevel',
}


def tool_surface():
    """The query tool surface as data, for the registration patch and a test to share."""
    return {
        'wiringVersion': WIRING_VERSION,
        'interfaceVersion': INTERFACE_VERSION,
        'capabilities': [
            {'capabilityId': 'scene.observe', 'method': TOOL_METHODS['scene.observe'],
             'rawToolName': 'mw_scene_observe_level',
             'observationLevel': 'projected', 'writeExecuted': False},
            {'capabilityId': 'scene.page', 'method': TOOL_METHODS['scene.page'],
             'rawToolName': 'mw_scene_page_entities',
             'observationLevel': 'projected', 'writeExecuted': False},
            {'capabilityId': 'scene.detail', 'method': TOOL_METHODS['scene.detail'],
             'rawToolName': 'mw_scene_entity_detail',
             'observationLevel': 'projected', 'writeExecuted': False},
            {'capabilityId': 'scene.diff', 'method': TOOL_METHODS['scene.diff'],
             'rawToolName': 'mw_scene_diff_level',
             'observationLevel': 'projected', 'writeExecuted': False},
        ],
    }


def wiring_manifest():
    """What this wiring binds to, as data, so a reviewer can check it by AST."""
    return {
        'wiringVersion': WIRING_VERSION,
        'interfaceVersion': INTERFACE_VERSION,
        'productionBinding': {key: (list(value) if isinstance(value, tuple) else value)
                              for key, value in PRODUCTION_BINDING.items()},
        'preDispatchCodes': sorted(PRE_DISPATCH_CODES),
        'postDispatchCodes': sorted(POST_DISPATCH_CODES),
        'awaitHumanCodes': sorted(AWAIT_HUMAN_CODES),
        'executionSurface': dict(_service.EXECUTION_SURFACE),
        'note': 'the port dispatches only through entity_server.load_handle / '
                'resolve_elevated_queue / inspect_level; it adds no execution path and '
                'accepts no path from a caller',
    }
