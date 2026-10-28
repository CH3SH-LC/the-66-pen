"""Resolve exact CAB/PPtr geometry dependencies and export native-world meshes.

No recentering, guessed root transform, or filename-derived mesh transform.
Unresolved references are reported and never emitted as placed geometry.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def build(batch_paths,out):
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned output only')
    nodes={};receipts=[]
    for bp in batch_paths:
        batch=json.loads(bp.read_text(encoding='utf8'));receipts.append({'path':relative(bp),'sha256':digest(bp)})
        for row in batch['items']:
            if row.get('error') or 'acquired' not in row:continue
            directory=project_path(row['acquired']['output']);source=json.loads((directory/'source.json').read_text(encoding='utf8'))
            if digest(directory/'node.bin')!=source['nodeSha256']:raise ValueError('Source node SHA mismatch')
            cab=source['nodePath'].lower();entry={'directory':directory,'source':source,'metadata':json.loads((directory/'metadata.json').read_text(encoding='utf8')),'geometry':row.get('geometry',{})}
            if cab in nodes and nodes[cab]['source']['nodeSha256']!=source['nodeSha256']:raise ValueError('Conflicting CAB versions')
            nodes[cab]=entry
    out.mkdir(parents=True);placed=[];unresolved=[]
    for cab,node in nodes.items():
        objects={o['pathId']:o for o in node['metadata']['objects']};hier={r['gameObject']['pathId']:r for r in node['geometry'].get('localHierarchy',[]) if r['gameObject']['fileId']==0}
        for obj in objects.values():
            if obj['classId']!=33 or 'identity' not in obj:continue
            ident=obj['identity'];go=ident['gameObject'];mesh=ident['mesh'];record={'prefabCab':cab,'meshFilterPathId':obj['pathId'],'gameObjectPathId':go['pathId'],'meshPPtr':mesh}
            try:
                if go['fileId']!=0:raise ValueError('External GameObject unresolved')
                t=hier[go['pathId']]
                if not t['parentChainResolved']:raise ValueError('Unresolved parent chain')
                if mesh['fileId']==0:meshcab=cab
                else:meshcab=node['metadata']['externals'][mesh['fileId']-1]['path'].replace('\\','/').split('/')[-1].lower()
                target=nodes[meshcab];g=next(m for m in target['geometry'].get('meshes',[]) if m['pathId']==mesh['pathId'])
                gp=project_path(g['npz'])
                if digest(gp)!=g['npzSha256']:raise ValueError('Mesh extraction SHA changed')
                a=np.load(gp,allow_pickle=False);matrix=np.array(t['nativeMatrixColumnVector']);v=a['vertices']@matrix[:3,:3].T+matrix[:3,3]
                f=a['triangles'].copy()
                if np.linalg.det(matrix[:3,:3])<0:f=f[:,[0,2,1]]
                path=out/f'world-{len(placed):03d}.npz';np.savez_compressed(path,vertices=v,triangles=f,faceSubmesh=a['faceSubmesh'])
                record.update(name=objects[go['pathId']]['identity']['name'],meshName=g['name'],meshCab=meshcab,meshPathId=mesh['pathId'],nativeMatrixColumnVector=matrix.tolist(),
                    nativeBounds={'xmin':float(v[:,0].min()),'xmax':float(v[:,0].max()),'ymin':float(v[:,1].min()),'ymax':float(v[:,1].max()),'zmin':float(v[:,2].min()),'zmax':float(v[:,2].max())},
                    vertexCount=len(v),triangleCount=len(f),geometry=relative(path),geometrySha256=digest(path),prefabNodeSha256=node['source']['nodeSha256'],meshNodeSha256=target['source']['nodeSha256'],
                    placementEvidence='exact MeshFilter PPtr + CAB dependency + complete native Transform parent chain',frame='native-game-world-XYZ',parentTransformResolved=True,
                    nativeCoordinateUnit='Unity game world unit; product editor conversion separately declared',resolutionClass='native stored asset LOD as named; not a full-detail claim')
                placed.append(record)
            except (KeyError,IndexError,StopIteration,ValueError) as e:unresolved.append(dict(record,error=str(e)))
    result={'schema':1,'sourceBatches':receipts,'frame':'native-game-world-XYZ','placedMeshes':placed,'unresolved':unresolved,'sourceReadMode':'rb','installationWrites':False,'gameProcessAccess':False}
    write_json(out/'native-world-index.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',action='append',required=True);p.add_argument('--out',required=True);a=p.parse_args();r=build([project_path(x) for x in a.batch],project_path(a.out));print(json.dumps({'placed':len(r['placedMeshes']),'unresolved':r['unresolved']}))
