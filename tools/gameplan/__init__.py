"""gameplan — describe a node graph declaratively, validate it offline, build it.

The project can add one node and one edge per native call, but has no way to
express a whole graph.  ``gameplan`` provides that:

* :mod:`tools.gameplan.contracts` — the port signatures, read from
  ``data/node-contracts`` (no bridge contact).
* :mod:`tools.gameplan.plan` — a declarative graph that validates against those
  signatures *before* any native call.
* :mod:`tools.gameplan.nodes` — named handles for the official nodes, so module
  code addresses pins by role, never by index.
* :mod:`tools.gameplan.modules` — the six gameplay modules as graph fragments.
* :mod:`tools.gameplan.builder` — turns a validated plan into the ordered
  ``author.py graph`` calls and records evidence.

Nothing in this package writes to the game by itself; only ``builder`` issues
native calls, and only when explicitly asked.
"""

from .contracts import ContractStore, default_store, load_store
from .nodes import Graph, Handle, NodeType
from .plan import ConstSpec, EdgeSpec, GraphPlan, NodeSpec, PlanError

__all__ = [
    "ContractStore",
    "ConstSpec",
    "EdgeSpec",
    "Graph",
    "GraphPlan",
    "Handle",
    "NodeSpec",
    "NodeType",
    "PlanError",
    "default_store",
    "load_store",
]
