"""Derived six-module coverage: which of the six directions a plan *genuinely* exercises.

Why a module of its own
-----------------------
Several demos report a ``coveredModules`` list.  Today every one of them derives it
the same loose way: *"does the plan place any node whose definitionId is in this
module's node set?"* — a membership test that says nothing about whether the node is
**reachable from the entry** or **free of a blocked primitive**.  That test is exactly
what would let a plan claim a module by parking a dead node in a corner.

This module makes the criterion explicit and checkable.  A module counts as covered
**iff** the plan places at least one node that is ALL THREE of:

1. **its own fragment** — the definitionId is in :data:`MODULE_NODE_IDS` (derived
   from :mod:`tools.gameplan.nodes` and the ``shop`` module's own node tables, never
   hand-typed);
2. **not a blocked primitive** — the definitionId is not in
   :func:`blocked_definition_ids` (derived from the three tables that record what the
   project cannot author: the interaction kinds' ``scene_half``, the farming-minimal
   event sources' ``manual_steps``, and the whole shop family);
3. **reachable from the entry** — the node is downstream of the plan's single event
   node over the plan's own exec/data edges, AND is not itself an event (a second
   event is not *reached*, it is another entry).

The third clause is the one the loose test omits.  It is what stops an **event** node
(e.g. ``92 进入碰撞触发器时``) from being counted: an event has no execution input, so
it can never be a flow target — placing one makes a *second* entry, not a node the
``71`` entry reaches.  That is the structural reason **M1 is uncoverable** by an
entry-``71`` graph even before its component blocker is considered, and the reason
**M6** (``frozenset()`` — no node half at all) is uncoverable too.

Nothing here touches the bridge, the game, the editor or a save.  It reads a
:class:`~tools.gameplan.plan.GraphPlan` and ``data/node-contracts`` only.
"""

from __future__ import annotations

from . import contracts
from .contracts import ContractStore
from .nodes import (
    ADD_BAG_CAPACITY,
    ADD_BAG_CURRENCY,
    ADD_BAG_ITEM,
    BAG_CURRENCY_CHANGED,
    BAG_ITEM_ADDED,
    BAG_ITEM_CHANGED,
    BAG_ITEM_LOST,
    BAG_ITEM_USED,
    CLOSE_SHOP,
    FLOATING_PAGE_TRIGGERED,
    GET_ALL_BAG_CURRENCIES,
    GET_ALL_BAG_ITEMS,
    GET_BAG_CAPACITY,
    GET_BAG_CURRENCY,
    GET_BAG_ITEM,
    OPEN_SHOP,
    PROXIMITY_ENTER,
    PROXIMITY_LEAVE,
    SHOP_BOUGHT_ITEM,
    SHOP_SOLD_BAG_ITEM,
    UI_CONTROL_TRIGGERED,
)
from .demo import farming_minimal as _farming_minimal
from .modules import interaction as _m1
from .modules import shop as _m5
from .plan import GraphPlan

# ---------------------------------------------------------------------------
# The module -> definitionId table.  Every set is derived from a role table
# already in the tree; the M6 entry is the empty set *because the tree declares
# no M6 node role* (nodes.py has no terrain/placement node), which is itself a
# derived fact, not a placeholder.
# ---------------------------------------------------------------------------

MODULE_NODE_IDS: dict[str, frozenset[int]] = {
    "M1-interaction": frozenset(k.event_definition_id for k in _m1.KINDS.values()),
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
            *_m5.SHOP_TABLE_NODE_TYPES,
            *_m5.SHOP_QUERY_NODE_TYPES,
        )
    ),
    # M6 (地块 / terrain + placement) has NO node half: terrain has no node role
    # and placement is a scene action (entity.create by coordinate), not a node.
    # The empty set is the derived statement of that, so the six-module count is
    # honest (6 modules enumerated, one with zero expressible nodes).
    "M6-level-terrain": frozenset(),
}

#: Module order is fixed by :data:`MODULE_NODE_IDS`; helpers preserve it.
MODULE_ORDER: tuple[str, ...] = tuple(MODULE_NODE_IDS)


def blocked_definition_ids() -> frozenset[int]:
    """DefinitionIds whose placement needs an editor asset this project cannot author.

    Derived, never typed (the same three clauses as
    :func:`tools.gameplan.demo.farming_runnable.blocked_definition_ids`, kept here so a
    core module needs no demo import):

    1. every interaction event whose recorded ``scene_half`` is non-empty
       (``92/91/316/826`` — a component/UI the bridge cannot author);
    2. every event source whose ``manual_steps`` is non-empty (``315/733`` + the four
       above — an editor asset is a precondition of the event itself);
    3. the whole shop family — its nodes act on a ``商店组件`` that must sit on an
       entity, the same missing add-component primitive.
    """
    ids: set[int] = set()
    ids |= {k.event_definition_id for k in _m1.KINDS.values() if k.scene_half}
    ids |= {
        s.definition_id
        for s in _farming_minimal.EVENT_SOURCES.values()
        if s.manual_steps
    }
    ids |= {
        t.definition_id
        for t in (
            OPEN_SHOP,
            CLOSE_SHOP,
            SHOP_SOLD_BAG_ITEM,
            SHOP_BOUGHT_ITEM,
            *_m5.SHOP_TABLE_NODE_TYPES,
            *_m5.SHOP_QUERY_NODE_TYPES,
        )
    }
    return frozenset(ids)


#: The frozen derivation, so a caller (and the test) reads one object.
BLOCKED_DEFINITION_IDS: frozenset[int] = blocked_definition_ids()


def definition_ids(plan: GraphPlan) -> frozenset[int]:
    """Every ``definitionId`` the plan places."""
    return frozenset(n.definition_id for n in plan.nodes)


def entry_aliases(plan: GraphPlan, store: ContractStore | None = None) -> tuple[str, ...]:
    """The plan's event nodes: a contract with an execution output and no exec input."""
    store = store or contracts.default_store()
    return tuple(
        n.alias
        for n in plan.nodes
        if store.require(n.definition_id).exec_outputs
        and not store.require(n.definition_id).exec_inputs
    )


def reachable_aliases(plan: GraphPlan, store: ContractStore | None = None) -> frozenset[str]:
    """Every alias downstream of the plan's single entry over its own edges.

    A plan with zero or more than one event node is ambiguous (which event is "the"
    entry?), so this raises :class:`ValueError` rather than guessing.  The walk
    follows every edge in the plan — execution edges (2->1) and data edges (4->3)
    alike — because a data node fed by the entry is reached by it too.
    """
    store = store or contracts.default_store()
    entries = entry_aliases(plan, store)
    if len(entries) != 1:
        raise ValueError(
            f"expected exactly one entry node (exec output, no exec input); "
            f"found {list(entries)!r}"
        )
    reached: set[str] = {entries[0]}
    changed = True
    while changed:
        changed = False
        for edge in plan.edges:
            if edge.src in reached and edge.dst not in reached:
                reached.add(edge.dst)
                changed = True
    return frozenset(reached)


def module_coverage(
    plan: GraphPlan,
    *,
    blocked: frozenset[int] | None = None,
    store: ContractStore | None = None,
) -> dict[str, frozenset[int]]:
    """For each module, the definitionIds of *that module* the plan genuinely covers.

    A definitionId is credited to a module only if it is reachable from the entry,
    is not itself an event node, and is not in ``blocked`` (defaults to the derived
    :data:`BLOCKED_DEFINITION_IDS`).  ``blocked`` is a parameter so a caller (and the
    test) can prove the result is *derived*: pass a different set and the answer moves.
    """
    store = store or contracts.default_store()
    excluded = BLOCKED_DEFINITION_IDS if blocked is None else blocked
    reached = reachable_aliases(plan, store)
    credited: dict[str, set[int]] = {}
    for node in plan.nodes:
        if node.alias not in reached:
            continue
        if node.definition_id in excluded:
            continue
        defn = store.require(node.definition_id)
        if defn.exec_outputs and not defn.exec_inputs:
            continue  # an event node is another entry, not a node this entry reaches
        for module, ids in MODULE_NODE_IDS.items():
            if node.definition_id in ids:
                credited.setdefault(module, set()).add(node.definition_id)
    return {module: frozenset(credited.get(module, ())) for module in MODULE_ORDER}


def covered_modules(
    plan: GraphPlan,
    *,
    blocked: frozenset[int] | None = None,
    store: ContractStore | None = None,
) -> tuple[str, ...]:
    """The modules the plan genuinely covers, in :data:`MODULE_ORDER` order."""
    coverage = module_coverage(plan, blocked=blocked, store=store)
    return tuple(module for module in MODULE_ORDER if coverage[module])


def module_status(
    plan: GraphPlan,
    *,
    blocked: frozenset[int] | None = None,
    store: ContractStore | None = None,
) -> dict[str, str]:
    """Why each module is (or is not) covered — a per-module verdict a reader can trust.

    Verdicts: ``"covered"``; ``"no-node-half"`` (the module declares no node at all);
    ``"all-nodes-are-events"`` (every node is an event, so none can be reached from
    another entry); ``"all-nodes-blocked"`` (every node needs an absent primitive);
    ``"not-placed"`` (expressible, just not in this plan).
    """
    store = store or contracts.default_store()
    excluded = BLOCKED_DEFINITION_IDS if blocked is None else blocked
    coverage = module_coverage(plan, blocked=blocked, store=store)
    verdicts: dict[str, str] = {}
    for module, ids in MODULE_NODE_IDS.items():
        if coverage[module]:
            verdicts[module] = "covered"
            continue
        if not ids:
            verdicts[module] = "no-node-half"
            continue
        if all(
            store.require(i).exec_outputs and not store.require(i).exec_inputs
            for i in ids
        ):
            verdicts[module] = "all-nodes-are-events"
            continue
        if ids <= excluded:
            verdicts[module] = "all-nodes-blocked"
            continue
        verdicts[module] = "not-placed"
    return verdicts


__all__ = [
    "BLOCKED_DEFINITION_IDS",
    "MODULE_NODE_IDS",
    "MODULE_ORDER",
    "blocked_definition_ids",
    "covered_modules",
    "definition_ids",
    "entry_aliases",
    "module_coverage",
    "module_status",
    "reachable_aliases",
]
