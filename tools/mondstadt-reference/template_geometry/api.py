"""Frozen offline geometry consumer; never opens installation or a process."""
import argparse,hashlib,json,sys
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
DEFAULT=ROOT/'data/mondstadt/reference3d/template-geometry-v1'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

class GeometryCatalog:
    def __init__(self,folder=DEFAULT):
        self.folder=Path(folder).resolve();p=self.folder/'PACKAGE.json'
        if not p.exists():raise ValueError('Package not frozen and validated')
        self.package=json.loads(p.read_text(encoding='utf8'))
        if self.package.get('offlineValidationPassed')is not True:raise ValueError('Package validation incomplete')
        self.expected={x['path']:x['sha256']for x in self.package['files']}
        self.index=self.read('data/mondstadt/reference3d/template-geometry-v1/geometry-index.json')
        self.rows={x['templateId']:x for x in self.index['rows']}
    def path(self,relative):
        path=(ROOT/relative).resolve()
        if not path.is_relative_to(ROOT)or str(Path(relative))not in self.expected:raise ValueError('Unregistered package file')
        if sha(path)!=self.expected[str(Path(relative))]:raise ValueError('Package file changed: '+relative)
        return path
    def read(self,relative):return json.loads(self.path(relative).read_text(encoding='utf8'))
    def geometry(self,template_id):
        row=self.rows[int(template_id)]
        if row['status']!='captured':raise ValueError('Template geometry unavailable')
        return self.read(row['geometry'])
    def vertices(self,template_id,scope='non-shadow-enabled-static'):
        row=self.geometry(template_id);data=np.load(self.path(row['combinedMesh']['npz']),allow_pickle=False)
        faces=data['triangles'];parts=data['facePart']
        if scope=='non-shadow-enabled-static':faces=faces[np.isin(parts,[x['partIndex']for x in row['parts']if x['nonShadowEnabledStaticCandidate']])]
        elif scope!='all-static':raise ValueError('Unknown geometry scope')
        return data['vertices'][np.unique(faces)]
    def transformed_bounds(self,template_id,matrix,scope='non-shadow-enabled-static'):
        """Explicit source-root to caller frame. No implicit editor/world scaling."""
        matrix=np.asarray(matrix,dtype=float)
        if matrix.shape!=(4,4)or not np.isfinite(matrix).all()or not np.allclose(matrix[3],[0,0,0,1],atol=1e-12):raise ValueError('Finite affine 4x4 required')
        v=self.vertices(template_id,scope);v=v@matrix[:3,:3].T+matrix[:3,3]
        return {'minXYZ':v.min(axis=0).tolist(),'maxXYZ':v.max(axis=0).tolist(),'sizeXYZ':np.ptp(v,axis=0).tolist(),
            'sourceRootToCallerMatrix':matrix.tolist(),'scope':scope,'runtimeVerified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--template-id',type=int,required=True);a=p.parse_args();row=GeometryCatalog().geometry(a.template_id)
    print(json.dumps({k:row[k]for k in ['templateId','prefabRoot','nonShadowEnabledStaticBounds','staticGeometryComplete','limitations']},ensure_ascii=False,indent=2))
