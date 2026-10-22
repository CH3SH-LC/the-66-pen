"""Read saved role bag and plot shop references; never modify the GIL.

Schema evidence: task-bb/role-binding-evidence.json (record locations),
task-ac/binding-contract.json (kind33 export), task-y/binding-contract.json
(kind35 export). This checks those references, not template contents or play.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/beyond-save"))
import gil_container as gil


class SavedBindingError(ValueError):
    """An input or the examined saved structure is not unambiguous."""


def _uint(value: int, label: str) -> int:
    if type(value) is not int or not 0 < value <= 0xFFFFFFFF:
        raise SavedBindingError(f"{label} must be a positive uint32")
    return value


def _one(fields, number, wire, path, *, required=False):
    found = [f for f in fields if f.number == number]
    if len(found) > 1:
        raise SavedBindingError(f"{path}.f{number}: duplicate singular field")
    if not found:
        if required:
            raise SavedBindingError(f"{path}.f{number}: missing required field")
        return None
    if found[0].wire_type != wire:
        raise SavedBindingError(f"{path}.f{number}: wrong wire type")
    return found[0]


def _scalar(fields, number, path, *, default=None, required=False):
    value = _one(fields, number, gil.WIRE_VARINT, path, required=required)
    return default if value is None else value.value


def _message(fields, number, path, *, required=False):
    value = _one(fields, number, gil.WIRE_LENGTH, path, required=required)
    return None if value is None else gil.parse_fields(value.data)


def _messages(fields, number, path):
    result = []
    for f in fields:
        if f.number != number:
            continue
        if f.wire_type != gil.WIRE_LENGTH:
            raise SavedBindingError(f"{path}.f{number}: wrong repeated-message wire type")
        result.append(gil.parse_fields(f.data))
    return result


def _record(root, collection, object_id):
    path = f"root{collection}.f1[id={object_id}]"
    block = _message(root, collection, "root")
    if block is None:
        return path, None
    matches = [r for r in _messages(block, 1, f"root{collection}")
               if _scalar(r, 1, f"root{collection}.f1") == object_id]
    if len(matches) > 1:
        raise SavedBindingError(f"{path}: duplicate object ID")
    return path, matches[0] if matches else None


def _reference(fields, path):
    template_id = _scalar(fields, 2, path, default=0)
    if not 0 <= template_id <= 0xFFFFFFFF:
        raise SavedBindingError(f"{path}.f2: reference ID exceeds uint32")
    classification = _scalar(fields, 1, path, default=0)
    return {"templateId": template_id, "classification": classification,
            "classificationMatchesId": classification == ((template_id >> 30) & 1)}


def _component(record, group, kind, path):
    if record is None:
        return None
    matches = [c for c in _messages(record, group, path)
               if _scalar(c, 1, f"{path}.f{group}") == kind]
    if len(matches) > 1:
        raise SavedBindingError(f"{path}.f{group}: duplicate component kind {kind}")
    return matches[0] if matches else None


def _binding(record, group, kind, expected_id, path):
    component = _component(record, group, kind, path)
    component_path = f"{path}.f{group}[kind={kind}]"
    result = {"path": component_path, "recordPresent": record is not None,
              "componentPresent": component is not None, "kind": kind,
              "expectedTemplateId": expected_id, "enabled": False,
              "status": "record_absent" if record is None else "component_absent",
              "referenceMatches": False, "entries": []}
    if component is None:
        return result
    enabled = _scalar(component, 2, component_path, default=0)
    if enabled not in (0, 1):
        raise SavedBindingError(f"{component_path}.f2: invalid enabled boolean")
    result["enabled"] = bool(enabled)
    payload_field = 44 if kind == 33 else 46
    other_payload = 46 if kind == 33 else 44
    if any(f.number == other_payload for f in component):
        raise SavedBindingError(f"{component_path}: conflicting bag/shop oneof payload")
    payload = _message(component, payload_field, component_path)
    if payload is None:
        result["status"] = "payload_absent"
        return result
    payload_path = f"{component_path}.f{payload_field}"
    if kind == 33:
        ref = _message(payload, 1, payload_path)
        if ref is None:
            result["status"] = "reference_absent"
            return result
        result["reference"] = _reference(ref, payload_path + ".f1")
        result["referencePath"] = payload_path + ".f1.f2"
        result["referenceMatches"] = (result["reference"]["templateId"] == expected_id
                                      and result["reference"]["classificationMatchesId"])
    else:
        indices = set()
        for entry in _messages(payload, 1, payload_path):
            entry_path = payload_path + ".f1"
            index = _scalar(entry, 1, entry_path, default=0)
            if not 0 < index <= 0x7FFFFFFF or index in indices:
                raise SavedBindingError(f"{entry_path}: nonpositive or duplicate shop entry index")
            indices.add(index)
            ref = _message(entry, 2, entry_path)
            result["entries"].append({"index": index, "reference": None if ref is None
                                      else _reference(ref, entry_path + ".f2")})
        matches = [e for e in result["entries"] if e["reference"] is not None
                   and e["reference"]["templateId"] == expected_id
                   and e["reference"]["classificationMatchesId"]]
        if len(matches) > 1:
            raise SavedBindingError(f"{payload_path}: multiple entries reference the requested shop")
        result["matchingShopIndices"] = [e["index"] for e in matches]
        result["referencePath"] = payload_path + ".f1.f2.f2"
        result["referenceMatches"] = len(matches) == 1
    result["status"] = "reference_matches" if result["referenceMatches"] else "reference_mismatch"
    return result


def validate_saved_bindings(gil_path: str | Path, *, level_id: int, character_id: int,
                            plot_id: int, bag_template_id: int, shop_template_id: int) -> dict:
    """Inspect one file. Missing references are a report, malformed input raises.

    Level identity must be embedded in this bounded checker. A user-supplied ID
    or renamed filename alone cannot prove the level of an arbitrary backup.
    """
    for label, value in (("level_id", level_id), ("character_id", character_id),
                         ("plot_id", plot_id), ("bag_template_id", bag_template_id),
                         ("shop_template_id", shop_template_id)):
        _uint(value, label)
    if character_id == plot_id or bag_template_id == shop_template_id:
        raise SavedBindingError("character/plot and bag/shop must respectively be distinct")
    path = Path(gil_path).resolve()
    blob = path.read_bytes()
    container = gil.decode_container(blob)
    if container.subtype != gil.SUBTYPE_LEVEL:
        raise SavedBindingError("input is not a level container")
    root = gil.parse_fields(container.payload)
    actual_level = _scalar(root, 1, "root", required=True)
    if actual_level != level_id:
        raise SavedBindingError(f"embedded level ID {actual_level} != requested {level_id}")
    template_path, character_template = _record(root, 4, character_id)
    instance_path, character_instance = _record(root, 5, character_id)
    plot_path, plot = _record(root, 5, plot_id)
    template_base = None if character_template is None else _scalar(character_template, 2, template_path)
    instance_base = None if character_instance is None else _scalar(character_instance, 8, instance_path)
    role_ref = None if character_instance is None else _message(character_instance, 2, instance_path)
    source_id = None if role_ref is None else _scalar(role_ref, 1, instance_path + ".f2")
    role_link = {"templateBaseConfig": template_base, "instanceBaseConfig": instance_base,
                 "instanceTemplateId": source_id, "expectedCharacterId": character_id,
                 "verified": template_base == 1000001 and instance_base == 1000001
                 and source_id == character_id}
    template_bag = _binding(character_template, 8, 33, bag_template_id, template_path)
    instance_bag = _binding(character_instance, 7, 33, bag_template_id, instance_path)
    plot_shop = _binding(plot, 7, 35, shop_template_id, plot_path)
    locations = (template_bag, instance_bag, plot_shop)
    references_verified = role_link["verified"] and all(r["referenceMatches"] for r in locations)
    enabled = all(r["enabled"] for r in locations)
    # A concurrently saved/replaced input must be read again by the caller.
    if path.read_bytes() != blob:
        raise SavedBindingError("input file changed while being inspected")
    return {"schemaVersion": 1, "scope": "saved_role_bag_and_plot_shop_references_only",
            "file": {"path": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                     "size": len(blob), "stableAcrossRead": True},
            "levelId": actual_level, "levelIdentitySource": "embedded_root1",
            "characterLink": role_link, "characterTemplateBag": template_bag,
            "characterInstanceBag": instance_bag, "plotShop": plot_shop,
            "savedReferencesVerified": references_verified,
            "allReferencedComponentsEnabled": enabled,
            "savedBindingsVerified": references_verified and enabled,
            "templateDefinitionsChecked": False, "triggerBindingsChecked": False,
            "nativeSaveExecutionVerified": False, "reopenVerified": False,
            "runtimeEffectiveVerified": False, "gameplayVerified": False,
            "limitations": ["Only the named role/plot references and exported enable flags are checked.",
                            "Template contents and trigger/event 92 mapping are outside this check.",
                            "Saved shop index is reported without claiming gameplay-node index semantics.",
                            "File evidence does not prove native save execution, reopen, or gameplay."]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gil", required=True, type=Path)
    for name in ("level-id", "character-id", "plot-id", "bag-template-id", "shop-template-id"):
        parser.add_argument("--" + name, type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_saved_bindings(args.gil, level_id=args.level_id,
            character_id=args.character_id, plot_id=args.plot_id,
            bag_template_id=args.bag_template_id, shop_template_id=args.shop_template_id)
    except (OSError, ValueError) as exc:
        print(json.dumps({"savedBindingsVerified": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["savedBindingsVerified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
