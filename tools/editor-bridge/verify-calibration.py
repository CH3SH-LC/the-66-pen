"""Check the actual game export's recursion guard, types and spawn parameters."""
import argparse
import json
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location('inspect_graph', Path(__file__).with_name('inspect-graph.py'))
module = module_from_spec(spec)
spec.loader.exec_module(module)


def verify(path):
    report = module.inspect(path)
    def require(condition, label):
        if not condition:
            raise ValueError(label)
    require(report['name'] == 'MW_Platform_Calibration_20260916', 'Wrong graph')
    definitions = [(n['id'], n['definition']) for n in report['nodes']]
    require(definitions == [(1, 71), (2, 73), (3, 14), (4, 2), (5, 252), (6, 1), (7, 192)], 'Unexpected nodes')
    expected = {
        ((1, 2, 0), (4, 1, 0)), ((1, 4, 0), (3, 3, 0)),
        ((2, 4, 0), (3, 3, 1)), ((3, 4, 0), (4, 3, 0)),
        ((4, 2, 0), (5, 1, 0)), ((5, 2, 0), (6, 1, 0)),
        ((2, 4, 0), (5, 3, 3)), ((7, 4, 0), (5, 3, 1)), ((7, 4, 0), (5, 3, 2))}
    actual = {(tuple(e['source']), tuple(e['target'])) for e in report['directedEdges']}
    require(actual == expected and len(report['directedEdges']) == 9, 'Guard, origin or edges differ')
    equal = report['nodes'][2]
    for pin in equal['pins']:
        value = pin['value']['val_poly']['actual_value']
        require(value['type_def']['server_side']['type_tag'] == 'S_ENTITY', 'Wrong equality type')
    spawn = report['nodes'][4]
    inputs = {p['shell_sig'].get('index', 0): p for p in spawn['pins']
              if p['shell_sig']['kind'] == 'IN_PARAM'}
    prefab = inputs[0]['value']
    require(prefab['type_def']['server_side']['type_tag'] == 'S_PREFAB', 'Wrong prefab type')
    require(prefab['val_id']['id'] == '20001875', 'Wrong prefab ID')
    require(inputs[5]['kernel_sig']['index'] == 7, 'Wrong boolean kernel pin')
    require(inputs[6]['kernel_sig']['index'] == 5, 'Wrong level kernel pin')
    require(inputs[6]['value']['val_int']['int'] == 1, 'Wrong level')
    return {'ok': True, 'graphId': report['graphId'], 'sha256': report['sha256'],
            'guard': 'spawn only when event source equals graph owner',
            'prefabId': 20001875, 'nodeCount': 7, 'edgeCount': 9,
            'positionRotation': 'explicit zero vector node; runtime placement not verified',
            'playtestVerified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(verify(args.path), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
