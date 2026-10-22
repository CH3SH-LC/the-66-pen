"""Version refusal tests using only temporary synthetic files and mocked gates."""
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import register_level as reg
import keep_registered as keeper
spec = importlib.util.spec_from_file_location('realtime_lab_guard_test', HERE / 'create-realtime-lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


def refusal():
    return reg.IncompatibleVersion({'ok': False, 'code': 'incompatible-version', 'reasons': ['synthetic changed build']})


class WriteGuardTests(unittest.TestCase):
    def test_register_library_refuses_before_any_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / 'profile.gip'; profile.write_bytes(b'original')
            plan = SimpleNamespace(level_path=root/'new.gil', profile_path=profile,
                                   level_payload=b'level', profile_payload=b'profile')
            with patch.object(reg, 'require_compatible', side_effect=refusal()):
                with self.assertRaises(reg.IncompatibleVersion):
                    reg.apply_registration(plan)
            self.assertEqual(profile.read_bytes(), b'original')
            self.assertFalse(plan.level_path.exists())

    def test_register_rechecks_second_formal_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); profile=root/'profile.gip';profile.write_bytes(b'original')
            plan=SimpleNamespace(level_path=root/'new.gil',profile_path=profile,
                                 level_payload=b'level',profile_payload=b'profile')
            with patch.object(reg,'require_compatible',side_effect=[{},refusal()]) as gate:
                with self.assertRaises(reg.IncompatibleVersion):reg.apply_registration(plan)
            self.assertEqual(gate.call_count,2)
            self.assertTrue(plan.level_path.exists())
            self.assertEqual(profile.read_bytes(),b'original')

    def test_all_apply_clis_refuse_before_file_access(self):
        for module in (reg,keeper,lab):
            with self.subTest(module=module.__name__):
                output=io.StringIO()
                with patch.object(module,'require_compatible',side_effect=refusal()), \
                     patch.object(sys,'argv',['entry.py','--apply']), \
                     patch.object(Path,'read_bytes',side_effect=AssertionError('read before guard')), \
                     patch.object(Path,'write_bytes',side_effect=AssertionError('write before guard')), \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(module.main(),2)
                self.assertEqual(json.loads(output.getvalue())['code'],'incompatible-version')

    def test_atomic_replace_refuses_without_temp_or_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'profile.gip';target.write_bytes(b'old')
            with patch.object(lab,'require_compatible',side_effect=refusal()):
                with self.assertRaises(reg.IncompatibleVersion):lab.atomic_replace(target,b'new',b'old')
            self.assertEqual(target.read_bytes(),b'old')
            self.assertEqual(list(root.iterdir()),[target])

    def test_atomic_replace_rechecks_before_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target=root/'profile.gip';target.write_bytes(b'old')
            with patch.object(lab,'require_compatible',side_effect=[{},refusal()]) as gate:
                with self.assertRaises(reg.IncompatibleVersion):lab.atomic_replace(target,b'new',b'old')
            self.assertEqual(gate.call_count,2)
            self.assertEqual(target.read_bytes(),b'old')
            self.assertEqual(list(root.iterdir()),[target])

    def test_keeper_rechecks_every_iteration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'Beyond_Local_Save_Player.gip';profile.write_bytes(b'original')
            level_dir=root/'Beyond_Local_Save_Level';level_dir.mkdir();(level_dir/'123.gil').write_bytes(b'existing')
            with patch.object(keeper,'decode_container',return_value=SimpleNamespace(payload=b'ignored')), \
                 patch.object(keeper,'parse_profile',return_value=SimpleNamespace(levels=[])), \
                 patch.object(keeper,'build_registered_profile',return_value=(b'rebuilt',123,'built')), \
                 patch.object(keeper,'require_compatible',side_effect=[{},refusal()]) as gate:
                self.assertEqual(keeper.ensure_registered(root,'test','tab',123,'1'),'re-applied')
                profile.write_bytes(b'writer changed profile')
                with self.assertRaises(reg.IncompatibleVersion):keeper.ensure_registered(root,'test','tab',123,'1')
            self.assertEqual(gate.call_count,2)
            self.assertEqual(profile.read_bytes(),b'writer changed profile')

    def test_keeper_checks_new_level_write_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'Beyond_Local_Save_Player.gip';profile.write_bytes(b'original')
            level_dir=root/'Beyond_Local_Save_Level';level_dir.mkdir();(level_dir/'100.gil').write_bytes(b'template')
            with patch.object(keeper,'decode_container',return_value=SimpleNamespace(payload=b'ignored')), \
                 patch.object(keeper,'parse_profile',return_value=SimpleNamespace(levels=[])), \
                 patch.object(keeper,'build_registered_profile',return_value=(b'rebuilt',123,'built')), \
                 patch.object(keeper,'build_level_payload',return_value=b'new level'), \
                 patch.object(keeper,'require_compatible',side_effect=[{},refusal()]) as gate:
                with self.assertRaises(reg.IncompatibleVersion):keeper.ensure_registered(root,'test','tab',123,'1')
            self.assertEqual(gate.call_count,2)
            self.assertFalse((level_dir/'123.gil').exists())

    def test_keeper_present_registration_remains_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'Beyond_Local_Save_Player.gip';profile.write_bytes(b'unchanged')
            with patch.object(keeper,'decode_container',return_value=SimpleNamespace(payload=b'ignored')), \
                 patch.object(keeper,'parse_profile',return_value=SimpleNamespace(levels=[SimpleNamespace(name='test')])), \
                 patch.object(keeper,'require_compatible',side_effect=refusal()) as gate:
                self.assertEqual(keeper.ensure_registered(root,'test','tab',123,'1'),'present')
                gate.assert_not_called()
            self.assertEqual(profile.read_bytes(),b'unchanged')


if __name__=='__main__':unittest.main()