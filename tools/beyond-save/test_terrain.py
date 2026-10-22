"""Tests for ``tools/beyond-save/terrain.py`` -- the field-7 terrain decoder.

Three things must hold, in the order the task names them:

(a) a real file decodes to 400 cells with ``x, y`` in ``100..119``;
(b) a file with no field 7 fails *cleanly* (a named exception, not an empty grid);
(c) decoding is read-only -- re-serialising the untouched bytes returns them
    byte for byte, and the file on disk is unchanged.

The real level files are read from the live game directory but never written to.
The "no field 7" case is exercised on a *synthetic* level built here, so it does
not depend on the live save keeping its placeholder levels.

Run::

    python -B tools/beyond-save/test_terrain.py
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gil_container as g  # noqa: E402
import terrain  # noqa: E402
from terrain import TerrainError, read_terrain_fields  # noqa: E402

GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
LEVEL_DIR = GAME_DATA / "100000001" / "Beyond_Local_Save_Level"

# Levels on this machine that carry the (default, untouched) terrain.
REAL_TERRAIN_LEVELS = (1073741825, 1073741828, 1073741829)
# Placeholder levels (79/78 bytes) that carry no terrain at all.
REAL_PLACEHOLDER_LEVELS = (1073741826, 1073741827)

# The default terrain id is deliberately NOT the level id; it is a constant that
# shows up in every file. The name is the one the editor shows.
DEFAULT_TERRAIN_ID = 1073741825
DEFAULT_TERRAIN_NAME = "地形01"
DEFAULT_TRANSFORM = (-547.5, -2.5, -547.5)

HAVE_REAL = LEVEL_DIR.exists()


def level_path(n: int) -> Path:
    return LEVEL_DIR / f"{n}.gil"


def top_field7(path: Path) -> g.Field | None:
    """The raw field-7 entry of a level file, or None if it has none."""
    payload = g.decode_container(path.read_bytes()).payload
    for f in g.parse_fields(payload):
        if f.number == terrain.FIELD_TERRAIN_LIST:
            return f
    return None


def make_level_bytes(level_id: int, name: bytes = b"placeholder") -> bytes:
    """A minimal, field-7-free level container (schema-wise a real placeholder)."""
    payload = g.encode_fields([
        g.Field(1, g.WIRE_VARINT, value=level_id),
        g.Field(2, g.WIRE_LENGTH, data=name),
    ])
    return g.encode_container(g.Container(subtype=g.SUBTYPE_LEVEL, payload=payload))


@unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
class RealTerrainTest(unittest.TestCase):
    """(a) and (c) against the real level files."""

    def _first_available(self) -> Path:
        for n in REAL_TERRAIN_LEVELS:
            p = level_path(n)
            if p.exists() and top_field7(p) is not None:
                return p
        self.skipTest("none of the real terrain levels are present")

    def test_a_real_file_has_400_cells_in_the_100_119_grid(self):
        path = self._first_available()
        info = read_terrain_fields(path)

        self.assertEqual(info.cell_count, 400, "a default terrain is 20x20")
        for (x, y) in info.cells:
            self.assertTrue(100 <= x <= 119, f"x={x} out of the observed 100..119")
            self.assertTrue(100 <= y <= 119, f"y={y} out of the observed 100..119")

        xs = {x for x, _ in info.cells}
        ys = {y for _, y in info.cells}
        self.assertEqual((min(xs), max(xs)), (100, 119))
        self.assertEqual((min(ys), max(ys)), (100, 119))
        # Every coordinate of the 20x20 square, exactly once -- a grid, not a list.
        self.assertEqual(len(info.cells), len(xs) * len(ys))
        self.assertEqual(
            set(info.cells), {(x, y) for x in range(100, 120) for y in range(100, 120)}
        )

    def test_terrain_id_is_a_constant_not_the_level_id(self):
        for n in REAL_TERRAIN_LEVELS:
            p = level_path(n)
            if not p.exists() or top_field7(p) is None:
                continue
            with self.subTest(level=n):
                info = read_terrain_fields(p)
                self.assertEqual(info.terrain_id, DEFAULT_TERRAIN_ID)
                self.assertEqual(info.name, DEFAULT_TERRAIN_NAME)
                # This is the point: a level whose id differs still reports the
                # same terrain id, so "terrain id == level id" is false.
                if n != DEFAULT_TERRAIN_ID:
                    self.assertNotEqual(info.terrain_id, n)

    def test_default_transform_decodes_to_three_floats(self):
        path = self._first_available()
        info = read_terrain_fields(path)
        self.assertIsNotNone(info.transform)
        for got, want in zip(info.transform, DEFAULT_TRANSFORM):
            self.assertAlmostEqual(got, want, places=4)

    def test_default_terrain_is_byte_identical_across_files(self):
        """All the real levels still carry the *same* untouched default terrain."""
        digests = {}
        for n in REAL_TERRAIN_LEVELS:
            p = level_path(n)
            if not p.exists() or top_field7(p) is None:
                continue
            digests[n] = hashlib.sha256(top_field7(p).data).hexdigest()
        if len(digests) < 2:
            self.skipTest("fewer than two real terrain levels present")
        self.assertEqual(len(set(digests.values())), 1, digests)

    def test_c_read_only_reserialise_is_byte_identical(self):
        """(c) Decode, re-serialise, and confirm nothing moved -- on disk or in bytes."""
        for n in REAL_TERRAIN_LEVELS:
            p = level_path(n)
            if not p.exists() or top_field7(p) is None:
                continue
            with self.subTest(level=n):
                blob = p.read_bytes()
                info = read_terrain_fields(p)

                # field 7 round-trips through the raw walker byte for byte.
                self.assertEqual(terrain.reserialise_field7(info), top_field7(p).data)
                # ... and so does the whole payload.
                payload = g.decode_container(blob).payload
                self.assertEqual(g.encode_fields(g.parse_fields(payload)), payload)
                # The file itself was never opened for writing.
                self.assertEqual(p.read_bytes(), blob)

    def test_describe_reports_level_and_cells(self):
        path = self._first_available()
        info = read_terrain_fields(path)
        text = info.describe()
        self.assertIn(f"level {info.level_id}", text)
        self.assertIn("400 cells", text)
        self.assertIn(DEFAULT_TERRAIN_NAME, text)


@unittest.skipUnless(HAVE_REAL, "no live Miliastra save on this machine")
class RealPlaceholderTest(unittest.TestCase):
    """(b) on the real placeholder files, when they are still placeholders."""

    def test_real_placeholder_level_has_no_terrain_and_raises(self):
        checked = 0
        for n in REAL_PLACEHOLDER_LEVELS:
            p = level_path(n)
            if not p.exists() or top_field7(p) is not None:
                continue
            with self.subTest(level=n):
                with self.assertRaises(TerrainError) as ctx:
                    read_terrain_fields(p)
                self.assertIn("no field 7", str(ctx.exception))
                checked += 1
        if checked == 0:
            self.skipTest("no placeholder level present (all have terrain now)")


class NoTerrainTest(unittest.TestCase):
    """(b) guaranteed, on a synthetic level -- independent of the live save."""

    def test_level_without_field7_raises_cleanly(self):
        level_id = 0x40000099
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{level_id}.gil"
            path.write_bytes(make_level_bytes(level_id))
            # Sanity: the synthetic file really is a decodable level...
            self.assertEqual(g.read_level(path).level_id, level_id)
            # ...but it has no terrain, and that is a named, catchable failure.
            with self.assertRaises(TerrainError) as ctx:
                read_terrain_fields(path)
            self.assertIn("no field 7", str(ctx.exception))
            self.assertIn(str(level_id), str(ctx.exception))

    def test_truncated_container_still_raises_container_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "1073741977.gil"
            blob = make_level_bytes(1073741977)
            path.write_bytes(blob[:-4])  # chop the trailer
            with self.assertRaises(g.ContainerError):
                read_terrain_fields(path)


class ReadOnlySourceTest(unittest.TestCase):
    """The module offers no way to write, so 'read-only' is structural, not a promise."""

    def test_no_write_primitives_in_source(self):
        source = Path(terrain.__file__).read_text(encoding="utf-8")
        for forbidden in ("write_bytes", ".write(", "open(", "os.replace", "shutil."):
            self.assertNotIn(forbidden, source, f"{forbidden!r} would be a write path")


if __name__ == "__main__":
    unittest.main(verbosity=2)
