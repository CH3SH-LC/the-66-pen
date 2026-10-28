"""Build source delivery notes/plots and a face-level lake elevation selection."""
import shutil
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from common import *

def build():
    writable();water=json.loads((OUT/'lake-consumer.json').read_text(encoding='utf8'))
    anchor=next(x for x in water['parts']if x['id']=='water-13-part-0')
    with np.load(ROOT/anchor['geometry'])as a:
        vv=a['nativeVertices'];ff=a['triangles'];level=float(vv[ff[0],1].mean())
    selected=[];nv=[];pv=[];tri=[];facepart=[];faceid=[];cursor=0;tolerance=1e-4
    for j,part in enumerate(water['parts']):
        with np.load(ROOT/part['geometry'])as a:
            v=a['nativeVertices'];p=a['productVertices'];f=a['triangles'];hit=np.flatnonzero(np.max(np.abs(v[f,1]-level),axis=1)<=tolerance)
            if not len(hit):continue
            selected.append({'partId':part['id'],'sourceFaceIds':hit.tolist(),'count':len(hit),'meshCab':part['meshCab'],'meshPathId':part['meshPathId']})
            nv.append(v);pv.append(p);tri.append(f[hit]+cursor);facepart.extend([j]*len(hit));faceid.extend(hit.tolist());cursor+=len(v)
    nv=np.concatenate(nv);pv=np.concatenate(pv);faces=np.concatenate(tri)
    # Weld only for topological seam cancellation; saved original vertices stay unmodified.
    _,representative,inverse=np.unique(np.round(nv/1e-4).astype(np.int64),axis=0,return_index=True,return_inverse=True)
    welded=inverse[faces];edges=np.sort(np.concatenate([welded[:,[0,1]],welded[:,[1,2]],welded[:,[2,0]]]),axis=1)
    ue,count=np.unique(edges,axis=0,return_counts=True);boundary=representative[ue[count==1]]
    dest=OUT/'cider-lake-level-candidate.npz'
    np.savez_compressed(dest,nativeVertices=nv,productVertices=pv,triangles=faces,sourcePartIndex=np.asarray(facepart),sourceFaceId=np.asarray(faceid),boundaryVertexPairs=boundary)
    used=np.unique(faces);row={'schema':'source-horizontal-water-selection-v1','status':'geometry-elevation-selection; visible-shoreline-unresolved',
        'selectionRule':'All captured WaterPlane triangles with every nativeY within 0.0001 of the first face of water-13-part-0.',
        'anchorPart':'water-13-part-0','anchorSourceFaceId':0,'nativeY':level,'productY':level*0.5,
        'productFormula':'0.5 * (nativeY - 0); editor offset is not applied','sourceUnitCalibration':'v5 declared product scale, not measured editor unit',
        'toleranceNative':tolerance,'boundaryWeldToleranceNative':1e-4,'geometry':rel(dest),'sha256':sha(dest.read_bytes()),
        'nativeBounds':{'minXYZ':nv[used].min(0).tolist(),'maxXYZ':nv[used].max(0).tolist()},
        'productBounds':{'minXYZ':pv[used].min(0).tolist(),'maxXYZ':pv[used].max(0).tolist()},
        'sourceParts':selected,'triangleCount':len(faces),'boundaryEdgeCount':len(boundary),'nonManifoldWeldedEdgeCount':int((count>2).sum()),
        'waterBodySemantic':'Candidate Cider Lake elevation around native Mondstadt; no automatic geographic lake name classification or terrain visibility claim.',
        'meshBoundaryIsVisibleShoreline':False,'shoreOcclusionEvaluated':False,'runtimeVerified':False}
    save(OUT/'cider-lake-level-candidate.json',row)
    fig,ax=plt.subplots(figsize=(11,10),dpi=150)
    ax.add_collection(PolyCollection(pv[faces][:,:,[0,2]],facecolors='#438db0',edgecolors='none',alpha=.65))
    for a,b in pv[boundary][:,:,[0,2]]:ax.plot([a[0],b[0]],[a[1],b[1]],color='#123449',lw=.35)
    ax.scatter([0],[0],s=30,color='red');ax.annotate('v5 city anchor',(0,0),xytext=(5,6),textcoords='offset points')
    ax.autoscale();ax.set_aspect('equal');ax.set_xlabel('v5 product X (declared scale 0.5)');ax.set_ylabel('v5 product Z')
    ax.set_title(f'Original WaterPlane face selection: native Y = {level:.6f}\nMesh edges only; land/city occlusion and rendered shoreline not evaluated')
    ax.grid(alpha=.2);fig.tight_layout();fig.savefig(OUT/'cider-lake-level-topdown.png');plt.close(fig)
    review=ROOT/'.runtime/mondstadt/rework-20261017/fishing-five-source-visual-review.json'
    shutil.copyfile(review,OUT/'fishing-five-visual-review.json')
    save(OUT/'visual-review-source.json',{'path':rel(review),'sha256':sha(review.read_bytes()),'copiedTo':'fishing-five-visual-review.json'})
    placement=json.loads((OUT/'scene-placement.json').read_text(encoding='utf8'))
    coverage=[]
    for source in placement['sources']:
        dec=json.loads((OUT/'scene-decoded'/('BigWorld_'+source['block']+'.json')).read_text(encoding='utf8'))
        coverage.append({'block':source['block'],'indexedGroups':dec['indexedRecords'],'decodedGroups':source['decodedGroups'],
            'decodedObjects':source['decodedObjects'],'unresolvedGroups':dec['unresolvedGroups'],
            'waterPrefabIds':[p['waterId']for p in placement['placements']if p['sector']==source['block']]})
    save(OUT/'coverage.json',{'sixSectors':coverage,'waterPrefabCount':len(placement['placements']),'waterMeshPartCount':len(water['parts']),
        'unresolvedWaterPrefabIds':placement['unresolvedWaterIds'],'nativeWorldPlacementEvidenceCompleteForCapturedWater':not placement['unresolvedWaterIds'],
        'templateIds':[20001946,20002987,20002811,20002321,20001019],'allGameplayOrRenderedAcceptance':False})
    print(json.dumps({'lakeNativeY':level,'lakeProductY':level/2,'selectedFaces':len(faces),'selectedParts':len(selected),'nativeBounds':row['nativeBounds']}))

if __name__=='__main__':build()
