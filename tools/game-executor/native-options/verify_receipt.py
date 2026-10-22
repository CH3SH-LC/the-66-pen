"""Decode the native option receipt independently of its success summary."""
from pathlib import Path
import json,struct,sys,argparse
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
import build_readonly_profile as ro
def verify(run,layout):
    run=Path(run);layout=json.loads(Path(layout).read_text(encoding='utf-8-sig'))
    record,_=ro.load_decoder().read_probe(run/'stdout.jsonl');raw=bytes.fromhex(record['tabsHex'])
    assert len(raw)==layout['NativeTabReceipt']==record['tabsBytes']
    assert record['ok'] and record['transportOk'] and record['unhooked'] and record['callbackCount']==1 and record['activeCallbacks']==0
    assert record['tabs']['status']==record['tabs']['sehCode']==0 and record['tabs']['completedHosts']==2
    rows=[]
    expected=[(1077936131,['打开农场商店']),(1077936133,['播种（消耗1颗种子）','收获作物'])]
    for i,(eid,labels) in enumerate(expected):
        start=layout['hosts']+i*layout['TabHostResult']
        actual,status,n,collider_n,verified=struct.unpack_from('<5I',raw,start)
        assert (actual,status,n,collider_n,verified)==(eid,0,len(labels),1,1)
        assert struct.unpack_from('<i',raw,start+layout['colliderShape'])[0]==1
        radius=struct.unpack_from('<f',raw,start+layout['radius'])[0];assert radius==2.0
        options=[]
        for j,label in enumerate(labels):
            at=start+layout['options']+j*layout['TabRow']
            pointer,klass,index,sort,length,icon,filter_=struct.unpack_from('<2Q3i2I',raw,at)
            active,enabled=struct.unpack_from('<2B',raw,at+36)
            text=raw[at+layout['text']:at+layout['text']+length*2].decode('utf-16le')
            assert pointer and klass and index==sort==j+1 and text==label and active==int(j==0) and enabled==1
            options.append(dict(index=index,text=text,initialActive=bool(active),icon=icon,filter=filter_))
        rows.append(dict(entityId=eid,radius=radius,options=options))
    result=dict(ok=True,hosts=rows,nativeComponentReadbackVerified=True,saveVerified=False,playVerified=False)
    (run/'component-readback-verified.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);ap.add_argument('--layout',required=True);a=ap.parse_args();print(json.dumps(verify(a.run,a.layout),ensure_ascii=False))
