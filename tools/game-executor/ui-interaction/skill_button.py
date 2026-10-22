"""Offline codec and official-method recipe for the current native UI button.

This module never loads a game, reads a process, writes a save, or dispatches a
request. Field numbers are from native export 7de80e0 and writer 13177580.
Unknown enum meanings deliberately keep their property hashes.
"""
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path

IMAGE_SHA256 = "7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e"
METADATA_SHA256 = "469eccd43aa48fe7a2df4e1caf66fa1268a17f5a4a03fa209e1427e467cb0161"
KEYBOARD_PROPERTY = 0x57BE76BC
KEYBOARD_FIELD = 513
Z_KEYBOARD_SELECTOR = 26
Z_INPUT_EVENT = 5508
# Native 7b13d30 sets its out-allowed flag for exactly these selectors.
ALLOWED_KEYBOARD_SELECTORS = frozenset({1, 3, 4, 5, 6, 7, 8, 10, 12, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 49, 50, 51, 52, 54, 55, 56, 57, 58, 59, 60})


@dataclass(frozen=True)
class Field:
    number: int
    model_offset: int
    proto_offset: int
    kind: str
    property_hash: int | None = None


FIELDS = {
    f.number: f for f in (
        Field(501, 0xA4, 0x34, "int32", 0x8F60E6FD),
        Field(502, 0x9C, 0x44, "int32", 0x3453CD4D),
        Field(503, 0x90, 0x50, "int32", 0xE1617C66),
        Field(504, 0x94, 0x30, "uint32"),
        Field(505, 0x88, 0x48, "int32", 0xB7AC520C),
        Field(506, 0xA0, 0x28, "float", 0x8334A071),
        Field(507, 0xB1, 0x2D, "bool", 0x47FDAE67),
        Field(508, 0xB0, 0x2C, "bool", 0x3813BB2C),
        Field(509, 0x78, 0x20, "message", 0x7BBA35DF),
        Field(510, 0xAC, 0x4C, "int32", 0xB3679614),
        Field(511, 0xA8, 0x3C, "int32", 0x81FD23FA),
        Field(512, 0x58, 0x18, "message", 0x5136907D),
        Field(513, 0x8C, 0x40, "int32", KEYBOARD_PROPERTY),
        Field(514, 0x98, 0x38, "int32", 0x4B42604C),
    )
}
WIRE = {"int32": 0, "uint32": 0, "bool": 0, "message": 2, "float": 5}


def _varint(value: int) -> bytes:
    if not 0 <= value < 1 << 64:
        raise ValueError("varint outside uint64")
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    for i in range(10):
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        if i == 9 and byte > 1:
            raise ValueError("varint exceeds uint64")
        result |= (byte & 127) << (i * 7)
        if not byte & 128:
            return result, pos
    raise ValueError("unterminated varint")


def encode(fields: dict[int, object]) -> bytes:
    """Encode a button child only. This is not a complete root9/UI group."""
    result = bytearray()
    for number, value in sorted(fields.items()):
        field = FIELDS.get(number)
        if field is None:
            raise ValueError(f"unproved field {number}")
        if field.kind == "message":
            if not isinstance(value, bytes):
                raise ValueError(f"field {number} needs opaque nested message bytes")
            payload = _varint(len(value)) + value
        elif field.kind == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"field {number} needs a float")
            payload = struct.pack("<f", value)
            if value == 0:
                continue
        else:
            if field.kind == "bool":
                if type(value) is not bool:
                    raise ValueError(f"field {number} needs bool")
                value = int(value)
            elif type(value) is not int:
                raise ValueError(f"field {number} needs integer")
            low, high = (-2**31, 2**31 - 1) if field.kind == "int32" else (0, 2**32 - 1)
            if not low <= value <= high:
                raise ValueError(f"field {number} out of range")
            if value == 0:
                continue
            payload = _varint(value & (2**64 - 1))
        result.extend(_varint(number * 8 + WIRE[field.kind]))
        result.extend(payload)
    return bytes(result)


def decode(data: bytes) -> dict[int, object]:
    """Strict decoder of the proved child schema; reject unknown/duplicate tags."""
    result: dict[int, object] = {}
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        number, wire = tag >> 3, tag & 7
        field = FIELDS.get(number)
        if field is None or wire != WIRE[field.kind] or number in result:
            raise ValueError(f"unexpected/duplicate field or wire: {number}/{wire}")
        if wire == 0:
            value, pos = _read_varint(data, pos)
            if field.kind == "int32":
                if value > 2**31 - 1:
                    if value < 2**64 - 2**31:
                        raise ValueError("invalid sign extension for int32")
                    value -= 2**64
            elif field.kind == "uint32" and value > 2**32 - 1:
                raise ValueError("uint32 overflow")
            elif field.kind == "bool":
                if value not in (0, 1):
                    raise ValueError("nonboolean value")
                value = bool(value)
        else:
            if wire == 2:
                size, pos = _read_varint(data, pos)
            else:
                size = 4
            if pos + size > len(data):
                raise ValueError("truncated payload")
            value = data[pos:pos + size]
            pos += size
            if wire == 5:
                value = struct.unpack("<f", value)[0]
        result[number] = value
    return result


def keyboard_configuration_recipe(selector: int, observed_key: str, source: str) -> dict:
    """Make a non-dispatchable recipe after selector label verification.

    1..60 are UI selectors. Unity KeyCode 122 is intentionally rejected.
    The reference can be pinned native parser proof or a current readback.
    """
    if type(selector) is not int or selector not in ALLOWED_KEYBOARD_SELECTORS:
        raise ValueError("keyboard selector must pass the native allowed table, not Unity KeyCode")
    if selector != Z_KEYBOARD_SELECTOR:
        raise ValueError("this pinned build maps only selector 26 to Z press")
    if observed_key.upper() != "Z" or not source.strip():
        raise ValueError("Z label/current binding evidence is required")
    return {
        "schema": "miliastra-skill-button-keyboard-recipe-v1",
        "dispatchable": False,
        "imageSha256": IMAGE_SHA256,
        "metadataSha256": METADATA_SHA256,
        "officialTypeName": "BydUICompSkillButtonEditData",
        "definitionIndex": 78893,
        "keyboardEvidence": {"selector": selector, "observedKey": "Z", "source": source},
        "componentOnly": True,
        "steps": [
            {"operation": "officialFactory", "rva": "0x95f6410", "argument": "BydUICompSkillButtonEditData"},
            {"operation": "initializeDefaults", "rva": "0x8b3b5e0", "note": "Only for a newly allocated detached model, before applying properties."},
            {"operation": "setKeyboardEnum", "rva": "0x8b3b840", "propertyHash": "0x57be76bc", "value": selector},
            {"operation": "readKeyboardEnum", "rva": "0x8b3bc70", "propertyHash": "0x57be76bc", "expect": selector},
            {"operation": "exportComponent", "rva": "0x7de80e0", "protobufField": 513, "expect": selector},
        ],
        "requires": ["official parent UI registration and group indices", "interaction-event mode value from editor schema", "player UI group attachment", "one 316 handler for this single button", "native save/readback/playtest by coordinator"],
    }


def with_z_binding(fields: dict[int, object]) -> dict[int, object]:
    """Preserve other proved component fields; set the native Z-press selector."""
    encode(fields)  # Check the caller supplied the child schema, not a wrapper.
    return {**fields, KEYBOARD_FIELD: Z_KEYBOARD_SELECTOR}


def z_configuration_recipe(source: str) -> dict:
    result = keyboard_configuration_recipe(Z_KEYBOARD_SELECTOR, "Z", source)
    result["keyboardEvidence"].update(inputEventId=Z_INPUT_EVENT, inputEventName="KeyCodeZPressEvent", verification="current-build-static-code")
    return result


def with_z_interaction(fields: dict[int, object]) -> dict[int, object]:
    """Select the native group interaction event and Z press, preserving others."""
    return {**with_z_binding(fields), 503: 2}


def interaction_configuration_recipe(z_proof: str, mode_proof: str) -> dict:
    if not mode_proof.strip():
        raise ValueError("current native mode proof is required")
    result = z_configuration_recipe(z_proof)
    result["schema"] = "miliastra-ui-z-interaction-component-recipe-v1"
    result["nativeComponentKind"] = 22
    result["interactionEvidence"] = {"mode": 2, "field": 503, "source": mode_proof}
    result["steps"] = [
        {"operation": "addComponentToFreshUiNode", "rva": "0x10616220", "componentKind": 22,
         "history": True, "initialize": True},
        {"operation": "readComponentEditDataList", "rva": "0xbc16250",
         "expectUniqueDefinition": 78893, "expectOwnerHandle": "freshUiNodeHandle"},
        {"operation": "setInteractionMode", "rva": "0x8b38c00", "propertyHash": "0xe1617c66", "value": 2},
        {"operation": "readInteractionMode", "rva": "0x8b3b4a0", "propertyHash": "0xe1617c66", "expect": 2},
        {"operation": "setKeyboardEnum", "rva": "0x8b3b840", "propertyHash": "0x57be76bc", "value": 26},
        {"operation": "readKeyboardEnum", "rva": "0x8b3bc70", "propertyHash": "0x57be76bc", "expect": 26},
    ]
    result["requires"] = ["fresh UI node creation and actual index readback", "official owner update notification",
                          "visible parent layout attachment or library activation", "one 316 handler using actual button/group indices",
                          "native save/readback/playtest by coordinator"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["encode", "decode", "keyboard-recipe"])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.operation == "encode":
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        values = {int(k): (bytes.fromhex(v["hex"]) if isinstance(v, dict) else v) for k, v in raw.items()}
        args.output.write_bytes(encode(values))
    elif args.operation == "decode":
        values = decode(args.input.read_bytes())
        args.output.write_text(json.dumps({str(k): ({"hex": v.hex()} if isinstance(v, bytes) else v) for k, v in values.items()}, indent=2), encoding="utf-8")
    else:
        values = json.loads(args.input.read_text(encoding="utf-8"))
        recipe = keyboard_configuration_recipe(values["selector"], values["observedKey"], values["source"])
        args.output.write_text(json.dumps(recipe, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
