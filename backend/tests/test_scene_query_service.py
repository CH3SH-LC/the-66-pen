"""Offline composition tests for backend/scene_query_service.py.

Everything here is offline.  There is no process to start, no queue, no helper, no game and
no file the service itself opens: the execution layer is a test double, and every document
comes from ``backend/fixtures/scene_observation`` -- byte copies of real receipts and
declared reverse cases, all marked ``live: false``.

The suite is organised as the claims it has to break:

* ``ContractShapeTests``          -- the G01 v1 result contract, field by field
* ``ExecutionSurfaceTests``       -- this module cannot reach anything (AST, not prose)
* ``InjectedLayerTests``          -- an untrusted or contradictory observer answer is refused
* ``CountLayerTests``             -- a count is not an observation, and cannot become one
* ``ObservationLayerTests``       -- unknown / truncated / source markers survive the layer
* ``PagingTests``                 -- both limits count; a stale cursor is refused
* ``DetailTests``                 -- absence is not upgraded; unknown is not zero
* ``DiffTests``                   -- no silent empty diff; same-count swap is visible
* ``LiveClaimDisciplineTests``    -- this layer never claims a live readback it did not get
* ``MutationControlTests``        -- each guarantee above, removed, is caught
* ``ProvenanceTests``             -- the T04 projection and its fixtures are untouched

Run:

    .runtime/mcp-venv/Scripts/python.exe -B backend/tests/test_scene_query_service.py
    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.tests.test_scene_query_service

``--mutation-report PATH`` writes the mutation-control table as JSON (used for the handoff
evidence); without it the table is printed.
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
for _candidate in (ROOT, ROOT / 'backend'):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from backend import scene_observation as observation          # noqa: E402
from backend import scene_query_service as service            # noqa: E402

FIXTURES = ROOT / 'backend/fixtures/scene_observation'
PROVENANCE = json.loads((FIXTURES / 'PROVENANCE.json').read_text(encoding='utf-8'))

LEVEL = 1073741839
OTHER_LEVEL = 1073741834
HANDLE = 'handle-fixture-inspect-153108'
INSPECT = 'captured/inspect-20260929-153108.before-context.json'
CREATE_BEFORE = 'captured/create-20260929-152943.before-context.json'
CREATE_AFTER = 'captured/create-20260929-152943.after-context.json'
RUN_REF = '.runtime/game-executor/scene-cli/inspect/20260929-153108-edb0fcdf3e'

#: The T04 module as delivered and independently re-verified by the coordinator.  Asserting
#: it here is how this task proves it did not touch the projection it reuses.
T04_MODULE_SHA256 = '5fe59e5f0fa0a61c499927400e94e94593cbbe5949a4860f0c7dd6016caa2e5e'
T04_TEST_SHA256 = 'bfb66e11953247472c92faf4f2a23b5599a9889bcb983d77a073f73a33851b77'

DELIVERED = (ROOT / 'backend/scene_query_service.py',
             ROOT / 'backend/tests/test_scene_query_service.py')


def fixture(rel):
    return json.loads((FIXTURES / rel).read_text(encoding='utf-8-sig'))


def raw(rel):
    return (FIXTURES / rel).read_bytes()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(**overrides):
    base = {
        'targetHandle': HANDLE,
        'levelId': LEVEL,
        'observedAt': '2026-10-02T03:00:00Z',
        'receiptPath': RUN_REF + '/before-context.json',
        'receiptSha256': PROVENANCE['fixtures'][INSPECT]['fixtureSha256'],
        'sessionPid': 4004,
        'sessionCreation': '2026-10-01T00:00:00+08:00',
        'sessionSource': 'pointer',
    }
    base.update(overrides)
    return base


def duplicate_identity(document):
    """A same-shape document whose second row repeats the first row's identity."""
    mutated = copy.deepcopy(document)
    first, second = mutated['entities'][0], mutated['entities'][1]
    second['id'] = first['id']
    second['dictionaryKey'] = first['dictionaryKey']
    return mutated


def with_swapped_id(document, index=5, new_id=1077936199):
    """A same-count, different-object reverse case built from a captured copy."""
    mutated = copy.deepcopy(document)
    row = mutated['entities'][index]
    assert row['flags']['value'] & 1 and row['flags']['value'] & 8, row['flags']
    row['id'] = new_id
    row['dictionaryKey'] = new_id
    return mutated


# --------------------------------------------------------------------------- #
# the injected execution layer, as a test double
# --------------------------------------------------------------------------- #

class FakeObserver:
    """Stands in for the execution layer.  Holds no path and runs nothing.

    Every field may be a scalar or a list; a list is consumed one answer at a time so one
    double can script a whole conversation (observe, observe, observe ...).
    """

    def __init__(self, *, documents=None, counts=None, states='known-complete',
                 read_modes='fixture', errors=None, hints=None,
                 evidence=('.runtime/fake/execution-layer-run',), identities=None,
                 interface_version='scene-query/observer/v1', extra=None):
        self.documents = list(documents or [])
        self.counts = list(counts or [])
        self.states = states
        self.read_modes = read_modes
        self.errors = errors
        self.hints = hints
        self.evidence = evidence
        self.identities = list(identities or [])
        self.interface_version = interface_version
        self.extra = dict(extra or {})
        self.calls = []
        self.results = []

    @staticmethod
    def _take(value, default):
        if isinstance(value, list):
            return value.pop(0) if value else default
        return default if value is None else value

    def _result(self, method, material, handle):
        taken = self._take(self.evidence, [])
        if isinstance(taken, str):
            taken = [taken]
        result = {
            'interfaceVersion': self.interface_version,
            'operationState': self._take(self.states, 'known-complete'),
            'readMode': self._take(self.read_modes, 'fixture'),
            'error': self._take(self.errors, None),
            'nextActionHint': self._take(self.hints, None),
            'evidenceRef': list(taken),
        }
        if material is not None:
            result['count' if method == 'count' else 'document'] = material
            if method == 'observe':
                result['identity'] = (self.identities.pop(0) if self.identities
                                      else identity(targetHandle=handle, levelId=LEVEL))
        result.update(self.extra)
        self.results.append(result)
        return result

    def count(self, handle):
        self.calls.append(('count', handle))
        material = self.counts.pop(0) if self.counts else None
        return self._result('count', material, handle)

    def observe(self, handle):
        self.calls.append(('observe', handle))
        material = self.documents.pop(0) if self.documents else None
        return self._result('observe', material, handle)


def build(**kwargs):
    return service.SceneQueryService(FakeObserver(**kwargs))


def observed(*, documents=None, **kwargs):
    """A service holding one observation of HANDLE, plus the response."""
    svc = build(documents=documents or [fixture(INSPECT)], **kwargs)
    return svc, svc.query_observe(targetHandle=HANDLE)


def json_of(thing):
    return json.dumps(thing, ensure_ascii=False, sort_keys=True)


# --------------------------------------------------------------------------- #
# 1. the G01 v1 result contract
# --------------------------------------------------------------------------- #

class ContractShapeTests(unittest.TestCase):

    def test_every_result_carries_the_g01_envelope(self):
        _, result = observed()
        for key in ('schemaVersion', 'contract', 'contractVersion', 'contractName',
                    'capabilityId', 'operationId', 'caseId', 'targetHandle', 'targetBinding',
                    'state', 'ok', 'isError', 'writeExecuted', 'retryAttempted', 'objectIds',
                    'changed', 'failedItems', 'nextAction', 'nextActionDetail',
                    'observationLevel', 'observation', 'stages', 'error', 'evidenceRef'):
            self.assertIn(key, result, key)
        self.assertEqual(result['contractVersion'], '1')
        self.assertIsInstance(result['contractVersion'], str)
        self.assertEqual(result['schemaVersion'], 1)
        self.assertIsInstance(result['schemaVersion'], int)

    def test_state_and_ok_are_never_independent(self):
        """G01 STATE-1: ok === (state === 'completed'), isError === (state !== 'completed')."""
        cases = [
            observed()[1],
            build(counts=[{'entityCount': 3}]).query_count(targetHandle=HANDLE),
            build(states='never-claimed',
                  errors=[{'code': 'HELPER_UNAVAILABLE', 'message': 'x', 'detail': {}}]
                  ).query_observe(targetHandle=HANDLE),
            build(states='outcome-unknown', documents=[],
                  errors=[{'code': 'X', 'message': 'y', 'detail': {}}]
                  ).query_observe(targetHandle=HANDLE),
        ]
        for result in cases:
            self.assertEqual(result['ok'], result['state'] == 'completed', result['state'])
            self.assertEqual(result['isError'], result['state'] != 'completed', result['state'])
            self.assertIn(result['state'], service.BUSINESS_STATES)

    def test_a_query_never_reports_a_write(self):
        for result in (observed()[1],
                       build(counts=[{'entityCount': 1}]).query_count(targetHandle=HANDLE)):
            self.assertFalse(result['writeExecuted'])
            self.assertFalse(result['retryAttempted'])
            self.assertEqual(result['changed'], [])
            self.assertEqual(result['failedItems'], [])

    def test_all_five_stages_are_present_and_only_live_readback_is_asserted(self):
        result = build(documents=[fixture(INSPECT)], read_modes='live').query_observe(
            targetHandle=HANDLE)
        self.assertEqual(tuple(result['stages']), service.STAGE_NAMES)
        self.assertEqual(result['stages']['liveReadback']['status'], 'pass')
        for name in ('saveDiff', 'reopen', 'runtime', 'cleanup'):
            stage = result['stages'][name]
            self.assertEqual(stage['status'], 'not-run', name)
            self.assertTrue(stage['reason'], name)

    def test_persistence_is_never_emitted_as_a_stage_name(self):
        """G01 conflict C-1: saveDiff is canonical; persistence is an input alias only."""
        self.assertNotIn('persistence', observed()[1]['stages'])

    def test_every_stage_carries_a_reason_and_a_pass_carries_evidence(self):
        results = [observed()[1],
                   build(counts=[{'entityCount': 1}]).query_count(targetHandle=HANDLE),
                   build(states='never-claimed',
                         errors=[{'code': 'HELPER_UNAVAILABLE', 'message': 'x', 'detail': {}}
                                 ]).query_observe(targetHandle=HANDLE)]
        for result in results:
            for name, stage in result['stages'].items():
                self.assertIn(stage['status'], service.STAGE_STATUSES)
                self.assertIsInstance(stage['reason'], str)
                self.assertTrue(stage['reason'], '%s/%s has no reason' % (result['state'], name))
                self.assertIsInstance(stage['evidenceRef'], list)
                if stage['status'] == 'pass':
                    self.assertTrue(stage['evidenceRef'], '%s claims pass with no evidence'
                                    % name)

    def test_a_pass_without_evidence_is_refused_outright(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            find_stage = service._stage
            find_stage('pass', reason='looks fine')
        self.assertEqual(caught.exception.code, 'STAGE_PASS_WITHOUT_EVIDENCE')

    def test_next_action_is_always_a_closed_g01_token(self):
        results = [observed()[1],
                   build(states='never-claimed',
                         hints=['await-human'],
                         errors=[{'code': 'HELPER_UNAVAILABLE', 'message': 'x', 'detail': {}}
                                 ]).query_observe(targetHandle=HANDLE),
                   build(states='outcome-unknown',
                         errors=[{'code': 'X', 'message': 'y', 'detail': {}}]
                         ).query_observe(targetHandle=HANDLE)]
        for result in results:
            self.assertIn(result['nextAction'], service.NEXT_ACTIONS)
            self.assertTrue(result['nextActionDetail'])

    def test_an_observer_may_ask_for_a_human_when_the_layer_is_down(self):
        result = build(
            states='never-claimed', hints=['await-human'],
            errors=[{'code': 'NATIVE_SCENE_HELPER_UNAVAILABLE', 'message': 'helper dead',
                     'detail': {}}]).query_observe(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['nextAction'], 'await-human')
        self.assertFalse(result['ok'])
        self.assertEqual(result['stages']['liveReadback']['status'], 'blocked')

    def test_every_refusal_produces_a_rejected_pre_dispatch_result(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            service.SceneQueryService(FakeObserver()).query_page(targetHandle=HANDLE)
        result = service.refusal_result(caught.exception, capabilityId='scene.page',
                                        targetHandle=HANDLE)
        self.assertEqual(result['state'], 'rejected')
        self.assertFalse(result['ok'])
        self.assertTrue(result['isError'])
        self.assertFalse(result['writeExecuted'])
        self.assertEqual(result['error']['code'], 'OBSERVATION_NOT_HELD')
        self.assertEqual(result['error']['disposition'], 'refusal-before-dispatch')
        self.assertIn(result['nextAction'], service.NEXT_ACTIONS)
        self.assertEqual(tuple(result['stages']), service.STAGE_NAMES)
        self.assertIsNone(result['observation'])
        self.assertIsNone(result['observationLevel'])

    def test_observation_id_and_case_id_are_echoed_never_minted(self):
        svc = build(counts=[{'entityCount': 1}])
        result = svc.query_count(targetHandle=HANDLE, operationId='op-abc_1', caseId='case-2')
        self.assertEqual(result['operationId'], 'op-abc_1')
        self.assertEqual(result['caseId'], 'case-2')
        for bad in ('has space', '', 'x' * 81, '1' + '-' * 81, 7):
            with self.assertRaises(service.QueryRefusal) as caught:
                svc.query_count(targetHandle=HANDLE, operationId=bad)
            self.assertEqual(caught.exception.code, 'OPERATION_ID_INVALID')

    def test_target_binding_carries_the_session_it_was_read_under(self):
        """G01 open item O-4: the result must show which session the handle bound to."""
        result = observed()[1]
        bound = result['targetBinding']
        self.assertEqual(bound['levelId'], LEVEL)
        self.assertEqual(bound['sessionPid'], 4004)
        self.assertEqual(bound['sessionProcessCreation'], '2026-10-01T00:00:00+08:00')
        self.assertEqual(bound['sessionSource'], 'pointer')

    def test_a_handle_is_required_and_is_never_a_level_id(self):
        svc = build(counts=[{'entityCount': 1}])
        for bad in (None, '', '   ', 1073741839, ['handle']):
            with self.assertRaises(service.QueryRefusal) as caught:
                svc.query_count(targetHandle=bad)
            self.assertEqual(caught.exception.code, 'HANDLE_REQUIRED')

    def test_an_unrecognized_observer_key_is_reported_not_dropped(self):
        svc = build(counts=[{'entityCount': 2}], extra={'somethingNew': 1})
        result = svc.query_count(targetHandle=HANDLE)
        self.assertEqual(result['unrecognizedObserverKeys'], ['somethingNew'])

    def test_observer_schema_is_published_as_data(self):
        schema = service.observer_result_schema()
        self.assertEqual(schema['interfaceVersion'], service.OBSERVER_INTERFACE_VERSION)
        self.assertEqual(schema['operationStates'], list(service.OPERATION_STATES))
        self.assertEqual(sorted(schema['keys']), sorted(service.OBSERVER_RESULT_KEYS))
        for key in schema['required']:
            self.assertIn(key, service.OBSERVER_RESULT_KEYS)


# --------------------------------------------------------------------------- #
# 2. the module cannot reach anything
# --------------------------------------------------------------------------- #

_ALLOWED_IMPORTS = {'__future__', 'json', 'collections', 'collections.abc', 'backend',
                    'scene_observation'}
_BANNED_NAMES = {'open', 'eval', 'exec', 'compile', '__import__', 'input', 'breakpoint'}
_BANNED_ATTRS = {'Popen', 'system', 'popen', 'spawn', 'spawnv', 'execv', 'execvp', 'fork',
                 'kill', 'remove', 'unlink', 'rmdir', 'mkdir', 'makedirs', 'write_text',
                 'write_bytes', 'read_text', 'read_bytes', 'check_output', 'check_call',
                 'getoutput', 'walk'}
_BANNED_PARAM_NAMES = {'path', 'paths', 'file', 'filename', 'command', 'cmd', 'argv', 'arg',
                       'shell', 'queue', 'queuedir', 'elevatedqueue', 'helper', 'script',
                       'exe', 'executable', 'interpreter', 'run', 'runid', 'pid', 'timeout',
                       'cwd', 'env', 'plan', 'review'}


class ExecutionSurfaceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'backend/scene_query_service.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.source)

    def test_no_import_outside_the_allowed_stdlib_allowlist(self):
        seen = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                seen.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                seen.add((node.module or '').split('.')[0])
        self.assertTrue(seen <= _ALLOWED_IMPORTS, seen - _ALLOWED_IMPORTS)

    def test_no_banned_builtin_or_method_is_reachable(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, _BANNED_NAMES, node.lineno)
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, _BANNED_ATTRS, node.lineno)

    def test_the_module_imports_the_verified_projection_instead_of_reimplementing_it(self):
        self.assertIn('scene_observation', self.source)
        self.assertIs(service._observation, observation)

    def test_no_public_call_takes_a_path_command_queue_or_helper(self):
        tree = ast.parse(self.source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith('_'):
                    continue
                for arg in (node.args.posonlyargs + node.args.args + node.args.kwonlyargs):
                    if arg.arg.lower() in _BANNED_PARAM_NAMES:
                        offenders.append('%s(%s)' % (node.name, arg.arg))
        self.assertEqual(offenders, [])

    def test_execution_surface_is_declared_false(self):
        self.assertTrue(service.EXECUTION_SURFACE)
        for key, value in service.EXECUTION_SURFACE.items():
            self.assertIs(value, False, key)

    def test_the_delivered_files_are_lf(self):
        for path in DELIVERED:
            self.assertNotIn(b'\r\n', Path(path).read_bytes(), path.name)


# --------------------------------------------------------------------------- #
# 3. the injected layer's answers
# --------------------------------------------------------------------------- #

class InjectedLayerTests(unittest.TestCase):

    def test_an_observer_without_the_two_methods_is_refused(self):
        class OnlyCount:
            def count(self, handle):
                return {}

        with self.assertRaises(service.QueryRefusal) as caught:
            service.SceneQueryService(OnlyCount())
        self.assertEqual(caught.exception.code, 'OBSERVER_MISSING_METHOD')
        with self.assertRaises(service.QueryRefusal):
            service.SceneQueryService(object())

    def test_a_near_miss_operation_state_is_refused_not_rounded(self):
        for bad in ('complete', 'known_success', 'COMPLETED', 'done', 0, 'known-complete ',
                    'known-complete\n', ('known-complete',)):
            with self.subTest(state=bad):
                with self.assertRaises(service.QueryRefusal) as caught:
                    build(counts=[{'entityCount': 1}], states=bad).query_count(
                        targetHandle=HANDLE)
                self.assertEqual(caught.exception.code,
                                 'OBSERVER_RESULT_UNRECOGNIZED_STATE')

    def test_a_completed_read_must_hand_over_what_it_produced(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(documents=[], states='known-complete').query_observe(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_CONTRADICTORY')
        self.assertEqual(caught.exception.detail['missing'], 'document')

    def test_material_before_a_terminal_state_is_refused(self):
        for state in ('never-claimed', 'claimed', 'dispatched', 'outcome-unknown'):
            with self.assertRaises(service.QueryRefusal) as caught:
                build(documents=[fixture(INSPECT)], states=state).query_observe(
                    targetHandle=HANDLE)
            self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_CONTRADICTORY')

    def test_an_answer_for_another_handle_is_refused(self):
        svc = build(documents=[fixture(INSPECT)],
                    identities=[identity(targetHandle='a-different-handle')])
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_CONTRADICTORY')
        self.assertEqual(caught.exception.detail['answeredHandle'], 'a-different-handle')

    def test_an_unknown_read_mode_is_refused(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(counts=[{'entityCount': 1}], read_modes='maybe').query_count(
                targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_INVALID')

    def test_an_unknown_interface_version_is_refused(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(counts=[{'entityCount': 1}], interface_version='scene-query/observer/v9'
                  ).query_count(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_INTERFACE_VERSION_UNSUPPORTED')

    def test_an_invalid_next_action_hint_is_refused(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(counts=[{'entityCount': 1}], hints=['retry-now']).query_count(
                targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_INVALID')

    def test_an_error_plus_completed_is_a_contradiction(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(documents=[fixture(INSPECT)],
                  errors=[{'code': 'X', 'message': 'y', 'detail': {}}]).query_observe(
                targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_CONTRADICTORY')

    def test_a_hint_on_a_completed_operation_is_a_contradiction(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(documents=[fixture(INSPECT)], hints=['reconcile']).query_observe(
                targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_CONTRADICTORY')

    def test_an_observer_that_raises_is_reported_and_nothing_is_interpreted(self):
        class Exploding:
            def count(self, handle):
                raise RuntimeError('boom')

            def observe(self, handle):
                raise RuntimeError('boom')

        with self.assertRaises(service.QueryRefusal) as caught:
            service.SceneQueryService(Exploding()).query_count(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_CALL_FAILED')
        self.assertEqual(caught.exception.detail['errorType'], 'RuntimeError')

    def test_a_non_mapping_observer_answer_is_refused(self):
        class NotMapping:
            def count(self, handle):
                return ['entityCount', 1]

            def observe(self, handle):
                return None

        with self.assertRaises(service.QueryRefusal) as caught:
            service.SceneQueryService(NotMapping()).query_count(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_INVALID')

    def test_evidence_and_count_blocks_are_shape_checked(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(counts=[{'entityCount': -1}]).query_count(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_INVALID')
        with self.assertRaises(service.QueryRefusal) as caught:
            build(counts=[{'entityCount': True}]).query_count(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_INVALID')
        with self.assertRaises(service.QueryRefusal) as caught:
            build(counts=[{'entityCount': 1}], evidence=['']).query_count(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVER_RESULT_INVALID')

    def test_observe_eventually_needs_a_document(self):
        svc = build(documents=[])
        with self.assertRaises(service.QueryRefusal):
            svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(svc.held()['handles'], {})


# --------------------------------------------------------------------------- #
# 3b. the frozen interface, exercised in the shapes the registration patch emits
# --------------------------------------------------------------------------- #

class PatchShapedObserver:
    """The exact result shapes the entity_server registration patch's observer returns.

    This is the offline composition check for the frozen injected interface: it shows the
    shapes the patch specifies actually produce sane G01 results, without importing,
    starting or touching the server.
    """

    INTERFACE = 'scene-query/observer/v1'
    RUN_REF = '.runtime/game-executor/scene-cli/inspect/20260929-153108-edb0fcdf3e'
    AWAIT_HUMAN = frozenset({
        'ELEVATED_POINTER_MISSING', 'ELEVATED_QUEUE_OUTSIDE_PROJECT_OR_MISSING',
        'ELEVATED_HEARTBEAT_ABSENT', 'ELEVATED_HELPER_NOT_USABLE',
        'ELEVATED_HELPER_BLOCKED', 'ELEVATED_HELPER_DEADLINE_PASSED',
        'DISCOVERY_INTERPRETER_MISSING'})

    def __init__(self, *, document=None, entity_count=None, refusal=None, failure=None):
        self.document = document
        self.entity_count = entity_count
        self.refusal = refusal
        self.failure = failure

    def _refused(self):
        code, message, extra = self.refusal
        return {'interfaceVersion': self.INTERFACE, 'operationState': 'never-claimed',
                'readMode': 'live',
                'error': {'code': code, 'message': message, 'detail': extra},
                'nextActionHint': 'await-human' if code in self.AWAIT_HUMAN else None,
                'evidenceRef': []}

    def _failed(self):
        code, message, extra = self.failure
        return {'interfaceVersion': self.INTERFACE, 'operationState': 'known-failed',
                'readMode': 'live',
                'error': {'code': code, 'message': message, 'detail': extra},
                'nextActionHint': None,
                'evidenceRef': [ref for ref in (extra.get('run'),) if ref]}

    def count(self, handle):
        if self.refusal:
            return self._refused()
        if self.failure:
            return self._failed()
        return {'interfaceVersion': self.INTERFACE, 'operationState': 'known-complete',
                'readMode': 'live', 'error': None, 'nextActionHint': None,
                'evidenceRef': [self.RUN_REF],
                'count': {'entityCount': self.entity_count, 'levelId': LEVEL,
                          'run': self.RUN_REF}}

    def observe(self, handle):
        if self.refusal:
            return self._refused()
        if self.failure:
            return self._failed()
        return {'interfaceVersion': self.INTERFACE, 'operationState': 'known-complete',
                'readMode': 'live', 'error': None, 'nextActionHint': None,
                'evidenceRef': [self.RUN_REF],
                'document': self.document,
                'identity': {'targetHandle': handle, 'levelId': LEVEL, 'observedAt': None,
                             'receiptPath': self.RUN_REF + '/before-context.json',
                             'receiptSha256': PROVENANCE['fixtures'][INSPECT]['fixtureSha256'],
                             'sessionPid': None, 'sessionCreation': None,
                             'sessionSource': 'discovery-receipt'}}


class ExecutionLayerContractTests(unittest.TestCase):
    """The patch's observer shapes, end to end, offline."""

    def test_the_patch_success_shape_reaches_a_backed_live_pass(self):
        svc = service.SceneQueryService(PatchShapedObserver(document=fixture(INSPECT)))
        result = svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['observationLevel'], 'projected')
        stage = result['stages']['liveReadback']
        self.assertEqual(stage['status'], 'pass')
        self.assertEqual(stage['evidenceRef'], [PatchShapedObserver.RUN_REF])
        self.assertEqual(stage['evidenceSha256'],
                         [PROVENANCE['fixtures'][INSPECT]['fixtureSha256']])
        self.assertTrue(result['observation']['complete'])
        self.assertTrue(result['heldForLaterCalls'])

    def test_a_missing_session_identity_stays_null_and_is_visible(self):
        """G01 open item O-4: load_handle exposes no session process creation today."""
        svc = service.SceneQueryService(PatchShapedObserver(document=fixture(INSPECT)))
        bound = svc.query_observe(targetHandle=HANDLE)['targetBinding']
        self.assertIsNone(bound['sessionPid'])
        self.assertIsNone(bound['sessionProcessCreation'])
        self.assertEqual(bound['sessionSource'], 'discovery-receipt')

    def test_the_patch_count_shape_is_count_layer_and_keeps_the_path_out_of_the_answer(self):
        svc = service.SceneQueryService(PatchShapedObserver(entity_count=15))
        result = svc.query_count(targetHandle=HANDLE)
        self.assertEqual(result['observationLevel'], 'count-only')
        self.assertEqual(result['observation']['entityCount'], 15)
        self.assertEqual(result['evidenceRef'], [PatchShapedObserver.RUN_REF])
        self.assertNotIn('snapshotPath', json_of(result))
        self.assertEqual(result['stages']['liveReadback']['status'], 'pass')

    def test_a_handle_refusal_is_a_rejected_call_with_a_blocked_readback(self):
        svc = service.SceneQueryService(PatchShapedObserver(
            refusal=('LEVEL_HANDLE_UNKNOWN', 'no discovery run named this handle', {})))
        result = svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['error']['code'], 'LEVEL_HANDLE_UNKNOWN')
        self.assertEqual(result['stages']['liveReadback']['status'], 'blocked')
        self.assertEqual(result['nextAction'], 'fix-input')
        self.assertFalse(result['writeExecuted'])

    def test_a_dead_helper_asks_for_a_human(self):
        svc = service.SceneQueryService(PatchShapedObserver(
            refusal=('ELEVATED_HEARTBEAT_ABSENT', 'the helper is not running; a human must '
                     'start it', {'queueDir': '.runtime/editor-bridge/x'})))
        result = svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['nextAction'], 'await-human')
        self.assertEqual(result['stages']['liveReadback']['status'], 'blocked')
        self.assertIn('ELEVATED_HEARTBEAT_ABSENT', result['stages']['liveReadback']['reason'])

    def test_a_read_that_failed_after_dispatch_is_fail_not_rejected(self):
        svc = service.SceneQueryService(PatchShapedObserver(
            failure=('READBACK_NOT_ACCEPTED', 'read-only receipt was rejected',
                     {'reasons': ['COMPLETE_ENTITY_SET'], 'run': PatchShapedObserver.RUN_REF})))
        result = svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['stages']['liveReadback']['status'], 'fail')
        self.assertEqual(result['stages']['liveReadback']['evidenceRef'],
                         [PatchShapedObserver.RUN_REF])
        self.assertEqual(result['error']['disposition'], 'failure-after-dispatch')
        self.assertEqual(result['nextAction'], 'report-and-repair')

    def test_an_execution_layer_refusal_keeps_its_detail_without_colliding(self):
        refusal = service.QueryRefusal.from_execution_layer(
            'ELEVATED_HELPER_BLOCKED', 'blocked', detail={'phase': 'x', 'next_action': 'y'},
            next_action='await-human')
        self.assertEqual(refusal.phase, 'observer')
        self.assertEqual(refusal.next_action, 'await-human')
        self.assertEqual(refusal.detail['executionLayerDetail'],
                         {'phase': 'x', 'next_action': 'y'})
        result = service.refusal_result(refusal, capabilityId='scene.observe',
                                        targetHandle=HANDLE)
        self.assertEqual(result['state'], 'rejected')
        self.assertEqual(result['error']['code'], 'ELEVATED_HELPER_BLOCKED')
        self.assertEqual(result['error']['detail']['executionLayerDetail']['phase'], 'x')

    def test_a_refusal_next_action_must_be_a_closed_token(self):
        with self.assertRaises(ValueError):
            service.QueryRefusal('X', 'y', next_action='retry-now')


# --------------------------------------------------------------------------- #
# 4. the count layer is not an observation
# --------------------------------------------------------------------------- #

class CountLayerTests(unittest.TestCase):

    def test_a_count_answers_with_a_count_and_nothing_else(self):
        svc = build(counts=[{'entityCount': 15, 'run': '.runtime/x/run-1',
                             'snapshotPath': '.runtime/x/run-1/before-context.json',
                             'levelId': LEVEL}])
        result = svc.query_count(targetHandle=HANDLE)
        self.assertEqual(result['observationLevel'], 'count-only')
        self.assertEqual(result['observation']['kind'], 'entity-count')
        self.assertEqual(result['observation']['entityCount'], 15)
        blob = json_of(result['observation'])
        for forbidden in ('knownAttributes', 'fieldProvenance', 'unknownFields', 'position',
                          'snapshotPath', 'entityIds'):
            self.assertNotIn('"%s"' % forbidden, blob, forbidden)
        self.assertEqual(result['objectIds'], [])

    def test_the_snapshot_path_is_a_controlled_reference_not_the_answer(self):
        """G01 HONEST-7: a raw snapshot path is never the business answer."""
        svc = build(counts=[{'entityCount': 4, 'run': '.runtime/x/run-1',
                             'snapshotPath': '.runtime/x/run-1/before-context.json'}])
        result = svc.query_count(targetHandle=HANDLE)
        self.assertIn('.runtime/x/run-1/before-context.json', result['evidenceRef'])
        self.assertNotIn('snapshotPath', result['observation'])
        self.assertNotIn('snapshotPath', result)

    def test_a_count_cannot_be_paged_detailed_or_diffed(self):
        svc = build(counts=[{'entityCount': 15}])
        svc.query_count(targetHandle=HANDLE)
        for call in (lambda: svc.query_page(targetHandle=HANDLE),
                     lambda: svc.query_detail(targetHandle=HANDLE, entityId=1),
                     lambda: svc.query_diff(targetHandle=HANDLE)):
            with self.assertRaises(service.QueryRefusal) as caught:
                call()
            self.assertEqual(caught.exception.code, 'COUNT_IS_NOT_AN_OBSERVATION')
        self.assertEqual(svc.held()['countOnlyHandles'], [HANDLE])

    def test_a_count_holds_no_projection_at_all(self):
        svc = build(counts=[{'entityCount': 15}])
        svc.query_count(targetHandle=HANDLE)
        self.assertEqual(svc.held()['handles'], {})

    def test_the_legacy_read_tool_is_relabelled_as_count_layer(self):
        legacy = {'ok': True, 'method': 'mw.scene.readEntities', 'entityCount': 15,
                  'run': '.runtime/game-executor/mcp-business/run-1',
                  'snapshotPath': '.runtime/game-executor/mcp-business/run-1/before-context.json'}
        result = service.label_legacy_read_result(legacy, targetHandle=HANDLE)
        self.assertEqual(result['observationLevel'], 'count-only')
        self.assertEqual(result['observation']['entityCount'], 15)
        self.assertTrue(result['snapshotPathWithheld'])
        self.assertEqual(result['evidenceRef'],
                         [legacy['run'], legacy['snapshotPath']])
        self.assertNotIn('snapshotPath', json_of(result['observation']))
        self.assertIn('paging', result['observation']['cannotAnswer'])
        self.assertEqual(result['stages']['liveReadback']['status'], 'not-run')

    def test_a_legacy_result_that_carries_rows_is_refused(self):
        for payload in ({'ok': True, 'entityCount': 3, 'entities': [{'entityId': 1}]},
                        {'ok': True, 'entityCount': 3,
                         'contract': observation.CONTRACT_ID},
                        {'ok': True, 'entityCount': 3, 'observationLevel': 'projected'}):
            with self.assertRaises(service.QueryRefusal) as caught:
                service.label_legacy_read_result(payload)
            self.assertEqual(caught.exception.code, 'LEGACY_RESULT_CLAIMS_OBSERVATION')

    def test_a_legacy_result_without_a_count_is_refused_rather_than_zeroed(self):
        for payload in ({'ok': True, 'run': '.runtime/x'}, {'ok': True, 'entityCount': None},
                        {'ok': True, 'entityCount': True}):
            with self.assertRaises(service.QueryRefusal) as caught:
                service.label_legacy_read_result(payload)
            self.assertEqual(caught.exception.code, 'LEGACY_RESULT_INVALID')

    def test_a_failed_legacy_read_is_rejected_not_completed(self):
        result = service.label_legacy_read_result({'ok': False, 'entityCount': 0,
                                                   'run': '.runtime/x'})
        self.assertEqual(result['state'], 'rejected')
        self.assertFalse(result['ok'])
        self.assertEqual(result['nextAction'], 'fix-input')

    def test_the_two_layers_never_share_a_handle(self):
        svc = build(counts=[{'entityCount': 15}], documents=[fixture(INSPECT)])
        svc.query_count(targetHandle=HANDLE)
        result = svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['observationLevel'], 'projected')
        self.assertEqual(svc.held()['countOnlyHandles'], [HANDLE])
        self.assertEqual(len(svc.held()['handles'][HANDLE]['snapshotIds']), 1)


# --------------------------------------------------------------------------- #
# 5. unknown / truncated / source markers survive the layer
# --------------------------------------------------------------------------- #

class ObservationLayerTests(unittest.TestCase):

    def test_the_projection_summary_keeps_the_three_verdicts_apart(self):
        _, result = observed()
        summary = result['observation']
        self.assertTrue(summary['readable'])
        self.assertTrue(summary['trusted'])
        self.assertTrue(summary['complete'])
        self.assertFalse(summary['truncated'])
        self.assertEqual(summary['capturedCount'], 15)
        self.assertEqual(summary['totalCount'], 15)
        self.assertEqual(summary['capacity'], 17)
        self.assertEqual(summary['entityCount'], 15)
        self.assertEqual(summary['status']['name'], 'ok')

    def test_a_truncated_set_stays_incomplete_and_says_why(self):
        _, result = observed(documents=[fixture('derived/truncated.derived.json')])
        summary = result['observation']
        self.assertTrue(summary['truncated'])
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['capturedCount'], 15)
        self.assertEqual(summary['totalCount'], 512)
        self.assertIn('ENTITIES_TRUNCATED', summary['refusalCodes'])
        self.assertTrue(summary['invalidatingRefusals'])

    def test_an_unreadable_read_is_not_an_empty_level(self):
        _, result = observed(documents=[fixture('derived/unreadable-empty.derived.json')])
        summary = result['observation']
        self.assertFalse(summary['readable'])
        self.assertFalse(summary['complete'])
        self.assertEqual(summary['entityCount'], 0)
        self.assertIn('SNAPSHOT_STATUS_NOT_OK', summary['refusalCodes'])
        self.assertEqual(result['state'], 'completed',
                         'the read operation completed; what it found is a separate verdict')

    def test_an_untrusted_identity_set_is_reported_not_hidden(self):
        svc, result = observed(documents=[fixture('derived/duplicate-identity.derived.json')])
        self.assertFalse(result['observation']['trusted'])
        self.assertIn('DUPLICATE_ENTITY_IDENTITY', result['observation']['refusalCodes'])
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_detail(targetHandle=HANDLE, entityId=1077936129)
        self.assertEqual(caught.exception.code, 'SNAPSHOT_UNTRUSTED')

    def test_unsourced_attributes_are_declared_for_every_entity(self):
        _, result = observed()
        unsupported = result['observation']['unsupportedAttributes']
        for name in ('rotation', 'scale', 'name', 'graphBindings', 'customVariables'):
            self.assertIn(name, unsupported)
            self.assertTrue(unsupported[name])

    def test_a_subsystem_refusal_is_never_read_as_an_empty_subsystem(self):
        _, result = observed(documents=[fixture('derived/subsystems-refused.derived.json')])
        subsystems = result['observation']['subsystems']
        self.assertEqual(set(subsystems), set(observation.SUBSYSTEM_NAMES))
        for name, block in subsystems.items():
            self.assertEqual(block['state'], 'unknown', name)
            self.assertEqual(block['status'], 'baseline_refused', name)
            self.assertTrue(block['emptyResultIsNotAnObservation'], name)

    def test_an_unsupplied_subsystem_reads_unavailable(self):
        _, result = observed()
        for block in result['observation']['subsystems'].values():
            self.assertEqual(block['state'], 'unavailable')
            self.assertIsNone(block['payload'])

    def test_unrecognised_document_keys_are_listed(self):
        _, result = observed(documents=[fixture('derived/subsystems-refused.derived.json')])
        self.assertIn('subsystems.levelCatalog', result['observation']['unrecognizedDocumentKeys'])

    def test_mixed_observation_times_are_explicit(self):
        _, result = observed(documents=[fixture('derived/labels-geometry-multibyte.derived.json')])
        summary = result['observation']
        self.assertTrue(summary['mixedObservationTimes'])
        self.assertTrue(summary['observationTimes']['attributeBound'])
        self.assertIn('EXTERNAL_BLOCK_UNKNOWN_ENTITY', summary['refusalCodes'])

    def test_the_observation_keeps_its_own_timestamp_and_never_invents_one(self):
        _, result = observed()
        self.assertEqual(result['observation']['observedAt'], '2026-10-02T03:00:00Z')
        self.assertEqual(result['observation']['observedAtSource'], 'execution-layer')
        svc = build(documents=[fixture(INSPECT)],
                    identities=[identity(observedAt=None)])
        blank = svc.query_observe(targetHandle=HANDLE)
        self.assertIsNone(blank['observation']['observedAt'])
        self.assertEqual(blank['observation']['observedAtSource'], 'unavailable')

    def test_a_fixture_document_is_marked_as_one(self):
        _, result = observed(documents=[fixture('derived/truncated.derived.json')])
        self.assertIsNotNone(result['observation']['fixtureMarker'])
        self.assertFalse(result['observation']['fixtureMarker']['live'])

    def test_a_captured_copy_needs_no_fixture_marker_and_still_never_claims_live(self):
        _, result = observed(documents=[fixture(INSPECT)])
        self.assertIsNone(result['observation']['fixtureMarker'])
        self.assertEqual(result['stages']['liveReadback']['status'], 'not-run')

    def test_an_id_list_too_long_is_flagged_not_cut_silently(self):
        document = fixture(INSPECT)
        document = copy.deepcopy(document)
        blank = copy.deepcopy(document['entities'][0])
        for index in range(len(document['entities']), service.MAX_INLINE_IDS + 5):
            row = copy.deepcopy(blank)
            new_id = 2000000000 + index
            row['index'] = index
            row['id'] = new_id
            row['dictionaryKey'] = new_id
            document['entities'].append(row)
        document['counts']['entityCaptured'] = len(document['entities'])
        document['counts']['entityValidEntries'] = len(document['entities'])
        document['counts']['entityCapacity'] = len(document['entities'])
        _, result = observed(documents=[document])
        summary = result['observation']
        self.assertTrue(summary['entityIdsTruncated'])
        self.assertEqual(len(summary['entityIds']), service.MAX_INLINE_IDS)
        self.assertEqual(summary['entityIdsTotal'], len(document['entities']))


# --------------------------------------------------------------------------- #
# 6. paging and cursors
# --------------------------------------------------------------------------- #

class PagingTests(unittest.TestCase):

    def test_a_page_is_bounded_by_items_and_reports_the_true_totals(self):
        svc, _ = observed()
        page = svc.query_page(targetHandle=HANDLE, maxItems=2)
        body = page['page']
        self.assertEqual(page['observation']['returnedCount'], 2)
        self.assertEqual(page['observation']['rowsInSnapshot'], 15)
        self.assertEqual(page['observation']['snapshotTotalCount'], 15)
        self.assertEqual(page['observation']['truncationReason'], 'item-limit')
        self.assertEqual(body['offset'], 0)
        self.assertEqual([row['index'] for row in body['items']], [0, 1])
        self.assertIsInstance(page['observation']['nextCursor'], str)

    def test_the_cursor_reaches_the_end_and_then_stops(self):
        svc, _ = observed()
        seen, cursor, guard = [], None, 0
        while True:
            page = svc.query_page(targetHandle=HANDLE, cursor=cursor, maxItems=4)
            seen += [row['index'] for row in page['page']['items']]
            cursor = page['observation']['nextCursor']
            guard += 1
            self.assertLess(guard, 10)
            if cursor is None:
                break
        self.assertEqual(seen, list(range(15)))
        self.assertEqual(page['observation']['truncationReason'], 'end-of-page')

    def test_a_page_never_reads_as_the_whole_level(self):
        svc, _ = observed(documents=[fixture('derived/truncated.derived.json')])
        page = svc.query_page(targetHandle=HANDLE, maxItems=3)
        self.assertFalse(page['observation']['complete'])
        self.assertTrue(page['observation']['truncated'])
        self.assertEqual(page['observation']['rowsInSnapshot'], 15)
        self.assertEqual(page['observation']['snapshotTotalCount'], 512)
        self.assertIn('only the rows that were captured',
                      page['page']['note'] if 'note' in page['page'] else '')
        self.assertTrue(page['page']['rowCountMeaning'])

    def test_byte_accounting_is_on_utf8_not_on_characters(self):
        svc, _ = observed(documents=[fixture('derived/labels-geometry-multibyte.derived.json')])
        for max_bytes in (4096, 8192, 16384, 262144):
            page = svc.query_page(targetHandle=HANDLE, maxItems=200, maxBytes=max_bytes)
            body = page['page']
            if not body['oversizedItems']:
                self.assertLessEqual(body['bytes'], max_bytes)
            else:
                self.assertEqual(len(body['items']), 1,
                                 'an oversized page returns exactly the one row, whole')
                self.assertEqual(body['truncationReason'], 'single-item-exceeds-max-bytes')
            self.assertEqual(body['bytes'], len(json.dumps(
                body['items'], sort_keys=True, separators=(',', ':'),
                ensure_ascii=False).encode('utf-8')))

    def test_one_object_is_never_cut_apart(self):
        svc, _ = observed()
        page = svc.query_page(targetHandle=HANDLE, maxItems=4, maxBytes=1)
        body = page['page']
        self.assertEqual(len(body['items']), 1)
        self.assertTrue(body['oversizedItems'])
        self.assertEqual(body['truncationReason'], 'single-item-exceeds-max-bytes')
        self.assertEqual(body['items'][0]['entityId'], body['oversizedItems'][0])

    def test_page_limits_are_closed(self):
        svc, _ = observed()
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE, maxItems=1000)
        self.assertEqual(caught.exception.code, 'PAGE_LIMIT_EXCEEDS_MAXIMUM')
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE, maxItems=0)
        self.assertEqual(caught.exception.code, 'PAGE_LIMIT_INVALID')

    def test_a_tampered_cursor_is_refused(self):
        svc, _ = observed()
        cursor = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        body = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8'))
        body['offset'] = 0
        forged = base64.urlsafe_b64encode(json.dumps(body).encode('utf-8')).decode('ascii')
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE, cursor=forged)
        self.assertEqual(caught.exception.code, 'CURSOR_TAMPERED')

    def test_a_cursor_with_a_recomputed_check_but_a_wild_offset_is_refused(self):
        svc, _ = observed()
        cursor = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        body = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8'))
        body['offset'] = 9999
        body.pop('check')
        canonical = json.dumps(body, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False).encode('utf-8').decode('utf-8')
        body['check'] = hashlib.sha256(
            (observation.CURSOR_PEPPER + canonical).encode('utf-8')).hexdigest()[:32]
        forged = base64.urlsafe_b64encode(
            json.dumps(body, sort_keys=True).encode('utf-8')).decode('ascii')
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE, cursor=forged)
        self.assertEqual(caught.exception.code, 'CURSOR_OFFSET_OUT_OF_RANGE')

    def test_a_cursor_from_another_snapshot_is_refused(self):
        svc, _ = observed()
        stale = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        svc2 = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                     identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                 identity(observedAt='2026-10-02T04:00:00Z')])
        svc2.query_observe(targetHandle=HANDLE)
        svc2.query_observe(targetHandle=HANDLE)
        with self.assertRaises(service.QueryRefusal) as caught:
            svc2.query_page(targetHandle=HANDLE, cursor=stale)
        self.assertEqual(caught.exception.code, 'CURSOR_SNAPSHOT_CHANGED')

    def test_a_cursor_survives_an_identical_re_observation_only_by_refusal(self):
        """Even unchanged content is a new snapshot: two reads are two observations."""
        svc = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T05:00:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        cursor = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        svc.query_observe(targetHandle=HANDLE)
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE, cursor=cursor)
        self.assertEqual(caught.exception.code, 'CURSOR_SNAPSHOT_CHANGED')

    def test_a_cursor_cannot_be_carried_to_another_handles_snapshot(self):
        svc = build(documents=[fixture(INSPECT), fixture(CREATE_AFTER)])
        svc.query_observe(targetHandle=HANDLE)
        cursor = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        svc.query_observe(targetHandle='another-handle')
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle='another-handle', cursor=cursor)
        self.assertEqual(caught.exception.code, 'CURSOR_SNAPSHOT_CHANGED')

    def test_paging_without_any_observation_is_refused(self):
        svc = build()
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'OBSERVATION_NOT_HELD')

    def test_a_cursor_binds_to_the_snapshot_not_to_the_process(self):
        """Same material and same identity is the SAME snapshot, so the cursor is honoured.

        This is the deliberate other half of the stale-cursor rule: the binding is the
        snapshot's identity (contract, handle, level, observation time, counts, entity
        digest), not an in-memory token.
        """
        first = build(documents=[fixture(INSPECT)])
        first.query_observe(targetHandle=HANDLE)
        cursor = first.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        second = build(documents=[fixture(INSPECT)])
        result = second.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['currentSnapshotId'],
                         first.held()['handles'][HANDLE]['currentSnapshotId'])
        self.assertEqual(second.query_page(targetHandle=HANDLE, cursor=cursor)['page']['offset'],
                         2)

    def test_a_cursor_from_another_instance_for_later_material_is_refused(self):
        first = build(documents=[fixture(INSPECT)],
                      identities=[identity(observedAt='2026-10-02T03:00:00Z')])
        first.query_observe(targetHandle=HANDLE)
        cursor = first.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        second = build(documents=[fixture(INSPECT)],
                       identities=[identity(observedAt='2026-10-02T09:00:00Z')])
        second.query_observe(targetHandle=HANDLE)
        with self.assertRaises(service.QueryRefusal) as caught:
            second.query_page(targetHandle=HANDLE, cursor=cursor)
        self.assertEqual(caught.exception.code, 'CURSOR_SNAPSHOT_CHANGED')
        self.assertEqual(second.query_page(targetHandle=HANDLE)['page']['offset'], 0)

    def test_a_first_page_can_be_inlined_in_the_observation_and_continued_by_cursor(self):
        svc, result = observed()
        self.assertNotIn('page', result, 'pages are opt-in, so a summary stays bounded')
        svc2 = build(documents=[fixture(INSPECT)])
        first = svc2.query_observe(targetHandle=HANDLE, page=True, maxItems=3)
        self.assertEqual(first['page']['offset'], 0)
        self.assertEqual(len(first['page']['items']), 3)
        self.assertEqual(first['objectIds'], [row['entityId'] for row in first['page']['items']])
        second = svc2.query_page(targetHandle=HANDLE,
                                cursor=first['page']['nextCursor'], maxItems=3)
        self.assertEqual(second['page']['offset'], 3)

    def test_the_page_stage_reuses_the_observation_it_came_from(self):
        svc, observation_result = observed()
        page = svc.query_page(targetHandle=HANDLE, maxItems=2)
        self.assertEqual(page['stages']['liveReadback'], observation_result['stages']['liveReadback'])

    def test_the_retention_bound_evicts_oldest_first_and_says_so(self):
        svc = build(documents=[fixture(INSPECT)] * 5,
                    identities=[identity(observedAt='2026-10-02T0%d:00:00Z' % (n + 1))
                                for n in range(5)])
        svc._held_limit = 3
        ids = [svc.query_observe(targetHandle=HANDLE)['currentSnapshotId'] for _ in range(5)]
        self.assertEqual(len(svc.held()['handles'][HANDLE]['snapshotIds']), 3)
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_diff(targetHandle=HANDLE, beforeSnapshotId=ids[0],
                           afterSnapshotId=ids[-1])
        self.assertEqual(caught.exception.code, 'SNAPSHOT_NOT_HELD')


# --------------------------------------------------------------------------- #
# 7. entity detail
# --------------------------------------------------------------------------- #

class DetailTests(unittest.TestCase):

    def test_a_known_entity_is_returned_by_id_with_its_provenance(self):
        svc, _ = observed()
        result = svc.query_detail(targetHandle=HANDLE, entityId=1077936129)
        body = result['observation']
        self.assertTrue(body['found'])
        self.assertEqual(body['entity']['entityId'], 1077936129)
        self.assertEqual(body['entity']['templateId'], 20001034)
        self.assertIn('fieldProvenance', body['entity'])
        self.assertIn('unknownFields', body['entity'])
        self.assertEqual(result['objectIds'], [1077936129])

    def test_the_detail_answer_carries_exactly_one_entity(self):
        svc, _ = observed()
        result = svc.query_detail(targetHandle=HANDLE, entityId=1077936129)
        blob = json_of(result['observation'])
        self.assertEqual(blob.count('"knownAttributes"'), 1)
        self.assertEqual(blob.count('"fieldProvenance"'), 1)
        self.assertNotIn('entityIds', result['observation'])

    def test_a_missing_entity_is_never_a_confirmed_absence_in_a_truncated_set(self):
        svc, _ = observed(documents=[fixture('derived/truncated.derived.json')])
        result = svc.query_detail(targetHandle=HANDLE, entityId=1077939999)
        body = result['observation']
        self.assertFalse(body['found'])
        self.assertEqual(body['absenceMeaning'], 'no-evidence-truncated-or-incomplete-snapshot')
        self.assertTrue(body['absenceReason'])
        self.assertEqual(result['objectIds'], [])

    def test_a_missing_entity_in_a_complete_set_is_stated_as_such(self):
        svc, _ = observed()
        result = svc.query_detail(targetHandle=HANDLE, entityId=1077939999)
        self.assertEqual(result['observation']['absenceMeaning'],
                         'not-present-in-complete-snapshot')

    def test_an_unread_position_stays_unknown_and_is_never_zero(self):
        """T04's own gap, preserved: no captured receipt ever read a position."""
        svc, _ = observed()
        result = svc.query_detail(targetHandle=HANDLE, entityId=1077936129)
        entity = result['observation']['entity']
        self.assertNotIn('position', entity['knownAttributes'])
        self.assertEqual(entity['fieldProvenance']['position']['status'], 'unknown')
        self.assertIsNone(entity['fieldProvenance']['position']['source'])
        reasons = {entry['field']: entry['reason'] for entry in entity['unknownFields']}
        self.assertIn('NOT zero', reasons['position'])

    def test_a_read_position_is_reported_with_its_own_source(self):
        svc, _ = observed(documents=[fixture('derived/position-known.derived.json')])
        rows = svc.query_page(targetHandle=HANDLE, maxItems=200)['page']['items']
        with_position = [row for row in rows
                         if row['fieldProvenance']['position']['status'] == 'known']
        self.assertTrue(with_position)
        zeros = [row for row in with_position
                 if row['knownAttributes']['position'] == [0.0, 0.0, 0.0]]
        self.assertTrue(zeros, 'the fixture carries one entity exactly at the origin')
        result = svc.query_detail(targetHandle=HANDLE, entityId=zeros[0]['entityId'])
        entity = result['observation']['entity']
        self.assertEqual(entity['knownAttributes']['position'], [0.0, 0.0, 0.0])
        self.assertEqual(entity['fieldProvenance']['position']['status'], 'known')
        self.assertNotIn('position', [entry['field'] for entry in entity['unknownFields']])

    def test_an_invalid_entity_id_is_refused(self):
        svc, _ = observed()
        for bad in (0, -1, None, '1077936129', True, 1.0):
            with self.assertRaises(service.QueryRefusal) as caught:
                svc.query_detail(targetHandle=HANDLE, entityId=bad)
            self.assertEqual(caught.exception.code, 'ENTITY_ID_INVALID')

    def test_a_detail_from_a_set_that_did_not_complete_is_refused(self):
        svc = build(documents=[fixture(INSPECT)], states='known-failed')
        result = svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['heldForLaterCalls'])
        self.assertTrue(result['observationNotHeldReason'])
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_detail(targetHandle=HANDLE, entityId=1077936129)
        self.assertEqual(caught.exception.code, 'OBSERVATION_NOT_HELD')


# --------------------------------------------------------------------------- #
# 8. differences
# --------------------------------------------------------------------------- #

class DiffTests(unittest.TestCase):

    def test_one_observation_is_not_enough_for_a_difference(self):
        svc, _ = observed()
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_diff(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'DIFF_NEEDS_TWO_OBSERVATIONS')

    def test_the_captured_create_pair_reports_exactly_one_addition(self):
        svc = build(documents=[fixture(CREATE_BEFORE), fixture(CREATE_AFTER)],
                    identities=[identity(observedAt='2026-09-29T15:29:43Z'),
                                identity(observedAt='2026-09-29T15:29:44Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        result = svc.query_diff(targetHandle=HANDLE)
        body = result['observation']
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(body['diffState'], 'observed')
        self.assertTrue(body['authoritative'])
        self.assertEqual(body['addedCount'], 1)
        self.assertEqual(body['removedCount'], 0)
        self.assertEqual(body['added'], [1077936132])
        self.assertEqual(body['selectedBy'], 'default-previous-vs-current')
        self.assertEqual(body['counts']['before']['capturedCount'], 14)
        self.assertEqual(body['counts']['after']['capturedCount'], 15)
        self.assertIn(1077936132, result['objectIds'])

    def test_a_same_count_swap_cannot_pass_as_no_change(self):
        before = fixture(INSPECT)
        after = with_swapped_id(before, index=5, new_id=1077936199)
        svc = build(documents=[before, after],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T03:05:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        body = svc.query_diff(targetHandle=HANDLE)['observation']
        self.assertEqual(body['diffState'], 'observed')
        self.assertEqual(body['addedCount'], 1)
        self.assertEqual(body['removedCount'], 1)
        self.assertTrue(body['sameCountDifferentObjects'])
        self.assertEqual(body['added'], [1077936199])

    def test_a_diff_over_an_unreadable_side_is_unknown_and_lists_stay_null(self):
        svc = build(documents=[fixture(INSPECT),
                               fixture('derived/unreadable-empty.derived.json')],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T03:05:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        result = svc.query_diff(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['nextAction'], 'reconcile')
        self.assertEqual(result['error']['code'], 'SNAPSHOT_NOT_READABLE')
        self.assertIsNone(result['observation']['added'])
        self.assertIsNone(result['observation']['removed'])
        self.assertIsNone(result['observation']['addedCount'])

    def test_a_diff_over_wrong_levels_is_refused_with_no_lists(self):
        svc = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T04:00:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        svc._held[HANDLE][-1]['projection'] = dict(svc._held[HANDLE][-1]['projection'],
                                                   levelId=OTHER_LEVEL)
        result = svc.query_diff(targetHandle=HANDLE)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'SNAPSHOT_LEVEL_MISMATCH')
        self.assertEqual(result['observation']['diffState'], 'refused')
        self.assertIsNone(result['observation']['added'])
        self.assertIsNone(result['observation']['removed'])

    def test_explicit_snapshot_ids_are_honoured_and_echoed(self):
        svc = build(documents=[fixture(CREATE_BEFORE), fixture(CREATE_AFTER)],
                    identities=[identity(observedAt='2026-09-29T15:29:43Z'),
                                identity(observedAt='2026-09-29T15:29:44Z')])
        first = svc.query_observe(targetHandle=HANDLE)['currentSnapshotId']
        second = svc.query_observe(targetHandle=HANDLE)['currentSnapshotId']
        result = svc.query_diff(targetHandle=HANDLE, beforeSnapshotId=second,
                                afterSnapshotId=first)
        self.assertEqual(result['observation']['selectedBy'], 'explicit')
        self.assertEqual(result['observation']['added'], [])
        self.assertEqual(result['observation']['removed'], [1077936132])

    def test_half_a_pair_of_snapshot_ids_is_refused(self):
        svc = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T04:00:00Z')])
        first = svc.query_observe(targetHandle=HANDLE)['currentSnapshotId']
        svc.query_observe(targetHandle=HANDLE)
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_diff(targetHandle=HANDLE, beforeSnapshotId=first)
        self.assertEqual(caught.exception.code, 'DIFF_SNAPSHOT_ID_INCOMPLETE')

    def test_a_changed_attribute_is_reported_with_both_sides_sources(self):
        before = fixture('derived/position-known.derived.json')
        after = copy.deepcopy(before)
        target = None
        for row in after['entities']:
            if row['flags']['value'] & 16 and row['position'] != [0.0, 0.0, 0.0]:
                target = row
                break
        self.assertIsNotNone(target, 'the fixture must carry a non-origin read position')
        target['position'] = [float(v) + 1.0 for v in target['position']]
        svc = build(documents=[before, after],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T03:05:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        body = svc.query_diff(targetHandle=HANDLE)['observation']
        position_changes = [c for c in body['changed'] if c['field'] == 'position']
        self.assertEqual(len(position_changes), 1)
        self.assertEqual(position_changes[0]['kind'], 'value-changed')
        self.assertIn('beforeSource', position_changes[0])
        self.assertIn('afterSource', position_changes[0])

    def test_a_null_position_never_equals_the_origin(self):
        before = fixture(INSPECT)
        after = fixture('derived/position-known.derived.json')
        svc = build(documents=[before, after],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T03:05:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        body = svc.query_diff(targetHandle=HANDLE)['observation']
        kinds = {c['kind'] for c in body['changed'] if c['field'] == 'position'}
        self.assertEqual(kinds, {'availability-changed'})
        for change in body['changed']:
            if change['field'] == 'position':
                self.assertNotEqual(change.get('before'), change.get('after'))

    def test_a_large_change_list_is_capped_and_the_true_count_survives(self):
        svc = build(documents=[fixture(INSPECT), fixture('derived/position-known.derived.json')],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T03:05:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        body = svc.query_diff(targetHandle=HANDLE)['observation']
        self.assertLessEqual(len(body['changed']), observation.MAX_DIFF_CHANGES)
        self.assertGreaterEqual(body['changedCount'], len(body['changed']))
        self.assertIsInstance(body['changedTruncated'], bool)

    def test_a_snapshot_that_is_not_held_is_named_not_guessed(self):
        svc = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T04:00:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_diff(targetHandle=HANDLE, beforeSnapshotId='so1-does-not-exist',
                           afterSnapshotId='so1-neither-does-this')
        self.assertEqual(caught.exception.code, 'SNAPSHOT_NOT_HELD')
        self.assertEqual(caught.exception.detail['missing'],
                         ['so1-does-not-exist', 'so1-neither-does-this'])

    def test_the_diff_readback_stage_is_the_weaker_of_its_two_reads(self):
        svc = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T04:00:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(svc.query_diff(targetHandle=HANDLE)['stages']['liveReadback']['status'],
                         'not-run')

    def test_a_live_pair_merges_its_evidence_into_one_pass(self):
        svc = build(documents=[fixture(INSPECT), fixture(INSPECT)],
                    read_modes='live', evidence=('.runtime/fake/run-a',),
                    identities=[identity(observedAt='2026-10-02T03:00:00Z'),
                                identity(observedAt='2026-10-02T04:00:00Z')])
        svc.query_observe(targetHandle=HANDLE)
        svc.query_observe(targetHandle=HANDLE)
        stage = svc.query_diff(targetHandle=HANDLE)['stages']['liveReadback']
        self.assertEqual(stage['status'], 'pass')
        self.assertEqual(stage['evidenceRef'], ['.runtime/fake/run-a'])


# --------------------------------------------------------------------------- #
# 9. the layer never claims a live readback it did not get
# --------------------------------------------------------------------------- #

class LiveClaimDisciplineTests(unittest.TestCase):

    def _status(self, **kwargs):
        svc = build(**kwargs)
        if kwargs.get('counts'):
            return svc.query_count(targetHandle=HANDLE)['stages']['liveReadback']
        return svc.query_observe(targetHandle=HANDLE)['stages']['liveReadback']

    def test_offline_material_never_reaches_a_pass_whatever_it_contains(self):
        documents = (fixture(INSPECT), fixture('derived/truncated.derived.json'),
                     fixture('derived/duplicate-identity.derived.json'),
                     fixture('derived/unreadable-empty.derived.json'),
                     fixture('derived/subsystems-ok.derived.json'))
        for document in documents:
            stage = self._status(documents=[document])
            self.assertEqual(stage['status'], 'not-run', document.get('_fixture', {}).get('mutation'))
            self.assertTrue(stage['reason'])

    def test_a_count_from_a_non_live_layer_never_reaches_a_pass(self):
        self.assertEqual(self._status(counts=[{'entityCount': 3}])['status'], 'not-run')

    def test_the_same_document_reaches_a_pass_only_when_the_layer_says_live(self):
        fixture_stage = self._status(documents=[fixture(INSPECT)])
        live_stage = self._status(documents=[fixture(INSPECT)], read_modes='live')
        self.assertEqual(fixture_stage['status'], 'not-run')
        self.assertEqual(live_stage['status'], 'pass')
        self.assertEqual(live_stage['evidenceRef'], ['.runtime/fake/execution-layer-run'])
        self.assertEqual(live_stage['evidenceSha256'],
                         [PROVENANCE['fixtures'][INSPECT]['fixtureSha256']])

    def test_a_live_read_carrying_a_fixture_document_is_a_contradiction(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(documents=[fixture('derived/truncated.derived.json')],
                  read_modes='live').query_observe(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'READ_MODE_CONTRADICTS_DOCUMENT')

    def test_a_live_read_with_no_evidence_cannot_be_a_pass(self):
        def strip_evidence(result):
            result['evidenceRef'] = []
            if 'identity' in result:
                result['identity'] = dict(result['identity'])
                result['identity']['receiptPath'] = None
                result['identity']['receiptSha256'] = None
            return result

        class NoEvidence(FakeObserver):
            def observe(self, handle):
                return strip_evidence(FakeObserver.observe(self, handle))

            def count(self, handle):
                return strip_evidence(FakeObserver.count(self, handle))

        svc = service.SceneQueryService(NoEvidence(documents=[fixture(INSPECT)], read_modes='live'))
        stage = svc.query_observe(targetHandle=HANDLE)['stages']['liveReadback']
        self.assertEqual(stage['status'], 'unknown')
        self.assertIn('false claim', stage['reason'])
        count_stage = service.SceneQueryService(
            NoEvidence(counts=[{'entityCount': 2}], read_modes='live')
        ).query_count(targetHandle=HANDLE)['stages']['liveReadback']
        self.assertEqual(count_stage['status'], 'unknown')

    def test_a_read_that_never_left_the_layer_is_blocked_not_failed(self):
        result = build(states='never-claimed',
                       errors=[{'code': 'NATIVE_SCENE_HELPER_UNAVAILABLE', 'message': 'x',
                                'detail': {}}]).query_observe(targetHandle=HANDLE)
        self.assertEqual(result['stages']['liveReadback']['status'], 'blocked')
        self.assertEqual(result['state'], 'rejected')

    def test_a_read_still_in_flight_is_unknown(self):
        for state in ('claimed', 'dispatched', 'outcome-unknown'):
            result = build(states=state,
                           errors=[{'code': 'PENDING', 'message': 'x', 'detail': {}}]
                           ).query_observe(targetHandle=HANDLE)
            self.assertEqual(result['stages']['liveReadback']['status'], 'unknown', state)
            self.assertIn(result['state'], ('pending', 'unknown'), state)

    def test_a_read_that_failed_is_fail(self):
        result = build(documents=[fixture(INSPECT)], states='known-failed',
                       read_modes='live',
                       errors=[{'code': 'READBACK_NOT_ACCEPTED', 'message': 'x',
                                'detail': {}}]).query_observe(targetHandle=HANDLE)
        self.assertEqual(result['stages']['liveReadback']['status'], 'fail')
        self.assertEqual(result['state'], 'failed')

    def test_an_untrusted_identity_set_fails_the_stage(self):
        """Built inline from a captured copy: a derived fixture carries a marker and could
        never be reported as a live read in the first place."""
        stage = self._status(documents=[duplicate_identity(fixture(INSPECT))],
                             read_modes='live')
        self.assertEqual(stage['status'], 'fail')
        self.assertIn('not trustworthy', stage['reason'])
        self.assertIn('DUPLICATE', stage['reason'])

    def test_a_snapshot_error_is_surfaced_with_the_projection_code(self):
        svc = build(documents=[fixture('derived/wrong-level.derived.json')],
                    identities=[identity(levelId=LEVEL)])
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_observe(targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'WRONG_LEVEL')
        self.assertEqual(caught.exception.phase, 'projection')

    def test_a_raw_probe_record_is_refused_by_the_projection_not_re_decoded(self):
        with self.assertRaises(service.QueryRefusal) as caught:
            build(documents=[{'snapshotHex': '00', 'beforeSnapshotHex': '00'}]).query_observe(
                targetHandle=HANDLE)
        self.assertEqual(caught.exception.code, 'INPUT_KIND_UNSUPPORTED')


# --------------------------------------------------------------------------- #
# 10. mutation controls: every guarantee above, removed, must be caught
# --------------------------------------------------------------------------- #

def probe_count_layer(m):
    svc = m.SceneQueryService(FakeObserver(counts=[{
        'entityCount': 15, 'run': '.runtime/x/run-1',
        'snapshotPath': '.runtime/x/run-1/before-context.json', 'levelId': LEVEL}]))
    result = svc.query_count(targetHandle=HANDLE)
    if result['observationLevel'] != 'count-only':
        return False
    if 'snapshotPath' in result['observation']:
        return False
    if '.runtime/x/run-1/before-context.json' not in result['evidenceRef']:
        return False
    try:
        svc.query_page(targetHandle=HANDLE)
    except m.QueryRefusal as exc:
        return exc.code == 'COUNT_IS_NOT_AN_OBSERVATION'
    return False


def probe_cursor_is_honoured(m):
    svc = m.SceneQueryService(FakeObserver(documents=[fixture(INSPECT)]))
    svc.query_observe(targetHandle=HANDLE)
    cursor = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
    page = svc.query_page(targetHandle=HANDLE, cursor=cursor, maxItems=2)
    return page['page']['offset'] == 2


def probe_truncation_survives(m):
    svc = m.SceneQueryService(FakeObserver(documents=[fixture('derived/truncated.derived.json')]))
    summary = svc.query_observe(targetHandle=HANDLE)['observation']
    return summary['truncated'] is True and summary['complete'] is False


def probe_offline_never_passes(m):
    svc = m.SceneQueryService(FakeObserver(documents=[fixture(INSPECT)]))
    return svc.query_observe(targetHandle=HANDLE)['stages']['liveReadback']['status'] == 'not-run'


def probe_near_miss_state_refused(m):
    svc = m.SceneQueryService(FakeObserver(counts=[{'entityCount': 1}], states='done'))
    try:
        svc.query_count(targetHandle=HANDLE)
    except m.QueryRefusal as exc:
        return exc.code == 'OBSERVER_RESULT_UNRECOGNIZED_STATE'
    except Exception:
        return False
    return False


def probe_legacy_guard(m):
    try:
        m.label_legacy_read_result({'ok': True, 'entityCount': 3, 'entities': [{'entityId': 1}]})
    except m.QueryRefusal as exc:
        return exc.code == 'LEGACY_RESULT_CLAIMS_OBSERVATION'
    return False


def probe_ok_matches_state(m):
    svc = m.SceneQueryService(FakeObserver(
        states='never-claimed',
        errors=[{'code': 'HELPER_UNAVAILABLE', 'message': 'x', 'detail': {}}]))
    result = svc.query_observe(targetHandle=HANDLE)
    return result['ok'] is False and result['isError'] is True


def probe_unread_position_stays_unknown(m):
    svc = m.SceneQueryService(FakeObserver(documents=[fixture(INSPECT)]))
    svc.query_observe(targetHandle=HANDLE)
    entity = svc.query_detail(targetHandle=HANDLE, entityId=1077936129)['observation']['entity']
    return ('position' not in entity['knownAttributes']
            and entity['fieldProvenance']['position']['status'] == 'unknown')


#: (name, old source text, replacement, probe).  Each replacement must appear exactly once.
MUTATIONS = (
    ('count-view-claims-to-be-a-projection',
     "observation_level='count-only',", "observation_level='projected',", probe_count_layer),
    ('count-layer-registers-as-an-observation',
     'if handle in self._counts:', 'if False:', probe_count_layer),
    ('page-ignores-the-cursor',
     'payload = _observation.page_entities(\n                projection, cursor=cursor,',
     'payload = _observation.page_entities(\n                projection, cursor=None,',
     probe_cursor_is_honoured),
    ('truncation-forced-false',
     "'truncated': projection['truncated'],", "'truncated': False,", probe_truncation_survives),
    ('fixture-material-treated-as-live',
     "if result['readMode'] != 'live':", 'if False:', probe_offline_never_passes),
    ('near-miss-state-accepted',
     'if state not in OPERATION_STATES:', 'if False:', probe_near_miss_state_refused),
    ('legacy-result-guard-removed',
     "or 'entities' in result or \\",
     "or ('entities' in result and False) or \\", probe_legacy_guard),
    ('ok-decoupled-from-state',
     "'ok': state == 'completed',", "'ok': True,", probe_ok_matches_state),
    ('unread-position-filled-with-zero',
     "'entity': detail['entity'],",
     "'entity': dict(detail['entity'], knownAttributes=dict("
     "detail['entity']['knownAttributes'], position=[0.0, 0.0, 0.0])),",
     probe_unread_position_stays_unknown),
)

#: A control mutation that changes nothing any assertion depends on.  Its probe must still
#: pass, which is what shows the probes are not simply always false.
NOOP_MUTATION = ('noop-comment-only-edit',
                 '    #: targetHandle -> count-layer results, kept apart from projections '
                 'on purpose.',
                 '    #: targetHandle -> count-layer results kept apart from projections '
                 'on purpose.',
                 probe_offline_never_passes)


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MutationControlTests(unittest.TestCase):

    SOURCE = ROOT / 'backend/scene_query_service.py'

    def setUp(self):
        self.original = self.SOURCE.read_bytes()
        self.original_sha = hashlib.sha256(self.original).hexdigest()
        self.addCleanup(self._assert_untouched)

    def _assert_untouched(self):
        self.assertEqual(hashlib.sha256(self.SOURCE.read_bytes()).hexdigest(),
                         self.original_sha, 'the mutation control left the module altered')

    def _mutant(self, old, new):
        text = self.original.decode('utf-8')
        self.assertGreaterEqual(text.count(old), 1,
                                'mutation anchor not found: %r' % old[:60])
        mutant_text = text.replace(old, new, 1)
        self.assertNotEqual(mutant_text, text)
        directory = tempfile.mkdtemp(prefix='ds09-mutant-')
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / 'scene_query_service_mutant.py'
        path.write_text(mutant_text, encoding='utf-8', newline='')
        return _load_module(path, 'ds09_mutant_%d' % abs(hash(old)))

    def test_every_guarantee_is_caught_when_removed(self):
        report = []
        for name, old, new, probe in MUTATIONS:
            with self.subTest(mutation=name):
                mutant = self._mutant(old, new)
                self.assertTrue(probe(service), 'the probe itself fails on the real module')
                caught = not probe(mutant)
                report.append({'mutation': name, 'caught': caught})
                self.assertTrue(caught, 'mutation %r was not caught by its probe' % name)
        self.assertEqual(len(report), len(MUTATIONS))

    def test_the_control_mutation_is_not_caught(self):
        name, old, new, probe = NOOP_MUTATION
        mutant = self._mutant(old, new)
        self.assertTrue(probe(mutant), 'the control mutation must not be caught')

    def test_every_probe_anchor_still_exists_exactly_once(self):
        text = self.SOURCE.read_text(encoding='utf-8')
        for name, old, _new, _probe in MUTATIONS + (NOOP_MUTATION,):
            self.assertEqual(text.count(old), 1, 'anchor %r for %s' % (old[:50], name))

    def test_the_mutation_report_is_well_formed(self):
        rows = []
        for name, old, new, _probe in MUTATIONS:
            self.assertIn(old, self.SOURCE.read_text(encoding='utf-8'), name)
            rows.append(name)
        self.assertEqual(len(rows), len(set(rows)))


# --------------------------------------------------------------------------- #
# 11. the reused layer is untouched
# --------------------------------------------------------------------------- #

class ProvenanceTests(unittest.TestCase):

    def test_the_t04_projection_is_byte_identical_to_what_was_verified(self):
        self.assertEqual(sha256_file(ROOT / 'backend/scene_observation.py'), T04_MODULE_SHA256)
        self.assertEqual(sha256_file(ROOT / 'backend/test_scene_observation.py'), T04_TEST_SHA256)

    def test_the_t04_gaps_are_preserved_rather_than_filled_in(self):
        """T04's self-reported gaps, restated by this layer and NOT papered over.

        1. no captured receipt ever read a position: every entity of every captured copy
           reads unknown, so the known-position path exists only as a derived fixture;
        2. no real ``subsystems`` block was ever captured: on captured material both
           subsystems are ``unavailable``, not "empty";
        3. the truncation and read-failure paths likewise exist only as derived cases.
        """
        rows = 0
        for rel in (INSPECT, CREATE_BEFORE, CREATE_AFTER):
            result = observed(documents=[fixture(rel)])[1]
            summary = result['observation']
            self.assertFalse(summary['truncated'], rel)
            for name, block in summary['subsystems'].items():
                self.assertEqual(block['state'], 'unavailable', (rel, name))
            svc = build(documents=[fixture(rel)])
            svc.query_observe(targetHandle=HANDLE)
            collected = []
            cursor = None
            while True:
                page = svc.query_page(targetHandle=HANDLE, cursor=cursor, maxItems=200,
                                      maxBytes=observation.MAX_PAGE_BYTES)
                collected += page['page']['items']
                cursor = page['observation']['nextCursor']
                if cursor is None:
                    break
            self.assertEqual(len(collected), len(fixture(rel)['entities']), rel)
            for row in collected:
                rows += 1
                self.assertEqual(row['fieldProvenance']['position']['status'], 'unknown', rel)
                self.assertNotIn('position', row['knownAttributes'], rel)
        self.assertEqual(rows, 44, '3 captured receipts: 15 + 14 + 15 entity rows')

    def test_the_known_position_and_truncation_paths_are_derived_material_only(self):
        derived = ('derived/position-known.derived.json', 'derived/truncated.derived.json',
                   'derived/entity-read-failure.derived.json')
        for rel in derived:
            meta = PROVENANCE['fixtures'][rel]
            self.assertEqual(meta['kind'], 'derived-reverse-case', rel)
            self.assertIs(meta['notARealObservation'], True, rel)
            self.assertIs(fixture(rel)['_fixture']['live'], False, rel)

    def test_every_fixture_still_matches_its_recorded_digest(self):
        for rel, meta in PROVENANCE['fixtures'].items():
            self.assertEqual(sha256_file(FIXTURES / rel), meta['fixtureSha256'], rel)
            self.assertIs(meta['live'], False, rel)

    def test_no_fixture_is_marked_live(self):
        for rel, meta in PROVENANCE['fixtures'].items():
            if meta.get('kind') == 'derived-reverse-case':
                document = fixture(rel)
                self.assertIs(document['_fixture']['live'], False, rel)
            else:
                self.assertNotIn('_fixture', fixture(rel), rel)

    def test_the_captured_copies_reproduce_the_projection_theories(self):
        """The service consumes the same documents T04 verified; nothing is re-derived."""
        projection = observation.project_snapshot(fixture(INSPECT), identity=identity())
        svc, result = observed()
        self.assertEqual(result['observation']['snapshotId'], projection['snapshotId'])
        self.assertEqual(result['observation']['contentDigest'], projection['contentDigest'])
        self.assertEqual(result['observation']['entityIds'], projection['entityIds'])

    def test_the_service_reuses_the_projection_cursor_machinery(self):
        """Its refusal codes and its detail come from the projection, not a second vocabulary."""
        svc, _ = observed()
        cursor = svc.query_page(targetHandle=HANDLE, maxItems=2)['observation']['nextCursor']
        with self.assertRaises(service.QueryRefusal) as caught:
            svc.query_page(targetHandle=HANDLE, cursor=cursor[:-1] + 'A')
        self.assertIn(caught.exception.code, ('CURSOR_TAMPERED', 'CURSOR_INVALID'))
        self.assertEqual(caught.exception.next_action, 'fix-input')

    def test_the_projection_and_this_layer_agree_on_the_document_version(self):
        self.assertEqual(observation.CONTRACT_ID, 'scene-observation/projection/v1')
        self.assertEqual(observation.SCHEMA_VERSION, 1)
        projection = observation.project_snapshot(fixture(INSPECT), identity=identity())
        self.assertEqual(projection['contract'], observation.CONTRACT_ID)


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #

def _measure(entry, source):
    """Apply one mutation to a byte copy and measure whether its probe catches it."""
    name, old, new, probe = entry
    text = source.decode('utf-8')
    row = {'mutation': name, 'anchorOccurrences': text.count(old)}
    if row['anchorOccurrences'] != 1:
        row.update(caught=False, measured='anchor-not-unique')
        return row
    directory = tempfile.mkdtemp(prefix='ds09-mutant-')
    try:
        path = Path(directory) / 'scene_query_service_mutant.py'
        path.write_text(text.replace(old, new, 1), encoding='utf-8', newline='')
        mutant = _load_module(path, 'ds09_report_%d' % abs(hash(name)))
    finally:
        shutil.rmtree(directory, True)
    try:
        real_ok = probe(service) is True
    except Exception as exc:                       # noqa: BLE001 - recorded, not hidden
        real_ok = 'probe-raised:%s' % type(exc).__name__
    try:
        mutant_ok = probe(mutant) is True
    except Exception as exc:                       # noqa: BLE001
        mutant_ok = 'probe-raised:%s' % type(exc).__name__
    row['probeOnDeliveredModule'] = real_ok
    row['probeOnMutant'] = mutant_ok
    row['caught'] = bool(real_ok) and not mutant_ok
    return row


def _write_mutation_report(path):
    """Measure every mutation control and write the table.

    The delivered module is hashed before and after: a mutation is applied to a byte copy in
    a temp directory, never in place, and the report proves it.
    """
    module = ROOT / 'backend/scene_query_service.py'
    before = sha256_file(module)
    source = module.read_bytes()
    rows = [_measure(entry, source) for entry in MUTATIONS]
    control = _measure(NOOP_MUTATION, source)
    after = sha256_file(module)
    caught = sum(1 for row in rows if row['caught'])
    report = {
        'schemaVersion': 1,
        'module': 'backend/scene_query_service.py',
        'moduleSha256Before': before,
        'moduleSha256After': after,
        'moduleUnchangedByTheControlRun': before == after,
        'mutationsApplied': len(rows),
        'mutationsCaught': caught,
        'allMutationsCaught': caught == len(rows),
        'controlMutation': control,
        'controlMutationNotCaught': control['caught'] is False,
        'note': 'each mutation is applied to a byte copy in a temp directory; the delivered '
                'module is never edited in place, and the before/after hashes show it',
        'mutations': rows,
    }
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8', newline='')
    return 0 if (report['allMutationsCaught'] and report['controlMutationNotCaught']
                 and before == after) else 1


def main(argv):
    if '--mutation-report' in argv:
        index = argv.index('--mutation-report')
        return _write_mutation_report(argv[index + 1])
    # ``module='__main__'`` explicitly: with ``module=None`` and no test names, unittest
    # falls back to DISCOVERY over the working directory and would run every other worker's
    # suite as well.
    unittest.main(module='__main__', argv=[argv[0], '-v'] + [a for a in argv[1:] if a != '--'])


if __name__ == '__main__':
    _status = main(sys.argv)
    sys.exit(0 if _status is None else _status)
