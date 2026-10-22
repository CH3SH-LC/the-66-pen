"""Stream an existing tracerpt XML; retain only target-process file/image evidence."""
import argparse,json,pathlib,xml.etree.ElementTree as E,collections
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('xml',type=pathlib.Path);parser.add_argument('out',type=pathlib.Path)
parser.add_argument('--pid',type=int,default=30488);parser.add_argument('--tid',type=int,default=30492)
args=parser.parse_args();src=args.xml;out=args.out;n='{http://schemas.microsoft.com/win/2004/08/events/event}';t='{http://schemas.microsoft.com/win/2004/08/events/trace}'
if out.exists():parser.error('Refusing to overwrite: '+str(out))
counts=collections.Counter();game=[];target=[];modules=[];stacks=[];threadio=[];seq=0
def num(v):
 try:return int(v.strip(),16) if v.strip().lower().startswith('0x') else int(v.strip())
 except:return -1
ctx=E.iterparse(src,events=('start','end'));_,root=next(ctx)
for kind,e in ctx:
 if kind!='end' or e.tag!=n+'Event':continue
 seq+=1
 sysel=e.find(n+'System');render=e.find(n+'RenderingInfo');event=render.findtext(t+'EventName') if render is not None else None
 if event in ('FileIo','Image','StackWalk'):
  execution=sysel.find(n+'Execution');pid=num(execution.get('ProcessID',''));data={d.get('Name'):d.text or '' for d in e.findall(n+'EventData/'+n+'Data')};op=render.findtext(n+'Opcode');counts[event]+=1
  row={'index':seq,'time':sysel.find(n+'TimeCreated').get('SystemTime'),'pid':pid,'tid':execution.get('ThreadID'),'event':event,'op':op,'data':data}
  if event=='StackWalk' and num(data.get('StackProcess',''))==args.pid:stacks.append(row)
  if event=='FileIo' and pid==args.pid:game.append(row)
  # Kernel copy writes may have header PID 4 but retain the initiating TTID.
  if event=='FileIo' and num(data.get('TTID',''))==args.tid:threadio.append(row)
  if event=='FileIo' and any('BeyondLocal' in v or '1073741832' in v for v in data.values()):target.append(row)
  if event=='Image' and (pid==args.pid or any(k.lower() in ('processid','process id') and num(v)==args.pid for k,v in data.items())):modules.append(row)
 root.remove(e);e.clear()
result={'targetPid':args.pid,'targetTid':args.tid,'counts':dict(counts),'targetFileEvents':target,'gameFileEvents':game,'gameModules':modules,'gameStacks':stacks,'saveThreadFileEvents':threadio}
out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'counts':dict(counts),'targetFileEvents':len(target),'gameFileEvents':len(game),'gameModules':len(modules)}))
