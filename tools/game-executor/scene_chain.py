"""Run one reviewed native batch with explicit session/level and no automatic retry.

The complete plan is bound to the coordinator review. A batch is limited to the
native callback limit (256); larger plans must be split into independently reviewed
runs so later writes cannot reuse a baseline from before previous side effects.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from build_scene_profile import MAX_BATCH,build_profile,resolve_level,write_json
from scene_cli import (SceneFailure,json_file,run_profile,queue_request,send_queued_scene,
                       read_plan_spec)


def main():
    # The parent reads the JSON receipt as UTF-8 even on a legacy Windows console.
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('placements',type=Path)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--session',type=Path)
    parser.add_argument('--level-id',type=int)
    parser.add_argument('--review',type=Path)
    parser.add_argument('--elevated-queue',type=Path,metavar='QUEUE_DIR')
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();built=None
    summary={'startedUtc':datetime.now(timezone.utc).isoformat(),'steps':[],'retryAttempted':False}
    try:
        if args.elevated_queue is not None and args.prepare_only:
            raise ValueError('--prepare-only cannot be combined with --elevated-queue')
        spec=read_plan_spec(args.placements) if args.elevated_queue is not None else json_file(args.placements)
        placements=spec['placements'];level=resolve_level(args.level_id)
        if not isinstance(placements,list) or not 1<=len(placements)<=MAX_BATCH:
            raise ValueError('One reviewed chain requires 1..256 placements; split larger plans into independently reviewed runs')
        # 2026-10-09: no template whitelist. The shape is checked here; whether the id exists
        # in the catalog is the native layer's call.
        for index,item in enumerate(placements):
            value=item.get('template_id')
            if isinstance(value,bool) or not isinstance(value,int):
                raise ValueError('Placement template_id is not an integer at '+str(index))
        summary.update(step=spec.get('step',args.placements.stem),level=level,placements=placements)
        if args.elevated_queue is not None:
            request_args=argparse.Namespace(action='create-batch',session=args.session,level_id=level,
                                            review=args.review,plan=args.placements)
            queued=queue_request(request_args)
            summary['placements']=queued['placements']
            result=send_queued_scene(queued,'create-batch',args.elevated_queue)
        else:
            built=build_profile('create-batch',placements=placements,session_path=args.session,level_id=level,review_path=args.review)
            if args.prepare_only:
                print(json.dumps(dict(built,preparedOnly=True),ensure_ascii=False));return 0
            result=run_profile(built)
        summary['steps'].append(result);summary['ok']=result['ok']
        summary.update(outcomeUncertain=result.get('outcomeUncertain',False),run=result.get('run'),
                       requestId=result.get('requestId'),helper=result.get('helper'))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        summary.update(ok=False,error=str(exc),outcomeUncertain=getattr(exc,'uncertain',False),run=getattr(exc,'run',None) or (built['run'] if built else None))
    summary['finishedUtc']=datetime.now(timezone.utc).isoformat()
    target=args.out or (Path(built['run']) if built else None)
    if target:
        target.mkdir(parents=True,exist_ok=True);write_json(target/'chain-result.json',summary)
    console={key:value for key,value in summary.items() if key!='placements'}
    console['placementCount']=len(summary.get('placements',[]))
    print(json.dumps(console,ensure_ascii=False));return 0 if summary['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
