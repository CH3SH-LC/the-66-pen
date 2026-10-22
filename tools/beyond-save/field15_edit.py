"""**In-memory only** reusable primitive for the field-15 template store.

READ the module name before using it: this module **can not write a save**. Every
function takes ``bytes`` and returns ``bytes`` (or plain data); there is no path,
no ``open()``, no ``write_bytes``. Persisting the returned bytes is a separate,
deliberate step the caller owns -- the same convention :mod:`terrain` documents for
its writer half. Per ``CLAUDE.md`` §一 the project has no sanctioned writer for a
level ``.gil`` at all: the bridge writes *editor memory* and the native ``save``
writes whatever the *game process* holds, so nothing we hand back is persisted by
us.

**No evidence exists that the game accepts bytes we produce.** The editor is the
only proven writer of field 15: on 2026-10-08 one editor session appended four new
records to level ``1073741842`` and changed none of the four pre-existing ones
(``.runtime/scratch/SHOP-INPLACE-VS-APPEND.md`` §0, per-record sha256 across three
independent BEFORE copies). Whether the engine would *load* a field-15 table we
synthesised is untested and is **not** claimed here.

What this adds over :mod:`template_edit`
----------------------------------------
:mod:`template_edit` answers "does the table admit ONE extra record". It ships an
append (``add_template``) with a duplicate-id guard, but **no replace-in-place**.
The measured way to change an existing record's payload was *composition* --
``remove_template`` then ``add_template`` -- and that route **moves the record to
the tail of the table** (measured: shop index 4 -> 7, ``SHOP-INPLACE-VS-APPEND.md``
§1). This module adds the missing primitive:

* :func:`append_record` -- append a record ``{1: id, 2: f2, 4*: blocks}`` built
  from caller-supplied parts. It **delegates the duplicate-id refusal to**
  ``template_edit.add_template`` so there is exactly one guard and one message
  (``template id <id> already present -- refusing to duplicate``), then **re-reads
  the result** and requires the appended id to appear exactly once.  The guard reads
  each existing entry's id by scanning its parsed fields for **field 1**
  (``template_edit.entry_id``), never by assuming it leads -- a body that does not
  lead with field 1 must still be seen.
* :func:`replace_record_payload` -- **replace the payload of ONE component block
  of an existing record, in place**, keeping the record's index and leaving every
  other record byte-identical. This is the shape "add a shop's goods" needs.
* :func:`reserialise_level` / :func:`reserialise_field15` -- re-encode the whole
  container / just the store body with no change; byte-exact for every real file.

The record model (measured, re-derived in :mod:`template_edit`)
--------------------------------------------------------------
A root field 15 holds repeated ``{1: id}`` entries. Each entry body is
``{1: <typed id>, 2: <small int>, 4*: <component block>}``. A block is
``{1: <kind>, <P>: <payload>}`` where ``P`` is a *census* (``template_edit
.payload_field_for``), not a formula. The one real shop record (level 1073741842,
index 4, id 1136656385, 54 B) is::

    088180809e04 1011 221508015a110a0fe887aae5ae9ae4b989e6a8a1e69dbf
                 22150830d203100a 0e 080120012a0032003a0050015801
    f1 = 1136656385                     (id band (id>>22)-256 = 15 = 商店模板)
    f2 = 17
    f4 { f1=1  f11{ f1="自定义模板" } }                      <- name block
    f4 { f1=48 f58{ f1{ f1=1 f4=1 f5={} f6={} f7={} f10=1 f11=1 } } }  <- settings block

``payload_field_for(48) == 58``; ``replace_record_payload`` replaces the bytes at
that position. Which of the settings block's empty ``f5/f6/f7`` carries the goods
table is **UNKNOWN** -- there is no goods-bearing sample on this machine -- so this
module takes the new payload from the caller and never guesses it.
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import template_edit as te  # noqa: E402
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

#: The root field that holds the template store. Named after the evidence
#: (``template_edit.TEMPLATE_TABLE_FIELD``), re-stated so this module reads alone.
FIELD15 = 15
ENTRY_ID_FIELD = 1        # entry field 1 -- the typed asset id (varint)
ENTRY_KIND_FIELD = 2      # entry field 2 -- the small int beside the id (the "f2")
ENTRY_BLOCK_FIELD = 4     # entry field 4 -- one component block (repeated)
BLOCK_COMPONENT_FIELD = 1  # a block's field 1 -- the component kind

#: The duplicate-id refusal is :mod:`template_edit`'s and is reused verbatim.
#: Aliased so ``except field15_edit.Field15Error`` catches every failure this
#: module (and the append it delegates) can raise.
Field15Error = te.TemplateEditError


@dataclass(frozen=True)
class Record:
    """One decoded store entry. ``body`` is the raw entry bytes, kept verbatim."""
    index: int
    record_id: int
    f2: int | None
    body: bytes

    @property
    def sha256(self) -> str:
        """sha256 of the raw entry body -- the unit the tests compare on."""
        return hashlib.sha256(self.body).hexdigest()

    @property
    def byte_len(self) -> int:
        return len(self.body)


@dataclass(frozen=True)
class Field15Edit:
    """What an in-memory edit produced: the new bytes plus the exact diff facts.

    ``blob`` is the re-encoded level -- NOT written anywhere. For an append
    ``removed_bytes`` is empty and ``added_bytes`` is the appended ``field 1``; for
    a payload replacement ``old_payload_bytes`` / ``new_payload_bytes`` describe the
    changed payload. Everything is a fact about these two byte strings, nothing is
    written.
    """
    blob: bytes
    operation: str
    record_id: int
    index: int                 # where the record sits in the table (before/after)
    size_before: int
    size_after: int
    table_len_before: int
    table_len_after: int
    record_count_before: int
    record_count_after: int
    record_len_before: int
    record_len_after: int
    added_bytes: bytes = b""
    removed_bytes: bytes = b""
    old_payload_bytes: bytes = b""
    new_payload_bytes: bytes = b""

    @property
    def byte_delta(self) -> int:
        """Exact file-size growth (negative once a payload shrinks)."""
        return self.size_after - self.size_before

    @property
    def record_delta(self) -> int:
        """Growth of the target record body."""
        return self.record_len_after - self.record_len_before

    @property
    def table_delta(self) -> int:
        return self.table_len_after - self.table_len_before


# --------------------------------------------------------------------------- #
# reading -- thin wrappers over template_edit's record model
# --------------------------------------------------------------------------- #

def _table_index(root: list[Field]) -> int:
    """The index of the single root field 15, or a named error."""
    idx = [i for i, f in enumerate(root) if f.number == FIELD15]
    if not idx:
        raise Field15Error("level payload has no root field 15 (template store)")
    if len(idx) > 1:
        raise Field15Error(
            f"root field 15 appears {len(idx)} times -- refusing to guess which is the store")
    return idx[0]


def _split(blob: bytes) -> tuple[Container, list[Field], int]:
    container = decode_container(blob)
    if container.subtype != 2:
        raise Field15Error(f"container subtype {container.subtype} is not a level (2)")
    root = parse_fields(container.payload)
    return container, root, _table_index(root)


def _reencode(container: Container, root: list[Field]) -> bytes:
    return encode_container(Container(
        subtype=container.subtype,
        payload=encode_fields(root),
        version=container.version,
        magic=container.magic,
        trailer=container.trailer,
    ))


def read_records(blob: bytes) -> list[Record]:
    """Read every store record. Read-only; delegates the decode to template_edit."""
    return [
        Record(index=t.index, record_id=t.template_id, f2=t.kind, body=t.entry_bytes)
        for t in te.read_templates(blob)
    ]


def record_digests(blob: bytes) -> dict[int, str]:
    """``{record_id: sha256(body)}`` -- the per-record unit the tests compare on."""
    return {r.record_id: r.sha256 for r in read_records(blob)}


def record_index(blob: bytes, record_id: int) -> int:
    """The table position of ``record_id`` (raises if absent)."""
    for r in read_records(blob):
        if r.record_id == record_id:
            return r.index
    raise Field15Error(f"template id {record_id} not present in root field 15")


def field15_value(blob: bytes) -> bytes:
    """The raw field-15 body (the repeated ``{1: entry}`` wrappers)."""
    _, root, ti = _split(blob)
    return root[ti].data or b""


# --------------------------------------------------------------------------- #
# re-serialisation -- returns bytes, never a path
# --------------------------------------------------------------------------- #

def reserialise_field15(blob: bytes) -> bytes:
    """Re-encode ONLY the field-15 body from a parse. Byte-exact, opens nothing."""
    _, root, ti = _split(blob)
    return encode_fields(parse_fields(root[ti].data or b""))


def reserialise_level(blob: bytes) -> bytes:
    """Re-encode the whole level container with NO change. Byte-exact for every
    real file (the tests assert it). Returns bytes; persisting them is a separate,
    deliberate step the caller owns.

    Unlike :func:`reserialise_field15` this does **not** require a field 15 -- a
    level with no template store still round-trips (it must: a store-less level is
    a valid level).
    """
    container = decode_container(blob)
    return _reencode(container, parse_fields(container.payload))


# --------------------------------------------------------------------------- #
# append -- the duplicate guard is template_edit's, reused verbatim
# --------------------------------------------------------------------------- #

def _build_entry(
    record_id: int,
    f2: int | None,
    name: str | None,
    component_kind: int | None,
    payload: bytes,
    payload_field: int | None,
    blocks: tuple[Field, ...],
) -> bytes:
    fields: list[Field] = [Field(ENTRY_ID_FIELD, WIRE_VARINT, value=record_id)]
    if f2 is not None:
        fields.append(Field(ENTRY_KIND_FIELD, WIRE_VARINT, value=f2))
    if name is not None:
        fields.append(te.build_name_block(name))
    fields.extend(blocks)
    if component_kind is not None or payload:
        if component_kind is None:
            raise Field15Error(
                "a payload needs component_kind (the block's field-1 value); "
                "pass component_kind=<kind>")
        fields.append(te.build_block(component_kind, payload, payload_field))
    return encode_fields(fields)


def append_record(
    blob: bytes,
    record_id: int,
    f2: int | None = None,
    payload: bytes = b"",
    *,
    component_kind: int | None = None,
    name: str | None = None,
    payload_field: int | None = None,
    blocks: tuple[Field, ...] = (),
    entry: bytes | None = None,
) -> Field15Edit:
    """Return a NEW level blob with one record appended to root field 15.

    Pure function: ``blob`` in, new ``bytes`` out. Nothing is written.

    The record is built as ``{1: id, 2: f2, 4*: blocks, 4: {kind: payload}}``; a
    caller that already has the exact entry bytes passes ``entry=``. The record is
    appended as a new repeated ``field 1`` at the END of the existing field-15
    value, so no root field appears or moves and every existing record is carried
    through untouched.

    **Duplicate ids are refused by** ``template_edit.add_template`` -- the one guard
    in the tree -- with its message ``template id <id> already present -- refusing to
    duplicate``. A body whose ``field 1`` is not ``record_id`` is refused too.  After
    the append this re-reads the result and requires the id to appear **exactly
    once**: the pre-check scans each existing entry for field 1 (it no longer reads
    the entry's *first* field), and this outcome check is the backstop.
    """
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id < 1:
        raise Field15Error(f"record id must be a positive int, got {record_id!r}")
    if entry is None:
        entry = _build_entry(record_id, f2, name, component_kind, payload, payload_field, blocks)

    # The guard lives in template_edit; reusing it keeps ONE message, one behaviour.
    # It reads each existing entry's id by SCANNING for field 1 (template_edit.entry_id),
    # not by assuming it leads -- see _build_entry's docstring.
    edit = te.add_template(blob, record_id, entry=entry)

    # Second half of the guard: re-read the RESULT and require the id EXACTLY ONCE.
    # The pre-check scans the existing entries; this checks the outcome, so no
    # mis-scan -- a body that does not lead with field 1, a duplicate field 1 --
    # can leave two records sharing an id.  Pure: ``edit.blob`` is never written.
    count = sum(1 for r in read_records(edit.blob) if r.record_id == record_id)
    if count > 1:
        raise Field15Error(
            f"template id {record_id} already present -- refusing to duplicate")
    if count != 1:
        raise Field15Error(
            f"template id {record_id} present {count} times after append -- refusing")

    return Field15Edit(
        blob=edit.blob,
        operation="append",
        record_id=record_id,
        index=edit.entry_count_before,          # appended at the tail
        size_before=len(blob),
        size_after=len(edit.blob),
        table_len_before=edit.table_len_before,
        table_len_after=edit.table_len_after,
        record_count_before=edit.entry_count_before,
        record_count_after=edit.entry_count_after,
        record_len_before=0,
        record_len_after=len(entry),
        added_bytes=edit.added_bytes,
    )


# --------------------------------------------------------------------------- #
# replace-in-place -- the primitive the composition route lacked
# --------------------------------------------------------------------------- #

def _locate_wrapper(children: list[Field], record_id: int) -> int:
    """Index in the field-15 body of the ``{1: record_id}`` wrapper.

    The record's id is read with :func:`template_edit.entry_id` -- a SCAN for
    field 1 in the entry body, never its first field -- so a body that does not
    lead with field 1 is still located.
    """
    found: list[int] = []
    for i, ch in enumerate(children):
        if ch.number != ENTRY_ID_FIELD or ch.wire_type != WIRE_LENGTH or not ch.data:
            continue
        if te.entry_id(parse_fields(ch.data)) == record_id:
            found.append(i)
    if not found:
        raise Field15Error(f"template id {record_id} not present in root field 15")
    if len(found) > 1:
        raise Field15Error(
            f"template id {record_id} appears {len(found)} times -- refusing to guess which")
    return found[0]


def replace_record_payload(
    blob: bytes,
    record_id: int,
    payload: bytes,
    *,
    block_index: int = -1,
    payload_field: int | None = None,
) -> Field15Edit:
    """Replace the payload of ONE component block of an existing record, IN PLACE.

    Pure function: ``blob`` in, new ``bytes`` out. Nothing is written. Unlike the
    composed ``remove_template`` + ``add_template`` route -- which re-appends the
    record at the TAIL, moving it (measured: shop index 4 -> 7) -- this edits the
    record where it sits: **the index is preserved and every other record stays
    byte-identical** (the tests compare per-record sha256).

    The target block is the ``block_index``-th ``field 4`` of the record body
    (0-based; negative counts from the end, so the default ``-1`` is the record's
    last block -- for the measured ``{1: id, 2: f2, 4: name, 4: settings}`` shape,
    the settings/payload block). Its payload child is the first length-delimited
    child that is not the ``{1: kind}`` tag; that child's bytes are replaced.

    If the block carries no payload child yet, ``payload_field`` (or the measured
    ``template_edit.payload_field_for(kind)``) supplies the field number for the new
    one. ``payload_field`` given when the block already has a *different* payload
    field is refused -- the caller may be looking at the wrong block.
    """
    container, root, ti = _split(blob)
    table_value = root[ti].data or b""
    before = te.read_templates(blob)
    count_before = len(before)

    children = parse_fields(table_value)
    widx = _locate_wrapper(children, record_id)
    body = children[widx].data or b""
    body_fields = parse_fields(body)

    block_positions = [j for j, f in enumerate(body_fields)
                       if f.number == ENTRY_BLOCK_FIELD and f.wire_type == WIRE_LENGTH]
    if not block_positions:
        raise Field15Error(
            f"template id {record_id} has no field 4 component block to replace")
    bi = block_index + len(block_positions) if block_index < 0 else block_index
    if not (0 <= bi < len(block_positions)):
        raise Field15Error(
            f"block_index {block_index} out of range 0..{len(block_positions) - 1} "
            f"for template id {record_id}")

    block = body_fields[block_positions[bi]]
    kids = parse_fields(block.data or b"")
    if not kids or kids[0].number != BLOCK_COMPONENT_FIELD:
        raise Field15Error(
            f"template id {record_id} block {bi} has no {{1: kind}} tag -- cannot locate its payload")
    block_kind = kids[0].value
    pay_i = next((k for k, f in enumerate(kids)
                  if f.number != BLOCK_COMPONENT_FIELD and f.wire_type == WIRE_LENGTH), None)

    if pay_i is not None:
        pf = kids[pay_i].number
        if payload_field is not None and payload_field != pf:
            raise Field15Error(
                f"template id {record_id} block {bi} carries payload field {pf}, "
                f"not the requested {payload_field}")
        old_payload = kids[pay_i].data or b""
        kids[pay_i] = Field(pf, WIRE_LENGTH, data=bytes(payload))
    else:
        if payload_field is None:
            payload_field = te.payload_field_for(block_kind)  # census; raises for unmeasured
        old_payload = b""
        kids.append(Field(payload_field, WIRE_LENGTH, data=bytes(payload)))

    body_fields[block_positions[bi]] = Field(
        ENTRY_BLOCK_FIELD, WIRE_LENGTH, data=encode_fields(kids))
    new_body = encode_fields(body_fields)

    children[widx] = Field(ENTRY_ID_FIELD, WIRE_LENGTH, data=new_body)
    new_table = encode_fields(children)
    root[ti] = Field(FIELD15, WIRE_LENGTH, data=new_table)
    new_blob = _reencode(container, root)

    after = te.read_templates(new_blob)
    return Field15Edit(
        blob=new_blob,
        operation="replace-payload",
        record_id=record_id,
        index=next(t.index for t in after if t.template_id == record_id),
        size_before=len(blob),
        size_after=len(new_blob),
        table_len_before=len(table_value),
        table_len_after=len(encode_fields(children)),
        record_count_before=count_before,
        record_count_after=len(after),
        record_len_before=len(body),
        record_len_after=len(new_body),
        old_payload_bytes=old_payload,
        new_payload_bytes=bytes(payload),
    )


# --------------------------------------------------------------------------- #
# read-only CLI (inspection only -- opens files for reading, never writing)
# --------------------------------------------------------------------------- #

def _main(argv: list[str]) -> int:  # pragma: no cover - manual inspection
    paths = argv[1:]
    if not paths:
        print("usage: python -m field15_edit <level.gil> [more.gil ...]")
        return 2
    for p in paths:
        blob = Path(p).read_bytes()
        try:
            records = read_records(blob)
        except Field15Error as exc:
            print(f"{p}: {type(exc).__name__}: {exc}")
            continue
        print(f"{p}: {len(records)} record(s)")
        for r in records:
            print(f"  [{r.index}] id={r.record_id} type={te.id_type(r.record_id)} "
                  f"f2={r.f2} len={r.byte_len} sha={r.sha256[:12]}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
