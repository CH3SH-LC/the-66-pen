"""Read-only saved GIL acceptance for an entity with an event -> print graph."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify(args):
    reader = module('saved_entity_reader', ROOT / 'tools/game-executor/verify-created-save.py')
    graphs = module('saved_graph_reader', ROOT / 'tools/editor-bridge/audit-native-enums.py')
    from miliastra_agent.parsers.entity_graph_bindings import parse_gil_entity_graph_bindings
    from miliastra_agent.parsers.entities import parse_payload
    data = args.gil.read_bytes()
    header = reader.builder.read_header(data)
    reader.require(header.file_type == 2, 'Expected GIL')
    reader.require(header.version == 1, 'Unsupported GIL version')
    _, saved_graphs = graphs.load_graphs(args.gil)
    matches = [g for g in saved_graphs if g.identity.runtime_id == args.graph_id]
    reader.require(len(matches) == 1, 'Graph missing or duplicated')
    graph = matches[0]
    reader.require(graph.display_name == args.name, 'Graph name mismatch')
    reader.require({n.index: n.shell_ref.runtime_id for n in graph.nodes} ==
                   {args.event_node: 71, args.print_node: 1} and len(graph.nodes) == 2,
                   'Expected exactly the specified event and print nodes')
    edges = []
    strings = []
    for node in graph.nodes:
        for pin in node.pins:
            if node.index == args.print_node and pin.value.HasField('val_string'):
                reader.require(pin.shell_sig.kind == 3 and pin.shell_sig.index == 0, 'Unexpected string pin')
                strings.append(pin.value.val_string.str)
            for connection in pin.connections:
                edges.append((node.index, pin.shell_sig.kind, pin.shell_sig.index,
                              connection.target_node_index, connection.target_pin_shell.kind,
                              connection.target_pin_shell.index))
    reader.require(edges == [(args.event_node, 2, 0, args.print_node, 1, 0)], 'Execution edge mismatch')
    reader.require(strings == [args.text], 'Print content mismatch')
    bindings = parse_gil_entity_graph_bindings(data[20:-4])
    reader.require(sum(b.entity_id == args.entity_id and b.graph_id == args.graph_id for b in bindings) == 1,
                   'Entity graph binding missing or duplicated')
    entities = [e for e in parse_payload(data[20:-4], file_type=2) if e.entity_id == args.entity_id]
    reader.require(len(entities) == 1 and entities[0].template_id == args.template_id, 'Entity/template mismatch')
    record = reader.entity_records(data[20:-4])[args.entity_id][0]
    geometry = reader.target_geometry(record)
    for key in ('position', 'rotation', 'scale'):
        reader.quantized_check(geometry[key], getattr(args, key), 1e-6)
    reader.require(args.gil.read_bytes() == data, 'Save changed during readback; take a stable snapshot')
    return dict(ok=True, scope='saved_file_content_only', sha256=hashlib.sha256(data).hexdigest(),
                entityId=args.entity_id, graphId=args.graph_id, geometry=geometry,
                nodeCount=2, edgeCount=1, bindingVerified=True, persistenceVerified=True,
                officialPlaytestVerified=False, sceneBoundsVerified=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('gil', type=Path)
    for key in ('entity-id', 'template-id', 'graph-id', 'event-node', 'print-node'):
        ap.add_argument('--' + key, required=True, type=int)
    for key in ('name', 'text'):
        ap.add_argument('--' + key, required=True)
    for key in ('position', 'rotation', 'scale'):
        ap.add_argument('--' + key, required=True, nargs=3, type=float)
    args = ap.parse_args()
    try:
        result = verify(args)
    except Exception as error:
        result = dict(ok=False, error=str(error), persistenceVerified=False, officialPlaytestVerified=False)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
