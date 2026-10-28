"""Locate exact dependency CABs using only encrypted bundle directory headers.

This does not decompress payloads or enumerate object names. Completed full-index
files are skipped, and each installation file is opened read-only. Missing CABs
remain unresolved. This is a targeted dependency lookup, not a second data scan.
"""
from __future__ import annotations
import argparse,json,hashlib,time
from pathlib import Path
from blb3_reference import INSTALL,read_header,tables
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def locate(request,index,out):
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned output required')
    wanted=set(json.loads(request.read_text(encoding='utf8')))
    if not wanted or len(wanted)>32 or any(not c.startswith('cab-') for c in wanted):raise ValueError('At most32 exact CAB names required')
    inventory=json.loads((index/'source-inventory.json').read_text(encoding='utf8'));out.mkdir(parents=True)
    t=tables();results=[];files=[];start=time.time();read_bytes=0
    with (out/'progress.jsonl').open('w',encoding='utf8') as progress:
        for file in inventory['files']:
            path=Path(file['path']).resolve()
            if not path.is_relative_to(INSTALL):raise ValueError('Installed input only')
            key=hashlib.sha256(str(path).encode()).hexdigest()[:20]
            if (index/(key+'.summary.json')).exists():continue
            st=path.stat();offset=0;bundles=0;errors=[]
            while offset<st.st_size:
                try:meta,nonce,decoded=read_header(path,offset,t)
                except Exception as e:errors.append({'offset':offset,'error':str(e)});break
                bundles+=1;read_bytes+=28+len(decoded)
                for ni,node in enumerate(meta['nodes']):
                    if node['path'].lower() not in wanted:continue
                    row={'sourcePath':str(path),'bundleOffset':offset,'bundleSize':meta['bundleSize'],'nodeIndex':ni,'nodePath':node['path'],'nodeSize':node['size'],'classIds':[],
                         'sourceSize':st.st_size,'sourceMtimeNs':st.st_mtime_ns,'lookupMethod':'exact CAB in Blb3 directory; object classes not yet decoded'}
                    results.append(row);wanted.remove(node['path'].lower());write_json(out/'located-request.json',results)
                    print(json.dumps({'found':node['path'],'remaining':sorted(wanted),'file':str(path),'offset':offset}),flush=True)
                offset+=meta['bundleSize']
                if not wanted:break
            if path.stat().st_size!=st.st_size or path.stat().st_mtime_ns!=st.st_mtime_ns:raise ValueError('Source changed during read')
            row={'path':str(path),'size':st.st_size,'mtimeNs':st.st_mtime_ns,'bundles':bundles,'lastBundleEnd':offset,'errors':errors};files.append(row);progress.write(json.dumps(row)+'\n');progress.flush()
            if len(files)%20==0:print(json.dumps({'files':len(files),'bundles':sum(f['bundles'] for f in files),'directoryBytesRead':read_bytes,'remaining':sorted(wanted),'seconds':round(time.time()-start)}),flush=True)
            if not wanted:break
    receipt={'schema':1,'request':relative(request),'requestSha256':digest(request),'located':results,'unresolved':sorted(wanted),'scannedFiles':files,'directoryBytesRead':read_bytes,'payloadBytesRead':0,'sourceReadMode':'rb','installationWrites':False,'gameProcessAccess':False}
    write_json(out/'lookup-receipt.json',receipt);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--index',required=True);p.add_argument('--out',required=True);a=p.parse_args();locate(project_path(a.request),project_path(a.index),project_path(a.out))
