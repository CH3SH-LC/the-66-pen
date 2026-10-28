"""Gadget model registry from its native primary index and bounded records.

Static reading only. Exact indexed byte spans and the current native parser
must agree on every record and ID; unknown fields remain uninterpreted.
"""
import argparse,hashlib,json,os,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_catalog import ROOT,SOURCE,index_bin_rows,BundleReader,tables,Reader,MASK32
from monster_catalog import base_identity,native_string,u64,MASK64
from primary_index import decode as decode_index

def record(data):
    r=Reader(data);v=base_identity(r);v['gadgetConfigId']=v.pop('monsterConfigId')
    m=(u64(r)+0x466db4eb)&MASK64;v['gadgetMask']=m
    known=(0x20000,0x20,0x800,0x400000,0x200,0x8000,4,0x1000,8,2,0x80000,
           0x40000,1,0x4000000,0x400,0x1000000,0x2000000,0x10,0x10000,0x100000,0x80,0x10000000)
    if m&~sum(known):raise ValueError('GADGET_DERIVED_MASK')
    def fixed(bit,width):
        if m&bit:r.take(width)
    def string(bit,key,offset):
        v['string'+offset]=native_string(r,key,lambda n:(n+(key&65535))&65535) if m&bit else ''
    fixed(0x20000,1);fixed(0x20,1);fixed(0x800,8)
    v['strings58']=[]
    if m&0x400000:
        n=(r.u32()+0xc77c5b9a)&MASK32
        if n>4096:raise ValueError('GADGET_STRING_ARRAY_BUDGET')
        v['strings58']=[native_string(r,0x9714ff85fa17e9d9,lambda n:(n+0xe9d9)&65535) for _ in range(n)]
    fixed(0x200,1);fixed(0x8000,4);fixed(4,8);fixed(0x1000,1);fixed(8,4);fixed(2,1)
    fixed(0x80000,4);fixed(0x40000,4);string(1,0xbeee8ad37bfe5e23,'50')
    fixed(0x4000000,1);fixed(0x400,4);string(0x1000000,0xfa1ae5aa1a987859,'48')
    string(0x2000000,0x897fdd2018ea6723,'60');fixed(0x10,1);fixed(0x10000,4)
    fixed(0x100000,4);fixed(0x80,4);fixed(0x10000000,1)
    if r.p!=len(data):raise ValueError('GADGET_RECORD_TRAILING')
    v['rawSha256']=hashlib.sha256(data).hexdigest();return v

def acquire(index_path,out):
    index_path=Path(index_path).resolve();out=Path(out).resolve()
    if not index_path.is_relative_to(ROOT) or out.exists() or not out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017'):raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    index_data=index_path.read_bytes();index=decode_index(index_data);end=index[-1]['offset']+index[-1]['size']
    candidates=[x for x in index_bin_rows(SOURCE) if end+4<=x['object']['size']<=end+7]
    out.mkdir(parents=True);found=[];constants=tables()
    for row in candidates:
        source=Path(row['source']);before=source.stat();reader=BundleReader(source,row['bundleOffset'],constants)
        if reader.meta['nodes'][row['nodeIndex']]['path'].lower()!=row['cab'].lower():raise ValueError('CAB_CHANGED')
        obj=row['object'];raw=reader.read(row['nodeIndex'],obj['offset'],obj['size']);size=struct.unpack_from('<I',raw)[0]
        if size!=end or not 0<=len(raw)-4-size<=3 or any(raw[4+size:]):continue
        data=raw[4:4+size];rows=[]
        for ir in index:
            payload=data[ir['offset']:ir['offset']+ir['size']]
            try:v=record(payload)
            except ValueError as exc:raise ValueError(f"{exc}: id={ir['id']} offset={ir['offset']}") from exc
            if v['gadgetConfigId']!=ir['id']:raise ValueError('INDEX_RECORD_ID_MISMATCH')
            v.update(offset=ir['offset'],size=ir['size']);rows.append(v)
        after=source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED')
        stem='gadget-models-'+str(obj['pathId']);(out/(stem+'.bin')).write_bytes(data)
        result=dict(source=row,payloadSha256=hashlib.sha256(data).hexdigest(),rows=rows,
                    primaryIndex={'path':str(index_path),'sha256':hashlib.sha256(index_data).hexdigest()},
                    resourcePath='Data/_ExcelBinOutput/GadgetExcelConfigData',rowDecoderRvas=['0xbd6daa0','0x10296fb0'],
                    fullTableConsumed=True,allPrimaryIdsMatched=True,gameProcessAccessed=False,nativeCalled=False,appearanceVerified=False)
        (out/(stem+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');found.append({'file':stem+'.json','rows':len(rows)})
    result={'found':found,'candidateCount':len(candidates),'gameProcessAccessed':False};(out/'receipt.json').write_text(json.dumps(result,indent=2),encoding='utf8');return result

if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1';p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(acquire(a.index,a.out)))
