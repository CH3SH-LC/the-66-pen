"""Isolated tests for the legacy CLI success semantics and the CRUD gate.

Everything here is synthetic. ``send`` and ``subprocess.run`` are mocked, only
temporary directories are used, and no test starts a game or editor, requests
UAC, reads or writes a queue directory, touches the live session pointer, runs a
child process or opens a formal save. Importing the modules under test must not
run anything or reconfigure the unittest stdout.

Covered refusals:
  * ``elevated-request.py load`` needs ``accepted`` to be literal ``true`` and
    ``call`` needs ``ok`` to be literal ``true``; raw, absent, false, non-boolean
    and string replies all exit non-zero.
  * ``fs`` replies have no ``ok`` field in elevated-fs-ops.ps1, so absence is not
    treated as failure -- but an explicit non-true ``ok`` is obeyed.
  * ``run_live_crud_acceptance.py`` requires explicit positive ``--editor-pid``
    and ``--level-id`` with explicit phase/session/review, propagates the level to every child as ``MILIASTRA_LEVEL``,
    compares saved snapshots under that exact level key, refuses a receipt that
    names another level, and checks the compatibility guard before it creates a
    run directory, reads the session pointer or dispatches anything.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / 'tools/editor-bridge/elevated-request.py'
CRUD = ROOT / 'tools/game-executor/run_live_crud_acceptance.py'

RUN_ID = '0c8a176d-546d-4480-85fb-c66ea9851b27'
# Deliberately synthetic: neither the retired hardcoded editor PID nor the
# retired hardcoded GIL level, so a regression to either constant fails here.
EDITOR_PID = 40000
LEVEL = 1073741999
ENTITY_ID = 600


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ImportSpy(io.StringIO):
    """A stdout stand-in that records reconfigure calls."""

    def __init__(self):
        super().__init__()
        self.reconfigures = []

    def reconfigure(self, *args, **kwargs):
        self.reconfigures.append((args, kwargs))


class ImportSafetyTests(unittest.TestCase):
    def test_import_runs_nothing_and_leaves_stdout_alone(self):
        out, err = _ImportSpy(), _ImportSpy()
        with patch.object(sys, 'stdout', out), patch.object(sys, 'stderr', err), \
                patch.object(subprocess, 'run', side_effect=AssertionError('child process at import')):
            client = load_module('elevated_request_import_probe', CLIENT)
            crud = load_module('crud_import_probe', CRUD)
        self.assertEqual(out.reconfigures, [])
        self.assertEqual(err.reconfigures, [])
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue(), '')
        self.assertTrue(callable(client.main))
        self.assertTrue(callable(crud.main))
        self.assertNotEqual(LEVEL, 1073741832)


class ElevatedRequestDecisionTests(unittest.TestCase):
    """Exit codes follow literal success, never the mere presence of a reply."""

    @classmethod
    def setUpClass(cls):
        cls.client = load_module('elevated_request_under_test', CLIENT)

    def _run(self, argv, reply):
        stream = io.StringIO()
        with patch.object(self.client, 'send', return_value=reply) as send, \
                patch.object(sys, 'argv', ['elevated-request.py', *argv]), \
                contextlib.redirect_stdout(stream):
            code = self.client.main()
        return code, stream.getvalue(), send

    def test_read_only_status_reply_stays_success(self):
        code, text, _ = self._run(['status'], {'kind': 'status', 'elevated': True})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)['kind'], 'status')

    def test_load_requires_literal_true_accepted(self):
        code, _, send = self._run(['load', '--target-pid', str(EDITOR_PID)],
                                  {'kind': 'load', 'runId': RUN_ID, 'accepted': True})
        self.assertEqual(code, 0)
        send.assert_called_once_with({'kind': 'load', 'targetPid': EDITOR_PID})
        failures = ({'kind': 'load', 'runId': RUN_ID, 'accepted': value}
                    for value in (False, 'true', 'false', 0, 1, None))
        for reply in list(failures) + [{'kind': 'load', 'runId': RUN_ID}, {'raw': 'not json'}]:
            with self.subTest(reply=reply):
                code, text, _ = self._run(['load', '--target-pid', str(EDITOR_PID)], reply)
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(text), reply)

    def test_call_requires_literal_true_ok(self):
        base = ['call', '--op', 'inspect-entity-crud-probe', '--run-id', RUN_ID]
        code, _, send = self._run(base, {'ok': True, 'status': 'read'})
        self.assertEqual(code, 0)
        # ``call`` gained a ``--request-id`` flag; when it is absent the id is the
        # send default (None), so the dispatch identity is unchanged.
        send.assert_called_once_with({'kind': 'call', 'runId': RUN_ID, 'op': 'inspect-entity-crud-probe'},
                                     timeout=300.0, request_id=None)
        for reply in ({'ok': False}, {'ok': 'false'}, {'ok': 'true'}, {'ok': 1}, {'ok': 0},
                      {'status': 'read'}, {'raw': 'oops'}):
            with self.subTest(reply=reply):
                code, _, _ = self._run(base, reply)
                self.assertEqual(code, 1)

    def test_fs_obeys_an_explicit_ok_and_tolerates_its_absence(self):
        argv = ['fs', '--op', 'list', '--path', 'D:\\synthetic']
        # elevated-fs-ops.ps1 returns no ok field; failures arrive as runner errors.
        code, _, _ = self._run(argv, {'op': 'list', 'path': 'D:\\synthetic', 'count': 0, 'entries': []})
        self.assertEqual(code, 0)
        for reply in ({'op': 'list', 'ok': False, 'error': 'synthetic'},
                      {'op': 'list', 'ok': 'true'}, {'op': 'list', 'ok': 0}):
            with self.subTest(reply=reply):
                code, _, _ = self._run(argv, reply)
                self.assertEqual(code, 1)

    def test_failed_or_malformed_fs_reply_never_writes_output(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(self.client, 'ROOT', Path(folder)):
            out = Path(folder) / '.runtime' / 'outputs' / 'must-not-exist.bin'
            out.parent.mkdir(parents=True)
            for reply in ({'op': 'read', 'ok': False, 'data': ''}, {'raw': 'oops'}, [], None):
                with self.subTest(reply=reply):
                    code, _, _ = self._run(['fs', '--op', 'read', '--path', 'D:\\synthetic', '--out', str(out)], reply)
                    self.assertEqual(code, 1)
                    self.assertFalse(out.exists())

    def test_fs_read_still_writes_the_requested_payload(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(self.client, 'ROOT', Path(folder)):
            out = Path(folder) / '.runtime' / 'outputs' / 'copy.bin'
            out.parent.mkdir(parents=True)
            reply = {'op': 'read', 'encoding': 'base64',
                     'data': base64.b64encode(b'synthetic bytes').decode('ascii')}
            code, _, _ = self._run(['fs', '--op', 'read', '--path', 'D:\\synthetic', '--out', str(out)], reply)
            self.assertEqual(code, 0)
            self.assertEqual(out.read_bytes(), b'synthetic bytes')


class CrudAcceptanceTests(unittest.TestCase):
    """The original CLI gates, now using the isolated six-phase fixture.

    Composition intentionally avoids inheriting/re-running the dedicated phase
    test class. Every external call remains blocked by that fixture, while these
    tests retain the legacy explicit-input, exact-level and literal-success gates.
    """

    def setUp(self):
        phase_tests = load_module('legacy_crud_phase_fixture',
                                 ROOT / 'tools/game-executor/test_crud_phases.py')
        # Keep the historical regression values different from the dedicated
        # suite, so neither test silently accepts a hardcoded target.
        phase_tests.EDITOR = EDITOR_PID
        phase_tests.LEVEL = LEVEL
        phase_tests.ENTITY = ENTITY_ID
        self.fixture = phase_tests.StagedCrudTests(methodName='runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.crud = phase_tests.crud

    def test_explicit_values_reach_children_and_readback_uses_the_level(self):
        fixture = self.fixture
        fixture.advance('verify')
        state = json.loads((fixture.run / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual(state['levelId'], LEVEL)
        self.assertEqual(state['editorPid'], EDITOR_PID)
        self.assertEqual(len(fixture.review_calls), 3)
        # The fixture independently asserts MILIASTRA_LEVEL on EVERY child.
        self.assertTrue(fixture.calls)
        for call in fixture.calls:
            argv = call['argv']
            self.assertNotIn('38240', argv)
            self.assertNotIn('1073741832', argv)
            if call['label'] in ('create', 'save-renamed', 'save-deleted'):
                self.assertEqual(argv[argv.index('--level-id') + 1], str(LEVEL))
                self.assertEqual(argv[argv.index('--session') + 1], str(fixture.session_path))
                self.assertTrue(Path(argv[argv.index('--review') + 1]).is_file())
            if '--run-id' in argv:
                self.assertEqual(argv[argv.index('--run-id') + 1], fixture.scope)
        load = next(c['argv'] for c in fixture.calls if c['label'] == 'load-editor')
        self.assertEqual(load[load.index('--target-pid') + 1], str(EDITOR_PID))
        # Exact-level receipts are bound to the corresponding save verification.
        results = {phase: json.loads((fixture.run / 'phases' / (phase + '.result.json')).read_text(
                   encoding='utf-8')) for phase in ('start', 'save-renamed', 'save-deleted')}
        snapshots = [results['start']['evidence']['beforeGil']['snapshot'],
                     results['save-renamed']['evidence']['gil']['snapshot'],
                     results['save-deleted']['evidence']['gil']['snapshot']]
        verify = next(c['argv'] for c in fixture.calls if c['label'] == 'verify-crud-saves')
        self.assertEqual(verify[2:5], snapshots)
        self.assertEqual(verify[verify.index('--entity-id') + 1], str(ENTITY_ID))
        self.assertEqual(fixture.effects.count('stop-owned-editor-scope'), 1)
        self.assertEqual([c.args[0] for c in fixture.guard.call_args_list],
                         ['native-scene', 'editor'] * 6)

    def test_gate_failure_refuses_before_run_queue_or_dispatch(self):
        fixture = self.fixture
        with tempfile.TemporaryDirectory() as folder:
            bare = Path(folder)
            report = {'ok': False, 'code': 'incompatible-version', 'component': 'native-scene',
                      'reasons': ['synthetic updated build']}
            argv = ['--phase', 'start', '--run', '--run-dir', str(bare / '.runtime/crud'),
                    '--session', str(bare / 'absent-session.json'),
                    '--review', str(bare / 'absent-review.json'),
                    '--editor-pid', str(EDITOR_PID), '--level-id', str(LEVEL)]
            stream = io.StringIO()
            with patch.object(self.crud, 'ROOT', bare), \
                    patch.object(self.crud, 'require_compatible', side_effect=self.crud.IncompatibleVersion(report)), \
                    patch.object(self.crud, 'load_session', side_effect=AssertionError('session before guard')) as session, \
                    patch.object(self.crud, 'read_queue_pointer', side_effect=AssertionError('queue before guard')) as queue, \
                    contextlib.redirect_stdout(stream):
                code = self.crud.main(argv)
            payload = json.loads(stream.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload['guard'], report)
            self.assertFalse(payload['ok'])
            self.assertFalse(payload['outcomeUncertain'])
            session.assert_not_called()
            queue.assert_not_called()
            self.assertEqual(fixture.calls, [])
            self.assertEqual(list(bare.rglob('*')), [])

    def test_create_receipt_naming_another_level_is_rejected(self):
        fixture = self.fixture
        fixture.faults['create'] = lambda reply: dict(reply, levelId=LEVEL + 1)
        code, payload = fixture.invoke('start')
        self.assertEqual(code, 1)
        self.assertFalse(payload['ok'])
        self.assertIn('levelId', payload['result']['error'])
        self.assertIn(str(LEVEL), payload['result']['error'])
        self.assertTrue(payload['result']['outcomeUncertain'])
        self.assertFalse((fixture.run / 'probe.json').exists())
        self.assertNotIn('rename-entity-crud-probe', fixture.effects)

    def test_snapshot_for_another_level_is_never_used(self):
        fixture = self.fixture
        def wrong_snapshot(reply):
            return dict(reply, beforeGils={str(LEVEL + 1): reply['beforeGils'][str(LEVEL)]})
        fixture.faults['create'] = wrong_snapshot
        code, payload = fixture.invoke('start')
        self.assertEqual(code, 1)
        self.assertFalse(payload['ok'])
        self.assertIn('level', payload['result']['error'])
        self.assertTrue(payload['result']['outcomeUncertain'])
        # The new contract preserves an uncertain scope until natural expiry;
        # it does not claim cleanup, reconnect, retry or dispatch another write.
        before = len(fixture.calls)
        self.assertEqual(fixture.invoke('rename')[0], 2)
        self.assertEqual(len(fixture.calls), before)
        self.assertNotIn('stop-owned-editor-scope', fixture.effects)
        self.assertNotIn('save-renamed', fixture.effects)
        self.assertTrue((fixture.run / 'scope.json').is_file())

    def test_load_that_is_not_literally_accepted_is_rejected(self):
        fixture = self.fixture
        fixture.faults['load-editor'] = lambda reply: dict(reply, accepted='false')
        code, payload = fixture.invoke('start')
        self.assertEqual(code, 1)
        self.assertFalse(payload['ok'])
        self.assertIn('accepted', payload['result']['error'])
        self.assertEqual([c for c in fixture.calls if '--op' in c['argv']], [])
        self.assertNotIn('create', fixture.effects)

    def test_legacy_or_incomplete_staged_cli_refuses_before_dispatch(self):
        fixture = self.fixture
        base = ['--phase', 'start', '--run', '--run-dir', str(fixture.run),
                '--session', str(fixture.session_path), '--review', str(fixture.root / 'unused-review.json'),
                '--editor-pid', str(EDITOR_PID), '--level-id', str(LEVEL)]
        cases = [['--run', '--editor-pid', str(EDITOR_PID), '--level-id', str(LEVEL)]]
        for flag in ('--session', '--phase', '--review'):
            args = list(base)
            index = args.index(flag)
            del args[index:index + 2]
            cases.append(args)
        for flag, value in (('--editor-pid', '0'), ('--level-id', '0'), ('--level-id', str(2 ** 32))):
            args = list(base)
            args[args.index(flag) + 1] = value
            cases.append(args)
        for argv in cases:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as caught:
                self.crud.main(argv)
            self.assertEqual(caught.exception.code, 2)
        self.assertFalse(fixture.run.exists())
        self.assertEqual(fixture.calls, [])
        fixture.guard.assert_not_called()


if __name__ == '__main__':
    unittest.main()
