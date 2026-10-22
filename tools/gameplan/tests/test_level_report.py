"""Tests for ``tools/gameplan/level_report.py`` -- the whole-save health table.

The behaviour is defined by SYNTHETIC bytes, so it passes on a machine with no
save; a separate block exercises the real save tree when one is present (read-only,
and skipped otherwise).

The task names four things, in order:

(a) a synthetic tree carrying BOTH on-disk layouts -- a flat ``<id>.gil`` and a
    ``<id>/<id>.gil`` directory -- is reported with each row's layout;
(b) a level with 400 terrain cells reports ``terrainCellCount == 400``;
(c) a damaged level / level directory reports its defect AND the report still
    renders and serialises (a bad file never crashes the report);
(d) the report is deterministic -- two runs over one tree produce identical text.

Two more lines ``levels.py``'s own suite holds, kept here too because this module
is a second reader of the same files: the module never opens anything for write
(a source scan and a runtime spy on the real ``open``).

Run::

    python -B tools/gameplan/tests/test_level_report.py
"""
from __future__ import annotations

import builtins
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BEYOND_SAVE = _REPO_ROOT / "tools" / "beyond-save"
for _path in (str(_REPO_ROOT), str(_BEYOND_SAVE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools.gameplan import level_report as LR  # noqa: E402
from tools.gameplan import levels as L  # noqa: E402

import gil_container as G  # noqa: E402
import terrain as T  # noqa: E402
from gil_container import (  # noqa: E402
    SUBTYPE_LEVEL,
    WIRE_LENGTH,
    WIRE_VARINT,
    Container,
    Field,
    encode_container,
    encode_fields,
)

LEVEL_REPORT_SOURCE = _REPO_ROOT / "tools" / "gameplan" / "level_report.py"

# Where the live save would be, discovered the same way the module discovers it.
GAME_LOCAL = Path.home() / "AppData" / "LocalLow" / "miHoYo"
LIVE_ACCOUNTS = L.find_account_dirs(GAME_LOCAL)


# --------------------------------------------------------------------------- #
# synthetic save-tree builders (bytes only -- no game, no bridge)
# --------------------------------------------------------------------------- #

def _entry(entry_id: int | None = None, name: str = "页签") -> Field:
    """One root-6 entry (a tab).  ``entry_id=None`` reproduces the dropped-field-1 damage."""
    parts: list[Field] = []
    if entry_id is not None:
        parts.append(Field(1, WIRE_VARINT, value=entry_id))
    parts.append(Field(2, WIRE_LENGTH, data=encode_fields([
        Field(1, WIRE_LENGTH, data=b"root"),
        Field(3, WIRE_VARINT, value=0),
    ])))
    parts.append(Field(3, WIRE_LENGTH, data=encode_fields([
        Field(1, WIRE_LENGTH, data=name.encode("utf-8")),
        Field(3, WIRE_VARINT, value=2),
    ])))
    return Field(1, WIRE_LENGTH, data=encode_fields(parts))


def _directory_section(entries: list[Field]) -> Field:
    return Field(6, WIRE_LENGTH, data=encode_fields(entries))


def _level_bytes(level_id: int, name: str | None = "存档", *, field1: bool = True,
                 entries: list[Field] | None = None,
                 terrain_cells: dict[tuple[int, int], int] | None = None,
                 named: bool = True) -> bytes:
    """Container bytes for one synthetic level.

    ``named=False`` omits field 2 (the name) entirely -- a container whose payload
    is not a level at all, which must surface as ``level-parse-failed``.
    """
    fields: list[Field] = []
    if field1:
        fields.append(Field(1, WIRE_VARINT, value=level_id))
    if named:
        fields.append(Field(2, WIRE_LENGTH, data=(name or "").encode("utf-8")))
    if entries is not None:
        fields.append(_directory_section(entries))
    if terrain_cells is not None:
        T.add_terrain(fields, terrain_id=1073741825, name="地形01",
                      transform=(-547.5, -2.5, -547.5), cells=dict(terrain_cells))
    return encode_container(Container(subtype=SUBTYPE_LEVEL, payload=encode_fields(fields)))


CLEAN_TABS = [_entry(56, "页签一"), _entry(6, "页签二")]
DAMAGED_TABS = [_entry(56, "页签一"), _entry(None, "没有id的页签")]

FLAT_WITH_TERRAIN = 1073741825     # flat, 400 terrain cells, clean directory
FLAT_PLACEHOLDER = 1073741826      # flat, no field 7, no root-6 directory
FLAT_BROKEN = 1073741829           # flat, not a container at all
FLAT_DAMAGED_DIR = 1073741830      # flat, root-6 tab with no id
FLAT_NOT_A_LEVEL = 1073741832      # flat, a container but no field 2
DIR_WITH_TERRAIN = 1073741836      # nested <id>/<id>.gil, small terrain
DIR_WITHOUT_GIL = 1073741837       # nested dir, no .gil at all
DIR_GIL_MISMATCH = 1073741838      # nested dir holding the wrong <id>.gil

SMALL_TERRAIN = {(100, 100): 1, (101, 100): 2, (100, 101): 3}  # 3 cells


def _write(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


class SyntheticSaveTree:
    """A uid folder carrying both layouts plus every damage shape the report must survive."""

    def __init__(self, base: Path):
        self.uid = base / "400000001"
        self.level_dir = self.uid / L.LEVEL_DIR_NAME
        self.level_dir.mkdir(parents=True, exist_ok=True)

        # (a) flat <id>.gil, 400 terrain cells, clean root-6 -- the (b) case too
        _write(self.level_dir / f"{FLAT_WITH_TERRAIN}.gil",
               _level_bytes(FLAT_WITH_TERRAIN, "flat_存档", entries=CLEAN_TABS,
                            terrain_cells=T.default_cells()))
        # flat, no root-6, no terrain (a placeholder)
        _write(self.level_dir / f"{FLAT_PLACEHOLDER}.gil",
               _level_bytes(FLAT_PLACEHOLDER, "placeholder_存档", entries=None))
        # flat, not a container at all
        _write(self.level_dir / f"{FLAT_BROKEN}.gil",
               b"this is not a gil container, not even close")
        # flat, root-6 damaged (a tab with no field 1)
        _write(self.level_dir / f"{FLAT_DAMAGED_DIR}.gil",
               _level_bytes(FLAT_DAMAGED_DIR, "damaged_存档", entries=DAMAGED_TABS))
        # flat, a container whose payload is not a level (no field 2)
        _write(self.level_dir / f"{FLAT_NOT_A_LEVEL}.gil",
               _level_bytes(FLAT_NOT_A_LEVEL, entries=CLEAN_TABS, named=False))

        # (a) nested <id>/<id>.gil, small terrain, clean root-6
        nested = self.level_dir / str(DIR_WITH_TERRAIN)
        nested.mkdir(exist_ok=True)
        _write(nested / f"{DIR_WITH_TERRAIN}.gil",
               _level_bytes(DIR_WITH_TERRAIN, "nested_存档", entries=CLEAN_TABS,
                            terrain_cells=SMALL_TERRAIN))
        # a numeric directory with no .gil -- damage reported, not skipped
        (self.level_dir / str(DIR_WITHOUT_GIL)).mkdir(exist_ok=True)
        # a numeric directory holding a differently-named .gil
        mismatch = self.level_dir / str(DIR_GIL_MISMATCH)
        mismatch.mkdir(exist_ok=True)
        _write(mismatch / f"{FLAT_WITH_TERRAIN}.gil",
               _level_bytes(FLAT_WITH_TERRAIN, "misnamed"))

        # noise that is NOT a level and must be ignored
        backup = self.level_dir / "UpgradeBackup"
        backup.mkdir(exist_ok=True)
        _write(backup / "1073741825.gil", _level_bytes(FLAT_WITH_TERRAIN, "backup"))
        _write(self.level_dir / "notes.txt", b"not a level either")
        _write(self.level_dir / "not_a_number.gil", _level_bytes(1, "junk"))


class SyntheticTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = SyntheticSaveTree(Path(self._tmp.name))
        self.uid = self.tree.uid
        self.report = LR.build_report(self.uid)
        self.by_id = {row.level_id: row for row in self.report.levels}

    def row(self, level_id: int) -> LR.LevelRow:
        return self.by_id[level_id]

    def codes(self, level_id: int) -> set[str]:
        return set(self.row(level_id).defect_codes)


# --------------------------------------------------------------------------- #
# (a) both layouts, and the row shape
# --------------------------------------------------------------------------- #

class TestBothLayouts(SyntheticTestBase):
    def test_every_synthetic_level_is_listed_once(self):
        self.assertEqual([r.level_id for r in self.report.levels],
                         [FLAT_WITH_TERRAIN, FLAT_PLACEHOLDER, FLAT_BROKEN,
                          FLAT_DAMAGED_DIR, FLAT_NOT_A_LEVEL, DIR_WITH_TERRAIN,
                          DIR_WITHOUT_GIL, DIR_GIL_MISMATCH])

    def test_flat_layout_is_named_flat(self):
        row = self.row(FLAT_WITH_TERRAIN)
        self.assertEqual(row.layout, LR.LAYOUT_FLAT)
        self.assertEqual(Path(row.path), self.tree.level_dir / f"{FLAT_WITH_TERRAIN}.gil")
        self.assertEqual(row.name, "flat_存档")

    def test_directory_layout_is_named_dir(self):
        row = self.row(DIR_WITH_TERRAIN)
        self.assertEqual(row.layout, LR.LAYOUT_DIR)
        self.assertEqual(Path(row.path),
                         self.tree.level_dir / str(DIR_WITH_TERRAIN) / f"{DIR_WITH_TERRAIN}.gil")
        self.assertEqual(row.name, "nested_存档")

    def test_each_is_exactly_one_of_the_two_names(self):
        for row in self.report.levels:
            self.assertIn(row.layout, (LR.LAYOUT_FLAT, LR.LAYOUT_DIR), msg=row.path)

    def test_non_level_entries_are_ignored(self):
        self.assertNotIn("UpgradeBackup", " ".join(r.path for r in self.report.levels))
        self.assertEqual(self.report.level_count, 8)  # notes.txt / not_a_number.gil dropped

    def test_size_and_hash_come_through_from_levels(self):
        row = self.row(FLAT_WITH_TERRAIN)
        blob = Path(row.path).read_bytes()
        self.assertEqual(row.size_bytes, len(blob))
        self.assertEqual(row.sha256_short, L.sha256_short(blob))


# --------------------------------------------------------------------------- #
# (b) terrain cell count -- the named 400
# --------------------------------------------------------------------------- #

class TestTerrainCells(SyntheticTestBase):
    def test_a_400_cell_level_reports_400(self):
        row = self.row(FLAT_WITH_TERRAIN)
        self.assertTrue(row.has_terrain)
        self.assertEqual(row.terrain_cell_count, 400)

    def test_the_default_grid_used_by_the_fixture_really_is_400(self):
        self.assertEqual(len(T.default_cells()), 400)

    def test_a_smaller_terrain_reports_its_own_count(self):
        self.assertEqual(self.row(DIR_WITH_TERRAIN).terrain_cell_count, len(SMALL_TERRAIN))

    def test_a_level_without_terrain_reports_zero(self):
        row = self.row(FLAT_PLACEHOLDER)
        self.assertFalse(row.has_terrain)
        self.assertEqual(row.terrain_cell_count, 0)

    def test_cell_count_agrees_with_an_independent_readback(self):
        for row in self.report.levels:
            path = Path(row.path)
            if not path.is_file():
                self.assertEqual(row.terrain_cell_count, 0, msg=row.path)
                continue
            try:
                decoded = T.read_terrain_fields(path)
            except (T.TerrainError, G.ContainerError):
                self.assertEqual(row.terrain_cell_count, 0, msg=row.path)
            else:
                self.assertEqual(row.terrain_cell_count,
                                 sum(len(t.cells) for t in decoded.terrains), msg=row.path)


# --------------------------------------------------------------------------- #
# (c) damage is a row, never a crash
# --------------------------------------------------------------------------- #

class TestDamageIsARowNotACrash(SyntheticTestBase):
    def test_damaged_root6_directory_reports_missing_entry_id(self):
        self.assertIn("missing-entry-id", self.codes(FLAT_DAMAGED_DIR))
        # ... and the level is still readable: the defect does not hide the name.
        self.assertEqual(self.row(FLAT_DAMAGED_DIR).name, "damaged_存档")
        self.assertEqual(self.row(FLAT_DAMAGED_DIR).directory_entries, 2)

    def test_placeholder_without_a_directory_reports_missing_root6(self):
        self.assertIn("missing-root-6", self.codes(FLAT_PLACEHOLDER))
        # An empty-but-present directory reads as 0 entries, not None.
        self.assertEqual(self.row(FLAT_PLACEHOLDER).directory_entries, 0)

    def test_directory_without_a_gil_reports_a_defect_and_does_not_vanish(self):
        row = self.row(DIR_WITHOUT_GIL)
        self.assertIn("level-directory-without-gil", self.codes(DIR_WITHOUT_GIL))
        self.assertIsNone(row.size_bytes)
        self.assertIsNone(row.sha256_short)
        self.assertIsNone(row.name)
        self.assertIsNone(row.directory_entries)
        self.assertFalse(row.has_terrain)

    def test_directory_holding_the_wrong_gil_reports_a_mismatch(self):
        row = self.row(DIR_GIL_MISMATCH)
        self.assertIn("level-directory-gil-name-mismatch", self.codes(DIR_GIL_MISMATCH))
        self.assertIsNone(row.size_bytes)

    def test_malformed_container_reports_a_defect(self):
        row = self.row(FLAT_BROKEN)
        self.assertIn("level-not-a-container", self.codes(FLAT_BROKEN))
        self.assertIsNone(row.name)
        self.assertIsNone(row.directory_entries)
        self.assertEqual(row.size_bytes, len(b"this is not a gil container, not even close"))

    def test_container_that_is_not_a_level_reports_parse_failed(self):
        row = self.row(FLAT_NOT_A_LEVEL)
        self.assertIn("level-parse-failed", self.codes(FLAT_NOT_A_LEVEL))
        self.assertIsNone(row.name)

    def test_a_tree_full_of_bad_files_still_renders_and_serialises(self):
        # The whole point: no bad file above may stop the text or the JSON.
        text = LR.render_text(self.report)
        self.assertIsInstance(text, str)
        self.assertIn("totals:", text)
        blob = json.loads(LR.to_json(self.report))
        self.assertEqual(blob["levelCount"], self.report.level_count)

    def test_every_defect_block_is_json_ready(self):
        for row in self.report.levels:
            for defect in row.directory_defects:
                self.assertIsInstance(defect, dict)
                self.assertEqual(set(defect), {"code", "index", "detail"})

    def test_missing_tree_is_a_named_error_not_an_empty_report(self):
        with self.assertRaises(FileNotFoundError):
            LR.build_report(Path(self._tmp.name) / "no" / "such" / "account")

    def test_cli_reports_a_missing_tree_without_a_traceback(self):
        code = LR.main(["--account-dir", str(Path(self._tmp.name) / "no" / "such" / "account")])
        self.assertEqual(code, 2)


# --------------------------------------------------------------------------- #
# totals
# --------------------------------------------------------------------------- #

class TestTotals(SyntheticTestBase):
    def test_counts(self):
        report = self.report
        self.assertEqual(report.level_count, 8)
        self.assertEqual(report.levels_with_terrain, 2)
        self.assertEqual(report.total_terrain_cells, 403)
        self.assertEqual(report.levels_with_defects, 6)
        self.assertEqual(report.total_defects, 6)
        self.assertEqual(report.levels_unreadable, 2)

    def test_by_layout_partitions_the_levels(self):
        self.assertEqual(self.report.by_layout, {LR.LAYOUT_DIR: 3, LR.LAYOUT_FLAT: 5})
        self.assertEqual(sum(self.report.by_layout.values()), self.report.level_count)

    def test_total_size_sums_only_readable_levels(self):
        expected = sum(r.size_bytes for r in self.report.levels if r.size_bytes is not None)
        self.assertEqual(self.report.total_size_bytes, expected)

    def test_defect_histogram_counts_levels_per_code(self):
        histogram = self.report.defect_codes
        # Each damaged level carries exactly one distinct code, so the histogram values are 1.
        self.assertEqual(sorted(histogram.values()), [1, 1, 1, 1, 1, 1])
        self.assertEqual(sum(1 for r in self.report.levels if r.directory_defects),
                         len(histogram))

    def test_the_account_dir_may_be_the_level_directory_itself(self):
        report = LR.build_report(self.tree.level_dir)
        self.assertEqual(report.level_count, self.report.level_count)
        self.assertEqual([r.level_id for r in report.levels],
                         [r.level_id for r in self.report.levels])


# --------------------------------------------------------------------------- #
# (d) determinism
# --------------------------------------------------------------------------- #

class TestDeterminism(SyntheticTestBase):
    def test_two_runs_produce_identical_json(self):
        again = LR.build_report(self.uid)
        self.assertEqual(LR.to_json(self.report), LR.to_json(again))

    def test_two_runs_produce_identical_text(self):
        again = LR.build_report(self.uid)
        self.assertEqual(LR.render_text(self.report), LR.render_text(again))

    def test_rows_are_ordered_by_level_id(self):
        ids = [row["levelId"] for row in json.loads(LR.to_json(self.report))["levels"]]
        self.assertEqual(ids, sorted(ids))

    def test_json_round_trips_and_carries_the_named_keys(self):
        blob = json.loads(LR.to_json(self.report))
        self.assertEqual(blob["accountDir"], str(self.uid))
        required = {"levelId", "name", "layout", "sizeBytes", "hasTerrain",
                    "terrainCellCount", "directoryEntries", "directoryDefects"}
        for row in blob["levels"]:
            self.assertTrue(required.issubset(row), msg=row)

    def test_text_names_the_400_and_the_defect(self):
        text = LR.render_text(self.report)
        self.assertIn(str(FLAT_WITH_TERRAIN), text)
        self.assertIn("400", text)
        self.assertIn("missing-entry-id", text)


# --------------------------------------------------------------------------- #
# read-only -- a source scan and a runtime spy (the same line levels.py holds)
# --------------------------------------------------------------------------- #

#: Call-shaped tokens.  Written with the "(" so a bare mention in the docstring
#: (which names the writers it deliberately avoids) does not trip the scan.
FORBIDDEN_CALL_TOKENS = (
    "open(", "write_bytes(", "write_text(", ".write(", "os.open(",
    "set_cell(", "add_terrain(", "apply_terrain_fields(", "to_level_bytes(",
    "unlink(", "mkdir(", "rmdir(", "touch(", "chmod(", "truncate(",
    "shutil.copy", "shutil.move", "os.remove", "os.replace", "os.rename",
)

#: The read entry points this module is REQUIRED to go through instead.
REQUIRED_READ_TOKENS = (
    "list_levels(", "read_terrain_fields(", "read_directory(", "resolve_level_root(",
)


class TestModuleIsReadOnlyBySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = LEVEL_REPORT_SOURCE.read_text(encoding="utf-8")

    def test_no_write_call_token_appears(self):
        for token in FORBIDDEN_CALL_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, self.source,
                                 f"{LEVEL_REPORT_SOURCE} contains {token!r}; "
                                 "level_report.py must not write")

    def test_no_open_in_write_mode_literal(self):
        import re
        for match in re.finditer(r"mode\s*=\s*['\"]([^'\"]*)['\"]", self.source):
            mode = match.group(1)
            self.assertFalse(any(ch in mode for ch in "wax+"),
                             f"write-mode literal {mode!r} in {LEVEL_REPORT_SOURCE}")

    def test_it_does_go_through_the_read_entry_points(self):
        for token in REQUIRED_READ_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, self.source)


class TestModuleIsReadOnlyAtRuntime(SyntheticTestBase):
    def _run_with_spy(self):
        seen: list[tuple[str, str]] = []
        real_io_open, real_builtins_open = io.open, builtins.open

        def spy(file, mode="r", *args, **kwargs):
            seen.append((str(file), mode))
            if any(ch in mode for ch in "wax+"):
                raise AssertionError(f"write-mode open during build_report: {file!r} mode={mode!r}")
            return real_io_open(file, mode, *args, **kwargs)

        io.open = spy
        builtins.open = spy
        try:
            report = LR.build_report(self.uid)
        finally:
            io.open = real_io_open
            builtins.open = real_builtins_open
        return report, seen

    def test_open_is_only_ever_called_for_reading(self):
        report, seen = self._run_with_spy()
        self.assertTrue(report.levels)
        self.assertTrue(seen, "expected the reader to actually touch files")
        for path, mode in seen:
            self.assertIn(mode, ("r", "rb"), f"{path} opened with {mode!r}")

    def test_building_the_report_leaves_the_tree_byte_identical(self):
        gil_files = sorted(self.tree.level_dir.rglob("*.gil"))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in gil_files}
        LR.build_report(self.uid)
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in gil_files}
        self.assertEqual(before, after)


# --------------------------------------------------------------------------- #
# the real save tree, when one is present (read-only)
# --------------------------------------------------------------------------- #

@unittest.skipUnless(LIVE_ACCOUNTS, "no live Miliastra save on this machine")
class TestLiveSaveReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.account = L.default_account_dir(GAME_LOCAL)
        cls.report = LR.build_report(cls.account)

    def test_the_live_save_reports_both_layouts(self):
        self.assertIn(LR.LAYOUT_FLAT, self.report.by_layout)
        self.assertIn(LR.LAYOUT_DIR, self.report.by_layout,
                      "the live save keeps recent levels as <id>/<id>.gil directories")

    def test_the_live_report_is_deterministic(self):
        again = LR.build_report(self.account)
        self.assertEqual(LR.to_json(self.report), LR.to_json(again))

    def test_every_row_is_internally_consistent(self):
        for row in self.report.levels:
            self.assertIsInstance(row.level_id, int)
            self.assertEqual(Path(row.path).name, f"{row.level_id}.gil")
            if row.size_bytes is None:
                self.assertFalse(Path(row.path).is_file())
                continue
            self.assertEqual(row.size_bytes, Path(row.path).stat().st_size)


if __name__ == "__main__":
    unittest.main(verbosity=2)
