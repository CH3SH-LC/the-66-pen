"""Verify a generalized-tabs receipt against the parameter table it was built from.

Independent of the native side's own success summary:

  * every offset comes from the compiled receipt-layout table, never from a literal
    (a missing field is layout_incomplete, not a silent misread);
  * every refusal is reported by name and stage; a refused run never reads as success;
  * the option captions are compared as UTF-16 against the spec file, so a mis-encoded
    C++ literal cannot pass even though the native readback compared it with itself;
  * the before/after snapshots are compared field by field, so "scene unchanged" is
    re-derived here instead of trusted, and their ABI is derived from the payload itself
    (v1 512 entities / v2 4096 entities) rather than from one remembered size.

The output is written once (evidence_output_exists if it already exists) and always
carries saveVerified=false / playVerified=false / playerVisibleVerified=false: this
file proves a component readback in the game process, nothing more.

Usage:
  python -B tools/game-executor/native-options/verify_generalized_receipt.py \
      --run RUN --layout RUN/receipt-layout.json --spec RUN/normalized-spec.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build_generalized as build  # noqa: E402  (no heavy imports at module level)
# The decoder owns the snapshot layout formula; the builder re-exports it after putting
# tools/game-executor on sys.path, so the verifier reads the same registry it does.
snapshot_decoder = build.snapshot_decoder

ROOT = build.ROOT


class ReceiptRefusal(Exception):
    """A receipt that must not be certified. `code` is a refusal code."""

    def __init__(self, code: str, detail: str = '') -> None:
        if code not in build.refusal_code_names():
            raise ValueError('unknown refusal code ' + code)
        super().__init__(code + (':' + detail if detail else ''))
        self.code = code
        self.detail = detail


def refuse(code: str, detail: str = ''):
    raise ReceiptRefusal(code, detail)


def tool_path() -> None:
    if str(build.EX) not in sys.path:
        sys.path.insert(0, str(build.EX))


def layout_value(layout, section: str, key: str) -> int:
    block = layout.get(section) if isinstance(layout, dict) else None
    if not isinstance(block, dict) or type(block.get(key)) is not int:
        refuse('layout_incomplete', section + '.' + key)
    return block[key]


def relative(layout, section: str, key: str, fmt: str, raw: bytes, base: int = 0):
    at = base + layout_value(layout, section, key)
    size = struct.calcsize(fmt)
    if at < 0 or at + size > len(raw):
        refuse('layout_incomplete', f'{section}.{key} outside the receipt')
    return struct.unpack_from(fmt, raw, at)[0]


def refuse_name(layout, code: int) -> str:
    table = layout.get('refuseCodes') if isinstance(layout, dict) else None
    if not isinstance(table, dict):
        refuse('layout_refuse_table_missing')
    entry = table.get(str(code))
    if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
        refuse('layout_refuse_table_missing', str(code))
    return entry['name']


def scene_abi(raw: bytes, scene_size: int, label: str) -> dict:
    """The snapshot ABI of one scene payload, derived -- never one remembered size.

    Two independent statements must agree: the compiler's `sizeof(GameContextSnapshot)`
    (the layout probe's `sceneSize`) and the payload's own header (structSize/version),
    checked against the reviewed registry the decoder owns
    (decode_context_snapshot.SNAPSHOT_LAYOUTS: v1 512 entities / 33208 B, v2 4096 entities /
    262584 B, both through 184 + 32*8 + N*64). Every disagreement is a named refusal; no
    path truncates, pads or re-reads the payload at another size.

    Codes: an unreviewed compiler size keeps the historical `layout_incomplete`
    (tools/mondstadt/life/tests/test_life_tabs_spec.py pins that name); a reviewed size whose
    payload length is something else is `scene_size_mismatch`; a payload whose header
    contradicts its own length or the registry is `scene_abi_mismatch`.
    """
    reviewed = [abi for abi in build.SNAPSHOT_ABIS.values() if abi['bytes'] == scene_size]
    if len(reviewed) != 1:
        refuse('layout_incomplete',
               f'{label} snapshot ABI {scene_size} is not a reviewed ABI '
               f'({",".join(f"v{abi['version']}:{abi['bytes']}" for abi in build.SNAPSHOT_ABIS.values())})')
    abi = reviewed[0]
    if len(raw) != abi['bytes']:
        refuse('scene_size_mismatch', f'{label} snapshot is {len(raw)} bytes, not the {abi["bytes"]} '
                                      f'bytes the compiler reports for ABI v{abi["version"]}')
    struct_size, version = struct.unpack_from(snapshot_decoder.SNAPSHOT_HEADER_UNPACK, raw, 0)[:2]
    if struct_size not in (0, len(raw)):
        refuse('scene_abi_mismatch',
               f'{label} snapshot header structSize={struct_size} != its own {len(raw)} bytes')
    if (struct_size == 0) != (version == 0):
        refuse('scene_abi_mismatch',
               f'{label} snapshot header is half-initialized: structSize={struct_size} version={version}')
    if version != 0 and version != abi['version']:
        refuse('scene_abi_mismatch',
               f'{label} snapshot header version={version} != v{abi["version"]} for {len(raw)} bytes')
    return dict(build.SNAPSHOT_ABIS[abi['version']], entityOffset=snapshot_decoder.ENTITIES_OFFSET,
                entityStride=snapshot_decoder.ENTITY.size, headerInitialized=struct_size != 0,
                source=label)


def scene_identity(raw: bytes, scene_size: int, label: str) -> dict:
    """The fields the native comparison uses, read straight out of a snapshot.

    The offsets are the shared GameContextSnapshot ABI, not the receipt's: header 184 bytes +
    32 stack slots * 8 (tools/game-executor/decode_context_snapshot.py:23-26,56, asserted at
    compile time by game_context_snapshot.h:119-120). Entity capacity and stride come from the
    derived ABI, so a v1 and a v2 snapshot each read at their own offsets.
    """
    abi = scene_abi(raw, scene_size, label)
    entity_captured = struct.unpack_from('<I', raw, snapshot_decoder.count_offset('entityCaptured'))[0]
    if entity_captured > abi['maxEntities']:
        refuse('scene_abi_mismatch',
               f'{label} entityCaptured={entity_captured} exceeds the {abi["maxEntities"]} entities '
               f'ABI v{abi["version"]} ({abi["bytes"]} bytes) can hold')
    entities = []
    for index in range(entity_captured):
        at = abi['entityOffset'] + index * abi['entityStride']
        if at + abi['entityStride'] > len(raw):
            refuse('scene_abi_mismatch', f'{label} entity {index} outside the snapshot')
        entities.append(struct.unpack_from('<QQQIII', raw, at))
    return {
        'flags': struct.unpack_from('<I', raw, 12)[0],
        'levelId': struct.unpack_from('<I', raw, snapshot_decoder.RESERVED_OFFSET)[0],
        'entityCaptured': entity_captured,
        'entityValidEntries': struct.unpack_from('<I', raw, snapshot_decoder.count_offset('entityValidEntries'))[0],
        'entityRejected': struct.unpack_from('<I', raw, snapshot_decoder.count_offset('entityRejected'))[0],
        'entities': entities,
    }


def compare_scenes(before_raw: bytes, after_raw: bytes, scene_size: int) -> dict:
    before = scene_identity(before_raw, scene_size, 'before')
    after = scene_identity(after_raw, scene_size, 'after')
    for key in ('flags', 'levelId', 'entityCaptured', 'entityValidEntries', 'entityRejected', 'entities'):
        if before[key] != after[key]:
            refuse('scene_changed', f'{key}: before={before[key]!r} after={after[key]!r}')
    return {'sceneUnchanged': True, 'beforeLevelId': before['levelId'], 'afterLevelId': after['levelId'],
            'entityCaptured': before['entityCaptured'], 'flags': before['flags'],
            'entitiesCompared': len(before['entities'])}


def decode_receipt(raw: bytes, layout, spec, summary=None) -> dict:
    """Decode and check one receipt. Every failure raises a named ReceiptRefusal."""
    receipt_size = layout_value(layout, 'receipt', 'size')
    if len(raw) != receipt_size:
        refuse('receipt_size_mismatch', f'{len(raw)} != {receipt_size}')
    host_slots = layout_value(layout, 'receipt', 'hostSlots')
    max_hosts = layout_value(layout, 'receipt', 'maxHosts')
    if host_slots != max_hosts:
        refuse('host_capacity_mismatch', f'receipt array {host_slots} != declared limit {max_hosts}')
    max_options = layout_value(layout, 'receipt', 'maxOptionsPerHost')
    option_slots = layout_value(layout, 'host', 'optionSlots')
    if option_slots != max_options:
        refuse('host_capacity_mismatch', f'option array {option_slots} != declared limit {max_options}')

    version = relative(layout, 'receipt', 'version', '<I', raw)
    status = relative(layout, 'receipt', 'status', '<I', raw)
    seh = relative(layout, 'receipt', 'sehCode', '<I', raw)
    stage = relative(layout, 'receipt', 'stage', '<I', raw)
    refuse_code = relative(layout, 'receipt', 'refuseCode', '<I', raw)
    refuse_stage = relative(layout, 'receipt', 'refuseStage', '<I', raw)
    refuse_host = relative(layout, 'receipt', 'refuseHost', '<I', raw)
    refuse_option = relative(layout, 'receipt', 'refuseOption', '<I', raw)
    host_count = relative(layout, 'receipt', 'hostCount', '<I', raw)
    completed = relative(layout, 'receipt', 'completedHosts', '<I', raw)
    scene_unchanged = relative(layout, 'receipt', 'sceneUnchanged', '<I', raw)
    kind = relative(layout, 'receipt', 'kind', '<I', raw)
    expected_level = relative(layout, 'receipt', 'expectedLevelId', '<I', raw)
    level_before = relative(layout, 'receipt', 'levelIdBefore', '<I', raw)
    level_after = relative(layout, 'receipt', 'levelIdAfter', '<I', raw)
    radius = relative(layout, 'receipt', 'radius', '<f', raw)
    metadata_calls = relative(layout, 'receipt', 'metadataCalls', '<I', raw)

    if seh:
        refuse('business_status_not_ok', f'sehCode={seh} stage={stage}')
    if status != 0:
        reported = refuse_name(layout, refuse_code) if refuse_code else 'none'
        refuse('receipt_refused' if refuse_code else 'business_status_not_ok',
               f'status={status} stage={stage} refused={reported} refuseStage={refuse_stage} '
               f'refuseHost={refuse_host} refuseOption={refuse_option}')
    if refuse_code:
        refuse('receipt_refused',
               f'{refuse_name(layout, refuse_code)} stage={refuse_stage} host={refuse_host} option={refuse_option}')
    if scene_unchanged != 1:
        refuse('scene_changed', 'receipt reports sceneUnchanged=0')
    if version != 1:
        refuse('business_status_not_ok', f'receipt version {version}')

    # The usage-group metadata bootstrap is part of the reviewed action: require it to
    # have run exactly once per group from the pinned profile.
    attempted = relative(layout, 'receipt', 'attempted', '<I', raw)
    groups = len(build.runtime_profile().get('usageGroups', []))
    if attempted != 1 or metadata_calls != groups:
        refuse('business_status_not_ok',
               f'attempted={attempted} metadataCalls={metadata_calls} expected {groups}')

    spec_hosts = spec['hosts']
    if len(spec_hosts) > max_hosts:
        refuse('spec_host_limit_exceeded', f'{len(spec_hosts)} > {max_hosts}')
    if host_count != len(spec_hosts):
        refuse('host_count_mismatch', f'receipt {host_count} != spec {len(spec_hosts)}')
    if completed != host_count:
        refuse('business_status_not_ok', f'completedHosts {completed} != hostCount {host_count}')
    if expected_level != spec['levelId']:
        refuse('level_mismatch', f'expectedLevelId {expected_level} != spec {spec["levelId"]}')
    for label, value in (('levelIdBefore', level_before), ('levelIdAfter', level_after)):
        if value != spec['levelId']:
            refuse('level_mismatch', f'{label} {value} != declared {spec["levelId"]}')
    if kind != spec['kind']:
        refuse('component_kind_mismatch', f'receipt kind {kind} != spec {spec["kind"]}')
    spec_radius = struct.unpack('<f', struct.pack('<f', spec['radius']))[0]
    if radius != spec_radius:
        refuse('spec_radius_mismatch', f'receipt radius {radius!r} != spec {spec_radius!r}')

    if isinstance(summary, dict):
        for key, value in (('status', status), ('sehCode', seh), ('refuseCode', refuse_code),
                           ('refuseStage', refuse_stage), ('hostCount', host_count),
                           ('completedHosts', completed), ('expectedLevelId', expected_level),
                           ('attempted', attempted), ('metadataCalls', metadata_calls),
                           ('sceneUnchanged', scene_unchanged)):
            if summary.get(key) != value:
                refuse('receipt_summary_disagrees', f'{key}: summary={summary.get(key)!r} hex={value!r}')

    codes = layout.get('codes')
    if not isinstance(codes, dict) or type(codes.get('attach_attached_verified')) is not int \
            or type(codes.get('edit_complete')) is not int:
        refuse('layout_incomplete', 'codes')
    host_stride = layout_value(layout, 'receipt', 'hostStride')
    hosts_at = layout_value(layout, 'receipt', 'hosts')
    hosts = []
    for host_index in range(host_count):
        base = hosts_at + host_index * host_stride
        if base + host_stride > len(raw):
            refuse('layout_incomplete', f'host {host_index} outside the receipt')
        entity_id = relative(layout, 'host', 'entityId', '<I', raw, base)
        spec_host = spec_hosts[host_index]
        if entity_id != spec_host['entityId']:
            refuse('host_entity_mismatch', f'hosts[{host_index}]: receipt {entity_id} != spec {spec_host["entityId"]}')
        host_status = relative(layout, 'host', 'status', '<I', raw, base)
        host_refuse = relative(layout, 'host', 'refuseCode', '<I', raw, base)
        host_stage = relative(layout, 'host', 'refuseStage', '<I', raw, base)
        host_option = relative(layout, 'host', 'refuseOption', '<I', raw, base)
        if host_refuse:
            refuse('receipt_refused',
                   f'hosts[{host_index}] {refuse_name(layout, host_refuse)} stage={host_stage} '
                   f'option={host_option}')
        if host_status != 0:
            refuse('business_status_not_ok', f'hosts[{host_index}].status={host_status}')
        attach_code = relative(layout, 'host', 'attachmentCode', '<I', raw, base)
        if attach_code != codes['attach_attached_verified']:
            hint = 'existing component (not overwritten)' if attach_code == codes.get('attach_existing') else 'not attached_verified'
            refuse('attach_code_not_verified', f'hosts[{host_index}].attachCode={attach_code} ({hint})')
        edit_code = relative(layout, 'host', 'editCode', '<I', raw, base)
        if edit_code != codes['edit_complete']:
            refuse('business_status_not_ok', f'hosts[{host_index}].editCode={edit_code}')
        component_kind = relative(layout, 'host', 'componentKind', '<I', raw, base)
        if component_kind != spec['kind']:
            refuse('component_kind_mismatch', f'hosts[{host_index}].componentKind={component_kind} != {spec["kind"]}')
        kind_rows = relative(layout, 'host', 'kindRowsFound', '<I', raw, base)
        kind_matches = relative(layout, 'host', 'kindRowMatchesConfig', '<I', raw, base)
        if kind_rows != 1 or kind_matches != 1:
            refuse('component_kind_readback_mismatch',
                   f'hosts[{host_index}] kindRowsFound={kind_rows} kindRowMatchesConfig={kind_matches}')
        option_count = relative(layout, 'host', 'optionCount', '<I', raw, base)
        spec_options = spec_host['options']
        if option_count != len(spec_options):
            refuse('option_count_mismatch', f'hosts[{host_index}]: {option_count} != {len(spec_options)}')
        if option_count > max_options:
            refuse('host_capacity_mismatch', f'hosts[{host_index}]: {option_count} > {max_options}')
        collider_count = relative(layout, 'host', 'colliderCount', '<I', raw, base)
        if collider_count != 1:
            refuse('collider_list_shape_mismatch', f'hosts[{host_index}].colliderCount={collider_count}')
        collider_shape = relative(layout, 'host', 'colliderShape', '<i', raw, base)
        if collider_shape != 1:
            refuse('collider_shape_mismatch', f'hosts[{host_index}].colliderShape={collider_shape}')
        host_radius = relative(layout, 'host', 'radius', '<f', raw, base)
        if host_radius != spec_radius:
            refuse('radius_mismatch', f'hosts[{host_index}].radius={host_radius!r} != {spec_radius!r}')
        for key in ('radiusVerified', 'textVerified', 'readbackVerified'):
            if relative(layout, 'host', key, '<I', raw, base) != 1:
                refuse('business_status_not_ok', f'hosts[{host_index}].{key}=0')
        option_stride = layout_value(layout, 'option', 'size')
        options_at = layout_value(layout, 'host', 'options')
        text_units = layout_value(layout, 'receipt', 'maxTextUnits')
        options = []
        for option_index, spec_option in enumerate(spec_options):
            at = base + options_at + option_index * option_stride
            if at + option_stride > len(raw):
                refuse('layout_incomplete', f'hosts[{host_index}].options[{option_index}] outside the receipt')
            index = relative(layout, 'option', 'index', '<i', raw, at)
            if index != spec_option['index']:
                refuse('option_index_mismatch',
                       f'hosts[{host_index}].options[{option_index}]: {index} != {spec_option["index"]}')
            expected_index = relative(layout, 'option', 'expectedIndex', '<i', raw, at)
            if expected_index != spec_option['index']:
                refuse('option_index_mismatch', f'expectedIndex {expected_index}')
            expected_enabled = relative(layout, 'option', 'expectedEnabled', '<I', raw, at)
            if expected_enabled != (1 if spec_option['enabled'] else 0):
                refuse('option_enabled_mismatch', f'expectedEnabled {expected_enabled}')
            text_length = relative(layout, 'option', 'textLength', '<i', raw, at)
            expected_units = relative(layout, 'option', 'expectedTextUnits', '<I', raw, at)
            encoded = spec_option['text'].encode('utf-16-le')
            spec_units = len(encoded) // 2
            if expected_units != spec_units:
                refuse('option_text_mismatch', f'expectedTextUnits {expected_units} != {spec_units}')
            if text_length != spec_units:
                refuse('option_text_mismatch', f'textLength {text_length} != {spec_units}')
            if text_length < 1 or text_length >= text_units:
                refuse('option_text_mismatch', f'textLength {text_length} outside 1..{text_units - 1}')
            text_at = at + layout_value(layout, 'option', 'text')
            if text_at + text_length * 2 > len(raw):
                refuse('layout_incomplete', 'option text outside the receipt')
            readback = raw[text_at:text_at + text_length * 2].decode('utf-16-le', errors='strict')
            if readback != spec_option['text']:
                mismatch = relative(layout, 'option', 'mismatchUnit', '<I', raw, at)
                refuse('option_text_mismatch',
                       f'hosts[{host_index}].options[{option_index}]: readback {readback!r} != '
                       f'spec {spec_option["text"]!r} (mismatchUnit={mismatch})')
            if relative(layout, 'option', 'textMatched', '<I', raw, at) != 1:
                refuse('option_text_mismatch', f'textMatched=0 hosts[{host_index}].options[{option_index}]')
            if relative(layout, 'option', 'indexMatched', '<I', raw, at) != 1:
                refuse('option_index_mismatch', f'indexMatched=0 hosts[{host_index}].options[{option_index}]')
            if relative(layout, 'option', 'enabledMatched', '<I', raw, at) != 1:
                refuse('option_enabled_mismatch', f'enabledMatched=0 hosts[{host_index}].options[{option_index}]')
            state = relative(layout, 'option', 'activeOrEnabledState', '<B', raw, at)
            row_enabled = relative(layout, 'option', 'rowEnabledByte', '<B', raw, at)
            wanted = 1 if spec_option['enabled'] else 0
            if state != wanted:
                refuse('option_enabled_mismatch',
                       f'hosts[{host_index}].options[{option_index}]: state {state} != spec {wanted}')
            options.append({
                'index': index,
                'text': readback,
                'utf16Units': text_length,
                'enabled': bool(expected_enabled),
                'initialActiveState': state,
                'rowEnabledByteObserved': row_enabled,
                'textMatched': True,
            })
        hosts.append({
            'entityId': entity_id,
            'attachCode': attach_code,
            'editCode': edit_code,
            'componentKind': component_kind,
            'kindRowsFound': kind_rows,
            'kindRowMatchesConfig': kind_matches,
            'colliderCount': collider_count,
            'colliderShape': collider_shape,
            'radius': host_radius,
            'options': options,
        })
    result = {
        'ok': True,
        'status': 'receipt-verified',
        'actionCode': layout.get('actionCode'),
        'receiptVersion': layout.get('receiptVersion'),
        'levelId': expected_level,
        'levelIdObservedBefore': level_before,
        'levelIdObservedAfter': level_after,
        'kind': kind,
        'radius': radius,
        'hostCount': host_count,
        'completedHosts': completed,
        'metadataCalls': metadata_calls,
        'hosts': hosts,
        'sceneUnchanged': bool(scene_unchanged),
        'saveVerified': False,
        'playVerified': False,
        'playerVisibleVerified': False,
        'limits': ('Component attach + field readback inside the game process only. No save, '
                   'no reopen, no player-visible confirmation is established by this file.'),
        'unresolved': [],
    }
    return result


def verify(run, layout_path, spec_path, out_path=None) -> dict:
    tool_path()
    import build_readonly_profile as ro
    run = Path(run).resolve()
    layout = json.loads(Path(layout_path).read_text(encoding='utf-8-sig'))
    spec_raw = json.loads(Path(spec_path).read_text(encoding='utf-8-sig'))
    try:
        spec = build.validate_spec(spec_raw)
    except build.SpecRefusal as refusal:
        refuse('spec_not_normalizable', f'{refusal.code}: {refusal.detail}')
    except build.BuildError as error:
        refuse('spec_not_normalizable', str(error))
    record, _ = ro.load_decoder().read_probe(run / 'stdout.jsonl')
    for key, wanted in (('ok', True), ('transportOk', True), ('unhooked', True)):
        if record.get(key) is not wanted:
            refuse('transport_not_ok', f'{key}={record.get(key)!r}')
    if record.get('callbackCount') != 1 or record.get('activeCallbacks') != 0:
        refuse('transport_not_ok', f'callbackCount={record.get("callbackCount")} '
                                  f'activeCallbacks={record.get("activeCallbacks")}')
    if record.get('scope') != 'FIXED_GENERALIZED_TABS_ACTION':
        refuse('business_status_not_ok', f'scope={record.get("scope")!r}')
    encoded = record.get('generalizedTabsHex')
    if not isinstance(encoded, str) or not encoded:
        refuse('receipt_bytes_missing', 'generalizedTabsHex')
    raw = bytes.fromhex(encoded)
    if record.get('generalizedTabsBytes') != len(raw):
        refuse('receipt_size_mismatch', f'generalizedTabsBytes={record.get("generalizedTabsBytes")}')
    before_hex = record.get('snapshotHex')
    after_hex = record.get('afterSceneHex')
    if not isinstance(before_hex, str) or not isinstance(after_hex, str):
        refuse('receipt_bytes_missing', 'snapshotHex/afterSceneHex')
    scene_size = layout_value(layout, 'receipt', 'sceneSize')
    before = bytes.fromhex(before_hex)
    after = bytes.fromhex(after_hex)
    result = decode_receipt(raw, layout, spec, record.get('generalizedTabs'))
    result.update({'sceneComparison': compare_scenes(before, after, scene_size)})
    exit_evidence = run / 'exit.json'
    if exit_evidence.is_file():
        exit_row = json.loads(exit_evidence.read_text(encoding='utf-8-sig'))
        if exit_row.get('executed') is not True or exit_row.get('exitCode') != 0 or exit_row.get('error'):
            refuse('exit_receipt_rejected',
                   f'executed={exit_row.get("executed")!r} exitCode={exit_row.get("exitCode")!r} '
                   f'error={exit_row.get("error")!r}')
        result['wrapperExitCode'] = exit_row.get('exitCode')
    else:
        result['unresolved'].append('exit.json missing: wrapper exit is not evidenced')
    result['evidence'] = {
        'run': str(run),
        'stdout': str(run / 'stdout.jsonl'),
        'layout': str(Path(layout_path).resolve()),
        'layoutSha256': hashlib.sha256(Path(layout_path).read_bytes()).hexdigest(),
        'spec': str(Path(spec_path).resolve()),
        'specSha256': hashlib.sha256(Path(spec_path).read_bytes()).hexdigest(),
        'receiptSha256': hashlib.sha256(raw).hexdigest(),
        'receiptBytes': len(raw),
    }
    destination = (Path(out_path).resolve() if out_path else run / 'generalized-tabs-verified.json')
    if destination.exists():
        refuse('evidence_output_exists', str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    result['output'] = str(destination)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='run directory holding stdout.jsonl')
    parser.add_argument('--layout', required=True, help='receipt-layout.json emitted by the build')
    parser.add_argument('--spec', required=True, help='the parameter table the build used')
    parser.add_argument('--out', help='output path (default RUN/generalized-tabs-verified.json)')
    args = parser.parse_args(argv)
    try:
        result = verify(args.run, args.layout, args.spec, args.out)
    except ReceiptRefusal as refusal:
        print(json.dumps({'ok': False, 'refused': refusal.code, 'detail': refusal.detail},
                         ensure_ascii=False))
        return 2
    print(json.dumps({key: value for key, value in result.items() if key != 'hosts'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
