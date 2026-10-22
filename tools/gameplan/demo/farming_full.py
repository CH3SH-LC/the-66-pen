"""Game B demo — the *whole* farming loop as ONE server node graph.

This is the consolidated six-direction demo: every module fragment M1–M5 is
wired into a single graph (kind 20000) instead of the v0 build in
:mod:`tools.gameplan.demo.farming`.

Flow (docs/NEW-FEATURE-PLAN.md §六: 收 → 合成 → 卖 + 反馈):

1. **收** (M1+M3) — the player walks into a plot (``进入碰撞触发器时`` 92) →
   ``增加背包道具数量`` (686) ``+harvest_gain`` crop.
1b. **收菜直接给钱** (M1+M2, #13) — the *same* plot-enter event also fans out to
   ``增加背包货币数量`` (688) ``+harvest_bonus``.  Only built when
   ``harvest_bonus > 0``; the default 0 places no extra node (byte-identical).
2. **合成** (M3+F2) — the crop is *used* (``背包内道具被使用时`` 733) →
   ``获取背包道具数量`` (690) → ``数值大于等于`` (233) → ``双分支`` (2):
   * **真**: consume ``recipe_cost`` crops (686, ``-recipe_cost``) *then*
     bake ``cook_gain`` food (686, ``+cook_gain``);
   * **假**: ``打印字符串`` (1) ``"材料不足"``.
3. **卖** (M1+M5+M2) — the player walks into the stall (``进入碰撞触发器时`` 92)
   → ``打开商店`` (702).  Trading is automatic once the official store is open.
4. **反馈** (M2) — ``背包货币数量变化时`` (684) → ``打印字符串`` (1).

Two honest limits, unchanged from v0 and stated here so nobody mistakes the
graph for a working scene:

* **The templates must already exist.**  ``货币``/``道具``/``商店`` templates are
  editor assets this project's tools cannot create (no template writer in the
  bridge/CLI/MCP).  Their ids are parameters — ``config`` — not constants we mint.
  ``currency_id`` is carried for parity with v0 and for a future wallet read; the
  feedback leg only *reacts* to the change event (684), it does not name the
  currency.
* **The interaction scene-half is manual.**  The ``碰撞触发器`` component that
  makes a plot or a stall fire must be configured in the editor — see
  :mod:`tools.gameplan.modules.interaction`.  This graph is the *logic* half.

Everything here uses ONLY the current public API of ``tools/gameplan/modules/*``
and the named role tables in :mod:`tools.gameplan.nodes`; no new helpers are
assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import BRANCH, GE, PRINT, Graph
from ..plan import GraphPlan
from ..modules import currency as m2
from ..modules import interaction as m1
from ..modules import item as m3
from ..modules import shop as m5

DEFAULT_NAME = "MW_API_FARM_FULL"


@dataclass(frozen=True)
class FarmFullConfig:
    """Everything the graph needs that lives in the editor, not in our tools."""

    currency_id: int          # 货币配置ID (type 20) — carried from v0
    crop_id: int              # 作物道具配置ID (type 20)
    food_id: int              # 加工食物道具配置ID (type 20)
    item_slot: str = "int"    # the `--slot` used to write a configID (see paramtypes)
    currency_slot: str = "int"  # the `--slot` used to write a 货币配置ID (type 20)
    unit_price: int = 10      # legacy config field; native shop tables own pricing
    recipe_cost: int = 2      # crops consumed per cook
    harvest_gain: int = 1     # crops gained per harvest
    harvest_bonus: int = 0    # coins gained per harvest (0 = no bonus branch; see build)
    cook_gain: int = 1        # food produced per cook


@dataclass(frozen=True)
class PlanShape:
    """A structural summary of a plan, so a caller need not read NodeSpecs."""

    node_count: int
    edge_count: int
    const_count: int
    ordered_nodes: tuple[tuple[str, int], ...]  # (alias, definitionId), in build order


def plan_shape(plan: GraphPlan) -> PlanShape:
    """Return the node/edge/value counts and the ordered alias->definitionId list."""
    return PlanShape(
        node_count=len(plan.nodes),
        edge_count=len(plan.edges),
        const_count=len(plan.consts),
        ordered_nodes=tuple((n.alias, n.definition_id) for n in plan.nodes),
    )


def build(config: FarmFullConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the full farming graph.  Returns an *unvalidated* :class:`Graph`."""
    g = Graph(name)

    # --- 1. 收：走进地块 → 收 harvest_gain 份作物 --------------------------
    plot = m1.proximity_enter(g, "plot_enter")
    m3.grant(
        g, plot, holder=(plot, "entrant"), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias="harvest",
    )

    # --- 1b. 收菜直接给钱支线：同一次进入，额外的币奖励 --------------------
    # Only when harvest_bonus > 0 — at the default 0 no node is placed, so the
    # zero-bonus graph stays byte-identical to the pre-bonus build.  Both sinks
    # hang off the *same* 92 execution output (进入碰撞触发器时.then): the event
    # fans out to `harvest` (crops) and `harvest_bonus` (coins) in parallel.
    if config.harvest_bonus > 0:
        m2.grant(
            g, plot, holder=(plot, "entrant"), currency_id=config.currency_id,
            amount=config.harvest_bonus, currency_slot=config.currency_slot,
            alias="harvest_bonus",
        )

    # --- 2. 合成：使用作物 → 够了就 recipe_cost 换 cook_gain，不够就提示 ----
    used = m3.on_used(g, "crop_used")                       # 背包内道具被使用时
    have = m3.read(g, holder=(used, "holder"), item_id=config.crop_id,
                   item_slot=config.item_slot, alias="crop_count")

    enough = g.place(GE, "enough")                          # 数值大于等于
    enough.data_from(have, "amount", "left")
    enough.const("right", config.recipe_cost, "int")

    gate = g.place(BRANCH, "gate")                          # 双分支
    used.flow_to(gate)
    gate.data_from(enough, "result", "condition")

    consume = m3.grant(g, gate, holder=(used, "holder"), item_id=config.crop_id,
                       count=-config.recipe_cost, item_slot=config.item_slot,
                       alias="consume", from_role="true")
    m3.grant(g, consume, holder=(used, "holder"), item_id=config.food_id,
             count=config.cook_gain, item_slot=config.item_slot, alias="bake")

    short = g.place(PRINT, "short")
    gate.flow_to(short, "false")
    short.const("text", "材料不足", "string")

    # --- 3. 卖：走进摊位 → 打开官方商店（之后交易由官方自动处理） ----------
    stall = m1.proximity_enter(g, "stall_enter")
    m5.open_(g, stall, player=(stall, "entrant"), shop_owner=(stall, "trigger"),
             shop_index=0, alias="open_shop")

    # The native shop already exchanged items and currency before this event.
    sold = m5.on_bag_item_sold(g, alias="sold")
    sold_note = g.place(PRINT, "sold_note")
    sold.flow_to(sold_note)
    sold_note.const("text", "商店交易完成", "string")

    # --- 4. 反馈：货币一变就打印一行 ---------------------------------------
    money = m2.on_changed(g, "money_changed")
    note = g.place(PRINT, "money_note")
    money.flow_to(note)
    note.const("text", "货币发生变化", "string")

    return g


def build_plan(config: FarmFullConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the full farming graph, returning the :class:`GraphPlan`.

    Raises :class:`tools.gameplan.plan.PlanError` if any node, edge or constant is
    inconsistent with ``data/node-contracts``.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan
