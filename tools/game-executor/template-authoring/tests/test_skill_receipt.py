"""Independent skill catalogue evidence; synthetic records, no native execution."""
import struct
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE/'tests'))
import receipt
import skill_receipt
from test_currency_receipt import encode


class SkillReceiptTests(unittest.TestCase):
    def setUp(self):
        self.old = (0x42000009, 9, 0x50000, 0x60000)
        self.added = (0x41800001, 6, 0x70000, 0x80000)
        self.old_c = (self.old[0], self.old[0], 0x42000099, 0, 1, 4, 0x90000, 0xa0000)
        self.added_c = (self.added[0], self.added[0], 0x41800044, 0, 1, 4, 0xb0000, 0xc0000)
        self.before = encode([self.old], [self.old_c], level=99)

    def check(self, rows=None, companions=None, **kwargs):
        options = dict(level_id=99, returned_resource=0x70000,
                       expected_class=0x80000, expected_companion_class=0xc0000)
        options.update(kwargs)
        return receipt.verify_skill_delta(self.before,
            encode(rows if rows is not None else [self.old, self.added],
                   companions if companions is not None else [self.old_c, self.added_c], level=99), **options)

    def test_full_skill_pair_is_registration_only(self):
        result = self.check()
        self.assertEqual((result['createdId'],result['companionOwnId']), (0x41800001,0x41800044))
        self.assertTrue(result['catalogDeltaVerified'])
        for key in ('persistentSaveVerified','nameVerified','defaultsVerified','gameplayVerified'):
            self.assertFalse(result[key])

    def test_energy_resource_is_not_skill(self):
        for row in [(0x41c00001,7,0x70000,0x80000),(0x41c00001,6,0x70000,0x80000)]:
            with self.subTest(row=row), self.assertRaises(receipt.ReceiptError): self.check(rows=[self.old,row])

    def test_prior_rows_and_returned_pointer_must_match(self):
        with self.assertRaisesRegex(ValueError,'PRIOR_PRIMARY_CHANGED'):
            self.check(rows=[(self.old[0],9,0x50008,0x60000),self.added])
        with self.assertRaisesRegex(ValueError,'NEW_RESOURCE_IDENTITY'): self.check(returned_resource=0x70008)
        with self.assertRaisesRegex(ValueError,'NEW_RESOURCE_IDENTITY'): self.check(expected_class=0x80008)
        with self.assertRaisesRegex(ValueError,'CONTEXT_CHANGED'): self.check(level_id=98)

    def test_companion_must_be_new_same_key_and_correct_domain(self):
        with self.assertRaisesRegex(ValueError,'COMPANION_DELTA_COUNT'): self.check(companions=[self.old_c])
        for field, value in [(0,0x41800002),(1,0x41800002),(3,1),(4,0),(5,5),(7,0xc0008)]:
            row = list(self.added_c); row[field]=value
            with self.subTest(field=field), self.assertRaises(ValueError): self.check(companions=[self.old_c,tuple(row)])
        row = list(self.old_c); row[2] += 1
        with self.assertRaisesRegex(ValueError,'PRIOR_COMPANION_CHANGED'):
            self.check(companions=[tuple(row),self.added_c])

    def test_duplicate_and_incomplete_raw_records_fail(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_PRIMARY'):
            self.check(rows=[self.old,self.added,self.added])
        changed=bytearray.fromhex(self.before); struct.pack_into('<I',changed,0,1)
        self.before=changed.hex()
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_CATALOG'): self.check()


class SkillRawReceiptTests(unittest.TestCase):
    setUp = SkillReceiptTests.setUp
    def raw(self):
        raw = bytearray(skill_receipt.RECEIPT_BYTES)
        struct.pack_into('<4I',raw,0,len(raw),1,0,1)
        skill_receipt.ACTION.pack_into(raw,16,0,0,0,0,
            0xd0000,0xe0000,0x70000,0x80000,0xc0000,0xb0000,
            2,5,0x41800001,0x41800044,1,1,2,2,*([1]*7))
        raw[369784:632088] = bytes.fromhex(self.before)
        raw[632088:] = bytes.fromhex(encode([self.old,self.added],[self.old_c,self.added_c],level=99))
        return raw

    def verify_raw(self, raw):
        return skill_receipt.verify(bytes(raw),level_id=99,global_pointer=0x10000)

    def test_actual_104_byte_action_layout(self):
        result=self.verify_raw(self.raw())
        self.assertTrue(result['catalogDeltaVerified'])
        self.assertEqual(result['action']['metadataCallsCompleted'],2)
        self.assertEqual(result['action']['defaultValue'],5)

    def test_uncertain_failed_attempt_is_decodable_but_not_accepted(self):
        raw=self.raw();struct.pack_into('<I',raw,8,0xc0000005);struct.pack_into('<I',raw,16,16)
        reported=skill_receipt.decode(bytes(raw))
        self.assertTrue(reported['createCalled']);self.assertTrue(reported['outcomeUncertain'])
        with self.assertRaisesRegex(ValueError,'NATIVE_RESULT'):self.verify_raw(raw)

    def test_default_metadata_counts_and_bools_are_not_inferred(self):
        for offset,fmt,value in [(80,'<I',1),(104,'<I',1),(108,'<I',1),(112,'<B',0),(118,'<B',2)]:
            with self.subTest(offset=offset):
                raw=self.raw();struct.pack_into(fmt,raw,offset,value)
                with self.assertRaises(ValueError):self.verify_raw(raw)
        raw=self.raw();struct.pack_into('<I',raw,96,2)
        with self.assertRaisesRegex(ValueError,'BEFORE_COUNTS'):self.verify_raw(raw)

    def test_good_flags_do_not_hide_wrong_registration(self):
        raw=self.raw();struct.pack_into('<I',raw,632088+160+receipt.PRIMARY.size+4,7)
        with self.assertRaisesRegex(ValueError,'NEW_RESOURCE_IDENTITY'):self.verify_raw(raw)


if __name__=='__main__': unittest.main()
