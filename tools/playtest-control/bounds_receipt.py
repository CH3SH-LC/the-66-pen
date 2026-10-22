"""Card-bound independent evidence for the fixed range edit."""
import hashlib,math,struct
from contract import read,sha,require,extension,interpretation
SIZE=528
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased',
        'guardStatus','writeStarted','writeCompleted','settingsUnchanged')
def parse(raw):
    require(len(raw)==SIZE,'BOUNDS_SIZE')
    h=struct.unpack_from('<24I',raw);n=dict(zip(HEADER,h[:12]))
    require(n['bytes']==SIZE and n['version']==1 and n['operation'] in (1,2) and not any(h[12:]),'BOUNDS_ABI')
    n['observation']=extension(raw[96:432])
    n.update(zip(('manager','basic','primary','cached'),struct.unpack_from('<4Q',raw,432)))
    v=struct.unpack_from('<16f',raw,464);require(all(math.isfinite(x) for x in v) and v[-1]==0,'BOUNDS_FLOATS')
    for i,k in enumerate(('beforePrimary','beforeCached','afterPrimary','afterCached','desired')):n[k]=list(v[i*3:i*3+3])
    require(all(n[k] in (0,1) for k in ('resourcesReleased','writeStarted','writeCompleted','settingsUnchanged')),'BOUNDS_FLAGS')
    if n['writeCompleted']:
        require(n['operation']==2 and n['writeStarted']==1 and n['nativeCalls']==2 and n['settingsUnchanged']==1,'BOUNDS_WRITE_EVIDENCE')
        require(n['beforePrimary'] in ([0.,0.,0.],[100.,100.,100.]) and n['beforeCached']==[100.,100.,100.],'BOUNDS_BASELINE')
        require(n['desired']==n['afterPrimary']==n['afterCached']==[800.,300.,800.],'BOUNDS_READBACK')
    return n
def decode_bound(run,prepared):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_BOUNDS','WRAPPER_SCOPE')
    base=dict(run=str(run),session=prepared['session'],targetLevelId=prepared['targetLevelId'],operation=prepared['mode'],
              readOnly=prepared['mode']=='bounds-state',persistentWorldWriteRequested=prepared['mode']=='bounds-expand',
              changesTrialMode=False,replayForbidden=True)
    if e.get('executed') is False:
        require(not (run/'attempt.used').exists(),'ATTEMPT_DESPITE_REFUSAL')
        return dict(base,ok=False,error=e.get('error'),called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_BOUNDS' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(r.get('pid')==prepared['session']['pid'] and r.get('tid')==prepared['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==prepared['nonce'] and r.get('receiptDeadline')==str(prepared['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE')
    raw=(run/'acceptance.bin').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    require(digest==r.get('acceptanceSha256') and raw[:96].hex()==r.get('acceptanceHeaderHex'),'BINARY_BINDING')
    n=parse(raw);require(n['operation']=={'bounds-state':1,'bounds-expand':2}[prepared['mode']],'OPERATION_BINDING')
    cleanup=(r.get('callbackCount')==1 and r.get('activeCallbacks')==0 and r.get('unhooked') is True and r.get('transportOk') is True and
             r.get('probeElevatedHigh') is True and n['seh']==0 and n['resourcesReleased']==1 and (not n['writeStarted'] or n['writeCompleted']==1))
    result=dict(base,ok=False,error='BOUNDS_INCOMPLETE',called=n['nativeCalls']>0,nativeStarted=True,outcomeUncertain=not cleanup,
                cleanupVerified=cleanup,safeToRelease=cleanup,nativeReceipt=n,binaryReceiptSha256=digest,rawReceiptSha256=sha(run/'stdout.jsonl'))
    if r.get('ok') is not True or n['status'] or n['stage']!=3 or n['guardStatus'] or not cleanup or e.get('exitCode')!=0 or e.get('error'):return result
    state=interpretation(n['observation'],1073741845)
    require(prepared['targetLevelId']==n['observation']['targetLevel']==1073741845 and state['mode']=='editor' and state['editorIsTargetLevel'],'BOUNDS_TARGET')
    require(n['operation']!=2 or n['writeCompleted']==1,'BOUNDS_WRITE_NOT_COMPLETE')
    return dict(result,ok=True,error=None,mode='editor',editorIsTargetLevel=True,saveStillRequired=bool(n['writeCompleted']))
