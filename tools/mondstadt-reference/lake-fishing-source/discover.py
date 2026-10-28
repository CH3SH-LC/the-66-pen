"""Indexed, bounded name/source discovery; names only select candidates."""
import json,re
from common import *

def run():
    c=catalog();queries={
      'regionalWater':("SELECT node,pathid,classid,name,json FROM objects WHERE classid IN (1,43,142) AND (name GLOB '*Mengde*' OR name GLOB '*MengDe*' OR name GLOB '*MD*' OR name GLOB '*Mond*' OR name GLOB '*GuoJiu*' OR name GLOB '*JiuHu*') AND (name GLOB '*Water*' OR name GLOB '*water*' OR name GLOB '*Lake*' OR name GLOB '*Hu*')",()),
      'namedWaterMesh':("SELECT node,pathid,classid,name,json FROM objects WHERE classid=43 AND (name GLOB '*Water*' OR name GLOB '*water*')",()),
      'sceneWaterRoots':("SELECT node,pathid,classid,name,json FROM objects WHERE classid=1 AND (name GLOB '*1_-1*Water*' OR name GLOB '*1_0*Water*' OR name GLOB '*2_-1*Water*' OR name GLOB '*2_0*Water*' OR name GLOB '*1_-2*Water*' OR name GLOB '*2_-2*Water*' OR name GLOB '*Water*1_-1*' OR name GLOB '*Water*2_-1*')",())}
    allrows={}
    for label,(sql,args)in queries.items():
        rows=[]
        for node,pid,cid,name,raw in c.execute(sql,args):
            row={'nodeId':node,'pathId':pid,'classId':cid,'name':name,'indexedObject':json.loads(raw)}
            rows.append(row)
        allrows[label]=rows
        print(json.dumps({'query':label,'count':len(rows),'names':[r['name']for r in rows[:100]]}),flush=True)
    ids={r['nodeId']for rows in allrows.values()for r in rows}
    nodes={}
    for nid in ids:
        row=c.execute('SELECT source,offset,node,cab,json FROM nodes WHERE id=?',(nid,)).fetchone()
        nodes[str(nid)]={'sourcePath':row[0],'bundleOffset':row[1],'nodeIndex':row[2],'cab':row[3],'record':json.loads(row[4])}
    save(OUT/'lake-discovery.json',{'queries':{k:v[0]for k,v in queries.items()},'results':allrows,'nodes':nodes,'claims':'Names are discovery only; geometry/parent chain needed for placement.'})

if __name__=='__main__':run()
