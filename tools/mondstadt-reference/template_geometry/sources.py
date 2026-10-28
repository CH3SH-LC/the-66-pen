"""Exact-CAB, bounded local source acquisition for offline template geometry."""
import hashlib,json,os,sqlite3,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/mondstadt-reference'))
from blb3_reference import BundleReader,INSTALL
from serialized_reference import Reader,metadata,object_identity
from reference_cli import digest,write_json

OUTPUT=ROOT/'data/mondstadt/reference3d/template-geometry-v1'
DB=ROOT/'.runtime/mondstadt/rework-20261017/reference3d/source-chain-v5/local-reference-catalog.sqlite'

def asset_bundle(data):
    r=Reader(data);name=r.string();preload=[r.ptr() for _ in range(r.count(2000000))]
    containers=[]
    for _ in range(r.count(2000000)):
        key=r.string();first=r.read('i');count=r.read('i');ptr=r.ptr()
        containers.append({'key':key,'preloadIndex':first,'preloadSize':count,'asset':ptr})
    return {'name':name,'preload':preload,'containers':containers,'parsedPrefixBytes':r.p,'totalBytes':len(data)}

class NodeStore:
    def __init__(self,out=OUTPUT/'raw'):
        self.out=Path(out).resolve()if out is not None else None
        if self.out is not None and not self.out.is_relative_to(OUTPUT):raise ValueError('Owned template source directory required')
        self.con=sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)
        self.cache={};self.read_bytes=0
    def locate(self,cab):
        rows=list(self.con.execute('SELECT source,offset,node,json FROM nodes WHERE cab=?',(cab.lower(),)))
        unique={(r[0],r[1],r[2]):r for r in rows}
        if len(unique)!=1:raise ValueError('CAB location missing or ambiguous: '+cab)
        source,offset,node,raw=next(iter(unique.values()));row=json.loads(raw)
        row.update(sourcePath=source,bundleOffset=offset,nodeIndex=node)
        return row
    def acquire(self,cab,explicit=None):
        cab=cab.lower()
        if not cab.startswith('cab-') or len(cab)!=36 or any(x not in '0123456789abcdef'for x in cab[4:]):raise ValueError('Invalid CAB')
        if cab in self.cache:return self.cache[cab]
        folder=self.out/cab if self.out is not None else None
        if folder is not None and (folder/'source.json').exists():
            receipt=json.loads((folder/'source.json').read_text(encoding='utf8'));raw=(folder/'node.bin').read_bytes()
            if hashlib.sha256(raw).hexdigest()!=receipt['nodeSha256']:raise ValueError('Captured node changed')
            meta=json.loads((folder/'metadata.json').read_text(encoding='utf8'))
        else:
            if folder is not None and (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen template package: acquisition writes refused')
            row=explicit or self.locate(cab);path=Path(row['sourcePath']).resolve()
            if not path.is_relative_to(INSTALL):raise ValueError('Installation read source required')
            before=path.stat();reader=BundleReader(path,row['bundleOffset']);node=reader.meta['nodes'][row['nodeIndex']]
            if node['path'].lower()!=cab or not node['serializedAsset']:raise ValueError('Exact indexed CAB mismatch')
            if node['size']>64*1024**2:raise ValueError('Selected node exceeds64MiB')
            raw=reader.read(row['nodeIndex'],0,node['size']);self.read_bytes+=reader.read_bytes
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed')
            meta=metadata(raw)
            for obj in meta['objects']:
                try:obj['identity']=object_identity(obj,raw[obj['offset']:obj['offset']+obj['size']],meta['endian'])
                except (ValueError,UnicodeError)as e:obj['identityError']=str(e)
            receipt=dict(row,nodeSha256=hashlib.sha256(raw).hexdigest(),sourceBytes=before.st_size,sourceMtimeNs=before.st_mtime_ns,readBytes=reader.read_bytes,
                installationWrites=False,gameProcessAccess=False)
            if folder is not None:
                folder.mkdir(parents=True,exist_ok=False);(folder/'node.bin').write_bytes(raw)
                write_json(folder/'source.json',receipt);write_json(folder/'metadata.json',meta)
        result={'folder':folder,'receipt':receipt,'raw':raw,'metadata':meta,'objects':{o['pathId']:o for o in meta['objects']}}
        self.cache[cab]=result;return result
    def object(self,cab,pathid):
        n=self.acquire(cab);o=n['objects'][pathid]
        return o,n['raw'][o['offset']:o['offset']+o['size']]
    def external_cab(self,cab,file_id):
        if file_id==0:return cab
        ext=self.acquire(cab)['metadata']['externals'][file_id-1]
        return ext['path'].replace('\\','/').rsplit('/',1)[-1].lower()

if __name__=='__main__':
    import argparse
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cab',action='append',required=True);a=p.parse_args();s=NodeStore()
    for cab in a.cab:
        n=s.acquire(cab);info={'cab':cab,'nodeBytes':len(n['raw']),'objects':n['metadata']['objects'],'containers':[]}
        for obj in n['metadata']['objects']:
            if obj['classId']==142:info['containers'].append(asset_bundle(n['raw'][obj['offset']:obj['offset']+obj['size']]))
        write_json(n['folder']/'inspection.json',info);print(json.dumps(info,ensure_ascii=False))
