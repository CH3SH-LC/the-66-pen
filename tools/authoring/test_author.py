import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import author

COMPATIBLE = {'ok': True, 'code': 'compatible', 'component': 'all'}


def refused(component='all'):
    return author.IncompatibleVersion({'ok': False, 'code': 'incompatible-version',
                                       'component': component, 'components': {},
                                       'reasons': ['game.timestamp: expected 1785321476, got 1788945104']})


class AuthorTests(unittest.TestCase):
    def setUp(self):
        # No test may reach the real installation: every guard call is mocked.
        self.gate = patch.object(author, 'require_compatible', return_value=COMPATIBLE)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def test_one_shot_cached_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            def backend(command):
                calls.append(command)
                return {'ok': True, 'nonce': 'do-not-log', 'entityId': 42}
            command = {'backend': 'scene', 'action': 'create', 'mutating': True, 'review': 'synthetic-review.json'}
            first = author.execute(command, 'same', journal=Path(folder), transport=backend)
            second = author.execute(command, 'same', journal=Path(folder), transport=backend)
            self.assertEqual(len(calls), 1)
            self.assertTrue(second['replayed'])
            self.assertNotIn('nonce', first['backend'])
            self.assertFalse(first['persistenceVerified'])
            with self.assertRaisesRegex(ValueError, 'CONFLICT'):
                author.execute(dict(command, action='save'), 'same', journal=Path(folder), transport=backend)

    def test_unknown_claim_does_not_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            command = {'backend': 'scene', 'mutating': True}
            directory = Path(folder) / 'lost'
            directory.mkdir()
            author.exclusive_json(directory / 'claim.json', {
                'sha256': author.hashlib.sha256(author.encoded(command).encode()).hexdigest()})
            with self.assertRaisesRegex(ValueError, 'OUTCOME_UNKNOWN'):
                author.execute(command, 'lost', journal=Path(folder), transport=lambda _: self.fail('dispatched'))

    def test_exception_no_retry_or_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            def failure(_):
                raise TimeoutError('secret nonce')
            result = author.execute({'mutating': True}, 'timeout', journal=Path(folder), transport=failure)
            self.assertTrue(result['outcomeUncertain'])
            self.assertNotIn('secret', author.encoded(result))

    def test_expired_and_closed_lease(self):
        with tempfile.TemporaryDirectory() as folder:
            run_id = str(author.uuid.uuid4())
            directory = Path(folder) / run_id
            directory.mkdir()
            settings = directory / 'bridge-settings.json'
            settings.write_text(author.encoded({'expiresUtc': (datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()}))
            with self.assertRaisesRegex(ValueError, 'EXPIRED'):
                author.lease(run_id, Path(folder))
            settings.write_text(author.encoded({'expiresUtc': (datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()}))
            self.assertEqual(author.lease(run_id, Path(folder)), directory)
            (directory / 'lease-closed.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'CLOSED'):
                author.lease(run_id, Path(folder))

    def test_graph_shape_and_node_count(self):
        argv = ['graph', 'add', '--request-id', 'x', '--run-id', str(author.uuid.uuid4()), '--name', 'MW_API_test',
                '--graph-id', '3', '--definition-id', '71', '--expected-node-count', '0']
        command = author.command_from_args(author.parser().parse_args(argv))
        self.assertEqual(command['payload']['action'], 'add-node')
        self.assertEqual(command['payload']['expectedNodeCount'], 0)
        argv[-1] = '128'
        with self.assertRaises(ValueError):
            author.command_from_args(author.parser().parse_args(argv))

    def test_scene_command_environment(self):
        command = dict(action='create', levelId=1073741834, templateId=20001034,
                       position=[0, 0, -2], rotation=[0, 0, 0], scale=[1, 1, 1])
        with patch.object(author, 'process_json', return_value={'ok': True}) as run:
            author.scene_call(command)
        args, kwargs = run.call_args
        self.assertEqual(kwargs['environment']['MILIASTRA_LEVEL'], '1073741834')
        self.assertIn('-2', args[0])
        self.assertTrue(args[0][1].endswith('scene_cli.py'))


class RejectedVersionTests(unittest.TestCase):
    """A rejected build must refuse before any side effect, but only for live work."""

    def test_rejected_version_leaves_no_journal_claim_or_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = []
            with patch.object(author, 'require_compatible', side_effect=refused('game')):
                result = author.execute({'backend': 'scene', 'action': 'create', 'mutating': True, 'review': 'synthetic-review.json'},
                                        'blocked', journal=Path(folder),
                                        transport=lambda command: calls.append(command))
            self.assertEqual(result['code'], 'incompatible-version')
            self.assertFalse(result['ok'])
            self.assertFalse(result['outcomeUncertain'])
            self.assertFalse(result['retryAttempted'])
            self.assertIsNone(result['journal'])
            self.assertEqual(calls, [])
            self.assertEqual(list(Path(folder).iterdir()), [])  # no journal directory at all

    def test_rejected_version_preserves_request_id_protection(self):
        with patch.object(author, 'require_compatible', side_effect=refused('all')):
            with self.assertRaises(ValueError):
                author.execute({'backend': 'scene'}, 'bad id!', journal=Path(tempfile.mkdtemp()))

    def test_component_selected_per_backend(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(author, 'require_compatible', return_value=COMPATIBLE) as gate:
                author.execute({'backend': 'scene', 'mutating': False}, 'scene-1',
                               journal=Path(folder), transport=lambda _: {'ok': True})
                author.execute({'backend': 'graph', 'mutating': False}, 'graph-1',
                               journal=Path(folder), transport=lambda _: {'ok': True})
            self.assertEqual([call.args[0] for call in gate.call_args_list], ['native-scene', 'editor'])

    def test_direct_dispatch_does_not_bypass_the_guard(self):
        with patch.object(author, 'require_compatible', side_effect=refused('game')):
            with patch.object(author, 'process_json') as process:
                with self.assertRaises(author.IncompatibleVersion):
                    author.scene_call({'action': 'create', 'templateId': 20001200, 'levelId': 1,
                                       'position': [0, 0, 0], 'rotation': [0, 0, 0], 'scale': [1, 1, 1]})
                process.assert_not_called()
        with patch.object(author, 'require_compatible', side_effect=refused('editor')):
            with patch.object(author, 'lease') as lease:
                with self.assertRaises(author.IncompatibleVersion):
                    author.graph_call({'runId': 'not-a-uuid', 'payload': {}}, 'rid', Path('nowhere'))
                lease.assert_not_called()

    def test_graph_cli_refuses_before_reading_lease(self):
        output = io.StringIO()
        argv = ['author.py', 'graph', 'catalog', '--request-id', 'rejected-graph',
                '--run-id', str(author.uuid.uuid4())]
        with patch.object(author, 'require_compatible', side_effect=refused('editor')), \
             patch.object(author, 'lease', side_effect=AssertionError('lease touched')) as lease, \
             patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
            self.assertEqual(author.main(), 2)
            lease.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['code'], 'incompatible-version')

    def test_local_capabilities_and_status_stay_available(self):
        with patch.object(author, 'require_compatible', side_effect=refused('all')) as gate:
            for command in ('capabilities', 'status'):
                stream = io.StringIO()
                with patch.object(sys, 'argv', ['author.py', command]), contextlib.redirect_stdout(stream):
                    self.assertEqual(author.main(), 0)
                payload = json.loads(stream.getvalue())
                self.assertTrue(payload['ok'])
                self.assertIn('sceneBackend', payload)
            gate.assert_not_called()  # local reads never touch the live gate
        self.assertFalse(author.capabilities()['officialPlaytestVerified'])


if __name__ == '__main__':
    unittest.main()
