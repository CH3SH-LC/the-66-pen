"""Offline guard for the RUNNABLE demo (``demo/farming_runnable.py``).

Three things are asserted, none of which needs the bridge, the game, the editor or
the helper:

  (a) **The plan's entry node is ``71``** — the first node placed is ``71`` *and*
      the only entry node (a node whose contract has an execution output and no
      execution input) is ``71``.  The entry is derived from ``data/node-contracts``,
      so this cannot be satisfied by an accident of build order alone.
  (b) **No node in the plan requires a blocked primitive.**  The blocked set is
      *derived* (:func:`farming_runnable.blocked_definition_ids`) from three tables
      already in the tree — the interaction kinds, the farming-minimal event sources
      and the shop module's node tables — never typed out.  The check has a
      **positive control** (the derived set must be non-empty and must contain the
      known blockers ``92``/``702``) and a **negative control** (a plan that *does*
      carry a ``92`` must be flagged), so it can both find things and fail.
  (c) **The plan builds to an ordered native call sequence** — the exact
      ``author.py graph …`` argv list, via the simulated runner, with the node adds
      in plan order.  This is the same projection ``cli farming`` emits; it proves
      the graph is buildable through the real dispatch path, offline.

Read-only and offline: it never dispatches anything.  The one file it *reads* is the
plan artifact ``.runtime/scratch/DEMO-RUNNABLE-plan.json``; if that artifact is absent
(.runtime/ is git-ignored, so it is absent on a fresh checkout) that single test skips
loudly with the regeneration command rather than passing vacuously.

Run::

    python -B -m unittest tools.gameplan.tests.test_demo_runnable
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.gameplan import contracts
from tools.gameplan.builder import GraphBuilder, simulated_runner
from tools.gameplan.demo import farming_runnable as fr
from tools.gameplan.demo.farming_runnable import (
    BLOCKED_DEFINITION_IDS,
    DEMO_CONFIG,
    RunnableConfig,
    build,
    demo_plan,
    entry_definition_ids,
    plan_of,
)
from tools.gameplan.nodes import PROXIMITY_ENTER

REPO = Path(__file__).resolve().parents[3]
ARTIFACT = REPO / ".runtime" / "scratch" / "DEMO-RUNNABLE-plan.json"

#: DefinitionIds the runnable demo must never carry, as a *spot check* on the
#: derived set (the real assertion is the intersection; these make the derivation
#: non-vacuous if a table is ever emptied).
KNOWN_BLOCKED = (PROXIMITY_ENTER.definition_id, 702, 733, 316)
KNOWN_BLOCKED_BY_CONTRACT = (71, 685, 686, 688, 690, 691, 689, 233, 230, 2, 1)


class EntryIsOnCreate(unittest.TestCase):
    """(a) the plan is entered by 71 实体创建时, not by a component-gated event."""

    def test_first_node_placed_is_71(self):
        plan = demo_plan()
        self.assertEqual(
            plan.nodes[0].definition_id, 71,
            f"the demo's first node is {plan.nodes[0].definition_id} "
            f"({plan.nodes[0].alias}); it must be 71 实体创建时 — the entry trigger is "
            "the only thing that needed a component, so it is the one thing that changed.")

    def test_the_only_entry_node_is_71(self):
        plan = demo_plan()
        self.assertEqual(
            entry_definition_ids(plan), (71,),
            "the plan must have exactly one entry node (exec output, no exec input) "
            "and it must be 71; a second entry would be a second, unverified event.")


class NoBlockedPrimitive(unittest.TestCase):
    """(b) no placed node requires a component/template this project cannot author."""

    def test_blocked_derivation_is_non_vacuous(self):
        """Positive control: the derived set really is the blocker set."""
        for definition_id in KNOWN_BLOCKED:
            self.assertIn(
                definition_id, BLOCKED_DEFINITION_IDS,
                f"the derived blocked set lost {definition_id}, a known blocker — the "
                "derivation is broken and the intersection check below would be vacuous.")

    def test_known_satisfiable_ids_are_not_blocked(self):
        """The other direction: config-id readers/writers are NOT blockers."""
        for definition_id in KNOWN_BLOCKED_BY_CONTRACT:
            self.assertNotIn(
                definition_id, BLOCKED_DEFINITION_IDS,
                f"{definition_id} was put in the blocked set; its inputs are a literal "
                "config-id and a controlled entity, so it is placeable and runnable — "
                "excluding it would shrink the demo for no reason.")

    def test_plan_contains_no_blocked_definition_id(self):
        plan = demo_plan()
        offenders = sorted(fr.blocked_in_plan(plan))
        self.assertEqual(
            offenders, [],
            f"the runnable demo carries blocked definitionId(s) {offenders}; the whole "
            "point of this graph is that every node's input is a literal or a node we "
            "control. A blocked node re-introduces the primitive that stopped the old "
            "demo from ever firing.")

    def test_negative_control_a_92_plan_is_flagged(self):
        """The guard must actually fail on a graph that carries a blocked node."""
        g = fr.build(RunnableConfig(currency_id=1, crop_id=2))
        g.place(PROXIMITY_ENTER, "plot_enter")       # 92 — a blocked entry
        g.validate()
        self.assertEqual(
            fr.blocked_in_plan(g.plan), frozenset({PROXIMITY_ENTER.definition_id}),
            "a plan carrying a 92 was not flagged: the negative control failed, so the "
            "'no blocked node' assertion above proves nothing.")


class BuildsToOrderedNativeCalls(unittest.TestCase):
    """(c) the plan compiles to the ordered native call sequence, offline."""

    def _steps(self):
        builder = GraphBuilder(demo_plan(), simulated_runner(graph_id=1073741829),
                               run_id="dry-run")
        return builder.build().steps

    def test_call_sequence_shape_and_order(self):
        steps = self._steps()
        names = [s.summary()["step"] for s in steps]
        plan = demo_plan()
        expected = ["create", "lookup"] + [f"add:{n.alias}" for n in plan.nodes]
        # create, lookup, then one `add` per node in plan order (consts/edges follow
        # as value/wire steps; they are asserted below).
        self.assertEqual(names[: len(expected)], expected,
                         f"native call order drifted: {names[:len(expected)]} != {expected}")

    def test_every_node_add_is_dispatched_and_wired(self):
        steps = self._steps()
        plan = demo_plan()
        adds = [s for s in steps if s.summary()["step"].startswith("add:")]
        self.assertEqual(len(adds), len(plan.nodes))
        # every add carries its own definition id in the argv, in plan order
        defs = [int(s.argv[s.argv.index("--definition-id") + 1]) for s in adds]
        self.assertEqual(defs, [n.definition_id for n in plan.nodes])
        # every edge becomes exactly one wire step
        wires = [s for s in steps if s.summary()["step"].startswith("wire:")]
        self.assertEqual(len(wires), len(plan.edges))

    def test_first_dispatch_is_create_of_the_71_graph(self):
        steps = self._steps()
        first = steps[0]
        self.assertEqual(first.argv[first.argv.index("graph") + 1], "create")
        self.assertEqual(first.argv[first.argv.index("--name") + 1], fr.DEFAULT_NAME)


class ShapeAndCoverage(unittest.TestCase):
    """The graph's shape and which module directions it actually exercises."""

    def test_shape_is_18_nodes_23_edges_15_consts(self):
        plan = demo_plan()
        self.assertEqual((len(plan.nodes), len(plan.edges), len(plan.consts)), (18, 23, 15))

    def test_covered_modules_are_m2_m3_m4(self):
        self.assertEqual(fr.covered_modules(demo_plan()),
                         ("M2-currency", "M3-item", "M4-inventory"))

    def test_m1_and_m5_have_no_runnable_node(self):
        """The modules the demo must drop, and the reason — asserted, not asserted-in-prose."""
        m1_ids = fr.MODULE_NODE_IDS["M1-interaction"]
        m5_ids = fr.MODULE_NODE_IDS["M5-shop"]
        self.assertTrue(m1_ids and m1_ids <= BLOCKED_DEFINITION_IDS,
                        "every M1 interaction entry must be in the blocked set")
        self.assertTrue(m5_ids and m5_ids <= BLOCKED_DEFINITION_IDS,
                        "every M5 shop node must be in the blocked set")

    def test_every_constant_slot_is_writable(self):
        plan = demo_plan()
        for const in plan.consts:
            self.assertIn(const.slot, {"auto", "int", "uint", "enum", "float", "bool", "string"},
                          f"{const.alias} uses slot {const.slot!r}, which the builder cannot encode")


class CommittedArtifact(unittest.TestCase):
    """The plan artifact the wave was asked to produce stays in step with the code."""

    def test_artifact_matches_a_fresh_build(self):
        if not ARTIFACT.exists():
            self.skipTest(
                f"{ARTIFACT.relative_to(REPO).as_posix()} is not in this checkout "
                "(.runtime/ is git-ignored). Regenerate with: "
                "python -B -c \"from tools.gameplan.demo import farming_runnable as fr; "
                "import json,pathlib; p=fr.demo_plan(); "
                "pathlib.Path('.runtime/scratch/DEMO-RUNNABLE-plan.json').write_text("
                "json.dumps(fr.artifact(p), ensure_ascii=False, indent=1))\"")
        data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(data, fr.artifact(demo_plan()),
                         "DEMO-RUNNABLE-plan.json drifted from a fresh build of "
                         "farming_runnable.demo_plan()")

    def test_artifact_entry_is_71_and_no_blocked(self):
        """The artifact itself encodes the two invariants, for a reader who never runs."""
        data = fr.artifact(demo_plan())
        self.assertEqual(data["entryDefinitionId"], 71)
        self.assertEqual(data["blockedIntersection"], [])
        self.assertEqual(data["coveredModules"], ["M2-currency", "M3-item", "M4-inventory"])


class ConfigIsHonest(unittest.TestCase):
    """A caller cannot build the runnable demo without naming real config ids."""

    def test_config_requires_both_config_ids(self):
        with self.assertRaises(TypeError):
            RunnableConfig()  # type: ignore[call-arg]

    def test_plan_name_matches_graph_name_re(self):
        from tools.gameplan.plan import GRAPH_NAME_RE

        self.assertRegex(fr.DEFAULT_NAME, GRAPH_NAME_RE.pattern)

    def test_plan_validates_against_the_contract_store(self):
        # plan_of raises PlanError on any contract drift; a clean call is the proof.
        plan_of(DEMO_CONFIG, name=fr.DEFAULT_NAME)
        store = contracts.default_store()
        for node in demo_plan().nodes:
            self.assertIsNotNone(store.get(node.definition_id))


if __name__ == "__main__":
    unittest.main()
