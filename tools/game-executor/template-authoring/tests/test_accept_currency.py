"""Synthetic raw native receipt fixtures; no live verification is asserted by tests."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tests'))
import accept_currency as accept
import prepare_currency as prepare
from test_template_review import ReviewFixture
from test_currency_receipt import encode


class AcceptCurrencyTests(unittest.TestCase):
    def setUp(self):
        self.data = ReviewFixture(); self.data.initialize(self)
        self.output = self.data.base / 'prepared-currency'
        self.enterContext(patch.object(prepare, 'OUTPUT', self.output))
        self.enterContext(patch.object(accept, 'PREPARED_ROOT', self.output))
        # Metadata resembles the target for the positive parsing fixture only;
        # identity/compiler calls are mocked and no output executable is run.
        self.data.session['image'] = str(accept.profiles.TARGET_IMAGE.resolve())
        self.data.request['session'] = dict(self.data.session)
        self.data.request_path.write_bytes(accept.requests.canonical_bytes(self.data.request))
        baseline = accept.requests.read_json(self.data.baseline / 'prepared.json')
        baseline['session'] = dict(self.data.session)
        self.data.write(self.data.baseline / 'prepared.json', baseline)
        self.data.review.update(session=dict(self.data.session),
            requestSha256=accept.profiles.sha256(self.data.request_path),
            evidenceHashes=accept.requests._baseline_hashes(self.data.baseline, 'readonly'))
        self.data.save()
        self.old_record = accept.requests.read_json(self.data.baseline / 'stdout.jsonl')
        self.raw_scene = bytes.fromhex(self.old_record['snapshotHex'])
        profile = accept.profiles.load_profile()
        kernel, user = Mock(), Mock()
        kernel.GetTickCount64.return_value = 1000
        user.RegisterWindowMessageW.return_value = 0xc456
        def fake_compile(run):
            for name in ('hook_receipt.dll', 'hook_receipt_probe.exe'):
                (run / name).write_bytes(b'SYNTHETIC TEST DATA; NOT AN EXECUTABLE')
            return 'test compiler mock'
        with patch.object(prepare.candidate, 'load_inputs', return_value=(self.data.request, self.raw_scene,
                self.data.runtime, profile, {'sha256': profile['image']['sha256']}, {})), \
             patch.object(prepare.profiles, 'validate_session', return_value=self.data.session), \
             patch.object(prepare.profiles, 'windows_api', return_value=(kernel, user)), \
             patch.object(prepare.candidate, 'compile_sources', side_effect=fake_compile):
            self.built = prepare.prepare(self.data.review_path)
        self.run = Path(self.built['run'])
        self.old = (0x42000001, 9, 0x50000, 0x60000)
        self.added = (0x42800001, 11, 0x70000, 0x80000)
        self.companion = (0x42000001, 0x42000001, 0x42000099, 0, 1, 4, 0x90000, 0xA0000)
        self.before_catalog = self.catalog([self.old])
        self.after_catalog = self.catalog([self.old, self.added])
        raw = bytearray(894352)
        struct.pack_into('<4I', raw, 0, 894352, 1, 0, 1)
        struct.pack_into('<4I2q2QI7B5x', raw, 16, 0, 4, 0, 0, 0, 100, 0x70000, 0x80000, 0x42800001, *([1] * 7))
        raw[80:80+33208] = self.raw_scene
        raw[33288:33288+33208] = self.raw_scene
        raw[369744:369744+262304] = self.before_catalog
        raw[632048:632048+262304] = self.after_catalog
        summary = dict(size=894352, version=1, sehCode=0, afterSceneUnchanged=1, code=0, stage=4,
            callCode=0, mainDeltaCode=0, count=0, limit=100, returnedResource='0x70000', createdId=0x42800001,
            groupLookupCalled=True, limitInitializationCalled=True, allocationCalled=True, createCalled=True,
            mainCatalogVerified=True, companionCatalogUnchanged=True, outcomeUncertain=True)
        self.record = dict(self.old_record, scope='FIXED_TEMPLATE_CURRENCY_ACTION', selfTestOnly=False,
            ok=True, transportOk=True, probeElevatedHigh=True, pid=9, tid=8, callbackCount=1,
            activeCallbacks=0, unhooked=True, hostPostUnhookPings=0, snapshotStatus=0,
            templateResultBytes=len(raw), templateResultHex=raw.hex(), templateResult=summary,
            observedCurrencyClass='0x80000', beforeCatalogBytes=262304, afterCatalogBytes=262304,
            beforeCatalogHex=self.before_catalog.hex(), afterCatalogHex=self.after_catalog.hex(),
            afterSnapshotBytes=33208, afterSnapshotHex=self.raw_scene.hex())
        self.save_record()
        for name in ('launch.claim', 'attempt.used', 'stderr.txt'):
            (self.run / name).write_bytes(b'')
        now = datetime.now(timezone.utc)
        self.data.write(self.run / 'exit.json', {'executed': True, 'exitCode': 0, 'error': None,
            'scope': 'FIXED_TEMPLATE_CURRENCY_ACTION', 'startedUtc': now.isoformat(),
            'finishedUtc': (now + timedelta(seconds=1)).isoformat(), 'wrapperPid': 234})

    def catalog(self, rows, companions=None):
        raw = bytearray.fromhex(encode(rows, [self.companion] if companions is None else companions, level=99))
        struct.pack_into('<Q', raw, 16, struct.unpack_from('<Q', self.raw_scene, 24)[0])
        return bytes(raw)

    def save_record(self):
        self.data.write(self.run / 'stdout.jsonl', self.record)

    def change_catalog(self, raw):
        self.record['afterCatalogHex'] = raw.hex()
        receipt = bytearray.fromhex(self.record['templateResultHex'])
        receipt[632048:632048+262304] = raw
        self.record['templateResultHex'] = receipt.hex()
        self.save_record()

    def test_raw_registration_acceptance_is_not_name_or_save_acceptance(self):
        self.assertGreater((self.run / 'stdout.jsonl').stat().st_size, 2 * 1024 * 1024)
        with patch.object(accept.profiles, 'windows_api', side_effect=AssertionError('no Windows API')):
            result = accept.validate_run(self.run)
        self.assertTrue(result['catalogRegisteredVerified'])
        self.assertEqual(result['createdId'], self.added[0])
        self.assertTrue(result['outcomeUncertain'])
        for key in ('persistentSaveVerified', 'nameVerified', 'defaultsVerified', 'gameplayVerified'):
            self.assertFalse(result[key])
        self.assertIn('stdout.jsonl', result['inputHashes'])
        self.assertIn('build-result.json', result['inputHashes'])

    def test_host_wrong_scope_incomplete_drain_and_session_rejected(self):
        original = copy.deepcopy(self.record)
        for key, value in (('selfTestOnly', True), ('scope', 'READ_ONLY_CONTEXT_RECEIPT'),
                           ('pid', 1), ('callbackCount', 2), ('activeCallbacks', 1),
                           ('unhooked', False), ('probeElevatedHigh', False)):
            with self.subTest(key=key):
                self.record = copy.deepcopy(original); self.record[key] = value; self.save_record()
                with self.assertRaisesRegex(ValueError, 'CURRENCY_NATIVE_TRANSPORT'):
                    accept.validate_run(self.run)

    def test_compile_only_candidate_and_artifact_change_rejected(self):
        original = copy.deepcopy(self.built)
        self.built['compileOnly'] = True
        self.data.write(self.run / 'build-result.json', self.built)
        with self.assertRaisesRegex(ValueError, 'DEDICATED_CURRENCY_BUILD_CONTRACT'):
            accept.validate_run(self.run)
        self.data.write(self.run / 'build-result.json', original)
        (self.run / 'hook_receipt.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'CURRENCY_ARTIFACT_CHANGED'):
            accept.validate_run(self.run)

    def test_summary_cannot_override_raw_create_result_or_class(self):
        self.record['templateResult']['createCalled'] = False; self.save_record()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_RAW_SUMMARY_MISMATCH:createCalled'):
            accept.validate_run(self.run)
        self.record['templateResult']['createCalled'] = True
        self.record['observedCurrencyClass'] = '0xB0000'; self.save_record()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_RAW_SUMMARY_MISMATCH:observedCurrencyClass'):
            accept.validate_run(self.run)

    def test_dedicated_catalog_duplicate_must_equal_receipt_bytes(self):
        self.record['afterCatalogHex'] = self.before_catalog.hex(); self.save_record()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_RAW_DUPLICATE_MISMATCH:afterCatalog'):
            accept.validate_run(self.run)

    def test_old_resource_and_companion_changes_fail_independent_recalculation(self):
        replaced = (self.old[0], self.old[1], 0xB0000, self.old[3])
        self.change_catalog(self.catalog([replaced, self.added]))
        with self.assertRaisesRegex(ValueError, 'PRIOR_PRIMARY_CHANGED'):
            accept.validate_run(self.run)
        changed = (*self.companion[:2], 0x42000088, *self.companion[3:])
        self.change_catalog(self.catalog([self.old, self.added], [changed]))
        with self.assertRaisesRegex(ValueError, 'COMPANION_CHANGED'):
            accept.validate_run(self.run)

    def test_scene_and_callback_stack_recomputed_even_when_native_claims_unchanged(self):
        raw = bytearray(self.raw_scene)
        struct.pack_into('<I', raw, 440 + 32, 456)  # Existing entity config ID changed.
        receipt = bytearray.fromhex(self.record['templateResultHex'])
        receipt[33288:33288+33208] = raw
        self.record['templateResultHex'] = receipt.hex(); self.record['afterSnapshotHex'] = raw.hex(); self.save_record()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_SCENE_CHANGED'):
            accept.validate_run(self.run)
        raw = bytearray(self.raw_scene); struct.pack_into('<I', raw, 152, 0)
        self.record['snapshotHex'] = raw.hex(); self.save_record()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_CALLBACK_STACK'):
            accept.validate_run(self.run)

    def test_failed_exit_and_missing_attempt_not_live_acceptance(self):
        path = self.run / 'exit.json'
        original = path.read_bytes()
        value = accept.requests.read_json(path); value['executed'] = False
        self.data.write(path, value)
        with self.assertRaisesRegex(ValueError, 'CURRENCY_NATIVE_EXIT'):
            accept.validate_run(self.run)
        path.write_bytes(original)
        (self.run / 'attempt.used').unlink()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_ATTEMPT_REQUIRED'):
            accept.validate_run(self.run)

    def test_source_change_named_refusal_does_not_rewrite_historical_inputs(self):
        original = (self.run / 'prepared.json').read_bytes()
        with patch.object(accept.reviews, 'source_hashes', return_value={}):
            result = accept.accept_run(self.run)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'CURRENCY_SOURCE_CHANGED')
        self.assertTrue(result['outcomeUncertain'])
        self.assertTrue(result['reportedCreateCalled'])
        self.assertFalse(result['catalogRegisteredVerified'])
        self.assertEqual((self.run / 'prepared.json').read_bytes(), original)

    def test_acceptance_output_exclusive_and_bounded_stdout(self):
        first = accept.accept_run(self.run)
        output = Path(first['output']); original = output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'CURRENCY_ACCEPTANCE_ALREADY_EXISTS'):
            accept.accept_run(self.run)
        self.assertEqual(output.read_bytes(), original)
        with patch.object(accept, 'MAX_STDOUT_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'CURRENCY_STDOUT_LIMIT'):
                accept.read_record(self.run / 'stdout.jsonl')


if __name__ == '__main__':
    unittest.main()
