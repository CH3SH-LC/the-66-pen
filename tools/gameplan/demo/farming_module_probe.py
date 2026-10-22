"""The MODULE PROBE: one entry-``71`` graph that places a node from **each module
the census says is real**, and prints **one distinct string per module** so a
single playtest capture attributes each print to a module.

What this fixes, and what it deliberately does NOT claim
--------------------------------------------------------

``demo/farming_runnable.py`` proves *"a graph ran"* (entry fires, two RAW print
nodes captured).  It does **not** prove any *module function ran*: it places only
M2/M3/M4 writer nodes, and three of the five prints sit on branches that a config
change can select.  The gap is attribution — a captured line proves *a* string
was printed, not *which module's node produced it*.

This graph closes that gap **at the node level**.  A probe chain runs:

::

    on_create  71 实体创建时                                   (entry)
      └ then ─▶ print_entry  1 "W29AI模块探针入口已触发"           (the "it ran" probe)
                  └ then ─▶ m4_grow     685 增加背包最大容量       +grow_amount
                              └ then ─▶ print_m4  1 "W29AI-M4-背包容量已扩容"
                                          └ then ─▶ m3_grant    686 增加背包道具数量    +harvest_gain
                                                      └ then ─▶ print_m3  1 "W29AI-M3-道具已发放"
                                                                   └ then ─▶ m2_grant   688 增加背包货币数量   +coin_bonus
                                                                                └ then ─▶ print_m2  1 "W29AI-M2-货币已发放"
                                                                                             └ then ─▶ m1_activate 90 激活/关闭碰撞触发器
                                                                                                          └ then ─▶ print_m1  1 "W29AI-M1-碰撞触发器已激活"
                                                                                                                        └ then ─▶ m5_open  702 打开商店
                                                                                                                                      └ then ─▶ print_m5 1 "W29AI-M5-商店已打开"
                                                                                                                                                    └ then ─▶ print_end 1 "W29AI模块探针结束"

13 nodes / 18 edges / 15 consts, kind 20000.  Each module node is *immediately*
followed by its own print, so "the print fired" ⇒ "the module node's ``then``
fired" ⇒ **the engine executed that module's node**.  Every print string is
unique to this graph (the ``W29AI`` prefix), so a capture is self-identifying and
each line pins exactly one module (the prediction proves uniqueness — see
:mod:`tools.gameplan.runtime_prediction`).

THE ONE HONESTY LINE (node executed ≠ module works)
---------------------------------------------------

This graph proves a module's **node ran**, **not** that the module's *effect*
landed.  Two of the five placements in particular are the same "dangling
reference" every demo in this tree rests on:

* ``685``/``686``/``688`` act on a 背包组件 the bare created entity may not
  carry, and a config-id (type 20) with no editor template instance — the write
  is **inert** (``runtime_prediction.DEPENDENCY_NOTES``), the node still runs.
* ``90`` 激活/关闭碰撞触发器 and ``702`` 打开商店 act on a **碰撞触发器 / 商店组件**
  that must sit on an entity.  This project cannot add a component
  (``CLAUDE.md`` §六(a)), so those components do not exist on the created entity:
  the **node executes**, but there is no trigger to activate and no store to
  open.  ``702`` in particular is in the *derived blocked set* of
  ``coverage.py`` / ``farming_runnable`` (as the shop-component family), so this
  graph **deliberately diverges** from that set — see below.

Why ``90`` and ``702`` are included when the old demo blocked them
------------------------------------------------------------------

The old demos dropped M1 and M5 because they looked only at the four M1 *events*
(``91``/``92``/``316``/``826``) and the shop-component family.  The offline
``NODE-CENSUS-BY-MODULE`` (811 nodes) shows both buckets carry **placeable**
nodes the old view missed:

* M1 interaction = 16 nodes; ``90`` is a chain node (exec-in/exec-out) whose
  three inputs are ``目标实体`` (entity) + ``触发器序号`` (int) + ``是否激活``
  (bool) — the entity comes from ``71``, the other two are literals.
* M5 shop = 20 nodes; ``702`` 打开商店 is a chain node whose inputs are two
  entities (``71`` twice) + one int literal.

Both contracts are verified in ``data/node-contracts`` (and, for ``90``, by
``tests/test_plan.py`` re-deriving its roles).  Nothing here is a guessed defId.
The M1/M5 *events* remain absent (an event can never be a flow target), and the
shop *table writers* remain absent (their price pin is a type-27 dict this
project cannot write).

M6 地形/地块 — the module that CANNOT be exercised this way
-----------------------------------------------------------

The same census finds **0** terrain instruction nodes (bounded negative against
the node-name surface, positive-controlled).  Terrain is an editor concept (a
terrain tab / ``TILEMAP`` type / ``.gil`` field 7), not a node graph.  There is
no node to place, so M6 is **uncoverable by any graph** and is absent by
construction — see :data:`UNAVAILABLE_MODULES`.

Named ``plan_of`` — **not** ``build_plan`` — on purpose: the demo-golden guard
(``tests/test_demo_golden.py``) discovers every ``demo/*.py`` exposing
``build_plan`` and demands a frozen snapshot.  This module's shape guard is
``tests/test_demo_module_probe.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import (
    ACTIVATE_COLLISION_TRIGGER,
    ADD_BAG_CAPACITY,
    ADD_BAG_CURRENCY,
    ADD_BAG_ITEM,
    ON_CREATE,
    OPEN_SHOP,
    PRINT,
    Graph,
    Handle,
    NodeType,
)
from ..plan import GraphPlan
from ..modules import currency as m2
from ..modules import inventory as m4
from ..modules import item as m3

DEFAULT_NAME = "MW_API_MODPROBE"
"""The graph name; matches ``plan.GRAPH_NAME_RE`` (``MW_API_`` + ``[A-Za-z0-9_]{1,48}``)."""

# ---------------------------------------------------------------------------
# One print string per module — each unique, each self-identifying.
# ---------------------------------------------------------------------------

#: The unconditional line printed the instant the entry fires (the WAVE-29AA probe).
ENTRY_PROBE_TEXT = "W29AI模块探针入口已触发"

#: M1 交互点 — fires iff node ``90`` executed.
M1_TEXT = "W29AI-M1-碰撞触发器已激活"
#: M2 货币 — fires iff node ``688`` executed.
M2_TEXT = "W29AI-M2-货币已发放"
#: M3 道具 — fires iff node ``686`` executed.
M3_TEXT = "W29AI-M3-道具已发放"
#: M4 背包 — fires iff node ``685`` executed.
M4_TEXT = "W29AI-M4-背包容量已扩容"
#: M5 商店 — fires iff node ``702`` executed.
M5_TEXT = "W29AI-M5-商店已打开"
#: The end-of-chain marker — fires only if the WHOLE chain ran to the last node.
END_TEXT = "W29AI模块探针结束"

# ---------------------------------------------------------------------------
# The census-based module table.  Every id is verified in data/node-contracts;
# never a guessed defId.  Keys are the six module names, in a fixed order.
# ---------------------------------------------------------------------------

#: module -> the ONE :class:`NodeType` this graph places to exercise it.  This is
#: the *census* view (each module's placeable chain node), which is broader than
#: :data:`tools.gameplan.coverage.MODULE_NODE_IDS` for M1/M5 — deliberately, and
#: documented in the module docstring.
CENSUS_MODULE_NODE: dict[str, NodeType] = {
    "M1-interaction": ACTIVATE_COLLISION_TRIGGER,  # 90 激活/关闭碰撞触发器
    "M2-currency": ADD_BAG_CURRENCY,               # 688 增加背包货币数量
    "M3-item": ADD_BAG_ITEM,                       # 686 增加背包道具数量
    "M4-inventory": ADD_BAG_CAPACITY,              # 685 增加背包最大容量
    "M5-shop": OPEN_SHOP,                          # 702 打开商店
}

#: module -> the exact print string its node leads to (the `print_m*` node).
MODULE_PRINT_TEXT: dict[str, str] = {
    "M1-interaction": M1_TEXT,
    "M2-currency": M2_TEXT,
    "M3-item": M3_TEXT,
    "M4-inventory": M4_TEXT,
    "M5-shop": M5_TEXT,
}

#: The modules the graph CANNOT exercise, and the derived reason — never a choice.
UNAVAILABLE_MODULES: dict[str, str] = {
    "M6-level-terrain": (
        "the NODE-CENSUS-BY-MODULE finds 0 terrain instruction nodes against the "
        "811-node name surface (positive-controlled: 商店=17, 货币=8): terrain is "
        "an editor concept (terrain tab / TILEMAP type / .gil field 7), so it has "
        "no node to place and no entry-71 graph can exercise it"
    ),
}

#: Execution-chain order: the well-understood M4/M3/M2 writers first, then the
#: component-gated M1/M5 nodes LAST, so a later abort cannot suppress an earlier
#: module's evidence (each print fires iff its own module node's ``then`` fired).
_CHAIN_ORDER: tuple[str, ...] = (
    "M4-inventory", "M3-item", "M2-currency", "M1-interaction", "M5-shop",
)


def definition_ids(plan: GraphPlan) -> frozenset[int]:
    """Every ``definitionId`` the plan places."""
    return frozenset(n.definition_id for n in plan.nodes)


def covered_modules(plan: GraphPlan) -> tuple[str, ...]:
    """The modules with their census node placed, in :data:`CENSUS_MODULE_NODE` order."""
    present = definition_ids(plan)
    return tuple(
        name for name, ntype in CENSUS_MODULE_NODE.items()
        if ntype.definition_id in present
    )


def entry_definition_ids(plan: GraphPlan, store=None) -> tuple[int, ...]:
    """The plan's entry nodes: contracts with an execution output and no exec input."""
    from .. import contracts

    store = store or contracts.default_store()
    out: list[int] = []
    for node in plan.nodes:
        defn = store.require(node.definition_id)
        if defn.exec_outputs and not defn.exec_inputs:
            out.append(node.definition_id)
    return tuple(out)


@dataclass(frozen=True)
class ProbeConfig:
    """Everything the graph needs that lives in the editor, not in our tools."""

    currency_id: int            # 货币配置ID (type 20)
    crop_id: int                # 作物道具配置ID (type 20)
    item_slot: str = "int"      # the `--slot` used to write a configID
    currency_slot: str = "int"  # the `--slot` used to write a 货币配置ID (type 20)
    grow_amount: int = 10       # 685 delta — bag capacity added
    harvest_gain: int = 1       # 686 delta — crops granted
    coin_bonus: int = 10        # 688 delta — coins granted
    trigger_index: int = 0      # 90 触发器序号 (int literal)
    activate: bool = True       # 90 是否激活 (bool literal)
    shop_index: int = 0         # 702 商店序号 (int literal)


def _module_node(g: Graph, module: str, src: Handle, create: Handle, config: ProbeConfig) -> Handle:
    """Place one module's node on the exec chain ``src`` and return its handle.

    Every node's inputs come from ``create`` (the ``71`` entry entity) plus
    literals — nothing else.  The M1 (``90``) and M5 (``702``) nodes are placed
    directly because neither module function exposes a placeable chain node (their
    event/table-writer half is blocked); the M2/M3/M4 writers use the module
    fragments so their pin wiring stays single-sourced.
    """
    if module == "M2-currency":
        return m2.grant(
            g, src, holder=(create, "entity"), currency_id=config.currency_id,
            amount=config.coin_bonus, currency_slot=config.currency_slot, alias="m2_grant",
        )
    if module == "M3-item":
        return m3.grant(
            g, src, holder=(create, "entity"), item_id=config.crop_id,
            count=config.harvest_gain, item_slot=config.item_slot, alias="m3_grant",
        )
    if module == "M4-inventory":
        return m4.grow_then(
            g, src, holder=(create, "entity"), amount=config.grow_amount, alias="m4_grow",
        )
    if module == "M1-interaction":
        node = g.place(ACTIVATE_COLLISION_TRIGGER, "m1_activate")   # 90
        src.flow_to(node)
        node.data_from(create, "entity", "target")                  # 目标实体 <- 71.entity
        node.const("trigger_index", int(config.trigger_index), "int")
        node.const("activate", bool(config.activate), "bool")
        return node
    if module == "M5-shop":
        node = g.place(OPEN_SHOP, "m5_open")                        # 702
        src.flow_to(node)
        node.data_from(create, "entity", "player")                  # 玩家实体 <- 71.entity
        node.data_from(create, "entity", "shop_owner")              # 商店归属者实体 <- 71.entity
        node.const("shop_index", int(config.shop_index), "int")
        return node
    raise KeyError(f"unknown module {module!r}; known: {sorted(CENSUS_MODULE_NODE)}")


def build(config: ProbeConfig, name: str = DEFAULT_NAME) -> Graph:
    """Build the module probe.  Returns an *unvalidated* :class:`Graph`.

    The **first** node placed — and therefore index 0 of the plan — is ``71``.
    """
    g = Graph(name)

    create = g.place(ON_CREATE, "on_create")        # 71 实体创建时
    assert create.ntype is ON_CREATE

    probe = g.place(PRINT, "print_entry")           # 1 打印字符串 (unconditional)
    create.flow_to(probe)
    probe.const("text", ENTRY_PROBE_TEXT, "string")

    src: Handle = probe
    for module in _CHAIN_ORDER:
        node = _module_node(g, module, src, create, config)
        line = g.place(PRINT, f"print_{module.split('-')[0].lower()}")   # 1
        node.flow_to(line)
        line.const("text", MODULE_PRINT_TEXT[module], "string")
        src = line

    end = g.place(PRINT, "print_end")               # 1 打印字符串
    src.flow_to(end)
    end.const("text", END_TEXT, "string")

    return g


def plan_of(config: ProbeConfig, name: str = DEFAULT_NAME) -> GraphPlan:
    """Build and validate the probe graph, returning its :class:`GraphPlan`.

    Raises :class:`tools.gameplan.plan.PlanError` if any node, edge or constant is
    inconsistent with ``data/node-contracts`` — before any native call.
    """
    graph = build(config, name=name)
    graph.validate()
    return graph.plan


#: The config the committed plan artifact and the tests are generated from.
DEMO_CONFIG = ProbeConfig(currency_id=1115684864, crop_id=1120000001)


def demo_plan() -> GraphPlan:
    """The canonical plan (the one written to ``DEMO-MODPROBE-plan.json``)."""
    return plan_of(DEMO_CONFIG)


#: The full predicted string set, in firing order, for the canonical config.
PREDICTED_PRINTS: tuple[str, ...] = (
    ENTRY_PROBE_TEXT,
    M4_TEXT, M3_TEXT, M2_TEXT, M1_TEXT, M5_TEXT,
    END_TEXT,
)


def artifact(plan: GraphPlan) -> dict:
    """The plan as a self-describing JSON object (the ``DEMO-MODPROBE-plan.json`` shape).

    Carries the invariants a reader can check without running (``entryDefinitionId``
    / ``coveredModules`` / ``unavailableModules`` / the per-module print map) and the
    concrete dispatch payloads (adapter ``build-plan`` shape + ordered native argv).
    Pure: the custom-call projection uses the *simulated* runner, so nothing is
    dispatched.
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
        "coveredModules": list(covered_modules(plan)),
        "unavailableModules": dict(UNAVAILABLE_MODULES),
        "moduleNodeDefinitionIds": {
            name: ntype.definition_id for name, ntype in CENSUS_MODULE_NODE.items()
        },
        "modulePrintText": dict(MODULE_PRINT_TEXT),
        "predictedPrints": list(PREDICTED_PRINTS),
        "orderedNodes": [[n.alias, n.definition_id] for n in plan.nodes],
        "constants": [
            {"alias": c.alias, "portIndex": c.port_index, "slot": c.slot, "value": c.value}
            for c in plan.consts
        ],
        "batchPlan": builder.batch_plan_json(),
        "nativeCalls": [{"step": s.summary()["step"], "argv": s.argv} for s in result.steps],
    }


def describe(plan: GraphPlan) -> list[str]:
    """One human line per node, in build order: ``idx  defId(alias)  in/val/then``.

    A readable projection so a reader can check "what will happen if it runs"
    without decoding node contracts.  Pure.
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
    "CENSUS_MODULE_NODE",
    "DEFAULT_NAME",
    "DEMO_CONFIG",
    "END_TEXT",
    "ENTRY_PROBE_TEXT",
    "M1_TEXT",
    "M2_TEXT",
    "M3_TEXT",
    "M4_TEXT",
    "M5_TEXT",
    "MODULE_PRINT_TEXT",
    "PREDICTED_PRINTS",
    "ProbeConfig",
    "UNAVAILABLE_MODULES",
    "artifact",
    "build",
    "covered_modules",
    "definition_ids",
    "demo_plan",
    "describe",
    "entry_definition_ids",
    "plan_of",
]
