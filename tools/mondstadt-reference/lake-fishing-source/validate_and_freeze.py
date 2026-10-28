"""One complete offline batch after development, then immutable source seal.

Only captured workspace bytes are read. Never touches game/IPC/installation.
"""
import platform,struct
import numpy as np
from PIL import Image
from common import *
from scene_placement import stream_record,Cursor,name_hash,sector_records,vo_map
import consumer

def main():
    writable();checks=[];raw_cache={};dependencies=[]
    def check(name,condition,detail=None):
        checks.append({'name':name,'passed':bool(condition),'detail':detail})
    def j(path):return json.loads(Path(path).read_text(encoding='utf8'))
    def obj(cab,pid):
        if cab not in raw_cache:
            folder=OUT/'raw'/cab;data=(folder/'node.bin').read_bytes();meta=j(folder/'metadata.json');receipt=j(folder/'source.json')
            check('raw-node-sha:'+cab,sha(data)==receipt['nodeSha256']);raw_cache[cab]=(data,{o['pathId']:o for o in meta['objects']})
        data,rows=raw_cache[cab];o=rows[pid];return o,data[o['offset']:o['offset']+o['size']]
    for name,expected in [('template-geometry-v1','e824a461e67bd014fc561b30449ce5c1d4cda3b98568d9e5e2303fddf27e71e8'),
                          ('native-world-source-v5-final','05c00364b32db6d2510999f0a78ed58930f9d79111ab0db48986afe07cd662e6')]:
        path=OUT.parent/name/'PACKAGE.json';p=j(path);check('old-frozen-package:'+name,sha(path.read_bytes())==expected)
        dependencies.append({'path':rel(path),'sha256':sha(path.read_bytes())})
        rows=p['files']
        if isinstance(rows,dict):rows=[dict(v,path=rel(path.parent/k))for k,v in rows.items()]
        for r in rows:check('old-frozen-file:'+r['path'],sha((ROOT/r['path']).read_bytes())==r['sha256'])
    index=j(OUT/'geometry-index.json');ids={20001946,20002987,20002811,20002321,20001019}
    check('five-exact-template-ids',{r['templateId']for r in index['rows']}==ids)
    for row in index['rows']:
        d=j(ROOT/row['geometry']);tid=d['templateId'];check(f'template-complete:{tid}',d['staticGeometryComplete']and not d['unresolved'])
        check(f'no-runtime-promotion:{tid}',not d['runtimeRendererBoundsVerified']and not d['runtimeColliderBoundsVerified']and not d['runtimePivotVerified'])
        mats={};rootid=d['prefabRoot']['transformPathId']
        for h in d['hierarchy']:
            to,traw=obj(h['cab'],h['transformPathId']);check(f'transform-sha:{tid}:{h["transformPathId"]}',sha(traw)==h['objectSha256'])
            t=to['identity'];parent=t['father']['pathId'];m=np.eye(4)if h['transformPathId']==rootid else mats[parent]@local_matrix(t)
            check(f'hierarchy-matrix:{tid}:{h["transformPathId"]}',np.allclose(m,h['rootLocalMatrix'],atol=1e-10));mats[h['transformPathId']]=m
        for p in d['parts']:
            mo,mraw=obj(p['meshCab'],p['meshPathId']);info,a=read_mesh(mraw)
            with np.load(ROOT/p['npz'])as saved:
                check(f'original-mesh:{tid}',sha(mraw)==p['meshObjectSha256']and np.array_equal(a['vertices'],saved['vertices'])and np.array_equal(a['triangles'],saved['triangles']))
                m=np.asarray(p['rootLocalMatrix']);v=a['vertices']@m[:3,:3].T+m[:3,3]
                check(f'local-vertices:{tid}',np.array_equal(v,saved['rootLocalVertices']))
                used=v[np.unique(a['triangles'])];check(f'local-bounds:{tid}',np.allclose(used.min(0),p['bounds']['minXYZ'],atol=1e-10)and np.allclose(used.max(0),p['bounds']['maxXYZ'],atol=1e-10))
    visual=j(OUT/'fishing-five-visual-review.json')
    for r in visual['rows']:
        p=OUT/'projections'/f'{r["templateId"]}.png'
        with Image.open(p)as im:check(f'projection:{r["templateId"]}',im.size==(1500,1250)and sha(p.read_bytes())==r['imageSha256'])
    check('crate-barrel-semantics',[r['approvedAsFishCatchModel']for r in visual['rows']if r['templateId']==20002321]==[False]and[r['approvedAsVisibleEmptyBucket']for r in visual['rows']if r['templateId']==20001019]==[False])
    placement=j(OUT/'scene-placement.json');water=j(OUT/'lake-consumer.json');coverage=j(OUT/'coverage.json')
    check('water-counts',len(placement['placements'])==24 and len(water['parts'])==73 and not placement['unresolvedWaterIds'])
    native_map=np.asarray(water['declaredProductTransform']['nativeToProductMatrixColumnVector'])
    check('v5-exact-matrix',np.array_equal(native_map,[[0,0,-.5,-374.875],[0,.5,0,0],[.5,0,0,-1161],[0,0,0,1]]))
    decoded_by_block={}
    for s in placement['sources']:
        a=s['dataSource']['objects'][0];b=s['indexSource']['objects'][0];raw=(ROOT/a['raw']).read_bytes();ind=(ROOT/b['raw']).read_bytes()
        check('sector-source-sha:'+s['block'],sha(raw)==a['sha256']and sha(ind)==b['sha256'])
        decoded=sector_records(raw,ind);decoded_by_block[s['block']]=decoded
        check('sector-reparse:'+s['block'],decoded==j(OUT/'scene-decoded'/('BigWorld_'+s['block']+'.json')))
        check('sector-explicit-unknown:'+s['block'],len(decoded['unresolvedGroups'])==1 and decoded['unresolvedGroups'][0]['reason']=='UNSUPPORTED_SECTOR_ENVELOPE')
    for p in placement['placements']:
        r=p['sceneRecord'];raw=(ROOT/p['sceneObjectSource']['raw']).read_bytes();at=r['recordOffset'];n=r['recordBytes'];record=stream_record(Cursor(raw[at:at+n],at))
        check('source-record:'+p['waterId'],record==r and sha(raw[at:at+n])==r['recordSha256'])
        check('source-namehash:'+p['waterId'],name_hash(p['name'])==r['nameHash']==p['voMapSource']['row']['nameHash'])
        check('source-no-euler-assumption:'+p['waterId'],r['rotationEulerXYZ']==[0,0,0]and r['scaleXYZ']==[1,1,1])
        g=j(OUT/'water'/p['waterId']/'geometry.json');maps=[m for rr in p['resourceResolution']for m in rr['matches']]
        check('exact-resource-prefab:'+p['waterId'],len(maps)==1 and maps[0]['targetCab']==g['prefabRoot']['cab']and maps[0]['targetPathId']==g['prefabRoot']['gameObjectPathId'])
        vo=p['voMapSource'];source_obj,source_raw=obj(vo['cab'],vo['pathId']);_,rows=vo_map(source_raw);found=[x for x in rows if x['nameHash']==r['nameHash']]
        check('vo-source-row:'+p['waterId'],found==[vo['row']])
        if p['waterId']=='water-13':
            check('independent-water13-byte-control',at==797 and struct.unpack_from('<3f',raw,810)==(2304.,200.,-768.)and r['positionXYZ']==[2304.,200.,-768.])
        outer=np.asarray(p['outerSceneMatrixColumnVector'])
        for part in g['parts']:
            _,meshraw=obj(part['meshCab'],part['meshPathId']);_,a=read_mesh(meshraw);m=np.asarray(part['serializedSceneMatrix']);v=a['vertices']@m[:3,:3].T+m[:3,3]
            nativ=v@outer[:3,:3].T+outer[:3,3];prod=nativ@native_map[:3,:3].T+native_map[:3,3]
            key=p['waterId']+'-part-'+str(part['partIndex']);w=next(x for x in water['parts']if x['id']==key)
            with np.load(ROOT/w['geometry'])as saved:
                check('world-mesh:'+key,np.array_equal(saved['nativeVertices'],nativ)and np.array_equal(saved['productVertices'],prod)and np.array_equal(saved['triangles'],a['triangles']))
            used=np.unique(a['triangles']);check('world-bounds:'+key,np.array_equal(nativ[used].min(0),w['nativeBounds']['minXYZ'])and np.array_equal(nativ[used].max(0),w['nativeBounds']['maxXYZ']))
    # Exercise public consumer methods against the just-built workspace snapshot.
    # Constructor/frozen-manifest gate is exercised after the final seal below.
    paths=[p for p in OUT.rglob('*')if p.is_file()and p.name!='PACKAGE.json']
    expected={rel(p):sha(p.read_bytes())for p in paths}
    cat=consumer.GeometryCatalog.__new__(consumer.GeometryCatalog);cat.folder=OUT;cat.expected=expected;cat.rows={r['templateId']:r for r in index['rows']}
    for tid in ids:
        v=cat.vertices(tid);m=np.array([[0,0,2,7],[0,.5,0,20],[-3,0,0,-6],[0,0,0,1]],dtype=float)
        transformed=cat.transformed_bounds(tid,m);vv=v@m[:3,:3].T+m[:3,3]
        check('public-transform:'+str(tid),np.array_equal(vv.min(0),transformed['minXYZ'])and np.array_equal(vv.max(0),transformed['maxXYZ']))
    w=consumer.WaterReference.__new__(consumer.WaterReference);w.folder=OUT;w.expected=expected;w.index=water;w.parts=[]
    for r in water['parts']:
        with np.load(ROOT/r['geometry'])as a:w.parts.append((r,a['nativeVertices'].copy(),a['productVertices'].copy(),a['triangles'].copy()))
    for r,nv,pv,ff in w.parts:
        tri=pv[ff];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);ii=np.flatnonzero(np.abs(cross[:,1])>1e-8)
        check('has-queryable-faces:'+r['id'],len(ii)>0)
        if len(ii):
            k=int(ii[0]);point=tri[k].mean(0);hits=w.query_product([point[[0,2]]],part_ids=[r['id']])[0]['hits'];match=[h for h in hits if h['sourceFaceId']==k]
            check('barycentric-original-face:'+r['id'],len(match)==1 and abs(match[0]['productY']-point[1])<1e-8 and abs(match[0]['nativeY']-nv[ff[k],1].mean())<1e-8)
        boundary=w.boundary(r['id']);check('boundary-api:'+r['id'],boundary['segments'].shape==(r['boundaryEdgeCount'],2,3)and not boundary['visibleShoreline'])
    check('outside-water-no-height',w.query_product([[1e6,1e6]])[0]['productY']is None)
    w.parts=[];check('missing-placement-no-height',w.query_product([[0,0]])[0]['status']=='missing-scene-placement')
    bad=[lambda:cat.transformed_bounds(20002987,[[1]]),lambda:cat.geometry(123),lambda:w.query_product([[float('nan'),0]]),
         lambda:w.query_product([[0,0]],native_y_band=[2,1]),lambda:w.query_product([[0,0]],part_ids=['missing'])]
    for i,fn in enumerate(bad):
        try:fn();ok=False
        except(ValueError,KeyError):ok=True
        check('invalid-input-rejected:'+str(i),ok)
    lake=j(OUT/'cider-lake-level-candidate.json')
    with np.load(ROOT/lake['geometry'])as a:
        check('lake-source-y',np.max(np.abs(a['nativeVertices'][a['triangles'],1]-202.39999389648438))<1e-4 and lake['productY']==101.19999694824219)
        check('lake-no-shoreline-promotion',not lake['meshBoundaryIsVisibleShoreline']and not lake['runtimeVerified'])
        check('lake-source-face-count',len(a['triangles'])==166 and len(lake['sourceParts'])==9)
    failures=[x for x in checks if not x['passed']]
    report={'schema':'lake-fishing-source-offline-batch-v1','passed':not failures,'checks':checks,'checkCount':len(checks),'failures':failures,
        'runtimeAcceptance':False,'installationAccessDuringBatch':False,'oldFrozenDependencies':dependencies,'python':platform.python_version(),'numpy':np.__version__}
    save(OUT/'offline-validation.json',report)
    if failures:raise ValueError('OFFLINE_BATCH_FAILED: '+str([x['name']for x in failures]))
    files=[]
    for base in [OUT,HERE]:
        for p in sorted(base.rglob('*')):
            if not p.is_file()or'__pycache__'in p.parts or p.name=='PACKAGE.json':continue
            files.append({'path':rel(p),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
    package={'schema':'lake-fishing-source-extension-v1','offlineValidationPassed':True,'offlineCheckCount':len(checks),'files':files,
        'api':rel(HERE/'consumer.py'),'entry':[rel(OUT/'geometry-index.json'),rel(OUT/'lake-consumer.json')],
        'dependencies':dependencies,'templateCount':5,'waterPrefabCount':24,'waterPartCount':73,'runtimeAcceptance':False,'immutable':True}
    save(OUT/'PACKAGE.json',package)
    # Final public loading gate in this same complete batch; no source acquisition.
    finalcat=consumer.GeometryCatalog();finalwater=consumer.WaterReference()
    for tid in ids:finalcat.geometry(tid)
    finalwater.lake_level_candidate();finalwater.query_product([[0,0]])
    print(json.dumps({'passed':True,'checks':len(checks),'packageSha256':sha((OUT/'PACKAGE.json').read_bytes()),'files':len(files),'bytes':sum(x['bytes']for x in files)}))

if __name__=='__main__':main()
