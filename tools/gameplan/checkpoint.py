"""One command that answers "where is the demo right now?" -- as a diffable record.

WHY THIS EXISTS
    The demo spans four artefacts that live in four different places:

      * the **live level** -- open right now in ``YuanShen.exe``; readable only
        through the resident helper (:mod:`tools.gameplan.live`).
      * the **graph in the editor** -- in ``BeyondEditor.exe``'s memory, readable
        only through a read-only ``author.py graph inspect`` (``tools/gameplan/
        cli.py:197`` ``cmd_graph_status``).
      * the **``.gil`` on disk** -- what a native ``save`` actually persisted;
        readable with the graph-on-disk verifier
        (:mod:`tools.gameplan.verify_graph_on_disk`).
      * the **directory defects** -- ``root field 6``'s tab list, whose damage
        (:mod:`tools.beyond-save.level_directory`) is invisible to every other
        reader.

    Today "where are we?" means re-reading each of those by hand.  This module
    reads all four and writes one JSON file, so a later run can be **diffed**
    against it.  That is the whole point: a checkpoint is a *comparison point*,
    not a status line.

THE THREE LAYERS (``CLAUDE.md:25``) STAY SEPARATE
    Every section records *how* it was read, and an **unavailable** section is
    never dropped -- it stays in the report carrying a named, machine-readable
    ``reason``.  A checkpoint therefore distinguishes:

      * "this source was not read" (``available: false`` + ``reason``),
      * "this source was read, and it is not in the good state" (``available:
        true, ok: false`` + ``reason``),
      * "this source was read and is good" (``available: true, ok: true``).

    Silently omitting a source would collapse the first two into "nothing
    happened", which is exactly the conflation the doctrine forbids.

WHAT IT DOES **NOT** DO
    * It does not prove anything is *playable*.  ``ok`` per section is: the live
      level is identity-verified; the editor graph inspected; the graph id's
      bytes occur in the ``.gil``; the directory has no defects.  None of that is
      a playtest.  The ``.gil`` section carries ``verify_graph_on_disk``'s own
      ``DOES_NOT_PROVE`` caveats verbatim.
    * It does not read a checkpoint's *file* into a verdict -- two checkpoints
      are compared leaf by leaf (:func:`diff`), and the timestamp is ignored by
      default because it differs on every run by construction.

READ / WRITE
    The only writes are checkpoint JSON files under
    ``.runtime/scratch/checkpoints/<stamp>.json`` (``outputs-stay-inside-the-
    project``).  Every source this reads is read-only; the tool never opens a
    ``.gil`` for writing and never dispatches anything but a read.

The four source readers are **injected**, so the entire suite runs offline: no
bridge, no game, no editor, no network -- see ``tests/test_checkpoint.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from . import live
from .builder import request_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CHECKPOINT_DIR = _REPO_ROOT / ".runtime" / "scratch" / "checkpoints"
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"

# ``level_directory`` lives under tools/beyond-save beside ``gil_container`` and
# reaches it as a sibling module, so that directory must be importable -- the
# same reach ``bounds.py:63`` uses.
_BEYOND_SAVE = _REPO_ROOT / "tools" / "beyond-save"
if str(_BEYOND_SAVE) not in sys.path:
    sys.path.insert(0, str(_BEYOND_SAVE))

#: The four sources every checkpoint MUST carry, in report order.  ``collect``
#: starts with all four present-and-unavailable and then fills each, so no code
#: path can drop one by accident.
SECTION_NAMES: tuple[str, ...] = (
    "liveLevel",
    "editorGraph",
    "graphOnDisk",
    "directoryDefects",
)

#: A live reader is ``live.Runner`` (argv -> (returncode, stdout)); a graph reader
#: is the ``builder.Runner`` shape (argv -> parsed dict); both are injected.
LiveRunner = Callable[[list[str]], "tuple[int, str]"]
GraphRunner = Callable[[list[str]], dict]

#: A "loader" resolves an optional module to ``(module, None)`` or
#: ``(None, reason)``.  Injectable so the module-absent path is testable without
#: deleting a file from the tree.
ModuleLoader = Callable[[], "tuple[Any, str | None]"]


# --------------------------------------------------------------------------- #
# section shape -- one small builder, so "never silently omit" is structural
# --------------------------------------------------------------------------- #

def section(name: str, *, available: bool, ok: bool, reason: str | None,
            data: Mapping[str, Any] | None = None) -> dict:
    """Build one source's report block.  ``reason`` is required when not ok."""
    if available and not ok and not reason:
        raise ValueError(f"section {name!r} is not ok but carries no reason")
    if not available and not reason:
        raise ValueError(f"section {name!r} is unavailable but carries no reason")
    return {
        "name": name,
        "available": bool(available),
        "ok": bool(ok),
        "reason": reason,
        "data": None if data is None else dict(data),
    }


def _unavailable(name: str, reason: str) -> dict:
    return section(name, available=False, ok=False, reason=reason, data=None)


def _guarded(name: str, reader: Callable[[], dict]) -> dict:
    """Run one reader, turning any raise into a named unavailable section.

    A collector that crashes must not take the whole checkpoint down, and must
    not disappear either: the exception's type and message become the reason.
    """
    try:
        result = reader()
    except Exception as error:  # noqa: BLE001 -- the point is to name ANY failure
        return _unavailable(name, f"{name} collector raised "
                                  f"{type(error).__name__}: {error}")
    if not isinstance(result, dict) or result.get("name") != name:
        return _unavailable(name, f"{name} collector returned a malformed section")
    return result


# --------------------------------------------------------------------------- #
# the four source readers
# --------------------------------------------------------------------------- #

def _live_reader(queue_dir, live_runner: LiveRunner | None,
                 live_reader: Callable[[], Any] | None, enabled: bool) -> dict:
    """Read the live sandbox via :mod:`tools.gameplan.live` (injectable runner)."""
    if not enabled:
        return _unavailable("liveLevel", "liveLevel: live read disabled")
    if live_reader is not None:
        state = live_reader()
    else:
        state = live.read_live(queue_dir, runner=live_runner)

    if isinstance(state, live.LiveState):
        summary, ok, reason = state.summary(), state.ok, state.reason
    elif isinstance(state, Mapping):
        summary = dict(state)
        ok = bool(state.get("ok"))
        reason = state.get("reason")
    else:
        raise TypeError(f"live reader returned {type(state).__name__}")

    if ok:
        return section("liveLevel", available=True, ok=True, reason=None, data=summary)
    return section("liveLevel", available=True, ok=False,
                   reason=reason or "live level read but not identity-verified",
                   data=summary)


def _editor_graph_reader(graph_runner: GraphRunner | None, *, name, graph_id,
                         run_id, queue_dir, python: str) -> dict:
    """Inspect the graph in the editor with a read-only ``author.py graph inspect``.

    The argv is built exactly the way ``cli.py:232-240`` (``cmd_graph_status``)
    builds it, including the request id derived from ``(name, graph_id, run_id)``
    -- a graph id is a function of the save (``level-ids-are-per-save-never-
    pinned``), so it is never inferred.  Only ``inspect`` is ever emitted.
    """
    if graph_runner is None:
        return _unavailable("editorGraph", "editorGraph: no inspect runner supplied")
    if not name:
        return _unavailable("editorGraph",
                            "editorGraph: no graph name supplied (author.py graph "
                            "inspect is keyed by name)")
    if graph_id is None:
        return _unavailable("editorGraph", "editorGraph: no graph id supplied")
    if not run_id:
        return _unavailable("editorGraph",
                            "editorGraph: no bridge run id supplied (it is never inferred)")

    request = request_id("graph-status", "inspect", name, graph_id, run_id)
    argv = [
        python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", str(queue_dir),
        "graph", "inspect",
        "--request-id", request,
        "--run-id", str(run_id),
        "--name", str(name),
        "--graph-id", str(graph_id),
    ]
    if argv[argv.index("graph") + 1] != "inspect":
        raise AssertionError("checkpoint must only ever dispatch `graph inspect`")

    result = graph_runner(argv)
    if not isinstance(result, dict):
        return _unavailable("editorGraph",
                            f"editorGraph: runner returned {type(result).__name__}, "
                            f"not a parsed receipt")

    backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    nodes = [n for n in (backend.get("nodes") or []) if isinstance(n, dict)]
    definitions = [n.get("definitionId") for n in nodes]
    bound = [int(entity) for entity in (backend.get("boundEntityIds") or [])]

    data = {
        "graphId": graph_id,
        "name": name,
        "runId": run_id,
        "requestId": request,
        "status": backend.get("status"),
        "nodeCount": backend.get("nodeCount", len(nodes)),
        "nodeDefinitionIds": definitions,
        "boundEntityIds": bound,
        "nodes": nodes,
    }
    if result.get("ok") is True:
        return section("editorGraph", available=True, ok=True, reason=None, data=data)
    return section("editorGraph", available=True, ok=False,
                   reason=f"inspect refused: {result.get('error') or result}",
                   data=data)


def _graph_on_disk_reader(verify_module, verify_loader: ModuleLoader | None,
                          *, gil_path, graph_id, entity_id, baseline,
                          expected_size) -> dict:
    """Read the ``.gil`` with the graph-on-disk verifier, present or absent.

    The verifier is another agent's module; the import is therefore optional and
    its failure becomes a NAMED reason on the section, not a silent zero.
    """
    if gil_path is None:
        return _unavailable("graphOnDisk", "graphOnDisk: no .gil path supplied")
    if graph_id is None:
        return _unavailable("graphOnDisk",
                            "graphOnDisk: no graph id supplied (nothing to look for)")

    module = verify_module
    if module is None:
        module, reason = (verify_loader or load_verify_module)()
        if module is None:
            return _unavailable("graphOnDisk", reason or
                                "graphOnDisk: verify_graph_on_disk unavailable")

    report = module.verify(
        gil_path,
        graph_id=int(graph_id),
        entity_id=None if entity_id is None else int(entity_id),
        baseline=baseline,
        expected_size=expected_size,
    )
    data = {
        "path": str(report.path),
        "fileSize": report.file_size,
        "payloadSize": report.payload_size,
        "subtype": report.subtype,
        "sha256": report.sha256,
        "graphId": report.graph_id,
        "graphFound": report.graph_found,
        "graphOccurrences": report.graph_occurrences,
        "graphOccurrencesByRootField": [
            [number, count] for number, count
            in sorted((report.graph_occurrences_by_root_field or {}).items())
        ],
        "entityId": report.entity_id,
        "entityOccurrences": report.entity_occurrences,
        "sizeDelta": report.size_delta,
        "payloadDelta": report.payload_delta,
        "changedRootFields": [
            {"number": f.number, "before": f.before, "after": f.after, "delta": f.delta}
            for f in report.changed_root_fields
        ],
        "notes": list(report.notes),
        "doesNotProve": list(getattr(module, "DOES_NOT_PROVE", ())),
    }
    if report.graph_found:
        return section("graphOnDisk", available=True, ok=True, reason=None, data=data)
    return section("graphOnDisk", available=True, ok=False,
                   reason=f"graph id {graph_id} not found in {report.path}",
                   data=data)


def _directory_reader(directory_module, directory_loader: ModuleLoader | None,
                      directory_reader_fn: Callable[[Any], Any] | None,
                      directory_path) -> dict:
    """Read the ``root field 6`` tab directory and report its defects."""
    if directory_path is None:
        return _unavailable("directoryDefects", "directoryDefects: no .gil path supplied")

    reader = directory_reader_fn
    if reader is None:
        module = directory_module
        if module is None:
            module, reason = (directory_loader or load_directory_module)()
            if module is None:
                return _unavailable("directoryDefects", reason or
                                    "directoryDefects: level_directory unavailable")
        reader = module.check_directory

    defects = list(reader(directory_path))
    data = {
        "path": str(directory_path),
        "defectCount": len(defects),
        "defects": [
            {"code": getattr(d, "code", None),
             "index": getattr(d, "index", None),
             "detail": getattr(d, "detail", str(d))}
            for d in defects
        ],
    }
    if not defects:
        return section("directoryDefects", available=True, ok=True, reason=None, data=data)
    return section("directoryDefects", available=True, ok=False,
                   reason=f"{len(defects)} defect(s) in the root-field-6 directory",
                   data=data)


# --------------------------------------------------------------------------- #
# optional-module resolution -- named reasons, never a bare failure
# --------------------------------------------------------------------------- #

def load_verify_module() -> tuple[Any, str | None]:
    """Resolve :mod:`tools.gameplan.verify_graph_on_disk`, or a named reason."""
    try:
        from . import verify_graph_on_disk
    except Exception as error:  # noqa: BLE001
        return None, (f"graphOnDisk: verify_graph_on_disk unavailable "
                      f"({type(error).__name__}: {error})")
    return verify_graph_on_disk, None


def load_directory_module() -> tuple[Any, str | None]:
    """Resolve :mod:`tools.beyond-save.level_directory`, or a named reason."""
    try:
        import level_directory
    except Exception as error:  # noqa: BLE001
        return None, (f"directoryDefects: tools/beyond-save/level_directory "
                      f"unavailable ({type(error).__name__}: {error})")
    return level_directory, None


# --------------------------------------------------------------------------- #
# collect -- the one call
# --------------------------------------------------------------------------- #

def _now_utc(now=None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    value = now() if callable(now) else now
    if not isinstance(value, datetime):
        raise TypeError(f"now must be a datetime or a callable, got {type(value).__name__}")
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(moment: datetime | None = None) -> str:
    """The filename stamp for a checkpoint: ``YYYYMMDDTHHMMSSZ`` (UTC, sortable)."""
    return _now_utc(moment).strftime("%Y%m%dT%H%M%SZ")


def _stages(sections: Mapping[str, dict]) -> dict:
    """Turn the four sections into the demo's "which step are we on" flags."""
    live_section = sections["liveLevel"]
    graph_section = sections["editorGraph"]
    disk_section = sections["graphOnDisk"]
    directory_section = sections["directoryDefects"]
    graph_data = graph_section.get("data") or {}
    return {
        "levelKnown": bool(live_section["available"] and live_section["ok"]),
        "graphInEditor": bool(graph_section["available"] and graph_section["ok"]
                              and (graph_data.get("nodeCount") or 0) > 0),
        "graphBound": bool(graph_section["available"] and graph_section["ok"]
                           and (graph_data.get("boundEntityIds") or [])),
        "graphOnDisk": bool(disk_section["available"] and disk_section["ok"]),
        "directoryClean": bool(directory_section["available"] and directory_section["ok"]),
    }


def collect(
    *,
    queue_dir: str | Path | None = None,
    live_runner: LiveRunner | None = None,
    live_reader: Callable[[], Any] | None = None,
    live_enabled: bool = True,
    graph_runner: GraphRunner | None = None,
    graph_name: str | None = None,
    graph_id: int | None = None,
    run_id: str | None = None,
    python: str = "python",
    gil_path: str | Path | None = None,
    entity_id: int | None = None,
    baseline: str | Path | None = None,
    expected_size: int | None = None,
    verify_module: Any | None = None,
    verify_loader: ModuleLoader | None = None,
    directory_path: str | Path | None = None,
    directory_module: Any | None = None,
    directory_loader: ModuleLoader | None = None,
    directory_reader_fn: Callable[[Any], Any] | None = None,
    now=None,
) -> dict:
    """Read the four demo sources and return one diffable checkpoint dict.

    Every argument is injected: the live and editor-graph **runners**, and the
    optional modules/readers for the ``.gil`` and directory.  With everything
    injected nothing shells out and no file outside a caller's temp dir is
    touched -- which is how the tests stay offline.

    A source whose inputs are missing, whose optional module is absent, or whose
    reader raises is NOT dropped: it appears in ``sections`` with
    ``available: false`` and a named ``reason``, and its name is listed in the
    top-level ``unavailable`` array.
    """
    queue = Path(queue_dir) if queue_dir is not None else _DEFAULT_QUEUE
    sections: dict[str, dict] = {
        name: _unavailable(name, f"{name}: not collected")
        for name in SECTION_NAMES
    }

    sections["liveLevel"] = _guarded(
        "liveLevel",
        lambda: _live_reader(queue, live_runner, live_reader, live_enabled))
    sections["editorGraph"] = _guarded(
        "editorGraph",
        lambda: _editor_graph_reader(graph_runner, name=graph_name, graph_id=graph_id,
                                     run_id=run_id, queue_dir=queue, python=python))
    sections["graphOnDisk"] = _guarded(
        "graphOnDisk",
        lambda: _graph_on_disk_reader(verify_module, verify_loader, gil_path=gil_path,
                                      graph_id=graph_id, entity_id=entity_id,
                                      baseline=baseline, expected_size=expected_size))
    sections["directoryDefects"] = _guarded(
        "directoryDefects",
        lambda: _directory_reader(directory_module, directory_loader, directory_reader_fn,
                                  directory_path))

    return {
        "kind": "gameplan-checkpoint",
        "version": 1,
        "createdUtc": _iso_utc(_now_utc(now)),
        "sections": sections,
        "stages": _stages(sections),
        "unavailable": [n for n in SECTION_NAMES if not sections[n]["available"]],
        "notOk": [n for n in SECTION_NAMES
                  if sections[n]["available"] and not sections[n]["ok"]],
        "ok": all(sections[n]["available"] and sections[n]["ok"] for n in SECTION_NAMES),
    }


# --------------------------------------------------------------------------- #
# persistence -- compare two runs
# --------------------------------------------------------------------------- #

def checkpoint_dir(directory: str | Path | None = None) -> Path:
    return Path(directory) if directory is not None else _DEFAULT_CHECKPOINT_DIR


def dumps(checkpoint: Mapping[str, Any]) -> str:
    return json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def loads(text: str) -> dict:
    return json.loads(text)


def _unique_path(directory: Path, moment: datetime) -> Path:
    base = stamp(moment)
    candidate = directory / f"{base}.json"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{base}-{counter:02d}.json"
        counter += 1
    return candidate


def write_checkpoint(checkpoint: Mapping[str, Any], *, directory: str | Path | None = None,
                     path: str | Path | None = None, now=None) -> Path:
    """Write a checkpoint under ``<directory>/<stamp>.json``; returns the path."""
    if path is None:
        target_dir = checkpoint_dir(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_path(target_dir, _now_utc(now))
    else:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps(checkpoint), encoding="utf-8")
    return target


def read_checkpoint(path: str | Path) -> dict:
    return loads(Path(path).read_text(encoding="utf-8"))


def list_checkpoints(directory: str | Path | None = None) -> list[Path]:
    target_dir = checkpoint_dir(directory)
    if not target_dir.is_dir():
        return []
    return sorted(target_dir.glob("*.json"))


def latest_checkpoint(directory: str | Path | None = None) -> Path | None:
    found = list_checkpoints(directory)
    return found[-1] if found else None


def collect_and_write(*, directory: str | Path | None = None, path=None, now=None,
                      **kwargs) -> tuple[dict, Path]:
    """Collect, then write.  Convenience for the CLI and the demo driver."""
    checkpoint = collect(now=now, **kwargs)
    written = write_checkpoint(checkpoint, directory=directory, path=path, now=now)
    return checkpoint, written


def _flatten(value: Any, prefix: str = "") -> dict:
    """Flatten nested dicts/lists to ``{dotted.path: leaf}`` for comparison.

    Empty containers stay as leaves (an empty list is a value, not "no field"),
    so removing the last element of a list shows up as a change, not a vanish.
    """
    out: dict[str, Any] = {}
    if isinstance(value, dict) and value:
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten(value[key], path))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            out.update(_flatten(item, f"{prefix}[{index}]"))
    else:
        out[prefix] = value
    return out


def _ignored(path: str, ignore: set[str]) -> bool:
    return any(path == field or path.startswith(field + ".")
               or path.startswith(field + "[") for field in ignore)


def diff(before: Mapping[str, Any], after: Mapping[str, Any], *,
         ignore: tuple[str, ...] = ("createdUtc",)) -> dict:
    """Leaf-by-leaf diff of two checkpoints.

    ``ignore`` defaults to ``createdUtc`` because two real runs are *always*
    separated in time; comparing timestamps would drown the state change the
    diff exists to surface.  Every other leaf is compared, including ones added
    or removed, so a source that went from present to absent shows up as a
    removal rather than as "unchanged".
    """
    flat_before = _flatten(before)
    flat_after = _flatten(after)
    ignore_set = set(ignore)
    changed: dict[str, dict] = {}
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    for path in sorted(set(flat_before) | set(flat_after)):
        if _ignored(path, ignore_set):
            continue
        if path not in flat_after:
            removed[path] = flat_before[path]
        elif path not in flat_before:
            added[path] = flat_after[path]
        elif flat_before[path] != flat_after[path]:
            changed[path] = {"before": flat_before[path], "after": flat_after[path]}
    return {
        "clean": not (changed or added or removed),
        "changed": changed,
        "added": added,
        "removed": removed,
        "changedCount": len(changed),
        "addedCount": len(added),
        "removedCount": len(removed),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--queue-dir", default=str(_DEFAULT_QUEUE))
    parser.add_argument("--python", default="python")
    parser.add_argument("--no-live", action="store_true",
                        help="do not read the live sandbox")
    parser.add_argument("--graph-name", default=None,
                        help="MW_API_… graph name; required to inspect the editor graph")
    parser.add_argument("--graph-id", type=int, default=None, help="uint32 graph id")
    parser.add_argument("--run-id", default=None, help="live bridge run id (UUID)")
    parser.add_argument("--gil", default=None, help="the .gil to check on disk")
    parser.add_argument("--entity-id", type=int, default=None)
    parser.add_argument("--baseline", default=None, help="the pre-write .gil, to diff against")
    parser.add_argument("--expected-size", type=int, default=None)
    parser.add_argument("--directory", default=None,
                        help="the .gil whose root-field-6 tab directory to check")
    parser.add_argument("--checkpoint-dir", default=None,
                        help=f"where to write (default: {_DEFAULT_CHECKPOINT_DIR})")


def _cmd_collect(args) -> int:
    from .builder import subprocess_runner as graph_subprocess_runner

    live_runner = None if args.no_live else live.subprocess_runner()
    graph_runner = None
    if args.graph_name or args.graph_id or args.run_id:
        graph_runner = graph_subprocess_runner(args.python)

    checkpoint = collect(
        queue_dir=args.queue_dir,
        live_runner=live_runner,
        live_enabled=not args.no_live,
        graph_runner=graph_runner,
        graph_name=args.graph_name,
        graph_id=args.graph_id,
        run_id=args.run_id,
        python=args.python,
        gil_path=args.gil,
        entity_id=args.entity_id,
        baseline=args.baseline,
        expected_size=args.expected_size,
        directory_path=args.directory,
    )
    print(dumps(checkpoint), end="")
    if not args.no_write:
        written = write_checkpoint(checkpoint, directory=args.checkpoint_dir)
        print(f"# wrote {written}", file=sys.stderr)
    return 0 if checkpoint["ok"] else 1


def _cmd_diff(args) -> int:
    before = read_checkpoint(args.before)
    after = read_checkpoint(args.after)
    report = diff(before, after, ignore=tuple(args.ignore))
    print(dumps(report), end="")
    return 0 if report["clean"] else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gameplan checkpoint",
        description="Read the four demo artefacts into one diffable JSON checkpoint.")
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect", help="read the sources and write a checkpoint")
    collect_parser.add_argument("--no-write", action="store_true",
                                help="print only; write no checkpoint file")
    _add_source_args(collect_parser)
    collect_parser.set_defaults(func=_cmd_collect)

    diff_parser = sub.add_parser("diff", help="diff two checkpoint files")
    diff_parser.add_argument("before")
    diff_parser.add_argument("after")
    diff_parser.add_argument("--ignore", action="append", default=["createdUtc"],
                             help="a dotted leaf to ignore (repeatable; default: createdUtc)")
    diff_parser.set_defaults(func=_cmd_diff)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


__all__ = [
    "SECTION_NAMES",
    "checkpoint_dir",
    "collect",
    "collect_and_write",
    "diff",
    "dumps",
    "latest_checkpoint",
    "list_checkpoints",
    "load_directory_module",
    "load_verify_module",
    "loads",
    "main",
    "read_checkpoint",
    "section",
    "stamp",
    "write_checkpoint",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
