"""Game B — the *whole* farming loop, closed, with a terminal win condition.

:mod:`tools.gameplan.demo.farming_full` builds the 15-node demo (收 → 合成 → 卖 →
反馈) and :mod:`tools.gameplan.golden` freezes its *shape*.  This module does the
one thing that demo does not: it **closes the loop** — it adds an *observable end
state* the player can reach and the graph can announce — and it pins the closed
shape in its own golden snapshot (``tools/gameplan/golden/farming_loop.json``).

The loop, read as one cycle
---------------------------

::

    收   entering a plot  (进入碰撞触发器时 92)
           -> 增加背包道具数量 686  +harvest_gain  crops

    合成 using a crop  (背包内道具被使用时 733)
           -> 获取背包道具数量 690 -> 数值大于等于 233 -> 双分支 2
                ├ 是 -> 增加背包道具数量 686  -recipe_cost   (consumed)
                │        -> 增加背包道具数量 686  +cook_gain  (baked)
                └ 否 -> 打印字符串 1  "材料不足"

    卖   entering the stall  (进入碰撞触发器时 92)
           -> 打开商店 702
           -> 商店出售背包物品时 701 -> 打印字符串 1 (engine already settled)

    反馈 a wallet change  (背包货币数量变化时 684)
           -> 打印字符串 1  "货币发生变化"

    终局 the *same* 684 wallet change, fanned out a second time
           -> 获取背包货币数量 691 -> 数值大于等于 233  (>= target_coins)
                -> 双分支 2
                     ├ 是 -> 打印字符串 1  "通关"        (TERMINAL / 通关)
                     └ 否 -> 打印字符串 1  "继续加油"

The four legs 收/合成/卖/反馈 are **exactly** :func:`farming_full.build`'s graph,
reused verbatim (this module calls it), so the two can never drift: the loop body
*is* the frozen `farming_full` shape.  Everything new here is the 终局 leg hung
off the very same 684 event — a fan-out, the same technique ``plot_enter`` uses
to drive two sinks in parallel.

Why the terminal reads 691 and not a constant
---------------------------------------------

"Coins reached the target" is a fact about the *wallet*, not about a number we
baked into the graph.  So the comparison's left operand is the live ``691`` output
``amount`` (its holder comes from the 684 event's ``holder`` — a runtime entity,
never a constant) and only its right operand is the parameter ``target_coins``.
A constant left operand would print 通关 the moment the loop was entered, which is
exactly the failure the "reads 691, not a constant" test forbids.

Two honest limits (unchanged from ``farming_full``, restated so nobody mistakes
the graph for a working scene)
----------------------------------------------------------------------------------------------

* **The templates must already exist.**  ``货币`` / ``道具`` / ``商店`` templates
  are editor assets this project cannot create (no template writer in the
  bridge/CLI/MCP); their ids are parameters — ``config`` — not constants we mint.
* **The interaction scene-half is manual.**  The ``碰撞触发器`` component that
  makes a plot or a stall fire must be configured in the editor — see
  :mod:`tools.gameplan.modules.interaction`.  This graph is the *logic* half.

The 通关 print is the graph's observable end state: it is a ``打印字符串`` (1), so
it lands in the runtime log.  Nothing here claims a UI banner or a scene object
appears — only that the loop's terminal condition *fires a distinct line*.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import BRANCH, GE, PRINT, Graph
from ..plan import GraphPlan
from ..modules import currency as m2
from ..demo import farming_full

DEFAULT_NAME = "MW_API_FARM_LOOP"

#: The feedback line on every wallet change (the 反馈 leg), verbatim from the
#: ``farming_full`` body.
FEEDBACK_TEXT = "货币发生变化"

#: The terminal line printed when the wallet reaches ``target_coins``.
TERMINAL_WIN_TEXT = "通关"

#: The line printed while the wallet is still short of ``target_coins``.
TERMINAL_KEEP_TEXT = "继续加油"

#: The four reused legs' node aliases, in build order — the exact order
#: ``farming_full.build`` places them.  Exposed so a caller (and the test) can
#: tell the reused body from the terminal leg without reading every NodeSpec.
LOOP_BODY = (
    "plot_enter", "harvest", "crop_used", "crop_count", "enough", "gate",
    "consume", "bake", "short", "stall_enter", "open_shop", "sold", "sold_note",
    "money_changed", "money_note",
)

#: The terminal leg's node aliases, in build order (the part this module adds).
TERMINAL_NODES = ("ter_read", "ter_cmp", "ter_gate", "win", "keep")


@dataclass(frozen=True)
class LoopConfig(farming_full.FarmFullConfig):
    """``FarmFullConfig`` plus the one knob the terminal condition needs.

    ``target_coins`` is the wallet amount at which the loop announces 通关.  Every
    other field keeps ``FarmFullConfig``'s meaning and default.
    """

    target_coins: int = 100


def build(config: LoopConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the closed loop.  Returns an *unvalidated* :class:`Graph`.

    The 收/合成/卖/反馈 body is delegated to :func:`farming_full.build` (so the
    two graphs cannot drift); the 终局 leg is appended onto the same
    ``money_changed`` (684) event the 反馈 print already hangs off.
    """
    # --- 收 → 合成 → 卖 → 反馈 : the frozen 15-node body, reused verbatim ----
    g = farming_full.build(config, name=name)

    # --- 终局 : the same 684 wallet-change event, second fan-out --------------
    # Read the live wallet (691), compare it to the target, and branch.  The
    # holder is the event's own entity — never a constant.
    money = g.handle("money_changed")

    ter_read = m2.read(
        g,
        holder=(money, "holder"),
        currency_id=config.currency_id,
        currency_slot=config.currency_slot,
        alias="ter_read",
    )

    ter_cmp = g.place(GE, "ter_cmp")                  # 数值大于等于
    ter_cmp.data_from(ter_read, "amount", "left")     # 691.amount -> 左值
    ter_cmp.const("right", config.target_coins, "int")

    ter_gate = g.place(BRANCH, "ter_gate")            # 双分支
    money.flow_to(ter_gate)                            # 684.then -> 双分支
    ter_gate.data_from(ter_cmp, "result", "condition")

    win = g.place(PRINT, "win")                        # 是：通关
    ter_gate.flow_to(win, "true")
    win.const("text", TERMINAL_WIN_TEXT, "string")

    keep = g.place(PRINT, "keep")                      # 否：继续加油
    ter_gate.flow_to(keep, "false")
    keep.const("text", TERMINAL_KEEP_TEXT, "string")

    return g


def build_plan(config: LoopConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the closed loop, returning the :class:`GraphPlan`.

    Raises :class:`tools.gameplan.plan.PlanError` if any node, edge or constant is
    inconsistent with ``data/node-contracts``.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


def golden_plans() -> dict[str, GraphPlan]:
    """The canonical ``name -> plan`` this module pins (mirrors ``golden``'s shape).

    Kept here (not in :mod:`tools.gameplan.golden`) so the committed snapshot is
    generated from exactly the config the tests read: one plan, frozen at the
    default ``LoopConfig`` used across this project's demos.
    """
    return {
        "farming_loop": build_plan(
            LoopConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)
        )
    }
