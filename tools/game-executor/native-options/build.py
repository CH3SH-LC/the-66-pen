"""Compile pinned native cards. Live preparation never executes the probe.

The baked baseline payload's snapshot ABI is *derived* from the payload itself (its own
structSize/version plus the 184 + 32*8 + N*64 formula owned by
tools/game-executor/decode_context_snapshot.py) and never typed here: the historical v1
(512 entities / 33208 B) and the large-scene v2 (4096 entities / 262584 B) both build, and
the copy of native/game_context_snapshot.h this build compiles carries a static_assert so a
payload of the other ABI fails the compile instead of being trimmed by
memcpy(&o->expectedScene, TAB_EXPECTED_SNAPSHOT, sizeof(o->expectedScene)).
"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import argparse,hashlib,json,os,secrets,subprocess,sys
HERE=Path(__file__).resolve().parent;EX=HERE.parent;ROOT=EX.parents[1]
sys.path.insert(0,str(EX));import build_readonly_profile as ro;import native_profiles as p
import decode_context_snapshot as snapshot_abi  # owns the snapshot layout formula (dual ABI)
OUT=ROOT/'.runtime/native-options'
GROUPS={'native':(EX/'native',ro.SOURCES),
 'template-authoring':(EX/'template-authoring',('component_attachment.h','component_attachment.cpp','template_catalog_capture.h','template_catalog.h','owner_notification_calls.h','owner_notification_calls.cpp')),
 'native-options':(HERE,('native_tabs.h','native_tabs.cpp'))}

def replace(text,old,new):
    p.require(text.count(old)==1,'SOURCE_PATTERN_CHANGED:'+old[:65]);return text.replace(old,new,1)

SNAPSHOT_ABIS={version:{'version':version,'bytes':size,'maxEntities':counts[0],
  'largeScene':snapshot_abi.SNAPSHOT_LARGE_SCENE[version]}
  for (version,size),counts in snapshot_abi.SNAPSHOT_LAYOUTS.items()}
HISTORICAL_SNAPSHOT_VERSION=min(SNAPSHOT_ABIS)

def derive_abi(raw,what):
    """The ABI the payload itself declares. Named refusals; never a fallback or a resize."""
    try:return snapshot_abi.derive_snapshot_abi(raw,what)
    except snapshot_abi.SnapshotAbiError as error:p.require(False,error.code+':'+error.detail)

# The compiled translation unit must agree with the payload we baked. The guard lives in the
# *copy* of game_context_snapshot.h this build compiles (never in the shared source), and it
# is the only place "the baked bytes" and "sizeof(GameContextSnapshot)" meet.
ABI_GUARD_ANCHOR='void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept;'
ABI_GUARD=\
 ('#if defined(TAB_EXPECTED_SNAPSHOT)\n'
  'static_assert(sizeof(TAB_EXPECTED_SNAPSHOT) == sizeof(GameContextSnapshot),\n'
  '    "TAB_SNAPSHOT_ABI: the baked baseline payload is not this compiled snapshot ABI");\n'
  '#endif\n')

def sources(run):
    hashes={}
    for folder,(origin,names) in GROUPS.items():
        dest=run/'candidate-source'/folder;dest.mkdir(parents=True)
        for name in names:
            path=origin/name;hashes[path.relative_to(ROOT).as_posix()]=p.sha256(path);(dest/name).write_bytes(path.read_bytes())
    def edit(name,changes):
        path=run/'candidate-source/native'/name;text=path.read_text(encoding='utf-8')
        for a,b in changes:text=replace(text,a,b)
        path.write_text(text,encoding='utf-8')
    edit('game_context_snapshot.h',[(
      '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1))',
      '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 12 && defined(TA_TABS_REVIEWED) && TA_TABS_REVIEWED == 1))'),
      (ABI_GUARD_ANCHOR,ABI_GUARD_ANCHOR+'\n'+ABI_GUARD)])
    edit('hook_receipt_protocol.h',[
      ('#if HR_ACTION\n#include "game_scene_action.h"','#if HR_ACTION == 12\n#include "../native-options/native_tabs.h"\n#elif HR_ACTION\n#include "game_scene_action.h"'),
      ('#if HR_ACTION\n    GameSceneActionResult action;','#if HR_ACTION == 12\n    NativeTabReceipt tabs;\n#elif HR_ACTION\n    GameSceneActionResult action;'),
      ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = HR_ACTION == 12 ? 16 : HR_READ_REOPEN_GUARDS')])
    edit('hook_receipt.cpp',[
      ('#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
       '#if HR_ACTION == 12\n                    ExecuteNativeTabAction(&receipt->context, &receipt->tabs);\n#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')])
    output=r'''#if HR_ACTION == 12
                const auto& tab=receipt->tabs;
                std::printf(",\"tabs\":{\"status\":%u,\"stage\":%u,\"sehCode\":%u,\"attempted\":%u,\"completedHosts\":%u,\"failedRva\":%u,\"failedValue\":%u,\"sceneUnchanged\":%u,\"hostStatus\":[%u,%u],\"editCode\":[%u,%u],\"attachCode\":[%u,%u]}",tab.status,tab.stage,tab.sehCode,tab.attempted,tab.completedHosts,tab.failedRva,tab.failedValue,tab.sceneUnchanged,tab.hosts[0].status,tab.hosts[1].status,static_cast<unsigned>(tab.hosts[0].edit.code),static_cast<unsigned>(tab.hosts[1].edit.code),static_cast<unsigned>(tab.hosts[0].attachment.code),static_cast<unsigned>(tab.hosts[1].attachment.code));
                std::printf(",\"tabsBytes\":%zu,\"tabsHex\":\"",sizeof(tab));
                const auto tabBytes=reinterpret_cast<const unsigned char*>(&tab);
                for(std::size_t i=0;i<sizeof(tab);++i)std::printf("%02x",static_cast<unsigned>(tabBytes[i]));
                std::printf("\"");
'''
    edit('hook_receipt_probe.cpp',[
      # 2026-10-16：这条锚点已过期。共享源码 hook_receipt_probe.cpp:133 现在是
      # `    std::memset(receipt, 0, sizeof(*receipt));`（注释说明聚合赋值会在 wmain 里
      # 物化两个完整 Receipt 临时量、超过可执行文件的 1 MiB 栈保留），旧的
      # `    *receipt = {};` 在源码里 0 命中 ⇒ 原先会在 SOURCE_PATTERN_CHANGED 处 fail-closed
      # （由 build_generalized.py 的叶子发现，owner 复核后修）。这里改成**幂等确认**：
      # old == new 时 replace() 只断言「恰好命中一次」，不再改写。
      ('    std::memset(receipt, 0, sizeof(*receipt));',
       '    std::memset(receipt, 0, sizeof(*receipt));'),
      ('#if HR_ACTION < 1 || HR_ACTION > 3','#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 12 && defined(TA_TABS_REVIEWED) && TA_TABS_REVIEWED == 1))'),
      ('#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
       '#if HR_ACTION == 12\n                reportedOk = reportedOk && receipt->tabs.status == 0 && receipt->tabs.sehCode == 0 && receipt->tabs.completedHosts == 2 && receipt->tabs.sceneUnchanged == 1;\n#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status'),
      ('HR_ACTION ? "FIXED_SCENE_ACTION"','HR_ACTION == 12 ? "FIXED_NATIVE_TABS_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
      ('#if HR_ACTION\n                std::printf(",\\\"action\\\":',output+'#elif HR_ACTION\n                std::printf(",\\\"action\\\":')])
    return hashes

def header(run,profile,runtime,session=None,raw=None,abi=None):
    session=session or dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(run/'compile-only.invalid'))
    launchable=raw is not None
    if abi is None:abi=dict(SNAPSHOT_ABIS[HISTORICAL_SNAPSHOT_VERSION],source='compile-default')
    if raw is None:raw=bytes(abi['bytes'])          # compile-only placeholder of this ABI
    abi=derive_abi(raw,abi['source'])
    kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000 if launchable else 1
    message=int(user.RegisterWindowMessageW('Miliastra.NativeTabs.'+secrets.token_hex(12))) if launchable else 0xc001
    # GS_LARGE_SCENE follows the payload's own version, so the compiled struct and the baked
    # bytes are the same ABI (game_context_snapshot.h:75-92).
    ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=secrets.randbits(63)|1,
                   large_scene=bool(abi['largeScene']))
    target=run/'target_config.h';text=target.read_text(encoding='utf-8')
    text=replace(text,'#define HR_ACTION 0ULL','#define HR_ACTION 12ULL');text=replace(text,'#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TA_TABS_REVIEWED 1\n'
    text+='#define TAB_CODE_RVAS '+','.join(x['rva'] for x in runtime['functions'])+'\n'
    text+='#define TAB_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in runtime['functions'])+'\n'
    text+='#define TAB_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n'
    text+='#define TAB_USAGE_GROUPS '+','.join(runtime['usageGroups'])+'\n'
    text+='// snapshot ABI v'+str(abi['version'])+': '+str(abi['bytes'])+' bytes = 184 + 32*8 + '+str(abi['maxEntities'])+'*64 (decode_context_snapshot.py)\n'
    text+='inline constexpr unsigned char kTabExpected[]={\n'+'\n'.join(','.join(str(x) for x in raw[i:i+40])+',' for i in range(0,len(raw),40))+'\n};\n#define TAB_EXPECTED_SNAPSHOT kTabExpected\n'
    target.write_text(text,encoding='utf-8');return deadline,abi

def compile(run):
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';p.require(vc.is_file(),'MSVC_REQUIRED')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    units=[('native','game_context_snapshot'),('template-authoring','component_attachment'),('template-authoring','owner_notification_calls'),('native-options','native_tabs')]
    lines=['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1'];objects=[]
    for folder,name in units:
        obj=run/(name+'.obj');objects.append(obj);lines+=[common+f'/c "{run/"candidate-source"/folder/(name+".cpp")}" /Fo:"{obj}"','if errorlevel 1 exit /b 1']
    lines+=[common+f'/LD "{run/"candidate-source/native/hook_receipt.cpp"}" /Fo:"{run/"hook.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib '+' '.join('"'+str(x)+'"' for x in objects),'if errorlevel 1 exit /b 1',common+f'"{run/"candidate-source/native/hook_receipt_probe.cpp"}" /Fo:"{run/"probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib','exit /b %ERRORLEVEL%']
    (run/'build.cmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    r=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'build.log').write_text(r.stdout+r.stderr,encoding='utf-8');p.require(r.returncode==0,'BUILD_FAILED:'+str(run/'build.log'))

def build(args):
    profile=p.load_profile();p.verify_disk(profile);runtime=json.loads((HERE/'runtime-profile.json').read_text(encoding='utf-8'))
    p.require(runtime['imageSha256']==profile['image']['sha256'],'RUNTIME_IMAGE_DRIFT')
    raw=None;session=None;recovery=None;abi=None
    if args.baseline:
        baseline=Path(args.baseline).resolve();ver=ro.decode_run(baseline)
        p.require(ver['ok'],'BASELINE_NOT_VALID')
        prepared=ro.read_json(baseline/'prepared.json');session=p.validate_session(prepared['session'])
        record,_=ro.load_decoder().read_probe(baseline/'stdout.jsonl');snapshot=ro.load_decoder().decode_snapshot(record)
        p.require(snapshot['levelObservation']['levelId']==1073741842,'WRONG_LEVEL')
        end=datetime.fromisoformat(ro.read_json(baseline/'exit.json')['finishedUtc'].replace('Z','+00:00'))
        p.require(0<=(datetime.now(timezone.utc)-end).total_seconds()<900,'STALE_BASELINE')
        p.require({1077936129,1077936130,1077936131,1077936133} <= {x['id'] for x in snapshot['entities']},'DEMO_ENTITIES_MISSING')
        raw=bytes.fromhex(record['snapshotHex'])
        abi=derive_abi(raw,'baseline snapshot')
        p.require(abi['bytes']==snapshot['structureSize'] and abi['version']==snapshot['version'],
                  'snapshot_abi_unsupported: baseline decodes as v'+str(snapshot['version'])+'/'+str(snapshot['structureSize'])+'B, derivation says v'+str(abi['version'])+'/'+str(abi['bytes'])+'B')
        source=Path.home()/'AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/Beyond_Local_Save_Level/1073741842/1073741842.gil'
        recovery=(source,source.read_bytes())
    if abi is None:
        # Compile-only default: an explicit --snapshot-abi names a reviewed version, otherwise
        # the profile's own default (GS_LARGE_SCENE unset -> the historical v1).
        version=getattr(args,'snapshot_abi_version',None) or HISTORICAL_SNAPSHOT_VERSION
        p.require(version in SNAPSHOT_ABIS,'snapshot_abi_unsupported: v'+str(version))
        abi=dict(SNAPSHOT_ABIS[version],
                 source='--snapshot-abi v'+str(version) if getattr(args,'snapshot_abi_version',None) else 'compile-default')
    # `launchable` is the baseline, not the placeholder: the placeholder only satisfies the
    # compiler's memcpy.
    run=ro.output_directory(OUT/('prepared' if args.baseline else 'candidates'));hashes=sources(run)
    deadline,abi=header(run,profile,runtime,session,raw,abi);compile(run)
    for name,digest in hashes.items():p.require(p.sha256(ROOT/name)==digest,'SOURCE_CHANGED')
    if args.baseline:
        p.validate_session(session);(run/'baseline-snapshot.bin').write_bytes(raw)
        source,content=recovery;(run/'before-1073741842.gil').write_bytes(content);p.require(source.read_bytes()==content,'SOURCE_SAVE_CHANGED')
    result=dict(ok=True,kind='native-tabs-build-v1',run=str(run),compiled=True,launchable=bool(args.baseline),compileOnly=not bool(args.baseline),nativeCalled=False,actionCode=12,receiptVersion=16,deadlineTick=deadline,session=session,sourceHashes=hashes,runtimeSha256=p.sha256(HERE/'runtime-profile.json'),baseline=args.baseline,
                snapshotAbi=dict(abi,compiledAbiGuard='sizeof(TAB_EXPECTED_SNAPSHOT)==sizeof(GameContextSnapshot)'))
    if args.baseline:
        expires=datetime.now(timezone.utc)+timedelta(minutes=8)
        pins={str(ROOT/n):h for n,h in hashes.items()};pins.update({str(x):p.sha256(x) for x in run.rglob('*') if x.is_file()})
        pins[str(source)]=hashlib.sha256(content).hexdigest()
        template=(ROOT/'.runtime/scratch/offline-farming-20261014/ui-root-activation/invoke-resume-ui.template.ps1').read_text(encoding='utf-8')
        template=template.replace('FIXED_UI_Z_RESUME_ACTION','FIXED_NATIVE_TABS_ACTION').replace('fixed-ui-z-resume-build-v1','native-tabs-build-v1')
        start=template.index('    $validation=&');end=template.index('    $stdout=',start);template=template[:start]+template[end:]
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        for key,value in {'@@RUN@@':quote(run),'@@EXPIRES@@':quote(expires.isoformat()),'@@PINS@@':',\n'.join('    @('+quote(x)+','+quote(h)+')' for x,h in sorted(pins.items()))}.items():template=template.replace(key,value)
        p.require('@@' not in template,'WRAPPER_PLACEHOLDER')
        wrapper=run/'invoke-native-tabs.ps1';wrapper.write_text(template,encoding='utf-8-sig');result.update(wrapper=str(wrapper),wrapperSha256=p.sha256(wrapper),expiresUtc=expires.isoformat())
    result['hashes']={x.relative_to(run).as_posix():p.sha256(x) for x in run.rglob('*') if x.is_file()}
    ro.write_json(run/'build-result.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('hashes','sourceHashes')},ensure_ascii=False));return result

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--baseline')
    ap.add_argument('--snapshot-abi',choices=('auto',)+tuple('v%d'%v for v in sorted(SNAPSHOT_ABIS)),default='auto',
                    help='which reviewed snapshot ABI to bake when no --baseline is given '
                         '(--baseline always wins, taken from the snapshot itself); '
                         'auto = the profile default, the historical v1')
    args=ap.parse_args()
    if args.snapshot_abi!='auto':
        p.require(args.baseline is None,'snapshot_abi_unsupported: --baseline decides the ABI itself')
        args.snapshot_abi_version=int(args.snapshot_abi[1:])
    build(args)
