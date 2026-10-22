"""Tests for tools/gameplan/verify_graph_on_disk.py — offline, read-only.

Two layers, on purpose:

* ``TestSyntheticPair`` builds its own ``.gil`` bytes (via the same
  ``gil_container`` codec the tool uses) and never touches a real file.  These
  tests *define* the behaviour and pass on a machine with no game installed.
* ``TestRealPair`` runs against the real before/after pair recorded in
  ``PROGRESS.md:15`` — the live ``1073741842.gil`` and the byte-exact backup
  taken before the write (21872 B) under ``.runtime``.  The **live** file is not
  a constant: the game autosaves and it legitimately grows (28383 B at demo time
  -> 28405 B the next day -> …).  So its assertions are split by SUBJECT:

  - about **our in-repo backup** (an immutable artefact) or **our decoder**
    (presence, subtype, self-consistency, negatives): asserted unconditionally;
  - the demo **artefact ids** (graphId / entityId / templateId) being PRESENT in
    the live save: asserted unconditionally — the load-bearing assertion;
  - the frozen **demo numbers** (file size, sha256, occurrence counts, per-field
    deltas): asserted only while the live file still equals the recorded
    snapshot, via :func:`requires_demo_snapshot`; once it drifts they SKIP with a
    named reason instead of failing.

  The whole class skips (with a reason) when the files are absent.

Every test treats the ``.gil`` inputs as read-only: ``TestReadOnly`` asserts the
bytes, size and mtime are identical before and after a ``verify`` call.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:  # runnable as a script, not only under pytest
    sys.path.insert(0, str(_REPO))

from tools.gameplan.verify_graph_on_disk import (  # noqa: E402
    DOES_NOT_PROVE,
    UNATTRIBUTED,
    RootFieldSize,
    gil_codec,
    main,
    verify,
)

Field = gil_codec.Field
WIRE_LENGTH = gil_codec.WIRE_LENGTH
WIRE_VARINT = gil_codec.WIRE_VARINT

# --- the real pair, as recorded in PROGRESS.md:15 -------------------------- #
REAL = Path("C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001"
            "/Beyond_Local_Save_Level/1073741842/1073741842.gil")
BACKUP = (_REPO / ".runtime/editor-bridge/backups"
          / "20261009T163136Z-pre-graph-demo-save-20261010/files"
          / "Beyond_Local_Save_Level/1073741842/1073741842.gil")
GRAPH_ID = 1073741829
ENTITY_ID = 1077936129
TEMPLATE_ID = 20001965          # 土田 -- the demo's plot tile
HAS_REAL_PAIR = REAL.is_file() and BACKUP.is_file()

#: sha256 of OUR in-repo pre-save backup -- an immutable artefact, safe to pin.
BACKUP_SHA = "88ad2acfb3a0b8e64065b92b66482178a713fa9b499507ceab7e552b757870ec"

#: The demo-SNAPSHOT numbers recorded the moment the save landed (PROGRESS.md:15).
#: They are a property of the LIVE machine, not of our decoder: the game autosaves
#: and the ``.gil`` legitimately grows (28383 B at demo time -> 28405 B on
#: 2026-10-11 -> whatever comes next).  They are therefore asserted ONLY while the
#: live file still equals the snapshot; the moment it drifts, those pins SKIP with a
#: named reason instead of failing.  Presence, subtype and self-consistency hold no
#: matter how large the file grows and are asserted unconditionally.
DEMO_SNAPSHOT_FILE_SIZE = 28383
DEMO_SNAPSHOT_PAYLOAD_SIZE = 28359
DEMO_SNAPSHOT_SHA = "56feb97d916d903789cc47028bb47028ab2f587501f978e28daabb36dc919164"


def _live_matches_demo_snapshot() -> tuple[bool, str]:
    """True iff the live save is still the byte-exact demo snapshot."""
    if not HAS_REAL_PAIR:
        return False, "real 1073741842 pair not present"
    size = REAL.stat().st_size
    if size != DEMO_SNAPSHOT_FILE_SIZE:
        return False, (f"live save is {size} B, not the recorded "
                       f"{DEMO_SNAPSHOT_FILE_SIZE} B demo snapshot -- the game "
                       "autosaved and the .gil grew; frozen-number pins skipped")
    sha = hashlib.sha256(REAL.read_bytes()).hexdigest()
    if sha != DEMO_SNAPSHOT_SHA:
        return False, ("live save sha256 differs from the recorded demo snapshot; "
                       "frozen-number pins skipped")
    return True, ""


DEMO_SNAPSHOT_OK, DEMO_SNAPSHOT_REASON = (
    (False, "real 1073741842 pair not present") if not HAS_REAL_PAIR
    else _live_matches_demo_snapshot())

#: Guard for the tests that assert the frozen demo numbers (size, sha256,
#: occurrence counts, per-field deltas).  They keep their exact bodies and run
#: whenever the live file still equals the snapshot; otherwise they skip, never
#: fail -- a live save is not a constant.
requires_demo_snapshot = unittest.skipUnless(
    DEMO_SNAPSHOT_OK,
    DEMO_SNAPSHOT_REASON or "live save drifted from the recorded demo snapshot")


# --------------------------------------------------------------------------- #
# synthetic fixtures — the observed container shape, rebuilt field by field
# --------------------------------------------------------------------------- #

def _level_blob(root_fields: list) -> bytes:
    """Wrap a synthetic level payload in a real container."""
    return gil_codec.encode_container(
        gil_codec.Container(subtype=gil_codec.SUBTYPE_LEVEL,
                            payload=gil_codec.encode_fields(root_fields)))


def _write(tmp: Path, name: str, root_fields: list) -> Path:
    path = tmp / name
    path.write_bytes(_level_blob(root_fields))
    return path


# A baseline whose root 9 lists level ids the way the real files do — and one of
# them IS the graph id, so presence alone cannot distinguish the two.
def _baseline_fields(graph_id=5000) -> list:
    return [
        Field(2, WIRE_LENGTH, data="synthetic level".encode("utf-8")),
        Field(9, WIRE_LENGTH, data=gil_codec.encode_fields([
            Field(1, WIRE_VARINT, value=graph_id),
            Field(2, WIRE_VARINT, value=42),
        ])),
    ]


def _after_fields(graph_id=5000, entity_id=7000) -> list:
    return _baseline_fields(graph_id) + [
        Field(10, WIRE_LENGTH, data=gil_codec.encode_fields([
            Field(1, WIRE_LENGTH, data=gil_codec.encode_fields([
                Field(1, WIRE_VARINT, value=graph_id),
                Field(2, WIRE_VARINT, value=entity_id),
            ])),
        ])),
    ]


class TestSyntheticPair(unittest.TestCase):
    """Behaviour-defining tests that need no real file at all."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.before = _write(self.tmp, "before.gil", _baseline_fields())
        self.after = _write(self.tmp, "after.gil", _after_fields())

    # -- the counts ---------------------------------------------------------- #

    def test_counts_and_root_field_attribution(self):
        r = verify(self.after, graph_id=5000, entity_id=7000, baseline=self.before)
        self.assertEqual(r.graph_occurrences, 2)
        self.assertEqual(dict(r.graph_occurrences_by_root_field), {9: 1, 10: 1})
        self.assertEqual(r.entity_occurrences, 1)
        self.assertEqual(dict(r.entity_occurrences_by_root_field), {10: 1})

    def test_baseline_counts_are_reported_separately(self):
        r = verify(self.after, graph_id=5000, entity_id=7000, baseline=self.before)
        self.assertEqual(r.baseline_graph_occurrences, 1)
        self.assertEqual(dict(r.baseline_graph_by_root_field), {9: 1})
        self.assertEqual(r.baseline_entity_occurrences, 0)
        self.assertEqual(dict(r.baseline_entity_by_root_field), {})

    def test_a_wrong_graph_id_finds_zero(self):
        for wrong in (5001, 12345678, 5000 * 1000):
            r = verify(self.after, graph_id=wrong, baseline=self.before)
            self.assertEqual(r.graph_occurrences, 0, f"id {wrong} should not be present")
            self.assertFalse(r.graph_found)
            self.assertEqual(dict(r.graph_occurrences_by_root_field), {})

    def test_a_wrong_entity_id_finds_zero(self):
        r = verify(self.after, graph_id=5000, entity_id=999999)
        self.assertEqual(r.entity_occurrences, 0)
        self.assertFalse(r.entity_found)

    def test_entity_id_is_optional(self):
        r = verify(self.after, graph_id=5000)
        self.assertIsNone(r.entity_occurrences)
        self.assertIsNone(r.entity_occurrences_by_root_field)
        self.assertIsNone(r.entity_found)

    # -- what changed -------------------------------------------------------- #

    def test_new_root_field_is_located(self):
        r = verify(self.after, graph_id=5000, entity_id=7000, baseline=self.before)
        numbers = [f.number for f in r.changed_root_fields]
        self.assertEqual(numbers, [10])
        field = r.changed_root_fields[0]
        self.assertEqual(field.before, 0)
        self.assertTrue(field.is_new)
        self.assertFalse(field.is_removed)
        self.assertEqual(field.after, len(gil_codec.encode_fields([_after_fields()[2]])))
        self.assertEqual(field.delta, field.after)

    def test_removed_root_field_is_located(self):
        r = verify(self.before, graph_id=5000, baseline=self.after)
        numbers = [f.number for f in r.changed_root_fields]
        self.assertEqual(numbers, [10])
        self.assertTrue(r.changed_root_fields[0].is_removed)

    def test_deltas_sum_to_the_payload_delta(self):
        r = verify(self.after, graph_id=5000, baseline=self.before)
        self.assertEqual(r.changed_root_delta_sum, r.payload_delta)
        self.assertEqual(r.payload_delta, r.payload_size - r.baseline_payload_size)
        self.assertEqual(r.size_delta, r.file_size - r.baseline_file_size)
        self.assertTrue(r.root_fields_cover_payload)

    def test_unchanged_root_fields_are_not_reported(self):
        r = verify(self.after, graph_id=5000, baseline=self.before)
        self.assertNotIn(2, [f.number for f in r.changed_root_fields])
        self.assertNotIn(9, [f.number for f in r.changed_root_fields])

    def test_identical_file_reports_no_change(self):
        r = verify(self.before, graph_id=5000, baseline=self.before)
        self.assertEqual(r.changed_root_fields, ())
        self.assertEqual(r.changed_root_delta_sum, 0)
        self.assertEqual(r.payload_delta, 0)

    # -- expected size and notes --------------------------------------------- #

    def test_expected_size_match_and_mismatch(self):
        size = self.after.stat().st_size
        ok = verify(self.after, graph_id=5000, expected_size=size)
        self.assertTrue(ok.size_matches_expected)
        self.assertFalse(any("expected_size" in n for n in ok.notes))
        bad = verify(self.after, graph_id=5000, expected_size=size + 1)
        self.assertFalse(bad.size_matches_expected)
        self.assertTrue(any("expected_size" in n for n in bad.notes))

    def test_no_baseline_says_so(self):
        r = verify(self.after, graph_id=5000)
        self.assertIsNone(r.baseline_path)
        self.assertIsNone(r.changed_root_delta_sum)
        self.assertEqual(r.changed_root_fields, ())
        self.assertTrue(any("no baseline" in n for n in r.notes))

    def test_note_separates_preexisting_from_new_root_fields(self):
        r = verify(self.after, graph_id=5000, baseline=self.before)
        joined = " | ".join(r.notes)
        self.assertIn("root field(s) [9]", joined)      # pre-existing, not evidence
        self.assertIn("[10]", joined)                   # the actual change
        self.assertIn("not evidence of a new graph", joined)

    def test_summary_states_what_is_not_proven(self):
        text = verify(self.after, graph_id=5000, baseline=self.before).summary()
        self.assertIn("does NOT prove:", text)
        for caveat in DOES_NOT_PROVE:
            self.assertIn(caveat, text)

    # -- error paths --------------------------------------------------------- #

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            verify(self.tmp / "nope.gil", graph_id=5000)

    def test_non_container_bytes_raise(self):
        junk = self.tmp / "junk.gil"
        junk.write_bytes(b"this is not a Beyond container, not even close")
        with self.assertRaises(gil_codec.ContainerError):
            verify(junk, graph_id=5000)

    def test_ha256_is_of_the_whole_file(self):
        r = verify(self.after, graph_id=5000)
        self.assertEqual(r.sha256, hashlib.sha256(self.after.read_bytes()).hexdigest())


class TestUnattributedBucket(unittest.TestCase):
    """A hit outside every root field must be bucketed as unattributed, not guessed."""

    def test_unattributed_is_field_number_zero(self):
        self.assertEqual(UNATTRIBUTED, 0)
        with tempfile.TemporaryDirectory() as tmp:
            # A payload whose root fields decode fine; the byte scan is separate.
            path = _write(Path(tmp), "a.gil", _after_fields())
            r = verify(path, graph_id=5000)
            self.assertNotIn(UNATTRIBUTED, r.graph_occurrences_by_root_field)


class TestReadOnly(unittest.TestCase):
    """verify() must never write: bytes, size and mtime are unchanged."""

    def test_synthetic_file_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "a.gil", _baseline_fields())
            stat_before = path.stat()
            blob_before = path.read_bytes()
            verify(path, graph_id=5000, entity_id=7000, baseline=path)
            stat_after = path.stat()
            self.assertEqual(blob_before, path.read_bytes())
            self.assertEqual(stat_before.st_size, stat_after.st_size)
            self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)

    @unittest.skipUnless(HAS_REAL_PAIR, "real 1073741842 pair not present")
    def test_live_save_is_untouched(self):
        before = REAL.stat()
        blob = REAL.read_bytes()
        verify(REAL, graph_id=GRAPH_ID, entity_id=ENTITY_ID, baseline=BACKUP)
        after = REAL.stat()
        self.assertEqual(blob, REAL.read_bytes())
        self.assertEqual(before.st_size, after.st_size)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)


class TestCLI(unittest.TestCase):
    def _run(self, argv) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_text_output_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "a.gil", _after_fields())
            code, out = self._run(["--gil", str(path), "--graph-id", "5000",
                                   "--entity-id", "7000"])
            self.assertEqual(code, 0)
            self.assertIn("graph_id        5000", out)
            self.assertIn("does NOT prove:", out)

    def test_json_output_is_parseable_and_carries_the_caveats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp), "a.gil", _after_fields())
            code, out = self._run(["--gil", str(path), "--graph-id", "5000",
                                   "--entity-id", "7000", "--json"])
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data["graph_occurrences"], 2)   # root 9 (pre-existing) + root 10
            self.assertEqual(data["entity_occurrences"], 1)
            self.assertEqual(data["graph_occurrences_by_root_field"],
                             [{"root_field": 9, "count": 1}, {"root_field": 10, "count": 1}])
            self.assertEqual(data["does_not_prove"], list(DOES_NOT_PROVE))

    def test_json_baseline_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = _write(Path(tmp), "before.gil", _baseline_fields())
            after = _write(Path(tmp), "after.gil", _after_fields())
            code, out = self._run(["--gil", str(after), "--graph-id", "5000",
                                   "--baseline", str(before), "--json"])
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(data["baseline_graph_occurrences"], 1)
            self.assertEqual(data["size_delta"], data["file_size"] - data["baseline_file_size"])
            self.assertEqual([f["number"] for f in data["changed_root_fields"]], [10])


class TestRootFieldSizeDataclass(unittest.TestCase):
    def test_delta_and_flags(self):
        new = RootFieldSize(number=10, wire_type=WIRE_LENGTH, before=0, after=5)
        self.assertEqual(new.delta, 5)
        self.assertTrue(new.is_new)
        self.assertFalse(new.is_removed)
        gone = RootFieldSize(number=10, wire_type=WIRE_LENGTH, before=5, after=0)
        self.assertTrue(gone.is_removed)
        same = RootFieldSize(number=1, wire_type=WIRE_VARINT, before=2, after=2)
        self.assertEqual(same.delta, 0)
        self.assertFalse(same.is_new or same.is_removed)


# --------------------------------------------------------------------------- #
# the real pair — the load-bearing assertions, tied to PROGRESS.md:15
# --------------------------------------------------------------------------- #

@unittest.skipUnless(HAS_REAL_PAIR, "real 1073741842 pair not present")
class TestRealPair(unittest.TestCase):
    """Split by subject: our backup / our decoder unconditionally; the live
    file's frozen numbers only while it still equals the recorded snapshot."""

    @classmethod
    def setUpClass(cls):
        cls.r = verify(REAL, graph_id=GRAPH_ID, entity_id=ENTITY_ID, baseline=BACKUP)

    # -- our in-repo backup: an immutable artefact, so exact numbers are honest -- #

    def test_backup_artifact_is_byte_frozen(self):
        self.assertEqual(self.r.baseline_file_size, 21872)   # the pre-save backup
        self.assertEqual(self.r.baseline_payload_size, 21848)
        self.assertEqual(verify(BACKUP, graph_id=GRAPH_ID).sha256, BACKUP_SHA)

    def test_baseline_graph_id_is_five_and_all_in_root_nine(self):
        # The trap this tool exists to expose: the id is already in the baseline.
        self.assertEqual(self.r.baseline_graph_occurrences, 5)
        self.assertEqual(dict(self.r.baseline_graph_by_root_field), {9: 5})

    def test_baseline_has_no_entity_id(self):
        self.assertEqual(self.r.baseline_entity_occurrences, 0)
        self.assertEqual(dict(self.r.baseline_entity_by_root_field), {})

    # -- the LIVE save: assert STRUCTURE, never a frozen size ------------------- #

    def test_live_save_subtype_and_growth(self):
        self.assertEqual(self.r.subtype, gil_codec.SUBTYPE_LEVEL)
        # the demo save can only have grown since the pre-save backup
        self.assertGreaterEqual(self.r.file_size, self.r.baseline_file_size)

    def test_live_report_is_self_consistent(self):
        self.assertEqual(self.r.sha256, hashlib.sha256(REAL.read_bytes()).hexdigest())
        self.assertEqual(self.r.size_delta,
                         self.r.file_size - self.r.baseline_file_size)
        self.assertEqual(self.r.payload_delta,
                         self.r.payload_size - self.r.baseline_payload_size)
        self.assertTrue(self.r.root_fields_cover_payload)

    # -- the load-bearing assertion: the demo artefact ids are PRESENT ----------- #

    def test_demo_artifacts_are_present_in_the_save(self):
        """graphId / entityId / templateId of the demo are in the LIVE save.

        This is the assertion worth keeping: it is about the SAVE carrying our
        content, and it holds no matter how large the file grows.  It is
        presence, not a count -- the graph id also appears 5x in the baseline's
        sibling list, which is exactly why only presence (not a bare count) is
        quoted as the valuable claim.
        """
        self.assertTrue(self.r.graph_found, f"graphId {GRAPH_ID} missing from the save")
        self.assertTrue(self.r.entity_found, f"entityId {ENTITY_ID} missing from the save")
        payload = gil_codec.decode_container(REAL.read_bytes()).payload
        self.assertIn(gil_codec.write_varint(TEMPLATE_ID), payload,
                      f"templateId {TEMPLATE_ID} missing from the save")

    # -- our decoder vs the live file: negatives that don't depend on its size --- #

    def test_a_wrong_graph_id_finds_zero_in_the_real_file(self):
        for wrong in (1073741824, 1073741900, TEMPLATE_ID + 1):
            r = verify(REAL, graph_id=wrong)
            self.assertEqual(r.graph_occurrences, 0, f"id {wrong} must not be found")
            self.assertFalse(r.graph_found)

    def test_entity_id_in_the_wrong_slot_finds_zero(self):
        r = verify(REAL, graph_id=GRAPH_ID, entity_id=999999999)
        self.assertEqual(r.entity_occurrences, 0)
        self.assertFalse(r.entity_found)

    def test_expected_size_comparison_uses_the_supplied_value(self):
        # Tests OUR comparison, never the machine's current size.
        live = REAL.stat().st_size
        self.assertTrue(
            verify(REAL, graph_id=GRAPH_ID, expected_size=live).size_matches_expected)
        self.assertFalse(
            verify(REAL, graph_id=GRAPH_ID, expected_size=live + 1).size_matches_expected)

    def test_summary_names_the_file_and_the_caveat(self):
        text = self.r.summary()
        self.assertIn("1073741842.gil", text)
        self.assertIn("does NOT prove:", text)

    # -- the frozen demo numbers: asserted ONLY while the live file matches ----- #

    @requires_demo_snapshot
    def test_demo_snapshot_sizes_and_sha(self):
        self.assertEqual(self.r.file_size, DEMO_SNAPSHOT_FILE_SIZE)
        self.assertEqual(self.r.payload_size, DEMO_SNAPSHOT_PAYLOAD_SIZE)
        self.assertEqual(self.r.sha256, DEMO_SNAPSHOT_SHA)

    @requires_demo_snapshot
    def test_graph_id_occurrence_count_is_eight(self):
        self.assertEqual(self.r.graph_occurrences, 8)         # PROGRESS.md:15

    @requires_demo_snapshot
    def test_graph_id_occurrences_by_root_field(self):
        self.assertEqual(dict(self.r.graph_occurrences_by_root_field),
                         {5: 1, 6: 1, 9: 5, 10: 1})

    @requires_demo_snapshot
    def test_entity_id_occurrence_count_is_two(self):
        self.assertEqual(self.r.entity_occurrences, 2)        # PROGRESS.md:15

    @requires_demo_snapshot
    def test_entity_id_occurrences_by_root_field(self):
        self.assertEqual(dict(self.r.entity_occurrences_by_root_field), {5: 1, 6: 1})

    @requires_demo_snapshot
    def test_graph_id_reaches_three_new_root_fields(self):
        fresh = set(self.r.graph_occurrences_by_root_field) - set(
            self.r.baseline_graph_by_root_field)
        self.assertEqual(fresh, {5, 6, 10})
        joined = " | ".join(self.r.notes)
        self.assertIn("[5, 6, 10]", joined)

    @requires_demo_snapshot
    def test_changed_root_fields_and_deltas(self):
        fields = {f.number: f for f in self.r.changed_root_fields}
        self.assertEqual(sorted(fields), [5, 6, 10, 46])
        self.assertEqual((fields[5].before, fields[5].after, fields[5].delta),
                         (3184, 3751, 567))
        self.assertEqual((fields[6].before, fields[6].after, fields[6].delta),
                         (1453, 1587, 134))
        self.assertEqual((fields[10].before, fields[10].after, fields[10].delta),
                         (4, 5792, 5788))
        self.assertEqual((fields[46].before, fields[46].after, fields[46].delta),
                         (25, 47, 22))
        self.assertTrue(all(f.wire_type == WIRE_LENGTH for f in fields.values()))
        self.assertFalse(any(f.is_new or f.is_removed for f in self.r.changed_root_fields))

    @requires_demo_snapshot
    def test_deltas_sum_exactly_to_the_payload_growth(self):
        self.assertEqual(self.r.changed_root_delta_sum, 6511)
        self.assertEqual(self.r.payload_delta, 6511)
        self.assertEqual(self.r.size_delta, 6511)
        self.assertTrue(self.r.root_fields_cover_payload)

    @requires_demo_snapshot
    def test_sibling_level_id_is_a_false_positive_without_a_baseline(self):
        """The caveat, made concrete: a *sibling level id* is present too.

        1073741830 is another level on this machine, listed in root 9; a bare
        presence check reports it as "found" with no graph involved.  Only the
        baseline comparison tells the two apart -- which is why the run always
        carries the DOES_NOT_PROVE block.
        """
        r = verify(REAL, graph_id=1073741830)
        self.assertEqual(r.graph_occurrences, 5)
        self.assertEqual(dict(r.graph_occurrences_by_root_field), {9: 5})
        self.assertTrue(r.graph_field_paths)                        # all inside root 9
        self.assertTrue(all(p.startswith("9.") for p in r.graph_field_paths))
        self.assertTrue(r.graph_found)  # the weak signal, on purpose
        self.assertIn("NOT proof", " | ".join(DOES_NOT_PROVE))

    @requires_demo_snapshot
    def test_structural_paths_never_overcount_the_byte_scan(self):
        # The descent only visits parsed fields, so it can under-count (one of the
        # 8 hits sits in bytes that do not parse as a message) but never invent one.
        self.assertEqual(len(self.r.graph_field_paths), 7)
        self.assertLessEqual(len(self.r.graph_field_paths), self.r.graph_occurrences)
        self.assertIn("5.1.6.13.1.1.2", self.r.graph_field_paths)
        self.assertIn("10.1.1.1.5", self.r.graph_field_paths)
        self.assertIn("6.1.3.5.2", self.r.entity_field_paths)
        self.assertEqual(self.r.entity_field_paths, ("5.1.1", "6.1.3.5.2"))

    @requires_demo_snapshot
    def test_summary_names_the_counts(self):
        text = self.r.summary()
        self.assertIn("8 varint occurrence(s)", text)
        self.assertIn("2 varint occurrence(s)", text)
        self.assertIn("+6511 B", text)


if __name__ == "__main__":
    unittest.main()
