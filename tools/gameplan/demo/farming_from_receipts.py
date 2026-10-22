"""Compile farming from independently revalidated native resource receipts.

This entry never reads *-acceptance.json as authority, invokes a native helper,
reviews a write, queues a graph, or saves a level. It calls the existing raw
currency/item/binding validate_run APIs, then builds the ordinary native_shop
graph. Supplied region indices and storage slots remain explicit prerequisites;
receipt registration/binding is not event92 delivery or a playable character bag.

Run with ``python -m tools.gameplan.demo.farming_from_receipts --help``.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

from ..builder import GraphBuilder
from ..plan import PlanError
from .farming_interactive import FarmInteractiveConfig, build_plan as build_interactive

ROOT = Path(__file__).resolve().parents[3]
AUTHORING = ROOT / "tools/game-executor/template-authoring"
SESSION_FIELDS = ("schemaVersion", "pid", "tid", "window", "windowClass",
                  "processCreation", "threadCreation", "image")


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _runtime_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    _require(path.is_relative_to(ROOT / ".runtime") and path != ROOT / ".runtime",
             "FARM_EVIDENCE_OUTSIDE_PROJECT_RUNTIME")
    return path


def _acceptors():
    # These existing standalone modules use sibling imports. Import only the
    # project's own modules; their validate_run APIs perform disk reads only.
    directory = str(AUTHORING)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    modules = {}
    for key in ("currency", "item", "binding"):
        module = importlib.import_module("accept_" + key)
        _require(Path(module.__file__).resolve() == AUTHORING / ("accept_" + key + ".py"),
                 "FARM_ACCEPTOR_MODULE_COLLISION:" + key)
        modules[key] = module
    return modules


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unchanged(run, hashes):
    _require(type(hashes) is dict and {"prepared.json", "stdout.jsonl"} <= hashes.keys(),
             "FARM_VALIDATED_INPUT_HASHES_REQUIRED")
    for name, digest in hashes.items():
        path = (run / name).resolve()
        _require(path.is_relative_to(run) and path != run and _hash(path) == digest,
                 "FARM_RECEIPT_CHANGED:" + str(run) + ":" + name)


def _validated(module, run, action):
    accepted = module.validate_run(run)  # Recomputes raw ABI, transport and deltas.
    _require(accepted.get("ok") is True and accepted.get("action") == action and
             Path(accepted["run"]).resolve() == run, "FARM_WRONG_VALIDATED_ACTION:" + action)
    _unchanged(run, accepted["inputHashes"])
    prepared = module.requests.read_json(run / "prepared.json")
    _require(prepared["levelId"] == accepted["levelId"], "FARM_VALIDATED_LEVEL_MISMATCH")
    session = {key: prepared["session"][key] for key in SESSION_FIELDS}
    return {"run": run, "accepted": accepted, "session": session}


def compile_from_receipts(*, currency_run, seed_run, crop_run, bag_run, shop_run,
        character_entity_id: int, plot_entity_id: int,
        farm_trigger_index: int, sell_trigger_index: int,
        item_slot: str, currency_slot: str, variable_flag_slot: str, shop_flag_slot: str,
        name: str = "MW_API_FARM_INTERACTIVE", growth_seconds: float = 10.0,
        seed_price: int = 2, sale_price: int = 10,
        starter_seed_count: int = 3, starter_currency_amount: int = 20) -> dict:
    """Return a validated batch plan and compile-only CLI argv, without dispatch.

    The expected character and plot IDs are explicit identity constraints. They
    must match the raw binding results; the role is not inferred from an ID band.
    Region indices must come from actual native readback and have no default
    here. The first valid interaction supplies three seeds and twenty currency
    by default, so a new character can start farming; zero disables each grant.
    """
    for key, value in (("character", character_entity_id), ("plot", plot_entity_id)):
        _require(type(value) is int and 0 < value < 2**32, "FARM_INVALID_ENTITY:" + key)
    _require(character_entity_id != plot_entity_id, "FARM_CHARACTER_AND_PLOT_MUST_DIFFER")
    runs = {key: _runtime_path(value) for key, value in (
        ("currency", currency_run), ("seed", seed_run), ("crop", crop_run),
        ("bag", bag_run), ("shop", shop_run))}
    _require(len(set(runs.values())) == 5, "FARM_DISTINCT_ACTION_RUNS_REQUIRED")
    modules = _acceptors()
    sources = {key: _validated(modules[which], runs[key], action) for key, which, action in (
        ("currency", "currency", "create-currency"), ("seed", "item", "create-item"),
        ("crop", "item", "create-item"), ("bag", "binding", "bind-bag"),
        ("shop", "binding", "bind-shop"))}
    level = sources["currency"]["accepted"]["levelId"]
    session = sources["currency"]["session"]
    for key, source in sources.items():
        _require(source["accepted"]["levelId"] == level, "FARM_CROSS_LEVEL:" + key)
        _require(source["session"] == session, "FARM_CROSS_SESSION:" + key)
    for key in ("currency", "seed", "crop"):
        _require(sources[key]["accepted"].get("catalogRegisteredVerified") is True,
                 "FARM_RESOURCE_NOT_REGISTERED:" + key)
    bag, shop = sources["bag"]["accepted"], sources["shop"]["accepted"]
    _require(bag.get("bindingVerified") is True and bag["entityId"] == character_entity_id,
             "FARM_BAG_OWNER_NOT_EXPECTED_CHARACTER")
    _require(shop.get("bindingVerified") is True and shop["entityId"] == plot_entity_id,
             "FARM_SHOP_OWNER_NOT_EXPECTED_PLOT")
    seed_id, crop_id, currency_id = (sources[key]["accepted"]["createdId"] for key in ("seed", "crop", "currency"))
    config = FarmInteractiveConfig(seed_id=seed_id, crop_id=crop_id, currency_id=currency_id,
        item_slot=item_slot, currency_slot=currency_slot, variable_flag_slot=variable_flag_slot,
        shop_flag_slot=shop_flag_slot, growth_seconds=growth_seconds,
        farm_trigger_index=farm_trigger_index, sell_trigger_index=sell_trigger_index,
        inventory_holder="entrant", sale_mode="native_shop", interaction_mode="proximity",
        seed_price=seed_price, sale_price=sale_price, shop_index=shop["shopIndex"],
        starter_seed_count=starter_seed_count, starter_currency_amount=starter_currency_amount)
    plan = build_interactive(config, name=name)

    def no_dispatch(_):
        raise AssertionError("receipt compiler cannot dispatch")

    builder = GraphBuilder(plan, no_dispatch, run_id="compile-only", entity_id=plot_entity_id)
    cli_args = ["farming-interactive", "--name", name]
    for option, value in (
        ("seed-id", seed_id), ("crop-id", crop_id), ("currency-id", currency_id),
        ("item-slot", item_slot), ("currency-slot", currency_slot),
        ("variable-flag-slot", variable_flag_slot), ("shop-flag-slot", shop_flag_slot),
        ("entity-id", plot_entity_id), ("farm-trigger-index", farm_trigger_index),
        ("sell-trigger-index", sell_trigger_index), ("shop-index", config.shop_index),
        ("growth-seconds", growth_seconds), ("seed-price", seed_price), ("sale-price", sale_price),
        ("starter-seeds", starter_seed_count), ("starter-currency", starter_currency_amount),
        ("sale-mode", "native_shop"), ("inventory-holder", "entrant"), ("interaction-mode", "proximity")):
        cli_args.extend(("--" + option, str(value)))
    # Ensure earlier inputs did not change while the other raw receipts/graph
    # were being validated. This is an offline interval check, not a live lease.
    for source in sources.values():
        _unchanged(source["run"], source["accepted"]["inputHashes"])
    return {
        "ok": True, "mode": "compile", "buildMode": "batch", "deploymentReady": False,
        "editorDispatchAttempted": False, "rawReceiptsRevalidated": True,
        "liveSessionRevalidated": False, "persistentSaveVerified": False, "gameRuntimeVerified": False,
        "levelId": level, "session": session, "characterEntityId": character_entity_id,
        "plotEntityId": plot_entity_id, "config": asdict(config),
        "bindings": {"bagTemplateId": bag["templateId"], "bagComponentId": bag["componentId"],
            "shopTemplateId": shop["templateId"], "shopComponentId": shop["componentId"], "shopIndex": config.shop_index},
        "summary": {"nodes": len(plan.nodes), "edges": len(plan.edges), "consts": len(plan.consts)},
        "plan": builder.batch_plan_json(), "cliModule": "tools.gameplan.cli", "cliArgs": cli_args,
        "sources": {key: {"run": str(source["run"]), "action": source["accepted"]["action"],
            "requestSha256": source["accepted"]["requestSha256"], "reviewSha256": source["accepted"]["reviewSha256"],
            "rawStdoutSha256": source["accepted"]["inputHashes"]["stdout.jsonl"],
            "acceptorSha256": source["accepted"]["acceptorSha256"]} for key, source in sources.items()},
        "prerequisites": {
            "triggerRegions": {"verified": False, "entityId": plot_entity_id,
                "farmIndex": farm_trigger_index, "sellIndex": sell_trigger_index,
                "source": "explicit-indices-require-native-region-readback"},
            "event92Delivery": {"verified": False, "expectedEntrant": "playable-character"},
            "valueSlots": {"verified": False, "requires": "current-native-slot-descriptor-readback"},
            "characterBackpack": {"bindingReadbackVerified": True, "entityId": character_entity_id,
                "playableAssignmentVerified": False, "templateSynchronizationVerified": False,
                "saveReadback": "role template root4/f8 and instance root5/f7 require separate verification"},
            "shopTemplateCustomList": {"verified": False, "templateId": shop["templateId"]},
            "starterDelivery": {"configured": bool(starter_seed_count or starter_currency_amount),
                "verified": False, "requires": "character bag/custom variables and starting seed or currency"},
            "plotCustomVariables": {"verified": False},
        },
        "note": "Validated registration/binding receipts supply IDs, not a live deployment or playable demo. "
                "CLI arguments compile only; a fresh bridge scope, remaining prerequisites and save/play acceptance are separate.",
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("currency", "seed", "crop", "bag", "shop"):
        parser.add_argument("--" + key + "-run", required=True, help="executed native action run; raw receipts are revalidated")
    for key in ("character-entity-id", "plot-entity-id", "farm-trigger-index", "sell-trigger-index"):
        parser.add_argument("--" + key, required=True, type=int)
    for key, choices in (("item-slot", ("int", "uint")), ("currency-slot", ("int", "uint", "enum")),
                         ("variable-flag-slot", ("bool", "enum")), ("shop-flag-slot", ("bool", "enum"))):
        parser.add_argument("--" + key, required=True, choices=choices)
    parser.add_argument("--name", default="MW_API_FARM_INTERACTIVE")
    parser.add_argument("--growth-seconds", type=float, default=10.0)
    parser.add_argument("--seed-price", type=int, default=2)
    parser.add_argument("--sale-price", type=int, default=10)
    parser.add_argument("--starter-seed-count", type=int, default=3)
    parser.add_argument("--starter-currency-amount", type=int, default=20)
    parser.add_argument("--out", help="optional new JSON output under project .runtime; never an input run")
    return parser


def main(argv=None):
    options = vars(build_parser().parse_args(argv))
    output = options.pop("out")
    try:
        path = _runtime_path(output) if output else None
        if path:
            _require(not path.exists(), "FARM_OUTPUT_ALREADY_EXISTS")
            _require(not any(path.is_relative_to(_runtime_path(options[key + "_run"]))
                             for key in ("currency", "seed", "crop", "bag", "shop")), "FARM_OUTPUT_OVERLAPS_EVIDENCE")
        result = compile_from_receipts(**options)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            result["output"] = str(path)
    except (OSError, ValueError, KeyError, TypeError, struct.error, PlanError) as error:
        print(json.dumps({"ok": False, "mode": "compile", "error": str(error),
            "editorDispatchAttempted": False, "deploymentReady": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
