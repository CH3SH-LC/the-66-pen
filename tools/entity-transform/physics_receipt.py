"""Independent decoding of actual Collider queries, never a player-contact claim."""
from pathlib import Path
import math
import struct
from contract import read,sha,require,decode_extension,valid_pose,same_pose

ENTITY_SIZE=13256
COLLIDER_SIZE=816
RAY_SIZE=112

def manifest(run):
    from receipt import guarded_run
    run=guarded_run(run);prepared=read(run/'prepared.json');built=read(run/'build-result.json')
    require(prepared.get('kind')=='entity-physics-prepared-v1' and prepared.get('action')==15 and prepared.get('receiptVersion')==19 and prepared.get('run')==str(run),'PHYSICS_PREPARED_CONTRACT')
    require(built.get('kind')=='entity-physics-build-v1' and built.get('preparedSha256')==sha(run/'prepared.json'),'PHYSICS_PREPARED_BINDING')
    for name,digest in prepared['artifacts'].items():
        path=run/name;require(path.resolve().is_relative_to(run) and sha(path)==digest,'PHYSICS_ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:require(sha(run/'invoke-transform.ps1')==built['wrapperSha256'],'PHYSICS_WRAPPER_CHANGED')
    return run,prepared,built

def numbers(raw,at,n):
    result=list(struct.unpack_from('<'+'f'*n,raw,at));require(all(math.isfinite(x) for x in result),'PHYSICS_NONFINITE');return result

def extension(raw,snapshot_size):
    transform_size=48+128*280+snapshot_size
    require(len(raw)==48+transform_size+8*ENTITY_SIZE,'PHYSICS_RECEIPT_SIZE')
    names=('size','version','status','stage','seh','count','completed','nativeCalls','sceneUnchanged','mutationCalls','failedRva','failedValue')
    result=dict(zip(names,struct.unpack_from('<12I',raw)))
    require(result['size']==len(raw) and result['version']==1 and result['count']<=8,'PHYSICS_RECEIPT_ABI')
    transform_raw=raw[48:48+transform_size]
    if transform_raw==bytes(transform_size):
        result['transform']=dict(size=0,status=1,seh=0,count=0,completed=0,rows=[],mode=0,sceneUnchanged=0)
        after=bytes(snapshot_size)
    else:result['transform'],after=decode_extension(transform_raw,snapshot_size)
    rows=[]
    for i in range(result['count']):
        at=48+transform_size+i*ENTITY_SIZE
        row=dict(zip(('entityId','status','count','roots','poseUnchanged','reserved'),struct.unpack_from('<6I',raw,at)))
        require(row['count']<=16,'PHYSICS_COLLIDER_CAPACITY')
        row['unity'],row['view']=struct.unpack_from('<2Q',raw,at+24)
        row['localToWorld']=numbers(raw,at+40,16);row['worldToLocal']=numbers(raw,at+104,16)
        row['actualLocalRotation']=numbers(raw,at+168,4);row['expectedLocalRotation']=numbers(raw,at+184,4)
        colliders=[]
        for j in range(row['count']):
            start=at+200+j*COLLIDER_SIZE
            collider=dict(zip(('collider','klass','transform','gameObject'),struct.unpack_from('<4Q',raw,start)))
            collider.update(zip(('enabled','active','isTrigger','belongs','stable','isSceneQuery'),struct.unpack_from('<6I',raw,start+32)))
            collider['bounds']={'center':numbers(raw,start+56,3),'extents':numbers(raw,start+68,3)}
            collider['localToWorld']=numbers(raw,start+80,16);rays=[]
            for k in range(6):
                offset=start+144+k*RAY_SIZE
                ray=dict(origin=numbers(raw,offset,3),direction=numbers(raw,offset+12,3),maxDistance=numbers(raw,offset+24,1)[0],hit=struct.unpack_from('<I',raw,offset+28)[0])
                hit=raw[offset+32:offset+112]
                ray.update(collider=struct.unpack_from('<Q',hit)[0],point=numbers(hit,8,3),normal=numbers(hit,20,3),distance=numbers(hit,40,1)[0],
                           instanceId=struct.unpack_from('<i',hit,52)[0],tagAndLayerPopulated=False,rawHex=hit.hex())
                rays.append(ray)
            collider['rays']=rays;colliders.append(collider)
        require(raw[at+200+row['count']*COLLIDER_SIZE:at+ENTITY_SIZE]==bytes((16-row['count'])*COLLIDER_SIZE),'PHYSICS_UNUSED_COLLIDERS_CHANGED')
        row['colliders']=colliders;rows.append(row)
    start=48+transform_size+len(rows)*ENTITY_SIZE
    require(raw[start:]==bytes((8-len(rows))*ENTITY_SIZE),'PHYSICS_UNUSED_ENTITIES_CHANGED')
    result['entities']=rows;return result,after

def matmul(a,b):
    return [sum(a[k*4+r]*b[c*4+k] for k in range(4)) for c in range(4) for r in range(4)]

def point(m,p):return [sum(m[c*4+r]*p[c] for c in range(3))+m[12+r] for r in range(3)]
def distance(a,b):return math.sqrt(sum((x-y)**2 for x,y in zip(a,b)))
def normal(m,n):
    # If world normal = inverse(M).transpose * local normal, local = M.transpose * world.
    v=[sum(m[c*4+r]*n[r] for r in range(3)) for c in range(3)];length=distance(v,[0,0,0])
    require(length>1e-8,'PHYSICS_ZERO_NORMAL');return [x/length for x in v]
def close(a,b,tolerance=.005):return len(a)==len(b) and all(abs(x-y)<=tolerance for x,y in zip(a,b))
def quaternion_equal(a,b):
    return abs(sum(v*v for v in a)-1)<.001 and abs(sum(v*v for v in b)-1)<.001 and abs(abs(sum(x*y for x,y in zip(a,b)))-1)<.0001

def samples(row):
    """Evidence from each queried solid collider; order-independent matching occurs later."""
    identity=[1. if i%5==0 else 0. for i in range(16)]
    require(close(matmul(row['worldToLocal'],row['localToWorld']),identity,.002),'PHYSICS_MATRIX_INVERSE')
    require(quaternion_equal(row['actualLocalRotation'],row['expectedLocalRotation']),'PHYSICS_UNITY_ROTATION_DIFFERS_FROM_EULER')
    result=[]
    for collider in row['colliders']:
        require(collider['belongs']==collider['stable']==1,'PHYSICS_COLLIDER_IDENTITY_OR_STATE_CHANGED')
        if not(collider['enabled']==collider['active']==collider['isSceneQuery']==1 and collider['isTrigger']==0):continue
        local=[]
        for ray in collider['rays']:
            require(ray['hit']==1,'PHYSICS_AXIAL_RAY_MISSED')
            require(ray['collider']==collider['collider'],'PHYSICS_HIT_DIFFERENT_COLLIDER')
            require(0<=ray['distance']<=ray['maxDistance'] and ray['maxDistance']>0,'PHYSICS_DISTANCE')
            require(abs(distance(ray['direction'],[0,0,0])-1)<.001 and abs(distance(ray['normal'],[0,0,0])-1)<.01,'PHYSICS_UNIT_VECTORS')
            expected=[x+d*ray['distance'] for x,d in zip(ray['origin'],ray['direction'])]
            require(distance(expected,ray['point'])<=.02,'PHYSICS_POINT_NOT_ON_RAY')
            local.append(dict(point=point(row['worldToLocal'],ray['point']),normal=normal(row['localToWorld'],ray['normal'])))
        result.append(dict(klass=collider['klass'],relativeMatrix=matmul(row['worldToLocal'],collider['localToWorld']),samples=local))
    require(result,'PHYSICS_NO_ACTIVE_SOLID_QUERY_COLLIDER');return result

def compare(reference,target):
    require(len(reference)==len(target),'PHYSICS_SOLID_COLLIDER_COUNT_DIFFERS')
    remaining=list(range(len(target)))
    for ref in reference:
        matches=[i for i in remaining if ref['klass']==target[i]['klass'] and close(ref['relativeMatrix'],target[i]['relativeMatrix'],.002)]
        require(len(matches)==1,'PHYSICS_COLLIDER_MATCH_NOT_UNIQUE');idx=matches[0];remaining.remove(idx)
        for a,b in zip(ref['samples'],target[idx]['samples']):
            require(close(a['point'],b['point'],.02),'PHYSICS_SHAPE_SAMPLE_POSITION_DIFFERS')
            require(close(a['normal'],b['normal'],.02),'PHYSICS_SHAPE_SAMPLE_NORMAL_DIFFERS')
    return True

def decode(run):
    from receipt import same_scene
    from build import ro
    run,prepared,built=manifest(run)
    require(prepared['launchable'] and not prepared['compileOnly'],'COMPILE_ONLY_CANNOT_HAVE_LIVE_EVIDENCE')
    end=read(run/'exit.json');require(end.get('scope')=='FIXED_ENTITY_PHYSICS_QUERY','PHYSICS_WRAPPER_SCOPE')
    base=dict(run=str(run),mode='physics-inspect',levelId=prepared['levelId'],session=prepared['session'],referenceEntityId=prepared['referenceEntityId'],
        playerContactVerified=False,playerBlockingVerified=False,collisionLayerMatrixVerified=False,sceneRegistrationVerified=False,persistentSaveVerified=False,
        mutationCalls=0,replayForbidden=True,sampledShapeTransformVerified=False,requestedTransformShapeVerified=False,requestedTransformPoseMatched=False)
    if end.get('executed') is False:
        require(not(run/'attempt.used').exists(),'PHYSICS_ATTEMPT_DESPITE_REFUSAL')
        return dict(base,ok=False,error=end.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
    require(end.get('executed') is True,'PHYSICS_EXECUTION_UNKNOWN')
    decoder=ro.load_decoder();raw_record,_=decoder.read_probe(run/'stdout.jsonl')
    require(raw_record.get('scope')=='FIXED_ENTITY_PHYSICS_QUERY' and raw_record.get('selfTestOnly') is False,'PHYSICS_RECEIPT_SCOPE')
    require(raw_record.get('pid')==prepared['session']['pid'] and raw_record.get('tid')==prepared['session']['tid'],'PHYSICS_TARGET_IDENTITY')
    require(raw_record.get('physicsNonce')==prepared['nonce'] and raw_record.get('physicsDeadline')==str(prepared['deadlineTick']) and raw_record.get('physicsProtocol')==19,'PHYSICS_CARD_IDENTITY')
    raw=bytes.fromhex(raw_record.get('physicsHex',''));require(raw_record.get('physicsBytes')==len(raw),'PHYSICS_RAW_BYTES')
    original=(run/'baseline-snapshot.bin').read_bytes();report,after_raw=extension(raw,len(original))
    transform=report['transform'];cleanup=(raw_record.get('callbackCount')==1 and raw_record.get('activeCallbacks')==0 and raw_record.get('unhooked') is True and raw_record.get('transportOk') is True and raw_record.get('probeElevatedHigh') is True and report['seh']==transform['seh']==0)
    result=dict(base,ok=False,queryComplete=False,called=report['nativeCalls']>0,nativeStarted=True,outcomeUncertain=not cleanup,cleanupVerified=cleanup,safeToRelease=cleanup,
        rawReceiptSha256=sha(run/'stdout.jsonl'),nativeReceipt=report,entities=report['entities'],error='PHYSICS_QUERY_NOT_COMPLETE')
    if not(raw_record.get('ok') is True and cleanup and report['status']==0 and report['stage']==4 and report['completed']==report['count'] and report['sceneUnchanged']==1 and report['mutationCalls']==0 and end.get('exitCode')==0 and not end.get('error')):return result
    require(transform['mode']==0 and transform['status']==0 and transform['completed']==report['count'] and transform['sceneUnchanged']==1,'PHYSICS_INSPECTION_INCOMPLETE')
    before=decoder.decode_snapshot(raw_record);after=decoder.decode_snapshot(dict(snapshotHex=after_raw.hex(),snapshotBytes=len(after_raw)))
    baseline=decoder.decode_snapshot(dict(snapshotHex=original.hex(),snapshotBytes=len(original)))
    for snapshot in (before,after):
        require(snapshot['status']['value']==0 and snapshot['flags']['value']&1951==1951 and not snapshot['flags']['value']&96,'PHYSICS_SCENE_INCOMPLETE')
        same_scene(baseline,snapshot)
    owners={x['id']:x for x in before['entities']};templates=prepared['templateIds']
    require(len(report['entities'])==len(prepared['requests'])==len(transform['rows']),'PHYSICS_REQUEST_COUNT')
    for row,pose,request in zip(report['entities'],transform['rows'],prepared['requests']):
        target=request['entityId'];owner=owners[target]['owner'];owner=int(owner,16) if isinstance(owner,str) else owner
        require(row['entityId']==pose['entityId']==target and pose['owner']==owner and row['unity']==pose['unity'],'PHYSICS_ENTITY_BINDING')
        require(row['status']==0 and row['poseUnchanged']==1 and 1<=row['roots']<=2,'PHYSICS_ENTITY_UNSTABLE')
        require(owners[target]['configId']==templates[str(target)],'PHYSICS_TEMPLATE_CHANGED')
        require(pose['status']==0 and pose['readbackVerified']==1 and pose['mask']==pose['called']==pose['openCalled']==pose['snapshotCalled']==pose['notifyCalled']==pose['closeCalled']==0,'PHYSICS_UNEXPECTED_MUTATION')
        valid_pose(pose['before']);require(same_pose(pose['before'],pose['after']),'PHYSICS_POSE_CHANGED')
        row['pose']=pose['after']
    result.update(ok=True,queryComplete=True,error=None,outcomeUncertain=False,sceneUnchanged=True)
    checks=[]
    try:
        by_id={row['entityId']:row for row in report['entities']};reference=samples(by_id[prepared['referenceEntityId']])
        for row in report['entities']:
            if row['entityId']==prepared['referenceEntityId']:continue
            try:compare(reference,samples(row));checks.append(dict(entityId=row['entityId'],ok=True))
            except ValueError as exc:checks.append(dict(entityId=row['entityId'],ok=False,error=str(exc)))
        result['sampledShapeTransformVerified']=bool(checks) and all(x['ok'] for x in checks)
    except ValueError as exc:result['acceptanceError']=str(exc)
    result['shapeChecks']=checks
    expected=prepared.get('expectedTransformPoses')
    if expected is not None:
        pose_checks=[dict(entityId=row['entityId'],ok=same_pose(row['pose'],expected[str(row['entityId'])])) for row in report['entities'] if row['entityId']!=prepared['referenceEntityId']]
        result['requestedPoseChecks']=pose_checks
        result['requestedTransformPoseMatched']=bool(pose_checks) and all(x['ok'] for x in pose_checks)
        result['requestedTransformShapeVerified']=result['sampledShapeTransformVerified'] and result['requestedTransformPoseMatched']
    result['evidenceScope']='Collider.Raycast six axial samples, exact collider identity, enabled/active/non-trigger/query flags, Unity pose and same-template reference; no actual player contact or global raycast'
    return result
