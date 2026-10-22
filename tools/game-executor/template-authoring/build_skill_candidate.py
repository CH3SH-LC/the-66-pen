"""Compile-only skill action candidate; never launch, queue, or install it.

Live native sources and helper pins remain untouched. Every compilation uses
private source copies, an expired deadline, and PID/TID 1. Review macros select
the internal C++ contract only: this does not create a dispatch authorization.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import mmap
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
EXECUTOR = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EXECUTOR))
import request as requests
import build_readonly_profile as readonly
import native_profiles as profiles

OUTPUT = ROOT / '.runtime/template-authoring/candidates'
DEFAULT_RUNTIME_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-be/skill-runtime-profile.json'
NATIVE_FILES = readonly.SOURCES
TEMPLATE_FILES = ('template_calls.h', 'template_calls.cpp', 'template_catalog.h',
                  'template_catalog_capture.h', 'template_catalog_capture.cpp',
                  'skill_calls.h',
                  'skill_action.h', 'skill_action.cpp',
                  'skill_native_adapter.h', 'skill_native_adapter.cpp')
FUNCTIONS = (0x524250, 0x526de0, 0xd1f8af0, 0x1001c9b0, 0x105792a0, 0x10579330,
             0x1057a440, 0x128ef5b0, 0x102e20f0, 0x102e2180, 0x10da0e00,
             0x10f675e0, 0xf7fe540, 0xf7ff510, 0xb0a8bf0, 0xb0a8ce0, 0xb0a54a0, 0xb0a90c0)
DEFAULT_SERVICE_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-am/currency-runtime-profile.json' 
HOTFIX = tuple(sorted((0x57278c0, 0x573650f, 0x56f593d, 0x56f5932,
    0x56f5946, 0x5707fae, 0x572788e, 0x56fc736, 0x571bfd4, 0x57278c6,
    0x5744b54, 0x5744b5b, 0x5746847, 0x56e94ed, 0x56e94e7, 0x575997e,
    0x5765746, 0x5765747, 0x56e94ea, 0x56e94eb, 0x576572e, 0x576574e)))


def replace_once(text, old, new):
    profiles.require(text.count(old) == 1, 'CANDIDATE_SOURCE_PATTERN_CHANGED:' + old[:80])
    return text.replace(old, new, 1)


def source_copies(run):
    """Copy all required source bytes before patching the isolated native copy."""
    source = run / 'candidate-source'
    originals = {}
    for folder, origin, names in (('native', EXECUTOR / 'native', NATIVE_FILES),
                                  ('template-authoring', HERE, TEMPLATE_FILES)):
        destination = source / folder
        destination.mkdir(parents=True)
        for name in names:
            data = (origin / name).read_bytes()
            (destination / name).write_bytes(data)
            originals[folder + '/' + name] = hashlib.sha256(data).hexdigest()
    native = source / 'native'
    file = native / 'game_context_snapshot.h'
    text = file.read_text(encoding='utf-8')
    old = '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1))'
    new = '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 9 && defined(TA_SKILL_REVIEWED) && TA_SKILL_REVIEWED == 1))'
    file.write_text(replace_once(text, old, new), encoding='utf-8')

    file = native / 'hook_receipt_protocol.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#if HR_ACTION\n#include "game_scene_action.h"',
        '#if HR_ACTION == 9\n#include "../template-authoring/skill_native_adapter.h"\n'
        'static_assert(TA_SKILL_REVIEWED == 1 && HR_READ_CONTEXT == 1, "Skill contract required");\n'
        '#elif HR_ACTION\n#include "game_scene_action.h"')
    text = replace_once(text, '#if HR_ACTION\n    GameSceneActionResult action;',
        '#if HR_ACTION == 9\n    NativeSkillReceipt templateResult;\n#elif HR_ACTION\n    GameSceneActionResult action;')
    text = replace_once(text, 'constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS',
        'constexpr DWORD kReceiptVersion = HR_ACTION == 9 ? 13 : HR_READ_REOPEN_GUARDS')
    file.write_text(text, encoding='utf-8')

    file = native / 'hook_receipt.cpp'
    text = replace_once(file.read_text(encoding='utf-8'),
        '#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 9\n                    ExecuteNativeSkillAction(&receipt->context, &receipt->templateResult);\n'
        '#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')
    file.write_text(text, encoding='utf-8')

    file = native / 'hook_receipt_probe.cpp'
    text = file.read_text(encoding='utf-8')
    # Clear the mapped receipt without a receipt-sized temporary stack object.
    # 2026-10-19（lead 授权）：native 源码已是原地 memset，期望匹配当前真实字节；旧形态仍做替换。
    _legacy_clear = '    *receipt = {};'
    _memset_clear = '    std::memset(receipt, 0, sizeof(*receipt));'
    if text.count(_legacy_clear) == 1:
        text = text.replace(_legacy_clear, _memset_clear, 1)
    else:
        profiles.require(text.count(_memset_clear) == 1,
                         'CANDIDATE_SOURCE_PATTERN_CHANGED:' + _legacy_clear)
    text = replace_once(text, '#if HR_ACTION < 1 || HR_ACTION > 3',
        '#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 9 && defined(TA_SKILL_REVIEWED) && TA_SKILL_REVIEWED == 1))')
    text = replace_once(text, '#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"',
        '#error "Action requires supported contract; skill requires TA_SKILL_REVIEWED"')
    text = replace_once(text, '#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
        '#if HR_ACTION == 9\n                reportedOk = reportedOk && receipt->templateResult.sehCode == 0 &&\n'
        '                    receipt->templateResult.action.code == ge::skills::SkillActionCode::catalog_verified &&\n'
        '                    receipt->templateResult.action.createCalled && receipt->templateResult.afterSceneUnchanged == 1;\n'
        '#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status')
    text = replace_once(text, 'HR_ACTION ? "FIXED_SCENE_ACTION"',
        'HR_ACTION == 9 ? "FIXED_TEMPLATE_SKILL_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"')
    text = replace_once(text, '#if HR_ACTION\n                std::printf(",\\"action\\":',
        SKILL_PROBE + '\n#elif HR_ACTION\n                std::printf(",\\"action\\":')
    file.write_text(text, encoding='utf-8')
    return originals


SKILL_PROBE = r'''#if HR_ACTION == 9
                const auto& skill = receipt->templateResult;
                const auto& outcome = skill.action;
                std::printf(",\"skillResult\":{\"size\":%u,\"version\":%u,\"sehCode\":%u,\"afterSceneUnchanged\":%u,\"code\":%u,\"stage\":%u,\"mainDeltaCode\":%u,\"nameCode\":%u,\"returnedResource\":\"0x%llx\",\"createdId\":%u,\"companionResource\":\"0x%llx\",\"companionOwnId\":%u,\"defaultTable\":\"0x%llx\",\"defaultRecord\":\"0x%llx\",\"defaultType\":%u,\"defaultValue\":%u,\"primaryCountBefore\":%u,\"companionCountBefore\":%u,\"metadataCallsStarted\":%u,\"metadataCallsCompleted\":%u,\"defaultLookupCalled\":%s,\"allocationCalled\":%s,\"createCalled\":%s,\"postCaptureAttempted\":%s,\"mainCatalogVerified\":%s,\"companionCatalogVerified\":%s,\"outcomeUncertain\":%s}",
                    skill.size, skill.version, skill.sehCode, skill.afterSceneUnchanged,
                    static_cast<unsigned int>(outcome.code), static_cast<unsigned int>(outcome.stage),
                    static_cast<unsigned int>(outcome.mainDeltaCode),
                    static_cast<unsigned int>(outcome.nameCode),
                    static_cast<unsigned long long>(outcome.returnedResource), outcome.createdId,
                    static_cast<unsigned long long>(outcome.companionResource), outcome.companionOwnId,
                    static_cast<unsigned long long>(outcome.defaultTable), static_cast<unsigned long long>(outcome.defaultRecord),
                    outcome.defaultType, outcome.defaultValue, outcome.primaryCountBefore, outcome.companionCountBefore,
                    outcome.metadataCallsStarted, outcome.metadataCallsCompleted,
                    outcome.defaultLookupCalled ? "true" : "false", outcome.allocationCalled ? "true" : "false",
                    outcome.createCalled ? "true" : "false", outcome.postCaptureAttempted ? "true" : "false",
                    outcome.mainCatalogVerified ? "true" : "false", outcome.companionCatalogVerified ? "true" : "false",
                    outcome.outcomeUncertain ? "true" : "false");
                const auto printRaw = [](const char* name, const void* data, std::size_t length) {
                    std::printf(",\"%sBytes\":%zu,\"%sHex\":\"", name, length, name);
                    const auto bytes = static_cast<const unsigned char*>(data);
                    for (std::size_t i = 0; i < length; ++i) std::printf("%02x", static_cast<unsigned int>(bytes[i]));
                    std::printf("\"");
                };
                std::printf(",\"observedMainClass\":\"0x%llx\",\"observedCompanionClass\":\"0x%llx\"",
                    static_cast<unsigned long long>(outcome.observedMainClass),
                    static_cast<unsigned long long>(outcome.observedCompanionClass));
                printRaw("skillResult", &skill, sizeof(skill));
                printRaw("beforeCatalog", &skill.workspace.before, sizeof(skill.workspace.before));
                printRaw("afterCatalog", &skill.workspace.after, sizeof(skill.workspace.after));
                printRaw("afterSnapshot", &skill.after, sizeof(skill.after));''' 

def load_inputs(request_path, baseline_run, runtime_profile):
    path = requests.runtime_path(request_path)
    value = requests.validate_request(requests.read_json(path))
    profiles.require(value['action'] == 'create-skill', 'CANDIDATE_SKILL_ONLY')
    profiles.require(path.read_bytes() == requests.canonical_bytes(value), 'CANONICAL_REQUEST_REQUIRED')
    evidence = requests.read_json(path.with_name('review-evidence.json'))
    prepared = requests.read_json(path.with_name('prepared.json'))
    digest = profiles.sha256(path)
    profiles.require(prepared.get('state') == 'prepared-not-dispatchable' and
                     prepared.get('reviewed') is False and prepared.get('dispatchable') is False and
                     prepared.get('requestSha256') == evidence.get('requestSha256') == digest,
                     'PREPARED_REQUEST_BINDING_REQUIRED')
    run = requests.runtime_path(baseline_run)
    profiles.require(run.name == value['runId'] and evidence.get('baselineRun') == str(run) and
                     evidence.get('baselineKind') == 'readonly', 'REQUEST_BASELINE_BINDING')
    profiles.require(evidence.get('baselineEvidenceHashes') == requests._baseline_hashes(run, 'readonly'),
                     'PREPARED_BASELINE_CHANGED')
    snapshot, baseline = requests.review_api.load_baseline(run, 'readonly', value['levelId'])
    for key in requests.SESSION_FIELDS:
        profiles.require(value['session'][key] == baseline['session'][key], 'BASELINE_SESSION:' + key)
    record, _ = readonly.load_decoder().read_probe(run / 'stdout.jsonl')
    raw = bytes.fromhex(record['snapshotHex'])
    profiles.require(len(raw) == snapshot['structureSize'] == 33208, 'BASELINE_RAW_ABI')
    runtime_path = requests.runtime_path(runtime_profile)
    runtime = requests.read_json(runtime_path)
    profile = profiles.load_profile()
    profiles.require(runtime['imageSha256'] == profile['image']['sha256'], 'SKILL_PROFILE_IMAGE')
    profiles.require(tuple(int(f['rva'], 16) for f in runtime['functions']) == FUNCTIONS,
                     'SKILL_FUNCTION_SET')
    profiles.require(tuple(int(rva, 16) for rva in runtime['hotfixZeroRvas']) == HOTFIX,
                     'SKILL_HOTFIX_SET')
    profiles.require(tuple((f['usage'], f['slot'], f['definition']) for f in runtime['classBindings']) ==
        (('0x8a8a', '0x57d3ff8', 68266), ('0xea00', '0x57c98f8', 58345)), 'SKILL_METADATA_CONTRACT')
    profiles.require(runtime['registration']['main']['subtype'] == 6 and
                     runtime['registration']['main']['idBand'] == 6 and
                     runtime['registration']['companion']['guidDomain'] == [0, 1, 4], 'SKILL_REGISTRATION_CONTRACT')
    service_path = requests.runtime_path(DEFAULT_SERVICE_PROFILE)
    service = requests.read_json(service_path)
    profiles.require(service['imageSha256'] == runtime['imageSha256'] and
                     service['metadataSha256'] == runtime['metadataSha256'], 'SERVICE_PROFILE_BUILD')
    create = next((f for f in service['functions'] if int(f['rva'], 16) == 0xb0a90c0), None)
    profiles.require(create is not None and any(int(g['flagRva'], 16) == 0x576574e
                     for g in service['hotfixGates']), 'FULL_CREATION_SERVICE_EVIDENCE')
    profiles.require(create['head32'] == runtime['functions'][-1]['headBytes'], 'FULL_CREATION_SERVICE_ANCHOR')
    disk = profiles.verify_disk(profile)
    with profiles.TARGET_IMAGE.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
        pe = profiles.inspect_pe(image)
        for function in runtime['functions']:
            head = bytes.fromhex(function['headBytes'])
            profiles.require(0 < len(head) == function['headLength'] <= 32, 'SKILL_ANCHOR_LENGTH')
            offset = profiles.rva_offset(pe['sections'], int(function['rva'], 16), len(head), len(image))
            profiles.require(image[offset:offset + len(head)] == head, 'SKILL_DISK_ANCHOR_MISMATCH')
    return value, raw, runtime, profile, disk, {
        'requestPath': str(path), 'requestSha256': digest, 'baselineRun': str(run),
        'baselineEvidenceHashes': evidence['baselineEvidenceHashes'],
        'runtimeProfilePath': str(runtime_path), 'runtimeProfileSha256': profiles.sha256(runtime_path),
        'serviceProfilePath': str(service_path), 'serviceProfileSha256': profiles.sha256(service_path),
        'reviewed': False, 'liveSessionRevalidated': False,
    }


def emit_header(run, value, raw, runtime, profile):
    fixture = {'pid': 1, 'tid': 1, 'processCreation': 1, 'threadCreation': 1,
               'image': str(run / 'compile-only-target.invalid')}
    readonly.emit_header(profile, fixture, run, deadline=1, message_id=0xc001, nonce=1)
    file = run / 'target_config.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#define HR_ACTION 0ULL', '#define HR_ACTION 9ULL')
    text = replace_once(text, '#define GS_BOOTSTRAP_READONLY 1ULL', '#define GS_BOOTSTRAP_READONLY 0ULL')
    text = '// Compile-only expired candidate; review markers are not dispatch authorization.\n' + text
    text += '#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TA_SKILL_REVIEWED 1\n'
    text += '#define TA_SKILL_ANCHOR_RVAS ' + ','.join(hex(rva) for rva in FUNCTIONS) + '\n'
    text += '#define TA_SKILL_ANCHOR_BYTES ' + ','.join(
        '{' + ','.join(hex(b) for b in bytes.fromhex(f['headBytes'])) + '}' for f in runtime['functions']) + '\n'
    text += '#define TA_SKILL_ANCHOR_LENGTHS ' + ','.join(str(f['headLength']) for f in runtime['functions']) + '\n'
    text += '#define TA_SKILL_HOTFIX_RVAS ' + ','.join(hex(rva) for rva in HOTFIX) + '\n'
    text += '#define TA_SKILL_NAME "' + ''.join('\\x%02x' % b for b in value['parameters']['name'].encode('utf-8')) + '"\n'
    text += 'inline constexpr unsigned char kTemplateExpectedSnapshot[] = {\n'
    text += '\n'.join(','.join(str(b) for b in raw[i:i+32]) + ',' for i in range(0, len(raw), 32))
    text += '\n};\n#define TA_EXPECTED_SNAPSHOT kTemplateExpectedSnapshot\n'
    file.write_text(text, encoding='utf-8')


def compile_sources(run):
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
    vcvars = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
    profiles.require(bool(vs) and vcvars.is_file(), 'MSVC_X64_UNAVAILABLE')
    # All source/output paths derive from this repository, not the invoking cwd.
    common = f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run / "target_config.h"}" '
    source = run / 'candidate-source'
    objects = []
    lines = ['@echo off', f'call "{vcvars}" >nul', 'if errorlevel 1 exit /b 1']
    units = [('native', 'game_context_snapshot')] + [('template-authoring', stem) for stem in
        ('template_calls', 'template_catalog_capture', 'skill_action', 'skill_native_adapter')]
    for directory, stem in units:
        obj = run / (stem + '.obj'); objects.append(obj)
        lines.extend([common + f'/c "{source / directory / (stem + ".cpp")}" /Fo:"{obj}"',
                      'if errorlevel 1 exit /b 1'])
    lines.extend([common + f'/LD "{source / "native/hook_receipt.cpp"}" /Fo:"{run / "hook_receipt.obj"}" '
        f'/Fe:"{run / "hook_receipt.dll"}" /link User32.lib ' + ' '.join('"' + str(obj) + '"' for obj in objects),
        'if errorlevel 1 exit /b 1',
        common + f'"{source / "native/hook_receipt_probe.cpp"}" /Fo:"{run / "hook_receipt_probe.obj"}" '
        f'/Fe:"{run / "hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib', 'exit /b %ERRORLEVEL%'])
    (run / 'build.cmd').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    result = subprocess.run(['cmd.exe', '/d', '/c', str(run / 'build.cmd')], cwd=run,
                            capture_output=True, text=True, timeout=180)
    (run / 'build.log').write_text((result.stdout or '') + (result.stderr or ''), encoding='utf-8')
    profiles.require(result.returncode == 0, 'MSVC_BUILD_FAILED:' + str(run / 'build.log'))
    return str(vcvars)


def compile_candidate(request_path, baseline_run, runtime_profile=DEFAULT_RUNTIME_PROFILE):
    value, raw, runtime, profile, disk, inputs = load_inputs(request_path, baseline_run, runtime_profile)
    run = readonly.output_directory(OUTPUT)
    sources = source_copies(run)
    emit_header(run, value, raw, runtime, profile)
    (run / 'baseline-snapshot.bin').write_bytes(raw)
    manifest = {'schemaVersion': 1, 'kind': 'template-skill-compile-candidate-v1',
        'compileOnly': True, 'launchable': False, 'allowWrites': False, 'reviewed': False,
        'nativeCalled': False, 'probeExecuted': False, 'action': 'create-skill', 'actionCode': 9,
        'requestId': value['requestId'], 'requestLevelId': value['levelId'],
        'buildIdentity': {'pid': 1, 'tid': 1, 'deadline': 1}, 'receiptVersion': 13,
        'inputs': inputs, 'originalSourceHashes': sources, 'disk': disk,
        'readonlyProfileSha256': profiles.PROFILE_SHA256,
        'readOnlyPreflight': False,
        'limits': 'Candidate compilation only. Metadata, default-list selection and name allocation may mutate runtime state. 4096 is local catalogue capture capacity, not an official skill limit. No execution occurred. Existing helper cannot dispatch this action.'}
    readonly.write_json(run / 'candidate-inputs.json', manifest)
    compiler = compile_sources(run)
    for relative, before in sources.items():
        folder, name = relative.split('/', 1)
        original = (EXECUTOR / 'native' if folder == 'native' else HERE) / name
        profiles.require(profiles.sha256(original) == before, 'SOURCE_CHANGED_DURING_COMPILE:' + relative)
    profiles.require(inputs['baselineEvidenceHashes'] == requests._baseline_hashes(Path(inputs['baselineRun']), 'readonly'),
                     'BASELINE_CHANGED_DURING_COMPILE')
    manifest.update(ok=True, compiled=True, compiler=compiler, run=str(run),
        completedAtUtc=datetime.now(timezone.utc).isoformat(),
        hashes={str(path.relative_to(run)).replace('\\', '/'): profiles.sha256(path)
            for path in sorted(run.rglob('*')) if path.is_file()})
    readonly.write_json(run / 'candidate-manifest.json', manifest)
    return {key: manifest[key] for key in ('ok', 'run', 'compiled', 'compileOnly', 'launchable',
                                         'allowWrites', 'reviewed', 'nativeCalled', 'probeExecuted')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    skill = sub.add_parser('compile-check')
    skill.add_argument('--request', required=True)
    skill.add_argument('--baseline-run', required=True)
    skill.add_argument('--runtime-profile', default=str(DEFAULT_RUNTIME_PROFILE))
    args = parser.parse_args(argv)
    try:
        result = compile_candidate(args.request, args.baseline_run, args.runtime_profile)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'compileOnly': True,
            'launchable': False, 'allowWrites': False, 'nativeCalled': False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
