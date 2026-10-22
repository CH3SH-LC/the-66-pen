"""Tests for the in-memory component editor (tools/beyond-save/component_edit.py).

The load-bearing claims, each checked here:

  * the edit is **in-memory** -- the module has no write call at all (AST check),
    and editing leaves the source file's sha256 untouched;
  * the edit **round-trips** -- the produced bytes re-decode, the target entity
    gains exactly one wrapper, and *every other byte* is carried through;
  * the **delta is exact** -- a group-6 wrapper with an empty payload grows the
    file by exactly 7 bytes (and the record body by the same 7);
  * the length prefixes the edit must recompute (record body, root field 5, the
    container's inner length and total length) all move together.

Both a synthetic fixture (deterministic, always runs) and the real repo snapshot
of level 1073741842 -- which carries our own entity 1077936129 -- are exercised.
Nothing here writes a save: the real-file tests read a *committed snapshot* copy,
never the live ``LocalLow`` path.

Run:
    python -m pytest tools/beyond-save/test_component_edit.py
    python      tools/beyond-save/test_component_edit.py
"""
from __future__ import annotations

import ast
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import component_edit as ce          # noqa: E402
import entity_geometry as eg         # noqa: E402
import gil_container as gc           # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

#: A committed copy of the live 1073741842 save (28383 B, 12 entities including
#: our own 1077936129).  A snapshot, so the tests never touch the live path.
SNAPSHOT_842 = (ROOT / ".runtime" / "game-executor" / "scene-cli"
                / "20261010-004106-save-640895e1" / "after-1073741842.gil")
HAVE_SNAPSHOT = SNAPSHOT_842.exists()

OUR_ENTITY = 1077936129


# --------------------------------------------------------------------------- #
# synthetic fixture -- a tiny but well-formed level with an entity table
# --------------------------------------------------------------------------- #

def _wrapper(kind: int, payload_field: int, payload: bytes) -> bytes:
    return gc.encode_fields([
        gc.Field(1, gc.WIRE_VARINT, value=kind),
        gc.Field(payload_field, gc.WIRE_LENGTH, data=payload),
    ])


def _record(entity_id: int, template_id: int, wrappers: list[tuple[int, int, bytes]]) -> bytes:
    fields = [
        gc.Field(1, gc.WIRE_VARINT, value=entity_id),
        gc.Field(2, gc.WIRE_LENGTH, data=gc.encode_fields([
            gc.Field(1, gc.WIRE_VARINT, value=template_id),
            gc.Field(2, gc.WIRE_VARINT, value=1),
        ])),
    ]
    for group, kind, payload in wrappers:
        fields.append(gc.Field(group, gc.WIRE_LENGTH, data=_wrapper(kind, kind + 10, payload)))
    fields.append(gc.Field(8, gc.WIRE_VARINT, value=template_id))
    return gc.encode_fields(fields)


def synthetic_level() -> bytes:
    """Two entities; the first carries one transform wrapper, the second none."""
    ent_a = _record(OUR_ENTITY, 20001965, [(6, 1, b"\x0a\x00")])
    ent_b = _record(1086324737, 1000000, [])
    table = gc.encode_fields([
        gc.Field(1, gc.WIRE_LENGTH, data=ent_a),
        gc.Field(1, gc.WIRE_LENGTH, data=ent_b),
    ])
    payload = gc.encode_fields([
        gc.Field(2, gc.WIRE_LENGTH, data=b"synthetic"),
        gc.Field(5, gc.WIRE_LENGTH, data=table),
        gc.Field(39, gc.WIRE_VARINT, value=100000001),
    ])
    return gc.encode_container(gc.Container(subtype=gc.SUBTYPE_LEVEL, payload=payload))


# --------------------------------------------------------------------------- #
# the module is read-only -- proven by AST, not by promise
# --------------------------------------------------------------------------- #

class TestModuleNeverWrites(unittest.TestCase):
    def test_source_has_no_write_call(self) -> None:
        tree = ast.parse((Path(ce.__file__)).read_text(encoding="utf-8"))
        banned_names = {"write_bytes", "write_text", "open", "writelines",
                        "write", "unlink", "remove", "rename", "replace"}
        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "attr", None) or getattr(func, "id", None)
                if name in banned_names:
                    offenders.append(name)
        self.assertEqual(offenders, [], f"component_edit.py calls write-capable names: {offenders}")


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

    def test_entity_starts_with_exactly_one_wrapper(self) -> None:
        before = ce.read_components(self.blob, OUR_ENTITY)
        self.assertEqual([(g, k) for g, k, _ in before], [(6, 1)])

    def test_add_collision_wrapper(self) -> None:
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=b"")
        # exact delta
        self.assertEqual(edit.byte_delta, 7)
        self.assertEqual(edit.record_delta, 7)
        self.assertEqual(len(edit.blob), len(self.blob) + 7)
        # the wrapper bytes are exactly {1:8, 18:""} and the on-record copy is {6: <that>}
        self.assertEqual(edit.wrapper_bytes.hex(), "0808920100")
        self.assertEqual(edit.appended_bytes.hex(), "32050808920100")
        # re-decode: the component is present, nothing else changed
        after = ce.read_components(edit.blob, OUR_ENTITY)
        self.assertEqual(len(after), 2)
        self.assertIn((6, 8, b"\x08\x08\x92\x01\x00"), after)

    def test_add_with_a_payload_mirrors_a_real_collision_wrapper(self) -> None:
        # the real entity's (6,8) wrapper is `08089201050801a81f01`: {1:8, 18:{1:1,501:1}}
        payload = gc.encode_fields([gc.Field(1, gc.WIRE_VARINT, value=1),
                                    gc.Field(501, gc.WIRE_VARINT, value=1)])
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=payload)
        self.assertEqual(edit.wrapper_bytes.hex(), "08089201050801a81f01")
        self.assertEqual(edit.byte_delta, 12)   # 2 (kind) + 2 key + 1 len + 5 data, wrapped: key+len+10

    def test_every_other_byte_is_carried_through(self) -> None:
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=b"")
        before_top = gc.parse_fields(gc.decode_container(self.blob).payload)
        after_top = gc.parse_fields(gc.decode_container(edit.blob).payload)
        self.assertEqual([f.number for f in before_top], [f.number for f in after_top])
        # every top-level field except 5 (the entity table) is byte-identical
        for b, a in zip(before_top, after_top):
            if b.number == ce.ENTITY_TABLE_FIELD:
                continue
            self.assertEqual(gc.encode_fields([b]), gc.encode_fields([a]))

    def test_the_other_entity_record_is_untouched(self) -> None:
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=b"")
        a = eg.read_entity_records_blob(self.blob)
        b = eg.read_entity_records_blob(edit.blob)
        self.assertEqual(len(a), len(b))
        other_a = next(r for r in a if r.entity_id == 1086324737).raw_bytes
        other_b = next(r for r in b if r.entity_id == 1086324737).raw_bytes
        self.assertEqual(other_a, other_b)

    def test_new_wrapper_is_exactly_removable(self) -> None:
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=b"")
        old = next(r for r in eg.read_entity_records_blob(self.blob) if r.entity_id == OUR_ENTITY)
        new = next(r for r in eg.read_entity_records_blob(edit.blob) if r.entity_id == OUR_ENTITY)
        idx = new.raw_bytes.index(edit.appended_bytes)
        # removability: excising the added field leaves the original record exactly
        self.assertEqual(new.raw_bytes[:idx] + new.raw_bytes[idx + len(edit.appended_bytes):],
                         old.raw_bytes)
        # and it was inserted *before* the trailing field-8 tag, keeping canonical order
        self.assertEqual(new.raw_bytes[idx + len(edit.appended_bytes):][0], 0x40)


class TestDeltaTable(unittest.TestCase):
    """The delta is a function of the wrapper, and here is its formula."""

    def test_group6_empty_payload_delta_is_exactly_encodable(self) -> None:
        blob = synthetic_level()
        for kind in (5, 8, 12, 25):
            with self.subTest(kind=kind):
                edit = ce.add_component(blob, OUR_ENTITY, kind=kind, payload=b"")
                # the delta is fully determined by the wrapper's length varints:
                #   appended = group key (1) + len(wrapper) varint + wrapper
                expected = 1 + len(gc.write_varint(len(edit.wrapper_bytes))) + len(edit.wrapper_bytes)
                self.assertEqual(edit.byte_delta, expected)
                self.assertEqual(len(edit.blob), len(blob) + expected)
        # two concrete values named in the report: 5->6 B (key 1 byte), 8->7 B (key 2 bytes)
        self.assertEqual(ce.add_component(blob, OUR_ENTITY, kind=5).byte_delta, 6)
        self.assertEqual(ce.add_component(blob, OUR_ENTITY, kind=8).byte_delta, 7)

    def test_group5_needs_explicit_payload_field(self) -> None:
        with self.assertRaises(ce.ComponentEditError):
            ce.payload_field_for(5, 1)
        self.assertEqual(ce.payload_field_for(6, 11), 21)


# --------------------------------------------------------------------------- #
# real snapshot -- the entity this project actually owns
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAVE_SNAPSHOT, "no committed 1073741842 snapshot in this checkout")
class TestRealSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = SNAPSHOT_842.read_bytes()
        self.sha_before = hashlib.sha256(self.blob).hexdigest()

    def test_snapshot_layout_is_as_documented(self) -> None:
        records = eg.read_entity_records(SNAPSHOT_842)
        our = next(r for r in records if r.entity_id == OUR_ENTITY)
        self.assertEqual(our.tag, 20001965)          # entry field 8 == template id
        self.assertEqual(our.ref, {1: 20001965, 2: 1})
        self.assertEqual(len(our.components), 31)    # the documented 31 wrappers
        self.assertEqual(len(our.raw_bytes), 564)    # the documented body length

    def test_group6_kind_plus_ten_rule_holds_on_every_wrapper(self) -> None:
        records = eg.read_entity_records(SNAPSHOT_842)
        for rec in records:
            for c in rec.components:
                if c.group != 6 or c.kind is None:
                    continue
                with self.subTest(entity=rec.entity_id, kind=c.kind):
                    self.assertEqual(c.payload_field, c.kind + 10)

    def test_add_component_to_our_entity_round_trips(self) -> None:
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=b"")
        self.assertEqual(edit.record_len_before, 564)
        self.assertEqual(edit.record_len_after, 571)
        self.assertEqual(edit.byte_delta, 7)
        self.assertEqual(len(edit.blob), len(self.blob) + 7)

        comps = ce.read_components(edit.blob, OUR_ENTITY)
        self.assertEqual(len(comps), 32)
        self.assertIn((6, 8, b"\x08\x08\x92\x01\x00"), comps)
        edited = eg.read_entity_records_blob(edit.blob)
        our = next(r for r in edited if r.entity_id == OUR_ENTITY)
        self.assertEqual(len(our.components), 32)
        self.assertEqual(len(our.raw_bytes), 571)

    def test_all_other_entities_are_byte_identical(self) -> None:
        edit = ce.add_component(self.blob, OUR_ENTITY, kind=ce.KIND_COLLISION, payload=b"")
        before = {r.entity_id: r.raw_bytes for r in eg.read_entity_records(SNAPSHOT_842)}
        after = {r.entity_id: r.raw_bytes for r in eg.read_entity_records_blob(edit.blob)}
        self.assertEqual(set(before), set(after))
        for eid, raw in before.items():
            if eid == OUR_ENTITY:
                continue
            self.assertEqual(after[eid], raw)

    def test_source_file_is_untouched(self) -> None:
        before = hashlib.sha256(SNAPSHOT_842.read_bytes()).hexdigest()
        ce.add_component(SNAPSHOT_842.read_bytes(), OUR_ENTITY, kind=ce.KIND_COLLISION)
        self.assertEqual(hashlib.sha256(SNAPSHOT_842.read_bytes()).hexdigest(), before)
        self.assertEqual(before, self.sha_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
