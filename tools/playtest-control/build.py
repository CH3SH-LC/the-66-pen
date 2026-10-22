"""Immutable action17 read-only card; prepare never queries a game process."""
from datetime import datetime,timezone,timedelta
import os,secrets,subprocess,sys
from pathlib import Path
from contract import read,write,sha,require
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
EX=ROOT/'tools/game-executor'
sys.path.insert(0,str(EX))
import build_readonly_profile as ro
import native_profiles as p
OUTPUT=ROOT/'.runtime/playtest-control-20261016/prepared'
OWN=('native_observe.h','native_observe.cpp','runtime-profile.json','contract.py','control_contract.py','build.py','receipt.py','cli.py','invoke.template.ps1')
def replace(text,old,new):
    require(text.count(old)==1,'NATIVE_SOURCE_PATTERN_CHANGED:'+old[:60]);return text.replace(old,new,1)
def copy_sources(run):
    hashes={}
    for folder,origin,names in [('native',EX/'native',ro.SOURCES),('playtest-control',HERE,OWN)]:
        target=run/'candidate-source'/folder;target.mkdir(parents=True)
        for name in names:
            source=origin/name;hashes[str(source)]=sha(source);(target/name).write_bytes(source.read_bytes())
    def edit(name,pairs):
        file=run/'candidate-source/native'/name;text=file.read_text(encoding='utf-8')
        for old,new in pairs:text=replace(text,old,new)
        file.write_text(text,encoding='utf-8')
    edit('hook_receipt_protocol.h',[
        ('#if HR_ACTION\n#include "game_scene_action.h"','#if HR_ACTION == 17\n#include "../playtest-control/native_observe.h"\nstatic_assert(HR_READ_CONTEXT==0 && PLAY_OBSERVE_REVIEWED==1,"independent readonly mode observation");\n#elif HR_ACTION\n#include "game_scene_action.h"'),
        ('#if HR_ACTION\n    GameSceneActionResult action;','#if HR_ACTION == 17\n    PlayReceipt observation;\n#elif HR_ACTION\n    GameSceneActionResult action;'),
        ('static_assert(sizeof(Receipt) == 64, "receipt ABI");\nconstexpr DWORD kReceiptVersion = 1;','#if HR_ACTION == 17\nstatic_assert(sizeof(Receipt)==400,"observation receipt ABI");\nconstexpr DWORD kReceiptVersion=21;\n#else\nstatic_assert(sizeof(Receipt) == 64, "receipt ABI");\nconstexpr DWORD kReceiptVersion = 1;\n#endif')])
    edit('hook_receipt.cpp',[
        ('#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);','#if HR_ACTION == 17\n                    ExecutePlayObservation(&receipt->observation);\n#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')])
    output='''#if HR_ACTION == 17
                std::printf(",\\\"transportOk\\\":true,\\\"observationBytes\\\":%zu,\\\"observationHex\\\":\\\"",sizeof(receipt->observation));
                const auto data=reinterpret_cast<const unsigned char*>(&receipt->observation);
                for(std::size_t i=0;i<sizeof(receipt->observation);++i)std::printf("%02x",static_cast<unsigned>(data[i]));
                std::printf("\\\"");
'''
    edit('hook_receipt_probe.cpp',[
        ('#if HR_ACTION < 1 || HR_ACTION > 3','#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION==17 && PLAY_OBSERVE_REVIEWED==1))'),
        ('#else\n                const bool reportedOk = true;','#elif HR_ACTION == 17\n                const bool reportedOk=receipt->observation.status==0 && receipt->observation.seh==0 && receipt->observation.stage==3;\n#else\n                const bool reportedOk = true;'),
        ('HR_ACTION ? "FIXED_SCENE_ACTION"','HR_ACTION == 17 ? "FIXED_PLAYTEST_OBSERVATION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
        ('#if HR_ACTION\n                std::printf(",\\\"action\\\":',output+'#elif HR_ACTION\n                std::printf(",\\\"action\\\":'),
        ('#if HR_READ_CONTEXT && GS_STRICT_PROFILE\n                // Nonzero exit','#if (HR_READ_CONTEXT && GS_STRICT_PROFILE) || HR_ACTION == 17\n                // Nonzero exit')])
    probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text(encoding='utf-8')
    require('std::memset(receipt, 0, sizeof(*receipt));' in probe and '*receipt = {};' not in probe,'IN_PLACE_RECEIPT_INITIALIZATION_REQUIRED')
    return hashes
def compile_card(run,*,fixture=False):
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';require(vc.is_file(),'MSVC_REQUIRED')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines=['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1',
        common+f'/c "{run/"candidate-source/playtest-control/native_observe.cpp"}" /Fo:"{run/"observe.obj"}"','if errorlevel 1 exit /b 1',
        common+f'/LD "{run/"candidate-source/native/hook_receipt.cpp"}" /Fo:"{run/"hook.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib "{run/"observe.obj"}"','if errorlevel 1 exit /b 1',
        common+f'"{run/"candidate-source/native/hook_receipt_probe.cpp"}" /Fo:"{run/"probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib','if errorlevel 1 exit /b 1']
    if fixture:lines += [common+f'"{run/"candidate-source/playtest-control/callback_fixture.cpp"}" /Fo:"{run/"fixture.obj"}" /Fe:"{run/"callback_fixture.exe"}"','if errorlevel 1 exit /b 1']
    lines+=['exit /b 0']
    (run/'build.cmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'build.log').write_text((result.stdout or '')+(result.stderr or ''),encoding='utf-8');require(result.returncode==0,'BUILD_FAILED:'+str(run/'build.log'))
def prepare(args,*,compile_only=False):
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(runtime['imageSha256']==profile['image']['sha256'] and sha(metadata)==runtime['metadataSha256'],'RUNTIME_SOURCE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session)
        require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE')
        require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.PlayObservation.'+secrets.token_hex(12)))
        require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce)
    header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 17ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n'
    text+='#define PLAY_CODE_RVAS '+','.join(x['rva'] for x in runtime['functions'])+'\n'
    text+='#define PLAY_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in runtime['functions'])+'\n'
    text+='#define PLAY_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n';header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/callback_fixture.cpp';hashes[str(fixture)]=sha(fixture)
        (run/'candidate-source/playtest-control/callback_fixture.cpp').write_bytes(fixture.read_bytes())
    compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    manifest=dict(schemaVersion=1,kind='playtest-control-prepared-v1',run=str(run),action=17,receiptVersion=21,mode='observe',targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'])
    manifest['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',manifest)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in manifest['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('@@EXPIRES@@',quote(manifest['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v1',run=str(run),compiled=True,launchable=not compile_only,actionCode=17,receiptVersion=21,mode='observe',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
