"""Card-bound raw runtime vitals, independently redecoded offline."""
import hashlib
from contract import read,sha,require
from vitals_contract import SIZE,parse,interpretation
def decode_bound(run,card):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_VITALS','WRAPPER_SCOPE')
    base=dict(run=str(run),session=card['session'],targetLevelId=card['targetLevelId'],operation='vitals-state',readOnly=True,changesTrialMode=False,mutatesTemporaryRenderResources=False,replayForbidden=True)
    if e.get('executed') is False:
        require(not(run/'attempt.used').exists(),'ATTEMPT_DESPITE_REFUSAL');return dict(base,ok=False,error=e.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_VITALS' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(r.get('pid')==card['session']['pid'] and r.get('tid')==card['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==card['nonce'] and r.get('receiptDeadline')==str(card['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_CARD_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE_MISSING');raw=(run/'acceptance.bin').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    require(len(raw)==SIZE and raw[:96].hex()==r.get('acceptanceHeaderHex') and digest==r.get('acceptanceSha256'),'BINARY_RECEIPT_BINDING');o=parse(raw)
    require(o['pageStart']==card['pageStart'] and o['control']['observation']['targetLevel']==card['targetLevelId'],'OPERATION_BINDING')
    cleanup=r.get('callbackCount')==1 and r.get('activeCallbacks')==0 and r.get('unhooked') is True and r.get('transportOk') is True and r.get('probeElevatedHigh') is True and not o['seh'] and o['resourcesReleased']==1 and not o['control']['seh'] and o['control']['resourcesReleased']==1 and not o['control']['observation']['seh']
    result=dict(base,ok=False,error='VITALS_INCOMPLETE',called=bool(o['nativeCalls'] or o['control']['nativeCalls']),nativeStarted=True,outcomeUncertain=not cleanup,cleanupVerified=cleanup,safeToRelease=cleanup,nativeReceipt=o,rawReceiptSha256=sha(run/'stdout.jsonl'),binaryReceiptSha256=digest)
    if r.get('ok') is not True or o['status'] or o['stage']!=3 or o['control']['status'] or o['control']['stage']!=3 or o['control']['observation']['status'] or not cleanup or e.get('exitCode')!=0 or e.get('error'):return result
    result.update(interpretation(o,card));result.update(ok=True,error=None);return result
