"""Skill can join the same reviewed launch batch; no executable is run."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import bundle_prepared
import test_prepare_skill as fixtures


class BundleSkillTests(unittest.TestCase):
    def test_prepared_skill_keeps_its_own_wrapper_and_one_shot_contract(self):
        fixture=fixtures.PrepareSkillTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        built=fixtures.prepare_api.prepare(fixture.data.review_path)
        with patch.object(bundle_prepared,'OUTPUT',fixture.data.base/'batches'):
            result=bundle_prepared.bundle([built['run']])
        self.assertEqual(result['actions'][0]['action'],'create-skill')
        self.assertEqual(result['actions'][0]['wrapper'],'invoke-skill-probe.ps1')
        self.assertFalse(result['executed'] or result['elevationRequested'])
        self.assertFalse((Path(built['run'])/'launch.claim').exists())


if __name__=='__main__':unittest.main()
