"""Startup regression fixtures are never live game cards."""
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from build import initialize_receipt_in_place

class StartupContractTests(unittest.TestCase):
    def test_legacy_receipt_assignment_becomes_direct_clear(self):
        self.assertEqual(initialize_receipt_in_place('before\n    *receipt = {};\nafter'),
                         'before\n    std::memset(receipt, 0, sizeof(*receipt));\nafter')

    def test_shared_direct_clear_is_preserved(self):
        source='before\n    std::memset(receipt, 0, sizeof(*receipt));\nafter'
        self.assertEqual(initialize_receipt_in_place(source),source)

    def test_ambiguous_or_unknown_receipt_initialization_is_rejected(self):
        for source in ('unknown','    *receipt = {};\n    *receipt = {};',
                       '    *receipt = {};\n    std::memset(receipt, 0, sizeof(*receipt));'):
            with self.subTest(source=source),self.assertRaisesRegex(ValueError,'RECEIPT_INITIALIZATION_PATTERN_CHANGED'):
                initialize_receipt_in_place(source)

if __name__=='__main__':
    unittest.main()
