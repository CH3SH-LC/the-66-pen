"""Decode raw material ABI and independently recompute acceptance. No dispatch."""
from pathlib import Path
from datetime import datetime
from material_contract import read,sha,require,decode_extension,state_bytes,shader_matches,LEVEL
from material_build import ROOT,OUTPUT,ro

def guarded_run(value):
    path=Path(value).absolute()
    require(path.is_relative_to(OUTPUT) and path!=OUTPUT,'MATERIAL_RUN_OUTSIDE_PREPARED_ROOT')
    for part in (path,*path.parents):
        require(not part.is_symlink() and not (getattr(part.stat(),'st_file_attributes',0)&0x400),'REPARSE_PATH_REFUSED')
        if part==ROOT:break
    return path.resolve()

def manifest(run):
    run=guarded_run(run);built=read(run/'build-result.json');prepared=read(run/'prepared.json')
    require(built.get('kind')=='entity-material-build-v1' and built.get('preparedSha256')==sha(run/'prepared.json'),'PREPARED_BINDING')
    require(prepared.get('kind')=='entity-material-prepared-v1' and prepared.get('run')==str(run) and prepared.get('action')==22 and prepared.get('receiptVersion')==28 and prepared.get('levelId')==LEVEL,'PREPARED_CONTRACT')
    for name,digest in prepared['artifacts'].items():
        path=run/name
        require(path.resolve().is_relative_to(run) and sha(path)==digest,'ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:require(sha(run/'invoke-material.ps1')==built['wrapperSha256'],'WRAPPER_CHANGED')
    return run,prepared,built

def same_scene(a,b):
    for key in ('moduleBase','global','currentContext','entityDictionary','contextDictionary'):
        require(a['pointers'][key]==b['pointers'][key],'SCENE_POINTER_CHANGED:'+key)
    require(a['origin']==b['origin'] and a['levelObservation']==b['levelObservation'],'SCENE_ORIGIN_OR_LEVEL_CHANGED')
    for key in ('entityVersionBefore','entityVersionAfter','entityCaptured','entityValidEntries','entityRejected'):
        require(a['counts'][key]==b['counts'][key],'SCENE_COUNT_CHANGED:'+key)
    identity=lambda s:[(r['id'],r['owner'],r['config'],r['context'],r['configId'],r['dictionaryKey']) for r in s['entities']]
    require(identity(a)==identity(b),'SCENE_ENTITY_IDENTITY_CHANGED')

def slot_identity(rows):
    return [(x['renderer'],x['slot'],x['active'],x['enabled']) for x in rows]

def decode(run):
    run,prepared,_=manifest(run)
    require(prepared['launchable'] and not prepared['compileOnly'],'COMPILE_ONLY_CANNOT_HAVE_LIVE_EVIDENCE')
    exit_result=read(run/'exit.json');require(exit_result.get('scope')=='FIXED_ENTITY_MATERIAL_ACTION','WRAPPER_SCOPE')
    base=dict(run=str(run),levelId=prepared['levelId'],session=prepared['session'],origin=prepared['origin'],mode=prepared['mode'],
              persistentSaveVerified=False,reopenVerified=False,visualEffectVerified=False,gridTextureRemovedVerified=False,replayForbidden=True)
    if exit_result.get('executed') is False:
        require(not (run/'attempt.used').exists(),'NATIVE_ATTEMPT_DESPITE_WRAPPER_REFUSAL')
        return dict(base,ok=False,error=exit_result.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,rows=[])
    require(exit_result.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN')
    decoder=ro.load_decoder();record,_=decoder.read_probe(run/'stdout.jsonl')
    require(record.get('scope')=='FIXED_ENTITY_MATERIAL_ACTION' and record.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(record.get('pid')==prepared['session']['pid'] and record.get('tid')==prepared['session']['tid'],'RECEIPT_SESSION')
    require(record.get('materialNonce')==prepared['nonce'] and record.get('materialDeadline')==str(prepared['deadlineTick']) and record.get('materialProtocol')==28,'RECEIPT_CARD_IDENTITY')
    raw=bytes.fromhex(record.get('materialHex',''));require(record.get('materialBytes')==len(raw),'RECEIPT_BYTES')
    snapshot_raw=(run/'baseline-snapshot.bin').read_bytes()
    extension,after_raw=decode_extension(raw,len(snapshot_raw))
    cleanup=(record.get('callbackCount')==1 and record.get('activeCallbacks')==0 and record.get('unhooked') is True and record.get('transportOk') is True and record.get('probeElevatedHigh') is True and extension['seh']==0 and
             all(not r['openCalled'] or (r['closeCalled']==r['closed']==1 and r['depthAfter']==r['depthBefore'] and r['pendingAfter']==0) for r in extension['rows']))
    called=any(r['deserializeCalled'] or r['openCalled'] for r in extension['rows'])
    result=dict(base,ok=False,called=called,nativeStarted=True,cleanupVerified=cleanup,safeToRelease=cleanup,outcomeUncertain=called,rows=extension['rows'],nativeReceipt=extension,rawReceiptSha256=sha(run/'stdout.jsonl'),error='NATIVE_MATERIAL_NOT_COMPLETE')
    if(record.get('ok') is not True or extension['status'] or extension['seh'] or extension['stage']!=5 or extension['sceneUnchanged']!=1 or extension['guardsUnchanged']!=1 or extension['count']!=extension['completed'] or not cleanup or exit_result.get('exitCode')!=0 or exit_result.get('error')):
        return result
    mode=1 if prepared['mode']=='set' else 0
    require(extension['mode']==mode and len(extension['rows'])==len(prepared['requests']),'RECEIPT_REQUEST_BINDING')
    before=decoder.decode_snapshot(record)
    baseline=decoder.decode_snapshot(dict(snapshotHex=snapshot_raw.hex(),snapshotBytes=len(snapshot_raw)))
    after=decoder.decode_snapshot(dict(snapshotHex=after_raw.hex(),snapshotBytes=len(after_raw)))
    for snapshot in (before,after):
        require(snapshot['status']['value']==0 and snapshot['flags']['value']&1951==1951 and not snapshot['flags']['value']&96,'SNAPSHOT_NOT_COMPLETE')
        require(snapshot['counts']['entityRejected']==0 and snapshot['counts']['entityCaptured']==snapshot['counts']['entityValidEntries'],'SNAPSHOT_REJECTED_ENTITIES')
        same_scene(baseline,snapshot)
    number=lambda x:int(x,16) if isinstance(x,str) else x
    owners={e['id']:(number(e['owner']),e['configId']) for e in before['entities']}
    for row,q in zip(extension['rows'],prepared['requests']):
        require(row['entityId']==q['entityId'] and row['mask']==q['mask'] and (row['owner'],row['configId'])==owners[q['entityId']],'ROW_IDENTITY')
        require(row['status']==0 and row['readbackVerified']==1 and row['uncertain']==0 and all(row[k] for k in ('owner','component','klass','unity','view')),'ROW_INCOMPLETE')
        require(state_bytes(row['desired'])==state_bytes(row['after']),'COMPONENT_READBACK_MISMATCH')
        require(slot_identity(row['beforeRender'])==slot_identity(row['afterRender']) and row['afterSlots']>0,'RENDERER_TOPOLOGY_CHANGED')
        if mode:
            require(row['nativeBlocked']==0,'NATIVE_BLOCKED_TEMPLATE_WAS_EDITED')
            require(state_bytes(row['before'])==state_bytes(q['expected']) and state_bytes(row['desired'])==state_bytes(q['desired']) and row['component']==q['expectedComponent'],'PRECONDITION_OR_REQUEST_MISMATCH')
            require(row['stage']==8 and all(row[k]==1 for k in ('openCalled','snapshotCalled','deserializeCalled','notifyCalled','closeCalled','closed','refreshCalled','shaderVerified')),'NATIVE_TRANSACTION_INCOMPLETE')
            require(row['pendingBefore']==row['pendingAfter']==0 and row['pendingSnapshot']==1 and row['record'] and row['beforeBlob'] and row['payload'],'UNDO_OR_INPUT_PAYLOAD_MISSING')
            shader_matches(row['after'],row['afterRender'])
        else:
            require(row['mask']==row['openCalled']==row['deserializeCalled']==row['refreshCalled']==0 and state_bytes(row['before'])==state_bytes(row['after']) and row['beforeRender']==row['afterRender'],'INSPECT_MUTATION')
    require(len(extension['guards'])==len(owners),'INCOMPLETE_OTHER_ENTITY_GUARDS')
    targets={r['entityId']:r for r in extension['rows']}
    seen=set()
    for g in extension['guards']:
        require(g['entityId'] in owners and g['entityId'] not in seen and g['owner']==owners[g['entityId']][0],'GUARD_IDENTITY')
        seen.add(g['entityId'])
        require(g['target']==int(g['entityId'] in targets),'GUARD_TARGET_CHANGED')
        if not g['target'] or not mode:
            require(state_bytes(g['before'])==state_bytes(g['after']) and g['rendererHashBefore']==g['rendererHashAfter'],'OTHER_ENTITY_MATERIAL_CHANGED')
        else:
            row=targets[g['entityId']]
            require(g['component']==row['component'] and state_bytes(g['before'])==state_bytes(row['before']) and state_bytes(g['after'])==state_bytes(row['after']),'TARGET_GUARD_MISMATCH')
    result.update(ok=True,error=None,outcomeUncertain=False,afterSnapshot=after,nativeMaterialVerified=bool(mode),nativeTransactionVerified=bool(mode),rendererCustomPropertiesVerified=bool(mode),otherEntityMaterialsUnchanged=True,
                  shaderEvidence='Renderer custom property block plus actual shared-material keywords; no pixel or texture-grid acceptance')
    return result

def verify(write_run,inspection_run):
    changed=decode(write_run);observed=decode(inspection_run)
    require(changed['ok'] and changed['mode']=='set' and observed['ok'] and observed['mode']=='inspect','SET_AND_INDEPENDENT_INSPECTION_REQUIRED')
    require(changed['session']==observed['session'] and changed['levelId']==observed['levelId'] and changed['origin']==observed['origin'],'INDEPENDENT_SESSION_CHANGED')
    end=datetime.fromisoformat(read(Path(write_run)/'exit.json')['finishedUtc'].replace('Z','+00:00'))
    start=datetime.fromisoformat(read(Path(inspection_run)/'exit.json')['startedUtc'].replace('Z','+00:00'))
    require(start>=end,'INSPECTION_MUST_FOLLOW_WRITE')
    by_id={r['entityId']:r for r in observed['rows']}
    for row in changed['rows']:
        require(row['entityId'] in by_id,'INDEPENDENT_TARGET_MISSING')
        now=by_id[row['entityId']]
        require(all(row[k]==now[k] for k in ('owner','component','configId','klass','unity','view')) and state_bytes(row['after'])==state_bytes(now['after']),'INDEPENDENT_COMPONENT_READBACK_MISMATCH')
        require(slot_identity(row['afterRender'])==slot_identity(now['afterRender']),'INDEPENDENT_RENDERER_TOPOLOGY_CHANGED')
        shader_matches(now['after'],now['afterRender'])
    return dict(ok=True,kind='entity-material-independent-verification-v1',run=str(Path(write_run).resolve()),inspectionRun=str(Path(inspection_run).resolve()),
                writeReceiptSha256=changed['rawReceiptSha256'],inspectionReceiptSha256=observed['rawReceiptSha256'],levelId=changed['levelId'],entityIds=list(by_id),
                componentReadbackVerified=True,rendererCustomPropertiesVerified=True,independentReadbackVerified=True,persistentSaveVerified=False,reopenVerified=False,
                visualEffectVerified=False,gridTextureRemovedVerified=False,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=True)
