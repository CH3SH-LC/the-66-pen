"""Statically validate the unbound MW_Runtime_Count_Audit_20260916 graph export.

This is file-content validation only. The audit graph is re-derived from the
exported .gia bytes (via inspect-graph.py) and compared against its design:
the event source/owner guard, the one-shot timer on the owner, the timer-name
match, and the prefab-entity count print chain. Passing here is NOT runtime
verification -- no in-game behaviour is proven by it.

--self-test runs the primary tests: the pristine export must pass and every
single-field mutation of it must be rejected with ValueError.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import tempfile
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

_spec = spec_from_file_location('inspect_graph', Path(__file__).with_name('inspect-graph.py'))
inspect_graph = module_from_spec(_spec)
_spec.loader.exec_module(inspect_graph)

GRAPH_NAME = 'MW_Runtime_Count_Audit_20260916'
TIMER_NAME = 'MW_AUDIT_ONESHOT_20260916'
MARKER = 'MW_AUDIT_GLOBAL_PREFAB_20001875_COUNT_NEXT'
PREFAB_ID = 20001875

# ServerTypeId and PinSignature.Kind values from gia_graph.proto.
S_ENTITY, S_INT, S_BOOL, S_STRING, S_FLOAT, S_FLOAT_LIST = 1, 3, 4, 6, 5, 10
S_ENTITY_LIST, S_PREFAB = 13, 21
IN_FLOW, OUT_FLOW, IN_PARAM, OUT_PARAM = 1, 2, 3, 4

# Node index -> shell definition id, exactly as designed for the audit graph.
DEFINITIONS = {1: 71, 2: 73, 3: 14, 4: 2, 5: 79, 6: 83, 7: 14,
               8: 2, 9: 320, 10: 142, 11: 180, 12: 1, 13: 1}

# Every directed edge of the audit graph as (source pin, target pin).
EXPECTED_EDGES = {
    ((1, OUT_FLOW, 0), (4, IN_FLOW, 0)), ((1, OUT_PARAM, 0), (3, IN_PARAM, 0)),
    ((2, OUT_PARAM, 0), (3, IN_PARAM, 1)), ((2, OUT_PARAM, 0), (5, IN_PARAM, 0)),
    ((3, OUT_PARAM, 0), (4, IN_PARAM, 0)), ((4, OUT_FLOW, 0), (5, IN_FLOW, 0)),
    ((6, OUT_FLOW, 0), (8, IN_FLOW, 0)), ((6, OUT_PARAM, 2), (7, IN_PARAM, 0)),
    ((7, OUT_PARAM, 0), (8, IN_PARAM, 0)), ((8, OUT_FLOW, 0), (12, IN_FLOW, 0)),
    ((9, OUT_PARAM, 0), (10, IN_PARAM, 0)), ((10, OUT_PARAM, 0), (11, IN_PARAM, 0)),
    ((11, OUT_PARAM, 0), (13, IN_PARAM, 0)), ((12, OUT_FLOW, 0), (13, IN_FLOW, 0))}


def _require(condition, label):
    if not condition:
        raise ValueError(label)


def _single(nodes, definition, label):
    matches = [n for n in nodes if n['definition'] == definition]
    _require(len(matches) == 1,
             'Expected exactly one %s node, found %d' % (label, len(matches)))
    return matches[0]


def _pins(node, kind):
    return {p['shell_sig'].get('index', 0): p for p in node['pins']
            if p['shell_sig']['kind'] == kind}


def _actual(pin):
    """The value object a pin actually carries, unwrapping the type selector."""
    value = pin.get('value')
    if not value:
        return {}
    return value['val_poly']['actual_value'] if 'val_poly' in value else value


def _type_tag(pin):
    return _actual(pin).get('type_def', {}).get('server_side', {}).get('type_tag')


def _literal(pin):
    return _actual(pin).get('val_string', {}).get('str', '')


def _sources(edges, target):
    return {source for source, dest in edges if dest == target}


def _require_source(edges, target, source, label):
    found = _sources(edges, target)
    _require(found == {source}, '%s: expected %s, found %s' % (label, source, sorted(found)))


def verify(path):
    """Validate the audit export. Raises ValueError on any discrepancy."""
    report = inspect_graph.inspect(path)

    _require(report['name'] == GRAPH_NAME, 'Wrong graph name: %r' % (report['name'],))
    nodes = report['nodes']
    actual_definitions = {n['id']: n['definition'] for n in nodes}
    _require(actual_definitions == DEFINITIONS,
             'Unexpected node definitions: %r' % (actual_definitions,))
    _require(report['nodeCount'] == len(DEFINITIONS), 'Unexpected node count')
    _require(isinstance(report['graphId'], int) and report['graphId'] > 0, 'Missing graph id')

    edges = {(tuple(e['source']), tuple(e['target'])) for e in report['directedEdges']}

    # Roles are derived from the structure, not assumed from node indices.
    event = _single(nodes, 71, 'event')
    owner = _single(nodes, 73, 'owner')
    timer = _single(nodes, 79, 'one-shot timer')
    timer_event = _single(nodes, 83, 'timer event')
    query = _single(nodes, 320, 'prefab query')
    length = _single(nodes, 142, 'length')
    to_text = _single(nodes, 180, 'int to string')
    equalities = [n for n in nodes if n['definition'] == 14]
    branches = [n for n in nodes if n['definition'] == 2]
    prints = [n for n in nodes if n['definition'] == 1]
    _require(len(equalities) == 2 and len(branches) == 2 and len(prints) == 2,
             'Unexpected node roles: %d equalities, %d branches, %d prints'
             % (len(equalities), len(branches), len(prints)))

    # Guard: the event source must equal the graph owner, both side S_ENTITY.
    owner_equality = [n for n in equalities
                      if (event['id'], OUT_PARAM, 0) in _sources(edges, (n['id'], IN_PARAM, 0))]
    _require(len(owner_equality) == 1, 'No equality node consumes the event source')
    owner_equality = owner_equality[0]
    owner_inputs = _pins(owner_equality, 'IN_PARAM')
    _require(set(owner_inputs) == {0, 1}, 'Owner equality must have exactly two inputs')
    _require_source(edges, (owner_equality['id'], IN_PARAM, 0), (event['id'], OUT_PARAM, 0),
                    'Event source must feed the owner equality')
    _require_source(edges, (owner_equality['id'], IN_PARAM, 1), (owner['id'], OUT_PARAM, 0),
                    'Graph owner must feed the owner equality')
    for index, pin in sorted(owner_inputs.items()):
        _require(pin.get('type') == S_ENTITY and _type_tag(pin) == 'S_ENTITY',
                 'Owner equality input %d must be S_ENTITY' % index)

    # Only the true branch of that guard starts the one-shot timer on the owner.
    owner_branch = [n for n in branches
                    if (owner_equality['id'], OUT_PARAM, 0) in _sources(edges, (n['id'], IN_PARAM, 0))]
    _require(len(owner_branch) == 1, 'No branch consumes the owner equality')
    owner_branch = owner_branch[0]
    _require_source(edges, (owner_branch['id'], IN_PARAM, 0), (owner_equality['id'], OUT_PARAM, 0),
                    'Owner equality must drive the branch condition')
    _require_source(edges, (owner_branch['id'], IN_FLOW, 0), (event['id'], OUT_FLOW, 0),
                    'Event flow must enter the branch')
    _require_source(edges, (timer['id'], IN_FLOW, 0), (owner_branch['id'], OUT_FLOW, 0),
                    'Branch true flow must start the timer')
    _require_source(edges, (timer['id'], IN_PARAM, 0), (owner['id'], OUT_PARAM, 0),
                    'Timer must be started on the graph owner')

    # One-shot: named timer, loop off by default, exactly one float interval.
    timer_inputs = _pins(timer, 'IN_PARAM')
    _require(set(timer_inputs) == {0, 1, 2, 3},
             'Unexpected timer inputs: %r' % (sorted(timer_inputs),))
    _require(timer_inputs[0].get('type') == S_ENTITY, 'Timer owner input must be an entity')
    name_pin, loop_pin, interval_pin = timer_inputs[1], timer_inputs[2], timer_inputs[3]
    _require(name_pin.get('type') == S_STRING and _type_tag(name_pin) == 'S_STRING'
             and _literal(name_pin) == TIMER_NAME, 'Timer name must be %r' % TIMER_NAME)
    _require(loop_pin.get('type') == S_BOOL and loop_pin['value'].get('val_enum') == {},
             'Timer loop flag must be the default zero (no loop)')
    _require(interval_pin.get('type') == S_FLOAT_LIST and _type_tag(interval_pin) == 'S_FLOAT_LIST',
             'Timer interval must be typed S_FLOAT_LIST')
    elements = interval_pin['value']['val_list']['elements']
    _require(len(elements) == 1 and elements[0].get('type_def', {}).get('server_side', {}).get('type_tag') == 'S_FLOAT'
             and float(elements[0]['val_float']['float']) == 1.0,
             'Timer interval must be exactly [1.0]')

    # The timer event fires again only when its name matches the registered name.
    name_equality = [n for n in equalities
                     if (timer_event['id'], OUT_PARAM, 2) in _sources(edges, (n['id'], IN_PARAM, 0))]
    _require(len(name_equality) == 1, 'No equality node consumes the timer name')
    name_equality = name_equality[0]
    _require_source(edges, (name_equality['id'], IN_PARAM, 0), (timer_event['id'], OUT_PARAM, 2),
                    'Timer event name must feed the name equality')
    name_inputs = _pins(name_equality, 'IN_PARAM')
    _require(set(name_inputs) == {0, 1}, 'Name equality must have exactly two inputs')
    for index, pin in sorted(name_inputs.items()):
        _require(pin.get('type') == S_STRING and _type_tag(pin) == 'S_STRING',
                 'Name equality input %d must be S_STRING' % index)
    _require(_literal(name_inputs[0]) == '',
             'Timer name equality input must be wired, not a literal')
    _require(_literal(name_inputs[1]) == _literal(name_pin),
             'Timer name literal must equal the registered timer name')

    name_branch = [n for n in branches
                   if (name_equality['id'], OUT_PARAM, 0) in _sources(edges, (n['id'], IN_PARAM, 0))]
    _require(len(name_branch) == 1, 'No branch consumes the timer name equality')
    name_branch = name_branch[0]
    _require_source(edges, (name_branch['id'], IN_PARAM, 0), (name_equality['id'], OUT_PARAM, 0),
                    'Name equality must drive the branch condition')
    _require_source(edges, (name_branch['id'], IN_FLOW, 0), (timer_event['id'], OUT_FLOW, 0),
                    'Timer event flow must enter the name branch')

    # True branch: print a marker, then print the count downstream of it.
    marker_print = [n for n in prints
                    if _sources(edges, (n['id'], IN_FLOW, 0)) == {(name_branch['id'], OUT_FLOW, 0)}]
    _require(len(marker_print) == 1, 'No print node follows the name branch')
    marker_print = marker_print[0]
    marker_inputs = _pins(marker_print, 'IN_PARAM')
    _require(set(marker_inputs) == {0}, 'Marker print must have exactly one input')
    _require(marker_inputs[0].get('type') == S_STRING
             and _type_tag(marker_inputs[0]) == 'S_STRING'
             and _literal(marker_inputs[0]) == MARKER, 'Marker print must print %r' % MARKER)

    # Count chain: prefab query -> entity list length -> int -> string -> print.
    query_inputs = _pins(query, 'IN_PARAM')
    _require(set(query_inputs) == {0}, 'Query must have exactly one input')
    _require(query_inputs[0].get('type') == S_PREFAB and _type_tag(query_inputs[0]) == 'S_PREFAB'
             and int(_actual(query_inputs[0])['val_id']['id']) == PREFAB_ID,
             'Query must select prefab %d' % PREFAB_ID)
    _require_source(edges, (length['id'], IN_PARAM, 0), (query['id'], OUT_PARAM, 0),
                    'Query must feed the length node')
    _require(_type_tag(_pins(length, 'IN_PARAM')[0]) == 'S_ENTITY_LIST',
             'Length input must be the queried S_ENTITY_LIST')
    _require_source(edges, (to_text['id'], IN_PARAM, 0), (length['id'], OUT_PARAM, 0),
                    'Length must feed the conversion')
    _require(_type_tag(_pins(to_text, 'IN_PARAM')[0]) == 'S_INT', 'Conversion input must be S_INT')
    _require(_type_tag(_pins(to_text, 'OUT_PARAM')[0]) == 'S_STRING',
             'Conversion output must be S_STRING')
    count_print = [n for n in prints
                   if _sources(edges, (n['id'], IN_PARAM, 0)) == {(to_text['id'], OUT_PARAM, 0)}]
    _require(len(count_print) == 1, 'No print node consumes the converted count')
    count_print = count_print[0]
    _require(count_print['id'] != marker_print['id'],
             'Marker and count prints must be distinct nodes')
    count_inputs = _pins(count_print, 'IN_PARAM')
    _require(set(count_inputs) == {0}, 'Count print must have exactly one input')
    _require(count_inputs[0].get('type') == S_STRING and _literal(count_inputs[0]) == '',
             'Count print must print the wired string')
    _require_source(edges, (count_print['id'], IN_FLOW, 0), (marker_print['id'], OUT_FLOW, 0),
                    'Marker print must flow into the count print')

    _require(len(report['directedEdges']) == len(EXPECTED_EDGES) and edges == EXPECTED_EDGES,
             'Edges differ from the audit graph: %r' % (sorted(edges),))

    return {'ok': True, 'name': report['name'], 'graphId': report['graphId'],
            'sha256': report['sha256'], 'nodeCount': report['nodeCount'],
            'edgeCount': len(report['directedEdges']),
            'globalPrefabCountOnly': True, 'runtimeVerified': False}


# --- mutation tests: every single-field change must be rejected -------------

def _schema_path():
    return (Path(__file__).resolve().parents[2]
            / 'third_party/auto-miliastra/src')


def _pb():
    path = str(_schema_path())
    if path not in sys.path:
        sys.path.insert(0, path)
    from miliastra_agent.core.proto_gen import gia_graph_pb2
    return gia_graph_pb2


def _read_container(path):
    data = Path(path).read_bytes()
    fields = struct.unpack('>5I', data[:20])
    return fields, struct.unpack('>I', data[-4:])[0], data[20:-4]


def _write_container(path, fields, trailer, payload):
    _, version, magic, kind, _ = fields
    _require(magic == 0x326 and kind == 3 and trailer == 0x679,
             'Unexpected container header in the fixture')
    size = 20 + len(payload)
    Path(path).write_bytes(struct.pack('>5I', size, version, magic, kind, len(payload))
                           + payload + struct.pack('>I', trailer))


def _g(bundle):
    return bundle.primary_resource.graph_data.inner.graph


def _n(bundle, index):
    for node in _g(bundle).nodes:
        if node.index == index:
            return node
    raise ValueError('fixture has no node %d' % index)


def _p(bundle, node_index, kind, pin_index):
    for pin in _n(bundle, node_index).pins:
        if pin.shell_sig.kind == kind and pin.shell_sig.index == pin_index:
            return pin
    raise ValueError('fixture has no pin %d on node %d' % (pin_index, node_index))


def _add_extra_node(bundle):
    extra = _g(bundle).nodes.add()
    extra.index = 14
    extra.shell_ref.runtime_id = 71


def _add_extra_edge(bundle):
    connection = _p(bundle, 12, OUT_FLOW, 0).connections.add()
    connection.target_node_index = 5
    connection.target_pin_shell.kind = IN_FLOW
    connection.target_pin_shell.index = 0


def _mutation_cases():
    """(name, mutate, expected error fragment): each case must be rejected."""
    return [
        ('rename the graph',
         lambda b: setattr(b.primary_resource, 'internal_name', 'MW_Other'),
         'Wrong graph name'),
        ('retarget a node definition',
         lambda b: setattr(_n(b, 4).shell_ref, 'runtime_id', 3),
         'node definitions'),
        ('add an extra node', _add_extra_node, 'node definitions'),
        ('drop the event flow edge',
         lambda b: _p(b, 1, OUT_FLOW, 0).ClearField('connections'),
         'Event flow must enter the branch'),
        ('retarget the branch true flow',
         lambda b: setattr(_p(b, 4, OUT_FLOW, 0).connections[0], 'target_node_index', 8),
         'must start the timer'),
        ('add an extra edge', _add_extra_edge, 'must start the timer'),
        ('enable timer loop',
         lambda b: setattr(_p(b, 5, IN_PARAM, 2).value.val_enum, 'enum', 1),
         'loop flag'),
        ('change the timer interval',
         lambda b: setattr(_p(b, 5, IN_PARAM, 3).value.val_list.elements[0].val_float, 'float', 2.0),
         'exactly [1.0]'),
        ('append a second timer interval',
         lambda b: _p(b, 5, IN_PARAM, 3).value.val_list.elements.add(),
         'exactly [1.0]'),
        ('rename the timer',
         lambda b: setattr(_p(b, 5, IN_PARAM, 1).value.val_string, 'str', 'MW_Other'),
         'Timer name must be'),
        ('retarget the timer owner',
         lambda b: setattr(_p(b, 5, IN_PARAM, 0).connections[0], 'target_node_index', 1),
         'started on the graph owner'),
        ('make one owner equality input non-entity',
         lambda b: setattr(_p(b, 3, IN_PARAM, 1).value.val_poly.actual_value.type_def.server_side,
                           'type_tag', S_INT),
         'must be S_ENTITY'),
        ('compare the event source with itself',
         lambda b: setattr(_p(b, 3, IN_PARAM, 1).connections[0], 'target_node_index', 1),
         'Graph owner must feed'),
        ('mismatch the timer name literal',
         lambda b: setattr(_p(b, 7, IN_PARAM, 1).value.val_poly.actual_value.val_string,
                           'str', 'MW_Other'),
         'must equal the registered timer name'),
        ('query another prefab',
         lambda b: setattr(_p(b, 9, IN_PARAM, 0).value.val_id, 'id', 20001876),
         'prefab 20001875'),
        ('make the length input a non-entity list',
         lambda b: setattr(_p(b, 10, IN_PARAM, 0).value.val_poly.actual_value.type_def.server_side,
                           'type_tag', 8),
         'Length input must be'),
        ('make the conversion output a non-string',
         lambda b: setattr(_p(b, 11, OUT_PARAM, 0).value.val_poly.actual_value.type_def.server_side,
                           'type_tag', S_INT),
         'Conversion output must be S_STRING'),
        ('rename the marker',
         lambda b: setattr(_p(b, 12, IN_PARAM, 0).value.val_string, 'str', 'MW_Other'),
         'Marker print must print'),
        ('unlink the converted count',
         lambda b: _p(b, 13, IN_PARAM, 0).ClearField('connections'),
         'consumes the converted count'),
        ('feed the count print from the marker',
         lambda b: setattr(_p(b, 13, IN_PARAM, 0).connections[0], 'target_node_index', 12),
         'consumes the converted count'),
        ('drop the marker to count flow',
         lambda b: _p(b, 12, OUT_FLOW, 0).ClearField('connections'),
         'must flow into the count print')]


def _self_test(path):
    """Pristine export must pass; every single-field mutation must be rejected."""
    failures = []
    fixtures = {'ok': True, 'fixture': str(Path(path).resolve()), 'runtimeVerified': False}

    try:
        report = verify(path)
    except ValueError as error:
        failures.append('pristine export rejected: %s' % error)
        fixtures['fixtureAccepted'] = False
    else:
        fixtures['fixtureAccepted'] = True
        fixtures['fixtureSha256'] = report['sha256']

    pb = _pb()
    cases = []
    with tempfile.TemporaryDirectory(prefix='audit-negative-', dir=Path(__file__).resolve().parents[2] / '.runtime/editor-bridge') as tmp:
        for name, mutate, expected in _mutation_cases():
            fields, trailer, raw = _read_container(path)
            bundle = pb.AssetBundle()
            bundle.ParseFromString(raw)
            canonical = bundle.SerializeToString()
            try:
                mutate(bundle)
                payload = bundle.SerializeToString()
            except (ValueError, AttributeError) as error:
                cases.append({'mutation': name, 'rejected': None, 'error': 'bad test: %s' % error})
                failures.append('%s: mutation could not be applied: %s' % (name, error))
                continue
            if payload == canonical:
                cases.append({'mutation': name, 'rejected': False, 'error': 'no byte change'})
                failures.append('%s: mutation did not change the graph bytes' % name)
                continue
            target = Path(tmp) / (name.replace(' ', '-') + '.gia')
            _write_container(target, fields, trailer, payload)
            try:
                verify(target)
            except ValueError as error:
                if expected in str(error):
                    cases.append({'mutation': name, 'rejected': True, 'error': str(error)})
                else:
                    cases.append({'mutation': name, 'rejected': None, 'error': str(error)})
                    failures.append('%s: rejected for the wrong reason: %s' % (name, error))
            else:
                cases.append({'mutation': name, 'rejected': False, 'error': 'accepted'})
                failures.append('%s: mutation accepted by the validator' % name)

    fixtures['cases'] = cases
    fixtures['failed'] = failures
    fixtures['ok'] = not failures
    print(json.dumps(fixtures, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path, help='exported .gia to validate')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--self-test', action='store_true',
                        help='also require every single-field mutation to be rejected')
    args = parser.parse_args()
    if args.self_test:
        sys.exit(_self_test(args.path))
    result = json.dumps(verify(args.path), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
