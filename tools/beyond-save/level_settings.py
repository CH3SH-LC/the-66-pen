"""Decoder for ``.gil`` top-level field 11 -- the level-settings payload.

Everything here is *observed* structure, read off real ``.gil`` files under
``%USERPROFILE%\\AppData\\LocalLow\\miHoYo\\原神\\BeyondLocal\\<uid>\\``. Nothing in
this module writes; ``read_level_settings`` opens a file read-only and the only
"encode" it can do is the byte-identical re-encode used as a proof that the decode
lost nothing.

Why field 11
------------
``tools/beyond-save/gil_container.py`` documents the container and the handful of
top-level fields it understood (1 id, 2 name, 39 creator, 40 timestamp). It never
looked inside field 11. Third-party reverse-engineering notes describe it:

    `genshin-miliastra-file-format/docs/zh/内容负载/GIL.md`:
    ``// id = 11, type = LENGTH`` -> ``LevelSettings``,
    "包含所有关卡设置信息（阵营、预设点等）"

quoted in `docs/offline-research/CONTRACT-V08-TERRAIN.md:314-321`. The in-repo
observation matches that: field 11's children carry the Chinese strings
``初始玩家阵营``/``初始物件阵营``/``初始造物阵营`` (factions) and ``出生点1`` /
``新建预设点`` (preset points), which is exactly "阵营、预设点".

What this module can and cannot say about ``level.bounds``
----------------------------------------------------------
The group ``level.bounds`` (场景生效范围) is MISSING in
``tools/authoring/INTERFACE-INVENTORY.md:20``. ``docs/official-docs/LEVEL-SETTINGS-AND-BOUNDS.json``
records that the official 关卡设置 chapter names the field
(``运行后场景生效范围`` / ``生效范围`` / ``自定义范围``) but gives **no numbers and no
shape**.

This module can state positively, and the tests pin, that:

  * field 11 IS a protobuf message; its children are field numbers 1..10 in all 29
    of the 37 ``.gil`` on this machine that carry field 11 at all;
  * the vector at ``field11 > field 1 > field 1`` -- a 15-byte message holding
    three ``wire type 5`` (fixed 32-bit, little-endian) floats -- reads as (100.0,
    100.0, 100.0) in **every one of those 29** field-11 files.  It is the only
    vector in the *basic* sub-message, but it is **NOT the only vector-shaped value
    in field 11**: ``field11 > field 5 > field 1 > field 2`` is a preset-point
    field that is non-empty on two levels here -- a 3 x fixed32 POINT on
    1073741840, a single fixed32 (``0d0000c0c0`` = -6.0) on 1073741835 (four
    ``.gil`` files counting the ``Temp`` copies; present but 0 bytes on the other
    25 field-11 files) -- so only the 3-component form is unique to one level.  A
    point is not a box, so it is no scene range either;
  * the identical 3 x fixed32 encoding is used for the terrain record's world
    position in top-level field 7 (``field7 > field1 > field3 > field1`` =
    (-547.5, -2.5, -547.5)), so the triple is a project-wide convention, not a
    decoding coincidence.

This module CANNOT establish that that triple is ``运行后场景生效范围``. See
``describe()`` for the exact reason (it never varies across the 29 field-11 files
-- 29 of the 37 ``.gil`` on this machine carry field 11).

Depth of decode
---------------
Two layers are exported and kept apart, the same way ``gil_container`` keeps its
walker apart from its schema:

  * ``LevelSettings.fields`` / ``.data`` -- the raw field-11 children, kept byte
    for byte. ``LevelSettings.reencode()`` proves the walk was lossless.
  * ``.basic`` / ``.factions`` / ``.preset_points`` / ``.player_slots`` -- the
    parts whose *shape* the bytes actually justify. Anything whose meaning is an
    inference says so in its docstring.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gil_container import (  # noqa: E402
    Field,
    WIRE_32BIT,
    WIRE_LENGTH,
    WIRE_VARINT,
    decode_container,
    encode_fields,
    parse_fields,
)

# The top-level field number this module decodes. Established by the third-party
# GIL note quoted above and confirmed in-repo by the faction/preset strings.
LEVEL_FIELD_SETTINGS = 11

# Encodings inside field 11, all observed, each named for the bytes not a guess.
VEC3_FIELDS = (1, 2, 3)      # a 3-float vector is fields 1/2/3, wire type 5 each
VEC3_LEN = 15               # 3 * (1 key byte + 4 float bytes)
NAME_FIELD = 501            # the opaque extended key that carries a UTF-8 name
LEVEL_REF_MIN = 0x40000000  # level ids are 0x40000000 + n; a varint >= this is a ref

# Sub-messages of field 11 that this module names, with the evidence for each name.
PART_BASIC = 1       # the direct child 1..10 whose OWN payload holds a float vector -> 基础/生效范围 candidate
PART_FACTIONS = 2    # children carry 初始玩家阵营 / 初始物件阵营 / 初始造物阵营
PART_SPAWN = 3       # child carries the name 出生点1
PART_PRESET = 5      # child carries the name 新建预设点
PART_MEMBERS = 6     # child carries a packed list of small indices + a count


class LevelSettingsError(ValueError):
    """The bytes do not decode as a level-settings payload."""


# --------------------------------------------------------------------------- #
# small decoders
# --------------------------------------------------------------------------- #

def float32(field_value: int) -> float:
    """Reinterpret a wire-type-5 field's integer as an IEEE-754 binary32.

    ``gil_container`` stores wire-type-5 values as little-endian unsigned ints
    (``gil_container.py:197-202``); this is that value read back as the float the
    four bytes actually spell.
    """
    return struct.unpack("<f", struct.pack("<I", field_value & 0xFFFFFFFF))[0]


def parse_vec3(data: bytes) -> Optional["Vec3"]:
    """Decode ``{1:f32, 2:f32, 3:f32}`` -- or return None if the shape does not fit.

    Deliberately strict: exactly three children, numbered 1, 2, 3, all wire type 5
    (fixed 32-bit). A looser rule would turn unrelated triples of varints into a
    "vector" and defeat the point of the check.

    "Three floats" is this function's contract, not a claim that its callers meet
    only that shape: the same store -- ``field 11 > 5 > 1 > 2`` -- is a single
    fixed32 (``0d0000c0c0`` = -6.0) on level 1073741835, which this function
    correctly returns ``None`` for.  Only the 3-component form on 1073741840 is a
    vector.
    """
    fields = parse_fields(data)
    if len(fields) != 3:
        return None
    if [f.number for f in fields] != list(VEC3_FIELDS):
        return None
    if any(f.wire_type != WIRE_32BIT for f in fields):
        return None
    return Vec3(
        x=float32(fields[0].value or 0),
        y=float32(fields[1].value or 0),
        z=float32(fields[2].value or 0),
        raw=data,
    )


@dataclass(frozen=True)
class Vec3:
    """Three little-endian binary32 floats carried as protobuf fields 1/2/3."""
    x: float
    y: float
    z: float
    raw: bytes

    def __str__(self) -> str:
        return f"({self.x:g}, {self.y:g}, {self.z:g})"


@dataclass
class BasicSettings:
    """field 11 > field 1.

    Among the direct children 1..10 of field 11, the only one whose OWN payload
    directly contains a float vector.  The vector (at ``field 11 > 1 > 1``) is
    exposed as ``extent`` and is the scene-range candidate; see
    ``LevelSettings.describe``.

    "Direct" is load-bearing and must not be dropped: a second 3 x fixed32 vector
    sits one level deeper, at ``field 11 > 5 > 1 > 2``.  Direct child 5 does NOT
    hold that vector itself -- it holds child 1, which holds it -- so the sentence
    is true only as scoped to DIRECT children that DIRECTLY contain a vector.  Read
    without "direct" it would claim field 11 has one vector, which is false; the
    unique-vector guard exists to stop exactly that over-read.

    ``custom_range_bytes`` is field 11.1.2's raw payload. In all 29 field-11 files
    it is **empty** (a zero-length length-delimited field). That is consistent with a
    ``自定义范围`` box that has never been customised, but nothing in the bytes
    says so -- it is a hypothesis, and is kept raw for that reason.
    """
    extent: Optional[Vec3] = None
    custom_range_bytes: bytes = b""
    integers: dict[int, int] = field(default_factory=dict)
    floats: dict[int, float] = field(default_factory=dict)
    raw: list[Field] = field(default_factory=list)

    def reencode(self) -> bytes:
        return encode_fields(self.raw)


@dataclass
class Faction:
    """One entry of field 11 > field 2.

    Shape, from the bytes: a message with field 1 = name (UTF-8), field 2 = an
    integer index, field 3 = a UI marker string (``UI_MarkPlayer_Faction_N``).
    The names (玩家阵营 / 造物阵营 / 物件阵营1..) are what the editor's 阵营 tab
    shows; the ``UI_MarkPlayer_Faction_N`` strings are the same generator the rest
    of the project already reads from the UI resource tables.
    """
    name: str
    index: int
    ui_mark: str
    raw: bytes = b""


@dataclass
class NamedRecord:
    """A preset-point-style record: a name plus a level reference.

    Found inside field 11 > field 3 (出生点) and field 11 > field 5 (预设点). The
    record itself is one message holding:

      * a UTF-8 name under field number 501 (``出生点1`` / ``新建预设点``);
      * a varint >= 0x40000000 under field 1 or 2 -- a *level id*, not a coordinate;
      * an opaque field 502 whose wire type differs between the two sites (length
        delimited in field 3, varint in field 5).

    These records are **not coordinate-free**: the preset-point record under field
    11 > 5 can carry a *point* in its own field 2 (``field 11 > 5 > 1 > 2``).  That
    field is non-empty on two levels here (four ``.gil`` files counting the
    ``Temp`` copies) -- a 3 x fixed32 vector on 1073741840, a single fixed32
    (-6.0) on 1073741835; present but 0 bytes on the other 25 field-11 files -- so
    only the 3-component form is unique to one level.  It is not decoded here -- a
    point is not a ``level_ref`` -- but a
    coordinate's presence contradicts any reading of these records as position-less.
    The *spawn / terrain origin*
    coordinate is a separate value, in top-level field 7; see
    ``LevelSettings.describe``.
    """
    name: Optional[str]
    level_ref: Optional[int]
    site_field: int          # the field-11 child this record was found under (3 or 5)
    raw: bytes = b""


@dataclass
class PlayerSlots:
    """field 11 > field 6 > field 1.

    Carries field 4 as a **packed varint list** of small indices (1..8) and a
    varint count under field 502. Observed: eight indices with count 8 on
    1073741842, four indices with count 4 on 1073741825. Read as the 人数设置
    slot list, on the strength of the count equalling the list length -- an
    inference, labelled here rather than hidden.
    """
    indices: list[int]
    count: Optional[int]
    raw: bytes = b""


# --------------------------------------------------------------------------- #
# offset tracking
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Span:
    """Where one field sits: key offset and value offset, relative to the payload.

    ``value_start`` is the first payload byte of the field's *value* (after the
    key and, for length-delimited fields, after the length varint).
    """
    number: int
    wire_type: int
    key_offset: int
    value_start: int
    value_end: int


def find_field_spans(buf: bytes) -> list[Span]:
    """Like ``parse_fields`` but keeping each field's byte offsets.

    Offsets are relative to ``buf``. Raises the same way ``parse_fields`` does, so
    a misparse stays loud instead of silently resynchronising.
    """
    spans: list[Span] = []
    pos = 0
    n = len(buf)
    while pos < n:
        key_offset = pos
        key, pos = _read_varint(buf, pos)
        number, wire_type = key >> 3, key & 7
        if number == 0:
            raise LevelSettingsError(f"field number 0 at offset {pos}")
        if wire_type == WIRE_VARINT:
            value_start = pos
            _, pos = _read_varint(buf, pos)
            spans.append(Span(number, wire_type, key_offset, value_start, pos))
        elif wire_type == WIRE_LENGTH:
            length, pos = _read_varint(buf, pos)
            value_start = pos
            if pos + length > n:
                raise LevelSettingsError(
                    f"field {number} claims {length} bytes, only {n - pos} left")
            pos += length
            spans.append(Span(number, wire_type, key_offset, value_start, pos))
        elif wire_type == WIRE_32BIT:
            value_start = pos
            if pos + 4 > n:
                raise LevelSettingsError(f"field {number} truncated 32-bit value")
            pos += 4
            spans.append(Span(number, wire_type, key_offset, value_start, pos))
        elif wire_type == 1:  # 64-bit, kept for completeness; unseen in field 11
            value_start = pos
            if pos + 8 > n:
                raise LevelSettingsError(f"field {number} truncated 64-bit value")
            pos += 8
            spans.append(Span(number, wire_type, key_offset, value_start, pos))
        else:
            raise LevelSettingsError(f"field {number} has reserved wire type {wire_type}")
    return spans


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise LevelSettingsError("varint runs off the end of the buffer")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise LevelSettingsError("varint longer than 10 bytes")


def _first(fields: list[Field], number: int) -> Optional[Field]:
    for f in fields:
        if f.number == number:
            return f
    return None


def _all(fields: list[Field], number: int) -> list[Field]:
    return [f for f in fields if f.number == number]


def _text(f: Optional[Field]) -> Optional[str]:
    if f is None or f.wire_type != WIRE_LENGTH or f.data is None:
        return None
    try:
        return f.data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _packed_varints(data: bytes) -> list[int]:
    """Read a packed repeated varint payload; returns [] on anything malformed."""
    out: list[int] = []
    pos = 0
    try:
        while pos < len(data):
            value, pos = _read_varint(data, pos)
            out.append(value)
    except LevelSettingsError:
        return []
    return out


def _walk_named_records(data: bytes, site: int) -> list[NamedRecord]:
    """Find ``{... 501: name, <level id> ...}`` records inside a field-11 child.

    The record sits one or two levels down and at an inconsistent field number
    (field 3 puts it under field 2, field 5 under field 1), so this walks the
    children one level and accepts any message that carries field 501 as text.
    """
    records: list[NamedRecord] = []
    for child in parse_fields(data):
        if child.wire_type != WIRE_LENGTH or child.data is None:
            continue
        grand = parse_fields(child.data)
        name = _text(_first(grand, NAME_FIELD))
        if name is None:
            continue
        level_ref = None
        for g in grand:
            if g.wire_type == WIRE_VARINT and (g.value or 0) >= LEVEL_REF_MIN:
                level_ref = g.value
                break
        records.append(NamedRecord(name=name, level_ref=level_ref, site_field=site,
                                   raw=child.data))
    return records


# --------------------------------------------------------------------------- #
# the top-level decode
# --------------------------------------------------------------------------- #

@dataclass
class LevelSettings:
    """Everything field 11 yields, plus the proof that nothing was lost.

    ``present`` is False for a level whose payload has no field 11 at all -- which
    is the normal shape of a freshly-registered placeholder level; see
    ``describe``.
    """
    present: bool
    level_id: int
    payload: bytes = b""
    key_offset: Optional[int] = None
    value_start: Optional[int] = None
    value_end: Optional[int] = None
    data: Optional[bytes] = None               # field 11's value bytes
    fields: list[Field] = field(default_factory=list)   # parsed children of field 11
    basic: Optional[BasicSettings] = None
    factions: list[Faction] = field(default_factory=list)
    preset_points: list[NamedRecord] = field(default_factory=list)
    player_slots: Optional[PlayerSlots] = None
    raw_parts: dict[int, list[bytes]] = field(default_factory=dict)

    # -- proofs ------------------------------------------------------------- #

    def reencode(self) -> bytes:
        """Re-encode the whole payload. Must equal ``self.payload`` byte for byte.

        This is the read-only proof: it shows the walk understood the bytes well
        enough to reproduce them, so ``level.bounds`` work can never be blocked by
        a decoder that silently rewrites what it did not understand.
        """
        return encode_fields(parse_fields(self.payload))

    def reencode_settings(self) -> Optional[bytes]:
        """Re-encode just field 11's value; None when field 11 is absent."""
        if self.data is None:
            return None
        return encode_fields(parse_fields(self.data))

    # -- the vector --------------------------------------------------------- #

    @property
    def extent(self) -> Optional[Vec3]:
        """The basic sub-message's float vector (field 11 > 1 > 1) -- the scene-range candidate.

        Not the *only* vector in field 11 (a preset-point coordinate sits at
        ``field 11 > 5 > 1 > 2``); it is only the one this decoder reads as an
        extent.  ``None`` if field 11 is absent or its shape changed. See
        ``describe`` for why this is a candidate and not a claim.
        """
        return self.basic.extent if self.basic else None

    # -- human readout ------------------------------------------------------ #

    def describe(self) -> str:
        lines: list[str] = []
        size = len(self.data) if self.data else 0
        state = "present, %d bytes" % size if self.present else "ABSENT"
        lines.append(f"level {self.level_id}: field {LEVEL_FIELD_SETTINGS} {state}")
        if not self.present:
            lines.append("  - a freshly-registered / placeholder level carries no field 11:")
            lines.append("    the editor writes it only once level settings exist.")
            lines.append("  - therefore this level exposes NO scene-range value.")
            return "\n".join(lines)

        lines.append(f"  key at payload[{self.key_offset}], "
                     f"value payload[{self.value_start}:{self.value_end}]")
        lines.append(f"  parts: {sorted(f.number for f in self.fields)}")

        if self.extent is not None:
            lines.append("  extent candidate (field 11 > 1 > 1), 3 x fixed32 LE floats:")
            lines.append(f"    {self.extent}   bytes={self.extent.raw.hex()}")
            lines.append("    NOT PROVEN to be 运行后场景生效范围: the triple is "
                         "(100,100,100) in every .gil that carries field 11, so it")
            lines.append("    never tracks an edit; it could be a derived terrain size.")
        else:
            lines.append("  extent candidate: ABSENT (field 11 > 1 > 1 did not decode "
                         "as three fixed32 floats)")

        if self.basic is not None:
            if self.basic.custom_range_bytes == b"":
                lines.append("  field 11 > 1 > 2 is present but EMPTY (0 bytes) -- "
                             "consistent with an unused 自定义范围, unproven")
            ints = ", ".join(f"{k}={v}" for k, v in sorted(self.basic.integers.items()))
            flts = ", ".join(f"{k}={v:g}" for k, v in sorted(self.basic.floats.items()))
            lines.append(f"  basic integers: {ints}")
            lines.append(f"  basic floats  : {flts}")

        if self.factions:
            lines.append(f"  factions ({len(self.factions)}):")
            for fac in self.factions:
                lines.append(f"    [{fac.index}] {fac.name!r} ui={fac.ui_mark!r}")

        if self.preset_points:
            lines.append(f"  preset-point records ({len(self.preset_points)}):")
            for rec in self.preset_points:
                lines.append(f"    under field {rec.site_field}: name={rec.name!r} "
                             f"level_ref={rec.level_ref}")
            lines.append("    NOTE: a preset-point record may carry a coordinate POINT "
                         "in its own field 2 (field 11 > 5 > 1 > 2), which this decoder "
                         "does not read. The spawn / terrain-origin coordinate "
                         "(-547.5,-2.5,-547.5) is a different value, in TOP-LEVEL field 7 "
                         "(field7 > 1 > 3 > 1).")

        if self.player_slots is not None:
            lines.append(f"  player slots (field 11 > 6): indices={self.player_slots.indices} "
                         f"count={self.player_slots.count}")

        lines.append("  cannot establish from these bytes: the field number of "
                     "运行后场景生效范围; whether a range box is a size, a half-extent, "
                     "or a radius; and whether field 11 > 1 > 2 is 自定义范围.")
        return "\n".join(lines)


def parse_level_settings(payload: bytes, level_id: int) -> LevelSettings:
    """Decode field 11 out of an already-decompressed ``.gil`` protobuf payload."""
    top = parse_fields(payload)
    spans = {s.number: s for s in find_field_spans(payload)}
    f11 = _first(top, LEVEL_FIELD_SETTINGS)
    if f11 is None or f11.wire_type != WIRE_LENGTH or f11.data is None:
        return LevelSettings(present=False, level_id=level_id, payload=payload)

    span = spans.get(LEVEL_FIELD_SETTINGS)
    children = parse_fields(f11.data)

    settings = LevelSettings(
        present=True,
        level_id=level_id,
        payload=payload,
        key_offset=span.key_offset if span else None,
        value_start=span.value_start if span else None,
        value_end=span.value_end if span else None,
        data=f11.data,
        fields=children,
    )

    # field 1 -> basic / extent
    basic = _first(children, PART_BASIC)
    if basic is not None and basic.wire_type == WIRE_LENGTH and basic.data is not None:
        basic_fields = parse_fields(basic.data)
        extent = None
        custom_range = b""
        for child in basic_fields:
            if child.number == 1 and child.wire_type == WIRE_LENGTH and child.data is not None:
                extent = parse_vec3(child.data)
            elif child.number == 2 and child.wire_type == WIRE_LENGTH:
                custom_range = child.data or b""
        settings.basic = BasicSettings(
            extent=extent,
            custom_range_bytes=custom_range,
            integers={c.number: (c.value or 0) for c in basic_fields if c.wire_type == WIRE_VARINT},
            floats={c.number: float32(c.value or 0) for c in basic_fields if c.wire_type == WIRE_32BIT},
            raw=basic_fields,
        )

    # field 2 -> factions
    factions = _first(children, PART_FACTIONS)
    if factions is not None and factions.wire_type == WIRE_LENGTH and factions.data is not None:
        for entry in _all(parse_fields(factions.data), 1):
            if entry.wire_type != WIRE_LENGTH or entry.data is None:
                continue
            parts = parse_fields(entry.data)
            settings.factions.append(Faction(
                name=_text(_first(parts, 1)) or "",
                index=(_first(parts, 2).value if _first(parts, 2) else 0) or 0,
                ui_mark=_text(_first(parts, 3)) or "",
                raw=entry.data,
            ))

    # field 3 (出生点) and field 5 (预设点) -> named records
    for site in (PART_SPAWN, PART_PRESET):
        holder = _first(children, site)
        if holder is not None and holder.wire_type == WIRE_LENGTH and holder.data is not None:
            settings.preset_points.extend(_walk_named_records(holder.data, site))

    # field 6 -> player slots
    members = _first(children, PART_MEMBERS)
    if members is not None and members.wire_type == WIRE_LENGTH and members.data is not None:
        for entry in _all(parse_fields(members.data), 1):
            if entry.wire_type != WIRE_LENGTH or entry.data is None:
                continue
            parts = parse_fields(entry.data)
            list_field = _first(parts, 4)
            if list_field is None or list_field.wire_type != WIRE_LENGTH:
                continue
            settings.player_slots = PlayerSlots(
                indices=_packed_varints(list_field.data or b""),
                count=(_first(parts, 502).value if _first(parts, 502) else None),
                raw=entry.data,
            )

    # everything else, raw
    for child in children:
        if child.wire_type == WIRE_LENGTH:
            settings.raw_parts.setdefault(child.number, []).append(child.data or b"")

    return settings


def read_level_settings(path: Path) -> LevelSettings:
    """Read a ``<id>.gil`` READ-ONLY and decode its field 11.

    The level id comes from the file name, matching ``gil_container.read_level``:
    field 1 is present only in some files, so the name is the authority.
    """
    payload = decode_container(path.read_bytes()).payload
    try:
        level_id = int(Path(path).stem)
    except ValueError:
        level_id = 0
    return parse_level_settings(payload, level_id)
