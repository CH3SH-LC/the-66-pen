"""v8 raw identity/option and conservative contact acceptance. Offline only."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import contact_contract as c,contact_build as b,contact_receipt as receipt
import test_control as control
BASE=0x140000000

def card():
    p=control.card();p.update(mode='contact-state',pageStart=0);return p

def row(local=False,id=9,index=2):
    return struct.pack('<2Q8I',0x10007 if local else 0x20000+id,0x50000,7 if local else id,10000001 if local else 21010101,1 if local else 2,3,0,int(local),0xffffffff if local else index,0)

def raw():
    data=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=7,stage=3,operation=17,resourcesReleased=1,count=2,pageEnd=3,stable=1)
    struct.pack_into('<12IQ',data,0,*(h[k] for k in c.HEADER),BASE);data[c.CONTROL_OFFSET:c.SAMPLES_OFFSET]=control.raw()
    s=bytearray(c.SAMPLE_SIZE);p={k:0x30000+i*0x1000 for i,k in enumerate(c.POINTERS)};n={k:0 for k in c.NUMBERS};n.update(entityCount=3,entityVersion=1,entityCapacity=3,avatarId=7,mapCount=2,mapCapacity=2,reverseCount=2,reverseCapacity=2,optionCount=1)
    struct.pack_into('<11Q12I',s,0,*(p[k] for k in c.POINTERS),*(n[k] for k in c.NUMBERS));struct.pack_into('<Q',s,136+0x20,p['mapEntries']);struct.pack_into('<I',s,136+0x44,2);struct.pack_into('<Q',s,216+0x10,p['reverseEntries']);struct.pack_into('<I',s,216+0x40,2)
    struct.pack_into('<I',s,296+80,1);s[c.ROWS_AT:c.ROWS_AT+c.ROW_SIZE]=row(True);s[c.ROWS_AT+c.ROW_SIZE:c.ROWS_AT+2*c.ROW_SIZE]=row()
    opt=bytearray(c.OPTION_SIZE);ptrs={k:0x80000+i*0x1000 for i,k in enumerate(c.OPTION_POINTERS)};ptrs['callbackMethod']=0x100000
    struct.pack_into('<10Q4I',opt,0,*(ptrs[k] for k in c.OPTION_POINTERS),0,0,0,4);opt[96:104]='测试交互'.encode('utf-16-le')
    struct.pack_into('<7Q8I',opt,352,0x91000,0x92000,BASE+0x100000,BASE+0x101000,0x93000,ptrs['callbackTarget']+0x30,0x20009,0,3,16,0x30,9,1,1,0);opt[440:448]=bytes.fromhex('8b4130c390909090');opt[448:496]=row()
    s[c.OPTIONS_AT:c.OPTIONS_AT+c.OPTION_SIZE]=opt
    for i in range(2):
        struct.pack_into('<iiIII',s,c.MAPS_AT+i*20,9+i,-1,9+i,1001+i,9001+i);struct.pack_into('<iiII',s,c.REVERSE_AT+i*16,1001+i,-1,1001+i,9+i)
    data[c.SAMPLES_OFFSET:c.SAMPLES_OFFSET+c.SAMPLE_SIZE]=s;data[c.SAMPLES_OFFSET+c.SAMPLE_SIZE:]=s;return data

def head(data,**changes):
    for key,value in changes.items():struct.pack_into('<I',data,c.HEADER.index(key)*4,value)
def samples(data,offset,value,fmt='I',both=True):
    for i in range(2 if both else 1):struct.pack_into('<'+fmt,data,c.SAMPLES_OFFSET+i*c.SAMPLE_SIZE+offset,value)

class BinaryTests(unittest.TestCase):
    def decode(self,data=None):return c.interpretation(c.parse(raw() if data is None else data),card())
    def refuse(self,mutate,error):
        d=raw();mutate(d)
        with self.assertRaisesRegex(ValueError,error):c.parse(d)
    def test_bound_native_identity(self):self.assertEqual(self.decode()['entities'][1]['editorEntityGuid'],1001)
    def test_avatar_trial_bound(self):self.assertTrue(self.decode()['entities'][0]['belongsToBoundTrial'])
    def test_other_entity_not_assumed_trial_spawn(self):self.assertIsNone(self.decode()['entities'][1]['belongsToBoundTrial'])
    def test_host_native_identity(self):self.assertEqual(self.decode()['interactionOptions'][0]['host']['editorEntityGuid'],1001)
    def test_chinese_label_preserved(self):self.assertEqual(self.decode()['interactionOptions'][0]['text'],'测试交互')
    def test_collision_not_inferred(self):self.assertFalse(self.decode()['collisionVerified']);self.assertIsNone(self.decode()['grounded'])
    def test_unknown_controller_not_reported_known(self):self.assertFalse(self.decode()['controllerStateKnown'])
    def test_raw_serializable(self):json.dumps(c.parse(raw()),allow_nan=False)
    def test_no_config_merging(self):
        s=c.parse(raw())['first'];s['rows'].append(c.entity_row(row(id=10,index=1)));items=c.identities(s);self.assertEqual([x['editorEntityGuid'] for x in items[1:]],[1001,1002]);self.assertEqual(items[1]['configId'],items[2]['configId'])
    def test_duplicate_forward_unknown(self):
        d=raw();samples(d,c.MAPS_AT+20+8,9);self.assertFalse(self.decode(d)['entities'][1]['identityMappingVerified'])
    def test_duplicate_guid_unknown(self):
        d=raw();samples(d,c.MAPS_AT+20+12,1001);self.assertFalse(self.decode(d)['entities'][1]['identityMappingVerified'])
    def test_wrong_inverse_unknown(self):
        d=raw();samples(d,c.REVERSE_AT+12,10);self.assertFalse(self.decode(d)['entities'][1]['identityMappingVerified'])
    def test_deleted_forward_unknown(self):
        d=raw();samples(d,c.MAPS_AT,-1,'i');self.assertFalse(self.decode(d)['entities'][1]['identityMappingVerified'])
    def test_deleted_inverse_unknown(self):
        d=raw();samples(d,c.REVERSE_AT,-1,'i');self.assertFalse(self.decode(d)['entities'][1]['identityMappingVerified'])
    def test_missing_map_unknown(self):
        d=raw();samples(d,88+9*4,1);self.assertFalse(self.decode(d)['interactionHostIdentityVerified'])
    def test_zero_editor_guid_not_claimed(self):
        d=raw();samples(d,c.MAPS_AT+12,0);self.assertIsNone(self.decode(d)['entities'][1]['editorEntityGuid'])
    def test_zero_gameplay_id_not_claimed(self):
        d=raw();samples(d,c.MAPS_AT+16,0);self.assertFalse(self.decode(d)['entities'][1]['identityMappingVerified'])
    def test_inactive_option_unknown(self):
        d=raw();samples(d,c.OPTIONS_AT+408,1);samples(d,c.OPTIONS_AT+428,0);self.assertFalse(self.decode(d)['interactionHostIdentityVerified'])
    def test_unknown_getter_not_assumed_owner(self):
        d=raw();samples(d,c.OPTIONS_AT+408,1);self.assertFalse(self.decode(d)['interactionOptions'][0]['hostIdentityVerified'])
    def test_wrong_size(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(b'')
    def test_wrong_version(self):self.refuse(lambda d:head(d,version=6),'VERSION')
    def test_wrong_op(self):self.refuse(lambda d:head(d,operation=16),'VERSION')
    def test_reserved(self):self.refuse(lambda d:struct.pack_into('<I',d,56,1),'HEADER')
    def test_count_overflow(self):self.refuse(lambda d:head(d,count=130),'HEADER')
    def test_map_overflow(self):self.refuse(lambda d:samples(d,88+4*4,8193),'BOUNDS')
    def test_option_overflow(self):self.refuse(lambda d:samples(d,88+8*4,65),'BOUNDS')
    def test_native_call_bound(self):self.refuse(lambda d:head(d,nativeCalls=133),'NATIVE_CALLS')
    def test_changed_second_sample(self):self.refuse(lambda d:samples(d,c.MAPS_AT+16,44,both=False),'STABILITY')
    def test_map_header_disagreement(self):self.refuse(lambda d:samples(d,136+0x44,1),'MAP_HEADER')
    def test_reverse_header_disagreement(self):self.refuse(lambda d:samples(d,216+0x40,1),'REVERSE_HEADER')
    def test_unused_bytes(self):self.refuse(lambda d:d.__setitem__(-1,1),'UNUSED')
    def test_wrong_avatar(self):self.refuse(lambda d:samples(d,c.ROWS_AT,0x10008,'Q'),'AVATAR')
    def test_page_boundary(self):self.refuse(lambda d:samples(d,c.ROWS_AT+c.ROW_SIZE+40,3),'PAGE_ROWS')
    def test_impure_getter_refused(self):self.refuse(lambda d:samples(d,c.OPTIONS_AT+440,0xe8,'B'),'GETTER_NOT_PURE')
    def test_field_offset_mismatch(self):self.refuse(lambda d:samples(d,c.OPTIONS_AT+420,0x34),'GETTER')
    def test_callback_slot_mismatch(self):self.refuse(lambda d:samples(d,c.OPTIONS_AT+368,BASE+0x100001,'Q'),'VTABLE')
    def test_owner_id_mismatch(self):self.refuse(lambda d:samples(d,c.OPTIONS_AT+424,10),'OWNER_ENTITY')
    def test_owner_recycled(self):self.refuse(lambda d:samples(d,c.OPTIONS_AT+448+28,11),'OWNER_ENTITY')
    def test_getter_disp32(self):self.assertEqual(c.getter_offset(bytes.fromhex('8b8130010000c390')),0x130)
    def test_getter_large_offset(self):
        with self.assertRaisesRegex(ValueError,'RANGE'):c.getter_offset(bytes.fromhex('8b8100100000c390'))
    def test_getter_negative_offset(self):
        with self.assertRaisesRegex(ValueError,'RANGE'):c.getter_offset(bytes.fromhex('8b81f0ffffffc390'))
    def test_wrong_trial_token(self):
        p=card();p['binding']['token']=8
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(raw()),p)
    def test_missing_ancestry(self):
        p=card();p['lineage']['attemptedOperations']=[]
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(raw()),p)
    def test_editor_cannot_be_contact_proof(self):
        d=raw();d[c.CONTROL_OFFSET:c.SAMPLES_OFFSET]=control.raw(playing=False)
        with self.assertRaisesRegex(ValueError,'UNBOUND'):self.decode(d)

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=folder);self.run=Path(self.temp.name);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_CONTACT',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_CONTACT',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
        for name,value in [('exit.json',self.exit),('stdout.jsonl',r)]:(self.run/name).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipt.decode_bound(self.run,self.card)
    def test_card_bound(self):self.assertTrue(self.decode()['ok'])
    def test_nonce(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptNonce='100')
    def test_protocol(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptProtocol=21)
    def test_target(self):
        with self.assertRaisesRegex(ValueError,'TARGET'):self.decode(pid=124)
    def test_hash(self):
        with self.assertRaisesRegex(ValueError,'BINARY_RECEIPT'):self.decode(acceptanceSha256='0'*64)
    def test_page(self):
        self.card['pageStart']=1
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):self.decode()
    def test_cleanup_failed(self):self.assertTrue(self.decode(unhooked=False)['outcomeUncertain'])
    def test_active_callback(self):self.assertFalse(self.decode(activeCallbacks=1)['safeToRelease'])
    def test_seh(self):head(self.data,status=2,seh=0xc0000005);self.assertFalse(self.decode()['safeToRelease'])
    def test_refusal(self):self.exit.update(executed=False,error='SOURCE_CHANGED');self.assertTrue(self.decode()['safeToRelease'])
    def test_refusal_after_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_anchor_changed(self):
        p=dict(anchorRun='anchor',session={},targetLevelId=1843,lineage={'original':1},binding={})
        with patch.object(b.c,'previous',return_value=({},{})),self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):b.revalidate_proofs(p)
    def test_invalid_plan(self):
        with self.assertRaisesRegex(ValueError,'CONTACT_PLAN'):b.validate_card(dict(mode='shop-ui',pageStart=0))
    def test_compile_only_cannot_launch(self):
        with self.assertRaisesRegex(ValueError,'COMPILE_ONLY'):b.validate_card(dict(mode='contact-state',pageStart=0,compileOnly=True,launchable=True))

if __name__=='__main__':unittest.main()
