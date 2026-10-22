"""Unified v5 batch. Private host only; never dispatch, open game or use desktop."""
from pathlib import Path
import datetime,hashlib,json,re,subprocess,sys
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/vitals-offline'
def main():
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True);records=[]
    def command(name,argv,expected,cwd=ROOT):
        result=subprocess.run(list(map(str,argv)),cwd=cwd,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(result.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(result.stderr or '',encoding='utf-8')
        records.append(dict(name=name,command=list(map(str,argv)),exitCode=result.returncode));assert result.returncode==expected,(name,result.returncode);return result
    value=command('python',[sys.executable,'-B','-m','unittest','discover','-s',HERE/'tests','-p','test_*.py','-v'],0)
    matched=re.search(r'Ran (\d+) tests',value.stderr);assert matched;python_count=int(matched.group(1))
    value=command('vitals-compile',[sys.executable,'-B',HERE/'cli.py','compile-check','--operation','vitals-state'],0)
    built=json.loads(value.stdout);prepared=Path(built['run']);exe=prepared/'hook_receipt_probe.exe'
    sys.path.insert(0,str(ROOT/'tools/game-executor/tests'));from probe_startup_common import inspect_pe
    pe=[inspect_pe(prepared/name) for name in ('hook_receipt_probe.exe','hook_receipt.dll','acceptance_fixture.exe')]
    (run/'pe-stack-evidence.json').write_text(json.dumps(pe,indent=2)+'\n',encoding='utf-8');assert pe[0]['stackReserve']==1024*1024
    value=command('expired',[exe],1);assert json.loads(value.stdout)['stage']=='PROFILE_DEADLINE'
    value=command('argc',[exe,'refuse-runtime-target'],1);assert json.loads(value.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS';assert not(prepared/'attempt.used').exists()
    value=command('private-full-hook',[prepared/'acceptance_fixture.exe'],0,cwd=prepared)
    fixture=json.loads(value.stdout.strip().splitlines()[-1]);assert fixture['gameAccess'] is False and fixture['productionHookAndCallback'] is True and fixture['checks']==8 and fixture['callbackStackReserve']==65536 and fixture['gameplayVerified'] is False
    sys.path.insert(0,str(HERE));from vitals_contract import parse
    raw=(prepared/'vitals-pipeline.bin').read_bytes();decoded=parse(raw);assert decoded['status']==0 and decoded['count']==2 and decoded['first'][0]['currentHp']==100. and decoded['first'][1]['currentHp']==0. and decoded['first'][1]['alive']==0
    (run/'private-decoded.json').write_text(json.dumps(decoded,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    records[-1].update(binaryEvidence=str(prepared/'vitals-pipeline.bin'),binarySha256=hashlib.sha256(raw).hexdigest())
    result=dict(ok=True,gameAccess=False,desktopAccess=False,pythonTests=python_count,productionCompiles=1,productionPreTargetRejections=2,privateFullHookRuns=1,privateChecks=8,engineEndpointsAreStandins=True,gameplayVerified=False,prepared=str(prepared),commands=records,hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()})
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=True,evidence=str(run/'summary.json'))))
if __name__=='__main__':main()
