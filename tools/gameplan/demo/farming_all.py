"""Game B demo — the canonical **all-module** graph: one plan, every expressible half.

:mod:`tools.gameplan.demo.farming_full` is the 15-node 收/合成/卖/反馈 loop;
:mod:`tools.gameplan.demo.farming_loop` closes it with a terminal; and
:mod:`tools.gameplan.demo.farming_m4` proves the M4 bag primitives (``689`` /
``230`` / ``2`` / ``1`` / ``685``) in a graph of their own.  None of them is the
*whole* thing: ``farming_full`` never places a single M4 node, and ``farming_m4``
has no currency, item or shop leg.

This module is the *canonical* one.  It builds **one** graph (kind 20000) that
exercises a helper from **every** module we can express as nodes, and freezes its
shape as a committed snapshot a machine can diff:

* **M1 交互点** — two ``进入碰撞触发器时`` (``92``) event sources
  (:func:`interaction.proximity_enter`): the plot and the stall.
* **M2 货币** — the wallet reaction (:func:`currency.on_changed`, ``684``) and the
  engine transaction feedback; no second wallet payout.
* **M3 道具** — the harvest grant (:func:`item.grant`, ``686``), the crafting
  read/compare (:func:`item.read` ``690`` + ``233``), and the use event
  (:func:`item.on_used`, ``733``).
* **M4 背包** — the **capacity gate** (:func:`inventory.capacity_gate`, ``689`` →
  ``230`` → ``2`` → ``1``) and the grow primitive (:func:`inventory.grow_then`,
  ``685``).  ``689``/``685`` are the two M4 nodes that can actually enter a graph.
* **M5 商店** — the store open (:func:`shop.open_`, ``702``), the **sale notification**
  (:func:`shop.on_bag_item_sold`, ``701`` → ``1``), and the product writer
  (:func:`shop.list_item_for_sale`, ``709`` — the bag-store shape).

Six-module honesty
------------------

The repository counts **six** modules (``docs/gameplan/README.md`` §五): M1–M5
plus **M6** (地块 / terrain + placement).  M6 has **no node half at all** —
``nodes.py`` declares no terrain role (``README.md`` §五 M6a row: "无地形类节点").
So "every module half we can express" is exactly the node halves of M1–M5, and
this graph carries all five.  M6 is placement, not a node graph
(:mod:`tools.gameplan.placement`), and is deliberately absent here.

The two limits that are *not* ours to fix (unchanged from every sibling demo):

* **The templates must already exist.**  ``货币`` / ``道具`` / ``商店`` / ``背包``
  templates are editor assets this project cannot create (no template writer in
  the bridge/CLI/MCP); their ids are parameters — ``config`` — not constants we
  mint.
* **The interaction scene-half is manual.**  The ``碰撞触发器`` component that
  makes a plot or a stall fire must be configured in the editor — see
  :mod:`tools.gameplan.modules.interaction`.  This graph is the *logic* half.

Naming note (why not ``build_plan``)
------------------------------------

The public validator here is :func:`plan_of`, **not** ``build_plan``, for the same
reason as :mod:`tools.gameplan.demo.farming_minimal`: the demo-golden guard
(``tests/test_demo_golden.py``) discovers *every* module under ``demo/`` that
exposes ``build_plan`` and demands an aggregate shape for it, and that registry
(``tools/gameplan/golden.py``) is outside this task's file ownership.  This
module's own shape guard is the asserted node list in
``tests/test_farming_all.py`` plus the committed snapshot
``tools/gameplan/golden/farming_all.json``.

Everything here uses ONLY the current public API of ``tools/gameplan/modules/*``
and the named role tables in :mod:`tools.gameplan.nodes`; no new helpers are
assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import (
    ADD_BAG_CAPACITY,
    ADD_BAG_CURRENCY,
    ADD_BAG_ITEM,
    BAG_CURRENCY_CHANGED,
    BAG_ITEM_ADDED,
    BAG_ITEM_CHANGED,
    BAG_ITEM_LOST,
    BAG_ITEM_USED,
    BRANCH,
    CLOSE_SHOP,
    FLOATING_PAGE_TRIGGERED,
    GET_ALL_BAG_CURRENCIES,
    GET_ALL_BAG_ITEMS,
    GET_BAG_CAPACITY,
    GET_BAG_CURRENCY,
    GET_BAG_ITEM,
    Graph,
    OPEN_SHOP,
    PRINT,
    PROXIMITY_ENTER,
    PROXIMITY_LEAVE,
    SHOP_BOUGHT_ITEM,
    SHOP_SOLD_BAG_ITEM,
    UI_CONTROL_TRIGGERED,
)
from ..plan import GraphPlan
from ..modules import currency as m2
from ..modules import interaction as m1
from ..modules import inventory as m4
from ..modules import item as m3
from ..modules import shop as m5
from . import farming_full

DEFAULT_NAME = "MW_API_FARM_ALL"

#: The line printed when the bag is nearly full (capacity below the threshold).
BAG_FULL_TEXT = "背包快满了"

#: ``compare`` selector used by the M4 capacity gate — ``lt`` ⇒ ``容量 < 阈值`` is
#: the "背包将满" predicate (``modules/inventory.py:65-95``).
CAPACITY_COMPARE = "lt"


@dataclass(frozen=True)
class FarmAllConfig(farming_full.FarmFullConfig):
    """``FarmFullConfig`` plus the two M4 knobs and the shop-sale tab index.

    Every inherited field keeps ``FarmFullConfig``'s meaning and default; the new
    fields are the M4 capacity gate's threshold, the grow amount, and the sale
    tab the product is listed under.
    """

    capacity_threshold: int = 20  # 容量 < 此值 ⇒ 打印 BAG_FULL_TEXT
    grow_amount: int = 10         # 每次进入给背包加的最大容量 (685 delta)
    sale_tab: int = 3             # 出售页签序号 (m5.TAB_INDEX_ENUM[3] = 材料)


# ---------------------------------------------------------------------------
# Module coverage — which definitionIds belong to which module.
#
# Derived from the module-owned role tables (``nodes.py`` and the two ``shop``
# NodeType tables), never hand-typed, so a drifted id cannot make this lie.  A
# caller (and the test) can read exactly which of a module's nodes the graph
# places.
# ---------------------------------------------------------------------------

MODULE_NODE_IDS: dict[str, frozenset[int]] = {
    "M1-interaction": frozenset(
        t.definition_id
        for t in (
            PROXIMITY_ENTER,
            PROXIMITY_LEAVE,
            UI_CONTROL_TRIGGERED,
            FLOATING_PAGE_TRIGGERED,
        )
    ),
    "M2-currency": frozenset(
        t.definition_id for t in (ADD_BAG_CURRENCY, GET_BAG_CURRENCY, BAG_CURRENCY_CHANGED)
    ),
    "M3-item": frozenset(
        t.definition_id
        for t in (
            ADD_BAG_ITEM,
            GET_BAG_ITEM,
            BAG_ITEM_ADDED,
            BAG_ITEM_LOST,
            BAG_ITEM_CHANGED,
            BAG_ITEM_USED,
        )
    ),
    "M4-inventory": frozenset(
        t.definition_id
        for t in (GET_BAG_CAPACITY, ADD_BAG_CAPACITY, GET_ALL_BAG_ITEMS, GET_ALL_BAG_CURRENCIES)
    ),
    "M5-shop": frozenset(
        t.definition_id
        for t in (
            OPEN_SHOP,
            CLOSE_SHOP,
            SHOP_SOLD_BAG_ITEM,
            SHOP_BOUGHT_ITEM,
            *m5.SHOP_TABLE_NODE_TYPES,
            *m5.SHOP_QUERY_NODE_TYPES,
        )
    ),
}

#: Node definitionIds that are *event* entry points (no execution input).  An
#: event can never be a flow target — ``Handle.flow_to`` refuses it at build
#: time — and this set makes the property checkable on a finished plan.
EVENT_NODE_IDS: frozenset[int] = frozenset(
    t.definition_id
    for t in (
        PROXIMITY_ENTER,
        PROXIMITY_LEAVE,
        UI_CONTROL_TRIGGERED,
        FLOATING_PAGE_TRIGGERED,
        BAG_CURRENCY_CHANGED,
        BAG_ITEM_ADDED,
        BAG_ITEM_LOST,
        BAG_ITEM_CHANGED,
        BAG_ITEM_USED,
        SHOP_SOLD_BAG_ITEM,
        SHOP_BOUGHT_ITEM,
    )
)


def definition_ids(plan: GraphPlan) -> frozenset[int]:
    """Every ``definitionId`` the plan places."""
    return frozenset(n.definition_id for n in plan.nodes)


def module_coverage(plan: GraphPlan) -> dict[str, frozenset[int]]:
    """For each module, the definitionIds of *that module* the plan places.

    A module is *represented* exactly when its entry here is non-empty.
    """
    present = definition_ids(plan)
    return {
        module: frozenset(present & ids) for module, ids in MODULE_NODE_IDS.items()
    }


def covered_modules(plan: GraphPlan) -> tuple[str, ...]:
    """The modules with at least one placed node, in :data:`MODULE_NODE_IDS` order."""
    coverage = module_coverage(plan)
    return tuple(module for module in MODULE_NODE_IDS if coverage[module])


def build(config: FarmAllConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the all-module graph.  Returns an *unvalidated* :class:`Graph`."""
    # --- 收 → 合成 → 卖 → 反馈 : the frozen 15-node body, reused verbatim -----
    # Delegated to farming_full.build so the two graphs cannot drift; that body
    # already carries M1 (two 92 events), M2 (684 transaction feedback), M3 (686/690/
    # 233/733) and M5 (702/701).
    g = farming_full.build(config, name=name)

    # --- M4 腿：容量门 (689 -> 230 -> 2 -> 1) + 扩容 (685) --------------------
    # Hung off the *same* plot-enter execution output the harvest grant uses —
    # the same fan-out technique `plot_enter` already uses to drive two sinks.
    plot = g.handle("plot_enter")

    bag_cmp = m4.capacity_gate(
        g,
        holder=(plot, "entrant"),          # holder 来自事件实体，绝不是常量
        threshold=config.capacity_threshold,
        alias="bag",
        compare=CAPACITY_COMPARE,
    )                                       # -> 230；689 是它的 bag_cap 兄弟

    bag_branch = g.place(BRANCH, "bag_gate")            # 2 双分支
    plot.flow_to(bag_branch)                            # 执行：92.then -> 2
    bag_branch.data_from(bag_cmp, "result", "condition")  # 数据：230.结果 -> 2.条件

    bag_full = g.place(PRINT, "bag_full")               # 1 打印字符串
    bag_branch.flow_to(bag_full, "true")                # 2.是(0) -> 1
    bag_full.const("text", BAG_FULL_TEXT, "string")
    # 2.否(1) 故意不接线：容量够大时不做事。

    m4.grow_then(                                       # 685 增加背包最大容量
        g,
        plot,
        holder=(plot, "entrant"),
        amount=config.grow_amount,
        alias="grow",
    )

    # --- M5 创建商品腿：把作物挂到摊位的背包商店出售表 ------------------------
    # The stall's trigger entity is the shop owner; the product is the crop the
    # harvest leg grants.  The 出售货币字典 (type 27) pin stays unwired by design
    # (bag-store price is anchored to the item template's 货币价值 — shop.py
    # docstring), so this leg adds no dict constant.
    stall = g.handle("stall_enter")
    m5.list_item_for_sale(
        g,
        stall,
        shop_owner=(stall, "trigger"),
        shop_index=0,
        item_id=config.crop_id,
        item_slot=config.item_slot,
        store=m5.STORE_BAG_ADD,
        tab_index=config.sale_tab,
        alias="list_crop",
    )

    return g


def plan_of(config: FarmAllConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the all-module graph, returning the :class:`GraphPlan`.

    Raises :class:`tools.gameplan.plan.PlanError` if any node, edge or constant is
    inconsistent with ``data/node-contracts`` — before any native call.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


def golden_plans() -> dict[str, GraphPlan]:
    """The canonical ``name -> plan`` this module pins (mirrors the siblings).

    Frozen at the ids :data:`tools.gameplan.golden._DEMO_IDS` carries, so the
    committed ``farming_all.json`` is generated from exactly the config the test
    reads.
    """
    return {
        "farming_all": plan_of(
            FarmAllConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)
        )
    }


__all__ = [
    "CAPACITY_COMPARE",
    "BAG_FULL_TEXT",
    "DEFAULT_NAME",
    "EVENT_NODE_IDS",
    "FarmAllConfig",
    "MODULE_NODE_IDS",
    "build",
    "covered_modules",
    "definition_ids",
    "golden_plans",
    "module_coverage",
    "plan_of",
]
