"""Capability discovery must survive allowlist removal without calling the game."""
import unittest
from unittest.mock import patch
from backend import entity_server as server


class CurrentCapabilities(unittest.TestCase):
    def test_current_native_contract_imports_and_does_not_dispatch(self):
        with patch.object(server, '_ok', side_effect=lambda method, **fields: fields), \
             patch.object(server, '_fail', side_effect=lambda method, exc: (_ for _ in ()).throw(exc)):
            report = server.mw_scene_capabilities()
        self.assertIsNone(report['supportedTemplateIds'])
        self.assertIsNone(report['supportedTemplateCount'])
        self.assertFalse(report['templateIdRule']['whitelistEnforced'])
        for candidate in (1, 20001125, 2**32 - 1):
            self.assertTrue(server.is_supported_template(candidate))
        for candidate in (0, -1, True, 2**32):
            self.assertFalse(server.is_supported_template(candidate))
        self.assertEqual(report['stages']['runtime'], 'not performed by this server')


if __name__ == '__main__':
    unittest.main()
