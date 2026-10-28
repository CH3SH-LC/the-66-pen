"""Native-free contract/geometry regressions for the new destructive conversion."""
import unittest
from pathlib import Path
import sys
import struct
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from assembly_build import validate_pairs
from assembly_receipt import extension, same_world


class Assembly(unittest.TestCase):
    def test_refuse_cycles_and_sources_used_as_hosts(self):
        for pairs in ([dict(sourceId=1,hostId=1)],
                      [dict(sourceId=1,hostId=2),dict(sourceId=2,hostId=3)],
                      [dict(sourceId=1,hostId=3),dict(sourceId=1,hostId=4)]):
            with self.assertRaises(ValueError):validate_pairs(pairs)

    def test_bounded_batch(self):
        self.assertEqual(len(validate_pairs([dict(sourceId=i,hostId=200) for i in range(1,65)])),64)
        with self.assertRaises(ValueError):validate_pairs([dict(sourceId=i,hostId=200) for i in range(1,66)])
        with self.assertRaises(ValueError):validate_pairs([])

    def test_rotation_equivalence_but_not_stretched_geometry(self):
        a=dict(position=(1,2,3),rotation=(0,359,0),scale=(2,3,4))
        b=dict(a,rotation=(0,-1,0))
        self.assertTrue(same_world(a,b))
        self.assertFalse(same_world(a,dict(b,scale=(2,3,4.1))))
        self.assertFalse(same_world(a,dict(b,position=(1,2,3.1))))
        self.assertFalse(same_world(a,dict(b,rotation=(0,2,0))))
        self.assertFalse(same_world(a,dict(b,position=(float('nan'),2,3))))

    def test_receipt_layout_and_unused_rows(self):
        for size in (33208,262584):
            total=48+(48+128*280+size)+size+128*152
            raw=bytearray(total)
            struct.pack_into('<12I',raw,0,total,1,1,1,0,1,0,0,0,0,0,0)
            decoded,before,after=extension(bytes(raw),size)
            self.assertEqual(len(decoded['rows']),1)
            self.assertEqual(before,bytes(size))
            self.assertEqual(after,bytes(size))
            raw[-1]=1
            with self.assertRaises(ValueError):extension(bytes(raw),size)

    def test_transaction_diagnostic_abi(self):
        size=262584
        total=48+(48+128*280+size)+size+128*152+88
        raw=bytearray(total)
        struct.pack_into('<12I',raw,0,total,2,1,2,0,1,0,0,0,0,0,206)
        struct.pack_into('<8Q6I',raw,total-88,*range(1,9),1,20,20,0,1,0)
        result,_,_=extension(bytes(raw),size)
        self.assertEqual(result['undoDiagnostic']['base'],20)
        self.assertEqual(result['undoDiagnostic']['count'],1)
        self.assertEqual(result['undoDiagnostic']['reserved'],0)


if __name__=='__main__':unittest.main()
