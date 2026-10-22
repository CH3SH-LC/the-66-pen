"""Tests for the in-memory template editor (tools/beyond-save/template_edit.py).

The load-bearing claims, each checked here:

  * the module is **in-memory only** -- no write-capable call in its source (AST
    check), and editing leaves the source file's sha256 untouched;
  * field 15 really is a typed template registry -- a synthetic fixture proves the
    ladder (id -> type -> name), and the committed real snapshot proves the
    ``(id, type, name)`` census on a record the engine itself wrote;
  * the edit **round-trips** -- the produced bytes re-decode, the table gains
    exactly one record, and *every other byte* is carried through: excising the
    added record and re-encoding reproduces the pre-edit blob byte-for-byte;
  * the **delta is exact** -- a minimal ``{1: id}`` record grows the file by a
    computable number of bytes (8 B for a 5-byte id), all of it inside field 15.

Both a synthetic fixture (deterministic, always runs) and a committed repo
snapshot of level 1073741825 -- which carries the type-11 背包模板 record -- are
exercised. Nothing here writes a save: the real-file test reads a *repo* copy,
never the live ``LocalLow`` path.

Run:
    python -m pytest tools/beyond-save/test_template_edit.py
    python      tools/beyond-save/test_template_edit.py
"""
from __future__ import annotations

import ast
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gil_container as gc          # noqa: E402
import template_edit as te          # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

#: A committed copy of level 1073741825 (65071 B) -- carries root field 15 with
#: two records: the type-11 背包模板 and the type-27 环境配置. A repo snapshot, so
#: the tests never touch the live LocalLow path.
SNAPSHOT_825 = ROOT / ".runtime" / "beyond-save" / "fixtures" / "1073741825.gil"
HAVE_SNAPSHOT = SNAPSHOT_825.exists()

BAG_ID = te.DONOR_TYPE_11_ID          # 1119879169, type 11 道具背包 = 背包模板
BAG_NAME = "背包模板"


# --------------------------------------------------------------------------- #
# synthetic fixture -- a tiny but well-formed level with a template table
# --------------------------------------------------------------------------- #

def synthetic_level() -> bytes:
    entry = te.build_entry(BAG_ID, kind=12, name=BAG_NAME)
    table = gc.encode_fields([gc.Field(1, gc.WIRE_LENGTH, data=entry)])
    payload = gc.encode_fields([
        gc.Field(2, gc.WIRE_LENGTH, data=b"synthetic"),
        gc.Field(15, gc.WIRE_LENGTH, data=table),
        gc.Field(39, gc.WIRE_VARINT, value=100000001),
    ])
    return gc.encode_container(gc.Container(subtype=gc.SUBTYPE_LEVEL, payload=payload))


NEW_ID = 1124073471                   # top of the type-11 range (1119879168..1124073471)


# --------------------------------------------------------------------------- #
# the module is read-only -- proven by AST, not by promise
# --------------------------------------------------------------------------- #

class TestModuleNeverWrites(unittest.TestCase):
    def test_source_has_no_write_call(self) -> None:
        tree = ast.parse(Path(te.__file__).read_text(encoding="utf-8"))
        banned = {"write_bytes", "write_text", "open", "writelines",
                  "write", "unlink", "remove", "rename", "replace"}
        offenders = [
            getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        ]
        self.assertEqual([o for o in offenders if o in banned], [],
                         "template_edit.py calls a write-capable name")


# --------------------------------------------------------------------------- #
# the derived structure: id -> type -> name
# --------------------------------------------------------------------------- #

class TestDerivedStructure(unittest.TestCase):
    def test_id_type_census_values(self) -> None:
        # the typed-id ladder: (id >> 22) - 256 recovers the asset type. Which
        # types exist is a property of the save files, not a frozen set here.
        self.assertEqual(te.id_type(BAG_ID), 11)          # 背包模板
        self.assertEqual(te.id_type(1186988033), 27)      # 环境配置
        self.assertEqual(te.id_type(1090519041), 4)       # 自定义职业
        self.assertEqual(te.id_type(1094713345), 5)       # 自定义成长曲线
        self.assertEqual(te.id_type(1124073471), 11)      # top of the bag range

    def test_payload_field_census_is_not_a_formula(self) -> None:
        self.assertEqual(te.payload_field_for(1), 11)     # == kind + 10 here only
        self.assertEqual(te.payload_field_for(8), 16)     # kind + 8, not +10
        self.assertEqual(te.payload_field_for(42), 55)    # kind + 13
        self.assertEqual(te.payload_field_for(70), 75)
        with self.assertRaises(te.TemplateEditError):
            te.payload_field_for(3)                       # never seen -> refuse to guess

    def test_build_entry_has_the_real_shape(self) -> None:
        body = te.build_entry(BAG_ID, kind=12, name=BAG_NAME)
        # byte-for-byte identical to the real 46 B donor minus its second block
        self.assertTrue(body.startswith(bytes.fromhex("088180809604100c221208015a0e0a0c")))
        fields = gc.parse_fields(body)
        self.assertEqual([f.number for f in fields], [1, 2, 4])
        entry = next(f for f in fields if f.number == 4)
        kids = gc.parse_fields(entry.data)
        self.assertEqual([f.number for f in kids], [1, 11])
        self.assertEqual(kids[0].value, te.NAME_BLOCK_KIND)

    def test_minimal_entry_is_just_the_id(self) -> None:
        body = te.minimal_entry_bytes(BAG_ID)
        self.assertEqual(body.hex(), "08" + gc.write_varint(BAG_ID).hex())
        self.assertEqual(len(body), 6)                    # 1 key + 5-byte varint
        with self.assertRaises(te.TemplateEditError):
            te.minimal_entry_bytes(0)


# --------------------------------------------------------------------------- #
# synthetic round-trip
# --------------------------------------------------------------------------- #

class TestSyntheticRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = synthetic_level()

    def test_input_round_trips_byte_for_byte(self) -> None:
        c = gc.decode_container(self.blob)
        self.assertEqual(gc.encode_container(c), self.blob)
        self.assertEqual(gc.encode_fields(gc.parse_fields(c.payload)), c.payload)

    def test_read_back_sees_the_fixture_record(self) -> None:
        got = te.read_templates(self.blob)
        self.assertEqual([(t.template_id, t.id_type, t.kind, t.name) for t in got],
                         [(BAG_ID, 11, 12, BAG_NAME)])

    def test_add_minimal_record_delta_is_exact(self) -> None:
        edit = te.add_template(self.blob, NEW_ID)
        # {1: 5-byte id} = 6 B body; appended as field 1 -> key(1)+len(1)+6 = 8 B
        self.assertEqual(edit.entry_bytes.hex(), "08" + gc.write_varint(NEW_ID).hex())
        self.assertEqual(edit.added_bytes.hex(), "0a" + "06" + "08" + gc.write_varint(NEW_ID).hex())
        self.assertEqual(edit.byte_delta, 8)
        self.assertEqual(edit.table_delta, 8)
        self.assertEqual(len(edit.blob), len(self.blob) + 8)
        self.assertEqual((edit.entry_count_before, edit.entry_count_after), (1, 2))

    def test_round_trips_and_only_field_15_changes(self) -> None:
        edit = te.add_template(self.blob, NEW_ID)
        before = gc.parse_fields(gc.decode_container(self.blob).payload)
        after = gc.parse_fields(gc.decode_container(edit.blob).payload)
        self.assertEqual([f.number for f in before], [f.number for f in after])  # no new root field
        for b, a in zip(before, after):
            if b.number == te.TEMPLATE_TABLE_FIELD:
                continue
            self.assertEqual(gc.encode_fields([b]), gc.encode_fields([a]))

    def test_new_record_appears_and_old_one_survives(self) -> None:
        edit = te.add_template(self.blob, NEW_ID)
        got = te.read_templates(edit.blob)
        self.assertEqual([t.template_id for t in got], [BAG_ID, NEW_ID])
        self.assertIsNone(got[1].name)                    # minimal record carries no name

    def test_every_other_byte_is_carried_through(self) -> None:
        # excision is the strong form: remove the added record, re-encode, == original
        edit = te.add_template(self.blob, NEW_ID)
        self.assertEqual(te.remove_template(edit.blob, NEW_ID), self.blob)

    def test_canonical_record_round_trips_with_name(self) -> None:
        body = te.build_entry(1124073471, kind=12, name="MW_测试背包")
        edit = te.add_template(self.blob, 1124073471, entry=body)
        got = te.read_templates(edit.blob)[1]
        self.assertEqual((got.template_id, got.id_type, got.name), (1124073471, 11, "MW_测试背包"))
        self.assertEqual([t.template_id for t in te.read_templates(self.blob)], [BAG_ID])
        self.assertEqual(te.remove_template(edit.blob, 1124073471), self.blob)

    def test_duplicate_id_is_refused(self) -> None:
        with self.assertRaises(te.TemplateEditError):
            te.add_template(self.blob, BAG_ID)

    def test_body_id_must_match(self) -> None:
        wrong = te.build_entry(BAG_ID, kind=12, name="x")
        with self.assertRaises(te.TemplateEditError):
            te.add_template(self.blob, NEW_ID, entry=wrong)

    def test_source_bytes_are_untouched(self) -> None:
        before = hashlib.sha256(self.blob).hexdigest()
        te.add_template(self.blob, NEW_ID)
        self.assertEqual(hashlib.sha256(self.blob).hexdigest(), before)


# --------------------------------------------------------------------------- #
# real snapshot -- a record the engine itself wrote
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_SNAPSHOT, "no committed 1073741825 fixture in this checkout")
class TestRealSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = SNAPSHOT_825.read_bytes()
        self.sha_before = hashlib.sha256(self.blob).hexdigest()

    def test_snapshot_layout_is_as_documented(self) -> None:
        got = te.read_templates(self.blob)
        self.assertEqual(len(got), 2)
        bag = next(t for t in got if t.template_id == BAG_ID)
        self.assertEqual(bag.id_type, 11)
        self.assertEqual(bag.kind, 12)
        self.assertEqual(bag.name, BAG_NAME)
        self.assertEqual(len(bag.entry_bytes), 46)        # the documented 46 B donor
        self.assertEqual(bag.entry_bytes.hex(), te.DONOR_TYPE_11_ENTRY_HEX)
        self.assertEqual(bag.component_kinds, (1, 42))

    def test_add_minimal_record_round_trips(self) -> None:
        edit = te.add_template(self.blob, NEW_ID)
        self.assertEqual(edit.byte_delta, 8)
        self.assertEqual(len(edit.blob), len(self.blob) + 8)
        got = te.read_templates(edit.blob)
        self.assertEqual([t.template_id for t in got], [BAG_ID, 1186988033, NEW_ID])

    def test_only_field_15_changes_and_excision_reproduces_the_file(self) -> None:
        edit = te.add_template(self.blob, NEW_ID)
        before = gc.parse_fields(gc.decode_container(self.blob).payload)
        after = gc.parse_fields(gc.decode_container(edit.blob).payload)
        for b, a in zip(before, after):
            if b.number == te.TEMPLATE_TABLE_FIELD:
                continue
            self.assertEqual(gc.encode_fields([b]), gc.encode_fields([a]))
        self.assertEqual(te.remove_template(edit.blob, NEW_ID), self.blob)

    def test_clone_a_real_record_and_re_id_it(self) -> None:
        # the PLAUSIBLE route: copy the engine's own bytes, change only the id
        donor = next(t for t in te.read_templates(self.blob) if t.template_id == BAG_ID)
        clone = te.clone_entry(donor.entry_bytes, template_id=1124073471, name="MW_背包副本")
        edit = te.add_template(self.blob, 1124073471, entry=clone)
        got = next(t for t in te.read_templates(edit.blob) if t.template_id == 1124073471)
        self.assertEqual(got.id_type, 11)
        self.assertEqual(got.name, "MW_背包副本")
        self.assertEqual(got.component_kinds, (1, 42))    # every non-name byte preserved
        self.assertEqual(te.remove_template(edit.blob, 1124073471), self.blob)

    def test_source_file_is_untouched(self) -> None:
        before = hashlib.sha256(SNAPSHOT_825.read_bytes()).hexdigest()
        te.add_template(SNAPSHOT_825.read_bytes(), NEW_ID)
        self.assertEqual(hashlib.sha256(SNAPSHOT_825.read_bytes()).hexdigest(), before)
        self.assertEqual(before, self.sha_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
