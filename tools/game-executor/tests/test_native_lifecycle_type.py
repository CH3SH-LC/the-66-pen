"""Offline synthetic receipt tests; no process discovery or game access."""
from pathlib import Path
import sys,struct,unittest,copy,tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import native_lifecycle_type as api
import native_profiles as profiles
class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.profile=api.load_profile();self.base=0x140000000;self.cls=0x70000000000;self.level=self.profile['expectedLevelId'];self.target=self.base+0x9037840
  self.context={'status':{'value':0},'levelObservation':{'verified':True,'levelId':self.level},'pointers':{'moduleBase':hex(self.base)},'counts':{'peImageSize':453693440}}
 def fixture(self):
  raw=bytearray(api.LIFECYCLE_TYPE_BYTES);struct.pack_into('<4I',raw,0,len(raw),1,0,255)
  struct.pack_into('<6Q',raw,16,self.base,self.base+0x5826620,self.cls,self.cls+0xd0,self.cls+0xd0+32,self.target)
  struct.pack_into('<12I',raw,64,453693440,self.level,1,1,4,4,1,2,12000,50,0,0)
  struct.pack_into('<4Q',raw,112,self.base+1,self.base+2,self.target,self.base+3)
  struct.pack_into('<4Q',raw,1136,0,0x60000000,0,0x70000000)
  return raw
 def decode(self,raw,**fields):
  return api.decode({'lifecycleTypeHex':raw.hex(),'lifecycleTypeBytes':len(raw),'lifecycleTypeStatus':0,**fields},self.context,self.profile)
 def test_valid(self):
  r=self.decode(self.fixture());self.assertTrue(r['ok']);self.assertTrue(r['allocatedClassToCandidateFunctionVerified']);self.assertFalse(r['completionVerified']);self.assertFalse(r['reopenVerified']);self.assertEqual(r['gameMethodsCalled'],0)
 def test_trailing_words_are_opaque(self):
  raw=self.fixture();struct.pack_into('<Q',raw,1136+16,0);self.assertTrue(self.decode(raw)['ok'])
 def test_malformed_encoding_size(self):
  for raw in (b'',self.fixture()[:-1],self.fixture()+b'\0'):
   with self.assertRaises(profiles.ProfileError):self.decode(raw)
  with self.assertRaises(profiles.ProfileError):self.decode(self.fixture(),lifecycleTypeHex='z'*(2160*2))
 def test_abi_version(self):
  raw=self.fixture();struct.pack_into('<I',raw,4,2)
  with self.assertRaises(profiles.ProfileError):self.decode(raw)
 def test_status_fail_closed(self):
  for status in range(1,12):
   raw=self.fixture();struct.pack_into('<I',raw,8,status);self.assertFalse(self.decode(raw)['ok'])
 def test_flags_each_required(self):
  for bit in (1,2,4,8,16,32,64,128):
   raw=self.fixture();struct.pack_into('<I',raw,12,255&~bit);self.assertFalse(self.decode(raw)['ok'])
 def test_identity_layout_initialization_and_stability(self):
  for offset,value in ((64,0),(68,self.level+1),(72,0),(76,0),(80,0),(80,129),(84,5),(88,2),(92,1),(96,1048577),(100,4097),(104,1),(108,1)):
   raw=self.fixture();struct.pack_into('<I',raw,offset,value)
   with self.subTest(offset=offset,value=value):self.assertFalse(self.decode(raw)['ok'])
 def test_pointer_layout_and_target(self):
  for offset in (16,24,32,40,48,56):
   raw=self.fixture();struct.pack_into('<Q',raw,offset,1)
   with self.subTest(offset=offset):self.assertFalse(self.decode(raw)['ok'])
 def test_no_match(self):
  raw=self.fixture();struct.pack_into('<Q',raw,128,self.target+1);self.assertFalse(self.decode(raw)['ok'])
 def test_duplicate_match(self):
  raw=self.fixture();struct.pack_into('<Q',raw,112,self.target);self.assertFalse(self.decode(raw)['ok'])
 def test_wrong_interleaved_layout(self):
  raw=self.fixture();struct.pack_into('<Q',raw,48,self.cls+0xd0+8);self.assertFalse(self.decode(raw)['ok'])
 def test_nonzero_unused(self):
  for offset in (112+4*8,1136+4*8,2152):
   raw=self.fixture();struct.pack_into('<Q',raw,offset,1);self.assertFalse(self.decode(raw)['ok'])
 def test_context_refusal(self):
  for section,key,value in [('status','value',1),('levelObservation','verified',False),('levelObservation','levelId',1),('pointers','moduleBase','bad'),('counts','peImageSize',1)]:
   old=copy.deepcopy(self.context);self.context[section][key]=value;self.assertFalse(self.decode(self.fixture())['ok']);self.context=old
 def test_record_status_mismatch(self):
  self.assertFalse(self.decode(self.fixture(),lifecycleTypeStatus=1)['ok'])
 def test_profile_hash(self):
  self.assertEqual(profiles.sha256(api.PROFILE),api.PROFILE_SHA256)
 def test_emitted_header(self):
  with tempfile.TemporaryDirectory(dir=HERE) as directory:
   api.append_header(directory,self.profile);text=(Path(directory)/'target_config.h').read_text(encoding='utf-8')
   for token in ('HR_READ_LIFECYCLE_TYPE 1ULL','GLT_CLASS_SLOT_RVA 0x5826620ULL','GLT_HOTFIX_RVAS 0x57833b1,0x57833ad'):self.assertIn(token,text)
if __name__=='__main__':unittest.main(verbosity=2)
