"""Loopback receive-only by default; optional single synthetic Tag experiment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from types import SimpleNamespace
from .editor_host import ROOT, EXE
from .ipc_discovery import read_port
from .ipc_frames import decode_one
from .osbackend import WindowsCimProcessBackend

LIMIT=65536
DURATION=45
HOST_LEASE=60
SNAPSHOT_REUSE_SECONDS=0.05
EVIDENCE_ROOT=ROOT/'.runtime/verification/editor-probe'


class PhaseTimer:
    def __init__(self):
        self.origin=time.monotonic()
        self.origin_utc=datetime.now(timezone.utc).isoformat()
        self.events=[]

    @contextmanager
    def phase(self,name):
        event={'phase':name,'startSeconds':time.monotonic()-self.origin,'startUtc':datetime.now(timezone.utc).isoformat(),'status':'running'}
        self.events.append(event)
        try:
            yield
            event['status']='completed'
        except BaseException as exc:
            event.update(status='failed',errorType=type(exc).__name__)
            raise
        finally:
            event['endSeconds']=time.monotonic()-self.origin
            event['endUtc']=datetime.now(timezone.utc).isoformat()
            event['durationSeconds']=event['endSeconds']-event['startSeconds']

    def mark(self,name):
        with self.phase(name):pass


def control_metadata(inner):
    """Classify only the observed ID-zero, ten-byte envelope; never decode a body.

    The null-message writer writes four length bytes after clearing only two.
    A nonzero declaration is retained as an anomaly, not normalized as valid.
    """
    if len(inner)!=10 or inner[:4]!=bytes.fromhex('06560000') or inner[-2:]!=bytes.fromhex('0666'):
        return None
    declared=int.from_bytes(inner[4:8],'big')
    return {'transportHeaderHex':'0000000a','transportFrameBytes':10,
            'headerHex':inner[:8].hex(),'innerControlHex':inner.hex(),
            'messageID':0,'classification':'empty-control-envelope',
            'observedPayloadBytes':0,'declaredPayloadBytes':declared,
            'declaredLengthAnomaly':declared!=0,
            'businessDecoded':False,'controlMeaningVerified':False}


def preflight():
    ok,rows=WindowsCimProcessBackend().query()
    if not ok: raise ValueError('PROCESS_OBSERVATION_UNKNOWN')
    for p in rows:
        if p.simulated: raise ValueError('SIMULATED_OBSERVATION_REJECTED')
        if not p.name and not p.executable_path: raise ValueError('UNIDENTIFIED_PROCESS')
        if (p.name or '').casefold() in {'yuanshen.exe','genshinimpact.exe','beyondeditor.exe'}:
            raise ValueError('GAME_OR_EDITOR_ALREADY_RUNNING')
        if p.executable_path and os.path.normcase(p.executable_path)==os.path.normcase(EXE):
            raise ValueError('EDITOR_ALREADY_RUNNING')
    port,error=read_port()
    if error or type(port) is not int or not 1<=port<=65535:raise ValueError('REGISTRY_PORT_UNKNOWN')
    return port


# Only validated integer ports/PID are interpolated. Output omits command lines and environment.
PEER_SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$rows=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter 'LocalPort=%d AND RemotePort=%d' | Where-Object {$_.LocalAddress -eq '127.0.0.1' -and $_.RemoteAddress -eq '127.0.0.1' -and $_.State -eq 5})
if($rows.Count -ne 1){throw 'ambiguous peer'}
$nextId=[int]$rows[0].OwningProcess
$chain=@()
for($i=0;$i -lt 10;$i++){
 $p=Get-CimInstance Win32_Process -Filter "ProcessId=$nextId"
 if($null -eq $p){throw 'missing process'}
 $chain+=@{pid=[int]$p.ProcessId;parent=[int]$p.ParentProcessId;path=$p.ExecutablePath}
 if([int]$p.ProcessId -eq %d){break}
 $nextId=[int]$p.ParentProcessId
}
ConvertTo-Json -InputObject $chain -Depth 3 -Compress
'''


def verify_peer(peer_port,server_port,host):
    if host.poll() is not None:raise ValueError('HOST_NOT_ALIVE')
    if any(type(v) is not int or v<=0 for v in (peer_port,server_port,host.pid)):raise ValueError('INVALID_PEER_IDS')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',PEER_SCRIPT%(peer_port,server_port,host.pid)],capture_output=True,text=True,encoding='utf8',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('PEER_QUERY_FAILED')
    chain=json.loads(result.stdout)
    return validate_peer_chain(chain,host)


def validate_peer_chain(chain,host):
    if not isinstance(chain,list) or len(chain)<2 or len(chain)>10:raise ValueError('PEER_CHAIN_UNKNOWN')
    if any(not isinstance(row,dict) or type(row.get('pid')) is not int or type(row.get('parent')) is not int for row in chain):raise ValueError('MALFORMED_PEER_CHAIN')
    if chain[-1]['pid']!=host.pid or host.poll() is not None:raise ValueError('PEER_NOT_OWNED_BY_HOST')
    if os.path.normcase(chain[-1].get('path') or '')!=os.path.normcase(sys.executable):raise ValueError('HOST_PATH_UNKNOWN')
    for i,item in enumerate(chain[:-1]):
        if os.path.normcase(item.get('path') or '')!=os.path.normcase(EXE):raise ValueError('PEER_EDITOR_PATH_UNKNOWN')
        if item['parent']!=chain[i+1]['pid']:raise ValueError('PEER_CHAIN_BROKEN')
    return {'peerPID':chain[0]['pid'],'hostPID':host.pid,'editorChainPIDs':[x['pid'] for x in chain[:-1]],'verified':True}


# One PowerShell invocation, one full process snapshot, one TCP observation.
# They are sequential observations, not an atomic OS transaction.
PRESEND_SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$processes=@(Get-CimInstance Win32_Process | ForEach-Object {@{pid=[int]$_.ProcessId;parent=[int]$_.ParentProcessId;path=$_.ExecutablePath;name=$_.Name}})
$tcp=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter 'LocalPort=%d AND RemotePort=%d' | Where-Object {$_.LocalAddress -eq '127.0.0.1' -and $_.RemoteAddress -eq '127.0.0.1' -and $_.State -eq 5} | ForEach-Object {[int]$_.OwningProcess})
ConvertTo-Json -InputObject @{processes=$processes;owners=$tcp} -Depth 4 -Compress
'''


def verify_presend(peer_port,server_port,host,accepted_peer=None):
    from .tag_sync import require_owned_editors
    if host.poll() is not None:raise ValueError('HOST_NOT_ALIVE')
    if any(type(v) is not int or v<=0 for v in (peer_port,server_port,host.pid)):
        raise ValueError('INVALID_PEER_IDS')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',PRESEND_SCRIPT%(peer_port,server_port)],capture_output=True,text=True,encoding='utf8',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('PEER_QUERY_FAILED')
    data=json.loads(result.stdout)
    if not isinstance(data,dict):raise ValueError('PRE_SEND_PROCESS_OBSERVATION_UNKNOWN')
    rows=data.get('processes');owners=data.get('owners')
    if not isinstance(rows,list) or not rows:raise ValueError('PRE_SEND_PROCESS_OBSERVATION_UNKNOWN')
    if not isinstance(owners,list) or len(owners)!=1 or type(owners[0]) is not int:
        raise ValueError('PEER_CHAIN_UNKNOWN')
    by_id={}
    for row in rows:
        if (not isinstance(row,dict) or type(row.get('pid')) is not int or row['pid']<0
            or type(row.get('parent')) is not int or row['parent']<0
            or not isinstance(row.get('name'),(str,type(None)))
            or not isinstance(row.get('path'),(str,type(None))) or row['pid'] in by_id):
            raise ValueError('PRE_SEND_PROCESS_IDENTITY_UNKNOWN')
        by_id[row['pid']]=row
    chain=[];next_id=owners[0]
    for _ in range(10):
        if next_id not in by_id or any(x['pid']==next_id for x in chain):raise ValueError('PEER_CHAIN_UNKNOWN')
        row=by_id[next_id];chain.append(row)
        if next_id==host.pid:break
        next_id=row['parent']
    peer=validate_peer_chain(chain,host)
    if accepted_peer is not None and peer!=accepted_peer:raise ValueError('PRE_SEND_EDITOR_CHAIN_CHANGED')
    processes=[SimpleNamespace(pid=r['pid'],name=r['name'],executable_path=r['path'],simulated=False) for r in rows]
    require_owned_editors(True,processes,peer,EXE)
    if host.poll() is not None:raise ValueError('HOST_NOT_ALIVE')
    return peer


def presend_snapshot(snapshot,conn,peer_port,server_port,host):
    """Reuse only this connection's just-completed full guard observation."""
    if host.poll() is not None:raise ValueError('HOST_NOT_ALIVE')
    age=time.monotonic()-snapshot['completed']
    if snapshot['conn'] is conn and 0<=age<=SNAPSHOT_REUSE_SECONDS:
        return {'mode':'snapshot-reused','snapshotCompletionAgeSeconds':age,
                'maximumReuseAgeSeconds':SNAPSHOT_REUSE_SECONDS}
    verify_presend(peer_port,server_port,host,snapshot['peer'])
    return {'mode':'snapshot-refreshed','previousSnapshotCompletionAgeSeconds':age,
            'maximumReuseAgeSeconds':SNAPSHOT_REUSE_SECONDS}


def receive_metadata(conn,deadline,on_1001=None,timing=None):
    buf=b'';total=0;frames=[];reason='deadline';raw_hash=hashlib.sha256();read_error=None
    handshake_action_done=False
    while total<LIMIT:
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        conn.settimeout(remaining)
        try: chunk=conn.recv(min(4096,LIMIT-total))
        except socket.timeout:break
        except OSError as exc:
            reason='peer-reset' if isinstance(exc,ConnectionResetError) else 'read-error'
            read_error=type(exc).__name__
            break
        if not chunk: reason='peer-closed';break
        total+=len(chunk);buf+=chunk;raw_hash.update(chunk)
        while buf:
            # Static send chain: big-endian uint32 counts inner frame including tail.
            if len(buf)<4:break
            transport_length=int.from_bytes(buf[:4],'big')
            try:
                if not 10<=transport_length<=LIMIT-4:
                    raise ValueError(f'transport length {transport_length} outside 10..{LIMIT-4}')
                if len(buf)<4+transport_length:break
                control=control_metadata(buf[4:4+transport_length])
                if control is not None:
                    frames.append(control)
                    buf=buf[4+transport_length:]
                    continue
                decoded=decode_one(buf[4:4+transport_length],max_payload=LIMIT-14)
                if decoded is None or decoded[1]!=transport_length:
                    raise ValueError('transport length does not match complete inner frame')
            except ValueError as exc:
                reason='invalid-or-oversized-frame'
                # Only header-derived errors may expose their numeric values.
                detail=str(exc)
                if not detail.startswith(('bad head magic ', 'declared payload length ', 'transport length ')):
                    detail='frame validation failed (non-header details omitted)'
                return {'bytesReceived':total,'frames':frames,'stopReason':reason,'unparsedBytes':len(buf),'headerHex':buf[:8].hex(),'receivedRawSha256':raw_hash.hexdigest(),'decodeError':detail}
            if decoded is None:break
            frame,used=decoded
            frames.append({'transportHeaderHex':buf[:4].hex(),'transportFrameBytes':transport_length,'headerHex':buf[4:12].hex(),'messageID':frame.message_id,'payloadBytes':len(frame.payload),'payloadSha256':hashlib.sha256(frame.payload).hexdigest()})
            buf=buf[4+used:]
            if frame.message_id==1001 and not handshake_action_done:
                handshake_action_done=True
                if timing is not None:timing.mark('1001')
                if on_1001 is not None and not on_1001():
                    return {'bytesReceived':total,'frames':frames,'stopReason':'synthetic-tag-send-refused-or-failed','unparsedBytes':len(buf)}
    if total==LIMIT:reason='byte-limit'
    result={'bytesReceived':total,'frames':frames,'stopReason':reason,'unparsedBytes':len(buf)}
    if read_error is not None:
        result.update(errorType=read_error,receivedRawSha256=raw_hash.hexdigest())
    return result


def run_probe(sync_synthetic_tag=False):
    timing=PhaseTimer()
    run_dir=EVIDENCE_ROOT/uuid.uuid4().hex;run_dir.mkdir(parents=True,exist_ok=False)
    report={'source':'receive-only-project-probe-not-game','sentBytes':0,'payloadStored':False,'readiness':'not-verified','timings':timing.events,'timingClock':'monotonic-seconds-since-probe-start','startedUtc':timing.origin_utc}
    if sync_synthetic_tag:
        report.update(source='synthetic-tag-project-probe-not-game',tagSync={'status':'not-sent-awaiting-1001','effectState':'not-sent','modelReadbackVerified':False})
    host=None
    try:
        with timing.phase('preflight'):
            port=preflight()
            report['port']=port
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            with timing.phase('bind'):
                listener.bind(('127.0.0.1',port))
            # Recheck after binding, before creating the host. Refuse races with existing editor/game.
            with timing.phase('preflight-after-bind'):
                if preflight()!=port:raise ValueError('REGISTRY_PORT_CHANGED')
            listener.listen(1)
            with (run_dir/'host-stdout.log').open('wb') as out,(run_dir/'host-stderr.log').open('wb') as err:
                with timing.phase('host'):
                    host=subprocess.Popen([sys.executable,'-m','bridge.editor_host','run','--lease-seconds',str(HOST_LEASE)],cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=out,stderr=err,shell=False,close_fds=True)
                report['hostPID']=host.pid
                deadline=time.monotonic()+DURATION
                listener.settimeout(DURATION)
                try:
                    with timing.phase('accept'):
                        conn,address=listener.accept()
                    listener.close()  # Exactly one connection; stop listening before peer verification.
                    with conn:
                        if address[0]!='127.0.0.1':raise ValueError('NON_LOOPBACK_PEER')
                        with timing.phase('peer'):
                            report['peer']=verify_presend(address[1],port,host)
                            snapshot={'peer':report['peer'],'conn':conn,'completed':time.monotonic()}
                            report['peerObservation']='full-process-snapshot-and-tcp-owner'
                        def send_tag_once():
                            from .tag_sync import encode_tag
                            try:
                                with timing.phase('presend'):
                                    report['presendObservation']=presend_snapshot(snapshot,conn,address[1],port,host)
                                    if time.monotonic()>=deadline:raise ValueError('SEND_DEADLINE_EXPIRED')
                                # Locally allocated experiment ID; never copied from any session.
                                tag_id=0xe0000000 | (uuid.uuid4().int & 0x0fffffff)
                                wire,metadata=encode_tag(tag_id)
                                report['tagSync']={**metadata,'status':'sending','effectState':'unknown'}
                                report['sentBytes']=None  # sendall failure may still have sent a prefix.
                                with timing.phase('send'):
                                    conn.settimeout(max(0.001,deadline-time.monotonic()))
                                    conn.sendall(wire)
                                report['sentBytes']=len(wire)
                                report['tagSync'].update(status='socket-write-completed',effectState='model-unverified')
                                # Bounded live handoff for explicit read-only diagnostics.
                                # File failure cannot reverse a completed socket write.
                                state={'hostPID':host.pid,'peer':report['peer'],'expectedTagID':tag_id,
                                       'name':metadata['name'],'sentBytes':len(wire),
                                       'utc':datetime.now(timezone.utc).isoformat(),'status':'socket-write-completed'}
                                temporary=run_dir/'send-state.json.tmp'
                                try:
                                    with temporary.open('x',encoding='utf8') as stream:
                                        json.dump(state,stream,indent=2)
                                        stream.flush();os.fsync(stream.fileno())
                                    os.replace(temporary,run_dir/'send-state.json')
                                except OSError as exc:
                                    report['tagSync']['sendStateWriteErrorType']=type(exc).__name__
                                return True
                            except (ValueError,OSError,subprocess.SubprocessError,json.JSONDecodeError) as exc:
                                report['tagSync'].update(status='refused-or-failed',errorType=type(exc).__name__)
                                known={'PRE_SEND_PROCESS_OBSERVATION_UNKNOWN','PRE_SEND_PROCESS_IDENTITY_UNKNOWN','PRE_SEND_GAME_PRESENT','PRE_SEND_UNOWNED_EDITOR','PRE_SEND_EDITOR_CHAIN_CHANGED','SEND_DEADLINE_EXPIRED','HOST_NOT_ALIVE','INVALID_PEER_IDS','PEER_QUERY_FAILED','PEER_CHAIN_UNKNOWN','MALFORMED_PEER_CHAIN','PEER_NOT_OWNED_BY_HOST','HOST_PATH_UNKNOWN','PEER_EDITOR_PATH_UNKNOWN','PEER_CHAIN_BROKEN','TAG_ID_UINT32_REQUIRED'}
                                if isinstance(exc,ValueError) and str(exc) in known:
                                    report['tagSync']['reason']=str(exc)
                                return False
                        report['capture']=receive_metadata(conn,deadline,send_tag_once if sync_synthetic_tag else None,timing)
                except socket.timeout:report['capture']={'stopReason':'no-connection-before-deadline'}
                except (ValueError,OSError,subprocess.SubprocessError,json.JSONDecodeError) as exc:
                    report['capture']={'stopReason':'refused-or-failed','errorType':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else 'observation failed'}
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        report['error']={'type':type(exc).__name__,'reason':str(exc) if isinstance(exc,ValueError) else 'bind or local operation failed'}
    finally:
        timing.mark('result')
        if host is not None:
            try:
                with timing.phase('host-wait'):
                    report['hostExitCode']=host.wait(timeout=90)
            except subprocess.TimeoutExpired:report['hostExitObserved']=False
        report['hostKilled']=False
        (run_dir/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps({'report':str(run_dir/'report.json'),**report}),flush=True)
    if sync_synthetic_tag and report['tagSync']['status']!='socket-write-completed':return 2
    return 0 if 'capture' in report and report['capture'].get('stopReason') not in {'refused-or-failed','synthetic-tag-send-refused-or-failed'} else 2


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);parser.add_argument('command',choices=['run'])
    parser.add_argument('--sync-synthetic-tag',action='store_true',help='Explicit fresh-editor experiment: send one synthetic Tag after verified 1001; no model-readback claim')
    args=parser.parse_args(argv)
    try:return run_probe(sync_synthetic_tag=args.sync_synthetic_tag)
    except (ValueError,OSError) as exc:
        print(json.dumps({'status':'refused','reason':str(exc),'payloadStored':False}),flush=True);return 2

if __name__=='__main__':raise SystemExit(main())


