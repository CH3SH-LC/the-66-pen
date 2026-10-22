"""Offline acceptance of a dedicated skill action receipt; never execute or save.

Raw ABI confirmed with MSVC sizeof/offsetof in task-bi/skill-layout.json. Transport,
scene invariants, native result fields and both catalogue deltas are checked
independently. Registration acceptance does not prove names/defaults/persistence.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import struct

import build_skill_candidate as candidate
import receipt as catalogs
import skill_review as reviews

requests, profiles, readonly = candidate.requests, candidate.profiles, candidate.readonly
PREPARED_ROOT = candidate.ROOT / '.runtime/template-authoring/prepared-skill'
MAX_STDOUT_BYTES = 8 * 1024 * 1024
SNAPSHOT_BYTES = 33208
RECEIPT_BYTES = 894392
ACTION_AT, EXPECTED_AT, AFTER_AT = 16, 120, 33328
BEFORE_CATALOG_AT, AFTER_CATALOG_AT = 369784, 632088
import skill_receipt as native


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
    require(len(raw) <= MAX_STDOUT_BYTES, 'SKILL_STDOUT_LIMIT')
    # The dedicated launcher copies raw native stdout bytes, with no UTF-16 redirect.
    text = raw.decode('utf-8-sig', errors='strict')
    records = [json.loads(line, object_pairs_hook=requests._unique_object)
               for line in text.splitlines() if line.strip()]
    require(len(records) == 1 and type(records[0]) is dict, 'EXACTLY_ONE_SKILL_RECEIPT_REQUIRED')
    return records[0]


def decode_native(record):
    require(record.get('skillResultBytes') == RECEIPT_BYTES, 'SKILL_RECEIPT_ABI')
    raw = blob(record.get('skillResultHex'), RECEIPT_BYTES, 'SKILL_RECEIPT')
    action = native.decode(raw)
    summary = record.get('skillResult')
    require(type(summary) is dict, 'SKILL_RESULT_SUMMARY_REQUIRED')
    for key, value in action.items():
        supplied = record.get(key) if key in ('observedMainClass', 'observedCompanionClass') else summary.get(key)
        if key in ('defaultTable','defaultRecord','returnedResource','companionResource','observedMainClass','observedCompanionClass'):
            require(type(supplied) is str and re.fullmatch('0x[0-9a-fA-F]+', supplied) is not None, 'SKILL_POINTER_SUMMARY:' + key)
            supplied = int(supplied, 16)
        require(type(supplied) is type(value) and supplied == value, 'SKILL_RAW_SUMMARY_MISMATCH:' + key)
    for key, offset, size in (('beforeCatalog', BEFORE_CATALOG_AT, catalogs.CATALOG_BYTES),
                             ('afterCatalog', AFTER_CATALOG_AT, catalogs.CATALOG_BYTES),
                             ('afterSnapshot', AFTER_AT, SNAPSHOT_BYTES)):
        require(record.get(key + 'Bytes') == size and blob(record.get(key + 'Hex'), size, key) == raw[offset:offset + size],
                'SKILL_RAW_DUPLICATE_MISMATCH:' + key)
    return action, raw[EXPECTED_AT:EXPECTED_AT + SNAPSHOT_BYTES]


def runtime_profiles(review, inputs, header):
    runtime_path = requests.runtime_path(review['runtimeProfilePath'])
    transitive = review['transitiveCurrencyProfile']
    requests.exact_fields(transitive, {'path', 'sha256'}, 'transitive-currency-profile')
    service_path = requests.runtime_path(transitive['path'])
    require(service_path == requests.runtime_path(candidate.DEFAULT_SERVICE_PROFILE), 'SKILL_SERVICE_PROFILE_PATH')
    require(profiles.sha256(runtime_path) == review['runtimeProfileSha256'] and
            profiles.sha256(service_path) == transitive['sha256'], 'SKILL_RUNTIME_OR_SERVICE_PROFILE_CHANGED')
    require(inputs.get('runtimeProfilePath') == str(runtime_path) and
            inputs.get('runtimeProfileSha256') == review['runtimeProfileSha256'] and
            inputs.get('serviceProfilePath') == str(service_path) and inputs.get('serviceProfileSha256') == transitive['sha256'],
            'SKILL_TRANSITIVE_PROFILE_BINDING')
    runtime, service = requests.read_json(runtime_path), requests.read_json(service_path)
    require(runtime['imageSha256'] == service['imageSha256'] == profiles.load_profile()['image']['sha256'] and
            runtime['metadataSha256'] == service['metadataSha256'], 'SKILL_PROFILE_BUILD_MISMATCH')
    require(tuple(int(f['rva'],16) for f in runtime['functions']) == candidate.FUNCTIONS and
            tuple(int(rva,16) for rva in runtime['hotfixZeroRvas']) == candidate.HOTFIX, 'SKILL_PROFILE_FUNCTIONS_OR_HOTFIX')
    require(tuple((f['usage'],f['slot'],f['definition']) for f in runtime['classBindings']) ==
            (('0x8a8a','0x57d3ff8',68266),('0xea00','0x57c98f8',58345)), 'SKILL_PROFILE_CLASSES')
    require(runtime['registration']['main']['subtype'] == 6 and runtime['registration']['main']['idBand'] == 6 and
            runtime['registration']['companion']['guidDomain'] == [0,1,4], 'SKILL_REGISTRATION_CONTRACT')
    create = [f for f in service['functions'] if int(f['rva'],16) == 0xb0a90c0]
    require(len(create) == 1 and create[0]['head32'] == runtime['functions'][-1]['headBytes'] and
            any(int(g['flagRva'],16) == 0x576574e for g in service['hotfixGates']), 'SKILL_SERVICE_CREATION_EVIDENCE')
    functions = runtime['functions']
    require(all(0 < len(bytes.fromhex(f['headBytes'])) == f['headLength'] <= 32 for f in functions), 'SKILL_PROFILE_ANCHOR_LENGTH')
    expected = {'TA_SKILL_ANCHOR_RVAS': ','.join(hex(rva) for rva in candidate.FUNCTIONS),
        'TA_SKILL_ANCHOR_BYTES': ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['headBytes'])) + '}' for f in functions),
        'TA_SKILL_ANCHOR_LENGTHS': ','.join(str(f['headLength']) for f in functions),
        'TA_SKILL_HOTFIX_RVAS': ','.join(hex(rva) for rva in candidate.HOTFIX)}
    text = header.read_text(encoding='utf-8')
    for key, value in expected.items():
        found = re.findall(r'^#define ' + key + r' (.+)$', text, re.M)
        require(found == [value], 'SKILL_COMPILED_PROFILE:' + key)


def scene(raw, profile, level):
    decoder = readonly.load_decoder()
    value = decoder.decode_snapshot({'snapshotHex': raw.hex(), 'snapshotBytes': len(raw)})
    counts, flags = value['counts'], value['flags']['value']
    require(value['status']['value'] == 0 and flags & 1951 == 1951 and not flags & 96,
            'SKILL_SCENE_INCOMPLETE')
    require(counts['peTimestamp'] == profile['image']['timestamp'] and
            counts['peImageSize'] == profile['image']['sizeOfImage'], 'SKILL_SCENE_BUILD')
    require(value['levelObservation']['verified'] and value['levelObservation']['levelId'] == level,
            'SKILL_SCENE_LEVEL')
    require(counts['activeKey'] == 0 and counts['contextMatchingEntries'] == 1 and
            counts['entityRejected'] == 0 and 0 < counts['entityCaptured'] == counts['entityValidEntries'] == len(value['entities']) and
            counts['entityVersionBefore'] == counts['entityVersionAfter'], 'SKILL_SCENE_COUNTS')
    require(set(profile['callbackStackRvas']) <= {f['rva'] for f in value['stack'] if f['inMainModule']},
            'SKILL_CALLBACK_STACK')
    rows = value['entities']
    require(len({row['id'] for row in rows}) == len(rows) and
            all(type(row['id']) is int and row['id'] > 0 and row['flags']['value'] & 79 == 79 and
                row['dictionaryKey'] == row['id'] and row['context'] == value['pointers']['currentContext']
                for row in rows), 'SKILL_SCENE_ENTITY_IDENTITY')
    return value


def same_scene(first, second):
    require(first['pointers'] == second['pointers'] and first['entities'] == second['entities'] and
            first['origin'] == second['origin'] and
            all(first['counts'][key] == second['counts'][key] for key in
                ('activeKey', 'contextCapacity', 'contextValidEntries', 'contextMatchingEntries',
                 'entityCapacity', 'entityValidEntries', 'entityCaptured', 'entityRejected',
                 'entityVersionBefore', 'entityVersionAfter')), 'SKILL_SCENE_CHANGED')


def date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'SKILL_TIMEZONE_REQUIRED')
    return parsed


def header_binding(path, prepared, raw):
    text = path.read_text(encoding='utf-8')
    session = prepared['session']
    expected = {'HR_ACTION': 9, 'TA_SKILL_REVIEWED': 1, 'GS_REVIEWED_ACTION_PROFILE': 1,
        'GS_BOOTSTRAP_READONLY': 0, 'HR_TARGET_PID': session['pid'], 'HR_TARGET_TID': session['tid'],
        'HR_TARGET_CREATION': session['processCreation'], 'HR_TARGET_THREAD_CREATION': session['threadCreation'],
        'HR_NONCE': prepared['nonce'], 'HR_DEADLINE': prepared['deadline'], 'HR_MESSAGE_ID': prepared['messageId']}
    for name, value in expected.items():
        found = re.findall(r'^#define ' + name + r' ([0-9]+)(?:ULL)?$', text, re.M)
        require(len(found) == 1 and int(found[0]) == value, 'SKILL_COMPILED_IDENTITY:' + name)
    image = re.findall(r'^#define HR_TARGET_IMAGE L(.+)$', text, re.M)
    require(len(image) == 1 and json.loads(image[0]) == session['image'], 'SKILL_COMPILED_IMAGE')
    baseline = re.findall(r'inline constexpr unsigned char kTemplateExpectedSnapshot\[\] = \{\n([0-9,\n]+)\n\};', text)
    require(len(baseline) == 1 and bytes(int(v) for v in baseline[0].replace('\n', '').split(',') if v) == raw,
            'SKILL_COMPILED_BASELINE')


def validate_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()), 'DEDICATED_SKILL_RUN_REQUIRED')
    prepared, built, contract = (requests.read_json(run / name) for name in
                                 ('prepared.json', 'build-result.json', 'build-contract.json'))
    for value, kind in ((prepared, 'template-skill-prepared-v1'), (built, 'template-skill-build-v1'),
                        (contract, 'template-skill-build-contract-v1')):
        require(value.get('kind') == kind and value.get('schemaVersion') == 1 and
                value.get('action') == 'create-skill' and value.get('actionCode') == 9 and
                value.get('compileOnly') is False and value.get('reviewed') is True and
                value.get('allowWrites') is True, 'DEDICATED_SKILL_BUILD_CONTRACT')
    require(prepared.get('launchable') is True and built.get('launchable') is True and
            contract.get('launchable') is False and prepared.get('compiled') is True and built.get('compiled') is True and
            built.get('ok') is True and prepared.get('receiptVersion') == contract.get('receiptVersion') == 13 and
            built.get('run') == str(run), 'SKILL_LAUNCHABLE_BUILD_REQUIRED')
    require(prepared.get('wrapperName') == built.get('wrapperName') == 'invoke-skill-probe.ps1', 'SKILL_WRAPPER')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'SKILL_PREPARED_CONTRACT_MISMATCH:' + key)
    for key in ('requestSha256', 'reviewSha256', 'nonce', 'deadline'):
        require(built.get(key) == prepared.get(key), 'SKILL_BUILD_BINDING:' + key)
    hashes = built.get('hashes')
    required = {'prepared.json', 'build-contract.json', 'target_config.h', 'baseline-snapshot.bin',
                'request.json', 'review.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-skill-probe.ps1'}
    required.update('candidate-source/native/' + name for name in candidate.NATIVE_FILES)
    required.update('candidate-source/template-authoring/' + name for name in candidate.TEMPLATE_FILES)
    require(type(hashes) is dict and required <= set(hashes), 'SKILL_ARTIFACT_HASH_SET')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
                'SKILL_ARTIFACT_CHANGED:' + name)
    review, request = requests.read_json(run / 'review.json'), requests.validate_request(requests.read_json(run / 'request.json'))
    requests.exact_fields(review, reviews.FIELDS, 'skill-review')
    require(review['state'] == 'reviewed' and review['kind'] == 'template-skill-review-v1' and
            review['reviewedBy'] == 'coordinator' and review['action'] == request['action'] == 'create-skill',
            'SKILL_REVIEW_REQUIRED')
    require(profiles.sha256(run / 'request.json') == review['requestSha256'] == prepared['requestSha256'] and
            (run / 'request.json').read_bytes() == requests.canonical_bytes(request) and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'], 'SKILL_REVIEW_REQUEST_HASH')
    require(review['sourceHashes'] == prepared['sourceHashes'] == reviews.source_hashes(), 'SKILL_SOURCE_CHANGED')
    profile = profiles.load_profile()
    require(review['readonlyProfileSha256'] == profiles.PROFILE_SHA256 and
            prepared['disk'].get('sha256') == profile['image']['sha256'], 'SKILL_CURRENT_PROFILE_REQUIRED')
    runtime_profiles(review, prepared['inputs'], run / 'target_config.h')
    session = prepared['session']
    require({key: session.get(key) for key in requests.SESSION_FIELDS} == review['session'] == request['session'] and
            all(type(session.get(key)) is int and session[key] > 1 for key in ('pid', 'tid', 'window', 'processCreation', 'threadCreation')) and
            session['windowClass'] == 'UnityWndClass' and
            Path(session['image']).resolve() == profiles.TARGET_IMAGE.resolve(), 'SKILL_REAL_SESSION_REQUIRED')
    level = request['levelId']
    require(level == review['levelId'] == prepared['levelId'] and
            review['reviewId'] == prepared['reviewId'] and prepared['ttlSeconds'] == 180 and
            review['expiresUtc'] == prepared['reviewExpiresUtc'], 'SKILL_REQUEST_IDENTITY')
    baseline_run = requests.runtime_path(review['baselineRun'])
    require(baseline_run.name == request['runId'] and review['baselineKind'] == 'readonly' and
            review['evidenceHashes'] == requests._baseline_hashes(baseline_run, 'readonly'), 'SKILL_BASELINE_CHANGED')
    # This is the original readonly baseline, never a relabelled action receipt.
    baseline, baseline_prepared = requests.review_api.load_baseline(baseline_run, 'readonly', level)
    require(all(baseline_prepared['session'].get(k) == session[k] for k in requests.SESSION_FIELDS), 'SKILL_BASELINE_SESSION')
    raw = (run / 'baseline-snapshot.bin').read_bytes()
    old_record, _ = readonly.load_decoder().read_probe(baseline_run / 'stdout.jsonl')
    require(raw == bytes.fromhex(old_record['snapshotHex']), 'SKILL_BASELINE_RAW_CHANGED')
    header_binding(run / 'target_config.h', prepared, raw)
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('requestSha256') == prepared['requestSha256'] and
            claim.get('run') == str(run) and claim.get('claim') == 'single-skill-compilation-no-auto-retry', 'SKILL_REVIEW_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'SKILL_ATTEMPT_REQUIRED:' + name)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] == 0 and
            not exit_record.get('error') and exit_record.get('scope') == 'FIXED_TEMPLATE_SKILL_ACTION', 'SKILL_NATIVE_EXIT')
    require(date(review['reviewedAtUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']) and
            0 < (date(review['expiresUtc']) - date(review['reviewedAtUtc'])).total_seconds() <= 3600,
            'SKILL_EXECUTION_OUTSIDE_REVIEW')
    record = read_record(run / 'stdout.jsonl')
    require(record.get('scope') == 'FIXED_TEMPLATE_SKILL_ACTION' and record.get('selfTestOnly') is False and
            record.get('ok') is True and record.get('probeElevatedHigh') is True and record.get('transportOk') is True and
            record.get('pid') == session['pid'] and record.get('tid') == session['tid'] and
            record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
            record.get('hostPostUnhookPings') == 0 and record.get('snapshotStatus') == 0 and
            record.get('snapshotBytes') == SNAPSHOT_BYTES, 'SKILL_NATIVE_TRANSPORT')
    action, expected = decode_native(record)
    require(expected == raw, 'SKILL_NATIVE_EXPECTED_BASELINE')
    current = scene(blob(record['snapshotHex'], SNAPSHOT_BYTES, 'CURRENT_SNAPSHOT'), profile, level)
    after = scene(blob(record['afterSnapshotHex'], SNAPSHOT_BYTES, 'AFTER_SNAPSHOT'), profile, level)
    same_scene(baseline, current); same_scene(current, after)
    native_result = native.verify(bytes.fromhex(record['skillResultHex']), level_id=level,
                                  global_pointer=int(current['pointers']['global'], 16))
    delta = native_result
    input_hashes = {name: profiles.sha256(run / name) for name in
                   (*hashes, 'build-result.json', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used')}
    return {'ok': True, 'state': 'catalog-registered-only', 'action': 'create-skill',
        'scope': 'FIXED_TEMPLATE_SKILL_ACTION', 'run': str(run), 'levelId': level,
        'requestSha256': prepared['requestSha256'], 'reviewSha256': prepared['reviewSha256'],
        'catalogRegisteredVerified': True, 'createdId': delta['createdId'],
        'companionOwnId': delta['companionOwnId'], 'createdResource': hex(action['returnedResource']),
        'companionResource': hex(action['companionResource']), 'observedMainClass': hex(action['observedMainClass']),
        'observedCompanionClass': hex(action['observedCompanionClass']), 'createCalled': action['createCalled'],
        'defaultLookupCalled': action['defaultLookupCalled'], 'outcomeUncertain': action['outcomeUncertain'],
        'persistentSaveVerified': False, 'nameVerified': False, 'defaultsVerified': False, 'gameplayVerified': False,
        'inputHashes': input_hashes, 'acceptorSha256': profiles.sha256(Path(__file__)),
        'decoderHashes': {name: profiles.sha256(Path(__file__).with_name(name)) for name in ('skill_receipt.py','receipt.py')},
        'limits': 'Native transport and independent skill registration delta only. No name/default/attachment/save/gameplay acceptance.'}



def accept_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()) and run.is_dir(), 'DEDICATED_SKILL_RUN_REQUIRED')
    output = run / 'skill-acceptance.json'
    require(not output.exists(), 'SKILL_ACCEPTANCE_ALREADY_EXISTS')
    try:
        result = validate_run(run)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        result = {'ok': False, 'state': 'refused', 'error': str(error), 'run': str(run),
                  'catalogRegisteredVerified': False, 'createdId': None, 'outcomeUncertain': None,
                  'persistentSaveVerified': False, 'nameVerified': False, 'defaultsVerified': False}
        # Preserve a parseable attempted-call marker even when acceptance fails;
        # it is reported evidence only and never authorizes an automatic retry.
        try:
            reported, _ = decode_native(read_record(run / 'stdout.jsonl'))
            result['outcomeUncertain'] = reported['outcomeUncertain'] or reported['createCalled']
            result['reportedCreateCalled'] = reported['createCalled']
            result['reportedDefaultLookupCalled'] = reported['defaultLookupCalled']
            result['reportedAllocationCalled'] = reported['allocationCalled']
            result['reportedActionStage'] = reported['stage']
            result['reportedMetadataCallsStarted'] = reported['metadataCallsStarted']
            result['reportedMetadataCallsCompleted'] = reported['metadataCallsCompleted']

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
        result = {'ok': False, 'error': str(error), 'catalogRegisteredVerified': False, 'persistentSaveVerified': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
