"""Decode action19 data independently; extraction never contacts the game."""
import hashlib
from contract import read,write,sha,require
from acceptance_contract import parse,interpret,SIZE
def decode_bound(run,prepared):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_ACCEPTANCE','WRAPPER_SCOPE')
    frame=prepared['mode']=='render-frame'
    base=dict(run=str(run),session=prepared['session'],targetLevelId=prepared['targetLevelId'],operation=prepared['mode'],readOnly=not frame,mutatedGameState=None if frame else False,mutatesTemporaryRenderResources=frame,changesTrialMode=False,persistentWorldWriteRequested=False,replayForbidden=True,enterSupported=False,exitSupported=False)
    if e.get('executed') is False:
        require(not (run/'attempt.used').exists(),'ATTEMPT_DESPITE_WRAPPER_REFUSAL')
        return dict(base,ok=False,error=e.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_ACCEPTANCE' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(r.get('pid')==prepared['session']['pid'] and r.get('tid')==prepared['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==prepared['nonce'] and r.get('receiptDeadline')==str(prepared['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_CARD_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE_MISSING');raw=(run/'acceptance.bin').read_bytes()
    require(len(raw)==SIZE and raw[:96].hex()==r.get('acceptanceHeaderHex'),'BINARY_RECEIPT_HEADER_BINDING')
    digest=hashlib.sha256(raw).hexdigest();require(digest==r.get('acceptanceSha256'),'BINARY_RECEIPT_SHA256_BINDING');native=parse(raw)
    require(native['operation']=={'runtime-state':1,'render-frame':2}[prepared['mode']] and native['observation']['targetLevel']==prepared['targetLevelId'],'OPERATION_BINDING')
    cleanup=(r.get('callbackCount')==1 and r.get('activeCallbacks')==0 and r.get('unhooked') is True and r.get('transportOk') is True and r.get('probeElevatedHigh') is True and native['seh']==0 and native['observation']['seh']==0 and native['resourcesReleased']==1)
    summary={k:v for k,v in native.items() if k not in ('png','entities')}
    result=dict(base,ok=False,error='ACCEPTANCE_INCOMPLETE',called=native['nativeCalls']+native['observation']['nativeCalls']>0,nativeStarted=True,outcomeUncertain=not cleanup,cleanupVerified=cleanup,safeToRelease=cleanup,nativeReceipt=summary,rawReceiptSha256=sha(run/'stdout.jsonl'),binaryReceiptSha256=digest)
    if r.get('ok') is not True or native['status'] or native['seh'] or native['stage']!=3 or not cleanup or e.get('exitCode')!=0 or e.get('error'):return result
    result.update(interpret(native,prepared['targetLevelId'],prepared['pageStart']))
    if native['operation']==2:
        image=run/'frame.png'
        if image.exists():require(sha(image)==result['png']['sha256'],'FRAME_EXTRACTION_CHANGED')
        else:
            with image.open('xb') as f:f.write(native['png'])
        result['framePath']=str(image)
    result.update(ok=True,error=None);return result
