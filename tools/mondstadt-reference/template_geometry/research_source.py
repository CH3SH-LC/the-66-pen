"""Bounded static template-geometry research. Reads files; never opens a process."""
import argparse,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/entity-material/research'))
from api import Research

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--dump',nargs='*',default=[]);p.add_argument('--callers',nargs='*',default=[]);p.add_argument('--classes',default='');p.add_argument('--class-info',nargs='*',default=[],type=int);p.add_argument('--literals',default='');p.add_argument('--literal-xrefs',nargs='*',default=[],type=int);a=p.parse_args()
    out=(ROOT/a.out).resolve()
    if not out.is_relative_to(ROOT/'tools/mondstadt-reference/template_geometry') or out.exists():raise ValueError('New own evidence directory required')
    out.mkdir(parents=True);r=Research();result={'imageSha256':r.m.sha,'metadataSha256':r.m.metadata_sha,'gameProcessAccess':False,'nativeCalled':False}
    if a.classes:result['classes']=r.classes(a.classes,regex=True,limit=200)
    if a.literals:result['literals']=r.literals(a.literals,regex=True,limit=200)
    if a.callers:result['callers']=r.callers([int(x,0)for x in a.callers])
    for cid in a.class_info:(out/f'class-{cid}.json').write_text(json.dumps(r.class_info(cid),ensure_ascii=False,indent=2),encoding='utf8')
    for lid in a.literal_xrefs:result['literal-xrefs-'+str(lid)]=r.binding_xrefs(literal=lid)
    for value in a.dump:
        d=r.dump(int(value,0));(out/(value+'.json')).write_text(json.dumps(d,indent=2),encoding='utf8')
        (out/(value+'.asm')).write_text('\n'.join(x['rva']+': '+x['mnemonic']+' '+x['operands']for x in d['instructions']),encoding='utf8')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
