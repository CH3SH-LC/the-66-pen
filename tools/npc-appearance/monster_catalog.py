"""Full record-boundary decoder for current MonsterExcelConfigData.

Only identity, native model handle and literal strings are interpreted. Combat
fields are consumed in their actual native order and preserved by record SHA;
no semantics, NPC classification, or visual appearance are inferred from them.
"""
import argparse, hashlib, json, sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_catalog import ROOT,Reader,MASK32

MASK64=(1<<64)-1


def u64(r): return int.from_bytes(r.take(8),'little')


def native_string(r,key,length_fn,operation='xor'):
    n=length_fn(r.u16())
    if n>4096:raise ValueError('MONSTER_STRING_BUDGET')
    value=r.take(n);out=bytearray()
    # d411d60 and d412370 add the full uint64 key, with carries between
    # bytes. The other string loops xor. The native short tail is copied
    # into a zeroed uint64, transformed, then decoded at original length.
    for start in range(0,n,8):
        part=value[start:start+8];v=int.from_bytes(part,'little')
        v=((v+key)&MASK64) if operation=='add' else (v^key)
        out.extend(v.to_bytes(8,'little')[:len(part)])
    return bytes(out).decode('utf8')


def typed_pairs(r, kind):
    # cda7b80/cda7c70 and 8c2c490/8c2c5e0 respectively.
    count=((r.u32()+0xa39bcf28)&MASK32) if kind==60349 else (r.u32()^0x5f500d47)
    if count>4096: raise ValueError('MONSTER_NESTED_ARRAY_BUDGET')
    for _ in range(count):
        m=(r.u16()^0xa1bd) if kind==60349 else ((r.u16()+0x6dca)&65535)
        bits=(2,0x40) if kind==60349 else (4,8)
        if m&~sum(bits):raise ValueError('MONSTER_NESTED_MASK')
        for bit in bits:
            if m&bit:r.take(4)


def base_identity(r):
    # bd6daa0 -> inherited fields +10..+40.
    m=(r.u16()+0x5486)&65535
    if m&~255:raise ValueError('MONSTER_BASE_MASK')
    row={'baseMask':m}
    row['hash28']=str(u64(r)^0xa269090e) if m&0x20 else '0'
    row['modelResourceHandle']=str(u64(r)^0x67754856) if m&4 else '0'
    if m&1:r.take(4)
    row['baseString10']=r.string(0xde637c82e062ff2d,lambda n:((n+0xff2d)&65535)^0x7c82) if m&0x80 else ''
    if m&2:r.take(4)
    row['hash18']=str(u64(r)^0xa3ed922c) if m&8 else '0'
    row['hash38']=str(((u64(r)+0xcd92a1b8)&MASK64)^0x87a58eb3) if m&0x40 else '0'
    row['monsterConfigId']=(r.u32()+0x4894cea6)&MASK32 if m&0x10 else 0
    return row


def base_stats(r):
    # 9ae6950. Array +48 is a typed pair array; other fields are fixed width.
    m=(u64(r)+0x6b6c5b47)&MASK64
    order=(0x1000,2,0x400,0x10000,0x20000,0x40000000,0x40,0x200000,
           0x80,0x20,0x4000,0x200,0x100000,0x20000000,0x80000000,8,
           0x800000,4,0x2000000,0x8000000,0x1000000,0x400000,0x2000,
           0x800,0x10,0x10000000)
    if m&~sum(order):raise ValueError('MONSTER_STATS_MASK')
    for bit in order:
        if not m&bit:continue
        if bit==0x8000000:typed_pairs(r,60349)
        else:r.take(8 if bit in (0x40,0x100000) else 4)
    return m


def monster_fields(r):
    # d411ac0. Native tests alternate raw/xor masks where the tested xor-key
    # bit is zero; normalized m below preserves exactly those branches.
    m=u64(r)^0x66579e7c; result={'monsterMask':m}
    known=(4,0x8000000,0x20000000,0x10000000,0x800000,0x400000,0x4000,
           0x800,2,8,0x40000,0x80000000,0x40,0x10,0x200,1,0x400,0x80,
           0x100,0x2000,0x100000,0x8000,0x80000,0x10000,0x1000,0x20000,
           0x200000,0x4000000,0x20)
    if m&~sum(known):raise ValueError('MONSTER_DERIVED_MASK')
    def fixed(bit,n):
        if m&bit:r.take(n)
    def string(bit,offset,key,length,operation='xor'):
        result['string'+offset]=native_string(r,key,length,operation) if m&bit else ''
    def array(bit,count_fn,width):
        if not m&bit:return
        n=count_fn(r.u32())
        if n>4096:raise ValueError('MONSTER_ARRAY_BUDGET')
        r.take(n*width)
    fixed(4,1)
    string(0x8000000,'c0',0x0072560f96c0f8f0,lambda n:n^0xf8f0,'add')
    fixed(0x20000000,4);fixed(0x10000000,4)
    array(0x800000,lambda n:(n+0x4d94cb1e)&MASK32,4)
    fixed(0x400000,4);fixed(0x4000,1)
    string(0x800,'f8',0x7971fa8844a6b396,lambda n:n^0xb396,'add')
    array(2,lambda n:(n+0x779b05f2)&MASK32,8)
    array(8,lambda n:((n+0xf725f2b9)&MASK32)^0xe7d8927e,4)
    fixed(0x40000,4);fixed(0x80000000,4);fixed(0x40,4);fixed(0x10,4)
    string(0x200,'100',0x08793cac12e6007f,lambda n:((n+0x7f)&65535)^0x3cac)
    fixed(1,1);fixed(0x400,4);fixed(0x80,4);fixed(0x100,4)
    fixed(0x2000,8);fixed(0x100000,8);fixed(0x8000,4)
    string(0x80000,'f0',0xe4efbc4771df8a23,lambda n:(n+0x8a23)&65535)
    string(0x10000,'c8',0x831d93c3e9bae3c9,lambda n:(n+0xe3c9)&65535)
    fixed(0x1000,1);fixed(0x20000,1)
    if m&0x200000:typed_pairs(r,14556)
    fixed(0x4000000,1);fixed(0x20,4)
    return result


def decode_monsters(data):
    r=Reader(data);count=(r.u32()+0x964957bc)&MASK32
    if not 1<=count<=100000:raise ValueError('MONSTER_TABLE_COUNT')
    rows=[]
    for ordinal in range(count):
        start=r.p
        try:
            row=base_identity(r);row['statsMask']=base_stats(r);row.update(monster_fields(r))
        except ValueError as exc:raise ValueError(f'{exc}: record={ordinal}, start={start}, offset={r.p}') from exc
        row.update(offset=start,size=r.p-start,rawSha256=hashlib.sha256(data[start:r.p]).hexdigest())
        rows.append(row)
    if r.p!=len(data):raise ValueError('MONSTER_TRAILING_BYTES')
    if len({v['monsterConfigId'] for v in rows})!=len(rows):raise ValueError('MONSTER_DUPLICATE_ID')
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    source=Path(a.source).resolve();out=Path(a.out).resolve()
    if not source.is_relative_to(ROOT) or not out.is_relative_to(ROOT/'.runtime/npc-appearance-20261017') or out.exists():raise ValueError('OWNED_PATH_REQUIRED')
    data=source.read_bytes();rows=decode_monsters(data)
    result=dict(source=str(source),sourceSha256=hashlib.sha256(data).hexdigest(),rows=rows,
                fullTableConsumed=True,resourcePath='Data/_ExcelBinOutput/MonsterExcelConfigData',
                tableDecoderRva='0xd63ab20',rowDecoderRvas=['0xbd6daa0','0x9ae6950','0xd411ac0'],
                gameProcessAccessed=False,nativeCalled=False,appearanceVerified=False)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(rows=len(rows),out=str(out),fullTableConsumed=True,gameProcessAccessed=False)))


if __name__=='__main__':main()
