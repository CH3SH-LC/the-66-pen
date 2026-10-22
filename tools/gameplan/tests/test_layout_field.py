"""Offline tests for the M6b 3x3 field layout (``demo/layout_field.py``).

No bridge, no game, no editor.  The batch-plan shape is checked two ways: as a
literal structure, and by feeding it through the *real*
``tools/game-executor/scene_cli.py`` validation functions (imported by path, the
same trick ``tests/test_placement_batch.py:28`` uses) so an independently
rebuilt shape cannot drift from the shape authority.

This file deliberately does NOT import ``placement.to_batch_plan`` — the plan is
built by ``layout_field`` itself, and the point of these tests is that the two
shapes agree with scene_cli, not with each other by construction.
"""

import importlib.util
import json
import unittest

from tools.gameplan.demo.layout_field import (
    DEFAULT_SPACING,
    FIELD_COLS,
    FIELD_ORIGIN,
    FIELD_PLAN_PATH,
    FIELD_ROWS,
    LEVEL_ID_PLACEHOLDER,
    PLAN_PLACEHOLDER,
    REVIEW_PLACEHOLDER,
    SESSION_PLACEHOLDER,
    command_line,
    command_sequence,
    demo_plan,
    field_placements,
    field_plan,
    orchestrator_command_line,
)
from tools.gameplan.placement import TILE_FIELD
from pathlib import Path

# tools/gameplan/tests/test_layout_field.py -> repo root is parents[3].
_REPO = Path(__file__).resolve().parents[3]
_SCENE_CLI = _REPO / "tools" / "game-executor" / "scene_cli.py"
_FIELD_PLAN_FILE = _REPO / FIELD_PLAN_PATH


def _load_scene_cli():
    """Import scene_cli.py by path so this test never depends on sys.path luck."""
    spec = importlib.util.spec_from_file_location("_scene_cli_field_contract", _SCENE_CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scene_cli = _load_scene_cli()

# A deliberately non-zero origin and a spacing != 1 so a bug that ignores either
# shows up in the coordinates below.
ORIGIN = (10.0, -2.0, 100.0)
SPACING = 4.0


class TestFieldPlanShape(unittest.TestCase):
    def test_plan_is_wrapped_in_a_placements_list(self):
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        self.assertIsInstance(plan, dict)
        self.assertEqual(set(plan), {"placements"})
        self.assertIsInstance(plan["placements"], list)
        self.assertEqual(len(plan["placements"]), 9)

    def test_entry_keys_and_constant_values(self):
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        for entry in plan["placements"]:
            self.assertEqual(
                set(entry), {"template_id", "position", "rotation", "scale"}
            )
            self.assertEqual(entry["template_id"], TILE_FIELD)
            self.assertEqual(entry["rotation"], [0.0, 0.0, 0.0])
            self.assertEqual(entry["scale"], [1.0, 1.0, 1.0])

    def test_no_label_leaks_into_the_closed_plan(self):
        # scene_cli drops a label from the queued request; the plan must not carry
        # a field that never reaches the game.
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        for entry in plan["placements"]:
            self.assertNotIn("label", entry)

    def test_default_template_is_the_official_field_tile(self):
        self.assertEqual(TILE_FIELD, 20001965)
        plan = field_plan(origin=(0.0, 0.0, 0.0), spacing=1.0)
        self.assertEqual({e["template_id"] for e in plan["placements"]}, {20001965})

    def test_vector_lists_are_not_shared_between_entries(self):
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        first, second = plan["placements"][0], plan["placements"][1]
        self.assertIsNot(first["position"], second["position"])
        self.assertIsNot(first["rotation"], second["rotation"])
        self.assertIsNot(first["scale"], second["scale"])


class TestFieldGridCoordinates(unittest.TestCase):
    def test_nine_positions_row_major(self):
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        positions = [e["position"] for e in plan["placements"]]
        expected = [
            [10.0, -2.0, 100.0], [14.0, -2.0, 100.0], [18.0, -2.0, 100.0],
            [10.0, -2.0, 104.0], [14.0, -2.0, 104.0], [18.0, -2.0, 104.0],
            [10.0, -2.0, 108.0], [14.0, -2.0, 108.0], [18.0, -2.0, 108.0],
        ]
        self.assertEqual(positions, expected)

        # Row-major proof independent of the table above: x advances fastest,
        # z advances once per completed row.
        xs = [p[0] for p in positions]
        zs = [p[2] for p in positions]
        self.assertEqual(xs, [10.0, 14.0, 18.0] * 3)
        self.assertEqual(zs, [100.0] * 3 + [104.0] * 3 + [108.0] * 3)

    def test_same_geometry_as_field_placements(self):
        # The plan and the Placement list must agree tile-for-tile.
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        plots = field_placements(origin=ORIGIN, spacing=SPACING)
        self.assertEqual([e["position"] for e in plan["placements"]],
                         [p.position for p in plots])
        self.assertEqual([p.label for p in plots],
                         [f"plot_{i}" for i in range(9)])

    def test_default_spacing_tiles_edge_to_edge_at_one_metre(self):
        # 1 grid = 1 metre: a 1.0 spacing must step exactly one metre per column.
        self.assertEqual(DEFAULT_SPACING, 1.0)
        plan = field_plan(origin=(0.0, 0.0, 0.0))
        self.assertEqual([e["position"][0] for e in plan["placements"][:3]],
                         [0.0, 1.0, 2.0])

    def test_field_is_three_by_three(self):
        self.assertEqual((FIELD_ROWS, FIELD_COLS), (3, 3))


class TestRoundTripThroughSceneCli(unittest.TestCase):
    def test_real_normalize_placements_accepts_the_plan(self):
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        # The actual production entry point, not a copy of its rules.
        normalized = scene_cli.normalize_placements(plan["placements"])
        self.assertEqual(len(normalized), 9)
        self.assertEqual([n["template_id"] for n in normalized], [TILE_FIELD] * 9)
        self.assertEqual([n["position"] for n in normalized],
                         [e["position"] for e in plan["placements"]])

    def test_negative_control_missing_scale_is_rejected(self):
        # Proof the round trip really exercises scene_cli's validation.
        plan = field_plan(origin=ORIGIN, spacing=SPACING)
        del plan["placements"][4]["scale"]
        with self.assertRaises(ValueError):
            scene_cli.normalize_placements(plan["placements"])


class TestCommandLine(unittest.TestCase):
    def test_command_uses_the_create_batch_action_and_scene_cli(self):
        cmd = command_line()
        self.assertIn("scene_cli.py", cmd)
        self.assertIn("create-batch", cmd)
        # The elevated queue is this project's only write channel.
        self.assertIn("--elevated-queue", cmd)

    def test_command_carries_the_three_unknowable_placeholders(self):
        cmd = command_line()
        # The flags exist ...
        for flag in ("--level-id", "--review", "--plan"):
            self.assertIn(flag, cmd)
        # ... and their values are placeholders, not guessed concrete values.
        self.assertIn(f"--level-id {LEVEL_ID_PLACEHOLDER}", cmd)
        self.assertIn(f"--review {REVIEW_PLACEHOLDER}", cmd)
        self.assertIn(f"--plan {PLAN_PLACEHOLDER}", cmd)

    def test_placeholders_are_angle_bracket_tokens(self):
        # A placeholder that looked like a real value would invite a copy-paste of
        # a stale level id; these three must be visibly unfilled.
        for token in (LEVEL_ID_PLACEHOLDER, REVIEW_PLACEHOLDER, PLAN_PLACEHOLDER):
            self.assertTrue(token.startswith("<") and token.endswith(">"), token)

    def test_command_is_a_single_plain_string(self):
        cmd = command_line()
        self.assertIsInstance(cmd, str)
        self.assertNotIn("\n", cmd)

    def test_caller_supplied_values_replace_the_placeholders(self):
        cmd = command_line(
            plan_path=".runtime/scratch/field.json",
            level_id="1073741840",
            review=".runtime/scratch/review.json",
        )
        self.assertIn("--level-id 1073741840", cmd)
        self.assertIn("--review .runtime/scratch/review.json", cmd)
        self.assertIn("--plan .runtime/scratch/field.json", cmd)
        # The unfilled placeholders are gone once values are supplied.
        self.assertNotIn(LEVEL_ID_PLACEHOLDER, cmd)
        self.assertNotIn(REVIEW_PLACEHOLDER, cmd)
        self.assertNotIn(PLAN_PLACEHOLDER, cmd)


class TestCheckedInPlanFile(unittest.TestCase):
    def test_file_matches_the_module_output_exactly(self):
        # Drift guard: the checked-in artefact IS demo_plan(), byte-for-byte in
        # content.  If the geometry or shape changes, the file must be regenerated.
        on_disk = json.loads(_FIELD_PLAN_FILE.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, demo_plan())

    def test_file_origin_is_the_documented_example_not_the_spawn_preset(self):
        # The spawn preset (-547.5, -2.5, -547.5) is a global constant that
        # misleads; the example origin must not be it.
        self.assertEqual(FIELD_ORIGIN, (0.0, 0.0, 0.0))
        self.assertNotEqual(list(FIELD_ORIGIN), [-547.5, -2.5, -547.5])

    def test_file_has_nine_row_major_positions(self):
        on_disk = json.loads(_FIELD_PLAN_FILE.read_text(encoding="utf-8"))
        positions = [e["position"] for e in on_disk["placements"]]
        self.assertEqual(positions, [
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
            [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [2.0, 0.0, 1.0],
            [0.0, 0.0, 2.0], [1.0, 0.0, 2.0], [2.0, 0.0, 2.0],
        ])

    def test_file_round_trips_through_the_real_read_and_normalize(self):
        # Both real scene_cli entry points: read_plan_spec parses the FILE, then
        # normalize_placements validates its placements.
        spec = scene_cli.read_plan_spec(_FIELD_PLAN_FILE)
        normalized = scene_cli.normalize_placements(spec["placements"])
        self.assertEqual(len(normalized), 9)
        self.assertEqual([n["template_id"] for n in normalized], [TILE_FIELD] * 9)

    def test_file_missing_scale_is_refused_by_the_real_normalizer(self):
        # Negative control: the file is really validated, not rubber-stamped.
        on_disk = json.loads(_FIELD_PLAN_FILE.read_text(encoding="utf-8"))
        del on_disk["placements"][4]["scale"]
        with self.assertRaises(ValueError):
            scene_cli.normalize_placements(on_disk["placements"])


class TestOrchestratorCommandLine(unittest.TestCase):
    def test_command_mints_the_review_before_queueing(self):
        cmd = orchestrator_command_line()
        self.assertIn("orchestrate_write_review.py", cmd)
        self.assertIn("--action create-batch", cmd)
        # The coordinator is run as a script with byte-code writing disabled.
        self.assertIn("-B", cmd)

    def test_command_carries_every_coordinator_input(self):
        cmd = orchestrator_command_line()
        for flag in ("--session", "--level-id", "--plan", "--baseline-run",
                     "--baseline-kind", "--recovery-dir", "--out"):
            self.assertIn(flag, cmd)

    def test_baseline_kind_defaults_to_readonly(self):
        self.assertIn("--baseline-kind readonly", orchestrator_command_line())

    def test_plan_and_out_default_to_placeholders(self):
        cmd = orchestrator_command_line()
        self.assertIn(f"--plan {PLAN_PLACEHOLDER}", cmd)
        self.assertIn(f"--out {REVIEW_PLACEHOLDER}", cmd)
        self.assertIn(f"--level-id {LEVEL_ID_PLACEHOLDER}", cmd)
        self.assertIn(f"--session {SESSION_PLACEHOLDER}", cmd)

    def test_command_is_a_single_plain_string(self):
        cmd = orchestrator_command_line()
        self.assertIsInstance(cmd, str)
        self.assertNotIn("\n", cmd)


class TestCommandSequence(unittest.TestCase):
    def test_two_steps_in_order_mint_then_queue(self):
        steps = command_sequence(
            plan_path=".runtime/scratch/field.json",
            level_id="1073741840",
            session=".runtime/scratch/session.json",
            review=".runtime/scratch/review.json",
            baseline_run=".runtime/scratch/readonly-run",
        )
        self.assertEqual(len(steps), 2)
        mint, queue = steps
        self.assertIn("orchestrate_write_review.py", mint)
        self.assertIn("scene_cli.py", queue)
        # The review step one writes is the review step two reads.
        self.assertIn("--out .runtime/scratch/review.json", mint)
        self.assertIn("--review .runtime/scratch/review.json", queue)
        # The plan step one hashes is the plan step two sends.
        self.assertIn("--plan .runtime/scratch/field.json", mint)
        self.assertIn("--plan .runtime/scratch/field.json", queue)

    def test_default_sequence_matches_the_two_standalone_commands(self):
        self.assertEqual(command_sequence(),
                         [orchestrator_command_line(), command_line()])


if __name__ == "__main__":
    unittest.main()
