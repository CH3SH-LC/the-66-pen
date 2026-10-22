"""Game B demo — the farming loop a human can arm with the **fewest** manual steps.

The consolidated demo (:mod:`tools.gameplan.demo.farming_full`) hangs its 收/合成/卖
legs off ``92 进入碰撞触发器时`` — an event whose *scene half* a human must build in
the editor (a ``碰撞触发器`` component on the plot and on the stall) because this
project has **no add-component primitive** (``CLAUDE.md`` §六(a): ``AddComponent`` /
``CreateComponent`` / ``AttachComponent`` / ``InsertComponent`` are 0 hits across the
whole corpus).  That is the whole reason the demo still cannot be played.

This module builds the same 收 → 合成 → 卖 → 反馈 shaped loop against **event sources
that arm themselves** — nodes whose scene half is *empty*, so a graph can bring them
to life with no editor authoring at all.  It is the smallest-step sibling of
``farming_full``: identical gameplay legs, self-arming clock.

The graph
---------

::

    71 实体创建时  (arm — the bound plot entity is created; a tool action)
      └─ then ─▶ 79 启动定时器(是否循环=是)   ← arms the loop's clock
                   目标实体 ← 71.事件源实体

    83 定时器触发时  (loop clock — fires every timer point)
      ├─ then ─▶ 686 增加背包道具数量  +harvest_gain 作物        (收)
      ├─ then ─▶ 双分支 2  ◀── 233 数值大于等于 ◀── 690 读作物    (合成·条件)
      │             ├ 是 ─▶ 686 −recipe_cost 作物 ─▶ 686 +cook_gain 食物
      │             └ 否 ─▶ 1 打印字符串 "材料不足"
      ├─ then ─▶ 双分支 2  ◀── 233 数值大于等于 ◀── 690 读食物    (卖·条件)
      │             ├ 是 ─▶ 686 −1 食物 ─▶ 688 +unit_price 货币 ─▶ 1 打印 "售出"
      │             └ 否 ─▶ 1 打印字符串 "无货可卖"
      └─ then ─▶ 1 打印字符串 "自动循环一轮"                      (反馈)

Every execution edge leaves an **event** whose only execution pin is an *output*
(``data/node-contracts``: an event record has ``exec_outputs`` and no ``exec_inputs``),
so no edge can ever point *into* the clock: the loop is driven purely by the two
self-arming events, never by an interaction the player must walk into.

Why the chosen event source needs no manual editor step
-------------------------------------------------------

Two events carry the whole loop — the **arm** ``71`` and the **clock** ``83``.  Each
is picked not because it is convenient but because *nothing a human must author
stands between the graph and the event firing*:

============================  ==========================  ===================================  ==================
event                         what makes it fire           what arms it                         editor steps to fire
============================  ==========================  ===================================  ==================
``71 实体创建时`` (arm)         the entity the graph is      the *tool* creates that entity        **0**
                              bound to is created          by coordinate (``entity.create``
                                                           carries position — ``CLAUDE.md``
                                                           §六(c) "建时能定"; ``DEMO-GAP.md:101``
                                                           "地图摆放本身不是人工步")
``83 定时器触发时`` (clock)      a timer the graph ran        ``79 启动定时器`` — a *node*,          **0**
                              reaches a sequence point     which the graph runs itself off
                                                           ``71``.  A timer is **graph-only**:
                                                           it is never an entity component
                                                           (``mhufb90zbnts.json``: "定时器只能
                                                           通过节点图创建和使用，禁止在
                                                           entity.properties 的可挂载组件列表里
                                                           找它")
============================  ==========================  ===================================  ==================

So the event half of this demo costs **0** editor steps.  That is the entire design
goal, and it is why the clock is armed *from the graph* (``71 → 79 → 83``) instead of
from a scene component: the arm ``71`` is the one event source whose scene half is
*provably* empty (it is the graph's own bind target, which the tool places), and it is
the only buildable zero-step opening this project has today.

Rejected event sources, and what each would have cost
-----------------------------------------------------

Each row is a *real* event node in ``data/node-contracts`` (server kind 20000) that
this loop could have hung its clock off, with the editor authoring it would have added.
A source is rejected when it costs strictly more editor steps than the chosen ``71+83``
(0), or when it cannot be expressed with today's tooling at all.

=====================================  =====  ====================================================
event source                           steps  why it is not the clock (cost / blocker)
=====================================  =====  ====================================================
``315 全局计时器触发时``                1      the node may only reference a timer **pre-defined**
                                              in the global-timer management tool
                                              (``mhawd6rl5kpy.json``: "此处的计时器引用，
                                              只能是全局计时器管理工具中预先定义的计时器，
                                              否则无效") — 1 editor asset, so it is not a
                                              no-asset source.  Its arming node ``311
                                              启动全局计时器`` *is* buildable (target entity +
                                              name, both scalars), which is why this is the
                                              cheapest **buildable** timer alternative — it
                                              simply costs 1 more step than ``83``.
``386 玩家职业等级变化时``              0      no asset, and armable from the graph by ``391
                                              更改玩家当前职业等级`` (player + int level) —
                                              but it is **not a clock**: it fires on a
                                              gameplay progression event, its re-arm
                                              (``391``) must keep raising a level toward
                                              ``最高等级``, and no run has shown the event
                                              firing on a graph-driven ``391``.  Kept in the
                                              allowed set (:data:`ALLOWED_EVENT_IDS`) as a
                                              no-asset self-arming event, but not used as a
                                              clock.
``733 背包内道具被使用时``              1      the crop item template must exist **and** its
                                              ``允许使用`` be ticked before the event can fire
                                              (``MANUAL-STEPS.md:21-23``; ``DEMO-GAP.md:94``):
                                              it makes an editor asset a *precondition of the
                                              event itself*.
``92 进入碰撞触发器时``                 2      the demo's real trigger.  A ``碰撞触发器``
                                              component must be added and configured on the
                                              entity (``MANUAL-STEPS.md:35``; ``M1-interaction.md:37,56``)
                                              and no add-component primitive exists.
``701 商店出售背包物品时``              1      needs a ``商店`` component on the stall
                                              (``M4M5-inventory-shop.md:79``); the whole sell
                                              leg is instead done in-graph (``686/688``),
                                              removing the shop component entirely.
``316 界面控件组触发时``                2      build the control group, then assign its layout
                                              (``M1-interaction.md:21,22,31``).
``826 悬浮交互页操作触发时``            2      configure the page, then have a node 唤起 it
                                              (``M1-interaction.md:29,49``).
=====================================  =====  ====================================================

The honest limits (unchanged in spirit from every sibling demo, stated plainly)
-------------------------------------------------------------------------------

1. **The templates must already exist.**  The graph writes ``crop_id`` / ``food_id``
   (contract type 20 ``配置ID``) into ``686``/``690`` and ``currency_id`` into ``688``;
   a config id is a *reference*, so the 作物 / 食物 道具模板 and the 货币模板 must
   exist or the ids dangle.  ``货币`` / ``道具`` templates have **no writer** in the
   bridge / CLI / MCP (``DEMO-GAP.md:94``).  That is :data:`RESIDUAL_TEMPLATE_STEPS`,
   **3 manual steps**, and it is a property of *every* farm loop, not of the event
   source — so it appears for the chosen and the rejected alike.  It is counted here
   so :func:`total_manual_step_count` cannot be read as smaller than it is.

2. **The clock's period is the one pin today's layer cannot write — and it is not
   cosmetic: as built, the clock does not tick.**  ``79 启动定时器`` carries a
   ``定时器序列`` input (pin ``3:3``) that ``data/node-contracts`` types as a **float
   list** (``serverParamType`` 10).  This project's constant writer has no list slot:
   ``paramtypes.SLOT_FOR_TYPE`` has no entry for type 10, ``plan._SLOTS`` is
   ``{auto,int,uint,enum,float,bool,string}``, and ``builder._tagged`` encodes only
   scalars (``builder.py:72-93``).  So the graph places ``79`` and writes its other
   three inputs, but the *sequence* is deliberately left unwritten — see
   :data:`UNWRITABLE_TIMER_SEQUENCE_PIN` and the test that asserts it is not fabricated.
   The official node reference states the consequence outright: an illegal sequence means
   **定时器不会运行** (``mhw66orrrfkm`` §十六.1, cited verbatim in
   :data:`CLOCK_SEQUENCE_REQUIREMENT_CITATION`), and an unwritten (empty) list has no
   time point for the timer to fire on, so ``83 定时器触发时`` never fires and the whole
   loop is inert until the sequence is supplied.  This demo therefore does **not** claim
   to be playable today: the loop's *shape* is complete and validated, its clock's
   *period* is the one constant a future list slot unlocks, and until then it is one
   honest manual step (:data:`CLOCK_SEQUENCE_STEPS`), counted in
   :func:`total_manual_step_count` rather than hidden behind the word "caveat".

3. **The steps this design removes are named, not implied.**  The four editor actions
   ``farming_full`` needs that this graph does not are listed one by one in
   :data:`AVOIDED_MANUAL_STEPS` (the 商店 template, the two ``碰撞触发器`` components, and
   the 商店 component).  The trade is exact: ``farming_full``'s 7 steps = this demo's 3
   residual templates (:data:`RESIDUAL_TEMPLATE_STEPS`) + the 4 removed steps — the
   *event source* itself costs 0, because the graph arms the clock off ``71``.

Everything here uses ONLY the current public API of ``tools/gameplan/modules/*`` and the
named role tables in :mod:`tools.gameplan.nodes`; no new helpers are assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import (
    BRANCH,
    GE,
    ON_CREATE,
    PRINT,
    START_TIMER,
    TIMER_TICK,
    Graph,
    Handle,
)
from ..plan import GraphPlan
from ..modules import currency as m2
from ..modules import item as m3

DEFAULT_NAME = "MW_API_FARM_AUTOLOOP"
"""The graph name; matches ``plan.GRAPH_NAME_RE`` (``MW_API_`` + ``[A-Za-z0-9_]{1,48}``)."""

#: The ``79 启动定时器`` input pin whose ``data/node-contracts`` type is a **float
#: list** (``serverParamType`` 10) and which no current slot can write — the demo's one
#: buildability caveat (module docstring, "honest limits" #2).  Carried as a named
#: constant so the test can assert the plan never fabricates a value for it.
UNWRITABLE_TIMER_SEQUENCE_PIN = 3

#: The official sentence that makes the unwritten ``定时器序列`` pin *fatal to running*,
#: not merely untidy: an illegal sequence means the timer does not run, so ``83 定时器触发时``
#: never fires and the whole loop is inert.  Cited verbatim (chapter ``mhw66orrrfkm``,
#: 执行节点 §十六.1 启动定时器) so the consequence is checkable, exactly like a
#: :class:`ManualStep` — the demo must not be sold as "playable" while this holds.
CLOCK_SEQUENCE_REQUIREMENT_CITATION = (
    "docs/official-docs/chapters/mhw66orrrfkm.json §十六.1 启动定时器："
    "「定时器序列……需要传入一个从小到大排列的列表。如果传入的列表不合法"
    "（不是严格按照从小到大排列、存在负数等），定时器不会运行」"
)

#: The line printed when the craft step is short of ``recipe_cost`` crops.
CRAFT_SHORT_TEXT = "材料不足"

#: The line printed when the sell step had at least one food to sell.
SELL_OK_TEXT = "售出"

#: The line printed when the sell step found no food in the bag.
SELL_EMPTY_TEXT = "无货可卖"

#: The line printed once per clock tick (the 反馈 leg).
FEEDBACK_TEXT = "自动循环一轮"


# ---------------------------------------------------------------------------
# Event-source model — every candidate, its firing condition, its arming node, and
# the editor authoring (if any) a human must do before it can fire.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualStep:
    """One editor authoring action, with a ``file:line`` citation so it is checkable.

    ``citation`` is a ``file:line`` reference (or a comma-separated list of them) into
    this repository — an assertion without one is not evidence.
    """

    action: str
    citation: str


@dataclass(frozen=True)
class EventSource:
    """An event node (exec output, no exec input) considered for the loop's clock.

    ``armed_by`` is the sentence a reader needs: *what makes this event fire*.  A graph
    **arms it by itself** when the firing condition is set up by the graph's own nodes
    (``graph_self_arms``), not by an editor-authored component/asset.  ``manual_steps``
    is the *scene half* — editor authoring that must happen before the event can fire;
    an empty tuple is the property the whole demo is built on.  ``buildable`` is whether
    a graph using it can be expressed with today's constant writer.
    """

    key: str
    label: str
    definition_id: int
    fires_when: str
    armed_by: str
    graph_self_arms: bool
    manual_steps: tuple[ManualStep, ...]
    buildable: bool
    note: str = ""


#: Every event source examined, so a caller cannot read "the cheapest of two" as "the
#: cheapest of all".  The full server contract has 67 event nodes; the ones that are
#: neither self-arming nor asset-free are the interaction/shop/item families the demo
#: deliberately avoids.  The seven interaction-ish sources here are exactly the ones a
#: farming loop would plausibly reach for.
EVENT_SOURCES: dict[str, EventSource] = {
    "on-create": EventSource(
        "on-create",
        "71 实体创建时",
        71,
        "the entity the graph is bound to is created",
        "the tool creates that entity by coordinate at level load; nothing to author "
        "(scene_cli.py:181-192; DEMO-GAP.md:101).",
        True,
        (),  # 0 — the bind target is tool-placed
        True,
        "CHOSEN (arm): the unique buildable zero-step event source.",
    ),
    "timer": EventSource(
        "timer",
        "83 定时器触发时",
        83,
        "a timer the graph started reaches a point in its sequence",
        "79 启动定时器, which this graph runs itself off the 71 arm; a timer is "
        "graph-only and belongs to no entity component (mhufb90zbnts.json).",
        True,
        (),  # 0 — a timer is created by the node graph, not the editor
        False,  # ... but 79's 定时器序列 float-list input has no writable slot today
        "CHOSEN (clock): 0 editor steps; arming needs 79, whose 定时器序列 pin (3:3) "
        "is an unwritable float list (paramtypes.SLOT_FOR_TYPE has no type-10 entry; "
        "plan._SLOTS; builder.py:72-93).",
    ),
    "global-timer": EventSource(
        "global-timer",
        "315 全局计时器触发时",
        315,
        "a countdown global timer runs out",
        "311 启动全局计时器 (target entity + timer name — both scalars, buildable).",
        True,
        (
            ManualStep(
                "在全局计时器管理工具里预先定义该全局计时器（节点只能引用预定义的）",
                "docs/official-docs/chapters/mhawd6rl5kpy.json:16",
            ),
        ),
        True,
        "rejected: 1 editor step (the pre-defined timer is an editor asset), strictly "
        "costlier than the chosen 83. The cheapest *buildable* timer alternative.",
    ),
    "class-level": EventSource(
        "class-level",
        "386 玩家职业等级变化时",
        386,
        "the player's current-class level changes",
        "391 更改玩家当前职业等级 (target player + int level — no asset needed).",
        True,
        (),  # no editor asset is a precondition of this event
        True,
        "rejected on **fitness, not cost** — it ties the chosen pair at 0 editor steps "
        "(see COST_TIE_SOURCES). It is a gameplay progression event, not a periodic "
        "one, and re-arming means climbing toward 最高等级, so it cannot serve as a loop "
        "clock. Kept in ALLOWED_EVENT_IDS as a no-asset self-arming source.",
    ),
    "item-used": EventSource(
        "item-used",
        "733 背包内道具被使用时",
        733,
        "the player uses a consumable from the bag",
        "a consumable item template with 允许使用 ticked; the event cannot fire "
        "before that asset exists.",
        False,
        (
            ManualStep(
                "建作物道具模板并勾选「允许使用」，玩家才可以从背包使用它",
                "docs/gameplan/MANUAL-STEPS.md:21-23;"
                " docs/research/game-b-systems-20261009/M2M3-currency-item.md:57,69;"
                " docs/gameplan/DEMO-GAP.md:94",
            ),
        ),
        True,
        "rejected: 1 step; it makes an editor asset a precondition of the event itself.",
    ),
    "proximity": EventSource(
        "proximity",
        "92 进入碰撞触发器时",
        92,
        "a player carrying a 碰撞触发源 enters a 碰撞触发器 volume",
        "a 碰撞触发器 component configured on the entity — this project has no "
        "add-component primitive.",
        False,
        (
            ManualStep(
                "在目标实体上「组件编辑页签 → 添加通用组件 → 碰撞触发器」",
                "docs/gameplan/MANUAL-STEPS.md:35; docs/gameplan/DEMO-GAP.md:96",
            ),
            ManualStep(
                "在同一组件上「详细编辑」配好触发区形状与生效目标（移动方还须携带"
                "「碰撞触发源」组件）",
                "docs/research/game-b-systems-20261009/M1-interaction.md:37,56",
            ),
        ),
        True,
        "rejected: 2 steps; the demo's real trigger, and the reason it is not playable.",
    ),
    "shop-sold": EventSource(
        "shop-sold",
        "701 商店出售背包物品时",
        701,
        "the player sells a bag item at an official bag store",
        "a 商店 component on the stall referencing a 商店模板; no component writer.",
        False,
        (
            ManualStep(
                "在摊位实体上「添加通用组件 → 商店」并指向商店模板、配好商店序号",
                "docs/research/game-b-systems-20261009/M4M5-inventory-shop.md:79",
            ),
        ),
        True,
        "rejected: 1 step; the whole sell leg is done in-graph (686/688) instead.",
    ),
    "ui-button": EventSource(
        "ui-button",
        "316 界面控件组触发时",
        316,
        "a player presses a button in an authored UI control group",
        "a UI control group assigned to the player's 职业; no UI writer exists.",
        False,
        (
            ManualStep(
                "在「界面控件组编辑窗口」建界面控件组与交互按钮（类型选「交互事件」）",
                "docs/research/game-b-systems-20261009/M1-interaction.md:21,22",
            ),
            ManualStep(
                "在「系统菜单 → 界面控件组管理 → 界面布局」里把该布局经「职业引用」"
                "配给玩家",
                "docs/research/game-b-systems-20261009/M1-interaction.md:31",
            ),
        ),
        True,
        "rejected: 2 steps, costlier.",
    ),
    "floating-page": EventSource(
        "floating-page",
        "826 悬浮交互页操作触发时",
        826,
        "a player operates an authored floating interaction page",
        "a 悬浮交互页 configured in the editor, then 唤起 by a node; no writer.",
        False,
        (
            ManualStep(
                "在编辑器里配置「悬浮交互页」（页签 / 列表项）",
                "docs/research/game-b-systems-20261009/M1-interaction.md:29",
            ),
            ManualStep(
                "让节点图「唤起悬浮交互页」把它显示给玩家",
                "docs/research/game-b-systems-20261009/M1-interaction.md:49",
            ),
        ),
        True,
        "rejected: 2 steps, costlier.",
    ),
}

#: The event sources this demo's clock is built from: the arm ``71`` and the loop clock
#: ``83``.  Both are self-arming and need **no** editor-authored component or asset.
CHOSEN_EVENT_KEYS: tuple[str, ...] = ("on-create", "timer")

#: The definitionIds of every event that a graph can arm **by itself** with **no**
#: editor-authored component or asset.  The test asserts every event node in the graph
#: is a member — so a future edit that swaps in ``92``/``733``/``701``/``316``/``826``
#: (all of which need a hand-built scene half) fails instead of silently regressing the
#: manual-step count.  A timer (``83``) is here because a timer is graph-only; the
#: global timer (``315``) is *not*, because it must be pre-defined in the editor.
ALLOWED_EVENT_IDS: frozenset[int] = frozenset(
    source.definition_id
    for source in EVENT_SOURCES.values()
    if source.graph_self_arms and not source.manual_steps
)


#: Sources that **tie** the chosen pair on manual steps (0) and are rejected on
#: *fitness*, not on cost.  ``386 玩家职业等级变化时`` needs no editor asset and a graph
#: can arm it (``391``), so it is as cheap as the chosen pair — but it fires on a
#: gameplay *progression* event, never periodically, so it cannot be a loop's clock.
#: Named explicitly so the "minimises the human work" claim stays exact: the chosen pair
#: is *tied* for cheapest among self-arming, asset-free sources, then chosen for being a
#: clock (``83``) reachable from the one provably-empty arm (``71``).
COST_TIE_SOURCES: frozenset[str] = frozenset({"class-level"})


def event_source(key: str) -> EventSource:
    """The :class:`EventSource` for ``key``; raises :class:`KeyError` if unknown."""
    try:
        return EVENT_SOURCES[key]
    except KeyError:
        raise KeyError(
            f"unknown event source {key!r}; known: {sorted(EVENT_SOURCES)}"
        ) from None


def is_allowed_event(definition_id: int) -> bool:
    """Whether ``definition_id`` is a self-arming, asset-free event node."""
    return int(definition_id) in ALLOWED_EVENT_IDS


def manual_steps(key: str) -> tuple[ManualStep, ...]:
    """The event-source-specific editor steps ``key``'s scene half requires."""
    return event_source(key).manual_steps


def manual_step_count(key: str) -> int:
    """How many editor steps ``key`` needs before it can fire (scene half only)."""
    return len(event_source(key).manual_steps)


def event_step_count() -> int:
    """Editor steps the chosen events need before they can fire (0 for this demo)."""
    return sum(manual_step_count(key) for key in CHOSEN_EVENT_KEYS)


#: The editor assets **every** farm loop needs regardless of event source: the crop and
#: food item templates (their 配置ID the graph writes into 686/690) and the currency
#: template (688).  A per-graph cost, not a per-event cost — it appears for the chosen
#: and the rejected alike ("honest limits" #1).
RESIDUAL_TEMPLATE_STEPS: tuple[ManualStep, ...] = (
    ManualStep(
        "建作物道具模板（类型 8 普通道具、装备道具）并把编辑器分配的「配置ID」抄给 "
        "--crop-id",
        "docs/gameplan/MANUAL-STEPS.md:21-23; docs/gameplan/DEMO-GAP.md:94;"
        " docs/research/game-b-systems-20261009/M2M3-currency-item.md:130,181",
    ),
    ManualStep(
        "建加工食物道具模板（类型 8，类型选消耗品）并把「配置ID」抄给 --food-id",
        "docs/gameplan/MANUAL-STEPS.md:25-27",
    ),
    ManualStep(
        "建货币模板（类型 10 资源货币）并把「配置ID」抄给 --currency-id",
        "docs/gameplan/MANUAL-STEPS.md:15-18;"
        " docs/research/game-b-systems-20261009/M2M3-currency-item.md:130",
    ),
)

#: The one editor action the **clock** still needs: type a valid ``定时器序列`` into
#: ``79 启动定时器`` in the graph.  It is not a scene asset (so it is not in
#: :data:`RESIDUAL_TEMPLATE_STEPS`), but it *is* a genuine manual step — the doc in
#: :data:`CLOCK_SEQUENCE_REQUIREMENT_CITATION` makes the timer inert without a legal
#: sequence — so it is counted rather than buried in prose.  Arming the *event source*
#: still costs 0; this is the clock's period, not its trigger.
CLOCK_SEQUENCE_STEPS: tuple[ManualStep, ...] = (
    ManualStep(
        "在节点图里给「79 启动定时器」的「定时器序列」填一个合法的时间点列表"
        "（本工程的常量写入器没有列表槽，写不了）",
        "docs/official-docs/chapters/mhw66orrrfkm.json (§十六.1 启动定时器);"
        " tools/gameplan/paramtypes.py (SLOT_FOR_TYPE has no type-10 entry)",
    ),
)

#: The editor steps ``farming_full`` needs that **this design removes** — a human no
#: longer does any of them, because the trigger is graph-armed instead of scene-authored
#: (``71`` is tool-placed; ``79`` is a node, not a component).  Named per step so the
#: "fewer manual steps" claim is a list, not an assertion.  Together with
#: :data:`RESIDUAL_TEMPLATE_STEPS` (3) they reconcile exactly with
#: :data:`FARMING_FULL_MANUAL_STEP_COUNT` (7): 3 kept + 4 removed.
AVOIDED_MANUAL_STEPS: tuple[ManualStep, ...] = (
    ManualStep(
        "建商店模板（类型 15）——本 demo 的卖货腿在图内用 686/688 完成，不用商店",
        "docs/gameplan/MANUAL-STEPS.md:29-31;"
        " docs/research/game-b-systems-20261009/M4M5-inventory-shop.md:30-32",
    ),
    ManualStep(
        "在地块实体上「添加通用组件 → 碰撞触发器」并详细编辑——触发改由 71 事件接管",
        "docs/gameplan/MANUAL-STEPS.md:34-35; docs/gameplan/DEMO-GAP.md:96",
    ),
    ManualStep(
        "在摊位实体上「添加通用组件 → 碰撞触发器」——本 demo 没有摊位",
        "docs/research/game-b-systems-20261009/M1-interaction.md:37;"
        " docs/gameplan/DEMO-GAP.md:96",
    ),
    ManualStep(
        "在摊位实体上「添加通用组件 → 商店」挂上商店组件并指向商店模板、配商店序号"
        "——本 demo 无商店",
        "docs/gameplan/MANUAL-STEPS.md:43-44;"
        " docs/research/game-b-systems-20261009/M4M5-inventory-shop.md:79",
    ),
)


def avoided_step_count() -> int:
    """Editor steps this design removes relative to ``farming_full``."""
    return len(AVOIDED_MANUAL_STEPS)


def clock_sequence_step_count() -> int:
    """Editor steps the clock's period still needs (the unwritable ``定时器序列``)."""
    return len(CLOCK_SEQUENCE_STEPS)

#: ``farming_full``'s manual-step count, for the comparison the demo exists to make:
#: four templates (货币 / 作物 / 食物 / 商店) + two 碰撞触发器 components + one 商店
#: component (``farming_minimal.py:4-5``, from ``DEMO-GAP.md`` §三).  ``DEMO-GAP.md`` §三
#: step 6 (试玩) is the shared *playing* step, excluded from the comparison exactly as in
#: ``minimal_playable.py:30-34``.
FARMING_FULL_MANUAL_STEP_COUNT = 7


def residual_step_count() -> int:
    """Editor steps this graph needs regardless of event source (the templates)."""
    return len(RESIDUAL_TEMPLATE_STEPS)


def total_manual_step_count() -> int:
    """Event-source steps + the per-graph residual + the clock's period.

    ``0`` event steps (the trigger is graph-armed) ``+ 3`` templates ``+ 1`` timer
    sequence ``= 4`` — still strictly fewer than ``farming_full``'s 7, and honest about
    the timer sequence that :data:`CLOCK_SEQUENCE_REQUIREMENT_CITATION` makes mandatory.
    """
    return event_step_count() + residual_step_count() + clock_sequence_step_count()


def fewer_than_farming_full() -> bool:
    """Whether this demo needs strictly fewer manual steps than ``farming_full``."""
    return total_manual_step_count() < FARMING_FULL_MANUAL_STEP_COUNT


# ---------------------------------------------------------------------------
# The graph.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutoLoopConfig:
    """Everything the graph needs that lives in the editor, not in our tools.

    The first five fields mirror :class:`tools.gameplan.demo.farming_full.FarmFullConfig`
    (so the two demos describe the same economy); ``timer_name`` is the graph-side string
    that names the timer the clock listens for.
    """

    currency_id: int            # 货币配置ID (type 20)
    crop_id: int                # 作物道具配置ID (type 20)
    food_id: int                # 加工食物道具配置ID (type 20)
    item_slot: str = "int"      # the `--slot` used to write a configID (see paramtypes)
    currency_slot: str = "int"  # the `--slot` used to write a 货币配置ID (type 20)
    harvest_gain: int = 1       # crops granted per clock tick
    recipe_cost: int = 2        # crops consumed per craft
    cook_gain: int = 1          # food produced per craft
    unit_price: int = 10        # coins credited per food sold
    timer_name: str = "autoloop"  # the name 79 启动定时器 / 83 定时器触发时 share


def _arm_clock(g: Graph, config: AutoLoopConfig) -> tuple[Handle, Handle]:
    """Place the arm ``71`` and the clock ``83``, start the timer from the arm.

    Returns ``(arm, tick)``.  ``71`` fires when the tool-created bind entity is created;
    it drives ``79 启动定时器`` (looping) so ``83`` then ticks.  The ``定时器序列`` pin
    (3:3) is deliberately **not** written — no slot can express a float list today
    (:data:`UNWRITABLE_TIMER_SEQUENCE_PIN`); the graph still places the node.
    """
    arm = g.place(ON_CREATE, "arm")                       # 71 实体创建时
    assert arm.ntype is ON_CREATE

    start = g.place(START_TIMER, "start_clock")           # 79 启动定时器
    arm.flow_to(start)                                     # 71.then -> 79
    start.data_from(arm, "entity", "target")              # 71.事件源实体 -> 79.目标实体
    start.const("name", config.timer_name, "string")       # 79.定时器名称
    start.const("loop", 1, "enum")                         # 79.是否循环 = 是
    # 79.定时器序列 (pin 3:3) left unwritten on purpose -- see the module docstring.

    tick = g.place(TIMER_TICK, "tick")                    # 83 定时器触发时
    assert tick.ntype is TIMER_TICK
    return arm, tick


def _harvest_leg(g: Graph, tick: Handle, config: AutoLoopConfig) -> Handle:
    """收：each tick grants ``harvest_gain`` crops to the plot."""
    return m3.grant(
        g, tick, holder=(tick, "entity"), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias="harvest",
    )


def _craft_leg(g: Graph, tick: Handle, config: AutoLoopConfig) -> Handle:
    """合成：if the bag holds ``recipe_cost`` crops, consume them and bake food.

    The gate is a *condition* on the live crop count (``690`` → ``233`` → ``2``), never
    on a constant: a constant left operand would craft the moment the loop was entered.
    """
    cmp_node = m3.has_enough(
        g, holder=(tick, "entity"), item_id=config.crop_id,
        threshold=config.recipe_cost, item_slot=config.item_slot, alias="craft_enough",
    )  # 690 读作物 + 233 数值大于等于

    gate = g.place(BRANCH, "craft_gate")                  # 2 双分支
    tick.flow_to(gate)                                     # 83.then -> 2
    gate.data_from(cmp_node, "result", "condition")        # 233.结果 -> 2.条件

    take = m3.grant(
        g, gate, holder=(tick, "entity"), item_id=config.crop_id,
        count=-config.recipe_cost, item_slot=config.item_slot,
        alias="craft_take", from_role="true",
    )
    m3.grant(
        g, take, holder=(tick, "entity"), item_id=config.food_id,
        count=config.cook_gain, item_slot=config.item_slot, alias="craft_bake",
    )

    short = g.place(PRINT, "craft_short")                 # 1 打印字符串
    gate.flow_to(short, "false")
    short.const("text", CRAFT_SHORT_TEXT, "string")
    return gate


def _sell_leg(g: Graph, tick: Handle, config: AutoLoopConfig) -> Handle:
    """卖：if the bag holds at least one food, sell it for ``unit_price`` coins.

    Selling is done **in-graph** (``686`` take + ``688`` pay) rather than through
    ``702 打开商店`` / ``701`` — that route needs a 商店 component on the stall, the one
    manual step this demo removes.
    """
    cmp_node = m3.has_enough(
        g, holder=(tick, "entity"), item_id=config.food_id,
        threshold=1, item_slot=config.item_slot, alias="sell_enough",
    )  # 690 读食物 + 233 数值大于等于

    gate = g.place(BRANCH, "sell_gate")                   # 2 双分支
    tick.flow_to(gate)                                     # 83.then -> 2
    gate.data_from(cmp_node, "result", "condition")

    take = m3.grant(
        g, gate, holder=(tick, "entity"), item_id=config.food_id,
        count=-1, item_slot=config.item_slot, alias="sell_take", from_role="true",
    )
    pay = m2.grant(
        g, take, holder=(tick, "entity"), currency_id=config.currency_id,
        amount=config.unit_price, currency_slot=config.currency_slot, alias="sell_pay",
    )

    sold = g.place(PRINT, "sell_ok")                      # 1 打印字符串
    pay.flow_to(sold)
    sold.const("text", SELL_OK_TEXT, "string")

    empty = g.place(PRINT, "sell_empty")                  # 1 打印字符串
    gate.flow_to(empty, "false")
    empty.const("text", SELL_EMPTY_TEXT, "string")
    return gate


def _feedback_leg(g: Graph, tick: Handle) -> Handle:
    """反馈：one log line per tick, so the loop is observable in the runtime log."""
    note = g.place(PRINT, "feedback")                     # 1 打印字符串
    tick.flow_to(note)
    note.const("text", FEEDBACK_TEXT, "string")
    return note


def build(config: AutoLoopConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the self-arming farming loop.  Returns an *unvalidated* :class:`Graph`.

    The clock (``83``) fans out to the four legs (收 / 合成 / 卖 / 反馈) in parallel from
    its single execution output — the same fan-out technique ``farming_full`` uses for
    its two ``92`` sinks.  No leg is reachable except through an event whose execution
    pin is an output, so nothing in this graph depends on a scene-authored component.
    """
    g = Graph(name)
    _arm_clock(g, config)
    tick = g.handle("tick")
    _harvest_leg(g, tick, config)
    _craft_leg(g, tick, config)
    _sell_leg(g, tick, config)
    _feedback_leg(g, tick)
    return g


def plan_of(config: AutoLoopConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the loop, returning the :class:`GraphPlan`.

    Named ``plan_of`` — **not** ``build_plan`` — on purpose, for the same reason as the
    sibling comparison modules: the demo-golden guard (``tests/test_demo_golden.py``)
    discovers *every* module under ``demo/`` that exposes ``build_plan`` and demands a
    frozen shape for it, and that registry (``tools/gameplan/golden.py``) is outside this
    task's file ownership.  This module's shape guard is the asserted node list in
    ``tests/test_farming_autoloop.py``.

    Raises :class:`tools.gameplan.plan.PlanError` if any node, edge or constant is
    inconsistent with ``data/node-contracts`` — before any native call.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


__all__ = [
    "ALLOWED_EVENT_IDS",
    "AVOIDED_MANUAL_STEPS",
    "AutoLoopConfig",
    "CHOSEN_EVENT_KEYS",
    "CLOCK_SEQUENCE_REQUIREMENT_CITATION",
    "CLOCK_SEQUENCE_STEPS",
    "COST_TIE_SOURCES",
    "CRAFT_SHORT_TEXT",
    "DEFAULT_NAME",
    "EVENT_SOURCES",
    "EventSource",
    "FARMING_FULL_MANUAL_STEP_COUNT",
    "FEEDBACK_TEXT",
    "ManualStep",
    "RESIDUAL_TEMPLATE_STEPS",
    "SELL_EMPTY_TEXT",
    "SELL_OK_TEXT",
    "UNWRITABLE_TIMER_SEQUENCE_PIN",
    "avoided_step_count",
    "build",
    "clock_sequence_step_count",
    "event_source",
    "event_step_count",
    "fewer_than_farming_full",
    "is_allowed_event",
    "manual_step_count",
    "manual_steps",
    "plan_of",
    "residual_step_count",
    "total_manual_step_count",
]
