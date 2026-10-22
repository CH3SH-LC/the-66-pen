"""Offline tests for ``level.bounds`` -- the box and the pre-dispatch check.

Two paths are pinned, and each has a negative control:

  * the **explicit-box** path -- :func:`check_position` against a caller-supplied
    box, inside and outside, with the boundary cases;
  * the **no-bounds refusal** -- a check with no box must REFUSE
    (:class:`BoundsUnknown`), never pass, and :func:`load_bounds` must return
    ``None`` for the invariant field-11 triple AND for a level with no field 11.

The synthetic ``.gil`` fixtures are built here byte by byte, so the negative is
proven against the *shape the real files carry* (the ``(100,100,100)`` vector)
without needing a live save.  A live-save test, if the save is present, checks
that the same refusal comes back from a real file.

No bridge, no game, nothing written outside ``.runtime/scratch``.
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

from tools.gameplan.bounds import (
    Bounds,
    BoundsStatus,
    BoundsUnknown,
    Inside,
    OK,
    OutOfBounds,
    bounds_status,
    check_position,
    load_bounds,
)

# The container codec lives under tools/beyond-save; reach it the way bounds.py
# does so the synthetic fixtures are real containers, not bare protobuf.
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "tools" / "beyond-save"))

from gil_container import (  # noqa: E402
    SUBTYPE_LEVEL,
    Container,
    ContainerError,
    encode_container,
)

GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
HAVE_SAVE = GAME_DATA.exists()


# --------------------------------------------------------------------------- #
# synthetic .gil builders -- the observed shape, byte for byte
# --------------------------------------------------------------------------- #

def _fixed32(value: float) -> bytes:
    return struct.pack("<f", value)


def _field(number: int, wire_type: int) -> bytes:
    return bytes([(number << 3) | wire_type])


def _length_delimited(number: int, payload: bytes) -> bytes:
    assert len(payload) < 128, "test builder only needs one-byte lengths"
    return _field(number, 2) + bytes([len(payload)]) + payload


def _vec3_100() -> bytes:
    """The exact triple every real field-11 file carries: (100.0, 100.0, 100.0)."""
    return b"".join(
        _field(number, 5) + _fixed32(100.0) for number in (1, 2, 3)
    )


def _payload_with_extent() -> bytes:
    """top field 11 = {1: {1: (100,100,100)}} -- the real file-11 shape."""
    basic = _length_delimited(1, _vec3_100())
    return _length_delimited(11, _length_delimited(1, basic))


def _payload_without_field11() -> bytes:
    """A level payload with only field 2 (name) -- no settings payload."""
    return _length_delimited(2, b"placeholder")


def _write_gil(folder: Path, name: str, payload: bytes) -> Path:
    path = folder / name
    path.write_bytes(encode_container(Container(subtype=SUBTYPE_LEVEL, payload=payload)))
    return path


class _ScratchMixin:
    """A temp dir inside the project tree, so nothing is written outside it."""

    @classmethod
    def setUpClass(cls):
        cls._scratch = _REPO / ".runtime" / "scratch"
        cls._scratch.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# the explicit-box path
# --------------------------------------------------------------------------- #

class TestBoundsGeometry(unittest.TestCase):
    def test_corners(self):
        b = Bounds(origin=(-10.0, 0.0, -10.0), size=(20.0, 5.0, 20.0))
        self.assertEqual(b.min_corner, (-10.0, 0.0, -10.0))
        self.assertEqual(b.max_corner, (10.0, 5.0, 10.0))

    def test_inside_contains(self):
        b = Bounds(origin=(0.0, 0.0, 0.0), size=(4.0, 2.0, 4.0))
        self.assertTrue(b.contains((2.0, 1.0, 2.0)))
        self.assertEqual(b.outside_axes((2.0, 1.0, 2.0)), ())

    def test_closed_box_face_is_inside(self):
        # A point exactly on a face is inside: the box is closed, not half-open.
        b = Bounds(origin=(0.0, 0.0, 0.0), size=(4.0, 2.0, 4.0))
        self.assertTrue(b.contains((0.0, 0.0, 0.0)))       # min corner
        self.assertTrue(b.contains((4.0, 2.0, 4.0)))       # max corner
        self.assertTrue(b.contains((4.0, 1.0, 2.0)))       # mid of +x face

    def test_outside_axes_names_exactly_the_failed_axes(self):
        b = Bounds(origin=(0.0, 0.0, 0.0), size=(4.0, 2.0, 4.0))
        self.assertEqual(b.outside_axes((9.0, 1.0, 1.0)), ("x",))
        self.assertEqual(b.outside_axes((1.0, -5.0, 1.0)), ("y",))
        self.assertEqual(b.outside_axes((1.0, 1.0, -1.0)), ("z",))
        self.assertEqual(b.outside_axes((9.0, 1.0, 9.0)), ("x", "z"))
        self.assertEqual(b.outside_axes((-1.0, 99.0, -1.0)), ("x", "y", "z"))

    def test_non_positive_size_rejected(self):
        for bad in ((0.0, 1.0, 1.0), (1.0, -2.0, 1.0), (1.0, 1.0, 0.0)):
            with self.subTest(size=bad):
                with self.assertRaises(ValueError):
                    Bounds(origin=(0.0, 0.0, 0.0), size=bad)

    def test_wrong_arity_rejected(self):
        with self.assertRaises(ValueError):
            Bounds(origin=(0.0, 0.0), size=(1.0, 1.0, 1.0))


class TestCheckPositionExplicitBox(unittest.TestCase):
    def setUp(self):
        self.box = Bounds(origin=(-10.0, 0.0, -10.0), size=(20.0, 4.0, 20.0))

    def test_inside_returns_ok(self):
        verdict = check_position(self.box, (0.0, 1.0, 0.0))
        self.assertIsInstance(verdict, Inside)
        self.assertTrue(verdict.ok)
        self.assertTrue(verdict)                 # truthiness is ok
        self.assertEqual(verdict.reason, "")
        self.assertIs(verdict, OK)               # the shared ok value

    def test_outside_returns_out_of_bounds_with_reason(self):
        verdict = check_position(self.box, (150.0, 1.0, 0.0))
        self.assertIsInstance(verdict, OutOfBounds)
        self.assertFalse(verdict.ok)
        self.assertFalse(verdict)                # not truthy -> a caller's `if` catches it
        self.assertEqual(verdict.outside_axes, ("x",))
        self.assertEqual(verdict.point, (150.0, 1.0, 0.0))
        self.assertIn("150", verdict.reason)
        self.assertIn("outside", verdict.reason)

    def test_outside_on_multiple_axes(self):
        verdict = check_position(self.box, (11.0, 99.0, -11.0))
        self.assertIsInstance(verdict, OutOfBounds)
        self.assertEqual(verdict.outside_axes, ("x", "y", "z"))

    def test_negative_control_inside_is_not_outside(self):
        # Guard against a check that reports outside for everything.
        self.assertNotIsInstance(check_position(self.box, (0.0, 0.0, 0.0)), OutOfBounds)

    def test_boundary_point_is_inside(self):
        self.assertIs(check_position(self.box, (10.0, 4.0, 10.0)), OK)

    def test_accepts_a_list_as_well_as_a_tuple(self):
        self.assertIs(check_position(self.box, [0.0, 1.0, 0.0]), OK)

    def test_bad_point_rejected(self):
        with self.assertRaises(ValueError):
            check_position(self.box, (0.0, 1.0))
        with self.assertRaises(ValueError):
            check_position(self.box, "not a point")


# --------------------------------------------------------------------------- #
# the refusal path (no bounds known)
# --------------------------------------------------------------------------- #

class TestNoBoundsRefusal(unittest.TestCase):
    def test_none_refuses_never_passes(self):
        verdict = check_position(None, (0.0, 0.0, 0.0))
        self.assertIsInstance(verdict, BoundsUnknown)
        self.assertFalse(verdict.ok)
        self.assertFalse(verdict)
        # A refusal must NEVER be the ok value -- this is the whole point.
        self.assertIsNot(verdict, OK)

    def test_refusal_reason_says_unknown_and_names_the_field(self):
        verdict = check_position(None, (0.0, 0.0, 0.0))
        self.assertIn("UNKNOWN", verdict.reason)
        self.assertIn("运行后场景生效范围", verdict.reason)
        self.assertIn("LEVEL-SETTINGS-AND-BOUNDS.json", verdict.reason)


class TestBoundsStatus(_ScratchMixin, unittest.TestCase):
    def test_invariant_triple_yields_no_bounds(self):
        # The real file-11 shape: the (100,100,100) vector.  load_bounds must
        # NOT turn that constant into a box.
        with tempfile.TemporaryDirectory(dir=self._scratch) as folder:
            path = _write_gil(Path(folder), "1073741900.gil", _payload_with_extent())
            status = bounds_status(path)
            self.assertIsNone(status.bounds)
            self.assertIsNone(load_bounds(path))
            self.assertEqual(status.level_id, 1073741900)
            self.assertTrue(status.field11_present)
            self.assertIn("(100, 100, 100)", status.reason)
            self.assertIn("UNKNOWN", status.reason)

    def test_missing_field11_yields_no_bounds(self):
        with tempfile.TemporaryDirectory(dir=self._scratch) as folder:
            path = _write_gil(Path(folder), "1073741901.gil", _payload_without_field11())
            status = bounds_status(path)
            self.assertIsNone(status.bounds)
            self.assertFalse(status.field11_present)
            self.assertIn("ABSENT", status.reason)

    def test_check_position_agrees_with_load_bounds(self):
        # End to end: whatever box load_bounds gives (none, today), feeding it
        # straight into check_position must be the refusal, not a pass.
        with tempfile.TemporaryDirectory(dir=self._scratch) as folder:
            path = _write_gil(Path(folder), "1073741902.gil", _payload_with_extent())
            verdict = check_position(load_bounds(path), (0.0, 0.0, 0.0))
            self.assertIsInstance(verdict, BoundsUnknown)


class TestLoadBoundsReadErrors(unittest.TestCase):
    def test_missing_file_raises(self):
        # "cannot read the level" is a fault, not "no bounds known".
        with self.assertRaises(FileNotFoundError):
            load_bounds(Path("does") / "not" / "exist.gil")

    def test_garbage_bytes_raise_container_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.gil"
            path.write_bytes(b"not a gil container at all")
            with self.assertRaises(ContainerError):
                load_bounds(path)


# --------------------------------------------------------------------------- #
# the negative against a REAL save, when one is present
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_SAVE, "no live Miliastra save on this machine")
class TestLiveSaveHasNoBounds(unittest.TestCase):
    def _first_level_with_settings(self):
        level_dirs = list(GAME_DATA.rglob("Beyond_Local_Save_Level"))
        for directory in level_dirs:
            for gil in sorted(directory.rglob("*.gil")):
                try:
                    status = bounds_status(gil)
                except Exception:
                    continue
                if status.field11_present:
                    return gil, status
        return None, None

    def test_real_level_with_field11_still_has_no_bounds(self):
        gil, status = self._first_level_with_settings()
        if gil is None:
            self.skipTest("no level carrying field 11 in this save")
        self.assertIsNone(status.bounds)
        self.assertIn("(100, 100, 100)", status.reason)
        # ... and the real file feeds the refusal, not a pass.
        self.assertIsInstance(check_position(load_bounds(gil), (0.0, 0.0, 0.0)),
                              BoundsUnknown)


if __name__ == "__main__":
    unittest.main()
