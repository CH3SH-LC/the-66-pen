"""Build immutable action 13 cards. This module never dispatches a card."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
from contract import require, read, write, sha, identifier, normalize, merge, POSE_KEYS
from recovery import classify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EX = ROOT / 'tools/game-executor'
sys.path.insert(0, str(EX))
import build_readonly_profile as ro
import native_profiles as p

OUTPUT = ROOT / '.runtime/map-foundation-20261015/transform/prepared'
OWN = ('native_transform.h','native_transform.cpp','runtime-profile.json','contract.py','recovery.py','build.py','receipt.py','save_verify.py','cli.py','invoke.template.ps1')

def replace(text, old, new):
    require(text.count(old) == 1, 'NATIVE_SOURCE_PATTERN_CHANGED:' + old[:60])
    return text.replace(old,new,1)

def initialize_receipt_in_place(text):
    """Accept either known shared source revision, never stack-construct Receipt."""
    legacy = '    *receipt = {};'
    direct = '    std::memset(receipt, 0, sizeof(*receipt));'
    require(text.count(legacy) + text.count(direct) == 1, 'RECEIPT_INITIALIZATION_PATTERN_CHANGED')
    return text.replace(legacy, direct, 1)

def copy_sources(run):
    hashes = {}
    for folder, origin, names in (('native', EX/'native',ro.SOURCES), ('entity-transform', HERE, OWN)):
        target = run/'candidate-source'/folder
        target.mkdir(parents=True)
        for name in names:
            source = origin/name
            hashes[str(source)] = sha(source)
            (target/name).write_bytes(source.read_bytes())
    def edit(name, changes):
        file = run/'candidate-source/native'/name
        value = file.read_text(encoding='utf-8')
        for old,new in changes:
            value = replace(value,old,new)
        file.write_text(value,encoding='utf-8')
    edit('game_context_snapshot.h', [(
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1))',
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 13 && defined(TRANSFORM_REVIEWED) && TRANSFORM_REVIEWED == 1))')])
    edit('hook_receipt_protocol.h', [
        ('#if HR_ACTION\n#include "game_scene_action.h"','#if HR_ACTION == 13\n#include "../entity-transform/native_transform.h"\n#elif HR_ACTION\n#include "game_scene_action.h"'),
        ('#if HR_ACTION\n    GameSceneActionResult action;','#if HR_ACTION == 13\n    TransformReceipt transform;\n#elif HR_ACTION\n    GameSceneActionResult action;'),
        ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = HR_ACTION == 13 ? 17 : HR_READ_REOPEN_GUARDS')])
    edit('hook_receipt.cpp', [('#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 13\n                    ExecuteTransform(&receipt->context, &receipt->transform);\n#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')])
    output = r'''#if HR_ACTION == 13
                const auto& tr=receipt->transform;
                std::printf(",\"transformNonce\":\"%llu\",\"transformDeadline\":\"%llu\",\"transformProtocol\":%lu",static_cast<unsigned long long>(receipt->nonce),static_cast<unsigned long long>(receipt->deadline),static_cast<unsigned long>(receipt->version));
                std::printf(",\"transformBytes\":%zu,\"transformHex\":\"",sizeof(tr));
                const auto trBytes=reinterpret_cast<const unsigned char*>(&tr);
                for(std::size_t i=0;i<sizeof(tr);++i)std::printf("%02x",static_cast<unsigned>(trBytes[i]));
                std::printf("\"");
'''
    probe = run/'candidate-source/native/hook_receipt_probe.cpp'
    probe.write_text(initialize_receipt_in_place(probe.read_text(encoding='utf-8')),encoding='utf-8')
    edit('hook_receipt_probe.cpp', [
        ('#if HR_ACTION < 1 || HR_ACTION > 3','#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 13 && defined(TRANSFORM_REVIEWED) && TRANSFORM_REVIEWED == 1))'),
        ('#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
         '#if HR_ACTION == 13\n                reportedOk = reportedOk && receipt->transform.status == 0 && receipt->transform.seh == 0 && receipt->transform.completed == receipt->transform.count && receipt->transform.sceneUnchanged == 1;\n#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status'),
        ('HR_ACTION ? "FIXED_SCENE_ACTION"','HR_ACTION == 13 ? "FIXED_ENTITY_TRANSFORM_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
        ('#if HR_ACTION\n                std::printf(",\\\"action\\\":',output+'#elif HR_ACTION\n                std::printf(",\\\"action\\\":')])
    return hashes

def pose_literal(pose):
    def number(v):
        text = format(v,'.9g')
        return text + ('.0' if '.' not in text and 'e' not in text else '') + 'f'
    return '{'+','.join('{'+','.join(number(v) for v in pose[key])+'}' for key in POSE_KEYS)+'}'

def emit_header(run, profile, runtime, session, raw, level, requests, mode, launchable):
    version = struct.unpack_from('<I',raw,4)[0]
    require((version,len(raw)) in ((1,33208),(2,262584)), 'SNAPSHOT_ABI')
    if launchable:
        kernel,user = p.windows_api()
        deadline = int(kernel.GetTickCount64()) + 600000
        message = int(user.RegisterWindowMessageW('Miliastra.EntityTransform.'+secrets.token_hex(12)))
    else:
        deadline,message = 1,0xc001
    nonce = secrets.randbits(63)|1
    ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce,large_scene=version==2)
    file = run/'target_config.h'
    text = replace(file.read_text(encoding='utf-8'),'#define HR_ACTION 0ULL','#define HR_ACTION 13ULL')
    text = replace(text,'#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')
    text += '\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TRANSFORM_REVIEWED 1\n'
    text += '#define TRANSFORM_LEVEL '+str(level)+'U\n#define TRANSFORM_COUNT '+str(len(requests))+'U\n#define TRANSFORM_WRITE '+str(mode)+'U\n'
    text += '#define TRANSFORM_CODE_RVAS '+','.join(x['rva'] for x in runtime['functions'])+'\n'
    text += '#define TRANSFORM_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in runtime['functions'])+'\n'
    text += '#define TRANSFORM_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n'
    text += '#define TRANSFORM_USAGE_GROUPS '+','.join(runtime['usageGroups'])+'\n'
    text += 'alignas(8) inline constexpr unsigned char kTransformExpected[]={\n'+'\n'.join(','.join(str(v) for v in raw[i:i+48])+',' for i in range(0,len(raw),48))+'\n};\n#define TRANSFORM_EXPECTED kTransformExpected\n'
    text += '#define TRANSFORM_REQUESTS '+','.join('{'+str(q['entityId'])+'U,'+str(q['mask'])+'U,'+str(q['requireRoot'])+'U,'+str(q['expectedFrame'])+'U,'+str(q['expectedParent'])+'ULL,'+pose_literal(q['expected'])+','+pose_literal(q['desired'])+'}' for q in requests)+'\n'
    file.write_text(text,encoding='utf-8')
    return deadline,nonce

def compile_card(run, *, startup_fixture=False, physics=False):
    vswhere = Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc = Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    require(vc.is_file(),'MSVC_REQUIRED')
    common = f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines = ['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1']
    objects = []
    sources=[('native','game_context_snapshot'),('entity-transform','native_transform')]
    if physics:sources.append(('entity-transform','native_physics'))
    for folder,name in sources:
        obj = run/(name+'.obj');objects.append(obj)
        lines += [common+f'/c "{run/"candidate-source"/folder/(name+".cpp")}" /Fo:"{obj}"','if errorlevel 1 exit /b 1']
    lines += [common+f'/LD "{run/"candidate-source/native/hook_receipt.cpp"}" /Fo:"{run/"hook.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib '+' '.join('"'+str(x)+'"' for x in objects),
              'if errorlevel 1 exit /b 1',common+f'"{run/"candidate-source/native/hook_receipt_probe.cpp"}" /Fo:"{run/"probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib',
              'if errorlevel 1 exit /b 1']
    if startup_fixture:
        harness = run/'candidate-source/entity-transform/callback_startup.cpp'
        lines += [common+f'"{harness}" /Fo:"{run/"callback_startup.obj"}" /Fe:"{run/"callback_startup.exe"}" /link User32.lib '+' '.join('"'+str(x)+'"' for x in objects),
                  'if errorlevel 1 exit /b 1']
    lines += ['exit /b 0']
    (run/'build.cmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result = subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'build.log').write_text((result.stdout or '')+(result.stderr or ''),encoding='utf-8')
    require(result.returncode == 0,'BUILD_FAILED:'+str(run/'build.log'))

def baseline(path, *, require_fresh=True):
    folder = Path(path).resolve()
    prepared,built,exit_result = [read(folder/name) for name in ('prepared.json','build-result.json','exit.json')]
    for name,digest in built['hashes'].items():
        require(sha(folder/name) == digest,'BASELINE_ARTIFACT_CHANGED:'+name)
    decoder = ro.load_decoder()
    record,_ = decoder.read_probe(folder/'stdout.jsonl')
    snapshot = decoder.decode_snapshot(record)
    accepted = ro.validate_receipt(record,snapshot,prepared,p.load_profile())
    require(accepted['ok'], 'BASELINE_REJECTED:'+','.join(accepted['reasons']))
    require(exit_result.get('executed') is True and exit_result.get('exitCode') == 0 and not exit_result.get('error'),'BASELINE_EXIT_REJECTED')
    if require_fresh:
        finish = datetime.fromisoformat(exit_result['finishedUtc'].replace('Z','+00:00'))
        require(0 <= (datetime.now(timezone.utc)-finish).total_seconds() < 900,'BASELINE_EXPIRED')
    require(snapshot['levelObservation']['verified'],'LEVEL_NOT_OBSERVED')
    return prepared['session'],snapshot,bytes.fromhex(record['snapshotHex'])

def backups(run, source, level):
    source = Path(source).resolve()
    require(source.name == f'{level}.gil' and source.parent.name == str(level) and source.parent.parent.name == 'Beyond_Local_Save_Level','FORMAL_LEVEL_SAVE_REQUIRED')
    result = []
    target = run/'recovery';target.mkdir()
    # Formal levels and recognized UpgradeBackup files are separately classified.
    # Snapshot every known source before touching the scene. This does not write
    # the installation, formal save, or an existing evidence directory.
    for item in sorted(source.parent.parent.glob('*/*.gil')):
        data = item.read_bytes();copy = target/(item.parent.name+'-'+item.name)
        copy.write_bytes(data)
        require(sha(item) == sha(copy),'SAVE_CHANGED_DURING_BACKUP')
        result.append(dict(source=str(item),backup=str(copy),sha256=sha(copy),target=item==source))
    require(sum(x['target'] for x in result) == 1,'TARGET_SAVE_BACKUP_MISSING')
    formal,auxiliary=classify(result)
    for item in formal.values(): item['sourceKind']='formal-level'
    for item in auxiliary: item['sourceKind']='auxiliary-upgrade-backup'
    return result

def prepare(args, *, inspect=False, compile_only=False):
    profile = p.load_profile();p.verify_disk(profile)
    runtime = read(HERE/'runtime-profile.json')
    require(runtime['imageSha256'] == profile['image']['sha256'],'RUNTIME_IMAGE_DRIFT')
    metadata = p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(sha(metadata) == runtime['metadataSha256'],'RUNTIME_METADATA_DRIFT')
    if compile_only:
        inspect = args.mode == 'inspect'
    mode = 0 if inspect else 1
    empty = {key:[0.,0.,0.] for key in POSE_KEYS};empty['scale']=[1.,1.,1.]
    origin,request,inspection = [0.,0.,0.],None,None
    fixture = getattr(args,'baseline_fixture',None) if compile_only else None
    fixture_provenance = None
    if fixture:
        require(inspect,'BASELINE_FIXTURE_REQUIRES_INSPECT_MODE')
        require(args.entity_id,'BASELINE_FIXTURE_REQUIRES_EXPLICIT_ENTITY_ID')
        require(args.fixture_count == 1,'CAPTURED_FIXTURE_USES_EXPLICIT_ENTITY_IDS')
        # Historical captured evidence is sufficient for a compiler fixture.
        # Never query current process identity, clock, or native state here.
        session,snapshot,raw = baseline(fixture,require_fresh=False)
        level = snapshot['levelObservation']['levelId'];origin = snapshot['origin']
        ids = [identifier(v) for v in args.entity_id]
        require(1 <= len(ids) <= 128 and len(ids) == len(set(ids)),'INSPECT_UNIQUE_BATCH_1_TO_128')
        require(set(ids) <= {e['id'] for e in snapshot['entities']},'TARGET_NOT_IN_BASELINE')
        requests = [dict(entityId=v,mask=0,requireRoot=0,expectedFrame=0,expectedParent=0,expected=empty,desired=empty) for v in ids]
        fixture_provenance = {name:sha(Path(fixture)/name) for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json')}
    elif compile_only:
        require(not args.entity_id,'SYNTHETIC_FIXTURE_DOES_NOT_ACCEPT_ENTITY_IDS')
        require(1 <= args.fixture_count <= 128,'FIXTURE_COUNT_1_TO_128')
        raw = bytearray(262584 if args.large_scene else 33208)
        struct.pack_into('<II',raw,0,len(raw),2 if args.large_scene else 1)
        raw = bytes(raw);level = 1
        session = dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
        requests = [dict(entityId=i+1,mask=0 if inspect else 7,requireRoot=0 if inspect else 1,
                         expectedFrame=0 if inspect else 1,expectedParent=0 if inspect else 1,expected=empty,desired=empty)
                    for i in range(args.fixture_count)]
    else:
        session,snapshot,raw = baseline(args.baseline)
        session = p.validate_session(session)
        level = snapshot['levelObservation']['levelId'];origin = snapshot['origin']
        if inspect:
            ids = [identifier(v) for v in args.entity_id]
            require(1 <= len(ids) <= 128 and len(ids) == len(set(ids)),'INSPECT_UNIQUE_BATCH_1_TO_128')
            requests = [dict(entityId=v,mask=0,requireRoot=0,expectedFrame=0,expectedParent=0,expected=empty,desired=empty) for v in ids]
        else:
            from receipt import decode
            inspection = decode(args.inspection)
            require(inspection['ok'] and inspection['mode'] == 'inspect','SUCCESSFUL_INSPECTION_REQUIRED')
            require(inspection['session'] == session and inspection['levelId'] == level and inspection['origin'] == origin,'INSPECTION_SESSION_CHANGED')
            request = normalize(read(args.request));require(request['levelId'] == level,'REQUEST_LEVEL_MISMATCH')
            requests = merge(request,{r['entityId']:r['after'] for r in inspection['rows']},origin,
                             {r['entityId']:dict(frameKind=r['frameKind'],parent=r['parent']) for r in inspection['rows']})
        require({q['entityId'] for q in requests} <= {e['id'] for e in snapshot['entities']},'TARGET_NOT_IN_BASELINE')
    run = ro.output_directory(OUTPUT)
    (run/'baseline-snapshot.bin').write_bytes(raw)
    recovery = backups(run,args.save,level) if not inspect and not compile_only else []
    if request is not None:
        write(run/'request.json',request)
    hashes = copy_sources(run)
    startup_fixture = compile_only and not fixture
    if startup_fixture:
        harness = HERE/'tests/callback_startup.cpp'
        hashes[str(harness)] = sha(harness)
        (run/'candidate-source/entity-transform/callback_startup.cpp').write_bytes(harness.read_bytes())
    hashes[str(metadata)] = runtime['metadataSha256']
    deadline,nonce = emit_header(run,profile,runtime,session,raw,level,requests,mode,not compile_only)
    compile_card(run,startup_fixture=startup_fixture)
    for source,digest in hashes.items():
        require(sha(source) == digest,'SOURCE_CHANGED_DURING_BUILD')
    manifest = dict(schemaVersion=1,kind='entity-transform-prepared-v1',run=str(run),action=13,receiptVersion=17,
        mode='inspect' if inspect else 'set',launchable=not compile_only,compileOnly=compile_only,
        syntheticStartupFixture=startup_fixture,
        session=session,levelId=level,origin=origin,requests=requests,recovery=recovery,
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,
        baselineFixture=str(Path(fixture).resolve()) if fixture else None,fixtureProvenance=fixture_provenance,
        inspection=str(Path(args.inspection).resolve()) if inspection else None,
        sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],
        createdUtc=datetime.now(timezone.utc).isoformat(),nativeSnapshotVersion=struct.unpack_from('<I',raw,4)[0])
    manifest['artifacts'] = {x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()}
    write(run/'prepared.json',manifest)
    if not compile_only:
        pins = dict(hashes)
        pins.update({str(run/name):digest for name,digest in manifest['artifacts'].items()})
        pins[str(run/'prepared.json')] = sha(run/'prepared.json')
        pins[str(p.TARGET_IMAGE)] = profile['image']['sha256']
        pins.update({x['source']:x['sha256'] for x in recovery})
        quote = lambda x: "'"+str(x).replace("'","''")+"'"
        wrapper = (HERE/'invoke.template.ps1').read_text(encoding='utf-8')
        wrapper = wrapper.replace('@@EXPIRES@@',quote(manifest['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER')
        (run/'invoke-transform.ps1').write_text(wrapper,encoding='utf-8-sig')
    result = dict(ok=True,kind='entity-transform-build-v1',run=str(run),compiled=True,launchable=not compile_only,
        mode=manifest['mode'],actionCode=13,receiptVersion=17,called=False,nativeStarted=False,outcomeUncertain=False,
        cleanupVerified=True,safeToRelease=True,persistentSaveVerified=False,replayForbidden=False,
        preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-transform.ps1') if not compile_only else None)
    write(run/'build-result.json',result)
    return result
