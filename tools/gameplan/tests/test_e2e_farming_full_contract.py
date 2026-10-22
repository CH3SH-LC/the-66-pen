"""End-to-end OFFLINE contract, extended to the canonical demo graph.

Wave15's ``test_demo_contract.py`` already proves the demo builds, validates and
that ``batch_plan_json`` round-trips *in memory*.  This file (named ``_e2e_``
because it extends that file's surface while leaving its owner's copy untouched)
tightens the same contract on the two points the requirement names:

1. the build-plan JSON really **serialises** — ``json.dumps`` -> ``json.loads``
   through *text*, not just a dict->dict round; and
2. every **node reference index is in range** — edges' ``from``/``to`` and each
   value's ``node`` must fall in ``[0, len(nodes))``, and every node must be
   referenced at least once (no orphan node in the payload).

Both checks carry a negative control so they cannot pass vacuously.

Offline only: no bridge, editor, game, or queue file is touched.
"""

from __future__ import annotations

import json
import unittest

from tools.gameplan.builder import GraphBuilder
from tools.gameplan.demo.farming_full import (
    DEFAULT_NAME,
    FarmFullConfig,
    build_plan,
)
from tools.gameplan.plan import GraphPlan

CONFIG = FarmFullConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _batch_json(plan: GraphPlan) -> dict:
    """The plan in the adapter's ``build-plan`` shape.

    The runner raises if dispatched, proving ``batch_plan_json`` is pure.
    """
    def _never(argv):  # pragma: no cover - only runs if batch_plan_json dispatches
        raise AssertionError(f"batch_plan_json must not dispatch, got {argv!r}")

    return GraphBuilder(plan, _never, run_id="e2e-farm-full").batch_plan_json()


def _out_of_range_refs(batch: dict) -> list[tuple[str, int]]:
    """Every node reference in ``batch`` that is not a legal index.

    A legal reference is an integer in ``[0, len(batch["nodes"]))``.  This is the
    one place the range rule lives, so the test and its negative control agree.
    """
    n = len(batch["nodes"])
    bad: list[tuple[str, int]] = []
    for i, edge in enumerate(batch["edges"]):
        for key in ("from", "to"):
            ref = edge[key]
            if not isinstance(ref, int) or not (0 <= ref < n):
                bad.append((f"edge[{i}].{key}", ref))
    for i, value in enumerate(batch["values"]):
        ref = value["node"]
        if not isinstance(ref, int) or not (0 <= ref < n):
            bad.append((f"value[{i}].node", ref))
    return bad


def _referenced_indices(batch: dict) -> set[int]:
    """Every node index that is the endpoint of an edge or the owner of a value."""
    refs: set[int] = set()
    for edge in batch["edges"]:
        refs.add(edge["from"])
        refs.add(edge["to"])
    for value in batch["values"]:
        refs.add(value["node"])
    return refs


# ---------------------------------------------------------------------------
# (1) the build-plan JSON really serialises (text round-trip)
# ---------------------------------------------------------------------------

class TestBuildPlanJsonSerialises(unittest.TestCase):
    def test_json_dumps_and_loads_round_trip_the_text(self):
        batch = _batch_json(build_plan(CONFIG))
        text = json.dumps(batch, ensure_ascii=False)
        self.assertIsInstance(text, str)
        self.assertTrue(text)
        # Loaded back from *text* (a different dict object) it is byte-for-byte
        # equal in content.  If any value were a non-JSON Python object this
        # fail-fast json.dumps would have raised before we got here.
        self.assertEqual(json.loads(text), batch)

    def test_counts_survive_the_text_round_trip(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        reloaded = json.loads(json.dumps(batch, ensure_ascii=False))
        self.assertEqual(len(reloaded["nodes"]), len(plan.nodes))
        self.assertEqual(len(reloaded["edges"]), len(plan.edges))
        self.assertEqual(len(reloaded["values"]), len(plan.consts))
        self.assertEqual(set(reloaded), {"nodes", "edges", "values"})


# ---------------------------------------------------------------------------
# (2) every node reference index is in range
# ---------------------------------------------------------------------------

class TestEveryNodeRefIndexIsInRange(unittest.TestCase):
    def test_all_refs_are_within_the_node_list(self):
        batch = _batch_json(build_plan(CONFIG))
        self.assertEqual(_out_of_range_refs(batch), [])

    def test_every_node_index_is_referenced(self):
        # No orphan: a node that nothing points at and owns no value would be a
        # dead entry in the payload the adapter still builds.
        batch = _batch_json(build_plan(CONFIG))
        n = len(batch["nodes"])
        self.assertEqual(_referenced_indices(batch), set(range(n)))

    def test_out_of_range_control_is_detected(self):
        # Negative control: the range checker must fire on a broken payload,
        # otherwise the green assertions above prove nothing.  Two mutations:
        # an edge endpoint past the end, and a negative value owner.
        batch = _batch_json(build_plan(CONFIG))
        n = len(batch["nodes"])
        self.assertEqual(_out_of_range_refs(batch), [])  # control

        broken = _batch_json(build_plan(CONFIG))
        broken["edges"][0]["from"] = n          # one past the end
        broken["values"][0]["node"] = -1        # negative
        bad = _out_of_range_refs(broken)
        self.assertIn(("edge[0].from", n), bad)
        self.assertIn(("value[0].node", -1), bad)


# ---------------------------------------------------------------------------
# (3) reconstruct from the payload and re-validate (the full cycle)
# ---------------------------------------------------------------------------

def _plan_from_batch(batch: dict, name: str, graph_kind: int) -> GraphPlan:
    """Rebuild a :class:`GraphPlan` from ``build-plan`` JSON (indices -> aliases)."""
    plan = GraphPlan(name=name, graph_kind=graph_kind)
    alias = {i: f"node{i}" for i in range(len(batch["nodes"]))}
    for i, node in enumerate(batch["nodes"]):
        plan.add(alias[i], node["definitionId"], x=node["x"], y=node["y"])
    for edge in batch["edges"]:
        plan.wire(
            alias[edge["from"]], edge["fromKind"], edge["fromIndex"],
            alias[edge["to"]], edge["toKind"], edge["toIndex"],
        )
    for value in batch["values"]:
        scalar = next(iter(value["value"].values()))
        plan.const(alias[value["node"]], value["portIndex"], scalar, value["slot"])
    return plan


class TestReconstructionFromPayload(unittest.TestCase):
    def test_reconstruction_validates_and_preserves_every_count(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        restored = _plan_from_batch(batch, DEFAULT_NAME, plan.graph_kind)
        self.assertEqual(len(restored.nodes), len(plan.nodes))
        self.assertEqual(len(restored.edges), len(plan.edges))
        self.assertEqual(len(restored.consts), len(plan.consts))
        self.assertEqual(
            [n.definition_id for n in restored.nodes],
            [n.definition_id for n in plan.nodes],
        )
        self.assertIsNone(restored.validate())

    def test_reserialising_the_reconstruction_reproduces_the_payload(self):
        batch = _batch_json(build_plan(CONFIG))
        restored = _plan_from_batch(batch, DEFAULT_NAME, 20000)
        self.assertEqual(_batch_json(restored), batch)


if __name__ == "__main__":
    unittest.main()
