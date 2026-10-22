"""Verify one newly saved root5 entity using two immutable native GIL snapshots.

This reads GIL bytes only. It cannot establish who created/saved the entity,
whether an asynchronous save finished, or whether the game displayed it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'create_save_native_builder', ROOT / 'tools/editor-bridge/build-newdemo-static.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
from miliastra_agent.parsers.entities import parse_payload
from google.protobuf.message import DecodeError

SCOPE = 'disk_create_save_diff'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(data, field):
    return [(wire, payload, raw) for number, wire, payload, raw in builder.raw.spans(data)
            if number == field]


def one(data, field, wire=2):
    found = fields(data, field)
    require(len(found) == 1 and found[0][0] == wire,
            f'Expected one field {field} with wire type {wire}')
    return found[0][1]


def scalar(data, field):
    found = fields(data, field)
    require(len(found) == 1 and found[0][0] == 0,
            f'Expected one integer field {field}')
    encoded = found[0][2]
    _, pos = builder.raw._varint(encoded, 0)
    value, end = builder.raw._varint(encoded, pos)
    require(end == len(encoded), 'Invalid integer encoding')
    return value


def entity_records(payload):
    records = {}
    for number, wire, item, raw in builder.raw.spans(one(payload, 5)):
        if number != 1:
            continue
        require(wire == 2, 'Unsupported root5 entity wire type')
        entity_id = scalar(item, 1)
        require(0 < entity_id <= 0xffffffff and entity_id not in records,
                'Invalid or duplicate root5 entity ID')
        records[entity_id] = (item, raw)
    return records


def target_geometry(record):
    components = [payload for wire, payload, _ in fields(record, 6)
                  if wire == 2 and scalar(payload, 1) == 1]
    require(len(components) == 1, 'Target must have exactly one transform component')
    transform = one(components[0], 11)
    result = {}
    for index, name in enumerate(('position', 'rotation', 'scale'), 1):
        vector = one(transform, index)
        values = [0.0, 0.0, 0.0]  # Protobuf float defaults within a present vector.
        seen = set()
        for axis, wire, payload, _ in builder.raw.spans(vector):
            require(axis in (1, 2, 3) and wire == 5 and axis not in seen,
                    f'Unsupported or duplicate {name} axis encoding')
            seen.add(axis)
            values[axis - 1] = struct.unpack('<f', payload)[0]
        require(all(math.isfinite(v) for v in values), 'Nonfinite target geometry')
        result[name] = values
    return result


def directory(payload, target):
    section = one(payload, 6)
    categories = [item for wire, item, _ in fields(section, 1)
                  if wire == 2 and scalar(item, 1) == 3]
    require(len(categories) == 1, 'Unsupported directory: expected one entity category 3')
    category = categories[0]
    node = one(category, 3)
    matches = []
    for number, wire, item, raw in builder.raw.spans(node):
        if number == 5:
            require(wire == 2, 'Unsupported directory reference wire type')
            if scalar(item, 1) == 200 and scalar(item, 2) == target:
                matches.append(raw)
    return section, category, node, matches


def quantized_check(actual, expected, absolute):
    checks = []
    for axis, (observed, requested) in enumerate(zip(actual, expected)):
        require(math.isfinite(requested), 'Expected geometry must be finite')
        try:
            encoded = struct.pack('<f', requested)
        except OverflowError as exc:
            raise ValueError('Expected geometry must fit float32') from exc
        rounded = struct.unpack('<f', encoded)[0]
        require(math.isfinite(rounded), 'Expected geometry must fit finite float32')
        exponent = (struct.unpack('<I', encoded)[0] >> 23) & 255
        ulp = 2.0 ** (-149 if exponent == 0 else exponent - 127 - 23)
        tolerance = max(absolute, 2 * ulp)
        delta = abs(observed - rounded)
        require(delta <= tolerance,
                f'Geometry mismatch at axis {axis}: {observed} != {rounded} (tolerance {tolerance})')
        checks.append({'requested': requested, 'float32_expected': rounded,
                       'actual': observed, 'absolute_error': delta, 'tolerance': tolerance})
    return checks


def verify(args):
    data = [path.read_bytes() for path in (args.before, args.after)]
    headers = [builder.read_header(raw) for raw in data]
    for header, raw in zip(headers, data):
        require(header.file_type == 2, 'Input is not a native GIL container')
        require(header.version == 1, 'Unsupported GIL version; only evidenced version 1 is accepted')
        require(header.file_size == 20 + header.content_length and len(raw) == header.file_size + 4,
                'GIL container length mismatch or trailing bytes')
    require(headers[0].version == headers[1].version, 'GIL versions differ')
    payloads = [raw[20:-4] for raw in data]
    before, after = payloads
    level_ids = [fields(p, 1) for p in payloads]
    for p, ids in zip(payloads, level_ids):
        require(len(ids) <= 1, 'Duplicate optional root1 level ID')
        if ids:
            scalar(p, 1)  # Reject unknown wire types instead of guessing their semantics.
    require(level_ids[0] == level_ids[1], 'Optional root1 level ID changed')
    level = one(before, 2)
    require(level and level == one(after, 2), 'Level names differ or are empty')
    records_before, records_after = [entity_records(p) for p in payloads]
    target = args.entity_id
    require(target not in records_before, 'Expected entity ID already exists before creation')
    require(set(records_after) - set(records_before) == {target},
            'Expected exactly one newly added target entity')
    require(set(records_before) <= set(records_after), 'An existing entity was removed')
    target_record, target_raw = records_after[target]
    require(b''.join(raw for _, _, _, raw in builder.raw.spans(one(after, 5)) if raw != target_raw)
            == one(before, 5), 'Other entity records or root5 data changed')
    # Root27 uses a different placement schema. This verifier permits no change there.
    require(fields(before, 27) == fields(after, 27), 'Root27 placements changed')
    parsed = [parse_payload(p, file_type=2) for p in payloads]
    for entities in parsed:
        ids = [e.entity_id for e in entities]
        require(len(ids) == len(set(ids)), 'Duplicate entity IDs across GIL entity sections')
    before_ids = {e.entity_id for e in parsed[0]}
    after_ids = {e.entity_id for e in parsed[1]}
    require(target not in before_ids and after_ids - before_ids == {target},
            'Parsed entity set does not match a single creation')
    entity = next(e for e in parsed[1] if e.entity_id == target)
    require(entity.template_id == args.template_id, 'Target template ID mismatch')
    require(entity.name == args.name, 'Target name mismatch')
    # Do not allow parser defaults or ambiguous duplicate identity/name fields to pass.
    refs = fields(target_record, 2)
    direct = fields(target_record, 8)
    require(len(refs) <= 1 and len(direct) <= 1 and bool(refs or direct), 'Ambiguous template encoding')
    if refs:
        require(scalar(one(target_record, 2), 1) == args.template_id, 'Template reference mismatch')
    if direct:
        require(scalar(target_record, 8) == args.template_id, 'Direct template ID mismatch')
    names = [item for wire, item, _ in fields(target_record, 5)
             if wire == 2 and scalar(item, 1) == 1]
    require(len(names) == 1 and one(one(names[0], 11), 1).decode('utf-8') == args.name,
            'Target name is missing or ambiguous')
    actual = target_geometry(target_record)
    geometry = {name: quantized_check(actual[name], getattr(args, name), args.abs_tolerance)
                for name in ('position', 'rotation', 'scale')}
    initial_dir, _, _, initial_refs = directory(before, target)
    final_dir, category, node, final_refs = directory(after, target)
    require(not initial_refs and len(final_refs) == 1, 'Target directory registration is missing or duplicated')
    stripped_node = b''.join(raw for _, _, _, raw in builder.raw.spans(node) if raw != final_refs[0])
    stripped_dir = builder.replace_category(final_dir, builder.replace(category, 3, stripped_node))
    require(stripped_dir == initial_dir, 'Directory differs beyond the one target registration')
    require(fields(before, 10) == fields(after, 10), 'Old node graph section changed')
    changed_roots = sorted({f for p in payloads for f, _, _, _ in builder.raw.spans(p)
                            if fields(before, f) != fields(after, f)})
    return {'level_name': level.decode('utf-8'),
            'root1_optional_id': scalar(before, 1) if level_ids[0] else None,
            'entity_id': target, 'template_id': args.template_id,
            'name': args.name, 'entity_counts': [len(v) for v in parsed],
            'exactly_one_new_entity': True, 'other_entity_raw_records_preserved': True,
            'directory_target_registered': True, 'other_directory_bytes_preserved': True,
            'directory_schema': 'root6/f1[f1=3]/f3/f5[f1=200,f2=entity_id]',
            'old_node_graph_section_bytes_preserved': True,
            'geometry': geometry, 'changed_root_fields': changed_roots,
            'inputs': [{'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest()}
                       for p, raw in zip((args.before, args.after), data)],
            'limitations': ['Only the evidenced direct entity-directory category is supported; nested directories are not inferred.',
                            'Old graph bytes are preserved; graph execution and editor-visible state are not verified.',
                            'Other root sections may change and are listed, not assigned undocumented semantics.',
                            'Equal level names and optional root1 fields do not establish level identity or snapshot provenance.',
                            'Native snapshot provenance and the actor performing creation/save require separate evidence.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Required expectations use GIL transform units, with no angle conversion.
Geometry is compared to expected values rounded to IEEE float32, using
max(--abs-tolerance, two float32 ULPs) per axis. Default absolute tolerance: 1e-6.
Only evidenced GIL version 1 and a new root5 entity with a direct
category-3/type-200 directory entry are accepted. Optional root1 IDs must be
unique integers and unchanged; equal names/IDs do not authenticate the level.
Existing root5 records, root27 placements, directory data and root10
graphs must be unchanged after removing the single target addition.
Inputs are read only; no GIL is written. JSON output must be a new file beneath
the project .runtime/game-executor directory. Exit 0 = disk diff passes,
1 = verification rejected, 2 = invalid CLI/output. This never proves live-game
creation or background save, even when the disk diff passes.''')
    parser.add_argument('before', type=Path); parser.add_argument('after', type=Path)
    parser.add_argument('--entity-id', type=int, required=True)
    parser.add_argument('--template-id', type=int, required=True)
    parser.add_argument('--name', required=True)
    for name in ('position', 'rotation', 'scale'):
        parser.add_argument('--' + name, type=float, nargs=3, required=True, metavar=('X', 'Y', 'Z'))
    parser.add_argument('--abs-tolerance', type=float, default=1e-6,
                        help='Finite absolute tolerance in [0, 0.001], default 1e-6; two float32 ULPs also apply')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.before = args.before.resolve(); args.after = args.after.resolve(); args.out = args.out.resolve()
    if not (0 < args.entity_id <= 0xffffffff and 0 < args.template_id <= 0xffffffff):
        parser.error('Entity and template IDs must be nonzero uint32 values')
    if not args.name or not math.isfinite(args.abs_tolerance) or not 0 <= args.abs_tolerance <= .001:
        parser.error('Name must be nonempty; tolerance must be finite and within [0, 0.001]')
    if any(not math.isfinite(v) for name in ('position', 'rotation', 'scale') for v in getattr(args, name)):
        parser.error('Expected transform values must be finite')
    if any(v <= 0 for v in args.scale): parser.error('Expected scale must be positive')
    allowed = (ROOT / '.runtime/game-executor').resolve()
    if not args.out.is_relative_to(allowed) or args.out.suffix.lower() != '.json':
        parser.error('Output must be a new JSON file below .runtime/game-executor')
    if args.out.exists() or args.out in (args.before, args.after):
        parser.error('Refusing output overwrite or source write')
    report = {'scope': SCOPE, 'ok': False, 'game_runtime_verified': False,
              'background_save_verified': False, 'level_identity_verified': False,
              'snapshot_provenance_verified': False}
    try:
        report.update(verify(args)); report['ok'] = True
    except (ValueError, OSError, AssertionError, DecodeError, struct.error) as exc:
        report['error'] = str(exc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
