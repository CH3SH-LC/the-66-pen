"""Run only at root's unified test gate. No target access, no desktop APIs."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/offline'
def main():
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True);records=[]
    def command(name,argv,expected):
        value=subprocess.run(list(map(str,argv)),cwd=ROOT,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(value.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(value.stderr or '',encoding='utf-8')
        records.append(dict(name=name,command=list(map(str,argv)),exitCode=value.returncode));assert value.returncode==expected,(name,value.returncode)
        return value
    command('python',[sys.executable,'-B','-m','unittest','discover','-s',HERE/'tests','-p','test_*.py','-v'],0)
    for operation in ('runtime-state','render-frame'):
        value=command(operation+'-compile',[sys.executable,'-B',HERE/'cli.py','compile-check','--operation',operation],0);card=json.loads(value.stdout.strip());prepared=Path(card['run']);exe=prepared/'hook_receipt_probe.exe'
        value=command(operation+'-expired',[exe],1);assert json.loads(value.stdout)['stage']=='PROFILE_DEADLINE'
        value=command(operation+'-argc',[exe,'refuse-runtime-target'],1);assert json.loads(value.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS';assert not (prepared/'attempt.used').exists()
        value=command(operation+'-private-host',[prepared/'acceptance_fixture.exe'],0);fixture=json.loads(value.stdout);assert fixture['gameAccess'] is False and fixture['checks']==8
    result=dict(ok=True,gameAccess=False,desktopAccess=False,commands=records,hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()})
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=True,evidence=str(run/'summary.json'))))
if __name__=='__main__':main()
