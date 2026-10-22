"""Card-bound atomic interaction receipt; invocation is separate from effects."""
import hashlib
from contract import read,sha,require
from targeted_contract import SIZE,parse,interpretation

def decode_bound(run,card):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_TARGETED','WRAPPER_SCOPE')
    base=dict(run=str(run),session=card['session'],targetLevelId=card['targetLevelId'],operation='targeted-interact',readOnly=False,changesTrialMode=False,mutatesTemporaryRenderResources=False,replayForbidden=True,atomicTargetIdentityVerified=False,businessEffectVerified=False)
    if e.get('executed') is False:
        require(not(run/'attempt.used').exists(),'ATTEMPT_DESPITE_REFUSAL');return dict(base,ok=False,error=e.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_TARGETED' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(r.get('pid')==card['session']['pid'] and r.get('tid')==card['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==card['nonce'] and r.get('receiptDeadline')==str(card['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_CARD_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE_MISSING');raw=(run/'acceptance.bin').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    require(len(raw)==SIZE and raw[:96].hex()==r.get('acceptanceHeaderHex') and digest==r.get('acceptanceSha256'),'BINARY_RECEIPT_BINDING');o=parse(raw);d=o['directory'];c=d['contact'];control=c['control']
    require(c['pageStart']==card['pageStart'] and control['observation']['targetLevel']==card['targetLevelId'],'OPERATION_BINDING')
    p=card['targetPlan'];require(o['optionOrdinal']==p['optionIndex'] and o['editorGuid']==p['editorGuid'] and o['runtimeId']==p['runtimeId'],'TARGETED_PLAN_BINDING')
    cleanup=r.get('callbackCount')==1 and r.get('activeCallbacks')==0 and r.get('unhooked') is True and r.get('transportOk') is True and r.get('probeElevatedHigh') is True and not any(x['seh'] for x in (o,d,c,control,control['observation'])) and all(x['resourcesReleased']==1 for x in (o,d,c,control))
    result=dict(base,ok=False,error='TARGETED_INCOMPLETE',called=bool(o['nativeCalls'] or c['nativeCalls'] or control['nativeCalls']),nativeStarted=True,actionAttempted=bool(o['actionAttempted']),actionReturned=bool(o['actionReturned']),outcomeUncertain=not cleanup or bool(o['actionAttempted'] and not o['actionReturned']),cleanupVerified=cleanup,safeToRelease=cleanup,nativeReceipt=o,rawReceiptSha256=sha(run/'stdout.jsonl'),binaryReceiptSha256=digest)
    if r.get('ok') is not True or any(x['status'] for x in (o,d,c,control,control['observation'])) or o['stage']!=3 or not cleanup or e.get('exitCode')!=0 or e.get('error'):return result
    result.update(interpretation(o,card));result.update(ok=True,error=None);return result
