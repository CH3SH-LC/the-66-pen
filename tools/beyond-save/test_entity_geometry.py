"""Tests for the entity-geometry reader (tools/beyond-save/entity_geometry.py).

Two real level files are read from the live game directory and never written to:

  1073741842/1073741842.gil   12 entity records, the level with geometry
  1073741826.gil              79-byte placeholder, no entity table at all

(The task pointed at ``1073741826/1073741826.gil``; there is no such directory --
``1073741826`` is a flat 79-byte file next to the level directories. See the
module doc's negative results.)

The load-bearing tests are the byte-identity ones: decoding and re-encoding the
container and the protobuf payload must reproduce the file exactly, and reading
records must leave the file's sha256 unchanged. That is what "read-only" means
here -- not a promise, a checked invariant.

Run either:
    python -m pytest tools/beyond-save/test_entity_geometry.py
    python      tools/beyond-save/test_entity_geometry.py
"""
from __future__ import annotations

import hashlib
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entity_geometry as eg          # noqa: E402
import gil_container as gc            # noqa: E402

GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
UID_DIR = GAME_DATA / "100000001"
LEVEL_DIR = UID_DIR / "Beyond_Local_Save_Level"
PROFILE_SRC = UID_DIR / "Beyond_Local_Save_Player.gip"

LEVEL_842 = LEVEL_DIR / "1073741842" / "1073741842.gil"
LEVEL_826 = LEVEL_DIR / "1073741826.gil"
LEVEL_841 = LEVEL_DIR / "1073741841" / "1073741841.gil"

HAVE_SAVE = LEVEL_842.exists() and LEVEL_826.exists()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: The entity-table SHAPE recorded when this reader was written (2026-10-10):
#: level 842 carried 12 records.  That count is a property of the LIVE save -- the
#: user creating or deleting one entity changes it -- so the tests that pin the
#: exact count / first ids / universal set SKIP (named reason) once the level has
#: moved on.  The structural tests (offsets land on their bytes, every record is
#: well-formed, the kind->payload map is a function) run regardless of the count.
RECORDED_RECORD_COUNT_842 = 12
RECORDED_RECORD_COUNT_841 = 479


def _shape_state(records, expected: int = RECORDED_RECORD_COUNT_842) -> tuple[bool, str]:
    """True iff a live level still has the record count this test pins."""
    if len(records) != expected:
        return False, (f"live level now has {len(records)} entity records, not the "
                       f"recorded {expected} -- the level moved on; exact-shape pins "
                       "skipped")
    return True, ""


@unittest.skipUnless(HAVE_SAVE, "no live Miliastra save on this machine")
class TestByteIdentity(unittest.TestCase):
    """Re-serialising untouched bytes must be byte-identical -- the read-only proof."""

    def test_container_roundtrip_is_byte_identical(self) -> None:
        for path in (LEVEL_842, LEVEL_826):
            with self.subTest(path=path.name):
                blob = path.read_bytes()
                self.assertEqual(gc.encode_container(gc.decode_container(blob)), blob)

    def test_payload_field_roundtrip_is_byte_identical(self) -> None:
        for path in (LEVEL_842, LEVEL_826):
            with self.subTest(path=path.name):
                payload = gc.decode_container(path.read_bytes()).payload
                self.assertEqual(gc.encode_fields(gc.parse_fields(payload)), payload)

    def test_offset_walker_agrees_with_container_parser(self) -> None:
        payload = gc.decode_container(LEVEL_842.read_bytes()).payload
        walked = [r.field for r in eg.walk_fields(payload, eg.CONTAINER_HEADER)]
        self.assertEqual(walked, gc.parse_fields(payload))
        self.assertEqual(gc.encode_fields(walked), payload)

    def test_reading_records_leaves_the_file_untouched(self) -> None:
        for path in (LEVEL_842, LEVEL_826):
            with self.subTest(path=path.name):
                before = _sha256(path)
                eg.read_entity_records(path)
                self.assertEqual(_sha256(path), before)


@unittest.skipUnless(HAVE_SAVE, "no live Miliastra save on this machine")
class TestOffsets(unittest.TestCase):
    """Reported byte offsets must land on the bytes they claim."""

    def test_root_entity_table_key_byte(self) -> None:
        blob = LEVEL_842.read_bytes()
        ref = eg.walk_fields(gc.decode_container(blob).payload, eg.CONTAINER_HEADER)
        table = next(r for r in ref if r.number == eg.ENTITY_TABLE_FIELD)
        # field 5, wire type 2 -> key byte 0x2A.  The absolute byte offset is a
        # property of the LIVE file (it drifts as the game appends records), so it
        # is deliberately NOT pinned -- the key-byte check above is the real one.
        self.assertEqual(blob[table.key_offset], 0x2A)

    def test_every_record_offset_reconstructs_its_bytes(self) -> None:
        blob = LEVEL_842.read_bytes()
        records = eg.read_entity_records(LEVEL_842)
        self.assertTrue(records)
        for rec in records:
            with self.subTest(index=rec.index):
                raw = rec.raw_bytes
                # the entry is a field-1 (wire 2) child of root field 5 -> key 0x0A
                self.assertEqual(blob[rec.key_offset], 0x0A)
                self.assertEqual(blob[rec.value_offset:rec.value_offset + len(raw)], raw)

    def test_transform_offset_points_at_its_payload(self) -> None:
        records = eg.read_entity_records(LEVEL_842)
        ok, why = _shape_state(records)   # pins which record this is (pos y = 2000)
        if not ok:
            self.skipTest(why)
        rec = records[1]                              # id 1086324737, pos y = 2000
        comp = rec.component(eg.TRANSFORM_GROUP, eg.TRANSFORM_KIND)
        self.assertIsNotNone(comp)
        blob = LEVEL_842.read_bytes()
        self.assertEqual(blob[comp.payload_offset:comp.payload_offset + comp.payload_len],
                         comp.payload.data)
        # the y float of this record's position vector: read it at the payload's
        # OWN offset (the absolute 1584/1587 were live-file literals; derive them).
        self.assertEqual(
            struct.unpack("<f", blob[comp.payload_offset + 3:
                                     comp.payload_offset + 7])[0], 2000.0)


@unittest.skipUnless(HAVE_SAVE, "no live Miliastra save on this machine")
class TestStructure842(unittest.TestCase):
    """The positional structure the module claims, checked against 12 real records."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = eg.read_entity_records(LEVEL_842)
        cls.shape_ok, cls.shape_reason = _shape_state(cls.records)

    def test_record_count_and_ids(self) -> None:
        if not self.shape_ok:
            self.skipTest(self.shape_reason)
        self.assertEqual(len(self.records), RECORDED_RECORD_COUNT_842)
        self.assertEqual(self.records[0].entity_id, 1094713345)
        self.assertEqual(self.records[1].entity_id, 1086324737)
        # every record exposes an integer id and a tag
        for rec in self.records:
            self.assertIsInstance(rec.entity_id, int)
            self.assertIsInstance(rec.tag, int)

    def test_entry_field_numbers_are_identical_for_every_record(self) -> None:
        for rec in self.records:
            with self.subTest(index=rec.index):
                self.assertEqual(
                    sorted({f.number for f in rec.fields}), [1, 2, 5, 6, 7, 8])

    def test_transform_present_and_aligned_on_every_record(self) -> None:
        for rec in self.records:
            with self.subTest(index=rec.index):
                self.assertIsNotNone(rec.transform)
                self.assertEqual(sorted(rec.transform.vector_fields), [1, 2, 3])
                self.assertIn(501, rec.transform.scalar_fields)
                self.assertEqual(rec.transform.scalar_fields[501], 0xFFFFFFFF)

    def test_transform_vector_components_are_float32(self) -> None:
        for rec in self.records:
            comp = rec.component(eg.TRANSFORM_GROUP, eg.TRANSFORM_KIND)
            for child in gc.parse_fields(comp.payload.data):
                if child.number not in eg.TRANSFORM_VECTOR_FIELDS:
                    continue
                for part in gc.parse_fields(child.data):
                    with self.subTest(index=rec.index, vec=child.number, c=part.number):
                        self.assertIn(part.number, (1, 2, 3))
                        self.assertEqual(part.wire_type, eg.WIRE_FLOAT32)

    def test_scale_vector_is_three_positive_floats(self) -> None:
        # field 3 of the transform is present on all 12 with all three components;
        # in this level it is always (1,1,1) -- the identity scale.
        for rec in self.records:
            with self.subTest(index=rec.index):
                scale = rec.transform.scale
                self.assertEqual(sorted(scale.components), [1, 2, 3])
                self.assertTrue(all(v > 0 for v in scale.components.values()))
                self.assertEqual(scale.triple(), (1.0, 1.0, 1.0))

    def test_missing_components_default_to_zero(self) -> None:
        if not self.shape_ok:                 # pins which records these are
            self.skipTest(self.shape_reason)
        # record 0 is untouched -> its position vector is entirely absent, and
        # triple() must report (0,0,0) rather than fail.
        self.assertEqual(self.records[0].transform.position.components, {})
        self.assertEqual(self.records[0].transform.position.triple(), (0.0, 0.0, 0.0))
        # record 1 carries only the second component -> the other two default to 0.
        pos = self.records[1].transform.position
        self.assertEqual(sorted(pos.components), [2])
        self.assertEqual(pos.triple(), (0.0, 2000.0, 0.0))

    def test_kind_to_payload_field_is_a_function(self) -> None:
        # each (group, kind) pair must always land in the same payload field, or
        # the "wrapper = {1: kind, <P>: payload}" reading is wrong.
        seen: dict[tuple[int, int | None], set[int | None]] = {}
        for rec in self.records:
            for comp in rec.components:
                seen.setdefault((comp.group, comp.kind), set()).add(comp.payload_field)
        for key, payloads in seen.items():
            with self.subTest(key=key):
                self.assertEqual(len(payloads), 1)

    def test_summarize_universal_set(self) -> None:
        if not self.shape_ok:                 # the count + universal set are live
            self.skipTest(self.shape_reason)
        s = eg.summarize(self.records)
        self.assertEqual(s["entities"], RECORDED_RECORD_COUNT_842)
        self.assertEqual(
            [tuple(x) for x in s["universal"]],
            [(5, 1), (5, 19), (5, 111), (6, 1), (6, 3), (7, 1), (7, 3)],
        )
        self.assertEqual(s["transform"]["present"], 12)


@unittest.skipUnless(HAVE_SAVE, "no live Miliastra save on this machine")
class TestComparison826(unittest.TestCase):
    """The 79-byte placeholder is the negative control: no entity table at all."""

    def test_placeholder_has_no_entity_table(self) -> None:
        payload = gc.decode_container(LEVEL_826.read_bytes()).payload
        numbers = [f.number for f in gc.parse_fields(payload)]
        self.assertNotIn(eg.ENTITY_TABLE_FIELD, numbers)
        self.assertEqual(sorted(numbers), [1, 2, 34, 39, 40, 41, 42])

    def test_placeholder_reads_zero_records(self) -> None:
        self.assertEqual(eg.read_entity_records(LEVEL_826), [])

    def test_placeholder_summary_is_empty(self) -> None:
        s = eg.summarize(eg.read_entity_records(LEVEL_826))
        self.assertEqual(s["entities"], 0)
        self.assertEqual(s["universal"], [])
        self.assertEqual(s["transform"]["present"], 0)


@unittest.skipUnless(LEVEL_841.exists(), "level 1073741841 not present")
class TestStructure841(unittest.TestCase):
    """A second real file with 479 records, to show the shape is not a one-off."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = eg.read_entity_records(LEVEL_841)
        cls.shape_ok, cls.shape_reason = _shape_state(
            cls.records, RECORDED_RECORD_COUNT_841)

    def test_record_count(self) -> None:
        if not self.shape_ok:
            self.skipTest(self.shape_reason)
        self.assertEqual(len(self.records), RECORDED_RECORD_COUNT_841)

    def test_every_record_carries_the_transform(self) -> None:
        for rec in self.records:
            self.assertIsNotNone(rec.transform)
            self.assertEqual(sorted(rec.transform.vector_fields), [1, 2, 3])

    def test_kind_to_payload_field_is_a_function_over_479(self) -> None:
        seen: dict[tuple[int, int | None], set[int | None]] = {}
        for rec in self.records:
            for comp in rec.components:
                seen.setdefault((comp.group, comp.kind), set()).add(comp.payload_field)
        for key, payloads in seen.items():
            with self.subTest(key=key):
                self.assertEqual(len(payloads), 1)

    def test_positions_vary_and_are_readable(self) -> None:
        if not self.shape_ok:                 # pins which record index 12 is
            self.skipTest(self.shape_reason)
        # entity 12 of this level sits at (3.0, 2.7, 0) -- a non-round triple that
        # only a working float decode produces (2.7 is a float32, so it is
        # 2.700000047683716 exactly).
        rec = self.records[12]
        x, y, z = rec.transform.position.triple()
        self.assertEqual((x, z), (3.0, 0.0))
        self.assertAlmostEqual(y, 2.7, places=6)
        self.assertEqual(rec.transform.scale.components[2], 0.4000000059604645)


@unittest.skipUnless(PROFILE_SRC.exists(), "no live player profile on this machine")
class TestNegativeResults(unittest.TestCase):
    def test_profile_container_is_rejected(self) -> None:
        with self.assertRaises(eg.EntityGeometryError):
            eg.read_entity_records(PROFILE_SRC)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            eg.read_entity_records(LEVEL_DIR / "does-not-exist.gil")


if __name__ == "__main__":
    unittest.main(verbosity=2)
