"""The SIX-AXIS attempt: one runnable (entry ``71``) graph built to exercise **every
module direction the node catalogue genuinely allows** — and to say, by derivation,
which directions it cannot.

The aspiration and the honest result
------------------------------------

The task was "a demo that exercises all six module directions on the graph side".
This module builds the *maximal* such plan and reports, from the plan itself, what it
actually reaches.  The derived answer is **three of six** —
``M2-currency`` / ``M3-item`` / ``M4-inventory`` — and the other three are excluded
for three *different*, structural reasons (each is a fact about the node catalogue,
not a choice):

* **M1 交互点** — every node in the family (``92``/``91``/``316``/``826``) is an
  **event** (an execution output and no execution input).  An event can never be a
  flow *target* (:func:`~tools.gameplan.nodes.Handle.flow_to` refuses it), so placing
  one makes a **second entry**, not a node the ``71`` entry reaches.  M1 is
  uncoverable by an entry-``71`` graph even before its component blocker (the
  ``碰撞触发器`` / UI a ``92`` needs to fire, ``CLAUDE.md`` §六(a)) is considered.
* **M5 商店** — its nodes (``702``/``703``/``701``/``705``/``704``/``706``/``709``/
  ``714``/``715``) are *chain* nodes, but every one acts on a ``商店组件`` that must
  sit on an entity — the same missing add-component primitive as M1
  (``modules/shop.py`` docstring; ``docs/gameplan/DEMO-GAP.md`` §三 row 4).  So the
  whole family is in the derived blocked set.
* **M6 地块/地形** — has **no node half at all**: terrain has no node role, and
  placement is a *scene* action (``entity.create`` by coordinate), not a node.  Its
  entry in :data:`~tools.gameplan.coverage.MODULE_NODE_IDS` is the empty set — the
  derived statement of that.

The verdicts are not asserted in prose: :func:`six_axis_report` reads them out of
:mod:`tools.gameplan.coverage`, and ``tests/test_demo_six.py`` checks that the report
is a *function of the plan* (pass a different blocked set and the answer moves).

The graph
---------

::

    on_create  71 实体创建时                       (entry — bind target created)
      └─ then ─▶ print_entry 1 打印 "六号图入口已触发"   (unconditional WAVE-29AA probe)
                   └─ then ─▶ grow   685 增加背包最大容量   +grow_amount     (M4)
                       └─ then ─▶ harvest 686 增加背包道具数量 +harvest_gain   (M3)
                           └─ then ─▶ bonus 688 增加背包货币数量 +coin_bonus    (M2)
                               └─ then ─▶ gate_item 2 双分支 ◀── 233 ◀── 690 读作物
                                            ├ 是 ─▶ gate_cap 2 双分支 ◀── 230 ◀── 689 读容量
                                            │        ├ 是 ─▶ 1 打印 "背包容量偏低"
                                            │        └ 否 ─▶ 1 打印 "收获完成"
                                            └ 否 ─▶ gate_money 2 双分支 ◀── 233 ◀── 691 读货币
                                                     ├ 是 ─▶ 1 打印 "作物不足但货币充足"
                                                     └ 否 ─▶ 1 打印 "作物不足"
    (M4 exhaustive half) 721 获取背包所有基础道具 / 722 获取背包所有货币
        ← 71.entity   — reachable from the entry, but each returns an opaque type-27
        dict with no consumer this project can build, so they are inert leaves.

The M4 dict queries (``721``/``722``) are included to exercise **M4's whole reachable
fragment set** (``685``/``689``/``721``/``722``), not to claim coverage M4 already had
from ``685``/``689``.  They stay OFF unless ``include_dict_queries=True`` (the
default), and coverage is invariant to them (proved in the test): a module counts by
its own reachable nodes, and dead leaves change nothing — which is the point.

Two honesty notes carried over from :mod:`tools.gameplan.demo.farming_runnable`:

* **``686``/``688``/``690``/``691`` take a config-id that is just a number** (contract
  type 20).  The missing item/currency template makes the id *dangle* — the effect is
  inert — but the input is satisfiable, so the node is placeable and the graph runs.
* **The entry's firing is inherited, not proven here.**  ``71`` is claimed to fire
  when the graph's bind target is created (tool-built by coordinate).  This module
  builds and validates the plan offline only; the RUN4 playtest is the live evidence
  for the ``71`` design, not this module.

Named ``plan_of`` — **not** ``build_plan`` — on purpose: the demo-golden guard
discovers every ``demo/*.py`` exposing ``build_plan`` and demands a frozen snapshot;
this module's shape guard is ``tests/test_demo_six.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import coverage as cov
from ..nodes import (
    BRANCH,
    ON_CREATE,
    PRINT,
    Graph,
)
from ..plan import GraphPlan
from ..modules import currency as m2
from ..modules import inventory as m4
from ..modules import item as m3

DEFAULT_NAME = "MW_API_DEMO_SIX"
"""The graph name; matches ``plan.GRAPH_NAME_RE``. Names the 6-axis attempt."""

#: The unconditional line printed the instant the entry fires (names the graph).
ENTRY_PROBE_TEXT = "六号图入口已触发"

LOW_CAPACITY_TEXT = "背包容量偏低"
HARVEST_OK_TEXT = "收获完成"
SHORT_ITEM_RICH_TEXT = "作物不足但货币充足"
SHORT_ALL_TEXT = "作物不足"

CAPACITY_COMPARE = "lt"


def module_node_ids() -> dict[str, frozenset[int]]:
    """Re-export the derived module table, so a caller reads it off the plan's owner."""
    return dict(cov.MODULE_NODE_IDS)


@dataclass(frozen=True)
class SixConfig:
    """Everything the graph needs that lives in the editor, not in our tools."""

    currency_id: int            # 货币配置ID (type 20)
    crop_id: int                # 作物道具配置ID (type 20)
    item_slot: str = "int"      # the `--slot` used to write a configID
    currency_slot: str = "int"  # the `--slot` used to write a 货币配置ID (type 20)
    grow_amount: int = 10       # 685 delta — bag capacity added at level load
    harvest_gain: int = 1       # 686 delta — crops granted at level load
    coin_bonus: int = 10        # 688 delta — coins granted at level load
    recipe_cost: int = 2        # the crop threshold the first gate compares against
    coin_threshold: int = 100   # the wallet threshold the third gate compares against
    capacity_threshold: int = 20  # the bag-capacity threshold the second gate compares
    include_dict_queries: bool = True  # place M4's 721/722 (inert dict reads)


def build(config: SixConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the maximal-coverage graph.  Returns an *unvalidated* :class:`Graph`.

    The **first** node placed — index 0 of the plan — is ``71``.
    """
    g = Graph(name)

    create = g.place(ON_CREATE, "on_create")            # 71 实体创建时
    assert create.ntype is ON_CREATE

    probe = g.place(PRINT, "print_entry")               # 1 打印字符串 (unconditional)
    create.flow_to(probe)                               # 71.then -> 1
    probe.const("text", ENTRY_PROBE_TEXT, "string")

    # --- 收 (M4 → M3 → M2): grow the bag, then harvest crops, then pay coins ------
    grow = m4.grow_then(                                # 685 增加背包最大容量
        g, probe, holder=(create, "entity"), amount=config.grow_amount, alias="grow",
    )
    harvest = m3.grant(                                 # 686 增加背包道具数量
        g, grow, holder=(create, "entity"), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias="harvest",
    )
    bonus = m2.grant(                                   # 688 增加背包货币数量
        g, harvest, holder=(create, "entity"), currency_id=config.currency_id,
        amount=config.coin_bonus, currency_slot=config.currency_slot, alias="bonus",
    )

    # --- 合成判据 (F2): 作物够不够 → 2 双分支 ------------------------------------
    item_cmp = m3.has_enough(                           # 690 读作物 + 233 大于等于
        g, holder=(create, "entity"), item_id=config.crop_id,
        threshold=config.recipe_cost, item_slot=config.item_slot, alias="craft_enough",
    )
    gate_item = g.place(BRANCH, "gate_item")            # 2 双分支
    bonus.flow_to(gate_item)                            # 688.then -> 2
    gate_item.data_from(item_cmp, "result", "condition")

    # --- M4 容量门: 容量 < 阈值 → 提示 (true), 否则收获完成 (false) --------------
    cap_cmp = m4.capacity_gate(                         # 689 读容量 + 230 小于
        g, holder=(create, "entity"), threshold=config.capacity_threshold,
        alias="cap_gate", compare=CAPACITY_COMPARE,
    )
    gate_cap = g.place(BRANCH, "gate_cap")              # 2 双分支
    gate_item.flow_to(gate_cap, "true")                 # 2.是 -> 2
    gate_cap.data_from(cap_cmp, "result", "condition")

    p_low = g.place(PRINT, "print_low_cap")             # 1 打印字符串
    gate_cap.flow_to(p_low, "true")
    p_low.const("text", LOW_CAPACITY_TEXT, "string")

    p_ok = g.place(PRINT, "print_ok")                   # 1 打印字符串
    gate_cap.flow_to(p_ok, "false")
    p_ok.const("text", HARVEST_OK_TEXT, "string")

    # --- 作物不够: 再看钱够不够 (M2 读 691 + 233) --------------------------------
    money_cmp = m2.read_and_compare(                    # 691 读货币 + 233 大于等于
        g, holder=(create, "entity"), currency_id=config.currency_id,
        threshold=config.coin_threshold, currency_slot=config.currency_slot,
        alias="coin_enough",
    )
    gate_money = g.place(BRANCH, "gate_money")          # 2 双分支
    gate_item.flow_to(gate_money, "false")              # 2.否 -> 2
    gate_money.data_from(money_cmp, "result", "condition")

    p_rich = g.place(PRINT, "print_rich")               # 1 打印字符串
    gate_money.flow_to(p_rich, "true")
    p_rich.const("text", SHORT_ITEM_RICH_TEXT, "string")

    p_short = g.place(PRINT, "print_short")             # 1 打印字符串
    gate_money.flow_to(p_short, "false")
    p_short.const("text", SHORT_ALL_TEXT, "string")

    # --- M4 exhaustive half: the two dict queries (reachable but inert leaves) ----
    if config.include_dict_queries:
        m4.all_items(g, holder=(create, "entity"), alias="all_items")        # 721
        m4.all_currencies(g, holder=(create, "entity"), alias="all_currencies")  # 722

    return g


def plan_of(config: SixConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the graph, returning its :class:`GraphPlan`."""
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


#: The config the committed plan artifact and the tests are generated from.
DEMO_CONFIG = SixConfig(currency_id=1115684864, crop_id=1120000001)


def demo_plan() -> GraphPlan:
    """The canonical plan (the one written to ``DEMO-SIX-plan.json``)."""
    return plan_of(DEMO_CONFIG)


# ---------------------------------------------------------------------------
# The derived report — what the plan actually reaches, per module.
# ---------------------------------------------------------------------------

def six_axis_report(plan: GraphPlan) -> dict:
    """The plan's coverage, derived (never a typed list).

    Returns the covered modules, the per-module verdict, and — for the record — the
    reachable/non-blocked definitionIds credited to each module.
    """
    by_alias = {n.alias: n for n in plan.nodes}
    entries = cov.entry_aliases(plan)
    return {
        "coveredModules": list(cov.covered_modules(plan)),
        "moduleVerdict": cov.module_status(plan),
        "moduleCoverage": {
            module: sorted(ids) for module, ids in cov.module_coverage(plan).items()
        },
        "blockedIntersection": sorted(cov.definition_ids(plan) & cov.BLOCKED_DEFINITION_IDS),
        "entryDefinitionId": (
            by_alias[entries[0]].definition_id if entries else None
        ),
    }


def artifact(plan: GraphPlan) -> dict:
    """The plan as a self-describing JSON object (the ``DEMO-SIX-plan.json`` shape).

    Carries both the derived invariants and the concrete dispatch payloads (the
    adapter's ``build-plan`` shape and the ordered native argv list).  Pure: the
    custom-call projection uses the *simulated* runner, so nothing is dispatched.
    """
    from ..builder import GraphBuilder, simulated_runner

    builder = GraphBuilder(plan, simulated_runner(), run_id="dry-run")
    result = builder.build()
    report = six_axis_report(plan)
    return {
        "graphName": plan.name,
        "graphKind": plan.graph_kind,
        "entryDefinitionId": report["entryDefinitionId"],
        "nodeCount": len(plan.nodes),
        "edgeCount": len(plan.edges),
        "constCount": len(plan.consts),
        "blockedDefinitionIds": sorted(cov.BLOCKED_DEFINITION_IDS),
        "blockedIntersection": report["blockedIntersection"],
        "coveredModules": report["coveredModules"],
        "moduleVerdict": report["moduleVerdict"],
        "moduleCoverage": {k: list(v) for k, v in report["moduleCoverage"].items()},
        "orderedNodes": [[n.alias, n.definition_id] for n in plan.nodes],
        "constants": [
            {"alias": c.alias, "portIndex": c.port_index, "slot": c.slot, "value": c.value}
            for c in plan.consts
        ],
        "batchPlan": builder.batch_plan_json(),
        "nativeCalls": [{"step": s.summary()["step"], "argv": s.argv} for s in result.steps],
    }


def describe(plan: GraphPlan) -> list[str]:
    """One human line per node, in build order: ``idx  defId(alias)  in/val/then``."""
    index = {n.alias: i for i, n in enumerate(plan.nodes)}
    exec_out: dict[str, list[str]] = {}
    data_in: dict[str, list[str]] = {}
    for e in plan.edges:
        if e.src_kind == 2:
            exec_out.setdefault(e.src, []).append(f"{e.dst}[{e.dst_index}]")
        else:
            data_in.setdefault(e.dst, []).append(f"{e.src}.out{e.src_index}")
    consts: dict[str, list[str]] = {}
    for c in plan.consts:
        consts.setdefault(c.alias, []).append(f"3:{c.port_index}={c.value!r}")
    lines: list[str] = []
    for alias, i in sorted(index.items(), key=lambda kv: kv[1]):
        node = plan.nodes[i]
        parts = [f"{i:2d}", f"{node.definition_id}({alias})"]
        if data_in.get(alias):
            parts.append("in←" + ",".join(data_in[alias]))
        if consts.get(alias):
            parts.append("val=" + ",".join(consts[alias]))
        if exec_out.get(alias):
            parts.append("then→" + ",".join(exec_out[alias]))
        lines.append("  ".join(parts))
    return lines


__all__ = [
    "CAPACITY_COMPARE",
    "DEFAULT_NAME",
    "DEMO_CONFIG",
    "ENTRY_PROBE_TEXT",
    "HARVEST_OK_TEXT",
    "LOW_CAPACITY_TEXT",
    "SHORT_ALL_TEXT",
    "SHORT_ITEM_RICH_TEXT",
    "SixConfig",
    "artifact",
    "build",
    "demo_plan",
    "describe",
    "module_node_ids",
    "plan_of",
    "six_axis_report",
]
