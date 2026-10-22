"""Tests for tools/beyond-save/level_directory.py.

Runs under both ``python -B tools/beyond-save/test_level_directory.py`` and
pytest.  Synthetic fixtures carry the load: the real files are read from the
live game directory and the frozen backups under ``.runtime``, but the tests
that *define* the behaviour build their own bytes so they pass on a machine that
has neither.

The load-bearing test is ``test_synthetic_missing_id_reproduces_the_2026_10_08_shape``:
it rebuilds exactly the damage ``docs/PROGRESS-BY-FUNCTION.md:118-126`` describes
(two extra entries appended, the last with no field 1) and asserts the checker
catches it -- because the whole point of this module is that the shape used to
be invisible.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import level_directory as ld  # noqa: E402
from gil_container import (  # noqa: E402
    Container,
    ContainerError,
    Field,
    WIRE_LENGTH,
    WIRE_VARINT,
    encode_container,
    encode_fields,
)

ROOT = Path(__file__).resolve().parents[2]

# The 40 entry ids read off the user's original 1073741842.gil (sha 88ad2acf...),
# in file order.  Frozen here as evidence, not as a rule: the checker must not
# require this particular set, only that every entry carries an id.
CLEAN_IDS = [56, 6, 18, 21, 51, 204, 62, 52, 9, 10, 11, 12, 68, 61, 17, 19, 3, 22,
             4, 15, 16, 20, 14, 13, 57, 58, 59, 60, 67, 69, 7, 29, 33, 31, 39, 32,
             40, 38, 66, 35]

USER_ORIGINAL = (ROOT / ".runtime/formal-save-backups"
                 / "20261008T0930-1073741842-user-original-before-postsave-test"
                 / "1073741842.gil")
DAMAGED_BACKUP = (ROOT / ".runtime/formal-save-backups"
                  / "20261008T221152-1073741842-before-user-original-restore"
                  / "1073741842-1073741842.gil")
LIVE_SAVE = Path("C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001"
                 "/Beyond_Local_Save_Level/1073741842/1073741842.gil")


# --------------------------------------------------------------------------- #
# synthetic fixture builders -- the observed shape, rebuilt field by field
# --------------------------------------------------------------------------- #

def entry(entry_id=None, name="未分类页签", members=(), owner="root"):
    """One root-6 entry.  ``entry_id=None`` omits field 1: the damaged shape."""
    parts = []
    if entry_id is not None:
        parts.append(Field(ld.ENTRY_FIELD_ID, WIRE_VARINT, value=entry_id))
    parts.append(Field(ld.ENTRY_FIELD_OWNER, WIRE_LENGTH, data=encode_fields([
        Field(ld.OWNER_FIELD_NAME, WIRE_LENGTH, data=owner.encode("utf-8")),
        Field(ld.OWNER_FIELD_TAG, WIRE_VARINT, value=1),
    ])))
    body = [
        Field(ld.BODY_FIELD_NAME, WIRE_LENGTH, data=name.encode("utf-8")),
        Field(ld.BODY_FIELD_TYPE, WIRE_VARINT, value=2),
    ]
    for group, member_id in members:
        body.append(Field(ld.BODY_FIELD_MEMBER, WIRE_LENGTH, data=encode_fields([
            Field(ld.MEMBER_FIELD_GROUP, WIRE_VARINT, value=group),
            Field(ld.MEMBER_FIELD_ID, WIRE_VARINT, value=member_id),
        ])))
    parts.append(Field(ld.ENTRY_FIELD_BODY, WIRE_LENGTH, data=encode_fields(body)))
    return Field(ld.ENTRY_FIELD_ID, WIRE_LENGTH, data=encode_fields(parts))


def payload(entries, level_name="自定义页签_3_存档", include_root6=True):
    fields = [Field(2, WIRE_LENGTH, data=level_name.encode("utf-8"))]
    if include_root6:
        fields.append(Field(ld.ROOT_FIELD_DIRECTORY, WIRE_LENGTH,
                            data=encode_fields(list(entries))))
    return encode_fields(fields)


def write_gil(path, blob_payload):
    path.write_bytes(encode_container(Container(subtype=2, payload=blob_payload)))
    return path


def clean_entries():
    members = {0: [(5400, 1186988033)], 16: [(200, 1094713345)]}
    return [entry(i, members=members.get(n, ())) for n, i in enumerate(CLEAN_IDS)]


class SyntheticDirectoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_40_entry_directory_reads_and_checks_clean(self):
        path = write_gil(self.tmp / "40.gil", payload(clean_entries()))
        entries = ld.read_directory(path)
        self.assertEqual(len(entries), 40)
        self.assertEqual([e.entry_id for e in entries], CLEAN_IDS)
        self.assertEqual(ld.check_directory(path), [])

    def test_synthetic_missing_id_reproduces_the_2026_10_08_shape(self):
        # 40 clean + the extra id-36 tab + a tab with no id at all == 42, one
        # of which has no field 1.  This is byte-for-byte the described damage.
        damaged = clean_entries() + [entry(36), entry(None, name="未分类页签")]
        path = write_gil(self.tmp / "42.gil", payload(damaged))
        entries = ld.read_directory(path)
        self.assertEqual(len(entries), 42)
        self.assertIsNone(entries[-1].entry_id)
        self.assertEqual(entries[-1].name, "未分类页签")
        defects = ld.check_directory(path)
        self.assertEqual([d.code for d in defects], [ld.MISSING_ENTRY_ID])
        self.assertEqual(defects[0].index, 41)

    def test_duplicate_entry_id_is_detected_on_the_later_entry(self):
        path = write_gil(self.tmp / "dup.gil", payload([entry(7), entry(7), entry(8)]))
        defects = ld.check_directory(path)
        self.assertEqual([d.code for d in defects], [ld.DUPLICATE_ENTRY_ID])
        self.assertEqual(defects[0].index, 1)
        # The reader still returns all three; a dirty id is not a parse failure.
        self.assertEqual([e.entry_id for e in ld.read_directory(path)], [7, 7, 8])

    def test_missing_root6_is_a_defect_not_a_crash(self):
        path = write_gil(self.tmp / "noroot6.gil", payload([], include_root6=False))
        self.assertEqual(ld.read_directory(path), [])
        self.assertEqual([d.code for d in ld.check_directory(path)], [ld.MISSING_ROOT_6])

    def test_non_container_bytes_raise(self):
        path = self.tmp / "junk.gil"
        path.write_bytes(b"not a beyond save at all, really")
        with self.assertRaises(ContainerError):
            ld.read_directory(path)
        with self.assertRaises(ContainerError):
            ld.check_directory(path)

    def test_unexpected_root6_child_is_a_defect(self):
        bad_child = Field(9, WIRE_VARINT, value=1)
        path = write_gil(self.tmp / "odd.gil",
                         payload([entry(1), bad_child, entry(2)]))
        defects = ld.check_directory(path)
        self.assertEqual([d.code for d in defects], [ld.UNEXPECTED_ROOT_6_FIELD])
        self.assertEqual(defects[0].index, 1)

    def test_members_are_read(self):
        path = write_gil(self.tmp / "members.gil", payload([
            entry(3, members=[(200, 1094713345), (200, 1077936129)]),
        ]))
        entries = ld.read_directory(path)
        self.assertEqual([(m.group, m.member_id) for m in entries[0].members],
                         [(200, 1094713345), (200, 1077936129)])
        self.assertEqual(entries[0].owner, "root")
        self.assertEqual(entries[0].type_code, 2)

    def test_two_ids_in_one_entry_are_ambiguous_not_missing(self):
        parts = encode_fields([
            Field(ld.ENTRY_FIELD_ID, WIRE_VARINT, value=7),
            Field(ld.ENTRY_FIELD_ID, WIRE_VARINT, value=8),
            Field(ld.ENTRY_FIELD_BODY, WIRE_LENGTH, data=encode_fields([
                Field(ld.BODY_FIELD_NAME, WIRE_LENGTH, data="未分类页签".encode("utf-8")),
                Field(ld.BODY_FIELD_TYPE, WIRE_VARINT, value=2),
            ])),
        ])
        doubled = Field(ld.ENTRY_FIELD_ID, WIRE_LENGTH, data=parts)
        path = write_gil(self.tmp / "two-ids.gil", payload([doubled]))
        defects = ld.check_directory(path)
        self.assertEqual([d.code for d in defects], [ld.DUPLICATE_ENTRY_FIELD_1])

    def test_cli_reports_zero_defects_clean_and_one_defect_damaged(self):
        clean = write_gil(self.tmp / "cli-clean.gil", payload(clean_entries()))
        damaged = write_gil(self.tmp / "cli-bad.gil",
                            payload(clean_entries() + [entry(None)]))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(ld.main([str(clean)]), 0)
        self.assertIn("40 entries, 0 defect(s)", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(ld.main([str(damaged)]), 1)
        self.assertIn("41 entries, 1 defect(s)", buf.getvalue())


class RealFileTests(unittest.TestCase):
    """Verify against the frozen backups and the live save, when present.

    These assert the *recorded* state of each file.  The live save is not
    asserted to be clean: on 2026-10-10 it carried the re-appended damage, and a
    test that pinned a live count would be a lie the moment the game saved.
    """

    def test_user_original_backup_is_40_entries_and_zero_defects(self):
        if not USER_ORIGINAL.is_file():
            self.skipTest(f"backup absent: {USER_ORIGINAL}")
        entries = ld.read_directory(USER_ORIGINAL)
        self.assertEqual(len(entries), 40)
        self.assertEqual([e.entry_id for e in entries], CLEAN_IDS)
        self.assertEqual(ld.check_directory(USER_ORIGINAL), [])
        # Concrete field evidence, so this is not merely a count.
        self.assertEqual((entries[0].entry_id, entries[0].name), (56, "默认"))
        self.assertEqual([(m.group, m.member_id) for m in entries[0].members],
                         [(5400, 1186988033)])
        self.assertEqual((entries[16].entry_id, entries[16].name), (3, "未分类页签"))
        self.assertEqual([(m.group, m.member_id) for m in entries[16].members],
                         [(200, 1094713345)])

    def test_damaged_backup_reports_the_missing_id(self):
        if not DAMAGED_BACKUP.is_file():
            self.skipTest(f"backup absent: {DAMAGED_BACKUP}")
        entries = ld.read_directory(DAMAGED_BACKUP)
        self.assertEqual(len(entries), 42)
        defects = ld.check_directory(DAMAGED_BACKUP)
        self.assertEqual([d.code for d in defects], [ld.MISSING_ENTRY_ID])
        self.assertEqual(defects[0].index, 41)

    def test_live_save_reader_and_checker_agree(self):
        if not LIVE_SAVE.is_file():
            self.skipTest(f"live save absent: {LIVE_SAVE}")
        entries = ld.read_directory(LIVE_SAVE)
        defects = ld.check_directory(LIVE_SAVE)
        missing_id = sorted(e.index for e in entries if e.entry_id is None)
        reported = sorted(d.index for d in defects if d.code == ld.MISSING_ENTRY_ID)
        self.assertEqual(missing_id, reported)
        # The directory `verify-created-save.py` needs (one kind-3 entry) is
        # still readable; this module must not be a second, divergent reader.
        kind3 = [e for e in entries if e.entry_id == 3]
        self.assertEqual(len(kind3), 1)
        self.assertTrue(kind3[0].members)


if __name__ == "__main__":
    unittest.main()
