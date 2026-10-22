"""Validate a real exported graph without changing the file or game session."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path


def inspect(path: Path) -> dict:
    root = Path(__file__).resolve().parents[2]
    schema = root / 'third_party/auto-miliastra/src'
    sys.path.insert(0, str(schema))
    from miliastra_agent.core.proto_gen import gia_graph_pb2 as pb
    from google.protobuf.json_format import MessageToDict

    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError('Truncated GIA')
    size, version, magic, kind, payload_size = struct.unpack('>5I', data[:20])
    if (size != len(data) - 4 or payload_size != size - 20 or
            magic != 0x326 or kind != 3 or struct.unpack('>I', data[-4:])[0] != 0x679):
        raise ValueError('Invalid GIA container')
    bundle = pb.AssetBundle()
    bundle.ParseFromString(data[20:-4])
    resource = bundle.primary_resource
    if resource.resource_class != pb.ResourceEntry.ENTITY_NODE_GRAPH:
        raise ValueError('Expected entity node graph')
    graph = resource.graph_data.inner.graph
    nodes = []
    links = []
    edges = []
    for node in graph.nodes:
        strings = []
        for pin in node.pins:
            if pin.value.HasField('val_string'):
                strings.append(pin.value.val_string.str)
            for connection in pin.connections:
                links.append({'from': node.index, 'to': connection.target_node_index,
                              'fromKind': pin.shell_sig.kind,
                              'toKind': connection.target_pin_shell.kind})
                source = (node.index, pin.shell_sig.kind, pin.shell_sig.index)
                target = (connection.target_node_index, connection.target_pin_shell.kind,
                          connection.target_pin_shell.index)
                # Data connections are stored on inputs; execution connections on outputs.
                if source[1] == 3:  # IN_PARAM
                    source, target = target, source
                edges.append({'source': list(source), 'target': list(target)})
        nodes.append({'id': node.index, 'definition': node.shell_ref.runtime_id,
                      'x': node.x_pos, 'y': node.y_pos, 'strings': strings,
                      'pins': [MessageToDict(pin, preserving_proto_field_name=True)
                               for pin in node.pins]})
    ids = {node['id'] for node in nodes}
    if len(ids) != len(nodes) or any(link['to'] not in ids for link in links):
        raise ValueError('Duplicate node IDs or dangling links')
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'containerVersion': version,
            'engineVersion': bundle.engine_version, 'name': resource.internal_name,
            'graphId': graph.identity.runtime_id, 'nodeCount': len(nodes),
            'nodes': nodes, 'links': links, 'directedEdges': edges,
            'verified': 'exported-file-content-only', 'playtestVerified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--extract-payload', type=Path,
                        help='Write the validated graph protobuf for the native import adapter')
    args = parser.parse_args()
    report = inspect(args.path)
    if args.extract_payload:
        from miliastra_agent.core.proto_gen import gia_graph_pb2 as pb
        data = args.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != report['sha256']:
            raise ValueError('Input changed after validation')
        bundle = pb.AssetBundle()
        bundle.ParseFromString(data[20:-4])
        payload = bundle.primary_resource.graph_data.inner.graph.SerializeToString()
        args.extract_payload.parent.mkdir(parents=True, exist_ok=True)
        args.extract_payload.write_bytes(payload)
        report['payloadPath'] = str(args.extract_payload.resolve())
        report['payloadSha256'] = hashlib.sha256(payload).hexdigest()
    result = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result + '\n', encoding='utf-8')
    print(result)
