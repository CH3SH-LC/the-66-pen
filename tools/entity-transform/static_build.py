"""Immutable cards for the game's fixed scenery static-conversion operation."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import struct
import sys
from contract import read, write, sha, require, identifier, POSE_KEYS
import build as b

FILES = ('native_static.h', 'native_static.cpp', 'static_build.py',
         'static_receipt.py', 'static-profile.json', 'saved_assembly.py')
KIND = 'entity-static-prepared-v1'
SCOPE = 'FIXED_ENTITY_STATIC_CONVERSION'


def sources(run):
    hashes = b.copy_sources(run)
    for name in FILES:
        source = b.HERE / name
        hashes[str(source)] = sha(source)
        (run / 'candidate-source/entity-transform' / name).write_bytes(source.read_bytes())
    for name in ('game_context_snapshot.h', 'hook_receipt_protocol.h',
                 'hook_receipt.cpp', 'hook_receipt_probe.cpp'):
        path = run / 'candidate-source/native' / name
        text = path.read_text(encoding='utf-8').replace('HR_ACTION == 13', 'HR_ACTION == 16')
        text = text.replace('HR_ACTION == 16 ? 17', 'HR_ACTION == 16 ? 20')
        text = text.replace('../entity-transform/native_transform.h', '../entity-transform/native_static.h')
        text = text.replace('TransformReceipt transform;', 'StaticReceipt staticType;')
        text = text.replace('ExecuteTransform(&receipt->context, &receipt->transform);',
                            'ExecuteStatic(&receipt->context, &receipt->staticType);')
        text = text.replace('receipt->transform', 'receipt->staticType')
        for word in ('Nonce', 'Deadline', 'Protocol', 'Bytes', 'Hex'):
            text = text.replace('transform' + word, 'static' + word)
        path.write_text(text.replace('FIXED_ENTITY_TRANSFORM_ACTION', SCOPE), encoding='utf-8')
    path = run / 'candidate-source/entity-transform/native_transform.cpp'
    path.write_text(b.replace(path.read_text(encoding='utf-8'),
                             '#if HR_ACTION != 13', '#if HR_ACTION != 16'), encoding='utf-8')
    return hashes


def check_saved_scenery(path, ids, templates):
    """Only built-in scenery without authored node graphs may be converted."""
    from saved_assembly import read_entity_records_blob
    data = Path(path).read_bytes()
    rows = {r.entity_id: r for r in read_entity_records_blob(data, str(path))}
    require(len(rows) <= 3000 and set(ids) <= rows.keys(), 'STATIC_SAVED_ENTITY_SET')
    for eid in ids:
        row = rows[eid]
        require(20001000 <= row.tag < 20010000 and row.tag == templates[eid],
                'STATIC_BUILTIN_SCENERY_ONLY')
        graph = row.component(6, 3)
        require(graph is not None and graph.payload.data == b'', 'STATIC_AUTHORED_GRAPH_REFUSED')
        require(row.transform is not None and row.component(5, 1) is not None,
                'STATIC_REQUIRED_COMPONENT_MISSING')
    require(Path(path).read_bytes() == data, 'STATIC_SAVE_CHANGED_DURING_REVIEW')
    return sha(path)


def prepare(args, compile_only=False):
    profile = b.p.load_profile()
    b.p.verify_disk(profile)
    runtime = read(b.HERE / 'runtime-profile.json')
    static = read(b.HERE / 'static-profile.json')
    require(static['imageSha256'] == runtime['imageSha256'] == profile['image']['sha256'],
            'STATIC_IMAGE_DRIFT')
    metadata = b.p.TARGET_IMAGE.parent / 'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(sha(metadata) == static['metadataSha256'] == runtime['metadataSha256'],
            'STATIC_METADATA_DRIFT')
    mode = int(args.mode == 'set')
    if compile_only:
        raw = bytearray(262584 if args.large_scene else 33208)
        struct.pack_into('<II', raw, 0, len(raw), 2 if args.large_scene else 1)
        raw = bytes(raw)
        session = dict(pid=1, tid=1, processCreation=1, threadCreation=1,
                       image=str(b.OUTPUT / 'compile-only.invalid'))
        level, origin, ids = 1, [0., 0., 0.], list(range(1, 129))
        templates = {eid: 20001340 for eid in ids}
    else:
        session, snapshot, raw = b.baseline(args.baseline)
        session = b.p.validate_session(session)
        level, origin = snapshot['levelObservation']['levelId'], snapshot['origin']
        request = read(args.request)
        require(set(request) == {'schemaVersion', 'levelId', 'entities'} and
                request['schemaVersion'] == 1 and request['levelId'] == level,
                'STATIC_REQUEST_FIELDS')
        ids = [identifier(eid) for eid in request['entities']]
        require(1 <= len(ids) <= 128 and len(set(ids)) == len(ids), 'STATIC_BATCH_1_TO_128')
        entities = {r['id']: r for r in snapshot['entities']}
        require(set(ids) <= entities.keys(), 'STATIC_TARGET_NOT_IN_BASELINE')
        templates = {eid: entities[eid]['configId'] for eid in ids}
    empty = {key: [0., 0., 0.] for key in POSE_KEYS}
    empty['scale'] = [1., 1., 1.]
    requests = [dict(entityId=eid, mask=0, requireRoot=0, expectedFrame=0,
                     expectedParent=0, expected=empty, desired=empty) for eid in ids]
    run = b.ro.output_directory(b.OUTPUT)
    (run / 'baseline-snapshot.bin').write_bytes(raw)
    hashes = sources(run)
    hashes[str(metadata)] = static['metadataSha256']
    if compile_only:
        harness = b.HERE/'tests/static_callback_startup.cpp'
        hashes[str(harness)] = sha(harness)
        (run/'candidate-source/entity-transform/callback_startup.cpp').write_bytes(harness.read_bytes())
    backups = []
    if mode and not compile_only:
        require(args.save is not None, 'STATIC_SAVE_BACKUP_REQUIRED')
        reviewed_sha = check_saved_scenery(args.save, ids, templates)
        backups = b.backups(run, args.save, level)
        require(sha(args.save) == reviewed_sha, 'STATIC_SAVE_REVIEW_CHANGED')
    deadline, nonce = b.emit_header(run, profile, runtime, session, raw, level,
                                    requests, 0, not compile_only)
    header = run / 'target_config.h'
    text = b.replace(header.read_text(encoding='utf-8'), '#define HR_ACTION 13ULL',
                     '#define HR_ACTION 16ULL')
    text += '\n#define STATIC_REVIEWED 1\n#define STATIC_WRITE ' + str(mode) + '\n'
    text += '#define STATIC_CODE_RVAS ' + ','.join(x['rva'] for x in static['functions']) + '\n'
    text += '#define STATIC_CODE_BYTES ' + ','.join(
        '{' + ','.join(hex(v) for v in bytes.fromhex(x['head32'])) + '}'
        for x in static['functions']) + '\n'
    text += '#define STATIC_HOTFIX_RVAS ' + ','.join(static['hotfixZeroRvas']) + '\n'
    text += '#define STATIC_USAGE_GROUPS ' + ','.join(static['usageGroups']) + '\n'
    header.write_text(text, encoding='utf-8')
    b.compile_card(run, static_type=True, startup_fixture=compile_only)
    for path, digest in hashes.items():
        require(sha(path) == digest, 'SOURCE_CHANGED_DURING_BUILD')
    prepared = dict(schemaVersion=1, kind=KIND, run=str(run), action=16, receiptVersion=20,
        mode='static-set' if mode else 'static-inspect', launchable=not compile_only,
        compileOnly=compile_only, session=session, levelId=level, origin=origin,
        requests=requests, templateIds=templates, sourceHashes=hashes,
        recovery=backups, deadlineTick=deadline, nonce=str(nonce),
        createdUtc=datetime.now(timezone.utc).isoformat(),
        expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        nativeSnapshotVersion=struct.unpack_from('<I', raw, 4)[0],
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,
        imagePath=str(b.p.TARGET_IMAGE), imageSha256=profile['image']['sha256'])
    prepared['artifacts'] = {x.relative_to(run).as_posix(): sha(x)
                             for x in run.rglob('*') if x.is_file()}
    write(run / 'prepared.json', prepared)
    if not compile_only:
        pins = dict(hashes)
        pins.update({str(run/name): digest for name, digest in prepared['artifacts'].items()})
        pins[str(run/'prepared.json')] = sha(run/'prepared.json')
        pins[str(b.p.TARGET_IMAGE)] = profile['image']['sha256']
        pins.update({x['source']: x['sha256'] for x in backups})
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        wrapper = (b.HERE/'invoke.template.ps1').read_text(encoding='utf-8')
        wrapper = wrapper.replace('FIXED_ENTITY_TRANSFORM_ACTION', SCOPE)
        wrapper = wrapper.replace('entity-transform-build-v1', 'entity-static-build-v1')
        wrapper = wrapper.replace('@@EXPIRES@@', quote(prepared['expiresUtc']))
        wrapper = wrapper.replace('@@PINS@@', ',\n'.join(
            '    @('+quote(path)+','+quote(digest)+')' for path, digest in sorted(pins.items())))
        require('@@' not in wrapper, 'WRAPPER_PLACEHOLDER')
        (run/'invoke-transform.ps1').write_text(wrapper, encoding='utf-8-sig')
    result = dict(ok=True, kind='entity-static-build-v1', run=str(run), compiled=True,
        launchable=not compile_only, mode=prepared['mode'], actionCode=16, receiptVersion=20,
        called=False, nativeStarted=False, outcomeUncertain=False, cleanupVerified=True,
        safeToRelease=True, replayForbidden=False, preparedSha256=sha(run/'prepared.json'),
        wrapperSha256=sha(run/'invoke-transform.ps1') if not compile_only else None)
    write(run/'build-result.json', result)
    return result
