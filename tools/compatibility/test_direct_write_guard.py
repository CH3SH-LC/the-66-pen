"""Extra direct-writer refusals; synthetic temporary files only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools/editor-bridge'/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

static=load('direct_static_guard_test','apply-newdemo-static-save.py')
position=load('direct_position_guard_test','repair-mvp-position.py')

def rejected():
    return static.IncompatibleVersion({'ok':False,'code':'incompatible-version','reasons':['synthetic updated build']})

class DirectWriterTests(unittest.TestCase):
    def test_static_apply_refuses_before_save_access(self):
        stream=io.StringIO()
        with patch.object(static,'require_compatible',side_effect=rejected()), \
             patch.object(sys,'argv',['entry','nonexistent.gil','--apply']), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('save read')), \
             contextlib.redirect_stdout(stream):
            self.assertEqual(static.main(),2)
        self.assertEqual(json.loads(stream.getvalue())['code'],'incompatible-version')

    def test_position_apply_direct_library_refuses_before_verify_or_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(position,'require_compatible',side_effect=rejected()), \
                 patch.object(position,'verify_run',side_effect=AssertionError('verify touched')) as verify:
                with self.assertRaises(static.IncompatibleVersion):position.apply_run(root,True)
                verify.assert_not_called()
            self.assertEqual(list(root.iterdir()),[])

    def test_position_checks_again_before_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'evidence';out.mkdir();live=root/'live.gil';live.write_bytes(b'old')
            with patch.object(position,'LIVE',live), \
                 patch.object(position,'verify_run',return_value=({},b'old',b'new')), \
                 patch.object(position,'require_compatible',side_effect=[{},{},rejected()]) as gate:
                with self.assertRaises(static.IncompatibleVersion):position.apply_run(out,True)
            self.assertEqual(gate.call_count,3)
            self.assertEqual(live.read_bytes(),b'old')
            self.assertEqual(list(root.glob('*.tmp')),[])
            self.assertTrue((out/'apply-attempt.json').exists())

    def test_static_dry_run_available_and_replace_rechecked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);live=root/'1073741831.gil';live.write_bytes(b'old')
            source=root/'baseline.gil';source.write_bytes(b'baseline')
            (root/'newdemo-static-final-candidate.gil').write_bytes(b'candidate')
            for applying in (False,True):
                with self.subTest(applying=applying):
                    stream=io.StringIO()
                    argv=['entry',str(live)]+(['--apply'] if applying else [])
                    gate_effect=[{},{},{},rejected()] if applying else rejected()
                    with patch.object(static,'require_compatible',side_effect=gate_effect) as gate, \
                         patch.object(static.builder,'SOURCE',source),patch.object(static.builder,'OUT',root), \
                         patch.object(static.builder,'parse_gi_file',return_value=SimpleNamespace(level_name='newdemo',node_graph_count=3)), \
                         patch.object(static,'merge',return_value=b'new'),patch.object(sys,'argv',argv), \
                         contextlib.redirect_stdout(stream):
                        self.assertEqual(static.main(),2 if applying else 0)
                    self.assertEqual(gate.call_count,4 if applying else 0)
                    self.assertEqual(live.read_bytes(),b'old')
                    self.assertEqual(list(root.glob('*.tmp')),[])

    def test_position_status_is_read_only_without_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            live=Path(folder)/'fixture.gil';live.write_bytes(b'old');stream=io.StringIO()
            with patch.object(position,'LIVE',live), \
                 patch.object(position,'inspect_state',return_value={'ok':True,'state':'repaired'}), \
                 patch.object(position,'require_compatible',side_effect=rejected()) as gate, \
                 patch.object(sys,'argv',['entry','status']),contextlib.redirect_stdout(stream):
                self.assertEqual(position.main(),0);gate.assert_not_called()
            self.assertEqual(live.read_bytes(),b'old')

if __name__=='__main__':unittest.main()