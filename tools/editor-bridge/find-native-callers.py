"""Find validated direct-call references in executable PE sections (disk only)."""
import argparse,bisect,json,mmap,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.runtime/native-analysis/deps'))
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
p=argparse.ArgumentParser();p.add_argument('image');p.add_argument('out');p.add_argument('targets',nargs='+',type=lambda x:int(x,0));a=p.parse_args();targets=set(a.targets)
with open(a.image,'rb') as f:
 with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
  pe=struct.unpack_from('<I',m,60)[0];ns=struct.unpack_from('<H',m,pe+6)[0];osz=struct.unpack_from('<H',m,pe+20)[0];opt=pe+24;er,esz=struct.unpack_from('<II',m,opt+136);secs=[]
  for i in range(ns):
   o=opt+osz+i*40;vs,va,rs,ro=struct.unpack_from('<IIII',m,o+8);ch=struct.unpack_from('<I',m,o+36)[0];secs.append((va,rs,ro,ch))
  def off(rva):return next(ro+rva-va for va,rs,ro,ch in secs if va<=rva<va+rs)
  eo=off(er);funcs=sorted(struct.unpack_from('<III',m,eo+i) for i in range(0,esz-11,12));starts=[x[0] for x in funcs];candidates=[]
  for va,rs,ro,ch in secs:
   if not ch&0x20000000:continue
   pos=ro
   while True:
    pos=m.find(b'\xe8',pos,ro+rs-4)
    if pos<0:break
    call=va+pos-ro;target=call+5+struct.unpack_from('<i',m,pos+1)[0]
    if target in targets:
     i=bisect.bisect_right(starts,call)-1
     if i>=0 and funcs[i][0]<=call<funcs[i][1]:candidates.append((call,target,funcs[i][0],funcs[i][1]))
    pos+=1
  md=Cs(CS_ARCH_X86,CS_MODE_64);decoded={};rows=[]
  for call,target,beg,end in candidates:
   if end-beg>65536:continue
   if beg not in decoded:decoded[beg]={x.address:x for x in md.disasm(m[off(beg):off(beg)+end-beg],beg)}
   ins=decoded[beg].get(call)
   if ins and ins.mnemonic=='call' and ins.size==5:rows.append({'call':hex(call),'target':hex(target),'callerFunction':hex(beg)})
Path(a.out).write_text(json.dumps(rows,indent=2),encoding='utf-8');print(json.dumps(rows))
