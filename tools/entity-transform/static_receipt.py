"""Independent receipt decoder for static conversion; persistence is a separate check."""
import struct
from contract import read, sha, require, decode_extension, same_pose


def manifest(run):
    from receipt import guarded_run
    run = guarded_run(run)
    prepared, built = read(run/'prepared.json'), read(run/'build-result.json')
    require(prepared.get('kind') == 'entity-static-prepared-v1' and
            prepared.get('action') == 16 and prepared.get('receiptVersion') == 20 and
            prepared.get('run') == str(run), 'STATIC_PREPARED_CONTRACT')
    require(built.get('kind') == 'entity-static-build-v1' and
            built.get('preparedSha256') == sha(run/'prepared.json'), 'STATIC_PREPARED_BINDING')
    for name, digest in prepared['artifacts'].items():
        path = run/name
        require(path.resolve().is_relative_to(run) and sha(path) == digest,
                'STATIC_ARTIFACT_CHANGED:'+name)
    if prepared['launchable']:
        require(sha(run/'invoke-transform.ps1') == built['wrapperSha256'], 'STATIC_WRAPPER_CHANGED')
    return run, prepared, built


def extension(raw, snapshot_size):
    pose_size = 48+128*280+snapshot_size
    require(len(raw) == 48+2*pose_size+128*72, 'STATIC_RECEIPT_SIZE')
    names = ('size', 'version', 'status', 'stage', 'seh', 'count', 'completed',
             'sceneUnchanged', 'mode', 'mutationCalls', 'failedRva', 'failedValue')
    out = dict(zip(names, struct.unpack_from('<12I', raw)))
    require(out['size'] == len(raw) and out['version'] == 1 and
            0 <= out['count'] <= 128 and out['mode'] in (0, 1), 'STATIC_RECEIPT_ABI')
    snapshots = []
    for i, name in enumerate(('beforePose', 'afterPose')):
        block = raw[48+i*pose_size:48+(i+1)*pose_size]
        if block == bytes(pose_size):
            out[name] = dict(status=1, seh=0, rows=[], mode=0)
            snapshots.append(bytes(snapshot_size))
        else:
            out[name], snapshot = decode_extension(block, snapshot_size)
            snapshots.append(snapshot)
    start = 48+2*pose_size
    rows = []
    for i in range(out['count']):
        at = start+i*72
        row = dict(zip(('entityId', 'status', 'beforeFlag', 'afterFlag', 'called', 'returned',
                        'owner', 'component', 'klass', 'attachedBefore', 'attachedAfter',
                        'pendingBefore', 'pendingAfter', 'depthBefore', 'depthAfter'),
                       struct.unpack_from('<6I3Q4I2i', raw, at)))
        rows.append(row)
    require(raw[start+len(rows)*72:] == bytes((128-len(rows))*72), 'STATIC_UNUSED_ROWS')
    out['rows'] = rows
    return out, snapshots


def validate_success(report, requests):
    require(report['status'] == report['seh'] == 0 and report['stage'] == 5 and
            report['completed'] == report['count'] == len(requests) and
            report['sceneUnchanged'] == 1, 'STATIC_INCOMPLETE')
    require(report['mutationCalls'] == (len(requests) if report['mode'] else 0),
            'STATIC_MUTATION_COUNT')
    for name in ('beforePose', 'afterPose'):
        pose = report[name]
        require(pose['status'] == pose['seh'] == pose['mode'] == 0 and
                pose['completed'] == pose['count'] == len(requests) and
                pose['sceneUnchanged'] == 1, 'STATIC_POSE_CAPTURE_INCOMPLETE')
    for row, a, b, request in zip(report['rows'], report['beforePose']['rows'],
                                 report['afterPose']['rows'], requests):
        require(row['entityId'] == a['entityId'] == b['entityId'] == request['entityId'] and
                row['owner'] == a['owner'] == b['owner'], 'STATIC_ENTITY_BINDING')
        require(row['status'] == row['pendingBefore'] == row['pendingAfter'] == 0 and
                row['depthBefore'] == row['depthAfter'] >= 0 and row['component'] and
                row['klass'], 'STATIC_TRANSACTION_INCOMPLETE')
        require(a['unity'] == b['unity'] and a['parent'] == b['parent'] and
                same_pose(a['before'], b['after']), 'STATIC_POSE_CHANGED')
        for pose in (a, b):
            require(pose['status'] == pose['called'] == pose['mask'] ==
                    pose['openCalled'] == 0 and pose['readbackVerified'] == 1,
                    'STATIC_POSE_MUTATION')
        if report['mode']:
            require(row['beforeFlag'] == 0 and row['afterFlag'] == row['called'] ==
                    row['returned'] == 1 and row['attachedAfter'] == 0, 'STATIC_FLAG_NOT_SET')
        else:
            require(row['beforeFlag'] == row['afterFlag'] and
                    row['attachedBefore'] == row['attachedAfter'] and
                    row['called'] == row['returned'] == 0, 'STATIC_INSPECT_MUTATION')


def decode(run):
    from receipt import same_scene
    from build import ro
    run, prepared, built = manifest(run)
    require(prepared['launchable'] and not prepared['compileOnly'], 'STATIC_COMPILE_ONLY')
    end = read(run/'exit.json')
    require(end.get('scope') == 'FIXED_ENTITY_STATIC_CONVERSION', 'STATIC_WRAPPER_SCOPE')
    base = dict(run=str(run), mode=prepared['mode'], levelId=prepared['levelId'],
                session=prepared['session'], replayForbidden=True, persistentSaveVerified=False)
    if end.get('executed') is False:
        require(not (run/'attempt.used').exists(), 'STATIC_ATTEMPT_DESPITE_REFUSAL')
        return dict(base, ok=False, error=end.get('error'), called=False, nativeStarted=False,
                    outcomeUncertain=False, cleanupVerified=True, safeToRelease=True)
    require(end.get('executed') is True, 'STATIC_EXECUTION_UNKNOWN')
    decoder = ro.load_decoder()
    record, _ = decoder.read_probe(run/'stdout.jsonl')
    require(record.get('scope') == 'FIXED_ENTITY_STATIC_CONVERSION' and
            record.get('selfTestOnly') is False, 'STATIC_RECEIPT_SCOPE')
    require(record.get('pid') == prepared['session']['pid'] and
            record.get('tid') == prepared['session']['tid'], 'STATIC_TARGET_IDENTITY')
    require(record.get('staticNonce') == prepared['nonce'] and
            record.get('staticDeadline') == str(prepared['deadlineTick']) and
            record.get('staticProtocol') == 20, 'STATIC_CARD_IDENTITY')
    raw = bytes.fromhex(record.get('staticHex', ''))
    require(record.get('staticBytes') == len(raw), 'STATIC_RAW_BYTES')
    original = (run/'baseline-snapshot.bin').read_bytes()
    report, snapshots = extension(raw, len(original))
    cleanup = (record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and
               record.get('unhooked') is True and record.get('transportOk') is True and
               record.get('probeElevatedHigh') is True and report['seh'] == 0 and
               all(r['called'] == 0 or (r['status'] == r['pendingAfter'] == 0 and
                   r['depthAfter'] == r['depthBefore']) for r in report['rows']))
    result = dict(base, ok=False, called=report['mutationCalls'] > 0, nativeStarted=True,
        outcomeUncertain=report['mutationCalls'] > 0 or not cleanup,
        cleanupVerified=cleanup, safeToRelease=cleanup, nativeReceipt=report,
        rows=report['rows'], rawReceiptSha256=sha(run/'stdout.jsonl'),
        error='STATIC_OPERATION_NOT_COMPLETE')
    if not (record.get('ok') is True and cleanup and end.get('exitCode') == 0 and
            not end.get('error')):
        return result
    require(report['mode'] == int(prepared['mode'] == 'static-set'), 'STATIC_MODE_BINDING')
    validate_success(report, prepared['requests'])
    baseline = decoder.decode_snapshot(dict(snapshotHex=original.hex(), snapshotBytes=len(original)))
    actual = [decoder.decode_snapshot(record)] + [
        decoder.decode_snapshot(dict(snapshotHex=x.hex(), snapshotBytes=len(x))) for x in snapshots]
    for snapshot in actual:
        require(snapshot['status']['value'] == 0 and
                snapshot['flags']['value'] & 1951 == 1951 and
                not snapshot['flags']['value'] & 96, 'STATIC_SCENE_INCOMPLETE')
        same_scene(baseline, snapshot)
    owners = {x['id']: int(x['owner'], 16) if isinstance(x['owner'], str) else x['owner']
              for x in actual[0]['entities']}
    for row in report['rows']:
        require(row['owner'] == owners[row['entityId']], 'STATIC_OWNER_BINDING')
    result.update(ok=True, error=None, outcomeUncertain=False, entityCountPreserved=True,
                  posesPreserved=True, nativeStaticConversionVerified=bool(report['mode']))
    return result
