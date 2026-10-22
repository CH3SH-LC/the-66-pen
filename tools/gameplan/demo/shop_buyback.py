"""Set the crop price on an existing shop buyback row (707, not append 710).

The saved shop template already contains the crop with a zero price. Keep its
sale/startup graph intact and set that row on the same owner's create event.
The constructor wire form is checked against the saved, validated R7 price.
"""
from pathlib import Path
from collections import Counter
import hashlib,json
from .farming_manual import _export_loader,_leaf,_verify_value

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'.runtime/game-executor/scene-cli/20261014-134532-save-bb066478/after-1073741842.gil'
BASE_SHA='8a9b494cb0851790c1526399f91a3355123c75e40af36af25eafce0e0429985b'
NAME='MW_API_CROP_BUYBACK_PRICE'
HOST=1077936129
CROP=1107296258
CURRENCY=1115684865
DEFINITIONS=[73,71,14,2,707,1788]
EDGES=[(1,2,0,3,1,0),(1,4,0,2,3,0),(0,4,0,2,3,1),
       (2,4,0,3,3,0),(3,2,0,4,1,0),(0,4,0,4,3,0),(5,4,0,4,3,3)]

def package():
    values=[]
    for node,port,slot,value in [(4,1,'int',1),(4,2,'uint',CROP),(4,4,'enum',1),
                                (5,0,'int',2),(5,1,'uint',CURRENCY),(5,2,'int',10)]:
        values.append(dict(node=node,portIndex=port,slot=slot,value={'uint' if slot=='enum' else slot:value}))
    return dict(nodes=[dict(definitionId=d,x=i*250,y=0) for i,d in enumerate(DEFINITIONS)],
                edges=[dict(zip(('from','fromKind','fromIndex','to','toKind','toIndex'),e)) for e in EDGES],values=values)

def reference_nodes():
    raw,graphs=_export_loader().load_graphs(BASE);assert hashlib.sha256(raw).hexdigest()==BASE_SHA
    old=next(g for g in graphs if g.identity.runtime_id==1073741834)
    return {n.index:n for n in old.nodes}

def verify(path,mapping):
    raw,graphs=_export_loader().load_graphs(Path(path));gid=mapping['graphId'];ids=mapping['nodeIds']
    assert len(ids)==len(set(ids))==6
    candidates=[g for g in graphs if g.identity.runtime_id==gid];assert len(candidates)==1
    graph=candidates[0];assert graph.display_name==NAME and len(graph.nodes)==6
    assert (graph.identity.source_domain,graph.identity.service_domain,graph.identity.kind)==(10000,20000,21001)
    assert not graph.port_mappings and not graph.blackboard and not graph.entry_slot_index and not graph.evaluation_interval
    nodes={n.index:n for n in graph.nodes};assert set(nodes)==set(ids)
    observed=[]
    for i,d in enumerate(DEFINITIONS):
        n=nodes[ids[i]];assert n.shell_ref.runtime_id==d
        assert n.kernel_ref.runtime_id==([73,71,16,2,707,1890][i])
        for p in n.pins:
            assert p.shell_sig==p.kernel_sig
            for c in p.connections:
                assert c.target_pin_shell==c.target_pin_kernel
                a=(n.index,p.shell_sig.kind,p.shell_sig.index);b=(c.target_node_index,c.target_pin_shell.kind,c.target_pin_shell.index)
                if a[1]==3:a,b=b,a
                observed.append(a+b)
    assert Counter(observed)==Counter((ids[a],b,c,ids[d],e,f) for a,b,c,d,e,f in EDGES),'EXACT_EDGES'
    refs=reference_nodes()
    for i,source in ((0,1),(1,2),(2,3),(3,4),(5,62)):
        expected=type(refs[source])();expected.CopyFrom(refs[source])
        actual=type(expected)();actual.CopyFrom(nodes[ids[i]])
        for n in (expected,actual):
            n.ClearField('index');n.ClearField('x_pos');n.ClearField('y_pos')
            for p in n.pins:p.ClearField('connections')
        assert expected.SerializeToString(deterministic=True)==actual.SerializeToString(deterministic=True),('NATIVE_NODE_CONTENT',i)
    setter=nodes[ids[4]];pins={(p.shell_sig.kind,p.shell_sig.index):p for p in setter.pins}
    assert set(pins)=={(3,i) for i in range(5)},'SETTER_PINS'
    for i,typ in enumerate((1,3,20,27,4)):
        p=pins[3,i];assert p.type==typ
        if i in (0,3):assert not _leaf(p.value).is_value_set,'CONNECTED_PRICE_OR_OWNER_HAS_DEFAULT'
    for row in package()['values']:
        p=next(p for p in nodes[ids[row['node']]].pins if (p.shell_sig.kind,p.shell_sig.index)==(3,row['portIndex']))
        assert not p.connections
        _verify_value(p.value,row['value'],row['slot'],p.type,str(row))
    return dict(ok=True,graphId=gid,nodes=6,edges=7,values=6,existingRowSetter=707,
                cropId=CROP,currencyId=CURRENCY,price=10,serializedContentVerified=True,
                sourceSha256=hashlib.sha256(raw).hexdigest(),playVerified=False)
