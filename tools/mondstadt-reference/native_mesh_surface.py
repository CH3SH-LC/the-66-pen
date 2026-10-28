"""Query only explicitly selected architectural source faces, returning all hits.

There is no highest-hit-is-ground default. Owners choose semantic source faces;
the returned normal, face ID and all layers let them place roads/steps/NPCs with
their actual surface instead of placing everything on the TerrainData base.
"""
from __future__ import annotations
import json,math
from pathlib import Path
import numpy as np
from reference_cli import digest
from native_ground_reference import product_to_native_xz


class SelectedMeshSurface:
    def __init__(self,vertices,triangles,face_ids,bin_size=32.):
        self.vertices=np.asarray(vertices,float);self.triangles=np.asarray(triangles,dtype=np.int64);self.face_ids=np.asarray(face_ids,dtype=np.int64)
        if self.vertices.ndim!=2 or self.vertices.shape[1]!=3 or not np.isfinite(self.vertices).all():raise ValueError('Finite source vertices required')
        if self.triangles.ndim!=2 or self.triangles.shape[1]!=3 or self.triangles.min(initial=0)<0 or self.triangles.max(initial=0)>=len(self.vertices):raise ValueError('Valid source triangle indices required')
        if self.face_ids.ndim!=1 or len(np.unique(self.face_ids))!=len(self.face_ids) or self.face_ids.min(initial=0)<0 or self.face_ids.max(initial=-1)>=len(self.triangles):raise ValueError('Explicit unique source face IDs required')
        if not math.isfinite(bin_size) or bin_size<=0:raise ValueError('Positive finite bin size required')
        self.bin_size=bin_size;self.cells={};self.faces=self.vertices[self.triangles[self.face_ids]];self.normals=np.cross(self.faces[:,1]-self.faces[:,0],self.faces[:,2]-self.faces[:,0])
        lengths=np.linalg.norm(self.normals,axis=1);self.normals/=np.maximum(lengths[:,None],1e-30)
        for i,t in enumerate(self.faces):
            low=np.floor(t[:,[0,2]].min(0)/bin_size).astype(int);high=np.floor(t[:,[0,2]].max(0)/bin_size).astype(int)
            if (high[0]-low[0]+1)*(high[1]-low[1]+1)>100000:raise ValueError('Unexpected unbounded face projection')
            for ix in range(low[0],high[0]+1):
                for iz in range(low[1],high[1]+1):self.cells.setdefault((ix,iz),[]).append(i)

    @classmethod
    def from_semantic_file(cls,package,semantic_relative,classification):
        package=Path(package).resolve();path=(package/semantic_relative).resolve()
        if not path.is_relative_to(package):raise ValueError('Semantic path outside package')
        semantic=json.loads(path.read_text(encoding='utf8'));geometry=(package/semantic['nativeGeometry']).resolve()
        if not geometry.is_relative_to(package) or digest(geometry)!=semantic['nativeGeometrySha256']:raise ValueError('Geometry provenance mismatch')
        chosen=[r for r in semantic['classifications'] if r['classification']==classification]
        if len(chosen)!=1:raise ValueError('One explicit semantic classification required; no highest-surface fallback')
        a=np.load(geometry,allow_pickle=False);result=cls(a['vertices'],a['triangles'],chosen[0]['faceIds']);result.semantic={'classification':classification,'semanticSha256':digest(path),'geometrySha256':digest(geometry),'verifiedInGame':semantic['semanticsVerifiedInGame']};return result

    def query_native(self,points):
        points=np.asarray(points,float)
        if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all():raise ValueError('Finite N by2 XZ required')
        output=[]
        for x,z in points:
            hits=[]
            for i in self.cells.get((math.floor(x/self.bin_size),math.floor(z/self.bin_size)),[]):
                t=self.faces[i];a=t[1]-t[0];b=t[2]-t[0];det=a[0]*b[2]-b[0]*a[2]
                if abs(det)<1e-10:continue
                dx,dz=x-t[0,0],z-t[0,2];u=(dx*b[2]-b[0]*dz)/det;v=(a[0]*dz-dx*a[2])/det
                if u< -1e-9 or v< -1e-9 or u+v>1+1e-9:continue
                hits.append({'sourceFaceId':int(self.face_ids[i]),'nativeY':float(t[0,1]+u*a[1]+v*b[1]),'sourceWindingNormalXYZ':self.normals[i].tolist(),'barycentric':[float(1-u-v),float(u),float(v)]})
            hits.sort(key=lambda h:(h['nativeY'],h['sourceFaceId']))
            output.append({'nativeXZ':[float(x),float(z)],'hits':hits,'automaticGroundSelection':False,'semantic':getattr(self,'semantic',None)})
        return output

    def query_product(self,points,mapping):
        rows=self.query_native(product_to_native_xz(points,mapping));m=np.asarray(mapping['nativeToProductMatrixColumnVector'],float);normal_rotation=m[:3,:3]/float(mapping['scale'])
        for row,p in zip(rows,points):
            row['productXZ']=list(map(float,p));row['productTransformId']=mapping['id'];row['editorOffsetApplied']=False
            for hit in row['hits']:hit.update(productY=float(m[1,1]*hit['nativeY']+m[1,3]),productNormalXYZ=(normal_rotation@np.asarray(hit['sourceWindingNormalXYZ'])).tolist())
        return rows
