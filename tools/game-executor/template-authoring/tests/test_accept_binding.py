"""Synthetic raw binding receipts. No fixture executable is ever launched."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'tests'))
import accept_binding as accept
import binding_receipt as raw_api
import prepare_binding as prepare
import test_prepare_binding as preparation_fixtures
from test_component_receipt import encode as component_bytes
from test_currency_receipt import encode as catalog_hex


class AcceptBindingTests(unittest.TestCase):
    def setUp(self):
        self.preparation = preparation_fixtures.BindingPreparationTests()
        self.preparation.setUp(); self.addCleanup(self.preparation.doCleanups)
        data = self.data = self.preparation.data
        self.enterContext(patch.object(accept, 'PREPARED_ROOT', prepare.OUTPUT))
        runtime = accept.requests.read_json(accept.candidate.DEFAULT_RUNTIME_PROFILE)
        data.write(data.runtime_path, runtime)
        data.session['image'] = str(accept.profiles.TARGET_IMAGE.resolve())
        data.request['session'] = dict(data.session)
        data.request_path.write_bytes(accept.requests.canonical_bytes(data.request))
        baseline = accept.requests.read_json(data.baseline / 'prepared.json')
        baseline['session'] = dict(data.session); data.write(data.baseline / 'prepared.json', baseline)
        data.review.update(session=dict(data.session), requestSha256=accept.profiles.sha256(data.request_path),
            evidenceHashes=accept.requests._baseline_hashes(data.baseline, 'readonly'),
            runtimeProfileSha256=accept.profiles.sha256(data.runtime_path), sourceHashes=accept.reviews.source_hashes())
        data.save()
        self.original = accept.requests.read_json(data.baseline / 'stdout.jsonl')
        self.scene_raw = bytes.fromhex(self.original['snapshotHex'])
        profile = accept.profiles.load_profile()
        self.scene = accept.scene(self.scene_raw, profile, 99)
        self.owner = int(self.scene['entities'][0]['owner'], 16)
        self.module = int(self.scene['pointers']['moduleBase'], 16)
        self.global_pointer = int(self.scene['pointers']['global'], 16)
        inputs = dict(runtimeProfilePath=str(data.runtime_path), runtimeProfileSha256=data.review['runtimeProfileSha256'])
        kernel, user = Mock(), Mock()
        kernel.GetTickCount64.return_value = 1000; user.RegisterWindowMessageW.return_value = 0xc123
        def fake_compile(run):
            for name in ('hook_receipt.dll', 'hook_receipt_probe.exe'):
                (run / name).write_bytes(b'SYNTHETIC TEST; NOT EXECUTABLE')
            return 'mock compiler'
        with patch.object(prepare.candidate, 'load_inputs', return_value=(data.request, self.scene_raw,
                runtime, profile, {'sha256': profile['image']['sha256']}, inputs)), \
             patch.object(prepare.profiles, 'validate_session', return_value=data.session), \
             patch.object(prepare.profiles, 'windows_api', return_value=(kernel, user)), \
             patch.object(prepare.candidate, 'compile_sources', side_effect=fake_compile):
            self.built = prepare.prepare(data.review_path)
        self.run = Path(self.built['run'])
        self.raw = bytearray(988064)
        self.classes = tuple(0x21000 + 0x1000 * i for i in range(8))
        struct.pack_into('<9I', self.raw, 0, 988064, 2, 0, 0, 1, 0, 0, 19, 19)
        struct.pack_into('<8Q3B', self.raw, 40, *self.classes, 1, 1, 1)
        struct.pack_into('<5I', self.raw, 112, 0, 5, 123, 1136656385, 17)
        struct.pack_into('<5Qi', self.raw, 136, self.owner, 0x34000, 0x30000, 0x31000, 0x32000, 1)
        struct.pack_into('<I', self.raw, 184, 1)
        target = (0x30000, self.classes[2], 0x31000, self.classes[1], 35, 1)
        struct.pack_into('<4QiB3x', self.raw, 192, *target)
        struct.pack_into('<Q4B', self.raw, 232, 0x30000, 1, 1, 1, 1)
        struct.pack_into('<2I2Qi11B', self.raw, 248, 0, 0, 0x33000, 0x32000, 1,
            1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0)
        struct.pack_into('<8B', self.raw, 288, 1, 1, 1, 0, 1, 1, 0, 1)
        struct.pack_into('<2IQ10B', self.raw, 296, 13, 0, 0x45000, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1)
        struct.pack_into('<5QiB', self.raw, 328, self.module, self.global_pointer, self.owner, 0x30000, 0x31000, 35, 1)
        for offset in (50040, 83248): self.raw[offset:offset + 33208] = self.scene_raw
        catalog = bytearray.fromhex(catalog_hex([(1136656385, 17, 0x34000, self.classes[4])], [], level=99))
        struct.pack_into('<Q', catalog, 16, self.global_pointer)
        for offset in (419704, 682008): self.raw[offset:offset + 262304] = catalog
        old = (0x51000, 0x52000, 0x53000, 0x54000, 1, 1)
        for offset, rows in ((953872, [old]), (965248, [old, target]), (976624, [old, target])):
            block = bytearray(component_bytes(rows))
            struct.pack_into('<2Q', block, 24, self.owner, self.classes[7])
            self.raw[offset:offset + len(block)] = block
        struct.pack_into('<2Q2Ii', self.raw, 988032, 0x33000, 0x32000, 1136656385, 1, 1)
        for offset, count, depth, dirty in ((376, 0, 0, 0), (12792, 1, 1, 0),
                                           (25208, 1, 1, 1), (37624, 0, 0, 0)):
            struct.pack_into('<4I2i', self.raw, offset, 0, count, 2, count, 0, depth)
            struct.pack_into('<6Q', self.raw, offset + 32, 0x40000, 0x41000, 0x42000, self.classes[6], 0x44000, 10)
            if count:
                row = (0x46000, self.classes[6], 0x30000, 0, 0x47000, dirty)
                for at in (80, 128): struct.pack_into('<5QB7x', self.raw, offset + at, *row)
        self.save_record()
        for name in ('launch.claim', 'attempt.used', 'stderr.txt'): (self.run / name).write_bytes(b'')
        now = datetime.now(timezone.utc)
        data.write(self.run / 'exit.json', dict(executed=True, exitCode=0, error=None,
            scope='FIXED_TEMPLATE_BINDING_ACTION', startedUtc=now.isoformat(),
            finishedUtc=(now + timedelta(seconds=1)).isoformat()))

    def save_record(self):
        decoded = raw_api.decode_native(bytes(self.raw))
        n, a, b, at, e = (decoded[k] for k in ('native', 'action', 'binding', 'attachment', 'edit'))
        summary = {k: v for k, v in n.items() if k != 'classes'}
        summary.update({k: a[k] for k in ('code', 'stage', 'entityId', 'templateId', 'componentId', 'shopIndex',
            'reused', 'postBindingVerified', 'catalogsUnchanged', 'needsOwnerNotification', 'outcomeUncertain')})
        summary.update(bindCode=b['code'], bindStage=b['stage'], attachCalled=at['attachCalled'])
        summary.update({k: b[k] for k in ('referenceFactoryCalled', 'addCalled', 'setterCalled', 'dependencyRefreshCalled')})
        record = dict(self.original, scope='FIXED_TEMPLATE_BINDING_ACTION', selfTestOnly=False,
            ok=True, transportOk=True, probeElevatedHigh=True, pid=9, tid=8, callbackCount=1,
            activeCallbacks=0, unhooked=True, hostPostUnhookPings=0, snapshotStatus=0,
            bindingResultBytes=len(self.raw), bindingResultHex=self.raw.hex(), bindingResult=summary,
            editResult={k: e[k] for k in ('code', 'stage', 'openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled',
                'notificationVerified', 'closeVerified', 'transactionMayBeOpen', 'needsPersistenceAcceptance')})
        for name, offset, size in (
                ('beforeCatalog', 419704, 262304), ('afterCatalog', 682008, 262304),
                ('beforeComponents', 953872, 11376), ('afterAttachmentComponents', 965248, 11376),
                ('afterComponents', 976624, 11376), ('editResult', 296, 49744),
                ('editBefore', 376, 12416), ('editAfterSnapshot', 12792, 12416),
                ('editAfterNotify', 25208, 12416), ('editAfterClose', 37624, 12416), ('afterSnapshot', 83248, 33208)):
            record[name + 'Bytes'] = size; record[name + 'Hex'] = self.raw[offset:offset + size].hex()
        self.record = record
        self.data.write(self.run / 'stdout.jsonl', record)

    def test_full_raw_binding_transaction_and_non_persistence_boundary(self):
        with patch.object(accept.profiles, 'windows_api', side_effect=AssertionError('no Windows API')):
            result = accept.validate_run(self.run)
        self.assertTrue(result['bindingVerified'] and result['ownerNotificationVerified'] and result['editTransactionClosed'])
        self.assertEqual((result['entityId'], result['templateId'], result['shopIndex']), (123, 1136656385, 1))
        self.assertFalse(result['persistentSaveVerified'] or result['gameplayVerified'] or result['playerCharacterVerified'])

    def test_old_metadata_count_does_not_accept_new_typed_reference_run(self):
        struct.pack_into('<2I', self.raw, 28, 17, 17); self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_NATIVE_NOT_COMPLETE'):
            accept.validate_run(self.run)

    def test_compiled_reference_macros_are_bound_to_reviewed_profile(self):
        header = self.run / 'target_config.h'
        original = header.read_text(encoding='utf-8')
        prepared = accept.requests.read_json(self.run / 'prepared.json')
        for macro in ('TA_REFERENCE_ANCHOR_RVAS', 'TA_REFERENCE_ANCHOR_BYTES',
                      'TA_REFERENCE_USAGE_GROUPS', 'TA_REFERENCE_HOTFIX_RVAS'):
            with self.subTest(macro=macro):
                header.write_text(original.replace('#define ' + macro + ' ', '#define OMITTED_' + macro + ' '), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'BINDING_COMPILED_PROFILE:' + macro):
                    accept.runtime_profile(self.data.review, prepared, header, self.data.request)
        header.write_text(original, encoding='utf-8')

    def test_raw_edit_record_must_be_dirty_and_transaction_closed(self):
        self.raw[25208 + 80 + 40] = 0; self.raw[25208 + 128 + 40] = 0
        self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_EDIT_NOTIFY_RECORD_DELTA'): accept.validate_run(self.run)
        self.raw[25208 + 80 + 40] = 1; self.raw[25208 + 128 + 40] = 1
        struct.pack_into('<i', self.raw, 37624 + 20, 1); self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_EDIT_DEPTH_OR_PENDING'): accept.validate_run(self.run)

    def test_old_component_and_catalog_identity_must_survive(self):
        self.raw[976624 + 1136 + 36] = 0; self.save_record()
        with self.assertRaisesRegex(ValueError, 'COMPONENT_POST_BINDING_CHANGED'): accept.validate_run(self.run)
        self.raw[976624 + 1136 + 36] = 1
        struct.pack_into('<Q', self.raw, 682008 + 160 + 8, 0x35000); self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_CATALOG_CHANGED'): accept.validate_run(self.run)

    def test_summary_and_duplicate_hex_cannot_override_raw(self):
        self.record['bindingResult']['setterCalled'] = False
        self.data.write(self.run / 'stdout.jsonl', self.record)
        with self.assertRaisesRegex(ValueError, 'BINDING_RAW_SUMMARY_MISMATCH:setterCalled'): accept.validate_run(self.run)
        self.save_record(); self.record['editAfterCloseHex'] = '00' * 12416
        self.data.write(self.run / 'stdout.jsonl', self.record)
        with self.assertRaisesRegex(ValueError, 'BINDING_RAW_DUPLICATE_MISMATCH'): accept.validate_run(self.run)

    def test_wrong_target_metadata_and_missing_attempt_rejected(self):
        struct.pack_into('<I', self.raw, 120, 124); self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_ACTION_NOT_COMPLETE'): accept.validate_run(self.run)
        struct.pack_into('<I', self.raw, 120, 123); struct.pack_into('<I', self.raw, 32, 16); self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_NATIVE_NOT_COMPLETE'): accept.validate_run(self.run)
        (self.run / 'attempt.used').unlink()
        with self.assertRaisesRegex(ValueError, 'BINDING_ATTEMPT_REQUIRED'): accept.validate_run(self.run)

    def test_failed_action_retains_pending_transaction_and_attempt(self):
        struct.pack_into('<I', self.raw, 112, 26)
        self.raw[296 + 23] = 1; self.save_record()
        result = accept.accept_run(self.run)
        self.assertFalse(result['ok'])
        self.assertTrue(result['reportedComponentMutationCalled'] and result['reportedTransactionMayBeOpen'])
        self.assertTrue((self.run / 'attempt.used').is_file())

    def test_bag_single_reference_uses_same_transaction_with_no_shop_add(self):
        request = copy.deepcopy(self.data.request)
        request['action'] = 'bind-bag'; request['parameters']['templateId'] = 1119879169
        struct.pack_into('<I', self.raw, 124, 1119879169)
        struct.pack_into('<Qi', self.raw, 168, 0, 0)
        struct.pack_into('<Qi', self.raw, 216, self.classes[0], 33)
        struct.pack_into('<Qi', self.raw, 264, 0, 0)
        self.raw[278] = self.raw[279] = 0
        struct.pack_into('<i', self.raw, 368, 33)
        for at in (419704, 682008):
            struct.pack_into('<IIQQ', self.raw, at + 160, 1119879169, 12, 0x34000, self.classes[3])
        for at in (965248, 976624):
            struct.pack_into('<Qi', self.raw, at + 1136 + 40 + 24, self.classes[0], 33)
            struct.pack_into('<i', self.raw, at + 116, 33)
        struct.pack_into('<2Q2Ii', self.raw, 988032, 0x33000, 0, 1119879169, 0, 0)
        result = raw_api.verify_binding(bytes(self.raw), raw_api.decode_native(bytes(self.raw)),
            request=request, current=self.scene)
        self.assertTrue(result['bindingVerified'] and result['ownerNotificationVerified'])
        self.assertEqual(result['shopIndex'], 0)

    def test_existing_binding_reuse_requires_no_component_or_transaction_mutation(self):
        struct.pack_into('<I', self.raw, 112, 1)
        self.raw[291] = 1; self.raw[295] = self.raw[105] = 0
        struct.pack_into('<I', self.raw, 184, 0)
        struct.pack_into('<Q4B', self.raw, 232, 0, 0, 1, 0, 0)
        self.raw[248:288] = bytes(40); struct.pack_into('<I', self.raw, 248, 1)
        self.raw[296:50040] = bytes(49744)
        self.raw[953872:965248] = self.raw[965248:976624]
        self.raw[988000:988032] = self.raw[988032:988064]
        self.save_record()
        result = accept.validate_run(self.run)
        self.assertTrue(result['reused'] and result['bindingVerified'])
        self.assertFalse(result['ownerNotificationVerified'])
        self.raw[105] = 1; self.save_record()
        with self.assertRaisesRegex(ValueError, 'BINDING_REUSE_MUTATED'): accept.validate_run(self.run)


if __name__ == '__main__': unittest.main()
