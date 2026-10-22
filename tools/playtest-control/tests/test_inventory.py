"""Raw container / ownership / delta evidence, offline only."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import inventory_contract as c,inventory_build as b,inventory_receipt as receipt,inventory_diff as diff
import test_control as control

def card():
    p=control.card();p.update(mode='inventory-state',pageStart=0);return p
def context():
    r={k:0 for k in c.CONTEXT_POINTERS+c.CONTEXT_NUMBERS}
    for i,key in enumerate(c.CONTEXT_POINTERS):r[key]=0x20000+i*256
    r.update(avatar=0x10007,avatarId=7,avatarConfigId=10001,moduleCapacity=2,totalCount=2,totalCapacity=2,totalVersion=4,slotCount=3,slotCapacity=3,slotVersion=8,bagCapacity=3,bagOccupied=2,generation=23,generationCapacity=2,generationIndex=1,templateKey=(99<<32)|5)
    raw=bytearray(c.CONTEXT_SIZE);struct.pack_into('<14Q16I',raw,0,*(r[k] for k in c.CONTEXT_POINTERS+c.CONTEXT_NUMBERS));struct.pack_into('<Q',raw,176+0x18,r['moduleEntries']);struct.pack_into('<Q',raw,240+0x20,r['generationEntries']);return raw,r
def row(source,index):
    if source=='totals':v=(0x70000+index*256,0,((1115684865+index)<<32)|13,25 if index==0 else 9,index,0,0,0)
    elif index==2:v=(0x80000+index*256,0,0,0,index,0,0,0)
    else:v=(0x80000+index*256,0x90000+index*256,(1107296258<<32)|12,3+index,index,100+index,1,0)
    return struct.pack('<4Q4I',*v)
def raw():
    data=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=5,stage=3,operation=14,resourcesReleased=1,contextStable=1,samplesStable=1,totalCaptured=2,slotCaptured=3)
    ctx,r=context();struct.pack_into('<16I4Q',data,0,*(h[k] for k in c.HEADER),*(r[k] for k in c.POINTERS));data[c.CONTROL_OFFSET:c.CONTEXT_OFFSET]=control.raw();data[c.CONTEXT_OFFSET:c.ROWS_OFFSET]=ctx*2
    for i,source in enumerate(('totals','totals','slots','slots')):
        for j in range(2 if source=='totals' else 3):at=c.ROWS_OFFSET+i*c.LIMIT*c.ROW_SIZE+j*c.ROW_SIZE;data[at:at+c.ROW_SIZE]=row(source,j)
    return data
def head(data,**changes):
    for key,value in changes.items():struct.pack_into('<I',data,c.HEADER.index(key)*4,value)
def ctxchange(data,key,value,samples=(0,1)):
    index=(c.CONTEXT_POINTERS+c.CONTEXT_NUMBERS).index(key);fmt,offset=('Q',index*8) if index<14 else ('I',112+(index-14)*4)
    for sample in samples:struct.pack_into('<'+fmt,data,c.CONTEXT_OFFSET+sample*c.CONTEXT_SIZE+offset,value)
def change(data,key,value,source='slots',index=0,samples=(0,1)):
    n=c.ROW_FIELDS.index(key);fmt,off=('Q',n*8) if n<4 else ('I',32+(n-4)*4)
    for sample in samples:struct.pack_into('<'+fmt,data,c.ROWS_OFFSET+((2 if source=='slots' else 0)+sample)*c.LIMIT*c.ROW_SIZE+index*c.ROW_SIZE+off,value)

class BinaryTests(unittest.TestCase):
    def refuse(self,mutator,pattern):
        data=raw();mutator(data)
        with self.assertRaisesRegex(ValueError,pattern):c.parse(data)
    def test_current_counts(self):
        r=c.interpretation(c.parse(raw()),card());self.assertTrue(r['inventoryComplete']);self.assertEqual(r['physicalItemCounts'][0]['quantity'],'7');self.assertEqual(r['paymentResourceCounts'][0]['quantity'],'25');self.assertFalse(r['gameplayEffectVerified']);self.assertFalse(r['naturalInteractionVerified'])
    def test_unsigned_precision(self):
        data=raw();change(data,'quantity',2**64-1,source='totals');self.assertEqual(c.interpretation(c.parse(data),card())['paymentResourceCounts'][0]['quantity'],str(2**64-1))
    def test_length(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(bytes(20))
    def test_wrong_version(self):self.refuse(lambda d:head(d,version=4),'VERSION')
    def test_wrong_operation(self):self.refuse(lambda d:head(d,operation=13),'VERSION')
    def test_mutating_header(self):self.refuse(lambda d:head(d,nativeCalls=1),'READONLY')
    def test_reserved(self):self.refuse(lambda d:head(d,reserved0=1),'READONLY')
    def test_count_overflow(self):self.refuse(lambda d:head(d,totalCaptured=4097),'LIMITS')
    def test_wrong_avatar(self):self.refuse(lambda d:ctxchange(d,'avatarId',8),'AVATAR_BINDING')
    def test_no_owner(self):self.refuse(lambda d:ctxchange(d,'module',0),'OWNER_IDENTITY')
    def test_zero_template_uninitialized(self):self.refuse(lambda d:ctxchange(d,'templateKey',0),'OWNER_IDENTITY')
    def test_missing_slots_incomplete(self):self.refuse(lambda d:ctxchange(d,'slotCount',2),'LIMITS')
    def test_module_capacity_bound(self):self.refuse(lambda d:ctxchange(d,'moduleCapacity',1025),'LIMITS')
    def test_generation_capacity_bound(self):self.refuse(lambda d:ctxchange(d,'generationCapacity',65537),'LIMITS')
    def test_generation_index_bound(self):self.refuse(lambda d:ctxchange(d,'generationIndex',2),'LIMITS')
    def test_header_pointer_mismatch(self):self.refuse(lambda d:ctxchange(d,'generationEntries',123),'HEADER_POINTERS')
    def test_occupied_mismatch(self):self.refuse(lambda d:ctxchange(d,'bagOccupied',1),'OCCUPIED_COUNT')
    def test_changed_version_not_hidden(self):self.refuse(lambda d:ctxchange(d,'totalVersion',8,samples=(1,)),'CONTEXT_STABILITY')
    def test_unstable_context_not_interpreted(self):
        data=raw();ctxchange(data,'generation',24,samples=(1,));head(data,status=2,contextStable=0,samplesStable=0)
        with self.assertRaisesRegex(ValueError,'UNBOUND_OR_UNSTABLE'):c.interpretation(c.parse(data),card())
    def test_duplicate_resource(self):self.refuse(lambda d:change(d,'key',(1115684865<<32)|13,source='totals',index=1),'DUPLICATE_RESOURCE')
    def test_item_instance_duplicate(self):self.refuse(lambda d:change(d,'instanceId',100,index=1),'DUPLICATE_ITEM')
    def test_item_object_duplicate(self):self.refuse(lambda d:change(d,'item',0x90000,index=1),'DUPLICATE_ITEM')
    def test_empty_slot_cannot_claim_quantity(self):self.refuse(lambda d:change(d,'quantity',1,index=2),'EMPTY_SLOT')
    def test_physical_count_uint32(self):self.refuse(lambda d:change(d,'quantity',2**32),'ITEM_ROW')
    def test_item_kind_unknown_not_success(self):self.refuse(lambda d:change(d,'itemKind',3),'ITEM_ROW')
    def test_wrong_index(self):self.refuse(lambda d:change(d,'index',2),'ROW_IDENTITY')
    def test_changed_quantity_not_hidden(self):self.refuse(lambda d:change(d,'quantity',4,samples=(1,)),'SAMPLE_STABILITY')
    def test_unknown_partial_no_success(self):
        data=raw();head(data,status=1,stage=2,samplesStable=0,contextStable=0);ctxchange(data,'status',1);o=c.parse(data)
        with self.assertRaisesRegex(ValueError,'UNBOUND_OR_UNSTABLE'):c.interpretation(o,card())
    def test_unused_rows_rejected(self):self.refuse(lambda d:d.__setitem__(-1,1),'UNUSED_ROW')
    def test_wrong_trial_token(self):
        p=card();p['binding']['token']=88
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(raw()),p)
    def test_editor_avatar_not_trial(self):
        data=raw();data[c.CONTROL_OFFSET:c.CONTEXT_OFFSET]=control.raw(playing=False)
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(data),card())
    def test_missing_ancestor_not_trial(self):
        p=card();p['lineage']['attemptedOperations']=[]
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(raw()),p)

class DifferenceTests(unittest.TestCase):
    def setUp(self):self.a=c.interpretation(c.parse(raw()),card());self.z=json.loads(json.dumps(self.a));self.query=[dict(source='slots',configId=1107296258)]
    def test_actual_delta(self):self.z['physicalItemCounts'][0]['quantity']='5';self.assertEqual(diff.quantities(self.a,self.z,self.query)[0]['delta'],'-2')
    def test_currency_resource_delta(self):self.z['paymentResourceCounts'][0]['quantity']='35';self.assertEqual(diff.quantities(self.a,self.z,[dict(source='payment-resources',configId=1115684865)])[0]['delta'],'10')
    def test_new_item_previous_complete_zero(self):self.a['physicalItemCounts']=[];self.assertEqual(diff.quantities(self.a,self.z,self.query)[0]['before'],'0')
    def test_removed_item_complete_zero(self):self.z['physicalItemCounts']=[];self.assertEqual(diff.quantities(self.a,self.z,self.query)[0]['after'],'0')
    def test_unknown_type_cannot_guess_absent(self):
        with self.assertRaisesRegex(ValueError,'TYPE_REQUIRED'):diff.quantities(self.a,self.z,[dict(source='slots',configId=999)])
    def test_explicit_key_absence_on_complete_snapshots(self):self.assertEqual(diff.quantities(self.a,self.z,[dict(source='slots',configId=999,resourceType=12)])[0]['delta'],'0')
    def test_incomplete_not_zero(self):
        self.a['inventoryComplete']=False
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):diff.quantities(self.a,self.z,self.query)
    def test_wrong_source(self):
        with self.assertRaisesRegex(ValueError,'QUERY_ID'):diff.quantities(self.a,self.z,[dict(source='static-template',configId=999)])
    def test_boolean_id(self):
        with self.assertRaisesRegex(ValueError,'QUERY_ID'):diff.quantities(self.a,self.z,[dict(source='slots',configId=True)])
    def test_duplicate_queries(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_QUERY'):diff.quantities(self.a,self.z,self.query*2)
    def test_ambiguous_type(self):
        self.z['physicalItemCounts'].append(dict(configId=1107296258,resourceType=99,quantity='1'))
        with self.assertRaisesRegex(ValueError,'TYPE_REQUIRED'):diff.quantities(self.a,self.z,self.query)
    def test_query_bound(self):
        with self.assertRaisesRegex(ValueError,'QUERY_LIMIT'):diff.quantities(self.a,self.z,self.query*129)


class ComparisonBindingTests(unittest.TestCase):
    def setUp(self):
        self.a=c.interpretation(c.parse(raw()),card());self.a.update(ok=True,cleanupVerified=True,outcomeUncertain=False);self.z=json.loads(json.dumps(self.a))
        self.ac=dict(kind='playtest-control-prepared-v6',session={'pid':1},targetLevelId=1843,binding={'token':7},lineage={'rootRun':'entry'})
        self.zc=json.loads(json.dumps(self.ac));self.times=[dict(startedUtc='2026-10-17T01:00:00+00:00',finishedUtc='2026-10-17T01:00:01+00:00'),dict(startedUtc='2026-10-17T01:00:02+00:00',finishedUtc='2026-10-17T01:00:03+00:00')]
    def compare(self):
        with patch.object(diff,'manifest',side_effect=[(ROOT/'a',self.ac,{}),(ROOT/'z',self.zc,{})]),patch.object(diff,'decode',side_effect=[self.a,self.z]),patch.object(diff,'read',side_effect=self.times),patch.object(diff,'sha',return_value='rawhash'):
            return diff.compare('a','z',[dict(source='slots',configId=1107296258)])
    def test_complete_bound_comparison(self):self.assertFalse(self.compare()['gameplayEffectVerified'])
    def test_changed_session(self):
        self.zc['session']['pid']=2
        with self.assertRaisesRegex(ValueError,'TRIAL_CHANGED'):self.compare()
    def test_changed_token(self):
        self.zc['binding']['token']=8
        with self.assertRaisesRegex(ValueError,'TRIAL_CHANGED'):self.compare()
    def test_changed_trial_root(self):
        self.zc['lineage']['rootRun']='other'
        with self.assertRaisesRegex(ValueError,'TRIAL_CHANGED'):self.compare()
    def test_owner_generation_changes(self):
        self.z['runtimeOwner']['ownerGeneration']=24
        with self.assertRaisesRegex(ValueError,'OWNER_CHANGED'):self.compare()
    def test_changed_bag_object(self):
        self.z['runtimeOwner']['bag']=999
        with self.assertRaisesRegex(ValueError,'OWNER_CHANGED'):self.compare()
    def test_failed_second_receipt(self):
        self.z['ok']=False
        with self.assertRaisesRegex(ValueError,'UNVERIFIED'):self.compare()
    def test_uncertain_cleanup(self):
        self.z['outcomeUncertain']=True
        with self.assertRaisesRegex(ValueError,'UNVERIFIED'):self.compare()
    def test_reversed_order(self):
        self.times.reverse()
        with self.assertRaisesRegex(ValueError,'ORDER'):self.compare()
    def test_naive_time_not_order_proof(self):
        self.times[0]['startedUtc']='2026-10-17T01:00:00'
        with self.assertRaisesRegex(ValueError,'ORDER'):self.compare()

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=folder);self.run=Path(self.temp.name);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_INVENTORY',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_INVENTORY',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
        for name,value in [('exit.json',self.exit),('stdout.jsonl',r)]:(self.run/name).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipt.decode_bound(self.run,self.card)
    def test_card_bound_success(self):self.assertTrue(self.decode()['ok'])
    def test_wrong_nonce(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptNonce='100')
    def test_wrong_protocol(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptProtocol=21)
    def test_wrong_pid(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_TARGET'):self.decode(pid=124)
    def test_binary_hash_mismatch(self):
        with self.assertRaisesRegex(ValueError,'BINARY_RECEIPT'):self.decode(acceptanceSha256='0'*64)
    def test_page_mismatch(self):
        self.card['pageStart']=1
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):self.decode()
    def test_refusal_clean(self):self.exit.update(executed=False,error='SOURCE_CHANGED');self.assertTrue(self.decode()['safeToRelease'])
    def test_refusal_cannot_hide_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_unhook_failure_is_uncertain(self):self.assertTrue(self.decode(unhooked=False)['outcomeUncertain'])
    def test_active_callback_is_uncertain(self):self.assertFalse(self.decode(activeCallbacks=1)['safeToRelease'])
    def test_exception_is_uncertain(self):head(self.data,status=2,seh=0xc0000005);self.assertTrue(self.decode()['outcomeUncertain'])
    def test_partial_failed_card_clean_but_not_ok(self):
        head(self.data,status=1,stage=2,samplesStable=0);out=self.decode(ok=False);self.assertFalse(out['ok']);self.assertTrue(out['safeToRelease']);json.dumps(out,allow_nan=False)
    def test_embedded_exception_is_uncertain(self):
        struct.pack_into('<I',self.data,c.CONTROL_OFFSET+12,0xc0000005);self.assertFalse(self.decode()['safeToRelease'])
    def test_anchor_changes_refused(self):
        p=dict(anchorRun='anchor',session={},targetLevelId=1843,lineage={'original':1},binding={})
        with patch.object(b.c,'previous',return_value=({},{})),self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):b.revalidate_proofs(p)

class CandidateTests(unittest.TestCase):
    def test_generated_fixed_readonly_candidate(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            run=Path(temporary);b.copy_sources(run);protocol=(run/'candidate-source/native/hook_receipt_protocol.h').read_text();hook=(run/'candidate-source/native/hook_receipt.cpp').read_text();probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text()
            self.assertIn('InventoryReceipt acceptance;',protocol);self.assertIn('ExecuteInventory(&receipt->acceptance);',hook);self.assertIn('FIXED_PLAYTEST_INVENTORY',probe);self.assertNotIn('*receipt = {};',probe)
    def test_compile_card_is_not_launchable(self):
        p=dict(mode='inventory-state',pageStart=0,compileOnly=True,launchable=True,lineage={},binding={},anchorRun=None)
        with self.assertRaisesRegex(ValueError,'COMPILE_ONLY'):b.validate_card(p)
    def test_exited_trial_rejected(self):
        p=dict(mode='inventory-state',pageStart=0,compileOnly=False,anchorRun='anchor',lineage=dict(ancestors=[dict(run='anchor')],attemptedOperations=['enter-start','exit-request']))
        with self.assertRaisesRegex(ValueError,'ENTERED_LINEAGE'):b.validate_card(p)
    def test_boolean_page_rejected(self):
        with self.assertRaisesRegex(ValueError,'INVENTORY_PLAN'):b.validate_card(dict(mode='inventory-state',pageStart=True))

if __name__=='__main__':unittest.main()
