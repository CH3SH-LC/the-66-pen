"""Prepare one-at-a-time unit-scale sample requests and receipt-bound recovery lists.

This module only reads evidence and writes new project artifacts. It never creates,
deletes, saves, dispatches or authorizes game operations.
"""
import math
from pathlib import Path
from asset_inspection_common import *
from asset_inspection_templates import PLAN_KIND,same_session
import build as b
import scene_scale as scale

SAMPLE_KIND='asset-inspection-sample-sequence-v1'
RECOVERY_KIND='asset-inspection-sample-recovery-v1'

def sample_plan(plan_path,anchor,out):
    path=Path(plan_path).resolve();digest=sha(path);plan=read(path)
    require(plan.get('kind')==PLAN_KIND and plan.get('ok') is True and plan.get('baseline') is not None,'SAMPLE_REQUIRES_OBSERVED_TEMPLATE_PLAN')
    require(sha(plan['selection']['path'])==plan['selection']['sha256'],'SELECTION_CHANGED_REPLAN_REQUIRED')
    require(len(anchor)==3 and all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=100000 for x in anchor),'SAMPLE_ANCHOR_REQUIRED')
    missing=plan['missingTemplateIds'];require(missing and len(missing)==len(set(missing)),'SAMPLE_MISSING_SET_EMPTY_OR_DUPLICATE')
    rows={x['templateId']:x for x in plan['rows']};require(set(missing)<=rows.keys(),'SAMPLE_UNKNOWN_TEMPLATE')
    out=guarded_output(out);require(not out.exists(),'SAMPLE_OUTPUT_MUST_BE_NEW');out.mkdir(parents=True)
    stages=[]
    for i,tid in enumerate(missing):
        placement=dict(template_id=identifier(tid),position=list(anchor),rotation=[0.,0.,0.],scale=[1.,1.,1.])
        file=out/f'sample-{i:03d}-placement.json'
        write(file,dict(coordinateSpace='world',description='Single temporary unit-scale measurement sample; separate root approval required',placements=[placement]))
        stages.append(dict(index=i,templateId=tid,placement=placement,placementPlan=dict(path=str(file),sha256=sha(file)),
            requiresPreviousSampleRecovery=i>0,createdEntityIds=None,recoveryIdsMustComeFromCommit=True))
    require(sha(path)==digest,'PLAN_CHANGED_DURING_SAMPLE_PREPARATION')
    result=dict(ok=True,kind=SAMPLE_KIND,parentPlan=dict(path=str(path),sha256=digest),selection=plan['selection'],
        session=plan['session'],levelId=plan['levelId'],anchor=list(anchor),stages=stages,
        maxSimultaneousNewEntities=1,coordinateSource='explicit coordinator-supplied world anchor; no dimensions or spacing inferred',
        anchorClearanceVerified=False,requiresCoordinatorPlacementApproval=True,
        order='create one -> inspect -> measure -> receipt-bound removal -> verify removal -> next',
        gameWritesPerformed=False,dispatchAttempted=False,called=False,persistentSaveVerified=False)
    write(out/'samples.json',result);return result

def load_sequence(path,index):
    path=Path(path).resolve();sequence=read(path)
    require(sequence.get('kind')==SAMPLE_KIND and sequence.get('ok') is True,'SAMPLE_SEQUENCE_SCHEMA')
    require(sha(sequence['parentPlan']['path'])==sequence['parentPlan']['sha256'],'SAMPLE_PARENT_PLAN_CHANGED')
    require(sha(sequence['selection']['path'])==sequence['selection']['sha256'],'SAMPLE_SELECTION_CHANGED')
    require(type(index) is int and 0<=index<len(sequence['stages']),'SAMPLE_STAGE_INDEX')
    stage=sequence['stages'][index];source=stage['placementPlan']
    require(stage['index']==index and sha(source['path'])==source['sha256'],'SAMPLE_PLACEMENT_CHANGED')
    require(read(source['path'])['placements']==[stage['placement']],'SAMPLE_PLACEMENT_BINDING')
    return path,sequence,stage

def bind_sample(sequence_path,index,commit_path,before_baseline):
    path,sequence,stage=load_sequence(sequence_path,index)
    session,before,_=b.baseline(before_baseline,require_fresh=False)
    require(same_session(session,sequence['session']) and before['levelObservation']['levelId']==sequence['levelId'],'SAMPLE_BEFORE_SESSION_OR_LEVEL')
    missing={x['templateId'] for x in sequence['stages']}
    require(not any(x['configId'] in missing for x in before['entities']),'SAMPLE_TEMPLATE_OR_PREVIOUS_SAMPLE_PRESENT_REPLAN')
    commit_path=Path(commit_path).resolve()
    after,ids=scale.validate_commit(commit_path,sequence['levelId'],[stage['placement']],expected_before=before)
    commit=read(commit_path);run=Path(commit['run']);prepared=read(run/'prepared.json')
    require(same_session(prepared['session'],session),'SAMPLE_CREATE_SESSION_MISMATCH')
    require(len(ids)==1,'SAMPLE_SINGLE_CREATED_ID_REQUIRED')
    identity=scale.identities(after);target=next(x for x in after['entities'] if x['id']==ids[0])
    return dict(ok=True,kind=RECOVERY_KIND,samples=dict(path=str(path),sha256=sha(path)),stageIndex=index,
        parentPlan=sequence['parentPlan'],commit=dict(path=str(commit_path),sha256=sha(commit_path)),
        beforeBaseline=dict(run=str(Path(before_baseline).resolve()),evidence={name:sha(Path(before_baseline)/name) for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json')}),
        session=session,levelId=sequence['levelId'],templateId=stage['templateId'],
        exactCreatedEntityIds=ids,exactCreatedIdentities={str(e):list(identity[e]) for e in ids},
        targetIdentity=target,protectedOriginalEntityCount=len(before['entities']),
        measurementPrepareArgv=['python','-B',str(HERE/'asset_inspection.py'),'prepare','--baseline','FRESH_AFTER_CREATE_BASELINE','--entity-id',str(ids[0])],
        removalScope='only exact receipt-bound entityIds and unchanged owner/config/context identity; no ID range or name matching',
        removalAuthorizedByThisManifest=False,gameWritesPerformed=False,called=False,
        persistentSaveVerified=False,liveTransformVerified=False)

def verify_recovery(recovery_path,after_baseline):
    path=Path(recovery_path).resolve();recovery=read(path)
    require(recovery.get('kind')==RECOVERY_KIND and recovery.get('ok') is True,'SAMPLE_RECOVERY_SCHEMA')
    require(sha(recovery['samples']['path'])==recovery['samples']['sha256'] and sha(recovery['commit']['path'])==recovery['commit']['sha256'],'SAMPLE_RECOVERY_SOURCE_CHANGED')
    for name,digest in recovery['beforeBaseline']['evidence'].items():require(sha(Path(recovery['beforeBaseline']['run'])/name)==digest,'SAMPLE_BASELINE_CHANGED')
    rebound=bind_sample(recovery['samples']['path'],recovery['stageIndex'],recovery['commit']['path'],recovery['beforeBaseline']['run'])
    require(rebound==recovery,'SAMPLE_RECOVERY_MANIFEST_MISMATCH')
    session,after,_=b.baseline(after_baseline,require_fresh=False)
    _,before,_=b.baseline(recovery['beforeBaseline']['run'],require_fresh=False)
    require(same_session(session,recovery['session']) and after['levelObservation']['levelId']==recovery['levelId'],'SAMPLE_RECOVERY_SESSION_OR_LEVEL')
    require(not set(recovery['exactCreatedEntityIds']) & {x['id'] for x in after['entities']},'SAMPLE_STILL_PRESENT')
    scale.same_scene(before,after)
    return dict(ok=True,kind='asset-inspection-sample-recovered-v1',recovery=dict(path=str(path),sha256=sha(path)),
        afterBaseline=str(Path(after_baseline).resolve()),removedEntityIds=recovery['exactCreatedEntityIds'],
        sampleAbsent=True,allOriginalEntityIdentitiesPreserved=True,persistentSaveVerified=False,
        allTransformsPreservedVerified=False,scope='complete identity set only; not native save/reopen/pose/appearance acceptance',
        called=False,gameWritesPerformed=False,gameProcessAccessed=False)
