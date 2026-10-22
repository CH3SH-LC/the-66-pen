"""Only synthetic prepared actions and PowerShell parsing; never elevate/execute."""
from pathlib import Path
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tests'))
import bundle_prepared as bundle_api
import test_prepare_binding as binding_fixtures

prepare_api = binding_fixtures.prepare_api


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = binding_fixtures.BindingPreparationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.mocks()
        self.result = prepare_api.prepare(self.fixture.data.review_path)
        self.run = Path(self.result['run'])
        self.enterContext(patch.object(bundle_api, 'OUTPUT', self.fixture.data.base / 'batches'))

    def test_single_action_bundle_keeps_rows_nested_and_script_parses(self):
        result = bundle_api.bundle([self.run])
        self.assertFalse(result['executed'] or result['elevationRequested'])
        self.assertEqual(len(result['actions']), 1)
        script = Path(result['run']) / result['wrapper']
        self.assertEqual(bundle_api.profiles.sha256(script), result['wrapperSha256'])
        text = script.read_text(encoding='utf-8-sig')
        self.assertIn("System.Collections.Generic.List[object]", text)
        self.assertEqual(text.count('$taskRows.Add(@('), 1)
        self.assertIn('-WindowStyle Hidden -Wait -PassThru', text)
        self.assertIn('BATCH_ACTION_FAILED_NO_RETRY', text)
        self.assertNotIn('-Verb RunAs', text)
        self.assertFalse((self.run / 'launch.claim').exists())
        if os.name == 'nt':
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            command = '$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile(' + prepare_api.ps_literal(script) + ',[ref]$tokens,[ref]$errors)>$null;if($errors.Count){$errors|Out-String;exit 2}'
            parsed = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)

    def test_duplicate_or_previously_attempted_action_rejected(self):
        with self.assertRaisesRegex(ValueError, 'BATCH_DUPLICATE_ACTION'):
            bundle_api.bundle([self.run, self.run])
        (self.run / 'launch.claim').write_bytes(b'synthetic prior attempt')
        with self.assertRaisesRegex(ValueError, 'BATCH_ACTION_ALREADY_ATTEMPTED'):
            bundle_api.bundle([self.run])

    def test_compile_only_and_changed_wrapper_rejected(self):
        build = self.run / 'build-result.json'
        original = build.read_bytes()
        result = bundle_api.requests.read_json(build)
        result['compileOnly'] = True
        self.fixture.data.write(build, result)
        with self.assertRaisesRegex(ValueError, 'BATCH_REVIEWED_BUILD_REQUIRED'):
            bundle_api.bundle([self.run])
        build.write_bytes(original)
        (self.run / self.result['wrapperName']).write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'BATCH_ARTIFACT_CHANGED'):
            bundle_api.bundle([self.run])


if __name__ == '__main__':
    unittest.main()
