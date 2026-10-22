"""Command-line entry point for the gameplan graphs.

    # 1. Offline: validate the farming plan and print every native call it WOULD make.
    python -m tools.gameplan.cli farming --currency-id 1115684864 --crop-id 1120000001 --food-id 1120000002

    # 2. Real machine: actually build it (needs a live bridge run id, and --entity-id to bind).
    python -m tools.gameplan.cli farming --run-id <32hex> --entity-id <id> \
        --currency-id … --crop-id … --food-id … --execute

    # 3. Read-only: see one graph's current shape and diff it against its plan.
    python -m tools.gameplan.cli graph-status --graph-id <id> --run-id <uuid> --name MW_API_…

The default is a dry run: nothing is dispatched.  ``--execute`` is the only
switch that touches the editor, and even then the CLI never claims persistence —
that needs a native ``save`` plus an independent ``.gil`` readback.

``graph-status`` is the one subcommand that is neither a dry run nor a write: it
inspects a live graph through a single read-only ``author.py graph inspect`` and
never emits create/add/wire/value/bind.  It refuses to run without an explicit
``--run-id``.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from pathlib import Path

from .builder import _AUTHOR_PY, GraphBuilder, request_id, simulated_runner, subprocess_runner
from .demo.farming import FarmConfig, build_plan
from .plan import GRAPH_NAME_RE, PlanError

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _farm_config(args) -> FarmConfig:
    return FarmConfig(
        currency_id=args.currency_id,
        crop_id=args.crop_id,
        food_id=args.food_id,
        item_slot=args.item_slot,
    )


def cmd_farming(args) -> int:
    if args.full:
        from .demo.farming_full import FarmFullConfig, build_plan as build_full_plan

        plan = build_full_plan(
            FarmFullConfig(
                currency_id=args.currency_id,
                crop_id=args.crop_id,
                food_id=args.food_id,
                item_slot=args.item_slot,
                currency_slot=args.currency_slot,
                unit_price=args.unit_price,
            ),
            name=args.name,
        )
    else:
        plan = build_plan(_farm_config(args), name=args.name)
    queue = args.queue_dir or _repo_default_queue()

    if not args.execute:
        # Dry run: walk the sequence against a simulated editor and report the argv
        # it produces.  Nothing is dispatched.
        builder = GraphBuilder(plan, simulated_runner(), run_id=args.run_id or "dry-run",
                               entity_id=args.entity_id, queue_dir=queue)
        result = builder.build()
        calls = [{"step": s.summary()["step"], "argv": s.argv} for s in result.steps]
        print(json.dumps({
            "mode": "dry-run",
            "plan": plan.name,
            "nodes": len(plan.nodes), "edges": len(plan.edges), "consts": len(plan.consts),
            "calls": calls,
            "note": "no native call made; re-run with --execute and a live --run-id",
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.run_id:
        print("error: --execute requires --run-id (a live bridge scope)", file=sys.stderr)
        return 2
    builder = GraphBuilder(plan, subprocess_runner(args.python), run_id=args.run_id,
                           entity_id=args.entity_id, queue_dir=queue, python=args.python,
                           max_ops=args.max_ops)
    result = builder.build_batch() if args.batch else builder.build()
    evidence = result.evidence()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.partial:
        return 3            # resumable: reload the scope and run again
    return 0 if result.ok else 1


def _repo_default_queue() -> Path:
    return _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"


def _repo_default_scratch() -> Path:
    return _REPO_ROOT / ".runtime" / "scratch"


def _interactive_output_path(value: str | None) -> Path | None:
    """Resolve optional output from the repository, never the caller's cwd."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    path = path.resolve()
    runtime = (_REPO_ROOT / ".runtime").resolve()
    if not path.is_relative_to(runtime) or path == runtime:
        raise ValueError("--out must name a file under this repository's .runtime directory")
    return path


def cmd_farming_interactive(args, runner=None) -> int:
    """Compile by default; explicitly requested execution builds and binds once.

    Compile mode only serializes the validated plan. It never calls a runner or
    manufactures editor receipts. Execution uses the existing batch builder and
    author.py lease/identity checks; neither this command nor a successful build
    verifies templates, scene triggers, gameplay or persistence.
    """
    from .demo.farming_interactive import FarmInteractiveConfig, build_plan as build_interactive

    try:
        if args.execute:
            if not _valid_run_id(args.run_id) or uuid.UUID(args.run_id).int == 0:
                raise ValueError("--execute requires a nonzero UUID --run-id for the current live bridge scope")
            if args.entity_id is None:
                raise ValueError("--execute requires an explicit --entity-id to bind the graph")
        if args.entity_id is not None and not 0 < args.entity_id < 2 ** 32:
            raise ValueError("--entity-id must be a positive uint32")
        output = _interactive_output_path(args.out)
        config = FarmInteractiveConfig(
            seed_id=args.seed_id, crop_id=args.crop_id, currency_id=args.currency_id,
            item_slot=args.item_slot, currency_slot=args.currency_slot,
            variable_flag_slot=args.variable_flag_slot, growth_seconds=args.growth_seconds,
            seed_cost=args.seed_cost, harvest_gain=args.harvest_gain,
            sale_count=args.sale_count, sale_price=args.sale_price,
            farm_trigger_index=args.farm_trigger_index, sell_trigger_index=args.sell_trigger_index,
            state_name=args.state_name, timer_name=args.timer_name,
            inventory_holder=args.inventory_holder,
            interaction_mode=args.interaction_mode, skill_target=args.skill_target,
            sale_mode=args.sale_mode, seed_price=args.seed_price,
            shop_index=args.shop_index, shop_flag_slot=args.shop_flag_slot,
            starter_seed_count=args.starter_seeds,
            starter_currency_amount=args.starter_currency,
            starter_guard=args.starter_guard,
            farm_center=args.farm_center, sell_center=args.sell_center,
            interaction_radius=args.interaction_radius, exit_radius=args.exit_radius,
            poll_seconds=args.poll_seconds,
            host_key=args.host_key or (str(args.entity_id) if args.entity_id else None),
        )
        plan = build_interactive(config, name=args.name)
    except (ValueError, PlanError, OSError) as error:
        print(f"error: {error}; nothing was dispatched", file=sys.stderr)
        return 2

    def no_dispatch(argv):
        raise RuntimeError("compile mode cannot dispatch editor requests")

    run = (runner if runner is not None else subprocess_runner(args.python)) if args.execute else no_dispatch
    builder = GraphBuilder(plan, run, run_id=args.run_id or "compile-only",
        entity_id=args.entity_id, queue_dir=args.queue_dir or _repo_default_queue(), python=args.python)
    evidence = {
        "ok": True,
        "mode": "execute" if args.execute else "compile",
        "buildMode": "batch",
        "name": plan.name,
        "summary": {"nodes": len(plan.nodes), "edges": len(plan.edges), "consts": len(plan.consts)},
        "entityId": args.entity_id,
        "inventoryHolder": config.inventory_holder,
        "interactionMode": config.interaction_mode,
        "saleMode": config.sale_mode,
        "starterResources": {
            "enabled": bool(config.starter_seed_count or config.starter_currency_amount),
            "seedCount": config.starter_seed_count,
            "currencyAmount": config.starter_currency_amount,
            "recipient": "skill-caster-character" if config.interaction_mode == "skill" else "entrant-character",
            "guardName": config.starter_guard,
            "guardScope": "character-lifetime-shared-across-plots",
            "trigger": "first-valid-plant-or-sell-interaction",
            "failurePolicy": "mark-before-grants; partial-or-failed-delivery-is-not-automatically-retried",
            "lifecycleBoundary": "same-character-reentry-or-revival-does-not-reset; new-character-can-claim-again",
            "nativeDeliveryVerified": False,
        },
        "prerequisites": {
            "templates": {"status": "requires-independent-readback", "seedId": config.seed_id,
                          "cropId": config.crop_id, "currencyId": config.currency_id},
            "triggers": {"status": "requires-independent-readback", "entityId": args.entity_id,
                         "farmIndex": config.farm_trigger_index, "sellIndex": config.sell_trigger_index},
            "valueSlots": {"status": "requires-live-slot-readback", "item": config.item_slot,
                           "currency": config.currency_slot, "variableFlags": config.variable_flag_slot},
            "customVariableComponent": {"status": "requires-independent-readback", "entityId": args.entity_id},
            "startingSeeds": {"status": "required-in-holder-inventory", "minimum": config.seed_cost},
        },
        "editorDispatchAttempted": False,
        "persistentSaveVerified": False,
        "gameRuntimeVerified": False,
        "note": "IDs and slots are caller supplied, not verified by compilation. "
                "Native shop mode delegates payment and item exchange to the engine. "
                "Template/component creation, native save and play verification remain required.",
    }
    if config.interaction_mode == "skill":
        evidence["prerequisites"].pop("triggers")
        evidence["prerequisites"]["skillNotification"] = {
            "status": "requires-native-delivery-and-character-caster-verification",
            "parameter1": {"plant": "plant-or-harvest", "sell": "sell-or-open-shop"},
            "parameter2": config.skill_target,
            "targetRule": "unique-plot-tag; all nonmatching notifications are ignored",
            "templateCreated": False,
        }
    if config.interaction_mode == "distance":
        evidence["prerequisites"].pop("triggers")
        evidence["prerequisites"]["distanceInteraction"] = {
            "status": "requires-world-centers-and-single-character-runtime-verification",
            "farmCenter": list(config.farm_center), "sellCenter": list(config.sell_center),
            "interactionRadius": config.interaction_radius, "exitRadius": config.exit_radius,
            "pollSeconds": config.poll_seconds, "hostKey": config.host_key,
            "characterSource": "248 players; 258 roles; process only list length exactly 1",
            "entryRule": "distance <= interaction radius; latch before action",
            "rearmRule": "outside both exit radii; standing still never repeats",
            "collisionComponentRequired": False,
            "sampledMovement": True,
        }
        evidence["starterResources"]["recipient"] = "located-single-character"
    if config.sale_mode == "native_shop":
        evidence["prerequisites"]["shopComponent"] = {
            "status": "requires-independent-readback", "entityId": args.entity_id,
            "shopIndex": config.shop_index, "shopType": "custom", "flagSlot": config.shop_flag_slot,
        }
        evidence["prerequisites"].pop("startingSeeds")
        evidence["prerequisites"]["startingResources"] = {
            "status": "requires-at-least-one-source-in-character-backpack",
            "oneOf": [{"seedCount": config.seed_cost}, {"currencyAmount": config.seed_price}],
        }
    if evidence["starterResources"]["enabled"]:
        evidence["prerequisites"]["characterStarterGuard"] = {
            "status": "requires-character-bag-and-custom-variable-component-readback",
            "name": config.starter_guard,
            "resetOnEntryOrRevival": False,
        }
        if config.inventory_holder == "entrant":
            if config.sale_mode == "native_shop" and (
                    config.starter_seed_count >= config.seed_cost
                    or config.starter_currency_amount >= config.seed_price):
                evidence["prerequisites"]["startingResources"]["status"] = "starter-grant-configured-runtime-unverified"
            elif config.sale_mode == "direct" and config.starter_seed_count >= config.seed_cost:
                evidence["prerequisites"]["startingSeeds"]["status"] = "starter-grant-configured-runtime-unverified"
    if args.execute:
        result = builder.build_batch(plan_path=_repo_default_scratch() / f"{plan.name}-plan.json")
        evidence.update({"ok": result.ok, "editorDispatchAttempted": bool(result.steps), "build": result.evidence()})
        code = 3 if result.partial else (0 if result.ok else 1)
    else:
        evidence["plan"] = builder.batch_plan_json()
        code = 0
    text = json.dumps(evidence, ensure_ascii=False, indent=2)
    print(text)
    if output is not None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
        except OSError as error:
            print(f"error: output could not be written: {error}; inspect the printed execution evidence", file=sys.stderr)
            return 1
    return code


# -- graph-status: read one graph, diff it against its plan -------------------

def _valid_run_id(value: str | None) -> bool:
    """A bridge run id is a UUID (``author.py`` parses it with ``uuid.UUID``)."""
    if not value:
        return False
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _excess(seq: list, other: list) -> list:
    """The elements of ``seq`` left over once ``other`` has absorbed its share."""
    budget = Counter(other)
    extra = []
    for item in seq:
        if budget.get(item, 0) > 0:
            budget[item] -= 1
        else:
            extra.append(item)
    return extra


def _project(seq: list, common: Counter) -> list:
    """``seq`` restricted to ``common``'s first-N occurrences, order preserved."""
    budget = Counter(common)
    out = []
    for item in seq:
        if budget.get(item, 0) > 0:
            budget[item] -= 1
            out.append(item)
    return out


def diff_node_lists(planned_defs, inspected_defs) -> dict:
    """Diff an inspected node list against a plan, three ways.

    The editor returns instance ids plus definition ids; the plan only names
    definitions (it has no instance ids -- the editor assigns those).  So the
    comparison is on the **sequence of definition ids**, and it uses multiset
    arithmetic rather than set arithmetic: a plan that holds two identical nodes
    must not read as clean when the editor holds one.  ``reordered`` is decided
    on the order of the ids the two lists *share*, so a graph that has both moved
    nodes and gained or lost one still reports the movement.
    """
    planned = [int(d) for d in planned_defs]
    inspected = [int(d) for d in inspected_defs]
    added = _excess(inspected, planned)      # in the editor, absent from the plan
    removed = _excess(planned, inspected)    # in the plan, absent from the editor
    common = Counter(planned) & Counter(inspected)
    plan_projection = _project(planned, common)
    edit_projection = _project(inspected, common)
    mismatches = [
        {"index": i, "planned": p, "inspected": q}
        for i, (p, q) in enumerate(zip(plan_projection, edit_projection)) if p != q
    ]
    return {
        "clean": not added and not removed and not mismatches,
        "plannedDefinitionIds": planned,
        "inspectedDefinitionIds": inspected,
        "added": added,
        "removed": removed,
        "reordered": bool(mismatches),
        "orderMismatches": mismatches,
    }


def _read_plan(path: Path) -> tuple[dict, list[int] | None]:
    """Read a ``build-plan`` node list if the file exists; never a hard failure."""
    info: dict = {"path": str(path), "found": False}
    if not path.is_file():
        return info, None
    info["found"] = True
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
        definitions = [int(node["definitionId"]) for node in plan["nodes"]]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        info["error"] = f"{type(error).__name__}: {error}"
        return info, None
    info.update({
        "nodeCount": len(definitions),
        "nodeDefinitionIds": definitions,
        "edges": len(plan.get("edges") or []),
        "values": len(plan.get("values") or []),
    })
    return info, definitions


def cmd_graph_status(args, runner=None) -> int:
    """Inspect one live graph and diff its nodes against its plan.  Read-only.

    Exactly one dispatch is ever made: ``author.py graph inspect`` (a read op,
    ``mutating=False``; ``author.py:634``).  This command never emits
    create/add/wire/value/bind -- the guard below makes that structural.  It also
    requires an explicit ``--run-id``: a graph id is a function of the save, so
    nothing is inferred and nothing from a previous run is reused.

    Exit codes: 0 = inspected, no drift (or no plan to compare); 1 = the inspect
    itself failed; 2 = the command was called wrong; 4 = inspected, but the live
    graph has drifted from its plan (added / removed / reordered).
    """
    if not _valid_run_id(args.run_id):
        print("error: --run-id is required and must be a bridge run id (a UUID); "
              "it is never inferred or reused", file=sys.stderr)
        return 2
    if args.name is None:
        print("error: --name is required to inspect: author.py graph inspect keys the graph "
              "by name, so a bare --graph-id is refused by the adapter "
              "(AUTHOR_GRAPH_IDENTITY_MISMATCH); nothing was dispatched", file=sys.stderr)
        return 2
    if not GRAPH_NAME_RE.match(args.name):
        print(f"error: --name must match {GRAPH_NAME_RE.pattern}", file=sys.stderr)
        return 2
    if not 0 < args.graph_id < 2 ** 32:
        print("error: --graph-id must be a positive uint32", file=sys.stderr)
        return 2

    queue = Path(args.queue_dir) if args.queue_dir else _repo_default_queue()
    run = runner if runner is not None else getattr(args, "runner", None)
    if run is None:
        run = subprocess_runner(args.python)

    request = request_id("graph-status", "inspect", args.name, args.graph_id, args.run_id)
    argv = [
        args.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", str(queue),
        "graph", "inspect",
        "--request-id", request,
        "--run-id", args.run_id,
        "--name", args.name,
        "--graph-id", str(args.graph_id),
    ]
    # Structural guarantee: this subcommand is read-only and can only ever read.
    if argv[argv.index("graph") + 1] != "inspect":
        raise AssertionError("graph-status must only ever dispatch `inspect`")

    result = run(argv)
    if not isinstance(result, dict):
        print(json.dumps({"mode": "graph-status", "ok": False,
                          "error": f"runner returned {type(result).__name__}"},
                         ensure_ascii=False, indent=2))
        return 1

    backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    if result.get("ok") is not True:
        print(json.dumps({
            "mode": "graph-status", "ok": False, "graphId": args.graph_id, "name": args.name,
            "requestId": request, "error": result.get("error") or result,
            "call": {"action": "inspect", "argv": argv},
        }, ensure_ascii=False, indent=2))
        return 1

    nodes = [n for n in (backend.get("nodes") or []) if isinstance(n, dict)]
    inspected_defs = [n.get("definitionId") for n in nodes]
    bound = [int(entity) for entity in (backend.get("boundEntityIds") or [])]

    plan_info, plan_defs = _read_plan(Path(args.scratch_dir) / f"{args.name}-plan.json")
    diff = diff_node_lists(plan_defs, inspected_defs) if plan_defs is not None else None

    print(json.dumps({
        "mode": "graph-status",
        "ok": True,
        "graphId": args.graph_id,
        "name": args.name,
        "runId": args.run_id,
        "requestId": request,
        "readOnly": True,
        "inspect": {
            "status": backend.get("status"),
            "nodeCount": backend.get("nodeCount"),
            "nodes": nodes,
            "nodeDefinitionIds": inspected_defs,
            "boundEntityIds": bound,
        },
        "plan": plan_info,
        "diff": diff,
        "note": "read-only: one `graph inspect`; no create/add/wire/bind is ever dispatched",
    }, ensure_ascii=False, indent=2))
    return 0 if (diff is None or diff["clean"]) else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gameplan", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="plan", required=True)

    farm = sub.add_parser("farming", help="game B v0 — the farming loop graph")
    farm.add_argument("--name", default="MW_API_FARM_V0")
    farm.add_argument("--currency-id", type=int, required=True, help="货币配置ID (type 20)")
    farm.add_argument("--crop-id", type=int, required=True, help="作物道具配置ID")
    farm.add_argument("--food-id", type=int, required=True, help="加工食物道具配置ID")
    farm.add_argument("--item-slot", default="int", help="--slot used to write configIDs (default int)")
    farm.add_argument("--full", action="store_true",
                      help="use the consolidated demo graph (demo/farming_full.py) — adds the sell→pay leg "
                           "(701 sold → 688 credit) on top of the v0 graph")
    farm.add_argument("--currency-slot", default="int", help="--slot used to write a 货币配置ID (--full only)")
    farm.add_argument("--unit-price", type=int, default=10, help="coins per sold bag item (--full only)")
    farm.add_argument("--run-id", default=None, help="live bridge run id (32 hex); required for --execute")
    farm.add_argument("--entity-id", type=int, default=None, help="entity to bind the graph to")
    farm.add_argument("--queue-dir", default=None)
    farm.add_argument("--python", default="python")
    farm.add_argument("--out", default=None, help="write the evidence JSON here")
    farm.add_argument("--execute", action="store_true",
                      help="actually dispatch (default: dry run, nothing is sent)")
    farm.add_argument("--max-ops", type=int, default=None,
                      help="stop cleanly after this many EXECUTED ops (the bridge scope's lease is 5 min; "
                           "completed ops replay on the next run, so this makes a run resumable)")
    farm.add_argument("--batch", action="store_true",
                      help="build the whole graph in ONE dispatch (author.py graph build-plan); "
                           "requires the bridge revision that implements it")
    farm.set_defaults(func=cmd_farming)

    interactive = sub.add_parser("farming-interactive",
        help="compile the entity-state farming graph; --execute explicitly builds and binds it")
    interactive.add_argument("--name", default="MW_API_FARM_INTERACTIVE")
    for argument, label in (("seed", "种子道具"), ("crop", "作物道具"), ("currency", "货币")):
        interactive.add_argument(f"--{argument}-id", type=int, required=True,
            help=f"已存在并读回的{label}配置ID；没有默认或占位ID")
    interactive.add_argument("--item-slot", required=True, choices=("int", "uint", "enum"),
        help="从live slot读回选择道具配置ID写槽")
    interactive.add_argument("--currency-slot", required=True, choices=("int", "uint", "enum"),
        help="从live slot读回选择货币配置ID写槽")
    interactive.add_argument("--variable-flag-slot", required=True, choices=("bool", "enum"),
        help="从live slot读回选择22/50变量布尔写槽")
    interactive.add_argument("--growth-seconds", type=float, default=10.0)
    interactive.add_argument("--seed-cost", type=int, default=1)
    interactive.add_argument("--harvest-gain", type=int, default=1)
    interactive.add_argument("--starter-seeds", type=int, default=0,
        help="首次合法交互给角色的种子数量；默认0不启用种子领取")
    interactive.add_argument("--starter-currency", type=int, default=0,
        help="首次合法交互给角色的货币数量；默认0不启用货币领取")
    interactive.add_argument("--starter-guard", default="MW_FARM_STARTER_V1",
        help="所有地块共用的角色领取标记；勿按地块命名或在复苏时重置")
    interactive.add_argument("--sale-count", type=int, default=1, help="仅direct模式每批兑换的作物数量")
    interactive.add_argument("--sale-price", type=int, default=10,
        help="direct每批收益；native_shop每个作物的收购价")
    interactive.add_argument("--sale-mode", choices=("direct", "native_shop"), default="direct",
        help="direct直接兑换；native_shop由原生商店出售种子和收购作物，自动结算")
    interactive.add_argument("--seed-price", type=int, default=2,
        help="原生商店每份种子的货币价格")
    interactive.add_argument("--shop-index", type=int, default=1,
        help="商店组件实际读回的正整数编号，不是列表下标")
    interactive.add_argument("--shop-flag-slot", choices=("enum", "bool"), default=None,
        help="native_shop必填；708/710商品状态槽，执行前须读回核验")
    interactive.add_argument("--farm-trigger-index", type=int, default=1,
        help="种植区域实际读回的正整数编号")
    interactive.add_argument("--sell-trigger-index", type=int, default=2,
        help="卖货区域实际读回的正整数编号")
    interactive.add_argument("--interaction-mode", choices=("proximity", "skill", "distance"), default="proximity",
        help="proximity使用碰撞区域；skill使用技能通知；distance按角色位置轮询，无碰撞组件前置")
    interactive.add_argument("--skill-target", default=None,
        help="skill模式必填的唯一地块标识；技能通知参数1为plant/sell，参数2为此标识")
    interactive.add_argument("--farm-center", type=float, nargs=3, metavar=("X", "Y", "Z"),
        help="distance模式必填：种植区域世界坐标中心")
    interactive.add_argument("--sell-center", type=float, nargs=3, metavar=("X", "Y", "Z"),
        help="distance模式必填：商店区域世界坐标中心")
    interactive.add_argument("--interaction-radius", type=float,
        help="distance模式必填：进入半径，两区域共用")
    interactive.add_argument("--exit-radius", type=float,
        help="distance模式必填：离开半径，须大于进入半径；两个外圈须分离")
    interactive.add_argument("--poll-seconds", type=float, default=0.25)
    interactive.add_argument("--host-key", help="distance模式角色标记中的唯一宿主键；默认取显式entity-id")
    interactive.add_argument("--state-name", default="mw_farm_stage")
    interactive.add_argument("--timer-name", default="mw_farm_growth")
    interactive.add_argument("--inventory-holder", choices=("character_owner", "entrant"),
        default="entrant", help="默认使用进入触发器的角色背包；character_owner仅供已验证的特殊场景，不能与starter启用组合")
    interactive.add_argument("--run-id", help="当前有效bridge scope UUID；--execute必填")
    interactive.add_argument("--entity-id", type=int, help="当前已读回的绑定目标实体；--execute必填")
    interactive.add_argument("--queue-dir", default=None)
    interactive.add_argument("--python", default="python")
    interactive.add_argument("--out", help="可选输出JSON路径；必须位于工程.runtime内，相对路径从工程根解析")
    interactive.add_argument("--execute", action="store_true", help="显式构建并绑定；默认仅编译验证，零派发")
    interactive.add_argument("--batch", action="store_true", default=True,
        help="批量建图（本命令始终默认启用，避免逐节点耗尽scope）")
    interactive.set_defaults(func=cmd_farming_interactive)

    status = sub.add_parser(
        "graph-status",
        help="read-only: inspect one graph (nodes + boundEntityIds) and diff its nodes against "
             "<name>-plan.json in .runtime/scratch")
    status.add_argument("--graph-id", type=int, required=True, help="graph id (uint32) to inspect")
    status.add_argument("--run-id", required=True,
                        help="live bridge run id (a UUID). REQUIRED: the graph id is a function "
                             "of the save, so it is never inferred and never reused from a "
                             "previous run")
    status.add_argument("--name", default=None,
                        help="MW_API_… graph name. author.py graph inspect is keyed by name, so "
                             "this is needed to read the graph; it also selects <name>-plan.json")
    status.add_argument("--queue-dir", default=None)
    status.add_argument("--scratch-dir", default=str(_repo_default_scratch()),
                        help="directory searched for <name>-plan.json (default: .runtime/scratch)")
    status.add_argument("--python", default="python")
    status.set_defaults(func=cmd_graph_status)

    live = sub.add_parser("live", help="read the currently-open sandbox (native read-only)")
    live.add_argument("--queue-dir", default=str(_repo_default_queue()))
    live.set_defaults(func=cmd_live)
    return parser


def cmd_live(args) -> int:
    from .live import read_live

    state = read_live(args.queue_dir)
    print(json.dumps(state.summary(), ensure_ascii=False, indent=2))
    return 0 if state.ok else 1


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
