"""#4 THE DEMO THROUGH TESTS — the ONE suite that IS the demo contract.

Every other demo test owns exactly one slice:

* ``test_run_demo.py`` — the runner's own order / gates / dry-run / refusal stubs;
* ``test_batch_flow.py`` — the batched graph flow in isolation against a fake;
* ``test_builder.py`` — the builder's journal / budget;
* ``test_demo_end_to_end.py`` — a composed run of the eight demo steps;
* ``test_demo_contract.py`` / ``test_e2e_farming_full_contract.py`` / ``test_farming_all.py``
  — the plan *shape*, its serialisation, and the module tables.

This file is the **single place** that asserts the *whole* #4 contract at once, in
one ordered pass with one injected runner: the tile-grid plan, the graph
``create`` → ``lookup`` → ``build-plan`` → ``inspect`` (read-back matches), the
``bind``, the ``export``, the native ``save``, the independent on-disk ``verify``
and — last, gate-free — the read-only component read.  It does not repeat the
per-slice assertions above; it *composes* them and adds the clauses none of them
covers:

(a) the exact ordered pipeline, every **write** step carrying its gate and the
    final read carrying none;
(b) the four failure modes the goal names — a read-back mismatch, a missing
    review (refused *before* the first mutation), a lease expiry stopping
    ``partial=True``, and a malformed component reply (refused, never read as
    "no components");
(c) that the graph covers every module table — the node halves M1–M5 plus M6's
    placement half (the tile grid).

The runner is injected; the graph phase drives the **real**
:class:`~tools.gameplan.builder.GraphBuilder` against one
:class:`~tools.gameplan.testing.FakeBridge`, so the journal, the identity gate
and the read-back guard all apply.  Offline only: no bridge, editor, game, queue
or ``.gil`` under the repo is touched; the one artifact written is the
``create-batch`` plan, under ``tmp``.

Anchors (file:line) for the claims below:

* the eight demo steps and their order — ``demo/run_demo.py:86-95``;
* the two review-gated native writes and the three read-only steps —
  ``demo/run_demo.py:100-104``; the review gate — ``demo/run_demo.py:341-354``;
* the run's one entry point and its execute path — ``demo/run_demo.py:427-442``;
* the batched graph phase and its dispatch order — ``builder.py:480-517``;
* the independent read-back guard — ``builder.py:508-513``;
* the op budget that models the five-minute lease cap — ``builder.py:236-239``;
* the canonical component probe argv — ``component_sweep.py:342-364``;
* a malformed probe reply is refused, never "no components" —
  ``component_sweep.py:220-240`` and ``editor_steps.py:252-302``;
* the module tables — ``demo/farming_all.py:136-175``;
* the module registry / the absent M6 node half — ``modules/__init__.py:24-30``,
  ``nodes.py:158-167``;
* M6b, the placement half, is the tile grid — ``placement.py:41-42``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan import editor_steps
from tools.gameplan.builder import GraphBuilder
from tools.gameplan.component_sweep import (
    COMPONENT_OP,
    interpret_reply,
    probe_argv as component_probe_argv,
)
from tools.gameplan.demo import run_demo as demo
from tools.gameplan.demo.farming_all import (
    MODULE_NODE_IDS,
    FarmAllConfig,
    covered_modules,
    module_coverage,
    plan_of,
)
from tools.gameplan.demo.farming_full import FarmFullConfig, build_plan
from tools.gameplan.modules import MODULES
from tools.gameplan.nodes import ALL_NODE_TYPES
from tools.gameplan.placement import TILE_FIELD
from tools.gameplan.testing import ERROR_LEASE_REFUSED, FakeBridge

#: The canonical editor-asset ids every demo test freezes (test_farming_full /
#: test_demo_contract / test_batch_flow / test_demo_end_to_end all use these).
CONFIG = FarmFullConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

NAME = "MW_API_FARM_DEMO"
RUN_ID = "7588c713-fb80-433a-afce-c0f89cf13d96"
#: One live scope: the fake's graph id is the id every ``--graph-id`` must name
#: for the bridge's identity gate to pass (``testing.py:272-276``).
GRAPH_ID = 1073741900
ENTITY_ID = 1077936129
LEVEL_ID = 1073741842

#: The canonical module→definitionId table (``demo/farming_all.py:136``); the
#: graph's definitionId set must intersect every entry (see clause (c)).
MODULE_TABLES = MODULE_NODE_IDS

#: The ordered pipeline the goal names, as the *logical* steps a reader counts.
#: ``create``/``lookup``/``build-plan``/``inspect`` are the batch graph phase
#: (``builder.py:480-517``); ``bind``/``export`` are the demo's own steps;
#: ``verify-on-disk`` and ``component-read`` close it.
REQUIRED_PIPELINE = (
    "tile-grid",
    "create",
    "lookup",
    "build-plan",
    "inspect",
    "bind",
    "export",
    "save",
    "verify-on-disk",
    "component-read",
)


def _step_of(argv: list[str]) -> str:
    """Which of the eight demo steps an argv performs (mirrors ``demo._demo_step``).

    Ordering matters: the ``build-plan`` argv names the CLI module, the
    ``create-batch`` argv names ``scene_cli``, the component read names the op --
    so nothing is misclassified.
    """
    if "create-batch" in argv:
        return "create-batch"
    if any("verify-created-save.py" in a for a in argv):
        return "verify"
    if "--op" in argv and COMPONENT_OP in argv:
        return "component-read"
    if "tools.gameplan.cli" in argv:
        return "build-plan"
    if "graph" in argv:
        return argv[argv.index("graph") + 1]        # inspect / bind / export
    if any(a == "save" for a in argv):
        return "save"
    return "?"


class FullPipelineRunner:
    """One injected runner that drives the whole #4 pipeline in one live scope.

    The ``build-plan`` step runs the **real** builder against a single
    :class:`FakeBridge` (so the journal, the identity gate and the read-back
    guard all apply); the non-graph steps answer as the scene CLI / ``author.py``
    / the on-disk verifier / the component probe would.  Every argv is recorded,
    the graph phase's :class:`~tools.gameplan.builder.BuildResult` is kept, and
    the component read's reply is exposed for the oracle checks.

    ``op_budget`` switches the graph phase to the builder's **per-op** path with
    ``max_ops`` set -- the documented model of the five-minute lease cap
    (``builder.py:236-239``); it is the resumable path that stops ``partial=True``.
    ``components_reply`` overrides what the read-only probe returns, so a
    malformed reply can be injected (see clause (b)).
    """

    def __init__(self, plan, bridge: FakeBridge, *, tmp: Path,
                 op_budget: int | None = None, components_reply: dict | None = None):
        self.plan = plan
        self.bridge = bridge
        self.tmp = Path(tmp)
        self.op_budget = op_budget
        self.components_reply = components_reply
        self.calls: list[list[str]] = []            # every argv the pipeline ran
        self.build_result = None                    # the graph phase's BuildResult
        self.batch_plan: dict | None = None         # the create-batch plan it read
        self.components: dict | None = None         # the component read's reply

    def __call__(self, argv: list[str]) -> dict:
        self.calls.append(list(argv))
        step = _step_of(argv)
        if step == "create-batch":
            return self._create_batch(argv)
        if step == "build-plan":
            return self._graph_phase()
        if step in ("inspect", "bind", "export"):
            return self.bridge(argv)                # the same live scope
        if step == "save":
            return {"ok": True, "backend": {"status": "save-ok"}}
        if step == "verify":
            return self._verify(argv)
        if step == "component-read":
            return self._component_read(argv)
        raise AssertionError(f"the pipeline dispatched an unclassified argv: {argv!r}")

    # -- create-batch: the tile grid is a real, readable on-disk plan ---------

    def _create_batch(self, argv: list[str]) -> dict:
        plan_path = Path(argv[argv.index("--plan") + 1])
        assert plan_path.is_file(), f"create-batch dispatched before its plan existed: {plan_path}"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        placements = plan.get("placements")
        assert isinstance(placements, list) and placements, "the plan has no placements"
        self.batch_plan = plan
        return {"ok": True, "backend": {"created": len(placements), "actionStatus": 0}}

    # -- graph phase: the real builder against the fake bridge ----------------

    def _graph_phase(self) -> dict:
        if self.op_budget is not None:
            builder = GraphBuilder(self.plan, self.bridge, run_id=RUN_ID, max_ops=self.op_budget)
            result = builder.build()
        else:
            builder = GraphBuilder(self.plan, self.bridge, run_id=RUN_ID)
            # A tmp plan path keeps the test hermetic (never the shared scratch).
            result = builder.build_batch(plan_path=self.tmp / "batch-plan.json")
        self.build_result = result
        # The CLI prints exactly this (cli.py:91-93), so the pipeline sees the
        # builder's own ok / partial / error -- nothing is translated or dropped.
        return result.evidence()

    # -- verify: the independent on-disk rule, mirrored offline --------------

    def _verify(self, argv: list[str]) -> dict:
        i = next(k for k, a in enumerate(argv) if "verify-created-save.py" in a)
        before, after = Path(argv[i + 1]), Path(argv[i + 2])
        if not (before.is_file() and after.is_file()):
            missing = before if not before.is_file() else after
            return {"ok": False, "error": f"missing on-disk snapshot: {missing}"}
        if before.read_bytes() == after.read_bytes():
            return {"ok": False, "error": "no on-disk change: the save left the .gil identical"}
        return {"ok": True, "backend": {"status": "verified-on-disk",
                                        "before": str(before), "after": str(after)}}

    # -- component-read: the read-only probe ----------------------------------

    def _component_read(self, argv: list[str]) -> dict:
        if self.components_reply is not None:
            self.components = self.components_reply
            return self.components_reply
        entity_id = int(argv[argv.index("--entity-id") + 1])
        self.components = {
            "ok": True,
            "status": "entity-components-editor-model-read-only",
            "entityId": entity_id,
            "entityName": NAME,
            "componentType": "collision-trigger",
            "componentCount": 1,
            "components": [{"id": 8, "enabled": True, "x": 1.0, "y": 2.0}],
            "componentIdSpace": "editor-enum-value-or-native-index-UNVERIFIED",
        }
        return self.components


def _receipt(report: dict, step: str) -> dict:
    """The raw receipt the pipeline kept for ``step`` (halts carry theirs too)."""
    for entry in report["steps"]:
        if entry["step"] == step:
            return entry["receipt"]
    raise AssertionError(f"no step {step!r} in {[e['step'] for e in report['steps']]}")


def _logical_pipeline(runner: FullPipelineRunner) -> list[str]:
    """The ten logical steps the run performed, deduplicated first-seen, in order.

    The batch ``export`` (``builder.py:515-521``) is deliberately *not* counted
    here: it is the artifact dump inside the graph phase, and the demo carries
    its own ``export`` step (``demo/run_demo.py:279-284``) — the one the pipeline
    order names.  Counting it twice would misreport the shape.
    """
    seq: list[str] = []
    for argv in runner.calls:
        step = _step_of(argv)
        if step == "create-batch":
            seq.append("tile-grid")
        elif step == "build-plan":
            seq.extend(s.name for s in runner.build_result.steps if s.name != "export")
        elif step in ("inspect", "bind", "export"):
            seq.append(step)
        elif step == "save":
            seq.append("save")
        elif step == "verify":
            seq.append("verify-on-disk")
        elif step == "component-read":
            seq.append("component-read")
        else:  # pragma: no cover - a bug in _step_of would land here
            raise AssertionError(f"unclassified argv: {argv!r}")
    seen: set[str] = set()
    out: list[str] = []
    for name in seq:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


class DemoFullCase(unittest.TestCase):
    """A hermetic tmp dir, the real demo plan, both reviews and two .gil files."""

    tmp: Path

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.plan = build_plan(CONFIG, name=NAME)
        # Two DIFFERENT on-disk snapshots: a save that changed the .gil.
        self.before = self.tmp / "before.gil"
        self.after = self.tmp / "after.gil"
        self.before.write_bytes(b"MW_API_FARM_DEMO\x00BEFORE")
        self.after.write_bytes(b"MW_API_FARM_DEMO\x00AFTER\x01")

    def tearDown(self):
        self._tmp.cleanup()

    def reviews(self, *, steps=demo.REVIEW_STEPS) -> dict[str, str | None]:
        m: dict[str, str | None] = {}
        for step in demo.REVIEW_STEPS:
            if step in steps:
                path = self.tmp / f"{step}-review.json"
                path.write_text("{}", encoding="utf-8")
                m[step] = str(path)
            else:
                m[step] = None
        return m

    def config(self, **kw) -> demo.DemoConfig:
        base = dict(
            queue_dir=self.tmp / "queue",
            level_id=LEVEL_ID,
            template_id=TILE_FIELD,
            origin=(1.0, 2.0, 3.0),
            name=NAME,
            run_id=RUN_ID,
            graph_id=GRAPH_ID,
            entity_id=ENTITY_ID,
            currency_id=CONFIG.currency_id,
            crop_id=CONFIG.crop_id,
            food_id=CONFIG.food_id,
            batch_plan_path=self.tmp / "plots.json",
            verify_out=self.tmp / "verify.json",
            before_gil=self.before,
            after_gil=self.after,
            reviews=self.reviews(),
        )
        base.update(kw)
        return demo.DemoConfig(**base)

    def runner(self, *, readback_definitions=None, op_budget=None,
               components_reply=None, bridge=None) -> FullPipelineRunner:
        bridge = bridge or FakeBridge(graph_id=GRAPH_ID, readback_definitions=readback_definitions)
        return FullPipelineRunner(self.plan, bridge, tmp=self.tmp, op_budget=op_budget,
                                  components_reply=components_reply)

    def run_pipeline(self, *, runner, config=None, **cfg_kw) -> dict:
        cfg = config if config is not None else self.config(**cfg_kw)
        return demo.run(cfg, execute=True, runner=runner, plan_writer=demo.write_batch_plan)


# =====================================================================================
# (2) the whole automatable pipeline, in order, every gate
# =====================================================================================

class TestTheWholePipelineInOrder(DemoFullCase):
    def test_the_logical_pipeline_is_exactly_the_required_order(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        self.assertTrue(report["ok"], report)
        # the ten logical steps the goal names, in order, once each.
        self.assertEqual(_logical_pipeline(r), list(REQUIRED_PIPELINE))

    def test_the_eight_demo_steps_run_once_each_in_canonical_order(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        self.assertEqual([s["step"] for s in report["steps"]], list(demo.STEP_ORDER))
        self.assertEqual([_step_of(argv) for argv in r.calls], list(demo.STEP_ORDER))
        self.assertEqual(len(r.calls), len(demo.STEP_ORDER))
        self.assertIsNone(report["haltedAt"])

    def test_the_tile_grid_is_planned_then_read_by_create_batch(self):
        r = self.runner()
        cfg = self.config()
        self.run_pipeline(runner=r, config=cfg)
        # create-batch read a real on-disk plan: rows*cols placements, scene_cli shape.
        self.assertTrue(cfg.plan_path().is_file())
        self.assertEqual(len(r.batch_plan["placements"]), cfg.rows * cfg.cols)
        self.assertEqual(set(r.batch_plan["placements"][0]),
                         {"template_id", "position", "rotation", "scale"})
        # and it ran first, before any graph op (demo/run_demo.py:239-245).
        self.assertEqual(_step_of(r.calls[0]), "create-batch")

    def test_the_graph_phase_creates_looks_up_builds_and_reads_back(self):
        r = self.runner()
        self.run_pipeline(runner=r)
        self.assertTrue(r.build_result.ok, r.build_result.error)
        # builder.py:480-517 -- the batched flow, in order.
        self.assertEqual([s.name for s in r.build_result.steps],
                         ["create", "lookup", "build-plan", "inspect", "export"])
        # ...and the demo's own inspect/bind/export follow through the same scope.
        self.assertEqual(r.bridge.dispatched,
                         ["create", "lookup", "build-plan", "inspect", "export",
                          "inspect", "bind", "export"])

    def test_the_inspect_readback_matches_the_plan(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        expected = [n.definition_id for n in self.plan.nodes]
        # the builder's INDEPENDENT read-back (builder.py:508-513) agreed...
        self.assertTrue(r.build_result.ok, r.build_result.error)
        self.assertEqual(len(r.build_result.node_ids), len(self.plan.nodes))
        # ...and so did the demo's second, standalone inspect step.
        readback = [n["definitionId"] for n in _receipt(report, "inspect")["backend"]["nodes"]]
        self.assertEqual(readback, expected)

    def test_bind_names_the_node_count_of_the_plan_being_built(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        backend = _receipt(report, "bind")["backend"]
        self.assertEqual(backend["entityId"], ENTITY_ID)
        self.assertEqual(backend["graphId"], GRAPH_ID)
        self.assertEqual(backend["status"], "binding-requested-readback-pending")
        # the count is the REAL node count of the plan the build dispatched, not a guess
        # (demo/run_demo.py:194-204).
        bind_argv = next(s["argv"] for s in report["steps"] if s["step"] == "bind")
        self.assertEqual(bind_argv[bind_argv.index("--expected-node-count") + 1],
                         str(len(self.plan.nodes)))

    def test_export_save_and_the_independent_on_disk_verify(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        # export is the adapter's export invocation (testing.py:385-398).
        self.assertEqual(_receipt(report, "export")["backend"]["status"], "invoked-not-confirmed")
        # save ran (native write)...
        self.assertTrue(_receipt(report, "save")["ok"])
        # ...and verify proved the change on disk, not from the save receipt.
        verify = _receipt(report, "verify")["backend"]
        self.assertEqual(verify["status"], "verified-on-disk")
        self.assertEqual(verify["before"], str(self.before))
        self.assertEqual(verify["after"], str(self.after))

    def test_the_component_read_is_last_and_reads_the_bound_entity(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        self.assertEqual(report["steps"][-1]["step"], "component-read")   # last
        self.assertEqual(_step_of(r.calls[-1]), "component-read")          # last dispatched
        self.assertEqual(r.components["entityId"], ENTITY_ID)              # the bound entity
        # it is the one and only step that probes components, and it uses the
        # canonical argv (component_sweep.py:342-364).
        self.assertEqual([s.name for s in demo.build_sequence(self.config())
                          if "--op" in s.argv], ["component-read"])
        expected = component_probe_argv(ENTITY_ID, run_id=RUN_ID,
                                        queue_dir=str(self.tmp / "queue"), python="python")
        self.assertEqual(report["steps"][-1]["argv"], expected)


class TestEveryWriteStepCarriesItsGate(DemoFullCase):
    def test_only_the_native_writes_are_review_gated(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        gated = [s["step"] for s in report["steps"] if "--review" in s["argv"]]
        self.assertEqual(gated, list(demo.REVIEW_STEPS))
        self.assertEqual(set(gated), {"create-batch", "save"})
        # every gate names a review file that really exists right now.
        for step in report["steps"]:
            if "--review" in step["argv"]:
                path = Path(step["argv"][step["argv"].index("--review") + 1])
                self.assertTrue(path.is_file(), step["step"])

    def test_every_write_step_and_only_a_write_step_is_gated(self):
        for step in demo.build_sequence(self.config()):
            self.assertEqual("--review" in step.argv, step.native_write, step.name)

    def test_the_final_read_is_gate_free(self):
        last = demo.build_sequence(self.config())[-1]
        self.assertEqual(last.name, "component-read")
        self.assertTrue(last.read_only)
        self.assertFalse(last.native_write)
        self.assertNotIn("--review", last.argv)


# =====================================================================================
# (3) the four failure modes
# =====================================================================================

class TestReadbackMismatchFailsTheRun(DemoFullCase):
    def _broken(self) -> list[int]:
        defs = [n.definition_id for n in self.plan.nodes]
        defs[-1] = 1 if defs[-1] != 1 else 2                 # a definition never planned
        return defs

    def test_the_run_halts_at_build_plan_and_the_error_is_not_swallowed(self):
        broken = self._broken()
        r = self.runner(readback_definitions=broken)
        report = self.run_pipeline(runner=r)
        self.assertFalse(report["ok"], "a read-back that disagrees must not report success")
        self.assertEqual(report["haltedAt"], "build-plan")
        # the failure surfaced, named, with BOTH sides (builder.py:510-513).
        self.assertIn("readback mismatch", report["receipt"]["error"])
        self.assertIn(str(broken), report["receipt"]["error"])
        self.assertIn(str([n.definition_id for n in self.plan.nodes]),
                      report["receipt"]["error"])
        # it stopped the RUN -- no step past build-plan dispatched.
        self.assertEqual([s["step"] for s in report["steps"]], ["create-batch", "build-plan"])
        self.assertEqual(r.bridge.dispatched, ["create", "lookup", "build-plan", "inspect"])
        self.assertNotIn("bind", r.bridge.dispatched)
        self.assertNotIn("export", r.bridge.dispatched)

    def test_an_agreeing_readback_is_the_control(self):
        # The negative control: the identical flow with the plan's own definitions
        # completes, so the halt above proves the guard, not an always-failing path.
        r = self.runner(readback_definitions=[n.definition_id for n in self.plan.nodes])
        report = self.run_pipeline(runner=r)
        self.assertTrue(report["ok"], report)


class TestMissingReviewRefusesBeforeTheFirstMutation(DemoFullCase):
    def test_refusal_touches_nothing(self):
        r = self.runner()
        report = self.run_pipeline(runner=r, reviews={})
        self.assertEqual(report["mode"], "refused")
        self.assertFalse(report["ok"])
        self.assertEqual(set(report["missing"]), {"create-batch", "save"})
        self.assertEqual(r.calls, [])                            # nothing dispatched...
        self.assertFalse((self.tmp / "plots.json").is_file())    # ...and no artifact written

    def test_a_missing_save_review_alone_still_refuses_the_run(self):
        r = self.runner()
        report = self.run_pipeline(runner=r, reviews=self.reviews(steps=("create-batch",)))
        self.assertEqual(report["mode"], "refused")
        self.assertEqual(report["missing"], ["save"])
        self.assertEqual(r.calls, [])
        self.assertFalse((self.tmp / "plots.json").is_file())


class TestLeaseExpiryStopsWithPartial(DemoFullCase):
    def test_op_budget_stops_with_partial_and_the_run_halts(self):
        # The op budget IS the documented model of the five-minute lease cap
        # (builder.py:236-239): the graph phase stops early, partial=True -- a
        # resumable stop, NOT a failure.
        r = self.runner(op_budget=3)
        report = self.run_pipeline(runner=r)
        self.assertFalse(report["ok"], "a partial run must not claim success")
        self.assertEqual(report["haltedAt"], "build-plan")
        self.assertTrue(report["receipt"]["partial"], report["receipt"])
        self.assertIn("op budget", report["receipt"]["error"])
        # the builder itself agrees, and stopped at exactly create/lookup/add.
        self.assertTrue(r.build_result.partial)
        self.assertEqual(r.bridge.dispatched, ["create", "lookup", "add"])
        # and the RUN stopped: nothing after the graph phase ran.
        self.assertEqual([s["step"] for s in report["steps"]], ["create-batch", "build-plan"])
        self.assertNotIn("bind", r.bridge.dispatched)

    def test_a_dead_lease_at_the_batched_dispatch_halts_without_claiming_partial(self):
        # The other representation: the batched flow's single build-plan dispatch is
        # refused by a dead lease -- ok=False, the refusal named, run halts.  The
        # batched path has no resume concept, so `partial` must NOT be set.
        bridge = FakeBridge(graph_id=GRAPH_ID, lease_ops=2)   # create+lookup ok, then dead
        r = FullPipelineRunner(self.plan, bridge, tmp=self.tmp)
        report = self.run_pipeline(runner=r)
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "build-plan")
        self.assertEqual(report["receipt"]["error"], "build-plan failed")
        self.assertIn(ERROR_LEASE_REFUSED, r.build_result.steps[-1].result["backend"]["error"])
        self.assertFalse(report["receipt"].get("partial", False))
        self.assertEqual(r.bridge.dispatched, ["create", "lookup"])
        self.assertEqual([s["step"] for s in report["steps"]], ["create-batch", "build-plan"])


class TestMalformedComponentReplyIsRefused(DemoFullCase):
    """A broken reply must never read as "this entity has no components".

    Two independent oracles are exercised on the same reply: the parser
    (``component_sweep.interpret_reply``, ``component_sweep.py:243-269``) and the
    judge (``editor_steps.check_component``, ``editor_steps.py:447-476``).  A
    genuine empty read is the control that proves the refusal is about the
    malformation, not about emptiness.
    """

    #: count says 2, the list is empty -- internally inconsistent, so UNREADABLE.
    MALFORMED = {"ok": True, "entityId": ENTITY_ID, "componentCount": 2, "components": []}
    #: a genuine "the probe ran and found nothing" reply.
    EMPTY = {"ok": True, "entityId": ENTITY_ID, "componentCount": 0, "components": []}

    def _reply_from_a_run(self, reply: dict) -> dict:
        r = self.runner(components_reply=reply)
        report = self.run_pipeline(runner=r)
        self.assertTrue(report["ok"], report)
        return _receipt(report, "component-read")

    def test_a_malformed_reply_is_refused_by_the_parser(self):
        receipt = self._reply_from_a_run(self.MALFORMED)
        result = interpret_reply(ENTITY_ID, 0, json.dumps(receipt))
        self.assertFalse(result.ok)
        self.assertIsNone(result.rows)                    # never rows ...
        self.assertFalse(result.zero_components)          # ... and never "zero components"
        self.assertEqual(result.kind, "malformed")

    def test_a_malformed_reply_is_refused_by_the_judge(self):
        receipt = self._reply_from_a_run(self.MALFORMED)
        verdict = editor_steps.check_component(receipt, required_id=8)
        self.assertIs(verdict.status, editor_steps.Status.REFUSED)
        self.assertTrue(verdict.is_refusal)
        # explicitly NOT a clean negative
        self.assertIsNot(verdict.status, editor_steps.Status.ABSENT)
        self.assertIsNot(verdict.status, editor_steps.Status.INDETERMINATE)
        self.assertIn("REFUSED", editor_steps.describe(verdict))

    def test_a_genuine_empty_read_is_the_control(self):
        # Same pipeline, same oracle: an empty-but-well-formed reply is read as a
        # real absence -- so the refusal above is about the malformation.
        receipt = self._reply_from_a_run(self.EMPTY)
        result = interpret_reply(ENTITY_ID, 0, json.dumps(receipt))
        self.assertTrue(result.ok)
        self.assertTrue(result.zero_components)
        self.assertIs(editor_steps.check_component(receipt, required_id=8).status,
                      editor_steps.Status.ABSENT)

    def test_a_well_formed_reply_with_the_component_reads_present(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        receipt = _receipt(report, "component-read")
        self.assertIs(editor_steps.check_component(receipt, required_id=8).status,
                      editor_steps.Status.PRESENT)


# =====================================================================================
# (4) the graph covers every module table -- the node halves plus M6's placement half
# =====================================================================================

class TestTheGraphCoversEveryModuleTable(DemoFullCase):
    def test_the_demo_graph_covers_every_module_table_it_wires(self):
        # The graph the pipeline actually builds (farming_full) must have a node in
        # each table it claims: M1/M2/M3/M5 (test_demo_contract.py:288-317).
        present = {n.definition_id for n in self.plan.nodes}
        coverage = {module: present & ids for module, ids in MODULE_TABLES.items()}
        for module in ("M1-interaction", "M2-currency", "M3-item", "M5-shop"):
            with self.subTest(module=module):
                self.assertTrue(coverage[module],
                                f"{module} has no node in the demo graph")

    def test_definition_set_covers_each_module_table(self):
        # The canonical all-module graph carries EVERY expressible module half: the
        # plan's definitionId set intersects each module table (test_farming_all.py:182).
        plan = plan_of(FarmAllConfig(currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
                                     food_id=CONFIG.food_id))
        present = {n.definition_id for n in plan.nodes}
        coverage = module_coverage(plan)
        for module, ids in MODULE_TABLES.items():
            with self.subTest(module=module):
                self.assertTrue(
                    coverage[module],
                    f"{module} is not represented: none of {sorted(ids)} is in the plan",
                )
                self.assertEqual(coverage[module], present & ids)

    def test_all_six_module_halves_are_accounted_for(self):
        # The repo counts six modules (docs/gameplan/README.md §五): M1-M5 plus M6.
        # M1-M5 each have a node half (the module registry, modules/__init__.py:24-30);
        # M6 has NO node half (no terrain node in nodes.py), and its half -- placement
        # (M6b) -- is the demo's tile grid.  So the six halves = five node halves +
        # the placement half, and all six are present across demo_full.
        self.assertEqual(len(MODULES), 5)
        self.assertEqual(set(MODULE_TABLES),
                         {"M1-interaction", "M2-currency", "M3-item",
                          "M4-inventory", "M5-shop"})
        # M6: no terrain role at all -- the absence is structural, not an omission.
        self.assertFalse([t for t in ALL_NODE_TYPES if "地形" in t.label],
                         "M6 must have no node half (nodes.py declares no terrain role)")
        # ...and the M6b half IS carried: the demo's tile grid plans TILE_FIELD plots.
        cfg = self.config()
        self.assertEqual(cfg.template_id, TILE_FIELD)
        r = self.runner()
        self.run_pipeline(runner=r, config=cfg)
        self.assertEqual({p["template_id"] for p in r.batch_plan["placements"]}, {TILE_FIELD})
        self.assertEqual(covered_modules(plan_of(FarmAllConfig(
            currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id, food_id=CONFIG.food_id))),
            ("M1-interaction", "M2-currency", "M3-item", "M4-inventory", "M5-shop"))


if __name__ == "__main__":
    unittest.main()
