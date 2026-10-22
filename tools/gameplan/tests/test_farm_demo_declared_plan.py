"""Take the DECLARED farm-demo plan to the EXACT native call sequence — offline.

The demo ("game B") was really built on the machine once: the plan file
``.runtime/scratch/MW_API_FARM_DEMO-plan.json`` was dispatched in ONE
``build-plan`` call and the receipt is ``.runtime/scratch/farm-demo-build.json``
(graphId ``1073741829``, name ``MW_API_FARM_DEMO``, 15 nodes / 17 edges / 13
constants).

Everything in this module is **offline**: the plan is read from disk, loaded
into a :class:`~tools.gameplan.plan.GraphPlan`, validated against
``data/node-contracts``, and driven through the *real*
:class:`~tools.gameplan.builder.GraphBuilder.build_batch` against one
:class:`~tools.gameplan.testing.FakeBridge`.  No bridge, no editor, no game, no
helper, no queue, no ``.gil``: the fake only records argv and answers the
documented reply shapes.  The single artifact written is the builder's own plan
file, under a ``tmp`` dir.

What is pinned here (nothing else in the suite pins all four at once):

1. the declared file IS the demo plan — 15 / 17 / 13 and the frozen definition
   sequence (``docs/gameplan/DEMO-GAP.md:24``);
2. it loads and **validates** against the contract store, and every node
   ``definitionId`` is a *real* contract id (not a typo'd integer);
3. :meth:`GraphBuilder.build_batch` emits the exact ordered op sequence
   ``create -> lookup -> build-plan -> inspect -> export`` with each step's argv
   (including the request id, re-derived as a pure function of that request);
4. the batch payload the builder hands the adapter round-trips **byte-identical**
   to the declared plan file;
5. the demo accounts for all six module directions — each is either *carried*
   by the frozen plan / tile grid, or is the demo graph's own *derived* gap —
   and it FAILS LOUDLY if a module is silently missing.

Claim 5 is the honest one, and the earlier form of it was **false**, not merely
red.  The as-built 15-node demo carries M1/M2/M3/M5 in the graph and M6 in its
tile grid; **M4-inventory places zero nodes**, and that zero is *derived*, never
asserted: the frozen plan IS ``farming_full``'s plan (``demo/run_demo.py``
dispatches ``cli farming --full``), and ``farming_full`` places no M4 node
(``demo/farming_all.py`` module docstring — "``farming_full`` never places a
single M4 node"; the M4-carrying ``farming_all`` has **no build chain** —
``demo/run_demo.py`` never calls it).  The repo records the same zero in prose
(``docs/gameplan/DEMO-GAP.md`` "**M4 ×0**", ``FINAL-STATE.md`` M4 row,
``GOAL-SCORECARD-20261011.md:42,75``).  A guard that demands M4 nodes *in this
plan* therefore demands something the plan cannot have; the truthful guard is
"uncovered == the gap the demo graph's own generator derives".  It keeps the
bite — any *other* module going to zero still fails, and a stale derivation
(a gap that is actually filled) fails too — and it carries a **positive
control**: the all-module plan ``farming_all`` carries ``685``/``689``, so an
empty M4 here is this graph's build chain, not a blind spot in the guard.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan import contracts
from tools.gameplan.builder import GraphBuilder, request_id
from tools.gameplan.demo import farming_all, farming_full
from tools.gameplan.demo.farming_all import MODULE_NODE_IDS
from tools.gameplan.placement import TILE_FIELD, grid, to_batch_plan
from tools.gameplan.plan import GraphPlan
from tools.gameplan.testing import FakeBridge

ROOT = Path(__file__).resolve().parents[3]
PLAN_PATH = ROOT / ".runtime" / "scratch" / "MW_API_FARM_DEMO-plan.json"
BUILD_PATH = ROOT / ".runtime" / "scratch" / "farm-demo-build.json"
PLOTS_PATH = ROOT / ".runtime" / "scratch" / "MW_API_FARM_DEMO-plots.json"

#: The demo identity, read from the machine receipt (``farm-demo-build.json``).
NAME = "MW_API_FARM_DEMO"
GRAPH_ID = 1073741829
RUN_ID = "7588c713-fb80-433a-afce-c0f89cf13d96"
GRAPH_KIND = 20000

#: The declared counts, verbatim from ``docs/gameplan/DEMO-GAP.md:24`` and the
#: ``build-plan`` receipt (``nodeCount: 15``).
NODE_COUNT = 15
EDGE_COUNT = 17
CONST_COUNT = 13

#: The frozen node order the machine built (``docs/gameplan/README.md:109``;
#: ``docs/gameplan/DEMO-GAP.md:56``): the plan file's ``nodes[]`` definitionIds,
#: in order.
ORDERED_DEF_IDS = (92, 686, 733, 690, 233, 2, 686, 686, 1, 92, 702, 701, 688, 684, 1)

#: The ordered graph subcommands ``build_batch`` dispatches (``builder.py:480``).
ORDERED_OPS = ("create", "lookup", "build-plan", "inspect", "export")

#: The six module directions the demo claims (M1–M5 are the graph halves,
#: ``demo/farming_all.py:136``; M6 has no node half and rides the tile grid —
#: ``modules/__init__.py:24-30``, ``placement.py:41-42``).
SIX_MODULE_NAMES = (
    "M1-interaction",
    "M2-currency",
    "M3-item",
    "M4-inventory",
    "M5-shop",
    "M6-plots",
)

#: The 3x3, spacing-4 tile grid the demo's M6 half is (``demo/run_demo.py``).
PLOT_ROWS = 3
PLOT_COLS = 3
PLOT_SPACING = 4.0


# ---------------------------------------------------------------------------
# the loader — the plan file IS ``GraphBuilder.batch_plan_json``'s shape, with
# nodes referenced by index.  Loading it back into a ``GraphPlan`` is what lets
# the real builder re-emit it and dispatch.
# ---------------------------------------------------------------------------
def load_declared_plan(path: Path = PLAN_PATH) -> GraphPlan:
    """Read the batch-shaped plan file back into a validated-ready ``GraphPlan``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan = GraphPlan(name=NAME, graph_kind=GRAPH_KIND)
    aliases = [f"n{i}" for i in range(len(payload["nodes"]))]
    for alias, node in zip(aliases, payload["nodes"]):
        plan.add(alias, node["definitionId"], x=node.get("x", 0), y=node.get("y", 0))
    for edge in payload["edges"]:
        plan.wire(
            aliases[edge["from"]], edge["fromKind"], edge["fromIndex"],
            aliases[edge["to"]], edge["toKind"], edge["toIndex"],
        )
    for value in payload["values"]:
        # A batch value is a one-key ``{"<slot>": payload}`` object (builder._tagged).
        slot, scalar = next(iter(value["value"].items()))
        plan.const(aliases[value["node"]], value["portIndex"], scalar, value["slot"])
    return plan


def _dispatched_action(argv: list[str]) -> str:
    """The ``graph <action>`` subcommand an argv dispatches."""
    return argv[argv.index("graph") + 1]


def run_batch(plan: GraphPlan, bridge: FakeBridge):
    """Run the whole batched flow into a ``tmp`` dir; return (builder, result, written)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{plan.name}-plan.json"
        builder = GraphBuilder(plan, bridge, run_id=RUN_ID)
        result = builder.build_batch(plan_path=path)
        written = path.read_text(encoding="utf-8")
    return builder, result, written


# ---------------------------------------------------------------------------
# 1. the declared file IS the demo plan
# ---------------------------------------------------------------------------
class TestDeclaredPlanFile(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    def test_the_counts_are_the_declared_15_17_13(self):
        self.assertEqual(len(self.payload["nodes"]), NODE_COUNT)
        self.assertEqual(len(self.payload["edges"]), EDGE_COUNT)
        self.assertEqual(len(self.payload["values"]), CONST_COUNT)

    def test_the_ordered_definition_ids_are_frozen(self):
        got = tuple(n["definitionId"] for n in self.payload["nodes"])
        self.assertEqual(got, ORDERED_DEF_IDS)

    def test_the_machine_receipt_matches_the_plan(self):
        # The receipt is the *other* half of the pair: same graph id, same count.
        receipt = json.loads(BUILD_PATH.read_text(encoding="utf-8"))
        self.assertIs(receipt["ok"], True)
        self.assertEqual(receipt["graphId"], GRAPH_ID)
        build = next(s for s in receipt["steps"] if s["step"] == "build-plan")
        self.assertEqual(build["nodeCount"], NODE_COUNT)

    def test_the_demo_identity_is_a_legal_graph_name(self):
        from tools.gameplan.plan import GRAPH_NAME_RE

        self.assertIsNotNone(GRAPH_NAME_RE.match(NAME))


# ---------------------------------------------------------------------------
# 2. load + validate + every definitionId is a REAL contract id
# ---------------------------------------------------------------------------
class TestLoadAndValidate(unittest.TestCase):
    def setUp(self):
        self.plan = load_declared_plan()
        self.store = contracts.default_store()

    def test_the_plan_validates_against_the_contract_store(self):
        # Raises PlanError (not an assert) if any node/edge/const is inconsistent.
        self.plan.validate(self.store)

    def test_every_node_definition_id_is_a_real_contract_id(self):
        for node in self.plan.nodes:
            with self.subTest(definition_id=node.definition_id):
                self.assertIsNotNone(
                    self.store.get(node.definition_id),
                    f"definitionId {node.definition_id} is not in the contract store",
                )

    def test_the_loaded_shape_equals_the_declared_shape(self):
        self.assertEqual(len(self.plan.nodes), NODE_COUNT)
        self.assertEqual(len(self.plan.edges), EDGE_COUNT)
        self.assertEqual(len(self.plan.consts), CONST_COUNT)
        self.assertEqual(
            tuple(n.definition_id for n in self.plan.nodes), ORDERED_DEF_IDS
        )


# ---------------------------------------------------------------------------
# 3. the exact ordered native call sequence
# ---------------------------------------------------------------------------
class TestOfflineBuildBatch(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge(graph_id=GRAPH_ID)
        self.plan = load_declared_plan()
        self.builder, self.result, self.written = run_batch(self.plan, self.bridge)

    def test_the_build_succeeds_with_the_declared_graph_id(self):
        self.assertTrue(self.result.ok, self.result.error)
        self.assertEqual(self.result.graph_id, GRAPH_ID)
        self.assertEqual(self.result.node_ids, {f"node{i}": i for i in range(1, 16)})

    def test_the_dispatch_order_is_exactly_create_lookup_buildplan_inspect_export(self):
        # ``dispatched`` is the fake's ledger of actions it actually executed, in
        # order; a fresh build must dispatch the five ops once each, no replay.
        self.assertEqual(tuple(self.bridge.dispatched), ORDERED_OPS)
        self.assertEqual(tuple(s.name for s in self.result.steps), ORDERED_OPS)
        self.assertEqual(
            tuple(_dispatched_action(a) for a in self.bridge.calls), ORDERED_OPS
        )

    def test_each_step_carries_its_exact_argv_and_request_id(self):
        # The request id is a pure function of the request (builder.request_id),
        # re-derived here independently of the builder's own bookkeeping.  The
        # ``build-plan`` file path is a tmp path the builder mints, so it is
        # normalised to a placeholder on both sides; its basename is still pinned.
        plan_file = f"<tmp>/{NAME}-plan.json"

        def tail(step: str, rid: str) -> list[str]:
            body = {
                "create": ["--run-id", RUN_ID, "--name", NAME,
                           "--graph-kind", str(GRAPH_KIND)],
                "lookup": ["--run-id", RUN_ID, "--name", NAME],
                "build-plan": ["--run-id", RUN_ID, "--name", NAME,
                               "--graph-id", str(GRAPH_ID), "--expected-node-count", "0",
                               "--plan-file", plan_file],
                "inspect": ["--run-id", RUN_ID, "--name", NAME,
                            "--graph-id", str(GRAPH_ID)],
                "export": ["--run-id", RUN_ID, "--name", NAME,
                           "--graph-id", str(GRAPH_ID)],
            }[step]
            return [step, "--request-id", rid, *body]

        rid_of = {
            "create": request_id(NAME, "create"),
            "lookup": request_id(NAME, "lookup"),
            "build-plan": request_id(NAME, "build-plan", GRAPH_ID),
            "inspect": request_id(NAME, "inspect", GRAPH_ID),
            "export": request_id(NAME, "export", GRAPH_ID),
        }
        head = [
            self.builder.python, "-B", str(self.builder.author_py),
            "--elevated-queue", str(self.builder.queue_dir), "graph",
        ]
        self.assertEqual(len(self.bridge.calls), len(ORDERED_OPS))
        for argv, step in zip(self.bridge.calls, ORDERED_OPS):
            normalised = [plan_file if a.endswith(f"{NAME}-plan.json") else a for a in argv]
            with self.subTest(step=step):
                self.assertEqual(normalised, head + tail(step, rid_of[step]))
                self.assertEqual(
                    argv[argv.index("--request-id") + 1], rid_of[step],
                    f"{step}'s request id must be a function of the request",
                )
        # The builder wrote a plan file literally named <NAME>-plan.json.
        self.assertEqual(Path(self.builder._steps[2].argv[
            self.builder._steps[2].argv.index("--plan-file") + 1]).name,
            f"{NAME}-plan.json")

    def test_the_batch_payload_round_trips_byte_identical(self):
        # The builder re-emits the plan it was given: same bytes the machine sent.
        self.assertEqual(
            self.written, PLAN_PATH.read_text(encoding="utf-8"),
            "build_batch must re-emit the declared plan file verbatim",
        )

    def test_the_dispatched_counts_match_the_declared_counts(self):
        payload = json.loads(self.written)
        self.assertEqual(len(payload["nodes"]), NODE_COUNT)
        self.assertEqual(len(payload["edges"]), EDGE_COUNT)
        self.assertEqual(len(payload["values"]), CONST_COUNT)
        readback = next(s for s in self.result.steps if s.name == "inspect")
        self.assertEqual(readback.backend.get("nodeCount"), NODE_COUNT)


# ---------------------------------------------------------------------------
# 4. the six module directions
# ---------------------------------------------------------------------------
def module_coverage_of_demo() -> dict[str, list[int]]:
    """For each of the six directions, the demo's concrete representatives.

    M1–M5 come from the module-owned role tables (``demo/farming_all.py:136``)
    intersected with the demo graph's definitionIds; M6 is the tile grid (the
    demo's ``-plots.json`` placing ``TILE_FIELD`` tiles).
    """
    plan = load_declared_plan()
    present = frozenset(n.definition_id for n in plan.nodes)
    coverage: dict[str, list[int]] = {
        module: sorted(present & ids) for module, ids in MODULE_NODE_IDS.items()
    }
    plots = json.loads(PLOTS_PATH.read_text(encoding="utf-8"))
    coverage["M6-plots"] = sorted(
        {p["template_id"] for p in plots.get("placements", [])
         if p["template_id"] == TILE_FIELD}
    )
    return coverage


#: The editor-asset ids the demo plan was built at (``golden._DEMO_IDS`` — the
#: same config ``demo/run_demo.py`` and the committed tests use).
DEMO_IDS = dict(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)


def demo_generator_definition_ids() -> frozenset[int]:
    """The definitionIds of the plan the frozen file is *built from*.

    The frozen plan IS ``farming_full.build_plan`` — ``demo/run_demo.py``
    dispatches ``cli farming --full --batch``, which constructs ``farming_full``
    (never the M4-carrying ``farming_all``).  So whatever ``farming_full`` can
    carry is the most the frozen demo graph can carry: a module absent from this
    set is a **derived** gap of the demo graph, not a silent omission.
    """
    plan = farming_full.build_plan(farming_full.FarmFullConfig(**DEMO_IDS))
    return frozenset(n.definition_id for n in plan.nodes)


class TestSixModuleCoverage(unittest.TestCase):
    def test_the_plots_half_is_the_declared_3x3_tile_grid(self):
        # M6's half is placement; the declared plots file must be exactly the
        # canonical 3x3 TILE_FIELD grid (placement.py:68, :148).
        declared = json.loads(PLOTS_PATH.read_text(encoding="utf-8"))
        expected = to_batch_plan(
            grid(template_id=TILE_FIELD, rows=PLOT_ROWS, cols=PLOT_COLS,
                 spacing=PLOT_SPACING)
        )
        self.assertEqual(declared, expected)
        self.assertEqual(len(declared["placements"]), PLOT_ROWS * PLOT_COLS)

    def test_the_graph_carries_m1_m2_m3_m5(self):
        coverage = module_coverage_of_demo()
        for module in ("M1-interaction", "M2-currency", "M3-item", "M5-shop"):
            with self.subTest(module=module):
                self.assertTrue(coverage[module], f"{module} has no node in the demo")

    def test_every_module_is_carried_or_a_gap_of_the_demo_graph(self):
        # The guard the task asks for, in its honest form: a module with ZERO
        # representatives is a silent omission ONLY if the demo graph could have
        # carried it.  Here "could have carried it" is DERIVED from the demo's
        # own generator (``farming_full``), never typed out — so M4's zero is the
        # *explained* gap, and any other zero (or a stale derivation) still fails.
        coverage = module_coverage_of_demo()
        uncovered = {m for m in SIX_MODULE_NAMES if not coverage.get(m)}
        generator_ids = demo_generator_definition_ids()
        derived_gaps = {
            m for m, ids in MODULE_NODE_IDS.items() if not (generator_ids & ids)
        }
        self.assertEqual(
            uncovered, derived_gaps,
            "the demo's uncovered modules must EQUAL the gaps its own graph "
            f"derives; uncovered={sorted(uncovered)} derived={sorted(derived_gaps)} "
            f"(coverage={ {m: coverage.get(m) for m in SIX_MODULE_NAMES} })",
        )
        # Non-vacuous: the demo graph really does derive a gap, so this is not
        # the trivially-true "everything happens to be covered" case.  (If
        # ``farming_full`` ever gains an M4 node the derivation changes and this
        # assertion is what tells you the guard is now vacuous.)
        self.assertTrue(
            derived_gaps,
            "the demo graph derives no gap at all — farming_full now carries "
            "every module, so this guard no longer tests what it claims",
        )

    def test_the_demo_graphs_gap_module_is_expressible_elsewhere(self):
        # POSITIVE CONTROL for the guard above.  The same ``module_coverage``
        # method that finds M4 empty in the demo plan must find it NON-empty in
        # the project's all-module plan — proving (a) the method can find M4 at
        # all, and (b) the demo's zero is its build chain, not our vocabulary.
        demo_m4 = module_coverage_of_demo()["M4-inventory"]
        all_plan = farming_all.plan_of(farming_all.FarmAllConfig(**DEMO_IDS))
        all_m4 = sorted(farming_all.module_coverage(all_plan)["M4-inventory"])
        self.assertEqual(demo_m4, [], "the demo plan unexpectedly carries M4")
        self.assertTrue(
            all_m4,
            "farming_all no longer carries any M4 node — M4 is not expressible "
            "and the demo's gap is no longer merely a build-chain gap",
        )


if __name__ == "__main__":
    unittest.main()
