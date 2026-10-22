"""Build six tiled platforms, reusing the existing calibration cube at the start center."""
import copy
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.proto_gen import gia_graph_pb2 as pb

SOURCE = ROOT / '.runtime/editor-bridge/exports/miliastra-bridge-af8b2da7-b162-4f1a-9c19-fb2dbe085904/bridge-export-d9157a075ac54b66a76db9b3c5028065.gia'
NAME = 'MW_Route_Tiled_20260916'


def build():
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != '9db9b3de770e078ebae2931b9474ac31cf97639b741215596252e4c2101b2145':
        raise ValueError('Calibration source changed')
    scene_bytes = (ROOT / 'mvp/scene.json').read_bytes()
    scene = json.loads(scene_bytes)
    bundle = pb.AssetBundle.FromString(data[20:-4])
    resource = bundle.primary_resource
    graph = resource.graph_data.inner.graph
    resource.internal_name = NAME
    original = {n.index: copy.deepcopy(n) for n in graph.nodes}
    if len(original) != 7:
        raise ValueError('Expected seven-node calibration')
    del graph.nodes[:]
    for index in (1, 2, 3, 4, 6, 7):
        node = graph.nodes.add(); node.CopyFrom(original[index])
        if index == 6:
            for pin in node.pins:
                if pin.value.HasField('val_string'):
                    pin.value.val_string.str = 'MW_ROUTE_TILED_CREATED_20260916'
    tiles = []
    for platform in scene['entities']:
        width = int(platform['scale'][0])
        depth = int(platform['scale'][2])
        if width not in (2, 3) or depth != width:
            raise ValueError('Unsupported platform footprint')
        for x in range(width):
            for z in range(depth):
                dx, dz = x - (width - 1) / 2, z - (depth - 1) / 2
                if platform['index'] == 0 and dx == 0 and dz == 0:
                    continue  # Existing bound calibration graph supplies this cube.
                tiles.append({'platform': platform['index'], 'template_id': platform['template_id'],
                              'position': [platform['position'][0] + dx, platform['position'][1], platform['position'][2] + dz]})
    if len(tiles) != 33:
        raise ValueError('Expected 33 new tiles plus calibration center')
    spawn_ids = [5] + list(range(8, 40))
    for i, entity in enumerate(tiles):
        node = graph.nodes.add(); node.CopyFrom(original[5])
        node.index = spawn_ids[i]
        node.x_pos = 1050 + (i % 6) * 350
        node.y_pos = (i // 6) * 450
        for pin in node.pins:
            if pin.shell_sig.kind == 2:
                pin.connections[0].target_node_index = spawn_ids[i + 1] if i < len(tiles) - 1 else 6
            elif pin.shell_sig.kind == 3 and pin.shell_sig.index == 0:
                pin.value.val_id.id = entity['template_id']
            elif pin.shell_sig.kind == 3 and pin.shell_sig.index == 1:
                del pin.connections[:]
                pin.value.widget = pb.TypedValue.VECTOR_GROUP
                pin.value.is_value_set = 1
                pin.value.type_def.backend = pb.TypeDefinition.SERVER
                pin.value.type_def.server_side.type_tag = 12  # S_VECTOR
                pin.value.val_vector.vec.x, pin.value.val_vector.vec.y, pin.value.val_vector.vec.z = entity['position']
    payload = graph.SerializeToString()
    packed = bundle.SerializeToString()
    out = ROOT / '.runtime/editor-bridge/imports'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'tiled-route.pb').write_bytes(payload)
    (out / 'tiled-route.gia').write_bytes(struct.pack('>5I', len(packed) + 20, 1, 0x326, 3, len(packed)) + packed + struct.pack('>I', 0x679))
    manifest = {'name': NAME, 'payloadSha256': hashlib.sha256(payload).hexdigest(),
                'sceneSha256': hashlib.sha256(scene_bytes).hexdigest(), 'nodeCount': 39,
                'spawnIds': spawn_ids, 'entities': scene['entities'], 'tiles': tiles,
                'requiresCalibrationCenter': True, 'totalRuntimeCubes': 34,
                'nominalCubeSize': 1.0, 'physicalCollisionVerified': False,
                'nominalTopOffsetFromScene': 0.25,
                'scaleApplied': False, 'bindAllowed': True,
                'reason': 'Tiled footprint: 33 cubes plus the existing calibration center; original logical centers and gaps preserved; physical dimensions still require playtest.',
                'playabilityVerified': False}
    (out / 'tiled-route-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('name', 'payloadSha256', 'nodeCount', 'scaleApplied', 'bindAllowed')}))


if __name__ == '__main__':
    build()
