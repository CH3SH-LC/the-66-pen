"""Exact resource path/full hash lookup and bounded raw capture, disk only."""
import argparse,struct
from common import *
from scene_resource_index import ResourceIndex

def path_hash(path,type_suffix):
    value=(path+type_suffix).encode('utf8')
    padded=value.ljust(max(256,1<<(len(value)-1).bit_length()),b'\0')
    return int.from_bytes(hashlib.md5(padded).digest()[:8],'little')

def capture(path,suffix):
    store=Store();idx=ResourceIndex();handle=path_hash(path,suffix)
    rows=idx.resolve(handle,store);out={'path':path,'typeSuffix':suffix,'handle':str(handle),'rows':rows,'objects':[]}
    folder=OUT/'scene-resources'/str(handle);folder.mkdir(parents=True,exist_ok=True)
    for r in rows:
        for target in r['matches']:
            cab=target['targetCab'];pid=target['targetPathId'];obj,raw=store.object(cab,pid)
            dest=folder/(str(pid)+'.bin');dest.write_bytes(raw)
            named=[]
            # Source-discovery only: aligned UTF-8 strings with exact length prefix.
            for at in range(0,len(raw)-4,4):
                n=struct.unpack_from('<I',raw,at)[0]
                if 3<=n<=512 and at+4+n<=len(raw):
                    b=raw[at+4:at+4+n]
                    if all(32<=x<127 for x in b):named.append({'offset':at,'value':b.decode()})
            entry={'cab':cab,'pathId':pid,'object':obj,'raw':rel(dest),'sha256':sha(raw),'stringsForDiscovery':named}
            out['objects'].append(entry)
    save(folder/'source.json',out)
    print(json.dumps({'path':path,'handle':str(handle),'matches':len(out['objects']),
        'objects':[{'cab':x['cab'],'pathId':x['pathId'],'classId':x['object']['classId'],'bytes':x['object']['size'],'strings':len(x['stringsForDiscovery'])}for x in out['objects']]},ensure_ascii=False),flush=True)
    return out

if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1';p=argparse.ArgumentParser();p.add_argument('--path',required=True);p.add_argument('--type',required=True);a=p.parse_args();capture(a.path,a.type)
