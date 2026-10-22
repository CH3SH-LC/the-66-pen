"""Receipt-bound serial unit samples. Import/plan/report are offline; run is explicit.

Each attempt is immutable. A claimed step is never dispatched twice. Measurements
are admitted only after full scene identity recovery and raw delete reconciliation.
No image, template name or guessed dimensions can satisfy the geometry gate.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid
from asset_inspection_common import *
import asset_inspection_templates as templates
import asset_inspection_receipt as receipts
import build as b
import scene_scale as scale
import cleanup_owned_entities as cleanup

KIND='asset-inspection-sequential-measurement-v1'
BASE_FILES=('prepared.json','build-result.json','stdout.jsonl','exit.json')

def now():return datetime.now(timezone.utc).isoformat()
def stamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.tzinfo is not None,'SEQUENCE_TIMEZONE_REQUIRED');return result
def ref(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=sha(path))
def check_ref(value):
    path=Path(value['path']).resolve();templates.no_reparse(path)
    require(sha(path)==value['sha256'],'SEQUENCE_ARTIFACT_CHANGED:'+str(path));return path
def new_json(path,value):
    path=guarded_output(path);path.parent.mkdir(parents=True,exist_ok=True)
    scale.write(path,value);return value
def baseline_ref(run):
    run=Path(run).resolve();return dict(run=str(run),evidence={n:sha(run/n) for n in BASE_FILES})
def baseline(value,session,level):
    run=Path(value['run'])
    require(value['evidence']=={n:sha(run/n) for n in BASE_FILES},'SEQUENCE_BASELINE_CHANGED')
    actual,snapshot,_=b.baseline(run,require_fresh=False)
    require(templates.same_session(actual,session) and snapshot['levelObservation']['levelId']==level,'SEQUENCE_BASELINE_SESSION_OR_LEVEL')
    require(snapshot['version']==2,'SEQUENCE_REQUIRES_FULL_V2_BASELINE')
    end=read(run/'exit.json');return snapshot,stamp(end['finishedUtc'])

def plan_contract(plan,original=None):
    require(plan.get('kind')==templates.PLAN_KIND and plan.get('ok') is True and plan.get('baseline'),'SEQUENCE_REQUIRES_OBSERVED_PLAN')
    check_ref(plan['selection']);check_ref(plan['icons']);check_ref(plan['officialInventory'])
    selected=templates.selection_rows(read(plan['selection']['path']),plan['selection']['includeAlternatives'])
    tids=list(dict.fromkeys(x['templateId'] for x in selected))
    require([x['templateId'] for x in plan['rows']]==tids,'SEQUENCE_SELECTION_IDS_CHANGED')
    for row in plan['rows']:
        require(row['roles']==[x for x in selected if x['templateId']==row['templateId']],'SEQUENCE_ROLE_EVIDENCE_CHANGED')
        require(row['selectionConflict']==any(x['selectionConflict'] for x in row['roles']),'SEQUENCE_SELECTION_CONFLICT_CHANGED')
        thumbnail=row['thumbnail'];require(sha(thumbnail['imagePath'])==thumbnail['imageSha256'],'SEQUENCE_THUMBNAIL_CHANGED')
        for key in ('officialTemplateFile','capturedOfficialFile'):check_ref(row[key])
    if original is not None:
        require(plan['selection']==original['selection'] and plan['icons']==original['icons'],'SEQUENCE_SELECTION_OR_ICONS_CHANGED')
        require(templates.same_session(plan['session'],original['session']) and plan['levelId']==original['levelId'],'SEQUENCE_PLAN_SESSION_OR_LEVEL')
        require([(r['templateId'],r['officialTemplateFile']['sha256']) for r in plan['rows']]==[(r['templateId'],r['officialTemplateFile']['sha256']) for r in original['rows']],'SEQUENCE_TEMPLATE_SOURCE_CHANGED')
    return tids

def initialize(plan_path,anchor,out):
    source=ref(plan_path);plan=read(check_ref(source));tids=plan_contract(plan)
    require(len(anchor)==3 and all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=100000 for v in anchor),'SEQUENCE_ANCHOR_REQUIRED')
    snapshot,_=baseline(plan['baseline'],plan['session'],plan['levelId'])
    batches,present,missing=templates.batches_for(snapshot,tids)
    require(missing==plan['missingTemplateIds'],'SEQUENCE_PLAN_MISSING_SET')
    stages=[]
    if batches:stages.append(dict(index=0,mode='existing',templateIds=[v for v in tids if str(v) in present],entityIds=[e for batch in batches for e in batch['entityIds']]))
    for tid in missing:stages.append(dict(index=len(stages),mode='temporary',templateIds=[tid],entityIds=None,
        placement=dict(template_id=tid,position=list(anchor),rotation=[0.,0.,0.],scale=[1.,1.,1.])))
    require(stages,'SEQUENCE_EMPTY');out=guarded_output(out)
    require(out.is_relative_to(ROOT/'.runtime') and not out.exists(),'SEQUENCE_OUTPUT_MUST_BE_NEW_RUNTIME_DIRECTORY')
    out.mkdir(parents=True)
    source_paths=list(HERE.glob('asset_inspection*.py'))+[HERE/'scene_scale.py',HERE/'cleanup_owned_entities.py']
    result=dict(ok=True,kind=KIND,operation=str(out),operationId=uuid.uuid4().hex,createdUtc=now(),rootPlan=source,
        sourceHashes={str(p):sha(p) for p in source_paths},
        selection=plan['selection'],session=plan['session'],levelId=plan['levelId'],anchor=list(anchor),stages=stages,
        maxSimultaneousTemporaryEntities=1,placementAuthorization='User-authorized reversible measurement samples; actual dispatch only in the coordinator unified execution phase',
        anchorClearanceVerified=False,gameWritesPerformed=False,called=False,allSelectedSizeEvidenceReady=False,
        recoveryScope='Complete original entity identity set; original poses, save/reopen and pixels are not asserted')
    new_json(out/'sequence.json',result);return result

def load(operation):
    path=guarded_output(operation);require(path.is_relative_to(ROOT/'.runtime'),'SEQUENCE_RUNTIME_ONLY')
    document=read(path/'sequence.json');require(document.get('kind')==KIND and document.get('operation')==str(path),'SEQUENCE_SCHEMA')
    plan=read(check_ref(document['rootPlan']));plan_contract(plan)
    require(document['selection']==plan['selection'] and templates.same_session(document['session'],plan['session']) and document['levelId']==plan['levelId'],'SEQUENCE_ROOT_BINDING')
    original,_=baseline(plan['baseline'],document['session'],document['levelId'])
    tids=[x['templateId'] for x in plan['rows']];batches,present,missing=templates.batches_for(original,tids)
    expected=[]
    if batches:expected.append(dict(index=0,mode='existing',templateIds=[v for v in tids if str(v) in present],entityIds=[e for batch in batches for e in batch['entityIds']]))
    for tid in missing:expected.append(dict(index=len(expected),mode='temporary',templateIds=[tid],entityIds=None,
        placement=dict(template_id=tid,position=document['anchor'],rotation=[0.,0.,0.],scale=[1.,1.,1.])))
    require(document['stages']==expected,'SEQUENCE_STAGE_SCOPE_CHANGED')
    return path,document,plan,original

@contextmanager
def operation_lock(operation):
    # OS lock releases on process exit; immutable step claims still forbid replay.
    import msvcrt
    with (operation/'sequence.lock').open('a+b') as stream:
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise ValueError('SEQUENCE_BUSY') from exc
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def step(folder,name,request,action):
    directory=folder/name;directory.mkdir(exist_ok=True);claim=directory/'claim.json';result=directory/'result.json'
    if claim.exists():
        require(read(claim)['request']==request,'SEQUENCE_STEP_REQUEST_CHANGED')
        require(result.exists(),'SEQUENCE_STEP_OUTCOME_UNKNOWN_DO_NOT_REPLAY:'+str(directory))
        return read(result)
    new_json(claim,dict(request=request,startedUtc=now()))
    try:value=action()
    except Exception as exc:
        new_json(directory/'error.json',dict(error=str(exc),finishedUtc=now(),replayForbidden=True));raise
    new_json(result,value);new_json(directory/'end.json',dict(finishedUtc=now(),result=ref(result)))
    return value

class Live:
    """Only constructed by explicit sequence-run/recover; no import-time transport."""
    def __init__(self,session,queue,bridge_run):
        self.session=Path(session).resolve();self.queue=Path(queue).resolve();self.bridge_run=str(uuid.UUID(bridge_run))
        require(cleanup.check_queue_dir(self.queue) is None,'SEQUENCE_QUEUE_NOT_ALLOWED')
        self.identity=read(self.session)
    def inspect(self,level):return scale.send('inspect',self.session,level,queue=self.queue)
    def create(self,operation):return scale.run(operation,self.session,queue=self.queue,max_batches=1,save=False)
    def measure(self,run):
        from asset_inspection import dispatch
        return dispatch(run,queue=self.queue)
    def delete_call(self,folder,op,ids):
        folder.mkdir(exist_ok=False);rid=uuid.uuid4().hex
        request=dict(kind='call',runId=self.bridge_run,op=op)
        if ids is not None:request['ids']=ids
        argv=[sys.executable,'-B',str(cleanup.ELEVATED_REQUEST),'--queue-dir',str(self.queue),'call','--op',op,'--run-id',self.bridge_run,'--timeout','300','--request-id',rid]
        if ids is not None:argv+=['--ids',*[str(x) for x in ids]]
        new_json(folder/'claim.json',dict(requestId=rid,request=request,queueDir=str(self.queue),startedUtc=now()))
        try:
            p=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=330,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (folder/'stdout.txt').write_text(p.stdout,encoding='utf-8');(folder/'stderr.txt').write_text(p.stderr,encoding='utf-8')
            parsed=json.loads(p.stdout);require(isinstance(parsed,dict),'DELETE_RESPONSE_OBJECT_REQUIRED')
            for suffix in ('submission.json','response.json'):
                source=self.queue/(rid+'.'+suffix);require(source.is_file(),'DELETE_QUEUE_EVIDENCE_MISSING')
                (folder/suffix).write_bytes(source.read_bytes())
            require(read(folder/'submission.json')==request and read(folder/'response.json')==parsed,'DELETE_QUEUE_RESPONSE_BINDING')
            new_json(folder/'end.json',dict(exitCode=p.returncode,finishedUtc=now(),stdoutSha256=sha(folder/'stdout.txt')))
            return cleanup.DispatchResult(p.returncode,argv[argv.index('call'):],p.stdout,p.stderr,parsed)
        except Exception as exc:
            new_json(folder/'error.json',dict(error=str(exc),finishedUtc=now(),outcomeUncertain=True,replayForbidden=True))
            return cleanup.DispatchResult(-1,argv[argv.index('call'):],'','',None,launch_error=str(exc))

def observe(folder,name,live,document,expected):
    reply=step(folder,name,dict(action='inspect',levelId=document['levelId']),lambda:live.inspect(document['levelId']))
    require(reply.get('ok') is True and not reply.get('outcomeUncertain'),'SEQUENCE_INSPECT_INCOMPLETE')
    evidence=baseline_ref(reply['run']);snapshot,_=baseline(evidence,document['session'],document['levelId'])
    scale.same_scene(expected,snapshot);return evidence,snapshot

def create_binding(folder,stage,document,before):
    operation=Path(read(folder/'creation-operation.json')['operation']);commit=operation/'batch-0000/commit.json'
    after,ids=scale.validate_commit(commit,document['levelId'],[stage['placement']],expected_before=before)
    prepared=read(Path(read(commit)['run'])/'prepared.json')
    require(templates.same_session(prepared['session'],document['session']),'SEQUENCE_CREATE_SESSION_CHANGED')
    require(len(ids)==1,'SEQUENCE_SINGLE_SAMPLE_REQUIRED')
    return after,ids,ref(commit)

def call_evidence(directory):
    claim=read(directory/'claim.json')
    if (directory/'reconciled.json').exists():
        note=read(directory/'reconciled.json');request=read(check_ref(note['submission']));reply=read(check_ref(note['response']))
        require(note['requestId']==claim['requestId'] and note['request']==claim['request'],'SEQUENCE_RECONCILED_REQUEST_CHANGED')
        return claim,dict(exitCode=0 if reply.get('ok') is True else 1,finishedUtc=note['observedUtc']),request,reply
    end=read(directory/'end.json');request=read(directory/'submission.json');reply=read(directory/'response.json')
    require(end['stdoutSha256']==sha(directory/'stdout.txt') and json.loads((directory/'stdout.txt').read_text(encoding='utf-8'))==reply,'SEQUENCE_DELETE_RAW_RESPONSE_CHANGED')
    return claim,end,request,reply

def reconcile_call(directory):
    """Read the original request's completed queue files; never poll or re-enqueue."""
    if (directory/'end.json').exists() or (directory/'reconciled.json').exists():return
    claim=read(directory/'claim.json');queue=Path(claim['queueDir']);rid=claim['requestId']
    require(cleanup.check_queue_dir(queue) is None,'SEQUENCE_RECONCILE_QUEUE')
    source_request=queue/(rid+'.submission.json');source_reply=queue/(rid+'.response.json')
    require(read(source_request)==claim['request'],'SEQUENCE_ORIGINAL_SUBMISSION_CHANGED')
    reply=read(source_reply);require(isinstance(reply,dict) and not reply.get('pending') and not reply.get('outcomeUncertain'),'SEQUENCE_ORIGINAL_RESPONSE_NOT_TERMINAL')
    for source,name in ((source_request,'recovered.submission.json'),(source_reply,'recovered.response.json')):
        target=directory/name
        if target.exists():require(sha(target)==sha(source),'SEQUENCE_RECONCILED_SOURCE_CHANGED')
        else:target.write_bytes(source.read_bytes())
    new_json(directory/'reconciled.json',dict(requestId=rid,request=claim['request'],observedUtc=now(),
        submission=ref(directory/'recovered.submission.json'),response=ref(directory/'recovered.response.json'),
        originalStdoutRecovered=False,queueResponseRecovered=True,replayAttempted=False))

def verify_editor_guard(folder,level):
    directory=folder/'editor-guard';claim,end,request,reply=call_evidence(directory)
    require(request==claim['request'] and request['kind']=='call' and request['op']=='catalog' and 'ids' not in request,'SEQUENCE_EDITOR_GUARD_REQUEST')
    require(end['exitCode']==0,'SEQUENCE_EDITOR_GUARD_RESPONSE')
    observed=reply.get('levelLifecycle',{})
    require(reply.get('ok') is True and observed.get('payloadPresent') is True and observed.get('headerPresent') is True and observed.get('levelIdCandidate')==level,'SEQUENCE_EDITOR_LEVEL_MISMATCH')
    return request['runId'],stamp(end['finishedUtc'])

def verify_delete(folder,ids,level,session):
    bridge_run,guard_end=verify_editor_guard(folder,level)
    calls=sorted((folder/'delete-calls').glob('call-*'))
    require(2<=len(calls)<=3,'SEQUENCE_DELETE_CALL_COUNT')
    mapping=None;last=guard_end;references=[];request_ids=set()
    for index,call in enumerate(calls):
        claim,end,request,reply=call_evidence(call)
        require(claim['request']==request and request['ids']==ids and request['kind']=='call','SEQUENCE_DELETE_REQUEST_CHANGED')
        require(request['runId']==bridge_run and claim['requestId'] not in request_ids,'SEQUENCE_DELETE_BRIDGE_OR_REQUEST_REUSED');request_ids.add(claim['requestId'])
        uuid.UUID(request['runId']);require(len(claim['requestId'])==32,'SEQUENCE_DELETE_REQUEST_ID')
        require(end['exitCode'] in (0,1),'SEQUENCE_DELETE_EXIT_CODE')
        begin=stamp(claim['startedUtc']);finish=stamp(end['finishedUtc']);require(begin<=finish and (last is None or last<=begin),'SEQUENCE_DELETE_ORDER')
        last=finish;result=cleanup.DispatchResult(end['exitCode'],[],json.dumps(reply),'',reply)
        require(request['op']==(cleanup.DELETE_OP if index==1 else cleanup.DRY_OP),'SEQUENCE_DELETE_OPERATION_ORDER')
        if index==0:
            mapping,error=cleanup.classify_dry_run(result,ids);require(error is None,'SEQUENCE_DELETE_DRY_RUN_INVALID')
        elif index==1:
            ledger,error,unknown,warnings=cleanup.classify_execute(result,ids,mapping)
            require(error is None and unknown is None and not warnings and all(ledger.get(e)=='dispatched' for e in ids),'SEQUENCE_DELETE_NOT_FULLY_DISPATCHED')
        else:
            if reply.get('ok') is True:
                _,error=cleanup.classify_dry_run(result,ids);require(error is None,'SEQUENCE_DELETE_READBACK_INVALID')
            else:
                missing=reply.get('unresolved',[])
                require(reply.get('status')=='refused-unresolved-ids' and reply.get('invoked') is False and len(missing)==len(ids) and
                    {x.get('id') for x in missing}==set(ids) and all(x.get('matches')==0 for x in missing),'SEQUENCE_DELETE_READBACK_UNKNOWN')
        recovered=(call/'reconciled.json').exists();prefix='recovered.' if recovered else ''
        references.append(dict(directory=str(call),requestId=claim['requestId'],submission=ref(call/(prefix+'submission.json')),response=ref(call/(prefix+'response.json')),queueResponseRecovered=recovered))
    return last,references

def cleanup_sample(folder,stage,document,before,after_create,ids,live,*,recover_only=False):
    if recover_only and (folder/'delete/claim.json').exists():
        # A deletion might already have happened. Reconcile only the original request;
        # no automatic second delete. Unknown/nonterminal responses remain blocked.
        reconcile_call(folder/'editor-guard')
        for call in sorted((folder/'delete-calls').glob('call-*')):reconcile_call(call)
        verify_delete(folder,ids,document['levelId'],document['session'])
        current=baseline_ref(read(folder/'cleanup-before/result.json')['run'])
        name='recovery-observe-'+uuid.uuid4().hex
        recovered,_=observe(folder,name,live,document,before)
        return dict(beforeDelete=current,afterBaseline=recovered,deletedEntityIds=ids,identityRecoveryVerified=True,
            allOriginalTransformsPreservedVerified=False,persistentSaveVerified=False,originalDeleteReconciled=True)
    current,current_snapshot=observe(folder,'cleanup-before',live,document,after_create)
    # Derivatives are explicitly bound to validated native snapshots and commit IDs.
    for name,value in [('cleanup-current.json',current_snapshot),('cleanup-pre.json',before),
                       ('cleanup-owned.json',dict(levelId=document['levelId'],templateId=stage['templateIds'][0],placedIds=ids))]:
        if not(folder/name).exists():new_json(folder/name,value)
        else:require(read(folder/name)==value,'SEQUENCE_CLEANUP_DERIVATIVE_CHANGED')
    def invoke():
        guard=live.delete_call(folder/'editor-guard','catalog',None)
        require(guard.launch_error is None,'SEQUENCE_EDITOR_GUARD_UNKNOWN')
        verify_editor_guard(folder,document['levelId'])
        counter=0;(folder/'delete-calls').mkdir(exist_ok=False)
        def dispatch(op,wanted):
            nonlocal counter
            require(wanted==ids,'SEQUENCE_DELETE_SCOPE_CHANGED')
            target=folder/'delete-calls'/f'call-{counter:02d}';counter+=1
            return live.delete_call(target,op,wanted)
        run=cleanup.CleanupRun(receipts=[folder/'cleanup-owned.json'],baseline=folder/'cleanup-current.json',pre_baseline=folder/'cleanup-pre.json',
            level_id=document['levelId'],mode='execute',dispatch=dispatch,run_id=live.bridge_run,queue_dir=str(live.queue))
        return run.execute()
    result=step(folder,'delete',dict(ids=ids,levelId=document['levelId'],beforeBaseline=current),invoke)
    # Even a readable partial response is never resent. A fresh full snapshot settles absence.
    # The shared module treats "all IDs no longer resolve" as an inconclusive
    # dry-run. We retain that raw verdict and prove recovery from the subsequent
    # complete native identity snapshot, never reinterpret it as deletion proof.
    require(result.get('ownedIds')==ids,'SEQUENCE_CLEANUP_OWNERSHIP_INCOMPLETE')
    verify_delete(folder,ids,document['levelId'],document['session'])
    recovered,_=observe(folder,'recovered',live,document,before)
    return dict(beforeDelete=current,afterBaseline=recovered,deletedEntityIds=ids,identityRecoveryVerified=True,
        allOriginalTransformsPreservedVerified=False,persistentSaveVerified=False)

def execute_attempt(folder,stage,document,root_plan,original,live,*,recover_only=False):
    before_ref,before=observe(folder,'before',live,document,original)
    expected=before;ids=stage['entityIds'];creation=None
    if stage['mode']=='temporary':
        if not(folder/'creation-operation.json').exists():
            require(not recover_only,'SEQUENCE_NO_CREATE_BINDING_TO_RECOVER')
            placement=folder/'placement.json';new_json(placement,dict(coordinateSpace='world',placements=[stage['placement']]))
            operation=scale.prepare(placement,'asset-'+document['operationId']+'-'+folder.parent.name+'-'+folder.name,document['levelId'],batch_size=1)
            new_json(folder/'creation-operation.json',operation)
        operation=read(folder/'creation-operation.json')['operation']
        if not recover_only:step(folder,'create',dict(operation=operation),lambda:live.create(operation))
        expected,ids,creation=create_binding(folder,stage,document,before)
    successful=False;runs=[];plan_ref=None;failure=None
    try:
        if recover_only:
            # Never remove a sample while a claimed measurement may still be running.
            for claim in folder.glob('measure-*/claim.json'):
                run=read(claim)['request']['run'];require(receipts.cleanup_evidence(run),'SEQUENCE_MEASUREMENT_CLEANUP_UNKNOWN')
            failure='EXPLICIT_RECOVERY_WITHOUT_REPLAY'
        else:
            measured_baseline,_=observe(folder,'measurement-before',live,document,expected)
            plan_dir=folder/'fresh-plan'
            if not(plan_dir/'plan.json').exists():
                templates.make_plan(root_plan['selection']['path'],root_plan['icons']['path'],plan_dir,
                    baseline=measured_baseline['run'],include_alternatives=root_plan['selection']['includeAlternatives'])
            plan_ref=ref(plan_dir/'plan.json');plan=read(plan_ref['path']);plan_contract(plan,root_plan)
            indices=[batch['index'] for batch in plan['batches'] if set(batch['entityIds'])&set(ids)]
            require(indices,'SEQUENCE_NO_MEASUREMENT_BATCH')
            for index in indices:
                fresh,_=observe(folder,f'inspect-{index:04d}',live,document,expected)
                built=step(folder,f'prepare-{index:04d}',dict(plan=plan_ref,batch=index,baseline=fresh),
                    lambda:templates.prepare_batch(plan_ref['path'],index,fresh['run']))
                run=built['run'];runs.append(run)
                step(folder,f'measure-{index:04d}',dict(run=run),lambda:live.measure(run))
                result=receipts.decode(run)
                require(result.get('cleanupVerified') is True,'SEQUENCE_MEASUREMENT_CLEANUP_UNKNOWN')
                require(result.get('ok') is True and result.get('queryComplete') is True,'SEQUENCE_MEASUREMENT_FAILED')
            successful=True
    except Exception as exc:
        failure=str(exc)
        for claim in folder.glob('measure-*/claim.json'):
            require(receipts.cleanup_evidence(read(claim)['request']['run']),'SEQUENCE_MEASUREMENT_CLEANUP_UNKNOWN')
    recovery=None
    if stage['mode']=='temporary':recovery=cleanup_sample(folder,stage,document,before,expected,ids,live,recover_only=recover_only)
    else:
        recovered,_=observe(folder,'recovered',live,document,before)
        recovery=dict(afterBaseline=recovered,deletedEntityIds=[],identityRecoveryVerified=True,allOriginalTransformsPreservedVerified=False,persistentSaveVerified=False)
    result=dict(ok=True,kind='asset-inspection-sequence-attempt-v1',sequenceSha256=sha(Path(document['operation'])/'sequence.json'),
        stageIndex=stage['index'],mode=stage['mode'],successfulMeasurement=successful,failure=failure,entityIds=ids,
        beforeBaseline=before_ref,plan=plan_ref,creationCommit=creation,measurementRuns=runs,recovery=recovery,
        finishedUtc=now(),replayForbidden=True)
    result['artifactHashes']={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}
    new_json(folder/'attempt.json',result);return result

def validate_attempt(folder,document,root_plan,original,stage):
    folder=Path(folder);attempt=read(folder/'attempt.json')
    require(attempt.get('kind')=='asset-inspection-sequence-attempt-v1' and attempt.get('sequenceSha256')==sha(Path(document['operation'])/'sequence.json') and attempt['stageIndex']==stage['index'] and attempt['mode']==stage['mode'],'SEQUENCE_ATTEMPT_BINDING')
    actual_files={p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p!=folder/'attempt.json'}
    require(set(attempt['artifactHashes'])==actual_files,'SEQUENCE_ATTEMPT_ARTIFACT_SET_CHANGED')
    for name,digest in attempt['artifactHashes'].items():
        path=(folder/name).resolve();require(path.is_relative_to(folder.resolve()) and sha(path)==digest,'SEQUENCE_ATTEMPT_ARTIFACT_CHANGED')
    for claim in folder.glob('measure-*/claim.json'):
        require(receipts.cleanup_evidence(read(claim)['request']['run']),'SEQUENCE_MEASUREMENT_CLEANUP_UNKNOWN')
    before,start=baseline(attempt['beforeBaseline'],document['session'],document['levelId']);scale.same_scene(original,before)
    recovered,end=baseline(attempt['recovery']['afterBaseline'],document['session'],document['levelId']);scale.same_scene(before,recovered)
    require(start<=end,'SEQUENCE_RECOVERY_PRECEDES_ATTEMPT')
    ids=attempt['entityIds'];creation_end=start;delete_start=end
    require(type(attempt['successfulMeasurement']) is bool,'SEQUENCE_MEASUREMENT_STATUS_TYPE')
    if stage['mode']=='temporary':
        after,expected_ids,commit=create_binding(folder,stage,document,before)
        require(ids==expected_ids and attempt['creationCommit']==commit,'SEQUENCE_CREATED_ID_OR_COMMIT_CHANGED')
        create_run=Path(read(check_ref(commit))['run']);creation_end=stamp(read(create_run/'exit.json')['finishedUtc'])
        require(start<=creation_end<=end,'SEQUENCE_CREATE_TIME_ORDER')
        _,delete_finished=baseline(attempt['recovery']['beforeDelete'],document['session'],document['levelId'])
        current,_=baseline(attempt['recovery']['beforeDelete'],document['session'],document['levelId']);scale.same_scene(after,current)
        last,delete_refs=verify_delete(folder,ids,document['levelId'],document['session'])
        delete_start=stamp(read(folder/'delete-calls/call-00/claim.json')['startedUtc'])
        require(creation_end<=delete_finished<=delete_start<=last<=end,'SEQUENCE_DELETE_TIME_ORDER')
        require(attempt['recovery']['deletedEntityIds']==ids and not set(ids)&scale.identities(recovered).keys(),'SEQUENCE_SAMPLE_RECOVERY_IDS')
    else:
        require(ids==stage['entityIds'] and attempt['creationCommit'] is None and attempt['recovery']['deletedEntityIds']==[],'SEQUENCE_EXISTING_SCOPE_CHANGED')
        delete_refs=[]
    samples=[];run_refs=[];seen=set()
    if attempt['successfulMeasurement']:
        plan_path=check_ref(attempt['plan']);plan=read(plan_path);plan_contract(plan,root_plan)
        planned,_=baseline(plan['baseline'],document['session'],document['levelId'])
        scale.same_scene(after if stage['mode']=='temporary' else before,planned)
        allowed={eid:tid for batch in plan['batches'] for eid,tid in batch['templateIds'].items()}
        for run in attempt['measurementRuns']:
            report=receipts.decode(run)
            require(report.get('ok') is True and report.get('queryComplete') is True and report.get('sceneUnchanged') is True and report.get('cleanupVerified') is True,'SEQUENCE_REQUIRES_COMPLETE_RAW_MEASUREMENT')
            require(templates.same_session(report['session'],document['session']) and report['levelId']==document['levelId'],'SEQUENCE_MEASUREMENT_SESSION_OR_LEVEL')
            binding=report.get('measurementPlan') or {}
            require(binding.get('plan')==str(plan_path) and binding.get('planSha256')==attempt['plan']['sha256'] and binding.get('selection')==document['selection'],'SEQUENCE_MEASUREMENT_PLAN_BINDING')
            require(creation_end<=stamp(report['createdUtc'])<=stamp(report['observedFinishedUtc'])<=delete_start,'SEQUENCE_MEASUREMENT_TIME_ORDER')
            batch=plan['batches'][binding['batchIndex']]
            require(binding['templateIds']==batch['templateIds'] and {x['entityId'] for x in report['measurements']}==set(batch['entityIds']),'SEQUENCE_MEASUREMENT_BATCH_CHANGED')
            for sample in report['measurements']:
                eid=sample['entityId'];require(allowed.get(str(eid))==sample['templateId'],'SEQUENCE_MEASUREMENT_TEMPLATE_ID')
                if eid not in ids:continue # Additional original entities in the same native batch stay in raw evidence.
                require(eid not in seen,'SEQUENCE_DUPLICATE_MEASUREMENT');seen.add(eid)
                if stage['mode']=='temporary':
                    require(sample['templateId']==stage['templateIds'][0] and close(sample['pose']['scale'],[1,1,1],.001) and close(sample['pose']['worldPosition'],document['anchor'],.01) and close(sample['pose']['rotationDegrees'],[0,0,0],.01),'SEQUENCE_SAMPLE_NOT_REQUESTED_UNIT_POSE')
                samples.append(dict(sample,sourceRun=report['run'],rawReceiptSha256=report['rawReceiptSha256'],planSha256=attempt['plan']['sha256'],stageIndex=stage['index']))
            run_refs.append(dict(run=report['run'],rawReceiptSha256=report['rawReceiptSha256'],plan=attempt['plan'],observedFinishedUtc=report['observedFinishedUtc']))
        require(seen==set(ids),'SEQUENCE_MEASUREMENT_COVERAGE')
    return dict(attempt=ref(folder/'attempt.json'),stageIndex=stage['index'],successfulMeasurement=attempt['successfulMeasurement'],
        recovered=True,entityIds=ids,plan=attempt['plan'],creationCommit=attempt['creationCommit'],beforeBaseline=attempt['beforeBaseline'],
        recovery=attempt['recovery'],deleteEvidence=delete_refs,measurements=samples,evidence=run_refs,startUtc=start.isoformat(),endUtc=end.isoformat())

def report(operation):
    operation,document,plan,original=load(operation);stages=[];groups={};history=[];previous=None;used_runs=set();pending=[]
    for stage in document['stages']:
        stage_dir=operation/f'stage-{stage["index"]:03d}';attempts=sorted(stage_dir.glob('attempt-*'))
        accepted=None
        for folder in attempts:
            if not(folder/'attempt.json').exists():pending.append(str(folder));continue
            evidence=validate_attempt(folder,document,plan,original,stage)
            if previous is not None:require(stamp(previous)<=stamp(evidence['startUtc']),'SEQUENCE_STAGES_OVERLAP')
            previous=evidence['endUtc'];history.append(evidence)
            if evidence['successfulMeasurement']:
                require(accepted is None,'SEQUENCE_MULTIPLE_SUCCESSFUL_ATTEMPTS');accepted=evidence
                for item in evidence['evidence']:
                    require(item['run'] not in used_runs,'SEQUENCE_RAW_RUN_REUSED');used_runs.add(item['run'])
                for sample in evidence['measurements']:groups.setdefault(sample['templateId'],[]).append(sample)
        if accepted:stages.append(accepted)
    complete=len(stages)==len(document['stages']) and not pending
    output=[]
    for row in plan['rows']:
        samples=groups.get(row['templateId'],[])
        summary=template_summary(samples) if samples else dict(registryId=row['templateId'],nameZh=row['catalog']['name'],iconPath=row['catalog']['iconPath'],
            assetPath=None,boundsRenderer=None,boundsCollider=None,originConvention='unknown',sampleEntityIds=[],geometryMeasurementComplete=False,blocksSizeBasedPlacement=True)
        summary.update(selectedRoles=row['roles'],thumbnail=row['thumbnail'],officialTemplateFile=row['officialTemplateFile'],selectionConflict=row['selectionConflict'],
            modelIdentityVerified=False,runtimeModelAppearanceVerified=False,allPlannedInstancesMeasured=bool(samples),sampleRecoveryVerified=complete,
            measurementStages=[dict(stageIndex=s['stageIndex'],planSha256=s['planSha256'],sourceRun=s['sourceRun'],rawReceiptSha256=s['rawReceiptSha256']) for s in samples])
        summary['blocksSizeBasedPlacement']=summary['blocksSizeBasedPlacement'] or row['selectionConflict'] or not complete
        output.append(summary)
    return dict(ok=True,kind='asset-inspection-sequence-report-v1',schema='mw-asset-inspection',operation=str(operation),sequence=ref(operation/'sequence.json'),
        selection=document['selection'],session=document['session'],levelId=document['levelId'],cityTemplates=output,stages=stages,attemptHistory=history,pendingAttempts=pending,
        sequenceComplete=complete,allSamplesRecovered=not pending and all(x['recovered'] for x in history),
        allSelectedSizeEvidenceReady=complete and all(not x['blocksSizeBasedPlacement'] for x in output),
        allSelectedGeometryMeasured=complete and all(x['geometryMeasurementComplete'] for x in output),
        called=False,gameProcessAccessed=False,persistentSaveVerified=False,allOriginalTransformsPreservedVerified=False,appearanceVerified=False)

def run(operation,session,queue,bridge_run,*,max_stages=32,recover_stage=None):
    operation,document,plan,original=load(operation);require(type(max_stages) is int and 1<=max_stages<=128,'SEQUENCE_STAGE_BOUND')
    require(recover_stage is None or type(recover_stage) is int and 0<=recover_stage<len(document['stages']),'SEQUENCE_RECOVERY_STAGE_INDEX')
    for source,digest in document['sourceHashes'].items():require(sha(source)==digest,'SEQUENCE_SOURCE_CHANGED_BEFORE_DISPATCH')
    live=Live(session,queue,bridge_run);require(templates.same_session(live.identity,document['session']),'SEQUENCE_LIVE_SESSION_CHANGED')
    with operation_lock(operation):
        initial=report(operation);completed={x['stageIndex'] for x in initial['stages']};executed=0
        for stage in document['stages']:
            if stage['index'] in completed:continue
            if recover_stage is not None:require(recover_stage==stage['index'],'SEQUENCE_RECOVERY_MUST_TARGET_FIRST_UNFINISHED_STAGE')
            parent=operation/f'stage-{stage["index"]:03d}';parent.mkdir(exist_ok=True);attempts=sorted(parent.glob('attempt-*'))
            pending=[p for p in attempts if not(p/'attempt.json').exists()]
            if recover_stage is not None:
                require(len(pending)==1,'SEQUENCE_RECOVERY_REQUIRES_ONE_UNFINISHED_ATTEMPT');folder=pending[0]
            else:
                require(not pending,'SEQUENCE_PENDING_ATTEMPT_USE_RECOVERY_NO_REPLAY')
                if executed>=max_stages:break
                folder=parent/f'attempt-{len(attempts):03d}';folder.mkdir(exist_ok=False)
            execute_attempt(folder,stage,document,plan,original,live,recover_only=recover_stage is not None)
            verified=validate_attempt(folder,document,plan,original,stage);executed+=1
            if recover_stage is not None or not verified['successfulMeasurement']:break
        result=report(operation);result.update(called=executed>0,gameProcessAccessed=executed>0,stagesExecuted=executed,replayAttempted=False)
        return result
