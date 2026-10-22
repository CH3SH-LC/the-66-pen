import sys
import json
from contextlib import ExitStack
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_reopen_prerequisites as check

class PreflightTests(unittest.TestCase):
    def test_pending_does_not_analyze_or_repeat(self):
        with patch.object(check, 'analyze_run') as analyze:
            result = check.response_report({'pending': True, 'requestId': 'a' * 32})
        analyze.assert_not_called()
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(result['requestId'], 'a' * 32)
        self.assertFalse(result['retryAttempted'])

    def test_missing_run_is_unavailable_not_success(self):
        result = check.response_report({'ok': True})
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(result['preflightPassed'])

    def test_business_failure_cannot_be_upgraded(self):
        with patch.object(check, 'analyze_run', return_value={'preflightPassed': True}):
            result = check.response_report({'run': 'fixture', 'ok': False})
        self.assertFalse(result['preflightPassed'])

    def test_uncertain_reply_cannot_be_upgraded(self):
        with patch.object(check, 'analyze_run', return_value={'preflightPassed': True}):
            result = check.response_report(dict(run='fixture', ok=True, action='inspect',
                levelId=check.baseline.LEVEL, cleanupVerified=True, outcomeUncertain=True))
        self.assertFalse(result['preflightPassed'])

    def test_wrong_action_or_level_refuses(self):
        for action, level in [('save', check.baseline.LEVEL), ('inspect', 1)]:
            with self.subTest(action=action, level=level):
                with patch.object(check, 'analyze_run', return_value={'preflightPassed': True}):
                    result = check.response_report(dict(run='fixture', ok=True,
                        action=action, levelId=level, cleanupVerified=True))
                self.assertFalse(result['preflightPassed'])

    def test_pending_business_ownership_is_not_ready(self):
        with patch.object(check, 'analyze_run', return_value={'preflightPassed': True}):
            result = check.response_report(dict(run='fixture', ok=True, action='inspect',
                levelId=check.baseline.LEVEL, cleanupVerified=True,
                observedDuringReopenRequestId='a' * 32))
        self.assertFalse(result['preflightPassed'])
        self.assertEqual(result['status'], 'blocked')

    def test_ready_is_still_not_reopen(self):
        with patch.object(check, 'analyze_run', return_value={
                'preflightPassed': True, 'reopenInvoked': False, 'reopenVerified': False}):
            result = check.response_report(dict(run='fixture', ok=True, action='inspect',
                levelId=check.baseline.LEVEL, cleanupVerified=True))
        self.assertTrue(result['preflightPassed'])
        self.assertFalse(result['reopenInvoked'])
        self.assertFalse(result['reopenVerified'])

    def test_nonobject_response_rejected(self):
        with self.assertRaisesRegex(ValueError, 'NOT_OBJECT'):
            check.response_report('ok')

    def test_report_never_overwrites_old_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'report.json'
            check.put(target, {'original': True})
            before = target.read_bytes()
            with self.assertRaises(FileExistsError):
                check.put(target, {'original': False})
            self.assertEqual(target.read_bytes(), before)

class AnalyzeOwnershipTests(unittest.TestCase):
    """Real temporary evidence/lease paths; OS and game reads remain mocked."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.run = self.root / 'run'
        self.run.mkdir()
        self.session = {'pid': 123, 'tid': 456}
        documents = {'prepared.json': {'session': self.session}, 'build-result.json': {},
                     'exit.json': {'executed': True}, 'stdout.jsonl': {'synthetic': True}}
        for name, value in documents.items():
            (self.run / name).write_text(json.dumps(value), encoding='utf-8')
        self.record = dict(scope='READ_ONLY_CONTEXT_RECEIPT', selfTestOnly=False,
                           pid=123, tid=456, unhooked=True, activeCallbacks=0,
                           callbackCount=1, transportOk=True)
        self.context = {'entities': [1], 'levelObservation': {'verified': True}}
        decoder = SimpleNamespace(read_probe=lambda path: (self.record, 'utf-8'),
                                  decode_snapshot=lambda record: self.context)
        self.stack.enter_context(patch.object(check, 'ROOT', self.root))
        self.stack.enter_context(patch.object(check.reviews, 'project_evidence', side_effect=lambda path: Path(path)))
        self.stack.enter_context(patch.object(check.readonly, 'load_decoder', return_value=decoder))
        self.stack.enter_context(patch.object(check.scheduler, 'diagnose_prerequisites', return_value={'synthetic': True}))
        self.bindings = self.stack.enter_context(patch.object(check.baseline, 'validate_file_bindings'))
        self.identity = self.stack.enter_context(patch.object(check.profiles, 'validate_session'))
        self.fresh_baseline = self.stack.enter_context(patch.object(check.baseline, 'load'))
        self.pending = self.root / '.runtime/editor-bridge/native-dispatch/native-active.json'

    def test_analyze_without_pending_still_requires_identity_and_fresh_baseline(self):
        result = check.analyze_run(self.run)
        self.assertTrue(result['preflightPassed'])
        self.assertFalse(result['pendingReopenOwnership'])
        self.identity.assert_called_once_with(self.session)
        self.fresh_baseline.assert_called_once_with(self.run, self.session)
        self.bindings.assert_called_once()
        self.assertFalse(result['reopenVerified'])

    def test_any_existing_active_lease_blocks_even_if_unreadable_as_json(self):
        self.pending.parent.mkdir(parents=True)
        for payload in ('', '{malformed', '{"action":"inspect"}', '{"action":"reopen-current"}'):
            with self.subTest(payload=payload):
                self.pending.write_text(payload, encoding='utf-8')
                result = check.analyze_run(self.run)
                self.assertEqual(result['status'], 'blocked')
                self.assertFalse(result['preflightPassed'])
                self.assertTrue(result['pendingReopenOwnership'])
                self.assertTrue(result['nativeReadObserved'])
                self.assertTrue(result['hookCleanupVerified'])

    def test_old_or_rejected_baseline_never_reports_ready(self):
        self.fresh_baseline.side_effect = ValueError('REOPEN_BASELINE_EXPIRED')
        result = check.analyze_run(self.run)
        self.assertFalse(result['preflightPassed'])
        self.assertEqual(result['currentEligibilityError'], 'REOPEN_BASELINE_EXPIRED')
        self.assertEqual(result['diagnostic'], {'synthetic': True})

    def test_source_binding_failure_cannot_be_overridden_by_other_valid_evidence(self):
        self.bindings.side_effect = ValueError('REOPEN_ARTIFACT_CHANGED:prepared.json')
        result = check.analyze_run(self.run)
        self.assertFalse(result['preflightPassed'])
        self.assertIn('REOPEN_ARTIFACT_CHANGED', result['currentSourceBindingError'])

    def test_identity_failure_does_not_load_a_baseline_or_report_ready(self):
        self.identity.side_effect = ValueError('SESSION_CHANGED:processCreation')
        result = check.analyze_run(self.run)
        self.assertFalse(result['preflightPassed'])
        self.fresh_baseline.assert_not_called()
        self.assertIn('SESSION_CHANGED', result['currentEligibilityError'])

    def test_missing_hook_cleanup_cannot_be_overridden_by_freshness(self):
        self.record['unhooked'] = False
        result = check.analyze_run(self.run)
        self.assertFalse(result['preflightPassed'])
        self.assertFalse(result['hookCleanupVerified'])

    def test_pending_reply_key_presence_blocks_even_with_falsey_values(self):
        for value in (None, '', False, 0):
            with self.subTest(value=value), patch.object(check, 'analyze_run', return_value={'preflightPassed': True}):
                result = check.response_report(dict(run='fixture', ok=True, action='inspect',
                    levelId=check.baseline.LEVEL, cleanupVerified=True,
                    observedDuringReopenRequestId=value))
                self.assertFalse(result['preflightPassed'])
                self.assertEqual(result['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
