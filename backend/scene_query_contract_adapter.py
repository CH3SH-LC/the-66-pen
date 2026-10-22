"""W7: decouple the scene-query tool surface from the FROZEN v1 tool-result contract.

THE MEASURED PROBLEM (see checks/frozen-contract-coupling.json)
==============================================================
``plugins/miliastra/contracts/schemas/tool-result.schema.json`` is frozen at
``contractVersion const "1"``, closes ``additionalProperties`` at every level, closes the
``error.code`` enum to 39 business codes and fixes ``error.phase`` to
``{before-dispatch, after-dispatch}``.  Validated with ``jsonschema``, EVERY result the
delivered ``backend/scene_query_service.py`` produces is rejected: missing ``method`` /
``outcomeKnown`` / ``replayed``, forbidden extra keys (``observation``, ``limits``,
``evidenceRef``, ``contract`` ...), a ``targetBinding`` with unexpected keys, and refusal
codes (``HANDLE_REQUIRED``, ``PAGE_LIMIT_EXCEEDS_MAXIMUM``) that are not in the enum.

So the read surface cannot be expressed under v1.  There are exactly two ways to fix that,
and only one of them is allowed here:

* MIGRATION (forbidden) -- widen the frozen schema/contract in place, so yesterday's
  artifact silently means something new and every historical verdict that cited it becomes
  unverifiable.
* NEW VERSION + ADAPTER (this file) -- leave every frozen byte alone; publish version 2 as a
  NEW artifact; adapt explicitly in both directions, and record the correspondence.

WHAT THIS MODULE IS
===================
A pure function library.  It opens no socket, starts no process, reads no receipt, and
writes no file.  It reads the frozen v1 JSON only to *record* what it is (name, version,
sha256, tool names), so the correspondence can cite real values instead of prose.

* ``effective_profile()``  -- the v2 tool surface DERIVED from the frozen v1 + the wiring's
  own manifest.  It names, as data, which tools are v1 (unchanged) and which are v2 (added)
  and which are therefore absent from the frozen ``creationProfile.allow`` list.
* ``CORRESPONDENCE``       -- the new/old mapping table, one row per changed concept.
* ``scene_query_error_codes()`` -- the v2 closed code set, so the v2 schema can be generated
  from one source of truth instead of hand-copied.
* ``adapt_for_v1()``       -- give a v1-ONLY consumer a SAFE answer: either a faithful v1
  projection (only when nothing is lost) or a ``CONTRACT_VERSION_UNSUPPORTED`` version gate.
  It never silently drops an observation to squeeze a result into v1.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = (
    'FROZEN_CONTRACT_REL',
    'FROZEN_TOOL_RESULT_SCHEMA_REL',
    'V2_SCHEMA_REL',
    'G01_CONTRACT_VERSION',
    'PROFILE_VERSION',
    'PROFILE_ID',
    'V1_FAITHFUL_CAPABILITIES',
    'V1_ERROR_CODES',
    'SCENE_QUERY_ERROR_CODES',
    'CORRESPONDENCE',
    'frozen_evidence',
    'scene_query_error_codes',
    'effective_profile',
    'assert_frozen_unchanged',
    'adapt_for_v1',
)

FROZEN_CONTRACT_REL = 'plugins/miliastra/contracts/contract.json'
FROZEN_TOOL_RESULT_SCHEMA_REL = 'plugins/miliastra/contracts/schemas/tool-result.schema.json'
V2_SCHEMA_REL = ('plugins/miliastra/contracts/schemas/'
                 'tool-result.v2-scene-query.schema.json')

#: The G01 tool/state contract version.  The frozen tool-result schema pins this to "1",
#: and the scene-query service emits "1" too -- because this profile does NOT change the G01
#: contract.  Leaving it at "1" is the point: versioning it would claim a state/taxonomy
#: change that never happened.
G01_CONTRACT_VERSION = '1'
#: Version of the RESULT LAYOUT (the schema document and the key set).  This is what the
#: profile versions, and it is a NEW artifact published beside the frozen one.
PROFILE_VERSION = 2
#: Stable profile id, stamped on every result so a consumer can say which versioned surface
#: it speaks without guessing from the key set.
PROFILE_ID = 'scene-query/tool-surface/v2'

#: The only capability whose whole answer survives a v1 projection: a count fits in v1's
#: ``counts`` map.  Everything else needs ``observation``/``page``/``detail``, which v1 has
#: no place for -- so those are VERSION-GATED rather than silently emptied.
V1_FAITHFUL_CAPABILITIES = frozenset({'scene.count'})

#: The frozen ``error.code`` enum, copied verbatim from the v1 schema.  Kept here so the
#: correspondence and the v2 generator agree on what v1 already had.
V1_ERROR_CODES = (
    'CANCELLED_BEFORE_DISPATCH', 'CAPABILITY_NOT_ENABLED', 'CLEANUP_BRIDGE_UNAVAILABLE',
    'CLEANUP_ID_NOT_OWNED_BY_THIS_RUN', 'CLEANUP_IDS_DUPLICATED', 'CLEANUP_IDS_EMPTY',
    'CLEANUP_IDS_NOT_UINT32', 'CLEANUP_IDS_OVER_LIMIT', 'CLEANUP_REQUEST_NOT_A_CREATE',
    'CLEANUP_REQUEST_NOT_COMPLETE', 'CONTRACT_VERSION_UNSUPPORTED',
    'CREATE_EFFECT_NOT_AS_REQUESTED', 'EVIDENCE_INTEGRITY_FAILED',
    'EXECUTION_LAYER_BLOCKED', 'EXECUTION_LAYER_BUSY', 'EXECUTION_LAYER_UNAVAILABLE',
    'INCOMPATIBLE_VERSION', 'LEVEL_AT_CAPACITY', 'NATIVE_WRITE_REVIEW_REQUIRED',
    'READBACK_FAILED', 'READBACK_NOT_ACCEPTED', 'READBACK_WRONG_LEVEL',
    'REQUEST_ID_CONFLICT', 'REQUEST_ID_INVALID', 'REQUEST_INCOMPLETE_CLAIM',
    'REQUEST_OUTCOME_UNKNOWN', 'SAVE_STATUS_NOT_SUCCESS', 'SAVE_TOUCHED_PROTECTED_TARGET',
    'SCALE_NOT_POSITIVE', 'TARGET_HANDLE_INVALID', 'TARGET_HANDLE_RECEIPT_CHANGED',
    'TARGET_HANDLE_UNKNOWN', 'TARGET_HANDLE_UNVERIFIED', 'TARGET_STALE_REVISION',
    'TEMPLATE_ID_NOT_AN_INTEGER', 'TEMPLATE_NOT_SUPPORTED', 'TOOL_UNAVAILABLE_IN_PROFILE',
    'TRANSFORM_INVALID', 'UPSTREAM_PENDING', 'UPSTREAM_RECEIPT_UNREADABLE',
)

#: Codes the scene-query profile adds, over and above v1.  Three groups:
#:   * service/contract refusals raised by ``scene_query_service.py`` itself;
#:   * projection refusal codes, reused verbatim from ``scene_observation.py``;
#:   * upstream business codes that reach the caller through the read port, carried as the
#:     TOP-LEVEL code only because this profile's read path has exactly one business layer
#:     (``entity_server``) and it prefixes its own codes with the layer.  A v1 tool returns
#:     them under ``error.upstream``; v2 records the same string and no second vocabulary.
SCENE_QUERY_ERROR_CODES_ADDED = (
    # service-level refusals
    'COUNT_IS_NOT_AN_OBSERVATION', 'DETAIL_EXCEEDS_MAX_BYTES',
    'DIFF_NEEDS_TWO_OBSERVATIONS', 'DIFF_SNAPSHOT_ID_INCOMPLETE', 'HANDLE_REQUIRED',
    'HELD_SNAPSHOT_LIMIT_INVALID', 'LEGACY_READ_NOT_OK', 'LEGACY_RESULT_CLAIMS_OBSERVATION',
    'LEGACY_RESULT_INVALID', 'OBSERVATION_NOT_HELD', 'OBSERVER_CALL_FAILED',
    'OBSERVER_INTERFACE_VERSION_UNSUPPORTED', 'OBSERVER_MISSING_METHOD',
    'OBSERVER_REFUSED', 'OBSERVER_RESULT_CONTRADICTORY', 'OBSERVER_RESULT_INVALID',
    'OBSERVER_RESULT_UNRECOGNIZED_STATE', 'OPERATION_ID_INVALID', 'READ_NOT_COMPLETED',
    'READ_MODE_CONTRADICTS_DOCUMENT', 'SNAPSHOT_NOT_HELD', 'STAGE_PASS_WITHOUT_EVIDENCE',
    'STAGE_STATUS_INVALID',
    # projection refusal codes (reused, never remapped)
    'ACCEPTANCE_BLOCK_INVALID', 'DOCUMENT_COUNTS_INCONSISTENT', 'DOCUMENT_ENTITY_ID_INVALID',
    'DOCUMENT_ENTITY_SHAPE_UNSUPPORTED', 'DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED',
    'DOCUMENT_SHAPE_UNSUPPORTED', 'DOCUMENT_STATUS_UNKNOWN', 'DOCUMENT_VERSION_UNSUPPORTED',
    'DUPLICATE_ENTITY_IDENTITY', 'ENTITIES_TRUNCATED', 'ENTITY_ID_INVALID',
    'EXTERNAL_BLOCK_INVALID', 'EXTERNAL_BLOCK_UNKNOWN_ENTITY', 'IDENTITY_INVALID',
    'IDENTITY_OBSERVED_AT_INVALID', 'IDENTITY_RECEIPT_SHA_INVALID', 'INPUT_KIND_UNSUPPORTED',
    'PROJECTION_INVALID', 'SNAPSHOT_LEVEL_MISMATCH', 'SNAPSHOT_NOT_READABLE',
    'SNAPSHOT_STATUS_NOT_OK', 'SNAPSHOT_UNTRUSTED', 'SUBSYSTEM_BLOCK_INVALID',
    'SUBSYSTEM_STATUS_UNKNOWN', 'WRONG_LEVEL',
    # paging / cursor codes
    'CURSOR_CONTENT_CHANGED', 'CURSOR_INVALID', 'CURSOR_LEVEL_CHANGED',
    'CURSOR_OFFSET_OUT_OF_RANGE', 'CURSOR_SNAPSHOT_CHANGED', 'CURSOR_TAMPERED',
    'CURSOR_VERSION_UNSUPPORTED', 'PAGE_LIMIT_EXCEEDS_MAXIMUM', 'PAGE_LIMIT_INVALID',
    # upstream business codes that reach the caller through the read port
    'BACKEND_NO_JSON_RECEIPT', 'DISCOVERY_INTERPRETER_MISSING', 'ELEVATED_HELPER_BLOCKED',
    'ELEVATED_HELPER_DEADLINE_PASSED', 'ELEVATED_HELPER_NOT_USABLE',
    'ELEVATED_HEARTBEAT_ABSENT', 'ELEVATED_POINTER_MISSING',
    'ELEVATED_QUEUE_AMBIGUOUS', 'ELEVATED_QUEUE_NOT_FOUND',
    'ELEVATED_QUEUE_OUTSIDE_PROJECT_OR_MISSING', 'LEVEL_HANDLE_INVALID',
    'LEVEL_HANDLE_RECEIPT_CHANGED', 'LEVEL_HANDLE_UNKNOWN', 'LEVEL_HANDLE_UNVERIFIED',
    'READBACK_SNAPSHOT_CHANGED', 'READBACK_SNAPSHOT_UNREADABLE',
)

#: The v2 closed code set = v1's codes plus the additions.  One source of truth: the v2
#: schema's ``error.code`` enum is generated from this and a test re-derives it.
SCENE_QUERY_ERROR_CODES = tuple(sorted(set(V1_ERROR_CODES) | set(SCENE_QUERY_ERROR_CODES_ADDED)))

#: ``error.phase`` values this profile emits.  v1 knows only the dispatch boundary; v2 must
#: name WHICH pre-dispatch stage refused (input / cursor / projection / detail / diff /
#: observer / layer), because "refused" alone does not tell a caller what to correct.
PHASES_ADDED = ('input', 'observer', 'cursor', 'projection', 'detail', 'diff', 'layer')

#: Top-level keys v2 adds.  v1 forbids them (``additionalProperties: false``).
V2_KEYS_ADDED = (
    'contract', 'contractName', 'evidenceRef', 'heldForLaterCalls', 'isError', 'limits',
    'note', 'observation', 'observationLevel', 'observationNotHeldReason', 'page',
    'schemaVersion', 'unrecognizedObserverKeys', 'currentSnapshotId', 'evictedSnapshotIds',
    'objectIdsTruncated', 'nextStep', 'changedIdsShown', 'changedIdsTruncated',
    'snapshotPathWithheld',
)

#: The new/old correspondence, one row per changed concept.  ``v1`` is null exactly when the
#: concept did not exist in the frozen contract.
CORRESPONDENCE = (
    {'v2': 'tool-result layout v2, profileId scene-query/tool-surface/v2',
     'v1': 'tool-result layout v1 (frozen schema, no profileId)',
     'change': 'new-version',
     'note': 'a NEW schema artifact published beside the frozen one; the layout is versioned, '
             'NOT the G01 contract'},
    {'v2': 'contractVersion stays "1"',
     'v1': 'contractVersion "1"',
     'change': 'unchanged',
     'note': 'the G01 tool/state contract did not change: same five stages, same six states, '
             'same six nextAction tokens, same dispositions -- so the version that names the '
             'contract must not move'},
    {'v2': 'capabilityId scene.observe / scene.page / scene.detail / scene.diff',
     'v1': None, 'change': 'added',
     'note': 'v1 had no read/observation capability; its four allow-listed read tools were '
             'count-or-write only'},
    {'v2': 'capabilityId scene.count', 'v1': 'mw_scene_read_entities (count + path answer)',
     'change': 'renamed-and-narrowed',
     'note': 'the legacy tool is unchanged; the same count is reachable as a versioned '
             'capability whose snapshot path moves into evidenceRef (HONEST-7)'},
    {'v2': 'top-level observationLevel / observation',
     'v1': None, 'change': 'added',
     'note': 'v1 had no place for rows, per-attribute source or a completeness verdict'},
    {'v2': 'top-level evidenceRef (array of project-relative references)',
     'v1': 'stage.evidenceRef only', 'change': 'widened',
     'note': 'v1 kept evidence per stage; v2 also carries a result-level reference set'},
    {'v2': 'top-level limits / note / unrecognizedObserverKeys / schemaVersion / contract',
     'v1': None, 'change': 'added',
     'note': 'self-description and the observer-key audit trail'},
    {'v2': 'operationId: string | null',
     'v1': 'operationId: string (required)',
     'change': 'widened',
     'note': 'a read has no idempotency key when the caller supplies none, and this surface '
             'never mints one for the caller'},
    {'v2': 'isError === (state !== "completed")',
     'v1': 'ok === (state === "completed")',
     'change': 'widened',
     'note': 'v2 also publishes the negation explicitly instead of making the client derive '
             'it (G01 STATE-1)'},
    {'v2': 'writeExecuted: const false for every result',
     'v1': 'writeExecuted: bool | null',
     'change': 'narrowed',
     'note': 'every capability in this profile is a read; a profile that could write would '
             'need its own version'},
    {'v2': 'error.phase: before-dispatch | after-dispatch plus the refusing STAGE',
     'v1': 'error.phase: before-dispatch | after-dispatch',
     'change': 'widened',
     'note': 'v2 emits %s so a caller learns what to correct' % ', '.join(PHASES_ADDED)},
    {'v2': 'error.code: v1 codes + %d scene-query/upstream codes'
           % len(SCENE_QUERY_ERROR_CODES_ADDED),
     'v1': 'error.code: closed enum of %d business codes' % len(V1_ERROR_CODES),
     'change': 'widened',
     'note': 'READBACK_FAILED / READBACK_WRONG_LEVEL / READBACK_NOT_ACCEPTED stay exactly '
             'the three context-dependent codes the frozen taxonomy names, and this profile '
             'resolves their disposition at the emitting call site'},
    {'v2': 'targetBinding: {levelId, sessionPid, sessionProcessCreation, sessionSource, '
           'handleResolvedByDiscovery}',
     'v1': 'targetBinding: 7 required business fields + backend profile identity',
     'change': 'profile-specific',
     'note': 'a read binds to a discovery handle and its session; it has no backend profile '
             'id, so v1\'s required set cannot be satisfied and v2 declares its own'},
    {'v2': 'creationProfile.allow gains the four query tools (v2 profile)',
     'v1': 'creationProfile.allow holds exactly four tools',
     'change': 'widened-by-derived-profile',
     'note': 'expressed as a DERIVED profile (effective_profile); the frozen contract.json '
             'is not edited, so a v1 consumer still sees exactly what it saw before'},
    {'v2': 'state / nextAction / stages / changed / failedItems / objectIds / retryAttempted',
     'v1': 'identical closed sets', 'change': 'unchanged',
     'note': 'the five stages, the six nextAction tokens and the closed state set are reused '
             'verbatim; this profile does not invent a second vocabulary'},
)


def _sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_evidence(root):
    """Record what the frozen v1 artifacts ARE, so the correspondence cites real bytes."""
    root = Path(root)
    contract_path = root / FROZEN_CONTRACT_REL
    schema_path = root / FROZEN_TOOL_RESULT_SCHEMA_REL
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    profile = (contract.get('registration') or {}).get('creationProfile') or {}
    return {
        'contractPath': FROZEN_CONTRACT_REL,
        'contractSha256': _sha256_file(contract_path),
        'contractName': contract.get('contractName'),
        'contractVersion': contract.get('contractVersion'),
        'schemaPath': FROZEN_TOOL_RESULT_SCHEMA_REL,
        'schemaSha256': _sha256_file(schema_path),
        'schemaContractVersionConst': (schema.get('properties') or {})
                                       .get('contractVersion', {}).get('const'),
        'closedAtRoot': schema.get('additionalProperties') is False,
        'allow': list(profile.get('allow') or []),
        'allowForWriteScope': list(profile.get('allowForWriteScope') or []),
    }


def scene_query_error_codes():
    """The v2 closed code set, as data (the schema's enum is generated from this)."""
    return list(SCENE_QUERY_ERROR_CODES)


def effective_profile(root, tool_surface):
    """The v2 tool surface DERIVED from the frozen v1 plus this wiring's manifest.

    Pure: nothing is written.  Every tool carries its ``origin`` so a reviewer can see at a
    glance which entries are unchanged v1 tools and which are the additions, and
    ``needsFrozenAllowListEntry`` names exactly what a v2 consumer would have to allow --
    without that edit having been made to the frozen file.
    """
    evidence = frozen_evidence(root)
    frozen_allow = set(evidence['allow']) | set(evidence['allowForWriteScope'])
    raw_to_public = {}
    for name in frozen_allow:
        raw_to_public[name] = name
    tools = []
    for capability in tool_surface['capabilities']:
        raw = capability['rawToolName']
        public = 'mcp__miliastra__%s' % raw
        present = public in frozen_allow
        tools.append({
            'rawToolName': raw,
            'publicName': public,
            'capabilityId': capability['capabilityId'],
            'method': capability['method'],
            'origin': 'v1-frozen' if present else 'v2-added',
            'presentInFrozenAllowList': present,
            'needsFrozenAllowListEntry': not present,
        })
    return {
        'profileId': PROFILE_ID,
        'profileVersion': PROFILE_VERSION,
        'g01ContractVersion': G01_CONTRACT_VERSION,
        'derivedFrom': evidence,
        'wiringVersion': tool_surface['wiringVersion'],
        'observerInterfaceVersion': tool_surface['interfaceVersion'],
        'tools': tools,
        'addedToolNames': [tool['publicName'] for tool in tools
                           if tool['origin'] == 'v2-added'],
        'note': 'derived view only; plugins/miliastra/contracts/contract.json is not edited, '
                'so a v1 consumer still sees exactly the v1 tool set',
    }


def assert_frozen_unchanged(root, expected_sha256):
    """Guard: the frozen artifact still has the bytes the correspondence was written against."""
    actual = _sha256_file(Path(root) / FROZEN_CONTRACT_REL)
    if actual != expected_sha256:
        raise AssertionError('frozen contract changed: %s != %s' % (actual, expected_sha256))
    return actual


def _v1_error(error, *, message_fallback):
    """A v1-conformant error object, or ``None`` when the code cannot be expressed in v1."""
    if error is None:
        return None
    code = error.get('code')
    if code not in V1_ERROR_CODES:
        return None
    return {
        'code': code,
        'disposition': 'refusal-before-dispatch',
        'phase': 'before-dispatch',
        'sideEffect': 'none',
        'message': error.get('message') or message_fallback,
        'detail': error.get('detail') if isinstance(error.get('detail'), dict) else None,
    }


def version_gate_result(*, capability_id, operation_id=None, case_id=None, target_handle=None,
                        reasons, method=None):
    """A v1-conformant REJECTED result that says "use the versioned profile".

    This is the honest refusal: rather than squeeze an observation into a shape with no
    place for it, the adapter returns ``CONTRACT_VERSION_UNSUPPORTED`` with disposition
    ``version-gate`` -- one of v1's own four dispositions -- and names what could not be
    expressed.  Nothing is dropped silently, and nothing is written.
    """
    body = {
        'contractVersion': G01_CONTRACT_VERSION,
        'capabilityId': capability_id,
        'method': method or capability_id,
        'operationId': operation_id,
        'caseId': case_id,
        'targetHandle': target_handle,
        'state': 'rejected',
        'ok': False,
        'outcomeKnown': True,
        # NOTE: v1 has no ``isError`` field and forbids extra keys, so the v1 projection
        # carries ``ok`` only; a client derives the negation itself.
        'writeExecuted': False,
        'retryAttempted': False,
        'replayed': False,
        'objectIds': [],
        'changed': [],
        'failedItems': [],
        'nextAction': 'fix-input',
        'nextActionDetail': 'this consumer speaks the frozen tool-result layout v1; the '
                            'versioned scene-query profile (profileId "%s") is required for '
                            'this answer' % PROFILE_ID,
        'stages': {
            name: {'status': 'not-run',
                   'reason': 'a version gate refuses before any stage of this call could be '
                             'reported',
                   'evidenceRef': []}
            for name in ('liveReadback', 'saveDiff', 'reopen', 'runtime', 'cleanup')
        },
        'error': {
            'code': 'CONTRACT_VERSION_UNSUPPORTED',
            'disposition': 'version-gate',
            'phase': 'before-dispatch',
            'sideEffect': 'none',
            'message': 'scene-query results are published under profileId "%s"; the frozen '
                   'layout v1 has no field for them' % PROFILE_ID,
            'detail': {'profileId': PROFILE_ID,
                       'profileVersion': PROFILE_VERSION,
                       'contractVersion': G01_CONTRACT_VERSION,
                       'notExpressibleInV1': sorted(reasons)},
        },
    }
    return {'adapted': False, 'result': body, 'movedKeys': [], 'reasons': sorted(reasons)}


def adapt_for_v1(result, *, method=None, operation_id=None):
    """Give a v1-only consumer a SAFE answer for a v2 scene-query result.

    Two outcomes, never a third:

    * ``adapted: True`` -- a v1 result that LOSES NOTHING (only for ``scene.count``, whose
      whole answer is a number that v1's ``counts`` map can carry).  Keys that moved out of
      the top level are named in ``movedKeys``; the caller keeps its observation separately.
    * ``adapted: False`` -- a ``CONTRACT_VERSION_UNSUPPORTED`` version gate.  Any capability
      whose answer is rows, a page, a detail or a diff cannot be squeezed into v1, and the
      adapter refuses rather than returning an empty answer that looks like "nothing there".

    It never invents an ``operationId``: v1 requires a string and this surface never mints
    one, so a result with no operation id is version-gated instead of being given a fake one.
    """
    if result.get('profileId') != PROFILE_ID:
        raise ValueError('adapt_for_v1 expects a profileId %r result, got %r'
                         % (PROFILE_ID, result.get('profileId')))
    capability_id = result.get('capabilityId')
    reasons = []
    if capability_id not in V1_FAITHFUL_CAPABILITIES:
        reasons.append('capabilityId %s produces rows/observation that v1 cannot carry'
                       % capability_id)
    if result.get('observationLevel') not in (None, 'count-only'):
        reasons.append('observationLevel %r has no v1 field' % (result.get('observationLevel'),))
    operation = result.get('operationId') or operation_id
    if not isinstance(operation, str) or not operation:
        reasons.append('v1 requires a string operationId and this surface never mints one')
    if result.get('state') != 'completed':
        reasons.append('state %r carries an error code outside the v1 enum'
                       % (result.get('state'),))
    if reasons:
        return version_gate_result(
            capability_id=capability_id, operation_id=operation,
            case_id=result.get('caseId'), target_handle=result.get('targetHandle'),
            reasons=reasons,
            method=method or (result.get('observation') or {}).get('legacyTool'))

    observation = result.get('observation') or {}
    counts = {}
    if isinstance(observation.get('entityCount'), int):
        counts['entityCount'] = observation['entityCount']
    body = {
        'contractVersion': G01_CONTRACT_VERSION,
        'capabilityId': capability_id,
        'method': method or 'mw.scene.countEntities',
        'operationId': operation,
        'caseId': result.get('caseId'),
        'targetHandle': result.get('targetHandle'),
        'state': 'completed',
        'ok': True,
        'outcomeKnown': True,
        'writeExecuted': False,
        'retryAttempted': False,
        'replayed': False,
        'objectIds': [],
        'changed': [],
        'failedItems': [],
        'nextAction': 'none',
        'nextActionDetail': result.get('nextActionDetail'),
        'counts': counts,
        'stages': {name: {'status': stage['status'],
                          'reason': stage.get('reason'),
                          'evidenceRef': list(stage.get('evidenceRef') or [])}
                   for name, stage in result['stages'].items()},
        'error': None,
    }
    moved = sorted(set(result) - set(body) - {'stages'})
    return {
        'adapted': True,
        'result': body,
        'movedKeys': moved,
        'reasons': [],
        'note': 'a faithful v1 projection: the count survives in counts.entityCount and the '
                'stage evidence is carried verbatim; nothing was upgraded or invented',
    }
