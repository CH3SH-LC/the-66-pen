"""Actual production probe entry and private-hook-host tests; no game access.

Eight normal production-profile binaries run only their argc/deadline guards,
before OpenProcess. Four additional v2 probes use the existing self-test host
guard and a DLL linked only to explicit private snapshot/action stubs. They
exercise mapping initialization, hook dispatch, receipt emission and unhook.
"""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timezone

from probe_startup_common import inspect_pe

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NATIVE = HERE.parent / 'native'


def require(value, reason):
    if not value: raise ValueError(reason)


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def header(path, values):
    # Candidate constants only; no original failed card is read or executed.
    text = ''.join('#define %s %s\n' % (key, 'L' + json.dumps(value) if isinstance(value, str)
                                        else str(value) + 'ULL') for key, value in values.items())
    Path(path).write_text(text, encoding='utf-8')


def config(folder, large, action, *, private=False):
    nonce = secrets.randbits(62) | 1
    token = secrets.token_hex(16)
    return dict(HR_READ_CONTEXT=1, GS_LARGE_SCENE=large, HR_ACTION=action,
        GS_BOOTSTRAP_READONLY=int(action == 0), GS_REVIEWED_ACTION_PROFILE=int(action != 0),
        HR_ACTION_PROFILE_REVIEWED=1, HR_SELFTEST_ONLY=int(private),
        HR_TARGET_PID=1, HR_TARGET_TID=1, HR_TARGET_CREATION=1, HR_TARGET_THREAD_CREATION=1,
        HR_TARGET_IMAGE=str(folder / 'hook_receipt_host.exe'), HR_NONCE=nonce, HR_DEADLINE=0,
        HR_MESSAGE_NAME='Miliastra.Private.Scale.' + token, HR_MESSAGE_ID=0xc001,
        HR_MAPPING='Local\\Miliastra.Private.Scale.' + token,
        HR_DLL_PATH=str(folder / 'hook_receipt.dll'), HR_ATTEMPT_FILE=str(folder / 'attempt.used'))


def compile_commands(vcvars, folder, commands, env):
    script = folder / ('build-' + secrets.token_hex(4) + '.cmd')
    lines = ['@echo off', 'call "' + str(vcvars) + '" >nul', 'if errorlevel 1 exit /b 1']
    for command in commands:
        lines += [command, 'if errorlevel 1 exit /b 1']
    lines.append('exit /b 0')
    script.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    result = subprocess.run(['cmd.exe', '/d', '/c', str(script)], cwd=folder, env=env,
                            capture_output=True, timeout=120)
    script.with_suffix('.log').write_bytes(result.stdout + result.stderr)
    require(result.returncode == 0, 'COMPILE_FAILED:' + str(script.with_suffix('.log')))


def cl(source, output, include, *, dll=False, extra=()):
    return ('cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD ' + ('/LD ' if dll else '') +
            '/FI"' + str(include) + '" "' + str(source) + '" ' +
            ' '.join('"' + str(path) + '"' for path in extra) +
            ' /Fo:"' + str(output.with_suffix('.obj')) + '" /Fe:"' + str(output) +
            '" /link User32.lib Advapi32.lib')


def stack_check(path):
    info = inspect_pe(path)
    require(info['stackReserve'] == 0x100000, 'STACK_RESERVE_WAS_ENLARGED')
    require(info['maxStackBytes'] < 128 * 1024, 'PROBE_STACK_FRAME_TOO_LARGE')
    save(path.with_suffix('.stack.json'), info)
    return info['maxStackBytes']


def startup_guards(output, vcvars, env):
    cases, commands = [], []
    for large in (0, 1):
        for action in (0, 1, 2, 3):
            folder = output / ('production-v%d-action%d' % (large + 1, action))
            folder.mkdir()
            include, executable = folder / 'target_config.h', folder / 'hook_receipt_probe.exe'
            values = config(folder, large, action)
            header(include, values)
            commands.append(cl(NATIVE / 'hook_receipt_probe.cpp', executable, include))
            cases.append((folder, executable, large, action))
    compile_commands(vcvars, output, commands, env)
    results = []
    for folder, executable, large, action in cases:
        frame = stack_check(executable)
        outcomes = []
        for extra, expected in ((['private-startup-guard'], 'NO_RUNTIME_TARGET_ARGUMENTS'), ([], 'PROFILE_DEADLINE')):
            completed = subprocess.run([str(executable), *extra], cwd=folder, env=env,
                stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
            stem = 'argc' if extra else 'expired'
            (folder / (stem + '.stdout.json')).write_bytes(completed.stdout)
            (folder / (stem + '.stderr.txt')).write_bytes(completed.stderr)
            record = json.loads(completed.stdout)
            require(completed.returncode == 1 and record.get('stage') == expected and
                    record.get('selfTestOnly') is False, 'PRODUCTION_STARTUP_GUARD_FAILED:' + str(executable))
            require(not (folder / 'attempt.used').exists(), 'STARTUP_GUARD_REACHED_ATTEMPT')
            outcomes.append(dict(stage=expected, exitCode=completed.returncode))
        results.append(dict(largeScene=bool(large), action=action, maxStackBytes=frame, outcomes=outcomes))
    return results


def host_line(process, timeout=10):
    result = queue.Queue()
    def read():
        result.put(process.stdout.readline())
    threading.Thread(target=read, daemon=True).start()
    return result.get(timeout=timeout)


def private_host(output, vcvars, env, action):
    folder = output / ('private-v2-action%d' % action)
    folder.mkdir()
    include = folder / 'target_config.h'
    host, probe = folder / 'hook_receipt_host.exe', folder / 'hook_receipt_probe.exe'
    values = config(folder, 1, action, private=True)
    header(include, values)
    compile_commands(vcvars, folder, [cl(HERE / 'hook_receipt_host.cpp', host, include)], env)
    process = subprocess.Popen([str(host)], cwd=folder, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    ready = None
    try:
        line = host_line(process)
        ready = json.loads(line)
        require(ready.get('kind') == 'SELFTEST_HOST_READY' and ready['pid'] == process.pid,
                'PRIVATE_HOST_IDENTITY')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetTickCount64.restype = ctypes.c_ulonglong
        kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenThread.restype = wintypes.HANDLE
        kernel.GetThreadTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        thread = kernel.OpenThread(0x0040, False, ready['tid'])
        require(bool(thread), 'PRIVATE_THREAD_QUERY')
        times = [wintypes.FILETIME() for _ in range(4)]
        try:
            require(kernel.GetThreadTimes(thread, *(ctypes.byref(value) for value in times)), 'PRIVATE_THREAD_TIMES')
        finally:
            kernel.CloseHandle(thread)
        thread_ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        values.update(HR_TARGET_PID=ready['pid'], HR_TARGET_TID=ready['tid'],
                      HR_TARGET_CREATION=ready['creationTicks'], HR_MESSAGE_ID=ready['messageId'],
                      HR_TARGET_THREAD_CREATION=thread_ticks, HR_DEADLINE=kernel.GetTickCount64() + 120000)
        header(include, values)
        # Only fixture stubs implement the gameplay symbols. The production hook
        # and probe sources are compiled verbatim; no game object can be accessed.
        stub = folder / 'scene_probe_host_stubs.obj'
        compile_commands(vcvars, folder, [
            'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /c /FI"' + str(include) +
            '" "' + str(HERE / 'scene_probe_host_stubs.cpp') + '" /Fo:"' + str(stub) + '"',
            cl(NATIVE / 'hook_receipt.cpp', folder / 'hook_receipt.dll', include, dll=True,
               extra=(stub,)),
            cl(NATIVE / 'hook_receipt_probe.cpp', probe, include)], env)
        frame = stack_check(probe)
        completed = subprocess.run([str(probe)], cwd=folder, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
        (folder / 'stdout.jsonl').write_bytes(completed.stdout)
        (folder / 'stderr.txt').write_bytes(completed.stderr)
        record = json.loads(completed.stdout)
        require(completed.returncode == 0 and record.get('ok') is True and record.get('selfTestOnly') is True,
                'PRIVATE_PROBE_FAILED:' + str(folder))
        require(record.get('pid') == ready['pid'] and record.get('tid') == ready['tid'] and
                record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and
                record.get('unhooked') is True and record.get('hostPostUnhookPings') == 1,
                'PRIVATE_HOOK_NOT_DRAINED')
        require(record.get('receiptNonce') == str(values['HR_NONCE']) and
                record.get('receiptDeadline') == str(values['HR_DEADLINE']) and
                record.get('receiptProtocol') == (3 if action else 2), 'PRIVATE_CARD_IDENTITY')
        require(record.get('snapshotBytes') == 262584 and len(bytes.fromhex(record['snapshotHex'])) == 262584,
                'PRIVATE_V2_SNAPSHOT_ABI')
        if action:
            require(record['action']['kind'] == action and record['action']['called'] == 1 and
                    len(bytes.fromhex(record['afterSnapshotHex'])) == 262584, 'PRIVATE_ACTION_ABI')
        require((folder / 'attempt.used').is_file(), 'PRIVATE_MAPPING_INITIALIZATION_NOT_REACHED')
        return dict(action=action, maxStackBytes=frame, callbackCount=1, hostPostUnhookPings=1,
                    receiptProtocol=record['receiptProtocol'], realGameplayExecuted=False)
    finally:
        # This handle belongs solely to the private process started above. Never
        # enumerate processes or attempt to stop any game/editor/user session.
        if process.poll() is None and ready:
            ctypes.WinDLL('user32', use_last_error=True).PostThreadMessageW(ready['tid'], 0x0012, 0, 0)
        try:
            tail, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            tail, errors = process.communicate(timeout=5)
        (folder / 'host.stdout.jsonl').write_bytes((json.dumps(ready).encode() + b'\n' if ready else b'') + tail)
        (folder / 'host.stderr.txt').write_bytes(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / ('.runtime/map-foundation-20261015/scale/probe-startup-' +
              datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f'))).resolve()
    require(output.is_relative_to(ROOT / '.runtime'), 'OUTPUT_MUST_BE_PROJECT_RUNTIME')
    output.mkdir(parents=True, exist_ok=False)
    temp = output / 'temp'
    temp.mkdir()
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp))
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
    vcvars = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
    sources = {str(path): sha(path) for path in (NATIVE / 'hook_receipt_probe.cpp', NATIVE / 'hook_receipt.cpp',
               NATIVE / 'hook_receipt_protocol.h', HERE / 'scene_probe_host_stubs.cpp', HERE / 'hook_receipt_host.cpp')}
    result = dict(ok=False, scope='production-entry-and-private-hook-host-no-game', sources=sources)
    try:
        result['productionStartup'] = startup_guards(output, vcvars, env)
        result['privateHosts'] = [private_host(output, vcvars, env, action) for action in (0, 1, 2, 3)]
        require(sources == {path: sha(path) for path in sources}, 'SOURCES_CHANGED_DURING_STARTUP_SUITE')
        result.update(ok=True, productionBinaryCount=8, productionExecutions=16,
                      privateHostCount=4, privateProbeExecutions=4, gameAccessed=False)
    except Exception as error:
        result['error'] = repr(error)
    save(output / 'result.json', result)
    print(json.dumps(dict(ok=result['ok'], result=str(output / 'result.json'), error=result.get('error'))))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
