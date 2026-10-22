"""Independent native receipt and saved source-language verification."""
from pathlib import Path
import argparse, importlib.util, json, struct, sys, hashlib
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tools/beyond-save')]
from gil_container import decode_container, parse_fields, encode_fields
spec=importlib.util.spec_from_file_location('tabs_save_contract',ROOT/'tools/game-executor/native-options/verify_save.py')
tabs=importlib.util.module_from_spec(spec);spec.loader.exec_module(tabs)
LABELS=['田园种子','新鲜作物','田园币','打开商店','种田（消耗1颗种子）','收获作物']

def receipt(path):
    rows=[json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    row=next(r for r in rows if 'tabsHex' in r)
    raw=bytes.fromhex(row['tabsHex'])
    assert len(raw)==233848 and struct.unpack_from('<I',raw)[0]==len(raw),'RECEIPT_ABI'
    result=row['tabs'];assert result['status']==0 and result['sehCode']==0 and result['sceneUnchanged']==1
    assert row['ok'] is True and row['transportOk'] is True
    assert row['callbackCount']==1 and row['activeCallbacks']==0 and row['unhooked'] is True
    prop,n0,n1,lang,count=struct.unpack_from('<QIIII',raw,231376)
    assert prop and lang==2 and count==6
    texts=[]
    for i,expected in enumerate(LABELS):
        start=231400+i*408;index,sl,bl,al,l=struct.unpack_from('<iiiiI',raw,start)
        assert index>=0 and 0<sl<64 and 0<=bl<64 and 0<al<64 and l==lang
        source=raw[start+22:start+22+sl*2].decode('utf-16-le')
        before=raw[start+150:start+150+bl*2].decode('utf-16-le')
        after=raw[start+278:start+278+al*2].decode('utf-16-le')
        assert source==after==expected
        texts.append(dict(index=index,source=source,before=before,after=after,language=l,enabled=raw[start+20]))
    return dict(ok=True,stage=result['stage'],beforeCount=n0,afterCount=n1,texts=texts,cleanupSucceeded=True,playerVisibleVerified=False)

def saved(before,after):
    before,after=Path(before),Path(after)
    roots=[parse_fields(decode_container(p.read_bytes()).payload) for p in (before,after)]
    a,b=roots;one=tabs.one;scalar=tabs.scalar
    assert scalar(a,1)==scalar(b,1)==1073741842
    # Preserve graph bytes, commerce, UI and every unmodified entity/component.
    for f in (4,10,15,21):
        assert [x.data for x in a if x.number==f]==[x.data for x in b if x.number==f],('PROTECTED_ROOT_CHANGED',f)
    ea,eb=tabs.entities(a),tabs.entities(b);assert set(ea)==set(eb) and len(ea)==20
    for eid in ea:
        if eid not in (1077936131,1077936133):
            assert encode_fields(ea[eid])==encode_fields(eb[eid]),('ENTITY_CHANGED',eid)
            continue
        wa,wb=[tabs.comp(e[eid],7,17) for e in (ea,eb)]
        oa,ob=[parse_fields(one(w,27).data) for w in (wa,wb)]
        assert [x.data for x in oa if x.number!=2]==[x.data for x in ob if x.number!=2]
        ca,cb=[tabs.children(x,2) for x in (oa,ob)]
        assert len(ca)==len(cb)==(1 if eid==1077936131 else 2)
        for i,(left,right) in enumerate(zip(ca,cb)):
            expected=LABELS[3] if eid==1077936131 else LABELS[4+i]
            assert one(right,2).data.decode('utf8')==expected
            assert encode_fields([x for x in left if x.number not in (2,503)])==encode_fields([x for x in right if x.number not in (2,503)])
        def except_tab(e):return encode_fields([x for x in e if not(x.number==7 and scalar(parse_fields(x.data),1)==17)])
        assert except_tab(ea[eid])==except_tab(eb[eid])
    root35=parse_fields(one(b,35).data);group=parse_fields(one(parse_fields(one(root35,1).data),1).data)
    assert scalar(group,2)==2
    found={}
    for entry in tabs.children(group,1):
        source=one(entry,1).data.decode('utf8')
        if source not in LABELS:continue
        matches=[]
        for f in entry:
            if f.wire_type!=2 or f.number in (1,501):continue
            child=parse_fields(f.data)
            if scalar(child,1)==2 and any(x.number==2 and x.wire_type==2 for x in child):
                text=one(child,2).data.decode('utf8');matches.append((f.number,text))
        assert len(matches)==1 and matches[0][1]==source,('PRIMARY_LANGUAGE_MISSING',source,matches)
        found[source]=dict(language=2,text=source,translationField=matches[0][0])
    assert set(found)==set(LABELS)
    for level in range(1073741835,1073741842):
        assert (after.parent/f'before-{level}.gil').read_bytes()==(after.parent/f'after-{level}.gil').read_bytes()
    return dict(ok=True,levelId=1073741842,saveSha256=hashlib.sha256(after.read_bytes()).hexdigest(),bytes=after.stat().st_size,
        text=found,all16GraphsPreserved=True,tradeRootsPreserved=True,otherEntitiesPreserved=True,protected7LevelsPreserved=True,playerVisibleVerified=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--receipt');p.add_argument('--before');p.add_argument('--after');p.add_argument('--out',required=True);a=p.parse_args()
    result=receipt(a.receipt) if a.receipt else saved(a.before,a.after)
    out=Path(a.out).resolve();assert out.is_relative_to(ROOT);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
