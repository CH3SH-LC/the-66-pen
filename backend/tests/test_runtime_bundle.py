"""Offline tests for the runtime-bundle assembler.

Nothing here starts, connects to or drives Genshin, the Miliastra editor, the elevated
helper, the bridge, UAC or any live session.  The unit fixtures are synthetic responses
whose *field names* were read out of the real sources (``EditorAdapter.cs``'s
``RuntimeEvidence()`` / ``LogObserverEvidence()`` / ``ExternalAssetEvidence()``) and whose
values are invented.  One optional test re-assembles from byte-for-byte copies of two real
receipts under ``evidence/originals/``; it skips when those copies are absent and it makes
no live call either way.

    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.tests.test_runtime_bundle
"""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import runtime_bundle as rb  # noqa: E402
from backend import runtime_observation as ro  # noqa: E402

LEVEL = 1073741839
OBSERVATION_ID = 'e9c5a4005de14a93911c648f3d099c60'
REG_TICK = 3175291430318


def editor_evidence(**over):
    block = {
        'ok': True,
        'observedUtc': '2026-09-17T17:09:23.1196018Z',
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
        'notice': 'Missing markers do not prove the graph has not executed.',
    }
    block.update(over)
    return block


def observer_evidence(**over):
    block = {
        'ok': True,
        'observerTiming': {
            'scope': 'current-observer-instance-only',
            'stopwatchFrequency': 10000000,
            'startedUtc': '2026-09-17T17:05:00.0000000Z',
            'registrationCompletedUtc': '2026-09-17T17:05:00.5000000Z',
            'registrationCompletedTick': REG_TICK,
            'stoppedUtc': '2026-09-17T17:10:00.0000000Z',
            'stopReason': 'observer-lease-expired',
        },
        'levelInitialization': {
            'started': True,
            'observationId': OBSERVATION_ID,
            'observerTiming': {'registrationCompletedTick': REG_TICK},
            'sequence': 1,
            'retainedEvents': 1,
            'eventLimit': 16,
            'droppedEvents': 0,
            'overflow': False,
            'currentLevelId': LEVEL,
            'baselineLevelId': LEVEL,
            'events': [{'sequence': 1, 'receivedUtc': '2026-09-17T17:06:00.0000000Z',
                        'receivedTick': 1, 'managedThreadId': 1, 'levelId': LEVEL,
                        'parsed': True, 'error': None}],
        },
        'observedPackets': 12,
        'packetKinds': {'1022': 1},
        'scenePacketSnapshots': [],
        'ownMarkers': [],
        'observerCleanupError': None,
        'callbackErrors': 0,
        'originalReceiversPreserved': True,
        'observerRegistered': True,
        'playtestVerified': False,
        'notice': 'Markers may originate from historical debug logs.',
    }
    block.update(over)
    return block


def external_assets(**over):
    block = {'ok': True, 'captured': True, 'snapshots': [], 'totalEntriesScanned': 0,
             'sentToGame': False, 'scope': 'own-assets-only'}
    block.update(over)
    return block


def run_control(**over):
    block = {
        'contract': 'runtime-control/1', 'caseId': 'case-w17-0001', 'startStopMode': 'manual',
        'startedUtc': '2026-09-17T17:05:00.0000000Z',
        'stoppedUtc': '2026-09-17T17:10:00.0000000Z', 'triggeredBy': 'human-ui',
        'startRequestId': None, 'stopRequestId': None,
        'gameSession': {'pid': 1, 'tid': 2, 'processCreation': 'x', 'image': 'g.exe'},
        'levelId': LEVEL, 'startCommand': None, 'stopCommand': None, 'startsPlaytest': False,
    }
    block.update(over)
    return block


def part(kind, op, document=None, **over):
    entry = {'kind': kind, 'op': op,
             'document': document if document is not None else editor_evidence()}
    entry.update(over)
    return entry


def good_parts(**over):
    parts = {
        'observer-evidence': part('bridge-response', 'log-observer-evidence',
                                  observer_evidence()),
        'editor-evidence': part('bridge-response', 'runtime-evidence', editor_evidence()),
        'post-run-readback': part('bridge-response', 'runtime-evidence', editor_evidence()),
        'external-assets': part('bridge-response', 'external-asset-evidence',
                               external_assets()),
        'game-session': part('identity-record', 'game-session',
                             {'pid': 1, 'tid': 2, 'processCreation': 'x', 'image': 'g.exe'}),
        'run-control': part('contract-record', 'runtime-control/1', run_control()),
    }
    parts.update(over)
    return parts


class ContractTests(unittest.TestCase):
    def test_execution_surface_is_all_false(self):
        self.assertTrue(rb.EXECUTION_SURFACE)
        for key, value in rb.EXECUTION_SURFACE.items():
            self.assertIs(value, False, key)

    def test_the_cli_surface_opens_no_socket_and_never_overwrites(self):
        self.assertIs(rb.CLI_SURFACE['subprocess'], False)
        self.assertIs(rb.CLI_SURFACE['network'], False)
        self.assertIs(rb.CLI_SURFACE['game'], False)
        self.assertIs(rb.CLI_SURFACE['overwritesExistingOutput'], False)

    def test_the_bundle_marker_is_the_one_the_projection_accepts(self):
        assembly = rb.assemble_runtime_bundle(good_parts(), caseId='case-w17-0001')
        self.assertTrue(assembly['assembled'])
        self.assertEqual(rb.BUNDLE_CONTRACT_ID, 'runtime-evidence-bundle')
        self.assertEqual(ro.input_kind(assembly['bundle']), 'runtime-evidence-bundle')

    def test_the_roles_cover_every_lane_the_projection_reads(self):
        lanes = {lane for _, _, lane in rb.PART_ROLES.values()}
        for lane in ('logObserverEvidence', 'editorEvidence', 'postRunReadback',
                     'runtimeObjects', 'runControl', 'session', 'editorSession',
                     'levelObservation'):
            self.assertIn(lane, lanes, lane)
        # levelInitialization is not a lane of its own: it is lifted out of the observer
        # copy, because that is where the projection reads the 1022 cursor from.
        self.assertNotIn('levelInitialization', lanes)
        assembly = rb.assemble_runtime_bundle(good_parts())
        self.assertIn('levelInitialization', assembly['bundle'])

    def test_the_only_editor_state_operation_is_named(self):
        self.assertIn('catalog', rb.EDITOR_STATE_OPS)

    def test_the_gap_block_names_the_missing_input_and_invents_no_command(self):
        gap = rb.RUN_CONTROL_GAP
        self.assertEqual(gap['findingKind'], 'measured-negative')
        self.assertEqual(gap['runControl'], 'RUN_CONTROL_UNAVAILABLE')
        self.assertIn('level-state enumeration', gap['minimalMissingInput'])
        self.assertIn('start', gap['notImplementedHere'])
        self.assertNotIn('startCommand', json.dumps(gap))


class AssemblyTests(unittest.TestCase):
    def test_a_full_assembly_produces_the_bundle_lanes(self):
        assembly = rb.assemble_runtime_bundle(good_parts(), caseId='case-w17-0001')
        self.assertTrue(assembly['assembled'], assembly['refusals'])
        bundle = assembly['bundle']
        self.assertEqual(bundle['kind'], 'runtime-evidence-bundle')
        self.assertEqual(bundle['levelInitialization']['observationId'], OBSERVATION_ID)
        self.assertEqual(bundle['session']['pid'], 1)
        self.assertEqual(bundle['postRunReadback']['source'],
                         rb.POST_RUN_READBACK_SOURCE)
        self.assertEqual(bundle['assembledBy'], 'backend/runtime_bundle.py')

    def test_the_readback_level_comes_from_the_observer_copy_not_from_nowhere(self):
        assembly = rb.assemble_runtime_bundle(good_parts())
        readback = assembly['bundle']['postRunReadback']
        self.assertEqual(readback['levelId'], LEVEL)
        self.assertIn('levelInitialization.currentLevelId', readback['levelIdSource'])

    def test_an_unbound_readback_is_flagged_rather_than_given_a_level(self):
        parts = good_parts()
        parts.pop('observer-evidence')
        assembly = rb.assemble_runtime_bundle(parts)
        readback = assembly['bundle']['postRunReadback']
        self.assertNotIn('levelId', readback)
        self.assertIs(readback['levelBound'], False)

    def test_provenance_records_the_operation_and_the_digest(self):
        assembly = rb.assemble_runtime_bundle(good_parts())
        prov = assembly['provenance']['observer-evidence']
        self.assertEqual(prov['op'], 'log-observer-evidence')
        self.assertEqual(prov['kind'], 'bridge-response')
        self.assertEqual(len(prov['sha256']), 64)

    def test_the_bundle_digest_is_what_the_projection_binds_to(self):
        assembly = rb.assemble_runtime_bundle(good_parts(), caseId='case-w17-0001')
        bundle = assembly['bundle']
        binding = {'caseId': 'case-w17-0001', 'expectedLevelId': LEVEL,
                   'expectedGameSession': None, 'expectedEditorSession': None,
                   'expectedRunGeneration': None, 'expectedEntityIds': [],
                   'sourceSha256': rb.bundle_digest(bundle), 'evidenceMode': 'offline'}
        projection = ro.normalize_runtime_evidence(bundle, binding)  # must not raise
        self.assertEqual(projection['contract'], ro.CONTRACT_ID)


class RefusalTests(unittest.TestCase):
    def _first(self, parts):
        assembly = rb.assemble_runtime_bundle(parts)
        self.assertFalse(assembly['assembled'])
        self.assertIsNone(assembly['bundle'])
        return assembly['refusals'][0]['code']

    def test_an_editor_state_catalog_offered_as_runtime_objects_is_refused(self):
        code = self._first(good_parts(**{'runtime-objects': part(
            'bridge-response', 'catalog', {'ok': True})}))
        self.assertEqual(code, 'EDIT_STATE_NOT_RUNTIME')

    def test_an_unproven_operation_is_refused(self):
        code = self._first(good_parts(**{'editor-evidence': part(
            'bridge-response', 'start-playtest', editor_evidence())}))
        self.assertEqual(code, 'BUNDLE_PART_OP_UNPROVEN')

    def test_a_response_offered_for_the_wrong_lane_is_refused(self):
        code = self._first(good_parts(**{'editor-evidence': part(
            'bridge-response', 'log-observer-evidence', observer_evidence())}))
        self.assertEqual(code, 'BUNDLE_PART_ROLE_MISMATCH')

    def test_a_response_missing_a_known_field_is_refused(self):
        document = editor_evidence()
        document.pop('editorLevelState')
        code = self._first(good_parts(**{'editor-evidence': part(
            'bridge-response', 'runtime-evidence', document)}))
        self.assertEqual(code, 'BUNDLE_PART_FIELD_MISSING')

    def test_a_response_that_is_not_ok_is_refused(self):
        code = self._first(good_parts(**{'editor-evidence': part(
            'bridge-response', 'runtime-evidence', editor_evidence(ok=False))}))
        self.assertEqual(code, 'BUNDLE_PART_NOT_OK')

    def test_a_runtime_readback_without_a_generation_carrier_is_refused(self):
        code = self._first(good_parts(**{'runtime-objects': part(
            'declared-reader', 'runtime-scene-object-readback',
            {'source': 'runtime-scene-object-readback', 'levelId': LEVEL, 'objects': []})}))
        self.assertEqual(code, 'CORRELATION_GENERATION_UNBOUND')

    def test_a_runtime_readback_from_a_non_runtime_reader_is_refused(self):
        code = self._first(good_parts(**{'runtime-objects': part(
            'declared-reader', 'runtime-scene-object-readback',
            {'source': 'editor-entity-catalog', 'levelId': LEVEL, 'objects': [],
             'observationId': OBSERVATION_ID})}))
        self.assertEqual(code, 'RUNTIME_OBJECT_SOURCE_UNSUPPORTED')

    def test_a_control_record_naming_a_command_is_refused(self):
        code = self._first(good_parts(**{'run-control': part(
            'contract-record', 'runtime-control/1',
            run_control(startCommand='mw.startPlaytest'))}))
        self.assertEqual(code, 'CONTROL_COMMAND_NOT_REPRESENTABLE')

    def test_a_manual_run_relabelled_automated_is_refused(self):
        code = self._first(good_parts(**{'run-control': part(
            'contract-record', 'runtime-control/1',
            run_control(startStopMode='automated', triggeredBy='tool'))}))
        self.assertEqual(code, 'BUNDLE_CONTROL_AUTOMATED_UNPROVEN')

    def test_a_failed_assembly_emits_no_bundle(self):
        assembly = rb.assemble_runtime_bundle(good_parts(**{'runtime-objects': part(
            'bridge-response', 'catalog', {'ok': True})}))
        self.assertIsNone(assembly['bundle'])


class RealCopyTests(unittest.TestCase):
    """Re-assemble from byte-for-byte copies of two real receipts, if present."""

    def _copy(self, name):
        path = ROOT / '.runtime/cordis-plan-work/DW20-20261005/wave-01/W17/evidence/originals' / name
        if not path.exists():
            self.skipTest('the original receipt copies are not in this checkout')
        return json.loads(path.read_text(encoding='utf-8-sig'))

    def test_two_real_receipts_assemble_into_a_bundle_the_projection_accepts(self):
        parts = {
            'observer-evidence': part('bridge-response', 'log-observer-evidence',
                                      self._copy('log-observer-evidence-408229ea.json')),
            'editor-evidence': part('bridge-response', 'runtime-evidence',
                                    self._copy('runtime-evidence-demo-20260917T170920Z.json')),
        }
        assembly = rb.assemble_runtime_bundle(parts, caseId='case-w17-real')
        self.assertTrue(assembly['assembled'], assembly['refusals'])
        self.assertEqual(assembly['bundle']['levelInitialization']['observationId'],
                         OBSERVATION_ID)
        self.assertEqual(ro.input_kind(assembly['bundle']), 'runtime-evidence-bundle')


class CliTests(unittest.TestCase):
    def _manifest(self, directory, parts, caseId='case-w17-0001', extra=None):
        docs = pathlib.Path(directory) / 'docs'
        docs.mkdir(exist_ok=True)
        declared = {}
        for role, entry in parts.items():
            path = docs / (role + '.json')
            path.write_text(json.dumps(entry['document'], ensure_ascii=False),
                            encoding='utf-8')
            declared[role] = {'kind': entry['kind'], 'op': entry['op'], 'path': str(path)}
        manifest = {'manifestContract': rb.ASSEMBLY_MANIFEST_CONTRACT_ID, 'caseId': caseId,
                    'parts': declared}
        if extra:
            manifest.update(extra)
        path = pathlib.Path(directory) / 'manifest.json'
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        return path

    def _run(self, args):
        return subprocess.run([sys.executable, '-B', '-m', 'backend.runtime_bundle'] + args,
                              cwd=str(ROOT), capture_output=True, text=True)

    def test_help_exits_zero(self):
        self.assertEqual(self._run(['--help']).returncode, 0)

    def test_a_real_assembly_exits_zero_and_writes_one_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_parts())
            out = pathlib.Path(tmp) / 'out' / 'bundle.json'
            out.parent.mkdir()
            result = self._run(['--assembly-manifest', str(manifest), '--output', str(out),
                                '--task-run-root', tmp])
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(written['kind'], rb.BUNDLE_CONTRACT_ID)

    def test_a_refused_assembly_exits_two_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_parts(**{
                'runtime-objects': {'kind': 'bridge-response', 'op': 'catalog',
                                    'document': {'ok': True}}}))
            out = pathlib.Path(tmp) / 'bundle.json'
            result = self._run(['--assembly-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('EDIT_STATE_NOT_RUNTIME', result.stderr)
            self.assertFalse(out.exists())

    def test_an_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_parts())
            out = pathlib.Path(tmp) / 'bundle.json'
            out.write_text('do not touch', encoding='utf-8')
            result = self._run(['--assembly-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('OUTPUT_PATH_REFUSED', result.stderr)
            self.assertEqual(out.read_text(encoding='utf-8'), 'do not touch')

    def test_dry_run_validates_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_parts())
            out = pathlib.Path(tmp) / 'bundle.json'
            result = self._run(['--assembly-manifest', str(manifest), '--output', str(out),
                                '--dry-run'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(out.exists())

    def test_an_output_inside_an_input_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self._manifest(tmp, good_parts())
            out = pathlib.Path(tmp) / 'docs' / 'bundle.json'
            result = self._run(['--assembly-manifest', str(manifest), '--output', str(out)])
            self.assertEqual(result.returncode, 2)
            self.assertIn('OUTPUT_PATH_REFUSED', result.stderr)


class DeterminismTests(unittest.TestCase):
    def test_the_same_parts_assemble_byte_identically(self):
        first = rb.assemble_runtime_bundle(good_parts(), caseId='c')
        second = rb.assemble_runtime_bundle(good_parts(), caseId='c')
        self.assertEqual(json.dumps(first['bundle'], sort_keys=True),
                         json.dumps(second['bundle'], sort_keys=True))

    def test_assembly_does_not_mutate_the_inputs(self):
        parts = good_parts()
        before = json.dumps(parts, sort_keys=True)
        rb.assemble_runtime_bundle(parts)
        self.assertEqual(before, json.dumps(parts, sort_keys=True))

    def test_a_deep_copied_bundle_is_still_projected_the_same(self):
        assembly = rb.assemble_runtime_bundle(good_parts(), caseId='c')
        self.assertEqual(json.dumps(assembly['bundle'], sort_keys=True),
                         json.dumps(copy.deepcopy(assembly['bundle']), sort_keys=True))


if __name__ == '__main__':
    unittest.main()
