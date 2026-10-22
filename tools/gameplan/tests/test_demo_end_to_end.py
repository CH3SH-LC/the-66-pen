"""The #4 demo, proved END TO END offline: the WHOLE automatable pipeline in one run.

This file **extends**, and does not duplicate, the tests that already own each
piece:

* ``test_run_demo.py`` — the demo runner's own order / gates / dry-run / refusal;
* ``test_batch_flow.py`` — the batched graph flow (create -> lookup -> build-plan
  -> inspect -> export) in isolation, against :class:`FakeBridge`;
* ``test_builder.py`` — the builder + the one reusable fake's journal / budget;
* ``test_demo_contract.py`` / ``test_e2e_farming_full_contract.py`` — the plan
  *shape* and its serialisation.

What none of them does is **compose** them.  Here a single injected runner drives
``tools/gameplan/demo/run_demo.py`` end to end, and its ``build-plan`` step
actually runs the real :class:`GraphBuilder` against a :class:`FakeBridge` — so
the tile grid, the graph ``create``/``lookup``/``build-plan``/``inspect``, the
``bind``, the ``export``, the native ``save``, the on-disk ``.gil`` verify and the
read-only component read all happen in ONE ordered offline pass, exactly the way
the runbook does it on the machine.

The pipeline the goal names, in full
------------------------------------

``create-batch`` (the 3x3 tile grid) -> graph ``create`` -> ``lookup`` ->
``build-plan`` -> ``inspect`` (the read-back must equal the plan) -> ``bind`` ->
``export`` -> native ``save`` -> on-disk ``verify`` -> ``component-read`` (the
read-only probe on the *bound* entity).

Every assertion is file:line-anchored to the code it pins:

* the eight executable steps and their order — ``demo/run_demo.py:86-95``;
* the two review-gated native writes (``create-batch``/``save``) and the three
  read-only steps — ``demo/run_demo.py:100-104``, ``author.py:139``;
* the graph-phase dispatch order — ``builder.py:480-517``;
* the read-back guard — ``builder.py:508-513``;
* the op budget that models the five-minute lease cap — ``builder.py:236-239``,
  ``:319-321``;
* the component probe is the canonical ``inspect-entity-components`` argv —
  ``component_sweep.py:342-366``.

Offline only: no bridge, editor, game, queue or ``.gil`` under the repo is
touched; the one artifact written is the ``create-batch`` plan, under ``tmp``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan.builder import GraphBuilder
from tools.gameplan.demo import run_demo as demo
from tools.gameplan.demo.farming_full import FarmFullConfig, build_plan
from tools.gameplan.testing import ERROR_LEASE_REFUSED, FakeBridge

#: The canonical editor-asset ids every demo test freezes (test_farming_full /
#: test_demo_contract / test_e2e_farming_full_contract all use the same).
CONFIG = FarmFullConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

NAME = "MW_API_FARM_DEMO"
RUN_ID = "7588c713-fb80-433a-afce-c0f89cf13d96"
#: One live scope: the fake's graph id is the id every ``--graph-id`` must name
#: for the bridge's identity gate to pass (``testing.py:272-276``).
GRAPH_ID = 1073741900
ENTITY_ID = 1077936129


def _step_of(argv: list[str]) -> str:
    """Which of the eight demo steps an argv performs (mirrors ``_demo_step``).

    The order of the tests matters: the ``build-plan`` argv names the CLI module,
    the ``create-batch`` argv names ``scene_cli``, the component read names the op
    -- so nothing is misclassified.
    """
    if "create-batch" in argv:
        return "create-batch"
    if any("verify-created-save.py" in a for a in argv):
        return "verify"
    if "--op" in argv and "inspect-entity-components" in argv:
        return "component-read"
    if "tools.gameplan.cli" in argv:
        return "build-plan"
    if "graph" in argv:
        return argv[argv.index("graph") + 1]        # inspect / bind / export
    if any(a == "save" for a in argv):
        return "save"
    return "?"


class PipelineRunner:
    """One injected runner that models the whole runbook in one live bridge scope.

    The graph steps reuse the *real* builder against a single :class:`FakeBridge`
    (so the journal, the identity gate and the read-back guard all apply); the
    non-graph steps answer as the scene CLI / author.py / the probe would.  It
    records every argv it sees and, for the graph phase, keeps the
    :class:`~tools.gameplan.builder.BuildResult` so a test can inspect
    ``ok`` / ``partial`` / the dispatch order directly.

    ``op_budget`` switches the graph phase to the builder's **per-op** path
    (``GraphBuilder.build``) with ``max_ops`` set -- the documented model of the
    five-minute lease cap (``builder.py:236-239``, ``:319-321``); it is the
    resumable path that stops ``partial=True`` rather than failing.
    """

    def __init__(self, plan, bridge: FakeBridge, *, tmp: Path, op_budget: int | None = None):
        self.plan = plan
        self.bridge = bridge
        self.tmp = Path(tmp)
        self.op_budget = op_budget
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

    # -- verify: mirror the on-disk rule offline ------------------------------

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
        entity_id = int(argv[argv.index("--entity-id") + 1])
        self.components = {
            "entityId": entity_id,
            "componentCount": 2,
            "components": [{"id": 5, "enabled": True}, {"id": 5, "enabled": True}],
        }
        return {"ok": True, **self.components}


def _receipt(report: dict, step: str) -> dict:
    """The raw receipt the pipeline kept for ``step`` (halts carry theirs too)."""
    for entry in report["steps"]:
        if entry["step"] == step:
            return entry["receipt"]
    raise AssertionError(f"no step {step!r} in {[e['step'] for e in report['steps']]}")


class PipelineCase(unittest.TestCase):
    """A hermetic tmp dir, a validated demo plan, both reviews and two .gil files."""

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
            level_id=1073741842,
            template_id=20001965,
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

    def runner(self, *, readback_definitions=None, op_budget=None) -> PipelineRunner:
        bridge = FakeBridge(graph_id=GRAPH_ID, readback_definitions=readback_definitions)
        return PipelineRunner(self.plan, bridge, tmp=self.tmp, op_budget=op_budget)

    def run_pipeline(self, *, runner, config=None, **cfg_kw) -> dict:
        cfg = config if config is not None else self.config(**cfg_kw)
        return demo.run(cfg, execute=True, runner=runner, plan_writer=demo.write_batch_plan)


# =====================================================================================
# (1) the whole pipeline, in order, every gate
# =====================================================================================

class TestWholePipelineOffline(PipelineCase):
    def test_runs_every_step_in_the_canonical_order(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        self.assertTrue(report["ok"], report)
        # (a) exactly the eight canonical steps ran, in order, once each.
        self.assertEqual([s["step"] for s in report["steps"]], list(demo.STEP_ORDER))
        self.assertEqual([_step_of(argv) for argv in r.calls], list(demo.STEP_ORDER))
        self.assertEqual(len(r.calls), len(demo.STEP_ORDER))
        self.assertIsNone(report["haltedAt"])

    def test_the_tile_grid_is_written_then_read_by_create_batch(self):
        r = self.runner()
        cfg = self.config()
        self.run_pipeline(runner=r, config=cfg)
        # create-batch read a real on-disk plan: rows*cols placements, scene_cli shape.
        self.assertTrue(cfg.plan_path().is_file())
        self.assertEqual(len(r.batch_plan["placements"]), cfg.rows * cfg.cols)
        self.assertEqual(set(r.batch_plan["placements"][0]),
                         {"template_id", "position", "rotation", "scale"})
        # and it ran first, before any graph op.
        self.assertEqual(_step_of(r.calls[0]), "create-batch")

    def test_graph_phase_dispatches_create_lookup_build_plan_inspect_export(self):
        r = self.runner()
        self.run_pipeline(runner=r)
        self.assertTrue(r.build_result.ok, r.build_result.error)
        # builder.py:480-517 -- the batched flow, in order.
        self.assertEqual([s.name for s in r.build_result.steps],
                         ["create", "lookup", "build-plan", "inspect", "export"])
        # ...and the demo's own inspect/bind/export follow it through the same scope.
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

    def test_bind_attaches_the_graph_to_the_entity(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        backend = _receipt(report, "bind")["backend"]
        self.assertEqual(backend["entityId"], ENTITY_ID)
        self.assertEqual(backend["graphId"], GRAPH_ID)
        self.assertEqual(backend["status"], "binding-requested-readback-pending")

    def test_export_and_save_and_verify_on_disk(self):
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
        # the read-only steps carry no gate at all.
        for name in demo.READ_ONLY_STEPS:
            argv = next(s["argv"] for s in report["steps"] if s["step"] == name)
            self.assertNotIn("--review", argv, name)

    def test_verify_reads_disk_and_a_no_change_save_halts_the_run(self):
        # The verify gate has teeth: if the save left the .gil byte-identical, the
        # independent on-disk check fails and the RUN halts there -- before the
        # component read, which is after it (demo/run_demo.py:86-95).
        self.after.write_bytes(self.before.read_bytes())
        r = self.runner()
        report = self.run_pipeline(runner=r)
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "verify")
        self.assertIn("no on-disk change", report["receipt"]["error"])
        self.assertEqual(report["steps"][-1]["step"], "verify")
        self.assertNotIn("component-read", [s["step"] for s in report["steps"]])
        self.assertIsNone(r.components)                 # the component read never ran

    def test_missing_review_refuses_before_anything_runs(self):
        r = self.runner()
        report = self.run_pipeline(runner=r, reviews={})
        self.assertEqual(report["mode"], "refused")
        self.assertFalse(report["ok"])
        self.assertEqual(set(report["missing"]), {"create-batch", "save"})
        self.assertEqual(r.calls, [])                        # nothing dispatched...
        self.assertFalse((self.tmp / "plots.json").is_file())  # ...and no artifact written


# =====================================================================================
# (2) the two failure paths: a bad read-back fails the RUN; the lease cap is partial
# =====================================================================================

class TestReadbackMismatchFailsTheRun(PipelineCase):
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
        self.assertIn(str([n.definition_id for n in self.plan.nodes]), report["receipt"]["error"])
        # it stopped the RUN -- no step past build-plan dispatched.
        self.assertEqual([s["step"] for s in report["steps"]], ["create-batch", "build-plan"])
        self.assertEqual(r.bridge.dispatched, ["create", "lookup", "build-plan", "inspect"])
        self.assertNotIn("bind", r.bridge.dispatched)
        self.assertNotIn("export", r.bridge.dispatched)

    def test_an_agreeing_readback_is_the_control(self):
        # The negative control: the identical flow with the plan's own definitions
        # completes, so the halt above proves the guard and not an always-failing path.
        r = self.runner(readback_definitions=[n.definition_id for n in self.plan.nodes])
        report = self.run_pipeline(runner=r)
        self.assertTrue(report["ok"], report)


class TestLeaseCapStopsTheRun(PipelineCase):
    def test_op_budget_stops_with_partial_and_the_run_halts(self):
        # The op budget IS the documented model of the five-minute lease cap
        # (builder.py:236-239, :319-321): the graph phase stops early, partial=True.
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

    def test_a_dead_lease_at_the_batched_dispatch_also_halts_the_run(self):
        # The other representation: the batched flow's single build-plan dispatch is
        # refused by a dead lease -- ok=False, the refusal named, run halts.
        bridge = FakeBridge(graph_id=GRAPH_ID, lease_ops=2)   # create+lookup ok, then dead
        r = PipelineRunner(self.plan, bridge, tmp=self.tmp)
        report = self.run_pipeline(runner=r)
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "build-plan")
        # evidence() carries the pipeline-level error; the refusal itself survives,
        # named, on the failing builder step (the same trace test_batch_flow reads).
        self.assertEqual(report["receipt"]["error"], "build-plan failed")
        self.assertIn(ERROR_LEASE_REFUSED, r.build_result.steps[-1].result["backend"]["error"])
        self.assertFalse(report["receipt"].get("partial", False))
        self.assertEqual(r.bridge.dispatched, ["create", "lookup"])
        self.assertEqual([s["step"] for s in report["steps"]], ["create-batch", "build-plan"])


# =====================================================================================
# (3) the component read is LAST and gate-free
# =====================================================================================

class TestComponentReadIsLastAndGateFree(PipelineCase):
    def test_it_is_the_final_step_of_the_sequence(self):
        steps = demo.build_sequence(self.config())
        self.assertEqual(steps[-1].name, "component-read")
        # ...and the one and only step that probes components.
        self.assertEqual([s.name for s in steps if "--op" in s.argv], ["component-read"])

    def test_it_is_read_only_ungated_and_uses_the_canonical_probe(self):
        step = demo.build_sequence(self.config())[-1]
        self.assertTrue(step.read_only)
        self.assertFalse(step.native_write)
        self.assertNotIn("--review", step.argv)
        self.assertIn("inspect-entity-components", step.argv)   # component_sweep.py:79
        self.assertIn("--entity-id", step.argv)

    def test_it_runs_last_in_the_full_run_and_reads_the_bound_entity(self):
        r = self.runner()
        report = self.run_pipeline(runner=r)
        self.assertEqual(report["steps"][-1]["step"], "component-read")   # last, checked
        self.assertEqual(_step_of(r.calls[-1]), "component-read")          # last dispatched
        # it read the entity the graph was bound to, and nothing else ran after it.
        self.assertEqual(r.components["entityId"], ENTITY_ID)
        self.assertEqual(len(r.components["components"]), r.components["componentCount"])
        self.assertNotIn("--review", report["steps"][-1]["argv"])


if __name__ == "__main__":
    unittest.main()
