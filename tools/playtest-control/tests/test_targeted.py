"""Atomic callback identity and source membership, never inferred from UI pointer alone."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import targeted_contract as c,targeted_build as b,targeted_receipt as receipt
import test_directory as directory

def plan():return dict(targetId='npc-01',editorGuid=1001,runtimeId=9,optionIndex=0,label='测试交互')
def raw():
    data=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=9,stage=3,operation=19,resourcesReleased=1,actionAttempted=1,actionReturned=1,guardVerified=1,editorGuid=1001,runtimeId=9,nativeCalls=4)
    base=directory.contact.BASE;struct.pack_into('<16I4Q',data,0,*(h[k] for k in c.HEADER),base,100,100,0);nested=directory.raw();data[c.DIRECTORY_AT:c.OPTION_AT]=nested
    parsed=directory.c.parse(nested);s=parsed['contact']['first'];state=parsed['contact']['control']['observation']['after']
    at=directory.c.CONTACT_OFFSET+directory.contact.c.SAMPLES_OFFSET+directory.contact.c.OPTIONS_AT;data[c.OPTION_AT:c.SOURCE_AT]=nested[at:at+496]
    struct.pack_into('<QQIIQ',data,c.SOURCE_AT,0xc0000,0xd0000,1001,55,0xe0000)
    p={k:0x110000+i*0x1000 for i,k in enumerate(c.INPUT_POINTERS)};p.update(avatar=state['avatar'],componentOwner=state['avatar'],managedAvatar=state['avatar'],context=s['mainContext'],view=s['view'],expectedClass=0x116000,strengthSlot=base+0x12b51c50,activeSlot=base+0x12b526e0)
    n={k:0 for k in c.INPUT_NUMBERS};n.update(avatarId=state['avatarId'],owned=1,valid=1,frame=1);struct.pack_into('<12Q8I',data,c.INPUT_AT,*(p[k] for k in c.INPUT_POINTERS),*(n[k] for k in c.INPUT_NUMBERS));return data
def card():
    data=raw();o=c.parse(data);i=o['input'];p=directory.card();p.update(mode='targeted-interact',targetPlan=plan(),targetBinding=dict(optionHex=data[c.OPTION_AT:c.SOURCE_AT].hex(),avatar=i['avatar'],avatarId=i['avatarId'],mainContext=i['context'],view=i['view']));return p
def head(data,**changes):
    for key,value in changes.items():struct.pack_into('<I',data,4*c.HEADER.index(key),value)
class TargetTests(unittest.TestCase):
    def decode(self,data=None,p=None):return c.interpretation(c.parse(raw() if data is None else data),card() if p is None else p)
    def refuse(self,change,error):
        data=raw();change(data)
        with self.assertRaisesRegex(ValueError,error):c.parse(data)
    def test_atomic_target_identity(self):self.assertTrue(self.decode()['atomicTargetIdentityVerified'])
    def test_exact_editor_guid(self):self.assertEqual(self.decode()['invokedEditorEntityGuid'],1001)
    def test_exact_runtime_id(self):self.assertEqual(self.decode()['invokedRuntimeId'],9)
    def test_exact_chinese_label(self):self.assertEqual(self.decode()['invokedLabel'],'测试交互')
    def test_effect_independent(self):self.assertFalse(self.decode()['businessEffectVerified'])
    def test_npc_appearance_not_inferred(self):self.assertFalse(self.decode()['targetNpcIdentityVerified'])
    def test_collision_not_inferred(self):self.assertFalse(self.decode()['playerContactVerified'])
    def test_not_readonly(self):self.assertFalse(self.decode()['readOnly'])
    def test_wrong_size(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(b'')
    def test_version(self):self.refuse(lambda d:head(d,version=8),'VERSION')
    def test_operation(self):self.refuse(lambda d:head(d,operation=18),'VERSION')
    def test_reserved(self):self.refuse(lambda d:head(d,reserved=1),'HEADER')
    def test_call_bound(self):self.refuse(lambda d:head(d,nativeCalls=68),'HEADER')
    def test_no_attempt_without_guard(self):self.refuse(lambda d:head(d,guardVerified=0),'ACTION_ORDER')
    def test_no_return_without_attempt(self):self.refuse(lambda d:head(d,actionAttempted=0),'ACTION_ORDER')
    def test_no_success_without_return(self):self.refuse(lambda d:head(d,actionReturned=0),'SUCCESS_WITHOUT_ACTION')
    def test_menu_button_reused_different_callback(self):self.refuse(lambda d:struct.pack_into('<Q',d,c.OPTION_AT+48,0x88888),'ATOMIC_ASSOCIATION|OWNER_GETTER')
    def test_menu_same_label_different_owner(self):self.refuse(lambda d:struct.pack_into('<I',d,c.OPTION_AT+424,10),'OWNER_ENTITY|ATOMIC_ASSOCIATION')
    def test_input_disabled(self):self.refuse(lambda d:struct.pack_into('<I',d,c.INPUT_AT+100,1),'INPUT_GUARD')
    def test_avatar_owner_mismatch(self):self.refuse(lambda d:struct.pack_into('<Q',d,c.INPUT_AT+64,0x77777),'INPUT_IDENTITY')
    def test_input_class_mismatch(self):self.refuse(lambda d:struct.pack_into('<Q',d,c.INPUT_AT+56,0x77777),'INPUT_IDENTITY')
    def test_input_vtable_mismatch(self):self.refuse(lambda d:struct.pack_into('<Q',d,c.INPUT_AT+80,0x77777),'INPUT_IDENTITY')
    def test_checked_after_call_rejected(self):self.refuse(lambda d:struct.pack_into('<Q',d,80,99),'CALL_TIMING')
    def test_frozen_callback_bytes_rejected(self):
        p=card();p['targetBinding']['optionHex']='00'*496
        with self.assertRaisesRegex(ValueError,'EXPECTED_BINDING'):self.decode(p=p)
    def test_wrong_requested_editor_guid(self):
        p=card();p['targetPlan']['editorGuid']=1002
        with self.assertRaisesRegex(ValueError,'PLAN_BINDING'):self.decode(p=p)
    def test_wrong_requested_runtime(self):
        p=card();p['targetPlan']['runtimeId']=10
        with self.assertRaisesRegex(ValueError,'PLAN_BINDING'):self.decode(p=p)
    def test_wrong_requested_label(self):
        p=card();p['targetPlan']['label']='另一个选项'
        with self.assertRaisesRegex(ValueError,'OPTION_UNKNOWN'):self.decode(p=p)
    def test_source_record_mismatch(self):
        data=raw();struct.pack_into('<I',data,c.SOURCE_AT+16,1002)
        with self.assertRaisesRegex(ValueError,'EXPECTED_BINDING'):self.decode(data)
    def test_session_avatar_mismatch(self):
        p=card();p['targetBinding']['avatar']=0x77777
        with self.assertRaisesRegex(ValueError,'BASELINE_IDENTITY'):self.decode(p=p)
    def test_baseline_unverified_host(self):
        result=directory.c.interpretation(directory.c.parse(directory.raw()),directory.card());result.update(ok=True,safeToRelease=True,outcomeUncertain=False);result['interactionOptions'][0]['hostTrialMembershipVerified']=False
        with self.assertRaisesRegex(ValueError,'OPTION_UNKNOWN'):c.selected(result,plan())
    def test_plan_rejects_unsafe_id(self):
        with self.assertRaisesRegex(ValueError,'TARGETED_ID'):c.plan(SimpleNamespace(operation='targeted-interact',target_id='../repeat'))
    def test_plan_rejects_unknown_identity(self):
        with self.assertRaisesRegex(ValueError,'IDENTITIES'):c.plan(SimpleNamespace(operation='targeted-interact',target_id='one',expected_editor_guid=0,expected_runtime_id=9))
    def test_plan_rejects_bool_identity(self):
        with self.assertRaisesRegex(ValueError,'IDENTITIES'):c.plan(SimpleNamespace(operation='targeted-interact',target_id='one',expected_editor_guid=True,expected_runtime_id=9))
    def test_exact_card_mode(self):
        with self.assertRaisesRegex(ValueError,'CARD_MODE'):b.validate_card(dict(mode='interact-option',pageStart=0))
    def test_ancestor_changed(self):
        with patch.object(b.c,'previous',return_value=({},{})),self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):b.revalidate_proofs(dict(anchorRun='x',session={},targetLevelId=1,lineage={'old':1},binding={}))

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=folder);self.run=Path(self.temp.name);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_TARGETED',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_TARGETED',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
        for name,value in [('exit.json',self.exit),('stdout.jsonl',r)]:(self.run/name).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipt.decode_bound(self.run,self.card)
    def test_bound_success(self):self.assertTrue(self.decode()['atomicTargetIdentityVerified'])
    def test_wrong_nonce(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptNonce='100')
    def test_wrong_digest(self):
        with self.assertRaisesRegex(ValueError,'BINARY_RECEIPT'):self.decode(acceptanceSha256='0'*64)
    def test_cleanup_failure(self):self.assertFalse(self.decode(unhooked=False)['ok'])
    def test_partial_action_unknown(self):
        head(self.data,status=1,actionReturned=0,stage=2);r=self.decode(ok=False);self.assertTrue(r['outcomeUncertain']);self.assertFalse(r['atomicTargetIdentityVerified'])
    def test_refusal_no_attempt(self):self.exit.update(executed=False,error='SOURCE_CHANGED');self.assertTrue(self.decode()['safeToRelease'])
    def test_no_replay_after_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_claim_exclusive(self):
        self.card['lineage']['rootRun']=str(self.run);(self.run/'prepared.json').write_text('{}');b.claim_write(self.run,self.card)
        with self.assertRaises(FileExistsError):b.claim_write(self.run,self.card)
