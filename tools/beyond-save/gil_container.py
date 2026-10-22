"""Container codec for the Miliastra local save files.

Two file kinds live under
``%USERPROFILE%\\AppData\\LocalLow\\miHoYo\\<game>\\BeyondLocal\\<uid>\\``:

  ``Beyond_Local_Save_Player.gip``   the player profile -- the project registry
  ``Beyond_Local_Save_Level\\<id>.gil``   one level descriptor per file

Both are the same framing wrapped around a protobuf payload, so this module
deliberately keeps two layers apart:

  * ``parse_fields`` / ``encode_fields`` -- a generic protobuf walker that keeps
    every field's raw bytes. It never guesses a schema, and ``encode_fields``
    reproduces ``parse_fields``'s input byte for byte. That round-trip property is
    what makes it safe to edit one field of a real file and leave the rest alone.
  * ``parse_level`` / ``parse_profile`` -- the schema, as far as it has been
    *observed*. Every field number here was read off real files; anything not
    understood is kept in ``Level.raw`` / ``Profile.raw`` rather than dropped.

Container layout, verified against all four real ``.gil`` files and the live
``.gip``:

    u32be  total length      == 20 + inner length  (everything after this field)
    u32be  version           == 1
    u32be  magic             == 0x326
    u32be  subtype            1 = player profile, 2 = level
    u32be  inner length
    bytes  payload           inner length bytes of protobuf
    u32be  trailer           == 0x679 in every file seen

so the file is 24 + inner length bytes, and the first field is 4 less than that.

Level ids are ``0x40000000 + n``: the four levels on this machine are
1073741825..1073741828. The file name is the decimal level id.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
MAGIC = 0x326
TRAILER = 0x679

SUBTYPE_PLAYER = 1
SUBTYPE_LEVEL = 2

LEVEL_ID_BASE = 0x40000000

# Field numbers observed in a level descriptor. Names describe the evidence, not
# a vendor schema. Evidence for each, from the four live files:
#
#   field 39 is the creator uid -- it is 100000001 in all four, which is exactly
#     the directory they live in.
#   field 40 is a timestamp -- values 1788364733 / 1789390585 / 1789479851 /
#     1789627334 all land in September 2026, matching the files' mtimes.
#   field 2 is the name -- it decodes to the strings the editor displays.
#   field 1 is a redundant copy of the level id, and it is PRESENT ONLY IN SOME
#     FILES. The two large levels (61 KB and 21 KB) omit it entirely; the two
#     small placeholder levels carry it. So the file name, not field 1, is the
#     authoritative source of a level's id, and parse_level will not invent one.
LEVEL_FIELD_ID = 1
LEVEL_FIELD_NAME = 2
LEVEL_FIELD_CREATOR_UID = 39
LEVEL_FIELD_TIMESTAMP = 40


class ContainerError(ValueError):
    """The bytes are not a well-formed Beyond local save container."""


# --------------------------------------------------------------------------- #
# container framing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Container:
    subtype: int
    payload: bytes
    version: int = VERSION
    magic: int = MAGIC
    trailer: int = TRAILER


def decode_container(blob: bytes) -> Container:
    if len(blob) < 20:
        raise ContainerError(f"shorter than the 20-byte minimum: {len(blob)}")
    total = struct.unpack_from(">I", blob, 0)[0]
    if total != len(blob) - 4:
        raise ContainerError(f"declared length {total} != {len(blob) - 4} actual")
    version, magic, subtype, inner_len = struct.unpack_from(">IIII", blob, 4)
    if version != VERSION:
        raise ContainerError(f"unexpected version {version}")
    if magic != MAGIC:
        raise ContainerError(f"unexpected magic 0x{magic:x}, expected 0x{MAGIC:x}")
    if 20 + inner_len != total:
        raise ContainerError(f"inner length {inner_len} inconsistent with total {total}")
    payload = blob[20:20 + inner_len]
    trailer = struct.unpack_from(">I", blob, 20 + inner_len)[0]
    if trailer != TRAILER:
        raise ContainerError(f"unexpected trailer 0x{trailer:x}, expected 0x{TRAILER:x}")
    return Container(subtype=subtype, payload=payload, version=version, magic=magic, trailer=trailer)


def encode_container(container: Container) -> bytes:
    inner = container.payload
    total = 20 + len(inner)
    return (
        struct.pack(">IIIII", total, container.version, container.magic, container.subtype, len(inner))
        + inner
        + struct.pack(">I", container.trailer)
    )


# --------------------------------------------------------------------------- #
# protobuf walker -- schema-free, byte-preserving
# --------------------------------------------------------------------------- #

WIRE_VARINT = 0
WIRE_64BIT = 1
WIRE_LENGTH = 2
WIRE_32BIT = 5


@dataclass
class Field:
    """One protobuf field, with the original bytes kept either way."""
    number: int
    wire_type: int
    value: int | None = None       # wire types 0/1/5
    data: bytes | None = None      # wire type 2

    def children(self) -> list["Field"]:
        """Re-read a length-delimited field as a nested message."""
        if self.wire_type != WIRE_LENGTH or self.data is None:
            raise ContainerError(f"field {self.number} is not length-delimited")
        return parse_fields(self.data)

    def text(self) -> str:
        if self.wire_type != WIRE_LENGTH or self.data is None:
            raise ContainerError(f"field {self.number} is not length-delimited")
        return self.data.decode("utf-8")


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ContainerError("varint runs off the end of the buffer")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ContainerError("varint longer than 10 bytes")


def write_varint(value: int) -> bytes:
    if value < 0:
        raise ContainerError(f"varint must be non-negative, got {value}")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def parse_fields(buf: bytes) -> list[Field]:
    """Walk a message. Raises rather than resynchronising: a misparse must be loud."""
    fields: list[Field] = []
    pos = 0
    while pos < len(buf):
        key, pos = _read_varint(buf, pos)
        number, wire_type = key >> 3, key & 0x07
        if number == 0:
            raise ContainerError(f"field number 0 at offset {pos}")
        if wire_type == WIRE_VARINT:
            value, pos = _read_varint(buf, pos)
            fields.append(Field(number, wire_type, value=value))
        elif wire_type == WIRE_LENGTH:
            length, pos = _read_varint(buf, pos)
            if pos + length > len(buf):
                raise ContainerError(f"field {number} claims {length} bytes, only {len(buf) - pos} left")
            fields.append(Field(number, wire_type, data=buf[pos:pos + length]))
            pos += length
        elif wire_type == WIRE_64BIT:
            if pos + 8 > len(buf):
                raise ContainerError(f"field {number} truncated 64-bit value")
            fields.append(Field(number, wire_type, value=int.from_bytes(buf[pos:pos + 8], "little")))
            pos += 8
        elif wire_type == WIRE_32BIT:
            if pos + 4 > len(buf):
                raise ContainerError(f"field {number} truncated 32-bit value")
            fields.append(Field(number, wire_type, value=int.from_bytes(buf[pos:pos + 4], "little")))
            pos += 4
        else:
            raise ContainerError(f"field {number} has reserved wire type {wire_type}")
    return fields


def encode_fields(fields: list[Field]) -> bytes:
    out = bytearray()
    for f in fields:
        out += write_varint((f.number << 3) | f.wire_type)
        if f.wire_type == WIRE_VARINT:
            out += write_varint(f.value or 0)
        elif f.wire_type == WIRE_LENGTH:
            data = f.data or b""
            out += write_varint(len(data))
            out += data
        elif f.wire_type == WIRE_64BIT:
            out += (f.value or 0).to_bytes(8, "little")
        elif f.wire_type == WIRE_32BIT:
            out += (f.value or 0).to_bytes(4, "little")
        else:
            raise ContainerError(f"cannot encode wire type {f.wire_type}")
    return bytes(out)


# --------------------------------------------------------------------------- #
# the observed schema
# --------------------------------------------------------------------------- #

def _first(fields: list[Field], number: int) -> Field | None:
    for f in fields:
        if f.number == number:
            return f
    return None


def _all(fields: list[Field], number: int) -> list[Field]:
    return [f for f in fields if f.number == number]


@dataclass
class Level:
    """A level descriptor. ``raw`` keeps every field, so unknown ones survive edits."""
    level_id: int
    name: str
    creator_uid: int | None = None
    timestamp: int | None = None
    raw: list[Field] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"{self.level_id}.gil"


def parse_level(payload: bytes, level_id: int | None = None) -> Level:
    """Parse a level descriptor.

    ``level_id`` supplies the id for files that omit field 1; pass the file name's
    stem. At least one of the two must yield an id, and a field 1 that contradicts
    the file name is an error rather than something to paper over.
    """
    fields = parse_fields(payload)
    name_field = _first(fields, LEVEL_FIELD_NAME)
    if name_field is None:
        raise ContainerError("level payload lacks field 2 (name)")
    id_field = _first(fields, LEVEL_FIELD_ID)
    if id_field is not None:
        declared = id_field.value or 0
        if level_id is not None and declared != level_id:
            raise ContainerError(
                f"field 1 says level {declared} but the file is named {level_id}"
            )
        level_id = declared
    if level_id is None:
        raise ContainerError("level payload has no field 1; the file name must supply the id")
    uid_field = _first(fields, LEVEL_FIELD_CREATOR_UID)
    ts_field = _first(fields, LEVEL_FIELD_TIMESTAMP)
    return Level(
        level_id=level_id,
        name=name_field.text(),
        creator_uid=uid_field.value if uid_field else None,
        timestamp=ts_field.value if ts_field else None,
        raw=fields,
    )


def build_level(level: Level) -> bytes:
    """Re-encode a level, replacing only the name -- and field 1 only if it was there.

    A file that never carried field 1 must not gain one: the two shapes are
    produced by different writers, and adding a field to one of them is exactly the
    sort of unforced change that would make a save stop loading.
    """
    fields = []
    for f in level.raw:
        if f.number == LEVEL_FIELD_NAME:
            fields.append(Field(LEVEL_FIELD_NAME, WIRE_LENGTH, data=level.name.encode("utf-8")))
        elif f.number == LEVEL_FIELD_ID:
            fields.append(Field(LEVEL_FIELD_ID, WIRE_VARINT, value=level.level_id))
        else:
            fields.append(f)
    return encode_fields(fields)


@dataclass
class LevelRef:
    """One entry in the profile's level list."""
    level_id: int
    name: str
    timestamp: int | None = None
    flag: int | None = None
    raw: list[Field] = field(default_factory=list)


@dataclass
class Tab:
    """A 页签 -- the group a level is filed under.

    The live profile does not present its levels as one flat list. Inside
    field 1 > field 2 there are repeated field 4 entries, each naming a tab and
    holding repeated field 5 {group, level_id} pairs. On this machine:

        自定义页签_1 (kind 3) -> levels 1073741825, 1073741828
        自定义页签_2 (kind 4) -> levels 1073741826, 1073741827

    and the level names agree: every level under 页签_1 is named 自定义页签_1_...,
    every level under 页签_2 is named 自定义页签_2_.... A registration that appends
    only to the flat field 2 list therefore adds an entry the tab view does not
    know about, which is why add_level writes both.
    """
    name: str
    kind: int
    members: list[tuple[int, int]] = field(default_factory=list)  # (group, level_id)
    raw: list[Field] = field(default_factory=list)


# The group constant carried in every field 5 seen on this machine.
TAB_GROUP_DEFAULT = 1600


@dataclass
class Profile:
    """The player profile -- what the editor shows as the list of projects."""
    raw: list[Field] = field(default_factory=list)
    levels: list[LevelRef] = field(default_factory=list)
    tabs: list[Tab] = field(default_factory=list)
    trailing: int | None = None

    @property
    def root_name(self) -> str | None:
        outer = _first(self.raw, 1)
        if outer is None:
            return None
        inner = _first(outer.children(), 2)
        if inner is None:
            return None
        name = _first(inner.children(), 1)
        return name.text() if name else None


def parse_profile(payload: bytes) -> Profile:
    fields = parse_fields(payload)
    refs: list[LevelRef] = []
    for f in _all(fields, 2):
        entry = f.children()
        id_field = _first(entry, 1)
        name_field = _first(entry, 2)
        if id_field is None or name_field is None:
            continue
        ts_field = _first(entry, 3)
        flag_field = _first(entry, 5)
        refs.append(LevelRef(
            level_id=id_field.value or 0,
            name=name_field.text(),
            timestamp=ts_field.value if ts_field else None,
            flag=flag_field.value if flag_field else None,
            raw=entry,
        ))
    trailing_field = _first(fields, 3)
    return Profile(
        raw=fields,
        levels=refs,
        tabs=parse_tabs(fields),
        trailing=trailing_field.value if trailing_field and trailing_field.wire_type == WIRE_VARINT else None,
    )


def parse_tabs(profile_fields: list[Field]) -> list[Tab]:
    """Read the tab list out of field 1 > field 2 > field 4."""
    outer = _first(profile_fields, 1)
    if outer is None or outer.wire_type != WIRE_LENGTH:
        return []
    inner = _first(outer.children(), 2)
    if inner is None or inner.wire_type != WIRE_LENGTH:
        return []
    tabs: list[Tab] = []
    for entry in _all(inner.children(), 4):
        parts = entry.children()
        name = _first(parts, 1)
        kind = _first(parts, 3)
        members: list[tuple[int, int]] = []
        for pair in _all(parts, 5):
            pair_fields = pair.children()
            group = _first(pair_fields, 1)
            level_id = _first(pair_fields, 2)
            if group is not None and level_id is not None:
                members.append((group.value or 0, level_id.value or 0))
        tabs.append(Tab(
            name=name.text() if name else "",
            kind=kind.value if kind else 0,
            members=members,
            raw=parts,
        ))
    return tabs


def build_tab(tab: Tab) -> Field:
    """Re-encode one tab entry (a field 4 payload)."""
    parts = [
        Field(1, WIRE_LENGTH, data=tab.name.encode("utf-8")),
        Field(3, WIRE_VARINT, value=tab.kind),
    ]
    for group, level_id in tab.members:
        parts.append(Field(5, WIRE_LENGTH, data=encode_fields([
            Field(1, WIRE_VARINT, value=group),
            Field(2, WIRE_VARINT, value=level_id),
        ])))
    return Field(4, WIRE_LENGTH, data=encode_fields(parts))


def _replace_children(container: Field, number: int, replacements: list[Field]) -> Field:
    """Return `container` with its children of `number` swapped for `replacements`."""
    out: list[Field] = []
    inserted = False
    for child in parse_fields(container.data or b""):
        if child.number == number:
            if not inserted:
                out.extend(replacements)
                inserted = True
            continue
        out.append(child)
    if not inserted:
        out.extend(replacements)
    return Field(container.number, WIRE_LENGTH, data=encode_fields(out))


def build_profile(profile: Profile) -> bytes:
    """Re-encode a profile, replacing only the level list, the tabs, and the trailing id.

    The tabs are nested two levels down (field 1 > field 2 > field 4), so replacing
    them means rebuilding both enclosing messages. Everything else in those messages
    is carried through untouched, which is what keeps the round-trip byte-exact.
    """
    fields = []
    entries = [encode_fields(ref.raw) for ref in profile.levels]
    inserted = False
    for f in profile.raw:
        if f.number == 2:
            if not inserted:
                for entry in entries:
                    fields.append(Field(2, WIRE_LENGTH, data=entry))
                inserted = True
            continue
        if f.number == 3 and profile.trailing is not None and f.wire_type == WIRE_VARINT:
            fields.append(Field(3, WIRE_VARINT, value=profile.trailing))
            continue
        if f.number == 1 and f.wire_type == WIRE_LENGTH and profile.tabs:
            fields.append(_rebuild_tabs_holder(f, profile.tabs))
            continue
        fields.append(f)
    if not inserted:
        for entry in entries:
            fields.append(Field(2, WIRE_LENGTH, data=entry))
    return encode_fields(fields)


def _rebuild_tabs_holder(outer: Field, tabs: list[Tab]) -> Field:
    """Replace the field 4 tab entries inside field 1 > field 2."""
    rebuilt = []
    seen_root = False
    for child in parse_fields(outer.data or b""):
        if child.number == 2 and child.wire_type == WIRE_LENGTH and not seen_root:
            seen_root = True
            rebuilt.append(_replace_children(child, 4, [build_tab(t) for t in tabs]))
            continue
        rebuilt.append(child)
    if not seen_root:
        return outer
    return Field(outer.number, WIRE_LENGTH, data=encode_fields(rebuilt))


def add_level_to_profile(
    profile: Profile,
    level_id: int,
    name: str,
    timestamp: int,
    tab_name: str | None = None,
    group: int = TAB_GROUP_DEFAULT,
) -> Tab:
    """Register a level in BOTH places the profile lists it.

    Appending to the flat list alone produces a profile the tab view does not know
    about. This adds the level reference and files it under a tab, creating the tab
    if the caller names one that does not exist.
    """
    profile.levels.append(build_level_ref(level_id, name, timestamp))

    if tab_name is None:
        tab_name = f"自定义页签_{len(profile.tabs) + 1}"

    target = None
    for tab in profile.tabs:
        if tab.name == tab_name:
            target = tab
            break
    if target is None:
        kinds = [t.kind for t in profile.tabs]
        target = Tab(name=tab_name, kind=(max(kinds) + 1) if kinds else 3)
        profile.tabs.append(target)
    target.members.append((group, level_id))
    return target


def build_level_ref(level_id: int, name: str, timestamp: int, flag: int = 1) -> LevelRef:
    raw = [
        Field(1, WIRE_VARINT, value=level_id),
        Field(2, WIRE_LENGTH, data=name.encode("utf-8")),
        Field(3, WIRE_VARINT, value=timestamp),
        Field(5, WIRE_VARINT, value=flag),
    ]
    return LevelRef(level_id=level_id, name=name, timestamp=timestamp, flag=flag, raw=raw)


# --------------------------------------------------------------------------- #
# file helpers -- read-only unless told otherwise
# --------------------------------------------------------------------------- #

def read_level(path: Path) -> Level:
    """Read a level, taking the id from the file name and cross-checking field 1."""
    try:
        named_id = int(path.stem)
    except ValueError:
        named_id = None
    return parse_level(decode_container(path.read_bytes()).payload, level_id=named_id)


def read_profile(path: Path) -> Profile:
    return parse_profile(decode_container(path.read_bytes()).payload)


def write_bytes(path: Path, blob: bytes) -> None:
    """The only writer here. Callers must have a backup; see tools/editor-bridge/snapshot."""
    path.write_bytes(blob)


def next_level_id(profile: Profile) -> int:
    ids = [ref.level_id for ref in profile.levels]
    return (max(ids) + 1) if ids else (LEVEL_ID_BASE + 1)
