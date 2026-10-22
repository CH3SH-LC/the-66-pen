"""Model-facing scene query surface over the verified T04 projection.

WHAT THIS IS
============
The T04 projection (``backend/scene_observation.py``) is a pure function library: it can
project ONE already-decoded document, page it and diff two of them, but it holds no state,
cannot obtain a document, and answers by entity id only.  A model cannot consume that
directly -- it would have to carry a whole projection between calls, and nothing would stop
it from reading "the level holds 15 entities" as "here are the 15 entities".

This module is the thin, stateful, model-facing layer on top:

* the EXECUTION LAYER IS INJECTED.  ``SceneQueryService`` is constructed with an *observer*
  object; this module never opens a file, never spawns a process, never names a command, a
  queue, a helper, a script or an executable, and **no public method takes a path**.
  ``EXECUTION_SURFACE`` states that in machine-checkable form and
  ``backend/tests/test_scene_query_service.py`` enforces it by walking this file's AST.
* it HOLDS the projections it took, so page/detail/diff are answered from an observation
  the execution layer actually produced, and a cursor is only ever applied to the snapshot
  it was minted for.
* it speaks the G01 v1 result contract (``contractVersion "1"``): ``state`` from
  ``rejected|pending|unknown|failed|completed``, the five tool stages, per-stage
  ``evidenceRef``, a closed ``nextAction`` token, and an error object that separates a
  pre-dispatch refusal from a post-dispatch failure.

THE TWO LAYERS, WHICH MUST NOT BE CONFUSED
==========================================
``mw.scene.readEntities`` today answers with an entity COUNT and a snapshot PATH.  That is
the *count layer*: a number that came from a read, plus a file reference.  It carries no
entity attribute, no per-field provenance, no completeness verdict, and it cannot answer
"which entities" or "what changed".  The *observation layer* is a projection: ordered rows,
per-attribute source and observation time, ``unknown`` where nothing was read, and
``complete``/``truncated``/``trusted`` as three separate verdicts.

The two are kept apart in the types here:

* ``query_count`` and ``label_legacy_read_result`` produce ``observationLevel ==
  'count-only'``: no entity rows, no attributes, and the snapshot path moved out of the
  business answer into ``evidenceRef`` (G01 HONEST-7 forbids handing the model a raw
  snapshot path as the answer).
* ``query_observe``/``query_page``/``query_detail``/``query_diff`` produce
  ``observationLevel == 'projected'``, and every one of them REFUSES with
  ``COUNT_IS_NOT_AN_OBSERVATION`` when the only thing held for that handle is a count.
* a count-only result can never be turned into rows by any call here: the count path
  stores no projection at all.

WHAT IS NEVER UPGRADED
======================
* ``readMode`` is asserted by the injected layer and cross-checked against the document's
  own fixture marker.  A live read carrying a fixture document is refused
  (``READ_MODE_CONTRADICTS_DOCUMENT``); a non-live read is reported ``not-run`` on the
  ``liveReadback`` stage with a reason.  This layer never emits ``pass`` for material that
  is not a live read, and never emits ``pass`` without at least one ``evidenceRef`` (G01
  HONEST-3).
* ``complete``/``truncated``/``trusted``/``unknown``/``refusals`` come from the T04
  projection verbatim.  Nothing here recomputes or relaxes them.
* an entity ``position`` that was never read stays ``unknown``; the projection guarantees
  it and this layer passes the row through unchanged.
* a held ``subsystems`` block keeps its refusal status, so an empty payload under a
  non-``ok`` status stays ``state="unknown"`` and is never read as "the subsystem holds
  nothing".  T04 has never captured a real ``subsystems`` block; this layer invents none.
* a query sets no stage other than ``liveReadback``.  ``saveDiff``/``reopen``/``runtime``/
  ``cleanup`` are always ``not-run`` with a reason: a clean read says nothing about what
  reached the disk.

CURSOR POLICY
=============
A page cursor is bound by T04 to ``snapshotId`` + content digest + level.  This service adds
one rule on top: **a page is answered against the handle's CURRENT held snapshot**, so a
cursor taken before a newer observation is refused (``CURSOR_SNAPSHOT_CHANGED`` /
``CURSOR_CONTENT_CHANGED``) rather than silently splicing two reads together.  That is
deliberately stricter than "any snapshot still in memory": two reads of one level are two
observations and a page must not span them.  ``diff`` is the only call that addresses an
older snapshot, and it does so by explicit ``snapshotId``, never by cursor.

INJECTED INTERFACE (frozen for DS-08 / T05-T06 integration)
===========================================================
``observer.count(targetHandle)`` and ``observer.observe(targetHandle)`` both return a
mapping with exactly these keys (extra keys are recorded, never dropped silently):

    interfaceVersion : 'scene-query/observer/v1'    optional, checked when present
    operationState   : never-claimed | claimed | dispatched | known-complete |
                       known-failed | outcome-unknown        (G01 operationState)
    readMode         : 'live' | 'fixture'
    error            : null | {code, message, detail}
    nextActionHint   : null | one of the six G01 nextAction tokens
    evidenceRef      : [project-relative reference string, ...]
    count            : {entityCount, levelId?, run?, snapshotPath?, sessionPid?...}  count()
    document         : the decoded context document                                  observe()
    identity         : {targetHandle, levelId, observedAt?, receiptPath?, receiptSha256?,
                        sessionPid?, sessionCreation?, sessionSource?}                observe()

``observer_result_schema()`` returns that shape as data so a test or a peer module can check
it without reading this docstring.

A mapping whose ``operationState`` is not one of the six tokens is REFUSED
(``OBSERVER_RESULT_UNRECOGNIZED_STATE``); a state that contradicts the material it came with
(``known-complete`` with no document, or a document under a pre-terminal state) is REFUSED
(``OBSERVER_RESULT_CONTRADICTORY``).  Nothing is guessed from a near-miss token.
"""
from __future__ import annotations

from collections.abc import Mapping
import json

try:  # the package import the server uses (ROOT already on sys.path)
    from backend import scene_observation as _observation
except ImportError:  # pragma: no cover - direct execution from inside backend/
    import scene_observation as _observation

__all__ = (
    'SCHEMA_VERSION',
    'CONTRACT_ID',
    'CONTRACT_VERSION',
    'OBSERVER_INTERFACE_VERSION',
    'CAPABILITY_OBSERVE',
    'EXECUTION_SURFACE',
    'BUSINESS_STATES',
    'OPERATION_STATES',
    'STAGE_NAMES',
    'STAGE_STATUSES',
    'NEXT_ACTIONS',
    'OBSERVATION_LEVELS',
    'OBSERVER_RESULT_KEYS',
    'MAX_INLINE_IDS',
    'MAX_INLINE_REFUSALS',
    'MAX_DIFF_IDS',
    'MAX_DETAIL_BYTES',
    'QueryRefusal',
    'SceneQueryService',
    'observer_result_schema',
    'label_legacy_read_result',
    'refusal_result',
)

#: Version of the model-facing document this module emits.
SCHEMA_VERSION = 1
#: Stable contract id carried by every result, so a consumer cannot mix versions.
CONTRACT_ID = 'scene-query/service/v1'
#: G01 contractVersion -- a STRING, versioning the tool/state contract (G01 conflict C-6).
CONTRACT_VERSION = '1'
#: The injected execution-layer result contract.  Frozen; see the module docstring.
OBSERVER_INTERFACE_VERSION = 'scene-query/observer/v1'
#: G01 capabilityId of the read capability this service implements.
CAPABILITY_OBSERVE = 'scene.observe'

#: Machine-checkable statement of what this module can reach.  All false, by construction.
EXECUTION_SURFACE = {
    'subprocess': False,
    'shell': False,
    'filesystem': False,
    'network': False,
    'processControl': False,
    'arbitraryCommandParameter': False,
    'forwardableScriptOrPlan': False,
    'callerSuppliedPathParameter': False,
}

#: G01 businessState -- the model-facing verdict, closed set.
BUSINESS_STATES = ('rejected', 'pending', 'unknown', 'failed', 'completed')
#: G01 operationState -- what the execution layer may report, closed set.
OPERATION_STATES = ('never-claimed', 'claimed', 'dispatched', 'known-complete',
                    'known-failed', 'outcome-unknown')
#: G01 tool stages: separately resolved, separately reported.
STAGE_NAMES = ('liveReadback', 'saveDiff', 'reopen', 'runtime', 'cleanup')
STAGE_STATUSES = ('not-run', 'pass', 'fail', 'blocked', 'unknown', 'not-applicable')
NEXT_ACTIONS = ('none', 'fix-input', 'poll-same-operation', 'reconcile',
                'report-and-repair', 'await-human')
#: The two things a result here can be.  There is no third.
OBSERVATION_LEVELS = ('count-only', 'projected')

#: operationState -> (businessState, default nextAction).  G01 businessState.projection plus
#: G01 nextAction.nextActionFor.
_STATE_PROJECTION = {
    'never-claimed': ('rejected', 'fix-input'),
    'claimed': ('pending', 'poll-same-operation'),
    'dispatched': ('pending', 'poll-same-operation'),
    'known-complete': ('completed', 'none'),
    'known-failed': ('failed', 'report-and-repair'),
    'outcome-unknown': ('unknown', 'reconcile'),
}
#: States under which the execution layer may hand over produced material.
_MATERIAL_STATES = ('known-complete', 'known-failed')

#: Keys the injected observer result may carry.  Anything else is recorded in
#: ``unrecognizedObserverKeys`` rather than ignored.
OBSERVER_RESULT_KEYS = ('interfaceVersion', 'operationState', 'readMode', 'error',
                        'nextActionHint', 'evidenceRef', 'count', 'document', 'identity')

#: Bound on ids inlined into a model-facing answer.  Exceeding it sets an explicit
#: ``...Truncated`` flag beside the true count; a list is never silently cut.
MAX_INLINE_IDS = 200
#: Bound on refusal entries inlined into a model-facing observation summary.
MAX_INLINE_REFUSALS = 100
#: Bound on added/removed/changed ids inlined into a model-facing diff.
MAX_DIFF_IDS = 200
#: Bound on the UTF-8 bytes of one detail answer, mirroring the projection's page cap.
MAX_DETAIL_BYTES = _observation.MAX_PAGE_BYTES
#: Bound on snapshots retained per handle; older ones stay diff-addressable until evicted.
DEFAULT_HELD_SNAPSHOTS = 8

_OPERATION_ID_MAX = 80
_READ_MODES = ('live', 'fixture')


class QueryRefusal(RuntimeError):
    """A refusal with a stable code, carrying its G01 disposition.

    Raised for contract/shape violations only: an observer result this layer cannot trust, a
    handle that is not a handle, a cursor that does not belong to the snapshot being paged,
    a count being asked to answer as an observation.  Evidence problems (truncation, a read
    failure, an untrusted identity set) are NOT exceptions here: they are returned inside
    the result, so a refusal can never be mistaken for an empty answer.

    Every refusal this module raises is a PRE-DISPATCH refusal.  A query writes nothing, so
    its side effect is always ``none`` (G01 errorTaxonomy.disposition); a read has no
    mutation to be uncertain about.
    """

    def __init__(self, code: str, message: str, *, phase: str = 'input',
                 next_action: str = 'fix-input', **detail) -> None:
        super().__init__(message)
        if next_action not in NEXT_ACTIONS:
            raise ValueError('next_action must be a G01 nextAction token: %r' % (next_action,))
        self.code = code
        self.message = message
        self.phase = phase
        self.next_action = next_action
        self.detail = detail

    @classmethod
    def from_execution_layer(cls, code, message, *, detail=None, next_action='fix-input'):
        """Build a refusal from an execution-layer error without key collisions.

        An execution layer's error extras are free-form, so splatting them as keyword
        arguments could collide with ``phase``/``next_action``.  The mapping is carried
        verbatim under ``detail.executionLayerDetail`` instead, so nothing is lost and
        nothing is silently overwritten.
        """
        return cls(code, message, phase='observer', next_action=next_action,
                   executionLayerDetail=dict(detail or {}))

    @property
    def disposition(self) -> str:
        return 'refusal-before-dispatch'

    def as_error(self) -> dict:
        return {'code': self.code, 'message': self.message, 'phase': self.phase,
                'disposition': self.disposition, 'detail': self.detail}

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return '%s: %s' % (self.code, self.message)


# --------------------------------------------------------------------------- #
# small deterministic helpers
# --------------------------------------------------------------------------- #

def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bytes(value) -> int:
    """UTF-8 bytes of the canonical JSON of a value, for byte-accounted answers."""
    return len(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8'))


def _require_mapping(value, code, what, **detail):
    if not isinstance(value, Mapping):
        raise QueryRefusal(code, '%s must be a JSON object' % what,
                           observedType=type(value).__name__, **detail)
    return value


def _string_list(value, code, what):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or not v
                                                   for v in value):
        raise QueryRefusal(code, '%s must be an array of non-empty strings' % what)
    return [str(v) for v in value]


def _operation_id(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= _OPERATION_ID_MAX or \
            not value[0].isalnum() or any(not (c.isalnum() or c in '_-') for c in value):
        raise QueryRefusal(
            'OPERATION_ID_INVALID',
            '%s must be 1..%d letters, digits, underscore or hyphen starting with a letter '
            'or digit (G01 idempotency.keyShape); this service never mints one for the '
            'caller' % (field, _OPERATION_ID_MAX))
    return value


def _require_handle(value, field='targetHandle'):
    if not isinstance(value, str) or not value.strip():
        raise QueryRefusal(
            'HANDLE_REQUIRED',
            '%s must be the non-empty opaque handle the discovery call minted; this layer '
            'never mints one and never accepts a level id in its place' % field)
    return value


def _cap(values, limit):
    values = list(values or [])
    return values[:limit], len(values) > limit


def _cap_optional(values, limit):
    """Cap a list, or pass ``None`` through unchanged.

    ``None`` is the projection's way of saying "no list could be produced" (an unreadable
    side of a diff).  Turning it into ``[]`` here would be exactly the upgrade this layer
    exists to prevent, so it is preserved.
    """
    if values is None:
        return None, False
    return _cap(values, limit)


def _stage(status, *, reason, evidence_ref=(), evidence_sha=()):
    """One G01 stage object: status, mandatory reason, and its own evidenceRef.

    G01 HONEST-3 requires every ``pass`` to carry at least one ``evidenceRef``.  This module
    is stricter than the minimum for the other statuses -- it always carries a reason --
    because a bare ``not-run`` reads like a missing field.
    """
    if status not in STAGE_STATUSES:
        raise QueryRefusal('STAGE_STATUS_INVALID', 'unknown stage status %r' % (status,))
    if status == 'pass' and not list(evidence_ref):
        raise QueryRefusal(
            'STAGE_PASS_WITHOUT_EVIDENCE',
            'a stage pass must cite at least one evidenceRef; an evidence-free pass is a '
            'false claim (G01 HONEST-3)', status=status)
    payload = {'status': status, 'reason': reason, 'evidenceRef': list(evidence_ref)}
    if list(evidence_sha):
        payload['evidenceSha256'] = list(evidence_sha)
    return payload


def _not_run(reason):
    return _stage('not-run', reason=reason)


def _unavailable_stages(reason):
    """The four stages a read can never assert, each carrying its own reason."""
    return {
        'saveDiff': _not_run(reason),
        'reopen': _not_run(reason),
        'runtime': _not_run(reason),
        'cleanup': _not_run(reason),
    }


def _order_stages(stages):
    """Every stage key present, in the G01 order, with nothing left undefined."""
    ordered = {}
    for name in STAGE_NAMES:
        ordered[name] = stages.get(name) or _not_run(
            'this capability does not perform this stage, so it produced no evidence for it')
    return ordered


#: How weak each stage status is.  ``_combine_stages`` keeps the weaker of two.
_STAGE_RANK = {'fail': 0, 'blocked': 1, 'not-run': 2, 'unknown': 3, 'pass': 4}


def _combine_stages(left, right, *, label_left='before', label_right='after'):
    """The weaker of two liveReadback stages, with both sides' evidence merged on pass.

    Two identical passes merge their evidenceRef rather than picking one.  Anything else is
    reported at the weaker status with both sides named, so a difference is never advertised
    as backed by a live read when one of its two reads was not.
    """
    statuses = {left['status'], right['status']}
    if statuses == {'pass'}:
        merged = sorted(set(left['evidenceRef']) | set(right['evidenceRef']))
        sha = sorted(set(left.get('evidenceSha256', [])) | set(right.get('evidenceSha256', [])))
        return _stage('pass', reason='both sides are backed reads',
                      evidence_ref=merged, evidence_sha=sha)
    weakest = min(statuses, key=lambda s: _STAGE_RANK.get(s, 2))
    reasons = ['%s: %s (%s)' % (name, side['status'], side['reason'])
               for name, side in ((label_left, left), (label_right, right))
               if side['status'] != 'pass']
    return _stage(weakest, reason='; '.join(reasons),
                  evidence_ref=sorted(set(left['evidenceRef']) | set(right['evidenceRef'])))


def observer_result_schema() -> dict:
    """The frozen injected-interface description, as data.

    A peer module (DS-08's ``operation_state``/``business_contract``, or a test) can check
    its own output against this without importing anything private.
    """
    return {
        'interfaceVersion': OBSERVER_INTERFACE_VERSION,
        'methods': {
            'count': {'argument': 'targetHandle', 'returns': 'the count layer only'},
            'observe': {'argument': 'targetHandle', 'returns': 'one decoded document'},
        },
        'keys': list(OBSERVER_RESULT_KEYS),
        'required': ['operationState', 'readMode', 'evidenceRef'],
        'operationStates': list(OPERATION_STATES),
        'readModes': list(_READ_MODES),
        'materialKeyByMethod': {'count': 'count', 'observe': 'document'},
        'note': 'extra keys are recorded in unrecognizedObserverKeys, never dropped; an '
                'unrecognized operationState is refused rather than mapped to a near miss',
    }


# --------------------------------------------------------------------------- #
# injected execution layer: validation
# --------------------------------------------------------------------------- #

def _validate_observer(observer):
    for method in ('count', 'observe'):
        if not callable(getattr(observer, method, None)):
            raise QueryRefusal(
                'OBSERVER_MISSING_METHOD',
                'the injected execution layer must provide %s()' % method, missing=method)
    return observer


def _validate_observer_result(raw, *, method, target_handle):
    """Normalize one injected result, refusing anything that cannot be trusted.

    Nothing is inferred: an unrecognized ``operationState`` is refused, and a state that
    contradicts the material it came with is refused.  A near-miss token is never rounded to
    the nearest legal one.
    """
    result = _require_mapping(raw, 'OBSERVER_RESULT_INVALID',
                              'the execution layer result for %s()' % method)
    unrecognized = sorted(set(result) - set(OBSERVER_RESULT_KEYS))
    version = result.get('interfaceVersion')
    if version is not None and version != OBSERVER_INTERFACE_VERSION:
        raise QueryRefusal(
            'OBSERVER_INTERFACE_VERSION_UNSUPPORTED',
            'the injected layer speaks another interface version; this service refuses to '
            'guess at its field meaning', observed=version,
            supported=OBSERVER_INTERFACE_VERSION)
    state = result.get('operationState')
    if state not in OPERATION_STATES:
        raise QueryRefusal(
            'OBSERVER_RESULT_UNRECOGNIZED_STATE',
            'operationState %r is not one of the six G01 operation states; a near miss must '
            'not be rounded to a legal token' % (state,),
            operationState=state, allowed=list(OPERATION_STATES))
    read_mode = result.get('readMode')
    if read_mode not in _READ_MODES:
        raise QueryRefusal('OBSERVER_RESULT_INVALID',
                           'readMode must be the string live or fixture',
                           readMode=read_mode)
    error = result.get('error')
    if error is not None:
        error = _require_mapping(error, 'OBSERVER_RESULT_INVALID', 'observer error')
    hint = result.get('nextActionHint')
    if hint is not None and hint not in NEXT_ACTIONS:
        raise QueryRefusal('OBSERVER_RESULT_INVALID',
                           'nextActionHint must be a G01 nextAction token or null',
                           nextActionHint=hint, allowed=list(NEXT_ACTIONS))
    evidence_ref = _string_list(result.get('evidenceRef'), 'OBSERVER_RESULT_INVALID',
                                'observer evidenceRef')
    material_key = 'count' if method == 'count' else 'document'
    material = result.get(material_key)
    if state == 'known-complete' and material is None:
        raise QueryRefusal(
            'OBSERVER_RESULT_CONTRADICTORY',
            '%s() reported known-complete but supplied no %r; a completed read must hand over '
            'what it produced' % (method, material_key),
            operationState=state, missing=material_key)
    if material is not None and state not in _MATERIAL_STATES:
        raise QueryRefusal(
            'OBSERVER_RESULT_CONTRADICTORY',
            '%s() supplied %r under operationState %r; material cannot exist before the read '
            'reached a terminal state' % (method, material_key, state),
            operationState=state, supplied=material_key)
    level_id = None
    identity = result.get('identity')
    if method == 'observe' and material is not None:
        identity = _require_mapping(identity, 'OBSERVER_RESULT_INVALID',
                                    'observer identity for observe()')
        handle_seen = identity.get('targetHandle')
        if handle_seen != target_handle:
            raise QueryRefusal(
                'OBSERVER_RESULT_CONTRADICTORY',
                'the observer answered for a different handle than the one asked for; '
                'answering for either would merge two reads',
                askedHandle=target_handle, answeredHandle=handle_seen)
        level_id = identity.get('levelId')
        if not _is_int(level_id) or level_id <= 0:
            raise QueryRefusal('OBSERVER_RESULT_INVALID',
                               'observer identity.levelId must be a positive integer',
                               levelId=level_id)
    return {
        'operationState': state,
        'readMode': read_mode,
        'error': None if error is None else {'code': error.get('code'),
                                             'message': error.get('message'),
                                             'detail': error.get('detail')},
        'nextActionHint': hint,
        'evidenceRef': evidence_ref,
        'materialKey': material_key,
        'material': material,
        'identity': identity,
        'levelId': level_id,
        'unrecognizedKeys': unrecognized,
    }


# --------------------------------------------------------------------------- #
# the service
# --------------------------------------------------------------------------- #

class SceneQueryService:
    """Holds what it has observed; answers pages, details and diffs from it.

    One instance per execution-layer session.  Per handle it keeps the observations taken in
    this process and answers every cursor-bound call against the CURRENT one -- see the
    module docstring's cursor policy.
    """

    def __init__(self, observer, *, held_snapshots: int = DEFAULT_HELD_SNAPSHOTS) -> None:
        self._observer = _validate_observer(observer)
        if not _is_int(held_snapshots) or held_snapshots < 2:
            raise QueryRefusal('HELD_SNAPSHOT_LIMIT_INVALID',
                               'held_snapshots must be an integer >= 2')
        self._held_limit = held_snapshots
        #: targetHandle -> list of held snapshot entries, oldest first.
        self._held: dict = {}
        #: targetHandle -> count-layer results, kept apart from projections on purpose.
        self._counts: dict = {}

    # ---------------------------------------------------------------- registry

    def held(self) -> dict:
        """Diagnostics only; not registered as a tool.  No projection content leaks here."""
        return {
            'contract': CONTRACT_ID,
            'heldSnapshots': self._held_limit,
            'handles': {
                handle: {
                    'snapshotIds': [s['snapshotId'] for s in entries],
                    'currentSnapshotId': entries[-1]['snapshotId'],
                    'readModes': sorted({s['readMode'] for s in entries}),
                    'levelIds': sorted({s['levelId'] for s in entries}),
                }
                for handle, entries in sorted(self._held.items())
            },
            'countOnlyHandles': sorted(self._counts),
        }

    def _current(self, handle):
        entries = self._held.get(handle)
        return entries[-1] if entries else None

    def _hold(self, handle, entry):
        entries = self._held.setdefault(handle, [])
        entries.append(entry)
        evicted = []
        while len(entries) > self._held_limit:
            evicted.append(entries.pop(0)['snapshotId'])
        return evicted

    # ------------------------------------------------------------- entry points

    def query_count(self, *, targetHandle, operationId=None, caseId=None) -> dict:
        """The COUNT layer: how many entities the level holds, and nothing else.

        Deliberately the same information ``mw.scene.readEntities`` answers with.  It holds
        no projection, so no later call in this service can page or diff it.
        """
        handle = _require_handle(targetHandle)
        operation_id = _operation_id(operationId, 'operationId')
        case_id = _operation_id(caseId, 'caseId')
        result = _validate_observer_result(self._call_observer('count', handle),
                                           method='count', target_handle=handle)
        level_id, session, count, evidence = self._count_layer(result)
        self._counts[handle] = {'entityCount': count.get('entityCount'), 'levelId': level_id,
                                'readMode': result['readMode'], 'evidenceRef': evidence}
        live_stage = self._live_readback_stage(
            result, evidence, readable=result['operationState'] == 'known-complete',
            trusted=True, refusal_codes=())
        return self._envelope(
            capability=self.CAP_COUNT, operationId=operation_id, caseId=case_id, handle=handle,
            level_id=level_id, session=session, result=result,
            stages={'liveReadback': live_stage}, observation_level='count-only',
            observation={
                'kind': 'entity-count',
                'entityCount': count.get('entityCount'),
                'entityCountSource': 'the native read the execution layer performed',
                'canAnswer': ['how many entities the read captured', 'reissue a fresh count'],
                'cannotAnswer': ['entity attributes', 'per-field source', 'paging', 'diff',
                                 'a completeness verdict'],
                'layerNote': 'a count is not an observation: it has no rows, no per-attribute '
                             'source, no unknown fields and no complete/truncated/trusted '
                             'verdict. Use scene.observe for a projected observation.',
                'promotable': True,
            },
            evidence_ref=evidence, object_ids=[])

    def query_observe(self, *, targetHandle, operationId=None, caseId=None, page=False,
                      cursor=None, maxItems=None, maxBytes=None) -> dict:
        """One fresh observation through the injected layer, held for later calls.

        The whole projection is retained in this process; the model gets a bounded summary
        and, with ``page=True``, one bounded page.  Rows are reachable only through
        ``query_page``/``query_detail``.
        """
        handle = _require_handle(targetHandle)
        operation_id = _operation_id(operationId, 'operationId')
        case_id = _operation_id(caseId, 'caseId')
        result = _validate_observer_result(self._call_observer('observe', handle),
                                           method='observe', target_handle=handle)

        document = result['material']
        projection = None
        level_id = None
        if document is not None:
            level_id = result['levelId']
            projection = self._project(document, result['identity'])
            if result['readMode'] == 'live' and projection['fixtureMarker'] is not None:
                raise QueryRefusal(
                    'READ_MODE_CONTRADICTS_DOCUMENT',
                    'the injected layer called this read live while the document itself '
                    'carries a fixture marker; one of the two is wrong and this service will '
                    'not pick', phase='observer', readMode=result['readMode'],
                    fixtureMarker=projection['fixtureMarker'])

        evidence = list(result['evidenceRef'])
        live_stage = self._live_readback_stage(
            result, evidence, readable=bool(projection and projection['readable']),
            trusted=bool(projection and projection['trusted']),
            refusal_codes=sorted({r['code'] for r in projection['refusals']})
            if projection else ())
        action_detail = None
        held = False
        evicted = []
        if projection is not None:
            if result['operationState'] == 'known-complete':
                evicted = self._hold(handle, self._snapshot_entry(result, projection,
                                                                 live_stage))
                held = True
            else:
                action_detail = ('this read is not held for later calls: a set that did not '
                                 'complete must not be paged or diffed as if it had')
        page_payload = None
        if page and projection is not None:
            try:
                page_payload = _observation.page_entities(
                    projection, cursor=cursor, **self._page_limits(maxItems, maxBytes))
            except _observation.ObservationError as exc:
                raise self._from_observation_error(exc, phase='cursor')
        object_ids, ids_truncated = _cap(projection['entityIds'] if projection else [],
                                         MAX_INLINE_IDS)
        envelope = self._envelope(
            capability=self.CAP_OBSERVE, operationId=operation_id, caseId=case_id,
            handle=handle, level_id=level_id,
            session=projection['session'] if projection else None, result=result,
            stages={'liveReadback': live_stage},
            observation_level='projected' if projection is not None else None,
            observation=self._summarize(projection) if projection is not None else None,
            evidence_ref=evidence, object_ids=object_ids,
            extra={'heldForLaterCalls': held,
                   'currentSnapshotId': projection['snapshotId'] if (projection and held) else None,
                   'evictedSnapshotIds': evicted,
                   'objectIdsTruncated': ids_truncated,
                   'observationNotHeldReason': action_detail,
                   'nextStep': 'call scene.page (cursor=null for the first page) or '
                               'scene.detail with this handle' if held else
                               'no observation was held; take another observation before '
                               'paging, detailing or diffing'})
        if page_payload is not None:
            envelope['page'] = page_payload
            envelope['objectIds'] = self._page_object_ids(page_payload)
        return envelope

    def query_page(self, *, targetHandle, operationId=None, caseId=None, cursor=None,
                   maxItems=None, maxBytes=None) -> dict:
        """One bounded page of the CURRENT held observation for this handle.

        ``cursor=None`` addresses offset 0.  A cursor minted for anything other than the
        current snapshot is refused by the projection (``CURSOR_SNAPSHOT_CHANGED`` /
        ``CURSOR_CONTENT_CHANGED`` / ``CURSOR_LEVEL_CHANGED`` / ``CURSOR_TAMPERED``); this
        service never retries a cursor against another held snapshot.
        """
        handle = _require_handle(targetHandle)
        operation_id = _operation_id(operationId, 'operationId')
        case_id = _operation_id(caseId, 'caseId')
        entry = self._require_observation(handle)
        projection = entry['projection']
        try:
            payload = _observation.page_entities(
                projection, cursor=cursor, **self._page_limits(maxItems, maxBytes))
        except _observation.ObservationError as exc:
            raise self._from_observation_error(exc, phase='cursor')
        return self._envelope(
            capability=self.CAP_PAGE, operationId=operation_id, caseId=case_id, handle=handle,
            level_id=projection['levelId'], session=projection['session'],
            result={'operationState': 'known-complete', 'readMode': entry['readMode'],
                    'error': None, 'nextActionHint': None,
                    'unrecognizedKeys': [], 'evidenceRef': entry['evidenceRef']},
            stages={'liveReadback': entry['liveReadback']}, observation_level='projected',
            observation=self._page_summary(payload), evidence_ref=entry['evidenceRef'],
            object_ids=self._page_object_ids(payload),
            extra={'currentSnapshotId': projection['snapshotId'],
                   'page': payload})

    def query_detail(self, *, targetHandle, entityId, operationId=None, caseId=None) -> dict:
        """One entity, keyed by the id the native read returned.

        Absence is never upgraded: when the entity is not in the set and the set is not proven
        complete, the answer says so instead of reading like a confirmed absence.
        """
        handle = _require_handle(targetHandle)
        operation_id = _operation_id(operationId, 'operationId')
        case_id = _operation_id(caseId, 'caseId')
        entry = self._require_observation(handle)
        projection = entry['projection']
        try:
            detail = _observation.get_entity(projection, entityId)
        except _observation.ObservationError as exc:
            raise self._from_observation_error(exc, phase='detail')
        size = _bytes(detail)
        if size > MAX_DETAIL_BYTES:
            raise QueryRefusal(
                'DETAIL_EXCEEDS_MAX_BYTES',
                'one entity detail exceeds the model-facing byte cap; the row is not cut, so '
                'raise the budget instead of receiving half an object', phase='detail',
                bytes=size, maxBytes=MAX_DETAIL_BYTES)
        return self._envelope(
            capability=self.CAP_DETAIL, operationId=operation_id, caseId=case_id, handle=handle,
            level_id=projection['levelId'], session=projection['session'],
            result={'operationState': 'known-complete', 'readMode': entry['readMode'],
                    'error': None, 'nextActionHint': None,
                    'unrecognizedKeys': [], 'evidenceRef': entry['evidenceRef']},
            stages={'liveReadback': entry['liveReadback']}, observation_level='projected',
            observation={
                'kind': 'entity-detail',
                'found': detail['found'],
                'entity': detail['entity'],
                'occurrences': detail.get('occurrences'),
                'absenceMeaning': detail.get('absenceMeaning'),
                'absenceReason': detail.get('absenceReason'),
                'snapshotComplete': detail['complete'],
                'snapshotTruncated': detail['truncated'],
                'bytes': size,
                'unknownFieldNote': 'unknownFields lists every declared attribute that was NOT '
                                    'read, with a reason; fieldProvenance keeps each '
                                    "attribute's own source and observation time",
            },
            evidence_ref=entry['evidenceRef'],
            object_ids=[entityId] if detail['found'] else [],
            extra={'currentSnapshotId': projection['snapshotId']})

    def query_diff(self, *, targetHandle, beforeSnapshotId=None, afterSnapshotId=None,
                   operationId=None, caseId=None) -> dict:
        """Compare two observations this instance holds, addressed by snapshotId.

        With no ids it compares the previous held snapshot against the current one and says so
        (``selectedBy``).  With fewer than two held it REFUSES rather than reporting an empty
        difference: "nothing to compare" and "nothing changed" must not look alike.
        """
        handle = _require_handle(targetHandle)
        operation_id = _operation_id(operationId, 'operationId')
        case_id = _operation_id(caseId, 'caseId')
        observations = list(self._held.get(handle) or [])
        if not observations:
            # Nothing observable is held.  If a count is, say so in those terms rather than
            # burying it under "not enough observations".
            self._require_observation(handle)
        if len(observations) < 2:
            raise QueryRefusal(
                'DIFF_NEEDS_TWO_OBSERVATIONS',
                'a difference needs two observations of this handle and this instance holds '
                '%d; take another observation and ask again' % len(observations),
                phase='diff', heldSnapshots=[e['snapshotId'] for e in observations],
                next_action='fix-input')
        if beforeSnapshotId is None and afterSnapshotId is None:
            before_entry, after_entry = observations[-2], observations[-1]
            selected_by = 'default-previous-vs-current'
        else:
            if beforeSnapshotId is None or afterSnapshotId is None:
                raise QueryRefusal(
                    'DIFF_SNAPSHOT_ID_INCOMPLETE',
                    'name both snapshots or neither; this service will not guess which side an '
                    'unpaired id meant', phase='diff')
            by_id = {e['snapshotId']: e for e in observations}
            missing = [sid for sid in (beforeSnapshotId, afterSnapshotId) if sid not in by_id]
            if missing:
                raise QueryRefusal(
                    'SNAPSHOT_NOT_HELD',
                    'these snapshots are not held by this instance (never taken here, or '
                    'evicted by the retention bound); take fresh observations instead of '
                    'comparing against a snapshot that is gone', phase='diff',
                    missing=missing, heldSnapshots=sorted(by_id))
            before_entry, after_entry = by_id[beforeSnapshotId], by_id[afterSnapshotId]
            selected_by = 'explicit'
        diff = _observation.diff_snapshots(before_entry['projection'],
                                           after_entry['projection'])
        stages = _unavailable_stages('a difference is computed from two reads; it says nothing '
                                     'about what reached the disk')
        stages['liveReadback'] = _combine_stages(before_entry['liveReadback'],
                                                 after_entry['liveReadback'])
        added, added_truncated = _cap_optional(diff.get('added'), MAX_DIFF_IDS)
        removed, removed_truncated = _cap_optional(diff.get('removed'), MAX_DIFF_IDS)
        changed_ids, changed_ids_truncated = _cap(
            sorted({c['entityId'] for c in diff['changed']}), MAX_DIFF_IDS)
        if diff['state'] == 'observed':
            result = {'operationState': 'known-complete', 'readMode': before_entry['readMode'],
                      'error': None, 'nextActionHint': None, 'unrecognizedKeys': [],
                      'evidenceRef': sorted(set(before_entry['evidenceRef']) |
                                            set(after_entry['evidenceRef']))}
        elif diff['state'] == 'unknown':
            result = {'operationState': 'outcome-unknown', 'readMode': before_entry['readMode'],
                      'error': {'code': diff['code'], 'message': diff['reason'],
                                'detail': {'unreadableSides': diff.get('unreadableSides')}},
                      'nextActionHint': None, 'unrecognizedKeys': [],
                      'evidenceRef': sorted(set(before_entry['evidenceRef']) |
                                            set(after_entry['evidenceRef']))}
        else:
            result = {'operationState': 'known-failed', 'readMode': before_entry['readMode'],
                      'error': {'code': diff['code'], 'message': diff['reason'],
                                'detail': {'entitySetRefusals': diff.get('entitySetRefusals')}},
                      'nextActionHint': None, 'unrecognizedKeys': [],
                      'evidenceRef': sorted(set(before_entry['evidenceRef']) |
                                            set(after_entry['evidenceRef']))}
        return self._envelope(
            capability=self.CAP_DIFF, operationId=operation_id, caseId=case_id, handle=handle,
            level_id=after_entry['projection']['levelId'],
            session=after_entry['projection']['session'], result=result, stages=stages,
            observation_level='projected',
            observation={
                'kind': 'snapshot-difference',
                'selectedBy': selected_by,
                'beforeSnapshotId': diff['beforeSnapshotId'],
                'afterSnapshotId': diff['afterSnapshotId'],
                'diffState': diff['state'],
                'authoritative': diff['authoritative'],
                'added': added, 'addedCount': diff['addedCount'],
                'addedTruncated': added_truncated,
                'removed': removed, 'removedCount': diff['removedCount'],
                'removedTruncated': removed_truncated,
                'changed': diff['changed'], 'changedCount': diff['changedCount'],
                'changedTruncated': diff['changedTruncated'],
                'unchangedCount': diff['unchangedCount'],
                'sameCountDifferentObjects': diff['sameCountDifferentObjects'],
                'caveats': diff['caveats'],
                'refusals': diff['refusals'],
                'counts': diff['counts'],
                'diffStateMeaning': _DIFF_STATE_MEANING[diff['state']],
            },
            evidence_ref=result['evidenceRef'],
            object_ids=sorted(set(added or []) | set(removed or []) | set(changed_ids)),
            extra={'changedIdsShown': changed_ids,
                   'changedIdsTruncated': changed_ids_truncated})

    # ------------------------------------------------------------- capabilities

    CAP_COUNT = 'scene.count'
    CAP_OBSERVE = 'scene.observe'
    CAP_PAGE = 'scene.page'
    CAP_DETAIL = 'scene.detail'
    CAP_DIFF = 'scene.diff'

    # --------------------------------------------------------------- internals

    def _call_observer(self, method, handle):
        try:
            return getattr(self._observer, method)(handle)
        except QueryRefusal:
            raise
        except Exception as exc:  # noqa: BLE001 - an injected layer must not crash a query
            raise QueryRefusal(
                'OBSERVER_CALL_FAILED',
                'the injected execution layer raised while %s() was asked for a read; nothing '
                'was interpreted from a partial result' % method,
                phase='observer', errorType=type(exc).__name__, errorMessage=str(exc)[:400])

    def _project(self, document, identity, ):
        try:
            return _observation.project_snapshot(document, identity=identity)
        except _observation.ObservationError as exc:
            raise self._from_observation_error(exc, phase='projection')

    @staticmethod
    def _from_observation_error(exc, *, phase):
        return QueryRefusal(exc.code, exc.message, phase=phase, **dict(exc.detail))

    def _require_observation(self, handle):
        entry = self._current(handle)
        if entry is None:
            if handle in self._counts:
                raise QueryRefusal(
                    'COUNT_IS_NOT_AN_OBSERVATION',
                    'the only thing held for this handle is an entity count; a count has no '
                    'rows, no per-attribute source and no completeness verdict, so it cannot '
                    'answer this call. Take an observation first.',
                    phase='layer', handle=handle, heldLayer='count-only')
            raise QueryRefusal(
                'OBSERVATION_NOT_HELD',
                'no observation of this handle is held by this service instance; a snapshot '
                'taken by another instance, or before a restart, is not yours to page',
                phase='layer', handle=handle)
        return entry

    def _count_layer(self, result):
        """Normalize the count block and move its file references into evidenceRef.

        G01 HONEST-7: a raw snapshot path is never the business answer.  It is a controlled
        reference, so it lands in ``evidenceRef`` -- deduplicated, order preserved -- and the
        count path never retains it anywhere else.
        """
        count = _require_mapping(result['material'], 'OBSERVER_RESULT_INVALID',
                                 'observer count block')
        entity_count = count.get('entityCount')
        if not _is_int(entity_count) or entity_count < 0:
            raise QueryRefusal('OBSERVER_RESULT_INVALID',
                               'count.entityCount must be a non-negative integer',
                               entityCount=entity_count)
        level_id = count.get('levelId')
        if level_id is not None and (not _is_int(level_id) or level_id <= 0):
            raise QueryRefusal('OBSERVER_RESULT_INVALID',
                               'count.levelId must be a positive integer when present',
                               levelId=level_id)
        evidence = list(result['evidenceRef'])
        for key in ('run', 'snapshotPath'):
            value = count.get(key)
            if isinstance(value, str) and value and value not in evidence:
                evidence.append(value)
        session = {k: count.get(k) for k in ('sessionPid', 'sessionCreation', 'sessionSource')}
        return level_id, session, count, evidence

    def _snapshot_entry(self, result, projection, live_stage):
        identity = result.get('identity') or {}
        sha = identity.get('receiptSha256') if isinstance(identity, Mapping) else None
        return {
            'snapshotId': projection['snapshotId'],
            'projection': projection,
            'readMode': result['readMode'],
            'evidenceRef': list(result['evidenceRef']),
            'evidenceSha256': [sha] if isinstance(sha, str) and sha else [],
            'levelId': projection['levelId'],
            'observedAt': projection['observedAt'],
            'liveReadback': live_stage,
        }

    def _live_readback_stage(self, result, evidence, *, readable, trusted, refusal_codes):
        """The one stage a read may assert, derived -- never assumed.

        Order matters.  A read that never reached the level is ``blocked`` whatever material
        mode was configured; a read still in flight is ``unknown``; material that is not a
        live read is ``not-run`` even when it is complete, because this call performs no live
        readback; a live read that produced nothing readable, or an untrustworthy identity
        set, is ``fail``; and a live read with no citable evidence cannot be a ``pass``.
        """
        identity = result.get('identity')
        receipt_sha = identity.get('receiptSha256') if isinstance(identity, Mapping) else None
        sha = [receipt_sha] if isinstance(receipt_sha, str) and receipt_sha else []
        state = result['operationState']
        if state == 'never-claimed':
            code = (result['error'] or {}).get('code') or 'OBSERVER_REFUSED'
            return _stage('blocked',
                          reason='no read reached the level: the execution layer refused with '
                                 '%s' % code, evidence_ref=evidence)
        if state in ('claimed', 'dispatched', 'outcome-unknown'):
            return _stage('unknown',
                          reason='the execution layer reports the read as %s; its outcome is '
                                 'not established' % state, evidence_ref=evidence)
        if result['readMode'] != 'live':
            extra = ('; the material it did produce reports %s'
                     % ','.join(refusal_codes)) if refusal_codes else ''
            return _stage('not-run',
                          reason='the injected execution layer served %s material, so this '
                                 'call performs no live readback%s'
                                 % (result['readMode'], extra))
        if state == 'known-failed':
            return _stage('fail',
                          reason='the read did not complete (operationState=known-failed)',
                          evidence_ref=evidence)
        if not readable:
            return _stage('fail',
                          reason='the receipt status is not one under which the reader '
                                 'produces rows' +
                                 (': ' + ','.join(refusal_codes) if refusal_codes else ''),
                          evidence_ref=evidence)
        if not trusted:
            return _stage('fail',
                          reason='the entity identity set is not trustworthy' +
                                 (': ' + ','.join(refusal_codes) if refusal_codes else ''),
                          evidence_ref=evidence)
        if not evidence:
            return _stage('unknown',
                          reason='the read is live but neither the layer nor the identity '
                                 'recorded an evidence reference, and a pass without evidence '
                                 'is a false claim (G01 HONEST-3)')
        return _stage('pass',
                      reason='one read-only native inspection whose projection reports the '
                             'entity set as %s' % ('proven complete' if readable else 'readable'),
                      evidence_ref=evidence, evidence_sha=sha)

    def _summarize(self, projection):
        ids, ids_truncated = _cap(projection['entityIds'], MAX_INLINE_IDS)
        refusals, refusals_truncated = _cap(projection['refusals'], MAX_INLINE_REFUSALS)
        return {
            'kind': 'projection-summary',
            'snapshotId': projection['snapshotId'],
            'contentDigest': projection['contentDigest'],
            'levelId': projection['levelId'],
            'observedAt': projection['observedAt'],
            'observedAtSource': projection['observedAtSource'],
            'status': projection['status'],
            'flags': projection['flags'],
            'counts': projection['counts'],
            'readable': projection['readable'],
            'complete': projection['complete'],
            'truncated': projection['truncated'],
            'trusted': projection['trusted'],
            'capturedCount': projection['capturedCount'],
            'totalCount': projection['totalCount'],
            'capacity': projection['capacity'],
            'rejectedCount': projection['rejectedCount'],
            'entityCount': len(projection['entities']),
            'entityIds': ids,
            'entityIdsTotal': len(projection['entityIds']),
            'entityIdsTruncated': ids_truncated,
            'refusals': refusals,
            'refusalCount': len(projection['refusals']),
            'refusalCodes': sorted({r['code'] for r in projection['refusals']}),
            'refusalsTruncated': refusals_truncated,
            'invalidatingRefusals': projection['invalidatingRefusals'],
            'conflicts': projection['conflicts'],
            'unsupportedAttributes': projection['unsupportedAttributes'],
            'subsystems': projection['subsystems'],
            'acceptance': projection['acceptance'],
            'observationTimes': projection['observationTimes'],
            'mixedObservationTimes': projection['mixedObservationTimes'],
            'externalBlocks': projection['externalBlocks'],
            'unrecognizedDocumentKeys': projection['unrecognizedDocumentKeys'],
            'unrecognizedIdentityKeys': projection['unrecognizedIdentityKeys'],
            'fixtureMarker': projection['fixtureMarker'],
            'completeMeaning': 'complete is true only when the receipt itself proves a whole '
                               'set; an unknown or truncated set keeps complete=false and says '
                               'why in refusals/invalidatingRefusals',
            'rowAccess': 'rows are reachable only through scene.page and scene.detail; '
                         'entityId is the only key, never a label or an index',
        }

    @staticmethod
    def _page_summary(payload):
        return {
            'kind': 'entity-page',
            'snapshotId': payload['snapshotId'],
            'contentDigest': payload['contentDigest'],
            'levelId': payload['levelId'],
            'observedAt': payload['observedAt'],
            'offset': payload['offset'],
            'returnedCount': payload['returnedCount'],
            'rowsInSnapshot': payload['rowsInSnapshot'],
            'snapshotTotalCount': payload['snapshotTotalCount'],
            'capturedCount': payload['capturedCount'],
            'complete': payload['complete'],
            'truncated': payload['truncated'],
            'truncationReason': payload['truncationReason'],
            'nextCursor': payload['nextCursor'],
            'oversizedItems': payload['oversizedItems'],
            'bytes': payload['bytes'],
            'maxItems': payload['maxItems'],
            'maxBytes': payload['maxBytes'],
            'rowCountMeaning': payload['rowCountMeaning'],
            'loadMore': payload['loadMore'],
        }

    @staticmethod
    def _page_object_ids(payload):
        return [row['entityId'] for row in payload['items'] if row['entityId'] is not None]

    @staticmethod
    def _page_limits(max_items, max_bytes):
        limits = {}
        if max_items is not None:
            limits['maxItems'] = max_items
        if max_bytes is not None:
            limits['maxBytes'] = max_bytes
        return limits

    def _envelope(self, *, capability, operationId, caseId, handle, level_id, session, result,
                  stages, observation_level, observation, evidence_ref, object_ids,
                  extra=None):
        """Assemble the G01 v1 result.  ``state`` and ``ok`` are never set independently."""
        state_key = result['operationState']
        state, default_action = _STATE_PROJECTION[state_key]
        hint = result.get('nextActionHint')
        if hint is not None and state == 'completed' and hint != 'none':
            raise QueryRefusal(
                'OBSERVER_RESULT_CONTRADICTORY',
                'the layer asks for nextAction %r on a completed operation' % (hint,),
                phase='observer')
        error = result.get('error')
        if state == 'completed' and error is not None:
            raise QueryRefusal('OBSERVER_RESULT_CONTRADICTORY',
                               'a completed read cannot also carry an error object',
                               phase='observer')
        if state != 'completed' and error is None:
            error = {'code': 'READ_NOT_COMPLETED',
                     'message': 'the execution layer reported operationState %s and supplied no '
                                'error code; this service will not invent a cause beyond the '
                                'state itself' % state_key,
                     'detail': {'operationState': state_key}}
        body = {
            'schemaVersion': SCHEMA_VERSION,
            'contract': CONTRACT_ID,
            'contractVersion': CONTRACT_VERSION,
            'contractName': 'miliastra-tool-state',
            'capabilityId': capability,
            'operationId': operationId,
            'caseId': caseId,
            'targetHandle': handle,
            'targetBinding': {
                'levelId': level_id,
                'sessionPid': (session or {}).get('sessionPid'),
                'sessionProcessCreation': (session or {}).get('sessionCreation'),
                'sessionSource': (session or {}).get('sessionSource'),
                'handleResolvedByDiscovery': True,
            },
            'state': state,
            'ok': state == 'completed',
            'isError': state != 'completed',
            'writeExecuted': False,
            'retryAttempted': False,
            'objectIds': list(object_ids),
            'changed': [],
            'failedItems': [],
            'nextAction': hint or default_action,
            'nextActionDetail': _NEXT_ACTION_DETAIL[hint or default_action],
            'observationLevel': observation_level,
            'observation': observation,
            'stages': _order_stages(stages),
            'error': None if error is None else dict(error, disposition=_DISPOSITION[state]),
            'evidenceRef': list(evidence_ref),
            'unrecognizedObserverKeys': list(result.get('unrecognizedKeys') or []),
            'limits': {
                'maxInlineIds': MAX_INLINE_IDS,
                'maxInlineRefusals': MAX_INLINE_REFUSALS,
                'maxDiffIds': MAX_DIFF_IDS,
                'maxDetailBytes': MAX_DETAIL_BYTES,
                'note': 'a list is never cut silently: exceeding one of these sets a Truncated '
                        'flag beside the true count',
            },
            'note': _CAPABILITY_NOTE[capability],
        }
        if extra:
            body.update(extra)
        return body


_DISPOSITION = {
    'rejected': 'refusal-before-dispatch',
    'pending': 'unknown-after-dispatch',
    'unknown': 'unknown-after-dispatch',
    'failed': 'failure-after-dispatch',
    'completed': None,
}

_DIFF_STATE_MEANING = {
    'observed': 'a difference was computed; authoritative only when both sets are proven '
                'complete',
    'unknown': 'a side was not readable, so added/removed are null and NOT an empty set',
    'refused': "a side's identity set is untrustworthy, or the two sides are different "
               'levels; no lists were produced',
}

_NEXT_ACTION_DETAIL = {
    'none': 'the operation is terminally complete; nothing further for it',
    'fix-input': 'a pre-dispatch refusal: correct the input or the prerequisite and submit a '
                 'NEW operationId. Nothing was written.',
    'poll-same-operation': 'query the SAME operationId; never dispatch',
    'reconcile': 'read the original receipt; never dispatch',
    'report-and-repair': 'use changed[] and failedItems[] to plan a bounded repair',
    'await-human': 'the execution layer is unavailable or blocked; a human must act. This is '
                   'the only token that asks for elevation.',
}

_CAPABILITY_NOTE = {
    'scene.count': 'a count is the count layer, not an observation: no rows, no per-attribute '
                   'source and no completeness verdict',
    'scene.observe': 'a projection of one read-only inspection. complete/truncated/trusted are '
                     'three separate verdicts and none of them says anything about the disk',
    'scene.page': 'a bounded page of one held snapshot; rowsInSnapshot indexes this snapshot, '
                  'snapshotTotalCount is what the receipt said the level held',
    'scene.detail': 'one entity keyed by the id the native read returned; unknownFields lists '
                    'every declared attribute that was NOT read',
    'scene.diff': 'a difference between two observations; authoritative only when both sets '
                  'are proven complete',
}


# --------------------------------------------------------------------------- #
# refusal -> G01 result, so a tool wrapper needs no second vocabulary
# --------------------------------------------------------------------------- #

def refusal_result(refusal, *, capabilityId='scene.query', operationId=None, caseId=None,
                   targetHandle=None, evidenceRef=()) -> dict:
    """The G01 result for a raised :class:`QueryRefusal`.

    A query writes nothing, so every refusal here is ``rejected`` with disposition
    ``refusal-before-dispatch`` and ``writeExecuted: false``.  ``nextAction`` is the refusal's
    own request, defaulting to ``fix-input``; a refusal may ask for ``await-human`` when the
    execution layer itself is the problem.
    """
    if not isinstance(refusal, QueryRefusal):  # pragma: no cover - defensive
        raise TypeError('refusal_result needs a QueryRefusal')
    error = refusal.as_error()
    return {
        'schemaVersion': SCHEMA_VERSION,
        'contract': CONTRACT_ID,
        'contractVersion': CONTRACT_VERSION,
        'contractName': 'miliastra-tool-state',
        'capabilityId': capabilityId,
        'operationId': operationId,
        'caseId': caseId,
        'targetHandle': targetHandle,
        'state': 'rejected',
        'ok': False,
        'isError': True,
        'writeExecuted': False,
        'retryAttempted': False,
        'objectIds': [],
        'changed': [],
        'failedItems': [],
        'nextAction': refusal.next_action,
        'nextActionDetail': _NEXT_ACTION_DETAIL[refusal.next_action],
        'observationLevel': None,
        'observation': None,
        'stages': _order_stages({
            'liveReadback': _not_run('the call was refused in phase %r before any read result '
                                     'could be reported: %s' % (refusal.phase, error['code'])),
        }),
        'error': error,
        'evidenceRef': list(evidenceRef),
        'unrecognizedObserverKeys': [],
        'limits': {},
        'note': 'a refusal is not an empty answer: nothing was read and nothing was written',
    }


# --------------------------------------------------------------------------- #
# the count layer applied to the EXISTING tool result
# --------------------------------------------------------------------------- #

def label_legacy_read_result(read_result, *, targetHandle=None, operationId=None,
                             caseId=None) -> dict:
    """Relabel an existing ``mw.scene.readEntities`` answer as COUNT LAYER, explicitly.

    The legacy answer is ``{ok, entityCount, run, snapshotPath, ...}``: a count that came from
    a read, plus a path to a file the model must not be handed (G01 HONEST-7).  This is the
    cheap, pure way to keep that tool honest without editing it:

    * the count becomes an ``entity-count`` observation at ``observationLevel='count-only'``;
    * the run directory and snapshot path become ``evidenceRef`` -- a controlled reference,
      not the business answer -- and ``snapshotPathWithheld`` records that they moved;
    * ``cannotAnswer`` names paging, detail and diff, so a consumer cannot read a count as an
      observation.

    A result that already carries entity rows or a projection contract is REFUSED: this is a
    one-way relabel for the count layer, never a way to smuggle an observation through it.
    """
    result = _require_mapping(read_result, 'LEGACY_RESULT_INVALID', 'legacy read result')
    if result.get('contract') == _observation.CONTRACT_ID or 'entities' in result or \
            result.get('observationLevel') == 'projected':
        raise QueryRefusal(
            'LEGACY_RESULT_CLAIMS_OBSERVATION',
            'this input already carries entity rows or a projection contract; it must be '
            'consumed as an observation, not relabelled as a count',
            phase='input', contract=result.get('contract'), hasEntities='entities' in result)
    entity_count = result.get('entityCount')
    if not _is_int(entity_count) or entity_count < 0:
        raise QueryRefusal(
            'LEGACY_RESULT_INVALID',
            'a legacy read result must carry an integer entityCount; an absent count is '
            'reported as absent, never as zero', entityCount=entity_count)
    operation_id = _operation_id(operationId, 'operationId')
    case_id = _operation_id(caseId, 'caseId')
    refs = []
    for key in ('run', 'snapshotPath'):
        value = result.get(key)
        if isinstance(value, str) and value and value not in refs:
            refs.append(value)
    ok = result.get('ok') is True
    return {
        'schemaVersion': SCHEMA_VERSION,
        'contract': CONTRACT_ID,
        'contractVersion': CONTRACT_VERSION,
        'contractName': 'miliastra-tool-state',
        'capabilityId': 'scene.count',
        'operationId': operation_id,
        'caseId': case_id,
        'targetHandle': None if targetHandle is None else _require_handle(targetHandle),
        'state': 'completed' if ok else 'rejected',
        'ok': ok,
        'isError': not ok,
        'writeExecuted': False,
        'retryAttempted': False,
        'objectIds': [],
        'changed': [],
        'failedItems': [],
        'nextAction': 'none' if ok else 'fix-input',
        'nextActionDetail': _NEXT_ACTION_DETAIL['none' if ok else 'fix-input'],
        'observationLevel': 'count-only',
        'observation': {
            'kind': 'entity-count',
            'entityCount': entity_count,
            'legacyTool': result.get('method'),
            'canAnswer': ['how many entities the read captured'],
            'cannotAnswer': ['entity attributes', 'per-field source', 'paging', 'diff',
                             'a completeness verdict'],
            'layerNote': 'relabelled from the existing read tool: a count and a snapshot path '
                         'are NOT a complete scene observation',
        },
        'snapshotPathWithheld': bool(refs),
        'stages': _order_stages({
            'liveReadback': _not_run('the legacy result does not record whether the read was '
                                     'live or which material it came from, so this relabel '
                                     'asserts nothing about it'),
        }),
        'error': None if ok else {'code': 'LEGACY_READ_NOT_OK',
                                  'message': 'the legacy read result reported ok=false',
                                  'phase': 'input',
                                  'disposition': 'refusal-before-dispatch', 'detail': {}},
        'evidenceRef': refs,
        'unrecognizedObserverKeys': [],
        'limits': {},
        'note': _CAPABILITY_NOTE['scene.count'],
    }
