"""Offline GIA builder for the MW static course asset pack.

Owned by tools/editor-bridge/build-static-course-asset.py. Derives 34 static
entity assets from the validated static GIL candidate's placement container
(field 27), clones the matching entity template out of the frozen 6-entity
mvp/build/platformer_min.gia pack, and writes:

    .runtime/editor-bridge/static-level-draft/MW_Static_Course_20260916.gia
    .runtime/editor-bridge/static-level-draft/asset-manifest.json

Candidate/offline output only: never stages, imports, deploys, or touches any
game/user directory. Unexpected input is a hard failure, never a guess.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.gi_file import GI_TYPE_GIA, read_header, read_payload, wrap_payload
from miliastra_agent.core.proto_gen import asset_pb2, entity_pb2 as eb, gia_pb2

TEMPLATE_GIA = ROOT / 'mvp/build/platformer_min.gia'
PLACEMENTS_GIL = ROOT / '.runtime/editor-bridge/static-level-draft/level-static-candidate.gil'
PLACEMENTS_MANIFEST = ROOT / '.runtime/editor-bridge/static-level-draft/manifest.json'
OUT_DIR = ROOT / '.runtime/editor-bridge/static-level-draft'
OUT_GIA = OUT_DIR / 'MW_Static_Course_20260916.gia'
OUT_MANIFEST = OUT_DIR / 'asset-manifest.json'

TEMPLATE_TOTAL = 6
ASSET_TOTAL = 34
PLACEMENT_FIELD = 27
NAME_RE = re.compile(r'^MW_Static_P(\d+)_Tile(\d+)$')


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


def records(data):
    """Strict raw protobuf -> [(field, wire, value, raw_span)] in order.

    value is the decoded varint for wire 0, the payload bytes for wire 2, and
    the fixed bytes otherwise. Unsupported records raise instead of guessing.
    """
    out, pos = [], 0
    while pos < len(data):
        start = pos
        tag, pos = _varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0 or wire not in (0, 1, 2, 5):
            raise ValueError(f'unsupported record field={field} wire={wire}')
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 2:
            size, pos = _varint(data, pos)
            value = data[pos:pos + size]
            pos += size
        elif wire == 1:
            value, pos = data[pos:pos + 8], pos + 8
        else:
            value, pos = data[pos:pos + 4], pos + 4
        if pos > len(data):
            raise ValueError('truncated record')
        out.append((field, wire, value, data[start:pos]))
    return out


def _fingerprint(asset):
    """Template identity ignoring per-asset id/name/transform payload."""
    probe = asset_pb2.Asset()
    probe.CopyFrom(asset)
    probe.meta.asset_id = 0
    probe.name = ''
    data = probe.entity_data.data
    data.entity_id = 0
    for prop in data.properties:
        if prop.WhichOneof('value') == 'name':
            prop.name.name = ''
    for comp in data.components:
        if comp.WhichOneof('component_data') == 'transform':
            comp.transform.position.Clear()
            comp.transform.rotation.Clear()
            comp.transform.scale.Clear()
    return probe.SerializeToString()


def load_templates():
    """template_id -> pristine Asset clone, plus the payloads stripped from it."""
    payload = read_payload(TEMPLATE_GIA)
    header = read_header(TEMPLATE_GIA.read_bytes())
    if header.file_type != GI_TYPE_GIA:
        raise SystemExit(f'template is not a GIA (file_type={header.file_type})')
    collection = gia_pb2.GIACollection()
    collection.ParseFromString(payload)
    if len(collection.Assets) != TEMPLATE_TOTAL:
        raise SystemExit(f'expected {TEMPLATE_TOTAL} template assets, found {len(collection.Assets)}')

    groups, stripped = {}, []
    for asset in collection.Assets:
        if asset.type != asset_pb2.Asset.ENTITY or asset.WhichOneof('value') != 'entity_data':
            raise SystemExit(f'template asset {asset.name!r} is not an entity asset')
        entity = asset.entity_data
        data = entity.data
        meta = asset.meta
        if meta.meta_type != asset_pb2.AssetMeta.ENTITY or meta.field_2 != 1:
            raise SystemExit(f'template asset {asset.name!r} has unexpected meta')
        if entity.field_2 != 0:
            raise SystemExit(f'template asset {asset.name!r} has unexpected entity field_2')
        if not (meta.asset_id == data.entity_id > 0):
            raise SystemExit(f'template asset {asset.name!r} id mismatch {meta.asset_id}/{data.entity_id}')
        tpl_id = entity.template_id
        if tpl_id <= 0 or data.template_id_ref != tpl_id or data.template.template_id != tpl_id \
                or data.template.field_2 != 1:
            raise SystemExit(f'template asset {asset.name!r} template refs are incoherent')
        if len(data.properties) != 1 or len(data.components) != 1:
            raise SystemExit(f'template asset {asset.name!r} has unexpected property/component counts')
        prop, comp = data.properties[0], data.components[0]
        if prop.property_type != eb.Property.NAME or prop.WhichOneof('value') != 'name' \
                or prop.name.static_block != eb.NameProperty.STATIC:
            raise SystemExit(f'template asset {asset.name!r} is not a STATIC name property')
        if comp.component_type != eb.Component.TRANSFORM \
                or comp.WhichOneof('component_data') != 'transform':
            raise SystemExit(f'template asset {asset.name!r} has no transform component')

        if len(asset.dependent_assets):
            stripped.append({'templateId': tpl_id, 'field': 'dependent_assets',
                             'count': len(asset.dependent_assets)})
            del asset.dependent_assets[:]
        if len(data.field_7):
            stripped.append({'templateId': tpl_id, 'field': 'entity_data.field_7',
                             'count': len(data.field_7)})
            del data.field_7[:]

        groups.setdefault(tpl_id, []).append(asset)

    templates = {}
    for tpl_id, group in groups.items():
        prints = {_fingerprint(a) for a in group}
        if len(prints) != 1:
            raise SystemExit(f'template id {tpl_id} has structurally ambiguous clones')
        templates[tpl_id] = min(group, key=lambda a: a.meta.asset_id)
    return templates, header, stripped


def parse_placement(raw, index):
    """One field-27 entry -> (entity_id, template_id, Property, Component)."""
    seen, entity_id, template_id, prop_raw, comp_raw = [], None, None, None, None
    for field, wire, value, _raw in records(raw):
        if field == 1 and wire == 0:
            entity_id, _ = value, seen.append(1)
        elif field == 2 and wire == 0:
            template_id, _ = value, seen.append(2)
        elif field == 4 and wire == 2:
            prop_raw, _ = value, seen.append(4)
        elif field == 5 and wire == 2:
            comp_raw, _ = value, seen.append(5)
        else:
            raise SystemExit(f'placement {index}: unexpected field {field} wire {wire}')
    if seen != [1, 2, 4, 5]:
        raise SystemExit(f'placement {index}: unexpected field sequence {seen}')
    prop, comp = eb.Property(), eb.Component()
    prop.ParseFromString(prop_raw)
    comp.ParseFromString(comp_raw)
    if prop.property_type != eb.Property.NAME or prop.WhichOneof('value') != 'name':
        raise SystemExit(f'placement {index}: not a name property')
    if prop.name.static_block != eb.NameProperty.STATIC:
        raise SystemExit(f'placement {index}: static_block is not STATIC')
    if comp.component_type != eb.Component.TRANSFORM \
            or comp.WhichOneof('component_data') != 'transform':
        raise SystemExit(f'placement {index}: not a transform component')
    return entity_id, template_id, prop, comp


def load_placements():
    """34 placements from the validated candidate GIL's field-27 container."""
    data = PLACEMENTS_GIL.read_bytes()
    header = read_header(data)
    if header.file_type != 2:
        raise SystemExit(f'placements source is not a GIL (file_type={header.file_type})')
    payload = read_payload(PLACEMENTS_GIL)
    if len(payload) != header.content_length:
        raise SystemExit('placements payload is truncated')
    if PLACEMENTS_MANIFEST.exists():
        expected = json.loads(PLACEMENTS_MANIFEST.read_text(encoding='utf-8')).get('output', {}).get('sha256')
        actual = hashlib.sha256(data).hexdigest()
        if expected and expected != actual:
            raise SystemExit(f'placements sha256 {actual} != manifest {expected}')

    containers = [value for field, wire, value, _ in records(payload)
                  if field == PLACEMENT_FIELD and wire == 2]
    if len(containers) != 1:
        raise SystemExit(f'expected exactly one field-{PLACEMENT_FIELD} container, found {len(containers)}')
    entries = [value for field, wire, value, _ in records(containers[0]) if field == 1 and wire == 2]
    if len(entries) != ASSET_TOTAL:
        raise SystemExit(f'expected {ASSET_TOTAL} placements, found {len(entries)}')

    placements, ids, names = [], set(), set()
    for index, raw in enumerate(entries):
        entity_id, template_id, prop, comp = parse_placement(raw, index)
        name = prop.name.name
        if not NAME_RE.match(name):
            raise SystemExit(f'placement {index}: unexpected name {name!r}')
        if entity_id in ids or name in names:
            raise SystemExit(f'placement {index}: duplicate entity id or name {entity_id}/{name!r}')
        ids.add(entity_id)
        names.add(name)
        placements.append({'entityId': entity_id, 'templateId': template_id,
                           'name': name, 'property': prop, 'component': comp})
    return placements, header, hashlib.sha256(data).hexdigest()


def build_assets(templates, placements):
    assets = []
    for placement in placements:
        tpl_id = placement['templateId']
        if tpl_id not in templates:
            raise SystemExit(f'no template clone for template_id {tpl_id} ({placement["name"]})')
        entity_id = placement['entityId']
        asset = asset_pb2.Asset()
        asset.CopyFrom(templates[tpl_id])
        asset.meta.asset_id = entity_id
        asset.name = placement['name']
        entity = asset.entity_data
        entity.template_id = tpl_id
        data = entity.data
        data.entity_id = entity_id
        data.template.template_id = tpl_id
        data.template_id_ref = tpl_id
        data.properties[0].CopyFrom(placement['property'])
        data.components[0].transform.CopyFrom(placement['component'].transform)
        assets.append(asset)
    return assets


def verify_output(path, placements):
    payload = read_payload(path)
    header = read_header(path.read_bytes())
    if header.file_type != GI_TYPE_GIA:
        raise SystemExit('output is not a GIA')
    collection = gia_pb2.GIACollection()
    collection.ParseFromString(payload)
    if len(collection.Assets) != ASSET_TOTAL:
        raise SystemExit(f'readback has {len(collection.Assets)} assets, expected {ASSET_TOTAL}')
    for expected, asset in zip(placements, collection.Assets):
        entity = asset.entity_data
        data = entity.data
        prop, comp = data.properties[0], data.components[0]
        checks = [
            (asset.meta.asset_id == expected['entityId'], 'asset_id'),
            (data.entity_id == expected['entityId'], 'entity_id'),
            (asset.name == expected['name'], 'asset name'),
            (entity.template_id == expected['templateId'], 'entity template_id'),
            (data.template.template_id == expected['templateId'], 'template ref'),
            (data.template_id_ref == expected['templateId'], 'template_id_ref'),
            (prop.name.name == expected['name'], 'name property'),
            (prop.name.static_block == eb.NameProperty.STATIC, 'static_block'),
            (comp.transform.SerializeToString()
             == expected['component'].transform.SerializeToString(), 'transform'),
            (len(data.properties) == 1 and len(data.components) == 1, 'component counts'),
            (not asset.dependent_assets and not data.field_7, 'stripped payloads'),
        ]
        failed = [label for ok, label in checks if not ok]
        if failed:
            raise SystemExit(f'readback mismatch for {expected["name"]}: {failed}')
    return collection


def main():
    if not OUT_DIR.resolve().is_relative_to(ROOT.resolve()):
        raise SystemExit('refusing to write outside the project')

    templates, template_header, stripped = load_templates()
    placements, gil_header, gil_sha = load_placements()
    assets = build_assets(templates, placements)

    collection = gia_pb2.GIACollection()
    for asset in assets:
        collection.Assets.add().CopyFrom(asset)
    payload = collection.SerializeToString()
    output = wrap_payload(payload, GI_TYPE_GIA, template_header.version)
    if not OUT_GIA.resolve().is_relative_to(ROOT.resolve()):
        raise SystemExit('refusing to write outside the project')
    OUT_GIA.write_bytes(output)

    verify_output(OUT_GIA, placements)

    usage = {}
    for placement in placements:
        usage[str(placement['templateId'])] = usage.get(str(placement['templateId']), 0) + 1
    manifest = {
        'kind': 'static-course-asset-pack', 'candidate': True, 'offline': True,
        'deploymentAllowed': False, 'gameAccepted': False, 'staged': False, 'imported': False,
        'assetCount': len(assets), 'templateCount': len(templates),
        'source': {
            'template': {'path': str(TEMPLATE_GIA.relative_to(ROOT)),
                         'sha256': hashlib.sha256(TEMPLATE_GIA.read_bytes()).hexdigest(),
                         'entities': TEMPLATE_TOTAL, 'version': template_header.version},
            'placements': {'path': str(PLACEMENTS_GIL.relative_to(ROOT)), 'sha256': gil_sha,
                           'fileType': gil_header.file_type, 'field': PLACEMENT_FIELD,
                           'entries': len(placements)},
        },
        'output': {'path': str(OUT_GIA.relative_to(ROOT)),
                   'sha256': hashlib.sha256(output).hexdigest(),
                   'bytes': len(output), 'payloadBytes': len(payload), 'fileType': GI_TYPE_GIA},
        'templateUsage': usage, 'strippedPayloads': stripped,
        'assets': [{'assetId': p['entityId'], 'entityId': p['entityId'], 'name': p['name'],
                    'templateId': p['templateId'],
                    'position': [p['component'].transform.position.x,
                                 p['component'].transform.position.y,
                                 p['component'].transform.position.z],
                    'rotation': [p['component'].transform.rotation.x,
                                 p['component'].transform.rotation.y,
                                 p['component'].transform.rotation.z],
                    'scale': [p['component'].transform.scale.x,
                              p['component'].transform.scale.y,
                              p['component'].transform.scale.z]}
                   for p in placements],
        'notes': [
            'Each asset clones an existing STATIC entity template from platformer_min.gia; defaults are copied, '
            'not invented.',
            'Position/rotation/scale are copied verbatim from the candidate GIL field-27 placement transform.',
            'Not game-verified: no staging, import, deploy, save, or playtest was performed.',
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': manifest['output'], 'assetCount': len(assets),
                      'templateUsage': usage, 'strippedPayloads': stripped,
                      'manifest': str(OUT_MANIFEST.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
