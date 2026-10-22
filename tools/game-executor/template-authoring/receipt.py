"""Independent decoding of the candidate's raw template catalogues.

This module proves structural deltas only. Native transport/session/build
acceptance, resource name/defaults, export, saving and gameplay are separate.
It never invokes a compiler, process, helper, hook or native function.
"""
from __future__ import annotations
import struct

MAX_ROWS = 4096
DICTIONARY = struct.Struct("<4Q7Ii")
PRIMARY = struct.Struct("<IIQQ")
COMPANION = struct.Struct("<6IQQ")
CATALOG_BYTES = 160 + MAX_ROWS * (PRIMARY.size + COMPANION.size)


class ReceiptError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ReceiptError(reason)


def pointer(value):
    return type(value) is int and 0x10000 <= value < 0x800000000000 and value % 8 == 0


def dictionary(raw, at):
    values = DICTIONARY.unpack_from(raw, at)
    names = ("dictionary", "buckets", "entries", "comparer", "bucketCapacity",
             "entryCapacity", "initializedCount", "freeCount", "versionBefore",
             "versionAfter", "rowCount", "freeHead")
    result = dict(zip(names, values))
    require(pointer(result["dictionary"]), "INVALID_DICTIONARY")
    require(result["comparer"] == 0 or pointer(result["comparer"]), "INVALID_COMPARER")
    require(result["versionBefore"] == result["versionAfter"], "UNSTABLE_DICTIONARY")
    count, free, rows = result["initializedCount"], result["freeCount"], result["rowCount"]
    require(0 <= free <= count <= MAX_ROWS and rows == count - free, "PARTIAL_DICTIONARY")
    if result["buckets"] == result["entries"] == 0:
        require(count == free == rows == result["entryCapacity"] == result["bucketCapacity"] == 0,
                "INVALID_EMPTY_DICTIONARY")
    else:
        require(pointer(result["buckets"]) and pointer(result["entries"]), "INVALID_ARRAY_POINTER")
        require(0 < result["bucketCapacity"] == result["entryCapacity"] <= MAX_ROWS and
                count <= result["entryCapacity"], "INVALID_CAPACITY")
    return result


def decode_catalog(encoded):
    require(type(encoded) is str and len(encoded) == CATALOG_BYTES * 2, "CATALOG_SIZE")
    try:
        raw = bytes.fromhex(encoded)
    except ValueError as error:
        raise ReceiptError("CATALOG_HEX") from error
    require(len(raw) == CATALOG_BYTES, "CATALOG_SIZE")
    status, level, read_bytes, read_calls, global_pointer, manager = struct.unpack_from("<4I2Q", raw)
    require(status == 0, "INCOMPLETE_CATALOG")
    require(level > 0 and pointer(global_pointer) and pointer(manager), "INVALID_CATALOG_CONTEXT")
    require(0 < read_bytes <= 2 * 1024 * 1024 and 0 < read_calls <= 40000, "INVALID_CAPTURE_BUDGET")
    main, companion = dictionary(raw, 32), dictionary(raw, 96)
    require(main["dictionary"] != companion["dictionary"], "ALIASED_DICTIONARIES")
    primary_rows, companion_rows = {}, {}
    seen = set()
    for i in range(main["rowCount"]):
        row = PRIMARY.unpack_from(raw, 160 + i * PRIMARY.size)
        identifier, subtype, resource, klass = row
        require(identifier and subtype and pointer(resource) and pointer(klass), "INVALID_PRIMARY")
        require(identifier not in primary_rows and resource not in seen, "DUPLICATE_PRIMARY")
        primary_rows[identifier] = row
        seen.add(resource)
    seen.clear()
    for i in range(companion["rowCount"]):
        row = COMPANION.unpack_from(raw, 160 + MAX_ROWS * PRIMARY.size + i * COMPANION.size)
        key, parent, own_id, _, _, _, resource, klass = row
        require(key and parent == key and own_id and pointer(resource) and pointer(klass), "INVALID_COMPANION")
        require(key not in companion_rows and resource not in seen, "DUPLICATE_COMPANION")
        companion_rows[key] = row
        seen.add(resource)
    return {"levelId": level, "global": global_pointer, "manager": manager,
            "primary": primary_rows, "companion": companion_rows,
            "primaryHeader": main, "companionHeader": companion}


def verify_currency_delta(before_hex, after_hex, *, level_id, returned_resource, expected_class):
    """Recompute registration identity from raw records, never from success flags.

    expected_class must come from separately verified native type-slot evidence;
    deriving it from the newly added row would not verify its type.
    """
    require(type(level_id) is int and 0 < level_id < 2**32, "INVALID_LEVEL")
    require(pointer(returned_resource) and pointer(expected_class), "INVALID_EXPECTED_IDENTITY")
    before, after = decode_catalog(before_hex), decode_catalog(after_hex)
    require(before["levelId"] == after["levelId"] == level_id and
            before["global"] == after["global"] and before["manager"] == after["manager"], "CONTEXT_CHANGED")
    require(len(after["primary"]) == len(before["primary"]) + 1, "PRIMARY_DELTA_COUNT")
    require(all(after["primary"].get(key) == row for key, row in before["primary"].items()),
            "PRIOR_PRIMARY_CHANGED")
    added = set(after["primary"]) - set(before["primary"])
    require(len(added) == 1, "NON_UNIQUE_CREATED_ID")
    identifier = added.pop()
    row = after["primary"][identifier]
    require(row[1:] == (11, returned_resource, expected_class), "NEW_RESOURCE_IDENTITY")
    require(identifier & 0xE0000000 == 0x40000000 and (identifier >> 22) & 127 == 10,
            "CURRENCY_ID_BAND")
    require(before["companion"] == after["companion"], "COMPANION_CHANGED")
    return {"catalogDeltaVerified": True, "createdId": identifier,
            "scope": "structural-registration-delta-only", "persistentSaveVerified": False,
            "nameVerified": False, "defaultsVerified": False, "gameplayVerified": False}


def verify_item_delta(before_hex, after_hex, *, level_id, expected_class, expected_companion_class):
    """An ordinary item registers one main record and one separate companion."""
    require(type(level_id) is int and 0 < level_id < 2**32, "INVALID_LEVEL")
    require(pointer(expected_class) and pointer(expected_companion_class), "INVALID_EXPECTED_IDENTITY")
    before, after = decode_catalog(before_hex), decode_catalog(after_hex)
    require(before["levelId"] == after["levelId"] == level_id and
            before["global"] == after["global"] and before["manager"] == after["manager"], "CONTEXT_CHANGED")
    require(len(after["primary"]) == len(before["primary"]) + 1, "PRIMARY_DELTA_COUNT")
    require(all(after["primary"].get(key) == row for key, row in before["primary"].items()),
            "PRIOR_PRIMARY_CHANGED")
    added = set(after["primary"]) - set(before["primary"])
    require(len(added) == 1, "NON_UNIQUE_CREATED_ID")
    identifier = added.pop()
    row = after["primary"][identifier]
    require(row[1] == 9 and row[3] == expected_class, "NEW_RESOURCE_IDENTITY")
    require(identifier & 0xE0000000 == 0x40000000 and (identifier >> 22) & 127 == 8,
            "ITEM_ID_BAND")
    require(len(after["companion"]) == len(before["companion"]) + 1, "COMPANION_DELTA_COUNT")
    require(all(after["companion"].get(key) == old for key, old in before["companion"].items()),
            "PRIOR_COMPANION_CHANGED")
    require(set(after["companion"]) - set(before["companion"]) == {identifier}, "COMPANION_KEY")
    companion = after["companion"][identifier]
    require(companion[1] == identifier and companion[3:6] == (0, 1, 4) and
            companion[7] == expected_companion_class, "COMPANION_IDENTITY")
    # Its independent GUID domain permits equal OR unequal numeric IDs.
    return {"catalogDeltaVerified": True, "createdId": identifier,
            "companionOwnId": companion[2], "scope": "structural-registration-delta-only",
            "persistentSaveVerified": False, "nameVerified": False,
            "defaultsVerified": False, "gameplayVerified": False}


def verify_skill_delta(before_hex, after_hex, *, level_id, returned_resource,
                       expected_class, expected_companion_class):
    """A skill uses subtype 6 / ID band 6 and a distinct same-key companion.

    The existing energy resource subtype 7 is not a skill. Classes must come
    from the adapter's separately checked current-build class slots.
    """
    require(type(level_id) is int and 0 < level_id < 2**32, "INVALID_LEVEL")
    require(pointer(returned_resource) and pointer(expected_class) and
            pointer(expected_companion_class), "INVALID_EXPECTED_IDENTITY")
    before, after = decode_catalog(before_hex), decode_catalog(after_hex)
    require(before["levelId"] == after["levelId"] == level_id and
            before["global"] == after["global"] and before["manager"] == after["manager"], "CONTEXT_CHANGED")
    require(len(after["primary"]) == len(before["primary"]) + 1, "PRIMARY_DELTA_COUNT")
    require(all(after["primary"].get(key) == row for key, row in before["primary"].items()),
            "PRIOR_PRIMARY_CHANGED")
    added = set(after["primary"]) - set(before["primary"])
    require(len(added) == 1, "NON_UNIQUE_CREATED_ID")
    identifier = added.pop()
    require(after["primary"][identifier][1:] == (6, returned_resource, expected_class),
            "NEW_RESOURCE_IDENTITY")
    require(identifier & 0xE0000000 == 0x40000000 and (identifier >> 22) & 127 == 6,
            "SKILL_ID_BAND")
    require(len(after["companion"]) == len(before["companion"]) + 1, "COMPANION_DELTA_COUNT")
    require(all(after["companion"].get(key) == row for key, row in before["companion"].items()),
            "PRIOR_COMPANION_CHANGED")
    require(set(after["companion"]) - set(before["companion"]) == {identifier}, "COMPANION_KEY")
    companion = after["companion"][identifier]
    require(companion[1] == identifier and companion[3:6] == (0, 1, 4) and
            companion[7] == expected_companion_class, "COMPANION_IDENTITY")
    return {"catalogDeltaVerified": True, "createdId": identifier,
            "companionOwnId": companion[2], "scope": "structural-registration-delta-only",
            "persistentSaveVerified": False, "nameVerified": False,
            "defaultsVerified": False, "gameplayVerified": False}
