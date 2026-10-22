"""Synthetic item receipts exercise independent decoding; no live acceptance is claimed."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tests'))
import accept_item as accept
import prepare_item as prepare
from test_item_review import ReviewFixture
from test_currency_receipt import encode


class AcceptItemTests(unittest.TestCase):
    def setUp(self):
        direct = accept.requests.read_json(accept.candidate.DEFAULT_RUNTIME_PROFILE)
        service = accept.requests.read_json(accept.candidate.DEFAULT_SERVICE_PROFILE)
        self.data = ReviewFixture(); self.data.initialize(self)
        self.output = self.data.base / 'prepared-item'
        self.enterContext(patch.object(prepare, 'OUTPUT', self.output))
        self.enterContext(patch.object(accept, 'PREPARED_ROOT', self.output))
        self.data.write(self.data.runtime_path, direct)
        self.data.write(self.data.service_path, service)
        self.data.session['image'] = str(accept.profiles.TARGET_IMAGE.resolve())
        self.data.request['session'] = dict(self.data.session)
        self.data.request_path.write_bytes(accept.requests.canonical_bytes(self.data.request))
        baseline = accept.requests.read_json(self.data.baseline / 'prepared.json')
        baseline['session'] = dict(self.data.session)
        self.data.write(self.data.baseline / 'prepared.json', baseline)
        self.data.review.update(session=dict(self.data.session),
            requestSha256=accept.profiles.sha256(self.data.request_path),
            evidenceHashes=accept.requests._baseline_hashes(self.data.baseline, 'readonly'),
            runtimeProfileSha256=accept.profiles.sha256(self.data.runtime_path),
            transitiveCurrencyProfile={'path': str(self.data.service_path), 'sha256': accept.profiles.sha256(self.data.service_path)},
            sourceHashes=accept.reviews.source_hashes())
        self.data.save()
        self.old_record = accept.requests.read_json(self.data.baseline / 'stdout.jsonl')
        self.raw_scene = bytes.fromhex(self.old_record['snapshotHex'])
        profile = accept.profiles.load_profile()
        runtime = copy.deepcopy(direct)
        runtime['functions'].append(next(f for f in service['functions'] if f['rva'] == '0xb0a90c0'))
        inputs = {'runtimeProfilePath': str(self.data.runtime_path),
            'runtimeProfileSha256': self.data.review['runtimeProfileSha256'],
            'serviceProfilePath': str(self.data.service_path),
            'serviceProfileSha256': self.data.review['transitiveCurrencyProfile']['sha256']}
        kernel, user = Mock(), Mock()
        kernel.GetTickCount64.return_value = 1000; user.RegisterWindowMessageW.return_value = 0xc456
        def fake_compile(run):
            for name in ('hook_receipt.dll', 'hook_receipt_probe.exe'):
                (run / name).write_bytes(b'SYNTHETIC TEST DATA; NOT EXECUTABLE')
            return 'test compiler mock'
        with patch.object(prepare.candidate, 'load_inputs', return_value=(self.data.request, self.raw_scene,
                runtime, profile, {'sha256': profile['image']['sha256']}, inputs)), \
             patch.object(prepare.profiles, 'validate_session', return_value=self.data.session), \
             patch.object(prepare.profiles, 'windows_api', return_value=(kernel, user)), \
             patch.object(prepare.candidate, 'compile_sources', side_effect=fake_compile):
            self.built = prepare.prepare(self.data.review_path)
        self.run = Path(self.built['run'])
        self.old = (0x42000009, 9, 0x50000, 0x60000)
        self.added = (0x42000001, 9, 0x70000, 0x80000)
        self.old_companion = (0x42000009, 0x42000009, 0x42000099, 0, 1, 4, 0x90000, 0xA0000)
        self.new_companion = (0x42000001, 0x42000001, 0x42000044, 0, 1, 4, 0xB0000, 0xC0000)
        self.before = self.catalog([self.old], [self.old_companion])
        self.after = self.catalog([self.old, self.added], [self.old_companion, self.new_companion])
        raw = bytearray(894392)
        struct.pack_into('<4I', raw, 0, 894392, 1, 0, 1)
        struct.pack_into('<2I3I4B2I2q2I4Q9B7x', raw, 16,
            0, 6, 0, 0, 5, 1, 0, 1, 1, 0, 0, 1, 100, 0x42000001, 0x42000044,
            0x70000, 0xB0000, 0x80000, 0xC0000, *([1] * 9))
        raw[120:120+33208] = self.raw_scene
        raw[33328:33328+33208] = self.raw_scene
        raw[369784:369784+262304] = self.before
        raw[632088:632088+262304] = self.after
        summary = dict(size=894392, version=1, sehCode=0, afterSceneUnchanged=1, code=0, stage=6,
            itemCode=0, itemStage=0, mainDeltaCode=0, count=1, limit=100,
            createdResource='0x70000', createdId=0x42000001, companionResource='0xB0000', companionOwnId=0x42000044,
            metadataInitializationCalled=True, countCalled=True, limitInitializationCalled=True,
            controllerLookupCalled=True, allocationCalled=True, defaultGetterCalled=True, handlerCalled=True,
            createCalled=True, mainCatalogVerified=True, companionCatalogVerified=True, outcomeUncertain=True)
        self.record = dict(self.old_record, scope='FIXED_TEMPLATE_ITEM_ACTION', selfTestOnly=False,
            ok=True, transportOk=True, probeElevatedHigh=True, pid=9, tid=8, callbackCount=1,
            activeCallbacks=0, unhooked=True, hostPostUnhookPings=0, snapshotStatus=0,
            itemResultBytes=len(raw), itemResultHex=raw.hex(), itemResult=summary,
            observedMainClass='0x80000', observedCompanionClass='0xC0000',
            beforeCatalogBytes=262304, afterCatalogBytes=262304, beforeCatalogHex=self.before.hex(),
            afterCatalogHex=self.after.hex(), afterSnapshotBytes=33208, afterSnapshotHex=self.raw_scene.hex())
        self.save_record()
        for name in ('launch.claim', 'attempt.used', 'stderr.txt'): (self.run / name).write_bytes(b'')
        now = datetime.now(timezone.utc)
        self.data.write(self.run / 'exit.json', {'executed': True, 'exitCode': 0, 'error': None,
            'scope': 'FIXED_TEMPLATE_ITEM_ACTION', 'startedUtc': now.isoformat(),
            'finishedUtc': (now + timedelta(seconds=1)).isoformat(), 'wrapperPid': 234})

    def catalog(self, rows, companions):
        raw = bytearray.fromhex(encode(rows, companions, level=99))
        struct.pack_into('<Q', raw, 16, struct.unpack_from('<Q', self.raw_scene, 24)[0])
        return bytes(raw)

    def save_record(self):
        self.data.write(self.run / 'stdout.jsonl', self.record)

    def change_catalog(self, raw):
        self.record['afterCatalogHex'] = raw.hex()
        receipt = bytearray.fromhex(self.record['itemResultHex'])
        receipt[632088:632088+262304] = raw
        self.record['itemResultHex'] = receipt.hex(); self.save_record()

    def test_actual_item_layout_two_registrations_and_non_persistence_boundary(self):
        self.assertGreater((self.run / 'stdout.jsonl').stat().st_size, 2 * 1024 * 1024)
        with patch.object(accept.profiles, 'windows_api', side_effect=AssertionError('no Windows API')):
            result = accept.validate_run(self.run)
        self.assertTrue(result['catalogRegisteredVerified'])
        self.assertEqual((result['createdId'], result['companionOwnId']), (0x42000001, 0x42000044))
        self.assertTrue(result['handlerCalled']); self.assertTrue(result['outcomeUncertain'])
        for key in ('persistentSaveVerified', 'nameVerified', 'defaultsVerified', 'gameplayVerified'):
            self.assertFalse(result[key])

    def test_host_candidate_wrong_scope_or_missing_attempt_rejected(self):
        original = copy.deepcopy(self.record)
        for key, value in (('selfTestOnly', True), ('scope', 'FIXED_TEMPLATE_CURRENCY_ACTION'),
                           ('pid', 1), ('callbackCount', 2), ('activeCallbacks', 1)):
            with self.subTest(key=key):
                self.record = copy.deepcopy(original); self.record[key] = value; self.save_record()
                with self.assertRaisesRegex(ValueError, 'ITEM_NATIVE_TRANSPORT'): accept.validate_run(self.run)
        self.record = original; self.save_record()
        (self.run / 'attempt.used').unlink()
        with self.assertRaisesRegex(ValueError, 'ITEM_ATTEMPT_REQUIRED'): accept.validate_run(self.run)
        self.built['compileOnly'] = True; self.data.write(self.run / 'build-result.json', self.built)
        with self.assertRaisesRegex(ValueError, 'DEDICATED_ITEM_BUILD_CONTRACT'): accept.validate_run(self.run)

    def test_raw_class_handler_and_summary_must_agree(self):
        self.record['observedCompanionClass'] = '0xD0000'; self.save_record()
        with self.assertRaisesRegex(ValueError, 'ITEM_RAW_SUMMARY_MISMATCH:observedCompanionClass'):
            accept.validate_run(self.run)
        self.record['observedCompanionClass'] = '0xC0000'
        self.record['itemResult']['handlerCalled'] = False; self.save_record()
        with self.assertRaisesRegex(ValueError, 'ITEM_RAW_SUMMARY_MISMATCH:handlerCalled'):
            accept.validate_run(self.run)

    def test_main_kind_band_and_old_identity_recomputed(self):
        for rows, reason in (([self.old, (0x42800001, 9, 0x70000, 0x80000)], 'ITEM_ID_BAND'),
                             ([self.old, (self.added[0], 11, 0x70000, 0x80000)], 'NEW_RESOURCE_IDENTITY'),
                             ([(self.old[0], 9, 0xD0000, self.old[3]), self.added], 'PRIOR_PRIMARY_CHANGED')):
            with self.subTest(reason=reason):
                self.change_catalog(self.catalog(rows, [self.old_companion, self.new_companion]))
                with self.assertRaisesRegex(ValueError, reason): accept.validate_run(self.run)

    def test_companion_guid_class_parent_and_existing_identity_recomputed(self):
        wrong_guid = (*self.new_companion[:3], 0, 1, 3, *self.new_companion[6:])
        wrong_class = (*self.new_companion[:7], 0xD0000)
        wrong_parent = (self.new_companion[0], 0x42000002, *self.new_companion[2:])
        for companion, reason in ((wrong_guid, 'COMPANION_IDENTITY'), (wrong_class, 'COMPANION_IDENTITY'),
                                  (wrong_parent, 'INVALID_COMPANION')):
            with self.subTest(reason=reason):
                self.change_catalog(self.catalog([self.old, self.added], [self.old_companion, companion]))
                with self.assertRaisesRegex(ValueError, reason): accept.validate_run(self.run)
        self.change_catalog(self.catalog([self.old, self.added], [self.old_companion]))
        with self.assertRaisesRegex(ValueError, 'COMPANION_DELTA_COUNT'): accept.validate_run(self.run)

    def test_transitive_service_hash_and_compiled_profile_bound(self):
        for name in ('prepared.json', 'build-contract.json'):
            path = self.run / name; value = accept.requests.read_json(path)
            value['inputs']['serviceProfileSha256'] = '0' * 64
            self.data.write(path, value)
            self.built['hashes'][name] = accept.profiles.sha256(path)
        self.data.write(self.run / 'build-result.json', self.built)
        with self.assertRaisesRegex(ValueError, 'ITEM_TRANSITIVE_PROFILE_BINDING'): accept.validate_run(self.run)

    def test_failed_handler_and_default_getter_preserve_distinct_attempts(self):
        original = copy.deepcopy(self.record)
        exit_path = self.run / 'exit.json'; exit_record = accept.requests.read_json(exit_path)
        exit_record['exitCode'] = 1; self.data.write(exit_path, exit_record)
        for stage, handler in ((3, True), (1, False)):
            with self.subTest(stage=stage):
                self.record = copy.deepcopy(original)
                raw = bytearray.fromhex(self.record['itemResultHex'])
                struct.pack_into('<I', raw, 8, 0xC0000005)
                struct.pack_into('<I', raw, 16, 18)
                struct.pack_into('<2I', raw, 24, 10, stage)
                raw[38] = raw[39] = int(handler)  # Inner handler attempt and uncertainty.
                raw[109] = raw[112] = int(handler)  # Outer create attempt and uncertainty.
                self.record['itemResultHex'] = raw.hex()
                self.record['itemResult'].update(sehCode=0xC0000005, code=18, itemCode=10, itemStage=stage,
                    handlerCalled=handler, createCalled=handler, outcomeUncertain=handler)
                self.save_record()
                result = accept.accept_run(self.run)
                self.assertFalse(result['catalogRegisteredVerified'])
                self.assertEqual(result['reportedItemStage'], stage)
                self.assertEqual(result['reportedHandlerCalled'], handler)
                self.assertEqual(result['outcomeUncertain'], handler)
                self.assertTrue(result['reportedDefaultGetterCalled'])
                self.assertTrue((self.run / 'attempt.used').exists())
                (self.run / 'item-acceptance.json').unlink()  # Distinct synthetic scenarios only.

    def test_no_overwrite_and_source_change_refuses_without_rewriting_prepare(self):
        original = (self.run / 'prepared.json').read_bytes()
        with patch.object(accept.reviews, 'source_hashes', return_value={}):
            result = accept.accept_run(self.run)
        self.assertEqual(result['error'], 'ITEM_SOURCE_CHANGED')
        self.assertTrue(result['reportedHandlerCalled']); self.assertTrue(result['outcomeUncertain'])
        self.assertEqual((self.run / 'prepared.json').read_bytes(), original)
        output = self.run / 'item-acceptance.json'; original_output = output.read_bytes()
        with self.assertRaisesRegex(ValueError, 'ITEM_ACCEPTANCE_ALREADY_EXISTS'): accept.accept_run(self.run)
        self.assertEqual(output.read_bytes(), original_output)


if __name__ == '__main__': unittest.main()
