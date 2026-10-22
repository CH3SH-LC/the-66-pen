"""The offline bundle must use the retained successful file, never a live path."""
import unittest
from unittest.mock import patch
from pathlib import Path

from tools.gameplan.demo.offline_farming_baseline import inspect_baseline, BASELINE_GIL


class OfflineBaselineTests(unittest.TestCase):
    def test_real_saved_assets_and_geometry(self):
        with patch('subprocess.run', side_effect=AssertionError('no process execution')):
            result = inspect_baseline()
        self.assertTrue(result['ok'])
        self.assertEqual(result['shopIndex'], 1)
        self.assertEqual(result['interactionHosts'][1]['position'], [4.0, 0.0, 0.0])
        self.assertFalse(result['liveSessionVerified'])
        self.assertFalse(result['newInteractionDeployed'])

    def test_formal_save_is_not_an_offline_source(self):
        with self.assertRaisesRegex(ValueError, 'PROJECT_COPY'):
            inspect_baseline(Path.home()/'AppData/LocalLow/miHoYo/原神/formal.gil')

    def test_tampered_copy_is_rejected_before_schema_read(self):
        with patch.object(Path, 'read_bytes', return_value=b'changed'), \
                self.assertRaisesRegex(ValueError, 'BASELINE_CHANGED'):
            inspect_baseline(BASELINE_GIL)


if __name__ == '__main__':
    unittest.main()
