"""Offline acceptance of a dedicated currency action receipt; never execute or save.

Raw ABI confirmed with MSVC sizeof/offsetof in task-au/layout.json. Transport,
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

import build_candidate as candidate
import receipt as catalogs
import template_review as reviews
import snapshot_abi as abi

requests, profiles, readonly = candidate.requests, candidate.profiles, candidate.readonly
PREPARED_ROOT = candidate.ROOT / '.runtime/template-authoring/prepared-currency'
MAX_STDOUT_BYTES = 8 * 1024 * 1024
ACTION = struct.Struct('<4I2q2QI7B5x')
assert ACTION.size == 64
# 2026-10-17 双 ABI（对象①：原入口双 ABI 整链）：v1=33208 B（512 实体）/ v2=262584 B（4096 实体）。
# 收据布局**不再写死**：全部偏移与总长由 snapshot_abi.receipt_layout() 按快照尺寸推导。
# 下面的断言把 v1 的推导值钉回历史常量 —— v1 行为一个字节都不许变。
SNAPSHOT_BYTES = abi.DEFAULT_BYTES            # v1 别名（既有调用点/文档的语义不变）
#: ``sizeof(TemplateCatalogCaptureWorkspace)``（``template_catalog_capture.h:48-58``）：
#: ``TemplateDictionaryWorkspace`` = 0x48 + 4096*4(buckets) + 4096*24(entries) + 4096*1(seen) = 118856；
#: workspace = 2*118856 + 65536(compare) = 303248。它与快照 ABI 无关（目录行数固定 4096）。
CAPTURE_BYTES = 2 * (0x48 + catalogs.MAX_ROWS * (4 + 24 + 1)) + 65536
_LAYOUT_V1 = abi.receipt_layout(SNAPSHOT_BYTES, action_bytes=ACTION.size,
                                catalog_bytes=catalogs.CATALOG_BYTES, capture_bytes=CAPTURE_BYTES)
RECEIPT_BYTES = _LAYOUT_V1['receiptBytes']
ACTION_AT, EXPECTED_AT, AFTER_AT = (_LAYOUT_V1['actionOffset'], _LAYOUT_V1['expectedSnapshotOffset'],
                                    _LAYOUT_V1['afterSnapshotOffset'])
BEFORE_CATALOG_AT, AFTER_CATALOG_AT = _LAYOUT_V1['beforeCatalogOffset'], _LAYOUT_V1['afterCatalogOffset']
assert (CAPTURE_BYTES, RECEIPT_BYTES) == (303248, 894352) and \
    (ACTION_AT, EXPECTED_AT, AFTER_AT) == (16, 80, 33288) and \
    (BEFORE_CATALOG_AT, AFTER_CATALOG_AT) == (369744, 632048), 'CURRENCY_V1_LAYOUT_CHANGED'
BOOL_FIELDS = ('groupLookupCalled', 'limitInitializationCalled', 'allocationCalled', 'createCalled',
               'mainCatalogVerified', 'companionCatalogUnchanged', 'outcomeUncertain')


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
    require(len(raw) <= MAX_STDOUT_BYTES, 'CURRENCY_STDOUT_LIMIT')
    # The dedicated launcher copies raw native stdout bytes, with no UTF-16 redirect.
    text = raw.decode('utf-8-sig', errors='strict')
    records = [json.loads(line, object_pairs_hook=requests._unique_object)
               for line in text.splitlines() if line.strip()]
    require(len(records) == 1 and type(records[0]) is dict, 'EXACTLY_ONE_CURRENCY_RECEIPT_REQUIRED')
    return records[0]


def receipt_layout(snapshot_size):
    """该快照尺寸对应的收据布局（v1 时逐值等于历史常量；v2 时偏移整体右移）。"""
    return abi.receipt_layout(snapshot_size, action_bytes=ACTION.size,
                              catalog_bytes=catalogs.CATALOG_BYTES, capture_bytes=CAPTURE_BYTES)


def decode_native(record):
    # 两个**互相独立**的观测必须先一致：①收据长度反解出的快照尺寸 ②记录声明的 afterSnapshotBytes。
    # 任一不认识（bool/字符串/非受审尺寸）都在这里具名拒绝，绝不截断或补齐。
    snapshot_size = abi.snapshot_size_for_receipt(
        record.get('templateResultBytes'), action_bytes=ACTION.size,
        catalog_bytes=catalogs.CATALOG_BYTES, capture_bytes=CAPTURE_BYTES, code='CURRENCY_RECEIPT_ABI')
    layout = receipt_layout(snapshot_size)
    # 声明的快照尺寸走 snapshot_abi 的**不做类型强转**校验（True/"33208" 一律具名拒绝）。
    declared_snapshot = abi.validate_snapshot_size(record.get('afterSnapshotBytes'), 'CURRENCY_SNAPSHOT_ABI')
    require(declared_snapshot == snapshot_size, 'CURRENCY_SNAPSHOT_ABI')
    require(record.get('templateResultBytes') == layout['receiptBytes'], 'CURRENCY_RECEIPT_ABI')
    raw = blob(record.get('templateResultHex'), layout['receiptBytes'], 'CURRENCY_RECEIPT')
    size, version, seh, unchanged = struct.unpack_from('<4I', raw)
    require(size == layout['receiptBytes'] and version == 1, 'CURRENCY_RECEIPT_VERSION')
    values = ACTION.unpack_from(raw, layout['actionOffset'])
    names = ('code', 'stage', 'callCode', 'mainDeltaCode', 'count', 'limit',
             'returnedResource', 'observedCurrencyClass', 'createdId', *BOOL_FIELDS)
    action = dict(zip(names, values))
    for name in BOOL_FIELDS:
        require(action[name] in (0, 1), 'CURRENCY_BOOL_ENCODING:' + name)
        action[name] = bool(action[name])
    action.update(size=size, version=version, sehCode=seh, afterSceneUnchanged=unchanged)
    summary = record.get('templateResult')
    require(type(summary) is dict, 'CURRENCY_RESULT_SUMMARY_REQUIRED')
    for key, value in action.items():
        if key == 'observedCurrencyClass':
            supplied = record.get(key)
        else:
            supplied = summary.get(key)
        if key in ('returnedResource', 'observedCurrencyClass'):
            require(type(supplied) is str and re.fullmatch('0x[0-9a-fA-F]+', supplied) is not None,
                    'CURRENCY_POINTER_SUMMARY:' + key)
            supplied = int(supplied, 16)
        require(type(supplied) is type(value) and supplied == value, 'CURRENCY_RAW_SUMMARY_MISMATCH:' + key)
    for key, offset, size in (('beforeCatalog', layout['beforeCatalogOffset'], catalogs.CATALOG_BYTES),
                             ('afterCatalog', layout['afterCatalogOffset'], catalogs.CATALOG_BYTES),
                             ('afterSnapshot', layout['afterSnapshotOffset'], snapshot_size)):
        require(record.get(key + 'Bytes') == size and
                blob(record.get(key + 'Hex'), size, key) == raw[offset:offset + size],
                'CURRENCY_RAW_DUPLICATE_MISMATCH:' + key)
    expected = raw[layout['expectedSnapshotOffset']:layout['expectedSnapshotOffset'] + snapshot_size]
    # 快照**自述** ABI 也要对得上（尺寸/头部 structSize/version 三者一致），否则具名拒绝。
    abi.validate_snapshot_payload(expected, 'CURRENCY_EXPECTED_SNAPSHOT_ABI')
    return action, expected


def scene(raw, profile, level):
    decoder = readonly.load_decoder()
    value = decoder.decode_snapshot({'snapshotHex': raw.hex(), 'snapshotBytes': len(raw)})
    counts, flags = value['counts'], value['flags']['value']
    require(value['status']['value'] == 0 and flags & 1951 == 1951 and not flags & 96,
            'CURRENCY_SCENE_INCOMPLETE')
    require(counts['peTimestamp'] == profile['image']['timestamp'] and
            counts['peImageSize'] == profile['image']['sizeOfImage'], 'CURRENCY_SCENE_BUILD')
    require(value['levelObservation']['verified'] and value['levelObservation']['levelId'] == level,
            'CURRENCY_SCENE_LEVEL')
    require(counts['activeKey'] == 0 and counts['contextMatchingEntries'] == 1 and
            counts['entityRejected'] == 0 and 0 < counts['entityCaptured'] == counts['entityValidEntries'] == len(value['entities']) and
            counts['entityVersionBefore'] == counts['entityVersionAfter'], 'CURRENCY_SCENE_COUNTS')
    require(set(profile['callbackStackRvas']) <= {f['rva'] for f in value['stack'] if f['inMainModule']},
            'CURRENCY_CALLBACK_STACK')
    rows = value['entities']
    require(len({row['id'] for row in rows}) == len(rows) and
            all(type(row['id']) is int and row['id'] > 0 and row['flags']['value'] & 79 == 79 and
                row['dictionaryKey'] == row['id'] and row['context'] == value['pointers']['currentContext']
                for row in rows), 'CURRENCY_SCENE_ENTITY_IDENTITY')
    return value


def same_scene(first, second):
    require(first['pointers'] == second['pointers'] and first['entities'] == second['entities'] and
            first['origin'] == second['origin'] and
            all(first['counts'][key] == second['counts'][key] for key in
                ('activeKey', 'contextCapacity', 'contextValidEntries', 'contextMatchingEntries',
                 'entityCapacity', 'entityValidEntries', 'entityCaptured', 'entityRejected',
                 'entityVersionBefore', 'entityVersionAfter')), 'CURRENCY_SCENE_CHANGED')


def date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'CURRENCY_TIMEZONE_REQUIRED')
    return parsed


def header_binding(path, prepared, raw):
    text = path.read_text(encoding='utf-8')
    session = prepared['session']
    expected = {'HR_ACTION': 5, 'TA_CURRENCY_REVIEWED': 1, 'GS_REVIEWED_ACTION_PROFILE': 1,
        'GS_BOOTSTRAP_READONLY': 0, 'HR_TARGET_PID': session['pid'], 'HR_TARGET_TID': session['tid'],
        'HR_TARGET_CREATION': session['processCreation'], 'HR_TARGET_THREAD_CREATION': session['threadCreation'],
        'HR_NONCE': prepared['nonce'], 'HR_DEADLINE': prepared['deadline'], 'HR_MESSAGE_ID': prepared['messageId']}
    for name, value in expected.items():
        found = re.findall(r'^#define ' + name + r' ([0-9]+)(?:ULL)?$', text, re.M)
        require(len(found) == 1 and int(found[0]) == value, 'CURRENCY_COMPILED_IDENTITY:' + name)
    image = re.findall(r'^#define HR_TARGET_IMAGE L(.+)$', text, re.M)
    require(len(image) == 1 and json.loads(image[0]) == session['image'], 'CURRENCY_COMPILED_IMAGE')
    # 编译期 ABI 开关必须与本次基线的 ABI 一致：v2 必须显式 GS_LARGE_SCENE=1，
    # v1 必须**没有**这个开关（或为 0）—— 共享头文件的默认值仍是 0 = v1，逐 run 副本才改它。
    large_scene = re.findall(r'^#define GS_LARGE_SCENE ([0-9]+)(?:ULL)?$', text, re.M)
    expected_large_scene = abi.large_scene_for_size(len(raw))
    require(len(large_scene) <= 1 and (int(large_scene[0]) if large_scene else 0) == expected_large_scene,
            'CURRENCY_COMPILED_SNAPSHOT_ABI')
    baseline = re.findall(r'inline constexpr unsigned char kTemplateExpectedSnapshot\[\] = \{\n([0-9,\n]+)\n\};', text)
    require(len(baseline) == 1 and bytes(int(v) for v in baseline[0].replace('\n', '').split(',') if v) == raw,
            'CURRENCY_COMPILED_BASELINE')


def validate_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()), 'DEDICATED_CURRENCY_RUN_REQUIRED')
    prepared, built, contract = (requests.read_json(run / name) for name in
                                 ('prepared.json', 'build-result.json', 'build-contract.json'))
    for value, kind in ((prepared, 'template-currency-prepared-v1'), (built, 'template-currency-build-v1'),
                        (contract, 'template-currency-build-contract-v1')):
        require(value.get('kind') == kind and value.get('schemaVersion') == 1 and
                value.get('action') == 'create-currency' and value.get('actionCode') == 5 and
                value.get('compileOnly') is False and value.get('reviewed') is True and
                value.get('allowWrites') is True, 'DEDICATED_CURRENCY_BUILD_CONTRACT')
    require(prepared.get('launchable') is True and built.get('launchable') is True and
            contract.get('launchable') is False and prepared.get('compiled') is True and built.get('compiled') is True and
            built.get('ok') is True and prepared.get('receiptVersion') == contract.get('receiptVersion') == 9 and
            built.get('run') == str(run), 'CURRENCY_LAUNCHABLE_BUILD_REQUIRED')
    require(prepared.get('wrapperName') == built.get('wrapperName') == 'invoke-currency-probe.ps1', 'CURRENCY_WRAPPER')
    for key, value in contract.items():
        if key not in ('kind', 'launchable'):
            require(prepared.get(key) == value, 'CURRENCY_PREPARED_CONTRACT_MISMATCH:' + key)
    for key in ('requestSha256', 'reviewSha256', 'nonce', 'deadline'):
        require(built.get(key) == prepared.get(key), 'CURRENCY_BUILD_BINDING:' + key)
    hashes = built.get('hashes')
    required = {'prepared.json', 'build-contract.json', 'target_config.h', 'baseline-snapshot.bin',
                'request.json', 'review.json', 'hook_receipt.dll', 'hook_receipt_probe.exe', 'invoke-currency-probe.ps1'}
    required.update('candidate-source/native/' + name for name in candidate.NATIVE_FILES)
    required.update('candidate-source/template-authoring/' + name for name in candidate.TEMPLATE_FILES)
    require(type(hashes) is dict and required <= set(hashes), 'CURRENCY_ARTIFACT_HASH_SET')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        require(path.is_relative_to(run) and path != run and profiles.sha256(path) == digest,
                'CURRENCY_ARTIFACT_CHANGED:' + name)
    review, request = requests.read_json(run / 'review.json'), requests.validate_request(requests.read_json(run / 'request.json'))
    requests.exact_fields(review, reviews.FIELDS, 'currency-review')
    require(review['state'] == 'reviewed' and review['kind'] == 'template-currency-review-v1' and
            review['reviewedBy'] == 'coordinator' and review['action'] == request['action'] == 'create-currency',
            'CURRENCY_REVIEW_REQUIRED')
    require(profiles.sha256(run / 'request.json') == review['requestSha256'] == prepared['requestSha256'] and
            (run / 'request.json').read_bytes() == requests.canonical_bytes(request) and
            profiles.sha256(run / 'review.json') == prepared['reviewSha256'], 'CURRENCY_REVIEW_REQUEST_HASH')
    require(review['sourceHashes'] == prepared['sourceHashes'] == reviews.source_hashes(), 'CURRENCY_SOURCE_CHANGED')
    profile = profiles.load_profile()
    require(review['readonlyProfileSha256'] == profiles.PROFILE_SHA256 and
            prepared['disk'].get('sha256') == profile['image']['sha256'], 'CURRENCY_CURRENT_PROFILE_REQUIRED')
    runtime_path = requests.runtime_path(review['runtimeProfilePath'])
    require(profiles.sha256(runtime_path) == review['runtimeProfileSha256'], 'CURRENCY_RUNTIME_PROFILE_CHANGED')
    session = prepared['session']
    require({key: session.get(key) for key in requests.SESSION_FIELDS} == review['session'] == request['session'] and
            all(type(session.get(key)) is int and session[key] > 1 for key in ('pid', 'tid', 'window', 'processCreation', 'threadCreation')) and
            session['windowClass'] == 'UnityWndClass' and
            Path(session['image']).resolve() == profiles.TARGET_IMAGE.resolve(), 'CURRENCY_REAL_SESSION_REQUIRED')
    level = request['levelId']
    require(level == review['levelId'] == prepared['levelId'] and
            review['reviewId'] == prepared['reviewId'] and prepared['ttlSeconds'] == 180 and
            review['expiresUtc'] == prepared['reviewExpiresUtc'], 'CURRENCY_REQUEST_IDENTITY')
    baseline_run = requests.runtime_path(review['baselineRun'])
    require(baseline_run.name == request['runId'] and review['baselineKind'] == 'readonly' and
            review['evidenceHashes'] == requests._baseline_hashes(baseline_run, 'readonly'), 'CURRENCY_BASELINE_CHANGED')
    # This is the original readonly baseline, never a relabelled action receipt.
    baseline, baseline_prepared = requests.review_api.load_baseline(baseline_run, 'readonly', level)
    require(all(baseline_prepared['session'].get(k) == session[k] for k in requests.SESSION_FIELDS), 'CURRENCY_BASELINE_SESSION')
    raw = (run / 'baseline-snapshot.bin').read_bytes()
    old_record, _ = readonly.load_decoder().read_probe(baseline_run / 'stdout.jsonl')
    require(raw == bytes.fromhex(old_record['snapshotHex']), 'CURRENCY_BASELINE_RAW_CHANGED')
    header_binding(run / 'target_config.h', prepared, raw)
    claim = requests.read_json(requests.runtime_path(prepared['reviewClaimPath']))
    require(claim.get('reviewSha256') == prepared['reviewSha256'] and claim.get('requestSha256') == prepared['requestSha256'] and
            claim.get('run') == str(run) and claim.get('claim') == 'single-currency-compilation-no-auto-retry', 'CURRENCY_REVIEW_CLAIM')
    for name in ('launch.claim', 'attempt.used'):
        require((run / name).is_file() and (run / name).stat().st_size == 0, 'CURRENCY_ATTEMPT_REQUIRED:' + name)
    exit_record = requests.read_json(run / 'exit.json')
    require(exit_record.get('executed') is True and type(exit_record.get('exitCode')) is int and exit_record['exitCode'] == 0 and
            not exit_record.get('error') and exit_record.get('scope') == 'FIXED_TEMPLATE_CURRENCY_ACTION', 'CURRENCY_NATIVE_EXIT')
    require(date(review['reviewedAtUtc']) <= date(prepared['preparedAtUtc']) <= date(exit_record['startedUtc']) < date(review['expiresUtc']) and
            date(exit_record['finishedUtc']) >= date(exit_record['startedUtc']) and
            0 < (date(review['expiresUtc']) - date(review['reviewedAtUtc'])).total_seconds() <= 3600,
            'CURRENCY_EXECUTION_OUTSIDE_REVIEW')
    record = read_record(run / 'stdout.jsonl')
    # 2026-10-17 双 ABI：v1=33208 B（512 实体）/ v2=262584 B（4096 实体，蒙德 1613 实体用这个）。
    # 保留 v1 兼容：默认常量不变，v2 由记录自述的 snapshotBytes 接受（不认识即具名拒绝）。
    snapshot_size = abi.validate_snapshot_size(record.get('snapshotBytes'), 'CURRENCY_NATIVE_TRANSPORT')
    prepared_abi = prepared.get('snapshotBytes')
    if prepared_abi is not None:      # 旧 run 的 prepared.json 没有这个键（v1 行为不变）
        require(abi.validate_snapshot_size(prepared_abi, 'CURRENCY_PREPARED_ABI') == len(raw) == snapshot_size,
                'CURRENCY_PREPARED_ABI')
    require(record.get('scope') == 'FIXED_TEMPLATE_CURRENCY_ACTION' and record.get('selfTestOnly') is False and
            record.get('ok') is True and record.get('probeElevatedHigh') is True and record.get('transportOk') is True and
            record.get('pid') == session['pid'] and record.get('tid') == session['tid'] and
            record.get('callbackCount') == 1 and record.get('activeCallbacks') == 0 and record.get('unhooked') is True and
            record.get('hostPostUnhookPings') == 0 and record.get('snapshotStatus') == 0 and
            record.get('snapshotBytes') == snapshot_size, 'CURRENCY_NATIVE_TRANSPORT')
    action, expected = decode_native(record)
    require(expected == raw, 'CURRENCY_NATIVE_EXPECTED_BASELINE')
    require(action['sehCode'] == 0 and action['afterSceneUnchanged'] == 1 and action['code'] == 0 and
            action['stage'] == 4 and action['callCode'] == action['mainDeltaCode'] == 0 and
            0 <= action['count'] < action['limit'] <= 0xffffffff and all(action[name] for name in BOOL_FIELDS),
            'CURRENCY_NATIVE_RESULT_NOT_VERIFIED')
    current = scene(blob(record['snapshotHex'], snapshot_size, 'CURRENT_SNAPSHOT'), profile, level)
    after = scene(blob(record['afterSnapshotHex'], snapshot_size, 'AFTER_SNAPSHOT'), profile, level)
    same_scene(baseline, current); same_scene(current, after)
    before_catalog = catalogs.decode_catalog(record['beforeCatalogHex'])
    require(before_catalog['global'] == int(current['pointers']['global'], 16), 'CURRENCY_CATALOG_GLOBAL')
    delta = catalogs.verify_currency_delta(record['beforeCatalogHex'], record['afterCatalogHex'],
        level_id=level, returned_resource=action['returnedResource'], expected_class=action['observedCurrencyClass'])
    require(action['createdId'] == delta['createdId'], 'CURRENCY_CREATED_ID_MISMATCH')
    input_hashes = {name: profiles.sha256(run / name) for name in
                   (*hashes, 'build-result.json', 'stdout.jsonl', 'stderr.txt', 'exit.json', 'launch.claim', 'attempt.used')}
    return {'ok': True, 'state': 'catalog-registered-only', 'action': 'create-currency',
        'scope': 'FIXED_TEMPLATE_CURRENCY_ACTION', 'run': str(run), 'levelId': level,
        'requestSha256': prepared['requestSha256'], 'reviewSha256': prepared['reviewSha256'],
        'catalogRegisteredVerified': True, 'createdId': delta['createdId'],
        'returnedResource': hex(action['returnedResource']), 'observedCurrencyClass': hex(action['observedCurrencyClass']),
        'outcomeUncertain': action['outcomeUncertain'], 'persistentSaveVerified': False,
        'nameVerified': False, 'defaultsVerified': False, 'gameplayVerified': False,
        'inputHashes': input_hashes, 'acceptorSha256': profiles.sha256(Path(__file__)),
        'limits': 'Native transport and independent raw registration delta only. No name/default/export/save/gameplay acceptance.'}


def accept_run(run):
    run = requests.runtime_path(run)
    require(run.is_relative_to(PREPARED_ROOT.resolve()) and run.is_dir(), 'DEDICATED_CURRENCY_RUN_REQUIRED')
    output = run / 'currency-acceptance.json'
    require(not output.exists(), 'CURRENCY_ACCEPTANCE_ALREADY_EXISTS')
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
            result['outcomeUncertain'] = reported['outcomeUncertain']
            result['reportedCreateCalled'] = reported['createCalled']
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
