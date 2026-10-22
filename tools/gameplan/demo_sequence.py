"""One offline-planned, end-to-end sequence for the whole farm demo (#6 造).

``docs/gameplan/REAL-MACHINE-RUNBOOK.md`` is a list of commands a human pastes
one at a time, and it only begins *after* three preconditions (helper alive, a
bridge run id, the current level id) are already met.  This module turns the
whole demo into a single ordered :func:`build_sequence` a reader can inspect
before touching anything, plus a :func:`render` that prints the exact
copy-pasteable command lines — so someone who was not in this session can
reproduce it.

The nine entries, in order
--------------------------
1. ``live-read``     — read the CURRENTLY-OPEN sandbox (native, read-only).
2. ``templates``     — **a MANUAL gate, not a command**: the currency (type 10),
   item (type 8) and shop (type 15) templates have no writer in this project, so
   a human must build them in the editor UI first.  It appears in the sequence
   with an empty ``argv`` so the ordering is complete, but :func:`render` prints
   it as a ``#`` gate, never as a command.
3. ``create-plots``  — the plot entities, placed by coordinate from a **batch
   plan** (``placement.grid`` -> ``placement.to_batch_plan`` -> ``scene_cli
   create-batch``).  A native scene write, so its ``--review`` is its gate.
4. ``build-plan``    — the whole graph in ONE bridge dispatch (``cli farming
   --full --batch --execute``; the ``build-plan`` op).
5. ``inspect``       — an independent, read-only read-back of the built graph.
6. ``bind``          — attach the graph to the plot entity.
7. ``export``        — export the graph (a ``.gia``); mutates editor memory but
   carries no review and persists nothing.
8. ``save``          — native ``save``, the ONLY op that writes disk; a native
   scene write, so its ``--review`` is its gate.
9. ``verify``        — an independent on-disk ``.gil`` diff that does not trust
   the save receipt.

Two disciplines are structural, not prose
-----------------------------------------
* **A gate on every write.**  ``writes`` is ``True`` only for the two native
  scene writes (``create-plots``, ``save``) and each such step carries a
  non-empty ``gate`` naming the review file it needs.  ``writes`` here is
  shorthand for *"dispatches a native scene mutation, which needs a review
  gate"* — the graph ops (build-plan / inspect / bind / export) mutate editor
  memory but expose no review, so they are ``writes=False``.
* **Dry run by default.**  :func:`build_sequence` is offline: it mints no bridge
  request and contacts nothing.  Its *only* side effect is writing the batch
  plan file (``.runtime/scratch/<name>-plots.json``) that the ``create-plots``
  command reads — a deterministic, offline artifact.  :func:`render` is pure
  and executes nothing.

Everything here is copied from the runbook, not invented: the plot tile
(``placement.TILE_FIELD``), the batched build (runbook §5), inspect/bind
(runbook §7), save (runbook §8.1) and the independent ``.gil`` diff (runbook
§8.2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TypedDict

from .builder import request_id
from .demo.farming_full import FarmFullConfig, build_plan as build_full_plan, plan_shape
from .placement import TILE_FIELD, grid, to_batch_plan

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"
_SCENE_CLI = _REPO_ROOT / "tools" / "game-executor" / "scene_cli.py"
_VERIFY_PY = _REPO_ROOT / "tools" / "game-executor" / "verify-created-save.py"
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
_SCRATCH = _REPO_ROOT / ".runtime" / "scratch"
_VERIFY_OUT_DIR = _REPO_ROOT / ".runtime" / "game-executor"

#: The plot grid the demo lays down.  The acceptance target in
#: ``docs/MODULE-PLAN-6.md:150`` is a 3x3 grid; spacing matches the worked
#: example in ``tools/gameplan/tests/test_placement.py``.  They are NOT
#: parameters of :func:`build_sequence` (its signature is fixed), so they are
#: named constants a reader can see and change in one place.
PLOT_ROWS = 3
PLOT_COLS = 3
PLOT_SPACING = 4.0

#: ``build_sequence`` mints no entity/graph ids (both are functions of the
#: save), so the steps that need one print a placeholder an operator replaces
#: with the value from the previous step's receipt.
_RUN_ID = "<RUN_ID>"
_GRAPH_ID = "<GRAPH_ID>"
_ENTITY_ID = "<ENTITY_ID>"
_BEFORE_GIL = "<BEFORE.gil>"
_AFTER_GIL = "<AFTER.gil>"

#: The manual template gate.  DEMO-GAP §三 lists the three asset types with no
#: writer in the bridge/CLI/MCP, so this is a precondition a human performs.
TEMPLATE_GATE = (
    "MANUAL: build the currency (type 10), item (type 8: crop + food) and shop "
    "(type 15) templates in the editor UI — no template writer exists in the "
    "bridge/CLI/MCP, so the config ids in the graph would be dangling without them"
)

#: The order is a contract, not a suggestion: an entity must exist before it can
#: be bound, a graph must be built before it can be inspected/exported, and a
#: save must follow the work it is meant to persist.
STEP_LABELS = (
    "live-read",
    "templates",
    "create-plots",
    "build-plan",
    "inspect",
    "bind",
    "export",
    "save",
    "verify",
)

#: The two steps whose command is a native scene write and therefore needs a
#: review gate.  Exactly what the tools require — nothing invented.
GATED_WRITE_LABELS = ("create-plots", "save")


class Step(TypedDict):
    """One entry in the demo sequence.

    ``argv`` is the exact argument vector of the command to run; it is empty for
    a gate that is not a command (the manual template step).  ``writes`` is
    ``True`` for a native scene write, and every such step has a non-empty
    ``gate`` naming the review file it needs.  ``gate`` is also set (with a
    ``MANUAL:`` prefix) on the manual template step.
    """

    order: int
    label: str
    argv: list[str]
    writes: bool
    gate: str | None


def _posix(path: Path) -> str:
    return path.as_posix()


def _fv(value: float) -> str:
    return f"{float(value):g}"


def _validate(level_id, template_id, origin, crop_id, food_id, currency_id, graph_name) -> None:
    """Fail loudly on a value that is present but wrong.

    A *missing* required argument is a ``TypeError`` from the signature; this
    covers the case where one was supplied as ``None`` or a nonsense shape, so
    the sequence is never built from a half-value.
    """
    for name, value in (("level_id", level_id), ("template_id", template_id),
                        ("crop_id", crop_id), ("food_id", food_id),
                        ("currency_id", currency_id)):
        if value is None:
            raise ValueError(f"{name} is required")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} must be a positive int, got {value!r}")
    if not isinstance(graph_name, str) or not graph_name.strip():
        raise ValueError("graph_name must be a non-empty string")
    try:
        components = list(origin)
    except TypeError as error:
        raise ValueError(f"origin must be a 3-sequence of numbers: {error}") from error
    if len(components) != 3:
        raise ValueError(f"origin must have exactly 3 components, got {len(components)}")
    for c in components:
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            raise ValueError(f"origin components must be numbers, got {c!r}")


def _write_batch_plan(plan_path: Path, *, template_id: int, origin) -> None:
    """Write the plot grid as the ``create-batch`` plan object.

    The only file this module ever writes.  It uses the same shape authority the
    command reads: ``placement.to_batch_plan`` is asserted against
    ``scene_cli.normalize_placements`` in ``tests/test_placement_batch.py``.
    """
    placements = grid(
        template_id=template_id,
        origin=(float(origin[0]), float(origin[1]), float(origin[2])),
        rows=PLOT_ROWS,
        cols=PLOT_COLS,
        spacing=PLOT_SPACING,
        label_prefix=f"{plan_path.stem}",
    )
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(to_batch_plan(placements), ensure_ascii=False, indent=1),
                         encoding="utf-8")


def _expected_node_count(currency_id: int, crop_id: int, food_id: int) -> int:
    """The demo graph's node count, from the same plan the build step dispatches."""
    plan = build_full_plan(
        FarmFullConfig(currency_id=currency_id, crop_id=crop_id, food_id=food_id),
        name="MW_API_FARM_DEMO",
    )
    return plan_shape(plan).node_count


def build_sequence(*, level_id: int, template_id: int, origin, crop_id: int,
                   food_id: int, currency_id: int, graph_name: str) -> list[Step]:
    """The nine-entry demo sequence, in the runbook's order.

    Pure except for one offline artifact: the ``create-batch`` plan file named in
    the ``create-plots`` step's ``--plan`` is (re)written under
    ``.runtime/scratch/``.  No bridge, game, editor or save is contacted.
    """
    _validate(level_id, template_id, origin, crop_id, food_id, currency_id, graph_name)

    queue = _posix(_DEFAULT_QUEUE)
    plan_path = _SCRATCH / f"{graph_name}-plots.json"
    build_out = _SCRATCH / f"{graph_name}-build.json"
    verify_out = _VERIFY_OUT_DIR / f"{graph_name}-verify.json"
    gate_create = _posix(_SCRATCH / f"{graph_name}-create-review.json")
    gate_save = _posix(_SCRATCH / f"{graph_name}-save-review.json")
    ox, oy, oz = (float(origin[0]), float(origin[1]), float(origin[2]))
    node_count = _expected_node_count(currency_id, crop_id, food_id)

    _write_batch_plan(plan_path, template_id=template_id, origin=(ox, oy, oz))

    def step(label: str, argv: list[str], writes: bool, gate: str | None) -> Step:
        return {"order": 0, "label": label, "argv": argv, "writes": writes, "gate": gate}

    steps: list[Step] = [
        # 1. live-read — the CURRENTLY-OPEN sandbox, native read-only (runbook §3).
        step("live-read",
             ["python", "-m", "tools.gameplan.live", "--queue-dir", queue],
             False, None),

        # 2. templates — a MANUAL gate, not a command (empty argv).
        step("templates", [], False, TEMPLATE_GATE),

        # 3. create-plots — the plot grid, by coordinate, from the batch plan
        #    (runbook §6; scene_cli.py create-batch reads --plan).  Native write.
        step("create-plots",
             ["python", "-B", _posix(_SCENE_CLI), "create-batch",
              "--elevated-queue", queue,
              "--plan", _posix(plan_path),
              "--level-id", str(level_id),
              "--review", gate_create],
             True, gate_create),

        # 4. build-plan — the whole graph in ONE bridge dispatch (runbook §5).
        step("build-plan",
             ["python", "-m", "tools.gameplan.cli", "farming", "--full", "--batch", "--execute",
              "--name", graph_name,
              "--run-id", _RUN_ID,
              "--queue-dir", queue,
              "--currency-id", str(currency_id),
              "--crop-id", str(crop_id),
              "--food-id", str(food_id),
              "--out", _posix(build_out)],
             False, None),

        # 5. inspect — independent, read-only read-back (runbook §7).
        step("inspect",
             ["python", "-B", _posix(_AUTHOR_PY), "--elevated-queue", queue,
              "graph", "inspect",
              "--request-id", request_id("inspect", graph_name, _GRAPH_ID),
              "--run-id", _RUN_ID,
              "--name", graph_name,
              "--graph-id", _GRAPH_ID],
             False, None),

        # 6. bind — attach the graph to the plot entity (runbook §7).
        step("bind",
             ["python", "-B", _posix(_AUTHOR_PY), "--elevated-queue", queue,
              "graph", "bind",
              "--request-id", request_id("bind", graph_name, _GRAPH_ID, _ENTITY_ID),
              "--run-id", _RUN_ID,
              "--name", graph_name,
              "--graph-id", _GRAPH_ID,
              "--expected-node-count", str(node_count),
              "--entity-id", _ENTITY_ID],
             False, None),

        # 7. export — export the graph (runbook §5's fifth graph op).
        step("export",
             ["python", "-B", _posix(_AUTHOR_PY), "--elevated-queue", queue,
              "graph", "export",
              "--request-id", request_id("export", graph_name, _GRAPH_ID),
              "--run-id", _RUN_ID,
              "--name", graph_name,
              "--graph-id", _GRAPH_ID],
             False, None),

        # 8. save — the only op that writes disk (runbook §8.1).  Native write.
        step("save",
             ["python", "-B", _posix(_AUTHOR_PY), "--elevated-queue", queue,
              "save",
              "--request-id", request_id("save", level_id),
              "--level-id", str(level_id),
              "--review", gate_save],
             True, gate_save),

        # 9. verify — an independent on-disk .gil diff (runbook §8.2).
        step("verify",
             ["python", "-B", _posix(_VERIFY_PY), _BEFORE_GIL, _AFTER_GIL,
              "--entity-id", _ENTITY_ID,
              "--template-id", str(template_id),
              "--name", graph_name,
              "--position", _fv(ox), _fv(oy), _fv(oz),
              "--rotation", "0", "0", "0",
              "--scale", "1", "1", "1",
              "--out", _posix(verify_out)],
             False, None),
    ]

    for index, entry in enumerate(steps, start=1):
        entry["order"] = index
    labels = tuple(s["label"] for s in steps)
    assert labels == STEP_LABELS, labels  # the order is a contract, not a suggestion
    return steps


def _shell(argv: list[str]) -> str:
    """One copy-pasteable command line; quote any argument containing a space."""
    out: list[str] = []
    for arg in argv:
        if arg == "" or any(c.isspace() for c in arg):
            out.append('"' + arg.replace('"', '\\"') + '"')
        else:
            out.append(arg)
    return " ".join(out)


def render(sequence: list[Step]) -> str:
    """The exact copy-pasteable command lines for a sequence, plus gate headers.

    Pure: it formats the argv it is given and executes nothing.  Every real
    command is a plain line an operator can paste; a gate that is not a command
    (the manual template step) is printed only as a ``#`` comment, and every
    write carries a ``# gate:`` line naming the review it needs.
    """
    lines: list[str] = []
    for entry in sequence:
        tags = [t for t in (("WRITE" if entry["writes"] else None),
                            ("GATE" if entry["gate"] else None)) if t]
        header = f"# {entry['order']}. {entry['label']}"
        if tags:
            header += " [" + ", ".join(tags) + "]"
        lines.append(header)
        if entry["gate"]:
            lines.append(f"#    gate: {entry['gate']}")
        if entry["argv"]:
            lines.append(_shell(entry["argv"]))
        else:
            lines.append("#    (no command — manual gate; complete it before running on)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def writes_without_gate(sequence: list[Step]) -> list[str]:
    """The labels of any step that writes but names no gate (must stay empty)."""
    return [s["label"] for s in sequence if s["writes"] and not s["gate"]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gameplan demo-sequence",
        description="Print the whole farm-demo sequence as copy-pasteable commands (offline).")
    parser.add_argument("--level-id", type=int, required=True,
                        help="the CURRENT level id from a fresh live read — never a recorded one")
    parser.add_argument("--template-id", type=int, default=TILE_FIELD, help="plot tile (default 土田)")
    parser.add_argument("--origin", type=float, nargs=3, default=(0.0, 0.0, 0.0),
                        metavar=("X", "Y", "Z"), help="plot grid corner; must be verified empty")
    parser.add_argument("--crop-id", type=int, required=True)
    parser.add_argument("--food-id", type=int, required=True)
    parser.add_argument("--currency-id", type=int, required=True)
    parser.add_argument("--graph-name", default="MW_API_FARM_DEMO")
    parser.add_argument("--json", action="store_true", help="print the sequence as JSON, not commands")
    return parser


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    sequence = build_sequence(
        level_id=args.level_id, template_id=args.template_id, origin=tuple(args.origin),
        crop_id=args.crop_id, food_id=args.food_id, currency_id=args.currency_id,
        graph_name=args.graph_name)
    if args.json:
        print(json.dumps(sequence, ensure_ascii=False, indent=2))
    else:
        print(render(sequence), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
