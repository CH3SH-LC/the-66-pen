"""Bounded explicit list acquisition, geometry decoding, and provenance receipt."""
import argparse,json,os
from acquire_reference_node import acquire
from native_mesh_reference import decode as decode_mesh
from native_terrain_reference import decode_node as decode_terrain
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def run(request,out):
    rows=json.loads(request.read_text(encoding='utf8'))
    if not isinstance(rows,list) or len(rows)>100:raise ValueError('At most100 explicitly selected nodes')
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned output only')
    if sum(r['nodeSize'] for r in rows)>256*1024**2:raise ValueError('Batch node total over256MiB')
    out.mkdir(parents=True);results=[]
    for i,row in enumerate(rows):
        entry={'index':i,'requestedName':row.get('object',{}).get('name'),'sourceRow':row}
        try:
            node=out/f'{i:03d}-source';entry['acquired']=acquire(row,node)
            actual=json.loads((node/'metadata.json').read_text(encoding='utf8'));classes=sorted({o['classId'] for o in actual['objects']});entry['decodedClassIds']=classes
            if any(c in classes for c in (1,4,43)):entry['geometry']=decode_mesh(node,out/f'{i:03d}-geometry')
            if 156 in classes:entry['terrain']=decode_terrain(node,out/f'{i:03d}-terrain')
        except Exception as e:entry['error']=str(e)
        results.append(entry);print(json.dumps({'index':i,'name':entry['requestedName'],'error':entry.get('error')}),flush=True)
    receipt={'schema':1,'request':relative(request),'requestSha256':digest(request),'sourceReadMode':'rb','installationWrites':False,'gameProcessAccess':False,'items':results}
    write_json(out/'batch-receipt.json',receipt);return receipt


if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1';p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(project_path(a.request),project_path(a.out))
