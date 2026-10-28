"""Capture exact selected official templates and their proven native table chain."""
import ast, hashlib, json, sys
from pathlib import Path
sys.dont_write_bytecode=True
from sources import ROOT,OUTPUT,write_json
sys.path.insert(0,str(ROOT/'tools/npc-appearance'))
from official_models import Catalog

def selected():
    p=ROOT/'data/mondstadt/city/role-selection-verified.json';raw=p.read_bytes();doc=json.loads(raw);rows={};sources=[]
    sources.append({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest()})
    for role,row in doc['roles'].items():rows.setdefault(int(row['templateId']),[]).append({'scope':'central','role':role})
    for local in doc['regionLocalTables']:
        p=ROOT/'tools/mondstadt/city/regions'/(local['module']+'.py');raw=p.read_bytes();tree=ast.parse(raw)
        values=[]
        for node in tree.body:
            names=[x.id for x in node.targets if isinstance(x,ast.Name)]if isinstance(node,ast.Assign)else [node.target.id]if isinstance(node,ast.AnnAssign)and isinstance(node.target,ast.Name)else []
            if local['symbol']in names:values.append(ast.literal_eval(node.value))
        if len(values)!=1:raise ValueError('Declared local table not unique')
        sources.append({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'symbol':local['symbol']})
        for key,row in values[0].items():
            tid=int(key)if isinstance(key,int)else int(row['templateId'])
            rows.setdefault(tid,[]).append({'scope':local['module'],'role':str(key)})
    return rows,sources

def capture():
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package')
    targets,sources=selected();catalog=Catalog();result=catalog.resolve(sorted(targets));folder=OUTPUT/'official';folder.mkdir(exist_ok=True)
    for row in result['rows']:
        row['selectionRoles']=targets[row['templateId']];p=Path(row['officialSource']['path']);raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['officialSource']['sha256']:raise ValueError('Official source changed')
        captured=folder/(str(row['templateId'])+'.mihoyobin');captured.write_bytes(raw);row['capturedOfficialFile']=str(captured.relative_to(ROOT))
    result['selectionSources']=sources;result['scope']='central primary roles plus explicitly declared regional review tables; no alternatives silently substituted'
    write_json(OUTPUT/'template-identities.json',result)
    print(json.dumps({'templateCount':len(result['rows']),'models':[{'templateId':r['templateId'],'baseId':r['persistedBaseReference'],'handle':r['modelResourceHandle']}for r in result['rows']]}))
    return result

if __name__=='__main__':capture()
