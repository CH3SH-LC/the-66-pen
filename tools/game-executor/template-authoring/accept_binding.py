"""Offline acceptance of a dedicated binding action receipt; never execute or save.

Raw ABI confirmed with MSVC sizeof/offsetof in task-ba/layout.json. Transport,
scene invariants, native result fields and both catalogue deltas are checked
independently. Component-binding acceptance does not prove playable-character assignment or persistence.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import struct

import build_binding_candidate as candidate
import receipt as catalogs
import binding_review as reviews
import binding_receipt as binding_raw
import component_receipt

requests, profiles, readonly = candidate.requests, candidate.profiles, candidate.readonly
PREPARED_ROOT = candidate.ROOT / '.runtime/template-authoring/prepared-binding'
MAX_STDOUT_BYTES = 8 * 1024 * 1024
SNAPSHOT_BYTES = 33208


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def blob(encoded, size, label):
    require(type(encoded) is str and len(encoded) == size * 2 and
            re.fullmatch('[0-9a-fA-F]+', encoded) is not None, label + '_SIZE_OR_HEX')
    return bytes.fromhex(encoded)


def read_record(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_STDOUT_BYTES + 1)
    require(len(raw) <= MAX_STDOUT_BYTES, 'BINDING_STDOUT_LIMIT')
    # The dedicated launcher copies raw native stdout bytes, with no UTF-16 redirect.
    text = raw.decode('utf-8-sig', errors='strict')
    records = [json.loads(line, object_pairs_hook=requests._unique_object)
               for line in text.splitlines() if line.strip()]
    require(len(records) == 1 and type(records[0]) is dict, 'EXACTLY_ONE_BINDING_RECEIPT_REQUIRED')
    return records[0]


def scene(raw, profile, level):
    decoder = readonly.load_decoder()
    value = decoder.decode_snapshot({'snapshotHex': raw.hex(), 'snapshotBytes': len(raw)})
    counts, flags = value['counts'], value['flags']['value']
    require(value['status']['value'] == 0 and flags & 1951 == 1951 and not flags & 96,
            'BINDING_SCENE_INCOMPLETE')
    require(counts['peTimestamp'] == profile['image']['timestamp'] and
            counts['peImageSize'] == profile['image']['sizeOfImage'], 'BINDING_SCENE_BUILD')
    require(value['levelObservation']['verified'] and value['levelObservation']['levelId'] == level,
            'BINDING_SCENE_LEVEL')
    require(counts['activeKey'] == 0 and counts['contextMatchingEntries'] == 1 and
            counts['entityRejected'] == 0 and 0 < counts['entityCaptured'] == counts['entityValidEntries'] == len(value['entities']) and
            counts['entityVersionBefore'] == counts['entityVersionAfter'], 'BINDING_SCENE_COUNTS')
    require(set(profile['callbackStackRvas']) <= {f['rva'] for f in value['stack'] if f['inMainModule']},
            'BINDING_CALLBACK_STACK')
    rows = value['entities']
    require(len({row['id'] for row in rows}) == len(rows) and
            all(type(row['id']) is int and row['id'] > 0 and row['flags']['value'] & 79 == 79 and
                row['dictionaryKey'] == row['id'] and row['context'] == value['pointers']['currentContext']
                for row in rows), 'BINDING_SCENE_ENTITY_IDENTITY')
    return value


def same_scene(first, second):
    require(first['pointers'] == second['pointers'] and first['entities'] == second['entities'] and
            first['origin'] == second['origin'] and
            all(first['counts'][key] == second['counts'][key] for key in
                ('activeKey', 'contextCapacity', 'contextValidEntries', 'contextMatchingEntries',
                 'entityCapacity', 'entityValidEntries', 'entityCaptured', 'entityRejected',
                 'entityVersionBefore', 'entityVersionAfter')), 'BINDING_SCENE_CHANGED')


def date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'BINDING_TIMEZONE_REQUIRED')
    return parsed


def header_binding(path, prepared, raw):
    text = path.read_text(encoding='utf-8')
    session = prepared['session']
    expected = {'HR_ACTION': 7, 'TA_BINDING_REVIEWED': 1, 'GS_REVIEWED_ACTION_PROFILE': 1,
        'GS_BOOTSTRAP_READONLY': 0, 'HR_TARGET_PID': session['pid'], 'HR_TARGET_TID': session['tid'],
        'HR_TARGET_CREATION': session['processCreation'], 'HR_TARGET_THREAD_CREATION': session['threadCreation'],
        'HR_NONCE': prepared['nonce'], 'HR_DEADLINE': prepared['deadline'], 'HR_MESSAGE_ID': prepared['messageId']}
    for name, value in expected.items():
        found = re.findall(r'^#define ' + name + r' ([0-9]+)(?:ULL)?$', text, re.M)
        require(len(found) == 1 and int(found[0]) == value, 'BINDING_COMPILED_IDENTITY:' + name)
    image = re.findall(r'^#define HR_TARGET_IMAGE L(.+)$', text, re.M)
    require(len(image) == 1 and json.loads(image[0]) == session['image'], 'BINDING_COMPILED_IMAGE')
    baseline = re.findall(r'inline constexpr unsigned char kTemplateExpectedSnapshot\[\] = \{\n([0-9,\n]+)\n\};', text)
    require(len(baseline) == 1 and bytes(int(v) for v in baseline[0].replace('\n', '').split(',') if v) == raw,
            'BINDING_COMPILED_BASELINE')


def runtime_profile(review, prepared, header, request):
    path = requests.runtime_path(review['runtimeProfilePath'])
    require(profiles.sha256(path) == review['runtimeProfileSha256'] and
            prepared['inputs'].get('runtimeProfilePath') == str(path) and
            prepared['inputs'].get('runtimeProfileSha256') == review['runtimeProfileSha256'],
            'BINDING_RUNTIME_PROFILE_BINDING')
    runtime = requests.read_json(path)
    reference = candidate.validate_reference_contract(runtime)
    require(runtime['imageSha256'] == profiles.load_profile()['image']['sha256'] and
            tuple(int(f['rva'], 16) for f in runtime['functions']) == candidate.FUNCTIONS and
            tuple(int(f['flagRva'], 16) for f in runtime['hotfixGuards']) == candidate.HOTFIX and
            tuple(int(g, 16) for g in runtime['metadataInitialization']['fixedUsageIndices']) == candidate.USAGE_GROUPS and
            {int(p['slotRva'], 16): p['definitionIndex'] for p in runtime['metadataInitialization']['slotProof']} == candidate.TYPE_SLOTS,
            'BINDING_RUNTIME_PROFILE_CONTRACT')
    require(all(len(bytes.fromhex(f['head32'])) == 32 for f in runtime['functions']), 'BINDING_ANCHOR_LENGTH')
    expected = {
        'TA_BINDING_ANCHOR_RVAS': ','.join(hex(rva) for rva in candidate.FUNCTIONS),
        'TA_BINDING_ANCHOR_BYTES': ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in runtime['functions']),
        'TA_BINDING_USAGE_GROUPS': ','.join(hex(g) for g in candidate.USAGE_GROUPS),
        'TA_BINDING_HOTFIX_RVAS': ','.join(hex(rva) for rva in candidate.HOTFIX),
        'TA_REFERENCE_ANCHOR_RVAS': ','.join(hex(rva) for rva in candidate.REFERENCE_FUNCTIONS),
        'TA_REFERENCE_ANCHOR_BYTES': ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in reference['functions']),
        'TA_REFERENCE_USAGE_GROUPS': ','.join(hex(g) for g in candidate.REFERENCE_USAGE_GROUPS),
        'TA_REFERENCE_HOTFIX_RVAS': ','.join(hex(rva) for rva in candidate.REFERENCE_HOTFIX),
        'TA_BINDING_KIND': '35' if request['action'] == 'bind-shop' else '33',
        'TA_BINDING_ENTITY_ID': str(request['parameters']['entityId']) + 'U',
        'TA_BINDING_TEMPLATE_ID': str(request['parameters']['templateId']) + 'U',
    }
    text = header.read_text(encoding='utf-8')
    for key, value in expected.items():
        require(re.findall(r'^#define ' + key + r' (.+)$', text, re.M) == [value], 'BINDING_COMPILED_PROFILE:' + key)


def validate_envelope(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()), 'DEDICATED_BINDING_RUN_REQUIRED')
    prepared, built, contract = (requests.read_json(run / name) for name in
                                 ('prepared.json', 'build-result.json', 'build-contract.json'))
    for value, kind in ((prepared, 'template-binding-prepared-v1'), (built, 'template-binding-build-v1'),
                        (contract, 'template-binding-build-contract-v1')):
        require(value.get('kind') == kind and value.get('schemaVersion') == 1 and
                value.get('action') in ('bind-shop', 'bind-bag') and value.get('actionCode') == 7 and
                value.get('compileOnly') is False and value.get('reviewed') is True and
                value.get('allowWrites') is True, 'DEDICATED_BINDING_BUILD_CONTRACT')
    require(prepared.get('launchable') is True and built.get('launchable') is True and
            contract.get('launchable') is False and prepared.get('compiled') is True and built.get('compiled') is True and
            built.get('ok') is True and prepared.get('receiptVersion') == contract.get('receiptVersion') == 11 and
            built.get('run') == str(run), 'BINDING_LAUNCHABLE_BUILD_REQUIRED')
    require(prepared.get('wrapperName') == built.get('wrapperName') == 'invoke-binding-probe.ps1', 'BINDING_WRAPPER')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'BINDING_PREPARED_CONTRACT_MISMATCH:' + key)
    for key in ('requestSha256', 'reviewSha256', 'nonce', 'deadline'):
        require(built.get(key) == prepared.get(key), 'BINDING_BUILD_BINDING:' + key)
    hashes = built.get('hashes')
    required = {'prepared.json', 'build-contract.json', 'target_config.h', 'baseline-snapshot.bin',
                'request.json', 'review.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-binding-probe.ps1'}
    required.update('candidate-source/native/' + name for name in candidate.NATIVE_FILES)
    required.update('candidate-source/template-authoring/' + name for name in candidate.TEMPLATE_FILES)
    require(type(hashes) is dict and required <= set(hashes), 'BINDING_ARTIFACT_HASH_SET')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
                'BINDING_ARTIFACT_CHANGED:' + name)
    review, request = requests.read_json(run / 'review.json'), requests.validate_request(requests.read_json(run / 'request.json'))
    requests.exact_fields(review, reviews.FIELDS, 'binding-review')
    require(review['state'] == 'reviewed' and review['kind'] == 'template-binding-review-v1' and
            review['reviewedBy'] == 'coordinator' and review['action'] == request['action'] == prepared['action'] and request['action'] in ('bind-shop', 'bind-bag'),
            'BINDING_REVIEW_REQUIRED')
    require(profiles.sha256(run / 'request.json') == review['requestSha256'] == prepared['requestSha256'] and
            (run / 'request.json').read_bytes() == requests.canonical_bytes(request) and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'], 'BINDING_REVIEW_REQUEST_HASH')
    require(review['sourceHashes'] == prepared['sourceHashes'] == reviews.source_hashes(), 'BINDING_SOURCE_CHANGED')
    profile = profiles.load_profile()
    require(review['readonlyProfileSha256'] == profiles.PROFILE_SHA256 and
            prepared['disk'].get('sha256') == profile['image']['sha256'], 'BINDING_CURRENT_PROFILE_REQUIRED')
    runtime_path = requests.runtime_path(review['runtimeProfilePath'])
    require(profiles.sha256(runtime_path) == review['runtimeProfileSha256'], 'BINDING_RUNTIME_PROFILE_CHANGED')
    runtime_profile(review, prepared, run / 'target_config.h', request)
    session = prepared['session']
    require({key: session.get(key) for key in requests.SESSION_FIELDS} == review['session'] == request['session'] and
            all(type(session.get(key)) is int and session[key] > 1 for key in ('pid', 'tid', 'window', 'processCreation', 'threadCreation')) and
            session['windowClass'] == 'UnityWndClass' and
            Path(session['image']).resolve() == profiles.TARGET_IMAGE.resolve(), 'BINDING_REAL_SESSION_REQUIRED')
    level = request['levelId']
    require(level == review['levelId'] == prepared['levelId'] and
            review['reviewId'] == prepared['reviewId'] and prepared['ttlSeconds'] == 180 and
            review['expiresUtc'] == prepared['reviewExpiresUtc'], 'BINDING_REQUEST_IDENTITY')
    baseline_run = requests.runtime_path(review['baselineRun'])
    require(baseline_run.name == request['runId'] and review['baselineKind'] == 'readonly' and
            review['evidenceHashes'] == requests._baseline_hashes(baseline_run, 'readonly'), 'BINDING_BASELINE_CHANGED')
    # This is the original readonly baseline, never a relabelled action receipt.
    baseline, baseline_prepared = requests.review_api.load_baseline(baseline_run, 'readonly', level)
    require(all(baseline_prepared['session'].get(k) == session[k] for k in requests.SESSION_FIELDS), 'BINDING_BASELINE_SESSION')
    raw = (run / 'baseline-snapshot.bin').read_bytes()
    old_record, _ = readonly.load_decoder().read_probe(baseline_run / 'stdout.jsonl')
    require(raw == bytes.fromhex(old_record['snapshotHex']), 'BINDING_BASELINE_RAW_CHANGED')
    header_binding(run / 'target_config.h', prepared, raw)
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('requestSha256') == prepared['requestSha256'] and
            claim.get('run') == str(run) and claim.get('claim') == 'single-binding-compilation-no-auto-retry', 'BINDING_REVIEW_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'BINDING_ATTEMPT_REQUIRED:' + name)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] == 0 and
            not exit_record.get('error') and exit_record.get('scope') == 'FIXED_TEMPLATE_BINDING_ACTION', 'BINDING_NATIVE_EXIT')
    require(date(review['reviewedAtUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']) and
            0 < (date(review['expiresUtc']) - date(review['reviewedAtUtc'])).total_seconds() <= 3600,
            'BINDING_EXECUTION_OUTSIDE_REVIEW')
    record = read_record(run / 'stdout.jsonl')
    require(record.get('scope') == 'FIXED_TEMPLATE_BINDING_ACTION' and record.get('selfTestOnly') is False and
            record.get('ok') is True and record.get('probeElevatedHigh') is True and record.get('transportOk') is True and
            record.get('pid') == session['pid'] and record.get('tid') == session['tid'] and
            record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
            record.get('hostPostUnhookPings') == 0 and record.get('snapshotStatus') == 0 and
            record.get('snapshotBytes') == SNAPSHOT_BYTES, 'BINDING_NATIVE_TRANSPORT')
    return {'run': run, 'record': record, 'raw': raw, 'profile': profile,
            'baseline': baseline, 'level': level, 'request': request, 'review': review,
            'prepared': prepared, 'hashes': hashes}


def decode_native(record):
    require(record.get('bindingResultBytes') == binding_raw.RECEIPT_BYTES, 'BINDING_RECEIPT_ABI')
    raw = blob(record.get('bindingResultHex'), binding_raw.RECEIPT_BYTES, 'BINDING_RECEIPT')
    decoded = binding_raw.decode_native(raw)
    native, action, binding, attachment = (decoded[k] for k in ('native', 'action', 'binding', 'attachment'))
    summary = record.get('bindingResult')
    require(type(summary) is dict, 'BINDING_SUMMARY_REQUIRED')
    expected = {k: v for k, v in native.items() if k != 'classes'}
    expected.update({k: v for k, v in action.items() if k in (
        'code', 'stage', 'entityId', 'templateId', 'componentId', 'shopIndex', 'reused',
        'postBindingVerified', 'catalogsUnchanged', 'needsOwnerNotification', 'outcomeUncertain')})
    expected.update(bindCode=binding['code'], bindStage=binding['stage'], attachCalled=attachment['attachCalled'])
    expected.update({k: binding[k] for k in ('referenceFactoryCalled', 'addCalled', 'setterCalled', 'dependencyRefreshCalled')})
    for key, value in expected.items():
        require(type(summary.get(key)) is type(value) and summary[key] == value, 'BINDING_RAW_SUMMARY_MISMATCH:' + key)
    edit_summary = record.get('editResult')
    require(type(edit_summary) is dict, 'BINDING_EDIT_SUMMARY_REQUIRED')
    for key in ('code', 'stage', 'openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled',
                'notificationVerified', 'closeVerified', 'transactionMayBeOpen', 'needsPersistenceAcceptance'):
        require(type(edit_summary.get(key)) is type(decoded['edit'][key]) and edit_summary[key] == decoded['edit'][key],
                'BINDING_EDIT_RAW_SUMMARY_MISMATCH:' + key)
    parts = [
        ('beforeCatalog', binding_raw.BEFORE_CATALOG_AT, catalogs.CATALOG_BYTES),
        ('afterCatalog', binding_raw.AFTER_CATALOG_AT, catalogs.CATALOG_BYTES),
        ('beforeComponents', binding_raw.BEFORE_COMPONENTS_AT, component_receipt.COMPONENT_BYTES),
        ('afterAttachmentComponents', binding_raw.AFTER_ATTACH_AT, component_receipt.COMPONENT_BYTES),
        ('afterComponents', binding_raw.FINAL_COMPONENTS_AT, component_receipt.COMPONENT_BYTES),
        ('editResult', binding_raw.EDIT_AT, binding_raw.EDIT_BYTES),
        ('afterSnapshot', binding_raw.AFTER_AT, SNAPSHOT_BYTES)]
    parts += [(name, binding_raw.EDIT_AT + offset, binding_raw.STATE_BYTES) for name, offset in
              (('editBefore', 80), ('editAfterSnapshot', 12496), ('editAfterNotify', 24912), ('editAfterClose', 37328))]
    for key, offset, size in parts:
        require(record.get(key + 'Bytes') == size and
                blob(record.get(key + 'Hex'), size, key) == raw[offset:offset + size],
                'BINDING_RAW_DUPLICATE_MISMATCH:' + key)
    return decoded, raw


def validate_run(run):
    envelope = validate_envelope(run)
    run, record = envelope['run'], envelope['record']
    decoded, raw = decode_native(record)
    require(raw[binding_raw.EXPECTED_AT:binding_raw.EXPECTED_AT + SNAPSHOT_BYTES] == envelope['raw'],
            'BINDING_NATIVE_EXPECTED_BASELINE')
    current = scene(blob(record['snapshotHex'], SNAPSHOT_BYTES, 'CURRENT_SNAPSHOT'), envelope['profile'], envelope['level'])
    after = scene(blob(record['afterSnapshotHex'], SNAPSHOT_BYTES, 'AFTER_SNAPSHOT'), envelope['profile'], envelope['level'])
    same_scene(envelope['baseline'], current); same_scene(current, after)
    accepted = binding_raw.verify_binding(raw, decoded, request=envelope['request'], current=current)
    hashes = {name: profiles.sha256(run / name) for name in
              (*envelope['hashes'], 'build-result.json', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used')}
    return dict(accepted, ok=True, state='binding-readback-only', action=envelope['request']['action'],
        scope='FIXED_TEMPLATE_BINDING_ACTION', run=str(run), levelId=envelope['level'],
        requestSha256=envelope['prepared']['requestSha256'], reviewSha256=envelope['prepared']['reviewSha256'],
        persistentSaveVerified=False, gameplayVerified=False, inputHashes=hashes,
        acceptorSha256=profiles.sha256(Path(__file__)),
        decoderHashes={p.name: profiles.sha256(p) for p in
                      (Path(binding_raw.__file__), Path(component_receipt.__file__), Path(catalogs.__file__))},
        limits='Raw native binding and edit transaction only. Player-character assignment, save/reopen, inventory and gameplay require separate acceptance.')


def accept_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()) and run.is_dir(), 'DEDICATED_BINDING_RUN_REQUIRED')
    output = run / 'binding-acceptance.json'
    require(not output.exists(), 'BINDING_ACCEPTANCE_ALREADY_EXISTS')
    try:
        result = validate_run(run)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        result = dict(ok=False, state='refused', error=str(error), run=str(run), bindingVerified=False,
                      persistentSaveVerified=False, gameplayVerified=False, outcomeUncertain=None)
        # Retain attempted operations even when readback or envelope acceptance
        # fails. This is reported evidence and never permission to retry/close.
        try:
            reported, _ = decode_native(read_record(run / 'stdout.jsonl'))
            result.update(outcomeUncertain=reported['action']['outcomeUncertain'],
                reportedComponentMutationCalled=reported['native']['componentMutationCalled'],
                reportedTransactionMayBeOpen=reported['edit']['transactionMayBeOpen'])
        except (OSError, ValueError, KeyError, TypeError, struct.error):
            pass
        result['inputHashes'] = {name: profiles.sha256(run / name) for name in
            ('prepared.json', 'build-result.json', 'build-contract.json', 'stdout.jsonl', 'stderr.txt', 'exit.json')
            if (run / name).is_file()}
    readonly.write_json(output, result)
    return dict(result, output=str(output))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    args = parser.parse_args(argv)
    try:
        result = accept_run(args.run)
    except (OSError, ValueError) as error:
        result = dict(ok=False, error=str(error), bindingVerified=False, persistentSaveVerified=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
