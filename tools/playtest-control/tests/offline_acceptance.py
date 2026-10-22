"""Compile once, launch production probe only before target query, private host.

All outputs stay under the project. Run only after the unified testing gate.
No game process enumeration/query, hooks, queue or live session is used.
"""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/playtest-control-20261016/offline-acceptance'
def main():
    run=OUT/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');run.mkdir(parents=True)
    records=[]
    def command(name,argv):
        p=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=240)
        (run/(name+'.stdout')).write_text(p.stdout or '',encoding='utf-8');(run/(name+'.stderr')).write_text(p.stderr or '',encoding='utf-8')
        records.append(dict(name=name,command=list(map(str,argv)),exitCode=p.returncode));return p
    p=command('python',[sys.executable,'-B','-m','unittest','discover','-s',str(HERE/'tests'),'-p','test_*.py','-v']);assert p.returncode==0
    p=command('compile',[sys.executable,'-B',str(HERE/'cli.py'),'compile-check']);assert p.returncode==0
    card=json.loads(p.stdout.strip());prepared=Path(card['run']);exe=prepared/'hook_receipt_probe.exe'
    p=command('probe-expired',[str(exe)]);assert p.returncode==1 and json.loads(p.stdout)['stage']=='PROFILE_DEADLINE'
    p=command('probe-argc',[str(exe),'refuse-runtime-target']);assert p.returncode==1 and json.loads(p.stdout)['stage']=='NO_RUNTIME_TARGET_ARGUMENTS'
    assert not (prepared/'attempt.used').exists()
    p=command('private-callback',[str(prepared/'callback_fixture.exe')]);assert p.returncode==0 and json.loads(p.stdout)['gameAccess'] is False
    manifest=dict(ok=True,gameAccess=False,prepared=str(prepared),commands=records,hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in run.iterdir() if p.is_file()})
    (run/'summary.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print(json.dumps(dict(ok=True,evidence=str(run/'summary.json'))))
if __name__=='__main__':main()
