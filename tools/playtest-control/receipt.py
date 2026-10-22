"""Offline card-bound receipt decoding; no game APIs."""
from pathlib import Path
from contract import read,sha,require,extension,interpretation
from build import ROOT,OUTPUT
def manifest(value):
    run=Path(value).absolute();require(run.is_relative_to(OUTPUT) and run!=OUTPUT,'RUN_OUTSIDE_PREPARED_ROOT')
    for part in (run,*run.parents):
        require(not part.is_symlink() and not (getattr(part.stat(),'st_file_attributes',0)&0x400),'REPARSE_PATH_REFUSED')
        if part==ROOT:break
    run=run.resolve();built=read(run/'build-result.json');prepared=read(run/'prepared.json')
    from control_contract import OPERATIONS
    version={'playtest-control-prepared-v1':1,'playtest-control-prepared-v2':2,'playtest-control-prepared-v3':3,'playtest-control-prepared-v4':4,'playtest-control-prepared-v5':5,'playtest-control-prepared-v6':6,'playtest-control-prepared-v7':7,'playtest-control-prepared-v8':8,'playtest-control-prepared-v9':9,'playtest-control-prepared-v10':10,'playtest-control-prepared-v11':11,'playtest-control-prepared-v12':12}.get(prepared.get('kind'))
    require(version is not None,'PREPARED_KIND');modern=version!=1
    require(built.get('kind')==f'playtest-control-build-v{version}' and built.get('preparedSha256')==sha(run/'prepared.json'),'PREPARED_BINDING')
    if version==4:
        from input_contract import OPERATIONS as INPUT_OPERATIONS
        modes=tuple(INPUT_OPERATIONS)
    elif version==5:modes=('vitals-state',)
    elif version==6:modes=('inventory-state',)
    elif version==7:modes=('shop-state','shop-ui')
    elif version==8:modes=('contact-state',)
    elif version==9:modes=('trial-entities',)
    elif version==10:modes=('targeted-interact',)
    elif version==12:modes=('bounds-state','bounds-expand')
    elif version==11:modes=('scene-frame','scene-overview','scene-cleanup-state')
    else:modes=('observe',) if version==1 else ('runtime-state','render-frame') if version==2 else tuple(OPERATIONS)
    require(prepared.get('run')==str(run) and prepared.get('action')==(19 if modern else 17) and prepared.get('receiptVersion')==(24 if modern else 21) and prepared.get('mode') in modes,'PREPARED_CONTRACT')
    if modern:require(type(prepared.get('pageStart')) is int and 0<=prepared['pageStart']<=65536 and (prepared['mode'] in ('runtime-state','vitals-state','contact-state','trial-entities') or prepared['pageStart']==0),'PAGE_CONTRACT')
    for name,digest in prepared['artifacts'].items():
        path=run/name;require(path.resolve().is_relative_to(run) and sha(path)==digest,'ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:require(sha(run/'invoke-observe.ps1')==built['wrapperSha256'],'WRAPPER_CHANGED')
    if version==4:
        from input_build import validate_card
        validate_card(prepared)
    elif version==5:
        from vitals_build import validate_card
        validate_card(prepared)
    elif version==6:
        from inventory_build import validate_card
        validate_card(prepared)
    elif version==7:
        from shop_build import validate_card
        validate_card(prepared)
    elif version==8:
        from contact_build import validate_card
        validate_card(prepared)
    elif version==9:
        from directory_build import validate_card
        validate_card(prepared)
    elif version==10:
        from targeted_build import validate_card
        validate_card(prepared)
    return run,prepared,built
def decode(value):
    run,prepared,_=manifest(value);require(prepared['launchable'] and not prepared['compileOnly'],'NONLAUNCHABLE_CARD')
    if prepared['action']==19:
        if prepared['kind']=='playtest-control-prepared-v12':
            from bounds_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v11':
            from scene_frame_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v10':
            from targeted_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v9':
            from directory_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v8':
            from contact_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v7':
            from shop_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v6':
            from inventory_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v5':
            from vitals_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v4':
            from input_receipt import decode_bound
        elif prepared['kind']=='playtest-control-prepared-v3':
            from control_receipt import decode_bound
        else:
            from acceptance_receipt import decode_bound
        return decode_bound(run,prepared)
    exit_result=read(run/'exit.json');require(exit_result.get('scope')=='FIXED_PLAYTEST_OBSERVATION','WRAPPER_SCOPE')
    base=dict(run=str(run),session=prepared['session'],targetLevelId=prepared['targetLevelId'],operation='observe',mutatedGameState=False,replayForbidden=True,enterSupported=False,exitSupported=False)
    if exit_result.get('executed') is False:
        require(not (run/'attempt.used').exists(),'ATTEMPT_DESPITE_WRAPPER_REFUSAL')
        return dict(base,ok=False,error=exit_result.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(exit_result.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN')
    record=read(run/'stdout.jsonl')
    require(record.get('scope')=='FIXED_PLAYTEST_OBSERVATION' and record.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(record.get('pid')==prepared['session']['pid'] and record.get('tid')==prepared['session']['tid'],'RECEIPT_TARGET')
    require(record.get('receiptNonce')==prepared['nonce'] and record.get('receiptDeadline')==str(prepared['deadlineTick']) and record.get('receiptProtocol')==21,'RECEIPT_CARD_IDENTITY')
    raw=bytes.fromhex(record.get('observationHex',''));require(record.get('observationBytes')==len(raw),'RECEIPT_BYTES')
    e=extension(raw);require(e['targetLevel']==prepared['targetLevelId'],'RECEIPT_LEVEL_BINDING')
    cleanup=(record.get('callbackCount')==1 and record.get('activeCallbacks')==0 and record.get('unhooked') is True and record.get('transportOk') is True and record.get('probeElevatedHigh') is True and e['seh']==0)
    result=dict(base,ok=False,called=e['nativeCalls']>0,nativeStarted=True,outcomeUncertain=not cleanup,cleanupVerified=cleanup,safeToRelease=cleanup,nativeReceipt=e,rawReceiptSha256=sha(run/'stdout.jsonl'),error='OBSERVATION_INCOMPLETE')
    if record.get('ok') is not True or e['status'] or e['seh'] or e['stage']!=3 or not cleanup or exit_result.get('exitCode')!=0 or exit_result.get('error'):return result
    result.update(interpretation(e,prepared['targetLevelId']));result.update(ok=True,error=None);return result
