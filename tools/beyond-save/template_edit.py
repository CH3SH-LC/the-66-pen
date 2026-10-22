"""**In-memory only** editor for the template records of a level ``.gil``.

READ the module name before using it: this module **can not write a save**. Every
function takes ``bytes`` and returns ``bytes`` (or plain data); there is no path,
no ``open()``, no ``write_bytes``. Persisting the returned bytes is a separate,
deliberate step somebody else owns -- and per ``CLAUDE.md`` §一 the project has no
sanctioned writer for a level ``.gil`` at all. This module exists to answer a
**question about the bytes**, not to produce a save:

    Does the save's own template table admit ONE extra record, and if so exactly
    which bytes change and by how much?

It is the template-side twin of :mod:`component_edit` (which did the same for one
entity's component wrapper: a byte-exact in-memory round trip, a minimal added
record, and an exact file delta).

Where the record lives -- DERIVED, not assumed
---------------------------------------------
The task explicitly forbids assuming "field 15". The home of a template record is
derived here two independent ways, both re-runnable read-only:

1. **Container structure.** Every real level payload was walked
   (``gil_container.parse_fields``) and the *only* root field whose records are
   ``{1: <numeric id>, 2: <int>, 4*: <component block>}`` with a **printable name
   inside component kind 1** is **root field 15**. How many files carry it, their
   sizes, and their entry totals are a **property of the save files on this
   machine, not of this code** -- the game rewrites them, so they drift between
   checkouts. They are deliberately **not frozen** here; re-derive them by running
   :func:`read_templates` over ``.../BeyondLocal/100000001/**/*.gil``.
2. **Typed-id census.** The entry's field-1 value carries its own type in the
   high bits: ``type = (id >> 22) - 256``. Which types appear is likewise a
   **snapshot of the assets the save files currently hold** -- the owner creating
   an asset adds a type -- so the set is a property of the save, not a constant of
   this code. Field 15 is therefore a registry of *named, typed* assets, and
   the type-11 id ``1119879169`` (道具背包, per the official ID-type table
   ``docs/official-docs/chapters/mhsd6lrxvoe.json:66``: 11 = 1119879168..1124073471)
   is the "背包模板" template. Cross-check: the same id also appears as a
   ``field 6`` directory pointer tagged with resource group ``3800`` (StuffBag).

This matches the prior finding recorded in
``docs/research/reverse-eng-20261010/TEMPLATE-SAVE-WRITE.md`` §3.2 and
``TEMPLATE-STORAGE.md`` §2.3 (both 2026-10-10); this module re-derives it from
the current checkout rather than quoting it.

The record's minimal form (measured, not guessed)
-------------------------------------------------
An entry is a plain protobuf message; ``{1: <id>}`` alone is a well-formed entry.
But every *real* entry carries ``{1, 2, 4*}`` -- field 4 repeated once or more --
and the name only exists as a component block (kind 1 -> payload field 11 ->
field 1 = UTF-8); a few 自定义职业 entries add one trailing field 5. So this
module offers BOTH:

* :func:`minimal_entry_bytes` -- ``{1: id}``, the byte floor (6 B for a type-11
  id; 8 B added to the file once the ``field 1`` key+length are counted). Recorded
  as the lower bound the task asked for, **not** claimed to be engine-honoured.
* :func:`build_entry` -- the canonical shape ``{1: id, 2: kind, 4: {1: 1,
  11: {1: name}}, ...}`` mirroring the real 46 B type-11 donor.

Payload-field rule -- a CENSUS, not a formula
---------------------------------------------
Inside a component block ``{1: kind, <P>: payload}`` the payload field ``P`` is a
*function of kind* that is **not** ``kind + 10`` outside kind 1. Measured over
every real entry in the save files on this machine:

    kind  1 -> 11     kind  8 -> 16     kind  9 -> 17     kind 10 -> 18
    kind 11 -> 19     kind 12 -> 20     kind 24 -> 33     kind 25 -> 34
    kind 26 -> 35     kind 27 -> 36     kind 42 -> 55     kind 43 -> 51
    kind 48 -> 58     kind 51 -> 61     kind 70 -> 75     kind 101 -> 90
    kind 102 -> 91

Only kind 1 happens to satisfy ``kind + 10``. Like the type set above, this table
is a **snapshot of the current save files, not a constant** -- new kinds appear as
the owner makes new assets, so re-derive it rather than trusting the list. Then
:func:`payload_field_for` returns a value from this measured table and **raises**
for any unmeasured kind -- it does not interpolate. (Same discipline as
:mod:`component_edit`, where group 5/7 need an explicit payload field because no
rule holds.)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gil_container import (  # noqa: E402
    WIRE_LENGTH,
    WIRE_VARINT,
    Container,
    Field,
    decode_container,
    encode_container,
    encode_fields,
    parse_fields,
)

# --- positional constants (all read off real bytes; see module doc) --------- #
TEMPLATE_TABLE_FIELD = 15       # root field holding the repeated template records
ENTRY_ID_FIELD = 1              # entry field 1 -- the typed asset id (varint)
ENTRY_KIND_FIELD = 2            # entry field 2 -- the small int beside the id
ENTRY_BLOCK_FIELD = 4           # entry field 4 -- one component block (repeated)
ENTRY_TAIL_FIELD = 5            # entry field 5 -- seen once per 自定义职业 entry

BLOCK_COMPONENT_FIELD = 1       # a block's field 1 -- the component kind
NAME_BLOCK_KIND = 1             # the block kind that carries the display name
NAME_PAYLOAD_FIELD = 11         # kind-1 block's payload field (measured)
NAME_TEXT_FIELD = 1             # inside the name payload -- the UTF-8 string

#: ``type(id) = (id >> 22) - 256`` -- the official "ID type" encoding. Verified
#: against real entries: type 4/5/11 match 自定义职业/自定义成长曲线/背包模板, 27 is the
#: 环境配置 band. Which types exist is a property of the save, not of this code.
ID_TYPE_SHIFT = 22
ID_TYPE_OFFSET = 256

#: kind -> payload field INSIDE a component block. Measured across the real
#: entries of the current save files -- a SNAPSHOT of them, NOT a formula and NOT
#: a constant (a new asset type adds a row). Unlisted kinds must pass
#: ``payload_field``.
BLOCK_PAYLOAD_FIELDS: dict[int, int] = {
    1: 11, 8: 16, 9: 17, 10: 18, 11: 19, 12: 20,
    24: 33, 25: 34, 26: 35, 27: 36, 42: 55, 43: 51,
    48: 58, 51: 61, 70: 75, 101: 90, 102: 91,
}

#: The real 46 B type-11 donor ("背包模板", id 1119879169) as it sits in the file --
#: kept verbatim so a caller can clone a byte-real record instead of synthesising.
DONOR_TYPE_11_ID = 1119879169
DONOR_TYPE_11_ENTRY_HEX = (
    "088180809604100c221208015a0e0a0ce8838ce58c85e6a8a1e69dbf"
    "2210082aba030b0a09080a1a0518fe212200"
)


class TemplateEditError(ValueError):
    """The bytes are not a level whose template table we can edit."""


def id_type(template_id: int) -> int:
    """The official ID type of a template id: ``(id >> 22) - 256``."""
    return (template_id >> ID_TYPE_SHIFT) - ID_TYPE_OFFSET


def entry_id(entry_fields: list[Field]) -> int | None:
    """The id of an entry, from its PARSED BODY: the first field NUMBER 1.

    Scans for field 1 rather than reading ``[0]``: a protobuf message may order
    its fields freely, so a body that does not LEAD with field 1 would otherwise
    read as id-less and let a duplicate slip past a positional guard.  Every real
    entry happens to lead with field 1, but the guard must not depend on that
    accident.  The template store reads an entry's id here -- ``read_templates``,
    ``add_template``'s duplicate check and ``remove_template`` all call it -- so
    there is one rule, never a positional one.

    Returns ``None`` when the body carries no field 1.
    """
    f = next((c for c in entry_fields if c.number == ENTRY_ID_FIELD), None)
    return f.value if f is not None else None


def payload_field_for(kind: int) -> int:
    """The block payload field number for ``kind`` -- from the measured census.

    Raises for a kind that never appeared in a real entry; there is no rule to
    interpolate from (kind 1 alone is ``kind + 10``, kind 8 is ``kind + 8``,
    kind 42 is ``kind + 13``).
    """
    try:
        return BLOCK_PAYLOAD_FIELDS[kind]
    except KeyError:
        raise TemplateEditError(
            f"kind {kind} has no measured payload field; pass payload_field explicitly"
        ) from None


@dataclass(frozen=True)
class Template:
    """One decoded entry of the template table."""
    index: int
    template_id: int
    kind: int | None            # entry field 2
    name: str | None            # component kind 1 -> payload 11 -> field 1
    entry_bytes: bytes          # the raw entry body (parse -> encode)
    fields: list[Field] = dc_field(default_factory=list, compare=False)

    @property
    def id_type(self) -> int:
        return id_type(self.template_id)

    @property
    def component_kinds(self) -> tuple[int, ...]:
        """The ``field 1`` kinds of every ``field 4`` component block."""
        out = []
        for f in self.fields:
            if f.number != ENTRY_BLOCK_FIELD or f.wire_type != WIRE_LENGTH:
                continue
            kids = parse_fields(f.data or b"")
            if kids and kids[0].number == BLOCK_COMPONENT_FIELD:
                out.append(kids[0].value or 0)
        return tuple(out)


@dataclass(frozen=True)
class TemplateEdit:
    """What an in-memory edit produced: the new bytes plus the exact diff facts."""
    blob: bytes                 # the re-encoded level (NOT written anywhere)
    template_id: int
    added_bytes: bytes          # the appended ``field 1`` (key + len + entry body)
    entry_bytes: bytes          # the bare entry body {1: id, ...}
    table_len_before: int       # root field 15 value length before
    table_len_after: int        # root field 15 value length after
    entry_count_before: int
    entry_count_after: int

    @property
    def byte_delta(self) -> int:
        """Exact file-size growth (== length of the appended ``field 1``)."""
        return len(self.added_bytes)

    @property
    def table_delta(self) -> int:
        """Growth of the root field-15 value body (the entry nests inside it)."""
        return self.table_len_after - self.table_len_before


# --------------------------------------------------------------------------- #
# entry construction
# --------------------------------------------------------------------------- #

def build_name_block(name: str) -> Field:
    """The component block that carries an entry's display name (kind 1)."""
    payload = Field(NAME_TEXT_FIELD, WIRE_LENGTH, data=name.encode("utf-8"))
    return Field(ENTRY_BLOCK_FIELD, WIRE_LENGTH, data=encode_fields([
        Field(BLOCK_COMPONENT_FIELD, WIRE_VARINT, value=NAME_BLOCK_KIND),
        Field(NAME_PAYLOAD_FIELD, WIRE_LENGTH, data=encode_fields([payload])),
    ]))


def build_block(kind: int, payload: bytes = b"", payload_field: int | None = None) -> Field:
    """One generic component block ``{1: kind, <P>: payload}``.

    ``payload`` may be empty -- real entries carry 0-length blocks (the donor's
    trailing ``2200`` is exactly that).
    """
    if kind < 1:
        raise TemplateEditError(f"kind must be positive, got {kind}")
    if payload_field is None:
        payload_field = payload_field_for(kind)
    if payload_field < 1 or payload_field == BLOCK_COMPONENT_FIELD:
        raise TemplateEditError(f"payload field must be >1, got {payload_field}")
    return Field(ENTRY_BLOCK_FIELD, WIRE_LENGTH, data=encode_fields([
        Field(BLOCK_COMPONENT_FIELD, WIRE_VARINT, value=kind),
        Field(payload_field, WIRE_LENGTH, data=payload),
    ]))


def minimal_entry_bytes(template_id: int) -> bytes:
    """The byte FLOOR for an entry: ``{1: id}``. 6 B for a type-11 id.

    Kept separate from :func:`build_entry` because the floor is a *lower bound*,
    not the shape real records use -- no real entry lacks field 2 / field 4.
    """
    if template_id < 1:
        raise TemplateEditError(f"template id must be positive, got {template_id}")
    return encode_fields([Field(ENTRY_ID_FIELD, WIRE_VARINT, value=template_id)])


def build_entry(
    template_id: int,
    kind: int | None = None,
    name: str | None = None,
    blocks: tuple[Field, ...] = (),
) -> bytes:
    """The CANONICAL entry body ``{1: id, 2: kind, 4*: blocks, [name block]}``.

    Mirrors the real records: field 1, then field 2, then the component blocks
    (name block first, matching the donor), then any extra blocks. A caller that
    wants the exact donor bytes should use :data:`DONOR_TYPE_11_ENTRY_HEX` /
    :func:`clone_entry` instead.
    """
    if template_id < 1:
        raise TemplateEditError(f"template id must be positive, got {template_id}")
    fields: list[Field] = [Field(ENTRY_ID_FIELD, WIRE_VARINT, value=template_id)]
    if kind is not None:
        fields.append(Field(ENTRY_KIND_FIELD, WIRE_VARINT, value=kind))
    if name is not None:
        fields.append(build_name_block(name))
    fields.extend(blocks)
    return encode_fields(fields)


def clone_entry(entry: bytes, template_id: int | None = None, name: str | None = None) -> bytes:
    """Re-id (and optionally re-name) a REAL entry, keeping every other byte.

    This is the byte-grounded route recorded as PLAUSIBLE in
    ``TEMPLATE-SAVE-WRITE.md`` §6 #4: take a record the engine itself wrote and
    change only its identity. ``template_id`` replaces field 1, ``name`` replaces
    the kind-1 block's text. Nothing else is touched.
    """
    fields = parse_fields(entry)
    out: list[Field] = []
    for f in fields:
        if f.number == ENTRY_ID_FIELD and f.wire_type == WIRE_VARINT and template_id is not None:
            out.append(Field(ENTRY_ID_FIELD, WIRE_VARINT, value=template_id))
        elif name is not None and f.number == ENTRY_BLOCK_FIELD and f.wire_type == WIRE_LENGTH:
            kids = parse_fields(f.data or b"")
            if kids and kids[0].number == BLOCK_COMPONENT_FIELD and kids[0].value == NAME_BLOCK_KIND:
                out.append(build_name_block(name))
            else:
                out.append(f)
        else:
            out.append(f)
    return encode_fields(out)


# --------------------------------------------------------------------------- #
# reading / editing
# --------------------------------------------------------------------------- #

def _table_index(root: list[Field]) -> int:
    idx = [i for i, f in enumerate(root) if f.number == TEMPLATE_TABLE_FIELD]
    if not idx:
        raise TemplateEditError("level payload has no root field 15 (template table)")
    if len(idx) > 1:
        raise TemplateEditError(
            f"root field 15 appears {len(idx)} times -- refusing to guess which is the table")
    return idx[0]


def _decode_entries(table_value: bytes) -> list[Field]:
    return [f for f in parse_fields(table_value) if f.number == ENTRY_ID_FIELD]


def _entry_name(entry_fields: list[Field]) -> str | None:
    for f in entry_fields:
        if f.number != ENTRY_BLOCK_FIELD or f.wire_type != WIRE_LENGTH:
            continue
        kids = parse_fields(f.data or b"")
        if not kids or kids[0].number != BLOCK_COMPONENT_FIELD or kids[0].value != NAME_BLOCK_KIND:
            continue
        for payload in kids[1:]:
            if payload.wire_type != WIRE_LENGTH:
                continue
            for text in parse_fields(payload.data or b""):
                if text.number == NAME_TEXT_FIELD and text.wire_type == WIRE_LENGTH:
                    try:
                        return (text.data or b"").decode("utf-8")
                    except UnicodeDecodeError:
                        return None
    return None


def read_templates(blob: bytes) -> list[Template]:
    """Read every template record from a level ``.gil``. Read-only.

    Raises :class:`TemplateEditError` if the payload is not a level or has no
    root field 15. A level with an *empty* table returns ``[]``.
    """
    container = decode_container(blob)
    if container.subtype != 2:
        raise TemplateEditError(f"container subtype {container.subtype} is not a level (2)")
    root = parse_fields(container.payload)
    table = root[_table_index(root)]
    out: list[Template] = []
    for index, e in enumerate(_decode_entries(table.data or b"")):
        entry_fields = parse_fields(e.data or b"")
        eid = entry_id(entry_fields)
        kindf = next((c for c in entry_fields if c.number == ENTRY_KIND_FIELD), None)
        out.append(Template(
            index=index,
            template_id=eid if eid is not None else 0,
            kind=kindf.value if kindf else None,
            name=_entry_name(entry_fields),
            entry_bytes=e.data or b"",
            fields=entry_fields,
        ))
    return out


def add_template(blob: bytes, template_id: int, entry: bytes | None = None) -> TemplateEdit:
    """Return a NEW level blob with one template record appended to root field 15.

    Pure function: ``blob`` in, new ``bytes`` out. Nothing is written.

    ``entry`` is the bare entry body to append; when omitted the byte-floor
    ``{1: id}`` is used (see :func:`minimal_entry_bytes`). The record is appended
    as a new repeated ``field 1`` at the END of the existing field-15 value, so
    the root field order is preserved and no new root field appears. The only
    other byte changes are the enclosing length varints (field-15 value, container
    inner length, container total length) being recomputed -- every other byte is
    carried through untouched, which the tests assert by excising the added record
    and re-encoding to the original blob.
    """
    container = decode_container(blob)
    if container.subtype != 2:
        raise TemplateEditError(f"container subtype {container.subtype} is not a level (2)")

    root = parse_fields(container.payload)
    ti = _table_index(root)
    table_value = root[ti].data or b""

    existing = _decode_entries(table_value)
    for wrapper in existing:
        if entry_id(parse_fields(wrapper.data or b"")) == template_id:
            raise TemplateEditError(
                f"template id {template_id} already present -- refusing to duplicate")

    body = entry if entry is not None else minimal_entry_bytes(template_id)
    # positive check: the body must be a message whose field 1 is the id we claim
    body_fields = parse_fields(body)
    idf = next((f for f in body_fields if f.number == ENTRY_ID_FIELD), None)
    if idf is None or idf.value != template_id:
        raise TemplateEditError(
            f"entry body's field 1 ({idf.value if idf else None}) != template_id {template_id}")

    new_table = table_value + encode_fields([Field(ENTRY_ID_FIELD, WIRE_LENGTH, data=body)])
    root[ti] = Field(TEMPLATE_TABLE_FIELD, WIRE_LENGTH, data=new_table)

    new_blob = _encode_container(container, encode_fields(root))
    return TemplateEdit(
        blob=new_blob,
        template_id=template_id,
        added_bytes=new_table[len(table_value):],
        entry_bytes=body,
        table_len_before=len(table_value),
        table_len_after=len(new_table),
        entry_count_before=len(existing),
        entry_count_after=len(_decode_entries(new_table)),
    )


def remove_template(blob: bytes, template_id: int) -> bytes:
    """Return a NEW level blob with the entry ``template_id`` removed. Read-only.

    Used by the tests to prove *every other byte is carried through*: excising the
    added record and re-encoding must reproduce the pre-edit blob exactly.
    """
    container = decode_container(blob)
    if container.subtype != 2:
        raise TemplateEditError(f"container subtype {container.subtype} is not a level (2)")
    root = parse_fields(container.payload)
    ti = _table_index(root)
    table_value = root[ti].data or b""
    kept: list[Field] = []
    found = False
    for f in parse_fields(table_value):
        if f.number == ENTRY_ID_FIELD and f.wire_type == WIRE_LENGTH and f.data:
            if entry_id(parse_fields(f.data)) == template_id:
                found = True
                continue
        kept.append(f)
    if not found:
        raise TemplateEditError(f"template id {template_id} not present in root field 15")
    root[ti] = Field(TEMPLATE_TABLE_FIELD, WIRE_LENGTH, data=encode_fields(kept))
    return _encode_container(container, encode_fields(root))


def _encode_container(container: Container, payload: bytes) -> bytes:
    """Re-encode the container shell around a new payload (same version/magic/trailer)."""
    return encode_container(Container(
        subtype=container.subtype,
        payload=payload,
        version=container.version,
        magic=container.magic,
        trailer=container.trailer,
    ))
