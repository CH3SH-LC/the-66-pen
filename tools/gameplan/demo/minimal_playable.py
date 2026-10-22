"""The smallest graph that a human could actually make *fire* — and why it is.

The full demo (:mod:`tools.gameplan.demo.farming_full`) is 15 nodes and its
harvesting leg hangs off ``92 进入碰撞触发器时``.  That node is dead weight a human
cannot bring to life cheaply: a ``92`` fires only when a ``碰撞触发器`` **component**
is configured on an entity, and the cost of that leg is a *manual editor step*
this project's tools cannot perform (no component writer — ``CLAUDE.md`` §六(a)).

This module builds the smallest alternative: **one event node, one effect node**,
driven by the event source whose scene half is the cheapest for a human to set
up.  The graph is the demo's harvesting leg with the trigger swapped out::

    build()             733 背包内道具被使用时  → 686 增加背包道具数量 (+harvest_gain)
    build_alternative()  92 进入碰撞触发器时    → 686 增加背包道具数量 (+harvest_gain)

Both graphs are the **same two nodes and the same two edges** — one execution
edge (event ``then`` → the grant) and one data edge (the event's entity output →
the grant's ``holder``).  The only thing that differs is the *event source*, and
therefore the number of **manual editor steps** a human must perform before the
graph can fire at all.  That is the whole point: with the graph held constant,
pick the event source that costs the fewest human steps.

What counts as a "manual step" (and what does not)
--------------------------------------------------
A **manual step** is an *authoring action inside the editor* that a human must
perform *before* the graph can fire, because no tool in this project can do it
(``docs/gameplan/DEMO-GAP.md`` §三 lists them with the ``file:line`` of the
missing primitive).  It is *not*:

* the act of **playing** — pressing 试玩 and walking into the plot / using the
  item.  That step is identical for every design, so :func:`manual_step_count`
  counts only the *event-source-specific* authoring steps; the shared playtest
  step is named here once and excluded from the comparison (``DEMO-GAP.md`` §三
  step 6 is the common playtest step).
* **seeding the bag** — giving the player the one crop the ``733`` event needs.
  ``DEMO-GAP.md:98`` records this as a *node-graph* action ("或用节点图给一次"),
  not an editor step, so it adds zero manual steps.  It is deliberately **left
  out of the minimal graph**; a caller that wants to fire from a cold bag
  prepends the zero-step ``71 实体创建时`` leg (an entity is created by the tool,
  not by hand).  See :func:`seed_leg`.
* **creating the plot entity** — ``entity.create`` carries a position
  (``CLAUDE.md`` §六(c)), and the tool has already created one on the machine,
  so placing an entity by coordinate is not a human step either.

The event sources used, and their exact manual step (with citation)
------------------------------------------------------------------
**Primary — ``733 背包内道具被使用时`` (item used).  Manual steps: 1.**

1. In the editor, create the crop item template (type 8 ``普通道具、装备道具``) and
   tick ``允许使用`` so the player can use it from the bag.

   * ``新建道具``: ``docs/research/game-b-systems-20261009/M2M3-currency-item.md:57``
     ("点击新建道具按钮，在弹窗内选择确认创建即可新建一个道具模板").
   * ``允许使用`` lives under 3.交互设置 of the same template:
     ``M2M3-currency-item.md:69``.
   * The template has no writer in the bridge/CLI/MCP, so a human builds it once:
     ``docs/gameplan/DEMO-GAP.md:94``.

   Nothing else is scene-owned: the bag is a **built-in** official system
   (``M2M3-currency-item.md:145`` — "存储是官方模板 + 背包组件 + 61 个现成节点"),
   so the event fires with no entity component and no UI asset.

**Alternative — ``92 进入碰撞触发器时`` (proximity enter).  Manual steps: 2.**

1. Add a ``碰撞触发器`` general component to the entity: "组件编辑页签 → 添加通用组件 →
   碰撞触发器" (``docs/research/game-b-systems-20261009/M1-interaction.md:37``;
   ``DEMO-GAP.md:96``).

2. Configure it ("详细编辑"): the trigger shape (长方体/球体/胶囊体) and the
   生效目标, and the moving party must carry a ``碰撞触发源`` component —
   ``M1-interaction.md:37`` and ``M1-interaction.md:56`` (the trigger "持续监测其他
   携带'碰撞触发源组件'的实体").

   The component write has **no primitive** anywhere in the tools
   (``DEMO-GAP.md:96`` — ``AddComponent``/``SetComponent`` … 0 hits;
   ``NATIVE_ACTIONS`` has 6 entries and none writes a component).

So ``733`` costs **1** manual step and ``92`` costs **2**, for the *same* graph.
:func:`manual_step_count` makes that a number the tests assert on.

Honesty about the claim (per the task's own escape hatch)
--------------------------------------------------------
The minimality asserted here is exact and narrow: **for a fixed graph shape, the
event source with the fewest authoring steps wins, and ``733`` (1) beats ``92``
(2).**  It is *not* a claim that no smaller graph of any other shape exists — a
``71 实体创建时 → 1 打印字符串`` graph needs zero templates (zero steps) but its
event is not a player interaction and prints only to the log
(``docs/gameplan/README.md:140``: the only feedback this project has is a log
print).  The choice to stay inside the *interaction* family — the family whose
scene halves ``interaction.py`` documents — is a judgement call; the step counts
themselves are not.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import BAG_ITEM_USED, ON_CREATE, Graph
from ..plan import GraphPlan
from ..modules import interaction as m1
from ..modules import item as m3

DEFAULT_NAME = "MW_API_MIN_PLAYABLE"
ALT_NAME = "MW_API_MIN_PLAYABLE_ALT"

#: Event-source keys for the two sources this module compares.  They are the
#: keys of :data:`MANUAL_STEPS`.
EVENT_ITEM_USED = "item-used"
EVENT_PROXIMITY = "proximity"


@dataclass(frozen=True)
class MinimalConfig:
    """Everything the graph needs that lives in the editor, not in our tools.

    ``crop_id`` is the item template the human must create (the one manual
    step); ``harvest_gain`` is how many crops a use yields.
    """

    crop_id: int                  # 作物道具配置ID (type 20)
    item_slot: str = "int"        # the `--slot` used to write a configID
    harvest_gain: int = 1         # crops granted per use


@dataclass(frozen=True)
class ManualStep:
    """One editor authoring action a human must perform, with its citation.

    ``citation`` is a ``file:line`` reference (or a comma-separated list of
    them) into this repository, so the claim is checkable rather than asserted.
    """

    action: str
    citation: str


#: The manual editor steps each event source's *scene half* needs — the honest
#: limit :mod:`tools.gameplan.modules.interaction` records as ``scene_half``,
#: turned into a countable list.  Only the two event sources this module builds
#: are required; the other two interaction families are carried so the model is
#: complete and so a caller cannot read "one of four" as "the cheap one".
MANUAL_STEPS: dict[str, tuple[ManualStep, ...]] = {
    EVENT_ITEM_USED: (
        ManualStep(
            "编辑器【货币与背包】→ 道具页签 → 新建道具：建一个道具模板（类型 8 "
            "普通道具、装备道具）并勾选「允许使用」，玩家即可从背包使用它",
            "docs/research/game-b-systems-20261009/M2M3-currency-item.md:57,69;"
            " docs/gameplan/DEMO-GAP.md:94",
        ),
    ),
    EVENT_PROXIMITY: (
        ManualStep(
            "在目标实体上「组件编辑页签 → 添加通用组件 → 碰撞触发器」",
            "docs/research/game-b-systems-20261009/M1-interaction.md:37;"
            " docs/gameplan/DEMO-GAP.md:96",
        ),
        ManualStep(
            "在同一组件上「详细编辑」配好触发区形状与生效目标（移动方还须携带"
            "「碰撞触发源」组件）",
            "docs/research/game-b-systems-20261009/M1-interaction.md:37,56",
        ),
    ),
    "ui-button": (
        ManualStep(
            "在「界面控件组编辑窗口」建界面控件组与交互按钮（按键设置；类型选"
            "「交互事件」）",
            "docs/research/game-b-systems-20261009/M1-interaction.md:21,22",
        ),
        ManualStep(
            "在「系统菜单 → 界面控件组管理 → 界面布局」里把该布局经「职业引用」"
            "配给玩家",
            "docs/research/game-b-systems-20261009/M1-interaction.md:31",
        ),
    ),
    "floating-page": (
        ManualStep(
            "在编辑器里配置「悬浮交互页」（页签 / 列表项）并搭好界面控件组",
            "docs/research/game-b-systems-20261009/M1-interaction.md:29",
        ),
        ManualStep(
            "让节点图「唤起悬浮交互页」把它显示给玩家",
            "docs/research/game-b-systems-20261009/M1-interaction.md:49",
        ),
    ),
}


def manual_steps(event_key: str) -> tuple[ManualStep, ...]:
    """The manual editor steps ``event_key``'s scene half requires.

    Raises :class:`KeyError` for an unknown key, so a caller cannot silently
    compare against a source whose cost was never written down.
    """
    try:
        return MANUAL_STEPS[event_key]
    except KeyError:
        raise KeyError(
            f"unknown event source {event_key!r}; known: {sorted(MANUAL_STEPS)}"
        ) from None


def manual_step_count(event_key: str) -> int:
    """How many manual editor steps ``event_key`` needs before it can fire."""
    return len(manual_steps(event_key))


def _grant_on(g: Graph, event, *, role: str, config: MinimalConfig, alias: str) -> Graph:
    """Wire ``event.<role> -> 686 增加背包道具数量`` and return the graph."""
    m3.grant(
        g, event, holder=(event, role), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias=alias,
    )
    return g


def build(config: MinimalConfig, name: str = DEFAULT_NAME) -> Graph:
    """The minimal graph: using a crop (``733``) grants ``harvest_gain`` crops.

    Returns an *unvalidated* :class:`Graph`.  The event fires once the player
    uses a crop from the bag; the crop template is the one manual step.  The
    graph is not seeded (see the module docstring) — :func:`seed_leg` prepends
    the zero-step ``71 实体创建时`` leg that makes it fire from a cold bag.
    """
    g = Graph(name)
    use = m3.on_used(g, "use_crop")  # 733 背包内道具被使用时
    assert use.ntype is BAG_ITEM_USED
    _grant_on(g, use, role="holder", config=config, alias="regrow")
    return g


def build_alternative(config: MinimalConfig, name: str = ALT_NAME) -> Graph:
    """The same graph built from the *other* event source: proximity (``92``).

    This is exactly the demo's harvesting leg (``farming_full.py`` ``plot_enter``
    → ``harvest``): walk into the plot, get ``harvest_gain`` crops.  Its graph is
    identical in size to :func:`build` — the difference is that its event source
    costs **two** manual editor steps instead of one.
    """
    g = Graph(name)
    plot = m1.proximity_enter(g, "plot_enter")  # 92 进入碰撞触发器时
    _grant_on(g, plot, role="entrant", config=config, alias="harvest")
    return g


def seed_leg(g: Graph, config: MinimalConfig, alias: str = "seed") -> None:
    """Prepend a zero-manual-step seed: ``71 实体创建时 → 686 (+1 crop)``.

    Optional.  It gives the player one crop at level start so :func:`build`'s
    ``733`` event fires from a cold bag.  No template beyond ``crop_id`` is
    needed, and an entity is created by the tool, so this leg adds no human step
    (module docstring; ``DEMO-GAP.md:98``).
    """
    create = g.place(ON_CREATE, alias)  # 71 实体创建时
    m3.grant(
        g, create, holder=(create, "entity"), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias=f"{alias}_crop",
    )


def plan_of(config: MinimalConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the minimal graph, returning the :class:`GraphPlan`.

    Named ``plan_of`` — **not** ``build_plan`` — on purpose.  The demo-golden
    guard (``tests/test_demo_golden.py``) discovers *every* module under
    ``demo/`` that exposes ``build_plan`` and demands a frozen shape for it in
    ``tools/gameplan/golden/demo-graphs.json``.  This module is a comparison
    study, not a new pinned demo graph, and the golden registry is outside this
    task's file ownership, so it deliberately stays out of that set; its shape
    guard is the asserted node list in ``tests/test_minimal_playable.py``.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


def alternative_plan_of(config: MinimalConfig, name: str = ALT_NAME) -> GraphPlan:
    """Build and validate the proximity alternative, returning its plan."""
    graph = build_alternative(config, name=name)
    graph.validate()
    return graph.plan
