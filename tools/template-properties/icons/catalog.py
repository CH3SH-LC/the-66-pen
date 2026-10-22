"""Read-only installed Beyond icon catalog decoder. No native execution."""
from __future__ import annotations
import hashlib
import gzip
import json
from pathlib import Path
import sqlite3
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/mondstadt-reference'))
from blb3_reference import BundleReader, tables
from serialized_reference import Reader

DB = ROOT / '.runtime/mondstadt/rework-20261017/reference3d/source-chain-v5/local-reference-catalog.sqlite'
INSTALL = Path('D:/games/Genshin Impact Game').resolve()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def connect():
    return sqlite3.connect(DB.as_uri()+'?mode=ro', uri=True, timeout=20)

def source_row(row):
    obj, source, offset, node, cab = row
    source = Path(source).resolve()
    if not source.is_relative_to(INSTALL):
        raise ValueError('INSTALL_SOURCE_REQUIRED')
    return dict(object=json.loads(obj), source=str(source), bundleOffset=offset,
                nodeIndex=node, cab=cab)

def object_rows(class_id=None, name=None):
    clauses=[];args=[]
    if class_id is not None: clauses.append('o.classid=?');args.append(class_id)
    if name is not None: clauses.append('o.name=?');args.append(name)
    if not clauses: raise ValueError('BOUNDED_QUERY_REQUIRED')
    with connect() as db:
        rows=db.execute('SELECT o.json,n.source,n.offset,n.node,n.cab FROM objects o JOIN nodes n ON n.id=o.node WHERE '+' AND '.join(clauses),args).fetchall()
    return [source_row(r) for r in rows]

def find_textures(names, previous=None):
    """Reuse SQL and completed, not-yet-imported gzip indexes; no installation scan."""
    names=set(names);found={name:[] for name in names};consumed=[];prior={}
    if previous is not None:
        if set(previous['names'])!=names:raise ValueError('INCREMENTAL_NAME_SET_CHANGED')
        found=previous['names']
        consumed=previous['proof']['completedAdditionalIndexes'][:]
        prior={r['path']:r['sha256'] for r in consumed}
    with connect() as db:
        indexed=dict(db.execute('SELECT key,sha FROM files'))
        for name in sorted(names):
            rows=db.execute('SELECT o.json,n.source,n.offset,n.node,n.cab FROM objects o JOIN nodes n ON n.id=o.node WHERE o.classid=28 AND o.name=?',(name,)).fetchall()
            found[name].extend(source_row(row) for row in rows)
    for folder in ('local-asset-index','local-patch-asset-index'):
        index=DB.parent/folder
        for summary in sorted(index.glob('*.summary.json')):
            key=summary.name.split('.')[0]
            if key in indexed:continue
            relative=str(summary.relative_to(ROOT));raw=summary.read_bytes();digest=sha(raw)
            if relative in prior:
                if prior[relative]!=digest:raise ValueError('COMPLETED_INDEX_CHANGED')
                continue
            receipt=json.loads(raw)
            if not receipt.get('complete'):continue
            source=Path(receipt['sourcePath']).resolve()
            if not source.is_relative_to(INSTALL):raise ValueError('INSTALL_SOURCE_REQUIRED')
            st=source.stat()
            if receipt['size']!=st.st_size or receipt['mtimeNs']!=st.st_mtime_ns:
                raise ValueError('SOURCE_INDEX_STALE')
            with gzip.open(index/(key+'.jsonl.gz'),'rt',encoding='utf8') as stream:
                for line in stream:
                    node=json.loads(line)
                    for obj in node.get('objects',[]):
                        if obj['classId']==28 and obj.get('name') in names:
                            found[obj['name']].append(dict(object=obj,source=str(source),bundleOffset=node['bundleOffset'],
                                nodeIndex=node['nodeIndex'],cab=node['nodePath']))
            consumed.append(dict(path=relative,sha256=digest))
    for name,rows in found.items():
        unique={}
        for row in rows:
            key=(row['source'],row['bundleOffset'],row['nodeIndex'],row['object']['pathId'])
            unique[key]=row
        found[name]=list(unique.values())
    return found,dict(sharedSqlite=str(DB.relative_to(ROOT)),completedAdditionalIndexes=consumed,
                      installationScanned=False,indexedNamesOnly=True,wholeInstallIndexComplete=False,
                      uniquenessScope='completed indexes available at lookup time; not an all-install uniqueness proof')

def read_object(row, constants=None, size=None):
    source=Path(row['source']).resolve()
    if not source.is_relative_to(INSTALL):raise ValueError('INSTALL_SOURCE_REQUIRED')
    reader=BundleReader(source,row['bundleOffset'],constants or tables())
    if reader.meta['nodes'][row['nodeIndex']]['path'].lower()!=row['cab'].lower():
        raise ValueError('INDEX_CAB_CHANGED')
    obj=row['object']
    data=reader.read(row['nodeIndex'],obj['offset'],obj['size'] if size is None else min(size,obj['size']))
    return data,reader

class ConfigReader:
    def __init__(self,data):self.data=data;self.p=0
    def take(self,n):
        if n<0 or self.p+n>len(self.data):raise ValueError('CONFIG_TRUNCATED')
        b=self.data[self.p:self.p+n];self.p+=n;return b
    def u16(self):return struct.unpack('<H',self.take(2))[0]
    def u32(self):return struct.unpack('<I',self.take(4))[0]
    def string(self,key):
        n=(self.u16()+(key&65535))&65535
        if n>4096:raise ValueError('CONFIG_STRING_BOUNDS')
        raw=self.take(n);kb=key.to_bytes(8,'little')
        return bytes(b^kb[i%8] for i,b in enumerate(raw)).decode('utf8')

def decode_config(data):
    """Exact 102e25d0/b5860b0 field order, arithmetic and two UTF8 XOR keys."""
    r=ConfigReader(data);count=r.u32()^0x5cfcb0a5
    if not 1<=count<=100000:raise ValueError('ICON_CONFIG_COUNT')
    rows=[]
    for _ in range(count):
        start=r.p;mask=r.u16()^0x9a7a
        if mask&~255:raise ValueError('ICON_CONFIG_MASK')
        row={'offset':start,'presenceMask':mask}
        row['value20']=(r.u32()^0x5998948c) if mask&1 else 0
        row['iconId']=((r.u32()+0x3d2af8dc)&0xffffffff) if mask&16 else 0
        row['string10']=r.string(0x9c3e04ad550c77b1) if mask&32 else ''
        row['value30']=((r.u32()+0x7fef24d7)&0xffffffff) if mask&64 else 0
        row['value2c']=((r.u32()+0x640754df)&0xffffffff) if mask&4 else 0
        row['category']=((r.u32()+0x4afde1f0)&0xffffffff) if mask&2 else 0
        row['string18']=r.string(0xe5ac948370863277) if mask&8 else ''
        row['value28']=(r.u32()^0xa6d73f34) if mask&128 else 0
        row['size']=r.p-start;rows.append(row)
    if r.p!=len(data):raise ValueError('ICON_CONFIG_TRAILING_BYTES')
    if len({v['iconId'] for v in rows})!=len(rows):raise ValueError('DUPLICATE_ICON_ID')
    return rows

def index_bin_rows(source):
    source=Path(source).resolve()
    if not source.is_relative_to(INSTALL):raise ValueError('INSTALL_SOURCE_REQUIRED')
    work=DB.parent
    key=sha(str(source).encode())[:20]
    index=work/'local-patch-asset-index'
    receipt=json.loads((index/(key+'.summary.json')).read_text(encoding='utf8'))
    st=source.stat()
    if not receipt['complete'] or receipt['size']!=st.st_size or receipt['mtimeNs']!=st.st_mtime_ns:
        raise ValueError('SOURCE_INDEX_STALE')
    result=[]
    with gzip.open(index/(key+'.jsonl.gz'),'rt',encoding='utf8') as stream:
        for line in stream:
            d=json.loads(line)
            for obj in d['objects']:
                if obj['classId']==1208:
                    result.append(dict(object=obj,source=str(source),bundleOffset=d['bundleOffset'],
                                       nodeIndex=d['nodeIndex'],cab=d['nodePath']))
    return result

def locate_config(out, indexed_source=None):
    """Only indexed class1208 objects, first10bytes. No block inventory scan."""
    out=Path(out).resolve()
    if not out.is_relative_to(ROOT) or out.exists():raise ValueError('NEW_PROJECT_OUTPUT_REQUIRED')
    out.mkdir(parents=True)
    constants=tables();candidates=[];errors=[];read_bytes=0
    sources=index_bin_rows(indexed_source) if indexed_source else object_rows(class_id=1208)
    previous=None;reader=None
    for i,row in enumerate(sources):
        try:
            key=(row['source'],row['bundleOffset'])
            if key!=previous:
                if reader:read_bytes+=reader.read_bytes
                reader=BundleReader(Path(row['source']),row['bundleOffset'],constants);previous=key
            if reader.meta['nodes'][row['nodeIndex']]['path'].lower()!=row['cab'].lower():
                raise ValueError('INDEX_CAB_CHANGED')
            if i%5000==0:print(json.dumps({'progress':i,'total':len(sources),'readBytes':read_bytes+reader.read_bytes}),flush=True)
            raw=reader.read(row['nodeIndex'],row['object']['offset'],min(10,row['object']['size']))
            if len(raw)<10:continue
            count=struct.unpack_from('<I',raw,4)[0]^0x5cfcb0a5
            mask=struct.unpack_from('<H',raw,8)[0]^0x9a7a
            if not 1<=count<=100000 or mask&~255:continue
            raw=reader.read(row['nodeIndex'],row['object']['offset'],row['object']['size'])
            n=struct.unpack_from('<I',raw)[0]
            if not 0<=len(raw)-4-n<=3 or any(raw[4+n:]):continue
            rows=decode_config(raw[4:4+n])
            prefix=f'catalog-{len(candidates):02d}'
            (out/(prefix+'.bin')).write_bytes(raw[4:4+n])
            record=dict(source=row,objectSha256=sha(raw),payloadSha256=sha(raw[4:4+n]),rows=rows)
            (out/(prefix+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
            candidates.append(dict(file=prefix+'.json',rowCount=len(rows),source=row))
            print(json.dumps({'found':prefix,'rows':len(rows),'index':i}),flush=True)
        except (ValueError,UnicodeError,RuntimeError) as e:
            errors.append(dict(index=i,error=str(e),source=row))
    if reader:read_bytes+=reader.read_bytes
    result=dict(indexedBinObjects=len(sources),candidates=candidates,errors=errors,readBytes=read_bytes,
                installWrites=False,gameProcessAccess=False,wholeInstallScanned=False)
    (out/'locate.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result
