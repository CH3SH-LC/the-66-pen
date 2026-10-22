"""Immutable read-only Collider cards; no live operation occurs during compilation."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import struct
from contract import read,write,sha,require,identifier,POSE_KEYS
import build as b

FILES=('native_physics.h','native_physics.cpp','physics_build.py','physics_receipt.py','physics-profile.json')
KIND='entity-physics-prepared-v1'
SCOPE='FIXED_ENTITY_PHYSICS_QUERY'

def sources(run):
    hashes=b.copy_sources(run)
    for name in FILES:
        source=b.HERE/name;hashes[str(source)]=sha(source)
        (run/'candidate-source/entity-transform'/name).write_bytes(source.read_bytes())
    for name in ('game_context_snapshot.h','hook_receipt_protocol.h','hook_receipt.cpp','hook_receipt_probe.cpp'):
        target=run/'candidate-source/native'/name
        value=target.read_text(encoding='utf-8').replace('HR_ACTION == 13','HR_ACTION == 15')
        value=value.replace('HR_ACTION == 15 ? 17','HR_ACTION == 15 ? 19')
        value=value.replace('../entity-transform/native_transform.h','../entity-transform/native_physics.h')
        value=value.replace('TransformReceipt transform;','PhysicsReceipt physics;')
        value=value.replace('ExecuteTransform(&receipt->context, &receipt->transform);','ExecutePhysics(&receipt->context, &receipt->physics);')
        value=value.replace('receipt->transform','receipt->physics')
        value=value.replace('transformNonce','physicsNonce').replace('transformDeadline','physicsDeadline').replace('transformProtocol','physicsProtocol')
        value=value.replace('transformBytes','physicsBytes').replace('transformHex','physicsHex').replace('FIXED_ENTITY_TRANSFORM_ACTION',SCOPE)
        target.write_text(value,encoding='utf-8')
    target=run/'candidate-source/entity-transform/native_transform.cpp'
    target.write_text(b.replace(target.read_text(encoding='utf-8'),'#if HR_ACTION != 13','#if HR_ACTION != 15'),encoding='utf-8')
    return hashes

def prepare(args,compile_only=False):
    profile=b.p.load_profile();b.p.verify_disk(profile)
    runtime=read(b.HERE/'runtime-profile.json');physics=read(b.HERE/'physics-profile.json')
    require(physics['imageSha256']==runtime['imageSha256']==profile['image']['sha256'],'PHYSICS_IMAGE_DRIFT')
    metadata=b.p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(sha(metadata)==physics['metadataSha256']==runtime['metadataSha256'],'PHYSICS_METADATA_DRIFT')
    if compile_only:
        raw=bytearray(262584 if args.large_scene else 33208);struct.pack_into('<II',raw,0,len(raw),2 if args.large_scene else 1);raw=bytes(raw)
        session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(b.OUTPUT/'compile-only.invalid'))
        level=1;origin=[0.,0.,0.];reference=1;ids=list(range(1,9));templates={v:1 for v in ids}
    else:
        session,snapshot,raw=b.baseline(args.baseline);session=b.p.validate_session(session)
        level=snapshot['levelObservation']['levelId'];origin=snapshot['origin']
        reference=identifier(args.reference_entity_id);targets=[identifier(x) for x in args.entity_id]
        require(1<=len(targets)<=7 and len(set(targets))==len(targets) and reference not in targets,'PHYSICS_TARGETS_AND_DISTINCT_REFERENCE')
        ids=[reference,*targets];entities={row['id']:row for row in snapshot['entities']}
        require(set(ids)<=entities.keys(),'PHYSICS_TARGET_NOT_IN_BASELINE')
        templates={v:entities[v]['configId'] for v in ids}
        require(len(set(templates.values()))==1,'PHYSICS_REFERENCE_TEMPLATE_MISMATCH')
    expected=None;expected_pins={}
    if not compile_only and args.expected_transform_run:
        from receipt import decode
        prior=decode(args.expected_transform_run)
        require(prior['ok'] and prior['mode']=='set' and prior['session']==session and prior['levelId']==level,'PHYSICS_EXPECTED_TRANSFORM_SESSION')
        by_id={x['entityId']:x['after'] for x in prior['rows']}
        require(set(ids[1:])<=by_id.keys(),'PHYSICS_EXPECTED_TRANSFORM_MISSING_TARGET')
        expected={v:by_id[v] for v in ids[1:]}
        folder=Path(prior['run'])
        expected_pins={str(folder/name):sha(folder/name) for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json')}
    empty={key:[0.,0.,0.] for key in POSE_KEYS};empty['scale']=[1.,1.,1.]
    requests=[dict(entityId=v,mask=0,requireRoot=0,expectedFrame=0,expectedParent=0,expected=empty,desired=empty) for v in ids]
    run=b.ro.output_directory(b.OUTPUT);(run/'baseline-snapshot.bin').write_bytes(raw)
    hashes=sources(run);hashes[str(metadata)]=physics['metadataSha256'];hashes.update(expected_pins)
    if compile_only:
        path=b.HERE/'tests/physics_callback_startup.cpp';hashes[str(path)]=sha(path)
        (run/'candidate-source/entity-transform/callback_startup.cpp').write_bytes(path.read_bytes())
    deadline,nonce=b.emit_header(run,profile,runtime,session,raw,level,requests,0,not compile_only)
    header=run/'target_config.h';value=b.replace(header.read_text(encoding='utf-8'),'#define HR_ACTION 13ULL','#define HR_ACTION 15ULL')
    value+='\n#define PHYSICS_REVIEWED 1\n#define PHYSICS_COLLIDER_USAGE '+physics['colliderUsage']+'U\n#define PHYSICS_COLLIDER_CLASS_SLOT '+physics['colliderClassSlot']+'ULL\n'
    value+='#define PHYSICS_CODE_RVAS '+','.join(x['rva'] for x in physics['functions'])+'\n'
    value+='#define PHYSICS_CODE_BYTES '+','.join('{'+','.join(hex(v) for v in bytes.fromhex(x['head32']))+'}' for x in physics['functions'])+'\n'
    header.write_text(value,encoding='utf-8')
    b.compile_card(run,startup_fixture=compile_only,physics=True)
    for path,digest in hashes.items():require(sha(path)==digest,'SOURCE_CHANGED_DURING_BUILD')
    prepared=dict(schemaVersion=1,kind=KIND,run=str(run),action=15,receiptVersion=19,mode='physics-inspect',launchable=not compile_only,compileOnly=compile_only,
        syntheticStartupFixture=compile_only,session=session,levelId=level,origin=origin,requests=requests,referenceEntityId=reference,templateIds=templates,
        sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        createdUtc=datetime.now(timezone.utc).isoformat(),nativeSnapshotVersion=struct.unpack_from('<I',raw,4)[0],
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,imagePath=str(b.p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],
        expectedTransformPoses=expected,expectedTransformEvidence=expected_pins,
        evidenceScope='six axial Collider.Raycast samples per active non-trigger descendant collider; no player contact, refresh, geometry write or save')
    prepared['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()}
    write(run/'prepared.json',prepared)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in prepared['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(b.p.TARGET_IMAGE)]=profile['image']['sha256']
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(b.HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_ENTITY_TRANSFORM_ACTION',SCOPE).replace('entity-transform-build-v1','entity-physics-build-v1')
        wrapper=wrapper.replace('@@EXPIRES@@',quote(prepared['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-transform.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='entity-physics-build-v1',run=str(run),compiled=True,launchable=not compile_only,mode=prepared['mode'],actionCode=15,receiptVersion=19,
        called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=False,playerContactVerified=False,playerBlockingVerified=False,
        preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-transform.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
