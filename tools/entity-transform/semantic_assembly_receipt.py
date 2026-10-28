"""Independent binary receipt checks; a successful callback is not a saved asset."""
import math
import struct
from contract import read, sha, require, decode_extension
from semantic_assembly_build import KIND, SCOPE, validate_pairs


def manifest(run):
    from receipt import guarded_run
    run = guarded_run(run)
    p, built = read(run/'prepared.json'), read(run/'build-result.json')
    require(p.get('kind') == KIND and p.get('action') == 17 and p.get('receiptVersion') == 21
            and p.get('run') == str(run), 'ASSEMBLY_PREPARED_CONTRACT')
    validate_pairs(p['pairs'])
    require(built.get('kind') == 'entity-semantic-assembly-build-v1' and
            built.get('preparedSha256') == sha(run/'prepared.json'), 'ASSEMBLY_PREPARED_BINDING')
    for name, digest in p['artifacts'].items():
        path = run/name
        require(path.resolve().is_relative_to(run) and sha(path) == digest, 'ASSEMBLY_ARTIFACT_CHANGED:'+name)
    if p['launchable']:
        require(sha(run/'invoke-transform.ps1') == built['wrapperSha256'], 'ASSEMBLY_WRAPPER_CHANGED')
    return run, p, built


def extension(raw, size):
    pose_size = 48+128*280+size
    legacy_size = 48+pose_size+size+128*152
    require(len(raw) in (legacy_size,legacy_size+88), 'ASSEMBLY_RECEIPT_SIZE')
    names = ('size', 'version', 'status', 'stage', 'seh', 'count', 'completed',
             'sceneUnchanged', 'mode', 'mutationCalls', 'failedRva', 'failedValue')
    out = dict(zip(names, struct.unpack_from('<12I', raw)))
    require(out['size'] == len(raw) and out['version'] == (1 if len(raw)==legacy_size else 2) and
            0 <= out['count'] <= 64 and out['mode'] in (0, 1), 'ASSEMBLY_RECEIPT_ABI')
    block = raw[48:48+pose_size]
    if block == bytes(pose_size):
        out['beforePose'] = dict(status=1, seh=0, rows=[], mode=0)
        before = bytes(size)
    else:
        out['beforePose'], before = decode_extension(block, size)
    after = raw[48+pose_size:48+pose_size+size]
    start = 48+pose_size+size
    rows = []
    names = ('sourceId','hostId','status','called','beforeCount','afterCount',
             'pendingBefore','pendingAfter','depthBefore','depthAfter',
             'source','host','accessory','component')
    for i in range(out['count']):
        at = start+i*152
        row = dict(zip(names, struct.unpack_from('<8I2i4Q', raw, at)))
        for offset, label in ((72, 'before'), (108, 'after')):
            vec = struct.unpack_from('<9f', raw, at+offset)
            row[label] = dict(position=vec[:3], rotation=vec[3:6], scale=vec[6:])
        row['accessoryId'], row['modelId'] = struct.unpack_from('<2I', raw, at+144)
        rows.append(row)
    require(raw[start+len(rows)*152:legacy_size] == bytes((128-len(rows))*152), 'ASSEMBLY_UNUSED_ROWS')
    if out['version']==2:
        names=('manager','record','klass','target','before','function0','function1','function2',
               'count','base','depth','flags','dirty','reserved')
        out['undoDiagnostic']=dict(zip(names,struct.unpack_from('<8Q6I',raw,legacy_size)))
    out['rows'] = rows
    return out, before, after


def quaternion(e):
    x,y,z = [v*math.pi/360 for v in e]
    sx,cx,sy,cy,sz,cz = math.sin(x),math.cos(x),math.sin(y),math.cos(y),math.sin(z),math.cos(z)
    return cy*sx*cz+sy*cx*sz,sy*cx*cz-cy*sx*sz,cy*cx*sz-sy*sx*cz,cy*cx*cz+sy*sx*sz


def same_world(a,b):
    return (all(math.isfinite(v) for q in (a,b) for k in q for v in q[k]) and
        all(abs(x-y) <= .0031 for k in ('position','scale') for x,y in zip(a[k],b[k])) and
        abs(sum(x*y for x,y in zip(quaternion(a['rotation']),quaternion(b['rotation'])))) >= .999999)


def validate_success(o,p):
    require(o['status'] == o['seh'] == 0 and o['stage'] == 5 and
            o['completed'] == o['count'] == len(p['pairs']) and o['sceneUnchanged'] == 1,
            'ASSEMBLY_INCOMPLETE')
    mode = int(p['mode'] == 'assembly-set')
    require(o['mode'] == mode and o['mutationCalls'] == mode*o['count'], 'ASSEMBLY_MUTATION_COUNT')
    if 'undoDiagnostic' in o:
        u=o['undoDiagnostic']
        require(u['reserved'] in (0,2) and (u['reserved']!=2 or
                (mode==1 and u['count']==1 and u['base']==u['depth'] and u['flags']==0)),
                'ASSEMBLY_PREVIOUS_TRANSACTION_NOT_CLOSED')
    pose = o['beforePose']
    require(pose['status'] == pose['seh'] == pose['mode'] == 0 and
            pose['completed'] == pose['count'] == len(p['requests']) and
            pose['sceneUnchanged'] == 1, 'ASSEMBLY_POSE_PREFLIGHT')
    poses = {x['entityId']: x for x in pose['rows']}
    require(set(poses) == {x['entityId'] for x in p['requests']}, 'ASSEMBLY_PREFLIGHT_IDS')
    for r,pair in zip(o['rows'],p['pairs']):
        require(all(r[k] == pair[k] for k in pair), 'ASSEMBLY_PAIR_BINDING')
        require(r['source'] == poses[r['sourceId']]['owner'] and
                r['host'] == poses[r['hostId']]['owner'], 'ASSEMBLY_OWNER_BINDING')
        require(r['status'] == r['pendingBefore'] == r['pendingAfter'] == 0 and
                r['depthBefore'] == r['depthAfter'] >= 0 and r['component'] and
                r['called'] == mode, 'ASSEMBLY_TRANSACTION_INCOMPLETE')
        require(same_world(r['before'],r['after']), 'ASSEMBLY_WORLD_CHANGED')
        require(r['modelId'] == p['templateIds'][str(r['sourceId'])], 'ASSEMBLY_MODEL_BINDING')
        require(r['afterCount'] == r['beforeCount']+mode <= 999, 'ASSEMBLY_COUNT_DELTA')
        require(bool(r['accessory']) == bool(r['accessoryId']) == bool(mode), 'ASSEMBLY_ACCESSORY_MISSING')


def decode(run):
    from receipt import same_scene
    from build import ro
    run,p,built = manifest(run)
    require(p['launchable'] and not p['compileOnly'], 'ASSEMBLY_COMPILE_ONLY')
    end = read(run/'exit.json')
    require(end.get('scope') == SCOPE, 'ASSEMBLY_WRAPPER_SCOPE')
    base = dict(run=str(run), mode=p['mode'], levelId=p['levelId'], session=p['session'],
                replayForbidden=True, persistentSaveVerified=False, reopenVerified=False)
    if end.get('executed') is False:
        require(not (run/'attempt.used').exists(), 'ASSEMBLY_ATTEMPT_DESPITE_REFUSAL')
        return dict(base, ok=False, error=end.get('error'), called=False, nativeStarted=False,
                    outcomeUncertain=False, cleanupVerified=True, safeToRelease=True)
    require(end.get('executed') is True, 'ASSEMBLY_EXECUTION_UNKNOWN')
    decoder = ro.load_decoder()
    record,_ = decoder.read_probe(run/'stdout.jsonl')
    require(record.get('scope') == SCOPE and record.get('selfTestOnly') is False and
            record.get('pid') == p['session']['pid'] and record.get('tid') == p['session']['tid'],
            'ASSEMBLY_TARGET_IDENTITY')
    require(record.get('assemblyNonce') == p['nonce'] and
            record.get('assemblyDeadline') == str(p['deadlineTick']) and
            record.get('assemblyProtocol') == 21, 'ASSEMBLY_CARD_IDENTITY')
    raw = bytes.fromhex(record.get('assemblyHex',''))
    require(record.get('assemblyBytes') == len(raw), 'ASSEMBLY_RAW_BYTES')
    original = (run/'baseline-snapshot.bin').read_bytes()
    o,before,after = extension(raw,len(original))
    cleanup = (record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and
        record.get('unhooked') is True and record.get('transportOk') is True and
        record.get('probeElevatedHigh') is True and o['seh'] == 0 and
        o.get('undoDiagnostic',{}).get('reserved',0)!=1 and
        all(not r['called'] or (r['accessory'] and r['pendingAfter'] == 0 and
             r['depthAfter'] == r['depthBefore']) for r in o['rows']))
    result = dict(base, ok=False, called=o['mutationCalls']>0, nativeStarted=True,
        outcomeUncertain=o['mutationCalls']>0 or not cleanup, cleanupVerified=cleanup,
        safeToRelease=cleanup, nativeReceipt=o, rows=o['rows'], rawReceiptSha256=sha(run/'stdout.jsonl'),
        error='ASSEMBLY_OPERATION_NOT_COMPLETE')
    if not (record.get('ok') is True and cleanup and end.get('exitCode') == 0 and not end.get('error')):
        return result
    validate_success(o,p)
    snap = lambda x: decoder.decode_snapshot(dict(snapshotHex=x.hex(),snapshotBytes=len(x)))
    baseline,pre,post = snap(original),snap(before),snap(after)
    same_scene(baseline,decoder.decode_snapshot(record))
    same_scene(baseline,pre)
    require(post['status']['value'] == 0 and post['flags']['value']&1951 == 1951 and
            not post['flags']['value']&96 and post['origin'] == pre['origin'] and
            post['levelObservation'] == pre['levelObservation'], 'ASSEMBLY_SCENE_IDENTITY')
    for k in ('moduleBase','global','currentContext','entityDictionary','contextDictionary'):
        require(pre['pointers'][k] == post['pointers'][k], 'ASSEMBLY_SCENE_POINTER:'+k)
    removed = {r['sourceId'] for r in o['rows']} if o['mode'] else set()
    identity = lambda r: tuple(r[k] for k in ('id','owner','config','context','configId','dictionaryKey'))
    expected = {r['id']:identity(r) for r in pre['entities'] if r['id'] not in removed}
    actual = {r['id']:identity(r) for r in post['entities']}
    require(expected == actual and len(pre['entities'])-len(post['entities']) == len(removed),
            'ASSEMBLY_SCENE_DELTA')
    result.update(ok=True,error=None,outcomeUncertain=False,worldTransformsPreserved=True,
                  independentEntitiesRemoved=len(removed),accessoryModelsAdded=len(removed))
    return result
