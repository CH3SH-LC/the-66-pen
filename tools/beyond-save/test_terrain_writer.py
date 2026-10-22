"""Tests for the in-memory terrain writer added to ``tools/beyond-save/terrain.py``.

The writer is the prerequisite M6a never had: a way to change a cell of ``.gil``
field 7 *in memory* and get bytes back.  It does not make M6a work -- the game
would still have to accept the bytes -- so these tests only pin down what can be
proven offline:

(a) ``gil_container.encode_fields`` is a byte-exact round-trip, on a real level's
    whole payload and on its field-7 payload;
(b) reading a real level and re-encoding it **with no change** returns the exact
    original file bytes;
(c) changing ONE cell, re-encoding, and parsing again shows the new value, with
    everything else byte-identical -- proven by the strongest available signal,
    that exactly one byte of the file moved.  That fixed-offset signal is the
    *same-width* special case; a value that widens its varint (1 -> 129) grows the
    file by one and moves the tail, so locality there is proven at the value level
    instead (see ``test_a_wider_varint_grows_the_file_one_byte_and_only_the_target_cell_moves``);
(d) a cell outside the observed 100..119 grid is refused, and the refusal does
    not half-apply;
(e) the writer takes Python objects, never a path, and the writer source contains
    no file primitive -- so it cannot be pointed at a live save by accident.

Tests (b)-(d) run against the real level files, read-only; (a) and the synthetic
parts are independent of the live save so the suite still runs without one.

Run::

    python -B tools/beyond-save/test_terrain_writer.py
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gil_container as g  # noqa: E402
import terrain  # noqa: E402
from terrain import TerrainError  # noqa: E402

GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
LEVEL_DIR = GAME_DATA / "100000001" / "Beyond_Local_Save_Level"

# Levels that carry the default terrain on this machine.
REAL_TERRAIN_LEVELS = (1073741825, 1073741828, 1073741829)

HAVE_REAL = LEVEL_DIR.exists()


def level_path(n: int) -> Path:
    return LEVEL_DIR / f"{n}.gil"


def first_terrain_level() -> Path | None:
    for n in REAL_TERRAIN_LEVELS:
        p = level_path(n)
        if p.exists():
            try:
                if terrain.read_terrain_fields(p).cell_count:
                    return p
            except (TerrainError, g.ContainerError):
                continue
    return None


def synthetic_level(level_id: int = 0x40000099) -> g.Level:
    """A minimal level object with no field 7 (a placeholder-shaped level)."""
    payload = g.encode_fields([
        g.Field(1, g.WIRE_VARINT, value=level_id),
        g.Field(2, g.WIRE_LENGTH, data=b"writer-test"),
    ])
    return g.parse_level(payload, level_id=level_id)


# --------------------------------------------------------------------------- #
# (a) the byte-exact round-trip the writer leans on
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
class EncoderRoundTripTest(unittest.TestCase):
    """``encode_fields(parse_fields(x)) == x`` -- the property the writer rests on."""

    def test_payload_round_trips_byte_for_byte(self):
        for n in REAL_TERRAIN_LEVELS:
            p = level_path(n)
            if not p.exists():
                continue
            with self.subTest(level=n):
                payload = g.decode_container(p.read_bytes()).payload
                self.assertEqual(g.encode_fields(g.parse_fields(payload)), payload)

    def test_field7_round_trips_byte_for_byte(self):
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        info = terrain.read_terrain_fields(p)
        self.assertEqual(
            g.encode_fields(g.parse_fields(info.raw_field7.data)),
            info.raw_field7.data,
        )


# --------------------------------------------------------------------------- #
# (b) no change -> byte-identical to the real file
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
class NoChangeByteIdentityTest(unittest.TestCase):

    def test_reencode_without_edit_is_the_original_file(self):
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        original = p.read_bytes()

        level = g.read_level(p)
        info = terrain.terrain_fields_of(level)
        terrain.apply_terrain_fields(level, info)           # flush, no edit
        self.assertEqual(terrain.to_level_bytes(level), original)

        # ... and the file on disk was never opened for writing.
        self.assertEqual(p.read_bytes(), original)

    def test_field7_payload_unchanged_when_nothing_edited(self):
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        level = g.read_level(p)
        info = terrain.terrain_fields_of(level)
        self.assertEqual(terrain.encode_terrain_list(info), info.raw_field7.data)


# --------------------------------------------------------------------------- #
# (c) change ONE cell -> the change is there and everything else is byte-identical
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
class ChangeOneCellTest(unittest.TestCase):

    def test_one_cell_change_is_local_and_exactly_one_byte_moves(self):
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        original = p.read_bytes()

        level = g.read_level(p)
        info = terrain.terrain_fields_of(level)
        before = terrain.terrain_fields_of(level)

        target = info.terrains[0]
        old = target.cells[(105, 107)]
        self.assertLess(old, 0x7F, "expected the default one-byte value (1)")
        new_value = old + 2                                 # 1 -> 3, still one byte
        terrain.set_cell(target, 105, 107, new_value)
        terrain.apply_terrain_fields(level, info)
        blob = terrain.to_level_bytes(level)

        # Parse the result back, exactly as a fresh reader would.
        level2 = g.parse_level(g.decode_container(blob).payload, level_id=level.level_id)
        after = terrain.terrain_fields_of(level2)
        self.assertEqual(after.terrains[0].cells[(105, 107)], new_value)
        self.assertEqual(after.cell_count, before.cell_count)
        self.assertEqual(after.terrain_id, before.terrain_id)
        self.assertEqual(after.name, before.name)
        self.assertEqual(after.transform, before.transform)

        # The strongest locality signal: the value varint is the only byte that
        # differs -- no offset shift, no field reordering, nothing else moved.
        self.assertEqual(len(blob), len(original))
        diffs = [i for i, (a, b) in enumerate(zip(original, blob)) if a != b]
        self.assertEqual(len(diffs), 1, f"expected 1 differing byte, got {len(diffs)}")
        self.assertEqual(original[diffs[0]], old)
        self.assertEqual(blob[diffs[0]], new_value)

    def test_every_other_cell_and_top_level_field_is_unchanged(self):
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        original = p.read_bytes()

        level = g.read_level(p)
        info = terrain.terrain_fields_of(level)
        before = terrain.terrain_fields_of(level)
        terrain.set_cell(info.terrains[0], 100, 119, 4)
        terrain.apply_terrain_fields(level, info)
        blob = terrain.to_level_bytes(level)

        # Every top-level field except 7 is byte-identical; field 7 did change.
        orig_top = g.parse_fields(g.decode_container(original).payload)
        new_top = g.parse_fields(g.decode_container(blob).payload)
        self.assertEqual([f.number for f in orig_top], [f.number for f in new_top])
        for a, b in zip(orig_top, new_top):
            if a.number == terrain.FIELD_TERRAIN_LIST:
                self.assertNotEqual(a.data, b.data)
            else:
                self.assertEqual(g.encode_fields([a]), g.encode_fields([b]))

        level2 = g.parse_level(g.decode_container(blob).payload, level_id=level.level_id)
        after = terrain.terrain_fields_of(level2)
        # Every cell but the edited one matches, value for value.
        edited = (100, 119)
        self.assertEqual(
            {k for k in before.cells if k != edited},
            {k for k in after.cells if k != edited},
        )
        for key, value in before.cells.items():
            if key == edited:
                continue
            self.assertEqual(after.cells[key], value)
        self.assertEqual(after.cells[edited], 4)

    def test_a_wider_varint_grows_the_file_one_byte_and_only_the_target_cell_moves(self):
        """The same-width case above is the *special* case; a value that widens
        its varint is the general one, and it is a different, weaker locality.

        ``1 -> 3`` stays one varint byte, so the whole file differs at one offset
        (the test above).  ``1 -> 129`` needs two bytes, so the file grows by one:
        the container's length header, the field-7 length prefix and every byte
        after the insertion all move.  Locality then holds at the *value* level --
        the edited cell is the only cell that changed, and id/name/transform are
        unchanged -- not at the byte-offset level.  Pinned so the boundary between
        the two cases is measured, not assumed.
        """
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        original = p.read_bytes()

        level = g.read_level(p)
        info = terrain.terrain_fields_of(level)
        before = terrain.terrain_fields_of(level)

        target = info.terrains[0]
        edited = (105, 107)
        old = target.cells[edited]
        self.assertLess(old, 0x7F, "expected the default one-byte value (1)")
        new_value = old + 128                       # 1 -> 129: a two-byte varint
        terrain.set_cell(target, edited[0], edited[1], new_value)
        terrain.apply_terrain_fields(level, info)
        blob = terrain.to_level_bytes(level)

        # A width change grows the file by exactly the extra varint byte ...
        self.assertEqual(len(blob), len(original) + 1)
        # ... so it is NOT the fixed-offset single-byte diff of the same-width case.
        n = min(len(original), len(blob))
        diffs = [i for i in range(n) if original[i] != blob[i]]
        self.assertGreater(len(diffs), 1)

        # Re-decode: the change is there; every OTHER cell and every non-cell
        # field is unchanged, value for value.
        level2 = g.parse_level(g.decode_container(blob).payload, level_id=level.level_id)
        after = terrain.terrain_fields_of(level2)
        self.assertEqual(after.terrains[0].cells[edited], new_value)
        self.assertEqual(after.cell_count, before.cell_count)
        self.assertEqual(after.terrain_id, before.terrain_id)
        self.assertEqual(after.name, before.name)
        self.assertEqual(after.transform, before.transform)
        self.assertEqual(
            {k for k in before.cells if k != edited},
            {k for k in after.cells if k != edited},
        )
        for key, value in before.cells.items():
            if key == edited:
                continue
            self.assertEqual(after.cells[key], value)

        # The top-level field set is unchanged; the container still says "level".
        orig_top = g.parse_fields(g.decode_container(original).payload)
        new_top = g.parse_fields(g.decode_container(blob).payload)
        self.assertEqual([f.number for f in orig_top], [f.number for f in new_top])
        for a, b in zip(orig_top, new_top):
            if a.number == terrain.FIELD_TERRAIN_LIST:
                self.assertNotEqual(a.data, b.data)
            else:
                self.assertEqual(g.encode_fields([a]), g.encode_fields([b]))


# --------------------------------------------------------------------------- #
# (d) a cell outside the grid is refused (and the refusal does not half-apply)
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
class RefuseOutOfGridTest(unittest.TestCase):

    def _terrain(self):
        p = first_terrain_level()
        if p is None:
            self.skipTest("no real terrain level present")
        return terrain.terrain_fields_of(g.read_level(p)).terrains[0]

    def test_each_side_of_the_grid_is_refused(self):
        t = self._terrain()
        for (x, y) in [(99, 100), (100, 99), (120, 100), (100, 120),
                       (0, 0), (200, 200), (-1, 100), (1 << 16, 1 << 16)]:
            with self.subTest(cell=(x, y)):
                with self.assertRaises(TerrainError):
                    terrain.set_cell(t, x, y, 1)

    def test_in_bounds_cell_is_accepted(self):
        t = self._terrain()
        for (x, y) in [(100, 100), (119, 119), (105, 107)]:
            terrain.set_cell(t, x, y, 2)
            self.assertEqual(t.cells[(x, y)], 2)

    def test_a_refused_edit_leaves_the_terrain_untouched(self):
        t = self._terrain()
        snapshot = dict(t.cells)
        with self.assertRaises(TerrainError):
            terrain.set_cell(t, 200, 100, 9)
        self.assertEqual(t.cells, snapshot)

    def test_add_terrain_refuses_an_out_of_grid_cell(self):
        level = synthetic_level()
        with self.assertRaises(TerrainError):
            terrain.add_terrain(level.raw, cells={(99, 100): 1})
        # The refusal left field 7 uncreated.
        self.assertFalse(any(f.number == terrain.FIELD_TERRAIN_LIST for f in level.raw))

    def test_negative_and_non_int_values_are_refused(self):
        t = self._terrain()
        for bad in (-1, 1.5, "3", None, True):
            with self.subTest(value=bad):
                with self.assertRaises(TerrainError):
                    terrain.set_cell(t, 105, 107, bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# (e) the writer takes objects, not paths -- structurally
# --------------------------------------------------------------------------- #

class WriterTakesObjectsNotPathsTest(unittest.TestCase):

    WRITERS = ("set_cell", "add_terrain", "apply_terrain_fields", "to_level_bytes")

    def test_no_writer_parameter_is_a_path(self):
        for name in self.WRITERS:
            fn = getattr(terrain, name)
            params = inspect.signature(fn).parameters
            for param in params:
                self.assertNotIn(
                    "path", param.lower(),
                    f"{name}: parameter {param!r} looks like a path",
                )

    def test_writer_source_has_no_file_primitive(self):
        source = "".join(inspect.getsource(getattr(terrain, n)) for n in self.WRITERS)
        for forbidden in ("write_bytes", ".write(", "open(", "Path(", "os.replace", "shutil."):
            self.assertNotIn(forbidden, source, f"{forbidden!r} would be a file path")

    def test_to_level_bytes_rejects_a_string_instead_of_a_level(self):
        with self.assertRaises(TerrainError):
            terrain.to_level_bytes(str(level_path(1073741825)))  # type: ignore[arg-type]

    def test_set_cell_rejects_a_string_instead_of_a_terrain(self):
        with self.assertRaises(TerrainError):
            terrain.set_cell(str(level_path(1073741825)), 105, 107, 1)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# synthetic -- independent of the live save
# --------------------------------------------------------------------------- #

class SyntheticWriterTest(unittest.TestCase):
    """A level is built, given a terrain, edited, and read back -- no real file."""

    LEVEL_ID = 0x40000099

    def test_add_terrain_then_set_cell_round_trips(self):
        level = synthetic_level(self.LEVEL_ID)
        self.assertFalse(any(f.number == terrain.FIELD_TERRAIN_LIST for f in level.raw))

        added = terrain.add_terrain(
            level.raw,
            terrain_id=self.LEVEL_ID,
            name="地形01",
            transform=(-547.5, -2.5, -547.5),
        )
        self.assertEqual(len(added.cells), terrain.CELLS_PER_TERRAIN)

        # Edit through a decode of the level, so the flush carries the change.
        info = terrain.terrain_fields_of(level)
        terrain.set_cell(info.terrains[0], 110, 111, 9)
        terrain.apply_terrain_fields(level, info)

        blob = terrain.to_level_bytes(level)
        level2 = g.parse_level(g.decode_container(blob).payload, level_id=self.LEVEL_ID)
        info2 = terrain.terrain_fields_of(level2)
        self.assertEqual(len(info2.terrains), 1)
        self.assertEqual(info2.name, "地形01")
        self.assertEqual(info2.cell_count, terrain.CELLS_PER_TERRAIN)
        self.assertEqual(info2.cells[(110, 111)], 9)
        self.assertAlmostEqual(info2.transform[0], -547.5, places=4)

    def test_payload_bytes_are_immutable_and_reencoding_is_stable(self):
        """Re-encoding a level twice yields identical bytes (no drift)."""
        level = synthetic_level(self.LEVEL_ID)
        terrain.add_terrain(level.raw, terrain_id=self.LEVEL_ID, name="地形01")
        first = terrain.to_level_bytes(level)
        self.assertEqual(terrain.to_level_bytes(level), first)


# --------------------------------------------------------------------------- #
# (f) the blob-level surface -- the field15_edit idiom applied to field 7
# --------------------------------------------------------------------------- #

def synthetic_two_terrain_blob() -> bytes:
    """A level blob with TWO terrains, built through the object writers."""
    level = synthetic_level(0x40000099)
    terrain.add_terrain(level.raw, terrain_id=1000001, name="terrain-A")
    terrain.add_terrain(level.raw, terrain_id=1000002, name="terrain-B")
    return terrain.to_level_bytes(level)


class BlobSurfaceTest(unittest.TestCase):
    """``reserialise_level`` / ``terrain_digests`` / ``edit_cell``: bytes in, bytes out."""

    def test_reserialise_level_is_byte_exact_on_synthetic(self):
        blob = synthetic_two_terrain_blob()
        self.assertEqual(terrain.reserialise_level(blob), blob)

    @unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
    def test_reserialise_level_is_byte_exact_on_real_files(self):
        for n in REAL_TERRAIN_LEVELS:
            p = level_path(n)
            if not p.exists():
                continue
            with self.subTest(level=n):
                blob = p.read_bytes()
                self.assertEqual(terrain.reserialise_level(blob), blob)

    def test_terrain_digests_one_per_terrain_and_unique_per_terrain(self):
        blob = synthetic_two_terrain_blob()
        d = terrain.terrain_digests(blob)
        self.assertEqual(len(d), 2)
        self.assertNotEqual(d[0], d[1], "two distinct terrains must not share a digest")

    def test_edit_cell_proves_every_other_terrain_untouched_by_digest(self):
        blob = synthetic_two_terrain_blob()
        edit = terrain.edit_cell(blob, 105, 107, 3, terrain_index=0)
        # Exactly the edited terrain's digest moved; the other did not.
        self.assertEqual(edit.touched_indices, (0,))
        self.assertEqual(edit.untouched_indices, (1,))
        self.assertEqual(edit.terrain_count_before, edit.terrain_count_after)
        # ... and the edit is real on re-read.
        after = terrain.terrain_fields_of(g.parse_level(
            g.decode_container(edit.blob).payload, level_id=0x40000099))
        self.assertEqual(after.terrains[0].cells[(105, 107)], 3)
        self.assertEqual(after.terrains[1].cells[(105, 107)], 1)   # untouched terrain

    def test_edit_cell_same_width_is_zero_byte_delta(self):
        blob = synthetic_two_terrain_blob()
        edit = terrain.edit_cell(blob, 105, 107, 2)
        self.assertEqual(edit.byte_delta, 0)
        self.assertEqual(edit.digests_before[0] == edit.digests_after[0], False)

    def test_edit_cell_wider_varint_grows_the_file_and_still_touches_one_terrain(self):
        blob = synthetic_two_terrain_blob()
        edit = terrain.edit_cell(blob, 105, 107, 129)
        self.assertEqual(edit.byte_delta, 1)
        self.assertEqual(edit.touched_indices, (0,))

    def test_edit_cell_refuses_out_of_grid_and_produces_no_bytes(self):
        blob = synthetic_two_terrain_blob()
        with self.assertRaises(TerrainError):
            terrain.edit_cell(blob, 99, 100, 1)
        with self.assertRaises(TerrainError):
            terrain.edit_cell(blob, 105, 107, -1)
        with self.assertRaises(TerrainError):
            terrain.edit_cell(blob, 105, 107, 1, terrain_index=5)

    def test_edit_cell_refuses_a_non_level_container(self):
        not_level = g.encode_container(g.Container(subtype=1, payload=b"\x08\x01"))
        with self.assertRaises(TerrainError):
            terrain.edit_cell(not_level, 105, 107, 1)
        with self.assertRaises(TerrainError):
            terrain.reserialise_level(not_level)

    def test_terrain_digests_raises_without_field7(self):
        no_terrain = terrain.to_level_bytes(synthetic_level())
        with self.assertRaises(TerrainError):
            terrain.terrain_digests(no_terrain)


class BlobSurfaceIsInMemoryOnlyTest(unittest.TestCase):
    """The blob surface takes ``bytes`` and reaches no file primitive -- structurally."""

    FUNCS = ("reserialise_level", "terrain_digests", "edit_cell")

    def test_no_function_parameter_is_a_path(self):
        for name in self.FUNCS:
            params = inspect.signature(getattr(terrain, name)).parameters
            for param in params:
                self.assertNotIn("path", param.lower(),
                                 f"{name}: parameter {param!r} looks like a path")

    def test_source_has_no_file_primitive(self):
        source = "".join(inspect.getsource(getattr(terrain, n)) for n in self.FUNCS)
        for forbidden in ("write_bytes", ".write(", "open(", "Path(", "os.replace", "shutil."):
            self.assertNotIn(forbidden, source, f"{forbidden!r} would be a file path")

    def test_edit_cell_rejects_a_string_blob_instead_of_bytes(self):
        with self.assertRaises((TerrainError, g.ContainerError, TypeError, AttributeError)):
            terrain.edit_cell(str(level_path(1073741825)), 105, 107, 1)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main(verbosity=2)
