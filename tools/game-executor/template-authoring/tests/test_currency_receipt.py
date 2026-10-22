from pathlib import Path
import importlib.util
import struct
import unittest

spec = importlib.util.spec_from_file_location("template_receipt", Path(__file__).resolve().parents[1] / "receipt.py")
receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receipt)


def encode(rows, companions=(), *, level=1073741842, status=0):
    data = bytearray(receipt.CATALOG_BYTES)
    struct.pack_into("<4I2Q", data, 0, status, level, 1024, 20, 0x10000, 0x20000)
    for offset, pointer, count in ((32, 0x30000, len(rows)), (96, 0x40000, len(companions))):
        receipt.DICTIONARY.pack_into(data, offset, pointer, pointer + 0x1000, pointer + 0x2000,
                                    0, 7, 7, count, 0, 1, 1, count, -1)
    for index, row in enumerate(rows):
        receipt.PRIMARY.pack_into(data, 160 + index * receipt.PRIMARY.size, *row)
    for index, row in enumerate(companions):
        receipt.COMPANION.pack_into(data, 160 + receipt.MAX_ROWS * receipt.PRIMARY.size +
                                   index * receipt.COMPANION.size, *row)
    return data.hex()


class CurrencyReceiptTest(unittest.TestCase):
    old = (0x42000001, 9, 0x50000, 0x60000)
    added = (0x42800001, 11, 0x70000, 0x80000)
    companion = (0x42000001, 0x42000001, 0x42000099, 0, 1, 4, 0x90000, 0xA0000)

    def verify(self, before, after):
        return receipt.verify_currency_delta(before, after, level_id=1073741842,
                                             returned_resource=0x70000, expected_class=0x80000)

    def test_delta_recomputed_and_not_save_acceptance(self):
        result = self.verify(encode([self.old], [self.companion]), encode([self.added, self.old], [self.companion]))
        self.assertEqual(result["createdId"], self.added[0])
        self.assertTrue(result["catalogDeltaVerified"])
        self.assertFalse(result["persistentSaveVerified"])

    def test_raw_damage_rejected(self):
        original = encode([self.old])
        for broken in (original[:-2], "z" + original[1:], encode([self.old], status=3)):
            with self.subTest(broken=broken[:20]), self.assertRaises(receipt.ReceiptError):
                receipt.decode_catalog(broken)

    def test_partial_occupancy_rejected(self):
        raw = bytearray.fromhex(encode([self.old]))
        struct.pack_into("<I", raw, 32 + 40, 2)  # initializedCount=2, rowCount=1
        with self.assertRaisesRegex(receipt.ReceiptError, "PARTIAL_DICTIONARY"):
            receipt.decode_catalog(raw.hex())

    def test_old_primary_replacement_rejected(self):
        changed = (self.old[0], self.old[1], 0xB0000, self.old[3])
        with self.assertRaisesRegex(receipt.ReceiptError, "PRIOR_PRIMARY_CHANGED"):
            self.verify(encode([self.old]), encode([self.added, changed]))

    def test_companion_change_rejected_even_when_main_delta_valid(self):
        changed = (*self.companion[:2], 0x42000088, *self.companion[3:])
        with self.assertRaisesRegex(receipt.ReceiptError, "COMPANION_CHANGED"):
            self.verify(encode([self.old], [self.companion]), encode([self.old, self.added], [changed]))

    def test_wrong_class_band_level_and_extra_creation(self):
        cases = (encode([self.old, (self.added[0], 11, 0x70000, 0xB0000)]),
                 encode([self.old, (0x42400001, 11, 0x70000, 0x80000)]),
                 encode([self.old, self.added], level=1073741843),
                 encode([self.old, self.added, (0x42800002, 11, 0xB0000, 0x80000)]))
        for after in cases:
            with self.subTest(after=after[:20]), self.assertRaises(receipt.ReceiptError):
                self.verify(encode([self.old]), after)


class ItemReceiptTest(unittest.TestCase):
    added = (0x42000001, 9, 0x50000, 0x60000)

    def verify(self, companions):
        return receipt.verify_item_delta(encode([]), encode([self.added], companions),
            level_id=1073741842, expected_class=0x60000, expected_companion_class=0xA0000)

    def test_companion_own_id_has_independent_domain(self):
        for own in (self.added[0], 0x42000099):
            companion = (self.added[0], self.added[0], own, 0, 1, 4, 0x90000, 0xA0000)
            self.assertEqual(self.verify([companion])["companionOwnId"], own)

    def test_missing_or_wrong_companion_rejected(self):
        companions = ([], [(self.added[0], self.added[0], 1, 0, 1, 3, 0x90000, 0xA0000)],
                      [(self.added[0], self.added[0], 1, 0, 1, 4, 0x90000, 0xB0000)],
                      [(self.added[0] + 1, self.added[0] + 1, 1, 0, 1, 4, 0x90000, 0xA0000)])
        for rows in companions:
            with self.subTest(rows=rows), self.assertRaises(receipt.ReceiptError):
                self.verify(rows)


if __name__ == "__main__":
    unittest.main()
