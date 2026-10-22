"""Static installed-file research only; never loads or calls game code."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/mondstadt/asset-inspection/research'
sys.path[:0] = [str(ROOT/'.runtime/native-analysis/deps'),
               str(ROOT/'.runtime/scratch/overnight-features-20261013/task-bd')]

def main():
    from signatures import h, m, signature
    OUT.mkdir(parents=True, exist_ok=True)
    h.OUT = OUT
    wanted = {'MeshFilter', 'Mesh', 'MeshRenderer', 'SkinnedMeshRenderer'}
    classes = {}
    for owner in range(4000):
        name = m.definition_name(owner)['identifier']['name']
        if name not in wanted:
            continue
        methods = [signature(x['methodIndex']) for x in h.methods(owner)['methods']]
        (OUT/(name+'-signatures.json')).write_text(json.dumps(methods, indent=2), encoding='utf-8')
        refs = m.definition_usage_refs(owner)
        classes[name] = refs
        for row in methods:
            label = (row.get('name') or {}).get('name', '')
            if label not in ('get_sharedMesh', 'get_bounds_Injected', 'INTERNAL_get_bounds',
                             'get_localBounds_Injected', 'INTERNAL_get_localBounds'):
                continue
            rva = int(row['method']['functionRva'], 16)
            h.dump(rva)
            first = next(m.md.disasm(m.get(rva,32), rva))
            if first.mnemonic == 'jmp' and first.op_str.startswith('0x'):
                h.dump(int(first.op_str,16))
            print(name, label, hex(rva), 'params', [p['type']['kind'] for p in row['parameters']])
    for rva in (0x19cb2e60, 0x19cd25d0, 0x982810, 0x19cd26c0, 0x19cd26e0):
        h.dump(rva)
        first = next(m.md.disasm(m.get(rva,32),rva))
        if first.mnemonic == 'jmp' and first.op_str.startswith('0x'):
            h.dump(int(first.op_str,16))
    result = dict(imageSha256=m.sha,metadataSha256=m.metadata_sha,classes=classes)
    (OUT/'mesh-class-slots.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    rvas = [0x19cbcac0,0x1453c60,0x1453c10,0x1452b80,0x14cdc50,
            0x19d071c0,0x19d071f0,0x19d07210,0x19c9b820,0x19d07370,
            0x1437760,0x14377c0,0x19cb2e60,0x14389f0,0x19cd25d0,0x982810,
            0x19cd26c0,0x982f40,0x19ca1d70,0x984720,0x19ca0300,0x97c820]
    slots={}
    for key in ('Mesh','MeshFilter','MeshRenderer'):
        refs=[x for x in classes[key]['refs'] if x['kind']==1 and x['usage']==0x4c1b1]
        if len(refs)!=1:raise ValueError('Class slot is not unique: '+key)
        slots[key]=refs[0]['slot']
    profile=dict(schemaVersion=1,imageSha256=m.sha,metadataSha256=m.metadata_sha,
        classSlots=slots,functions=[dict(rva=hex(r),head32=m.get(r,32).hex()) for r in rvas],
        source='static installed image + metadata; no runtime claim',runtimeVerified=False)
    (ROOT/'tools/game-executor/asset_inspection_profile.json').write_text(json.dumps(profile,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v['refs'] for k,v in classes.items()}))

if __name__ == '__main__':
    main()
