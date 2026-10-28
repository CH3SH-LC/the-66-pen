"""Exact validated RIP MOV/LEA source references; static bytes only."""
import re,struct,argparse
from common import *
sys.path.insert(0,str(ROOT/'tools/entity-material/research'))
from api import Research

def capture(targets=None,subfolder='scene-research'):
    r=Research();targets=set(targets or [0x5a52da8,0x5a52f18,0x5a53260,0x5a1ad98]);rows=[];cached={}
    for name,va,size,offset,flags in r.m.sections:
        if not flags&0x20000000:continue
        data=r.m.data[offset:offset+size]
        for match in re.finditer(b'[\x48-\x4f][\x8b\x8d][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]',data):
            at=match.start()
            if at+7>len(data):continue
            target=va+at+7+struct.unpack_from('<i',data,at+3)[0]
            if target not in targets:continue
            point=va+at;span=r.m.containing(point)
            if not span:continue
            if span[0]not in cached:cached[span[0]]=r.dump(span[0])
            ins=next((x for x in cached[span[0]]['instructions']if int(x['rva'],16)==point),None)
            if ins is not None and hex(target)in ins['ripTargets']:
                rows.append({'target':hex(target),'instruction':ins,'span':[hex(x)for x in span],'methods':r.method_at(span[0])})
    folder=OUT/subfolder;folder.mkdir(exist_ok=True)
    for at,d in cached.items():save(folder/(hex(at)+'.json'),d)
    save(folder/'rip-references.json',{'imageSha256':r.m.sha,'metadataSha256':r.m.metadata_sha,'rows':rows,
        'scope':'Only validated RIP-relative 64-bit MOV/LEA candidates for four known literal slots. Not all instruction forms.'})
    print(json.dumps([{'target':x['target'],'function':x['span'][0],'methods':[(m['name']['name'],m['method']['owner']['identifier']['name'])for m in x['methods']]}for x in rows]),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--targets',nargs='*');p.add_argument('--folder',default='scene-research');a=p.parse_args()
    capture([int(x,0)for x in a.targets]if a.targets else None,a.folder)
