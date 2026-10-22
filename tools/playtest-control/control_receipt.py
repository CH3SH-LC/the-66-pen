"""Decode the independent control binary and its exact native card identity."""
import hashlib
from contract import read,sha,require
from control_contract import parse,interpretation_control,SIZE,OPERATIONS

def decode_bound(run,prepared):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_CONTROL','WRAPPER_SCOPE')
    operation=prepared['mode'];mutation=operation not in ('trial-state','trial-frame');frame=operation=='trial-frame'
    base=dict(run=str(run),session=prepared['session'],targetLevelId=prepared['targetLevelId'],operation=operation,readOnly=not mutation and not frame,mutatedGameState=None if mutation or frame else False,changesTrialMode=mutation,mutatesTemporaryRenderResources=frame,publicationRequested=False,replayForbidden=True)
    if e.get('executed') is False:
        require(not (run/'attempt.used').exists(),'ATTEMPT_DESPITE_WRAPPER_REFUSAL')
        return dict(base,ok=False,error=e.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_CONTROL' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(r.get('pid')==prepared['session']['pid'] and r.get('tid')==prepared['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==prepared['nonce'] and r.get('receiptDeadline')==str(prepared['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_CARD_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE_MISSING');raw=(run/'acceptance.bin').read_bytes()
    require(len(raw)==SIZE and raw[:96].hex()==r.get('acceptanceHeaderHex'),'BINARY_RECEIPT_HEADER_BINDING')
    digest=hashlib.sha256(raw).hexdigest();require(digest==r.get('acceptanceSha256'),'BINARY_RECEIPT_SHA256_BINDING');o=parse(raw)
    require(o['operation']==OPERATIONS[operation] and o['observation']['targetLevel']==prepared['targetLevelId'],'OPERATION_BINDING')
    cleanup=(r.get('callbackCount')==1 and r.get('activeCallbacks')==0 and r.get('unhooked') is True and r.get('transportOk') is True and r.get('probeElevatedHigh') is True and o['seh']==0 and o['observation']['seh']==0 and o['resourcesReleased']==1)
    uncertain=not cleanup or bool(o['actionAttempted'] and not o['actionReturned'])
    summary={k:v for k,v in o.items() if k!='png'}
    result=dict(base,ok=False,error='CONTROL_INCOMPLETE',called=bool(o['nativeCalls']+o['observation']['nativeCalls']),nativeStarted=True,outcomeUncertain=uncertain,cleanupVerified=cleanup,safeToRelease=cleanup and not uncertain,nativeReceipt=summary,rawReceiptSha256=sha(run/'stdout.jsonl'),binaryReceiptSha256=digest)
    if r.get('ok') is not True or o['status'] or o['stage']!=3 or not cleanup or e.get('exitCode')!=0 or e.get('error'):return result
    result.update(interpretation_control(o,prepared))
    if frame:
        image=run/'frame.png'
        if image.exists():require(sha(image)==result['png']['sha256'],'FRAME_EXTRACTION_CHANGED')
        else:
            with image.open('xb') as f:f.write(o['png'])
        result['framePath']=str(image)
    result.update(ok=True,error=None);return result
