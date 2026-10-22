"""Recover observed caller-return/callee-frame pairs from ETW game stacks."""
import argparse,bisect,collections,json,mmap,struct
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('events');p.add_argument('image');p.add_argument('out');p.add_argument('returns',nargs='+',type=lambda x:int(x,0));a=p.parse_args()
d=json.loads(Path(a.events).read_text(encoding='utf-8'));md=next(x['data'] for x in d['gameModules'] if x['data'].get('FileName','').endswith('YuanShen.exe'));base=int(md['ImageBase'],16);size=int(md['ImageSize'],16)
with open(a.image,'rb') as f:
 with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
  pe=struct.unpack_from('<I',m,60)[0];ns=struct.unpack_from('<H',m,pe+6)[0];opt=pe+24;osz=struct.unpack_from('<H',m,pe+20)[0];er,esz=struct.unpack_from('<II',m,opt+112+24)
  sections=[struct.unpack_from('<IIII',m,opt+osz+i*40+8) for i in range(ns)]
  eo=next(ro+er-va for vs,va,rs,ro in sections if va<=er<va+rs)
  funcs=sorted(struct.unpack_from('<III',m,eo+j) for j in range(0,esz-11,12));starts=[x[0] for x in funcs]
def fn(rva):
 i=bisect.bisect_right(starts,rva)-1
 return funcs[i][0] if i>=0 and funcs[i][0]<=rva<funcs[i][1] else rva
counts={r:collections.Counter() for r in a.returns};examples={};seen=set()
for x in d['gameStacks']:
 z=x['data']
 if int(z['StackThread'])!=30492:continue
 frames=[int(v,16) for k,v in z.items() if k.startswith('Stack') and k[5:].isdigit() and v];raw=z.get('win:ExtraPayload','').removeprefix('0x')
 if raw and len(raw)%16==0:frames+=list(struct.unpack('<'+'Q'*(len(raw)//16),bytes.fromhex(raw)))
 for i,addr in enumerate(frames):
  ret=addr-base
  if ret not in counts or not i:continue
  callee=frames[i-1]-base
  if not 0<=callee<size:continue
  key=(z['EventTimeStamp'],ret,callee)
  if key in seen:continue
  seen.add(key);start=fn(callee);counts[ret][start]+=1
  examples.setdefault((ret,start),{'time':x['time'],'calleeFrameRva':hex(callee),'nearbyFrames':[hex(v-base) for v in frames[max(0,i-4):i+3] if base<=v<base+size]})
out={'scope':'Adjacent frames in sampled stack: observed dynamic call-chain evidence, not argument contract; tail calls/inlining may hide frames','edges':[]}
for ret,c in counts.items():
 for target,n in c.most_common():out['edges'].append({'callerReturnRva':hex(ret),'adjacentCalleeFunction':hex(target),'samples':n,'example':examples[(ret,target)]})
Path(a.out).write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out))
