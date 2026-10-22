"""Pure terrain plans and independent native-save verification; never writes a save.

Current-build evidence: CMHBFDDNDNO export 0x133f3340/0x133f3a30,
APACHJEHNKM writer 0x12779370. These establish fields 1..6, not just
the symmetric 20x20 starter terrain. Public coordinates are native X/Z.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/beyond-save'))
from gil_container import decode_container, parse_fields, encode_fields

MAX_CELLS = 65536
MAX_EDITS = 4096
LIMIT = 9999  # exclusive; native constants .cctor 0x7d22a90
SCHEMA = 'native-terrain-plan-v1'
NAMES = ('key', 'height', 'material', 'extraA', 'extraB', 'extraC')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def artifact_path(value):
    """Project runtime output only; reject junction/symlink redirection."""
    lexical = Path(value).absolute()
    for part in (lexical, *lexical.parents):
        if part.exists() or part.is_symlink():
            require(not part.is_symlink() and not (getattr(part.lstat(), 'st_file_attributes', 0) & 0x400), 'REPARSE_OUTPUT_PATH')
    resolved = lexical.resolve()
    require(resolved.is_relative_to((ROOT / '.runtime').resolve()), 'OUTPUT_MUST_BE_PROJECT_RUNTIME')
    return resolved

def digest(data):
    return hashlib.sha256(data).hexdigest()

def uint(value, label, maximum=0xffffffff):
    require(type(value) is int and 0 <= value <= maximum, f'{label}: expected integer 0..{maximum}')
    return value

def key(x, z):
    return uint(x, 'x', LIMIT - 1) | (uint(z, 'z', LIMIT - 1) << 16)

def present(row):
    return bool(row[1] or row[3] or row[5])

def canonical(fields):
    """Keep opaque fields byte-exact, but ignore protobuf field ordering."""
    return sorted(encode_fields([f]).hex() for f in fields)

def decode_save(blob):
    container = decode_container(blob)
    require(container.subtype == 2, 'NOT_LEVEL_CONTAINER')
    root = parse_fields(container.payload)
    f7 = [f for f in root if f.number == 7]
    require(len(f7) == 1 and f7[0].wire_type == 2, 'ONE_TERRAIN_LIST_REQUIRED')
    children = parse_fields(f7[0].data)
    terrains = []
    for entry in children:
        if entry.number != 1:
            continue
        require(entry.wire_type == 2, 'TERRAIN_ENTRY_WIRE')
        fields = parse_fields(entry.data)
        ids = [f.value for f in fields if f.number == 1 and f.wire_type == 0]
        require(len(ids) == 1, 'ONE_TERRAIN_ID_REQUIRED')
        rows, raw_cells, unknown = [], {}, []
        for f in fields:
            if f.number != 4:
                continue
            require(f.wire_type == 2, 'CELL_WIRE')
            parts = parse_fields(f.data)
            values = [0] * 6
            seen = set()
            for part in parts:
                if 1 <= part.number <= 6:
                    require(part.number not in seen and part.wire_type == 0, 'DUPLICATE_OR_INVALID_CELL_FIELD')
                    seen.add(part.number)
                    values[part.number - 1] = uint(part.value, 'cell field')
                else:
                    unknown.append({'key': values[0], 'field': part.number})
            k = values[0]
            require(k not in raw_cells, 'DUPLICATE_CELL_COORDINATE')
            require((k & 0xffff) < LIMIT and (k >> 16) < LIMIT, 'UNSUPPORTED_COORDINATE')
            require(values[1] < LIMIT, 'UNSUPPORTED_HEIGHT_ENCODING')
            require(present(values), 'SERIALIZED_EMPTY_CELL')
            raw_cells[k] = canonical(parts)
            rows.append(values)
        rows.sort()
        require(len(rows) <= MAX_CELLS, 'TERRAIN_CAPTURE_CAPACITY')
        terrains.append({'terrainId': ids[0], 'cells': rows,
                         'unknownCellFields': unknown, 'rawCells': raw_cells,
                         'otherFields': canonical([f for f in fields if f.number != 4]),
                         'raw': encode_fields([entry]).hex()})
    require(len({t['terrainId'] for t in terrains}) == len(terrains), 'DUPLICATE_TERRAIN_ID')
    return {'terrains': terrains,
            'otherRoot': {str(n): canonical([f for f in root if f.number == n])
                          for n in {f.number for f in root} if n != 7},
            'otherTerrainList': canonical([f for f in children if f.number != 1]),
            'sha256': digest(blob)}

def select(model, terrain_id):
    found = [t for t in model['terrains'] if t['terrainId'] == terrain_id]
    require(len(found) == 1, 'TERRAIN_ID_NOT_UNIQUE_OR_MISSING')
    return found[0]

def apply_edits(rows, edits, material_ids=None):
    require(type(edits) is list and 0 < len(edits) <= MAX_EDITS, f'EDITS_REQUIRED_1_TO_{MAX_EDITS}')
    current = {r[0]: list(r) for r in rows}
    materials = {r[2] for r in rows} if material_ids is None else {uint(x,'catalog material') for x in material_ids}
    changes, seen = [], set()
    for edit in edits:
        require(type(edit) is dict, 'UNKNOWN_EDIT_FIELD')
        surface=edit.get('op')=='surface'
        require(surface or set(edit) <= {'x', 'z', 'op', 'height', 'material'}, 'UNKNOWN_EDIT_FIELD')
        k = key(edit.get('x'), edit.get('z'))
        require(k not in seen, 'DUPLICATE_EDIT_COORDINATE')
        seen.add(k)
        before = current.get(k)
        op = edit.get('op', 'set')
        if surface:
            import terrain_shapes_v3
            after=terrain_shapes_v3.apply(before,k,edit,materials)
            current[k]=after
        elif op == 'delete':
            require(set(edit) <= {'x', 'z', 'op'} and before is not None, 'DELETE_REQUIRES_EXISTING_CELL_NO_VALUES')
            after = [k, 0, before[2], 0, 0, 0]
            del current[k]
        else:
            require(op == 'set' and ('height' in edit or 'material' in edit), 'SET_HEIGHT_OR_MATERIAL_REQUIRED')
            # New terrain cells copy an existing, observed material explicitly;
            # no guessed default brush or arbitrary material identifier.
            require(before is not None or ('height' in edit and 'material' in edit), 'NEW_CELL_REQUIRES_HEIGHT_AND_MATERIAL')
            after = list(before or [k, 0, 0, 0, 0, 0])
            if 'height' in edit:
                after[1] = uint(edit['height'], 'height', LIMIT - 1)
            if 'material' in edit:
                after[2] = uint(edit['material'], 'material')
                require(after[2] in materials, 'MATERIAL_MUST_BE_OBSERVED_IN_TARGET_TERRAIN' if material_ids is None else 'MATERIAL_NOT_IN_NATIVE_RENDERABLE_CATALOG')
            require(present(after), 'USE_DELETE_FOR_EMPTY_CELL')
            require(after != before, 'NO_OP_CELL_EDIT')
            current[k] = after
        changes.append({'op': op, 'key': k, 'before': before, 'after': after})
    require(len(current) <= MAX_CELLS, 'TERRAIN_CAPTURE_CAPACITY')
    return changes, sorted(current.values())

def make_plan(blob, terrain_id, edits, source=None, material_source=None):
    model = decode_save(blob)
    target = select(model, uint(terrain_id, 'terrainId'))
    require(not target['unknownCellFields'], 'UNKNOWN_CELL_FIELDS_REQUIRE_RESEARCH_BEFORE_WRITE')
    if material_source is not None:
        import terrain_catalog
        terrain_catalog.validate_authority(material_source,terrain_id)
    changes, expected = apply_edits(target['cells'], edits,None if material_source is None else material_source['materialIds'])
    result = {'schema': SCHEMA, 'terrainId': terrain_id, 'source': source,
            'sourceSha256': digest(blob), 'before': target['cells'],
            'edits': edits, 'changes': changes, 'expected': expected,
            'capabilities': ['cell-add', 'cell-delete', 'integer-height', 'observed-material'],
            'unprovenSemantics': ['continuous-height', 'slope', 'water', 'path'],
            'saveInvoked': False}
    if material_source is not None:
        result['materialSource']=material_source;result['capabilities']=['cell-add','cell-delete','integer-height','native-catalog-material','world-matrix-guard']
    import terrain_shapes_v3
    if terrain_shapes_v3.has_surface(edits):
        result['schema']=terrain_shapes_v3.SCHEMA
        result['shapeSemantics']=terrain_shapes_v3.binding()
        result['capabilities']+=['native-slope-type-and-direction','native-path']
        result['unprovenSemantics']=['continuous-height','water','slope-type-ui-labels']
        terrain_shapes_v3.requirements(result)
    return result

def validate_plan(plan, blob):
    import terrain_shapes_v3
    require(plan.get('schema') in (SCHEMA,terrain_shapes_v3.SCHEMA) and plan.get('sourceSha256') == digest(blob), 'PLAN_SOURCE_CHANGED')
    expected = make_plan(blob, plan['terrainId'], plan['edits'], plan.get('source'),plan.get('materialSource'))
    require(plan == expected, 'PLAN_CONTENT_CHANGED')
    return plan

def observed_root46_form(encoded_fields):
    """Recognize only the opaque form seen in three actual 1843 native saves.

    Runs 231810-a1096bee, 233854-4b688d50 and 234456-51ca20e3 show
    root46 -> field1 message -> fields1/2 uint64 changing. This establishes
    neither its semantics nor that arbitrary root46 changes are harmless.
    """
    if not isinstance(encoded_fields,list) or len(encoded_fields)!=1:return False
    try:
        root=parse_fields(bytes.fromhex(encoded_fields[0]))
        if len(root)!=1 or root[0].number!=46 or root[0].wire_type!=2:return False
        outer=parse_fields(root[0].data)
        if len(outer)!=1 or outer[0].number!=1 or outer[0].wire_type!=2:return False
        inner=parse_fields(outer[0].data)
        return (len(inner)==2 and {f.number for f in inner}=={1,2} and
                all(f.wire_type==0 and type(f.value) is int and 0<=f.value<2**64 for f in inner))
    except (ValueError,TypeError):return False

def verify_save(before_blob, after_blob, plan):
    validate_plan(plan, before_blob)
    result=verify_expected_save(before_blob,after_blob,plan['terrainId'],plan['expected'],{c['key'] for c in plan['changes']})
    if plan.get('shapeSemantics'):
        result.update(surfaceDataContentVerified=result['ok'],nativeSurfaceSaveVerified=False,
                      shapeSemantics=plan['shapeSemantics'],shapeVisualVerified=False,playerTraversalVerified=False)
    return result

def observed_engine_managed_form(encoded_fields, field_number):
    """Classify engine/session-managed root fields seen in real native saves.

    Evidence (env-verify, 2026-10-22, D-ENV-23)：真实地形 save 后仅 field7（地形内容）、
    field6（目录/页签 40→41 条，1439→1474B）、field46（存档历史头 1→2 条，22→44B）变化；
    实体表 field5 / 定义 field15 等逐字节相同。

    只接受**与真实观测一致的规模/形态**，并记录 before/after sha 与字节差，不做"一律放行"：
    小规模或形态不符（如实体目录的少量记录变化）一律不分类 ⇒ 继续 FAIL。
    """
    try:
        field_number = int(field_number)
    except (TypeError, ValueError):
        return None
    if not isinstance(encoded_fields, list) or not encoded_fields:
        return None
    if len(encoded_fields) > 8:
        return None
    counts, total = [], 0
    for hex_blob in encoded_fields:
        if not isinstance(hex_blob, str):
            return None
        try:
            outer = parse_fields(bytes.fromhex(hex_blob))
        except (ValueError, TypeError):
            return None
        if len(outer) != 1 or outer[0].number != field_number or outer[0].wire_type != 2:
            return None
        try:
            inner = parse_fields(outer[0].data)
        except (ValueError, TypeError):
            return None
        # 真实 field6 是 40 条目录记录（每条约 36B）；低于 20 条不视为同类目录形态
        if len(inner) < 20 or len(inner) > 4096:
            return None
        counts.append(len(inner))
        total += len(outer[0].data)
    if total < 512 or total > 1 << 20:
        return None
    if len(counts) == 2 and abs(counts[1] - counts[0]) > 2:
        return None  # 只允许"追加/极小改动"，禁止整体替换
    return {"rootField": field_number, "classification": "engine-managed",
            "semanticsVerified": False, "preservationVerified": False,
            "beforeRecordCount": counts[0] if counts else None,
            "afterRecordCount": counts[-1] if counts else None,
            "reason": "observed engine/session-managed directory form "
                      "(>=20 records, bounded size, record delta<=2); semantics unclassified (D-ENV-23)"}


def observed_save_history_form(before_fields, after_fields, field_number=46):
    """识别真实存档历史头形态（env-verify 真实样本 D-ENV-23 冻结夹具）。

    实测：root46 内是 repeated field1（wire2, 每条 20B 消息），save 后 **新头前插** ⇒ 1→2 条，
    字节 25→47（+22）。只接受该有界形态；其余仍走 legacy opaque 判定/FAIL。
    """
    try:
        field_number = int(field_number)
    except (TypeError, ValueError):
        return None
    if not (isinstance(before_fields, list) and isinstance(after_fields, list)
            and len(before_fields) == 1 and len(after_fields) == 1):
        return None
    counts, lengths = [], []
    for hex_blob in (before_fields[0], after_fields[0]):
        try:
            outer = parse_fields(bytes.fromhex(hex_blob))
        except (ValueError, TypeError):
            return None
        if len(outer) != 1 or outer[0].number != field_number or outer[0].wire_type != 2:
            return None
        try:
            inner = parse_fields(outer[0].data)
        except (ValueError, TypeError):
            return None
        if not inner or any(item.number != 1 or item.wire_type != 2 for item in inner):
            return None
        counts.append(len(inner))
        lengths.extend(len(item.data) for item in inner)
    before_bytes = len(bytes.fromhex(before_fields[0]))
    after_bytes = len(bytes.fromhex(after_fields[0]))
    if counts[1] != counts[0] + 1 or after_bytes - before_bytes not in (0, 22):
        return None
    return {"rootField": field_number, "classification": "engine-managed-history",
            "semanticsVerified": False, "preservationVerified": False,
            "beforeRecordCount": counts[0], "afterRecordCount": counts[1],
            "beforeBytes": before_bytes, "afterBytes": after_bytes,
            "recordLengthsEqual": len(set(lengths)) == 1,
            "reason": "observed save-history header form (repeated field1 messages, prepend +1 record, "
                      "+22 bytes; real D-ENV-23 fixture); semantics unclassified"}


def verify_expected_save(before_blob,after_blob,terrain_id,expected,changed):
    """Content comparison only. Caller must separately prove the complete plan."""
    before, after = decode_save(before_blob), decode_save(after_blob)
    a, b = select(before, terrain_id), select(after, terrain_id)
    failures = []
    if b['cells'] != expected:
        failures.append('TARGET_CELL_VALUES_DIFFER')
    if a['otherFields'] != b['otherFields']:
        failures.append('TARGET_NAME_OR_TRANSFORM_OR_OTHER_FIELDS_CHANGED')
    if {k:v for k,v in a['rawCells'].items() if k not in changed} != {k:v for k,v in b['rawCells'].items() if k not in changed}:
        failures.append('UNTOUCHED_CELL_FIELDS_CHANGED')
    if {t['terrainId']:t['raw'] for t in before['terrains'] if t['terrainId'] != terrain_id} != {t['terrainId']:t['raw'] for t in after['terrains'] if t['terrainId'] != terrain_id}:
        failures.append('OTHER_TERRAINS_CHANGED')
    root_changes = sorted(n for n in set(before['otherRoot']) | set(after['otherRoot']) if before['otherRoot'].get(n) != after['otherRoot'].get(n))
    # 逐字段语义分类（D-ENV-23）：timestamp(40) / engine-managed(6,46)；其余一律视为
    # 内容域或未知域 ⇒ 必须 FAIL（回归用例：实体/图/绑定/定义任一变化）。
    classifications = []
    unknown_changes = []
    for number in root_changes:
        record = {
            'rootField': int(number),
            'beforeBytes': len(before['otherRoot'].get(number) or []) and
                           sum(len(x) // 2 for x in before['otherRoot'].get(number) or []),
            'afterBytes': len(after['otherRoot'].get(number) or []) and
                          sum(len(x) // 2 for x in after['otherRoot'].get(number) or []),
            'beforeSha256': digest(bytes.fromhex(''.join(before['otherRoot'].get(number) or []))),
            'afterSha256': digest(bytes.fromhex(''.join(after['otherRoot'].get(number) or []))),
            'byteDelta': None,
            'classification': 'unknown',
            'semanticsVerified': False,
        }
        record['byteDelta'] = (record['afterBytes'] or 0) - (record['beforeBytes'] or 0)
        if number == '40':
            record.update(classification='timestamp', semanticsVerified=True,
                          reason='known save timestamp field 40 (pre-existing allowlist)')
            classifications.append(record)
            continue
        if number == '46':
            history = observed_save_history_form(before['otherRoot'].get('46'),
                                                 after['otherRoot'].get('46'), 46)
            if history:
                record.update(history)
                classifications.append(record)
                continue
        if number == '46' and all(observed_root46_form(m['otherRoot'].get('46')) for m in (before, after)):
            record.update(classification='engine-managed-opaque', semanticsVerified=False,
                          preservationVerified=False,
                          beforeEncodedFields=before['otherRoot'].get('46'),
                          afterEncodedFields=after['otherRoot'].get('46'),
                          reason='observed native-save opaque value changed (pre-existing classification); '
                                 'semantics remain unclassified')
            classifications.append(record)
            continue
        if number in ('6', '46'):
            engine = observed_engine_managed_form(before['otherRoot'].get(number), number)
            if engine and observed_engine_managed_form(after['otherRoot'].get(number), number):
                record.update(engine)
                classifications.append(record)
                continue
        record['reason'] = 'unclassified root-field change (content domain must be byte-identical)'
        classifications.append(record)
        unknown_changes.append(number)
    if unknown_changes:
        failures.append('UNRELATED_LEVEL_FIELDS_CHANGED')
    if before['otherTerrainList'] != after['otherTerrainList']:
        failures.append('TERRAIN_LIST_OTHER_FIELDS_CHANGED')
    engine_managed = [item['rootField'] for item in classifications
                      if item['classification'].startswith('engine-managed')]
    content_fields_unchanged = not unknown_changes
    semantics_verified = all(item['semanticsVerified'] for item in classifications)
    return {'ok': not failures, 'failures': failures, 'terrainId': terrain_id,
            'beforeSha256': digest(before_blob), 'afterSha256': digest(after_blob),
            'changedTopLevelFields': root_changes, 'cellCount': len(b['cells']),
            'fieldClassifications': classifications,
            'engineManagedFields': engine_managed,
            'contentDomainsByteIdentical': content_fields_unchanged,
            'engineManagedChangesAllowed': bool(engine_managed) and not unknown_changes,
            'unclassifiedSaveDifferences': [c for c in classifications
                                            if not c['semanticsVerified'] and
                                            c['classification'] in ('unknown', 'engine-managed-opaque')],
            'allSaveDomainsVerified': not failures and semantics_verified,
            'allOtherSavedFieldsPreserved': not failures and semantics_verified,
            'fileContentScope':'terrain-and-protected-domains','timestampField40Allowed':True,
            'fileContentVerified': not failures, 'nativeSaveVerified': False,
            'persistentSaveVerified': False, 'reopenVerified': False,
            'visualRebuildVerified': False, 'called': False, 'outcomeUncertain': False}
