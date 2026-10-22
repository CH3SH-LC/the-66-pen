"""Offline tests for the end-to-end demo sequence (#6 造).

These pin the behaviours the task makes contractual:

* the order is exactly the runbook order,
* every ``writes`` step carries a non-empty gate,
* the manual template step appears as a GATE, never as a command,
* a dry run renders the commands without running anything, and
* a missing required argument raises.

Nothing here contacts the bridge, the game or the editor: ``build_sequence`` is
offline by construction, and its one file write (the ``create-batch`` plan) is
redirected into a temp directory.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.gameplan import demo_sequence as ds


class SequenceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.scratch = self.tmp / "scratch"
        self.verify = self.tmp / "game-executor"
        self.queue = self.tmp / "queue"

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, **overrides):
        kwargs = dict(
            level_id=1073741842,
            template_id=20001965,          # 土田 (placement.TILE_FIELD)
            origin=(1.0, 2.0, 3.0),
            crop_id=1120000001,
            food_id=1120000002,
            currency_id=1115684864,
            graph_name="MW_API_FARM_DEMO",
        )
        kwargs.update(overrides)
        with mock.patch.object(ds, "_SCRATCH", self.scratch), \
             mock.patch.object(ds, "_VERIFY_OUT_DIR", self.verify), \
             mock.patch.object(ds, "_DEFAULT_QUEUE", self.queue):
            return ds.build_sequence(**kwargs)

    @staticmethod
    def by_label(sequence):
        return {s["label"]: s for s in sequence}

    @staticmethod
    def arg_after(argv, flag):
        return argv[argv.index(flag) + 1]


class TestOrder(SequenceCase):
    def test_order_is_exactly_the_runbook_order(self):
        sequence = self.build()
        self.assertEqual([s["label"] for s in sequence], list(ds.STEP_LABELS))
        self.assertEqual(list(ds.STEP_LABELS), [
            "live-read", "templates", "create-plots", "build-plan",
            "inspect", "bind", "export", "save", "verify",
        ])

    def test_order_field_is_1_based_and_dense(self):
        sequence = self.build()
        self.assertEqual([s["order"] for s in sequence], list(range(1, len(sequence) + 1)))

    def test_live_read_is_first_and_read_only(self):
        first = self.build()[0]
        self.assertEqual(first["label"], "live-read")
        self.assertFalse(first["writes"])
        self.assertIsNone(first["gate"])
        self.assertIn("tools.gameplan.live", first["argv"])


class TestWriteGates(SequenceCase):
    def test_only_native_scene_writes_are_marked_writes(self):
        sequence = self.build()
        self.assertEqual({s["label"] for s in sequence if s["writes"]},
                         set(ds.GATED_WRITE_LABELS))
        self.assertEqual(tuple(ds.GATED_WRITE_LABELS), ("create-plots", "save"))

    def test_every_write_carries_a_non_empty_gate(self):
        sequence = self.build()
        for step in sequence:
            if step["writes"]:
                self.assertTrue(step["gate"], f"{step['label']} writes but has no gate")
        self.assertEqual(ds.writes_without_gate(sequence), [])

    def test_gate_flag_is_present_on_exactly_the_writes(self):
        for step in self.build():
            has_review = "--review" in step["argv"]
            self.assertEqual(has_review, step["writes"], step["label"])

    def test_write_gates_name_a_review_file(self):
        by = self.by_label(self.build())
        self.assertTrue(by["create-plots"]["gate"].endswith("-create-review.json"))
        self.assertTrue(by["save"]["gate"].endswith("-save-review.json"))


class TestManualTemplateGate(SequenceCase):
    def test_template_step_is_a_gate_not_a_command(self):
        step = self.by_label(self.build())["templates"]
        self.assertEqual(step["argv"], [])          # no command
        self.assertFalse(step["writes"])            # and not a write
        self.assertTrue(step["gate"])
        self.assertTrue(step["gate"].startswith("MANUAL"))

    def test_render_prints_it_as_a_comment_not_a_command(self):
        text = ds.render(self.build())
        commands = [line for line in text.splitlines() if line and not line.startswith("#")]
        # Only the eight command steps produce a command line; the manual gate does not.
        self.assertEqual(len(commands), sum(1 for s in self.build() if s["argv"]))
        self.assertIn("# 2. templates", text)
        # Nothing between the templates header and the create-plots header is a command.
        lines = text.splitlines()
        start = lines.index("# 2. templates [GATE]")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("# 3."))
        self.assertTrue(all(not line or line.startswith("#") for line in lines[start + 1:end]))

    def test_manual_gate_sits_between_live_read_and_create(self):
        labels = [s["label"] for s in self.build()]
        self.assertEqual(labels.index("templates"), labels.index("live-read") + 1)
        self.assertEqual(labels.index("create-plots"), labels.index("templates") + 1)


class TestPlotsBatchPlan(SequenceCase):
    def test_create_plots_dispatches_the_batch_plan(self):
        argv = self.by_label(self.build())["create-plots"]["argv"]
        self.assertIn("scene_cli.py", " ".join(argv))
        self.assertIn("create-batch", argv)
        plan = Path(self.arg_after(argv, "--plan"))
        self.assertTrue(plan.is_file())
        payload = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["placements"]), ds.PLOT_ROWS * ds.PLOT_COLS)

    def test_plan_geometry_is_the_named_grid(self):
        argv = self.by_label(self.build())["create-plots"]["argv"]
        payload = json.loads(Path(self.arg_after(argv, "--plan")).read_text(encoding="utf-8"))
        positions = [p["position"] for p in payload["placements"]]
        self.assertEqual(positions[0], [1.0, 2.0, 3.0])
        self.assertEqual(positions[-1],
                         [1.0 + (ds.PLOT_COLS - 1) * ds.PLOT_SPACING, 2.0,
                          3.0 + (ds.PLOT_ROWS - 1) * ds.PLOT_SPACING])
        for entry in payload["placements"]:
            self.assertEqual(entry["template_id"], 20001965)
            self.assertNotIn("label", entry)


class TestGraphSteps(SequenceCase):
    def test_build_plan_is_one_batched_dispatch(self):
        argv = self.by_label(self.build())["build-plan"]["argv"]
        self.assertIn("tools.gameplan.cli", argv)
        self.assertIn("farming", argv)
        self.assertIn("--batch", argv)
        self.assertIn("--execute", argv)
        self.assertEqual(self.arg_after(argv, "--crop-id"), "1120000001")
        self.assertEqual(self.arg_after(argv, "--food-id"), "1120000002")
        self.assertEqual(self.arg_after(argv, "--currency-id"), "1115684864")

    def test_inspect_bind_export_are_author_graph_actions(self):
        by = self.by_label(self.build())
        for label, action in (("inspect", "inspect"), ("bind", "bind"), ("export", "export")):
            argv = by[label]["argv"]
            self.assertIn("graph", argv)
            self.assertEqual(argv[argv.index("graph") + 1], action)
            self.assertEqual(self.arg_after(argv, "--name"), "MW_API_FARM_DEMO")

    def test_bind_carries_the_node_count_of_the_demo_graph(self):
        argv = self.by_label(self.build())["bind"]["argv"]
        self.assertEqual(self.arg_after(argv, "--expected-node-count"), "15")
        self.assertEqual(self.arg_after(argv, "--entity-id"), ds._ENTITY_ID)

    def test_bind_follows_build_plan_and_export_follows_bind(self):
        labels = [s["label"] for s in self.build()]
        self.assertLess(labels.index("build-plan"), labels.index("inspect"))
        self.assertLess(labels.index("inspect"), labels.index("bind"))
        self.assertLess(labels.index("bind"), labels.index("export"))
        self.assertLess(labels.index("export"), labels.index("save"))


class TestSaveAndVerify(SequenceCase):
    def test_save_is_the_author_scene_save_with_a_review(self):
        step = self.by_label(self.build())["save"]
        self.assertTrue(step["writes"])
        self.assertIn("save", step["argv"])
        self.assertEqual(self.arg_after(step["argv"], "--level-id"), "1073741842")
        self.assertEqual(self.arg_after(step["argv"], "--review"), step["gate"])

    def test_verify_is_the_independent_gil_diff(self):
        argv = self.by_label(self.build())["verify"]["argv"]
        self.assertIn("verify-created-save.py", " ".join(argv))
        self.assertEqual(argv[3], ds._BEFORE_GIL)
        self.assertEqual(argv[4], ds._AFTER_GIL)
        self.assertEqual(self.arg_after(argv, "--template-id"), "20001965")
        self.assertTrue(self.arg_after(argv, "--out").endswith("-verify.json"))

    def test_save_precedes_verify(self):
        labels = [s["label"] for s in self.build()]
        self.assertLess(labels.index("save"), labels.index("verify"))


class TestDryRunRender(SequenceCase):
    def test_render_executes_nothing_and_writes_nothing(self):
        sequence = self.build()
        before = sorted(p.name for p in self.scratch.iterdir())
        text = ds.render(sequence)
        after = sorted(p.name for p in self.scratch.iterdir())
        self.assertEqual(before, after)                     # render touched no file
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip())

    def test_render_is_pure_and_deterministic(self):
        sequence = self.build()
        self.assertEqual(ds.render(sequence), ds.render(sequence))

    def test_render_emits_one_command_line_per_command_step(self):
        sequence = self.build()
        lines = ds.render(sequence).splitlines()
        commands = [line for line in lines if line and not line.startswith("#")]
        self.assertTrue(all(line.startswith("python") for line in commands))
        self.assertEqual(len(commands), sum(1 for s in sequence if s["argv"]))

    def test_render_names_the_gate_for_each_write(self):
        text = ds.render(self.build())
        by = self.by_label(self.build())
        self.assertIn(by["create-plots"]["gate"], text)
        self.assertIn(by["save"]["gate"], text)


class TestOnlyOfflineArtifact(SequenceCase):
    def test_build_writes_only_the_batch_plan(self):
        self.build()
        written = sorted(p.name for p in self.scratch.iterdir())
        self.assertEqual(written, ["MW_API_FARM_DEMO-plots.json"])
        self.assertFalse(self.verify.exists())   # nothing dispatched, no verify output


class TestRequiredArguments(SequenceCase):
    REQUIRED = ("level_id", "template_id", "origin", "crop_id",
                "food_id", "currency_id", "graph_name")

    def test_missing_required_argument_raises(self):
        base = dict(level_id=1073741842, template_id=20001965, origin=(0, 0, 0),
                    crop_id=1, food_id=2, currency_id=3, graph_name="MW_API_X")
        for name in self.REQUIRED:
            partial = {k: v for k, v in base.items() if k != name}
            with self.subTest(missing=name):
                # Called directly: the local build() supplies defaults for every name,
                # which would mask the missing-argument TypeError under test.
                with self.assertRaises(TypeError):
                    ds.build_sequence(**partial)

    def test_none_level_id_raises(self):
        with self.assertRaises(ValueError):
            self.build(level_id=None)

    def test_bad_origin_shape_raises(self):
        with self.assertRaises(ValueError):
            self.build(origin=(0.0, 0.0))

    def test_empty_graph_name_raises(self):
        with self.assertRaises(ValueError):
            self.build(graph_name="   ")

    def test_non_positive_id_raises(self):
        with self.assertRaises(ValueError):
            self.build(crop_id=0)


if __name__ == "__main__":
    unittest.main()
