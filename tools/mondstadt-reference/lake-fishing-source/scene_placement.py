"""Bounded native sector records + exact VO map to original WaterPlane prefab.

Record decoder: installed PE 0x9355210; vector decoder 0x10f82db0;
name hash: 0xc129ee0. Index spans, all flags, finite values and EOF are checked.
No filename-derived translation and no WaterTile grid data are used.
"""
import struct,math
import numpy as np
from common import *
from capture_resource import capture,path_hash
from scene_resource_index import ResourceIndex

VO_PATH='Build/LevelStreaming/Config/LODConfig/VOFinInfoMap'
SECTOR_PATH='Build/LevelStreaming/Level/OpenWorld/BigWorld/StreamGen/'
BLOCKS=['1_-1','1_-2','1_0','2_-1','2_-2','2_0']

def resource(path,suffix):
    p=OUT/'scene-resources'/str(path_hash(path,suffix))/'source.json'
    return json.loads(p.read_text(encoding='utf8'))if p.exists()else capture(path,suffix)
def raw_object(source):
    if len(source['objects'])!=1:raise ValueError('RESOURCE_TARGET_NOT_UNIQUE')
    obj=source['objects'][0];raw=(ROOT/obj['raw']).read_bytes()
    if sha(raw)!=obj['sha256']:raise ValueError('OBJECT_SHA')
    return obj,raw
def name_hash(s):
    a=b=5381
    units=struct.unpack('<'+'H'*(len(s.encode('utf-16le'))//2),s.encode('utf-16le'))
    for i,c in enumerate(units):
        if i%2:b=((b*33)^c)&0xffffffff
        else:a=((a*33)^c)&0xffffffff
    return(a+b*0x5d588b65)&0xffffffff
class Cursor:
    def __init__(self,data,base=0):self.data=data;self.p=0;self.base=base
    def take(self,n):
        if n<0 or self.p+n>len(self.data):raise ValueError('RECORD_TRUNCATED')
        x=self.data[self.p:self.p+n];self.p+=n;return x
    def var(self):
        v=0
        for shift in range(0,70,7):
            x=self.take(1)[0];v|=(x&127)<<shift
            if not x&128:
                if v>=2**64:raise ValueError('VARINT_OVERFLOW')
                return v
        raise ValueError('VARINT_TOO_LONG')
    def f32(self):
        v=struct.unpack('<f',self.take(4))[0]
        if not math.isfinite(v):raise ValueError('NONFINITE_FLOAT')
        return v
    def vector(self):
        mask=self.take(1)[0]
        if mask&~7:raise ValueError('VECTOR_MASK')
        return [self.f32()if mask&(1<<i)else 0. for i in range(3)]
def stream_record(r):
    start=r.p;mask=r.var()
    if mask&~511:raise ValueError('STREAM_MASK')
    t=r.var()if mask&1 else 0;t=(t>>1)^-(t&1)
    handle=r.var()if mask&2 else 0
    nh=r.var()if mask&4 else 0
    magnitude=r.f32()if mask&8 else 0.
    position=r.vector()if mask&16 else[0.,0.,0.]
    rotation=r.vector()if mask&32 else[0.,0.,0.]
    scale=r.vector()if mask&64 else[0.,0.,0.]
    u3c=r.var()if mask&128 else 0;u40=r.var()if mask&256 else 0
    return {'recordOffset':r.base+start,'recordBytes':r.p-start,'recordSha256':sha(r.data[start:r.p]),'mask':mask,
        'streamType':t,'directGameObjectPathHash':str(handle),'nameHash':nh,'magnitude':magnitude,
        'positionXYZ':position,'rotationEulerXYZ':rotation,'scaleXYZ':scale,'nativeOffset3c':u3c,'nativeOffset40':u40}
def vo_map(data):
    r=Reader(data);r.p=28;name=r.string();n=r.count(100000);rows=[]
    for i in range(n):
        at=r.p;nh=r.read('I');typ=r.read('i');pattern=r.read('I');effect=r.read('I');features=r.read('Q')
        handle=r.read('Q');col=r.read('Q');simple=r.read('Q');cull=r.read('f');flag=r.read('B');r.align()
        rows.append({'nameHash':nh,'modelResourceHandle':str(handle),'colliderResourceHandle':str(col),
            'simpleColliderResourceHandle':str(simple),'offset':at,'bytes':r.p-at,'rawSha256':sha(data[at:r.p]),
            'scenePropType':typ,'patternHash':pattern,'effectHash':effect,'features':str(features),'cullingScale':cull,'flag':flag})
    if r.p!=len(data):raise ValueError('VO_MAP_TAIL')
    return name,rows
def sector_records(data,index):
    n=struct.unpack_from('<I',data)[0]
    if n+4>len(data)or any(data[n+4:])or len(data)-4-n>3:raise ValueError('BINDATA_LENGTH')
    payload=data[4:4+n];r=Reader(index);r.p=28;name=r.string();count=r.count(100000);spans=[];start=0
    for i in range(count):
        end=r.read('I');key=r.read('Q')
        if not start<end<=len(payload):raise ValueError('SECTOR_INDEX_RANGE')
        spans.append((start,end,key));start=end
    if r.p!=len(index)or start!=len(payload):raise ValueError('SECTOR_INDEX_COVERAGE')
    rows=[];unresolved=[]
    for start,end,key in spans:
        c=Cursor(payload[start:end],4+start)
        try:
            envelope=c.var()
            if envelope!=3:raise ValueError('UNSUPPORTED_SECTOR_ENVELOPE')
            group=c.var();num=c.var()
            if not 0<num<=100000:raise ValueError('SECTOR_OBJECT_BUDGET')
            objects=[stream_record(c)for _ in range(num)]
            if c.p!=len(c.data):raise ValueError('SECTOR_RECORD_TAIL')
            rows.append({'indexStart':start,'indexEnd':end,'indexPathHash':str(key),'envelopeRaw':envelope,
                'groupHashRaw':group,'objects':objects})
        except ValueError as e:unresolved.append({'indexStart':start,'indexEnd':end,'indexPathHash':str(key),'reason':str(e)})
    return {'name':name,'indexedRecords':len(spans),'decodedGroups':rows,'unresolvedGroups':unresolved,'payloadBytes':len(payload)}

def acquire_and_build():
    vo_source=resource(VO_PATH,'.ScriptableObject');vo_obj,vo_raw=raw_object(vo_source);_,vos=vo_map(vo_raw)
    byhash={}
    for row in vos:byhash.setdefault(row['nameHash'],[]).append(row)
    index=json.loads((OUT/'water-index.json').read_text(encoding='utf8'));wanted={name_hash(r['name']):r for r in index['rows']}
    if len(wanted)!=len(index['rows']):raise ValueError('WATER_NAME_HASH_COLLISION')
    idx=ResourceIndex();store=Store();parts=[];placements=[];sources=[];miss=[];mp=np.asarray(mapping()['nativeToProductMatrixColumnVector'])
    for block in BLOCKS:
        source=resource(SECTOR_PATH+'BigWorld_'+block,'.MiHoYoBinData')
        ind=resource(SECTOR_PATH+'BigWorld_'+block+'_Index','.ScriptableObject')
        obj,raw=raw_object(source);indobj,indraw=raw_object(ind);decoded=sector_records(raw,indraw)
        save(OUT/'scene-decoded'/('BigWorld_'+block+'.json'),decoded)
        sources.append({'block':block,'dataSource':source,'indexSource':ind,'decodedGroups':len(decoded['decodedGroups']),
            'unresolvedGroups':len(decoded['unresolvedGroups']),'decodedObjects':sum(len(x['objects'])for x in decoded['decodedGroups'])})
        for group in decoded['decodedGroups']:
            for inst in group['objects']:
                if inst['nameHash']not in wanted:continue
                target=wanted[inst['nameHash']];geometry=json.loads((ROOT/target['geometry']).read_text(encoding='utf8'))
                maps=byhash.get(inst['nameHash'],[])
                if len(maps)!=1:raise ValueError('VO_MAP_NAME_NOT_UNIQUE')
                vo=maps[0];resolved=idx.resolve(int(vo['modelResourceHandle']),store)
                matches=[m for rr in resolved for m in rr['matches']]
                expected=(geometry['prefabRoot']['cab'],geometry['prefabRoot']['gameObjectPathId'])
                if len(matches)!=1 or(matches[0]['targetCab'],matches[0]['targetPathId'])!=expected:raise ValueError('VO_PREFAB_CHAIN_MISMATCH')
                if inst['rotationEulerXYZ']!=[0.,0.,0.]:raise ValueError('NONZERO_EULER_ORDER_UNRESOLVED')
                if any(s==0 for s in inst['scaleXYZ']):raise ValueError('DEGENERATE_SCALE')
                outer=np.eye(4);outer[:3,:3]=np.diag(inst['scaleXYZ']);outer[:3,3]=inst['positionXYZ']
                placement={'waterId':target['id'],'name':target['name'],'sector':block,'sceneRecord':inst,'sectorGroup':{k:v for k,v in group.items()if k!='objects'},
                    'sceneObjectSource':{'cab':obj['cab'],'pathId':obj['pathId'],'sha256':obj['sha256'],'raw':obj['raw']},
                    'voMapSource':{'cab':vo_obj['cab'],'pathId':vo_obj['pathId'],'sha256':vo_obj['sha256'],'row':vo},'resourceResolution':resolved,
                    'outerSceneMatrixColumnVector':outer.tolist(),'placementStatus':'source-scene-instance-resolved','runtimeVerified':False}
                placements.append(placement)
                for part in geometry['parts']:
                    if not part['nonShadowEnabledStaticCandidate']:continue
                    with np.load(ROOT/part['npz'],allow_pickle=False)as a:
                        v=a['serializedSceneVertices'];f=a['triangles'];nv=v@outer[:3,:3].T+outer[:3,3];pv=nv@mp[:3,:3].T+mp[:3,3]
                    pid=target['id']+'-part-'+str(part['partIndex']);dest=OUT/'world-water'/(pid+'.npz');dest.parent.mkdir(exist_ok=True)
                    np.savez_compressed(dest,nativeVertices=nv,productVertices=pv,triangles=f)
                    used=np.unique(f);edges=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1);ue,cnt=np.unique(edges,axis=0,return_counts=True);boundary=ue[cnt==1]
                    boundary_path=OUT/'world-water'/(pid+'-boundary.npz');np.savez_compressed(boundary_path,vertexPairs=boundary,nativeVertices=nv,productVertices=pv)
                    row={'id':pid,'waterId':target['id'],'partIndex':part['partIndex'],'name':part['name'],'geometry':rel(dest),'geometrySha256':sha(dest.read_bytes()),
                        'boundary':rel(boundary_path),'boundaryMeaning':'Topological open mesh edges only; not terrain-occluded visible shoreline.',
                        'meshCab':part['meshCab'],'meshPathId':part['meshPathId'],'meshObjectSha256':part['meshObjectSha256'],
                        'nativeBounds':{'minXYZ':nv[used].min(0).tolist(),'maxXYZ':nv[used].max(0).tolist()},
                        'productBounds':{'minXYZ':pv[used].min(0).tolist(),'maxXYZ':pv[used].max(0).tolist()},
                        'triangleCount':len(f),'boundaryEdgeCount':len(boundary),'placementStatus':'source-scene-instance-resolved','sourceGeometry':target['geometry']}
                    parts.append(row)
    found={x['waterId']for x in placements};miss=[r['id']for r in index['rows']if r['id']not in found]
    if len(found)!=len(placements):raise ValueError('MULTIPLE_SCENE_INSTANCES_NEED_UNIQUE_IDS')
    save(OUT/'scene-placement.json',{'sources':sources,'placements':placements,'unresolvedWaterIds':miss,'gameProcessAccess':False})
    save(OUT/'lake-consumer.json',{'schema':'original-waterplane-world-v1','parts':parts,'unresolvedWaterIds':miss,
        'declaredProductTransform':mapping(),'sourceV5Index':rel(V5/'source-index.json'),'sourceV5IndexSha256':sha((V5/'source-index.json').read_bytes()),
        'placementEvidence':'Native indexed sector binary object TRS + native name hash + VOFinInfoMap full resource handle + exact prefab CAB/pathId.',
        'coordinateStatus':'native-scene-source; product scale 0.5 is declared design scale, not editor calibration',
        'editorOffsetApplied':False,'visibleShorelineResolved':False,'runtimeRenderingVerified':False,'colliderVerified':False,
        'scope':'Six target source sectors original WaterPlane meshes, not a single automatically classified lake. Higher ponds and water planes remain separate.'})
    print(json.dumps({'placements':len(placements),'parts':len(parts),'unresolved':miss,'groups':[(s['block'],s['decodedGroups'],s['unresolvedGroups'])for s in sources]}),flush=True)

if __name__=='__main__':os.environ['MONDSTADT_CODEC_ISOLATE']='1';acquire_and_build()
