"""Prepare/dispatch a bounded native graph vector write; independently read GIA.

This tool never edits/imports a protobuf or loads a bridge. Dispatch goes through
the existing author.py journal/lease/backend and is explicit, single use. Export
verification reads exact GIA bytes, not a writer-supplied success flag.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.authoring.author import validate_scalar_payload
from tools.gameplan.contracts import default_store

OUT = ROOT / '.runtime/graph-vector-values'
AUTHOR = ROOT / 'tools/authoring/author.py'
CODEC = ROOT / 'tools/beyond-save/gil_container.py'
SOURCE_FILES = [AUTHOR, Path(__file__).resolve(), CODEC, Path(__file__).with_name('release.py')] + [
    ROOT / path for path in (
        'tools/editor-bridge/Adapter/AuthoringGraph.cs',
        'tools/editor-bridge/Adapter/AuthoringVector.cs',
        'tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs',
        'tools/gameplan/contracts.py', 'tools/gameplan/paramtypes.py',
        'tools/gameplan/plan.py', 'tools/gameplan/builder.py')] + sorted(
            (ROOT / 'data/node-contracts/variants/server').glob('*.json'))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def local(path) -> Path:
    p = Path(path).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('VECTOR_PATH_OUTSIDE_PROJECT')
    return p


def dump(path: Path, value):
    local(path).parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def checked_value(row):
    required = {'nodeId', 'definitionId', 'portIndex', 'vector3'}
    if not isinstance(row, dict) or set(row) != required:
        raise ValueError('VECTOR_EXPECT_FIELDS')
    for key in ('nodeId', 'definitionId', 'portIndex'):
        if type(row[key]) is not int or not (0 if key == 'portIndex' else 1) <= row[key] <= 2**32-1:
            raise ValueError('VECTOR_EXPECT_ID:' + key)
    validate_scalar_payload({'vector3': row['vector3']})
    definition = default_store().require(row['definitionId'])
    port = definition.port(3, row['portIndex'])
    if port is None or port.server_param_type != 12 or port.generic_id != 12:
        raise ValueError('VECTOR_EXPECT_CONCRETE_SERVER_TYPE_12_REQUIRED')
    return row


def expectation(value):
    if not isinstance(value, dict) or set(value) != {'name', 'graphId', 'values'}:
        raise ValueError('VECTOR_EXPECTATION_FIELDS')
    import re
    if not isinstance(value['name'], str) or not re.fullmatch(r'MW_API_[A-Za-z0-9_]{1,48}', value['name']):
        raise ValueError('VECTOR_NAME_INVALID')
    if type(value['graphId']) is not int or not 1 <= value['graphId'] <= 2**32-1:
        raise ValueError('VECTOR_GRAPH_ID_INVALID')
    if not isinstance(value['values'], list) or not 1 <= len(value['values']) <= 128:
        raise ValueError('VECTOR_EXPECT_COUNT_INVALID')
    seen = set()
    for row in value['values']:
        checked_value(row)
        identity = row['nodeId'], row['portIndex']
        if identity in seen:
            raise ValueError('VECTOR_DUPLICATE_PIN')
        seen.add(identity)
    return value


def author_argv(card):
    expected = expectation(card['expected'])
    if len(expected['values']) != 1:
        raise ValueError('VECTOR_SINGLE_CARD_REQUIRED')
    row = expected['values'][0]
    run_id = str(uuid.UUID(card['runId']))
    request_id = str(uuid.UUID(card['requestId']))
    argv = [sys.executable, '-B', str(AUTHOR)]
    if card['elevatedQueue'] is not None:
        argv += ['--elevated-queue', str(local(card['elevatedQueue']))]
    return argv + ['graph', 'value', '--run-id', run_id, '--request-id', request_id,
        '--name', expected['name'], '--graph-id', str(expected['graphId']),
        '--node-id', str(row['nodeId']), '--port-index', str(row['portIndex']),
        '--definition-id', str(row['definitionId']),
        '--expect-server-param-type', '12', '--expect-generic-id', '12',
        '--slot', 'vector3', '--value-json', canonical({'vector3': row['vector3']}).decode()]


def prepare(args):
    card = {'kind': 'native-graph-vector3-card-v1', 'runId': str(uuid.UUID(args.run_id)),
        'requestId': str(uuid.uuid4()), 'elevatedQueue': str(local(args.elevated_queue)) if args.elevated_queue else None,
        'expected': {'name': args.name, 'graphId': args.graph_id, 'values': [{
            'nodeId': args.node_id, 'definitionId': args.definition_id,
            'portIndex': args.port_index, 'vector3': args.xyz}]},
        'sourceHashes': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in SOURCE_FILES},
        'executed': False, 'runtimeVerified': False, 'persistentSaveVerified': False}
    author_argv(card)
    card['cardSha256'] = sha(canonical(card))
    dest = OUT / 'prepared' / card['requestId'] / 'card.json'
    dump(dest, card)
    return {'prepared': str(dest), 'cardSha256': card['cardSha256'], 'argv': author_argv(card),
            'executed': False, 'runtimeVerified': False}


def load_card(path):
    path = local(path)
    if not path.is_relative_to(OUT / 'prepared') or path.name != 'card.json':
        raise ValueError('VECTOR_CARD_LOCATION_INVALID')
    card = json.loads(path.read_text(encoding='utf-8'))
    frozen = dict(card)
    digest = frozen.pop('cardSha256', None)
    if sha(canonical(frozen)) != digest or card.get('kind') != 'native-graph-vector3-card-v1':
        raise ValueError('VECTOR_CARD_HASH_INVALID')
    expected_sources = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in SOURCE_FILES}
    if card['sourceHashes'] != expected_sources:
        raise ValueError('VECTOR_CARD_SOURCE_CHANGED')
    author_argv(card)
    return path, card


def dispatch(path):
    path, card = load_card(path)
    claim = path.parent / 'attempt.used'
    # An uncertain timeout or nonzero result still consumes this attempt.
    with claim.open('xb') as stream:
        stream.write(canonical({'cardSha256': card['cardSha256']}))
    argv = author_argv(card)
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=180)
        (path.parent / 'author.stdout').write_bytes(result.stdout)
        (path.parent / 'author.stderr').write_bytes(result.stderr)
        try:
            response = json.loads(result.stdout.decode('utf-8-sig'))
        except (UnicodeError, ValueError):
            response = None
        report = {'returncode': result.returncode, 'response': response,
            'ok': result.returncode == 0 and isinstance(response, dict) and response.get('ok') is True,
            'cardSha256': card['cardSha256'], 'retryAttempted': False,
            'independentExportVerified': False, 'runtimeVerified': False, 'persistentSaveVerified': False}
    except (OSError, subprocess.TimeoutExpired) as error:
        report = {'ok': False, 'error': type(error).__name__, 'outcomeUncertain': True, 'retryAttempted': False}
    dump(path.parent / 'dispatch.json', report)
    return report


def codec():
    name = '_graph_vector_codec'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, CODEC)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def verify_export(path: Path, expected: dict):
    """Strict raw-wire GIA verification. No protobuf model/writer is imported."""
    expected = expectation(expected)
    path = local(path)
    if path.stat().st_size > 32*1024*1024:
        raise ValueError('VECTOR_EXPORT_TOO_LARGE')
    data = path.read_bytes()
    wire = codec()
    container = wire.decode_container(data)
    if container.subtype != 3:
        raise ValueError('VECTOR_EXPECT_GIA_SUBTYPE_3')
    def field(fs, n, wt, optional=False):
        entries = [f for f in fs if f.number == n]
        if not entries and optional:
            return None
        if len(entries) != 1 or entries[0].wire_type != wt:
            raise ValueError('VECTOR_EXPORT_FIELD_INVALID:' + str(n))
        return entries[0]
    def msg(fs, n):
        return field(fs, n, 2).children()
    def number(fs, n, default=None):
        f = field(fs, n, 0, optional=default is not None)
        return f.value if f else default
    def text(fs, n):
        return field(fs, n, 2).text()
    resource = msg(wire.parse_fields(container.payload), 1)
    if number(resource, 5) != 9 or text(resource, 3) != expected['name']:
        raise ValueError('VECTOR_EXPORT_RESOURCE_IDENTITY')
    graph = msg(msg(msg(resource, 13), 1), 1)
    identity = msg(graph, 1)
    if number(identity, 5) != expected['graphId'] or number(identity, 2) != 20000:
        raise ValueError('VECTOR_EXPORT_GRAPH_IDENTITY')
    nodes = {}
    for f in graph:
        if f.number != 3:
            continue
        node = f.children()
        index = number(node, 1)
        if index in nodes:
            raise ValueError('VECTOR_EXPORT_DUPLICATE_NODE')
        nodes[index] = node
    verified = []
    for row in expected['values']:
        node = nodes.get(row['nodeId'])
        if node is None or number(msg(node, 2), 5) != row['definitionId']:
            raise ValueError('VECTOR_EXPORT_NODE_IDENTITY')
        matches = []
        for f in node:
            if f.number != 4:
                continue
            pin = f.children()
            signature = msg(pin, 1)
            if number(signature, 1) == 3 and number(signature, 2, 0) == row['portIndex']:
                matches.append(pin)
        if len(matches) != 1:
            raise ValueError('VECTOR_EXPORT_PIN_IDENTITY')
        pin = matches[0]
        if any(f.number == 5 for f in pin):
            raise ValueError('VECTOR_EXPORT_CONSTANT_HAS_INPUT_CONNECTION')
        if number(pin, 4, 12) != 12:
            raise ValueError('VECTOR_EXPORT_PIN_TYPE')
        value = msg(pin, 3)
        if number(value, 1) != 7 or number(value, 2, 0) != 1:
            raise ValueError('VECTOR_EXPORT_STORAGE_OR_UNSET')
        type_def = msg(value, 4)
        if number(type_def, 1) != 1 or number(msg(type_def, 100), 1) != 12:
            raise ValueError('VECTOR_EXPORT_SERVER_TYPE')
        if [f.number for f in value if 101 <= f.number <= 112] != [107]:
            raise ValueError('VECTOR_EXPORT_STORAGE_ONEOF')
        vec = msg(msg(value, 107), 1)
        if any(f.number not in (1, 2, 3) for f in vec):
            raise ValueError('VECTOR_EXPORT_AXIS_UNKNOWN')
        actual = []
        for i in (1, 2, 3):
            f = field(vec, i, 5, optional=True)
            actual.append(f.value if f else 0)  # omitted protobuf float is +0
        wanted = [bits(x) for x in row['vector3']]
        if actual != wanted:
            raise ValueError('VECTOR_EXPORT_FLOAT32_MISMATCH:' + str(row['nodeId']))
        verified.append(dict(row, float32Bits=actual))
    return {'ok': True, 'kind': 'graph-vector3-export-verification-v1',
        'path': str(path), 'sha256': sha(data), 'graphId': expected['graphId'],
        'verifiedValues': verified, 'evidence': 'independent-export-bytes-only',
        'runtimeVerified': False, 'persistentSaveVerified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    for key in ('run-id', 'name'):
        p.add_argument('--' + key, required=True)
    for key in ('graph-id', 'node-id', 'definition-id', 'port-index'):
        p.add_argument('--' + key, type=int, required=True)
    p.add_argument('--xyz', nargs=3, type=float, required=True)
    p.add_argument('--elevated-queue')
    p = commands.add_parser('dispatch')
    p.add_argument('--prepared', required=True)
    p = commands.add_parser('verify-export')
    p.add_argument('--gia', type=Path, required=True)
    p.add_argument('--expect-file', type=Path, required=True)
    p.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args)
        elif args.command == 'dispatch':
            result = dispatch(args.prepared)
        else:
            expected = json.loads(local(args.expect_file).read_text(encoding='utf-8'))
            result = verify_export(args.gia, expected)
            if args.output:
                dump(args.output, result)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result.get('ok', True) else 2
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
