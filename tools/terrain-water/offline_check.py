"""One complete offline batch: private fixtures and eight production C++ modes.

No session discovery, helper, game queue, desktop, or live callback. Native
executables have PID/TID/deadline=1 and are required to refuse before OpenProcess.
"""
import argparse,io,json,sys,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import water_native as native
import water_stack_check as stack

def main():
    output=native.ro.output_directory(native.OUT.parent/'offline-checks')
    result=dict(kind='terrain-water-offline-check-v1',gameProcessOpened=False,nativeCalled=False,privateReceiptsAreStubs=True,realGameAccepted=False,builds=[])
    log=io.StringIO();suite=unittest.defaultTestLoader.discover(str(HERE/'tests'))
    tested=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (output/'fixtures.log').write_text(log.getvalue(),encoding='utf-8')
    result.update(tests=tested.testsRun,fixtureFailures=len(tested.failures),fixtureErrors=len(tested.errors))
    if tested.wasSuccessful():
        for large in (False,True):
            for mode in ('inspect','catalog','write','runtime'):
                try:
                    built=native.compile_check(argparse.Namespace(large_scene=large,inspect_only=mode=='inspect',catalog_probe=mode=='catalog',catalog_guard=mode=='write',runtime_probe=mode=='runtime',refresh_only=False))
                    refused=stack.check(built['run']);result['builds'].append(dict(mode=mode,largeScene=large,build=built,refusal=refused,ok=True))
                except Exception as exc:result['builds'].append(dict(mode=mode,largeScene=large,ok=False,error=str(exc)))
    result['ok']=tested.wasSuccessful() and len(result['builds'])==8 and all(b['ok'] for b in result['builds'])
    result['sourceSha256']={str(p):native.profiles.sha256(p) for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.cpp','.h','.inc')}
    native.write(output/'result.json',result)
    print(json.dumps(dict(ok=result['ok'],tests=result['tests'],fixtureFailures=result['fixtureFailures'],fixtureErrors=result['fixtureErrors'],builds=len(result['builds']),passedBuilds=sum(b['ok'] for b in result['builds']),evidence=str(output/'result.json'),gameProcessOpened=False,realGameAccepted=False),ensure_ascii=False))
    return 0 if result['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
