"""Offline tests for the empty-patch finder.  No bridge, no game, no files."""

import unittest

from tools.gameplan.origin import NoGapError, find_gap, patch_covers


def _xyz(entry):
    """Reduce a snapshot row or bare triple to an ``[x, y, z]`` triple."""
    if isinstance(entry, dict):
        entry = entry["position"]
    return entry


def _patch_is_free(origin, positions, *, size_x, size_z) -> bool:
    """True when no position lies inside the patch — the core invariant."""
    return all(
        not patch_covers(origin, _xyz(p), size_x=size_x, size_z=size_z)
        for p in positions
    )


def _ring_clusters():
    """Two 3x3 clusters far on either side of the origin, leaving it empty.

    Cluster A sits at x,z in {-20,-19,-18}; cluster B at x in {18,19,20},
    z in {-20,-19,-18}.  The origin cell and the whole corridor between them
    (x roughly -17..17) are empty, so the nearest free patch is the origin's.
    """
    cluster_a = [(x, 0, z) for x in (-20, -19, -18) for z in (-20, -19, -18)]
    cluster_b = [(x, 0, z) for x in (18, 19, 20) for z in (-20, -19, -18)]
    return cluster_a + cluster_b


class TestClusterLeavesAGap(unittest.TestCase):
    def test_gap_is_found_at_the_origin(self):
        positions = _ring_clusters()
        origin = find_gap(positions, size_x=1, size_z=1)
        # The origin itself is free, and it is the nearest patch to (0, 0).
        self.assertEqual(origin, (0.0, 0.0, 0.0))
        # It really does contain none of the existing entities.
        self.assertTrue(_patch_is_free(origin, positions, size_x=1, size_z=1))
        # Sanity: the clusters are non-trivial (the test is not vacuous).
        self.assertEqual(len(positions), 18)

    def test_gap_moves_when_the_origin_is_occupied(self):
        # A single entity sitting exactly on the origin makes every patch that
        # covers (0, 0) illegal, so the gap is pushed to the nearest free cell.
        positions = [(0, 0, 0)]
        origin = find_gap(positions, size_x=1, size_z=1)
        self.assertNotEqual(origin, (0.0, 0.0, 0.0))
        self.assertTrue(_patch_is_free(origin, positions, size_x=1, size_z=1))
        # Nearest free patch is one metre away on the lattice.
        self.assertAlmostEqual(origin[0] ** 2 + origin[2] ** 2, 1.0)


class TestPackedAreaRaises(unittest.TestCase):
    def test_every_candidate_occupied_raises_no_gap(self):
        # Every integer lattice cell in [-3, 3]^2 holds an entity, so every 1x1
        # candidate patch within the searched radius contains its own entity.
        positions = [(x, 0, z) for x in range(-3, 4) for z in range(-3, 4)]
        with self.assertRaises(NoGapError):
            find_gap(positions, size_x=1, size_z=1, spacing=1.0, search_radius=2.0)

    def test_no_gap_is_a_named_runtime_error(self):
        self.assertTrue(issubclass(NoGapError, RuntimeError))


class TestDeterminism(unittest.TestCase):
    def test_same_inputs_same_answer(self):
        positions = _ring_clusters()
        first = find_gap(positions, size_x=2, size_z=2)
        second = find_gap(positions, size_x=2, size_z=2)
        self.assertEqual(first, second)

    def test_input_order_does_not_matter(self):
        positions = _ring_clusters()
        forward = find_gap(positions, size_x=3, size_z=3)
        backward = find_gap(list(reversed(positions)), size_x=3, size_z=3)
        self.assertEqual(forward, backward)


class TestBiggerFootprintNegControl(unittest.TestCase):
    """The same inputs, a bigger footprint — must pick a different, still-valid origin."""

    BLOCK = [(2, 0, 2), (2, 0, 3), (3, 0, 2), (3, 0, 3)]

    def test_small_footprint_fits_on_the_origin(self):
        origin = find_gap(self.BLOCK, size_x=1, size_z=1)
        self.assertEqual(origin, (0.0, 0.0, 0.0))
        self.assertTrue(_patch_is_free(origin, self.BLOCK, size_x=1, size_z=1))

    def test_bigger_footprint_moves_but_stays_valid(self):
        small = find_gap(self.BLOCK, size_x=1, size_z=1)
        big = find_gap(self.BLOCK, size_x=2, size_z=2)
        # A 2x2 patch rooted at the origin covers the block's corner (2, 2) on
        # its far edge, so the origin is no longer available for the big patch.
        self.assertNotEqual(small, big)
        self.assertTrue(patch_covers((0.0, 0.0, 0.0), (2, 0, 2), size_x=2, size_z=2))
        # ... and the winner is exactly the nearest free 2x2 patch.
        self.assertEqual(big, (-1.0, 0.0, 0.0))
        self.assertTrue(_patch_is_free(big, self.BLOCK, size_x=2, size_z=2))


class TestBoundaryIsOccupied(unittest.TestCase):
    def test_edge_contact_counts_as_inside(self):
        # An entity exactly on the patch's far edge is still an overlap: the
        # occupancy test is a closed rectangle.
        self.assertTrue(patch_covers((0.0, 0.0, 0.0), (1, 0, 0), size_x=1, size_z=1))
        self.assertTrue(patch_covers((0.0, 0.0, 0.0), (0, 0, 1), size_x=1, size_z=1))

    def test_just_outside_the_edge_is_free(self):
        self.assertFalse(
            patch_covers((0.0, 0.0, 0.0), (1.0001, 0, 0), size_x=1, size_z=1)
        )

    def test_origin_flees_a_boundary_entity(self):
        positions = [(1, 0, 0)]
        origin = find_gap(positions, size_x=1, size_z=1)
        self.assertNotEqual(origin, (0.0, 0.0, 0.0))
        self.assertTrue(_patch_is_free(origin, positions, size_x=1, size_z=1))


class TestInputShapes(unittest.TestCase):
    def test_snapshot_rows_and_bare_triples_agree(self):
        triples = [(0, 0, 0), (5, 0, 5)]
        rows = [{"position": [0, 0, 0]}, {"position": None}, {"position": [5, 0, 5]}]
        self.assertEqual(
            find_gap(triples, size_x=1, size_z=1),
            find_gap(rows, size_x=1, size_z=1),
        )

    def test_none_position_rows_are_skipped(self):
        rows = [{"position": None}, {"position": None}]
        # Only the origin cell is free-enough to matter, and nothing occupies it.
        self.assertEqual(find_gap(rows, size_x=1, size_z=1), (0.0, 0.0, 0.0))

    def test_malformed_position_raises_value_error(self):
        with self.assertRaises(ValueError):
            find_gap([(1,)], size_x=1, size_z=1)
        with self.assertRaises(ValueError):
            find_gap([{"position": "nope"}], size_x=1, size_z=1)


class TestValidation(unittest.TestCase):
    def test_non_positive_sizes_rejected(self):
        for bad in (0.0, -1.0):
            with self.subTest(size=bad):
                with self.assertRaises(ValueError):
                    find_gap([], size_x=bad, size_z=1.0)
                with self.assertRaises(ValueError):
                    find_gap([], size_x=1.0, size_z=bad)

    def test_non_positive_spacing_rejected(self):
        with self.assertRaises(ValueError):
            find_gap([], size_x=1.0, size_z=1.0, spacing=0.0)

    def test_negative_search_radius_rejected(self):
        with self.assertRaises(ValueError):
            find_gap([], size_x=1.0, size_z=1.0, search_radius=-1.0)


class TestReturnShape(unittest.TestCase):
    def test_returns_a_triple_with_ground_y(self):
        origin = find_gap([], size_x=1, size_z=1)
        self.assertEqual(len(origin), 3)
        self.assertEqual(origin[1], 0.0)
        self.assertEqual(origin, (0.0, 0.0, 0.0))

    def test_candidates_sit_on_the_spacing_lattice(self):
        origin = find_gap([(0, 0, 0)], size_x=1, size_z=1, spacing=5.0, search_radius=50.0)
        # The empty origin cell is blocked at spacing 5, so the answer is a
        # neighbour exactly 5 m out, still on the 5 m lattice.
        self.assertEqual(origin[0] % 5.0, 0.0)
        self.assertEqual(origin[2] % 5.0, 0.0)
        self.assertAlmostEqual(origin[0] ** 2 + origin[2] ** 2, 25.0)


if __name__ == "__main__":
    unittest.main()
