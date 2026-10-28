"""Bounded current-build Gadget primary-index research, no native execution.

1880d3f0 reads a ZigZag count, unsigned keys, one initial offset, then
unsigned record sizes with cumulative offsets. The caller's supported
Gadget IDs select a candidate; only complete parsing and record-ID matches
can later establish identity. Merely matching count is not sufficient.
"""
import argparse,hashlib,json,os,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_catalog import ROOT,SOURCE,index_bin_rows,BundleReader,tables,Reader

def varint(r):
    n=0
    for i in range(10):
        v=r.take(1)[0]
        if i==9 and v>1:raise ValueError('INDEX_VARINT_OVERFLOW')
        n|=(v&127)<<(i*7)
        if not v&128:return n
    raise ValueError('INDEX_VARINT_OVERFLOW')

def decode(data):
    r=Reader(data);raw=varint(r);n=(raw>>1)^-(raw&1)
    if not 1<=n<=100000:raise ValueError('INDEX_COUNT')
    rows=[];offset=None
    for _ in range(n):
        key=varint(r)
        if key>0xffffffff:raise ValueError('INDEX_ID_OVERFLOW')
        if offset is None:offset=varint(r)
        size=varint(r)
        if not 0<size<=1024*1024 or offset+size>128*1024*1024:raise ValueError('INDEX_RECORD_BOUNDS')
        rows.append({'id':key,'offset':offset,'size':size});offset+=size
    if r.p!=len(data):raise ValueError('INDEX_TRAILING')
    if len({x['id'] for x in rows})!=n:raise ValueError('INDEX_DUPLICATE_ID')
    return rows

def locate(out,beyond):
    out=Path(out).resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017'):raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    required={x['gadgetConfigId'] for x in json.loads(Path(beyond).read_text(encoding='utf8'))['rows'] if x['gadgetConfigId']}
    sources=index_bin_rows(SOURCE);constants=tables();reader=None;key=None;found=[];out.mkdir(parents=True)
    before=SOURCE.stat()
    for row in sources:
        newkey=(row['source'],row['bundleOffset'])
        if key!=newkey:reader=BundleReader(Path(row['source']),row['bundleOffset'],constants);key=newkey
        obj=row['object'];prefix=reader.read(row['nodeIndex'],obj['offset'],min(20,obj['size']))
        if len(prefix)<8:continue
        try:
            raw_count=varint(Reader(prefix[4:]));n=(raw_count>>1)^-(raw_count&1)
            if not len(required)<=n<=100000:continue
        except ValueError:continue
        if obj['size']>16*1024*1024:continue
        raw=reader.read(row['nodeIndex'],obj['offset'],obj['size']);size=struct.unpack_from('<I',raw)[0]
        if not 0<=len(raw)-4-size<=3 or any(raw[4+size:]):continue
        payload=raw[4:4+size]
        try:records=decode(payload)
        except ValueError:continue
        hits=required&{x['id'] for x in records}
        if not hits:continue
        stem='primary-'+str(obj['pathId']);(out/(stem+'.bin')).write_bytes(payload)
        record=dict(source=row,payloadSha256=hashlib.sha256(payload).hexdigest(),rows=records,matchedRequiredIds=len(hits),requiredCount=len(required),missingRequiredIds=sorted(required-hits),fullTableConsumed=True,tableIdentityProven=False,gameProcessAccessed=False)
        (out/(stem+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8');found.append({'file':stem+'.json','rows':len(records),'matches':len(hits),'endOffset':records[-1]['offset']+records[-1]['size']})
    after=SOURCE.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED')
    result=dict(found=found,objectsInspected=len(sources),gameProcessAccessed=False,nativeCalled=False);(out/'receipt.json').write_text(json.dumps(result,indent=2),encoding='utf8');return result

if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1';p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--beyond',required=True);a=p.parse_args();print(json.dumps(locate(a.out,a.beyond)))
