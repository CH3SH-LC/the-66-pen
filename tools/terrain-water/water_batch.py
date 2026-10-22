"""Serial full-terrain cards backed by original receipts, never fabricated saves.

This module does not invoke the game. batch-prepare compiles one card; execute is
the existing explicit dispatcher. Accepted raw after rows supply the next before.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import json,secrets,struct
from pathlib import Path
import water_model as model
import terrain_recovery as recovery

ROOT=model.ROOT
OUT=ROOT/'.runtime/terrain-water-20261017/batches'
SCHEMA='native-water-batch-v1'
CARD='native-water-batch-card-v1'
require=model.require

def api():
    import water_native
    return water_native

def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def sha(path):return model.digest(Path(path).read_bytes())
def canonical(value):return model.digest(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
def write(path,value):
    with model.artifact_path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
def utc(value):return datetime.fromisoformat(value.replace('Z','+00:00'))

def compile_plan(blob,terrain_id,edits,source,level,chunk_size=4096,material_source=None):
    model.authorized_level(level)
    require(material_source is not None,'WATER_CATALOG_REQUIRED')
    require(type(chunk_size) is int and 1<=chunk_size<=model.MAX_EDITS,'BATCH_CHUNK_1_TO_4096')
    require(type(edits) is list and 0<len(edits)<=2*model.MAX_CELLS,'BATCH_EDITS_1_TO_131072')
    saved=model.decode_save(blob);target=model.select(saved,model.uint(terrain_id,'terrainId'))
    require(not target['unknownCellFields'],'UNKNOWN_CELL_FIELDS_REQUIRE_RESEARCH_BEFORE_WRITE')
    identity=saved['otherRoot'].get('1',[])
    require(len(identity)==1,'BATCH_SOURCE_LEVEL_REQUIRED')
    fields=model.parse_fields(bytes.fromhex(identity[0]))
    require(len(fields)==1 and fields[0].wire_type==0 and fields[0].value==level,'BATCH_SOURCE_LEVEL_MISMATCH')
    if material_source is not None:
        import water_catalog as terrain_catalog
        terrain_catalog.validate_authority(material_source,terrain_id)
        require(material_source['levelId']==level,'CATALOG_LEVEL_MISMATCH')
    rows=target['cells'];steps=[]
    for start in range(0,len(edits),chunk_size):
        subset=edits[start:start+chunk_size];changes,after=model.apply_edits(rows,subset,None if material_source is None else material_source['waterTypes'])
        steps.append(dict(index=len(steps),before=rows,edits=subset,changes=changes,expected=after));rows=after
    result=dict(schema=SCHEMA,source=str(source),sourceSha256=model.digest(blob),levelId=level,terrainId=terrain_id,
                chunkSize=chunk_size,edits=edits,initial=target['cells'],steps=steps,expected=rows,
                nativePerCardLimit=model.MAX_EDITS,nativeWholeTerrainLimit=model.MAX_CELLS,saveInvoked=False)
    if material_source is not None:result['materialSource']=material_source
    return result

def load(path):
    batch=model.artifact_path(path);require(batch.is_relative_to(OUT.resolve()) and batch.is_dir(),'BATCH_ROOT_REQUIRED')
    manifest=read(batch/'manifest.json');plan=read(batch/'plan.json');blob=(batch/'initial.gil').read_bytes()
    require(manifest==dict(schema=SCHEMA,batch=str(batch),planSha256=sha(batch/'plan.json'),initialSha256=model.digest(blob),
                          recoverySha256=sha(batch/'recovery.json')),'BATCH_MANIFEST_CHANGED')
    expected=compile_plan(blob,plan['terrainId'],plan['edits'],plan['source'],plan['levelId'],plan['chunkSize'],plan.get('materialSource'))
    require(plan==expected,'BATCH_PLAN_CHANGED')
    recovery.validate(batch,read(batch/'recovery.json'),plan['levelId'],plan['source'])
    return batch,plan,blob

def unchanged_formal(batch,plan):
    rows=recovery.validate(batch,read(batch/'recovery.json'),plan['levelId'],plan['source'])
    require({str(p) for p in recovery.sibling_files(Path(plan['source']))}=={item['source'] for item in rows.values()},'BATCH_FORMAL_SET_CHANGED')
    for item in rows.values():require(model.digest(recovery.stable_bytes(Path(item['source'])))==item['sha256'],'BATCH_FORMAL_FILE_CHANGED:'+item['source'])

@contextmanager
def lock(batch):
    path=model.artifact_path(batch/'operation.lock');token=secrets.token_hex(16)
    with path.open('x',encoding='utf-8') as stream:stream.write(token)
    try:yield
    finally:
        require(path.read_text('utf-8')==token,'BATCH_LOCK_OWNERSHIP_CHANGED')
        path.unlink()

def step_path(batch,index):return batch/'steps'/f'{index:05d}'
def attempts(batch,index):
    parent=step_path(batch,index)/'attempts'
    return sorted(p for p in parent.iterdir() if p.is_dir()) if parent.exists() else []
def active_attempt(batch,index):
    pending=[p for p in attempts(batch,index) if not (p/'abandoned.json').exists()]
    require(len(pending)<=1,'BATCH_MULTIPLE_PENDING_ATTEMPTS')
    return pending[0] if pending else None

def immutable_evidence(run):
    names=('prepared.json','build-result.json','request.json','stdout.jsonl','exit.json','launch.claim','attempt.used',
           'baseline-prepared.json','baseline-snapshot.bin')
    return {str(model.artifact_path(run/name)):sha(run/name) for name in names}

def original(run):
    """Independent native decode plus direct rows from the same immutable raw."""
    native=api();run,built=native.checked_run(run);proof=native.decode(run)
    require(proof['ok'] and proof['safeToRelease'] and not proof['outcomeUncertain'],'BATCH_ORIGINAL_RECEIPT_NOT_ACCEPTED')
    pins=immutable_evidence(run)
    if built.get('runtimeProbe'):
        import terrain_runtime
        record,_=terrain_runtime.read_probe(run/'stdout.jsonl')
    else:record,_=native.ro.load_decoder().read_probe(run/'stdout.jsonl')
    require(sha(run/'stdout.jsonl')==proof['rawReceiptSha256']==pins[str(run/'stdout.jsonl')],'BATCH_RECEIPT_CHANGED_DURING_READ')
    raw=bytes.fromhex(record['terrainHex']);head=proof['header']
    before=[list(struct.unpack_from('<6I',raw,256+24*i)) for i in range(head['beforeCount'])]
    after=[list(struct.unpack_from('<6I',raw,256+24*model.MAX_CELLS+24*i)) for i in range(head['afterCount'])]
    size=262584 if built['nativeSnapshotVersion']==2 else 33208
    snapshot=raw[native.RECEIPT_BASE_SIZE:native.RECEIPT_BASE_SIZE+size]
    scene=native.ro.load_decoder().decode_snapshot(dict(snapshotHex=snapshot.hex(),snapshotBytes=size))
    return dict(run=run,built=built,proof=proof,pins=pins,before=before,after=after,scene=scene,
                request=read(run/'request.json'),exit=read(run/'exit.json'))

def accepted_prefix(batch,plan):
    result=[];previous=None
    import water_save_verify as saveproof
    for index,step in enumerate(plan['steps']):
        path=step_path(batch,index)/'accepted.json'
        if not path.exists():
            require(not any((step_path(batch,i)/'accepted.json').exists() for i in range(index+1,len(plan['steps']))),'BATCH_ACCEPTANCE_GAP')
            break
        accepted=read(path);observation=original(accepted['run'])
        card=observation['request'];binding=card.get('batch',{})
        require(binding.get('path')==str(batch) and binding.get('index')==index,'BATCH_ACCEPTED_WRONG_CARD')
        require(accepted['evidence']==observation['pins'] and accepted['after']==observation['after']==step['expected'] and
                observation['before']==step['before'] and accepted['afterSha256']==canonical(observation['after']),
                'BATCH_ACCEPTED_ORIGINAL_CHANGED')
        require(observation['proof'].get('nativeRenderRebuildVerified') is True,'BATCH_REBUILD_REQUIRED')
        if previous:
            saveproof.same_session(previous['built']['session'],observation['built']['session'])
            saveproof.same_scene(previous['scene'],observation['scene'])
        previous=observation;result.append(observation)
    return result

def validate_card(card,blob,run=None,dispatch=False):
    """Pure card binding. Prior acceptance is hash-bound; no recursive decoding."""
    require(card.get('schema')==CARD and type(card.get('batch')) is dict,'BATCH_CARD_REQUIRED')
    binding=card['batch'];batch,plan,initial=load(binding['path']);index=binding['index']
    require(type(index) is int and 0<=index<len(plan['steps']),'BATCH_CARD_INDEX')
    require(blob==initial and binding['manifestSha256']==sha(batch/'manifest.json'),'BATCH_CARD_INITIAL_CHANGED')
    attempt=model.artifact_path(binding['attempt'])
    require(attempt.parent==step_path(batch,index)/'attempts' and attempt.is_dir(),'BATCH_ATTEMPT_PATH')
    intent=read(attempt/'intent.json');require(intent['batch']==str(batch) and intent['index']==index,'BATCH_ATTEMPT_IDENTITY')
    previous=step_path(batch,index-1)/'accepted.json' if index else None
    require(binding['previousAcceptedSha256']==(sha(previous) if previous else None),'BATCH_PREVIOUS_ACCEPTANCE_CHANGED')
    if previous:require(read(previous)['after']==plan['steps'][index]['before'],'BATCH_NEXT_BEFORE_NOT_ACCEPTED_AFTER')
    expected=dict(schema=CARD,terrainId=plan['terrainId'],source=plan['source'],sourceSha256=plan['sourceSha256'],
                  **{key:plan['steps'][index][key] for key in ('before','edits','changes','expected')},batch=binding,saveInvoked=False)
    if plan.get('materialSource') is not None:expected['materialSource']=plan['materialSource']
    require(card==expected,'BATCH_CARD_CONTENT_CHANGED')
    require(binding['inspectionRun']==intent['inspectionRun'] and binding['inspectionReceiptSha256']==sha(Path(binding['inspectionRun'])/'stdout.jsonl'),
            'BATCH_INSPECTION_BINDING_CHANGED')
    if run is not None:require(read(attempt/'run.json')=={'run':str(Path(run).resolve())},'BATCH_CANDIDATE_LINK_CHANGED')
    if dispatch:
        require(not (attempt/'abandoned.json').exists() and not (step_path(batch,index)/'accepted.json').exists() and active_attempt(batch,index)==attempt,
                'BATCH_CARD_NOT_ACTIVE')
    return card

def plan_for_prepare(args,session,scene):
    """Called after the existing core independently decodes the fresh baseline."""
    batch,plan,blob=load(args.batch);accepted=accepted_prefix(batch,plan);index=len(accepted)
    require(index<len(plan['steps']),'BATCH_ALREADY_COMPLETE')
    attempt=model.artifact_path(args._batch_attempt)
    require(active_attempt(batch,index)==attempt,'BATCH_PREPARE_ATTEMPT_CHANGED')
    intent=read(attempt/'intent.json')
    require(intent['baseline']==str(model.artifact_path(args.baseline)) and intent['inspectionRun']==str(model.artifact_path(args.inspection)),
            'BATCH_PREPARE_INPUT_BINDING_CHANGED')
    unchanged_formal(batch,plan)
    inspected=original(args.inspection);built=inspected['built'];import water_save_verify as saveproof
    require(built['inspectOnly'] and not built.get('refreshOnly') and not built.get('batch') and
            built['terrainId']==plan['terrainId'] and built['levelId']==plan['levelId'],'BATCH_NATIVE_INSPECT_REQUIRED')
    saveproof.same_session(session,built['session']);saveproof.same_scene(scene,inspected['scene'])
    finished=utc(inspected['exit']['finishedUtc']);baseline_exit=read(Path(args.baseline)/'exit.json')
    require(0<=(datetime.now(timezone.utc)-finished).total_seconds()<900 and finished<=utc(baseline_exit['finishedUtc']),
            'BATCH_FRESH_INSPECTION_THEN_BASELINE_REQUIRED')
    before=accepted[-1]['after'] if accepted else plan['initial']
    require(inspected['before']==inspected['after']==before==plan['steps'][index]['before'],
            'BATCH_NATIVE_FULL_TERRAIN_DIFFERS_FROM_ACCEPTED_BEFORE')
    if accepted:
        saveproof.same_session(session,accepted[-1]['built']['session']);saveproof.same_scene(scene,accepted[-1]['scene'])
        require(utc(inspected['exit']['startedUtc'])>=utc(accepted[-1]['exit']['finishedUtc']),'BATCH_INSPECTION_PRECEDES_PREVIOUS_WRITE')
    previous=step_path(batch,index-1)/'accepted.json' if index else None
    binding=dict(path=str(batch),index=index,manifestSha256=sha(batch/'manifest.json'),attempt=str(attempt),
                 previousAcceptedSha256=sha(previous) if previous else None,inspectionRun=str(inspected['run']),
                 inspectionReceiptSha256=inspected['proof']['rawReceiptSha256'])
    card=dict(schema=CARD,terrainId=plan['terrainId'],source=plan['source'],sourceSha256=plan['sourceSha256'],
              before=before,edits=plan['steps'][index]['edits'],changes=plan['steps'][index]['changes'],expected=plan['steps'][index]['expected'],
              batch=binding,saveInvoked=False)
    if plan.get('materialSource') is not None:card['materialSource']=plan['materialSource']
    pins={str(batch/name):sha(batch/name) for name in ('manifest.json','plan.json','initial.gil','recovery.json')}
    pins[str(attempt/'intent.json')]=sha(attempt/'intent.json');pins.update(inspected['pins'])
    for i,observed in enumerate(accepted):
        p=step_path(batch,i)/'accepted.json';pins[str(p)]=sha(p);pins.update(observed['pins'])
    args._batch_pins=pins
    return card

def create(args):
    source=Path(args.save).resolve();require(source.stem.isdecimal(),'BATCH_FORMAL_SOURCE_ID')
    level=int(source.stem);source=recovery.formal_source(source,level);blob=recovery.stable_bytes(source)
    material_source=None
    if getattr(args,'catalog_run',None):
        import water_catalog as terrain_catalog
        material_source=terrain_catalog.authority(args.catalog_run,args.terrain_id)
    plan=compile_plan(blob,args.terrain_id,read(args.edits),str(source),level,args.chunk_size,material_source)
    batch=api().ro.output_directory(model.artifact_path(OUT));(batch/'steps').mkdir()
    with (batch/'initial.gil').open('xb') as stream:stream.write(blob)
    write(batch/'plan.json',plan);write(batch/'recovery.json',recovery.capture(batch,source,level,model.digest(blob)))
    write(batch/'manifest.json',dict(schema=SCHEMA,batch=str(batch),planSha256=sha(batch/'plan.json'),initialSha256=model.digest(blob),recoverySha256=sha(batch/'recovery.json')))
    return dict(ok=True,batch=str(batch),cards=len(plan['steps']),edits=len(plan['edits']),expectedCells=len(plan['expected']),called=False,nativeSaveVerified=False)

def prepare(args):
    batch,plan,_=load(args.batch)
    with lock(batch):
        accepted=accepted_prefix(batch,plan);index=len(accepted);require(index<len(plan['steps']),'BATCH_ALREADY_COMPLETE')
        require(active_attempt(batch,index) is None,'BATCH_PENDING_CARD_REQUIRES_ACCEPT_OR_ABANDON')
        attempt=step_path(batch,index)/'attempts'/secrets.token_hex(12);attempt.mkdir(parents=True)
        write(attempt/'intent.json',dict(batch=str(batch),index=index,inspectionRun=str(model.artifact_path(args.inspection)),
                                        baseline=str(model.artifact_path(args.baseline))))
        args._batch_attempt=str(attempt);args._run_started=lambda run:write(attempt/'run.json',{'run':str(run)})
        args.plan=None;args.terrain_id=None;args.inspect_only=False;args.runtime_probe=False;args.refresh_only=False;args.cells=None;args.save=None
        try:
            result=api().prepare(args);write(attempt/'prepared-link.json',dict(run=result['run'],preparedSha256=sha(Path(result['run'])/'prepared.json')))
            return result|dict(batch=str(batch),batchIndex=index,attempt=str(attempt))
        except Exception as exc:
            write(attempt/'prepare-error.json',dict(error=str(exc),nativeCalled=False));raise

def accept(args):
    batch,plan,_=load(args.batch)
    with lock(batch):
        accepted=accepted_prefix(batch,plan);run=Path(args.run).resolve()
        if any(item['run']==run for item in accepted):return dict(ok=True,batch=str(batch),acceptedCards=len(accepted),alreadyAccepted=True,called=False)
        index=len(accepted);require(index<len(plan['steps']),'BATCH_ALREADY_COMPLETE');unchanged_formal(batch,plan)
        observed=original(run);card=observed['request'];validate_card(card,(batch/'initial.gil').read_bytes(),run,True)
        require(card['batch']['path']==str(batch) and card['batch']['index']==index,'BATCH_WRONG_NEXT_CARD')
        require(observed['before']==plan['steps'][index]['before'] and observed['after']==plan['steps'][index]['expected'] and
                observed['proof'].get('nativeRenderRebuildVerified') is True,'BATCH_CARD_RESULT_MISMATCH')
        if accepted:
            import water_save_verify as saveproof
            saveproof.same_session(accepted[-1]['built']['session'],observed['built']['session'])
            saveproof.same_scene(accepted[-1]['scene'],observed['scene'])
        attempt=active_attempt(batch,index);link=read(attempt/'prepared-link.json')
        require(link==dict(run=str(run),preparedSha256=sha(run/'prepared.json')),'BATCH_PREPARED_LINK_CHANGED')
        write(step_path(batch,index)/'accepted.json',dict(run=str(run),after=observed['after'],afterSha256=canonical(observed['after']),
                                                       evidence=observed['pins'],acceptedUtc=datetime.now(timezone.utc).isoformat()))
        return dict(ok=True,batch=str(batch),acceptedCards=index+1,totalCards=len(plan['steps']),complete=index+1==len(plan['steps']),
                    acceptedAfterCells=len(observed['after']),called=False,nativeSaveVerified=False)

def status(args):
    batch,plan,_=load(args.batch);accepted=accepted_prefix(batch,plan);index=len(accepted)
    pending=active_attempt(batch,index) if index<len(plan['steps']) else None
    return dict(ok=True,batch=str(batch),acceptedCards=index,totalCards=len(plan['steps']),complete=index==len(plan['steps']),
                pendingAttempt=str(pending) if pending else None,lastRun=str(accepted[-1]['run']) if accepted else None,
                called=False,nativeSaveVerified=False)

def abandon(args):
    batch,plan,_=load(args.batch)
    with lock(batch):
        accepted=accepted_prefix(batch,plan);index=len(accepted);require(index<len(plan['steps']),'BATCH_ALREADY_COMPLETE')
        attempt=active_attempt(batch,index);require(attempt is not None,'BATCH_NO_PENDING_ATTEMPT')
        run=Path(read(attempt/'run.json')['run']) if (attempt/'run.json').exists() else None
        launched=run and any((run/n).exists() for n in ('launch.claim','attempt.used','stdout.jsonl','exit.json','dispatch-result.json'))
        evidence=None
        if launched:
            result=api().decode(run)
            require(result['called'] is False and result['safeToRelease'] is True and result['cleanupVerified'] is True and
                    result['outcomeUncertain'] is False,'BATCH_CANNOT_ABANDON_CALLED_OR_UNKNOWN_CARD')
            evidence=dict(rawReceiptSha256=result['rawReceiptSha256'],called=False,cleanupVerified=True)
        write(attempt/'abandoned.json',dict(run=str(run) if run else None,reason='confirmed no terrain call; never replay this card',evidence=evidence))
        return dict(ok=True,batch=str(batch),abandonedAttempt=str(attempt),called=False,noAutomaticReplay=True)

@contextmanager
def dispatch_guard(card):
    batch,plan,blob=load(card['batch']['path'])
    with lock(batch):
        validate_card(card,blob,dispatch=True);unchanged_formal(batch,plan)
        yield

def saved_content(card,before,after):
    validate_card(card,before);batch,plan,blob=load(card['batch']['path']);accepted=accepted_prefix(batch,plan)
    require(len(accepted)==len(plan['steps']) and card==accepted[-1]['request'],'BATCH_COMPLETE_ACCEPTED_CHAIN_REQUIRED_FOR_SAVE')
    changed={change['key'] for step in plan['steps'] for change in step['changes']}
    result=model.verify_expected_save(blob,after,plan['terrainId'],accepted[-1]['after'],changed)
    evidence={str(batch/name):sha(batch/name) for name in ('manifest.json','plan.json','initial.gil','recovery.json')}
    for item in read(batch/'recovery.json')['entries']:evidence[item['backup']]=item['sha256']
    for index,observed in enumerate(accepted):
        path=step_path(batch,index)/'accepted.json';evidence[str(path)]=sha(path);evidence.update(observed['pins'])
        # Preserve the inspect originals exactly as pinned when this card was
        # prepared, not their current unchecked sidecars. Check again at the
        # end of the outer native-save verifier, alongside every saved copy.
        inspection=Path(observed['request']['batch']['inspectionRun'])
        for path,value in immutable_evidence(inspection).items():
            require(observed['built']['pins'].get(path)==value,'BATCH_INSPECTION_ORIGINAL_CHANGED')
            evidence[path]=value
    return result|dict(batch=str(batch),acceptedCards=len(accepted),completeChainVerified=True,batchEvidenceSha256=evidence)

def verify_save(args):
    batch,plan,_=load(args.batch);accepted=accepted_prefix(batch,plan)
    require(len(accepted)==len(plan['steps']),'BATCH_INCOMPLETE_NO_SAVE_PROOF')
    import water_save_verify
    return water_save_verify.verify(accepted[-1]['run'],args.save_run)
