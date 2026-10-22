"""Build immutable read-only action18 cards; this module does not dispatch."""
from datetime import datetime,timezone,timedelta
import os
from pathlib import Path
import struct
import subprocess
from asset_inspection_common import *
import build as b

FILES=('asset_inspection.py','asset_inspection_common.py','asset_inspection_build.py','asset_inspection_receipt.py',
       'asset_inspection_templates.py','asset_inspection_icons.py',
       'asset_inspection_native.h','asset_inspection_native.cpp','asset_inspection_profile.json')

def sources(run):
    hashes=b.copy_sources(run)
    hashes[str(TRANSFORM/'physics_receipt.py')]=sha(TRANSFORM/'physics_receipt.py')
    for name in FILES:
        p=HERE/name;hashes[str(p)]=sha(p);(run/'candidate-source/entity-transform'/name).write_bytes(p.read_bytes())
    for name in ('game_context_snapshot.h','hook_receipt_protocol.h','hook_receipt.cpp','hook_receipt_probe.cpp'):
        path=run/'candidate-source/native'/name
        value=path.read_text(encoding='utf-8').replace('HR_ACTION == 13','HR_ACTION == 18')
        value=value.replace('HR_ACTION == 18 ? 17','HR_ACTION == 18 ? 23')
        value=value.replace('../entity-transform/native_transform.h','../entity-transform/asset_inspection_native.h')
        value=value.replace('TransformReceipt transform;','AssetReceipt asset;')
        value=value.replace('ExecuteTransform(&receipt->context, &receipt->transform);','ExecuteAssetInspection(&receipt->context, &receipt->asset);')
        value=value.replace('receipt->transform','receipt->asset')
        for old,new in [('transformNonce','assetNonce'),('transformDeadline','assetDeadline'),('transformProtocol','assetProtocol'),
                        ('transformBytes','assetBytes'),('transformHex','assetHex'),('FIXED_ENTITY_TRANSFORM_ACTION',SCOPE)]:value=value.replace(old,new)
        path.write_text(value,encoding='utf-8')
    path=run/'candidate-source/entity-transform/native_transform.cpp'
    path.write_text(b.replace(path.read_text(encoding='utf-8'),'#if HR_ACTION != 13','#if HR_ACTION != 18'),encoding='utf-8')
    return hashes

def compile_card(run,fixture):
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';require(vc.is_file(),'MSVC_REQUIRED')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run/"target_config.h"}" '
    lines=['@echo off',f'call "{vc}" >nul','if errorlevel 1 exit /b 1'];objects=[]
    for folder,name in [('native','game_context_snapshot'),('entity-transform','native_transform'),('entity-transform','asset_inspection_native')]:
        obj=run/(name+'.obj');objects.append(obj)
        lines += [common+f'/c "{run/"candidate-source"/folder/(name+".cpp")}" /Fo:"{obj}"','if errorlevel 1 exit /b 1']
    link=' '.join('"'+str(p)+'"' for p in objects)
    for name,source,dll,libraries in [('hook_receipt','native/hook_receipt.cpp',True,'User32.lib'),('hook_receipt_probe','native/hook_receipt_probe.cpp',False,'User32.lib Advapi32.lib')]:
        target=run/(name+('.dll' if dll else '.exe'))
        lines += [common+('/LD ' if dll else '')+f'"{run/"candidate-source"/source}" /Fo:"{run/(name+".obj")}" /Fe:"{target}" /link '+libraries+(' '+link if dll else ''),'if errorlevel 1 exit /b 1']
    if fixture:
        lines += [common+f'"{run/"candidate-source/entity-transform/asset_inspection_startup.cpp"}" /Fo:"{run/"startup.obj"}" /Fe:"{run/"callback_startup.exe"}" /link User32.lib '+link,'if errorlevel 1 exit /b 1']
    lines+=['exit /b 0'];(run/'build.cmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'build.log').write_text((result.stdout or '')+(result.stderr or ''),encoding='utf-8')
    require(result.returncode==0,'BUILD_FAILED:'+str(run/'build.log'))

def prepare(args,compile_only=False):
    profile=b.p.load_profile();b.p.verify_disk(profile)
    runtime=read(TRANSFORM/'runtime-profile.json');asset=read(HERE/'asset_inspection_profile.json')
    metadata=b.p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(asset['imageSha256']==runtime['imageSha256']==profile['image']['sha256'],'ASSET_IMAGE_DRIFT')
    require(sha(metadata)==asset['metadataSha256']==runtime['metadataSha256'],'ASSET_METADATA_DRIFT')
    if compile_only:
        raw=bytearray(262584 if args.large_scene else 33208);struct.pack_into('<II',raw,0,len(raw),2 if args.large_scene else 1);raw=bytes(raw)
        session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
        level=1;origin=[0.,0.,0.];ids=list(range(1,MAX_ENTITIES+1));templates={v:1 for v in ids};catalog={}
    else:
        session,snapshot,raw=b.baseline(args.baseline);session=b.p.validate_session(session)
        ids=[identifier(v) for v in args.entity_id]
        require(1<=len(ids)<=MAX_ENTITIES and len(set(ids))==len(ids),'ASSET_UNIQUE_ENTITY_BATCH_1_TO_8')
        entities={r['id']:r for r in snapshot['entities']};require(set(ids)<=entities.keys(),'ASSET_ENTITY_NOT_IN_BASELINE')
        templates={v:entities[v]['configId'] for v in ids}
        require(all(type(v) is int and v>0 for v in templates.values()),'ASSET_TEMPLATE_ID_UNAVAILABLE')
        catalog=catalog_evidence(set(templates.values()))
        level=snapshot['levelObservation']['levelId'];origin=snapshot['origin']
    empty={key:[0.,0.,0.] for key in b.POSE_KEYS};empty['scale']=[1.,1.,1.]
    requests=[dict(entityId=v,mask=0,requireRoot=0,expectedFrame=0,expectedParent=0,expected=empty,desired=empty) for v in ids]
    run=b.ro.output_directory(OUTPUT);(run/'baseline-snapshot.bin').write_bytes(raw)
    hashes=sources(run);hashes[str(metadata)]=asset['metadataSha256']
    if not compile_only:hashes[str(CATALOG)]=CATALOG_SHA
    if compile_only:
        source=HERE/'asset_inspection_startup.cpp';hashes[str(source)]=sha(source)
        (run/'candidate-source/entity-transform/asset_inspection_startup.cpp').write_bytes(source.read_bytes())
    deadline,nonce=b.emit_header(run,profile,runtime,session,raw,level,requests,0,not compile_only)
    header=run/'target_config.h';value=b.replace(header.read_text(encoding='utf-8'),'#define HR_ACTION 13ULL','#define HR_ACTION 18ULL')
    value+='\n#define ASSET_INSPECTION_REVIEWED 1\n#define ASSET_MESH_RENDERER_CLASS_SLOT '+asset['classSlots']['MeshRenderer']+'ULL\n'
    value+='#define ASSET_MESH_CLASS_SLOT '+asset['classSlots']['Mesh']+'ULL\n'
    value+='#define ASSET_CODE_RVAS '+','.join(x['rva'] for x in asset['functions'])+'\n'
    value+='#define ASSET_CODE_BYTES '+','.join('{'+','.join(hex(v) for v in bytes.fromhex(x['head32']))+'}' for x in asset['functions'])+'\n'
    header.write_text(value,encoding='utf-8');compile_card(run,compile_only)
    for path,digest in hashes.items():require(sha(path)==digest,'SOURCE_CHANGED_DURING_BUILD')
    prepared=dict(schemaVersion=1,kind=KIND,run=str(run),action=18,receiptVersion=23,mode='inspect',launchable=not compile_only,compileOnly=compile_only,
        syntheticStartupFixture=compile_only,session=session,levelId=level,origin=origin,requests=requests,templateIds=templates,catalogEvidence=catalog,
        sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),
        createdUtc=datetime.now(timezone.utc).isoformat(),nativeSnapshotVersion=struct.unpack_from('<I',raw,4)[0],
        baseline=str(Path(args.baseline).resolve()) if not compile_only else None,imagePath=str(b.p.TARGET_IMAGE),imageSha256=profile['image']['sha256'])
    prepared['measurementPlan']=getattr(args,'measurement_plan',None)
    prepared['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',prepared)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in prepared['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(b.p.TARGET_IMAGE)]=profile['image']['sha256']
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(TRANSFORM/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_ENTITY_TRANSFORM_ACTION',SCOPE).replace('entity-transform-build-v1',BUILD_KIND)
        wrapper=wrapper.replace('@@EXPIRES@@',quote(prepared['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-asset.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind=BUILD_KIND,run=str(run),compiled=True,launchable=not compile_only,mode='inspect',actionCode=18,receiptVersion=23,
        called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,replayForbidden=False,
        appearanceVerified=False,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-asset.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
