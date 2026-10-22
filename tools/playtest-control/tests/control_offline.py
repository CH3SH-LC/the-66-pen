"""Unified-stage only: complete module, nine probes and private host fixtures."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/control-offline'

def main():
    assert sys.argv[1:] in ([],['--control-only'])
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True);records=[]
    def command(name,argv,expected):
        result=subprocess.run(list(map(str,argv)),cwd=ROOT,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(result.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(result.stderr or '',encoding='utf-8')
        records.append(dict(name=name,command=list(map(str,argv)),exitCode=result.returncode));assert result.returncode==expected,(name,result.returncode);return result
    command('python',[sys.executable,'-B','-m','unittest','discover','-s',HERE/'tests','-p','test_*.py','-v'],0)
    operations=('trial-state','enter-request','enter-start','exit-request','exit-return','trial-frame')
    if not sys.argv[1:]:operations=('observe','runtime-state','render-frame')+operations
    for operation in operations:
        value=command(operation+'-compile',[sys.executable,'-B',HERE/'cli.py','compile-check','--operation',operation],0);card=json.loads(value.stdout.strip());prepared=Path(card['run']);exe=prepared/'hook_receipt_probe.exe'
        value=command(operation+'-expired',[exe],1);assert json.loads(value.stdout)['stage']=='PROFILE_DEADLINE'
        value=command(operation+'-argc',[exe,'refuse-runtime-target'],1);assert json.loads(value.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS';assert not (prepared/'attempt.used').exists()
        fixture_name='callback_fixture.exe' if operation=='observe' else 'acceptance_fixture.exe'
        expected_checks=8 if operation in ('runtime-state','render-frame') else 7
        value=command(operation+'-private-host',[prepared/fixture_name],0);fixture=json.loads(value.stdout);assert fixture['gameAccess'] is False and fixture['checks']==expected_checks
    result=dict(ok=True,gameAccess=False,desktopAccess=False,commands=records,hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()})
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=True,evidence=str(run/'summary.json'))))
if __name__=='__main__':main()
