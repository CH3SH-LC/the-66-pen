"""Read-only regression checks for DS discovery, without a live game or helper."""
import importlib.util
from pathlib import Path
import unittest

from tools.authoring import author, inventory

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('ds_entity_names', ROOT / 'tools/game-executor/entity_name_rule.py')
names = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(names)


class DiscoveryRegression(unittest.TestCase):
    def test_removed_whitelist_does_not_break_inventory(self):
        report = inventory.inventory('core')
        finding = next(row for row in report['findings'] if row['id'] == 'template-wrapper-drift')
        self.assertTrue(finding['literalAllowlistsAbsent'])
        self.assertIsNone(finding['missingFromUnified'])
        self.assertFalse(report['liveProbed'])

    def test_real_chinese_name_and_id_search(self):
        by_id = names.search('20001125')
        self.assertEqual([row['templateId'] for row in by_id['rows']], [20001125])
        text = by_id['rows'][0]['name']
        self.assertTrue(text)
        by_name = names.search(text)
        self.assertIn(20001125, [row['templateId'] for row in by_name['rows']])
        self.assertFalse(by_name['placementVerified'])

    def test_duplicate_names_keep_distinct_ids_and_paginate(self):
        first = names.search('乔木', limit=2)
        self.assertGreater(first['matched'], 2)
        self.assertEqual(first['nextOffset'], 2)
        second = names.search('乔木', limit=2, offset=first['nextOffset'])
        self.assertTrue(set(row['templateId'] for row in first['rows']).isdisjoint(
            row['templateId'] for row in second['rows']))

    def test_no_match_and_invalid_pagination(self):
        self.assertEqual(names.search('DS_NO_SUCH_PREFAB')['rows'], [])
        for kwargs in ({'limit': 0}, {'limit': 101}, {'offset': -1}, {'limit': True}):
            with self.assertRaises(ValueError):
                names.search('乔木', **kwargs)

    def test_author_capabilities_distinguish_requestable_and_verified(self):
        report = author.capabilities()
        self.assertIn(20000, report['graphKinds'])
        self.assertIsNone(report['templateIds'])
        self.assertFalse(report['boundGraphEditing'])
        self.assertFalse(report['officialPlaytestVerified'])


if __name__ == '__main__':
    unittest.main()
