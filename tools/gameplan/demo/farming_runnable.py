"""The demo rebuilt so it can actually **run**: entry ``71 实体创建时``, no blocked primitive.

The problem this module solves
------------------------------

The shipped demo (``demo/farming_full.py``, the 15-node ``MW_API_FARM_DEMO``) enters
through ``92 进入碰撞触发器时``.  A ``92`` fires only from a ``碰撞触发器`` **component**
configured on an entity — and "add a component" is a primitive this project has
**proven absent** (``CLAUDE.md`` §六(a): ``AddComponent`` / ``CreateComponent`` /
``AttachComponent`` / ``InsertComponent`` are 0 hits across the decompiled corpus,
both string tables and both command tables).  So the shipped demo can never fire:
it is a graph nobody has seen run, and the *only* thing standing in the way is the
choice of **entry node**.

``71 实体创建时`` (on-create) has no such requirement: it fires when the entity the
graph is **bound to** is created, and that entity is created by the tool *by
coordinate* (``scene_cli.py`` ``create`` / ``create-batch``; ``CLAUDE.md`` §六(c)
"建时能定"; ``docs/gameplan/DEMO-GAP.md:101`` — "地图摆放本身不是人工步").  Swapping
``92`` for ``71`` therefore removes the one *event-side* blocker, and everything
downstream can be built from primitives that already exist.

The graph
---------

::

    on_create  71 实体创建时                (entry — the bind target is created)
      └─ then ─▶ grow     685 增加背包最大容量      +grow_amount        (M4)
                   └─ then ─▶ harvest 686 增加背包道具数量  +harvest_gain  (M3)
                       └─ then ─▶ bonus   688 增加背包货币数量  +coin_bonus    (M2)
                           └─ then ─▶ gate_item 2 双分支  ◀── 233 数值大于等于 ◀── 690 读作物
                                        ├ 是 ─▶ gate_cap  2 双分支 ◀── 230 数值小于 ◀── 689 读容量
                                        │            ├ 是 ─▶ 1 打印 "背包容量偏低"
                                        │            └ 否 ─▶ 1 打印 "收获完成"
                                        └ 否 ─▶ gate_money 2 双分支 ◀── 233 数值大于等于 ◀── 691 读货币
                                                     ├ 是 ─▶ 1 打印 "作物不足但货币充足"
                                                     └ 否 ─▶ 1 打印 "作物不足"

17 nodes / 22 edges / 14 constants, kind 20000.  Every **execution** edge leaves a
node that has an execution *input*; the single entry ``71`` is the graph's only
event and its only node with no execution input (asserted, not assumed — see
:func:`entry_definition_ids`).

Why every input is satisfiable (the honesty table the design rests on)
----------------------------------------------------------------------

Each node's inputs are one of three kinds, and nothing else:

* **a literal** — an int / bool / string constant written by :mod:`graphplan.builder`
  (``_tagged`` handles ``int/uint/enum/float/bool/string``);
* **a node we control** — a data output of a node already in this graph;
* **an editor asset** — a template or component this project cannot create.  A node
  that *needs* one of these for its **input** is **excluded** (:data:`BLOCKED_DEFINITION_IDS`).

+-------------+------------------------------------------+----------------------------------+
| node        | inputs                                   | why satisfiable                  |
+=============+==========================================+==================================+
| ``71``      | none (event; only data *outputs*)        | literally has no input           |
| ``685``     | holder ← ``71.entity``; delta = literal  | controlled node + literal        |
| ``686``     | holder ← ``71.entity``; item/delta = lit | controlled node + literal        |
| ``688``     | holder ← ``71.entity``; curr/delta = lit | controlled node + literal        |
| ``690/691`` | holder ← ``71.entity``; item/curr = lit  | controlled node + literal        |
| ``689``     | holder ← ``71.entity``                   | controlled node                  |
| ``233/230`` | left ← a read; right = literal           | controlled node + literal        |
| ``2``       | condition ← a compare's bool             | controlled node                  |
| ``1``       | text = literal                           | literal                          |
+-------------+------------------------------------------+----------------------------------+

The key finding (the question this module was built to answer)
--------------------------------------------------------------

**Do ``686``/``688``/``690``/``691`` need a template *instance* to exist, or do they
take a *configuration id* that is just a number?**  *They take a plain number.*
``data/node-contracts`` types their ``道具配置ID`` / ``货币配置ID`` pins as
``serverParamType`` **20** (``config-id``) — a scalar written on the wire as an
integer constant (``modules/item.py`` ``node.const("item", int(item_id), item_slot)``;
``builder._tagged`` encodes it as ``{"int": …}``).  No pin anywhere in this graph
takes a live template **object** or a component.  So the node is placeable, its
input is *satisfiable with a literal*, and the graph executes; what a missing
template costs is the **effect** (the grant lands in a bag that does not know that
id) — the config id is a *dangling reference*, exactly as ``DEMO-GAP.md`` §二
describes ("没实例 ⇒ 图里的 货币配置ID 是悬空引用").  A dangling reference is not an
unsatisfiable input, and a graph that executes with inert effects **is still a
running graph**.  That is the whole difference from the shipped demo, whose entry
node's *scene half* (the trigger entity) does not exist at all.

Why M1, M5 and M6 are absent — and it is not an oversight
----------------------------------------------------------

* **M1 交互点** — all four entry points (``92``/``91``/``316``/``826``) record a
  non-empty ``scene_half`` in :mod:`graphplan.modules.interaction`; every one needs a
  component or a UI the bridge cannot author.  **M1 is 0/% runnable today.**
* **M5 商店** — every node in the family (``702``/``703``/``701``/``705``/``704``/
  ``706``/``709``/``714``/``715``) acts on a **shop component** that must sit on an
  entity (``shop.py`` module docstring; ``DEMO-GAP.md`` §三 row 4).  Without it there
  is no shop to open, sell into or query.  **M5 is 0/% runnable today.**
* **M6 地块/地形** — has **no node half at all** (``nodes.py`` declares no terrain
  role; ``README.md`` §五 M6a row).  Placement is a *scene* action, not a node graph.

So the runnable demo exercises **M2 + M3 + M4** (plus the shared F2 flow and F5 print
families) — three of the six module directions — and says so.

The one assumption that is NOT proven here (stated, not hidden)
---------------------------------------------------------------

``71`` is claimed to fire when the graph's bind target is created.  That claim is
inherited from :mod:`tools.gameplan.demo.farming_minimal` (which shares it) and is
backed by the node's contract (``71`` has an execution *output* and no execution
input — an event) and by the tool creating the bind target by coordinate.  It has
**not been observed on a real machine** in this wave: this module builds and
validates the plan offline only.  Everything below the entry (the exec chain, the
two comparisons, the three prints) is deterministic *given* that ``71`` fires.

Named ``plan_of`` — **not** ``build_plan`` — on purpose: the demo-golden guard
(``tests/test_demo_golden.py``) discovers every ``demo/*.py`` exposing ``build_plan``
and demands a frozen snapshot in ``golden/demo-graphs.json``, a registry outside this
task's file ownership.  Its shape guard is ``tests/test_demo_runnable.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import (
    ADD_BAG_CURRENCY,
    ADD_BAG_CAPACITY,
    ADD_BAG_ITEM,
    BAG_CURRENCY_CHANGED,
    BAG_ITEM_ADDED,
    BAG_ITEM_CHANGED,
    BAG_ITEM_LOST,
    BAG_ITEM_USED,
    BRANCH,
    CLOSE_SHOP,
    GET_ALL_BAG_CURRENCIES,
    GET_ALL_BAG_ITEMS,
    GET_BAG_CAPACITY,
    GET_BAG_CURRENCY,
    GET_BAG_ITEM,
    ON_CREATE,
    OPEN_SHOP,
    PRINT,
    SHOP_BOUGHT_ITEM,
    SHOP_SOLD_BAG_ITEM,
    Graph,
)
from ..plan import GraphPlan
from ..modules import currency as m2
from ..modules import interaction as m1
from ..modules import inventory as m4
from ..modules import item as m3
from ..modules import shop as m5
from . import farming_minimal

DEFAULT_NAME = "MW_API_DEMO_RUN"
"""The graph name; matches ``plan.GRAPH_NAME_RE`` (``MW_API_`` + ``[A-Za-z0-9_]{1,48}``)."""

#: The unconditional line printed the instant the entry fires — the "the graph ran at
#: all" probe (WAVE-29AA).  Chinese, ambiguity-free, and names this graph (4th run) so
#: one captured line is self-identifying.  Maps 1:1 to the graph name MW_API_DEMO_RUN4.
ENTRY_PROBE_TEXT = "四号图入口已触发"

#: The line printed when the bag's capacity is below ``capacity_threshold`` (M4 gate).
LOW_CAPACITY_TEXT = "背包容量偏低"

#: The line printed when capacity is fine (the M4 gate's false branch).
HARVEST_OK_TEXT = "收获完成"

#: The line printed when the crop count is short of ``recipe_cost`` but the wallet is
#: at/above ``coin_threshold`` (the M2 gate's true branch).
SHORT_ITEM_RICH_TEXT = "作物不足但货币充足"

#: The line printed when both the crop count and the wallet are short.
SHORT_ALL_TEXT = "作物不足"

#: ``compare`` selector for the M4 capacity gate — ``lt`` ⇒ ``容量 < 阈值``.
CAPACITY_COMPARE = "lt"


# ---------------------------------------------------------------------------
# The blocked set — DERIVED, never typed.
#
# A definitionId is **blocked** iff it cannot be placed with every input satisfied
# without an editor-authored asset this project cannot write (CLAUDE.md §六).  The
# three clauses below each read a *different* table already in the tree, so the set
# moves when the doctrine moves and cannot be a hand-typed guess:
# ---------------------------------------------------------------------------

def blocked_definition_ids() -> frozenset[int]:
    """DefinitionIds whose *inputs* need a component/template we cannot author.

    Three derived clauses (no literal id is typed anywhere in this function):

    1. **Interaction entry points** — every :class:`interaction.InteractionKind`
       whose recorded ``scene_half`` is non-empty.  A trigger entity that must carry
       a ``碰撞触发器`` component cannot be produced (no add-component primitive), so
       the ``92``/``91``/``316``/``826`` events and their entity outputs are unusable.
    2. **Asset-gated events** — every :class:`farming_minimal.EventSource` whose
       ``manual_steps`` is non-empty, i.e. whose firing needs a hand-built template,
       timer or component before it can ever fire (``315``/``733`` plus the four above).
    3. **The whole shop family** — the ids come from the shop module's own node
       tables (``SHOP_TABLE_NODE_TYPES`` / ``SHOP_QUERY_NODE_TYPES``) plus the four
       shop nodes in :mod:`graphplan.nodes`.  Every one of them acts on a ``商店组件``
       that must be attached to an entity (``shop.py`` docstring; ``DEMO-GAP.md`` §三
       row 4), which is the same missing add-component primitive.

    Deliberately **not** blocked: ``686``/``688``/``690``/``691`` — their item /
    currency pins are ``config-id`` (type 20) *scalars*, satisfiable by a literal;
    the missing template makes the id dangle, it does not make the input unsatisfiable
    (module docstring, "The key finding").
    """
    ids: set[int] = set()
    ids |= {
        kind.event_definition_id
        for kind in m1.KINDS.values()
        if kind.scene_half
    }
    ids |= {
        source.definition_id
        for source in farming_minimal.EVENT_SOURCES.values()
        if source.manual_steps
    }
    ids |= {
        t.definition_id
        for t in (
            OPEN_SHOP,
            CLOSE_SHOP,
            SHOP_SOLD_BAG_ITEM,
            SHOP_BOUGHT_ITEM,
            *m5.SHOP_TABLE_NODE_TYPES,
            *m5.SHOP_QUERY_NODE_TYPES,
        )
    }
    return frozenset(ids)


#: The frozen derivation, so a caller (and the test) reads one object.
BLOCKED_DEFINITION_IDS: frozenset[int] = blocked_definition_ids()


def definition_ids(plan: GraphPlan) -> frozenset[int]:
    """Every ``definitionId`` the plan places."""
    return frozenset(n.definition_id for n in plan.nodes)


def entry_definition_ids(plan: GraphPlan, store=None) -> tuple[int, ...]:
    """The plan's entry nodes: nodes whose definition has NO execution input.

    Derived from ``data/node-contracts`` (a node with an execution *output* but no
    execution *input* is an event), so "the entry is ``71``" is a fact about the
    contract store, not about the order the builder happened to place nodes in.
    """
    from .. import contracts

    store = store or contracts.default_store()
    out: list[int] = []
    for node in plan.nodes:
        defn = store.require(node.definition_id)
        has_exec_in = any(p.kind == 1 for p in defn.ports)
        has_exec_out = any(p.kind == 2 for p in defn.ports)
        if has_exec_out and not has_exec_in:
            out.append(node.definition_id)
    return tuple(out)


def blocked_in_plan(plan: GraphPlan) -> frozenset[int]:
    """The plan's definitionIds that intersect :data:`BLOCKED_DEFINITION_IDS`."""
    return definition_ids(plan) & BLOCKED_DEFINITION_IDS


# ---------------------------------------------------------------------------
# Module coverage — which placed node belongs to which module, so a caller can
# read what the runnable demo actually exercises instead of being told.
# ---------------------------------------------------------------------------

MODULE_NODE_IDS: dict[str, frozenset[int]] = {
    "M1-interaction": frozenset(k.event_definition_id for k in m1.KINDS.values()),
    "M2-currency": frozenset(t.definition_id for t in (
        ADD_BAG_CURRENCY, GET_BAG_CURRENCY, BAG_CURRENCY_CHANGED,
    )),
    "M3-item": frozenset(t.definition_id for t in (
        ADD_BAG_ITEM, GET_BAG_ITEM, BAG_ITEM_ADDED, BAG_ITEM_LOST, BAG_ITEM_CHANGED,
        BAG_ITEM_USED,
    )),
    "M4-inventory": frozenset(t.definition_id for t in (
        GET_BAG_CAPACITY, ADD_BAG_CAPACITY, GET_ALL_BAG_ITEMS, GET_ALL_BAG_CURRENCIES,
    )),
    "M5-shop": frozenset(t.definition_id for t in (
        CLOSE_SHOP, OPEN_SHOP, SHOP_SOLD_BAG_ITEM, SHOP_BOUGHT_ITEM,
        *m5.SHOP_TABLE_NODE_TYPES, *m5.SHOP_QUERY_NODE_TYPES,
    )),
}


def covered_modules(plan: GraphPlan) -> tuple[str, ...]:
    """The modules with at least one placed node, in :data:`MODULE_NODE_IDS` order."""
    present = definition_ids(plan)
    return tuple(name for name, ids in MODULE_NODE_IDS.items() if present & ids)


@dataclass(frozen=True)
class RunnableConfig:
    """Everything the graph needs that lives in the editor, not in our tools."""

    currency_id: int            # 货币配置ID (type 20)
    crop_id: int                # 作物道具配置ID (type 20)
    item_slot: str = "int"      # the `--slot` used to write a configID (see paramtypes)
    currency_slot: str = "int"  # the `--slot` used to write a 货币配置ID (type 20)
    grow_amount: int = 10       # 685 delta — bag capacity added at level load
    harvest_gain: int = 1       # 686 delta — crops granted at level load
    coin_bonus: int = 10        # 688 delta — coins granted at level load
    recipe_cost: int = 2        # the crop threshold the first gate compares against
    coin_threshold: int = 100   # the wallet threshold the third gate compares against
    capacity_threshold: int = 20  # the bag-capacity threshold the second gate compares


def build(config: RunnableConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the runnable demo graph.  Returns an *unvalidated* :class:`Graph`.

    The **first** node placed — and therefore index 0 of the plan — is ``71``.
    """
    g = Graph(name)

    # --- entry: 71 实体创建时 (the bind target is created) --------------------
    create = g.place(ON_CREATE, "on_create")   # 71 实体创建时
    assert create.ntype is ON_CREATE

    # --- WAVE-29AA: unconditional probe the instant the entry fires -----------
    # The exec chain prints ONLY at its leaves (print_short etc.).  If a downstream
    # node aborts (offline prediction: 685 aborts when the bound entity carries no
    # bag component), nothing prints and NO_LOG_TRAFFIC cannot tell "the graph never
    # ran" from "it ran and died at step 2".  One 打印字符串 immediately after 71
    # makes ANY entry fire produce a capture.  See WAVE29AA-RUNBOOK.md.
    probe = g.place(PRINT, "print_entry")       # 1 打印字符串
    create.flow_to(probe)                       # 71.then -> 1.exec_in
    probe.const("text", ENTRY_PROBE_TEXT, "string")

    # --- 收 (M4 → M3 → M2): grow the bag, then harvest crops, then pay coins --
    grow = m4.grow_then(                                    # 685 增加背包最大容量
        g, probe, holder=(create, "entity"), amount=config.grow_amount, alias="grow",
    )
    harvest = m3.grant(                                     # 686 增加背包道具数量
        g, grow, holder=(create, "entity"), item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias="harvest",
    )
    bonus = m2.grant(                                       # 688 增加背包货币数量
        g, harvest, holder=(create, "entity"), currency_id=config.currency_id,
        amount=config.coin_bonus, currency_slot=config.currency_slot, alias="bonus",
    )

    # --- 合成判据 (F2): 作物够不够 → 2 双分支 --------------------------------
    item_cmp = m3.has_enough(                               # 690 读作物 + 233 大于等于
        g, holder=(create, "entity"), item_id=config.crop_id,
        threshold=config.recipe_cost, item_slot=config.item_slot, alias="craft_enough",
    )
    gate_item = g.place(BRANCH, "gate_item")                # 2 双分支
    bonus.flow_to(gate_item)                                # 688.then -> 2
    gate_item.data_from(item_cmp, "result", "condition")    # 233.结果 -> 2.条件

    # --- M4 容量门: 容量 < 阈值 → 提示 (true), 否则收获完成 (false) ----------
    cap_cmp = m4.capacity_gate(                             # 689 读容量 + 230 小于
        g, holder=(create, "entity"), threshold=config.capacity_threshold,
        alias="cap_gate", compare=CAPACITY_COMPARE,
    )
    gate_cap = g.place(BRANCH, "gate_cap")                  # 2 双分支
    gate_item.flow_to(gate_cap, "true")                     # 2.是 -> 2
    gate_cap.data_from(cap_cmp, "result", "condition")      # 230.结果 -> 2.条件

    p_low = g.place(PRINT, "print_low_cap")                 # 1 打印字符串
    gate_cap.flow_to(p_low, "true")                         # 2.是 -> 1
    p_low.const("text", LOW_CAPACITY_TEXT, "string")

    p_ok = g.place(PRINT, "print_ok")                       # 1 打印字符串
    gate_cap.flow_to(p_ok, "false")                         # 2.否 -> 1
    p_ok.const("text", HARVEST_OK_TEXT, "string")

    # --- 作物不够: 再看钱够不够 (M2 读 691 + 233) ---------------------------
    money_cmp = m2.read_and_compare(                        # 691 读货币 + 233 大于等于
        g, holder=(create, "entity"), currency_id=config.currency_id,
        threshold=config.coin_threshold, currency_slot=config.currency_slot,
        alias="coin_enough",
    )
    gate_money = g.place(BRANCH, "gate_money")              # 2 双分支
    gate_item.flow_to(gate_money, "false")                  # 2.否 -> 2
    gate_money.data_from(money_cmp, "result", "condition")  # 233.结果 -> 2.条件

    p_rich = g.place(PRINT, "print_rich")                   # 1 打印字符串
    gate_money.flow_to(p_rich, "true")                      # 2.是 -> 1
    p_rich.const("text", SHORT_ITEM_RICH_TEXT, "string")

    p_short = g.place(PRINT, "print_short")                 # 1 打印字符串
    gate_money.flow_to(p_short, "false")                    # 2.否 -> 1
    p_short.const("text", SHORT_ALL_TEXT, "string")

    return g


def plan_of(config: RunnableConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the runnable graph, returning its :class:`GraphPlan`.

    Raises :class:`tools.gameplan.plan.PlanError` if any node, edge or constant is
    inconsistent with ``data/node-contracts`` — before any native call.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


#: The config the committed plan artifact and the tests are generated from.
DEMO_CONFIG = RunnableConfig(currency_id=1115684864, crop_id=1120000001)


def demo_plan() -> GraphPlan:
    """The canonical plan (the one written to ``DEMO-RUNNABLE-plan.json``)."""
    return plan_of(DEMO_CONFIG)


def artifact(plan: GraphPlan) -> dict:
    """The plan as a self-describing JSON object (the ``DEMO-RUNNABLE-plan.json`` shape).

    Carries both the *invariants* a reader can check without running code
    (``entryDefinitionId`` / ``blockedIntersection`` / ``coveredModules``) and the
    concrete dispatch payloads — the adapter's ``build-plan`` shape (``batchPlan``,
    node refs are indices) and the ordered native argv list (``nativeCalls``).  Pure:
    the custom-call projection uses :class:`~graphplan.builder.GraphBuilder` with the
    *simulated* runner, so nothing is dispatched.
    """
    from ..builder import GraphBuilder, simulated_runner

    builder = GraphBuilder(plan, simulated_runner(), run_id="dry-run")
    result = builder.build()
    return {
        "graphName": plan.name,
        "graphKind": plan.graph_kind,
        "entryDefinitionId": entry_definition_ids(plan)[0] if entry_definition_ids(plan) else None,
        "nodeCount": len(plan.nodes),
        "edgeCount": len(plan.edges),
        "constCount": len(plan.consts),
        "blockedDefinitionIds": sorted(BLOCKED_DEFINITION_IDS),
        "blockedIntersection": sorted(blocked_in_plan(plan)),
        "coveredModules": list(covered_modules(plan)),
        "orderedNodes": [[n.alias, n.definition_id] for n in plan.nodes],
        "constants": [
            {"alias": c.alias, "portIndex": c.port_index, "slot": c.slot, "value": c.value}
            for c in plan.consts
        ],
        "batchPlan": builder.batch_plan_json(),
        "nativeCalls": [
            {"step": s.summary()["step"], "argv": s.argv} for s in result.steps
        ],
    }


def describe(plan: GraphPlan) -> list[str]:
    """One human line per node, in build order: ``idx  defId(alias)  <- in, -> out``.

    A readable projection of the plan so a reader can check "what will happen if it
    runs" without decoding node contracts.  Pure.
    """
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
    "BLOCKED_DEFINITION_IDS",
    "CAPACITY_COMPARE",
    "DEFAULT_NAME",
    "DEMO_CONFIG",
    "ENTRY_PROBE_TEXT",
    "HARVEST_OK_TEXT",
    "LOW_CAPACITY_TEXT",
    "MODULE_NODE_IDS",
    "RunnableConfig",
    "SHORT_ALL_TEXT",
    "SHORT_ITEM_RICH_TEXT",
    "artifact",
    "blocked_definition_ids",
    "blocked_in_plan",
    "build",
    "covered_modules",
    "definition_ids",
    "demo_plan",
    "describe",
    "entry_definition_ids",
    "plan_of",
]
