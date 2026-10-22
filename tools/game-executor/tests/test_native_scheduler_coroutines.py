from pathlib import Path
import sys,struct,unittest,copy,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_scheduler_coroutines as api
import native_profiles as profiles
class SchedulerTests(unittest.TestCase):
 def setUp(self):
  self.p=api.load_profile();self.base=0x140000000;self.cls=0x50000;self.owner=0x60000;self.level=self.p['expectedLevelId']
  self.ctx={'status':{'value':0},'levelObservation':{'verified':True,'levelId':self.level},'pointers':{'moduleBase':hex(self.base),'global':hex(0x20000)},'lifecycleType':{'ok':True,'allocatedClassToCandidateFunctionVerified':True,'pointers':{'classPointer':hex(self.cls)},'counts':{'slotCountBefore':9}}}
 def fixture(self,kind=7,state=4):
  r=bytearray(api.SCHEDULER_COROUTINES_BYTES);struct.pack_into('<4I',r,0,len(r),1,0,255);struct.pack_into('<10Q',r,16,self.base,0x20000,0x30000,0x40000,0x41000,self.owner,self.cls,self.base+0x5826620,0xa0000,0xb0000)
  target=int(kind==7);null=int(kind==0);unavailable=int(kind in (1,2,3,4));other=int(kind in (5,6))
  struct.pack_into('<16I',r,96,self.level,1,1,2,3,3,1,target,null,unavailable,other,20000,150,9,0,0)
  handle=0 if kind==0 else 0x70000;holder=0 if kind<2 else 0x71000;iterator=0 if kind in (0,1,4) else 0x72000
  klass=0 if kind<5 else 0x73000 if kind==5 else self.cls
  owner=0 if kind<6 else 0x80000 if kind==6 else self.owner
  refkind=0 if kind<2 else 1 if kind==3 else 2
  released=1 if kind==2 else 0
  count=0 if kind<2 else 1;retained=count;rowstate=state if kind>=6 else 0;current=0x90000 if kind>=6 else 0
  struct.pack_into('<9QIIIiIIiI',r,160,handle,0 if kind==0 else 0xb0000,holder,iterator,klass,owner,current,0,0,0,kind,refkind,count,retained,released,rowstate,0);return r
 def decode(self,r,**patch):return api.decode({'schedulerCoroutinesHex':r.hex(),'schedulerCoroutinesBytes':len(r),'schedulerCoroutinesStatus':0,**patch},self.ctx,self.p)
 def test_target_is_not_completion_or_attribution(self):
  x=self.decode(self.fixture());self.assertTrue(x['ok']);self.assertTrue(x['instanceObserved']);self.assertTrue(x['rows'][0]['stageObserved']);self.assertFalse(x['completionVerified']);self.assertFalse(x['requestAttributionVerified'])
 def test_all_dispositions(self):
  for kind in range(8):
   x=self.decode(self.fixture(kind));self.assertTrue(x['ok'],x['reasons']);self.assertEqual(x['instanceObserved'],kind==7)
 def test_unknown_and_released_do_not_require_iterator_pointer(self):
  for kind in (2,3):
   r=self.fixture(kind);struct.pack_into('<Q',r,184,0xffffffffffffffff);x=self.decode(r);self.assertTrue(x['ok']);self.assertFalse(x['allListedReferencesInterpretable'])
 def test_negative_and_unexpected_state_remain_unknown(self):
  for state in (-2147483648,-1,8,2147483647):
   x=self.decode(self.fixture(state=state));self.assertTrue(x['ok']);self.assertFalse(x['rows'][0]['stageObserved']);self.assertFalse(x['completionVerified'])
 def test_empty_array_sample(self):
  r=self.fixture();r[160:]=bytes(len(r)-160);struct.pack_into('<16I',r,96,self.level,0,0,0,3,3,0,0,0,0,0,20000,150,9,0,0);x=self.decode(r);self.assertTrue(x['ok']);self.assertFalse(x['instanceObserved'])
 def test_bad_abi(self):
  for r in (b'',self.fixture()[:-1],self.fixture()+b'\0'):
   with self.assertRaises(profiles.ProfileError):self.decode(r)
  r=self.fixture();struct.pack_into('<I',r,4,2)
  with self.assertRaises(profiles.ProfileError):self.decode(r)
 def test_failed_status(self):
  for status in range(1,10):
   r=self.fixture();struct.pack_into('<I',r,8,status);self.assertFalse(self.decode(r)['ok'])
 def test_each_flag_required(self):
  for bit in (1,2,4,8,16,32,64,128):
   r=self.fixture();struct.pack_into('<I',r,12,255&~bit);self.assertFalse(self.decode(r)['ok'])
 def test_counts_versions_budget_summary(self):
  for offset,value in ((96,1),(100,2),(104,2),(108,0),(108,0x80000000),(116,4),(124,0),(128,1),(132,1),(136,1),(140,0),(140,1048577),(144,4097),(148,8),(152,1),(156,1)):
   r=self.fixture();struct.pack_into('<I',r,offset,value)
   with self.subTest(offset=offset):self.assertFalse(self.decode(r)['ok'])
 def test_root_pointer_and_classslot(self):
  for off in range(16,96,8):
   r=self.fixture();struct.pack_into('<Q',r,off,1);self.assertFalse(self.decode(r)['ok'])
 def test_unused_rows(self):
  r=self.fixture();r[-1]=1;self.assertFalse(self.decode(r)['ok'])
 def test_row_index_reserved_classification(self):
  for off,value in ((232,1),(236,5),(252,256),(260,1)):
   r=self.fixture();struct.pack_into('<I',r,off,value);self.assertFalse(self.decode(r)['ok'])
 def test_unavailable_dereference_refused(self):
  for kind in (2,3,4):
   r=self.fixture(kind);struct.pack_into('<Q',r,192,self.cls);self.assertFalse(self.decode(r)['ok'])
 def test_other_class_does_not_claim_owner(self):
  r=self.fixture(5);struct.pack_into('<Q',r,200,self.owner);self.assertFalse(self.decode(r)['ok'])
 def test_current_binding_required(self):
  self.ctx['lifecycleType']['ok']=False;self.assertFalse(self.decode(self.fixture())['ok'])
 def test_context_identity_required(self):
  self.ctx['pointers']['global']='0x90000';self.assertFalse(self.decode(self.fixture())['ok'])
 def test_null_fields_invariant(self):
  for kind in (0,1):
   r=self.fixture(kind);struct.pack_into('<Q',r,224,1);self.assertFalse(self.decode(r)['ok'])
 def test_unavailable_holder_state_never_dereferenced(self):
  for offset,value in ((244,0),(244,0xffffffff),(248,0),(248,2)):
   r=self.fixture(4);struct.pack_into('<I',r,offset,value);struct.pack_into('<I',r,236,8)
   x=self.decode(r);self.assertTrue(x['ok'],x['reasons']);self.assertFalse(x['allListedReferencesInterpretable'])
  r=self.fixture(4);struct.pack_into('<Q',r,184,0x71000);struct.pack_into('<I',r,236,8)
  self.assertTrue(self.decode(r)['ok'])
 def test_wrong_handle_class_is_unavailable(self):
  r=self.fixture(1);struct.pack_into('<Q',r,168,1);struct.pack_into('<I',r,236,9)
  x=self.decode(r);self.assertTrue(x['ok'],x['reasons']);self.assertFalse(x['instanceObserved']);self.assertFalse(x['allListedReferencesInterpretable'])
  struct.pack_into('<Q',r,176,0x71000);self.assertFalse(self.decode(r)['ok'])
 def test_reference_policy_is_opaque_but_stable(self):
  r=self.fixture();struct.pack_into('<II',r,152,255,255);self.assertTrue(self.decode(r)['ok'])
  struct.pack_into('<II',r,152,256,256);self.assertFalse(self.decode(r)['ok'])
 def test_duplicate_matches_report_unique_separately(self):
  r=self.fixture();r[264:368]=r[160:264];struct.pack_into('<I',r,336,1)
  for off in (100,104,120,124):struct.pack_into('<I',r,off,2)
  x=self.decode(r);self.assertTrue(x['ok'],x['reasons']);self.assertEqual(x['targetMatchRows'],2);self.assertEqual(x['uniqueTargetIterators'],1);self.assertEqual(x['duplicateNonNullHandles'],1);self.assertEqual(x['duplicateTargetIteratorRows'],1)
 def failure_bounds(self,count=129,capacity=1600,saturated=False):
  r=self.fixture();r[160:]=bytes(len(r)-160);struct.pack_into('<II',r,8,5,263|(512 if saturated else 0))
  struct.pack_into('<16I',r,96,self.level,count&0xffffffff,0,capacity,11,0,0,0,0,0,0,7872,47,9,0,0)
  return r
 def test_failure_bounds_remain_unstable_and_never_ok(self):
  r=self.failure_bounds();x=self.decode(r,schedulerCoroutinesStatus=5);self.assertFalse(x['ok']);self.assertFalse(x['sampleStable']);self.assertFalse(x['instanceObserved'])
  b=x['observedBounds'];self.assertEqual((b['listCount'],b['capacity'],b['listVersion']),(129,1600,11));self.assertFalse(b['capacitySaturated']);self.assertFalse(b['stabilityVerified']);self.assertFalse(b['arrayEntriesRead'])
 def test_failure_bounds_negative_count_preserves_signed_value(self):
  x=self.decode(self.failure_bounds(-1,128),schedulerCoroutinesStatus=5);self.assertFalse(x['ok']);self.assertEqual(x['observedBounds']['listCount'],-1)
 def test_failure_bounds_uint64_overflow_is_explicit_saturation(self):
  x=self.decode(self.failure_bounds(3,0xffffffff,True),schedulerCoroutinesStatus=5);self.assertFalse(x['ok']);self.assertIsNone(x['observedBounds']['capacity']);self.assertTrue(x['observedBounds']['capacitySaturated']);self.assertEqual(x['observedBounds']['capacityLowerBound'],0x100000000)
 def test_failure_bounds_require_exact_failed_phase_and_no_rows(self):
  cases=((8,0),(12,255),(12,271),(12,775),(120,1),(104,1),(116,1),(156,1))
  for offset,value in cases:
   r=self.failure_bounds();struct.pack_into('<I',r,offset,value);x=self.decode(r,schedulerCoroutinesStatus=5);self.assertFalse(x['ok']);self.assertIsNone(x['observedBounds'])
  r=self.failure_bounds(3,128);x=self.decode(r,schedulerCoroutinesStatus=5);self.assertIsNone(x['observedBounds'])
 def test_original_limit_receipt_has_no_fabricated_bounds(self):
  r=self.failure_bounds();struct.pack_into('<I',r,12,7);x=self.decode(r,schedulerCoroutinesStatus=5);self.assertFalse(x['ok']);self.assertIsNone(x['observedBounds'])
 def logical_rows(self,count,capacity):
  r=self.fixture();one=bytes(r[160:264]);r[160:]=bytes(len(r)-160)
  for i in range(count):r[160+i*104:264+i*104]=one;struct.pack_into('<I',r,232+i*104,i)
  struct.pack_into('<16I',r,96,self.level,count,count,capacity,104634,104634,count,count,0,0,0,20000,150,9,0,0)
  return r
 def test_logical_count_three_with_retained_capacity_1600(self):
  x=self.decode(self.logical_rows(3,1600));self.assertTrue(x['ok'],x['reasons']);self.assertEqual(len(x['rows']),3);self.assertTrue(x['logicalListComplete']);self.assertFalse(x['unusedCapacityRead']);self.assertFalse(x['completionVerified']);self.assertEqual(x['counts']['listCapacity'],1600)
 def test_empty_logical_list_with_retained_capacity(self):
  x=self.decode(self.logical_rows(0,1600));self.assertTrue(x['ok'],x['reasons']);self.assertTrue(x['logicalListComplete']);self.assertFalse(x['unusedCapacityRead']);self.assertFalse(x['instanceObserved']);self.assertFalse(x['completionVerified']);self.assertFalse(x['requestAttributionVerified'])
 def test_exact_128_rows_do_not_scale_with_capacity(self):
  x=self.decode(self.logical_rows(128,0x7fffffff));self.assertTrue(x['ok'],x['reasons']);self.assertEqual(len(x['rows']),128);self.assertTrue(x['logicalListComplete']);self.assertFalse(x['unusedCapacityRead'])
 def test_count_exceeding_capacity_or_signed_capacity_limit_refused(self):
  for count,capacity in ((3,2),(0,0x80000000),(3,0xffffffff)):
   x=self.decode(self.logical_rows(count,capacity));self.assertFalse(x['ok']);self.assertFalse(x['logicalListComplete'])
  r=self.logical_rows(128,1600);struct.pack_into('<I',r,120,129)
  with self.assertRaises(profiles.ProfileError):self.decode(r)
 def test_failure_does_not_claim_complete_logical_list(self):
  r=self.logical_rows(3,1600);struct.pack_into('<I',r,116,104635);x=self.decode(r);self.assertFalse(x['ok']);self.assertFalse(x['logicalListComplete']);self.assertFalse(x['completionVerified'])
 def test_profile(self):self.assertEqual(profiles.sha256(api.PROFILE),api.PROFILE_SHA256)
 def test_header(self):
  with tempfile.TemporaryDirectory() as d:
   api.append_header(d,self.p);s=(Path(d)/'target_config.h').read_text();self.assertIn('HR_READ_SCHEDULER_COROUTINES 1ULL',s);self.assertIn('GSC_HOLDER_RELEASED_OFFSET 0x50ULL',s)
class SchedulerIntegrationTests(unittest.TestCase):
 def setUp(self):
  import build_readonly_profile as builder
  self.builder=builder
 def test_missing_lifecycle_refused_before_disk_or_compiler_access(self):
  from unittest.mock import patch
  with patch.object(profiles,'load_profile',side_effect=AssertionError('disk touched')), patch.object(self.builder.subprocess,'check_output',side_effect=AssertionError('compiler touched')):
   for call in (lambda:self.builder.prepare(scheduler_coroutines=True),lambda:self.builder.compile_probe(Path('.'),scheduler_coroutines=True)):
    with self.assertRaisesRegex(profiles.ProfileError,'SCHEDULER_REQUIRES_LIFECYCLE_TYPE'):call()
 def run_decode(self,prepared,record=None,scheduler_result=None,lifecycle_result=None):
  from unittest.mock import patch,Mock
  from contextlib import ExitStack
  decoder=Mock();decoder.read_probe.return_value=(record or {},'fixture');decoder.decode_snapshot.return_value={}
  documents={'prepared.json':prepared,'build-result.json':{'hashes':{}},'exit.json':{'executed':True,'exitCode':0,'error':None}}
  calls=[]
  def life(*args):calls.append('lifecycle');return lifecycle_result or {'ok':True,'reasons':[]}
  def scheduler(record,context,profile):
   calls.append('scheduler');self.assertIn('lifecycleType',context)
   return scheduler_result or {'ok':True,'reasons':[]}
  with ExitStack() as stack:
   stack.enter_context(patch.object(self.builder,'read_json',side_effect=lambda p:documents[p.name]))
   stack.enter_context(patch.object(self.builder,'write_json'))
   stack.enter_context(patch.object(self.builder,'load_decoder',return_value=decoder))
   stack.enter_context(patch.object(self.builder,'validate_receipt',return_value={'ok':True,'reasons':[]}))
   stack.enter_context(patch.object(self.builder.lifecycle_api,'decode',side_effect=life))
   stack.enter_context(patch.object(self.builder.scheduler_api,'decode',side_effect=scheduler))
   return self.builder.decode_run(Path('.')),calls
 def binding(self):
  return {'lifecycleTypeProfileSha256':self.builder.lifecycle_api.PROFILE_SHA256,'schedulerCoroutinesProfileSha256':api.PROFILE_SHA256,'schedulerCoroutinesDecoderSha256':profiles.sha256(Path(api.__file__))}
 def test_scheduler_decode_requires_fresh_type_first(self):
  result,calls=self.run_decode(self.binding());self.assertTrue(result['ok']);self.assertEqual(calls,['lifecycle','scheduler'])
 def test_failed_extension_cannot_be_promoted_by_transport(self):
  result,_=self.run_decode(self.binding(),scheduler_result={'ok':False,'reasons':['SCHEDULER_UNSTABLE']})
  self.assertFalse(result['ok']);self.assertIn('SCHEDULER_UNSTABLE',result['reasons'])
  result,_=self.run_decode(self.binding(),lifecycle_result={'ok':False,'reasons':['LIFECYCLE_UNSTABLE']})
  self.assertFalse(result['ok']);self.assertIn('LIFECYCLE_UNSTABLE',result['reasons'])
 def test_unbound_scheduler_status_bytes_or_hex_rejected(self):
  for key,value in (('schedulerCoroutinesStatus',0),('schedulerCoroutinesBytes',13472),('schedulerCoroutinesHex','')):
   result,calls=self.run_decode({},record={key:value});self.assertFalse(result['ok']);self.assertIn('UNBOUND_SCHEDULER_EXTENSION',result['reasons']);self.assertEqual(calls,[])
 def test_scheduler_profile_decoder_and_type_bindings_required(self):
  cases=(('lifecycleTypeProfileSha256',None,'SCHEDULER_REQUIRES_LIFECYCLE_BINDING'),('schedulerCoroutinesProfileSha256','changed','SCHEDULER_PROFILE_BINDING'),('schedulerCoroutinesDecoderSha256',None,'SCHEDULER_DECODER_BINDING'),('schedulerCoroutinesDecoderSha256','changed','SCHEDULER_DECODER_BINDING'))
  for key,value,reason in cases:
   prepared=self.binding()
   if value is None:prepared.pop(key)
   else:prepared[key]=value
   with self.assertRaisesRegex(profiles.ProfileError,reason):self.run_decode(prepared)
if __name__=='__main__':unittest.main(verbosity=2)
