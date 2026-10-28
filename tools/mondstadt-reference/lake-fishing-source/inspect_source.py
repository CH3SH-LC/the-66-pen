"""Capture exact catalog candidates for structural research, not acceptance."""
import argparse
from collections import Counter
from common import *

def inspect(names):
    c=catalog();s=Store();rows=[]
    for name in names:
        matches=c.execute('SELECT node,pathid,classid,json FROM objects WHERE name=?',(name,)).fetchall()
        for nid,pid,cid,obj in matches:
            loc=c.execute('SELECT source,offset,node,cab FROM nodes WHERE id=?',(nid,)).fetchone()
            node=s.acquire(loc[3],{'sourcePath':loc[0],'bundleOffset':loc[1],'nodeIndex':loc[2]})
            item={'requestedName':name,'cab':loc[3],'pathId':pid,'classes':dict(Counter(x['classId']for x in node['metadata']['objects'])),
                'objects':[{'pathId':x['pathId'],'classId':x['classId'],'size':x['size'],'identity':x.get('identity')}for x in node['metadata']['objects'] if x['classId']in(1,4,33,114,142)]}
            rows.append(item);print(json.dumps(item,ensure_ascii=False),flush=True)
    save(OUT/'inspections'/('names-'+sha('|'.join(names).encode())[:12]+'.json'),rows)

if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1';p=argparse.ArgumentParser();p.add_argument('names',nargs='+');a=p.parse_args();inspect(a.names)
