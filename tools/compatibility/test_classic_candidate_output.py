"""Offline candidate isolation only; no game/editor/session calls."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('classic_candidate_under_test', ROOT / 'tools/editor-bridge/repair-classic-save.py')
classic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classic)


class CandidateOutputTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / '.runtime'
        self.runtime.mkdir()
        self.source = self.root / 'source.gil'
        self.blob = classic.codec.encode_container(classic.codec.Container(2, b''))
        self.source.write_bytes(self.blob)
        self.target = self.runtime / 'candidate.gil'
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(classic, 'ROOT', self.root))
        self.stack.enter_context(patch.object(subprocess, 'run', side_effect=AssertionError('LIVE PROCESS FORBIDDEN')))

    def invoke(self, target=None, source=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return classic.main([str(source or self.source), str(target or self.target)])

    def test_valid_container_creates_only_runtime_candidate(self):
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.target.read_bytes(), self.blob)
        self.assertEqual(self.source.read_bytes(), self.blob)

    def test_outside_and_formal_outputs_refuse_before_reading_source(self):
        missing = self.root / 'missing-source.gil'
        for target in [self.root/'outside.gil',
                       self.root/'AppData/LocalLow/miHoYo/Game/BeyondLocal/123/Beyond_Local_Save_Level/new.gil',
                       self.runtime/'../escaped.gil']:
            with self.subTest(target=target), self.assertRaises(SystemExit) as caught:
                self.invoke(target, missing)
            self.assertEqual(caught.exception.code, 2)
            self.assertFalse(target.exists())
        self.assertFalse((self.root/'AppData').exists())

    def test_existing_output_and_source_path_remain_untouched(self):
        self.target.write_bytes(b'existing-candidate')
        with self.assertRaises(SystemExit): self.invoke()
        self.assertEqual(self.target.read_bytes(), b'existing-candidate')
        with self.assertRaises(SystemExit): self.invoke(self.target, self.target)
        self.assertEqual(self.source.read_bytes(), self.blob)

    def test_concurrent_candidate_creation_is_not_overwritten(self):
        def repair(blob):
            self.target.write_bytes(b'concurrent-candidate')
            return blob, []
        with patch.object(classic, 'repair', side_effect=repair), self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.target.read_bytes(), b'concurrent-candidate')
        self.assertEqual(self.source.read_bytes(), self.blob)

    def test_runtime_directory_itself_is_not_an_output(self):
        with self.assertRaises(SystemExit) as caught: self.invoke(self.runtime)
        self.assertEqual(caught.exception.code, 2)
        self.assertTrue(self.runtime.is_dir())


if __name__ == '__main__':
    unittest.main()
