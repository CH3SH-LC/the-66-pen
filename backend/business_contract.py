"""T05 -- the one business result and error contract.  Pure offline; no dispatch, no game.

WHY THIS EXISTS
---------------
The same chain carried four different state vocabularies and one error shape that could
not express "I do not know".  A write that had already reached the disk was reported with
every stage ``not-run`` -- literally "nothing happened" -- because ``backend/entity_server
._fail`` served both sides of the dispatch boundary.  And an ``isError=false`` reply with
``created=false`` was read by drivers as success.  This module is the single place that
turns those into one closed vocabulary, and it refuses to emit a result that lies.

SINGLE SOURCE OF TRUTH
----------------------
Every closed set here is *loaded* from ``plugins/miliastra/contracts/contract.json`` (the
G01 machine-readable fact source, itself checked by ``contracts/validate.py``).  Nothing is
re-typed.  If the contract drifts, ``frozen_sets()`` fails loudly instead of quietly
maintaining a second copy of the truth.

THE INTERFACE OTHER WORKERS BUILD ON  (T02 / T03 / T04 / T06 / T07 / T09 / T10)
-------------------------------------------------------------------------------
    business_state(operation_state: str) -> str            # total, dict lookup
    reconcile_state(operation_state: str) -> str           # total, dict lookup
    next_action_for(business_state: str) -> str            # total, dict lookup
    disposition_of(code: str) -> str | None                # None == context-dependent
    make_error(code, message, *, disposition=None, phase=None, target=None,
               operation_id=None, reconcile=None, upstream=None, detail=None) -> dict
    stage(status, *, evidence_ref=(), reason=None, detail=None,
          evidence_sha256=()) -> dict
    blank_stages() -> dict
    result(*, capability_id, method, operation_id, operation_state, ...) -> dict
    validate_result(instance) -> list[str]                 # [] == valid; never raises
    normalize_legacy(legacy, *, save_diff=None) -> dict    # entity_server shape -> v1
    render_for_model(instance) -> (model_body, evidence_index)

Every one of those is a pure function.  ``validate_result`` is the gate: it returns the
list of contract violations rather than raising, so a caller can decide, and it is what
the tests assert on.

REFUSAL SEMANTICS (what a caller may conclude from each state)
--------------------------------------------------------------
    rejected   pre-dispatch refusal or version gate.  writeExecuted is false, changed[]
               and failedItems[] are empty, and the error disposition is one of
               refusal-before-dispatch / version-gate.  Nothing was dispatched, so the
               only correct next move is to fix the input and submit a NEW operationId.
    pending    claimed or dispatched, no terminal receipt yet.  Query the SAME operation;
               never dispatch again.  outcomeKnown is false.
    unknown    the outcome cannot be established.  writeExecuted is null (not false --
               "not established" and "did not happen" are different claims).  The error
               MUST carry error.reconcile, because an unknown without a reconciliation
               route leaves the caller no legal move but a blind resend.
    failed     a terminal, observed business failure.  May be partial: changed[] and
               failedItems[] carry the per-object truth and must not collapse into the
               top-level verdict.
    completed  this operation met its own stated completion condition -- and nothing
               wider.  ``ok`` is derived, never supplied.

Sample (a completed create; abridged):

    {
      "contractVersion": "1", "capabilityId": "entity.create",
      "method": "mw.scene.createEntity", "operationId": "op-1",
      "state": "completed", "operationState": "known-complete", "outcomeKnown": true,
      "writeExecuted": true, "targetHandle": "20261002-...",
      "objectIds": [1077936133],
      "changed": [{"objectId": 1077936133, "result": "created",
                   "fields": {"templateId": 20001034}}],
      "failedItems": [], "counts": {"entityCountBefore": 17, "entityCountAfter": 18},
      "stages": {"liveReadback": {"status": "pass", "evidenceRef": ["..."]},
                 "saveDiff": {"status": "not-run", "reason": "nothing was saved", "evidenceRef": []},
                 "reopen": {...}, "runtime": {...}, "cleanup": {...}},
      "error": null, "nextAction": "none",
      "retryAttempted": false, "replayed": false, "ok": true
    }

HARD RULES ENFORCED HERE (each has a test)
------------------------------------------
  * ``ok == (state == 'completed')`` and ``outcomeKnown == (state not in {pending,unknown})``.
  * a stage ``pass`` needs at least one evidenceRef; every non-pass needs a reason.
  * a stage evidenceRef must be a project-relative reference, never an absolute path --
    the model sees tokens, the raw location stays in the internal evidence index.
  * ``nativeStatus == 0`` is an execution fact, NOT a ``saveDiff`` pass.  A save ACK with
    no independent differential normalises to ``saveDiff=blocked``, never to ``pass``.
  * a protocol success with a business failure is still a business failure; ``isError``
    and ``state`` never substitute for one another.
  * the removed catch-all ``BUSINESS_ERROR`` is rejected, not translated.
  * ``retryAttempted`` is always false; no layer here retries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / 'plugins' / 'miliastra' / 'contracts' / 'contract.json'
TOOL_RESULT_SCHEMA = ROOT / 'plugins' / 'miliastra' / 'contracts' / 'schemas' / 'tool-result.schema.json'

#: The one contract version this module emits.  A string, not an integer: persisted
#: records carry the integer ``schemaVersion`` and the two are different things (C-6).
CONTRACT_VERSION = '1'

#: Keys a tool result may carry besides the required envelope.  Deliberately the schema's
#: own optional set, so ``result()`` cannot drift into emitting an undeclared field.
OPTIONAL_RESULT_KEYS = ('caseId', 'targetBinding', 'created', 'saved', 'deleted',
                        'counts', 'backendKind', 'notes')

#: Input aliases accepted for exactly one contract version and NEVER emitted (C-1/C-2/C-7).
INPUT_STAGE_ALIASES = {'persistence': 'saveDiff'}
INPUT_STAGE_STATUS_ALIASES = {'failed': 'fail', 'not_run': 'not-run'}
INPUT_FIELD_ALIASES = {'levelHandle': 'targetHandle', 'requestId': 'operationId'}

#: The code that G01 removed.  It is not translated; it is a contract violation.
REMOVED_CODES = frozenset({'BUSINESS_ERROR'})

_SETS_CACHE: dict[str, Any] = {}


class ContractViolation(ValueError):
    """A result that must not be published.  Carries every violation, not just the first."""

    def __init__(self, violations: Sequence[str]):
        self.violations = list(violations)
        super().__init__('; '.join(self.violations) or 'contract violation')


# --------------------------------------------------------------------------- #
# The closed sets, loaded from the G01 contract (not re-typed)
# --------------------------------------------------------------------------- #

def _contract() -> dict:
    if 'contract' not in _SETS_CACHE:
        _SETS_CACHE['contract'] = json.loads(CONTRACT_PATH.read_text(encoding='utf-8-sig'))
    return _SETS_CACHE['contract']


def frozen_sets() -> dict:
    """The closed sets, read from the contract every process, cached once.

    Raises ``ContractViolation`` if the contract cannot supply them: a missing fact source
    must stop the caller, never silently fall back to a private copy of the vocabulary.
    """
    if 'sets' in _SETS_CACHE:
        return _SETS_CACHE['sets']
    contract = _contract()
    try:
        operation_state = list(contract['operationState']['values'])
        business_state_values = list(contract['businessState']['values'])
        reconcile_state_values = list(contract['reconcileState']['projection'])
        stage_names = list(contract['stages']['values'])
        stage_status = list(contract['stages']['statusValues'])
        next_action = list(contract['nextAction']['values'])
        disposition = list(contract['errorTaxonomy']['disposition']['values'])
        side_effect = sorted(set(contract['errorTaxonomy']['disposition']['sideEffect'].values()))
        codes = {row['code']: row for row in contract['errorTaxonomy']['codes']}
    except (KeyError, TypeError) as exc:
        raise ContractViolation(['contract.json is missing %r' % (exc,), ]) from None
    sets = {
        'operationState': operation_state,
        'businessState': business_state_values,
        'reconcileState': reconcile_state_values,
        'stages': stage_names,
        'stageStatus': stage_status,
        'nextAction': next_action,
        'disposition': disposition,
        'sideEffect': side_effect,
        'codes': codes,
        'sideEffectFor': dict(contract['errorTaxonomy']['disposition']['sideEffect']),
        'nextActionForBusiness': dict(contract['businessState']['nextActionFor']),
    }
    _SETS_CACHE['sets'] = sets
    return sets


def _projection(kind: str) -> dict:
    """Invert a contract projection (target value -> [source values]) into source -> target.

    The contract states ``businessState.projection.rejected == ['never-claimed']``; the
    function we need is the other direction.  Inverting the stored table -- rather than
    hand-writing the map -- is what keeps this module from becoming a second truth.
    """
    table = _contract()[kind]['projection']
    inverted: dict[str, str] = {}
    for target, sources in table.items():
        for source in sources:
            if source in inverted:
                raise ContractViolation(['%s projection maps %r twice' % (kind, source)])
            inverted[source] = target
    set_key = {'businessState': 'operationState', 'reconcileState': 'operationState'}[kind]
    missing = sorted(set(frozen_sets()[set_key]) - set(inverted))
    if missing:
        raise ContractViolation(['%s projection does not totalise over %s: %s'
                                 % (kind, set_key, missing)])
    return inverted


def _mapping(kind: str) -> dict:
    if kind not in _SETS_CACHE:
        _SETS_CACHE[kind] = _projection(kind)
    return _SETS_CACHE[kind]


def business_state(operation_state: str) -> str:
    """operationState -> the model-facing ``state``.  Total; unknown input raises."""
    return _mapping('businessState')[operation_state]


def reconcile_state(operation_state: str) -> str:
    """operationState -> T06's read-time reconcile verdict.  A projection, not a truth."""
    return _mapping('reconcileState')[operation_state]


def next_action_for(state: str) -> str:
    """businessState -> the closed ``nextAction`` token."""
    return frozen_sets()['nextActionForBusiness'][state]


def is_error_state(state: str) -> bool:
    """``isError`` is the complement of completed.  It is transport, not the verdict."""
    return state != 'completed'


def disposition_of(code: str) -> str | None:
    """The fixed disposition for a code, or None when it is context-dependent.

    Three codes (READBACK_FAILED, READBACK_WRONG_LEVEL, READBACK_NOT_ACCEPTED) return None
    and MUST have their disposition and phase supplied by the emitting call site.
    """
    row = frozen_sets()['codes'].get(code)
    if row is None:
        return None
    return row.get('disposition')


def taxonomy_next_action(code: str) -> str | None:
    row = frozen_sets()['codes'].get(code)
    return row.get('nextAction') if row else None


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #

_WINDOWS_ABSOLUTE = re.compile(r'[A-Za-z]:[\\/][^\s\'"]*')
_POSIX_ABSOLUTE = re.compile(r'(?<![\w.])/(?:[\w.\-]+/)+[\w.\-]+')

#: Identity shapes, quoted from the two request/result schemas rather than re-invented.
_OPERATION_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')
_CAPABILITY_ID = re.compile(r'^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$')


def is_absolute_path(value: str) -> bool:
    """True for a host-absolute path.  A project-relative reference is not one."""
    return (bool(len(value) > 1 and value[1] == ':' and value[0].isalpha())
            or value.startswith('/') or value.startswith('\\\\'))


def _check_evidence_ref(reference: Any, *, model_facing: bool = False) -> str | None:
    if not isinstance(reference, str) or not reference:
        return 'evidenceRef entries must be non-empty strings'
    if model_facing and is_absolute_path(reference):
        return ('evidenceRef %r is a host-absolute path; the model-facing body carries a token '
                'and the raw location stays in the internal evidence index' % reference)
    return None


def stage(status: str, *, evidence_ref: Iterable[str] = (), reason: str | None = None,
          detail: dict | None = None, evidence_sha256: Iterable[str] = (),
          model_facing: bool = False) -> dict:
    """One stage record, validated on construction.

    ``pass`` requires at least one evidenceRef.  Every other status requires a reason.
    ``not-run`` means "this call does not perform this stage" and must never be smuggled in
    to mean "it failed" -- an unreadable piece of evidence is ``unknown``.

    The internal record may cite a raw location; ``model_facing=True`` (or
    ``render_for_model``) is what forbids a host-absolute path from reaching the model.
    """
    sets = frozen_sets()
    if status not in sets['stageStatus']:
        raise ContractViolation(['stage status %r is not in %s' % (status, sets['stageStatus'])])
    references = list(evidence_ref)
    payload: dict[str, Any] = {'status': status, 'evidenceRef': references}
    problems = [p for p in (_check_evidence_ref(r, model_facing=model_facing) for r in references) if p]
    if status == 'pass' and not references:
        problems.append('a pass with no evidenceRef is an unsupported claim (HONEST-3)')
    if status != 'pass' and not (isinstance(reason, str) and reason.strip()):
        problems.append('stage %r needs a reason explaining why it is not a pass (HONEST-3)' % status)
    if reason is not None:
        payload['reason'] = reason
    if detail is not None:
        payload['detail'] = detail
    if evidence_sha256:
        digests = list(evidence_sha256)
        if any(not (isinstance(d, str) and len(d) == 64) for d in digests):
            problems.append('evidenceSha256 entries must be 64 hex characters')
        payload['evidenceSha256'] = digests
    if problems:
        raise ContractViolation(problems)
    return payload


def blank_stages(reason: str = 'this call does not perform this stage') -> dict:
    return {name: stage('not-run', reason=reason) for name in frozen_sets()['stages']}


def not_run(stage_name: str, reason: str) -> dict:
    return stage('not-run', reason=reason)


def stages_from(mapping: dict) -> dict:
    """Build the five stages from a partial mapping, filling the rest as not-run.

    ``persistence`` is accepted as an input alias for ``saveDiff`` for one contract version
    and is NEVER emitted (C-1).  ``failed`` is an input alias for ``fail`` (C-2).
    """
    sets = frozen_sets()
    problem: list[str] = []
    for key in mapping:
        canonical = INPUT_STAGE_ALIASES.get(key, key)
        if canonical not in sets['stages']:
            problem.append('stage key %r is not one of %s' % (key, sets['stages']))
    if problem:
        raise ContractViolation(problem)
    built: dict[str, dict] = {}
    for name in sets['stages']:
        alias = next((a for a, target in INPUT_STAGE_ALIASES.items() if target == name), None)
        source = mapping.get(name)
        if source is None and alias is not None:
            source = mapping.get(alias)
        if source is None:
            built[name] = stage('not-run', reason='this call does not perform this stage')
            continue
        source = dict(source)
        raw_status = source.pop('status', 'not-run')
        status = INPUT_STAGE_STATUS_ALIASES.get(raw_status, raw_status)
        evidence = source.pop('evidenceRef', source.pop('evidence', []))
        built[name] = stage(status, evidence_ref=evidence,
                            reason=source.pop('reason', None), detail=source.pop('detail', None),
                            evidence_sha256=source.pop('evidenceSha256', ()))
        if source:
            raise ContractViolation(['stage %r carries undeclared keys %s' % (name, sorted(source))])
    return built


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

def make_error(code: str, message: str, *, disposition: str | None = None,
               phase: str | None = None, target: str | None = None,
               operation_id: str | None = None, reconcile: dict | None = None,
               upstream: dict | None = None, detail: dict | None = None) -> dict:
    """One classified error.  The disposition fixes the side effect and the phase.

    A context-dependent code has no fixed disposition, so the emitting call site must pass
    one; passing one for a fixed-disposition code is a violation, not an override.
    """
    sets = frozen_sets()
    problems: list[str] = []
    if code in REMOVED_CODES:
        problems.append('%s was removed by G01 D34: it erased the phase and reported every '
                        'stage as not-run' % code)
    if code not in sets['codes']:
        problems.append('%r is not a top-level code; an upstream code belongs in '
                        'error.upstream.code' % code)
    fixed = disposition_of(code)
    if fixed is None and code in sets['codes']:
        if disposition not in (sets['codes'][code].get('allowedDispositions') or []):
            problems.append('%s is context-dependent: the emitter must supply one of %s'
                            % (code, sets['codes'][code].get('allowedDispositions')))
    elif fixed is not None:
        if disposition is not None and disposition != fixed:
            problems.append('%s has the fixed disposition %r; an emitter may not override it'
                            % (code, fixed))
        disposition = fixed
    if disposition is not None and disposition not in sets['disposition']:
        problems.append('disposition %r is not in %s' % (disposition, sets['disposition']))
    side_effect = sets['sideEffectFor'].get(disposition)
    expected_phase = 'before-dispatch' if side_effect == 'none' else 'after-dispatch'
    if phase is not None and phase != expected_phase:
        problems.append('disposition %r implies phase %r, not %r'
                        % (disposition, expected_phase, phase))
    phase = expected_phase
    if disposition == 'unknown-after-dispatch' and not isinstance(reconcile, dict):
        problems.append('an unknown-after-dispatch error must carry error.reconcile '
                        '(operationId + ledgerRef); otherwise the caller can only resend blindly')
    if reconcile is not None and reconcile:
        for key in ('operationId', 'ledgerRef'):
            if not isinstance(reconcile.get(key), str) or not reconcile.get(key):
                problems.append('error.reconcile.%s must be a non-empty string' % key)
    if problems:
        raise ContractViolation(problems)
    payload: dict[str, Any] = {'code': code, 'disposition': disposition, 'phase': phase,
                               'sideEffect': side_effect, 'message': message}
    if target is not None:
        payload['target'] = target
    if operation_id is not None:
        payload['operationId'] = operation_id
    if reconcile is not None:
        payload['reconcile'] = reconcile
    if upstream is not None:
        layers = ['business', 'ledger', 'queue-client', 'queue-runner', 'native-cli',
                  'native-probe', 'bridge']
        if upstream.get('layer') not in layers or not upstream.get('code'):
            raise ContractViolation(['error.upstream needs {layer in %s, code}' % layers])
        payload['upstream'] = upstream
    if detail is not None:
        payload['detail'] = detail
    return payload


def refusal_error(code: str, message: str, **extra) -> dict:
    """A pre-dispatch refusal.  Raises if the code cannot mean 'nothing was dispatched'."""
    error = make_error(code, message, **extra)
    if error['disposition'] not in ('refusal-before-dispatch', 'version-gate'):
        raise ContractViolation(['%s cannot be used as a pre-dispatch refusal' % code])
    return error


def unknown_error(code: str, message: str, *, reconcile: dict, **extra) -> dict:
    """An after-dispatch unknown.  A reconcile route is mandatory, hence not optional here."""
    return make_error(code, message, disposition='unknown-after-dispatch', reconcile=reconcile, **extra)


# --------------------------------------------------------------------------- #
# The result envelope
# --------------------------------------------------------------------------- #

def result(*, capability_id: str, method: str, operation_id: str, operation_state: str,
           target_handle: str | None = None, target_binding: dict | None = None,
           case_id: str | None = None, write_executed: bool | None = None,
           object_ids: Sequence[int] = (), changed: Sequence[dict] = (),
           failed_items: Sequence[dict] = (), stage_map: dict | None = None,
           error: dict | None = None, counts: dict | None = None,
           notes: Sequence[str] = (), replayed: bool = False,
           **optional: Any) -> dict:
    """Assemble and validate a v1 tool result.  ``ok``/``state``/``nextAction`` are derived.

    ``operation_state`` is the authoritative input.  ``state``, ``ok``, ``outcomeKnown`` and
    ``nextAction`` are computed from it, so a caller cannot report a completed operation as
    a failure or claim a known outcome it does not have.
    """
    sets = frozen_sets()
    if operation_state not in sets['operationState']:
        raise ContractViolation(['operationState %r is not in %s'
                                 % (operation_state, sets['operationState'])])
    state = business_state(operation_state)
    payload: dict[str, Any] = {
        'contractVersion': CONTRACT_VERSION,
        'capabilityId': capability_id,
        'method': method,
        'operationId': operation_id,
        'caseId': case_id,
        'state': state,
        'operationState': operation_state,
        'reconcileState': reconcile_state(operation_state),
        'outcomeKnown': state not in ('pending', 'unknown'),
        'writeExecuted': write_executed,
        'targetHandle': target_handle,
        'objectIds': list(object_ids),
        'changed': list(changed),
        'failedItems': list(failed_items),
        'stages': stages_from(stage_map or {}),
        'error': error,
        'nextAction': next_action_for(state),
        'retryAttempted': False,
        'replayed': bool(replayed),
        'ok': state == 'completed',
    }
    if target_binding is not None:
        payload['targetBinding'] = target_binding
    if counts is not None:
        payload['counts'] = counts
    if notes:
        payload['notes'] = list(notes)
    undeclared = sorted(set(optional) - set(OPTIONAL_RESULT_KEYS))
    if undeclared:
        raise ContractViolation(['result() got undeclared fields %s; the envelope is closed'
                                 % undeclared])
    payload.update(optional)
    violations = validate_result(payload)
    if violations:
        raise ContractViolation(violations)
    return payload


def validate_result(instance: dict, *, model_facing: bool = False) -> list[str]:
    """Every contract rule, as a list of violations.  Never raises; [] means publishable.

    Stricter than the JSON schema on purpose: the schema cannot express "an unknown must
    carry an error", because the disposition check inside ``then`` is vacuous when the error
    is null.  A schema that accepts everything is not a gate, so the real gate is here.

    ``model_facing=True`` additionally forbids a host-absolute path anywhere the model can
    read it.  The internal record legitimately carries raw locations; the projection does not.
    """
    problems: list[str] = []
    sets = frozen_sets()
    if not isinstance(instance, dict):
        return ['the result must be an object']

    missing = sorted(_REQUIRED_KEYS - set(instance))
    if missing:
        problems.append('required keys missing: %s -- a result is never published with holes '
                        'in it' % missing)
    extra = sorted(set(instance) - set(_envelope_keys()))
    if extra:
        problems.append('undeclared keys %s (the envelope is closed)' % extra)

    if instance.get('contractVersion') != CONTRACT_VERSION:
        problems.append('contractVersion must be the string %r' % CONTRACT_VERSION)

    operation_id = instance.get('operationId')
    if not isinstance(operation_id, str) or not _OPERATION_ID.match(operation_id):
        problems.append('operationId %r must match %s' % (operation_id, _OPERATION_ID.pattern))
    capability = instance.get('capabilityId')
    if not isinstance(capability, str) or not _CAPABILITY_ID.match(capability):
        problems.append('capabilityId %r must match %s' % (capability, _CAPABILITY_ID.pattern))
    handle = instance.get('targetHandle')
    if isinstance(handle, str) and any(c in handle for c in '/\\:'):
        problems.append('targetHandle %r contains a path separator; a handle is never a path'
                        % handle)

    state = instance.get('state')
    operation_state = instance.get('operationState')
    if state not in sets['businessState']:
        problems.append('state %r is not in %s' % (state, sets['businessState']))
    if operation_state is not None and operation_state not in sets['operationState']:
        problems.append('operationState %r is not in %s' % (operation_state, sets['operationState']))
    if state in sets['businessState'] and operation_state in sets['operationState']:
        expected = business_state(operation_state)
        if state != expected:
            problems.append('state %r is not the projection of operationState %r (expected %r)'
                            % (state, operation_state, expected))
        if instance.get('ok') is not (state == 'completed'):
            problems.append('ok must equal (state == "completed") (STATE-1)')
        if instance.get('outcomeKnown') is not (state not in ('pending', 'unknown')):
            problems.append('outcomeKnown must be false exactly for pending and unknown')
        if instance.get('nextAction') != next_action_for(state):
            problems.append('nextAction %r does not match state %r (%r)'
                            % (instance.get('nextAction'), state, next_action_for(state)))
    if instance.get('retryAttempted') is not False:
        problems.append('retryAttempted is always false (IDEM-8)')

    if operation_state is not None and state in sets['businessState']:
        expected_reconcile = reconcile_state(operation_state)
        if instance.get('reconcileState') not in (None, expected_reconcile):
            problems.append('reconcileState %r is not the projection of %r'
                            % (instance.get('reconcileState'), operation_state))

    for name in sets['stages']:
        record = (instance.get('stages') or {}).get(name)
        if not isinstance(record, dict):
            problems.append('stages.%s is missing' % name)
            continue
        status = record.get('status')
        if status not in sets['stageStatus']:
            problems.append('stages.%s.status %r is not in %s'
                            % (name, status, sets['stageStatus']))
            continue
        references = record.get('evidenceRef')
        if not isinstance(references, list):
            problems.append('stages.%s.evidenceRef must be a list' % name)
        else:
            problems += ['stages.%s.%s' % (name, p)
                         for p in (_check_evidence_ref(r, model_facing=model_facing)
                                   for r in references) if p]
            if status == 'pass' and not references:
                problems.append('stages.%s is pass with no evidenceRef (HONEST-3)' % name)
        if status != 'pass' and not (isinstance(record.get('reason'), str)
                                     and record['reason'].strip()):
            problems.append('stages.%s is %r with no reason (HONEST-3)' % (name, status))
        if status == 'pass' and name == 'saveDiff':
            evidence = record.get('detail') or {}
            if evidence.get('saveInvocationAckOnly') is True:
                problems.append('stages.saveDiff is pass on an ACK alone: nativeStatus==0 is an '
                                'execution fact, not a saved-content differential (D12)')
    for name in set(instance.get('stages') or {}) - set(sets['stages']):
        problems.append('stages.%s is not one of the five stages (C-1)' % name)

    # STATE-2 (R19): a success-shaped boolean is derived from state and counted evidence.
    # ``saved`` is the save-shaped one.  An ACK-derived ``saved=true`` sitting next to a
    # differential that did not pass is the exact display this rule forbids.
    _saved = instance.get('saved')
    # MAIN-LINE FIX (round 135, from the R19 review's hard-defect finding).  This used to be
    #     ((instance.get('stages') or {}).get('saveDiff') or {}).get('status')
    # ``or {}`` rescues a FALSY saveDiff but not a TRUTHY NON-DICT one, so a stage shaped
    # ``"blocked"`` / ``[1]`` / ``5`` reached ``.get`` and raised AttributeError out of
    # ``validate_result`` -- which is documented "Never raises; [] means publishable" (:492).
    # A malformed stage must be a FINDING, not an exception.  ``None`` below makes both
    # STATE-2 rules fire, so the instance is refused rather than crashing the validator.
    _save_diff = (instance.get('stages') if isinstance(instance.get('stages'), dict)
                  else {}).get('saveDiff')
    _save_diff_status = _save_diff.get('status') if isinstance(_save_diff, dict) else None
    if _saved is True and _save_diff_status != 'pass':
        problems.append('saved is true while stages.saveDiff is %r: a success-shaped boolean '
                        'must be derived from the differential, not the dispatch ack '
                        '(STATE-2/D12)' % _save_diff_status)
    if _saved is True and state != 'completed':
        problems.append('saved is true with state %r: STATE-2 requires saved === true only '
                        'when state is completed' % state)
    if _saved is False and _save_diff_status != 'fail':
        problems.append('saved is false while stages.saveDiff is %r: a save may be reported '
                        'false only when the differential proves nothing reached the disk '
                        '(STATE-2/D12)' % _save_diff_status)
    error = instance.get('error')
    if state == 'completed' and error is not None:
        problems.append('a completed result must carry error null')
    if state == 'completed' and instance.get('failedItems'):
        problems.append('a completed result carrying failedItems[] is a contradiction: partial '
                        'failure must not collapse into a completed verdict')
    if state == 'failed' and not isinstance(error, dict):
        problems.append('a failed result must carry an error object')
    if state == 'rejected':
        if instance.get('writeExecuted') is not False:
            problems.append('a rejected result must state writeExecuted false (OPS-3)')
        if instance.get('changed'):
            problems.append('a rejected result may not carry changed[] (OPS-3)')
        if instance.get('failedItems'):
            problems.append('a rejected result may not carry failedItems[] (OPS-3)')
        if isinstance(error, dict) and error.get('disposition') not in \
                ('refusal-before-dispatch', 'version-gate'):
            problems.append('a rejected result must carry a pre-dispatch or version-gate '
                            'disposition, not %r' % (error or {}).get('disposition'))
    if state == 'unknown':
        if not isinstance(error, dict):
            problems.append('an unknown result must carry an error object (an unknown without '
                            'an error carries no reconciliation route)')
        elif error.get('disposition') != 'unknown-after-dispatch':
            problems.append('an unknown result must carry an unknown-after-dispatch error')
        elif not isinstance(error.get('reconcile'), dict):
            problems.append('an unknown result must carry error.reconcile (OPS-2)')
    if isinstance(error, dict):
        problems += _validate_error(error)
    elif error is not None:
        problems.append('error must be an object or null')
    return problems


def _envelope_keys() -> set:
    return {'contractVersion', 'capabilityId', 'method', 'operationId', 'caseId', 'targetHandle',
            'targetBinding', 'state', 'operationState', 'reconcileState', 'outcomeKnown',
            'writeExecuted', 'created', 'saved', 'deleted', 'objectIds', 'changed', 'failedItems',
            'counts', 'stages', 'error', 'nextAction', 'nextActionDetail', 'retryAttempted',
            'replayed', 'ok', 'backendKind', 'notes'}


#: The keys every published result carries.  ``operationState`` is optional on the wire
#: (the schema does not require it) but is required in practice here, so its absence is
#: reported by the projection cross-check rather than by this set.
_REQUIRED_KEYS = frozenset({'contractVersion', 'capabilityId', 'method', 'operationId', 'state',
                            'outcomeKnown', 'writeExecuted', 'targetHandle', 'objectIds', 'changed',
                            'failedItems', 'stages', 'error', 'nextAction', 'retryAttempted',
                            'replayed', 'ok'})


def validate_evidence_binding(instance: dict, *, operation_id: str, case_id: str | None = None,
                              evidence_index: dict | None = None,
                              sibling_operation_ids: Iterable[str] = (),
                              expired_refs: Iterable[str] = ()) -> list[str]:
    """Does every cited piece of evidence actually belong to THIS operation?

    A stage pass is only meaningful if the evidence it cites is this operation's own.  The
    convention this project already follows on disk is that evidence lives inside an
    operation-scoped directory (``.runtime/authoring/requests/<requestId>`` and
    ``.runtime/game-executor/mcp-business/<requestId>``), so a reference must name the
    operationId, and it must not name a sibling one.  Three failure modes are refused here:

    * a reference to a DIFFERENT operation (the cross-level / cross-case mix-up);
    * a reference to a superseded observation (``expired_refs``);
    * a case-bound call citing evidence taken outside its case.
    """
    problems: list[str] = []
    index = evidence_index or {}
    expired = set(expired_refs)
    siblings = [s for s in sibling_operation_ids if s and s != operation_id]
    for name, record in (instance.get('stages') or {}).items():
        if not isinstance(record, dict):
            continue
        for reference in record.get('evidenceRef') or []:
            raw = index.get(reference, reference)
            if not isinstance(raw, str):
                continue
            if reference in expired:
                problems.append('stages.%s cites %r, an observation that has been superseded'
                                % (name, reference))
                continue
            cited_sibling = next((other for other in siblings if other in raw), None)
            if cited_sibling is not None:
                problems.append('stages.%s cites %r, which belongs to operation %r, not %r'
                                % (name, raw, cited_sibling, operation_id))
                continue
            if operation_id and operation_id not in raw:
                problems.append('stages.%s cites %r, which is not bound to operation %r'
                                % (name, raw, operation_id))
    if case_id:
        for name, record in (instance.get('stages') or {}).items():
            if isinstance(record, dict) and record.get('status') == 'pass':
                references = record.get('evidenceRef') or []
                if references and not any(case_id in index.get(r, r) for r in references):
                    problems.append('stages.%s passes inside case %r but its evidence names no '
                                    'part of that case' % (name, case_id))
    return problems


def _validate_error(error: dict) -> list[str]:
    problems: list[str] = []
    sets = frozen_sets()
    code = error.get('code')
    if code in REMOVED_CODES:
        problems.append('%s was removed by G01 D34' % code)
    if code not in sets['codes']:
        problems.append('error.code %r is not a top-level code' % code)
    disposition = error.get('disposition')
    if disposition not in sets['disposition']:
        problems.append('error.disposition %r is not in %s' % (disposition, sets['disposition']))
    fixed = disposition_of(code) if code in sets['codes'] else None
    if fixed is not None and disposition != fixed:
        problems.append('error.code %s fixes disposition %r, not %r' % (code, fixed, disposition))
    if fixed is None and code in sets['codes'] and disposition not in \
            (sets['codes'][code].get('allowedDispositions') or []):
        problems.append('error.code %s is context-dependent; %r is not one of its allowed '
                        'dispositions %s' % (code, disposition,
                                             sets['codes'][code].get('allowedDispositions')))
    side_effect = sets['sideEffectFor'].get(disposition)
    if error.get('sideEffect') != side_effect:
        problems.append('error.sideEffect %r does not follow from disposition %r (must be %r)'
                        % (error.get('sideEffect'), disposition, side_effect))
    phase = 'before-dispatch' if side_effect == 'none' else 'after-dispatch'
    if error.get('phase') != phase:
        problems.append('error.phase %r does not follow from disposition %r (must be %r)'
                        % (error.get('phase'), disposition, phase))
    if disposition == 'unknown-after-dispatch':
        if not isinstance(error.get('reconcile'), dict):
            problems.append('an unknown-after-dispatch error must carry error.reconcile (OPS-2)')
    if not isinstance(error.get('message'), str) or not error['message'].strip():
        problems.append('error.message must be a non-empty string')
    if isinstance(error.get('upstream'), dict):
        layers = ['business', 'ledger', 'queue-client', 'queue-runner', 'native-cli',
                  'native-probe', 'bridge']
        if error['upstream'].get('layer') not in layers:
            problems.append('error.upstream.layer %r is not one of %s'
                            % (error['upstream'].get('layer'), layers))
    elif error.get('upstream') is not None:
        problems.append('error.upstream must be an object or absent')
    return problems


# --------------------------------------------------------------------------- #
# Legacy normalisation -- entity_server's CURRENT shape -> v1
# --------------------------------------------------------------------------- #

#: The five keys the current server emits, mapped onto the canonical stage names.
_LEGACY_STAGE_KEYS = ('liveReadback', 'persistence', 'reopen', 'runtime', 'cleanup')

#: The old server's stages carry no evidenceRef; a pass there is a status word alone.
_LEGACY_ACK_DETAIL = 'native save status 0 on the target level'


def _legacy_detail(value: Any) -> dict | None:
    """The old shape sometimes put a sentence where the schema wants an object."""
    if value is None or isinstance(value, dict):
        return value
    return {'legacyDetail': value}


def _legacy_stage_to_v1(name: str, record: dict | None, *, save_diff: dict | None) -> dict:
    record = record or {}
    status = INPUT_STAGE_STATUS_ALIASES.get(record.get('status'), record.get('status', 'not-run'))
    canonical = INPUT_STAGE_ALIASES.get(name, name)
    if canonical != 'saveDiff':
        references = [r for r in (record.get('evidenceRef') or [])]
        if status == 'pass' and not references:
            # The old shape had no evidenceRef field.  A pass with nothing to cite is not a
            # pass here; downgrade to unknown rather than invent a reference.
            return stage('unknown', reason='the legacy receipt recorded %r but named no evidence, '
                                           'so the claim cannot be re-checked' % status,
                         detail=_legacy_detail(record.get('detail')))
        try:
            return stage(status, evidence_ref=references, reason=record.get('reason')
                         or ('legacy status %r' % status if status != 'pass' else None),
                         detail=_legacy_detail(record.get('detail')))
        except ContractViolation as exc:
            return stage('unknown', reason='legacy stage could not be normalised: %s' % exc)
    # --- saveDiff: the ACK trap (D12) ---------------------------------------- #
    if status != 'pass':
        return stage('fail' if status == 'fail' else status,
                     reason=record.get('reason') or 'the legacy save stage reported %r' % status,
                     detail=record.get('detail'))
    verified = (save_diff or {}).get('verdict')
    if verified == 'pass' and (save_diff or {}).get('evidenceRef'):
        return stage('pass', evidence_ref=save_diff['evidenceRef'],
                     detail={'saveInvocation': (save_diff or {}).get('saveInvocation'),
                             'savedContent': (save_diff or {}).get('savedContent'),
                             'allowedDelta': (save_diff or {}).get('allowedDelta'),
                             'unrelatedUnchanged': (save_diff or {}).get('unrelatedUnchanged'),
                             'legacyDetail': record.get('detail')})
    return stage('blocked',
                 reason='the legacy receipt reports %r from the native save call, which is an '
                        'execution fact; no independent content differential was supplied, so '
                        'saveDiff is not a pass (D12)' % (record.get('detail') or status),
                 detail={'saveInvocationAckOnly': True, 'legacyDetail': record.get('detail'),
                         'independentDifferential': bool(save_diff)})


def normalize_legacy(legacy: dict, *, save_diff: dict | None = None,
                     operation_id: str | None = None, capability_id: str | None = None,
                     method: str | None = None) -> dict:
    """Translate the entity_server shape into v1 WITHOUT ever promoting a claim.

    Two things this must get right:

    * **The ACK is not a differential.**  The old server marks ``persistence`` pass on
      ``nativeStatus == 0`` alone.  That is an execution fact.  Without an independent
      differential (``save_diff``) the stage becomes ``blocked``, never ``pass``.
    * **A post-dispatch failure is not a refusal.**  The old ``_fail`` produced one shape --
      every stage not-run, no phase -- for both a pre-dispatch refusal and a failure
      observed after the write.  The disposition in the taxonomy decides which; an
      ``unknown-after-dispatch`` code becomes ``unknown`` and is given a reconcile route.
    """
    problems: list[str] = []
    operation_id = operation_id or legacy.get('requestId')
    state_source = legacy.get('state')
    error = legacy.get('error')
    code = None
    if isinstance(error, dict):
        code = error.get('code')
    elif isinstance(error, str):
        # A bare string is a message, not a code claim -- unless the taxonomy already knows
        # it, in which case it is the code the old server happened to put there.
        code = error if error in frozen_sets()['codes'] else None
    stage_map = {name: legacy.get(name) for name in _LEGACY_STAGE_KEYS if legacy.get(name) is not None}
    rebuilt = {INPUT_STAGE_ALIASES.get(n, n): _legacy_stage_to_v1(n, r, save_diff=save_diff)
               for n, r in stage_map.items()}

    if code is not None:
        if code in REMOVED_CODES:
            raise ContractViolation([
                'the legacy result carries %s, the catch-all G01 removed (D34); it cannot be '
                'translated because it does not record which side of the dispatch boundary it '
                'was raised on' % code])
        if code not in frozen_sets()['codes']:
            # An unrecognised string is not silently discarded: report it as a violation of
            # the closed taxonomy so the emitter is fixed rather than the evidence.
            problems.append('error code %r is not in the closed taxonomy' % code)
        ledger_ref = legacy.get('journal') or ('.runtime/authoring/requests/%s' % operation_id
                                               if operation_id else '')
        upstream = _legacy_upstream(error)
        detail = _legacy_extra(error)
        disposition = disposition_of(code) if code in frozen_sets()['codes'] else None
        context_dependent = disposition is None and code in frozen_sets()['codes']
        if context_dependent:
            # The legacy shape never recorded the phase.  Choosing for it would be exactly
            # the defect being fixed, so the honest answer is unknown.
            operation_state = 'outcome-unknown'
            rebuilt['liveReadback'] = stage(
                'unknown', reason='legacy %s is context-dependent and the old shape recorded no '
                                  'phase, so which side of the dispatch boundary it happened on '
                                  'cannot be established from this record' % code)
            error = make_error(code, _legacy_message(legacy, error),
                               disposition='unknown-after-dispatch',
                               operation_id=operation_id, upstream=upstream, detail=detail,
                               reconcile={'operationId': operation_id or '', 'ledgerRef': ledger_ref})
        elif disposition in ('refusal-before-dispatch', 'version-gate'):
            operation_state = 'never-claimed'
            error = make_error(code, _legacy_message(legacy, error), operation_id=operation_id,
                               upstream=upstream, detail=detail)
        elif disposition == 'unknown-after-dispatch':
            operation_state = 'outcome-unknown'
            error = make_error(code, _legacy_message(legacy, error), operation_id=operation_id,
                               upstream=upstream, detail=detail,
                               reconcile={'operationId': operation_id or '', 'ledgerRef': ledger_ref})
        else:  # failure-after-dispatch
            operation_state = 'known-failed'
            error = make_error(code, _legacy_message(legacy, error), operation_id=operation_id,
                               upstream=upstream, detail=detail)
    elif state_source in frozen_sets()['operationState']:
        operation_state = state_source
    elif legacy.get('ok') is True:
        operation_state = 'known-complete'
    else:
        operation_state = 'outcome-unknown'
        error = make_error('UPSTREAM_PENDING',
                           'the legacy result reported neither a terminal state nor a '
                           'classified error, so the outcome is not established',
                           operation_id=operation_id,
                           reconcile={'operationId': operation_id or '',
                                      'ledgerRef': legacy.get('journal') or ''})

    object_ids = list(legacy.get('objectIds') or [])
    changed = list(legacy.get('changed') or [])
    failed_items = list(legacy.get('failedItems') or [])
    entity_id = legacy.get('entityId')
    if entity_id is not None and operation_state == 'known-complete' and not changed:
        changed = [{'objectId': int(entity_id), 'result': 'created', 'fields': None}]
        object_ids = object_ids or [int(entity_id)]
    write_executed = legacy.get('writeExecuted')
    if write_executed is None:
        if operation_state == 'never-claimed':
            write_executed = False
        elif operation_state in ('claimed', 'dispatched', 'outcome-unknown'):
            write_executed = None
        else:
            write_executed = bool(legacy.get('created') or legacy.get('saved')) or None

    # R19 / STATE-2: ``saved`` is a success-shaped boolean, so it is derived from the
    # differential and never forwarded from the legacy dispatch ack (which is a dispatch
    # fact).  ``rebuilt['saveDiff']`` is the one projection of that differential: pass ->
    # true, fail -> false, anything unproven (blocked/unknown/not-run) -> null.
    _save_diff_status = (rebuilt.get('saveDiff') or {}).get('status')
    saved_value = True if _save_diff_status == 'pass' else (
        False if _save_diff_status == 'fail' else None)
    built = result(capability_id=capability_id or legacy.get('capabilityId') or 'entity.create',
                   method=method or legacy.get('method') or 'mw.scene.unknown',
                   operation_id=operation_id or 'unnamed',
                   operation_state=operation_state,
                   target_handle=legacy.get('levelHandle') or legacy.get('targetHandle'),
                   object_ids=object_ids, changed=changed, failed_items=failed_items,
                   stage_map=rebuilt, error=error, replayed=bool(legacy.get('replayed')),
                   write_executed=write_executed,
                   caseId=legacy.get('caseId'), created=legacy.get('created'),
                   saved=saved_value)
    if problems:
        raise ContractViolation(problems)
    return built


def _legacy_message(legacy: dict, error: Any) -> str:
    if isinstance(error, dict) and error.get('message'):
        return str(error['message'])
    if isinstance(error, str):
        return error
    return 'the legacy result reported %s' % (legacy.get('error') or 'an error')


def _legacy_extra(error: Any) -> dict | None:
    if not isinstance(error, dict):
        return None
    extra = {k: v for k, v in error.items() if k not in ('code', 'message', 'upstream')}
    return extra or None


def _legacy_upstream(error: Any) -> dict | None:
    """Lift a legacy error.upstream into the contract's own upstream slot (D35)."""
    if not isinstance(error, dict):
        return None
    upstream = error.get('upstream')
    if isinstance(upstream, dict) and upstream.get('layer') and upstream.get('code'):
        return {'layer': upstream['layer'], 'code': upstream['code'],
                'message': upstream.get('message')}
    return None


# --------------------------------------------------------------------------- #
# Model-facing render: tokens in, raw locations out
# --------------------------------------------------------------------------- #

def evidence_token(reference: str) -> str:
    """A stable, non-resolving token for one evidence reference."""
    return 'evidence:' + hashlib.sha256(reference.encode('utf-8')).hexdigest()[:16]


def render_for_model(instance: dict) -> tuple[dict, dict]:
    """The model-facing body plus the internal evidence index.

    The model sees stage statuses, reasons and tokens.  The raw evidence locations -- which
    on this project are absolute Windows paths -- stay in the index, which the caller keeps.
    ``error.code`` survives, because it is the actionable part a model must be able to read.
    """
    violations = validate_result(instance)
    if violations:
        raise ContractViolation(violations)
    body = copy.deepcopy(instance)
    index: dict[str, str] = {}
    for name, record in body['stages'].items():
        tokens = []
        for reference in record.get('evidenceRef') or []:
            if is_absolute_path(reference):
                token = evidence_token(reference)
                index[token] = reference
                tokens.append(token)
            else:
                tokens.append(reference)   # a project-relative reference is already safe
        record['evidenceRef'] = tokens
        if isinstance(record.get('reason'), str):
            record['reason'] = redact(record['reason'], index)
    if isinstance(body.get('error'), dict) and isinstance(body['error'].get('message'), str):
        body['error']['message'] = redact(body['error']['message'], index)
    if isinstance(body.get('nextActionDetail'), str):
        body['nextActionDetail'] = redact(body['nextActionDetail'], index)
    if isinstance(body.get('notes'), list):
        body['notes'] = [redact(n, index) if isinstance(n, str) else n for n in body['notes']]
    problems = validate_result(body, model_facing=True)
    if problems:  # a redaction that left a raw path behind is a bug, not a warning
        raise ContractViolation(problems)
    return body, index


def redact(text: str, index: dict) -> str:
    """Replace absolute paths in free text with evidence tokens, keeping the text readable."""
    def swap(match):
        token = evidence_token(match.group(0))
        index[token] = match.group(0)
        return token
    return _POSIX_ABSOLUTE.sub(swap, _WINDOWS_ABSOLUTE.sub(swap, text))


# --------------------------------------------------------------------------- #
# Small helpers the other workers asked for
# --------------------------------------------------------------------------- #

def finite_vector(value: Any, *, name: str = 'vector') -> list[float]:
    """A three-component finite vector.  JSON booleans are not numbers here."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ContractViolation(['%s must be exactly three numbers' % name])
    out = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)) \
                or not math.isfinite(component):
            raise ContractViolation(['%s must contain only finite numbers (a JSON bool is not '
                                     'a number)' % name])
        out.append(float(component))
    return out


def payload_digest(payload: dict) -> str:
    """sha256 of the canonical encoding -- the same encoder the ledger fingerprint uses."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


__all__ = [
    'CONTRACT_VERSION', 'ContractViolation', 'TOOL_RESULT_SCHEMA',
    'blank_stages', 'business_state', 'disposition_of', 'evidence_token', 'finite_vector',
    'frozen_sets', 'is_error_state', 'make_error', 'next_action_for', 'normalize_legacy',
    'not_run', 'payload_digest', 'reconcile_state', 'redact', 'refusal_error',
    'render_for_model', 'result', 'stage', 'stages_from', 'taxonomy_next_action',
    'unknown_error', 'validate_evidence_binding', 'validate_result',
]
