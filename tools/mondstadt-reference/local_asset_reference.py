"""Read-only static Blb3 asset-name directory for locating original terrain.

One resumable pass reads metadata and named-object prefixes only. Payload blocks
are cached per bundle. All source files are opened rb; no process APIs are used.
"""
from __future__ import annotations
import argparse, collections, concurrent.futures, gzip, hashlib, json, os, re, struct, time
from pathlib import Path
from blb3_reference import INSTALL, WORK, BundleReader, tables
from serialized_reference import NAMED, metadata, object_identity
from reference_cli import project_path, write_json
from regional_registration import SOURCE, relative

MATCH=re.compile(r'mengde|mondstadt|bigworldterrain|hlod|stormdragon|church|citywall|fenglong',re.I)
_TABLES=None

def scan_file(request):
    global _TABLES
    if _TABLES is None:_TABLES=tables()
    filename,outdir=request;path=Path(filename);out=Path(outdir);key=hashlib.sha256(str(path).encode()).hexdigest()[:20]
    done=out/(key+'.summary.json')
    if done.exists():return json.loads(done.read_text(encoding='utf8'))
    stat=path.stat();summary={'sourcePath':str(path),'size':stat.st_size,'mtimeNs':stat.st_mtime_ns,'bundles':0,'nodes':0,'objects':0,'readBytes':0,'matches':0,'errors':[],'classCounts':{}}
    offset=0;counts=collections.Counter()
    with gzip.open(out/(key+'.jsonl.gz'),'wt',encoding='utf8') as index, (out/(key+'.matches.jsonl')).open('w',encoding='utf8') as matched:
        while offset<stat.st_size:
            try:reader=BundleReader(path,offset,_TABLES)
            except Exception as e:
                summary['errors'].append({'bundleOffset':offset,'stage':'header','error':str(e)});break
            summary['bundles']+=1
            for ni,node in enumerate(reader.meta['nodes']):
                if not node['serializedAsset']:continue
                record={'bundleOffset':offset,'bundleSize':reader.meta['bundleSize'],'nodeIndex':ni,'nodePath':node['path'],'nodeSize':node['size']}
                try:
                    header=reader.read(ni,0,min(20,node['size']))
                    if len(header)<20:raise ValueError('Short Unity header')
                    metadata_size,file_size,version,start=struct.unpack_from('>IIII',header)
                    if start>16*1024**2:raise ValueError('Metadata exceeds 16MiB bounded index')
                    m=metadata(reader.read(ni,0,min(start,node['size'])),node['size'])
                    record.update(unityVersion=m['unityVersion'],classIds=sorted(set(t['classId'] for t in m['types'])),externals=m['externals'],objects=[])
                    for obj in m['objects']:
                        cid=obj['classId'];counts[cid]+=1;entry=dict(obj)
                        if cid in NAMED or cid==1:
                            try:
                                identity=object_identity(obj,reader.read(ni,obj['offset'],min(obj['size'],16384)),m['endian'])
                                entry['name']=identity.get('name','')
                                if MATCH.search(entry['name']):
                                    match={**record,'sourcePath':str(path),'object':entry};match.pop('objects',None)
                                    matched.write(json.dumps(match,ensure_ascii=False)+'\n');summary['matches']+=1
                            except Exception as e:entry['nameError']=str(e)
                        record['objects'].append(entry)
                    summary['nodes']+=1;summary['objects']+=len(m['objects'])
                except Exception as e:
                    record['error']=str(e);summary['errors'].append({'bundleOffset':offset,'nodeIndex':ni,'stage':'serialized','error':str(e)})
                index.write(json.dumps(record,ensure_ascii=False)+'\n')
            summary['readBytes']+=reader.read_bytes
            offset+=reader.meta['bundleSize']
    if path.stat().st_size!=stat.st_size or path.stat().st_mtime_ns!=stat.st_mtime_ns:summary['errors'].append({'stage':'source-stability','error':'Source changed during scan'})
    summary.update(lastBundleEnd=offset,complete=offset==stat.st_size,classCounts=dict(counts))
    write_json(done,summary);return summary


def scan(args):
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    out=project_path(args.out)
    if not out.is_relative_to(SOURCE):raise ValueError('Owned output only')
    out.mkdir(parents=True,exist_ok=True)
    roots=[INSTALL/('YuanShen_Data/StreamingAssets/AssetBundles/blocks' if args.source=='streaming' else 'YuanShen_Data/Persistent/AssetBundles/blocks')]
    files=sorted(p for root in roots for p in root.rglob('*.blk'))
    if args.limit:files=files[:args.limit]
    write_json(out/'source-inventory.json',{'sourceReadMode':'rb','installationWrites':False,'gameProcessAccess':False,'files':[{'path':str(p),'size':p.stat().st_size} for p in files]})
    results=[];start=time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        for i,r in enumerate(pool.map(scan_file,[(str(p),str(out)) for p in files])):
            results.append(r)
            if (i+1)%10==0:print(json.dumps({'files':i+1,'total':len(files),'bundles':sum(v['bundles'] for v in results),'matches':sum(v['matches'] for v in results),'errors':sum(len(v['errors']) for v in results),'seconds':round(time.time()-start)}),flush=True)
    result={'schema':1,'files':len(results),'sourceReadMode':'rb','installationWrites':False,'gameProcessAccess':False,'decodedPayloadIsNotReferenceAcceptance':True,
        'bundles':sum(r['bundles'] for r in results),'objects':sum(r['objects'] for r in results),'readBytes':sum(r['readBytes'] for r in results),'matches':sum(r['matches'] for r in results),'errors':sum(len(r['errors']) for r in results),'elapsedSeconds':time.time()-start,'sourceFiles':results}
    write_json(out/'scan-receipt.json',result);print(json.dumps({k:v for k,v in result.items() if k!='sourceFiles'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);p.add_argument('--workers',type=int,default=3,choices=range(1,5));p.add_argument('--limit',type=int,default=0);p.add_argument('--source',choices=['streaming','persistent'],default='streaming');scan(p.parse_args())
