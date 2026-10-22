"""Build one reviewed reopen-current attempt. This module never launches its probe."""
from datetime import datetime, timezone
from pathlib import Path
import json, os, re, secrets, subprocess
import native_profiles as profiles
import native_reopen_baseline as baseline_api
import native_write_review as review_api
import build_readonly_profile as readonly
import native_level_catalog as catalog
import native_lifecycle_type as lifecycle
import native_scheduler_coroutines as scheduler
import native_reopen_guards as guards

ROOT=profiles.ROOT
NATIVE=Path(__file__).with_name('native')
SOURCES=('game_context_snapshot.cpp','game_level_catalog_action.cpp','game_lifecycle_type_action.cpp',
 'game_scheduler_coroutines_action.cpp','game_reopen_guards.cpp','game_reopen_guards_capture_action.cpp',
 'reopen_action_validation.cpp','reopen_call.cpp','reopen_action.cpp')
ENTRY_SOURCES=('hook_reopen_receipt.cpp','hook_reopen_probe.cpp')

def validate_review(path,session):
    path=review_api.project_evidence(path);review_sha=profiles.sha256(path);v=review_api.read_json(path)
    profiles.require(v.get('schemaVersion')==1 and v.get('operation')=='level.reopen-current' and v.get('allowedCalls')==1 and v.get('levelId')==baseline_api.LEVEL,'REOPEN_REVIEW_CONTRACT')
    profiles.require(isinstance(v.get('requestId'),str) and re.fullmatch('[0-9a-f]{32}',v['requestId']),'REOPEN_REQUEST_ID')
    start=datetime.fromisoformat(v['createdUtc'].replace('Z','+00:00'));end=datetime.fromisoformat(v['expiresUtc'].replace('Z','+00:00'));now=datetime.now(timezone.utc)
    profiles.require(start.tzinfo is not None and end.tzinfo is not None and start<=now<end and 0<(end-start).total_seconds()<=300,'REOPEN_REVIEW_EXPIRED')
    for k in review_api.SESSION_FIELDS:profiles.require(v['session'].get(k)==session.get(k),'REOPEN_REVIEW_SESSION:'+k)
    b=baseline_api.load(v['baselineRun'],session)
    profiles.require(v.get('baselineHashes')==b['evidenceHashes'],'REOPEN_REVIEW_RAW_BINDING')
    manifest=review_api.project_evidence(v['accountBackupManifest'])
    profiles.require(profiles.sha256(manifest)==v['accountBaselineSha256'],'REOPEN_ACCOUNT_MANIFEST_CHANGED')
    m=review_api.read_json(manifest);source=Path(m['source']).resolve();backup=review_api.project_evidence(m['backup'])
    official=(Path(os.environ['USERPROFILE'])/'AppData/LocalLow/miHoYo/原神/BeyondLocal').resolve()
    profiles.require(source.parent==official and source.name.isdigit(),'REOPEN_ACCOUNT_ROOT')
    expected={}
    for row in m['files']:
        rel=Path(row['relativePath']);p=(source/rel).resolve();q=(backup/rel).resolve()
        profiles.require(not rel.is_absolute() and p.is_relative_to(source) and q.is_relative_to(backup) and rel.as_posix() not in expected,'REOPEN_BACKUP_PATH')
        profiles.require(p.is_file() and q.is_file() and p.stat().st_size==q.stat().st_size==row['bytes'] and profiles.sha256(p)==profiles.sha256(q)==row['sha256'],'REOPEN_ACCOUNT_OR_BACKUP_CHANGED')
        expected[rel.as_posix()]=row['sha256']
    actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    profiles.require(actual==set(expected),'REOPEN_ACCOUNT_FILE_SET_CHANGED')
    target=f'Beyond_Local_Save_Level/{baseline_api.LEVEL}/{baseline_api.LEVEL}.gil'
    # The current single-use review pins the complete recovery manifest, including
    # this target's digest. Normal saves must not be compared with an old experiment.
    profiles.require(target in expected,'REOPEN_TARGET_MISSING_FROM_BACKUP')
    recovery={'source':str((source/target).resolve()),'backup':str((backup/target).resolve()),'sha256':expected[target]}
    # Observer/content evidence is independently checked by the coordinator/acceptance producer.
    # Hash binding here prevents a different prepared evidence set from being substituted later.
    for k in ('editorBaseline','observerBaseline'):
        item=review_api.project_evidence(v[k]['path'])
        profiles.require(profiles.sha256(item)==v[k]['sha256'],'REOPEN_EVIDENCE_CHANGED:'+k)
    profiles.require(isinstance(v.get('bridgeRunId'),str) and re.fullmatch('[0-9a-f-]{36}',v['bridgeRunId']),'REOPEN_BRIDGE_ID')
    profiles.require(profiles.sha256(manifest)==v['accountBaselineSha256'],'REOPEN_ACCOUNT_MANIFEST_CHANGED')
    profiles.require(profiles.sha256(path)==review_sha,'REOPEN_REVIEW_CHANGED')
    return v,b,{'path':str(path),'sha256':review_sha,'accountManifest':str(manifest),
                'accountManifestSha256':v['accountBaselineSha256'],'recovery':recovery}

def emit_recovery_checks(binding):
    """Final launch checks against the exact review that built this one-shot probe."""
    recovery=binding['recovery'];lit=readonly.ps_literal
    items=((binding['path'],binding['sha256'],'REOPEN_REVIEW_CHANGED'),
           (binding['accountManifest'],binding['accountManifestSha256'],'REOPEN_ACCOUNT_MANIFEST_CHANGED'),
           (recovery['source'],recovery['sha256'],'REOPEN_SAVED_BASELINE_CHANGED'),
           (recovery['backup'],recovery['sha256'],'REOPEN_RECOVERY_COPY_CHANGED'))
    return '\n'.join(" if((Get-FileHash -LiteralPath "+lit(path)+" -Algorithm SHA256).Hash -ine "+lit(digest)+"){throw "+lit(reason)+"}" for path,digest,reason in items)


def emit_wrapper(run,image,image_sha,hashes,request_id,review_sha,*,binding):
    lit=readonly.ps_literal
    checks='\n'.join(" if((Get-FileHash -LiteralPath (Join-Path $taskRun "+lit(n)+") -Algorithm SHA256).Hash -ine "+lit(h)+"){throw 'REOPEN_ARTIFACT_CHANGED'}" for n,h in hashes.items())
    code="""$ErrorActionPreference='Stop'
$taskRun=$PSScriptRoot
$taskResult=[ordered]@{startedUtc=[DateTime]::UtcNow.ToString('o');helperPid=$PID;executed=$false;exitCode=$null;error=$null;scope='FIXED_REOPEN_ACTION';allowWrites=$true;businessVerified=$false}
try {
 $principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
 if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'NOT_ELEVATED'}
 $claim=[IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$claim.Dispose()
__CHECKS__
 $active=Get-Content -LiteralPath __ACTIVE__ -Raw | ConvertFrom-Json
 if($active.schema -ne 1 -or $active.action -cne 'reopen-current' -or $active.requestId -cne __REQUEST__ -or $active.reviewSha256 -cne __REVIEW_SHA__){throw 'REOPEN_PENDING_LEASE_MISMATCH'}
 if((Get-FileHash -LiteralPath __ACTIVE__ -Algorithm SHA256).Hash -cne (Get-FileHash -LiteralPath __CLAIM__ -Algorithm SHA256).Hash){throw 'REOPEN_PENDING_CLAIM_MISMATCH'}
 if((Get-FileHash -LiteralPath __IMAGE__ -Algorithm SHA256).Hash -ine __IMAGE_SHA__){throw 'GAME_SOURCE_HASH_MISMATCH'}
__RECOVERY_CHECKS__
 $taskResult.executed=$true
 # PS5 redirection defaults to UTF-16; write the receipt as UTF-8 without BOM.
 $taskStdoutStream = [IO.File]::Open((Join-Path $taskRun 'stdout.jsonl'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
 $taskStdoutWriter = New-Object IO.StreamWriter($taskStdoutStream,(New-Object Text.UTF8Encoding($false)))
 $taskPreviousOutputEncoding = [Console]::OutputEncoding
 try {
     [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
     $taskStdoutWriter.AutoFlush = $true
     & (Join-Path $taskRun 'hook_reopen_probe.exe') 2> (Join-Path $taskRun 'stderr.txt') | ForEach-Object { $taskStdoutWriter.WriteLine([string]$_) }
     $taskResult.exitCode = $LASTEXITCODE
 } finally {
     [Console]::OutputEncoding = $taskPreviousOutputEncoding
     $taskStdoutWriter.Dispose()
 }
} catch {$taskResult.error=$_.Exception.Message}
finally {
 $taskResult['finishedUtc']=[DateTime]::UtcNow.ToString('o')
 $stream=[IO.File]::Open((Join-Path $taskRun 'exit.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
 $writer=New-Object IO.StreamWriter($stream,(New-Object Text.UTF8Encoding($false)))
 try {$writer.Write(($taskResult|ConvertTo-Json -Depth 8))} finally {$writer.Dispose()}
}
""".replace('__CHECKS__',checks).replace('__RECOVERY_CHECKS__',emit_recovery_checks(binding)).replace('__IMAGE__',lit(image)).replace('__IMAGE_SHA__',lit(image_sha)).replace('__ACTIVE__',lit(ROOT/'.runtime/editor-bridge/native-dispatch/native-active.json')).replace('__CLAIM__',lit(ROOT/'.runtime/editor-bridge/native-dispatch'/request_id/'reopen-claim.json')).replace('__REQUEST__',lit(request_id)).replace('__REVIEW_SHA__',lit(review_sha))
    (run/'invoke-reopen-probe.ps1').write_text(code,encoding='utf-8-sig')

def compile_probe(run):
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vcvars=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat';profiles.require(vcvars.is_file(),'MSVC_UNAVAILABLE')
    common=f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /FI"{run/"target_config.h"}" '
    lines=['@echo off',f'call "{vcvars}" >nul','if errorlevel 1 exit /b 1']
    for name in SOURCES:
        lines += [common+f'/c "{NATIVE/name}" /Fo:"{run/(Path(name).stem+".obj")}"','if errorlevel 1 exit /b 1']
    objects=' '.join('"'+str(run/(Path(n).stem+'.obj'))+'"' for n in SOURCES)
    lines += [common+f'/LD "{NATIVE/"hook_reopen_receipt.cpp"}" /Fo:"{run/"hook_reopen_receipt.obj"}" /Fe:"{run/"hook_reopen_receipt.dll"}" /link User32.lib '+objects,'if errorlevel 1 exit /b 1',
              common+f'"{NATIVE/"hook_reopen_probe.cpp"}" /Fo:"{run/"hook_reopen_probe.obj"}" /Fe:"{run/"hook_reopen_probe.exe"}" /link User32.lib Advapi32.lib','exit /b %ERRORLEVEL%']
    (run/'build.cmd').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    r=subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')],cwd=run,text=True,capture_output=True)
    (run/'build.log').write_text((r.stdout or '')+(r.stderr or ''),encoding='utf-8');profiles.require(r.returncode==0,'REOPEN_BUILD_FAILED:'+str(run/'build.log'))
    return vs

def emit_header(run,profile,session,context,*,deadline,message,nonce):
    defs=readonly.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce)
    catalog.append_header(run,catalog.load_profile());lifecycle.append_header(run,lifecycle.load_profile());scheduler.append_header(run,scheduler.load_profile());guards.append_header(run,guards.load_profile())
    h=run/'target_config.h';text=h.read_text(encoding='utf-8').replace('// Generated readonly bootstrap. HR_ACTION=0; no scene action is linked.','// Dedicated reviewed reopen-current profile. One attempted call, asynchronous business pending.')
    text=text.replace('#define HR_ACTION 0ULL','#define HR_ACTION 4ULL').replace('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')
    text=text.replace('hook_receipt.dll','hook_reopen_receipt.dll')
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define HR_REOPEN_ACTION_REVIEWED 1\n#define HR_REOPEN_EXPECTED_LEVEL_ID 1073741840\n#define HR_REOPEN_ALLOWED_CALLS 1\n#define HR_REOPEN_REVIEW_NONCE HR_NONCE\n#define HR_REOPEN_ALLOWED_SCHEDULER_MASK ((1U<<0)|(1U<<2)|(1U<<5))\n#define HR_REOPEN_GUARD_RESULT_VERSION 2\n'
    entities=context['entities']
    text+='#include <cstdint>\n#define HR_REOPEN_EXPECTED_CONTEXT '+context['pointers']['currentContext']+'ULL\n#define HR_REOPEN_EXPECTED_ENTITY_COUNT '+str(len(entities))+'\n'
    for macro,key,width in [('HR_EXPECTED_ENTITY_IDS','id',32),('HR_EXPECTED_CONFIG_IDS','configId',32),('HR_EXPECTED_OWNER_POINTERS','owner',64),('HR_EXPECTED_CONFIG_POINTERS','config',64),('HR_EXPECTED_ENTITY_CONTEXTS','context',64)]:
        values=','.join(str(e[key])+('ULL' if width==64 else 'U') for e in entities)
        text+=f'constexpr std::uint{width}_t {macro}[]={{'+values+'};\n'
    rows=','.join('{'+','.join([str(e['id'])+'U',str(e['configId'])+'U',str(e['owner'])+'ULL',str(e['config'])+'ULL',str(e['context'])+'ULL'])+'}' for e in entities)
    text+='#define HR_REOPEN_EXPECTED_ENTITY_ROWS '+rows+'\n'
    h.write_text(text,encoding='utf-8')
    return dict(defs,HR_ACTION=4,GS_BOOTSTRAP_READONLY=0,HR_DLL_PATH=str(run/'hook_reopen_receipt.dll'))

def prepare(session_path,review_path,*,output_root=ROOT/'.runtime/game-executor/reopen-current'):
    session=profiles.validate_session(review_api.read_json(session_path));profile=profiles.load_profile();disk=profiles.verify_disk(profile)
    review,base,binding=validate_review(review_path,session)
    run=readonly.output_directory(output_root)
    k,u=profiles.windows_api()
    expires=datetime.fromisoformat(review['expiresUtc'].replace('Z','+00:00'))
    auth=review_api.read_json(ROOT/'.runtime/editor-bridge/current-elevated-session.json')
    cutoff=datetime.fromisoformat(auth['deadlineUtc'].replace('Z','+00:00'))
    remaining=min(120,(expires-datetime.now(timezone.utc)).total_seconds(),(cutoff-datetime.now(timezone.utc)).total_seconds())
    profiles.require(remaining>=15,'REOPEN_REVIEW_TOO_CLOSE_TO_EXPIRY')
    deadline=k.GetTickCount64()+int(remaining*1000);nonce=secrets.randbits(63)|1
    message=u.RegisterWindowMessageW('Miliastra.Reopen.'+secrets.token_hex(16));profiles.require(message!=0,'REGISTER_MESSAGE_FAILED')
    defs=emit_header(run,profile,session,base['context'],deadline=deadline,message=message,nonce=nonce)
    sources={p.name:profiles.sha256(p) for p in NATIVE.iterdir() if p.is_file() and p.suffix in ('.cpp','.h','.inc')}
    prepared={'scope':'FIXED_REOPEN_ACTION','action':'reopen-current','allowWrites':True,'businessVerified':False,'requestId':review['requestId'],'session':session,'createdUtc':datetime.now(timezone.utc).isoformat(),'deadlineTick':deadline,'nativeDefinitions':dict(defs,HR_ACTION=4,GS_BOOTSTRAP_READONLY=0,HR_DLL_PATH=str(run/'hook_reopen_receipt.dll')),'sources':sources,'reviewBinding':binding,'reviewPath':binding['path'],'reviewSha256':binding['sha256'],'profileSha256':guards.PROFILE_SHA256,'baselineHashes':base['evidenceHashes'],'reopenProfileSha256':guards.PROFILE_SHA256,'reopenDecoderSha256':profiles.sha256(Path(guards.__file__))}
    prepared.update(profileSha256=profiles.PROFILE_SHA256,launchable=True,compileOnly=False,
        levelObservationProfileSha256=readonly.level_api.LEVEL_PROFILE_SHA256,
        levelCatalogProfileSha256=catalog.PROFILE_SHA256,lifecycleTypeProfileSha256=lifecycle.PROFILE_SHA256,
        schedulerCoroutinesProfileSha256=scheduler.PROFILE_SHA256,
        schedulerCoroutinesDecoderSha256=profiles.sha256(Path(scheduler.__file__)),
        reopenGuardsProfileSha256=guards.PROFILE_SHA256,reopenGuardsHeaderSha256=guards.HEADER_SHA256,
        reopenGuardsDecoderSha256=profiles.sha256(Path(guards.__file__)))
    readonly.write_json(run/'prepared.json',prepared);toolchain=compile_probe(run)
    profiles.require(all(profiles.sha256(NATIVE/n)==v for n,v in sources.items()),'REOPEN_BUILD_SOURCE_CHANGED')
    _,_,current_binding=validate_review(review_path,session)
    profiles.require(current_binding==binding,'REOPEN_REVIEW_CHANGED_DURING_BUILD')
    profiles.validate_session(session);profiles.require(k.GetTickCount64()<deadline,'REOPEN_BUILD_EXPIRED')
    claims=ROOT/'.runtime/game-executor/reopen-claims';claims.mkdir(exist_ok=True,parents=True)
    readonly.write_json(claims/(review['requestId']+'.json'),{'reviewSha256':binding['sha256'],'run':str(run),'requestId':review['requestId'],'noReplay':True})
    hashes={n:profiles.sha256(run/n) for n in ('hook_reopen_receipt.dll','hook_reopen_probe.exe','target_config.h','prepared.json')}
    emit_wrapper(run,session['image'],disk['sha256'],hashes,review['requestId'],binding['sha256'],binding=binding);hashes['invoke-reopen-probe.ps1']=profiles.sha256(run/'invoke-reopen-probe.ps1')
    result={'run':str(run),'wrapper':str(run/'invoke-reopen-probe.ps1'),'hashes':hashes,'toolchain':toolchain,'scope':'FIXED_REOPEN_ACTION','requestId':review['requestId'],'session':session,'action':'reopen-current','targetPid':session['pid'],'targetTid':session['tid'],'launchable':True,'executed':False,'allowWrites':True,'businessVerified':False,'deadlineTick':deadline}
    readonly.write_json(run/'build-result.json',result);return result
