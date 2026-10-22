"""Independent raw ABI validation; neither cached bridge state nor summaries prove a write."""
from pathlib import Path
import struct
import sys
from contract import read, sha, require, decode_extension, same_pose, valid_pose
from build import ROOT, OUTPUT, ro

def guarded_run(value):
    path = Path(value).absolute()
    require(path.is_relative_to(OUTPUT) and path != OUTPUT,'TRANSFORM_RUN_OUTSIDE_PREPARED_ROOT')
    for part in (path,*path.parents):
        require(not part.is_symlink() and not (getattr(part.stat(),'st_file_attributes',0) & 0x400),'REPARSE_PATH_REFUSED')
        if part == ROOT:
            break
    return path.resolve()

def manifest(run):
    run = guarded_run(run)
    built = read(run/'build-result.json')
    prepared = read(run/'prepared.json')
    if prepared.get('kind') == 'entity-physics-prepared-v1':
        from physics_receipt import manifest as physics_manifest
        return physics_manifest(run)
    require(built.get('kind') == 'entity-transform-build-v1' and built.get('preparedSha256') == sha(run/'prepared.json'),'PREPARED_BINDING')
    require(prepared.get('kind') == 'entity-transform-prepared-v1' and prepared.get('run') == str(run) and prepared.get('action') == 13 and prepared.get('receiptVersion') == 17,'PREPARED_CONTRACT')
    for name,digest in prepared['artifacts'].items():
        path = run/name
        require(path.resolve().is_relative_to(run) and sha(path) == digest,'ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:
        require(sha(run/'invoke-transform.ps1') == built['wrapperSha256'],'WRAPPER_CHANGED')
    return run,prepared,built

def same_scene(a,b):
    for key in ('moduleBase','global','currentContext','entityDictionary','contextDictionary'):
        require(a['pointers'][key] == b['pointers'][key],'SCENE_POINTER_CHANGED:'+key)
    require(a['origin'] == b['origin'],'SCENE_ORIGIN_CHANGED')
    require(a['levelObservation'] == b['levelObservation'],'SCENE_LEVEL_CHANGED')
    for key in ('entityVersionBefore','entityVersionAfter','entityCaptured','entityValidEntries','entityRejected'):
        require(a['counts'][key] == b['counts'][key],'SCENE_COUNT_CHANGED:'+key)
    identity = lambda s: [(r['id'],r['owner'],r['config'],r['context'],r['configId'],r['dictionaryKey']) for r in s['entities']]
    require(identity(a) == identity(b),'SCENE_ENTITY_IDENTITY_CHANGED')

def decode(run):
    run,prepared,built = manifest(run)
    if prepared.get('kind') == 'entity-physics-prepared-v1':
        from physics_receipt import decode as physics_decode
        return physics_decode(run)
    require(prepared['launchable'] and not prepared['compileOnly'],'COMPILE_ONLY_CANNOT_HAVE_LIVE_EVIDENCE')
    exit_result = read(run/'exit.json')
    require(exit_result.get('scope') == 'FIXED_ENTITY_TRANSFORM_ACTION','WRAPPER_SCOPE')
    base = dict(run=str(run),levelId=prepared['levelId'],session=prepared['session'],origin=prepared['origin'],mode=prepared['mode'],
                persistentSaveVerified=False,reopenVerified=False,visualEffectVerified=False,replayForbidden=True)
    if exit_result.get('executed') is False:
        require(not (run/'attempt.used').exists(),'NATIVE_ATTEMPT_DESPITE_WRAPPER_REFUSAL')
        return dict(base,ok=False,error=exit_result.get('error') or 'WRAPPER_DID_NOT_EXECUTE',called=False,nativeStarted=False,
                    outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,rows=[])
    require(exit_result.get('executed') is True,'WRAPPER_EXECUTION_UNKNOWN')
    decoder = ro.load_decoder()
    record,_ = decoder.read_probe(run/'stdout.jsonl')
    require(record.get('scope') == 'FIXED_ENTITY_TRANSFORM_ACTION' and record.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    require(record.get('pid') == prepared['session']['pid'] and record.get('tid') == prepared['session']['tid'],'RECEIPT_TARGET_IDENTITY')
    require(record.get('transformNonce') == prepared['nonce'] and record.get('transformDeadline') == str(prepared['deadlineTick']) and record.get('transformProtocol') == 17,'RECEIPT_CARD_IDENTITY')
    raw = bytes.fromhex(record.get('transformHex',''))
    require(record.get('transformBytes') == len(raw),'RECEIPT_BYTES')
    snapshot_raw = (run/'baseline-snapshot.bin').read_bytes()
    extension,after_raw = decode_extension(raw,len(snapshot_raw))
    cleanup = (record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
               record.get('transportOk') is True and record.get('probeElevatedHigh') is True and extension['seh'] == 0 and
               all(not r['openCalled'] or (r['closeCalled'] == r['closed'] == 1 and r['depthAfter'] == r['depthBefore'] and r['pendingAfter'] == 0) for r in extension['rows']))
    called = any(r['called'] or r['openCalled'] for r in extension['rows'])
    result = dict(base,ok=False,called=called,nativeStarted=True,cleanupVerified=cleanup,safeToRelease=cleanup,
                  outcomeUncertain=called,rows=extension['rows'],nativeReceipt=extension,
                  rawReceiptSha256=sha(run/'stdout.jsonl'),error='NATIVE_TRANSFORM_NOT_COMPLETE')
    if (record.get('ok') is not True or extension['status'] or extension['seh'] or extension['stage'] != 5 or
        extension['sceneUnchanged'] != 1 or extension['count'] != extension['completed'] or not cleanup or
        exit_result.get('exitCode') != 0 or exit_result.get('error')):
        return result
    expected_mode = 1 if prepared['mode'] == 'set' else 0
    require(extension['mode'] == expected_mode and len(extension['rows']) == len(prepared['requests']),'RECEIPT_REQUEST_BINDING')
    before = decoder.decode_snapshot(record)
    baseline = decoder.decode_snapshot(dict(snapshotHex=snapshot_raw.hex(),snapshotBytes=len(snapshot_raw)))
    after = decoder.decode_snapshot(dict(snapshotHex=after_raw.hex(),snapshotBytes=len(after_raw)))
    for snapshot in (before,after):
        require(snapshot['status']['value'] == 0 and snapshot['flags']['value'] & 1951 == 1951 and not snapshot['flags']['value'] & 96,'SNAPSHOT_NOT_COMPLETE')
        require(snapshot['counts']['entityRejected'] == 0 and snapshot['counts']['entityCaptured'] == snapshot['counts']['entityValidEntries'],'SNAPSHOT_REJECTED_ENTITIES')
        same_scene(baseline,snapshot)
    owners = {e['id']:int(e['owner'],16) if isinstance(e['owner'],str) else e['owner'] for e in before['entities']}
    for row,q in zip(extension['rows'],prepared['requests']):
        require(row['entityId'] == q['entityId'] and row['mask'] == q['mask'] and row['owner'] == owners[q['entityId']],'ROW_IDENTITY')
        require(row['status'] == 0 and row['readbackVerified'] == 1 and row['uncertain'] == 0,'ROW_INCOMPLETE')
        for name in ('before','desired','after'):
            valid_pose(row[name])
        require(row['frameKind'] in (1,2),'FRAME_KIND_INVALID')
        require(same_pose(row['desired'],row['after'],world=row['frameKind']==1),'READBACK_DIFFERS_FROM_DESIRED')
        row['worldPositionPredicted'] = row['frameKind']==1
        row['worldPositionEvidence'] = 'predicted-and-read-back' if row['frameKind']==1 else 'native-read-back-only'
        if expected_mode:
            require(row['before'] == q['expected'] and same_pose(row['desired'],q['desired']),'PRECONDITION_OR_REQUEST_MISMATCH')
            require(row['parent'] == q['expectedParent'] and row['frameKind'] == q['expectedFrame'] and (not q['requireRoot'] or row['frameKind']==1),'PARENT_FRAME_CHANGED')
            require(row['called'] == q['mask'] and row['stage'] == 8 and row['openCalled'] == row['snapshotCalled'] == row['notifyCalled'] == row['closeCalled'] == row['closed'] == 1,'NATIVE_TRANSACTION_INCOMPLETE')
            require(row['pendingBefore'] == row['pendingAfter'] == 0 and row['pendingSnapshot'] == 1 and row['record'] and row['beforeBlob'],'UNDO_RECORD_MISSING')
        else:
            require(row['called'] == row['mask'] == row['openCalled'] == 0 and same_pose(row['before'],row['after']),'INSPECT_MUTATION')
    result.update(ok=True,error=None,outcomeUncertain=False,afterSnapshot=after,
                  nativeTransformVerified=bool(expected_mode),nativeTransactionVerified=bool(expected_mode))
    return result
