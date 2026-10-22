"""One table a human reads to judge a save's health -- layout + terrain + directory, together.

WHY THIS EXISTS
    Three readers already answer three slices of "is this save healthy?", and each
    one sees only its own slice:

      * ``levels.list_levels`` (``tools/gameplan/levels.py:309``) -- which levels
        exist, in which of the two on-disk layouts, with size / short hash /
        ``hasTerrain`` / the root-``field 6`` directory defects.
      * ``terrain.read_terrain_fields`` (``tools/beyond-save/terrain.py:322``) --
        the ``field 7`` terrain list, cell by cell.
      * ``level_directory.read_directory``
        (``tools/beyond-save/level_directory.py:275``) -- the root-``field 6`` tab
        directory, entry by entry.

    No single command joined them, so judging a save still meant three runs and a
    human holding three outputs in their head.  This module is that join: one
    report (:func:`build_report`), one compact table (:func:`render_text`) and one
    JSON blob to diff two runs against (:func:`to_json`).

IT REUSES ``levels.py`` -- IT DOES NOT RE-WALK THE TREE
    ``tools/gameplan/levels.py`` **is** present (419 lines, read-only, and
    ``tools/gameplan/tests/test_levels.py`` holds that line).  So this module does
    **not** implement its own tree walk -- ``levels.list_levels`` is the sole
    source of the inventory (ids, names, layout, size, hash, and the defect list),
    and this module adds only the two numbers that reader does not carry:

      * ``terrainCellCount`` -- via ``terrain.read_terrain_fields``;
      * ``directoryEntries`` -- via ``level_directory.read_directory``.

    If ``levels.py`` had been absent, the honest move would have been to walk the
    tree here (bare ``<id>.gil`` and ``<id>/<id>.gil``) and say so; because it is
    present, the tree walk stays in one place.

THE TWO ON-DISK LAYOUTS, IN THE REPORT'S OWN WORDS
    ``levels`` names the shapes ``bare-file`` / ``nested-directory``.  This report
    calls them ``flat`` / ``dir`` (the vocabulary the task asks a human to read),
    mapping each row's layout through :data:`_LAYOUT_NAMES`.  An unknown layout
    string is passed through unchanged rather than dropped.

READ-ONLY, STRUCTURALLY
    Every file touch is a read: ``levels.list_levels`` reads the level bytes, and
    the two extras call ``terrain.read_terrain_fields`` (which opens the file
    read-only, ``terrain.py:322``) and ``level_directory.read_directory`` (which
    reads the bytes, ``level_directory.py:275``).  **No writer from any of the
    four modules is imported into a call path** -- in particular
    ``terrain.set_cell`` / ``add_terrain`` / ``apply_terrain_fields`` /
    ``to_level_bytes`` (``terrain.py:468-587``) and ``gil_container.write_bytes``
    (``gil_container.py:553``) are never reached.  ``tests/test_level_report.py``
    holds that line two ways: a source scan for writer tokens, and a runtime spy
    on ``open`` that fails on any non-read mode.

A DAMAGED FILE IS A ROW, NEVER AN EXCEPTION
    A level that is not a container, a level directory holding no ``.gil``, or a
    root-``field 6`` directory with a tab that lost its id all become
    ``directoryDefects`` on that level's row; the report still renders and still
    serialises.  The one thing that *does* raise is a missing save tree -- an empty
    inventory and an absent save are different answers (``levels.py:309``).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# ``levels`` / ``terrain`` / ``level_directory`` / ``gil_container`` live under
# tools/gameplan and tools/beyond-save; both directories must be importable, the
# same reach ``bounds.py:70`` and ``levels.py:79`` use.  ``levels`` inserts the
# beyond-save one itself, but doing both here keeps this module's import order
# independent of who imported whom, and lets the file run standalone
# (``python -B tools/gameplan/level_report.py``) as well as as a package module.
_GAMEPLAN_DIR = Path(__file__).resolve().parent
_BEYOND_SAVE = _GAMEPLAN_DIR.parent / "beyond-save"
for _dir in (str(_BEYOND_SAVE), str(_GAMEPLAN_DIR)):
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

try:  # as a package module: ``from tools.gameplan import level_report``
    from . import levels  # noqa: E402
except ImportError:  # pragma: no cover - run directly: ``python tools/gameplan/level_report.py``
    import levels  # type: ignore[no-redef]  # noqa: E402

import level_directory  # noqa: E402
import terrain  # noqa: E402

#: This report's two layout names, mapped from ``levels``' on-disk vocabulary.
LAYOUT_FLAT = "flat"
LAYOUT_DIR = "dir"
_LAYOUT_NAMES = {
    levels.LAYOUT_BARE: LAYOUT_FLAT,
    levels.LAYOUT_NESTED: LAYOUT_DIR,
}


# --------------------------------------------------------------------------- #
# dataclasses -- one row, one report
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LevelRow:
    """One level's health, as a plain value object.

    ``terrain_cell_count`` is the total number of distinct terrain cells across
    every terrain the level carries (0 when it carries none).  ``directory_entries``
    is the number of tabs in the root-``field 6`` directory, or ``None`` when the
    level's bytes are not a container at all (so the count is unknown, not zero).
    """

    level_id: int
    name: str | None
    layout: str
    path: str
    size_bytes: int | None
    sha256_short: str | None
    has_terrain: bool
    terrain_cell_count: int
    directory_entries: int | None
    directory_defects: tuple[dict, ...] = ()

    @property
    def defect_codes(self) -> tuple[str, ...]:
        return tuple(sorted({d.get("code", "?") for d in self.directory_defects}))

    def to_dict(self) -> dict:
        """The row as JSON-ready camelCase.  Key order is fixed, so two runs diff cleanly."""
        return {
            "levelId": self.level_id,
            "name": self.name,
            "layout": self.layout,
            "path": self.path,
            "sizeBytes": self.size_bytes,
            "sha256Short": self.sha256_short,
            "hasTerrain": self.has_terrain,
            "terrainCellCount": self.terrain_cell_count,
            "directoryEntries": self.directory_entries,
            "directoryDefects": [dict(d) for d in self.directory_defects],
        }


@dataclass(frozen=True)
class SaveHealthReport:
    """Every level in one account's save tree, plus the account totals."""

    account_dir: str
    level_root: str
    levels: tuple[LevelRow, ...]
    level_count: int
    total_size_bytes: int
    levels_with_terrain: int
    total_terrain_cells: int
    levels_with_defects: int
    total_defects: int
    levels_unreadable: int
    by_layout: dict  # {"flat": n, "dir": m}
    defect_codes: dict  # {code: how many levels show it}

    def to_dict(self) -> dict:
        return {
            "accountDir": self.account_dir,
            "levelRoot": self.level_root,
            "levelCount": self.level_count,
            "totalSizeBytes": self.total_size_bytes,
            "levelsWithTerrain": self.levels_with_terrain,
            "totalTerrainCells": self.total_terrain_cells,
            "levelsWithDefects": self.levels_with_defects,
            "totalDefects": self.total_defects,
            "levelsUnreadable": self.levels_unreadable,
            "byLayout": dict(self.by_layout),
            "defectCodes": dict(self.defect_codes),
            "levels": [row.to_dict() for row in self.levels],
        }


# --------------------------------------------------------------------------- #
# the two extras levels.py does not carry
# --------------------------------------------------------------------------- #

def _terrain_cell_count(path: Path) -> int:
    """Distinct terrain cells across all terrains in ``path``; 0 when there are none.

    A missing file, a non-container, a placeholder with no ``field 7``, or any
    decode failure all mean "no measurable terrain" and yield 0.  Broad on purpose:
    the point of this report is that a bad file becomes a numberless row, not an
    exception (see the module docstring).
    """
    if not path.is_file():
        return 0
    try:
        fields = terrain.read_terrain_fields(path)
    except Exception:  # noqa: BLE001 -- a decode failure is "no terrain here", not a crash
        return 0
    return sum(len(t.cells) for t in fields.terrains)


def _directory_entry_count(path: Path) -> int | None:
    """The count of root-``field 6`` tabs in ``path``, or ``None`` when unreadable.

    ``None`` (not 0) distinguishes "these bytes are not a container, so there is no
    directory to count" from "a container whose directory is empty".  Broad on
    purpose, as above.
    """
    if not path.is_file():
        return None
    try:
        return len(level_directory.read_directory(path))
    except Exception:  # noqa: BLE001 -- not-a-container is a missing count, not a crash
        return None


def _row_from_levels_row(row: dict) -> LevelRow:
    """Lift one ``levels.list_levels`` dict into a :class:`LevelRow` with the two extras."""
    path = Path(row["path"])
    return LevelRow(
        level_id=row["levelId"],
        name=row["name"],
        layout=_LAYOUT_NAMES.get(row["layout"], row["layout"]),
        path=row["path"],
        size_bytes=row["sizeBytes"],
        sha256_short=row["sha256Short"],
        has_terrain=bool(row["hasTerrain"]),
        terrain_cell_count=_terrain_cell_count(path),
        directory_entries=_directory_entry_count(path),
        directory_defects=tuple(dict(d) for d in row["directoryDefects"]),
    )


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def build_report(account_dir: str | Path) -> SaveHealthReport:
    """Build the whole-save health report for ``account_dir``, READ-ONLY.

    ``account_dir`` is a uid folder or the ``Beyond_Local_Save_Level`` directory
    itself.  Raises ``FileNotFoundError`` when the tree is absent (the caller sees
    a named error, never a silently empty report -- ``levels.py:309``).
    """
    rows = levels.list_levels(account_dir)  # raises FileNotFoundError when absent
    level_rows = tuple(_row_from_levels_row(r) for r in rows)

    by_layout: dict[str, int] = {}
    defect_codes: dict[str, int] = {}
    for row in level_rows:
        by_layout[row.layout] = by_layout.get(row.layout, 0) + 1
        for code in row.defect_codes:
            defect_codes[code] = defect_codes.get(code, 0) + 1

    return SaveHealthReport(
        account_dir=str(account_dir),
        level_root=str(levels.resolve_level_root(account_dir)),
        levels=level_rows,
        level_count=len(level_rows),
        total_size_bytes=sum(r.size_bytes for r in level_rows if r.size_bytes is not None),
        levels_with_terrain=sum(1 for r in level_rows if r.has_terrain),
        total_terrain_cells=sum(r.terrain_cell_count for r in level_rows),
        levels_with_defects=sum(1 for r in level_rows if r.directory_defects),
        total_defects=sum(len(r.directory_defects) for r in level_rows),
        levels_unreadable=sum(1 for r in level_rows if r.size_bytes is None),
        by_layout={k: by_layout[k] for k in sorted(by_layout)},
        defect_codes={k: defect_codes[k] for k in sorted(defect_codes)},
    )


# --------------------------------------------------------------------------- #
# rendering -- text table and JSON
# --------------------------------------------------------------------------- #

def render_text(report: SaveHealthReport) -> str:
    """A compact fixed-width table, one line per level, with a totals footer."""
    header = (f"    {'levelId':>11} {'size':>9}  {'terrain':<7} {'cells':>6} "
              f"{'ents':>5} {'deflt':>5}  {'layout':<5} name / defects")
    lines = [f"save health -- {report.account_dir}", header]
    for row in report.levels:
        size = "-" if row.size_bytes is None else str(row.size_bytes)
        terrain_flag = "yes" if row.has_terrain else "no"
        ents = "-" if row.directory_entries is None else str(row.directory_entries)
        name = row.name if row.name is not None else f"<{row.path}>"
        codes = ",".join(row.defect_codes)
        suffix = f"  [{codes}]" if codes else ""
        lines.append(
            f"    {row.level_id:>11} {size:>9}  {terrain_flag:<7} "
            f"{row.terrain_cell_count:>6} {ents:>5} {len(row.directory_defects):>5}  "
            f"{row.layout:<5} {name}{suffix}")

    layout_bits = ", ".join(f"{k}={v}" for k, v in report.by_layout.items()) or "-"
    defect_bits = ", ".join(f"{k}x{v}" for k, v in report.defect_codes.items()) or "none"
    lines.append(
        f"totals: {report.level_count} level(s); "
        f"{report.total_size_bytes} B; "
        f"terrain {report.levels_with_terrain} level(s)/{report.total_terrain_cells} cell(s); "
        f"layout {layout_bits}")
    lines.append(
        f"        defects: {report.total_defects} on {report.levels_with_defects} level(s) "
        f"[{defect_bits}]; unreadable {report.levels_unreadable}")
    return "\n".join(lines)


def to_json(report: SaveHealthReport, *, indent: int | None = 2) -> str:
    """The report as a JSON string, ready to diff two runs.

    Key order is fixed and lists are already sorted by ``levelId`` (``levels`` sorts
    them), so two runs over the same tree produce byte-identical text -- which is
    what makes ``diff`` between two saves meaningful.
    """
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=indent, sort_keys=False)


# --------------------------------------------------------------------------- #
# CLI -- read-only
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="gameplan level-report",
        description="One read-only health table for a Miliastra save: layout, terrain "
                    "and directory defects together. Discovers the account; never pins "
                    "a level id.")
    parser.add_argument("--account-dir",
                        help="uid folder, or the Beyond_Local_Save_Level dir itself")
    parser.add_argument("--local-root",
                        help="override the miHoYo LocalLow root "
                             "(default: %%USERPROFILE%%\\AppData\\LocalLow\\miHoYo)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the table")
    args = parser.parse_args(argv)

    if args.account_dir:
        account: Path | None = Path(args.account_dir)
    else:
        account = levels.default_account_dir(args.local_root)
        if account is None:
            print(f"no live Miliastra save found under "
                  f"{args.local_root or levels.default_local_root()}", file=sys.stderr)
            return 2

    try:
        report = build_report(account)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    if args.json:
        print(to_json(report))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
