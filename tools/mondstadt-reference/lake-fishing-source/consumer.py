"""Frozen source-only lake and fishing geometry API. No installation access."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
DEFAULT=ROOT/'data/mondstadt/reference3d/lake-fishing-source-v1'

class Package:
    def __init__(self,folder=DEFAULT):
        self.folder=Path(folder).resolve();p=self.folder/'PACKAGE.json'
        d=json.loads(p.read_text(encoding='utf8'))
        if d.get('offlineValidationPassed')is not True:raise ValueError('Source extension not frozen/validated')
        self.expected={str(Path(x['path'])):x['sha256']for x in d['files']}
    def path(self,relative):
        relative=str(Path(relative));p=(ROOT/relative).resolve()
        if not p.is_relative_to(ROOT)or relative not in self.expected:raise ValueError('Unregistered source file')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=self.expected[relative]:raise ValueError('Source SHA mismatch: '+relative)
        return p
    def read(self,relative):return json.loads(self.path(relative).read_text(encoding='utf8'))
    def own(self,name):return self.read(str((self.folder/name).relative_to(ROOT)))

class GeometryCatalog(Package):
    """Same geometry/vertices/transformed_bounds interface as the old38 API."""
    def __init__(self,folder=DEFAULT):
        super().__init__(folder);self.rows={x['templateId']:x for x in self.own('geometry-index.json')['rows']}
    def geometry(self,template_id):
        row=self.rows[int(template_id)]
        if row['status']!='captured':raise ValueError('Requested template geometry unresolved')
        return self.read(row['geometry'])
    def vertices(self,template_id,scope='non-shadow-enabled-static'):
        row=self.geometry(template_id)
        with np.load(self.path(row['combinedMesh']['npz']),allow_pickle=False)as a:
            faces=a['triangles'];parts=a['facePart']
            if scope=='non-shadow-enabled-static':faces=faces[np.isin(parts,[p['partIndex']for p in row['parts']if p['nonShadowEnabledStaticCandidate']])]
            elif scope!='all-static':raise ValueError('Unknown geometry scope')
            return a['vertices'][np.unique(faces)]
    def transformed_bounds(self,template_id,matrix,scope='non-shadow-enabled-static'):
        m=np.asarray(matrix,dtype=float)
        if m.shape!=(4,4)or not np.isfinite(m).all()or not np.allclose(m[3],[0,0,0,1],atol=1e-12):raise ValueError('Explicit finite affine4x4 required')
        v=self.vertices(template_id,scope)@m[:3,:3].T+m[:3,3]
        return {'minXYZ':v.min(axis=0).tolist(),'maxXYZ':v.max(axis=0).tolist(),'sizeXYZ':np.ptp(v,axis=0).tolist(),
            'sourceRootToCallerMatrix':m.tolist(),'scope':scope,'runtimeVerified':False}

class WaterReference(Package):
    """Actual original WaterPlane triangles. Missing scene placement fails closed."""
    def __init__(self,folder=DEFAULT):
        super().__init__(folder);self.index=self.own('lake-consumer.json');self.parts=[]
        for row in self.index['parts']:
            if row['placementStatus']!='source-scene-instance-resolved':continue
            with np.load(self.path(row['geometry']),allow_pickle=False)as a:
                self.parts.append((row,a['nativeVertices'].copy(),a['productVertices'].copy(),a['triangles'].copy()))
    def boundary(self,part_id,frame='product'):
        if frame not in ('product','native'):raise ValueError('Explicit native or product frame required')
        rows=[x for x in self.index['parts']if x['id']==part_id]
        if len(rows)!=1:raise ValueError('Unknown source water part')
        with np.load(self.path(rows[0]['boundary']),allow_pickle=False)as a:
            return {'segments':a[frame+'Vertices'][a['vertexPairs']].copy(),'frame':frame,'visibleShoreline':False,'editorOffsetApplied':False}
    def query_product(self,points,part_ids=None,native_y_band=None):
        q=np.asarray(points,dtype=float)
        if q.ndim!=2 or q.shape[1]!=2 or not np.isfinite(q).all():raise ValueError('Finite N by2 productXZ required')
        if part_ids is not None:
            known={x['id']for x in self.index['parts']}
            if not set(part_ids)<=known:raise ValueError('Unknown source water part')
        if native_y_band is not None:
            band=np.asarray(native_y_band,dtype=float)
            if band.shape!=(2,)or not np.isfinite(band).all()or band[0]>band[1]:raise ValueError('Finite ordered nativeY band required')
        out=[]
        for x,z in q:
            hits=[]
            for row,native,v,faces in self.parts:
                if part_ids is not None and row['id']not in part_ids:continue
                tri=v[faces];a=tri[:,0,[0,2]];u=tri[:,1,[0,2]]-a;w=tri[:,2,[0,2]]-a;d=np.array([x,z])-a
                det=u[:,0]*w[:,1]-u[:,1]*w[:,0];valid=np.abs(det)>1e-12
                b=np.divide(d[:,0]*w[:,1]-d[:,1]*w[:,0],det,out=np.zeros_like(det),where=valid)
                c=np.divide(u[:,0]*d[:,1]-u[:,1]*d[:,0],det,out=np.zeros_like(det),where=valid)
                valid&=(b>=-1e-8)&(c>=-1e-8)&(b+c<=1+1e-8)
                for fid in np.flatnonzero(valid):
                    bary=np.array([1-b[fid]-c[fid],b[fid],c[fid]])
                    ny=float(bary@native[faces[fid],1])
                    if native_y_band is not None and not native_y_band[0]<=ny<=native_y_band[1]:continue
                    hits.append({'partId':row['id'],'sourceFaceId':int(fid),'barycentric':bary.tolist(),
                        'nativeY':ny,'productY':float(bary@tri[fid,:,1]),
                        'sourceMeshCab':row['meshCab'],'sourceMeshPathId':row['meshPathId'],'surfaceKind':'original-WaterPlane-mesh'})
            ys=[h['productY']for h in hits]
            status='sampled-water-mesh'if hits and max(ys)-min(ys)<1e-5 else 'multiple-water-surfaces'if hits else 'outside-captured-water-mesh'if self.parts else 'missing-scene-placement'
            out.append({'productXZ':[float(x),float(z)],'status':status,'hits':hits,
                'productY':ys[0]if status=='sampled-water-mesh'else None,'editorOffsetApplied':False,
                'selection':{'partIds':part_ids,'nativeYBand':native_y_band},'unresolvedWaterPrefabIds':self.index['unresolvedWaterIds'],
                'shoreOcclusionEvaluated':False,'runtimeWaterShaderEvaluated':False,
                'warning':'A mesh hit alone does not establish visible water: terrain/buildings may occlude it.'})
        return out
    def lake_level_candidate(self):
        row=self.own('cider-lake-level-candidate.json')
        with np.load(self.path(row['geometry']),allow_pickle=False)as a:
            return {'metadata':row,'arrays':{k:a[k].copy()for k in a.files}}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--template-id',type=int);p.add_argument('--water-xz',nargs=2,type=float);a=p.parse_args()
    if a.template_id:
        r=GeometryCatalog().geometry(a.template_id);print(json.dumps({k:r[k]for k in ('templateId','prefabRoot','nonShadowEnabledStaticBounds','limitations')},ensure_ascii=False,indent=2))
    elif a.water_xz:print(json.dumps(WaterReference().query_product([a.water_xz]),ensure_ascii=False,indent=2))
    else:p.error('Select --template-id or --water-xz')
