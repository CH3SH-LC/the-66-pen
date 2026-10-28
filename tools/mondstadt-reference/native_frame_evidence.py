"""Audit a sourced native-coordinate map model without adopting HLOD frames.

The production coordinate converter is independent evidence for native XYZ to
official pixels. It does NOT prove where each OBJ was baked. This module keeps
that missing link explicit and never rewrites a registration or source package.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np

from reference_cli import PROJECT, digest, project_path, write_json
from regional_registration import ROOT, SOURCE, PREPARE, EXTRACTED, OFFICIAL, read, relative, mosaic, overlap_report

MATRIX = np.array([[0., 1.], [-1., 0.]])
# Only an explicit candidate for baked XYZ, not an established per-block survey.
COMMON_X = {'hlod-1_-1': 1024., 'hlod-1_-2': 1024., 'hlod-2_-1': 1024.,
            'hlod-2_-2': 1024., 'hlod-1_0': 1024., 'hlod-2_0': -1024.}


def native_to_pixel(xyz, official_origin=(24206., 8918.)):
    xyz = np.asarray(xyz, float)
    if xyz.shape[-1] != 3 or not np.isfinite(xyz).all():
        raise ValueError('Finite native XYZ required')
    # GiWorldPosition.X=Position[2]; .Y=Position[0]; GameToMysWeb negates
    # offsets (-749.75,2322). Official unproject subtracts image origin.
    return np.asarray(official_origin) + np.stack((-749.75-xyz[..., 2], 2322.-xyz[..., 0]), axis=-1)


def common_to_pixel(xz, official_origin=(24206., 8918.)):
    xz = np.asarray(xz, float)
    if xz.shape[-1] != 2 or not np.isfinite(xz).all():
        raise ValueError('Finite common-frame XZ required')
    xyz = np.stack((1024.-xz[..., 0], np.zeros(xz.shape[:-1]), xz[..., 1]), axis=-1)
    return native_to_pixel(xyz, official_origin)


def frame_shift(record):
    if record['id'] not in COMMON_X:
        return np.zeros(2)  # The city has its separate sourced manifest frame.
    raw_to_viewer = np.asarray(record['rawToFrame'], float)
    if not np.allclose(raw_to_viewer[:3, :3], np.eye(3)):
        raise ValueError('Cannot infer baked basis through a nontranslation')
    return np.array([COMMON_X[record['id']], 0.])-raw_to_viewer[[0, 2], 3]


def seam_evidence(index):
    """Mutual nearest XYZ vertices are reported, not optimized or promoted.

    XYZ duplicates in an overlap may establish relative geometry; fewer than
    three noncollinear points cannot establish a rigid frame. Even a strong
    relative seam does not establish absolute placement on the official map.
    """
    from scipy.spatial import cKDTree
    meshes = {}
    for row in index['meshSources']:
        if row['id'] not in COMMON_X:
            continue
        a = np.load(EXTRACTED/row['geometryNpz'], allow_pickle=False)
        meshes[row['id']] = (np.unique(a['vertices'], axis=0), frame_shift(row))
    rows = []
    for ia, a in enumerate(sorted(meshes)):
        for b in sorted(meshes)[ia+1:]:
            blocks = [tuple(map(int, key.removeprefix('hlod-').split('_'))) for key in (a, b)]
            if sum(abs(x-y) for x,y in zip(*blocks)) != 1:
                continue
            states = {}
            for state in ('viewer', 'raw-baked-candidate'):
                va, sa = meshes[a]; vb, sb = meshes[b]
                va, vb = va.copy(), vb.copy()
                if state != 'viewer':
                    va[:, [0, 2]] += sa; vb[:, [0, 2]] += sb
                dist, near = cKDTree(vb).query(va)
                reverse = cKDTree(va).query(vb)[1]
                keep = np.flatnonzero((dist <= .02) & (reverse[near] == np.arange(len(va))))
                points = va[keep]
                rank = int(np.linalg.matrix_rank(points-points.mean(0), tol=.02)) if len(points) else 0
                states[state] = {'mutualPairsWithin002SourceUnits': len(keep),
                    'sourceXYZRank': rank, 'medianDistance': float(np.median(dist[keep])) if len(keep) else None,
                    'maxDistance': float(dist[keep].max()) if len(keep) else None,
                    'pairs': [{'aXYZ': va[i].tolist(), 'bXYZ': vb[near[i]].tolist(), 'distance': float(dist[i])} for i in keep],
                    'absoluteMapRegistrationEstablished': False}
            rows.append({'meshes': [a, b], **states})
    return {'schema': 1, 'pairs': rows, 'toleranceSourceUnits': .02,
            'warning': 'Shared vertices are relative geometry evidence only. Height/topology gaps and exact matches are retained; no seam deformation or infill.'}


def source_derivation(origin):
    sources = [SOURCE/'source'/('bgi-'+n) for n in (
        'GameWebMapCoordinateConverter.cs', 'GiWorldPosition.cs', 'MaskMapPointService.cs', 'SceneBaseMap.cs', 'TeyvatMap.cs', 'GiWorldScene.cs')]
    rows = []
    for file in sources:
        lines = file.read_text(encoding='utf-8-sig').splitlines()
        needles = ('MysWebOffset', 'GameToMysWeb', 'MysWebToGame', 'Position[2]', 'Position[0]',
                   'ConvertGenshinMapCoordinatesToImageCoordinates', '_mapImageBlockWidthScale =')
        evidence = [{'line': i+1, 'text': line.strip()} for i, line in enumerate(lines) if any(n in line for n in needles)]
        rows.append({'path': relative(file), 'sha256': digest(file), 'bytes': file.stat().st_size, 'evidence': evidence})
    info = read(OFFICIAL/'map-info.json')
    details = []
    def walk(obj):
        if isinstance(obj, dict):
            if obj.get('origin') == list(origin) and 'map_version' in obj: details.append(obj)
            for value in obj.values(): walk(value)
        elif isinstance(obj, list):
            for value in obj: walk(value)
    walk(info)
    if len(details) != 1:
        raise ValueError('Official source must identify the unique locked-map origin')
    snippets = []
    for file in OFFICIAL.glob('*.js'):
        text = file.read_text(encoding='utf-8')
        for needle in ('initTileLayer:function', 'unproject:function(t){return new r.LatLng(t.y-a,t.x-n)'):
            start = text.find(needle)
            if start >= 0:
                # Exact implementation rather than an earlier call site.
                snippets.append({'path': relative(file), 'sha256': digest(file), 'characterOffset': start,
                                 'needle': needle, 'snippet': text[max(0,start-250):start+1100]})
    return {'schema': 1, 'bgiCommit': 'c9db8b8291fe4ac25a600aee1582298005919eb2',
        'sources': rows, 'officialInfo': {'path': relative(OFFICIAL/'map-info.json'),
        'sha256': digest(OFFICIAL/'map-info.json'), 'detail': details[0]}, 'officialCodeContexts': snippets,
        'axisMapping': 'GiWorldPosition native Position=[longitudinal,height,lateral]; 2D game X=Position[2], Y=Position[0]',
        'formula': 'pixelX=originX-749.75-nativeZ; pixelY=originY+2322-nativeX',
        'formulaForCommonSourceCandidate': 'nativeX=1024-sourceX; nativeZ=sourceZ',
        'commonSourceRowVectorMatrix2x2': MATRIX.tolist(),
        'commonSourceOffsetPixels': common_to_pixel([0.,0.],origin).tolist(),
        'evidenceBoundary': 'Production coordinate path is sourced. Original game version and baked local OBJ transforms remain separate unresolved dependencies. Not a native/editor metre calibration.'}


def build(args):
    out = project_path(args.out)
    if not out.is_relative_to(ROOT) or out.exists():
        raise ValueError('Create only a new immutable owned reference directory')
    out.mkdir(parents=True)
    index = read(EXTRACTED/'index.json'); by_id = {r['id']: r for r in index['meshSources']}
    origin = [24206,8918]
    derivation = source_derivation(origin)
    write_json(out/'coordinate-derivation.json', derivation)
    old = read(ROOT/'registration.json'); matrix = np.asarray(old['matrix2x2']); offset = np.asarray(old['offsetPixels'])
    shifts = {r['id']: frame_shift(r) for r in index['meshSources'] if r['id'] in COMMON_X}
    city = []
    for row in read(ROOT/'anchors.json')['anchors']:
        source, target = np.asarray(row['sourceXZ']), np.asarray(row['officialGlobalPixel'])
        pixel = common_to_pixel(source,origin)
        city.append({'id': row['id'], 'sourceXZ': source.tolist(), 'officialGlobalPixel': target.tolist(),
                     'analyticPixel': pixel.tolist(), 'analyticResidualPixels': float(np.linalg.norm(pixel-target)),
                     'previousFitResidualPixels': float(np.linalg.norm(source@matrix+offset-target)),
                     'independentOfAnalyticFormula': True})
    features_path = PREPARE/'feature-panels/features.json'
    features = {r['mesh']: {v['featureId']:v for v in r['features']} for r in read(features_path)['rows']}
    observations = read(PREPARE/'control-observations.json')
    regional = []
    for row in observations['regions']:
        mid = row['mesh']; controls = []
        for c in row['controls']:
            feature = features[mid][c['featureId']]
            source = np.array(feature['sourceXZ']); target = np.array(c['officialGlobalPixel'])
            pixel = common_to_pixel(source+shifts[mid],origin)
            controls.append(dict(c, sourceXZ=source.tolist(), analyticCandidatePixel=pixel.tolist(),
                analyticCandidateResidualPixels=float(np.linalg.norm(pixel-target))))
        regional.append({'mesh': mid, 'viewerToCommonCandidateShiftXZ': shifts[mid].tolist(),
            'rawToCommonCandidateTranslationXZ': [COMMON_X[mid],0.],
            'rawXBasisHypothesis': 'rawX-2048 equals negative native longitudinal X' if mid=='hlod-2_0' else 'rawX equals negative native longitudinal X',
            'grade': 3, 'accepted': False, 'controls': controls,
            'reason': 'OBJ baked coordinate equivalence lacks independent per-block transform/control evidence; coarse coastline residuals do not justify high precision.'})
    # Report original map shoreline/city controls, not fitted by this model.
    accepted_capes = []
    for c in read(ROOT/'shoreline-review/shoreline-controls.json')['controls']:
        pixel = common_to_pixel(np.array(c['sourceXZ'])+shifts[c['mesh']],origin)
        accepted_capes.append(dict(c,analyticCandidatePixel=pixel.tolist(),analyticCandidateResidualPixels=float(np.linalg.norm(pixel-c['officialGlobalPixel']))))
    write_json(out/'feature-comparison.json', {'schema':1,'city':city,'regional':regional,'block2minus1':accepted_capes,
        'cityAnalyticRmsePixels':float(np.sqrt(np.mean([r['analyticResidualPixels']**2 for r in city]))),
        'noControlWasFittedToAnalyticFormula':True,'acceptedChanges':[]})
    write_json(out/'seam-evidence.json', seam_evidence(index))
    # Comparison uses unchanged city map matrix on both states to isolate baked
    # source translation, not conflate it with a different global pixel model.
    overlap = overlap_report(index,read(ROOT/'surface-selection.json'),matrix,offset,{k:v@matrix for k,v in shifts.items()})
    overlap['meaning'] = 'Isolate viewer versus raw-baked candidate source shift; frozen city map matrix used for both; source Y retained.'
    write_json(out/'overlap-evidence.json',overlap)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    image, extent = mosaic(PREPARE)
    contours=read(SOURCE/'regional-v4-visible/contours.json')
    for row in contours['meshes']:
        mid=row['mesh'];fig,axes=plt.subplots(1,2,figsize=(18,10),constrained_layout=True)
        points=[]
        for layer in row['waterContours']:
            if layer.get('segmentCount'):points.extend(np.array(layer['segmentsXZ']).reshape(-1,2))
        if not points:plt.close(fig);continue
        oldpix=np.array(points)@matrix+offset;newpix=common_to_pixel(np.array(points)+shifts[mid],origin)
        low=np.minimum(oldpix.min(0),newpix.min(0))-20;high=np.maximum(oldpix.max(0),newpix.max(0))+20
        for ax in axes:ax.imshow(image,extent=extent)
        for layer in row['waterContours']:
            if not layer.get('segmentCount'):continue
            s=np.array(layer['segmentsXZ'])
            axes[0].add_collection(LineCollection(s@matrix+offset,colors='red',linewidths=.7))
            axes[1].add_collection(LineCollection(common_to_pixel(s+shifts[mid],origin),colors='magenta',linewidths=.7))
        for ax in axes:
            ax.set_xlim(low[0],high[0]);ax.set_ylim(high[1],low[1]);ax.set_aspect('equal');ax.grid(alpha=.2)
        axes[0].set_title(mid+' unchanged viewer registration')
        axes[1].set_title('Sourced coordinate formula + UNVERIFIED raw-baked basis')
        fig.savefig(out/(mid+'-analytic-candidate.png'),dpi=150);plt.close(fig)
    # Native waypoint positions provide independent coordinate evidence only;
    # no corresponding HLOD object was positively identified in this module.
    tps=[point for scene in read(SOURCE/'source/bgi-tp.json')['data'] if scene['sceneId']==3 for point in scene['points']];selected=[]
    for t in tps:
        if str(t['id']) not in {'5','10','29','33','35','36','37','38','122'}:continue
        selected.append({'id':t['id'],'name':t['name'],'nativeXYZ':t['position'],
            'officialGlobalPixel':native_to_pixel(t['position'],origin).tolist(),
            'matchingHlodLandmarkEstablished':False,'usedAsFitControl':False})
    write_json(out/'native-point-cross-reference.json',{'schema':1,'source':relative(SOURCE/'source/bgi-tp.json'),
        'sourceSha256':digest(SOURCE/'source/bgi-tp.json'),'points':selected,
        'unavailableAdditionalSource':{'manifestName':'Area_StormDragon_City_Constant_HLOD','manifestPosition':[0,0,0],
            'url':'https://cdn.flatypus.me/genshin/game_data/hlod_all/Area_StormDragon_City_Constant_HLOD_Lod0.obj',
            'fetchOutcome':'HTTP 403 Forbidden, 2026-10-17; no geometry downloaded',
            'meaning':'Cannot assert absence, positioning or fidelity from this unsuccessful public fetch.'}})
    write_json(out/'registration-decision.json',{'schema':1,'acceptedChanges':[],'adoptedGradeChanges':[],
        'oldRegistrationSha256':digest(ROOT/'registration.json'),'oldV3PackageSha256':digest(ROOT/'consumer-all-regions-v3/PACKAGE.json'),
        'regionalRows':[{'mesh':r['mesh'],'grade':3,'unappliedSourceShiftXZ':r['viewerToCommonCandidateShiftXZ']} for r in regional],
        'recommendation':'Retain v3. Analytic coordinate path is useful new source evidence, but no independently proven per-block baked-frame registration is available.',
        'noCurrentOwnerRebuildRequested':True,'nativeScaleVerified':False,'gameWrites':False,'desktopAccess':False})
    inputs=[ROOT/'anchors.json',ROOT/'registration.json',ROOT/'surface-selection.json',EXTRACTED/'index.json',features_path,
        PREPARE/'control-observations.json',PREPARE/'official-tiles-lock.json',SOURCE/'regional-v4-visible/contours.json',
        SOURCE/'source/bgi-tp.json',SOURCE/'source/all_hlod_manifest.json',ROOT/'consumer-all-regions-v3/PACKAGE.json']
    write_json(out/'PACKAGE.json',{'schema':1,'entry':relative(out/'registration-decision.json'),
        'inputs':{relative(p):digest(p) for p in inputs},
        'files':{relative(p):{'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file()},
        'immutable':True,'sourceModuleDevelopmentComplete':True,'offlineBatchNotYetRunAtFreeze':True})
    print(json.dumps({'out':relative(out),'cityAnalyticRmsePixels':float(np.sqrt(np.mean([r['analyticResidualPixels']**2 for r in city]))),
                      'adoptedChanges':[],'files':len(list(out.iterdir()))}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',default=str(ROOT/'native-frame-audit-v4'))
    build(p.parse_args())
