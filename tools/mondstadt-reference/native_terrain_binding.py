"""Read Terrain -> TerrainData dependencies and separate prefab from placement.

The Terrain prefix follows the locked 2017.4 type tree. Collider custom bytes are
not guessed: its matching exact PPtr occurrence is independently recorded.
Prefab identity roots do not establish the runtime scene placement.
"""
import struct
import numpy as np
from serialized_reference import Reader
from native_mesh_reference import resolve_local_hierarchy
from reference_cli import digest
from regional_registration import read,relative


def terrain_bindings(node_dir):
    meta=read(node_dir/'metadata.json');source=read(node_dir/'source.json');data=(node_dir/'node.bin').read_bytes()
    if digest(node_dir/'node.bin')!=source['nodeSha256']:raise ValueError('Source node changed')
    objects={o['pathId']:o for o in meta['objects']};transforms={r['gameObject']['pathId']:r for r in resolve_local_hierarchy(meta)};out=[]
    for obj in meta['objects']:
        if obj['classId']!=218:continue
        payload=data[obj['offset']:obj['offset']+obj['size']];r=Reader(payload,meta['endian']);go=r.ptr();enabled=r.read('B');r.align();ptr=r.ptr()
        cab=source['nodePath'] if ptr['fileId']==0 else meta['externals'][ptr['fileId']-1]['path'].replace('\\','/').split('/')[-1]
        name=objects[go['pathId']]['identity']['name'];colliders=[]
        for co in meta['objects']:
            if co['classId']!=154:continue
            raw=data[co['offset']:co['offset']+co['size']];cr=Reader(raw,meta['endian'])
            if cr.ptr()!=go:continue
            encoded=struct.pack(meta['endian']+'iq',ptr['fileId'],ptr['pathId']);offsets=[i for i in range(len(raw)-len(encoded)+1) if raw[i:i+len(encoded)]==encoded]
            colliders.append({'pathId':co['pathId'],'matchingTerrainDataPPtrByteOffsets':offsets,'customColliderLayoutNotFullyParsed':True})
        t=transforms.get(go['pathId']);matrix=t.get('nativeMatrixColumnVector') if t else None
        out.append({'name':name,'terrainPathId':obj['pathId'],'gameObject':go,'terrainEnabled':bool(enabled),'terrainDataPPtr':ptr,'terrainDataCab':cab.lower(),
            'terrainPrefixParsedBytes':r.p,'terrainSuffixUnparsedBytes':len(payload)-r.p,'colliders':colliders,'prefabTransform':t,
            'prefabRootIsIdentity':bool(matrix is not None and np.allclose(matrix,np.eye(4))),
            'runtimeScenePlacementResolved':False,'placementWarning':'Prefab root coordinates are not an instantiation matrix; world placement must be separately evidenced.',
            'sourceNode':relative(node_dir),'sourceNodeSha256':source['nodeSha256']})
    return out
