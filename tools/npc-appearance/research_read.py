"""Static NPC research; disk reads only, no game process/API access."""
import argparse,json,re,sqlite3,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/entity-material/research'))
from api import Research

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--slots',nargs='*',type=lambda s:int(s,0));p.add_argument('--classes',nargs='*',type=int);p.add_argument('--assets',action='store_true');a=p.parse_args()
    out=a.out.resolve();assert out.is_relative_to(ROOT/'tools/npc-appearance') or out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017')
    out.mkdir(parents=True,exist_ok=False);result=dict(gameConnected=False,nativeCalled=False)
    if a.slots or a.classes:
        r=Research();result.update(imageSha256=r.m.sha,metadataSha256=r.m.metadata_sha)
        if a.classes:
            for index in a.classes:
                value=r.class_info(index);(out/f'class-{index}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        if a.slots:
            wanted=set(a.slots);candidates=set();matches=[]
            # Restrict candidate load/store/lea instructions to validated RIP-relative
            # instruction boundaries, then preserve complete containing functions.
            for _,va,size,offset,flags in r.m.sections:
                if not flags&0x20000000:continue
                raw=r.m.data[offset:offset+size]
                for m in re.finditer(b'[\x48\x49\x4c\x4d][\x8b\x89\x8d][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]',raw):
                    pos=m.start()
                    if pos+7>len(raw):continue
                    target=va+pos+7+struct.unpack_from('<i',raw,pos+3)[0]
                    if target in wanted:
                        bounds=r.m.containing(va+pos)
                        if bounds:candidates.add(bounds)
            for start,end in sorted(candidates):
                dump=r.instructions(start,end)
                hits=[x for x in dump['instructions'] if set(x['ripTargets'])&{hex(x) for x in wanted}]
                if not hits:continue
                matches.append(dict(range=[hex(start),hex(end)],hits=hits,methods=r.method_at(start)))
                (out/(hex(start)+'.asm')).write_text('\n'.join(x['rva']+': '+x['mnemonic']+' '+x['operands'] for x in dump['instructions']),encoding='utf-8')
            result['ripReferences']=matches;result['coverage']='Validated 7-byte REX+mov/lea RIP instructions in unwind functions only; other forms not covered'
    if a.assets:
        db=ROOT/'.runtime/mondstadt/rework-20261017/reference3d/source-chain-v5/local-reference-catalog.sqlite'
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as con:
            result['assetRows']=[dict(zip(('name','classId','source','offset','node','cab','object','nodeMetadata'),row)) for row in con.execute("SELECT o.name,o.classid,n.source,n.offset,n.node,n.cab,o.json,n.json FROM objects o JOIN nodes n ON n.id=o.node WHERE o.classid IN(1,21,28,43,49) AND (o.name LIKE '%UgcAvatar%' OR o.name LIKE '%CharacterAppearance%' OR o.name LIKE '%BeyondCostume%' OR o.name LIKE '%Beyd%Body%') LIMIT 300")]
            result['database']=str(db);result['indexIncomplete']=True
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(ok=True,out=str(out),ripMatches=len(result.get('ripReferences',[])),assetMatches=len(result.get('assetRows',[])),gameConnected=False)))
if __name__=='__main__':main()
