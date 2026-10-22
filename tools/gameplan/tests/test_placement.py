"""Offline tests for the M6b scene-placement planner.  No bridge, no game."""

import unittest

from tools.gameplan.placement import (
    TILE_FIELD,
    TILE_SINGLE_FIELD,
    Placement,
    describe,
    grid,
    to_scene_requests,
)


class TestGridGeometry(unittest.TestCase):
    def test_3x3_count_and_coordinates(self):
        # Origin (10, -2, 100), spacing 4.0: a clean, non-zero origin so a bug
        # that ignores origin shows up.
        plots = grid(
            template_id=TILE_SINGLE_FIELD,
            origin=(10.0, -2.0, 100.0),
            rows=3,
            cols=3,
            spacing=4.0,
        )
        self.assertEqual(len(plots), 9)

        coords = [(p.x, p.y, p.z) for p in plots]
        expected = [
            (10.0, -2.0, 100.0), (14.0, -2.0, 100.0), (18.0, -2.0, 100.0),
            (10.0, -2.0, 104.0), (14.0, -2.0, 104.0), (18.0, -2.0, 104.0),
            (10.0, -2.0, 108.0), (14.0, -2.0, 108.0), (18.0, -2.0, 108.0),
        ]
        self.assertEqual(coords, expected)

        # Every tile carries the requested template.
        for p in plots:
            self.assertEqual(p.template_id, TILE_SINGLE_FIELD)

    def test_row_major_order(self):
        plots = grid(template_id=TILE_FIELD, rows=2, cols=3, spacing=2.0)
        # 2x3 row-major: [r0c0, r0c1, r0c2, r1c0, r1c1, r1c2].
        # x advances fastest (columns), z advances per row.
        self.assertEqual([(p.x, p.z) for p in plots], [
            (0.0, 0.0), (2.0, 0.0), (4.0, 0.0),
            (0.0, 2.0), (2.0, 2.0), (4.0, 2.0),
        ])
        # Labels follow the same flat row-major index, so they are unique and
        # ordered exactly like the geometry.
        self.assertEqual([p.label for p in plots], [
            "plot_0", "plot_1", "plot_2", "plot_3", "plot_4", "plot_5",
        ])

    def test_label_prefix_is_honoured(self):
        plots = grid(template_id=TILE_FIELD, rows=1, cols=2, spacing=1.0,
                     label_prefix="farm")
        self.assertEqual([p.label for p in plots], ["farm_0", "farm_1"])

    def test_single_tile_grid(self):
        plots = grid(template_id=TILE_SINGLE_FIELD, origin=(5.0, 0.0, 7.0),
                     rows=1, cols=1, spacing=9.0)
        self.assertEqual(plots, [Placement(TILE_SINGLE_FIELD, 5.0, 0.0, 7.0, "plot_0")])


class TestGridValidation(unittest.TestCase):
    def test_rows_below_one_rejected(self):
        with self.assertRaises(ValueError):
            grid(template_id=TILE_FIELD, rows=0, cols=3, spacing=1.0)
        with self.assertRaises(ValueError):
            grid(template_id=TILE_FIELD, rows=-1, cols=3, spacing=1.0)

    def test_cols_below_one_rejected(self):
        with self.assertRaises(ValueError):
            grid(template_id=TILE_FIELD, rows=3, cols=0, spacing=1.0)
        with self.assertRaises(ValueError):
            grid(template_id=TILE_FIELD, rows=3, cols=-2, spacing=1.0)

    def test_non_positive_spacing_rejected(self):
        for bad in (0.0, -1.0, -0.001):
            with self.subTest(spacing=bad):
                with self.assertRaises(ValueError):
                    grid(template_id=TILE_FIELD, rows=2, cols=2, spacing=bad)


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_give_equal_lists(self):
        args = dict(template_id=TILE_FIELD, origin=(1.0, 2.0, 3.0),
                    rows=4, cols=5, spacing=2.5)
        self.assertEqual(grid(**args), grid(**args))

    def test_negative_control_wrong_spacing_differs(self):
        # A wrong spacing must NOT compare equal to the right one.  This is the
        # control that would catch a grid() that ignored spacing entirely.
        right = grid(template_id=TILE_FIELD, rows=3, cols=3, spacing=4.0)
        wrong = grid(template_id=TILE_FIELD, rows=3, cols=3, spacing=5.0)
        self.assertNotEqual(right, wrong)
        # ... and the difference is exactly in the spacing-sensitive tiles.
        self.assertEqual(right[0], wrong[0])  # origin tile is unaffected
        self.assertNotEqual(right[1], wrong[1])  # x = col*spacing differs


class TestToSceneRequests(unittest.TestCase):
    def test_length_and_shape(self):
        plots = grid(template_id=TILE_SINGLE_FIELD, origin=(0.0, 0.0, 0.0),
                     rows=2, cols=3, spacing=4.0)
        reqs = to_scene_requests(plots, request_id_for=lambda label: f"rid-{label}")
        self.assertEqual(len(reqs), len(plots))
        first = reqs[0]
        self.assertEqual(
            set(first), {"template_id", "position", "label", "request_id"}
        )
        self.assertEqual(first["template_id"], TILE_SINGLE_FIELD)
        self.assertEqual(first["position"], [0.0, 0.0, 0.0])
        self.assertEqual(first["label"], "plot_0")
        # The last request must reflect its own tile, not the first.
        self.assertEqual(reqs[-1]["position"], [8.0, 0.0, 4.0])

    def test_request_id_for_is_actually_used(self):
        plots = grid(template_id=TILE_FIELD, rows=1, cols=3, spacing=1.0)
        seen: list[str] = []

        def mint(label: str) -> str:
            seen.append(label)
            return f"id::{label}"

        reqs = to_scene_requests(plots, request_id_for=mint)
        # The minter saw every label exactly once, in order ...
        self.assertEqual(seen, ["plot_0", "plot_1", "plot_2"])
        # ... and its result landed verbatim in the request.
        self.assertEqual([r["request_id"] for r in reqs],
                         ["id::plot_0", "id::plot_1", "id::plot_2"])

    def test_position_is_a_fresh_list_per_request(self):
        plots = grid(template_id=TILE_FIELD, rows=1, cols=2, spacing=1.0)
        reqs = to_scene_requests(plots, request_id_for=lambda label: label)
        self.assertIsNot(reqs[0]["position"], reqs[1]["position"])


class TestDescribe(unittest.TestCase):
    def test_summary_mentions_count_and_extent(self):
        plots = grid(template_id=TILE_FIELD, rows=3, cols=3, spacing=4.0)
        text = describe(plots)
        self.assertIn("9", text)
        self.assertIn("x=[0, 8]", text)
        self.assertIn("z=[0, 8]", text)

    def test_empty_summary(self):
        self.assertEqual(describe([]), "0 placements")


class TestTileConstants(unittest.TestCase):
    def test_official_tile_ids(self):
        # The only two 地块 the catalogue has (docs/MODULE-PLAN-6.md:150).
        self.assertEqual(TILE_FIELD, 20001965)
        self.assertEqual(TILE_SINGLE_FIELD, 20001966)


if __name__ == "__main__":
    unittest.main()
