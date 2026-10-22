"""Read and validate a level's ``root field 6`` -- its tab directory (页签目录).

WHY THIS EXISTS
    ``docs/PROGRESS-BY-FUNCTION.md:118-126`` records real damage to
    ``1073741842.gil``: two saves each appended one entry to ``root field 6``
    (and one to ``root field 46``), and one of the two new field-6 entries had
    no ``field 1`` -- a tab with no id.  The damage was repaired by hand but
    *nothing in the tree could detect it*: the field-6 shape was only ever read
    incidentally, by ``tools/game-executor/verify-created-save.py`` looking for
    exactly one category ``kind == 3``.  This module turns the field-6 shape
    into something that can be read whole and checked, so the same failure mode
    stops being invisible.

THE SHAPE (measured, not a vendor schema)
    Every byte below was read off real ``.gil`` files (see ``read_directory``
    and the tests).  ``root field 6`` is a length-delimited section whose
    children are *all* ``field 1``.  Each ``field 1`` child is one directory
    entry (a tab):

        field 6  section
          repeated field 1  entry
            field 1  varint      entry id            <- the field the damage dropped
            field 2  message     owner  { field 1 owner-name (utf-8, "root"),
                                          field 3 tag }
            field 3  message     body   { field 1 display name (utf-8),
                                          field 3 type code (2),
                                          repeated field 5 member {
                                              field 1 group,
                                              field 2 member id } }

    On the four real 1073741842 snapshots seen while writing this:

        user original (sha 88ad2acf...)     40 entries, every one carrying field 1
        2026-10-08 damaged copies           42 entries, the last one has no field 1
        live save, 2026-10-10 00:41         42 entries, the last one has no field 1

    So the damage is not historical -- the live save carries the same shape
    again.  This module is what makes that visible without a human eyeballing
    hex.

WHAT THIS MODULE IS NOT
    * It does not claim field 1 is the only legitimate id, nor that 40 is the
      only legitimate count.  A *missing* field 1 and a *duplicate* id are
      defects regardless of how many entries there are.
    * It is read-only.  It never writes a ``.gil``.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field as _field
from pathlib import Path

from gil_container import (  # noqa: E402  (sibling module, imported via sys.path)
    Field,
    WIRE_LENGTH,
    WIRE_VARINT,
    _all,
    _first,
    decode_container,
    parse_fields,
)

# Field numbers, as observed.  Names describe the evidence, not a vendor schema.
ROOT_FIELD_DIRECTORY = 6

ENTRY_FIELD_ID = 1
ENTRY_FIELD_OWNER = 2
ENTRY_FIELD_BODY = 3

OWNER_FIELD_NAME = 1
OWNER_FIELD_TAG = 3

BODY_FIELD_NAME = 1
BODY_FIELD_TYPE = 3
BODY_FIELD_MEMBER = 5

MEMBER_FIELD_GROUP = 1
MEMBER_FIELD_ID = 2

# Defect codes.  A stable string, so callers can filter without parsing prose.
MISSING_ROOT_6 = "missing-root-6"
MULTIPLE_ROOT_6 = "multiple-root-6-sections"
ROOT_6_NOT_MESSAGE = "root-6-not-message"
UNEXPECTED_ROOT_6_FIELD = "unexpected-root6-field"
ENTRY_NOT_MESSAGE = "entry-not-message"
MISSING_ENTRY_ID = "missing-entry-id"
DUPLICATE_ENTRY_FIELD_1 = "duplicate-entry-field-1"
DUPLICATE_ENTRY_ID = "duplicate-entry-id"
MALFORMED_MEMBER = "malformed-member"


@dataclass(frozen=True)
class Member:
    """One ``field 5`` reference inside an entry's body."""

    group: int
    member_id: int


@dataclass
class DirectoryEntry:
    """One tab in the root-6 directory.

    ``entry_id`` is ``None`` when the entry carries no ``field 1`` -- the exact
    shape the 2026-10-08 damage produced.  ``index`` is the 0-based position of
    the entry among root 6's children, which is what makes a defect locatable.
    """

    index: int
    entry_id: int | None
    owner: str | None
    name: str | None
    type_code: int | None
    members: list[Member] = _field(default_factory=list)
    raw: list[Field] = _field(default_factory=list)


@dataclass(frozen=True)
class Defect:
    """One reason this directory is not clean.

    ``index`` is the offending entry's position, or ``None`` for a whole-section
    defect.  ``detail`` is human-readable and is not meant to be parsed.
    """

    code: str
    index: int | None
    detail: str


# --------------------------------------------------------------------------- #
# the one scanner both public functions are built on
# --------------------------------------------------------------------------- #

def _text_of(fields: list[Field], number: int) -> str | None:
    found = _first(fields, number)
    if found is None or found.wire_type != WIRE_LENGTH:
        return None
    try:
        return found.text()
    except UnicodeDecodeError:
        return None


def _scan_section(section: Field) -> tuple[list[DirectoryEntry], list[Defect]]:
    """Read the children of a root-6 section into entries plus defects."""
    entries: list[DirectoryEntry] = []
    defects: list[Defect] = []

    children = section.children()
    for position, child in enumerate(children):
        if child.number != ENTRY_FIELD_ID:
            defects.append(Defect(
                UNEXPECTED_ROOT_6_FIELD, position,
                f"root 6 child at position {position} is field {child.number}, "
                f"not the field {ENTRY_FIELD_ID} every real entry uses"))
            continue
        if child.wire_type != WIRE_LENGTH:
            defects.append(Defect(
                ENTRY_NOT_MESSAGE, position,
                f"entry at position {position} has wire type {child.wire_type}, "
                f"not a length-delimited message"))
            continue

        parts = child.children()
        id_fields = _all(parts, ENTRY_FIELD_ID)
        entry_id: int | None = None
        if len(id_fields) > 1:
            defects.append(Defect(
                DUPLICATE_ENTRY_FIELD_1, position,
                f"entry at position {position} carries {len(id_fields)} "
                f"field {ENTRY_FIELD_ID} values; the id is ambiguous"))
        elif id_fields:
            entry_id = id_fields[0].value

        owner_field = _first(parts, ENTRY_FIELD_OWNER)
        owner = _text_of(owner_field.children(), OWNER_FIELD_NAME) if owner_field and owner_field.wire_type == WIRE_LENGTH else None

        body_field = _first(parts, ENTRY_FIELD_BODY)
        name: str | None = None
        type_code: int | None = None
        members: list[Member] = []
        if body_field is not None and body_field.wire_type == WIRE_LENGTH:
            body = body_field.children()
            name = _text_of(body, BODY_FIELD_NAME)
            type_field = _first(body, BODY_FIELD_TYPE)
            type_code = type_field.value if type_field and type_field.wire_type == WIRE_VARINT else None
            for member_field in _all(body, BODY_FIELD_MEMBER):
                if member_field.wire_type != WIRE_LENGTH:
                    defects.append(Defect(
                        MALFORMED_MEMBER, position,
                        f"member of entry {position} has wire type {member_field.wire_type}"))
                    continue
                mparts = member_field.children()
                group = _first(mparts, MEMBER_FIELD_GROUP)
                member_id = _first(mparts, MEMBER_FIELD_ID)
                if group is None or member_id is None:
                    defects.append(Defect(
                        MALFORMED_MEMBER, position,
                        f"member of entry {position} lacks field "
                        f"{MEMBER_FIELD_GROUP if group is None else MEMBER_FIELD_ID}"))
                    continue
                members.append(Member(group.value or 0, member_id.value or 0))

        entries.append(DirectoryEntry(
            index=position,
            entry_id=entry_id,
            owner=owner,
            name=name,
            type_code=type_code,
            members=members,
            raw=parts,
        ))

    # An entry with no field 1 is a tab with no id -- exactly the 2026-10-08
    # damage.  The name is folded in only as a locator; it is not the id.  An
    # entry with *several* field 1 values was already flagged as ambiguous above
    # and is not also "missing".
    for entry in entries:
        if _all(entry.raw, ENTRY_FIELD_ID):
            continue
        label = f" ({entry.name!r})" if entry.name else ""
        defects.append(Defect(
            MISSING_ENTRY_ID, entry.index,
            f"entry at position {entry.index}{label} has no field "
            f"{ENTRY_FIELD_ID}: a tab with no id"))

    # Duplicate ids are a defect on the *later* occurrence; the first is the one
    # the id is understood to name.
    seen: dict[int, int] = {}
    for entry in entries:
        if entry.entry_id is None:
            continue
        if entry.entry_id in seen:
            defects.append(Defect(
                DUPLICATE_ENTRY_ID, entry.index,
                f"entry id {entry.entry_id} repeats (first at position "
                f"{seen[entry.entry_id]}, again at {entry.index})"))
        else:
            seen[entry.entry_id] = entry.index

    return entries, defects


def _scan_payload(payload: bytes) -> tuple[list[DirectoryEntry], list[Defect]]:
    defects: list[Defect] = []
    sections = _all(parse_fields(payload), ROOT_FIELD_DIRECTORY)
    if not sections:
        return [], [Defect(MISSING_ROOT_6, None,
                           f"payload has no field {ROOT_FIELD_DIRECTORY} section")]
    if len(sections) > 1:
        defects.append(Defect(
            MULTIPLE_ROOT_6, None,
            f"payload has {len(sections)} field {ROOT_FIELD_DIRECTORY} sections; "
            f"the real files carry exactly one"))
    section = sections[0]
    if section.wire_type != WIRE_LENGTH:
        defects.append(Defect(
            ROOT_6_NOT_MESSAGE, None,
            f"field {ROOT_FIELD_DIRECTORY} has wire type {section.wire_type}, "
            f"not a length-delimited section"))
        return [], defects
    entries, entry_defects = _scan_section(section)
    defects.extend(entry_defects)
    defects.sort(key=lambda d: (d.index if d.index is not None else -1, d.code))
    return entries, defects


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def read_directory(path: str | Path) -> list[DirectoryEntry]:
    """Return the tabs of ``path``'s root-6 directory, damaged entries included.

    Raises ``gil_container.ContainerError`` when the bytes are not a beyond
    local-save container at all.  A well-formed container whose *directory* is
    damaged is not an error here -- that is what ``check_directory`` is for.
    """
    payload = decode_container(Path(path).read_bytes()).payload
    entries, _ = _scan_payload(payload)
    return entries


def check_directory(path: str | Path) -> list[Defect]:
    """Return every defect in ``path``'s root-6 directory; empty means clean.

    Same container-level contract as ``read_directory``: a non-container raises,
    a container with a damaged directory returns defects.
    """
    payload = decode_container(Path(path).read_bytes()).payload
    _, defects = _scan_payload(payload)
    return defects


# --------------------------------------------------------------------------- #
# CLI -- read-only
# --------------------------------------------------------------------------- #

def _report(path: Path) -> dict:
    entries = read_directory(path)
    defects = check_directory(path)
    return {
        "path": str(path),
        "entryCount": len(entries),
        "entryIds": [e.entry_id for e in entries],
        "entries": [
            {"index": e.index, "id": e.entry_id, "name": e.name,
             "owner": e.owner, "type": e.type_code,
             "members": [[m.group, m.member_id] for m in e.members]}
            for e in entries
        ],
        "defects": [{"code": d.code, "index": d.index, "detail": d.detail} for d in defects],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read and validate the root field 6 tab directory of a .gil file. "
                    "Read-only: no file is written.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a summary")
    args = parser.parse_args(argv)

    reports = []
    exit_code = 0
    for path in args.paths:
        report = _report(path)
        reports.append(report)
        if report["defects"]:
            exit_code = 1
        if not args.json:
            print(f"{path}: {report['entryCount']} entries, "
                  f"{len(report['defects'])} defect(s)")
            for defect in report["defects"]:
                where = "" if defect["index"] is None else f" [entry {defect['index']}]"
                print(f"    {defect['code']}{where}: {defect['detail']}")
    if args.json:
        json.dump(reports if len(reports) > 1 else reports[0],
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
