"""Summarize ETW sampled stacks by PE runtime function; reads files only."""
import argparse,bisect,collections,json,mmap,struct
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('events');p.add_argument('image');p.add_argument('out');p.add_argument('--compare');p.add_argument('--tid',type=int,default=30492);a=p.parse_args()
if Path(a.out).exists():p.error('Refusing to overwrite: '+a.out)
d=json.loads(Path(a.events).read_text(encoding='utf-8'))
image_events=[x for x in d['gameModules'] if x['data'].get('FileName','').endswith('YuanShen.exe')]
rundown=[x for x in image_events if x['op'] in ('DCStart','DCEnd')]
if not rundown or not {'DCStart','DCEnd'} <= {x['op'] for x in rundown}:raise ValueError('missing start/end image rundown')
base=int(rundown[0]['data']['ImageBase'],16);size=int(rundown[0]['data']['ImageSize'],16)
if any(int(x['data']['ImageBase'],16)!=base for x in rundown):raise ValueError('ambiguous resident game mapping')
if any(x['op']=='UnLoad' and int(x['data']['ImageBase'],16)==base for x in image_events):raise ValueError('resident game mapping unloaded')
secondary_mappings=[x for x in image_events if int(x['data']['ImageBase'],16)!=base]
with open(a.image,'rb') as f:
 with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
  pe=struct.unpack_from('<I',m,60)[0];ns=struct.unpack_from('<H',m,pe+6)[0];opt=pe+24;osz=struct.unpack_from('<H',m,pe+20)[0];er,esz=struct.unpack_from('<II',m,opt+112+24);sections=[]
  for i in range(ns):
   vs,va,rs,ro=struct.unpack_from('<IIII',m,opt+osz+i*40+8);sections.append((va,rs,ro))
  eo=next(ro+er-va for va,rs,ro in sections if va<=er<va+rs)
  funcs=sorted(struct.unpack_from('<III',m,eo+j) for j in range(0,esz-11,12));starts=[x[0] for x in funcs]
def function(rva):
 i=bisect.bisect_right(starts,rva)-1
 return funcs[i][0] if i>=0 and funcs[i][0]<=rva<funcs[i][1] else rva
samples={}
for r in d['gameStacks']:
 data=r['data'];key=(int(data['StackThread']),data['EventTimeStamp'])
 addresses=[int(v,16) for k,v in data.items() if k.startswith('Stack') and k[5:].isdigit() and v]
 raw=data.get('win:ExtraPayload','').removeprefix('0x')
 if raw:
  if len(raw)%16:raise ValueError('unaligned stack payload')
  addresses.extend(struct.unpack('<'+'Q'*(len(raw)//16),bytes.fromhex(raw)))
 game=[function(x-base) for x in addresses if base<=x<base+size]
 item=samples.setdefault(key,{'functions':set(),'leaf':None})
 item['functions'].update(game)
 if game and item['leaf'] is None:item['leaf']=game[0]
threads=collections.Counter();inc=collections.Counter();leaf=collections.Counter();main_samples=0
for (tid,stamp),sample in samples.items():
 if not sample['functions']:continue
 threads[tid]+=1
 if tid==a.tid:
  main_samples+=1;inc.update(sample['functions']);leaf[sample['leaf']]+=1
result={'scope':'CPU sampled stacks; function frequency is not proof of editing semantics','mainThread':a.tid,'moduleBase':hex(base),'excludedSecondaryImageEvents':secondary_mappings,'stackRecords':len(d['gameStacks']),'mergedSamples':len(samples),'threadSamplesWithGame':dict(threads),'mainSamplesWithGame':main_samples,'inclusive':{hex(k):v for k,v in inc.most_common()},'leaf':{hex(k):v for k,v in leaf.most_common()}}
if a.compare:
 b=json.loads(Path(a.compare).read_text(encoding='utf-8'));bn=b['mainSamplesWithGame'];rows=[]
 for k,v in result['inclusive'].items():
  bv=b['inclusive'].get(k,0);rate=v/main_samples if main_samples else 0;br=bv/bn if bn else 0
  if v>=5:rows.append({'function':k,'currentCount':v,'referenceCount':bv,'currentRate':rate,'referenceRate':br,'difference':rate-br})
 result['differentialCandidates']=sorted(rows,key=lambda x:x['difference'],reverse=True)[:100]
Path(a.out).write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'mainSamplesWithGame':main_samples,'uniqueMainFunctions':len(inc),'topFunctions':list(result['inclusive'].items())[:8],'differentialCandidates':result.get('differentialCandidates',[])[:12]}))
