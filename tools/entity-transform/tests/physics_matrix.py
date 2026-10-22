"""Unified-gate v1/v2 compilation and six actual non-game startup checks."""
import json,secrets,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
from contract import read,write,sha,require
from startup_smoke import run_startup

def main():
    out=ROOT/'.runtime/map-foundation-20261015/transform/physics-matrix'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4));out.mkdir(parents=True)
    rows=[]
    for version in (1,2):
        command=[sys.executable,'-B','-I','-S',str(HERE/'cli.py'),'physics-compile-check']+(['--large-scene'] if version==2 else [])
        observed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/f'v{version}.stdout.json').write_text(observed.stdout,encoding='utf-8');(out/f'v{version}.stderr.txt').write_text(observed.stderr,encoding='utf-8')
        result={};startup=None;error=None
        try:
            result=json.loads(observed.stdout);require(observed.returncode==0 and result.get('ok') is True,'PHYSICS_COMPILE_FAILED')
            run=Path(result['run']);prepared=read(run/'prepared.json')
            require(prepared['action']==15 and prepared['receiptVersion']==19 and prepared['nativeSnapshotVersion']==version and len(prepared['requests'])==8,'PHYSICS_COMPILE_ABI')
            startup=run_startup(run,out/f'v{version}-startup');require(startup['ok'],'PHYSICS_STARTUP_FAILED')
        except (ValueError,OSError,KeyError,subprocess.SubprocessError) as exc:error=str(exc)
        rows.append(dict(version=version,ok=error is None,result=result,startup=startup,error=error))
    report=dict(ok=all(x['ok'] for x in rows),rows=rows,gameProcessAccessed=False,dispatchAttempted=False,createdUtc=datetime.now(timezone.utc).isoformat(),run=str(out))
    write(out/'result.json',report);print(json.dumps(report,ensure_ascii=False));return 0 if report['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
