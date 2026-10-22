"""Byte-level diff of two ``.gil`` local saves, field by field.

The project kept re-deriving the same thing by hand: after a save we would copy
the previous ``.gil``, compare it to the new one, and stare at "field 6 grew by
N bytes, field 5/6/46 changed together". There was no general tool, so every
such finding was a one-off. This module is that tool.

It answers one question only: **of the protobuf payload's top-level fields, which
ones changed, and how?** It does not guess what a field *means* -- the schema is
reverse-engineered in ``gil_container.py`` and is deliberately incomplete, so a
diff that pretends to know field names would lie about the unknown ones. It
reports bytes.

Two layers, kept apart on purpose:

  * ``decode_container`` strips the 24-byte framing (``gil_container.py``); only
    the payload is compared. The container header's ``inner length`` necessarily
    changes whenever the payload size does, so comparing framing would report a
    trivial change on every real diff and bury the interesting ones.
  * ``parse_fields`` splits the payload into top-level fields, and for each field
    number we compare the *content* bytes -- the length-delimited data for wire
    type 2, the varint / fixed-width encoding otherwise. A field number that
    repeats (the profile's field 2 does; a level's top-level fields do not) has
    its occurrences concatenated in order, so one row still means one field
    number.

Classification, per field, from the pair of content byte strings:

  ``unchanged``          the two are equal (never emitted -- the report lists only
                         fields that changed)
  ``appended-tail``      one is a prefix of the other: the change is pure tail
                         growth or truncation. An empty side counts as the empty
                         prefix, so a field present in only one file classifies
                         here too.
  ``in-place-rewrite``   same length, different bytes.
  ``replaced``           different length and neither is a prefix of the other --
                         the payload was rewritten, not merely extended.

A field present in both files but carrying equal bytes is omitted, the report is
ordered by field number, and nothing in it depends on wall-clock time or dict
iteration order -- so ``diff_gils`` called twice on the same pair is equal.

Verified against the real save pair on this machine:

  before  ``.runtime/editor-bridge/backups/20261009T163136Z-pre-graph-demo-save-20261010/files/Beyond_Local_Save_Level/1073741842/1073741842.gil``
          21872 bytes (payload 21848)
  after   ``%USERPROFILE%\\AppData\\LocalLow\\miHoYo\\原神\\BeyondLocal\\100000001\\Beyond_Local_Save_Level\\1073741842\\1073741842.gil``
          28383 bytes (payload 28359)

This is the graph-build save: a 15-node graph was created in the editor, bound to
a plot entity, and written to disk natively. Both payloads carry the *same* set of
top-level field numbers -- no field was added or removed at the top level -- but
five of them changed:

  field 5   len 3181 -> 3748   appended-tail      (old is a prefix; 567 bytes
                                                  appended; the new tail's
                                                  readable runs are the node
                                                  names 土田, MPActionGroup,
                                                  GI_RootNode, RootNode2 and
                                                  中心原点)
  field 6   len 1450 -> 1584   replaced           (first differing byte at 589;
                                                  tail gains a "root" entry and
                                                  a 未分类页签 tab)
  field 10  len    2 -> 5789   replaced           (first differing byte at 0;
                                                  the graph itself -- the new
                                                  payload contains "MW_API_" and
                                                  the node-graph structure)
  field 29  len   55 ->   55   in-place-rewrite   (first differing byte at 29;
                                                  the version 7.1.0 string is
                                                  unchanged, a trailing timestamp
                                                  is rewritten)
  field 46  len   22 ->   44   replaced           (first differing byte at 3; the
                                                  new value is a second 22-byte
                                                  block prepended to the old one)

Every other top-level field (1, 2, 3, 4, 7, 8, 9, 11, 12, 14..23, 25, 27, 30..33,
35..38, 39, 40, 41, 43, 44, 45, 48, 49, 50, 52, 53 and the rest) is byte-identical.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Import the sibling codec whether this file is run as a script or imported by
# its test. Both live in tools/beyond-save/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gil_container import (  # noqa: E402
    WIRE_32BIT,
    WIRE_64BIT,
    WIRE_LENGTH,
    WIRE_VARINT,
    ContainerError,
    Field,
    decode_container,
    parse_fields,
    write_varint,
)

UNCHANGED = "unchanged"
APPENDED_TAIL = "appended-tail"
IN_PLACE_REWRITE = "in-place-rewrite"
REPLACED = "replaced"


def field_content(f: Field) -> bytes:
    """The field's payload bytes, with the tag/length prefix stripped.

    This is what the diff compares: two fields with the same wire type and the
    same content are "unchanged" even though a length-delimited field's bytes on
    disk are prefixed by a varint length that would also have to match.
    """
    if f.wire_type == WIRE_VARINT:
        return write_varint(f.value or 0)
    if f.wire_type == WIRE_LENGTH:
        return f.data or b""
    if f.wire_type == WIRE_64BIT:
        return (f.value or 0).to_bytes(8, "little")
    if f.wire_type == WIRE_32BIT:
        return (f.value or 0).to_bytes(4, "little")
    raise ContainerError(f"field {f.number} has wire type {f.wire_type}, cannot take content")


def _group(fields: list[Field]) -> dict[int, tuple[int, bytes]]:
    """Collapse a field list into ``{number: (wire_type, concatenated content)}``.

    Repeated field numbers are concatenated in file order, so a field number maps
    to exactly one comparable byte string.
    """
    grouped: dict[int, list[Field]] = {}
    for f in fields:
        grouped.setdefault(f.number, []).append(f)
    return {
        number: (occurrences[0].wire_type, b"".join(field_content(f) for f in occurrences))
        for number, occurrences in grouped.items()
    }


def _first_difference(a: bytes, b: bytes) -> int:
    """Offset of the first differing byte, or the shorter length if one is a prefix."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def classify(old: bytes, new: bytes) -> str:
    """Name the relationship between two content byte strings."""
    if old == new:
        return UNCHANGED
    if new.startswith(old) or old.startswith(new):
        return APPENDED_TAIL
    if len(old) == len(new):
        return IN_PLACE_REWRITE
    return REPLACED


@dataclass(frozen=True)
class FieldDiff:
    """How one top-level field number differs between the two saves."""
    number: int
    wire_type: int
    old_size: int
    new_size: int
    first_differing_offset: int
    old_is_prefix_of_new: bool
    new_is_prefix_of_old: bool
    classification: str


@dataclass(frozen=True)
class SaveDiff:
    """The report ``diff_gils`` returns. Empty ``changed`` means the two match."""
    before_path: str
    after_path: str
    before_size: int
    after_size: int
    changed: tuple[FieldDiff, ...]

    @property
    def changed_numbers(self) -> tuple[int, ...]:
        return tuple(d.number for d in self.changed)

    @property
    def is_identical(self) -> bool:
        return not self.changed


def diff_payloads(before_payload: bytes, after_payload: bytes) -> tuple[FieldDiff, ...]:
    """Diff two protobuf payloads, returning changed fields ordered by number."""
    before = _group(parse_fields(before_payload))
    after = _group(parse_fields(after_payload))
    report: list[FieldDiff] = []
    for number in sorted(set(before) | set(after)):
        old_wire, old = before.get(number, (0, b""))
        new_wire, new = after.get(number, (0, b""))
        if old == new:
            continue
        report.append(FieldDiff(
            number=number,
            wire_type=new_wire or old_wire,
            old_size=len(old),
            new_size=len(new),
            first_differing_offset=_first_difference(old, new),
            old_is_prefix_of_new=new.startswith(old),
            new_is_prefix_of_old=old.startswith(new),
            classification=classify(old, new),
        ))
    return tuple(report)


def diff_gils(before_path: Path | str, after_path: Path | str) -> SaveDiff:
    """Diff two ``.gil`` saves. Both are read only; nothing is written."""
    before_path = Path(before_path)
    after_path = Path(after_path)
    before_blob = before_path.read_bytes()
    after_blob = after_path.read_bytes()
    before_payload = decode_container(before_blob).payload
    after_payload = decode_container(after_blob).payload
    return SaveDiff(
        before_path=str(before_path),
        after_path=str(after_path),
        before_size=len(before_blob),
        after_size=len(after_blob),
        changed=diff_payloads(before_payload, after_payload),
    )


def render(report: SaveDiff) -> str:
    """A stable, line-per-field, human-readable form of a ``SaveDiff``."""
    lines = [
        f"before {report.before_path} ({report.before_size} B)",
        f"after  {report.after_path} ({report.after_size} B)",
    ]
    if report.is_identical:
        lines.append("no top-level field changed")
        return "\n".join(lines)
    lines.append(f"{len(report.changed)} top-level field(s) changed:")
    for d in report.changed:
        prefix = "old-prefix" if d.old_is_prefix_of_new else (
            "new-prefix" if d.new_is_prefix_of_old else "no-prefix")
        lines.append(
            f"  field {d.number:<4} wire {d.wire_type}  "
            f"len {d.old_size} -> {d.new_size}  "
            f"@ {d.first_differing_offset}  {prefix}  {d.classification}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args(argv)
    print(render(diff_gils(args.before, args.after)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
