"""Read-only bounded x64 PE function inspection; never attaches to a process."""
import argparse,bisect,json,mmap,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'.runtime/native-analysis/deps'))
from capstone import Cs,CS_ARCH_X86,CS_MODE_64
p=argparse.ArgumentParser();p.add_argument('image');p.add_argument('out');p.add_argument('rvas',nargs='+',type=lambda s:int(s,0));a=p.parse_args()
out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
with open(a.image,'rb') as f:
 with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
  pe=struct.unpack_from('<I',m,60)[0];ns=struct.unpack_from('<H',m,pe+6)[0];osz=struct.unpack_from('<H',m,pe+20)[0];opt=pe+24
  if struct.unpack_from('<H',m,opt)[0]!=0x20b:raise ValueError('PE32+ required')
  base=struct.unpack_from('<Q',m,opt+24)[0];er,esz=struct.unpack_from('<II',m,opt+112+24);secs=[]
  for i in range(ns):
   s=opt+osz+i*40;vs,va,rs,ro=struct.unpack_from('<IIII',m,s+8);secs.append((va,rs,ro))
  def off(rva):
   for va,rs,ro in secs:
    if va<=rva<va+rs:return ro+rva-va
   raise ValueError('RVA outside raw sections '+hex(rva))
  eo=off(er);funcs=[struct.unpack_from('<III',m,eo+j) for j in range(0,esz-11,12)];funcs.sort();starts=[x[0] for x in funcs];md=Cs(CS_ARCH_X86,CS_MODE_64);md.detail=True;results=[]
  for rva in a.rvas:
   idx=bisect.bisect_right(starts,rva)-1;beg,end,uw=funcs[idx]
   if not beg<=rva<end:raise ValueError('no function for '+hex(rva))
   if end-beg>65536:raise ValueError('function exceeds bound')
   data=m[off(beg):off(beg)+end-beg];rows=[]
   for ins in md.disasm(data,beg):
    row={'rva':hex(ins.address),'bytes':ins.bytes.hex(),'asm':ins.mnemonic+' '+ins.op_str}
    for op in ins.operands:
     if op.type==3 and ins.reg_name(op.mem.base)=='rip':
      dest=ins.address+ins.size+op.mem.disp;row['ripTarget']=hex(dest)
      try:
       raw=m[off(dest):off(dest)+128];row['targetHead']=raw[:24].hex()
       for enc in ['utf-8','utf-16-le']:
        try:
         text=raw.decode(enc).split('\0')[0]
         if len(text)>3 and all(c.isprintable() for c in text):row[enc]=text
        except UnicodeError:pass
      except ValueError:pass
    rows.append(row)
   item={'requested':hex(rva),'begin':hex(beg),'end':hex(end),'decodedBytes':sum(len(bytes.fromhex(x['bytes'])) for x in rows),'size':end-beg,'instructions':rows};results.append(item)
   (out/(hex(beg)+'.asm')).write_text('\n'.join(x['rva']+' '+x['asm']+(' ; '+json.dumps({k:v for k,v in x.items() if k not in ['rva','bytes','asm']},ensure_ascii=True) if 'ripTarget' in x else '') for x in rows),encoding='utf-8')
  (out/'functions.json').write_text(json.dumps({'image':str(Path(a.image).resolve()),'preferredBase':hex(base),'functions':results},indent=2),encoding='utf-8')
  print(json.dumps([{'begin':x['begin'],'size':x['size'],'decodedBytes':x['decodedBytes']} for x in results]))
