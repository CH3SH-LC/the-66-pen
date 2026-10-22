"""Read names, isTradeable and stackLimit of saved ordinary item resources.

Current-build evidence: task-saved-items/saved-item-mapping.json. These are
editor-save fields, not the distinct normal-item runtime export protobuf.
No game calls, writes, save execution or gameplay claims are made here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import saved_farming_bindings as saved


def _item(root, item_id: int, expected_name: str, expected_stack_limit: int) -> dict:
    path, record = saved._record(root, 15, item_id)
    result = {"itemId": item_id, "expectedName": expected_name,
              "expectedStackLimit": expected_stack_limit, "recordPath": path,
              "templatePresent": record is not None, "templateSubtype": None,
              "name": None, "nameMatches": False, "isTradeable": None,
              "stackLimit": None, "propertiesRead": False,
              "savedPropertiesVerified": False, "status": "template_absent",
              "paths": {"name": path + ".f4[kind=1].f11.f1",
                        "isTradeable": path + ".f4[kind=39].f49.f1.f3.f2",
                        "stackLimit": path + ".f4[kind=39].f49.f1.f1.f1"}}
    if record is None:
        return result
    result["templateSubtype"] = saved._scalar(record, 2, path)
    if result["templateSubtype"] != 9:
        result["status"] = "wrong_template_subtype"
        return result
    name_property = saved._component(record, 4, 1, path)
    if name_property is not None:
        name_payload = saved._message(name_property, 11, path + ".f4[kind=1]")
        if name_payload is not None:
            name_field = saved._one(name_payload, 1, saved.gil.WIRE_LENGTH,
                                   path + ".f4[kind=1].f11")
            try:
                result["name"] = "" if name_field is None else name_field.data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise saved.SavedBindingError(f"{path}: invalid UTF-8 resource name") from exc
            result["nameMatches"] = result["name"] == expected_name
    property39 = saved._component(record, 4, 39, path)
    result["status"] = "property_absent"
    if property39 is None:
        return result
    prop_path = path + ".f4[kind=39]"
    wrapper = saved._message(property39, 49, prop_path)
    result["status"] = "payload_absent"
    if wrapper is None:
        return result
    data = saved._message(wrapper, 1, prop_path + ".f49")
    result["status"] = "config_absent"
    if data is None:
        return result
    data_path = prop_path + ".f49.f1"
    basic = saved._message(data, 1, data_path)
    inter = saved._message(data, 3, data_path)
    result["status"] = "basic_or_inter_info_absent"
    if basic is None or inter is None:
        return result
    stack_field = saved._one(basic, 1, saved.gil.WIRE_VARINT, data_path + ".f1")
    trade_field = saved._one(inter, 2, saved.gil.WIRE_VARINT, data_path + ".f3")
    # Omitted protobuf scalars are zero/false, never constructor defaults.
    stack = 0 if stack_field is None else stack_field.value
    trade = 0 if trade_field is None else trade_field.value
    if not 0 <= stack <= 0xFFFFFFFF:
        raise saved.SavedBindingError(f"{data_path}.f1.f1: stackLimit exceeds uint32")
    if trade not in (0, 1):
        raise saved.SavedBindingError(f"{data_path}.f3.f2: invalid isTradeable boolean")
    verified = result["nameMatches"] and bool(trade) and stack == expected_stack_limit
    result.update(propertiesRead=True, stackLimit=stack, isTradeable=bool(trade),
                  stackLimitFieldPresent=stack_field is not None,
                  isTradeableFieldPresent=trade_field is not None,
                  savedPropertiesVerified=verified,
                  status="saved_properties_match" if verified else "saved_properties_mismatch")
    return result


def read_saved_item_properties(gil_path: str | Path, *, level_id: int,
                              expected_items: dict[int, str],
                              expected_stack_limit: int = 9999) -> dict:
    """Compare explicit item IDs/names with one stable level-save snapshot."""
    saved._uint(level_id, "level_id")
    saved._uint(expected_stack_limit, "expected_stack_limit")
    if not expected_items:
        raise saved.SavedBindingError("expected_items must contain actual item IDs and names")
    for item_id, name in expected_items.items():
        saved._uint(item_id, "item_id")
        if not isinstance(name, str) or not name or "\0" in name:
            raise saved.SavedBindingError("expected item names must be nonempty strings without NUL")
    path = Path(gil_path).resolve()
    blob = path.read_bytes()
    container = saved.gil.decode_container(blob)
    if container.subtype != saved.gil.SUBTYPE_LEVEL:
        raise saved.SavedBindingError("input is not a level container")
    root = saved.gil.parse_fields(container.payload)
    actual_level = saved._scalar(root, 1, "root", required=True)
    if actual_level != level_id:
        raise saved.SavedBindingError(f"embedded level ID {actual_level} != requested {level_id}")
    items = [_item(root, item_id, name, expected_stack_limit)
             for item_id, name in expected_items.items()]
    if path.read_bytes() != blob:
        raise saved.SavedBindingError("input file changed while being inspected")
    return {"schemaVersion": 1, "scope": "saved_ordinary_item_name_trade_stack_only",
            "levelId": actual_level, "items": items,
            "savedPropertiesVerified": all(item["savedPropertiesVerified"] for item in items),
            "file": {"path": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                     "size": len(blob), "stableAcrossRead": True},
            "nativeSaveExecutionVerified": False, "reopenVerified": False,
            "runtimeEffectiveVerified": False, "gameplayVerified": False,
            "limitations": ["The named settings exist in this file; this does not verify native save execution or reopening.",
                            "Shop goods, prices, purchase-to-bag behavior and planting are outside this check.",
                            "Other item flags, including automatic use, are not assigned a meaning."]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gil", required=True, type=Path)
    parser.add_argument("--level-id", required=True, type=int)
    parser.add_argument("--item", required=True, nargs=2, action="append", metavar=("ID", "NAME"))
    parser.add_argument("--stack-limit", type=int, default=9999)
    args = parser.parse_args(argv)
    try:
        expected = {}
        for value, name in args.item:
            item_id = int(value)
            if item_id in expected:
                raise saved.SavedBindingError("duplicate requested item ID")
            expected[item_id] = name
        result = read_saved_item_properties(args.gil, level_id=args.level_id,
                                           expected_items=expected,
                                           expected_stack_limit=args.stack_limit)
    except (ValueError, OSError) as exc:
        print(json.dumps({"savedPropertiesVerified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["savedPropertiesVerified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
