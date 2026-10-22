"""Synthetic raw evidence, including changed old rows and mismatched dual sets."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import component_receipt as c


def encode(rows):
    data = bytearray(11376)
    struct.pack_into('<5I', data, 0, 0, 5000, 40, len(rows), len(rows))
    struct.pack_into('<7Q', data, 24, 0x10000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000, 0x70000)
    struct.pack_into('<5Ii', data, 80, 10, 10, len(rows), 2, 3, -1)
    for index, row in enumerate(rows):
        struct.pack_into('<i', data, 112 + 4 * index, row[4])
        struct.pack_into('<4QiB3x', data, 1136 + 40 * index, *row)
    return bytes(data)


class ComponentReceiptTests(unittest.TestCase):
    old = (0xA0000, 0xB0000, 0xC0000, 0xD0000, 1, 1)
    bag = (0x80000, 0x90000, 0xE0000, 0xF0000, 33, 1)

    def check(self, before, after, final, attached=True):
        return c.verify_component_transition(before, after, final, owner=0x10000, kind=33,
            wrapper_class=0x90000, config_class=0xF0000, wrapper=0x80000, config=0xE0000,
            attach_called=attached)

    def test_exact_append_and_existing_component(self):
        one, two = encode([self.old]), encode([self.old, self.bag])
        result = self.check(one, two, two)
        self.assertEqual((result['componentCountBefore'], result['componentCountAfter']), (1, 2))
        self.assertFalse(result['playerCharacterVerified'] or result['persistentSaveVerified'])
        self.assertTrue(self.check(two, b'', two, False)['componentDeltaVerified'])

    def test_changed_or_reordered_old_component_rejected(self):
        one = encode([self.old])
        for rows in ([(*self.old[:5], 0), self.bag], [self.bag, self.old]):
            with self.assertRaisesRegex(ValueError, 'COMPONENT_ATTACH_DELTA'):
                self.check(one, encode(rows), encode(rows))

    def test_set_list_disagreement_and_duplicate_wrappers_rejected(self):
        raw = bytearray(encode([self.old, self.bag]))
        struct.pack_into('<i', raw, 116, 35)
        with self.assertRaisesRegex(ValueError, 'COMPONENT_SET_LIST_KINDS'):
            c.decode_components(bytes(raw))
        with self.assertRaisesRegex(ValueError, 'COMPONENT_DUPLICATE_ROW'):
            c.decode_components(encode([self.old, (self.old[0], *self.bag[1:])]))

    def test_changes_after_binding_and_wrong_owner_rejected(self):
        two = encode([self.old, self.bag])
        changed = encode([self.old, (*self.bag[:5], 0)])
        with self.assertRaisesRegex(ValueError, 'COMPONENT_POST_BINDING_CHANGED'):
            self.check(encode([self.old]), two, changed)
        changed = bytearray(two); struct.pack_into('<Q', changed, 24, 0x11000)
        with self.assertRaisesRegex(ValueError, 'COMPONENT_OWNER_CHANGED'):
            self.check(encode([self.old]), two, bytes(changed))

    def test_bad_status_counts_and_missing_reused_component_rejected(self):
        good = encode([self.old])
        for offset, value, reason in ((0, 3, 'INCOMPLETE'), (12, 257, 'COUNT'),
                                      (80, 257, 'CAPACITIES')):
            raw = bytearray(good); struct.pack_into('<I', raw, offset, value)
            with self.assertRaisesRegex(ValueError, reason): c.decode_components(bytes(raw))
        with self.assertRaisesRegex(ValueError, 'COMPONENT_REUSED_KIND_MISSING'):
            self.check(good, b'', good, False)

    def test_only_target_enable_may_change_during_native_inheritance_update(self):
        before, after = encode([self.old]), encode([self.old, self.bag])
        parameters = dict(owner=0x10000, kind=33, wrapper_class=0x90000,
            config_class=0xF0000, wrapper=0x80000, config=0xE0000,
            attach_called=True, allow_target_enable_change=True)
        result = c.verify_component_transition(before, after,
            encode([self.old, (*self.bag[:5], 0)]), **parameters)
        self.assertTrue(result['targetEnableChanged'])
        self.assertEqual(result['targetEnabledAfter'], 0)
        with self.assertRaisesRegex(ValueError, 'COMPONENT_POST_BINDING_CHANGED'):
            c.verify_component_transition(before, after,
                encode([(*self.old[:5], 0), self.bag]), **parameters)


if __name__ == '__main__': unittest.main()
