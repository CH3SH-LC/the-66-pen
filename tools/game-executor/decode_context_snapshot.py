"""Decode one read-only hook probe snapshot; never contacts a process.

Usage: python decode_context_snapshot.py PROBE_STDOUT OUTPUT_JSON
The input may be UTF-8 or UTF-16 JSON/JSONL. OUTPUT_JSON must not exist.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import struct
import sys


# Mirrors game_context_snapshot.h. kMaxEntities was raised 32 -> 512 because a decorated
# level holds hundreds of entities and the snapshot must be COMPLETE for any write action
# to run; a partial snapshot makes every action refuse by design.
MAX_ENTITIES = 512
LARGE_MAX_ENTITIES = 4096
MAX_STACK = 32
HEADER_BYTES = 184
STACK_OFFSET = HEADER_BYTES
ENTITIES_OFFSET = HEADER_BYTES + MAX_STACK * 8
SNAPSHOT_BYTES = ENTITIES_OFFSET + MAX_ENTITIES * 64
LARGE_SNAPSHOT_BYTES = ENTITIES_OFFSET + LARGE_MAX_ENTITIES * 64
SNAPSHOT_LAYOUTS = {(1, SNAPSHOT_BYTES): (MAX_ENTITIES, 4096, 256 * 1024, 16384),
                    (2, LARGE_SNAPSHOT_BYTES): (LARGE_MAX_ENTITIES, 8192, 1024 * 1024, 65536)}
MAX_INPUT_BYTES = 8 * 1024 * 1024
STATUS = {
    0: "ok", 1: "build_mismatch", 2: "module_unavailable", 3: "unreadable",
    4: "invalid_structure", 5: "limit_exceeded", 6: "context_not_found",
    7: "unstable", 8: "partial_entities",
}
SNAPSHOT_FLAGS = {
    1: "build_verified", 2: "origin_read", 4: "contexts_complete",
    8: "entities_complete", 16: "structure_rechecked", 32: "entities_truncated",
    64: "entity_read_failure", 128: "stack_captured",
    # native/game_context_snapshot.h:23 strict-profile bits (readonly bootstrap only):
    # 0x100 was previously unknown -> the real v2 probe receipt (flags 0x181) could not be
    # decoded offline. Names mirror the enum exactly; GS_LEVEL_OBSERVED is recorded but the
    # reserved level-id field it uses stays refused by the ABI checks above.
    256: "stack_verified", 512: "hotfix_default_confirmed", 1024: "level_observed",
}
ENTITY_FLAGS = {
    1: "id_read", 2: "config_id_read", 4: "context_match", 8: "key_match",
    16: "position_read", 32: "config_null", 64: "context_read",
}
POINTER_NAMES = (
    "moduleBase", "global", "contextManager", "saveManager", "contextDictionary",
    "contextEntries", "contextBuckets", "currentContext", "entityDictionary",
    "entityEntries", "entityBuckets",
)
COUNT_NAMES = (
    "peTimestamp", "peImageSize", "activeKey", "contextCapacity", "contextValidEntries",
    "contextMatchingEntries", "entityCapacity", "entityValidEntries", "entityCaptured",
    "entityRejected", "bytesRead", "readCalls", "stackCount", "entityVersionBefore",
    "entityVersionAfter", "lastReadStatus",
)
ENTITY = struct.Struct("<QQQIIIIfffIQ")
assert ENTITY.size == 64
assert 16 + 11 * 8 + 16 * 4 + 16 + MAX_STACK * 8 + MAX_ENTITIES * ENTITY.size == SNAPSHOT_BYTES

# ---- the self-describing snapshot ABI (one formula, two reviewed ABIs) ----------------
# A snapshot carries its own ABI in its first four uint32: structSize, version, status,
# flags (native/game_context_snapshot.h:104, mirrored by the unpack at :103 below), and its
# entity capacity follows from the byte count through the one layout formula this module
# owns:
#
#     snapshotBytes(N) = HEADER_BYTES (184) + MAX_STACK (32) * 8 + N * ENTITY.size (64)
#
# ENTITIES_OFFSET is that 184 + 256 = 440, asserted against the compiled struct above and
# again in native/game_context_snapshot.h:119-120. Consumers therefore never type an entity
# count or a byte count: they call snapshot_bytes() / abi_for_size() / derive_snapshot_abi()
# below and get a reviewed (version, size, maxEntities) triple or a named refusal. The two
# reviewed ABIs are SNAPSHOT_LAYOUTS: v1 (512 entities, 33208 B, historical) and v2 (4096
# entities, 262584 B, GS_LARGE_SCENE=1).
SNAPSHOT_HEADER_BYTES = HEADER_BYTES
SNAPSHOT_ENTITY_BYTES = ENTITY.size
SNAPSHOT_HEADER_UNPACK = "<4I"
COUNTS_OFFSET = 104          # the start of the 16 uint32 counters (see COUNT_NAMES)
RESERVED_OFFSET = 180        # GameContextSnapshot::reserved, the level id under GS_LEVEL_OBSERVED
# native/game_context_snapshot.h:75-92: GS_LARGE_SCENE selects the ABI at compile time, 0 is
# v1 and 1 is v2 -- the only switch that changes sizeof(GameContextSnapshot). Keyed by the
# version the payload declares, so a payload names its own compile flag.
SNAPSHOT_LARGE_SCENE = {1: 0, 2: 1}
assert set(SNAPSHOT_LARGE_SCENE) == {version for version, _size in SNAPSHOT_LAYOUTS}


class SnapshotAbiError(ValueError):
    """A snapshot whose self-described ABI must not be used.

    `code` is a refusal-code name (the same vocabulary the native side publishes in
    tools/game-executor/native-options/generalized_tabs.h), so a caller refuses by name
    instead of truncating, padding or guessing a size.
    """

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(code + (':' + detail if detail else ''))
        self.code = code
        self.detail = detail


def snapshot_bytes(max_entities: int) -> int:
    """The byte count of a snapshot holding `max_entities` entities (the formula above)."""
    return ENTITIES_OFFSET + int(max_entities) * ENTITY.size


def abi_for_size(size: int) -> dict | None:
    """The unique reviewed ABI whose byte count is `size`, or None. Registry-derived."""
    matched = [{'version': version, 'bytes': layout_size, 'maxEntities': counts[0],
                'largeScene': SNAPSHOT_LARGE_SCENE[version]}
               for (version, layout_size), counts in SNAPSHOT_LAYOUTS.items()
               if layout_size == size]
    return matched[0] if len(matched) == 1 else None


def derive_snapshot_abi(data, label: str = 'snapshot') -> dict:
    """Read one payload's ABI out of the payload itself; refuse by name when it cannot.

    The declared structSize, the actual byte count and a reviewed (version, size) pair must
    agree. An all-zero header is the documented *uninitialized* payload -- the builder's
    compile-only placeholder and the offline synthetic receipts -- and is accepted by byte
    count only; a half-initialized header (one of structSize/version zero and the other not)
    is refused. Nothing here ever resizes a payload.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise SnapshotAbiError('snapshot_abi_derivation_failed', f'{label}: {type(data).__name__} is not bytes')
    raw = bytes(data)
    size = len(raw)
    if size < ENTITIES_OFFSET or (size - ENTITIES_OFFSET) % ENTITY.size != 0:
        raise SnapshotAbiError('snapshot_abi_derivation_failed',
                               f'{label}: {size} bytes is not {ENTITIES_OFFSET} + N*{ENTITY.size}')
    max_entities = (size - ENTITIES_OFFSET) // ENTITY.size
    struct_size, version, _status, _flags = struct.unpack_from(SNAPSHOT_HEADER_UNPACK, raw, 0)
    if struct_size not in (0, size):
        raise SnapshotAbiError('snapshot_size_mismatch',
                               f'{label}: header structSize={struct_size} != {size} payload bytes')
    abi = abi_for_size(size)
    if abi is None:
        reviewed = ','.join(f'v{v}:{s}B' for v, s in sorted(SNAPSHOT_LAYOUTS))
        raise SnapshotAbiError('snapshot_abi_unsupported',
                               f'{label}: {size} bytes ({max_entities} entities) is not a reviewed ABI '
                               f'({reviewed})')
    if abi['maxEntities'] != max_entities:  # unreachable while the module assert holds
        raise SnapshotAbiError('snapshot_abi_derivation_failed',
                               f'{label}: {size} bytes implies {max_entities} entities, registry says '
                               f'{abi["maxEntities"]}')
    if (struct_size == 0) != (version == 0):
        raise SnapshotAbiError('snapshot_abi_derivation_failed',
                               f'{label}: half-initialized header structSize={struct_size} version={version}')
    if version != 0 and version != abi['version']:
        raise SnapshotAbiError('snapshot_abi_unsupported',
                               f'{label}: header version={version} != v{abi["version"]} for {size} bytes')
    return {'version': abi['version'], 'bytes': size, 'maxEntities': max_entities,
            'largeScene': SNAPSHOT_LARGE_SCENE[abi['version']], 'entityOffset': ENTITIES_OFFSET,
            'entityStride': ENTITY.size, 'headerInitialized': struct_size != 0, 'source': label}


def count_offset(name: str) -> int:
    """The byte offset of one named uint32 counter in a snapshot header."""
    return COUNTS_OFFSET + COUNT_NAMES.index(name) * 4


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def flags(value: int, names: dict[int, str]) -> dict:
    require(value & ~sum(names) == 0, f"Unknown flag bits: {value:#x}")
    return {"value": value, "names": [name for bit, name in names.items() if value & bit]}


def read_probe(path: Path) -> tuple[dict, str]:
    # One bounded read; do not reopen the input during parsing or output generation.
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    require(len(raw) <= MAX_INPUT_BYTES, "Probe output exceeds 8 MiB")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    elif b"\0" in raw[:128]:
        encoding = "utf-16-le" if raw[1:2] == b"\0" else "utf-16-be"
    else:
        encoding = "utf-8"
    text = raw.decode(encoding, errors="strict").strip()
    require(bool(text), "Probe output is empty")
    try:
        records = [json.loads(text)]
    except json.JSONDecodeError:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    require(all(isinstance(record, dict) for record in records), "Expected JSON object records")
    candidates = [record for record in records if "snapshotHex" in record]
    require(len(candidates) == 1, "Expected exactly one snapshotHex record")
    return candidates[0], encoding


def decode_snapshot(record: dict) -> dict:
    encoded = record.get("snapshotHex")
    require(isinstance(encoded, str) and len(encoded) in (SNAPSHOT_BYTES * 2, LARGE_SNAPSHOT_BYTES * 2) and
            re.fullmatch(r"[0-9a-fA-F]+", encoded) is not None, "Invalid snapshotHex size or encoding")
    require(type(record.get("snapshotBytes")) is int and record["snapshotBytes"] * 2 == len(encoded),
            "snapshotBytes does not match the snapshot payload")
    data = bytes.fromhex(encoded)
    size, version, status, snapshot_flags = struct.unpack_from("<4I", data, 0)
    require((version, size) in SNAPSHOT_LAYOUTS and size == len(data), "Unsupported snapshot structure size/version")
    max_entities, max_dictionary, read_budget, read_calls = SNAPSHOT_LAYOUTS[(version, size)]
    require(status in STATUS, "Unknown snapshot status")
    pointers = dict(zip(POINTER_NAMES, struct.unpack_from("<11Q", data, 16)))
    counts = dict(zip(COUNT_NAMES, struct.unpack_from("<16I", data, 104)))
    require(counts["lastReadStatus"] in STATUS, "Unknown lastReadStatus")
    require(counts["contextCapacity"] <= 256 and counts["entityCapacity"] <= max_dictionary,
            "Dictionary capacity exceeds snapshot limits")
    require(counts["contextMatchingEntries"] <= counts["contextValidEntries"] <= counts["contextCapacity"],
            "Inconsistent context counts")
    require(counts["entityRejected"] <= counts["entityCaptured"] <= max_entities and
            counts["entityCaptured"] <= counts["entityValidEntries"] <= counts["entityCapacity"],
            "Inconsistent entity counts")
    require(counts["stackCount"] <= MAX_STACK and counts["bytesRead"] <= read_budget and counts["readCalls"] <= read_calls,
            "Snapshot count or read budget exceeds limits")
    origin = struct.unpack_from("<3f", data, 168)
    require(struct.unpack_from("<I", data, 180)[0] == 0, "Nonzero reserved snapshot field")
    if snapshot_flags & 2:
        require(all(math.isfinite(value) for value in origin), "Invalid marked-valid origin")
    stack = []
    for index, address in enumerate(struct.unpack_from(f"<{MAX_STACK}Q", data, STACK_OFFSET)[:counts["stackCount"]]):
        in_module = pointers["moduleBase"] <= address < pointers["moduleBase"] + counts["peImageSize"]
        stack.append({"index": index, "address": hex(address), "inMainModule": in_module,
                      "rva": hex(address - pointers["moduleBase"]) if in_module else None})
    entities = []
    for index in range(counts["entityCaptured"]):
        owner, config, context, key, entity_id, config_id, entity_flags, x, y, z, reserved, reserved2 = ENTITY.unpack_from(data, ENTITIES_OFFSET + index * ENTITY.size)
        require(reserved == 0 and reserved2 == 0, f"Nonzero reserved entity field at {index}")
        if entity_flags & 16:
            require(all(math.isfinite(value) for value in (x, y, z)), f"Invalid marked-valid position at {index}")
        entities.append({"index": index, "owner": hex(owner), "config": hex(config), "context": hex(context),
                         "dictionaryKey": key, "id": entity_id if entity_flags & 1 else None,
                         "configId": config_id if entity_flags & 2 else None,
                         "flags": flags(entity_flags, ENTITY_FLAGS),
                         "position": [x, y, z] if entity_flags & 16 else None})
    return {
        "structureSize": size, "version": version,
        "status": {"value": status, "name": STATUS[status]},
        "flags": flags(snapshot_flags, SNAPSHOT_FLAGS),
        "pointers": {name: hex(value) for name, value in pointers.items()},
        "counts": counts, "lastReadStatusName": STATUS[counts["lastReadStatus"]],
        "origin": list(origin) if snapshot_flags & 2 else None,
        "stack": stack, "entities": entities,
        "limits": "Read-only, bounded, unlocked observation; no create/save business result. Stack thread is not thereby proven to be the scene thread.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        record, encoding = read_probe(args.input)
        result = decode_snapshot(record)
        result["source"] = {"path": str(args.input.resolve()), "encoding": encoding,
                            "probe": {name: value for name, value in record.items() if name != "snapshotHex"}}
        # Exclusive creation also rejects input == output. Never replace older evidence.
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"output": str(args.output.resolve()), "snapshotStatus": result["status"]["name"],
                          "entities": len(result["entities"]), "stackFrames": len(result["stack"])}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, UnicodeError, struct.error) as error:
        print(f"Snapshot decode failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
