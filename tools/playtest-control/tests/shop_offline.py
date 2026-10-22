"""Full v7 batch: production compile/probe/hook, private native UI endpoints only."""
from pathlib import Path
import datetime,hashlib,json,re,subprocess,sys,traceback
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/shop-offline'

def main():
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True);records=[];cards=[];pe=[];python_count=0;checks=0
    def command(name,argv,expected,cwd=ROOT):
        print('running '+name,flush=True);result=subprocess.run(list(map(str,argv)),cwd=cwd,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(result.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(result.stderr or '',encoding='utf-8');records.append(dict(name=name,command=list(map(str,argv)),exitCode=result.returncode))
        assert result.returncode==expected,(name,result.returncode);return result
    try:
        value=command('python',[sys.executable,'-B','-m','unittest','discover','-s',HERE/'tests','-p','test_*.py','-v'],0);matched=re.search(r'Ran (\d+) tests',value.stderr);assert matched;python_count=int(matched.group(1))
        sys.path.insert(0,str(HERE));from receipt import manifest
        from shop_contract import parse
        sys.path.insert(0,str(ROOT/'tools/game-executor/tests'));from probe_startup_common import inspect_pe
        for action in (None,'goods','bag-item','quantity-one','buy','sell-open','sell','back'):
            name=action or 'state';argv=[sys.executable,'-B',HERE/'cli.py','compile-check','--operation','shop-ui' if action else 'shop-state']
            if action:
                argv+=['--ui-action',action,'--ui-id','offline-'+name,'--label','10' if action=='goods' else '出售' if action=='sell' else '苹果']
                if action!='back':argv+=['--config-id','1107296258']
                if action in ('goods','bag-item'):argv+=['--ui-row','0' if action=='goods' else '1']
            value=command(name+'-compile',argv,0);built=json.loads(value.stdout);prepared=Path(built['run']);_,card,_=manifest(prepared)
            assert card['kind']=='playtest-control-prepared-v7' and card['compileOnly'] and not card['launchable'];cards.append(str(prepared))
            for file in ('hook_receipt_probe.exe','hook_receipt.dll','acceptance_fixture.exe'):pe.append(inspect_pe(prepared/file))
            assert pe[-3]['stackReserve']==1024*1024
            exe=prepared/'hook_receipt_probe.exe';value=command(name+'-expired',[exe],1);assert json.loads(value.stdout)['stage']=='PROFILE_DEADLINE'
            value=command(name+'-argc',[exe,'refuse-runtime-target'],1);assert json.loads(value.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS';assert not(prepared/'attempt.used').exists()
            value=command(name+'-private-full-hook',[prepared/'acceptance_fixture.exe'],0,cwd=prepared);result=json.loads(value.stdout.strip().splitlines()[-1]);expected=7 if action is None else 14 if action=='back' else 12 if action in ('buy','sell') else 11
            assert result['gameAccess'] is False and result['productionHookAndCallback'] is True and result['checks']==expected and result['callbackStackReserve']==65536 and result['gameplayVerified'] is False;checks+=expected
            raw=(prepared/'shop-pipeline.bin').read_bytes();decoded=parse(raw);assert decoded['status']==0 and decoded['uiStable']==1 and decoded['inventory']['totalCaptured']==2 and decoded['inventory']['slotCaptured']==3
            assert decoded['before']['ownerId']==88 and decoded['before']['shopId']==9
            if action in (None,'goods','bag-item'):
                assert decoded['before']['rows'][0]['text']=='10' and decoded['before']['rows'][1]['text']=='苹果' and decoded['before']['rows'][1]['configId']==1107296258
            else:assert decoded['before']['text']==('出售' if action=='sell' else '苹果')
            assert decoded['actionReturned']==int(bool(action));assert decoded['inventory']['totalsFirst'][0]['quantity']==25 and sum(x['quantity'] for x in decoded['inventory']['slotsFirst'])==7
            (run/(name+'-decoded.json')).write_text(json.dumps(decoded,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');records[-1].update(binaryEvidence=str(prepared/'shop-pipeline.bin'),binarySha256=hashlib.sha256(raw).hexdigest())
            for i in range(1 if action=='quantity-one' else 3 if action=='back' else 0):
                path=prepared/('shop-variant-'+str(i)+'.bin');extra=path.read_bytes();variant=parse(extra);assert variant['status']==0 and variant['actionReturned']==1 and variant['afterReadable']==1
                if action=='quantity-one':assert variant['before']['kind']==4 and variant['before']['quantity']==3 and variant['after']['quantity']==1
                else:assert variant['before']['kind']==(1,3,4)[i] and variant['after']['kind']==(5 if i==0 else 1)
                records[-1].setdefault('variants',[]).append(dict(path=str(path),sha256=hashlib.sha256(extra).hexdigest(),beforeKind=variant['before']['kind'],afterKind=variant['after']['kind']))
        result=dict(ok=True,gameAccess=False,desktopAccess=False,pythonTests=python_count,productionCompiles=len(cards),productionPreTargetRejections=len(cards)*2,privateFullHookRuns=len(cards),privateChecks=checks,engineEndpointsAreStandins=True,gameplayVerified=False,prepared=cards,commands=records)
    except BaseException:
        result=dict(ok=False,gameAccess=False,desktopAccess=False,pythonTests=python_count,prepared=cards,commands=records,error=traceback.format_exc());raise
    finally:
        (run/'pe-stack-evidence.json').write_text(json.dumps(pe,indent=2)+'\n',encoding='utf-8');result['hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()};(run/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=result['ok'],evidence=str(run/'summary.json'))),flush=True)
if __name__=='__main__':main()
