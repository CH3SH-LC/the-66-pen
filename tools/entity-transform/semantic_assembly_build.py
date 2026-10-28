"""Pinned native scene-to-accessory assembly. Preparation never dispatches."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import struct
import sys
from contract import read, write, sha, require, identifier, POSE_KEYS
import build as b

FILES = ('native_assembly.h', 'native_assembly.cpp', 'assembly_build.py',
         'assembly_receipt.py', 'assembly-profile.json', 'semantic_assembly_build.py',
         'semantic_assembly_receipt.py', 'semantic_source_contract.py', 'ownership_contract.py',
         'saved_assembly.py')
KIND = 'entity-semantic-assembly-prepared-v1'
SCOPE = 'FIXED_SEMANTIC_SCENERY_ASSEMBLY'
STONE = {20001319, 20001340, 20003385, 20001334, 20001307}
# Verified native paving pair and grass-topped stone platform used in the avenue.
# These have ordinary static model configuration; all scene, graph, ownership,
# collision, world-pose and batch guards below remain mandatory.
AVENUE_MODELS = {20003420, 20003422, 20001204}
SOURCE_MODELS = STONE | AVENUE_MODELS


def sources(run):
    hashes = b.copy_sources(run)
    for name in FILES:
        source = Path(__file__).resolve().parent / name
        hashes[str(source)] = sha(source)
        (run / 'candidate-source/entity-transform' / name).write_bytes(source.read_bytes())
    for name in ('game_context_snapshot.h', 'hook_receipt_protocol.h',
                 'hook_receipt.cpp', 'hook_receipt_probe.cpp'):
        path = run / 'candidate-source/native' / name
        text = path.read_text(encoding='utf-8').replace('HR_ACTION == 13', 'HR_ACTION == 17')
        text = text.replace('HR_ACTION == 17 ? 17', 'HR_ACTION == 17 ? 21')
        text = text.replace('../entity-transform/native_transform.h', '../entity-transform/native_assembly.h')
        text = text.replace('TransformReceipt transform;', 'AssemblyReceipt assembly;')
        text = text.replace('ExecuteTransform(&receipt->context, &receipt->transform);',
                            'ExecuteAssembly(&receipt->context, &receipt->assembly);')
        text = text.replace('receipt->transform', 'receipt->assembly')
        for word in ('Nonce', 'Deadline', 'Protocol', 'Bytes', 'Hex'):
            text = text.replace('transform' + word, 'assembly' + word)
        path.write_text(text.replace('FIXED_ENTITY_TRANSFORM_ACTION', SCOPE), encoding='utf-8')
    path = run / 'candidate-source/entity-transform/native_transform.cpp'
    path.write_text(b.replace(path.read_text(encoding='utf-8'),
                             '#if HR_ACTION != 13', '#if HR_ACTION != 17'), encoding='utf-8')
    patch_native(run)
    return hashes


def validate_pairs(pairs):
    require(isinstance(pairs, list) and 1 <= len(pairs) <= 64, 'ASSEMBLY_PAIRS_1_TO_64')
    result = []
    for p in pairs:
        require(isinstance(p, dict) and set(p) == {'sourceId', 'hostId'}, 'ASSEMBLY_PAIR_FIELDS')
        result.append({k: identifier(v) for k, v in p.items()})
    src, hosts = [p['sourceId'] for p in result], {p['hostId'] for p in result}
    require(len(set(src)) == len(src) and not set(src) & hosts, 'ASSEMBLY_DUPLICATE_OR_NESTED')
    require(len(set(src) | hosts) <= 128, 'ASSEMBLY_POSE_BATCH_LIMIT')
    return result


from semantic_source_contract import check_saved, patch_native, append_limits

def prepare(args, compile_only=False):
    profile = b.p.load_profile()
    b.p.verify_disk(profile)
    runtime = read(b.HERE / 'runtime-profile.json')
    assembly = read(b.HERE / 'assembly-profile.json')
    require(assembly['imageSha256'] == runtime['imageSha256'] == profile['image']['sha256'],
            'ASSEMBLY_IMAGE_DRIFT')
    metadata = b.p.TARGET_IMAGE.parent / 'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(sha(metadata) == assembly['metadataSha256'] == runtime['metadataSha256'],
            'ASSEMBLY_METADATA_DRIFT')
    mode = int(args.mode == 'set')
    if compile_only:
        raw = bytearray(262584 if args.large_scene else 33208)
        struct.pack_into('<II', raw, 0, len(raw), 2 if args.large_scene else 1)
        raw = bytes(raw)
        session = dict(pid=1, tid=1, processCreation=1, threadCreation=1,
                       image=str(b.OUTPUT / 'compile-only.invalid'))
        level, origin = 1, [0., 0., 0.]
        if getattr(args,'compile_level',None) is not None:
            level = identifier(args.compile_level)
        pairs = [dict(sourceId=i, hostId=128) for i in range(1, 65)]
        templates = {i: 20001340 for i in list(range(1, 65)) + [128]}
    else:
        session, snapshot, raw = b.baseline(args.baseline)
        session = b.p.validate_session(session)
        level, origin = snapshot['levelObservation']['levelId'], snapshot['origin']
        request = read(args.request)
        require(set(request) == {'schemaVersion', 'levelId', 'pairs'} and
                request['schemaVersion'] == 1 and request['levelId'] == level,
                'ASSEMBLY_REQUEST_FIELDS')
        pairs = validate_pairs(request['pairs'])
        entities = {r['id']: r for r in snapshot['entities']}
        ids = {p[k] for p in pairs for k in ('sourceId', 'hostId')}
        require(ids <= entities.keys(), 'ASSEMBLY_TARGET_NOT_IN_BASELINE')
        templates = {eid: entities[eid]['configId'] for eid in sorted(ids)}
        require(args.save is not None, 'ASSEMBLY_SAVE_REVIEW_REQUIRED')
        reviewed_sha = check_saved(args.save, pairs, templates, getattr(args,'ownership',None), level)
    empty = {key: [0., 0., 0.] for key in POSE_KEYS}
    empty['scale'] = [1., 1., 1.]
    requests = [dict(entityId=eid, mask=0, requireRoot=0, expectedFrame=0,
                    expectedParent=0, expected=empty, desired=empty) for eid in sorted(templates)]
    run = b.ro.output_directory(b.OUTPUT)
    (run / 'baseline-snapshot.bin').write_bytes(raw)
    hashes = sources(run)
    if not compile_only and getattr(args,'ownership',None):
        hashes[str(Path(args.ownership).resolve())] = sha(args.ownership)
    hashes[str(metadata)] = assembly['metadataSha256']
    if compile_only:
        harness = b.HERE / 'tests/assembly_callback_startup.cpp'
        hashes[str(harness)] = sha(harness)
        (run / 'candidate-source/entity-transform/callback_startup.cpp').write_bytes(harness.read_bytes())
    backups = b.backups(run, args.save, level) if mode and not compile_only else []
    if not compile_only:
        require(sha(args.save) == reviewed_sha, 'ASSEMBLY_SAVE_REVIEW_CHANGED')
        hashes[str(Path(args.save).resolve())] = reviewed_sha
    deadline, nonce = b.emit_header(run, profile, runtime, session, raw, level, requests, 0, not compile_only)
    header = run / 'target_config.h'
    text = b.replace(header.read_text(encoding='utf-8'), '#define HR_ACTION 13ULL',
                     '#define HR_ACTION 17ULL')
    text += f'\n#define ASSEMBLY_REVIEWED 1\n#define ASSEMBLY_WRITE {mode}\n#define ASSEMBLY_COUNT {len(pairs)}U\n'
    text += '#define ASSEMBLY_PAIRS ' + ','.join(
        '{'+str(p['sourceId'])+'U,'+str(p['hostId'])+'U}' for p in pairs) + '\n'
    text += '#define ASSEMBLY_CODE_RVAS ' + ','.join(x['rva'] for x in assembly['functions']) + '\n'
    text += '#define ASSEMBLY_CODE_BYTES ' + ','.join(
        '{'+','.join(hex(v) for v in bytes.fromhex(x['head32']))+'}' for x in assembly['functions'])+'\n'
    text += '#define ASSEMBLY_HOTFIX_RVAS '+','.join(assembly['hotfixZeroRvas'])+'\n'
    text += '#define ASSEMBLY_USAGE_GROUPS '+','.join(assembly['usageGroups'])+'\n'
    header.write_text(text, encoding='utf-8')
    append_limits(run,pairs,args.save,compile_only)
    b.compile_card(run, assembly=True, startup_fixture=compile_only)
    for path, digest in hashes.items():
        require(sha(path) == digest, 'SOURCE_CHANGED_DURING_BUILD')
    prepared = dict(schemaVersion=1, kind=KIND, run=str(run), action=17, receiptVersion=21,
        mode='assembly-set' if mode else 'assembly-inspect', launchable=not compile_only,
        compileOnly=compile_only, session=session, levelId=level, origin=origin,
        requests=requests, pairs=pairs, templateIds=templates, sourceHashes=hashes,
        recovery=backups, deadlineTick=deadline, nonce=str(nonce),
        createdUtc=datetime.now(timezone.utc).isoformat(),
        expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        nativeSnapshotVersion=struct.unpack_from('<I', raw, 4)[0],
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,
        imagePath=str(b.p.TARGET_IMAGE), imageSha256=profile['image']['sha256'])
    prepared['artifacts'] = {x.relative_to(run).as_posix(): sha(x) for x in run.rglob('*') if x.is_file()}
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
        wrapper = wrapper.replace('entity-transform-build-v1', 'entity-semantic-assembly-build-v1')
        wrapper = wrapper.replace('@@EXPIRES@@', quote(prepared['expiresUtc']))
        wrapper = wrapper.replace('@@PINS@@', ',\n'.join(
            '    @('+quote(path)+','+quote(digest)+')' for path, digest in sorted(pins.items())))
        require('@@' not in wrapper, 'WRAPPER_PLACEHOLDER')
        (run/'invoke-transform.ps1').write_text(wrapper, encoding='utf-8-sig')
    result = dict(ok=True, kind='entity-semantic-assembly-build-v1', run=str(run), compiled=True,
        launchable=not compile_only, mode=prepared['mode'], actionCode=17, receiptVersion=21,
        called=False, nativeStarted=False, outcomeUncertain=False, cleanupVerified=True,
        safeToRelease=True, replayForbidden=False, preparedSha256=sha(run/'prepared.json'),
        wrapperSha256=sha(run/'invoke-transform.ps1') if not compile_only else None)
    write(run/'build-result.json', result)
    return result
