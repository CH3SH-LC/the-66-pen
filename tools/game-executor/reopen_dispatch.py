"""Execute exactly one helper-owned reopen attempt; retain asynchronous business ownership."""
from pathlib import Path
import json,os,re,struct,subprocess,time
from datetime import datetime,timezone
import native_profiles as profiles
import build_reopen_profile as builder
import native_write_review as review_api
import build_readonly_profile as readonly
import native_level_catalog as catalog_api
import native_lifecycle_type as lifecycle_api
import native_scheduler_coroutines as scheduler_api
import native_reopen_guards as guards_api
from native_reopen_result import dispatch_result

ACTION_BYTES=104

def decode_action(record,prepared):
    raw=record.get('reopenActionHex')
    profiles.require(type(raw) is str and len(raw)==ACTION_BYTES*2 and re.fullmatch('[0-9a-fA-F]+',raw),'REOPEN_ACTION_HEX')
    z=struct.unpack('<4I4Q4I9II',bytes.fromhex(raw))
    names=('size','version','action','status','invocation','entry','levelManager','record','levelId','preflightAccepted','routeBefore','routeAfter',
           'callSize','callVersion','callCode','nativeCallAttempted','nativeCallReturned','exceptionCode','businessPending','reopenVerified','persistenceVerified','reserved')
    a=dict(zip(names,z));nonce=prepared['nativeDefinitions']['HR_NONCE'];session=prepared['session']
    profiles.require(a['size']==104 and a['version']==1 and a['action']==4 and 1<=a['status']<=8 and a['invocation']==nonce and a['levelId']==1073741840 and a['reserved']==0,'REOPEN_ACTION_ABI')
    profiles.require(type(record.get('reopenActionStatus')) is int and type(record.get('reopenActionBytes')) is int and record.get('reopenActionStatus')==a['status'] and record.get('reopenActionBytes')==104 and record.get('scope')=='REVIEWED_REOPEN_ACTION','REOPEN_ACTION_RECORD')
    profiles.require(type(record.get('pid')) is int and type(record.get('tid')) is int and record.get('pid')==session['pid'] and record.get('tid')==session['tid'],'REOPEN_ACTION_IDENTITY')
    for k in ('preflightAccepted','routeBefore','routeAfter','nativeCallAttempted','nativeCallReturned','businessPending','reopenVerified','persistenceVerified'):
        profiles.require(a[k] in (0,1),'REOPEN_ACTION_BOOLEAN')
    profiles.require(a['reopenVerified']==a['persistenceVerified']==0,'REOPEN_PREMATURE_BUSINESS_SUCCESS')
    if a['nativeCallAttempted']:
        profiles.require(a['callSize']==36 and a['callVersion']==1 and a['preflightAccepted']==a['routeBefore']==a['routeAfter']==a['businessPending']==1,'REOPEN_ACTION_CALL_CONTRACT')
        base=readonly.load_decoder().decode_snapshot(record)
        base['levelCatalog']=catalog_api.decode(record,base,catalog_api.load_profile())
        base['lifecycleType']=lifecycle_api.decode(record,base,lifecycle_api.load_profile())
        base['schedulerCoroutines']=scheduler_api.decode(record,base,scheduler_api.load_profile())
        g=guards_api.decode(record,base,guards_api.load_profile(),prepared)
        d=base['levelCatalog'];matches=[row for row in d['levels'] if row['id']==a['levelId']]
        profiles.require(d['ok'] and base['lifecycleType']['ok'] and base['schedulerCoroutines']['ok'] and
                         g['ok'] and g['bothFalseProven'] and d['counts']['dirtyByte']==0,'REOPEN_ACTION_FRESH_PREREQUISITES')
        profiles.require(a['entry']==int(base['pointers']['moduleBase'],16)+0x13564e90 and
                         a['levelManager']==int(d['pointers']['levelManager'],16) and len(matches)==1 and
                         a['record']==matches[0]['record']==int(g['pointers']['currentRecord'],16),'REOPEN_ACTION_TARGET')
        profiles.require((a['status'],a['callCode'],a['nativeCallReturned']) in ((7,2,1),(8,3,0)),'REOPEN_ACTION_OUTCOME')
        profiles.require(a['exceptionCode']==0 if a['nativeCallReturned'] else a['exceptionCode']!=0,'REOPEN_ACTION_EXCEPTION')
    else:
        profiles.require(a['status'] in (1,2,3,4,5,6) and not any(a[k] for k in ('callSize','callVersion','callCode','nativeCallReturned','exceptionCode','businessPending','preflightAccepted','entry','levelManager','record')),'REOPEN_REFUSAL_CALL_FIELDS')
        expected_routes={1:{(0,0)},2:{(0,0)},3:{(0,0)},4:{(0,0),(1,0)},5:{(1,0)},6:{(1,1)}}
        profiles.require((a['routeBefore'],a['routeAfter']) in expected_routes[a['status']],'REOPEN_REFUSAL_ROUTE_FIELDS')
    profiles.require(record.get('businessPending') is bool(a['businessPending']) and record.get('reopenVerified') is False and
                     record.get('persistenceVerified') is False and record.get('callReturned') is bool(a['nativeCallReturned']) and
                     record.get('ok') is False,'REOPEN_ACTION_REPORTED_BOUNDARY')
    cleanup=(type(record.get('activeCallbacks')) is int and type(record.get('callbackCount')) is int and record.get('transportOk') is True and record.get('unhooked') is True and record.get('activeCallbacks')==0 and record.get('callbackCount')==1)
    return a,cleanup

def _run(session_path,review_path,request_id,lease_sha,*,_evidence):
    from scene_cli import is_admin_token
    profiles.require(is_admin_token(),'REOPEN_REQUIRES_HELPER_ELEVATED_TOKEN')
    profiles.require(type(request_id) is str and re.fullmatch('[0-9a-f]{32}',request_id) and type(lease_sha) is str and re.fullmatch('[0-9a-f]{64}',lease_sha),'REOPEN_HELPER_BINDING')
    root=profiles.ROOT/'.runtime/editor-bridge/native-dispatch';active=root/'native-active.json';claim=root/request_id/'reopen-claim.json'
    profiles.require(profiles.sha256(active)==profiles.sha256(claim)==lease_sha,'REOPEN_LEASE_CHANGED')
    lease=review_api.read_json(active);review=review_api.read_json(review_path)
    profiles.require(lease.get('schema')==1 and lease.get('levelId')==1073741840 and
                     Path(lease.get('sessionPath','')).resolve()==Path(session_path).resolve() and
                     lease.get('sessionSha256')==profiles.sha256(Path(session_path)),'REOPEN_LEASE_SESSION_BINDING')
    profiles.require(lease.get('action')=='reopen-current' and lease.get('requestId')==review.get('requestId')==request_id and lease.get('reviewSha256')==profiles.sha256(review_path),'REOPEN_REVIEW_LEASE_BINDING')
    profile=builder.prepare(session_path,review_path);run=Path(profile['run']);_evidence['run']=str(run);prepared=review_api.read_json(run/'prepared.json')
    profiles.require(profiles.sha256(active)==lease_sha,'REOPEN_LEASE_CHANGED_BEFORE_LAUNCH')
    for n,h in profile['hashes'].items():profiles.require(profiles.sha256(run/n)==h,'REOPEN_ARTIFACT_CHANGED')
    builder.validate_review(review_path,prepared['session']);profiles.validate_session(prepared['session'])
    profiles.require(all(profiles.sha256(builder.NATIVE/n)==h for n,h in prepared['sources'].items()),'REOPEN_SOURCES_CHANGED')
    readonly.write_json(run/'direct-launch-intent.json',{'action':'reopen-current','requestId':request_id,'leaseSha256':lease_sha,'createdUtc':datetime.now(timezone.utc).isoformat(),'nativeStarted':None})
    host=profiles.powershell_host();readonly.write_json(run/'powershell-host.json',host)
    shell=Path(host['path']);env=os.environ.copy();env['PSModulePath']=str(shell.parent/'Modules')
    with (run/'launcher.stdout.txt').open('xb') as stdout,(run/'launcher.stderr.txt').open('xb') as stderr:
        child=subprocess.Popen([str(shell),'-NoProfile','-File',profile['wrapper']],cwd=run,stdout=stdout,stderr=stderr,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    until=time.monotonic()+90
    while time.monotonic()<until:
        if (run/'exit.json').exists():
            try:x=review_api.read_json(run/'exit.json')
            except (OSError,ValueError):time.sleep(.1);continue
            profiles.require(x.get('executed') is True and x.get('error') is None,'REOPEN_WRAPPER_FAILED')
            record,_=readonly.load_decoder().read_probe(run/'stdout.jsonl');a,cleanup=decode_action(record,prepared)
            result=dispatch_result(request_id=request_id,native_receipt_sha256=profiles.sha256(run/'stdout.jsonl'),
                preflight_passed=bool(a['preflightAccepted']),call_attempted=bool(a['nativeCallAttempted']),call_returned=bool(a['nativeCallReturned']),
                call_exception_code=a['exceptionCode'],hook_cleanup_verified=cleanup)
            profiles.require(x['exitCode']==(0 if a['nativeCallReturned'] else 1),'REOPEN_EXIT_RECEIPT_MISMATCH')
            result.update(run=str(run),receipt=str(run/'stdout.jsonl'),preparedSha256=profiles.sha256(run/'prepared.json'),leaseSha256=lease_sha,actionReceipt=a)
            readonly.write_json(run/'result.json',result);return result
        if child.poll() is not None:raise RuntimeError('REOPEN_WRAPPER_EXIT_WITHOUT_RECEIPT; business ownership retained')
        time.sleep(.1)
    raise RuntimeError('REOPEN_WAIT_EXPIRED; do not retry; business ownership retained')


def run(session_path,review_path,request_id,lease_sha):
    evidence={}
    try:
        return _run(session_path,review_path,request_id,lease_sha,_evidence=evidence)
    except Exception as exc:
        # Keep the exact evidence path for CLI/helper reconciliation. Never clear ownership.
        if 'run' in evidence:exc.run=evidence['run']
        raise
