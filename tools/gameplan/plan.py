"""A declarative node-graph plan, validated offline against the port contracts.

Why this exists
---------------
The bridge can add *one* node at a time (``author.py graph add``) and wire *one*
edge at a time (``graph wire``).  Composing a real gameplay graph from that is
exactly the kind of thing you get subtly wrong by hand: a wrong pin index, an
execution edge written as a data edge, a constant typed for the wrong slot.
Those mistakes are *not* free — each one is a native call, and a bad graph is
hard to delete (``delete-owned-graph-ids`` has never worked).

So we describe the graph declaratively, validate every node/edge/constant
against ``data/node-contracts`` **before** any call, and only then hand the
compiler a plan that is known to be internally consistent.

Scope
-----
This is a *description* layer, not an executor.  It never talks to the bridge.
``builder.py`` turns a validated plan into the ordered native calls.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from . import contracts
from . import paramtypes
from .contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    ContractError,
    ContractStore,
)

# The adapter enforces this exact shape (AuthoringGraph.cs:113).
GRAPH_NAME_RE = re.compile(r"^MW_API_[A-Za-z0-9_]{1,48}$")

#: The only graph kind the editor proves creatable.  Client kinds are accepted
#: by the CLI but not yet confirmed by the native graph manager.
DEFAULT_GRAPH_KIND = 20000

#: Adapter node-count ceiling when the count-gate marker is absent.
NODE_LIMIT = 128


class PlanError(Exception):
    """A plan that cannot be built as written."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def validate_container_payload(value: object) -> str:
    """Validate an explicit container using the authoring request contract.

    Container tags belong to the payload, never to the scalar slot vocabulary.
    Importing the request validator performs no editor or game operation.
    """
    from tools.authoring.author import validate_scalar_payload

    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("container must have exactly one list or dict tag")
    name = next(iter(value))
    if name not in ("list", "dict"):
        raise ValueError("container must have exactly one list or dict tag")
    validate_scalar_payload(value)
    return name


@dataclass(frozen=True)
class NodeSpec:
    """One node instance to add.  ``alias`` is a local handle used in edges."""

    alias: str
    definition_id: int
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class EdgeSpec:
    """One directed link.  Kinds are pin kinds (2->1 execution, 4->3 data)."""

    src: str
    src_kind: int
    src_index: int
    dst: str
    dst_kind: int
    dst_index: int


@dataclass(frozen=True)
class ConstSpec:
    """A typed constant written into a declared data-input pin.

    ``expect_server_param_type`` and ``expect_generic_id`` are echoed to the
    adapter, which re-checks them against the live pin before writing
    (``AuthoringGraph.cs:360-366``).  Leaving them ``None`` means "take them
    from the contract" — the common case.
    """

    alias: str
    port_index: int
    value: Any
    slot: str  # one of author.py graph value --slot
    expect_server_param_type: int | None = None
    expect_generic_id: int | None = None


@dataclass
class GraphPlan:
    name: str
    graph_kind: int = DEFAULT_GRAPH_KIND
    nodes: list[NodeSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)
    consts: list[ConstSpec] = field(default_factory=list)

    # -- authoring helpers -------------------------------------------------

    def add(
        self, alias: str, definition_id: int, x: int = 0, y: int = 0
    ) -> NodeSpec:
        spec = NodeSpec(alias=alias, definition_id=int(definition_id), x=int(x), y=int(y))
        self.nodes.append(spec)
        return spec

    def wire(
        self,
        src: str,
        src_kind: int,
        src_index: int,
        dst: str,
        dst_kind: int,
        dst_index: int,
    ) -> EdgeSpec:
        edge = EdgeSpec(
            src=src,
            src_kind=int(src_kind),
            src_index=int(src_index),
            dst=dst,
            dst_kind=int(dst_kind),
            dst_index=int(dst_index),
        )
        self.edges.append(edge)
        return edge

    def flow(self, src: str, dst: str, out_index: int = 0) -> EdgeSpec:
        """Wire an execution edge (source exec-out -> target exec-in)."""
        return self.wire(src, EXEC_OUTPUT, out_index, dst, EXEC_INPUT, 0)

    def data(self, src: str, src_index: int, dst: str, dst_index: int) -> EdgeSpec:
        """Wire a data edge (source data-out -> target data-in)."""
        return self.wire(src, DATA_OUTPUT, src_index, dst, DATA_INPUT, dst_index)

    def const(
        self,
        alias: str,
        port_index: int,
        value: Any,
        slot: str,
        expect_server_param_type: int | None = None,
        expect_generic_id: int | None = None,
    ) -> ConstSpec:
        spec = ConstSpec(
            alias=alias,
            port_index=int(port_index),
            value=value,
            slot=slot,
            expect_server_param_type=expect_server_param_type,
            expect_generic_id=expect_generic_id,
        )
        self.consts.append(spec)
        return spec

    def dict_const(self, alias: str, port_index: int, entries: list[dict]) -> ConstSpec:
        """Set typed key/value pairs without converting integer keys to strings."""
        value = {"dict": deepcopy(entries)}
        validate_container_payload(value)
        return self.const(alias, port_index, value, "auto")

    def vector3_const(self, alias: str, port_index: int, xyz: list[float]) -> ConstSpec:
        """A type-12 vector (including position/rotation), with three float32 axes.

        A generic pin must already have been materialized to vector storage by a
        native edge. This method does not change a generic pin's type itself.
        """
        from tools.authoring.author import validate_scalar_payload
        value = {"vector3": deepcopy(xyz)}
        validate_scalar_payload(value)
        return self.const(alias, port_index, value, "vector3")

    def list_const(self, alias: str, port_index: int, elements: list[dict]) -> ConstSpec:
        """Set a bounded list of tagged scalar elements, e.g. timer intervals."""
        value = {"list": deepcopy(elements)}
        validate_container_payload(value)
        return self.const(alias, port_index, value, "auto")

    # -- validation --------------------------------------------------------

    def aliases(self) -> dict[str, NodeSpec]:
        return {n.alias: n for n in self.nodes}

    def validate(self, store: ContractStore | None = None) -> None:
        """Raise :class:`PlanError` listing every problem, or return cleanly."""
        store = store or contracts.default_store()
        problems: list[str] = []

        if not GRAPH_NAME_RE.match(self.name):
            problems.append(
                f"graph name {self.name!r} must match {GRAPH_NAME_RE.pattern}"
            )
        if self.graph_kind not in (20000, 20001, 20002, 20007):
            problems.append(f"graph kind {self.graph_kind} is not requestable")
        if len(self.nodes) > NODE_LIMIT:
            problems.append(
                f"{len(self.nodes)} nodes exceeds the {NODE_LIMIT}-node ceiling"
            )

        aliases: dict[str, NodeSpec] = {}
        for node in self.nodes:
            if node.alias in aliases:
                problems.append(f"duplicate node alias {node.alias!r}")
                continue
            aliases[node.alias] = node
            if store.get(node.definition_id) is None:
                problems.append(
                    f"node {node.alias!r}: definitionId {node.definition_id} "
                    f"is not in the server contract store"
                )

        self._validate_edges(store, aliases, problems)
        self._validate_consts(store, aliases, problems)

        if problems:
            raise PlanError(problems)

    def _validate_edges(
        self,
        store: ContractStore,
        aliases: dict[str, NodeSpec],
        problems: list[str],
    ) -> None:
        for edge in self.edges:
            src_node = aliases.get(edge.src)
            dst_node = aliases.get(edge.dst)
            if src_node is None:
                problems.append(f"edge references unknown source alias {edge.src!r}")
                continue
            if dst_node is None:
                problems.append(f"edge references unknown target alias {edge.dst!r}")
                continue
            if edge.src == edge.dst:
                problems.append(f"edge {edge.src!r} links a node to itself")
                continue

            # Direction: the adapter only permits (2->1) and (4->3).
            pair = (edge.src_kind, edge.dst_kind)
            if pair not in ((EXEC_OUTPUT, EXEC_INPUT), (DATA_OUTPUT, DATA_INPUT)):
                problems.append(
                    f"edge {edge.src}->{edge.dst}: kind pair {pair} is not "
                    f"one of (2->1 execution) or (4->3 data)"
                )
                continue

            src_def = store.require(src_node.definition_id)
            dst_def = store.require(dst_node.definition_id)

            if pair == (EXEC_OUTPUT, EXEC_INPUT):
                # Execution: source index 0 or 1 (双分支 has 是/否), target 0.
                if edge.src_index not in (0, 1):
                    problems.append(
                        f"edge {edge.src}->{edge.dst}: execution output index "
                        f"{edge.src_index} is not 0 or 1"
                    )
                if edge.dst_index != 0:
                    problems.append(
                        f"edge {edge.src}->{edge.dst}: execution input index "
                        f"must be 0, got {edge.dst_index}"
                    )
                # Check the exec pins actually exist on the definitions.
                if not any(
                    p.kind == EXEC_OUTPUT and p.index == edge.src_index
                    for p in src_def.ports
                ):
                    problems.append(
                        f"edge {edge.src}->{edge.dst}: definition "
                        f"{src_def.definition_id} has no execution output "
                        f"index {edge.src_index}"
                    )
                if not any(
                    p.kind == EXEC_INPUT and p.index == edge.dst_index
                    for p in dst_def.ports
                ):
                    problems.append(
                        f"edge {edge.src}->{edge.dst}: definition "
                        f"{dst_def.definition_id} has no execution input "
                        f"index {edge.dst_index}"
                    )
            else:
                src_port = src_def.port(DATA_OUTPUT, edge.src_index)
                dst_port = dst_def.port(DATA_INPUT, edge.dst_index)
                if src_port is None:
                    problems.append(
                        f"edge {edge.src}->{edge.dst}: definition "
                        f"{src_def.definition_id} has no data output index "
                        f"{edge.src_index}"
                    )
                if dst_port is None:
                    problems.append(
                        f"edge {edge.src}->{edge.dst}: definition "
                        f"{dst_def.definition_id} has no data input index "
                        f"{edge.dst_index}"
                    )
                if src_port and dst_port:
                    # A generic end is filled by the native editor from the
                    # concrete one, so only compare two concrete ends.
                    if (
                        not src_port.is_generic
                        and not dst_port.is_generic
                        and src_port.server_param_type != dst_port.server_param_type
                    ):
                        problems.append(
                            f"edge {edge.src}->{edge.dst}: data type mismatch "
                            f"{src_port.server_param_type} -> "
                            f"{dst_port.server_param_type} (both concrete)"
                        )

    def _validate_consts(
        self,
        store: ContractStore,
        aliases: dict[str, NodeSpec],
        problems: list[str],
    ) -> None:
        seen: set[tuple[str, int]] = set()
        for const in self.consts:
            node = aliases.get(const.alias)
            if node is None:
                problems.append(
                    f"constant references unknown alias {const.alias!r}"
                )
                continue
            spot = (const.alias, const.port_index)
            if spot in seen:
                problems.append(
                    f"constant {const.alias!r} pin 3:{const.port_index} set twice"
                )
                continue
            seen.add(spot)

            definition = store.require(node.definition_id)
            port = definition.port(DATA_INPUT, const.port_index)
            if port is None:
                problems.append(
                    f"constant {const.alias!r}: definition "
                    f"{definition.definition_id} has no data input index "
                    f"{const.port_index}"
                )
                continue
            if const.slot not in _SLOTS:
                problems.append(
                    f"constant {const.alias!r}: slot {const.slot!r} is not one "
                    f"of {sorted(_SLOTS)}"
                )
            is_vector = const.slot == "vector3" or (
                isinstance(const.value, dict) and "vector3" in const.value)
            if is_vector:
                try:
                    from tools.authoring.author import validate_scalar_payload
                    payload = {"vector3": const.value} if isinstance(const.value, list) else const.value
                    validate_scalar_payload(payload)
                    if (not isinstance(payload, dict) or set(payload) != {"vector3"}
                            or const.slot not in ("auto", "vector3")):
                        raise ValueError("vector3 requires vector3 payload and slot='vector3' or 'auto'")
                    if not port.is_generic and port.server_param_type != paramtypes.VECTOR3:
                        raise ValueError("vector3 requires serverParamType 12, not editable storage code 7")
                except ValueError as error:
                    problems.append(f"constant {const.alias!r} pin 3:{const.port_index}: {error}")
            elif isinstance(const.value, (dict, list)):
                try:
                    container = validate_container_payload(const.value)
                    if const.slot != "auto":
                        raise ValueError("container constants require slot='auto'")
                    if (container == "dict" and not port.is_generic
                            and port.server_param_type != 27):
                        raise ValueError("dict constant requires a type-27 or generic pin")
                except ValueError as error:
                    problems.append(f"constant {const.alias!r} pin 3:{const.port_index}: {error}")
            expect = const.expect_server_param_type
            if (
                expect is not None
                and not port.is_generic
                and expect != port.server_param_type
            ):
                problems.append(
                    f"constant {const.alias!r} pin 3:{const.port_index}: expect "
                    f"type {expect} but the contract declares "
                    f"{port.server_param_type}"
                )

            # The pin's declared type is a fact even when no ``expect_*`` was
            # passed.  A slot whose wire type is *unambiguous* (bool/float/string,
            # 1:1 with codes 4/5/6 -- see ``paramtypes.CONFIDENT_SLOT_TYPE``) must
            # therefore match a concrete pin.  Without this, a block could write
            # ``slot="string"`` into an integer-coded pin such as the config-id
            # ``686 3:1`` (serverParamType 20) and still validate -- the ledger's
            # counterexample (b).  ``int``/``uint``/``enum`` are left unconstrained
            # on purpose: the integer family is where slot<->type is unproven
            # (``paramtypes.CONFIG_ID_SLOT is None``), so a config-id constant
            # *must* be allowed to say ``slot="int"``.
            if not port.is_generic:
                slot_type = paramtypes.CONFIDENT_SLOT_TYPE.get(const.slot)
                if slot_type is not None and slot_type != port.server_param_type:
                    problems.append(
                        f"constant {const.alias!r} pin 3:{const.port_index}: slot "
                        f"{const.slot!r} writes a type-{slot_type} value but the "
                        f"contract declares serverParamType "
                        f"{port.server_param_type}"
                    )


_SLOTS = frozenset({"auto", "int", "uint", "enum", "float", "bool", "string", "vector3"})
