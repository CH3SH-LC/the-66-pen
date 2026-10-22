"""Golden snapshots of a graph plan — freeze it, diff it, and notice drift.

Why this exists
---------------
The six-module demo graph changed *shape* three times in a single night (13
nodes -> 15 nodes and back) and nothing failed.  A silently different graph is
the worst kind of bug in this project: every node and every wire is a native
call, a wrong graph is hard to delete, and by the time the machine disagrees
with you the diff is a memory.  A plan that only lives in the builder is a plan
nobody can *review*.

So we pin the plan: :func:`freeze` turns a :class:`~.plan.GraphPlan` into one
canonical, JSON-clean dict; :func:`compare` reports every difference between a
live plan and a frozen one; and the frozen dicts are committed in-repo
(:data:`COMMITTED_DIR`) so a shape change shows up as a **visible diff in a
commit**, never as a silent drift.

Canonical form
--------------
:func:`freeze` emits plain JSON types only (str/int/list/dict) and :func:`dumps`
serialises with ``sort_keys=True`` + a fixed indent, so two identical plans
always produce byte-identical files.  Ordering that is *meaningful* — node build
order, edge order, const order — is preserved (that is exactly the "13 -> 15"
kind of change we want to catch); only mapping-key order is normalised.

Where files live
----------------
* :data:`SCRATCH_DIR` (``.runtime/scratch/golden/``) — the working output, where
  :func:`write_golden` writes by default (doctrine: artefacts stay in the repo).
* :data:`COMMITTED_DIR` (``tools/gameplan/golden/``) — the reviewed baselines the
  tests read.  A change here is a commit you can see, not a byte on a disk.

Module vs directory name
------------------------
This package deliberately has both ``golden.py`` and a ``golden/`` data
directory.  On CPython (3.13, checked) the module wins a same-name clash, so
``import tools.gameplan.golden`` is unambiguous; the data directory carries no
``__init__.py``.  Do not add one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .plan import GraphPlan

# tools/gameplan/golden.py -> parents[0]=gameplan, [1]=tools, [2]=repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Working output directory (doctrine: never write outside the project).
SCRATCH_DIR = _REPO_ROOT / ".runtime" / "scratch" / "golden"

#: The reviewed, committed baselines.  A change here is a committed diff.
COMMITTED_DIR = Path(__file__).resolve().parent / "golden"


class GoldenError(Exception):
    """A golden snapshot that cannot be used as one."""


class GoldenMissingError(GoldenError, FileNotFoundError):
    """No golden file by that name.

    Derives from :class:`FileNotFoundError` so callers that catch the builtin
    (or ``OSError``) still work, while the name tells a *reader* what is missing
    — a snapshot, not some arbitrary file.
    """


# --------------------------------------------------------------------------
# freeze: GraphPlan -> canonical, JSON-clean dict
# --------------------------------------------------------------------------


def freeze(plan: GraphPlan) -> dict:
    """Return the canonical JSON dict for ``plan``.

    The dict holds only JSON types and is stable: freezing the same plan twice
    (or an equal plan built twice) yields equal dicts and, through :func:`dumps`,
    byte-identical text.  Node/edge/const *order* is the plan's own order and is
    preserved on purpose — reordering is a shape change we want to see.
    """
    return {
        "name": plan.name,
        "graphKind": int(plan.graph_kind),
        "nodes": [
            {
                "alias": node.alias,
                "definitionId": int(node.definition_id),
                "x": int(node.x),
                "y": int(node.y),
            }
            for node in plan.nodes
        ],
        "edges": [
            {
                "from": edge.src,
                "to": edge.dst,
                "fromKind": int(edge.src_kind),
                "fromIndex": int(edge.src_index),
                "toKind": int(edge.dst_kind),
                "toIndex": int(edge.dst_index),
            }
            for edge in plan.edges
        ],
        "consts": [
            {
                "alias": const.alias,
                "portIndex": int(const.port_index),
                "slot": const.slot,
                "value": _canonical_value(const.value),
            }
            for const in plan.consts
        ],
    }


def _canonical_value(value: Any) -> Any:
    """Coerce a const value to JSON-clean scalars and containers."""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if value is None:
        return None
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise GoldenError("const dictionaries must have string keys")
        return {key: _canonical_value(item) for key, item in value.items()}
    # Container constants are legal plan shapes; anything else is a bug in the
    # plan, so make it loud rather than silently stringifying.
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise GoldenError(
        f"const value {value!r} of type {type(value).__name__} is not a "
        f"canonical JSON primitive"
    )


def dumps(golden: dict) -> str:
    """Serialise a frozen plan canonically (sorted keys, fixed indent, trailing NL)."""
    return json.dumps(golden, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def loads(text: str) -> dict:
    """Parse golden text back into a dict, raising :class:`GoldenError` if it is not."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise GoldenError(f"golden text is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise GoldenError(f"golden text must decode to an object, got {type(data).__name__}")
    return data


# --------------------------------------------------------------------------
# compare: DiffReport
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One difference between a live plan and a golden snapshot.

    ``alias`` and ``definition_id`` are carried structurally (not just embedded
    in prose) so a caller — or a test — can assert on the exact node that moved.
    For a node whose ``definitionId`` changed, ``was_definition_id`` is the
    golden value and ``definition_id`` is the live value.
    """

    kind: str
    summary: str
    alias: str | None = None
    definition_id: int | None = None
    was_definition_id: int | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.summary

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "summary": self.summary,
            "alias": self.alias,
            "definitionId": self.definition_id,
            "wasDefinitionId": self.was_definition_id,
        }


@dataclass(frozen=True)
class DiffReport:
    """The result of :func:`compare`: ``ok`` plus every :class:`Change`."""

    ok: bool
    changes: tuple[Change, ...]

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return "identical"
        return "\n".join(change.summary for change in self.changes)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "changes": [c.to_dict() for c in self.changes]}


def compare(plan: GraphPlan, golden: dict) -> DiffReport:
    """Diff ``plan`` (the live graph) against ``golden`` (a frozen snapshot).

    Returns a :class:`DiffReport`; ``report.ok`` is ``True`` only when they are
    identical.  ``golden`` is normally the dict from :func:`freeze` / :func:`read_golden`,
    but a :class:`~.plan.GraphPlan` is accepted and frozen on the fly.
    """
    actual = freeze(plan)
    expected = freeze(golden) if isinstance(golden, GraphPlan) else golden
    if not isinstance(expected, dict):
        raise GoldenError(f"golden must be a frozen dict or a GraphPlan, got {type(expected).__name__}")

    changes: list[Change] = []

    if expected.get("name") != actual["name"]:
        changes.append(
            Change("name_changed", f"graph name {expected.get('name')!r} -> {actual['name']!r}")
        )
    if expected.get("graphKind") != actual["graphKind"]:
        changes.append(
            Change("kind_changed", f"graph kind {expected.get('graphKind')} -> {actual['graphKind']}")
        )

    changes.extend(_compare_nodes(expected.get("nodes", []), actual["nodes"]))
    changes.extend(_compare_edges(expected.get("edges", []), actual["edges"]))
    changes.extend(_compare_consts(expected.get("consts", []), actual["consts"]))

    return DiffReport(ok=not changes, changes=tuple(changes))


def _compare_nodes(expected: list, actual: list) -> list[Change]:
    changes: list[Change] = []
    exp = {n["alias"]: n for n in expected}
    act = {n["alias"]: n for n in actual}

    for alias, node in exp.items():
        if alias not in act:
            changes.append(
                Change(
                    "node_removed",
                    f"node -{alias} (definitionId {node['definitionId']})",
                    alias=alias,
                    definition_id=node["definitionId"],
                )
            )
    for alias, node in act.items():
        if alias not in exp:
            changes.append(
                Change(
                    "node_added",
                    f"node +{alias} (definitionId {node['definitionId']})",
                    alias=alias,
                    definition_id=node["definitionId"],
                )
            )
    for alias, node in act.items():
        old = exp.get(alias)
        if old is None:
            continue
        if old["definitionId"] != node["definitionId"]:
            changes.append(
                Change(
                    "node_definition_changed",
                    f"node {alias} definitionId {old['definitionId']} -> {node['definitionId']}",
                    alias=alias,
                    definition_id=node["definitionId"],
                    was_definition_id=old["definitionId"],
                )
            )
        if (old["x"], old["y"]) != (node["x"], node["y"]):
            changes.append(
                Change(
                    "node_position_changed",
                    f"node {alias} moved ({old['x']},{old['y']}) -> ({node['x']},{node['y']})",
                    alias=alias,
                    definition_id=node["definitionId"],
                )
            )

    # Order only matters when the *set* of aliases is unchanged (otherwise the
    # add/remove changes above already tell the story).
    if set(exp) == set(act):
        exp_order = [n["alias"] for n in expected]
        act_order = [n["alias"] for n in actual]
        if exp_order != act_order:
            changes.append(
                Change(
                    "node_order_changed",
                    f"node order {exp_order} -> {act_order}",
                )
            )
    return changes


def _edge_key(edge: dict) -> tuple:
    return (
        edge["from"], edge["fromKind"], edge["fromIndex"],
        edge["to"], edge["toKind"], edge["toIndex"],
    )


def _edge_label(edge: dict) -> str:
    return (
        f"{edge['from']}({edge['fromKind']}:{edge['fromIndex']}) -> "
        f"{edge['to']}({edge['toKind']}:{edge['toIndex']})"
    )


def _compare_edges(expected: list, actual: list) -> list[Change]:
    changes: list[Change] = []
    exp = [_edge_key(e) for e in expected]
    act = [_edge_key(e) for e in actual]
    exp_labels = {_edge_key(e): _edge_label(e) for e in expected}
    act_labels = {_edge_key(e): _edge_label(e) for e in actual}

    for key in _multiset_missing(exp, act):
        changes.append(Change("edge_removed", f"edge -{exp_labels[key]}"))
    for key in _multiset_missing(act, exp):
        changes.append(Change("edge_added", f"edge +{act_labels[key]}"))
    return changes


def _const_key(const: dict) -> tuple:
    return (const["alias"], const["portIndex"])


def _const_label(const: dict) -> str:
    return f"{const['alias']} 3:{const['portIndex']} = {const['value']!r} ({const['slot']})"


def _compare_consts(expected: list, actual: list) -> list[Change]:
    changes: list[Change] = []
    exp = {_const_key(c): c for c in expected}
    act = {_const_key(c): c for c in actual}

    for key, const in exp.items():
        if key not in act:
            changes.append(
                Change("const_removed", f"const -{_const_label(const)}", alias=const["alias"])
            )
    for key, const in act.items():
        if key not in exp:
            changes.append(
                Change("const_added", f"const +{_const_label(const)}", alias=const["alias"])
            )
    for key, const in act.items():
        old = exp.get(key)
        if old is None:
            continue
        if (old["slot"], _json_scalar(old["value"])) != (const["slot"], _json_scalar(const["value"])):
            changes.append(
                Change(
                    "const_changed",
                    f"const {_const_label(old)} -> {_const_label(const)}",
                    alias=const["alias"],
                )
            )
    return changes


def _json_scalar(value: Any) -> str:
    # Compare as JSON text so True/1 and 1.0/1 are not silently equal.
    return json.dumps(value, sort_keys=True)


def _multiset_missing(want: list, have: list) -> list:
    """Keys present more times in ``want`` than in ``have`` (stable, in order)."""
    pool = list(have)
    missing = []
    for key in want:
        if key in pool:
            pool.remove(key)
        else:
            missing.append(key)
    return missing


# --------------------------------------------------------------------------
# read/write
# --------------------------------------------------------------------------


def _resolve_dir(directory: Path | str | None) -> Path:
    return Path(directory) if directory is not None else SCRATCH_DIR


def write_golden(name: str, golden: dict, *, directory: Path | str | None = None) -> Path:
    """Write ``golden`` to ``<directory>/<name>.json`` (default :data:`SCRATCH_DIR`).

    Creates the directory if it does not exist.  Returns the path written.
    """
    target_dir = _resolve_dir(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.json"
    path.write_text(dumps(golden), encoding="utf-8")
    return path


def read_golden(name: str, *, directory: Path | str | None = None) -> dict:
    """Read ``<directory>/<name>.json`` (default :data:`SCRATCH_DIR`).

    Raises :class:`GoldenMissingError` (a ``FileNotFoundError``) when there is no
    such snapshot, and :class:`GoldenError` when the file is not a JSON object.
    """
    path = _resolve_dir(directory) / f"{name}.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise GoldenMissingError(f"no golden snapshot {name!r} at {path}") from error
    return loads(text)


def compare_file(plan: GraphPlan, name: str, *, directory: Path | str | None = None) -> DiffReport:
    """Compare ``plan`` against the on-disk golden ``<name>.json``."""
    return compare(plan, read_golden(name, directory=directory))


# --------------------------------------------------------------------------
# the demo baselines (single source of truth for the generator and the tests)
# --------------------------------------------------------------------------

#: The editor-asset ids the committed snapshots were frozen with.  Kept here so
#: the generator and the test build byte-identical plans.
_DEMO_IDS = dict(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

#: The aggregate snapshot filename: **one** JSON object holding every demo graph,
#: as opposed to the per-plan ``<name>.json`` files :func:`write_all` emits.
DEMO_GOLDEN_NAME = "demo-graphs"


def build_demo_plans() -> dict[str, GraphPlan]:
    """The canonical ``name -> plan`` snapshots this project pins.

    ``farming`` is game-B v0 (:mod:`tools.gameplan.demo.farming`); ``farming_full``
    is the consolidated six-direction demo (:mod:`tools.gameplan.demo.farming_full`),
    both at the default (``harvest_bonus=0``) config used by the committed tests.
    """
    from .demo.farming import FarmConfig, build_plan as build_farming
    from .demo.farming_full import FarmFullConfig, build_plan as build_farming_full

    return {
        "farming": build_farming(FarmConfig(**_DEMO_IDS)),
        "farming_full": build_farming_full(FarmFullConfig(**_DEMO_IDS)),
    }


def build_all_demo_plans() -> dict[str, GraphPlan]:
    """The canonical ``name -> plan`` for **every** demo graph under ``demo/``.

    A superset of :func:`build_demo_plans`: it adds the closed loop
    (:mod:`tools.gameplan.demo.farming_loop`) and the M4 bag graph
    (:mod:`tools.gameplan.demo.farming_m4`), each at its module-default config.
    ``farming_interactive`` is included with explicitly synthetic, offline-only
    item ids and direct-sale mode. Insertion order is stable (``farming``,
    ``farming_full``, ``farming_loop``, ``farming_m4``, ``farming_interactive``,
    ``farming_manual``). The manual graph uses its saved demo asset IDs and an
    explicitly requested offline UI index, without claiming that UI exists,
    so the aggregate golden is byte-stable, and the key is the
    demo module's stem — the discovery test relies on that one-to-one mapping.
    """
    from .demo.farming_loop import LoopConfig, build_plan as build_loop
    from .demo.farming_m4 import FarmM4Config, build_plan as build_m4
    from .demo.farming_interactive import (
        FarmInteractiveConfig,
        build_plan as build_interactive,
    )
    from .demo.farming_manual import FarmManualConfig, build_plan as build_manual

    plans = build_demo_plans()
    plans["farming_loop"] = build_loop(LoopConfig(**_DEMO_IDS))
    plans["farming_m4"] = build_m4(FarmM4Config())
    plans["farming_interactive"] = build_interactive(FarmInteractiveConfig(
        seed_id=1120000003,
        crop_id=_DEMO_IDS["crop_id"],
        currency_id=_DEMO_IDS["currency_id"],
        item_slot="int",
        currency_slot="int",
        variable_flag_slot="bool",
        sale_mode="direct",
    ))
    # 1 is an offline requested UI index, not a claim that the control exists.
    plans["farming_manual"] = build_manual(FarmManualConfig(group_index=1))
    return plans


def write_all(directory: Path | str | None = None) -> dict[str, Path]:
    """Freeze every demo plan and write it to ``directory`` (default :data:`SCRATCH_DIR`)."""
    target_dir = _resolve_dir(directory)
    return {
        name: write_golden(name, freeze(plan), directory=target_dir)
        for name, plan in build_demo_plans().items()
    }


def all_demo_golden() -> dict:
    """One canonical dict holding *every* demo graph, keyed by plan name.

    Shape is ``{"graphs": {name: <freeze(plan)>}}`` — a single file a reviewer can
    diff, so an accidental shape change to **any** demo graph shows up as one
    visible diff rather than a silently rebuilt plan.  Frozen with :func:`freeze`
    (and therefore serialised byte-stably through :func:`dumps`).
    """
    return {
        "graphs": {
            name: freeze(plan) for name, plan in build_all_demo_plans().items()
        }
    }


def write_all_demo_golden(directory: Path | str | None = None) -> Path:
    """Write :func:`all_demo_golden` to ``<dir>/demo-graphs.json`` (default :data:`SCRATCH_DIR`)."""
    return write_golden(DEMO_GOLDEN_NAME, all_demo_golden(), directory=directory)


__all__ = [
    "Change",
    "COMMITTED_DIR",
    "DEMO_GOLDEN_NAME",
    "DiffReport",
    "GoldenError",
    "GoldenMissingError",
    "SCRATCH_DIR",
    "all_demo_golden",
    "build_all_demo_plans",
    "build_demo_plans",
    "compare",
    "compare_file",
    "dumps",
    "freeze",
    "loads",
    "read_golden",
    "write_all",
    "write_all_demo_golden",
    "write_golden",
]
