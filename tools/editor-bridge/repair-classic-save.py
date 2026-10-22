"""Produce a separate, lossless repair candidate for our demo level saves.

Writes only a new candidate under project .runtime; never overwrites the source.
Does not load/save the editor or prove playtest success.
Only our named game-loop graphs are eligible; unrelated wire fields are preserved.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'beyond-save'))
import gil_container as codec

spec = importlib.util.spec_from_file_location('enum_audit', Path(__file__).with_name('audit-native-enums.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

ROOT = Path(__file__).resolve().parents[2]

ALLOWED = {'MW_Game_Loop_20260917': 29, 'MW_Game_Loop_V2_20260917': 28,
           'MW_Game_Loop_V3_20260917': 27}


def repair(blob):
    container = codec.decode_container(blob)
    if container.subtype != 2:
        raise ValueError('Expected level GIL')
    changes = []

    def graph_leaf(raw):
        graph = audit.pb.NodeGraph()
        graph.ParseFromString(raw)
        if graph.display_name not in ALLOWED:
            return raw
        if graph.SerializeToString() != raw or len(graph.nodes) != ALLOWED[graph.display_name]:
            raise ValueError('Unexpected graph encoding or node count')
        teleports = [n for n in graph.nodes if n.shell_ref.runtime_id in (288, 805)]
        if len(teleports) != 1 or teleports[0].kernel_ref.runtime_id != teleports[0].shell_ref.runtime_id:
            raise ValueError('Unexpected teleport definition')
        node = teleports[0]
        if node.shell_ref.runtime_id == 288:
            node.shell_ref.runtime_id = node.kernel_ref.runtime_id = 805
            changes.append({'graph': graph.display_name, 'graphId': graph.identity.runtime_id,
                            'node': node.index, 'field': 'teleport', 'before': 288, 'after': 805})
        for node in graph.nodes:
            if node.shell_ref.runtime_id != 652:
                continue
            pins = [p for p in node.pins if p.shell_sig.kind == 3 and p.shell_sig.index == 1]
            if len(pins) != 1 or pins[0].connections or pins[0].type != 14:
                raise ValueError('Unexpected settlement pin')
            value = pins[0].value
            if not value.HasField('val_enum') or value.val_enum.enum not in (1, 4101):
                raise ValueError('Unexpected settlement value')
            if value.val_enum.enum == 1:
                value.val_enum.enum = 4101
                changes.append({'graph': graph.display_name, 'graphId': graph.identity.runtime_id,
                                'node': node.index, 'field': 'settlement', 'before': 1, 'after': 4101})
        return graph.SerializeToString()

    def walk(raw, path):
        if not path:
            return graph_leaf(raw)
        fields = codec.parse_fields(raw)
        if codec.encode_fields(fields) != raw:
            raise ValueError('Non-lossless wire roundtrip')
        for field in fields:
            if field.number == path[0]:
                if field.wire_type != codec.WIRE_LENGTH:
                    raise ValueError('Unexpected graph wrapper wire type')
                field.data = walk(field.data, path[1:])
        return codec.encode_fields(fields)

    payload = walk(container.payload, (10, 1, 1))
    result = codec.encode_container(codec.Container(container.subtype, payload,
                                                   container.version, container.magic, container.trailer))
    return result, changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(argv)
    runtime = (ROOT / '.runtime').resolve()
    output = args.output.resolve()
    if (not runtime.is_relative_to(ROOT.resolve()) or output == runtime
            or not output.is_relative_to(runtime)):
        parser.error('Output must be an isolated candidate under project .runtime')
    if args.source.resolve() == output or output.exists():
        raise SystemExit('Output must be a new candidate file, never the source')
    before = args.source.read_bytes()
    after, changes = repair(before)
    twice, repeated_changes = repair(after)
    if twice != after or repeated_changes:
        raise ValueError('Repair is not idempotent')
    # Exclusive creation preserves the no-overwrite promise even if a file
    # appeared while the offline candidate was being computed.
    with output.open('xb') as stream:
        stream.write(after)
    print(json.dumps({'sourceSha256': hashlib.sha256(before).hexdigest(),
                      'candidateSha256': hashlib.sha256(after).hexdigest(),
                      'changes': changes, 'idempotent': True, 'sourceUnchanged': args.source.read_bytes() == before,
                      'appliedToEditor': False, 'playtestVerified': False}, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
