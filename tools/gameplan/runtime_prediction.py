"""What the RUNNABLE demo *should* do — an offline execution prediction.

Why
---
The project's scorecard says **0 / 15 runtime behaviours verified** (``CLAUDE.md``
§五).  A graph was built, bound and saved on the machine; nobody has watched it
run, and a playtest is a human click.  Everything on *either* side of that click
has to be machine-checkable, or the click settles nothing.  This module is the
"before" side: it walks :mod:`tools.gameplan.demo.farming_runnable` from its entry
node and predicts, from the plan alone, **which nodes fire, in what order, and
which exact string each ``打印字符串`` (defId 1) prints**.

It is a *symbolic* evaluator, not a runtime.  It never dispatches, never loads a
save, never touches the editor or the game.  It reads the plan the same way a
player's eye would read the graph in the editor, and it produces a prediction
sharp enough to be falsified by one playtest.

The one semantic model (stated, because everything rests on it)
---------------------------------------------------------------
A ``获取…`` query node (``689``/``690``/``691``) reads a bag that a ``增加…``
writer node (``685``/``686``/``688``) mutated earlier in the same execution.  We
do **not** know the bag's starting amount, so the model evaluates the two ends of
the uncertainty — ``0`` (the write was inert / the id dangles) and ``delta`` (the
write landed) — and reports a branch as *decided* only when **both** give the same
arm.  For this demo they do (see :func:`predict`), which is why the prediction is
robust to the very thing we cannot yet observe.

Everything else is derived: the entry node comes from ``data/node-contracts``
(exec output, no exec input), the branch/compare/print ids come from
:mod:`tools.gameplan.nodes`, and the constants come from the plan.  Nothing in
the prediction is typed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from . import contracts
from .nodes import (
    ADD_BAG_CAPACITY,
    ADD_BAG_CURRENCY,
    ADD_BAG_ITEM,
    BRANCH,
    EQ,
    GET_BAG_CAPACITY,
    GET_BAG_CURRENCY,
    GET_BAG_ITEM,
    GE,
    GT,
    LE,
    LT,
    PRINT,
)
from .plan import GraphPlan

# ---------------------------------------------------------------------------
# The three family tables.  Each is keyed on a definitionId this project already
# declares in ``nodes.py``; the *pairing* (a query reads the family a writer
# writes) is read off the node names — 容量 / 道具 / 货币 — so it cannot drift
# silently: ``test_demo_runtime_prediction`` re-derives each family from the
# contract's port names and fails if these tables disagree.
# ---------------------------------------------------------------------------

#: ``获取…`` query defId -> family it reads.
READ_FAMILY: dict[int, str] = {
    GET_BAG_CAPACITY.definition_id: "capacity",
    GET_BAG_ITEM.definition_id: "item",
    GET_BAG_CURRENCY.definition_id: "currency",
}

#: ``增加…`` writer defId -> family it writes.
WRITE_FAMILY: dict[int, str] = {
    ADD_BAG_CAPACITY.definition_id: "capacity",
    ADD_BAG_ITEM.definition_id: "item",
    ADD_BAG_CURRENCY.definition_id: "currency",
}

#: comparison defId -> the predicate ``left OP right`` its ``result`` carries.
COMPARE_PREDICATE: dict[int, str] = {
    LT.definition_id: "lt",
    LE.definition_id: "le",
    GT.definition_id: "gt",
    GE.definition_id: "ge",
    EQ.definition_id: "eq",
}

_OPS = {
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "eq": lambda a, b: a == b,
}

#: The roles the adapter writes constants for.  A writer's delta lives on its
#: ``delta`` pin; a query's family key lives on the ``item`` / ``currency`` pin
#: (capacity has none).  Indices are taken from ``nodes.py`` (single source).
_DELTA_PORT = 2  # every writer in this demo declares delta at 3:2 ...
_CAPACITY_DELTA_PORT = 1  # ... except 685, whose delta is 3:1 (no config-id pin).
_READ_KEY_PORT = 1


@dataclass(frozen=True)
class Visit:
    """One node the prediction expects to *execute* (an execution-pin traversal)."""

    index: int
    alias: str
    definition_id: int


@dataclass(frozen=True)
class DataVisit:
    """One data-only node the prediction expects to *evaluate* on the way to a gate."""

    index: int
    alias: str
    definition_id: int


@dataclass(frozen=True)
class BranchDecision:
    """A ``双分支`` that must be reached, and which way it must go."""

    index: int
    alias: str
    condition_alias: str            # the compare node feeding ``condition``
    read_alias: str                 # the ``获取…`` node the compare reads
    family: str                     # capacity / item / currency
    predicate: str                  # lt / le / gt / ge / eq
    threshold: int                  # the compare's right-hand constant
    observed: tuple[int, ...]       # every candidate bag value the model considered
    taken: Literal["true", "false"]  # 是 / 否 arm the walk follows
    decided: bool                   # both candidate ends agree on ``taken``

    @property
    def arm(self) -> str:
        return "是" if self.taken == "true" else "否"


@dataclass(frozen=True)
class PrintCapture:
    """One ``打印字符串`` (defId 1) the prediction expects to fire.

    ``node_unique`` is the whole point: a captured string that appears on **exactly
    one** node in the plan *identifies* that node when the log-observer sees it
    (``observed``).  A string carried by two or more nodes cannot distinguish which
    one fired (``inferred``).  ``owners`` are the aliases carrying the exact text.
    """

    order: int
    index: int
    alias: str
    definition_id: int
    text: str
    node_unique: bool
    owners: tuple[str, ...]


@dataclass(frozen=True)
class BranchArm:
    """One arm of a ``双分支``: where it goes, and the leaf string if it is a print.

    ``leaf_text`` is set only when the arm's immediate successor **is** a
    ``打印字符串``; when the successor is another branch it stays ``None`` and
    ``successor_definition_id`` names it, so "no leaf" is never confused with "leaf".
    """

    branch_alias: str
    arm: str                    # "true" (是) | "false" (否)
    successor_alias: str | None
    successor_definition_id: int | None
    leaf_text: str | None


@dataclass(frozen=True)
class Prediction:
    """Everything one playtest can check, derived from the plan."""

    graph_name: str
    entry: Visit
    executed: tuple[Visit, ...]                 # exec-pin walk order
    evaluated_data: tuple[DataVisit, ...]       # data nodes evaluated, in dependency order
    prints: tuple[str, ...]                     # EXACT text, in firing order
    branches: tuple[BranchDecision, ...]
    unexercised: tuple[Visit, ...]              # nodes in the plan the run never reaches
    captures: tuple[PrintCapture, ...] = ()     # the prints, with their node-uniqueness
    branch_arms: tuple[BranchArm, ...] = ()     # every branch's two arms, planned-only

    @property
    def print_nodes(self) -> int:
        return sum(1 for v in self.executed if v.definition_id == PRINT.definition_id)

    @property
    def observed_able(self) -> tuple[str, ...]:
        """Predicted prints a capture would *attribute to a specific node* (unique)."""
        return tuple(c.text for c in self.captures if c.node_unique)


# ---------------------------------------------------------------------------
# Loading a plan's wiring
# ---------------------------------------------------------------------------

class _Wiring:
    """A plan pulled into the few maps the walker needs."""

    def __init__(self, plan: GraphPlan, store: contracts.ContractStore | None = None):
        self.plan = plan
        self.store = store or contracts.default_store()
        self.index: dict[str, int] = {n.alias: i for i, n in enumerate(plan.nodes)}
        self.defn: dict[str, int] = {n.alias: n.definition_id for n in plan.nodes}
        #: alias -> {out_index: dst_alias}, execution edges only (2->1).
        self.exec_out: dict[str, dict[int, str]] = {}
        #: (dst_alias, dst_index) -> (src_alias, src_index), data edges only (4->3).
        self.data_into: dict[tuple[str, int], tuple[str, int]] = {}
        #: alias -> {port_index: value}
        self.consts: dict[str, dict[int, object]] = {}
        for e in plan.edges:
            if e.src_kind == contracts.EXEC_OUTPUT and e.dst_kind == contracts.EXEC_INPUT:
                self.exec_out.setdefault(e.src, {})[e.src_index] = e.dst
            elif e.src_kind == contracts.DATA_OUTPUT and e.dst_kind == contracts.DATA_INPUT:
                self.data_into[(e.dst, e.dst_index)] = (e.src, e.src_index)
        for c in plan.consts:
            self.consts.setdefault(c.alias, {})[c.port_index] = c.value

    def entry_alias(self) -> str:
        """The graph's single event: a node contract with an exec output, no exec input."""
        entries = [
            n.alias
            for n in self.plan.nodes
            if (d := self.store.require(n.definition_id)).exec_outputs
            and not d.exec_inputs
        ]
        if len(entries) != 1:
            raise ValueError(
                f"expected exactly one entry node (exec output, no exec input); "
                f"found {entries!r}"
            )
        return entries[0]

    def const(self, alias: str, port: int, default=None):
        return self.consts.get(alias, {}).get(port, default)

    def has_exec_input(self, alias: str) -> bool:
        return bool(self.store.require(self.defn[alias]).exec_inputs)


# ---------------------------------------------------------------------------
# Data-node evaluation (the branch conditions)
# ---------------------------------------------------------------------------

def _writer_delta(w: "_Wiring", writer_alias: str, family: str) -> int | None:
    """The delta a writer adds to its family, or ``None`` if it is not written."""
    port = _CAPACITY_DELTA_PORT if family == "capacity" else _DELTA_PORT
    value = w.const(writer_alias, port)
    return None if value is None else int(value)


def _read_key(w: "_Wiring", read_alias: str, family: str) -> int | None:
    if family == "capacity":
        return None
    value = w.const(read_alias, _READ_KEY_PORT)
    return None if value is None else int(value)


def _family_for_writer(w: "_Wiring", writer_alias: str) -> str:
    return WRITE_FAMILY[w.defn[writer_alias]]


def _branch_decision(w: "_Wiring", branch_alias: str, exec_prefix: tuple[str, ...]) -> BranchDecision:
    """Resolve one ``双分支`` by reading its compare, the compare's query, and the
    earlier writer of the same family.

    ``exec_prefix`` is the execution chain walked *so far* (including the branch
    itself).  Only writers already on it count — a writer placed after the gate
    cannot have fed the gate.
    """
    cond = w.data_into.get((branch_alias, 0))
    if cond is None:
        raise ValueError(f"branch {branch_alias!r} has no condition wired")
    cmp_alias = cond[0]
    cmp_id = w.defn[cmp_alias]
    if cmp_id not in COMPARE_PREDICATE:
        raise ValueError(f"{cmp_alias!r} (defId {cmp_id}) is not a comparison node")

    left = w.data_into.get((cmp_alias, 0))
    if left is None:
        raise ValueError(f"comparison {cmp_alias!r} has no left operand wired")
    read_alias = left[0]
    read_id = w.defn[read_alias]
    if read_id not in READ_FAMILY:
        raise ValueError(f"{read_alias!r} (defId {read_id}) is not a 获取… query node")

    family = READ_FAMILY[read_id]
    predicate = COMPARE_PREDICATE[cmp_id]
    threshold = int(w.const(cmp_alias, 1))
    key = _read_key(w, read_alias, family)

    # The writers on the chain that could have moved this family's amount.
    writers = [
        a for a in exec_prefix
        if w.defn[a] in WRITE_FAMILY
        and _family_for_writer(w, a) == family
        and (key is None or _read_key(w, a, family) == key)
    ]
    if len(writers) > 1:
        raise ValueError(
            f"{len(writers)} writers of family {family!r} key={key!r} precede "
            f"{branch_alias!r}: {writers!r}; the model assumes at most one"
        )
    delta = _writer_delta(w, writers[0], family) if writers else None
    if len(writers) == 1 and delta is None:
        raise ValueError(f"writer {writers[0]!r} has no delta constant")

    # The two ends of the uncertainty: the write was inert (0) or it landed (delta).
    candidates = sorted({0, delta} if delta is not None else {0})
    op = _OPS[predicate]
    outcomes = {op(value, threshold) for value in candidates}
    decided = len(outcomes) == 1
    taken: Literal["true", "false"] = "true" if outcomes == {True} else "false"

    return BranchDecision(
        index=w.index[branch_alias],
        alias=branch_alias,
        condition_alias=cmp_alias,
        read_alias=read_alias,
        family=family,
        predicate=predicate,
        threshold=threshold,
        observed=tuple(candidates),
        taken=taken,
        decided=decided,
    )


# ---------------------------------------------------------------------------
# Capture identity: which strings *name their node*, and where each branch goes.
# ---------------------------------------------------------------------------

def string_owners(plan: GraphPlan) -> dict[str, tuple[str, ...]]:
    """Every string constant in the plan -> the aliases carrying that exact text.

    The map is the basis for "observed vs inferred": if a text has one owner, a log
    capture of it points at exactly one node; if it has two, the capture cannot tell
    which node produced it.
    """
    owners: dict[str, list[str]] = {}
    for spec in plan.consts:
        if spec.slot != "string":
            continue
        owners.setdefault(str(spec.value), []).append(spec.alias)
    return {text: tuple(aliases) for text, aliases in owners.items()}


def node_unique_strings(plan: GraphPlan) -> frozenset[str]:
    """The string constants carried by exactly one node — the *node-identifying* ones."""
    return frozenset(
        text for text, owners in string_owners(plan).items() if len(owners) == 1
    )


def branch_arms(plan: GraphPlan, store: contracts.ContractStore | None = None) -> tuple[BranchArm, ...]:
    """Every arm of every ``双分支``: its successor, and the leaf text if it prints.

    Reads the plan's execution edges only — no branch is evaluated.  This is the
    "expected captured output under each branch" table: an arm whose successor is a
    ``打印字符串`` records that exact string; an arm that leads to another branch
    records the branch's definitionId and leaves ``leaf_text`` ``None``.
    """
    w = _Wiring(plan, store)
    out: list[BranchArm] = []
    for node in plan.nodes:
        if node.definition_id != BRANCH.definition_id:
            continue
        for arm, out_index in (("true", 0), ("false", 1)):
            successor = w.exec_out.get(node.alias, {}).get(out_index)
            if successor is None:
                out.append(BranchArm(node.alias, arm, None, None, None))
                continue
            successor_id = w.defn[successor]
            text = w.const(successor, 0) if successor_id == PRINT.definition_id else None
            out.append(
                BranchArm(
                    node.alias,
                    arm,
                    successor,
                    successor_id,
                    None if text is None else str(text),
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------

def predict(plan: GraphPlan, store: contracts.ContractStore | None = None) -> Prediction:
    """Walk ``plan`` from its entry node and predict what one run fires.

    Raises :class:`ValueError` if the plan is not the shape this model understands
    (a second entry, an undecided branch, two writers of one family) — a loud
    failure beats a confident wrong prediction.
    """
    w = _Wiring(plan, store)
    entry = w.entry_alias()

    executed: list[Visit] = []
    evaluated_data: list[DataVisit] = []
    branches: list[BranchDecision] = []
    prints: list[str] = []
    seen: set[str] = set()

    alias: str | None = entry
    while alias is not None:
        if alias in seen:
            raise ValueError(f"execution cycle through {alias!r}; the demo is acyclic")
        seen.add(alias)
        defn = w.defn[alias]
        executed.append(Visit(w.index[alias], alias, defn))

        if defn == PRINT.definition_id:
            text = w.const(alias, 0)
            if text is None:
                raise ValueError(f"print node {alias!r} has no ``text`` constant")
            prints.append(str(text))

        if defn == BRANCH.definition_id:
            decision = _branch_decision(w, alias, tuple(v.alias for v in executed))
            branches.append(decision)
            evaluated_data.append(
                DataVisit(w.index[decision.condition_alias], decision.condition_alias,
                          w.defn[decision.condition_alias])
            )
            evaluated_data.append(
                DataVisit(w.index[decision.read_alias], decision.read_alias,
                          w.defn[decision.read_alias])
            )
            out_index = 0 if decision.taken == "true" else 1
        else:
            out_index = 0

        alias = w.exec_out.get(alias, {}).get(out_index)

    reached = {v.alias for v in executed} | {d.alias for d in evaluated_data}
    unexercised = tuple(
        Visit(i, n.alias, n.definition_id)
        for i, n in enumerate(plan.nodes)
        if n.alias not in reached
    )

    owners = string_owners(plan)
    captures: list[PrintCapture] = []
    for order, v in enumerate(executed):
        if v.definition_id != PRINT.definition_id:
            continue
        text = str(w.const(v.alias, 0))
        own = owners.get(text, (v.alias,))
        captures.append(
            PrintCapture(
                order=order,
                index=v.index,
                alias=v.alias,
                definition_id=v.definition_id,
                text=text,
                node_unique=len(own) == 1,
                owners=own,
            )
        )

    return Prediction(
        graph_name=plan.name,
        entry=executed[0],
        executed=tuple(executed),
        evaluated_data=tuple(evaluated_data),
        prints=tuple(prints),
        branches=tuple(branches),
        unexercised=unexercised,
        captures=tuple(captures),
        branch_arms=branch_arms(plan, store),
    )


# ---------------------------------------------------------------------------
# The written prediction + the honesty table (the things the run will NOT do)
# ---------------------------------------------------------------------------

#: What each family's *effect* depends on, and what happens when it is missing.
#: ``("inert", ...)`` means the node executes but changes nothing; ``("refused", ...)``
#: means its target (a bag component) does not exist, and the runtime may drop the
#: effect *or* abort the chain — we do not have evidence to pick one.
DEPENDENCY_NOTES: dict[str, tuple[str, str]] = {
    "capacity": (
        "refused-or-inert",
        "685 writes a 背包组件 the tool cannot attach (no add-component primitive, "
        "CLAUDE.md §六(a)); a bare created entity may carry no bag at all.",
    ),
    "item": (
        "inert",
        "crop config-id 1120000001 has no editor template instance (DEMO-GAP.md §二) "
        "⇒ the grant is a dangling reference: no such item exists to receive +1.",
    ),
    "currency": (
        "inert",
        "currency config-id 1115684864 has no editor template instance ⇒ dangling "
        "reference; the wallet gains nothing.",
    ),
}


def classify_capture(
    pred: Prediction, captured: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """Split a log capture against the prediction, by what it can *prove*.

    * ``observedNodes`` — captured strings that are **node-unique** in the plan and
      were predicted: each one pins a specific node, so the run *observed* it.
    * ``inferred`` — captured strings that were predicted but are **not** node-unique
      (two+ nodes carry the same text): the run produced them, but the capture cannot
      say which node did — the function is only *inferred*.
    * ``unexpected`` — captured strings not in the prediction at all.
    * ``missing`` — predicted strings the capture lacks.
    """
    seen = list(captured)
    predicted_unique = {c.text for c in pred.captures if c.node_unique}
    predicted_shared = {c.text for c in pred.captures if not c.node_unique}
    observed = tuple(t for t in seen if t in predicted_unique)
    inferred = tuple(t for t in seen if t in predicted_shared)
    unexpected = tuple(t for t in seen if t not in predicted_unique | predicted_shared)
    missing = tuple(t for t in pred.prints if t not in seen)
    return {
        "observedNodes": observed,
        "inferred": inferred,
        "unexpected": unexpected,
        "missing": missing,
    }


@dataclass(frozen=True)
class ModulePrint:
    """One predicted print, attributed to the module whose node led to it.

    A *module probe* graph (``demo/farming_module_probe.py``) places each module's
    node **immediately before** a distinct print node, so the print's predecessor
    in the execution walk names the module that ran.  ``module`` is ``None`` when
    the predecessor is not a known module node (e.g. the entry probe print, whose
    predecessor is the entry ``71``).
    """

    order: int                              # position in the exec walk (== PrintCapture.order)
    index: int                              # node index in the plan
    alias: str                              # the print node's alias
    text: str                               # the exact predicted string
    module: str | None                      # the module of the immediately-preceding node
    module_node_alias: str | None           # that preceding node's alias
    module_node_definition_id: int | None   # that preceding node's definitionId


def attribute_module_prints(
    pred: Prediction, module_for_definition_id: dict[int, str]
) -> tuple[ModulePrint, ...]:
    """Attribute each predicted print to the module of the executed node before it.

    ``module_for_definition_id`` maps a module's node ``definitionId`` to the module
    name (the probe module owns it; nothing is typed here).  The attribution is a
    pure function of the prediction — no runtime, no dispatch — so it is checkable
    offline, and a plan whose wiring changes moves it.
    """
    out: list[ModulePrint] = []
    for cap in pred.captures:
        lead = pred.executed[cap.order - 1] if cap.order > 0 else None
        out.append(
            ModulePrint(
                order=cap.order,
                index=cap.index,
                alias=cap.alias,
                text=cap.text,
                module=(module_for_definition_id.get(lead.definition_id)
                        if lead is not None else None),
                module_node_alias=lead.alias if lead is not None else None,
                module_node_definition_id=lead.definition_id if lead is not None else None,
            )
        )
    return tuple(out)


def module_print_map(
    pred: Prediction, module_for_definition_id: dict[int, str]
) -> dict[str, str]:
    """The predicted ``module -> printed string`` map for a module-probe graph.

    Raises :class:`ValueError` if one module leads to two prints (an ambiguous
    graph): a probe that can print two different lines for one module cannot
    attribute a capture, so the model refuses rather than guess.
    """
    out: dict[str, str] = {}
    for mp in attribute_module_prints(pred, module_for_definition_id):
        if mp.module is None:
            continue
        if mp.module in out:
            raise ValueError(
                f"module {mp.module!r} led to two prints: {out[mp.module]!r} and "
                f"{mp.text!r}; the model assumes one print per module"
            )
        out[mp.module] = mp.text
    return out


def narrative(pred: Prediction) -> list[str]:
    """The prediction as human lines — the sheet a playtest is compared against."""
    lines: list[str] = []
    lines.append(f"graph {pred.graph_name}")
    lines.append(
        f"entry {pred.entry.definition_id} ({pred.entry.alias}) fires when the bound "
        "entity is created"
    )
    lines.append("execution order:")
    for order, v in enumerate(pred.executed):
        kind = "PRINT" if v.definition_id == PRINT.definition_id else ""
        lines.append(f"  {order:2d} [{v.index:2d}] defId {v.definition_id:<3} {v.alias} {kind}".rstrip())
    for d in pred.evaluated_data:
        lines.append(f"       (data) [{d.index:2d}] defId {d.definition_id:<3} {d.alias}")
    for b in pred.branches:
        lines.append(
            f"branch {b.alias}: {b.family} {b.predicate} {b.threshold} over "
            f"{list(b.observed)} -> {b.arm} ({'decided' if b.decided else 'UNDECIDED'})"
        )
    lines.append("expected prints, in order:")
    for cap in pred.captures:
        tag = "OBSERVED-able" if cap.node_unique else f"INFERRED (owners={list(cap.owners)})"
        lines.append(f"  [{cap.index:2d}] {cap.alias}: {cap.text!r}  <- {tag}")
    lines.append("branch arms (planned, not evaluated):")
    for arm in pred.branch_arms:
        if arm.leaf_text is not None:
            dest = f"prints {arm.leaf_text!r}"
        elif arm.successor_alias is not None:
            dest = f"-> branch {arm.successor_alias} (defId {arm.successor_definition_id})"
        else:
            dest = "(unwired)"
        lines.append(f"  {arm.branch_alias}.{'是' if arm.arm == 'true' else '否'} {dest}")
    lines.append("NOT expected (never reached this config):")
    for v in pred.unexercised:
        if v.definition_id == PRINT.definition_id:
            lines.append(f"  [{v.index:2d}] {v.alias}")
    return lines


__all__ = [
    "BranchArm",
    "BranchDecision",
    "COMPARE_PREDICATE",
    "DEPENDENCY_NOTES",
    "DataVisit",
    "ModulePrint",
    "Prediction",
    "PrintCapture",
    "READ_FAMILY",
    "Visit",
    "WRITE_FAMILY",
    "attribute_module_prints",
    "branch_arms",
    "classify_capture",
    "module_print_map",
    "narrative",
    "node_unique_strings",
    "predict",
    "string_owners",
]
