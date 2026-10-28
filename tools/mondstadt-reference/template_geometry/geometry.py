"""Exact prefab-root static mesh geometry. No runtime renderer/collider claims."""
import hashlib,json,os,struct,sys
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
from sources import ROOT,OUTPUT,NodeStore,Reader,write_json
from resource_index import ResourceIndex
from native_mesh_reference import read_mesh,local_matrix

def sha(b):return hashlib.sha256(b).hexdigest()
def bounds(v):
    if not len(v):return None
    low=v.min(axis=0);high=v.max(axis=0);center=(low+high)/2;size=high-low
    return {'minXYZ':low.tolist(),'maxXYZ':high.tolist(),'sizeXYZ':size.tolist(),'centerOffsetXYZ':center.tolist(),
        'bottomCenterOffsetXYZ':[float(center[0]),float(low[1]),float(center[2])],
        'pivotToBottomY':float(low[1]),'rootOriginXYZ':[0.,0.,0.]}

def renderer_prefix(data):
    """Pinned GI2017.4 Renderer prefix. Unknown later fields stay explicit."""
    r=Reader(data);go=r.ptr();pos=r.p;end=pos
    while end<=pos+0x1a:
        value=struct.unpack_from('<h',data,end)[0];end+=2
        if value==-1:break
    new=end-pos==0x1a
    enabled=r.read('B');cast=r.read('B');receive=r.read('B');dynamic=r.read('B');r.take(4)
    if new:r.read('B')
    r.take(7)
    if new:r.take(3)
    r.take(4);r.align();light=[r.read('H'),r.read('H')]
    if light!=[65535,65535]:raise ValueError('Unsupported renderer lightmap header')
    r.take(32);distance=[r.read('f'),r.read('f')];materials=[r.ptr()for _ in range(r.count(10000))]
    if enabled not in (0,1)or cast not in (0,1,2,3):raise ValueError('Renderer control flag domain')
    return {'gameObject':go,'enabled':bool(enabled),'castShadowsRaw':cast,'receiveShadowsRaw':receive,
        'dynamicOccludeeRaw':dynamic,'newHeader':new,'materials':materials,'distanceRatios':distance,
        'parsedPrefixBytes':r.p,'unparsedSuffixBytes':len(data)-r.p,'runtimeEvaluated':False}

class Extractor:
    def __init__(self,store=None,index=None):self.store=store or NodeStore();self.index=index or ResourceIndex();self.mesh_cache={}
    def ptr(self,cab,p):return self.store.external_cab(cab,p['fileId']),p['pathId']
    def obj(self,key):return self.store.object(*key)
    def identity(self,key):return self.obj(key)[0]['identity']
    def mesh(self,key):
        if key not in self.mesh_cache:
            obj,data=self.obj(key)
            if obj['classId']!=43:raise ValueError('MeshFilter target is not Mesh')
            info,arrays=read_mesh(data);self.mesh_cache[key]=(info,arrays,sha(data))
        return self.mesh_cache[key]
    def extract(self,record,*,source_root=None,output_folder=None):
        tid=record.get('templateId')
        if source_root is None:
            if tid is None:raise ValueError('Template ID required for model-handle extraction')
            folder=OUTPUT/'templates'/str(tid)
        else:
            if tid is not None:raise ValueError('Direct source extraction must not claim a template ID')
            if output_folder is None:raise ValueError('Explicit original-source output directory required')
            folder=Path(output_folder).resolve()
            if not folder.is_relative_to(ROOT/'data/codex-main-street/upper-landmarks/resource-audit'):
                raise ValueError('Owned landmark source output required')
        folder.mkdir(parents=True,exist_ok=True)
        row={'schema':'offline-template-geometry-v1' if source_root is None else 'offline-original-landmark-geometry-v1',
            'identityChain':record,'parts':[],'hierarchy':[],
            'componentInventory':[],'unresolved':[],'staticGeometryComplete':False,'runtimeRendererBoundsVerified':False,
            'runtimeColliderBoundsVerified':False,'runtimePivotVerified':False,'gameProcessAccessed':False,
            'coordinateConvention':'Unity prefab root local XYZ, column-vector TRS; root serialized TRS reported separately',
            'boundsScope':'Referenced mesh triangle vertices in captured prefab hierarchy; no runtime deformation/LOD/collider claim'}
        if source_root is None:
            row['templateId']=tid
            mappings=self.index.resolve(record['modelResourceHandle'],self.store);row['resourceMappings']=mappings
            row['resourceIndexSource']={'cab':self.index.source['cab'],'nodeSha256':self.index.source['nodeSha256'],
                'objectSha256':self.index.source['objectSha256'],'payloadSha256':self.index.source['payloadSha256'],
                'payloadBytes':self.index.source['payloadBytes']}
            matches=[(m,p)for m in mappings if not m['errors']for p in m['matches']]
            unique={(p['targetCab'],p['targetPathId'])for m,p in matches}
            if len(unique)!=1:raise ValueError('Resource target missing or language-ambiguous')
            root=next(iter(unique))
        else:
            root=tuple(source_root)
            row.update(sourceResourceVerified=True,saveableEntityVerified=False,
                       officialTemplateMappingVerified=False)
        obj,data=self.obj(root)
        if obj['classId']!=1:raise ValueError('Model target is not GameObject')
        ident=obj['identity'];row['prefabRoot']={'cab':root[0],'gameObjectPathId':root[1],'name':ident['name'],'objectSha256':sha(data)}
        transforms=[self.ptr(root[0],p)for p in ident['components']if self.obj(self.ptr(root[0],p))[0]['classId']==4]
        if len(transforms)!=1:raise ValueError('Prefab root transform missing or ambiguous')
        root_transform=transforms[0];root_ident=self.identity(root_transform)
        if root_ident['father']['pathId']!=0:raise ValueError('Selected prefab root has parent')
        row['prefabRoot'].update(transformPathId=root_transform[1],serializedTRS=root_ident,
            serializedRootMatrix=local_matrix(root_ident).tolist())
        seen=set();all_v=[];all_f=[];part_ids=[];render_v=[];vertex_cursor=0
        def visit(key,matrix,parent=None):
            nonlocal vertex_cursor
            if key in seen:raise ValueError('Transform child cycle or duplicate parent')
            seen.add(key);to,tdata=self.obj(key)
            if to['classId']!=4:raise ValueError('Hierarchy child is not Transform')
            t=to['identity'];father=self.ptr(key[0],t['father'])if t['father']['pathId']else None
            if father!=parent:raise ValueError('Child/father references disagree')
            go_key=self.ptr(key[0],t['gameObject']);go,godata=self.obj(go_key)
            if go['classId']!=1:raise ValueError('Transform GameObject pointer class mismatch')
            g=go['identity'];components=[(self.ptr(go_key[0],p),*self.obj(self.ptr(go_key[0],p)))for p in g['components']]
            row['hierarchy'].append({'cab':key[0],'transformPathId':key[1],'gameObjectCab':go_key[0],'gameObjectPathId':go_key[1],
                'name':g['name'],'localTRS':t,'rootLocalMatrix':matrix.tolist(),'objectSha256':sha(tdata),
                'gameObjectUnparsedSuffixHex':godata[g['parsedBytes']:].hex()})
            renderers=[]
            for ck,co,cd in components:
                ci={'cab':ck[0],'pathId':ck[1],'classId':co['classId'],'objectSha256':sha(cd),'bytes':len(cd),'gameObjectPathId':go_key[1]}
                if co['classId']==23:
                    try:ci['renderer']=renderer_prefix(cd);renderers.append(ci)
                    except ValueError as e:row['unresolved'].append({'component':ci,'reason':str(e)})
                elif co['classId']==114:
                    r=Reader(cd);r.ptr();enabled=r.read('B');r.align();script=r.ptr();ci['scriptPointer']=script;ci['enabledRaw']=enabled
                    if script['pathId']:
                        sk=self.ptr(ck[0],script);so,_=self.obj(sk);ci['scriptName']=so.get('identity',{}).get('name')
                    ci['interpretation']='Serialized script; arbitrary behavior not executed or inferred'
                if co['classId']in (114,1204,1206,137,205):ci['runtimeBehaviorUnresolved']=True
                row['componentInventory'].append(ci)
            filters=[(ck,co,cd)for ck,co,cd in components if co['classId']==33]
            for ck,co,cd in filters:
                try:
                    mf=co['identity'];mesh_key=self.ptr(ck[0],mf['mesh']);info,arrays,hashmesh=self.mesh(mesh_key)
                    v=arrays['vertices'];f=arrays['triangles'];transformed=v@matrix[:3,:3].T+matrix[:3,3]
                    used=np.unique(f.reshape(-1));partid=len(row['parts']);path=folder/f'part-{partid:03d}.npz'
                    np.savez_compressed(path,vertices=v,rootLocalVertices=transformed,triangles=f,faceSubmesh=arrays['faceSubmesh'],rootLocalMatrix=matrix)
                    candidate=any(x['renderer']['enabled']and x['renderer']['castShadowsRaw']!=3 for x in renderers)
                    part={'partIndex':partid,'gameObjectCab':go_key[0],'gameObjectPathId':go_key[1],'name':g['name'],'meshFilterCab':ck[0],
                        'meshFilterPathId':ck[1],'meshCab':mesh_key[0],'meshPathId':mesh_key[1],'mesh':info,'meshObjectSha256':hashmesh,
                        'rootLocalMatrix':matrix.tolist(),'bounds':bounds(transformed[used]),'allStoredVerticesBounds':bounds(transformed),
                        'rendererCandidates':renderers,'nonShadowEnabledStaticCandidate':candidate,'npz':str(path.relative_to(ROOT)),'npzSha256':sha(path.read_bytes())}
                    row['parts'].append(part);all_v.append(transformed);all_f.append(f+vertex_cursor);part_ids.extend([partid]*len(f));vertex_cursor+=len(v)
                    if candidate:render_v.append(transformed[used])
                except Exception as e:row['unresolved'].append({'meshFilterCab':ck[0],'meshFilterPathId':ck[1],'reason':type(e).__name__+': '+str(e)})
            for child in t['children']:
                childkey=self.ptr(key[0],child);visit(childkey,matrix@local_matrix(self.identity(childkey)),key)
        visit(root_transform,np.eye(4))
        if not row['parts']:raise ValueError('No decoded static MeshFilter geometry')
        vertices=np.concatenate(all_v);faces=np.concatenate(all_f);path=folder/'combined.npz'
        np.savez_compressed(path,vertices=vertices,triangles=faces,facePart=np.array(part_ids,dtype=np.int32))
        row.update(staticGeometryComplete=not row['unresolved'],allStaticMeshBounds=bounds(vertices[np.unique(faces)]),
            nonShadowEnabledStaticBounds=bounds(np.concatenate(render_v))if render_v else None,
            combinedMesh={'npz':str(path.relative_to(ROOT)),'sha256':sha(path.read_bytes()),'vertexCount':len(vertices),'triangleCount':len(faces)},
            limitations=['Serialized GameObject activity suffix retained without interpreting it.',
                'MonoBehaviour and MiHoYo LOD components are inventoried; runtime selection/deformation not evaluated.',
                'Root local geometry does not establish editor units, entity pivot, collider shape, or runtime renderer bounds.',
                'Projection is an untextured original-mesh rendering, not a game screenshot or appearance acceptance.'])
        write_json(folder/'geometry.json',row);return row

def acquire_all():
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package')
    document=json.loads((OUTPUT/'template-identities.json').read_text(encoding='utf8'));e=Extractor();rows=[]
    for rec in document['rows']:
        try:
            result=e.extract(rec);rows.append({'templateId':rec['templateId'],'status':'captured','geometry':str((OUTPUT/'templates'/str(rec['templateId'])/'geometry.json').relative_to(ROOT)),
                'staticGeometryComplete':result['staticGeometryComplete'],'parts':len(result['parts']),'bounds':result['nonShadowEnabledStaticBounds'],'unresolved':result['unresolved']})
        except Exception as exc:rows.append({'templateId':rec['templateId'],'status':'unresolved','error':type(exc).__name__+': '+str(exc)})
        print(json.dumps(rows[-1]),flush=True)
    write_json(OUTPUT/'geometry-index.json',{'schema':'template-geometry-index-v1','rows':rows,'installationReadBytes':e.store.read_bytes,
        'validationRun':False,'runtimeAcceptance':False})

if __name__=='__main__':os.environ['MONDSTADT_CODEC_ISOLATE']='1';acquire_all()
