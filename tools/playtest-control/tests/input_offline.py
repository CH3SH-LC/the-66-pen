"""Run only after the unified gate opens; no target process or desktop APIs."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/input-offline'
def main():
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True);records=[]
    def command(name,argv,expected,cwd=ROOT):
        result=subprocess.run(list(map(str,argv)),cwd=cwd,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(result.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(result.stderr or '',encoding='utf-8')
        records.append(dict(name=name,command=list(map(str,argv)),exitCode=result.returncode));assert result.returncode==expected,(name,result.returncode);return result
    command('python',[sys.executable,'-B','-m','unittest','discover','-s',HERE/'tests','-p','test_*.py','-v'],0)
    for operation in ('input-state','move-pulse','attack-tap','interact-option'):
        args=[] if operation=='input-state' else ['--input-id','offline-case']
        if operation=='interact-option':args+=['--option-index','0','--label','打开商店']
        value=command(operation+'-compile',[sys.executable,'-B',HERE/'cli.py','compile-check','--operation',operation,*args],0);card=json.loads(value.stdout.strip());prepared=Path(card['run']);exe=prepared/'hook_receipt_probe.exe'
        value=command(operation+'-expired',[exe],1);assert json.loads(value.stdout)['stage']=='PROFILE_DEADLINE'
        value=command(operation+'-argc',[exe,'refuse-runtime-target'],1);assert json.loads(value.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS';assert not(prepared/'attempt.used').exists()
        value=command(operation+'-private-host',[prepared/'acceptance_fixture.exe'],0);fixture=json.loads(value.stdout);assert fixture['gameAccess'] is False and fixture['checks']==8
        value=command(operation+'-full-pipeline',[prepared/'input_pipeline_fixture.exe'],0,cwd=prepared);fixture=json.loads(value.stdout.strip().splitlines()[-1]);assert fixture['gameAccess'] is False and fixture['productionHookAndCallback'] is True and fixture['playerMotionVerified'] is False and fixture['checks']==5
        sys.path.insert(0,str(HERE));from input_contract import parse,OPERATIONS
        raw=(prepared/'input-pipeline.bin').read_bytes();decoded=parse(raw);assert decoded['operation']==OPERATIONS[operation] and decoded['released']==1 and decoded['control']['after']['trialReady']==1
        records[-1].update(binaryEvidence=str(prepared/'input-pipeline.bin'),binarySha256=hashlib.sha256(raw).hexdigest(),callbacks=decoded['callbacks'],points=decoded['points'])
    result=dict(ok=True,gameAccess=False,desktopAccess=False,commands=records,hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()})
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=True,evidence=str(run/'summary.json'))))
if __name__=='__main__':main()
