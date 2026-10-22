"""D04.01.03 -- batch create that keeps each item's REAL id and repairs only the failed one.

WHY THIS EXISTS (status before this module, 2026-10-06)
======================================================
``backend/entity_server.py`` offers ONE create (``mw_scene_create_entity``) and ONE batch
route, a batch DELETE (``mw_scene_cleanup_owned``).  ``mw_scene_capabilities`` advertises
``batchLimit = MAX_BATCH`` (256) and offers no batch create at all, so the advertised limit
was a number with no entry behind it (``tools/authoring/INTERFACE-INVENTORY.md:94-97``
records the drift as ``backendHasBatch=true, unifiedHasBatch=false``).

A native batch DOES exist one layer down -- ``create-batch``, one of the five native write
verbs (``tools/editor-bridge/elevated-request.py:280``), reached through
``tools/game-executor/scene_cli.py create-batch --plan`` -> ``build_scene_profile.py``
(``HR_ACTION=3``) -- but it cannot satisfy this leaf:

  * ``build_scene_profile.validate_baseline`` refuses the WHOLE batch when any one template
    is outside the permitted set (``build_scene_profile.py:165-166``), before anything is
    dispatched.  The minimum sample is "3 placements, 1 illegal template"; the native batch
    answers it with 0 created, not 2 + 1 refused.
  * the batch receipt is ONE row (``scene_cli.py:549-562``): when ``placedCount`` does not
    match the request the WHOLE batch is marked ``outcomeUncertain``, so a single missing
    placement destroys the per-item truth.

That is the exact opposite of what this leaf requires.  ``INTERFACE-PLAN.md:27`` states the
contract: "批次逐项返回实际ID；部分成功不整批重试；保留原实体".  So the product layer must
orchestrate per-item: one reviewed native ``create`` (the single-create verb, already
journaled and idempotent) per placement, and the batch adds exactly two things the single
create does not have -- a per-item requestId namespace and a repair round that re-dispatches
ONLY the failed item.

THIS MODULE IS THE COORDINATOR.  It is pure: it opens no queue, starts no process, reads no
journal and writes no file.  ``dispatch_one`` (one per-item create) and ``prior_lookup``
(one journal read) are injected, and ``validate_item`` supplies the domain checks so this
module never re-implements ``entity_server.validate_transform`` or the template set.  The
whole module is therefore offline-testable against a faithful fake -- which is how it was
built -- and the ``entity_server`` wiring is the only place that knows about the queue, the
helper and the MCP transport.

WHAT IS REAL HERE
=================
  * ``item_request_id``   a deterministic per-(batch, item, attempt) 32-hex requestId.  The
                          requestId is the ONLY idempotency key the bottom layer has
                          (``author.py`` :229-241 claims on the directory, :238 refuses a
                          resend), so making it a pure function of the item and the attempt
                          is what makes a replay a replay and a repair a NEW operation.
  * ``normalize_create_reply``  the ONLY place that turns ``mw_scene_create_entity``'s reply
                          into the closed disposition vocabulary.  ``_ok(created=False)`` --
                          ``entity_server.py:1455-1462`` -- is a transport success carrying a
                          business failure; reading its ``ok`` as success is the defect
                          ``business_contract.STATE-1`` names, so this function reads
                          ``created`` and ``replayed``, never ``ok``.
  * ``run_batch``         dispatch every not-already-known-good item once, in order; carry a
                          known-good item forward VERBATIM (its real id, ``createdHere``
                          false) instead of re-dispatching it; refuse to resend an item whose
                          outcome is unknown.
  * ``contract_result``   the round folded into ONE v1 contract result
                          (``backend/business_contract.py``).  A partial round is
                          ``known-failed`` -> ``failed`` -> ``report-and-repair`` with the
                          per-object truth in ``changed[]`` and ``failedItems[]``, never
                          collapsed into the top-level verdict.

WHAT THIS MODULE REFUSES TO DO (fail closed, not fail soft)
===========================================================
  * resend an item whose requestId was claimed but never answered -- reconcile it first;
  * re-dispatch an item that already succeeded -- the second round's own guard, and the
    reason ``原两项不重复`` holds on the native side and not merely in local bookkeeping;
  * re-dispatch an item whose write already took effect but was not as requested
    (``CREATE_EFFECT_NOT_AS_REQUESTED``) -- its receipt, not a resend, is the answer;
  * invent an error code.  Every code this module puts on the top-level error comes from
    ``contract.json``'s ``errorTaxonomy``; a per-item code the taxonomy does not name stays
    in ``failedItems[]`` and the round's own verdict is carried by a taxonomy code.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Callable, Iterable, Mapping, Sequence

from backend import business_contract as bc

__all__ = (
    'CAPABILITY_ID', 'METHOD', 'PARTIAL_CODE', 'LAYER_CODE', 'RECONCILE_CODE',
    'PRE', 'POST', 'UNKNOWN', 'REPAIRABLE_CODES',
    'BatchInputError', 'ItemRefusal', 'item_request_id', 'normalize_create_reply',
    'check_batch_call', 'run_batch', 'contract_result',
)

CAPABILITY_ID = 'entity.create-batch'
METHOD = 'mw.scene.createBatch'

#: The four dispositions are the contract's closed set (contract.json errorTaxonomy
#: disposition.values).  This module emits three of them; ``version-gate`` belongs to the
#: compatibility guard, not to a create.
PRE = 'refusal-before-dispatch'
POST = 'failure-after-dispatch'
UNKNOWN = 'unknown-after-dispatch'

#: The taxonomy row for "a dispatch happened and did not produce what was asked"
#: (contract.json:361 -- it is the SAME row ``scene_cli.py:561`` "Batch receipt did not
#: resolve every placement" is filed under).  Its fixed disposition is
#: failure-after-dispatch and its nextAction is report-and-repair, which is precisely the
#: pair of facts a partial batch must publish.
PARTIAL_CODE = 'CREATE_EFFECT_NOT_AS_REQUESTED'
#: The row for "the execution layer could not be used" (a helper that is not running, a
#: queue that is not resolvable).  Used only as the top-level error when every per-item
#: refusal carries a code the taxonomy does not name, so the round still publishes a valid
#: envelope instead of an unclassified one.
LAYER_CODE = 'EXECUTION_LAYER_UNAVAILABLE'
#: The row for "claimed, never answered"; every unknown item must point at its own journal
#: so the caller has a reconciliation route (OPS-2).
RECONCILE_CODE = 'REQUEST_OUTCOME_UNKNOWN'
#: The row for "the request was never dispatched".  Used for an item that a previous round
#: refused before its own dispatch, so no journal exists to carry.
NEVER_DISPATCHED_CODE = 'CANCELLED_BEFORE_DISPATCH'

#: The per-item refusals a repair round may re-dispatch.  A code outside this set either
#: happened AFTER the write (its receipt, not a resend, is the answer) or does not name a
#: repairable cause; ``run_batch`` refuses to guess.
REPAIRABLE_CODES = frozenset({'TEMPLATE_NOT_SUPPORTED', 'TEMPLATE_ID_NOT_AN_INTEGER',
                              'TRANSFORM_INVALID', 'SCALE_NOT_POSITIVE',
                              'REQUEST_ID_INVALID', 'REQUEST_ID_CONFLICT',
                              'LEVEL_AT_CAPACITY', NEVER_DISPATCHED_CODE})

#: The dispatch one applyable placement.  Returns the normalized outcome this module speaks
#: (see ``normalize_create_reply``): ``{'ok', 'entityId', 'disposition', 'code',
#: 'createdHere', 'replayed', 'liveReadback', 'detail'}``.
DispatchOne = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
#: One journal read for one requestId.  ``('none', None)`` when it was never claimed,
#: ``('unknown', None)`` when it was claimed without a result, ``('receipt', <result.json>)``
#: when a receipt was published.  A binding disagreement is a refusal and must be raised.
PriorLookup = Callable[[str, Mapping[str, Any]], tuple[str, Mapping[str, Any] | None]]
#: The per-item domain check (template membership, transform legality).  Returns ``None``
#: when the item is dispatchable, or raises :class:`ItemRefusal` with a taxonomy code.
ValidateItem = Callable[[Mapping[str, Any]], None]


class BatchInputError(ValueError):
    """The BATCH call itself is malformed.  Refused as a whole, before any item runs."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class ItemRefusal(RuntimeError):
    """ONE item is not dispatchable.  It fails that item and no other."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def item_request_id(batch_id: str, item_key: str, attempt: int) -> str:
    """The requestId of one item of one batch at one attempt -- a pure function.

    Deterministic on purpose.  The bottom layer's only idempotency key is the requestId
    (``author.py`` claims on the journal directory and refuses a repeat with
    ``REQUEST_ID_CONFLICT`` / replays it), so a second call of the SAME (batch, item,
    attempt) must resolve to the SAME requestId, or a replay would mint a second entity.
    A repair is a DIFFERENT attempt and therefore a different requestId: that is the whole
    mechanism by which "补失败项" is a new operation instead of a repeat.
    """
    if not isinstance(batch_id, str) or not batch_id:
        raise BatchInputError('BATCH_ID_INVALID', 'batchId must be a non-empty string')
    if not isinstance(item_key, str) or not item_key:
        raise BatchInputError('BATCH_ITEM_KEY_INVALID', 'itemKey must be a non-empty string')
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise BatchInputError('BATCH_ATTEMPT_INVALID', 'attempt must be an integer >= 1')
    material = 'd040103:%s:%s:%d' % (batch_id, item_key, attempt)
    return hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]


def normalize_create_reply(body: Mapping[str, Any] | None, is_error: bool,
                           *, detail: str | None = None) -> dict:
    """``mw_scene_create_entity``'s reply -> this module's closed per-item outcome.

    The single-create tool has four reply shapes and they do NOT line up with
    ``result.ok``:

    ``_ok(created=True, entityId=int, replayed=False)``   a create; ``liveReadback`` is the
                                                          tool's own independent readback.
    ``_ok(created=True, entityId=int, replayed=True)``    a REPLAY of the journaled receipt;
                                                          the id is real, nothing was
                                                          dispatched by THIS call.
    ``_ok(created=False, liveReadback=fail)``             the native write was refused.
                                                          ``result.ok`` is True -- this is
                                                          STATE-1's counterexample, so it is
                                                          read as a failure here.
    ``_fail(error.code=...)``                             a refusal raised before the
                                                          dispatch, except
                                                          ``CREATE_DID_NOT_ADD_EXACTLY_ONE_ENTITY``
                                                          which is raised after the write.
    """
    body = body or {}
    if is_error:
        code = ((body.get('error') or {}).get('code')) or 'BUSINESS_ERROR'
        if code == 'CREATE_DID_NOT_ADD_EXACTLY_ONE_ENTITY':
            # Raised AFTER the write (entity_server.py:1476-1479): the level's own readback
            # disagreed with the create, so an effect may exist and must not be resent.
            return _outcome(ok=False, disposition=POST, code=PARTIAL_CODE, live_readback='fail',
                            detail=detail or 'the level did not gain exactly the entity the '
                                             'native create reported')
        # Otherwise the disposition is the code's OWN fixed one (contract.json: "disposition
        # is determined by WHERE the code is raised").  REQUEST_OUTCOME_UNKNOWN is the case
        # that matters: the inner tool raised it for a claim with no receipt, so the batch
        # must treat that item as unknown and reconcile it, never as a plain refusal.
        fixed = bc.disposition_of(code)
        disposition = fixed if fixed in (PRE, POST, UNKNOWN) else PRE
        return _outcome(ok=False, disposition=disposition,
                        code=RECONCILE_CODE if disposition == UNKNOWN else code,
                        live_readback='unknown' if disposition == UNKNOWN else 'not-run',
                        detail=detail or ((body.get('error') or {}).get('message')))
    live = body.get('liveReadback') or {}
    status = live.get('status')
    replayed = body.get('replayed') is True
    created = body.get('created')
    entity_id = body.get('entityId')
    if created is True:
        if isinstance(entity_id, bool) or not isinstance(entity_id, int):
            return _outcome(ok=False, disposition=POST, code=PARTIAL_CODE, live_readback='fail',
                            detail='the create reported success without an integer entityId, so '
                                   'no id can be carried forward')
        return _outcome(ok=True, entity_id=entity_id, created_here=not replayed, replayed=replayed,
                        live_readback=status or ('unknown' if replayed else 'pass'),
                        detail=detail or ('replayed from the journaled receipt'
                                          if replayed else None))
    if replayed:
        # A replay of an original that did not create: the outcome IS known (a receipt
        # exists), so it is an observed failure, never an unknown.
        return _outcome(ok=False, disposition=POST, code=PARTIAL_CODE, replayed=True,
                        live_readback=status or 'fail',
                        detail='the journaled original dispatch did not create this placement')
    unknown = live.get('outcomeUncertain') is True or body.get('outcomeUncertain') is True
    return _outcome(ok=False,
                    disposition=UNKNOWN if unknown else POST,
                    code=RECONCILE_CODE if unknown else PARTIAL_CODE,
                    live_readback=status or 'fail',
                    detail=(body.get('error') or live.get('reason') or
                            'the native create was refused'))


def _outcome(*, ok: bool, entity_id: int | None = None, disposition: str | None = None,
             code: str | None = None, created_here: bool = False, replayed: bool = False,
             live_readback: str | None = None, detail: str | None = None) -> dict:
    return {'ok': ok, 'entityId': entity_id, 'disposition': disposition, 'code': code,
            'createdHere': created_here, 'replayed': replayed,
            'liveReadback': live_readback, 'detail': detail}


# --------------------------------------------------------------------------- #
# Batch-call validation -- the whole call, before any item runs
# --------------------------------------------------------------------------- #

_ITEM_KEYS = ('itemKey', 'templateId', 'position', 'rotation', 'scale')


def check_batch_call(items: Sequence[Mapping[str, Any]], *, max_items: int,
                     attempt: int = 1,
                     repair_keys: Sequence[str] | None = None) -> frozenset[str] | None:
    """Refuse a malformed BATCH call as a whole.  Returns the repair key set (or None).

    A per-ITEM mistake is not a malformed batch: an illegal template fails that item and
    leaves the others alone (that is the whole point of this leaf), and the injected
    ``validate_item`` is what refuses it.  What is refused here is the batch's own shape --
    the mistakes that make a per-item readback impossible to interpret.
    """
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise BatchInputError('BATCH_ITEMS_NOT_A_LIST', 'items must be a list of placements')
    if not items:
        raise BatchInputError('BATCH_ITEMS_EMPTY', 'a batch needs at least one placement')
    if len(items) > max_items:
        raise BatchInputError('BATCH_ITEMS_OVER_LIMIT',
                              'at most %d placements per batch (got %d)' % (max_items, len(items)))
    keys = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise BatchInputError('BATCH_ITEM_NOT_AN_OBJECT',
                                  'items[%d] must be an object' % index)
        for name in ('itemKey', 'templateId', 'position'):
            if name not in item:
                raise BatchInputError('BATCH_ITEM_INCOMPLETE',
                                      'items[%d] is missing %r' % (index, name))
        key = item.get('itemKey')
        if not isinstance(key, str) or not key or len(key) > 64:
            raise BatchInputError('BATCH_ITEM_KEY_INVALID',
                                  'items[%d].itemKey must be 1..64 characters' % index)
        keys.append(key)
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        # Two placements with one itemKey would make "the item that failed" ambiguous, and
        # the repair round would not know which one its requestId belonged to.
        raise BatchInputError('BATCH_ITEM_KEYS_DUPLICATED',
                              'itemKey must be unique within a batch: %s' % duplicated)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise BatchInputError('BATCH_ATTEMPT_INVALID', 'attempt must be an integer >= 1')
    if repair_keys is None:
        if attempt != 1:
            raise BatchInputError('BATCH_REPAIR_KEYS_REQUIRED',
                                  'attempt %d must name repairKeys: a later round re-dispatches '
                                  'only the items it names, never the whole batch' % attempt)
        return None
    if isinstance(repair_keys, (str, bytes)) or not isinstance(repair_keys, Sequence):
        raise BatchInputError('BATCH_REPAIR_KEYS_NOT_A_LIST', 'repairKeys must be a list')
    if not repair_keys:
        raise BatchInputError('BATCH_REPAIR_KEYS_EMPTY',
                              'repairKeys names the items to re-dispatch; an empty list would '
                              'only carry the previous round forward with no repair')
    if attempt < 2:
        raise BatchInputError('BATCH_REPAIR_WITHOUT_ATTEMPT',
                              'repairKeys belongs to attempt >= 2; attempt 1 dispatches every '
                              'dispatchable placement')
    unknown = sorted(set(repair_keys) - set(keys))
    if unknown:
        raise BatchInputError('BATCH_REPAIR_KEY_UNKNOWN',
                              'repairKeys names items this batch does not carry: %s' % unknown)
    return frozenset(repair_keys)


# --------------------------------------------------------------------------- #
# The round
# --------------------------------------------------------------------------- #

def _receipt(item_key: str, attempt: int, request_id: str | None, outcome: Mapping[str, Any],
             result: str, *, carried: bool = False,
             attempted_here: bool = False) -> dict:
    record = {'itemKey': item_key, 'attempt': attempt, 'requestId': request_id,
              'ok': bool(outcome.get('ok')), 'entityId': outcome.get('entityId'),
              'disposition': outcome.get('disposition'), 'code': outcome.get('code'),
              'detail': outcome.get('detail'),
              'createdHere': bool(outcome.get('createdHere')),
              'replayed': bool(outcome.get('replayed')),
              'liveReadback': outcome.get('liveReadback'),
              'attemptedHere': attempted_here, 'carried': carried, 'result': result}
    return record


def _carry_from_prior(batch_id: str, item: Mapping[str, Any], attempt: int,
                      prior_lookup: PriorLookup) -> dict:
    """One item's receipt for a round that is NOT re-dispatching it.

    Walks the item's own attempts from the most recent downwards and carries the FIRST
    journal that exists, so an item that a round skipped is still found.  Its REAL id is
    preserved and ``createdHere`` is false: the id is a fact, but this call created nothing.
    """
    key = item['itemKey']
    for previous in range(attempt - 1, 0, -1):
        request_id = item_request_id(batch_id, key, previous)
        kind, detail = prior_lookup(request_id, item)
        if kind == 'none':
            continue
        if kind == 'unknown':
            return _receipt(key, previous, request_id, _outcome(
                ok=False, disposition=UNKNOWN, code=RECONCILE_CODE, live_readback='unknown',
                detail='requestId %s was claimed but its receipt was never written, so the '
                       'outcome is unknown: reconcile it, never resend it' % request_id),
                'unknown', carried=True)
        if kind != 'receipt':
            raise BatchInputError('BATCH_PRIOR_LOOKUP_INVALID',
                                 'prior_lookup returned an unrecognised kind %r' % (kind,))
        backend = (detail or {}).get('backend') or {}
        ok = (detail or {}).get('ok') is True
        entity_id = backend.get('entityId')
        has_run = bool(backend.get('run'))
        if ok and (isinstance(entity_id, bool) or not isinstance(entity_id, int)):
            return _receipt(key, previous, request_id, _outcome(
                ok=False, disposition=POST, code=PARTIAL_CODE, live_readback='fail',
                detail='the journaled receipt says the create succeeded but carries no '
                       'integer entityId, so no id can be carried forward'), 'failed',
                carried=True)
        return _receipt(key, previous, request_id, _outcome(
            ok=ok, entity_id=entity_id if ok else None,
            disposition=None if ok else POST,
            code=None if ok else PARTIAL_CODE,
            live_readback=('pass' if (ok and has_run) else ('fail' if not ok else 'unknown')),
            detail='carried forward from the journaled receipt of attempt %d; this call '
                   'dispatched nothing for it' % previous),
            'carried' if ok else 'failed', carried=True)
    return _receipt(key, attempt, None, _outcome(
        ok=False, disposition=PRE, code=NEVER_DISPATCHED_CODE, live_readback='not-run',
        detail='no prior attempt ever dispatched this item, so there is no receipt to carry: '
               'it must be named in repairKeys to be created'), 'not-attempted', carried=True)


def _latest_prior(batch_id: str, item: Mapping[str, Any], attempt: int,
                  prior_lookup: PriorLookup) -> tuple[str, Mapping[str, Any] | None]:
    """``prior_lookup`` for the newest attempt below ``attempt`` that has a journal row."""
    for previous in range(attempt - 1, 0, -1):
        kind, detail = prior_lookup(item_request_id(batch_id, item['itemKey'], previous), item)
        if kind != 'none':
            return kind, detail
    return 'none', None


def run_batch(*, batch_id: str, items: Sequence[Mapping[str, Any]], dispatch_one: DispatchOne,
              validate_item: ValidateItem, max_items: int, attempt: int = 1,
              repair_keys: Sequence[str] | None = None,
              prior_lookup: PriorLookup | None = None) -> dict:
    """Attempt every item that is not already known-good, once, in order.

    ``repair_keys`` is ``None`` for round one (every dispatchable item is attempted) and the
    named itemKeys for a later round.  In a later round every OTHER item is carried forward
    from its own journal -- its id is preserved and nothing is dispatched for it -- and a
    named item may NOT already have succeeded (that would duplicate it) or have an unknown
    outcome (that must be reconciled first).  Both refusals are batch-level: they name a
    call that would break the "no duplicate of the original two" guarantee.
    """
    repair = check_batch_call(items, max_items=max_items, attempt=attempt,
                              repair_keys=repair_keys)
    receipts: list[dict] = []
    for item in items:
        key = item['itemKey']
        if repair is not None:
            kind, detail = _latest_prior(batch_id, item, attempt, prior_lookup or _no_journal)
            if key in repair:
                # A journal directory exists only once ``author.py`` was reached, so it is
                # the proof that a dispatch left the process for this item.  Such an item is
                # reconciled from its own receipt, never resent (contract.json OPS-2); only an
                # item with NO journal -- one a round refused before its own dispatch -- is
                # "补失败项" territory, which is the minimum sample's illegal-template item.
                if kind == 'unknown':
                    raise BatchInputError(
                        'BATCH_REPAIR_OF_UNKNOWN_ITEM',
                        'item %r was dispatched without a receipt; it must be reconciled from '
                        'its requestId, never resent' % key)
                if kind == 'receipt':
                    raised = 'BATCH_REPAIR_OF_SUCCEEDED_ITEM' \
                        if (detail or {}).get('ok') is True else 'BATCH_REPAIR_OF_DISPATCHED_ITEM'
                    raise BatchInputError(
                        raised,
                        'item %r already has a journal receipt, so it was dispatched in a '
                        'previous attempt: its receipt is the answer and re-dispatching it '
                        'would either duplicate it or resend an unknown write' % key)
            else:
                receipts.append(_carry_from_prior(batch_id, item, attempt,
                                                 prior_lookup or _no_journal))
                continue
        refusal = None
        try:
            validate_item(item)
        except ItemRefusal as exc:
            refusal = exc
        if refusal is not None:
            receipts.append(_receipt(key, attempt, None, _outcome(
                ok=False, disposition=PRE, code=refusal.code, live_readback='not-run',
                detail=refusal.message), 'refused'))
            continue
        request_id = item_request_id(batch_id, key, attempt)
        outcome = dispatch_one(request_id, item)
        if outcome.get('ok') is True:
            receipts.append(_receipt(key, attempt, request_id, outcome, 'created',
                                     attempted_here=True))
        elif outcome.get('disposition') == UNKNOWN:
            receipts.append(_receipt(key, attempt, request_id, outcome, 'unknown',
                                     attempted_here=True))
        else:
            receipts.append(_receipt(key, attempt, request_id, outcome, 'failed',
                                     attempted_here=True))
    return _report(batch_id, attempt, receipts)


def _no_journal(request_id: str, item: Mapping[str, Any]) -> tuple[str, None]:
    """The default ``prior_lookup``: a wiring that names no journal can carry nothing.

    Returning ``('none', None)`` makes a later round carry nothing and refuse a repair of an
    item it cannot prove, which is the safe direction.  The production wiring always supplies
    a real lookup.
    """
    return 'none', None


def _state_of(receipts: Sequence[Mapping[str, Any]]) -> str:
    if any(r['disposition'] == UNKNOWN for r in receipts):
        return 'unknown'
    if not any(r['ok'] for r in receipts) and not any(r['attemptedHere'] or r['carried']
                                                     for r in receipts):
        return 'rejected'
    if all(r['ok'] for r in receipts):
        return 'completed'
    return 'failed'


_OPERATION_STATE = {'rejected': 'never-claimed', 'completed': 'known-complete',
                    'failed': 'known-failed', 'unknown': 'outcome-unknown'}


def _report(batch_id: str, attempt: int, receipts: Sequence[Mapping[str, Any]]) -> dict:
    state = _state_of(receipts)
    return {'batchId': batch_id, 'attempt': attempt, 'state': state,
            'operationState': _OPERATION_STATE[state],
            'receipts': list(receipts),
            'dispatchedItemKeys': [r['itemKey'] for r in receipts if r['attemptedHere']],
            'repairableKeys': [r['itemKey'] for r in receipts
                               if not r['ok'] and r['disposition'] == PRE
                               and r['code'] in REPAIRABLE_CODES]}


# --------------------------------------------------------------------------- #
# The round -> the frozen v1 result
# --------------------------------------------------------------------------- #

def _live_readback_stage(receipts: Sequence[Mapping[str, Any]]) -> dict:
    """The batch's ``liveReadback``, folded from the per-item readbacks -- never invented.

    A ``pass`` cites each item's own journal directory, so the evidence names the objects
    the claim is about.  One item without an independent readback makes the batch stage
    ``unknown`` rather than ``pass``: the count would be right and the claim would still be
    unsupported, which is the failure ``business_contract`` HONEST-3 forbids.
    """
    unknown = [r for r in receipts if r['disposition'] == UNKNOWN]
    if unknown:
        return bc.stage('unknown', reason='%d of %d placement(s) have no receipt, so the batch '
                                         'cannot be read back: %s'
                        % (len(unknown), len(receipts),
                           ', '.join(r['itemKey'] for r in unknown)))
    failed = [r for r in receipts if not r['ok']]
    if failed:
        return bc.stage('fail', reason='%d of %d placement(s) do not exist: %s'
                        % (len(failed), len(receipts), ', '.join(r['itemKey'] for r in failed)))
    unreviewed = [r for r in receipts if r['liveReadback'] != 'pass']
    if unreviewed:
        return bc.stage('unknown', reason='%d carried placement(s) have no citable readback of '
                                         'their own: %s'
                        % (len(unreviewed), ', '.join(r['itemKey'] for r in unreviewed)))
    return bc.stage('pass',
                    evidence_ref=['.runtime/authoring/requests/%s' % r['requestId']
                                 for r in receipts if r['requestId']],
                    detail={'placementCount': len(receipts),
                            'reviewed': 'each placement carries the single-create tool\'s own '
                                        'projected readback'})


def _top_error(report: Mapping[str, Any]) -> dict | None:
    """The round's ONE classified error, or None for a completed round.

    Every code here is a ``contract.json`` taxonomy code; a per-item code the taxonomy does
    not name stays in ``failedItems[]``.  The mapping is fixed by where the round's failure
    happened, not by a preference: a round that dispatched anything is
    ``failure-after-dispatch`` even when one item was refused before ITS dispatch, because
    the level was already changed by the round.
    """
    receipts = report['receipts']
    state = report['state']
    batch_id = report['batchId']
    failed = [r for r in receipts if not r['ok']]
    if state == 'completed':
        return None
    if state == 'unknown':
        first = next(r for r in receipts if r['disposition'] == UNKNOWN)
        return bc.make_error(
            RECONCILE_CODE,
            'at least one placement was dispatched without a receipt, so the batch outcome is '
            'not established; query the named requestId instead of resending the batch',
            operation_id=batch_id,
            reconcile={'operationId': first['requestId'] or batch_id,
                       'ledgerRef': '.runtime/authoring/requests/%s'
                                    % (first['requestId'] or batch_id)},
            detail={'failedItems': [{'itemKey': r['itemKey'], 'requestId': r['requestId']}
                                    for r in failed]})
    if state == 'rejected':
        code = next((r['code'] for r in failed if r['code'] in bc.frozen_sets()['codes']),
                    LAYER_CODE)
        return bc.make_error(
            code, 'no placement was dispatched, so the batch was refused before any write: ' +
                  '; '.join('%s=%s' % (r['itemKey'], r['code']) for r in failed),
            operation_id=batch_id,
            detail={'failedItems': [{'itemKey': r['itemKey'], 'code': r['code'],
                                     'disposition': r['disposition']} for r in failed]})
    return bc.make_error(
        PARTIAL_CODE,
        'the batch did not create every requested placement (%d of %d created); the created '
        'objects and the failed items are itemised in changed[] and failedItems[]'
        % (len(receipts) - len(failed), len(receipts)),
        operation_id=batch_id,
        detail={'failedItems': [{'itemKey': r['itemKey'], 'code': r['code'],
                                 'disposition': r['disposition']} for r in failed],
                'repairableKeys': report['repairableKeys']})


def contract_result(report: Mapping[str, Any], *, level_handle: str) -> dict:
    """Fold one round into ONE v1 contract result (``business_contract.result``).

    ``state``/``ok``/``nextAction``/``outcomeKnown`` are all derived by ``result()`` from the
    operation state, so a partial round cannot be published as a success: it is
    ``known-failed`` -> ``failed`` -> ``report-and-repair``, with ``changed[]`` holding the
    placements that really exist and their REAL ids and ``failedItems[]`` holding what did
    not.  ``state == 'completed'`` forbids a non-empty ``failedItems[]`` in the validator, so
    the partial truth cannot collapse into the top-level verdict either.
    """
    receipts = report['receipts']
    state = report['state']
    if state == 'rejected':
        write_executed: bool | None = False
    elif state == 'unknown':
        write_executed = None
    else:
        write_executed = True
    object_ids = [r['entityId'] for r in receipts if r['ok']]
    changed = [{'objectId': r['entityId'], 'itemKey': r['itemKey'],
                'attempt': r['attempt'], 'result': 'created' if r['createdHere'] else 'carried'}
               for r in receipts if r['ok']]
    # A rejected round dispatched nothing, and the validator forbids changed[]/failedItems[]
    # on it (OPS-3), so its per-item refusals live in error.detail instead -- where the
    # caller still gets the itemised truth without the result claiming an object.
    failed_items = [] if state == 'rejected' else [
        {'itemKey': r['itemKey'], 'attempt': r['attempt'], 'requestId': r['requestId'],
         'result': r['result'], 'code': r['code'],
         'disposition': r['disposition'], 'detail': r['detail']}
        for r in receipts if not r['ok']]
    notes = ['a partial round keeps the real id of every placement it created and, in a later '
             'attempt, carries them forward instead of re-dispatching them',
             'repairableKeys: %s' % (report['repairableKeys'],)]
    if report['attempt'] > 1:
        notes.append('this is repair attempt %d; only %s were dispatched, the rest were carried '
                     'forward from their own receipts' % (report['attempt'],
                                                          report['dispatchedItemKeys']))
    return bc.result(
        capability_id=CAPABILITY_ID, method=METHOD, operation_id=report['batchId'],
        operation_state=report['operationState'], target_handle=level_handle,
        write_executed=write_executed, object_ids=object_ids, changed=changed,
        failed_items=failed_items,
        stage_map={'liveReadback': _live_readback_stage(receipts)},
        error=_top_error(report),
        counts={'requested': len(receipts), 'created': len(object_ids),
                'failed': len(failed_items),
                'dispatchedThisAttempt': len(report['dispatchedItemKeys'])},
        notes=notes,
        replayed=bool(receipts) and all(r['replayed'] or r['carried'] for r in receipts))
