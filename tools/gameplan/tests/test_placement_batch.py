"""Offline tests for the M6b -> scene_cli ``create-batch`` plan bridge.

These tests import the *real* ``tools/game-executor/scene_cli.py`` (by path, the
same trick ``tools/game-executor/tests/test_scene_elevated_transport.py:29``
uses) and feed :func:`tools.gameplan.placement.to_batch_plan`'s output through
``normalize_placements`` / ``read_plan_spec``.  Nothing here contacts the bridge,
the game or the editor; scene_cli is used purely as the shape authority it is.
"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tools.gameplan.placement import (
    TILE_FIELD,
    TILE_SINGLE_FIELD,
    grid,
    to_batch_plan,
)

# tools/gameplan/tests/test_placement_batch.py -> repo root is parents[3].
_REPO = Path(__file__).resolve().parents[3]
_SCENE_CLI = _REPO / "tools" / "game-executor" / "scene_cli.py"


def _load_scene_cli():
    """Import scene_cli.py by path so this test never depends on sys.path luck."""
    spec = importlib.util.spec_from_file_location("_scene_cli_batch_contract", _SCENE_CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scene_cli = _load_scene_cli()


class TestBatchPlanShape(unittest.TestCase):
    def test_plan_is_wrapped_in_a_placements_list(self):
        plan = to_batch_plan(grid(template_id=TILE_FIELD, rows=1, cols=1, spacing=1.0))
        self.assertIsInstance(plan, dict)
        self.assertEqual(set(plan), {"placements"})
        self.assertIsInstance(plan["placements"], list)
        self.assertEqual(len(plan["placements"]), 1)

    def test_entry_keys_and_values(self):
        plots = grid(template_id=TILE_SINGLE_FIELD, origin=(1.0, 2.0, 3.0),
                     rows=1, cols=2, spacing=4.0)
        plan = to_batch_plan(plots)
        self.assertEqual(set(plan["placements"][0]),
                         {"template_id", "position", "rotation", "scale"})
        self.assertEqual(plan["placements"][0], {
            "template_id": TILE_SINGLE_FIELD,
            "position": [1.0, 2.0, 3.0],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
        })
        # The second tile reflects its own coordinate, not the first's.
        self.assertEqual(plan["placements"][1]["position"], [5.0, 2.0, 3.0])

    def test_no_label_leaks_into_the_queued_request(self):
        # Placement carries a label for request-id minting; scene_cli drops it, so
        # the plan must not smuggle it into the closed helper request.
        plan = to_batch_plan(grid(template_id=TILE_FIELD, rows=2, cols=2, spacing=1.0))
        for entry in plan["placements"]:
            self.assertNotIn("label", entry)

    def test_vector_lists_are_not_shared_between_entries(self):
        plan = to_batch_plan(grid(template_id=TILE_FIELD, rows=1, cols=2, spacing=1.0))
        a, b = plan["placements"]
        self.assertIsNot(a["position"], b["position"])
        self.assertIsNot(a["rotation"], b["rotation"])
        self.assertIsNot(a["scale"], b["scale"])

    def test_empty_placements_stays_a_valid_plan_object(self):
        # scene_cli rejects a 0-length list, but that rejection is its job; the
        # planner still emits the well-formed envelope rather than a bare list.
        self.assertEqual(to_batch_plan([]), {"placements": []})


class TestRoundTripThroughSceneCli(unittest.TestCase):
    def test_real_normalize_placements_accepts_the_plan(self):
        plots = grid(template_id=TILE_FIELD, origin=(10.0, -2.0, 100.0),
                     rows=3, cols=3, spacing=4.0)
        plan = to_batch_plan(plots)

        # The actual production entry point, not a copy of its rules.
        normalized = scene_cli.normalize_placements(plan["placements"])

        self.assertEqual(len(normalized), 9)
        self.assertEqual([n["template_id"] for n in normalized], [TILE_FIELD] * 9)
        # scene_cli re-derives exactly the geometry grid() planned.
        self.assertEqual([n["position"] for n in normalized],
                         [[p.x, p.y, p.z] for p in plots])
        self.assertEqual([n["rotation"] for n in normalized], [[0.0, 0.0, 0.0]] * 9)
        self.assertEqual([n["scale"] for n in normalized], [[1.0, 1.0, 1.0]] * 9)

    def test_read_plan_spec_accepts_the_serialised_plan(self):
        plan = to_batch_plan(grid(template_id=TILE_SINGLE_FIELD, origin=(0.0, 0.0, 0.0),
                                  rows=2, cols=2, spacing=3.0))
        scratch = _REPO / ".runtime" / "scratch"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            path = Path(folder) / "plan.json"
            # A real plan is JSON on disk; round-trip through bytes, not objects.
            path.write_text(json.dumps(plan), encoding="utf-8")

            spec = scene_cli.read_plan_spec(path)
            self.assertEqual(spec, plan)
            # ... and the spec's list is what normalize_placements consumes.
            self.assertEqual(len(scene_cli.normalize_placements(spec["placements"])), 4)

    def test_negative_control_missing_scale_is_rejected(self):
        # A plan that dropped scale must fail at the real boundary -- proof the
        # round trip is actually exercising scene_cli's validation, not a no-op.
        plan = to_batch_plan(grid(template_id=TILE_FIELD, rows=1, cols=1, spacing=1.0))
        del plan["placements"][0]["scale"]
        with self.assertRaises(ValueError):
            scene_cli.normalize_placements(plan["placements"])

    def test_negative_control_missing_position_is_rejected(self):
        plan = to_batch_plan(grid(template_id=TILE_FIELD, rows=1, cols=1, spacing=1.0))
        del plan["placements"][0]["position"]
        with self.assertRaises(ValueError):
            scene_cli.normalize_placements(plan["placements"])

    def test_negative_control_empty_list_is_rejected(self):
        with self.assertRaises(ValueError):
            scene_cli.normalize_placements(to_batch_plan([])["placements"])


class TestBatchPlanMatchesSceneRequests(unittest.TestCase):
    def test_same_geometry_as_to_scene_requests(self):
        # The two consumers (create-batch plan vs entity.create args) must agree on
        # template and coordinate for every tile; only the request id differs.
        plots = grid(template_id=TILE_SINGLE_FIELD, origin=(2.0, 1.0, 5.0),
                     rows=2, cols=3, spacing=4.0)
        from tools.gameplan.placement import to_scene_requests

        plan = to_batch_plan(plots)
        requests = to_scene_requests(plots, request_id_for=lambda label: label)
        self.assertEqual([e["position"] for e in plan["placements"]],
                         [r["position"] for r in requests])
        self.assertEqual([e["template_id"] for e in plan["placements"]],
                         [r["template_id"] for r in requests])


if __name__ == "__main__":
    unittest.main()
