"""Independent, card-bound decoder for deferred native screenshot cleanup."""
import hashlib,math,struct
from contract import read,sha,require,extension,interpretation
from acceptance_contract import png_info,CAPACITY
SIZE=568+CAPACITY
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased',
        'frameBefore','frameAfter','renderedBefore','renderedAfter','width','height','pngBytes','frameStatus',
        'callbacks','handle','handleReleased','cameraRestored','destroyQueued','frameAdvanced','guardStatus','reserved')
def parse(raw):
    require(len(raw)==SIZE,'SCENE_FRAME_SIZE')
    out=dict(zip(HEADER,struct.unpack_from('<24I',raw)))
    require(out['bytes']==SIZE and out['version']==1 and out['operation'] in (1,2,3) and not out['reserved'],'SCENE_FRAME_ABI')
    require(0<=out['pngBytes']<=CAPACITY and 1<=out['callbacks']<=4096,'SCENE_FRAME_BOUNDS')
    for k in ('resourcesReleased','handleReleased','cameraRestored','destroyQueued','frameAdvanced'):
        require(out[k] in (0,1),'SCENE_FRAME_ENUM')
    out['observation']=extension(raw[96:432])
    out.update(zip(('texture','cachedBefore','cachedAfter','camera','transform','startedTick'),struct.unpack_from('<6Q',raw,432)))
    v=struct.unpack_from('<22f',raw,480);require(all(math.isfinite(x) for x in v),'SCENE_FRAME_POSE_NONFINITE')
    for key,a,b in [('originalPosition',0,3),('originalRotation',3,7),('capturePosition',7,10),('captureRotation',10,14),('restoredPosition',14,17),('restoredRotation',17,21)]:
        out[key]=list(v[a:b])
    out['fieldOfView']=v[21];out['png']=raw[568:568+out['pngBytes']]
    require(not any(raw[568+out['pngBytes']:]),'SCENE_FRAME_UNUSED_PNG')
    if out['resourcesReleased'] and out['texture']:
        require(out['cachedAfter']==0 and out['frameAdvanced']==1 and out['destroyQueued']==1 and out['handle']>0,'SCENE_FRAME_RELEASE_PROOF')
    if out['cameraRestored'] and out['transform'] and out['pngBytes']:
        require(all(abs(a-b)<0.001 for a,b in zip(v[:7],v[14:21])),'SCENE_FRAME_RESTORE_PROOF')
    return out
def decode_bound(run,prepared):
    e=read(run/'exit.json');require(e.get('scope')=='FIXED_PLAYTEST_SCENE_FRAME','WRAPPER_SCOPE')
    followup=prepared['mode']=='scene-cleanup-state'
    base=dict(run=str(run),session=prepared['session'],targetLevelId=prepared['targetLevelId'],
              operation=prepared['mode'],readOnly=followup,mutatesTemporaryRenderResources=not followup,
              temporarilyChangesCamera=prepared['mode']=='scene-overview',persistentWorldWriteRequested=False,
              changesTrialMode=False,replayForbidden=True)
    if e.get('executed') is False:
        require(not (run/'attempt.used').exists(),'ATTEMPT_DESPITE_REFUSAL')
        return dict(base,ok=False,error=e.get('error'),called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(e.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN');r=read(run/'stdout.jsonl')
    require(r.get('scope')=='FIXED_PLAYTEST_SCENE_FRAME' and r.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(r.get('pid')==prepared['session']['pid'] and r.get('tid')==prepared['session']['tid'],'RECEIPT_TARGET')
    require(r.get('receiptNonce')==prepared['nonce'] and r.get('receiptDeadline')==str(prepared['deadlineTick']) and r.get('receiptProtocol')==24,'RECEIPT_IDENTITY')
    require(r.get('evidenceWritten') is True and r.get('acceptanceBytes')==SIZE,'BINARY_EVIDENCE_MISSING')
    raw=(run/'acceptance.bin').read_bytes();digest=hashlib.sha256(raw).hexdigest()
    require(digest==r.get('acceptanceSha256') and raw[:96].hex()==r.get('acceptanceHeaderHex'),'BINARY_BINDING')
    n=parse(raw)
    require(n['operation']=={'scene-frame':1,'scene-overview':2,'scene-cleanup-state':3}[prepared['mode']] and n['observation']['targetLevel']==prepared['targetLevelId'],'OPERATION_BINDING')
    if followup:
        prior=prepared['previousCapture']
        for key in ('texture','cachedBefore','handle','frameBefore'):
            require(n[key]==prior[key],'PREVIOUS_RESOURCE_BINDING')
        require(n['pngBytes']==n['camera']==n['transform']==0 and n['callbacks']==1,'READ_ONLY_FOLLOWUP_CONTRACT')
    cleanup=(r.get('callbackCount')==n['callbacks'] and r.get('activeCallbacks')==0 and r.get('unhooked') is True and
             r.get('transportOk') is True and r.get('probeElevatedHigh') is True and n['seh']==0 and
             n['resourcesReleased']==n['handleReleased']==n['cameraRestored']==1)
    result=dict(base,ok=False,error='SCENE_FRAME_INCOMPLETE',called=n['nativeCalls']>0,nativeStarted=True,
                outcomeUncertain=not cleanup,cleanupVerified=cleanup,safeToRelease=cleanup,
                nativeReceipt={k:v for k,v in n.items() if k!='png'},binaryReceiptSha256=digest,rawReceiptSha256=sha(run/'stdout.jsonl'))
    if r.get('ok') is not True or n['status'] or n['stage']!=3 or n['guardStatus'] or n['frameStatus'] or not cleanup or e.get('exitCode')!=0 or e.get('error'):
        return result
    state=interpretation(n['observation'],prepared['targetLevelId'])
    require(state['mode']=='editor' and state['editorIsTargetLevel'],'SCENE_FRAME_EDITOR_TARGET')
    if followup:
        return dict(result,ok=True,error=None,mode='editor',editorIsTargetLevel=True,
                    previousCapture=prepared['previousCapture'],delayedDestructionObserved=True,
                    recaptured=False,resourceReleaseRepeated=False,visualAcceptanceVerified=False)
    info=png_info(n['png'],n['width'],n['height'])
    image=run/'frame.png'
    if image.exists():require(sha(image)==info['sha256'],'EXTRACTED_IMAGE_CHANGED')
    else:
        with image.open('xb') as stream:stream.write(n['png'])
    return dict(result,ok=True,error=None,mode='editor',editorIsTargetLevel=True,png=info,framePath=str(image),
                frameSource='native game backbuffer',viewPreset='mondstadt-top' if n['operation']==2 else 'current',
                cameraRenderInvoked=n['operation']==2,visualAcceptanceVerified=False)
