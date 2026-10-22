"""Verify a native save against the exact successful transform receipt and backups."""
import importlib.util
from datetime import datetime
from pathlib import Path
import re
import hashlib
from contract import read, sha, require, near
from build import ROOT, EX, ro
from receipt import decode, manifest, same_scene
from recovery import classify,auxiliary_unchanged

SESSION_FIELDS = ('schemaVersion','pid','tid','window','windowClass','processCreation','threadCreation','image')

def timestamp(value):
    require(isinstance(value,str),'SAVE_TIME_REQUIRED')
    parsed = datetime.fromisoformat(value.replace('Z','+00:00'))
    require(parsed.tzinfo is not None,'SAVE_TIME_ZONE_REQUIRED')
    return parsed

def bind_session_and_time(prepared, save_prepared, save_built, record, transform_exit, save_exit):
    expected = prepared['session']
    for other in (save_prepared['session'],save_built['session']):
        require(all(key in expected and key in other and expected[key] == other[key] for key in SESSION_FIELDS),'SAVE_SESSION_MISMATCH')
    require(record.get('pid') == expected['pid'] and record.get('tid') == expected['tid'],'SAVE_CALLBACK_IDENTITY')
    a,b = timestamp(transform_exit['startedUtc']),timestamp(transform_exit['finishedUtc'])
    c = timestamp(save_built['createdUtc'])
    d,e = timestamp(save_exit['startedUtc']),timestamp(save_exit['finishedUtc'])
    require(a <= b <= c <= d <= e,'SAVE_MUST_FOLLOW_COMPLETED_TRANSFORM')
    return dict(transformFinishedUtc=transform_exit['finishedUtc'],savePreparedUtc=save_built['createdUtc'],
                saveStartedUtc=save_exit['startedUtc'],saveFinishedUtc=save_exit['finishedUtc'])

def bind_native_card(header_text, record, prepared):
    def constant(name):
        found = re.findall(r'^#define '+re.escape(name)+r' (\d+)ULL\s*$',header_text,re.MULTILINE)
        require(len(found)==1,'SAVE_COMPILED_CONSTANT_REQUIRED:'+name)
        return int(found[0])
    require(constant('HR_ACTION') == 2 and constant('HR_EXPECTED_LEVEL') == prepared['levelId'],'SAVE_COMPILED_ACTION_MISMATCH')
    session=prepared['session']
    for name,key in (('HR_TARGET_PID','pid'),('HR_TARGET_TID','tid'),('HR_TARGET_CREATION','processCreation'),('HR_TARGET_THREAD_CREATION','threadCreation')):
        require(constant(name) == session[key],'SAVE_COMPILED_SESSION_MISMATCH:'+key)
    require(record.get('receiptNonce') == str(constant('HR_NONCE')) and
            record.get('receiptDeadline') == str(constant('HR_DEADLINE')) and record.get('receiptProtocol') == 3,
            'SAVE_RAW_RECEIPT_CARD_IDENTITY_REQUIRED')
    return dict(nonce=record['receiptNonce'],deadline=record['receiptDeadline'],protocol=record['receiptProtocol'])

def bind_gil_evidence(save_run, prepared, save_built, reply):
    """Both snapshots must belong to this save and its complete source set."""
    save_run=Path(save_run).resolve()
    require(Path(reply['run']).resolve() == save_run and Path(reply['receipt']).resolve() == save_run/'stdout.jsonl','SAVE_RESULT_PATH_MISMATCH')
    expected,auxiliary=classify(prepared['recovery'])
    sources=[Path(save_built['targetGil']).resolve(),*[Path(p).resolve() for p in save_built.get('protectedGils',[])]]
    require(len(sources)==len(set(sources)) and set(sources)=={Path(v['source']).resolve() for v in expected.values()},'SAVE_SOURCE_ENUMERATION_MISMATCH')
    target=next(v for v in expected.values() if v['target'])
    require(sources[0] == Path(target['source']).resolve(),'SAVE_TARGET_SOURCE_MISMATCH')
    phases={}
    for phase in ('before','after'):
        copied=read(save_run/(phase+'-gils.json'))
        require(copied == reply[phase+'Gils'] and set(copied)==set(expected),'SAVE_PHASE_ENUMERATION_MISMATCH:'+phase)
        for key,item in copied.items():
            artifact=save_run/f'{phase}-{key}.gil'
            require(Path(item['source']).resolve()==Path(expected[key]['source']).resolve() and Path(item['snapshot']).resolve()==artifact,'SAVE_COPY_PATH_OR_SOURCE_MISMATCH')
            require(artifact.is_file() and not artifact.is_symlink() and not (getattr(artifact.stat(),'st_file_attributes',0)&0x400),'SAVE_COPY_REPARSE_OR_MISSING')
            require(sha(artifact)==item['sha256'] and artifact.stat().st_size==item['bytes'],'SAVE_COPY_HASH_OR_SIZE_MISMATCH')
            if phase=='before':
                require(item['sha256']==expected[key]['sha256'],'SAVE_BASELINE_MISMATCH')
            elif not expected[key]['target']:
                require(item['sha256']==expected[key]['sha256'],'PROTECTED_LEVEL_CHANGED:'+key)
        phases[phase]=copied
    phases['auxiliaryBackups']=auxiliary_unchanged(prepared,auxiliary)
    return phases

def reader_module():
    spec = importlib.util.spec_from_file_location('_entity_transform_saved_reader',EX/'verify-created-save.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def payload(reader,path):
    data = Path(path).read_bytes()
    header = reader.builder.read_header(data)
    require(header.file_type == 2 and header.version == 1 and header.file_size == 20+header.content_length and len(data) == header.file_size+4,'GIL_CONTAINER_INVALID')
    return data[20:-4]

def preserve_geometry(reader, left, right, mask):
    def component(entity):
        entries = [item for wire,item,_ in reader.fields(entity,6) if wire == 2 and reader.scalar(item,1) == 1]
        require(len(entries) == 1,'EXACTLY_ONE_TRANSFORM_COMPONENT_REQUIRED')
        return entries[0]
    a,b = component(left),component(right)
    strip = lambda data,numbers: b''.join(raw for n,w,item,raw in reader.builder.raw.spans(data) if n not in numbers)
    def non_transform(entity):
        return b''.join(raw for n,w,item,raw in reader.builder.raw.spans(entity) if not (n == 6 and w == 2 and reader.scalar(item,1) == 1))
    require(non_transform(left) == non_transform(right),'OTHER_ENTITY_FIELDS_CHANGED')
    require(strip(a,{11}) == strip(b,{11}),'TRANSFORM_WRAPPER_CHANGED')
    ta,tb = reader.one(a,11),reader.one(b,11)
    changed = {n for n in (1,2,3) if mask & (1 << (n-1))}
    require(strip(ta,changed) == strip(tb,changed),'UNREQUESTED_TRANSFORM_FIELDS_CHANGED')

def unclassified_root46(reader,before,after):
    """Report the observed opaque pair, without declaring its domain preserved."""
    def side(body):
        values=reader.fields(body,46)
        require(len(values)<=1,'UNCLASSIFIED_ROOT46_SHAPE_CHANGED')
        if not values:return dict(present=False,encodedHex='',sha256=hashlib.sha256(b'').hexdigest())
        wire,data,raw=values[0]
        require(wire==2,'UNCLASSIFIED_ROOT46_SHAPE_CHANGED')
        outer=list(reader.builder.raw.spans(data))
        require(len(outer)==1 and outer[0][0:2]==(1,2),'UNCLASSIFIED_ROOT46_SHAPE_CHANGED')
        pair=outer[0][2];fields=list(reader.builder.raw.spans(pair))
        require([(n,w) for n,w,_,_ in fields]==[(1,0),(2,0)],'UNCLASSIFIED_ROOT46_SHAPE_CHANGED')
        return dict(present=True,encodedHex=raw.hex(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                    opaqueUInt64=[reader.scalar(pair,1),reader.scalar(pair,2)])
    return dict(root=46,classification='unclassified-save-difference',meaningVerified=False,
                preserved=False,before=side(before),after=side(after))

def verify_payloads(reader, before, after, rows, level, *, unclassified_differences=None):
    require(reader.scalar(before,1) == reader.scalar(after,1) == level,'SAVED_LEVEL_MISMATCH')
    old,new = reader.entity_records(before),reader.entity_records(after)
    require(set(old) == set(new),'SAVED_ENTITY_SET_CHANGED')
    changed = {row['entityId']:row for row in rows}
    require(set(changed) <= set(old),'SAVED_TARGET_MISSING')
    checks = []
    for eid,left in old.items():
        right = new[eid]
        if eid not in changed:
            require(left == right,'OTHER_ENTITY_CHANGED:'+str(eid))
            continue
        row = changed[eid]
        preserve_geometry(reader,left[0],right[0],row['mask'])
        before_geo,after_geo = reader.target_geometry(left[0]),reader.target_geometry(right[0])
        detail = {}
        for key,native in (('position','localPosition'),('rotation','rotationDegrees'),('scale','scale')):
            require(near(before_geo[key],row['before'][native]),'UNSAVED_BASELINE_GEOMETRY:'+str(eid)+':'+key)
            detail[key] = reader.quantized_check(after_geo[key],row['after'][native],0.0001)
        checks.append(dict(entityId=eid,fields=detail))
    for number in {n for body in (before,after) for n,_,_,_ in reader.builder.raw.spans(body)}:
        if number != 5:
            if number==46 and reader.fields(before,number)!=reader.fields(after,number) and unclassified_differences is not None:
                unclassified_differences.append(unclassified_root46(reader,before,after))
                continue
            require(reader.fields(before,number) == reader.fields(after,number),'OTHER_SAVE_ROOT_CHANGED:'+str(number))
    def root_other(body):
        return b''.join(raw for n,w,item,raw in reader.builder.raw.spans(reader.one(body,5)) if n != 1)
    require(root_other(before) == root_other(after),'OTHER_ROOT5_FIELDS_CHANGED')
    return checks

def verify(run,save_run):
    result = decode(run)
    require(result['ok'] and result['mode'] == 'set' and result['nativeTransactionVerified'],'SUCCESSFUL_TRANSFORM_REQUIRED')
    run,prepared,_ = manifest(run)
    save_run = Path(save_run).resolve()
    import scene_cli
    import native_write_review as reviews
    scene_cli.guarded_runtime_file(save_run/'result.json','NATIVE_SAVE_RESULT')
    reply = read(save_run/'result.json')
    require(reply.get('ok') is True and reply.get('action') == 'save' and not reply.get('outcomeUncertain'),'NATIVE_SAVE_NOT_SUCCESSFUL')
    saved_snapshot,save_prepared = reviews.load_baseline(save_run,'action-after',prepared['levelId'])
    save_built=read(save_run/'build-result.json')
    require(save_built.get('action') == 'save' and save_prepared.get('request') == dict(action='save',levelId=prepared['levelId']),'SAVE_PREPARED_REQUEST_MISMATCH')
    record,_ = ro.load_decoder().read_probe(save_run/'stdout.jsonl')
    require(record.get('action',{}).get('kind') == 2 and record['action'].get('nativeSaveStatus') == 0,'NATIVE_SAVE_RECEIPT_REQUIRED')
    chronology=bind_session_and_time(prepared,save_prepared,save_built,record,read(run/'exit.json'),read(save_run/'exit.json'))
    card=bind_native_card((save_run/'target_config.h').read_text(encoding='utf-8'),record,prepared)
    before_snapshot=ro.load_decoder().decode_snapshot(record)
    accepted=ro.validate_receipt(dict(record,scope='READ_ONLY_CONTEXT_RECEIPT'),before_snapshot,save_prepared,ro.profiles.load_profile())
    require(accepted['ok'],'SAVE_BEFORE_SNAPSHOT_REJECTED:'+','.join(accepted['reasons']))
    same_scene(result['afterSnapshot'],before_snapshot)
    same_scene(before_snapshot,saved_snapshot)
    same_scene(result['afterSnapshot'],saved_snapshot)
    phases=bind_gil_evidence(save_run,prepared,save_built,reply)
    target = next(x for x in prepared['recovery'] if x['target'])
    require(sha(target['backup']) == target['sha256'],'BEFORE_BACKUP_CHANGED')
    level_key = str(prepared['levelId'])
    after_info = phases['after'][level_key]
    after_path = Path(after_info['snapshot'])
    require(sha(after_path) == after_info['sha256'],'AFTER_SAVE_CHANGED')
    require(reply['beforeGils'][level_key]['sha256'] == target['sha256'],'SAVE_BASELINE_MISMATCH')
    protected = []
    formal,_=classify(prepared['recovery'])
    for item in formal.values():
        require(sha(item['backup']) == item['sha256'],'RECOVERY_BACKUP_CHANGED')
        if item['target']:
            continue
        key = Path(item['source']).stem
        require(key in reply['beforeGils'] and key in reply['afterGils'],'PROTECTED_LEVEL_NOT_OBSERVED:'+key)
        require(reply['beforeGils'][key]['sha256'] == reply['afterGils'][key]['sha256'] == item['sha256'],'PROTECTED_LEVEL_CHANGED:'+key)
        require(sha(reply['afterGils'][key]['snapshot']) == item['sha256'],'PROTECTED_SAVE_EVIDENCE_CHANGED:'+key)
        protected.append(int(key))
    reader = reader_module()
    unclassified=[]
    checks = verify_payloads(reader,payload(reader,target['backup']),payload(reader,after_path),result['rows'],prepared['levelId'],
                             unclassified_differences=unclassified)
    return dict(ok=True,run=str(run),saveRun=str(save_run),levelId=prepared['levelId'],called=False,nativeStarted=False,
                outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=True,
                persistentSaveVerified=True,nativeTransformVerified=True,nativeSaveVerified=True,
                rotationStorageUnit='degrees',positionStorageSpace='local',
                verificationScope='requested-transform-and-classified-save-domains',
                savedTransformVerified=True,classifiedOtherSavedFieldsPreserved=True,
                allSaveDomainsVerified=not unclassified,allOtherSavedFieldsPreserved=not unclassified,
                unclassifiedSaveDifferences=unclassified,auxiliaryBackups=phases['auxiliaryBackups'],
                protectedLevels=protected,geometry=checks,reopenVerified=False,visualEffectVerified=False,
                chronology=chronology,nativeSaveCard=card,sameSessionVerified=True,saveBeforeAndAfterSceneVerified=True,
                evidence=dict(transformReceipt=result['rawReceiptSha256'],nativeSaveReceipt=sha(save_run/'stdout.jsonl'),
                              savePrepared=sha(save_run/'prepared.json'),saveHeader=sha(save_run/'target_config.h'),
                              saveResult=sha(save_run/'result.json'),beforeManifest=sha(save_run/'before-gils.json'),afterManifest=sha(save_run/'after-gils.json'),
                              before=target['sha256'],after=sha(after_path)))
