"""Complete v9 offline batch. No target process, desktop, broker or queue access."""
from pathlib import Path
import datetime,hashlib,json,re,subprocess,sys,traceback
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/directory-offline'
def main():
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True);records=[];pe=[];python_count=0;prepared=None
    def command(name,argv,expected,cwd=ROOT):
        print('running '+name,flush=True);result=subprocess.run(list(map(str,argv)),cwd=cwd,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(result.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(result.stderr or '',encoding='utf-8');records.append(dict(name=name,command=list(map(str,argv)),exitCode=result.returncode))
        assert result.returncode==expected,(name,result.returncode);return result
    try:
        value=command('python',[sys.executable,'-B','-m','unittest','discover','-s',HERE/'tests','-p','test_*.py','-v'],0);matched=re.search(r'Ran (\d+) tests',value.stderr);assert matched;python_count=int(matched.group(1))
        value=command('directory-compile',[sys.executable,'-B',HERE/'cli.py','compile-check','--operation','trial-entities'],0);built=json.loads(value.stdout);prepared=Path(built['run'])
        sys.path.insert(0,str(HERE));from receipt import manifest
        from directory_contract import parse,interpretation
        import test_contact as fixture_card
        _,card,_=manifest(prepared);assert card['kind']=='playtest-control-prepared-v9' and card['compileOnly'] and not card['launchable']
        sys.path.insert(0,str(ROOT/'tools/game-executor/tests'));from probe_startup_common import inspect_pe
        pe=[inspect_pe(prepared/name) for name in ('hook_receipt_probe.exe','hook_receipt.dll','acceptance_fixture.exe')];assert pe[0]['stackReserve']==1024*1024
        exe=prepared/'hook_receipt_probe.exe';value=command('expired',[exe],1);assert json.loads(value.stdout)['stage']=='PROFILE_DEADLINE'
        value=command('argc',[exe,'refuse-runtime-target'],1);assert json.loads(value.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS';assert not(prepared/'attempt.used').exists()
        value=command('private-full-hook',[prepared/'acceptance_fixture.exe'],0,cwd=prepared);fixture=json.loads(value.stdout.strip().splitlines()[-1]);assert fixture['gameAccess'] is False and fixture['productionHookAndCallback'] is True and fixture['checks']==13 and fixture['callbackStackReserve']==65536 and fixture['gameplayVerified'] is False
        raw=(prepared/'directory-pipeline.bin').read_bytes();decoded=parse(raw);assert decoded['status']==0 and decoded['stable']==1 and decoded['first']['status']==0 and decoded['first']['count']==2
        c=decoded['contact']['control'];binding=dict(c['after']);binding.update(initialToken=1,initialData=1,initialSettleData=0,exitSettleBefore=0)
        bound=fixture_card.card();bound['targetLevelId']=1;bound['binding'].update(binding);bound['binding']['global']=c['after']['global'];bound['binding']['editor']=c['after']['editor'];bound['binding']['task']=c['after']['task']
        result=interpretation(decoded,bound);assert [x['editorEntityGuid'] for x in result['entities']]==[None,1001,1002]
        assert all(x['targetLevelSpawnMembershipVerified'] for x in result['entities'][1:]) and result['interactionOptions'][0]['hostTrialMembershipVerified']
        assert result['collisionVerified'] is False
        (run/'private-decoded.json').write_text(json.dumps(decoded,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');records[-1].update(binaryEvidence=str(prepared/'directory-pipeline.bin'),binarySha256=hashlib.sha256(raw).hexdigest())
        for path,digest in card['sourceHashes'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
        result=dict(ok=True,gameAccess=False,desktopAccess=False,pythonTests=python_count,productionCompiles=1,productionPreTargetRejections=2,privateFullHookRuns=1,privateChecks=13,engineEndpointsAreStandins=True,gameplayVerified=False,actualPlayerContactVerified=False,prepared=str(prepared),commands=records)
    except BaseException:
        result=dict(ok=False,gameAccess=False,desktopAccess=False,pythonTests=python_count,prepared=str(prepared) if prepared else None,commands=records,error=traceback.format_exc());raise
    finally:
        (run/'pe-stack-evidence.json').write_text(json.dumps(pe,indent=2)+'\n',encoding='utf-8');result['hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()};(run/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=result['ok'],evidence=str(run/'summary.json'))),flush=True)
if __name__=='__main__':main()
