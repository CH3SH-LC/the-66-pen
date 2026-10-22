"""Check real exported placement data against the six-entity scene, without claiming scale or playability."""
import argparse
import json
import math
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('graph_inspector', Path(__file__).with_name('inspect-graph.py'))
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)


def verify(path):
    report = inspector.inspect(path)
    scene = json.loads((Path(__file__).resolve().parents[2] / 'mvp/scene.json').read_text(encoding='utf-8-sig'))
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    require(report['name'] == 'MW_Route_Placement_20260916', 'Unexpected graph name')
    require(report['nodeCount'] == 12, 'Unexpected node count')
    nodes = {n['id']: n for n in report['nodes']}
    ids = [5, 8, 9, 10, 11, 12]
    expected = {(1, 2, 0, 4, 1, 0), (1, 4, 0, 3, 3, 0), (2, 4, 0, 3, 3, 1),
                (3, 4, 0, 4, 3, 0), (4, 2, 0, 5, 1, 0)}
    for id, definition in {1: 71, 2: 73, 3: 14, 4: 2, 6: 1, 7: 192}.items():
        require(nodes[id]['definition'] == definition, 'Guard or output node changed')
    for pin in nodes[3]['pins']:
        require(pin['value']['val_poly']['actual_value']['type_def']['server_side']['type_tag'] == 'S_ENTITY', 'Wrong equality type')
    for i, (id, entity) in enumerate(zip(ids, scene['entities'])):
        node = nodes[id]
        require(node['definition'] == 252, 'Not a create-prefab node')
        pins = {p['shell_sig'].get('index', 0): p for p in node['pins'] if p['shell_sig']['kind'] == 'IN_PARAM'}
        require(int(pins[0]['value']['val_id']['id']) == entity['template_id'], 'Wrong prefab')
        require(pins[1]['value']['type_def']['server_side']['type_tag'] == 'S_VECTOR', 'Position lost vector type')
        xyz = pins[1]['value']['val_vector'].get('vec', {})
        require(all(math.isclose(xyz.get(axis, 0), v, abs_tol=1e-5) for axis, v in zip(('x', 'y', 'z'), entity['position'])), 'Position changed')
        require(pins[6]['value']['val_int']['int'] == 1 and pins[6]['kernel_sig']['index'] == 5, 'Level changed')
        require(pins[5]['kernel_sig']['index'] == 7 and pins[5]['value']['val_enum'].get('enum', 0) == 0, 'Create mode changed')
        expected.update({(id, 2, 0, ids[i+1] if i < 5 else 6, 1, 0), (7, 4, 0, id, 3, 2), (2, 4, 0, id, 3, 3)})
    edges = {tuple(e['source'] + e['target']) for e in report['directedEdges']}
    require(edges == expected and len(report['directedEdges']) == 23, 'Guard, spawn ordering or ownership edges changed')
    require(nodes[6]['strings'] == ['MW_ROUTE_PLACEMENT_CREATED_20260916'], 'Missing completion marker')
    return {'ok': True, 'graphId': report['graphId'], 'sha256': report['sha256'], 'nodeCount': 12,
            'spawnCount': 6, 'edgeCount': len(edges), 'positionsAndPrefabsMatchScene': True,
            'scaleApplied': False, 'bindAllowed': False, 'playabilityVerified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(verify(args.path), indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
