"""Check serialized graph enum constants against decoded native resource tables.

Reads GIA/GIL only. Includes unbound graph definitions. This is a content audit,
not the game's upload validator. Zero-valued protobuf fields are not errors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.proto_gen import gia_graph_pb2 as pb
from miliastra_agent.core.wire import get_bytes_fields


def scalar(fields, number, default=0):
    return next((f['v'] for f in fields if f['f'] == number and 'v' in f), default)


def message(fields, number):
    return next((f.get('m', []) for f in fields if f['f'] == number), [])


def native_contracts(directory):
    globals_ = list(directory.glob('Beyond__BeyondGlobal__*.mihoyobin.json'))
    if len(globals_) != 1:
        raise ValueError('Expected exactly one native global enum table')
    d = json.loads(globals_[0].read_text(encoding='utf-8'))
    enums = {}
    for row in message(d['fields'], 1):
        if row['f'] == 1:
            fields = row.get('m', [])
            enums[scalar(fields, 1)] = {
                scalar(entry.get('m', []), 1)
                for entry in fields if entry['f'] == 2
            }
    contracts = {}
    sources = [globals_[0]]
    for path in sorted(directory.glob('Beyond__Node__*.mihoyobin.json')):
        fields = json.loads(path.read_text(encoding='utf-8'))['fields']
        categories = message(fields, 4)
        keys = [f.get('m', []) for f in categories if f['f'] == 1]
        for key in keys:
            if [scalar(key, n) for n in (1, 2, 3)] != [10001, 20000, 22000]:
                continue
            node_id = scalar(key, 5)
            for pin in (f.get('m', []) for f in fields if f['f'] == 102):
                signature = message(pin, 3)
                definition = message(pin, 4)
                enum_id = scalar(message(definition, 101), 1)
                if enum_id:
                    if enum_id not in enums or not enums[enum_id]:
                        raise ValueError(f'Missing native enum table {enum_id}')
                    contract_key = (node_id, scalar(signature, 2))
                    contract = (enum_id, enums[enum_id])
                    if contract_key in contracts and contracts[contract_key] != contract:
                        raise ValueError(f'Conflicting native pin contract {contract_key}')
                    contracts[contract_key] = contract
                    sources.append(path)
    if not contracts:
        raise ValueError('No native enum contracts decoded')
    digest = hashlib.sha256()
    for path in sorted(set(sources)):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return contracts, digest.hexdigest()


def load_graphs(path):
    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError('Truncated container')
    length, version, magic, kind, payload_length = struct.unpack('>5I', data[:20])
    if (length != len(data) - 4 or payload_length != len(data) - 24
            or magic != 0x326 or struct.unpack('>I', data[-4:])[0] != 0x679):
        raise ValueError('Invalid container')
    graphs = []
    if kind == 3:
        bundle = pb.AssetBundle()
        bundle.ParseFromString(data[20:-4])
        if bundle.primary_resource.resource_class != pb.ResourceEntry.ENTITY_NODE_GRAPH:
            raise ValueError('Expected graph GIA')
        graphs.append(bundle.primary_resource.graph_data.inner.graph)
    elif kind == 2:
        for group in get_bytes_fields(data[20:-4], 10):
            for wrapper in get_bytes_fields(group, 1):
                for raw in get_bytes_fields(wrapper, 1):
                    graph = pb.NodeGraph()
                    graph.ParseFromString(raw)
                    graphs.append(graph)
    else:
        raise ValueError(f'Unsupported container kind {kind}')
    return data, graphs


def audit(path, contracts, source_hash):
    data, graphs = load_graphs(path)
    checks, warnings = [], []
    for graph in graphs:
        for node in graph.nodes:
            definition = node.shell_ref.runtime_id
            if definition == 288:
                warnings.append({'graphId': graph.identity.runtime_id, 'node': node.index,
                                 'code': 'BEYOND_TELEPORT_REQUIRES_MODE_REVIEW'})
            for pin in node.pins:
                if pin.shell_sig.kind != 3 or pin.connections:
                    continue
                value = pin.value
                if value.HasField('val_poly'):
                    value = value.val_poly.actual_value
                if not value.HasField('val_enum') or pin.type not in (4, 14):
                    continue
                # Resource f3 is the kernel signature. Shell order can differ:
                # node 252 shell pin 5 is kernel pin 7 (boolean).
                key = (node.kernel_ref.runtime_id or definition, pin.kernel_sig.index)
                if key not in contracts:
                    checks.append({'graphId': graph.identity.runtime_id, 'node': node.index,
                                   'definition': definition, 'pin': pin.shell_sig.index,
                                   'pass': False, 'reason': 'native-enum-contract-missing'})
                    continue
                enum_id, allowed = contracts[key]
                actual = int(value.val_enum.enum)
                checks.append({'graphId': graph.identity.runtime_id, 'node': node.index,
                               'definition': definition, 'pin': pin.shell_sig.index,
                               'enumId': enum_id, 'actual': actual, 'allowed': sorted(allowed),
                               'pass': actual in allowed})
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
            'nativeContractSha256': source_hash, 'graphCount': len(graphs),
            'checkedConstants': len(checks), 'ok': all(c['pass'] for c in checks),
            'checks': checks, 'warnings': warnings, 'playtestVerified': False,
            'scope': 'explicit unconnected enum constants in all graph definitions only'}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('paths', nargs='+', type=Path)
    ap.add_argument('--native-dir', type=Path, default=ROOT / '.runtime/editor-catalog/decoded')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    try:
        contracts, digest = native_contracts(args.native_dir)
        reports = [audit(path, contracts, digest) for path in args.paths]
        result = {'ok': all(r['ok'] for r in reports), 'reports': reports}
        code = 0 if result['ok'] else 1
    except Exception as exc:
        result, code = {'ok': False, 'error': str(exc)}, 2
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
    raise SystemExit(code)
