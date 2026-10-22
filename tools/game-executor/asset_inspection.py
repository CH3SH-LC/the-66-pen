"""Batch existing-entity asset measurements and exact native catalog PNGs.

prepare/prepare-batch build only. dispatch is explicit and single-use. plan/template-plan/decode/merge/icons
read disk evidence only; they do not connect to a game or editor.
"""
from __future__ import annotations
import argparse
import ctypes
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import zipfile
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parent))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='strict')
from asset_inspection_common import *
from asset_inspection_receipt import decode,manifest,cleanup_evidence
import build as b

class Parser(argparse.ArgumentParser):
    def error(self,message):raise ValueError('ARGUMENTS:'+message)

def uncertainty(run):
    if run is None:return dict(called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=False)
    path=Path(run);claimed=any((path/n).exists() for n in ('map-queue-claim.json','dispatch.claim','launch.claim','attempt.used'))
    try:
        clean=cleanup_evidence(path)
        return dict(called=claimed,nativeStarted=claimed,outcomeUncertain=not clean,cleanupVerified=clean,safeToRelease=clean,replayForbidden=claimed)
    except (OSError,ValueError,KeyError,TypeError,struct.error):
        return dict(called=claimed,nativeStarted=claimed,outcomeUncertain=claimed,cleanupVerified=not claimed,safeToRelease=not claimed,replayForbidden=claimed)

def dispatch(run,*,direct=False,queue=None):
    require(bool(direct)!=bool(queue),'SELECT_EXACTLY_ONE_DISPATCH_TRANSPORT')
    run,prepared,built=manifest(run);require(prepared['launchable'] and not prepared['compileOnly'],'NONLAUNCHABLE_CARD')
    if queue:
        spec=importlib.util.spec_from_file_location('_asset_inspection_elevated_request',ROOT/'tools/editor-bridge/elevated-request.py')
        client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
        return client.send_native_map('asset-inspection',str(run),timeout=300,queue_dir=Path(queue))
    require(ctypes.windll.shell32.IsUserAnAdmin()!=0,'DIRECT_ELEVATED_REQUIRES_ADMINISTRATOR')
    require(not any((run/n).exists() for n in ('dispatch.claim','launch.claim','attempt.used','exit.json')),'CARD_ALREADY_CONSUMED_DO_NOT_REPLAY')
    require(datetime.now(timezone.utc)<datetime.fromisoformat(prepared['expiresUtc']),'PREPARATION_EXPIRED')
    for source,digest in prepared['sourceHashes'].items():require(sha(source)==digest,'SOURCE_CHANGED_BEFORE_DISPATCH')
    b.p.verify_disk(b.p.load_profile());b.p.validate_session(prepared['session']);host=b.p.powershell_host()
    write(run/'dispatch.claim',dict(startedUtc=datetime.now(timezone.utc).isoformat(),wrapperSha256=built['wrapperSha256'],host=host))
    env=os.environ.copy();env['PSModulePath']=str(Path(host['path']).parent/'Modules')
    invoked=subprocess.run([host['path'],'-NoProfile','-NonInteractive','-File',str(run/'invoke-asset.ps1')],cwd=run,stdin=subprocess.DEVNULL,
        capture_output=True,text=True,env=env,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (run/'dispatch.stdout.txt').write_text(invoked.stdout or '',encoding='utf-8');(run/'dispatch.stderr.txt').write_text(invoked.stderr or '',encoding='utf-8')
    result=decode(run);write(run/'result.json',result);return result

def plan(baseline,entity_ids=None,template_ids=None,all_entities=False):
    require(sum((bool(entity_ids),bool(template_ids),bool(all_entities)))==1,'PLAN_SELECT_EXACTLY_ONE_ID_KIND')
    session,snapshot,_=b.baseline(baseline,require_fresh=False);by_id={x['id']:x for x in snapshot['entities']}
    if entity_ids:
        ids=[identifier(v) for v in entity_ids];require(len(ids)==len(set(ids)) and set(ids)<=by_id.keys(),'PLAN_UNKNOWN_OR_DUPLICATE_ENTITY_ID')
    elif template_ids:
        tids={identifier(v) for v in template_ids};ids=[x['id'] for x in snapshot['entities'] if x['configId'] in tids]
        require(tids<={by_id[v]['configId'] for v in ids},'PLAN_TEMPLATE_NOT_PRESENT')
    else:ids=list(by_id)
    require(ids,'PLAN_EMPTY')
    return dict(ok=True,kind='asset-inspection-plan-v1',baseline=str(Path(baseline).resolve()),session=session,levelId=snapshot['levelObservation']['levelId'],
        baselineEvidence={name:sha(Path(baseline)/name) for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json')},
        batches=[dict(entityIds=ids[i:i+MAX_ENTITIES],templateIds={str(v):by_id[v]['configId'] for v in ids[i:i+MAX_ENTITIES]}) for i in range(0,len(ids),MAX_ENTITIES)],
        entityCount=len(ids),templateCount=len({by_id[v]['configId'] for v in ids}),called=False,
        historicalPlanOnly=True,freshBaselineRequiredForPreparation=True,templateSelection='all observed entities with exact configId, never choose one by name or minimum id')

def merge(runs):
    reports=[decode(v) for v in runs];require(reports and all(x['ok'] and x['queryComplete'] for x in reports),'MERGE_REQUIRES_COMPLETE_RAW_RUNS')
    first=reports[0]
    require(all(x['session']==first['session'] and x['levelId']==first['levelId'] and x['imageSha256']==first['imageSha256'] for x in reports),'MERGE_SESSION_OR_LEVEL_MISMATCH')
    groups={};seen=set()
    for report in reports:
        for row in report['measurements']:
            require(row['entityId'] not in seen,'MERGE_DUPLICATE_ENTITY_OBSERVATION');seen.add(row['entityId'])
            groups.setdefault(str(row['templateId']),[]).append(dict(row,sourceRun=report['run'],rawReceiptSha256=report['rawReceiptSha256']))
    return dict(ok=True,kind='asset-inspection-batch-v1',schema='mw-asset-inspection',levelId=first['levelId'],session=first['session'],imageSha256=first['imageSha256'],
        entityCount=len(seen),templateCount=len(groups),templates=groups,called=False,appearanceVerified=False,
        cityTemplates=[template_summary(v) for v in groups.values()],
        measurementsArePerInstance=True,canonicalTemplateDimensionsChosen=False,
        evidence=[dict(run=x['run'],rawReceiptSha256=x['rawReceiptSha256'],observedFinishedUtc=x['observedFinishedUtc']) for x in reports])

def main(argv=None):
    args=None
    try:
        parser=Parser(description=__doc__);subs=parser.add_subparsers(dest='command',required=True,parser_class=Parser)
        item=subs.add_parser('prepare');item.add_argument('--baseline',type=Path,required=True);item.add_argument('--entity-id',type=int,action='append',required=True)
        item=subs.add_parser('prepare-batch');item.add_argument('--plan',type=Path,required=True);item.add_argument('--batch',type=int,required=True);item.add_argument('--baseline',type=Path,required=True)
        item=subs.add_parser('template-plan');item.add_argument('--selection',type=Path,required=True);item.add_argument('--icons',type=Path,required=True)
        item.add_argument('--out',type=Path,required=True);item.add_argument('--baseline',type=Path);item.add_argument('--include-alternatives',action='store_true')
        item=subs.add_parser('template-report');group=item.add_mutually_exclusive_group(required=True);group.add_argument('--plan',type=Path);group.add_argument('--sequence',type=Path)
        item.add_argument('--run',type=Path,action='append');item.add_argument('--out',type=Path)
        item=subs.add_parser('sequence-plan');item.add_argument('--plan',type=Path,required=True);item.add_argument('--anchor',nargs=3,type=float,required=True);item.add_argument('--out',type=Path,required=True)
        item=subs.add_parser('sequence-report');item.add_argument('--operation',type=Path,required=True);item.add_argument('--out',type=Path)
        for name in ('sequence-run','sequence-recover'):
            item=subs.add_parser(name);item.add_argument('--operation',type=Path,required=True);item.add_argument('--session',type=Path,required=True)
            item.add_argument('--elevated-queue',type=Path,required=True);item.add_argument('--bridge-run-id',required=True);item.add_argument('--out',type=Path)
            if name=='sequence-run':item.add_argument('--max-stages',type=int,default=32)
            else:item.add_argument('--stage',type=int,required=True)
        item=subs.add_parser('sample-plan');item.add_argument('--plan',type=Path,required=True);item.add_argument('--anchor',nargs=3,type=float,required=True);item.add_argument('--out',type=Path,required=True)
        item=subs.add_parser('sample-bind');item.add_argument('--samples',type=Path,required=True);item.add_argument('--sample',type=int,required=True);item.add_argument('--commit',type=Path,required=True);item.add_argument('--before-baseline',type=Path,required=True);item.add_argument('--out',type=Path,required=True)
        item=subs.add_parser('verify-sample-recovery');item.add_argument('--recovery',type=Path,required=True);item.add_argument('--baseline',type=Path,required=True);item.add_argument('--out',type=Path)
        item=subs.add_parser('compile-check');item.add_argument('--large-scene',action='store_true')
        item=subs.add_parser('dispatch');item.add_argument('--run',type=Path,required=True)
        group=item.add_mutually_exclusive_group(required=True);group.add_argument('--direct-elevated',action='store_true');group.add_argument('--elevated-queue',type=Path)
        item=subs.add_parser('decode');item.add_argument('--run',type=Path,required=True);item.add_argument('--out',type=Path)
        item=subs.add_parser('plan');item.add_argument('--baseline',type=Path,required=True);item.add_argument('--out',type=Path)
        group=item.add_mutually_exclusive_group(required=True);group.add_argument('--entity-id',type=int,action='append');group.add_argument('--template-id',type=int,action='append');group.add_argument('--all-entities',action='store_true')
        item=subs.add_parser('merge');item.add_argument('--run',type=Path,action='append',required=True);item.add_argument('--out',type=Path)
        item=subs.add_parser('icons');item.add_argument('--out',type=Path,required=True)
        group=item.add_mutually_exclusive_group(required=True);group.add_argument('--template-id',type=int,action='append');group.add_argument('--run',type=Path);group.add_argument('--role-catalog',type=Path)
        item.add_argument('--include-alternatives',action='store_true',help='Preview every explicit alternativeId in a role catalog; never selects one')
        args=parser.parse_args(argv)
        sequence_export=getattr(args,'out',None) and (args.command in ('sequence-run','sequence-recover','sequence-report') or args.command=='template-report' and args.sequence)
        if sequence_export:
            export=guarded_output(args.out);require(not export.exists(),'SEQUENCE_EXPORT_MUST_BE_NEW');export.parent.mkdir(parents=True,exist_ok=True)
        if args.command in ('prepare','compile-check'):
            from asset_inspection_build import prepare
            result=prepare(args,compile_only=args.command=='compile-check')
        elif args.command=='dispatch':result=dispatch(args.run,direct=args.direct_elevated,queue=args.elevated_queue)
        elif args.command=='template-plan':
            from asset_inspection_templates import make_plan
            result=make_plan(args.selection,args.icons,args.out,baseline=args.baseline,include_alternatives=args.include_alternatives)
        elif args.command=='prepare-batch':
            from asset_inspection_templates import prepare_batch
            result=prepare_batch(args.plan,args.batch,args.baseline)
        elif args.command=='template-report':
            if args.sequence:
                require(not args.run,'SEQUENCE_REPORT_READS_BOUND_RUNS_ONLY')
                from asset_inspection_sequence import report
                result=report(args.sequence)
            else:
                from asset_inspection_templates import template_report
                result=template_report(args.plan,args.run or [])
        elif args.command=='sequence-plan':
            from asset_inspection_sequence import initialize
            result=initialize(args.plan,args.anchor,args.out)
        elif args.command=='sequence-report':
            from asset_inspection_sequence import report
            result=report(args.operation)
        elif args.command in ('sequence-run','sequence-recover'):
            from asset_inspection_sequence import run
            result=run(args.operation,args.session,args.elevated_queue,args.bridge_run_id,
                max_stages=getattr(args,'max_stages',32),recover_stage=getattr(args,'stage',None))
        elif args.command=='sample-plan':
            from asset_inspection_samples import sample_plan
            result=sample_plan(args.plan,args.anchor,args.out)
        elif args.command=='sample-bind':
            from asset_inspection_samples import bind_sample
            result=bind_sample(args.samples,args.sample,args.commit,args.before_baseline)
        elif args.command=='verify-sample-recovery':
            from asset_inspection_samples import verify_recovery
            result=verify_recovery(args.recovery,args.baseline)
        elif args.command=='decode':result=decode(args.run)
        elif args.command=='plan':result=plan(args.baseline,args.entity_id,args.template_id,args.all_entities)
        elif args.command=='merge':result=merge(args.run)
        else:
            from asset_inspection_icons import extract,ids_from_role_catalog
            require(not args.include_alternatives or args.role_catalog,'ALTERNATIVES_REQUIRE_ROLE_CATALOG')
            selection=None
            if args.run:
                measured=decode(args.run);require(measured['ok'] and measured['queryComplete'],'ICONS_REQUIRE_COMPLETE_ENTITY_OBSERVATION')
                ids=list(dict.fromkeys(x['templateId'] for x in measured['measurements']))
            elif args.role_catalog:ids,selection=ids_from_role_catalog(args.role_catalog,args.include_alternatives)
            else:ids=args.template_id
            result=extract(ids,args.out)
            if selection:
                result['declaredRoleSelection']=selection
                emit(args.out/'role-selection.json',selection)
        if sequence_export:
            from asset_inspection_sequence import new_json,ref
            new_json(args.out,result);result['export']=ref(args.out)
        elif getattr(args,'out',None) and args.command not in ('icons','template-plan','sample-plan','sequence-plan'):result['export']=emit(args.out,result)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('ok') is True else 2
    except (OSError,ValueError,KeyError,TypeError,AttributeError,StopIteration,subprocess.SubprocessError,struct.error,zipfile.BadZipFile,zlib.error,RuntimeError,AssertionError) as exc:
        run=getattr(args,'run',None);state=uncertainty(run if not isinstance(run,list) else None)
        if getattr(args,'command',None) in ('decode','merge','icons','template-plan','template-report'):state.update(called=False,nativeStarted=False)
        if getattr(args,'command',None) in ('sequence-run','sequence-recover'):
            state.update(called=True,nativeStarted=True,outcomeUncertain=True,cleanupVerified=False,safeToRelease=False,replayForbidden=True,
                operation=str(args.operation),recoveryCommand='sequence-recover: revalidate persisted evidence; never replay a claimed action')
        print(json.dumps(dict(ok=False,stage=getattr(args,'command','arguments'),error=str(exc),**state),ensure_ascii=False,allow_nan=False));return 2

if __name__=='__main__':raise SystemExit(main())
