import struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bounds_receipt import SIZE,parse
class BoundsContract(unittest.TestCase):
    def raw(self):
        b=bytearray(SIZE)
        struct.pack_into('<12I',b,0,SIZE,1,0,0,3,2,2,1,0,1,1,1)
        struct.pack_into('<16I',b,96,336,1,0,0,3,0,0,0,1,1,15,15,1073741845,0,0,0)
        struct.pack_into('<I',b,96+64+92,1);struct.pack_into('<I',b,96+200+92,1)
        struct.pack_into('<16f',b,464,0,0,0,100,100,100,800,300,800,800,300,800,800,300,800,0)
        return b
    def test_completed(self):self.assertEqual(parse(self.raw())['writeCompleted'],1)
    def test_incorrect_second_vector(self):
        b=self.raw();struct.pack_into('<f',b,500,100)
        with self.assertRaisesRegex(ValueError,'READBACK'):parse(b)
    def test_wrong_before_refused(self):
        b=self.raw();struct.pack_into('<f',b,464,400)
        with self.assertRaisesRegex(ValueError,'BASELINE'):parse(b)
    def test_partial_not_promoted(self):
        b=self.raw();struct.pack_into('<I',b,40,0);struct.pack_into('<I',b,28,0)
        self.assertEqual(parse(b)['writeCompleted'],0)
if __name__=='__main__':unittest.main()
