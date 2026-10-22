"""Offline effect evidence, only from two independently decoded actual cards."""
from datetime import datetime
from contract import require,read,sha
from receipt import manifest,decode

def quantities(before,after,queries):
    require(isinstance(queries,list) and 0<len(queries)<=128,'INVENTORY_QUERY_LIMIT');out=[];seen=set()
    for q in queries:
        require(isinstance(q,dict) and set(q)<= {'source','configId','resourceType'} and {'source','configId'}<=set(q),'INVENTORY_QUERY_SHAPE')
        source=q['source'];config=q['configId'];require(source in ('slots','payment-resources') and type(config) is int and 0<config<=0xffffffff,'INVENTORY_QUERY_ID')
        field='physicalItemCounts' if source=='slots' else 'paymentResourceCounts'
        groups=[[x for x in result[field] if x['configId']==config] for result in (before,after)]
        kinds={x['resourceType'] for group in groups for x in group}
        if 'resourceType' in q:
            kind=q['resourceType'];require(type(kind) is int and 0<=kind<=0xffffffff,'INVENTORY_QUERY_TYPE')
        else:
            require(len(kinds)==1,'INVENTORY_QUERY_TYPE_REQUIRED');kind=next(iter(kinds))
        identity=(source,kind,config);require(identity not in seen,'INVENTORY_DUPLICATE_QUERY');seen.add(identity)
        values=[]
        for result,group in zip((before,after),groups):
            require(result.get('inventoryComplete') is True and result.get('inventoryQuantitiesVerified') is True,'INVENTORY_DIFF_INCOMPLETE')
            match=[x for x in group if x['resourceType']==kind];require(len(match)<=1,'INVENTORY_AMBIGUOUS_QUANTITY');values.append(int(match[0]['quantity']) if match else 0)
        out.append(dict(source=source,resourceType=kind,configId=config,before=str(values[0]),after=str(values[1]),delta=str(values[1]-values[0])))
    return out

def compare(before_path,after_path,queries):
    a,ac,_=manifest(before_path);z,zc,_=manifest(after_path)
    require(a!=z and ac['kind']==zc['kind']=='playtest-control-prepared-v6','INVENTORY_DIFF_CARDS')
    require(ac['session']==zc['session'] and ac['targetLevelId']==zc['targetLevelId'] and ac['binding']==zc['binding'] and ac['lineage']['rootRun']==zc['lineage']['rootRun'],'INVENTORY_DIFF_TRIAL_CHANGED')
    before,after=decode(a),decode(z)
    require(all(v.get('ok') is True and v.get('cleanupVerified') is True and v.get('outcomeUncertain') is False for v in (before,after)),'INVENTORY_DIFF_UNVERIFIED')
    require(before['runtimeOwner']==after['runtimeOwner'],'INVENTORY_DIFF_OWNER_CHANGED')
    first,last=read(a/'exit.json'),read(z/'exit.json')
    times=[datetime.fromisoformat(x) for x in (first['startedUtc'],first['finishedUtc'],last['startedUtc'],last['finishedUtc'])]
    require(all(t.tzinfo is not None for t in times) and times==sorted(times) and times[0]<times[3],'INVENTORY_DIFF_ORDER')
    return dict(ok=True,operation='inventory-diff',readOnly=True,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,targetLevelId=ac['targetLevelId'],runtimeOwner=before['runtimeOwner'],quantityEncoding='decimal string',changes=quantities(before,after,queries),sources=[dict(run=str(p),rawSha256=sha(p/'acceptance.bin'),receiptSha256=sha(p/'stdout.jsonl'),exitSha256=sha(p/'exit.json')) for p in (a,z)],gameplayEffectVerified=False,attribution='Observed quantity deltas only. Match these receipts to actual bounded gameplay actions; this comparison alone does not prove which interaction caused the change.')
