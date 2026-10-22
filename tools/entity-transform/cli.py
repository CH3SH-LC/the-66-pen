"""Existing entity transforms through the 7.1 native numeric-editor transaction.

inspect and prepare/set compile only unless --direct-elevated is explicit.
dispatch consumes a prepared card once. decode and verify-save are offline.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
# The fixed elevated broker deliberately uses -I -S. Only this checked-in tool
# directory is made importable; it does not restore ambient site-packages.
sys.path.insert(0,str(Path(__file__).resolve().parent))
if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8',errors='strict')
from contract import read, write, sha, require
from build import prepare, ROOT, p
from receipt import decode, manifest
from save_verify import verify

class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise ValueError('ARGUMENTS:'+message)

def dispatch(run, *, direct=False, queue=None):
    require(bool(direct) != bool(queue),'SELECT_EXACTLY_ONE_DISPATCH_TRANSPORT')
    run,prepared,built = manifest(run)
    require(prepared['launchable'] and not prepared['compileOnly'],'NONLAUNCHABLE_CARD')
    if queue:
        spec = importlib.util.spec_from_file_location('_transform_elevated_request',ROOT/'tools/editor-bridge/elevated-request.py')
        client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client)
        return client.send_native_map('entity-transform',str(run),timeout=300,queue_dir=Path(queue))
    require(ctypes.windll.shell32.IsUserAnAdmin() != 0,'DIRECT_ELEVATED_REQUIRES_ADMINISTRATOR')
    require(not any((run/name).exists() for name in ('dispatch.claim','launch.claim','attempt.used','exit.json')),'CARD_ALREADY_CONSUMED_DO_NOT_REPLAY')
    require(datetime.now(timezone.utc) < datetime.fromisoformat(prepared['expiresUtc']),'PREPARATION_EXPIRED')
    for source,digest in prepared['sourceHashes'].items():
        require(sha(source) == digest,'SOURCE_CHANGED_BEFORE_DISPATCH')
    p.verify_disk(p.load_profile())
    p.validate_session(prepared['session'])
    host = p.powershell_host()
    # The immutable claim precedes any launch. A missing receipt after this point
    # is unknown, never permission to retry the native operation.
    write(run/'dispatch.claim',dict(startedUtc=datetime.now(timezone.utc).isoformat(),wrapperSha256=built['wrapperSha256'],host=host))
    env = os.environ.copy();env['PSModulePath'] = str(Path(host['path']).parent/'Modules')
    invoked = subprocess.run([host['path'],'-NoProfile','-NonInteractive','-File',str(run/'invoke-transform.ps1')],
                             cwd=run,stdin=subprocess.DEVNULL,capture_output=True,text=True,env=env,timeout=300,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (run/'dispatch.stdout.txt').write_text(invoked.stdout or '',encoding='utf-8')
    (run/'dispatch.stderr.txt').write_text(invoked.stderr or '',encoding='utf-8')
    result = decode(run)
    write(run/'result.json',result)
    return result

def uncertainty(run):
    if run is None:
        return dict(called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=False)
    path = Path(run)
    claimed = any((path/n).exists() for n in ('map-queue-claim.json','dispatch.claim','launch.claim','attempt.used'))
    try:
        exit_result = read(path/'exit.json')
        if exit_result.get('scope') in ('FIXED_ENTITY_TRANSFORM_ACTION','FIXED_ENTITY_PHYSICS_QUERY') and exit_result.get('executed') is False and not (path/'attempt.used').exists():
            return dict(called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=True)
    except (OSError,ValueError,TypeError):
        pass
    return dict(called=claimed,nativeStarted=claimed,outcomeUncertain=claimed,cleanupVerified=not claimed,safeToRelease=not claimed,replayForbidden=claimed)

def failure_state(run,command):
    if command not in ('decode','physics-decode','verify-save'):
        return uncertainty(run)
    # Offline validation never dispatches. A disk/domain mismatch must not turn
    # an already proven closed native transaction into a new unknown callback.
    try:
        prior=decode(run)
        return dict(called=False,nativeStarted=False,outcomeUncertain=prior['outcomeUncertain'],
            cleanupVerified=prior['cleanupVerified'],safeToRelease=prior['safeToRelease'],replayForbidden=True,
            historicalTransformExecution={key:prior[key] for key in
                ('called','nativeStarted','outcomeUncertain','cleanupVerified','safeToRelease')})
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration):
        state=uncertainty(run)
        state.update(called=False,nativeStarted=False,historicalTransformEvidenceVerified=False)
        return state

def main(argv=None):
    args = None
    try:
        parser = Parser(description=__doc__)
        sub = parser.add_subparsers(dest='command',required=True,parser_class=Parser)
        for command in ('inspect','prepare','set'):
            item = sub.add_parser(command)
            item.add_argument('--baseline',type=Path,required=True)
            if command == 'inspect':
                item.add_argument('--entity-id',type=int,action='append',required=True)
            else:
                item.add_argument('--inspection',type=Path,required=True)
                item.add_argument('--request',type=Path,required=True)
                item.add_argument('--save',type=Path,required=True)
            transport = item.add_mutually_exclusive_group()
            transport.add_argument('--direct-elevated',action='store_true')
            transport.add_argument('--elevated-queue',type=Path)
        item = sub.add_parser('compile-check')
        item.add_argument('--large-scene',action='store_true')
        item.add_argument('--mode',choices=('inspect','set'),default='set')
        item.add_argument('--baseline-fixture',type=Path,help='Compile expired read-only captured evidence without querying the live process; inspect mode only')
        item.add_argument('--fixture-count',type=int,default=1,help='Synthetic compiler/startup fixture requests, 1 to 128; no game target')
        item.add_argument('--entity-id',type=int,action='append')
        item = sub.add_parser('physics-inspect')
        item.add_argument('--baseline',type=Path,required=True)
        item.add_argument('--entity-id',type=int,action='append',required=True)
        item.add_argument('--reference-entity-id',type=int,required=True)
        item.add_argument('--expected-transform-run',type=Path,help='Bind target poses to a successful prior transform card; the reference remains independently observed')
        transport = item.add_mutually_exclusive_group()
        transport.add_argument('--direct-elevated',action='store_true')
        transport.add_argument('--elevated-queue',type=Path)
        item = sub.add_parser('physics-compile-check')
        item.add_argument('--large-scene',action='store_true')
        item = sub.add_parser('dispatch')
        item.add_argument('--run',type=Path,required=True)
        transport = item.add_mutually_exclusive_group(required=True)
        transport.add_argument('--direct-elevated',action='store_true')
        transport.add_argument('--elevated-queue',type=Path)
        for command in ('decode','physics-decode','verify-save'):
            item = sub.add_parser(command)
            item.add_argument('--run',type=Path,required=True)
            if command == 'verify-save':
                item.add_argument('--save-run',type=Path,required=True)
        args = parser.parse_args(argv)
        if args.command in ('inspect','prepare','set','compile-check','physics-inspect','physics-compile-check'):
            if args.command.startswith('physics-'):
                from physics_build import prepare as prepare_physics
                result = prepare_physics(args,compile_only=args.command=='physics-compile-check')
            else:
                result = prepare(args,inspect=args.command=='inspect',compile_only=args.command=='compile-check')
            args.run = result['run']
            if getattr(args,'direct_elevated',False) or getattr(args,'elevated_queue',None):
                result = dispatch(result['run'],direct=args.direct_elevated,queue=args.elevated_queue)
        elif args.command == 'dispatch':
            result = dispatch(args.run,direct=args.direct_elevated,queue=args.elevated_queue)
        elif args.command in ('decode','physics-decode'):
            result = decode(args.run)
        else:
            result = verify(args.run,args.save_run)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0 if result.get('ok') is True else 2
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration,subprocess.SubprocessError) as exc:
        result = dict(ok=False,stage=getattr(args,'command','arguments'),error=str(exc),
                      **failure_state(getattr(args,'run',None),getattr(args,'command',None)))
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
