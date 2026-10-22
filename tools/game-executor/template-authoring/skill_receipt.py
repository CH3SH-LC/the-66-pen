"""Independent raw skill receipt decoder; no process, native call or save.

MSVC layout: task-bi/skill-layout.json. Transport, compiled profile, callback
identity and scene continuity remain the caller's separate acceptance checks.
"""
from __future__ import annotations
import struct
import receipt as catalogs

RECEIPT_BYTES, SNAPSHOT_BYTES = 894392, 33208
ACTION_AT, EXPECTED_AT, AFTER_AT, WORKSPACE_AT = 16, 120, 33328, 66536
BEFORE_CATALOG_AT, AFTER_CATALOG_AT = 369784, 632088
ACTION = struct.Struct('<4I6Q8I7Bx')
assert ACTION.size == 104 and AFTER_CATALOG_AT + catalogs.CATALOG_BYTES == RECEIPT_BYTES
BOOL_FIELDS = ('defaultLookupCalled', 'allocationCalled', 'createCalled',
               'postCaptureAttempted', 'mainCatalogVerified', 'companionCatalogVerified', 'outcomeUncertain')
NAMES = ('code', 'stage', 'mainDeltaCode', 'nameCode', 'defaultTable', 'defaultRecord',
         'returnedResource', 'observedMainClass', 'observedCompanionClass', 'companionResource',
         'defaultType', 'defaultValue', 'createdId', 'companionOwnId', 'primaryCountBefore',
         'companionCountBefore', 'metadataCallsStarted', 'metadataCallsCompleted', *BOOL_FIELDS)
require = catalogs.require


def decode(raw: bytes) -> dict:
    require(type(raw) is bytes and len(raw) == RECEIPT_BYTES, 'SKILL_RECEIPT_SIZE')
    size, version, seh, unchanged = struct.unpack_from('<4I', raw)
    require(size == RECEIPT_BYTES and version == 1, 'SKILL_RECEIPT_VERSION')
    result = dict(zip(NAMES, ACTION.unpack_from(raw, ACTION_AT)))
    for key in BOOL_FIELDS:
        require(result[key] in (0, 1), 'SKILL_BOOL_ENCODING:' + key)
        result[key] = bool(result[key])
    result.update(size=size, version=version, sehCode=seh, afterSceneUnchanged=unchanged)
    return result


def verify(raw: bytes, *, level_id: int, global_pointer: int) -> dict:
    action = decode(raw)
    require(action['code'] == action['stage'] == action['mainDeltaCode'] == action['nameCode'] == 0 and
            action['sehCode'] == 0 and action['afterSceneUnchanged'] == 1 and
            action['defaultType'] == 2 and action['metadataCallsStarted'] == action['metadataCallsCompleted'] == 2 and
            all(action[key] for key in BOOL_FIELDS), 'SKILL_NATIVE_RESULT_NOT_VERIFIED')
    require(catalogs.pointer(action['defaultTable']) and catalogs.pointer(action['defaultRecord']),
            'SKILL_DEFAULT_POINTERS')
    before_hex = raw[BEFORE_CATALOG_AT:BEFORE_CATALOG_AT+catalogs.CATALOG_BYTES].hex()
    after_hex = raw[AFTER_CATALOG_AT:AFTER_CATALOG_AT+catalogs.CATALOG_BYTES].hex()
    before = catalogs.decode_catalog(before_hex)
    require(before['global'] == global_pointer, 'SKILL_CATALOG_GLOBAL')
    require(action['primaryCountBefore'] == len(before['primary']) and
            action['companionCountBefore'] == len(before['companion']) and
            action['primaryCountBefore'] < catalogs.MAX_ROWS and action['companionCountBefore'] < catalogs.MAX_ROWS,
            'SKILL_BEFORE_COUNTS')
    delta = catalogs.verify_skill_delta(before_hex, after_hex, level_id=level_id,
        returned_resource=action['returnedResource'], expected_class=action['observedMainClass'],
        expected_companion_class=action['observedCompanionClass'])
    after = catalogs.decode_catalog(after_hex)
    require(action['createdId'] == delta['createdId'] and action['companionOwnId'] == delta['companionOwnId'] and
            after['companion'][delta['createdId']][6] == action['companionResource'], 'SKILL_CREATED_IDENTITY')
    return dict(delta, action=action)
