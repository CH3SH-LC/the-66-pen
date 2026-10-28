"""Pure saved-scene geometry and accessory readers, extracted from proven assembly methods.

No author/installer imports, fixed level, current-state file, session or game calls.
Source conventions: assemble_street_models, finish_static_scenery and Unity Z-X-Y Euler.
"""
from collections import Counter
from pathlib import Path
import math
import sys
from contract import require

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/beyond-save"))
from gil_container import parse_fields, decode_container
from entity_geometry import EntityRecord, walk_fields, _make_component, _make_transform, read_entity_records_blob


def records(path):
    raw = Path(path).read_bytes()
    parsed = read_entity_records_blob(raw, str(path))
    result = {r.entity_id: r for r in parsed}
    require(len(result) == len(parsed), "DUPLICATE_ENTITY_IDS")
    return raw, result


def static_flag(row):
    component = row.component(5, 1)
    if component is None:
        return None
    fields = [f for f in parse_fields(component.payload.data) if f.number == 2]
    require(len(fields) <= 1, "DUPLICATE_STATIC_FIELD")
    if not fields:
        return 0
    require(fields[0].wire_type == 0 and fields[0].value in (0,1), "INVALID_STATIC_FIELD")
    return fields[0].value


class AccessoryRecord(EntityRecord):
    @property
    def tag(self):
        return next(f.value for f in self.fields if f.number == 2 and f.wire_type == 0)


def component_ids(component, number):
    require(component is not None, "ACCESSORY_COMPONENT_MISSING")
    out = []
    for f in parse_fields(component.payload.data):
        if f.number != number:
            continue
        if f.wire_type == 0:
            out.append(f.value)
        elif f.wire_type == 2:
            value = shift = 0
            for byte in f.data:
                value |= (byte & 127) << shift
                if byte < 128:
                    out.append(value)
                    value = shift = 0
                else:
                    shift += 7
                require(shift <= 35, "INVALID_ACCESSORY_ID")
            require(shift == 0, "INVALID_ACCESSORY_ID")
        else:
            raise ValueError("INVALID_ACCESSORY_ID_WIRE")
    return out


def accessories(raw):
    roots = [f for f in parse_fields(decode_container(raw).payload) if f.number == 27]
    require(len(roots) <= 1, "DUPLICATE_ACCESSORY_ROOT")
    result = {}
    for root in roots:
        for f in parse_fields(root.data):
            require(f.number == 2 and f.wire_type == 2, "ACCESSORY_ROOT_SCHEMA")
            eid = next(x.value for x in parse_fields(f.data) if x.number == 1)
            require(eid not in result, "DUPLICATE_ACCESSORY_RECORD")
            result[eid] = f.data
    return result


def nested_records(raw, wanted):
    found = {}
    def visit(data, path, depth):
        if depth > 12:
            return
        try:
            fields = parse_fields(data)
        except (ValueError, IndexError, OverflowError):
            return
        ids = [f.value for f in fields if f.number == 1 and f.wire_type == 0]
        if len(ids) == 1 and ids[0] in wanted and any(f.number == 2 and f.wire_type == 0 for f in fields):
            require({f.number for f in fields} <= {1,2,3,4,5,11,12}, "UNEXPECTED_ACCESSORY_SCHEMA")
            row = AccessoryRecord(index=0, key_offset=0, value_offset=0, fields=fields)
            for f in walk_fields(data):
                if f.number in (4,5):
                    row.components.append(_make_component(f.number+1, f))
            transform = row.component(6,1)
            if transform:
                row.transform = _make_transform(transform)
                require(ids[0] not in found, "DUPLICATE_ACCESSORY_RECORD")
                found[ids[0]] = (path, row)
                return
        counts = Counter()
        for f in fields:
            counts[f.number] += 1
            if f.wire_type == 2 and f.data:
                visit(f.data, path+[(f.number, counts[f.number]-1)], depth+1)
    visit(decode_container(raw).payload, [], 0)
    return found


def quat_mul(a, b):
    x,y,z,w = a
    u,v,t,s = b
    return w*u+x*s+y*t-z*v, w*v-x*t+y*s+z*u, w*t+x*v-y*u+z*s, w*s-x*u-y*v-z*t


def quat_xyzw(euler):
    x,y,z = [math.radians(a)/2 for a in euler]
    return quat_mul(quat_mul((0,math.sin(y),0,math.cos(y)),
                            (math.sin(x),0,0,math.cos(x))),
                    (0,0,math.sin(z),math.cos(z)))


def saved_world(host, child):
    h,c = host.transform, child.transform
    hq,cq = quat_xyzw(h.rotation.triple()), quat_xyzw(c.rotation.triple())
    hs,cs = h.scale.triple(), c.scale.triple()
    vector = tuple(a*b for a,b in zip(hs,c.position.triple()))+(0.,)
    rotated = quat_mul(quat_mul(hq,vector),(-hq[0],-hq[1],-hq[2],hq[3]))[:3]
    return dict(position=tuple(a+b for a,b in zip(h.position.triple(),rotated)),
                rotationQuaternion=quat_mul(hq,cq),scale=tuple(a*b for a,b in zip(hs,cs)))
