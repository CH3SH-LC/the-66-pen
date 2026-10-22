"""Read-only native GIA dictionary inspection and exact ConfigID -> Int32 verification.

Writes use the existing author.py / GraphPlan.dict_const production path. This
module deliberately imports neither that writer nor a generated protobuf model.
All relative paths are anchored to the repository root, never the caller cwd.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
CODEC = ROOT / 'tools/beyond-save/gil_container.py'
LIMIT = 64


def local(path):
    path = Path(path)
    return (path if path.is_absolute() else ROOT / path).resolve()


def codec():
    name = '_dictionary_raw_wire_codec'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, CODEC)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def one(fields, number, wire_type, optional=False):
    found = [f for f in fields if f.number == number]
    if not found and optional:
        return None
    if len(found) != 1 or found[0].wire_type != wire_type:
        raise ValueError(f'DICT_FIELD_INVALID:{number}')
    return found[0]


def msg(fields, number):
    return one(fields, number, 2).children()


def num(fields, number, default=None):
    field = one(fields, number, 0, optional=default is not None)
    return field.value if field else default


def text_value(fields, number):
    return one(fields, number, 2).text()


def descriptor(fields):
    declared = msg(fields, 4)
    if num(declared, 1) != 1 or any(f.number == 101 for f in declared):
        raise ValueError('DICT_EXPECT_SERVER_DESCRIPTOR')
    server = msg(declared, 100)
    result = {'serverType': num(server, 1), 'implementation': num(server, 2, 0)}
    binding = one(server, 101, 2, optional=True)
    if binding:
        fields = binding.children()
        result.update(keyServerType=num(fields, 1), valueServerType=num(fields, 2))
        # Fields 4/5 occur in original exports; retain without guessing semantics.
        result['bindingExtras'] = [{'field': f.number, 'wire': f.wire_type,
                                   'value': f.value, 'hex': (f.data or b'').hex()}
                                  for f in fields if f.number not in (1, 2)]
    result['schemaFields'] = [f.number for f in server if f.number >= 100]
    return result


def typed(fields, branch):
    if any(f.number not in (1, 2, 4, 5, branch) for f in fields):
        raise ValueError('DICT_TYPED_VALUE_UNKNOWN_FIELD')
    if [f.number for f in fields if 101 <= f.number <= 112] != [branch]:
        raise ValueError('DICT_STORAGE_ONEOF')
    return {'storageKind': num(fields, 1), 'isValueSet': num(fields, 2, 0),
            **descriptor(fields)}, msg(fields, branch)


def leaf(fields):
    storage = num(fields, 1)
    branches = {1: 101, 2: 102}
    if storage not in branches:
        return {'storageKind': storage, 'isValueSet': num(fields, 2, 0),
                **descriptor(fields), 'unsupportedLeaf': True}
    result, payload = typed(fields, branches[storage])
    if any(f.number != 1 for f in payload):
        raise ValueError('DICT_SCALAR_UNKNOWN_FIELD')
    scalar = one(payload, 1, 0, optional=True)
    value = scalar.value if scalar else 0
    if storage == 2:
        if value >= 1 << 63:
            value -= 1 << 64
        if not -(1 << 31) <= value < 1 << 31:
            raise ValueError('DICT_INT32_RANGE')
    elif not 0 <= value < 1 << 32:
        raise ValueError('DICT_UINT32_RANGE')
    result.update(scalarPresent=scalar is not None,
                  tagged={'uint' if storage == 1 else 'int': value})
    return result


def read_dictionary(fields):
    result, payload = typed(fields, 112)
    if result['storageKind'] != 10003:
        raise ValueError('DICT_EXPECT_STORAGE_10003')
    if any(f.number != 1 or f.wire_type != 2 for f in payload):
        raise ValueError('DICT_MAP_STORAGE_SHAPE')
    pairs = []
    for field in payload:
        entry, pair = typed(field.children(), 111)
        if any(f.number not in (1, 2) for f in pair):
            raise ValueError('DICT_PAIR_STORAGE_SHAPE')
        entry.update(key=leaf(msg(pair, 1)), value=leaf(msg(pair, 2)))
        pairs.append(entry)
    result['pairs'] = pairs
    return result


def inspect_export(path):
    path = local(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('DICT_EXPORT_TOO_LARGE')
    data = path.read_bytes()
    wire = codec()
    container = wire.decode_container(data)
    if container.subtype != 3:
        raise ValueError('DICT_EXPECT_GIA_SUBTYPE_3')
    resource = msg(wire.parse_fields(container.payload), 1)
    if num(resource, 5) != 9:
        raise ValueError('DICT_EXPECT_GRAPH_RESOURCE_9')
    graph = msg(msg(msg(resource, 13), 1), 1)
    identity = msg(graph, 1)
    graph_name = text_value(graph, 2)
    if text_value(resource, 3) != graph_name or num(identity, 2) != 20000:
        raise ValueError('DICT_GRAPH_IDENTITY')
    nodes, dictionaries = set(), []
    for field in graph:
        if field.number != 3:
            continue
        node = field.children()
        node_id = num(node, 1)
        if node_id in nodes:
            raise ValueError('DICT_DUPLICATE_NODE')
        nodes.add(node_id)
        definition = num(msg(node, 2), 5)
        kernel_definition = num(msg(node, 3), 5)
        pins = set()
        for pin_field in node:
            if pin_field.number != 4:
                continue
            pin = pin_field.children()
            signature = msg(pin, 1)
            kind, index = num(signature, 1), num(signature, 2, 0)
            if (kind, index) in pins:
                raise ValueError('DICT_DUPLICATE_PIN')
            pins.add((kind, index))
            value_field = one(pin, 3, 2, optional=True)
            if not value_field or num(value_field.children(), 1, 0) != 10003:
                continue
            kernel = msg(pin, 2)
            dictionaries.append({'nodeId': node_id, 'definitionId': definition,
                'kernelDefinitionId': kernel_definition, 'portKind': kind, 'portIndex': index,
                'kernelPortKind': num(kernel, 1), 'kernelPortIndex': num(kernel, 2, 0),
                'serverParamType': num(pin, 4),
                'inputConnectionCount': sum(f.number == 5 for f in pin),
                **read_dictionary(value_field.children())})
    return {'ok': True, 'kind': 'graph-dictionary-export-inspection-v1',
            'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'name': graph_name, 'graphId': num(identity, 5), 'dictionaries': dictionaries,
            'constantValuesVerified': False, 'levelIdentityVerified': False,
            'runtimeVerified': False, 'persistentSaveVerified': False}


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('DICT_EXPECTATION_INTEGER:' + label)
    return value


def expectation(expected):
    if not isinstance(expected, dict) or set(expected) != {'graphId', 'name', 'values'}:
        raise ValueError('DICT_EXPECTATION_SHAPE')
    integer(expected['graphId'], 'graphId', 1, 0xFFFFFFFF)
    if not isinstance(expected['name'], str) or not expected['name']:
        raise ValueError('DICT_EXPECTATION_NAME')
    if not isinstance(expected['values'], list) or not expected['values']:
        raise ValueError('DICT_EXPECTATION_VALUES')
    seen = set()
    for row in expected['values']:
        if not isinstance(row, dict) or set(row) != {'nodeId', 'definitionId', 'portIndex',
                                                    'keyServerType', 'valueServerType', 'dict'}:
            raise ValueError('DICT_EXPECTATION_ROW_SHAPE')
        integer(row['nodeId'], 'nodeId', 1, 0xFFFFFFFF)
        integer(row['definitionId'], 'definitionId', 1, 0xFFFFFFFF)
        integer(row['portIndex'], 'portIndex', 0, 0xFFFF)
        if type(row['keyServerType']) is not int or type(row['valueServerType']) is not int or (row['keyServerType'], row['valueServerType']) != (20, 3):
            raise ValueError('DICT_VERIFIER_SUPPORTS_CONFIG_ID_20_TO_INT32_3_ONLY')
        signature = row['nodeId'], row['portIndex']
        if signature in seen:
            raise ValueError('DICT_EXPECTATION_DUPLICATE_PIN')
        seen.add(signature)
        if not isinstance(row['dict'], list) or not 1 <= len(row['dict']) <= LIMIT:
            raise ValueError('DICT_EXPECTATION_ENTRIES_1_TO_64')
        keys = set()
        for pair in row['dict']:
            if not isinstance(pair, dict) or set(pair) != {'key', 'value'} or not isinstance(pair['key'], dict) or not isinstance(pair['value'], dict) or set(pair['key']) != {'uint'} or set(pair['value']) != {'int'}:
                raise ValueError('DICT_EXPECTATION_TYPED_PAIR')
            key = integer(pair['key']['uint'], 'key.uint', 0, 0xFFFFFFFF)
            integer(pair['value']['int'], 'value.int', -(1 << 31), (1 << 31) - 1)
            if key in keys:
                raise ValueError('DICT_EXPECTATION_DUPLICATE_KEY')
            keys.add(key)
    return expected


def verify_export(path, expected):
    expected = expectation(expected)
    report = inspect_export(path)
    if (report['graphId'], report['name']) != (expected['graphId'], expected['name']):
        raise ValueError('DICT_EXPORT_EXPECTED_GRAPH_IDENTITY')
    verified = []
    for row in expected['values']:
        matches = [p for p in report['dictionaries'] if p['nodeId'] == row['nodeId']
                   and p['portKind'] == 3 and p['portIndex'] == row['portIndex']]
        if len(matches) != 1:
            raise ValueError('DICT_EXPORT_EXPECTED_PIN_MISSING')
        pin = matches[0]
        if pin['definitionId'] != row['definitionId'] or pin['kernelDefinitionId'] != row['definitionId'] or (pin['kernelPortKind'], pin['kernelPortIndex']) != (3, row['portIndex']):
            raise ValueError('DICT_EXPORT_EXPECTED_NODE_OR_PIN_IDENTITY')
        if pin['inputConnectionCount']:
            raise ValueError('DICT_CONSTANT_HAS_INPUT_CONNECTION')
        if pin['serverParamType'] != 27 or pin['serverType'] != 27 or pin['isValueSet'] != 1 or pin['implementation'] != 2:
            raise ValueError('DICT_EXPORT_TYPE_OR_UNSET')
        if (pin.get('keyServerType'), pin.get('valueServerType')) != (20, 3) or pin['schemaFields'] != [101]:
            raise ValueError('DICT_EXPORT_KEY_VALUE_BINDING')
        if len(pin['pairs']) != len(row['dict']):
            raise ValueError('DICT_EXPORT_EXACT_CARDINALITY')
        actual, keys = [], set()
        for pair in pin['pairs']:
            if (pair['storageKind'], pair['serverType'], pair['isValueSet'], pair['implementation'], pair.get('keyServerType'), pair.get('valueServerType')) != (10007, 25, 1, 2, 20, 3) or pair['schemaFields'] != [101]:
                raise ValueError('DICT_EXPORT_ENTRY_DESCRIPTOR_OR_UNSET')
            for role, storage, server in (('key', 1, 20), ('value', 2, 3)):
                value = pair[role]
                if (value['storageKind'], value['serverType'], value['isValueSet'], value['implementation']) != (storage, server, 1, 0) or value['schemaFields']:
                    raise ValueError('DICT_EXPORT_LEAF_DESCRIPTOR_OR_UNSET')
            key = pair['key']['tagged']['uint']
            if key in keys:
                raise ValueError('DICT_EXPORT_DUPLICATE_KEY')
            keys.add(key)
            actual.append({'key': pair['key']['tagged'], 'value': pair['value']['tagged']})
        if actual != row['dict']:
            raise ValueError('DICT_EXPORT_EXACT_PAIRS_MISMATCH')
        verified.append(row)
    return {key: value for key, value in report.items() if key != 'dictionaries'} | {
        'kind': 'graph-price-dictionary-export-verification-v1', 'constantValuesVerified': True,
        'verifiedValues': verified, 'evidence': 'independent-export-bytes-only',
        'genericIdVerifiedFromExport': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('inspect-export', 'verify-export'):
        child = sub.add_parser(command)
        child.add_argument('--gia', required=True)
        child.add_argument('--output')
        if command == 'verify-export':
            child.add_argument('--expect-file', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'inspect-export':
            result = inspect_export(args.gia)
        else:
            expected = json.loads(local(args.expect_file).read_text(encoding='utf-8-sig'))
            result = verify_export(args.gia, expected)
    except (ValueError, OSError, KeyError, TypeError) as error:
        result = {'ok': False, 'error': str(error), 'constantValuesVerified': False}
    if args.output:
        output = local(args.output)
        try:
            output.relative_to(ROOT)
            output.parent.mkdir(parents=True, exist_ok=True)
            # Preserve receipts; never overwrite an earlier result or an input GIA.
            with output.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
        except (ValueError, OSError) as error:
            result = {'ok': False, 'error': 'DICT_OUTPUT_NOT_CREATED:' + str(error)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
