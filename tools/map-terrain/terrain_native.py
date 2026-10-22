"""Build/dispatch one pinned terrain callback. Importing this module is offline."""
from __future__ import annotations
import ctypes
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
from terrain_model import ROOT, MAX_CELLS, require, digest, validate_plan, artifact_path
import terrain_recovery
import terrain_refresh
import terrain_shapes_v3 as shapes

HERE=Path(__file__).resolve().parent
EX=ROOT/'tools/game-executor'
OUT=ROOT/'.runtime/map-foundation-20261015/terrain/prepared'
sys.path.insert(0,str(EX))
import build_readonly_profile as ro
import native_profiles as profiles

HEADER_NAMES=('size version status stage sehCode mutationCalls completed transactionMayBeOpen outcomeUncertain '
              'beforeCount afterCount terrainId manager owner dictionary beforeVersion afterVersion failedKey '
              'failedRva failedValue openCalled snapshotCalled notifyCalled closeCalled snapshotVerified '
              'notificationVerified closeVerified sceneUnchanged captureStable terrainCount constantsValid reserved').split()
RECEIPT_BASE_SIZE=256+48*MAX_CELLS

def validate_request(plan,blob,run=None,dispatch=False):
    if plan.get('schema')=='native-terrain-batch-card-v1':
        import terrain_batch
        return terrain_batch.validate_card(plan,blob,run,dispatch)
    return (terrain_refresh.validate if plan.get('refreshOnly') else validate_plan)(plan,blob)

def replace(text,old,new):
    require(text.count(old)==1,'CANDIDATE_SOURCE_PATTERN_CHANGED:'+old[:60])
    return text.replace(old,new,1)

def write(path,data):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def sources(run,runtime_probe=False,catalog_probe=False):
    hashes={}
    for folder,origin,names in [('native',EX/'native',ro.SOURCES),('map-terrain',HERE,('native_terrain.h','native_terrain.cpp','terrain_runtime.h','terrain_runtime.inc','terrain_rebuild.inc','terrain_catalog.h','terrain_catalog.inc','terrain_shapes_v3.inc'))]:
        dest=run/'candidate-source'/folder;dest.mkdir(parents=True)
        for name in names:
            path=origin/name;hashes[str(path)]=profiles.sha256(path);(dest/name).write_bytes(path.read_bytes())
    def edit(name,changes):
        path=run/'candidate-source/native'/name;text=path.read_text(encoding='utf-8')
        for old,new in changes:text=replace(text,old,new)
        path.write_text(text,encoding='utf-8')
    edit('game_context_snapshot.h',[(
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1))',
        '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 14 && defined(TERRAIN_ACTION_REVIEWED) && TERRAIN_ACTION_REVIEWED == 1))')])
    edit('hook_receipt_protocol.h',[
        ('#if HR_ACTION\n#include "game_scene_action.h"','#if HR_ACTION == 14\n#include "../map-terrain/native_terrain.h"\n#elif HR_ACTION\n#include "game_scene_action.h"'),
        ('#if HR_ACTION\n    GameSceneActionResult action;','#if HR_ACTION == 14\n    TerrainReceipt terrain;\n#elif HR_ACTION\n    GameSceneActionResult action;'),
        ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS','constexpr DWORD kReceiptVersion = HR_ACTION == 14 ? '+('27' if catalog_probe else '20' if runtime_probe else '18')+' : HR_READ_REOPEN_GUARDS')])
    edit('hook_receipt.cpp',[(
        '#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 14\n                    ExecuteTerrainAction(&receipt->context, &receipt->terrain);\n#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')])
    output='''#if HR_ACTION == 14
                std::printf(",\\\"receiptPrefixHex\\\":\\\"");
                const auto prefixBytes=reinterpret_cast<const unsigned char*>(receipt);
                for(std::size_t i=0;i<64;++i)std::printf("%02x",static_cast<unsigned>(prefixBytes[i]));
                std::printf("\\\",\\\"processCreation\\\":%llu,\\\"threadCreation\\\":%llu",static_cast<unsigned long long>(ticks),static_cast<unsigned long long>(threadTicks));
                std::printf(",\\\"terrainBytes\\\":%zu,\\\"terrainHex\\\":\\\"",sizeof(receipt->terrain));
                const auto terrainBytes=reinterpret_cast<const unsigned char*>(&receipt->terrain);
                for(std::size_t i=0;i<sizeof(receipt->terrain);++i)std::printf("%02x",static_cast<unsigned>(terrainBytes[i]));
                std::printf("\\\"");
'''
    edit('hook_receipt_probe.cpp',[
        ('#if HR_ACTION < 1 || HR_ACTION > 3','#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 14 && defined(TERRAIN_ACTION_REVIEWED) && TERRAIN_ACTION_REVIEWED == 1))'),
        ('#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
         '#if HR_ACTION == 14\n                reportedOk = reportedOk && receipt->terrain.status == 0 && receipt->terrain.sehCode == 0 && receipt->terrain.sceneUnchanged == 1 && receipt->terrain.outcomeUncertain == 0;\n#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status'),
        ('HR_ACTION ? "FIXED_SCENE_ACTION"','HR_ACTION == 14 ? "FIXED_TERRAIN_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
        ('#if HR_ACTION\n                std::printf(",\\\"action\\\":',output+'#elif HR_ACTION\n                std::printf(",\\\"action\\\":')])
    probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text(encoding='utf-8')
    require(probe.count('std::memset(receipt, 0, sizeof(*receipt));')==1 and '*receipt = {};' not in probe,
            'SHARED_PROBE_REQUIRES_IN_PLACE_ZERO_INITIALIZATION')
    return hashes

def request_header(run,plan,raw,level_id,inspect_only,catalog_payload=None):
    def rows(name,data):
        return 'inline constexpr TerrainCellRow '+name+'[]={\n'+','.join('{'+','.join(str(x)+'U' for x in r)+'}' for r in (data or [[0]*6]))+'\n};\n'
    text='#pragma once\n#define TERRAIN_ID '+str(plan['terrainId'])+'U\n#define TERRAIN_LEVEL_ID '+str(level_id)+'U\n'
    text+='#define TERRAIN_INSPECT_ONLY '+str(int(inspect_only))+'\n'
    text+='#define TERRAIN_REFRESH_ONLY '+str(int(bool(plan.get('refreshOnly'))))+'\n'
    if 'runtimeKeys' in plan:
        text+='#define TERRAIN_RUNTIME_TARGET_COUNT '+str(len(plan['runtimeKeys']))+'U\n'
        text+='inline constexpr std::uint32_t kTerrainRuntimeKeys[]={'+','.join(str(key)+'U' for key in plan['runtimeKeys'])+'};\n'
    for name,data in [('Before',plan['before']),('After',plan['expected'])]:
        text+=rows('kTerrain'+name,data)+'#define TERRAIN_'+name.upper()+'_COUNT '+str(len(data))+'ULL\n'
    text+='struct TerrainEdit { TerrainCellRow after; bool remove; };\ninline constexpr TerrainEdit kTerrainEdits[]={\n'
    changes=plan['changes'] or [{'after':[0]*6,'op':'set'}]
    text+=','.join('{{'+','.join(str(x)+'U' for x in c['after'])+'},'+('true' if c['op']=='delete' else 'false')+'}' for c in changes)+'\n};\n'
    text+='#define TERRAIN_EDIT_COUNT '+str(len(plan['changes']))+'ULL\n'
    if plan.get('shapeSemantics'):
        require(plan['shapeSemantics']==shapes.binding(),'SHAPE_SEMANTICS_CHANGED')
        shape_materials=shapes.requirements(plan)
        text+='struct TerrainShapeMaterial { std::uint32_t material,slopeTypeMask; bool path; };\n'
        text+='#define TERRAIN_SHAPE_MATERIAL_COUNT '+str(len(shape_materials))+'U\n'
        text+='inline constexpr TerrainShapeMaterial kTerrainShapeMaterials[]={'+','.join(
            '{'+str(r['material'])+'U,'+str(r['slopeTypeMask'])+'U,'+('true' if r['path'] else 'false')+'}' for r in (shape_materials or [dict(material=0,slopeTypeMask=0,path=False)]))+'};\n'
    text+='alignas(8) inline constexpr unsigned char kTerrainExpectedScene[]={\n'
    text+='\n'.join(','.join(str(v) for v in raw[i:i+48])+',' for i in range(0,len(raw),48))+'\n};\n'
    text+='static_assert(sizeof(kTerrainExpectedScene)==sizeof(GameContextSnapshot), "Terrain baseline snapshot ABI");\n'
    if catalog_payload is not None:
        text+='alignas(8) inline constexpr unsigned char kTerrainExpectedCatalog[]={\n'
        text+='\n'.join(','.join(str(v) for v in catalog_payload[i:i+48])+',' for i in range(0,len(catalog_payload),48))+'\n};\n'
        text+='static_assert(sizeof(kTerrainExpectedCatalog)==sizeof(TerrainCatalogReceipt), "Catalog guard ABI");\n'
    (run/'candidate-source/map-terrain/terrain_request.h').write_text(text,encoding='utf-8')

def compile_candidate(run):
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';require(vc.is_file(),'MSVC_REQUIRED')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines=['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1'];objects=[]
    for folder,name in [('native','game_context_snapshot'),('map-terrain','native_terrain')]:
        obj=run/(name+'.obj');objects.append(obj)
        lines+=[common+f'/c "{run/"candidate-source"/folder/(name+".cpp")}" /Fo:"{obj}"','if errorlevel 1 exit /b 1']
    lines+=[common+f'/LD "{run/"candidate-source/native/hook_receipt.cpp"}" /Fo:"{run/"hook.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib '+' '.join('"'+str(o)+'"' for o in objects),
            'if errorlevel 1 exit /b 1',common+f'"{run/"candidate-source/native/hook_receipt_probe.cpp"}" /Fo:"{run/"probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib','exit /b %ERRORLEVEL%']
    (run/'build.cmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'build.log').write_text((result.stdout or '')+(result.stderr or ''),encoding='utf-8')
    require(result.returncode==0,'BUILD_FAILED:'+str(run/'build.log'))

def action_header(run,profile,runtime,session,raw,deadline,message,nonce,large,runtime_probe=False,catalog_probe=False,catalog_guard=False,shapes_guard=False):
    ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce,large_scene=large)
    target=run/'target_config.h';text=target.read_text(encoding='utf-8')
    text=replace(text,'#define HR_ACTION 0ULL','#define HR_ACTION 14ULL')
    text=replace(text,'#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TERRAIN_ACTION_REVIEWED 1\n'
    text+='#define TERRAIN_RUNTIME_PROBE '+str(int(runtime_probe))+'\n'
    text+='#define TERRAIN_CATALOG_PROBE '+str(int(catalog_probe))+'\n#define TERRAIN_CATALOG_GUARD '+str(int(catalog_guard))+'\n'
    text+='#define TERRAIN_SHAPES_GUARD '+str(int(shapes_guard))+'\n'
    if shapes_guard:
        shape_profile=ro.read_json(HERE/'shapes-profile-v3.json')
        require(shape_profile['imageSha256']==profile['image']['sha256'] and shape_profile.get('guardClassifier')=='branch-body-v1','SHAPES_PROFILE_DRIFT')
        text+='#define TERRAIN_SHAPES_RVAS '+','.join(x['rva'] for x in shape_profile['functions'])+'\n'
        text+='#define TERRAIN_SHAPES_HEADS '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in shape_profile['functions'])+'\n'
        text+='#define TERRAIN_SHAPES_HOTFIX '+','.join(shape_profile['hotfixZeroRvas'])+'\n'
        text+='#define TERRAIN_SHAPES_INITIALIZED '+','.join(shape_profile['initializationBooleanRvas'])+'\n'
    if catalog_probe or catalog_guard:
        catalog=ro.read_json(HERE/'catalog-profile.json')
        require(catalog['imageSha256']==profile['image']['sha256'] and catalog.get('guardClassifier')=='branch-body-v1','CATALOG_PROFILE_DRIFT')
        text+='#define TERRAIN_CATALOG_RVAS '+','.join(x['rva'] for x in catalog['functions'])+'\n'
        text+='#define TERRAIN_CATALOG_HEADS '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in catalog['functions'])+'\n'
        text+='#define TERRAIN_CATALOG_HOTFIX '+','.join(catalog['hotfixZeroRvas'])+'\n'
        text+='#define TERRAIN_CATALOG_INITIALIZED '+','.join(catalog['initializationBooleanRvas'])+'\n'
    rebuild=ro.read_json(HERE/'rebuild-profile.json')
    require(rebuild['imageSha256']==profile['image']['sha256'],'REBUILD_IMAGE_DRIFT')
    require(rebuild.get('guardClassifier')=='branch-body-v1' and rebuild['hotfixZeroRvas'] and
            rebuild['initializationBooleanRvas'] and not set(rebuild['hotfixZeroRvas'])&set(rebuild['initializationBooleanRvas']),
            'REBUILD_GUARD_CLASSIFICATION_REQUIRED')
    text+='#define TERRAIN_REBUILD_RVAS '+','.join(x['rva'] for x in rebuild['functions'])+'\n'
    text+='#define TERRAIN_REBUILD_HEADS '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in rebuild['functions'])+'\n'
    text+='#define TERRAIN_REBUILD_HOTFIX '+','.join(rebuild['hotfixZeroRvas'])+'\n'
    text+='#define TERRAIN_REBUILD_INITIALIZED '+','.join(rebuild['initializationBooleanRvas'])+'\n'
    if runtime_probe:
        observation=ro.read_json(HERE/'runtime-observation-profile.json')
        require(observation['imageSha256']==profile['image']['sha256'],'RUNTIME_OBSERVATION_IMAGE_DRIFT')
        text+='#define TERRAIN_RUNTIME_RVAS '+','.join(x['rva'] for x in observation['functions'])+'\n'
        text+='#define TERRAIN_RUNTIME_HEADS '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in observation['functions'])+'\n'
    text+='#define TERRAIN_CODE_RVAS '+','.join(x['rva'] for x in runtime['functions'])+'\n'
    text+='#define TERRAIN_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in runtime['functions'])+'\n'
    hotfix=set(runtime['hotfixZeroRvas']);initialized=set(runtime['initializationBooleanRvas'])
    require(runtime.get('guardClassifier')=='branch-body-v1' and hotfix and initialized and not hotfix&initialized,
            'TERRAIN_GUARD_CLASSIFICATION_REQUIRED')
    text+='#define TERRAIN_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n'
    text+='#define TERRAIN_INITIALIZATION_RVAS '+','.join(runtime['initializationBooleanRvas'])+'\n'
    target.write_text(text,encoding='utf-8')

def compile_check(args):
    """Expired disk-only fixtures; never discovers or opens a process."""
    profile=profiles.load_profile();profiles.verify_disk(profile)
    runtime=ro.read_json(HERE/'runtime-profile.json')
    require(runtime['imageSha256']==profile['image']['sha256'],'TERRAIN_IMAGE_DRIFT')
    runtime_probe=getattr(args,'runtime_probe',False);catalog_probe=getattr(args,'catalog_probe',False)
    catalog_guard=getattr(args,'catalog_guard',False);inspect_only=args.inspect_only or runtime_probe or catalog_probe
    require(not(runtime_probe and catalog_probe) and not(catalog_guard and inspect_only),'CATALOG_MODE_EXCLUSIVE')
    refresh_only=getattr(args,'refresh_only',False)
    require(not(refresh_only and inspect_only),'REFRESH_IS_A_RENDER_MUTATION_NOT_INSPECT')
    shapes_guard=getattr(args,'shapes_guard',False)
    require(not(shapes_guard and (inspect_only or refresh_only)),'SHAPES_GUARD_REQUIRES_WRITE')
    run=ro.output_directory(artifact_path(OUT.parent/'candidates'));sources(run,runtime_probe,catalog_probe)
    session={'pid':1,'tid':1,'processCreation':1,'threadCreation':1,'image':str(run/'compile-only.invalid')}
    raw=bytes(262584 if args.large_scene else 33208)
    plan={'terrainId':1001,'before':[[0x640064,1,0,2,3,4]],'expected':[[0x640064,2,0,2,3,4]],
          'changes':[{'after':[0x640064,2,0,2,3,4],'op':'set'}]}
    if inspect_only:plan={'terrainId':1001,'before':[],'expected':[],'changes':[]}
    if refresh_only:plan.update(refreshOnly=True,expected=plan['before'],changes=[])
    if runtime_probe:plan['runtimeKeys']=[117|(117<<16),118|(117<<16),120|(117<<16),119|(118<<16)]
    if shapes_guard:
        before=[[0x640064+i,1,0,0,0,t<<4] for i,t in enumerate((1,2,3))]
        after=[r[:4]+[1,r[5]] for r in before]
        plan=dict(terrainId=1001,before=before,expected=after,shapeSemantics=shapes.binding(),
                  changes=[dict(op='surface',before=a,after=b) for a,b in zip(before,after)])
    action_header(run,profile,runtime,session,raw,1,0xc001,1,args.large_scene,runtime_probe,catalog_probe,catalog_guard,shapes_guard)
    import terrain_catalog
    request_header(run,plan,raw,1073741900,inspect_only,bytes(terrain_catalog.SIZE) if catalog_guard else None)
    compile_candidate(run)
    result={'ok':True,'kind':'native-terrain-compile-only-v1','run':str(run),'compiled':True,
            'launchable':False,'compileOnly':True,'deadlineTick':1,'nativeSnapshotVersion':2 if args.large_scene else 1,
            'inspectOnly':inspect_only,'runtimeProbe':runtime_probe,'catalogProbe':catalog_probe,'catalogGuard':catalog_guard,'shapesGuard':shapes_guard,'refreshOnly':refresh_only,'called':False,'outcomeUncertain':False}
    write(run/'build-result.json',result)
    return result

def prepare(args):
    profile=profiles.load_profile();profiles.verify_disk(profile)
    runtime=ro.read_json(HERE/'runtime-profile.json')
    require(runtime['imageSha256']==profile['image']['sha256'],'TERRAIN_IMAGE_DRIFT')
    baseline=Path(args.baseline).resolve();check=ro.decode_run(baseline)
    require(check['ok'],'BASELINE_NOT_VALID')
    prepared=ro.read_json(baseline/'prepared.json');session=profiles.validate_session(prepared['session'])
    finished=datetime.fromisoformat(ro.read_json(baseline/'exit.json')['finishedUtc'].replace('Z','+00:00'))
    require(0<=(datetime.now(timezone.utc)-finished).total_seconds()<900,'STALE_BASELINE')
    record,_=ro.load_decoder().read_probe(baseline/'stdout.jsonl');snapshot=ro.load_decoder().decode_snapshot(record)
    level=snapshot['levelObservation'];require(level['verified'] and level['levelId']>0,'LEVEL_NOT_VERIFIED')
    raw=bytes.fromhex(record['snapshotHex']);large=len(raw)==262584
    require(len(raw) in (33208,262584),'SNAPSHOT_ABI')
    runtime_probe=getattr(args,'runtime_probe',False);catalog_probe=getattr(args,'catalog_probe',False)
    require(not(runtime_probe and catalog_probe),'CATALOG_MODE_EXCLUSIVE')
    inspect_only=args.inspect_only or runtime_probe or catalog_probe
    refresh_only=getattr(args,'refresh_only',False)
    require(not(refresh_only and inspect_only),'REFRESH_IS_A_RENDER_MUTATION_NOT_INSPECT')
    require(refresh_only or not getattr(args,'save',None),'SAVE_ARGUMENT_REQUIRES_REFRESH_ONLY')
    require(runtime_probe or not getattr(args,'cells',None),'CELLS_REQUIRES_RUNTIME_PROBE')
    if getattr(args,'batch',None):
        require(not inspect_only and not refresh_only and args.plan is None and args.terrain_id is None,'BATCH_PREPARE_CONTRACT')
        import terrain_batch
        plan=terrain_batch.plan_for_prepare(args,session,snapshot)
        source=terrain_recovery.formal_source(plan['source'],level['levelId']);content=terrain_recovery.stable_bytes(source)
        validate_request(plan,content)
    elif inspect_only:
        require(args.terrain_id is not None and args.plan is None,'INSPECT_REQUIRES_TERRAIN_ID_NO_PLAN')
        plan={'terrainId':args.terrain_id,'before':[],'expected':[],'changes':[]}
        source=None;content=None
        if runtime_probe:
            import terrain_runtime
            require(getattr(args,'cells',None),'RUNTIME_CELLS_REQUIRED')
            plan['runtimeKeys']=terrain_runtime.cells(ro.read_json(Path(args.cells)))
    elif refresh_only:
        require(args.terrain_id is not None and args.plan is None and getattr(args,'save',None),
                'REFRESH_REQUIRES_SAVE_AND_TERRAIN_ID_NO_PLAN')
        source=terrain_recovery.formal_source(args.save,level['levelId']);content=terrain_recovery.stable_bytes(source)
        plan=terrain_refresh.make_plan(content,args.terrain_id,str(source))
    else:
        require(args.plan is not None and args.terrain_id is None,'APPLY_REQUIRES_PLAN_NO_TERRAIN_ID')
        plan=ro.read_json(args.plan);source=terrain_recovery.formal_source(plan['source'],level['levelId'])
        content=terrain_recovery.stable_bytes(source);validate_plan(plan,content)
    run=ro.output_directory(artifact_path(OUT))
    if getattr(args,'_run_started',None):args._run_started(run)
    pins=sources(run,runtime_probe,catalog_probe)
    pins.update(getattr(args,'_batch_pins',{}))
    import terrain_catalog
    catalog_pins,catalog_payload=terrain_catalog.preparation(plan,session,level['levelId']);pins.update(catalog_pins)
    if plan.get('batch'):
        link=Path(plan['batch']['attempt'])/'run.json';pins[str(link)]=profiles.sha256(link)
    kernel,user=profiles.windows_api();deadline=int(kernel.GetTickCount64())+600000
    message=int(user.RegisterWindowMessageW('Miliastra.Terrain.'+secrets.token_hex(12)))
    nonce=secrets.randbits(63)|1
    action_header(run,profile,runtime,session,raw,deadline,message,nonce,large,runtime_probe,catalog_probe,catalog_payload is not None,bool(plan.get('shapeSemantics')))
    request_header(run,plan,raw,level['levelId'],inspect_only,catalog_payload)
    write(run/'request.json',plan);(run/'baseline-snapshot.bin').write_bytes(raw)
    write(run/'baseline-prepared.json',prepared)
    recovery=None
    if source:
        recovery=terrain_recovery.capture(run,source,level['levelId'],digest(content))
        write(run/'recovery.json',recovery)
        (run/'before.gil').write_bytes(content)
        pins.update({item['source']:item['sha256'] for item in recovery['entries']})
    compile_candidate(run)
    profiles.validate_session(session)
    for path,h in pins.items():require(profiles.sha256(Path(path))==h,'SOURCE_CHANGED_DURING_BUILD:'+path)
    for path in [HERE/'runtime-profile.json',HERE/'terrain_native.py',HERE/'terrain_model.py',HERE/'terrain_cli.py',
                 HERE/'terrain_recovery.py',HERE/'terrain_save_verify.py',HERE/'terrain_runtime.py',HERE/'runtime-observation-profile.json',
                 HERE/'terrain_refresh.py',HERE/'rebuild-profile.json',HERE/'terrain_batch.py',HERE/'terrain_catalog.py',HERE/'terrain_calibration.py',HERE/'catalog-profile.json',
                 HERE/'terrain_shapes_v3.py',HERE/'shapes-profile-v3.json']:
        pins[str(path)]=profiles.sha256(path)
    pins.update({str(path):profiles.sha256(path) for path in run.rglob('*') if path.is_file()})
    result={'ok':True,'kind':'native-terrain-build-v1','run':str(run),'launchable':True,'compileOnly':False,
            'compiled':True,'actionCode':14,'receiptVersion':27 if catalog_probe else 20 if runtime_probe else 18,'inspectOnly':inspect_only,'session':session,
            'catalogProbe':catalog_probe,'catalogKind':'native-terrain-catalog-calibration-v1' if catalog_probe else None,
            'catalogGuard':catalog_payload is not None,'materialSource':plan.get('materialSource'),
            'shapeSemantics':plan.get('shapeSemantics'),'shapeGuardVersion':1 if plan.get('shapeSemantics') else None,
            'runtimeProbe':runtime_probe,'runtimeKeys':plan.get('runtimeKeys',[]),
            'runtimeObservationVersion':2 if runtime_probe else None,'refreshOnly':refresh_only,
            'batch':plan.get('batch'),
            'requiresRenderRebuild':not inspect_only,'renderRebuildEvidenceVersion':1 if not inspect_only else None,
            'levelId':level['levelId'],'terrainId':plan['terrainId'],'nativeSnapshotVersion':2 if large else 1,
            'expiresUtc':(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),'deadlineTick':deadline,'nonce':nonce,'messageId':message,
            'sourceSave':str(source) if source else None,'recovery':recovery,'pins':pins,'called':False,'outcomeUncertain':False,
            'nativeSaveVerified':False,'visualRebuildVerified':False}
    # One authority for dispatch/decoding. The helper checks this fixed filename.
    # build-result is the same record, explicitly hash-bound by prepared.json.
    write(run/'build-result.json',result)
    write(run/'prepared.json',{'kind':'native-terrain-prepared-v1','run':str(run),
                              'buildResultSha256':profiles.sha256(run/'build-result.json')})
    return {k:v for k,v in result.items() if k not in ('pins','session')}

def checked_run(path):
    run=artifact_path(path);require(run.is_relative_to(OUT.resolve()) and run.is_dir(),'TERRAIN_RUN_OUTSIDE_PREPARED_ROOT')
    built=ro.read_json(run/'build-result.json')
    prepared=ro.read_json(run/'prepared.json')
    require(prepared=={'kind':'native-terrain-prepared-v1','run':str(run),
                       'buildResultSha256':profiles.sha256(run/'build-result.json')},'PREPARED_BUILD_BINDING_CHANGED')
    require(built.get('kind')=='native-terrain-build-v1' and built.get('run')==str(run) and built.get('launchable') is True,'INVALID_TERRAIN_BUILD')
    return run,built

def decode(run):
    run,built=checked_run(run)
    # Original save changes after the explicit native-save step; immutable
    # candidate/request artifacts still have to match the preparation manifest.
    for path,h in built['pins'].items():
        if Path(path).resolve().is_relative_to(run):
            require(profiles.sha256(Path(path))==h,'RUN_ARTIFACT_CHANGED:'+path)
    # 6 MiB terrain hex + the optional large scene fit the shared 8 MiB decoder.
    raw_receipt_sha=profiles.sha256(run/'stdout.jsonl')
    runtime_probe=built.get('runtimeProbe',False)
    catalog_probe=built.get('catalogProbe',False)
    require(not(runtime_probe and catalog_probe),'CATALOG_MODE_EXCLUSIVE')
    if runtime_probe:
        import terrain_runtime
        record,_=terrain_runtime.read_probe(run/'stdout.jsonl')
    else:record,_=ro.load_decoder().read_probe(run/'stdout.jsonl')
    require(profiles.sha256(run/'stdout.jsonl')==raw_receipt_sha,'RECEIPT_CHANGED_DURING_DECODE')
    prefix=bytes.fromhex(record.get('receiptPrefixHex',''))
    require(len(prefix)==64,'RECEIPT_PREFIX_ABI')
    magic,version,nonce,deadline,pid,tid,claim,actual_pid,actual_tid,callbacks,active,_,_,_=struct.unpack('<IIQQII8i',prefix)
    identity=(magic==0x31524847 and version==(27 if catalog_probe else 20 if runtime_probe else 18) and nonce==built['nonce'] and deadline==built['deadlineTick'] and
              pid==actual_pid==built['session']['pid'] and tid==actual_tid==built['session']['tid'] and claim==2 and callbacks==1 and active==0 and
              record.get('processCreation')==built['session']['processCreation'] and record.get('threadCreation')==built['session']['threadCreation'])
    exit_evidence=ro.read_json(run/'exit.json')
    launch=(exit_evidence.get('executed') is True and type(exit_evidence.get('exitCode')) is int and
            exit_evidence.get('stdoutSha256')==profiles.sha256(run/'stdout.jsonl') and (run/'launch.claim').is_file() and (run/'attempt.used').is_file())
    cleanup=(identity and launch and record.get('callbackCount')==1 and record.get('activeCallbacks')==0 and record.get('unhooked') is True and record.get('transportOk') is True)
    raw=bytes.fromhex(record.get('terrainHex',''))
    snapshot_size=262584 if built['nativeSnapshotVersion']==2 else 33208
    import terrain_catalog
    receipt_size=RECEIPT_BASE_SIZE+snapshot_size+(terrain_runtime.SIZE if runtime_probe else terrain_catalog.SIZE if catalog_probe else 0)
    require(record.get('terrainBytes')==receipt_size and len(raw)==receipt_size,'TERRAIN_RECEIPT_ABI')
    head=dict(zip(HEADER_NAMES,struct.unpack_from('<32Q',raw)))
    require(head['size']==receipt_size and head['version']==(3 if catalog_probe else 2 if runtime_probe else 1) and head['beforeCount']<=MAX_CELLS and head['afterCount']<=MAX_CELLS,'TERRAIN_HEADER_INVALID')
    before=[list(struct.unpack_from('<6I',raw,256+24*i)) for i in range(head['beforeCount'])]
    after=[list(struct.unpack_from('<6I',raw,256+24*MAX_CELLS+24*i)) for i in range(head['afterCount'])]
    plan=ro.read_json(run/'request.json');reasons=[]
    def check(c,r):
        if not c:reasons.append(r)
    check(built.get('batch')==plan.get('batch'),'BATCH_BUILD_REQUEST_BINDING')
    check(built.get('materialSource')==plan.get('materialSource') and bool(built.get('catalogGuard'))==bool(plan.get('materialSource')),'CATALOG_GUARD_REQUEST_BINDING')
    shape_enabled=bool(plan.get('shapeSemantics'))
    check(built.get('shapeSemantics')==plan.get('shapeSemantics') and built.get('shapeGuardVersion')==(1 if shape_enabled else None),'SHAPE_GUARD_REQUEST_BINDING')
    shape_evidence=shapes.evidence(head['reserved'],shape_enabled)
    check(shape_evidence['verified'],'SHAPE_RESOURCES_NOT_VERIFIED')
    check(identity,'CARD_PREFIX_OR_SESSION_BINDING')
    check(launch,'EXIT_EXECUTION_EVIDENCE')
    check(record.get('ok') is True and exit_evidence.get('exitCode')==0,'PROBE_REPORTED_FAILURE')
    check(cleanup,'CALLBACK_CLEANUP_NOT_VERIFIED')
    check(record.get('scope')=='FIXED_TERRAIN_ACTION' and record.get('selfTestOnly') is False and record.get('probeElevatedHigh') is True,'RECEIPT_SCOPE')
    check(record.get('pid')==built['session']['pid'] and record.get('tid')==built['session']['tid'],'RECEIPT_SESSION')
    check(head['status']==0 and head['sehCode']==0 and head['sceneUnchanged']==1 and head['captureStable']==1 and head['constantsValid']==1 and head['outcomeUncertain']==0,'TERRAIN_NATIVE_STATUS')
    check(head['terrainId']==built['terrainId']==plan['terrainId'],'TERRAIN_ID')
    decoder=ro.load_decoder()
    baseline_bytes=(run/'baseline-snapshot.bin').read_bytes()
    after_bytes=raw[RECEIPT_BASE_SIZE:RECEIPT_BASE_SIZE+snapshot_size]
    # Only the transport scope/aggregate action flag is adapted for the existing
    # READ-ONLY validator. Its profile, stack, level, full graph and ABI predicates
    # are applied to both independently decoded snapshots, with the raw action
    # outcome checked separately above and below.
    original_prepared=ro.read_json(run/'baseline-prepared.json')
    context_checks=[];context_not_captured=not any(after_bytes)
    def scene_identity(s):
        return (s['pointers'],s['entities'],s['levelObservation'],{k:s['counts'][k] for k in ('activeKey','entityVersionBefore','entityVersionAfter','entityCaptured','entityValidEntries')})
    try:
        context=decoder.decode_snapshot(record)
        baseline_context=decoder.decode_snapshot(dict(record,snapshotHex=baseline_bytes.hex(),snapshotBytes=len(baseline_bytes)))
        observed_contexts=[context]
        if context_not_captured:
            # Native stage-1 refusal has not produced an afterScene. Its zero
            # bytes are missing evidence, not an unsupported snapshot protocol.
            reasons.append('AFTER_CONTEXT_NOT_CAPTURED')
        else:
            observed_contexts.append(decoder.decode_snapshot(dict(record,snapshotHex=after_bytes.hex(),snapshotBytes=len(after_bytes))))
        for observed in observed_contexts:
            adapted=dict(record,scope='READ_ONLY_CONTEXT_RECEIPT',ok=observed['status']['value']==0,snapshotStatus=observed['status']['value'])
            context_checks.append(ro.validate_receipt(adapted,observed,original_prepared,profiles.load_profile()))
        check(all(c['ok'] for c in context_checks),'INDEPENDENT_CONTEXT_VALIDATION')
        check(all(scene_identity(baseline_context)==scene_identity(observed) for observed in observed_contexts),'INDEPENDENT_SCENE_CHANGED')
    except (ValueError,KeyError,TypeError) as exc:
        reasons.append('CONTEXT_DECODE:'+str(exc))
    if built['inspectOnly']:
        check(not any(head[x] for x in ('mutationCalls','openCalled','snapshotCalled','notifyCalled','closeCalled')) and before==after,'INSPECT_MUTATED')
    else:
        validate_request(plan,(run/'before.gil').read_bytes(),run)
        check(before==plan['before'] and after==plan['expected'],'INDEPENDENT_CELL_COMPARISON')
        if built.get('refreshOnly'):
            check(before==after and not any(head[x] for x in ('mutationCalls','completed','openCalled','snapshotCalled','notifyCalled','closeCalled','snapshotVerified','notificationVerified','closeVerified','transactionMayBeOpen')),
                  'REFRESH_CHANGED_LOGIC_OR_TRANSACTION')
            check(built.get('requiresRenderRebuild') is True,'REFRESH_REBUILD_CONTRACT_REQUIRED')
        else:
            check(head['mutationCalls']==head['completed']==len(plan['changes']),'INCOMPLETE_EDITS')
            check(all(head[x]==1 for x in ('openCalled','snapshotCalled','notifyCalled','closeCalled','snapshotVerified','notificationVerified','closeVerified')) and head['transactionMayBeOpen']==0,'TRANSACTION_INCOMPLETE')
    rebuild=terrain_refresh.evidence(head['reserved'] & ~shapes.MASK if shape_enabled else head['reserved']) if built.get('requiresRenderRebuild') else None
    if rebuild:
        check(not built['inspectOnly'] and built.get('renderRebuildEvidenceVersion')==1 and rebuild['verified'],'NATIVE_RENDER_REBUILD_NOT_VERIFIED')
    else:check(head['reserved']==0,'UNEXPECTED_REBUILD_EVIDENCE')
    check(before==sorted(before) and after==sorted(after) and len({r[0] for r in before})==len(before) and len({r[0] for r in after})==len(after),'CELL_ORDER_OR_DUPLICATES')
    observation=None
    catalog_observation=None
    if catalog_probe:
        check(built['inspectOnly'] is True and built.get('catalogKind')=='native-terrain-catalog-calibration-v1','CATALOG_READ_CONTRACT')
        catalog_observation=terrain_catalog.decode(raw[RECEIPT_BASE_SIZE+snapshot_size:]);reasons.extend(catalog_observation['reasons'])
    if runtime_probe:
        check(built['inspectOnly'] is True and built.get('runtimeKeys')==plan.get('runtimeKeys'),'RUNTIME_REQUEST_BINDING')
        keys=plan.get('runtimeKeys',[])
        require(isinstance(keys,list) and 1<=len(keys)<=4 and len(set(keys))==len(keys),'RUNTIME_REQUEST_KEYS')
        observation=terrain_runtime.decode(raw[RECEIPT_BASE_SIZE+snapshot_size:],keys,before,built.get('runtimeObservationVersion',1))
        reasons.extend(observation['reasons'])
    called=bool(head['mutationCalls'] or head['openCalled'] or (rebuild and rebuild['called']))
    uncertain=bool(head['outcomeUncertain'] or head['transactionMayBeOpen'] or (called and reasons))
    result={'ok':not reasons,'reasons':reasons,'run':str(run),'called':called,
            'outcomeUncertain':uncertain,
            'cleanupVerified':cleanup,'safeToRelease':cleanup and not uncertain,'noAutomaticReplay':True,
            'nativeSaveVerified':False,'visualRebuildVerified':False,'header':head,'before':before,'after':after,
            'rawReceiptSha256':raw_receipt_sha,'contextValidation':context_checks,'contextNotCaptured':context_not_captured,
            'afterContextVerified':not context_not_captured and len(context_checks)==2 and all(c['ok'] for c in context_checks)}
    if rebuild:
        result.update(renderRebuild=rebuild,nativeRenderRebuildVerified=not reasons and rebuild['verified'],
                      refreshOnly=bool(built.get('refreshOnly')),logicalTerrainPreserved=not reasons and before==after)
    if shape_enabled:
        result.update(shapeEvidence=shape_evidence,nativeSurfaceDataVerified=not reasons,
                      nativeSurfaceResourcesVerified=not reasons and shape_evidence['verified'],
                      surfaceChanges=[dict(key=c['key'],before=c['before'],after=c['after']) for c in plan['changes']],
                      shapeVisualVerified=False,playerTraversalVerified=False)
    if runtime_probe:
        result['runtimeObservation']=observation
        result['physicalQueryVerified']=not reasons and observation['physicalQueryVerified']
        result['rendererStateVerified']=not reasons and observation['rendererStateVerified']
        result['pixelAppearanceVerified']=False;result['playerBlockingVerified']=False
    if catalog_probe:
        result['catalogObservation']=catalog_observation
        result['materialCatalogVerified']=not reasons and catalog_observation['materialCatalogVerified']
        result['worldMatrixVerified']=not reasons and catalog_observation['worldMatrixVerified']
    (run/'decoded.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:v for k,v in result.items() if k not in ('before','after','runtimeObservation','catalogObservation')}
    if observation:summary['runtimeTargets']=observation['targets']
    return summary|{'decoded':str(run/'decoded.json')}

def execute(args):
    run,built=checked_run(args.run)
    if built.get('batch') and not args.elevated_queue:
        import terrain_batch
        with terrain_batch.dispatch_guard(ro.read_json(run/'request.json')):
            return _execute_unlocked(args)
    return _execute_unlocked(args)

def _execute_unlocked(args):
    run,built=checked_run(args.run)
    if args.elevated_queue:
        require(not args.direct_elevated,'QUEUE_AND_DIRECT_ARE_EXCLUSIVE')
        path=ROOT/'tools/editor-bridge/elevated-request.py'
        spec=importlib.util.spec_from_file_location('terrain_elevated_request',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        args._dispatch_possible=True
        return module.send_native_map('terrain',str(run),timeout=300,queue_dir=Path(args.elevated_queue))
    require(args.direct_elevated,'EXECUTE_REQUIRES_ELEVATED_QUEUE_OR_DIRECT_ELEVATED')
    require(bool(ctypes.windll.shell32.IsUserAnAdmin()),'NORMAL_ADMIN_APPROVAL_REQUIRED')
    require(datetime.now(timezone.utc)<datetime.fromisoformat(built['expiresUtc']),'TERRAIN_PREPARATION_EXPIRED')
    for path,h in built['pins'].items():require(profiles.sha256(Path(path))==h,'PIN_CHANGED:'+path)
    profiles.verify_disk(profiles.load_profile());profiles.validate_session(built['session'])
    if not built['inspectOnly']:
        plan=ro.read_json(run/'request.json');validate_request(plan,(run/'before.gil').read_bytes(),run,True)
        import terrain_catalog
        terrain_catalog.preparation(plan,built['session'],built['levelId'])
        recovery=terrain_recovery.validate(run,built.get('recovery',{}),built['levelId'],built['sourceSave'])
        require(ro.read_json(run/'recovery.json')==built['recovery'],'RECOVERY_MANIFEST_CHANGED')
        require({str(p) for p in terrain_recovery.sibling_files(Path(built['sourceSave']))}=={item['source'] for item in recovery.values()},
                'SIBLING_SET_CHANGED_BEFORE_TERRAIN_WRITE')
    # Queue delegation does not consume this one-shot claim. Only this exact
    # elevated invocation may claim, then it never retries an ambiguous attempt.
    with (run/'launch.claim').open('xb') as claim:claim.write(b'one terrain callback\n')
    outcome={'startedUtc':datetime.now(timezone.utc).isoformat(),'executed':False,'exitCode':None,'called':False,
             'outcomeUncertain':False,'cleanupVerified':False,'safeToRelease':False,'noAutomaticReplay':True}
    try:
        with (run/'stdout.jsonl').open('xb') as stdout,(run/'stderr.txt').open('xb') as stderr:
            args._dispatch_possible=True
            process=subprocess.Popen([str(run/'hook_receipt_probe.exe')],cwd=run,stdout=stdout,stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            outcome['executed']=True;outcome['called']=None;outcome['outcomeUncertain']=True
            outcome['exitCode']=process.wait(timeout=85)
        outcome['finishedUtc']=datetime.now(timezone.utc).isoformat()
        outcome['stdoutSha256']=profiles.sha256(run/'stdout.jsonl')
        write(run/'exit.json',outcome)
        result=decode(run)
        outcome.update({k:result[k] for k in ('called','outcomeUncertain','cleanupVerified','safeToRelease')})
        return result|{'exitCode':outcome['exitCode']}
    except Exception as exc:
        # Do not terminate a possibly active callback and do not replay it.
        if getattr(args,'_dispatch_possible',False) and not outcome['executed']:
            outcome['called']=None;outcome['outcomeUncertain']=True
        return {'ok':False,'run':str(run),'error':str(exc),**outcome}
    finally:
        outcome['finishedUtc']=datetime.now(timezone.utc).isoformat()
        if not (run/'exit.json').exists():write(run/'exit.json',outcome)
        else:write(run/'dispatch-result.json',outcome)
