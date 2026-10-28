"""Triangle-level normals/heights/UV evidence for selected city foundations."""
import hashlib
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from reference_cli import PROJECT, write_json, digest


def main():
    root=PROJECT/'data/mondstadt/reference3d';extracted=root/'extracted-viewer';out=root/'semantic-review';out.mkdir(parents=True,exist_ok=True)
    src=PROJECT/'.runtime/mondstadt/rework-20261017/reference3d/source'
    obj=src/'Area_Mengde_City_Constant_HLOD_Lod0.obj';texture_path=src/'Stages_Texture_Area_Mengde_City_HLOD_Combined_Diffuse.png'
    tex=plt.imread(texture_path);uv=[];face_uv=[]
    for line in obj.read_text(encoding='utf-8-sig').splitlines():
        p=line.split()
        if not p:continue
        if p[0]=='vt':uv.append([float(p[1]),float(p[2])])
        if p[0]=='f':face_uv.append([int(x.split('/')[1])-1 for x in p[1:]])
    uv=np.asarray(uv);face_uv=np.asarray(face_uv,dtype=np.int64)
    a=np.load(extracted/'mondstadt-city-lod0.npz');vertices,faces=a['vertices'],a['faces']
    if len(face_uv)!=len(faces):raise ValueError('OBJ face/UV ordering mismatch')
    coords=uv[face_uv].mean(axis=1)
    ix=np.rint(np.clip(coords[:,0],0,1)*(tex.shape[1]-1)).astype(int)
    iz=np.rint((1-np.clip(coords[:,1],0,1))*(tex.shape[0]-1)).astype(int)
    colors=tex[iz,ix,:3]
    rows={r['candidateId']:r for r in json.loads((extracted/'city-components.json').read_text(encoding='utf-8'))['candidates']}
    selection=json.loads((root/'surface-selection.json').read_text(encoding='utf-8'))
    selected=selection['meshes']['mondstadt-city-lod0']['selection']['city-paved']
    records=[]
    for cid in selected+[107,111]:
        row=rows[cid];ids=np.array(row['faceIds']);triangles=vertices[faces[ids]]
        normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);length=np.linalg.norm(normal,axis=1)
        unit=normal/np.maximum(length[:,None],1e-20);slope=np.degrees(np.arccos(np.clip(np.abs(unit[:,1]),0,1)))
        area=length/2;flat=(slope<=10)&(np.ptp(triangles[:,:,1],axis=1)<=.5)
        clusters={}
        for y,ar in zip(triangles[flat,:,1].mean(axis=1),area[flat]):
            k=str(round(float(y)*2)/2);clusters[k]=clusters.get(k,0)+float(ar)
        records.append({'componentId':cid,'selectedAsPavedCandidate':cid in selected,
            'aabbMin':row['aabbMin'],'aabbMax':row['aabbMax'],'faceCount':len(ids),
            'surfaceArea':float(area.sum()),'nearHorizontalAreaWithin10deg':float(area[slope<=10].sum()),
            'horizontalHeightClustersRoundedToHalfUnitArea':clusters,
            'retainedGroundFaceIds':ids[slope<=60].tolist() if cid in selected else [],
            'steepFacesExcludedFromGround':ids[slope>60].tolist() if cid in selected else [],
            'faces':[{'sourceFaceId':int(fi),'yMin':float(t[:,1].min()),'yMax':float(t[:,1].max()),
                      'normalXYZ':n.tolist(),'slopeDegrees':float(s),'surfaceArea':float(ar),
                      'uvSampleRgb':c.tolist()} for fi,t,n,s,ar,c in zip(ids,triangles,unit,slope,area,colors[ids])]})
    write_json(out/'component-surface-audit.json',{'schema':1,'citySourceSha256':digest(obj),'textureSha256':digest(texture_path),
        'uvSampling':'mean face UV, OBJ bottom-left to PNG top-left; diagnostic color only',
        'groundSlopeLimitDegrees':60,'records':records,
        'component450Conclusion':'Broad cathedral base/terrace: max Y260.266 versus cathedral body107 max284.454 and spire111 min303.95. The topdown label overlaps roof projection; components are separate.'})
    ids_to_plot=[444,448,449,450,452,454,458,461,466,481,107,111]
    fig,axes=plt.subplots(3,4,figsize=(18,14))
    for ax,cid in zip(axes.flat,ids_to_plot):
        ids=np.array(rows[cid]['faceIds']);triangles=vertices[faces[ids]];order=np.argsort(triangles[:,:,1].mean(axis=1))
        patch=PolyCollection(triangles[order][:,:,[0,2]],facecolors=colors[ids][order],edgecolors='black',linewidths=.2)
        ax.add_collection(patch);ax.autoscale_view();ax.set_aspect('equal');ax.set_title(f'Component {cid}: Y {triangles[:,:,1].min():.2f}..{triangles[:,:,1].max():.2f}')
    fig.suptitle('Source OBJ UV samples: explicit ground candidates; last two are excluded cathedral roof/spire')
    fig.tight_layout();fig.savefig(out/'component-uv-review.png',dpi=160);plt.close(fig)
    fig=plt.figure(figsize=(12,9));ax=fig.add_subplot(111,projection='3d')
    for cid,color in [(450,'green'),(107,'sienna'),(111,'blue')]:
        tri=vertices[faces[rows[cid]['faceIds']]]
        # Horizontal X/Z, vertical Y; no rescaling of source heights.
        ax.add_collection3d(Poly3DCollection(tri[:,:,[0,2,1]],facecolors=color,alpha=.7,linewidths=.1,edgecolors='black'))
    ax.set_xlim(-1395,-1280);ax.set_ylim(-725,-590);ax.set_zlim(230,325);ax.set_box_aspect((115,135,95))
    ax.set_xlabel('X');ax.set_ylabel('Z');ax.set_zlabel('Y');ax.view_init(elev=25,azim=-55)
    ax.set_title('450 terrace green; 107 cathedral body brown; 111 spire blue (original source coordinates)')
    fig.savefig(out/'component-450-context.png',dpi=160,bbox_inches='tight');plt.close(fig)


if __name__=='__main__':main()
