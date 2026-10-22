"""Internal evidence gate for a single reviewed native write request.

This is not another user-approval flow. The coordinator records its existing
review of source, full runtime snapshot and recoverable save before dispatch.
No CLI here manufactures a reviewed record; missing/incomplete evidence refuses.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid
import native_profiles as profiles
import build_readonly_profile as readonly
import native_level_observation as level_api

WRITE_PROFILE=Path(__file__).with_name('profiles')/'genshin-cn-7.1.0-reviewed-write.json'
WRITE_PROFILE_SHA256='8887edc948ee75fc53ab2f1a32ed40d2fd1385d5395c0373d37de837b762b58e'
SESSION_FIELDS=('schemaVersion','pid','tid','window','windowClass','processCreation','threadCreation','image')


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def canonical_hash(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def project_evidence(path):
    p=Path(path).resolve();profiles.require(p.is_relative_to(profiles.ROOT/'.runtime'),'EVIDENCE_OUTSIDE_PROJECT_RUNTIME');return p

def load_write_profile():
    profiles.require(profiles.sha256(WRITE_PROFILE)==WRITE_PROFILE_SHA256,'WRITE_PROFILE_SOURCE_HASH_MISMATCH')
    p=read_json(WRITE_PROFILE);profiles.require(p.get('allowUnreviewedWrites') is False,'UNREVIEWED_WRITES_FORBIDDEN');return p

def load_baseline(run_path,kind,level_id):
    run=project_evidence(run_path);profile=profiles.load_profile();prepared=read_json(run/'prepared.json');built=read_json(run/'build-result.json')
    profiles.require(prepared.get('profileSha256')==profiles.PROFILE_SHA256 and prepared.get('launchable') is True and prepared.get('compileOnly') is False,'BASELINE_PROFILE_BINDING')
    for name,digest in built['hashes'].items():
        artifact=(run/name).resolve();profiles.require(artifact.parent==run,'BASELINE_ARTIFACT_PATH');profiles.require(profiles.sha256(artifact)==digest,'BASELINE_ARTIFACT_CHANGED:'+name)
    decoder=readonly.load_decoder();record,_=decoder.read_probe(run/'stdout.jsonl');exit_record=read_json(run/'exit.json')
    profiles.require(exit_record.get('executed') is True and exit_record.get('exitCode')==0 and not exit_record.get('error'),'BASELINE_EXECUTION_REJECTED')
    if kind=='readonly':
        snapshot=decoder.decode_snapshot(record);accepted=readonly.validate_receipt(record,snapshot,prepared,profile)
    elif kind=='action-after':
        action=record.get('action',{})
        profiles.require(record.get('scope')=='FIXED_SCENE_ACTION' and record.get('ok') is True and action.get('status')==0 and action.get('called')==1 and action.get('levelId')==level_id,'BASELINE_ACTION_NOT_COMPLETE')
        profiles.require(read_json(run/'result.json').get('ok') is True,'BASELINE_ACTION_RESULT_REJECTED')
        derived=dict(record,snapshotHex=record.get('afterSnapshotHex'),scope='READ_ONLY_CONTEXT_RECEIPT',snapshotStatus=0)
        snapshot=decoder.decode_snapshot(derived);accepted=readonly.validate_receipt(derived,snapshot,prepared,profile)
    else:raise profiles.ProfileError('BASELINE_KIND_UNSUPPORTED')
    profiles.require(accepted['ok'] and accepted['baselineNonempty'],'COMPLETE_RUNTIME_BASELINE_REQUIRED:'+','.join(accepted['reasons']))
    observed=snapshot.get('levelObservation',{})
    profiles.require(prepared.get('levelObservationProfileSha256')==level_api.LEVEL_PROFILE_SHA256 and observed.get('verified') is True and observed.get('levelId')==level_id,'BASELINE_CURRENT_LEVEL_NOT_VERIFIED')
    return snapshot,prepared

def validate_review(review_path,session,level_id,request,*,now=None):
    profiles.require(review_path is not None,'NATIVE_WRITE_REVIEW_REQUIRED')
    path=project_evidence(review_path);review=read_json(path);wp=load_write_profile()
    profiles.require(review.get('schemaVersion')==1 and review.get('kind')=='native-write-review-v1' and review.get('state')=='reviewed' and review.get('reviewedBy')=='coordinator','COORDINATOR_REVIEW_REQUIRED')
    identifier=str(uuid.UUID(review['reviewId']));profiles.require(identifier==review['reviewId'],'INVALID_REVIEW_ID')
    profiles.require(review.get('profileId')==wp['profileId'] and review.get('writeProfileSha256')==WRITE_PROFILE_SHA256 and review.get('readonlyProfileSha256')==profiles.PROFILE_SHA256,'REVIEW_PROFILE_MISMATCH')
    profiles.require(type(level_id) is int and 0<level_id<2**32 and review.get('levelId')==level_id,'REVIEW_LEVEL_MISMATCH')
    profiles.require(request.get('action') in wp['allowedActions'] and review.get('requestSha256')==canonical_hash(request),'REVIEW_REQUEST_MISMATCH')
    for key in SESSION_FIELDS:profiles.require(review['session'].get(key)==session.get(key),'REVIEW_SESSION_MISMATCH:'+key)
    at=datetime.fromisoformat(review['reviewedAtUtc'].replace('Z','+00:00'));until=datetime.fromisoformat(review['expiresUtc'].replace('Z','+00:00'));current=now or datetime.now(timezone.utc)
    profiles.require(at.tzinfo is not None and until.tzinfo is not None and at<=current<until and 0<(until-at).total_seconds()<=3600,'REVIEW_EXPIRED_OR_INVALID_TIME')
    run=project_evidence(review['baselineRun']);required={'prepared.json','build-result.json','stdout.jsonl','exit.json'}
    if review['baselineKind']=='action-after':required.add('result.json')
    profiles.require(required<=set(review['evidenceHashes']),'REVIEW_EVIDENCE_HASH_SET')
    for name,digest in review['evidenceHashes'].items():
        artifact=(run/name).resolve();profiles.require(artifact.parent==run,'REVIEW_ARTIFACT_PATH');profiles.require(profiles.sha256(artifact)==digest,'REVIEW_EVIDENCE_CHANGED:'+name)
    snapshot,prepared=load_baseline(run,review['baselineKind'],level_id)
    for key in SESSION_FIELDS:profiles.require(prepared['session'].get(key)==session.get(key),'BASELINE_SESSION_MISMATCH:'+key)
    save=review['recovery'];target=Path(save['source']).resolve();backup=project_evidence(save['backup'])
    official=Path(os.environ['USERPROFILE'])/'AppData/LocalLow/miHoYo/原神/BeyondLocal'
    relative=target.relative_to(official.resolve()) if target.is_relative_to(official.resolve()) else None
    profiles.require(relative is not None and len(relative.parts)==4 and relative.parts[0].isdigit() and relative.parts[1]=='Beyond_Local_Save_Level' and relative.parts[2]==str(level_id) and relative.parts[3]==str(level_id)+'.gil','REVIEW_TARGET_GIL_PATH')
    profiles.require(profiles.sha256(backup)==save['sha256'] and profiles.sha256(target)==save['sha256'],'RECOVERY_COPY_OR_FORMAL_GIL_CHANGED')
    protected=[]
    for name in review.get('protectedGils',[]):
        p=Path(name).resolve();profiles.require(p.parent.parent==target.parent.parent and p.parent.name==p.stem and p.stem.isdigit() and p.suffix=='.gil' and p!=target,'PROTECTED_GIL_PATH');protected.append(str(p))
    return {'reviewId':identifier,'reviewPath':str(path),'reviewSha256':profiles.sha256(path),
            'writeProfile':wp,'baseline':snapshot,'baselineRun':str(run),'targetGil':str(target),
            'protectedGils':protected,'recovery':save,'request':request,'review':review}

def claim_review(validated,run):
    claims=profiles.ROOT/'.runtime/game-executor/native-write-review-claims';claims.mkdir(parents=True,exist_ok=True)
    readonly.write_json(claims/(validated['reviewId']+'.json'),{'reviewSha256':validated['reviewSha256'],'run':str(run),'claim':'single-compiled-attempt; never auto-replayed'})

