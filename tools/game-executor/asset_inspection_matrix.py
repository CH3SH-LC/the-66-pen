"""Unified-gate offline ABI compilation and real non-game startup checks."""
from pathlib import Path
import json
import subprocess
import sys
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent))
from asset_inspection_common import *
from asset_inspection_build import prepare,b
sys.path.insert(0,str(HERE/'tests'))
from probe_startup_common import inspect_pe

def startup(run,out):
    prepared=read(run/'prepared.json')
    require(prepared['compileOnly'] and not prepared['launchable'] and prepared['syntheticStartupFixture'] and
            prepared['session']['pid']==prepared['session']['tid']==prepared['deadlineTick']==1,'SYNTHETIC_CARD_REQUIRED')
    claims=('attempt.used','dispatch.claim','launch.claim','map-queue-claim.json','invoke-asset.ps1')
    require(not any((run/x).exists() for x in claims),'FIXTURE_HAS_DISPATCH_PATH')
    for name,digest in prepared['artifacts'].items():require(sha(run/name)==digest,'FIXTURE_CHANGED')
    source=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text(encoding='utf-8');main=source[source.index('int wmain('):]
    require(main.index('NO_RUNTIME_TARGET_ARGUMENTS')<main.index('PROFILE_DEADLINE')<main.index('OpenProcess('),'REFUSALS_MUST_PRECEDE_PROCESS_ACCESS')
    require('    *receipt = {};' not in source and source.count('std::memset(receipt, 0, sizeof(*receipt));')==1,'NO_LARGE_RECEIPT_STACK_TEMPORARY')
    out.mkdir(parents=True);binaries={}
    for name in ('hook_receipt_probe.exe','hook_receipt.dll','callback_startup.exe'):
        stack=inspect_pe(run/name);limit=128*1024 if name=='hook_receipt_probe.exe' else 16*1024
        require(stack['maxStackBytes']<=limit,'FRAME_TOO_LARGE')
        if name.endswith('.exe'):require(stack['stackReserve']==1024*1024,'DEFAULT_EXE_STACK_REQUIRED')
        write(out/(name+'.unwind.json'),stack);binaries[name]=dict(sha256=sha(run/name),stack=stack)
    cases=[]
    for label,binary,argv,exit_code,stage in [('arguments','hook_receipt_probe.exe',['synthetic'],1,'NO_RUNTIME_TARGET_ARGUMENTS'),('expired','hook_receipt_probe.exe',[],1,'PROFILE_DEADLINE'),('callback','callback_startup.exe',[],0,None)]:
        p=subprocess.run([str(run/binary),*argv],cwd=run,capture_output=True,text=True,encoding='utf-8',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/(label+'.stdout.json')).write_text(p.stdout,encoding='utf-8');(out/(label+'.stderr.txt')).write_text(p.stderr,encoding='utf-8')
        raw=json.loads(p.stdout);require(p.returncode==exit_code and not p.stderr,'STARTUP_EXIT')
        if stage:require(raw.get('stage')==stage and raw.get('ok') is False,'STARTUP_REFUSAL')
        else:require(raw.get('ok') is True and raw.get('nativeCalls')==0 and raw.get('gameProcessAccessed') is False and raw.get('privateThreadStack')==65536 and raw.get('requestCount')==8,'CALLBACK_STARTUP_FAILED')
        require(not any((run/x).exists() for x in claims),'STARTUP_CREATED_CLAIM');cases.append(dict(name=label,ok=True,exitCode=p.returncode,raw=raw))
    result=dict(ok=True,binaries=binaries,cases=cases,gameProcessAccessed=False,dispatchAttempted=False);write(out/'result.json',result);return result

def main():
    out=b.ro.output_directory(ROOT/'.runtime/asset-inspection-20261017/validation');rows=[]
    for version in (1,2):
        try:
            built=prepare(SimpleNamespace(large_scene=version==2),compile_only=True)
            checked=startup(Path(built['run']),out/f'v{version}-startup')
            rows.append(dict(version=version,ok=True,build=built,startup=checked))
        except Exception as exc:
            rows.append(dict(version=version,ok=False,error=str(exc)));break
    report=dict(ok=len(rows)==2 and all(x['ok'] for x in rows),rows=rows,run=str(out),gameProcessAccessed=False,dispatchAttempted=False)
    write(out/'result.json',report);print(json.dumps(report,ensure_ascii=False));return 0 if report['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
