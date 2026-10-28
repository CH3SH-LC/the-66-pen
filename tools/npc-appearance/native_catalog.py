"""Current-build installed NPC capability source tables; no process access.

The Beyond table decoder follows 12297cc0 / 10415830. Field names are
native offsets unless a consuming call establishes their meaning. Reading a
base row is not permission or proof that its model is an ordinary resident.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
# Captured-table decoding stays stdlib-only under the fixed -I -S entry.
# Optional static bundle acquisition has the reference tool's own dependencies;
# importing a decoder must not import that acquisition stack.
def acquisition():
    sys.path.insert(0, str(ROOT / 'tools/template-properties/icons'))
    import catalog
    return catalog


def index_bin_rows(*args, **kwargs):
    return acquisition().index_bin_rows(*args, **kwargs)


def BundleReader(*args, **kwargs):
    return acquisition().BundleReader(*args, **kwargs)


def tables(*args, **kwargs):
    return acquisition().tables(*args, **kwargs)

SOURCE = Path('D:/games/Genshin Impact Game/YuanShen_Data/Persistent/AssetBundles/blocks/00/25539185.blk')
MASK32 = 0xffffffff


class Reader:
    def __init__(self, data): self.data, self.p = data, 0
    def take(self, n):
        if n < 0 or self.p+n > len(self.data): raise ValueError('CONFIG_TRUNCATED')
        result = self.data[self.p:self.p+n]; self.p += n; return result
    def u16(self): return struct.unpack('<H', self.take(2))[0]
    def u32(self): return struct.unpack('<I', self.take(4))[0]
    def array(self, count_fn, value_fn):
        n = count_fn(self.u32())
        if n > 4096: raise ValueError('CONFIG_ARRAY_BUDGET')
        return [value_fn(self.u32()) for _ in range(n)]
    def string(self, key, length_fn):
        n = length_fn(self.u16())
        if n > 4096: raise ValueError('CONFIG_STRING_BUDGET')
        value = self.take(n); kb = key.to_bytes(8, 'little')
        return bytes(v ^ kb[i % 8] for i, v in enumerate(value)).decode('utf8')


def beyond_monsters(data):
    r = Reader(data); n = (r.u32()+0xb2fd1818)&MASK32
    if not 1 <= n <= 100000: raise ValueError('BEYOND_MONSTER_COUNT')
    rows = []
    for _ in range(n):
        start = r.p; mask = r.u16() ^ 0x6bba
        if mask & ~255: raise ValueError('BEYOND_MONSTER_MASK')
        row = dict(offset=start, presenceMask=mask)
        row['float38Bits'] = (r.u32()+0x5c13a3c8)&MASK32 if mask&2 else 0
        row['values28'] = r.array(lambda v:v^0xa0048d9a,lambda v:v^0xf56644f0) if mask&1 else []
        row['values10'] = r.array(lambda v:v^0xdbfd859b,lambda v:(v+0x192cf4b6)&MASK32) if mask&8 else []
        row['values20'] = r.array(lambda v:(v+0x52350daf)&MASK32,lambda v:v^0xa4c0af2d) if mask&4 else []
        # 1003e2f0 reads row+34 through bb2c5e0 into model config+20;
        # 1003e500 uses it with d63aa40 (MonsterExcelConfigData lookup).
        row['monsterConfigId'] = r.u32()^0xb5c98ffb if mask&16 else 0
        row['string18'] = r.string(0xfa30e428d3648399,lambda v:((v+0x8399)&65535)^0xe428) if mask&128 else ''
        # 12297cc0 uses row+30 as the dictionary key, and 1003e650 saves
        # exactly this Beyond key in the native monster template oneof.
        row['beyondMonsterBaseId'] = ((r.u32()^0xafcd39c8)+0xa3743633)&MASK32 if mask&32 else 0
        row['float3cBits'] = (r.u32()+0xe17fbb7d)&MASK32 if mask&64 else 0
        row['size'] = r.p-start; rows.append(row)
    if r.p != len(data): raise ValueError('CONFIG_TRAILING_BYTES')
    if len({v['beyondMonsterBaseId'] for v in rows}) != len(rows): raise ValueError('CONFIG_DUPLICATE_ID')
    return rows


def locate_beyond_monsters(out):
    out = Path(out).resolve()
    if out.exists() or not out.is_relative_to(ROOT / '.runtime/npc-appearance-20261017'):
        raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    rows = index_bin_rows(SOURCE); constants = tables(); reader = None; previous = None
    out.mkdir(parents=True); found = []; candidates = []; read_bytes = 0
    before = SOURCE.stat()
    for row in rows:
        key = (row['source'], row['bundleOffset'])
        if key != previous:
            if reader: read_bytes += reader.read_bytes
            reader = BundleReader(Path(row['source']), row['bundleOffset'], constants); previous = key
        if reader.meta['nodes'][row['nodeIndex']]['path'].lower() != row['cab'].lower():
            raise ValueError('INDEX_CAB_CHANGED')
        obj = row['object']; prefix = reader.read(row['nodeIndex'], obj['offset'], min(obj['size'],10))
        if len(prefix)<10: continue
        n=(struct.unpack_from('<I',prefix,4)[0]+0xb2fd1818)&MASK32
        mask=struct.unpack_from('<H',prefix,8)[0]^0x6bba
        if not 1<=n<=100000 or mask&~255: continue
        if obj['size'] > 16*1024*1024: raise ValueError('CONFIG_OBJECT_BUDGET')
        raw=reader.read(row['nodeIndex'],obj['offset'],obj['size']); size=struct.unpack_from('<I',raw)[0]
        candidate=dict(source=row,countCandidate=n)
        if not 0<=len(raw)-4-size<=3 or any(raw[4+size:]):
            candidate['error']='BINDATA_FRAME';candidates.append(candidate);continue
        try: decoded=beyond_monsters(raw[4:4+size])
        except (ValueError,UnicodeError) as exc:
            candidate['error']=str(exc);candidates.append(candidate);continue
        stem='beyond-monsters-'+str(obj['pathId']);payload=raw[4:4+size]
        (out/(stem+'.bin')).write_bytes(payload)
        record=dict(source=row,rawObjectSha256=hashlib.sha256(raw).hexdigest(),
                    payloadSha256=hashlib.sha256(payload).hexdigest(),rows=decoded,
                    rowDecoderRva='0x10415830',tableDecoderRva='0x12297cc0',
                    resourcePath='Data/_ExcelBinOutput/BeyondMonsterBaseExcelConfigData',
                    gameplayNpcAppearanceVerified=False,gameProcessAccessed=False)
        (out/(stem+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        found.append(dict(path=stem+'.json',rows=len(decoded),payloadSha256=record['payloadSha256']))
    if reader: read_bytes+=reader.read_bytes
    after=SOURCE.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('SOURCE_CHANGED')
    result=dict(found=found,candidatesRejected=candidates,objectsInspected=len(rows),readBytes=read_bytes,
                sourceWrites=False,gameProcessAccessed=False,nativeCalled=False,
                sourceSize=before.st_size,sourceMtimeNs=before.st_mtime_ns)
    (out/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def main():
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(locate_beyond_monsters(a.out),ensure_ascii=False))


if __name__=='__main__':main()
