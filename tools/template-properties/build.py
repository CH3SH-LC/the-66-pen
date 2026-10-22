"""Prepare immutable native property cards; never dispatch during preparation."""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
import os,secrets,struct,subprocess,sys
from contract import require,read,write,sha,normalize,merge,LEVEL,MAX_BATCH
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
EX=ROOT/'tools/game-executor'
sys.path.insert(0,str(ROOT/'tools/entity-material'))
import material_build as shared_build
ro,p=shared_build.ro,shared_build.p
baseline,backups=shared_build.baseline,shared_build.backups
OUTPUT=ROOT/'.runtime/template-properties-20261017/prepared'
OWN=('native_properties.h','native_properties.cpp','contract.py','build.py','receipt.py','cli.py','runtime-profile.json','invoke.template.ps1')
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
    for folder, origin, names in (('native', EX/'native',ro.SOURCES), ('template-properties', HERE, OWN), ('template-authoring', EX/'template-authoring', ('template_catalog.h','template_catalog_capture.h','template_catalog_capture.cpp'))):
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
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 24 && defined(PROPERTIES_REVIEWED) && PROPERTIES_REVIEWED == 1))')])
    edit('hook_receipt_protocol.h', [
        ('#if HR_ACTION\n#include "game_scene_action.h"','#if HR_ACTION == 24\n#include "../template-properties/native_properties.h"\n#elif HR_ACTION\n#include "game_scene_action.h"'),
        ('#if HR_ACTION\n    GameSceneActionResult action;','#if HR_ACTION == 24\n    PropertyReceipt properties;\n#elif HR_ACTION\n    GameSceneActionResult action;'),
        ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = HR_ACTION == 24 ? 30 : HR_READ_REOPEN_GUARDS')])
    edit('hook_receipt.cpp', [('#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 24\n                    ExecuteProperties(&receipt->context, &receipt->properties);\n#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')])
    output = r'''#if HR_ACTION == 24
                const auto& tr=receipt->properties;
                std::printf(",\"propertiesNonce\":\"%llu\",\"propertiesDeadline\":\"%llu\",\"propertiesProtocol\":%lu",static_cast<unsigned long long>(receipt->nonce),static_cast<unsigned long long>(receipt->deadline),static_cast<unsigned long>(receipt->version));
                std::printf(",\"propertiesBytes\":%zu,\"propertiesHex\":\"",sizeof(tr));
                const auto trBytes=reinterpret_cast<const unsigned char*>(&tr);
                for(std::size_t i=0;i<sizeof(tr);++i)std::printf("%02x",static_cast<unsigned>(trBytes[i]));
                std::printf("\"");
'''
    probe = run/'candidate-source/native/hook_receipt_probe.cpp'
    probe.write_text(initialize_receipt_in_place(probe.read_text(encoding='utf-8')),encoding='utf-8')
    edit('hook_receipt_probe.cpp', [
        ('#if HR_ACTION < 1 || HR_ACTION > 3','#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 24 && defined(PROPERTIES_REVIEWED) && PROPERTIES_REVIEWED == 1))'),
        ('#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
         '#if HR_ACTION == 24\n                reportedOk = reportedOk && receipt->properties.status == 0 && receipt->properties.seh == 0 && receipt->properties.completed == receipt->properties.count && receipt->properties.sceneUnchanged == 1;\n#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status'),
        ('HR_ACTION ? "FIXED_SCENE_ACTION"','HR_ACTION == 24 ? "FIXED_TEMPLATE_PROPERTIES_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
        ('#if HR_ACTION\n                std::printf(",\\\"action\\\":',output+'#elif HR_ACTION\n                std::printf(",\\\"action\\\":')])
    catalog=run/'candidate-source/template-authoring/template_catalog_capture.cpp'
    catalog.write_text(replace(catalog.read_text(encoding='utf-8'), 'baseline->version != 1', '(baseline->version != 1 && baseline->version != 2)'),encoding='utf-8')
    return hashes

def compile_card(run):
    vswhere = Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc = Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    require(vc.is_file(),'MSVC_REQUIRED')
    common = f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines = ['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1']
    objects = []
    sources=[('native','game_context_snapshot'),('template-properties','native_properties'),('template-authoring','template_catalog_capture')]
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

def state_literal(v):
    raw=v['name'].encode('utf-16-le');chars=struct.unpack('<'+str(len(raw)//2)+'H',raw) if raw else ()
    return '{'+','.join((str(v['iconId'])+'U',str(v['stackLimit'])+'U',str(int(v['isTradeable']))+'U',str(len(chars))+'U','{'+','.join(map(str,chars))+'}'))+'}'

def emit_header(run,profile,runtime,session,raw,requests,mode,launchable):
    version=struct.unpack_from('<I',raw,4)[0]
    require((version,len(raw)) in ((1,33208),(2,262584)),'SNAPSHOT_ABI')
    if launchable:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000
        message=int(user.RegisterWindowMessageW('Miliastra.TemplateProperties.'+secrets.token_hex(12)))
        require(0xc000<=message<=0xffff,'REGISTERED_MESSAGE_REQUIRED')
    else:deadline,message=1,0xc001
    nonce=secrets.randbits(63)|1
    ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce,large_scene=version==2)
    file=run/'target_config.h';value=file.read_text(encoding='utf8')
    value=replace(value,'#define HR_ACTION 0ULL','#define HR_ACTION 24ULL');value=replace(value,'#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')
    value+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PROPERTIES_REVIEWED 1\n'
    value+=f'#define PROPERTIES_LEVEL {LEVEL}U\n#define PROPERTIES_COUNT {len(requests)}U\n#define PROPERTIES_WRITE {mode}U\n'
    value+='#define PROPERTIES_CODE_RVAS '+','.join(x['rva'] for x in runtime['functions'])+'\n'
    value+='#define PROPERTIES_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in runtime['functions'])+'\n'
    value+='#define PROPERTIES_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n#define PROPERTIES_USAGE_GROUPS '+','.join(runtime['usageGroups'])+'\n'
    value+='alignas(8) inline constexpr unsigned char kPropertiesExpected[]={\n'+'\n'.join(','.join(str(v) for v in raw[i:i+48])+',' for i in range(0,len(raw),48))+'\n};\n#define PROPERTIES_EXPECTED kPropertiesExpected\n'
    def req(q):return '{'+','.join([str(q['id'])+'U',str(q['subtype'])+'U',str(q['mask'])+'U','0U',*[str(q[k])+'ULL' for k in ('resource','nameProperty','dataProperty')],state_literal(q['expected']),state_literal(q['desired'])])+'}'
    value+='#define PROPERTIES_REQUESTS '+','.join(req(q) for q in requests)+'\n';file.write_text(value,encoding='utf8');return deadline,nonce

def prepare(args,*,inspect=False,compile_only=False):
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(runtime['imageSha256']==profile['image']['sha256'] and sha(metadata)==runtime['metadataSha256'],'NATIVE_BUILD_DRIFT')
    if compile_only:inspect=args.mode=='inspect'
    request=inspection=None
    empty=dict(iconId=1,stackLimit=9999,isTradeable=True,name='离线样例')
    if compile_only:
        raw=bytearray(262584 if args.large_scene else 33208);struct.pack_into('<II',raw,0,len(raw),2 if args.large_scene else 1);raw=bytes(raw);origin=[0.,0.,0.]
        session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
        requests=[dict(id=0x42000001,subtype=9,mask=0 if inspect else 15,resource=65536,nameProperty=65544,dataProperty=65552,expected=empty,desired=empty)]
    else:
        session,snapshot,raw=baseline(args.baseline);session=p.validate_session(session)
        require(snapshot['levelObservation']['levelId']==LEVEL,'ONLY_AUTHORIZED_LEVEL_1073741843');origin=snapshot['origin']
        if inspect:
            request=normalize(read(args.request))
            requests=[dict(id=q['id'],subtype=9 if q['kind']=='item' else 11,mask=0,resource=0,nameProperty=0,dataProperty=0,expected=empty,desired=empty) for q in request['definitions']]
        else:
            from receipt import decode
            inspection=decode(args.inspection)
            require(inspection['ok'] and inspection['mode']=='inspect','SUCCESSFUL_INSPECTION_REQUIRED')
            finished=datetime.fromisoformat(read(Path(args.inspection)/'exit.json')['finishedUtc'].replace('Z','+00:00'))
            require(0<=(datetime.now(timezone.utc)-finished).total_seconds()<900,'INSPECTION_EXPIRED')
            require(inspection['session']==session and inspection['levelId']==LEVEL and inspection['origin']==origin,'INSPECTION_SESSION_CHANGED')
            request=normalize(read(args.request));requests=merge(request,{r['id']:r for r in inspection['rows']})
            for q in requests:
                if q['mask']&2:require(q['desired']['iconId'] in inspection['nativeReceipt']['itemIcons' if q['subtype']==9 else 'currencyIcons'],'ICON_NOT_IN_NATIVE_CATEGORY')
    run=ro.output_directory(OUTPUT);(run/'baseline-snapshot.bin').write_bytes(raw)
    recovery=backups(run,args.save,LEVEL) if not inspect and not compile_only else []
    if request is not None:write(run/'request.json',request)
    hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    for source in (EX/'build_readonly_profile.py',EX/'native_profiles.py',ROOT/'tools/editor-bridge/elevated-request.py',ROOT/'tools/editor-bridge/elevated-runner.ps1',ROOT/'tools/entity-material/material_build.py',ROOT/'tools/entity-material/material_contract.py',ROOT/'tools/entity-material/material_recovery.py'):
        hashes[str(source)]=sha(source)
    deadline,nonce=emit_header(run,profile,runtime,session,raw,requests,0 if inspect else 1,not compile_only)
    compile_card(run)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    prepared=dict(schemaVersion=1,kind='template-properties-prepared-v1',run=str(run),action=24,receiptVersion=30,mode='inspect' if inspect else 'set',launchable=not compile_only,compileOnly=compile_only,session=session,levelId=LEVEL,origin=origin,requests=requests,recovery=recovery,baseline=str(Path(args.baseline).resolve()) if not compile_only else None,inspection=str(Path(args.inspection).resolve()) if inspection else None,inspectionRawSha256=inspection['rawReceiptSha256'] if inspection else None,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],nativeSnapshotVersion=struct.unpack_from('<I',raw,4)[0])
    prepared['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',prepared)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/n):v for n,v in prepared['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256'];pins.update({x['source']:x['sha256'] for x in recovery})
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf8').replace('@@EXPIRES@@',quote(prepared['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(a)+','+quote(b)+')' for a,b in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-properties.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='template-properties-build-v1',run=str(run),compiled=True,launchable=not compile_only,mode=prepared['mode'],actionCode=24,receiptVersion=30,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,persistentSaveVerified=False,playerDisplayVerified=False,replayForbidden=False,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-properties.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result

