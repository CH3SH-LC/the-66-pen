"""Acquire one explicitly indexed serialized node, with stable source receipt."""
import argparse,hashlib,json,os
from pathlib import Path
from blb3_reference import BundleReader,INSTALL
from serialized_reference import metadata,object_identity
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def acquire(row,out):
    path=Path(row['sourcePath']).resolve()
    if not path.is_relative_to(INSTALL):raise ValueError('Installation source only')
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned output only')
    before=path.stat();r=BundleReader(path,row['bundleOffset']);n=row['nodeIndex']
    data=r.read(n,0,r.meta['nodes'][n]['size']);m=metadata(data)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during acquisition')
    out.mkdir(parents=True);(out/'node.bin').write_bytes(data)
    for obj in m['objects']:
        if obj['classId'] in (1,4,33):
            try:obj['identity']=object_identity(obj,data[obj['offset']:obj['offset']+obj['size']],m['endian'])
            except Exception as e:obj['identityError']=str(e)
    write_json(out/'metadata.json',m)
    write_json(out/'source.json',dict(row,sourceSize=before.st_size,sourceMtimeNs=before.st_mtime_ns,sourceReadMode='rb',sourceWrites=False,readBytes=r.read_bytes,nodeSha256=digest(out/'node.bin')))
    return {'output':relative(out),'sha256':digest(out/'node.bin'),'bytes':len(data),'typeTreeEnabled':m['typeTreeEnabled'],'objectCount':len(m['objects']),'classIds':sorted(set(o['classId'] for o in m['objects']))}


if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    print(json.dumps(acquire(json.loads(project_path(a.request).read_text(encoding='utf8')),project_path(a.out))))
