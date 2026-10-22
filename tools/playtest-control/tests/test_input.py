"""Independent binary, provenance, one-shot and uncertainty regressions."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import input_contract as c,input_build as b,input_receipt as receipts,contract
import test_control as control

def args(operation='move-pulse',**changes):
    p=dict(operation=operation,input_id=None if operation=='input-state' else 'case-01',angle=0.0,strength=0.5,duration_ms=500,max_distance=2.0,label=None,option_index=None);p.update(changes);return SimpleNamespace(**p)
def card(operation='input-state'):
    p=control.card();p.update(mode=operation,inputPlan=c.plan(args(operation,**(dict(label='打开商店',option_index=0) if operation=='interact-option' else {}))),inputBinding=dict(avatar=0x10007,avatarId=7,component=0x30000,mainContext=0x40000,view=0x50000,button=0x60000,attackSlot=2,item=0x70000));return p
def raw(operation='input-state'):
    data=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=3,stage=3,operation=c.OPERATIONS[operation],resourcesReleased=1,callbacks=1,points=1,options=1,released=1)
    if operation!='input-state':h.update(actionAttempted=1,actionReturned=1,releaseAttempted=1)
    struct.pack_into('<16I',data,0,*(h[k] for k in c.HEADER));struct.pack_into('<2Q4I',data,64,100,100,1,1,int(operation=='attack-tap'),0)
    data[96:96+c.CONTROL_SIZE]=control.raw();at=96+c.CONTROL_SIZE
    values=dict(avatar=0x10007,manager=0x20000,component=0x30000,inputState=0x31000,mainContext=0x40000,view=0x50000,actionPanel=0x51000,inteePanel=0x52000,button=0x60000)
    struct.pack_into('<9Q',data,at,*(values[k] for k in c.POINTERS));at+=72
    struct.pack_into('<8I',data,at,7,2,0x167,0,1,1,1,0);at+=32
    label='打开商店'.encode('utf-16-le');struct.pack_into('<2Q4I',data,at,0x70000,0x60000,0,1,1,len(label)//2);data[at+32:at+32+len(label)]=label
    at+=64*288;struct.pack_into('<Q2I5fI',data,at,100,1,0,11.,22.,33.,0.,0.,0);return data
def set_header(data,**changes):
    for k,v in changes.items():struct.pack_into('<I',data,4*c.HEADER.index(k),v)

class PlanTests(unittest.TestCase):
    def test_readonly_has_no_identity(self):self.assertIsNone(c.plan(args('input-state'))['inputId'])
    def test_readonly_refuses_input_id(self):
        with self.assertRaisesRegex(ValueError,'NO_ID'):c.plan(args('input-state',input_id='x'))
    def test_mutation_requires_identity(self):
        with self.assertRaisesRegex(ValueError,'INPUT_ID'):c.plan(args(input_id=None))
    def test_path_identity_refused(self):
        with self.assertRaisesRegex(ValueError,'INPUT_ID'):c.plan(args(input_id='../other'))
    def test_nonfinite_angle_refused(self):
        with self.assertRaisesRegex(ValueError,'FINITE'):c.plan(args(angle=float('nan')))
    def test_nonfinite_distance_refused(self):
        with self.assertRaisesRegex(ValueError,'FINITE'):c.plan(args(max_distance=float('inf')))
    def test_duration_ceiling(self):
        with self.assertRaisesRegex(ValueError,'BOUNDED'):c.plan(args(duration_ms=3001))
    def test_distance_ceiling(self):
        with self.assertRaisesRegex(ValueError,'BOUNDED'):c.plan(args(max_distance=8.1))
    def test_boolean_duration_refused(self):
        with self.assertRaisesRegex(ValueError,'BOUNDED'):c.plan(args(duration_ms=True))
    def test_strength_ceiling(self):
        with self.assertRaisesRegex(ValueError,'BOUNDED'):c.plan(args(strength=1.1))
    def test_exact_option_label(self):self.assertEqual(c.plan(args('interact-option',label='打开商店',option_index=0))['label'],'打开商店')
    def test_blank_label_refused(self):
        with self.assertRaisesRegex(ValueError,'EXACT_OPTION'):c.plan(args('interact-option',label='',option_index=0))
    def test_utf16_capacity(self):
        with self.assertRaisesRegex(ValueError,'EXACT_OPTION'):c.plan(args('interact-option',label='🌱'*64,option_index=0))
    def test_wrong_action_label(self):
        with self.assertRaisesRegex(ValueError,'WRONG_ACTION'):c.plan(args(label='攻击',option_index=0))

class BinaryTests(unittest.TestCase):
    def test_readonly_has_real_trial_binding(self):
        out=c.interpretation(c.parse(raw()),card());self.assertEqual(out['worldPosition'],[11.,22.,33.]);self.assertTrue(out['playerBelongsToTargetLevel']);self.assertFalse(out['nativeInputSubmitted'])
    def test_parsed_output_json_serializable(self):json.dumps(c.parse(raw()),allow_nan=False)
    def test_wrong_size(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(b'')
    def test_unknown_version(self):
        data=raw();set_header(data,version=4)
        with self.assertRaisesRegex(ValueError,'VERSION'):c.parse(data)
    def test_observer_cannot_claim_write(self):
        data=raw();set_header(data,actionAttempted=1)
        with self.assertRaisesRegex(ValueError,'READ_ONLY'):c.parse(data)
    def test_return_without_attempt(self):
        data=raw();set_header(data,actionReturned=1)
        with self.assertRaisesRegex(ValueError,'RETURN_WITHOUT'):c.parse(data)
    def test_callback_bound(self):
        data=raw();set_header(data,callbacks=4097)
        with self.assertRaisesRegex(ValueError,'BOUNDS'):c.parse(data)
    def test_option_bound(self):
        data=raw();set_header(data,options=65)
        with self.assertRaisesRegex(ValueError,'BOUNDS'):c.parse(data)
    def test_unused_trajectory_bytes(self):
        data=raw();data[-1]=1
        with self.assertRaisesRegex(ValueError,'PADDING'):c.parse(data)
    def test_option_padding(self):
        data=raw();data[96+c.CONTROL_SIZE+104+287]=1
        with self.assertRaisesRegex(ValueError,'OPTION_PADDING'):c.parse(data)
    def test_trial_token_mismatch(self):
        p=card();p['binding']['token']=99
        with self.assertRaisesRegex(ValueError,'TRIAL_BINDING'):c.interpretation(c.parse(raw()),p)
    def test_editor_not_trial(self):
        data=raw();data[96:96+c.CONTROL_SIZE]=control.raw(playing=False)
        with self.assertRaisesRegex(ValueError,'TRIAL_BINDING'):c.interpretation(c.parse(data),card())
    def test_missing_enter_receipt_refused(self):
        p=card();p['lineage']['attemptedOperations']=[]
        with self.assertRaisesRegex(ValueError,'TRIAL_BINDING'):c.interpretation(c.parse(raw()),p)
    def test_changed_avatar_refused(self):
        p=card('move-pulse');p['inputBinding']['avatar']=0x99999
        with self.assertRaisesRegex(ValueError,'BASELINE_IDENTITY'):c.interpretation(c.parse(raw('move-pulse')),p)
    def test_release_required(self):
        data=raw('move-pulse');set_header(data,released=0)
        with self.assertRaisesRegex(ValueError,'RELEASE'):c.interpretation(c.parse(data),card('move-pulse'))
    def test_attack_not_damage(self):
        out=c.interpretation(c.parse(raw('attack-tap')),card('attack-tap'));self.assertTrue(out['nativeInputSubmitted']);self.assertFalse(out['damageVerified'])
    def test_option_not_natural_effect(self):
        out=c.interpretation(c.parse(raw('interact-option')),card('interact-option'));self.assertTrue(out['interactionCallbackSubmitted']);self.assertFalse(out['naturalInteractionVerified'])
    def test_changed_chinese_option(self):
        p=card('interact-option');p['inputPlan']['label']='收获作物'
        with self.assertRaisesRegex(ValueError,'EXACT_OPTION_CHANGED'):c.interpretation(c.parse(raw('interact-option')),p)
    def test_motion_observation_not_contact(self):
        data=raw('move-pulse');set_header(data,points=2);at=96+c.CONTROL_SIZE+104+64*288+40;struct.pack_into('<Q2I5fI',data,at,200,2,1,12.,22.,33.,.5,0.,0)
        out=c.interpretation(c.parse(data),card('move-pulse'));self.assertTrue(out['actualPlayerMotionObserved']);self.assertFalse(out['playerContactVerified'])

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=folder);self.run=Path(self.temp.name)
        self.data=raw('move-pulse');self.card=card('move-pulse');self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_INPUT',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_INPUT',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
        for n,value in [('exit.json',self.exit),('stdout.jsonl',r)]:(self.run/n).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipts.decode_bound(self.run,self.card)
    def test_full_raw_binding(self):self.assertTrue(self.decode()['ok'])
    def test_wrong_nonce(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptNonce='100')
    def test_wrong_full_hash(self):
        with self.assertRaisesRegex(ValueError,'BINARY_RECEIPT'):self.decode(acceptanceSha256='0'*64)
    def test_callback_count_mismatch(self):self.assertFalse(self.decode(callbackCount=2)['safeToRelease'])
    def test_missing_release_uncertain(self):
        set_header(self.data,released=0);out=self.decode();self.assertTrue(out['outcomeUncertain']);self.assertFalse(out['safeToRelease'])
    def test_missing_return_uncertain(self):
        set_header(self.data,actionReturned=0);self.assertTrue(self.decode()['outcomeUncertain'])
    def test_native_seh_uncertain(self):
        set_header(self.data,seh=0xc0000005,status=2);self.assertTrue(self.decode()['outcomeUncertain'])
    def test_wrapper_refusal_clean(self):
        self.exit.update(executed=False,error='SOURCE_CHANGED');out=self.decode();self.assertFalse(out['nativeStarted']);self.assertTrue(out['safeToRelease'])
    def test_refusal_with_attempt_rejected(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_same_input_id_cannot_replay(self):
        (self.run/'prepared.json').write_text('{}');self.card['lineage']['rootRun']=str(self.run);b.claim_write(self.run,self.card)
        with self.assertRaises(FileExistsError):b.claim_write(self.run,self.card)
    def test_two_cards_same_id_refused(self):
        (self.run/'prepared.json').write_text('{}');self.card['lineage']['rootRun']=str(self.run);b.claim_write(self.run,self.card);other=self.run/'other';other.mkdir();(other/'prepared.json').write_text('{}')
        with self.assertRaises(FileExistsError):b.claim_write(other,self.card)
    def test_readonly_does_not_claim(self):b.claim_write(self.run,dict(mode='input-state'));self.assertEqual(list(self.run.glob('*.claim')),[])
    def test_anchor_revalidation_cannot_be_skipped(self):
        p=dict(anchorRun='anchor',session={},targetLevelId=1843,lineage={'old':1},binding={},inputBaseline=None)
        with patch.object(b.c,'previous',return_value=({},{})),self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):b.revalidate_proofs(p)
    def test_readonly_baseline_cannot_be_forged(self):
        p=dict(mode='input-state',inputPlan=c.plan(args('input-state')),compileOnly=False,lineage=dict(ancestors=[dict(run='a')],attemptedOperations=['enter-start']),anchorRun='a',inputBinding={'unexpected':1},inputBaseline=None)
        with self.assertRaisesRegex(ValueError,'READ_ONLY_PLAN'):b.validate_card(p)

class CandidateTests(unittest.TestCase):
    def test_fixed_multiframe_private_transport(self):
        folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temp:
            run=Path(temp);b.copy_sources(run)
            protocol=(run/'candidate-source/native/hook_receipt_protocol.h').read_text();hook=(run/'candidate-source/native/hook_receipt.cpp').read_text();probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text()
            self.assertIn('InputReceipt acceptance;',protocol);self.assertIn('kReceiptVersion=24;',protocol)
            self.assertIn('StepInput(&receipt->acceptance)',hook);self.assertIn('InterlockedCompareExchange(&receipt->claim,0,0)<2',hook)
            self.assertIn('InterlockedExchange(&receipt->claim,inputDone?2:1)',hook);self.assertIn('FIXED_PLAYTEST_INPUT',probe)
            self.assertIn('receipt->callbacks!=static_cast<LONG>(receipt->acceptance.callbacks)',probe);self.assertIn('Sleep(16)',probe);self.assertIn('CALG_SHA_256',probe)
            self.assertNotIn('*receipt = {};',probe)
    def test_native_input_no_desktop_or_transform_write_import(self):
        source=(HERE/'native_input.cpp').read_text()
        for forbidden in ('SendInput','SetCursorPos','SetForegroundWindow','SetWorldPosition','WriteProcessMemory','set_position'):self.assertNotIn(forbidden,source)

if __name__=='__main__':unittest.main()
