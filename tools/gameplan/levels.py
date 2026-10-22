"""Inventory every level in a Miliastra save tree -- one command, never a pinned id.

WHY THIS EXISTS
    Project doctrine is that a **level id is a function of the save** and must
    never be copied from one round to the next (``CLAUDE.md`` §四; the memory
    ``level-ids-are-per-save-never-pinned``).  ``tools/gameplan/live.py`` answers
    "what is open *right now*" (``live.py:1``, ``live.py:120``) but there was no
    way to see **all** the levels on disk with fresh metadata -- so every round
    still started by eyeballing ``ls`` and hand-copying a hex-y id.

    This module is that missing inventory.  ``list_levels(account_dir)`` walks the
    save tree READ-ONLY and returns one row per level: its id (taken from the file
    *name*, never from the file's own bytes -- see below), its name, its path, its
    size, a short content hash, whether it carries terrain, and any damage the
    level's directory shows.

TWO ON-DISK LAYOUTS, BOTH LIVE
    The save tree carries levels in two shapes at once, and both must be listed:

        <root>/1073741825.gil                 the older, bare-file form
        <root>/1073741836/1073741836.gil      the newer directory form

    Measured on the live save (2026-10-10, user 100000001): ids ``…825..834`` are
    bare files, ids ``…835..842`` are ``<id>/<id>.gil`` directories.  A tool that
    only knows the bare form silently misses half the save -- which is exactly why
    the live level ``…842`` (28383 B) went unnoticed by bare-path readers.

THE ID COMES FROM THE NAME, NOT THE PAYLOAD
    ``gil_container.py:257`` (``parse_level``) cross-checks the file's ``field 1``
    against the name and *raises* when they disagree; ``gil_container.py:540``
    (``read_level``) takes the id from ``path.stem``.  This module does the same:
    the id is the entry's name (bare ``<id>.gil`` stem, or the ``<id>/`` directory
    name), and a ``field 1`` that contradicts it becomes a recorded defect rather
    than a silent pass.

WHAT IT REUSES (no new decoders)
    * ``gil_container`` -- ``decode_container`` (``gil_container.py:86``) and
      ``parse_level`` (``gil_container.py:257``) for the container and the name.
    * ``level_directory`` -- ``check_directory`` (``level_directory.py:287``) for
      the root-``field 6`` tab-directory damage the module was written to expose.
    * ``terrain`` -- ``terrain_fields_of`` (``terrain.py:293``) for ``hasTerrain``;
      a level with no ``field 7`` raises ``TerrainError`` and reports ``False``.

READ-ONLY, STRUCTURALLY
    Every file touch here is a read: ``Path.read_bytes`` for the level bytes and
    the two readers above.  **No writer from any of the three modules is imported
    into a call path** -- in particular ``terrain``'s in-memory writers
    (``set_cell`` / ``add_terrain`` / ``apply_terrain_fields`` / ``to_level_bytes``,
    ``terrain.py:468-587``) and ``gil_container.write_bytes``
    (``gil_container.py:553``) are never reached.  ``tests/test_levels.py`` holds
    that line two ways: a source scan for writer tokens, and a runtime spy on
    ``open`` that fails on any non-read mode.

WHAT A ROW IS
    Each row is a plain dict, so ``json.dump`` needs no adapter::

        {levelId, name, path, sizeBytes, sha256Short, hasTerrain,
         directoryDefects, layout}

    ``directoryDefects`` folds two evidence streams into one list of
    ``{code, index, detail}`` blocks: the ``level_directory`` root-6 defects (their
    own codes, e.g. ``missing-entry-id``) and this module's own layout defects
    (``level-not-a-container``, ``level-parse-failed``,
    ``level-directory-without-gil``, ``level-directory-gil-name-mismatch``,
    ``level-directory-unreadable``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# ``gil_container`` / ``level_directory`` / ``terrain`` live beside each other
# under tools/beyond-save and reach one another as sibling modules, so that
# directory must be importable -- the same reach ``bounds.py:68`` and
# ``checkpoint.py:75`` use.
_BEYOND_SAVE = Path(__file__).resolve().parents[1] / "beyond-save"
if str(_BEYOND_SAVE) not in sys.path:
    sys.path.insert(0, str(_BEYOND_SAVE))

import gil_container  # noqa: E402
import level_directory  # noqa: E402
import terrain  # noqa: E402

#: The directory under a uid folder that holds the level files.
LEVEL_DIR_NAME = "Beyond_Local_Save_Level"

#: How many leading hex characters of the sha256 go in the row.  A short hash is
#: for telling two snapshots of the *same* id apart, not for verification.
SHA256_SHORT_HEX = 16

#: The two on-disk shapes a level can take.  Both are listed.
LAYOUT_BARE = "bare-file"           # <root>/<id>.gil
LAYOUT_NESTED = "nested-directory"  # <root>/<id>/<id>.gil

# Layout defects this module observes itself.  Root-6 defects keep whatever code
# ``level_directory`` gave them.
DEFECT_NOT_A_CONTAINER = "level-not-a-container"
DEFECT_PARSE_FAILED = "level-parse-failed"
DEFECT_DIR_WITHOUT_GIL = "level-directory-without-gil"
DEFECT_GIL_NAME_MISMATCH = "level-directory-gil-name-mismatch"
DEFECT_DIRECTORY_UNREADABLE = "level-directory-unreadable"


# --------------------------------------------------------------------------- #
# locating the tree
# --------------------------------------------------------------------------- #

def default_local_root() -> Path:
    """``%USERPROFILE%\\AppData\\LocalLow\\miHoYo`` -- the parent of every game."""
    return Path.home() / "AppData" / "LocalLow" / "miHoYo"


def _looks_like_level_root(path: Path) -> bool:
    """True when ``path`` itself holds level entries (a bare ``<id>.gil`` or ``<id>/``)."""
    if not path.is_dir():
        return False
    for entry in path.iterdir():
        if entry.is_file() and entry.suffix == ".gil" and _is_level_id(entry.stem):
            return True
        if entry.is_dir() and _is_level_id(entry.name):
            return True
    return False


def resolve_level_root(account_dir: str | Path) -> Path:
    """Find the directory that holds the level files.

    ``account_dir`` may be the uid folder (which contains ``Beyond_Local_Save_Level``)
    or that level directory itself.  The returned path may not exist -- the caller
    turns that into a named error rather than a silent empty list.
    """
    path = Path(account_dir)
    nested = path / LEVEL_DIR_NAME
    if nested.is_dir():
        return nested
    if path.name == LEVEL_DIR_NAME or _looks_like_level_root(path):
        return path
    return nested  # the expected-but-absent path, so the error names it


def find_account_dirs(local_root: str | Path | None = None) -> list[Path]:
    """Every uid folder under the miHoYo LocalLow root that carries a save tree.

    Scans ``<local_root>/<game>/BeyondLocal/<uid>/`` for a ``Beyond_Local_Save_Level``
    child.  Discovered, never pinned -- a different save is a different folder.
    """
    root = Path(local_root) if local_root is not None else default_local_root()
    found: list[Path] = []
    if not root.is_dir():
        return found
    for game in sorted(root.iterdir(), key=lambda p: p.name):
        beyond = game / "BeyondLocal"
        if not beyond.is_dir():
            continue
        for uid in sorted(beyond.iterdir(), key=lambda p: p.name):
            if (uid / LEVEL_DIR_NAME).is_dir():
                found.append(uid)
    return found


def default_account_dir(local_root: str | Path | None = None) -> Path | None:
    """The account whose level files were touched most recently, or ``None``.

    "Most recently written" is the best offline proxy for "the save in play"; it
    is a heuristic and is reported as such, never treated as identity.
    """
    best: Path | None = None
    best_mtime = float("-inf")
    for account in find_account_dirs(local_root):
        newest = _newest_level_mtime(account)
        if newest > best_mtime:
            best, best_mtime = account, newest
    return best


def _newest_level_mtime(account_dir: Path) -> float:
    root = resolve_level_root(account_dir)
    newest = float("-inf")
    if not root.is_dir():
        return newest
    for gil in root.rglob("*.gil"):
        try:
            newest = max(newest, gil.stat().st_mtime)
        except OSError:
            continue
    return newest


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _is_level_id(name: str) -> bool:
    try:
        int(name)
    except ValueError:
        return False
    return True


def _defect(code: str, detail: str, index: int | None = None) -> dict:
    return {"code": code, "index": index, "detail": detail}


def sha256_short(blob: bytes, length: int = SHA256_SHORT_HEX) -> str:
    """The leading ``length`` hex characters of ``blob``'s sha256."""
    return hashlib.sha256(blob).hexdigest()[:length]


# --------------------------------------------------------------------------- #
# one row
# --------------------------------------------------------------------------- #

def _tab_directory_defects(gil_path: Path) -> list[dict]:
    """Root-``field 6`` defects via ``level_directory.check_directory``.

    ``check_directory`` re-reads the file (``level_directory.py:287``); that second
    read is deliberate -- it keeps this module from re-implementing the field-6
    walk, and it is still read-only.
    """
    try:
        defects = level_directory.check_directory(gil_path)
    except Exception as error:  # noqa: BLE001 -- any decode failure is a defect, not a crash
        return [_defect(DEFECT_DIRECTORY_UNREADABLE, f"{type(error).__name__}: {error}")]
    return [
        _defect(getattr(d, "code", "?"), getattr(d, "detail", str(d)),
                index=getattr(d, "index", None))
        for d in defects
    ]


def _read_row(level_id: int, gil_path: Path, layout: str,
              extra_defects: list[dict] | None = None) -> dict:
    """Build one row from a level file, recording damage instead of raising."""
    defects = list(extra_defects or [])
    blob = gil_path.read_bytes()  # read-only
    name: str | None = None
    has_terrain = False
    level = None

    try:
        container = gil_container.decode_container(blob)
    except gil_container.ContainerError as error:
        defects.append(_defect(DEFECT_NOT_A_CONTAINER, str(error)))
    else:
        try:
            level = gil_container.parse_level(container.payload, level_id=level_id)
            name = level.name
        except (gil_container.ContainerError, UnicodeDecodeError) as error:
            defects.append(_defect(DEFECT_PARSE_FAILED, f"{type(error).__name__}: {error}"))

    if level is not None:
        try:
            decoded = terrain.terrain_fields_of(level, label=gil_path.name)
        except terrain.TerrainError:
            has_terrain = False
        else:
            has_terrain = len(decoded.terrains) > 0
        defects.extend(_tab_directory_defects(gil_path))

    return {
        "levelId": level_id,
        "name": name,
        "path": str(gil_path),
        "sizeBytes": len(blob),
        "sha256Short": sha256_short(blob),
        "hasTerrain": has_terrain,
        "directoryDefects": defects,
        "layout": layout,
    }


def _row_from_directory(directory: Path) -> dict:
    """One ``<id>/`` level directory: the expected ``<id>/<id>.gil``, or a defect."""
    level_id = int(directory.name)
    expected = directory / f"{directory.name}.gil"
    if expected.is_file():
        return _read_row(level_id, expected, LAYOUT_NESTED)

    strays = sorted(p.name for p in directory.glob("*.gil") if p.is_file())
    if strays:
        defect = _defect(
            DEFECT_GIL_NAME_MISMATCH,
            f"level directory {directory.name!r} holds {strays} but no "
            f"{directory.name}.gil")
    else:
        defect = _defect(
            DEFECT_DIR_WITHOUT_GIL,
            f"level directory {directory.name!r} holds no .gil file at all")
    return {
        "levelId": level_id,
        "name": None,
        "path": str(expected),
        "sizeBytes": None,
        "sha256Short": None,
        "hasTerrain": False,
        "directoryDefects": [defect],
        "layout": LAYOUT_NESTED,
    }


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def list_levels(account_dir: str | Path) -> list[dict]:
    """Every level in ``account_dir``'s save tree, READ-ONLY, sorted by id.

    ``account_dir`` is a uid folder or the ``Beyond_Local_Save_Level`` directory
    itself.  Returns one row per level (see the module docstring for the shape);
    an unreadable or damaged level is a row carrying ``directoryDefects``, never an
    exception.  Raises ``FileNotFoundError`` when the tree itself is absent -- an
    empty inventory and a missing save are different answers.
    """
    root = resolve_level_root(account_dir)
    if not root.is_dir():
        raise FileNotFoundError(
            f"no level tree at {root} (looked for {LEVEL_DIR_NAME!r} under "
            f"{Path(account_dir)})")

    rows: list[dict] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            if not _is_level_id(entry.name):
                continue  # UpgradeBackup and friends are not levels
            rows.append(_row_from_directory(entry))
        elif entry.is_file() and entry.suffix == ".gil" and _is_level_id(entry.stem):
            rows.append(_read_row(int(entry.stem), entry, LAYOUT_BARE))
    rows.sort(key=lambda row: row["levelId"])
    return rows


def level_ids(account_dir: str | Path) -> list[int]:
    """Just the ids, sorted.  The one-liner for "what is there right now?"."""
    return [row["levelId"] for row in list_levels(account_dir)]


def find_level_file(account_dir: str | Path, level_id: int) -> Path | None:
    """The on-disk path of ``level_id``, in whichever layout it uses; ``None`` if absent.

    Resolving fresh each call is the point: the id is a function of the save, and so
    is the layout it happens to live in.
    """
    root = resolve_level_root(account_dir)
    bare = root / f"{level_id}.gil"
    if bare.is_file():
        return bare
    nested = root / str(level_id) / f"{level_id}.gil"
    if nested.is_file():
        return nested
    return None


# --------------------------------------------------------------------------- #
# CLI -- read-only
# --------------------------------------------------------------------------- #

def format_rows(rows: list[dict]) -> str:
    """A fixed-width table, one line per level, defects summarised."""
    lines = [f"    {'levelId':>11} {'size':>9}  {'terrain':<7} {'layout':<17} "
             f"{'defects':<16} name"]
    for row in rows:
        size = "-" if row["sizeBytes"] is None else str(row["sizeBytes"])
        defects = ",".join(sorted({d["code"] for d in row["directoryDefects"]})) or "-"
        name = row["name"] if row["name"] is not None else f"<{row['path']}>"
        lines.append(f"    {row['levelId']:>11} {size:>9}  "
                     f"{'yes' if row['hasTerrain'] else 'no':<7} "
                     f"{row['layout']:<17} {defects:<16} {name}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="gameplan levels",
        description="List every level in a Miliastra save tree, read-only. "
                    "Discovers the account; never pins a level id.")
    parser.add_argument("--account-dir",
                        help="uid folder, or the Beyond_Local_Save_Level dir itself")
    parser.add_argument("--local-root",
                        help="override the miHoYo LocalLow root (default: %%USERPROFILE%%\\AppData\\LocalLow\\miHoYo)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args(argv)

    if args.account_dir:
        account: Path | None = Path(args.account_dir)
    else:
        account = default_account_dir(args.local_root)
        if account is None:
            print(f"no live Miliastra save found under "
                  f"{args.local_root or default_local_root()}", file=sys.stderr)
            return 2

    try:
        rows = list_levels(account)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
    if args.json:
        json.dump({
            "accountDir": str(account),
            "levelRoot": str(resolve_level_root(account)),
            "count": len(rows),
            "levels": rows,
        }, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(f"{account}")
        print(format_rows(rows))
        print(f"    {len(rows)} level(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
