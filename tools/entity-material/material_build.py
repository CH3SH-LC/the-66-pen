"""Build immutable action 22 cards. This module never dispatches a card."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
from material_contract import require, read, write, sha, identifier, normalize, merge, STATE_KEYS, LEVEL, MAX_BATCH, PRIMITIVES
from material_recovery import classify

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EX = ROOT / 'tools/game-executor'
sys.path.insert(0, str(EX))
import build_readonly_profile as ro
import native_profiles as p

OUTPUT = ROOT / '.runtime/entity-material-20261017/prepared'
OWN = ('native_material.h','native_material.cpp','runtime-profile.json','material_contract.py','material_recovery.py','material_build.py','material_receipt.py','cli.py','invoke.template.ps1')

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
    for folder, origin, names in (('native', EX/'native',ro.SOURCES), ('entity-material', HERE, OWN)):
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
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 22 && defined(MATERIAL_REVIEWED) && MATERIAL_REVIEWED == 1))')])
    edit('hook_receipt_protocol.h', [
        ('#if HR_ACTION\n#include "game_scene_action.h"','#if HR_ACTION == 22\n#include "../entity-material/native_material.h"\n#elif HR_ACTION\n#include "game_scene_action.h"'),
        ('#if HR_ACTION\n    GameSceneActionResult action;','#if HR_ACTION == 22\n    MaterialReceipt material;\n#elif HR_ACTION\n    GameSceneActionResult action;'),
        ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = HR_ACTION == 22 ? 28 : HR_READ_REOPEN_GUARDS')])
    edit('hook_receipt.cpp', [('#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 22\n                    ExecuteMaterial(&receipt->context, &receipt->material);\n#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')])
    output = r'''#if HR_ACTION == 22
                const auto& tr=receipt->material;
                std::printf(",\"materialNonce\":\"%llu\",\"materialDeadline\":\"%llu\",\"materialProtocol\":%lu",static_cast<unsigned long long>(receipt->nonce),static_cast<unsigned long long>(receipt->deadline),static_cast<unsigned long>(receipt->version));
                std::printf(",\"materialBytes\":%zu,\"materialHex\":\"",sizeof(tr));
                const auto trBytes=reinterpret_cast<const unsigned char*>(&tr);
                for(std::size_t i=0;i<sizeof(tr);++i)std::printf("%02x",static_cast<unsigned>(trBytes[i]));
                std::printf("\"");
'''
    probe = run/'candidate-source/native/hook_receipt_probe.cpp'
    probe.write_text(initialize_receipt_in_place(probe.read_text(encoding='utf-8')),encoding='utf-8')
    edit('hook_receipt_probe.cpp', [
        ('#if HR_ACTION < 1 || HR_ACTION > 3','#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 22 && defined(MATERIAL_REVIEWED) && MATERIAL_REVIEWED == 1))'),
        ('#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
         '#if HR_ACTION == 22\n                reportedOk = reportedOk && receipt->material.status == 0 && receipt->material.seh == 0 && receipt->material.completed == receipt->material.count && receipt->material.sceneUnchanged == 1;\n#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status'),
        ('HR_ACTION ? "FIXED_SCENE_ACTION"','HR_ACTION == 22 ? "FIXED_ENTITY_MATERIAL_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
        ('#if HR_ACTION\n                std::printf(",\\\"action\\\":',output+'#elif HR_ACTION\n                std::printf(",\\\"action\\\":')])
    return hashes

def state_literal(state):
    values = [str(state['material']), *(str(int(state[k])) for k in ('enableMaterial','coverDecorationMaterial','coverDecorationColor','enableColor')),str(state['argb'])+'U',str(state['blendMode']),str(state['rgb'])]
    number=format(state['alphaPercent'],'.9g')
    values.append(number+('.0' if '.' not in number and 'e' not in number else '')+'f')
    return '{'+','.join(values)+'}'

def emit_header(run,profile,runtime,session,raw,level,requests,mode,launchable):
    version=struct.unpack_from('<I',raw,4)[0]
    require((version,len(raw)) in ((1,33208),(2,262584)),'SNAPSHOT_ABI')
    if launchable:
        kernel,user=p.windows_api()
        deadline=int(kernel.GetTickCount64())+600000
        message=int(user.RegisterWindowMessageW('Miliastra.EntityMaterial.'+secrets.token_hex(12)))
        require(0xc000<=message<=0xffff,'REGISTERED_MESSAGE_REQUIRED')
    else:deadline,message=1,0xc001
    nonce=secrets.randbits(63)|1
    ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce,large_scene=version==2)
    file=run/'target_config.h'
    text=replace(file.read_text(encoding='utf-8'),'#define HR_ACTION 0ULL','#define HR_ACTION 22ULL')
    text=replace(text,'#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define MATERIAL_REVIEWED 1\n'
    text+='#define MATERIAL_LEVEL '+str(level)+'U\n#define MATERIAL_COUNT '+str(len(requests))+'U\n#define MATERIAL_WRITE '+str(mode)+'U\n'
    text+='#define MATERIAL_CODE_RVAS '+','.join(x['rva'] for x in runtime['functions'])+'\n'
    text+='#define MATERIAL_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in runtime['functions'])+'\n'
    text+='#define MATERIAL_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n'
    text+='#define MATERIAL_USAGE_GROUPS '+','.join(runtime['usageGroups'])+'\n'
    text+='alignas(8) inline constexpr unsigned char kMaterialExpected[]={\n'+'\n'.join(','.join(str(v) for v in raw[i:i+48])+',' for i in range(0,len(raw),48))+'\n};\n#define MATERIAL_EXPECTED kMaterialExpected\n'
    text+='#define MATERIAL_REQUESTS '+','.join('{'+str(q['entityId'])+'U,'+str(q['configId'])+'U,'+str(q['mask'])+'U,0U,'+str(q['expectedComponent'])+'ULL,'+state_literal(q['expected'])+','+state_literal(q['desired'])+'}' for q in requests)+'\n'
    file.write_text(text,encoding='utf-8')
    return deadline,nonce

def compile_card(run):
    vswhere = Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc = Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    require(vc.is_file(),'MSVC_REQUIRED')
    common = f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines = ['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1']
    objects = []
    sources=[('native','game_context_snapshot'),('entity-material','native_material')]
    for folder,name in sources:
        obj = run/(name+'.obj');objects.append(obj)
        lines += [common+f'/c "{run/"candidate-source"/folder/(name+".cpp")}" /Fo:"{obj}"','if errorlevel 1 exit /b 1']
    lines += [common+f'/LD "{run/"candidate-source/native/hook_receipt.cpp"}" /Fo:"{run/"hook.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib '+' '.join('"'+str(x)+'"' for x in objects),
              'if errorlevel 1 exit /b 1',common+f'"{run/"candidate-source/native/hook_receipt_probe.cpp"}" /Fo:"{run/"probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib',
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
    profile=p.load_profile();p.verify_disk(profile)
    runtime=read(HERE/'runtime-profile.json')
    require(runtime['imageSha256']==profile['image']['sha256'],'RUNTIME_IMAGE_DRIFT')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(sha(metadata)==runtime['metadataSha256'],'RUNTIME_METADATA_DRIFT')
    if compile_only:inspect=args.mode=='inspect'
    mode=0 if inspect else 1
    empty=dict(material=0,enableMaterial=False,coverDecorationMaterial=False,coverDecorationColor=False,enableColor=False,argb=0xffffffff,blendMode=6700,rgb=0xffffff,alphaPercent=100.)
    request,inspection=None,None
    if compile_only:
        require(1<=args.fixture_count<=MAX_BATCH,'FIXTURE_COUNT_1_TO_32')
        raw=bytearray(262584 if args.large_scene else 33208)
        struct.pack_into('<II',raw,0,len(raw),2 if args.large_scene else 1)
        raw=bytes(raw);level=LEVEL;origin=[0.,0.,0.]
        session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
        requests=[dict(entityId=i+1,configId=PRIMITIVES[0],mask=0 if inspect else 127,expectedComponent=0 if inspect else 65536,expected=empty,desired=empty) for i in range(args.fixture_count)]
    else:
        session,snapshot,raw=baseline(args.baseline)
        session=p.validate_session(session)
        level=snapshot['levelObservation']['levelId'];origin=snapshot['origin']
        require(level==LEVEL,'ONLY_AUTHORIZED_LEVEL_1073741843')
        templates={e['id']:e['configId'] for e in snapshot['entities']}
        if inspect:
            ids=[identifier(v) for v in args.entity_id]
            require(1<=len(ids)<=MAX_BATCH and len(ids)==len(set(ids)),'INSPECT_UNIQUE_BATCH_1_TO_32')
            require(all(templates.get(eid) in PRIMITIVES for eid in ids),'UNREVIEWED_PRIMITIVE_TEMPLATE')
            requests=[dict(entityId=eid,configId=templates[eid],mask=0,expectedComponent=0,expected=empty,desired=empty) for eid in ids]
        else:
            from material_receipt import decode
            inspection=decode(args.inspection)
            require(inspection['ok'] and inspection['mode']=='inspect','SUCCESSFUL_INSPECTION_REQUIRED')
            finished=datetime.fromisoformat(read(Path(args.inspection)/'exit.json')['finishedUtc'].replace('Z','+00:00'))
            require(0<=(datetime.now(timezone.utc)-finished).total_seconds()<900,'INSPECTION_EXPIRED')
            require(inspection['session']==session and inspection['levelId']==level and inspection['origin']==origin,'INSPECTION_SESSION_CHANGED')
            request=normalize(read(args.request))
            requests=merge(request,{r['entityId']:r for r in inspection['rows']})
        require(all(templates.get(q['entityId'])==q['configId'] for q in requests),'TARGET_BASELINE_CHANGED')
    run=ro.output_directory(OUTPUT)
    (run/'baseline-snapshot.bin').write_bytes(raw)
    recovery=backups(run,args.save,level) if not inspect and not compile_only else []
    if request is not None:write(run/'request.json',request)
    hashes=copy_sources(run)
    hashes[str(metadata)]=runtime['metadataSha256']
    # Fixed transport code is part of the reviewed card, including root's current
    # action22 route. Hash now, never reuse an old hard-coded transport digest.
    for path in (EX/'build_readonly_profile.py',EX/'native_profiles.py',ROOT/'tools/editor-bridge/elevated-request.py',ROOT/'tools/editor-bridge/elevated-runner.ps1'):
        hashes[str(path)]=sha(path)
    deadline,nonce=emit_header(run,profile,runtime,session,raw,level,requests,mode,not compile_only)
    compile_card(run)
    for path,digest in hashes.items():require(sha(path)==digest,'SOURCE_CHANGED_DURING_BUILD')
    manifest=dict(schemaVersion=1,kind='entity-material-prepared-v1',run=str(run),action=22,receiptVersion=28,mode='inspect' if inspect else 'set',
        launchable=not compile_only,compileOnly=compile_only,session=session,levelId=level,origin=origin,requests=requests,recovery=recovery,
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,
        inspection=str(Path(args.inspection).resolve()) if inspection else None,
        inspectionRawSha256=inspection['rawReceiptSha256'] if inspection else None,
        sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],createdUtc=datetime.now(timezone.utc).isoformat(),nativeSnapshotVersion=struct.unpack_from('<I',raw,4)[0])
    manifest['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()}
    write(run/'prepared.json',manifest)
    if not compile_only:
        pins=dict(hashes)
        pins.update({str(run/name):digest for name,digest in manifest['artifacts'].items()})
        pins[str(run/'prepared.json')]=sha(run/'prepared.json')
        pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        pins.update({x['source']:x['sha256'] for x in recovery})
        quote=lambda x: "'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8')
        wrapper=wrapper.replace('@@EXPIRES@@',quote(manifest['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER')
        (run/'invoke-material.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='entity-material-build-v1',run=str(run),compiled=True,launchable=not compile_only,mode=manifest['mode'],actionCode=22,receiptVersion=28,
        called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,persistentSaveVerified=False,visualEffectVerified=False,
        replayForbidden=False,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-material.ps1') if not compile_only else None)
    write(run/'build-result.json',result)
    return result
