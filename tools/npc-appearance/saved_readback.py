"""Independent raw GIL association readback; no save or runtime claim."""
import struct
from pathlib import Path
from official_models import require, sha, Catalog
from native_catalog import Reader
from primary_index import varint


def spans(data):
    r = Reader(data)
    rows = []
    while r.p < len(data):
        start = r.p
        tag = varint(r)
        number, wire = tag >> 3, tag & 7
        require(0 < number < 1 << 29, 'WIRE_FIELD_NUMBER')
        if wire == 0:
            value = varint(r)
        elif wire == 2:
            value = r.take(varint(r))
        elif wire in (1, 5):
            value = r.take(8 if wire == 1 else 4)
        else:
            raise ValueError('WIRE_TYPE_UNSUPPORTED')
        rows.append((number, wire, value, data[start:r.p]))
        require(len(rows) <= 2000000, 'WIRE_FIELD_BUDGET')
    return rows


def one(data, number, wire):
    found = [v for f, w, v, _ in spans(data) if f == number]
    kinds = [w for f, w, v, _ in spans(data) if f == number]
    require(len(found) == 1 and kinds == [wire], 'SAVED_FIELD_NOT_UNIQUE:' + str(number))
    return found[0]


def records(payload, root):
    result = {}
    for f, w, data, raw in spans(one(payload, root, 2)):
        if f != 1:
            continue
        require(w == 2, 'SAVED_RECORD_WIRE')
        identifier = one(data, 1, 0)
        require(type(identifier) is int and 0 < identifier <= 0xffffffff and
                identifier not in result, 'SAVED_DUPLICATE_OR_INVALID_ID')
        result[identifier] = data
    return result


def component_evidence(data, field):
    rows = []
    for f, w, component, _ in spans(data):
        if f != field:
            continue
        require(w == 2, 'SAVED_COMPONENT_WIRE')
        rows.append(dict(kind=one(component, 1, 0), rawSha256=sha(component),
                         rawHex=component.hex()))
    return rows


def inspect(path, expected_sha, entity_ids, catalog=None):
    path = Path(path).resolve()
    require(path.is_file() and 24 <= path.stat().st_size <= 128 * 1024 * 1024,
            'SAVED_INPUT_SIZE')
    raw = path.read_bytes()
    require(sha(raw) == expected_sha, 'SAVED_INPUT_SHA_MISMATCH')
    size, version, magic, filetype, length = struct.unpack('>5I', raw[:20])
    require(magic == 0x326 and filetype == 2 and version == 1 and
            size == 20 + length and len(raw) == size + 4 and
            raw[-4:] == struct.pack('>I', 0x679), 'SAVED_GIL_CONTAINER')
    require(entity_ids and len(entity_ids) <= 4096 and
            len(set(entity_ids)) == len(entity_ids), 'SAVED_SELECTION_INVALID')
    payload = raw[20:-4]
    entities, templates = records(payload, 5), records(payload, 4)
    associations = []
    for eid in entity_ids:
        require(eid in entities, 'SAVED_ENTITY_NOT_FOUND:' + str(eid))
        entity = entities[eid]
        template_id = one(one(entity, 2, 2), 1, 0)
        if template_id in templates:
            template = templates[template_id]
            official_id = one(template, 2, 0)
            template_evidence = dict(templateId=template_id, rawSha256=sha(template),
                rawHex=template.hex(), components=component_evidence(template, 6))
        else:
            official_id = template_id
            template_evidence = None
        associations.append(dict(entityId=eid, templateId=template_id,
            officialTemplateId=official_id, rawEntitySha256=sha(entity), rawEntityHex=entity.hex(),
            savedTemplate=template_evidence,
            instanceComponents=component_evidence(entity, 6)))
    catalog = catalog or Catalog()
    resolved = catalog.resolve(list(dict.fromkeys(x['officialTemplateId'] for x in associations)))
    by_id = {x['templateId']:x for x in resolved['rows']}
    for row in associations:
        row['baseModel'] = by_id[row['officialTemplateId']]
        row['effectiveAppearanceVerified'] = False
        row['uninterpretedAppearanceOverridesPossible'] = True
    require(sha(path.read_bytes()) == expected_sha, 'SAVED_INPUT_CHANGED')
    return dict(kind='npc-appearance-saved-base-readback-v1', ok=True,
        source=dict(path=str(path), sha256=expected_sha, bytes=len(raw)), rows=associations,
        modelScope='Base identity only; instance/template properties are retained raw and may override it',
        gameProcessAccessed=False, nativeCalled=False, gameWritesPerformed=False,
        nativeSavePerformed=False, liveReadbackPerformed=False, appearanceVerified=False)
