"""Node-definition contracts: the authoritative port signatures we build against.

The bridge resolves a node definition by ``(10001, graphKind, 22000, 0)`` plus a
uint32 ``definitionId`` (``tools/editor-bridge/Adapter/AuthoringGraph.cs:32``,
``TryResolveAuthorDefinition``).  ``data/node-contracts/variants/server/*.json``
records those server-side definitions together with their pins, straight from a
live read (``live-node-schema.json``).

This module is deliberately read-only and dependency-free: it turns those JSON
buckets into a lookup we can validate a graph plan against *before* spending a
single native call.  Nothing here talks to the bridge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator

# Pin kinds, per data/node-contracts/shared/pin-kinds.json.  Only 1..4 are
# wireable; 5 ("未定-106") is observed but unnamed and never wired.
EXEC_INPUT = 1
EXEC_OUTPUT = 2
DATA_INPUT = 3
DATA_OUTPUT = 4

KIND_LABELS = {
    EXEC_INPUT: "输入执行",
    EXEC_OUTPUT: "输出执行",
    DATA_INPUT: "输入数据",
    DATA_OUTPUT: "输出数据",
}

#: The server graph kind is the only one the editor proves creatable
#: (``AuthoringGraph.cs:15-17``); every contract bucket below is that kind.
SERVER_GRAPH_KIND = 20000

#: A generic (un-materialised) pin carries ``serverParamType == 0``.  The native
#: editor fills it in from the concrete end of the edge, so a data edge touching
#: a generic pin skips the exact type check (``AuthoringGraph.cs:410-418``).
GENERIC_TYPE = 0

# Repo root: this file lives at <root>/tools/gameplan/contracts.py
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_DIR = _REPO_ROOT / "data" / "node-contracts" / "variants" / "server"


class ContractError(Exception):
    """Raised when the contract store cannot be loaded or is inconsistent."""


@dataclass(frozen=True)
class Port:
    kind: int
    index: int
    direction: str  # "input" | "output"
    server_param_type: int
    generic_id: int
    name: str
    generic_binding: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.index}"

    @property
    def is_generic(self) -> bool:
        return self.server_param_type == GENERIC_TYPE


@dataclass(frozen=True)
class NodeDefinition:
    definition_id: int
    name: str
    graph_kind: int
    ports: tuple[Port, ...]

    def port(self, kind: int, index: int) -> Port | None:
        for p in self.ports:
            if p.kind == kind and p.index == index:
                return p
        return None

    @property
    def exec_inputs(self) -> tuple[Port, ...]:
        return tuple(p for p in self.ports if p.kind == EXEC_INPUT)

    @property
    def exec_outputs(self) -> tuple[Port, ...]:
        return tuple(p for p in self.ports if p.kind == EXEC_OUTPUT)


def _port_from_record(rec: dict) -> Port:
    name = rec.get("name")
    if isinstance(name, dict):
        name = name.get("value")
    # The adapter reads (TypeId, GenericId) off the live registry
    # (AuthoringGraph.cs:496-497: stored fields ``pR9KY126SEr`` / ``fbGKY8GZn68``).
    # ``serverParamType`` is the same number as the adapter's TypeId (proven by the
    # adapter's own fixed signature table at AuthoringGraph.cs:536-537, where
    # def 71 4:0 is ``1:1`` and def 1 3:0 is ``6:6``), and ``fbGKY8GZn68`` is the
    # GenericId verbatim -- it rides along inside ``opaqueFields``.
    opaque = rec.get("opaqueFields") or {}
    # ``kind`` is the label ("exec"/"data"); ``kindRaw`` is the numeric pin kind.
    return Port(
        kind=int(rec["kindRaw"]),
        index=int(rec["index"]),
        direction=str(rec["direction"]),
        server_param_type=int(rec.get("serverParamType", 0)),
        generic_id=int(opaque.get("fbGKY8GZn68", 0)),
        name=str(name or ""),
        generic_binding=str(rec.get("genericBinding", "not-applicable")),
    )


def _definition_from_record(rec: dict) -> NodeDefinition:
    sk = rec["stableKey"]
    return NodeDefinition(
        definition_id=int(sk["definitionId"]),
        name=str(rec.get("name") or ""),
        graph_kind=int(rec.get("graphKindRaw", SERVER_GRAPH_KIND)),
        ports=tuple(_port_from_record(p) for p in rec.get("ports", [])),
    )


class ContractStore:
    """A read-only index of node definitions by uint32 ``definitionId``."""

    def __init__(self, definitions: dict[int, NodeDefinition], source: str):
        self._defs = dict(definitions)
        self.source = source

    def __len__(self) -> int:
        return len(self._defs)

    def __contains__(self, definition_id: object) -> bool:
        return definition_id in self._defs

    def __iter__(self) -> Iterator[int]:
        return iter(sorted(self._defs))

    def get(self, definition_id: int) -> NodeDefinition | None:
        return self._defs.get(int(definition_id))

    def require(self, definition_id: int) -> NodeDefinition:
        d = self.get(definition_id)
        if d is None:
            raise ContractError(
                f"definitionId {definition_id} is not in the server contract store"
            )
        return d

    def definition_ids(self, graph_kind: int | None = None) -> tuple[int, ...]:
        if graph_kind is None:
            return tuple(sorted(self._defs))
        return tuple(
            sorted(k for k, v in self._defs.items() if v.graph_kind == graph_kind)
        )


def load_store(contract_dir: Path | str | None = None) -> ContractStore:
    """Load every ``variants/server/bucket-*.json`` into a :class:`ContractStore`."""
    directory = Path(contract_dir) if contract_dir is not None else DEFAULT_CONTRACT_DIR
    if not directory.is_dir():
        raise ContractError(f"contract directory not found: {directory}")
    definitions: dict[int, NodeDefinition] = {}
    seen_files = 0
    for path in sorted(directory.glob("bucket-*.json")):
        seen_files += 1
        for rec in json.loads(path.read_text(encoding="utf-8")):
            definition = _definition_from_record(rec)
            prior = definitions.get(definition.definition_id)
            if prior is not None and prior != definition:
                raise ContractError(
                    f"definitionId {definition.definition_id} appears twice with "
                    f"different content ({prior.name!r} vs {definition.name!r})"
                )
            definitions[definition.definition_id] = definition
    if not definitions:
        raise ContractError(f"no definitions loaded from {directory}")
    return ContractStore(definitions, source=f"{directory} ({seen_files} buckets)")


@lru_cache(maxsize=1)
def default_store() -> ContractStore:
    """Process-wide cached store over the repo's committed contracts."""
    return load_store()
