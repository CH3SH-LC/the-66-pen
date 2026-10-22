"""Tests for the in-memory field-15 primitive (tools/beyond-save/field15_edit.py).

The load-bearing claims, each checked here:

  * the module is **in-memory only** -- no write-capable call in its source (AST
    check), editing never mutates the input bytes, and no file is written;
  * **byte-exactness is the bar**: a real level re-serialised with no change is
    byte-identical, and after an append or a payload replace **every other record**
    is byte-identical -- compared per-record sha256, not by total length;
  * **replace is in place**: unlike the measured ``remove`` + ``add`` composition
    route (which re-appends at the TAIL and moves the record), this keeps the
    record's index -- a contrast the tests assert directly;
  * the **duplicate guard** is ``template_edit``'s, reused verbatim; a mutation test
    shows an *unguarded* append really does produce a duplicate, so the guard -- not
    some incidental property -- is what refuses.  The guard reads each entry's id by
    SCANNING for field 1 (``template_edit.entry_id``), not by its first field, so a
    crafted body that does not LEAD with field 1 is still refused.

Two fixtures are exercised. A **synthetic** level (deterministic, always runs) is
the shape the real store has -- a name block and a kind-48 settings block whose
payload carries the three empty ``f5/f6/f7`` submessages -- so the replace path is
covered even with no save on disk. The **real** fixtures live under
``.runtime/beyond-save/fixtures/`` -- which is **gitignored** (``.gitignore`` line
``/.runtime/``; no ``.gil`` is tracked anywhere in this repo), so on a clean
checkout those tests SKIP and the synthetic tests are what run. Nothing here writes
a save: the real-file tests read a repo copy, never the live ``LocalLow`` path.

Run:
    python -m pytest tools/beyond-save/test_field15_edit.py
    python      tools/beyond-save/test_field15_edit.py
"""
from __future__ import annotations

import ast
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import field15_edit as fe            # noqa: E402
import gil_container as gc           # noqa: E402
import template_edit as te           # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / ".runtime" / "beyond-save" / "fixtures"
SHOP_FIXTURE = FIXTURE_DIR / "1073741842" / "1073741842.gil"   # 8 records, has the shop
FIVE_FIXTURE = FIXTURE_DIR / "1073741825.gil"                  # 2 records
HAVE_SHOP = SHOP_FIXTURE.exists()
HAVE_FIVE = FIVE_FIXTURE.exists()

# Real ids and the real measured settings payload (see field15_edit.py docstring).
SHOP_ID = 1136656385                 # type 15 商店模板
BAG_ID = te.DONOR_TYPE_11_ID         # 1119879169, type 11 背包模板
ENV_ID = 1186988033                  # type 27 环境配置
NEW_ID = 1124073471                  # top of the type-11 range; no fixture holds it
DUP_MSG = "template id {} already present -- refusing to duplicate"

#: The settings block's payload from the real 54 B shop record: a wrapper
#: ``{1: {f1=f4=1, f5={}, f6={}, f7={}, f10=f11=1}}`` -- three empty submessages.
SETTINGS_PAYLOAD = bytes.fromhex("0a0e080120012a0032003a0050015801")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def synthetic_level() -> bytes:
    """A tiny but well-formed level whose store mirrors the real record shapes."""
    entries = [
        te.build_entry(BAG_ID, kind=12, name="背包模板"),
        te.build_entry(SHOP_ID, kind=17, name="自定义模板",
                       blocks=(te.build_block(48, SETTINGS_PAYLOAD),)),
        te.build_entry(ENV_ID, kind=26, name="环境配置"),
    ]
    table = gc.encode_fields([gc.Field(1, gc.WIRE_LENGTH, data=e) for e in entries])
    payload = gc.encode_fields([
        gc.Field(2, gc.WIRE_LENGTH, data=b"synthetic"),
        gc.Field(15, gc.WIRE_LENGTH, data=table),
        gc.Field(39, gc.WIRE_VARINT, value=100000001),
    ])
    return gc.encode_container(gc.Container(subtype=gc.SUBTYPE_LEVEL, payload=payload))


def shop_payload_with_goods(payload: bytes) -> bytes:
    """Fill the settings block's empty ``f5`` with one 5-byte 'goods' row (+3 B).

    Mirrors ``.runtime/scratch/shop_inplace_demo.py``: ``f5{}`` -> ``f5{f1=12345}``,
    so the record grows 54 -> 57 B, exactly the prior measured composition demo.
    """
    outer = gc.parse_fields(payload)                 # [ {1: <inner>} ]
    inner = gc.parse_fields(outer[0].data)           # f1, f4, f5, f6, f7, f10, f11
    goods = gc.encode_fields([gc.Field(1, gc.WIRE_VARINT, value=12345)])
    rebuilt = [
        gc.Field(f.number, gc.WIRE_LENGTH, data=goods)
        if (f.number == 5 and (f.data or b"") == b"") else f
        for f in inner
    ]
    return gc.encode_fields([gc.Field(1, gc.WIRE_LENGTH, data=gc.encode_fields(rebuilt))])


def unguarded_append(blob: bytes, entry: bytes) -> bytes:
    """Append a record WITHOUT the duplicate check -- the mutation for the guard test.

    This is the exact table surgery :func:`append_record` performs, minus the guard,
    so it can materialise the duplicate the guard exists to stop.
    """
    c = gc.decode_container(blob)
    root = gc.parse_fields(c.payload)
    ti = next(i for i, f in enumerate(root) if f.number == fe.FIELD15)
    new_table = (root[ti].data or b"") + gc.encode_fields(
        [gc.Field(1, gc.WIRE_LENGTH, data=entry)])
    root[ti] = gc.Field(fe.FIELD15, gc.WIRE_LENGTH, data=new_table)
    return gc.encode_container(gc.Container(
        subtype=c.subtype, payload=gc.encode_fields(root),
        version=c.version, magic=c.magic, trailer=c.trailer))


# --------------------------------------------------------------------------- #
# the module is read-only -- proven by AST, not by promise
# --------------------------------------------------------------------------- #

class TestModuleNeverWrites(unittest.TestCase):
    def test_source_has_no_write_call(self) -> None:
        tree = ast.parse(Path(fe.__file__).read_text(encoding="utf-8"))
        banned = {"write_bytes", "write_text", "open", "writelines",
                  "write", "unlink", "remove", "rename", "replace"}
        offenders = [
            getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        ]
        self.assertEqual([o for o in offenders if o in banned], [],
                         "field15_edit.py calls a write-capable name")

    def test_error_type_is_template_edit_error(self) -> None:
        self.assertIs(fe.Field15Error, te.TemplateEditError)


# --------------------------------------------------------------------------- #
# synthetic round-trip -- always runs
# --------------------------------------------------------------------------- #

class TestSyntheticRoundTrip(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = synthetic_level()
        self.sha = hashlib.sha256(self.blob).hexdigest()

    def test_no_change_reserialise_is_byte_exact(self) -> None:
        self.assertEqual(fe.reserialise_level(self.blob), self.blob)
        self.assertEqual(fe.reserialise_field15(self.blob), fe.field15_value(self.blob))

    def test_read_back_sees_the_fixture_records(self) -> None:
        got = fe.read_records(self.blob)
        self.assertEqual([(r.index, r.record_id, r.f2) for r in got],
                         [(0, BAG_ID, 12), (1, SHOP_ID, 17), (2, ENV_ID, 26)])

    def test_editing_never_mutates_the_input(self) -> None:
        fe.append_record(self.blob, NEW_ID, 12, name="x")
        fe.replace_record_payload(self.blob, SHOP_ID, SETTINGS_PAYLOAD, block_index=-1)
        self.assertEqual(hashlib.sha256(self.blob).hexdigest(), self.sha)

    # --- append ----------------------------------------------------------- #

    def test_append_grows_by_exactly_one_record(self) -> None:
        edit = fe.append_record(self.blob, NEW_ID, f2=12, name="新背包")
        self.assertEqual(edit.operation, "append")
        self.assertEqual((edit.record_count_before, edit.record_count_after), (3, 4))
        self.assertEqual(edit.index, 3)                  # appended at the tail
        got = fe.read_records(edit.blob)
        self.assertEqual([r.record_id for r in got], [BAG_ID, SHOP_ID, ENV_ID, NEW_ID])
        new = got[3]
        self.assertEqual(new.f2, 12)
        self.assertEqual(te.read_templates(edit.blob)[3].name, "新背包")

    def test_append_leaves_every_other_record_byte_identical(self) -> None:
        before = fe.record_digests(self.blob)
        after = fe.record_digests(fe.append_record(self.blob, NEW_ID, f2=12).blob)
        for rid in (BAG_ID, SHOP_ID, ENV_ID):
            self.assertEqual(before[rid], after[rid], f"record {rid} changed on append")

    def test_append_matches_template_edit_verbatim(self) -> None:
        ours = fe.append_record(self.blob, NEW_ID, f2=12, name="新背包").blob
        theirs = te.add_template(
            self.blob, NEW_ID, entry=te.build_entry(NEW_ID, kind=12, name="新背包")).blob
        self.assertEqual(ours, theirs)

    def test_duplicate_id_is_refused_with_the_established_message(self) -> None:
        with self.assertRaises(fe.Field15Error) as ctx:
            fe.append_record(self.blob, BAG_ID, f2=12)
        self.assertEqual(str(ctx.exception), DUP_MSG.format(BAG_ID))

    def test_body_id_must_match_the_requested_id(self) -> None:
        wrong = te.build_entry(BAG_ID, kind=12, name="x")   # id != NEW_ID
        with self.assertRaises(fe.Field15Error):
            fe.append_record(self.blob, NEW_ID, entry=wrong)

    def test_append_rejects_a_non_positive_id(self) -> None:
        with self.assertRaises(fe.Field15Error):
            fe.append_record(self.blob, 0)

    # --- replace ---------------------------------------------------------- #

    def test_replace_grows_the_record_and_keeps_the_index(self) -> None:
        before = fe.record_digests(self.blob)
        grow = shop_payload_with_goods(SETTINGS_PAYLOAD)   # +3 B
        edit = fe.replace_record_payload(self.blob, SHOP_ID, grow, block_index=-1)
        self.assertEqual(edit.operation, "replace-payload")
        self.assertEqual(edit.old_payload_bytes, SETTINGS_PAYLOAD)
        self.assertEqual(edit.new_payload_bytes, grow)
        self.assertEqual(edit.record_delta, 3)            # 54 -> 57 on the real file
        self.assertEqual(edit.byte_delta, 3)              # the whole file grows by 3
        # in place: index preserved, count unchanged, every OTHER record identical
        self.assertEqual(edit.index, 1)
        self.assertEqual(edit.record_count_after, 3)
        after = fe.record_digests(edit.blob)
        self.assertNotEqual(before[SHOP_ID], after[SHOP_ID])       # the shop itself changed
        self.assertEqual(before[BAG_ID], after[BAG_ID])
        self.assertEqual(before[ENV_ID], after[ENV_ID])

    def test_replace_with_identical_payload_is_byte_exact(self) -> None:
        edit = fe.replace_record_payload(self.blob, SHOP_ID, SETTINGS_PAYLOAD, block_index=-1)
        self.assertEqual(edit.blob, self.blob)            # zero perturbation
        self.assertEqual(edit.byte_delta, 0)

    def test_replace_default_block_is_the_payload_block(self) -> None:
        # block 0 is the name block; block -1 / 1 is the kind-48 settings block.
        e1 = fe.replace_record_payload(self.blob, SHOP_ID, shop_payload_with_goods(SETTINGS_PAYLOAD))
        e2 = fe.replace_record_payload(self.blob, SHOP_ID, shop_payload_with_goods(SETTINGS_PAYLOAD),
                                       block_index=1)
        self.assertEqual(e1.blob, e2.blob)
        # and targeting block 0 (the name block) is a different, well-formed edit
        e3 = fe.replace_record_payload(self.blob, SHOP_ID, SETTINGS_PAYLOAD, block_index=0)
        self.assertNotEqual(e3.blob, self.blob)

    def test_replace_refuses_a_mismatched_payload_field(self) -> None:
        with self.assertRaises(fe.Field15Error):
            fe.replace_record_payload(self.blob, SHOP_ID, b"x", block_index=-1, payload_field=99)

    def test_replace_refuses_an_out_of_range_block(self) -> None:
        with self.assertRaises(fe.Field15Error):
            fe.replace_record_payload(self.blob, SHOP_ID, b"x", block_index=9)

    def test_replace_refuses_an_absent_record(self) -> None:
        with self.assertRaises(fe.Field15Error):
            fe.replace_record_payload(self.blob, 999999999, b"x")

    # --- the contrast that motivates the primitive ------------------------ #

    def test_composition_moves_the_record_but_the_primitive_does_not(self) -> None:
        grow = shop_payload_with_goods(SETTINGS_PAYLOAD)
        # the measured composition route: remove + add re-appends at the TAIL
        new_body = te.clone_entry(
            next(t for t in te.read_templates(self.blob) if t.template_id == SHOP_ID).entry_bytes)
        moved = te.add_template(te.remove_template(self.blob, SHOP_ID), SHOP_ID,
                                entry=new_body).blob
        self.assertEqual(fe.record_index(moved, SHOP_ID), 2)      # 1 -> 2 (moved)
        # the primitive edits in place
        edited = fe.replace_record_payload(self.blob, SHOP_ID, grow, block_index=-1).blob
        self.assertEqual(fe.record_index(edited, SHOP_ID), 1)     # unchanged


# --------------------------------------------------------------------------- #
# mutation test: the duplicate guard is load-bearing
# --------------------------------------------------------------------------- #

class TestDuplicateGuardIsLoadBearing(unittest.TestCase):
    def test_unguarded_append_really_produces_a_duplicate(self) -> None:
        blob = synthetic_level()
        dup = unguarded_append(blob, te.build_entry(BAG_ID, kind=12, name="副本"))
        ids = [r.record_id for r in fe.read_records(dup)]
        self.assertEqual(ids.count(BAG_ID), 2)                    # the defect the guard stops
        # the guarded API refuses the same append, with the established message
        with self.assertRaises(fe.Field15Error) as ctx:
            fe.append_record(blob, BAG_ID, f2=12, name="副本")
        self.assertEqual(str(ctx.exception), DUP_MSG.format(BAG_ID))


def level_with_a_non_leading_id_record() -> bytes:
    """A level whose store holds a record whose BODY does not LEAD with field 1.

    The id (field 1) is present but SECOND, after field 2 -- exactly the shape a
    positional ``parse_fields(body)[0]`` id-read misses while a scan for field 1
    finds.  Every real entry leads with field 1, so this shape is crafted; the
    guard must not depend on that accident.
    """
    crafted = gc.encode_fields([
        gc.Field(fe.ENTRY_KIND_FIELD, gc.WIRE_VARINT, value=17),   # field 2 FIRST
        gc.Field(fe.ENTRY_ID_FIELD, gc.WIRE_VARINT, value=SHOP_ID),  # the id SECOND
        te.build_name_block("自定义模板"),
    ])
    table = gc.encode_fields([
        gc.Field(1, gc.WIRE_LENGTH, data=te.build_entry(BAG_ID, kind=12, name="背包模板")),
        gc.Field(1, gc.WIRE_LENGTH, data=crafted),
    ])
    payload = gc.encode_fields([
        gc.Field(2, gc.WIRE_LENGTH, data=b"synthetic"),
        gc.Field(15, gc.WIRE_LENGTH, data=table),
    ])
    return gc.encode_container(gc.Container(subtype=gc.SUBTYPE_LEVEL, payload=payload))


class TestDuplicateGuardScansForFieldOne(unittest.TestCase):
    """The duplicate guard must read each entry's id by SCANNING for field 1, never
    by its first parsed field.  A protobuf body may order its fields freely, so a
    record that does not LEAD with field 1 must still be seen -- otherwise append
    silently yields two records with the same id (the HOLE 2 blind spot)."""

    def test_the_fixture_body_does_not_lead_with_field_one(self) -> None:
        # the whole point of the fixture: the id is NOT the first parsed field,
        # yet the intrinsic reader still returns it.
        wrappers = gc.parse_fields(fe.field15_value(level_with_a_non_leading_id_record()))
        crafted = gc.parse_fields(wrappers[1].data)
        self.assertNotEqual(crafted[0].number, fe.ENTRY_ID_FIELD)
        self.assertEqual(te.entry_id(crafted), SHOP_ID)

    def test_a_non_leading_field_one_duplicate_is_refused(self) -> None:
        blob = level_with_a_non_leading_id_record()
        self.assertEqual([r.record_id for r in fe.read_records(blob)], [BAG_ID, SHOP_ID])
        with self.assertRaises(fe.Field15Error) as ctx:
            fe.append_record(blob, SHOP_ID, f2=17)
        self.assertEqual(str(ctx.exception), DUP_MSG.format(SHOP_ID))

    def test_the_guard_sees_the_id_the_positional_read_would_have_missed(self) -> None:
        """Negative control: the retired positional read returns the WRONG id for
        this body, so the refusal above is the scan's doing, not an accident."""
        wrappers = gc.parse_fields(fe.field15_value(level_with_a_non_leading_id_record()))
        crafted = gc.parse_fields(wrappers[1].data)
        # the OLD rule -- ``parse_fields(body)[0]`` -- reads field 2, not the id
        self.assertEqual(crafted[0].number, fe.ENTRY_KIND_FIELD)
        self.assertNotEqual(crafted[0].value, SHOP_ID)


# --------------------------------------------------------------------------- #
# real fixtures -- gitignored, so these SKIP on a clean checkout
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_SHOP,
    "gitignored .runtime fixture absent: no .gil is tracked in this repo "
    "(.gitignore has /.runtime/), so on a clean checkout only the synthetic "
    "tests run -- the shop fixture is a repo COPY at "
    ".runtime/beyond-save/fixtures/1073741842/1073741842.gil")
class TestRealShopFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = SHOP_FIXTURE.read_bytes()
        self.sha = hashlib.sha256(self.blob).hexdigest()

    def test_layout_is_as_documented(self) -> None:
        got = fe.read_records(self.blob)
        self.assertEqual(len(got), 8)
        shop = got[fe.record_index(self.blob, SHOP_ID)]
        self.assertEqual((shop.record_id, shop.f2, shop.byte_len), (SHOP_ID, 17, 54))
        self.assertEqual(te.id_type(SHOP_ID), 15)                 # 商店模板 band

    def test_no_change_reserialise_is_byte_exact(self) -> None:
        self.assertEqual(fe.reserialise_level(self.blob), self.blob)
        self.assertEqual(fe.reserialise_field15(self.blob), fe.field15_value(self.blob))

    def test_append_leaves_every_other_record_byte_identical(self) -> None:
        before = fe.record_digests(self.blob)
        edit = fe.append_record(self.blob, NEW_ID, f2=11, name="MW_背包")
        after = fe.record_digests(edit.blob)
        self.assertEqual(set(after) - set(before), {NEW_ID})
        for rid in before:
            self.assertEqual(before[rid], after[rid], f"record {rid} changed on append")
        self.assertEqual(len(edit.blob), len(self.blob) + edit.byte_delta)

    def test_replace_shop_payload_in_place(self) -> None:
        before = fe.record_digests(self.blob)
        grow = shop_payload_with_goods(SETTINGS_PAYLOAD)
        edit = fe.replace_record_payload(self.blob, SHOP_ID, grow, block_index=-1)
        self.assertEqual(edit.record_delta, 3)                    # 54 -> 57 B
        self.assertEqual(edit.byte_delta, 3)                      # file +3 B (matches demo)
        self.assertEqual(edit.index, 4)                           # in place, was index 4
        after = fe.record_digests(edit.blob)
        self.assertEqual(len(after), 8)
        for rid in before:
            if rid == SHOP_ID:
                self.assertNotEqual(before[rid], after[rid])
            else:
                self.assertEqual(before[rid], after[rid], f"record {rid} changed on replace")

    def test_duplicate_id_is_refused_on_a_real_file(self) -> None:
        with self.assertRaises(fe.Field15Error) as ctx:
            fe.append_record(self.blob, SHOP_ID, f2=17)
        self.assertEqual(str(ctx.exception), DUP_MSG.format(SHOP_ID))

    def test_source_file_is_untouched(self) -> None:
        fe.append_record(SHOP_FIXTURE.read_bytes(), NEW_ID, f2=11)
        self.assertEqual(hashlib.sha256(SHOP_FIXTURE.read_bytes()).hexdigest(), self.sha)


@unittest.skipUnless(HAVE_FIVE,
    "gitignored .runtime fixture absent (see TestRealShopFixture: /.runtime/ is "
    "gitignored and no .gil is tracked); synthetic tests cover the same paths")
class TestRealPlainFixture(unittest.TestCase):
    def test_two_records_round_trip_and_append(self) -> None:
        blob = FIVE_FIXTURE.read_bytes()
        self.assertEqual(fe.reserialise_level(blob), blob)
        self.assertEqual([r.record_id for r in fe.read_records(blob)], [BAG_ID, ENV_ID])
        before = fe.record_digests(blob)
        after = fe.record_digests(fe.append_record(blob, NEW_ID, f2=11).blob)
        self.assertEqual(before[BAG_ID], after[BAG_ID])
        self.assertEqual(before[ENV_ID], after[ENV_ID])


if __name__ == "__main__":
    unittest.main(verbosity=2)
