"""Named source landmark geometry, without guessing native prefab identities."""
import json
import math
import numpy as np
from geometry import convex_hull
from reference_cli import PROJECT, write_json, digest


def main():
    root=PROJECT/'data/mondstadt/reference3d';extracted=root/'extracted-final-v1'
    source=np.load(extracted/'mondstadt-city-lod0.npz')
    components={c['candidateId']:c for c in json.loads((extracted/'city-components.json').read_text(encoding='utf-8'))['candidates']}
    registration=json.loads((root/'registration.json').read_text(encoding='utf-8'))
    definitions=[('cathedral-superstructure-reference',[107,108,109,110,111],False,'Main cathedral roof and three spires; associated terrace is separate ground component450'),
                 ('anemo-statue-reference',[437,438,439,440,441],False,'Wing and body fragments visually identified; not a native prefab'),
                 ('main-city-gate-reference',[568,569,570],True,'Two gate towers and middle arch geometry')]
    definitions += [(f'wall-tower-{i}',[i],True,'Individual source wall tower geometry') for i in range(287,296)]
    output=[]
    for name,cids,whole,note in definitions:
        ids=sorted({f for cid in cids for f in components[cid]['faceIds']})
        points=source['vertices'][np.unique(source['faces'][ids])]
        low,high=points.min(axis=0),points.max(axis=0);center=(low+high)/2
        centered=points[:,[0,2]]-points[:,[0,2]].mean(axis=0)
        values,vectors=np.linalg.eigh(centered.T@centered)
        direction=vectors[:,np.argmax(values)];yaw=math.degrees(math.atan2(direction[1],direction[0]))%180
        hull=np.array(convex_hull(points[:,[0,2]]))
        pixels=hull@np.array(registration['matrix2x2'])+np.array(registration['offsetPixels'])
        output.append({'name':name,'componentIds':cids,'sourceFaceIds':ids,
            'sourceAabbMin':low.tolist(),'sourceAabbMax':high.tolist(),'sizeXYZ':(high-low).tolist(),
            'geometryCenterXYZ':center.tolist(),'nativePivotKnown':False,
            'principalAxisYawModulo180':yaw,'nativeRotationKnown':False,
            'convexFootprintXZ':hull.tolist(),'officialPixelFootprint':pixels.tolist(),
            'sourceBottomRelativeToWaterCandidate202_4':float(low[1]-202.4),
            'sourceTopRelativeToWaterCandidate202_4':float(high[1]-202.4),
            'wholeVisibleObjectCandidate':whole,'description':note,
            'nativePrefabId':None,'semantics':'analyst identification of source geometry; requires owner asset assembly mapping'})
    write_json(root/'named-landmarks.json',{'schema':1,'sourceFrame':'viewer','sourceMesh':'extracted-final-v1/mondstadt-city-lod0.npz',
        'meshSourceSha256':json.loads((extracted/'index.json').read_text(encoding='utf-8'))['meshSources'][0]['sourceSha256'],
        'registrationSha256':digest(root/'registration.json'),'landmarks':output})


if __name__=='__main__':main()
