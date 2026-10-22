"""Legacy in-memory codec for the terrain list in a Miliastra level file (``.gil``).

Current native editing lives in ``tools/map-terrain``. Its evidence establishes
native X/Z packing as ``x | (z << 16)``, integer height field 2, material field 3,
and preserved opaque fields 4..6. This historical module retains its original
high16/low16 x/y API for compatibility; do not pass those coordinates directly
to the native API. The 100..119 writer guard below describes this old interface,
not the current game's proven coordinate limit. Nothing here applies live edits.

Why this module exists
----------------------
``gil_container.py`` documents four fields of a level descriptor (id / name /
creator uid / timestamp) and keeps every other field -- including **field 7** --
as opaque bytes in ``Level.raw``.  Before this file there was *no code anywhere in
the tree that read field 7* (see ``docs/gameplan/TERRAIN-STATUS.md``).

This module has two halves.  The **reader** (``read_terrain_fields`` /
``terrain_fields_of``) only ever reads; ``read_terrain_fields`` *does* take a save
path (``gil_path``), but it opens the file read-only and never writes, and its
tests prove a decoded file is byte-identical afterwards.  The **writer**
(``set_cell`` / ``add_terrain`` / ``apply_terrain_fields`` / ``to_level_bytes``)
mutates an *in-memory* copy and hands bytes back to the caller; it takes Python
objects, never a path, and opens nothing.  So the *writer* half structurally
cannot be aimed at a live save, while the reader can be pointed at one but cannot
alter it.  Persisting the returned bytes is a separate, deliberate step the caller
owns.

What field 7 actually turns out to be (observed, not assumed)
-------------------------------------------------------------
Read off the real level files under
``%USERPROFILE%\\AppData\\LocalLow\\miHoYo\\原神\\BeyondLocal\\100000001\\Beyond_Local_Save_Level``
(``1073741825/828/829/830..834.gil``)::

    field 7  (WIRE_LENGTH)                    the terrain list
    └─ field 1 (WIRE_LENGTH)                  ONE terrain
       ├─ field 1 varint                       terrain id  (NOT the level id -- see note)
       ├─ field 2 (WIRE_LENGTH)                > field 1 = the name, e.g. "地形01"
       ├─ field 3 (WIRE_LENGTH)                transform: > field 1 > {1,2,3} = X,Y,Z floats
       └─ field 4 (WIRE_LENGTH) * 400          one cell each
          └─ { field 1 varint = (x << 16) | y
               field 2 varint = raw value (layer count; 1 for the untouched default) }

``1073741826.gil`` / ``1073741827.gil`` are 79/78-byte placeholder levels and
carry **no field 7 at all** -- ``read_terrain_fields`` raises ``TerrainError``
for them rather than inventing an empty terrain.

Two corrections to the prose in ``docs/research/.../M6a-level-terrain.md``,
which the decode contradicts:

* It claims "f1 = level id / 地形 id = 关卡 id".  False in general: the terrain id
  is the *same* 1073741825 in every file, including ``1073741828.gil`` whose own
  level id is 1073741828.  It is a fixed constant, not the containing level's id.
* It lists 1073741826/827 among the "levels with terrain".  They have none.

Every field number and the ``(x<<16)|y`` packing below come from decoding the
real bytes; ``GRID_MIN``/``GRID_MAX``/``CELLS_PER_TERRAIN`` are asserted against
them in ``test_terrain.py`` rather than assumed.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import dataclass, field as _dc_field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # importable as a plain module, like gil_container
    sys.path.insert(0, str(_HERE))

from gil_container import (  # noqa: E402
    SUBTYPE_LEVEL,
    WIRE_32BIT,
    WIRE_LENGTH,
    WIRE_VARINT,
    Container,
    ContainerError,
    Field,
    Level,
    decode_container,
    encode_container,
    encode_fields,
    parse_fields,
    read_level,
)


class TerrainError(ValueError):
    """A level payload is not a decodable terrain list."""


# --------------------------------------------------------------------------- #
# field numbers -- evidence, not a vendor schema (see module docstring)
# --------------------------------------------------------------------------- #

FIELD_TERRAIN_LIST = 7      # top level: the terrain list
TERRAIN_FIELD_ID = 1        # a terrain's id
TERRAIN_FIELD_NAME = 2      # a terrain's name (nested one level down)
TERRAIN_FIELD_TRANSFORM = 3  # a terrain's origin / transform
TERRAIN_FIELD_CELL = 4      # one grid cell, repeated

CELL_FIELD_COORD = 1        # (x << 16) | y
CELL_FIELD_VALUE = 2        # raw value (layer count)

# The name is a nested message: terrain.field2 > field1 = the utf-8 name.
_NAME_TEXT_FIELD = 1

# Geometry observed on every default terrain. Kept as named constants so the
# test can hold the decoder to them, and so a future non-default terrain that
# breaks them is visible instead of silently averaged away.
GRID_MIN = 100
GRID_MAX = 119
GRID_SIDE = 20
CELLS_PER_TERRAIN = GRID_SIDE * GRID_SIDE  # 400


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _first(fields: list[Field], number: int) -> Field | None:
    for f in fields:
        if f.number == number:
            return f
    return None


def _all(fields: list[Field], number: int) -> list[Field]:
    return [f for f in fields if f.number == number]


def _varint(field: Field | None) -> int | None:
    if field is None or field.wire_type != WIRE_VARINT:
        return None
    return field.value


@dataclass(frozen=True)
class TerrainCell:
    """One grid cell of a terrain, with its raw fields kept for fidelity."""
    x: int
    y: int
    coord: int          # the raw (x << 16) | y value from field 1
    value: int | None   # the raw value from field 2 (layer count)
    raw: tuple[Field, ...] = ()

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"({self.x},{self.y})=[{self.coord:#x}]->{self.value}"


@dataclass
class Terrain:
    """One terrain. ``cells`` maps ``(x, y) -> raw value`` (field 2)."""
    terrain_id: int | None
    name: str
    cells: dict[tuple[int, int], int | None] = _dc_field(default_factory=dict)
    transform: tuple[float, float, float] | None = None
    cell_fields: dict[tuple[int, int], TerrainCell] = _dc_field(default_factory=dict)
    raw: list[Field] = _dc_field(default_factory=list)

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        if not self.cells:
            return None
        xs = [x for x, _ in self.cells]
        ys = [y for _, y in self.cells]
        return (min(xs), min(ys), max(xs), max(ys))

    def value_counts(self) -> dict[int | None, int]:
        counts: dict[int | None, int] = {}
        for v in self.cells.values():
            counts[v] = counts.get(v, 0) + 1
        return counts

    def describe(self) -> str:
        if not self.cells:
            grid = "0 cells"
        else:
            mnx, mny, mxx, mxy = self.bounds  # type: ignore[misc]
            grid = f"{len(self.cells)} cells, x {mnx}..{mxx}, y {mny}..{mxy}"
        counts = ", ".join(f"{v}×{n}" for v, n in sorted(
            self.value_counts().items(), key=lambda kv: (kv[0] is None, kv[0])))
        origin = "" if self.transform is None else f", transform {self.transform}"
        return (f"terrain {self.name!r} (id {self.terrain_id}): {grid}; "
                f"values {{{counts}}}{origin}")


@dataclass
class TerrainFields:
    """The decoded terrain list of one level.

    The scalar ``terrain_id`` / ``name`` / ``cells`` describe the *primary*
    (first) terrain, which is the only shape on this machine.  ``terrains`` keeps
    all of them, and ``raw`` / ``raw_field7`` keep the original bytes so a
    caller can re-serialise field 7 without loss.
    """
    level_id: int
    terrain_id: int | None = None
    name: str = ""
    cells: dict[tuple[int, int], int | None] = _dc_field(default_factory=dict)
    transform: tuple[float, float, float] | None = None
    terrains: tuple[Terrain, ...] = ()
    raw: list[Field] = _dc_field(default_factory=list)
    raw_field7: Field | None = None

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    def describe(self) -> str:
        if not self.terrains:
            return f"level {self.level_id}: field 7 present but holds no terrain"
        parts = [f"level {self.level_id}: {len(self.terrains)} terrain(s)"]
        parts.extend("  " + t.describe() for t in self.terrains)
        return "\n".join(parts)

    def __str__(self) -> str:  # pragma: no cover - display only
        return self.describe()


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #

def _decode_name(field: Field | None) -> str:
    """The name is a nested message (field 2 > field 1 = utf-8 text)."""
    if field is None or field.wire_type != WIRE_LENGTH or field.data is None:
        return ""
    inner = _first(parse_fields(field.data), _NAME_TEXT_FIELD)
    if inner is None:
        # Tolerate a flat encoding too, in case a writer ever degrades to it.
        try:
            return field.data.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return inner.data.decode("utf-8") if inner.data is not None else ""


def _decode_transform(field: Field | None) -> tuple[float, float, float] | None:
    """field 3 > field 1 > fields 1, 2, 3 = X, Y, Z little-endian float32."""
    if field is None or field.wire_type != WIRE_LENGTH or field.data is None:
        return None
    holder = _first(parse_fields(field.data), TERRAIN_FIELD_ID)
    if holder is None or holder.data is None:
        return None
    floats: list[float] = [
        struct.unpack("<f", f.value.to_bytes(4, "little"))[0]
        for f in parse_fields(holder.data)
        if f.wire_type == WIRE_32BIT and f.value is not None
    ]
    if len(floats) < 3:
        return None
    return (floats[0], floats[1], floats[2])


def _decode_cell(field: Field) -> TerrainCell:
    parts = parse_fields(field.data or b"")
    coord = _varint(_first(parts, CELL_FIELD_COORD))
    if coord is None:
        raise TerrainError("terrain cell has no field 1 coordinate")
    value = _varint(_first(parts, CELL_FIELD_VALUE))
    return TerrainCell(
        x=coord >> 16,
        y=coord & 0xFFFF,
        coord=coord,
        value=value,
        raw=tuple(parts),
    )


def _decode_terrain(field: Field) -> Terrain:
    parts = parse_fields(field.data or b"")
    cells: dict[tuple[int, int], int | None] = {}
    cell_fields: dict[tuple[int, int], TerrainCell] = {}
    for cell_field in _all(parts, TERRAIN_FIELD_CELL):
        cell = _decode_cell(cell_field)
        key = (cell.x, cell.y)
        cells[key] = cell.value
        cell_fields[key] = cell
    return Terrain(
        terrain_id=_varint(_first(parts, TERRAIN_FIELD_ID)),
        name=_decode_name(_first(parts, TERRAIN_FIELD_NAME)),
        cells=cells,
        transform=_decode_transform(_first(parts, TERRAIN_FIELD_TRANSFORM)),
        cell_fields=cell_fields,
        raw=parts,
    )


def _find_terrain_field(raw: list[Field]) -> Field | None:
    f7 = _first(raw, FIELD_TERRAIN_LIST)
    if f7 is None:
        return None
    if f7.wire_type != WIRE_LENGTH:
        raise TerrainError(
            f"field {FIELD_TERRAIN_LIST} is wire type {f7.wire_type}, "
            f"expected length-delimited ({WIRE_LENGTH})"
        )
    return f7


def terrain_fields_of(level: Level, label: str | None = None) -> TerrainFields:
    """Decode the terrain list (field 7) of an already-parsed level.

    In-memory: takes a :class:`~gil_container.Level` and opens nothing.  Raises
    :class:`TerrainError` when the level carries no field 7 (e.g. a placeholder
    level).  ``label`` names the source in that error; it defaults to the level id.
    """
    f7 = _find_terrain_field(level.raw)
    if f7 is None:
        who = label or f"level {level.level_id}"
        raise TerrainError(
            f"{who}: no field {FIELD_TERRAIN_LIST} -- this level carries no terrain "
            f"(top-level fields: {sorted(f.number for f in level.raw)})"
        )
    child_fields = parse_fields(f7.data or b"")
    terrains = tuple(_decode_terrain(tf) for tf in _all(child_fields, TERRAIN_FIELD_ID))
    primary = terrains[0] if terrains else None
    return TerrainFields(
        level_id=level.level_id,
        terrain_id=primary.terrain_id if primary else None,
        name=primary.name if primary else "",
        cells=dict(primary.cells) if primary else {},
        transform=primary.transform if primary else None,
        terrains=terrains,
        raw=child_fields,
        raw_field7=f7,
    )


def read_terrain_fields(gil_path: str | Path) -> TerrainFields:
    """Decode the terrain list (field 7) of a level file.

    Read-only: the file is opened for reading only and is not touched.  Raises
    :class:`TerrainError` when the file has no field 7 (e.g. a placeholder
    level), and :class:`~gil_container.ContainerError` when the file is not a
    well-formed save container.
    """
    path = Path(gil_path)
    level = read_level(path)  # cross-checks field 1 against the file name
    return terrain_fields_of(level, label=path.name)


def reserialise_field7(fields: TerrainFields) -> bytes:
    """Re-encode field 7 from what was decoded -- used to prove losslessness.

    This is *not* a writer: the bytes are handed back to the caller, never to
    disk.  For any file this returns the exact original field 7 payload.
    """
    if fields.raw_field7 is None or fields.raw_field7.data is None:
        raise TerrainError("no field 7 to re-serialise")
    return encode_fields(parse_fields(fields.raw_field7.data))


# --------------------------------------------------------------------------- #
# writer -- IN-MEMORY ONLY.
#
# Nothing in this section takes or returns a file path, and nothing here touches
# a file.  Every function either mutates a Python object (a ``Terrain``'s cells,
# a ``Level``'s raw field list) or hands bytes back to the caller; persisting
# those bytes is a separate, deliberate step.  This is deliberate armour: a
# terrain writer that could be pointed at a live save is exactly what the project
# discipline forbids, so the API is built so it cannot be.
# --------------------------------------------------------------------------- #

# The value every cell of an untouched default terrain carries (field 2 = 1).
DEFAULT_CELL_VALUE = 1


def default_cells(value: int = DEFAULT_CELL_VALUE) -> dict[tuple[int, int], int]:
    """The 20x20 default grid: all 400 cells at ``value`` (1 = untouched)."""
    return {(x, y): value for x in range(GRID_MIN, GRID_MAX + 1)
            for y in range(GRID_MIN, GRID_MAX + 1)}


def _require_grid_cell(x: int, y: int) -> None:
    """Refuse a coordinate outside the only grid this format has been seen with."""
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
        raise TerrainError(f"cell coordinates must be ints, got ({x!r}, {y!r})")
    if not (GRID_MIN <= x <= GRID_MAX and GRID_MIN <= y <= GRID_MAX):
        raise TerrainError(
            f"cell ({x},{y}) is outside the writable grid {GRID_MIN}..{GRID_MAX} "
            f"(both axes); refusing rather than inventing a cell no real file carries"
        )


def _require_value(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TerrainError(f"cell value must be a non-negative int, got {value!r}")


def _float32_bits(value: float) -> int:
    return int.from_bytes(struct.pack("<f", value), "little")


def _cell_field(cell: TerrainCell, value: int | None) -> Field:
    """Rebuild one cell field, changing only its value and keeping everything else.

    ``value is None`` drops field 2, matching how a valueless cell was decoded.
    """
    parts: list[Field] = []
    replaced = False
    for f in cell.raw:
        if f.number == CELL_FIELD_VALUE:
            replaced = True
            if value is not None:
                parts.append(Field(CELL_FIELD_VALUE, WIRE_VARINT, value=value))
        else:
            parts.append(f)
    if not replaced and value is not None:
        parts.append(Field(CELL_FIELD_VALUE, WIRE_VARINT, value=value))
    return Field(TERRAIN_FIELD_CELL, WIRE_LENGTH, data=encode_fields(parts))


def _new_cell_field(x: int, y: int, value: int) -> Field:
    coord = (x << 16) | y
    return Field(TERRAIN_FIELD_CELL, WIRE_LENGTH, data=encode_fields([
        Field(CELL_FIELD_COORD, WIRE_VARINT, value=coord),
        Field(CELL_FIELD_VALUE, WIRE_VARINT, value=value),
    ]))


def encode_terrain(terrain: Terrain) -> bytes:
    """Re-encode one terrain message from its in-memory state.

    A cell whose value is unchanged is emitted with its *original* bytes, so a
    terrain nobody edited reproduces its input exactly and an edited one differs
    only where it was edited.  A cell present in ``cells`` but not in the raw
    fields (i.e. one just added) is appended.
    """
    parts: list[Field] = []
    seen: set[tuple[int, int]] = set()
    for f in terrain.raw:
        if f.number == TERRAIN_FIELD_CELL and f.wire_type == WIRE_LENGTH and f.data is not None:
            cell = _decode_cell(f)
            key = (cell.x, cell.y)
            seen.add(key)
            if key not in terrain.cells:
                continue  # an explicit in-memory deletion must not resurrect the raw cell
            new_value = terrain.cells[key]
            parts.append(f if new_value == cell.value else _cell_field(cell, new_value))
        else:
            parts.append(f)
    for key in sorted(terrain.cells):
        if key not in seen:
            parts.append(_new_cell_field(key[0], key[1], terrain.cells[key]))
    return encode_fields(parts)


def _terrain_entry(terrain: Terrain) -> Field:
    """One terrain as a field-7 child (field 1, length-delimited)."""
    return Field(TERRAIN_FIELD_ID, WIRE_LENGTH, data=encode_terrain(terrain))


def _terrain_parts(terrain: Terrain) -> list[Field]:
    """The raw field list of a freshly built terrain (id, name, transform, cells)."""
    parts: list[Field] = []
    if terrain.terrain_id is not None:
        parts.append(Field(TERRAIN_FIELD_ID, WIRE_VARINT, value=terrain.terrain_id))
    if terrain.name:
        parts.append(Field(TERRAIN_FIELD_NAME, WIRE_LENGTH, data=encode_fields([
            Field(_NAME_TEXT_FIELD, WIRE_LENGTH, data=terrain.name.encode("utf-8")),
        ])))
    if terrain.transform is not None:
        tx, ty, tz = terrain.transform
        points = encode_fields([
            Field(1, WIRE_32BIT, value=_float32_bits(tx)),
            Field(2, WIRE_32BIT, value=_float32_bits(ty)),
            Field(3, WIRE_32BIT, value=_float32_bits(tz)),
        ])
        parts.append(Field(TERRAIN_FIELD_TRANSFORM, WIRE_LENGTH, data=encode_fields([
            Field(TERRAIN_FIELD_ID, WIRE_LENGTH, data=points),
        ])))
    for (x, y) in sorted(terrain.cells):
        parts.append(_new_cell_field(x, y, terrain.cells[(x, y)]))
    return parts


def set_cell(terrain: Terrain, x: int, y: int, value: int) -> None:
    """Change one cell of an in-memory terrain.  Never touches a file.

    Both axes must lie in the observed 100..119 grid, and the value must be a
    non-negative int; anything else raises :class:`TerrainError` and leaves the
    terrain untouched.  Taking a ``Terrain`` (not a path) means this cannot be
    aimed at a save file.
    """
    if not isinstance(terrain, Terrain):
        raise TerrainError(
            f"set_cell takes a Terrain object, not {type(terrain).__name__}; "
            "this writer never edits a path"
        )
    _require_grid_cell(x, y)
    _require_value(value)
    terrain.cells[(x, y)] = value


def add_terrain(
    level_fields: list[Field],
    terrain_id: int | None = None,
    name: str = "",
    transform: tuple[float, float, float] | None = None,
    cells: dict[tuple[int, int], int] | None = None,
) -> Terrain:
    """Add a terrain to a level's in-memory field list, and return it.

    ``level_fields`` is a ``Level.raw``-shaped list of top-level fields.  If it
    already carries field 7 the new terrain is appended to that list, otherwise
    field 7 is created -- that is how a placeholder level gets its first terrain.
    In-memory only: the list is mutated, no file is touched.

    ``cells`` defaults to the observed default grid (400 cells, value 1).  Every
    key must satisfy the same 100..119 bound as :func:`set_cell`.
    """
    if not isinstance(level_fields, list):
        raise TerrainError(
            f"add_terrain takes a list of Fields (a Level.raw), not {type(level_fields).__name__}"
        )
    if cells is None:
        cells = default_cells()
    checked: dict[tuple[int, int], int] = {}
    for (x, y), value in cells.items():
        _require_grid_cell(x, y)
        _require_value(value)
        checked[(x, y)] = value

    terrain = Terrain(terrain_id=terrain_id, name=name, cells=checked, transform=transform)
    terrain.raw = _terrain_parts(terrain)
    entry = _terrain_entry(terrain)

    for i, f in enumerate(level_fields):
        if f.number == FIELD_TERRAIN_LIST and f.wire_type == WIRE_LENGTH:
            children = parse_fields(f.data or b"")
            children.append(entry)
            level_fields[i] = Field(FIELD_TERRAIN_LIST, WIRE_LENGTH, data=encode_fields(children))
            break
    else:
        level_fields.append(Field(FIELD_TERRAIN_LIST, WIRE_LENGTH, data=encode_fields([entry])))
    return terrain


def encode_terrain_list(fields: TerrainFields) -> bytes:
    """The field-7 payload for a decoded (and possibly edited) terrain list.

    Terrains are re-emitted in place of the field-1 entries in ``fields.raw``; any
    other field-7 child is carried through untouched.  With no edit this returns
    exactly ``fields.raw_field7.data``.
    """
    entries = [_terrain_entry(t) for t in fields.terrains]
    parts: list[Field] = []
    i = 0
    for f in fields.raw:
        if f.number == TERRAIN_FIELD_ID and f.wire_type == WIRE_LENGTH:
            if i < len(entries):
                parts.append(entries[i])
                i += 1
            continue
        parts.append(f)
    parts.extend(entries[i:])
    return encode_fields(parts)


def apply_terrain_fields(level: Level, fields: TerrainFields) -> None:
    """Splice an edited terrain list back into a level's in-memory field list.

    Mutates ``level.raw`` only.  When the level had no field 7 one is appended
    (the first-terrain case); otherwise the existing field 7 keeps its position.
    """
    if not isinstance(level, Level):
        raise TerrainError(
            f"apply_terrain_fields takes a Level object, not {type(level).__name__}"
        )
    new_field7 = Field(FIELD_TERRAIN_LIST, WIRE_LENGTH, data=encode_terrain_list(fields))
    parts: list[Field] = []
    inserted = False
    for f in level.raw:
        if f.number == FIELD_TERRAIN_LIST and f.wire_type == WIRE_LENGTH and not inserted:
            parts.append(new_field7)
            inserted = True
            continue
        parts.append(f)
    if not inserted:
        parts.append(new_field7)
    level.raw[:] = parts


def to_level_bytes(level: Level) -> bytes:
    """Re-encode a level to full container bytes.  Takes an object, never a path.

    The result is what a caller may persist themselves, after taking a backup;
    this function itself opens nothing and touches no file.
    """
    if not isinstance(level, Level):
        raise TerrainError(
            f"to_level_bytes takes a Level object, not {type(level).__name__}; "
            "this writer returns bytes and never writes a path"
        )
    payload = encode_fields(level.raw)
    return encode_container(Container(subtype=SUBTYPE_LEVEL, payload=payload))


# --------------------------------------------------------------------------- #
# blob-level surface -- the same idiom as ``field15_edit``.
#
# ``field15_edit`` is a *bytes-in / bytes-out* primitive: it takes a level blob
# and hands back a new one, with a result object that records the exact diff and
# per-record sha256 so "every other record is untouched" is a fact, not a claim.
# The object-level writers above cannot express that without the caller first
# building a ``Level``; these wrappers close the gap so field 7 has the same
# single-call surface.  **Still in-memory only**: ``bytes`` go in, ``bytes`` come
# back, nothing here opens a file, and no evidence exists that the game accepts
# bytes we produce (the editor remains the only proven writer of this file).
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Field7Edit:
    """The result of an in-memory cell edit: the new blob plus the exact diff facts.

    ``blob`` is NOT written anywhere. ``digests_before`` / ``digests_after`` are
    the per-terrain sha256 (the unit :func:`terrain_digests` returns); for a
    single-cell edit exactly one index should differ -- the edited terrain --
    which is how "every unrelated record is untouched" is proven rather than
    inferred from a length.
    """
    blob: bytes
    operation: str
    x: int
    y: int
    old_value: int | None
    new_value: int
    terrain_index: int
    size_before: int
    size_after: int
    field7_len_before: int
    field7_len_after: int
    terrain_count_before: int
    terrain_count_after: int
    digests_before: tuple[str, ...]
    digests_after: tuple[str, ...]

    @property
    def byte_delta(self) -> int:
        """Exact file-size growth (0 for a same-width edit, +k once a varint widens)."""
        return self.size_after - self.size_before

    @property
    def touched_indices(self) -> tuple[int, ...]:
        """Terrain positions whose per-terrain sha256 changed (the proof unit)."""
        return tuple(i for i, (a, b) in enumerate(zip(self.digests_before, self.digests_after))
                     if a != b)

    @property
    def untouched_indices(self) -> tuple[int, ...]:
        return tuple(i for i in range(min(len(self.digests_before), len(self.digests_after)))
                     if self.digests_before[i] == self.digests_after[i])


def _level_from_blob(blob: bytes) -> Level:
    """A ``Level`` over a blob's root fields. The blob carries no file name, so an
    absent field 1 leaves ``level_id`` at 0 -- readable, but never used to write."""
    root = parse_fields(decode_container(blob).payload)
    return Level(level_id=0, name="", raw=root)


def _terrain_entry_fields(fields: TerrainFields) -> list[Field]:
    """The field-7 children that are terrain entries (field 1, length-delimited)."""
    return [f for f in fields.raw
            if f.number == TERRAIN_FIELD_ID and f.wire_type == WIRE_LENGTH]


def reserialise_level(blob: bytes) -> bytes:
    """Re-encode a level container with NO change: bytes in, bytes out.

    Byte-exact for every real (decodable) file -- the tests assert it. This is not
    a writer: the bytes are handed back to the caller, never to a path. The
    container subtype is required to be a level (2), mirroring
    ``field15_edit.reserialise_level``.
    """
    container = decode_container(blob)
    if container.subtype != SUBTYPE_LEVEL:
        raise TerrainError(f"container subtype {container.subtype} is not a level ({SUBTYPE_LEVEL})")
    return to_level_bytes(_level_from_blob(blob))


def terrain_digests(blob: bytes) -> list[str]:
    """``[sha256(entry)]`` -- one digest per terrain, in field-7 order.

    The unit the idiom compares on: unchanged terrains must keep an identical
    digest across an edit, whatever the container length does. Keyed by position,
    not by terrain id -- the observed default terrain id (1073741825) is a fixed
    constant and need not be unique. Raises :class:`TerrainError` if there is no
    field 7.
    """
    info = terrain_fields_of(_level_from_blob(blob), label="<blob>")
    return [hashlib.sha256(encode_fields([e])).hexdigest() for e in _terrain_entry_fields(info)]


def edit_cell(
    blob: bytes,
    x: int,
    y: int,
    value: int,
    *,
    terrain_index: int = 0,
) -> Field7Edit:
    """Return a NEW level blob with ONE cell of ONE terrain changed. Pure function.

    ``blob`` in, new ``bytes`` out; nothing is written. The edit is applied through
    the object-level writers (``set_cell`` -> ``apply_terrain_fields`` ->
    ``to_level_bytes``) so there is one validation path and one encoder; a refused
    coordinate/value raises :class:`TerrainError` before any bytes are produced.
    Every other terrain is proven untouched by comparing per-terrain sha256
    (:func:`terrain_digests`), not by a length.
    """
    container = decode_container(blob)
    if container.subtype != SUBTYPE_LEVEL:
        raise TerrainError(f"container subtype {container.subtype} is not a level ({SUBTYPE_LEVEL})")
    level = _level_from_blob(blob)
    info = terrain_fields_of(level, label="<blob>")
    if not info.terrains:
        raise TerrainError("field 7 present but holds no terrain to edit")
    if not (0 <= terrain_index < len(info.terrains)):
        raise TerrainError(
            f"terrain_index {terrain_index} out of range 0..{len(info.terrains) - 1}")

    digests_before = terrain_digests(blob)
    field7_before = len(info.raw_field7.data or b"")
    target = info.terrains[terrain_index]
    old_value = target.cells.get((x, y))

    set_cell(target, x, y, value)          # validates x/y and value; raises before any encode
    apply_terrain_fields(level, info)
    new_blob = to_level_bytes(level)

    after_info = terrain_fields_of(_level_from_blob(new_blob), label="<blob>")
    return Field7Edit(
        blob=new_blob,
        operation="set-cell",
        x=x,
        y=y,
        old_value=old_value,
        new_value=value,
        terrain_index=terrain_index,
        size_before=len(blob),
        size_after=len(new_blob),
        field7_len_before=field7_before,
        field7_len_after=len(after_info.raw_field7.data or b""),
        terrain_count_before=len(info.terrains),
        terrain_count_after=len(after_info.terrains),
        digests_before=tuple(digests_before),
        digests_after=tuple(terrain_digests(new_blob)),
    )


def _main(argv: list[str]) -> int:  # pragma: no cover - manual inspection
    paths = argv[1:]
    if not paths:
        print("usage: python -m terrain <level.gil> [more.gil ...]")
        return 2
    for p in paths:
        try:
            info = read_terrain_fields(p)
        except (TerrainError, ContainerError) as exc:
            print(f"{p}: {type(exc).__name__}: {exc}")
            continue
        print(f"{p}:")
        print(info.describe())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
