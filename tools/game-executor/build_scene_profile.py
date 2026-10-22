"""Build an explicit-session, evidence-gated native profile. Never installs a hook."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
import math
import mmap
import os
from pathlib import Path
import secrets
import struct
import subprocess

import native_profiles as profile_api
import native_write_review as review_api
import build_readonly_profile as readonly
import native_level_observation as level_api

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / '.runtime/game-executor/scene-cli'
NATIVE = ROOT / 'tools/game-executor/native'
TARGET_IMAGE = profile_api.TARGET_IMAGE
# No implicit level or stale session. Environment support is explicit legacy CLI
# compatibility; each build still requires a current validated session record.
LEVEL = int(os.environ['MILIASTRA_LEVEL']) if os.environ.get('MILIASTRA_LEVEL') else None
CURRENT_SESSION = ROOT / '.runtime/game-executor/current-native-session.json'
NATIVE_PROFILE = profile_api.load_profile()
# REMOVED 2026-10-09 (user directive): the template whitelist.
#
# Three hand-maintained copies of a 51-id allowlist used to gate every create -- here, in
# tools/editor-bridge/elevated-request.py (NATIVE_TEMPLATES) and in
# tools/editor-bridge/elevated-runner.ps1 ($templateWhitelist) -- against a live catalog the
# editor reports as 2722 entries. Nothing outside those 51 ids had ever been sent (693 CLI
# journal claims, 109 creates, 51 distinct ids), so the list measured itself, not the
# sandbox. It is gone: a create now accepts any uint32 templateId and the native layer is
# the authority on whether an id is real.
#
# Look an id up in the catalog before requesting it -- as guidance, NOT as a gate:
#   .runtime/verification/interface-experiments-20260928/bridge-surface/prefab-catalog.json
#   (2722 entries: registryId, name, iconPath, nativeKind)
TEMPLATE_ID_MAX = 2 ** 32 - 1


def is_template_id(value) -> bool:
    """Any uint32 is a templateId. Deliberately NOT a membership test."""
    return type(value) is int and 0 < value <= TEMPLATE_ID_MAX


# Mirrors game_context_snapshot.h / game_scene_action.h. MAX_ENTITIES is the snapshot's fixed
# capacity: it is the ceiling on how many entities a level may hold for ANY write action to
# run, because the action precondition is a complete snapshot. MAX_BATCH is how many one
# callback may create -- bounded so a single request cannot exceed what the snapshot can
# hold, and because the receipt carries an id per placement.
MAX_ENTITIES = 512
LARGE_MAX_ENTITIES = 4096
MAX_BATCH = 256
MAX_STACK = 32
SNAPSHOT_BYTES = 184 + MAX_STACK * 8 + MAX_ENTITIES * 64
LARGE_SNAPSHOT_BYTES = 184 + MAX_STACK * 8 + LARGE_MAX_ENTITIES * 64

TIMESTAMP = NATIVE_PROFILE['image']['timestamp']
IMAGE_SIZE = NATIVE_PROFILE['image']['sizeOfImage']
ANCHORS = {name:(int(row['rva'],16),row['bytes']) for name,row in NATIVE_PROFILE['anchors'].items()}



def write_json(path: Path, value) -> None:
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def vector(values, *, positive=False) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError('Exactly three vector components are required')
    result = tuple(struct.unpack('<f', struct.pack('<f', float(v)))[0] for v in values)
    if not all(math.isfinite(v) and (not positive or v > 0) for v in result):
        raise ValueError('Vectors must be finite float32 values; scale must be positive')
    return result


def validate_baseline(value: dict, action: str, template_id: int | None = None,
                      templates: tuple[int, ...] = ()) -> list[int]:
    c = value['counts']
    layouts = {(1, SNAPSHOT_BYTES): MAX_ENTITIES, (2, LARGE_SNAPSHOT_BYTES): LARGE_MAX_ENTITIES}
    capacity = layouts.get((value['version'], value['structureSize']), 0)
    if (not capacity or value['status']['value'] != 0 or
        value['flags']['value'] & 927 != 927 or value['flags']['value'] & 96 or c['activeKey'] != 0 or c['entityRejected'] != 0 or
        c['entityCaptured'] != c['entityValidEntries'] or c['entityCaptured'] != len(value['entities']) or
        not 1 <= c['entityCaptured'] <= capacity or c['peTimestamp'] != TIMESTAMP or c['peImageSize'] != IMAGE_SIZE):
        raise ValueError('Complete supported-build context-zero baseline required')
    ids = [e['id'] for e in value['entities']]
    if len(set(ids)) != len(ids) or any(type(i) is not int or not 0 < i < 2**32 for i in ids):
        raise ValueError('Invalid or duplicate baseline entity IDs')
    if any(e['flags']['value'] & 79 != 79 for e in value['entities']):
        raise ValueError('All baseline owner/key/config/context checks must pass')
    if action in ('create', 'creature-create', 'create-batch') and len(ids) >= capacity:
        raise ValueError('Create requires capacity')
    if action == 'create-batch':
        wanted = set(templates)
        if not wanted:
            raise ValueError('Batch requires at least one placement')
        if len(templates) > MAX_BATCH:
            raise ValueError('Batch exceeds the single-callback limit of %d' % MAX_BATCH)
        if len(ids) + len(templates) > capacity:
            raise ValueError('Batch would exceed the snapshot capacity of %d entities' % capacity)
        for candidate in templates:
            if not is_template_id(candidate):
                raise ValueError('Batch template id is not a uint32: ' + repr(candidate))
        return ids
    if action in ('create', 'creature-create'):
        if not is_template_id(template_id):
            raise ValueError('Template id is not a uint32: ' + repr(template_id))
    return ids


def windows_api():
    return profile_api.windows_api()


def resolve_level(level_id=None):
    selected = level_id if level_id is not None else (int(os.environ['MILIASTRA_LEVEL']) if os.environ.get('MILIASTRA_LEVEL') else None)
    if type(selected) is not int or not 0 < selected < 2**32:
        raise ValueError('Explicit --level-id or MILIASTRA_LEVEL is required; no default level is selected')
    return selected


def resolve_session(session_path=None):
    selected = Path(session_path) if session_path is not None else CURRENT_SESSION
    if not selected.is_file():
        raise ValueError('Fresh native session JSON required; run build_readonly_profile.py discover first')
    session = readonly.read_json(selected)
    return selected.resolve(), profile_api.validate_session(session)


def verify_disk_build():
    return profile_api.verify_disk(NATIVE_PROFILE)


def ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def emit_wrapper(run: Path, hashes: dict, reviewed: dict) -> None:
    artifacts = ',\n'.join("        @(" + ps_literal(name) + ',' + ps_literal(sha) + ')' for name, sha in hashes.items())
    script = """$ErrorActionPreference = 'Stop'
$taskRun = $PSScriptRoot
$taskResult = [ordered]@{startedUtc=[DateTime]::UtcNow.ToString('o');helperPid=$PID;executed=$false;exitCode=$null;error=$null}
try {
    $taskIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal($taskIdentity)
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'NOT_ELEVATED' }
    $taskClaim = [IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $taskClaim.Dispose()
    foreach ($taskArtifact in @(
__ARTIFACTS__
    )) {
        if ((Get-FileHash -LiteralPath (Join-Path $taskRun $taskArtifact[0]) -Algorithm SHA256).Hash -ine $taskArtifact[1]) { throw 'ARTIFACT_CHANGED' }
    }
    if ((Get-FileHash -LiteralPath __GAME_IMAGE__ -Algorithm SHA256).Hash -ine __GAME_SHA__) { throw 'GAME_SOURCE_HASH_MISMATCH' }
    if ((Get-FileHash -LiteralPath __REVIEW_PATH__ -Algorithm SHA256).Hash -ine __REVIEW_SHA__) { throw 'REVIEW_CHANGED' }
    if ((Get-FileHash -LiteralPath __FORMAL_GIL__ -Algorithm SHA256).Hash -ine __GIL_SHA__) { throw 'FORMAL_GIL_CHANGED_SINCE_REVIEW' }
    if ((Get-FileHash -LiteralPath __RECOVERY_COPY__ -Algorithm SHA256).Hash -ine __GIL_SHA__) { throw 'RECOVERY_COPY_CHANGED' }
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
""".replace('__ARTIFACTS__', artifacts).replace('__GAME_IMAGE__', ps_literal(TARGET_IMAGE)).replace('__GAME_SHA__', ps_literal(NATIVE_PROFILE['image']['sha256'])).replace('__REVIEW_PATH__', ps_literal(reviewed['reviewPath'])).replace('__REVIEW_SHA__', ps_literal(reviewed['reviewSha256'])).replace('__FORMAL_GIL__', ps_literal(reviewed['targetGil'])).replace('__GIL_SHA__', ps_literal(reviewed['recovery']['sha256'])).replace('__RECOVERY_COPY__', ps_literal(reviewed['recovery']['backup']))
    with (run/'invoke-fixed-probe.ps1').open('x', encoding='utf-8-sig') as stream:
        stream.write(script)


def build_profile(action='inspect', *, baseline=None, template_id=20001200,
                  position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
                  placements=None, session_path=None, level_id=None, review_path=None, reopen_prerequisites=False,
                  place_builtin=1, large_scene=False) -> dict:
    if type(large_scene) is not bool or (large_scene and action != 'inspect'):
        raise ValueError('LARGE_SCENE_INSPECT_TRUE_ONLY')
    if type(reopen_prerequisites) is not bool or (reopen_prerequisites and action != 'inspect'):
        raise ValueError('REOPEN_PREREQUISITES_INSPECT_TRUE_ONLY')
    if action not in ('inspect', 'create', 'creature-create', 'create-batch', 'save'):
        raise ValueError('Unsupported operation')
    # The layout factory's 3rd argument is a caller-supplied mode flag, always sent as 1 until
    # now (native/scene_calls.cpp:33). It is a parameter only so a reviewed probe build can ask
    # whether a 3xxxxxxx template needs a different value; 1 reproduces the drag caller exactly.
    if type(place_builtin) is not int or not 0 <= place_builtin <= 255:
        raise ValueError('HR_PLACE_BUILTIN must be an unsigned byte (0..255)')
    level_id = resolve_level(level_id)
    if action != 'inspect' and review_path is None:
        raise ValueError('NATIVE_WRITE_REVIEW_REQUIRED: complete runtime baseline and coordinator evidence are required before preparation')
    session_file, session = resolve_session(session_path)
    if action == 'inspect':
        options = dict(level_catalog=True, lifecycle_type=True, scheduler_coroutines=True, reopen_guards=True) if reopen_prerequisites else {}
        result = readonly.prepare(session_file, output_root=OUTPUT / 'inspect', large_scene=large_scene, **options)
        if reopen_prerequisites: result['reopenPrerequisites'] = True
        result.update(action='inspect', expectedLevelId=level_id, session=session,
                      wrapperName='invoke-readonly-probe.ps1')
        return result
    position, rotation, scale = vector(position), vector(rotation), vector(scale, positive=True)
    # Normalise the batch request here so the C header only ever sees validated numbers.
    batch = None
    if action == 'create-batch':
        if not isinstance(placements, list) or not 1 <= len(placements) <= MAX_BATCH:
            raise ValueError('Batch requires 1..%d placements' % MAX_BATCH)
        for spec in placements:
            if not isinstance(spec, dict) or not is_template_id(spec.get('template_id')):
                raise ValueError('Batch template id must be a uint32 integer, not a boolean')
            for key in ('position', 'rotation', 'scale'):
                values = spec.get(key, (0, 0, 0) if key == 'rotation' else None)
                if (not isinstance(values, (list, tuple)) or len(values) != 3 or
                    any(type(v) not in (int, float) for v in values)):
                    raise ValueError('Batch vectors must have three numbers, not booleans or strings')
        batch = [(int(spec['template_id']), vector(spec['position']),
                  vector(spec.get('rotation', (0, 0, 0))), vector(spec['scale'], positive=True))
                 for spec in (placements or [])]
    request = {'action':action, 'levelId':level_id}
    if action in ('create', 'creature-create'):
        request.update(templateId=template_id, position=position, rotation=rotation, scale=scale)
    elif action == 'create-batch':
        request['placements'] = [dict(template_id=t,position=p,rotation=r,scale=z) for t,p,r,z in batch]
    reviewed = review_api.validate_review(review_path,session,level_id,request)
    proven = reviewed['baseline']
    if baseline is not None and any(baseline.get(key) != proven.get(key) for key in ('counts','pointers','entities','origin')):
        raise ValueError('Supplied baseline differs from independently decoded reviewed evidence')
    baseline = proven
    ids = validate_baseline(baseline, action, template_id, tuple(t for t,_,_,_ in (batch or [])))
    verify_disk_build()
    k,u = windows_api()
    run = OUTPUT / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + action + '-' + secrets.token_hex(4))
    run.mkdir(parents=True)
    review_api.claim_review(reviewed,run)
    tag = secrets.token_hex(16); message = 'Miliastra.Scene.Fixed.' + tag
    message_id = u.RegisterWindowMessageW(message)
    if not message_id:
        raise C.WinError(C.get_last_error())
    values = dict(HR_NONCE=secrets.randbits(63)|1, HR_MESSAGE_NAME=message,
        HR_MAPPING='Local\\Miliastra.Scene.Fixed.'+tag, HR_TARGET_PID=session['pid'], HR_TARGET_TID=session['tid'],
        HR_TARGET_CREATION=session['processCreation'], HR_TARGET_THREAD_CREATION=session['threadCreation'], HR_TARGET_IMAGE=str(TARGET_IMAGE), HR_MESSAGE_ID=message_id,
        HR_DEADLINE=k.GetTickCount64()+180000, HR_DLL_PATH=str(run/'hook_receipt.dll'),
        HR_ATTEMPT_FILE=str(run/'attempt.used'), HR_READ_CONTEXT=1, HR_GAME_TIMESTAMP=TIMESTAMP,
        HR_GAME_IMAGE_SIZE=IMAGE_SIZE, HR_CONTEXT_ANCHOR_RVA=ANCHORS['CONTEXT'][0],
        # creature-create drives the SAME native branch as create. The native side has no
        # entity-category parameter and no template whitelist of its own (native/scene_calls.h:15-19,
        # native/game_scene_action.cpp:184); the family distinction lives entirely in the three
        # template whitelists. If the live probe shows a creature needs a different mode flag,
        # the change is HR_PLACE_BUILTIN below, not a new HR_ACTION.
        HR_ACTION={'inspect':0,'create':1,'creature-create':1,'save':2,'create-batch':3}[action],
        HR_PLACE_BUILTIN=place_builtin,
        HR_EXPECTED_LEVEL=level_id, HR_TEMPLATE_ID=template_id, GS_BOOTSTRAP_READONLY=0,
        GS_REVIEWED_ACTION_PROFILE=1, HR_ACTION_PROFILE_REVIEWED=1,
        HR_EXPECTED_CONTEXT=int(baseline['pointers']['currentContext'],16),
        HR_LEVEL_MANAGER_OFFSET=int(reviewed['writeProfile']['levelManagerOffset'],16),
        HR_STACK_PUMP_RVA=int(NATIVE_PROFILE['callbackStackRvas'][0],16),
        HR_STACK_OUTER_RVA=int(NATIVE_PROFILE['callbackStackRvas'][1],16))
    values['HR_DEADLINE'] = min(values['HR_DEADLINE'], k.GetTickCount64()+int((datetime.fromisoformat(reviewed['review']['expiresUtc'].replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds()*1000))
    if baseline['version'] == 2:
        values['GS_LARGE_SCENE'] = 1
    def float_literal(v):
        text = format(v, '.9g')
        return text + ('f' if '.' in text or 'e' in text else '.0f')
    header = run/'target_config.h'
    level_profile=level_api.load_profile()
    with header.open('x', encoding='utf-8') as stream:
        stream.write('#define GS_READ_LEVEL_METADATA 1\n')
        for name, raw in level_profile['layout'].items():
            stream.write('#define '+name+' '+raw+'ULL\n')
        for key, value in values.items():
            literal = 'L'+json.dumps(value) if isinstance(value, str) else str(value)+'ULL'
            stream.write(f'#define {key} {literal}\n')
        for name, raw in NATIVE_PROFILE['layout'].items():
            stream.write('#define '+name+' '+raw+'ULL\n')
        for name, (rva, _) in ANCHORS.items():
            if name != 'CONTEXT': stream.write('#define HR_'+name+'_ANCHOR_RVA '+hex(rva)+'ULL\n')
        stream.write('#define GS_PROFILE_ANCHOR_RVAS '+','.join(hex(ANCHORS[name][0]) for name in profile_api.ANCHOR_NAMES)+'\n')
        stream.write('#define GS_PROFILE_ANCHOR_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(ANCHORS[name][1]))+'}' for name in profile_api.ANCHOR_NAMES)+'\n')
        stream.write('#define GS_PROFILE_STACK_RVAS '+','.join(NATIVE_PROFILE['callbackStackRvas'])+'\n')
        stream.write('#define GS_PROFILE_HOTFIX_RVAS '+','.join(NATIVE_PROFILE['defaultHotfixByteRvas']+reviewed['writeProfile']['additionalDefaultHotfixByteRvas'])+'\n')
        for name, (_, encoded) in ANCHORS.items():
            stream.write('#define HR_'+name+'_ANCHOR '+','.join(hex(b) for b in bytes.fromhex(encoded))+'\n')
        if ids:
            # Emitted as a brace-initialised array rather than a comma macro: braces accept
            # newlines, so a level with hundreds of ids needs no line continuations.
            stream.write('[[maybe_unused]] static constexpr unsigned int HR_EXPECTED_ENTITY_IDS[] = {\n' +
                         ''.join('    ' + ','.join(str(v) for v in ids[at:at + 16]) + ',\n'
                                 for at in range(0, len(ids), 16)) + '};\n')
        for array_name, field, wide in [('HR_EXPECTED_OWNER_POINTERS','owner',True),('HR_EXPECTED_CONFIG_POINTERS','config',True),('HR_EXPECTED_CONFIG_IDS','configId',False),('HR_EXPECTED_ENTITY_CONTEXTS','context',True)]:
            row_values = [(int(e[field],16) if isinstance(e[field],str) else int(e[field])) for e in baseline['entities']]
            stream.write('[[maybe_unused]] static constexpr '+('unsigned long long ' if wide else 'unsigned int ')+array_name+'[] = {'+','.join(str(v)+('ULL' if wide else 'U') for v in row_values)+'};\n')
        for name, v in [('POSITION',position),('ROTATION',rotation),('SCALE',scale)]:
            stream.write('#define HR_'+name+' '+','.join(float_literal(x) for x in v)+'\n')
        if batch is not None:
            stream.write('#define HR_PLACEMENT_COUNT %d\n' % len(batch))
            stream.write('[[maybe_unused]] static constexpr unsigned int HR_PLACEMENT_TEMPLATE[HR_PLACEMENT_COUNT] = {\n' +
                         ''.join('    ' + ','.join(str(tid) for tid in group) + ',\n'
                                 for group in [ [r[0] for r in batch[at:at + 12] ]
                                                for at in range(0, len(batch), 12) ]) + '};\n')
            stream.write('[[maybe_unused]] static constexpr float HR_PLACEMENT_TRANSFORM[HR_PLACEMENT_COUNT * 9] = {\n' +
                         ''.join('    ' + ','.join(float_literal(x) for row in batch[at:at + 4]
                                                   for v in (row[1], row[2], row[3]) for x in v) + ',\n'
                                 for at in range(0, len(batch), 4)) + '};\n')
    if baseline is not None:
        write_json(run/'baseline-context.json', baseline)
    write_json(run/'target-profile.json', values)
    source_files=tuple(dict.fromkeys((*readonly.SOURCES,'game_scene_action.cpp','game_scene_action.h','scene_calls.cpp','scene_calls.h')))
    source_hashes={name:digest(NATIVE/name) for name in source_files}
    prepared = dict(levelObservationProfileSha256=level_api.LEVEL_PROFILE_SHA256,sources=source_hashes,profileId=NATIVE_PROFILE['profileId'],profileSha256=profile_api.PROFILE_SHA256,
        session=session,launchable=True,compileOnly=False,allowWrites=True,
        writeProfileId=reviewed['writeProfile']['profileId'],writeProfileSha256=review_api.WRITE_PROFILE_SHA256,
        reviewSha256=reviewed['reviewSha256'],reviewPath=reviewed['reviewPath'],
        request=request,disk=NATIVE_PROFILE['image'],nativeSnapshotVersion=baseline['version'])
    write_json(run/'prepared.json',prepared)
    vswhere = Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'], text=True).strip()
    vcvars = Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    if not vs or not vcvars.is_file():
        raise ValueError('Local x64 MSVC toolchain unavailable')
    common = f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /FI"{header}" '
    objects = ['game_context_snapshot'] + (['game_scene_action','scene_calls'] if action != 'inspect' else [])
    lines = ['@echo off', f'call "{vcvars}" >nul', 'if errorlevel 1 exit /b 1']
    for name in objects:
        lines += [common+f'/c "{NATIVE/(name+".cpp")}" /Fo:"{run/(name+".obj")}"', 'if errorlevel 1 exit /b 1']
    linked = ' '.join(f'"{run/(name+".obj")}"' for name in objects)
    lines += [common+f'/LD "{NATIVE/"hook_receipt.cpp"}" /Fo:"{run/"hook_receipt.obj"}" /Fe:"{run/"hook_receipt.dll"}" /link User32.lib '+linked,
              'if errorlevel 1 exit /b 1',
              common+f'"{NATIVE/"hook_receipt_probe.cpp"}" /Fo:"{run/"hook_receipt_probe.obj"}" /Fe:"{run/"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib',
              'exit /b %ERRORLEVEL%']
    with (run/'build.cmd').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines)+'\n')
    built = subprocess.run(['cmd.exe','/d','/c',str(run/'build.cmd')], cwd=run, text=True, capture_output=True)
    with (run/'build.log').open('x', encoding='utf-8') as stream:
        stream.write((built.stdout or '')+(built.stderr or ''))
    if built.returncode:
        raise RuntimeError(f'MSVC build failed; see {run / "build.log"}')
    if source_hashes != {name:digest(NATIVE/name) for name in source_files}:
        raise ValueError('Native sources changed during build')
    profile_api.validate_session(session)
    if k.GetTickCount64() >= values['HR_DEADLINE']: raise ValueError('Reviewed profile expired during preparation')
    hashes = {name:digest(run/name) for name in ('hook_receipt.dll','hook_receipt_probe.exe','target_config.h','prepared.json','baseline-context.json')}
    emit_wrapper(run, hashes, reviewed)
    hashes['invoke-fixed-probe.ps1'] = digest(run/'invoke-fixed-probe.ps1')
    result = dict(run=str(run), action=action, createdUtc=datetime.now(timezone.utc).isoformat(),
                  executed=False, deadlineTick=values['HR_DEADLINE'], targetPid=session['pid'], targetTid=session['tid'],
                  expectedLevelId=level_id, hashes=hashes, templateId=template_id if action in ('create', 'creature-create') else None,
                  position=position, rotation=rotation, scale=scale, toolchain=vs,
                  placementCount=len(batch) if batch is not None else None,
                  session=session,wrapperName='invoke-fixed-probe.ps1',profileId=reviewed['writeProfile']['profileId'],
                  reviewId=reviewed['reviewId'],reviewPath=reviewed['reviewPath'],requestSha256=review_api.canonical_hash(request),
                  targetGil=reviewed['targetGil'],protectedGils=reviewed['protectedGils'],allowWrites=True)
    write_json(run/'build-result.json', result)
    return result
