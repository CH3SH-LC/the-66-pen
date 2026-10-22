"""Offline receipt rejection tests; no process discovery or execution."""
from pathlib import Path
import sys,struct,unittest,copy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_level_catalog as catalog
import native_profiles as profiles
class CatalogTests(unittest.TestCase):
 def setUp(self):
  self.profile=catalog.load_profile();self.level=self.profile['expectedLevelId']
  self.context={'status':{'value':0},'levelObservation':{'verified':True,'levelId':self.level}}
 def fixture(self):
  raw=bytearray(catalog.CATALOG_BYTES);struct.pack_into('<4I',raw,0,len(raw),1,0,31)
  struct.pack_into('<6Q',raw,16,0x10000,0x20000,0x30000,0x40000,0x50000,0)
  struct.pack_into('<14I',raw,64,self.level,self.level,1,0,3,3,2,2,1024,30,0,1,0,0)
  struct.pack_into('<IIQ',raw,120,self.level,self.level,0x60000)
  return raw
 def decode(self,raw,**patch):
  return catalog.decode(dict(catalogHex=raw.hex(),catalogBytes=len(raw),catalogStatus=0,**patch),self.context,self.profile)
 def test_valid_read_only(self):
  x=self.decode(self.fixture());self.assertTrue(x['ok']);self.assertFalse(x['allowWrites']);self.assertFalse(x['reopenVerified'])
 def test_missing_truncated_or_oversized(self):
  for raw in (b'',self.fixture()[:-1],self.fixture()+b'\0'):
   with self.subTest(size=len(raw)),self.assertRaises(profiles.ProfileError):self.decode(raw)
 def test_abi_version(self):
  raw=self.fixture();struct.pack_into('<I',raw,4,2)
  with self.assertRaises(profiles.ProfileError):self.decode(raw)
 def test_refusal_status(self):
  raw=self.fixture();struct.pack_into('<I',raw,8,7);self.assertFalse(self.decode(raw)['ok'])
 def test_required_flags(self):
  for bit in (1,2,4,8,16):
   raw=self.fixture();struct.pack_into('<I',raw,12,31&~bit);self.assertFalse(self.decode(raw)['ok'])
 def test_identity_counts_versions_budgets_and_unused_fields(self):
  # Byte offsets in the fixed ABI, each changes a business invariant.
  for offset,value in ((64,self.level+1),(68,self.level+1),(72,2),(76,2),(80,513),(84,0),(92,3),(96,1048577),(100,4097),(104,2),(112,1),(116,1)):
   raw=self.fixture();struct.pack_into('<I',raw,offset,value)
   with self.subTest(offset=offset):self.assertFalse(self.decode(raw)['ok'])
 def test_duplicate_rows(self):
  raw=self.fixture();struct.pack_into('<I',raw,72,2);struct.pack_into('<I',raw,108,2);raw[136:152]=raw[120:136];self.assertFalse(self.decode(raw)['ok'])
 def test_nonzero_tail(self):
  raw=self.fixture();raw[-1]=1;self.assertFalse(self.decode(raw)['ok'])
 def test_invalid_pointer(self):
  for offset in (16,24,32,40,48,56,128):
   raw=self.fixture();struct.pack_into('<Q',raw,offset,1);self.assertFalse(self.decode(raw)['ok'])
 def test_unverified_context(self):
  self.context['levelObservation']['verified']=False;self.assertFalse(self.decode(self.fixture())['ok'])
 def test_profile_hash_is_fixed(self):
  self.assertEqual(profiles.sha256(catalog.PROFILE),catalog.PROFILE_SHA256)
if __name__=='__main__':unittest.main(verbosity=2)
