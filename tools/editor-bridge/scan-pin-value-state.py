"""Read-only scan of a native .gia export: pins marked "value set" whose value slot is empty.

Independent of the project's own inspect helper: parses the GIA container and the protobuf
schema directly, then reports every pin where `is_value_set` is true and the value oneof is
empty. Used to decide whether that shape is a defect or ordinary protobuf zero-omission, by
comparing a suspect graph against a graph already known to work.

Reads only; writes nothing.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / 'third_party/auto-miliastra/src'

sys.path.insert(0, str(SCHEMA))
from google.protobuf.json_format import MessageToDict  # noqa: E402
from miliastra_agent.core.proto_gen import gia_graph_pb2 as pb  # noqa: E402

def value_branches(value_json: dict) -> dict:
    """The value oneof branches present in a pin's value message.

    MessageToDict renders them camelCase (valInt / valPoly / valString ...), so match on the
    shared prefix rather than an enumerated list that would silently go stale.
    """
    return {k: v for k, v in value_json.items() if k.startswith('val')}


def load_graph(path: Path):
    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError('Truncated GIA')
    size, _version, magic, kind, payload_size = struct.unpack('>5I', data[:20])
    if (size != len(data) - 4 or payload_size != size - 20 or
            magic != 0x326 or kind != 3 or
            struct.unpack('>I', data[-4:])[0] != 0x679):
        raise ValueError('Invalid GIA container')
    bundle = pb.AssetBundle()
    bundle.ParseFromString(data[20:-4])
    resource = bundle.primary_resource
    if resource.resource_class != pb.ResourceEntry.ENTITY_NODE_GRAPH:
        raise ValueError('Expected entity node graph')
    return resource.graph_data.inner.graph


def pin_value_state(pin_json: dict):
    """Classify a pin as ('unset'|'empty-while-set'|'populated', branch_names)."""
    value = pin_json.get('value')
    if value is None:
        return 'unset', []
    if not value.get('isValueSet'):
        return 'unset', []
    branches = value_branches(value)
    if not branches:
        return 'empty-while-set', []
    # A branch can be present but carry an empty message (e.g. valInt: {}): protobuf's
    # MessageToDict omits zero-valued scalar fields, so an all-empty branch means the value
    # is the type's zero. Report which branch, so the caller can judge the shape.
    if all(not v for v in branches.values()):
        return 'empty-while-set', sorted(branches)
    return 'populated', sorted(branches)


def scan(path: Path) -> dict:
    graph = load_graph(path)
    graph_json = MessageToDict(graph, preserving_proto_field_name=False)
    nodes = graph_json.get('nodes', [])

    total = 0
    empty_while_set = 0
    populated = 0
    details = []

    for index, node in enumerate(nodes, 1):
        node_id = node.get('id', node.get('nodeId'))
        for ordinal, pin in enumerate(node.get('pins', [])):
            total += 1
            state, branches = pin_value_state(pin)
            sig = pin.get('shellSig') or {}
            if state == 'empty-while-set':
                empty_while_set += 1
                details.append({
                    'nodeIndex': index,
                    'nodeId': node_id,
                    'pinOrdinal': ordinal,
                    'pinKind': sig.get('kind'),
                    'valueKeys': branches,
                })
            elif state == 'populated':
                populated += 1

    return {
        'path': str(path),
        'nodeCount': len(nodes),
        'pinCount': total,
        'populated': populated,
        'emptyWhileSet': empty_while_set,
        'emptyWhileSetDetails': details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exports', nargs='+', type=Path)
    parser.add_argument('--as-json', action='store_true')
    args = parser.parse_args()

    results = []
    failed = False
    for path in args.exports:
        try:
            results.append(scan(path))
        except Exception as exc:  # noqa: BLE001 - reported, not masked
            failed = True
            results.append({'path': str(path), 'error': f'{type(exc).__name__}: {exc}'})

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{Path(r['path']).name}")
            if 'error' in r:
                print(f"  ERROR {r['error']}")
                continue
            print(f"  nodes={r['nodeCount']} pins={r['pinCount']} "
                  f"populated={r['populated']} emptyWhileSet={r['emptyWhileSet']}")
            for d in r['emptyWhileSetDetails']:
                print(f"    node#{d['nodeIndex']} (id={d['nodeId']}) "
                      f"pin{d['pinOrdinal']} kind={d['pinKind']} valueKeys={d['valueKeys']}")
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
