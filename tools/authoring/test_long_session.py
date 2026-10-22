"""Long-helper routing tests; all process and queue dispatches are isolated."""
import contextlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import author
from native_profiles import ProfileError


class LongSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = self.root / '.runtime/editor-bridge/owned'
        self.queue.mkdir(parents=True)
        self.directory = self.root / '.runtime/authoring/requests/one'
        self.directory.mkdir(parents=True)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(author, 'ROOT', self.root))
        self.stack.enter_context(patch.object(author, 'require_compatible', return_value={'ok': True}))
        self.lease = self.stack.enter_context(patch.object(author, 'lease', return_value=self.root))
        # The host policy is tested separately; long-session routing never launches it.
        self.host = self.stack.enter_context(patch.object(author, 'powershell_host', return_value={
            'path': str(self.root / 'fake-host/pwsh.exe'), 'policy': 'RemoteSigned',
            'policyOverride': False, 'fallbackAttempted': False}))
        self.child = self.stack.enter_context(patch.object(author, 'process_json', side_effect=AssertionError('unexpected subprocess')))
        self.send = Mock(return_value={'ok': True, 'phase': 'observed'})
        client = types.SimpleNamespace(send=self.send)
        spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda _: None))
        self.stack.enter_context(patch.object(author.importlib.util, 'spec_from_file_location', return_value=spec))
        self.stack.enter_context(patch.object(author.importlib.util, 'module_from_spec', return_value=client))
        self.command = {'backend': 'graph', 'runId': '12345678-1234-1234-1234-123456789abc',
                        'payload': {'action': 'inspect', 'name': 'MW_API_test', 'graphId': 7},
                        'mutating': False, 'elevatedQueue': str(self.queue)}

    def test_host_policy_refusal_precedes_lease_request_and_send(self):
        self.host.side_effect = ProfileError('NATIVE_POWERSHELL_HOST_POLICY_REFUSED:Restricted')
        with patch.object(author, 'exclusive_json', wraps=author.exclusive_json) as request_write:
            with self.assertRaisesRegex(ProfileError, 'NATIVE_POWERSHELL_HOST_POLICY_REFUSED:Restricted'):
                author.graph_call(self.command, 'one', self.directory)
            request_write.assert_not_called()
        self.host.assert_called_once_with()
        self.lease.assert_not_called()
        self.child.assert_not_called()
        self.send.assert_not_called()
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_queue_is_bound_to_scene_command(self):
        a=author.parser().parse_args(['--elevated-queue', str(self.queue), 'entity-inspect', '--request-id', 'x', '--level-id', '1'])
        self.assertEqual(author.command_from_args(a)['elevatedQueue'], str(self.queue.resolve()))

    def test_queue_is_bound_to_graph_command(self):
        a=author.parser().parse_args(['--elevated-queue', str(self.queue), 'graph', 'catalog', '--request-id', 'x', '--run-id', self.command['runId']])
        self.assertEqual(author.command_from_args(a)['elevatedQueue'], str(self.queue.resolve()))

    def test_scene_explicit_queue_forwarding(self):
        self.child.side_effect=None; self.child.return_value={'ok':True}
        author.scene_call({'action':'inspect','levelId':1,'elevatedQueue':str(self.queue)})
        argv=self.child.call_args.args[0]
        self.assertEqual(argv[argv.index('--elevated-queue')+1],str(self.queue))

    def test_graph_only_sends_identifiers_and_records_queue_id(self):
        result=author.graph_call(self.command,'one',self.directory)
        payload=self.send.call_args.args[0]
        self.assertEqual(payload,{'kind':'author-graph','runId':self.command['runId'],'requestId':'one'})
        queued=self.send.call_args.kwargs['request_id']
        self.assertRegex(queued,r'^[0-9a-f]{32}$')
        record=json.loads((self.directory/'helper-request.json').read_text())
        self.assertEqual(record['queueRequestId'],queued)
        self.assertEqual(result['queueRequestId'],queued)
        self.child.assert_not_called()

    def test_pending_is_preserved_without_second_dispatch(self):
        self.send.return_value={'ok':False,'pending':True,'outcomeUncertain':True,'retryAttempted':False}
        journal=self.root/'.runtime/other-journal'
        first=author.execute(self.command,'pending',journal=journal)
        second=author.execute(self.command,'pending',journal=journal)
        self.assertFalse(first['ok']); self.assertTrue(first['backend']['pending'])
        self.assertEqual(second['backend']['queueRequestId'],first['backend']['queueRequestId'])
        self.assertTrue(second['replayed']); self.assertEqual(self.send.call_count,1)

    def test_queue_change_is_request_conflict(self):
        journal=self.root/'.runtime/other-journal'
        author.execute(self.command,'same',journal=journal)
        other=self.queue.parent/'other'; other.mkdir()
        with self.assertRaisesRegex(ValueError,'REQUEST_ID_CONFLICT'):
            author.execute(dict(self.command,elevatedQueue=str(other)),'same',journal=journal)
        self.assertEqual(self.send.call_count,1)

    def test_runner_failure_does_not_escape_or_claim_no_effect(self):
        self.send.side_effect=SystemExit('runner error: test')
        result=author.graph_call(self.command,'one',self.directory)
        self.assertFalse(result['ok']); self.assertTrue(result['outcomeUncertain'])
        self.assertEqual(self.send.call_count,1)

    def test_queue_outside_project_rejected(self):
        with self.assertRaisesRegex(ValueError,'ELEVATED_QUEUE'):
            author.normalized_queue(self.root)
        self.send.assert_not_called()

    def test_existing_dispatch_record_prevents_second_send(self):
        author.graph_call(self.command,'one',self.directory)
        with self.assertRaises(FileExistsError):author.graph_call(self.command,'one',self.directory)
        self.assertEqual(self.send.call_count,1)

if __name__=='__main__':unittest.main()
