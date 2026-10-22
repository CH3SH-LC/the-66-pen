"""Offline static-level draft generator for the current save snapshot.

Owned by tools/editor-bridge/build-static-level-draft.py. Reads the frozen
level.gil snapshot, appends 34 static block placements under root field 27, and
removes exactly two runtime-spawn graph bindings from entity 1094713345.
Candidate/offline output only: never stages, imports, or touches game/user dirs.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.gi_file import GI_TYPE_GIL, read_header, wrap_payload
from miliastra_agent.core.proto_gen import entity_pb2 as eb
from miliastra_agent.core.wire import get_bytes_fields, get_varint
from miliastra_agent.parsers.entity_graph_bindings import parse_gil_entity_graph_bindings

try:  # gil.proto exists upstream; a generated gil_pb2 may or may not be present.
    from miliastra_agent.core.proto_gen import gil_pb2
except ImportError:  # pragma: no cover - fallback keeps this script runnable
    gil_pb2 = None

SOURCE = ROOT / '.runtime/editor-bridge/static-entity-research/current-level-snapshot/level.gil'
SCENE = ROOT / 'mvp/scene.json'
OUT_DIR = ROOT / '.runtime/editor-bridge/static-level-draft'
OUT_GIL = OUT_DIR / 'level-static-candidate.gil'
OUT_MANIFEST = OUT_DIR / 'manifest.json'
EXPECTED_SHA256 = '6651107185a50fc46c22cd3daf5dccfdbebbc29bd6acfce9003752df1de5e3db'
TARGET_ENTITY = 1094713345
REMOVE_GRAPHS = (1073741825, 1073741826)
KEEP_GRAPH = 1073741827
FIRST_ID = 1078001000
TILE_TOTAL, PLATFORM_TOTAL = 34, 6
REMOVED = []


def _varint(data, pos):
    value = shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            break
    raise ValueError('truncated varint')


def _enc_varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def spans(data):
    """Strict raw protobuf spans -> (field, wire, payload, raw_bytes) in order."""
    out, pos = [], 0
    while pos < len(data):
        start = pos
        tag, pos = _varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0 or wire not in (0, 1, 2, 5):
            raise ValueError(f'unsupported record field={field} wire={wire}')
        if wire == 0:
            _, pos = _varint(data, pos)
            payload = None
        elif wire == 2:
            size, pos = _varint(data, pos)
            payload = data[pos:pos + size]
            pos += size
        elif wire == 1:
            payload, pos = data[pos:pos + 8], pos + 8
        else:
            payload, pos = data[pos:pos + 4], pos + 4
        if pos > len(data):
            raise ValueError('truncated record')
        out.append((field, wire, payload, data[start:pos]))
    return out


def rec(field, payload):
    return _enc_varint(field << 3 | 2) + _enc_varint(len(payload)) + payload


def recv(field, value):
    return _enc_varint(field << 3 | 0) + _enc_varint(value)


def join(records):
    return b''.join(records)


def strip_graph_refs(blob):
    """Drop ref records whose graph id is a spawn graph; keep every other raw record."""
    out = []
    for field, wire, payload, raw in spans(blob):
        if field == 1 and wire == 2:
            kept, dropped = [], []
            for rfield, rwire, rpayload, rraw in spans(payload):
                graph_id = get_varint(rpayload, 2) if (rfield == 1 and rwire == 2) else None
                if graph_id in REMOVE_GRAPHS:
                    dropped.append(graph_id)
                else:
                    kept.append(rraw)
            if dropped:
                REMOVED.extend(dropped)
                out.append(rec(field, join(kept)))
                continue
        out.append(raw)
    return join(out)


def patch_component(component):
    out = []
    for field, wire, payload, raw in spans(component):
        if field == 13 and wire == 2:
            out.append(rec(13, strip_graph_refs(payload)))
        else:
            out.append(raw)
    return join(out)


def patch_entity(entity):
    out = []
    for field, wire, payload, raw in spans(entity):
        if field == 6 and wire == 2 and get_varint(payload, 1) == 3:
            out.append(rec(6, patch_component(payload)))
        else:
            out.append(raw)
    return join(out)


def patch_logic(container):
    out = []
    for field, wire, payload, raw in spans(container):
        if field == 1 and wire == 2 and get_varint(payload, 1) == TARGET_ENTITY:
            out.append(rec(1, patch_entity(payload)))
        else:
            out.append(raw)
    return join(out)


def patch_root(payload, entries):
    out = []
    for field, wire, payload_bytes, raw in spans(payload):
        if field == 5 and wire == 2:
            out.append(rec(5, patch_logic(payload_bytes)))
        elif field == 27 and wire == 2:
            out.append(rec(27, join(rec(1, entry) for entry in entries)))
        else:
            out.append(raw)
    return join(out)


def make_entry(entity_id, template_id, name, position):
    prop = eb.Property()
    prop.property_type = eb.Property.PropertyType.NAME
    prop.name.name = name
    prop.name.static_block = eb.NameProperty.StaticBlock.STATIC
    component = eb.Component()
    component.component_type = eb.Component.ComponentType.TRANSFORM
    component.transform.position.CopyFrom(eb.Position(x=position[0], y=position[1], z=position[2]))
    component.transform.rotation.CopyFrom(eb.Rotation(x=0.0, y=0.0, z=0.0))
    component.transform.scale.CopyFrom(eb.Scale(x=1.0, y=1.0, z=1.0))
    if gil_pb2 is not None:
        placement = gil_pb2.GilPlacement(entity_id=entity_id, template_id=template_id)
        placement.properties.add().CopyFrom(prop)
        placement.components.add().CopyFrom(component)
        return placement.SerializeToString()
    return recv(1, entity_id) + recv(2, template_id) + rec(4, prop.SerializeToString()) + rec(5, component.SerializeToString())


def build_placements():
    scene = json.loads(SCENE.read_text(encoding='utf-8-sig'))
    platforms = scene['entities']
    if len(platforms) != PLATFORM_TOTAL:
        raise ValueError(f'expected {PLATFORM_TOTAL} platforms, found {len(platforms)}')
    entries, tiles, index = [], [], 0
    for platform in platforms:
        width, depth = int(platform['scale'][0]), int(platform['scale'][2])
        if width not in (2, 3) or depth != width:
            raise ValueError(f'unsupported footprint {width}x{depth}')
        for x in range(width):
            for z in range(depth):
                dx, dz = x - (width - 1) / 2, z - (depth - 1) / 2
                position = [platform['position'][0] + dx, platform['position'][1], platform['position'][2] + dz]
                entity_id = FIRST_ID + index
                name = f"MW_Static_P{platform['index']}_Tile{x * depth + z}"
                entries.append(make_entry(entity_id, platform['template_id'], name, position))
                tiles.append({'entityId': entity_id, 'platform': platform['index'], 'name': name,
                              'templateId': platform['template_id'], 'position': position})
                index += 1
    if index != TILE_TOTAL:
        raise ValueError(f'expected {TILE_TOTAL} tiles, built {index}')
    return entries, tiles


def main():
    if not OUT_DIR.resolve().is_relative_to(ROOT.resolve()):
        raise SystemExit('refusing to write outside the project')
    data = SOURCE.read_bytes()
    if hashlib.sha256(data).hexdigest() != EXPECTED_SHA256:
        raise SystemExit('unexpected source sha256')
    header = read_header(data)
    if header.file_type != GI_TYPE_GIL:
        raise SystemExit(f'unexpected file type {header.file_type}, expected GIL')
    payload = data[20:20 + header.content_length]
    if len(payload) != header.content_length:
        raise SystemExit('truncated payload')

    containers = get_bytes_fields(payload, 27)
    if len(containers) != 1 or containers[0] != b'':
        raise SystemExit('expected exactly one empty placement container')
    existing = {get_varint(item, 1) for chunk in (5, 27) for record in get_bytes_fields(payload, chunk)
                for item in get_bytes_fields(record, 1) if get_varint(item, 1) is not None}
    bindings = parse_gil_entity_graph_bindings(payload)
    target = [b for b in bindings if b.entity_id == TARGET_ENTITY]
    removed = [b for b in target if b.graph_id in REMOVE_GRAPHS]
    stray = [b for b in bindings if b.entity_id != TARGET_ENTITY and b.graph_id in REMOVE_GRAPHS]
    if stray:
        raise SystemExit('spawn graph referenced outside the level entity')
    if len(target) != 3 or len(removed) != len(REMOVE_GRAPHS):
        raise SystemExit(f'unexpected target binding counts: {[b.graph_id for b in target]}')

    entries, tiles = build_placements()
    if existing & {t['entityId'] for t in tiles}:
        raise SystemExit('new entity ids collide with existing ids')

    patched = patch_root(payload, entries)
    if sorted(REMOVED) != sorted(REMOVE_GRAPHS):
        raise SystemExit(f'unexpected removed graph set {REMOVED}')
    after = parse_gil_entity_graph_bindings(patched)
    kept = [b for b in after if b.entity_id == TARGET_ENTITY]
    if len(kept) != 1 or kept[0].graph_id != KEEP_GRAPH:
        raise SystemExit(f'unexpected post-patch bindings {[b.graph_id for b in kept]}')

    before_spans, after_spans = spans(payload), spans(patched)
    if [s[0] for s in before_spans] != [s[0] for s in after_spans]:
        raise SystemExit('root field sequence changed')
    for old, new in zip(before_spans, after_spans):
        if old[0] not in (5, 27) and old[3] != new[3]:
            raise SystemExit(f'root field {old[0]} not byte-preserving')

    output = wrap_payload(patched, GI_TYPE_GIL, header.version)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_GIL.write_bytes(output)
    manifest = {
        'kind': 'static-level-draft', 'candidate': True, 'offline': True,
        'deploymentAllowed': False, 'gameAccepted': False, 'staged': False, 'imported': False,
        'source': {'path': str(SOURCE.relative_to(ROOT)), 'sha256': EXPECTED_SHA256,
                   'bytes': len(data), 'fileType': header.file_type},
        'output': {'path': str(OUT_GIL.relative_to(ROOT)),
                   'sha256': hashlib.sha256(output).hexdigest(), 'bytes': len(output)},
        'tiles': TILE_TOTAL, 'platforms': PLATFORM_TOTAL,
        'removedBindings': [{'entityId': b.entity_id, 'graphId': b.graph_id, 'slot': b.slot,
                             'field501': b.field_501} for b in removed],
        'keptBindings': [{'entityId': b.entity_id, 'graphId': b.graph_id, 'slot': b.slot,
                          'field501': b.field_501} for b in kept],
        'placementEntries': tiles, 'graphDefinitionsUnchanged': True,
        'notes': ['Static placements use scale [1,1,1] at scene centers + tile offsets; footprint widths 2 and 3 only.',
                  'Graph bindings 1073741825/1073741826 removed on entity 1094713345 only; node graphs untouched.',
                  'Not game-verified: no staging, import, save, or playtest was performed.'],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': manifest['output'], 'tiles': TILE_TOTAL, 'platforms': PLATFORM_TOTAL,
                      'removedGraphs': REMOVED, 'keptGraphs': [b.graph_id for b in kept]}))


if __name__ == '__main__':
    main()
