"""Sweep a level's entities for the components a human configured, one dispatch each.

WHAT THIS IS
------------
The bridge's ``inspect-entity-components`` op reads **one** entity by registry id and
returns that entity's component rows straight off the live 7.1 editor model
(``tools/editor-bridge/Adapter/EntityComponentProbe.cs:124``).  It is read-only: the
adapter sets ``nativeMutationInvoked``/``localModelWritten``/``sentToGame`` all false
(:168-172).  There is no bulk form, so "what components did a human put on this level"
is answered by running the op once per entity.

This module is that loop, made testable: :func:`sweep` takes an **injected runner**, so
the whole sweep runs offline against a fake, and the production runner is a two-line
subprocess shim (:func:`subprocess_runner`, the same shape ``tools/gameplan/live.py``
uses).

THE ONE RULE
------------
A reply that FAILED must never read back as "this entity has no components".  Those are
different answers and conflating them is how a sweep quietly reports "nothing configured"
for an entity it never actually read.  So:

* ``rows == ()`` (a tuple) means the probe ran and the entity genuinely has zero
  components (``ok: true``, ``componentCount: 0``).
* ``rows is None`` plus a named ``error``/``kind`` means anything else: a refusal, a
  malformed reply, a runner-level error, a timeout.  :class:`EntityResult` enforces the
  invariant in ``__post_init__`` so a failed result cannot be constructed with rows.

WIRE SHAPE (verified, not guessed)
----------------------------------
Request: ``python elevated-request.py [--queue-dir DIR] call --op inspect-entity-components
--entity-id N --run-id R [--timeout S]`` (``tools/editor-bridge/elevated-request.py:11,
:236-240, :584-586``).  ``--queue-dir`` is a top-level flag and MUST precede ``call``.

Reply (the runner hands back the bridge's raw line, ``call-bridge.ps1:67-70``)::

    {"ok": true, "status": "entity-components-editor-model-read-only",
     "entityId": 123, "entityName": "...", "componentType": "...",
     "componentCount": 2, "components": [{"id": 5, "enabled": true, "x": 1.0, "y": 2.0}, ...],
     "componentIdSpace": "editor-enum-value-or-native-index-UNVERIFIED", ...}

A refusal arrives two ways and both are failures here:

* a bridge-level refusal: exit 1 with a JSON ``{"ok": false, "error": "<CODE>"}``
  (``elevated-request.py:671`` returns non-zero when ``ok`` is not literal ``true``);
* a runner-level throw: exit non-zero with a message and no JSON
  (``elevated-request.py:127-128``).

CHUNKING
--------
Every dispatch re-hashes the compatibility pins (``call-bridge.ps1:16``, measured ~16 s)
and every call is bounded by the run's 5-minute scope lease (``new-scope.ps1:27``,
``AddMinutes(5)``).  A sweep long enough to outlive one lease must be split into chunks,
each run under a freshly minted lease (:func:`dispatches_per_lease`, :func:`chunk_entities`).

Nothing in this module dispatches anything by itself.  :func:`sweep` only calls the
runner it is handed; the CLI defaults to printing the human plan.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
_ELEVATED_REQUEST = _REPO_ROOT / "tools" / "editor-bridge" / "elevated-request.py"
DEFAULT_PYTHON = "python"

#: The one op this module issues.  Spelled exactly; ``call-bridge.ps1`` matches it
#: case-sensitively (``-ceq``).
COMPONENT_OP = "inspect-entity-components"

#: A runner takes a full argv and returns ``(returncode, combined_output)``.  Injected so
#: the whole sweep is testable offline; the production runner shells out.
Runner = Callable[[list[str]], "tuple[int, str]"]

# --- lease math constants (see the module docstring) --------------------------------
DISPATCH_SECONDS = 16.0        # ~16 s pin re-hash per dispatch (call-bridge.ps1:16)
LEASE_SECONDS = 300.0          # 5-minute scope lease (new-scope.ps1:27 AddMinutes(5))
LEASE_RESERVE_SECONDS = 60.0   # headroom so the last dispatch finishes before SCOPE_EXPIRED

# --- result kinds (the vocabulary ``EntityResult.kind`` uses) -----------------------
KIND_COMPONENTS = "components"      # ok: rows is a (possibly empty) tuple
KIND_REFUSED = "refused"            # {"ok": false, "error": ...}
KIND_MALFORMED = "malformed"        # JSON present but not a well-formed component reply
KIND_RUNNER_ERROR = "runner-error"  # non-zero exit, no JSON (a raised/conditional code)
KIND_TIMEOUT = "timeout"            # queue reply carried "pending": true

_FAILED_KINDS = (KIND_REFUSED, KIND_MALFORMED, KIND_RUNNER_ERROR, KIND_TIMEOUT)


@dataclass(frozen=True)
class ComponentRow:
    """One configured component, exactly as the adapter reports it."""

    id: int
    enabled: bool
    x: float
    y: float


@dataclass(frozen=True)
class EntityResult:
    """The answer for one entity: rows, or a named error.  Never both, never neither.

    ``kind`` is one of the module's ``KIND_*`` constants.  ``rows`` is a tuple for
    :data:`KIND_COMPONENTS` (empty when the entity genuinely has no components) and
    ``None`` for every failure; ``error`` is a short machine-readable string on failure
    and ``None`` on success.
    """

    entity_id: int
    kind: str
    rows: "tuple[ComponentRow, ...] | None"
    error: "str | None"

    def __post_init__(self) -> None:
        if self.kind == KIND_COMPONENTS:
            if self.rows is None or self.error is not None:
                raise ValueError("components result must carry rows and no error")
        elif self.kind in _FAILED_KINDS:
            if self.rows is not None or not self.error:
                raise ValueError("failed result must carry an error and no rows")
        else:
            raise ValueError("unknown result kind: " + str(self.kind))

    @property
    def ok(self) -> bool:
        return self.kind == KIND_COMPONENTS

    @property
    def zero_components(self) -> bool:
        """True only when the probe ran and found an empty component set."""
        return self.kind == KIND_COMPONENTS and not self.rows

    def as_document(self) -> dict:
        """A JSON-serializable form: ``{kind, rows | error}``."""
        return {
            "kind": self.kind,
            "rows": (
                [{"id": r.id, "enabled": r.enabled, "x": r.x, "y": r.y} for r in self.rows]
                if self.rows is not None
                else None
            ),
            "error": self.error,
        }


def _check_entity_id(entity_id: int) -> int:
    """Mirror the runner's own rule: a real int in 1..4294967295, bool excluded.

    Refusing here means a bad id is a local ``ValueError``, never a dispatch under it
    (``elevated-request.py:238``, ``elevated-runner.ps1:326-327``).
    """
    if type(entity_id) is not int or not 1 <= entity_id <= 4294967295:
        raise ValueError("ENTITY_COMPONENT_ID_INVALID:" + repr(entity_id))
    return entity_id


def _unique(values: Iterable[int]) -> list[int]:
    """Deduplicate, preserving first-seen order.  One dispatch per entity, exactly."""
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _extract_json(text: str):
    """The first JSON value in ``text``, allowing leading log noise and trailing junk."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return value


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _fail(entity_id: int, kind: str, error: str) -> EntityResult:
    return EntityResult(entity_id=entity_id, kind=kind, rows=None, error=error)


def _parse_row(element) -> "ComponentRow | None":
    if not isinstance(element, dict):
        return None
    cid, enabled, x, y = element.get("id"), element.get("enabled"), element.get("x"), element.get("y")
    if type(cid) is not int or cid < 0:
        return None
    if type(enabled) is not bool:
        return None
    if not _is_number(x) or not _is_number(y):
        return None
    return ComponentRow(id=cid, enabled=enabled, x=float(x), y=float(y))


def _parse_components(entity_id: int, payload: dict) -> EntityResult:
    """Validate the body of an ``ok: true`` reply.  Any doubt is a refusal to read."""
    if type(payload.get("entityId")) is not int or payload["entityId"] != entity_id:
        # The adapter always echoes the id it read (EntityComponentProbe.cs:162).  A
        # missing or different id means this is not the answer to our question.
        return _fail(entity_id, KIND_MALFORMED, "MALFORMED_REPLY:entityId-mismatch")
    components = payload.get("components")
    if not isinstance(components, list):
        return _fail(entity_id, KIND_MALFORMED, "MALFORMED_REPLY:components-not-list")
    count = payload.get("componentCount")
    if type(count) is not int or count != len(components):
        # A count that disagrees with the list is a truncated/partial reply, not a
        # shorter entity; refuse rather than trust either number.
        return _fail(entity_id, KIND_MALFORMED, "MALFORMED_REPLY:componentCount-mismatch")
    rows: list[ComponentRow] = []
    for index, element in enumerate(components):
        row = _parse_row(element)
        if row is None:
            return _fail(entity_id, KIND_MALFORMED, f"MALFORMED_REPLY:component[{index}]")
        rows.append(row)
    return EntityResult(entity_id=entity_id, kind=KIND_COMPONENTS, rows=tuple(rows), error=None)


def interpret_reply(entity_id: int, returncode: int, output: str) -> EntityResult:
    """Turn one dispatch's ``(returncode, output)`` into an :class:`EntityResult`.

    Pure and total: every input produces exactly one result, and a failure never
    produces rows.
    """
    payload = _extract_json(output or "")

    if isinstance(payload, dict) and payload.get("pending") is True:
        return _fail(entity_id, KIND_TIMEOUT, "QUEUE_PENDING:" + str(payload.get("requestId") or ""))

    if isinstance(payload, dict):
        ok = payload.get("ok")
        if ok is False:
            code = payload.get("error")
            return _fail(entity_id, KIND_REFUSED, "REFUSED:" + (str(code) if code else "UNNAMED"))
        if ok is not True:
            return _fail(entity_id, KIND_MALFORMED, "MALFORMED_REPLY:ok-not-true")
        if returncode != 0:
            # exit non-zero means the caller was told this failed; a payload claiming
            # success cannot be trusted to carry rows.
            return _fail(entity_id, KIND_MALFORMED, "MALFORMED_REPLY:ok-true-but-nonzero-exit")
        return _parse_components(entity_id, payload)

    if returncode != 0:
        return _fail(entity_id, KIND_RUNNER_ERROR, "RUNNER_ERROR:" + (_first_line(output) or "no-output"))
    return _fail(entity_id, KIND_MALFORMED, "MALFORMED_REPLY:no-json")


def sweep(
    entity_ids: Sequence[int],
    *,
    runner: Runner,
    run_id: str,
    queue_dir: "Path | str | None" = None,
    python: str = DEFAULT_PYTHON,
    timeout: "float | None" = None,
) -> dict[int, EntityResult]:
    """Dispatch the component probe once per entity and return ``{entityId: result}``.

    The value is an :class:`EntityResult` — ``.rows`` (a tuple, maybe empty) on success
    or a named ``.error`` on failure.  Never a failure dressed up as an empty row set.

    ``runner`` is injected: production passes :func:`subprocess_runner`, tests pass a
    fake.  ``run_id`` names the bridge scope (the lease) the dispatches run under; it
    must be an open lease for the whole sweep, or a chunk must be split off with
    :func:`chunk_entities` and its own fresh lease.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("RUN_ID_REQUIRED")
    report: dict[int, EntityResult] = {}
    for entity_id in _unique(entity_ids):
        _check_entity_id(entity_id)
        argv = probe_argv(entity_id, run_id=run_id, queue_dir=queue_dir, python=python, timeout=timeout)
        returncode, output = runner(argv)
        report[entity_id] = interpret_reply(entity_id, int(returncode), output or "")
    return report


def summarize(report: dict[int, EntityResult]) -> dict:
    """Counts over a report.  ``failed`` and ``zeroComponents`` are disjoint by design."""
    counts = {kind: 0 for kind in _FAILED_KINDS}
    with_rows = 0
    zero = 0
    failed_ids: list[int] = []
    for result in report.values():
        if result.kind == KIND_COMPONENTS:
            if result.zero_components:
                zero += 1
            else:
                with_rows += 1
        else:
            counts[result.kind] += 1
            failed_ids.append(result.entity_id)
    return {
        "entities": len(report),
        "withComponents": with_rows,
        "zeroComponents": zero,
        "refused": counts[KIND_REFUSED],
        "malformed": counts[KIND_MALFORMED],
        "runnerError": counts[KIND_RUNNER_ERROR],
        "timeout": counts[KIND_TIMEOUT],
        "failed": len(failed_ids),
        "failedEntityIds": failed_ids,
    }


# --- planning / rendering (the human-run part) --------------------------------------

_SAFE_ARG = re.compile(r"^[A-Za-z0-9_@%+=:,./\\-]+$")


def _quote(arg: str) -> str:
    text = str(arg)
    if text and _SAFE_ARG.match(text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def probe_argv(
    entity_id: int,
    *,
    run_id: str,
    queue_dir: "Path | str | None" = None,
    python: str = DEFAULT_PYTHON,
    timeout: "float | None" = None,
) -> list[str]:
    """The exact argv for one entity's probe.

    ``--queue-dir`` is a top-level flag and precedes the ``call`` subcommand
    (``elevated-request.py:540-541``); putting it after ``call`` is a parse error.
    """
    _check_entity_id(entity_id)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("RUN_ID_REQUIRED")
    argv = [python, "-B", str(_ELEVATED_REQUEST)]
    if queue_dir is not None:
        argv += ["--queue-dir", str(queue_dir)]
    argv += ["call", "--op", COMPONENT_OP, "--entity-id", str(entity_id), "--run-id", run_id]
    if timeout is not None:
        argv += ["--timeout", str(timeout)]
    return argv


def plan_commands(
    entity_ids: Sequence[int],
    *,
    run_id: str,
    queue_dir: "Path | str | None" = None,
    python: str = DEFAULT_PYTHON,
    timeout: "float | None" = None,
) -> list[list[str]]:
    """One argv per entity (deduplicated, order preserved).  Does not dispatch."""
    return [
        probe_argv(entity_id, run_id=run_id, queue_dir=queue_dir, python=python, timeout=timeout)
        for entity_id in _unique(entity_ids)
    ]


def render_command(argv: Sequence[str]) -> str:
    """A copy-pasteable shell line for one argv."""
    return " ".join(_quote(arg) for arg in argv)


def render_commands(
    entity_ids: Sequence[int],
    *,
    run_id: str,
    queue_dir: "Path | str | None" = None,
    python: str = DEFAULT_PYTHON,
    timeout: "float | None" = None,
) -> list[str]:
    return [render_command(argv) for argv in plan_commands(
        entity_ids, run_id=run_id, queue_dir=queue_dir, python=python, timeout=timeout)]


def dispatches_per_lease(
    *,
    dispatch_seconds: float = DISPATCH_SECONDS,
    lease_seconds: float = LEASE_SECONDS,
    reserve_seconds: float = LEASE_RESERVE_SECONDS,
) -> int:
    """How many one-entity dispatches fit in one lease, with headroom.

    ``floor((lease - reserve) / dispatch)``, floored at 1.  With the measured defaults
    (300 s lease, ~16 s per dispatch, 60 s reserve) that is 15 -- a 15-entity chunk
    finishing well inside the 5-minute window rather than racing ``SCOPE_EXPIRED``.
    """
    if dispatch_seconds <= 0 or lease_seconds <= reserve_seconds:
        return 1
    return max(1, int(math.floor((lease_seconds - reserve_seconds) / dispatch_seconds)))


def chunk_entities(
    entity_ids: Sequence[int],
    *,
    max_per_chunk: "int | None" = None,
    dispatch_seconds: float = DISPATCH_SECONDS,
    lease_seconds: float = LEASE_SECONDS,
    reserve_seconds: float = LEASE_RESERVE_SECONDS,
) -> list[list[int]]:
    """Split entities into lease-sized chunks.  Each chunk needs its own fresh lease."""
    ids = _unique(entity_ids)
    size = max_per_chunk if max_per_chunk is not None else dispatches_per_lease(
        dispatch_seconds=dispatch_seconds, lease_seconds=lease_seconds, reserve_seconds=reserve_seconds)
    if size < 1:
        raise ValueError("CHUNK_SIZE_INVALID")
    return [ids[index:index + size] for index in range(0, len(ids), size)]


def render_chunked_plan(
    entity_ids: Sequence[int],
    *,
    run_ids: "Sequence[str] | None" = None,
    queue_dir: "Path | str | None" = None,
    python: str = DEFAULT_PYTHON,
    timeout: "float | None" = None,
    max_per_chunk: "int | None" = None,
) -> str:
    """The full human plan: chunks, the lease note, and each entity's exact command."""
    chunks = chunk_entities(entity_ids, max_per_chunk=max_per_chunk)
    per_lease = max_per_chunk if max_per_chunk is not None else dispatches_per_lease()
    total = sum(len(chunk) for chunk in chunks)
    lines = [
        f"# component sweep plan: {total} entities, {len(chunks)} chunk(s), "
        f"<= {per_lease} dispatch(es) per 5-minute lease (~{DISPATCH_SECONDS:.0f}s each)",
        "# Each chunk runs under ONE lease: load a fresh run-id before the chunk's first line.",
    ]
    if run_ids is not None and len(run_ids) != len(chunks):
        raise ValueError("RUN_IDS_LENGTH_MISMATCH")
    for index, chunk in enumerate(chunks):
        run_id = run_ids[index] if run_ids is not None else f"<mint-fresh-lease-{index + 1}>"
        lines.append(f"# --- chunk {index + 1}/{len(chunks)} ({len(chunk)} entities) ---")
        for entity_id in chunk:
            lines.append(render_command(
                probe_argv(entity_id, run_id=run_id, queue_dir=queue_dir,
                           python=python, timeout=timeout)))
    return "\n".join(lines)


def report_document(report: dict[int, EntityResult]) -> dict:
    """A JSON-serializable ``{entityId: {kind, rows | error}}`` plus counts."""
    return {
        "entities": {str(entity_id): result.as_document() for entity_id, result in report.items()},
        "summary": summarize(report),
    }


# --- production runner + CLI --------------------------------------------------------

def subprocess_runner() -> Runner:
    """Shell out to the real argv, concatenating stdout+stderr (see ``live.py``)."""
    def run(argv: list[str]) -> "tuple[int, str]":
        completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")

    return run


def main(argv: "Sequence[str] | None" = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="gameplan component-sweep",
        description="Per-entity component sweep over the read-only inspect-entity-components probe.")
    parser.add_argument("--entity-id", type=int, nargs="+", required=True,
                        help="nonzero uint32 entity ids to read (deduplicated, order kept)")
    parser.add_argument("--run-id", default=None, help="bridge scope id (an open lease)")
    parser.add_argument("--queue-dir", default=str(_DEFAULT_QUEUE))
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--max-per-chunk", type=int, default=None)
    parser.add_argument("--json", action="store_true", help="print the plan (or report) as JSON")
    parser.add_argument("--execute", action="store_true",
                        help="actually dispatch (needs --run-id); otherwise prints the plan")
    args = parser.parse_args(argv)

    if args.execute:
        if not args.run_id:
            raise SystemExit("RUN_ID_REQUIRED: --execute needs --run-id of an open lease")
        report = sweep(args.entity_id, runner=subprocess_runner(), run_id=args.run_id,
                       queue_dir=args.queue_dir, python=args.python, timeout=args.timeout)
        document = report_document(report)
        print(json.dumps(document, ensure_ascii=False, indent=2))
        return 0 if document["summary"]["failed"] == 0 else 1

    chunks = chunk_entities(args.entity_id, max_per_chunk=args.max_per_chunk)
    # One --run-id can only be honoured when the whole sweep fits in a single lease; a
    # multi-chunk plan mints a fresh lease per chunk, so a single id is a contradiction
    # rather than something to silently reuse past SCOPE_EXPIRED.
    run_ids = None
    if args.run_id:
        if len(chunks) != 1:
            raise SystemExit("RUN_ID_SPANS_MULTIPLE_LEASES: pass no --run-id and mint one per chunk")
        run_ids = [args.run_id]

    if args.json:
        document = {
            "perLease": args.max_per_chunk if args.max_per_chunk is not None else dispatches_per_lease(),
            "chunkCount": len(chunks),
            "chunks": chunks,
            "commands": render_commands(args.entity_id, run_id=args.run_id or "<mint-fresh-lease>",
                                        queue_dir=args.queue_dir, python=args.python, timeout=args.timeout),
        }
        print(json.dumps(document, ensure_ascii=False, indent=2))
        return 0

    print(render_chunked_plan(args.entity_id, run_ids=run_ids, queue_dir=args.queue_dir,
                              python=args.python, timeout=args.timeout, max_per_chunk=args.max_per_chunk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
