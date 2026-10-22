"""Offline raw v7 decoder. Cleanup and UI/transaction outcomes stay separate."""
import hashlib
from contract import read,sha,require
from shop_contract import SIZE,OPERATIONS,parse,interpretation
def decode_bound(run,card):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_SHOP','WRAPPER_SCOPE')
    base=dict(run=str(run),session=card['session'],targetLevelId=card['targetLevelId'],operation=card['mode'],readOnly=card['mode']=='shop-state',changesTrialMode=False,mutatesTemporaryRenderResources=False,replayForbidden=True,transactionVerified=False,inventoryEffectVerified=False)
    if e.get('executed') is False:
        require(not(run/'attempt.used').exists(),'ATTEMPT_DESPITE_REFUSAL');return dict(base,ok=False,error=e.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_SHOP' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE');require(r.get('pid')==card['session']['pid'] and r.get('tid')==card['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==card['nonce'] and r.get('receiptDeadline')==str(card['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_CARD_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE_MISSING');raw=(run/'acceptance.bin').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    require(len(raw)==SIZE and raw[:96].hex()==r.get('acceptanceHeaderHex') and digest==r.get('acceptanceSha256'),'BINARY_RECEIPT_BINDING');o=parse(raw);require(o['operation']==OPERATIONS[card['mode']],'OPERATION_BINDING')
    inv=o['inventory'];control=inv['control'] if inv else None
    if control:require(control['observation']['targetLevel']==card['targetLevelId'],'TARGET_LEVEL_BINDING')
    cleanup=r.get('callbackCount')==1 and r.get('activeCallbacks')==0 and r.get('unhooked') is True and r.get('transportOk') is True and r.get('probeElevatedHigh') is True and o['resourcesReleased']==1 and (not inv or (inv['resourcesReleased']==1 and control['resourcesReleased']==1))
    uncertain=bool(o['actionAttempted'] and (not o['actionReturned'] or o['seh'])) or not cleanup
    result=dict(base,ok=False,error='SHOP_INCOMPLETE',called=bool(o['nativeCalls'] or (control and control['nativeCalls'])),nativeStarted=True,outcomeUncertain=uncertain,cleanupVerified=cleanup,safeToRelease=cleanup,nativeReceipt=o,rawReceiptSha256=sha(run/'stdout.jsonl'),binaryReceiptSha256=digest)
    if r.get('ok') is not True or o['status'] or o['seh'] or o['stage']!=3 or not inv or inv['status'] or inv['seh'] or control['status'] or control['seh'] or control['observation']['status'] or control['observation']['seh'] or not cleanup or e.get('exitCode')!=0 or e.get('error'):return result
    result.update(interpretation(o,card));result.update(ok=True,error=None);return result
