"""Find boundary-verified common x64 MOV/LEA RIP references in a disk PE."""
import argparse,bisect,json,mmap,re,struct,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.runtime/native-analysis/deps'))
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
p=argparse.ArgumentParser();p.add_argument('image');p.add_argument('out');p.add_argument('targets',nargs='+',type=lambda x:int(x,0));a=p.parse_args();targets=set(a.targets);candidates=[];rows=[];limited=[]
with open(a.image,'rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
 pe=struct.unpack_from('<I',m,60)[0];n=struct.unpack_from('<H',m,pe+6)[0];sz=struct.unpack_from('<H',m,pe+20)[0];o=pe+24;er,esz=struct.unpack_from('<II',m,o+136);secs=[]
 for i in range(n):
  k=o+sz+i*40;vs,va,rs,ro=struct.unpack_from('<IIII',m,k+8);ch=struct.unpack_from('<I',m,k+36)[0];secs.append((va,rs,ro,ch))
 def off(r):return next(ro+r-va for va,rs,ro,ch in secs if va<=r<va+rs)
 eo=off(er);fs=sorted(struct.unpack_from('<III',m,eo+i) for i in range(0,esz-11,12));starts=[x[0] for x in fs]
 pattern=re.compile(b'[\x48\x4c][\x8b\x8d][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]')
 for va,rs,ro,ch in secs:
  if not ch&0x20000000:continue
  for match in pattern.finditer(m,ro,ro+rs-4):
   pos=match.start();r=va+pos-ro;t=r+7+struct.unpack_from('<i',m,pos+3)[0]
   if t not in targets:continue
   i=bisect.bisect_right(starts,r)-1
   if i>=0 and fs[i][0]<=r<fs[i][1]:candidates.append((r,t,fs[i][0],fs[i][1]))
 md=Cs(CS_ARCH_X86,CS_MODE_64);cache={}
 for r,t,b,e in candidates:
  if e-b>65536:limited.append(hex(b));continue
  if b not in cache:cache[b]={x.address:x for x in md.disasm(m[off(b):off(b)+e-b],b)}
  x=cache[b].get(r)
  if x and x.size==7 and 'rip' in x.op_str:rows.append({'function':hex(b),'rva':hex(r),'target':hex(t),'instruction':x.mnemonic+' '+x.op_str})
result={'scope':'common MOV/LEA forms only; disk references do not reveal current pointer values','hits':rows,'limited':sorted(set(limited))};Path(a.out).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
