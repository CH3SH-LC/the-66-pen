import unittest,struct,json,hashlib,tempfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_reopen_guards as g
P=Path(__file__).resolve().parent/'fixtures/reopen-guards'
ARGS=dict(invocation=77,module_base=0x140000000,global_root=0x10000000,current_record=0x29000000,scheduler_status=0,scheduler_flags=255)
class DecoderTests(unittest.TestCase):
 def raw(self,name='valid'):return (P/(name+'.bin')).read_bytes()
 def test_valid(self):
  r=g.decode_raw(self.raw(),**ARGS);self.assertTrue(r['receiptValid']);self.assertTrue(r['bothFalseProven']);self.assertFalse(r['allowWrites']);self.assertFalse(r['reopenVerified']);self.assertFalse(r['scheduler']['absenceProven'])
 def test_cache_unknown(self):
  r=g.decode_raw(self.raw('cache_null'),**ARGS);self.assertEqual(r['confirmation'],'unknown');self.assertIs(r['earlyAbort'],False);self.assertFalse(r['bothFalseProven'])
 def test_unavailable_is_not_absence(self):
  r=g.decode_raw(self.raw('unavailable_scheduler'),**ARGS);self.assertTrue(r['bothFalseProven']);self.assertEqual(r['scheduler']['unavailableCount'],1);self.assertFalse(r['scheduler']['absenceProven'])
 def test_partial_scheduler_keeps_guards_separate(self):
  r=g.decode_raw(self.raw("partial_scheduler"),**dict(ARGS,scheduler_status=5,scheduler_flags=7));self.assertTrue(r["receiptValid"]);self.assertTrue(r["bothFalseProven"]);self.assertFalse(r["scheduler"]["complete"]);self.assertFalse(r["scheduler"]["absenceProven"])
 def test_confirmation_true_not_eligible(self):
  r=g.decode_raw(self.raw("confirmation_true"),**ARGS);self.assertTrue(r["receiptValid"]);self.assertIs(r["confirmation"],True);self.assertFalse(r["bothFalseProven"])
 def test_bad_invocation(self):
  r=g.decode_raw(self.raw(),**dict(ARGS,invocation=78));self.assertFalse(r['receiptValid']);self.assertFalse(r['bothFalseProven'])
 def test_bad_scheduler_binding(self):
  r=g.decode_raw(self.raw(),**dict(ARGS,scheduler_status=5,scheduler_flags=7));self.assertFalse(r['receiptValid'])
 def test_truncated(self):
  with self.assertRaisesRegex(ValueError,'ABI_SIZE'):g.decode_raw(self.raw()[:-1],**ARGS)
 def test_unstable_boolean_cannot_pass(self):
  raw=bytearray(self.raw());struct.pack_into('<I',raw,12,7);r=g.decode_raw(bytes(raw),**ARGS);self.assertFalse(r['receiptValid']);self.assertEqual(r['confirmation'],'unknown')
 def test_partial_recheck(self):
  raw=bytearray(self.raw());struct.pack_into('<I',raw,140,0);r=g.decode_raw(bytes(raw),**ARGS);self.assertFalse(r['receiptValid'])
 def test_profile_modified(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'profile.json';p.write_bytes(g.PROFILE.read_bytes()+b' ')
   with self.assertRaisesRegex(ValueError,'PROFILE_CHANGED'):g.load_profile(p)
 def test_anchor_source_hashes(self):
  self.assertEqual(len(g.load_profile()['anchors']),6)
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  import build_readonly_profile as builder
  self.b=builder;self.p=g.load_profile();pid=self.p['expectedProcessId'];creation=self.p['expectedProcessCreation']
  self.prepared={'session':{'pid':pid,'tid':44,'processCreation':creation},'nativeDefinitions':{'HR_NONCE':77,'HR_TARGET_PID':pid,'HR_TARGET_TID':44,'HR_TARGET_CREATION':creation},
    'levelCatalogProfileSha256':builder.catalog_api.PROFILE_SHA256,'lifecycleTypeProfileSha256':builder.lifecycle_api.PROFILE_SHA256,'schedulerCoroutinesProfileSha256':builder.scheduler_api.PROFILE_SHA256,
    'schedulerCoroutinesDecoderSha256':builder.profiles.sha256(Path(builder.scheduler_api.__file__)),
    'reopenGuardsProfileSha256':g.PROFILE_SHA256,'reopenGuardsHeaderSha256':g.HEADER_SHA256,'reopenGuardsDecoderSha256':builder.profiles.sha256(Path(g.__file__))}
  self.context={'status':{'value':0},'pointers':{'moduleBase':hex(ARGS['module_base']),'global':hex(ARGS['global_root'])},'levelCatalog':{'ok':True,'reasons':[],'levels':[{'id':self.p['expectedLevelId'],'record':ARGS['current_record']}]},'lifecycleType':{'ok':True,'reasons':[]},'schedulerCoroutines':{'ok':True,'reasons':[],'flags':255}}
 def record(self,name='valid',scheduler_status=0):
  return {'reopenGuardsHex':(P/(name+'.bin')).read_bytes().hex(),'reopenGuardsBytes':168,'reopenGuardsStatus':0,'schedulerCoroutinesStatus':scheduler_status,'pid':self.p['expectedProcessId'],'tid':44}
 def test_production_true_boolean_is_read_success_not_permission(self):
  v=g.decode(self.record('confirmation_true'),self.context,self.p,self.prepared);self.assertTrue(v['ok']);self.assertIs(v['confirmation'],True);self.assertFalse(v['bothFalseProven']);self.assertFalse(v['allowWrites'])
 def test_production_unknown_remains_unknown_and_not_ok(self):
  r=self.record('cache_null');r['reopenGuardsStatus']=9;v=g.decode(r,self.context,self.p,self.prepared);self.assertFalse(v['ok']);self.assertEqual(v['confirmation'],'unknown');self.assertIs(v['earlyAbort'],False)
 def test_failed_scheduler_stays_independent_and_never_absence(self):
  self.context['schedulerCoroutines']={'ok':False,'flags':7,'reasons':['SCHEDULER_LIMIT']};v=g.decode(self.record('partial_scheduler',5),self.context,self.p,self.prepared);self.assertTrue(v['ok']);self.assertTrue(v['bothFalseProven']);self.assertFalse(v['scheduler']['complete']);self.assertFalse(v['scheduler']['absenceProven'])
 def test_identity_nonce_or_prerequisite_failure_erases_boolean_claim(self):
  import copy
  for field in ('pid','tid'):
   r=self.record();r[field]+=1;v=g.decode(r,self.context,self.p,self.prepared);self.assertFalse(v['ok']);self.assertEqual(v['confirmation'],'unknown')
  p=copy.deepcopy(self.prepared);p['nativeDefinitions']['HR_NONCE']+=1;self.assertFalse(g.decode(self.record(),self.context,self.p,p)['ok'])
  self.context['levelCatalog']['ok']=False;self.assertFalse(g.decode(self.record(),self.context,self.p,self.prepared)['ok'])
 def test_reported_status_and_hex_rejected(self):
  r=self.record();r['reopenGuardsStatus']=8;self.assertFalse(g.decode(r,self.context,self.p,self.prepared)['ok'])
  for value in ('','zz'*168):
   r=self.record();r['reopenGuardsHex']=value
   with self.assertRaises(ValueError):g.decode(r,self.context,self.p,self.prepared)
 def test_missing_any_build_prerequisite_refused_before_disk(self):
  from unittest.mock import patch
  with patch.object(self.b.profiles,'load_profile',side_effect=AssertionError('disk touched')):
   for mask in range(7):
    opts={'level_catalog':bool(mask&1),'lifecycle_type':bool(mask&2),'scheduler_coroutines':bool(mask&4),'reopen_guards':True}
    with self.assertRaisesRegex(ValueError,'REOPEN_REQUIRES_ALL_READONLY_EXTENSIONS'):self.b.prepare(**opts)
    with self.assertRaisesRegex(ValueError,'REOPEN_REQUIRES_ALL_READONLY_EXTENSIONS'):self.b.compile_probe(Path('.'),**opts)
 def run_pipeline(self,record,prepared=None):
  from unittest.mock import patch,Mock
  from contextlib import ExitStack
  docs={'prepared.json':prepared if prepared is not None else self.prepared,'build-result.json':{'hashes':{}},'exit.json':{'executed':True,'exitCode':0,'error':None}}
  decoder=Mock();decoder.read_probe.return_value=(record,'fixture');decoder.decode_snapshot.return_value=self.context;order=[]
  def stage(name,value):
   def decode(*args):order.append(name);return value
   return decode
  with ExitStack() as stack:
   stack.enter_context(patch.object(self.b,'read_json',side_effect=lambda p:docs[p.name]));stack.enter_context(patch.object(self.b,'write_json'));stack.enter_context(patch.object(self.b,'load_decoder',return_value=decoder))
   stack.enter_context(patch.object(self.b,'validate_receipt',return_value={'ok':False,'reasons':['EXISTING_OVERALL_FAILURE']}))
   for api,name,key in ((self.b.catalog_api,'catalog','levelCatalog'),(self.b.lifecycle_api,'type','lifecycleType'),(self.b.scheduler_api,'scheduler','schedulerCoroutines')):stack.enter_context(patch.object(api,'decode',side_effect=stage(name,self.context[key])))
   return self.b.decode_run(Path('.')),order
 def test_pipeline_does_not_promote_overall_failure_from_two_false(self):
  result,order=self.run_pipeline(self.record());self.assertEqual(order,['catalog','type','scheduler']);self.assertTrue(result['reopenGuards']['bothFalseProven']);self.assertFalse(result['ok']);self.assertIn('EXISTING_OVERALL_FAILURE',result['reasons'])
 def test_unbound_extension_rejected(self):
  for key,value in (('reopenGuardsHex',''),('reopenGuardsBytes',168),('reopenGuardsStatus',0)):
   result,_=self.run_pipeline({key:value},{});self.assertFalse(result['ok']);self.assertIn('UNBOUND_REOPEN_EXTENSION',result['reasons'])
 def test_source_profile_header_and_all_input_bindings_required(self):
  import copy
  for key,reason in (('reopenGuardsProfileSha256','REOPEN_PROFILE_BINDING'),('reopenGuardsHeaderSha256','REOPEN_HEADER_BINDING'),('reopenGuardsDecoderSha256','REOPEN_DECODER_BINDING')):
   p=copy.deepcopy(self.prepared);p[key]='changed'
   with self.assertRaisesRegex(ValueError,reason):self.run_pipeline(self.record(),p)
  p=copy.deepcopy(self.prepared);p.pop('levelCatalogProfileSha256')
  with self.assertRaisesRegex(ValueError,'REOPEN_REQUIRES_ALL_INPUT_BINDINGS'):self.run_pipeline(self.record(),p)
class DiagnosticV2Tests(unittest.TestCase):
 def raw(self,stage=0,bc=1600,ec=1600,count=3,free=0,version=123,visited=1):
  raw=bytearray((P/'valid.bin').read_bytes());struct.pack_into('<II',raw,0,208,2);struct.pack_into('<I',raw,112,0)
  raw.extend(struct.pack('<IIQQiiII',1,stage,bc,ec,count,free,version,visited));return raw
 def test_v1_raw_remains_decodable_without_new_metadata(self):
  v=g.decode_raw((P/'valid.bin').read_bytes(),**ARGS);self.assertTrue(v['bothFalseProven']);self.assertEqual(v['guardAbiVersion'],1);self.assertIsNone(v['modeDictionaryDiagnostic'])
 def test_v2_large_capacity_lookup_not_full_dictionary(self):
  v=g.decode_raw(bytes(self.raw()),**ARGS);self.assertTrue(v['bothFalseProven']);self.assertEqual(v['guardAbiVersion'],2);self.assertTrue(v['modeLookup']['complete']);self.assertFalse(v['modeLookup']['fullDictionaryVerified']);self.assertEqual(v['modeDictionaryDiagnostic']['entryCapacity'],1600);self.assertEqual(v['modeDictionaryDiagnostic']['visitedEntries'],1)
 def test_uint64_capacity_limit_keeps_booleans_unknown(self):
  r=self.raw(2,0x100000001,0x200000005,7,2,123,0);struct.pack_into('<6I',r,8,5,7,0,0,3,0);struct.pack_into('<II',r,140,0,0)
  v=g.decode_raw(bytes(r),**ARGS);self.assertTrue(v['receiptValid']);self.assertFalse(v['bothFalseProven']);self.assertEqual(v['confirmation'],'unknown');self.assertEqual(v['modeDictionaryDiagnostic']['bucketCapacity'],0x100000001);self.assertFalse(v['modeDictionaryDiagnostic']['stabilityVerified'])
 def test_negative_metadata_is_signed_and_unknown(self):
  r=self.raw(3,3,3,-2,-7,17,0);struct.pack_into('<6I',r,8,4,7,0,0,3,0);struct.pack_into('<II',r,140,0,0)
  v=g.decode_raw(bytes(r),**ARGS);self.assertTrue(v['receiptValid']);self.assertEqual(v['modeDictionaryDiagnostic']['count'],-2);self.assertEqual(v['modeDictionaryDiagnostic']['freeCount'],-7);self.assertFalse(v['bothFalseProven'])
 def test_invalid_diagnostic_and_visit_count_refused(self):
  for off,value in ((168,2),(172,99),(204,513),(204,0)):
   r=self.raw();struct.pack_into('<I',r,off,value);v=g.decode_raw(bytes(r),**ARGS);self.assertFalse(v['receiptValid']);self.assertFalse(v['bothFalseProven'])
 def test_complete_cannot_omit_observed_metadata(self):
  r=self.raw();r[168:]=bytes(40);v=g.decode_raw(bytes(r),**ARGS);self.assertFalse(v['receiptValid']);self.assertFalse(v['bothFalseProven'])
 def test_complete_requires_valid_capacity_and_count_metadata(self):
  for bc,ec,count,free in ((0,1600,3,0),(1600,0x80000000,3,0),(1600,1600,1601,0),(1600,1600,3,4)):
   v=g.decode_raw(bytes(self.raw(bc=bc,ec=ec,count=count,free=free)),**ARGS);self.assertFalse(v['receiptValid']);self.assertFalse(v['bothFalseProven'])
 def test_changed_v2_size_version_refused(self):
  for size,version in ((168,2),(208,1),(208,3)):
   r=self.raw();struct.pack_into('<II',r,0,size,version)
   with self.assertRaises(ValueError):g.decode_raw(bytes(r),**ARGS)
class FixtureLevelBindingTests(unittest.TestCase):
 """Every synthetic receipt vector must carry the level the reviewed profile pins.

  The profile sha256 (``g.PROFILE_SHA256``) and the generated header sha256 are frozen
  in the decoder, so a re-pinned ``expectedLevelId`` cannot be reverted here -- the
  vectors are what has to follow.  Without this test a re-pin silently turns the whole
  decode suite red with a generic ``receiptValid=False``.
 """
 def test_every_fixture_receipt_binds_the_profile_level(self):
  level=g.load_profile()['expectedLevelId']
  seen=[]
  for path in sorted(P.glob('*.bin')):
   seen.append(path.name)
   self.assertEqual(struct.unpack_from('<I',path.read_bytes(),88)[0],level,path.name)
  self.assertEqual(seen,['cache_null.bin','confirmation_true.bin','partial_scheduler.bin','unavailable_scheduler.bin','valid.bin'])
 def test_fixtures_are_synthetic_vectors_not_captures(self):
  # 0x12345678 / 0x01020304 style fillers: these files are hand-built ABI vectors,
  # so aligning their declared level to the reviewed profile edits test data, not evidence.
  for path in sorted(P.glob('*.bin')):
   self.assertEqual(struct.unpack_from('<I',path.read_bytes(),96)[0],0x12345678,path.name)
if __name__=='__main__':unittest.main()
