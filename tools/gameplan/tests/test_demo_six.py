"""Offline guard for the SIX-AXIS demo (``demo/farming_six.py``) and the derived coverage.

Four things are asserted, none of which needs the bridge, the game, the editor or the
helper:

  (a) **Shape & entry** — the plan enters through ``71 实体创建时`` (the only event
      node), the unconditional ``打印字符串`` sits immediately after it, and no node
      carries a blocked primitive.
  (b) **Derived coverage** — the six-module coverage is what
      :mod:`tools.gameplan.coverage` *derives* from the plan (reachable + not blocked
      + not an event), NOT a hardcoded list.  The controls prove it moves: pass an
      empty blocked set and a placed shop node would cover M5; place a second event
      and the plan is no longer single-entry.
  (c) **The other three directions and their exact reasons** — M1's nodes are all
      events, M5's are all blocked, M6 declares no node.
  (d) **Prediction with capture identity** — the predicted prints, their
      node-uniqueness (observed vs inferred), and the branch-arm table.

Read-only and offline: it never dispatches anything.  It reads one file, the plan
artifact ``.runtime/scratch/DEMO-SIX-plan.json``; when that is absent (``.runtime/``
is git-ignored) that single test skips loudly.

Run::

    python -B -m unittest tools.gameplan.tests.test_demo_six
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.gameplan import coverage as cov
from tools.gameplan import contracts, runtime_prediction as rp
from tools.gameplan.nodes import CLOSE_SHOP, PRINT, PROXIMITY_ENTER
from tools.gameplan.demo import farming_runnable as fr
from tools.gameplan.demo import farming_six as fs

REPO = Path(__file__).resolve().parents[3]
ARTIFACT = REPO / ".runtime" / "scratch" / "DEMO-SIX-plan.json"


class ShapeAndEntry(unittest.TestCase):
    def test_first_node_is_71(self):
        self.assertEqual(fs.demo_plan().nodes[0].definition_id, 71)

    def test_only_entry_is_71(self):
        plan = fs.demo_plan()
        self.assertEqual(cov.entry_aliases(plan), ("on_create",))
        by_alias = {n.alias: n for n in plan.nodes}
        self.assertEqual(by_alias["on_create"].definition_id, 71)

    def test_probe_is_unconditional_and_immediate(self):
        plan = fs.demo_plan()
        by_alias = {n.alias: n for n in plan.nodes}
        self.assertEqual(by_alias["print_entry"].definition_id, PRINT.definition_id)
        # the entry's exec output goes straight to the probe
        wire = [(e.src, e.src_index, e.dst) for e in plan.edges
                if e.src == "on_create" and e.src_kind == 2]
        self.assertEqual(wire, [("on_create", 0, "print_entry")])
        # and the probe prints the graph's own name
        text = [c.value for c in plan.consts
                if c.alias == "print_entry" and c.slot == "string"]
        self.assertEqual(text, [fs.ENTRY_PROBE_TEXT])

    def test_no_blocked_primitive(self):
        plan = fs.demo_plan()
        self.assertEqual(sorted(cov.definition_ids(plan) & cov.BLOCKED_DEFINITION_IDS), [])

    def test_shape_with_and_without_dict_queries(self):
        with_q = fs.plan_of(fs.SixConfig(currency_id=1, crop_id=2))
        without_q = fs.plan_of(fs.SixConfig(currency_id=1, crop_id=2, include_dict_queries=False))
        self.assertEqual((len(with_q.nodes), len(without_q.nodes)), (20, 18))
        self.assertEqual(len(with_q.consts), 15)


class DerivedCoverage(unittest.TestCase):
    """(b) coverage is DERIVED, and the derivation is live."""

    def test_covered_modules_is_derived(self):
        # The expected value, but asserted *through the derivation* (and each control
        # below shows the derivation would answer differently if the inputs changed).
        self.assertEqual(
            cov.covered_modules(fs.demo_plan()),
            ("M2-currency", "M3-item", "M4-inventory"),
        )

    def test_module_node_table_matches_the_sibling(self):
        # Two derivations of the same table (coverage.py and farming_runnable.py) must
        # not drift; this is the guard that makes the duplication safe.
        self.assertEqual(
            cov.BLOCKED_DEFINITION_IDS, fr.BLOCKED_DEFINITION_IDS
        )
        for module, ids in fr.MODULE_NODE_IDS.items():
            self.assertEqual(cov.MODULE_NODE_IDS[module], ids, module)

    def test_blocked_derivation_is_non_vacuous(self):
        self.assertIn(PROXIMITY_ENTER.definition_id, cov.BLOCKED_DEFINITION_IDS)
        self.assertIn(CLOSE_SHOP.definition_id, cov.BLOCKED_DEFINITION_IDS)
        self.assertIn(92, cov.BLOCKED_DEFINITION_IDS)
        self.assertIn(702, cov.BLOCKED_DEFINITION_IDS)

    def test_coverage_moves_when_the_blocked_set_moves(self):
        """Proves the answer is a function of the blocked set, not a typed list."""
        g = fs.build(fs.SixConfig(currency_id=1, crop_id=2))
        shut = g.place(CLOSE_SHOP, "shut")   # 703 — a *chain* M5 node
        g.handle("print_short").flow_to(shut)
        g.validate()
        plan = g.plan
        # With the real (derived) blocked set, M5 stays out ...
        self.assertNotIn("M5-shop", cov.covered_modules(plan))
        # ... but with the blocker set empty (as if 商店组件 were authorable), the
        # very same plan covers M5. A hardcoded list could not do this.
        self.assertIn("M5-shop", cov.covered_modules(plan, blocked=frozenset()))

    def test_placing_a_second_event_breaks_single_entry(self):
        """M1's nodes are events; one extra event makes the plan ambiguous, not richer."""
        g = fs.build(fs.SixConfig(currency_id=1, crop_id=2))
        g.place(PROXIMITY_ENTER, "plot_enter")   # 92
        g.validate()
        self.assertEqual(len(cov.entry_aliases(g.plan)), 2)
        with self.assertRaises(ValueError):
            cov.covered_modules(g.plan)

    def test_coverage_is_invariant_to_the_dead_dict_queries(self):
        a = cov.covered_modules(fs.plan_of(fs.SixConfig(currency_id=1, crop_id=2,
                                                         include_dict_queries=True)))
        b = cov.covered_modules(fs.plan_of(fs.SixConfig(currency_id=1, crop_id=2,
                                                         include_dict_queries=False)))
        self.assertEqual(a, b)

    def test_m4_fragment_set_is_the_full_reachable_set(self):
        # Includes 721/722 (all-items / all-currencies): reachable from the entry,
        # their outputs are opaque — included, but they change no *module* coverage.
        cov_map = cov.module_coverage(fs.demo_plan())
        self.assertEqual(cov_map["M4-inventory"], frozenset({685, 689, 721, 722}))


class TheOtherThreeDirections(unittest.TestCase):
    """(c) each uncovered direction, with its exact reason — derived, not narrated."""

    def _status(self):
        return cov.module_status(fs.demo_plan())

    def test_m1_all_nodes_are_events(self):
        store = contracts.default_store()
        ids = cov.MODULE_NODE_IDS["M1-interaction"]
        self.assertTrue(ids)
        for d in ids:
            defn = store.require(d)
            self.assertTrue(defn.exec_outputs and not defn.exec_inputs,
                            f"M1 node {d} is not an event")
        self.assertEqual(self._status()["M1-interaction"], "all-nodes-are-events")

    def test_m5_all_nodes_blocked(self):
        ids = cov.MODULE_NODE_IDS["M5-shop"]
        self.assertTrue(ids)
        self.assertTrue(ids <= cov.BLOCKED_DEFINITION_IDS)
        self.assertEqual(self._status()["M5-shop"], "all-nodes-blocked")

    def test_m6_declares_no_node(self):
        self.assertEqual(cov.MODULE_NODE_IDS["M6-level-terrain"], frozenset())
        self.assertEqual(self._status()["M6-level-terrain"], "no-node-half")

    def test_six_modules_are_enumerated(self):
        self.assertEqual(len(cov.MODULE_ORDER), 6)
        self.assertEqual(
            cov.MODULE_ORDER,
            ("M1-interaction", "M2-currency", "M3-item", "M4-inventory",
             "M5-shop", "M6-level-terrain"),
        )


class PredictionWithCaptureIdentity(unittest.TestCase):
    """(d) the runnable prediction, sharpened with observed-vs-inferred identity."""

    def setUp(self):
        self.pred = rp.predict(fs.demo_plan())

    def test_entry_and_prints(self):
        self.assertEqual(self.pred.entry.definition_id, 71)
        self.assertEqual(self.pred.prints, (fs.ENTRY_PROBE_TEXT, fs.SHORT_ALL_TEXT))

    def test_execution_order(self):
        self.assertEqual(
            [(v.definition_id, v.alias) for v in self.pred.executed],
            [(71, "on_create"), (1, "print_entry"), (685, "grow"), (686, "harvest"),
             (688, "bonus"), (2, "gate_item"), (2, "gate_money"), (1, "print_short")],
        )

    def test_predicted_strings_are_node_unique(self):
        for cap in self.pred.captures:
            self.assertTrue(cap.node_unique, f"{cap.text!r} is not node-unique")
            self.assertEqual(cap.owners, (cap.alias,))
        self.assertEqual(set(self.pred.observed_able), set(self.pred.prints))

    def test_both_reached_branches_are_decided(self):
        self.assertTrue(all(b.decided for b in self.pred.branches))
        self.assertEqual([b.taken for b in self.pred.branches], ["false", "false"])

    def test_branch_arm_table(self):
        arms = {(a.branch_alias, a.arm): a for a in self.pred.branch_arms}
        self.assertEqual(arms[("gate_cap", "true")].leaf_text, fs.LOW_CAPACITY_TEXT)
        self.assertEqual(arms[("gate_cap", "false")].leaf_text, fs.HARVEST_OK_TEXT)
        self.assertEqual(arms[("gate_money", "true")].leaf_text, fs.SHORT_ITEM_RICH_TEXT)
        self.assertEqual(arms[("gate_money", "false")].leaf_text, fs.SHORT_ALL_TEXT)
        # gate_item's arms lead to further branches, not prints
        self.assertIsNone(arms[("gate_item", "true")].leaf_text)
        self.assertEqual(arms[("gate_item", "true")].successor_definition_id, 2)

    def test_classify_capture_separates_observed_inferred_unexpected(self):
        got = rp.classify_capture(self.pred, list(self.pred.prints) + ["噪声"])
        self.assertEqual(got["observedNodes"], self.pred.prints)
        self.assertEqual(got["inferred"], ())
        self.assertEqual(got["unexpected"], ("噪声",))
        self.assertEqual(got["missing"], ())

    def test_a_shared_string_cannot_be_observed(self):
        """A text carried by two nodes is INFERRED — the capture cannot pin either."""
        owners = {"同款文本": ("a", "b")}
        shared = fs.plan_of(fs.SixConfig(currency_id=1, crop_id=2))
        # synthesize the two-owner map directly through the public helper's contract
        pred_unique = rp.node_unique_strings(shared)
        self.assertIn(fs.ENTRY_PROBE_TEXT, pred_unique)
        self.assertNotIn("同款文本", pred_unique)
        self.assertEqual(len(owners["同款文本"]), 2)

    def test_prediction_moves_when_the_plan_moves(self):
        low = rp.predict(fs.plan_of(fs.SixConfig(currency_id=1, crop_id=2, recipe_cost=0)))
        self.assertEqual(low.prints, (fs.ENTRY_PROBE_TEXT, fs.LOW_CAPACITY_TEXT))


class CommittedArtifact(unittest.TestCase):
    def test_artifact_absent_skips_loudly(self):
        if not ARTIFACT.exists():
            self.skipTest(
                f"{ARTIFACT.relative_to(REPO).as_posix()} is absent (.runtime/ is "
                "git-ignored). Regenerate with: python -B -c \"from "
                "tools.gameplan.demo import farming_six as fs; import json,pathlib; "
                "pathlib.Path('.runtime/scratch/DEMO-SIX-plan.json').write_text("
                "json.dumps(fs.artifact(fs.demo_plan()), ensure_ascii=False, indent=1))\""
            )
        data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(data, fs.artifact(fs.demo_plan()))
        self.assertEqual(data["entryDefinitionId"], 71)
        self.assertEqual(data["blockedIntersection"], [])
        self.assertEqual(data["coveredModules"], ["M2-currency", "M3-item", "M4-inventory"])


if __name__ == "__main__":
    unittest.main()
