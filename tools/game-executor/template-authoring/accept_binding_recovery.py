"""Offline acceptance of a dedicated, one-attempt partial bag transaction closure."""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
import struct

import accept_binding as binding
import binding_recovery_receipt as raw_api
import binding_receipt as prior_api

requests, profiles, readonly = binding.requests, binding.profiles, binding.readonly
require, blob, date = binding.require, binding.blob, binding.date
ROOT = Path(__file__).resolve().parents[3]
PREPARED_ROOT = ROOT / '.runtime/template-authoring/prepared-binding-recovery'
SCOPE = 'FIXED_BINDING_RECOVERY_ACTION'
ACTION = 'close-partial-bag-edit'
REVIEW_FIELDS = {'schemaVersion', 'kind', 'reviewId', 'reviewerRole', 'action', 'priorRun', 'priorEvidenceHashes',
    'priorStdoutSha256', 'priorRawSha256', 'baselineRun', 'evidenceHashes', 'levelId', 'session', 'sourceHashes',
    'runtimeProfilePath', 'runtimeProfileSha256', 'recovery', 'issuedUtc', 'expiresUtc',
    'tokenRefusalRun', 'tokenRefusalEvidenceHashes', 'diagnosticOnly', 'pendingDiagnosticRun', 'pendingDiagnosticEvidenceHashes'}


def hashes_match(run, hashes, required):
    require(type(hashes) is dict and required <= set(hashes), 'RECOVERY_ARTIFACT_HASH_SET')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        require(path != run and path.is_relative_to(run) and profiles.sha256(path) == digest,
                'RECOVERY_ARTIFACT_CHANGED:' + name)


def transport(record, session, scope, *, successful):
    require(record.get('scope') == scope and record.get('selfTestOnly') is False and
            record.get('ok') is successful and record.get('probeElevatedHigh') is True and record.get('transportOk') is True and
            record.get('pid') == session['pid'] and record.get('tid') == session['tid'] and
            record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
            record.get('hostPostUnhookPings') == 0 and record.get('snapshotStatus') == 0 and
            record.get('snapshotBytes') == raw_api.SNAPSHOT_BYTES, 'RECOVERY_NATIVE_TRANSPORT')


def historical_prior(review):
    """Validate frozen original artifacts; never compare old source with today's source."""
    run = requests.runtime_path(review['priorRun'])
    require(run.is_relative_to((ROOT / '.runtime/template-authoring/prepared-binding').resolve()), 'RECOVERY_PRIOR_RUN_ROOT')
    prepared, built, contract, old_review, request = [requests.read_json(run / name) for name in
        ('prepared.json', 'build-result.json', 'build-contract.json', 'review.json', 'request.json')]
    evidence = review['priorEvidenceHashes']
    hashes_match(run, evidence, {'prepared.json', 'build-result.json', 'build-contract.json', 'review.json', 'request.json',
        'target_config.h', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used'})
    hashes_match(run, built['hashes'], {'prepared.json', 'build-contract.json', 'review.json', 'request.json',
        'hook_receipt.dll', 'hook_receipt_probe.exe', 'target_config.h', 'baseline-snapshot.bin', 'invoke-binding-probe.ps1'})
    require(prepared.get('kind') == 'template-binding-prepared-v1' and built.get('kind') == 'template-binding-build-v1' and
            contract.get('kind') == 'template-binding-build-contract-v1' and built.get('ok') is True and
            prepared.get('action') == request.get('action') == old_review.get('action') == 'bind-bag' and
            prepared.get('actionCode') == 7 and prepared.get('receiptVersion') == 11 and prepared.get('reviewed') is True and
            prepared.get('compiled') is True and prepared.get('allowWrites') is True and prepared.get('launchable') is True,
            'RECOVERY_PRIOR_PREPARED')
    require(profiles.sha256(run / 'review.json') == prepared['reviewSha256'] == built['reviewSha256'] and
            profiles.sha256(run / 'request.json') == prepared['requestSha256'] == old_review['requestSha256'] and
            old_review['kind'] == 'template-binding-review-v1' and old_review['state'] == 'reviewed' and
            old_review['reviewedBy'] == 'coordinator' and old_review['sourceHashes'] == prepared['sourceHashes'],
            'RECOVERY_PRIOR_REVIEW_BINDING')
    originals = prepared['originalNativeSourceHashes']
    require(type(originals) is dict and originals, 'RECOVERY_PRIOR_SOURCE_SET')
    for name, digest in originals.items():
        require(prepared['sourceHashes'].get('tools/game-executor/' + name) == digest and
                'candidate-source/' + name in built['hashes'], 'RECOVERY_PRIOR_SOURCE_COPY_BINDING:' + name)
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'RECOVERY_PRIOR_CONTRACT:' + key)
    session = review['session']
    require({k: prepared['session'][k] for k in requests.SESSION_FIELDS} == request['session'] == old_review['session'] == session and
            prepared['levelId'] == request['levelId'] == old_review['levelId'] == review['levelId'], 'RECOVERY_PRIOR_SESSION')
    require(profiles.sha256(run / 'stdout.jsonl') == review['priorStdoutSha256'], 'RECOVERY_PRIOR_STDOUT_SHA')
    record = binding.read_record(run / 'stdout.jsonl')
    transport(record, session, 'FIXED_TEMPLATE_BINDING_ACTION', successful=False)
    decoded, raw = binding.decode_native(record)
    require(hashlib.sha256(raw).hexdigest() == review['priorRawSha256'], 'RECOVERY_PRIOR_RAW_SHA')
    raw_api.verify_prior(raw)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] != 0 and
            not exit_record.get('error') and exit_record.get('scope') == 'FIXED_TEMPLATE_BINDING_ACTION', 'RECOVERY_PRIOR_EXIT')
    require(date(old_review['reviewedAtUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(old_review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']), 'RECOVERY_PRIOR_TIME')
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('requestSha256') == prepared['requestSha256'] and
            claim.get('run') == str(run) and claim.get('claim') == 'single-binding-compilation-no-auto-retry', 'RECOVERY_PRIOR_CLAIM')
    for name in ('attempt.used', 'launch.claim'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'RECOVERY_PRIOR_ATTEMPT')
    return raw, decoded


def historical_token_refusal(review, prior_raw, candidate):
    run = requests.runtime_path(review['tokenRefusalRun'])
    require(run == candidate.TOKEN_REFUSAL_RUN.resolve(), 'RECOVERY_EXACT_REFUSAL_RUN')
    prepared, built, contract, old_review = [requests.read_json(run / name) for name in
        ('prepared.json', 'build-result.json', 'build-contract.json', 'review.json')]
    hashes_match(run, review['tokenRefusalEvidenceHashes'], {'prepared.json', 'build-result.json', 'build-contract.json',
        'review.json', 'target_config.h', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used'})
    hashes_match(run, built['hashes'], {'prepared.json', 'build-contract.json', 'review.json', 'target_config.h',
        'hook_receipt.dll', 'hook_receipt_probe.exe', 'baseline-snapshot.bin', 'prior-receipt.bin', 'invoke-binding-recovery-probe.ps1'})
    for value, suffix in ((prepared, 'prepared'), (built, 'build'), (contract, 'build-contract')):
        require(value.get('kind') == 'template-binding-recovery-' + suffix + '-v1' and value.get('action') == ACTION and
                value.get('actionCode') == 8 and value.get('receiptVersion') == 12 and value.get('reviewed') is True,
                'RECOVERY_REFUSAL_BUILD')
    require(built.get('ok') is True and prepared.get('launchable') is True and prepared.get('compiled') is True and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'] == built['reviewSha256'] and
            old_review.get('reviewerRole') == 'coordinator' and old_review.get('kind') == 'template-binding-recovery-review-v1' and
            old_review['priorRawSha256'] == review['priorRawSha256'] and old_review['sourceHashes'] == prepared['sourceHashes'],
            'RECOVERY_REFUSAL_REVIEW')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'): require(prepared.get(key) == value, 'RECOVERY_REFUSAL_CONTRACT:' + key)
    for name, digest in prepared['originalNativeSourceHashes'].items():
        require(prepared['sourceHashes'].get('tools/game-executor/' + name) == digest and
                'candidate-source/' + name in built['hashes'], 'RECOVERY_REFUSAL_SOURCE_COPY')
    require(profiles.sha256(run / 'stdout.jsonl') == candidate.TOKEN_REFUSAL_STDOUT_SHA256 and
            (run / 'prior-receipt.bin').read_bytes() == prior_raw and prepared['levelId'] == review['levelId'] and
            old_review['session'] == review['session'], 'RECOVERY_REFUSAL_BINDING')
    record = binding.read_record(run / 'stdout.jsonl'); transport(record, review['session'], SCOPE, successful=False)
    raw = blob(record.get('bindingRecoveryResultHex'), raw_api.LEGACY_RECEIPT_BYTES, 'RECOVERY_REFUSAL_RAW')
    require(record.get('bindingRecoveryResultBytes') == len(raw) and hashlib.sha256(raw).hexdigest() == candidate.TOKEN_REFUSAL_RAW_SHA256,
            'RECOVERY_REFUSAL_RAW_SHA')
    raw_api.verify_token_refusal(raw, prior_raw)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and exit_record.get('exitCode') == 1 and not exit_record.get('error') and
            exit_record.get('scope') == SCOPE and date(old_review['issuedUtc']) <= date(prepared['preparedAtUtc']) <=
            date(exit_record['startedUtc']) < date(old_review['expiresUtc']), 'RECOVERY_REFUSAL_EXIT')
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('priorRawSha256') == review['priorRawSha256'] and
            claim.get('run') == str(run), 'RECOVERY_REFUSAL_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'RECOVERY_REFUSAL_ATTEMPT')
    return raw


def historical_pending_diagnostic(review, prior_raw, refusal_raw, candidate):
    run = requests.runtime_path(review['pendingDiagnosticRun'])
    require(run == candidate.PENDING_DIAGNOSTIC_RUN.resolve() and
            profiles.sha256(run / 'build-result.json') == candidate.PENDING_DIAGNOSTIC_BUILD_SHA256, 'RECOVERY_FIXED_PENDING_PACKAGE')
    prepared, built, contract, old_review = [requests.read_json(run / name) for name in
        ('prepared.json', 'build-result.json', 'build-contract.json', 'review.json')]
    hashes_match(run, review['pendingDiagnosticEvidenceHashes'], {'prepared.json', 'build-result.json', 'build-contract.json',
        'review.json', 'target_config.h', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used'})
    hashes_match(run, built['hashes'], {'prepared.json', 'build-contract.json', 'review.json', 'target_config.h',
        'hook_receipt.dll', 'hook_receipt_probe.exe', 'baseline-snapshot.bin', 'prior-receipt.bin',
        'token-refusal-receipt.bin', 'invoke-binding-recovery-probe.ps1'})
    require(all(v.get('diagnosticOnly') is True and v.get('allowWrites') is False for v in (prepared, built, contract)) and
            old_review.get('diagnosticOnly') is True and old_review.get('reviewerRole') == 'coordinator' and built.get('ok') is True and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'] == built['reviewSha256'] and
            prepared['sourceHashes'] == old_review['sourceHashes'] and old_review['session'] == review['session'], 'RECOVERY_PENDING_REVIEW')
    for name, digest in prepared['originalNativeSourceHashes'].items():
        require(prepared['sourceHashes'].get('tools/game-executor/' + name) == digest and
                'candidate-source/' + name in built['hashes'], 'RECOVERY_PENDING_SOURCE_COPY')
    require((run / 'prior-receipt.bin').read_bytes() == prior_raw and (run / 'token-refusal-receipt.bin').read_bytes() == refusal_raw and
            profiles.sha256(run / 'stdout.jsonl') == candidate.PENDING_DIAGNOSTIC_STDOUT_SHA256, 'RECOVERY_PENDING_PRIOR_BINDING')
    record = binding.read_record(run / 'stdout.jsonl')
    transport(record, review['session'], 'FIXED_BINDING_RECOVERY_DIAGNOSTIC', successful=True)
    raw = blob(record.get('bindingRecoveryResultHex'), raw_api.RECEIPT_BYTES, 'RECOVERY_PENDING_RAW')
    require(record.get('diagnosticOnly') is True and hashlib.sha256(raw).hexdigest() == candidate.PENDING_DIAGNOSTIC_RAW_SHA256,
            'RECOVERY_PENDING_RAW_SHA')
    raw_api.verify_pending_diagnostic(raw, prior_raw, refusal_raw)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and exit_record.get('exitCode') == 0 and not exit_record.get('error') and
            exit_record.get('diagnosticOnly') is True and exit_record.get('allowWrites') is False and
            exit_record.get('scope') == 'FIXED_BINDING_RECOVERY_DIAGNOSTIC', 'RECOVERY_PENDING_EXIT')
    return raw


def compiled_header(path, prepared, baseline_raw, prior_raw, runtime, token_refusal_raw=None, pending_diagnostic_raw=None):
    text = path.read_text(encoding='utf-8')
    session = prepared['session']; identity = prepared['identity']
    expected = {'HR_ACTION': 8, 'TA_BINDING_RECOVERY_REVIEWED': 1, 'GS_REVIEWED_ACTION_PROFILE': 1,
        'GS_BOOTSTRAP_READONLY': 0, 'HR_TARGET_PID': session['pid'], 'HR_TARGET_TID': session['tid'],
        'HR_TARGET_CREATION': session['processCreation'], 'HR_TARGET_THREAD_CREATION': session['threadCreation'],
        'HR_NONCE': prepared['nonce'], 'HR_DEADLINE': prepared['deadline'], 'HR_MESSAGE_ID': prepared['messageId'],
        'TA_BINDING_ENTITY_ID': identity['entityId'], 'TA_BINDING_TEMPLATE_ID': identity['templateId'],
        'TA_RECOVERY_COMPONENT_ID': identity['componentId'], 'TA_RECOVERY_OWNER': identity['owner'],
        'TA_RECOVERY_WRAPPER': identity['wrapper'], 'TA_RECOVERY_CONFIG': identity['config'], 'TA_RECOVERY_TOKEN': identity['transaction']}
    if pending_diagnostic_raw is not None: expected['TA_BINDING_RECOVERY_DIAGNOSTIC_ONLY'] = 0
    for name, value in expected.items():
        found = re.findall(r'^#define ' + name + r' ([0-9]+)(?:ULL|U)?$', text, re.M)
        require(len(found) == 1 and int(found[0]) == value, 'RECOVERY_COMPILED_IDENTITY:' + name)
    image = re.findall(r'^#define HR_TARGET_IMAGE L(.+)$', text, re.M)
    require(len(image) == 1 and json.loads(image[0]) == session['image'], 'RECOVERY_COMPILED_IMAGE')
    arrays = [('TA_EXPECTED_SNAPSHOT', baseline_raw), ('TA_RECOVERY_PRIOR', prior_raw),
              ('TA_RECOVERY_PRIOR_SHA256', hashlib.sha256(prior_raw).digest())]
    if token_refusal_raw is not None:
        arrays += [('TA_RECOVERY_TOKEN_REFUSAL', token_refusal_raw),
                   ('TA_RECOVERY_TOKEN_REFUSAL_SHA256', hashlib.sha256(token_refusal_raw).digest())]
    if pending_diagnostic_raw is not None:
        arrays += [('TA_RECOVERY_PENDING_DIAGNOSTIC', pending_diagnostic_raw),
                   ('TA_RECOVERY_PENDING_DIAGNOSTIC_SHA256', hashlib.sha256(pending_diagnostic_raw).digest())]
    for macro, expected_raw in arrays:
        alias = re.findall(r'^#define ' + macro + r' ([A-Za-z_][A-Za-z_0-9]*)$', text, re.M)
        require(len(alias) == 1, 'RECOVERY_COMPILED_ARRAY_ALIAS:' + macro)
        found = re.findall(r'unsigned char ' + alias[0] + r'\[\]\s*=\s*\{([^}]+)\};', text, re.S)
        require(len(found) == 1 and bytes(int(x.strip(), 0) for x in found[0].split(',') if x.strip()) == expected_raw,
                'RECOVERY_COMPILED_ARRAY:' + macro)
    expected_profile = {
        'TA_BINDING_ANCHOR_RVAS': ','.join(f['rva'] for f in runtime['functions']),
        'TA_BINDING_ANCHOR_BYTES': ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in runtime['functions']),
        'TA_BINDING_HOTFIX_RVAS': ','.join(f['flagRva'] for f in runtime['hotfixGuards'])}
    for key, value in expected_profile.items():
        actual = re.findall(r'^#define ' + key + r' (.+)$', text, re.M)
        require(actual == [value], 'RECOVERY_COMPILED_PROFILE:' + key)


def validate_envelope(run):
    candidate = importlib.import_module('build_binding_recovery_candidate')
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()), 'DEDICATED_RECOVERY_RUN_REQUIRED')
    prepared, built, contract, review = [requests.read_json(run / name) for name in
        ('prepared.json', 'build-result.json', 'build-contract.json', 'review.json')]
    for data, suffix in ((prepared, 'prepared'), (built, 'build'), (contract, 'build-contract')):
        require(data.get('kind') == 'template-binding-recovery-' + suffix + '-v2' and data.get('schemaVersion') == 1 and
                data.get('action') == ACTION and data.get('actionCode') == 8 and data.get('compileOnly') is False and
                data.get('allowWrites') is True and data.get('reviewed') is True and data.get('diagnosticOnly') is False, 'RECOVERY_BUILD_CONTRACT')
    require(prepared.get('receiptVersion') == contract.get('receiptVersion') == 12 and built.get('ok') is True and
            prepared.get('compiled') is True and built.get('compiled') is True and built.get('run') == str(run) and
            prepared.get('launchable') is True and built.get('launchable') is True and contract.get('launchable') is False and
            prepared.get('wrapperName') == built.get('wrapperName') == 'invoke-binding-recovery-probe.ps1', 'RECOVERY_LAUNCHABLE_BUILD')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'RECOVERY_PREPARED_CONTRACT:' + key)
    for key in ('reviewSha256', 'nonce', 'deadline'):
        require(built.get(key) == prepared[key], 'RECOVERY_BUILD_BINDING:' + key)
    hashes = built['hashes']
    required = {'prepared.json', 'build-contract.json', 'target_config.h', 'baseline-snapshot.bin', 'prior-receipt.bin',
        'review.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-binding-recovery-probe.ps1',
        'token-refusal-receipt.bin', 'pending-diagnostic-receipt.bin'}
    required.update('candidate-source/' + name for name in prepared['originalNativeSourceHashes'])
    hashes_match(run, hashes, required)
    requests.exact_fields(review, REVIEW_FIELDS, 'binding-recovery-review')
    require(review['schemaVersion'] == 1 and review['kind'] == 'template-binding-recovery-review-v2' and
            review['reviewerRole'] == 'coordinator' and review['action'] == ACTION and
            review['diagnosticOnly'] is False and review['reviewId'] == prepared['reviewId'] and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'], 'RECOVERY_REVIEW_REQUIRED')
    require(review['sourceHashes'] == prepared['sourceHashes'] == candidate.source_hashes(), 'RECOVERY_SOURCE_CHANGED')
    for name, digest in prepared['originalNativeSourceHashes'].items():
        require(review['sourceHashes'].get('tools/game-executor/' + name) == digest,
                'RECOVERY_COPIED_SOURCE_NOT_REVIEWED:' + name)
    inputs = prepared['inputs']
    for key in ('priorRun', 'priorEvidenceHashes', 'priorStdoutSha256', 'priorRawSha256', 'baselineRun', 'runtimeProfilePath', 'runtimeProfileSha256',
                'tokenRefusalRun', 'tokenRefusalEvidenceHashes', 'pendingDiagnosticRun', 'pendingDiagnosticEvidenceHashes'):
        require(inputs.get(key) == review[key], 'RECOVERY_INPUT_BINDING:' + key)
    require(inputs.get('baselineEvidenceHashes') == review['evidenceHashes'], 'RECOVERY_BASELINE_BINDING')
    session = prepared['session']
    require({key: session.get(key) for key in requests.SESSION_FIELDS} == review['session'] and
            all(type(session.get(key)) is int and session[key] > 1 for key in ('pid', 'tid', 'window', 'processCreation', 'threadCreation')) and
            session['windowClass'] == 'UnityWndClass' and Path(session['image']).resolve() == profiles.TARGET_IMAGE.resolve(), 'RECOVERY_REAL_SESSION')
    require(review['levelId'] == prepared['levelId'] and prepared['ttlSeconds'] == 180 and
            review['expiresUtc'] == prepared['reviewExpiresUtc'], 'RECOVERY_REVIEW_IDENTITY')
    profile = profiles.load_profile()
    runtime_path = requests.runtime_path(review['runtimeProfilePath']); runtime = requests.read_json(runtime_path)
    require(profiles.sha256(runtime_path) == review['runtimeProfileSha256'] == candidate.RUNTIME_PROFILE_SHA256 and
            runtime['imageSha256'] == profile['image']['sha256'] and
            tuple(int(f['rva'], 16) for f in runtime['functions']) == candidate.FUNCTIONS and
            tuple(int(g['flagRva'], 16) for g in runtime['hotfixGuards']) == candidate.HOTFIX and
            all(g['requiredRuntimeByte'] == 0 for g in runtime['hotfixGuards']) and
            all(len(bytes.fromhex(f['head32'])) == 32 for f in runtime['functions']), 'RECOVERY_RUNTIME_PROFILE')
    baseline_run = requests.runtime_path(review['baselineRun'])
    require(review['evidenceHashes'] == requests._baseline_hashes(baseline_run, 'readonly'), 'RECOVERY_BASELINE_CHANGED')
    baseline, baseline_prepared = requests.review_api.load_baseline(baseline_run, 'readonly', review['levelId'])
    require(all(baseline_prepared['session'][key] == session[key] for key in requests.SESSION_FIELDS), 'RECOVERY_BASELINE_SESSION')
    original, _ = readonly.load_decoder().read_probe(baseline_run / 'stdout.jsonl')
    baseline_raw = (run / 'baseline-snapshot.bin').read_bytes()
    require(baseline_raw == bytes.fromhex(original['snapshotHex']), 'RECOVERY_BASELINE_RAW')
    prior_raw, prior = historical_prior(review)
    token_refusal_raw = historical_token_refusal(review, prior_raw, candidate)
    pending_diagnostic_raw = historical_pending_diagnostic(review, prior_raw, token_refusal_raw, candidate)
    require(inputs.get('pendingDiagnosticRawSha256') == candidate.PENDING_DIAGNOSTIC_RAW_SHA256 and
            (run / 'pending-diagnostic-receipt.bin').read_bytes() == pending_diagnostic_raw, 'RECOVERY_PENDING_COPY')
    require(inputs.get('tokenRefusalRawSha256') == candidate.TOKEN_REFUSAL_RAW_SHA256 and
            (run / 'token-refusal-receipt.bin').read_bytes() == token_refusal_raw, 'RECOVERY_REFUSAL_COPY')
    require((run / 'prior-receipt.bin').read_bytes() == prior_raw, 'RECOVERY_PRIOR_COPY')
    raw_api.verify_prior(prior_raw, identity=prepared['identity'])
    compiled_header(run / 'target_config.h', prepared, baseline_raw, prior_raw, runtime, token_refusal_raw, pending_diagnostic_raw)
    recovery = review['recovery']; requests.exact_fields(recovery, {'source', 'backup', 'sha256'}, 'recovery')
    source, backup = Path(recovery['source']).resolve(), requests.runtime_path(recovery['backup'])
    require(source.is_absolute() and source.name == str(review['levelId']) + '.gil' and
            binding.reviews.equal_files(source, backup) and profiles.sha256(source) == profiles.sha256(backup) == recovery['sha256'], 'RECOVERY_BACKUP_BYTES')
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewId') == review['reviewId'] and claim.get('reviewSha256') == prepared['reviewSha256'] and
            claim.get('priorRawSha256') == review['priorRawSha256'] and claim.get('tokenRefusalRawSha256') == candidate.TOKEN_REFUSAL_RAW_SHA256 and
            claim.get('pendingDiagnosticRawSha256') == candidate.PENDING_DIAGNOSTIC_RAW_SHA256 and claim.get('diagnosticOnly') is False and
            claim.get('action') == ACTION and claim.get('run') == str(run), 'RECOVERY_REVIEW_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'RECOVERY_ATTEMPT_REQUIRED:' + name)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] == 0 and
            not exit_record.get('error') and exit_record.get('scope') == SCOPE, 'RECOVERY_NATIVE_EXIT')
    require(date(review['issuedUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']) and
            0 < (date(review['expiresUtc']) - date(review['issuedUtc'])).total_seconds() <= 3600, 'RECOVERY_REVIEW_TIME')
    record = binding.read_record(run / 'stdout.jsonl'); transport(record, session, SCOPE, successful=True)
    return dict(run=run, prepared=prepared, review=review, profile=profile, baseline=baseline, baseline_raw=baseline_raw,
        prior_raw=prior_raw, prior=prior, token_refusal_raw=token_refusal_raw, pending_diagnostic_raw=pending_diagnostic_raw, record=record, hashes=hashes)


def decode_native(record):
    require(record.get('bindingRecoveryResultBytes') == raw_api.RECEIPT_BYTES, 'RECOVERY_RECEIPT_ABI')
    raw = blob(record.get('bindingRecoveryResultHex'), raw_api.RECEIPT_BYTES, 'RECOVERY_RECEIPT')
    d = raw_api.decode(raw)
    summary = record.get('bindingRecoveryResult')
    require(type(summary) is dict, 'RECOVERY_SUMMARY_REQUIRED')
    for key in ('size', 'version', 'sehCode', 'afterSceneUnchanged', 'priorHashVerified', 'tokenRefusalHashVerified'):
        require(type(summary.get(key)) is int and summary[key] == d['native'][key], 'RECOVERY_SUMMARY:' + key)
    for key in ('code', 'identityVerified', 'emptyReferenceVerified', 'tokenVerified', 'transactionClosed', 'needsBinding', 'outcomeUncertain',
                'emptyReferenceClassification', 'emptyReferenceId', 'recoveryVersion', 'pendingScopeVerified',
                'closeCoreCalled', 'closeCoreReturned', 'originalTokenUnused'):
        require(type(summary.get(key)) is type(d['result'][key]) and summary[key] == d['result'][key], 'RECOVERY_SUMMARY:' + key)
    for name, at, size in (('afterSnapshot', raw_api.AFTER_AT, raw_api.SNAPSHOT_BYTES),
            ('beforeComponents', raw_api.BEFORE_COMPONENTS_AT, 11376), ('afterComponents', raw_api.AFTER_COMPONENTS_AT, 11376),
            ('editResult', raw_api.EDIT_AT, prior_api.EDIT_BYTES)):
        require(record.get(name + 'Bytes') == size and blob(record.get(name + 'Hex'), size, name) == raw[at:at + size], 'RECOVERY_DUPLICATE_RAW:' + name)
    return d, raw


def validate_run(run):
    e = validate_envelope(run); d, raw = decode_native(e['record'])
    require(raw[raw_api.EXPECTED_AT:raw_api.EXPECTED_AT + raw_api.SNAPSHOT_BYTES] == e['baseline_raw'], 'RECOVERY_EXPECTED_BASELINE')
    level = e['review']['levelId']
    current = binding.scene(blob(e['record']['snapshotHex'], raw_api.SNAPSHOT_BYTES, 'CURRENT_SNAPSHOT'), e['profile'], level)
    after = binding.scene(raw[raw_api.AFTER_AT:raw_api.AFTER_AT + raw_api.SNAPSHOT_BYTES], e['profile'], level)
    prior_scene = binding.scene(e['prior_raw'][prior_api.AFTER_AT:prior_api.AFTER_AT + raw_api.SNAPSHOT_BYTES], e['profile'], level)
    binding.same_scene(e['baseline'], current); binding.same_scene(current, after); binding.same_scene(current, prior_scene)
    accepted = raw_api.verify(raw, e['prior_raw'], e['token_refusal_raw'], e['pending_diagnostic_raw'], identity=e['prepared']['identity'])
    require(d['evidence']['moduleBase'] == int(current['pointers']['moduleBase'], 16) and
            d['evidence']['global'] == int(current['pointers']['global'], 16) and
            any(row['id'] == accepted['entityId'] and int(row['owner'], 16) == d['evidence']['owner'] for row in current['entities']),
            'RECOVERY_OWNER_SCENE')
    accepted.update(ok=True, state='partial-attachment-transaction-closed', action=ACTION, scope=SCOPE, run=str(e['run']), levelId=level,
        decoderSha256=profiles.sha256(Path(raw_api.__file__)), acceptorSha256=profiles.sha256(Path(__file__)),
        inputHashes={name: profiles.sha256(e['run'] / name) for name in
            (*e['hashes'], 'build-result.json', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used')})
    return accepted


def accept_run(run):
    run = requests.runtime_path(run); require(run.is_relative_to(PREPARED_ROOT.resolve()) and run.is_dir(), 'DEDICATED_RECOVERY_RUN_REQUIRED')
    output = run / 'binding-recovery-acceptance.json'; require(not output.exists(), 'RECOVERY_ACCEPTANCE_ALREADY_EXISTS')
    try:
        result = validate_run(run)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        result = dict(ok=False, state='refused', error=str(error), run=str(run), editTransactionClosed=False, needsBinding=True,
            bindingVerified=False, persistentSaveVerified=False, gameplayVerified=False, outcomeUncertain=None)
        try:
            d, _ = decode_native(binding.read_record(run / 'stdout.jsonl'))
            result.update(outcomeUncertain=d['result']['outcomeUncertain'], reportedNotifyCalled=d['edit']['notifyCalled'],
                reportedCloseCalled=d['edit']['closeCalled'], reportedTransactionMayBeOpen=d['edit']['transactionMayBeOpen'])
        except (OSError, ValueError, KeyError, TypeError, struct.error): pass
    readonly.write_json(output, result); return dict(result, output=str(output))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    try: result = accept_run(args.run)
    except (OSError, ValueError) as error: result = dict(ok=False, error=str(error), bindingVerified=False)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result['ok'] else 2


if __name__ == '__main__': raise SystemExit(main())
