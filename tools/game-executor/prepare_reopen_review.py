"""Prepare one evidence-bound reopen review; never compile, dispatch, or reopen.

This is an internal evidence gate, not user approval. Inputs must describe the
current session, a fresh full native baseline, a complete editor capture and a
newly registered passive observer. Existing backup-account-saves manifests are
normalized into a new directory; source evidence and live saves are never edited.
Editor and observer inputs must be the fixed response files in the named bridge
run directory. Copied business JSON and caller-written request metadata cannot
establish scope ownership.
"""
from __future__ import annotations
import argparse
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import json
import os
import re
import secrets

import native_profiles as profiles
import native_write_review as review_api
import native_reopen_baseline as baseline_api
import native_reopen_acceptance as acceptance
import build_reopen_profile as builder
import build_readonly_profile as readonly


def now_utc():return datetime.now(timezone.utc)


def evidence_time(value, reason):
    profiles.require(isinstance(value,str),reason)
    try:
        return acceptance.utc(value)
    except (ValueError,TypeError,OverflowError) as exc:
        raise profiles.ProfileError(reason) from exc


def reference(path):
    path=review_api.project_evidence(path)
    return {'path':str(path),'sha256':profiles.sha256(path)}


def query_editor_identity(pid):
    """Query-only process metadata; does not connect a pipe or invoke editor code."""
    k,_=profiles.windows_api();handle=k.OpenProcess(0x1000,False,pid)
    profiles.require(bool(handle),'REOPEN_EDITOR_PROCESS_QUERY_FAILED')
    try:
        image=C.create_unicode_buffer(32768);length=W.DWORD(len(image));times=[W.FILETIME() for _ in range(4)]
        profiles.require(k.QueryFullProcessImageNameW(handle,0,image,C.byref(length)) and
                         k.GetProcessTimes(handle,*(C.byref(t) for t in times)),'REOPEN_EDITOR_PROCESS_QUERY_FAILED')
        return dict(pid=pid,creationFileTime=profiles._filetime(times[0]),image=str(Path(image.value).resolve()))
    finally:k.CloseHandle(handle)


def validate_bridge_scope(run_id, session, editor_path, observer_path):
    # call-bridge.ps1 writes raw replies without identity envelopes. Only its
    # fixed per-scope response files, paired with the server's ready receipt,
    # provide the available provenance. Caller-made request metadata is not proof.
    directory=review_api.project_evidence(profiles.ROOT/'.runtime/editor-bridge/runs'/run_id)
    profiles.require(not (directory/'lease-closed.json').exists(),'REOPEN_BRIDGE_SCOPE_CLOSED')
    scope_ref=reference(directory/'bridge-settings.json');ready_ref=reference(directory/'bridge-ready.json')
    scope=acceptance.json_read(scope_ref['path']);ready=acceptance.json_read(ready_ref['path'])
    expected_editor=Path(session['image']).resolve().parent/'BeyondAssets/BeyondAssistEditor/BeyondEditor.exe'
    pid=scope.get('pid');ticks=scope.get('startUtcTicks')
    profiles.require(type(pid) is int and pid>0 and pid!=session['pid'] and
                     isinstance(ticks,str) and ticks.isdigit() and int(ticks)>504911232000000000,'REOPEN_BRIDGE_IDENTITY')
    profiles.require(Path(scope.get('expectedExe','')).resolve()==expected_editor and
                     scope.get('pipeName')=='miliastra-bridge-'+run_id,'REOPEN_BRIDGE_TARGET')
    current=now_utc();expires=evidence_time(scope.get('expiresUtc'),'REOPEN_BRIDGE_EXPIRY')
    opened=evidence_time(ready.get('recordedUtc'),'REOPEN_BRIDGE_READY_TIME')
    profiles.require(opened<=current<expires and 0<(expires-opened).total_seconds()<=300,'REOPEN_BRIDGE_EXPIRED')
    profiles.require(ready.get('accepted') is True and ready.get('code')==0 and ready.get('reason') is None and
                     ready.get('readyWritten') is True and ready.get('readyWriteFailure') is None,'REOPEN_BRIDGE_NOT_READY')
    profiles.require(ready.get('hostPid')==ready.get('settingsPid')==pid and
                     ready.get('hostStartUtcTicks')==ready.get('settingsStartUtcTicks')==ticks and
                     Path(ready.get('hostExePath','')).resolve()==Path(ready.get('settingsExpectedExe','')).resolve()==expected_editor and
                     ready.get('pipeName')==scope['pipeName'] and
                     evidence_time(ready.get('settingsExpiresUtc'),'REOPEN_BRIDGE_EXPIRY')==expires,'REOPEN_BRIDGE_READY_BINDING')
    refs={}
    for key,path,name in (('editorResponse',editor_path,'inspect-reopen-content-response.json'),
                          ('observerResponse',observer_path,'start-external-asset-observer-response.json')):
        expected=(directory/name).resolve()
        profiles.require(review_api.project_evidence(path)==expected,'REOPEN_SCOPE_RESPONSE_PATH:'+key)
        refs[key]=reference(expected)
    observed=query_editor_identity(pid)
    profiles.require(observed.get('pid')==pid and observed.get('creationFileTime')==int(ticks)-504911232000000000 and
                     Path(observed.get('image','')).resolve()==expected_editor,'REOPEN_EDITOR_PROCESS_CHANGED')
    observed['image']=str(expected_editor)
    for ref in (scope_ref,ready_ref,*refs.values()):
        profiles.require(profiles.sha256(Path(ref['path']))==ref['sha256'],'REOPEN_BRIDGE_EVIDENCE_CHANGED')
    return dict(scope=scope_ref,ready=ready_ref,**refs,editorProcess=observed,
                openedUtc=opened.isoformat(),expiresUtc=expires.isoformat())


def normalize_backup(manifest_path):
    """Validate current source and full recovery copy, supporting both known schemas."""
    manifest_path=review_api.project_evidence(manifest_path)
    digest=profiles.sha256(manifest_path);m=acceptance.json_read(manifest_path)
    profiles.require(evidence_time(m.get('createdUtc'),'REOPEN_BACKUP_TIME')<=now_utc(),'REOPEN_BACKUP_TIME')
    source=Path(m['source']).resolve()
    official=(Path(os.environ['USERPROFILE'])/'AppData/LocalLow/miHoYo/\u539f\u795e/BeyondLocal').resolve()
    profiles.require(source.parent==official and source.name.isdigit(),'REOPEN_ACCOUNT_ROOT')
    standard=m.get('schemaVersion')==1 and 'backup' not in m
    profiles.require(standard or ('backup' in m and 'schemaVersion' not in m),'REOPEN_BACKUP_SCHEMA')
    backup=review_api.project_evidence(manifest_path.parent/'files' if standard else m['backup'])
    profiles.require(isinstance(m.get('files'),list) and m['files'],'REOPEN_BACKUP_FILES')
    rows=[];seen=set()
    for row in m['files']:
        rel=row['relpath' if standard else 'relativePath'];size=row['size' if standard else 'bytes'];sha=row['sha256']
        profiles.require(type(rel) is str,'REOPEN_BACKUP_PATH')
        pure=PurePosixPath(rel);key=rel.casefold()
        profiles.require(str(pure)==rel and not pure.is_absolute() and '..' not in pure.parts and '\\' not in rel and key not in seen,'REOPEN_BACKUP_PATH')
        a=(source/rel).resolve();b=(backup/rel).resolve()
        profiles.require(a.is_relative_to(source) and b.is_relative_to(backup),'REOPEN_BACKUP_PATH')
        profiles.require(type(size) is int and size>=0 and type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha),'REOPEN_BACKUP_ROW')
        profiles.require(a.is_file() and b.is_file() and a.stat().st_size==b.stat().st_size==size and profiles.sha256(a)==profiles.sha256(b)==sha,'REOPEN_ACCOUNT_OR_BACKUP_CHANGED')
        rows.append(dict(relativePath=rel,bytes=size,sha256=sha,mtimeNs=row['mtimeNs']));seen.add(key)
    for root in (source,backup):
        actual={p.relative_to(root).as_posix().casefold() for p in root.rglob('*') if p.is_file()}
        profiles.require(actual==seen,'REOPEN_ACCOUNT_FILE_SET_CHANGED')
    profiles.require(m.get('fileCount')==len(rows) and m.get('totalBytes')==sum(r['bytes'] for r in rows),'REOPEN_BACKUP_TOTALS')
    profiles.require(acceptance.FORMAL_RELATIVE.casefold() in seen and 'beyond_local_save_player.gip' in seen,'REOPEN_ACCOUNT_REQUIRED_FILES')
    profiles.require(profiles.sha256(manifest_path)==digest,'REOPEN_BACKUP_MANIFEST_CHANGED')
    return dict(createdUtc=m['createdUtc'],source=str(source),backup=str(backup),fileCount=len(rows),
                totalBytes=sum(r['bytes'] for r in rows),files=rows,
                originalManifest=dict(path=str(manifest_path),sha256=digest))


def validate_observer(value, now):
    profiles.require(all(value.get(k) is True for k in ('ok','active','observerRegistered','originalReceiversPreserved')),'REOPEN_OBSERVER_INACTIVE')
    profiles.require(value.get('callbackErrors')==0 and value.get('contractRejectedCallbacks')==0 and value.get('observerCleanupError') is None,'REOPEN_OBSERVER_ERRORS')
    x=value['levelInitialization'];timing=value['observerTiming']
    profiles.require(all(x.get(k) is True for k in ('started','active','managerSameReference','originalReceiverOrderPreserved','builtinBeforeOwnObserver','currentPayloadPresent','currentPayloadSameReference')) and x.get('ownReceiverCount')==1,'REOPEN_OBSERVER_CONTRACT')
    profiles.require(x.get('source')=='received-1022-packet-observer' and x.get('overflow') is False and all(x.get(k)==0 for k in ('parseErrors','evidenceErrors','threadErrors','droppedEvents','retainedEvents','sequence')) and x.get('events')==[],'REOPEN_OBSERVER_BASELINE_NOT_CLEAN')
    profiles.require(x.get('currentLevelId')==x.get('baselineLevelId')==baseline_api.LEVEL and isinstance(x.get('observationId'),str) and x['observationId'],'REOPEN_OBSERVER_LEVEL_IDENTITY')
    initialized=evidence_time(x.get('initStartedUtc'),'REOPEN_OBSERVER_INIT_TIME')
    registered=evidence_time(timing.get('registrationCompletedUtc'),'REOPEN_OBSERVER_NOT_FRESH')
    profiles.require(initialized<=registered<=now,'REOPEN_OBSERVER_INIT_TIME')
    profiles.require(timing.get('scope')=='current-observer-instance-only' and type(timing.get('registrationCompletedTick')) is int and timing.get('stoppedUtc') is None and timing.get('stoppedTick') is None and 0<=(now-registered).total_seconds()<=10,'REOPEN_OBSERVER_NOT_FRESH')


def prepare(session_path, baseline_run, account_backup_manifest, editor_baseline, observer_baseline,
            bridge_run_id, *, output_root=None, ttl_seconds=120):
    profiles.require(type(ttl_seconds) is int and 15<=ttl_seconds<=300,'REOPEN_REVIEW_TTL')
    profiles.require(isinstance(bridge_run_id,str) and re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',bridge_run_id),'REOPEN_BRIDGE_ID')
    session_ref=reference(session_path);session=profiles.validate_session(review_api.read_json(session_ref['path']))
    bridge=validate_bridge_scope(bridge_run_id,session,editor_baseline,observer_baseline)
    base=baseline_api.load(baseline_run,session)
    normalized=normalize_backup(account_backup_manifest)
    editor_ref=reference(editor_baseline);observer_ref=reference(observer_baseline)
    editor_doc=acceptance.json_read(editor_ref['path']);observer_doc=acceptance.json_read(observer_ref['path'])
    current=now_utc()
    opened=acceptance.utc(bridge['openedUtc']);scope_expiry=acceptance.utc(bridge['expiresUtc'])
    profiles.require(opened<=evidence_time(editor_doc.get('observedUtc'),'REOPEN_EDITOR_NOT_FRESH') and
                     opened<=evidence_time(observer_doc.get('levelInitialization',{}).get('initStartedUtc'),'REOPEN_OBSERVER_INIT_TIME'),'REOPEN_EVIDENCE_PRECEDES_SCOPE')
    profiles.require(0<=(current-acceptance.utc(editor_doc['observedUtc'])).total_seconds()<=180 and
                     acceptance.utc(editor_doc['observedUtc'])<=acceptance.utc(editor_doc['finishedUtc'])<=current,'REOPEN_EDITOR_NOT_FRESH')
    profiles.require(editor_doc.get('schemaVersion')==2,'CURRENT_SHARED_EDITOR_SCHEMA_REQUIRED')
    editor=acceptance.editor_content(editor_doc)
    formal=acceptance.formal_content(Path(normalized['backup'])/acceptance.FORMAL_RELATIVE)
    # Compare only the pre-action structures; this is not a roundtrip claim.
    acceptance.compare_content(editor,editor,formal,base['context'],base['context'])
    validate_observer(observer_doc,now_utc())
    for ref in (session_ref,editor_ref,observer_ref,normalized['originalManifest']):
        profiles.require(profiles.sha256(Path(ref['path']))==ref['sha256'],'REOPEN_INPUT_CHANGED')
    refreshed=baseline_api.load(baseline_run,session)
    profiles.require(refreshed['evidenceHashes']==base['evidenceHashes'],'REOPEN_BASELINE_CHANGED')
    profiles.require(validate_bridge_scope(bridge_run_id,session,editor_baseline,observer_baseline)==bridge,'REOPEN_BRIDGE_CHANGED_DURING_PREPARATION')
    request_id=secrets.token_hex(16)
    parent=review_api.project_evidence(output_root or profiles.ROOT/'.runtime/game-executor/reopen-reviews')
    work=parent/request_id;work.mkdir(parents=True,exist_ok=False)
    manifest=work/'account-before.json';readonly.write_json(manifest,normalized)
    acceptance.read_account(manifest)
    stamp=now_utc();expires=min(stamp+timedelta(seconds=ttl_seconds),scope_expiry)
    profiles.require((expires-stamp).total_seconds()>=15,'REOPEN_BRIDGE_WINDOW_TOO_SHORT')
    review=dict(schemaVersion=1,operation='level.reopen-current',allowedCalls=1,levelId=baseline_api.LEVEL,
        requestId=request_id,createdUtc=stamp.isoformat(),expiresUtc=expires.isoformat(),
        session=session,baselineRun=base['baselineRun'],baselineHashes=base['evidenceHashes'],
        accountBackupManifest=str(manifest),accountBaselineSha256=profiles.sha256(manifest),
        editorBaseline=editor_ref,observerBaseline=observer_ref,bridgeRunId=bridge_run_id,bridgeEvidence=bridge)
    review['reopenLifecycle']=dict(bridgeRunId=bridge_run_id,accountBaselineSha256=review['accountBaselineSha256'],
                                 acceptanceVerifierSha256=profiles.sha256(Path(acceptance.__file__)))
    candidate=work/'review.pending.json';readonly.write_json(candidate,review)
    try:
        builder.validate_review(candidate,session)
        validate_observer(observer_doc,now_utc())
        profiles.require(validate_bridge_scope(bridge_run_id,session,editor_baseline,observer_baseline)==bridge,'REOPEN_BRIDGE_CHANGED_DURING_PREPARATION')
        final=work/'review.json';candidate.rename(final)
    except BaseException as exc:
        # This file belongs only to this new attempt. Retain the failed intent
        # as data, while refusing accidental dispatch of the rejected candidate.
        if candidate.exists():
            rejected=dict(schemaVersion=0,operation='level.reopen-review-rejected',error=str(exc),candidate=review)
            candidate.write_text(json.dumps(rejected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
    result=dict(ok=True,requestId=request_id,reviewPath=str(final),reviewSha256=profiles.sha256(final),
        accountBackupManifest=str(manifest),accountBaselineSha256=review['accountBaselineSha256'],
        executed=False,businessVerified=False,scope='review-preparation-only')
    readonly.write_json(work/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('session','baseline-run','account-backup-manifest','editor-baseline','observer-baseline','bridge-run-id'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--output-root');parser.add_argument('--ttl-seconds',type=int,default=120)
    args=parser.parse_args()
    try:
        result=prepare(args.session,args.baseline_run,args.account_backup_manifest,args.editor_baseline,
                       args.observer_baseline,args.bridge_run_id,output_root=args.output_root,ttl_seconds=args.ttl_seconds)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print(json.dumps(dict(ok=False,error=str(exc),executed=False,businessVerified=False)));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
