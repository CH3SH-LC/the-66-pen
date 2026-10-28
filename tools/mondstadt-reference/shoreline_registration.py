"""Extract terrain/plane intersection curves for independent shoreline controls."""
import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

from reference_cli import PROJECT, project_path, write_json


def contour_segments(vertices,faces,height):
    segments=[]
    for face in faces:
        triangle=vertices[face];signed=triangle[:,1]-height;points=[]
        for a,b in ((0,1),(1,2),(2,0)):
            if signed[a]*signed[b]<0:
                t=-signed[a]/(signed[b]-signed[a]);points.append(triangle[a]+t*(triangle[b]-triangle[a]))
            elif abs(signed[a])<1e-7 and abs(signed[b])>1e-7:points.append(triangle[a])
        if len(points)==2 and np.linalg.norm(points[0]-points[1])>1e-5:
            segments.append(np.asarray(points)[:,[0,2]])
    return np.asarray(segments)


def main(args):
    root=PROJECT/'data/mondstadt/reference3d';extracted=root/'extracted-viewer'
    index=json.loads((extracted/'index.json').read_text(encoding='utf-8'))
    selection=json.loads((root/'surface-selection.json').read_text(encoding='utf-8'))
    registration=json.loads((root/'registration.json').read_text(encoding='utf-8'))
    matrix=np.asarray(registration['matrix2x2']);offset=np.asarray(registration['offsetPixels'])
    result=[];fig,ax=plt.subplots(figsize=(14,14))
    tiles=PROJECT/'.runtime/mondstadt/rework-20261017/reference-source'
    for x in (93,94,95,96):
        for y in (33,34,35,36):
            ax.imshow(plt.imread(tiles/f'{x}_{y}_P0.png'),extent=[x*256,(x+1)*256,(y+1)*256,y*256])
    for mid,color in [('hlod-2_-1','red'),('hlod-2_-2','orange')]:
        archive=np.load(extracted/(mid+'.npz'));rows=json.loads((extracted/(mid+'-components.json')).read_text(encoding='utf-8'))['candidates']
        cs={r['candidateId']:r for r in rows};ids=selection['meshes'][mid]['selection']['base-terrain']
        faces=archive['faces'][[f for cid in ids for f in cs[cid]['faceIds']]]
        segments=contour_segments(archive['vertices'],faces,args.height)
        pixel=segments@matrix+offset
        ax.add_collection(LineCollection(pixel,colors=color,linewidths=1,label=mid+' viewer'))
        record=next(r for r in index['meshSources'] if r['id']==mid)
        shift=np.array([1024,0])-np.array(record['rawToFrame'])[[0,2],3]
        # Alternative follows the raw baked source X plus exactly one common 1024 translation.
        alternative=(segments+shift)@matrix+offset
        ax.add_collection(LineCollection(alternative,colors='cyan',linewidths=.7,linestyles='dashed'))
        result.append({'mesh':mid,'height':args.height,'viewerSegmentsXZ':segments.tolist(),
                       'rawBakedPlus1024CandidateShiftXZ':shift.tolist(),'segmentCount':len(segments),
                       'meaning':'height-plane intersections, shoreline candidates; map water artwork is approximate'})
    ax.set_xlim(23950,24550);ax.set_ylim(9300,8750);ax.set_aspect('equal')
    ax.set_xticks(np.arange(23950,24551,50));ax.set_yticks(np.arange(8750,9301,50));ax.tick_params(axis='x',labelrotation=90);ax.grid(alpha=.4)
    ax.set_title('Native-source HLOD ground at water candidate Y=202.4: viewer red/orange; raw-baked +1024 cyan')
    ax.legend();out=project_path(args.out);out.mkdir(parents=True,exist_ok=True)
    fig.savefig(out/'shoreline-overlay.png',dpi=180,bbox_inches='tight');plt.close(fig)
    write_json(out/'shoreline-segments.json',{'schema':1,'planeSemantics':'large source water candidate, not synthetic ocean',
        'height':args.height,'groups':result})
    # Manual landmark observations are kept separate from the geometric fit.
    # The two doubtful correspondences are intentionally retained as doubtful.
    regions=[('southern-island-tip',[24280,24335,9100,9150],1,'max',[24315,9125]),
             ('east-island-cape',[24440,24480,8980,9020],0,'max',[24460,9005]),
             ('northeast-beach-cape',[24410,24460,8910,8950],0,'max',[24444,8931]),
             ('cathedral-western-shore',[24045,24075,8830,8880],0,'min',[24051,8850]),
             ('harbour-northern-inlet',[24390,24420,8870,8895],1,'min',[24405,8884])]
    points=np.asarray(result[0]['viewerSegmentsXZ']).reshape(-1,2);pixels=points@matrix+offset
    controls=[]
    for number,(name,window,axis,mode,target) in enumerate(regions):
        candidate=np.flatnonzero((pixels[:,0]>=window[0])&(pixels[:,0]<=window[1])&
                                (pixels[:,1]>=window[2])&(pixels[:,1]<=window[3]))
        if not len(candidate):raise ValueError('Missing explicitly selected shoreline feature '+name)
        i=candidate[np.argmax(pixels[candidate,axis]) if mode=='max' else np.argmin(pixels[candidate,axis])]
        controls.append({'id':name,'mesh':result[0]['mesh'],'sourceXZ':points[i].tolist(),
            'sourceSegmentEndpointIndex':int(i),'selection':{'predictedPixelWindow':window,'extremum':mode,'axis':axis},
            'officialGlobalPixel':target,'predictedPixel':pixels[i].tolist(),
            'residualPixels':float(np.linalg.norm(pixels[i]-target)),'estimatedPixelUncertainty':5,
            'method':'Manual visual shoreline feature identification; original geometric plane contour extremum, not native survey',
            'correspondenceStatus':'identified-distinct-cape' if number<3 else 'ambiguous-coarse-contour-vs-drawn-map'})
    write_json(out/'shoreline-controls.json',{'schema':1,'sourceHeight':args.height,'sourceFrame':'viewer',
        'notUsedToFitCityRegistration':True,'controls':controls,
        'rmsePixelsAllControlsIncludingAmbiguous':float(np.sqrt(np.mean([x['residualPixels']**2 for x in controls]))),
        'maxResidualPixelsAllControlsIncludingAmbiguous':max(x['residualPixels'] for x in controls),
        'acceptedControlMeaning':'Three distinct capes agree approximately; two ambiguous controls remain recorded and are not fitted away. No per-block native coordinate survey.'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--height',type=float,default=202.4)
    p.add_argument('--out',default='data/mondstadt/reference3d/shoreline-review');main(p.parse_args())
