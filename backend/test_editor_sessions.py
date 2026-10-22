"""Request lifecycle checks with no game or helper execution."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch
from bridge import editor_sessions as s


class Sessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.rid = str(uuid.uuid4())
        self.proc = Mock(pid=888)
        self.proc.poll.return_value = None
        self.patches = [patch.object(s, 'REQUESTS_DIR', self.base/'requests'),
                        patch.object(s, 'RUNS_DIR', self.base/'runs'),
                        patch.object(s, '_live', {}),
                        patch.object(s.subprocess, 'Popen', return_value=self.proc)]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def test_same_id_never_launches_twice(self):
        self.assertTrue(s.start(self.rid, 10, 'observe')['spawned'])
        self.assertFalse(s.start(self.rid, 10, 'observe')['spawned'])
        self.assertEqual(s.subprocess.Popen.call_count, 1)
        with self.assertRaises(s.SessionError): s.start(self.rid, 10, 'restore-route')

    def test_invalid_parameters_have_no_effect(self):
        for rid,pid,action in [('bad',10,'observe'),(self.rid,True,'observe'),
                               (self.rid,'10','observe'),(self.rid,0,'observe'),
                               (self.rid,10,'arbitrary')]:
            with self.assertRaises(s.SessionError): s.start(rid,pid,action)
        s.subprocess.Popen.assert_not_called()
        self.assertFalse(s.REQUESTS_DIR.exists())

    def test_crash_before_metadata_does_not_retry(self):
        (s.REQUESTS_DIR/self.rid).mkdir(parents=True)
        self.assertEqual(s.start(self.rid,10,'observe')['lifecycle'], 'unknown')
        s.subprocess.Popen.assert_not_called()

    def test_failed_spawn_is_not_retried(self):
        s.subprocess.Popen.side_effect = OSError('test')
        with self.assertRaises(s.SessionError): s.start(self.rid,10,'observe')
        self.assertFalse(s.start(self.rid,10,'observe')['spawned'])
        self.assertEqual(s.subprocess.Popen.call_count, 1)

    def test_terminated_launcher_is_not_running(self):
        s.start(self.rid,10,'observe'); self.proc.poll.return_value=1
        self.assertEqual(s.status(self.rid)['lifecycle'], 'launcher-failed')
        self.assertFalse(s.status(self.rid)['processAlive'])

    def test_receipt_identity_and_result(self):
        s.start(self.rid,10,'observe')
        run=str(uuid.uuid4()); d=s.RUNS_DIR/run; d.mkdir(parents=True)
        (d/'session-launch.json').write_text('{}')
        out=s.REQUESTS_DIR/self.rid/'launcher-stdout.json'
        out.write_text(json.dumps({'runId':run,'targetPid':11,'action':'observe'}))
        self.assertIsNone(s.status(self.rid)['runId'])
        out.write_text(json.dumps({'runId':run,'targetPid':10,'action':'observe','nonce':'hidden'}))
        with patch.object(s,'_session_status',return_value={'status':'helper-running'}):
            reply=s.start(self.rid,10,'observe')
        self.assertEqual(reply['runId'],run)
        self.assertNotIn('nonce',json.dumps(reply))
        self.assertEqual(s.subprocess.Popen.call_count,1)


if __name__ == '__main__': unittest.main()
