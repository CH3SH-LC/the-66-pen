"""Independent control-contract regression fixtures. Unified gate only."""
import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import contract,control_contract as c,control_build as b,control_receipt as receipts
import test_observation as observation_tests
from test_acceptance import Fixture as ImageFixture

def state(**changes):
    result={k:0 for k in c.POINTERS+c.NUMBERS};result.update(global_=0x10000,editor=0x20000,task=0x30000,cache=0x40000,data=0x40000,room=0x60000,cacheEditData=0x50000,token=7,roomToken=7,localUid=123,ownerUid=123,editorLevel=1843,readable=767)
    result['global']=result.pop('global_');result.update(changes);return result

def play_state(**changes):
    result=state(data=0x40000,sceneId=47504,sceneType=5,editing=0,isTrial=1,cacheIsTrial=1,currentIsTrial=1,loadPhase=10,avatarActive=1,trialReady=1);result.update(changes);return result

def raw(operation=3,playing=True,**state_changes):
    out=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=2,stage=3,operation=operation,resourcesReleased=1,stateStable=1)
    if operation in (4,5,6,7):h.update(actionAttempted=1,actionReturned=1)
    old=observation_tests.ObservationTests();e=old.evidence()
    for key in ('before','after'):e[key].update(editorManager=0x20000)
    if playing:
        e['mode']=0
        for key in ('before','after'):e[key].update(rawMode=47504,editing=0)
    out[96:432]=old.raw(e)
    s=play_state(**state_changes) if playing else state(editing=1,sceneId=0xb993,**state_changes)
    for at in (432,648):struct.pack_into('<15Q24I',out,at,*(s[k] for k in c.POINTERS+c.NUMBERS))
    if operation==8:
        png=ImageFixture.png();h.update(width=1,height=1,pngBytes=len(png));out[c.PNG_OFFSET:c.PNG_OFFSET+len(png)]=png
    struct.pack_into('<20I',out,0,*(h[k] for k in c.HEADER));return out

def prepared(operation='trial-state'):
    return dict(mode=operation,targetLevelId=1843,binding=dict(global_=0x10000,editor=0x20000,task=0x30000,cache=0x40000,cacheEditData=0x50000,token=7),lineage=dict(attemptedOperations=['enter-request','enter-start']))

def card(operation='trial-state'):
    p=prepared(operation);p['binding']['global']=p['binding'].pop('global_');return p

class ControlContractTests(unittest.TestCase):
    def test_bound_loaded_trial_is_play(self):
        v=c.interpretation_control(c.parse(raw()),card());self.assertEqual(v['mode'],'play');self.assertTrue(v['playerBelongsToTargetLevel']);self.assertFalse(v['playerContactVerified'])
    def test_local_avatar_alone_not_play(self):
        p=card();p['binding']['token']=8;v=c.interpretation_control(c.parse(raw()),p);self.assertEqual(v['mode'],'unknown');self.assertIsNone(v['playerBelongsToTargetLevel'])
    def test_missing_start_receipt_not_play(self):
        p=card();p['lineage']['attemptedOperations']=['enter-request'];self.assertNotEqual(c.interpretation_control(c.parse(raw()),p)['mode'],'play')
    def test_editor_avatar_not_target_player(self):
        v=c.interpretation_control(c.parse(raw(playing=False)),card());self.assertEqual(v['mode'],'editor');self.assertFalse(v['playerBelongsToTargetLevel'])
    def test_transition_not_complete(self):
        e=c.parse(raw());e['after']['loadPhase']=9;e['after']['loadTask']=0x60000;e['after']['trialReady']=0;e['stateStable']=0
        v=c.interpretation_control(e,card());self.assertEqual(v['mode'],'transition');self.assertFalse(v['asynchronousActionComplete'])
    def test_non_beyond_type_not_play(self):
        v=c.interpretation_control(c.parse(raw(sceneType=1,trialReady=0)),card());self.assertEqual(v['mode'],'unknown')
    def test_native_positive_guard_independently_recomputed(self):
        with self.assertRaisesRegex(ValueError,'POSITIVE_GUARD'):c.interpretation_control(c.parse(raw(sceneType=1)),card())
    def test_trial_guid_not_used_as_editor_id(self):
        self.assertNotIn('levelGuid',c.POINTERS);self.assertTrue(c.interpretation_control(c.parse(raw()),card())['trialIdentityBound'])
    def test_no_natural_interaction_or_monster_hp_claim(self):
        v=c.interpretation_control(c.parse(raw()),card());self.assertFalse(v['naturalInteractionVerified']);self.assertFalse(v['monsterHealthVerified']);self.assertFalse(v['monsterAiVerified'])
    def test_wrong_binary_version(self):
        data=raw();struct.pack_into('<I',data,4,1)
        with self.assertRaisesRegex(ValueError,'VERSION'):c.parse(data)
    def test_readonly_cannot_claim_mutation(self):
        data=raw();struct.pack_into('<I',data,32,1)
        with self.assertRaisesRegex(ValueError,'OBSERVATION_MUTATION'):c.parse(data)
    def test_return_requires_attempt(self):
        data=raw();struct.pack_into('<I',data,36,1)
        with self.assertRaisesRegex(ValueError,'RETURN_WITHOUT_ATTEMPT'):c.parse(data)
    def test_reserved_data_rejected(self):
        data=raw();data[80]=1
        with self.assertRaisesRegex(ValueError,'RESERVED'):c.parse(data)
    def test_unused_image_data_rejected(self):
        data=raw();data[-1]=1
        with self.assertRaisesRegex(ValueError,'UNUSED_FRAME'):c.parse(data)
    def test_trial_frame_bound_and_not_visual_pass(self):
        v=c.interpretation_control(c.parse(raw(8)),card('trial-frame'));self.assertTrue(v['renderFrameCaptured']);self.assertFalse(v['visualAcceptanceVerified']);self.assertIn('not-guaranteed',v['frameFreshness'])
    def test_trial_frame_target_mismatch(self):
        p=card('trial-frame');p['binding']['cacheEditData']=1
        with self.assertRaisesRegex(ValueError,'FRAME_BINDING'):c.interpretation_control(c.parse(raw(8)),p)
    def test_settlement_is_not_play(self):
        e=c.parse(raw(settleTrial=1,exitReady=1,readable=1023,settleManager=0x70000,settleContext=0x71000,settleData=0x72000));p=card();v=c.interpretation_control(e,p)
        # A live avatar during settlement does not turn the settlement back into play.
        self.assertEqual(v['mode'],'settlement')
    def test_editor_return_requires_exit_receipt(self):
        e=c.parse(raw(playing=False));p=card();self.assertFalse(c.interpretation_control(e,p)['returnToOriginalEditorVerified']);p['lineage']['attemptedOperations'].append('exit-request');self.assertTrue(c.interpretation_control(e,p)['returnToOriginalEditorVerified'])

class FlowTests(unittest.TestCase):
    def value(self,**changes):
        result=dict(ok=True,safeToRelease=True,outcomeUncertain=False,mode='unknown',trialIdentityBound=False,trialState=dict(taskPhase=9,entryReady=1));result.update(changes);return result
    def test_start_only_once(self):self.assertEqual(c.next_operation('enter',self.value(),['enter-request','enter-start']),'trial-state')
    def test_start_after_positive_ready(self):self.assertEqual(c.next_operation('enter',self.value(),['enter-request']),'enter-start')
    def test_play_completes_enter(self):self.assertEqual(c.next_operation('enter',self.value(mode='play',trialIdentityBound=True),['enter-start']),'complete')
    def test_failed_upload_stops(self):
        with self.assertRaisesRegex(ValueError,'VALIDATION_OR_UPLOAD'):c.next_operation('enter',self.value(trialState=dict(taskPhase=12,entryReady=0)),['enter-request'])
    def test_uncertain_stops(self):
        with self.assertRaisesRegex(ValueError,'NOT_CLEAN'):c.next_operation('enter',self.value(outcomeUncertain=True),[])
    def test_exit_requires_bound_play(self):
        with self.assertRaisesRegex(ValueError,'BOUND_LIVE_TRIAL'):c.next_operation('exit',self.value(mode='play'),[])
    def test_return_only_once(self):self.assertEqual(c.next_operation('exit',self.value(mode='settlement',trialIdentityBound=True),['exit-request','exit-return']),'trial-state')
    def test_settlement_dispatches_official_return(self):self.assertEqual(c.next_operation('exit',self.value(mode='settlement',trialIdentityBound=True),['exit-request']),'exit-return')
    def test_return_complete_requires_original_editor(self):self.assertEqual(c.next_operation('exit',self.value(returnToOriginalEditorVerified=True),['exit-request']),'complete')

class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';self.folder.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=self.folder);self.run=Path(self.temp.name);(self.run/'prepared.json').write_text('{}')
    def tearDown(self):self.temp.cleanup()
    def test_first_entry_claim_and_repeat_refusal(self):
        p=dict(mode='enter-request');b.claim_write(self.run,p)
        with self.assertRaises(FileExistsError):b.claim_write(self.run,p)
    def test_two_cards_cannot_replay_same_stage(self):
        p=dict(mode='enter-start',lineage=dict(rootRun=str(self.run)));b.claim_write(self.run,p)
        other=self.run/'other';other.mkdir();(other/'prepared.json').write_text('{}')
        with self.assertRaises(FileExistsError):b.claim_write(other,p)
    def test_readonly_and_frame_do_not_consume_action_claim(self):
        for operation in ('trial-state','trial-frame'):b.claim_write(self.run,dict(mode=operation))
        self.assertEqual(list(self.run.glob('*.claim')),[])

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        ClaimTests.setUp(self);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='12345',deadlineTick=999)
        self.exit=dict(scope='FIXED_PLAYTEST_CONTROL',executed=True,exitCode=0,error=None)
    def tearDown(self):ClaimTests.tearDown(self)
    def decode(self,changes=None):
        record=dict(scope='FIXED_PLAYTEST_CONTROL',selfTestOnly=False,pid=123,tid=456,receiptNonce='12345',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True)
        record.update(changes or {})
        for name,value in (('exit.json',self.exit),('stdout.jsonl',record)):(self.run/name).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipts.decode_bound(self.run,self.card)
    def test_bound_success(self):self.assertTrue(self.decode()['playStateProven'])
    def test_nonce_rejects_cross_card_receipt(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(dict(receiptNonce='wrong'))
    def test_whole_binary_sha_bound(self):
        with self.assertRaisesRegex(ValueError,'SHA256_BINDING'):self.decode(dict(acceptanceSha256='0'*64))
    def test_native_exception_remains_uncertain(self):
        struct.pack_into('<I',self.data,12,0xc0000005);v=self.decode();self.assertTrue(v['outcomeUncertain']);self.assertFalse(v['safeToRelease'])
    def test_attempt_without_return_not_replayable(self):
        self.card['mode']='enter-start';self.data=raw(5);struct.pack_into('<I',self.data,36,0);struct.pack_into('<I',self.data,8,2)
        v=self.decode(dict(ok=False));self.assertTrue(v['outcomeUncertain']);self.assertTrue(v['replayForbidden']);self.assertFalse(v['safeToRelease']);self.assertTrue(v['cleanupVerified'])
    def test_render_extracts_only_bound_game_png(self):
        self.card['mode']='trial-frame';self.data=raw(8);v=self.decode();self.assertEqual((self.run/'frame.png').read_bytes(),ImageFixture.png());self.assertFalse(v['readOnly']);self.assertFalse(v['changesTrialMode'])
    def test_wrapper_refusal_has_no_native_attempt(self):
        self.exit.update(executed=False,error='PIN_CHANGED');v=self.decode();self.assertFalse(v['nativeStarted']);self.assertTrue(v['cleanupVerified'])

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        ClaimTests.setUp(self);self.session=dict(pid=1,tid=2);self.states={};self.manifests={};self.proofs=[]
    def tearDown(self):ClaimTests.tearDown(self)
    def add(self,operation,state_value=None):
        at=self.run/str(len(self.manifests));at.mkdir()
        for name in b.PROOF_NAMES:(at/name).write_bytes(name.encode())
        ancestors=list(self.proofs);root=str(self.run/'0');attempted=[x['mode'] for x in self.manifests.values() if x['mode']!='trial-state']
        p=dict(kind='playtest-control-prepared-v3',run=str(at),mode=operation,session=self.session,targetLevelId=1843,lineage=dict(rootRun=root,ancestors=ancestors,attemptedOperations=attempted) if ancestors else {},binding={})
        s=state_value or state(token=3,roomToken=3,cacheEditData=0x50000)
        result=dict(ok=True,safeToRelease=True,outcomeUncertain=False,trialState=s,nativeReceipt=dict(before=s,stateStable=1),actionAttempted=operation!='trial-state',mode='editor')
        self.manifests[str(at)]=p;self.states[str(at)]=result;self.proofs.append(dict(run=str(at),hashes={n:contract.sha(at/n) for n in b.PROOF_NAMES}));return at
    def previous(self,at,operation='trial-state'):
        import receipt
        with patch.object(receipt,'manifest',side_effect=lambda x:(Path(x),self.manifests[str(x)],{})),patch.object(receipt,'decode',side_effect=lambda x:self.states[str(x)]):return b.previous(at,self.session,1843,operation)
    def test_original_raw_evidence_chain(self):
        root=self.add('enter-request');lineage,binding=self.previous(root);self.assertEqual(lineage['attemptedOperations'],['enter-request']);self.assertEqual(binding['initialToken'],3)
    def test_ancestor_raw_change_is_rejected(self):
        root=self.add('enter-request');observe=self.add('trial-state');(root/'acceptance.bin').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'ANCESTOR_CHANGED'):self.previous(observe)
    def test_missing_original_entry_is_rejected(self):
        root=self.add('trial-state')
        with self.assertRaisesRegex(ValueError,'ROOT_REQUEST'):self.previous(root)
    def test_repeated_mutation_is_rejected(self):
        self.add('enter-request');other=self.add('enter-request')
        with self.assertRaisesRegex(ValueError,'MUTATION_REPLAY'):self.previous(other)
    def test_fresh_server_token_and_export_required(self):
        root=self.add('enter-request');observe=self.add('trial-state',state(entryReady=1,token=3,roomToken=3,cacheEditData=0x50000))
        with self.assertRaisesRegex(ValueError,'FRESH_TOKEN'):self.previous(observe,'enter-start')
    def test_ready_state_binds_new_trial_cache(self):
        self.add('enter-request');observe=self.add('trial-state',state(entryReady=1,token=8,roomToken=8,cacheEditData=0x70000))
        lineage,binding=self.previous(observe,'enter-start');self.assertEqual(binding['token'],8);self.assertEqual(binding['cacheEditData'],0x70000)
    def test_conflicting_session_rejected(self):
        root=self.add('enter-request');self.manifests[str(root)]['session']={}
        with self.assertRaisesRegex(ValueError,'PREVIOUS_CARD_TARGET'):self.previous(root)

class CandidateTests(unittest.TestCase):
    def test_native_generated_card_keeps_transport_and_control_abi(self):
        scratch=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            run=Path(temp);b.copy_sources(run)
            header=(run/'candidate-source/native/hook_receipt_protocol.h').read_text();hook=(run/'candidate-source/native/hook_receipt.cpp').read_text();probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text()
            self.assertIn('ControlReceipt acceptance;',header);self.assertIn('kReceiptVersion=24;',header);self.assertIn('ExecuteControl(&receipt->acceptance);',hook);self.assertIn('FIXED_PLAYTEST_CONTROL',probe);self.assertIn('CALG_SHA_256',probe);self.assertNotIn('*receipt = {};',probe)

if __name__=='__main__':unittest.main()
