"""Terrain CLI; one final JSON object on stdout, no implicit live calls."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from terrain_model import decode_save, make_plan, verify_save, require, artifact_path

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

class JsonParser(argparse.ArgumentParser):
    def error(self,message):
        raise ValueError(message)

def main(argv=None):
    ap=JsonParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('inspect');p.add_argument('--save',required=True)
    p=sub.add_parser('plan');p.add_argument('--save',required=True);p.add_argument('--terrain-id',type=int,required=True);p.add_argument('--edits',required=True);p.add_argument('--output',required=True);p.add_argument('--catalog-run')
    p=sub.add_parser('prepare');p.add_argument('--baseline',required=True);p.add_argument('--plan');p.add_argument('--inspect-only',action='store_true');p.add_argument('--terrain-id',type=int);p.add_argument('--runtime-probe',action='store_true');p.add_argument('--cells');p.add_argument('--refresh-only',action='store_true');p.add_argument('--save')
    p.add_argument('--catalog-probe',action='store_true')
    p=sub.add_parser('compile-check');p.add_argument('--large-scene',action='store_true');p.add_argument('--inspect-only',action='store_true');p.add_argument('--runtime-probe',action='store_true');p.add_argument('--refresh-only',action='store_true')
    p.add_argument('--catalog-probe',action='store_true');p.add_argument('--catalog-guard',action='store_true')
    p.add_argument('--shapes-guard',action='store_true')
    p=sub.add_parser('surfaces');p.add_argument('--save');p.add_argument('--terrain-id',type=int);p.add_argument('--run')
    p=sub.add_parser('surface-edits');p.add_argument('--spec',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('catalog');p.add_argument('--run',required=True)
    p=sub.add_parser('calibrate');p.add_argument('--run',required=True);p.add_argument('--points');p.add_argument('--quantization',choices=('exact','nearest'),default='exact');p.add_argument('--output')
    p=sub.add_parser('execute');p.add_argument('--run',required=True);p.add_argument('--direct-elevated',action='store_true');p.add_argument('--elevated-queue')
    p=sub.add_parser('decode');p.add_argument('--run',required=True)
    p=sub.add_parser('batch-create');p.add_argument('--save',required=True);p.add_argument('--terrain-id',type=int,required=True);p.add_argument('--edits',required=True);p.add_argument('--chunk-size',type=int,default=4096)
    p.add_argument('--catalog-run');p.add_argument('--initial-from-inspect');p.add_argument('--allow-initial-from-inspect',action='store_true')
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
        if args.command.startswith('batch-'):
            import terrain_batch
            result=getattr(terrain_batch,args.command[6:].replace('-','_'))(args)
        elif args.command=='inspect':
            model=decode_save(Path(args.save).read_bytes())
            result={'ok':True,'sha256':model['sha256'],'terrains':[{'terrainId':t['terrainId'],'cells':len(t['cells']),
                'materials':sorted({r[2] for r in t['cells']}),'unknownCellFields':t['unknownCellFields']} for t in model['terrains']],
                'coordinateConvention':'native x = low16, z = high16','heightEncoding':'integer 0..9998; local column step2.5, grid5; world conversion requires native catalog calibration',
                'materialSemantics':'numeric IDs only; use catalog for installed native name-hash and loaded-style evidence'}
        elif args.command in ('surfaces','surface-edits'):
            import terrain_shapes_v3 as shapes
            if args.command=='surfaces':
                require(not(args.save and args.run),'SURFACES_SAVE_AND_RUN_EXCLUSIVE')
                require(args.run or bool(args.save)==(args.terrain_id is not None),'SURFACES_SAVE_AND_TERRAIN_ID_REQUIRED_TOGETHER')
                rows=None
                if args.save:
                    from terrain_model import select
                    rows=select(decode_save(Path(args.save).read_bytes()),args.terrain_id)['cells']
                if args.run:
                    import terrain_batch
                    original=terrain_batch.original(args.run)
                    require(args.terrain_id is None or args.terrain_id==original['built']['terrainId'],'SURFACES_TERRAIN_ID_MISMATCH')
                    rows=original['after']
                result=shapes.describe(rows)
                if args.run:result.update(terrainId=original['built']['terrainId'],rawReceiptSha256=original['proof']['rawReceiptSha256'],nativeCellsVerified=True)
                else:result['nativeCellsVerified']=False
            else:
                edits=shapes.generate(read_json(args.spec));output=artifact_path(args.output)
                require(output.suffix.lower()=='.json','SURFACE_OUTPUT_MUST_BE_JSON');output.parent.mkdir(parents=True,exist_ok=True)
                with output.open('x',encoding='utf-8') as stream:json.dump(edits,stream,ensure_ascii=False,indent=2);stream.write('\n')
                result=dict(ok=True,edits=str(output),count=len(edits),shapeSemantics=shapes.binding(),called=False)
        elif args.command in ('catalog','calibrate'):
            import terrain_catalog,terrain_calibration
            result=terrain_catalog.catalog(args.run) if args.command=='catalog' else terrain_calibration.calibrate(args.run,read_json(args.points) if args.points else None,args.quantization)
            if getattr(args,'output',None):
                output=artifact_path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
                with output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
                result={'ok':True,'output':str(output),'edits':len(result.get('edits',[])),'called':False}
        elif args.command=='plan':
            material_source=None
            if args.catalog_run:
                import terrain_catalog
                material_source=terrain_catalog.authority(args.catalog_run,args.terrain_id)
            source=Path(args.save).resolve();result_plan=make_plan(source.read_bytes(),args.terrain_id,read_json(args.edits),str(source),material_source)
            output=artifact_path(args.output);require(output.suffix.lower()=='.json','PLAN_OUTPUT_MUST_BE_JSON')
            output.parent.mkdir(parents=True,exist_ok=True)
            with output.open('x',encoding='utf-8') as f:json.dump(result_plan,f,ensure_ascii=False,indent=2);f.write('\n')
            result={'ok':True,'plan':str(output),'terrainId':args.terrain_id,'edits':len(result_plan['changes']),'sourceSha256':result_plan['sourceSha256']}
        elif args.command in ('prepare','execute','decode','compile-check'):
            import terrain_native
            result=terrain_native.decode(args.run) if args.command=='decode' else getattr(terrain_native,args.command.replace('-','_'))(args)
        else:
            import terrain_native
            if args.save_run:
                import terrain_save_verify
                result=terrain_save_verify.verify(args.run,args.save_run)
            else:
                run,built=terrain_native.checked_run(args.run);receipt=terrain_native.decode(run)
                require(receipt['ok'] and not built['inspectOnly'] and not built.get('refreshOnly'),'SUCCESSFUL_APPLY_RECEIPT_REQUIRED')
                result=verify_save((run/'before.gil').read_bytes(),Path(args.after).read_bytes(),read_json(run/'request.json'))
                result.update(scope='terrain-file-content-only-v1',nativeSaveVerified=False,persistentSaveVerified=False)
                output=run/('file-verification-'+result['afterSha256'][:16]+'.json');result['verification']=str(output)
                if output.exists():require(read_json(output)==result,'EXISTING_FILE_VERIFICATION_DIFFERS')
                else:terrain_native.write(output,result)
        result.setdefault('called',False);result.setdefault('outcomeUncertain',False);result.setdefault('noAutomaticReplay',True)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('ok') else 1
    except Exception as exc:
        possible=bool(getattr(args,'_dispatch_possible',False))
        if args.command in ('execute','batch-accept'):
            path=Path(args.run)
            possible=possible or any((path/name).exists() for name in ('launch.claim','attempt.used','stdout.jsonl','exit.json'))
        print(json.dumps({'ok':False,'error':str(exc),'called':None if possible else False,'outcomeUncertain':possible,
                          'cleanupVerified':False,'safeToRelease':not possible,'noAutomaticReplay':True},ensure_ascii=False));return 1

if __name__=='__main__':
    raise SystemExit(main())
