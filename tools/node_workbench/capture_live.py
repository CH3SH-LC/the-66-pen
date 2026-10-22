"""Bounded read-only capture of the editor's complete recorded node domain."""
import argparse,hashlib,importlib.util,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--queue-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 out=Path(a.out).resolve();assert out.is_relative_to(ROOT/'.runtime') and not out.exists();out.mkdir(parents=True)
 s=importlib.util.spec_from_file_location('read_queue',ROOT/'tools/editor-bridge/elevated-request.py');q=importlib.util.module_from_spec(s);s.loader.exec_module(q);q.QUEUE=Path(a.queue_dir).resolve()
 def call(op,ids=None):
  req={'kind':'call','runId':str(uuid.UUID(a.run_id)),'op':op}
  if ids is not None:req['ids']=q.validate_call_ids(op,ids)
  rid=uuid.uuid4().hex;name=op+('-'+str(ids[0]) if ids else '')
  (out/(name+'-request.json')).write_text(json.dumps({'queueRequestId':rid,'request':req},indent=2),encoding='utf-8')
  r=q.send(req,timeout=90,request_id=rid);(out/(name+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
  if r.get('ok') is not True:raise RuntimeError('READ_FAILED:'+name)
  return r
 catalog=call('catalog')
 old=read(ROOT/'.runtime/verification/interface-experiments-20260926/live-node-schema.json')
 ids=sorted({r['id'] for r in old['nodes']});nodes=[]
 for start in range(0,len(ids),64):
  r=call('node-definition-variants',ids[start:start+64]);nodes.extend(r['variants'])
  assert all(not n['definition']['pinsTruncated'] for n in r['variants'])
  print('Read',min(start+64,len(ids)),'/',len(ids),'definitions',flush=True)
 keys={(tuple(n['category']),n['id']) for n in nodes};assert len(keys)==len(nodes)
 groups={tuple(g['category']):g['count'] for g in catalog['groups'] if any(m['kind']==6 for m in g['models'])}
 actual={c:sum(tuple(n['category'])==c for n in nodes) for c in {tuple(n['category']) for n in nodes}}
 assert groups==actual,('CATALOG_DOMAIN_MISMATCH',groups,actual)
 result={'schemaVersion':1,'observedUtc':datetime.now(timezone.utc).isoformat(),'runId':a.run_id,'definitionCount':len(ids),'variantCount':len(nodes),'nodes':nodes,'domainCounts':{','.join(map(str,k)):v for k,v in actual.items()},'completeForCatalog':True,'nativeConstructorsInvoked':False,'graphModified':False,'runtimeVerified':False}
 (out/'live-node-schema.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k!='nodes'},ensure_ascii=False))
if __name__=='__main__':main()
