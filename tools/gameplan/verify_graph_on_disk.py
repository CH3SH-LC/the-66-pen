"""Re-check, from the ``.gil`` file alone, that a graph landed on disk.

WHY THIS EXISTS
    ``PROGRESS.md:15`` records the project's first full loop -- bridge builds a
    15-node graph, binds it to an entity, a native ``save`` runs, and the level
    file grows ``21872 -> 28383`` bytes carrying ``graphId 1073741829`` and
    ``entityId 1077936129``.  That核对 was done by hand, in a throwaway script,
    and *nothing in the tree could repeat it*.  Repeating it is exactly what a
    doctrine of "``ok:true`` alone does not prove persistence -- you need a
    ``.gil`` byte diff plus an independent readback" (``CLAUDE.md:59``) demands.
    This module is that repeatable check: one function, one CLI line, no bridge,
    no game, no write.

WHAT IT MEASURES (and how, exactly)
    1. **Presence count.** The payload is searched for the canonical protobuf
       varint encoding of ``graph_id`` / ``entity_id``
       (``gil_container.write_varint``).  Each hit is attributed to the *root*
       field whose byte span contains it.  On the real pair that turns a bare
       "8 occurrences" into "root 5 x1, root 6 x1, root 9 x5, root 10 x1" --
       and the baseline's 5 are all in root 9 (the sibling-level directory),
       which is the difference between a coincidence and evidence.
    2. **Structural hint.** A best-effort descent of the protobuf tree records
       the dotted field path of every *field value* equal to the id.  This is a
       heuristic (length-delimited fields that are not messages will not parse),
       so it is reported separately from the byte count and never alone.
    3. **What changed.** Root fields are sized by their on-disk encoded length
       (``len(encode_fields([f]))``); the sizes *now* are diffed against a
       supplied baseline file.  Because ``encode_fields`` round-trips
       ``parse_fields`` byte for byte, those encoded sizes sum to the payload
       length exactly, so the deltas sum to the payload delta -- an invariant
       this module checks and reports, not assumes.

WHAT IT DOES **NOT** PROVE  (read this before quoting a green run)
    * A byte run matching an id is **not** proof that a well-formed, loadable
      graph definition is present.  It is a substring count over opaque bytes.
    * The same id can appear for reasons that have nothing to do with this
      graph: on the real pair ``graph_id 1073741829`` already occurs 5 times in
      the *baseline*, because root field 9 lists sibling level ids and one
      sibling shares the number.  A nonzero count therefore proves nothing on
      its own; the *difference* against a baseline is the signal.
    * ``entity_id`` is only as trustworthy as the caller passing the right one.
    * Nothing here says the graph is *well-formed*, *bound*, or *executed*.
      It says bytes that look like this id are in this file, and which root
      fields changed size.  Runtime semantics need a playtest; this cannot
      reach that.

The ``DOES_NOT_PROVE`` tuple below is the same list in machine-readable form, so
the caveat travels with the report instead of living only in this docstring.

READ-ONLY
    The only I/O is ``Path.read_bytes``.  Nothing in this module opens a file
    for writing; ``gil_container.write_bytes`` is deliberately not imported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Mapping

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODEC_PATH = _REPO_ROOT / "tools" / "beyond-save" / "gil_container.py"

#: Attribution bucket for a hit that falls outside every root field span.  Field
#: number 0 is illegal in protobuf (``gil_container.parse_fields`` rejects it),
#: so 0 is unambiguous as "no root field".
UNATTRIBUTED = 0

#: Standing caveats, kept next to the code that could be misread without them.
DOES_NOT_PROVE: tuple[str, ...] = (
    "presence of an id's varint bytes is NOT proof the graph is well-formed, "
    "bound, or loadable",
    "an id can occur for unrelated reasons (the real baseline carries the "
    "graph id 5x in root field 9's sibling-level list); only the difference "
    "against a baseline is evidence",
    "changed root-field sizes say where bytes moved, not what they mean",
    "nothing here observes runtime behaviour -- that needs a playtest",
)


# --------------------------------------------------------------------------- #
# the container codec, loaded by path
# --------------------------------------------------------------------------- #

def _load_codec():
    """Import ``tools/beyond-save/gil_container.py`` -- its directory has a dash.

    The module is registered in ``sys.modules`` *before* ``exec_module``: the
    codec uses ``from __future__ import annotations``, and ``@dataclass``
    resolves its annotations through ``sys.modules[cls.__module__]`` at class
    creation time, which is ``None`` until the registration happens.
    """
    name = "_gil_container_for_graph_disk_verify"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, _CODEC_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load the container codec from {_CODEC_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: The container codec, exposed so callers and tests can build/parse with the
#: exact same authority this module uses.
gil_codec = _load_codec()


# --------------------------------------------------------------------------- #
# report types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RootFieldSize:
    """One root field's on-disk size before and after, both in encoded bytes."""

    number: int
    wire_type: int
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before

    @property
    def is_new(self) -> bool:
        return self.before == 0 and self.after > 0

    @property
    def is_removed(self) -> bool:
        return self.after == 0 and self.before > 0


@dataclass(frozen=True)
class GraphOnDiskReport:
    """What a read-only pass over one ``.gil`` found.  Nothing here is a verdict."""

    path: Path
    file_size: int
    payload_size: int
    subtype: int
    sha256: str

    graph_id: int
    graph_occurrences: int
    graph_occurrences_by_root_field: Mapping[int, int]
    graph_field_paths: tuple[str, ...]

    entity_id: int | None = None
    entity_occurrences: int | None = None
    entity_occurrences_by_root_field: Mapping[int, int] | None = None
    entity_field_paths: tuple[str, ...] | None = None

    baseline_path: Path | None = None
    baseline_file_size: int | None = None
    baseline_payload_size: int | None = None
    baseline_graph_occurrences: int | None = None
    baseline_graph_by_root_field: Mapping[int, int] | None = None
    baseline_entity_occurrences: int | None = None
    baseline_entity_by_root_field: Mapping[int, int] | None = None

    size_delta: int | None = None          # file bytes now - baseline file bytes
    payload_delta: int | None = None       # payload bytes now - baseline payload
    expected_size: int | None = None       # expected CURRENT file size, if given
    size_matches_expected: bool | None = None

    changed_root_fields: tuple[RootFieldSize, ...] = ()
    changed_root_delta_sum: int | None = None
    root_fields_cover_payload: bool = True

    notes: tuple[str, ...] = _field(default_factory=tuple)

    @property
    def graph_found(self) -> bool:
        """True when the graph id's varint bytes occur at least once.  Weak on purpose."""
        return self.graph_occurrences > 0

    @property
    def entity_found(self) -> bool | None:
        if self.entity_occurrences is None:
            return None
        return self.entity_occurrences > 0

    @property
    def root_fields_grew(self) -> tuple[RootFieldSize, ...]:
        return tuple(f for f in self.changed_root_fields if f.delta > 0)

    def summary(self) -> str:
        """A short human-readable block.  The caveats are part of the output."""
        lines = [
            f"file            {self.path}",
            f"size            {self.file_size} B (payload {self.payload_size} B, "
            f"subtype {self.subtype})",
            f"sha256          {self.sha256}",
            f"graph_id        {self.graph_id}: {self.graph_occurrences} varint "
            f"occurrence(s) {_fmt_by_root(self.graph_occurrences_by_root_field)}",
            f"  field paths   {list(self.graph_field_paths) or '(none found)'}",
        ]
        if self.entity_id is not None:
            lines.append(
                f"entity_id       {self.entity_id}: {self.entity_occurrences} varint "
                f"occurrence(s) {_fmt_by_root(self.entity_occurrences_by_root_field)}")
            lines.append(f"  field paths   {list(self.entity_field_paths or ()) or '(none found)'}")
        if self.baseline_path is not None:
            lines += [
                f"baseline        {self.baseline_path} "
                f"({self.baseline_file_size} B, payload {self.baseline_payload_size} B)",
                f"  baseline graph_id  {self.baseline_graph_occurrences} "
                f"{_fmt_by_root(self.baseline_graph_by_root_field)}",
            ]
            if self.entity_id is not None:
                lines.append(f"  baseline entity_id {self.baseline_entity_occurrences} "
                             f"{_fmt_by_root(self.baseline_entity_by_root_field)}")
            lines.append(f"  file delta    {_signed(self.size_delta)} B, "
                         f"payload delta {_signed(self.payload_delta)} B")
            if self.changed_root_fields:
                lines.append("  changed root fields:")
                for f in self.changed_root_fields:
                    lines.append(
                        f"    field {f.number:<3} wire {f.wire_type}  "
                        f"{f.before} -> {f.after} B ({_signed(f.delta)})"
                        + ("  [new]" if f.is_new else "")
                        + ("  [removed]" if f.is_removed else ""))
                lines.append(
                    f"    sum of deltas {_signed(self.changed_root_delta_sum)} B "
                    f"(payload delta {_signed(self.payload_delta)} B"
                    + (", consistent"
                       if self.changed_root_delta_sum == self.payload_delta else
                       ", INCONSISTENT") + ")")
            else:
                lines.append("  changed root fields: none (no root field changed size)")
        if self.expected_size is not None:
            lines.append(f"expected_size   {self.expected_size} B -> "
                         f"{'match' if self.size_matches_expected else 'MISMATCH'}")
        for note in self.notes:
            lines.append(f"note            {note}")
        lines.append("does NOT prove:")
        for caveat in DOES_NOT_PROVE:
            lines.append(f"  - {caveat}")
        return "\n".join(lines)


def _fmt_by_root(by_root: Mapping[int, int] | None) -> str:
    if not by_root:
        return "(no root field)"
    parts = []
    for number in sorted(by_root):
        label = f"root {number}" if number != UNATTRIBUTED else "unattributed"
        parts.append(f"{label} x{by_root[number]}")
    return "[" + ", ".join(parts) + "]"


def _signed(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+d}" if value else "0"


# --------------------------------------------------------------------------- #
# measurement
# --------------------------------------------------------------------------- #

def _root_spans(fields) -> list[tuple[int, int, int]]:
    """(number, start, end) byte spans of each root field in the payload.

    ``encode_fields`` reproduces ``parse_fields``'s input byte for byte, so the
    encoded length of one field *is* the number of payload bytes it occupies.
    """
    spans: list[tuple[int, int, int]] = []
    pos = 0
    for f in fields:
        size = len(gil_codec.encode_fields([f]))
        spans.append((f.number, pos, pos + size))
        pos += size
    return spans


def _root_number_at(spans: list[tuple[int, int, int]], offset: int) -> int:
    for number, start, end in spans:
        if start <= offset < end:
            return number
    return UNATTRIBUTED


def _count_occurrences(payload: bytes, spans, value: int):
    """Raw byte occurrences of ``value``'s varint, and their root-field bucket."""
    needle = gil_codec.write_varint(value)
    total = 0
    by_root: dict[int, int] = {}
    cursor = 0
    while True:
        hit = payload.find(needle, cursor)
        if hit < 0:
            break
        total += 1
        number = _root_number_at(spans, hit)
        by_root[number] = by_root.get(number, 0) + 1
        cursor = hit + 1  # overlapping matches count; this is a byte scan, not a tokenizer
    return total, by_root


def _field_paths_with_value(fields, value: int, _prefix=(), _depth: int = 0) -> tuple[str, ...]:
    """Dotted paths of parsed *field values* equal to ``value``.

    Best-effort: a length-delimited field that is not a message raises on parse
    and is skipped, so this can under-count relative to the byte scan.  It never
    over-counts -- every path returned is a real parsed varint/32/64-bit value.
    """
    if _depth > 32:
        return ()
    found: list[str] = []
    for f in fields:
        path = _prefix + (f.number,)
        if f.wire_type in (gil_codec.WIRE_VARINT, gil_codec.WIRE_32BIT, gil_codec.WIRE_64BIT):
            if f.value == value:
                found.append(".".join(str(n) for n in path))
        elif f.wire_type == gil_codec.WIRE_LENGTH:
            try:
                children = gil_codec.parse_fields(f.data or b"")
            except Exception:
                continue
            found.extend(_field_paths_with_value(children, value, path, _depth + 1))
    return tuple(found)


def _sizes_by_number(fields) -> dict[int, tuple[int, int]]:
    """number -> (wire_type, encoded size).  Root numbers are unique in practice."""
    out: dict[int, tuple[int, int]] = {}
    for f in fields:
        wire_type, size = f.wire_type, len(gil_codec.encode_fields([f]))
        if f.number in out:
            old_wire, old_size = out[f.number]
            out[f.number] = (old_wire, old_size + size)
        else:
            out[f.number] = (wire_type, size)
    return out


def _changed_root_fields(after_fields, before_fields) -> tuple[RootFieldSize, ...]:
    after = _sizes_by_number(after_fields)
    before = _sizes_by_number(before_fields)
    changed: list[RootFieldSize] = []
    for number in sorted(set(after) | set(before)):
        a_wire, a_size = after.get(number, (before.get(number, (0, 0))[0], 0))
        b_wire, b_size = before.get(number, (after.get(number, (0, 0))[0], 0))
        if a_size != b_size or a_wire != b_wire:
            changed.append(RootFieldSize(number=number, wire_type=a_wire,
                                         before=b_size, after=a_size))
    return tuple(changed)


# --------------------------------------------------------------------------- #
# the check
# --------------------------------------------------------------------------- #

def verify(
    gil_path,
    *,
    graph_id: int,
    entity_id: int | None = None,
    baseline=None,
    expected_size: int | None = None,
) -> GraphOnDiskReport:
    """Read one ``.gil`` read-only and report what its bytes say about ``graph_id``.

    ``baseline``      a path to the pre-write file.  When given, the root fields
                      whose encoded size changed are reported, and the counts
                      are put side by side with the baseline's -- the comparison
                      is the evidence, not the counts alone.
    ``expected_size`` the **current** file size you expect to observe, as a
                      single number when the bytes are unavailable.  It can
                      confirm the file is the size you think; it cannot localize
                      which root fields changed (pass ``baseline`` for that).

    Raises ``FileNotFoundError`` for a missing file and
    ``gil_container.ContainerError`` for bytes that are not a Beyond container.
    """
    path = Path(gil_path)
    if not path.is_file():
        raise FileNotFoundError(f"not a file: {path}")
    blob = path.read_bytes()
    container = gil_codec.decode_container(blob)
    payload = container.payload
    fields = gil_codec.parse_fields(payload)
    spans = _root_spans(fields)
    covered = spans[-1][2] == len(payload) if spans else len(payload) == 0

    graph_total, graph_by_root = _count_occurrences(payload, spans, graph_id)
    graph_paths = _field_paths_with_value(fields, graph_id)

    entity_total = entity_by_root = entity_paths = None
    if entity_id is not None:
        entity_total, entity_by_root = _count_occurrences(payload, spans, entity_id)
        entity_paths = _field_paths_with_value(fields, entity_id)

    baseline_path = Path(baseline) if baseline is not None else None
    b_file = b_payload = b_graph_total = b_entity_total = None
    b_graph_by = b_entity_by = None
    size_delta = payload_delta = delta_sum = None
    changed: tuple[RootFieldSize, ...] = ()

    if baseline_path is not None:
        b_blob = baseline_path.read_bytes()
        b_container = gil_codec.decode_container(b_blob)
        b_fields = gil_codec.parse_fields(b_container.payload)
        b_spans = _root_spans(b_fields)
        b_file, b_payload = len(b_blob), len(b_container.payload)
        b_graph_total, b_graph_by = _count_occurrences(b_container.payload, b_spans, graph_id)
        if entity_id is not None:
            b_entity_total, b_entity_by = _count_occurrences(b_container.payload, b_spans, entity_id)
        changed = _changed_root_fields(fields, b_fields)
        delta_sum = sum(f.delta for f in changed)
        size_delta = len(blob) - b_file
        payload_delta = len(payload) - b_payload

    matches_expected = None if expected_size is None else (len(blob) == expected_size)

    notes: list[str] = []
    if baseline_path is None:
        notes.append("no baseline supplied: this run reports presence counts only, "
                     "not what changed. A nonzero count on its own is not evidence.")
    if entity_id is None:
        notes.append("entity_id not supplied: entity occurrences were not computed.")
    if not covered:
        notes.append("root field spans do not exactly cover the payload; the "
                     "per-root-field attribution may be incomplete.")
    if b_graph_by is not None:
        already = sorted(set(graph_by_root) & set(b_graph_by))
        if already:
            notes.append(
                f"root field(s) {already} already carried graph_id {graph_id} in the "
                f"baseline -- for those, a nonzero count is not evidence of a new graph.")
        fresh = sorted(number for number in graph_by_root if number not in b_graph_by)
        if fresh:
            notes.append(
                f"graph_id {graph_id} appears in root field(s) {fresh} now and not in "
                f"the baseline -- that is the change to look at.")
    if expected_size is not None and not matches_expected:
        notes.append(f"file size {len(blob)} B != expected_size {expected_size} B "
                     f"({_signed(len(blob) - expected_size)} B).")

    return GraphOnDiskReport(
        path=path,
        file_size=len(blob),
        payload_size=len(payload),
        subtype=container.subtype,
        sha256=hashlib.sha256(blob).hexdigest(),
        graph_id=graph_id,
        graph_occurrences=graph_total,
        graph_occurrences_by_root_field=graph_by_root,
        graph_field_paths=graph_paths,
        entity_id=entity_id,
        entity_occurrences=entity_total,
        entity_occurrences_by_root_field=entity_by_root,
        entity_field_paths=entity_paths,
        baseline_path=baseline_path,
        baseline_file_size=b_file,
        baseline_payload_size=b_payload,
        baseline_graph_occurrences=b_graph_total,
        baseline_graph_by_root_field=b_graph_by,
        baseline_entity_occurrences=b_entity_total,
        baseline_entity_by_root_field=b_entity_by,
        size_delta=size_delta,
        payload_delta=payload_delta,
        expected_size=expected_size,
        size_matches_expected=matches_expected,
        changed_root_fields=changed,
        changed_root_delta_sum=delta_sum,
        root_fields_cover_payload=covered,
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- #
# CLI -- the re-runnable command
# --------------------------------------------------------------------------- #

def _by_root_json(by_root: Mapping[int, int] | None):
    """Sorted ``[{root_field, count}]`` -- int keys would stringify in JSON."""
    if by_root is None:
        return None
    return [{"root_field": number, "count": by_root[number]} for number in sorted(by_root)]


def _as_json(report: GraphOnDiskReport) -> dict:
    """An explicit dict -- no generic dataclass dump, so the shape is inspectable."""
    return {
        "path": str(report.path),
        "file_size": report.file_size,
        "payload_size": report.payload_size,
        "subtype": report.subtype,
        "sha256": report.sha256,
        "graph_id": report.graph_id,
        "graph_found": report.graph_found,
        "graph_occurrences": report.graph_occurrences,
        "graph_occurrences_by_root_field": _by_root_json(report.graph_occurrences_by_root_field),
        "graph_field_paths": list(report.graph_field_paths),
        "entity_id": report.entity_id,
        "entity_found": report.entity_found,
        "entity_occurrences": report.entity_occurrences,
        "entity_occurrences_by_root_field": _by_root_json(report.entity_occurrences_by_root_field),
        "entity_field_paths": (None if report.entity_field_paths is None
                               else list(report.entity_field_paths)),
        "baseline_path": None if report.baseline_path is None else str(report.baseline_path),
        "baseline_file_size": report.baseline_file_size,
        "baseline_payload_size": report.baseline_payload_size,
        "baseline_graph_occurrences": report.baseline_graph_occurrences,
        "baseline_graph_by_root_field": _by_root_json(report.baseline_graph_by_root_field),
        "baseline_entity_occurrences": report.baseline_entity_occurrences,
        "baseline_entity_by_root_field": _by_root_json(report.baseline_entity_by_root_field),
        "size_delta": report.size_delta,
        "payload_delta": report.payload_delta,
        "expected_size": report.expected_size,
        "size_matches_expected": report.size_matches_expected,
        "changed_root_fields": [
            {"number": f.number, "wire_type": f.wire_type, "before": f.before,
             "after": f.after, "delta": f.delta, "is_new": f.is_new,
             "is_removed": f.is_removed}
            for f in report.changed_root_fields
        ],
        "changed_root_delta_sum": report.changed_root_delta_sum,
        "root_fields_cover_payload": report.root_fields_cover_payload,
        "notes": list(report.notes),
        "does_not_prove": list(DOES_NOT_PROVE),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_graph_on_disk",
        description="Read-only check: are a graph id / entity id present in a .gil, "
                    "and which root fields changed size vs a baseline?")
    parser.add_argument("--gil", required=True, help="the .gil to read (never written)")
    parser.add_argument("--graph-id", required=True, type=int,
                        help="the graphId to look for, e.g. 1073741829")
    parser.add_argument("--entity-id", type=int, default=None,
                        help="the entityId to look for, e.g. 1077936129")
    parser.add_argument("--baseline", default=None,
                        help="the pre-write .gil, to diff root-field sizes against")
    parser.add_argument("--expected-size", type=int, default=None,
                        help="the CURRENT file size you expect, in bytes")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = verify(
        args.gil,
        graph_id=args.graph_id,
        entity_id=args.entity_id,
        baseline=args.baseline,
        expected_size=args.expected_size,
    )
    if args.json:
        print(json.dumps(_as_json(report), ensure_ascii=False, indent=2))
    else:
        print(report.summary())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
