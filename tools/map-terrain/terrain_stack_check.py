"""Run only expired compile cards and a local native refusal fixture, never a game target."""
import argparse,importlib.util,json,os,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import terrain_native as native
from terrain_model import artifact_path,require

def check(value):
    run=artifact_path(value);require(run.parent==native.OUT.parent/'candidates','COMPILE_CARD_ROOT_REQUIRED')
    built=native.ro.read_json(run/'build-result.json')
    require(built.get('kind')=='native-terrain-compile-only-v1' and built.get('ok') is True and
            built.get('compileOnly') is True and built.get('launchable') is False and built.get('deadlineTick')==1,
            'EXPIRED_COMPILE_CARD_REQUIRED')
    header=(run/'target_config.h').read_text(encoding='utf-8')
    for key in ('HR_TARGET_PID','HR_TARGET_TID','HR_DEADLINE'):
        require(re.findall(r'^#define '+key+r' (.+)$',header,re.M)==['1ULL'],'OFFLINE_IDENTITY_REQUIRED:'+key)
    source=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text(encoding='utf-8')
    require(source.index('return Fail("PROFILE_DEADLINE"')<source.index('OpenProcess('),'DEADLINE_MUST_PRECEDE_PROCESS_ACCESS')
    require('std::memset(receipt, 0, sizeof(*receipt));' in source and '*receipt = {};' not in source,'IN_PLACE_INITIALIZATION_REQUIRED')
    output=run/'offline-stack-check';output.mkdir(exist_ok=False)
    pins={str(p):native.profiles.sha256(p) for p in run.rglob('*') if p.is_file()}
    inspector=native.EX/'tests/probe_startup_common.py'
    pins[str(inspector)]=native.profiles.sha256(inspector)
    spec=importlib.util.spec_from_file_location('terrain_pe_stack_inspector',inspector)
    pe_api=importlib.util.module_from_spec(spec);spec.loader.exec_module(pe_api)
    stack={'probe':pe_api.inspect_pe(run/'hook_receipt_probe.exe'),
           'callbackDll':pe_api.inspect_pe(run/'hook_receipt.dll')}
    require(stack['probe']['maxStackBytes']<128*1024 and stack['callbackDll']['maxStackBytes']<16*1024,
            'UNEXPECTED_LARGE_NATIVE_STACK_FRAME')
    native.write(output/'pe-stack.json',stack)
    result=subprocess.run([str(run/'hook_receipt_probe.exe')],cwd=run,capture_output=True,text=True,timeout=20)
    (output/'probe.stdout').write_text(result.stdout,encoding='utf-8');(output/'probe.stderr').write_text(result.stderr,encoding='utf-8')
    raw=json.loads(result.stdout)
    require(result.returncode==1 and raw.get('stage')=='PROFILE_DEADLINE' and not (run/'attempt.used').exists(),
            'PROBE_DID_NOT_REFUSE_BEFORE_TARGET_ACCESS:'+str(result.returncode))
    # Compile the actual native callback objects into a separate local executable.
    # Its worker is fixed to the PID/TID=1 expired card, and cannot enter game code.
    fixture=run/'candidate-source/map-terrain/native_stack_smoke.cpp'
    fixture.write_bytes((HERE/'tests/native_stack_smoke.cpp').read_bytes())
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                                '-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';require(vc.is_file(),'MSVC_REQUIRED')
    command=output/'build-smoke.cmd'
    command.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'+
        'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"'+str(run/'target_config.h')+'" "'+str(fixture)+
        '" /Fo:"'+str(output/'smoke.obj')+'" /Fe:"'+str(output/'native_stack_smoke.exe')+'" /link "'+str(run/'native_terrain.obj')+
        '" "'+str(run/'game_context_snapshot.obj')+'"\nexit /b %ERRORLEVEL%\n',encoding='utf-8')
    compiled=subprocess.run(['cmd.exe','/d','/c',str(command)],cwd=output,capture_output=True,text=True,timeout=180)
    (output/'build.log').write_text(compiled.stdout+compiled.stderr,encoding='utf-8');require(compiled.returncode==0,'SMOKE_BUILD_FAILED')
    smoke=subprocess.run([str(output/'native_stack_smoke.exe')],cwd=output,capture_output=True,text=True,timeout=20)
    (output/'smoke.stdout').write_text(smoke.stdout,encoding='utf-8');(output/'smoke.stderr').write_text(smoke.stderr,encoding='utf-8')
    require(smoke.returncode==0,'NATIVE_STACK_SMOKE_FAILED:'+str(smoke.returncode));observed=json.loads(smoke.stdout)
    require(observed.get('ok') is True and observed.get('workerStackReserve')==65536 and
            observed.get('nativeCalled') is False and observed.get('gameProcessOpened') is False,'NATIVE_STACK_SMOKE_REJECTED')
    for path,sha in pins.items():require(native.profiles.sha256(Path(path))==sha,'CANDIDATE_CHANGED_DURING_STACK_CHECK')
    report={'ok':True,'run':str(run),'compileOnly':True,'launchable':False,'probeExitCode':result.returncode,
            'probeRefusal':raw,'nativeFixture':observed,'artifactSha256':pins,'peStack':stack,'gameProcessOpened':False,'nativeCalled':False,
            'receiptStackTemporaryAbsent':True,'fullLiveCallbackVerified':False}
    native.write(output/'result.json',report)
    return {'ok':True,'run':str(run),'evidence':str(output/'result.json'),'probeRefusal':raw['stage'],
            'workerStackReserve':65536,'gameProcessOpened':False,'nativeCalled':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',required=True);args=parser.parse_args()
    try:result=check(args.run);code=0
    except Exception as exc:result={'ok':False,'error':str(exc),'gameProcessOpened':False,'nativeCalled':False};code=1
    print(json.dumps(result,ensure_ascii=False));return code

if __name__=='__main__':raise SystemExit(main())
