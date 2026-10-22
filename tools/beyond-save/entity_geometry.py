"""Read entity records and their transform geometry out of a Miliastra level ``.gil``.

READ-ONLY. This module never writes. ``read_entity_records`` only calls
``Path.read_bytes``; the container codec (``gil_container``) is used purely to
walk bytes, and its round-trip property is asserted in the tests.

Why this module exists
----------------------
`entity.transform` was listed as a top functional gap (docs/PROGRESS-BY-FUNCTION.md
§六). Before anything can move or place an object, we need to be able to *read*
back where the engine thinks objects already are. This module establishes that,
positionally, from the bytes -- no schema, no guessed field names.

The established structure (all of it from bytes; see tests)
-----------------------------------------------------------
A level payload is a protobuf message (``gil_container.parse_fields``). The
entity table is a **repeated root field 5**. Every child of root field 5 in the
files seen is a ``field 1``-wrapped message -- one entity record:

    root field 5                       entity table, one entry per entity
      entry field 1  (varint)          integer id (e.g. 1094713345)
      entry field 2  (message)         {1: <int>, 2: <int>}
      entry field 5,6,7 (messages)     component groups; each child is a
                                       wrapper {1: <kind>, <P>: <payload>}
      entry field 8  (varint)          a tag int (e.g. 10003004, 1000000)

Inside the wrapper, ``<P>`` is a *fixed* function of ``kind`` -- measured over
479 entities of level 1073741841, every observed ``(group, kind)`` pair maps to
exactly one payload field number. Group 6 happens to map to ``kind + 10``; the
other groups do not follow a single rule (group 5 kind 3 -> field 12 but kind 13
-> field 22, group 7 kind 40 -> field 51), so this module records the pair rather
than deriving it.

The transform lives at one exact address, present on every entity in the sample:

    root field 5 > entry field 6 > wrapper kind 1 > wrapper field 11

and that payload is a message with three length-delimited sub-messages plus one
trailing varint:

    field 1  message  the three sub-fields 1,2,3 are all float32 (wire type 5)
    field 2  message  only sub-field 2 is ever present in the sample
    field 3  message  sub-fields 1,2,3 all present, values ~1.0
    field 501 varint  present on every record (value 0xFFFFFFFF = 4294967295,
                      proto3's "unset" uint32, in all 12 records here)

Reading those as (position, rotation, scale) is an *interpretation*, justified
by: field 3 is a 3-float vector whose value is (1,1,1) for an untouched entity
== identity scale; field 2 carries a single degree-like value (20.0, 45.0) on
records that look rotated; field 1 is a free 3-float vector. The code keeps the
positional form (``vectors[1]``, ``vectors[2]``, ``vectors[3]``) as the source of
truth and exposes ``position``/``rotation``/``scale`` as documented aliases.

Missing float components are zero, not absent-by-error: proto3 omits zero-valued
fields, so a vector whose y is 0 arrives as ``{1: x, 3: z}``. ``Vec.triple``
therefore pads with 0.0 -- this is the "按 0 补" rule recorded in
``.claude memory gil-level-file-is-decodable``.

Worked byte offsets (real file, 1073741842.gil, size 28383)
-----------------------------------------------------------
Container header is 20 bytes, so file offset = 20 + payload offset.

    file 0x04E4 = 1252   root field 5 key byte (0x2A), value at 1255 (3748 B)
    file 1450            entry #1 value; first bytes 08 81 80 80 86 04 -> id
    file 1580            entry #1, group-6 wrapper value
    file 1584            group-6 wrapper field 11 (the transform), 33 B
    file 1587            transform field 1 -> sub-field 2 float
                         0x0000FA44 = 2000.0f   (this entity's y)
    file 1601            transform field 3 -> sub-field 2  0x0000803F = 1.0f
    file 1612            transform field 501 varint

What repeats per entity / what does not (measured, 1073741842.gil, 12 entities)
-------------------------------------------------------------------------------
REPEATS on all 12: entry sub-field numbers are exactly {1, 2, 5, 6, 7, 8};
the transform (group 6, kind 1, field 11) with a field-3 vector of (1,1,1);
group 5 kind 1, group 5 kind 19, group 5 kind 111, group 6 kind 3,
group 7 kind 1, group 7 kind 3.

DOES NOT repeat: entry field 1 (the id) and field 8; the *set* of group-5/6/7
kinds and their payload lengths (e.g. entry 2 carries a 997-byte group-5/kind-3
payload while entry 0 carries 189 bytes total); the transform's field-1/field-2
vectors (present only when non-zero); every group-5 kind above 19 and every
group-6 kind from 2 upward appears on a subset only.

The full per-file census is produced by :func:`summarize`.

What could NOT be established -- reported as negative results
-------------------------------------------------------------
* The numeric ``kind`` values and the payload field numbers are positional only.
  No public name (collider, model, script, ...) is asserted for any of them; the
  bytes do not carry a name we could check.
* **Root field 6 is not entity geometry.** In 1073741842.gil it holds 42
  ``field 1`` entries, each ``{1: <small int>, 2: {1: "root", 3: 1},
  3: {1: <name>, 3: 2, 5: {1,2}}}`` with names like ``未分类页签``/``玩家模板``/
  ``职业`` -- a page/template directory, not positions. It grew 40 -> 42 across
  two saves (docs/PROGRESS-BY-FUNCTION.md §四), but that growth is directory
  entries, not entities, so it is out of scope here.
* **Root field 46 is not entity geometry either.** It is two entries of
  ``{1: <u64>, 2: <u64>}`` (44 bytes total) -- two opaque 64-bit pairs.
* The comparison level ``1073741826.gil`` (79 bytes) carries **no root field 5
  at all**, so it has zero entity records; it is not a useful geometric
  comparison, only a negative control (placeholder levels carry fields
  1,2,34,39,40,41,42 and nothing else).
* Only the transform (group 6, kind 1) payload is decoded. The other 30-odd
  ``(group, kind)`` pairs are reported positionally -- kind, payload field
  number, and raw bytes -- but no meaning is claimed for them.

Nothing here fixes entity ids or level ids as constants -- see
``.claude memory entity-id-reused-across-levels`` and ``level-ids-are-per-save``.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import gil_container as gc

# --------------------------------------------------------------------------- #
# positional constants -- every one is a field number read off real bytes, not a
# vendor name. The doc comment above records what justifies each.
# --------------------------------------------------------------------------- #

ENTITY_TABLE_FIELD = 5          # root field holding the repeated entity records
ENTRY_ID_FIELD = 1              # entry field 1 -- the integer id
ENTRY_REF_FIELD = 2             # entry field 2 -- {1: int, 2: int}
ENTRY_TAG_FIELD = 8             # entry field 8 -- an integer tag
COMPONENT_GROUPS = (5, 6, 7)    # entry fields whose children are component wrappers

TRANSFORM_GROUP = 6             # component group that holds the transform
TRANSFORM_KIND = 1             # the wrapper's field-1 value for the transform
TRANSFORM_PAYLOAD_FIELD = 11    # the wrapper field that carries the transform
TRANSFORM_VECTOR_FIELDS = (1, 2, 3)   # sub-messages of the transform message

WIRE_FLOAT32 = 5

# Absolute offset of the protobuf payload inside the file: the container header
# (total/version/magic/subtype/inner_len) is 20 bytes. See gil_container.
CONTAINER_HEADER = 20


class EntityGeometryError(gc.ContainerError):
    """The file is not a level ``.gil`` we can read entity records from."""


# --------------------------------------------------------------------------- #
# offset-aware field walk
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FieldRef:
    """A parsed field plus where it sits: key byte and value bytes, absolute."""
    field: gc.Field
    key_offset: int
    value_offset: int

    @property
    def number(self) -> int:
        return self.field.number

    @property
    def wire_type(self) -> int:
        return self.field.wire_type

    @property
    def data(self) -> bytes | None:
        return self.field.data

    @property
    def value(self) -> int | None:
        return self.field.value


def walk_fields(buf: bytes, base: int = 0) -> list[FieldRef]:
    """Like ``gil_container.parse_fields`` but keeps each field's byte offsets.

    ``base`` is the absolute offset of ``buf``'s first byte, so offsets come back
    absolute in whatever coordinate the caller is tracking (we pass the file
    offset). The parsed fields are identical to ``parse_fields(buf)`` -- asserted
    by the tests -- so ``encode_fields([r.field for r in walk_fields(b, 0)]) == b``.
    """
    out: list[FieldRef] = []
    pos = 0
    n = len(buf)
    while pos < n:
        start = pos
        key, pos = gc._read_varint(buf, pos)
        number, wire_type = key >> 3, key & 0x07
        if number == 0:
            raise gc.ContainerError(f"field number 0 at offset {base + pos}")
        if wire_type == gc.WIRE_VARINT:
            value_off = pos
            value, pos = gc._read_varint(buf, pos)
            out.append(FieldRef(gc.Field(number, wire_type, value=value), base + start, base + value_off))
        elif wire_type == gc.WIRE_LENGTH:
            length, pos = gc._read_varint(buf, pos)
            if pos + length > n:
                raise gc.ContainerError(
                    f"field {number} claims {length} bytes, only {n - pos} left")
            value_off = pos
            data = buf[pos:pos + length]
            pos += length
            out.append(FieldRef(gc.Field(number, wire_type, data=data), base + start, base + value_off))
        elif wire_type == gc.WIRE_64BIT:
            if pos + 8 > n:
                raise gc.ContainerError(f"field {number} truncated 64-bit value")
            value_off = pos
            value = int.from_bytes(buf[pos:pos + 8], "little")
            pos += 8
            out.append(FieldRef(gc.Field(number, wire_type, value=value), base + start, base + value_off))
        elif wire_type == gc.WIRE_32BIT:
            if pos + 4 > n:
                raise gc.ContainerError(f"field {number} truncated 32-bit value")
            value_off = pos
            value = int.from_bytes(buf[pos:pos + 4], "little")
            pos += 4
            out.append(FieldRef(gc.Field(number, wire_type, value=value), base + start, base + value_off))
        else:
            raise gc.ContainerError(f"field {number} has reserved wire type {wire_type}")
    return out


# --------------------------------------------------------------------------- #
# the decoded record shape
# --------------------------------------------------------------------------- #

@dataclass
class Vec:
    """A 3-float vector as it actually appears: component number -> float32.

    Only the components that were written are keys; ``triple`` fills the rest
    with 0.0 (proto3 drops zero-valued fields).
    """
    components: dict[int, float] = dc_field(default_factory=dict)

    def get(self, component: int, default: float = 0.0) -> float:
        return self.components.get(component, default)

    def triple(self) -> tuple[float, float, float]:
        return (self.get(1), self.get(2), self.get(3))

    @property
    def is_zero(self) -> bool:
        return all(v == 0.0 for v in self.components.values())

    def __str__(self) -> str:  # stable repr for reports
        if not self.components:
            return "(0, 0, 0)"
        parts = ", ".join(f"{k}:{v:g}" for k, v in sorted(self.components.items()))
        return "{" + parts + "}"


@dataclass
class Transform:
    """The message at root5/entry6/wrapperKind1/field11, kept positional."""
    vector_fields: dict[int, Vec] = dc_field(default_factory=dict)
    scalar_fields: dict[int, int] = dc_field(default_factory=dict)

    def vector(self, number: int) -> Vec:
        return self.vector_fields.get(number, Vec())

    # Documented interpretation of the three positional vectors. See module doc.
    @property
    def position(self) -> Vec:
        return self.vector(TRANSFORM_VECTOR_FIELDS[0])

    @property
    def rotation(self) -> Vec:
        return self.vector(TRANSFORM_VECTOR_FIELDS[1])

    @property
    def scale(self) -> Vec:
        return self.vector(TRANSFORM_VECTOR_FIELDS[2])


@dataclass
class Component:
    """One entry of an entity's group-5/6/7 list: ``{1: kind, <payload_field>: ...}``."""
    group: int
    kind: int | None
    payload_field: int | None
    payload: gc.Field | None
    payload_offset: int = -1
    raw: list[gc.Field] = dc_field(default_factory=list)

    @property
    def payload_len(self) -> int:
        return len(self.payload.data) if self.payload and self.payload.data is not None else 0


@dataclass
class EntityRecord:
    """One entity: a ``field 1`` entry of root field 5."""
    index: int
    key_offset: int
    value_offset: int
    fields: list[gc.Field] = dc_field(default_factory=list)
    components: list[Component] = dc_field(default_factory=list)
    transform: Transform | None = None

    @property
    def entity_id(self) -> int | None:
        """Value of entry field 1 -- the integer id (e.g. 1094713345)."""
        f = gc._first(self.fields, ENTRY_ID_FIELD)
        return f.value if f is not None else None

    @property
    def ref(self) -> dict[int, int]:
        """Entry field 2 read as ``{1: int, 2: int}`` (empty if absent)."""
        f = gc._first(self.fields, ENTRY_REF_FIELD)
        if f is None or f.wire_type != gc.WIRE_LENGTH or f.data is None:
            return {}
        return {c.number: c.value for c in gc.parse_fields(f.data) if c.wire_type == gc.WIRE_VARINT}

    @property
    def tag(self) -> int | None:
        """Value of entry field 8 -- the integer tag."""
        f = gc._first(self.fields, ENTRY_TAG_FIELD)
        return f.value if f is not None else None

    @property
    def raw_bytes(self) -> bytes:
        """The exact bytes of this record's message body (parse -> encode)."""
        return gc.encode_fields(self.fields)

    def component(self, group: int, kind: int) -> Component | None:
        for c in self.components:
            if c.group == group and c.kind == kind:
                return c
        return None

    @property
    def signature(self) -> tuple[tuple[int, int | None], ...]:
        """The ``(group, kind)`` pairs present, sorted -- the record's shape."""
        return tuple(sorted((c.group, c.kind) for c in self.components))


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #

def _make_vec(field: gc.Field) -> Vec:
    """Read a length-delimited sub-message as component-number -> float32."""
    out: dict[int, float] = {}
    if field.wire_type != gc.WIRE_LENGTH or field.data is None:
        return Vec(out)
    for child in gc.parse_fields(field.data):
        if child.wire_type == WIRE_FLOAT32 and child.value is not None:
            out[child.number] = struct.unpack("<f", child.value.to_bytes(4, "little"))[0]
    return Vec(out)


def _make_component(group: int, ref: FieldRef) -> Component:
    kids = gc.parse_fields(ref.data or b"")
    kind = kids[0].value if kids and kids[0].number == 1 and kids[0].wire_type == gc.WIRE_VARINT else None
    payload: gc.Field | None = None
    payload_field: int | None = None
    for child in kids:
        if child.number != 1:
            payload = child
            payload_field = child.number
            break
    # payload value bytes offset: wrapper value + key byte + (length varint).
    payload_offset = -1
    if payload is not None:
        inner = walk_fields(ref.data or b"", ref.value_offset)
        for child in inner:
            if child.number == payload_field:
                payload_offset = child.value_offset
                break
    return Component(group=group, kind=kind, payload_field=payload_field,
                     payload=payload, payload_offset=payload_offset, raw=kids)


def _make_transform(wrapper: Component) -> Transform | None:
    if wrapper.payload is None or wrapper.payload.wire_type != gc.WIRE_LENGTH:
        return None
    tf = Transform()
    for child in gc.parse_fields(wrapper.payload.data or b""):
        if child.wire_type == gc.WIRE_LENGTH and child.number in TRANSFORM_VECTOR_FIELDS:
            tf.vector_fields[child.number] = _make_vec(child)
        elif child.wire_type == gc.WIRE_VARINT and child.value is not None:
            tf.scalar_fields[child.number] = child.value
    return tf


def read_entity_records(path: str | Path) -> list[EntityRecord]:
    """Read every entity record from a level ``.gil``.

    Returns ``[]`` -- not an error -- for a level that has no root field 5 (the
    small placeholder levels do not). Raises :class:`EntityGeometryError` if the
    file is not a level container. Read-only: only ``read_bytes`` is called.
    """
    blob = Path(path).read_bytes()
    return read_entity_records_blob(blob, source=str(path))


def read_entity_records_blob(blob: bytes, source: str = "<bytes>") -> list[EntityRecord]:
    """Same as :func:`read_entity_records` but on an in-memory blob.

    Split out so an *edited* payload can be re-decoded without ever touching the
    filesystem -- the in-memory round-trip tests in ``test_component_edit.py`` use
    this, and nothing here writes. Read-only: only reads ``blob``.
    """
    container = gc.decode_container(blob)          # raises on a malformed container
    if container.subtype != gc.SUBTYPE_LEVEL:
        raise EntityGeometryError(
            f"{source} is container subtype {container.subtype}, not a level (2)")

    root = walk_fields(container.payload, CONTAINER_HEADER)
    table = next((r for r in root if r.number == ENTITY_TABLE_FIELD), None)
    if table is None or table.data is None:
        return []

    records: list[EntityRecord] = []
    for index, entry in enumerate(walk_fields(table.data, table.value_offset)):
        if entry.wire_type != gc.WIRE_LENGTH or entry.data is None:
            continue
        fields = gc.parse_fields(entry.data)
        record = EntityRecord(
            index=index,
            key_offset=entry.key_offset,
            value_offset=entry.value_offset,
            fields=fields,
        )
        for child in walk_fields(entry.data, entry.value_offset):
            if child.number in COMPONENT_GROUPS:
                record.components.append(_make_component(child.number, child))
        wrapper = record.component(TRANSFORM_GROUP, TRANSFORM_KIND)
        if wrapper is not None:
            record.transform = _make_transform(wrapper)
        records.append(record)
    return records


def summarize(records: list[EntityRecord]) -> dict:
    """Census of what repeats per entity and what does not, for reporting.

    Returns a dict with:
      ``entities``      number of records
      ``component``     ``(group, kind) -> count`` of entities carrying it
      ``universal``     the ``(group, kind)`` pairs present on *every* entity
      ``transform``     how many entities expose a transform and how many carry
                        each transform vector field
      ``signatures``    distinct record shapes and how many entities have each
    """
    from collections import Counter

    total = len(records)
    component: Counter = Counter()
    for r in records:
        for c in r.components:
            component[(c.group, c.kind)] += 1

    universal = sorted(k for k, n in component.items() if total and n == total)

    has_tf = sum(1 for r in records if r.transform is not None)
    tf_vectors: Counter = Counter()
    tf_scalars: Counter = Counter()
    for r in records:
        if r.transform is None:
            continue
        for n in r.transform.vector_fields:
            tf_vectors[n] += 1
        for n in r.transform.scalar_fields:
            tf_scalars[n] += 1

    signatures: Counter = Counter(r.signature for r in records)

    return {
        "entities": total,
        "component": dict(sorted(component.items())),
        "universal": universal,
        "transform": {
            "present": has_tf,
            "vector_fields": dict(sorted(tf_vectors.items())),
            "scalar_fields": dict(sorted(tf_scalars.items())),
        },
        "signatures": signatures,
    }
