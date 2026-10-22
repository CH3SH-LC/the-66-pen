"""Native persistence proof: raw save callback + exact immutable GIL recovery.

No process access, game method, save invocation, or formal-file write. Content
equality alone never produces nativeSaveVerified.
"""
from __future__ import annotations
from datetime import datetime
import json
import re
from pathlib import Path
from terrain_model import artifact_path, digest, require, verify_save
import terrain_recovery as recovery_api
import terrain_native as native
import native_write_review as reviews

def read(path):return native.ro.read_json(path)
def sha(path):return native.profiles.sha256(Path(path))

def same_scene(left,right):
    for name in ('moduleBase','global','currentContext','contextManager','saveManager','contextDictionary','entityDictionary'):
        require(left['pointers'][name]==right['pointers'][name],'SAVE_SCENE_POINTER_CHANGED:'+name)
    require(left['origin']==right['origin'],'SAVE_SCENE_ORIGIN_CHANGED')
    require(left['levelObservation']==right['levelObservation'],'SAVE_SCENE_LEVEL_CHANGED')
    for name in ('activeKey','entityVersionBefore','entityVersionAfter','entityCaptured','entityValidEntries','entityRejected'):
        require(left['counts'][name]==right['counts'][name],'SAVE_SCENE_COUNT_CHANGED:'+name)
    require(left['entities']==right['entities'],'SAVE_SCENE_ENTITIES_CHANGED')

def same_session(left,right):
    for name in reviews.SESSION_FIELDS:
        require(name in left and name in right and left[name]==right[name],'SAVE_SESSION_CHANGED:'+name)

def utc(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(result.tzinfo is not None,'SAVE_TIMEZONE_REQUIRED')
    return result

def capture_evidence(run,names):
    result={}
    for name in names:
        path=artifact_path(run/name);require(path.parent==run and path.is_file(),'SAVE_EVIDENCE_PATH')
        result[str(path)]=sha(path)
    return result

def check_unchanged(pins):
    for path,value in pins.items():require(sha(path)==value,'SAVE_EVIDENCE_CHANGED_DURING_VERIFY:'+path)

def bind_save_card(save_run,profile,prepared,record):
    """Read the compiled card's pinned header, never the unpinned sidecar."""
    required={'hook_receipt.dll','hook_receipt_probe.exe','target_config.h','prepared.json',
              'baseline-context.json','invoke-fixed-probe.ps1'}
    hashes=profile.get('hashes',{})
    require(type(hashes) is dict and required<=set(hashes),'SAVE_COMPILED_ARTIFACT_SET_REQUIRED')
    pins=capture_evidence(save_run,hashes)
    for name,value in hashes.items():require(pins[str(save_run/name)]==value,'SAVE_COMPILED_ARTIFACT_CHANGED:'+name)
    text=(save_run/'target_config.h').read_text(encoding='utf-8')
    values={}
    for name in ('HR_NONCE','HR_DEADLINE','HR_ACTION','HR_TARGET_PID','HR_TARGET_TID',
                 'HR_TARGET_CREATION','HR_TARGET_THREAD_CREATION','HR_EXPECTED_LEVEL','HR_EXPECTED_CONTEXT'):
        definitions=re.findall(r'^\s*#define\s+'+name+r'\s+([^\r\n]+)',text,re.M)
        require(len(definitions)==1 and re.fullmatch(r'[0-9]+ULL',definitions[0]) is not None,
                'SAVE_HEADER_CARD_VALUE_REQUIRED:'+name)
        values[name]=int(definitions[0][:-3])
    session=prepared['session']
    expected={'HR_ACTION':2,'HR_TARGET_PID':session['pid'],'HR_TARGET_TID':session['tid'],
              'HR_TARGET_CREATION':session['processCreation'],'HR_TARGET_THREAD_CREATION':session['threadCreation'],
              'HR_EXPECTED_LEVEL':profile['expectedLevelId']}
    require(all(values[name]==value for name,value in expected.items()),'SAVE_HEADER_IDENTITY_MISMATCH')
    image=re.findall(r'^\s*#define\s+HR_TARGET_IMAGE\s+L([^\r\n]+)',text,re.M)
    require(len(image)==1 and json.loads(image[0])==session['image'],'SAVE_HEADER_IMAGE_MISMATCH')
    require(values['HR_NONCE']>0 and values['HR_DEADLINE']>0 and
            record.get('receiptNonce')==str(values['HR_NONCE']) and
            record.get('receiptDeadline')==str(values['HR_DEADLINE']) and
            type(record.get('receiptProtocol')) is int and record['receiptProtocol']==3,
            'SAVE_RAW_CARD_BINDING_REQUIRED')
    require(profile.get('deadlineTick')==values['HR_DEADLINE'] and profile.get('targetPid')==session['pid'] and
            profile.get('targetTid')==session['tid'],'SAVE_BUILD_CARD_BINDING_MISMATCH')
    require(prepared.get('allowWrites') is True and profile.get('allowWrites') is True and
            prepared.get('writeProfileSha256')==reviews.WRITE_PROFILE_SHA256,'SAVE_WRITE_PROFILE_REQUIRED')
    return values,pins

def verify_gil_bundle(run,built,save_run,reply,save_profile,plan):
    """Pure file-evidence layer; does not certify that a native call occurred."""
    recovery=recovery_api.validate(run,built.get('recovery',{}),built['levelId'],built['sourceSave'])
    require(read(run/'recovery.json')==built['recovery'],'RECOVERY_MANIFEST_CHANGED')
    level_key=str(built['levelId']);target=recovery[level_key]
    require(sha(run/'before.gil')==target['sha256']==plan['sourceSha256'],'TERRAIN_BEFORE_COPY_MISMATCH')
    require(recovery_api.formal_source(save_profile['targetGil'],built['levelId'])==Path(target['source']),
            'SAVE_PROFILE_TARGET_SOURCE_CHANGED')
    expected_siblings={item['source'] for key,item in recovery.items() if key!=level_key}
    protected=save_profile.get('protectedGils',[])
    require(type(protected) is list and len(protected)==len(set(protected)) and set(protected)==expected_siblings,
            'SAVE_PROFILE_PROTECTED_SIBLINGS_INCOMPLETE')
    before,after=reply.get('beforeGils'),reply.get('afterGils')
    require(type(before) is dict and type(after) is dict and set(before)==set(after)==set(recovery),'SAVE_GIL_SET_MISMATCH')
    copies={};pins={str(run/'recovery.json'):sha(run/'recovery.json')}
    pins.update({item['backup']:item['sha256'] for item in recovery.values()})
    for phase,observed in [('before',before),('after',after)]:
        copies[phase]={}
        for key,item in observed.items():
            source=recovery_api.formal_source(item['source'],int(key))
            require(str(source)==recovery[key]['source'],'SAVE_GIL_SOURCE_CHANGED:'+key)
            path=artifact_path(item['snapshot'])
            require(path==save_run/f'{phase}-{key}.gil','SAVE_GIL_COPY_OUTSIDE_RUN:'+key)
            blob=path.read_bytes();actual=digest(blob)
            require(actual==item['sha256'] and len(blob)==item['bytes'],'SAVE_GIL_COPY_CHANGED:'+key)
            copies[phase][key]=blob;pins[str(path)]=actual
            if phase=='before' or key!=level_key:
                require(actual==recovery[key]['sha256'],'SAVE_BASELINE_OR_SIBLING_CHANGED:'+key)
    if plan.get('schema')=='native-terrain-batch-card-v1':
        import terrain_batch
        content=terrain_batch.saved_content(plan,target['blob'],copies['after'][level_key])
    else:content=verify_save(target['blob'],copies['after'][level_key],plan)
    require(content['ok'],'SAVED_TERRAIN_CONTENT_REJECTED:'+','.join(content['failures']))
    pins.update(content.get('batchEvidenceSha256',{}))
    return content,sorted(int(key) for key in recovery if key!=level_key),pins

def verify(run,save_run):
    run,built=native.checked_run(run)
    terrain=native.decode(run)
    require(terrain['ok'] and not built['inspectOnly'] and not built.get('refreshOnly') and not terrain['outcomeUncertain'] and terrain['safeToRelease'],
            'SUCCESSFUL_TERRAIN_WRITE_REQUIRED')
    require(built.get('recovery',{}).get('schema')=='terrain-save-recovery-v1','NATIVE_SAVE_REQUIRES_PREWRITE_RECOVERY')
    save_run=artifact_path(save_run);require(save_run!=run,'SAVE_RUN_MUST_BE_SEPARATE')
    import scene_cli
    scene_cli.guarded_runtime_file(save_run/'result.json','NATIVE_SAVE_RESULT')
    pins=capture_evidence(save_run,('result.json','prepared.json','build-result.json','stdout.jsonl','exit.json','before-gils.json','after-gils.json'))
    pins.update(capture_evidence(run,('prepared.json','build-result.json','stdout.jsonl','exit.json','request.json','before.gil')))
    require(pins[str(run/'stdout.jsonl')]==terrain['rawReceiptSha256'],'TERRAIN_RECEIPT_CHANGED_DURING_VERIFY')
    reply=read(save_run/'result.json');save_profile=read(save_run/'build-result.json')
    require(reply.get('ok') is True and reply.get('action')=='save' and not reply.get('outcomeUncertain') and
            Path(reply.get('run','')).resolve()==save_run,'NATIVE_SAVE_RESULT_REQUIRED')
    require(save_profile.get('action')=='save' and save_profile.get('expectedLevelId')==built['levelId'] and
            Path(save_profile.get('run','')).resolve()==save_run,'NATIVE_SAVE_PROFILE_REQUIRED')
    saved_after,save_prepared=reviews.load_baseline(save_run,'action-after',built['levelId'])
    require(save_prepared.get('request')=={'action':'save','levelId':built['levelId']},'SAVE_PREPARED_REQUEST_MISMATCH')
    require(save_profile.get('requestSha256')==reviews.canonical_hash(save_prepared['request']),'SAVE_REQUEST_HASH_MISMATCH')
    same_session(built['session'],save_prepared['session']);same_session(built['session'],save_profile['session'])
    save_record,_=native.ro.load_decoder().read_probe(save_run/'stdout.jsonl')
    card,card_pins=bind_save_card(save_run,save_profile,save_prepared,save_record);pins.update(card_pins)
    action=save_record.get('action',{})
    require(action.get('kind')==2 and action.get('status')==0 and action.get('called')==1 and
            action.get('nativeSaveStatus')==0 and action.get('levelId')==action.get('expectedLevelId')==built['levelId'],
            'NATIVE_SAVE_ACTION_RECEIPT_REQUIRED')
    require(save_record.get('transportOk') is True and save_record.get('unhooked') is True and
            save_record.get('activeCallbacks')==0 and save_record.get('callbackCount')==1,'NATIVE_SAVE_CLEANUP_REQUIRED')
    decoder=native.ro.load_decoder();saved_before=decoder.decode_snapshot(save_record)
    require(int(saved_before['pointers']['currentContext'],16)==card['HR_EXPECTED_CONTEXT'],'SAVE_HEADER_CONTEXT_MISMATCH')
    read_record=dict(save_record,scope='READ_ONLY_CONTEXT_RECEIPT',snapshotStatus=saved_before['status']['value'])
    validation=native.ro.validate_receipt(read_record,saved_before,save_prepared,native.profiles.load_profile())
    require(validation['ok'],'SAVE_BEFORE_CONTEXT_REJECTED:'+','.join(validation['reasons']))
    terrain_record,_=decoder.read_probe(run/'stdout.jsonl')
    raw=bytes.fromhex(terrain_record['terrainHex'])[native.RECEIPT_BASE_SIZE:]
    terrain_after=decoder.decode_snapshot(dict(snapshotHex=raw.hex(),snapshotBytes=len(raw)))
    same_scene(terrain_after,saved_before);same_scene(terrain_after,saved_after)
    terrain_exit,save_exit=read(run/'exit.json'),read(save_run/'exit.json')
    require(utc(terrain_exit['finishedUtc'])<=utc(save_exit['startedUtc'])<=utc(save_exit['finishedUtc']),
            'NATIVE_SAVE_NOT_AFTER_TERRAIN_WRITE')
    require(read(save_run/'before-gils.json')==reply['beforeGils'] and read(save_run/'after-gils.json')==reply['afterGils'],
            'SAVE_GIL_MANIFEST_MISMATCH')
    content,protected,copy_pins=verify_gil_bundle(run,built,save_run,reply,save_profile,read(run/'request.json'))
    pins.update(copy_pins)
    import terrain_catalog
    catalog_pins,_=terrain_catalog.preparation(read(run/'request.json'),built['session'],built['levelId']);pins.update(catalog_pins)
    review_path=artifact_path(save_prepared['reviewPath']);require(sha(review_path)==save_prepared['reviewSha256'],'SAVE_REVIEW_CHANGED')
    review=read(review_path);require(review.get('recovery',{}).get('source')==built['sourceSave'] and
            review['recovery'].get('sha256')==content['beforeSha256'],'SAVE_REVIEW_RECOVERY_MISMATCH')
    wp=reviews.load_write_profile()
    require(review.get('schemaVersion')==1 and review.get('kind')=='native-write-review-v1' and
            review.get('state')=='reviewed' and review.get('reviewedBy')=='coordinator','SAVE_REVIEW_REQUIRED')
    require(review.get('levelId')==built['levelId'] and review.get('requestSha256')==save_profile['requestSha256'] and
            review.get('writeProfileSha256')==reviews.WRITE_PROFILE_SHA256 and
            review.get('readonlyProfileSha256')==native.profiles.PROFILE_SHA256 and
            review.get('profileId')==save_prepared.get('writeProfileId')==wp['profileId'],'SAVE_REVIEW_BINDING_MISMATCH')
    same_session(review['session'],built['session'])
    require(review.get('protectedGils')==save_profile['protectedGils'],'SAVE_REVIEW_PROTECTION_MISMATCH')
    require(utc(review['reviewedAtUtc'])<=utc(save_exit['startedUtc'])<utc(review['expiresUtc']) and
            0<(utc(review['expiresUtc'])-utc(review['reviewedAtUtc'])).total_seconds()<=3600,'SAVE_REVIEW_TIME_MISMATCH')
    review_copy=artifact_path(review['recovery']['backup']);require(sha(review_copy)==content['beforeSha256'],'SAVE_REVIEW_COPY_CHANGED')
    pins[str(review_path)]=sha(review_path);pins[str(review_copy)]=sha(review_copy)
    check_unchanged(pins)
    result={**content,'scope':'terrain-native-save-proof-v1','run':str(run),'saveRun':str(save_run),
            'fileContentVerified':True,'nativeSaveVerified':True,'persistentSaveVerified':True,
            'nativeTerrainVerified':True,'fullSceneVerified':True,'protectedLevels':protected,
            'entityRootPreserved':True,'directoryRootPreserved':True,'nodeGraphsPreserved':True,
            'allOtherSavedFieldsPreserved':content['allOtherSavedFieldsPreserved'],
            'allSaveDomainsVerified':content['allSaveDomainsVerified'],'timestampField40Allowed':True,
            'cleanupVerified':True,'safeToRelease':True,'noAutomaticReplay':True,
            'evidence':{'terrainReceiptSha256':terrain['rawReceiptSha256'],
                        'nativeSaveReceiptSha256':pins[str(save_run/'stdout.jsonl')],
                        'beforeSha256':content['beforeSha256'],'afterSha256':content['afterSha256'],
                        'artifactSha256':pins}}
    if content.get('shapeSemantics'):
        require(terrain.get('nativeSurfaceDataVerified') is True and terrain.get('nativeSurfaceResourcesVerified') is True,
                'SURFACE_NATIVE_DATA_AND_RESOURCE_PROOF_REQUIRED')
        result['nativeSurfaceSaveVerified']=True
    output=run/('native-save-verification-'+result['evidence']['nativeSaveReceiptSha256'][:16]+'.json')
    result['verification']=str(output)
    if output.exists():require(read(output)==result,'EXISTING_SAVE_PROOF_DIFFERS')
    else:native.write(output,result)
    return result
