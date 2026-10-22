"""Golden shape guard for **every** demo graph under ``tools/gameplan/demo/``.

The six-module demo graph has been rebuilt several times (13 -> 15 nodes, then a
bonus branch); nothing failed, because nothing pinned its shape.  :mod:`tools.gameplan.golden`
freezes *one* plan; this file freezes *all of them at once*, into a single
reviewable file — ``tools/gameplan/golden/demo-graphs.json`` — and fails loudly
whenever a live build drifts from it.

What is guarded
---------------

* **Completeness** — every demo module that exposes ``build_plan`` has an entry,
  keyed by its module stem.  A new demo graph cannot be added without a golden.
* **Shape** — each live build is compared (via ``golden.compare``) against the
  committed snapshot and must be identical node-for-node, wire-for-wire.
* **File hygiene** — the committed file is valid JSON, has exactly the expected
  keys, and is the canonical serialisation of a fresh build (so a change is a
  clean one-line diff, never key-order noise).
* **Discrimination** — mutating a plan in memory reports the *specific* node
  alias that changed, not merely a falsy boolean.

These tests only *read* the committed file; they never call the bridge.
"""

from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

from tools.gameplan import golden
from tools.gameplan.golden import COMMITTED_DIR, DEMO_GOLDEN_NAME, compare
from tools.gameplan.plan import GraphPlan, NodeSpec

#: The demo graphs this file pins (module stem == plan name), in build order.
EXPECTED_GRAPHS = (
    "farming", "farming_full", "farming_loop", "farming_m4",
    "farming_interactive", "farming_manual",
)

#: The keys :func:`tools.gameplan.golden.freeze` emits for one graph.
_GRAPH_KEYS = {"name", "graphKind", "nodes", "edges", "consts"}
_NODE_KEYS = {"alias", "definitionId", "x", "y"}
_EDGE_KEYS = {"from", "to", "fromKind", "fromIndex", "toKind", "toIndex"}
_CONST_KEYS = {"alias", "portIndex", "slot", "value"}

_GOLDEN_PATH = COMMITTED_DIR / f"{DEMO_GOLDEN_NAME}.json"


def _raw_golden() -> dict:
    """The committed aggregate file, decoded as plain JSON (no helpers)."""
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def _golden_graphs() -> dict:
    """The committed ``name -> frozen graph`` mapping, via the golden reader."""
    return golden.read_golden(DEMO_GOLDEN_NAME, directory=COMMITTED_DIR)["graphs"]


def _demo_modules_with_build_plan() -> set[str]:
    """Every module under ``tools/gameplan/demo/`` that defines ``build_plan``."""
    demo_dir = Path(golden.__file__).resolve().parent / "demo"
    found: set[str] = set()
    for path in sorted(demo_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        module = importlib.import_module(f"tools.gameplan.demo.{path.stem}")
        if callable(getattr(module, "build_plan", None)):
            found.add(path.stem)
    return found


class TestEveryDemoGraphIsCovered(unittest.TestCase):
    """The guard that makes "EVERY demo graph" true, not aspirational."""

    def test_golden_covers_every_demo_module_that_can_build_a_plan(self):
        modules = _demo_modules_with_build_plan()
        covered = set(golden.build_all_demo_plans())
        self.assertEqual(
            modules,
            covered,
            f"demo modules {modules} != golden graphs {covered}; a demo graph was "
            f"added without a frozen shape, or a golden entry names no module",
        )

    def test_every_demo_module_that_can_build_a_plan_is_named_in_the_file(self):
        self.assertEqual(set(_golden_graphs()), _demo_modules_with_build_plan())

    def test_expected_graphs_are_exactly_present(self):
        self.assertEqual(set(_golden_graphs()), set(EXPECTED_GRAPHS))

    def test_all_demo_plans_is_a_superset_of_the_original_two(self):
        self.assertTrue(
            set(golden.build_demo_plans()) <= set(golden.build_all_demo_plans())
        )

    def test_every_golden_entry_is_a_validated_graph_plan(self):
        for name, plan in golden.build_all_demo_plans().items():
            with self.subTest(plan=name):
                self.assertIsInstance(plan, GraphPlan)
                plan.validate()  # raises PlanError if a node/edge/const is off


class TestGoldenFileIsWellFormed(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(_GOLDEN_PATH.exists(), f"missing {_GOLDEN_PATH}")

    def test_parses_as_a_json_object_with_only_the_graphs_key(self):
        data = _raw_golden()
        self.assertIsInstance(data, dict)
        self.assertEqual(list(data), ["graphs"])
        self.assertIsInstance(data["graphs"], dict)

    def test_graphs_key_holds_exactly_the_expected_names(self):
        self.assertEqual(set(_raw_golden()["graphs"]), set(EXPECTED_GRAPHS))

    def test_every_graph_has_exactly_the_frozen_keys(self):
        for name, graph in _raw_golden()["graphs"].items():
            with self.subTest(plan=name):
                self.assertEqual(set(graph), _GRAPH_KEYS)
                self.assertIsInstance(graph["name"], str)
                self.assertIsInstance(graph["graphKind"], int)
                for node in graph["nodes"]:
                    self.assertEqual(set(node), _NODE_KEYS)
                for edge in graph["edges"]:
                    self.assertEqual(set(edge), _EDGE_KEYS)
                for const in graph["consts"]:
                    self.assertEqual(set(const), _CONST_KEYS)

    def test_committed_bytes_are_the_canonical_fresh_build(self):
        # Re-freezing a fresh build must reproduce the file exactly: a change is
        # a clean one-line diff, never pure key-order noise.
        text = _GOLDEN_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            text,
            golden.dumps(golden.all_demo_golden()),
            "tools/gameplan/golden/demo-graphs.json is not the canonical build; "
            "regenerate with golden.write_all_demo_golden(directory=COMMITTED_DIR)",
        )
        self.assertTrue(text.endswith("\n"))

    def test_keys_are_sorted_at_every_level(self):
        def assert_sorted(obj, where):
            if isinstance(obj, dict):
                self.assertEqual(list(obj), sorted(obj), f"keys unsorted at {where}")
                for key, value in obj.items():
                    assert_sorted(value, f"{where}.{key}")
            elif isinstance(obj, list):
                for i, value in enumerate(obj):
                    assert_sorted(value, f"{where}[{i}]")

        assert_sorted(_raw_golden(), DEMO_GOLDEN_NAME)


class TestEveryDemoGraphMatchesItsGolden(unittest.TestCase):
    """A live build must equal the committed snapshot, node for node."""

    def test_every_live_plan_matches_the_committed_shape(self):
        graphs = _golden_graphs()
        for name, plan in golden.build_all_demo_plans().items():
            with self.subTest(plan=name):
                report = compare(plan, graphs[name])
                self.assertTrue(
                    report.ok,
                    f"plan {name!r} drifted from "
                    f"tools/gameplan/golden/{DEMO_GOLDEN_NAME}.json:\n{report}",
                )
                self.assertEqual(report.changes, ())

    def test_a_fresh_build_is_ok_when_compared_to_itself(self):
        for name, plan in golden.build_all_demo_plans().items():
            with self.subTest(plan=name):
                self.assertTrue(compare(plan, golden.build_all_demo_plans()[name]))


class TestMutationIsReportedWithTheNodeAlias(unittest.TestCase):
    """The negative control: a mutated plan names the node that changed."""

    @staticmethod
    def _replace_node(plan, alias, *, definition_id=None, x=None, y=None):
        for i, node in enumerate(plan.nodes):
            if node.alias == alias:
                plan.nodes[i] = NodeSpec(
                    alias=node.alias,
                    definition_id=node.definition_id if definition_id is None else definition_id,
                    x=node.x if x is None else x,
                    y=node.y if y is None else y,
                )
                return node
        raise KeyError(alias)

    def test_retyped_node_reports_alias_and_both_definition_ids(self):
        # farming_m4's `branch` is 双分支 (2); retype it and the diff must name it.
        plan = golden.build_all_demo_plans()["farming_m4"]
        self._replace_node(plan, "branch", definition_id=999)
        report = compare(plan, _golden_graphs()["farming_m4"])
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_definition_changed")
        self.assertEqual(change.alias, "branch")
        self.assertEqual(change.definition_id, 999)      # the mutated (live) value
        self.assertEqual(change.was_definition_id, 2)     # the committed value
        self.assertIn("branch", str(change))

    def test_moved_node_reports_the_exact_alias(self):
        plan = golden.build_all_demo_plans()["farming_loop"]
        self._replace_node(plan, "win", x=9999, y=-64)
        report = compare(plan, _golden_graphs()["farming_loop"])
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_position_changed")
        self.assertEqual(change.alias, "win")
        self.assertIn("9999", str(change))

    def test_removed_node_reports_alias_and_definition_id(self):
        plan = golden.build_all_demo_plans()["farming_loop"]
        plan.nodes[:] = [n for n in plan.nodes if n.alias != "ter_gate"]
        report = compare(plan, _golden_graphs()["farming_loop"])
        change = next(c for c in report.changes if c.kind == "node_removed")
        self.assertEqual(change.alias, "ter_gate")
        self.assertEqual(change.definition_id, 2)

    def test_an_untouched_sibling_graph_is_unaffected(self):
        # Mutating one graph must not make the *other* graphs look drifted.
        plan = golden.build_all_demo_plans()["farming_m4"]
        self._replace_node(plan, "branch", definition_id=999)
        graphs = _golden_graphs()
        self.assertFalse(compare(plan, graphs["farming_m4"]).ok)
        self.assertTrue(compare(golden.build_all_demo_plans()["farming"], graphs["farming"]).ok)


if __name__ == "__main__":
    unittest.main()
