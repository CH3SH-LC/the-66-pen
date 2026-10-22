"""Mock identity/compiler tests: no native function, probe, or helper is run."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tests'))
import prepare_item as prepare_api
from test_item_review import ReviewFixture


class PrepareItemTests(unittest.TestCase):
    def setUp(self):
        self.data = ReviewFixture()
        self.data.initialize(self)
        self.output = self.data.base / 'prepared-item'
        self.enterContext(patch.object(prepare_api, 'OUTPUT', self.output))
        record = prepare_api.requests.read_json(self.data.baseline / 'stdout.jsonl')
        raw = bytes.fromhex(record['snapshotHex'])
        profile = prepare_api.profiles.load_profile()
        self.inputs = {'requestPath': str(self.data.request_path), 'syntheticFixture': True,
                  'serviceProfilePath': str(self.data.service_path),
                  'serviceProfileSha256': self.data.review['transitiveCurrencyProfile']['sha256']}
        self.loader = self.enterContext(patch.object(prepare_api.candidate, 'load_inputs', return_value=(
            self.data.request, raw, self.data.runtime, profile, {'syntheticFixture': True}, self.inputs)))
        self.identity = self.enterContext(patch.object(prepare_api.profiles, 'validate_session', return_value=self.data.session))
        self.kernel = Mock()
        self.kernel.GetTickCount64.return_value = 1000
        self.user = Mock()
        self.user.RegisterWindowMessageW.return_value = 0xc456
        self.enterContext(patch.object(prepare_api.profiles, 'windows_api', return_value=(self.kernel, self.user)))
        self.compiler = self.enterContext(patch.object(prepare_api.candidate, 'compile_sources', side_effect=self.fake_compile))

    @staticmethod
    def fake_compile(run):
        for name in ('hook_receipt.dll', 'hook_receipt_probe.exe'):
            (run / name).write_bytes(b'UNIT TEST PLACEHOLDER: never executable')
        (run / 'build.log').write_text('Synthetic compiler fixture; no native build or execution.', encoding='utf-8')
        return 'synthetic compiler fixture'

    def test_bound_header_manifest_wrapper_and_full_raw_baseline(self):
        result = prepare_api.prepare(self.data.review_path)
        run = Path(result['run'])
        self.assertTrue(result['launchable'])
        self.assertFalse(result['probeExecuted'])
        self.assertFalse(result['nativeCalled'])
        header = (run / 'target_config.h').read_text()
        for text in ('#define HR_ACTION 6ULL', '#define HR_TARGET_PID 9ULL', '#define HR_TARGET_TID 8ULL',
                     '#define HR_TARGET_CREATION 6ULL', '#define HR_TARGET_THREAD_CREATION 5ULL',
                     '#define HR_DEADLINE 601000ULL', '#define HR_MESSAGE_ID 50262ULL',
                     '#define HR_NONCE ' + str(result['nonce']) + 'ULL', '#define TA_ITEM_REVIEWED 1'):
            self.assertIn(text, header)
        self.assertNotIn('compile-only-target.invalid', header)
        self.assertIn('\\xe5\\x86\\x9c', header)  # Chinese name retained as UTF-8 bytes.
        raw = bytes.fromhex(prepare_api.requests.read_json(self.data.baseline / 'stdout.jsonl')['snapshotHex'])
        self.assertEqual((run / 'baseline-snapshot.bin').read_bytes(), raw)
        for name, digest in result['hashes'].items():
            self.assertEqual(prepare_api.profiles.sha256(run / name), digest, name)
        self.assertEqual(self.identity.call_count, 2)
        self.compiler.assert_called_once()
        self.assertFalse((run / 'launch.claim').exists())
        self.assertFalse((run / 'stdout.jsonl').exists())
        self.assertFalse((run / 'exit.json').exists())
        wrapper = (run / result['wrapperName']).read_text(encoding='utf-8-sig')
        for marker in ('NOT_ELEVATED', 'CreateNew', 'ITEM_REVIEW_EXPIRED', 'ARTIFACT_CHANGED',
                       'REVIEW_INPUT_CHANGED', 'WRAPPER_CHANGED', 'CopyToAsync', 'CreateNoWindow = $true'):
            self.assertIn(marker, wrapper)
        for profile in (self.data.runtime_path, self.data.service_path):
            self.assertIn(prepare_api.ps_literal(profile), wrapper)
            self.assertIn(prepare_api.profiles.sha256(profile), wrapper)
        contract = prepare_api.requests.read_json(run / 'build-contract.json')
        self.assertEqual((contract['actionCode'], contract['receiptVersion'], contract['ttlSeconds']), (6, 10, 600))
        self.assertNotIn('invoke-fixed-probe', wrapper)
        self.assertNotIn('elevated-runner', wrapper)
        # Parse only: PowerShell never evaluates or launches this generated body.
        if os.name == 'nt':
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            command = '$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile(' + prepare_api.ps_literal(run / result['wrapperName']) + ',[ref]$tokens,[ref]$errors)>$null;if($errors.Count){$errors|Out-String;exit 2}'
            parsed = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                                    capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)

    def test_unreviewed_input_rejected_before_identity_or_build(self):
        self.data.review['state'] = 'unreviewed'; self.data.save()
        with self.assertRaisesRegex(ValueError, 'ITEM_COORDINATOR_REVIEW_REQUIRED'):
            prepare_api.prepare(self.data.review_path)
        self.identity.assert_not_called()
        self.compiler.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_build_failure_consumes_review_and_produces_no_launcher(self):
        self.compiler.side_effect = ValueError('synthetic build failure')
        with self.assertRaisesRegex(ValueError, 'synthetic build failure'):
            prepare_api.prepare(self.data.review_path)
        self.assertFalse(list(self.output.rglob('invoke-item-probe.ps1')))
        with self.assertRaisesRegex(ValueError, 'ITEM_REVIEW_ALREADY_CLAIMED'):
            prepare_api.prepare(self.data.review_path)
        self.assertEqual(self.compiler.call_count, 1)

    def test_revoked_review_or_expired_deadline_after_compile_never_gets_launcher(self):
        def revoked(run):
            result = self.fake_compile(run)
            self.data.review['state'] = 'unreviewed'; self.data.save()
            return result
        self.compiler.side_effect = revoked
        with self.assertRaisesRegex(ValueError, 'ITEM_COORDINATOR_REVIEW_REQUIRED'):
            prepare_api.prepare(self.data.review_path)
        self.assertFalse(list(self.output.rglob('invoke-item-probe.ps1')))

    def test_expired_native_deadline_after_compile_never_gets_launcher(self):
        self.kernel.GetTickCount64.side_effect = [1000, 601001]
        with self.assertRaisesRegex(ValueError, 'ITEM_BUILD_DEADLINE_EXPIRED'):
            prepare_api.prepare(self.data.review_path)
        self.assertFalse(list(self.output.rglob('invoke-item-probe.ps1')))

    def test_cli_has_no_execute_review_creation_or_old_action_argument(self):
        for forbidden in ('--execute', '--create-review', '--op', '--session', '--pid'):
            with self.subTest(forbidden=forbidden), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                prepare_api.main(['--review', str(self.data.review_path), forbidden])
        self.compiler.assert_not_called()

    def test_loaded_transitive_profile_mismatch_stops_before_identity_or_compiler(self):
        self.inputs['serviceProfileSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'VALIDATED_TRANSITIVE_PROFILE_CHANGED'):
            prepare_api.prepare(self.data.review_path)
        self.identity.assert_not_called()
        self.compiler.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_transitive_profile_changed_during_compilation_never_gets_launcher(self):
        def changed(run):
            result = self.fake_compile(run)
            self.data.service_path.write_bytes(self.data.service_path.read_bytes() + b' ')
            return result
        self.compiler.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'REVIEW_SOURCE_CHANGED_OR_INCOMPLETE'):
            prepare_api.prepare(self.data.review_path)
        self.assertFalse(list(self.output.rglob('invoke-item-probe.ps1')))


if __name__ == '__main__':
    unittest.main()
