"""Prepare a version-pinned readonly native snapshot; execution is always separate.

verify-disk                         reads the executable only
discover --output SESSION.json       queries current window/process/thread identity
prepare --session SESSION.json      rechecks identity and builds a one-shot probe
compile-check                       compiles an expired, non-launchable fixture
decode --run RUN                    validates the saved callback receipt
No command in this CLI injects, elevates, invokes the probe, calls a game method,
or enables native writes. Use the generated wrapper only through a separately
reviewed standard UAC launch. A successful build is not runtime acceptance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import struct
import native_level_observation as level_api
import native_level_catalog as catalog_api
import native_lifecycle_type as lifecycle_api
import native_scheduler_coroutines as scheduler_api
import native_reopen_guards as reopen_api
import native_profiles as profiles

ROOT = profiles.ROOT
NATIVE = Path(__file__).with_name('native')
OUTPUT_ROOT = ROOT / '.runtime/game-executor/readonly-bootstrap'
SOURCES = ('game_context_snapshot.cpp','game_context_snapshot.h','hook_receipt.cpp',
           'hook_receipt_probe.cpp','hook_receipt_protocol.h')

def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False);f.write('\n')

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def output_directory(parent):
    parent=Path(parent).resolve()
    profiles.require(parent.is_relative_to(ROOT/'.runtime'), 'OUTPUT_MUST_BE_PROJECT_RUNTIME')
    run=parent/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(5))
    run.mkdir(parents=True,exist_ok=False)
    return run

def emit_header(profile, session, run, *, deadline, message_id, nonce, large_scene=False):
    profiles.require_action(profile,'inspect')
    level_profile=level_api.load_profile()
    values={'HR_TARGET_PID':session['pid'],'HR_TARGET_TID':session['tid'],
        'HR_TARGET_CREATION':session['processCreation'],'HR_TARGET_THREAD_CREATION':session['threadCreation'],
        'HR_TARGET_IMAGE':session['image'],'HR_DLL_PATH':str(run/'hook_receipt.dll'),
        'HR_ATTEMPT_FILE':str(run/'attempt.used'),'HR_NONCE':nonce,
        'HR_MAPPING':'Local\\Miliastra.Readonly.'+secrets.token_hex(16),
        'HR_DEADLINE':deadline,'HR_MESSAGE_ID':message_id,'HR_READ_CONTEXT':1,'HR_ACTION':0,
        'GS_BOOTSTRAP_READONLY':1,'HR_GAME_TIMESTAMP':profile['image']['timestamp'],
        'HR_GAME_IMAGE_SIZE':profile['image']['sizeOfImage'],
        'HR_CONTEXT_ANCHOR_RVA':int(profile['anchors']['CONTEXT']['rva'],16)}
    profiles.require(type(large_scene) is bool, 'LARGE_SCENE_BOOL_REQUIRED')
    if large_scene: values['GS_LARGE_SCENE'] = 1
    lines=['// Generated readonly bootstrap. HR_ACTION=0; no scene action is linked.']
    for name,value in values.items():
        literal='L'+json.dumps(value) if isinstance(value,str) else str(value)+'ULL'
        lines.append('#define '+name+' '+literal)
    lines += ['#define '+name+' '+value+'ULL' for name,value in profile['layout'].items()]
    lines.append('#define GS_READ_LEVEL_METADATA 1')
    lines += ['#define '+name+' '+value+'ULL' for name,value in level_profile['layout'].items()]
    context=bytes.fromhex(profile['anchors']['CONTEXT']['bytes'])
    lines.append('#define HR_CONTEXT_ANCHOR '+','.join(hex(b) for b in context))
    anchors=[profile['anchors'][name] for name in profiles.ANCHOR_NAMES]
    lines.append('#define GS_PROFILE_ANCHOR_RVAS '+','.join(a['rva'] for a in anchors))
    lines.append('#define GS_PROFILE_ANCHOR_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(a['bytes']))+'}' for a in anchors))
    lines.append('#define GS_PROFILE_STACK_RVAS '+','.join(profile['callbackStackRvas']))
    lines.append('#define GS_PROFILE_HOTFIX_RVAS '+','.join(profile['defaultHotfixByteRvas']+level_profile['additionalDefaultHotfixByteRvas']))
    header=run/'target_config.h'
    with header.open('x',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines)+'\n')
    return values

def compile_probe(run, *, level_catalog=False, lifecycle_type=False, scheduler_coroutines=False, reopen_guards=False):
    profiles.require(not reopen_guards or (level_catalog and lifecycle_type and scheduler_coroutines),'REOPEN_REQUIRES_ALL_READONLY_EXTENSIONS')
    profiles.require(not scheduler_coroutines or lifecycle_type,'SCHEDULER_REQUIRES_LIFECYCLE_TYPE')
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vcvars=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    profiles.require(bool(vs) and vcvars.is_file(),'MSVC_X64_UNAVAILABLE')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /FI"{run / "target_config.h"}" '
    lines=['@echo off',f'call "{vcvars}" >nul','if errorlevel 1 exit /b 1',
           common+f'/c "{NATIVE / "game_context_snapshot.cpp"}" /Fo:"{run / "game_context_snapshot.obj"}"','if errorlevel 1 exit /b 1',
           common+f'/LD "{NATIVE / "hook_receipt.cpp"}" /Fo:"{run / "hook_receipt.obj"}" /Fe:"{run / "hook_receipt.dll"}" /link User32.lib "{run / "game_context_snapshot.obj"}"','if errorlevel 1 exit /b 1',
           common+f'"{NATIVE / "hook_receipt_probe.cpp"}" /Fo:"{run / "hook_receipt_probe.obj"}" /Fe:"{run / "hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib',
           'exit /b %ERRORLEVEL%']
    if level_catalog:
        extra=common+f'/c "{NATIVE / "game_level_catalog.cpp"}" /Fo:"{run / "game_level_catalog.obj"}"'
        link=next(i for i,line in enumerate(lines) if '/LD ' in line)
        lines[link]+=f' "{run / "game_level_catalog.obj"}"'
        lines[link:link]=[extra,'if errorlevel 1 exit /b 1']
    if lifecycle_type:
        extra=common+f'/c "{NATIVE / "game_lifecycle_type.cpp"}" /Fo:"{run / "game_lifecycle_type.obj"}"'
        link=next(i for i,line in enumerate(lines) if '/LD ' in line)
        lines[link]+=f' "{run / "game_lifecycle_type.obj"}"'
        lines[link:link]=[extra,'if errorlevel 1 exit /b 1']
    if scheduler_coroutines:
        extra=common+f'/c "{NATIVE / "game_scheduler_coroutines.cpp"}" /Fo:"{run / "game_scheduler_coroutines.obj"}"'
        link=next(i for i,line in enumerate(lines) if '/LD ' in line)
        lines[link]+=f' "{run / "game_scheduler_coroutines.obj"}"'
        lines[link:link]=[extra,'if errorlevel 1 exit /b 1']
    if reopen_guards:
        for name in ('game_reopen_guards','game_reopen_guards_capture'):
            extra=common+f'/c "{NATIVE / (name+".cpp")}" /Fo:"{run / (name+".obj")}"'
            link=next(i for i,line in enumerate(lines) if '/LD ' in line)
            lines[link]+=f' "{run / (name+".obj")}"'
            lines[link:link]=[extra,'if errorlevel 1 exit /b 1']
    with (run/'build.cmd').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    result=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,text=True,capture_output=True)
    # `stdout`/`stderr` are typed `str | None` and MEASURED can be None: under a
    # launcher that hands this process unusual stdio (the dsh-spawned business MCP
    # server did), the compiler's output came back as None and `+` raised
    # "can only concatenate str (not NoneType) to str".  That killed level discovery
    # before the probe was ever launched, with no way to tell which stage failed.
    with (run/'build.log').open('x',encoding='utf-8') as f:f.write((result.stdout or '')+(result.stderr or ''))
    profiles.require(result.returncode==0,'MSVC_BUILD_FAILED:'+str(run/'build.log'))
    return vs

def ps_literal(s):return "'"+str(s).replace("'","''")+"'"

def emit_wrapper(run, image, image_hash, hashes):
    checks='\n'.join('    if ((Get-FileHash -LiteralPath (Join-Path $taskRun '+ps_literal(name)+') -Algorithm SHA256).Hash -ine '+ps_literal(digest)+") { throw 'ARTIFACT_CHANGED' }" for name,digest in hashes.items())
    text="""$ErrorActionPreference = 'Stop'
$taskRun = $PSScriptRoot
$taskResult = [ordered]@{ startedUtc=[DateTime]::UtcNow.ToString('o'); helperPid=$PID; executed=$false; exitCode=$null; error=$null; scope='READONLY_BOOTSTRAP'; allowWrites=$false }
try {
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'NOT_ELEVATED' }
    $taskClaim = [IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $taskClaim.Dispose()
__CHECKS__
    if ((Get-FileHash -LiteralPath __IMAGE__ -Algorithm SHA256).Hash -ine __IMAGE_HASH__) { throw 'GAME_SOURCE_HASH_MISMATCH' }
    $taskResult.executed = $true
    # PS5 redirection defaults to UTF-16; write the receipt as UTF-8 without BOM.
    $taskStdoutStream = [IO.File]::Open((Join-Path $taskRun 'stdout.jsonl'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $taskStdoutWriter = New-Object IO.StreamWriter($taskStdoutStream,(New-Object Text.UTF8Encoding($false)))
    $taskPreviousOutputEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
        $taskStdoutWriter.AutoFlush = $true
        & (Join-Path $taskRun 'hook_receipt_probe.exe') 2> (Join-Path $taskRun 'stderr.txt') | ForEach-Object { $taskStdoutWriter.WriteLine([string]$_) }
        $taskResult.exitCode = $LASTEXITCODE
    } finally {
        [Console]::OutputEncoding = $taskPreviousOutputEncoding
        $taskStdoutWriter.Dispose()
    }
} catch { $taskResult.error = $_.Exception.Message }
finally {
    $taskResult['finishedUtc'] = [DateTime]::UtcNow.ToString('o')
    $taskJson = $taskResult | ConvertTo-Json
    $taskStream = [IO.File]::Open((Join-Path $taskRun 'exit.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $taskWriter = New-Object IO.StreamWriter($taskStream,(New-Object Text.UTF8Encoding($false)))
    try { $taskWriter.Write($taskJson) } finally { $taskWriter.Dispose() }
}
""".replace('__CHECKS__',checks).replace('__IMAGE__',ps_literal(image)).replace('__IMAGE_HASH__',ps_literal(image_hash))
    with (run/'invoke-readonly-probe.ps1').open('x',encoding='utf-8-sig') as f:f.write(text)

def prepare(session_path=None, *, output_root=OUTPUT_ROOT, ttl_seconds=180, compile_only=False, level_catalog=False, lifecycle_type=False, scheduler_coroutines=False, reopen_guards=False, large_scene=False):
    profiles.require(not (large_scene and reopen_guards), 'LARGE_SCENE_REOPEN_NOT_SUPPORTED')
    profiles.require(not reopen_guards or (level_catalog and lifecycle_type and scheduler_coroutines),'REOPEN_REQUIRES_ALL_READONLY_EXTENSIONS')
    profiles.require(not scheduler_coroutines or lifecycle_type,'SCHEDULER_REQUIRES_LIFECYCLE_TYPE')
    profile=profiles.load_profile();disk=profiles.verify_disk(profile)
    profiles.require(type(ttl_seconds) is int and 30<=ttl_seconds<=300,'TTL_OUT_OF_RANGE')
    if compile_only:
        session={'schemaVersion':1,'pid':1,'tid':1,'window':1,'windowClass':'COMPILE_ONLY',
            'processCreation':1,'threadCreation':1,'image':str(ROOT/'.runtime/readonly_compile_fixture.invalid'),
            'callbackObserved':False,'source':'expired-offline-compile-fixture'}
        deadline=0;message_id=0xc001
    else:
        profiles.require(session_path is not None,'SESSION_JSON_REQUIRED')
        session=profiles.validate_session(read_json(session_path))
        k,u=profiles.windows_api();deadline=k.GetTickCount64()+ttl_seconds*1000
        message_id=u.RegisterWindowMessageW('Miliastra.Readonly.'+secrets.token_hex(16))
        profiles.require(message_id!=0,'REGISTER_MESSAGE_FAILED')
    run=output_directory(output_root)
    sources=SOURCES+('game_level_catalog.cpp','game_level_catalog.h','game_level_catalog_core.inc') if level_catalog else SOURCES
    if lifecycle_type:sources+=('game_lifecycle_type.cpp','game_lifecycle_type.h','game_lifecycle_type_core.inc')
    if scheduler_coroutines:sources+=('game_scheduler_coroutines.cpp','game_scheduler_coroutines.h','game_scheduler_coroutines_core.inc')
    if reopen_guards:sources+=('game_reopen_guards.cpp','game_reopen_guards.h','game_reopen_guards_capture.cpp','game_reopen_guards_capture_core.inc','guard_profile.generated.h')
    source_hashes={name:profiles.sha256(NATIVE/name) for name in sources}
    values=emit_header(profile,session,run,deadline=deadline,message_id=message_id,nonce=secrets.randbits(63)|1,large_scene=large_scene)
    if level_catalog:
        catalog_profile=catalog_api.load_profile()
        if not compile_only:
            profiles.require(session['pid']==catalog_profile['expectedProcessId'] and session['processCreation']==catalog_profile['expectedProcessCreation'],'CATALOG_SESSION_CHANGED')
        catalog_api.append_header(run,catalog_profile)
    if lifecycle_type:
        lifecycle_profile=lifecycle_api.load_profile()
        if not compile_only:
            profiles.require(session['pid']==lifecycle_profile['expectedProcessId'] and session['processCreation']==lifecycle_profile['expectedProcessCreation'],'LIFECYCLE_SESSION_CHANGED')
        lifecycle_api.append_header(run,lifecycle_profile)
    if scheduler_coroutines:
        scheduler_profile=scheduler_api.load_profile()
        if not compile_only:
            profiles.require(session['pid']==scheduler_profile['expectedProcessId'] and session['processCreation']==scheduler_profile['expectedProcessCreation'],'SCHEDULER_SESSION_CHANGED')
        scheduler_api.append_header(run,scheduler_profile)
    if reopen_guards:
        reopen_profile=reopen_api.load_profile()
        if not compile_only:
            profiles.require(session['pid']==reopen_profile['expectedProcessId'] and session['processCreation']==reopen_profile['expectedProcessCreation'],'REOPEN_SESSION_CHANGED')
        reopen_api.append_header(run,reopen_profile)
    prepared={'profileId':profile['profileId'],'profileSha256':profiles.PROFILE_SHA256,'disk':disk,
        'session':session,'createdUtc':datetime.now(timezone.utc).isoformat(),'deadlineTick':deadline,
        'compileOnly':compile_only,'launchable':not compile_only,'allowWrites':False,
        'scope':'READONLY_BOOTSTRAP','levelObservationProfileSha256':level_api.LEVEL_PROFILE_SHA256,'sources':source_hashes,'nativeDefinitions':values}
    if level_catalog:prepared['levelCatalogProfileSha256']=catalog_api.PROFILE_SHA256
    if lifecycle_type:prepared['lifecycleTypeProfileSha256']=lifecycle_api.PROFILE_SHA256
    if scheduler_coroutines:
        prepared['schedulerCoroutinesProfileSha256']=scheduler_api.PROFILE_SHA256
        prepared['schedulerCoroutinesDecoderSha256']=profiles.sha256(Path(scheduler_api.__file__))
    if reopen_guards:
        prepared['reopenGuardsProfileSha256']=reopen_api.PROFILE_SHA256
        prepared['reopenGuardsHeaderSha256']=reopen_api.HEADER_SHA256
        prepared['reopenGuardsDecoderSha256']=profiles.sha256(Path(reopen_api.__file__))
    write_json(run/'prepared.json',prepared)
    toolchain=compile_probe(run,level_catalog=level_catalog,lifecycle_type=lifecycle_type,scheduler_coroutines=scheduler_coroutines,reopen_guards=reopen_guards)
    profiles.require(source_hashes=={name:profiles.sha256(NATIVE/name) for name in sources},'NATIVE_SOURCE_CHANGED_DURING_BUILD')
    if scheduler_coroutines:
        profiles.require(prepared['schedulerCoroutinesDecoderSha256']==profiles.sha256(Path(scheduler_api.__file__)),'SCHEDULER_DECODER_CHANGED_DURING_BUILD')
        scheduler_api.load_profile()
    if reopen_guards:
        profiles.require(prepared['reopenGuardsDecoderSha256']==profiles.sha256(Path(reopen_api.__file__)),'REOPEN_DECODER_CHANGED_DURING_BUILD')
        reopen_api.load_profile()
    if not compile_only:
        profiles.validate_session(session)
        profiles.require(profiles.windows_api()[0].GetTickCount64()<deadline,'PREPARATION_EXPIRED')
    hashes={name:profiles.sha256(run/name) for name in ('hook_receipt.dll','hook_receipt_probe.exe','target_config.h','prepared.json')}
    if not compile_only:
        emit_wrapper(run,session['image'],disk['sha256'],hashes)
        hashes['invoke-readonly-probe.ps1']=profiles.sha256(run/'invoke-readonly-probe.ps1')
    result={'run':str(run),'profileId':profile['profileId'],'scope':'READONLY_BOOTSTRAP',
        'launchable':not compile_only,'compileOnly':compile_only,'executed':False,'allowWrites':False,
        'targetPid':session['pid'],'targetTid':session['tid'],'deadlineTick':deadline,'hashes':hashes,
        'toolchain':toolchain,'wrapper':str(run/'invoke-readonly-probe.ps1') if not compile_only else None}
    write_json(run/'build-result.json',result)
    return result

def load_decoder():
    spec=importlib.util.spec_from_file_location('_readonly_snapshot_decoder',Path(__file__).with_name('decode_context_snapshot.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.STATUS.update({9:'stack_mismatch',10:'hotfix_active'})
    module.SNAPSHOT_FLAGS.update({256:'stack_verified',512:'hotfix_default_confirmed',1024:'level_observed'})
    original_decode=module.decode_snapshot
    def decode(record):
        raw=bytearray.fromhex(record.get('snapshotHex',''));observed=False;level_id=0
        if len(raw) in (module.SNAPSHOT_BYTES, module.LARGE_SNAPSHOT_BYTES):
            observed=bool(struct.unpack_from('<I',raw,12)[0]&1024);level_id=struct.unpack_from('<I',raw,180)[0]
            profiles.require((observed and level_id>0) or (not observed and level_id==0),'LEVEL_OBSERVATION_FIELD_INVALID')
            struct.pack_into('<I',raw,180,0)
        value=original_decode(dict(record,snapshotHex=raw.hex()))
        value['levelObservation']={'verified':observed,'levelId':level_id if observed else None,'method':'bounded-memory-default-branch-predicates-no-function-call' if observed else None}
        return value
    module.decode_snapshot=decode
    return module

def validate_receipt(record, snapshot, prepared, profile):
    c=snapshot['counts'];f=snapshot['flags']['value'];session=prepared['session']
    reasons=[]
    def check(value,reason):
        if not value:reasons.append(reason)
    check(prepared.get('launchable') is True and prepared.get('compileOnly') is False,'NONLAUNCHABLE_BUILD')
    check(prepared.get('profileSha256')==profiles.PROFILE_SHA256,'PROFILE_BINDING')
    check(record.get('scope')=='READ_ONLY_CONTEXT_RECEIPT' and record.get('selfTestOnly') is False,'RECEIPT_SCOPE')
    check(record.get('pid')==session['pid'] and record.get('tid')==session['tid'],'CALLBACK_IDENTITY')
    check(record.get('callbackCount')==1 and record.get('activeCallbacks')==0 and record.get('unhooked') is True,'CALLBACK_DRAIN')
    check(record.get('probeElevatedHigh') is True,'HELPER_TOKEN')
    check(snapshot['status']['value']==0,'SNAPSHOT_'+snapshot['status']['name'].upper())
    expected_version = prepared.get('nativeSnapshotVersion', 2 if prepared.get('nativeDefinitions', {}).get('GS_LARGE_SCENE') == 1 else 1)
    check(snapshot['version'] == expected_version, 'SNAPSHOT_ABI_PROFILE_BINDING')
    check(record.get('ok') is True and record.get('transportOk') is True and record.get('snapshotStatus')==0,'BUSINESS_SUCCESS')
    check(f&927==927 and not f&96,'SNAPSHOT_REQUIRED_FLAGS')
    check(c['peTimestamp']==profile['image']['timestamp'] and c['peImageSize']==profile['image']['sizeOfImage'],'SNAPSHOT_PE')
    check(c['activeKey']==0 and c['contextMatchingEntries']==1,'CONTEXT_ZERO')
    check(c['entityRejected']==0 and c['entityCaptured']==c['entityValidEntries']==len(snapshot['entities']),'COMPLETE_ENTITY_SET')
    check(c['entityVersionBefore']==c['entityVersionAfter'],'ENTITY_VERSION_CHANGED')
    observed={row['rva'] for row in snapshot['stack'] if row['inMainModule']}
    check(set(profile['callbackStackRvas'])<=observed,'CALLBACK_STACK')
    ids=[row['id'] for row in snapshot['entities']]
    check(len(ids)==len(set(ids)) and all(type(v) is int and v>0 for v in ids),'ENTITY_IDENTITY')
    check(all(row['flags']['value']&79==79 for row in snapshot['entities']),'ENTITY_OWNER_CONFIG_CONTEXT')
    if prepared.get('levelObservationProfileSha256') is not None:
        check(prepared['levelObservationProfileSha256']==level_api.LEVEL_PROFILE_SHA256,'LEVEL_PROFILE_BINDING')
        check(snapshot.get('levelObservation',{}).get('verified') is True,'LEVEL_NOT_OBSERVED')
    return {'ok':not reasons,'reasons':reasons,'allowWrites':False,
        'scope':'readonly-snapshot-evidence-only','entityCount':len(ids),
        'baselineNonempty':bool(ids),'profileId':profile['profileId'],'levelObservation':snapshot.get('levelObservation'),
        'limits':'No game method called; no creation/save/official acceptance is established.'}

def decode_run(run):
    run=Path(run).resolve();profile=profiles.load_profile();prepared=read_json(run/'prepared.json');built=read_json(run/'build-result.json')
    for name,digest in built['hashes'].items():
        profiles.require(profiles.sha256(run/name)==digest,'RUN_ARTIFACT_CHANGED:'+name)
    decoder=load_decoder();record,encoding=decoder.read_probe(run/'stdout.jsonl');snapshot=decoder.decode_snapshot(record)
    result=validate_receipt(record,snapshot,prepared,profile)
    if 'levelCatalogProfileSha256' in prepared:
        profiles.require(prepared['levelCatalogProfileSha256']==catalog_api.PROFILE_SHA256,'CATALOG_PROFILE_BINDING')
        catalog=catalog_api.decode(record,snapshot,catalog_api.load_profile())
        snapshot['levelCatalog']=catalog
        result['levelCatalog']=catalog
        if not catalog['ok']:
            result['ok']=False;result['reasons'].extend(catalog['reasons'])
    elif 'catalogHex' in record:
        result['ok']=False;result['reasons'].append('UNBOUND_CATALOG_EXTENSION')
    if 'lifecycleTypeProfileSha256' in prepared:
        profiles.require(prepared['lifecycleTypeProfileSha256']==lifecycle_api.PROFILE_SHA256,'LIFECYCLE_PROFILE_BINDING')
        lifecycle=lifecycle_api.decode(record,snapshot,lifecycle_api.load_profile())
        snapshot['lifecycleType']=lifecycle;result['lifecycleType']=lifecycle
        if not lifecycle['ok']:
            result['ok']=False;result['reasons'].extend(lifecycle['reasons'])
    elif 'lifecycleTypeHex' in record:
        result['ok']=False;result['reasons'].append('UNBOUND_LIFECYCLE_EXTENSION')
    if 'schedulerCoroutinesProfileSha256' in prepared:
        profiles.require('lifecycleTypeProfileSha256' in prepared,'SCHEDULER_REQUIRES_LIFECYCLE_BINDING')
        profiles.require(prepared['schedulerCoroutinesProfileSha256']==scheduler_api.PROFILE_SHA256,'SCHEDULER_PROFILE_BINDING')
        profiles.require(prepared.get('schedulerCoroutinesDecoderSha256')==profiles.sha256(Path(scheduler_api.__file__)),'SCHEDULER_DECODER_BINDING')
        scheduler=scheduler_api.decode(record,snapshot,scheduler_api.load_profile())
        snapshot['schedulerCoroutines']=scheduler;result['schedulerCoroutines']=scheduler
        if not scheduler['ok']:
            result['ok']=False;result['reasons'].extend(scheduler['reasons'])
    elif any(key in record for key in ('schedulerCoroutinesHex','schedulerCoroutinesBytes','schedulerCoroutinesStatus')):
        result['ok']=False;result['reasons'].append('UNBOUND_SCHEDULER_EXTENSION')
    if 'reopenGuardsProfileSha256' in prepared:
        profiles.require(all(k in prepared for k in ('levelCatalogProfileSha256','lifecycleTypeProfileSha256','schedulerCoroutinesProfileSha256')),'REOPEN_REQUIRES_ALL_INPUT_BINDINGS')
        profiles.require(prepared['reopenGuardsProfileSha256']==reopen_api.PROFILE_SHA256,'REOPEN_PROFILE_BINDING')
        profiles.require(prepared.get('reopenGuardsHeaderSha256')==reopen_api.HEADER_SHA256,'REOPEN_HEADER_BINDING')
        profiles.require(prepared.get('reopenGuardsDecoderSha256')==profiles.sha256(Path(reopen_api.__file__)),'REOPEN_DECODER_BINDING')
        guards=reopen_api.decode(record,snapshot,reopen_api.load_profile(),prepared)
        snapshot['reopenGuards']=guards;result['reopenGuards']=guards
        if not guards['ok']:
            result['ok']=False;result['reasons'].extend(guards['reasons'])
    elif any(key in record for key in ('reopenGuardsHex','reopenGuardsBytes','reopenGuardsStatus')):
        result['ok']=False;result['reasons'].append('UNBOUND_REOPEN_EXTENSION')
    exit_result=read_json(run/'exit.json')
    if exit_result.get('executed') is not True or exit_result.get('exitCode')!=0 or exit_result.get('error'):
        result['ok']=False;result['reasons'].append('WRAPPER_OR_NATIVE_EXIT_REJECTED')
    snapshot['source']={'encoding':encoding,'probe':{k:v for k,v in record.items() if k!='snapshotHex'}}
    write_json(run/'readonly-snapshot.json',snapshot);write_json(run/'readonly-acceptance.json',result)
    return result

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('verify-disk')
    disc=sub.add_parser('discover');disc.add_argument('--output',type=Path,required=True)
    for command in ('prepare','compile-check'):
        item=sub.add_parser(command);item.add_argument('--output-root',type=Path,default=OUTPUT_ROOT)
        item.add_argument('--level-catalog',action='store_true',help='Session-pinned read-only level catalog extension')
        item.add_argument('--lifecycle-type',action='store_true',help='Session-pinned read-only lifecycle type binding')
        item.add_argument('--scheduler-coroutines',action='store_true',help='Read-only scheduler sample; requires --lifecycle-type')
        item.add_argument('--reopen-guards',action='store_true',help='Read-only guard bundle; requires catalog, lifecycle type and scheduler')
        item.add_argument('--large-scene',action='store_true',help='Explicit v2 complete scene snapshot (4096 records)')
        if command=='prepare':item.add_argument('--session',type=Path,required=True);item.add_argument('--ttl-seconds',type=int,default=180)
    item=sub.add_parser('decode');item.add_argument('--run',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='verify-disk':result=profiles.verify_disk(profiles.load_profile())
        elif args.command=='discover':
            profiles.verify_disk(profiles.load_profile());result=profiles.discover_session();write_json(args.output,result)
        elif args.command=='prepare':result=prepare(args.session,output_root=args.output_root,ttl_seconds=args.ttl_seconds,level_catalog=args.level_catalog,lifecycle_type=args.lifecycle_type,scheduler_coroutines=args.scheduler_coroutines,reopen_guards=args.reopen_guards,large_scene=args.large_scene)
        elif args.command=='compile-check':result=prepare(output_root=args.output_root,compile_only=True,level_catalog=args.level_catalog,lifecycle_type=args.lifecycle_type,scheduler_coroutines=args.scheduler_coroutines,reopen_guards=args.reopen_guards,large_scene=args.large_scene)
        else:result=decode_run(args.run)
        print(json.dumps(result,ensure_ascii=False));return 0 if result.get('ok',True) else 2
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False,'stage':args.command,'error':str(exc),'allowWrites':False},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
