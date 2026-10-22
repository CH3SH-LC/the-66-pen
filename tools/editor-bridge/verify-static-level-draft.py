"""Check the isolated static draft against the saved level and native route export."""
import importlib.util
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.wire import iter_fields, get_bytes_fields, get_varint
from miliastra_agent.parsers.gil import parse_gi_file
from miliastra_agent.core.proto_gen import entity_pb2

SOURCE = ROOT / '.runtime/editor-bridge/static-entity-research/current-level-snapshot/level.gil'
CANDIDATE = ROOT / '.runtime/editor-bridge/static-level-draft/level-static-candidate.gil'
spec = importlib.util.spec_from_file_location('inspect_graph', Path(__file__).with_name('inspect-graph.py'))
inspect_graph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspect_graph)

def payload(path):
    data = path.read_bytes()
    size, version, magic, kind, length = struct.unpack('>5I', data[:20])
    if (size != len(data)-4 or length != len(data)-24 or magic != 806 or kind != 2
            or data[-4:] != struct.pack('>I',1657)):
        raise ValueError('Invalid GIL container')
    return data[20:-4]

def require(ok, message):
    if not ok:
        raise ValueError(message)

def verify(candidate=CANDIDATE):
    require(hashlib.sha256(SOURCE.read_bytes()).hexdigest() ==
            '6651107185a50fc46c22cd3daf5dccfdbebbc29bd6acfce9003752df1de5e3db', 'Saved source changed')
    before, after = payload(SOURCE), payload(candidate)
    original, draft = parse_gi_file(SOURCE), parse_gi_file(candidate)
    keep = lambda p: [(n,w,v) for n,w,v in iter_fields(p) if n not in (5,27)]
    require(keep(before) == keep(after), 'Unrelated root sections changed')
    require(original.node_graphs == draft.node_graphs, 'Graph definitions changed')
    expected_bindings = [b for b in original.entity_graph_bindings if b.graph_id not in (1073741825,1073741826)]
    require(draft.entity_graph_bindings == expected_bindings, 'Unexpected bindings')
    require(len(draft.entities) == len(original.entities)+34, 'Expected 34 new placements')
    original_ids = {e.entity_id for e in original.entities}
    require([e for e in draft.entities if e.entity_id in original_ids] == original.entities, 'Existing entity placements changed')
    added = [e for e in draft.entities if e.entity_id not in original_ids]
    require(len({e.entity_id for e in draft.entities}) == len(draft.entities), 'Duplicate entity ids')
    require(len(added) == 34 and len({e.name.split('_Tile')[0] for e in added}) == 6, 'Expected six named platforms')
    actual = Counter()
    for e in added:
        require((e.scale.x,e.scale.y,e.scale.z) == (1,1,1), 'Changed unit cube scale')
        require((e.rotation.x,e.rotation.y,e.rotation.z) == (0,0,0), 'Unexpected rotation')
        actual[(e.template_id, *(round(v,4) for v in (e.position.x,e.position.y,e.position.z)))] += 1
    # Independent geometry source: real native export, not the builder manifest.
    route = inspect_graph.inspect(ROOT / '.runtime/editor-bridge/runs/96af4d80-a640-43bd-8503-233de56e5095/course-backup/tiled.gia')
    require(route['sha256'] == 'f799dcdd52482c7b67b6bcfbcc3f5bb30d9308ad440bd95da5f86cc4dd95eb38', 'Native route source changed')
    expected = Counter({(20001875,0.0,0.0,0.0):1})  # verified calibration center
    for n in route['nodes']:
        if n['definition'] != 252:
            continue
        pins = {p['shell_sig'].get('index',0):p for p in n['pins'] if p['shell_sig']['kind']=='IN_PARAM'}
        vec = pins[1]['value']['val_vector']['vec']
        expected[(int(pins[0]['value']['val_id']['id']), *(round(vec.get(k,0),4) for k in ('x','y','z')))] += 1
    require(sum(expected.values()) == 34 and actual == expected, 'Static geometry differs from native runtime course')
    for block in get_bytes_fields(after,27):
        for item in get_bytes_fields(block,1):
            props = [entity_pb2.Property.FromString(p) for p in get_bytes_fields(item,4)]
            require(len(props)==1 and props[0].name.static_block==1, 'Missing static unit flag')
    # Existing logic entities must remain byte-identical except the level binding component.
    old_entities = [v for c in get_bytes_fields(before,5) for v in get_bytes_fields(c,1)]
    new_entities = [v for c in get_bytes_fields(after,5) for v in get_bytes_fields(c,1)]
    require(len(old_entities)==len(new_entities), 'Logic entity count changed')
    for old,new in zip(old_entities,new_entities):
        require(get_varint(old,1)==get_varint(new,1), 'Logic entity order changed')
        if get_varint(old,1)!=1094713345:
            require(old==new, 'Unrelated logic entity bytes changed')
        else:
            non_binding = lambda p: [(n,w,v) for n,w,v in iter_fields(p)
                if not(n==6 and w==2 and get_varint(v,1)==3)]
            require(non_binding(old)==non_binding(new), 'Unrelated level components changed')
    return {'ok':True,'staticPlacements':34,'platforms':6,'geometryMatchesNativeExport':True,
            'originalGraphsPreserved':True,'runtimeSpawnBindingsRemoved':True,
            'gameAccepted':False,'deploymentAllowed':False}

if __name__=='__main__':
    result=verify(Path(sys.argv[1]) if len(sys.argv)>1 else CANDIDATE)
    print(json.dumps(result,indent=2))
