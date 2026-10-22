"""Offline acceptance of a dedicated item action receipt; never execute or save.

Raw ABI confirmed with MSVC sizeof/offsetof in task-ay/layout.json. Transport,
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

import build_item_candidate as candidate
import receipt as catalogs
import item_review as reviews
import snapshot_abi as abi

requests, profiles, readonly = candidate.requests, candidate.profiles, candidate.readonly
PREPARED_ROOT = candidate.ROOT / '.runtime/template-authoring/prepared-item'
MAX_STDOUT_BYTES = 8 * 1024 * 1024
SNAPSHOT_BYTES = abi.DEFAULT_BYTES            # v1 别名（既有调用点语义不变）
# Actual ItemActionResult: nested caller-owned ItemResult is 16 bytes at +8.
ACTION = struct.Struct('<2I3I4B2I2q2I4Q9B7x')
#: **收据协议版本**：`item_native_adapter.cpp:93` 逐字 —— `std::memset(out,0,sizeof(*out)); out->size = sizeof(*out); out->version = 1;`
#: ⇒ 它是**另一个字段**，与嵌入的 `GameContextSnapshot.version` 无关，**恒为 1**（currency accept 的 `version==1` 与 kind17 收据同理）。
#: v1/v2 的区分走**嵌入快照的载荷自述头**（见 decode_native 末尾的 `validate_snapshot_payload`），**不靠**收据 version。
RECEIPT_PROTOCOL_VERSION = 1
# 2026-10-17 双 ABI（对象①口径）：收据布局**不再写死** —— 偏移与总长按快照尺寸推导。
# v1 的推导值由下面的断言钉回历史常量：v1 行为一个字节都不许变。
#: ``sizeof(TemplateCatalogCaptureWorkspace)``（``template_catalog_capture.h:48-58``）与快照 ABI 无关
#: （目录行数固定 4096）；口径与 ``accept_currency.py:30-33`` 同源。
CAPTURE_BYTES = 2 * (0x48 + catalogs.MAX_ROWS * (4 + 24 + 1)) + 65536
_LAYOUT_V1 = abi.receipt_layout(SNAPSHOT_BYTES, action_bytes=ACTION.size,
                                catalog_bytes=catalogs.CATALOG_BYTES, capture_bytes=CAPTURE_BYTES)
RECEIPT_BYTES = _LAYOUT_V1['receiptBytes']
ACTION_AT, EXPECTED_AT, AFTER_AT = (_LAYOUT_V1['actionOffset'], _LAYOUT_V1['expectedSnapshotOffset'],
                                    _LAYOUT_V1['afterSnapshotOffset'])
BEFORE_CATALOG_AT, AFTER_CATALOG_AT = _LAYOUT_V1['beforeCatalogOffset'], _LAYOUT_V1['afterCatalogOffset']
assert ACTION.size == 104 and AFTER_CATALOG_AT + catalogs.CATALOG_BYTES == RECEIPT_BYTES
assert (CAPTURE_BYTES, RECEIPT_BYTES) == (303248, 894392) and \
    (ACTION_AT, EXPECTED_AT, AFTER_AT) == (16, 120, 33328) and \
    (BEFORE_CATALOG_AT, AFTER_CATALOG_AT) == (369784, 632088), 'ITEM_V1_LAYOUT_CHANGED'


def _abi_from_receipt(receipt_bytes):
    """由**收据长度**反解快照尺寸，并返回该 ABI 的布局。

    只用 ``abi.SIZES`` + ``abi.receipt_layout``（不依赖额外的关键字签名），
    因此与 ``accept_currency.py`` 的推导走**同一真源**；不认识的长度 ⇒ ``ITEM_RECEIPT_ABI``。
    """
    for candidate in abi.SIZES:
        layout = abi.receipt_layout(candidate, action_bytes=ACTION.size,
                                    catalog_bytes=catalogs.CATALOG_BYTES, capture_bytes=CAPTURE_BYTES)
        if layout['receiptBytes'] == receipt_bytes:
            return candidate, layout
    raise ValueError('ITEM_RECEIPT_ABI')


ITEM_BOOL_FIELDS = ('defaultGetterCalled', 'itemAllocationCalled', 'handlerCalled', 'itemOutcomeUncertain')
OUTER_BOOL_FIELDS = ('metadataInitializationCalled', 'countCalled', 'limitInitializationCalled',
                    'controllerLookupCalled', 'allocationCalled', 'createCalled',
                    'mainCatalogVerified', 'companionCatalogVerified', 'outcomeUncertain')
BOOL_FIELDS = ITEM_BOOL_FIELDS + OUTER_BOOL_FIELDS


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
    require(len(raw) <= MAX_STDOUT_BYTES, 'ITEM_STDOUT_LIMIT')
    # The dedicated launcher copies raw native stdout bytes, with no UTF-16 redirect.
    text = raw.decode('utf-8-sig', errors='strict')
    records = [json.loads(line, object_pairs_hook=requests._unique_object)
               for line in text.splitlines() if line.strip()]
    require(len(records) == 1 and type(records[0]) is dict, 'EXACTLY_ONE_ITEM_RECEIPT_REQUIRED')
    return records[0]


def decode_native(record):
    # 双 ABI：先由**收据长度**反解快照尺寸（与记录自述 `*Bytes` 两个独立观测互校后才切片）。
    snapshot_size, layout = _abi_from_receipt(record.get('itemResultBytes'))
    receipt_bytes = layout['receiptBytes']
    require(record.get('itemResultBytes') == receipt_bytes, 'ITEM_RECEIPT_ABI')
    raw = blob(record.get('itemResultHex'), receipt_bytes, 'ITEM_RECEIPT')
    size, version, seh, unchanged = struct.unpack_from('<4I', raw)
    # 收据协议 version **恒为 1**（`item_native_adapter.cpp:93`）——它不是嵌入快照的版本；
    # 嵌入的 GameContextSnapshot 的 v1/v2 由末尾的 validate_snapshot_payload 严格校验。
    require(size == receipt_bytes and version == RECEIPT_PROTOCOL_VERSION, 'ITEM_RECEIPT_VERSION')
    values = ACTION.unpack_from(raw, ACTION_AT)
    names = ('code', 'stage', 'itemCode', 'itemStage', 'defaultValue', *ITEM_BOOL_FIELDS,
             'mainDeltaCode', 'nameCode', 'count', 'limit', 'createdId', 'companionOwnId',
             'createdResource', 'companionResource', 'observedMainClass', 'observedCompanionClass',
             *OUTER_BOOL_FIELDS)
    action = dict(zip(names, values))
    for name in BOOL_FIELDS:
        require(action[name] in (0, 1), 'ITEM_BOOL_ENCODING:' + name)
        action[name] = bool(action[name])
    action.update(size=size, version=version, sehCode=seh, afterSceneUnchanged=unchanged)
    summary = record.get('itemResult')
    require(type(summary) is dict, 'ITEM_RESULT_SUMMARY_REQUIRED')
    for key, value in action.items():
        if key in ('defaultValue', 'itemAllocationCalled', 'itemOutcomeUncertain', 'nameCode'):
            # These exist only in raw caller-owned storage; never infer them
            # from the outer summary's similarly named fields.
            continue
        if key in ('observedMainClass', 'observedCompanionClass'):
            supplied = record.get(key)
        else:
            supplied = summary.get(key)
        if key in ('createdResource', 'companionResource', 'observedMainClass', 'observedCompanionClass'):
            require(type(supplied) is str and re.fullmatch('0x[0-9a-fA-F]+', supplied) is not None,
                    'ITEM_POINTER_SUMMARY:' + key)
            supplied = int(supplied, 16)
        require(type(supplied) is type(value) and supplied == value, 'ITEM_RAW_SUMMARY_MISMATCH:' + key)
    for key, offset, size in (('beforeCatalog', layout['beforeCatalogOffset'], catalogs.CATALOG_BYTES),
                             ('afterCatalog', layout['afterCatalogOffset'], catalogs.CATALOG_BYTES),
                             ('afterSnapshot', layout['afterSnapshotOffset'], snapshot_size)):
        require(record.get(key + 'Bytes') == size and
                blob(record.get(key + 'Hex'), size, key) == raw[offset:offset + size],
                'ITEM_RAW_DUPLICATE_MISMATCH:' + key)
    expected = raw[layout['expectedSnapshotOffset']:layout['expectedSnapshotOffset'] + snapshot_size]
    # 交叉验证：期望快照的**载荷自述头**（长度/版本）必须与由收据长度反解出的 ABI 一致。
    # 这是第三个独立观测（收据长度 ↔ 记录自述 *Bytes ↔ 载荷自述头），不放宽任何重复字段校验。
    abi.validate_snapshot_payload(expected, 'ITEM_EXPECTED_SNAPSHOT_PAYLOAD_ABI')
    return action, expected


def runtime_profiles(review, inputs, header):
    """Bind both direct AP calls and the AM creation service inherited by the handler."""
    runtime_path = requests.runtime_path(review['runtimeProfilePath'])
    transitive = review['transitiveCurrencyProfile']
    requests.exact_fields(transitive, {'path', 'sha256'}, 'transitive-currency-profile')
    service_path = requests.runtime_path(transitive['path'])
    require(service_path == requests.runtime_path(candidate.DEFAULT_SERVICE_PROFILE), 'ITEM_SERVICE_PROFILE_PATH')
    require(profiles.sha256(runtime_path) == review['runtimeProfileSha256'] and
            profiles.sha256(service_path) == transitive['sha256'], 'ITEM_RUNTIME_OR_SERVICE_PROFILE_CHANGED')
    require(inputs.get('runtimeProfilePath') == str(runtime_path) and
            inputs.get('runtimeProfileSha256') == review['runtimeProfileSha256'] and
            inputs.get('serviceProfilePath') == str(service_path) and
            inputs.get('serviceProfileSha256') == transitive['sha256'], 'ITEM_TRANSITIVE_PROFILE_BINDING')
    runtime, service = requests.read_json(runtime_path), requests.read_json(service_path)
    require(runtime['imageSha256'] == service['imageSha256'] == profiles.load_profile()['image']['sha256'] and
            runtime['metadataSha256'] == service['metadataSha256'], 'ITEM_PROFILE_BUILD_MISMATCH')
    require(tuple(int(f['rva'], 16) for f in runtime['functions']) == candidate.ITEM_FUNCTIONS and
            tuple(int(g['flagRva'], 16) for g in runtime['hotfixGuards']) == candidate.HOTFIX[:-1],
            'ITEM_PROFILE_FUNCTIONS_OR_HOTFIX')
    create = [f for f in service['functions'] if int(f['rva'], 16) == 0xb0a90c0]
    require(len(create) == 1 and any(int(g['flagRva'], 16) == candidate.HOTFIX[-1]
                                  for g in service['hotfixGates']), 'ITEM_SERVICE_CREATION_EVIDENCE')
    functions = runtime['functions'] + create
    expected = {'TA_ITEM_ANCHOR_RVAS': ','.join(hex(rva) for rva in candidate.FUNCTIONS),
        'TA_ITEM_ANCHOR_BYTES': ','.join('{' + ','.join(hex(b) for b in bytes.fromhex(f['head32'])) + '}' for f in functions),
        'TA_ITEM_HOTFIX_RVAS': ','.join(hex(rva) for rva in candidate.HOTFIX)}
    require(all(len(bytes.fromhex(f['head32'])) == 32 for f in functions), 'ITEM_PROFILE_ANCHOR_LENGTH')
    text = header.read_text(encoding='utf-8')
    for key, value in expected.items():
        found = re.findall(r'^#define ' + key + r' (.+)$', text, re.M)
        require(found == [value], 'ITEM_COMPILED_PROFILE:' + key)


def scene(raw, profile, level):
    decoder = readonly.load_decoder()
    value = decoder.decode_snapshot({'snapshotHex': raw.hex(), 'snapshotBytes': len(raw)})
    counts, flags = value['counts'], value['flags']['value']
    require(value['status']['value'] == 0 and flags & 1951 == 1951 and not flags & 96,
            'ITEM_SCENE_INCOMPLETE')
    require(counts['peTimestamp'] == profile['image']['timestamp'] and
            counts['peImageSize'] == profile['image']['sizeOfImage'], 'ITEM_SCENE_BUILD')
    require(value['levelObservation']['verified'] and value['levelObservation']['levelId'] == level,
            'ITEM_SCENE_LEVEL')
    require(counts['activeKey'] == 0 and counts['contextMatchingEntries'] == 1 and
            counts['entityRejected'] == 0 and 0 < counts['entityCaptured'] == counts['entityValidEntries'] == len(value['entities']) and
            counts['entityVersionBefore'] == counts['entityVersionAfter'], 'ITEM_SCENE_COUNTS')
    require(set(profile['callbackStackRvas']) <= {f['rva'] for f in value['stack'] if f['inMainModule']},
            'ITEM_CALLBACK_STACK')
    rows = value['entities']
    require(len({row['id'] for row in rows}) == len(rows) and
            all(type(row['id']) is int and row['id'] > 0 and row['flags']['value'] & 79 == 79 and
                row['dictionaryKey'] == row['id'] and row['context'] == value['pointers']['currentContext']
                for row in rows), 'ITEM_SCENE_ENTITY_IDENTITY')
    return value


def same_scene(first, second):
    require(first['pointers'] == second['pointers'] and first['entities'] == second['entities'] and
            first['origin'] == second['origin'] and
            all(first['counts'][key] == second['counts'][key] for key in
                ('activeKey', 'contextCapacity', 'contextValidEntries', 'contextMatchingEntries',
                 'entityCapacity', 'entityValidEntries', 'entityCaptured', 'entityRejected',
                 'entityVersionBefore', 'entityVersionAfter')), 'ITEM_SCENE_CHANGED')


def date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'ITEM_TIMEZONE_REQUIRED')
    return parsed


def header_binding(path, prepared, raw):
    text = path.read_text(encoding='utf-8')
    session = prepared['session']
    expected = {'HR_ACTION': 6, 'TA_ITEM_REVIEWED': 1, 'GS_REVIEWED_ACTION_PROFILE': 1,
        'GS_BOOTSTRAP_READONLY': 0, 'HR_TARGET_PID': session['pid'], 'HR_TARGET_TID': session['tid'],
        'HR_TARGET_CREATION': session['processCreation'], 'HR_TARGET_THREAD_CREATION': session['threadCreation'],
        'HR_NONCE': prepared['nonce'], 'HR_DEADLINE': prepared['deadline'], 'HR_MESSAGE_ID': prepared['messageId']}
    for name, value in expected.items():
        found = re.findall(r'^#define ' + name + r' ([0-9]+)(?:ULL)?$', text, re.M)
        require(len(found) == 1 and int(found[0]) == value, 'ITEM_COMPILED_IDENTITY:' + name)
    image = re.findall(r'^#define HR_TARGET_IMAGE L(.+)$', text, re.M)
    require(len(image) == 1 and json.loads(image[0]) == session['image'], 'ITEM_COMPILED_IMAGE')
    baseline = re.findall(r'inline constexpr unsigned char kTemplateExpectedSnapshot\[\] = \{\n([0-9,\n]+)\n\};', text)
    require(len(baseline) == 1 and bytes(int(v) for v in baseline[0].replace('\n', '').split(',') if v) == raw,
            'ITEM_COMPILED_BASELINE')


def validate_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()), 'DEDICATED_ITEM_RUN_REQUIRED')
    prepared, built, contract = (requests.read_json(run / name) for name in
                                 ('prepared.json', 'build-result.json', 'build-contract.json'))
    for value, kind in ((prepared, 'template-item-prepared-v1'), (built, 'template-item-build-v1'),
                        (contract, 'template-item-build-contract-v1')):
        require(value.get('kind') == kind and value.get('schemaVersion') == 1 and
                value.get('action') == 'create-item' and value.get('actionCode') == 6 and
                value.get('compileOnly') is False and value.get('reviewed') is True and
                value.get('allowWrites') is True, 'DEDICATED_ITEM_BUILD_CONTRACT')
    require(prepared.get('launchable') is True and built.get('launchable') is True and
            contract.get('launchable') is False and prepared.get('compiled') is True and built.get('compiled') is True and
            built.get('ok') is True and prepared.get('receiptVersion') == contract.get('receiptVersion') == 10 and
            built.get('run') == str(run), 'ITEM_LAUNCHABLE_BUILD_REQUIRED')
    require(prepared.get('wrapperName') == built.get('wrapperName') == 'invoke-item-probe.ps1', 'ITEM_WRAPPER')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'ITEM_PREPARED_CONTRACT_MISMATCH:' + key)
    for key in ('requestSha256', 'reviewSha256', 'nonce', 'deadline'):
        require(built.get(key) == prepared.get(key), 'ITEM_BUILD_BINDING:' + key)
    hashes = built.get('hashes')
    required = {'prepared.json', 'build-contract.json', 'target_config.h', 'baseline-snapshot.bin',
                'request.json', 'review.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-item-probe.ps1'}
    required.update('candidate-source/native/' + name for name in candidate.NATIVE_FILES)
    required.update('candidate-source/template-authoring/' + name for name in candidate.TEMPLATE_FILES)
    require(type(hashes) is dict and required <= set(hashes), 'ITEM_ARTIFACT_HASH_SET')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
                'ITEM_ARTIFACT_CHANGED:' + name)
    review, request = requests.read_json(run / 'review.json'), requests.validate_request(requests.read_json(run / 'request.json'))
    requests.exact_fields(review, reviews.FIELDS, 'item-review')
    require(review['state'] == 'reviewed' and review['kind'] == 'template-item-review-v1' and
            review['reviewedBy'] == 'coordinator' and review['action'] == request['action'] == 'create-item',
            'ITEM_REVIEW_REQUIRED')
    require(profiles.sha256(run / 'request.json') == review['requestSha256'] == prepared['requestSha256'] and
            (run / 'request.json').read_bytes() == requests.canonical_bytes(request) and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'], 'ITEM_REVIEW_REQUEST_HASH')
    require(review['sourceHashes'] == prepared['sourceHashes'] == reviews.source_hashes(), 'ITEM_SOURCE_CHANGED')
    profile = profiles.load_profile()
    require(review['readonlyProfileSha256'] == profiles.PROFILE_SHA256 and
            prepared['disk'].get('sha256') == profile['image']['sha256'], 'ITEM_CURRENT_PROFILE_REQUIRED')
    runtime_profiles(review, prepared['inputs'], run / 'target_config.h')
    session = prepared['session']
    require({key: session.get(key) for key in requests.SESSION_FIELDS} == review['session'] == request['session'] and
            all(type(session.get(key)) is int and session[key] > 1 for key in ('pid', 'tid', 'window', 'processCreation', 'threadCreation')) and
            session['windowClass'] == 'UnityWndClass' and
            Path(session['image']).resolve() == profiles.TARGET_IMAGE.resolve(), 'ITEM_REAL_SESSION_REQUIRED')
    level = request['levelId']
    require(level == review['levelId'] == prepared['levelId'] and
            review['reviewId'] == prepared['reviewId'] and prepared['ttlSeconds'] in (180, 600) and
            review['expiresUtc'] == prepared['reviewExpiresUtc'], 'ITEM_REQUEST_IDENTITY')
    baseline_run = requests.runtime_path(review['baselineRun'])
    require(baseline_run.name == request['runId'] and review['baselineKind'] == 'readonly' and
            review['evidenceHashes'] == requests._baseline_hashes(baseline_run, 'readonly'), 'ITEM_BASELINE_CHANGED')
    # This is the original readonly baseline, never a relabelled action receipt.
    baseline, baseline_prepared = requests.review_api.load_baseline(baseline_run, 'readonly', level)
    require(all(baseline_prepared['session'].get(k) == session[k] for k in requests.SESSION_FIELDS), 'ITEM_BASELINE_SESSION')
    raw = (run / 'baseline-snapshot.bin').read_bytes()
    old_record, _ = readonly.load_decoder().read_probe(baseline_run / 'stdout.jsonl')
    require(raw == bytes.fromhex(old_record['snapshotHex']), 'ITEM_BASELINE_RAW_CHANGED')
    header_binding(run / 'target_config.h', prepared, raw)
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('requestSha256') == prepared['requestSha256'] and
            claim.get('run') == str(run) and claim.get('claim') == 'single-item-compilation-no-auto-retry', 'ITEM_REVIEW_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'ITEM_ATTEMPT_REQUIRED:' + name)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] == 0 and
            not exit_record.get('error') and exit_record.get('scope') == 'FIXED_TEMPLATE_ITEM_ACTION', 'ITEM_NATIVE_EXIT')
    require(date(review['reviewedAtUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']) and
            0 < (date(review['expiresUtc']) - date(review['reviewedAtUtc'])).total_seconds() <= 3600,
            'ITEM_EXECUTION_OUTSIDE_REVIEW')
    record = read_record(run / 'stdout.jsonl')
    # 2026-10-17 双 ABI：v1=33208 B（512 实体）/ v2=262584 B（4096 实体）。
    # 蒙德关卡 1613 实体 ⇒ 必须 v2。**保留 v1 兼容**，只在原入口新增 v2；默认常量不变。
    snapshot_size = abi.validate_snapshot_size(record.get('snapshotBytes'), 'ITEM_NATIVE_TRANSPORT')
    require(record.get('scope') == 'FIXED_TEMPLATE_ITEM_ACTION' and record.get('selfTestOnly') is False and
            record.get('ok') is True and record.get('probeElevatedHigh') is True and record.get('transportOk') is True and
            record.get('pid') == session['pid'] and record.get('tid') == session['tid'] and
            record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
            record.get('hostPostUnhookPings') == 0 and record.get('snapshotStatus') == 0 and
            record.get('snapshotBytes') == snapshot_size, 'ITEM_NATIVE_TRANSPORT')
    action, expected = decode_native(record)
    require(expected == raw, 'ITEM_NATIVE_EXPECTED_BASELINE')
    require(action['sehCode'] == 0 and action['afterSceneUnchanged'] == 1 and action['code'] == 0 and
            action['stage'] == 6 and action['itemStage'] == 0 and action['itemCode'] == action['nameCode'] == action['mainDeltaCode'] == 0 and
            0 <= action['count'] < action['limit'] <= 0xffffffff and
            all(action[name] for name in OUTER_BOOL_FIELDS) and action['defaultGetterCalled'] and
            action['handlerCalled'] and action['itemOutcomeUncertain'] and not action['itemAllocationCalled'],
            'ITEM_NATIVE_RESULT_NOT_VERIFIED')
    current = scene(blob(record['snapshotHex'], snapshot_size, 'CURRENT_SNAPSHOT'), profile, level)
    after = scene(blob(record['afterSnapshotHex'], snapshot_size, 'AFTER_SNAPSHOT'), profile, level)
    same_scene(baseline, current); same_scene(current, after)
    before_catalog = catalogs.decode_catalog(record['beforeCatalogHex'])
    require(before_catalog['global'] == int(current['pointers']['global'], 16), 'ITEM_CATALOG_GLOBAL')
    delta = catalogs.verify_item_delta(record['beforeCatalogHex'], record['afterCatalogHex'],
        level_id=level, expected_class=action['observedMainClass'], expected_companion_class=action['observedCompanionClass'])
    after_catalog = catalogs.decode_catalog(record['afterCatalogHex'])
    require(action['createdId'] == delta['createdId'] and action['companionOwnId'] == delta['companionOwnId'], 'ITEM_CREATED_ID_MISMATCH')
    require(after_catalog['primary'][delta['createdId']][2] == action['createdResource'] and
            after_catalog['companion'][delta['createdId']][6] == action['companionResource'], 'ITEM_CREATED_RESOURCE_MISMATCH')
    input_hashes = {name: profiles.sha256(run / name) for name in
                   (*hashes, 'build-result.json', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used')}
    return {'ok': True, 'state': 'catalog-registered-only', 'action': 'create-item',
        'scope': 'FIXED_TEMPLATE_ITEM_ACTION', 'run': str(run), 'levelId': level,
        'requestSha256': prepared['requestSha256'], 'reviewSha256': prepared['reviewSha256'],
        'catalogRegisteredVerified': True, 'createdId': delta['createdId'],
        'companionOwnId': delta['companionOwnId'], 'createdResource': hex(action['createdResource']),
        'companionResource': hex(action['companionResource']), 'observedMainClass': hex(action['observedMainClass']),
        'observedCompanionClass': hex(action['observedCompanionClass']), 'handlerCalled': action['handlerCalled'],
        'itemStage': action['itemStage'],
        'outcomeUncertain': action['outcomeUncertain'], 'persistentSaveVerified': False,
        'nameVerified': False, 'defaultsVerified': False, 'gameplayVerified': False,
        'inputHashes': input_hashes, 'acceptorSha256': profiles.sha256(Path(__file__)),
        'limits': 'Native transport and independent raw registration delta only. No name/default/export/save/gameplay acceptance.'}


def accept_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()) and run.is_dir(), 'DEDICATED_ITEM_RUN_REQUIRED')
    output = run / 'item-acceptance.json'
    require(not output.exists(), 'ITEM_ACCEPTANCE_ALREADY_EXISTS')
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
            result['outcomeUncertain'] = reported['outcomeUncertain'] or reported['itemOutcomeUncertain'] or reported['handlerCalled']
            result['reportedCreateCalled'] = reported['createCalled']
            result['reportedHandlerCalled'] = reported['handlerCalled']
            result['reportedDefaultGetterCalled'] = reported['defaultGetterCalled']
            result['reportedAllocationCalled'] = reported['allocationCalled']
            result['reportedItemStage'] = reported['itemStage']
            result['reportedActionStage'] = reported['stage']
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
