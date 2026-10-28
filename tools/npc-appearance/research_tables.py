"""Bounded read-only lookup of a native table count signature for investigation.

Candidates are explicitly unproven until their complete row decoder consumes
the payload. This command cannot create a game object or access any process.
"""
import argparse, hashlib, json, os, struct, sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from native_catalog import ROOT, SOURCE, index_bin_rows, BundleReader, tables

def main():
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
    out=Path(a.out).resolve()
    if out.exists() or not out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017'):raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    sources=index_bin_rows(SOURCE);constants=tables();reader=None;old=None;found=[]
    out.mkdir(parents=True)
    for row in sources:
        key=row['source'],row['bundleOffset']
        if key!=old:reader=BundleReader(Path(row['source']),row['bundleOffset'],constants);old=key
        obj=row['object'];prefix=reader.read(row['nodeIndex'],obj['offset'],min(obj['size'],10))
        if len(prefix)<10:continue
        count=(struct.unpack_from('<I',prefix,4)[0]+0x964957bc)&0xffffffff
        mask=(struct.unpack_from('<H',prefix,8)[0]+0x5486)&65535
        if not 1<=count<=100000 or mask&~255:continue
        if obj['size']>16*1024*1024:raise ValueError('OBJECT_BUDGET')
        raw=reader.read(row['nodeIndex'],obj['offset'],obj['size']);n=struct.unpack_from('<I',raw)[0]
        if not 0<=len(raw)-4-n<=3 or any(raw[4+n:]):continue
        name='candidate-'+str(obj['pathId']);payload=raw[4:4+n]
        (out/(name+'.bin')).write_bytes(payload)
        receipt=dict(source=row,countCandidate=count,firstBaseMask=mask,tableIdentityProven=False,
                     payloadSha256=hashlib.sha256(payload).hexdigest(),gameProcessAccessed=False,nativeCalled=False)
        (out/(name+'.json')).write_text(json.dumps(receipt,indent=2),encoding='utf8');found.append(receipt)
    print(json.dumps(dict(candidates=len(found),records=[dict(pathId=x['source']['object']['pathId'],count=x['countCandidate']) for x in found],gameProcessAccessed=False)))

if __name__=='__main__':main()
