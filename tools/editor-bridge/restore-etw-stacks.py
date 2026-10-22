"""Recover raw ETW StackWalk payloads, cross-checking sampled IP and timing."""
import argparse,collections,datetime as dt,json,struct,xml.etree.ElementTree as E
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('xml',type=Path,help='Existing tracerpt XML including ProcessingErrorData raw payloads')
parser.add_argument('metadata',type=Path,help='Existing summarize-save-io.py JSON for modules and other events')
parser.add_argument('output',type=Path,help='New recovered events JSON; must not exist')
parser.add_argument('--validation',type=Path,help='New validation JSON; defaults beside output')
parser.add_argument('--pid',type=int,default=30488)
parser.add_argument('--tid',type=int,default=30492)
args=parser.parse_args()
validation=args.validation or args.output.with_name(args.output.stem+'.validation.json')
if args.output.resolve()==validation.resolve():parser.error('output and validation must differ')
for target in (args.output,validation):
    if target.exists():parser.error('Refusing to overwrite: '+str(target))
    if not target.parent.is_dir():parser.error('Output parent does not exist: '+str(target.parent))
def decode_payload(raw):
    if len(raw)<24 or (len(raw)-16)%8:raise ValueError('Malformed StackWalk payload length')
    ts,pid,tid=struct.unpack_from('<QII',raw)
    return ts,pid,tid,struct.unpack_from('<'+'Q'*((len(raw)-16)//8),raw,16)
n='{http://schemas.microsoft.com/win/2004/08/events/event}';t='{http://schemas.microsoft.com/win/2004/08/events/trace}'
existing=json.loads(args.metadata.read_text(encoding='utf-8'))
stacks=[];stats=collections.Counter();depths=collections.Counter();last_profile={};matches=[];seq=0
def num(v):return int(v.strip(),16) if v.strip().lower().startswith('0x') else int(v.strip())
ctx=E.iterparse(args.xml,events=('start','end'));_,root=next(ctx)
for kind,e in ctx:
    if kind!='end' or e.tag!=n+'Event':continue
    seq+=1;r=e.find(n+'RenderingInfo');name=r.findtext(t+'EventName') if r is not None else None
    if name not in ('StackWalk','PerfInfo'):
        root.remove(e);e.clear();continue
    op=r.findtext(n+'Opcode');sys=e.find(n+'System');stamp=sys.find(n+'TimeCreated').get('SystemTime')
    data={x.get('Name'):x.text or '' for x in e.findall(n+'EventData/'+n+'Data')}
    if name=='PerfInfo' and op=='SampleProf':
        tid=num(data['ThreadId'])
        if tid==args.tid:last_profile[tid]=(dt.datetime.fromisoformat(stamp),int(data['InstructionPointer'],16),stamp)
    if name=='StackWalk' and op!='Stack':
        stats['unsupportedStackWalkOpcode']+=1
        root.remove(e);e.clear();continue
    if name=='StackWalk':
        err=e.find(n+'ProcessingErrorData');recovered=err is not None
        if recovered:
            raw=bytes.fromhex(err.findtext(n+'EventPayload'))
            if len(raw)<24 or (len(raw)-16)%8:
                stats['rejectedMalformedPayload']+=1;root.remove(e);e.clear();continue
            ts,pid,tid,frames=decode_payload(raw)
            stats['recoveredAllProcesses']+=1;depths[len(frames)]+=1
            data={'EventTimeStamp':str(ts),'StackProcess':hex(pid),'StackThread':str(tid),'win:ExtraPayload':'0x'+raw[16:].hex()}
        else:
            ts=num(data['EventTimeStamp']);pid=num(data['StackProcess']);tid=num(data['StackThread'])
            frames=[int(v,16) for k,v in data.items() if k.startswith('Stack') and k[5:].isdigit() and v]
            extra=data.get('win:ExtraPayload','').removeprefix('0x')
            if extra:frames.extend(struct.unpack('<'+'Q'*(len(extra)//16),bytes.fromhex(extra)))
            stats['originalDecodedAllProcesses']+=1
            # Serialization consistency is separate from the independent PerfInfo check.
            encoded=struct.pack('<QII',ts,pid,tid)+struct.pack('<'+'Q'*len(frames),*frames)
            roundtrip=decode_payload(encoded)
            if roundtrip!=(ts,pid,tid,tuple(frames)):raise ValueError('Decoded-data layout roundtrip mismatch')
            stats['decodedLayoutRoundtripChecks']+=1
        if pid==args.pid:
            stats['recoveredGame' if recovered else 'originalDecodedGame']+=1
            if tid==args.tid:
                stats['recoveredMain' if recovered else 'originalDecodedMain']+=1
                recent=last_profile.get(tid)
                if recent:
                    delta=(dt.datetime.fromisoformat(stamp)-recent[0]).total_seconds()
                    if 0<=delta<0.001 and frames[0]==recent[1]:
                        stats['rawMainSampleIpAndTimeMatches' if recovered else 'decodedMainSampleIpAndTimeMatches']+=1
                        if len(matches)<12:matches.append({'source':'raw' if recovered else 'decoded','stackTime':stamp,'sampleTime':recent[2],'deltaSeconds':delta,'eventTimeStamp':ts,'pid':pid,'tid':tid,'firstFrame':hex(frames[0]),'sampleIP':hex(recent[1]),'depth':len(frames)})
            ex=sys.find(n+'Execution')
            stacks.append({'index':seq,'time':stamp,'pid':num(ex.get('ProcessID')),'tid':ex.get('ThreadID'),'event':'StackWalk','op':op,'recoveredFromRawPayload':recovered,'data':data})
    root.remove(e);e.clear()
existing['gameStacks']=stacks
existing['rawRecovery']={'scope':'Fixed StackWalk payload is uint64 EventTimeStamp, uint32 StackProcess, uint32 StackThread, followed by uint64 frame addresses. Raw and originally decoded samples are independently compared with nearby PerfInfo sampled IPs. Kernel/user fragments share EventTimeStamp and must merge.',
                       'statistics':dict(stats),'rawStackDepths':dict(depths),'sampleIpCrossCheckExamples':matches}
with args.output.open('x',encoding='utf-8') as out:json.dump(existing,out,indent=2)
with validation.open('x',encoding='utf-8') as out:json.dump(existing['rawRecovery'],out,indent=2)
print(json.dumps(existing['rawRecovery']['statistics'],indent=2))
