"""One final offline batch after complete module development; freeze only on pass."""
import hashlib,importlib.util,json,os,sqlite3,struct,sys,time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from PIL import Image
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
from sources import ROOT,OUTPUT,Reader
from serialized_reference import metadata,object_identity
from native_mesh_reference import read_mesh
from resource_index import ResourceIndex,INDEX,PATCH_INDEX,INDEX_CAB

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def save(p,obj):Path(p).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def run():
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package; no repeated batch')
    start=time.time();checks=[]
    def check(name,condition,details=None):
        checks.append({'name':name,'passed':bool(condition),'details':details})
        if not condition:raise AssertionError(name)
    index=read(OUTPUT/'geometry-index.json');identity=read(OUTPUT/'template-identities.json');projection=read(OUTPUT/'projections.json')
    expected={x['templateId']for x in identity['rows']};check('38 exact selected templates captured',len(expected)==38 and {x['templateId']for x in index['rows']}==expected and all(x['status']=='captured'for x in index['rows']))
    nodes={};payloads={}
    for pattern in ['raw/*/source.json','raw-persistent-index/*/source.json']:
        for p in OUTPUT.glob(pattern):
            receipt=read(p);raw=(p.parent/'node.bin').read_bytes();check('captured node SHA '+str(p.parent.name),hashlib.sha256(raw).hexdigest()==receipt['nodeSha256'])
            parsed=metadata(raw);captured=read(p.parent/'metadata.json')
            for o in parsed['objects']:
                try:o['identity']=object_identity(o,raw[o['offset']:o['offset']+o['size']],parsed['endian'])
                except (ValueError,UnicodeError)as e:o['identityError']=str(e)
            check('independent metadata reparse '+p.parent.name,parsed==captured)
            if p.parent.parent.name=='raw':nodes[p.parent.name]=parsed;payloads[p.parent.name]=raw
    # Re-decode original pinned tables and captured OfficialPrefab wire, never the decoded join alone.
    sys.path.insert(0,str(ROOT/'tools/npc-appearance'));from official_models import Catalog
    from asset_inspection_templates import decode_official
    native=Catalog();res=ResourceIndex();base=ResourceIndex(INDEX)
    source_folder=OUTPUT/'raw-persistent-index'/INDEX_CAB;meta=read(source_folder/'metadata.json');obj=next(o for o in meta['objects']if o['pathId']==3)
    node=(source_folder/'node.bin').read_bytes();payload=node[obj['offset']+4:obj['offset']+4+res.source['payloadBytes']]
    check('persistent payload SHA',hashlib.sha256(payload).hexdigest()==res.source['payloadSha256'])
    for row in identity['rows']:
        tid=row['templateId'];captured=ROOT/row['capturedOfficialFile'];check('OfficialPrefab SHA '+str(tid),digest(captured)==row['officialSource']['sha256'])
        fields,_=decode_official(captured.read_bytes());decoded=native.resolve_fields(tid,fields,row['officialSource'])
        check('native model identity '+str(tid),all(decoded[k]==row[k]for k in ['persistedBaseReference','configId','modelResourceHandle']))
        for location in res.lookup(row['modelResourceHandle']):
            at=location['assetRecordOffset'];handle,count=struct.unpack_from('<QB',payload,at);variants=[struct.unpack_from('<Bi',payload,at+9+5*i)for i in range(count)]
            check('raw fullU64 lookup '+str(tid),str(handle)==row['modelResourceHandle']and(location['language'],location['encodedBundleIndex'])in variants)
            block=location['block'];bid,offset,size=struct.unpack_from('<III',payload,block['recordOffset']);check('raw bundle record '+str(tid),(bid,offset,size)==(location['bundleIndex'],block['offset'],block['size']))
    same=read(OUTPUT/'persistent-index-comparison.json');check('38 base/persistent logical bindings identical',same['allSelectedBindingsUnchanged']and len(same['selectedComparison'])==38)
    # Independently reconstruct each matrix using scipy quaternion conversion.
    max_vertex_residual=0.;total_parts=0;total_faces=0
    for entry in index['rows']:
        tid=entry['templateId'];row=read(ROOT/entry['geometry']);hier={(x['cab'],x['transformPathId']):x for x in row['hierarchy']};cache={}
        def transform(key):
            if key in cache:return cache[key]
            h=hier[key];t=h['localTRS'];father=t['father'];m=np.eye(4);m[:3,:3]=Rotation.from_quat(t['localRotation']).as_matrix()@np.diag(t['localScale']);m[:3,3]=t['localPosition']
            if father['pathId']==0:m=np.eye(4)
            else:
                if father['fileId']!=0:raise ValueError('Batch independent external parent unsupported')
                m=transform((key[0],father['pathId']))@m
            cache[key]=m;return m
        go_to_t={(x['gameObjectCab'],x['gameObjectPathId']):(x['cab'],x['transformPathId'])for x in row['hierarchy']};combined=[];visible=[]
        for part in row['parts']:
            path=ROOT/part['npz'];check('part artifact SHA '+str(tid)+':'+str(part['partIndex']),digest(path)==part['npzSha256']);a=np.load(path,allow_pickle=False)
            verts=a['vertices'];faces=a['triangles'];m=transform(go_to_t[(part['gameObjectCab'],part['gameObjectPathId'])]);transformed=(m@np.column_stack((verts,np.ones(len(verts)))).T).T[:,:3]
            residual=float(np.max(np.abs(transformed-a['rootLocalVertices'])));max_vertex_residual=max(max_vertex_residual,residual)
            check('independent TRS vertex transform '+str(tid)+':'+str(part['partIndex']),residual<1e-10)
            used=transformed[np.unique(faces)];check('referenced vertex bounds '+str(tid)+':'+str(part['partIndex']),np.allclose(used.min(axis=0),part['bounds']['minXYZ'],atol=1e-10)and np.allclose(used.max(axis=0),part['bounds']['maxXYZ'],atol=1e-10))
            cab=part['meshCab'];o=next(o for o in nodes[cab]['objects']if o['pathId']==part['meshPathId']);raw=payloads[cab][o['offset']:o['offset']+o['size']]
            check('exact referenced Mesh object '+str(tid)+':'+str(part['partIndex']),o['classId']==43 and hashlib.sha256(raw).hexdigest()==part['meshObjectSha256'])
            decoded_mesh,decoded_arrays=read_mesh(raw)
            check('Mesh bytes reproduce exported topology/positions '+str(tid)+':'+str(part['partIndex']),np.array_equal(decoded_arrays['vertices'],verts)and np.array_equal(decoded_arrays['triangles'],faces))
            combined.append(used)
            if part['nonShadowEnabledStaticCandidate']:visible.append(used)
            total_parts+=1;total_faces+=len(faces)
        v=np.concatenate(visible);b=row['nonShadowEnabledStaticBounds'];check('visible static union '+str(tid),np.allclose(v.min(axis=0),b['minXYZ'],atol=1e-10)and np.allclose(v.max(axis=0),b['maxXYZ'],atol=1e-10))
        check('no runtime promotion '+str(tid),all(row[k]is False for k in ['runtimeRendererBoundsVerified','runtimeColliderBoundsVerified','runtimePivotVerified','gameProcessAccessed']))
        check('no unresolved static MeshFilter '+str(tid),row['staticGeometryComplete']and not row['unresolved'])
        check('current index binding recorded '+str(tid),row['resourceIndexSource']['payloadSha256']==res.source['payloadSha256'])
    for item in projection['rows']:
        path=ROOT/item['path'];im=Image.open(path);im.verify();check('projection PNG '+str(item['templateId']),digest(path)==item['sha256']and item['textureApplied']is False and item['runtimeScreenshot']is False)
    check('projection complete',len(projection['rows'])==38 and {x['templateId']for x in projection['rows']}==expected)
    priority=read(OUTPUT/'source-priority.json');containers=[]
    for x in priority['rows']:
        p=Path(x['capturedPath']);md5=hashlib.md5();s256=hashlib.sha256()
        with p.open('rb')as f:
            while block:=f.read(4*1024**2):md5.update(block);s256.update(block)
        match=x['manifestEntry']is not None and md5.hexdigest()==x['manifestEntry']['md5']
        if x['capturedIsPreferred']:check('preferred source matches installation manifest '+p.name,match)
        containers.append({'path':str(p),'sha256':s256.hexdigest(),'md5':md5.hexdigest(),'currentManifestMatches':match,'preferred':x['capturedIsPreferred']})
    receipt={'schema':'template-geometry-offline-batch-v1','passed':True,'checks':checks,'templateCount':38,'partCount':total_parts,'triangleCount':total_faces,
        'maxIndependentTransformResidual':max_vertex_residual,'sourceContainers':containers,'elapsedSeconds':time.time()-start,
        'gameProcessAccessed':False,'runtimeAcceptance':False,'visualReview':'Technical PNG review by owner/root occurs after this batch; not material/game acceptance'}
    save(OUTPUT/'offline-receipt.json',receipt)
    # Freeze all owned artifact/code bytes only after the complete source batch succeeds.
    paths=[p for folder in [OUTPUT,HERE]for p in folder.rglob('*')if p.is_file()and '__pycache__'not in p.parts and p.name!='PACKAGE.json']
    files=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest(p)}for p in sorted(paths)]
    package={'schema':'frozen-template-geometry-v1','offlineValidationPassed':True,'templateCount':38,'files':files,
        'entry':'data/mondstadt/reference3d/template-geometry-v1/geometry-index.json','api':'tools/mondstadt-reference/template_geometry/api.py',
        'sourceIndex':'Persistent asset_index; base retained; selected bindings identical','runtimeAcceptance':False}
    save(OUTPUT/'PACKAGE.json',package)
    # Public frozen API is exercised in this same batch; retract seal on failure.
    try:
        spec=importlib.util.spec_from_file_location('template_geometry_public_api',HERE/'api.py');api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api);consumer=api.GeometryCatalog()
        for tid in expected:
            r=consumer.geometry(tid);b=consumer.transformed_bounds(tid,np.eye(4));assert np.allclose(b['sizeXYZ'],r['nonShadowEnabledStaticBounds']['sizeXYZ'])
        try:consumer.transformed_bounds(20002108,np.zeros((3,3)))
        except ValueError:pass
        else:raise AssertionError('Non-affine transform accepted')
    except Exception:
        (OUTPUT/'PACKAGE.json').unlink();receipt['passed']=False;receipt['publicApiPassed']=False;save(OUTPUT/'offline-receipt.json',receipt);raise
    receipt.update(publicApiPassed=True,publicApiTemplateCount=38,invalidAffineRejected=True)
    save(OUTPUT/'offline-receipt.json',receipt)
    package['files']=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest(p)}for p in sorted(paths)]
    save(OUTPUT/'PACKAGE.json',package)
    print(json.dumps({'passed':True,'checks':len(checks),'templates':38,'parts':total_parts,'triangles':total_faces,'maxResidual':max_vertex_residual,
        'publicApiTemplates':38,'packageSha256':digest(OUTPUT/'PACKAGE.json'),'seconds':time.time()-start}))

if __name__=='__main__':run()
