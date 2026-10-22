"""Offline tests for the pre-dispatch placement guard.  No bridge, no game.

The guard answers one question three ways, and the whole point of these tests is
that the three never collapse -- in particular that **OUT_OF_BOUNDS** and
**BOUNDS_UNKNOWN** are *different objects with different codes*, even though both
are ``ok=False``.

Paths pinned here:

  * a **known box** with placements inside / outside / exactly on a face;
  * the **unknown-box refusal** from :func:`guard` (``bounds=None``) and from
    :func:`guard_default` (which calls :func:`load_bounds` -- ``None`` today);
  * a **malformed box** refusing outright (``ValueError``), never mistaken for
    ``None``;
  * the **explicit-box certification path** a human uses to certify a layout.

The synthetic ``.gil`` fixtures are built here byte by byte (the same real shape
``tools/gameplan/tests/test_bounds.py`` uses), so ``guard_default``'s
unknown-box branch is proven against the bytes a real level carries without a
live save.  Nothing is written outside ``.runtime/scratch``.
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

from tools.gameplan.bounds import Bounds
from tools.gameplan.placement import (
    TILE_SINGLE_FIELD,
    Placement,
    grid,
)
from tools.gameplan.placement_guard import (
    CODE_BOUNDS_UNKNOWN,
    CODE_CERTIFIED,
    CODE_OUT_OF_BOUNDS,
    Certified,
    GuardVerdict,
    Offender,
    OutOfBounds,
    Uncertified,
    guard,
    guard_default,
)

_REPO = Path(__file__).resolve().parents[3]

# The container codec lives under tools/beyond-save; reach it the way bounds.py
# does so a guard_default fixture is a real container, not bare protobuf.
sys.path.insert(0, str(_REPO / "tools" / "beyond-save"))

from gil_container import (  # noqa: E402
    SUBTYPE_LEVEL,
    Container,
    encode_container,
)

GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
HAVE_SAVE = GAME_DATA.exists()


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def _box() -> Bounds:
    """An 8x2x8 box from the origin -- a 3x3 grid at spacing 4 spans exactly it."""
    return Bounds(origin=(0.0, 0.0, 0.0), size=(8.0, 2.0, 8.0))


def _9_plots(origin=(0.0, 1.0, 0.0)) -> list[Placement]:
    return grid(
        template_id=TILE_SINGLE_FIELD,
        origin=origin,
        rows=3,
        cols=3,
        spacing=4.0,
    )


def _fixed32(value: float) -> bytes:
    return struct.pack("<f", value)


def _field(number: int, wire_type: int) -> bytes:
    return bytes([(number << 3) | wire_type])


def _length_delimited(number: int, payload: bytes) -> bytes:
    assert len(payload) < 128, "test builder only needs one-byte lengths"
    return _field(number, 2) + bytes([len(payload)]) + payload


def _payload_with_extent() -> bytes:
    """top field 11 = {1: {1: (100,100,100)}} -- the real file-11 shape."""
    vec = b"".join(_field(n, 5) + _fixed32(100.0) for n in (1, 2, 3))
    return _length_delimited(11, _length_delimited(1, _length_delimited(1, vec)))


def _write_gil(folder: Path, name: str, payload: bytes) -> Path:
    path = folder / name
    path.write_bytes(encode_container(Container(subtype=SUBTYPE_LEVEL, payload=payload)))
    return path


class _ScratchMixin:
    @classmethod
    def setUpClass(cls):
        cls._scratch = _REPO / ".runtime" / "scratch"
        cls._scratch.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# the verdict is a three-way, and the codes differ
# --------------------------------------------------------------------------- #

class TestVerdictShape(unittest.TestCase):
    def test_out_of_bounds_and_unknown_are_different_objects_and_codes(self):
        # The assertion the whole module exists for: a box-known rejection and a
        # no-box refusal must NOT be the same answer.
        out = guard(_9_plots(origin=(1000.0, 1.0, 1000.0)), bounds=_box())
        unknown = guard(_9_plots(), bounds=None)

        self.assertIsInstance(out, OutOfBounds)
        self.assertIsInstance(unknown, Uncertified)
        self.assertNotIsInstance(out, Uncertified)
        self.assertNotIsInstance(unknown, OutOfBounds)

        self.assertNotEqual(out.code, unknown.code)
        self.assertEqual(out.code, CODE_OUT_OF_BOUNDS)
        self.assertEqual(unknown.code, CODE_BOUNDS_UNKNOWN)
        self.assertIsNot(out, unknown)

    def test_unknown_does_not_block_but_out_of_bounds_does(self):
        out = guard(_9_plots(origin=(1000.0, 1.0, 1000.0)), bounds=_box())
        unknown = guard(_9_plots(), bounds=None)

        self.assertTrue(out.blocking)
        self.assertFalse(out.may_proceed)

        self.assertFalse(unknown.blocking)
        self.assertTrue(unknown.may_proceed)

    def test_both_negatives_are_falsy_so_bool_is_not_the_decision(self):
        # Documented footgun: ok=False for BOTH negatives.  This is why callers
        # must read .blocking / .code, not truthiness.
        out = guard(_9_plots(origin=(1000.0, 1.0, 1000.0)), bounds=_box())
        unknown = guard(_9_plots(), bounds=None)
        self.assertFalse(out.ok)
        self.assertFalse(unknown.ok)
        self.assertFalse(bool(out))
        self.assertFalse(bool(unknown))
        # ... and the certified pass is the only truthy verdict.
        self.assertTrue(bool(guard(_9_plots(), bounds=_box())))

    def test_all_verdicts_share_the_base(self):
        for verdict in (
            guard(_9_plots(), bounds=_box()),
            guard(_9_plots(origin=(1000.0, 1.0, 1000.0)), bounds=_box()),
            guard(_9_plots(), bounds=None),
        ):
            self.assertIsInstance(verdict, GuardVerdict)


# --------------------------------------------------------------------------- #
# known box: inside / outside / on the face
# --------------------------------------------------------------------------- #

class TestKnownBox(unittest.TestCase):
    def test_inside_is_certified(self):
        verdict = guard(_9_plots(), bounds=_box())
        self.assertIsInstance(verdict, Certified)
        self.assertTrue(verdict.ok)
        self.assertTrue(verdict.certified)
        self.assertFalse(verdict.blocking)
        self.assertTrue(verdict.may_proceed)
        self.assertEqual(verdict.code, CODE_CERTIFIED)
        self.assertEqual(verdict.count, 9)
        # A pass carries no offenders field at all -- nothing failed.
        self.assertFalse(hasattr(verdict, "offenders"))

    def test_outside_lists_the_offenders(self):
        # Shift one tile to x=1000; every tile is then out on x, but only that
        # one tile's row is out -- assert on the record, not just the count.
        plots = _9_plots()
        plots[1] = Placement(TILE_SINGLE_FIELD, 1000.0, 1.0, 0.0, "plot_1")
        verdict = guard(plots, bounds=_box())

        self.assertIsInstance(verdict, OutOfBounds)
        self.assertTrue(verdict.blocking)
        self.assertFalse(verdict.may_proceed)
        self.assertEqual(verdict.code, CODE_OUT_OF_BOUNDS)
        self.assertEqual(verdict.count, 9)
        self.assertEqual(len(verdict.offenders), 1)
        offender = verdict.offenders[0]
        self.assertIsInstance(offender, Offender)
        self.assertEqual(offender.label, "plot_1")
        self.assertEqual(offender.position, (1000.0, 1.0, 0.0))
        self.assertEqual(offender.outside_axes, ("x",))

    def test_outside_names_axes_and_reads_without_collapsing(self):
        verdict = guard([(11.0, 99.0, -11.0)], bounds=_box())
        self.assertIsInstance(verdict, OutOfBounds)
        self.assertEqual(verdict.offenders[0].outside_axes, ("x", "y", "z"))
        self.assertIn("outside", verdict.reason)
        self.assertIn("11", verdict.reason)          # the offending x
        self.assertIn("1 of 1", verdict.reason)      # how many failed

    def test_a_face_point_is_inside_the_closed_box(self):
        # The box is CLOSED (tools/gameplan/bounds.py:104-105): corners and face
        # midpoints count as inside, so a grid that touches the wall certifies.
        for point in ((0.0, 0.0, 0.0), (8.0, 2.0, 8.0), (8.0, 1.0, 4.0), (4.0, 2.0, 0.0)):
            with self.subTest(point=point):
                verdict = guard([point], bounds=_box())
                self.assertIsInstance(verdict, Certified)

    def test_just_past_a_face_is_outside(self):
        # The negative control for the closed-box test above.
        for point in ((8.0001, 1.0, 4.0), (4.0, 2.0001, 4.0), (4.0, 1.0, -0.0001)):
            with self.subTest(point=point):
                self.assertIsInstance(guard([point], bounds=_box()), OutOfBounds)

    def test_empty_layout_with_a_known_box_is_vacuously_certified(self):
        verdict = guard([], bounds=_box())
        self.assertIsInstance(verdict, Certified)
        self.assertEqual(verdict.count, 0)

    def test_accepts_bare_three_sequences_and_placement_objects(self):
        self.assertIsInstance(guard([(1.0, 1.0, 1.0)], bounds=_box()), Certified)
        self.assertIsInstance(guard(_9_plots(), bounds=_box()), Certified)

    def test_consumes_a_generator_once(self):
        verdict = guard((p for p in _9_plots()), bounds=_box())
        self.assertIsInstance(verdict, Certified)
        self.assertEqual(verdict.count, 9)


# --------------------------------------------------------------------------- #
# unknown box: refuse to certify, but do NOT block
# --------------------------------------------------------------------------- #

class TestUnknownBox(unittest.TestCase):
    def test_guard_with_none_refuses_without_blocking(self):
        verdict = guard(_9_plots(), bounds=None)
        self.assertIsInstance(verdict, Uncertified)
        self.assertFalse(verdict.ok)
        self.assertFalse(verdict.certified)
        self.assertFalse(verdict.blocking)
        self.assertTrue(verdict.may_proceed)
        self.assertEqual(verdict.code, CODE_BOUNDS_UNKNOWN)

    def test_refusal_reason_says_so_out_loud(self):
        verdict = guard(_9_plots(), bounds=None)
        self.assertIn("bounds unknown", verdict.reason)
        self.assertIn("refusing to certify", verdict.reason)
        self.assertIn("NOT blocking", verdict.reason)
        # ... and it carries the shared evidence tail, so the negative reads
        # identically wherever it is surfaced.
        self.assertIn("运行后场景生效范围", verdict.reason)

    def test_unknown_is_not_a_pass(self):
        # The refusal must never be the certified value, for the same reason
        # tools/gameplan/bounds.py:199-200 makes it never the ok value.
        verdict = guard(_9_plots(), bounds=None)
        self.assertNotIsInstance(verdict, Certified)
        self.assertFalse(verdict.certified)

    def test_unknown_with_no_path_never_invents_a_box(self):
        # guard_default with no level path: still a refusal, still not blocking,
        # and NOT an out-of-bounds verdict even for far-away placements.
        verdict = guard_default(_9_plots(origin=(10_000.0, 1.0, 10_000.0)))
        self.assertIsInstance(verdict, Uncertified)
        self.assertFalse(verdict.blocking)
        self.assertIn("refusing to certify", verdict.reason)


# --------------------------------------------------------------------------- #
# malformed box refuses
# --------------------------------------------------------------------------- #

class TestMalformedBox(unittest.TestCase):
    def test_non_bounds_object_refuses(self):
        for bad in (
            {"origin": (0.0, 0.0, 0.0), "size": (8.0, 2.0, 8.0)},
            (0.0, 0.0, 0.0),
            "not a box",
            [0.0, 0.0, 0.0, 8.0, 2.0, 8.0],
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    guard(_9_plots(), bounds=bad)

    def test_malformed_is_not_treated_as_none(self):
        # A malformed box must NOT quietly become the "unknown" refusal -- that
        # would hide the caller's bug behind a benign-looking verdict.
        with self.assertRaises(ValueError) as ctx:
            guard(_9_plots(), bounds={"origin": (0, 0, 0)})
        self.assertIn("Bounds", str(ctx.exception))

    def test_unreadable_placement_refuses(self):
        with self.assertRaises(ValueError):
            guard([(1.0, 2.0)], bounds=_box())   # arity 2
        with self.assertRaises(ValueError):
            guard(["not a point"], bounds=_box())


# --------------------------------------------------------------------------- #
# the explicit-box certification path (what a human uses)
# --------------------------------------------------------------------------- #

class TestExplicitCertification(unittest.TestCase):
    def test_human_supplied_box_certifies_a_known_good_layout(self):
        # A human who knows the scene range supplies the box; the guard then
        # certifies (a definite, non-blocking pass) rather than refusing.
        plots = _9_plots(origin=(4.0, 0.5, 4.0))
        box = Bounds(origin=(-10.0, 0.0, -10.0), size=(30.0, 4.0, 30.0))
        verdict = guard(plots, bounds=box)
        self.assertIsInstance(verdict, Certified)
        self.assertEqual(verdict.bounds, box)
        self.assertEqual(verdict.count, 9)

    def test_same_placements_certify_or_reject_depending_on_the_box(self):
        # Certifiability is a function of the box, not of the layout alone.
        plots = _9_plots()
        tight = Bounds(origin=(0.0, 0.0, 0.0), size=(8.0, 2.0, 8.0))
        shifted = Bounds(origin=(-100.0, 0.0, -100.0), size=(8.0, 2.0, 8.0))
        self.assertIsInstance(guard(plots, bounds=tight), Certified)
        self.assertIsInstance(guard(plots, bounds=shifted), OutOfBounds)


# --------------------------------------------------------------------------- #
# guard_default against a (synthetic) level -- load_bounds yields None today
# --------------------------------------------------------------------------- #

class TestGuardDefault(_ScratchMixin, unittest.TestCase):
    def test_default_reads_no_box_and_refuses_without_blocking(self):
        # The real file-11 shape: the invariant (100,100,100) vector.  Today
        # load_bounds cannot make a box of it (tools/gameplan/bounds.py:279-292),
        # so guard_default must refuse -- not block, not pass.
        with tempfile.TemporaryDirectory(dir=self._scratch) as folder:
            path = _write_gil(Path(folder), "1073741900.gil", _payload_with_extent())
            verdict = guard_default(_9_plots(), level_gil_path=path)
        self.assertIsInstance(verdict, Uncertified)
        self.assertEqual(verdict.code, CODE_BOUNDS_UNKNOWN)
        self.assertFalse(verdict.blocking)
        self.assertTrue(verdict.may_proceed)
        self.assertIn("load_bounds", verdict.reason)
        self.assertIn("refusing to certify", verdict.reason)

    def test_default_does_not_derive_a_box_from_the_invariant_triple(self):
        # Guard against futures where (100,100,100) is silently treated as a box:
        # if it were, these far-away placements would become OUT_OF_BOUNDS.  The
        # correct answer is still the unknown refusal.
        with tempfile.TemporaryDirectory(dir=self._scratch) as folder:
            path = _write_gil(Path(folder), "1073741901.gil", _payload_with_extent())
            verdict = guard_default(_9_plots(origin=(500.0, 1.0, 500.0)), level_gil_path=path)
        self.assertIsInstance(verdict, Uncertified)
        self.assertNotIsInstance(verdict, OutOfBounds)

    def test_missing_level_file_propagates_the_read_fault(self):
        # "cannot read the level" is a fault, not an unknown-bounds refusal
        # (tools/gameplan/bounds.py:296-302) -- guard_default must not swallow it.
        with self.assertRaises(FileNotFoundError):
            guard_default(_9_plots(), level_gil_path=Path("does") / "not" / "exist.gil")


@unittest.skipUnless(HAVE_SAVE, "no live Miliastra save on this machine")
class TestLiveSaveRefuses(_ScratchMixin, unittest.TestCase):
    def _first_level(self) -> Path | None:
        for directory in GAME_DATA.rglob("Beyond_Local_Save_Level"):
            for gil in sorted(directory.rglob("*.gil")):
                return gil
        return None

    def test_real_level_refuses_without_blocking(self):
        gil = self._first_level()
        if gil is None:
            self.skipTest("no level .gil in this save")
        verdict = guard_default(_9_plots(), level_gil_path=gil)
        # READ-ONLY: the guard never writes; a real level has no certifiable box.
        self.assertIsInstance(verdict, Uncertified)
        self.assertFalse(verdict.blocking)
        self.assertTrue(verdict.may_proceed)


if __name__ == "__main__":
    unittest.main()
