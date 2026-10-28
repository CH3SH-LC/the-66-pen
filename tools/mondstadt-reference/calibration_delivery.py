"""Finalize regional calibration evidence and consumer impact; no source adoption."""
import argparse
import math
import numpy as np

from reference_cli import digest, project_path, write_json
from regional_registration import ROOT, read, relative
from native_frame_evidence import source_derivation


def build(args):
    out=project_path(args.out)
    if not out.is_relative_to(ROOT) or out.exists():raise ValueError('New owned immutable output required')
    out.mkdir(parents=True)
    v3=ROOT/'consumer-all-regions-v3';cal=ROOT/'regional-calibration-v4';native=ROOT/'native-frame-audit-v4'
    index=read(v3/'consumer-index.json');coverage=read(v3/'coverage-report.json');reg=read(ROOT/'registration.json')
    shared_path=ROOT.parent/'outside/terrain/shared-transform.json';shared=read(shared_path)
    scale=float(shared['scale']['value']);source_scale=float(np.linalg.norm(np.array(reg['matrix2x2'])[0]))*scale
    fit={r['mesh']:r for r in read(cal/'regional-registration.json')['rows']}
    caps=read(ROOT/'shoreline-review/shoreline-controls.json')['controls']
    mesh_rows={}
    for mid,code in index['sourceMeshCodes'].items():
        row={'mesh':mid,'meshCode':code,'absoluteNativeHorizontalErrorKnown':False,'absoluteNativeVerticalErrorKnown':False}
        if mid=='mondstadt-city-lod0':
            row.update({'mapControlEvidence':'eight independently identified city landmarks',
                'currentV3MapResidualPixels':{'rmse':reg['rmsePixels'],'max':reg['maxResidualPixels'],'leaveOneOutMax':max(reg['leaveOneOutPixels'])},
                'actualUsefulScope':'city visible HLOD building layout, orientation, footprint and relative heights; not full-resolution architecture, collision, or metre survey',
                'highPrecisionGlobalTerrainSource':False,'cityLayoutReferenceRetained':True})
        elif mid=='hlod-2_-1':
            distinct=[c for c in caps if c['correspondenceStatus']=='identified-distinct-cape']
            row.update({'mapControlEvidence':'three distinct island capes; two ambiguous controls retained but excluded',
                'currentV3MapResidualPixels':{'values':[c['residualPixels'] for c in distinct],'max':max(c['residualPixels'] for c in distinct)},
                'actualUsefulScope':'approximately positioned island HLOD terrain reference; no surveyed vertical datum or regional precision bound',
                'highPrecisionGlobalTerrainSource':False,'cityLayoutReferenceRetained':False})
        else:
            r=fit[mid];f=r['fit'];before=f.get('beforeResidualPixels',[])
            row.update({'mapControlEvidence':'coarse shoreline candidates, not an error-bounded survey',
                'currentV3MapResidualPixels':{'coarseControlResiduals':before,'rmse':float(np.sqrt(np.mean(np.array(before)**2))) if before else None,'max':max(before) if before else None},
                'rejectedCandidateFit':{k:f.get(k) for k in ['controlCount','rmsePixels','maxResidualPixels','maxLeaveOneOutPixels','rejectionReasons']},
                'excludedAmbiguousControls':r['excludedAmbiguousControls'],
                'actualUsefulScope':'rough HLOD relief and source-shape investigation only; unsuitable for claiming precise terrain or bank/road placement',
                'highPrecisionGlobalTerrainSource':False,'cityLayoutReferenceRetained':False})
        row['currentWorldErrorBound']=None
        row['boundMeaning']='No numeric world-error bound inferred from coarse controls or source availability. Pixel residuals only describe these observed 2D features.'
        mesh_rows[mid]=row
    regions=[]
    for r in coverage['regions']:
        counts=r['declaredNew']['meshCodeCounts'];contributing=[mid for mid,code in index['sourceMeshCodes'].items() if counts.get(str(code),0)>0]
        regions.append({'region':r['id'],'declaredRectangle':r['declaredRect'],
            'declaredProbeCount':r['declaredNew']['probes'],'resolvedProbeCount':r['resolvedNew']['probes'],
            'sourceMeshContributions':[{ 'mesh':mid,'count':counts[str(index['sourceMeshCodes'][mid])],
                'evidenceRef':'meshEvidence.'+mid} for mid in contributing],
            'unknownLocationOrHeightErrorCannotBeCollapsedToOneRMSE':True,
            'highPrecisionTerrainSourceEstablished':False,
            'cityLayoutUseful':any(mesh_rows[mid]['cityLayoutReferenceRetained'] for mid in contributing)})
    seams=[]
    for pair in read(native/'overlap-evidence.json')['pairs']:
        stats=pair['before'].get('heightDifferenceSourceUnits')
        seams.append({'meshes':pair['meshes'],'commonSourceQueries':pair['before']['commonVerticalSamples'],
            'observedVerticalDisagreementSourceUnits':stats,
            'conditionalMagnitudeUnderSharedIsotropicScale':{k:v*source_scale for k,v in stats.items()} if stats else None,
            'meaning':'Disagreement between two independently simplified source meshes at the same XZ; not measured native terrain error. No source designated ground truth.'})
    write_json(out/'v3-region-impact.json',{'schema':1,'meshEvidence':mesh_rows,'regions':regions,'sourceOverlapDisagreements':seams,
        'conditionalSharedMetersPerSourceUnit':source_scale,'conditionalSharedScaleStatus':shared['scale'].get('status','ASSUMED-SCALE'),
        'pixelResidualToSharedWorldDistanceFactor':scale,
        'consumerScaleSource':relative(shared_path),'consumerScaleSourceSha256':digest(shared_path),
        'v3HeightPrecisionConclusion':'Not established. V3 is a classified, traceable HLOD reference with complete declared ROI coverage, not a high-precision original terrain or measured heightfield.',
        'unitFixDoesNotResolveGeometry':'Changing a reciprocal scale to forward scale is about 0.9 percent and cannot resolve cross-block observed 10.5 to 65.5 source-unit median height disagreements.',
        'currentEditorStateInspected':False,'terrainOrEntitiesModified':False})
    write_json(out/'coordinate-source-evidence.json',source_derivation([24206,8918]))
    packages=[cal/'PACKAGE.json',native/'PACKAGE.json',v3/'PACKAGE.json']
    files=[out/'v3-region-impact.json',out/'coordinate-source-evidence.json']
    write_json(out/'DELIVERY.json',{'schema':1,'status':'calibration source module implemented; five regional precise registrations remain unestablished',
        'recommendedExistingGeometryEntry':relative(v3/'consumer-index.json'),
        'existingGeometryUseRestriction':'Use as coarse classified HLOD reference. No claim of high-precision terrain is supported; preserve source grades and explicit uncertainty.',
        'cityReferenceRemainsUseful':True,'adoptedTransforms':[],'ownerBlindRebuildRequested':False,
        'calibrationEntry':relative(cal/'regional-registration.json'),'nativeCoordinateAudit':relative(native/'registration-decision.json'),
        'correctedExactOfficialCodeEvidence':relative(out/'coordinate-source-evidence.json'),
        'regionImpact':relative(out/'v3-region-impact.json'),
        'packages':{relative(p):digest(p) for p in packages},'files':{relative(p):digest(p) for p in files},
        'requiredNextSourceEvidence':['per-block original exported parent/local transforms or a source scene with preserved hierarchy',
            'higher-detail actual terrain geometry with documented placement and vertical datum',
            'independently identifiable roads/landmarks or banks with precise mesh correspondences'],
        'sourceGameVersionUnknown':True,'gameWrites':False,'desktopAccess':False,'offlineBatchReceiptStoredSeparately':True})
    print(relative(out/'DELIVERY.json'),digest(out/'DELIVERY.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',default=str(ROOT/'delivery-regional-calibration-v4'))
    build(p.parse_args())
