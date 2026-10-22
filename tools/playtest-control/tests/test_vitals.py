"""Raw-vitals integrity and refusal tests. Run only after the unified gate."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import vitals_contract as c,vitals_build as b,vitals_receipt as receipt
import test_control as control
TABLE=bytes(range(256))*12
HP100=bytes.fromhex('00000000000000000000c8420000c842')
HP120=bytes.fromhex('00000000000000000000f0420000f042')

def card():
    p=control.card();p.update(mode='vitals-state',pageStart=0);return p
def row(monster=False):
    data=bytearray(c.ROW_SIZE)
    struct.pack_into('<4Q10I2f',data,0,0x20007 if monster else 0x10007,0x50000,0x60000,0x70000,9 if monster else 7,21010101 if monster else 10000001,2 if monster else 1,3,0,0,0,0 if monster else 1,0 if monster else 1,2 if monster else 0xffffffff,0. if monster else 100.,120.)
    data[80:96]=bytes(16) if monster else HP100;data[96:112]=HP120;return data
def raw():
    data=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=4,stage=3,operation=13,resourcesReleased=1,count=2,pageEnd=3,dictionaryStable=1,samplesStable=1)
    struct.pack_into('<16I4Q',data,0,*(h[k] for k in c.HEADER),0x30000,0x40000,0x80000,0x10007)
    data[c.CONTROL_OFFSET:c.CONTEXT_OFFSET]=control.raw()
    for at in (c.CONTEXT_OFFSET,c.CONTEXT_OFFSET+16):struct.pack_into('<4I',data,at,3,10,3,7)
    data[c.TABLE_OFFSET:c.ROWS_OFFSET]=TABLE*2
    for sample in range(2):
        at=c.ROWS_OFFSET+sample*c.ROW_CAPACITY*c.ROW_SIZE;data[at:at+c.ROW_SIZE]=row();data[at+c.ROW_SIZE:at+2*c.ROW_SIZE]=row(True)
    return data
def head(data,**changes):
    for key,value in changes.items():struct.pack_into('<I',data,c.HEADER.index(key)*4,value)
def change_row(data,field,value,index=0,samples=(0,1)):
    fields=c.ROW_POINTERS+c.ROW_NUMBERS+('currentHp','maxHp')
    i=fields.index(field);fmt,offset=('Q',i*8) if i<4 else ('I',32+(i-4)*4) if i<14 else ('f',72+(i-14)*4)
    for sample in samples:struct.pack_into('<'+fmt,data,c.ROWS_OFFSET+sample*c.ROW_CAPACITY*c.ROW_SIZE+index*c.ROW_SIZE+offset,value)

class CodecTests(unittest.TestCase):
    def test_fixed_current(self):self.assertEqual(c.decode_hp(HP100,TABLE),(0,100.))
    def test_fixed_max(self):self.assertEqual(c.decode_hp(HP120,TABLE),(0,120.))
    def test_nonzero_seed(self):self.assertEqual(c.decode_hp(bytes.fromhex('0c000000000000000c00c8420000c842'),TABLE),(0,100.))
    def test_signed_seed_remainder(self):self.assertEqual(c.decode_hp(bytes.fromhex('040000800400c8c20400c8c200000000'),TABLE),(0,100.))
    def test_empty_valid_encoding_is_zero(self):self.assertEqual(c.decode_hp(bytes(16),TABLE),(0,0.))
    def test_checksum_not_zero_health(self):self.assertEqual(c.decode_hp(HP100[:4]+b'\1'+HP100[5:],TABLE),(3,None))
    def test_negative_not_valid_health(self):self.assertEqual(c.decode_hp(bytes.fromhex('0000000000000000000080bf000080bf'),TABLE),(4,None))
    def test_nonfinite_not_valid_health(self):self.assertEqual(c.decode_hp(bytes.fromhex('00000000000000000000807f0000807f'),TABLE),(4,None))
    def test_table_size_refused(self):
        with self.assertRaisesRegex(ValueError,'HP_INPUT_SIZE'):c.decode_hp(HP100,TABLE[:-1])

class BinaryTests(unittest.TestCase):
    def test_bound_avatar_and_monster_vitals(self):
        out=c.interpretation(c.parse(raw()),card());self.assertEqual(out['localAvatarVitals']['currentHp'],100.);self.assertTrue(out['entities'][1]['dead']);self.assertTrue(out['monsterHealthVerified']);self.assertFalse(out['damageVerified']);self.assertFalse(out['inventoryQuantitiesVerified'])
    def test_json_serializable(self):json.dumps(c.parse(raw()),allow_nan=False)
    def test_monster_not_assumed_target_spawn(self):
        out=c.interpretation(c.parse(raw()),card());self.assertIsNone(out['entities'][1]['belongsToBoundTrial']);self.assertFalse(out['entities'][1]['configuredSpawnIdentityVerified'])
    def test_binary_size(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(b'')
    def test_version(self):
        data=raw();head(data,version=5)
        with self.assertRaisesRegex(ValueError,'VERSION'):c.parse(data)
    def test_native_call_counter_readonly(self):
        data=raw();head(data,nativeCalls=1)
        with self.assertRaisesRegex(ValueError,'READ_ONLY'):c.parse(data)
    def test_row_capacity(self):
        data=raw();head(data,count=130)
        with self.assertRaisesRegex(ValueError,'LIMITS'):c.parse(data)
    def test_unused_row_bytes(self):
        data=raw();data[-1]=1
        with self.assertRaisesRegex(ValueError,'UNUSED'):c.parse(data)
    def test_changed_dictionary_detected(self):
        data=raw();struct.pack_into('<I',data,c.CONTEXT_OFFSET+20,11)
        with self.assertRaisesRegex(ValueError,'DICTIONARY_STABILITY'):c.parse(data)
    def test_changed_dictionary_no_interpretation(self):
        data=raw();struct.pack_into('<I',data,c.CONTEXT_OFFSET+20,11);head(data,status=2,dictionaryStable=0)
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(data),card())
    def test_changed_sample_not_silently_accepted(self):
        data=raw();change_row(data,'configId',88,samples=(1,))
        with self.assertRaisesRegex(ValueError,'SAMPLE_STABILITY'):c.parse(data)
    def test_duplicate_id(self):
        data=raw();change_row(data,'id',7,index=1)
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):c.parse(data)
    def test_wrong_local_avatar(self):
        data=raw();change_row(data,'entity',0x10008)
        with self.assertRaisesRegex(ValueError,'LOCAL_AVATAR'):c.parse(data)
    def test_identity_missing(self):
        data=raw();change_row(data,'id',0)
        with self.assertRaisesRegex(ValueError,'ROW_IDENTITY'):c.parse(data)
    def test_page_entry_outside_page(self):
        data=raw();change_row(data,'entryIndex',3,index=1)
        with self.assertRaisesRegex(ValueError,'ROW_PAGE'):c.parse(data)
    def test_value_requires_encoded_agreement(self):
        data=raw();change_row(data,'currentHp',99.)
        with self.assertRaisesRegex(ValueError,'RAW_DECODE'):c.parse(data)
    def test_table_changed_not_stable(self):
        data=raw();data[c.TABLE_OFFSET+3072]=1
        with self.assertRaisesRegex(ValueError,'TABLE_STABILITY'):c.parse(data)
    def test_unknown_properties_not_health_or_zero(self):
        data=raw();change_row(data,'hpStatus',1);change_row(data,'component',0);change_row(data,'properties',0)
        out=c.interpretation(c.parse(data),card())['localAvatarVitals'];self.assertFalse(out['hpKnown']);self.assertIsNone(out['currentHp'])
    def test_lifecycle_not_loaded_is_unknown(self):
        data=raw();change_row(data,'flags',1);change_row(data,'lifeStatus',1)
        out=c.interpretation(c.parse(data),card())['localAvatarVitals'];self.assertIsNone(out['alive']);self.assertIsNone(out['dead']);self.assertEqual(out['lifeState'],'unknown')
    def test_recycled_not_dead(self):
        data=raw();change_row(data,'flags',11);change_row(data,'lifeStatus',1)
        out=c.interpretation(c.parse(data),card())['localAvatarVitals'];self.assertTrue(out['recycled']);self.assertIsNone(out['dead'])
    def test_false_lifecycle_claim_rejected(self):
        data=raw();change_row(data,'flags',7)
        with self.assertRaisesRegex(ValueError,'LIFECYCLE'):c.parse(data)
    def test_unknown_nonfinite_does_not_break_evidence_json(self):
        data=raw();change_row(data,'hpStatus',4);change_row(data,'currentHp',float('nan'))
        out=c.parse(data);json.dumps(out,allow_nan=False);self.assertIsNone(out['first'][0]['currentHp'])
    def test_partial_second_capture_preserved(self):
        data=raw();head(data,stage=2,status=1,samplesStable=0,dictionaryStable=0);data[c.ROWS_OFFSET+c.ROW_CAPACITY*c.ROW_SIZE:]=bytes(c.ROW_CAPACITY*c.ROW_SIZE)
        out=c.parse(data);self.assertIsNone(out['second'][0]);self.assertEqual(out['first'][0]['currentHp'],100.)
    def test_partial_table_capture_preserved(self):
        data=raw();head(data,stage=2,status=1);data[c.TABLE_OFFSET+3072:c.ROWS_OFFSET]=bytes(3072);data[c.ROWS_OFFSET+c.ROW_CAPACITY*c.ROW_SIZE:]=bytes(c.ROW_CAPACITY*c.ROW_SIZE);c.parse(data)
    def test_trial_token_is_not_inferred(self):
        p=card();p['binding']['token']=99
        with self.assertRaisesRegex(ValueError,'UNBOUND_TRIAL'):c.interpretation(c.parse(raw()),p)
    def test_editor_avatar_is_not_play(self):
        data=raw();data[c.CONTROL_OFFSET:c.CONTEXT_OFFSET]=control.raw(playing=False)
        with self.assertRaisesRegex(ValueError,'UNBOUND_TRIAL'):c.interpretation(c.parse(data),card())
    def test_missing_enter_ancestor(self):
        p=card();p['lineage']['attemptedOperations']=[]
        with self.assertRaisesRegex(ValueError,'UNBOUND_TRIAL'):c.interpretation(c.parse(raw()),p)

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=folder);self.run=Path(self.temp.name);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_VITALS',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_VITALS',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
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
        head(self.data,status=1,stage=2,samplesStable=0);self.data[c.ROWS_OFFSET+c.ROW_CAPACITY*c.ROW_SIZE:]=bytes(c.ROW_CAPACITY*c.ROW_SIZE);out=self.decode(ok=False);self.assertFalse(out['ok']);self.assertTrue(out['safeToRelease']);json.dumps(out,allow_nan=False)
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
            self.assertIn('VitalsReceipt acceptance;',protocol);self.assertIn('ExecuteVitals(&receipt->acceptance);',hook);self.assertIn('FIXED_PLAYTEST_VITALS',probe);self.assertNotIn('*receipt = {};',probe)
    def test_compile_card_is_not_launchable(self):
        p=dict(mode='vitals-state',pageStart=0,compileOnly=True,launchable=True,lineage={},binding={},anchorRun=None)
        with self.assertRaisesRegex(ValueError,'COMPILE_ONLY'):b.validate_card(p)
    def test_exited_trial_rejected(self):
        p=dict(mode='vitals-state',pageStart=0,compileOnly=False,anchorRun='anchor',lineage=dict(ancestors=[dict(run='anchor')],attemptedOperations=['enter-start','exit-request']))
        with self.assertRaisesRegex(ValueError,'ENTERED_LINEAGE'):b.validate_card(p)
    def test_boolean_page_rejected(self):
        with self.assertRaisesRegex(ValueError,'VITALS_PLAN'):b.validate_card(dict(mode='vitals-state',pageStart=True))

if __name__=='__main__':unittest.main()
