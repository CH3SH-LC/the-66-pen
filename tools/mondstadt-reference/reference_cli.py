"""Acquisition and geometry extraction for a pinned, bounded reference subset."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = PROJECT/'data/mondstadt/reference3d/source-lock.json'
DEFAULT_OUT = PROJECT/'data/mondstadt/reference3d/extracted'
ALLOWED_HOSTS = {'raw.githubusercontent.com', 'cdn.flatypus.me'}


def project_path(value):
    p = Path(value)
    if not p.is_absolute(): p = PROJECT/p
    p=p.resolve()
    if not p.is_relative_to(PROJECT):
        raise ValueError('All inputs and outputs must stay inside project')
    return p


def write_json(path, value):
    path=project_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.partial')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(path)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def read_lock(path):
    lock=json.loads(project_path(path).read_text(encoding='utf-8-sig'))
    if lock.get('schema')!=1 or not lock.get('files'):
        raise ValueError('Unsupported or empty source lock')
    names=set()
    for row in lock['files']:
        if row['id'] in names: raise ValueError('Duplicate source id')
        names.add(row['id']);project_path(row['path'])
        if len(row['sha256'])!=64 or any(c not in '0123456789abcdef' for c in row['sha256']):
            raise ValueError('Invalid SHA256')
        url=urllib.parse.urlparse(row['url'])
        if url.scheme!='https' or url.hostname not in ALLOWED_HOSTS or url.username or url.password:
            raise ValueError('Unapproved public data URL')
    return lock


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed=urllib.parse.urlparse(newurl)
        if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError('Redirect leaves source allowlist')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def acquire(args):
    lock=read_lock(args.lock);receipts=[];opener=urllib.request.build_opener(SafeRedirect())
    # Fixed lock bounds scope and aggregate data size; there is no archive unpack.
    if sum(r['bytes'] for r in lock['files'])>args.max_total_mib*1024*1024:
        raise ValueError('Source lock exceeds acquisition budget')
    for row in lock['files']:
        path=project_path(row['path'])
        if path.exists():
            if path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:
                raise ValueError(f'Existing source differs; preserving it: {path}')
            receipts.append({'id':row['id'],'status':'existing-matched','sha256':row['sha256']})
            continue
        request=urllib.request.Request(row['url'],headers={'User-Agent':'Mondstadt-Reference-Acquisition/1.0'})
        with opener.open(request,timeout=45) as response:
            announced=response.headers.get('Content-Length')
            if announced is not None and int(announced)>row['bytes']:
                raise ValueError('Remote file exceeds locked size')
            data=response.read(row['bytes']+1)
            etag=response.headers.get('ETag')
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise ValueError(f'Remote content differs from lock: {row["id"]}')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as destination: destination.write(data)
        receipts.append({'id':row['id'],'status':'downloaded','sha256':row['sha256'],'etag':etag})
    write_json(args.receipt,{'schema':1,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                             'lockSha256':digest(project_path(args.lock)),'files':receipts})
    print(json.dumps({'acquired':len(receipts),'receipt':str(project_path(args.receipt))}))


def load_sources(lock):
    rows=[]
    for row in lock['files']:
        path=project_path(row['path'])
        if not path.is_file() or digest(path)!=row['sha256']:
            raise ValueError(f'Source missing or hash changed: {path}')
        if row.get('role') not in ('city-geometry','regional-hlod-geometry'):
            continue
        mesh=read_obj(path) if path.suffix=='.obj' else read_glb(path)
        rows.append((row,mesh))
    return rows


def join_meshes(rows):
    vertices,faces,groups,face_groups,spans=[],[],[],[],[]
    vi=fi=gi=0
    for row,mesh in rows:
        vertices.append(mesh.vertices);faces.append(mesh.faces+vi)
        face_groups.append(mesh.face_groups+gi)
        groups.extend(f'{row["id"]}:{g}' for g in mesh.groups)
        spans.append({'id':row['id'],'firstVertex':vi,'vertexCount':len(mesh.vertices),
                      'firstFace':fi,'faceCount':len(mesh.faces),'sourceSha256':row['sha256']})
        vi+=len(mesh.vertices);fi+=len(mesh.faces);gi+=len(mesh.groups)
    if not vertices: raise ValueError('No geometry')
    return Mesh(np.concatenate(vertices),np.concatenate(faces),groups,np.concatenate(face_groups)),spans


def frame_matrix(row,mesh,frame):
    matrix=np.eye(4)
    if frame=='raw': return matrix
    if row['role']=='city-geometry':
        p=row['manifestPosition']
        matrix[:3,3]=[-p['x']+(1024 if frame=='viewer' else 0),p['y'],p['z']]
    elif frame=='viewer':
        bx,bz=row['block'];center=(mesh.vertices.min(axis=0)+mesh.vertices.max(axis=0))/2
        matrix[:3,3]=[-bx*1024+512-center[0],0,bz*1024+512-center[2]]
        if row.get('viewerOverride'): matrix[:3,3]=row['viewerOverride']
    # raw-baked hypothesis is only used for spatial comparisons, not called native.
    return matrix


def save_mesh(path,mesh):
    np.savez_compressed(path,vertices=mesh.vertices,faces=mesh.faces,
                        face_groups=mesh.face_groups,group_names=np.array(mesh.groups))


def export_grid(path,mesh,bounds,spacing,frame,spans):
    grid=sample_surface(mesh,bounds,spacing)
    np.savez_compressed(path.with_suffix('.npz'),**grid)
    valid=np.isfinite(grid['top']);both=valid&np.isfinite(grid['bottom'])
    metadata={'schema':1,'frame':frame,'spacingSourceUnits':spacing,'metersPerSourceUnitVerified':False,
              'boundsXZ':bounds,'shapeZThenX':list(grid['top'].shape),'validSamples':int(valid.sum()),
              'missingSamples':int((~valid).sum()),'holesFilled':False,'syntheticOceanIncluded':False,
              'semantics':'vertical triangle intersections; top/bottom are surface candidates, not classified bare earth',
              'layerAmbiguousSamples':int((both&((grid['top']-grid['bottom'])>0.25)).sum()),
              'triangleHitsMeaning':'triangle intersections, shared edges can count twice',
              'heightRange':[float(np.nanmin(grid['bottom'])),float(np.nanmax(grid['top']))] if valid.any() else None,
              'npz':path.with_suffix('.npz').name,'faceSourceSpans':spans,
              'arrays':{'x':'1D x coordinates','z':'1D z coordinates','top':'highest surface Y; NaN is missing',
                        'bottom':'lowest surface Y; NaN is missing','top_face':'joined mesh triangle id',
                        'bottom_face':'joined mesh triangle id','triangle_hits':'not unique layers',
                        'top_slope_degrees':'0 horizontal, 90 vertical; double sided'}}
    write_json(path.with_suffix('.json'),metadata)
    return metadata,grid


def draw_geometry(mesh,path,labels=None,title=''):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    triangles=mesh.vertices[mesh.faces]
    fig,ax=plt.subplots(figsize=(12,12))
    order=np.argsort(triangles[:,:,1].mean(axis=1))
    patches=PolyCollection(triangles[order][:,:,[0,2]],array=triangles[order,:,1].mean(axis=1),
                           cmap='terrain',linewidths=0,rasterized=True)
    ax.add_collection(patches);ax.autoscale_view();ax.set_aspect('equal')
    if labels:
        for row in labels:
            if row['convexFootprintArea']>=15 and row['faceCount']>=30:
                x,z=row['centerXZ'];ax.text(x,z,str(row['candidateId']),fontsize=6,
                    bbox={'facecolor':'white','alpha':0.6,'edgecolor':'none','pad':0.2})
    ax.set_xlabel('source frame X');ax.set_ylabel('source frame Z');ax.set_title(title)
    fig.colorbar(patches,ax=ax,label='source surface Y')
    fig.savefig(path,dpi=150,bbox_inches='tight');plt.close(fig)


def extract(args):
    lock=read_lock(args.lock);sources=load_sources(lock);out=project_path(args.out)
    out.mkdir(parents=True,exist_ok=True);index=[];placed=[];city=None
    for row,raw in sources:
        matrix=frame_matrix(row,raw,args.frame);mesh=transform(raw,matrix)
        save_mesh(out/(row['id']+'.npz'),mesh)
        record={'id':row['id'],'sourceSha256':row['sha256'],'role':row['role'],
                'rawAabbMin':raw.vertices.min(axis=0).tolist(),'rawAabbMax':raw.vertices.max(axis=0).tolist(),
                'aabbMin':mesh.vertices.min(axis=0).tolist(),'aabbMax':mesh.vertices.max(axis=0).tolist(),
                'rawToFrame':matrix.tolist(),'vertexCount':len(mesh.vertices),'faceCount':len(mesh.faces),
                'groups':mesh.groups,'geometryNpz':row['id']+'.npz'}
        index.append(record);placed.append((row,mesh))
        if row['role']=='city-geometry':city=(row,mesh)
        else:
            write_json(out/(row['id']+'-components.json'),
                       {'schema':1,'mesh':row['id'],'sourceSha256':row['sha256'],
                        'candidates':component_candidates(mesh,args.weld)})
    if city is None: raise ValueError('City mesh required')
    city_row,city_mesh=city
    candidates=component_candidates(city_mesh,args.weld)
    write_json(out/'city-components.json',{'schema':1,'frame':args.frame,
                'sourceSha256':city_row['sha256'],'weldToleranceSourceUnits':args.weld,
                'meaning':'Connected geometry and convex footprints; not one-to-one building instances',
                'requiresVisualSemanticReview':True,'candidates':candidates})
    joined,spans=join_meshes(placed);save_mesh(out/'joined-geometry.npz',joined)
    regional,rspans=join_meshes([(r,m) for r,m in placed if r['role']!='city-geometry'])
    if args.bounds:bounds=args.bounds
    else:
        lo=city_mesh.vertices.min(axis=0);hi=city_mesh.vertices.max(axis=0)
        bounds=[float(lo[0]-500),float(hi[0]+500),float(lo[2]-600),float(hi[2]+400)]
    surfaces=[]
    for name,mesh,mesh_spans in [('all-surfaces',joined,spans),('regional-surfaces',regional,rspans)]:
        metadata,_=export_grid(out/name,mesh,bounds,args.spacing,args.frame,mesh_spans);surfaces.append(metadata)
    draw_geometry(city_mesh,out/'city-topdown.png',candidates,'Mondstadt source HLOD: geometry component IDs (not buildings)')
    draw_geometry(joined,out/'region-topdown.png',title='Source HLOD surfaces; water fill excluded; placement frame: '+args.frame)
    result={'schema':1,'sourceLockSha256':digest(project_path(args.lock)),'frame':args.frame,
            'frameMeaning':lock['frames'][args.frame],'nativeCoordinateMatchVerified':False,
            'metersPerSourceUnitVerified':False,'meshSources':index,'componentCount':len(candidates),
            'surfaceGrids':surfaces,'sourceGameVersion':'not supplied by upstream',
            'semanticBuildingInventoryComplete':False,'originalOceanOrWaterGeometry':False,
            'official2dRegistration':'requires separately identified anchors and residual report',
            'actualGameImportOrAcceptance':False}
    write_json(out/'index.json',result)
    print(json.dumps({'out':str(out),'meshes':len(index),'components':len(candidates),
                      'vertices':len(joined.vertices),'triangles':len(joined.faces),
                      'surfaceSamples':[r['validSamples'] for r in surfaces]}))


def register(args):
    doc=json.loads(project_path(args.anchors).read_text(encoding='utf-8-sig'))
    result=fit_registration(doc['anchors'],args.allow_reflection)
    result['sourceFrame']=doc['sourceFrame'];result['anchorFileSha256']=digest(project_path(args.anchors))
    result['officialReference']=doc['officialReference'];result['deploymentEligible']=False
    result['thresholdSatisfied']=result['maxResidualPixels']<=args.max_residual
    result['residualThresholdPixels']=args.max_residual
    write_json(args.out,result);print(json.dumps(result,ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);commands=p.add_subparsers(dest='command',required=True)
    a=commands.add_parser('acquire');a.add_argument('--lock',default=str(DEFAULT_LOCK))
    a.add_argument('--max-total-mib',type=float,default=64)
    a.add_argument('--receipt',default='.runtime/mondstadt/rework-20261017/reference3d/acquisition-receipt.json');a.set_defaults(run=acquire)
    a=commands.add_parser('extract');a.add_argument('--lock',default=str(DEFAULT_LOCK));a.add_argument('--out',default=str(DEFAULT_OUT))
    a.add_argument('--frame',choices=['raw','viewer','raw-baked-hypothesis'],default='viewer')
    a.add_argument('--bounds',nargs=4,type=float);a.add_argument('--spacing',type=float,default=5)
    a.add_argument('--weld',type=float,default=0.0001);a.set_defaults(run=extract)
    a=commands.add_parser('register');a.add_argument('--anchors',required=True);a.add_argument('--out',required=True)
    a.add_argument('--allow-reflection',action='store_true');a.add_argument('--max-residual',type=float,default=3);a.set_defaults(run=register)
    args=p.parse_args()
    # Help and schema discovery work without optional mesh dependencies.
    global np, Mesh, component_candidates, fit_registration, read_glb, read_obj, sample_surface, transform
    import numpy as np
    from geometry import (Mesh, component_candidates, fit_registration, read_glb,
                          read_obj, sample_surface, transform)
    args.run(args)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
