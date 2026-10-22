"""Pure transform request/receipt contracts. No process or file mutation on import."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import struct

MAX_BATCH = 128
POSE_KEYS = ('localPosition', 'rotationDegrees', 'scale', 'worldPosition')

def require(ok, code):
    if not ok:
        raise ValueError(code)

def unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'DUPLICATE_JSON_KEY:' + key)
        out[key] = value
    return out

def read(path):
    data = Path(path).read_bytes()
    require(len(data) <= 8 * 1024 * 1024, 'JSON_TOO_LARGE')
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))

def write(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def f32(value):
    require(type(value) in (int, float) and math.isfinite(value), 'FINITE_NUMBER_REQUIRED')
    try:
        result = struct.unpack('<f', struct.pack('<f', value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError('FLOAT32_OVERFLOW') from exc
    require(math.isfinite(result), 'FLOAT32_OVERFLOW')
    return result

def identifier(value):
    require(type(value) is int and 0 < value <= 0xffffffff, 'POSITIVE_UINT32_REQUIRED')
    return value

def normalize(value):
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'levelId', 'positionSpace', 'rotationUnit', 'entities'}, 'REQUEST_FIELDS')
    require(value['schemaVersion'] == 1, 'REQUEST_VERSION')
    identifier(value['levelId'])
    require(value['positionSpace'] in ('local', 'world'), 'POSITION_SPACE_REQUIRED')
    require(value['rotationUnit'] in ('degrees', 'radians'), 'ROTATION_UNIT_REQUIRED')
    require(isinstance(value['entities'], list) and 1 <= len(value['entities']) <= MAX_BATCH, 'BATCH_SIZE_1_TO_128')
    ids = set()
    entities = []
    for item in value['entities']:
        require(isinstance(item, dict) and set(item) <= {'entityId', 'position', 'rotation', 'scale'}, 'ENTITY_FIELDS')
        eid = identifier(item.get('entityId'))
        require(eid not in ids, 'DUPLICATE_ENTITY_ID')
        ids.add(eid)
        row = {'entityId': eid}
        for key in ('position', 'rotation', 'scale'):
            if key not in item:
                continue
            vector = item[key]
            require(isinstance(vector, list) and len(vector) == 3 and any(v is not None for v in vector), 'VECTOR3_OR_NULL_AXES_REQUIRED:' + key)
            row[key] = [None if v is None else f32(v) for v in vector]
            if key == 'scale':
                require(all(v is None or v > 0 for v in row[key]), 'POSITIVE_SCALE_REQUIRED')
        require(len(row) > 1, 'EMPTY_ENTITY_CHANGE')
        entities.append(row)
    return dict(value, entities=entities)

def valid_pose(value):
    require(isinstance(value, dict) and set(value) == set(POSE_KEYS), 'POSE_FIELDS')
    out = {}
    for key in POSE_KEYS:
        require(isinstance(value[key], list) and len(value[key]) == 3, 'POSE_VECTOR')
        out[key] = [f32(x) for x in value[key]]
    require(all(x > 0 for x in out['scale']), 'POSE_SCALE')
    return out

def merge(request, poses, origin, frames=None):
    request = normalize(request)
    require(len(origin) == 3, 'ORIGIN_VECTOR')
    origin = [f32(x) for x in origin]
    result = []
    for item in request['entities']:
        eid = item['entityId']
        require(eid in poses, 'INSPECTION_TARGET_MISSING:' + str(eid))
        before = valid_pose(poses[eid])
        frame = frames[eid] if frames is not None else dict(frameKind=1,parent=0)
        require(frame['frameKind'] in (1,2),'INSPECTION_FRAME_UNKNOWN')
        require(not ('position' in item and request['positionSpace'] == 'world' and frame['frameKind'] != 1),'NESTED_WORLD_POSITION_REQUIRES_PARENT_MATRIX')
        desired = {key: list(v) for key, v in before.items()}
        mask = 0
        for key, flag, native in (('position', 1, 'localPosition'), ('rotation', 2, 'rotationDegrees'), ('scale', 4, 'scale')):
            if key not in item:
                continue
            mask |= flag
            for axis, v in enumerate(item[key]):
                if v is None:
                    continue
                if key == 'position' and request['positionSpace'] == 'world':
                    v = f32(v - origin[axis])
                elif key == 'rotation' and request['rotationUnit'] == 'radians':
                    v = f32(v * 180.0 / math.pi)
                desired[native][axis] = f32(v)
        if frame['frameKind'] == 1:
            desired['worldPosition'] = [f32(desired['localPosition'][i] + origin[i]) for i in range(3)]
        result.append(dict(entityId=eid,mask=mask,expected=before,desired=valid_pose(desired),
                           expectedFrame=frame['frameKind'],expectedParent=frame['parent'],
                           requireRoot=int('position' in item and request['positionSpace']=='world'),
                           worldPositionPredicted=frame['frameKind']==1))
    return result

def near(a, b):
    return len(a) == len(b) and all(math.isfinite(x) and math.isfinite(y) and abs(x-y) <= 0.0001 for x,y in zip(a,b))

def same_pose(a, b, *, world=True):
    return all(near(a[k], b[k]) for k in (POSE_KEYS if world else POSE_KEYS[:3]))

def decode_pose(raw, offset):
    values = struct.unpack_from('<12f', raw, offset)
    return valid_pose({key: list(values[i*3:i*3+3]) for i,key in enumerate(POSE_KEYS)})

def decode_extension(raw, snapshot_bytes):
    require(len(raw) == 48 + MAX_BATCH * 280 + snapshot_bytes, 'TRANSFORM_RECEIPT_SIZE')
    names = ('size','version','status','stage','seh','count','completed','sceneUnchanged','failedRva','failedValue','mode','nativeCalls')
    result = dict(zip(names, struct.unpack_from('<12I', raw)))
    require(result['size'] == len(raw) and result['version'] == 1 and result['count'] <= MAX_BATCH, 'TRANSFORM_RECEIPT_ABI')
    rows = []
    for index in range(result['count']):
        at = 48 + index * 280
        row = dict(zip(('entityId','status','mask','called'), struct.unpack_from('<4I',raw,at)))
        row.update(zip(('owner','component','klass','unity','parent','transaction'), struct.unpack_from('<6Q',raw,at+16)))
        # Failed rows can contain zero/unwritten poses. Decode without asserting
        # positive scale; successful rows are validated separately by the caller.
        for i,key in enumerate(('before','desired','after')):
            vals = struct.unpack_from('<12f',raw,at+64+i*48)
            require(all(math.isfinite(v) for v in vals), 'RECEIPT_NONFINITE_POSE')
            row[key] = {name:list(vals[j*3:j*3+3]) for j,name in enumerate(POSE_KEYS)}
        row.update(zip(('stage','openCalled','snapshotCalled','notifyCalled','closeCalled','closed','readbackVerified','uncertain',
                        'pendingBefore','pendingSnapshot','pendingAfter','depthBefore','depthAfter','frameKind'),struct.unpack_from('<14I',raw,at+208)))
        row['record'],row['beforeBlob'] = struct.unpack_from('<2Q',raw,at+264)
        rows.append(row)
    require(raw[48+result['count']*280:48+MAX_BATCH*280] == bytes((MAX_BATCH-result['count'])*280), 'UNUSED_RECEIPT_ROWS_CHANGED')
    result['rows'] = rows
    return result, raw[48+MAX_BATCH*280:]
