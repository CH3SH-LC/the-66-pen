"""Independent raw v9 fixture; no game access, unknown is never membership."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import directory_contract as c,directory_build as b,directory_receipt as receipt
import test_contact as contact
def card():
    p=contact.card();p.update(mode='trial-entities');return p
def raw():
    data=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=8,stage=3,operation=18,resourcesReleased=1,stable=1)
    struct.pack_into('<12IQ',data,0,*(h[k] for k in c.HEADER),contact.BASE);data[c.CONTACT_OFFSET:c.SAMPLES_OFFSET]=contact.raw()
    state=contact.c.parse(contact.raw())['control']['after'];s=bytearray(c.SAMPLE_SIZE);p={k:0xa0000+i*0x1000 for i,k in enumerate(c.POINTERS)};p.update(global_=state['global'],levelData=state['cache'],editData=state['cacheEditData'],enumerator=contact.BASE+0x1713e080,capacity=2);p['global']=p.pop('global_');p['expectedEditClass']=p['editClass'];p['expectedCommonClass']=p['commonClass'];p['expectedContainerClass']=p['containerClass']
    n={k:0 for k in c.NUMBERS};n.update(count=2,listVersion=5,virtualCount=64,recordCount=2)
    struct.pack_into('<17Q8I',s,0,*(p[k] for k in c.POINTERS),*(n[k] for k in c.NUMBERS));struct.pack_into('<Q',s,168,p['containerClass']);struct.pack_into('<Q',s,184,p['list']);struct.pack_into('<QII',s,216,p['entries'],2,5)
    for i in range(2):struct.pack_into('<QQIIQ',s,c.ROWS_AT+i*32,0xc0000+i*0x1000,0xd0000,1001+i,55,0xe0000)
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
    def test_source_directory_known(self):self.assertTrue(self.decode()['sourceDirectoryKnown'])
    def test_runtime_entity_exact_membership(self):
        e=self.decode()['entities'][1];self.assertTrue(e['belongsToBoundTrial']);self.assertTrue(e['targetLevelSpawnMembershipVerified']);self.assertEqual(e['sourceInstance']['editorGuid'],1001)
    def test_native_menu_host_same_directory(self):self.assertTrue(self.decode()['interactionOptions'][0]['hostTrialMembershipVerified'])
    def test_local_avatar_is_not_source_instance(self):self.assertFalse(self.decode()['entities'][0]['targetLevelSpawnMembershipVerified'])
    def test_collision_still_unproven(self):self.assertFalse(self.decode()['collisionVerified']);self.assertIsNone(self.decode()['grounded'])
    def test_not_npc_just_from_directory(self):self.assertFalse(self.decode()['targetNpcIdentityVerified'])
    def test_same_template_not_merged(self):self.assertEqual(len(self.decode()['sourceDirectory']['rows']),2)
    def test_missing_guid_unknown(self):
        d=raw();samples(d,c.ROWS_AT+16,999);e=self.decode(d)['entities'][1];self.assertIsNone(e['belongsToBoundTrial']);self.assertFalse(e['targetLevelSpawnMembershipVerified'])
    def test_duplicate_guid_unknown(self):
        d=raw();samples(d,c.ROWS_AT+32+16,1001);self.assertFalse(self.decode(d)['sourceDirectoryKnown']);self.assertIsNone(self.decode(d)['entities'][1]['belongsToBoundTrial'])
    def test_duplicate_record_unknown(self):
        d=raw();samples(d,c.ROWS_AT+32,0xc0000,'Q');self.assertFalse(self.decode(d)['sourceDirectoryKnown'])
    def test_incomplete_directory_unknown(self):
        d=raw();samples(d,136,1);self.assertFalse(self.decode(d)['targetLevelSpawnMembershipVerified'])
    def test_runtime_mapping_not_bypassed(self):
        d=raw();part=bytearray(d[c.CONTACT_OFFSET:c.SAMPLES_OFFSET]);contact.samples(part,contact.c.MAPS_AT+8,11);d[c.CONTACT_OFFSET:c.SAMPLES_OFFSET]=part;self.assertFalse(self.decode(d)['entities'][1]['targetLevelSpawnMembershipVerified'])
    def test_wrong_size(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(b'')
    def test_version(self):self.refuse(lambda d:head(d,version=7),'VERSION')
    def test_operation(self):self.refuse(lambda d:head(d,operation=17),'VERSION')
    def test_not_a_calling_card(self):self.refuse(lambda d:head(d,nativeCalls=1),'HEADER')
    def test_reserved(self):self.refuse(lambda d:head(d,reserved0=1),'HEADER')
    def test_capacity(self):self.refuse(lambda d:samples(d,88,1,'Q'),'COMPLETE')
    def test_count_limit(self):self.refuse(lambda d:samples(d,140,8193),'BOUNDS')
    def test_partial_count_cannot_be_complete(self):self.refuse(lambda d:samples(d,152,1),'COMPLETE')
    def test_raw_version_header(self):self.refuse(lambda d:samples(d,228,6),'LIST_HEADER')
    def test_raw_list_header(self):self.refuse(lambda d:samples(d,184,0x77777,'Q'),'CONTAINER_HEADER')
    def test_raw_entry_header(self):self.refuse(lambda d:samples(d,216,0x77777,'Q'),'LIST_HEADER')
    def test_source_from_different_trial(self):self.refuse(lambda d:samples(d,24,0x77777,'Q'),'TRIAL_SOURCE')
    def test_wrong_enumerator(self):self.refuse(lambda d:samples(d,72,contact.BASE+0x1713e081,'Q'),'ENUMERATOR')
    def test_edit_type_mismatch(self):self.refuse(lambda d:samples(d,96,0x77777,'Q'),'EXACT_TYPES')
    def test_common_type_mismatch(self):self.refuse(lambda d:samples(d,104,0x77777,'Q'),'EXACT_TYPES')
    def test_container_type_mismatch(self):self.refuse(lambda d:samples(d,128,0x77777,'Q'),'EXACT_TYPES')
    def test_zero_guid(self):self.refuse(lambda d:samples(d,c.ROWS_AT+16,0),'RECORD')
    def test_unstable_raw_samples(self):self.refuse(lambda d:samples(d,c.ROWS_AT+20,56,both=False),'STABILITY')
    def test_unused(self):self.refuse(lambda d:d.__setitem__(-1,1),'UNUSED')
    def test_wrong_bound_token(self):
        p=card();p['binding']['token']=8
        with self.assertRaisesRegex(ValueError,'UNBOUND'):c.interpretation(c.parse(raw()),p)
    def test_json_serializable(self):json.dumps(self.decode(),allow_nan=False)
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=folder);self.run=Path(self.temp.name);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_DIRECTORY',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_DIRECTORY',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
        for name,value in [('exit.json',self.exit),('stdout.jsonl',r)]:(self.run/name).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipt.decode_bound(self.run,self.card)
    def test_bound_receipt(self):self.assertTrue(self.decode()['ok'])
    def test_nonce(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptNonce='100')
    def test_digest(self):
        with self.assertRaisesRegex(ValueError,'BINARY_RECEIPT'):self.decode(acceptanceSha256='0'*64)
    def test_cleanup(self):self.assertFalse(self.decode(unhooked=False)['safeToRelease'])
    def test_page(self):
        self.card['pageStart']=1
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):self.decode()
    def test_refusal(self):self.exit.update(executed=False,error='SOURCE_CHANGED');self.assertTrue(self.decode()['safeToRelease'])
    def test_no_replay_after_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_source_binding_revalidated(self):
        p=dict(anchorRun='anchor',session={},targetLevelId=1843,lineage={'old':1},binding={})
        with patch.object(b.c,'previous',return_value=({},{})),self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):b.revalidate_proofs(p)
    def test_exact_operation(self):
        p=dict(mode='contact-state',pageStart=0)
        with self.assertRaisesRegex(ValueError,'DIRECTORY_PLAN'):b.validate_card(p)
