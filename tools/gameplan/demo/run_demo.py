"""The #7 demo as ONE ordered sequence a fresh session can reproduce.

This is the *demo runner*: it turns the whole farm-demo pipeline into a single
ordered argument-vector list, dry-run by default, gated per native write.

It **extends** :mod:`tools.gameplan.run_demo` — that module proved the six-step
editor pipeline (``create -> build-plan -> inspect -> bind -> save -> verify``);
this one carries the fuller pipeline the #7 demo needs, adding the **tile grid**
(``create-batch``), the **graph export** and, last, the **read-only component
read** on the bound entity.  It reuses the same building blocks rather than
re-inventing them:

* ``request_id`` / ``subprocess_runner`` — :mod:`tools.gameplan.builder`
  (a request id is a pure function of the request; a runner is injected so the
  whole sequence is testable offline).
* ``grid`` / ``to_batch_plan`` / ``TILE_FIELD`` — :mod:`tools.gameplan.placement`
  (the ``create-batch`` plan object ``scene_cli`` reads, ``placement.py:148``).
* ``FarmFullConfig`` / ``build_plan`` / ``plan_shape`` — :mod:`.farming_full`
  (so ``bind``'s ``--expected-node-count`` is the real count of the plan the
  build step dispatches, not a guess).
* ``probe_argv`` / ``COMPONENT_OP`` — :mod:`tools.gameplan.component_sweep`
  (the *read-only* ``inspect-entity-components`` probe, ``component_sweep.py:342``).

The eight entries, in order
---------------------------
==================  ========  ====================================================
label               writes    command
==================  ========  ====================================================
``create-batch``    yes       ``scene_cli create-batch --plan`` — the plot grid
``build-plan``      no        ``cli farming --full --batch --execute`` — the graph
``inspect``         no        ``author.py graph inspect`` — read-back
``bind``            no        ``author.py graph bind`` — attach graph to entity
``export``          no        ``author.py graph export`` — dump the graph
``save``            yes       ``author.py save`` — the only disk write
``verify``          no        ``verify-created-save.py`` — on-disk ``.gil`` diff
``component-read``  no        ``elevated-request.py call --op inspect-entity-components``
==================  ========  ====================================================

Two disciplines are structural, not prose
-----------------------------------------
* **A gate on every native write.**  ``writes`` is ``True`` only for the two
  native **scene** writes (``create-batch``, ``save``) — exactly the actions
  ``author.py`` refuses without a ``--review`` (``author.py:139``,
  ``SCENE_WRITE_ACTIONS``).  The graph ops (``build-plan``/``inspect``/``bind``/
  ``export``) mutate editor memory but expose no review, so they are
  ``writes=False``; ``verify`` and ``component-read`` are read-only.
* **Dry run by default.**  :func:`build_sequence` is pure and offline: it mints
  no bridge request and contacts nothing.  The one offline artifact — the
  ``create-batch`` plan file — is written by :func:`write_batch_plan`, which
  :func:`run` calls **only** on the execute path.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..builder import request_id, subprocess_runner
from ..component_sweep import COMPONENT_OP, probe_argv as component_probe_argv
from ..placement import TILE_FIELD, grid, to_batch_plan
from .farming_full import FarmFullConfig, build_plan as build_full_plan, plan_shape

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"
_SCENE_CLI = _REPO_ROOT / "tools" / "game-executor" / "scene_cli.py"
_VERIFY_PY = _REPO_ROOT / "tools" / "game-executor" / "verify-created-save.py"
_ELEVATED_REQUEST = _REPO_ROOT / "tools" / "editor-bridge" / "elevated-request.py"
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
_SCRATCH = _REPO_ROOT / ".runtime" / "scratch"
_VERIFY_OUT_DIR = _REPO_ROOT / ".runtime" / "game-executor"

#: A runner takes a full argv and returns the parsed JSON object the command
#: printed (the same contract :func:`tools.gameplan.builder.subprocess_runner`
#: and :mod:`tools.gameplan.run_demo` use).
Runner = Callable[[list[str]], dict]

#: The canonical order.  It is the one thing the sequence is *not* free to
#: reorder: tiles must exist before the graph that binds to them is built, a
#: graph must be built before it is inspected/exported, a save must follow the
#: work it persists, and the component read must read the *saved, bound* entity
#: — so it is last.
STEP_ORDER = (
    "create-batch",
    "build-plan",
    "inspect",
    "bind",
    "export",
    "save",
    "verify",
    "component-read",
)

#: The steps whose command is a native **scene** mutation and therefore carries
#: a ``--review``: exactly the actions ``author.py`` gates
#: (``author.py:139``).  Nothing invented — the graph ops expose no review.
REVIEW_STEPS = ("create-batch", "save")

#: The steps that only read (no gate, no mutation).  ``component-read`` is here
#: and is last: it proves what the bound entity actually carries.
READ_ONLY_STEPS = ("inspect", "verify", "component-read")

_P_RUN_ID = "<RUN_ID>"
_P_GRAPH_ID = "<GRAPH_ID>"
_P_ENTITY_ID = "<ENTITY_ID>"
_P_LEVEL_ID = "<LEVEL_ID>"
_P_NODE_COUNT = "<NODE_COUNT>"
_P_BEFORE = "<BEFORE.gil>"
_P_AFTER = "<AFTER.gil>"
_P_CURRENCY = "<CURRENCY_ID>"
_P_CROP = "<CROP_ID>"
_P_FOOD = "<FOOD_ID>"

#: The plot grid the demo lays down.  Not parameters of :func:`build_sequence`
#: beyond ``rows``/``cols``/``spacing`` on the config, so they live in one place.
DEFAULT_ROWS = 3
DEFAULT_COLS = 3
DEFAULT_SPACING = 4.0


def _placeholder(step: str) -> str:
    return f"<{step.upper().replace('-', '_')}_REVIEW.json>"


@dataclass
class DemoConfig:
    """Everything the sequence needs; an unknown value stays ``None`` and prints
    as a ``<...>`` placeholder during a dry run."""

    queue_dir: Path = _DEFAULT_QUEUE
    level_id: int | None = None
    template_id: int = TILE_FIELD           # 土田, the plot tile
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    name: str = "MW_API_FARM_DEMO"
    run_id: str | None = None
    graph_id: int | None = None
    entity_id: int | None = None
    # build-plan — the farming demo ids
    currency_id: int | None = None
    crop_id: int | None = None
    food_id: int | None = None
    # the plot grid
    rows: int = DEFAULT_ROWS
    cols: int = DEFAULT_COLS
    spacing: float = DEFAULT_SPACING
    # bind's --expected-node-count; None means "derive it from the plan"
    node_count: int | None = None
    python: str = "python"
    out: Path | None = None                # build-plan evidence JSON
    batch_plan_path: Path | None = None    # create-batch plan (defaulted below)
    verify_out: Path | None = None         # verify evidence JSON (defaulted below)
    before_gil: Path | None = None         # verify: on-disk snapshot before save
    after_gil: Path | None = None          # verify: on-disk snapshot after save
    reviews: dict[str, str | None] = field(default_factory=dict)

    def plan_path(self) -> Path:
        return self.batch_plan_path or (_SCRATCH / f"{self.name}-plots.json")

    def verify_path(self) -> Path:
        return self.verify_out or (_VERIFY_OUT_DIR / f"{self.name}-verify.json")

    def review_path(self, step: str) -> str:
        path = self.reviews.get(step)
        return str(path) if path else _placeholder(step)


@dataclass
class SequenceStep:
    """One named step and the single command that performs it."""

    name: str
    argv: list[str]

    @property
    def native_write(self) -> bool:
        """True only for a native scene write, which needs a ``--review`` gate."""
        return self.name in REVIEW_STEPS

    @property
    def read_only(self) -> bool:
        return self.name in READ_ONLY_STEPS

    def command(self) -> str:
        return " ".join(self.argv)


def _fv(value: float) -> str:
    return f"{float(value):g}"


def _expected_node_count(cfg: DemoConfig) -> str:
    """The demo graph's node count, from the same plan the build step dispatches."""
    if cfg.node_count is not None:
        return str(cfg.node_count)
    if cfg.currency_id is None or cfg.crop_id is None or cfg.food_id is None:
        return _P_NODE_COUNT                      # dry-run placeholder
    plan = build_full_plan(
        FarmFullConfig(currency_id=cfg.currency_id, crop_id=cfg.crop_id, food_id=cfg.food_id),
        name=cfg.name,
    )
    return str(plan_shape(plan).node_count)


def _component_read_argv(cfg: DemoConfig, queue: str, entity_id: str, run_id: str) -> list[str]:
    """The read-only component probe, reusing the canonical builder when the ids
    are known so the argv is byte-identical to :mod:`tools.gameplan.component_sweep`."""
    if cfg.entity_id is not None and cfg.run_id:
        return component_probe_argv(
            cfg.entity_id, run_id=cfg.run_id, queue_dir=str(cfg.queue_dir), python=cfg.python)
    return [
        cfg.python, "-B", str(_ELEVATED_REQUEST),
        "--queue-dir", queue, "call", "--op", COMPONENT_OP,
        "--entity-id", entity_id, "--run-id", run_id,
    ]


def build_sequence(cfg: DemoConfig) -> list[SequenceStep]:
    """The eight commands, in order.  Pure: no dispatch, no I/O."""
    queue = str(cfg.queue_dir)
    level_id = str(cfg.level_id) if cfg.level_id is not None else _P_LEVEL_ID
    graph_id = str(cfg.graph_id) if cfg.graph_id is not None else _P_GRAPH_ID
    entity_id = str(cfg.entity_id) if cfg.entity_id is not None else _P_ENTITY_ID
    run_id = cfg.run_id or _P_RUN_ID
    currency = str(cfg.currency_id) if cfg.currency_id is not None else _P_CURRENCY
    crop = str(cfg.crop_id) if cfg.crop_id is not None else _P_CROP
    food = str(cfg.food_id) if cfg.food_id is not None else _P_FOOD
    before = str(cfg.before_gil) if cfg.before_gil is not None else _P_BEFORE
    after = str(cfg.after_gil) if cfg.after_gil is not None else _P_AFTER
    ox, oy, oz = (float(cfg.origin[0]), float(cfg.origin[1]), float(cfg.origin[2]))

    steps: list[SequenceStep] = []

    # 1. create-batch — the plot grid, from the batch plan ``scene_cli`` reads.
    #    A native scene write, so it carries the create review
    #    (``scene_cli.py:627`` --plan, :611 --review).
    steps.append(SequenceStep("create-batch", [
        cfg.python, "-B", str(_SCENE_CLI), "create-batch",
        "--elevated-queue", queue,
        "--plan", str(cfg.plan_path()),
        "--level-id", level_id,
        "--review", cfg.review_path("create-batch"),
    ]))

    # 2. build-plan — the whole graph in ONE bridge dispatch (builder.py:368-436).
    build = [
        cfg.python, "-m", "tools.gameplan.cli", "farming", "--full", "--batch", "--execute",
        "--name", cfg.name,
        "--run-id", run_id,
        "--queue-dir", queue,
        "--currency-id", currency,
        "--crop-id", crop,
        "--food-id", food,
        "--out", str(cfg.out) if cfg.out is not None else str(_SCRATCH / f"{cfg.name}-build.json"),
    ]
    steps.append(SequenceStep("build-plan", build))

    # 3. inspect — an independent, read-only read-back of the built graph.
    steps.append(SequenceStep("inspect", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "graph", "inspect",
        "--request-id", request_id("inspect", cfg.name, graph_id),
        "--run-id", run_id, "--name", cfg.name, "--graph-id", graph_id,
    ]))

    # 4. bind — attach the graph to the plot entity (needs both ids from above).
    steps.append(SequenceStep("bind", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "graph", "bind",
        "--request-id", request_id("bind", cfg.name, graph_id, entity_id),
        "--run-id", run_id, "--name", cfg.name, "--graph-id", graph_id,
        "--expected-node-count", _expected_node_count(cfg), "--entity-id", entity_id,
    ]))

    # 5. export — dump the graph.  Mutates editor memory, persists no disk file
    #    the save does not also cover, so it is not a review-gated scene write.
    steps.append(SequenceStep("export", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "graph", "export",
        "--request-id", request_id("export", cfg.name, graph_id),
        "--run-id", run_id, "--name", cfg.name, "--graph-id", graph_id,
    ]))

    # 6. save — the only op that writes disk (native write; needs the save review).
    steps.append(SequenceStep("save", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "save",
        "--request-id", request_id("save", level_id),
        "--level-id", level_id,
        "--review", cfg.review_path("save"),
    ]))

    # 7. verify — an independent .gil diff that does not trust the save receipt.
    steps.append(SequenceStep("verify", [
        cfg.python, "-B", str(_VERIFY_PY),
        before, after,
        "--entity-id", entity_id,
        "--template-id", str(cfg.template_id),
        "--name", cfg.name,
        "--position", _fv(ox), _fv(oy), _fv(oz),
        "--rotation", "0", "0", "0",
        "--scale", "1", "1", "1",
        "--out", str(cfg.verify_path()),
    ]))

    # 8. component-read — the read-only probe on the bound entity.  LAST, and
    #    the only step that reads what the save actually left on the entity.
    steps.append(SequenceStep(
        "component-read",
        _component_read_argv(cfg, queue, entity_id, run_id),
    ))

    names = tuple(s.name for s in steps)
    assert names == STEP_ORDER, names  # the order is a contract, not a suggestion
    return steps


def write_batch_plan(cfg: DemoConfig) -> Path:
    """Write the plot grid as the ``create-batch`` plan object.

    The one file this runner writes, and it writes it **only** on the execute
    path (never in a dry run).  The shape comes from ``placement.to_batch_plan``,
    asserted against ``scene_cli.normalize_placements`` in
    ``tests/test_placement_batch.py``.
    """
    placements = grid(
        template_id=cfg.template_id,
        origin=(float(cfg.origin[0]), float(cfg.origin[1]), float(cfg.origin[2])),
        rows=cfg.rows, cols=cfg.cols, spacing=cfg.spacing,
        label_prefix=cfg.name,
    )
    path = cfg.plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_batch_plan(placements), ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def review_gate(steps: list[SequenceStep], reviews: dict[str, str | None]) -> list[str]:
    """The native-write steps whose review file does not exist right now.

    Read *before* anything runs, so a missing review is a refusal, never a
    half-built demo.
    """
    missing: list[str] = []
    for step in steps:
        if not step.native_write:
            continue
        path = reviews.get(step.name)
        if not path or not Path(path).is_file():
            missing.append(step.name)
    return missing


def dry_report(cfg: DemoConfig, steps: list[SequenceStep]) -> dict:
    """What the sequence WOULD do.  The runner is never touched in this mode."""
    return {
        "mode": "dry-run",
        "executed": 0,
        "note": "nothing dispatched; re-run with --execute and a live --run-id, "
                "plus a review file per native-write step",
        "order": list(STEP_ORDER),
        "steps": [
            {"step": s.name, "nativeWrite": s.native_write, "readOnly": s.read_only,
             "argv": s.argv, "command": s.command()}
            for s in steps
        ],
    }


def refusal_report(missing: list[str]) -> dict:
    """A fresh review is required for every native write; say which ones are missing."""
    detail = ", ".join(repr(name) for name in missing)
    flags = "; ".join(f"--review {name}=PATH" for name in missing)
    return {
        "mode": "refused",
        "ok": False,
        "executed": 0,
        "reason": "review-required",
        "missing": list(missing),
        "message": (
            f"refusing to run: no review file present for native-write step(s) {detail}. "
            f"Pass {flags}. A review is a per-request evidence record — one write = one fresh "
            "review; reusing one is refused by the tool, not replayed."
        ),
    }


def execute_report(steps: list[SequenceStep], runner: Runner) -> dict:
    """Run the steps in order, stop at the first failure, print its raw receipt.

    No retries, ever: a step that is not ``ok`` halts the sequence and the exact
    receipt is returned so an operator decides what to do next.
    """
    records: list[dict] = []
    for step in steps:
        try:
            receipt = runner(step.argv)
        except Exception as error:  # noqa: BLE001 - surfaced, never swallowed
            receipt = {"ok": False, "error": f"{type(error).__name__}: {error}"}
        if not isinstance(receipt, dict):
            receipt = {"ok": False, "error": f"runner returned {type(receipt).__name__}"}
        ok = receipt.get("ok") is True
        records.append({"step": step.name, "argv": step.argv, "ok": ok, "receipt": receipt})
        if not ok:
            return {
                "mode": "execute",
                "ok": False,
                "executed": len(records),
                "haltedAt": step.name,
                "retryAttempted": False,
                "steps": records,
                "receipt": receipt,
            }
    return {
        "mode": "execute",
        "ok": True,
        "executed": len(records),
        "haltedAt": None,
        "retryAttempted": False,
        "steps": records,
    }


def run(cfg: DemoConfig, *, execute: bool = False, runner: Runner | None = None,
        plan_writer: Callable[[DemoConfig], Path] | None = None) -> dict:
    """Build the sequence and either print it or run it.  The one entry point.

    On the execute path the review gate runs **first** (a refusal touches
    nothing), then the ``create-batch`` plan artifact is written, then the steps
    dispatch.  A dry run writes nothing and dispatches nothing.
    """
    steps = build_sequence(cfg)
    if not execute:
        return dry_report(cfg, steps)
    missing = review_gate(steps, cfg.reviews)
    if missing:
        return refusal_report(missing)
    (plan_writer or write_batch_plan)(cfg)     # the offline artifact step 1 reads
    return execute_report(steps, runner or subprocess_runner(cfg.python))


def resolve_reviews(items: list[str] | None) -> dict[str, str | None]:
    """Parse ``--review`` occurrences into a per-step map.

    ``--review create-batch=a.json --review save=b.json`` names each native
    write; a bare ``--review a.json`` is the default for every native-write step.
    """
    default: str | None = None
    per_step: dict[str, str] = {}
    for item in items or []:
        step, sep, path = item.partition("=")
        if sep:
            per_step[step.strip()] = path.strip()
        else:
            default = item.strip()
    return {step: per_step.get(step, default) for step in REVIEW_STEPS}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gameplan demo-run",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--queue-dir", default=str(_DEFAULT_QUEUE))
    parser.add_argument("--level-id", type=int, default=None,
                        help="the CURRENT level id from a fresh live read — never a recorded one")
    parser.add_argument("--template-id", type=int, default=TILE_FIELD, help="地块 tile (default 土田)")
    parser.add_argument("--origin", type=float, nargs=3, default=(0.0, 0.0, 0.0),
                        metavar=("X", "Y", "Z"), help="plot grid corner; must be verified empty")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS, help="plot grid rows")
    parser.add_argument("--cols", type=int, default=DEFAULT_COLS, help="plot grid cols")
    parser.add_argument("--spacing", type=float, default=DEFAULT_SPACING, help="plot spacing")
    parser.add_argument("--name", default="MW_API_FARM_DEMO")
    parser.add_argument("--run-id", default=None, help="live bridge run id (32 hex)")
    parser.add_argument("--graph-id", type=int, default=None)
    parser.add_argument("--entity-id", type=int, default=None)
    parser.add_argument("--node-count", type=int, default=None,
                        help="bind's --expected-node-count (default: derive from the plan)")
    parser.add_argument("--currency-id", type=int, default=None)
    parser.add_argument("--crop-id", type=int, default=None)
    parser.add_argument("--food-id", type=int, default=None)
    parser.add_argument("--python", default="python")
    parser.add_argument("--out", default=None, help="build-plan evidence JSON path")
    parser.add_argument("--batch-plan", default=None, help="create-batch plan path")
    parser.add_argument("--verify-out", default=None)
    parser.add_argument("--before-gil", default=None)
    parser.add_argument("--after-gil", default=None)
    parser.add_argument("--review", action="append", default=None, metavar="[STEP=]PATH",
                        help="review file for a native-write step (create-batch, save); repeatable")
    parser.add_argument("--execute", action="store_true",
                        help="actually run the sequence (default: dry run, nothing is dispatched)")
    return parser


def config_from_args(args) -> DemoConfig:
    return DemoConfig(
        queue_dir=Path(args.queue_dir),
        level_id=args.level_id,
        template_id=args.template_id,
        origin=tuple(args.origin),
        name=args.name,
        run_id=args.run_id,
        graph_id=args.graph_id,
        entity_id=args.entity_id,
        currency_id=args.currency_id,
        crop_id=args.crop_id,
        food_id=args.food_id,
        rows=args.rows,
        cols=args.cols,
        spacing=args.spacing,
        node_count=args.node_count,
        python=args.python,
        out=Path(args.out) if args.out else None,
        batch_plan_path=Path(args.batch_plan) if args.batch_plan else None,
        verify_out=Path(args.verify_out) if args.verify_out else None,
        before_gil=Path(args.before_gil) if args.before_gil else None,
        after_gil=Path(args.after_gil) if args.after_gil else None,
        reviews=resolve_reviews(args.review),
    )


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    report = run(config_from_args(args), execute=args.execute)
    if report.get("mode") == "dry-run":
        for entry in report["steps"]:
            print(f"# {entry['step']}: {entry['command']}")
        print()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("mode") == "refused":
        return 2
    if report.get("mode") == "execute" and not report.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
