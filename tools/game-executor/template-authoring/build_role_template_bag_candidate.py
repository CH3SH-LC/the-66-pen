"""Compile-only binding action candidate; never launch, queue, or install it.

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
import snapshot_abi as abi

OUTPUT = ROOT / '.runtime/template-authoring/candidates'
DEFAULT_RUNTIME_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-role-template-bag/runtime-profile.json'
NATIVE_FILES = readonly.SOURCES
TEMPLATE_FILES = ('template_calls.h', 'template_catalog.h',
                  'template_catalog_capture.h', 'template_catalog_capture.cpp',
                  'component_attachment.h', 'component_attachment.cpp',
                  'component_binding_calls.h', 'component_binding_calls.cpp',
                  'binding_action.h',
                  'owner_notification_calls.h', 'owner_notification_calls.cpp',
                  'role_template_bag_action.h', 'role_template_bag_action.cpp',
                  'role_template_bag_edit.h', 'role_template_bag_edit.cpp',
                  'role_template_bag_native_adapter.h', 'role_template_bag_native_adapter.cpp')
FUNCTIONS = (0x524250, 0x13dddca0, 0x867c610, 0xea07cd0, 0x1013f680, 0x8250bf0, 0x8a3a760, 0x10ed3110, 0x82514f0, 0x10ed3250, 0xe827750, 0xc7bab90, 0x107abdf0, 0x9c26fa0, 0x9c257e0, 0x9c26c70, 0x9c270a0, 0x106ffc40, 0x106ff110, 0x106ff240, 0xb613ce0, 0x112386f0, 0x106dfc20, 0x1123a310, 0x11c15380)
HOTFIX = (0x570d048, 0x56e964f, 0x570a4d2, 0x56f5882, 0x576d72a, 0x5742f1e, 0x5772ab3, 0x578239f, 0x578238f, 0x56e9657, 0x5763722, 0x5772ab8, 0x571aaa3, 0x5763724, 0x5715609, 0x574c5db, 0x5715608, 0x5761932, 0x575936f, 0x574c5e5, 0x574c5d4, 0x574c5e3, 0x5759371, 0x574c5e6, 0x574c5e2, 0x574c5d6, 0x574c5d2, 0x5769638, 0x56f587b, 0x56f587d, 0x570a4d5, 0x56f586c, 0x571aa9b, 0x574b3f6, 0x574b3e3, 0x57372e7, 0x57358b8, 0x574b417, 0x5770222, 0x5770226, 0x570bee5)
USAGE_GROUPS = (0x2a925, 0x264b3, 0xd94d, 0x2bacb, 0x94ba, 0x1dc77, 0x19149, 0x1dcb2, 0x1dc53, 0x1dca5, 0x1dcbe, 0x16d33, 0x16d10, 0x16679, 0x264a7, 0x10643, 0x220a9)
TYPE_SLOTS = {0x57dda88:72833, 0x57b1060:80471, 0x57b0058:19879,
              0x57e9bd0:34146, 0x57e9bf0:71308, 0x57b3280:56469,
              0x5812cf8:68054, 0x57af188:60938}
# Keep the historical 25-anchor contract above unchanged for partial-transaction
# recovery. New ordinary binding requires this additional, separately pinned route.
REFERENCE_FUNCTIONS = (0x95f6410, 0x1013f9f0, 0x1013f8e0, 0x110e2f00)
REFERENCE_HOTFIX = (0x571ae71, 0x5742f25, 0x5742f23, 0x56e966e, 0x56e964f)
REFERENCE_USAGE_GROUPS = (0xd49f, 0x2bacd)
REFERENCE_CONTRACT = {
    'version': 1, 'factoryRva': '0x95f6410', 'factoryAbi': 'void* (void* managedTypeName)',
    'setIdRva': '0x1013f9f0', 'setIdAbi': 'void (void* reference, uint32 templateId)',
    'typeNameSlot': '0x5a016f8', 'typeName': 'ClientBeyondConfigReferenceEditData',
    'classSlot': '0x57b3280', 'classDefinition': 56469, 'poolGlobalOffset': '0x6d00',
    'usageGroups': [hex(g) for g in REFERENCE_USAGE_GROUPS],
}


def validate_reference_contract(runtime):
    reference = runtime.get('referenceFactory', {})
    profiles.require(all(reference.get(key) == expected for key, expected in REFERENCE_CONTRACT.items()),
                     'BINDING_TYPED_REFERENCE_CONTRACT')
    profiles.require(tuple(int(f['rva'], 16) for f in reference['functions']) == REFERENCE_FUNCTIONS,
                     'BINDING_REFERENCE_FUNCTION_SET')
    profiles.require(tuple(int(g['flagRva'], 16) for g in reference['hotfixGuards']) == REFERENCE_HOTFIX and
                     all(g['requiredRuntimeByte'] == 0 for g in reference['hotfixGuards']),
                     'BINDING_REFERENCE_HOTFIX_SET')
    profiles.require(all(len(bytes.fromhex(f['head32'])) == 32 for f in reference['functions']),
                     'BINDING_REFERENCE_ANCHOR_LENGTH')
    return reference


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
    new = '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 10 && defined(TA_ROLE_TEMPLATE_BAG_REVIEWED) && TA_ROLE_TEMPLATE_BAG_REVIEWED == 1))'
    file.write_text(replace_once(text, old, new), encoding='utf-8')

    file = native / 'hook_receipt_protocol.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#if HR_ACTION\n#include "game_scene_action.h"',
        '#if HR_ACTION == 10\n#include "../template-authoring/role_template_bag_native_adapter.h"\n'
        'static_assert(TA_ROLE_TEMPLATE_BAG_REVIEWED == 1 && HR_READ_CONTEXT == 1, "Binding contract required");\n'
        '#elif HR_ACTION\n#include "game_scene_action.h"')
    text = replace_once(text, '#if HR_ACTION\n    GameSceneActionResult action;',
        '#if HR_ACTION == 10\n    NativeRoleTemplateBagReceipt templateResult;\n#elif HR_ACTION\n    GameSceneActionResult action;')
    text = replace_once(text, 'constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS',
        'constexpr DWORD kReceiptVersion = HR_ACTION == 10 ? 14 : HR_READ_REOPEN_GUARDS')
    file.write_text(text, encoding='utf-8')

    file = native / 'hook_receipt.cpp'
    text = replace_once(file.read_text(encoding='utf-8'),
        '#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 10\n                    ExecuteNativeRoleTemplateBagAction(&receipt->context, &receipt->templateResult);\n'
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
        '#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 10 && defined(TA_ROLE_TEMPLATE_BAG_REVIEWED) && TA_ROLE_TEMPLATE_BAG_REVIEWED == 1))')
    text = replace_once(text, '#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"',
        '#error "Action requires supported contract; binding requires TA_ROLE_TEMPLATE_BAG_REVIEWED"')
    text = replace_once(text, '#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
        '#if HR_ACTION == 10\n                reportedOk = reportedOk && receipt->templateResult.sehCode == 0 &&\n'
        '                    receipt->templateResult.readbackSehCode == 0 && receipt->templateResult.code == NativeRoleTemplateBagCode::action_returned &&\n'
        '                    (receipt->templateResult.action.code == ge::templates::BindingActionCode::binding_verified ||\n'
        '                     receipt->templateResult.action.code == ge::templates::BindingActionCode::reused) &&\n'
        '                    receipt->templateResult.action.postBindingVerified && receipt->templateResult.afterSceneUnchanged == 1 &&\n'
        '                    receipt->templateResult.workspace.finalEditAfter.code == ge::component_edit::ReadCode::complete &&\n'
        '                    receipt->templateResult.workspace.finalEditAfter.count == 0 &&\n'
        '                    receipt->templateResult.workspace.finalEditAfter.depth == receipt->templateResult.workspace.finalEditAfter.baseDepth &&\n'
        '                    (receipt->templateResult.action.reused || (receipt->templateResult.action.edit.closeVerified &&\n'
        '                     receipt->templateResult.action.edit.notificationVerified && !receipt->templateResult.action.needsOwnerNotification));\n'
        '#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status')
    text = replace_once(text, 'HR_ACTION ? "FIXED_SCENE_ACTION"',
        'HR_ACTION == 10 ? "FIXED_ROLE_TEMPLATE_BAG_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"')
    text = replace_once(text, '#if HR_ACTION\n                std::printf(",\\"action\\":',
        BINDING_PROBE + '\n#elif HR_ACTION\n                std::printf(",\\"action\\":')
    file.write_text(text, encoding='utf-8')
    return originals


BINDING_PROBE = r'''#if HR_ACTION == 10
                const auto& binding = receipt->templateResult;
                const auto& outcome = binding.action;
                std::printf(",\"roleTemplateBagResult\":{\"size\":%u,\"version\":%u,\"sehCode\":%u,\"readbackSehCode\":%u,\"afterSceneUnchanged\":%u,\"nativeCode\":%u,\"code\":%u,\"stage\":%u,\"bindCode\":%u,\"bindStage\":%u,\"entityId\":%u,\"templateId\":%u,\"componentId\":%u,\"shopIndex\":%d,\"metadataCallsStarted\":%u,\"metadataCallsCompleted\":%u,\"metadataUsageInProgress\":%u,\"nativeCallAttempted\":%s,\"componentMutationCalled\":%s,\"runtimeStateMayHaveChanged\":%s,\"attachCalled\":%s,\"referenceFactoryCalled\":%s,\"addCalled\":%s,\"setterCalled\":%s,\"dependencyRefreshCalled\":%s,\"reused\":%s,\"postBindingVerified\":%s,\"catalogsUnchanged\":%s,\"needsOwnerNotification\":%s,\"outcomeUncertain\":%s}",
                    binding.size, binding.version, binding.sehCode, binding.readbackSehCode, binding.afterSceneUnchanged,
                    static_cast<unsigned int>(binding.code), static_cast<unsigned int>(outcome.code), static_cast<unsigned int>(outcome.stage),
                    static_cast<unsigned int>(outcome.binding.code), static_cast<unsigned int>(outcome.binding.exceptionStage),
                    outcome.entityId, outcome.templateId, outcome.componentId, outcome.shopIndex,
                    binding.metadataCallsStarted, binding.metadataCallsCompleted, binding.metadataUsageInProgress,
                    binding.nativeCallAttempted ? "true" : "false", binding.componentMutationCalled ? "true" : "false",
                    binding.runtimeStateMayHaveChanged ? "true" : "false", outcome.attachment.attach_called ? "true" : "false",
                    outcome.binding.referenceFactoryCalled ? "true" : "false", outcome.binding.addCalled ? "true" : "false",
                    outcome.binding.setterCalled ? "true" : "false", outcome.binding.dependencyRefreshCalled ? "true" : "false",
                    outcome.reused ? "true" : "false", outcome.postBindingVerified ? "true" : "false",
                    outcome.catalogsUnchanged ? "true" : "false", outcome.needsOwnerNotification ? "true" : "false",
                    outcome.outcomeUncertain ? "true" : "false");
                const auto printRaw = [](const char* name, const void* data, std::size_t length) {
                    std::printf(",\"%sBytes\":%zu,\"%sHex\":\"", name, length, name);
                    const auto bytes = static_cast<const unsigned char*>(data);
                    for (std::size_t i = 0; i < length; ++i) std::printf("%02x", static_cast<unsigned int>(bytes[i]));
                    std::printf("\"");
                };
                printRaw("roleTemplateBagResult", &binding, sizeof(binding));
                printRaw("beforeCatalog", &binding.workspace.binding.beforeCatalog, sizeof(binding.workspace.binding.beforeCatalog));
                printRaw("afterCatalog", &binding.workspace.binding.afterCatalog, sizeof(binding.workspace.binding.afterCatalog));
                printRaw("beforeComponents", &binding.workspace.binding.attachment.before, sizeof(binding.workspace.binding.attachment.before));
                printRaw("afterAttachmentComponents", &binding.workspace.binding.attachment.after, sizeof(binding.workspace.binding.attachment.after));
                printRaw("afterComponents", &binding.workspace.binding.postComponents, sizeof(binding.workspace.binding.postComponents));
                printRaw("editResult", &outcome.edit, sizeof(outcome.edit));
                printRaw("editBefore", &outcome.edit.before, sizeof(outcome.edit.before));
                printRaw("editAfterSnapshot", &outcome.edit.afterSnapshot, sizeof(outcome.edit.afterSnapshot));
                printRaw("editAfterNotify", &outcome.edit.afterNotify, sizeof(outcome.edit.afterNotify));
                printRaw("editAfterClose", &outcome.edit.afterClose, sizeof(outcome.edit.afterClose));
                std::printf(",\"editResult\":{\"code\":%u,\"stage\":%u,\"openCalled\":%s,\"snapshotCalled\":%s,\"notifyCalled\":%s,\"closeCalled\":%s,\"notificationVerified\":%s,\"closeVerified\":%s,\"transactionMayBeOpen\":%s,\"needsPersistenceAcceptance\":%s}",
                    static_cast<unsigned>(outcome.edit.code), static_cast<unsigned>(outcome.edit.stage),
                    outcome.edit.openCalled ? "true" : "false", outcome.edit.snapshotCalled ? "true" : "false",
                    outcome.edit.notifyCalled ? "true" : "false", outcome.edit.closeCalled ? "true" : "false",
                    outcome.edit.notificationVerified ? "true" : "false", outcome.edit.closeVerified ? "true" : "false",
                    outcome.edit.transactionMayBeOpen ? "true" : "false", outcome.edit.needsPersistenceAcceptance ? "true" : "false");
                printRaw("beforeOwner", &binding.workspace.beforeOwner, sizeof(binding.workspace.beforeOwner));
                printRaw("afterOwner", &binding.workspace.afterOwner, sizeof(binding.workspace.afterOwner));
                printRaw("finalEditAfter", &binding.workspace.finalEditAfter, sizeof(binding.workspace.finalEditAfter));
                printRaw("afterSnapshot", &binding.after, sizeof(binding.after));''' 


BASE_RUNTIME_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-ref-factory/binding-reference-runtime-profile.json'
ROLE_PROFILE_SHA256 = '032ac4f24cfa1f14e9f5e6a9bfef8b82b6f0e9ff620816dfc9f118b93db7b2e7'
BASE_PROFILE_SHA256 = '4d29aa69b76266fa17661b15c2fc43421de74e40db86a0c280fa4f0051b04a15'


def read_runtime(runtime_profile=DEFAULT_RUNTIME_PROFILE):
    path = requests.runtime_path(runtime_profile)
    profiles.require(path == DEFAULT_RUNTIME_PROFILE.resolve() and profiles.sha256(path) == ROLE_PROFILE_SHA256,
                     'ROLE_PROFILE_FIXED_HASH')
    role = requests.read_json(path)
    binding = role['baseBindingProfile']
    profiles.require(requests.runtime_path(binding['path']) == BASE_RUNTIME_PROFILE.resolve() and
                     binding['sha256'] == BASE_PROFILE_SHA256 == profiles.sha256(BASE_RUNTIME_PROFILE),
                     'ROLE_BASE_PROFILE_FIXED_HASH')
    base = requests.read_json(BASE_RUNTIME_PROFILE)
    validate_reference_contract(base)
    profiles.require(role['imageSha256'] == base['imageSha256'], 'ROLE_PROFILE_IMAGE')
    profiles.require(len(role['functions']) == 14 and len(role['hotfixGuards']) == 31 and
                     role['usageGroups'] == ['0x1c2a3'], 'ROLE_PROFILE_CONTRACT')
    return dict(base, roleProfile=role)


def load_inputs(request_path, baseline_run, runtime_profile=DEFAULT_RUNTIME_PROFILE):
    import role_template_bag_review as reviews
    path = requests.runtime_path(request_path)
    value = reviews.validate_request(requests.read_json(path))
    profiles.require(path.read_bytes() == requests.canonical_bytes(value), 'CANONICAL_REQUEST_REQUIRED')
    digest = profiles.sha256(path)
    run = requests.runtime_path(baseline_run)
    profiles.require(run.name == value['runId'], 'REQUEST_BASELINE_BINDING')
    hashes = requests._baseline_hashes(run, 'readonly')
    snapshot, baseline = requests.review_api.load_baseline(run, 'readonly', value['levelId'])
    for key in requests.SESSION_FIELDS:
        profiles.require(value['session'][key] == baseline['session'][key], 'BASELINE_SESSION:' + key)
    profiles.require(any(e['id'] == value['parameters']['sceneEntityId'] for e in snapshot['entities']),
                     'ROLE_SCENE_TARGET_NOT_IN_BASELINE')
    record, _ = readonly.load_decoder().read_probe(run / 'stdout.jsonl')
    raw = bytes.fromhex(record['snapshotHex'])
    abi.validate_snapshot_payload(raw, 'BASELINE_RAW_ABI')
    profiles.require(len(raw) == snapshot['structureSize'], 'BASELINE_RAW_ABI')
    runtime_path = requests.runtime_path(runtime_profile)
    runtime = read_runtime(runtime_path)
    profile = profiles.load_profile()
    profiles.require(runtime['imageSha256'] == profile['image']['sha256'], 'ROLE_PROFILE_IMAGE')
    disk = profiles.verify_disk(profile)
    functions = runtime['functions'] + runtime['referenceFactory']['functions'] + runtime['roleProfile']['functions']
    with profiles.TARGET_IMAGE.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
        pe = profiles.inspect_pe(image)
        for function in functions:
            head = bytes.fromhex(function['head32'])
            profiles.require(len(head) == 32, 'ROLE_ANCHOR_LENGTH')
            offset = profiles.rva_offset(pe['sections'], int(function['rva'], 16), 32, len(image))
            profiles.require(image[offset:offset + 32] == head, 'ROLE_DISK_ANCHOR_MISMATCH')
    profiles.require(hashes == requests._baseline_hashes(run, 'readonly'), 'BASELINE_CHANGED')
    return value, raw, runtime, profile, disk, {
        'requestPath': str(path), 'requestSha256': digest, 'baselineRun': str(run),
        'baselineEvidenceHashes': hashes, 'runtimeProfilePath': str(runtime_path),
        'runtimeProfileSha256': profiles.sha256(runtime_path),
        'baseRuntimeProfilePath': str(BASE_RUNTIME_PROFILE), 'baseRuntimeProfileSha256': BASE_PROFILE_SHA256,
        'reviewed': False, 'liveSessionRevalidated': False,
    }


def emit_header(run, value, raw, runtime, profile):
    reference = validate_reference_contract(runtime)
    fixture = {'pid': 1, 'tid': 1, 'processCreation': 1, 'threadCreation': 1,
               'image': str(run / 'compile-only-target.invalid')}
    readonly.emit_header(profile, fixture, run, deadline=1, message_id=0xc001, nonce=1,
                         large_scene=bool(abi.validate_snapshot_payload(raw)['largeScene']))
    file = run / 'target_config.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#define HR_ACTION 0ULL', '#define HR_ACTION 10ULL')
    text = replace_once(text, '#define GS_BOOTSTRAP_READONLY 1ULL', '#define GS_BOOTSTRAP_READONLY 0ULL')
    text = '// Compile-only expired candidate; review markers are not dispatch authorization.\n' + text
    text += '#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TA_ROLE_TEMPLATE_BAG_REVIEWED 1\n'
    text += '#define TA_ROLE_TEMPLATE_BAG_LEVEL ' + str(value['levelId']) + 'U\n'
    text += '#define TA_BINDING_ANCHOR_RVAS ' + ','.join(hex(rva) for rva in FUNCTIONS) + '\n'
    text += '#define TA_BINDING_ANCHOR_BYTES ' + ','.join(
        '{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in runtime['functions']) + '\n'
    text += '#define TA_BINDING_USAGE_GROUPS ' + ','.join(hex(g) for g in USAGE_GROUPS) + '\n'
    text += '#define TA_BINDING_HOTFIX_RVAS ' + ','.join(hex(rva) for rva in HOTFIX) + '\n'
    text += '#define TA_REFERENCE_ANCHOR_RVAS ' + ','.join(hex(rva) for rva in REFERENCE_FUNCTIONS) + '\n'
    text += '#define TA_REFERENCE_ANCHOR_BYTES ' + ','.join(
        '{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in reference['functions']) + '\n'
    text += '#define TA_REFERENCE_USAGE_GROUPS ' + ','.join(hex(g) for g in REFERENCE_USAGE_GROUPS) + '\n'
    text += '#define TA_REFERENCE_HOTFIX_RVAS ' + ','.join(hex(rva) for rva in REFERENCE_HOTFIX) + '\n'
    role = runtime['roleProfile']
    text += '#define TA_ROLE_ANCHOR_RVAS ' + ','.join(f['rva'] for f in role['functions']) + '\n'
    text += '#define TA_ROLE_ANCHOR_BYTES ' + ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in role['functions']) + '\n'
    text += '#define TA_ROLE_HOTFIX_RVAS ' + ','.join(g['flagRva'] for g in role['hotfixGuards']) + '\n'
    text += '#define TA_ROLE_USAGE_GROUPS ' + ','.join(role['usageGroups']) + '\n'
    for macro, key in (('SCENE_ID', 'sceneEntityId'), ('PREFAB_ID', 'rolePrefabId'), ('BAG_ID', 'bagId')):
        text += '#define TA_ROLE_TEMPLATE_BAG_' + macro + ' ' + str(value['parameters'][key]) + 'U\n'
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
    source = Path('candidate-source')
    objects = []
    lines = ['@echo off', f'call "{vcvars}" >nul', 'if errorlevel 1 exit /b 1']
    units = [('native', 'game_context_snapshot')] + [('template-authoring', stem) for stem in
        ('template_catalog_capture', 'component_attachment', 'component_binding_calls', 'owner_notification_calls', 'role_template_bag_action', 'role_template_bag_edit', 'role_template_bag_native_adapter')]
    for directory, stem in units:
        obj = Path(stem + '.obj'); objects.append(obj)
        lines.extend([common + f'/c "{source / directory / (stem + ".cpp")}" /Fo:"{obj}"',
                      'if errorlevel 1 exit /b 1'])
    lines.extend([common + f'/LD "{source / "native/hook_receipt.cpp"}" /Fo:"{"hook_receipt.obj"}" '
        f'/Fe:"{"hook_receipt.dll"}" /link User32.lib ' + ' '.join('"' + str(obj) + '"' for obj in objects),
        'if errorlevel 1 exit /b 1',
        common + f'"{source / "native/hook_receipt_probe.cpp"}" /Fo:"{"hook_receipt_probe.obj"}" '
        f'/Fe:"{"hook_receipt_probe.exe"}" /link User32.lib Advapi32.lib', 'exit /b %ERRORLEVEL%'])
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
    manifest = {'schemaVersion': 1, 'kind': 'role-template-bag-compile-candidate-v1',
        'compileOnly': True, 'launchable': False, 'allowWrites': False, 'reviewed': False,
        'nativeCalled': False, 'probeExecuted': False, 'action': value['action'], 'actionCode': 10,
        'requestId': value['requestId'], 'requestLevelId': value['levelId'],
        'buildIdentity': {'pid': 1, 'tid': 1, 'deadline': 1}, 'receiptVersion': 14,
        'inputs': inputs, 'originalSourceHashes': sources, 'disk': disk,
        'readonlyProfileSha256': profiles.PROFILE_SHA256,
        'readOnlyPreflight': False,
        'limits': 'Candidate compilation only. Metadata initialization and reference allocation may mutate runtime state. Attach/add/set and formal snapshot/notify/close use caller-owned progress. Native notification includes dependency refresh once; transaction readback still does not prove export, save or gameplay. No execution occurred. Existing helper cannot dispatch this action.'}
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
    binding = sub.add_parser('compile-check')
    binding.add_argument('--request', required=True)
    binding.add_argument('--baseline-run', required=True)
    binding.add_argument('--runtime-profile', default=str(DEFAULT_RUNTIME_PROFILE))
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
