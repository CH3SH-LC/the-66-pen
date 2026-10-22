"""Strict, offline material/color contract. Native color is AARRGGBB, never RGBA."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import struct

LEVEL = 1073741843
MAX_BATCH = 32
MAX_SLOTS = 64
PRIMITIVES = (10009002, 10009003, 10009008, 10009009)
STATE_KEYS = ('material', 'enableMaterial', 'coverDecorationMaterial', 'coverDecorationColor', 'enableColor', 'argb', 'blendMode', 'rgb', 'alphaPercent')
PATCH_KEYS = ('material', 'enableMaterial', 'coverDecorationMaterial', 'coverDecorationColor', 'enableColor', 'rgba', 'blendMode')
MASKS = {k: 1 << i for i, k in enumerate(PATCH_KEYS)}

def require(ok, code):
    if not ok:
        raise ValueError(code)

def unique(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, 'DUPLICATE_JSON_KEY:' + k)
        result[k] = v
    return result

def read(path):
    raw = Path(path).read_bytes()
    require(len(raw) <= 32 * 1024 * 1024, 'JSON_TOO_LARGE')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))

def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def f32(value):
    require(type(value) in (int, float) and math.isfinite(value), 'FINITE_NUMBER_REQUIRED')
    result = struct.unpack('<f', struct.pack('<f', value))[0]
    require(math.isfinite(result), 'FINITE_FLOAT32_REQUIRED')
    return result

def identifier(value):
    require(type(value) is int and 0 < value <= 0xffffffff, 'POSITIVE_UINT32_REQUIRED')
    return value

def pack_rgba(rgba):
    require(type(rgba) is list and len(rgba) == 4 and all(type(x) is int and 0 <= x <= 255 for x in rgba), 'RGBA_FOUR_BYTE_INTEGERS_REQUIRED')
    r, g, b, a = rgba
    return (a << 24) | (r << 16) | (g << 8) | b

def rgba(argb):
    return [(argb >> n) & 255 for n in (16, 8, 0, 24)]

def valid_state(value):
    require(type(value) is dict and set(value) == set(STATE_KEYS), 'MATERIAL_STATE_FIELDS')
    out = dict(value)
    for k in ('enableMaterial', 'coverDecorationMaterial', 'coverDecorationColor', 'enableColor'):
        require(type(out[k]) is bool, 'MATERIAL_BOOLEAN:' + k)
    for k in ('material', 'blendMode', 'rgb'):
        require(type(out[k]) is int and -0x80000000 <= out[k] < 0x80000000, 'MATERIAL_INT32:' + k)
    require(type(out['argb']) is int and 0 <= out['argb'] <= 0xffffffff, 'MATERIAL_UINT32_ARGB')
    out['alphaPercent'] = f32(out['alphaPercent'])
    require(0 <= out['alphaPercent'] <= 100, 'ALPHA_PERCENT_RANGE')
    return out

def state_bytes(value):
    s = valid_state(value)
    return struct.pack('<i4BIiif', s['material'], s['enableMaterial'], s['coverDecorationMaterial'], s['coverDecorationColor'], s['enableColor'], s['argb'], s['blendMode'], s['rgb'], s['alphaPercent'])

def state_from_bytes(raw, offset=0):
    values = struct.unpack_from('<i4BIiif', raw, offset)
    require(all(v in (0, 1) for v in values[1:5]), 'NONBOOLEAN_NATIVE_STATE')
    return valid_state(dict(zip(STATE_KEYS, [values[0], *[bool(v) for v in values[1:5]], *values[5:]])))

def normalize(value):
    require(type(value) is dict and set(value) == {'schemaVersion', 'levelId', 'entities'}, 'REQUEST_FIELDS')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1 and value['levelId'] == LEVEL, 'REQUEST_LEVEL_OR_VERSION')
    require(type(value['entities']) is list and 1 <= len(value['entities']) <= MAX_BATCH, 'BATCH_SIZE_1_TO_32')
    seen = set()
    for item in value['entities']:
        require(type(item) is dict and set(item) <= {'entityId', *PATCH_KEYS} and len(item) > 1, 'ENTITY_PATCH_FIELDS')
        eid = identifier(item.get('entityId'))
        require(eid not in seen, 'DUPLICATE_ENTITY_ID')
        seen.add(eid)
        for k in ('enableMaterial', 'coverDecorationMaterial', 'coverDecorationColor', 'enableColor'):
            if k in item:
                require(type(item[k]) is bool, 'PATCH_BOOLEAN:' + k)
        if 'rgba' in item:
            pack_rgba(item['rgba'])
        if 'material' in item:
            require(type(item['material']) is int and item['material'] in (0, 6710, 6711), 'ONLY_NATIVE_DEFAULT_FROZEN_PETRIFIED_SUPPORTED')
        if 'blendMode' in item:
            require(type(item['blendMode']) is int and item['blendMode'] in (6700, 6701), 'NATIVE_BLEND_MODE_REQUIRED')
    return value

def merge(request, inspected):
    request = normalize(request)
    result = []
    for patch in request['entities']:
        eid = patch['entityId']
        require(eid in inspected, 'INSPECTION_TARGET_MISSING:' + str(eid))
        row = inspected[eid]
        require(row['configId'] in PRIMITIVES, 'UNREVIEWED_TEMPLATE')
        require(row['nativeBlocked'] == 0, 'TEMPLATE_BLOCKED_BY_NATIVE_MATERIAL_SYSTEM')
        before = valid_state(row['after'])
        desired = dict(before)
        mask = 0
        for k in PATCH_KEYS:
            if k not in patch:
                continue
            mask |= MASKS[k]
            if k == 'rgba':
                desired['argb'] = pack_rgba(patch[k])
                desired['rgb'] = desired['argb'] & 0xffffff
                # Native 862ce50: float32(alpha) / 255.0f * 100.0f.
                desired['alphaPercent'] = f32(f32(patch[k][3] / 255.0) * 100.0)
            else:
                desired[k] = patch[k]
        # The enabling flags apply to the main model. The two coverDecoration
        # flags only control propagation and are independent (c0e9920/e549d40).
        if desired['enableColor']:
            require(row['colorAllowed'] == 1, 'COLOR_OVERRIDE_UNSUPPORTED')
            require(desired['blendMode'] in row['allowedModes'], 'BLEND_NOT_ALLOWED_BY_TEMPLATE')
        if desired['enableMaterial']:
            require(desired['material'] in (6710, 6711) and desired['material'] in row['allowedMaterials'], 'MATERIAL_NOT_ALLOWED_BY_TEMPLATE')
        result.append(dict(entityId=eid, configId=row['configId'], expectedComponent=row['component'], mask=mask,
                           expected=before, desired=valid_state(desired)))
    return result

def shader_matches(state, slots):
    require(bool(slots), 'NO_RENDER_MATERIALS')
    for slot in slots:
        if state['enableColor']:
            require(slot['properties'] & 7 == 7, 'RENDERER_TINT_PROPERTIES_UNAVAILABLE')
            require(abs(slot['enable'] - 1.) < 0.0001 and abs(slot['blend'] - (state['blendMode'] == 6701)) < 0.0001, 'RENDERER_TINT_MODE_MISMATCH')
            require(all(abs(a - b / 255.) < 0.0001 for a, b in zip(slot['rgba'], rgba(state['argb']))), 'RENDERER_RGBA_MISMATCH')
        elif slot['properties'] & 1:
            require(abs(slot['enable']) < 0.0001, 'RENDERER_TINT_NOT_DISABLED')
        expected = 1 if state['enableMaterial'] and state['material'] == 6711 else 2 if state['enableMaterial'] and state['material'] == 6710 else 0
        require(slot['keywords'] == expected, 'RENDERER_MATERIAL_KEYWORD_MISMATCH')
    return True

def decode_extension(raw, snapshot_bytes):
    # Kept explicit, independent of C++ sizeof. Native static_assert guards ABI.
    row_size, guard_size = 8488, 88
    max_entities = 4096 if snapshot_bytes == 262584 else 512
    expected_size = 64 + MAX_BATCH * row_size + max_entities * guard_size + snapshot_bytes
    require(len(raw) == expected_size, 'MATERIAL_RECEIPT_SIZE')
    names = ('size','version','status','stage','seh','count','completed','sceneUnchanged','failedRva','failedValue','mode','nativeCalls','guardCount','guardsUnchanged','sharedMaterialsObserved','reserved')
    out = dict(zip(names, struct.unpack_from('<16I', raw)))
    require(out['size'] == len(raw) and out['version'] == 1 and 0 < out['count'] <= MAX_BATCH and out['guardCount'] <= max_entities, 'MATERIAL_RECEIPT_ABI')
    rows = []
    def slots(at, count):
        require(count <= MAX_SLOTS, 'RENDER_SLOT_LIMIT')
        entries = []
        for i in range(count):
            vals = struct.unpack_from('<QQIIII6fII', raw, at + i * 64)
            entries.append(dict(renderer=vals[0],material=vals[1],slot=vals[2],active=vals[3],enabled=vals[4],properties=vals[5],
                                enable=vals[6],blend=vals[7],rgba=list(vals[8:12]),keywords=vals[12],reserved=vals[13]))
        require(raw[at+count*64:at+MAX_SLOTS*64] == bytes((MAX_SLOTS-count)*64), 'UNUSED_SHADER_SLOTS_CHANGED')
        return entries
    for i in range(out['count']):
        at = 64 + i * row_size
        row = dict(zip(('entityId','configId','status','mask'), struct.unpack_from('<4I',raw,at)))
        row.update(zip(('owner','component','klass','unity','view','transaction','payload'),struct.unpack_from('<7Q',raw,at+16)))
        row.update((k,state_from_bytes(raw,at+72+j*24)) for j,k in enumerate(('before','desired','after')))
        row.update(zip(('stage','openCalled','snapshotCalled','deserializeCalled','notifyCalled','closeCalled','closed','refreshCalled','readbackVerified','shaderVerified','uncertain','pendingBefore','pendingSnapshot','pendingAfter','depthBefore','depthAfter','colorAllowed','materialCount','modeCount','beforeSlots','afterSlots','nativeBlocked'),struct.unpack_from('<22I',raw,at+144)))
        row['record'],row['beforeBlob']=struct.unpack_from('<2Q',raw,at+232)
        require(row['materialCount'] <= 4 and row['modeCount'] <= 4, 'NATIVE_CATALOG_LIMIT')
        row['allowedMaterials']=list(struct.unpack_from('<4i',raw,at+248)[:row['materialCount']])
        row['allowedModes']=list(struct.unpack_from('<4i',raw,at+264)[:row['modeCount']])
        row['beforeRender']=slots(at+296,row['beforeSlots'])
        row['afterRender']=slots(at+296+MAX_SLOTS*64,row['afterSlots'])
        row['guardBefore'],row['guardAfter']=struct.unpack_from('<2Q',raw,at+280)
        rows.append(row)
    require(raw[64+out['count']*row_size:64+MAX_BATCH*row_size] == bytes((MAX_BATCH-out['count'])*row_size),'UNUSED_ROWS_CHANGED')
    at = 64 + MAX_BATCH * row_size
    guards = []
    for i in range(out['guardCount']):
        off=at+i*guard_size
        g=dict(zip(('entityId','target'),struct.unpack_from('<2I',raw,off)))
        g.update(zip(('owner','component','rendererHashBefore','rendererHashAfter'),struct.unpack_from('<4Q',raw,off+8)))
        g['before']=state_from_bytes(raw,off+40);g['after']=state_from_bytes(raw,off+64)
        guards.append(g)
    require(raw[at+out['guardCount']*guard_size:at+max_entities*guard_size]==bytes((max_entities-out['guardCount'])*guard_size),'UNUSED_GUARDS_CHANGED')
    out.update(rows=rows,guards=guards)
    return out,raw[at+max_entities*guard_size:]
