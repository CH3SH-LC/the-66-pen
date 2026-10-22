import struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scene_frame_receipt import SIZE,parse
class FrameContract(unittest.TestCase):
    def receipt(self):
        b=bytearray(SIZE)
        struct.pack_into('<24I',b,0,SIZE,1,0,0,3,1,14,1,7,8,7,8,1,1,0,0,2,19,1,1,1,1,0,0)
        struct.pack_into('<16I',b,96,336,1,0,0,3,0,0,0,1,1,15,15,1073741845,0,0,0)
        struct.pack_into('<I',b,96+64+92,1);struct.pack_into('<I',b,96+200+92,1)
        struct.pack_into('<6Q',b,432,0x10000,0x20000,0,0,0,1)
        return b
    def test_release(self):self.assertEqual(parse(self.receipt())['resourcesReleased'],1)
    def test_live_texture_cannot_pass(self):
        b=self.receipt();struct.pack_into('<Q',b,448,0x20000)
        with self.assertRaisesRegex(ValueError,'RELEASE_PROOF'):parse(b)
    def test_same_frame_cannot_pass(self):
        b=self.receipt();struct.pack_into('<I',b,84,0)
        with self.assertRaisesRegex(ValueError,'RELEASE_PROOF'):parse(b)
    def test_timeout_remains_unclean(self):
        b=self.receipt();struct.pack_into('<I',b,28,0);self.assertEqual(parse(b)['resourcesReleased'],0)
    def test_readonly_followup_preserves_release_proof(self):
        b=self.receipt();struct.pack_into('<I',b,20,3)
        self.assertEqual(parse(b)['operation'],3)
        struct.pack_into('<Q',b,448,0x20000)
        with self.assertRaisesRegex(ValueError,'RELEASE_PROOF'):parse(b)
    def test_unused_png_rejected(self):
        b=self.receipt();b[-1]=1
        with self.assertRaisesRegex(ValueError,'UNUSED_PNG'):parse(b)
if __name__=='__main__':unittest.main()
