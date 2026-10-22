"""Compile-only item action candidate; never launch, queue, or install it.

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
import secrets
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
import snapshot_abi as abi

OUTPUT = ROOT / '.runtime/template-authoring/candidates'
DEFAULT_RUNTIME_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-ap/item-runtime-profile.json'
NATIVE_FILES = readonly.SOURCES
TEMPLATE_FILES = ('template_calls.h', 'template_calls.cpp', 'template_catalog.h',
                  'template_catalog_capture.h', 'template_catalog_capture.cpp',
                  'item_calls.h', 'item_calls.cpp',
                  'item_action.h', 'item_action.cpp',
                  'item_native_adapter.h', 'item_native_adapter.cpp')
ITEM_FUNCTIONS = (0x9b0e050, 0x9b0e0d0, 0x7888da0, 0x144e26f0, 0x7887c70, 0x526de0, 0x524250)
FUNCTIONS = ITEM_FUNCTIONS + (0xb0a90c0,)
DEFAULT_SERVICE_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-am/currency-runtime-profile.json' 
HOTFIX = (0x576f02c, 0x56ece50, 0x56ece56, 0x56ece5b, 0x576574e)


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
    new = '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 6 && defined(TA_ITEM_REVIEWED) && TA_ITEM_REVIEWED == 1))'
    file.write_text(replace_once(text, old, new), encoding='utf-8')

    file = native / 'hook_receipt_protocol.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#if HR_ACTION\n#include "game_scene_action.h"',
        '#if HR_ACTION == 6\n#include "../template-authoring/item_native_adapter.h"\n'
        'static_assert(TA_ITEM_REVIEWED == 1 && HR_READ_CONTEXT == 1, "Item contract required");\n'
        '#elif HR_ACTION\n#include "game_scene_action.h"')
    text = replace_once(text, '#if HR_ACTION\n    GameSceneActionResult action;',
        '#if HR_ACTION == 6\n    NativeItemReceipt templateResult;\n#elif HR_ACTION\n    GameSceneActionResult action;')
    text = replace_once(text, 'constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS',
        'constexpr DWORD kReceiptVersion = HR_ACTION == 6 ? 10 : HR_READ_REOPEN_GUARDS')
    file.write_text(text, encoding='utf-8')

    file = native / 'hook_receipt.cpp'
    text = replace_once(file.read_text(encoding='utf-8'),
        '#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 6\n                    ExecuteNativeItemAction(&receipt->context, &receipt->templateResult);\n'
        '#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);')
    file.write_text(text, encoding='utf-8')

    file = native / 'hook_receipt_probe.cpp'
    text = file.read_text(encoding='utf-8')
    # Clear the mapped receipt without a receipt-sized temporary stack object.
    # 2026-10-19：native 源码已是原地 memset（v2 动作会撑爆 1 MiB 栈，见 hook_receipt_probe.cpp 注释），
    # builder 必须匹配**当前源码真实字节**；旧形态仍做替换，新形态原样通过并断言存在。
    _legacy_clear = '    *receipt = {};'
    _memset_clear = '    std::memset(receipt, 0, sizeof(*receipt));'
    if text.count(_legacy_clear) == 1:
        text = text.replace(_legacy_clear, _memset_clear, 1)
    else:
        profiles.require(text.count(_memset_clear) == 1,
                         'CANDIDATE_SOURCE_PATTERN_CHANGED:' + _legacy_clear)
    text = replace_once(text, '#if HR_ACTION < 1 || HR_ACTION > 3',
        '#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 6 && defined(TA_ITEM_REVIEWED) && TA_ITEM_REVIEWED == 1))')
    text = replace_once(text, '#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"',
        '#error "Action requires supported contract; item requires TA_ITEM_REVIEWED"')
    text = replace_once(text, '#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
        '#if HR_ACTION == 6\n                reportedOk = reportedOk && receipt->templateResult.sehCode == 0 &&\n'
        '                    receipt->templateResult.action.code == ge::templates::ItemActionCode::catalog_verified &&\n'
        '                    receipt->templateResult.action.createCalled && receipt->templateResult.afterSceneUnchanged == 1;\n'
        '#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status')
    text = replace_once(text, 'HR_ACTION ? "FIXED_SCENE_ACTION"',
        'HR_ACTION == 6 ? "FIXED_TEMPLATE_ITEM_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"')
    text = replace_once(text, '#if HR_ACTION\n                std::printf(",\\"action\\":',
        ITEM_PROBE + '\n#elif HR_ACTION\n                std::printf(",\\"action\\":')
    file.write_text(text, encoding='utf-8')
    return originals


ITEM_PROBE = r'''#if HR_ACTION == 6
                const auto& item = receipt->templateResult;
                const auto& outcome = item.action;
                std::printf(",\"itemResult\":{\"size\":%u,\"version\":%u,\"sehCode\":%u,\"afterSceneUnchanged\":%u,\"code\":%u,\"stage\":%u,\"itemCode\":%u,\"itemStage\":%u,\"mainDeltaCode\":%u,\"count\":%lld,\"limit\":%lld,\"createdResource\":\"0x%llx\",\"createdId\":%u,\"companionResource\":\"0x%llx\",\"companionOwnId\":%u,\"metadataInitializationCalled\":%s,\"countCalled\":%s,\"limitInitializationCalled\":%s,\"controllerLookupCalled\":%s,\"allocationCalled\":%s,\"defaultGetterCalled\":%s,\"handlerCalled\":%s,\"createCalled\":%s,\"mainCatalogVerified\":%s,\"companionCatalogVerified\":%s,\"outcomeUncertain\":%s}",
                    item.size, item.version, item.sehCode, item.afterSceneUnchanged,
                    static_cast<unsigned int>(outcome.code), static_cast<unsigned int>(outcome.stage),
                    static_cast<unsigned int>(outcome.item.code), static_cast<unsigned int>(outcome.item.exceptionStage),
                    static_cast<unsigned int>(outcome.mainDeltaCode),
                    static_cast<long long>(outcome.count), static_cast<long long>(outcome.limit),
                    static_cast<unsigned long long>(outcome.createdResource), outcome.createdId,
                    static_cast<unsigned long long>(outcome.companionResource), outcome.companionOwnId,
                    outcome.metadataInitializationCalled ? "true" : "false", outcome.countCalled ? "true" : "false",
                    outcome.limitInitializationCalled ? "true" : "false", outcome.controllerLookupCalled ? "true" : "false",
                    outcome.allocationCalled ? "true" : "false", outcome.item.defaultGetterCalled ? "true" : "false",
                    outcome.item.handlerCalled ? "true" : "false", outcome.createCalled ? "true" : "false",
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
                printRaw("itemResult", &item, sizeof(item));
                printRaw("beforeCatalog", &item.workspace.before, sizeof(item.workspace.before));
                printRaw("afterCatalog", &item.workspace.after, sizeof(item.workspace.after));
                printRaw("afterSnapshot", &item.after, sizeof(item.after));''' 

def load_inputs(request_path, baseline_run, runtime_profile):
    path = requests.runtime_path(request_path)
    value = requests.validate_request(requests.read_json(path))
    profiles.require(value['action'] == 'create-item', 'CANDIDATE_ITEM_ONLY')
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
    # 2026-10-17 双 ABI：基线快照可以是 v1(33208/512) 或 v2(262584/4096)，其它尺寸具名拒绝。
    snapshot_size = abi.validate_snapshot_size(len(raw), 'BASELINE_RAW_ABI')
    profiles.require(len(raw) == snapshot['structureSize'] and
                     snapshot['version'] == abi.version_for_size(snapshot_size) and
                     abi.validate_snapshot_payload(raw, 'BASELINE_RAW_ABI')['bytes'] == snapshot_size,
                     'BASELINE_RAW_ABI')
    runtime_path = requests.runtime_path(runtime_profile)
    runtime = requests.read_json(runtime_path)
    profile = profiles.load_profile()
    profiles.require(runtime['imageSha256'] == profile['image']['sha256'], 'ITEM_PROFILE_IMAGE')
    profiles.require(tuple(int(f['rva'], 16) for f in runtime['functions']) == ITEM_FUNCTIONS,
                     'ITEM_FUNCTION_SET')
    profiles.require(tuple(int(g['flagRva'], 16) for g in runtime['hotfixGuards']) == HOTFIX[:-1],
                     'ITEM_HOTFIX_SET')
    profiles.require(runtime['metadataInitialization']['fixedUsageIndex'] == '0x1b911' and
                     runtime['countMethodInfo']['slotRva'] == '0x58ed380' and
                     runtime['createMethodInfo']['slotRva'] == '0x59369e0', 'ITEM_METADATA_CONTRACT')
    service_path = requests.runtime_path(DEFAULT_SERVICE_PROFILE)
    service = requests.read_json(service_path)
    profiles.require(service['imageSha256'] == runtime['imageSha256'] and
                     service['metadataSha256'] == runtime['metadataSha256'], 'SERVICE_PROFILE_BUILD')
    create = next((f for f in service['functions'] if int(f['rva'], 16) == 0xb0a90c0), None)
    profiles.require(create is not None and any(int(g['flagRva'], 16) == HOTFIX[-1]
                     for g in service['hotfixGates']), 'FULL_CREATION_SERVICE_EVIDENCE')
    runtime['functions'].append(create)
    disk = profiles.verify_disk(profile)
    with profiles.TARGET_IMAGE.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
        pe = profiles.inspect_pe(image)
        for function in runtime['functions']:
            head = bytes.fromhex(function['head32'])
            profiles.require(len(head) == 32, 'ITEM_ANCHOR_LENGTH')
            offset = profiles.rva_offset(pe['sections'], int(function['rva'], 16), 32, len(image))
            profiles.require(image[offset:offset + 32] == head, 'ITEM_DISK_ANCHOR_MISMATCH')
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
    # 逐 run 隔离副本据基线 ABI 打开编译期开关（v1 不定义 GS_LARGE_SCENE，共享头默认仍是 0）。
    snapshot_size = abi.validate_snapshot_size(len(raw), 'BASELINE_RAW_ABI')
    readonly.emit_header(profile, fixture, run, deadline=1, message_id=0xc001, nonce=1,
                         large_scene=bool(abi.large_scene_for_size(snapshot_size)))
    file = run / 'target_config.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#define HR_ACTION 0ULL', '#define HR_ACTION 6ULL')
    text = replace_once(text, '#define GS_BOOTSTRAP_READONLY 1ULL', '#define GS_BOOTSTRAP_READONLY 0ULL')
    text = '// Compile-only expired candidate; review markers are not dispatch authorization.\n' + text
    text += '#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TA_ITEM_REVIEWED 1\n'
    text += '#define TA_ITEM_ANCHOR_RVAS ' + ','.join(hex(rva) for rva in FUNCTIONS) + '\n'
    text += '#define TA_ITEM_ANCHOR_BYTES ' + ','.join(
        '{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in runtime['functions']) + '\n'
    text += '#define TA_ITEM_HOTFIX_RVAS ' + ','.join(hex(rva) for rva in HOTFIX) + '\n'
    text += '#define TA_ITEM_NAME "' + ''.join('\\x%02x' % b for b in value['parameters']['name'].encode('utf-8')) + '"\n'
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
        ('template_calls', 'template_catalog_capture', 'item_calls', 'item_action', 'item_native_adapter')]
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
    manifest = {'schemaVersion': 1, 'kind': 'template-item-compile-candidate-v1',
        'compileOnly': True, 'launchable': False, 'allowWrites': False, 'reviewed': False,
        'nativeCalled': False, 'probeExecuted': False, 'action': 'create-item', 'actionCode': 6,
        'requestId': value['requestId'], 'requestLevelId': value['levelId'],
        'buildIdentity': {'pid': 1, 'tid': 1, 'deadline': 1}, 'receiptVersion': 10,
        'snapshotBytes': len(raw), 'snapshotVersion': abi.version_for_size(len(raw)),
        'largeScene': abi.large_scene_for_size(len(raw)),
        'inputs': inputs, 'originalSourceHashes': sources, 'disk': disk,
        'readonlyProfileSha256': profiles.PROFILE_SHA256,
        'readOnlyPreflight': False,
        'limits': 'Candidate compilation only. Metadata resolution, controller get-or-create, default/limit initialization, count list and name allocation may mutate runtime state. No execution occurred. Existing helper cannot dispatch this action.'}
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
    item = sub.add_parser('compile-check')
    item.add_argument('--request', required=True)
    item.add_argument('--baseline-run', required=True)
    item.add_argument('--runtime-profile', default=str(DEFAULT_RUNTIME_PROFILE))
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
