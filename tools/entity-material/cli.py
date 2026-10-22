"""Prepare, dispatch once, and independently verify bounded native primitive materials."""
from __future__ import annotations
import argparse,ctypes,importlib.util,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='strict')
from material_contract import read,write,sha,require
from material_build import prepare,ROOT,p
from material_receipt import decode,manifest,verify

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('ARGUMENTS:'+message)

def dispatch(run,*,direct=False,queue=None):
    require(bool(direct)!=bool(queue),'SELECT_EXACTLY_ONE_DISPATCH_TRANSPORT')
    run,prepared,built=manifest(run)
    require(prepared['launchable'] and not prepared['compileOnly'],'NONLAUNCHABLE_CARD')
    if queue:
        spec=importlib.util.spec_from_file_location('_material_elevated_request',ROOT/'tools/editor-bridge/elevated-request.py')
        client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
        return client.send_native_map('entity-material',str(run),timeout=300,queue_dir=Path(queue))
    require(ctypes.windll.shell32.IsUserAnAdmin()!=0,'DIRECT_ELEVATED_REQUIRES_ADMINISTRATOR')
    require(not any((run/n).exists() for n in ('dispatch.claim','launch.claim','attempt.used','exit.json')),'CARD_ALREADY_CONSUMED_DO_NOT_REPLAY')
    require(datetime.now(timezone.utc)<datetime.fromisoformat(prepared['expiresUtc']),'PREPARATION_EXPIRED')
    for source,digest in prepared['sourceHashes'].items():require(sha(source)==digest,'SOURCE_CHANGED_BEFORE_DISPATCH')
    p.verify_disk(p.load_profile());p.validate_session(prepared['session']);host=p.powershell_host()
    write(run/'dispatch.claim',dict(startedUtc=datetime.now(timezone.utc).isoformat(),wrapperSha256=built['wrapperSha256'],host=host))
    env=os.environ.copy();env['PSModulePath']=str(Path(host['path']).parent/'Modules')
    invoked=subprocess.run([host['path'],'-NoProfile','-NonInteractive','-File',str(run/'invoke-material.ps1')],cwd=run,stdin=subprocess.DEVNULL,capture_output=True,text=True,env=env,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (run/'dispatch.stdout.txt').write_text(invoked.stdout or '',encoding='utf-8');(run/'dispatch.stderr.txt').write_text(invoked.stderr or '',encoding='utf-8')
    result=decode(run);write(run/'result.json',result);return result

def uncertainty(run):
    claimed=bool(run) and any((Path(run)/n).exists() for n in ('map-queue-claim.json','dispatch.claim','launch.claim','attempt.used'))
    if run:
        try:
            result=read(Path(run)/'exit.json')
            if result.get('scope')=='FIXED_ENTITY_MATERIAL_ACTION' and result.get('executed') is False and not (Path(run)/'attempt.used').exists():claimed=False
        except (OSError,ValueError):pass
    return dict(called=claimed,nativeStarted=claimed,outcomeUncertain=claimed,cleanupVerified=not claimed,safeToRelease=not claimed,replayForbidden=claimed)

def main(argv=None):
    args=None
    try:
        parser=Parser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True,parser_class=Parser)
        for command in ('inspect','prepare'):
            item=sub.add_parser(command);item.add_argument('--baseline',type=Path,required=True)
            if command=='inspect':item.add_argument('--entity-id',type=int,action='append',required=True)
            else:
                item.add_argument('--inspection',type=Path,required=True);item.add_argument('--request',type=Path,required=True);item.add_argument('--save',type=Path,required=True)
        item=sub.add_parser('compile-check');item.add_argument('--large-scene',action='store_true');item.add_argument('--mode',choices=('inspect','set'),default='set');item.add_argument('--fixture-count',type=int,default=17)
        item=sub.add_parser('dispatch');item.add_argument('--run',type=Path,required=True)
        transport=item.add_mutually_exclusive_group(required=True);transport.add_argument('--direct-elevated',action='store_true');transport.add_argument('--elevated-queue',type=Path)
        item=sub.add_parser('decode');item.add_argument('--run',type=Path,required=True)
        item=sub.add_parser('verify');item.add_argument('--run',type=Path,required=True);item.add_argument('--inspection-run',type=Path,required=True)
        args=parser.parse_args(argv)
        if args.command in ('inspect','prepare','compile-check'):result=prepare(args,inspect=args.command=='inspect',compile_only=args.command=='compile-check')
        elif args.command=='dispatch':result=dispatch(args.run,direct=args.direct_elevated,queue=args.elevated_queue)
        elif args.command=='decode':result=decode(args.run)
        else:result=verify(args.run,args.inspection_run)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('ok') is True else 2
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration,subprocess.SubprocessError) as exc:
        state=uncertainty(getattr(args,'run',None))
        if getattr(args,'command',None) in ('decode','verify'):
            state.update(called=False,nativeStarted=False)
        print(json.dumps(dict(ok=False,stage=getattr(args,'command','arguments'),error=str(exc),**state),ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
