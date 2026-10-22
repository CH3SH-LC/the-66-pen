"""Offline queue boundary tests. All process/queue dispatch is replaced."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('native_map_queue_tests_client',
    PROJECT / 'tools/editor-bridge/elevated-request.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class MapQueueTests(unittest.TestCase):
    def setUp(self):
        work = PROJECT / '.runtime/map-foundation-20261015/integration/test-work'
        work.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=work, prefix='map-queue-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.queue = self.root / '.runtime/editor-bridge/queue'
        self.queue.mkdir(parents=True)
        self.roots = {tool: self.root / '.runtime/map-foundation-20261015' / folder / 'prepared'
                      for tool, folder in (('entity-transform', 'transform'), ('terrain', 'terrain'))}
        self.roots['playtest-control'] = self.root / '.runtime/playtest-control-20261016/prepared'
        self.roots['asset-inspection'] = self.root / '.runtime/asset-inspection-20261017/prepared'
        self.roots['entity-material'] = self.root / '.runtime/entity-material-20261017/prepared'
        self.roots['terrain-water'] = self.root / '.runtime/terrain-water-20261017/prepared'
        self.roots['template-properties'] = self.root / '.runtime/template-properties-20261017/v2-prepared'
        for tool in ('template-item', 'template-currency', 'generalized-tabs', 'mondstadt-dropstuff', 'mondstadt-combat', 'role-template-bag'):
            self.roots[tool] = self.root / '.runtime/native-card-20261017/prepared' / tool
        self.run = self.roots['entity-transform'] / 'one-card'
        self.run.mkdir(parents=True)
        (self.run / 'prepared.json').write_text('{}', encoding='utf-8')
        self.heartbeat = self.queue / 'runner.heartbeat'
        self.heartbeat.write_text(datetime.now(timezone.utc).isoformat() + ' pid=42 handled=0', encoding='utf-8')
        for key, value in (('ROOT', self.root), ('NATIVE_MAP_ROOTS', self.roots), ('QUEUE', self.queue)):
            changer = patch.object(client, key, value)
            changer.start()
            self.addCleanup(changer.stop)
        self.health = {'kind': 'status', 'pid': 42, 'elevated': True,
            'deadlineUtc': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            'nativeScene': {'blocked': False, 'pinsDigest': 'a' * 64},
            'nativeMap': {'schema': 1, 'enabled': True, 'tools': list(client.NATIVE_MAP_TOOLS),
                          'projectRoot': str(self.root), 'pinsDigest': 'a' * 64}}

    def payload(self):
        return {'kind': 'native-map', 'tool': 'entity-transform', 'runPath': str(self.run),
                'preparedSha256': client.hashlib.sha256(b'{}').hexdigest()}

    def test_closed_schema_and_tool_root(self):
        self.assertEqual(client.validate_native_map_request(self.payload()), self.payload())
        bad = [dict(self.payload(), command='anything'), dict(self.payload(), tool='unknown'),
               dict(self.payload(), tool='terrain'), dict(self.payload(), runPath='relative'),
               dict(self.payload(), runPath=str(self.root)), dict(self.payload(), runPath=True),
               dict(self.payload(), preparedSha256='0'*64)]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises((ValueError, OSError)):
                client.validate_native_map_request(payload)

    def test_role_bag_has_exact_root_and_never_crosses_template_routes(self):
        run = self.roots['role-template-bag'] / 'bag-card'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        payload = dict(self.payload(), tool='role-template-bag', runPath=str(run))
        self.assertEqual(client.validate_native_map_request(payload), payload)
        for tool in ('generalized-tabs', 'template-properties', 'template-item'):
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, 'WRONG_TOOL_ROOT'):
                client.validate_native_map_request(dict(payload, tool=tool))

    def test_repeat_polls_original_id_even_after_heartbeat_expires(self):
        reply = {'ok': True, 'cleanupVerified': True}
        with patch.object(client, 'send', side_effect=[self.health, reply]) as sender:
            first = client.send_native_map('entity-transform', self.run, queue_dir=self.queue)
        self.assertEqual(sender.call_count, 2)
        self.assertEqual(sender.call_args.args[0], self.payload())
        self.heartbeat.write_text('2000-01-01T00:00:00+00:00 pid=42 handled=1', encoding='utf-8')
        with patch.object(client, 'send', side_effect=AssertionError('no second dispatch')), \
                patch.object(client, 'poll_request', return_value=reply) as poll:
            second = client.send_native_map('entity-transform', self.run, queue_dir=self.queue)
        self.assertEqual(first['queueRequestId'], second['queueRequestId'])
        poll.assert_called_once_with(first['queueRequestId'], 300.0)

    def test_playtest_observation_uses_its_own_immutable_card_root(self):
        run = self.roots['playtest-control'] / 'mode-observation'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        payload = dict(self.payload(), tool='playtest-control', runPath=str(run))
        self.assertEqual(client.validate_native_map_request(payload), payload)
        for tool in ('entity-transform', 'terrain'):
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, 'WRONG_TOOL_ROOT'):
                client.validate_native_map_request(dict(payload, tool=tool))
        with patch.object(client, 'send', side_effect=[self.health, {'ok': True, 'cleanupVerified': True}]) as sender:
            first = client.send_native_map('playtest-control', run, queue_dir=self.queue)
        self.assertEqual(sender.call_args.args[0], payload)
        with patch.object(client, 'send', side_effect=AssertionError('no replay')), \
                patch.object(client, 'poll_request', return_value={'ok': True}) as poll:
            client.send_native_map('playtest-control', run, queue_dir=self.queue)
        poll.assert_called_once_with(first['queueRequestId'], 300.0)

    def test_pending_card_is_preserved_and_does_not_use_another_queue(self):
        pending = {'ok': False, 'pending': True, 'outcomeUncertain': True, 'retryAttempted': False}
        with patch.object(client, 'send', side_effect=[self.health, pending]):
            result = client.send_native_map('entity-transform', self.run)
        self.assertTrue(result['outcomeUncertain'])
        self.assertTrue((self.run / 'map-queue-claim.json').is_file())
        other = self.queue.parent / 'other-queue'
        other.mkdir()
        with patch.object(client, 'send') as sender, self.assertRaisesRegex(ValueError, 'CLAIM_CONFLICT'):
            client.send_native_map('entity-transform', self.run, queue_dir=other)
        sender.assert_not_called()

    def test_asset_inspection_card_cannot_cross_route_or_replay(self):
        run = self.roots['asset-inspection'] / 'observed-assets'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        payload = dict(self.payload(), tool='asset-inspection', runPath=str(run))
        self.assertEqual(client.validate_native_map_request(payload), payload)
        for tool in ('entity-transform', 'terrain', 'playtest-control'):
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, 'WRONG_TOOL_ROOT'):
                client.validate_native_map_request(dict(payload, tool=tool))
        with patch.object(client, 'send', side_effect=[self.health, {'ok': False, 'pending': True, 'outcomeUncertain': True}]) as sender:
            first = client.send_native_map('asset-inspection', run, queue_dir=self.queue)
        self.assertEqual(sender.call_args.args[0], payload)
        with patch.object(client, 'send', side_effect=AssertionError('no replay')), \
                patch.object(client, 'poll_request', return_value={'pending': True}) as poll:
            client.send_native_map('asset-inspection', run, queue_dir=self.queue)
        poll.assert_called_once_with(first['queueRequestId'], 300.0)

    def test_missing_capability_or_active_native_call_prevents_map_dispatch(self):
        for key in ('capability', 'blocked', 'pins'):
            health = json.loads(json.dumps(self.health))
            if key == 'capability':
                del health['nativeMap']
            elif key == 'blocked':
                health['nativeScene']['blocked'] = True
            else:
                health['nativeMap']['pinsDigest'] = 'b' * 64
            with self.subTest(key=key), patch.object(client, 'send', return_value=health) as sender:
                with self.assertRaisesRegex(ValueError, 'CAPABILITY_OR_IDENTITY'):
                    client.send_native_map('entity-transform', self.run)
                sender.assert_called_once_with({'kind': 'status'}, timeout=30.0)
                self.assertFalse((self.run / 'map-queue-claim.json').exists())

    def test_fixed_native_cards_are_disjoint_and_single_use(self):
        for tool in ('template-item', 'template-currency', 'generalized-tabs', 'mondstadt-dropstuff', 'mondstadt-combat', 'entity-material', 'terrain-water', 'template-properties'):
            run = self.roots[tool] / 'one-card'
            run.mkdir(parents=True)
            (run / 'prepared.json').write_text('{}', encoding='utf-8')
            payload = dict(self.payload(), tool=tool, runPath=str(run))
            self.assertEqual(client.validate_native_map_request(payload), payload)
            for wrong in set(client.NATIVE_MAP_TOOLS) - {tool}:
                with self.subTest(tool=tool, wrong=wrong), self.assertRaisesRegex(ValueError, 'WRONG_TOOL_ROOT'):
                    client.validate_native_map_request(dict(payload, tool=wrong))
            with patch.object(client, 'send', side_effect=[self.health, {'ok': True}]) as sender:
                result = client.send_native_map(tool, run, queue_dir=self.queue)
            self.assertEqual(sender.call_args.args[0], payload)
            with patch.object(client, 'send', side_effect=AssertionError('never replay')), \
                    patch.object(client, 'poll_request', return_value={'ok': True}) as poll:
                client.send_native_map(tool, run, queue_dir=self.queue)
            poll.assert_called_once_with(result['queueRequestId'], 300.0)

    def test_material_card_rejects_old_helper_before_mutation_intent(self):
        run = self.roots['entity-material'] / 'material-card'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        health = json.loads(json.dumps(self.health))
        health['nativeMap']['tools'].remove('entity-material')
        with patch.object(client, 'send', return_value=health) as sender:
            with self.assertRaisesRegex(ValueError, 'CAPABILITY_OR_IDENTITY'):
                client.send_native_map('entity-material', run, queue_dir=self.queue)
        sender.assert_called_once_with({'kind': 'status'}, timeout=30.0)
        self.assertFalse((run / 'map-queue-claim.json').exists())

    def test_material_unknown_response_polls_same_id_without_resubmit(self):
        run = self.roots['entity-material'] / 'unknown-card'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        pending = {'ok': False, 'pending': True, 'outcomeUncertain': True}
        with patch.object(client, 'send', side_effect=[self.health, pending]):
            first = client.send_native_map('entity-material', run, queue_dir=self.queue)
        with patch.object(client, 'send', side_effect=AssertionError('never resubmit')) as sender, \
                patch.object(client, 'poll_request', return_value=pending) as poll:
            second = client.send_native_map('entity-material', run, queue_dir=self.queue)
        sender.assert_not_called()
        self.assertEqual(first['queueRequestId'], second['queueRequestId'])
        self.assertTrue(second['outcomeUncertain'])
        poll.assert_called_once_with(first['queueRequestId'], 300.0)

    def test_invalid_timeout_leaves_no_claim(self):
        for value in (True, -1, 1801, float('nan')):
            with self.subTest(timeout=value), self.assertRaisesRegex(ValueError, 'TIMEOUT_INVALID'):
                client.send_native_map('entity-transform', self.run, timeout=value)
        self.assertFalse((self.run / 'map-queue-claim.json').exists())

    def test_water_card_requires_new_capability_and_keeps_unknown_request(self):
        run = self.roots['terrain-water'] / 'water-card'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        old = json.loads(json.dumps(self.health))
        old['nativeMap']['tools'].remove('terrain-water')
        with patch.object(client, 'send', return_value=old) as sender:
            with self.assertRaisesRegex(ValueError, 'CAPABILITY_OR_IDENTITY'):
                client.send_native_map('terrain-water', run, queue_dir=self.queue)
        sender.assert_called_once_with({'kind': 'status'}, timeout=30.0)
        self.assertFalse((run / 'map-queue-claim.json').exists())
        pending = {'ok': False, 'pending': True, 'outcomeUncertain': True}
        with patch.object(client, 'send', side_effect=[self.health, pending]):
            first = client.send_native_map('terrain-water', run, queue_dir=self.queue)
        with patch.object(client, 'send', side_effect=AssertionError('never resubmit')) as sender, \
                patch.object(client, 'poll_request', return_value=pending) as poll:
            second = client.send_native_map('terrain-water', run, queue_dir=self.queue)
        sender.assert_not_called()
        self.assertEqual(first['queueRequestId'], second['queueRequestId'])
        self.assertTrue(second['outcomeUncertain'])
        poll.assert_called_once_with(first['queueRequestId'], 300.0)

    def test_card_marker_without_queue_receipt_remains_pending(self):
        rid = '1' * 32
        (self.run / 'map-queue-claim.json').write_text(json.dumps({
            'schema': 1, 'requestId': rid, 'request': self.payload(), 'queueDir': str(self.queue)}), encoding='utf-8')
        with patch.object(client, 'send', side_effect=AssertionError('must not infer permission to resend')):
            result = client.send_native_map('entity-transform', self.run, timeout=0)
        self.assertTrue(result['pending'])
        self.assertTrue(result['outcomeUncertain'])
        self.assertEqual(result['queueRequestId'], rid)

    def test_template_properties_requires_current_helper_and_never_replays_unknown(self):
        run = self.roots['template-properties'] / 'properties-card'
        run.mkdir(parents=True)
        (run / 'prepared.json').write_text('{}', encoding='utf-8')
        old = json.loads(json.dumps(self.health))
        old['nativeMap']['tools'].remove('template-properties')
        with patch.object(client, 'send', return_value=old) as sender:
            with self.assertRaisesRegex(ValueError, 'CAPABILITY_OR_IDENTITY'):
                client.send_native_map('template-properties', run, queue_dir=self.queue)
        sender.assert_called_once_with({'kind': 'status'}, timeout=30.0)
        self.assertFalse((run / 'map-queue-claim.json').exists())
        pending = {'ok': False, 'pending': True, 'outcomeUncertain': True}
        with patch.object(client, 'send', side_effect=[self.health, pending]):
            first = client.send_native_map('template-properties', run, queue_dir=self.queue)
        with patch.object(client, 'send', side_effect=AssertionError('never resubmit')) as sender, \
                patch.object(client, 'poll_request', return_value=pending) as poll:
            second = client.send_native_map('template-properties', run, queue_dir=self.queue)
        sender.assert_not_called()
        self.assertEqual(first['queueRequestId'], second['queueRequestId'])
        self.assertTrue(second['outcomeUncertain'])
        poll.assert_called_once_with(first['queueRequestId'], 300.0)

    def test_template_properties_v1_card_cannot_enter_v2_dispatch(self):
        old_run = self.root / '.runtime/template-properties-20261017/prepared/v1-card'
        old_run.mkdir(parents=True)
        (old_run / 'prepared.json').write_text('{}', encoding='utf-8')
        request = dict(self.payload(), tool='template-properties', runPath=str(old_run))
        with self.assertRaisesRegex(ValueError, 'WRONG_TOOL_ROOT'):
            client.validate_native_map_request(request)
        with patch.object(client, 'send', side_effect=AssertionError('old ABI must never queue')):
            with self.assertRaisesRegex(ValueError, 'WRONG_TOOL_ROOT'):
                client.send_native_map('template-properties', old_run, queue_dir=self.queue)
        self.assertFalse((old_run / 'map-queue-claim.json').exists())


if __name__ == '__main__':
    unittest.main()
