"""Decode installed external_asset_index by the pinned native reader, disk only.

The full U64 key is looked up before deriving the hashed asset name. This does
not infer bundle IDs from handle bits. All language alternatives are retained.
"""
import argparse, hashlib, json, os, sqlite3, struct, sys
from pathlib import Path
sys.dont_write_bytecode=True
from sources import NodeStore, OUTPUT, INSTALL, write_json

INDEX_CAB='cab-b7c4cf0ace19593dc42a2c4e19166493'
INDEX=OUTPUT/'resource-index.sqlite'
PATCH_INDEX=OUTPUT/'resource-index-persistent.sqlite'

class Binary:
    def __init__(self,data):self.data=data;self.p=0
    def read(self,fmt):
        size=struct.calcsize('<'+fmt)
        if self.p+size>len(self.data):raise ValueError('Truncated resource index')
        row=struct.unpack_from('<'+fmt,self.data,self.p);self.p+=size
        return row[0] if len(row)==1 else row
    def count(self,maximum=10000000):
        n=self.read('i')
        if not 0<=n<=maximum:raise ValueError(f'Invalid count {n} at {self.p-4}')
        return n
    def take(self,n):
        if n<0 or self.p+n>len(self.data):raise ValueError('Invalid resource range')
        b=self.data[self.p:self.p+n];self.p+=n;return b
    def string(self):return self.take(self.count(100000)).decode('utf8')

def decode_to_sqlite(store=None,index_path=INDEX,summary_name='resource-index-source.json'):
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package')
    index_path=Path(index_path).resolve()
    if not index_path.is_relative_to(OUTPUT):raise ValueError('Owned index output required')
    if index_path.exists():raise FileExistsError('Preserve existing resource index; use lookup')
    store=store or NodeStore();obj,data=store.object(INDEX_CAB,3)
    if obj['classId']!=1208:raise ValueError('Expected MiHoYoBinData')
    size=struct.unpack_from('<I',data)[0]
    if size+4>len(data) or any(data[size+4:]):raise ValueError('Invalid bin payload length/pad')
    payload=data[4:4+size];r=Binary(payload);con=sqlite3.connect(index_path)
    con.executescript('''CREATE TABLE assets(handle TEXT,language INTEGER,bundle INTEGER,recordOffset INTEGER,recordSize INTEGER);
    CREATE TABLE dependencies(bundle INTEGER PRIMARY KEY,ids BLOB,recordOffset INTEGER,recordSize INTEGER);
    CREATE TABLE blocks(bundle INTEGER PRIMARY KEY,blockId INTEGER,offset INTEGER,size INTEGER,recordOffset INTEGER);
    CREATE TABLE block_flags(blockId INTEGER PRIMARY KEY,language INTEGER,flagA INTEGER,flagB INTEGER);
    CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);''')
    summary={'schemaVersion':1,'cab':INDEX_CAB,'pathId':3,'nodeSha256':store.acquire(INDEX_CAB)['receipt']['nodeSha256'],
        'objectSha256':hashlib.sha256(data).hexdigest(),'payloadSha256':hashlib.sha256(payload).hexdigest(),
        'payloadBytes':len(payload),'nativeReader':'0x6dd5f10','sections':{}}
    try:
        start=r.p;types=[(r.string(),r.string())for _ in range(r.count(2000))]
        summary['sections']['types']={'offset':start,'end':r.p,'count':len(types),'pairs':types}
        start=r.p;asset_count=r.count();batch=[];variant_count=0
        for _ in range(asset_count):
            at=r.p;handle=str(r.read('Q'));n=r.read('B');variants=[r.read('Bi')for _ in range(n)]
            if not variants:variants=[(-1,0)]
            batch.extend((handle,lang,bundle,at,r.p-at)for lang,bundle in variants);variant_count+=len(variants)
            if len(batch)>=20000:con.executemany('INSERT INTO assets VALUES(?,?,?,?,?)',batch);batch=[]
        con.executemany('INSERT INTO assets VALUES(?,?,?,?,?)',batch)
        summary['sections']['assets']={'offset':start,'end':r.p,'count':asset_count,'variantCount':variant_count}
        start=r.p;dep_count=r.count();total_declared=r.count(100000000);capacity=r.count(100000000);total=0;batch=[]
        for _ in range(dep_count):
            at=r.p;bundle=r.read('i');n=r.count();ids=r.take(n*4);total+=n;batch.append((bundle,ids,at,r.p-at))
            if len(batch)>=20000:con.executemany('INSERT INTO dependencies VALUES(?,?,?,?)',batch);batch=[]
        con.executemany('INSERT INTO dependencies VALUES(?,?,?,?)',batch)
        if total!=total_declared:raise ValueError('Dependency count mismatch')
        summary['sections']['dependencies']={'offset':start,'end':r.p,'count':dep_count,'totalReferences':total,'bundleCapacity':capacity}
        for key in ['preloadBlocks','preloadShaderBlocks']:
            start=r.p;n=r.count();values=list(struct.unpack('<'+'I'*n,r.take(n*4)))
            summary['sections'][key]={'offset':start,'end':r.p,'count':n,'values':values}
        start=r.p;groups=r.count(256);flag_count=0
        for _ in range(groups):
            language=r.read('i');n=r.count();flag_count+=n
            for _ in range(n):
                block,a,b=r.read('iBB');con.execute('INSERT INTO block_flags VALUES(?,?,?,?)',(block,language,a,b))
        summary['sections']['blockFlags']={'offset':start,'end':r.p,'groups':groups,'count':flag_count}
        start=r.p;block_count=r.count();entry_count=0;batch=[]
        for _ in range(block_count):
            block=r.read('i');n=r.count();entry_count+=n
            for _ in range(n):
                at=r.p;bundle,offset,length=r.read('III')
                if bundle>=capacity:raise ValueError('Bundle index outside capacity')
                batch.append((bundle,block,offset,length,at))
            if len(batch)>=20000:con.executemany('INSERT INTO blocks VALUES(?,?,?,?,?)',batch);batch=[]
        con.executemany('INSERT INTO blocks VALUES(?,?,?,?,?)',batch)
        summary['sections']['blocks']={'offset':start,'end':r.p,'count':block_count,'bundleEntries':entry_count}
        start=r.p;n=r.count()if r.p<len(payload)else 0;order=list(struct.unpack('<'+'I'*n,r.take(n*4)))
        summary['sections']['sortList']={'offset':start,'end':r.p,'count':n,'values':order}
        if r.p!=len(payload):raise ValueError('Unconsumed asset index tail')
        con.execute('CREATE INDEX assets_handle ON assets(handle)')
        con.execute('INSERT INTO metadata VALUES(?,?)',('source',json.dumps(summary)))
        con.commit();summary['parsedBytes']=r.p;write_json(OUTPUT/summary_name,summary)
    except Exception:
        con.rollback();raise
    finally:con.close()
    return summary

class ResourceIndex:
    def __init__(self,path=None):
        path=path or (PATCH_INDEX if PATCH_INDEX.exists()else INDEX)
        self.con=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        self.source=json.loads(self.con.execute("SELECT value FROM metadata WHERE key='source'").fetchone()[0])
        self.paths=None
    def lookup(self,handle):
        value=int(handle)
        if not 0<=value<2**64:raise ValueError('U64 handle required')
        result=[]
        for language,bundle,at,n in self.con.execute('SELECT language,bundle,recordOffset,recordSize FROM assets WHERE handle=?',(str(value),)):
            signed=(bundle&0x3fffffff);signed=signed-0x40000000 if signed&0x20000000 else signed;index=abs(signed)
            block=self.con.execute('SELECT blockId,offset,size,recordOffset FROM blocks WHERE bundle=?',(index,)).fetchone()
            result.append({'modelResourceHandle':str(value),'language':language,'encodedBundleIndex':bundle,'bundleIndex':index,
                'assetName':f'{(value>>8)&0xffffffff:08x}','resourceIdentifier':str((((value>>8)&0xffffffff)<<32)|index),
                'assetRecordOffset':at,'assetRecordSize':n,'block':None if block is None else dict(zip(['id','offset','size','recordOffset'],block))})
        return result
    def block_paths(self,blockid):
        if self.paths is None:
            self.paths={}
            for root in [INSTALL/'YuanShen_Data/StreamingAssets/AssetBundles/blocks',INSTALL/'YuanShen_Data/Persistent/AssetBundles/blocks']:
                if root.exists():
                    for p in root.rglob('*.blk'):
                        if p.stem.isdecimal():self.paths.setdefault(str(int(p.stem)),[]).append(str(p))
        return self.paths.get(str(blockid),[])

    def resolve(self,handle,store=None):
        """Read only the exact indexed bundle and return IndexObject PPtr matches."""
        from blb3_reference import read_header
        from serialized_reference import Reader
        from sources import asset_bundle
        store=store or NodeStore(out=None);result=[]
        for row in self.lookup(handle):
            row=dict(row);row['matches']=[];row['errors']=[];result.append(row)
            if row['block'] is None:row['errors'].append('NO_BLOCK_LOCATION');continue
            paths=self.block_paths(row['block']['id']);row['blockPaths']=paths
            if len(paths)!=1:row['errors'].append('BLOCK_PATH_NOT_UNIQUE');continue
            path=Path(paths[0]);header=read_header(path,row['block']['offset'])[0]
            if header['bundleSize']!=row['block']['size']:raise ValueError('Index bundle size differs from Blb3 header')
            for ni,node in enumerate(header['nodes']):
                if not node['serializedAsset']:continue
                cab=node['path'].lower();n=store.acquire(cab,{'sourcePath':str(path),'bundleOffset':row['block']['offset'],'nodeIndex':ni,'bundleSize':header['bundleSize']})
                for obj in n['metadata']['objects']:
                    if obj['classId']==142:
                        data=n['raw'][obj['offset']:obj['offset']+obj['size']]
                        for container in asset_bundle(data)['containers']:
                            key=container['key'];value=int(key)if key.lstrip('-').isdecimal()else None
                            if value is not None and (value&0xffffffff)==int(row['assetName'],16):
                                ptr=container['asset'];row['matches'].append({'indexCab':cab,'indexPathId':obj['pathId'],'key':key,
                                    'keyEncoding':'signed-decimal-u32-path-hash-bits-8-39','pointer':ptr,'targetCab':store.external_cab(cab,ptr['fileId']),
                                    'targetPathId':ptr['pathId'],'indexNodeSha256':n['receipt']['nodeSha256'],
                                    'indexObjectSha256':hashlib.sha256(data).hexdigest(),'containerPreloadIndex':container['preloadIndex'],'containerPreloadSize':container['preloadSize']})
                    if obj['classId']!=1210:continue
                    data=n['raw'][obj['offset']:obj['offset']+obj['size']];r=Reader(data);name=r.string()
                    for _ in range(r.count(100000)):
                        key=r.string();ptr=r.ptr();length=r.read('Q')
                        if key.lower()==row['assetName']:
                            target_cab=store.external_cab(cab,ptr['fileId'])
                            row['matches'].append({'indexCab':cab,'indexPathId':obj['pathId'],'key':key,'pointer':ptr,
                                'targetCab':target_cab,'targetPathId':ptr['pathId'],'declaredBytes':length,
                                'indexNodeSha256':n['receipt']['nodeSha256'],'indexObjectSha256':hashlib.sha256(data).hexdigest()})
                    if r.p!=len(data):raise ValueError('Unparsed IndexObject suffix')
            if len(row['matches'])!=1:row['errors'].append('EXACT_HASHED_ASSET_NOT_UNIQUE')
        return result

if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--decode',action='store_true');p.add_argument('--handle',action='append',default=[]);p.add_argument('--resolve',action='store_true');a=p.parse_args()
    if a.decode:
        s=decode_to_sqlite();print(json.dumps({k:v for k,v in s.items()if k!='sections'}))
        print(json.dumps({k:{a:b for a,b in v.items()if a not in ['pairs','values']}for k,v in s['sections'].items()}))
    if a.handle:
        idx=ResourceIndex();s=NodeStore();result={h:idx.resolve(h,s)if a.resolve else idx.lookup(h)for h in a.handle}
        if a.resolve:
            if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package; use read-only API')
            write_json(OUTPUT/'resource-handle-acquisition.json',result)
        print(json.dumps(result,indent=2))
