"""Disassemble bounded PE unwind function ranges from a disk image only."""
import argparse,bisect,json,mmap,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.runtime/native-analysis/deps'))
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
p=argparse.ArgumentParser();p.add_argument('image');p.add_argument('out');p.add_argument('rvas',nargs='+',type=lambda x:int(x,0));a=p.parse_args()
out=Path(a.out);out.mkdir(parents=True,exist_ok=True);result=[]
with open(a.image,'rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
 pe=struct.unpack_from('<I',m,60)[0];n=struct.unpack_from('<H',m,pe+6)[0];sz=struct.unpack_from('<H',m,pe+20)[0];opt=pe+24;er,esz=struct.unpack_from('<II',m,opt+136)
 secs=[struct.unpack_from('<IIII',m,opt+sz+i*40+8) for i in range(n)]
 def off(r):return next(ro+r-va for vs,va,rs,ro in secs if va<=r<va+rs)
 eo=off(er);fs=sorted(struct.unpack_from('<III',m,eo+i) for i in range(0,esz-11,12));starts=[x[0] for x in fs];md=Cs(CS_ARCH_X86,CS_MODE_64)
 for r in a.rvas:
  i=bisect.bisect_right(starts,r)-1
  if i<0 or not fs[i][0]<=r<fs[i][1]:raise ValueError('RVA outside runtime function')
  b,e,_=fs[i]
  if e-b>65536:raise ValueError('Function exceeds bounded size')
  target=out/f'{hex(r)}.asm'
  if target.exists():raise FileExistsError(target)
  ins=list(md.disasm(m[off(b):off(b)+e-b],b));target.write_text('\n'.join(f'{x.address:x}: {x.mnemonic} {x.op_str}' for x in ins),encoding='utf-8')
  result.append({'rva':hex(r),'begin':hex(b),'end':hex(e),'bytes':e-b,'decodedBytes':sum(x.size for x in ins),'complete':bool(ins) and ins[-1].address+ins[-1].size==e})
(out/'functions.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
