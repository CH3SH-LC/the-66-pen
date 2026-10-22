"""Offline serial workflow/receipt-bound aggregation; no game or queue access."""
import copy
from contextlib import ExitStack, nullcontext
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import asset_inspection_sequence as s
import asset_inspection as cli
import asset_inspection_common as c
from asset_inspection_tests import fixture
from asset_inspection_templates_tests import session,catalog

class SequenceTests(unittest.TestCase):
    def setUp(self):
        c.OUTPUT.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(prefix='sequence-contract-',dir=c.OUTPUT)).resolve();self.stack=ExitStack()
        self.tick=0;self.next_id=20;self.serial=0;self.measure_fail=False;self.geometry_missing=False;self.unsafe=False;self.calls=[]
        self.current=dict(version=2,entities=[self.entity(1,99)],pointers={'currentContext':123},origin=[0,0,0],levelObservation={'levelId':1843})
        self.selection=self.root/'selection.json';c.write(self.selection,dict(schema='mw-city-role-selection-verified',grade='thumbnail-reviewed',roles={
            str(i):dict(templateId=i,alternativesSameStyle=[],evidence='fixture declared selection') for i in (99,100,101)}))
        self.icons=self.root/'icons.json';c.write(self.icons,{'fixture':True});self.inventory=self.root/'inventory.json';c.write(self.inventory,{'fixture':True})
        self.source=self.root/'official.bin';self.source.write_bytes(b'fixture')
        self.stack.enter_context(patch.object(s,'now',side_effect=self.time))
        self.stack.enter_context(patch.object(s.b,'baseline',side_effect=self.read_baseline))
        self.stack.enter_context(patch.object(s.templates,'make_plan',side_effect=self.make_plan))
        self.stack.enter_context(patch.object(s.templates,'prepare_batch',side_effect=self.prepare_card))
        self.stack.enter_context(patch.object(s.scale,'prepare',side_effect=self.prepare_create))
        self.stack.enter_context(patch.object(s.scale,'validate_commit',side_effect=self.validate_commit))
        self.stack.enter_context(patch.object(s.receipts,'decode',side_effect=lambda run:c.read(Path(run)/'measurement.json')))
        self.stack.enter_context(patch.object(s.receipts,'cleanup_evidence',side_effect=lambda run:not self.unsafe))
        self.stack.enter_context(patch.object(s,'operation_lock',side_effect=lambda _:nullcontext()))
        owner=self
        class FakeLive:
            def __init__(self,*args):self.identity=session();self.bridge_run='11111111-2222-3333-4444-555555555555';self.queue=owner.root/'offline-queue'
            def inspect(self,level):owner.calls.append('inspect');return dict(ok=True,run=str(owner.new_baseline()))
            def create(self,operation):return owner.create(operation)
            def measure(self,run):owner.calls.append('measure');return c.read(Path(run)/'measurement.json')
            def delete_call(self,folder,op,ids):return owner.delete_call(folder,op,ids,self.bridge_run)
        self.stack.enter_context(patch.object(s,'Live',FakeLive))
    def tearDown(self):
        self.stack.close()
        if not self.root.is_relative_to(c.OUTPUT.resolve()):raise RuntimeError('unsafe fixture cleanup')
        shutil.rmtree(self.root)
    @staticmethod
    def entity(eid,tid):return dict(id=eid,configId=tid,owner=eid+1000,config=eid+2000,context=123,dictionaryKey=eid)
    def time(self):
        self.tick+=1;return (datetime(2026,10,17,tzinfo=timezone.utc)+timedelta(seconds=self.tick)).isoformat()
    def new_baseline(self):
        self.serial+=1;run=self.root/f'baseline-{self.serial:04d}';run.mkdir()
        for name in s.BASE_FILES:c.write(run/name,dict(finishedUtc=self.time()) if name=='exit.json' else {})
        c.write(run/'snapshot.json',self.current);return run
    def read_baseline(self,path,**kwargs):return session(),c.read(Path(path)/'snapshot.json'),b'fixture'
    def make_plan(self,selection,icons,out,*,baseline,include_alternatives=False):
        out=Path(out);out.mkdir();_,snap,_=self.read_baseline(baseline)
        selected=s.templates.selection_rows(c.read(self.selection));tids=list(dict.fromkeys(x['templateId'] for x in selected))
        batches,present,missing=s.templates.batches_for(snap,tids)
        rows=[dict(templateId=tid,roles=[r for r in selected if r['templateId']==tid],catalog=catalog(tid),thumbnail=dict(imagePath=str(self.source),imageSha256=c.sha(self.source)),
            officialTemplateFile=s.ref(self.source),capturedOfficialFile=s.ref(self.source),selectionConflict=False,sampleEntityIds=present.get(str(tid),[])) for tid in tids]
        result=dict(ok=True,kind=s.templates.PLAN_KIND,selection=dict(**s.ref(self.selection),includeAlternatives=False),icons=s.ref(self.icons),officialInventory=s.ref(self.inventory),
            baseline=s.baseline_ref(baseline),session=session(),levelId=1843,rows=rows,batches=batches,missingTemplateIds=missing)
        c.write(out/'plan.json',result);return result
    def initialize(self,*,empty=False,count=3):
        if empty:self.current['entities']=[]
        if count!=3:
            self.selection.write_text(json.dumps(dict(schema='mw-city-role-selection-verified',grade='thumbnail-reviewed',roles={
                str(i):dict(templateId=i,alternativesSameStyle=[],evidence='fixture') for i in range(99,99+count)})),encoding='utf-8')
        base=self.new_baseline();self.make_plan(self.selection,self.icons,self.root/'root-plan',baseline=base)
        result=s.initialize(self.root/'root-plan/plan.json',[0,0,0],self.root/'operation');self.operation=Path(result['operation']);return result
    def prepare_create(self,placement,name,level,**kwargs):
        run=self.root/name;run.mkdir();c.write(run/'placement.json',c.read(placement));return dict(ok=True,operation=str(run))
    def create(self,operation):
        self.calls.append('create');operation=Path(operation);placement=c.read(operation/'placement.json')['placements'][0]
        before=copy.deepcopy(self.current);self.next_id+=1;self.current['entities'].append(self.entity(self.next_id,placement['template_id']))
        run=operation/'native';run.mkdir();c.write(run/'prepared.json',{'session':session()});c.write(run/'exit.json',{'finishedUtc':self.time()})
        folder=operation/'batch-0000';folder.mkdir();c.write(folder/'commit.json',dict(run=str(run),before=before,after=self.current,ids=[self.next_id],placement=placement))
        return dict(ok=True,complete=True)
    def validate_commit(self,path,level,placements,expected_before=None):
        value=c.read(path);self.assertEqual(placements,[value['placement']]);self.assertEqual(level,1843)
        if expected_before is not None:s.scale.same_scene(expected_before,value['before'])
        return value['after'],value['ids']
    def prepare_card(self,path,index,baseline):
        plan=c.read(path);batch=plan['batches'][index];run=Path(path).parent/f'card-{index}';run.mkdir()
        samples=[]
        for eid in batch['entityIds']:
            item=fixture();item['entityId']=eid
            if self.geometry_missing:item['objects'][0]['geometry']=0
            sample=c.measure(item);tid=batch['templateIds'][str(eid)];sample.update(templateId=tid,catalog=catalog(tid));samples.append(sample)
        doc=dict(ok=not self.measure_fail,queryComplete=not self.measure_fail,sceneUnchanged=True,cleanupVerified=not self.unsafe,session=session(),levelId=1843,
            measurementPlan=dict(plan=str(Path(path).resolve()),planSha256=c.sha(path),selection=plan['selection'],batchIndex=index,templateIds=batch['templateIds']),
            createdUtc=self.time(),observedFinishedUtc=self.time(),measurements=samples,run=str(run),rawReceiptSha256='fixture-raw-'+run.name)
        c.write(run/'measurement.json',doc);return dict(ok=True,run=str(run))
    def delete_call(self,folder,op,ids,bridge):
        self.calls.append(op);folder=Path(folder);folder.mkdir();request=dict(kind='call',runId=bridge,op=op)
        if ids is not None:request['ids']=ids
        c.write(folder/'claim.json',dict(requestId=('%032x'%self.tick),request=request,startedUtc=self.time(),queueDir=str(self.root/'offline-queue')))
        if op=='catalog':reply=dict(ok=True,levelLifecycle=dict(payloadPresent=True,headerPresent=True,levelIdCandidate=1843,freshnessVerified=False))
        elif op==s.cleanup.DRY_OP:
            exists=[i for i in ids if i in s.scale.identities(self.current)]
            if exists==ids:reply=dict(ok=True,status='dry-run-mapping-only',invoked=False,requested=len(ids),resolvedCount=len(ids),mapping=[dict(id=i,frontendPath='/'+str(i)) for i in ids])
            else:reply=dict(ok=False,status='refused-unresolved-ids',invoked=False,unresolved=[dict(id=i,matches=0) for i in ids])
        else:
            self.current['entities']=[x for x in self.current['entities'] if x['id'] not in ids]
            reply=dict(ok=True,status='delete-requested-readback-pending',retryAllowed=False,invokedCount=len(ids),results=[dict(id=i,frontendPath='/'+str(i),invoked=True,nativeResult=True) for i in ids])
        c.write(folder/'submission.json',request);c.write(folder/'response.json',reply)
        (folder/'stdout.txt').write_text(json.dumps(reply),encoding='utf-8');(folder/'stderr.txt').write_text('',encoding='utf-8')
        code=0 if reply['ok'] else 1;c.write(folder/'end.json',dict(exitCode=code,finishedUtc=self.time(),stdoutSha256=c.sha(folder/'stdout.txt')))
        return s.cleanup.DispatchResult(code,[],json.dumps(reply),'',reply)
    def run_all(self,**kwargs):return s.run(self.operation,self.root/'session',self.root/'queue','11111111-2222-3333-4444-555555555555',**kwargs)
    def completed(self,**kwargs):self.initialize(**kwargs);return self.run_all()
    def stage_attempt(self,n=1):return self.operation/f'stage-{n:03d}/attempt-000'
    def mutate_attempt(self,fn,n=1):
        folder=self.stage_attempt(n);value=c.read(folder/'attempt.json');fn(value);(folder/'attempt.json').write_text(json.dumps(value),encoding='utf-8')
    def test_plan_is_offline_and_single_sample(self):
        out=self.initialize();self.assertEqual(self.calls,[]);self.assertEqual(out['maxSimultaneousTemporaryEntities'],1);self.assertEqual(len(out['stages']),3)
    def test_initial_report_is_not_ready(self):
        self.initialize();out=s.report(self.operation);self.assertFalse(out['allSelectedSizeEvidenceReady']);self.assertIsNone(out['cityTemplates'][0]['boundsRenderer'])
    def test_complete_existing_and_temporary_aggregate(self):
        out=self.completed();self.assertTrue(out['allSelectedSizeEvidenceReady']);self.assertEqual(len(out['stages']),3);self.assertEqual(len(self.current['entities']),1)
    def test_different_plan_sha_per_stage_supported(self):
        out=self.completed();self.assertEqual(len({x['plan']['sha256'] for x in out['stages']}),3)
    def test_twenty_three_templates_serial(self):
        out=self.completed(empty=True,count=23);self.assertTrue(out['sequenceComplete']);self.assertEqual(len(out['cityTemplates']),23);self.assertEqual(self.calls.count('create'),23);self.assertEqual(len(self.current['entities']),0)
    def test_resume_completed_stages_never_replays(self):
        self.completed();count=len(self.calls);self.assertTrue(self.run_all()['sequenceComplete']);self.assertEqual(count,len(self.calls))
    def test_bounded_stop_resume(self):
        self.initialize();first=self.run_all(max_stages=1);self.assertFalse(first['sequenceComplete']);second=self.run_all();self.assertTrue(second['sequenceComplete']);self.assertEqual(self.calls.count('create'),2)
    def test_pending_attempt_blocks_dispatch(self):
        self.initialize();(self.operation/'stage-000/attempt-000').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'PENDING_ATTEMPT'):self.run_all()
        self.assertEqual(self.calls,[])
    def test_unmeasured_geometry_never_guessed(self):
        self.geometry_missing=True;out=self.completed();self.assertTrue(out['sequenceComplete']);self.assertFalse(out['allSelectedSizeEvidenceReady']);self.assertIsNone(out['cityTemplates'][0]['boundsRenderer'])
    def test_known_measure_failure_still_removes_sample(self):
        self.initialize(empty=True);self.measure_fail=True;out=self.run_all();self.assertFalse(out['sequenceComplete']);self.assertTrue(out['allSamplesRecovered']);self.assertEqual(self.current['entities'],[])
    def test_failed_recovered_attempt_gets_new_attempt(self):
        self.initialize(empty=True);self.measure_fail=True;self.run_all(max_stages=1);self.measure_fail=False;out=self.run_all();self.assertTrue(out['sequenceComplete']);self.assertEqual(len(out['attemptHistory']),4)
    def test_unsafe_measurement_blocks_delete(self):
        self.initialize(empty=True);self.unsafe=True
        with self.assertRaisesRegex(ValueError,'CLEANUP_UNKNOWN'):self.run_all()
        self.assertNotIn(s.cleanup.DELETE_OP,self.calls);self.assertEqual(len(self.current['entities']),1)
    def test_unsafe_attempt_is_not_reported_recovered(self):
        self.initialize(empty=True);self.unsafe=True
        with self.assertRaises(ValueError):self.run_all()
        self.assertFalse(s.report(self.operation)['allSamplesRecovered'])
    def test_explicit_recovery_does_not_repeat_measure_or_create(self):
        self.initialize(empty=True);self.unsafe=True
        with self.assertRaises(ValueError):self.run_all()
        creates=self.calls.count('create');measures=self.calls.count('measure');self.unsafe=False;out=self.run_all(recover_stage=0)
        self.assertEqual(self.calls.count('create'),creates);self.assertEqual(self.calls.count('measure'),measures);self.assertTrue(out['allSamplesRecovered']);self.assertFalse(out['allSelectedSizeEvidenceReady'])
    def test_recovery_must_use_first_unfinished_stage(self):
        self.initialize()
        with self.assertRaisesRegex(ValueError,'FIRST_UNFINISHED'):self.run_all(recover_stage=2)
    def test_no_game_save_or_pose_preservation_claim(self):
        out=self.completed();self.assertFalse(out['persistentSaveVerified']);self.assertFalse(out['allOriginalTransformsPreservedVerified']);self.assertFalse(out['appearanceVerified'])
    def test_changed_selection_rejected(self):
        self.initialize();self.selection.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'):s.report(self.operation)
    def test_changed_root_plan_rejected(self):
        self.initialize();(self.root/'root-plan/plan.json').write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'):s.report(self.operation)
    def test_changed_attempt_artifact_rejected(self):
        self.completed();(self.stage_attempt()/'cleanup-owned.json').write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'):s.report(self.operation)
    def test_missing_artifact_pin_rejected(self):
        self.completed();self.mutate_attempt(lambda x:x['artifactHashes'].pop('cleanup-owned.json'))
        with self.assertRaisesRegex(ValueError,'ARTIFACT_SET'):s.report(self.operation)
    def test_wrong_created_id_rejected(self):
        self.completed();self.mutate_attempt(lambda x:x.update(entityIds=[999]))
        with self.assertRaisesRegex(ValueError,'CREATED_ID'):s.report(self.operation)
    def test_recovery_is_required_for_geometry(self):
        self.completed();self.mutate_attempt(lambda x:x['recovery'].update(deletedEntityIds=[]))
        with self.assertRaisesRegex(ValueError,'RECOVERY_IDS'):s.report(self.operation)
    def test_wrong_measurement_plan_binding_rejected(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run));out['measurementPlan']['planSha256']='wrong';return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'PLAN_BINDING'):s.report(self.operation)
    def test_wrong_measurement_session_rejected(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run));out['session']['processCreation']=9;return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'SESSION_OR_LEVEL'):s.report(self.operation)
    def test_measurement_after_removal_rejected(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run));out['observedFinishedUtc']='2027-01-01T00:00:00+00:00';return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'TIME_ORDER'):s.report(self.operation)
    def test_nonunit_sample_rejected(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run))
            for sample in out['measurements']:
                if sample['entityId']!=1:sample['pose']['scale']=[2,2,2]
            return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'UNIT_POSE'):s.report(self.operation)
    def test_original_entities_not_deleted(self):
        self.completed();self.assertEqual(self.current['entities'],[self.entity(1,99)])
        for file in self.operation.glob('stage-*/attempt-*/delete-calls/call-01/submission.json'):self.assertNotIn(1,c.read(file)['ids'])
    def test_editor_wrong_level_refuses_before_delete(self):
        self.initialize(empty=True);original=self.delete_call
        def changed(folder,op,ids,bridge):
            result=original(folder,op,ids,bridge)
            if op=='catalog':
                value=c.read(folder/'response.json');value['levelLifecycle']['levelIdCandidate']=1842
                (folder/'response.json').write_text(json.dumps(value),encoding='utf-8');(folder/'stdout.txt').write_text(json.dumps(value),encoding='utf-8')
                end=c.read(folder/'end.json');end['stdoutSha256']=c.sha(folder/'stdout.txt');(folder/'end.json').write_text(json.dumps(end),encoding='utf-8')
            return result
        with patch.object(self,'delete_call',side_effect=changed),self.assertRaisesRegex(ValueError,'EDITOR_LEVEL_MISMATCH'):self.run_all()
        self.assertNotIn(s.cleanup.DELETE_OP,self.calls)
    def test_deleted_absence_is_not_shared_cleanup_success(self):
        self.completed();report=c.read(self.stage_attempt()/'delete/result.json');self.assertEqual(report['exitCode'],s.cleanup.EXIT_UNKNOWN)
        self.assertTrue(s.report(self.operation)['allSamplesRecovered'])
    def test_unknown_delete_is_never_replayed(self):
        self.initialize(empty=True);original=self.delete_call
        def broken(folder,op,ids,bridge):
            result=original(folder,op,ids,bridge)
            if op==s.cleanup.DELETE_OP:
                (folder/'end.json').unlink();return s.cleanup.DispatchResult(-1,[],'','',None,launch_error='lost response')
            return result
        with patch.object(self,'delete_call',side_effect=broken),self.assertRaises(OSError):self.run_all()
        previous=self.calls.count(s.cleanup.DELETE_OP)
        with self.assertRaisesRegex(ValueError,'PENDING_ATTEMPT'):self.run_all()
        self.assertEqual(previous,self.calls.count(s.cleanup.DELETE_OP))
    def test_wrong_native_template_rejected(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run));out['measurements'][0]['templateId']=777;return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'TEMPLATE_ID'):s.report(self.operation)
    def test_missing_native_measurement_rejected(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run));out['measurements']=[];return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'BATCH_CHANGED'):s.report(self.operation)
    def test_unit_position_and_rotation_must_match(self):
        self.completed();old=s.receipts.decode
        def changed(run):
            out=copy.deepcopy(old(run))
            for sample in out['measurements']:
                if sample['entityId']!=1:sample['pose']['rotationDegrees']=[0,90,0]
            return out
        with patch.object(s.receipts,'decode',side_effect=changed),self.assertRaisesRegex(ValueError,'UNIT_POSE'):s.report(self.operation)
    def test_altered_stage_scope_rejected(self):
        self.initialize();path=self.operation/'sequence.json';value=c.read(path);value['stages'][1]['placement']['scale']=[2,2,2];path.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'STAGE_SCOPE'):s.report(self.operation)
    def test_unknown_stage_index_rejected_before_live(self):
        self.initialize()
        with self.assertRaisesRegex(ValueError,'STAGE_INDEX'):self.run_all(recover_stage=-1)
    def test_report_reads_only_no_live_calls(self):
        self.completed();calls=len(self.calls);s.report(self.operation);self.assertEqual(calls,len(self.calls))
    def test_step_claim_never_replayed(self):
        folder=self.root/'step';folder.mkdir();action=lambda:dict(ok=True)
        s.step(folder,'one',{'id':1},action)
        with patch.object(s,'new_json',side_effect=AssertionError('no writes')):self.assertEqual(s.step(folder,'one',{'id':1},action),{'ok':True})
    def test_step_without_result_is_unknown(self):
        folder=self.root/'step';(folder/'one').mkdir(parents=True);c.write(folder/'one/claim.json',{'request':{'id':1}})
        with self.assertRaisesRegex(ValueError,'OUTCOME_UNKNOWN'):s.step(folder,'one',{'id':1},lambda:self.fail('replayed'))
    def test_step_changed_request_rejected(self):
        folder=self.root/'step';folder.mkdir();s.step(folder,'one',{'id':1},lambda:{})
        with self.assertRaisesRegex(ValueError,'REQUEST_CHANGED'):s.step(folder,'one',{'id':2},lambda:{})
    def test_timezone_required(self):
        with self.assertRaisesRegex(ValueError,'TIMEZONE'):s.stamp('2026-10-17T00:00:00')
    def test_invalid_stage_bound(self):
        self.initialize()
        with self.assertRaisesRegex(ValueError,'STAGE_BOUND'):self.run_all(max_stages=0)
    def test_template_report_sequence_cli(self):
        self.initialize()
        with patch('sys.stdout') as output:self.assertEqual(cli.main(['template-report','--sequence',str(self.operation)]),0)
        self.assertTrue(output.write.called)
    def test_sequence_report_cannot_take_unbound_runs(self):
        self.initialize()
        with patch('sys.stdout'):self.assertEqual(cli.main(['template-report','--sequence',str(self.operation),'--run','anything']),2)
    def test_cli_live_errors_remain_conservative(self):
        with patch.object(s,'run',side_effect=ValueError('late uncertainty')),patch('builtins.print') as printer:
            self.assertEqual(cli.main(['sequence-run','--operation',str(self.root),'--session','x','--elevated-queue','x','--bridge-run-id','x']),2)
        value=json.loads(printer.call_args.args[0]);self.assertTrue(value['outcomeUncertain']);self.assertTrue(value['replayForbidden']);self.assertFalse(value['safeToRelease'])

if __name__=='__main__':unittest.main()
