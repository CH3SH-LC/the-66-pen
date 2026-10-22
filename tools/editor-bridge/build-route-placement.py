"""Derive an UNBOUND six-position test graph from the verified calibration export."""
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
NAME = 'MW_Route_Placement_20260916'


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
                    pin.value.val_string.str = 'MW_ROUTE_PLACEMENT_CREATED_20260916'
    spawn_ids = [5, 8, 9, 10, 11, 12]
    for i, entity in enumerate(scene['entities']):
        node = graph.nodes.add(); node.CopyFrom(original[5])
        node.index = spawn_ids[i]
        node.x_pos = 1050 + i * 350
        for pin in node.pins:
            if pin.shell_sig.kind == 2:
                pin.connections[0].target_node_index = spawn_ids[i + 1] if i < 5 else 6
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
    (out / 'route-placement.pb').write_bytes(payload)
    (out / 'route-placement.gia').write_bytes(struct.pack('>5I', len(packed) + 20, 1, 0x326, 3, len(packed)) + packed + struct.pack('>I', 0x679))
    manifest = {'name': NAME, 'payloadSha256': hashlib.sha256(payload).hexdigest(),
                'sceneSha256': hashlib.sha256(scene_bytes).hexdigest(), 'nodeCount': 12,
                'spawnIds': spawn_ids, 'entities': scene['entities'],
                'scaleApplied': False, 'bindAllowed': False,
                'reason': 'Native create-prefab node has no scale input; validate positioning before route activation.',
                'playabilityVerified': False}
    (out / 'route-placement-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('name', 'payloadSha256', 'nodeCount', 'scaleApplied', 'bindAllowed')}))


if __name__ == '__main__':
    build()
