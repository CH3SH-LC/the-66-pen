"""Native terrain water CLI. Import and offline commands never discover a process."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from water_model import ROOT,require,artifact_path,make_plan,decode_save,verify_save

def source_path(value):
    path=Path(value)
    return (path if path.is_absolute() else ROOT/path).resolve()

def read_json(path):return json.loads(source_path(path).read_text('utf-8-sig'))

class JsonParser(argparse.ArgumentParser):
    def error(self,message):raise ValueError(message)

def main(argv=None):
    ap=JsonParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('inspect');p.add_argument('--save',required=True)
    p=sub.add_parser('plan');p.add_argument('--save',required=True);p.add_argument('--terrain-id',type=int,required=True);p.add_argument('--edits',required=True);p.add_argument('--catalog-run',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('prepare');p.add_argument('--baseline',required=True);p.add_argument('--plan');p.add_argument('--terrain-id',type=int);p.add_argument('--inspect-only',action='store_true');p.add_argument('--catalog-probe',action='store_true');p.add_argument('--runtime-probe',action='store_true');p.add_argument('--cells')
    p=sub.add_parser('execute');p.add_argument('--run',required=True)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--direct-elevated',action='store_true');mode.add_argument('--elevated-queue')
    p=sub.add_parser('decode');p.add_argument('--run',required=True)
    p=sub.add_parser('catalog');p.add_argument('--run',required=True)
    p=sub.add_parser('locate');p.add_argument('--catalog-run',required=True);p.add_argument('--points',required=True);p.add_argument('--output')
    p=sub.add_parser('compile-check');p.add_argument('--large-scene',action='store_true');p.add_argument('--inspect-only',action='store_true');p.add_argument('--catalog-probe',action='store_true');p.add_argument('--catalog-guard',action='store_true');p.add_argument('--runtime-probe',action='store_true')
    p=sub.add_parser('batch-create');p.add_argument('--save',required=True);p.add_argument('--terrain-id',type=int,required=True);p.add_argument('--edits',required=True);p.add_argument('--catalog-run',required=True);p.add_argument('--chunk-size',type=int,default=4096)
    p=sub.add_parser('batch-prepare');p.add_argument('--batch',required=True);p.add_argument('--baseline',required=True);p.add_argument('--inspection',required=True)
    p=sub.add_parser('batch-accept');p.add_argument('--batch',required=True);p.add_argument('--run',required=True)
    p=sub.add_parser('batch-status');p.add_argument('--batch',required=True)
    p=sub.add_parser('batch-abandon');p.add_argument('--batch',required=True)
    p=sub.add_parser('batch-verify-save');p.add_argument('--batch',required=True);p.add_argument('--save-run',required=True)
    p=sub.add_parser('verify-save');p.add_argument('--run',required=True)
    proof=p.add_mutually_exclusive_group(required=True);proof.add_argument('--after');proof.add_argument('--save-run')
    args=argparse.Namespace(command='')
    try:
        args=ap.parse_args(argv)
        for name in ('run','save','baseline','plan','edits','cells','batch','inspection','catalog_run','save_run','after','points','elevated_queue'):
            if getattr(args,name,None):setattr(args,name,str(source_path(getattr(args,name))))
        if args.command.startswith('batch-'):
            import water_batch
            result=getattr(water_batch,args.command[6:].replace('-','_'))(args)
        elif args.command=='inspect':
            saved=decode_save(Path(args.save).read_bytes())
            result=dict(ok=True,sourceSha256=saved['sha256'],terrains=[dict(terrainId=t['terrainId'],cells=len(t['cells']),waterCells=sum(r[3]>0 for r in t['cells']),unknownCellFields=t['unknownCellFields']) for t in saved['terrains']],waterTypeField='field4 / extraA',called=False)
        elif args.command=='catalog':
            import water_catalog
            result=water_catalog.catalog(args.run)
        elif args.command=='locate':
            import water_catalog,water_geometry
            authority=water_catalog.authority(args.catalog_run)
            result=water_geometry.locate(authority,read_json(args.points))
            result['source']=authority
            if args.output:
                import water_native
                path=artifact_path(args.output);path.parent.mkdir(parents=True,exist_ok=True);water_native.write(path,result)
                result=dict(ok=True,output=str(path),points=len(result['points']),surfaceElevationVerified=False)
        elif args.command=='plan':
            import water_catalog,water_native
            source=Path(args.save);authority=water_catalog.authority(args.catalog_run,args.terrain_id)
            plan=make_plan(source.read_bytes(),args.terrain_id,read_json(args.edits),str(source),authority)
            output=artifact_path(args.output);require(output.suffix.lower()=='.json','PLAN_OUTPUT_MUST_BE_JSON')
            output.parent.mkdir(parents=True,exist_ok=True);water_native.write(output,plan)
            result=dict(ok=True,plan=str(output),terrainId=args.terrain_id,edits=len(plan['changes']),sourceSha256=plan['sourceSha256'])
        elif args.command in ('prepare','execute','decode','compile-check'):
            import water_native
            result=water_native.decode(args.run) if args.command=='decode' else getattr(water_native,args.command.replace('-','_'))(args)
        else:
            import water_native
            if args.save_run:
                import water_save_verify
                result=water_save_verify.verify(args.run,args.save_run)
            else:
                run,built=water_native.checked_run(args.run);receipt=water_native.decode(run)
                require(receipt['ok'] and not built['inspectOnly'],'SUCCESSFUL_WATER_APPLY_RECEIPT_REQUIRED')
                result=verify_save((run/'before.gil').read_bytes(),Path(args.after).read_bytes(),read_json(run/'request.json'))
                result.update(scope='water-file-content-only-v1',nativeSaveVerified=False,persistentSaveVerified=False)
                output=run/('file-verification-'+result['afterSha256'][:16]+'.json');result['verification']=str(output)
                if output.exists():require(read_json(output)==result,'EXISTING_FILE_VERIFICATION_DIFFERS')
                else:water_native.write(output,result)
        result.setdefault('called',False);result.setdefault('outcomeUncertain',False);result.setdefault('noAutomaticReplay',True)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('ok') else 1
    except Exception as exc:
        possible=bool(getattr(args,'_dispatch_possible',False))
        if args.command in ('execute','batch-accept'):
            path=source_path(args.run)
            possible=possible or any((path/name).exists() for name in ('launch.claim','attempt.used','stdout.jsonl','exit.json'))
        print(json.dumps(dict(ok=False,error=str(exc),called=None if possible else False,outcomeUncertain=possible,cleanupVerified=False,safeToRelease=not possible,noAutomaticReplay=True),ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
