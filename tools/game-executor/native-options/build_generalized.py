"""Bake the generalized kind-17 option-card parameter table and compile action 13.

This is the build entry for generalized_tabs.h/.cpp. It follows build.py exactly in the
two things that matter -- compile-time macro generation into the force-included
target_config.h, and the reviewed copy/edit/compile pipeline over the shared native
sources -- and adds three things build.py does not need:

  * a reviewed *spec* (Chinese option table, hosts, level id, radius, kind) validated
    before anything is generated, with named refusal codes;
  * a generated receipt-layout probe, so verify_generalized_receipt.py never hardcodes
    an offset: the compiler prints them and the verifier refuses if a field it needs is
    not in that table;
  * every call RVA must be one of the code anchors runtime-profile.json already pins, so
    "the address we call" and "the bytes we verified" cannot drift apart;
  * the snapshot ABI is *derived* from the snapshot (its own structSize/version plus the
    184 + 32*8 + N*64 formula owned by tools/game-executor/decode_context_snapshot.py) and
    cross-checked against the compiler's sizeof(GameContextSnapshot): the historical v1
    (512 entities) and the large-scene v2 (4096 entities) both build, and a payload that is
    neither -- or that is not the ABI this translation unit compiles -- is refused by name
    instead of being truncated.

Nothing here injects, elevates, launches the probe or touches the game. A successful
build is not a runtime acceptance: compile, injection and on-machine testing are the
leader's unified test stage (see GENERALIZED-TABS.md).

Usage:
  python -B tools/game-executor/native-options/build_generalized.py --spec SPEC.json
  python -B .../build_generalized.py --spec SPEC.json --layout-only
  python -B .../build_generalized.py --spec SPEC.json --layout-only --snapshot-abi v2
  python -B .../build_generalized.py --spec SPEC.json --baseline <readonly run dir>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import struct
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EX = HERE.parent
ROOT = EX.parents[1]
OUT = ROOT / '.runtime/native-options'

# Action identity. 12 is native_tabs/display-text, 13 is this action; the receipt
# protocol version is 18 (17 is the isolated display-field rank diagnostic).
ACTION_CODE = 13
RECEIPT_VERSION = 18
PROBE_URL_MESSAGE = 'Miliastra.GeneralizedTabs.'

# Capacities. These MUST equal generalized_tabs.h: the offline checker compares them
# textually, and the compiled layout probe compares the compiler's answer after a build.
MAX_HOSTS = 4
MAX_OPTIONS_PER_HOST = 4
MAX_TEXT_UNITS = 48
# ---- snapshot ABI: derived, dual, never a literal ------------------------------------
# The snapshot describes itself: its first four uint32 are structSize, version, status,
# flags (native/game_context_snapshot.h:104), and the entity capacity follows from the byte
# count through the one layout formula the decoder owns --
#
#     snapshotBytes(N) = 184 header + 32 stack slots * 8 + N entities * 64
#
# (tools/game-executor/decode_context_snapshot.py:23-27, asserted there against the compiled
# struct and again in game_context_snapshot.h:119-120). THIS FILE TYPES NO SNAPSHOT SIZE:
# every size below is derived from that decoder's SNAPSHOT_LAYOUTS registry, whose two
# reviewed ABIs are the historical v1 (512 entities, 33208 B, unchanged) and the large
# scene v2 (4096 entities, 262584 B, selected at compile time by GS_LARGE_SCENE,
# game_context_snapshot.h:80-92). EXPECTED_SNAPSHOT_BYTES / SNAPSHOT_MAX_ENTITIES survive
# only as the *historical v1* aliases so existing callers keep their meaning; every build
# path goes through snapshot_abi_* below, which refuses by name instead of resizing.
if str(EX) not in sys.path:
    sys.path.insert(0, str(EX))
import decode_context_snapshot as snapshot_decoder  # noqa: E402  (stdlib-only; owns the formula)

SNAPSHOT_ABIS = {version: {'version': version, 'bytes': size, 'maxEntities': counts[0],
                           'largeScene': snapshot_decoder.SNAPSHOT_LARGE_SCENE[version]}
                 for (version, size), counts in snapshot_decoder.SNAPSHOT_LAYOUTS.items()}
# The lowest reviewed version is the historical ABI (game_context_snapshot.h:86-92).
HISTORICAL_SNAPSHOT_VERSION = min(SNAPSHOT_ABIS)
EXPECTED_SNAPSHOT_BYTES = SNAPSHOT_ABIS[HISTORICAL_SNAPSHOT_VERSION]['bytes']
SNAPSHOT_MAX_ENTITIES = SNAPSHOT_ABIS[HISTORICAL_SNAPSHOT_VERSION]['maxEntities']
SNAPSHOT_ABI_CHOICES = ('auto',) + tuple(f'v{version}' for version in sorted(SNAPSHOT_ABIS))

SPEC_SCHEMA_VERSION = 1
SPEC_ACTION = 'generalized-tabs'
DEFAULT_KIND = 17
DEFAULT_RADIUS = 2.0
# component_attachment.cpp:173 accepts exactly these kinds; option cards are only
# profiled for 17 (its option/collider offsets exist, nobody else's do).
PRIMITIVE_KINDS = (17, 33, 35)
PROFILED_KIND = 17
# Same Chinese rule as tools/mondstadt/life/life_api.py:85,112-113 (CJK Unified
# Ideographs): the published interface says "中文 text" and the consumer enforces it.
CJK_START, CJK_STOP = 0x4E00, 0xA000

REQUIRED_COMPONENT_KEYS = (
    'classDefinition', 'classSlot', 'optionDefinition', 'optionSlot',
    'colliderDefinition', 'colliderSlot', 'optionListAddRva', 'optionListAddMethodInfoSlot',
    'colliderShape', 'sphereRadius', 'initialActiveProperty', 'captionProperty',
    'wrapperSlot', 'optionFactorySlot', 'indexProperty',
    'colliderShapeProperty', 'colliderRadiusProperty',
)

# Values runtime-profile.json does not carry. Each is copied from the reviewed historical
# action, not invented, and the citation travels with the value.
PINNED_DATA_SLOTS = {
    'wrapperSlot': ('0x57b0058ULL', 'native_tabs.cpp:65 + owner_notification_calls.cpp:43 (kind-independent wrapper class slot, definition 19879)'),
    'optionFactorySlot': ('0x5a298b8ULL', 'native_tabs.cpp:95 (type handle handed to the option factory)'),
    'indexProperty': ('0x090aa9abULL', 'native_tabs.cpp:103 (written with the card ordinal, same value as setIndex)'),
    'colliderShapeProperty': ('0x99112b76ULL', 'native_tabs.cpp:112'),
    'colliderRadiusProperty': ('0x0dba4cb3ULL', 'native_tabs.cpp:114'),
}

# Call targets: the macros generalized_tabs.cpp uses and the reviewed line each value
# comes from. Every value must be a code anchor in runtime-profile.json (checked below).
CALL_RVA_MACROS = (
    ('GT_ATTACH_RVA', '0x867c610ULL', 'component_attachment.h:7 AttachComponent'),
    ('GT_SET_INDEX_RVA', '0x9438200ULL', 'native_tabs.cpp:89 setIndex'),
    ('GT_SET_INT_RVA', '0x94393d0ULL', 'native_tabs.cpp:103 SetInt'),
    # 2026-10-19: collider（class 40001）的形状属性必须由 native_tabs.cpp:112 的 SetInt
    # (0x12ce23f0) 写入；0x94393d0 是 Option 卡片的 SetInt，对 collider 不生效。
    ('GT_SET_INT_COLLIDER_RVA', '0x12ce23f0ULL', 'native_tabs.cpp:112 SetInt(collider)'),
    ('GT_SET_BOOL_RVA', '0x9439240ULL', 'native_tabs.cpp:107 SetBool'),
    ('GT_SET_TEXT_RVA', '0x9438b60ULL', 'native_tabs.cpp:106 SetText'),
    ('GT_SET_FLOAT_RVA', '0xe80b1b0ULL', 'native_tabs.cpp:114 SetFloat'),
    ('GT_STRING_FACTORY_RVA', '0x526de0ULL', 'native_tabs.cpp:104 (utf8 bytes + length -> native string)'),
    ('GT_OPTION_FACTORY_RVA', '0x95f6410ULL', 'native_tabs.cpp:95'),
    ('GT_OPTION_LIST_ADD_RVA', '0x18baf8c0ULL', 'native_tabs.cpp:99 List<Option>.Add'),
    ('GT_TOUCH_RVA', '0x9438510ULL', 'native_tabs.cpp:108 post-write touch'),
    ('GT_METADATA_GROUP_RVA', '0x524250ULL', 'native_tabs.cpp:136 usage group bootstrap'),
    ('GT_EDIT_OPEN_RVA', '0xe827750ULL', 'native_tabs.cpp:74 OpenTransaction'),
    ('GT_EDIT_SNAPSHOT_RVA', '0x107abdf0ULL', 'native_tabs.cpp:75 SnapshotComponent'),
    ('GT_EDIT_NOTIFY_RVA', '0x9c26c70ULL', 'native_tabs.cpp:76 NotifyComponent'),
    ('GT_EDIT_CLOSE_RVA', '0xc7bab90ULL', 'native_tabs.cpp:77 CloseTransaction'),
)

# The two hosts and three labels of the historical action, expressed in the new schema.
# Used by GENERALIZED-TABS.md and by the offline checker.
EXAMPLE_SPEC = {
    'schemaVersion': SPEC_SCHEMA_VERSION,
    'action': SPEC_ACTION,
    'levelId': 1073741842,
    'levelIdEvidence': ('tools/game-executor/native-options/native_tabs.cpp:36 (historical level, '
                        'observed by the readonly probe)'),
    'kind': 17,
    'radius': 2.0,
    'hosts': [
        {'entityId': 1077936131, 'ref': 'MW_LIFE_CITY_SHOP_001',
         'options': [{'index': 1, 'text': '打开农场商店', 'enabled': True}]},
        {'entityId': 1077936133, 'ref': 'MW_LIFE_CITY_FARM_001',
         'options': [{'index': 1, 'text': '播种（消耗1颗种子）', 'enabled': True},
                     {'index': 2, 'text': '收获作物', 'enabled': False}]},
    ],
}

MACRO_SUFFIX = {
    'classSlot': 'CLASS_SLOT',
    'optionSlot': 'OPTION_SLOT',
    'colliderSlot': 'COLLIDER_SLOT',
    'optionListAddRva': 'OPTION_LIST_ADD_RVA',
    'optionListAddMethodInfoSlot': 'OPTION_LIST_ADD_METHOD_SLOT',
    'colliderShape': 'COLLIDER_SHAPE',
    'initialActiveProperty': 'INITIAL_ACTIVE_PROPERTY',
    'captionProperty': 'CAPTION_PROPERTY',
    'wrapperSlot': 'WRAPPER_SLOT',
    'optionFactorySlot': 'OPTION_FACTORY_SLOT',
    'indexProperty': 'INDEX_PROPERTY',
    'colliderShapeProperty': 'COLLIDER_SHAPE_PROPERTY',
    'colliderRadiusProperty': 'COLLIDER_RADIUS_PROPERTY',
    'classDefinition': 'CLASS_DEFINITION',
    'optionDefinition': 'OPTION_DEFINITION',
    'colliderDefinition': 'COLLIDER_DEFINITION',
    'sphereRadius': 'PROFILE_SPHERE_RADIUS',
}


class SpecRefusal(Exception):
    """A parameter table that must not be baked. `code` is a refusal code."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(code + (':' + detail if detail else ''))
        self.code = code
        self.detail = detail


class BuildError(Exception):
    """A build-level failure (toolchain, source drift, profile drift) -- not a spec one.

    Messages start with an uppercase reason, like build.py's SOURCE_PATTERN_CHANGED /
    BUILD_FAILED / MSVC_REQUIRED.
    """


_CODES = None


def refusal_codes(header_text=None):
    """The refusal-code table, parsed out of generalized_tabs.h.

    The header is the single source of truth: the C++ enum, the compiled name table,
    this validator and verify_generalized_receipt.py all read one list, so a code cannot
    mean two things in two places.
    """
    global _CODES
    if header_text is None and _CODES is not None:
        return _CODES
    text = header_text if header_text is not None else (HERE / 'generalized_tabs.h').read_text(encoding='utf-8')
    marker = '#define GT_REFUSE_CODES(X)'
    start = text.find(marker)
    if start < 0:
        raise BuildError('REFUSAL_CODE_TABLE_INVALID: marker missing from generalized_tabs.h')
    entries = []
    for raw in text[start + len(marker):].splitlines():
        line = raw.strip()
        if not line:
            break
        continued = line.endswith('\\')
        body = line[:-1].strip() if continued else line
        if body:
            match = re.fullmatch(r'X\(([a-z0-9_]+),\s*(\d+),\s*(build|runtime|verify)\)', body)
            if match is None:
                raise BuildError('REFUSAL_CODE_TABLE_INVALID: ' + raw.strip())
            entries.append((match.group(1), int(match.group(2)), match.group(3)))
        if not continued:
            break
    if not entries:
        raise BuildError('REFUSAL_CODE_TABLE_INVALID: empty')
    names = [entry[0] for entry in entries]
    if len(set(names)) != len(names):
        raise BuildError('REFUSAL_CODE_TABLE_INVALID: duplicate name')
    if [entry[1] for entry in entries] != list(range(len(entries))):
        raise BuildError('REFUSAL_CODE_TABLE_INVALID: values must be contiguous from 0')
    if header_text is None:
        _CODES = entries
    return entries


def refusal_code_names() -> frozenset:
    return frozenset(entry[0] for entry in refusal_codes())


def refusal_code_value(name: str) -> int:
    for entry in refusal_codes():
        if entry[0] == name:
            return entry[1]
    raise BuildError('REFUSAL_CODE_TABLE_INVALID: unknown code ' + name)


def refuse(code: str, detail: str = ''):
    if code not in refusal_code_names():
        raise BuildError('REFUSAL_CODE_TABLE_INVALID: unknown code ' + code)
    raise SpecRefusal(code, detail)


def snapshot_abi_by_selector(selector: str) -> dict:
    """'v1'/'v2' (as `--snapshot-abi` spells it) -> one reviewed ABI, never a size.

    The selector names a version; the byte count and the entity ceiling come from
    decode_context_snapshot.SNAPSHOT_LAYOUTS. An unknown version is refused by name rather
    than rounded to the nearest reviewed ABI.
    """
    text = str(selector).strip().lower()
    match = re.fullmatch(r'v([0-9]+)', text)
    if match is None or int(match.group(1)) not in SNAPSHOT_ABIS:
        refuse('snapshot_abi_unsupported',
               f'--snapshot-abi {selector!r} is not one of '
               f'{",".join(f"v{v}" for v in sorted(SNAPSHOT_ABIS))}')
    return dict(SNAPSHOT_ABIS[int(match.group(1))], source='--snapshot-abi ' + text)


def derived_snapshot_abi(raw, what: str) -> dict:
    """The ABI the payload itself declares, or a named refusal (`snapshot_abi_*`)."""
    try:
        abi = snapshot_decoder.derive_snapshot_abi(raw, what)
    except snapshot_decoder.SnapshotAbiError as error:
        refuse(error.code, error.detail)
    return abi


def require_compiled_scene_size(layout, abi: dict, what: str) -> None:
    """The compiler's own sizeof(GameContextSnapshot) must equal the derived ABI.

    `receipt.sceneSize` is printed by the generated layout probe, so this is a compiled
    answer and not a restatement of the derivation. Baking a payload of one ABI into a
    translation unit compiled for the other would be silently trimmed by
    `memcpy(&receipt.expectedScene, GT_EXPECTED_SNAPSHOT, sizeof(receipt.expectedScene))`
    (generalized_tabs.cpp:371); it is refused here instead.
    """
    block = layout.get('receipt') if isinstance(layout, dict) else None
    size = block.get('sceneSize') if isinstance(block, dict) else None
    if type(size) is not int or size != abi['bytes']:
        refuse('snapshot_abi_unsupported',
               f'{what}: compiled sceneSize {size!r} != derived ABI v{abi["version"]} '
               f'({abi["bytes"]} bytes, {abi["maxEntities"]} entities)')


def runtime_profile() -> dict:
    """runtime-profile.json: the pinned kind-17 component facts. A plain file read."""
    return json.loads((HERE / 'runtime-profile.json').read_text(encoding='utf-8'))


def component_profile(kind: int, overlay=None, supplied=None) -> dict:
    """The reviewed kind profile that supplies class slots, call targets and properties."""
    if kind not in PRIMITIVE_KINDS:
        refuse('kind_unsupported_by_primitive',
               f'kind {kind}: component_attachment.cpp:173 accepts only 17/33/35')
    if isinstance(supplied, dict):
        values = dict(supplied)
        name = 'spec:componentValues'
    elif kind == PROFILED_KIND:
        component = runtime_profile().get('component')
        if not isinstance(component, dict) or component.get('kind') != PROFILED_KIND:
            raise BuildError('COMPONENT_PROFILE_DRIFT: runtime-profile.json component.kind')
        values = {key: component[key] for key in (
            'classDefinition', 'classSlot', 'optionDefinition', 'optionSlot',
            'colliderDefinition', 'colliderSlot', 'optionListAddRva', 'optionListAddMethodInfoSlot',
            'colliderShape', 'sphereRadius', 'initialActiveProperty', 'captionProperty')
            if key in component}
        values.update({key: value for key, (value, _) in PINNED_DATA_SLOTS.items()})
        if float(values['sphereRadius']) != DEFAULT_RADIUS:
            raise BuildError('RADIUS_PROFILE_DRIFT: runtime-profile.json component.sphereRadius')
        name = 'runtime-profile.json:component'
    else:
        kinds = (overlay or {}).get('kinds') if isinstance(overlay, dict) else None
        entry = kinds.get(str(kind)) if isinstance(kinds, dict) else None
        if not isinstance(entry, dict):
            refuse('kind_not_profiled',
                   f'kind {kind} has no reviewed component profile; runtime-profile.json only profiles 17. '
                   f'Supply --component-profile with kinds["{kind}"] carrying every key of '
                   f'REQUIRED_COMPONENT_KEYS (owner_notification_calls.cpp:43 gives the class slot for '
                   f'33/35; nothing gives their option/collider offsets)')
        values = dict(entry)
        name = 'component-profile:' + str((overlay or {}).get('source', 'overlay'))
    missing = [key for key in REQUIRED_COMPONENT_KEYS if key not in values]
    if missing:
        if kind == PROFILED_KIND and not isinstance(supplied, dict):
            raise BuildError('COMPONENT_PROFILE_INCOMPLETE:' + ','.join(missing))
        refuse('kind_not_profiled', f'kind {kind} profile misses ' + ','.join(missing))
    return {'name': name, 'kind': kind, 'values': values}


def has_chinese(text: str) -> bool:
    return any(CJK_START <= ord(ch) < CJK_STOP for ch in text)


def validate_spec(spec, overlay=None) -> dict:
    """Validate and normalize one parameter table. Every refusal has a named code."""
    if not isinstance(spec, dict):
        refuse('spec_not_object', type(spec).__name__)
    if spec.get('schemaVersion') != SPEC_SCHEMA_VERSION:
        refuse('spec_schema_version', repr(spec.get('schemaVersion')))
    if spec.get('action') != SPEC_ACTION:
        refuse('spec_action_mismatch', repr(spec.get('action')))
    level = spec.get('levelId')
    if type(level) is not int or not 0 < level <= 0xffffffff:
        refuse('level_id_invalid', repr(level))
    evidence = spec.get('levelIdEvidence')
    if not isinstance(evidence, str) or not evidence.strip():
        # The level is a parameter, but never a bare number: the spec must say where the
        # id was observed. This is the anti-blind-write guard for the level.
        refuse('level_evidence_required', 'levelIdEvidence must be a non-empty observation reference')
    kind = spec.get('kind', DEFAULT_KIND)
    if type(kind) is not int:
        refuse('kind_invalid', repr(kind))
    profile = component_profile(kind, overlay, spec.get('componentValues'))
    radius = spec.get('radius', DEFAULT_RADIUS)
    if type(radius) is not float or not math.isfinite(radius) or radius <= 0:
        refuse('radius_invalid', repr(radius))
    if struct.unpack('<f', struct.pack('<f', radius))[0] != radius:
        # The receipt compares the readback with the compiled literal by equality and the
        # verifier compares it with this float, so only float32-exact radii survive.
        refuse('radius_not_float32', repr(radius))
    hosts = spec.get('hosts')
    if not isinstance(hosts, list) or not hosts:
        refuse('hosts_required', 'hosts must be a non-empty list')
    if len(hosts) > MAX_HOSTS:
        refuse('host_limit_exceeded', f'{len(hosts)} hosts > {MAX_HOSTS} receipt slots')
    seen_hosts = set()
    normalized_hosts = []
    for position, host in enumerate(hosts):
        if not isinstance(host, dict):
            refuse('host_not_object', f'hosts[{position}]')
        entity = host.get('entityId')
        if type(entity) is not int or not 0 < entity <= 0xffffffff:
            refuse('host_entity_id_invalid', f'hosts[{position}].entityId={entity!r}')
        if entity in seen_hosts:
            refuse('host_entity_duplicate', str(entity))
        seen_hosts.add(entity)
        options = host.get('options')
        if not isinstance(options, list) or not options:
            refuse('options_required', f'hosts[{position}].options')
        if len(options) > MAX_OPTIONS_PER_HOST:
            refuse('option_limit_exceeded', f'hosts[{position}]: {len(options)} > {MAX_OPTIONS_PER_HOST}')
        seen_index = set()
        enabled_count = 0
        normalized_options = []
        for option_position, option in enumerate(options):
            where = f'hosts[{position}].options[{option_position}]'
            if not isinstance(option, dict):
                refuse('option_not_object', where)
            index = option.get('index')
            if type(index) is not int or not 1 <= index <= 255:
                refuse('option_index_invalid', f'{where}.index={index!r}')
            if index in seen_index:
                refuse('option_index_duplicate', f'{where}.index={index}')
            seen_index.add(index)
            text = option.get('text')
            if not isinstance(text, str) or not text.strip():
                refuse('option_text_required', where)
            if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in text):
                refuse('option_text_not_printable', f'{where}: control character in the Chinese label')
            try:
                units = len(text.encode('utf-16-le')) // 2
            except UnicodeEncodeError as error:
                refuse('option_text_not_utf16', f'{where}: {error}')
            if units >= MAX_TEXT_UNITS:
                refuse('option_text_too_long', f'{where}: {units} UTF-16 units >= {MAX_TEXT_UNITS}')
            if not has_chinese(text):
                refuse('option_text_not_chinese', f'{where}: {text!r}')
            enabled = option.get('enabled')
            if type(enabled) is not bool:
                refuse('option_enabled_invalid', f'{where}.enabled={enabled!r}')
            if enabled:
                enabled_count += 1
            normalized_options.append({'index': index, 'text': text, 'enabled': enabled})
        # One boolean per card; the only boolean the verified primitive writes
        # (native_tabs.cpp:107, property 0x3d94f45f) selects the card that starts active.
        # Exactly one per host is the only configuration ever observed on machine: zero or
        # two would be an unverified shape, so it is refused rather than guessed.
        if enabled_count != 1:
            refuse('option_enabled_count_invalid',
                   f'hosts[{position}]: {enabled_count} enabled cards, exactly 1 is required')
        normalized_options.sort(key=lambda item: item['index'])
        normalized_hosts.append({'entityId': entity, 'ref': host.get('ref'), 'options': normalized_options})
    return {
        'schemaVersion': SPEC_SCHEMA_VERSION,
        'action': SPEC_ACTION,
        'levelId': level,
        'levelIdEvidence': evidence,
        'kind': kind,
        'radius': radius,
        'componentProfile': spec.get('componentProfile') or profile['name'],
        'componentValues': profile['values'],
        'hosts': normalized_hosts,
    }


def unanchored_call_rvas(runtime: dict) -> list:
    """Call macros whose RVA is not one of the code anchors runtime-profile.json pins.

    The macro values are C++ literals ('0x867c610ULL'), so they are read with
    numeric_literal() instead of int(..., 16): the integer parse used to raise
    `ValueError: invalid literal for int() with base 16: '0x867c610ULL'` on the first entry,
    which made every build fail before anything was compiled (found 2026-10-17 by the
    kind17 dual-ABI self-check, which is the first caller that actually runs build()).
    """
    known = {int(entry['rva'], 16) for entry in runtime.get('functions', [])}
    return [name for name, value, _ in CALL_RVA_MACROS if numeric_literal(value) not in known]


def cpp_float(value: float) -> str:
    text = repr(float(value))
    if '.' not in text and 'e' not in text and 'E' not in text:
        text += '.0'
    return text + 'f'


def cpp_narrow(text: str) -> str:
    """Guard the generated literal: the validator already refused these characters."""
    if any(ch in text for ch in ('"', '\\')) or any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in text):
        raise BuildError('SPEC_LITERAL_UNSAFE: ' + repr(text))
    return text


def host_table_cpp(normalized: dict) -> str:
    rows = []
    for host in normalized['hosts']:
        options = ', '.join(
            '{' + f"{option['index']}, {1 if option['enabled'] else 0}u, u\"{cpp_narrow(option['text'])}\"" + '}'
            for option in host['options'])
        rows.append('{' + f"{host['entityId']}ULL, {len(host['options'])}u, " + '{' + options + '}' + '}')
    return '#define GT_HOSTS { \\\n    ' + ', \\\n    '.join(rows) + '}'


def numeric_literal(text) -> int:
    """Read a baked hex literal ('0x18baf8c0' or '0x18baf8c0ULL') as a number."""
    match = re.fullmatch(r'0[xX]([0-9a-fA-F]+)(?:[uUlL]{0,3})', str(text).strip())
    if match is None:
        raise BuildError('COMPONENT_PROFILE_VALUE_NOT_A_LITERAL:' + repr(text))
    return int(match.group(1), 16)


def macro_lines(normalized: dict, runtime: dict, raw: bytes) -> list:
    lines = [
        f'#define GT_LEVEL_ID {normalized["levelId"]}ULL',
        f'#define GT_KIND {normalized["kind"]}',
        f'#define GT_RADIUS {cpp_float(normalized["radius"])}',
        f'#define GT_HOST_COUNT {len(normalized["hosts"])}ULL',
        host_table_cpp(normalized),
        '#define GT_CODE_RVAS ' + ','.join(entry['rva'] for entry in runtime['functions']),
        '#define GT_CODE_BYTES ' + ','.join(
            '{' + ','.join(hex(byte) for byte in bytes.fromhex(entry['head32'])) + '}'
            for entry in runtime['functions']),
        '#define GT_HOTFIX_RVAS ' + ','.join(runtime['hotfixZeroRvas']),
        '#define GT_USAGE_GROUPS ' + ','.join(runtime['usageGroups']),
    ]
    anchored = {}
    for macro, value, provenance in CALL_RVA_MACROS:
        anchored[macro] = value
        lines.append(f'#define {macro} {value} /* {provenance} */')
    values = component_profile(normalized['kind'], None, normalized.get('componentValues'))['values']
    for key in REQUIRED_COMPONENT_KEYS:
        macro = 'GT_' + MACRO_SUFFIX[key]
        if macro in anchored:
            # The reviewed call table owns this name; the profile must agree with it
            # instead of silently redefining the macro (MSVC C4005 is fatal under /WX).
            if numeric_literal(values[key]) != numeric_literal(anchored[macro]):
                raise BuildError('COMPONENT_PROFILE_CALL_RVA_DISAGREES:' + macro)
            continue
        lines.append(f'#define {macro} {values[key]}')
    abi = derived_snapshot_abi(raw, 'compiled expected snapshot')
    lines.append('// snapshot ABI v' + str(abi['version']) + ': ' + str(abi['bytes'])
                 + ' bytes = 184 + 32*8 + ' + str(abi['maxEntities']) + '*64 (decode_context_snapshot.py)')
    lines.append('inline constexpr unsigned char kGtExpected[]={')
    lines.append('\n'.join(','.join(str(byte) for byte in raw[index:index + 40]) + ','
                           for index in range(0, len(raw), 40)))
    lines.append('};')
    lines.append('#define GT_EXPECTED_SNAPSHOT kGtExpected')
    return lines


# Sections of the generated receipt-layout probe. Every value is a *compiler* answer
# (pointer arithmetic on static probe objects), never a number typed here.
LAYOUT_SECTIONS = {
    'receipt': ('receiptProbe', (
        ('size', None), ('hosts', 'hosts'), ('hostStride', None), ('hostSlots', None),
        ('maxHosts', None), ('maxOptionsPerHost', None), ('maxTextUnits', None), ('sceneSize', None),
        ('version', 'version'), ('status', 'status'), ('stage', 'stage'), ('sehCode', 'sehCode'),
        ('attempted', 'attempted'), ('sceneUnchanged', 'sceneUnchanged'),
        ('failedRva', 'failedRva'), ('failedValue', 'failedValue'), ('metadataCalls', 'metadataCalls'),
        ('completedHosts', 'completedHosts'), ('refuseCode', 'refuseCode'), ('refuseStage', 'refuseStage'),
        ('refuseHost', 'refuseHost'), ('refuseOption', 'refuseOption'),
        ('hostCount', 'hostCount'), ('kind', 'kind'), ('expectedLevelId', 'expectedLevelId'),
        ('levelIdBefore', 'levelIdBefore'), ('levelIdAfter', 'levelIdAfter'), ('radius', 'radius'),
        ('expectedScene', 'expectedScene'), ('afterScene', 'afterScene'),
    )),
    'host': ('hostProbe', (
        ('size', None), ('options', 'options'), ('optionSlots', None),
        ('entityId', 'entityId'), ('status', 'status'), ('refuseCode', 'refuseCode'),
        ('refuseStage', 'refuseStage'), ('refuseOption', 'refuseOption'),
        ('optionCount', 'optionCount'), ('colliderCount', 'colliderCount'),
        ('readbackVerified', 'readbackVerified'), ('textVerified', 'textVerified'),
        ('radiusVerified', 'radiusVerified'), ('componentKind', 'componentKind'),
        ('kindRowsFound', 'kindRowsFound'), ('kindRowIndex', 'kindRowIndex'),
        ('kindRowMatchesConfig', 'kindRowMatchesConfig'), ('kindRowEnabled', 'kindRowEnabled'),
        ('owner', 'owner'), ('ownerClass', 'ownerClass'), ('config', 'config'),
        ('collider', 'collider'), ('sphere', 'sphere'), ('colliderShape', 'colliderShape'),
        ('radius', 'radius'), ('beforeComponents', 'beforeComponents'),
        ('afterComponents', 'afterComponents'),
        ('attachmentCode', 'attachment.code'), ('editCode', 'edit.code'),
    )),
    'option': ('optionProbe', (
        ('size', None), ('pointer', 'pointer'), ('klass', 'klass'), ('index', 'index'),
        ('sort', 'sort'), ('textLength', 'textLength'), ('icon', 'icon'), ('filter', 'filter'),
        ('activeOrEnabledState', 'activeOrEnabledState'), ('rowEnabledByte', 'rowEnabledByte'),
        ('text', 'text'), ('expectedIndex', 'expectedIndex'), ('expectedEnabled', 'expectedEnabled'),
        ('indexMatched', 'indexMatched'), ('enabledMatched', 'enabledMatched'),
        ('textMatched', 'textMatched'), ('expectedTextUnits', 'expectedTextUnits'),
        ('mismatchUnit', 'mismatchUnit'),
    )),
}

# Extra compile-time values the receipt section carries (sizes and capacities).
LAYOUT_CONSTANTS = (('size', 'sizeof(gt::NativeGeneralizedTabsReceipt)'),
                    ('hostStride', 'sizeof(gt::HostResult)'),
                    ('hostSlots', 'sizeof(receiptProbe.hosts) / sizeof(gt::HostResult)'),
                    ('maxHosts', 'gt::kMaxHosts'),
                    ('maxOptionsPerHost', 'gt::kMaxOptionsPerHost'),
                    ('maxTextUnits', 'gt::kMaxTextUnits'),
                    ('sceneSize', 'sizeof(GameContextSnapshot)'))


# Keys check_layout() insists on after a real compile; the offline checker compares them
# against layout_keys() so a verifier/builder field cannot go missing unnoticed.
REQUIRED_LAYOUT_KEYS = {
    'receipt': ('size', 'hosts', 'hostStride', 'hostSlots', 'maxHosts', 'maxOptionsPerHost',
                'maxTextUnits', 'sceneSize', 'refuseCode', 'refuseStage', 'refuseHost',
                'refuseOption', 'hostCount', 'kind', 'expectedLevelId', 'levelIdBefore',
                'levelIdAfter', 'status', 'sehCode', 'completedHosts', 'sceneUnchanged',
                'attempted', 'metadataCalls', 'radius', 'version'),
    'host': ('size', 'options', 'optionSlots', 'attachmentCode', 'editCode', 'componentKind',
             'kindRowsFound', 'kindRowMatchesConfig', 'optionCount', 'colliderCount', 'radius',
             'colliderShape', 'readbackVerified', 'textVerified'),
    'option': ('size', 'text', 'textLength', 'index', 'expectedIndex', 'expectedEnabled',
               'activeOrEnabledState', 'rowEnabledByte', 'indexMatched', 'enabledMatched',
               'textMatched', 'expectedTextUnits', 'mismatchUnit'),
}


def layout_keys() -> dict:
    """Exactly the JSON keys the generated probe prints, by section.

    The offline checker compares the keys verify_generalized_receipt.py asks for against
    this set, so a verifier field that the probe does not print is caught without a
    compile.
    """
    keys = {}
    for name, (_probe, fields) in LAYOUT_SECTIONS.items():
        printed = {key for key, member in fields if member is not None}
        if name == 'receipt':
            printed.update(key for key, _expression in LAYOUT_CONSTANTS)
        if name == 'host':
            printed.update(('size', 'optionSlots'))
        if name == 'option':
            printed.add('size')
        keys[name] = printed
    return keys


def layout_source() -> str:
    """The receipt-layout probe the verifier reads its offsets from."""
    sections = []
    for name, (probe, fields) in LAYOUT_SECTIONS.items():
        body = ['    { bool first = true; std::printf("\\"' + name + '\\":{");']
        if name == 'receipt':
            for key, expression in LAYOUT_CONSTANTS:
                body.append(f'        GT_LAYOUT_FIELD("{key}", {expression});')
        if name == 'host':
            body.append('        GT_LAYOUT_FIELD("size", sizeof(gt::HostResult));')
            body.append('        GT_LAYOUT_FIELD("optionSlots", sizeof(hostProbe.options) / sizeof(gt::OptionRow));')
        if name == 'option':
            body.append('        GT_LAYOUT_FIELD("size", sizeof(gt::OptionRow));')
        for key, member in fields:
            if member is None:
                continue
            body.append(f'        GT_LAYOUT_FIELD("{key}", GT_OFF({probe}, {member}));')
        body.append('        std::printf("}"); }')
        sections.append('\n'.join(body))
    joined = '\n    std::printf(",");\n'.join(sections)
    head = (
        '// Generated by build_generalized.py: the compiler prints the receipt ABI.\n'
        '// verify_generalized_receipt.py refuses to decode without this table.\n'
        '#include <cstdio>\n'
        '#include <cstddef>\n'
        '#include "../native-options/generalized_tabs.h"\n'
        'static gt::NativeGeneralizedTabsReceipt receiptProbe;\n'
        'static gt::HostResult hostProbe;\n'
        'static gt::OptionRow optionProbe;\n'
        '#pragma warning(push)\n'
        '#pragma warning(disable : 4127) // do/while(0) in the two generated macros below\n'
        '#define GT_OFF(object, member) '
        '(reinterpret_cast<const char*>(&((object).member)) - reinterpret_cast<const char*>(&(object)))\n'
        '#define GT_LAYOUT_FIELD(name, value) do { std::printf("%s\\"%s\\":%zu", first ? "" : ",", name, '
        'static_cast<std::size_t>(value)); first = false; } while (0);\n'
        'int main() {\n'
        '    std::printf("{");\n'
        # No leading comma: the object opener has just been printed, so a comma here makes the
        # whole table invalid JSON ("{,\"actionCode\":...") and check_layout() can never read
        # it. Found 2026-10-17 by the kind17 dual-ABI self-check, the first run that actually
        # executed this generator (every earlier build died before compiling).
        '    std::printf("\\"actionCode\\":%d,\\"receiptVersion\\":%d,'
        '\\"provenance\\":\\"compiler-offsets\\"", '
    )
    tail = (
        '\n    std::printf(",\\"codes\\":{\\"attach_attached_verified\\":%u,\\"attach_existing\\":%u,"\n'
        '        "\\"capture_complete\\":%u,\\"edit_snapshot_ready\\":%u,\\"edit_complete\\":%u}",\n'
        '        static_cast<unsigned>(ge::component_attachment::AttachCode::attached_verified),\n'
        '        static_cast<unsigned>(ge::component_attachment::AttachCode::existing),\n'
        '        static_cast<unsigned>(ge::component_attachment::CaptureCode::complete),\n'
        '        static_cast<unsigned>(ge::component_edit::Code::snapshot_ready),\n'
        '        static_cast<unsigned>(ge::component_edit::Code::complete));\n'
        '    std::printf(",\\"refuseCodes\\":{");\n'
        '    bool firstCode = true;\n'
        '#define GT_REFUSE_JSON(name, value, phase) do { std::printf('
        '"%s\\"%u\\":{\\"name\\":\\"%s\\",\\"phase\\":\\"%s\\"}", firstCode ? "" : ",", '
        'static_cast<unsigned>(gt::RefuseCode::name), #name, #phase); firstCode = false; } while (0);\n'
        '    GT_REFUSE_CODES(GT_REFUSE_JSON)\n'
        '#undef GT_REFUSE_JSON\n'
        '    std::printf("}");\n'
        '    std::printf("}\\n");\n'
        '    return 0;\n'
        '}\n'
        '#pragma warning(pop)\n'
    )
    return head + str(ACTION_CODE) + ', ' + str(RECEIPT_VERSION) + ');\n    std::printf(",");\n' + joined + tail


def replace(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        raise BuildError('SOURCE_PATTERN_CHANGED:' + what + ':' + old[:60])
    return text.replace(old, new, 1)


def replace_or_confirm(text: str, old: str, new: str, what: str) -> str:
    """Idempotent form for a fix already present in the shared source.

    native-options/build.py:44 still replaces '    *receipt = {};' with the memset, but
    hook_receipt_probe.cpp already carries the memset, so that replacement now fails
    closed there. We confirm the intended end state instead of pretending to edit it.
    """
    if text.count(old) == 1:
        return text.replace(old, new, 1)
    if text.count(new) >= 1:
        return text
    raise BuildError('SOURCE_PATTERN_CHANGED:' + what)


PROBE_OUTPUT = r'''const auto& tab=receipt->tabs;
                std::printf(",\"generalizedTabs\":{\"status\":%u,\"stage\":%u,\"sehCode\":%u,\"refuseCode\":%u,\"refuseStage\":%u,\"refuseHost\":%u,\"refuseOption\":%u,\"hostCount\":%u,\"completedHosts\":%u,\"attempted\":%u,\"sceneUnchanged\":%u,\"failedRva\":%u,\"failedValue\":%u,\"expectedLevelId\":%u,\"levelIdBefore\":%u,\"levelIdAfter\":%u,\"kind\":%u,\"radius\":%.9g,\"metadataCalls\":%u}",tab.status,tab.stage,tab.sehCode,tab.refuseCode,tab.refuseStage,tab.refuseHost,tab.refuseOption,tab.hostCount,tab.completedHosts,tab.attempted,tab.sceneUnchanged,tab.failedRva,tab.failedValue,tab.expectedLevelId,tab.levelIdBefore,tab.levelIdAfter,tab.kind,static_cast<double>(tab.radius),tab.metadataCalls);
                std::printf(",\"generalizedHosts\":[");
                for(std::uint32_t i=0;i<tab.hostCount&&i<gt::kMaxHosts;++i){const auto& h=tab.hosts[i];
                    std::printf("%s{\"entityId\":%u,\"status\":%u,\"refuseCode\":%u,\"refuseStage\":%u,\"refuseOption\":%u,\"optionCount\":%u,\"colliderCount\":%u,\"componentKind\":%u,\"kindRowsFound\":%u,\"kindRowMatchesConfig\":%u,\"kindRowEnabled\":%u,\"attachCode\":%u,\"editCode\":%u,\"readbackVerified\":%u,\"textVerified\":%u,\"radiusVerified\":%u,\"options\":[",i?",":"",h.entityId,h.status,h.refuseCode,h.refuseStage,h.refuseOption,h.optionCount,h.colliderCount,h.componentKind,h.kindRowsFound,h.kindRowMatchesConfig,h.kindRowEnabled,static_cast<unsigned>(h.attachment.code),static_cast<unsigned>(h.edit.code),h.readbackVerified,h.textVerified,h.radiusVerified);
                    for(std::uint32_t j=0;j<h.optionCount&&j<gt::kMaxOptionsPerHost;++j){const auto& o=h.options[j];
                        std::printf("%s{\"index\":%d,\"expectedIndex\":%d,\"textLength\":%d,\"expectedTextUnits\":%u,\"activeOrEnabledState\":%u,\"rowEnabledByte\":%u,\"expectedEnabled\":%u,\"indexMatched\":%u,\"enabledMatched\":%u,\"textMatched\":%u,\"mismatchUnit\":%u}",j?",":"",o.index,o.expectedIndex,o.textLength,o.expectedTextUnits,static_cast<unsigned>(o.activeOrEnabledState),static_cast<unsigned>(o.rowEnabledByte),o.expectedEnabled,o.indexMatched,o.enabledMatched,o.textMatched,o.mismatchUnit);}
                    std::printf("]}");}
                std::printf("]");
                std::printf(",\"generalizedTabsBytes\":%zu,\"generalizedTabsHex\":\"",sizeof(tab));
                const auto tabBytes=reinterpret_cast<const unsigned char*>(&tab);
                for(std::size_t i=0;i<sizeof(tab);++i)std::printf("%02x",static_cast<unsigned>(tabBytes[i]));
                std::printf("\"");
                std::printf(",\"afterSceneBytes\":%zu,\"afterSceneHex\":\"",sizeof(tab.afterScene));
                const auto afterSceneBytes=reinterpret_cast<const unsigned char*>(&tab.afterScene);
                for(std::size_t i=0;i<sizeof(tab.afterScene);++i)std::printf("%02x",static_cast<unsigned>(afterSceneBytes[i]));
                std::printf("\"");
'''

CONTEXT_ANCHOR = ('(HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && '
                  'HR_REOPEN_ACTION_REVIEWED == 1))')


def source_edits() -> dict:
    """Every edit applied to the copied shared sources, keyed by file name."""
    return {
        'game_context_snapshot.h': [(CONTEXT_ANCHOR,
            CONTEXT_ANCHOR[:-1] + ' && !(HR_ACTION == 13 && defined(TA_GENERALIZED_TABS_REVIEWED) && '
            'TA_GENERALIZED_TABS_REVIEWED == 1))')],
        'hook_receipt_protocol.h': [
            ('#if HR_ACTION\n#include "game_scene_action.h"',
             '#if HR_ACTION == 13\n#include "../native-options/generalized_tabs.h"\n#elif HR_ACTION\n'
             '#include "game_scene_action.h"'),
            ('#if HR_ACTION\n    GameSceneActionResult action;',
             '#if HR_ACTION == 13\n    gt::NativeGeneralizedTabsReceipt tabs;\n#elif HR_ACTION\n'
             '    GameSceneActionResult action;'),
            ('constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS',
             f'constexpr DWORD kReceiptVersion = HR_ACTION == 13 ? {RECEIPT_VERSION} : HR_READ_REOPEN_GUARDS'),
        ],
        'hook_receipt.cpp': [
            ('#if HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);',
             '#if HR_ACTION == 13\n                    ExecuteGeneralizedTabAction(&receipt->context, &receipt->tabs);\n'
             '#elif HR_ACTION\n                    ExecuteGameSceneAction(&receipt->context, &receipt->action);'),
        ],
        'hook_receipt_probe.cpp': [
            ('#if HR_ACTION < 1 || HR_ACTION > 3',
             '#if HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 13 && defined(TA_GENERALIZED_TABS_REVIEWED) '
             '&& TA_GENERALIZED_TABS_REVIEWED == 1))'),
            ('#if HR_ACTION\n                reportedOk = reportedOk && receipt->action.status',
             '#if HR_ACTION == 13\n                reportedOk = reportedOk && receipt->tabs.status == 0 && '
             'receipt->tabs.sehCode == 0 && receipt->tabs.refuseCode == 0 && '
             'receipt->tabs.completedHosts == receipt->tabs.hostCount && receipt->tabs.sceneUnchanged == 1;\n'
             '#elif HR_ACTION\n                reportedOk = reportedOk && receipt->action.status'),
            ('HR_ACTION ? "FIXED_SCENE_ACTION"',
             'HR_ACTION == 13 ? "FIXED_GENERALIZED_TABS_ACTION" : HR_ACTION ? "FIXED_SCENE_ACTION"'),
            ('#if HR_ACTION\n                std::printf(",\\"action\\":',
             '#if HR_ACTION == 13\n                ' + PROBE_OUTPUT
             + '#elif HR_ACTION\n                std::printf(",\\"action\\":'),
        ],
    }


PROBE_MEMSET_OLD = '    *receipt = {};'
PROBE_MEMSET_NEW = '    std::memset(receipt, 0, sizeof(*receipt));'

SOURCE_GROUPS = {
    'native': (EX / 'native', None),
    'template-authoring': (EX / 'template-authoring', (
        'component_attachment.h', 'component_attachment.cpp', 'template_catalog_capture.h',
        'template_catalog.h', 'owner_notification_calls.h', 'owner_notification_calls.cpp')),
    'native-options': (HERE, ('generalized_tabs.h', 'generalized_tabs.cpp')),
}


def sources(run, ro, p) -> dict:
    hashes = {}
    for folder, (origin, names) in SOURCE_GROUPS.items():
        resolved = ro.SOURCES if names is None else names
        dest = run / 'candidate-source' / folder
        dest.mkdir(parents=True)
        for name in resolved:
            path = origin / name
            hashes[path.relative_to(ROOT).as_posix()] = p.sha256(path)
            (dest / name).write_bytes(path.read_bytes())
    for name, changes in source_edits().items():
        path = run / 'candidate-source/native' / name
        text = path.read_text(encoding='utf-8')
        for old, new in changes:
            text = replace(text, old, new, name)
        path.write_text(text, encoding='utf-8')
    probe = run / 'candidate-source/native/hook_receipt_probe.cpp'
    probe.write_text(replace_or_confirm(probe.read_text(encoding='utf-8'), PROBE_MEMSET_OLD,
                                        PROBE_MEMSET_NEW, 'hook_receipt_probe.cpp'), encoding='utf-8')
    generated = run / 'candidate-source/generalized'
    generated.mkdir(parents=True)
    (generated / 'receipt_layout.cpp').write_text(layout_source(), encoding='utf-8')
    return hashes


def header(run, profile, runtime, normalized, ro, p, session=None, raw=None, abi=None) -> int:
    """Bake target_config.h. `raw` is always a payload of `abi`, placeholder or baseline.

    `abi` decides the compiled snapshot layout: GS_LARGE_SCENE is set from the ABI's own
    `largeScene`, so "the bytes we baked" and "the struct this translation unit compiles"
    cannot be two different shapes (game_context_snapshot.h:75-92).
    """
    session = session or dict(pid=1, tid=1, processCreation=1, threadCreation=1,
                              image=str(run / 'compile-only.invalid'))
    launchable = raw is not None
    if abi is None:
        abi = dict(SNAPSHOT_ABIS[HISTORICAL_SNAPSHOT_VERSION], source='compile-default')
    if raw is None:
        # Compile-only placeholder: exactly this ABI's byte count, never a literal.
        raw = bytes(abi['bytes'])
    abi = derived_snapshot_abi(raw, abi['source'])
    kernel, user = p.windows_api()
    deadline = int(kernel.GetTickCount64()) + 600000 if launchable else 1
    message = int(user.RegisterWindowMessageW(PROBE_URL_MESSAGE + secrets.token_hex(12))) if launchable else 0xc001
    ro.emit_header(profile, session, run, deadline=deadline, message_id=message,
                   nonce=secrets.randbits(63) | 1, large_scene=bool(abi['largeScene']))
    target = run / 'target_config.h'
    text = target.read_text(encoding='utf-8')
    text = replace(text, '#define HR_ACTION 0ULL', f'#define HR_ACTION {ACTION_CODE}ULL', 'target_config.h')
    text = replace(text, '#define GS_BOOTSTRAP_READONLY 1ULL', '#define GS_BOOTSTRAP_READONLY 0ULL', 'target_config.h')
    text += ('\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n'
             '#define TA_GENERALIZED_TABS_REVIEWED 1\n')
    text += '\n'.join(macro_lines(normalized, runtime, raw)) + '\n'
    target.write_text(text, encoding='utf-8')
    return deadline


def tool_path() -> None:
    """build_readonly_profile / native_profiles live one directory up."""
    if str(EX) not in sys.path:
        sys.path.insert(0, str(EX))


def compile_run(run, *, layout_only: bool = False) -> None:
    tool_path()
    import native_profiles as p
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    p.require(vswhere.is_file(), 'MSVC_VSWHERE_MISSING:' + str(vswhere))
    vs = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
                                  'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
                                  '-property', 'installationPath'], text=True).strip()
    vc = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
    p.require(vc.is_file(), 'MSVC_REQUIRED')
    common = f'cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"{run / "target_config.h"}" '
    lines = ['@echo off', f'call "{vc}" >nul', 'if errorlevel 1 exit /b 1']
    objects = []
    units = [] if layout_only else [
        ('native', 'game_context_snapshot'),
        ('template-authoring', 'component_attachment'),
        ('template-authoring', 'owner_notification_calls'),
        ('native-options', 'generalized_tabs')]
    for folder, name in units:
        obj = run / (name + '.obj')
        objects.append(obj)
        lines += [common + f'/c "{run / "candidate-source" / folder / (name + ".cpp")}" /Fo:"{obj}"',
                  'if errorlevel 1 exit /b 1']
    if not layout_only:
        lines += [common + f'/LD "{run / "candidate-source/native/hook_receipt.cpp"}" '
                          f'/Fo:"{run / "hook.obj"}" /Fe:"{run / "hook_receipt.dll"}" /link User32.lib '
                          + ' '.join('"' + str(item) + '"' for item in objects),
                  'if errorlevel 1 exit /b 1',
                  common + f'"{run / "candidate-source/native/hook_receipt_probe.cpp"}" '
                           f'/Fo:"{run / "probe.obj"}" /Fe:"{run / "hook_receipt_probe.exe"}" '
                           f'/link User32.lib Advapi32.lib',
                  'if errorlevel 1 exit /b 1']
    lines += [common + f'"{run / "candidate-source/generalized/receipt_layout.cpp"}" '
                      f'/Fe:"{run / "receipt_layout.exe"}"',
              'if errorlevel 1 exit /b 1',
              f'"{run / "receipt_layout.exe"}" > "{run / "receipt-layout.json"}"',
              'if errorlevel 1 exit /b 1']
    (run / 'build.cmd').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    result = subprocess.run(['cmd.exe', '/d', '/c', str(run / 'build.cmd')], cwd=run,
                            capture_output=True, text=True, timeout=300)
    (run / 'build.log').write_text((result.stdout or '') + (result.stderr or ''), encoding='utf-8')
    p.require(result.returncode == 0, 'BUILD_FAILED:' + str(run / 'build.log'))
    layout_path = run / 'receipt-layout.json'
    p.require(layout_path.is_file(), 'LAYOUT_PROBE_MISSING')
    check_layout(json.loads(layout_path.read_text(encoding='utf-8')))


def check_layout(layout) -> None:
    """Fail closed when the compiler's receipt ABI disagrees with this file."""
    if not isinstance(layout, dict):
        raise BuildError('LAYOUT_INCOMPLETE: not an object')
    for section, keys in REQUIRED_LAYOUT_KEYS.items():
        block = layout.get(section)
        if not isinstance(block, dict):
            raise BuildError('LAYOUT_INCOMPLETE:' + section)
        missing = [key for key in keys if key not in block]
        if missing:
            raise BuildError('LAYOUT_INCOMPLETE:' + section + ':' + ','.join(missing))
    if layout.get('actionCode') != ACTION_CODE or layout.get('receiptVersion') != RECEIPT_VERSION:
        raise BuildError('LAYOUT_ACTION_DRIFT')
    for key, expected, reason in (('maxHosts', MAX_HOSTS, 'HOST_LIMIT_DRIFT'),
                                  ('hostSlots', MAX_HOSTS, 'HOST_LIMIT_DRIFT'),
                                  ('maxOptionsPerHost', MAX_OPTIONS_PER_HOST, 'OPTION_LIMIT_DRIFT'),
                                  ('maxTextUnits', MAX_TEXT_UNITS, 'TEXT_UNIT_DRIFT')):
        if layout['receipt'].get(key) != expected:
            raise BuildError(f'{reason}:{key}={layout["receipt"].get(key)} expected {expected}')
    codes = layout.get('refuseCodes')
    if not isinstance(codes, dict):
        raise BuildError('LAYOUT_REFUSE_TABLE_MISSING')
    names = [entry['name'] for entry in codes.values() if isinstance(entry, dict)]
    if names != [entry[0] for entry in refusal_codes()]:
        raise BuildError('LAYOUT_REFUSE_TABLE_DRIFT')
    kind_codes = layout.get('codes')
    for key in ('attach_attached_verified', 'attach_existing', 'capture_complete',
                'edit_snapshot_ready', 'edit_complete'):
        if not isinstance(kind_codes, dict) or type(kind_codes.get(key)) is not int:
            raise BuildError('LAYOUT_CODE_TABLE_INVALID:' + key)


def baseline_inputs(baseline, normalized, p, ro):
    """Decode a fresh readonly baseline: the declared level, the hosts and the .gil backup.

    The baseline payload also decides the snapshot ABI: its own header (structSize/version)
    is decoded twice -- once by the decoder's decode_snapshot and once by the shared
    derivation -- and the two must agree, so a snapshot cannot be read under one layout and
    baked under another.
    """
    baseline = Path(baseline).resolve()
    verification = ro.decode_run(baseline)
    p.require(verification['ok'], 'BASELINE_NOT_VALID')
    prepared = ro.read_json(baseline / 'prepared.json')
    session = p.validate_session(prepared['session'])
    record, _ = ro.load_decoder().read_probe(baseline / 'stdout.jsonl')
    snapshot = ro.load_decoder().decode_snapshot(record)
    observed = snapshot['levelObservation']['levelId']
    p.require(observed == normalized['levelId'], f'BASELINE_LEVEL_MISMATCH:{observed}')
    finished = datetime.fromisoformat(ro.read_json(baseline / 'exit.json')['finishedUtc'].replace('Z', '+00:00'))
    p.require(0 <= (datetime.now(timezone.utc) - finished).total_seconds() < 900, 'STALE_BASELINE')
    present = {row['id'] for row in snapshot['entities']}
    wanted = {host['entityId'] for host in normalized['hosts']}
    p.require(wanted <= present,
              'BASELINE_HOSTS_MISSING:' + ','.join(str(item) for item in sorted(wanted - present)))
    raw = bytes.fromhex(record['snapshotHex'])
    abi = derived_snapshot_abi(raw, 'baseline snapshot')
    for field, observed_value in (('structureSize', snapshot['structureSize']),
                                  ('version', snapshot['version'])):
        if abi['bytes' if field == 'structureSize' else 'version'] != observed_value:
            refuse('snapshot_abi_unsupported',
                   f'baseline snapshot: {field} decodes as {observed_value!r}, '
                   f'AIB derivation says {abi["bytes" if field == "structureSize" else "version"]}')
    source = (Path.home() / 'AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/Beyond_Local_Save_Level'
              / str(normalized['levelId']) / f'{normalized["levelId"]}.gil')
    return session, raw, source, abi


def build(args) -> dict:
    tool_path()
    import build_readonly_profile as ro
    import native_profiles as p
    profile = p.load_profile()
    p.verify_disk(profile)
    runtime = runtime_profile()
    p.require(runtime['imageSha256'] == profile['image']['sha256'], 'RUNTIME_IMAGE_DRIFT')
    overlay = None
    if args.component_profile:
        raw_overlay = json.loads(Path(args.component_profile).read_text(encoding='utf-8-sig'))
        p.require(isinstance(raw_overlay, dict), 'COMPONENT_PROFILE_NOT_OBJECT')
        overlay = dict(raw_overlay, source=str(Path(args.component_profile).resolve()))
    spec_path = Path(args.spec).resolve()
    normalized = validate_spec(json.loads(spec_path.read_text(encoding='utf-8-sig')), overlay)
    unanchored = unanchored_call_rvas(runtime)
    p.require(not unanchored, 'CALL_RVA_NOT_ANCHORED:' + ','.join(unanchored))
    # The ABI is chosen before anything is baked: an explicit --snapshot-abi names a reviewed
    # version, a baseline snapshot overrides it with the ABI that snapshot declares, and with
    # neither the compile default is the historical v1 (what the profile compiles). The byte
    # count is never typed here -- it comes from the derivation/registry.
    requested_abi = None if args.snapshot_abi == 'auto' else snapshot_abi_by_selector(args.snapshot_abi)
    abi = requested_abi
    raw = None
    session = None
    recovery = None
    if args.baseline and not args.layout_only:
        session, raw, source_path, baseline_abi = baseline_inputs(args.baseline, normalized, p, ro)
        if requested_abi is not None and requested_abi['version'] != baseline_abi['version']:
            refuse('snapshot_abi_unsupported',
                   f'--snapshot-abi v{requested_abi["version"]} contradicts the baseline snapshot, '
                   f'which declares v{baseline_abi["version"]} ({baseline_abi["size"]} bytes)')
        abi = baseline_abi
        recovery = (source_path, source_path.read_bytes())
    if abi is None:
        abi = dict(SNAPSHOT_ABIS[HISTORICAL_SNAPSHOT_VERSION], source='compile-default')
    if raw is None:
        # Compile-only placeholder of the selected ABI: never a literal byte count, and
        # never a resize of some other snapshot.
        raw = bytes(abi['bytes'])
        abi = derived_snapshot_abi(raw, 'compile-only placeholder')
    launchable = session is not None
    run = ro.output_directory(OUT / ('layout' if args.layout_only else 'prepared' if launchable else 'candidates'))
    hashes = sources(run, ro, p)
    deadline = header(run, profile, runtime, normalized, ro, p, session, raw if launchable else None, abi)
    compile_run(run, layout_only=args.layout_only)
    for name, digest in hashes.items():
        p.require(p.sha256(ROOT / name) == digest, 'SOURCE_CHANGED:' + name)
    (run / 'normalized-spec.json').write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8')
    if launchable:
        p.validate_session(session)
        (run / 'baseline-snapshot.bin').write_bytes(raw)
        source_path, content = recovery
        (run / f'before-{normalized["levelId"]}.gil').write_bytes(content)
        p.require(source_path.read_bytes() == content, 'SOURCE_SAVE_CHANGED')
    layout = json.loads((run / 'receipt-layout.json').read_text(encoding='utf-8'))
    # Dual-ABI self-proof: the compiler prints sizeof(GameContextSnapshot) and it must be the
    # ABI whose payload we just baked. This is what makes "the old ABI does not regress" a
    # compiled fact rather than an assumption.
    require_compiled_scene_size(layout, abi, 'generalized-tabs layout probe')
    result = dict(ok=True, kind='generalized-tabs-build-v1', run=str(run), compiled=True,
                  layoutOnly=bool(args.layout_only), launchable=launchable, compileOnly=not launchable,
                  nativeCalled=False, actionCode=ACTION_CODE, receiptVersion=RECEIPT_VERSION,
                  deadlineTick=deadline, session=session, sourceHashes=hashes,
                  snapshotAbi=dict(abi, requested=args.snapshot_abi, compiledSceneSize=layout['receipt']['sceneSize']),
                  spec=str(spec_path), specSha256=p.sha256(spec_path),
                  normalizedSpecSha256=p.sha256(run / 'normalized-spec.json'),
                  componentProfile=normalized['componentProfile'], hostCount=len(normalized['hosts']),
                  levelId=normalized['levelId'], componentKind=normalized['kind'], radius=normalized['radius'],
                  receiptBytes=layout['receipt']['size'], hostSlots=layout['receipt']['hostSlots'],
                  optionSlots=layout['host']['optionSlots'], optionStride=layout['option']['size'],
                  runtimeSha256=p.sha256(HERE / 'runtime-profile.json'), baseline=args.baseline)
    if launchable:
        expires = datetime.now(timezone.utc) + timedelta(minutes=8)
        pins = {str(ROOT / name): digest for name, digest in hashes.items()}
        pins.update({str(item): p.sha256(item) for item in run.rglob('*') if item.is_file()})
        pins[str(recovery[0])] = p.sha256(recovery[0])
        template_path = (ROOT / '.runtime/scratch/offline-farming-20261014/ui-root-activation'
                         '/invoke-resume-ui.template.ps1')
        p.require(template_path.is_file(), 'WRAPPER_TEMPLATE_MISSING:' + str(template_path))
        template = template_path.read_text(encoding='utf-8')
        template = template.replace('FIXED_UI_Z_RESUME_ACTION', 'FIXED_GENERALIZED_TABS_ACTION')
        template = template.replace('fixed-ui-z-resume-build-v1', 'generalized-tabs-build-v1')
        start = template.index('    $validation=&')
        end = template.index('    $stdout=', start)
        template = template[:start] + template[end:]

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        for key, value in {'@@RUN@@': quote(run), '@@EXPIRES@@': quote(expires.isoformat()),
                           '@@PINS@@': ',\n'.join('    @(' + quote(item) + ',' + quote(digest) + ')'
                                                  for item, digest in sorted(pins.items()))}.items():
            template = template.replace(key, value)
        p.require('@@' not in template, 'WRAPPER_PLACEHOLDER')
        wrapper = run / 'invoke-generalized-tabs.ps1'
        wrapper.write_text(template, encoding='utf-8-sig')
        result.update(wrapper=str(wrapper), wrapperSha256=p.sha256(wrapper), expiresUtc=expires.isoformat())
    result['hashes'] = {item.relative_to(run).as_posix(): p.sha256(item)
                        for item in run.rglob('*') if item.is_file()}
    ro.write_json(run / 'build-result.json', result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True,
                        help='parameter table: hosts[] with Chinese text + index + enabled')
    parser.add_argument('--component-profile', type=Path,
                        help='optional overlay for a kind other than 17')
    parser.add_argument('--baseline', help='fresh readonly run directory (makes the build launchable)')
    parser.add_argument('--snapshot-abi', choices=SNAPSHOT_ABI_CHOICES, default='auto',
                        help='which reviewed snapshot ABI to bake when no --baseline is given '
                             '(--baseline always wins, taken from the snapshot itself); '
                             'auto = the profile default, the historical v1')
    parser.add_argument('--layout-only', action='store_true',
                        help='compile only the receipt layout probe (no hook DLL, no probe)')
    args = parser.parse_args(argv)
    try:
        result = build(args)
    except SpecRefusal as refusal:
        print(json.dumps({'ok': False, 'refused': refusal.code, 'detail': refusal.detail},
                         ensure_ascii=False))
        return 2
    except BuildError as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 3
    print(json.dumps({key: value for key, value in result.items() if key not in ('hashes', 'sourceHashes')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
