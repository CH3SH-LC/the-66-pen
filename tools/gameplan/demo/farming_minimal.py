"""The farming demo variant a human can fire with the **fewest** manual steps.

The demo loop (:mod:`tools.gameplan.demo.farming_full`) needs a pile of *manual*
editor work before it can fire at all: four templates, two collision-trigger
components, and a shop component (``docs/gameplan/DEMO-GAP.md`` §三, six rows).
This module builds the *other* end of that trade: the smallest farm-shaped graph
whose chosen event source has **zero** event-specific editor steps, so the only
thing left for a human is the one asset any farm needs at all.

The graph
---------

::

    plot_created  71 实体创建时  ->  harvest  686 增加背包道具数量  (+harvest_gain crops)

Two nodes, two edges: one execution edge (``71.then`` → ``686``) and one data
edge (``71.entity`` → ``686.holder``).  Nothing else.  It is the demo's 收
(harvest) leg — ``+harvest_gain`` crops granted to the plot's creator — with the
event source swapped from the demo's ``92 进入碰撞触发器时`` to ``71``.

Why the event source is the whole story
---------------------------------------

Every other choice (which nodes, which wires, which constants) is *identical*
between this graph and :func:`build_alternative`; the **only** variable is which
event node sits on the left, and therefore how much editor authoring a human must
do before the graph can fire.  So the design is: hold the graph fixed, pick the
event source whose *scene half* costs the fewest human steps.

A **manual step** is an authoring action *inside the editor* that a tool cannot
perform, and that must happen before the graph can fire (the definition
:mod:`tools.gameplan.modules.interaction` records per ``InteractionKind`` and
``DEMO-GAP.md`` §三 tabulates with the missing primitive's ``file:line``).  It is
not "playing" (pressing 试玩 / walking into a plot) — that is identical for every
design and is excluded, exactly as in :mod:`tools.gameplan.demo.minimal_playable`.

The event sources, each with its exact manual step and citation
--------------------------------------------------------------

**Chosen — ``71 实体创建时`` (entity created).  Event-source manual steps: 0.**

``71`` fires when the entity the graph is bound to is created.  The tool creates
that entity *by coordinate* — ``entity.create`` takes ``position``/``rotation``/
``scale`` up front (``tools/game-executor/scene_cli.py:181-192``; doctrine
``CLAUDE.md`` §六(c) "建时能定"), and placing a map tile is explicitly **not** a
human step (``docs/gameplan/DEMO-GAP.md:101`` — "地图摆放本身不是人工步……
``entity.create`` 自带坐标，地块实体已由工具建出").  Binding the graph to it is a
bridge step, not an editor step.  So ``71`` needs **no** editor authoring: it is
the unique *buildable* event source whose scene half is empty (see
:func:`buildable_zero_step_sources`).

**Alternative — ``92 进入碰撞触发器时`` (proximity enter).  Manual steps: 2.**

This is the demo's real harvest trigger (``farming_full.py`` ``plot_enter``).

1. Add a ``碰撞触发器`` general component to the plot entity
   (``docs/gameplan/MANUAL-STEPS.md:35`` — "``组件编辑页签`` → 底部「添加通用组件」→
   选「碰撞触发器」"; the demo's own plot entity is ``1077936129``).
2. Configure it ("详细编辑": trigger shape, 生效目标) and note the moving party
   must carry a ``碰撞触发源`` component
   (``docs/research/game-b-systems-20261009/M1-interaction.md:37,56``;
   ``docs/gameplan/DEMO-GAP.md:96``).

Neither has a tool primitive: ``AddComponent`` / ``CreateComponent`` /
``AttachComponent`` / ``InsertComponent`` are 0 hits across the whole reverse-
engineering corpus (``CLAUDE.md`` §六(a) — the component boundary is
"readable, deletable, **not addable**").  **2 steps, chosen 71 wins by 2.**

Rejected event sources (and why)
--------------------------------

* ``83 定时器触发时`` (timer).  Scene steps **0** — a timer is created by the node
  graph, not attached in the editor (``docs/official-docs/chapters/
  mhufb90zbnts.json:133`` — "定时器只能通过节点图创建和使用，禁止在
  ``entity.properties`` 的可挂组件列表里找它").  But it is **not buildable**:
  starting it needs ``79 启动定时器``, whose ``定时器序列`` input is a *float list*
  (``docs/official-docs/chapters/mhw66orrrfkm.json:51-52``), and this project's
  constant writer has no list slot — ``builder._tagged`` handles only
  int/uint/enum/float/bool/string (``tools/gameplan/builder.py:60-81``) and
  ``plan._SLOTS`` has no list (``tools/gameplan/plan.py:341``).  Rejected:
  cheaper on paper, cannot be expressed today.  (Honest #6 candidate for the day
  a list constant exists.)
* ``315 全局计时器触发时`` (global timer).  **1 step** — the node may only
  reference a timer pre-defined in the global-timer management tool
  (``docs/official-docs/chapters/mhawd6rl5kpy.json:16``), i.e. editor authoring
  with no tool.  Rejected: strictly costlier than the chosen ``71``.
* ``733 背包内道具被使用时`` (item used).  **1 step** — the crop item template must
  be created *and* its ``允许使用`` ticked (``docs/gameplan/MANUAL-STEPS.md:21-23``;
  ``docs/research/game-b-systems-20261009/M2M3-currency-item.md:57,69``;
  ``docs/gameplan/DEMO-GAP.md:94``).  Rejected: it re-introduces an editor asset
  as a *precondition of the event itself*; ``71`` needs none.
* ``316 界面控件组触发时`` (UI control group).  **2 steps** — build the control
  group, then assign its layout to the player's 职业
  (``docs/research/game-b-systems-20261009/M1-interaction.md:21,22,31``).
  Rejected: costlier.
* ``826 悬浮交互页操作触发时`` (floating page).  **2 steps** — configure the page,
  then have a node 唤起 it (``M1-interaction.md:29,49``).  Rejected: costlier.

The residual, stated honestly
-----------------------------

Driving the event from ``71`` removes the *event* steps, but it does **not** remove
the one asset every farm graph needs regardless of event source: the graph writes
``crop_id`` (contract type 20 ``配置ID``) into ``686``, and a config id is only a
reference — the crop item template must exist or the id dangles.

* ``docs/gameplan/MANUAL-STEPS.md:21-23`` (§2, the crop item template build);
* ``docs/gameplan/DEMO-GAP.md:94`` (no bridge op / CLI / MCP writer for it);
* ``docs/research/game-b-systems-20261009/M2M3-currency-item.md:130,181``.

That is :data:`RESIDUAL_TEMPLATE_STEPS`, **1 manual step**, and it is a property of
*this graph* (it names one config id), not of the event source — so it appears in
:func:`total_manual_step_count` for the chosen and the alternative alike and never
changes the comparison.  **Grand total for this variant: 1** (0 event + 1 asset).
For contrast the full demo's 收/合成/卖 loop needs 货币+作物+食物+商店 templates,
two collider components and a shop component (``DEMO-GAP.md`` §三) — this variant's
whole point is that number, minimised.

Honesty about the claim (the task's own escape hatch)
-----------------------------------------------------

* The **strict** claim my tests assert is a *number*: for the same two-node graph,
  ``71`` (0 event steps) is strictly cheaper than ``92`` (2) and than ``733`` (1) —
  and ``71`` is the unique *buildable* zero-step source.  That part is exact.
* The **choice to stay inside the farming/interaction shape** — a graph that grants
  a crop when a trigger fires — is a **judgement call**.  A ``71 实体创建时 → 1
  打印字符串`` graph also needs zero templates, but it produces nothing a player can
  hold and is not a farm; the crop leg is kept so the variant is recognisably the
  demo's 收 leg and not a degenerate log line.  I claim the step counts; I do not
  claim "no smaller graph of any shape exists".
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import ON_CREATE, Graph, Handle
from ..plan import GraphPlan
from ..modules import interaction as m1
from ..modules import item as m3

DEFAULT_NAME = "MW_API_FARM_MINIMAL"
"""The chosen (zero-event-step) graph's name; matches ``plan.GRAPH_NAME_RE``."""

ALT_NAME = "MW_API_FARM_MINIMAL_ALT"
"""The same graph driven by the proximity event (the comparison arm)."""

#: Event-source keys of :data:`EVENT_SOURCES`.
EVENT_ON_CREATE = "on-create"
EVENT_TIMER = "timer"
EVENT_GLOBAL_TIMER = "global-timer"
EVENT_ITEM_USED = "item-used"
EVENT_PROXIMITY = "proximity"
EVENT_UI_BUTTON = "ui-button"
EVENT_FLOATING_PAGE = "floating-page"


@dataclass(frozen=True)
class ManualStep:
    """One editor authoring action, with a ``file:line`` citation so it is checkable.

    ``citation`` is a ``file:line`` reference (or a comma-separated list of them)
    into this repository — an assertion without one is not evidence.
    """

    action: str
    citation: str


#: The one editor asset this graph needs no matter which event drives it: the crop
#: item template whose ``配置ID`` the graph writes into ``686``.  A per-graph cost,
#: not a per-event cost (module docstring, "The residual").
RESIDUAL_TEMPLATE_STEPS: tuple[ManualStep, ...] = (
    ManualStep(
        "建作物道具模板（类型 8 普通道具、装备道具），把编辑器分配的「配置ID」"
        "抄回给 --crop-id；本工程无模板写入原语，图里的配置ID 在拿到真值前是悬空引用",
        "docs/gameplan/MANUAL-STEPS.md:21-23;"
        " docs/gameplan/DEMO-GAP.md:94;"
        " docs/research/game-b-systems-20261009/M2M3-currency-item.md:130,181",
    ),
)


@dataclass(frozen=True)
class EventSource:
    """An event node considered for the trigger, with its cost and buildability.

    ``manual_steps`` is the *scene half*: editor authoring that must happen before
    the event can fire (may be empty).  ``buildable`` is whether a graph using it
    can be expressed with this project's constant writer today — ``83`` has an
    empty scene half yet is **not** buildable, which is exactly why a bare step
    count is not enough to rank the sources (see :func:`buildable_zero_step_sources`).
    """

    key: str
    label: str
    definition_id: int
    manual_steps: tuple[ManualStep, ...]
    buildable: bool
    note: str = ""


#: Every event source examined, so a caller cannot read "the cheapest of two" as
#: "the cheapest of all" (the same completeness rule as the interaction module).
EVENT_SOURCES: dict[str, EventSource] = {
    EVENT_ON_CREATE: EventSource(
        EVENT_ON_CREATE,
        "71 实体创建时",
        71,
        (),  # 0 — the plot entity is created by the tool, not by hand
        True,
        "the graph is bound to an entity the tool builds by coordinate; nothing to "
        "author (scene_cli.py:181-192; DEMO-GAP.md:101).",
    ),
    EVENT_TIMER: EventSource(
        EVENT_TIMER,
        "83 定时器触发时",
        83,
        (),  # 0 — a timer is graph-only, not an editor component
        False,  # ... but starting it needs an unwritable float-list constant
        "rejected: 79 启动定时器 needs a 定时器序列 float list "
        "(mhw66orrrfkm.json:51-52), and the constant writer has no list slot "
        "(builder.py:60-81; plan.py:341). 0 steps on paper, unbuildable today.",
    ),
    EVENT_GLOBAL_TIMER: EventSource(
        EVENT_GLOBAL_TIMER,
        "315 全局计时器触发时",
        315,
        (
            ManualStep(
                "在全局计时器管理工具里预先定义该全局计时器（节点只能引用预定义的）",
                "docs/official-docs/chapters/mhawd6rl5kpy.json:16",
            ),
        ),
        True,
        "rejected: 1 step, strictly costlier than 71.",
    ),
    EVENT_ITEM_USED: EventSource(
        EVENT_ITEM_USED,
        "733 背包内道具被使用时",
        733,
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
    EVENT_PROXIMITY: EventSource(
        EVENT_PROXIMITY,
        "92 进入碰撞触发器时",
        92,
        (
            ManualStep(
                "在目标实体上「组件编辑页签 → 添加通用组件 → 碰撞触发器」",
                "docs/gameplan/MANUAL-STEPS.md:35;"
                " docs/gameplan/DEMO-GAP.md:96",
            ),
            ManualStep(
                "在同一组件上「详细编辑」配好触发区形状与生效目标（移动方还须"
                "携带「碰撞触发源」组件）",
                "docs/research/game-b-systems-20261009/M1-interaction.md:37,56",
            ),
        ),
        True,
        "the demo's real harvest trigger; 2 steps, no add-component primitive exists.",
    ),
    EVENT_UI_BUTTON: EventSource(
        EVENT_UI_BUTTON,
        "316 界面控件组触发时",
        316,
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
    EVENT_FLOATING_PAGE: EventSource(
        EVENT_FLOATING_PAGE,
        "826 悬浮交互页操作触发时",
        826,
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


def event_source(key: str) -> EventSource:
    """The :class:`EventSource` for ``key``; raises ``KeyError`` if unknown."""
    try:
        return EVENT_SOURCES[key]
    except KeyError:
        raise KeyError(
            f"unknown event source {key!r}; known: {sorted(EVENT_SOURCES)}"
        ) from None


def manual_steps(key: str) -> tuple[ManualStep, ...]:
    """The event-source-specific editor steps ``key``'s scene half requires."""
    return event_source(key).manual_steps


def manual_step_count(key: str) -> int:
    """How many editor steps ``key`` needs before it can fire (scene half only)."""
    return len(event_source(key).manual_steps)


def residual_template_step_count() -> int:
    """Editor steps this graph needs regardless of event source (the crop template)."""
    return len(RESIDUAL_TEMPLATE_STEPS)


def total_manual_step_count(key: str) -> int:
    """Event-source steps + the per-graph residual — the honest grand total."""
    return manual_step_count(key) + residual_template_step_count()


def is_buildable(key: str) -> bool:
    """Whether a graph using ``key`` can be expressed with today's tooling."""
    return event_source(key).buildable


def rejection(key: str) -> str:
    """Why ``key`` was not chosen (empty string for the chosen source)."""
    source = event_source(key)
    return "" if key == EVENT_ON_CREATE else source.note


def buildable_zero_step_sources() -> tuple[str, ...]:
    """The event sources that are both buildable and need 0 editor steps.

    The chosen ``71`` is (today) the only member: ``83`` also needs 0 editor steps
    but is not buildable (its timer start needs an unwritable list constant).
    """
    return tuple(
        key
        for key, source in EVENT_SOURCES.items()
        if source.buildable and not source.manual_steps
    )


@dataclass(frozen=True)
class MinimalFarmConfig:
    """Everything the graph needs that lives in the editor, not in our tools."""

    crop_id: int                # 作物道具配置ID (type 20)
    item_slot: str = "int"      # the `--slot` used to write a configID (see paramtypes)
    harvest_gain: int = 1       # crops granted when the trigger fires


def _grant_on(g: Graph, event: Handle, *, role: str, config: MinimalFarmConfig,
              alias: str) -> Handle:
    """Wire ``event.<role> -> 686 增加背包道具数量 (+harvest_gain)`` and return it."""
    return m3.grant(
        g, event, holder=(event, role), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias=alias,
    )


def build(config: MinimalFarmConfig, name: str = DEFAULT_NAME) -> Graph:
    """The minimal farm: ``71 实体创建时`` → give the plot's creator ``harvest_gain``.

    Returns an *unvalidated* :class:`Graph`.  The event fires when the plot entity
    — which the tool creates by coordinate — is created at level load; no editor
    authoring is needed for the event itself (the crop template is the residual).
    """
    g = Graph(name)
    created = g.place(ON_CREATE, "plot_created")   # 71 实体创建时
    assert created.ntype is ON_CREATE
    _grant_on(g, created, role="entity", config=config, alias="harvest")
    return g


def build_alternative(config: MinimalFarmConfig, name: str = ALT_NAME) -> Graph:
    """The *same two-node graph* driven by the demo's real event: ``92`` proximity.

    Identical in size and wiring to :func:`build` — the only difference is that its
    event source costs **two** editor steps instead of zero (:data:`EVENT_SOURCES`).
    """
    g = Graph(name)
    plot = m1.proximity_enter(g, "plot_enter")     # 92 进入碰撞触发器时
    _grant_on(g, plot, role="entrant", config=config, alias="harvest")
    return g


def plan_of(config: MinimalFarmConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the chosen graph, returning the :class:`GraphPlan`.

    Named ``plan_of`` — **not** ``build_plan`` — on purpose, for the same reason as
    :mod:`tools.gameplan.demo.minimal_playable`: the demo-golden guard
    (``tests/test_demo_golden.py``) discovers *every* module under ``demo/`` that
    exposes ``build_plan`` and demands a frozen shape for it, and that registry is
    outside this task's file ownership.  This is a comparison study, not a pinned
    demo graph; its shape guard is the asserted node list in
    ``tests/test_farming_minimal.py``.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


def alternative_plan_of(config: MinimalFarmConfig, name: str = ALT_NAME) -> GraphPlan:
    """Build and validate the proximity arm, returning its :class:`GraphPlan`."""
    graph = build_alternative(config, name=name)
    graph.validate()
    return graph.plan
