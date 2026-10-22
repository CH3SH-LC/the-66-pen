"""Offline tests for the runbook orchestrators — injected runner, no bridge, no game.

Two orchestrators are covered here:

* :mod:`tools.gameplan.run_demo` — the six-step editor pipeline
  (``create -> build-plan -> inspect -> bind -> save -> verify``); its tests are
  the original classes below.
* :mod:`tools.gameplan.demo.run_demo` — the **#7 demo runner**, the fuller eight-step
  pipeline that adds the tile grid (``create-batch``), the graph ``export`` and, last,
  the read-only component read; its tests are the ``...Demo...`` classes appended below.

Four behaviours both turn into contracts:

* a dry run dispatches nothing (and now writes nothing),
* a failing step halts the sequence (no retry, no later step),
* a missing native-write review refuses *before* the first mutation,
* the order is exactly what is specified — and for the demo, ``component-read`` is last.
"""

import tempfile
import unittest
from pathlib import Path

import tools.gameplan.demo.run_demo as demo  # the #7 demo runner (8 steps)
from tools.gameplan.component_sweep import probe_argv as component_probe_argv
from tools.gameplan.run_demo import (
    REVIEW_STEPS,
    STEP_ORDER,
    DemoConfig,
    build_sequence,
    main,
    resolve_reviews,
    review_gate,
    run,
)


def _step(argv: list[str]) -> str:
    """Which of the six steps an argv belongs to (the runner keys off this)."""
    if "entity-create" in argv:
        return "create"
    if "tools.gameplan.cli" in argv:
        return "build-plan"
    if any("verify-created-save.py" in a for a in argv):
        return "verify"
    if "graph" in argv:
        return argv[argv.index("graph") + 1]
    if any(a == "save" for a in argv):
        return "save"
    return "?"


class Recorder:
    """Records every argv and answers like the tools would; can fail one step."""

    def __init__(self, *, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str]) -> dict:
        self.calls.append(list(argv))
        step = _step(argv)
        if step == self.fail_on:
            return {"ok": False, "error": f"synthetic {step} failure", "retryAttempted": False}
        if step == "create":
            return {"ok": True, "backend": {"entityId": 1077936129, "called": 1, "actionStatus": 0}}
        if step == "build-plan":
            return {"ok": True, "graphId": 1073741829, "nodeIds": {"node1": 1073741889}}
        return {"ok": True, "backend": {"status": f"{step}-ok"}}


class Review:
    """A review file that exists only for the steps it is told to."""

    def __init__(self, tmp: Path, steps=("create", "save")):
        self.map: dict[str, str | None] = {}
        for step in REVIEW_STEPS:
            if step in steps:
                path = tmp / f"{step}-review.json"
                path.write_text("{}", encoding="utf-8")
                self.map[step] = str(path)
            else:
                self.map[step] = None


class ConfigCase(unittest.TestCase):
    tmp: Path

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, *, reviews=None, **kw) -> DemoConfig:
        base = dict(
            queue_dir=self.tmp / "queue",
            level_id=1073741842,
            template_id=20001965,
            origin=(1.0, 2.0, 3.0),
            name="MW_API_FARM_DEMO",
            run_id="7588c713-fb80-433a-afce-c0f89cf13d96",
            graph_id=1073741829,
            entity_id=1077936129,
            currency_id=1115684864,
            crop_id=1120000001,
            food_id=1120000002,
        )
        base.update(kw)
        if reviews is None:
            reviews = Review(self.tmp).map
        return DemoConfig(reviews=reviews, **base)


class TestStepOrder(ConfigCase):
    def test_order_is_the_runbook_order(self):
        steps = build_sequence(self.config())
        self.assertEqual([s.name for s in steps], list(STEP_ORDER))
        self.assertEqual(list(STEP_ORDER),
                         ["create", "build-plan", "inspect", "bind", "save", "verify"])

    def test_each_step_is_exactly_one_command(self):
        steps = build_sequence(self.config())
        for step in steps:
            self.assertTrue(step.argv)
            self.assertTrue(all(isinstance(a, str) for a in step.argv))

    def test_only_native_writes_are_review_gated(self):
        steps = build_sequence(self.config())
        gated = {s.name for s in steps if s.native_write}
        self.assertEqual(gated, set(REVIEW_STEPS))
        self.assertEqual(set(REVIEW_STEPS), {"create", "save"})

    def test_review_flag_present_only_on_native_writes(self):
        for step in build_sequence(self.config()):
            has_review = "--review" in step.argv
            self.assertEqual(has_review, step.native_write, step.name)

    def test_commands_match_the_runbook_surface(self):
        steps = {s.name: s.argv for s in build_sequence(self.config())}
        self.assertIn("entity-create", steps["create"])
        self.assertIn("--template-id", steps["create"])
        self.assertIn("--position", steps["create"])
        # build-plan is the batched farming dispatch
        self.assertIn("--batch", steps["build-plan"])
        self.assertIn("--execute", steps["build-plan"])
        self.assertIn("--crop-id", steps["build-plan"])
        # inspect and bind are author.py graph actions
        self.assertIn("inspect", steps["inspect"])
        self.assertIn("bind", steps["bind"])
        self.assertIn("--entity-id", steps["bind"])
        self.assertIn("--graph-id", steps["bind"])
        # save is the author.py scene save
        self.assertIn("save", steps["save"])
        # verify is the independent .gil diff
        self.assertTrue(any("verify-created-save.py" in a for a in steps["verify"]))

    def test_elevated_queue_precedes_graph_subcommand(self):
        steps = {s.name: s.argv for s in build_sequence(self.config())}
        for name in ("inspect", "bind"):
            argv = steps[name]
            self.assertEqual(argv[argv.index("--elevated-queue") + 1], str(self.tmp / "queue"))
            self.assertLess(argv.index("--elevated-queue"), argv.index("graph"))


class TestDryRun(ConfigCase):
    def test_dry_run_executes_nothing(self):
        runner = Recorder()
        report = run(self.config(), execute=False, runner=runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["executed"], 0)

    def test_dry_run_prints_every_command(self):
        report = run(self.config(), execute=False, runner=Recorder())
        commands = [entry["command"] for entry in report["steps"]]
        self.assertEqual(len(commands), len(STEP_ORDER))
        self.assertTrue(all(cmd.strip() for cmd in commands))
        self.assertEqual([e["step"] for e in report["steps"]], list(STEP_ORDER))

    def test_dry_run_needs_no_review(self):
        # Printing what WOULD run must not require the reviews a run needs.
        report = run(self.config(reviews={}), execute=False, runner=Recorder())
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["executed"], 0)

    def test_placeholders_stand_in_for_unknowns(self):
        report = run(self.config(graph_id=None, entity_id=None, run_id=None),
                     execute=False, runner=Recorder())
        joined = "\n".join(e["command"] for e in report["steps"])
        self.assertIn("<GRAPH_ID>", joined)
        self.assertIn("<ENTITY_ID>", joined)
        self.assertIn("<RUN_ID>", joined)


class TestReviewGate(ConfigCase):
    def test_missing_review_refuses_before_the_first_mutation(self):
        runner = Recorder()
        report = run(self.config(reviews={}), execute=True, runner=runner)
        self.assertEqual(runner.calls, [])           # nothing ran, not even create
        self.assertEqual(report["mode"], "refused")
        self.assertEqual(report["executed"], 0)
        self.assertEqual(set(report["missing"]), {"create", "save"})
        self.assertIn("review", report["message"].lower())

    def test_refusal_names_the_missing_step_explicitly(self):
        reviews = Review(self.tmp, steps=("create",)).map   # save review missing
        report = run(self.config(reviews=reviews), execute=True, runner=Recorder())
        self.assertEqual(report["missing"], ["save"])
        self.assertIn("'save'", report["message"])
        self.assertIn("--review save=PATH", report["message"])

    def test_refusal_when_review_path_does_not_exist(self):
        reviews = {"create": str(self.tmp / "nope.json"), "save": None}
        runner = Recorder()
        report = run(self.config(reviews=reviews), execute=True, runner=runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(report["missing"], ["create", "save"])

    def test_absent_reviews_gate_reports_every_native_write(self):
        steps = build_sequence(self.config())
        self.assertEqual(review_gate(steps, {}), list(REVIEW_STEPS))

    def test_resolve_reviews_per_step(self):
        mapped = resolve_reviews([f"create={self.tmp}/c.json", f"save={self.tmp}/s.json"])
        self.assertEqual(mapped["create"], f"{self.tmp}/c.json")
        self.assertEqual(mapped["save"], f"{self.tmp}/s.json")

    def test_resolve_reviews_bare_default(self):
        mapped = resolve_reviews([f"{self.tmp}/shared.json"])
        self.assertEqual(mapped["create"], f"{self.tmp}/shared.json")
        self.assertEqual(mapped["save"], f"{self.tmp}/shared.json")


class TestExecute(ConfigCase):
    def test_execute_runs_all_six_in_order(self):
        runner = Recorder()
        report = run(self.config(), execute=True, runner=runner)
        self.assertTrue(report["ok"], report)
        self.assertEqual([_step(argv) for argv in runner.calls], list(STEP_ORDER))
        self.assertEqual([e["step"] for e in report["steps"]], list(STEP_ORDER))
        self.assertIsNone(report["haltedAt"])

    def test_failing_step_halts_the_sequence(self):
        runner = Recorder(fail_on="inspect")
        report = run(self.config(), execute=True, runner=runner)
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "inspect")
        ran = [_step(argv) for argv in runner.calls]
        self.assertEqual(ran, ["create", "build-plan", "inspect"])
        self.assertNotIn("bind", ran)
        self.assertNotIn("save", ran)
        self.assertNotIn("verify", ran)

    def test_halt_prints_the_raw_receipt(self):
        runner = Recorder(fail_on="bind")
        report = run(self.config(), execute=True, runner=runner)
        self.assertEqual(report["haltedAt"], "bind")
        self.assertEqual(report["receipt"]["error"], "synthetic bind failure")
        self.assertIs(report["receipt"]["ok"], False)

    def test_failure_never_retries(self):
        runner = Recorder(fail_on="save")
        run(self.config(), execute=True, runner=runner)
        saves = [argv for argv in runner.calls if _step(argv) == "save"]
        self.assertEqual(len(saves), 1)               # attempted once, never again
        self.assertFalse(any(argv.count("save") > 1 for argv in saves))

    def test_first_step_failure_runs_nothing_else(self):
        runner = Recorder(fail_on="create")
        report = run(self.config(), execute=True, runner=runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(report["haltedAt"], "create")

    def test_runner_exception_is_a_halt_not_a_crash(self):
        class Boom(Recorder):
            def __call__(self, argv):
                self.calls.append(list(argv))
                if _step(argv) == "build-plan":
                    raise RuntimeError("bridge gone")
                return {"ok": True, "backend": {"status": "ok"}}

        report = run(self.config(), execute=True, runner=Boom())
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "build-plan")
        self.assertIn("bridge gone", report["receipt"]["error"])

    def test_execute_uses_the_injected_runner_only(self):
        runner = Recorder()
        run(self.config(), execute=True, runner=runner)
        self.assertEqual(len(runner.calls), len(STEP_ORDER))


class TestMainCli(ConfigCase):
    @staticmethod
    def _quiet(argv):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            return main(argv)

    def test_main_dry_run_returns_zero(self):
        code = self._quiet(["--queue-dir", str(self.tmp / "q"), "--level-id", "1073741842",
                            "--origin", "1", "2", "3"])
        self.assertEqual(code, 0)

    def test_main_refuses_without_reviews(self):
        code = self._quiet(["--queue-dir", str(self.tmp / "q"), "--level-id", "1073741842",
                            "--execute"])
        self.assertEqual(code, 2)

    def test_config_from_args_maps_reviews(self):
        from tools.gameplan.run_demo import _parser, config_from_args

        args = _parser().parse_args(["--review", f"create={self.tmp}/c.json",
                                     "--review", f"save={self.tmp}/s.json"])
        cfg = config_from_args(args)
        self.assertEqual(cfg.reviews["create"], f"{self.tmp}/c.json")
        self.assertEqual(cfg.reviews["save"], f"{self.tmp}/s.json")


# =====================================================================================
# The #7 demo runner: tools/gameplan/demo/run_demo.py
# =====================================================================================

#: The demo's canonical order, restated literally so a reorder is a test failure.
DEMO_STEP_ORDER = (
    "create-batch", "build-plan", "inspect", "bind", "export", "save", "verify",
    "component-read",
)


def _demo_step(argv: list[str]) -> str:
    """Which of the eight demo steps an argv belongs to (the demo runner keys off this)."""
    if "create-batch" in argv:
        return "create-batch"
    if any("verify-created-save.py" in a for a in argv):
        return "verify"
    if "--op" in argv and "inspect-entity-components" in argv:
        return "component-read"
    if "tools.gameplan.cli" in argv:
        return "build-plan"
    if "graph" in argv:
        return argv[argv.index("graph") + 1]      # inspect / bind / export
    if any(a == "save" for a in argv):
        return "save"
    return "?"


class DemoRecorder:
    """Records every argv and answers like the tools would; can fail one step."""

    def __init__(self, *, fail_on: str | None = None):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, argv: list[str]) -> dict:
        self.calls.append(list(argv))
        step = _demo_step(argv)
        if step == self.fail_on:
            return {"ok": False, "error": f"synthetic {step} failure", "retryAttempted": False}
        if step == "create-batch":
            return {"ok": True, "backend": {"created": 9, "actionStatus": 0}}
        if step == "build-plan":
            return {"ok": True, "graphId": 1073741829, "nodeIds": {"node1": 1073741889}}
        if step == "component-read":
            return {"ok": True, "componentCount": 2,
                    "components": [{"id": 5, "enabled": True}]}
        return {"ok": True, "backend": {"status": f"{step}-ok"}}


class DemoReview:
    """A review file that exists only for the steps it is told to."""

    def __init__(self, tmp: Path, steps=("create-batch", "save")):
        self.map: dict[str, str | None] = {}
        for step in demo.REVIEW_STEPS:
            if step in steps:
                path = tmp / f"{step}-review.json"
                path.write_text("{}", encoding="utf-8")
                self.map[step] = str(path)
            else:
                self.map[step] = None


class DemoCase(unittest.TestCase):
    tmp: Path

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, *, reviews=None, **kw) -> demo.DemoConfig:
        base = dict(
            queue_dir=self.tmp / "queue",
            level_id=1073741842,
            template_id=20001965,
            origin=(1.0, 2.0, 3.0),
            name="MW_API_FARM_DEMO",
            run_id="7588c713-fb80-433a-afce-c0f89cf13d96",
            graph_id=1073741829,
            entity_id=1077936129,
            currency_id=1115684864,
            crop_id=1120000001,
            food_id=1120000002,
            batch_plan_path=self.tmp / "plots.json",
            verify_out=self.tmp / "verify.json",
            before_gil=self.tmp / "before.gil",
            after_gil=self.tmp / "after.gil",
        )
        base.update(kw)
        if reviews is None:
            reviews = DemoReview(self.tmp).map
        return demo.DemoConfig(reviews=reviews, **base)


class TestDemoOrder(DemoCase):
    def test_order_is_the_demo_order(self):
        steps = demo.build_sequence(self.config())
        self.assertEqual([s.name for s in steps], list(DEMO_STEP_ORDER))
        self.assertEqual(list(demo.STEP_ORDER), list(DEMO_STEP_ORDER))

    def test_component_read_is_the_last_step(self):
        steps = demo.build_sequence(self.config())
        self.assertEqual(steps[-1].name, "component-read")
        # ...and the one and only step that calls the component probe.
        probes = [s.name for s in steps if "--op" in s.argv]
        self.assertEqual(probes, ["component-read"])

    def test_component_read_is_read_only_and_has_no_gate(self):
        step = demo.build_sequence(self.config())[-1]
        self.assertEqual(step.name, "component-read")
        self.assertFalse(step.native_write)
        self.assertTrue(step.read_only)
        self.assertNotIn("--review", step.argv)
        self.assertIn("inspect-entity-components", step.argv)

    def test_component_read_reuses_the_canonical_probe(self):
        # With real ids it must be byte-identical to the component sweep's builder.
        step = demo.build_sequence(self.config())[-1]
        expected = component_probe_argv(
            1077936129, run_id="7588c713-fb80-433a-afce-c0f89cf13d96",
            queue_dir=str(self.tmp / "queue"), python="python")
        self.assertEqual(step.argv, expected)

    def test_only_native_writes_are_review_gated(self):
        steps = demo.build_sequence(self.config())
        gated = {s.name for s in steps if s.native_write}
        self.assertEqual(gated, set(demo.REVIEW_STEPS))
        self.assertEqual(set(demo.REVIEW_STEPS), {"create-batch", "save"})

    def test_every_gated_step_carries_a_review_flag(self):
        for step in demo.build_sequence(self.config()):
            has_review = "--review" in step.argv
            self.assertEqual(has_review, step.native_write, step.name)

    def test_read_only_steps_are_never_gated(self):
        for name in demo.READ_ONLY_STEPS:
            self.assertIn(name, DEMO_STEP_ORDER)
            self.assertNotIn(name, demo.REVIEW_STEPS)

    def test_each_step_is_exactly_one_command(self):
        for step in demo.build_sequence(self.config()):
            self.assertTrue(step.argv)
            self.assertTrue(all(isinstance(a, str) for a in step.argv))

    def test_commands_match_the_surface(self):
        steps = {s.name: s.argv for s in demo.build_sequence(self.config())}
        # create-batch: the tile grid, from the batch plan, review-gated.
        self.assertIn("create-batch", steps["create-batch"])
        self.assertIn("--plan", steps["create-batch"])
        self.assertIn("--level-id", steps["create-batch"])
        self.assertIn("--review", steps["create-batch"])
        # build-plan: the batched farming dispatch.
        self.assertIn("--batch", steps["build-plan"])
        self.assertIn("--execute", steps["build-plan"])
        self.assertIn("--crop-id", steps["build-plan"])
        # inspect / bind / export are author.py graph actions.
        self.assertEqual(steps["inspect"][steps["inspect"].index("graph") + 1], "inspect")
        self.assertEqual(steps["bind"][steps["bind"].index("graph") + 1], "bind")
        self.assertEqual(steps["export"][steps["export"].index("graph") + 1], "export")
        self.assertIn("--entity-id", steps["bind"])
        self.assertIn("--graph-id", steps["bind"])
        # save is the author.py scene save, review-gated.
        self.assertIn("save", steps["save"])
        self.assertIn("--review", steps["save"])
        # verify is the independent .gil diff.
        self.assertTrue(any("verify-created-save.py" in a for a in steps["verify"]))
        # component-read is the read-only probe.
        self.assertIn("--op", steps["component-read"])
        self.assertIn("inspect-entity-components", steps["component-read"])
        self.assertIn("--entity-id", steps["component-read"])

    def test_elevated_queue_precedes_graph_subcommand(self):
        steps = {s.name: s.argv for s in demo.build_sequence(self.config())}
        for name in ("inspect", "bind", "export"):
            argv = steps[name]
            self.assertEqual(argv[argv.index("--elevated-queue") + 1], str(self.tmp / "queue"))
            self.assertLess(argv.index("--elevated-queue"), argv.index("graph"))


class TestDemoDryRun(DemoCase):
    def test_dry_run_executes_nothing(self):
        runner = DemoRecorder()
        report = demo.run(self.config(), execute=False, runner=runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["executed"], 0)

    def test_dry_run_writes_nothing(self):
        plan = self.tmp / "plots.json"
        demo.run(self.config(batch_plan_path=plan), execute=False, runner=DemoRecorder())
        self.assertFalse(plan.exists())          # the create-batch artifact is not touched

    def test_dry_run_prints_every_command(self):
        report = demo.run(self.config(), execute=False, runner=DemoRecorder())
        commands = [entry["command"] for entry in report["steps"]]
        self.assertEqual([e["step"] for e in report["steps"]], list(DEMO_STEP_ORDER))
        self.assertTrue(all(cmd.strip() for cmd in commands))

    def test_dry_run_needs_no_review(self):
        report = demo.run(self.config(reviews={}), execute=False, runner=DemoRecorder())
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["executed"], 0)

    def test_placeholders_stand_in_for_unknowns(self):
        report = demo.run(self.config(graph_id=None, entity_id=None, run_id=None),
                          execute=False, runner=DemoRecorder())
        joined = "\n".join(e["command"] for e in report["steps"])
        self.assertIn("<GRAPH_ID>", joined)
        self.assertIn("<ENTITY_ID>", joined)
        self.assertIn("<RUN_ID>", joined)


class TestDemoReviewGate(DemoCase):
    def test_missing_review_refuses_before_the_first_mutation(self):
        plan = self.tmp / "plots.json"
        runner = DemoRecorder()
        report = demo.run(self.config(reviews={}, batch_plan_path=plan),
                          execute=True, runner=runner)
        self.assertEqual(runner.calls, [])       # nothing ran, not even create-batch
        self.assertFalse(plan.exists())          # and the plan artifact was not written
        self.assertEqual(report["mode"], "refused")
        self.assertEqual(report["executed"], 0)
        self.assertEqual(set(report["missing"]), {"create-batch", "save"})
        self.assertIn("review", report["message"].lower())

    def test_refusal_names_the_missing_step_explicitly(self):
        reviews = DemoReview(self.tmp, steps=("create-batch",)).map   # save review missing
        report = demo.run(self.config(reviews=reviews), execute=True, runner=DemoRecorder())
        self.assertEqual(report["missing"], ["save"])
        self.assertIn("'save'", report["message"])
        self.assertIn("--review save=PATH", report["message"])

    def test_refusal_when_review_path_does_not_exist(self):
        reviews = {"create-batch": str(self.tmp / "nope.json"), "save": None}
        runner = DemoRecorder()
        report = demo.run(self.config(reviews=reviews), execute=True, runner=runner)
        self.assertEqual(runner.calls, [])
        self.assertEqual(report["missing"], ["create-batch", "save"])

    def test_absent_reviews_gate_reports_every_native_write(self):
        steps = demo.build_sequence(self.config())
        self.assertEqual(demo.review_gate(steps, {}), list(demo.REVIEW_STEPS))

    def test_resolve_reviews_per_step(self):
        mapped = demo.resolve_reviews([f"create-batch={self.tmp}/c.json",
                                       f"save={self.tmp}/s.json"])
        self.assertEqual(mapped["create-batch"], f"{self.tmp}/c.json")
        self.assertEqual(mapped["save"], f"{self.tmp}/s.json")

    def test_resolve_reviews_bare_default(self):
        mapped = demo.resolve_reviews([f"{self.tmp}/shared.json"])
        self.assertEqual(mapped["create-batch"], f"{self.tmp}/shared.json")
        self.assertEqual(mapped["save"], f"{self.tmp}/shared.json")


class TestDemoExecute(DemoCase):
    def test_execute_runs_all_eight_in_order(self):
        runner = DemoRecorder()
        report = demo.run(self.config(), execute=True, runner=runner)
        self.assertTrue(report["ok"], report)
        self.assertEqual([_demo_step(argv) for argv in runner.calls], list(DEMO_STEP_ORDER))
        self.assertEqual([e["step"] for e in report["steps"]], list(DEMO_STEP_ORDER))
        self.assertIsNone(report["haltedAt"])

    def test_execute_writes_the_plan_artifact_before_dispatching(self):
        plan = self.tmp / "plots.json"
        writes: list[Path] = []

        def plan_writer(cfg):
            writes.append(cfg.plan_path())
            return cfg.plan_path()

        report = demo.run(self.config(batch_plan_path=plan), execute=True,
                          runner=DemoRecorder(), plan_writer=plan_writer)
        self.assertTrue(report["ok"])
        self.assertEqual(writes, [plan])

    def test_write_batch_plan_produces_the_scene_cli_shape(self):
        import json

        cfg = self.config()
        path = demo.write_batch_plan(cfg)
        self.assertTrue(path.exists())
        plan = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("placements", plan)
        self.assertEqual(len(plan["placements"]), cfg.rows * cfg.cols)
        first = plan["placements"][0]
        self.assertEqual(set(first), {"template_id", "position", "rotation", "scale"})

    def test_failing_step_halts_the_sequence(self):
        runner = DemoRecorder(fail_on="bind")
        report = demo.run(self.config(), execute=True, runner=runner)
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "bind")
        ran = [_demo_step(argv) for argv in runner.calls]
        self.assertEqual(ran, ["create-batch", "build-plan", "inspect", "bind"])
        self.assertNotIn("export", ran)
        self.assertNotIn("save", ran)
        self.assertNotIn("component-read", ran)

    def test_halt_prints_the_raw_receipt(self):
        runner = DemoRecorder(fail_on="export")
        report = demo.run(self.config(), execute=True, runner=runner)
        self.assertEqual(report["haltedAt"], "export")
        self.assertEqual(report["receipt"]["error"], "synthetic export failure")
        self.assertIs(report["receipt"]["ok"], False)

    def test_failure_never_retries(self):
        runner = DemoRecorder(fail_on="save")
        demo.run(self.config(), execute=True, runner=runner)
        saves = [argv for argv in runner.calls if _demo_step(argv) == "save"]
        self.assertEqual(len(saves), 1)           # attempted once, never again

    def test_first_step_failure_runs_nothing_else(self):
        runner = DemoRecorder(fail_on="create-batch")
        report = demo.run(self.config(), execute=True, runner=runner)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(report["haltedAt"], "create-batch")

    def test_runner_exception_is_a_halt_not_a_crash(self):
        class Boom(DemoRecorder):
            def __call__(self, argv):
                self.calls.append(list(argv))
                if _demo_step(argv) == "build-plan":
                    raise RuntimeError("bridge gone")
                return {"ok": True, "backend": {"status": "ok"}}

        report = demo.run(self.config(), execute=True, runner=Boom())
        self.assertFalse(report["ok"])
        self.assertEqual(report["haltedAt"], "build-plan")
        self.assertIn("bridge gone", report["receipt"]["error"])

    def test_execute_uses_the_injected_runner_only(self):
        runner = DemoRecorder()
        demo.run(self.config(), execute=True, runner=runner)
        self.assertEqual(len(runner.calls), len(DEMO_STEP_ORDER))


class TestDemoMainCli(DemoCase):
    @staticmethod
    def _quiet(argv):
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            return demo.main(argv)

    def test_main_dry_run_returns_zero(self):
        code = self._quiet(["--queue-dir", str(self.tmp / "q"), "--level-id", "1073741842",
                            "--origin", "1", "2", "3"])
        self.assertEqual(code, 0)

    def test_main_refuses_without_reviews(self):
        code = self._quiet(["--queue-dir", str(self.tmp / "q"), "--level-id", "1073741842",
                            "--execute"])
        self.assertEqual(code, 2)

    def test_config_from_args_maps_reviews(self):
        from tools.gameplan.demo.run_demo import _parser, config_from_args

        args = _parser().parse_args(["--review", f"create-batch={self.tmp}/c.json",
                                     "--review", f"save={self.tmp}/s.json"])
        cfg = config_from_args(args)
        self.assertEqual(cfg.reviews["create-batch"], f"{self.tmp}/c.json")
        self.assertEqual(cfg.reviews["save"], f"{self.tmp}/s.json")


if __name__ == "__main__":
    unittest.main()
