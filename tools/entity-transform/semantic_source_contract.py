"""Narrow the broader scenery conversion to the authored semantic assembly plan."""
from collections import Counter
from pathlib import Path
import json
import math
import sys
from contract import require, sha
import build as b


def check_saved(path,pairs,templates,ownership=None,level=None):
    from saved_assembly import records, component_ids, static_flag
    from contract import read
    if ownership:
        from ownership_contract import check
        check(ownership,level,path,templates,pairs=pairs,operation="convert")
    else:
        raise ValueError("EXPLICIT_OWNERSHIP_REQUIRED_IN_PUBLIC_RELEASE")
    raw,rows = records(Path(path))
    for eid,tag in templates.items():
        r = rows[eid]
        require(r.tag == tag and 20001000 <= tag < 20010000 and
                static_flag(r) == 1 and r.component(6,3).payload.data == b"",
                "SEMANTIC_SCENERY_NO_LOGIC_ONLY")
    counts = Counter(q["hostId"] for q in pairs)
    for host,count in counts.items():
        require(len(component_ids(rows[host].component(5,40),501))+count <= 999,
                "SEMANTIC_HOST_CAPACITY")
    distances=[]
    for q in pairs:
        source,host = rows[q["sourceId"]],rows[q["hostId"]]
        require(source.component(5,40).payload.data == b"", "SEMANTIC_SOURCE_STILL_OWNS_CHILDREN")
        require(source.component(6,22).payload.data == host.component(6,22).payload.data,
                "SEMANTIC_MATERIAL_INHERITANCE")
        scale = host.transform.scale.triple()
        require(min(scale)>0 and max(scale)-min(scale)<=.0001, "SEMANTIC_UNIFORM_HOST")
        a,z = source.transform.position.triple(),host.transform.position.triple()
        distances.append((math.hypot(a[0]-z[0],a[2]-z[2]),abs(a[1]-z[1])))
    require(max(x for x,y in distances) <= 200 and max(y for x,y in distances) <= 100,
            "SEMANTIC_SPATIAL_ENVELOPE")
    require(Path(path).read_bytes() == raw, "SEMANTIC_SAVE_CHANGED")
    return sha(path)


def patch_native(run):
    source = run/"candidate-source/entity-transform/native_assembly.cpp"
    text = source.read_text(encoding="utf-8")
    for old,new in (
        ("r.beforeCount>934","r.beforeCount>=999"),
        ("dx*dx+dz*dz>32*32||std::fabs(dy)>24",
         "dx*dx+dz*dz>SEMANTIC_MAX_DISTANCE*SEMANTIC_MAX_DISTANCE||std::fabs(dy)>SEMANTIC_MAX_HEIGHT")):
        require(text.count(old) == 1,"SEMANTIC_NATIVE_PATTERN")
        text = text.replace(old,new)
    source.write_text(text,encoding="utf-8")


def append_limits(run,pairs,save_path,compile_only):
    if compile_only:
        distance,height=200.,100.
    else:
        from saved_assembly import records
        _,rows = records(Path(save_path))
        spans=[]
        for q in pairs:
            a,z = rows[q["sourceId"]].transform.position.triple(),rows[q["hostId"]].transform.position.triple()
            spans.append((math.hypot(a[0]-z[0],a[2]-z[2]),abs(a[1]-z[1])))
        distance=max(x for x,y in spans)+.01
        height=max(y for x,y in spans)+.01
    with (run/"target_config.h").open("a",encoding="utf-8") as stream:
        stream.write(f"\n#define SEMANTIC_MAX_DISTANCE {distance:.9f}f\n#define SEMANTIC_MAX_HEIGHT {height:.9f}f\n")
