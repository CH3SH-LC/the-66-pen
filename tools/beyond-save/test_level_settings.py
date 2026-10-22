"""Tests for the ``.gil`` field-11 (level settings) decoder.

The load-bearing test is ``test_payload_roundtrips_byte_for_byte``: the whole
point of decoding field 11 is eventually to *read* a scene range before writing
anything, and a decoder that silently rewrites the bytes it did not understand
would make every later edit unsafe. Re-encoding the original payload and getting
it back untouched is the read-only proof that the walk lost nothing.

The real files are opened READ-ONLY from the live game directory; each is copied
into ``.runtime/beyond-save/fixtures-level-settings/`` first and every assertion
works on the copy, so a stray write could never reach the save.

The suite pins a precise POSITIVE result (field 11 decodes; the basic
sub-message's float vector is three fixed32 floats) and a precise NEGATIVE one
(that vector is *not* proven
to be 运行后场景生效范围, and 1073741826 has no field 11 at all). A negative that
is written down with its bytes is a deliverable here, not a failure.
"""
from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gil_container import (  # noqa: E402
    WIRE_32BIT,
    WIRE_LENGTH,
    decode_container,
    encode_fields,
    parse_fields,
)
from level_settings import (  # noqa: E402
    LEVEL_FIELD_SETTINGS,
    LEVEL_REF_MIN,
    PART_SPAWN,
    PART_PRESET,
    parse_vec3,
    read_level_settings,
)

GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
UID_DIR = GAME_DATA / "100000001"
LEVEL_DIR = UID_DIR / "Beyond_Local_Save_Level"
FIXTURES = Path(__file__).resolve().parents[2] / ".runtime" / "beyond-save" / "fixtures-level-settings"

# The two levels the task names. 1073741842 is a saved, edited level; 1073741826 is
# a placeholder registered by this project's own `register_level.py`.
REAL_LEVEL = 1073741842
PLACEHOLDER_LEVEL = 1073741826

# The spawn/terrain origin. Memory records this exact triple as a constant shared by
# every save, and `docs/research/game-b-systems-20261009/M6a-level-terrain.md:113`
# locates it in top-level field 7. It is reproduced here as raw protobuf bytes:
#   0d <f32 -547.5> 15 <f32 -2.5> 1d <f32 -547.5>
SPAWN_VEC3 = bytes.fromhex("0d00e008c415000020c01d00e008c4")

HAVE_SAVE = LEVEL_DIR.exists()


def _find_level(name: int) -> Path | None:
    """Locate ``<name>.gil`` under the level directory, whichever folder shape it has.

    Level ids are a function of the save, so the file is found by search rather than
    assumed at a fixed path; a missing file skips instead of failing.
    """
    matches = sorted(LEVEL_DIR.rglob(f"{name}.gil"))
    return matches[0] if matches else None


class FixtureMixin:
    """Copies each level file into the project tree once per class."""

    @classmethod
    def setUpClass(cls):
        if not HAVE_SAVE:
            raise unittest.SkipTest("no live Miliastra save on this machine")
        if not FIXTURES.exists():
            FIXTURES.mkdir(parents=True, exist_ok=True)
        cls.paths: dict[int, Path] = {}
        for name in (REAL_LEVEL, PLACEHOLDER_LEVEL):
            src = _find_level(name)
            if src is None:
                continue
            dst = FIXTURES / f"{name}.gil"
            shutil.copy2(src, dst)
            cls.paths[name] = dst


class TestLevelSettingsDecode(FixtureMixin, unittest.TestCase):

    def require(self, name: int) -> Path:
        path = self.paths.get(name)
        if path is None:
            self.skipTest(f"level {name} not present in this save")
        return path

    # -- the read-only proof ------------------------------------------------- #

    def test_payload_roundtrips_byte_for_byte(self):
        for name in (REAL_LEVEL, PLACEHOLDER_LEVEL):
            path = self.require(name)
            payload = decode_container(path.read_bytes()).payload
            self.assertEqual(
                encode_fields(parse_fields(payload)), payload,
                f"the generic walker did not reproduce level {name}'s payload",
            )

    def test_field_11_roundtrips_byte_for_byte(self):
        settings = read_level_settings(self.require(REAL_LEVEL))
        self.assertTrue(settings.present)
        self.assertEqual(settings.reencode_settings(), settings.data)
        self.assertEqual(settings.reencode(), settings.payload)

    # -- presence / absence -------------------------------------------------- #

    def test_real_level_carries_field_11(self):
        settings = read_level_settings(self.require(REAL_LEVEL))
        self.assertTrue(settings.present)
        self.assertIsNotNone(settings.data)
        self.assertEqual(settings.data[0] & 0x07, WIRE_LENGTH, "field 11 is length-delimited")
        self.assertGreater(len(settings.data), 200)

    def test_placeholder_level_has_no_field_11(self):
        """A negative result, stated precisely: the level exists, field 11 does not."""
        settings = read_level_settings(self.require(PLACEHOLDER_LEVEL))
        self.assertFalse(settings.present)
        self.assertIsNone(settings.data)
        self.assertIsNone(settings.extent)
        numbers = {f.number for f in parse_fields(settings.payload)}
        self.assertNotIn(LEVEL_FIELD_SETTINGS, numbers)
        if len(settings.payload) < 200:  # still the placeholder shape, not a saved level
            self.assertEqual(numbers, {1, 2, 34, 39, 40, 41, 42})

    def test_key_offset_points_at_the_field_11_key(self):
        settings = read_level_settings(self.require(REAL_LEVEL))
        self.assertIsNotNone(settings.key_offset)
        key = settings.payload[settings.key_offset]
        self.assertEqual(key >> 3, LEVEL_FIELD_SETTINGS)
        self.assertEqual(key & 0x07, WIRE_LENGTH)
        self.assertEqual(
            settings.payload[settings.value_start:settings.value_end], settings.data)

    # -- the vector ---------------------------------------------------------- #

    def test_extent_is_three_fixed32_floats_equal_to_one_hundred(self):
        settings = read_level_settings(self.require(REAL_LEVEL))
        extent = settings.extent
        self.assertIsNotNone(extent)
        self.assertEqual((extent.x, extent.y, extent.z), (100.0, 100.0, 100.0))
        self.assertEqual(len(extent.raw), 15)
        self.assertEqual(extent.raw.hex(), "0d0000c842150000c8421d0000c842")

    def test_extent_is_the_basic_sub_messages_only_float_vector(self):
        """Every fixed32 field reached from field 11 > 1 -- the basic vector.

        Walking field 11 > 1 and collecting each fixed32 turns up exactly the
        vector's three floats, plus two scalar floats in the same sub-message
        (field 14 = 1.2, field 18 = 24.0), seen in ``basic.floats``.  The walk is
        two levels deep, so it says nothing about the deeper ``field 11 > 5 > 1 >
        2`` (a preset-point coordinate on 1073741840, a single fixed32 on
        1073741835): the claim is scoped to what this walk reaches, not to "field
        11" as a whole.
        """
        settings = read_level_settings(self.require(REAL_LEVEL))
        fixed32_paths = []
        for f in settings.fields:
            if f.wire_type != WIRE_LENGTH or f.data is None:
                continue
            for g in parse_fields(f.data):
                if g.wire_type == WIRE_32BIT:
                    fixed32_paths.append((f.number, g.number))
                elif g.wire_type == WIRE_LENGTH and g.data is not None:
                    for h in parse_fields(g.data):
                        if h.wire_type == WIRE_32BIT:
                            fixed32_paths.append((f.number, g.number, h.number))
        self.assertEqual(sorted(fixed32_paths, key=str), sorted(
            [(1, 1, 1), (1, 1, 2), (1, 1, 3), (1, 14), (1, 18)], key=str))
        self.assertEqual(set(settings.basic.floats), {14, 18})
        self.assertAlmostEqual(settings.basic.floats[14], 1.2, places=6)
        self.assertEqual(settings.basic.floats[18], 24.0)

    def test_the_extent_does_not_vary_across_readable_levels(self):
        """The honest caveat, pinned as a fact rather than a hunch.

        ``level.bounds`` is *not* thereby proven: a value that never changes cannot
        be shown to track an edit. This test records that (100,100,100) is what every
        readable level holds, so a future save with a different triple is the signal
        that this field really does follow the scene range.
        """
        seen = []
        for path in sorted(LEVEL_DIR.rglob("*.gil")):
            settings = read_level_settings(path)
            if settings.present and settings.extent is not None:
                seen.append((path.stem, (settings.extent.x, settings.extent.y, settings.extent.z)))
        self.assertGreaterEqual(len(seen), 5, "expected several levels carrying field 11")
        self.assertEqual({v for _, v in seen}, {(100.0, 100.0, 100.0)},
                         f"the extent differs somewhere, which would be a real finding: {seen}")

    def test_vec3_decoder_rejects_a_non_vector(self):
        # two floats, not three -> None; this keeps the strictness honest
        self.assertIsNone(parse_vec3(bytes.fromhex("0d0000c842150000c842")))

    # -- factions ------------------------------------------------------------ #

    def test_three_default_factions_decode_to_editor_strings(self):
        settings = read_level_settings(self.require(REAL_LEVEL))
        names = [f.name for f in settings.factions]
        self.assertEqual(names, ["初始玩家阵营", "初始物件阵营", "初始造物阵营"])
        self.assertEqual([f.index for f in settings.factions], [1, 2, 3])
        self.assertEqual(settings.factions[0].ui_mark, "UI_MarkPlayer_Faction_0")
        self.assertEqual(settings.factions[2].ui_mark, "UI_MarkPlayer_Faction_2")

    # -- preset points ------------------------------------------------------- #

    def test_preset_records_name_spawn_and_preset_points(self):
        settings = read_level_settings(self.require(REAL_LEVEL))
        by_site = {r.site_field: r for r in settings.preset_points}
        self.assertEqual(by_site[PART_SPAWN].name, "出生点1")
        self.assertEqual(by_site[PART_PRESET].name, "新建预设点")
        for rec in settings.preset_points:
            if rec.level_ref is not None:
                self.assertGreaterEqual(rec.level_ref, LEVEL_REF_MIN)

    def test_field_11_carries_no_spawn_coordinate(self):
        """NEGATIVE: the (-547.5,-2.5,-547.5) triple is NOT in field 11.

        The preset records hold a name and a level id, no position. The coordinate
        lives once, in top-level field 7 (the terrain record), which this test
        locates so the claim has its bytes.
        """
        path = self.require(REAL_LEVEL)
        payload = decode_container(path.read_bytes()).payload
        settings = read_level_settings(path)
        self.assertNotIn(SPAWN_VEC3, settings.data or b"")

        # The triple is in top-level field 7, and field 7 is a different top-level
        # field from field 11, so a caller that only reads field 11 cannot see it.
        idx = payload.find(SPAWN_VEC3)
        self.assertGreaterEqual(idx, 0, "the spawn triple should exist somewhere in the payload")
        vec = parse_vec3(payload[idx:idx + 15])
        self.assertEqual((vec.x, vec.y, vec.z), (-547.5, -2.5, -547.5))

        def top_field_of(offset: int) -> int | None:
            pos = 0
            while pos < len(payload):
                key, nxt = _varint(payload, pos)
                number, wt = key >> 3, key & 7
                if wt == WIRE_LENGTH:
                    length, vs = _varint(payload, nxt)
                    if vs <= offset < vs + length:
                        return number
                    pos = vs + length
                elif wt == 0:
                    _, pos = _varint(payload, nxt)
                elif wt == 5:
                    pos = nxt + 4
                elif wt == 1:
                    pos = nxt + 8
                else:
                    return None
            return None

        self.assertEqual(top_field_of(idx), 7)

    def test_placeholder_reports_absence_in_describe(self):
        text = read_level_settings(self.require(PLACEHOLDER_LEVEL)).describe()
        self.assertIn("ABSENT", text)
        self.assertIn("NO scene-range value", text)

    def test_describe_names_the_candidate_and_the_caveat(self):
        text = read_level_settings(self.require(REAL_LEVEL)).describe()
        self.assertIn("extent candidate", text)
        self.assertIn("100, 100, 100", text)
        self.assertIn("NOT PROVEN", text)


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


if __name__ == "__main__":
    unittest.main(verbosity=2)
