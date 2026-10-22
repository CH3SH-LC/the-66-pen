"""W15 -- bind the fixed-level CLI reopen capability to the v1 business contract.

WHY THIS EXISTS
===============
``tools/game-executor/scene_cli.py reopen-current`` is a real, working capability: it claims a
helper-owned lease, dispatches one reviewed reopen action, and writes
``reopen-dispatch.json`` / ``result.json`` next to a validated native receipt.  What it does
NOT do is speak the frozen tool-result contract in ``backend/business_contract.py``.  Its own
result is a dispatch classification (``nativeCallAttempted`` / ``nativeCallReturned`` /
``businessPending``) whose ``ok`` means *a validated dispatch receipt*, never *a completed
reopen*.  Two separate truths therefore live in two separate shapes:

  * the CLI dispatch record           -- proved by the native receipt hash;
  * the business reopen verdict       -- proved by the independent acceptance producer
                                         (``tools/game-executor/native_reopen_acceptance.py``).

This module is the adapter between them, and nothing else.  It is a PURE function library: it
opens no socket, starts no process, reads no receipt and writes no file.  Every input is an
already-parsed document supplied by the caller, so the whole module is offline-testable
against a fake backend -- which is exactly how W15 was built while W13 (reopen-inputs
producer) and W14 (helper session registry) had not yet landed.

THE FIXED-LEVEL RANGE GATE (do not delete)
==========================================
``scene_cli.py`` refuses any level other than ``1073741840``
(``REOPEN_REVIEW_AND_FIXED_LEVEL_REQUIRED``), and ``native_reopen_guards`` /
``native_reopen_result`` / ``native_reopen_acceptance`` all hard-pin ``levelId == 1073741840``.
That is not an accident to be "parameterised away"; it is the range gate that a human opened
for exactly one test level.  This adapter therefore:

  * keeps ``REOPEN_FIXED_LEVEL`` as the ONLY level the default profile permits;
  * refuses every other level with ``TOOL_UNAVAILABLE_IN_PROFILE`` unless the caller supplies
    an ``authorized_scope`` document that carries a reviewed-profile grant
    (``authorizedBy == 'coordinator'`` + a ``reviewId``).  A request can never authorise
    itself; widening the scope set is a HUMAN authorisation decision, not a technical one.

WHAT W15 DELIVERS
=================
  * ``check_bindings``       -- the consistency gate: same session / level / review / lease /
                                save original, else a classified refusal (never a silent pass).
  * ``adapt_reopen``         -- the CLI dispatch outcome -> one v1 contract result, with the
                                ``reopen`` stage reported SEPARATELY from ``liveReadback``.
  * ``poll_same_request``    -- the pending branch: query the SAME operationId; never mint a
                                new one and never re-dispatch.
  * ``normalize_inputs``     -- the seam into W13's ``reopen-inputs.json``, MEASURED against
                                the landed producer (level comes from the lease, the handle
                                level from an explicit observation).  Companion:
                                ``tools/game-executor/reopen_preflight_binding.py``.

HARD BOUNDARIES ENCODED HERE (each has a test)
==============================================
  * No initialization flag is ever written; this module is pure and the result says so.
  * ``ready`` (a preflight / dispatch receipt) is NEVER reported as ``reopened``.
  * A single playtest click is NOT accepted as evidence of a reopen.
  * The fixed-level range gate is never deleted and a request never widens it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from backend import business_contract as bc

__all__ = (
    'REOPEN_FIXED_LEVEL', 'CAPABILITY_ID', 'METHOD', 'PROFILE_ID',
    'FIXED_LEVEL_RANGE_GATE', 'REQUIRED_INPUTS', 'SESSION_FIELDS',
    'REFUSAL_CODES', 'refusals_of', 'check_bindings', 'level_scope_gate',
    'effective_level_scope', 'normalize_inputs', 'adapt_reopen',
    'poll_same_request',
)

#: The only level the default (un-reviewed) reopen profile may touch.  Derived from
#: ``scene_cli.py:659`` and the four native pin sites; quoted, not re-invented.
REOPEN_FIXED_LEVEL = 1073741840

#: capabilityId is the verb; ``method`` names the transport entry point the CLI offers.
CAPABILITY_ID = 'level.reopen-current'
METHOD = 'mw.scene.reopenCurrent'
#: Stable profile id stamped on every result, so a consumer knows which surface it speaks.
PROFILE_ID = 'reopen/tool-surface/v1'

#: The scope gate, as data.  A reviewer can read what was NOT removed instead of trusting a
#: comment: the fixed level, the fact that dynamic levels need an authorised scope, and the
#: fact that the authority is a human decision recorded in a reviewed profile.
FIXED_LEVEL_RANGE_GATE = {
    'kind': 'fixed-level-range-gate',
    'levelId': REOPEN_FIXED_LEVEL,
    'dynamicLevelsRequireAuthorizedScope': True,
    'scopeAuthority': 'reviewed-profile-human-decision',
    'note': 'the gate is a range limit a human opened for one test level; this adapter never '
            'deletes it and never lets a request widen it',
}

#: The five originals W13 must bind.  Missing any one is a refusal, never a default.
REQUIRED_INPUTS = ('requestId', 'levelId', 'session', 'review', 'lease', 'claim',
                   'sessionSha256', 'reviewSha256', 'leaseSha256', 'claimSha256',
                   'accountBaselineSha256')

#: The session identity fields (quoted from native_write_review.SESSION_FIELDS, not re-typed
#: by hand -- the constant is asserted against the CLI's list by the test suite).
SESSION_FIELDS = ('schemaVersion', 'pid', 'tid', 'window', 'windowClass', 'processCreation',
                  'threadCreation', 'image')

#: Every code this adapter may raise, and the exact reason it was chosen.  Kept as data so a
#: reviewer can challenge the mapping without reading control flow.
REFUSAL_CODES = {
    'wrong-level': 'READBACK_WRONG_LEVEL',
    'level-not-authorized': 'TOOL_UNAVAILABLE_IN_PROFILE',
    'request-id-invalid': 'REQUEST_ID_INVALID',
    'request-id-conflict': 'REQUEST_ID_CONFLICT',
    'incomplete-claim': 'REQUEST_INCOMPLETE_CLAIM',
    'review-missing': 'NATIVE_WRITE_REVIEW_REQUIRED',
    'review-not-current': 'TARGET_STALE_REVISION',
    'evidence-mismatch': 'EVIDENCE_INTEGRITY_FAILED',
    'handle-unverified': 'TARGET_HANDLE_UNVERIFIED',
    'profile-unavailable': 'TOOL_UNAVAILABLE_IN_PROFILE',
}

_HEX32 = re.compile(r'^[0-9a-f]{32}$')
_HEX64 = re.compile(r'^[0-9a-f]{64}$')
_LEVEL_SCOPE_KINDS = ('reviewed-profile-scope',)


def refusals_of(report: Mapping[str, Any]) -> list[dict]:
    """The refusal list a caller reads.  ``[]`` means the bindings are consistent."""
    return list(report.get('refusals') or [])


# --------------------------------------------------------------------------- #
# The scope gate
# --------------------------------------------------------------------------- #

def level_scope_gate() -> dict:
    """The gate as data (deep copy) so a caller cannot mutate the module constant."""
    return dict(FIXED_LEVEL_RANGE_GATE)


def effective_level_scope(authorized_scope: Mapping[str, Any] | None) -> frozenset[int]:
    """The levels this call may touch.  The fixed level is always in; nothing else by default.

    ``authorized_scope`` is a reviewed-profile grant.  It must be a
    ``reviewed-profile-scope`` document carrying a ``coordinator`` authorisation and a
    ``reviewId``; anything else is refused, because accepting an unreviewed scope would let
    the request widen its own range.  The returned set is ALWAYS a superset of the fixed
    level -- the gate is never deleted, only added to by a human decision.
    """
    scope: set[int] = {REOPEN_FIXED_LEVEL}
    if authorized_scope is None:
        return frozenset(scope)
    if not isinstance(authorized_scope, Mapping):
        raise bc.ContractViolation(['authorized_scope must be an object or None'])
    if authorized_scope.get('kind') not in _LEVEL_SCOPE_KINDS:
        raise bc.ContractViolation(['authorized_scope.kind must be one of %s'
                                    % (list(_LEVEL_SCOPE_KINDS),)])
    if authorized_scope.get('authorizedBy') != 'coordinator':
        raise bc.ContractViolation(['authorized_scope.authorizedBy must be "coordinator"; a '
                                    'scope grant is a human authorisation decision'])
    review_id = authorized_scope.get('reviewId')
    if not isinstance(review_id, str) or not review_id.strip():
        raise bc.ContractViolation(['authorized_scope.reviewId must name the reviewed profile '
                                    'that granted the wider range'])
    levels = authorized_scope.get('levels')
    if not isinstance(levels, Sequence) or isinstance(levels, (str, bytes)):
        raise bc.ContractViolation(['authorized_scope.levels must be a list of integers'])
    if len(levels) > 4096:
        # A reviewed profile grants a handful of levels, not a whole address space; an
        # oversized list is a malformed grant, and bounding it keeps a refusal report finite.
        raise bc.ContractViolation(['authorized_scope.levels carries %d entries; a reviewed '
                                    'grant is a small explicit list' % len(levels)])
    for level in levels:
        if isinstance(level, bool) or not isinstance(level, int) or not 0 < level < 2 ** 32:
            raise bc.ContractViolation(['authorized_scope.levels entries must be uint32 '
                                        'integers; got %r' % (level,)])
        scope.add(level)
    if authorized_scope.get('fixedLevelIncluded') is not True:
        raise bc.ContractViolation(['authorized_scope must state fixedLevelIncluded true; a '
                                    'scope grant may ADD levels, never remove the fixed one'])
    return frozenset(scope)


# --------------------------------------------------------------------------- #
# Refusals
# --------------------------------------------------------------------------- #

def _refusal(code: str, message: str, *, detail: dict | None = None) -> dict:
    """One pre-dispatch refusal, using the fixed or the context-dependent disposition.

    READBACK_WRONG_LEVEL is one of the three context-dependent codes, so the emitter supplies
    its disposition explicitly -- that is the whole point of the context-dependent rule.
    """
    if bc.disposition_of(code) is None:
        error = bc.make_error(code, message, disposition='refusal-before-dispatch',
                              detail=detail)
    else:
        error = bc.refusal_error(code, message, detail=detail)
    return error


def _add(refusals: list, kind: str, message: str, **detail: Any) -> None:
    refusals.append({'kind': kind, 'code': REFUSAL_CODES[kind], 'message': message,
                     'detail': detail or None})


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def _session_mismatch(review_session: Any, session: Any) -> list[str]:
    if not isinstance(review_session, Mapping) or not isinstance(session, Mapping):
        return ['<not-an-object>']
    return [field for field in SESSION_FIELDS
            if review_session.get(field) != session.get(field)]


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


# --------------------------------------------------------------------------- #
# The consistency gate
# --------------------------------------------------------------------------- #

def check_bindings(inputs: Mapping[str, Any], *, now: datetime | None = None,
                   authorized_scope: Mapping[str, Any] | None = None) -> list[dict]:
    """Every cross-document consistency rule, as a list of classified refusals.

    The five originals must agree on (requestId, levelId, session, review, lease, save).  The
    order below is the order a reviewer reads: identity, then range, then review, then lease,
    then destructuring.  It never short-circuits -- a caller fixing one field usually has more
    than one wrong, and a refusal that hides the rest is worth very little.
    """
    if not isinstance(inputs, Mapping):
        raise bc.ContractViolation(['inputs must be an object'])
    refusals: list[dict] = []

    # -- destructuring: the gate is a set, but a caller may pass None for an absent original
    present = {name: inputs.get(name) for name in REQUIRED_INPUTS}
    missing = sorted(name for name, value in present.items() if value is None)
    if missing:
        _add(refusals, 'incomplete-claim',
             'the reopen binding is missing required originals: %s' % ', '.join(missing),
             missing=missing)

    # -- request identity
    request_id = inputs.get('requestId')
    if not isinstance(request_id, str) or not _HEX32.match(request_id):
        _add(refusals, 'request-id-invalid',
             'requestId must be 32 lowercase hex characters', requestId=request_id)

    # -- range gate: the fixed level only, unless a reviewed grant says otherwise
    try:
        permitted = effective_level_scope(authorized_scope)
    except bc.ContractViolation as exc:
        _add(refusals, 'level-not-authorized', str(exc), authorizedScope=None)
        permitted = frozenset({REOPEN_FIXED_LEVEL})
    level_id = inputs.get('levelId')
    if isinstance(level_id, bool) or not isinstance(level_id, int):
        _add(refusals, 'wrong-level', 'levelId must be an integer', levelId=level_id)
        level_ok = False
    else:
        level_ok = True
        if level_id not in permitted:
            _add(refusals, 'level-not-authorized',
                 'level %r is outside this profile\'s range gate (fixed level %d); enabling a '
                 'dynamic level binding requires an authorized scope from a reviewed profile'
                 % (level_id, REOPEN_FIXED_LEVEL),
                 levelId=level_id, permitted=sorted(permitted),
                 gate=level_scope_gate())

    # -- handle: the level the observation/handle actually reported
    handle_level = inputs.get('handleLevelId')
    if handle_level is None:
        _add(refusals, 'handle-unverified',
             'handleLevelId is required: a dispatch without an observed handle level cannot be '
             'bound to a target')
    elif level_ok and handle_level != level_id:
        _add(refusals, 'wrong-level',
             'the observed handle is on level %r but the request targets %r'
             % (handle_level, level_id),
             handleLevelId=handle_level, levelId=level_id)

    # -- review: present, current, for THIS request and THIS level
    review = inputs.get('review')
    if not isinstance(review, Mapping):
        _add(refusals, 'review-missing', 'no coordinator review document was supplied')
    else:
        if (review.get('schemaVersion') != 1 or review.get('operation') != 'level.reopen-current'
                or review.get('allowedCalls') != 1):
            _add(refusals, 'review-missing',
                 'the review is not a single-call level.reopen-current review',
                 schemaVersion=review.get('schemaVersion'),
                 operation=review.get('operation'), allowedCalls=review.get('allowedCalls'))
        if review.get('requestId') != request_id:
            _add(refusals, 'request-id-conflict',
                 'the review authorises request %r, not %r'
                 % (review.get('requestId'), request_id),
                 reviewRequestId=review.get('requestId'))
        if level_ok and review.get('levelId') != level_id:
            _add(refusals, 'wrong-level',
                 'the review authorises level %r, not %r'
                 % (review.get('levelId'), level_id), reviewLevelId=review.get('levelId'))
        mismatched = _session_mismatch(review.get('session'), inputs.get('session'))
        if mismatched:
            _add(refusals, 'evidence-mismatch',
                 'the review session disagrees with the session under verification: %s'
                 % ', '.join(mismatched), fields=mismatched)
        created = _parse_time(review.get('createdUtc'))
        expires = _parse_time(review.get('expiresUtc'))
        current = now or datetime.now(timezone.utc)
        if created is None or expires is None or not (created <= current < expires):
            _add(refusals, 'review-not-current',
                 'the review is expired or its time window is invalid '
                 '(createdUtc=%r, expiresUtc=%r, now=%s)'
                 % (review.get('createdUtc'), review.get('expiresUtc'), current.isoformat()),
                 createdUtc=review.get('createdUtc'), expiresUtc=review.get('expiresUtc'))
        elif not 0 < (expires - created).total_seconds() <= 3600:
            _add(refusals, 'review-not-current',
                 'the review lifetime %r s is outside (0, 3600]'
                 % (expires - created).total_seconds())

    # -- lease / claim: two copies of one immutable record, both bound to the review + session
    lease, claim = inputs.get('lease'), inputs.get('claim')
    if not isinstance(lease, Mapping) or not isinstance(claim, Mapping):
        _add(refusals, 'incomplete-claim',
             'both the lease and its immutable claim copy are required')
    else:
        if lease.get('schema') != 1 or lease.get('action') != 'reopen-current':
            _add(refusals, 'incomplete-claim',
                 'the lease is not a schema-1 reopen-current claim',
                 schema=lease.get('schema'), action=lease.get('action'))
        if lease.get('requestId') != request_id:
            _add(refusals, 'request-id-conflict',
                 'the lease claims request %r, not %r'
                 % (lease.get('requestId'), request_id), leaseRequestId=lease.get('requestId'))
        if level_ok and lease.get('levelId') != level_id:
            _add(refusals, 'wrong-level',
                 'the lease is bound to level %r, not %r'
                 % (lease.get('levelId'), level_id), leaseLevelId=lease.get('levelId'))
        lease_sha, claim_sha = inputs.get('leaseSha256'), inputs.get('claimSha256')
        if not (_digest(lease_sha) and _digest(claim_sha)):
            _add(refusals, 'evidence-mismatch',
                 'leaseSha256 and claimSha256 must both be 64 hex characters')
        elif lease_sha != claim_sha:
            _add(refusals, 'evidence-mismatch',
                 'the lease and its immutable claim copy have different bytes '
                 '(leaseSha256 != claimSha256)', leaseSha256=lease_sha, claimSha256=claim_sha)
        review_sha = inputs.get('reviewSha256')
        if _digest(lease.get('reviewSha256')) and lease.get('reviewSha256') != review_sha:
            _add(refusals, 'evidence-mismatch',
                 'the lease pins reviewSha256 %r but the supplied review hashes to %r'
                 % (lease.get('reviewSha256'), review_sha),
                 leaseReviewSha256=lease.get('reviewSha256'), reviewSha256=review_sha)
        if _digest(lease.get('sessionSha256')) and lease.get('sessionSha256') != inputs.get(
                'sessionSha256'):
            _add(refusals, 'evidence-mismatch',
                 'the lease pins sessionSha256 %r but the supplied session hashes to %r'
                 % (lease.get('sessionSha256'), inputs.get('sessionSha256')),
                 leaseSessionSha256=lease.get('sessionSha256'),
                 sessionSha256=inputs.get('sessionSha256'))
        account_sha = inputs.get('accountBaselineSha256')
        if _digest(lease.get('accountBaselineSha256')) and \
                lease.get('accountBaselineSha256') != account_sha:
            _add(refusals, 'evidence-mismatch',
                 'the lease pins accountBaselineSha256 %r but the save original hashes to %r'
                 % (lease.get('accountBaselineSha256'), account_sha),
                 leaseAccountSha256=lease.get('accountBaselineSha256'),
                 accountBaselineSha256=account_sha)
    return refusals


# --------------------------------------------------------------------------- #
# Shape normalisation (the static W13 interface)
# --------------------------------------------------------------------------- #

def normalize_inputs(index: Mapping[str, Any], documents: Mapping[str, Any],
                     *, handle: Mapping[str, Any] | None = None) -> dict:
    """Build the adapter input from a W13 ``reopen-inputs.json`` index and parsed documents.

    MEASURED against the producer that actually landed, not assumed.  ``assemble_reopen_inputs
    .assemble`` emits exactly ``{'schemaVersion','requestId','editorPid','files','runs'}``
    (``ASSEMBLER_INDEX_SHAPE``) -- the index carries **no** ``levelId`` at all.  The original
    ``index.get('levelId')`` therefore returned ``None`` on every real index and ``check_bindings``
    refused the whole request with ``READBACK_WRONG_LEVEL`` ("levelId must be an integer"); the
    only well-formed input this seam accepted was one it had been handed by hand.

    The authoritative level is the **lease's** (``reopen-claim.json``, one of the ``files`` the
    index does carry), which ``assemble_reopen_inputs.check_lease`` has already pinned to the
    fixed level.  A top-level ``levelId`` is *refused* rather than honoured: the real index has
    none, so one could only be a second, unchecked source of truth.

    ``handleLevelId`` comes from the caller's explicit observation document.  Falling back to the
    lease -- the document the handle must be checked against -- would fabricate the very fact
    under test, so an absent observation is left absent and ``check_bindings`` raises
    ``TARGET_HANDLE_UNVERIFIED`` instead of inventing a level.

    ``tools/game-executor/reopen_preflight_binding.py`` is the measured companion of this seam:
    it destructures the real index, binds the elevated-session pointer to the lease, and is where
    a pointer whose pins/pid/creation/deadline has drifted is refused before any dispatch.
    """
    if not isinstance(index, Mapping):
        raise bc.ContractViolation(['index must be an object'])
    level_keys = sorted(name for name in ('levelId', 'handleLevelId') if name in index)
    if level_keys:
        raise bc.ContractViolation([
            'the reopen-inputs index carries no level; %s is not part of the assembler shape and '
            'the lease is the only level source' % ', '.join(level_keys)])
    files = index.get('files') or {}
    if not isinstance(files, Mapping):
        raise bc.ContractViolation(['index.files must be an object'])

    def digest_of(name: str) -> Any:
        row = files.get(name)
        return row.get('sha256') if isinstance(row, Mapping) else None

    def doc_of(name: str) -> Any:
        return documents.get(name)

    lease = doc_of('lease')
    level_id = lease.get('levelId') if isinstance(lease, Mapping) else None
    handle_level = handle.get('levelId') if isinstance(handle, Mapping) else None
    return {
        'requestId': index.get('requestId'),
        'levelId': level_id,
        'handleLevelId': handle_level,
        'session': doc_of('session'),
        'review': doc_of('review'),
        'lease': lease,
        'claim': doc_of('claim'),
        'dispatch': doc_of('dispatch'),
        'dispatchSha256': digest_of('dispatch'),
        'acceptance': doc_of('acceptance'),
        'sessionSha256': digest_of('session'),
        'reviewSha256': digest_of('review'),
        'leaseSha256': digest_of('lease'),
        'claimSha256': digest_of('claim'),
        'accountBaselineSha256': digest_of('beforeAccount'),
    }


# --------------------------------------------------------------------------- #
# The result envelope
# --------------------------------------------------------------------------- #

def _reopen_refusal_stage(refusals: Sequence[Mapping[str, Any]]) -> dict:
    return bc.stage('not-run',
                    reason='the reopen was refused before any dispatch: %s'
                           % '; '.join(r['code'] for r in refusals))


def _stage_map(reopen_stage: dict, reason_others: str) -> dict:
    return {
        'liveReadback': bc.stage('not-run', reason=reason_others),
        'saveDiff': bc.stage('not-run', reason=reason_others),
        'reopen': reopen_stage,
        'runtime': bc.stage('not-run', reason=reason_others),
        'cleanup': bc.stage('not-run', reason=reason_others),
    }


_NOT_THIS_CALL = 'this call adapts a reopen outcome; it does not perform this stage'


def adapt_reopen(inputs: Mapping[str, Any], *, now: datetime | None = None,
                 authorized_scope: Mapping[str, Any] | None = None,
                 evidence_ref: Iterable[str] = ()) -> dict:
    """Fold the CLI reopen outcome into ONE v1 contract result.

    The mapping is deliberately conservative:

    * a pre-dispatch refusal (bad bindings, or a native ``dispatch-refused-no-call``) is
      ``never-claimed`` -> ``rejected`` -> ``fix-input``; a NEW operation may be submitted;
    * a claimed-but-not-dispatched request, or a dispatch that returned, is ``dispatched`` ->
      ``pending`` -> ``poll-same-operation``.  ``ok`` is false and ``reopenVerified`` is false
      even when the native call returned: the CLI receipt proves a dispatch, not a reopen.
    * ``ready`` (a preflight) and a single playtest click are NOT evidence of a reopen and can
      never produce ``reopen: pass``.
    * only an independent acceptance document (``native_reopen_acceptance``) that binds to
      this request/lease/dispatch yields ``known-complete`` with ``reopen: pass``.

    Returns a WRAPPER ``{'adapted', 'result', 'refusals', 'reopenVerified',
    'initializationWritten', 'nextAction', 'pollOperationId'}``.  ``result`` is the frozen v1
    envelope and passes ``business_contract.validate_result`` untouched; the adapter-level
    facts that v1 has no field for stay in the wrapper, so the published result is never
    polluted with undeclared keys.
    """
    if not isinstance(inputs, Mapping):
        raise bc.ContractViolation(['inputs must be an object'])
    refusals = check_bindings(inputs, now=now, authorized_scope=authorized_scope)
    request_id = inputs.get('requestId')
    operation_id = request_id if isinstance(request_id, str) and _HEX32.match(request_id) \
        else 'reopen-unnamed'
    dispatch = inputs.get('dispatch')
    if isinstance(dispatch, Mapping) and dispatch.get('status') == 'dispatch-refused-no-call':
        _add(refusals, 'profile-unavailable',
             'the native preflight refused the call; nothing was dispatched',
             dispatchStatus=dispatch.get('status'))

    target_binding = {
        'profileId': PROFILE_ID,
        'levelId': inputs.get('levelId'),
        'requestId': request_id,
        'reviewSha256': inputs.get('reviewSha256'),
        'leaseSha256': inputs.get('leaseSha256'),
        'accountBaselineSha256': inputs.get('accountBaselineSha256'),
        'levelScope': 'fixed' if inputs.get('levelId') == REOPEN_FIXED_LEVEL else 'authorized',
        'initializationWritten': False,
    }

    if refusals:
        error = _refusal(refusals[0]['code'],
                         refusals[0]['message'],
                         detail={'profileId': PROFILE_ID,
                                 'refusals': [{'kind': r['kind'], 'message': r['message'],
                                               'detail': r['detail']} for r in refusals]})
        stage = _reopen_refusal_stage(refusals)
        result = bc.result(
            capability_id=CAPABILITY_ID, method=METHOD, operation_id=operation_id,
            operation_state='never-claimed', target_handle='reopen-%s' % operation_id,
            target_binding=target_binding, write_executed=False,
            stage_map=_stage_map(stage, _NOT_THIS_CALL), error=error,
            notes=['the reopen request was refused before dispatch; correct the input and '
                   'submit a NEW operationId'])
        return _wrap(result, refusals, reopen_verified=False)

    # -- bindings are consistent: classify the dispatch outcome ------------------ #
    dispatch_state = None if not isinstance(dispatch, Mapping) else dispatch.get('status')
    acceptance = inputs.get('acceptance')

    if dispatch_state in (None, 'claimed'):
        # No terminal dispatch record yet: claimed, awaiting the helper.  Poll the SAME id.
        operation_state = 'claimed'
        reopen_stage = bc.stage(
            'not-run', reason='no dispatch record exists yet; the claim is outstanding, so the '
                              'reopen has not been attempted')
        note = 'claimed but not dispatched; query the SAME operationId, never a new one'
    elif dispatch_state in ('dispatch-returned-business-pending',
                            'dispatch-uncertain-business-pending'):
        acceptance_ok, acceptance_reason = _acceptance_verdict(acceptance, inputs)
        if acceptance_ok:
            operation_state = 'known-complete'
            references = list(evidence_ref) or ['.runtime/game-executor/reopen-reviews/%s/'
                                                'reopen-acceptance.json' % operation_id]
            reopen_stage = bc.stage('pass', evidence_ref=references,
                                    detail={'acceptance': 'independent-verifier',
                                            'dispatchStatus': dispatch_state})
            note = 'the independent acceptance verifier confirmed the roundtrip'
        else:
            operation_state = 'dispatched'
            reopen_stage = bc.stage(
                'blocked',
                reason='a dispatch receipt is not a reopen; business acceptance is pending '
                       '(%s)' % acceptance_reason)
            note = 'dispatch returned; business pending; poll the SAME operationId'
    else:
        operation_state = 'outcome-unknown'
        reopen_stage = bc.stage(
            'unknown', reason='unrecognised dispatch status %r' % (dispatch_state,))
        note = 'the dispatch status is not recognised; read the original receipt'

    if operation_state == 'known-complete':
        error = None
        write_executed = True
    elif operation_state == 'outcome-unknown':
        error = bc.make_error('REQUEST_OUTCOME_UNKNOWN',
                              'the reopen outcome could not be established from the supplied '
                              'documents', operation_id=operation_id,
                              reconcile={'operationId': operation_id,
                                         'ledgerRef': '.runtime/game-executor/reopen-reviews/%s'
                                                      % operation_id})
        write_executed = None
    else:
        error = None
        write_executed = None

    result = bc.result(
        capability_id=CAPABILITY_ID, method=METHOD, operation_id=operation_id,
        operation_state=operation_state, target_handle='reopen-%s' % operation_id,
        target_binding=target_binding, write_executed=write_executed,
        stage_map=_stage_map(reopen_stage, _NOT_THIS_CALL), error=error, notes=[note])
    return _wrap(result, (), reopen_verified=operation_state == 'known-complete')


def _wrap(result: dict, refusals: Iterable[Mapping[str, Any]], *, reopen_verified: bool) -> dict:
    """The adapter-level wrapper around a strictly contract-valid v1 result.

    ``reopenVerified`` is derived from the operation state and nothing else, and
    ``initializationWritten`` is a constant False because this module is pure: it has no code
    path that could write an initialization flag.  ``pollOperationId`` names the SAME id a
    pending caller must query.
    """
    state = result.get('state')
    return {
        'adapted': state != 'rejected',
        'result': result,
        'refusals': [dict(r) for r in refusals],
        'reopenVerified': bool(reopen_verified),
        'initializationWritten': False,
        'nextAction': result.get('nextAction'),
        'pollOperationId': result.get('operationId') if state == 'pending' else None,
    }


def _acceptance_verdict(acceptance: Any, inputs: Mapping[str, Any]) -> tuple[bool, str]:
    """Is the supplied acceptance document a real, correctly-bound reopen verdict?

    A ``ready`` preflight, a dispatch receipt, a boolean or a playtest click is NOT.  The only
    accepted document is a schema-2 ``level.reopen-current`` acceptance whose verified flags and
    whose request, level, lease AND dispatch digests all bind to this binding.  The dispatch
    digest is what makes the packet THIS dispatch's: the real producer
    (``tools/game-executor/native_reopen_acceptance.py``) stamps ``dispatchSha256``, so an
    acceptance minted for an earlier dispatch of the same request/lease is a stale packet and is
    refused.  Fail closed: with no dispatch digest on either side, no verdict is reported.
    """
    if acceptance is None:
        return False, 'no independent acceptance document was supplied'
    if isinstance(acceptance, bool) or not isinstance(acceptance, Mapping):
        return False, 'acceptance must be the verifier document, not a boolean or a click'
    if acceptance.get('schema') != 2 or acceptance.get('operation') != 'level.reopen-current':
        return False, 'acceptance is not a schema-2 level.reopen-current verdict'
    if acceptance.get('scope') != 'fixed-1839-reopen-roundtrip':
        return False, 'acceptance scope %r is not the fixed-level roundtrip' % (
            acceptance.get('scope'),)
    if acceptance.get('requestId') != inputs.get('requestId'):
        return False, 'acceptance names a different requestId'
    if acceptance.get('levelId') != inputs.get('levelId'):
        return False, 'acceptance names a different levelId'
    if acceptance.get('leaseSha256') != inputs.get('leaseSha256'):
        return False, 'acceptance names a different lease'
    dispatch_sha = inputs.get('dispatchSha256')
    if not _digest(dispatch_sha):
        return False, ('no dispatch digest is bound to this request, so the acceptance '
                       'cannot be shown to belong to THIS dispatch')
    if acceptance.get('dispatchSha256') != dispatch_sha:
        return False, ('the acceptance was minted for a different dispatch (%r, not %r); an '
                       'old response packet is not evidence of this reopen'
                       % (acceptance.get('dispatchSha256'), dispatch_sha))
    if acceptance.get('businessVerified') is not True or \
            acceptance.get('reopenRoundtripVerified') is not True:
        return False, 'acceptance does not carry businessVerified + reopenRoundtripVerified'
    return True, 'accepted'


# --------------------------------------------------------------------------- #
# The pending branch
# --------------------------------------------------------------------------- #

def poll_same_request(inputs: Mapping[str, Any], *, requested_operation_id: str | None = None
                      ) -> dict:
    """The ONLY legal move for a pending reopen: query the SAME operationId.

    If the caller names a different operation id it is refused with ``REQUEST_ID_CONFLICT``
    (``never dispatch``), because a pending reopen that is re-sent under a fresh id is exactly
    the double-dispatch this contract exists to prevent.  This function never dispatches; it
    returns the poll plan for the caller's transport.
    """
    request_id = inputs.get('requestId')
    if not isinstance(request_id, str) or not _HEX32.match(request_id):
        raise bc.ContractViolation(['requestId must be 32 lowercase hex characters'])
    if requested_operation_id is not None and requested_operation_id != request_id:
        error = bc.refusal_error(
            'REQUEST_ID_CONFLICT',
            'a pending reopen must be polled under its ORIGINAL operationId; a new id would '
            're-dispatch the same request',
            detail={'originalRequestId': request_id,
                    'requestedOperationId': requested_operation_id})
        return {'ok': False, 'action': 'poll-same-operation', 'requestId': request_id,
                'dispatch': False, 'dispatchAttempted': False, 'retryAttempted': False,
                'mustNotMintNewOperationId': True, 'error': error}
    return {'ok': True, 'action': 'poll-same-operation', 'requestId': request_id,
            'operationId': request_id, 'dispatch': False, 'dispatchAttempted': False,
            'retryAttempted': False, 'mustNotMintNewOperationId': True}
