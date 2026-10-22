"""Run expired synthetic probes and the local production-callback harness only."""
from pathlib import Path
import json
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT/'tools/game-executor/tests'))
from contract import read,write,sha,require

CLAIMS = ('attempt.used','launch.claim','dispatch.claim','map-queue-claim.json','invoke-transform.ps1')

def run_startup(run, out):
    run,out = Path(run).resolve(),Path(out).resolve()
    prepared = read(run/'prepared.json')
    require(prepared['compileOnly'] is True and prepared['launchable'] is False and
            prepared.get('syntheticStartupFixture') is True and not prepared.get('baselineFixture'),
            'ONLY_SYNTHETIC_NONLAUNCHABLE_FIXTURES')
    require(prepared['deadlineTick'] == 1 and prepared['session']['pid'] == prepared['session']['tid'] == 1 and
            Path(prepared['session']['image']).name == 'compile-only.invalid','SYNTHETIC_TARGET_CHANGED')
    for name,digest in prepared['artifacts'].items():
        require(sha(run/name) == digest,'FIXTURE_ARTIFACT_CHANGED:'+name)
    require(not any((run/name).exists() for name in CLAIMS),'FIXTURE_HAS_EXECUTION_CLAIM')
    source = (run/'candidate-source/native/hook_receipt_probe.cpp').read_text(encoding='utf-8')
    main = source[source.index('int wmain('):]
    require(main.index('NO_RUNTIME_TARGET_ARGUMENTS') < main.index('PROFILE_DEADLINE') < main.index('OpenProcess('),
            'EARLY_REFUSALS_MUST_PRECEDE_PROCESS_ACCESS')
    require('    *receipt = {};' not in source and
            source.count('std::memset(receipt, 0, sizeof(*receipt));') == 1,'PROBE_STACK_INITIALIZATION')
    out.mkdir(parents=True)
    from probe_startup_common import inspect_pe
    binaries={}
    for name in ('hook_receipt_probe.exe','hook_receipt.dll','callback_startup.exe'):
        evidence = inspect_pe(run/name)
        # Probe has a known 64 KiB image-path buffer. Callback production DLL
        # must retain much smaller native frames; never solve by inflating /STACK.
        limit = 128*1024 if name == 'hook_receipt_probe.exe' else 16*1024
        require(evidence['maxStackBytes'] <= limit,'BINARY_NATIVE_FRAME_TOO_LARGE:'+name)
        if name.endswith('.exe'):
            require(evidence['stackReserve'] == 1024*1024,'DEFAULT_EXECUTABLE_STACK_REQUIRED:'+name)
        stack_path=out/(name+'.unwind.json')
        write(stack_path,evidence)
        binaries[name] = dict(sha256=sha(run/name),stackEvidence=str(stack_path),stackEvidenceSha256=sha(stack_path),
            stack={key:value for key,value in evidence.items() if key != 'functions'},frameLimit=limit)
    rows=[]
    cases = (
        ('argument-refusal','hook_receipt_probe.exe',['startup-fixture'],1,'NO_RUNTIME_TARGET_ARGUMENTS',87),
        ('deadline-refusal','hook_receipt_probe.exe',[],1,'PROFILE_DEADLINE',1460),
        ('callback-entry','callback_startup.exe',[],0,None,None),
    )
    for name,binary,arguments,expected_exit,expected_error,win32 in cases:
        observed = subprocess.run([str(run/binary),*arguments],cwd=run,capture_output=True,
            text=True,encoding='utf-8',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/(name+'.stdout.json')).write_text(observed.stdout,encoding='utf-8')
        (out/(name+'.stderr.txt')).write_text(observed.stderr,encoding='utf-8')
        error=None;raw={}
        try:
            raw=json.loads(observed.stdout)
            require(observed.returncode == expected_exit and not observed.stderr,'STARTUP_EXIT_OR_STDERR')
            if expected_error:
                require(raw.get('ok') is False and raw.get('stage') == expected_error and raw.get('win32') == win32,
                        'STARTUP_REFUSAL_MISMATCH')
            else:
                expected_stack = 64*1024 if prepared.get('kind') == 'entity-physics-prepared-v1' else 128*1024
                require(raw.get('ok') is True and raw.get('nativeCalls') == 0 and raw.get('gameProcessAccessed') is False and
                        raw.get('requestCount') == len(prepared['requests']) and raw.get('privateThreadStack') == expected_stack,
                        'CALLBACK_LOCAL_STARTUP_FAILED')
            require(not any((run/name).exists() for name in CLAIMS),'STARTUP_CREATED_EXECUTION_CLAIM')
        except (ValueError,KeyError,OSError) as exc:
            error=str(exc)
        rows.append(dict(name=name,ok=error is None,exitCode=observed.returncode,
            unsignedExitCode=observed.returncode & 0xffffffff,raw=raw,error=error))
    report=dict(ok=all(row['ok'] for row in rows),scope='synthetic-probe-and-callback-startup',
        preparedRun=str(run),preparedSha256=sha(run/'prepared.json'),binaries=binaries,cases=rows,
        gameProcessAccessed=False,nativeDispatchAttempted=False)
    write(out/'result.json',report)
    return report
