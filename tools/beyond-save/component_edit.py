"""**In-memory only** editor for an entity's component wrappers in a level ``.gil``.

READ the module name before using it: this module **can not write a save**. Every
function takes ``bytes`` and returns ``bytes``; there is no path, no ``open()``,
no ``write_bytes``. Persisting the returned bytes is a separate, deliberate step
somebody else owns -- and per ``CLAUDE.md`` §一 the project has no sanctioned
writer for a level ``.gil`` at all (the bridge writes editor memory; the native
``save`` writes whatever the *game process* holds in memory, not a file we hand
it). So this module exists to answer a **question about the bytes**, not to
produce a save:

    Does the save's own per-entity component encoding admit ONE extra component,
    and if so exactly which bytes change and by how much?

Design / evidence
-----------------
The entity record layout is re-derived from the byte decoders, not a schema:

    root field 5                      entity table (repeated entries)   entity_geometry.py:124
      entry field 1  (varint)         the integer entity id             entity_geometry.py:125
      entry field 2  (message)        {1: int, 2: int} reference        entity_geometry.py:126
      entry field 5/6/7 (message)     component groups; each child is a
                                      wrapper {1: kind, <P>: payload}   entity_geometry.py:128,353-372
      entry field 8  (varint)         the template id                   ENTITY-CREATE-FIELDS.md §4.2

Measured on a real record (level 1073741842, entity 1077936129, 564-byte body,
31 wrappers) the wrapper's payload field number ``P`` is a *function of*
``(group, kind)`` and for **group 6 it is exactly ``kind + 10``**: the real
record carries ``(6,1)->f11 (6,2)->f12 ... (6,8)->f18 (6,11)->f21 (6,12)->f22``.
Groups 5 and 7 do **not** follow a single rule (``(5,13)->f22`` but ``(5,14)->f23``;
every group-7 wrapper carries ``f2``), which is why ``payload_field_for`` only
derives the field for group 6 and demands it explicitly otherwise.

CAVEAT (kept loud on purpose): the *numeric* ``kind`` values are positional. The
editor-side component enum (``jaUof90C3Ncl5BAJri4x``, ``BeyondCompTypeCollision``
= 8, ``BeyondCompTypeClientTrigger`` = 5 -- COLLISION-COMPONENT-ID.md §1.1) is a
*different* vocabulary from the ``.gil`` wrapper's ``kind``; no committed source
connects the two numbers. ``KIND_COLLISION`` / ``KIND_CLIENT_TRIGGER`` below are
therefore **hypotheses carried from the editor corpus**, flagged as such, and the
actual byte edit below is agnostic to what ``kind`` means -- it will add a wrapper
of *any* kind you name.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
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
ENTITY_TABLE_FIELD = 5          # root field holding the repeated entity records
ENTRY_ID_FIELD = 1              # entry field 1 -- the entity id (varint)
ENTRY_TAG_FIELD = 8             # entry field 8 -- the template id; the engine writes it last
COMPONENT_GROUPS = (5, 6, 7)    # entry fields whose children are component wrappers
WRAPPER_KIND_FIELD = 1          # a wrapper's field 1 -- the component kind

#: group 6's wrapper payload field is `kind + 10` -- the ONE group where the rule
#: holds on every measured record. Groups 5/7 need the field passed explicitly.
GROUP6_PAYLOAD_OFFSET = 10

#: Editor-corpus enum values, carried here as *named hypotheses* (not proven to be
#: the `.gil` wrapper kind -- see the module docstring caveat).
KIND_CLIENT_TRIGGER = 5         # BeyondCompTypeClientTrigger  (COLLISION-COMPONENT-ID.md:9)
KIND_COLLISION = 8              # BeyondCompTypeCollision       (COLLISION-COMPONENT-ID.md:12)


class ComponentEditError(ValueError):
    """The bytes are not a level whose entity we can edit."""


@dataclass(frozen=True)
class ComponentEdit:
    """What an in-memory edit produced: the new bytes plus the exact diff facts."""
    blob: bytes                 # the re-encoded level (NOT written anywhere)
    entity_id: int
    group: int
    kind: int
    payload_field: int
    wrapper_bytes: bytes        # the bare wrapper {1: kind, P: payload}
    appended_bytes: bytes       # the wrapper as it sits inside the record (key+len+P)
    record_len_before: int
    record_len_after: int

    @property
    def byte_delta(self) -> int:
        """Exact file-size growth (== length of the appended wrapper field)."""
        return len(self.appended_bytes)

    @property
    def record_delta(self) -> int:
        """Growth of the target record body (== the same number; the wrappers nest)."""
        return self.record_len_after - self.record_len_before


def payload_field_for(group: int, kind: int) -> int:
    """The wrapper payload field number for ``(group, kind)``.

    Only **group 6** has a derivable rule (``kind + 10``, measured on every real
    record). Any other group must supply the field explicitly -- there is no
    general rule to guess from (entity_geometry.py:27-32).
    """
    if group == 6:
        return kind + GROUP6_PAYLOAD_OFFSET
    raise ComponentEditError(
        f"group {group} has no derived payload field; pass payload_field explicitly")


def build_wrapper(kind: int, payload: bytes, payload_field: int) -> bytes:
    """Encode one component wrapper ``{1: kind, <payload_field>: payload}``.

    ``payload`` may be empty -- a real record carries plenty of 0-length payload
    wrappers (e.g. ``(5,19,28,0)``), so an empty payload is a well-formed wrapper,
    not a corner case.
    """
    if kind < 1:
        raise ComponentEditError(f"kind must be positive, got {kind}")
    if payload_field < 1 or payload_field == WRAPPER_KIND_FIELD:
        raise ComponentEditError(f"payload field must be >1, got {payload_field}")
    return encode_fields([
        Field(WRAPPER_KIND_FIELD, WIRE_VARINT, value=kind),
        Field(payload_field, WIRE_LENGTH, data=payload),
    ])


def _find_entity_entry(payload: bytes, entity_id: int) -> tuple[int, int, bytes]:
    """Locate an entity entry.

    Returns ``(table_index, entry_index, entry_body)`` where ``table_index`` is the
    index of the root field-5 occurrence and ``entry_index`` the entry inside it.
    """
    top = parse_fields(payload)
    found: list[tuple[int, int, bytes]] = []
    for ti, f in enumerate(top):
        if f.number != ENTITY_TABLE_FIELD or f.wire_type != WIRE_LENGTH or f.data is None:
            continue
        for ei, entry in enumerate(parse_fields(f.data)):
            if entry.wire_type != WIRE_LENGTH or entry.data is None:
                continue
            body = parse_fields(entry.data)
            idf = next((c for c in body if c.number == ENTRY_ID_FIELD), None)
            if idf is not None and idf.value == entity_id:
                found.append((ti, ei, entry.data))
    if not found:
        raise ComponentEditError(f"entity {entity_id} not present in root field 5")
    if len(found) > 1:
        raise ComponentEditError(
            f"entity {entity_id} appears {len(found)} times -- refusing to guess")
    return found[0]


def add_component(
    blob: bytes,
    entity_id: int,
    kind: int,
    group: int = 6,
    payload: bytes = b"",
    payload_field: int | None = None,
) -> ComponentEdit:
    """Return a NEW level blob with one component wrapper added to an entity.

    Pure function: ``blob`` in, new ``bytes`` out. Nothing is written. The wrapper
    is inserted just before the record's trailing field-8 tag, so the record keeps
    the engine's field order. The only other byte changes are (a) the target record
    body growing by the wrapper field, and
    (b) the enclosing length varints (entry, root field 5, container inner length,
    container total length) being recomputed -- every other byte is carried through
    untouched, which the tests assert.
    """
    container = decode_container(blob)
    if container.subtype != 2:
        raise ComponentEditError(f"container subtype {container.subtype} is not a level (2)")
    if group not in COMPONENT_GROUPS:
        raise ComponentEditError(f"group {group} is not one of {COMPONENT_GROUPS}")
    if payload_field is None:
        payload_field = payload_field_for(group, kind)

    wrapper = build_wrapper(kind, payload, payload_field)
    appended = encode_fields([Field(group, WIRE_LENGTH, data=wrapper)])

    table_index, entry_index, body = _find_entity_entry(container.payload, entity_id)
    body_fields = parse_fields(body)
    record_len_before = len(body)
    # Insert the new wrapper **before** entry field 8 (the template id). Every
    # observed record ends with field 8, so appending past it would still be legal
    # protobuf but would be the one record whose field order differs from the
    # engine's -- an unforced change this project's doctrine forbids.
    new_wrapper = Field(group, WIRE_LENGTH, data=wrapper)
    insert_at = next((i for i, f in enumerate(body_fields)
                      if f.number == ENTRY_TAG_FIELD), len(body_fields))
    new_body = encode_fields(body_fields[:insert_at] + [new_wrapper] + body_fields[insert_at:])

    top = parse_fields(container.payload)
    entry_fields = parse_fields(top[table_index].data or b"")
    entry_fields[entry_index] = Field(ENTRY_ID_FIELD, WIRE_LENGTH, data=new_body)
    top[table_index] = Field(ENTITY_TABLE_FIELD, WIRE_LENGTH, data=encode_fields(entry_fields))

    new_blob = encode_container(Container(
        subtype=container.subtype,
        payload=encode_fields(top),
        version=container.version,
        magic=container.magic,
        trailer=container.trailer,
    ))
    return ComponentEdit(
        blob=new_blob,
        entity_id=entity_id,
        group=group,
        kind=kind,
        payload_field=payload_field,
        wrapper_bytes=wrapper,
        appended_bytes=appended,
        record_len_before=record_len_before,
        record_len_after=len(new_body),
    )


def read_components(blob: bytes, entity_id: int) -> list[tuple[int, int | None, bytes]]:
    """Read back ``(group, kind, wrapper_bytes)`` for one entity. Read-only."""
    container = decode_container(blob)
    _, _, body = _find_entity_entry(container.payload, entity_id)
    out: list[tuple[int, int | None, bytes]] = []
    for child in parse_fields(body):
        if child.number not in COMPONENT_GROUPS or child.wire_type != WIRE_LENGTH:
            continue
        kids = parse_fields(child.data or b"")
        kind = kids[0].value if kids and kids[0].number == WRAPPER_KIND_FIELD else None
        out.append((child.number, kind, child.data or b""))
    return out
