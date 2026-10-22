"""One bounded editor experiment with this Python process as the real parent."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from .locking import FileWriteLock
from .errors import BridgeError
from .osbackend import WindowsCimProcessBackend
from .targets import EDITOR_DIR, FROZEN_TARGETS

ROOT = Path(__file__).resolve().parent.parent
EXE = FROZEN_TARGETS['editor']['executablePath']
# Original editor uses this numeric language fallback; no human language label is inferred.
VERIFIED_LANGUAGE_ARGV: tuple[str, ...] | None = ('-language', '2')
EVIDENCE_ROOT = ROOT / '.runtime/verification/editor-host'
LOCK_PATH = ROOT / '.runtime/bridge/write.lock'


def fixed_argv():
    if VERIFIED_LANGUAGE_ARGV is None:
        raise ValueError('LANGUAGE_NOT_VERIFIED: editor-host launch remains disabled')
    return [EXE, '-sourceapp', 'genshin', '-sourcepid', str(os.getpid()), *VERIFIED_LANGUAGE_ARGV]


def validate_lease(seconds):
    if type(seconds) is not int or not 30 <= seconds <= 300:
        raise ValueError('leaseSeconds must be an integer from 30 to 300')


def ensure_no_editor(backend):
    ok, processes = backend.query()
    if not ok:
        raise ValueError('PROCESS_OBSERVATION_UNKNOWN: refusing duplicate experiment')
    for item in processes:
        if item.simulated:
            raise ValueError('SIMULATED_PROCESS_OBSERVATION: real host requires real observations')
        same_path = item.executable_path and os.path.normcase(item.executable_path) == os.path.normcase(EXE)
        unreadable_same_name = not item.executable_path and (item.name or '').casefold() == 'beyondeditor.exe'
        if same_path or unreadable_same_name:
            raise ValueError('EDITOR_ALREADY_RUNNING_OR_UNVERIFIED: refusing duplicate experiment')


def run_host(lease_seconds=120):
    validate_lease(lease_seconds)
    argv = fixed_argv()
    if not Path(EXE).is_file():
        raise ValueError('EDITOR_MISSING')
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FileWriteLock(LOCK_PATH, timeout_s=0) as lock:
        lock.acquire(fence=0)
        ensure_no_editor(WindowsCimProcessBackend())
        run_dir = EVIDENCE_ROOT / uuid.uuid4().hex
        run_dir.mkdir(parents=True, exist_ok=False)
        def emit(record):
            record['runDirectory'] = str(run_dir)
            with (run_dir / 'events.jsonl').open('a',encoding='utf8') as stream:
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')
            print(json.dumps(record,ensure_ascii=False),flush=True)
        with (run_dir/'editor-stdout.log').open('wb') as out, (run_dir/'editor-stderr.log').open('wb') as err:
            try:
                child = subprocess.Popen(argv,cwd=EDITOR_DIR,stdin=subprocess.DEVNULL,stdout=out,stderr=err,shell=False,close_fds=True)
            except OSError as exc:
                emit({'event':'launch-failed','hostPID':os.getpid(),'errorType':type(exc).__name__,'winerror':getattr(exc,'winerror',None),'elevationRequested':False})
                return 2
            emit({'event':'started','hostPID':os.getpid(),'editorPID':child.pid,'argv':argv,'leaseSeconds':lease_seconds,'source':'project-python-parent-not-genshin','readiness':'not-verified','elevationRequested':False})
            try:
                code = child.wait(timeout=lease_seconds)
                emit({'event':'editor-exited','hostPID':os.getpid(),'editorPID':child.pid,'exitCode':code,'readiness':'not-verified'})
            except subprocess.TimeoutExpired:
                emit({'event':'lease-ended','hostPID':os.getpid(),'editorPID':child.pid,'action':'host-exits-normally-no-kill','editorExitObserved':False,'expectedMechanism':'official-sourcepid-watcher-after-parent-exit','readiness':'not-verified'})
            except KeyboardInterrupt:
                emit({'event':'host-interrupted','hostPID':os.getpid(),'editorPID':child.pid,'action':'host-exits-no-kill','editorExitObserved':False})
                return 130
    return 0


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('command',choices=['run'])
    parser.add_argument('--lease-seconds',type=int,default=120)
    args=parser.parse_args(argv)
    try: validate_lease(args.lease_seconds)
    except ValueError as exc: parser.error(str(exc))
    return args


def main(argv=None):
    args=parse_args(argv)
    try: return run_host(args.lease_seconds)
    except (ValueError,OSError,BridgeError) as exc:
        print(json.dumps({'event':'refused','error':str(exc),'readiness':'not-verified'}),flush=True)
        return 2

if __name__=='__main__':
    raise SystemExit(main())



