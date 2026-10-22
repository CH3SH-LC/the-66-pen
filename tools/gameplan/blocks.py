"""Self-contained entry→exit **blocks** for the six gameplay modules.

The defect this module exists to fix
------------------------------------
``tools/gameplan/modules/`` emits *fragments*: every function takes an execution
source (``src``) the caller supplies, places a node or two, and hands a handle
back.  A fragment is not a block.  It cannot be **entered** (there is no entry
node), it cannot be **exited** (nothing observes the result), and therefore a
fragment that is never wired into a graph by hand never runs.  The 2026-10-12
census (``NODE-CENSUS-BY-MODULE``) made that concrete: of the module functions
in this tree, none is a complete ``入口 → … → 出口`` block.

This module makes each module's capability a **block**:

* an **entry** — a contract with an execution output and *no* execution input
  (an event node: ``71 实体创建时``, ``92 进入碰撞触发器时``, ``681/682/683/733``,
  ``684``, ``701/705`` …).  Exactly one per block;
* a **body** — the module's own nodes, wired by the module functions so the pin
  roles stay single-sourced (``tests/test_plan.py`` re-derives them);
* an **exit** — the execution tip: a node that receives an execution edge and
  sends none.  Every block here ends its chain in ``打印字符串`` (defId ``1``),
  the one observable the project has: a captured line proves the module node's
  ``then`` fired, hence that the engine executed it.

A block is **well-formed** iff it has exactly one entry, at least one exit,
**every** exit is a print, and every node is reachable from the entry
(:func:`block_shape` / :attr:`BlockShape.well_formed`).  The "every exit is a
print" clause (not merely "at least one") is what rejects a *dead module leg*:
a body node whose execution output is left unwired is itself an execution tip,
and a block that prints from the entry while the module node's ``then`` goes
nowhere would otherwise be judged well-formed.  Nothing here is dispatched,
saved, or pinned to a level.

Where a block cannot be completed, it is not faked
--------------------------------------------------
Two paths hit a real obstacle and raise a **named**, catchable error at the
obstacle — the ``DictPinUnsupported`` precedent from ``modules/shop.py``:

* the two type-27 dict queries (``721``/``722``) — the accessor ``1158
  以键查询字典值`` IS in the store, but all three of its pins are declared
  **generic** (``serverParamType 0``) and it has never been placed, so the
  concrete(27)→generic materialisation is unproven ⇒ :class:`DictAccessUnproven`
  (opt in with ``assume_generic_accessor=True`` to take the assumption);
* the two shop sale-table queries (``714``/``715``) — their outputs are opaque
  aggregates (``serverParamType 8``/``22``) the store declares **no** accessor
  for ⇒ :class:`ShopAggregateUnreadable`;
* ``M6 地块/地形`` — **0** instruction nodes (positive-controlled census), so no
  block can be assembled at all ⇒ :class:`TerrainHasNoNodeBlock``;
* the ``M1`` loot-pickup entry (掉落物拾取) — the census finds **no** loot-pickup
  event node (exec output, no exec input) in the 500-def store, so there is no
  entry to build a block from ⇒ :class:`LootPickupHasNoEventNode` (raised by
  :func:`loot_pickup_block`).  Its scene half (a 掉落物内容组件 + 拾取规则) is an
  editor step this project cannot author.

The ``M5`` custom-store table writer (``704``) still refuses with the existing
``shop.DictPinUnsupported`` when a price must be a 出售货币字典 (type-27) constant.

Doctrine: only contract-verified node ids, no invented pins.  Every defId placed
by a block is re-checked against ``data/node-contracts`` in
``tests/test_module_blocks.py``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

#: Repo root: this file lives at <root>/tools/gameplan/blocks.py
_REPO_ROOT = Path(__file__).resolve().parents[2]

from . import contracts
from .contracts import DATA_INPUT, EXEC_INPUT, EXEC_OUTPUT
from .modules import currency as _m2
from .modules import interaction as _m1
from .modules import inventory as _m4
from .modules import item as _m3
from .modules import shop as _m5
from .nodes import (
    ACTIVATE_COLLISION_TRIGGER,
    BRANCH,
    DICT_LOOKUP,
    GE,
    ON_CREATE,
    PRINT,
    Graph,
    Handle,
)
from .plan import GraphPlan

#: interaction kind key -> the module function that places that event node.
KIND_FUNCTION: dict[str, str] = {
    "proximity": "proximity_enter",
    "proximity-exit": "proximity_leave",
    "ui-button": "ui_control_triggered",
    "floating-page": "floating_page_triggered",
    "text-bubble": "text_bubble_completed",
}

#: Module order, fixed (mirrors ``coverage.MODULE_ORDER``).
MODULE_ORDER: tuple[str, ...] = (
    "M1-interaction",
    "M2-currency",
    "M3-item",
    "M4-inventory",
    "M5-shop",
    "M6-level-terrain",
)

#: Config-ids used by the canonical blocks.  They are plain numbers on the wire
#: (contract type 20); with no item/currency template authored they *dangle* — the
#: write is inert — but the node still places and runs, which is all a block claims.
CURRENCY_ID = 1001
ITEM_ID = 2001
BUBBLE_ID = 3001


def block_text(module: str, tag: str) -> str:
    """A per-block, self-identifying print string (``BLK-<Mx>-<TAG>``)."""
    return f"BLK-{module.split('-')[0]}-{tag}"


# ---------------------------------------------------------------------------
# Named refusals (the obstacles a block cannot cross)
# ---------------------------------------------------------------------------

class BlockError(Exception):
    """Base for a module block that cannot be completed as written."""

    code = "BLOCK_ERROR"

    def __init__(self, message: str, *, graph: Graph | None = None):
        self.graph = graph  # the partial block, up to the obstacle (may be None)
        super().__init__(message)


def _partial_nodes(graph: Graph | None) -> tuple[int, ...]:
    if graph is None:
        return ()
    return tuple(n.definition_id for n in graph.plan.nodes)


class DictAccessUnproven(BlockError):
    """A concrete type-27 dict output has no *proven* consumer.

    The accessor ``1158 以键查询字典值`` exists (the 2026-10-12 correction retired
    the false "the family is absent" negative), but all three of its pins are
    declared generic (``serverParamType 0``) and it has never been placed in a
    real graph, so whether the editor materialises the concrete(27) dict into the
    generic pins is UNPROVEN.  This is a named refusal, not a fake read.
    """

    code = "DICT_ACCESS_UNPROVEN"

    def __init__(self, node_id: int, out_index: int, *, graph: Graph | None = None):
        self.node_id = int(node_id)
        self.out_index = int(out_index)
        self.nodes = _partial_nodes(graph)
        super().__init__(
            f"defId {node_id} output 4:{out_index} is a concrete type-27 dict and "
            f"no consumer here binds it: the accessor 1158 以键查询字典值 is in the "
            f"store but declares ALL pins generic (serverParamType 0) and has never "
            f"been placed, so the concrete(27)->generic materialisation is unproven. "
            f"Use item.read(690) with a known 道具配置ID, or pass "
            f"assume_generic_accessor=True to take the assumption explicitly",
            graph=graph,
        )


class ShopAggregateUnreadable(BlockError):
    """A shop sale-table query output (type 8 / 22) has no accessor anywhere."""

    code = "SHOP_AGGREGATE_UNREADABLE"

    def __init__(
        self, node_id: int, out_index: int, server_param_type: int, *,
        graph: Graph | None = None,
    ):
        self.node_id = int(node_id)
        self.out_index = int(out_index)
        self.server_param_type = int(server_param_type)
        super().__init__(
            f"defId {node_id} output 4:{out_index} is an opaque aggregate "
            f"(serverParamType {server_param_type}); the server contract store "
            f"declares no accessor whose data input is type {server_param_type}, so "
            f"the value is both unwritable and unreadable here. Drive the table with "
            f"list_item_for_sale(709/706) and read single quantities with 690 instead",
            graph=graph,
        )


class TerrainHasNoNodeBlock(BlockError):
    """M6 has no node half: the census finds 0 terrain instruction nodes."""

    code = "TERRAIN_HAS_NO_NODE_BLOCK"

    def __init__(self):
        super().__init__(
            "M6 地块/地形 has 0 instruction nodes in the NODE-CENSUS-BY-MODULE "
            "corpus (811 nodes; same-run positive controls 商店=17 货币=8 道具=14). "
            "Terrain is an editor concept (.gil field 7 / a TILEMAP type / the 地形 "
            "编辑页签), and placement is a scene action (entity.create by "
            "coordinate), so no entry→exit node block can be assembled"
        )


class LootPickupHasNoEventNode(BlockError):
    """M1 entry 5 (掉落物拾取) has **no dedicated event node**: no entry to be.

    A same-instrument census over the whole 500-def contract store (event = an
    execution output and no execution input) finds exactly **one** loot/bubble
    family event — ``679 文本气泡完成时`` — and it is the text bubble, not the
    pickup.  Every other 掉落/拾取/战利品 node is an **action** (exec in *and*
    out: ``687``/``720``/``724``/``725``/``726``/``727``) or a **data-only**
    query (``728``/``729``/``730``/``731``/``732``) — none can be a block's entry.
    The pickup is a property of the ``掉落物内容组件`` on the dropped entity
    (拾取规则 ∈ {交互拾取, 自动拾取, 打开拾取界面, 自动吸附拾取}), and the node
    layer only *observes* it through the generic ``681 背包道具新增时`` event,
    which already has a block (``item.on_added``).  So M1's loot-pickup entry is
    **not** an :class:`~tools.gameplan.modules.interaction.InteractionKind` (a kind
    requires an ``event_definition_id``) and has no entry→exit block.
    """

    code = "LOOT_PICKUP_HAS_NO_EVENT_NODE"

    #: The loot-pickup family's node ids, every one verified present in
    #: ``data/node-contracts`` (``contracts.load_store``) by
    #: ``tests/test_interaction_entries.py`` — none is invented.
    nodes: tuple[int, ...] = (687, 720, 724, 725, 726, 727, 728, 729, 730, 731, 732)

    def __init__(self, *, graph: Graph | None = None):
        super().__init__(
            "M1 entry 5 掉落物拾取 has NO event node: a same-instrument census of "
            "the 500-def contract store (exec output, no exec input) finds no "
            "loot-pickup event — the 11 掉落/拾取/战利品 nodes are all actions "
            "(687/720/724/725/726/727) or data-only queries (728/729/730/731/732), "
            "and the pickup is observed only via the generic 681 背包道具新增时 "
            "(already a block: item.on_added). A block needs an entry event, so "
            "there is nothing to build; the scene half (a 掉落物内容组件 + 拾取规则) "
            "is an editor step this project cannot author",
            graph=graph,
        )


def loot_pickup_block() -> Graph:
    """M1's loot-pickup entry cannot be a node block at all.  Always raises."""
    raise LootPickupHasNoEventNode()


# ---------------------------------------------------------------------------
# Entry / exit analysis — pure reads of a GraphPlan
# ---------------------------------------------------------------------------

def entry_aliases(plan: GraphPlan, store=None) -> tuple[str, ...]:
    """The plan's event nodes: an execution output and no execution input."""
    store = store or contracts.default_store()
    return tuple(
        n.alias
        for n in plan.nodes
        if store.require(n.definition_id).exec_outputs
        and not store.require(n.definition_id).exec_inputs
    )


def exit_aliases(plan: GraphPlan) -> tuple[str, ...]:
    """The plan's execution tips: nodes that RECEIVE an execution edge and SEND none.

    Purely edge-derived (no role table): a tip is a node an execution edge lands on
    from which no execution edge leaves.  A print at the end of a chain qualifies.
    A *body* node whose exec-out is left unwired is **also** a tip (it received an
    edge and sends none) — that is why :attr:`BlockShape.well_formed` requires
    **every** tip to be a print, so a dangling module leg is not mistaken for a
    complete block.
    """
    fed = {e.dst for e in plan.edges if e.dst_kind == EXEC_INPUT}
    sends = {e.src for e in plan.edges if e.src_kind == EXEC_OUTPUT}
    order = [n.alias for n in plan.nodes]
    return tuple(alias for alias in order if alias in fed and alias not in sends)


def reachable_aliases(plan: GraphPlan) -> frozenset[str]:
    """Every alias downstream of the plan's single entry (all edges followed).

    Returns the empty set when the plan has zero or more than one entry (which IS
    "the entry" is ambiguous).
    """
    entries = entry_aliases(plan)
    if len(entries) != 1:
        return frozenset()
    reached = {entries[0]}
    changed = True
    while changed:
        changed = False
        for edge in plan.edges:
            if edge.src in reached and edge.dst not in reached:
                reached.add(edge.dst)
                changed = True
    return frozenset(reached)


@dataclass(frozen=True)
class BlockShape:
    """The entry/exit shape of a plan, and whether it is a complete block."""

    entry: tuple[str, ...]
    exits: tuple[str, ...]
    print_exits: tuple[str, ...]
    reachable: tuple[str, ...]
    unreachable: tuple[str, ...]

    @property
    def well_formed(self) -> bool:
        """Exactly one entry, ≥1 exit, **every** exit a print, nothing unreachable.

        ``print_exits`` is a subset of ``exits``, so ``print_exits == exits``
        means "no execution tip is a non-print" — i.e. no route out of the entry
        dead-ends in a body node.  Requiring only *one* print exit (the pre-fix
        rule) let a block pass with the module node's ``then`` going nowhere.
        """
        return (
            len(self.entry) == 1
            and bool(self.exits)
            and tuple(self.print_exits) == self.exits
            and not self.unreachable
        )


def block_shape(plan: GraphPlan, store=None) -> BlockShape:
    """Derive the block shape of *plan* (pure; never raises on a bad shape)."""
    store = store or contracts.default_store()
    entry = entry_aliases(plan, store)
    exits = exit_aliases(plan)
    print_exits = tuple(
        a for a in exits if plan.aliases()[a].definition_id == PRINT.definition_id
    )
    reached = reachable_aliases(plan)
    order = [n.alias for n in plan.nodes]
    unreachable = tuple(a for a in order if a not in reached) if reached else tuple(order)
    if not reached:
        reachable = ()
    else:
        reachable = tuple(a for a in order if a in reached)
    return BlockShape(
        entry=entry,
        exits=exits,
        print_exits=print_exits,
        reachable=reachable,
        unreachable=unreachable,
    )


def unwired_concrete_inputs(plan: GraphPlan, store=None) -> tuple[str, ...]:
    """Concrete data inputs of the plan that are neither wired nor constant-fed.

    Named gap **(c)** in the ledger: ``well_formed`` does **not** fail-closed on
    these.  Whether an unwired input is a *defect* depends on whether it is
    required, and ``data/node-contracts`` marks ``required`` as ``unknown`` for
    every port — so a blanket "every concrete input must be fed" rule would flip
    three currently-COMPLETE blocks (``230 3:2`` / ``233 3:2`` op pins left
    deliberately unwritten, and ``709 3:3`` the type-27 price).  Instead of
    guessing, this *reports* them so the ledger can name the hole with evidence.

    Returns ``"<alias> 3:<index> spt<N> (<node name>)"`` strings, in node order.
    """
    store = store or contracts.default_store()
    fed = {(e.dst, e.dst_index) for e in plan.edges if e.dst_kind == DATA_INPUT}
    const_fed = {(c.alias, c.port_index) for c in plan.consts}
    found: list[str] = []
    for node in plan.nodes:
        definition = store.require(node.definition_id)
        for port in definition.ports:
            if port.kind != DATA_INPUT or port.is_generic:
                continue
            if (node.alias, port.index) in fed or (node.alias, port.index) in const_fed:
                continue
            found.append(
                f"{node.alias} 3:{port.index} spt{port.server_param_type} "
                f"({definition.name})"
            )
    return tuple(found)


# ---------------------------------------------------------------------------
# Builders — small, role-aware helpers
# ---------------------------------------------------------------------------

def _entry(g: Graph, alias: str = "on_create") -> Handle:
    return g.place(ON_CREATE, alias)  # 71 实体创建时


def _exit(g: Graph, src: Handle, text: str, alias: str = "exit",
          from_role: str = "then") -> Handle:
    node = g.place(PRINT, alias)  # 1 打印字符串 — the observable exit
    src.flow_to(node, from_role)
    node.const("text", text, "string")
    return node


def _name(tag: str, override: str | None) -> str:
    return override or f"MW_API_BLK_{tag}"


# ---------------------------------------------------------------------------
# M1 — interaction
# ---------------------------------------------------------------------------

def interaction_event_block(kind: _m1.InteractionKind, *, text: str | None = None,
                            name: str | None = None) -> Graph:
    """``kind.event_definition_id`` (entry) → ``打印字符串`` (exit).

    The event node *is* the block's entry; the graph half is complete.  The scene
    half (a 碰撞触发器 component / a UI control group / a 悬浮交互页) is an editor
    step this project cannot author — the block builds and validates, but its entry
    only fires once that half exists.
    """
    g = Graph(_name(f"M1_{kind.key.upper().replace('-', '_')}", name))
    event = _m1.event(g, kind, "enter")
    _exit(g, event, text or block_text("M1-interaction", kind.key.upper()), "exit")
    return g


def interaction_activate_block(*, trigger_index: int = 0, activate: bool = True,
                               text: str | None = None, name: str | None = None) -> Graph:
    """``71`` (entry) → ``90 激活/关闭碰撞触发器`` → ``打印字符串`` (exit).

    ``90`` is M1's one *chain* node (exec-in and exec-out), so unlike the events it
    can hang off the ``71`` entry.  Its three inputs are the entry entity
    (``3:0`` entity), a trigger index (``3:1`` int) and an activate flag (``3:2``
    bool) — all satisfiable from the entry plus literals.
    """
    g = Graph(_name("M1_ACTIVATE", name))
    create = _entry(g)
    node = g.place(ACTIVATE_COLLISION_TRIGGER, "activate")  # 90
    create.flow_to(node)
    node.data_from(create, "entity", "target")
    node.const("trigger_index", int(trigger_index), "int")
    node.const("activate", bool(activate), "bool")
    _exit(g, node, text or block_text("M1-interaction", "ACTIVATE"), "exit")
    return g


def interaction_switch_bubble_block(*, bubble_id: int = BUBBLE_ID,
                                    bubble_slot: str = "int",
                                    text: str | None = None,
                                    name: str | None = None) -> Graph:
    """``71`` (entry) → ``631 切换生效的文本气泡`` → ``打印字符串`` (exit).

    The text-bubble entry's **action half**, mirroring
    :func:`interaction_activate_block` (``71`` → ``90`` → print) for the proximity
    entry: the event ``679`` is what fires, ``631`` is what it acts with.  Its two
    inputs are the entry entity (``3:0``, the entity carrying the 文本气泡
    component) and a 文本气泡配置ID (``3:1`` config-id, type 20) — both satisfiable
    from the entry plus a literal.  Scene half: the target needs a 文本气泡
    component, the same missing add-component primitive as the other M1 entries.
    """
    g = Graph(_name("M1_SWITCH_BUBBLE", name))
    create = _entry(g)
    node = _m1.switch_text_bubble(
        g, create, target=(create, "entity"), bubble_id=bubble_id,
        bubble_id_slot=bubble_slot, alias="switch_bubble",
    )
    _exit(g, node, text or block_text("M1-interaction", "SWITCH_BUBBLE"), "exit")
    return g


# ---------------------------------------------------------------------------
# M2 — currency
# ---------------------------------------------------------------------------

def currency_grant_block(*, currency_id: int = CURRENCY_ID, amount: int = 10,
                         currency_slot: str = "int", text: str | None = None,
                         name: str | None = None) -> Graph:
    """``71`` (entry) → ``688 增加背包货币数量`` → ``打印字符串`` (exit)."""
    g = Graph(_name("M2_GRANT", name))
    create = _entry(g)
    node = _m2.grant(g, create, holder=(create, "entity"), currency_id=currency_id,
                     amount=amount, currency_slot=currency_slot, alias="grant")
    _exit(g, node, text or block_text("M2-currency", "GRANT"), "exit")
    return g


def currency_gate_block(*, currency_id: int = CURRENCY_ID, threshold: int = 100,
                        currency_slot: str = "int", text_true: str | None = None,
                        text_false: str | None = None, name: str | None = None) -> Graph:
    """``71`` → ``691 获取背包货币数量`` → ``233 数值大于等于`` → ``双分支`` → two ``打印`` exits.

    The data leg (``691 → 233``) is placed by :func:`modules.currency.read_and_compare`;
    the exec leg (``71.then → 双分支``) and the two print exits are added here.
    """
    g = Graph(_name("M2_GATE", name))
    create = _entry(g)
    cmp_ = _m2.read_and_compare(g, holder=(create, "entity"), currency_id=currency_id,
                                threshold=threshold, currency_slot=currency_slot,
                                alias="enough")
    branch = g.place(BRANCH, "branch")  # 2 双分支
    create.flow_to(branch)
    branch.data_from(cmp_, "result", "condition")
    _exit(g, branch, text_true or block_text("M2-currency", "ENOUGH"),
          "exit_true", from_role="true")
    _exit(g, branch, text_false or block_text("M2-currency", "SHORT"),
          "exit_false", from_role="false")
    return g


def currency_event_block(*, text: str | None = None, name: str | None = None) -> Graph:
    """``684 背包货币数量变化时`` (entry) → ``打印字符串`` (exit)."""
    g = Graph(_name("M2_EVENT", name))
    changed = _m2.on_changed(g, "changed")
    _exit(g, changed, text or block_text("M2-currency", "CHANGED"), "exit")
    return g


# ---------------------------------------------------------------------------
# M3 — item
# ---------------------------------------------------------------------------

def item_grant_block(*, item_id: int = ITEM_ID, count: int = 1,
                     item_slot: str = "int", text: str | None = None,
                     name: str | None = None) -> Graph:
    """``71`` (entry) → ``686 增加背包道具数量`` → ``打印字符串`` (exit)."""
    g = Graph(_name("M3_GRANT", name))
    create = _entry(g)
    node = _m3.grant(g, create, holder=(create, "entity"), item_id=item_id,
                     count=count, item_slot=item_slot, alias="grant")
    _exit(g, node, text or block_text("M3-item", "GRANT"), "exit")
    return g


def item_gate_block(*, item_id: int = ITEM_ID, threshold: int = 2,
                    item_slot: str = "int", text_true: str | None = None,
                    text_false: str | None = None, name: str | None = None) -> Graph:
    """``71`` → ``690 获取背包道具数量`` → ``233`` → ``双分支`` → two ``打印`` exits."""
    g = Graph(_name("M3_GATE", name))
    create = _entry(g)
    cmp_ = _m3.has_enough(g, holder=(create, "entity"), item_id=item_id,
                          threshold=threshold, item_slot=item_slot, alias="enough")
    branch = g.place(BRANCH, "branch")
    create.flow_to(branch)
    branch.data_from(cmp_, "result", "condition")
    _exit(g, branch, text_true or block_text("M3-item", "ENOUGH"),
          "exit_true", from_role="true")
    _exit(g, branch, text_false or block_text("M3-item", "SHORT"),
          "exit_false", from_role="false")
    return g


#: item event wrapper -> (module function, defId).  681/682/683/733.
ITEM_EVENTS: dict[str, tuple[Callable, int]] = {
    "added": (_m3.on_added, 681),
    "lost": (_m3.on_lost, 682),
    "changed": (_m3.on_changed, 683),
    "used": (_m3.on_used, 733),
}


def item_event_block(kind: str = "added", *, text: str | None = None,
                     name: str | None = None) -> Graph:
    """``681/682/683/733`` (entry) → ``打印字符串`` (exit)."""
    func, def_id = ITEM_EVENTS[kind]
    g = Graph(_name(f"M3_EVENT_{kind.upper()}", name))
    event = func(g, "event")
    _exit(g, event, text or block_text("M3-item", kind.upper()), "exit")
    assert event.ntype.definition_id == def_id
    return g


# ---------------------------------------------------------------------------
# M4 — inventory
# ---------------------------------------------------------------------------

def inventory_grow_block(*, amount: int = 10, text: str | None = None,
                         name: str | None = None) -> Graph:
    """``71`` (entry) → ``685 增加背包最大容量`` → ``打印字符串`` (exit)."""
    g = Graph(_name("M4_GROW", name))
    create = _entry(g)
    node = _m4.grow(g, create, holder=(create, "entity"), amount=amount, alias="grow")
    _exit(g, node, text or block_text("M4-inventory", "GROW"), "exit")
    return g


def inventory_capacity_block(*, threshold: int = 20, text_true: str | None = None,
                             text_false: str | None = None,
                             name: str | None = None) -> Graph:
    """``71`` → ``689 获取背包容量`` → ``230 数值小于`` → ``双分支`` → two ``打印`` exits."""
    g = Graph(_name("M4_CAPACITY", name))
    create = _entry(g)
    cmp_ = _m4.capacity_gate(g, holder=(create, "entity"), threshold=threshold,
                             alias="low", compare="lt")
    branch = g.place(BRANCH, "branch")
    create.flow_to(branch)
    branch.data_from(cmp_, "result", "condition")
    _exit(g, branch, text_true or block_text("M4-inventory", "NEARLY_FULL"),
          "exit_true", from_role="true")
    _exit(g, branch, text_false or block_text("M4-inventory", "ROOMY"),
          "exit_false", from_role="false")
    return g


def _dict_query_block(
    func: Callable, def_id: int, *, tag: str, key: int, threshold: int,
    assume_generic_accessor: bool, text_true: str | None, text_false: str | None,
    name: str | None,
) -> Graph:
    """Shared shape for ``721``/``722``: place the query, then consume or refuse.

    Without ``assume_generic_accessor`` the block stops at the obstacle and raises
    :class:`DictAccessUnproven` (carrying the partial graph).  With it, the block is
    completed through the generic accessor ``1158`` — an **ASSUMED** wiring (generic
    pins, never placed) — into ``233`` → ``双分支`` → two print exits.
    """
    g = Graph(_name(f"M4_{tag.upper()}", name))
    create = _entry(g)
    query = func(g, holder=(create, "entity"), alias="all")
    if not assume_generic_accessor:
        raise DictAccessUnproven(def_id, 0, graph=g)

    lookup = g.place(DICT_LOOKUP, "lookup")  # 1158 — generic pins (ASSUMED)
    lookup.data_from(query, "items" if def_id == 721 else "currencies", "dict")
    lookup.const("key", int(key), "int")
    cmp_ = g.place(GE, "enough")  # 233 数值大于等于
    cmp_.data_from(lookup, "value", "left")
    cmp_.const("right", int(threshold), "int")
    branch = g.place(BRANCH, "branch")
    create.flow_to(branch)
    branch.data_from(cmp_, "result", "condition")
    _exit(g, branch, text_true or block_text("M4-inventory", f"{tag.upper()}_YES"),
          "exit_true", from_role="true")
    _exit(g, branch, text_false or block_text("M4-inventory", f"{tag.upper()}_NO"),
          "exit_false", from_role="false")
    return g


def inventory_all_items_block(*, key: int = 0, threshold: int = 1,
                              assume_generic_accessor: bool = False,
                              text_true: str | None = None, text_false: str | None = None,
                              name: str | None = None) -> Graph:
    """``721 获取背包所有基础道具`` — BLOCKED at the concrete type-27 dict by default."""
    return _dict_query_block(
        _m4.all_items, 721, tag="all_items", key=key, threshold=threshold,
        assume_generic_accessor=assume_generic_accessor,
        text_true=text_true, text_false=text_false, name=name,
    )


def inventory_all_currencies_block(*, key: int = 0, threshold: int = 1,
                                   assume_generic_accessor: bool = False,
                                   text_true: str | None = None,
                                   text_false: str | None = None,
                                   name: str | None = None) -> Graph:
    """``722 获取背包所有货币`` — BLOCKED at the concrete type-27 dict by default."""
    return _dict_query_block(
        _m4.all_currencies, 722, tag="all_currencies", key=key, threshold=threshold,
        assume_generic_accessor=assume_generic_accessor,
        text_true=text_true, text_false=text_false, name=name,
    )


# ---------------------------------------------------------------------------
# M5 — shop
# ---------------------------------------------------------------------------

def shop_open_block(*, shop_index: int = 0, text: str | None = None,
                    name: str | None = None) -> Graph:
    """``71`` (entry) → ``702 打开商店`` → ``打印字符串`` (exit).

    Scene half: ``702`` acts on a 商店组件 that must sit on an entity — the same
    missing add-component primitive as M1.  The block builds; the store half is an
    editor step.
    """
    g = Graph(_name("M5_OPEN", name))
    create = _entry(g)
    node = _m5.open_(g, create, player=(create, "entity"),
                     shop_owner=(create, "entity"), shop_index=shop_index, alias="open")
    _exit(g, node, text or block_text("M5-shop", "OPEN"), "exit")
    return g


def shop_close_block(*, text: str | None = None, name: str | None = None) -> Graph:
    """``71`` (entry) → ``703 关闭商店`` → ``打印字符串`` (exit)."""
    g = Graph(_name("M5_CLOSE", name))
    create = _entry(g)
    node = _m5.close(g, create, player=(create, "entity"), alias="close")
    _exit(g, node, text or block_text("M5-shop", "CLOSE"), "exit")
    return g


def shop_sold_event_block(*, currency_id: int = CURRENCY_ID, unit_price: int = 5,
                          currency_slot: str = "int", payee: str = "shop_owner",
                          text: str | None = None, name: str | None = None) -> Graph:
    """Observe an engine-settled bag-shop sale without paying a second time."""
    g = Graph(_name("M5_SOLD", name))
    event = _m5.on_bag_item_sold(g, alias="sold")
    _exit(g, event, text or block_text("M5-shop", "SOLD"), "exit")
    return g


def shop_bought_event_block(*, currency_id: int = CURRENCY_ID, unit_price: int = 5,
                            currency_slot: str = "int", seller: str = "seller",
                            text: str | None = None, name: str | None = None) -> Graph:
    """Observe an engine-settled purchase without debiting the seller again."""
    g = Graph(_name("M5_BOUGHT", name))
    event = _m5.acquire_and_pay(g, alias="bought")
    _exit(g, event, text or block_text("M5-shop", "BOUGHT"), "exit")
    return g


def shop_bought_trigger_block(*, text: str | None = None,
                              name: str | None = None) -> Graph:
    """``705 商店收购道具时`` (entry) → ``打印字符串`` (exit).

    The bare *trigger* half of the buy event: ``705`` is an event (exec output, no
    exec input), so it **is** the entry and the block is complete on its own.
    :func:`shop_bought_event_block` chains the settle (``688``) onto the same
    event; this one isolates the module function ``shop.on_shop_bought`` so its
    coverage is explicit rather than implied by the chained block.
    """
    g = Graph(_name("M5_BOUGHT_TRIGGER", name))
    event = _m5.on_shop_bought(g, "bought")
    _exit(g, event, text or block_text("M5-shop", "BOUGHT_TRIGGER"), "exit")
    return g


def shop_sold_trigger_block(*, text: str | None = None,
                            name: str | None = None) -> Graph:
    """``701 商店出售背包物品时`` (entry) → ``打印字符串`` (exit).

    The trigger half of the sell event; ``701`` is the entry.  Mirrors
    :func:`shop_bought_trigger_block` and isolates ``shop.on_sold_bag_item``.
    """
    g = Graph(_name("M5_SOLD_TRIGGER", name))
    event = _m5.on_sold_bag_item(g, "sold")
    _exit(g, event, text or block_text("M5-shop", "SOLD_TRIGGER"), "exit")
    return g


def shop_list_item_block(*, store: str = _m5.STORE_BAG_ADD, shop_index: int = 0,
                         item_id: int = ITEM_ID, item_slot: str = "int",
                         tab_index: int = 1, price: object | None = None,
                         item_index: int | None = None, flag_slot: str = "enum",
                         limit_count: int | None = None,
                         text: str | None = None, name: str | None = None) -> Graph:
    """Create/edit a priced custom or bag-shop row and emit a completion note."""
    g = Graph(_name("M5_LIST", name))
    create = _entry(g)
    try:
        node = _m5.list_item_for_sale(
            g, create, shop_owner=(create, "entity"), shop_index=shop_index,
            item_id=item_id, item_slot=item_slot, store=store, tab_index=tab_index,
            price=price, item_index=item_index, flag_slot=flag_slot,
            limit_count=limit_count, alias="list",
        )
    except _m5.DictPinUnsupported as error:
        # Attach the partial block (entry placed, writer refused) so the caller can
        # inspect how far it got -- the same shape as the BlockError refusals.
        error.graph = g
        raise
    _exit(g, node, text or block_text("M5-shop", "LIST"), "exit")
    return g


def shop_query_block(kind: str = "bag", *, shop_index: int | None = 0,
                     name: str | None = None) -> Graph:
    """``714/715`` 出售表查询 — BLOCKED: the aggregate output has no accessor.

    Raises :class:`ShopAggregateUnreadable` (carrying the partial graph: the entry
    and the query node).  ``kind`` selects ``"bag"`` (``715``, output type 22) or
    ``"custom"`` (``714``, output type 8).
    """
    if kind not in ("bag", "custom"):
        raise KeyError(f"unknown query kind {kind!r}; known: ['bag', 'custom']")
    g = Graph(_name(f"M5_QUERY_{kind.upper()}", name))
    create = _entry(g)
    if kind == "bag":
        node = _m5.query_bag_sales(g, holder=(create, "entity"), alias="query",
                                   shop_index=shop_index)
        out_type = 22
    else:
        node = _m5.query_custom_sales(g, holder=(create, "entity"), alias="query",
                                      shop_index=shop_index)
        out_type = 8
    raise ShopAggregateUnreadable(node.ntype.definition_id, 0, out_type, graph=g)


# ---------------------------------------------------------------------------
# M6 — terrain / level (no node half)
# ---------------------------------------------------------------------------

def terrain_block() -> Graph:
    """M6 cannot be a node block at all.  Always raises."""
    raise TerrainHasNoNodeBlock()


# ---------------------------------------------------------------------------
# The registry and the derived completion table
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModuleBlock:
    """One named block: the module function it makes self-contained, and how to build."""

    module: str
    function: str
    build: Callable[[], Graph]
    functions_made_real: tuple[str, ...]
    obstacle: str = ""
    refusal: type | None = None
    scene_half: str = ""


def _blocks() -> tuple[ModuleBlock, ...]:
    m1, m2, m3, m4, m5 = "M1-interaction", "M2-currency", "M3-item", "M4-inventory", "M5-shop"
    scene_component = ("needs a 碰撞触发器/界面控件组/悬浮交互页 authored in the editor "
                       "(no component writer) — the graph half is complete")
    scene_shop = ("needs a 商店组件 on an entity authored in the editor "
                  "(no component writer) — the graph half is complete")
    out: list[ModuleBlock] = []
    for key, kind in _m1.KINDS.items():
        out.append(ModuleBlock(
            m1, f"interaction.event[{key}]",
            (lambda k=kind: interaction_event_block(k)),
            ("interaction.event", f"interaction.{KIND_FUNCTION[key]}"),
            scene_half=scene_component,
        ))
    # NOTE: this block makes NO module fragment real — node 90 has no
    # ``modules/interaction.py`` function wrapping it.  ``functions_made_real`` is
    # therefore empty, NOT a hand-typed name: a block-local helper name here would
    # (i) count as a "covered module function" that does not exist and (ii) hide the
    # real surface from the mechanical guard in ``tests/test_module_blocks.py``.
    out.append(ModuleBlock(m1, "interaction.activate_block",
                           interaction_activate_block,
                           (), scene_half=scene_component))
    # The text-bubble entry's action half (679's sibling 631), mirroring
    # interaction_activate_block for the proximity entry.
    out.append(ModuleBlock(m1, "interaction.switch_bubble_block",
                           interaction_switch_bubble_block,
                           ("interaction.switch_text_bubble",),
                           scene_half=scene_component))
    out += [
        ModuleBlock(m2, "currency.grant", currency_grant_block, ("currency.grant",)),
        ModuleBlock(m2, "currency.read_and_compare", currency_gate_block,
                    ("currency.read_and_compare", "currency.read", "currency.at_least")),
        ModuleBlock(m2, "currency.on_changed", currency_event_block,
                    ("currency.on_changed",)),
        ModuleBlock(m3, "item.grant", item_grant_block, ("item.grant",)),
        ModuleBlock(m3, "item.has_enough", item_gate_block,
                    ("item.has_enough", "item.read")),
    ]
    for kind, (_func, _def) in ITEM_EVENTS.items():
        out.append(ModuleBlock(
            m3, f"item.on_{kind}",
            (lambda k=kind: item_event_block(k)),
            (f"item.on_{kind}",),
        ))
    out += [
        ModuleBlock(m4, "inventory.grow", inventory_grow_block,
                    ("inventory.grow", "inventory.grow_then")),
        ModuleBlock(m4, "inventory.capacity_gate", inventory_capacity_block,
                    ("inventory.capacity_gate", "inventory.capacity")),
        ModuleBlock(m4, "inventory.all_items", inventory_all_items_block,
                    ("inventory.all_items",),
                    obstacle="721 returns a concrete type-27 dict; the accessor 1158 "
                             "has fully generic pins and has never been placed",
                    refusal=DictAccessUnproven),
        ModuleBlock(m4, "inventory.all_currencies", inventory_all_currencies_block,
                    ("inventory.all_currencies",),
                    obstacle="722 returns a concrete type-27 dict; the accessor 1158 "
                             "has fully generic pins and has never been placed",
                    refusal=DictAccessUnproven),
        ModuleBlock(m5, "shop.open_", shop_open_block, ("shop.open_",), scene_half=scene_shop),
        ModuleBlock(m5, "shop.close", shop_close_block, ("shop.close",), scene_half=scene_shop),
        ModuleBlock(m5, "shop.on_bag_item_sold", shop_sold_event_block,
                    ("shop.on_bag_item_sold",)),
        ModuleBlock(m5, "shop.acquire_and_pay", shop_bought_event_block,
                    ("shop.acquire_and_pay",)),
        ModuleBlock(m5, "shop.on_shop_bought", shop_bought_trigger_block,
                    ("shop.on_shop_bought",)),
        ModuleBlock(m5, "shop.on_sold_bag_item", shop_sold_trigger_block,
                    ("shop.on_sold_bag_item",)),
        ModuleBlock(m5, "shop.list_item_for_sale[bag]", shop_list_item_block,
                    ("shop.list_item_for_sale",), scene_half=scene_shop),
        ModuleBlock(m5, "shop.list_item_for_sale[custom]",
                    (lambda: shop_list_item_block(store=_m5.STORE_CUSTOM,
                                                 item_index=0, price={CURRENCY_ID: 5})),
                    ("shop.list_item_for_sale",),
                    scene_half=scene_shop),
        ModuleBlock(m5, "shop.query_bag_sales",
                    (lambda: shop_query_block("bag")), ("shop.query_bag_sales",),
                    obstacle="715 returns an opaque aggregate (serverParamType 22) with "
                             "no accessor anywhere in the store",
                    refusal=ShopAggregateUnreadable),
        ModuleBlock(m5, "shop.query_custom_sales",
                    (lambda: shop_query_block("custom")), ("shop.query_custom_sales",),
                    obstacle="714 returns an opaque aggregate (serverParamType 8) with "
                             "no accessor anywhere in the store",
                    refusal=ShopAggregateUnreadable),
        ModuleBlock("M6-level-terrain", "terrain_block", terrain_block, (),
                    obstacle="0 terrain instruction nodes in the census; terrain is an "
                             "editor concept (.gil field 7 / TILEMAP), not a node graph",
                    refusal=TerrainHasNoNodeBlock),
    ]
    return tuple(out)


MODULE_BLOCKS: tuple[ModuleBlock, ...] = _blocks()


def refusal_location(exc_type: type) -> str:
    """``<repo-relative file>:<line>`` for a named refusal class (any class)."""
    try:
        line = inspect.getsourcelines(exc_type)[1]
        source = Path(inspect.getsourcefile(exc_type) or "").resolve()
        try:
            rel = source.relative_to(_REPO_ROOT)
        except ValueError:
            rel = source
    except (OSError, TypeError):  # pragma: no cover - source always present here
        return f"<unknown>:{getattr(exc_type, '__name__', exc_type)}"
    return f"{rel.as_posix()}:{line}"


@dataclass(frozen=True)
class BlockAttempt:
    """The outcome of building one :class:`ModuleBlock`."""

    module: str
    function: str
    status: str                 # "COMPLETE" | "REFUSED" | "MALFORMED" | "ERROR"
    nodes: tuple[int, ...]
    detail: str = ""
    refusal: str = ""
    #: Concrete data inputs left unwired — a COMPLETE block can still carry
    #: these; see :func:`unwired_concrete_inputs` (ledger gap (c)).
    unwired: tuple[str, ...] = ()


def attempt(block: ModuleBlock) -> BlockAttempt:
    """Build, validate and shape-check one block — never raising."""
    try:
        graph = block.build()
    except (BlockError, _m5.DictPinUnsupported) as error:
        nodes = tuple(getattr(error, "nodes", ())) or _partial_nodes(
            getattr(error, "graph", None))
        return BlockAttempt(
            block.module, block.function, "REFUSED", nodes,
            detail=str(error),
            refusal=type(error).__name__,
        )
    except Exception as error:  # noqa: BLE001 - reported, never raised
        return BlockAttempt(block.module, block.function, "ERROR", (), detail=str(error))
    try:
        graph.validate()
    except Exception as error:  # noqa: BLE001
        return BlockAttempt(
            block.module, block.function, "MALFORMED",
            tuple(n.definition_id for n in graph.plan.nodes), detail=str(error),
        )
    nodes = tuple(n.definition_id for n in graph.plan.nodes)
    shape = block_shape(graph.plan)
    if not shape.well_formed:
        return BlockAttempt(
            block.module, block.function, "MALFORMED", nodes,
            detail=f"shape entry={shape.entry} exits={shape.exits} "
                   f"unreachable={shape.unreachable}",
        )
    return BlockAttempt(block.module, block.function, "COMPLETE", nodes,
                        unwired=unwired_concrete_inputs(graph.plan))


def completion_table() -> list[dict]:
    """A per-module COMPLETE / PARTIAL / BLOCKED verdict, derived from the blocks.

    A module is **BLOCKED** when every one of its blocks refuses, **PARTIAL** when
    some refuse, **COMPLETE** otherwise.  ``nodeIds`` is the union of every defId the
    module's blocks place; ``refusals`` names each named error with its file:line.
    """
    rows: list[dict] = []
    for module in MODULE_ORDER:
        blocks = [b for b in MODULE_BLOCKS if b.module == module]
        attempts = [attempt(b) for b in blocks]
        statuses = {a.status for a in attempts}
        node_ids = sorted({n for a in attempts for n in a.nodes})
        refusals = sorted({a.refusal for a in attempts if a.refusal})
        locations = []
        for b in blocks:
            if b.refusal is not None:
                locations.append(f"{b.refusal.__name__} @ {refusal_location(b.refusal)}")
        if statuses == {"REFUSED"}:
            verdict = "BLOCKED"
        elif "REFUSED" in statuses:
            verdict = "PARTIAL"
        elif "MALFORMED" in statuses or "ERROR" in statuses:
            verdict = "MALFORMED"
        else:
            verdict = "COMPLETE"
        scene_half = sorted({b.scene_half for b in blocks if b.scene_half})
        rows.append({
            "module": module,
            "verdict": verdict,
            "nodeIds": node_ids,
            "blocks": [
                {"function": a.function, "status": a.status,
                 "nodes": list(a.nodes), "refusal": a.refusal}
                for a in attempts
            ],
            "refusals": sorted(set(locations)),
            "obstacles": sorted({b.obstacle for b in blocks if b.obstacle}),
            "unwiredConcreteInputs": sorted(
                {u for a in attempts for u in a.unwired}
            ),
            "sceneHalf": scene_half[0] if scene_half else "",
        })
    return rows


__all__ = [
    "BUBBLE_ID",
    "CURRENCY_ID",
    "DICT_LOOKUP",
    "ITEM_EVENTS",
    "ITEM_ID",
    "KIND_FUNCTION",
    "MODULE_BLOCKS",
    "MODULE_ORDER",
    "BlockAttempt",
    "BlockError",
    "BlockShape",
    "DictAccessUnproven",
    "LootPickupHasNoEventNode",
    "ModuleBlock",
    "ShopAggregateUnreadable",
    "TerrainHasNoNodeBlock",
    "attempt",
    "block_shape",
    "block_text",
    "completion_table",
    "currency_event_block",
    "currency_gate_block",
    "currency_grant_block",
    "entry_aliases",
    "exit_aliases",
    "interaction_activate_block",
    "interaction_event_block",
    "interaction_switch_bubble_block",
    "inventory_all_currencies_block",
    "inventory_all_items_block",
    "inventory_capacity_block",
    "inventory_grow_block",
    "item_event_block",
    "item_gate_block",
    "item_grant_block",
    "loot_pickup_block",
    "reachable_aliases",
    "refusal_location",
    "shop_bought_event_block",
    "shop_bought_trigger_block",
    "shop_close_block",
    "shop_list_item_block",
    "shop_open_block",
    "shop_query_block",
    "shop_sold_event_block",
    "shop_sold_trigger_block",
    "terrain_block",
    "unwired_concrete_inputs",
]
