"""Tests for ``tools/gameplan/levels.py`` -- the read-only level inventory.

The behaviour is defined by SYNTHETIC bytes, so it passes on a machine with no
save; a separate block exercises the real save tree when one is present (read-only,
and skipped otherwise).

Four things the task names, in order:

(a) both on-disk layouts are listed -- a bare ``<id>.gil`` and a ``<id>/<id>.gil``
    directory -- because the live save uses both at once;
(b) a level carrying terrain reports ``hasTerrain`` True (and one without does not);
(c) a damaged level / level directory reports ``directoryDefects`` instead of
    raising or vanishing;
(d) the module never opens anything for write -- proved by a source scan and by a
    runtime spy on the real ``open``.

Run::

    python -B tools/gameplan/tests/test_levels.py
"""
from __future__ import annotations

import builtins
import io
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BEYOND_SAVE = _REPO_ROOT / "tools" / "beyond-save"
for _path in (str(_REPO_ROOT), str(_BEYOND_SAVE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

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

LEVELS_SOURCE = _REPO_ROOT / "tools" / "gameplan" / "levels.py"

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


def _level_bytes(level_id: int, name: str, *, field1: bool = True,
                 entries: list[Field] | None = None,
                 terrain_cells: dict[tuple[int, int], int] | None = None) -> bytes:
    fields: list[Field] = []
    if field1:
        fields.append(Field(1, WIRE_VARINT, value=level_id))
    fields.append(Field(2, WIRE_LENGTH, data=name.encode("utf-8")))
    if entries is not None:
        fields.append(_directory_section(entries))
    if terrain_cells is not None:
        T.add_terrain(fields, terrain_id=1073741825, name="地形01",
                      transform=(-547.5, -2.5, -547.5), cells=dict(terrain_cells))
    return encode_container(Container(subtype=SUBTYPE_LEVEL, payload=encode_fields(fields)))


CLEAN_TABS = [_entry(56, "页签一"), _entry(6, "页签二")]
DAMAGED_TABS = [_entry(56, "页签一"), _entry(None, "没有id的页签")]

BARE_WITH_TERRAIN = 1073741825
BARE_PLACEHOLDER = 1073741826
BARE_BROKEN = 1073741829
BARE_DAMAGED_DIRECTORY = 1073741830
NESTED_WITH_TERRAIN = 1073741836
NESTED_WITHOUT_GIL = 1073741837


def _write(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


class SyntheticSaveTree:
    """A uid folder carrying both layouts plus every damage shape this module must survive."""

    def __init__(self, base: Path):
        self.uid = base / "400000001"
        self.level_dir = self.uid / L.LEVEL_DIR_NAME
        self.level_dir.mkdir(parents=True, exist_ok=True)

        # (a) bare <id>.gil, with terrain, clean root-6
        _write(self.level_dir / f"{BARE_WITH_TERRAIN}.gil",
               _level_bytes(BARE_WITH_TERRAIN, "bare_存档", entries=CLEAN_TABS,
                            terrain_cells={(100, 100): 1, (119, 119): 4}))
        # bare, no field 6, no terrain (a placeholder)
        _write(self.level_dir / f"{BARE_PLACEHOLDER}.gil",
               _level_bytes(BARE_PLACEHOLDER, "placeholder_存档", entries=None))
        # bare, not a container at all
        _write(self.level_dir / f"{BARE_BROKEN}.gil", b"this is not a gil container, not even close")
        # bare, root-6 damaged (a tab with no field 1)
        _write(self.level_dir / f"{BARE_DAMAGED_DIRECTORY}.gil",
               _level_bytes(BARE_DAMAGED_DIRECTORY, "damaged_存档", entries=DAMAGED_TABS))

        # (a) nested <id>/<id>.gil, with terrain
        nested = self.level_dir / f"{NESTED_WITH_TERRAIN}"
        nested.mkdir(exist_ok=True)
        _write(nested / f"{NESTED_WITH_TERRAIN}.gil",
               _level_bytes(NESTED_WITH_TERRAIN, "nested_存档", entries=CLEAN_TABS,
                            terrain_cells={(101, 101): 2}))
        # a numeric directory with no .gil -- damage that must be reported, not skipped
        (self.level_dir / f"{NESTED_WITHOUT_GIL}").mkdir(exist_ok=True)

        # noise that is NOT a level and must be ignored
        backup = self.level_dir / "UpgradeBackup"
        backup.mkdir(exist_ok=True)
        _write(backup / "1073741825.gil", _level_bytes(BARE_WITH_TERRAIN, "backup"))
        _write(self.level_dir / "notes.txt", b"not a level either")
        _write(self.level_dir / "not_a_number.gil", _level_bytes(1, "junk"))


class SyntheticTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tree = SyntheticSaveTree(Path(self._tmp.name))
        self.uid = self.tree.uid
        self.rows = L.list_levels(self.uid)

    def row(self, level_id: int) -> dict:
        for row in self.rows:
            if row["levelId"] == level_id:
                return row
        raise AssertionError(f"level {level_id} not in {[r['levelId'] for r in self.rows]}")

    def codes(self, level_id: int) -> set[str]:
        return {d["code"] for d in self.row(level_id)["directoryDefects"]}


# --------------------------------------------------------------------------- #
# (a) both layouts
# --------------------------------------------------------------------------- #

class TestBothLayouts(SyntheticTestBase):
    def test_every_synthetic_level_is_listed_once(self):
        self.assertEqual([r["levelId"] for r in self.rows],
                         [BARE_WITH_TERRAIN, BARE_PLACEHOLDER, BARE_BROKEN,
                          BARE_DAMAGED_DIRECTORY, NESTED_WITH_TERRAIN, NESTED_WITHOUT_GIL])

    def test_bare_file_layout(self):
        row = self.row(BARE_WITH_TERRAIN)
        self.assertEqual(row["layout"], L.LAYOUT_BARE)
        self.assertEqual(Path(row["path"]), self.tree.level_dir / f"{BARE_WITH_TERRAIN}.gil")
        self.assertEqual(row["name"], "bare_存档")
        self.assertTrue(row["layout"] == L.LAYOUT_BARE)

    def test_nested_directory_layout(self):
        row = self.row(NESTED_WITH_TERRAIN)
        self.assertEqual(row["layout"], L.LAYOUT_NESTED)
        self.assertEqual(Path(row["path"]),
                         self.tree.level_dir / f"{NESTED_WITH_TERRAIN}" / f"{NESTED_WITH_TERRAIN}.gil")
        self.assertEqual(row["name"], "nested_存档")

    def test_account_dir_may_be_the_level_directory_itself(self):
        rows = L.list_levels(self.tree.level_dir)
        self.assertEqual([r["levelId"] for r in rows], [r["levelId"] for r in self.rows])

    def test_non_level_entries_are_ignored(self):
        self.assertNotIn("UpgradeBackup", " ".join(r["path"] for r in self.rows))
        self.assertEqual(len(self.rows), 6)  # notes.txt and not_a_number.gil dropped

    def test_level_ids_and_find_level_file(self):
        self.assertEqual(L.level_ids(self.uid),
                         [BARE_WITH_TERRAIN, BARE_PLACEHOLDER, BARE_BROKEN,
                          BARE_DAMAGED_DIRECTORY, NESTED_WITH_TERRAIN, NESTED_WITHOUT_GIL])
        self.assertEqual(L.find_level_file(self.uid, NESTED_WITH_TERRAIN),
                         self.tree.level_dir / f"{NESTED_WITH_TERRAIN}" / f"{NESTED_WITH_TERRAIN}.gil")
        self.assertEqual(L.find_level_file(self.uid, BARE_WITH_TERRAIN),
                         self.tree.level_dir / f"{BARE_WITH_TERRAIN}.gil")
        self.assertIsNone(L.find_level_file(self.uid, 999999999))

    def test_size_and_short_hash_match_the_bytes(self):
        row = self.row(BARE_WITH_TERRAIN)
        blob = Path(row["path"]).read_bytes()
        self.assertEqual(row["sizeBytes"], len(blob))
        self.assertEqual(row["sha256Short"], L.sha256_short(blob))
        self.assertEqual(len(row["sha256Short"]), L.SHA256_SHORT_HEX)
        self.assertRegex(row["sha256Short"], r"^[0-9a-f]{16}$")


# --------------------------------------------------------------------------- #
# (b) terrain
# --------------------------------------------------------------------------- #

class TestTerrainFlag(SyntheticTestBase):
    def test_level_with_terrain_reports_true(self):
        self.assertTrue(self.row(BARE_WITH_TERRAIN)["hasTerrain"])
        self.assertTrue(self.row(NESTED_WITH_TERRAIN)["hasTerrain"])

    def test_level_without_field_7_reports_false(self):
        self.assertFalse(self.row(BARE_PLACEHOLDER)["hasTerrain"])

    def test_flag_agrees_with_an_independent_readback(self):
        for row in self.rows:
            path = Path(row["path"])
            if not path.is_file():
                continue
            try:
                decoded = T.read_terrain_fields(path)
            except (T.TerrainError, G.ContainerError):
                self.assertFalse(row["hasTerrain"], msg=row["path"])
            else:
                self.assertEqual(row["hasTerrain"], len(decoded.terrains) > 0, msg=row["path"])


# --------------------------------------------------------------------------- #
# (c) damage is reported, never raised
# --------------------------------------------------------------------------- #

class TestDamageIsReported(SyntheticTestBase):
    def test_damaged_root6_directory_reports_missing_entry_id(self):
        self.assertIn("missing-entry-id", self.codes(BARE_DAMAGED_DIRECTORY))
        # ... and the level is still readable: the defect does not hide the name.
        self.assertEqual(self.row(BARE_DAMAGED_DIRECTORY)["name"], "damaged_存档")

    def test_placeholder_without_a_directory_reports_missing_root6(self):
        self.assertIn("missing-root-6", self.codes(BARE_PLACEHOLDER))

    def test_directory_without_a_gil_reports_a_defect_and_does_not_vanish(self):
        row = self.row(NESTED_WITHOUT_GIL)
        self.assertIn(L.DEFECT_DIR_WITHOUT_GIL, self.codes(NESTED_WITHOUT_GIL))
        self.assertIsNone(row["sizeBytes"])
        self.assertIsNone(row["sha256Short"])
        self.assertIsNone(row["name"])
        self.assertFalse(row["hasTerrain"])

    def test_malformed_container_reports_a_defect(self):
        row = self.row(BARE_BROKEN)
        self.assertIn(L.DEFECT_NOT_A_CONTAINER, self.codes(BARE_BROKEN))
        self.assertIsNone(row["name"])
        self.assertFalse(row["hasTerrain"])
        self.assertEqual(row["sizeBytes"], len(b"this is not a gil container, not even close"))

    def test_every_defect_block_is_well_formed(self):
        for row in self.rows:
            self.assertIsInstance(row["directoryDefects"], list)
            for defect in row["directoryDefects"]:
                self.assertEqual(set(defect), {"code", "index", "detail"})
                self.assertIsInstance(defect["code"], str)
                self.assertIsInstance(defect["detail"], str)

    def test_missing_tree_is_a_named_error_not_an_empty_list(self):
        with self.assertRaises(FileNotFoundError):
            L.list_levels(Path(self._tmp.name) / "no" / "such" / "account")

    def test_cli_reports_a_missing_tree_without_a_traceback(self):
        code = L.main(["--account-dir", str(Path(self._tmp.name) / "no" / "such" / "account")])
        self.assertEqual(code, 2)


# --------------------------------------------------------------------------- #
# (d) read-only -- a source scan and a runtime spy
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
    "read_bytes(", "decode_container(", "parse_level(",
    "check_directory(", "terrain_fields_of(",
)


class TestModuleIsReadOnlyBySource(unittest.TestCase):
    """Grep-style: the module's own source never reaches a writer."""

    @classmethod
    def setUpClass(cls):
        cls.source = LEVELS_SOURCE.read_text(encoding="utf-8")

    def test_no_write_call_token_appears(self):
        for token in FORBIDDEN_CALL_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, self.source,
                                 f"{LEVELS_SOURCE} contains {token!r}; levels.py must not write")

    def test_no_open_in_write_mode_literal(self):
        import re
        for match in re.finditer(r"mode\s*=\s*['\"]([^'\"]*)['\"]", self.source):
            mode = match.group(1)
            self.assertFalse(any(ch in mode for ch in "wax+"),
                             f"write-mode literal {mode!r} in {LEVELS_SOURCE}")

    def test_it_does_go_through_the_read_entry_points(self):
        for token in REQUIRED_READ_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, self.source)


class TestModuleIsReadOnlyAtRuntime(SyntheticTestBase):
    """Spy on the real ``open``: every underlying open must be read-only."""

    def _run_with_spy(self):
        seen: list[tuple[str, str]] = []
        real_io_open, real_builtins_open = io.open, builtins.open

        def spy(file, mode="r", *args, **kwargs):
            seen.append((str(file), mode))
            if any(ch in mode for ch in "wax+"):
                raise AssertionError(f"write-mode open during list_levels: {file!r} mode={mode!r}")
            return real_io_open(file, mode, *args, **kwargs)

        io.open = spy
        builtins.open = spy
        try:
            rows = L.list_levels(self.uid)
        finally:
            io.open = real_io_open
            builtins.open = real_builtins_open
        return rows, seen

    def test_open_is_only_ever_called_for_reading(self):
        rows, seen = self._run_with_spy()
        self.assertTrue(rows)
        self.assertTrue(seen, "expected the reader to actually touch files")
        for path, mode in seen:
            self.assertIn(mode, ("r", "rb"), f"{path} opened with {mode!r}")

    def test_listing_leaves_the_tree_byte_identical(self):
        gil_files = sorted(self.tree.level_dir.rglob("*.gil"))
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in gil_files}
        L.list_levels(self.uid)
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in gil_files}
        self.assertEqual(before, after)


# --------------------------------------------------------------------------- #
# the real save tree, when one is present (read-only)
# --------------------------------------------------------------------------- #

@unittest.skipUnless(LIVE_ACCOUNTS, "no live Miliastra save on this machine")
class TestLiveSaveInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.account = L.default_account_dir(GAME_LOCAL)
        cls.rows = L.list_levels(cls.account)

    def test_the_live_tree_lists_both_layouts(self):
        layouts = {row["layout"] for row in self.rows}
        self.assertIn(L.LAYOUT_BARE, layouts)
        self.assertIn(L.LAYOUT_NESTED, layouts,
                      "the live save keeps recent levels as <id>/<id>.gil directories")

    def test_at_least_one_real_level_carries_terrain(self):
        self.assertTrue(any(row["hasTerrain"] for row in self.rows))

    def test_every_row_is_internally_consistent(self):
        for row in self.rows:
            self.assertIsInstance(row["levelId"], int)
            self.assertEqual(Path(row["path"]).name, f"{row['levelId']}.gil")
            if row["sizeBytes"] is None:
                self.assertFalse(Path(row["path"]).is_file())
                continue
            blob = Path(row["path"]).read_bytes()
            self.assertEqual(row["sizeBytes"], len(blob))
            self.assertEqual(row["sha256Short"], L.sha256_short(blob))

    def test_hasTerrain_agrees_with_an_independent_readback(self):
        for row in self.rows:
            path = Path(row["path"])
            if not path.is_file():
                continue
            try:
                decoded = T.read_terrain_fields(path)
            except (T.TerrainError, G.ContainerError):
                self.assertFalse(row["hasTerrain"], msg=row["path"])
            else:
                self.assertEqual(row["hasTerrain"], len(decoded.terrains) > 0, msg=row["path"])

    def test_find_level_file_agrees_with_the_listing(self):
        for row in self.rows:
            if not Path(row["path"]).is_file():
                continue
            found = L.find_level_file(self.account, row["levelId"])
            self.assertEqual(str(found), row["path"])

    def test_listing_the_live_tree_writes_nothing(self):
        root = L.resolve_level_root(self.account)
        gil_files = sorted(root.rglob("*.gil"))
        before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in gil_files}
        L.list_levels(self.account)
        after = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in gil_files}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
