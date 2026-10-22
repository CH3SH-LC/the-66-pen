"""Read-only check of a real tiled-route GIA export against mvp/scene.json.

The expected 33-tile layout is recomputed here from the scene file alone, so this
verifier does not share the generator's arithmetic. Tiling is NOMINAL: every tile
is a unit cube whose centre sits on the same Y as its logical platform centre, so
the top face rises 0.25 above the original 0.5-thick platform. That offset is
uniform across all tiles, leaving every step height unchanged. Nothing here
proves physical collision or playability.
"""
from __future__ import annotations

import argparse
import json
import math
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

spec = spec_from_file_location('graph_inspector', Path(__file__).with_name('inspect-graph.py'))
inspector = module_from_spec(spec)
spec.loader.exec_module(inspector)

GRAPH_NAME = 'MW_Route_Tiled_20260916'
COMPLETION_MARKER = 'MW_ROUTE_TILED_CREATED_20260916'
CREATE_DEFINITION = 252
STATIC_NODES = {1: 71, 2: 73, 3: 14, 4: 2, 6: 1, 7: 192}
CREATE_NODE_IDS = [5] + list(range(8, 40))
STATIC_EDGES = {
    ((1, 2, 0), (4, 1, 0)),   # event flow -> branch
    ((1, 4, 0), (3, 3, 0)),   # event source entity -> equality
    ((2, 4, 0), (3, 3, 1)),   # graph owner -> equality
    ((3, 4, 0), (4, 3, 0)),   # equality result -> branch condition
    ((4, 2, 0), (5, 1, 0)),   # branch true -> first create
}
TOLERANCE = 1e-5


def axis_offsets(extent):
    """Tile-centre offsets across a unit-cube span: range(n) - (n-1)/2."""
    count = int(round(float(extent)))
    if count < 1:
        raise ValueError(f'Invalid footprint extent {extent!r}')
    return [i - (count - 1) / 2.0 for i in range(count)]


def expected_tiles(scene):
    """(created tiles, nominal cube count). Platform order, X outer, Z inner.

    The start platform's (0, 0) offset is skipped: that centre cube is the one
    already created by the bound calibration graph.
    """
    centres = []
    for entity in scene['entities']:
        for dx in axis_offsets(entity['scale'][0]):
            for dz in axis_offsets(entity['scale'][2]):
                if entity.get('role') == 'start' and dx == 0.0 and dz == 0.0:
                    continue
                centres.append({
                    'templateId': entity['template_id'],
                    'centre': (entity['position'][0] + dx,
                               entity['position'][1],
                               entity['position'][2] + dz)})
    if len(centres) != len(CREATE_NODE_IDS):
        raise ValueError(f'Scene layout yields {len(centres)} tiles, not {len(CREATE_NODE_IDS)}')
    tiles = []
    for node_id, centre in zip(CREATE_NODE_IDS, centres):
        tiles.append({'nodeId': node_id, 'templateId': centre['templateId'],
                      'centre': centre['centre']})
    total = sum(int(round(float(e['scale'][0]))) * int(round(float(e['scale'][2])))
                for e in scene['entities'])
    return tiles, total


def verify(path):
    report = inspector.inspect(path)
    scene = json.loads(
        (Path(__file__).resolve().parents[2] / 'mvp/scene.json').read_text(encoding='utf-8-sig'))
    tiles, nominal_cubes = expected_tiles(scene)

    def require(ok, message):
        if not ok:
            raise ValueError(message)

    require(report['name'] == GRAPH_NAME, 'Unexpected graph name')
    require(report['nodeCount'] == 39, 'Unexpected node count')
    nodes = {n['id']: n for n in report['nodes']}
    require(len(nodes) == report['nodeCount'], 'Duplicate node IDs')
    require(set(nodes) == set(STATIC_NODES) | set(CREATE_NODE_IDS), 'Extra or missing nodes')
    for node_id, definition in STATIC_NODES.items():
        require(nodes[node_id]['definition'] == definition, f'Node {node_id} definition changed')
    require(nominal_cubes == 34, 'Nominal footprint is not 34 unit cubes')

    require(len(nodes[3]['pins']) == 2, 'Equality input missing or duplicated')
    for pin in nodes[3]['pins']:
        value = pin['value']['val_poly']['actual_value']
        require(value['type_def']['server_side']['type_tag'] == 'S_ENTITY',
                'Equality node no longer compares entity types')

    seen = {}
    actual_centres = []
    for tile in tiles:
        node_id = tile['nodeId']
        node = nodes[node_id]
        require(node['definition'] == CREATE_DEFINITION, f'Node {node_id} is not a create-prefab node')
        inputs = {p['shell_sig'].get('index', 0): p for p in node['pins']
                  if p['shell_sig']['kind'] == 'IN_PARAM'}
        require(inputs[0]['value']['type_def']['server_side']['type_tag'] == 'S_PREFAB', 'Wrong prefab type')
        require(inputs[5]['value']['type_def']['server_side']['type_tag'] == 'S_BOOL', 'Wrong boolean type')
        require(int(inputs[0]['value']['val_id']['id']) == tile['templateId'],
                f'Node {node_id} prefab does not match the scene template')
        position = inputs[1]
        require(not position.get('connections'), f'Node {node_id} position is still driven by a node')
        require(position['value']['type_def']['server_side']['type_tag'] == 'S_VECTOR',
                f'Node {node_id} position lost its vector type')
        vec = position['value']['val_vector'].get('vec', {})
        actual = tuple(float(vec.get(axis, 0.0)) for axis in ('x', 'y', 'z'))
        actual_centres.append(actual)
        require(all(math.isclose(a, e, abs_tol=TOLERANCE)
                    for a, e in zip(actual, tile['centre'])),
                f'Node {node_id} position {actual} != expected {tile["centre"]}')
        key = tuple(round(v / TOLERANCE) for v in actual)
        require(key not in seen, f'Node {node_id} duplicates the position of node {seen.get(key)}')
        seen[key] = node_id
        require(inputs[6]['kernel_sig']['index'] == 5 and inputs[6]['value']['val_int']['int'] == 1,
                f'Node {node_id} level changed')
        require(inputs[5]['kernel_sig']['index'] == 7
                and inputs[5]['value']['val_enum'].get('enum', 0) == 0,
                f'Node {node_id} boolean create mode changed')

    expected = set(STATIC_EDGES)
    for index, tile in enumerate(tiles):
        node_id = tile['nodeId']
        following = tiles[index + 1]['nodeId'] if index + 1 < len(tiles) else 6
        expected.add(((node_id, 2, 0), (following, 1, 0)))
        expected.add(((7, 4, 0), (node_id, 3, 2)))
        expected.add(((2, 4, 0), (node_id, 3, 3)))
    require(len(expected) == 104, 'Expected edge budget is not 104')
    edges = {(tuple(e['source']), tuple(e['target'])) for e in report['directedEdges']}
    require(len(report['directedEdges']) == 104, 'Unexpected directed edge count')
    require(edges == expected, 'Guard, spawn ordering or ownership edges changed')

    require(nodes[6]['strings'] == [COMPLETION_MARKER], 'Missing completion marker')
    require(all(not n['strings'] for i, n in nodes.items() if i != 6),
            'Unexpected string literal on another node')

    # Report geometry from the exported positions, not the static asset's
    # 0.5-high scale. The calibration centre is a required external dependency.
    centres = actual_centres + [(0.0, 0.0, 0.0)]
    heights = sorted(set(round(p[1], 5) for p in centres))
    platforms = []
    for height in heights:
        group = [p for p in centres if abs(p[1] - height) < TOLERANCE]
        xs = sorted(set(round(p[0], 5) for p in group))
        zs = sorted(set(round(p[2], 5) for p in group))
        require(len(group) == len(xs) * len(zs), 'Nominal platform has a missing tile')
        require(all(math.isclose(b-a, 1.0, abs_tol=TOLERANCE)
                    for axis in (xs, zs) for a, b in zip(axis, axis[1:])),
                'Nominal tiles do not meet edge to edge')
        platforms.append({'tileCount': len(group),
                          'xBounds': [xs[0]-0.5, xs[-1]+0.5],
                          'zBounds': [zs[0]-0.5, zs[-1]+0.5],
                          'nominalTopY': round(height+0.5, 5)})
    jumps = [{'edgeGap': round(b['xBounds'][0]-a['xBounds'][1], 5),
              'rise': round(b['nominalTopY']-a['nominalTopY'], 5)}
             for a, b in zip(platforms, platforms[1:])]

    return {'ok': True, 'graphId': report['graphId'], 'sha256': report['sha256'],
            'graphName': report['name'], 'nodeCount': report['nodeCount'],
            'logicalPlatforms': len(scene['entities']),
            'nominalCubeCount': nominal_cubes, 'createdCubeCount': len(tiles),
            'edgeCount': len(report['directedEdges']), 'expectedEdgeCount': len(expected),
            'skippedCentreTile': 'start (0,0) left to the bound calibration graph',
            'positionsAndPrefabsMatchScene': True, 'completionMarker': COMPLETION_MARKER,
            'scaleApplied': False, 'tiledFootprintNominal': True,
            'nominalGeometry': {'assumedCubeSide': 1.0,
                                'calibrationCentreAssumedPresent': True,
                                'platforms': platforms, 'jumps': jumps,
                                'collisionMeasured': False},
            'requiresCalibrationCenter': True, 'physicalCollisionVerified': False,
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
