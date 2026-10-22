"""Pure asset measurements and immutable artifact conventions. No live queries."""
from pathlib import Path
import itertools
import math
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TRANSFORM=ROOT/'tools/entity-transform'
sys.path.insert(0,str(TRANSFORM))
from contract import require,read,write,sha,identifier
from physics_receipt import matmul,point,close

OUTPUT=ROOT/'.runtime/asset-inspection-20261017/prepared'
DATA=ROOT/'data/mondstadt/asset-inspection'
KIND='asset-inspection-prepared-v1'
BUILD_KIND='asset-inspection-build-v1'
SCOPE='FIXED_ASSET_INSPECTION_QUERY'
MAX_ENTITIES=8
MAX_OBJECTS=64
OBJECT_SIZE=584
ENTITY_SIZE=37544
CATALOG=ROOT/'.runtime/verification/interface-experiments-20260928/geometry-fix/prefab-catalog-r219.json'
CATALOG_SHA='46faaa35cdd58c38cb513b865e06e48ef9bc8b865e11927ea5db0ab5698726f3'

def guarded_output(value,*,prepared=False):
    path=Path(value).absolute()
    boundary=OUTPUT if prepared else ROOT
    require(path.is_relative_to(boundary) and path!=boundary,'OUTPUT_OUTSIDE_ALLOWED_ROOT')
    for part in (path,*path.parents):
        if part.exists():
            require(not part.is_symlink() and not(getattr(part.stat(),'st_file_attributes',0)&0x400),'REPARSE_PATH_REFUSED')
        if part==ROOT:break
    return path.resolve()

def emit(path,value):
    path=guarded_output(path);path.parent.mkdir(parents=True,exist_ok=True);write(path,value)
    return dict(path=str(path),sha256=sha(path))

def bounds(corners):
    require(corners and all(len(p)==3 and all(math.isfinite(v) for v in p) for p in corners),'BOUNDS_FINITE_REQUIRED')
    lo=[min(p[i] for p in corners) for i in range(3)];hi=[max(p[i] for p in corners) for i in range(3)]
    return dict(min=lo,max=hi,center=[(a+b)/2 for a,b in zip(lo,hi)],size=[b-a for a,b in zip(lo,hi)],
                originToCenter=[(a+b)/2 for a,b in zip(lo,hi)],bottomOffset=lo[1])

def corners(value,matrix=None):
    c,e=value['center'],value['extents']
    require(len(c)==len(e)==3 and all(math.isfinite(x) for x in c+e) and all(x>=0 for x in e),'INVALID_NATIVE_BOUNDS')
    points=[[c[i]+sign[i]*e[i] for i in range(3)] for sign in itertools.product((-1,1),repeat=3)]
    return [point(matrix,p) for p in points] if matrix is not None else points

def aggregate(values):
    points=[]
    for v in values:points.extend([v['min'],v['max']])
    return bounds(points) if points else None

def measure(entity):
    identity=[1. if i%5==0 else 0. for i in range(16)]
    forward,inverse=entity['localToWorld'],entity['worldToLocal']
    require(len(forward)==len(inverse)==16 and close(matmul(inverse,forward),identity,.002),'ENTITY_MATRIX_NOT_INVERTIBLE')
    require(close([forward[12],forward[13],forward[14]],entity['pose']['worldPosition'],.01),'MATRIX_POSE_ORIGIN_MISMATCH')
    require(close([forward[3],forward[7],forward[11],forward[15]],[0,0,0,1],.001),'NONAFFINE_ENTITY_MATRIX')
    renderers=[];colliders=[]
    for obj in entity['objects']:
        require(obj['kind'] in (1,2) and obj['belongs']==obj['stable']==1,'OBJECT_KIND_OR_STABILITY')
        require(obj['geometry'] in (0,1) and (obj['kind']==1 or obj['geometry']==0),'GEOMETRY_SOURCE_INVALID')
        require(obj['geometry']==0 or obj['mesh']>=0x10000,'GEOMETRY_MESH_IDENTITY_UNAVAILABLE')
        relative=matmul(inverse,obj['localToWorld'])
        row=dict(obj,worldAabb=bounds(corners(obj['worldBounds'])),
                 normalizedWorldAabbEnvelope=bounds(corners(obj['worldBounds'],inverse)),
                 relativeToEntity=relative,worldAabbNormalization='inverse actual entity matrix; conservative envelope, rotation can enlarge',
                 actualCollisionSurfaceVerified=False)
        if obj['kind']==1:
            row['unitEntityLocalGeometryBounds']=bounds(corners(obj['localGeometryBounds'],relative)) if obj['geometry']==1 else None
            row['geometryBasis']='MeshRenderer.sharedMesh.bounds transformed to entity coordinates' if obj['geometry']==1 else 'unknown: renderer has no captured static shared mesh'
            row['tightMeshVertexBoundsVerified']=False
            renderers.append(row)
        else:colliders.append(row)
    active=[r for r in renderers if r['active']==r['enabled']==1]
    complete=bool(active) and all(r['unitEntityLocalGeometryBounds'] is not None for r in active)
    unit=aggregate([r['unitEntityLocalGeometryBounds'] for r in active]) if complete else None
    return dict(entityId=entity['entityId'],pose=entity['pose'],origin=dict(world=entity['pose']['worldPosition'],local=entity['pose']['localPosition'],
        unityTransform=entity['unity'],viewTransform=entity['view']),entityLocalToWorld=forward,entityWorldToLocal=inverse,
        actualLocalScale=entity['pose']['scale'],scaleNormalized=True,normalization='full actual inverse entity matrix; preserves child transforms; no division of rotated world AABB',
        renderers=renderers,colliders=colliders,rendererCount=len(renderers),colliderCount=len(colliders),
        activeRendererGeometryComplete=complete,unitEntityRendererGeometryBounds=unit,
        renderDimensionsAtUnitEntityScale=unit['size'] if unit else None,
        activeRendererWorldBounds=aggregate([r['worldAabb'] for r in active]),
        activeColliderWorldBounds=aggregate([r['worldAabb'] for r in colliders if r['active']==r['enabled']==1]),
        appearanceVerified=False,modelResourcePath=None,texturePixelsAvailable=False,
        playerContactVerified=False,collisionBlockingVerified=False)

def catalog_evidence(template_ids):
    require(sha(CATALOG)==CATALOG_SHA,'FROZEN_CATALOG_CHANGED')
    document=read(CATALOG)
    require(document.get('ok') is True and document.get('truncated') is False,'CATALOG_INCOMPLETE')
    by_id={}
    for row in document['prefabs']:
        tid=identifier(row['registryId']);require(tid not in by_id,'CATALOG_DUPLICATE_TEMPLATE_ID');by_id[tid]=row
    result={}
    for tid in template_ids:
        row=by_id.get(tid)
        result[str(tid)]=dict(found=row is not None,templateId=tid,name=row.get('name') if row else None,
            iconPath=row.get('iconPath') if row else None,nativeKind=row.get('nativeKind') if row else None,
            sameNameTemplateIds=[k for k,v in by_id.items() if row and v.get('name')==row.get('name')],
            association='exact registryId equals native snapshot configId; never a name lookup',
            source=str(CATALOG),sourceSha256=CATALOG_SHA,iconPixelsLoaded=False,modelPathKnown=False,appearanceVerified=False)
    return result

def template_summary(samples):
    """City-facing fields only when every observed instance supports the same bounds."""
    require(samples,'TEMPLATE_SAMPLES_REQUIRED')
    first=samples[0];tid=first['templateId'];require(all(x['templateId']==tid for x in samples),'MIXED_TEMPLATE_SUMMARY')
    geometry=[x['unitEntityRendererGeometryBounds'] for x in samples]
    complete=all(x is not None for x in geometry)
    agree=complete and all(close(geometry[0]['min'],x['min'],.01) and close(geometry[0]['max'],x['max'],.01) for x in geometry)
    measured=geometry[0] if agree else None
    origin='unknown'
    if measured:
        center=measured['center'];bottom=measured['min'][1]
        if close([center[0],bottom,center[2]],[0,0,0],.01):origin='base-center'
        elif close(center,[0,0,0],.01):origin='geometric-center'
        else:origin='explicit-offset'
    return dict(registryId=tid,nameZh=first['catalog']['name'],assetPath=None,iconPath=first['catalog']['iconPath'],
        nativeKind=first['catalog']['nativeKind'],category='unknown',sampleEntityIds=[x['entityId'] for x in samples],
        boundsRenderer=dict(min=measured['min'],max=measured['max'],space='entity-local-unit-scale',unit='native-world-unit',
            meterConversion='Project convention is 1 native world unit = 1 m; no independent physical calibration',
            basis='actual MeshRenderer sharedMesh bounds transformed by full entity inverse; not a vertex hull') if measured else None,
        boundsCollider=None,boundsColliderReason='Only runtime world AABB observed; inverse AABB is conservative and cannot establish exact local collider shape',
        colliderEnvelopes=[dict(entityId=x['entityId'],bounds=[y['normalizedWorldAabbEnvelope'] for y in x['colliders']]) for x in samples],
        originConvention=origin,originToGeometryCenter=measured['center'] if measured else None,
        geometryBottomOffset=measured['min'][1] if measured else None,
        sampleBoundsConsistent=agree,geometryMeasurementComplete=complete,appearanceVerified=False,
        blocksSizeBasedPlacement=not agree,canonicalAcrossUnobservedInstancesVerified=False,
        evidence=dict(source='native raw receipt(s); exact configId association',catalog=first['catalog'],
            note='Shared iconPath or unknown assetPath does not prove two IDs have identical models/materials'))
