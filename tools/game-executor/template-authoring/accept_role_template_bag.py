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

import build_role_template_bag_candidate as candidate
import receipt as catalogs
import role_template_bag_review as reviews
import binding_receipt as binding_raw
import component_receipt
import snapshot_abi as abi

requests, profiles, readonly = candidate.requests, candidate.profiles, candidate.readonly
PREPARED_ROOT = candidate.ROOT / '.runtime/template-authoring/prepared-role-template-bag'
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
    expected = {'HR_ACTION': 10, 'TA_ROLE_TEMPLATE_BAG_REVIEWED': 1, 'GS_REVIEWED_ACTION_PROFILE': 1,
        'GS_BOOTSTRAP_READONLY': 0, 'HR_TARGET_PID': session['pid'], 'HR_TARGET_TID': session['tid'],
        'HR_TARGET_CREATION': session['processCreation'], 'HR_TARGET_THREAD_CREATION': session['threadCreation'],
        'HR_NONCE': prepared['nonce'], 'HR_DEADLINE': prepared['deadline'], 'HR_MESSAGE_ID': prepared['messageId'],
        'TA_ROLE_TEMPLATE_BAG_LEVEL': prepared['levelId']}
    for name, value in expected.items():
        found = re.findall(r'^#define ' + name + r' ([0-9]+)(?:ULL|U)?$', text, re.M)
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
    runtime = candidate.read_runtime(path)
    reference = candidate.validate_reference_contract(runtime)
    role = runtime['roleProfile']
    expected = {}
    for prefix, functions, groups, guards in (
        ('TA_BINDING', runtime['functions'], candidate.USAGE_GROUPS, candidate.HOTFIX),
        ('TA_REFERENCE', reference['functions'], candidate.REFERENCE_USAGE_GROUPS, candidate.REFERENCE_HOTFIX),
        ('TA_ROLE', role['functions'], tuple(int(g, 16) for g in role['usageGroups']), tuple(int(g['flagRva'], 16) for g in role['hotfixGuards']))):
        expected[prefix + '_ANCHOR_RVAS'] = ','.join(f['rva'] for f in functions)
        expected[prefix + '_ANCHOR_BYTES'] = ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in functions)
        expected[prefix + '_USAGE_GROUPS'] = ','.join(hex(g) for g in groups)
        expected[prefix + '_HOTFIX_RVAS'] = ','.join(hex(g) for g in guards)
    expected.update({'TA_ROLE_TEMPLATE_BAG_SCENE_ID': str(request['parameters']['sceneEntityId']) + 'U',
        'TA_ROLE_TEMPLATE_BAG_PREFAB_ID': str(request['parameters']['rolePrefabId']) + 'U',
        'TA_ROLE_TEMPLATE_BAG_BAG_ID': str(request['parameters']['bagId']) + 'U'})
    text = header.read_text(encoding='utf-8')
    for key, value in expected.items():
        require(re.findall(r'^#define ' + key + r' (.+)$', text, re.M) == [value], 'BINDING_COMPILED_PROFILE:' + key)


def validate_envelope(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()), 'DEDICATED_BINDING_RUN_REQUIRED')
    prepared, built, contract = (requests.read_json(run / name) for name in
                                 ('prepared.json', 'build-result.json', 'build-contract.json'))
    for value, kind in ((prepared, 'role-template-bag-prepared-v1'), (built, 'role-template-bag-build-v1'),
                        (contract, 'role-template-bag-build-contract-v1')):
        require(value.get('kind') == kind and value.get('schemaVersion') == 1 and
                value.get('action') == 'bind-role-template-bag' and value.get('actionCode') == 10 and
                value.get('compileOnly') is False and value.get('reviewed') is True and
                value.get('allowWrites') is True, 'DEDICATED_BINDING_BUILD_CONTRACT')
    require(prepared.get('launchable') is True and built.get('launchable') is True and
            contract.get('launchable') is False and prepared.get('compiled') is True and built.get('compiled') is True and
            built.get('ok') is True and prepared.get('receiptVersion') == contract.get('receiptVersion') == 14 and
            built.get('run') == str(run), 'BINDING_LAUNCHABLE_BUILD_REQUIRED')
    require(prepared.get('wrapperName') == built.get('wrapperName') == 'invoke-role-template-bag-probe.ps1', 'BINDING_WRAPPER')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'BINDING_PREPARED_CONTRACT_MISMATCH:' + key)
    for key in ('requestSha256', 'reviewSha256', 'nonce', 'deadline'):
        require(built.get(key) == prepared.get(key), 'BINDING_BUILD_BINDING:' + key)
    hashes = built.get('hashes')
    required = {'prepared.json', 'build-contract.json', 'target_config.h', 'baseline-snapshot.bin',
                'request.json', 'review.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-role-template-bag-probe.ps1'}
    required.update('candidate-source/native/' + name for name in candidate.NATIVE_FILES)
    required.update('candidate-source/template-authoring/' + name for name in candidate.TEMPLATE_FILES)
    require(type(hashes) is dict and required <= set(hashes), 'BINDING_ARTIFACT_HASH_SET')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
                'BINDING_ARTIFACT_CHANGED:' + name)
    review, request = requests.read_json(run / 'review.json'), reviews.validate_request(requests.read_json(run / 'request.json'))
    requests.exact_fields(review, reviews.FIELDS, 'binding-review')
    require(review['state'] == 'reviewed' and review['kind'] == 'role-template-bag-review-v1' and
            review['reviewedBy'] == 'coordinator' and review['action'] == request['action'] == prepared['action'] and request['action'] == 'bind-role-template-bag',
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
            review['reviewId'] == prepared['reviewId'] and prepared['ttlSeconds'] == 600 and
            review['expiresUtc'] == prepared['reviewExpiresUtc'], 'BINDING_REQUEST_IDENTITY')
    baseline_run = requests.runtime_path(review['baselineRun'])
    require(baseline_run.name == request['runId'] and review['baselineKind'] == 'readonly' and
            review['evidenceHashes'] == requests._baseline_hashes(baseline_run, 'readonly'), 'BINDING_BASELINE_CHANGED')
    # This is the original readonly baseline, never a relabelled action receipt.
    baseline, baseline_prepared = requests.review_api.load_baseline(baseline_run, 'readonly', level)
    require(all(baseline_prepared['session'].get(k) == session[k] for k in requests.SESSION_FIELDS), 'BINDING_BASELINE_SESSION')
    raw = (run / 'baseline-snapshot.bin').read_bytes()
    abi.validate_snapshot_payload(raw, 'BINDING_BASELINE_ABI')
    old_record, _ = readonly.load_decoder().read_probe(baseline_run / 'stdout.jsonl')
    require(raw == bytes.fromhex(old_record['snapshotHex']), 'BINDING_BASELINE_RAW_CHANGED')
    header_binding(run / 'target_config.h', prepared, raw)
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('requestSha256') == prepared['requestSha256'] and
            claim.get('run') == str(run) and claim.get('claim') == 'single-role-template-bag-compilation-no-auto-retry', 'BINDING_REVIEW_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'BINDING_ATTEMPT_REQUIRED:' + name)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] == 0 and
            not exit_record.get('error') and exit_record.get('scope') == 'FIXED_ROLE_TEMPLATE_BAG_ACTION', 'BINDING_NATIVE_EXIT')
    require(date(review['reviewedAtUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']) and
            0 < (date(review['expiresUtc']) - date(review['reviewedAtUtc'])).total_seconds() <= 3600,
            'BINDING_EXECUTION_OUTSIDE_REVIEW')
    record = read_record(run / 'stdout.jsonl')
    require(record.get('scope') == 'FIXED_ROLE_TEMPLATE_BAG_ACTION' and record.get('selfTestOnly') is False and
            record.get('ok') is True and record.get('probeElevatedHigh') is True and record.get('transportOk') is True and
            record.get('pid') == session['pid'] and record.get('tid') == session['tid'] and
            record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
            record.get('hostPostUnhookPings') == 0 and record.get('snapshotStatus') == 0 and
            record.get('snapshotBytes') == len(raw), 'BINDING_NATIVE_TRANSPORT')
    return {'run': run, 'record': record, 'raw': raw, 'profile': profile,
            'baseline': baseline, 'level': level, 'request': request, 'review': review,
            'prepared': prepared, 'hashes': hashes}


# MSVC layout task-role-template-bag/layout.json; common result layout stays unchanged.
RECEIPT_BYTES = 1015928
ACTION_AT, EXPECTED_AT, AFTER_AT, WORK_AT = 120, 50048, 83256, 116464
EDIT_AT, EDIT_BYTES, STATE_BYTES = ACTION_AT + 184, 49744, 12416
BEFORE_CATALOG_AT, AFTER_CATALOG_AT = WORK_AT + 303248, WORK_AT + 565552
BEFORE_COMPONENTS_AT = WORK_AT + 827856 + 9560
AFTER_ATTACH_AT = BEFORE_COMPONENTS_AT + component_receipt.COMPONENT_BYTES
FINAL_COMPONENTS_AT = WORK_AT + 860168
BEFORE_BINDING_AT, AFTER_BINDING_AT = WORK_AT + 871544, WORK_AT + 871576
BEFORE_OWNER_AT, AFTER_OWNER_AT, OWNER_BYTES = WORK_AT + 871608, WORK_AT + 879328, 7720
FINAL_EDIT_AT = WORK_AT + 887048
METADATA_CALLS = 20
components = component_receipt
values, flags, decode_state, pointer = binding_raw.values, binding_raw.flags, binding_raw.decode_state, catalogs.pointer


def receipt_layout(*, snapshot_bytes=None, receipt_bytes=None):
    """Same fixed private payload with the two reviewed snapshot ABI sizes."""
    if snapshot_bytes is None:
        matches=[size for size in abi.SIZES if RECEIPT_BYTES+2*(size-SNAPSHOT_BYTES)==receipt_bytes]
        require(len(matches)==1,'BINDING_RECEIPT_ABI')
        snapshot_bytes=matches[0]
    abi.validate_snapshot_size(snapshot_bytes,'BINDING_SNAPSHOT_ABI')
    delta=snapshot_bytes-SNAPSHOT_BYTES
    result=dict(SNAPSHOT_BYTES=snapshot_bytes,RECEIPT_BYTES=RECEIPT_BYTES+2*delta,
                ACTION_AT=ACTION_AT,EXPECTED_AT=EXPECTED_AT,AFTER_AT=AFTER_AT+delta,
                WORK_AT=WORK_AT+2*delta,EDIT_AT=EDIT_AT)
    for name in ('BEFORE_CATALOG_AT','AFTER_CATALOG_AT','BEFORE_COMPONENTS_AT',
                 'AFTER_ATTACH_AT','FINAL_COMPONENTS_AT','BEFORE_BINDING_AT',
                 'AFTER_BINDING_AT','BEFORE_OWNER_AT','AFTER_OWNER_AT','FINAL_EDIT_AT'):
        result[name]=globals()[name]+2*delta
    return result


def decode_raw(raw):
    layout=receipt_layout(receipt_bytes=len(raw))
    require(type(raw) is bytes and len(raw) == layout["RECEIPT_BYTES"], 'BINDING_RAW_SIZE')
    native = values(raw, 0, '<9I', 'size version sehCode readbackSehCode afterSceneUnchanged nativeCode metadataUsageInProgress metadataCallsStarted metadataCallsCompleted')
    require(native['size'] == layout["RECEIPT_BYTES"] and native['version'] == 1, 'BINDING_NATIVE_VERSION')
    native['classes'] = struct.unpack_from('<9Q', raw, 40)
    native.update(flags(raw, 112, 'nativeCallAttempted componentMutationCalled runtimeStateMayHaveChanged'))
    action = values(raw, layout["ACTION_AT"], '<5I', 'code stage entityId templateId componentId')
    action.update(values(raw, layout["ACTION_AT"] + 24, '<5Qi', 'owner templateResource wrapper config entry shopIndex'))
    action.update(flags(raw, layout["ACTION_AT"] + 176, 'catalogVerified templateVerified componentVerified reused postBindingVerified catalogsUnchanged needsOwnerNotification outcomeUncertain'))
    attachment = values(raw, layout["ACTION_AT"] + 72, '<I', 'code')
    attachment['row'] = components.ROW.unpack_from(raw, layout["ACTION_AT"] + 80)
    attachment['returned'] = struct.unpack_from('<Q', raw, layout["ACTION_AT"] + 120)[0]
    attachment.update(flags(raw, layout["ACTION_AT"] + 128, 'attachCalled beforeVerified afterVerified outcomeUncertain'))
    binding = values(raw, layout["ACTION_AT"] + 136, '<2I2Qi', 'code stage reference entry shopIndex')
    binding.update(flags(raw, layout["ACTION_AT"] + 164, 'referenceFactoryCalled referenceReadbackVerified addCalled entryIndexReadbackVerified setterCalled fieldReadbackVerified dependencyRefreshCalled needsDependencyRefresh mutationCalled outcomeUncertain needsOwnerNotification'))
    edit = values(raw, layout["EDIT_AT"], '<2IQ', 'code stage transaction')
    edit.update(flags(raw, layout["EDIT_AT"] + 16, 'openCalled snapshotCalled notifyCalled closeCalled snapshotVerified notificationVerified closeVerified transactionMayBeOpen outcomeUncertain needsPersistenceAcceptance'))
    evidence = values(raw, layout["EDIT_AT"] + 32, '<5Qi', 'moduleBase global owner wrapper config kind')
    evidence.update(flags(raw, layout["EDIT_AT"] + 76, 'codeAndThreadVerified'))
    observed = [values(raw, at, '<2Q2Ii', 'reference entry templateId shopCount shopIndex')
                for at in (layout["BEFORE_BINDING_AT"], layout["AFTER_BINDING_AT"])]
    return dict(native=native, action=action, attachment=attachment, binding=binding,
                edit=edit, evidence=evidence, observed=observed)


def decode_owner(data, *, scene_owner, scene_class, prefab_class, scene_id, prefab_id):
    require(len(data) == OWNER_BYTES, 'ROLE_OWNER_SIZE')
    o = values(data, 0, '<4I9Q', 'code sceneId prefabId selectedIndex sceneOwner prefabOwner expectedClass manager dictionary buckets entries bucketCapacity entryCapacity')
    require(o['code'] == 0 and o['sceneId'] == scene_id and o['prefabId'] == prefab_id and
            o['sceneOwner'] == scene_owner and o['expectedClass'] == prefab_class and
            all(pointer(o[k]) for k in ('sceneOwner','prefabOwner','expectedClass','manager','dictionary','buckets','entries')),
            'ROLE_OWNER_IDENTITY')
    header, template, scene_prefix = data[88:160], data[160:352], data[352:544]
    u32 = lambda x, at: struct.unpack_from('<I', x, at)[0]
    u64 = lambda x, at: struct.unpack_from('<Q', x, at)[0]
    require(u64(scene_prefix, 0) == scene_class and u32(scene_prefix, 0x1c) == scene_id and
            u64(scene_prefix, 0xb8) == o['prefabOwner'] and u64(template, 0) == prefab_class and
            u32(template, 0x1c) == prefab_id and template[0xb4] == 0 and u32(template, 0xb8) == 1000001,
            'ROLE_PREFAB_PREFIX_NOT_ROOT4')
    require(u64(header, 0x20) == o['buckets'] and u64(header, 0x28) == o['entries'] and
            0 < o['bucketCapacity'] <= 4096 and 0 < o['entryCapacity'] <= 4096 and
            u32(header, 0x40) <= u32(header, 0x38) <= o['entryCapacity'], 'ROLE_DICTIONARY_HEADER')
    head, count = struct.unpack_from('<iI', data, 544)
    require(0 < head <= u32(header, 0x38) and 0 < count <= 256, 'ROLE_DICTIONARY_CHAIN')
    indices = struct.unpack_from('<' + 'I' * count, data, 552)
    entries = [struct.unpack_from('<iiI4xQ', data, 1576 + i * 24) for i in range(count)]
    require(indices[0] == head - 1 and len(set(indices)) == count and
            all(index < u32(header, 0x38) for index in indices), 'ROLE_CHAIN_INDICES')
    for i, entry in enumerate(entries):
        require(entry[0] >= 0 and entry[0] % o['bucketCapacity'] == (prefab_id & 0x7fffffff) % o['bucketCapacity'] and
                entry[1] == (indices[i+1] if i+1 < count else -1), 'ROLE_CHAIN_LINK')
    found = [(index, entry) for index, entry in zip(indices, entries) if entry[2] == prefab_id]
    require(len(found) == 1 and found[0] == (o['selectedIndex'], (prefab_id & 0x7fffffff, found[0][1][1], prefab_id, o['prefabOwner'])),
            'ROLE_MANAGER_PREFAB_LOOKUP')
    o.update(dictionaryHeader=header.hex(), templatePrefix=template.hex(), scenePrefix=scene_prefix.hex(),
             chainIndices=indices, chain=entries)
    return o


def verify_role_owners(raw, decoded, *, request, current):
    layout=receipt_layout(receipt_bytes=len(raw))
    a, n, p = decoded['action'], decoded['native'], request['parameters']
    rows = [row for row in current['entities'] if row['id'] == p['sceneEntityId']]
    require(len(rows) == 1, 'ROLE_SCENE_ID_NOT_UNIQUE')
    owners = [decode_owner(raw[at:at+OWNER_BYTES], scene_owner=int(rows[0]['owner'],16),
        scene_class=n['classes'][7], prefab_class=n['classes'][8], scene_id=p['sceneEntityId'],
        prefab_id=p['rolePrefabId']) for at in (layout["BEFORE_OWNER_AT"], layout["AFTER_OWNER_AT"])]
    require(all(owners[0][key] == owners[1][key] for key in owners[0] if key not in ('templatePrefix', 'scenePrefix')) and
            owners[0]['prefabOwner'] == a['owner'], 'ROLE_OWNER_CHANGED')
    return {'rolePrefabId':p['rolePrefabId'], 'sceneEntityId':p['sceneEntityId'],
        'roleOwnerVerified': True, 'roleOwner': a['owner'], 'sceneOwner': int(rows[0]['owner'],16)}


def verify_edit(raw, decoded, *, module_base, global_pointer, kind):
    layout=receipt_layout(receipt_bytes=len(raw))
    edit, evidence, action = (decoded[k] for k in ('edit', 'evidence', 'action'))
    require(edit['code'] == 13 and edit['stage'] == 0 and pointer(edit['transaction']) and
            all(edit[k] for k in ('openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled',
                'snapshotVerified', 'notificationVerified', 'closeVerified', 'outcomeUncertain', 'needsPersistenceAcceptance')) and
            not edit['transactionMayBeOpen'], 'BINDING_EDIT_NOT_COMPLETE')
    require(evidence == {'moduleBase': module_base, 'global': global_pointer,
            'owner': action['owner'], 'wrapper': action['wrapper'], 'config': action['config'], 'kind': kind,
            'codeAndThreadVerified': True}, 'BINDING_EDIT_EVIDENCE')
    states = [decode_state(raw[layout["EDIT_AT"] + offset:layout["EDIT_AT"] + offset + STATE_BYTES], action['wrapper'])
              for offset in (80, 12496, 24912, 37328)]
    before, snapshot, notified, closed = states
    require(all(s['recordClass'] == decoded['native']['classes'][6] for s in states), 'BINDING_EDIT_RECORD_CLASS')
    require(all(all(s[key] == before[key] for key in ('manager', 'list', 'recordClass', 'literal', 'baseDepth'))
                for s in states[1:]), 'BINDING_EDIT_CONTEXT_CHANGED')
    require(before['depth'] == before['baseDepth'] and snapshot['depth'] == notified['depth'] == before['depth'] + 1 and
            closed['depth'] == before['depth'] and closed['count'] == 0, 'BINDING_EDIT_DEPTH_OR_PENDING')
    require(snapshot['targetCount'] == notified['targetCount'] == 1 and pointer(snapshot['target'][4]),
            'BINDING_EDIT_SNAPSHOT_MISSING')
    if not before['targetCount']:
        require(snapshot['count'] == before['count'] + 1 and snapshot['records'][:-1] == before['records'] and
                snapshot['target'] == snapshot['records'][-1] and snapshot['target'][3] == snapshot['target'][5] == 0,
                'BINDING_EDIT_SNAPSHOT_APPEND')
    else:
        require(snapshot['records'] == before['records'], 'BINDING_EDIT_EXISTING_RECORD_CHANGED')
    require(notified['count'] == snapshot['count'], 'BINDING_EDIT_NOTIFY_COUNT')
    for old, new in zip(snapshot['records'], notified['records']):
        expected = (*old[:5], 1) if old[0] == snapshot['target'][0] else old
        require(new == expected, 'BINDING_EDIT_NOTIFY_RECORD_DELTA')
    return {'ownerNotificationVerified': True, 'editTransactionClosed': True}


def verify_binding(raw, decoded, *, request, current):
    layout=receipt_layout(receipt_bytes=len(raw))
    n, a, at, b = (decoded[k] for k in ('native', 'action', 'attachment', 'binding'))
    parameters = request['parameters']
    kind = 35 if request['action'] == 'bind-shop' else 33
    require(n['sehCode'] == n['readbackSehCode'] == n['nativeCode'] == n['metadataUsageInProgress'] == 0 and
            n['afterSceneUnchanged'] == 1 and n['metadataCallsStarted'] == n['metadataCallsCompleted'] == METADATA_CALLS and
            n['nativeCallAttempted'] and n['runtimeStateMayHaveChanged'] and
            all(pointer(p) for p in n['classes']), 'BINDING_NATIVE_NOT_COMPLETE')
    require(a['code'] in (0, 1) and a['stage'] == 5 and a['entityId'] == parameters['sceneEntityId'] and
            a['templateId'] == parameters['bagId'] and a['componentId'] > 0 and
            a['reused'] == (a['code'] == 1) and all(a[k] for k in
                ('catalogVerified', 'templateVerified', 'componentVerified', 'postBindingVerified', 'catalogsUnchanged')) and
            not a['needsOwnerNotification'], 'BINDING_ACTION_NOT_COMPLETE')
    require(all(pointer(a[k]) for k in ('owner', 'templateResource', 'wrapper', 'config')), 'BINDING_ACTION_POINTERS')
    ownership = verify_role_owners(raw, decoded, request=request, current=current)
    global_pointer = int(current['pointers']['global'], 16)
    catalogs_raw = [raw[off:off + catalogs.CATALOG_BYTES] for off in (layout["BEFORE_CATALOG_AT"], layout["AFTER_CATALOG_AT"])]
    old_catalog, new_catalog = [catalogs.decode_catalog(data.hex()) for data in catalogs_raw]
    require(old_catalog['levelId'] == new_catalog['levelId'] == request['levelId'] and
            old_catalog['global'] == new_catalog['global'] == global_pointer and
            all(old_catalog[k] == new_catalog[k] for k in ('manager', 'primary', 'companion')),
            'BINDING_CATALOG_CHANGED')
    template = a['templateId']
    require(template & 0xe0000000 == 0x40000000 and (template >> 22) & 127 == (15 if kind == 35 else 11) and
            old_catalog['primary'].get(template) == (template, 17 if kind == 35 else 12,
                a['templateResource'], n['classes'][4 if kind == 35 else 3]), 'BINDING_TEMPLATE_IDENTITY')
    require(at['code'] == (1 if at['attachCalled'] else 0) and at['beforeVerified'] and
            (not at['attachCalled'] or at['afterVerified'] and at['returned'] == a['wrapper']) and
            at['row'][:5] == (a['wrapper'], n['classes'][2], a['config'], n['classes'][1 if kind == 35 else 0], kind),
            'BINDING_ATTACHMENT_RESULT')
    delta = components.verify_component_transition(
        raw[layout["BEFORE_COMPONENTS_AT"]:layout["BEFORE_COMPONENTS_AT"] + components.COMPONENT_BYTES],
        raw[layout["AFTER_ATTACH_AT"]:layout["AFTER_ATTACH_AT"] + components.COMPONENT_BYTES],
        raw[layout["FINAL_COMPONENTS_AT"]:layout["FINAL_COMPONENTS_AT"] + components.COMPONENT_BYTES],
        owner=a['owner'], kind=kind, wrapper_class=n['classes'][2],
        config_class=n['classes'][1 if kind == 35 else 0], wrapper=a['wrapper'], config=a['config'],
        attach_called=at['attachCalled'], allow_target_enable_change=not a['reused'])
    before, after = decoded['observed']
    require(after['templateId'] == template and pointer(after['reference']) and
            after['entry'] == a['entry'] and after['shopIndex'] == a['shopIndex'], 'BINDING_FIELD_READBACK')
    if kind == 35:
        require(after['shopCount'] == 1 and after['shopIndex'] > 0 and pointer(after['entry']), 'BINDING_SHOP_ENTRY')
    else:
        require(after['shopCount'] == after['shopIndex'] == after['entry'] == 0, 'BINDING_BAG_SINGLE_REFERENCE')
    if a['reused']:
        require(before == after and not at['attachCalled'] and not n['componentMutationCalled'] and
                not any(b[k] for k in ('referenceFactoryCalled', 'addCalled', 'setterCalled', 'mutationCalled')) and
                not any(decoded['edit'][k] for k in ('openCalled', 'snapshotCalled', 'notifyCalled', 'closeCalled')),
                'BINDING_REUSE_MUTATED')
        notification = {'ownerNotificationVerified': False, 'editTransactionClosed': False}
    else:
        require(before['templateId'] == before['shopCount'] == 0 and b['code'] == b['stage'] == 0 and
                b['reference'] == after['reference'] and b['entry'] == after['entry'] and b['shopIndex'] == after['shopIndex'] and
                all(b[k] for k in ('referenceFactoryCalled', 'referenceReadbackVerified', 'setterCalled', 'fieldReadbackVerified',
                    'mutationCalled', 'outcomeUncertain')) and n['componentMutationCalled'] and a['outcomeUncertain'] and
                b['addCalled'] == b['entryIndexReadbackVerified'] == (kind == 35) and
                not any(b[k] for k in ('dependencyRefreshCalled', 'needsDependencyRefresh', 'needsOwnerNotification')),
                'BINDING_SETTER_NOT_VERIFIED')
        notification = verify_edit(raw, decoded, module_base=int(current['pointers']['moduleBase'], 16),
                                   global_pointer=global_pointer, kind=kind)
    return dict(delta, **notification, **ownership, bindingVerified=True, reused=a['reused'],
                entityId=a['entityId'], templateId=template, componentId=a['componentId'],
                shopIndex=a['shopIndex'], outcomeUncertain=a['outcomeUncertain'])
def decode_native(record):
    layout=receipt_layout(receipt_bytes=record.get("roleTemplateBagResultBytes"))
    require(record.get('roleTemplateBagResultBytes') == layout["RECEIPT_BYTES"], 'BINDING_RECEIPT_ABI')
    raw = blob(record.get('roleTemplateBagResultHex'), layout["RECEIPT_BYTES"], 'BINDING_RECEIPT')
    decoded = decode_raw(raw)
    native, action, binding, attachment = (decoded[k] for k in ('native', 'action', 'binding', 'attachment'))
    summary = record.get('roleTemplateBagResult')
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
        ('beforeCatalog', layout["BEFORE_CATALOG_AT"], catalogs.CATALOG_BYTES),
        ('afterCatalog', layout["AFTER_CATALOG_AT"], catalogs.CATALOG_BYTES),
        ('beforeComponents', layout["BEFORE_COMPONENTS_AT"], component_receipt.COMPONENT_BYTES),
        ('afterAttachmentComponents', layout["AFTER_ATTACH_AT"], component_receipt.COMPONENT_BYTES),
        ('afterComponents', layout["FINAL_COMPONENTS_AT"], component_receipt.COMPONENT_BYTES),
        ('editResult', layout["EDIT_AT"], EDIT_BYTES),
        ('afterSnapshot', layout["AFTER_AT"], layout["SNAPSHOT_BYTES"]), ('beforeOwner', layout["BEFORE_OWNER_AT"], OWNER_BYTES),
        ('afterOwner', layout["AFTER_OWNER_AT"], OWNER_BYTES), ('finalEditAfter', layout["FINAL_EDIT_AT"], STATE_BYTES)]
    parts += [(name, layout["EDIT_AT"] + offset, STATE_BYTES) for name, offset in
              (('editBefore', 80), ('editAfterSnapshot', 12496), ('editAfterNotify', 24912), ('editAfterClose', 37328))]
    for key, offset, size in parts:
        require(record.get(key + 'Bytes') == size and
                blob(record.get(key + 'Hex'), size, key) == raw[offset:offset + size],
                'BINDING_RAW_DUPLICATE_MISMATCH:' + key)
    return decoded, raw


def validate_run(run):
    envelope = validate_envelope(run)
    run, record = envelope['run'], envelope['record']
    layout=receipt_layout(snapshot_bytes=len(envelope['raw']))
    decoded, raw = decode_native(record)
    require(raw[layout["EXPECTED_AT"]:layout["EXPECTED_AT"] + layout["SNAPSHOT_BYTES"]] == envelope['raw'],
            'BINDING_NATIVE_EXPECTED_BASELINE')
    current = scene(blob(record['snapshotHex'], layout["SNAPSHOT_BYTES"], 'CURRENT_SNAPSHOT'), envelope['profile'], envelope['level'])
    after = scene(blob(record['afterSnapshotHex'], layout["SNAPSHOT_BYTES"], 'AFTER_SNAPSHOT'), envelope['profile'], envelope['level'])
    same_scene(envelope['baseline'], current); same_scene(current, after)
    accepted = verify_binding(raw, decoded, request=envelope['request'], current=current)
    final_state = decode_state(raw[layout["FINAL_EDIT_AT"]:layout["FINAL_EDIT_AT"]+STATE_BYTES], decoded['action']['wrapper'])
    require(final_state['depth'] == final_state['baseDepth'] and final_state['count'] == 0, 'ROLE_FINAL_EDIT_STILL_PENDING')
    if not decoded['action']['reused']:
        closed = decode_state(raw[layout["EDIT_AT"]+37328:layout["EDIT_AT"]+37328+STATE_BYTES], decoded['action']['wrapper'])
        require(all(final_state[key] == closed[key] for key in
                    ('manager', 'list', 'recordClass', 'literal', 'baseDepth', 'depth')),
                'ROLE_FINAL_EDIT_CONTEXT_CHANGED')
    hashes = {name: profiles.sha256(run / name) for name in
              (*envelope['hashes'], 'build-result.json', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used')}
    return dict(accepted, ok=True, state='role-template-bag-readback-only', action=envelope['request']['action'],
        scope='FIXED_ROLE_TEMPLATE_BAG_ACTION', run=str(run), levelId=envelope['level'],
        requestSha256=envelope['prepared']['requestSha256'], reviewSha256=envelope['prepared']['reviewSha256'],
        persistentSaveVerified=False, gameplayVerified=False, inputHashes=hashes,
        acceptorSha256=profiles.sha256(Path(__file__)),
        decoderHashes={p.name: profiles.sha256(p) for p in
                      (Path(binding_raw.__file__), Path(component_receipt.__file__), Path(catalogs.__file__))},
        limits='Raw native binding and edit transaction only. Root4 role-template binding only. Save/reopen, runtime inventory and purchasing require separate acceptance.')


def accept_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()) and run.is_dir(), 'DEDICATED_BINDING_RUN_REQUIRED')
    output = run / 'role-template-bag-acceptance.json'
    require(not output.exists(), 'BINDING_ACCEPTANCE_ALREADY_EXISTS')
    try:
        result = validate_run(run)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        result = dict(ok=False, state='refused', error=str(error), run=str(run), bindingVerified=False,
                      persistentSaveVerified=False, gameplayVerified=False, outcomeUncertain=None)
        # Retain attempted operations even when readback or envelope acceptance
        # fails. This is reported evidence and never permission to retry/close.
        try:
            reported, reported_raw = decode_native(read_record(run / 'stdout.jsonl'))
            result.update(outcomeUncertain=reported['action']['outcomeUncertain'],
                reportedComponentMutationCalled=reported['native']['componentMutationCalled'],
                reportedTransactionMayBeOpen=reported['edit']['transactionMayBeOpen'])
            result['reportedFinalEdit'] = values(reported_raw, receipt_layout(receipt_bytes=len(reported_raw))['FINAL_EDIT_AT'], '<4I2i',
                'code count version targetCount baseDepth depth')
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
