"""Bounded backend-only trial coordination. No write action is ever replayed."""
import time
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from contract import read,write,require
from control_contract import next_operation
from control_build import ROOT,prepare
FLOW_ROOT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/operations'

def run(args):
    from cli import dispatch
    from receipt import decode
    name=args.operation_id
    require(name and len(name)<=80 and all(x.isascii() and (x.isalnum() or x in '-_') for x in name),'OPERATION_ID')
    require(60<=args.timeout_seconds<=1800 and 1<=args.max_cards<=40,'CONTROL_RUN_BOUNDS')
    folder=FLOW_ROOT/name;folder.mkdir(parents=True,exist_ok=False)
    write(folder/'started.json',dict(direction=args.direction,session=read(args.session),targetLevelId=args.target_level,previousRun=str(args.previous_run) if args.previous_run else None,timeoutSeconds=args.timeout_seconds,maxCards=args.max_cards,startedUtc=datetime.now(timezone.utc).isoformat(),automaticResumeSupported=False))
    prior=args.previous_run;attempted=[];records=[];deadline=time.monotonic()+args.timeout_seconds;complete=False
    if args.direction=='enter':require(prior is None,'ENTER_REQUIRES_NEW_OPERATION');operation='enter-request'
    else:
        require(prior is not None,'EXIT_REQUIRES_COMPLETED_ENTRY_RECEIPT')
        result=decode(prior);require(result.get('mode')=='play' and result.get('trialIdentityBound') is True,'EXIT_REQUIRES_BOUND_TRIAL')
        operation='exit-request'
    try:
        for index in range(args.max_cards):
            require(time.monotonic()<deadline,'CONTROL_ASYNC_DEADLINE')
            built=prepare(SimpleNamespace(operation=operation,session=args.session,target_level=args.target_level,previous_run=prior,page_start=0))
            card=Path(built['run'])
            # A journal is committed BEFORE dispatch. Crashes leave this exact
            # candidate pending; the coordinator cannot start an automatic replay.
            write(folder/(f'{index:02d}-planned.json'),dict(operation=operation,run=str(card)))
            result=dispatch(card,queue=args.elevated_queue)
            write(folder/(f'{index:02d}-result.json'),result);records.append(dict(operation=operation,run=str(card),ok=result.get('ok'),mode=result.get('mode')))
            require(result.get('ok') is True and result.get('safeToRelease') is True and not result.get('outcomeUncertain'),'CONTROL_CARD_FAILED_OR_UNCERTAIN')
            if operation!='trial-state':attempted.append(operation)
            prior=card
            operation=next_operation(args.direction,result,attempted)
            if operation=='complete':complete=True;break
            # Poll only with fresh immutable read-only cards. Never repeat the
            # action request while waiting for its asynchronous response.
            if operation=='trial-state':time.sleep(min(2,max(0,deadline-time.monotonic())))
        require(complete,'CONTROL_CARD_LIMIT_REACHED')
        summary=dict(ok=True,direction=args.direction,completed=True,lastRun=str(prior),records=records,playerContactVerified=False,naturalInteractionVerified=False,desktopAccess=False)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        summary=dict(ok=False,direction=args.direction,completed=False,error=str(exc),lastRun=str(prior) if prior else None,records=records,automaticReplayForbidden=True,manualEvidenceInspectionRequired=True,desktopAccess=False)
    write(folder/'result.json',summary);return dict(summary,evidence=str(folder/'result.json'))
