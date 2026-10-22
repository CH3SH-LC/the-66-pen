"""Read one saved Shop template's goodSourceType and its proven value1 label.

Current-build proof: task-bh/source-export-proof.json. Native edit +0x48 is
copied unchanged to protobuf86818 +0x40, emitted as field1 (varint tag8).
Current-build task-shop-source-label/custom-source-proof.json proves value1
selects the native Table_ShopTemplate_SellCustomGoods dialog. Other values
remain unnamed. This is a saved configuration check, not a trade; no setter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import saved_farming_bindings as saved


def read_saved_shop_source(gil_path: str | Path, *, level_id: int, shop_template_id: int) -> dict:
    """Read root15.f1[shop].f4[kind48].f58.f1.f1 from a stable GIL snapshot."""
    saved._uint(level_id, "level_id")
    saved._uint(shop_template_id, "shop_template_id")
    path = Path(gil_path).resolve()
    blob = path.read_bytes()
    container = saved.gil.decode_container(blob)
    if container.subtype != saved.gil.SUBTYPE_LEVEL:
        raise saved.SavedBindingError("input is not a level container")
    root = saved.gil.parse_fields(container.payload)
    actual_level = saved._scalar(root, 1, "root", required=True)
    if actual_level != level_id:
        raise saved.SavedBindingError(f"embedded level ID {actual_level} != requested {level_id}")
    record_path, record = saved._record(root, 15, shop_template_id)
    field_path = record_path + ".f4[kind=48].f58.f1.f1"
    result = {"schemaVersion": 1, "scope": "saved_shop_goodSourceType_only",
              "levelId": actual_level, "shopTemplateId": shop_template_id,
              "recordPath": record_path, "sourcePath": field_path,
              "templatePresent": record is not None, "templateSubtype": None,
              "propertyPresent": False, "sourceRead": False, "sourceFieldPresent": False,
              "sourceValue": None, "sourceLabel": "unknown", "sourceLabelVerified": False,
              "customListVerified": False, "status": "template_absent",
              "nativeSaveExecutionVerified": False, "runtimeEffectiveVerified": False,
              "runtimeTradeVerified": False,
              "gameplayVerified": False, "deploymentReady": False,
              "mapping": {"editDefinition": 45868, "editField": "+0x48",
                          "fieldHash": "0x869dd4c5", "fieldName": "goodSourceType",
                          "enumDefinition": 84570, "protobufDefinition": 86818,
                          "protobufField": 1, "protobufTag": 8,
                          "exportPreservesNumericValue": True,
                          "value1SemanticProof": ".runtime/scratch/overnight-features-20261013/task-shop-source-label/custom-source-proof.json"},
              "limitations": ["Only value1 is mapped to CustomList; other numeric values remain unnamed.",
                              "CustomList configuration does not verify runtime goods, payment or delivery to a character bag.",
                              "This reads one saved template only; it does not change or invoke the game."]}
    if record is not None:
        result["templateSubtype"] = saved._scalar(record, 2, record_path)
        if result["templateSubtype"] != 17:
            result["status"] = "wrong_template_subtype"
        else:
            properties = [p for p in saved._messages(record, 4, record_path)
                          if saved._scalar(p, 1, record_path + ".f4") == 48]
            if len(properties) > 1:
                raise saved.SavedBindingError(f"{record_path}: duplicate Shop property48")
            result["propertyPresent"] = bool(properties)
            result["status"] = "property_absent"
            if properties:
                property_path = record_path + ".f4[kind=48]"
                wrapper = saved._message(properties[0], 58, property_path)
                result["status"] = "payload_absent"
                if wrapper is not None:
                    config = saved._message(wrapper, 1, property_path + ".f58")
                    result["status"] = "config_absent"
                    if config is not None:
                        field = saved._one(config, 1, saved.gil.WIRE_VARINT, property_path + ".f58.f1")
                        number = 0 if field is None else field.value
                        # Protobuf int32 can represent negative values as a sign-extended varint.
                        if not (0 <= number <= 0x7FFFFFFF or 0xFFFFFFFF80000000 <= number <= 0xFFFFFFFFFFFFFFFF):
                            raise saved.SavedBindingError(f"{field_path}: invalid int32 representation")
                        if number >= 0xFFFFFFFF80000000:
                            number -= 1 << 64
                        result.update(sourceRead=True, sourceFieldPresent=field is not None,
                                      sourceValue=number, status="numeric_source_read_label_unknown")
                        if number == 1:
                            result.update(sourceLabel="CustomList", sourceLabelVerified=True,
                                          customListVerified=True, status="custom_list_source_verified")
    if path.read_bytes() != blob:
        raise saved.SavedBindingError("input file changed while being inspected")
    result["file"] = {"path": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                      "size": len(blob), "stableAcrossRead": True}
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gil", required=True, type=Path)
    parser.add_argument("--level-id", required=True, type=int)
    parser.add_argument("--shop-template-id", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        result = read_saved_shop_source(args.gil, level_id=args.level_id, shop_template_id=args.shop_template_id)
    except (ValueError, OSError) as exc:
        print(json.dumps({"sourceRead": False, "sourceLabelVerified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # Exit0 means the field was read; inspect customListVerified separately.
    return 0 if result["sourceRead"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
