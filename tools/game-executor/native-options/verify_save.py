"""Verify the saved graphs, exact host bindings and native option components."""
from pathlib import Path
import argparse,hashlib,json,struct,sys
ROOT=Path(__file__).resolve().parents[3];sys.path[:0]=[str(ROOT),str(ROOT/'tools/beyond-save')]
from gil_container import decode_container,parse_fields,encode_fields
from tools.gameplan.demo import farming_tabs as t
from tools.gameplan.demo.farming_manual import verify_plan_export,_export_loader
def one(rows,n):
    matches=[x for x in rows if x.number==n];assert len(matches)==1,(n,len(matches));return matches[0]
def scalar(rows,n,default=0):
    matches=[x for x in rows if x.number==n];assert len(matches)<=1;return matches[0].value if matches else default
def children(rows,n):return [parse_fields(x.data) for x in rows if x.number==n]
def entities(root):return {one(e,1).value:e for e in children(parse_fields(one(root,5).data),1)}
def comp(rows,field,kind):
    matches=[x for x in rows if x.number==field and scalar(parse_fields(x.data),1)==kind]
    assert len(matches)==1,(field,kind,len(matches));return parse_fields(matches[0].data)
def bindings(e):
    graph_comp=parse_fields(one(comp(e,6,3),13).data)
    return [scalar(parse_fields(one(row,1).data),2) for row in children(graph_comp,1)]
def verify(before,after,deployment):
    before,after=Path(before),Path(after);left=parse_fields(decode_container(before.read_bytes()).payload);right=parse_fields(decode_container(after.read_bytes()).payload)
    assert scalar(left,1)==scalar(right,1)==1073741842
    le,re=entities(left),entities(right);assert set(le)==set(re) and len(re)==20
    # All pre-existing entities and all original server components remain.
    for eid in le:
        if eid not in (t.SHOP_HOST,t.FARM_HOST):assert encode_fields(le[eid])==encode_fields(re[eid]),('UNEXPECTED_ENTITY_CHANGE',eid)
    for field in (4,15):assert [x.data for x in left if x.number==field]==[x.data for x in right if x.number==field],('TRADE_ROOT_CHANGED',field)
    graphs=[{g.identity.runtime_id:g.SerializeToString(deterministic=True) for g in _export_loader().load_graphs(p)[1]} for p in (before,after)]
    added={json.loads((Path(deployment)/label/'mapping.json').read_text(encoding='utf-8'))['graphId'] for label in ('shop','farm')}
    assert set(graphs[1])-set(graphs[0])==added
    assert all(graphs[1].get(k)==v for k,v in graphs[0].items()),'EXISTING_GRAPH_CHANGED'
    def host_original(rows):
        return encode_fields([x for x in rows if x.number!=7 and not(x.number==6 and scalar(parse_fields(x.data),1)==3)])
    out=[]
    for label,plan,host,labels in [('shop',t.shop_plan(),t.SHOP_HOST,['打开农场商店']),('farm',t.farm_plan(),t.FARM_HOST,['播种（消耗1颗种子）','收获作物'])]:
        folder=Path(deployment)/label;mapping=json.loads((folder/'mapping.json').read_text(encoding='utf-8'))
        graph=verify_plan_export(after,plan,t.package(plan,host),build_receipt=mapping)
        assert host_original(le[host])==host_original(re[host]),('HOST_GEOMETRY_OR_COMPONENT_CHANGED',host)
        assert bindings(re[host])==bindings(le[host])+[mapping['graphId']],('BINDING_DELTA',host)
        server_old={scalar(parse_fields(x.data),1):x.data for x in le[host] if x.number==7}
        server_new={scalar(parse_fields(x.data),1):x.data for x in re[host] if x.number==7}
        assert set(server_new)==set(server_old)|{17}
        assert all(server_new[k]==v for k,v in server_old.items())
        option_wrapper=comp(re[host],7,17);assert scalar(option_wrapper,2)==1
        payloads=[x for x in option_wrapper if x.wire_type==2];assert len(payloads)==1
        assert payloads[0].number==27
        payload=payloads[0].data;options=parse_fields(payload)
        colliders=children(options,1);assert len(colliders)==1
        collider=colliders[0];assert scalar(collider,1)==1 and scalar(collider,503)==1
        sphere=parse_fields(one(collider,12).data)
        radius=one(sphere,2);assert radius.wire_type==5
        radius=struct.unpack('<f',struct.pack('<I',radius.value))[0];assert radius==2.0
        assert not parse_fields(one(sphere,1).data),'NONZERO_COLLIDER_CENTER'
        saved_options=children(options,2);assert len(saved_options)==len(labels)
        cards=[]
        for index,(card,text) in enumerate(zip(saved_options,labels),1):
            assert scalar(card,1)==scalar(card,504)==index
            assert one(card,2).data.decode('utf-8')==text
            assert scalar(card,3)==int(index==1)
            assert scalar(card,4)==scalar(card,5)==1
            cards.append(dict(index=index,text=text,initialActive=bool(scalar(card,3))))
        out.append(dict(label=label,entityId=host,graphId=mapping['graphId'],graphVerified=graph['serializedContentVerified'],
            bindingIds=bindings(re[host]),radius=radius,options=cards,optionField=payloads[0].number,optionPayloadHex=payload.hex()))
    for level in range(1073741835,1073741842):
        assert (after.parent/f'before-{level}.gil').read_bytes()==(after.parent/f'after-{level}.gil').read_bytes(),('PROTECTED_LEVEL_CHANGED',level)
    result=dict(ok=True,levelId=1073741842,sha256=hashlib.sha256(after.read_bytes()).hexdigest(),bytes=after.stat().st_size,
        graphAndBindingsVerified=True,originalGraphCount=len(graphs[0]),originalGraphsPreserved=True,
        tradeRootsPreserved=True,otherEntitiesPreserved=True,protected7LevelsPreserved=True,
        nativeOptionsSaved=True,hosts=out,playVerified=False)
    return result
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--before',required=True);ap.add_argument('--after',required=True);ap.add_argument('--deployment',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    result=verify(a.before,a.after,a.deployment);Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
