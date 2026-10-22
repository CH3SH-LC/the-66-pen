"""Independent raw receipt and subsequent observation validation. No game I/O."""
from datetime import datetime
from pathlib import Path
from contract import require,read,sha,decode_extension,state_bytes,LEVEL
from build import ROOT,OUTPUT,ro
from material_receipt import same_scene

def guarded_run(value):
    path=Path(value).absolute();require(path.is_relative_to(OUTPUT) and path!=OUTPUT,'RUN_OUTSIDE_PREPARED_ROOT')
    for part in (path,*path.parents):
        require(not part.is_symlink() and not (getattr(part.stat(),'st_file_attributes',0)&0x400),'REPARSE_PATH_REFUSED')
        if part==ROOT:break
    return path.resolve()
def manifest(run):
    run=guarded_run(run);built=read(run/'build-result.json');prepared=read(run/'prepared.json')
    require(built.get('kind')=='template-properties-build-v1' and built.get('preparedSha256')==sha(run/'prepared.json'),'PREPARED_BINDING')
    require(prepared.get('kind')=='template-properties-prepared-v1' and prepared.get('run')==str(run) and prepared.get('action')==24 and prepared.get('receiptVersion')==30 and prepared.get('levelId')==LEVEL,'PREPARED_CONTRACT')
    for name,digest in prepared['artifacts'].items():
        path=run/name;require(path.resolve().is_relative_to(run) and sha(path)==digest,'ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:require(sha(run/'invoke-properties.ps1')==built['wrapperSha256'],'WRAPPER_CHANGED')
    return run,prepared,built
def decode(run):
    run,prepared,_=manifest(run);require(prepared['launchable'] and not prepared['compileOnly'],'COMPILE_ONLY_IS_NOT_LIVE_EVIDENCE')
    exit_result=read(run/'exit.json');require(exit_result.get('scope')=='FIXED_TEMPLATE_PROPERTIES_ACTION','WRAPPER_SCOPE')
    base=dict(run=str(run),levelId=LEVEL,session=prepared['session'],origin=prepared['origin'],mode=prepared['mode'],persistentSaveVerified=False,reopenVerified=False,playerDisplayVerified=False,iconPixelsVerified=False,localizationVerified=False,replayForbidden=True)
    if exit_result.get('executed') is False:
        require(not (run/'attempt.used').exists(),'ATTEMPT_DESPITE_WRAPPER_REFUSAL')
        return dict(base,ok=False,error=exit_result.get('error') or 'WRAPPER_REFUSED',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,rows=[])
    require(exit_result.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN')
    decoder=ro.load_decoder();record,_=decoder.read_probe(run/'stdout.jsonl')
    require(record.get('scope')=='FIXED_TEMPLATE_PROPERTIES_ACTION' and record.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(record.get('pid')==prepared['session']['pid'] and record.get('tid')==prepared['session']['tid'],'RECEIPT_SESSION')
    require(record.get('propertiesNonce')==prepared['nonce'] and record.get('propertiesDeadline')==str(prepared['deadlineTick']) and record.get('propertiesProtocol')==30,'RECEIPT_CARD_IDENTITY')
    raw=bytes.fromhex(record.get('propertiesHex',''));require(record.get('propertiesBytes')==len(raw),'RECEIPT_BYTES')
    baseline_raw=(run/'baseline-snapshot.bin').read_bytes();extension,after_raw=decode_extension(raw,len(baseline_raw))
    cleanup=record.get('callbackCount')==1 and record.get('activeCallbacks')==0 and record.get('unhooked') is True and record.get('transportOk') is True and record.get('probeElevatedHigh') is True and extension['seh']==0 and all(not r['openCalled'] or r['closeCalled']==r['closed']==1 and r['pendingAfter']==0 and r['depthAfter']==r['depthBefore'] for r in extension['rows'])
    called=any(r['renameCalled'] or r['openCalled'] or r['setterCalls'] for r in extension['rows'])
    if any(r['renameCalled'] and r['uncertain'] for r in extension['rows']):cleanup=False
    result=dict(base,ok=False,called=called,nativeStarted=True,outcomeUncertain=called,cleanupVerified=cleanup,safeToRelease=cleanup,rows=extension['rows'],nativeReceipt=extension,rawReceiptSha256=sha(run/'stdout.jsonl'),error='NATIVE_PROPERTIES_INCOMPLETE')
    if not (record.get('ok') is True and not extension['status'] and not extension['seh'] and extension['stage']==4 and extension['sceneUnchanged']==extension['catalogUnchanged']==extension['guardsUnchanged']==1 and extension['count']==extension['completed'] and cleanup and exit_result.get('exitCode')==0 and not exit_result.get('error')):return result
    require(extension['mode']==int(prepared['mode']=='set') and len(extension['rows'])==len(prepared['requests']),'REQUEST_MODE_BINDING')
    require(extension['manager'] and extension['catalogBefore']==extension['catalogAfter'],'CATALOG_CHANGED')
    baseline=decoder.decode_snapshot(dict(snapshotHex=baseline_raw.hex(),snapshotBytes=len(baseline_raw)))
    for snapshot in (decoder.decode_snapshot(record),decoder.decode_snapshot(dict(snapshotHex=after_raw.hex(),snapshotBytes=len(after_raw)))):
        require(snapshot['status']['value']==0 and snapshot['flags']['value']&1951==1951 and not snapshot['flags']['value']&96,'SCENE_INCOMPLETE');same_scene(baseline,snapshot)
    for row,q in zip(extension['rows'],prepared['requests']):
        require(row['id']==q['id'] and row['subtype']==q['subtype'] and row['mask']==q['mask'],'ROW_IDENTITY')
        require(row['status']==0 and row['stage']==6 and row['readbackVerified']==row['companionNameVerified']==1 and row['uncertain']==0 and all(row[k] for k in ('resource','nameProperty','dataProperty','data')),'ROW_INCOMPLETE')
        require(state_bytes(row['after'])==state_bytes(row['desired']),'AFTER_DESIRED_MISMATCH')
        if prepared['mode']=='set':
            require(state_bytes(row['before'])==state_bytes(q['expected']) and state_bytes(row['desired'])==state_bytes(q['desired']),'EXPECTED_OR_DESIRED_MISMATCH')
            require(all(row[k]==q[k] for k in ('resource','nameProperty','dataProperty')),'RESOURCE_POINTER_CHANGED')
            require(row['renameCalled']==int(bool(q['mask']&1)),'RENAME_CALL_COUNT')
            require(row['setterCalls']==sum(bool(q['mask']&b) for b in (2,4,8)),'SETTER_CALL_COUNT')
            if q['mask']&2:require(row['iconAllowed']==1 and row['desired']['iconId'] in extension['itemIcons' if row['subtype']==9 else 'currencyIcons'],'ICON_CATEGORY')
            if q['mask']&14:
                require(all(row[k]==1 for k in ('openCalled','snapshotCalled','notifyCalled','closeCalled','closed')) and row['record'] and row['beforeBlob'] and row['pendingSnapshot']==1 and row['pendingBefore']==row['pendingAfter']==0 and row['depthBefore']==row['depthAfter'],'PROPERTY_TRANSACTION')
        else:
            require(not row['mask'] and not row['renameCalled'] and not row['openCalled'] and not row['setterCalls'] and state_bytes(row['before'])==state_bytes(row['after']),'INSPECT_CHANGED_STATE')
    require(extension['guardCount']>=len(extension['rows']),'RESOURCE_GUARDS_MISSING');seen=set();targets={r['id'] for r in extension['rows']}
    for g in extension['guards']:
        key=(g['id'],g['companion']);require(key not in seen and g['resource'] and g['before']==g['after'] and g['target']==int(g['id'] in targets),'RESOURCE_GUARD_CHANGED');seen.add(key)
    require(all((r['id'],0) in seen and (r['subtype']!=9 or (r['id'],1) in seen) for r in extension['rows']),'TARGET_GUARD_MISSING')
    result.update(ok=True,error=None,outcomeUncertain=False,nativeDefinitionPropertiesVerified=prepared['mode']=='set',nativeTransactionVerified=prepared['mode']=='set',catalogIdentityPreserved=True,observedPropertyPayloadsPreserved=True,wholeObjectGraphPreservationVerified=False)
    return result
def verify(write_run,inspection_run):
    changed,observed=decode(write_run),decode(inspection_run)
    require(changed['ok'] and changed['mode']=='set' and observed['ok'] and observed['mode']=='inspect','WRITE_AND_INDEPENDENT_INSPECTION_REQUIRED')
    require(changed['session']==observed['session'] and changed['origin']==observed['origin'],'SESSION_CHANGED')
    end=datetime.fromisoformat(read(Path(write_run)/'exit.json')['finishedUtc'].replace('Z','+00:00'));start=datetime.fromisoformat(read(Path(inspection_run)/'exit.json')['startedUtc'].replace('Z','+00:00'));require(start>=end,'INSPECTION_MUST_FOLLOW_WRITE')
    rows={r['id']:r for r in observed['rows']}
    for row in changed['rows']:
        require(row['id'] in rows,'INDEPENDENT_TARGET_MISSING');now=rows[row['id']]
        require(all(now[k]==row[k] for k in ('resource','nameProperty','dataProperty','data','companion')) and state_bytes(now['after'])==state_bytes(row['desired']),'INDEPENDENT_READBACK_MISMATCH')
    return dict(ok=True,levelId=LEVEL,writeRun=str(write_run),inspectionRun=str(inspection_run),independentNativeReadbackVerified=True,nativeDefinitionPropertiesVerified=True,persistentSaveVerified=False,reopenVerified=False,playerDisplayVerified=False,iconPixelsVerified=False,localizationVerified=False,called=False,nativeStarted=False,rows=observed['rows'])
