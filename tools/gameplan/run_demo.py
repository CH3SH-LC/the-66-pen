"""Turn ``docs/gameplan/REAL-MACHINE-RUNBOOK.md`` into one runnable sequence.

The runbook is a *list of commands a human pastes*, one at a time.  This module
makes it a single ordered sequence that a caller can read before running and
that an operator can run with one switch:

    create -> build-plan -> inspect -> bind -> save -> verify

Every command here is copied from the runbook, not invented:

* **create**  — ``author.py entity-create`` places the plot (``--template-id``,
  ``--position``); a native write, so it carries ``--review`` (runbook §6,
  ``author.py:451-471``).
* **build-plan** — the batched graph dispatch, runbook §5: one
  ``python -m tools.gameplan.cli farming --full --batch --execute`` builds the
  whole graph in one bridge lease (build_batch cannot spend a second lease —
  ``builder.py:368-375``).
* **inspect** — ``author.py graph inspect``, the *independent* read-back that is
  the project's evidence rule (runbook §7, ``author.py:478-484``).
* **bind** — ``author.py graph bind`` ties the graph to the entity (runbook §7,
  ``author.py:545-547``).
* **save** — ``author.py save``; the only op that writes disk, so it is a native
  write and carries its own ``--review`` (runbook §8, ``author.py:451-466``).
* **verify** — an *independent* ``.gil`` read-back that does not trust the save
  receipt (runbook §8.2): ``verify-created-save.py`` diffs two on-disk snapshots.

Two disciplines are enforced here, not merely documented:

1. **Dry run by default.**  Without ``--execute`` nothing is dispatched — the
   report lists every argv the sequence *would* run and the runner is never
   called.
2. **A review per native write, or a refusal before anything runs.**  The two
   native-write steps (``create``, ``save``) each need a review file that exists
   *now*.  If any is missing the whole sequence is refused up front, naming the
   step and the flag — the tool's own rule is one write = one fresh review
   (``docs/gameplan/REAL-MACHINE-RUNBOOK.md`` §6, ``author.py:459-464``), so
   reusing a review is a refusal, not a replay.

It **never auto-retries**: a step that comes back ``ok != true`` halts the
sequence and its raw receipt is printed.  The project forbids retries, and a
half-applied demo is a judgement call for the operator, not a loop.

Graph steps mutate editor memory but ``author.py`` exposes no ``--review`` for
them (only the scene backend takes one, ``author.py:459-464``); this orchestrator
therefore requires a review for exactly the steps whose command accepts one and
invents nothing extra.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .builder import request_id, subprocess_runner

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
_SCRATCH = _REPO_ROOT / ".runtime" / "scratch"
_VERIFY_OUT_DIR = _REPO_ROOT / ".runtime" / "game-executor"
_VERIFY_PY = _REPO_ROOT / "tools" / "game-executor" / "verify-created-save.py"

#: A runner takes a full argv and returns the parsed JSON object the command
#: printed (the same contract :class:`~tools.gameplan.builder.GraphBuilder` uses).
Runner = Callable[[list[str]], dict]

#: The canonical order, verbatim from the runbook.  It is the one thing the
#: sequence is *not* free to reorder: an entity must exist before it can be
#: bound, and a save must follow the bind it is meant to persist.
STEP_ORDER = ("create", "build-plan", "inspect", "bind", "save", "verify")

#: The steps whose command carries a ``--review``: the two native writes.  The
#: graph steps mutate editor memory but the bridge exposes no review parameter
#: for them, so this is exactly what the tools require — nothing invented.
REVIEW_STEPS = ("create", "save")


def _placeholder(step: str) -> str:
    return f"<{step.upper()}_REVIEW.json>"


@dataclass
class DemoConfig:
    """Everything the sequence needs; unknown values stay ``None`` and print as
    ``<...>`` placeholders during a dry run."""

    queue_dir: Path = _DEFAULT_QUEUE
    level_id: int | None = None
    template_id: int = 20001965           # 土田, the plot tile (placement.TILE_FIELD)
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    name: str = "MW_API_FARM_DEMO"
    run_id: str | None = None
    graph_id: int | None = None
    entity_id: int | None = None
    node_count: int = 15
    # build-plan (runbook §5) — the farming demo ids
    currency_id: int | None = None
    crop_id: int | None = None
    food_id: int | None = None
    python: str = "python"
    out: Path | None = None                # build-plan evidence JSON
    before_gil: Path | None = None         # verify: on-disk snapshot before save
    after_gil: Path | None = None          # verify: on-disk snapshot after save
    reviews: dict[str, str | None] = field(default_factory=dict)

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
        return self.name in REVIEW_STEPS

    def command(self) -> str:
        return " ".join(self.argv)


def _fv(value: float) -> str:
    return f"{float(value):g}"


def build_sequence(cfg: DemoConfig) -> list[SequenceStep]:
    """The six commands, in the runbook's order.  Pure: no dispatch, no I/O."""
    queue = str(cfg.queue_dir)
    graph_id = str(cfg.graph_id) if cfg.graph_id is not None else "<GRAPH_ID>"
    entity_id = str(cfg.entity_id) if cfg.entity_id is not None else "<ENTITY_ID>"
    run_id = cfg.run_id or "<RUN_ID>"
    ox, oy, oz = (float(cfg.origin[0]), float(cfg.origin[1]), float(cfg.origin[2]))

    steps: list[SequenceStep] = []

    # 1. create — place the plot entity (native write; needs the create review).
    steps.append(SequenceStep("create", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue,
        "entity-create",
        "--request-id", request_id("create", cfg.level_id, cfg.template_id, ox, oy, oz),
        "--level-id", str(cfg.level_id) if cfg.level_id is not None else "<LEVEL_ID>",
        "--review", cfg.review_path("create"),
        "--template-id", str(cfg.template_id),
        "--position", _fv(ox), _fv(oy), _fv(oz),
    ]))

    # 2. build-plan — the whole graph in ONE bridge dispatch (runbook §5).
    build = [
        cfg.python, "-m", "tools.gameplan.cli", "farming", "--full", "--batch", "--execute",
        "--name", cfg.name,
        "--run-id", run_id,
        "--queue-dir", queue,
        "--out", str(cfg.out) if cfg.out is not None else str(_SCRATCH / f"{cfg.name}-build.json"),
    ]
    for flag, value in (("--currency-id", cfg.currency_id), ("--crop-id", cfg.crop_id),
                        ("--food-id", cfg.food_id)):
        build += [flag, str(value) if value is not None else f"<{flag[2:].upper().replace('-', '_')}>"]
    steps.append(SequenceStep("build-plan", build))

    # 3. inspect — an independent, read-only read-back of the built graph.
    steps.append(SequenceStep("inspect", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "graph", "inspect",
        "--request-id", request_id("inspect", cfg.name, graph_id),
        "--run-id", run_id, "--name", cfg.name, "--graph-id", graph_id,
    ]))

    # 4. bind — attach the graph to the entity (needs both ids from above).
    steps.append(SequenceStep("bind", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "graph", "bind",
        "--request-id", request_id("bind", cfg.name, graph_id, entity_id),
        "--run-id", run_id, "--name", cfg.name, "--graph-id", graph_id,
        "--expected-node-count", str(cfg.node_count), "--entity-id", entity_id,
    ]))

    # 5. save — the only op that writes disk (native write; needs the save review).
    steps.append(SequenceStep("save", [
        cfg.python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", queue, "save",
        "--request-id", request_id("save", cfg.level_id),
        "--level-id", str(cfg.level_id) if cfg.level_id is not None else "<LEVEL_ID>",
        "--review", cfg.review_path("save"),
    ]))

    # 6. verify — an independent .gil diff that does not trust the save receipt.
    steps.append(SequenceStep("verify", [
        cfg.python, "-B", str(_VERIFY_PY),
        str(cfg.before_gil) if cfg.before_gil is not None else "<BEFORE.gil>",
        str(cfg.after_gil) if cfg.after_gil is not None else "<AFTER.gil>",
        "--entity-id", entity_id,
        "--template-id", str(cfg.template_id),
        "--name", cfg.name,
        "--position", _fv(ox), _fv(oy), _fv(oz),
        "--rotation", "0", "0", "0",
        "--scale", "1", "1", "1",
        "--out", str(_VERIFY_OUT_DIR / f"{cfg.name}-verify.json"),
    ]))

    names = tuple(s.name for s in steps)
    assert names == STEP_ORDER, names  # the order is a contract, not a suggestion
    return steps


def review_gate(steps: list[SequenceStep], reviews: dict[str, str | None]) -> list[str]:
    """The native-write steps whose review file does not exist right now.

    Read *before* anything runs, so a missing review is a refusal, never a
    half-built demo.  Each returned name is prefixed ``step=`` when a path was
    named but absent, or left bare when no path was given at all.
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
            {"step": s.name, "nativeWrite": s.native_write, "argv": s.argv, "command": s.command()}
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


def run(cfg: DemoConfig, *, execute: bool = False, runner: Runner | None = None) -> dict:
    """Build the sequence and either print it or run it.  The one entry point."""
    steps = build_sequence(cfg)
    if not execute:
        return dry_report(cfg, steps)
    missing = review_gate(steps, cfg.reviews)
    if missing:
        return refusal_report(missing)
    return execute_report(steps, runner or subprocess_runner(cfg.python))


def resolve_reviews(items: list[str] | None) -> dict[str, str | None]:
    """Parse ``--review`` occurrences into a per-step map.

    ``--review create=a.json --review save=b.json`` names each native write; a
    bare ``--review a.json`` is the default for every native-write step.
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
    parser = argparse.ArgumentParser(prog="gameplan run-demo", description=__doc__.splitlines()[0])
    parser.add_argument("--queue-dir", default=str(_DEFAULT_QUEUE))
    parser.add_argument("--level-id", type=int, default=None,
                        help="the CURRENT level id from a fresh live read — never a recorded one")
    parser.add_argument("--template-id", type=int, default=20001965, help="地块 tile (default 土田)")
    parser.add_argument("--origin", type=float, nargs=3, default=(0.0, 0.0, 0.0),
                        metavar=("X", "Y", "Z"), help="plot corner; must be verified empty")
    parser.add_argument("--name", default="MW_API_FARM_DEMO")
    parser.add_argument("--run-id", default=None, help="live bridge run id (32 hex)")
    parser.add_argument("--graph-id", type=int, default=None)
    parser.add_argument("--entity-id", type=int, default=None)
    parser.add_argument("--node-count", type=int, default=15)
    parser.add_argument("--currency-id", type=int, default=None)
    parser.add_argument("--crop-id", type=int, default=None)
    parser.add_argument("--food-id", type=int, default=None)
    parser.add_argument("--python", default="python")
    parser.add_argument("--out", default=None, help="build-plan evidence JSON path")
    parser.add_argument("--before-gil", default=None)
    parser.add_argument("--after-gil", default=None)
    parser.add_argument("--review", action="append", default=None, metavar="[STEP=]PATH",
                        help="review file for a native-write step (create, save); repeatable")
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
        node_count=args.node_count,
        currency_id=args.currency_id,
        crop_id=args.crop_id,
        food_id=args.food_id,
        python=args.python,
        out=Path(args.out) if args.out else None,
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
