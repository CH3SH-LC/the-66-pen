"""Locate native NPC source records by the exact base parser and NPC mask.

This reads only the native common identity prefix. Remaining NPC behavior
fields are explicitly not interpreted. No runtime NPC creation is implied.
"""
import argparse,hashlib,json,os,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_catalog import ROOT,SOURCE,index_bin_rows,BundleReader,tables,Reader
from monster_catalog import base_identity,u64
from primary_index import decode as decode_index,varint

NPC_BITS=(37,30,28,54,2,46,33,27,55,49,47,11,6,36,43,19,38,50,63,0,8,31,18,41,7,24,48,4,40,39,52,5,32,53)
NPC_MASK=sum(1<<b for b in NPC_BITS)

def prefix(payload,ir):
    r=Reader(payload);v=base_identity(r);v['npcConfigId']=v.pop('monsterConfigId')
    if v['npcConfigId']!=ir['id']:raise ValueError('NPC_INDEX_ID')
    m=u64(r)^0x95b8613f
    if m&~NPC_MASK:raise ValueError('NPC_MASK')
    v.update(npcMask=str(m),offset=ir['offset'],size=ir['size'],identityPrefixBytes=r.p,
             uninterpretedTailBytes=len(payload)-r.p,rawSha256=hashlib.sha256(payload).hexdigest())
    return v

def locate(out):
    out=Path(out).resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017'):raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    sources=index_bin_rows(SOURCE);reader=BundleReader(SOURCE,0,tables());out.mkdir(parents=True)
    before=SOURCE.stat();primary=[];found=[];candidates=[]
    def read(row):
        if row['bundleOffset']!=0 or row['nodeIndex']!=0 or reader.meta['nodes'][0]['path'].lower()!=row['cab'].lower():raise ValueError('SOURCE_CHANGED')
        obj=row['object'];raw=reader.read(0,obj['offset'],obj['size']);size=struct.unpack_from('<I',raw)[0]
        if not 0<=len(raw)-4-size<=3 or any(raw[4+size:]):raise ValueError('FRAME')
        return raw[4:4+size]
    for row in sources:
        obj=row['object']
        if not 16<=obj['size']<=2*1024*1024:continue
        lead=reader.read(0,obj['offset'],min(16,obj['size']))
        try:
            v=varint(Reader(lead[4:]));n=(v>>1)^-(v&1)
            if not 100<=n<=100000:continue
            data=read(row);records=decode_index(data)
        except ValueError:continue
        primary.append((row,data,records))
    for prow,pdata,indices in primary:
        end=indices[-1]['offset']+indices[-1]['size']
        for srow in sources:
            if not end+4<=srow['object']['size']<=end+7:continue
            data=read(srow)
            if len(data)!=end:continue
            try:
                values=[prefix(data[ir['offset']:ir['offset']+ir['size']],ir) for ir in indices]
            except ValueError as exc:
                candidates.append(dict(primaryPathId=prow['object']['pathId'],dataPathId=srow['object']['pathId'],error=str(exc)));continue
            stem='npc-model-prefixes-'+str(srow['object']['pathId'])
            (out/(stem+'.bin')).write_bytes(data);(out/(stem+'-index.bin')).write_bytes(pdata)
            result=dict(source=srow,primarySource=prow,sourceSha256=hashlib.sha256(data).hexdigest(),primarySha256=hashlib.sha256(pdata).hexdigest(),rows=values,
                        resourcePath='Data/_ExcelBinOutput/NpcExcelConfigData',identityParserRva='0xbd6daa0',npcParserRva='0x7883370',
                        allPrimaryIdsMatched=True,allNpcPresenceMasksMatched=True,fullNpcRecordDecoded=False,
                        gameProcessAccessed=False,nativeCalled=False,appearanceVerified=False)
            (out/(stem+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');found.append({'file':stem+'.json','rows':len(values)})
    after=SOURCE.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED')
    result=dict(found=found,candidates=candidates,primaryCandidates=len(primary),gameProcessAccessed=False,nativeCalled=False)
    (out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');return result

if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1';p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(locate(a.out)))
