"""Freeze real native terrain and world meshes into an auditable source package.

Inputs are explicitly acquired source nodes and exact decoded dependencies.
This never creates an editor plan, changes an old package, or fills missing data.
"""
from __future__ import annotations
import argparse,collections,json,math,shutil
from pathlib import Path
import numpy as np
from native_ground_reference import GroundReference,interpolate,native_to_product_xz
from native_product_frame import build_mapping,transform_xyz
from native_terrain_binding import terrain_bindings
from reference_cli import project_path,digest,write_json
from regional_registration import ROOT,SOURCE,EXTRACTED,read,relative


def numbers(values):
    v=np.asarray(values,float)
    if not len(v):return {'count':0}
    return {'count':len(v),'min':float(v.min()),'max':float(v.max()),'median':float(np.median(v)),
            'p90':float(np.quantile(v,.9)),'p95':float(np.quantile(v,.95)),'p99':float(np.quantile(v,.99)),
            'rms':float(np.sqrt(np.mean(v*v)))}


def sealed_copy(src,out,name):
    dst=out/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    if digest(src)!=digest(dst):raise ValueError('Copy hash mismatch')
    return dst


def seam_report(tiles,arrays):
    rows=[];bands=collections.defaultdict(list)
    for a in tiles:
        for b in tiles:
            ba,bb=a['nativeBounds'],b['nativeBounds'];axis=None
            if ba['xmax']==bb['xmin'] and ba['zmin']==bb['zmin']:axis='X';va=arrays[a['id']][-1,:];vb=arrays[b['id']][0,:];fixed=ba['xmax'];variable=ba['zmin'];step=a['scaleXYZ'][2]
            elif ba['zmax']==bb['zmin'] and ba['xmin']==bb['xmin']:axis='Z';va=arrays[a['id']][:,-1];vb=arrays[b['id']][:,0];fixed=ba['zmax'];variable=ba['xmin'];step=a['scaleXYZ'][0]
            if axis is None:continue
            delta=(va.astype(float)-vb.astype(float))*a['scaleXYZ'][1]/a['heightIntegerDenominator'];bad=np.flatnonzero(np.abs(delta)>2*a['quantizationY']);segments=[]
            for inds in np.split(bad,np.where(np.diff(bad)>1)[0]+1):
                if not len(inds):continue
                lo=variable+step*(int(inds[0])-1);hi=variable+step*(int(inds[-1])+1)
                band={'xmin':fixed-step if axis=='X' else lo,'xmax':fixed+step if axis=='X' else hi,
                      'zmin':lo if axis=='X' else fixed-step,'zmax':hi if axis=='X' else fixed+step,
                      'reason':'adjacent native TerrainData boundary differs by more than two stored height units',
                      'sourceTiles':[a['id'],b['id']]}
                bands[a['id']].append(band);bands[b['id']].append(band);segments.append(band)
            rows.append({'tiles':[a['id'],b['id']],'axis':axis,'fixedNativeCoordinate':fixed,'samples':len(delta),
                         'exactRawIntegerMatches':int(np.count_nonzero(va==vb)),'withinTwoRawIntegerUnits':int(np.count_nonzero(np.abs(va.astype(float)-vb.astype(float))<=2)),
                         'distinctExactlyMatchingRawValues':int(len(np.unique(va[va==vb]))),
                         'absoluteNativeHeightDifference':numbers(np.abs(delta)),'excludedBands':segments,
                         'smoothedOrFilled':False,'meaning':'Shared boundary sequence corroborates relative placement; differing segments remain excluded, not averaged.'})
    return {'schema':1,'pairs':rows},bands


def orientation_evidence(tiles,arrays):
    result=[];old_index={r['id']:r for r in read(EXTRACTED/'index.json')['meshSources']}
    for tile in tiles:
        block=tile['id'];mid='hlod-'+block
        if block not in {'1_-1','1_-2'}:continue
        row=old_index[mid];path=EXTRACTED/row['geometryNpz'];npz=np.load(path,allow_pickle=False)
        component=44 if block=='1_-1' else 4;comps=read(EXTRACTED/(mid+'-components.json'))['candidates'];face_ids=next(c['faceIds'] for c in comps if c['candidateId']==component)
        vertices=npz['vertices'][np.unique(npz['faces'][face_ids])].copy();m=np.asarray(row['rawToFrame']);vertices=(vertices-m[:3,3])@np.linalg.inv(m[:3,:3]).T;vertices[:,0]*=-1
        b=tile['nativeBounds'];keep=(vertices[:,0]>=b['xmin'])&(vertices[:,0]<=b['xmax'])&(vertices[:,2]>=b['zmin'])&(vertices[:,2]<=b['zmax']);v=vertices[keep];comparisons={}
        for axis in ('X','Z'):
            h=interpolate(arrays[block],v[:,0]-b['xmin'],v[:,2]-b['zmin'],2,2,axis)*tile['scaleXYZ'][1]/tile['heightIntegerDenominator']
            comparisons['row'+axis]=numbers(np.abs(v[:,1]-h))
        result.append({'tileId':block,'oldComponent':component,'sourceGeometry':relative(path),'sourceGeometrySha256':digest(path),
                       'comparisons':comparisons,'adoptedStorageRowAxis':'X','notAnAbsoluteTerrainAccuracyMeasurement':True,
                       'note':'Independently decoded native HLOD matches this public baked geometry; HLOD simplification and source layers explain residuals. Do not use these residuals as a fit deformation.'})
    return result


def placement_decisions(tiles,seams,orientation,compatibility):
    """Promote only a corroborated connected edge chain to the native anchor.

    This still does not recover a scene parent. It makes the evidence supporting
    the explicitly proposed grid origin inspectable and fails closed on a tile
    which has no matching nonconstant boundary chain.
    """
    exact_native={r['mesh'].removeprefix('hlod-') for r in compatibility if r['allFaceIndicesAgreeIgnoringWinding'] and r['maxVertexCoordinateDifference'] is not None and r['maxVertexCoordinateDifference']<.001}
    seeds={r['tileId'] for r in orientation if r['tileId'] in exact_native and r['comparisons']['rowX']['count']>=128 and r['comparisons']['rowX']['median']*4<r['comparisons']['rowZ']['median']}
    edges=[]
    for row in seams['pairs']:
        if row['exactRawIntegerMatches']>=128 and row['distinctExactlyMatchingRawValues']>=32 and row['withinTwoRawIntegerUnits']/row['samples']>=.7:edges.append(row['tiles'])
    reached=set(seeds);paths={k:[k] for k in seeds}
    while True:
        previous=len(reached)
        for a,b in edges:
            if a in reached and b not in reached:reached.add(b);paths[b]=paths[a]+[b]
            if b in reached and a not in reached:reached.add(a);paths[a]=paths[b]+[a]
        if len(reached)==previous:break
    for tile in tiles:
        r=tile['registration'];r['corroboratingBoundaryChain']=paths.get(tile['id']);r['nativeHlodOrientationSeed']=tile['id'] in seeds
        if tile['id'] not in reached:r.update(status='unresolved-native-placement',grade=3)
        r['absoluteSceneParentResolved']=False
        r['coordinateErrorBoundNativeUnits']=None
        r['reasonErrorBoundUnknown']='No original runtime scene instantiation matrix or surveyed control network. Finite source quantization does not bound absolute registration accuracy.'
    return {'schema':1,'nativeHlodOrientationSeeds':sorted(seeds),'acceptedRelativeEdges':edges,'registeredTiles':sorted(reached),
        'rule':'At least128 exact raw boundary values and >=70% within two stored height units connects to an independently oriented native HLOD seed. Absolute ground anchor is reported separately.',
        'notARuntimeParentRecovery':True}


def copy_meshes(paths,out,mapping):
    placed=[];unresolved=[]
    for path in paths:
        index=read(path)
        for row in index['placedMeshes']:
            src=project_path(row['geometry'])
            if digest(src)!=row['geometrySha256']:raise ValueError('Native mesh changed')
            target=sealed_copy(src,out,'meshes/native-'+str(len(placed))+'.npz');a=np.load(src,allow_pickle=False);pv=transform_xyz(a['vertices'],mapping)
            product=out/'meshes'/('product-'+str(len(placed))+'.npz');np.savez_compressed(product,vertices=pv,triangles=a['triangles'],faceSubmesh=a['faceSubmesh'])
            tri=a['vertices'][a['triangles']];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);area2=np.linalg.norm(cross,axis=1);normal=cross/np.maximum(area2[:,None],1e-30)
            attributes=out/'meshes'/('face-attributes-'+str(len(placed))+'.npz');np.savez_compressed(attributes,nativeWindingNormals=normal,nativeFaceAreas=area2/2,degenerate=area2<1e-10)
            placed.append(dict(row,geometry=target.relative_to(out).as_posix(),geometrySha256=digest(target),
                productGeometry=product.relative_to(out).as_posix(),productGeometrySha256=digest(product),sourceAssembly=relative(path),sourceAssemblySha256=digest(path),
                faceAttributes=attributes.relative_to(out).as_posix(),faceAttributesSha256=digest(attributes),
                productBounds={c+'min':float(pv[:,i].min()) for i,c in enumerate('xyz')}|{c+'max':float(pv[:,i].max()) for i,c in enumerate('xyz')},
                productTransformId=mapping['id'],editorOffsetApplied=False))
        unresolved.extend(index['unresolved'])
    return {'schema':1,'placedMeshes':placed,'unresolved':unresolved,'groundPolicy':'All meshes remain geometry references. Roofs, walls, water and bridges are not automatically classified as base terrain.'}


def old_mesh_compatibility(meshes,out):
    """Transfer semantic face IDs only after all vertex/triangle indices agree."""
    old_index=read(EXTRACTED/'index.json');reports=[];selections=read(ROOT/'surface-selection.json')
    for row in meshes['placedMeshes']:
        old_id='mondstadt-city-lod0' if row['name']=='Area_Mengde_City_Constant_HLOD_Lod0' else next(('hlod-'+b for b in ('1_-1','1_-2') if row['name']=='BigWorld_'+b+'_Constant_HLOD_Lod0'),None)
        if old_id is None:continue
        old=next(r for r in old_index['meshSources'] if r['id']==old_id);a=np.load(EXTRACTED/old['geometryNpz'],allow_pickle=False);native=np.load(out/row['geometry'],allow_pickle=False)
        m=np.asarray(old['rawToFrame']);v=(a['vertices']-m[:3,3])@np.linalg.inv(m[:3,:3]).T;v[:,0]*=-1
        if old_id=='mondstadt-city-lod0':v+=np.array([2275,263,-783])
        compatible=v.shape==native['vertices'].shape and a['faces'].shape==native['triangles'].shape
        residual=float(np.max(np.abs(v-native['vertices']))) if compatible else None
        triangles=bool(compatible and np.array_equal(np.sort(a['faces'],axis=1),np.sort(native['triangles'],axis=1)))
        record={'mesh':old_id,'nativeGeometry':row['geometry'],'nativeGeometrySha256':row['geometrySha256'],'publicGeometry':relative(EXTRACTED/old['geometryNpz']),
                'publicGeometrySha256':digest(EXTRACTED/old['geometryNpz']),'maxVertexCoordinateDifference':residual,'allFaceIndicesAgreeIgnoringWinding':triangles,'semanticTransferAccepted':False}
        if compatible and residual<.001 and triangles:
            compfile=EXTRACTED/('city-components.json' if old_id=='mondstadt-city-lod0' else old_id+'-components.json');components=read(compfile)['candidates'];semantic=selections['meshes'][old_id];chosen=[]
            for kind,ids in semantic['selection'].items():
                faceids=np.array([f for c in components if c['candidateId'] in ids for f in c['faceIds']],int)
                tri=native['vertices'][native['triangles'][faceids]];normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);length=np.linalg.norm(normals,axis=1);slope=np.degrees(np.arccos(np.clip(np.abs(normals[:,1])/np.maximum(length,1e-30),0,1)))
                maxslope=semantic.get('trianglePolicy',{}).get(kind,{}).get('maxSlopeDegrees',90);keep=(length>1e-10)&(slope<=maxslope)
                chosen.append({'classification':kind,'components':ids,'faceIds':faceids[keep].tolist(),'excludedSteepOrDegenerateFaceIds':faceids[~keep].tolist(),'maxSlopeDegrees':maxslope})
            semantic_path=out/'meshes'/(old_id+'-semantic-faces.json');write_json(semantic_path,{'schema':1,'nativeGeometry':row['geometry'],'nativeGeometrySha256':row['geometrySha256'],
                'classifications':chosen,'priorReviewSource':relative(ROOT/'surface-selection.json'),'priorReviewSha256':digest(ROOT/'surface-selection.json'),
                'semanticsVerifiedInGame':False,'classificationMethod':'Prior explicit source-face review transferred only after exact index/coordinate correspondence; not inferred from flatness alone.'})
            record.update(semanticTransferAccepted=True,semanticFaces=semantic_path.relative_to(out).as_posix(),semanticFacesSha256=digest(semantic_path))
            if old_id=='mondstadt-city-lod0':
                layout=[]
                for comp in components:
                    fi=np.asarray(comp['faceIds'],int);vv=native['vertices'][np.unique(native['triangles'][fi])];tt=native['vertices'][native['triangles'][fi]];cross=np.cross(tt[:,1]-tt[:,0],tt[:,2]-tt[:,0]);length=np.linalg.norm(cross,axis=1);slope=np.degrees(np.arccos(np.clip(np.abs(cross[:,1])/np.maximum(length,1e-30),0,1)))
                    flat=np.abs(slope)<2.;flat_y=tt[flat,:,1].mean(1);levels=[]
                    if len(flat_y):
                        for bucket in np.unique(np.round(flat_y,2)):
                            selected=np.abs(np.round(flat_y,2)-bucket)<1e-6;levels.append({'nativeYRoundedCentimetres':float(bucket),'faceCount':int(selected.sum()),'surfaceArea':float(length[flat][selected].sum()/2)})
                    layout.append({'componentId':comp['candidateId'],'faceIds':fi.tolist(),'nativeAabbMin':vv.min(0).tolist(),'nativeAabbMax':vv.max(0).tolist(),'nativeVertexCentroid':vv.mean(0).tolist(),
                                   'horizontalFaceHeightClusters':levels,'slopeDegrees':numbers(slope),'confirmedWholeBuilding':False,
                                   'classification':[k for k,ids in semantic['selection'].items() if comp['candidateId'] in ids]})
                write_json(out/'city-native-components.json',{'schema':1,'geometry':row['geometry'],'geometrySha256':row['geometrySha256'],'components':layout,
                    'meaning':'Connected source components may split a building or contain retaining walls; do not turn their centroid into a building placement without original source inspection.'})
        reports.append(record)
    return reports


def fidelity_report(tiles,arrays,mapping):
    rows=[]
    stride=5./(2.*mapping['scale'])
    if abs(stride-round(stride))>1e-10:return {'illustrative5ProductUnitResampling':'not computed: noninteger source stride; actual editor origin still unknown'}
    stride=int(round(stride))
    for tile in tiles:
        h=arrays[tile['id']].astype(float)*tile['scaleXYZ'][1]/tile['heightIntegerDenominator'];n=h.shape[0];knots=np.unique(np.r_[np.arange(0,n,stride),n-1]);coarse=h[np.ix_(knots,knots)]
        along_z=np.array([np.interp(np.arange(n),knots,row) for row in coarse]);reconstructed=np.array([np.interp(np.arange(n),knots,along_z[:,j]) for j in range(n)]).T
        error=np.abs(h-reconstructed)
        rows.append({'tileId':tile['id'],'storedQuantizationNativeY':tile['quantizationY'],'storedQuantizationProductY':tile['quantizationY']*mapping['scale'],
            'illustrative5ProductUnitGridReconstructionAbsErrorNativeY':numbers(error.ravel()),'illustrative5ProductUnitGridReconstructionAbsErrorProductY':numbers((error*mapping['scale']).ravel()),
            'sourcePointCount':int(h.size),'coarsePointCount':len(knots)**2,'coarseAlignment':'tile minimum, final endpoint retained; this is not actual editor origin',
            'isOriginalMapAccuracyBound':False,'includesCustomUnknownSourceCells':True})
    return {'schema':1,'rows':rows,'meaning':'Representation-loss analysis against original stored height samples, not original game render/collision accuracy. Actual editor cell origins, quantization and chosen surfaces must be assessed by terrain owner.'}


def render_overview(tiles,arrays,meshes,out,mapping):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    fig,ax=plt.subplots(figsize=(15,10),constrained_layout=True)
    minimum=min(t['nativeYRange'][0] for t in tiles);maximum=max(t['nativeYRange'][1] for t in tiles)
    for t in tiles:
        b=t['productBounds'];h=arrays[t['id']].astype(float)*t['scaleXYZ'][1]/t['heightIntegerDenominator'];img=ax.imshow(h[:,::-1],origin='lower',extent=[b['xmin'],b['xmax'],b['zmin'],b['zmax']],cmap='terrain',vmin=minimum,vmax=maximum,interpolation='nearest')
        ax.text((b['xmin']+b['xmax'])/2,(b['zmin']+b['zmax'])/2,t['id'],ha='center',va='center',bbox={'facecolor':'white','alpha':.8,'edgecolor':'none'})
        for band in t['excludedBoundaryBands']:
            q=native_to_product_xz([[band['xmin'],band['zmin']],[band['xmax'],band['zmax']]],mapping)
            ax.add_patch(plt.Rectangle(q.min(0),*np.ptp(q,axis=0),color='magenta',alpha=.6))
        with np.load(out/t['heightFile'],allow_pickle=False) as a:
            if 'customPerCellByteArray' in a:
                custom=a['customPerCellByteArray'];mask=(custom!=0)|(custom.T!=0)
                if mask.any():
                    rgba=np.zeros((*mask.shape,4));rgba[mask]=[1,0,0,.8];ax.imshow(rgba[:,::-1],origin='lower',extent=[b['xmin'],b['xmax'],b['zmin'],b['zmax']],interpolation='nearest')
    city=next((r for r in meshes['placedMeshes'] if r['name']=='Area_Mengde_City_Constant_HLOD_Lod0'),None)
    if city:
        a=np.load(out/city['productGeometry'],allow_pickle=False);faces=a['vertices'][a['triangles']];segments=faces[:,:,[0,2]][:,[0,1,2,0],:];ax.add_collection(LineCollection(segments,colors='black',linewidths=.15,alpha=.5))
    # imshow updates the data limits on every tile. Fix the union explicitly so
    # the last tile cannot silently crop the other five from the overview.
    ax.set_xlim(min(t['productBounds']['xmin'] for t in tiles),max(t['productBounds']['xmax'] for t in tiles));ax.set_ylim(min(t['productBounds']['zmin'] for t in tiles),max(t['productBounds']['zmax'] for t in tiles))
    ax.set_xlabel('Declared product X');ax.set_ylabel('Declared product Z');ax.set_title('Six original native TerrainData tiles + separate city HLOD\nMagenta: conflicting boundaries. Red: unresolved custom-cell mask. No infill.',fontsize=12);ax.set_aspect('equal');fig.colorbar(img,ax=ax,label='Native base height units, before product scaling / editor offset');fig.savefig(out/'native-source-overview.png',dpi=150);plt.close(fig)


def build(config_path,out):
    if not out.is_relative_to(ROOT) or out.exists():raise ValueError('New immutable reference delivery only')
    cfg=read(config_path);mapping=build_mapping(project_path(cfg['sharedTransform']),project_path(cfg['coordinateEvidence']),float(cfg['nativeYReference']))
    out.mkdir(parents=True);sealed_copy(config_path,out,'inputs/build-config.json');sealed_copy(project_path(cfg['sharedTransform']),out,'inputs/shared-transform.json');sealed_copy(project_path(cfg['coordinateEvidence']),out,'inputs/coordinate-evidence.json')
    bindings=[]
    for p in cfg['terrainPrefabNodes']:bindings.extend(terrain_bindings(project_path(p)))
    write_json(out/'terrain-bindings.json',{'bindings':bindings,'worldInstantiationMatrixNotPresentInPrefabs':True})
    tiles=[];arrays={}
    for entry in cfg['terrains']:
        record=read(project_path(entry['terrainRecord']));terrain=next(r for r in record['terrains'] if r['name']==entry['name']);src=project_path(terrain['npz'])
        if digest(src)!=terrain['npzSha256']:raise ValueError('Height source SHA changed')
        node=project_path(terrain['sourceNode']);source=read(node/'source.json');binding=next(b for b in bindings if b['terrainDataCab']==source['nodePath'].lower() and b['terrainDataPPtr']['pathId']==terrain['pathId'])
        if len(binding['colliders'])!=1 or len(binding['colliders'][0]['matchingTerrainDataPPtrByteOffsets'])!=1:raise ValueError('Expected unique exact collider/terrain agreement')
        tileid=entry['block'];bx,bz=map(int,tileid.split('_'));x=bx*1024.;z=bz*1024.;sc=terrain['scaleXYZ'];width=terrain['width'];height=terrain['height'];b={'xmin':x,'xmax':x+sc[0]*(width-1),'zmin':z,'zmax':z+sc[2]*(height-1)}
        target=sealed_copy(src,out,'heightfields/'+tileid+'.npz');arrays[tileid]=np.load(src,allow_pickle=False)['rawHeights']
        product=native_to_product_xz([[b['xmin'],b['zmin']],[b['xmax'],b['zmax']]],mapping)
        tiles.append({'id':tileid,'nativeBounds':b,'nativeYRange':terrain['heightRange'],'heightFile':target.relative_to(out).as_posix(),'heightSha256':digest(target),
            'sourceTerrainDataName':terrain['name'],'sourceTerrainDataPathId':terrain['pathId'],'sourceTerrainNodeSha256':terrain['sourceNodeSha256'],
            'sourceTerrainRecord':entry['terrainRecord'],'sourceTerrainRecordSha256':digest(project_path(entry['terrainRecord'])),
            'terrainBinding':binding,'scaleXYZ':sc,'storageRowAxis':'X','storageColumnAxis':'Z','shapeRowsXColumnsZ':[width,height],
            'heightIntegerDenominator':terrain['signedIntegerDenominator'],'nativeYOrigin':0.,'quantizationY':terrain['quantizationY'],
            'sampleSpacingNative':{'x':sc[0],'z':sc[2]},'sampleSpacingProduct':{'x':sc[2]*mapping['scale'],'z':sc[0]*mapping['scale']},
            'productBounds':{'xmin':float(product[:,0].min()),'xmax':float(product[:,0].max()),'zmin':float(product[:,1].min()),'zmax':float(product[:,1].max())},
            'sampleIndexFormula':'nativeX = xmin + rawRowIndex * scaleXYZ[0]; nativeZ = zmin + rawColumnIndex * scaleXYZ[2]; nativeY = rawHeights[row,column] / 32766 * scaleXYZ[1]',
            'origin':{'x':x,'z':z},'lastSample':{'x':b['xmax'],'z':b['zmax']},
            'registration':{'status':'independently-corroborated-native-placement','grade':2,'absoluteSceneParentResolved':False,
                'method':'Exact Terrain/TerrainCollider->TerrainData dependency; candidate 1024-grid placement independently checked against native HLOD geometry, native landmark and nonconstant shared edge sequences. Not a recovered runtime instantiation matrix.'},
            'customPerCellByteArraySemantics':terrain['customPerCellByteArraySemantics'],'customPerCellByteValueCounts':terrain.get('customPerCellByteValueCounts'),
            'baseHeightOnly':True,'buildingsBridgesRocksWaterNotIncluded':True})
    seams,bands=seam_report(tiles,arrays)
    for tile in tiles:tile['excludedBoundaryBands']=bands[tile['id']]
    write_json(out/'boundary-evidence.json',seams);orient=orientation_evidence(tiles,arrays);write_json(out/'axis-evidence.json',{'comparisons':orient,'storageRowAxis':'X','legacyTerrainRecordRowLabelSupersededByThisRegistration':True})
    meshes=copy_meshes([project_path(p) for p in cfg['nativeMeshIndexes']],out,mapping);write_json(out/'mesh-index.json',meshes)
    compatibility=old_mesh_compatibility(meshes,out);write_json(out/'mesh-correspondence.json',{'rows':compatibility})
    write_json(out/'placement-evidence.json',placement_decisions(tiles,seams,orient,compatibility))
    index={'schema':2,'immutable':True,'frame':'native-game-world-XYZ','declaredProductTransform':mapping,'terrainTiles':tiles,
        'terrainInterpolation':'bilinear on raw signed16 samples; each query also bounds the alternative two cell triangulations',
        'baseTerrainOnly':True,'meshIndex':'mesh-index.json','meshIndexSha256':digest(out/'mesh-index.json'),
        'knownUnresolved':cfg.get('knownUnresolved',[]),'allRequestedSixTerrainDataPresent':len(tiles)==6,
        'sourceReadMode':'rb','installationWrites':False,'gameProcessAccess':False,'desktopAccess':False,'editorPlan':False,
        'boundaryPolicy':'No infill/extrapolation. Conflicting boundary bands return null height; inspect actual mesh/scene overlay before resolving.',
        'precisionPolicy':'Stored vertical quantization is not global map accuracy. Scene placement remains independently corroborated, not parent-recovered; HLOD is simplified; editor 5m cells lose source detail.'}
    write_json(out/'source-index.json',index);ground=GroundReference(out/'source-index.json')
    points=read(ROOT/'native-frame-audit-v4/native-point-cross-reference.json')['points'];anchors=[]
    for point in points:
        xyz=point['nativeXYZ'];query=ground.query_native([[xyz[0],xyz[2]]])[0];product=transform_xyz(xyz,mapping)
        anchors.append(dict(point,productXYZ=product.tolist(),groundQuery=query,
            waypointMinusBaseTerrainY=None if query['nativeY'] is None else xyz[1]-query['nativeY'],
            meaning='Waypoint/player placement may stand on paving, rocks or structures. Difference is source evidence, not automatically a terrain error or a calibration control.'))
    write_json(out/'coordinate-examples.json',{'mapping':mapping,'nativePoints':anchors,
        'editorExample':{'editorOffsetY':2000,'offsetStatus':'illustration only; must be replaced by owner-selected editor offset',
        'formula':'editorY = productY + 2000. Do not multiply productY again.'}})
    write_json(out/'sampling-fidelity.json',fidelity_report(tiles,arrays,mapping));render_overview(tiles,arrays,meshes,out,mapping)
    oldprobes=read(project_path(cfg['oldWorldProbes']))['probes'];new=ground.query_product([p['worldXZ'] for p in oldprobes]);regions=collections.defaultdict(list);delta=[]
    for old,row in zip(oldprobes,new):
        row['logicalCell']=old['logicalCell'];row['resolvedRegion']=old['resolvedRegion'];regions[old['resolvedRegion']].append(row)
        oldheight=old.get('sourceY')
        if oldheight is not None and row['nativeY'] is not None:delta.append({'productXZ':row['productXZ'],'oldV3SourceY':oldheight,'nativeY':row['nativeY'],'nativeMinusV3Y':row['nativeY']-oldheight,'region':old['resolvedRegion']})
    write_json(out/'world-probe-reference.json',{'schema':2,'sourceIndex':'source-index.json','sourceIndexSha256':digest(out/'source-index.json'),'probes':new,
        'sameHorizontalProbeSetAs':cfg['oldWorldProbes'],'sameHorizontalProbeSetSha256':digest(project_path(cfg['oldWorldProbes']))})
    stats={key:{'count':len(rows),'statusCounts':dict(collections.Counter(r['status'] for r in rows)),
                 'tileCandidateCounts':dict(collections.Counter(c['tileId'] for r in rows for c in r['candidates']))} for key,rows in regions.items()}
    write_json(out/'coverage-report.json',{'schema':1,'probeCount':len(new),'statusCounts':dict(collections.Counter(r['status'] for r in new)),'resolvedRegions':stats,
        'actualTileBounds':[{'id':t['id'],'nativeBounds':t['nativeBounds'],'productBounds':t['productBounds']} for t in tiles],
        'sourceHeightIsBaseTerrainNotPlayableSurface':True,'interpolationDiagonalDifferenceNativeY':numbers([c['bilinearVsEitherCellDiagonalMaxDifferenceY'] for r in new for c in r['candidates']])})
    write_json(out/'v3-delta.json',{'schema':1,'sameProbeCount':len(new),'rawNativeMinusOldV3SourceHeight':numbers([r['nativeMinusV3Y'] for r in delta]),
        'byRegion':{r:numbers([d['nativeMinusV3Y'] for d in delta if d['region']==r]) for r in regions},'samples':delta,
        'meaning':'Actual new native base height versus old HLOD-selected source Y at identical declared product XZ. Mixes old placement errors, HLOD approximation and different surfaces; not a global additive correction.',
        'ownerAction':'Consume new source as a separate version and rebuild the whole chosen product frame together after review. Do not patch individual regions with these height deltas.'})
    # Freeze provenance after all derived data, before the module offline batch.
    sealed_copy(project_path('tools/mondstadt-reference/NATIVE-REFERENCE.md'),out,'README.md')
    for path in cfg.get('provenanceFiles',[]):sealed_copy(project_path(path),out,'provenance/'+Path(path).name)
    files={p.relative_to(out).as_posix():{'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(out.rglob('*')) if p.is_file()}
    package={'schema':1,'entry':'source-index.json','files':files,'sourceModuleDevelopmentComplete':True,'offlineBatchNotYetRunAtFreeze':True,
             'tools':{relative(p):digest(p) for p in sorted((project_path('tools/mondstadt-reference')).glob('*.py'))},'immutable':True}
    write_json(out/'PACKAGE.json',package)
    return {'out':relative(out),'terrainCount':len(tiles),'meshes':len(meshes['placedMeshes']),'probes':len(new),'statusCounts':dict(collections.Counter(r['status'] for r in new)),'packageSha256':digest(out/'PACKAGE.json')}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(build(project_path(a.config),project_path(a.out))))
