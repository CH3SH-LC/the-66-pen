"""Game B v0 — the farming loop, as one server node graph.

Flow (docs/NEW-FEATURE-PLAN.md §六: 种 → 收 → 合成 → 卖):

1. **收** — the player walks into a plot (碰撞触发器) → ``+1`` crop in the bag.
2. **合成** — the crop is *used* → if the bag holds ≥ 2, consume 2 and bake 1
   cooked item; otherwise print 材料不足.
3. **卖** — the player walks into the stall (碰撞触发器) → the official store
   opens; selling is automatic from there.
4. **反馈** — every currency change prints a line (the log is the only
   *player-visible* channel this project has today; a board/HUD would need UI
   writers that do not exist).

Two honest limits, stated once here rather than hidden:

* **The templates must already exist.** ``货币``/``道具``/``商店`` templates are
  editor assets this project's tools cannot create (research: bridge/CLI/MCP have
  no template writer). The ids are therefore parameters, not constants we mint.
* **The interaction scene-half is manual.** The ``碰撞触发器`` component that makes
  a plot or a stall fire must be configured in the editor — see
  ``modules/interaction.py``. This graph is the *logic* half.

Everything else — the node graph, the wires, the constants, the recipe condition
— is generated for real and validated against ``data/node-contracts``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import BRANCH, GE, PRINT, Graph, Handle
from ..modules import currency as m2
from ..modules import interaction as m1
from ..modules import item as m3
from ..modules import shop as m5


@dataclass(frozen=True)
class FarmConfig:
    """Everything the graph needs that lives in the editor, not in our tools."""

    currency_id: int          # 货币配置ID (type 20)
    crop_id: int              # 作物道具配置ID (type 20)
    food_id: int              # 加工食物道具配置ID (type 20)
    item_slot: str = "int"    # the `--slot` used to write a configID (see paramtypes)
    recipe_cost: int = 2      # crops consumed per cook
    harvest_gain: int = 1     # crops gained per harvest
    cook_gain: int = 1        # food produced per cook


def build(config: FarmConfig, name: str = "MW_API_FARM_V0") -> Graph:
    """Build the farming graph.  Returns an unvalidated :class:`Graph`."""
    g = Graph(name)

    # --- 收：走进地块 → 收 1 份作物 ----------------------------------------
    plot = m1.proximity_enter(g, "plot_enter")
    m3.grant(
        g, plot, holder=(plot, "entrant"), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias="harvest",
    )

    # --- 合成：使用作物 → 够了就 2 换 1，不够就提示 -------------------------
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
    short.const("text", "材料不足，无法加工", "string")

    # --- 卖：走进摊位 → 打开官方商店（之后交易由官方自动处理） --------------
    stall = m1.proximity_enter(g, "stall_enter")
    m5.open_(g, stall, player=(stall, "entrant"), shop_owner=(stall, "trigger"),
             shop_index=0, alias="open_shop")

    # --- 反馈：货币一变就打印一行 ------------------------------------------
    money = m2.on_changed(g, "money_changed")
    note = g.place(PRINT, "money_note")
    money.flow_to(note)
    note.const("text", "货币发生变化", "string")

    return g


def build_plan(config: FarmConfig, name: str = "MW_API_FARM_V0"):
    """Build and validate the farming graph, returning the :class:`GraphPlan`.

    Raises :class:`graphplan.plan.PlanError` if any node, edge or constant is
    inconsistent with the contracts.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan
