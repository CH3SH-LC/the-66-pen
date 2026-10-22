"""Offline tests for ``asset.measure``.  No bridge, no game, no file writes.

The point of these tests is the DOCTRINE, not coverage: ``asset.measure`` is a
deliberate NEGATIVE (``tools/gameplan/measure.py`` docstring), so the tests hold
two lines:

  * the unknown path returns a real ``None`` -- **never** a stand-in default like
    ``1.0`` (the exact failure ``tools/authoring/INTERFACE-INVENTORY.md:22`` warns
    about: "未知尺寸不能用图标猜"); and
  * any size that *were* known would have to be cited -- so if
    :data:`MEASURED_TILE_SIZES` ever gains an entry, the recorded-assumption table
    must not have been quietly promoted to an answer, and the reason string must
    name where a real value would come from.

Run either way::

    python -B -m unittest tools.gameplan.tests.test_measure
    python -m pytest tools/gameplan/tests/test_measure.py -q
"""

import unittest

from tools.gameplan.measure import (
    MEASURED_TILE_SIZES,
    RECORDED_SIZE_ASSUMPTIONS,
    UNKNOWN_SIZE_TAIL,
    describe_unknown,
    grid_spacing_for,
)
from tools.gameplan.placement import TILE_FIELD, TILE_SINGLE_FIELD


# A spread of ids that sweeps every class the repo ever talks about: the two
# farm-plot tiles the M6b demo places, the calibration prefabs that *do* have a
# recorded (unmeasured) size, a couple of decorations, and an id nothing knows.
PROBE_IDS = [
    TILE_FIELD,           # 20001965 土田 -- the demo's template, size unknown
    TILE_SINGLE_FIELD,    # 20001966 单块土田
    20001875,             # 通常立方体 -- recorded assumption 1.0
    20001224,             # 木质箱子 -- recorded assumption 1.0
    20001034,             # 石质元素立方体 -- recorded assumption 5.0
    20001001,             # 乔木
    999999999,            # nothing
]


class TestGridSpacingIsHonestlyNone(unittest.TestCase):
    """The unknown path must return None -- never a number, never a default."""

    def test_every_probe_id_returns_none(self):
        for tid in PROBE_IDS:
            with self.subTest(template_id=tid):
                self.assertIsNone(grid_spacing_for(tid))

    def test_none_is_not_a_stand_in_default(self):
        # The load-bearing assertion: an unknown size must NOT come back as 1.0
        # (or 0.0) dressed up as a measurement.  Asserting `is None` is stronger
        # than `not equal to 1.0`, but pin the specific trap too so a future
        # regression that defaults spacing to 1.0 fails loudly here.
        for tid in PROBE_IDS:
            with self.subTest(template_id=tid):
                result = grid_spacing_for(tid)
                self.assertNotEqual(result, 1.0)
                self.assertNotEqual(result, 0.0)
                self.assertIsNone(result)

    def test_recorded_assumptions_are_not_returned_as_sizes(self):
        # The recorded `size_units` numbers are documented ASSUMPTIONS, not
        # measurements (mvp/calibration/README.md:24).  Even for the ids that
        # have one, grid_spacing_for must not hand it back as a size.
        for tid, (value, _source) in RECORDED_SIZE_ASSUMPTIONS.items():
            with self.subTest(template_id=tid, recorded=value):
                self.assertIsNone(grid_spacing_for(tid))

    def test_measured_table_is_empty_today(self):
        # The one seam where a measured size could live.  If this fails, someone
        # measured a size -- good, but they must ALSO add it a citation and
        # update the tests below; do not relax this line to make it pass.
        self.assertEqual(MEASURED_TILE_SIZES, {})


class TestKnownSizesAreCited(unittest.TestCase):
    """If a size ever IS known, it must be cited -- nothing is cited as known today."""

    def test_every_recorded_assumption_carries_a_source(self):
        for tid, entry in RECORDED_SIZE_ASSUMPTIONS.items():
            with self.subTest(template_id=tid):
                self.assertEqual(len(entry), 2, "entry must be (size, source)")
                size, source = entry
                self.assertIsInstance(size, float)
                self.assertGreater(size, 0.0)
                self.assertIsInstance(source, str)
                self.assertTrue(source.strip(), "a recorded size needs a citation")
                # The citation must point at the real, unmeasured source.
                self.assertIn("block_config", source)
                self.assertIn("NOT measured", source)

    def test_a_hypothetical_measured_entry_would_be_returned_and_cited(self):
        # Exercise the seam without polluting the module: temporarily insert a
        # MEASURED size and confirm it is returned verbatim (so the table really
        # is what grid_spacing_for reads), then restore the empty table.
        sentinel_id = 123456789
        try:
            MEASURED_TILE_SIZES[sentinel_id] = 2.5
            self.assertEqual(grid_spacing_for(sentinel_id), 2.5)
            # ... and an id NOT in the table is still None -- the table is the
            # only thing that may produce a number.
            self.assertIsNone(grid_spacing_for(sentinel_id + 1))
        finally:
            MEASURED_TILE_SIZES.pop(sentinel_id, None)
        self.assertEqual(MEASURED_TILE_SIZES, {})


class TestDescribeUnknownNamesTheSource(unittest.TestCase):
    def test_returns_a_non_empty_reason_for_every_probe(self):
        for tid in PROBE_IDS:
            with self.subTest(template_id=tid):
                reason = describe_unknown(tid)
                self.assertIsInstance(reason, str)
                self.assertTrue(reason.strip())

    def test_reason_names_the_template_and_says_unknown(self):
        reason = describe_unknown(TILE_FIELD)
        self.assertIn(str(TILE_FIELD), reason)
        self.assertIn("UNKNOWN", reason)
        # It must refuse a default, not offer one.
        self.assertIn("None", reason)

    def test_reason_names_where_the_size_would_have_to_come_from(self):
        # The core requirement: the reason names the candidate sources, so a
        # caller reading a log understands a size is a NEW capability.
        reason = describe_unknown(999999999)
        for needle in (
            "prefab model",          # source (1): the editor model has no field
            "bounds field",          # the field a real value would need
            "native",                # source (2): no native/game bounds API
            ".gil",                  # live place-and-read-back would land here
            "PREFAB-FIELDS-MINE",    # cited mining report
            "GEOMETRY-THREE-WAYS",   # cited geometry report
            "size-entry",            # cited P03 negative
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, reason)

    def test_reason_for_a_recorded_id_names_the_number_but_calls_it_unmeasured(self):
        reason = describe_unknown(20001875)
        # The documented number is quoted so a reader cannot think it is hidden ...
        self.assertIn("1", reason)
        # ... while being plainly labelled unmeasured and NOT returned.
        self.assertIn("UNMEASURED", reason)
        self.assertIn("not returned", reason)
        self.assertIn("block_config", reason)

        reason5 = describe_unknown(20001034)
        self.assertIn("5", reason5)
        self.assertIn("UNMEASURED", reason5)

    def test_reason_for_an_unknown_id_does_not_quote_a_size(self):
        # An id with no recorded assumption must not fabricate any number.
        reason = describe_unknown(999999999)
        self.assertNotIn("is RECORDED", reason)
        self.assertNotIn("RECORDED_SIZE_ASSUMPTIONS", reason)

    def test_unknown_tail_is_shared_and_size_free(self):
        # The shared tail is what every reason ends with; it must never state a
        # template size, only where one would come from.
        self.assertTrue(UNKNOWN_SIZE_TAIL.strip())
        for tid in PROBE_IDS:
            self.assertTrue(describe_unknown(tid).endswith(UNKNOWN_SIZE_TAIL))


class TestInputHandling(unittest.TestCase):
    def test_non_integer_id_is_rejected(self):
        for bad in (None, "not-an-id", object()):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    grid_spacing_for(bad)
                with self.assertRaises(TypeError):
                    describe_unknown(bad)


if __name__ == "__main__":
    unittest.main()
