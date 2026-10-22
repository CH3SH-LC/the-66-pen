"""Offline guard for the MODULE PROBE demo (``demo/farming_module_probe.py``).

The probe closes the gap the previous demos left: it places **one node from each
module the census says is real** and follows each with a **distinct** print, so a
single playtest capture attributes every line to a module.  These tests pin that
shape and, more importantly, prove the claims are *derived*, not typed:

  (a) **the entry is ``71``** — the first node placed and the only entry node
      (a contract with an exec output and no exec input).
  (b) **every module's node is present and reachable** — the module node is a
      chain node (has an exec input) fed from the entry, and its ``then`` drives
      the module's own print.  The whole set is asserted, and a **negative
      control** shows ``covered_modules`` shrinks when a module node is dropped.
  (c) **every print string is unique** — a capture of one line pins one module.
  (d) **the plan serialises** — ``artifact(plan)`` round-trips through ``json``,
      carrying the batch-plan envelope and the ordered native argv list, offline.
  (e) **the defIds are real** — every placed ``definitionId`` is in
      ``data/node-contracts``, and node ``90``'s declared roles are re-derived
      from the contract's ports (not trusted).
  (f) **the prediction covers the FULL string set** — ``runtime_prediction.predict``
      yields exactly :data:`farming_module_probe.PREDICTED_PRINTS`, all
      node-unique, and ``module_print_map`` reproduces the per-module table; a
      **negative control** shows a text change moves the prediction.

Read-only and offline: no bridge, no native call, no save, no playtest.

Run::

    python -B -m unittest tools.gameplan.tests.test_demo_module_probe
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.gameplan import contracts, runtime_prediction as rp
from tools.gameplan.demo import farming_module_probe as fp
from tools.gameplan.nodes import ACTIVATE_COLLISION_TRIGGER, PRINT

REPO = Path(__file__).resolve().parents[3]
ARTIFACT = REPO / ".runtime" / "scratch" / "DEMO-MODPROBE-plan.json"


def _module_def_map() -> dict[int, str]:
    """``definitionId -> module`` for the probe's module nodes (the model's input)."""
    return {nt.definition_id: name for name, nt in fp.CENSUS_MODULE_NODE.items()}


def _exec_successor(plan, alias: str) -> str | None:
    for e in plan.edges:
        if e.src == alias and e.src_kind == 2:
            return e.dst
    return None


class EntryIsOnCreate(unittest.TestCase):
    """(a) the plan is entered by 71 实体创建时."""

    def test_first_node_placed_is_71(self):
        plan = fp.demo_plan()
        self.assertEqual(plan.nodes[0].definition_id, 71)
        self.assertEqual(plan.nodes[0].alias, "on_create")

    def test_the_only_entry_node_is_71(self):
        self.assertEqual(fp.entry_definition_ids(fp.demo_plan()), (71,))


class Shape(unittest.TestCase):
    def test_shape_is_13_nodes_18_edges_15_consts(self):
        plan = fp.demo_plan()
        self.assertEqual((len(plan.nodes), len(plan.edges), len(plan.consts)), (13, 18, 15))

    def test_plan_name_matches_graph_name_re(self):
        from tools.gameplan.plan import GRAPH_NAME_RE

        self.assertRegex(fp.DEFAULT_NAME, GRAPH_NAME_RE.pattern)

    def test_every_constant_slot_is_writable(self):
        for const in fp.demo_plan().consts:
            self.assertIn(const.slot, {"auto", "int", "uint", "enum", "float", "bool", "string"})


class EveryModuleIsPresentAndReachable(unittest.TestCase):
    """(b) each census module has a chain node reachable from the entry."""

    def test_covered_modules_is_all_five_node_modules(self):
        self.assertEqual(
            fp.covered_modules(fp.demo_plan()),
            ("M1-interaction", "M2-currency", "M3-item", "M4-inventory", "M5-shop"),
        )

    def test_each_module_node_is_placed(self):
        present = fp.definition_ids(fp.demo_plan())
        for name, ntype in fp.CENSUS_MODULE_NODE.items():
            with self.subTest(module=name):
                self.assertIn(ntype.definition_id, present)

    def test_each_module_node_is_a_chain_node(self):
        """A chain node has an exec INPUT, so it can be reached from the entry —
        unlike an event, which can only be a second entry."""
        store = contracts.default_store()
        for name, ntype in fp.CENSUS_MODULE_NODE.items():
            with self.subTest(module=name):
                self.assertTrue(store.require(ntype.definition_id).exec_inputs,
                                f"{name} node {ntype.definition_id} is not a chain node")

    def test_each_module_node_then_drives_its_own_print(self):
        plan = fp.demo_plan()
        by_id = {n.definition_id: n.alias for n in plan.nodes}
        for name, ntype in fp.CENSUS_MODULE_NODE.items():
            with self.subTest(module=name):
                succ = _exec_successor(plan, by_id[ntype.definition_id])
                self.assertIsNotNone(succ, f"{name}: module node has no exec successor")
                succ_node = next(n for n in plan.nodes if n.alias == succ)
                self.assertEqual(succ_node.definition_id, PRINT.definition_id)
                text = next(c.value for c in plan.consts
                            if c.alias == succ and c.slot == "string")
                self.assertEqual(text, fp.MODULE_PRINT_TEXT[name])

    def test_negative_control_dropping_a_module_shrinks_coverage(self):
        plan = fp.demo_plan()
        m1_id = fp.CENSUS_MODULE_NODE["M1-interaction"].definition_id
        plan.nodes[:] = [n for n in plan.nodes if n.definition_id != m1_id]
        self.assertNotIn("M1-interaction", fp.covered_modules(plan),
                         "coverage must be a function of the placed nodes; dropping "
                         "the M1 node should remove it.")


class PrintsAreUnique(unittest.TestCase):
    """(c) every print string is distinct, so a capture pins one module."""

    def test_module_print_texts_are_pairwise_distinct(self):
        texts = list(fp.MODULE_PRINT_TEXT.values())
        self.assertEqual(len(texts), len(set(texts)))

    def test_all_plan_string_constants_are_unique(self):
        strings = [c.value for c in fp.demo_plan().consts if c.slot == "string"]
        self.assertEqual(len(strings), len(set(strings)),
                         "two print nodes share a string; a capture could not "
                         "attribute the line to one module.")

    def test_predicted_prints_are_pairwise_distinct(self):
        self.assertEqual(len(fp.PREDICTED_PRINTS), len(set(fp.PREDICTED_PRINTS)))


class PlanSerialises(unittest.TestCase):
    """(d) the artifact round-trips through json and carries the dispatch shape."""

    def test_artifact_serialises(self):
        art = fp.artifact(fp.demo_plan())
        text = json.dumps(art, ensure_ascii=False, indent=1)
        self.assertEqual(json.loads(text)["graphName"], fp.DEFAULT_NAME)

    def test_artifact_invariants(self):
        art = fp.artifact(fp.demo_plan())
        self.assertEqual(art["entryDefinitionId"], 71)
        self.assertEqual(art["nodeCount"], 13)
        self.assertEqual(art["edgeCount"], 18)
        self.assertEqual(art["constCount"], 15)
        self.assertEqual(art["coveredModules"],
                         ["M1-interaction", "M2-currency", "M3-item",
                          "M4-inventory", "M5-shop"])
        self.assertIn("M6-level-terrain", art["unavailableModules"])

    def test_artifact_carries_batch_plan_and_native_calls(self):
        from collections import Counter

        plan = fp.demo_plan()
        art = fp.artifact(plan)
        self.assertIn("batchPlan", art)
        kinds = Counter(s["step"].split(":")[0] for s in art["nativeCalls"])
        # create + lookup + one add per node + one wire per edge + one value/set
        # per const + a trailing export.
        self.assertEqual(kinds["add"], len(plan.nodes))
        self.assertEqual(kinds["wire"], len(plan.edges))
        self.assertEqual(kinds["value"] + kinds["set"], len(plan.consts))
        self.assertEqual(art["nativeCalls"][0]["step"], "create")
        self.assertEqual(art["nativeCalls"][-1]["step"], "export")

    def test_committed_artifact_matches_a_fresh_build(self):
        if not ARTIFACT.exists():
            self.skipTest(
                f"{ARTIFACT.relative_to(REPO).as_posix()} is absent (.runtime/ is "
                "git-ignored). Regenerate with the command in WAVE29AI-RUNBOOK.md.")
        data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(data, fp.artifact(fp.demo_plan()))


class DefIdsAreReal(unittest.TestCase):
    """(e) every placed defId is in the contract store; 90's roles are re-derived."""

    def test_every_placed_definition_id_is_in_the_store(self):
        store = contracts.default_store()
        for node in fp.demo_plan().nodes:
            with self.subTest(alias=node.alias):
                self.assertIsNotNone(store.get(node.definition_id))

    def test_node_90_roles_match_the_contract(self):
        store = contracts.default_store()
        d = store.require(ACTIVATE_COLLISION_TRIGGER.definition_id)
        self.assertEqual(sorted(p.index for p in d.exec_inputs),
                         [ACTIVATE_COLLISION_TRIGGER.exec_in])
        self.assertEqual(sorted(p.index for p in d.exec_outputs),
                         sorted(ACTIVATE_COLLISION_TRIGGER.exec_outs.values()))
        self.assertEqual(sorted(p.index for p in d.ports if p.kind == 3),
                         sorted(ACTIVATE_COLLISION_TRIGGER.ins.values()))
        # the three inputs are exactly entity + int + bool — all satisfiable
        types = {p.name: p.server_param_type for p in d.ports if p.kind == 3}
        self.assertEqual(sorted(types.values()), [1, 3, 4])


class PredictionCoversTheFullStringSet(unittest.TestCase):
    """(f) the offline prediction yields exactly the planned strings, per module."""

    def test_predicted_prints_equal_the_planned_set(self):
        pred = rp.predict(fp.demo_plan())
        self.assertEqual(pred.prints, fp.PREDICTED_PRINTS)

    def test_every_predicted_print_is_node_unique(self):
        plan = fp.demo_plan()
        pred = rp.predict(plan)
        self.assertTrue(all(c.node_unique for c in pred.captures),
                        "a shared string would make the capture unable to attribute "
                        "the line to one print node.")
        self.assertEqual(rp.node_unique_strings(plan), frozenset(fp.PREDICTED_PRINTS))

    def test_module_print_map_matches_the_table(self):
        pred = rp.predict(fp.demo_plan())
        self.assertEqual(rp.module_print_map(pred, _module_def_map()),
                         dict(fp.MODULE_PRINT_TEXT))

    def test_every_module_print_is_attributed_to_its_node(self):
        pred = rp.predict(fp.demo_plan())
        attributed = {mp.module: mp.module_node_definition_id
                      for mp in rp.attribute_module_prints(pred, _module_def_map())
                      if mp.module is not None}
        self.assertEqual(
            attributed,
            {name: nt.definition_id for name, nt in fp.CENSUS_MODULE_NODE.items()},
        )

    def test_negative_control_a_text_change_moves_the_prediction(self):
        """The prediction is a function of the plan, not a constant."""
        plan = fp.demo_plan()
        plan.consts[:] = [
            (c if c.alias != "print_m4"
             else type(c)(alias=c.alias, port_index=c.port_index,
                          value="W29AI-M4-改了", slot=c.slot))
            for c in plan.consts
        ]
        pred = rp.predict(plan)
        self.assertIn("W29AI-M4-改了", pred.prints)
        self.assertNotIn(fp.M4_TEXT, pred.prints)


if __name__ == "__main__":
    unittest.main()
