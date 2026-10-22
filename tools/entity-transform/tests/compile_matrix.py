"""Offline v1/v2 x inspect/set compiler coverage, optionally with a real saved baseline."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
from contract import read,write,sha,require

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-fixture',type=Path)
    parser.add_argument('--entity-id',type=int,action='append')
    parser.add_argument('--startup-check',action='store_true',help='Actually run expired synthetic probes and heap-backed callback harnesses; never dispatch to game')
    parser.add_argument('--fixture-count',type=int,default=128)
    args=parser.parse_args()
    require(bool(args.baseline_fixture)==bool(args.entity_id),'FIXTURE_AND_ENTITY_IDS_REQUIRED_TOGETHER')
    require(1 <= args.fixture_count <= 128,'FIXTURE_COUNT_1_TO_128')
    out=ROOT/'.runtime/map-foundation-20261015/transform/compiler-matrix'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4))
    out.mkdir(parents=True)
    cases=[]
    for version in (1,2):
        for mode in ('inspect','set'):
            cases.append((f'v{version}-{mode}',version,mode,['--mode',mode,'--fixture-count',str(args.fixture_count)]+(['--large-scene'] if version==2 else [])))
    if args.baseline_fixture:
        extra=['--mode','inspect','--baseline-fixture',str(args.baseline_fixture)]
        for eid in args.entity_id:
            extra+=['--entity-id',str(eid)]
        cases.append(('captured-baseline-inspect',None,'inspect',extra))
    rows=[]
    for name,version,mode,extra in cases:
        command=[sys.executable,'-B','-I','-S',str(HERE/'cli.py'),'compile-check',*extra]
        observed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=180,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/(name+'.stdout.json')).write_text(observed.stdout,encoding='utf-8')
        (out/(name+'.stderr.txt')).write_text(observed.stderr,encoding='utf-8')
        error=None;result={};startup=None
        try:
            result=json.loads(observed.stdout)
            require(observed.returncode==0 and result.get('ok') is True,'COMPILE_DID_NOT_SUCCEED')
            prepared=read(Path(result['run'])/'prepared.json')
            require(result['mode']==prepared['mode']==mode and result['launchable'] is False and prepared['compileOnly'] is True,'COMPILER_CASE_MODE_OR_LAUNCHABILITY')
            require(prepared['deadlineTick']==1 and not (Path(result['run'])/'invoke-transform.ps1').exists(),'FIXTURE_MUST_HAVE_EXPIRED_DEADLINE_AND_NO_WRAPPER')
            require(result['called'] is False and result['nativeStarted'] is False,'FIXTURE_EXECUTED')
            if version is not None:
                require(prepared['nativeSnapshotVersion']==version,'COMPILER_CASE_ABI')
                require(len(prepared['requests'])==args.fixture_count,'COMPILER_CASE_REQUEST_COUNT')
                if args.startup_check:
                    sys.path.insert(0,str(Path(__file__).resolve().parent))
                    from startup_smoke import run_startup
                    startup=run_startup(Path(result['run']),out/(name+'-startup'))
                    require(startup['ok'],'SYNTHETIC_STARTUP_FAILED')
            else:
                require(prepared['baselineFixture']==str(args.baseline_fixture.resolve()) and prepared['fixtureProvenance']['stdout.jsonl']==sha(args.baseline_fixture/'stdout.jsonl'),'REAL_BASELINE_PROVENANCE')
        except (ValueError,KeyError,OSError,subprocess.TimeoutExpired) as exc:
            error=str(exc)
        rows.append(dict(name=name,ok=error is None,exitCode=observed.returncode,result=result,startup=startup,error=error))
    report=dict(ok=all(row['ok'] for row in rows),scope='offline-compiler-matrix',run=str(out),
                cases=rows,startupCheck=args.startup_check,fixtureCount=args.fixture_count,gameProcessAccessed=False,nativeDispatchAttempted=False,
                createdUtc=datetime.now(timezone.utc).isoformat())
    write(out/'result.json',report)
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['ok'] else 2

if __name__=='__main__':
    raise SystemExit(main())
