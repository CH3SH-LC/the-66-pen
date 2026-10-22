"""Complete large-scene fixtures and durable no-replay tests; no game access."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import scene_scale as scale
import build_scene_profile as builder
import build_readonly_profile as readonly
import discover_current_level as discovery
sys.path.insert(0, str(scale.ROOT))
from backend import scene_observation


def receipt(count, *, version=2, start=1000):
    decoder = readonly.load_decoder()
    capacity = 4096 if version == 2 else 512
    data = bytearray(440 + capacity * 64)
    struct.pack_into('<4I', data, 0, len(data), version, 0, 1951)
    pointers = [0x140000000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000, 0x70000,
                0x80000, 0x90000, 0xa0000, 0xb0000]
    struct.pack_into('<11Q', data, 16, *pointers)
    counts = [builder.TIMESTAMP, builder.IMAGE_SIZE, 0, 1, 1, 1, max(count, 1), count, count, 0,
              count * 64 + 1000, count * 6 + 30, 2, 4, 4, 0]
    struct.pack_into('<16I', data, 104, *counts)
    struct.pack_into('<3fI', data, 168, 100.0, 20.0, -60.0, 99)
    struct.pack_into('<2Q', data, 184, *(pointers[0] + int(x, 16) for x in builder.NATIVE_PROFILE['callbackStackRvas']))
    for index in range(count):
        entity_id = start + index
        struct.pack_into('<QQQIIIIfffIQ', data, 440 + index * 64, 0xc0000 + index * 256,
                         0x800000 + index * 64, 0x80000, entity_id, entity_id, 20001034, 79,
                         0, 0, 0, 0, 0)
    return {'snapshotBytes': len(data), 'snapshotHex': data.hex()}


def snapshot(count):
    return readonly.load_decoder().decode_snapshot(receipt(count))


def placement(index=0):
    return dict(template_id=20001034, position=[100.0 + index, 20.0, -60.0], rotation=[0, 90, 0], scale=[1, 2, 1])


class LargeSnapshotTests(unittest.TestCase):
    def test_legacy_and_600_3000_4096_full_decode(self):
        for count, version in [(20, 1), (512, 1), (600, 2), (3000, 2), (4096, 2)]:
            with self.subTest(count=count, version=version):
                value = readonly.load_decoder().decode_snapshot(receipt(count, version=version))
                self.assertEqual(len(value['entities']), count)
                self.assertEqual(len(builder.validate_baseline(value, 'save')), count)
                self.assertEqual(value['levelObservation']['levelId'], 99)

    def test_cross_abi_version_and_declared_size_refused(self):
        record = receipt(600)
        changed = bytearray.fromhex(record['snapshotHex'])
        struct.pack_into('<I', changed, 4, 1)
        with self.assertRaises(ValueError):
            readonly.load_decoder().decode_snapshot(dict(record, snapshotHex=changed.hex()))
        with self.assertRaises(ValueError):
            readonly.load_decoder().decode_snapshot(dict(record, snapshotBytes=33208))

    def test_partial_duplicate_or_wrong_owner_cannot_be_baseline(self):
        for field in ('truncated', 'count', 'duplicate', 'owner'):
            value = snapshot(600)
            if field == 'truncated': value['flags']['value'] |= 32
            if field == 'count': value['counts']['entityValidEntries'] += 1
            if field == 'duplicate': value['entities'][-1]['id'] = value['entities'][0]['id']
            if field == 'owner': value['entities'][-1]['flags']['value'] &= ~4
            with self.subTest(field=field), self.assertRaises(ValueError):
                builder.validate_baseline(value, 'create-batch', templates=(20001034,))

    def test_full_identity_reconciliation_above_old_ceiling(self):
        before, after = snapshot(600), snapshot(664)
        rows = [placement(i) for i in range(64)]
        ids = list(range(1600, 1664))
        self.assertTrue(scale.reconcile_batch(before, after, rows, ids)['ok'])
        for mutation in ('baseline-owner', 'extra-entity', 'duplicate-new', 'wrong-template', 'origin'):
            bad = copy.deepcopy(after)
            selected = list(ids)
            if mutation == 'baseline-owner': bad['entities'][599]['owner'] = '0x123456'
            if mutation == 'extra-entity': selected[-1] = 9000
            if mutation == 'duplicate-new': selected[-1] = selected[0]
            if mutation == 'wrong-template': bad['entities'][-1]['configId'] = 123
            if mutation == 'origin': bad['origin'][0] += 1
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                scale.reconcile_batch(before, bad, rows, selected)

    def test_single_callback_stays_bounded_but_scene_exceeds_512(self):
        self.assertEqual(len(builder.validate_baseline(snapshot(1000), 'create-batch', templates=(20001034,) * 256)), 1000)
        with self.assertRaises(ValueError):
            builder.validate_baseline(snapshot(1000), 'create-batch', templates=(20001034,) * 257)
        with self.assertRaises(ValueError):
            builder.validate_baseline(snapshot(4096), 'create')

    def test_discovery_selector_keeps_legacy_default(self):
        self.assertNotIn('largeScene', discovery.build_queue_request(HERE / 'unused.json'))
        self.assertIs(discovery.build_queue_request(HERE / 'unused.json', large_scene=True)['largeScene'], True)
        with self.assertRaises(ValueError): discovery.build_queue_request(HERE / 'unused.json', large_scene=1)

    def test_plan_budget_coordinate_and_numeric_guards(self):
        value = scale.normalize_plan({'placements': [placement(i) for i in range(600)]})
        self.assertEqual(len(value['placements']), 600)
        for changed in ({'placements': [placement()], 'coordinateSpace': 'local'},
                        {'placements': [dict(placement(), scale=[1, 0, 1])]},
                        {'placements': [dict(placement(), position=[True, 0, 0])]}):
            with self.assertRaises(ValueError): scale.normalize_plan(changed)
        with self.assertRaises(ValueError): scale.normalize_plan({'placements': [placement()]}, entity_budget=3001)

    def test_v2_pagination_retains_all_3000_ids_and_binds_cursor(self):
        value = snapshot(3000)
        value['counts']['entityCapacity'] = 8192
        projection = scene_observation.project_snapshot(value,
            identity={'targetHandle': 'scale-fixture', 'levelId': 99, 'observedAt': '2026-10-15T00:00:00Z'})
        self.assertTrue(projection['complete'])
        cursor, ids = None, []
        while True:
            page = scene_observation.page_entities(projection, cursor=cursor, maxItems=128)
            ids.extend(row['entityId'] for row in page['items'])
            cursor = page['nextCursor']
            if cursor is None: break
        self.assertEqual(ids, list(range(1000, 4000)))
        value['structureSize'] = 33208
        with self.assertRaises(scene_observation.ObservationError):
            scene_observation.project_snapshot(value, identity={'targetHandle': 'scale-fixture', 'levelId': 99})


class SavedCardBindingTests(unittest.TestCase):
    def setUp(self):
        base = scale.ROOT / '.runtime/map-foundation-20261015/scale/test-work'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.run = Path(self.temp.name)
        self.session = dict(pid=123, tid=456, processCreation=123456789, threadCreation=123456790)
        self.prepared = dict(session=self.session, request=dict(action='save', levelId=99))
        self.constants = dict(HR_ACTION=2, HR_EXPECTED_LEVEL=99, HR_TARGET_PID=123,
            HR_TARGET_TID=456, HR_TARGET_CREATION=123456789, HR_TARGET_THREAD_CREATION=123456790,
            HR_NONCE=9223372036854775783, HR_DEADLINE=76543210)
        self.record = dict(receiptNonce=str(self.constants['HR_NONCE']),
                           receiptDeadline=str(self.constants['HR_DEADLINE']), receiptProtocol=3)
        self.publish_header(self.constants)

    def tearDown(self):
        self.temp.cleanup()

    def publish_header(self, constants, extra=''):
        header = self.run / 'target_config.h'
        header.write_text(''.join('#define %s %dULL\n' % pair for pair in constants.items()) + extra,
                          encoding='utf-8')
        (self.run / 'build-result.json').write_text(json.dumps({'hashes': {'target_config.h': scale.digest(header)}}),
                                                   encoding='utf-8')

    def test_exact_decimal_card_identity_preserves_64_bit_nonce(self):
        result = scale.bind_save_card(self.run, self.prepared, self.record, 99)
        self.assertTrue(result['verified'])
        self.assertEqual(result['nonce'], '9223372036854775783')
        self.assertEqual(result['protocol'], 3)

    def test_wrong_nonce_deadline_protocol_and_types_are_rejected(self):
        changes = ({'receiptNonce': '9223372036854775784'}, {'receiptDeadline': '76543211'},
                   {'receiptProtocol': 2}, {'receiptProtocol': '3'}, {'receiptProtocol': True},
                   {'receiptNonce': self.constants['HR_NONCE']}, {'receiptDeadline': 76543210},
                   {'receiptNonce': '09223372036854775783'})
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'CARD_MISMATCH'):
                scale.bind_save_card(self.run, self.prepared, dict(self.record, **change), 99)

    def test_legacy_missing_card_fields_is_explicitly_unverified(self):
        for key in self.record:
            legacy = dict(self.record)
            legacy.pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'UNVERIFIED_LEGACY'):
                scale.bind_save_card(self.run, self.prepared, legacy, 99)

    def test_hashed_header_action_session_and_unique_constants_are_bound(self):
        with (self.run / 'target_config.h').open('a', encoding='utf-8') as stream:
            stream.write('// changed\n')
        with self.assertRaisesRegex(ValueError, 'HEADER_CHANGED'):
            scale.bind_save_card(self.run, self.prepared, self.record, 99)
        for key, value in (('HR_ACTION', 3), ('HR_EXPECTED_LEVEL', 100), ('HR_TARGET_PID', 124),
                           ('HR_TARGET_TID', 457), ('HR_TARGET_CREATION', 123456780),
                           ('HR_TARGET_THREAD_CREATION', 123456780), ('HR_NONCE', 0), ('HR_DEADLINE', 0)):
            self.publish_header(dict(self.constants, **{key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                scale.bind_save_card(self.run, self.prepared, self.record, 99)
        self.publish_header(self.constants, '#define HR_NONCE 9ULL\n')
        with self.assertRaisesRegex(ValueError, 'CONSTANT_REQUIRED:HR_NONCE'):
            scale.bind_save_card(self.run, self.prepared, self.record, 99)

    def test_saved_verifier_rejects_legacy_before_accepting_saved_bytes(self):
        reply = dict(ok=True, action='save', run=str(self.run))
        (self.run / 'result.json').write_text(json.dumps(reply), encoding='utf-8')
        record = {'action': {'kind': 2, 'nativeSaveStatus': 0}}
        with patch.object(scale, 'load', return_value=(self.run, {'levelId': 99}, {})), \
             patch.object(scale, 'status', return_value={'complete': True}), \
             patch.object(scale, 'verified_run', return_value=(self.run, {}, self.prepared, record)):
            with self.assertRaisesRegex(ValueError, 'UNVERIFIED_LEGACY'):
                scale.verify_save(self.run, self.run)


class DurableBatchTests(unittest.TestCase):
    def setUp(self):
        base = scale.ROOT / '.runtime/map-foundation-20261015/scale/test-work'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.output_patch = patch.object(scale, 'OUTPUT', self.root / 'operations')
        self.output_patch.start()
        self.session = self.root / 'session.json'
        self.session.write_text('{}', encoding='utf-8')
        self.plan = self.root / 'plan.json'
        self.plan.write_text(json.dumps({'placements': [placement(i) for i in range(600)]}), encoding='utf-8')
        self.operation = Path(scale.prepare(self.plan, 'full600', 99)['operation'])

    def tearDown(self):
        self.output_patch.stop()
        self.temp.cleanup()

    def drive(self, fail_batch=None, drift_batch=None):
        state = {'count': 20, 'batch': 0, 'calls': []}
        def dispatch(action, *args, **kwargs):
            state['calls'].append(action)
            if action == 'inspect':
                count = state['count'] + (1 if state['batch'] == drift_batch else 0)
                return dict(ok=True, run=str(self.root), fixtureCount=count, fixtureAction=action)
            if state['batch'] == fail_batch:
                return dict(ok=False, outcomeUncertain=True, fixtureAction=action)
            before = state['count']
            state['count'] += len(kwargs['placements'])
            state['batch'] += 1
            return dict(ok=True, run=str(self.root), fixtureCount=state['count'], fixtureBefore=before, fixtureAction=action)
        def verified(reply, level_id, kind):
            if not reply.get('ok'): raise ValueError('PARTIAL_FIXTURE')
            count = reply['fixtureCount']
            before = reply.get('fixtureBefore', count)
            record = receipt(before)
            record['action'] = dict(placedIds=list(range(1000 + before, 1000 + count)))
            prepared = {'session': {}}
            if reply['fixtureAction'] != 'inspect':
                start = before - 20
                rows = [scale.scene_cli.normalize_placement(placement(i), i) for i in range(start, count - 20)]
                prepared = dict(session={}, request=dict(action='create-batch', levelId=99, placements=rows), reviewSha256='fixture')
            return self.root, snapshot(count), prepared, record
        with patch.object(scale, 'send', side_effect=dispatch), \
             patch.object(scale, 'verified_run', side_effect=verified), \
             patch.object(scale.reviewer, 'orchestrate', return_value=dict(reviewPath='fixture', reviewSha256='fixture')), \
             patch.object(scale, 'digest', return_value='fixture'), \
             patch.object(scale, 'load', return_value=(self.operation, {'levelId': 99}, scale.normalize_plan(json.loads(self.plan.read_text())))), \
             patch.object(scale, 'raw_evidence_hashes', return_value={}):
            try: result = scale.run(self.operation, self.session, queue=self.root)
            except ValueError as error: result = dict(error=str(error))
        return result, state

    def test_600_plan_crosses_both_old_limits_in_ten_batches(self):
        result, state = self.drive()
        self.assertTrue(result['complete'])
        self.assertEqual(result['committed'], 600)
        self.assertEqual(state['calls'], ['inspect', 'create-batch'] * 10)
        ids = scale.read(self.operation / 'created.json')['entityIds']
        self.assertEqual(ids, list(range(1020, 1620)))
        self.assertFalse(result['persistentSaveVerified'])

    def test_partial_batch_is_claimed_and_blocks_automatic_replay(self):
        result, state = self.drive(fail_batch=0)
        self.assertIn('PARTIAL', result['error'])
        self.assertTrue((self.operation / 'batch-0000/claim.json').exists())
        self.assertTrue((self.operation / 'batch-0000/blocked.json').exists())
        with patch.object(scale, 'send') as sender:
            with self.assertRaisesRegex(ValueError, 'ALREADY_ATTEMPTED'):
                scale.run(self.operation, self.session, queue=self.root)
            sender.assert_not_called()

    def test_external_scene_change_stops_before_next_create(self):
        result, state = self.drive(drift_batch=1)
        self.assertIn('SCENE_CHANGED', result['error'])
        self.assertEqual(state['calls'], ['inspect', 'create-batch', 'inspect'])
        self.assertFalse((self.operation / 'batch-0001/claim.json').exists())

    def test_plan_tamper_refuses_before_dispatch(self):
        with (self.operation / 'plan.json').open('a', encoding='utf-8') as stream: stream.write(' ')
        with patch.object(scale, 'send') as sender:
            with self.assertRaisesRegex(ValueError, 'PLAN_CHANGED'):
                scale.run(self.operation, self.session, queue=self.root)
            sender.assert_not_called()


class SavedDirectoryPreservationTests(unittest.TestCase):
    """Exercise the real saved verifier with raw GIL directory bytes.

    Native transport/card binding has independent tests above. Only those
    prerequisites are stubbed here; no directory parser or comparison is mocked.
    An empty extra tab is still an unrequested root6 change.
    """
    def setUp(self):
        base = scale.ROOT / '.runtime/mondstadt/rework-20261017/save-analysis/test-work'
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.operation = Path(self.temp.name)
        self.saved = self.operation / 'save'
        self.saved.mkdir()
        spec = importlib.util.spec_from_file_location('_directory_regression_reader', HERE / 'verify-created-save.py')
        self.reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.reader)
        self.raw = self.reader.builder.raw
        self.old_ids, self.new_id = [1000, 1001], 1002
        self.plan = dict(batchSize=1, placements=[placement()])
        self.before_dir = self.category(3, self.old_ids) + self.category(6, [])
        self.after_dir = self.category(3, self.old_ids + [self.new_id]) + self.category(6, [])

    def category(self, kind, ids, *, name='未分类页签', member_kind=200):
        raw = self.raw
        owner = raw.rec(1, b'root') + raw.recv(3, 1)
        node = raw.rec(1, name.encode('utf-8')) + raw.recv(3, 2)
        node += b''.join(raw.rec(5, raw.recv(1, member_kind) + raw.recv(2, i)) for i in ids)
        return raw.rec(1, raw.recv(1, kind) + raw.rec(2, owner) + raw.rec(3, node))

    def entity(self, entity_id):
        raw = self.raw
        def vector(values):
            return b''.join(raw._enc_varint((i + 1) << 3 | 5) + struct.pack('<f', v)
                            for i, v in enumerate(values))
        pose = b''.join(raw.rec(i + 1, vector(v)) for i, v in enumerate(([0, 0, 0], [0, 90, 0], [1, 2, 1])))
        return raw.rec(1, raw.recv(1, entity_id) + raw.rec(2, raw.recv(1, 20001034)) +
                       raw.rec(6, raw.recv(1, 1) + raw.rec(11, pose)))

    def verify(self, directory=None):
        raw = self.raw
        before = raw.rec(5, b''.join(self.entity(i) for i in self.old_ids)) + raw.rec(6, self.before_dir)
        after = raw.rec(5, b''.join(self.entity(i) for i in self.old_ids + [self.new_id])) + raw.rec(6, self.after_dir if directory is None else directory)
        before_path, after_path = self.operation / 'before.gil', self.saved / 'after.gil'
        before_path.write_bytes(self.reader.builder.wrap_payload(before, 2, 1))
        after_path.write_bytes(self.reader.builder.wrap_payload(after, 2, 1))
        review = self.operation / 'review.json'
        scale.write(review, dict(recovery=dict(backup=str(before_path), sha256=scale.digest(before_path))))
        batch = self.operation / 'batch-0000'; batch.mkdir()
        scale.write(batch / 'claim.json', dict(reviewPath=str(review), reviewSha256=scale.digest(review)))
        scale.write(batch / 'commit.json', dict(run=str(self.saved)))
        scale.write(self.operation / 'created.json', dict(entityIds=[self.new_id]))
        reply = dict(ok=True, action='save', run=str(self.saved),
            beforeGils={'99': dict(sha256=scale.digest(before_path))},
            afterGils={'99': dict(snapshot=str(after_path), sha256=scale.digest(after_path))})
        scale.write(self.saved / 'result.json', reply)
        scale.write(self.saved / 'stdout.jsonl', {'fixture': 'directory-only; native receipt prerequisites stubbed'})
        state = snapshot(3)
        record = dict(action=dict(kind=2, nativeSaveStatus=0))
        with patch.object(scale, 'load', return_value=(self.operation, {'levelId': 99}, self.plan)), \
             patch.object(scale, 'status', return_value={'complete': True}), \
             patch.object(scale, 'verified_run', return_value=(self.saved, state, {'session': {}}, record)), \
             patch.object(scale, 'bind_save_card', return_value={'verified': True}):
            return scale.verify_save(self.operation, self.saved)

    def test_only_requested_registration_preserves_directory(self):
        result = self.verify()
        self.assertTrue(result['persistentSaveVerified'])
        self.assertTrue(result['otherDirectoryBytesPreserved'])
        self.assertFalse(result['allSaveDomainsVerified'])

    def test_extra_empty_category36_is_rejected_exactly_as_live_save(self):
        extra = bytes.fromhex('0a21082412080a04726f6f7418011a130a0fe69caae58886e7b1bbe9a1b5e7adbe1802')
        self.assertEqual(extra, self.category(36, []))
        with self.assertRaisesRegex(ValueError, '^OTHER_DIRECTORY_BYTES_CHANGED$'):
            self.verify(self.after_dir + extra)

    def test_existing_entity_category_name_change_rejected(self):
        changed = self.category(3, self.old_ids + [self.new_id], name='changed') + self.category(6, [])
        with self.assertRaisesRegex(ValueError, '^OTHER_DIRECTORY_BYTES_CHANGED$'):
            self.verify(changed)

    def test_existing_reference_order_change_rejected(self):
        changed = self.category(3, list(reversed(self.old_ids)) + [self.new_id]) + self.category(6, [])
        with self.assertRaisesRegex(ValueError, '^OTHER_DIRECTORY_BYTES_CHANGED$'):
            self.verify(changed)

    def test_other_category_removal_rejected(self):
        with self.assertRaisesRegex(ValueError, '^OTHER_DIRECTORY_BYTES_CHANGED$'):
            self.verify(self.category(3, self.old_ids + [self.new_id]))

    def test_other_category_content_change_rejected(self):
        changed = self.category(3, self.old_ids + [self.new_id]) + self.category(6, [], name='changed')
        with self.assertRaisesRegex(ValueError, '^OTHER_DIRECTORY_BYTES_CHANGED$'):
            self.verify(changed)

    def test_duplicate_new_registration_rejected(self):
        changed = self.category(3, self.old_ids + [self.new_id, self.new_id]) + self.category(6, [])
        with self.assertRaisesRegex(ValueError, '^SAVED_DIRECTORY_REGISTRATION_MISMATCH$'):
            self.verify(changed)

    def test_wrong_registration_kind_rejected(self):
        changed = self.category(3, self.old_ids + [self.new_id], member_kind=201) + self.category(6, [])
        with self.assertRaisesRegex(ValueError, '^SAVED_DIRECTORY_REGISTRATION_MISMATCH$'):
            self.verify(changed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
