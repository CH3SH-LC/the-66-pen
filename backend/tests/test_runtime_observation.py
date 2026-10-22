"""Offline tests for the runtime-observation projection.

Nothing here starts, connects to or drives Genshin, the Miliastra editor, the elevated
helper, the bridge, UAC or any live MCP session.  There is no live lane in this file at
all: every input is a *synthetic fixture* built by the builders below from field names that
were read out of the real receipts on disk (``EditorAdapter.cs``'s ``RuntimeEvidence()`` and
``LogObserverEvidence()``, ``LevelInitObservation.cs``'s 1022 stream, and the
``full-window-observer.json`` receipt under
``.runtime/verification/interface-experiments-20260927/``), but the values are invented and
every fixture is marked ``_fixture.live = false`` so that it can never be read as an
observation.  See ``FixtureDisciplineTests`` -- the fixture marker is load-bearing, not
decorative.

    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.tests.test_runtime_observation

Two of the tests shell out to the module's own command-line shell with
``sys.executable`` to capture a **real exit code** (0 accepted / 2 named refusal).  That
subprocess runs this same interpreter against this same repository: it opens a manifest and
a couple of JSON documents in a temp directory, and it cannot reach a game, a helper or a
queue because the shell has no such parameter and the test asserts that structurally.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import runtime_observation as ro  # noqa: E402

CASE = 'case-ds03-0001'
LEVEL = 1073741839
OTHER_LEVEL = 1073741834
GAME = {'pid': 31584, 'tid': 4321, 'processCreation': '2026-10-03T07:55:00.0000000Z',
        'image': 'C:/Genshin/GenshinImpact.exe'}
EDITOR = {'pid': 33992, 'image': 'C:/Genshin/BeyondEditor.exe',
          'creationFileTime': '2026-10-03T07:40:00.0000000Z'}
OBSERVATION_ID = 'e9c5a4005de14a93911c648f3d099c60'
REG_TICK = 3175291430318
SAVED_ENTITY = 1077936138
OTHER_ENTITY = 1077936139

W_START = '2026-10-03T09:00:00.0000000Z'
W_REG = '2026-10-03T09:00:00.5000000Z'
W_STOP = '2026-10-03T09:05:00.0000000Z'


def _fixture(note='synthetic', **extra):
    marker = {'kind': 'synthetic-fixture', 'live': False, 'note': note}
    marker.update(extra)
    return marker


def level_init(**over):
    block = {
        'started': True,
        'observationId': OBSERVATION_ID,
        'initStartedUtc': W_START,
        'initStartedTick': 3175291411784,
        'observerTiming': {
            'scope': 'current-observer-instance-only',
            'stopwatchFrequency': 10000000,
            'startedUtc': W_START,
            'startedTick': 3175291426354,
            'registrationCompletedUtc': W_REG,
            'registrationCompletedTick': REG_TICK,
            'stoppedUtc': W_STOP,
            'stoppedTick': 3176491848681,
            'stopReason': 'observer-lease-expired',
            'lastCallbackUtc': '2026-10-03T09:04:00.0000000Z',
            'lastCallbackTick': 3176488867532,
            'lastCallbackScope': 'proxy-entry-including-rejected-or-detached-callbacks',
            'historical1022Inferred': False,
        },
        'source': 'received-1022-packet-observer',
        'sequence': 2,
        'retainedEvents': 2,
        'eventLimit': 16,
        'droppedEvents': 0,
        'overflow': False,
        'events': [
            {'sequence': 1, 'receivedUtc': '2026-10-03T09:01:00.0000000Z',
             'receivedTick': 3175546378678, 'managedThreadId': 1, 'levelId': LEVEL,
             'parsed': True, 'error': None},
            {'sequence': 2, 'receivedUtc': '2026-10-03T09:03:00.0000000Z',
             'receivedTick': 3175549378678, 'managedThreadId': 1, 'levelId': LEVEL,
             'parsed': True, 'error': None},
        ],
        'parseErrors': 0,
        'evidenceErrors': 0,
        'threadErrors': 0,
        'baselinePayloadPresent': True,
        'baselineLevelId': LEVEL,
        'currentPayloadPresent': True,
        'currentLevelId': LEVEL,
    }
    block.update(over)
    return block


def observer_evidence(**over):
    block = {
        'ok': True,
        'active': False,
        'observedPackets': 155,
        'observedLogPackets': 0,
        'ownMarkers': [],
        'observerScanObjects': 0,
        'observerScanLimited': False,
        'packetKinds': {'0': 118, '1022': 1, '1010': 31},
        'scenePacketSnapshots': [{'utc': '2026-10-03T09:02:00.0000000Z', 'id': 1017,
                                  'snapshot': {'type': 'x'}}],
        'observerCleanupError': None,
        'callbackErrors': 0,
        'callbackInvocations': 155,
        'contractRejectedCallbacks': 0,
        'originalReceiversPreserved': True,
        'observerRegistered': True,
        'leaseSeconds': 300,
        'playtestVerified': False,
        'persistentSaveVerified': False,
        'notice': 'Markers may originate from historical debug logs; absence is not proof '
                  'of nonexecution.',
    }
    block.update(over)
    return block


def editor_evidence(**over):
    block = {
        'ok': True,
        'observedUtc': '2026-10-03T09:02:30.0000000Z',
        'editorLevelState': 3,
        'logModelPresent': False,
        'logRecordCount': 0,
        'scannedRecordLimit': 128,
        'ownMarkers': [],
        'markerScanObjects': 0,
        'markerScanLimited': False,
        'graphIds': [1073741825],
        'entityRegistrySlotCount': 22,
        'uniqueEntityModelCount': 11,
        'playtestVerified': False,
        'notice': 'Missing markers do not prove the graph has not executed; this is existing '
                  'editor log cache only.',
    }
    block.update(over)
    return block


def runtime_objects(**over):
    # A run-scope readback must be generation-bound, not only level-bound: an entity id is
    # reused across levels AND across runs of the same level, so the run's generation
    # carriers travel with the readback.
    block = {
        'source': 'runtime-scene-object-readback',
        'levelId': LEVEL,
        'observationId': OBSERVATION_ID,
        'registrationCompletedTick': REG_TICK,
        'sequence': 2,
        'objects': [
            {'entityId': SAVED_ENTITY, 'templateId': 20001034, 'position': [1.0, 2.0, 3.0],
             'observedUtc': '2026-10-03T09:02:10.0000000Z'},
        ],
    }
    block.update(over)
    return block


def run_control(**over):
    block = {
        'contract': 'runtime-control/1',
        'caseId': CASE,
        'startStopMode': 'manual',
        'startedUtc': W_START,
        'stoppedUtc': W_STOP,
        'triggeredBy': 'human-ui',
        'startRequestId': None,
        'stopRequestId': None,
        'gameSession': dict(GAME),
        'levelId': LEVEL,
        'startCommand': None,
        'stopCommand': None,
        'startsPlaytest': False,
    }
    block.update(over)
    return block


def good_bundle(**over):
    bundle = {
        'kind': 'runtime-evidence-bundle',
        'schemaVersion': 1,
        'caseId': CASE,
        'session': dict(GAME),
        'editorSession': dict(EDITOR),
        'levelObservation': {'verified': True, 'levelId': LEVEL},
        'levelInitialization': level_init(),
        'logObserverEvidence': observer_evidence(),
        'editorEvidence': editor_evidence(),
        'runtimeObjects': runtime_objects(),
        'runControl': run_control(),
        'postRunReadback': {'observedUtc': '2026-10-03T09:06:00.0000000Z', 'levelId': LEVEL,
                            'editorLevelState': 3,
                            'source': 'editor-runtime-evidence-readback',
                            'independentReadback': True},
        '_fixture': _fixture('good bundle: one observed static sample in one run'),
    }
    bundle.update(over)
    return bundle


def base_binding(**over):
    binding = {
        'caseId': CASE,
        'expectedLevelId': LEVEL,
        'expectedGameSession': dict(GAME),
        'expectedEditorSession': dict(EDITOR),
        'expectedRunGeneration': None,
        'expectedEntityIds': [SAVED_ENTITY],
        'sourceSha256': None,
        'evidenceMode': 'offline',
    }
    binding.update(over)
    return binding


def refreshing_bundle():
    """A forged document: everything looks live but the marker forbids it."""
    bundle = good_bundle()
    bundle['_fixture'] = _fixture('forged live claim', live=True)
    return bundle


# --------------------------------------------------------------------------- #
# contract surface
# --------------------------------------------------------------------------- #

class ContractSurfaceTests(unittest.TestCase):
    DECLARED = {
        'SCHEMA_VERSION', 'CONTRACT_ID', 'CONTROL_CONTRACT_ID', 'MANIFEST_CONTRACT_ID',
        'SUPPORTED_INPUTS', 'EXECUTION_SURFACE', 'CLI_SURFACE', 'EVIDENCE_MODES',
        'STAGE_STATUSES', 'REFUSAL_CODES', 'AUTHORIZED_TARGET_LEVEL_ID', 'BINDING_FIELDS',
        'FORBIDDEN_BINDING_FIELDS', 'CONTROL_FIELDS', 'FORBIDDEN_CONTROL_FIELDS',
        'CONTROL_CAPABILITIES', 'DS02_CONTROL_CONTRACT_ID', 'DS02_EVIDENCE',
        'DS02_START_STOP_TOKENS',
        'S09_EVIDENCE_ITEMS', 'EVIDENCE_PRODUCERS', 'RUNTIME_OBJECT_SOURCES',
        'EDIT_STATE_SOURCES', 'GENERATION_CARRIER_FIELDS', 'RETURN_TO_EDITOR_SOURCES',
        'EDIT_STATE_PREDICATE', 'STARTS_PLAYTEST', 'ObservationError', 'input_kind',
        'runtime_identity', 'observation_window', 'correlate_objects', 'return_to_editor',
        's09_responsibility', 'normalize_runtime_evidence', 'manifest_template',
    }

    def test_public_api_is_the_declared_closed_set(self):
        self.assertEqual(set(ro.__all__), self.DECLARED)

    def test_the_declared_execution_surface_is_all_false(self):
        self.assertTrue(ro.EXECUTION_SURFACE)
        for key, value in ro.EXECUTION_SURFACE.items():
            self.assertIs(value, False, key)

    def test_library_reaches_no_execution_surface(self):
        """Structural, not a grep: no import or call outside ``main``/``_decode``."""
        tree = ast.parse(pathlib.Path(ro.__file__).read_text(encoding='utf-8'))
        shell = {'main', '_decode'}
        forbidden_modules = {
            'subprocess', 'os', 'socket', 'shutil', 'ctypes', 'importlib', 'sys',
            'pathlib', 'urllib', 'http', 'requests', 'asyncio', 'multiprocessing',
            'winreg', 'signal', 'atexit', 'tempfile', 'argparse', 'pickle',
        }
        forbidden_names = {'eval', 'exec', 'compile', '__import__', 'open', 'input',
                           'breakpoint'}
        forbidden_attributes = {'system', 'popen', 'run', 'call', 'check_output',
                                'spawn', 'fork', 'connect', 'Popen'}
        shell_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.name in shell:
                for inner in ast.walk(node):
                    shell_nodes.add(id(inner))
        found = []
        for node in ast.walk(tree):
            if id(node) in shell_nodes:
                continue
            if isinstance(node, ast.Import):
                found += [a.name.split('.')[0] for a in node.names
                          if a.name.split('.')[0] in forbidden_modules]
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or '').split('.')[0]
                if root in forbidden_modules:
                    found.append(root)
            elif isinstance(node, ast.Name) and node.id in forbidden_names:
                found.append(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                found.append('.' + node.attr)
        self.assertEqual(found, [], 'execution surface outside the shell: %s'
                                    % sorted(set(found)))

    def test_file_io_exists_only_inside_the_shell(self):
        tree = ast.parse(pathlib.Path(ro.__file__).read_text(encoding='utf-8'))
        shell_nodes = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.name in {'main', '_decode'}:
                for inner in ast.walk(node):
                    shell_nodes.add(id(inner))
        outside = []
        for node in ast.walk(tree):
            if id(node) in shell_nodes:
                continue
            if isinstance(node, ast.Name) and node.id == 'open':
                outside.append(node.lineno)
            if isinstance(node, ast.Attribute) and node.attr in ('read_text', 'write_text',
                                                                 'read_bytes', 'write_bytes',
                                                                 'open'):
                outside.append(node.lineno)
        self.assertEqual(outside, [], 'file I/O outside the shell at lines %s' % outside)

    def test_cli_surface_declares_no_game_and_no_overwrite(self):
        self.assertIs(ro.CLI_SURFACE['game'], False)
        self.assertIs(ro.CLI_SURFACE['subprocess'], False)
        self.assertIs(ro.CLI_SURFACE['network'], False)
        self.assertIs(ro.CLI_SURFACE['overwritesExistingOutput'], False)
        self.assertIs(ro.CLI_SURFACE['outputInsideInputDirectory'], False)

    def test_no_public_function_takes_a_path_or_a_command(self):
        forbidden = {'path', 'paths', 'command', 'cmd', 'argv', 'script', 'exe',
                     'executable', 'queue', 'helper', 'request', 'plan', 'pid', 'runId'}
        for name in ('input_kind', 'runtime_identity', 'observation_window',
                     'correlate_objects', 'return_to_editor', 's09_responsibility',
                     'normalize_runtime_evidence', 'manifest_template'):
            parameters = set(inspect.signature(getattr(ro, name)).parameters)
            self.assertEqual(parameters & forbidden, set(), name)

    def test_starts_playtest_is_a_hard_false_constant(self):
        self.assertIs(ro.STARTS_PLAYTEST, False)
        self.assertIs(ro.EXECUTION_SURFACE['startsPlaytest'], False)

    def test_the_control_contract_pins_both_command_fields_to_null(self):
        template = ro.manifest_template(CASE)
        control = template['runControl']
        self.assertIsNone(control['startCommand'])
        self.assertIsNone(control['stopCommand'])
        self.assertIs(control['startsPlaytest'], False)
        self.assertEqual(set(control), set(ro.CONTROL_FIELDS))

    def test_refusal_codes_are_a_closed_exported_set(self):
        self.assertTrue(ro.REFUSAL_CODES)
        for code in ('RUNTIME_LOG_STALE', 'RUNTIME_WINDOW_TRUNCATED', 'RUNTIME_CLOCK_ROLLBACK',
                     'EDIT_STATE_NOT_RUNTIME', 'RUN_IDENTITY_LEVEL_MISMATCH',
                     'RUN_IDENTITY_GENERATION_MISMATCH', 'RUNTIME_MIXED_RUNS',
                     'FIXTURE_CLAIMS_LIVE', 'CONTROL_COMMAND_NOT_REPRESENTABLE'):
            self.assertIn(code, ro.REFUSAL_CODES)


# --------------------------------------------------------------------------- #
# input classification and binding
# --------------------------------------------------------------------------- #

class InputKindTests(unittest.TestCase):
    def test_a_bundle_is_recognised(self):
        self.assertEqual(ro.input_kind(good_bundle()), 'runtime-evidence-bundle')

    def test_a_bare_receipt_is_not_a_bundle(self):
        self.assertEqual(ro.input_kind(observer_evidence()), 'bare-runtime-receipt')

    def test_a_non_mapping_is_named(self):
        self.assertEqual(ro.input_kind(['nope']), 'not-a-mapping')
        self.assertEqual(ro.input_kind('a path string'), 'not-a-mapping')

    def test_a_bare_receipt_is_refused_rather_than_guessed_at(self):
        with self.assertRaises(ro.ObservationError) as caught:
            ro.normalize_runtime_evidence(observer_evidence(), base_binding())
        self.assertEqual(caught.exception.code, 'INPUT_KIND_UNSUPPORTED')


class BindingTests(unittest.TestCase):
    def test_unknown_binding_fields_are_refused(self):
        with self.assertRaises(ro.ObservationError) as caught:
            ro.runtime_identity(good_bundle(), binding=base_binding(whatever=1))
        self.assertEqual(caught.exception.code, 'BINDING_INVALID')

    def test_execution_layer_fields_are_refused_by_name(self):
        for field in ('runId', 'helperPid', 'elevatedQueue', 'scriptPath', 'timeout',
                      'startCommand', 'pid'):
            with self.assertRaises(ro.ObservationError) as caught:
                ro.runtime_identity(good_bundle(), binding=base_binding(**{field: 'x'}))
            self.assertEqual(caught.exception.code, 'BINDING_FORBIDDEN_FIELD', field)

    def test_the_case_id_is_required(self):
        binding = base_binding()
        binding.pop('caseId')
        with self.assertRaises(ro.ObservationError) as caught:
            ro.runtime_identity(good_bundle(), binding=binding)
        self.assertEqual(caught.exception.code, 'BINDING_INVALID')

    def test_the_level_is_required_and_never_defaulted(self):
        binding = base_binding()
        binding.pop('expectedLevelId')
        with self.assertRaises(ro.ObservationError) as caught:
            ro.runtime_identity(good_bundle(), binding=binding)
        self.assertEqual(caught.exception.code, 'BINDING_INVALID')

    def test_an_unknown_evidence_mode_is_refused(self):
        with self.assertRaises(ro.ObservationError) as caught:
            ro.runtime_identity(good_bundle(), binding=base_binding(evidenceMode='pretend-live'))
        self.assertEqual(caught.exception.code, 'BINDING_INVALID')

    def test_a_malformed_source_digest_is_refused(self):
        with self.assertRaises(ro.ObservationError) as caught:
            ro.runtime_identity(good_bundle(), binding=base_binding(sourceSha256='abc'))
        self.assertEqual(caught.exception.code, 'BINDING_INVALID')

    def test_a_source_digest_that_does_not_match_is_refused(self):
        binding = base_binding(sourceSha256='0' * 64)
        with self.assertRaises(ro.ObservationError) as caught:
            ro.normalize_runtime_evidence(good_bundle(), binding)
        self.assertEqual(caught.exception.code, 'SOURCE_DIGEST_MISMATCH')

    def test_a_matching_source_digest_is_accepted(self):
        bundle = good_bundle()
        projection = ro.normalize_runtime_evidence(
            bundle, base_binding(sourceSha256=ro._digest(bundle)))
        self.assertEqual(projection['caseId'], CASE)

    def test_expected_entity_ids_must_be_positive_integers(self):
        for bad in (['abc'], [0], [-3], [True]):
            with self.assertRaises(ro.ObservationError) as caught:
                ro.runtime_identity(good_bundle(), binding=base_binding(expectedEntityIds=bad))
            self.assertEqual(caught.exception.code, 'BINDING_INVALID', bad)


# --------------------------------------------------------------------------- #
# run identity
# --------------------------------------------------------------------------- #

class RunIdentityTests(unittest.TestCase):
    def test_a_complete_bundle_establishes_an_identity(self):
        identity = ro.runtime_identity(good_bundle(), binding=base_binding())
        self.assertTrue(identity['established'])
        self.assertEqual(identity['levelId'], LEVEL)
        self.assertEqual(identity['observationId'], OBSERVATION_ID)
        self.assertEqual(identity['eventCursor']['sequence'], 2)
        self.assertEqual(identity['eventCursor']['levelId'], LEVEL)
        self.assertEqual(identity['derivedGenerationId'],
                         ro.runtime_identity(good_bundle(),
                                             binding=base_binding())['derivedGenerationId'])

    def test_the_generation_id_is_labelled_as_derived_not_minted(self):
        identity = ro.runtime_identity(good_bundle(), binding=base_binding())
        self.assertIn('not a run id this layer minted', identity['derivedGenerationIdMeaning'])

    def test_no_event_cursor_means_no_identity_and_no_generation_id(self):
        bundle = good_bundle(levelInitialization=level_init(
            sequence=0, retainedEvents=0, events=[]))
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertFalse(identity['established'])
        self.assertIsNone(identity['derivedGenerationId'])
        self.assertIsNone(identity['eventCursor'])
        codes = {r['code'] for r in identity['refusals']}
        self.assertIn('RUN_IDENTITY_EVIDENCE_INSUFFICIENT', codes)
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_EVIDENCE_INSUFFICIENT'][0]
        self.assertIn('eventCursor', refusal['detail']['missing'])
        self.assertIn('evidence-insufficient', refusal['detail']['note'])

    def test_an_unparsed_event_is_retained_but_does_not_count(self):
        bundle = good_bundle(levelInitialization=level_init(
            sequence=1, retainedEvents=1, events=[
                {'sequence': 1, 'receivedUtc': '2026-10-03T09:01:00.0000000Z',
                 'receivedTick': 1, 'managedThreadId': 9, 'levelId': LEVEL,
                 'parsed': False, 'error': 'decode-failed'}]))
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertIsNone(identity['eventCursor'])
        self.assertEqual(identity['unparsedEventCount'], 1)
        self.assertEqual(len(identity['events']), 1)  # the gap field is kept, not dropped

    def test_a_wrong_game_session_is_refused(self):
        bundle = good_bundle(session=dict(GAME, pid=99999))
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertFalse(identity['established'])
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_SESSION_MISMATCH'][0]
        self.assertEqual(refusal['detail']['which'], 'game')
        self.assertIn('pid', refusal['detail']['differingFields'])

    def test_a_wrong_editor_session_is_refused(self):
        bundle = good_bundle(editorSession=dict(EDITOR, pid=1))
        identity = ro.runtime_identity(bundle, binding=base_binding())
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_SESSION_MISMATCH'][0]
        self.assertEqual(refusal['detail']['which'], 'editor')

    def test_a_session_field_we_could_not_verify_is_not_a_match(self):
        bundle = good_bundle(session={'pid': GAME['pid']})  # processCreation missing
        identity = ro.runtime_identity(bundle, binding=base_binding())
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_SESSION_MISMATCH'][0]
        self.assertIn('processCreation', refusal['detail']['unverifiedFields'])

    def test_an_absent_session_document_lists_every_unverified_field(self):
        bundle = good_bundle(session=None)
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertFalse(identity['established'])
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_SESSION_MISMATCH'][0]
        self.assertEqual(refusal['detail']['which'], 'game')
        self.assertEqual(refusal['detail']['unverifiedFields'],
                         ['image', 'pid', 'processCreation', 'tid'])

    def test_a_timestamp_without_a_timezone_is_unavailable_not_midnight(self):
        """A naive stamp is not quietly resolved to UTC and placed in the window."""
        naive = level_init(events=[
            {'sequence': 1, 'receivedUtc': '2026-10-03T09:01:00', 'receivedTick': 10,
             'managedThreadId': 1, 'levelId': LEVEL, 'parsed': True, 'error': None}])
        bundle = good_bundle(levelInitialization=naive)
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertIsNone(identity['eventCursor'])   # no usable cursor from a naive stamp
        window = ro.observation_window(bundle, identity=identity)
        self.assertIn('level-init-1022', {r['kind'] for r in window['undatedRecords']})
        self.assertNotIn('level-init-1022', {r['kind'] for r in window['inWindowRecords']})

    def test_a_wrong_level_is_refused_and_names_the_authorised_target(self):
        bundle = good_bundle(levelObservation={'verified': True, 'levelId': OTHER_LEVEL},
                             levelInitialization=level_init(
                                 events=[dict(e, levelId=OTHER_LEVEL)
                                         for e in level_init()['events']]))
        identity = ro.runtime_identity(bundle, binding=base_binding())
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_LEVEL_MISMATCH'][0]
        self.assertEqual(refusal['detail']['observedLevelId'], OTHER_LEVEL)
        self.assertEqual(refusal['detail']['authorizedTargetLevelId'],
                         ro.AUTHORIZED_TARGET_LEVEL_ID)

    def test_an_unverified_native_level_falls_back_to_the_event_payload(self):
        bundle = good_bundle(levelObservation={'verified': False, 'levelId': OTHER_LEVEL})
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertEqual(identity['levelId'], LEVEL)
        self.assertEqual(identity['levelIdSource'], 'received-1022-packet-observer')

    def test_a_previous_generation_of_the_same_level_is_refused(self):
        """The right log for the wrong run: same level, stale generation."""
        bundle = good_bundle()
        binding = base_binding(expectedRunGeneration={
            'observationId': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'sequence': 1, 'registrationCompletedTick': REG_TICK})
        identity = ro.runtime_identity(bundle, binding=binding)
        refusal = [r for r in identity['refusals']
                   if r['code'] == 'RUN_IDENTITY_GENERATION_MISMATCH'][0]
        self.assertIn('observationId', refusal['detail']['differingFields'])
        self.assertIn('previous run of the same level', refusal['message'])

    def test_the_same_generation_re_observed_is_accepted(self):
        bundle = good_bundle()
        binding = base_binding(expectedRunGeneration={
            'observationId': OBSERVATION_ID, 'sequence': 2,
            'registrationCompletedTick': REG_TICK})
        self.assertTrue(ro.runtime_identity(bundle, binding=binding)['established'])

    def test_a_malformed_expected_generation_is_refused(self):
        identity = ro.runtime_identity(good_bundle(),
                                       binding=base_binding(expectedRunGeneration='run-7'))
        codes = {r['code'] for r in identity['refusals']}
        self.assertIn('RUN_IDENTITY_GENERATION_MISMATCH', codes)


# --------------------------------------------------------------------------- #
# observation window
# --------------------------------------------------------------------------- #

class ObservationWindowTests(unittest.TestCase):
    def _window(self, bundle):
        identity = ro.runtime_identity(bundle, binding=base_binding())
        return ro.observation_window(bundle, identity=identity)

    def test_a_healthy_window_is_observed_and_usable(self):
        window = self._window(good_bundle())
        self.assertEqual(window['state'], 'observed')
        self.assertTrue(window['usable'])
        # two 1022 events, one editor-evidence stamp and one packet snapshot
        self.assertEqual(window['inWindowCount'], 4)
        self.assertFalse(window['truncated'])
        self.assertFalse(window['clockRollback'])
        self.assertEqual(window['cursor']['sequence'], 2)

    def test_the_wrong_level_on_every_record_still_reaches_the_window(self):
        """The window is about ordering, not identity: identity refuses separately."""
        bundle = good_bundle(
            levelObservation={'verified': True, 'levelId': OTHER_LEVEL},
            levelInitialization=level_init(
                events=[dict(e, levelId=OTHER_LEVEL) for e in level_init()['events']]))
        identity = ro.runtime_identity(bundle, binding=base_binding())
        self.assertFalse(identity['established'])
        self.assertEqual(ro.observation_window(bundle, identity=identity)['state'], 'observed')

    def test_an_old_log_with_the_same_marker_is_historical_not_evidence(self):
        """The named rejection: markers dated before the window do not count."""
        bundle = good_bundle(editorEvidence=editor_evidence(
            logRecordCount=83, ownMarkers=['MW_BRIDGE_ENTITY_CREATED_20260916'],
            observedUtc='2026-09-16T09:21:08.4813431Z'), _fixture=_fixture('old log'))
        window = self._window(bundle)
        self.assertEqual(window['state'], 'observed')  # the window itself is fine
        self.assertEqual(window['historicalCount'], 1)
        self.assertEqual(window['historicalRecords'][0]['kind'],
                         'editorEvidence.observedUtc')
        self.assertIn('received before the window opened',
                      window['historicalRecords'][0]['historicalBecause'])
        self.assertNotIn('editorEvidence.observedUtc',
                         {r['kind'] for r in window['inWindowRecords']})

    def test_a_bundle_with_no_clock_at_all_is_undated_not_empty(self):
        timing = dict(level_init()['observerTiming'], startedUtc=None, stoppedUtc=None,
                      lastCallbackUtc=None, registrationCompletedUtc=None)
        bundle = good_bundle(
            levelInitialization=level_init(events=[], observerTiming=timing),
            editorEvidence=editor_evidence(observedUtc=None),
            logObserverEvidence=observer_evidence(scenePacketSnapshots=[]),
            postRunReadback=None)
        window = self._window(bundle)
        self.assertEqual(window['state'], 'undated')
        self.assertFalse(window['usable'])
        self.assertIn('not-observed', window['emptyMeaning'])
        self.assertIn('absence is not proof of nonexecution', window['emptyMeaning'])

    def test_an_empty_window_is_not_observed_and_never_did_not_run(self):
        bundle = good_bundle(
            levelInitialization=level_init(sequence=0, retainedEvents=0, events=[],
                                           observerTiming=dict(
                                               level_init()['observerTiming'],
                                               lastCallbackUtc=None)),
            editorEvidence=editor_evidence(observedUtc=None),
            logObserverEvidence=observer_evidence(scenePacketSnapshots=[]),
            postRunReadback=None)
        window = self._window(bundle)
        self.assertEqual(window['state'], 'empty-window')
        self.assertFalse(window['usable'])
        self.assertEqual(window['inWindowCount'], 0)
        self.assertIn('not "it did not run"', window['emptyMeaning'])
        self.assertIn('absence is not proof of nonexecution', window['emptyMeaning'])

    def test_a_truncated_event_ring_is_refused_and_keeps_the_gap(self):
        bundle = good_bundle(levelInitialization=level_init(sequence=5, retainedEvents=2))
        window = self._window(bundle)
        self.assertEqual(window['state'], 'truncated')
        self.assertFalse(window['usable'])
        self.assertTrue(any('retainedEvents' in r for r in window['truncationReasons']))
        self.assertEqual(window['inWindowCount'], 4)  # the records are still returned

    def test_a_full_event_ring_is_a_truncation(self):
        bundle = good_bundle(levelInitialization=level_init(
            sequence=16, retainedEvents=16, eventLimit=16))
        window = self._window(bundle)
        self.assertIn('RUNTIME_WINDOW_TRUNCATED', {r['code'] for r in window['refusals']})

    def test_a_limited_scan_is_a_truncation(self):
        bundle = good_bundle(logObserverEvidence=observer_evidence(observerScanLimited=True))
        self.assertEqual(self._window(bundle)['state'], 'truncated')

    def test_an_undated_cached_reply_is_a_truncation(self):
        bundle = good_bundle(logObserverEvidence=observer_evidence(
            debugLogReply=[{'A': 1}, {'A': 2}]))
        window = self._window(bundle)
        self.assertEqual(window['state'], 'truncated')
        self.assertTrue(any('cached reply' in r for r in window['truncationReasons']))

    def test_dropped_events_are_a_truncation(self):
        bundle = good_bundle(levelInitialization=level_init(droppedEvents=3))
        self.assertEqual(self._window(bundle)['state'], 'truncated')

    def test_a_clock_that_moves_backwards_is_refused(self):
        bundle = good_bundle(levelInitialization=level_init(
            observerTiming=dict(level_init()['observerTiming'],
                                stoppedUtc='2026-10-03T08:00:00.0000000Z')))
        window = self._window(bundle)
        self.assertTrue(window['clockRollback'])
        self.assertEqual(window['state'], 'refused')
        self.assertIn('RUNTIME_CLOCK_ROLLBACK', {r['code'] for r in window['refusals']})

    def test_a_decreasing_sequence_is_refused_and_reported_out_of_order(self):
        bundle = good_bundle(levelInitialization=level_init(
            sequence=2, retainedEvents=2, events=[
                {'sequence': 2, 'receivedUtc': '2026-10-03T09:03:00.0000000Z',
                 'receivedTick': 20, 'managedThreadId': 1, 'levelId': LEVEL,
                 'parsed': True, 'error': None},
                {'sequence': 1, 'receivedUtc': '2026-10-03T09:01:00.0000000Z',
                 'receivedTick': 10, 'managedThreadId': 1, 'levelId': LEVEL,
                 'parsed': True, 'error': None}]))
        window = self._window(bundle)
        self.assertTrue(window['clockRollback'])
        self.assertTrue(any(e['field'] == 'sequence' for e in window['outOfOrder']))
        self.assertEqual(window['state'], 'refused')

    def test_an_event_received_after_the_observer_stopped_is_a_rollback(self):
        bundle = good_bundle(levelInitialization=level_init(
            events=[
                {'sequence': 1, 'receivedUtc': '2026-10-03T09:01:00.0000000Z',
                 'receivedTick': 10, 'managedThreadId': 1, 'levelId': LEVEL,
                 'parsed': True, 'error': None},
                {'sequence': 2, 'receivedUtc': '2026-10-03T09:09:00.0000000Z',
                 'receivedTick': 20, 'managedThreadId': 1, 'levelId': LEVEL,
                 'parsed': True, 'error': None}]))
        window = self._window(bundle)
        self.assertTrue(window['clockRollback'])
        self.assertTrue(any('after the observer stopped' in e['reason']
                            for e in window['clockRollbackEvidence']))

    def test_a_window_must_be_a_projection_of_this_contract(self):
        with self.assertRaises(ro.ObservationError) as caught:
            ro.observation_window(good_bundle(), identity={'contract': 'other/v1'})
        self.assertEqual(caught.exception.code, 'BINDING_CONTRACT_MISMATCH')


# --------------------------------------------------------------------------- #
# W16: window closure gates a pass, and only an integer sequence carries a generation
# --------------------------------------------------------------------------- #

def _never_stopped_bundle():
    """A receipt whose observer never stopped: a placeable start, no stop stamp."""
    return good_bundle(levelInitialization=level_init(
        observerTiming=dict(level_init()['observerTiming'], stoppedUtc=None,
                            stoppedTick=None)))


class WindowClosureTests(unittest.TestCase):
    """windowOpen is a gate, not a decoration: an unclosed window cannot pass."""

    def test_a_window_that_never_stopped_is_not_a_complete_observation(self):
        bundle = _never_stopped_bundle()
        identity = ro.runtime_identity(bundle, binding=base_binding())
        window = ro.observation_window(bundle, identity=identity)
        self.assertIs(window['window']['windowOpen'], True)
        self.assertIs(window['windowClosed'], False)
        self.assertEqual(window['state'], 'open-window')
        self.assertFalse(window['usable'])
        self.assertNotEqual(window['state'], 'observed')
        # the records are still returned, not deleted: an open window is "not a complete
        # observation", never "nothing happened".
        self.assertEqual(window['inWindowCount'], 4)
        self.assertIn('not closed', window['unclosedMeaning'])

    def test_a_closed_window_is_still_observed_and_usable(self):
        bundle = good_bundle()
        identity = ro.runtime_identity(bundle, binding=base_binding())
        window = ro.observation_window(bundle, identity=identity)
        self.assertIs(window['window']['windowOpen'], False)
        self.assertIs(window['windowClosed'], True)
        self.assertEqual(window['state'], 'observed')
        self.assertTrue(window['usable'])
        self.assertIsNone(window['unclosedMeaning'])

    def test_an_open_window_cannot_promote_live_or_a_pass(self):
        bundle = _never_stopped_bundle()
        bundle.pop('_fixture')                      # nothing but the window closure stops
        projection = ro.normalize_runtime_evidence(bundle,                    # a live claim
                                                   base_binding(evidenceMode='live'))
        self.assertEqual(projection['evidenceMode'], 'offline')
        self.assertIs(projection['liveEvidence']['derived'], False)
        self.assertEqual(projection['sampleObserved']['status'], 'blocked')
        self.assertFalse(projection['observationWindow']['usable'])
        self.assertIn('not usable', ' '.join(projection['liveEvidence']['whyNotLive']))

    def test_an_open_window_is_blocked_not_failed_in_s09(self):
        projection = ro.normalize_runtime_evidence(_never_stopped_bundle(), base_binding())
        item = projection['s09']['items']['runtime-observation']
        self.assertEqual(item['state'], 'open-window')
        self.assertEqual(item['status'], 'blocked')
        self.assertFalse(item['usable'])

    def test_a_window_with_no_receipt_at_all_is_not_usable(self):
        bundle = good_bundle()
        bundle.pop('levelInitialization')           # no observer registration: no window
        identity = ro.runtime_identity(bundle, binding=base_binding())
        window = ro.observation_window(bundle, identity=identity)
        self.assertIsNone(window['windowOpen'])
        self.assertFalse(window['windowClosed'])
        self.assertEqual(window['state'], 'unbounded-window')
        self.assertFalse(window['usable'])
        self.assertTrue(window['inWindowCount'])    # the dated editor stamp is kept


class GenerationCarrierTests(unittest.TestCase):
    """The 1022 event cursor is the only generation carrier, and it needs an int."""

    def _identity_with_sequences(self, *values):
        events = [dict(e, sequence=v) for e, v in zip(level_init()['events'], values)]
        return ro.runtime_identity(good_bundle(levelInitialization=level_init(events=events)),
                                   binding=base_binding())

    def test_a_non_integer_sequence_is_not_a_generation_carrier(self):
        for value in ('3', None, True, 2.0):
            identity = self._identity_with_sequences(value, value)
            self.assertIsNone(identity['eventCursor'], value)
            self.assertIsNone(identity['derivedGenerationId'], value)
            self.assertFalse(identity['established'], value)
            self.assertIn('RUN_IDENTITY_EVIDENCE_INSUFFICIENT',
                          {r['code'] for r in identity['refusals']}, value)
            refusal = [r for r in identity['refusals']
                       if r['code'] == 'RUN_IDENTITY_EVIDENCE_INSUFFICIENT'][0]
            self.assertIn('eventCursor', refusal['detail']['missing'], value)

    def test_a_non_integer_sequence_cannot_match_an_expected_generation(self):
        """Old behaviour: want '9' == cursor '9' read as agreement. That is not a match."""
        events = [dict(e, sequence='9') for e in level_init()['events']]
        bundle = good_bundle(levelInitialization=level_init(events=events))
        binding = base_binding(expectedRunGeneration={
            'observationId': OBSERVATION_ID, 'sequence': '9',
            'registrationCompletedTick': REG_TICK})
        identity = ro.runtime_identity(bundle, binding=binding)
        self.assertFalse(identity['established'])
        self.assertIn('RUN_IDENTITY_GENERATION_MISMATCH',
                      {r['code'] for r in identity['refusals']})

    def test_a_non_integer_sequence_event_is_reported_but_not_counted_as_unparsed(self):
        """The event parsed and is dated; only its sequence disqualifies it as a cursor."""
        identity = self._identity_with_sequences('3', '3')
        self.assertEqual(identity['unparsedEventCount'], 0)
        self.assertEqual([e['sequence'] for e in identity['events']], ['3', '3'])
        self.assertIsNone(identity['eventCursor'])

    def test_an_integer_sequence_still_carries_the_generation(self):
        identity = self._identity_with_sequences(1, 'not-an-int')
        self.assertTrue(identity['established'])
        self.assertEqual(identity['eventCursor']['sequence'], 1)
        self.assertFalse(isinstance(identity['eventCursor']['sequence'], bool))
        self.assertTrue(identity['derivedGenerationId'])

    def test_the_cursor_is_the_highest_integer_sequence_not_the_last_row(self):
        identity = self._identity_with_sequences(7, 3)
        self.assertEqual(identity['eventCursor']['sequence'], 7)


# --------------------------------------------------------------------------- #
# object correlation
# --------------------------------------------------------------------------- #

class CorrelationTests(unittest.TestCase):
    def _correlate(self, bundle, expected=None):
        identity = ro.runtime_identity(bundle, binding=base_binding())
        return ro.correlate_objects(bundle, identity=identity,
                                    expectedEntityIds=expected if expected is not None
                                    else [SAVED_ENTITY])

    def test_the_saved_sample_observed_in_the_run_is_a_pass(self):
        result = self._correlate(good_bundle())
        self.assertEqual(result['status'], 'pass')
        self.assertTrue(result['usable'])
        self.assertEqual(result['matched'], [SAVED_ENTITY])

    def test_an_editor_state_catalog_is_refused_not_reinterpreted(self):
        bundle = good_bundle(runtimeObjects=None,
                             editorCatalog={'source': 'editor-entity-catalog',
                                            'sourceKind': 'edit-time-entity-list',
                                            'entities': [{'entityId': SAVED_ENTITY}]})
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['code'], 'EDIT_STATE_NOT_RUNTIME')
        self.assertIn('EDIT_STATE_NOT_RUNTIME', {r['code'] for r in result['refusals']})

    def test_without_any_runtime_reader_the_item_is_blocked_not_passed(self):
        bundle = good_bundle(runtimeObjects=None)
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['code'], 'CORRELATION_NOT_A_RUNTIME_OBSERVATION')
        self.assertIn('runtime-scene-object-readback',
                      result['requiredReader']['mustCarry'])

    def test_a_non_runtime_source_is_refused(self):
        bundle = good_bundle(runtimeObjects=runtime_objects(source='formal-save-parse'))
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['code'], 'RUNTIME_OBJECT_SOURCE_UNSUPPORTED')

    def test_a_readback_from_another_level_is_refused(self):
        bundle = good_bundle(runtimeObjects=runtime_objects(levelId=OTHER_LEVEL))
        result = self._correlate(bundle)
        self.assertEqual(result['code'], 'RUN_IDENTITY_LEVEL_MISMATCH')

    def test_a_stale_readback_is_refused(self):
        bundle = good_bundle(runtimeObjects=runtime_objects(objects=[
            {'entityId': SAVED_ENTITY, 'observedUtc': '2026-09-16T09:00:00.0000000Z'}]))
        result = self._correlate(bundle)
        self.assertEqual(result['code'], 'RUNTIME_LOG_STALE')

    def test_a_label_only_match_is_refused(self):
        bundle = good_bundle(runtimeObjects=runtime_objects(objects=[
            {'label': 'my-saved-sample', 'observedUtc': '2026-10-03T09:02:10.0000000Z'}]))
        result = self._correlate(bundle)
        self.assertEqual(result['code'], 'CORRELATION_TEXT_ONLY')
        self.assertIn('a label is not an identity', result['reason'] + ' ' +
                      result['refusals'][0]['message'])

    def test_a_duplicated_entity_id_is_ambiguous_not_matched(self):
        bundle = good_bundle(runtimeObjects=runtime_objects(objects=[
            {'entityId': SAVED_ENTITY, 'observedUtc': '2026-10-03T09:02:10.0000000Z'},
            {'entityId': SAVED_ENTITY, 'observedUtc': '2026-10-03T09:02:20.0000000Z'}]))
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['ambiguous'], [SAVED_ENTITY])
        self.assertEqual(result['matched'], [])

    def test_a_missing_expected_entity_is_fail_not_pass(self):
        result = self._correlate(good_bundle(), expected=[SAVED_ENTITY, OTHER_ENTITY])
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['missing'], [OTHER_ENTITY])

    def test_an_unexpected_extra_object_does_not_fake_a_pass(self):
        bundle = good_bundle(runtimeObjects=runtime_objects(objects=[
            {'entityId': SAVED_ENTITY, 'observedUtc': '2026-10-03T09:02:10.0000000Z'},
            {'entityId': OTHER_ENTITY, 'observedUtc': '2026-10-03T09:02:11.0000000Z'}]))
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['unexpected'], [OTHER_ENTITY])

    def test_no_expected_ids_is_not_run_not_an_empty_success(self):
        bundle = good_bundle()
        identity = ro.runtime_identity(bundle, binding=base_binding())
        result = ro.correlate_objects(bundle, identity=identity, expectedEntityIds=[])
        self.assertEqual(result['status'], 'not-run')
        self.assertFalse(result['usable'])

    # -- same level AND same generation: an id match alone is not this run ----------------

    def test_a_readback_of_a_previous_generation_is_refused(self):
        """Right level, wrong run: the previous run of this same level is not this run."""
        bundle = good_bundle(runtimeObjects=runtime_objects(
            observationId='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'))
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['code'], 'RUN_IDENTITY_GENERATION_MISMATCH')
        self.assertIs(result['matchesIdentityLevel'], True)
        self.assertIs(result['matchesIdentityGeneration'], False)
        self.assertIn('observationId', result['refusals'][0]['detail']['differingFields'])
        self.assertEqual(result['matched'], [])

    def test_a_readback_with_no_generation_carrier_is_blocked_not_passed(self):
        """Level-matched is not enough; with no carrier a same-level re-read cannot be told
        apart from this run, so the item is blocked rather than accepted."""
        bundle = good_bundle(runtimeObjects=runtime_objects(
            observationId=None, registrationCompletedTick=None, sequence=None))
        result = self._correlate(bundle)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['code'], 'CORRELATION_GENERATION_UNBOUND')
        self.assertFalse(result['usable'])
        self.assertIn('observationId',
                      result['requiredGenerationCarrier'])

    def test_a_carrier_that_cannot_be_compared_is_not_a_match(self):
        """The run supplies a sequence; a readback naming a different one is a mismatch."""
        bundle = good_bundle(runtimeObjects=runtime_objects(sequence=99))
        result = self._correlate(bundle)
        self.assertEqual(result['code'], 'RUN_IDENTITY_GENERATION_MISMATCH')
        self.assertIn('sequence', result['refusals'][0]['detail']['differingFields'])

    def test_a_same_generation_readback_is_accepted(self):
        result = self._correlate(good_bundle())
        self.assertEqual(result['status'], 'pass')
        self.assertIs(result['matchesIdentityGeneration'], True)
        self.assertEqual(result['observedGeneration']['observationId'], OBSERVATION_ID)


# --------------------------------------------------------------------------- #
# return to editor
# --------------------------------------------------------------------------- #

class ReturnToEditorTests(unittest.TestCase):
    def test_return_to_editor_is_unknown_with_no_producer(self):
        bundle = good_bundle()
        identity = ro.runtime_identity(bundle, binding=base_binding())
        back = ro.return_to_editor(bundle, identity=identity)
        self.assertEqual(back['status'], 'unknown')
        self.assertFalse(back['usable'])
        self.assertIsNone(back['producer'])
        self.assertEqual(back['code'], 'RETURN_TO_EDITOR_READER_UNCONTRACTED')
        self.assertIn('no contracted reader', back['reason'])

    def test_a_supplied_readback_is_kept_and_never_counts_toward_a_pass(self):
        bundle = good_bundle()
        identity = ro.runtime_identity(bundle, binding=base_binding())
        back = ro.return_to_editor(bundle, identity=identity)
        observed = back['observedPostRunReadback']
        self.assertTrue(observed['afterWindowStop'])
        self.assertTrue(observed['matchesRunLevel'])
        self.assertIs(back['countsTowardPass'], False)
        self.assertEqual(back['status'], 'unknown')

    def test_a_readback_before_the_stop_is_recorded_as_not_after_the_stop(self):
        bundle = good_bundle(postRunReadback={'observedUtc': '2026-10-03T09:02:00.0000000Z',
                                              'levelId': LEVEL})
        identity = ro.runtime_identity(bundle, binding=base_binding())
        back = ro.return_to_editor(bundle, identity=identity)
        self.assertFalse(back['observedPostRunReadback']['afterWindowStop'])
        self.assertEqual(back['status'], 'unknown')

    # -- the reader is implemented; the predicate is what is missing --------------------

    def test_the_reader_accepts_a_proven_source_readback_but_still_unknown(self):
        bundle = good_bundle()
        identity = ro.runtime_identity(bundle, binding=base_binding())
        back = ro.return_to_editor(bundle, identity=identity)
        self.assertIs(back['readbackAccepted'], True)
        self.assertIs(back['reader']['implemented'], True)
        self.assertIs(back['reader']['predicateContracted'], False)
        self.assertEqual(back['reader']['blockedBy'], 'edit-state-predicate-not-contracted')
        self.assertEqual(back['status'], 'unknown')
        self.assertIs(back['countsTowardPass'], False)

    def test_a_readback_from_an_unproven_source_is_refused(self):
        bundle = good_bundle(postRunReadback={
            'observedUtc': '2026-10-03T09:06:00.0000000Z', 'levelId': LEVEL,
            'editorLevelState': 3, 'source': 'editor-level-state-read',
            'independentReadback': True})
        identity = ro.runtime_identity(bundle, binding=base_binding())
        back = ro.return_to_editor(bundle, identity=identity)
        self.assertIs(back['readbackAccepted'], False)
        codes = {r['code'] for r in back['refusals']}
        self.assertIn('RETURN_TO_EDITOR_SOURCE_UNSUPPORTED', codes)
        self.assertEqual(back['status'], 'unknown')

    def test_a_readback_from_another_level_is_refused(self):
        bundle = good_bundle(postRunReadback={
            'observedUtc': '2026-10-03T09:06:00.0000000Z', 'levelId': OTHER_LEVEL,
            'editorLevelState': 3, 'source': 'editor-runtime-evidence-readback',
            'independentReadback': True})
        identity = ro.runtime_identity(bundle, binding=base_binding())
        back = ro.return_to_editor(bundle, identity=identity)
        self.assertIn('RUN_IDENTITY_LEVEL_MISMATCH',
                      {r['code'] for r in back['refusals']})
        self.assertIs(back['readbackAccepted'], False)

    def test_the_edit_state_predicate_is_uncontracted_and_cites_its_basis(self):
        predicate = ro.EDIT_STATE_PREDICATE
        self.assertIs(predicate['contracted'], False)
        self.assertIsNone(predicate['expectedValue'])
        self.assertIsNone(predicate['authority'])
        self.assertIn('INTERFACE-INVENTORY', predicate['basis'])
        # The basis names the real observed values, not a convenient single one.
        self.assertIn('3 and 5', predicate['basis'])
        self.assertEqual(predicate['observedValues'], [3, 5])
        # Nothing the caller can put in a bundle flips the predicate or the verdict.
        for readback in ({'observedUtc': '2026-10-03T09:06:00.0000000Z', 'levelId': LEVEL,
                          'editorLevelState': 3,
                          'source': 'editor-runtime-evidence-readback',
                          'independentReadback': True, 'contracted': True,
                          'expectedValue': 3, 'authority': 'me'},
                         {'observedUtc': '2026-10-03T09:06:00.0000000Z', 'levelId': LEVEL,
                          'editorLevelState': 0,
                          'source': 'editor-runtime-evidence-readback',
                          'independentReadback': True}):
            bundle = good_bundle(postRunReadback=readback)
            identity = ro.runtime_identity(bundle, binding=base_binding())
            back = ro.return_to_editor(bundle, identity=identity)
            self.assertEqual(back['status'], 'unknown')
            self.assertIs(back['countsTowardPass'], False)


# --------------------------------------------------------------------------- #
# S09 responsibility
# --------------------------------------------------------------------------- #

class S09ResponsibilityTests(unittest.TestCase):
    def test_the_five_items_are_the_frozen_five(self):
        self.assertEqual(ro.S09_EVIDENCE_ITEMS,
                         ('current-run-identity', 'start-and-stop',
                          'runtime-object-correlation', 'runtime-observation',
                          'return-to-editor'))

    def test_the_producer_map_names_who_owns_each_item(self):
        this_module = ro.EVIDENCE_PRODUCERS['current-run-identity']['producer']
        self.assertEqual(this_module, 'backend/runtime_observation.py')
        self.assertEqual(ro.EVIDENCE_PRODUCERS['runtime-observation']['producer'],
                         'backend/runtime_observation.py')
        self.assertEqual(ro.EVIDENCE_PRODUCERS['runtime-object-correlation']['producer'],
                         'backend/runtime_observation.py')
        self.assertIsNone(ro.EVIDENCE_PRODUCERS['start-and-stop']['producer'])
        self.assertIs(ro.EVIDENCE_PRODUCERS['start-and-stop']['measuredNegativeFinding'], True)
        self.assertEqual(ro.EVIDENCE_PRODUCERS['start-and-stop']['code'],
                         'RUN_CONTROL_UNAVAILABLE')
        self.assertEqual(ro.EVIDENCE_PRODUCERS['start-and-stop']['status'],
                         'manual-step-required')
        self.assertIsNone(ro.EVIDENCE_PRODUCERS['return-to-editor']['producer'])
        self.assertEqual(ro.EVIDENCE_PRODUCERS['return-to-editor']['status'], 'unavailable')

    def test_no_item_is_claimed_as_autonomous(self):
        for name, entry in ro.EVIDENCE_PRODUCERS.items():
            self.assertIs(entry['autonomous'], False, name)

    def test_this_module_produces_three_items_and_owns_none_of_the_other_two(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        summary = projection['s09']['producerSummary']
        self.assertEqual(sorted(summary['producedByThisModule']),
                         ['current-run-identity', 'runtime-object-correlation',
                          'runtime-observation'])
        self.assertEqual(summary['noAutomatedProducerMeasured'], ['start-and-stop'])
        self.assertEqual(summary['humanOnlyProducer'], ['start-and-stop'])
        self.assertEqual(summary['noProducer'], ['return-to-editor'])
        # The old wording is gone on purpose: this is not a missing dependency.
        self.assertNotIn('blockedOnRuntimeControl', summary)

    def test_without_a_control_record_start_and_stop_is_unavailable(self):
        projection = ro.normalize_runtime_evidence(good_bundle(runControl=None),
                                                   base_binding())
        item = projection['s09']['items']['start-and-stop']
        self.assertEqual(item['status'], 'blocked')
        self.assertEqual(item['capability'], 'RUN_CONTROL_UNAVAILABLE')
        self.assertIn('does not invent a start-playtest command',
                      projection['s09']['runControl']['note'])

    def test_a_human_run_is_recorded_but_never_becomes_a_pass(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        item = projection['s09']['items']['start-and-stop']
        self.assertEqual(item['capability'], 'manual-step-required')
        self.assertEqual(item['ds02ItemToken'], 'manual-step-required')
        self.assertEqual(item['status'], 'blocked')
        self.assertNotEqual(item['status'], 'pass')
        self.assertIs(projection['s09']['runControl']['autonomousGateComplete'], False)


class DS02BindingTests(unittest.TestCase):
    """The freeze is bound to DS-02's measured negative, not to a missing file."""

    def test_the_evidence_block_is_well_formed(self):
        evidence = ro.DS02_EVIDENCE
        self.assertEqual(evidence['contract'], 't12-ds02-run-control-contract/1')
        self.assertEqual(evidence['findingKind'], 'measured-negative')
        self.assertEqual(evidence['verdict'], 'RUN_CONTROL_UNAVAILABLE')
        self.assertIs(evidence['manualStepRequired'], True)
        self.assertIs(evidence['autonomyVerified'], False)
        self.assertIs(evidence['notFoundIsNotAbsent'], True)
        self.assertGreaterEqual(evidence['surfacesSearched'], 10)
        for key in ('adjudicatorSha256', 'testsSha256', 'surfaceCatalogSha256',
                    'verdictManualPositiveSha256', 'verdictRouteNegativeSha256'):
            digest = evidence[key]
            self.assertEqual(len(digest), 64, key)
            self.assertEqual(digest, digest.lower(), key)
            self.assertTrue(all(c in '0123456789abcdef' for c in digest), key)

    def test_the_recorded_digests_still_match_the_delivered_files(self):
        """Read-only re-check against disk, skipped when the delivery is absent."""
        root = ROOT / '.runtime/cordis-plan-work/T12-ds02-parallel-20261002'
        pairs = (
            ('adjudicator', 'adjudicatorSha256'),
            ('tests', 'testsSha256'),
            ('surfaceCatalog', 'surfaceCatalogSha256'),
            ('verdictManualPositive', 'verdictManualPositiveSha256'),
            ('verdictRouteNegative', 'verdictRouteNegativeSha256'),
        )
        checked = 0
        for path_key, digest_key in pairs:
            path = ROOT / ro.DS02_EVIDENCE[path_key]
            if not path.exists():
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual, ro.DS02_EVIDENCE[digest_key],
                             '%s changed; the DS-02 freeze must be re-frozen deliberately'
                             % ro.DS02_EVIDENCE[path_key])
            checked += 1
        if checked == 0:
            self.skipTest('DS-02 delivery not present in this checkout')

    def test_reason_is_a_measurement_not_a_missing_dependency(self):
        projection = ro.normalize_runtime_evidence(good_bundle(runControl=None),
                                                   base_binding())
        finding = projection['s09']['startStopFinding']
        self.assertEqual(finding['kind'], 'measured-negative')
        self.assertIn('no programmable start/stop playtest entry exists', finding['statement'])
        self.assertIn('not an absence of a file', finding['statement'])
        self.assertIn('global-metadata.dat', finding['explicitlyNotClaimed'])
        self.assertEqual(finding['surfacesSearched'], 10)

    def test_the_start_stop_minimal_gap_names_the_missing_input(self):
        projection = ro.normalize_runtime_evidence(good_bundle(runControl=None),
                                                   base_binding())
        gap = projection['s09']['startStopFinding']['minimalGap']
        self.assertEqual(gap['kind'], 'measured-negative')
        self.assertIn('level-state enumeration', gap['missingInput'])
        self.assertIn('return-to-editor', gap['whyThisIsTheMinimum'])
        self.assertIn('start', gap['notClosedByThisModule'])
        self.assertEqual(projection['s09']['startStopFinding']['provenStartStopPath'],
                         'the official editor UI, pressed by a human')

    def test_run_control_is_unavailable_even_when_a_human_run_was_recorded(self):
        """DS-02's probe returns RUN_CONTROL_UNAVAILABLE regardless of who triggered it."""
        for bundle in (good_bundle(), good_bundle(runControl=None)):
            projection = ro.normalize_runtime_evidence(bundle, base_binding())
            control = projection['s09']['runControl']
            self.assertEqual(control['runControl'], 'RUN_CONTROL_UNAVAILABLE')
            self.assertEqual(control['capability'], 'RUN_CONTROL_UNAVAILABLE'
                             if bundle.get('runControl') is None
                             else 'manual-step-required')

    def test_our_verdict_agrees_with_ds02_on_the_decisive_fields(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        agreement = projection['s09']['ds02Agreement']
        self.assertIs(agreement['runControlAgrees'], True)
        self.assertIs(agreement['autonomyAgrees'], True)
        self.assertIs(agreement['agreesThatStartAndStopIsNotClosed'], True)
        self.assertEqual(agreement['ds02RunControl'], 'RUN_CONTROL_UNAVAILABLE')
        self.assertEqual(agreement['ourRunControl'], 'RUN_CONTROL_UNAVAILABLE')
        self.assertIs(agreement['ourAutonomyVerified'], False)

    def test_the_token_vocabulary_difference_is_named_not_hidden(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        agreement = projection['s09']['ds02Agreement']
        self.assertIn('manual-step-required', agreement['ds02ItemTokenVocabulary'])
        self.assertIn("neither is in G01 D10's closed stage set",
                      agreement['tokenVocabularyDifference'])
        self.assertEqual(agreement['ourItemToken'], 'manual-step-required')
        # our own status stays inside the closed G01 D10 set
        self.assertIn(projection['s09']['items']['start-and-stop']['status'],
                      ro.STAGE_STATUSES)

    def test_ds02_tokens_are_a_closed_declared_set(self):
        self.assertEqual(ro.DS02_START_STOP_TOKENS,
                         ('manual-step-required', 'blocked', 'rejected',
                          'evidence-insufficient'))
        self.assertNotIn('pass', ro.DS02_START_STOP_TOKENS)

    def test_control_capabilities_are_a_closed_declared_set(self):
        self.assertEqual(ro.CONTROL_CAPABILITIES,
                         ('RUN_CONTROL_UNAVAILABLE', 'manual-step-required', 'automated'))
        self.assertIn('automated', ro.CONTROL_CAPABILITIES)

    def test_the_automated_capability_is_unreachable_while_the_measurement_stands(self):
        """No input can make the item a pass, because no automated entry was measured."""
        bundle = good_bundle(runControl=run_control(startStopMode='automated',
                                                    triggeredBy='tool'))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        item = projection['s09']['items']['start-and-stop']
        self.assertEqual(item['ds02ItemToken'], 'blocked')
        self.assertNotEqual(item['status'], 'pass')

    def test_the_frozen_manifest_note_cites_the_measurement(self):
        template = ro.manifest_template(CASE)
        self.assertIn('measured negative', template['note'])
        self.assertIn(ro.DS02_EVIDENCE['adjudicatorSha256'], template['note'])
        self.assertEqual(template['findingKind'], 'measured-negative')

    def test_a_control_record_naming_a_command_is_refused(self):
        bundle = good_bundle(runControl=run_control(startCommand='mw.startPlaytest'))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        item = projection['s09']['items']['start-and-stop']
        self.assertEqual(item['status'], 'fail')
        self.assertIn('CONTROL_COMMAND_NOT_REPRESENTABLE',
                      {r['code'] for r in item['detail']})
        self.assertEqual(projection['s09']['runControl']['capability'],
                         'RUN_CONTROL_UNAVAILABLE')

    def test_a_control_record_claiming_it_started_the_playtest_is_refused(self):
        bundle = good_bundle(runControl=run_control(startsPlaytest=True))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        codes = {r['code'] for r in projection['s09']['items']['start-and-stop']['detail']}
        self.assertIn('CONTROL_COMMAND_NOT_REPRESENTABLE', codes)

    def test_a_control_record_of_the_wrong_contract_is_refused(self):
        bundle = good_bundle(runControl=run_control(contract='runtime-control/2'))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        codes = {r['code'] for r in projection['s09']['items']['start-and-stop']['detail']}
        self.assertIn('CONTROL_CONTRACT_MISMATCH', codes)

    def test_a_control_record_with_an_extra_field_is_refused(self):
        bundle = good_bundle(runControl=run_control(startCommandName='x'))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        codes = {r['code'] for r in projection['s09']['items']['start-and-stop']['detail']}
        self.assertIn('CONTROL_CONTRACT_MISMATCH', codes)

    def test_a_control_record_for_another_case_is_not_a_pass(self):
        bundle = good_bundle(runControl=run_control(caseId='other-case'))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        self.assertEqual(projection['s09']['items']['start-and-stop']['status'], 'fail')

    def test_a_bad_control_record_does_not_fail_a_correct_observation(self):
        """Two lanes, reported side by side, never merged into one verdict."""
        bundle = good_bundle(runControl=run_control(startCommand='mw.startPlaytest'))
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        self.assertIn('CONTROL_COMMAND_NOT_REPRESENTABLE', projection['refusalCodes'])
        self.assertEqual(projection['observationRefusals'], [])
        self.assertTrue(projection['controlRefusals'])
        self.assertEqual(projection['sampleObserved']['status'], 'pass')
        self.assertEqual(projection['s09']['items']['start-and-stop']['status'], 'fail')

    def test_the_two_lanes_are_named_in_the_projection(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertIn('observationRefusals', projection)
        self.assertIn('controlRefusals', projection)
        self.assertIn('observationRefusals', projection['laneSeparation'])


# --------------------------------------------------------------------------- #
# the projection: evidence mode, gameplay, determinism, mixed runs
# --------------------------------------------------------------------------- #

class ProjectionTests(unittest.TestCase):
    def test_the_default_is_offline(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertEqual(projection['evidenceMode'], 'offline')
        self.assertIs(projection['liveEvidence']['claimed'], False)
        self.assertIs(projection['liveEvidence']['derived'], False)

    def test_offline_is_forced_when_the_fixture_marker_says_not_live(self):
        projection = ro.normalize_runtime_evidence(
            good_bundle(), base_binding(evidenceMode='live'))
        self.assertEqual(projection['evidenceMode'], 'offline')
        self.assertIn('fixture marker with live=false',
                      ' '.join(projection['liveEvidence']['whyNotLive']))

    def test_a_live_claim_needs_every_fact_not_just_the_flag(self):
        """Every single ingredient is load-bearing: remove one and it falls to offline."""
        self.assertEqual(
            ro.normalize_runtime_evidence(good_bundle(), base_binding(evidenceMode='live'))[
                'evidenceMode'], 'offline', 'the fixture marker alone forbids live')

    def test_live_is_derived_only_when_the_document_is_not_a_fixture(self):
        bundle = good_bundle()
        bundle.pop('_fixture')
        projection = ro.normalize_runtime_evidence(bundle, base_binding(evidenceMode='live'))
        self.assertEqual(projection['evidenceMode'], 'live')
        self.assertIs(projection['liveEvidence']['derived'], True)
        self.assertEqual(projection['liveEvidence']['whyNotLive'], [])

    def test_a_fixture_that_claims_live_is_refused(self):
        projection = ro.normalize_runtime_evidence(refreshing_bundle(), base_binding())
        self.assertIn('FIXTURE_CLAIMS_LIVE', projection['refusalCodes'])
        self.assertEqual(projection['evidenceMode'], 'offline')

    def test_gameplay_is_never_claimed_from_one_static_sample(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertEqual(projection['gameplay']['status'], 'not-run')
        self.assertIn('cannot be read as gameplay verification',
                      projection['gameplay']['reason'])

    def test_starts_playtest_is_false_on_every_projection(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertIs(projection['startsPlaytest'], False)
        self.assertIs(projection['io']['startedPlaytest'], False)
        self.assertIs(projection['io']['openedAnyFile'], False)
        self.assertIs(projection['io']['performedAnyNativeAction'], False)

    def test_a_complete_bundle_with_a_runtime_readback_passes_the_sample(self):
        bundle = good_bundle()
        bundle.pop('_fixture')
        projection = ro.normalize_runtime_evidence(bundle, base_binding(evidenceMode='live'))
        self.assertEqual(projection['sampleObserved']['status'], 'pass')
        self.assertTrue(projection['sampleObserved']['evidenceRef'])

    def test_without_a_runtime_reader_the_sample_is_blocked_not_passed(self):
        projection = ro.normalize_runtime_evidence(good_bundle(runtimeObjects=None),
                                                   base_binding())
        self.assertEqual(projection['sampleObserved']['status'], 'blocked')

    def test_two_runs_in_one_bundle_are_refused_not_merged(self):
        second = level_init()
        second['observationId'] = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        second['observerTiming'] = dict(second['observerTiming'],
                                        registrationCompletedTick=9999999999999)
        bundle = good_bundle(levelInitialization=level_init())
        bundle['logObserverEvidence'] = observer_evidence(
            observerTiming=dict(second['observerTiming']))
        bundle['logObserverEvidence']['observationId'] = second['observationId']
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        self.assertIn('RUNTIME_MIXED_RUNS', projection['refusalCodes'])

    def test_the_projection_is_deterministic_and_json_serialisable(self):
        first = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        second = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertIsInstance(json.loads(json.dumps(first, allow_nan=False)), dict)

    def test_the_projection_carries_no_wall_clock_field(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        keys = set()

        def collect(node):
            if isinstance(node, dict):
                keys.update(node)
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(projection)
        for forbidden in ('projectedAt', 'generatedAt', 'observedNow', 'timestamp',
                          'createdAt', 'builtAt', 'readAt'):
            self.assertNotIn(forbidden, keys, forbidden)

    def test_every_refusal_code_emitted_is_in_the_closed_vocabulary(self):
        cases = [good_bundle(runtimeObjects=None), refreshing_bundle(),
                 good_bundle(runControl=run_control(startCommand='x')),
                 good_bundle(session=dict(GAME, pid=1))]
        for bundle in cases:
            projection = ro.normalize_runtime_evidence(bundle, base_binding())
            for code in projection['refusalCodes']:
                self.assertIn(code, ro.REFUSAL_CODES, code)

    def test_the_empty_window_case_keeps_its_gap_fields(self):
        bundle = good_bundle(
            levelInitialization=level_init(sequence=0, retainedEvents=0, events=[]),
            runtimeObjects=None, editorEvidence=editor_evidence(observedUtc=None),
            logObserverEvidence=observer_evidence(scenePacketSnapshots=[]),
            postRunReadback=None)
        projection = ro.normalize_runtime_evidence(bundle, base_binding())
        self.assertEqual(projection['observationWindow']['inWindowCount'], 0)
        self.assertEqual(projection['sampleObserved']['status'], 'blocked')
        self.assertEqual(projection['gameplay']['status'], 'not-run')


# --------------------------------------------------------------------------- #
# fixture discipline
# --------------------------------------------------------------------------- #

class FixtureDisciplineTests(unittest.TestCase):
    def test_every_builder_marks_its_fixture_not_live(self):
        self.assertIs(good_bundle()['_fixture']['live'], False)
        self.assertIs(refreshing_bundle()['_fixture']['live'], True)

    def test_the_good_bundle_is_never_emitted_as_live(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertEqual(projection['evidenceMode'], 'offline')

    def test_the_marker_is_surfaced_on_the_projection(self):
        projection = ro.normalize_runtime_evidence(good_bundle(), base_binding())
        self.assertIs(projection['fixture']['live'], False)
        self.assertEqual(projection['fixture']['kind'], 'synthetic-fixture')

    def test_no_live_lane_is_named_anywhere_in_this_file(self):
        """No bridge call, no elevate script, no probe: this file has no live lane.

        The tokens are assembled rather than written out, because a literal token inside
        this check would be found by this check -- the project has already lost time to a
        scanner that read its own output as corpus.
        """
        source = pathlib.Path(__file__).read_text(encoding='utf-8')
        for token in ('start-' + 'elevated', 'call-' + 'bridge', 'elevated-' + 'request.py',
                      'probe-log-' + 'observer', 'invoke-readonly-' + 'probe',
                      'request-debug-' + 'logs', 'current-elevated-' + 'session.json'):
            self.assertNotIn(token, source, token)

    def test_the_only_runtime_path_named_here_is_declared_provenance(self):
        source = pathlib.Path(__file__).read_text(encoding='utf-8')
        self.assertIn('.runtime/verification/interface-experiments-20260927/', source)
        self.assertIn('every input is a *synthetic fixture*', source)

    def test_the_builders_are_exact_copies_of_a_declared_shape(self):
        a, b = good_bundle(), good_bundle()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        mutated = copy.deepcopy(a)
        mutated['levelObservation']['levelId'] = OTHER_LEVEL
        self.assertNotEqual(json.dumps(a, sort_keys=True), json.dumps(mutated, sort_keys=True))


# --------------------------------------------------------------------------- #
# the command-line shell (real exit codes)
# --------------------------------------------------------------------------- #

class CliTests(unittest.TestCase):
    def _write(self, directory, name, payload):
        path = pathlib.Path(directory) / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path

    def _manifest(self, directory, bundle, binding=None, extra=None):
        docs = pathlib.Path(directory) / 'docs'
        docs.mkdir(exist_ok=True)
        bundle_path = self._write(docs, 'bundle.json', bundle)
        manifest = {
            'manifestContract': ro.MANIFEST_CONTRACT_ID,
            'binding': binding or base_binding(),
            'documents': {'bundle': str(bundle_path)},
        }
        if extra:
            manifest.update(extra)
        return self._write(directory, 'manifest.json', manifest)

    def _run(self, args):
        return subprocess.run([sys.executable, '-B', '-m', 'backend.runtime_observation'] + args,
                              cwd=str(ROOT), capture_output=True, text=True)

    def test_help_exits_zero(self):
        result = self._run(['--help'])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_real_projection_run_exits_zero_and_writes_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle())
            out = pathlib.Path(tmp) / 'out' / 'projection.json'
            out.parent.mkdir()
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out),
                                '--task-run-root', tmp])
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(written['evidenceMode'], 'offline')
            self.assertIs(written['startsPlaytest'], False)

    def test_a_named_refusal_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle(), binding=base_binding(runId='abc'))
            out = pathlib.Path(tmp) / 'projection.json'
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('BINDING_FORBIDDEN_FIELD', result.stderr)
            self.assertFalse(out.exists())

    def test_a_manifest_naming_an_execution_knob_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle(),
                                      extra={'elevatedQueue': '.runtime/elevated-queue'})
            out = pathlib.Path(tmp) / 'projection.json'
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('MANIFEST_FORBIDDEN_KEY', result.stderr)

    def test_an_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle())
            out = pathlib.Path(tmp) / 'projection.json'
            out.write_text('do not touch', encoding='utf-8')
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('OUTPUT_PATH_REFUSED', result.stderr)
            self.assertEqual(out.read_text(encoding='utf-8'), 'do not touch')

    def test_an_output_inside_an_input_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle())
            out = pathlib.Path(tmp) / 'docs' / 'projection.json'
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('OUTPUT_PATH_REFUSED', result.stderr)

    def test_an_output_outside_the_task_run_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle())
            out = pathlib.Path(tmp) / 'outside.json'
            root = pathlib.Path(tmp) / 'root'
            root.mkdir()
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out),
                                '--task-run-root', str(root)])
            self.assertEqual(result.returncode, 2)

    def test_dry_run_validates_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle())
            out = pathlib.Path(tmp) / 'projection.json'
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out),
                                '--dry-run'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(out.exists())

    def test_a_bad_manifest_contract_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_bundle(),
                                      extra={'manifestContract': 'something-else'})
            out = pathlib.Path(tmp) / 'projection.json'
            result = self._run(['--evidence-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('MANIFEST_INVALID', result.stderr)


if __name__ == '__main__':
    unittest.main()
