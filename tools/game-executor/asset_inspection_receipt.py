"""Validate raw action18 identity before interpreting bounds or template association."""
import struct
from asset_inspection_common import *
from contract import decode_extension,valid_pose,same_pose
from physics_receipt import numbers
from receipt import same_scene
import build as b

def manifest(run):
    run=guarded_output(run,prepared=True);prepared=read(run/'prepared.json');built=read(run/'build-result.json')
    require(prepared.get('kind')==KIND and prepared.get('action')==18 and prepared.get('receiptVersion')==23 and prepared.get('run')==str(run),'ASSET_PREPARED_CONTRACT')
    require(built.get('kind')==BUILD_KIND and built.get('preparedSha256')==sha(run/'prepared.json'),'ASSET_PREPARED_BINDING')
    for name,digest in prepared['artifacts'].items():
        path=run/name;require(path.resolve().is_relative_to(run) and sha(path)==digest,'ASSET_ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:require(sha(run/'invoke-asset.ps1')==built['wrapperSha256'],'ASSET_WRAPPER_CHANGED')
    return run,prepared,built

def text_field(raw,start,length,status):
    require(0<=length<=96 and status in (0,1,2,3),'ASSET_NAME_RANGE')
    value=raw[start:start+length*2]
    require(len(value)==length*2,'ASSET_NAME_TRUNCATED_RECEIPT')
    try:text=value.decode('utf-16-le');lossless=True
    except UnicodeDecodeError:text=value.decode('utf-16-le',errors='replace');lossless=False
    return dict(value=text if status in (1,3) else None,status={0:'not-observed',1:'complete',2:'unreadable',3:'truncated'}[status],
        rawUtf16Hex=value.hex(),lossless=lossless and status==1,isResourcePath=False)

def extension(raw,snapshot_size):
    require(snapshot_size in (33208,262584),'ASSET_SNAPSHOT_ABI')
    transform_size=48+128*280+snapshot_size
    require(len(raw)==48+transform_size+MAX_ENTITIES*ENTITY_SIZE,'ASSET_RECEIPT_SIZE')
    names=('size','version','status','stage','seh','count','completed','nativeCalls','sceneUnchanged','mutationCalls','failedRva','failedValue')
    report=dict(zip(names,struct.unpack_from('<12I',raw)))
    require(report['size']==len(raw) and report['version']==1 and report['count']<=MAX_ENTITIES,'ASSET_RECEIPT_ABI')
    transform_raw=raw[48:48+transform_size]
    if transform_raw==bytes(transform_size):
        report['transform']=dict(size=0,status=1,seh=0,count=0,completed=0,rows=[],mode=0,sceneUnchanged=0);after=bytes(snapshot_size)
    else:report['transform'],after=decode_extension(transform_raw,snapshot_size)
    rows=[]
    for i in range(report['count']):
        at=48+transform_size+i*ENTITY_SIZE
        row=dict(zip(('entityId','status','count','roots','poseUnchanged','reserved'),struct.unpack_from('<6I',raw,at)))
        require(row['count']<=MAX_OBJECTS,'ASSET_OBJECT_CAPACITY')
        row['unity'],row['view']=struct.unpack_from('<2Q',raw,at+24)
        row['localToWorld']=numbers(raw,at+40,16);row['worldToLocal']=numbers(raw,at+104,16)
        objects=[]
        for j in range(row['count']):
            start=at+168+j*OBJECT_SIZE
            obj=dict(zip(('object','klass','transform','gameObject','mesh'),struct.unpack_from('<5Q',raw,start)))
            obj.update(zip(('kind','enabled','active','isTrigger','isSceneQuery','belongs','stable','geometry'),struct.unpack_from('<8I',raw,start+40)))
            obj['worldBounds']=dict(center=numbers(raw,start+72,3),extents=numbers(raw,start+84,3))
            obj['localGeometryBounds']=dict(center=numbers(raw,start+96,3),extents=numbers(raw,start+108,3))
            obj['localToWorld']=numbers(raw,start+120,16)
            status,length,mesh_status,mesh_length=struct.unpack_from('<4I',raw,start+184)
            obj['objectName']=text_field(raw,start+200,length,status)
            obj['meshName']=text_field(raw,start+392,mesh_length,mesh_status)
            objects.append(obj)
        require(raw[at+168+row['count']*OBJECT_SIZE:at+ENTITY_SIZE]==bytes((MAX_OBJECTS-row['count'])*OBJECT_SIZE),'ASSET_UNUSED_OBJECTS_CHANGED')
        row['objects']=objects;rows.append(row)
    start=48+transform_size+len(rows)*ENTITY_SIZE
    require(raw[start:]==bytes((MAX_ENTITIES-len(rows))*ENTITY_SIZE),'ASSET_UNUSED_ENTITIES_CHANGED')
    report['entities']=rows;return report,after

def raw_receipt(run,prepared):
    decoder=b.ro.load_decoder();raw,_=decoder.read_probe(run/'stdout.jsonl')
    require(raw.get('scope')==SCOPE and raw.get('selfTestOnly') is False,'ASSET_RECEIPT_SCOPE')
    require(raw.get('pid')==prepared['session']['pid'] and raw.get('tid')==prepared['session']['tid'],'ASSET_TARGET_IDENTITY')
    require(raw.get('assetNonce')==prepared['nonce'] and raw.get('assetDeadline')==str(prepared['deadlineTick']) and raw.get('assetProtocol')==23,'ASSET_CARD_IDENTITY')
    return raw

def cleanup_evidence(run):
    run,prepared,_=manifest(run);end=read(run/'exit.json');require(end.get('scope')==SCOPE,'ASSET_WRAPPER_SCOPE')
    if end.get('executed') is False:
        require(not(run/'attempt.used').exists(),'ASSET_ATTEMPT_DESPITE_REFUSAL');return True
    require(end.get('executed') is True,'ASSET_EXECUTION_UNKNOWN')
    raw=raw_receipt(run,prepared)
    receipt=bytes.fromhex(raw.get('assetHex',''));snapshot_size=len((run/'baseline-snapshot.bin').read_bytes())
    report,_=extension(receipt,snapshot_size)
    return raw.get('callbackCount')==1 and raw.get('activeCallbacks')==0 and raw.get('unhooked') is True and raw.get('transportOk') is True and raw.get('probeElevatedHigh') is True and report['seh']==report['transform']['seh']==0

def decode(run):
    run,prepared,_=manifest(run);require(prepared['launchable'] and not prepared['compileOnly'],'COMPILE_ONLY_IS_NOT_LIVE_EVIDENCE')
    end=read(run/'exit.json');require(end.get('scope')==SCOPE,'ASSET_WRAPPER_SCOPE')
    base=dict(run=str(run),kind='asset-inspection-result-v1',mode='inspect',levelId=prepared['levelId'],session=prepared['session'],
        measurementPlan=prepared.get('measurementPlan'),
        createdUtc=prepared['createdUtc'],observedFinishedUtc=end.get('finishedUtc'),imageSha256=prepared['imageSha256'],
        appearanceVerified=False,playerContactVerified=False,collisionBlockingVerified=False,persistentSaveVerified=False,
        mutationCalls=0,replayForbidden=True,queryComplete=False)
    if end.get('executed') is False:
        require(not(run/'attempt.used').exists(),'ASSET_ATTEMPT_DESPITE_REFUSAL')
        return dict(base,ok=False,error=end.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(end.get('executed') is True,'ASSET_EXECUTION_UNKNOWN');raw=raw_receipt(run,prepared)
    blob=bytes.fromhex(raw.get('assetHex',''));require(raw.get('assetBytes')==len(blob),'ASSET_RAW_BYTES')
    original=(run/'baseline-snapshot.bin').read_bytes();report,after_raw=extension(blob,len(original));transform=report['transform']
    cleanup=cleanup_evidence(run)
    result=dict(base,ok=False,called=report['nativeCalls']>0,nativeStarted=True,outcomeUncertain=not cleanup,cleanupVerified=cleanup,safeToRelease=cleanup,
        rawReceiptSha256=sha(run/'stdout.jsonl'),nativeReceipt=report,measurements=[],error='ASSET_QUERY_NOT_COMPLETE')
    if not(raw.get('ok') is True and cleanup and report['status']==0 and report['stage']==4 and report['completed']==report['count'] and report['sceneUnchanged']==1 and report['mutationCalls']==0 and end.get('exitCode')==0 and not end.get('error')):return result
    require(transform['mode']==0 and transform['status']==0 and transform['completed']==report['count'] and transform['sceneUnchanged']==1,'ASSET_TRANSFORM_INSPECTION_INCOMPLETE')
    decoder=b.ro.load_decoder();before=decoder.decode_snapshot(raw)
    after=decoder.decode_snapshot(dict(snapshotHex=after_raw.hex(),snapshotBytes=len(after_raw)))
    baseline=decoder.decode_snapshot(dict(snapshotHex=original.hex(),snapshotBytes=len(original)))
    for snapshot in (before,after):
        require(snapshot['status']['value']==0 and snapshot['flags']['value']&1951==1951 and not snapshot['flags']['value']&96,'ASSET_SCENE_INCOMPLETE');same_scene(baseline,snapshot)
    owners={x['id']:x for x in before['entities']};templates=prepared['templateIds']
    require(len(report['entities'])==len(prepared['requests'])==len(transform['rows']),'ASSET_REQUEST_COUNT')
    for row,pose,request in zip(report['entities'],transform['rows'],prepared['requests']):
        eid=request['entityId'];owner=owners[eid]['owner'];owner=int(owner,16) if isinstance(owner,str) else owner
        require(row['entityId']==pose['entityId']==eid and pose['owner']==owner and row['unity']==pose['unity'],'ASSET_ENTITY_BINDING')
        require(row['status']==0 and row['poseUnchanged']==1 and 1<=row['roots']<=2,'ASSET_ENTITY_UNSTABLE')
        tid=owners[eid]['configId'];require(tid==templates[str(eid)],'ASSET_TEMPLATE_CHANGED')
        require(pose['status']==0 and pose['readbackVerified']==1 and pose['mask']==pose['called']==pose['openCalled']==pose['snapshotCalled']==pose['notifyCalled']==pose['closeCalled']==0,'ASSET_UNEXPECTED_MUTATION')
        valid_pose(pose['before']);require(same_pose(pose['before'],pose['after']),'ASSET_POSE_CHANGED');row['pose']=pose['after']
        require(len({x['object'] for x in row['objects']})==len(row['objects']),'ASSET_DUPLICATE_OBJECT')
        measured=measure(row)
        measured.update(templateId=tid,templateIdVerified=True,templateIdSource='native full snapshot entity configId + pinned owner/config/context, not name',
            nativeEntityIdentity=owners[eid],contextOrigin=before['origin'],catalog=prepared['catalogEvidence'][str(tid)])
        result['measurements'].append(measured)
    result.update(ok=True,queryComplete=True,error=None,outcomeUncertain=False,sceneUnchanged=True,
        evidenceScope='Runtime renderer and collider AABB; direct MeshRenderer.sharedMesh local bounds when available; full inverse transform normalization. No pixels, materials, mesh vertices or player collision test.')
    return result
