"""Static Beyond gadget source table, following d71a110/a6262a0 exactly.

Only the dictionary key and the consuming model lookup establish semantic
names. Other fields retain native offsets. No eligibility is inferred from
names or resource existence.
"""
import argparse,hashlib,json,os,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_catalog import ROOT,Reader,MASK32,SOURCE,index_bin_rows,BundleReader,tables
from monster_catalog import native_string


def decode_beyond_gadgets(data):
    r=Reader(data);count=((r.u32()^0x8cc73b87)+0xffefd91d)&MASK32
    if not 1<=count<=100000:raise ValueError('BEYOND_GADGET_COUNT')
    rows=[];known=1|0x2000|0x20|0x400|2|8|0x40|0x100|0x200|0x10|0x8000|4|0x4000|0x80
    for ordinal in range(count):
        start=r.p;m=r.u32()^0x52dfe942;v={'presenceMask':m}
        if m&~known:raise ValueError('BEYOND_GADGET_MASK')
        def array(bit,key,length):
            if not m&bit:return
            n=length(r.u32())
            if n>4096:raise ValueError('BEYOND_GADGET_ARRAY_BUDGET')
            raw=r.take(n*4);v[key]={'count':n,'rawSha256':hashlib.sha256(raw).hexdigest()}
        v['bool54']=(r.take(1)[0]!=0xdd) if m&1 else False
        array(0x2000,'array38',lambda n:((n^0x94e6ef3d)+0x1f4ca8ad)&MASK32)
        v['uint5c']=((r.u32()^0x76906c5e)+0x874f67af)&MASK32 if m&0x20 else 0
        v['beyondGadgetBaseId']=((r.u32()+0x72eaa525)&MASK32)^0x8ec0627b if m&0x400 else 0
        array(2,'array28',lambda n:(n+0x70d3c751)&MASK32)
        v['uint4c']=r.u32()^0xe30e9d1a if m&8 else 0
        array(0x40,'array18',lambda n:(n+0xf497b540)&MASK32)
        v['float58Bits']=(r.u32()+0x916195ca)&MASK32 if m&0x100 else 0
        v['string10']=native_string(r,0xaed593baa179ac7c,lambda n:n^0xac7c,'add') if m&0x200 else ''
        v['float50Bits']=r.u32()^0x1eba9f04 if m&0x10 else 0
        v['string30']=native_string(r,0x6d6137a1867a048e,lambda n:(n+0x48e)&65535) if m&0x8000 else ''
        array(4,'array20',lambda n:n^0x8b6bfbf6)
        # 113a3480 reads +48 through bb2c5e0 into model-config +2c;
        # 113a2a50 -> 969d350 then returns GadgetExcel +40.
        v['gadgetConfigId']=(r.u32()+0x5bcc594a)&MASK32 if m&0x4000 else 0
        v['enum44']=r.u32()^0xba188d2a if m&0x80 else 0
        v.update(offset=start,size=r.p-start,rawSha256=hashlib.sha256(data[start:r.p]).hexdigest());rows.append(v)
    if r.p!=len(data):raise ValueError('BEYOND_GADGET_TRAILING')
    if len({x['beyondGadgetBaseId'] for x in rows})!=len(rows):raise ValueError('BEYOND_GADGET_DUPLICATE')
    return rows


def locate(out):
    out=Path(out).resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017'):raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    out.mkdir(parents=True);found=[];rejected=[];reader=None;key=None;constants=tables();source_rows=index_bin_rows(SOURCE)
    before=SOURCE.stat()
    for row in source_rows:
        newkey=(row['source'],row['bundleOffset'])
        if key!=newkey:reader=BundleReader(Path(row['source']),row['bundleOffset'],constants);key=newkey
        if reader.meta['nodes'][row['nodeIndex']]['path'].lower()!=row['cab'].lower():raise ValueError('INDEX_CAB_CHANGED')
        obj=row['object'];prefix=reader.read(row['nodeIndex'],obj['offset'],min(12,obj['size']))
        if len(prefix)<12:continue
        n=((struct.unpack_from('<I',prefix,4)[0]^0x8cc73b87)+0xffefd91d)&MASK32
        if not 1<=n<=100000:continue
        if obj['size']>16*1024*1024:raise ValueError('OBJECT_BUDGET')
        raw=reader.read(row['nodeIndex'],obj['offset'],obj['size']);size=struct.unpack_from('<I',raw)[0]
        if not 0<=len(raw)-4-size<=3 or any(raw[4+size:]):raise ValueError('BINDATA_FRAME')
        payload=raw[4:4+size]
        try:decoded=decode_beyond_gadgets(payload)
        except (ValueError,UnicodeError) as exc:rejected.append({'pathId':obj['pathId'],'error':str(exc)});continue
        stem='beyond-gadgets-'+str(obj['pathId']);(out/(stem+'.bin')).write_bytes(payload)
        record=dict(source=row,payloadSha256=hashlib.sha256(payload).hexdigest(),rawObjectSha256=hashlib.sha256(raw).hexdigest(),rows=decoded,
                    rowDecoderRva='0xa6262a0',tableDecoderRva='0xd71a110',resourcePath='Data/_ExcelBinOutput/BeyondGadgetBaseExcelConfigData',
                    fullTableConsumed=True,gameProcessAccessed=False,appearanceVerified=False)
        (out/(stem+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8');found.append({'path':stem+'.json','rows':len(decoded)})
    after=SOURCE.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED')
    result=dict(found=found,rejected=rejected,objectsInspected=len(source_rows),gameProcessAccessed=False,nativeCalled=False)
    (out/'receipt.json').write_text(json.dumps(result,indent=2),encoding='utf8');return result


if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(locate(a.out)))
