"""Guarded disk repair for the six identified MVP pads in level 1073741833.

prepare never writes the live save. apply requires the prepared baseline to match
byte for byte; the operator must first leave the level to avoid stale RAM writes.
This is not the game's validation and never claims playtest success.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/beyond-save'))
sys.path.insert(0, str(ROOT / 'tools/compatibility'))
from version_guard import IncompatibleVersion, require_compatible
import gil_container as codec

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

v = module('mvp_geometry_verifier', ROOT / 'tools/game-executor/verify-created-save.py')
audit = module('mvp_graph_reader', Path(__file__).with_name('audit-native-enums.py'))
TARGETS = tuple(range(1077936129, 1077936135))
XS = (0., 9.5, 17.5, 25.5, 33.5, 43.)
NAME = 'MW_MVP_Course_20260922'
LIVE = Path(os.environ['USERPROFILE']) / 'AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/Beyond_Local_Save_Level/1073741833.gil'

def require(ok, reason):
    if not ok:
        raise ValueError(reason)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def fields(raw):
    result = codec.parse_fields(raw)
    require(codec.encode_fields(result) == raw, 'Non-lossless protobuf roundtrip')
    return result

def single(items, number, wire):
    found = [f for f in items if f.number == number]
    require(len(found) == 1 and found[0].wire_type == wire, f'Expected single field {number}/{wire}')
    return found[0]

def replace_nested(raw, path, fn):
    if not path:
        return fn(raw)
    fs = fields(raw)
    target = single(fs, path[0], 2)
    target.data = replace_nested(target.data, path[1:], fn)
    return codec.encode_fields(fs)

def repair(data, old_z=-50., new_z=0.):
    container = codec.decode_container(data)
    require(container.subtype == 2, 'Expected level GIL')
    root = fields(container.payload)
    entities = v.entity_records(container.payload)
    require(len(entities) == 17 and set(TARGETS) <= entities.keys(), 'Unexpected entity set')
    changes = []
    section = single(root, 5, 2)
    entity_fields = fields(section.data)
    for field in entity_fields:
        if field.number != 1 or field.wire_type != 2:
            continue
        entity = fields(field.data)
        eid = single(entity, 1, 0).value
        if eid not in TARGETS:
            continue
        i = TARGETS.index(eid)
        geo = v.target_geometry(field.data)
        expected = [XS[i], struct.unpack('<f', struct.pack('<f', i*.4))[0], old_z]
        require(geo['position'] == expected, f'Unexpected source position for {eid}')
        require(geo['rotation'] == [0., 0., 0.], f'Unexpected rotation for {eid}')
        expected_scale = 1.8 if i in (0, 5) else 1.2
        require(all(abs(a-b) < 1e-6 for a,b in zip(geo['scale'], [expected_scale,.1,expected_scale])), 'Unexpected scale')
        comps = [f for f in entity if f.number == 6 and f.wire_type == 2
                 and single(fields(f.data), 1, 0).value == 1]
        require(len(comps) == 1, 'Expected one transform component')
        def position(raw):
            fs = fields(raw)
            z = single(fs, 3, 5)
            require(z.value == struct.unpack('<I', struct.pack('<f', old_z))[0], 'Unexpected Z bits')
            z.value = struct.unpack('<I', struct.pack('<f', new_z))[0]
            return codec.encode_fields(fs)
        comps[0].data = replace_nested(comps[0].data, (11,1), position)
        field.data = codec.encode_fields(entity)
        changes.append({'entity':eid, 'before':geo['position'], 'after':expected[:2]+[new_z]})
    require(len(changes) == 6, 'Expected six geometry changes')
    section.data = codec.encode_fields(entity_fields)
    graph_count = 0
    for group in root:
        if group.number != 10:
            continue
        wrappers = fields(group.data)
        for wrapper in wrappers:
            if wrapper.number != 1 or wrapper.wire_type != 2:
                continue
            graph_fields = fields(wrapper.data)
            for entry in graph_fields:
                if entry.number != 1 or entry.wire_type != 2:
                    continue
                graph = audit.pb.NodeGraph()
                graph.ParseFromString(entry.data)
                require(graph.display_name == NAME and graph.identity.runtime_id == 1073741825
                        and len(graph.nodes) == 29, 'Unexpected graph identity or shape')
                require(graph.SerializeToString() == entry.data, 'Graph must roundtrip losslessly')
                for index in (14,28):
                    nodes = [n for n in graph.nodes if n.index == index and n.shell_ref.runtime_id == 225]
                    require(len(nodes) == 1, 'Expected goal/respawn vector node')
                    pins = [p for p in nodes[0].pins if p.shell_sig.kind == 3 and p.shell_sig.index == 2]
                    require(len(pins) == 1 and not pins[0].connections and pins[0].type == 5, 'Unexpected Z pin')
                    value = pins[0].value.val_float
                    require(getattr(value,'float') == old_z, 'Unexpected graph Z constant')
                    setattr(value,'float',new_z)
                entry.data = graph.SerializeToString()
                graph_count += 1
            wrapper.data = codec.encode_fields(graph_fields)
        group.data = codec.encode_fields(wrappers)
    require(graph_count == 1, 'Expected one graph')
    payload = codec.encode_fields(root)
    result = codec.encode_container(codec.Container(container.subtype,payload,container.version,container.magic,container.trailer))
    require([(n,r) for n,w,b,r in v.builder.raw.spans(container.payload) if n not in (5,10)] ==
            [(n,r) for n,w,b,r in v.builder.raw.spans(payload) if n not in (5,10)], 'Unrelated root change')
    updated = v.entity_records(payload)
    require(all(updated[e] == entities[e] for e in entities if e not in TARGETS), 'Unrelated entity change')
    return result, changes

def inspect_state(data):
    """Semantic readback tolerates native omission of zero-valued fields."""
    container = codec.decode_container(data)
    require(container.subtype == 2, 'Expected level GIL')
    root = fields(container.payload)
    require(single(root,2,2).text() == '自定义页签_3_存档', 'Unexpected level name')
    entities = v.entity_records(container.payload)
    require(len(entities)==17 and set(TARGETS)<=entities.keys(), 'Unexpected entity set')
    positions = {}
    for i,eid in enumerate(TARGETS):
        geo = v.target_geometry(entities[eid][0])
        require(abs(geo['position'][0]-XS[i])<1e-6 and abs(geo['position'][1]-i*.4)<1e-6,
                f'Unexpected platform X/Y: {eid}')
        width = 1.8 if i in (0,5) else 1.2
        require(geo['rotation']==[0.,0.,0.] and all(abs(a-b)<1e-6 for a,b in zip(geo['scale'],[width,.1,width])),
                f'Unexpected platform transform: {eid}')
        positions[str(eid)] = geo['position']
    graphs=[]
    for group in root:
        if group.number==10 and group.wire_type==2:
            for wrapper in fields(group.data):
                if wrapper.number==1 and wrapper.wire_type==2:
                    for entry in fields(wrapper.data):
                        if entry.number==1 and entry.wire_type==2:
                            graph=audit.pb.NodeGraph();graph.ParseFromString(entry.data);graphs.append(graph)
    require(len(graphs)==1, 'Expected one graph')
    graph=graphs[0]
    require(graph.display_name==NAME and graph.identity.runtime_id==1073741825, 'Unexpected graph identity')
    contract=module('mvp_topology_contract',Path(__file__).with_name('verify-gameloop-graph.py'))
    require(len(graph.nodes)==29 and {n.index:n.shell_ref.runtime_id for n in graph.nodes}==contract.DEFS,
            'Unexpected graph nodes')
    edges=[]
    for node in graph.nodes:
        for pin in node.pins:
            for link in pin.connections:
                a=(node.index,pin.shell_sig.kind,pin.shell_sig.index)
                b=(link.target_node_index,link.target_pin_shell.kind,link.target_pin_shell.index)
                if a[1]==3:a,b=b,a
                edges.append(f'{a}->{b}')
    require(len(edges)==38 and set(edges)==contract.EDGES, 'Unexpected graph connections')
    vectors=[]
    for index,xy in ((14,(43.,2.25)),(28,(0.,1.5))):
        node=next(n for n in graph.nodes if n.index==index)
        values=[]
        for axis in range(3):
            pins=[p for p in node.pins if p.shell_sig.kind==3 and p.shell_sig.index==axis]
            require(len(pins)==1 and pins[0].type==5 and not pins[0].connections
                    and pins[0].value.HasField('val_float'), 'Unexpected vector pin')
            values.append(getattr(pins[0].value.val_float,'float'))
        require(tuple(values[:2])==xy,'Unexpected graph X/Y')
        vectors.append(values)
    zs=[p[2] for p in positions.values()]+[p[2] for p in vectors]
    state='repaired' if all(z==0 for z in zs) else 'needs_repair' if all(z==-50 for z in zs) else 'mixed_or_unexpected'
    return dict(ok=state!='mixed_or_unexpected',state=state,levelId=1073741833,
                scope='saved_coordinates_and_graph_topology',sha256=sha(data),positions=positions,
                goal=vectors[0],respawn=vectors[1],entityCount=17,nodeCount=29,edgeCount=38,
                sceneBoundsVerified=False,playtestVerified=False)

def prepare_run(out):
    require(not out.exists(), 'Use a new evidence directory')
    before=LIVE.read_bytes()
    state=inspect_state(before)
    if state['state']=='repaired':
        return dict(state,action='prepare',changed=False,reason='Already repaired; no files written')
    require(state['state']=='needs_repair','Unsupported source coordinates')
    after,changes=repair(before)
    require(inspect_state(after)['state']=='repaired','Candidate readback failed')
    require(repair(after,0.,-50.)[0]==before,'Reverse repair did not exactly restore source')
    require(LIVE.read_bytes()==before,'Live file changed while preparing')
    out.mkdir(parents=True)
    for name,data in [('before.gil',before),('candidate.gil',after)]:
        with (out/name).open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
    report=dict(ok=True,action='prepare',directory=str(out),source=str(LIVE),
                beforeSha256=sha(before),candidateSha256=sha(after),changes=changes,
                graphChanges=['node14.z: -50 -> 0','node28.z: -50 -> 0'],reverseByteExact=True,
                unrelatedEntitiesPreserved=11,changedRootFields=[5,10],applied=False,
                sceneBoundsVerified=False,playtestVerified=False)
    (out/'prepared.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def verify_run(out):
    report=json.loads((out/'prepared.json').read_text(encoding='utf-8'))
    before=(out/'before.gil').read_bytes();after=(out/'candidate.gil').read_bytes()
    require(report['source']==str(LIVE) and sha(before)==report['beforeSha256']
            and sha(after)==report['candidateSha256'],'Prepared artifact mismatch')
    require(repair(before)[0]==after and repair(after,0.,-50.)[0]==before,'Candidate repair mismatch')
    require(inspect_state(before)['state']=='needs_repair' and inspect_state(after)['state']=='repaired',
            'Candidate semantic mismatch')
    return report,before,after

def apply_run(out,level_unloaded=False):
    require_compatible('all')  # Before claim artifacts or formal-file access.
    require(level_unloaded,'Leave the level first, then pass --level-unloaded; this flag is an operator assertion, not an automatic observation')
    report,before,after=verify_run(out)
    current=LIVE.read_bytes()
    if (out/'applied.json').exists():
        state=inspect_state(current)
        require(state['state']=='repaired','Previously applied but current contents differ; inspect, do not replay')
        return dict(state,action='apply',changed=False,reason='Previously applied; no write repeated')
    require(current==before,'Save changed; prepare a fresh repair')
    # Exclusive attempt marker survives uncertainty and prevents concurrent/repeated writes.
    with (out/'apply-attempt.json').open('x',encoding='utf-8') as stream:
        json.dump({'source':str(LIVE),'beforeSha256':sha(before)},stream);stream.flush();os.fsync(stream.fileno())
    temp=None
    try:
        require_compatible('all')
        with tempfile.NamedTemporaryFile(dir=LIVE.parent,prefix=LIVE.name+'.repair-',suffix='.tmp',delete=False) as stream:
            temp=Path(stream.name);stream.write(after);stream.flush();os.fsync(stream.fileno())
        require(temp.read_bytes()==after and LIVE.read_bytes()==before,'Concurrent change; refusing overwrite')
        require_compatible('all')
        os.replace(temp,LIVE)
        require(LIVE.read_bytes()==after and inspect_state(LIVE.read_bytes())['state']=='repaired','Post-write mismatch')
    finally:
        if temp is not None and temp.exists():temp.unlink()
    report.update(ok=True,action='apply',applied=True,changed=True,diskReadbackVerified=True)
    (out/'applied.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def _main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('status','prepare','verify','apply'))
    p.add_argument('directory', type=Path, nargs='?')
    p.add_argument('--level-unloaded',action='store_true',help='Operator confirms the level is closed, game remains running')
    args = p.parse_args()
    if args.action=='status':
        data=LIVE.read_bytes();report=inspect_state(data)
        require(LIVE.read_bytes()==data,'Save changed during status read; retry read-only inspection')
        report.update(action='status',source=str(LIVE),changed=False)
    else:
        require(args.directory is not None or args.action=='prepare','directory is required for verify/apply')
        out=(args.directory or ROOT/'.runtime/verification'/datetime.now().strftime('mvp-position-%Y%m%d-%H%M%S-%f')).resolve()
        require(ROOT in out.parents,'Evidence must stay inside project')
        if args.action=='prepare':report=prepare_run(out)
        elif args.action=='verify':
            _,_,candidate=verify_run(out)
            report=dict(inspect_state(candidate),action='verify',directory=str(out),reverseByteExact=True,changed=False)
        else:report=apply_run(out,args.level_unloaded)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report.get('ok',False) else 2

def main():
    try:
        return _main()
    except IncompatibleVersion as error:
        print(json.dumps(error.report, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'ok':False,'error':str(error),'playtestVerified':False},ensure_ascii=False))
        raise SystemExit(2)
