"""Compile-only exact partial-bag recovery candidate; never launch, queue, or install it.

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
import struct
import sys

HERE = Path(__file__).resolve().parent
EXECUTOR = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EXECUTOR))
import request as requests
import build_readonly_profile as readonly
import native_profiles as profiles
import binding_receipt as prior_decoder

OUTPUT = ROOT / '.runtime/scratch/overnight-features-20261013/task-binding-recovery-build'
DEFAULT_RUNTIME_PROFILE = ROOT / '.runtime/scratch/overnight-features-20261013/task-ba/binding-edit-runtime-profile.json'
NATIVE_FILES = readonly.SOURCES
TEMPLATE_FILES = ('template_calls.h', 'template_catalog.h',
    'template_catalog_capture.h', 'template_catalog_capture.cpp',
    'component_attachment.h', 'component_attachment.cpp', 'component_binding_calls.h',
    'binding_action.h', 'owner_notification_calls.h', 'owner_notification_calls.cpp',
    'binding_native_adapter.h', 'binding_recovery.h', 'binding_recovery.cpp',
    'binding_recovery_native_adapter.h', 'binding_recovery_native_adapter.cpp')
FUNCTIONS = (0x524250, 0x13dddca0, 0x867c610, 0xea07cd0, 0x1013f680, 0x8250bf0, 0x8a3a760, 0x10ed3110, 0x82514f0, 0x10ed3250, 0xe827750, 0xc7bab90, 0x107abdf0, 0x9c26fa0, 0x9c257e0, 0x9c26c70, 0x9c270a0, 0x106ffc40, 0x106ff110, 0x106ff240, 0xb613ce0, 0x112386f0, 0x106dfc20, 0x1123a310, 0x11c15380)
HOTFIX = (0x570d048, 0x56e964f, 0x570a4d2, 0x56f5882, 0x576d72a, 0x5742f1e, 0x5772ab3, 0x578239f, 0x578238f, 0x56e9657, 0x5763722, 0x5772ab8, 0x571aaa3, 0x5763724, 0x5715609, 0x574c5db, 0x5715608, 0x5761932, 0x575936f, 0x574c5e5, 0x574c5d4, 0x574c5e3, 0x5759371, 0x574c5e6, 0x574c5e2, 0x574c5d6, 0x574c5d2, 0x5769638, 0x56f587b, 0x56f587d, 0x570a4d5, 0x56f586c, 0x571aa9b, 0x574b3f6, 0x574b3e3, 0x57372e7, 0x57358b8, 0x574b417, 0x5770222, 0x5770226, 0x570bee5)
USAGE_GROUPS = (0x2a925, 0x264b3, 0xd94d, 0x2bacb, 0x94ba, 0x1dc77, 0x19149, 0x1dcb2, 0x1dc53, 0x1dca5, 0x1dcbe, 0x16d33, 0x16d10, 0x16679, 0x264a7, 0x10643, 0x220a9)
TYPE_SLOTS = {0x57dda88:72833, 0x57b1060:80471, 0x57b0058:19879,
              0x57e9bd0:34146, 0x57e9bf0:71308, 0x57b3280:56469,
              0x5812cf8:68054, 0x57af188:60938}

ACTION = 'close-partial-bag-edit'
PRIOR_STDOUT_SHA256 = 'cecf2c5eb16576629663e25f0dd6d51fd347d2b5d41b310b7696b6d666eea191'
PRIOR_RAW_SHA256 = '44d4e7fe4a52ad1a78d607f69b3f4b051e77034e393bdcecea1cca2dbdb91bf4'
RUNTIME_PROFILE_SHA256 = '483b0b4fc7ff914623256252dfb98c589ffbda3c18550eb6a019ff1e7fca1b8c'
TOKEN_REFUSAL_RUN = ROOT / '.runtime/template-authoring/prepared-binding-recovery/20261013-105434-4d3d0bf1f2'
TOKEN_REFUSAL_STDOUT_SHA256 = '28a5a731a8c666f082619831b73bbf1afa95323a34971c3dfb2e95c21f786e4e'
TOKEN_REFUSAL_RAW_SHA256 = '483003dbba78bc833a898c085bca9eb086a068d3901693154c7926f91042e6b8'
PENDING_DIAGNOSTIC_RUN = ROOT / '.runtime/template-authoring/prepared-binding-recovery/20261013-112823-0e567dc96a'
PENDING_DIAGNOSTIC_BUILD_SHA256 = '60a75b8db645c6d8634e6e3a7177c0189770e0b467bd95dad475a9774f43206a'
PENDING_DIAGNOSTIC_STDOUT_SHA256 = 'bc2a3297fe39378d8f76b75dc28862d3a8b5a3c8a35b19cefd50b22b54f3d276'
PENDING_DIAGNOSTIC_RAW_SHA256 = 'f631cc7d7272f62209b3f166109f412f90dda4181a4956ca34c82d23cbf307f3'
PENDING_DIAGNOSTIC_STATE_AT = 123720  # Native result 98752 + edit 56 + afterNotify 24912.


def source_paths():
    paths = [EXECUTOR / 'native' / name for name in NATIVE_FILES]
    paths += [HERE / name for name in TEMPLATE_FILES]
    paths += [HERE / name for name in ('request.py', 'receipt.py', 'component_receipt.py',
        'binding_receipt.py', 'build_binding_recovery_candidate.py', 'prepare_binding_recovery.py')]
    paths += [EXECUTOR / name for name in ('native_write_review.py', 'native_profiles.py',
        'build_readonly_profile.py', 'decode_context_snapshot.py', 'native_level_observation.py')]
    paths += [profiles.DEFAULT_PROFILE, requests.review_api.level_api.LEVEL_PROFILE]
    return {str(path.relative_to(ROOT)).replace('\\', '/'): path for path in paths}


def source_hashes():
    return {name: profiles.sha256(path) for name, path in source_paths().items()}


def prior_evidence_hashes(prior_run):
    """Validate the historical package against its own manifest, never current binding sources."""
    run = requests.runtime_path(prior_run)
    build = requests.read_json(run / 'build-result.json')
    profiles.require(build.get('kind') == 'template-binding-build-v1' and
        build.get('action') == 'bind-bag' and build.get('actionCode') == 7 and
        build.get('compiled') is True and build.get('launchable') is True and
        build.get('compileOnly') is False, 'RECOVERY_PRIOR_BUILD_REQUIRED')
    hashes = build.get('hashes')
    profiles.require(type(hashes) is dict and bool(hashes), 'RECOVERY_PRIOR_MANIFEST')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        profiles.require(path.is_relative_to(run) and path != run and
            profiles.sha256(path) == digest, 'RECOVERY_PRIOR_ARTIFACT_CHANGED:' + name)
    required = {'prepared.json', 'review.json', 'request.json', 'target_config.h',
        'build-contract.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-binding-probe.ps1'}
    profiles.require(required <= set(hashes), 'RECOVERY_PRIOR_MANIFEST_INCOMPLETE')
    return dict(hashes, **{name: profiles.sha256(run / name)
        for name in ('stdout.jsonl', 'stderr.txt', 'exit.json', 'build-result.json', 'launch.claim', 'attempt.used')})


def read_prior(prior_run):
    run = requests.runtime_path(prior_run)
    hashes = prior_evidence_hashes(run)
    profiles.require(hashes['stdout.jsonl'] == PRIOR_STDOUT_SHA256, 'RECOVERY_EXACT_PRIOR_STDOUT_REQUIRED')
    encoded = (run / 'stdout.jsonl').read_bytes()
    profiles.require(len(encoded) <= 8 * 1024 * 1024, 'RECOVERY_PRIOR_STDOUT_LIMIT')
    rows = [json.loads(line, object_pairs_hook=requests._unique_object)
        for line in encoded.decode('utf-8-sig').splitlines() if line.strip()]
    profiles.require(len(rows) == 1 and type(rows[0]) is dict, 'RECOVERY_PRIOR_SINGLE_RECEIPT')
    record = rows[0]
    raw = bytes.fromhex(record['bindingResultHex'])
    profiles.require(len(raw) == record['bindingResultBytes'] == 988064 and
        hashlib.sha256(raw).hexdigest() == PRIOR_RAW_SHA256, 'RECOVERY_EXACT_PRIOR_RAW_REQUIRED')
    prepared = requests.read_json(run / 'prepared.json')
    exit_record = requests.read_json(run / 'exit.json')
    profiles.require(exit_record['executed'] is True and exit_record['exitCode'] == 1 and
        exit_record['error'] is None and exit_record['scope'] == 'FIXED_TEMPLATE_BINDING_ACTION' and
        record['transportOk'] is True and record['callbackCount'] == 1 and record['activeCallbacks'] == 0 and
        record['unhooked'] is True and record['snapshotStatus'] == 0 and
        record['scope'] == 'FIXED_TEMPLATE_BINDING_ACTION' and
        record['pid'] == prepared['session']['pid'] and record['tid'] == prepared['session']['tid'],
        'RECOVERY_PRIOR_TRANSPORT')
    decoded = prior_decoder.decode_native(raw)
    action, edit, binding = (decoded[key] for key in ('action', 'edit', 'binding'))
    profiles.require(action['code'] == 19 and action['stage'] == 4 and binding['code'] == 3 and
        binding['stage'] == 0 and binding['referenceFactoryCalled'] and binding['reference'] == 0 and
        not any(binding[k] for k in ('setterCalled', 'addCalled', 'mutationCalled')) and
        edit['code'] == 8 and edit['openCalled'] and edit['snapshotCalled'] and
        edit['transactionMayBeOpen'] and not edit['notifyCalled'] and not edit['closeCalled'],
        'RECOVERY_PRIOR_NOT_EXACT_EMPTY_BAG_FAILURE')
    identity = {key: action[key] for key in ('entityId', 'templateId', 'componentId', 'owner', 'wrapper', 'config')}
    identity['transaction'] = edit['transaction']
    profiles.require(prepared['levelId'] == 1073741842 and
        tuple(identity[k] for k in ('entityId', 'templateId', 'componentId')) ==
        (1090519041, 1119879169, 1073741825), 'RECOVERY_FIXED_PRIOR_IDENTITY')
    return raw, identity, prepared, hashes


def token_refusal_evidence_hashes(token_refusal_run):
    """Keep the complete v1 rejection package immutable when constructing v2."""
    run = requests.runtime_path(token_refusal_run)
    profiles.require(run == TOKEN_REFUSAL_RUN.resolve(), 'RECOVERY_EXACT_TOKEN_REFUSAL_RUN')
    build = requests.read_json(run / 'build-result.json')
    profiles.require(build.get('kind') == 'template-binding-recovery-build-v1' and
        build.get('action') == ACTION and build.get('actionCode') == 8 and build.get('receiptVersion') == 12 and
        build.get('compiled') is True and build.get('launchable') is True and
        build.get('compileOnly') is False, 'RECOVERY_V1_REFUSAL_BUILD_REQUIRED')
    hashes = build.get('hashes')
    profiles.require(type(hashes) is dict and {'prepared.json', 'review.json', 'build-contract.json',
        'target_config.h', 'prior-receipt.bin', 'baseline-snapshot.bin', 'hook_receipt.dll',
        'hook_receipt_probe.exe', 'invoke-binding-recovery-probe.ps1'} <= set(hashes), 'RECOVERY_V1_REFUSAL_MANIFEST')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        profiles.require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
            'RECOVERY_V1_REFUSAL_ARTIFACT_CHANGED:' + name)
    return dict(hashes, **{name: profiles.sha256(run / name) for name in
        ('stdout.jsonl', 'stderr.txt', 'exit.json', 'build-result.json', 'launch.claim', 'attempt.used')})


def read_token_refusal(token_refusal_run, prior_raw, identity, prior_prepared):
    run = requests.runtime_path(token_refusal_run)
    hashes = token_refusal_evidence_hashes(run)
    profiles.require(hashes['stdout.jsonl'] == TOKEN_REFUSAL_STDOUT_SHA256, 'RECOVERY_EXACT_TOKEN_REFUSAL_STDOUT')
    record = requests.read_json(run / 'stdout.jsonl')
    raw = bytes.fromhex(record['bindingRecoveryResultHex'])
    profiles.require(len(raw) == record['bindingRecoveryResultBytes'] == 148552 and
        hashlib.sha256(raw).hexdigest() == TOKEN_REFUSAL_RAW_SHA256, 'RECOVERY_EXACT_TOKEN_REFUSAL_RAW')
    profiles.require(struct.unpack_from('<6I', raw) == (148552, 1, 0, 1, 1, 0) and
        struct.unpack_from('<I6B', raw, 98752) == (5, 1, 1, 0, 0, 1, 1), 'RECOVERY_V1_NOT_TOKEN_REFUSED')
    # The entire original edit is untouched: same token/pending record, no notify or close.
    profiles.require(raw[98808:148552] == prior_raw[prior_decoder.EDIT_AT:prior_decoder.EDIT_AT + 49744],
        'RECOVERY_V1_EDIT_CHANGED')
    prepared = requests.read_json(run / 'prepared.json')
    finished = requests.read_json(run / 'exit.json')
    profiles.require(prepared['identity'] == identity and prepared['levelId'] == prior_prepared['levelId'] and
        all(prepared['session'][key] == prior_prepared['session'][key] for key in requests.SESSION_FIELDS),
        'RECOVERY_V1_PRIOR_IDENTITY_CHANGED')
    profiles.require(finished['executed'] is True and finished['exitCode'] == 1 and finished['error'] is None and
        finished['scope'] == 'FIXED_BINDING_RECOVERY_ACTION' and record['transportOk'] is True and
        record['callbackCount'] == 1 and record['activeCallbacks'] == 0 and record['unhooked'] is True and
        record['snapshotStatus'] == 0 and record['scope'] == 'FIXED_BINDING_RECOVERY_ACTION' and
        record['pid'] == prepared['session']['pid'] and record['tid'] == prepared['session']['tid'],
        'RECOVERY_V1_REFUSAL_TRANSPORT')
    return raw, hashes


def pending_diagnostic_evidence_hashes(pending_diagnostic_run):
    """Verify the fixed read-only package using its own reviewed source copies."""
    run = requests.runtime_path(pending_diagnostic_run)
    profiles.require(run == PENDING_DIAGNOSTIC_RUN.resolve(), 'RECOVERY_EXACT_PENDING_DIAGNOSTIC_RUN')
    profiles.require(profiles.sha256(run / 'build-result.json') == PENDING_DIAGNOSTIC_BUILD_SHA256,
        'RECOVERY_PENDING_DIAGNOSTIC_MANIFEST_CHANGED')
    build = requests.read_json(run / 'build-result.json')
    profiles.require(build.get('kind') == 'template-binding-recovery-build-v2' and
        build.get('action') == ACTION and build.get('actionCode') == 8 and build.get('receiptVersion') == 12 and
        build.get('compiled') is True and build.get('launchable') is True and
        build.get('compileOnly') is False and build.get('diagnosticOnly') is True and
        build.get('allowWrites') is False, 'RECOVERY_PENDING_DIAGNOSTIC_BUILD_REQUIRED')
    hashes = build.get('hashes')
    required = {'prepared.json', 'review.json', 'build-contract.json', 'target_config.h',
        'prior-receipt.bin', 'token-refusal-receipt.bin', 'baseline-snapshot.bin',
        'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-binding-recovery-probe.ps1'}
    profiles.require(type(hashes) is dict and required <= set(hashes), 'RECOVERY_PENDING_DIAGNOSTIC_MANIFEST')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        profiles.require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
            'RECOVERY_PENDING_DIAGNOSTIC_ARTIFACT_CHANGED:' + name)
    prepared, review, contract = [requests.read_json(run / name) for name in
        ('prepared.json', 'review.json', 'build-contract.json')]
    profiles.require(prepared['sourceHashes'] == review['sourceHashes'] == contract['sourceHashes'] and
        prepared['reviewSha256'] == contract['reviewSha256'] == profiles.sha256(run / 'review.json') and
        prepared['diagnosticOnly'] is True and review['diagnosticOnly'] is True and
        contract['diagnosticOnly'] is True and prepared['allowWrites'] is False and
        contract['allowWrites'] is False, 'RECOVERY_PENDING_DIAGNOSTIC_REVIEW')
    for name, digest in prepared['originalNativeSourceHashes'].items():
        profiles.require(review['sourceHashes']['tools/game-executor/' + name] == digest,
            'RECOVERY_PENDING_DIAGNOSTIC_SOURCE_REVIEW:' + name)
        if name.startswith('template-authoring/'):
            profiles.require(hashes['candidate-source/' + name] == digest,
                'RECOVERY_PENDING_DIAGNOSTIC_SOURCE_COPY:' + name)
    return dict(hashes, **{name: profiles.sha256(run / name) for name in
        ('stdout.jsonl', 'stderr.txt', 'exit.json', 'build-result.json', 'launch.claim', 'attempt.used')})


def read_pending_diagnostic(pending_diagnostic_run, prior_raw, identity, prior_prepared):
    run = requests.runtime_path(pending_diagnostic_run)
    hashes = pending_diagnostic_evidence_hashes(run)
    profiles.require(hashes['stdout.jsonl'] == PENDING_DIAGNOSTIC_STDOUT_SHA256,
        'RECOVERY_EXACT_PENDING_DIAGNOSTIC_STDOUT')
    record = requests.read_json(run / 'stdout.jsonl')
    raw = bytes.fromhex(record['bindingRecoveryResultHex'])
    profiles.require(len(raw) == record['bindingRecoveryResultBytes'] == 148560 and
        hashlib.sha256(raw).hexdigest() == PENDING_DIAGNOSTIC_RAW_SHA256,
        'RECOVERY_EXACT_PENDING_DIAGNOSTIC_RAW')
    # Read the historical v2 ABI directly; a future decoder must not reinterpret it.
    profiles.require(struct.unpack_from('<6I', raw) == (148560, 2, 0, 1, 1, 1) and
        struct.unpack_from('<I6B', raw, 98752) == (10, 1, 1, 0, 0, 1, 1) and
        struct.unpack_from('<I4B', raw, 148552) == (2, 0, 0, 0, 1),
        'RECOVERY_PENDING_DIAGNOSTIC_NOT_READ_ONLY')
    edit_at = 98808
    profiles.require(struct.unpack_from('<I', raw, edit_at)[0] == 3 and
        raw[edit_at + 18:edit_at + 20] == b'\0\0' and
        raw[edit_at + 8:edit_at + 16] == prior_raw[prior_decoder.EDIT_AT + 8:prior_decoder.EDIT_AT + 16] and
        raw[edit_at + 32:edit_at + 80] == prior_raw[prior_decoder.EDIT_AT + 32:prior_decoder.EDIT_AT + 80],
        'RECOVERY_PENDING_DIAGNOSTIC_EDIT_IDENTITY')
    for offset in (80, 12496):
        profiles.require(raw[edit_at + offset:edit_at + offset + prior_decoder.STATE_BYTES] ==
            prior_raw[prior_decoder.EDIT_AT + offset:prior_decoder.EDIT_AT + offset + prior_decoder.STATE_BYTES],
            'RECOVERY_PENDING_DIAGNOSTIC_ORIGINAL_STATE_CHANGED')
    original = prior_decoder.decode_state(prior_raw[prior_decoder.EDIT_AT + 12496:
        prior_decoder.EDIT_AT + 12496 + prior_decoder.STATE_BYTES], identity['wrapper'])
    current = prior_decoder.decode_state(raw[PENDING_DIAGNOSTIC_STATE_AT:
        PENDING_DIAGNOSTIC_STATE_AT + prior_decoder.STATE_BYTES], identity['wrapper'])
    profiles.require(all(current[key] == original[key] for key in
        ('manager', 'list', 'items', 'recordClass', 'literal', 'capacity', 'baseDepth', 'depth', 'flags', 'targetCount', 'target')) and
        (current['baseDepth'], current['depth'], current['count'], current['version']) == (20, 21, 2, 6) and
        current['records'][:-1] == original['records'] and
        current['records'][-1] == (7697520584640, 5497694404248, 0, 0, 0, 0),
        'RECOVERY_PENDING_DIAGNOSTIC_REVIEWED_RECORDS')
    prepared, finished = [requests.read_json(run / name) for name in ('prepared.json', 'exit.json')]
    profiles.require(prepared['identity'] == identity and prepared['levelId'] == prior_prepared['levelId'] and
        all(prepared['session'][key] == prior_prepared['session'][key] for key in requests.SESSION_FIELDS) and
        (run / 'prior-receipt.bin').read_bytes() == prior_raw and
        profiles.sha256(run / 'token-refusal-receipt.bin') == TOKEN_REFUSAL_RAW_SHA256,
        'RECOVERY_PENDING_DIAGNOSTIC_PRIOR_CHANGED')
    profiles.require(finished['executed'] is True and finished['exitCode'] == 0 and finished['error'] is None and
        finished['scope'] == record['scope'] == 'FIXED_BINDING_RECOVERY_DIAGNOSTIC' and
        finished['diagnosticOnly'] is True and finished['allowWrites'] is False and record['diagnosticOnly'] is True and
        record['ok'] is True and record['transportOk'] is True and record['callbackCount'] == 1 and
        record['activeCallbacks'] == 0 and record['unhooked'] is True and record['snapshotStatus'] == 0 and
        record['pid'] == prepared['session']['pid'] and record['tid'] == prepared['session']['tid'],
        'RECOVERY_PENDING_DIAGNOSTIC_TRANSPORT')
    return raw, hashes


def load_inputs(prior_run, baseline_run, runtime_profile=DEFAULT_RUNTIME_PROFILE,
                token_refusal_run=TOKEN_REFUSAL_RUN, pending_diagnostic_run=PENDING_DIAGNOSTIC_RUN):
    prior, identity, prepared, prior_hashes = read_prior(prior_run)
    refusal, refusal_hashes = read_token_refusal(token_refusal_run, prior, identity, prepared)
    pending, pending_hashes = read_pending_diagnostic(pending_diagnostic_run, prior, identity, prepared)
    run = requests.runtime_path(baseline_run)
    level = prepared['levelId']
    snapshot, baseline = requests.review_api.load_baseline(run, 'readonly', level)
    for key in requests.SESSION_FIELDS:
        profiles.require(baseline['session'][key] == prepared['session'][key], 'RECOVERY_SESSION_CHANGED:' + key)
    record, _ = readonly.load_decoder().read_probe(run / 'stdout.jsonl')
    raw = bytes.fromhex(record['snapshotHex'])
    profiles.require(len(raw) == snapshot['structureSize'] == 33208, 'RECOVERY_BASELINE_ABI')
    old_scene = readonly.load_decoder().decode_snapshot({'snapshotHex':
        prior[prior_decoder.AFTER_AT:prior_decoder.AFTER_AT + 33208].hex(), 'snapshotBytes': 33208})
    profiles.require(snapshot['pointers'] == old_scene['pointers'] and snapshot['entities'] == old_scene['entities'],
        'RECOVERY_BASELINE_SCENE_CHANGED')
    refusal_scene = readonly.load_decoder().decode_snapshot({'snapshotHex':
        refusal[33232:66440].hex(), 'snapshotBytes': 33208})
    profiles.require(snapshot['pointers'] == refusal_scene['pointers'] and snapshot['entities'] == refusal_scene['entities'],
        'RECOVERY_TOKEN_REFUSAL_SCENE_CHANGED')
    pending_scene = readonly.load_decoder().decode_snapshot({'snapshotHex':
        pending[33232:66440].hex(), 'snapshotBytes': 33208})
    profiles.require(snapshot['pointers'] == pending_scene['pointers'] and snapshot['entities'] == pending_scene['entities'],
        'RECOVERY_PENDING_DIAGNOSTIC_SCENE_CHANGED')
    matches = [e for e in snapshot['entities'] if e['id'] == identity['entityId']]
    profiles.require(len(matches) == 1 and int(matches[0]['owner'], 16) == identity['owner'], 'RECOVERY_OWNER_MISMATCH')
    path = requests.runtime_path(runtime_profile)
    profiles.require(profiles.sha256(path) == RUNTIME_PROFILE_SHA256, 'RECOVERY_ORIGINAL_BA_PROFILE_REQUIRED')
    runtime = requests.read_json(path)
    profile = profiles.load_profile()
    profiles.require(runtime['imageSha256'] == profile['image']['sha256'] and
        tuple(int(f['rva'], 16) for f in runtime['functions']) == FUNCTIONS and
        tuple(int(g['flagRva'], 16) for g in runtime['hotfixGuards']) == HOTFIX and
        all(g['requiredRuntimeByte'] == 0 for g in runtime['hotfixGuards']), 'RECOVERY_FIXED_RUNTIME_PROFILE')
    disk = profiles.verify_disk(profile)
    with profiles.TARGET_IMAGE.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
        pe = profiles.inspect_pe(image)
        for function in runtime['functions']:
            head = bytes.fromhex(function['head32'])
            offset = profiles.rva_offset(pe['sections'], int(function['rva'], 16), 32, len(image))
            profiles.require(len(head) == 32 and image[offset:offset + 32] == head, 'RECOVERY_DISK_ANCHOR_CHANGED')
    value = {'action': ACTION, 'levelId': level,
        'session': {key: baseline['session'][key] for key in requests.SESSION_FIELDS}, 'identity': identity}
    inputs = {'priorRun': str(requests.runtime_path(prior_run)), 'priorEvidenceHashes': prior_hashes,
        'priorStdoutSha256': PRIOR_STDOUT_SHA256, 'priorRawSha256': PRIOR_RAW_SHA256,
        'tokenRefusalRun': str(requests.runtime_path(token_refusal_run)),
        'tokenRefusalEvidenceHashes': refusal_hashes,
        'tokenRefusalRawSha256': TOKEN_REFUSAL_RAW_SHA256,
        'pendingDiagnosticRun': str(requests.runtime_path(pending_diagnostic_run)),
        'pendingDiagnosticEvidenceHashes': pending_hashes,
        'pendingDiagnosticRawSha256': PENDING_DIAGNOSTIC_RAW_SHA256,
        'baselineRun': str(run), 'baselineEvidenceHashes': requests._baseline_hashes(run, 'readonly'),
        'runtimeProfilePath': str(path), 'runtimeProfileSha256': profiles.sha256(path)}
    return value, raw, runtime, profile, disk, inputs


def emit_header(run, value, raw, runtime, profile, prior_raw, token_refusal_raw, pending_diagnostic_raw, *, diagnostic_only=False):
    profiles.require(type(diagnostic_only) is bool, 'RECOVERY_DIAGNOSTIC_ONLY_BOOL_REQUIRED')
    fixture = {'pid': 1, 'tid': 1, 'processCreation': 1, 'threadCreation': 1,
        'image': str(run / 'compile-only-target.invalid')}
    readonly.emit_header(profile, fixture, run, deadline=1, message_id=0xc001, nonce=1)
    file = run / 'target_config.h'
    text = replace_once(file.read_text(encoding='utf-8'), '#define HR_ACTION 0ULL', '#define HR_ACTION 8ULL')
    text = replace_once(text, '#define GS_BOOTSTRAP_READONLY 1ULL', '#define GS_BOOTSTRAP_READONLY 0ULL')
    text = '// Compile-only expired candidate; review markers are not dispatch authorization.\n' + text
    text += '#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define TA_BINDING_RECOVERY_REVIEWED 1\n'
    text += '#define TA_BINDING_RECOVERY_DIAGNOSTIC_ONLY ' + str(int(diagnostic_only)) + '\n'
    text += '#define TA_BINDING_ANCHOR_RVAS ' + ','.join(hex(rva) for rva in FUNCTIONS) + '\n'
    text += '#define TA_BINDING_ANCHOR_BYTES ' + ','.join(
        '{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in runtime['functions']) + '\n'
    text += '#define TA_BINDING_HOTFIX_RVAS ' + ','.join(hex(rva) for rva in HOTFIX) + '\n'
    names = {'entityId':'TA_BINDING_ENTITY_ID', 'templateId':'TA_BINDING_TEMPLATE_ID',
        'componentId':'TA_RECOVERY_COMPONENT_ID', 'owner':'TA_RECOVERY_OWNER', 'wrapper':'TA_RECOVERY_WRAPPER',
        'config':'TA_RECOVERY_CONFIG', 'transaction':'TA_RECOVERY_TOKEN'}
    for key, name in names.items():
        text += '#define ' + name + ' ' + str(value['identity'][key]) + ('U' if key.endswith('Id') else 'ULL') + '\n'
    for name, data in (('TA_EXPECTED_SNAPSHOT', raw), ('TA_RECOVERY_PRIOR', prior_raw),
                       ('TA_RECOVERY_PRIOR_SHA256', bytes.fromhex(PRIOR_RAW_SHA256)),
                       ('TA_RECOVERY_TOKEN_REFUSAL', token_refusal_raw),
                       ('TA_RECOVERY_TOKEN_REFUSAL_SHA256', bytes.fromhex(TOKEN_REFUSAL_RAW_SHA256)),
                       ('TA_RECOVERY_PENDING_DIAGNOSTIC', pending_diagnostic_raw),
                       ('TA_RECOVERY_PENDING_DIAGNOSTIC_SHA256', bytes.fromhex(PENDING_DIAGNOSTIC_RAW_SHA256))):
        text += 'alignas(8) inline constexpr unsigned char k' + name + '[] = {\n'
        text += '\n'.join(','.join(str(b) for b in data[i:i+32]) + ',' for i in range(0, len(data), 32)) + '\n};\n'
        text += '#define ' + name + ' k' + name + '\n'
    file.write_text(text, encoding='utf-8')
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
    new = '(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1) && !(HR_ACTION == 8 && defined(TA_BINDING_RECOVERY_REVIEWED) && TA_BINDING_RECOVERY_REVIEWED == 1))'
    file.write_text(replace_once(text, old, new), encoding='utf-8')

    file = native / 'hook_receipt_protocol.h'
    text = file.read_text(encoding='utf-8')
    text = replace_once(text, '#if HR_ACTION\n#include "game_scene_action.h"',
        '#if HR_ACTION == 8\n#include "../template-authoring/binding_recovery_native_adapter.h"\n'
        'static_assert(TA_BINDING_RECOVERY_REVIEWED == 1 && HR_READ_CONTEXT == 1, "Binding contract required");\n'
        '#elif HR_ACTION\n#include "game_scene_action.h"')
    text = replace_once(text, '#if HR_ACTION\n    GameSceneActionResult action;',
        '#if HR_ACTION == 8\n    NativeBindingRecoveryReceipt templateResult;\n#elif HR_ACTION\n    GameSceneActionResult action;')
    text = replace_once(text, 'constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS',
        'constexpr DWORD kReceiptVersion = HR_ACTION == 8 ? 12 : HR_READ_REOPEN_GUARDS')
    file.write_text(text, encoding='utf-8')

    file = native / 'hook_receipt.cpp'
    text = replace_once(file.read_text(encoding='utf-8'),
        '#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
        '#if HR_ACTION == 8\n                    ExecuteNativeBindingRecovery(&receipt->context, &receipt->templateResult);\n'
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
        '#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 8 && defined(TA_BINDING_RECOVERY_REVIEWED) && TA_BINDING_RECOVERY_REVIEWED == 1))')
    text = replace_once(text, '#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"',
        '#error "Action requires supported contract; binding requires TA_BINDING_RECOVERY_REVIEWED"')
    text = replace_once(text, '#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
        '#if HR_ACTION == 8\n                reportedOk = reportedOk && receipt->templateResult.sehCode == 0 &&\n'
        '                    receipt->templateResult.version == 2 && receipt->templateResult.priorHashVerified == 1 &&\n'
        '                    receipt->templateResult.tokenRefusalHashVerified == 1 && receipt->templateResult.afterSceneUnchanged == 1 &&\n'
        '                    (TA_BINDING_RECOVERY_DIAGNOSTIC_ONLY == 1 ?\n'
        '                    (receipt->templateResult.result.code == ge::templates::BindingRecoveryCode::diagnostic_read &&\n'
        '                     receipt->templateResult.result.identityVerified && receipt->templateResult.result.emptyReferenceVerified &&\n'
        '                     receipt->templateResult.result.originalTokenUnused && !receipt->templateResult.result.tokenVerified &&\n'
        '                     !receipt->templateResult.result.edit.notifyCalled && !receipt->templateResult.result.edit.closeCalled &&\n'
        '                     !receipt->templateResult.result.closeCoreCalled && !receipt->templateResult.result.transactionClosed) :\n'
        '                    (receipt->templateResult.result.code == ge::templates::BindingRecoveryCode::transaction_closed &&\n'
        '                    receipt->templateResult.result.pendingScopeVerified && receipt->templateResult.result.closeCoreReturned &&\n'
        '                    receipt->templateResult.result.originalTokenUnused &&\n'
        '                    receipt->templateResult.result.transactionClosed && receipt->templateResult.result.edit.notificationVerified &&\n'
        '                    receipt->templateResult.result.edit.closeVerified && !receipt->templateResult.result.edit.transactionMayBeOpen));\n'
        '#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status')
    text = replace_once(text, 'HR_ACTION ? "FIXED_SCENE_ACTION"',
        'HR_ACTION == 8 ? (TA_BINDING_RECOVERY_DIAGNOSTIC_ONLY == 1 ? "FIXED_BINDING_RECOVERY_DIAGNOSTIC" : "FIXED_BINDING_RECOVERY_ACTION") : HR_ACTION ? "FIXED_SCENE_ACTION"')
    text = replace_once(text, '#if HR_ACTION\n                std::printf(",\\"action\\":',
        BINDING_PROBE + '\n#elif HR_ACTION\n                std::printf(",\\"action\\":')
    file.write_text(text, encoding='utf-8')
    return originals


BINDING_PROBE = r'''#if HR_ACTION == 8
                const auto& recovery = receipt->templateResult;
                const auto& outcome = recovery.result;
                const auto& edit = outcome.edit;
                std::printf(",\"diagnosticOnly\":%s", TA_BINDING_RECOVERY_DIAGNOSTIC_ONLY == 1 ? "true" : "false");
                std::printf(",\"bindingRecoveryResult\":{\"size\":%u,\"version\":%u,\"sehCode\":%u,\"afterSceneUnchanged\":%u,\"priorHashVerified\":%u,\"code\":%u,\"identityVerified\":%s,\"emptyReferenceVerified\":%s,\"tokenVerified\":%s,\"transactionClosed\":%s,\"needsBinding\":%s,\"outcomeUncertain\":%s,\"emptyReferenceClassification\":%u,\"emptyReferenceId\":%u,\"notifyCalled\":%s,\"closeCalled\":%s,\"notificationVerified\":%s,\"closeVerified\":%s,\"transactionMayBeOpen\":%s,\"tokenRefusalHashVerified\":%u,\"recoveryVersion\":%u,\"pendingScopeVerified\":%s,\"closeCoreCalled\":%s,\"closeCoreReturned\":%s,\"originalTokenUnused\":%s}",
                    recovery.size, recovery.version, recovery.sehCode, recovery.afterSceneUnchanged, recovery.priorHashVerified,
                    static_cast<unsigned>(outcome.code), outcome.identityVerified ? "true" : "false",
                    outcome.emptyReferenceVerified ? "true" : "false", outcome.tokenVerified ? "true" : "false",
                    outcome.transactionClosed ? "true" : "false", outcome.needsBinding ? "true" : "false",
                    outcome.outcomeUncertain ? "true" : "false", outcome.emptyReferenceClassification, outcome.emptyReferenceId,
                    edit.notifyCalled ? "true" : "false", edit.closeCalled ? "true" : "false",
                    edit.notificationVerified ? "true" : "false", edit.closeVerified ? "true" : "false", edit.transactionMayBeOpen ? "true" : "false",
                    recovery.tokenRefusalHashVerified, outcome.recoveryVersion,
                    outcome.pendingScopeVerified ? "true" : "false", outcome.closeCoreCalled ? "true" : "false",
                    outcome.closeCoreReturned ? "true" : "false", outcome.originalTokenUnused ? "true" : "false");
                const auto printRaw = [](const char* name, const void* data, std::size_t length) {
                    std::printf(",\"%sBytes\":%zu,\"%sHex\":\"", name, length, name);
                    const auto bytes = static_cast<const unsigned char*>(data);
                    for (std::size_t i = 0; i < length; ++i) std::printf("%02x", static_cast<unsigned int>(bytes[i]));
                    std::printf("\"");
                };
                printRaw("bindingRecoveryResult", &recovery, sizeof(recovery));
                printRaw("beforeComponents", &recovery.workspace.before, sizeof(recovery.workspace.before));
                printRaw("afterComponents", &recovery.workspace.after, sizeof(recovery.workspace.after));
                printRaw("editResult", &edit, sizeof(edit));
                printRaw("afterSnapshot", &recovery.after, sizeof(recovery.after));'''


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
        ('template_catalog_capture', 'component_attachment', 'owner_notification_calls', 'binding_recovery', 'binding_recovery_native_adapter')]
    for directory, stem in units:
        obj = Path(stem + '.obj'); objects.append(obj)
        lines.extend([common + f'/c "{source / directory / (stem + ".cpp")}" /Fo:"{obj}"',
                      'if errorlevel 1 exit /b 1'])
    lines.extend([common + f'/LD "{source / "native/hook_receipt.cpp"}" /Fo:"{run / "hook_receipt.obj"}" '
        f'/Fe:"{run / "hook_receipt.dll"}" /link User32.lib Bcrypt.lib ' + ' '.join('"' + str(obj) + '"' for obj in objects),
        'if errorlevel 1 exit /b 1',
        common + f'"{source / "native/hook_receipt_probe.cpp"}" /Fo:"{run / "hook_receipt_probe.obj"}" '
        f'/Fe:"{run / "hook_receipt_probe.exe"}" /link User32.lib Bcrypt.lib Advapi32.lib', 'exit /b %ERRORLEVEL%'])
    (run / 'build.cmd').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    result = subprocess.run(['cmd.exe', '/d', '/c', str(run / 'build.cmd')], cwd=run,
                            capture_output=True, text=True, timeout=180)
    (run / 'build.log').write_text((result.stdout or '') + (result.stderr or ''), encoding='utf-8')
    profiles.require(result.returncode == 0, 'MSVC_BUILD_FAILED:' + str(run / 'build.log'))
    return str(vcvars)


def compile_candidate(prior_run, baseline_run, runtime_profile=DEFAULT_RUNTIME_PROFILE,
                      token_refusal_run=TOKEN_REFUSAL_RUN, pending_diagnostic_run=PENDING_DIAGNOSTIC_RUN,
                      *, diagnostic_only=False):
    value, raw, runtime, profile, disk, inputs = load_inputs(
        prior_run, baseline_run, runtime_profile, token_refusal_run, pending_diagnostic_run)
    prior, identity, prepared, _ = read_prior(prior_run)
    refusal, _ = read_token_refusal(token_refusal_run, prior, identity, prepared)
    pending, _ = read_pending_diagnostic(pending_diagnostic_run, prior, identity, prepared)
    reviewed_sources = source_hashes()
    # A short owned directory also keeps MSVC's cross-directory includes below MAX_PATH.
    run = OUTPUT / ('r-' + os.urandom(5).hex())
    run.mkdir(parents=True, exist_ok=False)
    sources = source_copies(run)
    emit_header(run, value, raw, runtime, profile, prior, refusal, pending, diagnostic_only=diagnostic_only)
    (run / 'baseline-snapshot.bin').write_bytes(raw)
    (run / 'prior-receipt.bin').write_bytes(prior)
    (run / 'token-refusal-receipt.bin').write_bytes(refusal)
    (run / 'pending-diagnostic-receipt.bin').write_bytes(pending)
    manifest = {'schemaVersion': 1, 'kind': 'template-binding-recovery-compile-candidate-v2',
        'compileOnly': True, 'launchable': False, 'allowWrites': False, 'reviewed': False,
        'nativeCalled': False, 'probeExecuted': False, 'action': ACTION, 'actionCode': 8,
        'receiptVersion': 12, 'identity': value['identity'], 'levelId': value['levelId'],
        'diagnosticOnly': diagnostic_only,
        'buildIdentity': {'pid': 1, 'tid': 1, 'deadline': 1}, 'inputs': inputs, 'disk': disk,
        'sourceHashes': reviewed_sources, 'originalSourceHashes': sources,
        'limits': 'Compile only. Sole recovery closes the original empty bag edit. Binding, save and gameplay remain unverified.'}
    readonly.write_json(run / 'candidate-inputs.json', manifest)
    compiler = compile_sources(run)
    profiles.require(reviewed_sources == source_hashes(), 'RECOVERY_SOURCE_CHANGED_DURING_COMPILE')
    profiles.require(inputs['priorEvidenceHashes'] == prior_evidence_hashes(prior_run) and
        inputs['tokenRefusalEvidenceHashes'] == token_refusal_evidence_hashes(token_refusal_run) and
        inputs['pendingDiagnosticEvidenceHashes'] == pending_diagnostic_evidence_hashes(pending_diagnostic_run) and
        inputs['baselineEvidenceHashes'] == requests._baseline_hashes(Path(inputs['baselineRun']), 'readonly'),
        'RECOVERY_INPUT_CHANGED_DURING_COMPILE')
    manifest.update(ok=True, compiled=True, compiler=compiler, run=str(run),
        completedAtUtc=datetime.now(timezone.utc).isoformat(),
        hashes={str(p.relative_to(run)).replace('\\', '/'): profiles.sha256(p)
            for p in sorted(run.rglob('*')) if p.is_file()})
    readonly.write_json(run / 'candidate-manifest.json', manifest)
    return {key: manifest[key] for key in ('ok', 'run', 'compiled', 'compileOnly', 'launchable',
        'allowWrites', 'reviewed', 'nativeCalled', 'probeExecuted')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('compile-check')
    command.add_argument('--prior-run', required=True)
    command.add_argument('--baseline-run', required=True)
    command.add_argument('--runtime-profile', default=str(DEFAULT_RUNTIME_PROFILE))
    command.add_argument('--token-refusal-run', default=str(TOKEN_REFUSAL_RUN))
    command.add_argument('--pending-diagnostic-run', default=str(PENDING_DIAGNOSTIC_RUN))
    command.add_argument('--diagnostic-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = compile_candidate(args.prior_run, args.baseline_run, args.runtime_profile, args.token_refusal_run,
            args.pending_diagnostic_run, diagnostic_only=args.diagnostic_only)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'compileOnly': True, 'launchable': False,
            'allowWrites': False, 'nativeCalled': False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


