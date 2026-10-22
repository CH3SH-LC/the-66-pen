"""Observe runtime state or capture the game's native backbuffer, without desktop APIs.

prepare --session SESSION.json --target-level ID [--operation observe|runtime-state|render-frame]
builds an immutable card. Render capture allocates a temporary Texture2D and is not read-only.
dispatch --run RUN --elevated-queue QUEUE consumes it through the fixed broker.
decode is offline; compile-check uses an expired synthetic identity.
Official trial control is staged; asynchronous completion needs separate bound receipts.
"""
import argparse,ctypes,importlib.util,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='strict')
import json
from contract import read,write,sha,require
from build import prepare,ROOT,p
from receipt import decode,manifest
class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('ARGUMENTS:'+message)
def dispatch(value,*,direct=False,queue=None):
    require(bool(direct)!=bool(queue),'SELECT_EXACTLY_ONE_DISPATCH_TRANSPORT')
    run,prepared,built=manifest(value);require(prepared['launchable'] and not prepared['compileOnly'],'NONLAUNCHABLE_CARD')
    if queue:
        spec=importlib.util.spec_from_file_location('_observe_broker',ROOT/'tools/editor-bridge/elevated-request.py');client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
        return client.send_native_map('playtest-control',str(run),timeout=300,queue_dir=Path(queue))
    require(ctypes.windll.shell32.IsUserAnAdmin()!=0,'DIRECT_ELEVATED_REQUIRES_ADMINISTRATOR')
    require(not any((run/n).exists() for n in ('dispatch.claim','launch.claim','attempt.used','exit.json')),'CARD_ALREADY_CONSUMED_DO_NOT_REPLAY')
    require(datetime.now(timezone.utc)<datetime.fromisoformat(prepared['expiresUtc']),'PREPARATION_EXPIRED')
    for source,digest in prepared['sourceHashes'].items():require(sha(source)==digest,'SOURCE_CHANGED_BEFORE_DISPATCH')
    p.verify_disk(p.load_profile());p.validate_session(prepared['session']);host=p.powershell_host()
    if prepared['kind']=='playtest-control-prepared-v12':
        from bounds_build import revalidate_proofs
        revalidate_proofs(prepared)
    elif prepared['kind']=='playtest-control-prepared-v3':
        from control_build import claim_write
        claim_write(run,prepared)
    elif prepared['kind']=='playtest-control-prepared-v4':
        from input_build import revalidate_proofs,claim_write
        revalidate_proofs(prepared);claim_write(run,prepared)
    elif prepared['kind']=='playtest-control-prepared-v5':
        from vitals_build import revalidate_proofs
        revalidate_proofs(prepared)
    elif prepared['kind']=='playtest-control-prepared-v6':
        from inventory_build import revalidate_proofs
        revalidate_proofs(prepared)
    elif prepared['kind']=='playtest-control-prepared-v7':
        from shop_build import revalidate_proofs,claim_write
        revalidate_proofs(prepared);claim_write(run,prepared)
    elif prepared['kind']=='playtest-control-prepared-v8':
        from contact_build import revalidate_proofs
        revalidate_proofs(prepared)
    elif prepared['kind']=='playtest-control-prepared-v9':
        from directory_build import revalidate_proofs
        revalidate_proofs(prepared)
    elif prepared['kind']=='playtest-control-prepared-v10':
        from targeted_build import revalidate_proofs,claim_write
        revalidate_proofs(prepared);claim_write(run,prepared)
    write(run/'dispatch.claim',dict(startedUtc=datetime.now(timezone.utc).isoformat(),wrapperSha256=built['wrapperSha256'],host=host))
    env=os.environ.copy();env['PSModulePath']=str(Path(host['path']).parent/'Modules')
    invoked=subprocess.run([host['path'],'-NoProfile','-NonInteractive','-File',str(run/'invoke-observe.ps1')],cwd=run,stdin=subprocess.DEVNULL,capture_output=True,text=True,env=env,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (run/'dispatch.stdout.txt').write_text(invoked.stdout or '',encoding='utf-8');(run/'dispatch.stderr.txt').write_text(invoked.stderr or '',encoding='utf-8')
    result=decode(run);write(run/'result.json',result);return result
def uncertainty(value):
    run=Path(value) if value is not None else None
    claimed=bool(run and any((run/n).exists() for n in ('map-queue-claim.json','dispatch.claim','launch.claim','attempt.used')))
    if run:
        try:
            e=read(run/'exit.json')
            if e.get('scope') in ('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_ACCEPTANCE','FIXED_PLAYTEST_CONTROL','FIXED_PLAYTEST_INPUT','FIXED_PLAYTEST_VITALS','FIXED_PLAYTEST_INVENTORY','FIXED_PLAYTEST_SHOP','FIXED_PLAYTEST_CONTACT','FIXED_PLAYTEST_DIRECTORY','FIXED_PLAYTEST_TARGETED','FIXED_PLAYTEST_SCENE_FRAME','FIXED_PLAYTEST_BOUNDS') and e.get('executed') is False and not (run/'attempt.used').exists():claimed=False
        except (OSError,ValueError,TypeError):pass
    return dict(called=claimed,nativeStarted=claimed,outcomeUncertain=claimed,cleanupVerified=not claimed,safeToRelease=not claimed,replayForbidden=bool(run))
def main(argv=None):
    args=None
    try:
        parser=Parser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True,parser_class=Parser)
        from control_contract import OPERATIONS
        INPUT_OPERATIONS=('input-state','move-pulse','attack-tap','interact-option')
        def input_arguments(item):
            item.add_argument('--target-baseline',type=Path);item.add_argument('--target-id');item.add_argument('--expected-editor-guid',type=int);item.add_argument('--expected-runtime-id',type=int)
            item.add_argument('--ui-action',choices=('goods','bag-item','quantity-one','buy','sell-open','sell','back'));item.add_argument('--ui-id');item.add_argument('--ui-row',type=int);item.add_argument('--config-id',type=int);item.add_argument('--ui-baseline',type=Path)
            item.add_argument('--input-baseline',type=Path);item.add_argument('--input-id');item.add_argument('--angle',type=float,default=0.0);item.add_argument('--strength',type=float,default=0.5);item.add_argument('--duration-ms',type=int,default=500);item.add_argument('--max-distance',type=float,default=2.0);item.add_argument('--option-index',type=int);item.add_argument('--label')
        item=sub.add_parser('prepare');item.add_argument('--session',type=Path,required=True);item.add_argument('--target-level',type=int,required=True)
        item.add_argument('--operation',choices=('observe','runtime-state','render-frame','scene-frame','scene-overview','scene-cleanup-state','bounds-state','bounds-expand','enter','exit','vitals-state','inventory-state','shop-state','shop-ui','contact-state','trial-entities','targeted-interact')+tuple(OPERATIONS)+tuple(INPUT_OPERATIONS),default='observe');item.add_argument('--page-start',type=int,default=0);item.add_argument('--previous-run',type=Path);input_arguments(item)
        item=sub.add_parser('compile-check');item.add_argument('--operation',choices=('observe','runtime-state','render-frame','scene-frame','scene-overview','scene-cleanup-state','bounds-state','bounds-expand','vitals-state','inventory-state','shop-state','shop-ui','contact-state','trial-entities','targeted-interact')+tuple(OPERATIONS)+tuple(INPUT_OPERATIONS),default='observe');item.add_argument('--page-start',type=int,default=0);input_arguments(item)
        item=sub.add_parser('dispatch');item.add_argument('--run',type=Path,required=True)
        transport=item.add_mutually_exclusive_group(required=True);transport.add_argument('--direct-elevated',action='store_true');transport.add_argument('--elevated-queue',type=Path)
        item=sub.add_parser('decode');item.add_argument('--run',type=Path,required=True)
        item=sub.add_parser('inventory-diff');item.add_argument('--before-run',type=Path,required=True);item.add_argument('--after-run',type=Path,required=True);item.add_argument('--queries',type=Path,required=True)
        item=sub.add_parser('control');item.add_argument('--direction',choices=('enter','exit'),required=True);item.add_argument('--operation-id',required=True);item.add_argument('--session',type=Path,required=True);item.add_argument('--target-level',type=int,required=True);item.add_argument('--previous-run',type=Path);item.add_argument('--elevated-queue',type=Path,required=True);item.add_argument('--timeout-seconds',type=int,default=1200);item.add_argument('--max-cards',type=int,default=32)
        args=parser.parse_args(argv)
        if args.command in ('prepare','compile-check'):
            if args.operation=='observe':
                require(args.page_start==0,'OBSERVATION_HAS_NO_PAGE');result=prepare(args,compile_only=args.command=='compile-check')
            elif args.operation in ('bounds-state','bounds-expand'):
                from bounds_build import prepare as prepare_bounds
                result=prepare_bounds(args,compile_only=args.command=='compile-check')
            elif args.operation in ('scene-frame','scene-overview','scene-cleanup-state'):
                from scene_frame_build import prepare as prepare_scene_frame
                result=prepare_scene_frame(args,compile_only=args.command=='compile-check')
            elif args.operation in OPERATIONS:
                from control_build import prepare as prepare_control
                result=prepare_control(args,compile_only=args.command=='compile-check')
            elif args.operation in INPUT_OPERATIONS:
                from input_build import prepare as prepare_input
                result=prepare_input(args,compile_only=args.command=='compile-check')
            elif args.operation=='vitals-state':
                from vitals_build import prepare as prepare_vitals
                result=prepare_vitals(args,compile_only=args.command=='compile-check')
            elif args.operation=='inventory-state':
                from inventory_build import prepare as prepare_inventory
                result=prepare_inventory(args,compile_only=args.command=='compile-check')
            elif args.operation in ('shop-state','shop-ui'):
                from shop_build import prepare as prepare_shop
                result=prepare_shop(args,compile_only=args.command=='compile-check')
            elif args.operation=='contact-state':
                from contact_build import prepare as prepare_contact
                result=prepare_contact(args,compile_only=args.command=='compile-check')
            elif args.operation=='trial-entities':
                from directory_build import prepare as prepare_directory
                result=prepare_directory(args,compile_only=args.command=='compile-check')
            elif args.operation=='targeted-interact':
                from targeted_build import prepare as prepare_targeted
                result=prepare_targeted(args,compile_only=args.command=='compile-check')
            else:
                from acceptance_build import prepare as prepare_acceptance
                result=prepare_acceptance(args,compile_only=args.command=='compile-check')
        elif args.command=='dispatch':result=dispatch(args.run,direct=args.direct_elevated,queue=args.elevated_queue)
        elif args.command=='inventory-diff':
            from inventory_diff import compare
            result=compare(args.before_run,args.after_run,read(args.queries))
        elif args.command=='control':
            from control_flow import run
            result=run(args)
        else:result=decode(args.run)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('ok') is True else 2
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration,subprocess.SubprocessError) as exc:
        state=uncertainty(getattr(args,'run',None))
        if getattr(args,'command',None)=='decode':state.update(called=False,nativeStarted=False)
        print(json.dumps(dict(ok=False,stage=getattr(args,'command','arguments'),error=str(exc),**state),ensure_ascii=False,allow_nan=False));return 2
if __name__=='__main__':raise SystemExit(main())
