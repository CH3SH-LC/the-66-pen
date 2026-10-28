"""Read-only OBJ/GLB geometry, topology candidates and layered surface sampling.

No game process or third-party executable is used. Positions remain in explicitly
named source frames. A connected mesh component is not a confirmed building.
"""
from __future__ import annotations

import base64
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Mesh:
    vertices: np.ndarray
    faces: np.ndarray
    groups: list[str]
    face_groups: np.ndarray


def _valid(mesh: Mesh) -> Mesh:
    if mesh.vertices.ndim != 2 or mesh.vertices.shape[1] != 3:
        raise ValueError('Positions must be VEC3')
    if not np.isfinite(mesh.vertices).all():
        raise ValueError('Nonfinite position')
    if mesh.faces.ndim != 2 or mesh.faces.shape[1] != 3:
        raise ValueError('Only triangle meshes are accepted')
    if mesh.faces.size and (mesh.faces.min() < 0 or mesh.faces.max() >= len(mesh.vertices)):
        raise ValueError('Index out of range')
    return mesh


def read_obj(path: Path) -> Mesh:
    vertices, faces, groups, face_groups = [], [], ['default'], []
    current = 0
    with path.open(encoding='utf-8-sig') as source:
        for number, line in enumerate(source, 1):
            parts = line.strip().split()
            if not parts or parts[0].startswith('#'):
                continue
            if parts[0] == 'v':
                if len(parts) not in (4, 5):
                    raise ValueError(f'{path}:{number}: malformed vertex')
                point = list(map(float, parts[1:4]))
                if len(parts) == 5:
                    weight = float(parts[4])
                    if weight == 0:
                        raise ValueError('Zero homogeneous coordinate')
                    point = [v / weight for v in point]
                vertices.append(point)
            elif parts[0] in ('g', 'o'):
                groups.append(' '.join(parts[1:]) or 'unnamed')
                current = len(groups) - 1
            elif parts[0] == 'f':
                # Do not silently triangulate a potentially concave polygon.
                if len(parts) != 4:
                    raise ValueError(f'{path}:{number}: nontriangle polygon requires explicit triangulation')
                ids = [int(p.split('/')[0]) for p in parts[1:]]
                if any(v == 0 for v in ids):
                    raise ValueError('OBJ index zero')
                faces.append([v - 1 if v > 0 else len(vertices) + v for v in ids])
                face_groups.append(current)
    return _valid(Mesh(np.asarray(vertices, dtype=np.float64).reshape(-1, 3),
                       np.asarray(faces, dtype=np.int64).reshape(-1, 3), groups,
                       np.asarray(face_groups, dtype=np.int32)))


def _trs(node: dict) -> np.ndarray:
    if 'matrix' in node:
        if any(k in node for k in ('translation', 'rotation', 'scale')):
            raise ValueError('GLTF node has both matrix and TRS')
        return np.asarray(node['matrix'], dtype=float).reshape(4, 4, order='F')
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])
    norm = math.sqrt(x*x+y*y+z*z+w*w)
    if norm == 0:
        raise ValueError('Zero quaternion')
    x, y, z, w = x/norm, y/norm, z/norm, w/norm
    rotation = np.array([[1-2*y*y-2*z*z, 2*x*y-2*z*w, 2*x*z+2*y*w],
                         [2*x*y+2*z*w, 1-2*x*x-2*z*z, 2*y*z-2*x*w],
                         [2*x*z-2*y*w, 2*y*z+2*x*w, 1-2*x*x-2*y*y]])
    result = np.eye(4)
    result[:3, :3] = rotation @ np.diag(node.get('scale', [1, 1, 1]))
    result[:3, 3] = node.get('translation', [0, 0, 0])
    return result


def read_glb(path: Path) -> Mesh:
    """GLB 2.0 triangles with embedded buffers and node transforms.

    External URIs, skins/morphs, sparse accessors and geometry compression fail
    closed; no fetch, extension execution or implicit lossy approximation.
    """
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError('Truncated GLB')
    magic, version, length = struct.unpack_from('<4sII', data)
    if magic != b'glTF' or version != 2 or length != len(data):
        raise ValueError('Invalid GLB header')
    chunks, offset = [], 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError('Truncated chunk header')
        count, kind = struct.unpack_from('<II', data, offset)
        offset += 8
        if count % 4 or offset + count > len(data):
            raise ValueError('Invalid chunk size')
        chunks.append((kind, data[offset:offset+count])); offset += count
    if not chunks or chunks[0][0] != 0x4E4F534A:
        raise ValueError('First chunk is not JSON')
    doc = json.loads(chunks[0][1].rstrip(b' \x00'))
    if doc.get('extensionsRequired'):
        raise ValueError('Required GLTF extensions are not implemented')
    binary = [b for k, b in chunks if k == 0x004E4942]
    if len(binary) > 1:
        raise ValueError('Multiple BIN chunks')
    buffers = []
    for i, item in enumerate(doc.get('buffers', [])):
        uri = item.get('uri')
        if uri is None:
            if i != 0 or not binary:
                raise ValueError('Missing GLB buffer')
            value = binary[0]
        elif uri.startswith('data:application/octet-stream;base64,'):
            value = base64.b64decode(uri.split(',', 1)[1], validate=True)
        else:
            raise ValueError('External GLTF buffer is forbidden')
        if len(value) < item['byteLength']:
            raise ValueError('Truncated buffer')
        buffers.append(value)
    dtypes = {5120:'i1', 5121:'u1', 5122:'<i2', 5123:'<u2', 5125:'<u4', 5126:'<f4'}
    widths = {'SCALAR':1, 'VEC2':2, 'VEC3':3, 'VEC4':4}
    def accessor(index):
        a = doc['accessors'][index]
        if 'sparse' in a or a.get('normalized'):
            raise ValueError('Sparse/normalized accessor is not implemented')
        view = doc['bufferViews'][a['bufferView']]
        dtype = np.dtype(dtypes[a['componentType']]); width = widths[a['type']]
        start = view.get('byteOffset', 0) + a.get('byteOffset', 0)
        stride = view.get('byteStride', width*dtype.itemsize)
        if stride < width*dtype.itemsize or stride % dtype.itemsize:
            raise ValueError('Invalid accessor stride')
        end = start + max(0, a['count']-1)*stride + (width*dtype.itemsize if a['count'] else 0)
        if end > view.get('byteOffset', 0)+view['byteLength'] or end > len(buffers[view['buffer']]):
            raise ValueError('Accessor exceeds buffer view')
        return np.ndarray((a['count'], width), dtype=dtype, buffer=buffers[view['buffer']],
                          offset=start, strides=(stride, dtype.itemsize)).copy()
    all_v, all_f, labels, face_groups = [], [], [], []
    base = 0
    active = set()
    def walk(index, parent):
        nonlocal base
        if index in active:
            raise ValueError('GLTF node cycle')
        active.add(index)
        node = doc['nodes'][index]; matrix = parent @ _trs(node)
        if 'skin' in node or 'weights' in node:
            raise ValueError('Skinned/morphed node is unsupported')
        if 'mesh' in node:
            for pi, prim in enumerate(doc['meshes'][node['mesh']]['primitives']):
                if prim.get('mode', 4) != 4 or 'targets' in prim or prim.get('extensions'):
                    raise ValueError('Only uncompressed static triangles are supported')
                v = accessor(prim['attributes']['POSITION'])
                if v.shape[1] != 3:
                    raise ValueError('POSITION must be VEC3')
                v = (np.c_[v, np.ones(len(v))] @ matrix.T)[:, :3]
                f = accessor(prim['indices']).ravel().astype(np.int64) if 'indices' in prim else np.arange(len(v))
                if len(f) % 3 or (len(f) and (f.min() < 0 or f.max() >= len(v))):
                    raise ValueError('Invalid primitive indices')
                # Preserve transformed geometric winding under reflection.
                f = f.reshape(-1, 3)
                if np.linalg.det(matrix[:3, :3]) < 0:
                    f = f[:, [0, 2, 1]]
                all_v.append(v); all_f.append(f+base); base += len(v)
                labels.append(f"node:{index}:{node.get('name', '')}:primitive:{pi}")
                face_groups.extend([len(labels)-1]*len(f))
        for child in node.get('children', []):
            walk(child, matrix)
        active.remove(index)
    scenes = doc.get('scenes', [])
    if not scenes:
        raise ValueError('GLTF scene is required')
    for index in scenes[doc.get('scene', 0)].get('nodes', []):
        walk(index, np.eye(4))
    return _valid(Mesh(np.concatenate(all_v) if all_v else np.empty((0,3)),
                       np.concatenate(all_f) if all_f else np.empty((0,3), dtype=np.int64),
                       labels, np.asarray(face_groups, dtype=np.int32)))


def transform(mesh: Mesh, matrix) -> Mesh:
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0,0,0,1]):
        raise ValueError('Finite affine 4x4 matrix required')
    return _valid(Mesh((np.c_[mesh.vertices, np.ones(len(mesh.vertices))] @ matrix.T)[:, :3],
                       mesh.faces.copy(), mesh.groups, mesh.face_groups.copy()))


def convex_hull(points):
    values = sorted(set(map(tuple, np.asarray(points).tolist())))
    if len(values) <= 2:
        return values
    def cross(a,b,c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower, upper = [], []
    for p in values:
        while len(lower) >= 2 and cross(lower[-2],lower[-1],p) <= 0: lower.pop()
        lower.append(p)
    for p in reversed(values):
        while len(upper) >= 2 and cross(upper[-2],upper[-1],p) <= 0: upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


def component_candidates(mesh: Mesh, weld=0.0001):
    if weld <= 0:
        raise ValueError('Positive weld tolerance required')
    _, inverse = np.unique(np.rint(mesh.vertices/weld).astype(np.int64), axis=0, return_inverse=True)
    parent = np.arange(int(inverse.max())+1)
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return int(a)
    for a,b,c in inverse[mesh.faces]:
        ra,rb,rc = find(a),find(b),find(c)
        parent[rb] = ra; parent[rc] = ra
    bins = {}
    for fi, f in enumerate(mesh.faces):
        bins.setdefault(find(inverse[f[0]]), []).append(fi)
    rows = []
    for ids in bins.values():
        points = mesh.vertices[np.unique(mesh.faces[ids].ravel())]
        low, high = points.min(axis=0), points.max(axis=0)
        hull = convex_hull(points[:, [0,2]])
        center = points[:, [0,2]].mean(axis=0)
        centered = points[:, [0,2]]-center
        covariance = centered.T @ centered / max(1,len(points)-1)
        values, vectors = np.linalg.eigh(covariance)
        principal = vectors[:, np.argmax(values)]
        yaw = math.degrees(math.atan2(principal[1],principal[0])) % 180
        area = abs(sum(hull[i][0]*hull[(i+1)%len(hull)][1]-hull[(i+1)%len(hull)][0]*hull[i][1]
                       for i in range(len(hull))))/2 if len(hull)>2 else 0
        rows.append({'candidateId':len(rows),'classification':'unclassified-connected-surface',
                     'confirmedBuilding':False,'faceCount':len(ids),'vertexCount':len(points),
                     'faceIds':ids,'aabbMin':low.tolist(),'aabbMax':high.tolist(),
                     'centerXZ':center.tolist(),'heightRange':[float(low[1]),float(high[1])],
                     'convexFootprintXZ':hull,'convexFootprintArea':area,
                     'principalYawDegreesModulo180':yaw,
                     'orientationAnisotropy':float(values.max()/max(values.min(),1e-12)),
                     'orientationMeaning':'PCA of geometry, not native entity rotation',
                     'sourceGroups':sorted({mesh.groups[int(mesh.face_groups[i])] for i in ids})})
    return rows


def sample_surface(mesh: Mesh, bounds, spacing=5.0):
    """Vertical intersections, retaining both layers and source triangle IDs.

    Top is not automatically ground. No water surface or missing-data infill.
    Adjacent triangle intersections may produce duplicate hit counts.
    """
    x0,x1,z0,z1 = map(float,bounds)
    if spacing <= 0 or x1 <= x0 or z1 <= z0:
        raise ValueError('Invalid grid')
    xs = np.arange(math.ceil(x0/spacing)*spacing, x1+1e-8, spacing)
    zs = np.arange(math.ceil(z0/spacing)*spacing, z1+1e-8, spacing)
    if len(xs)*len(zs)>4_000_000 or not len(xs) or not len(zs):
        raise ValueError('Grid size out of bounds')
    shape = (len(zs),len(xs))
    top, bottom = np.full(shape,-np.inf),np.full(shape,np.inf)
    top_id,bottom_id = np.full(shape,-1,dtype=np.int32),np.full(shape,-1,dtype=np.int32)
    hits = np.zeros(shape,dtype=np.uint32)
    slope = np.full(shape,np.nan)
    for fi, ids in enumerate(mesh.faces):
        a,b,c = mesh.vertices[ids]
        determinant = (b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
        if abs(determinant)<1e-10: continue
        tri = np.array([a,b,c])
        ix0=max(0,int(math.ceil((tri[:,0].min()-xs[0])/spacing-1e-7)))
        ix1=min(len(xs)-1,int(math.floor((tri[:,0].max()-xs[0])/spacing+1e-7)))
        iz0=max(0,int(math.ceil((tri[:,2].min()-zs[0])/spacing-1e-7)))
        iz1=min(len(zs)-1,int(math.floor((tri[:,2].max()-zs[0])/spacing+1e-7)))
        if ix0>ix1 or iz0>iz1: continue
        xx,zz=np.meshgrid(xs[ix0:ix1+1],zs[iz0:iz1+1])
        wa=((b[2]-c[2])*(xx-c[0])+(c[0]-b[0])*(zz-c[2]))/determinant
        wb=((c[2]-a[2])*(xx-c[0])+(a[0]-c[0])*(zz-c[2]))/determinant
        wc=1-wa-wb
        mask=(wa>=-1e-7)&(wb>=-1e-7)&(wc>=-1e-7)
        y=wa*a[1]+wb*b[1]+wc*c[1]
        view=(slice(iz0,iz1+1),slice(ix0,ix1+1))
        hi=mask&(y>top[view]);lo=mask&(y<bottom[view])
        top[view][hi]=y[hi];bottom[view][lo]=y[lo]
        top_id[view][hi]=fi;bottom_id[view][lo]=fi
        normal=np.cross(b-a,c-a)
        angle=math.degrees(math.acos(min(1,abs(normal[1])/max(np.linalg.norm(normal),1e-30))))
        slope[view][hi]=angle;hits[view]+=mask.astype(np.uint32)
    top[~np.isfinite(top)]=np.nan;bottom[~np.isfinite(bottom)]=np.nan
    return dict(x=xs,z=zs,top=top,bottom=bottom,top_face=top_id,bottom_face=bottom_id,
                triangle_hits=hits,top_slope_degrees=slope)


def fit_registration(anchors: list[dict], allow_reflection=False):
    """Fit XZ -> official global pixels similarity using >=3 named controls.

    Fit residuals plus leave-one-out error are reported; numerical fit is not
    an assertion that a manually identified control is semantically correct.
    """
    if len(anchors)<3 or len({a['id'] for a in anchors})!=len(anchors):
        raise ValueError('At least three uniquely named control anchors required')
    source=np.array([a['sourceXZ'] for a in anchors],dtype=float)
    target=np.array([a['officialGlobalPixel'] for a in anchors],dtype=float)
    if source.shape!=(len(anchors),2) or target.shape!=source.shape or not np.isfinite(np.r_[source,target]).all():
        raise ValueError('Finite paired XZ and pixel coordinates required')
    def solve(a,b):
        ac=a.mean(axis=0);bc=b.mean(axis=0);aa=a-ac;bb=b-bc
        if np.linalg.matrix_rank(aa)<2:
            raise ValueError('Collinear controls cannot establish registration')
        u,s,vt=np.linalg.svd(aa.T@bb);r=u@vt
        if np.linalg.det(r)<0 and not allow_reflection:
            u[:,-1]*=-1;s[-1]*=-1;r=u@vt
        scale=s.sum()/np.sum(aa*aa)
        if scale<=0: raise ValueError('Degenerate registration')
        return r*scale,bc-ac@(r*scale)
    matrix,offset=solve(source,target);prediction=source@matrix+offset
    residual=np.linalg.norm(prediction-target,axis=1)
    loo=[]
    if len(anchors)>=4:
        for i in range(len(anchors)):
            try:
                m,o=solve(np.delete(source,i,axis=0),np.delete(target,i,axis=0))
                loo.append(float(np.linalg.norm(source[i]@m+o-target[i])))
            except ValueError: loo.append(None)
    return {'schema':1,'model':'similarity-row-vector','sourceFrame':'explicit-in-anchor-file',
            'matrix2x2':matrix.tolist(),'offsetPixels':offset.tolist(),
            'unitsPerPixel':float(1/np.linalg.norm(matrix[0])),
            'reflection':bool(np.linalg.det(matrix)<0),'rmsePixels':float(np.sqrt(np.mean(residual**2))),
            'maxResidualPixels':float(residual.max()),'leaveOneOutPixels':loo,
            'controls':[dict(a,predictedPixel=prediction[i].tolist(),residualPixels=float(residual[i]))
                        for i,a in enumerate(anchors)],'semanticAnchorValidation':'required-separately',
            'metersPerSourceUnitVerified':False}
