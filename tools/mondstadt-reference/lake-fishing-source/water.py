"""Extract actual WaterPlane render meshes and their serialized parent chains.

WaterTile MonoBehaviour cells are expressly not used for geometry or heights.
World placement is reported independently from the complete prefab hierarchy.
"""
import re
import numpy as np
from common import *
from geometry_extension import renderer_prefix,bounds

PATTERN=r'^Stages_BigWorld_([12])_(-1|-2|0)_Combine_-?\d+_-?\d+_-?\d+_WaterPlane_Vo$'

def extract(store,record,number):
    cab=record['cab'];pid=record['pathId'];rootobj,rootraw=store.object(cab,pid)
    def ptr(c,p):return(store.external_cab(c,p['fileId']),p['pathId'])
    def obj(key):return store.object(*key)
    def ident(key):return obj(key)[0]['identity']
    roots=[ptr(cab,p)for p in rootobj['identity']['components']if obj(ptr(cab,p))[0]['classId']==4]
    if len(roots)!=1:raise ValueError('Water prefab root transform not unique')
    root=roots[0];rootid=ident(root)
    if rootid['father']['pathId']:raise ValueError('Unresolved root parent')
    row={'id':f'water-{number:02d}','name':record['name'],'source':record,'prefabRoot':{'cab':cab,'gameObjectPathId':pid,'transformPathId':root[1],
        'objectSha256':sha(rootraw),'serializedTRS':rootid},'hierarchy':[],'parts':[],'components':[],'unresolved':[],
        'placementStatus':'complete-serialized-prefab-transform-chain-scene-instantiation-not-yet-corroborated',
        'waterGridUsed':False,'runtimeWaterShaderEvaluated':False,'nativeWorldPlacementVerified':False}
    folder=OUT/'water'/row['id'];folder.mkdir(parents=True,exist_ok=True);seen=set();vs=[];fs=[];ids=[];cursor=0
    def visit(key,parent,matrix):
        nonlocal cursor
        if key in seen:raise ValueError('Duplicate transform child/cycle')
        seen.add(key);to,raw=obj(key);t=to['identity'];father=ptr(key[0],t['father'])if t['father']['pathId']else None
        if parent!=father:raise ValueError('Parent/child contradiction')
        go=ptr(key[0],t['gameObject']);g,gd=obj(go)
        row['hierarchy'].append({'cab':key[0],'transformPathId':key[1],'gameObjectPathId':go[1],'name':g['identity']['name'],
            'localTRS':t,'serializedSceneMatrix':matrix.tolist(),'objectSha256':sha(raw),'gameObjectSha256':sha(gd)})
        components=[(ptr(go[0],p),*obj(ptr(go[0],p)))for p in g['identity']['components']]
        renderers=[]
        for ck,co,cd in components:
            ci={'cab':ck[0],'pathId':ck[1],'classId':co['classId'],'bytes':len(cd),'objectSha256':sha(cd)}
            if co['classId']==23:
                try:ci['renderer']=renderer_prefix(cd);renderers.append(ci)
                except Exception as e:ci['rendererError']=str(e)
            if co['classId']==114:
                r=Reader(cd);r.ptr();r.read('B');r.align();script=r.ptr();ci['scriptPointer']=script
                if script['pathId']:
                    so,_=obj(ptr(ck[0],script));ci['scriptName']=so.get('identity',{}).get('name')
                p=folder/(str(ck[1])+'.monobehaviour.bin');p.write_bytes(cd);ci['raw']=rel(p)
            row['components'].append(ci)
        for ck,co,cd in components:
            if co['classId']!=33:continue
            mk=ptr(ck[0],co['identity']['mesh']);mo,md=obj(mk);info,a=read_mesh(md)
            v=a['vertices'];f=a['triangles'];native=v@matrix[:3,:3].T+matrix[:3,3]
            pn=len(row['parts']);p=folder/f'part-{pn:02d}.npz'
            np.savez_compressed(p,vertices=v,serializedSceneVertices=native,triangles=f,faceSubmesh=a['faceSubmesh'],serializedSceneMatrix=matrix)
            row['parts'].append({'partIndex':pn,'name':g['identity']['name'],'meshFilterCab':ck[0],'meshFilterPathId':ck[1],
                'meshCab':mk[0],'meshPathId':mk[1],'meshObjectSha256':sha(md),'meshInfo':info,'npz':rel(p),'npzSha256':sha(p.read_bytes()),
                'serializedSceneMatrix':matrix.tolist(),'sourceBounds':bounds(native[np.unique(f)]),'coordinateFrame':'prefab-hierarchy-local; external scene instance absent here',
                'rendererCandidates':renderers,'nonShadowEnabledStaticCandidate':any(x.get('renderer',{}).get('enabled')and x['renderer']['castShadowsRaw']!=3 for x in renderers),
                'triangleCount':len(f),'vertexCount':len(v)})
            vs.append(native);fs.append(f+cursor);ids.extend([pn]*len(f));cursor+=len(v)
        for child in t['children']:
            k=ptr(key[0],child);visit(k,key,matrix@local_matrix(ident(k)))
    visit(root,None,local_matrix(rootid))
    if not vs:raise ValueError('No original WaterPlane MeshFilter')
    v=np.concatenate(vs);f=np.concatenate(fs);p=folder/'combined.npz'
    np.savez_compressed(p,serializedSceneVertices=v,triangles=f,facePart=np.array(ids,dtype=np.int32))
    row['combined']={'npz':rel(p),'sha256':sha(p.read_bytes()),'vertexCount':len(v),'triangleCount':len(f)}
    row['sourceBounds']=bounds(v[np.unique(f)]);row['coordinateFrame']='prefab-hierarchy-local; external scene instance absent here'
    save(folder/'geometry.json',row);return row

def capture():
    discovery=json.loads((OUT/'lake-discovery.json').read_text(encoding='utf8'));records={}
    for source in discovery['results']['sceneWaterRoots']:
        if re.fullmatch(PATTERN,source['name']):
            node=discovery['nodes'][str(source['nodeId'])]
            records[(node['cab'],source['pathId'])]=dict(source,cab=node['cab'],location=node)
    store=Store();rows=[]
    for i,r in enumerate(sorted(records.values(),key=lambda x:x['name'])):
        try:
            result=extract(store,r,i);entry={'id':result['id'],'name':r['name'],'status':'captured','geometry':rel(OUT/'water'/result['id']/'geometry.json'),
                'parts':len(result['parts']),'bounds':result['sourceBounds'],'unresolved':result['unresolved']}
        except Exception as e:entry={'name':r['name'],'status':'unresolved','error':type(e).__name__+': '+str(e)}
        rows.append(entry);print(json.dumps(entry),flush=True)
    save(OUT/'water-index.json',{'schema':'original-waterplane-geometry-v1','rows':rows,'declaredProductTransform':mapping(),
        'sourceV5Index':rel(V5/'source-index.json'),'sourceV5IndexSha256':sha((V5/'source-index.json').read_bytes()),
        'installationReadBytes':store.read_bytes,'waterGridSubstitution':False,'nativeWorldPlacementVerified':False,
        'coverageMeaning':'Six target block named WaterPlane render prefab candidates, each geometry and parent chain captured. Names alone do not prove scene placement.'})

if __name__=='__main__':os.environ['MONDSTADT_CODEC_ISOLATE']='1';capture()
