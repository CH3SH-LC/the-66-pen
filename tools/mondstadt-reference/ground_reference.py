"""Disambiguated ground reference and official-pixel consumer export.

Reads only our extracted meshes and a SHA-bound component selection. Objects,
water sheets and terrain are separate outputs. No inferred building or roof is
silently adopted as bare earth; ambiguous landform overlays remain flagged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from geometry import Mesh, sample_surface
from reference_cli import PROJECT, DEFAULT_LOCK, digest, draw_geometry, join_meshes, project_path, read_lock, write_json


ROOT=PROJECT/'data/mondstadt/reference3d'


def subset(mesh,face_ids,label):
    ids=np.asarray(sorted(set(face_ids)),dtype=np.int64)
    if not len(ids):return None
    if ids.min()<0 or ids.max()>=len(mesh.faces):raise ValueError('Selection face id out of bounds')
    return Mesh(mesh.vertices,mesh.faces[ids],[label],np.zeros(len(ids),dtype=np.int32))


def named_grid(grid,spacing):
    return {'arrayOrder':'[zIndex,xIndex]',
            'xmin':float(grid['x'][0]),'xmax':float(grid['x'][-1]),
            'zmin':float(grid['z'][0]),'zmax':float(grid['z'][-1]),
            'xSpan':float(grid['x'][-1]-grid['x'][0]),'zSpan':float(grid['z'][-1]-grid['z'][0]),
            'origin':{'x':float(grid['x'][0]),'z':float(grid['z'][0])},
            'step':{'x':spacing,'z':spacing},'shape':{'xCount':len(grid['x']),'zCount':len(grid['z'])},
            'lastSample':{'x':float(grid['x'][-1]),'z':float(grid['z'][-1])},
            'coordinateFormula':{'x':'origin.x + xIndex * step.x','z':'origin.z + zIndex * step.z'},
            'exampleIndex':{'zIndex':1,'xIndex':2,'x':float(grid['x'][0]+2*spacing),'z':float(grid['z'][0]+spacing)}}


def build(args):
    extracted=project_path(args.extracted);out=project_path(args.out);out.mkdir(parents=True,exist_ok=True)
    index=json.loads((extracted/'index.json').read_text(encoding='utf-8'))
    selection=json.loads(project_path(args.selection).read_text(encoding='utf-8'))
    registration=json.loads(project_path(args.registration).read_text(encoding='utf-8'))
    lock=read_lock(DEFAULT_LOCK);locked={r['id']:r for r in lock['files']}
    if index['frame']!='viewer' or registration['sourceFrame']!='viewer':raise ValueError('Frame mismatch')
    if not registration.get('thresholdSatisfied'):raise ValueError('Registration residual exceeds declared threshold')
    categories={k:[] for k in ['base-terrain','geological-overlay','city-paved','water-candidate','excluded-static']}
    coverage=[]
    for record in index['meshSources']:
        mid=record['id'];rule=selection['meshes'][mid]
        if rule['sourceSha256']!=record['sourceSha256'] or rule['sourceSha256']!=locked[mid]['sha256']:
            raise ValueError(f'Component selection is stale: {mid}')
        archive=np.load(extracted/record['geometryNpz'],allow_pickle=False)
        mesh=Mesh(archive['vertices'],archive['faces'],list(archive['group_names']),archive['face_groups'])
        component_path=extracted/('city-components.json' if mid=='mondstadt-city-lod0' else mid+'-components.json')
        document=json.loads(component_path.read_text(encoding='utf-8'));components={r['candidateId']:r for r in document['candidates']}
        topology=json.dumps([[cid,components[cid]['faceIds']] for cid in sorted(components)],separators=(',',':')).encode()
        if rule['componentTopologySha256']!=hashlib.sha256(topology).hexdigest():raise ValueError(f'Changed topology selection: {mid}')
        used=set()
        excluded_steep=[]
        for category,ids in rule['selection'].items():
            if category not in categories or category=='excluded-static':raise ValueError('Invalid selection category')
            if used.intersection(ids):raise ValueError('Component category collision')
            used.update(ids)
            faces=[fi for cid in ids for fi in components[cid]['faceIds']]
            policy=rule.get('trianglePolicy',{}).get(category,{})
            if 'maxSlopeDegrees' in policy:
                triangles=mesh.vertices[mesh.faces[faces]]
                normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
                length=np.linalg.norm(normals,axis=1)
                slope=np.degrees(np.arccos(np.clip(np.abs(normals[:,1])/np.maximum(length,1e-20),0,1)))
                keep=(length>1e-12)&(slope<=policy['maxSlopeDegrees'])
                excluded_steep.extend(np.asarray(faces)[~keep].tolist())
                faces=np.asarray(faces)[keep].tolist()
            piece=subset(mesh,faces,mid+':'+category)
            if piece is not None:categories[category].append((locked[mid],piece))
        excluded=[fi for cid,c in components.items() if cid not in used for fi in c['faceIds']]+excluded_steep
        piece=subset(mesh,excluded,mid+':excluded-static')
        if piece is not None:categories['excluded-static'].append((locked[mid],piece))
        coverage.append({'id':mid,'selectedComponents':rule['selection'],'excludedComponents':len(components)-len(used),
                         'method':rule['method'],'trianglePolicy':rule.get('trianglePolicy',{}),
                         'excludedSteepFaceCount':len(excluded_steep)})
    city=next(r for r in index['meshSources'] if r['role']=='city-geometry')
    lo,hi=city['aabbMin'],city['aabbMax']
    bounds=args.bounds or [lo[0]-500,hi[0]+500,lo[2]-600,hi[2]+400]
    # Count all grid sites, including holes: no silently expanding a native limit
    # by chunking the reference or hiding missing/duplicate cells.
    nx=int(np.floor(bounds[1]/args.spacing)-np.ceil(bounds[0]/args.spacing)+1)
    nz=int(np.floor(bounds[3]/args.spacing)-np.ceil(bounds[2]/args.spacing)+1)
    if args.native_cell_budget is not None and nx*nz>args.native_cell_budget:
        raise ValueError(f'ROI grid {nx*nz} exceeds proposed-cell budget {args.native_cell_budget}; crop actual scope, do not split to bypass native capacity')
    grids={};meshes={};spans={}
    for category,rows in categories.items():
        if not rows:raise ValueError('Empty semantic layer: '+category)
        mesh,source_spans=join_meshes(rows);meshes[category]=mesh;spans[category]=source_spans
        grids[category]=sample_surface(mesh,bounds,args.spacing)
        np.savez_compressed(out/(category+'.npz'),**grids[category])
    base=grids['base-terrain'];ground=base['top'].copy()
    source_class=np.where(np.isfinite(ground),1,0).astype(np.uint8)
    # Preserve selected foundation/landform data separately and flag what wins.
    for category,code in [('geological-overlay',2),('city-paved',3)]:
        candidate=grids[category]['top'];choose=np.isfinite(candidate)&(~np.isfinite(ground)|(candidate>ground))
        ground[choose]=candidate[choose];source_class[choose]=code
    water=grids['water-candidate']['top'];excluded=grids['excluded-static']['top']
    valid=np.isfinite(ground)
    underwater=valid&np.isfinite(water)&(water-ground>0.25)
    static_above=valid&np.isfinite(excluded)&(excluded-ground>0.5)
    primary_ambiguous=np.isfinite(base['top'])&np.isfinite(base['bottom'])&((base['top']-base['bottom'])>0.25)
    overlay_above=np.isfinite(grids['geological-overlay']['top'])&np.isfinite(base['top'])&(grids['geological-overlay']['top']-base['top']>0.25)
    # This is a semantic confidence flag, not a pass/fail or imported map mask.
    grade=np.where(valid,1,0).astype(np.uint8)
    grade[primary_ambiguous|overlay_above]=2
    grade[source_class==3]=3
    grade[underwater]=4
    mesh_codes={r['id']:i+1 for i,r in enumerate(index['meshSources'])}
    source_mesh_code=np.zeros(source_class.shape,dtype=np.uint8)
    for category,code in [('base-terrain',1),('geological-overlay',2),('city-paved',3)]:
        face=grids[category]['top_face']
        for span in spans[category]:
            chosen=(source_class==code)&(face>=span['firstFace'])&(face<span['firstFace']+span['faceCount'])
            source_mesh_code[chosen]=mesh_codes[span['id']]
    alignment_grade=np.where(valid,3,0).astype(np.uint8)
    alignment_grade[source_mesh_code==mesh_codes['mondstadt-city-lod0']]=1
    alignment_grade[source_mesh_code==mesh_codes['hlod-2_-1']]=2
    xx,zz=np.meshgrid(base['x'],base['z']);source_xz=np.stack([xx,zz],axis=-1)
    pixel=source_xz@np.asarray(registration['matrix2x2'])+np.asarray(registration['offsetPixels'])
    np.savez_compressed(out/'ground-height.npz',x=base['x'],z=base['z'],ground_y=ground,
        source_class=source_class,grade=grade,water_y=water,underwater_mask=underwater,
        excluded_static_above_mask=static_above,primary_multilayer_mask=primary_ambiguous,
        geological_overlay_mask=overlay_above,official_pixel_x=pixel[:,:,0],official_pixel_y=pixel[:,:,1],
        source_mesh_code=source_mesh_code,alignment_grade=alignment_grade)
    # Compact JSON rows let owners consume without NumPy; no NaN or implicit order.
    samples=[]
    for iz,ix in zip(*np.nonzero(valid)):
        samples.append([int(iz),int(ix),round(float(xx[iz,ix]),5),round(float(zz[iz,ix]),5),
                        round(float(ground[iz,ix]),5),int(source_class[iz,ix]),int(grade[iz,ix]),
                        bool(underwater[iz,ix]),bool(static_above[iz,ix])])
    schema=named_grid(base,args.spacing)
    write_json(out/'ground-height.json',{'schema':1,'grid':schema,
        'columns':['zIndex','xIndex','sourceX','sourceZ','groundCandidateY','sourceClass','grade','underwaterCandidate','excludedStaticAbove'],
        'samples':samples})
    candidates=json.loads((extracted/'city-components.json').read_text(encoding='utf-8'))['candidates']
    city_rows=[]
    for c in candidates:
        footprint=np.asarray(c['convexFootprintXZ'],dtype=float)
        transformed=(footprint@np.asarray(registration['matrix2x2'])+np.asarray(registration['offsetPixels'])).tolist() if len(footprint) else []
        center=np.asarray(c['centerXZ'])@np.asarray(registration['matrix2x2'])+np.asarray(registration['offsetPixels'])
        city_rows.append({k:v for k,v in c.items() if k!='faceIds'}|{'officialPixelFootprint':transformed,'officialPixelCenter':center.tolist(),
                          'groundSelection':c['candidateId'] in selection['meshes']['mondstadt-city-lod0']['selection']['city-paved']})
    write_json(out/'city-layout-reference.json',{'schema':1,'sourceFrame':'viewer','sourceGeometrySha256':city['sourceSha256'],
        'registrationSha256':digest(project_path(args.registration)),'nativePlacementScaleVerified':False,
        'meaning':'source geometry layout; connected candidates are not confirmed standalone buildings','candidates':city_rows})
    np.savez_compressed(out/'selected-ground-geometry.npz',**{
        name.replace('-','_')+'_vertices':meshes[name].vertices for name in ('base-terrain','geological-overlay','city-paved')},**{
        name.replace('-','_')+'_faces':meshes[name].faces for name in ('base-terrain','geological-overlay','city-paved')})
    display,_=join_meshes([(locked['mondstadt-city-lod0'],meshes[k]) for k in ('base-terrain','geological-overlay','city-paved')])
    draw_geometry(display,out/'ground-only-overview.png',title='Selected terrain + geological candidates + city paved ground; objects/water excluded')
    stats={'validGroundSamples':int(valid.sum()),'missingGroundSamples':int((~valid).sum()),
           'underwaterCandidates':int(underwater.sum()),'excludedStaticAboveSamples':int(static_above.sum()),
           'primaryMultilayerSamples':int(primary_ambiguous.sum()),'geologicalOverlaySamples':int(overlay_above.sum()),
           'cityPavedWinningSamples':int((source_class==3).sum())}
    report={'schema':1,'grid':schema,'requestedBounds':dict(zip(['xmin','xmax','zmin','zmax'],bounds)),
        'frame':'viewer','sourceClass':{'0':'missing','1':'large connected base terrain','2':'large geological overlay candidate','3':'selected city pavement/terrace'},
        'grade':{'0':'missing','1':'base geometry candidate','2':'multilayer or geological overlay; inspect layers','3':'city paving/terrace candidate','4':'below source water candidate'},
        'stats':stats,'componentSelections':coverage,'sourceSpans':spans,
        'semantics':'ground candidate selected from terrain/landform and city ground components; roofs/static/water kept out of ground heights',
        'pixelRegistration':{'rmse':registration['rmsePixels'],'maxResidual':registration['maxResidualPixels'],
            'leaveOneOutMax':max(x for x in registration['leaveOneOutPixels'] if x is not None)},
        'tilePlacementCaveat':'City has eight measured 2D controls. Regional blocks retain upstream AABB recenter placement and have NOT each been separately registered. Do not treat regional absolute XY as surveyed.',
        'sourceMeshCodes':mesh_codes,'alignmentGrade':{'0':'missing','1':'city eight visual controls fitted',
            '2':'block2_-1 three distinct coastline features within 4.1px under city transform; other coastline features ambiguous; no per-block native survey',
            '3':'upstream placement only; independently calibrate before claiming precise layout'},
        'scale':'5 source units by default; exact source-unit-to-editor-metre scale is not verified',
        'syntheticOceanIncluded':False,'unknowns':['source game version','regional per-block geometric registration','native asset mapping','game collision and walkability'],
        'allProductDevelopmentComplete':False,'actualGameAcceptance':False,
        'selectionSha256':digest(project_path(args.selection)),'sourceLockSha256':digest(DEFAULT_LOCK)}
    report['nativeCapacity']={'referenceGridSites':nx*nz,'proposedCellBudget':args.native_cell_budget,
        'withinRequestedBudget':None if args.native_cell_budget is None else nx*nz<=args.native_cell_budget,
        'notAnImportPlan':True,'freshExistingCellCountIncluded':False,
        'sourceGridIsNotNativeGrid':True,
        'instruction':'Choose actual city/outside ROI, transform/resample at native 5m origin, and account for fresh existing cells before any terrain write. Do not batch around the official limit.'}
    write_json(out/'consumer-index.json',report);print(json.dumps({'out':str(out),'stats':stats,'grid':schema}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extracted',default=str(ROOT/'extracted-viewer'))
    parser.add_argument('--selection',default=str(ROOT/'surface-selection.json'))
    parser.add_argument('--registration',default=str(ROOT/'registration.json'))
    parser.add_argument('--out',default=str(ROOT/'consumer'))
    parser.add_argument('--bounds',nargs=4,type=float);parser.add_argument('--spacing',type=float,default=5)
    parser.add_argument('--native-cell-budget',type=int,default=None)
    build(parser.parse_args())
