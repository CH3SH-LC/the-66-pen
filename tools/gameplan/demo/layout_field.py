"""M6b 摆放 — a 3x3 farm field as a scene_cli ``create-batch`` write (offline).

This module turns the abstract grid planner in :mod:`tools.gameplan.placement`
into the three artefacts a real "lay nine plots down in a level" run needs, and
nothing more:

1. **the batch plan dict** — the exact object ``scene_cli create-batch`` reads
   from its ``--plan`` file.  The shape is not invented here: it is the one
   ``tools/game-executor/scene_cli.py:204`` (:func:`read_plan_spec`) hands to
   ``scene_cli.py:195`` (:func:`normalize_placements`), whose per-entry rules
   live in ``scene_cli.py:170`` (:func:`normalize_placement`) — keys
   ``template_id``/``position``/``rotation``/``scale``/``label``, of which
   ``template_id``/``position``/``scale`` are required and a ``label`` is inert
   (dropped from the queued request, scene_cli.py:174).  We rebuild that shape
   here, in this file, rather than importing another agent's ``to_batch_plan``,
   so the two cannot silently drift apart::

       {"placements": [{"template_id": 20001965,
                        "position": [x, y, z],
                        "rotation": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0]}, ...]}

   A concrete, reviewable instance of this dict is checked in at
   ``tools/gameplan/demo/field-grid-3x3.json`` (see :data:`FIELD_PLAN_PATH`).

2. **the review-minting command line** — :func:`orchestrator_command_line`
   emits the ``orchestrate_write_review.py`` invocation that DERIVES the
   native-write-review record for this very batch.  A native mutation cannot be
   queued on a record a model wrote itself: the coordinator
   (``tools/game-executor/orchestrate_write_review.py``) re-validates a review
   against the request hash, a complete executed baseline run, the live session
   identity and a recovery copy of the formal save, and only then publishes it.
   This is step ONE of the two commands a run actually needs.

3. **the queue command line** — :func:`command_line` emits the
   ``scene_cli create-batch`` invocation that consumes the review step 2 minted
   and pushes the batch onto the elevated queue.  This is step TWO.

The order is load-bearing: step 2 *produces* ``<review.json>`` and step 3
*consumes* it, so the two commands share one value.  Both are returned as plain
STRINGS, meant to be read, filled in and run — nothing here is dispatched, no
process is started, no save is read or written, and no bridge request is formed.
The plan is inert until a caller pastes the commands and runs them.

Origin is NOT free — read this before you pick one
--------------------------------------------------
:func:`field_plan` puts the first tile at the caller's ``origin`` and the other
eight on a square lattice from it, so ``origin`` decides where a nine-tile field
lands *in the current level*.  Two traps, both already paid for in this project:

* The spawn preset point **``(-547.5, -2.5, -547.5)``** is a **global constant**
  — it is the player template's preset spawn and is identical across every save
  we have decoded.  It is **not** a level origin, and using it as ``origin``
  anchors the field to a point that has nothing to do with where the player is
  or where open ground is.  Do not copy it as an origin.
* **1 grid = 1 metre.**  The game's ground plane is XZ; ``spacing`` is in metres
  and the default ``1.0`` tiles a row of plots edge to edge.  A spacing that
  "looks about right" in editor units is a guess — pick the metre value you mean.

Therefore the caller MUST supply an ``origin`` that has been verified **empty**
in the *current* level (a level id is a function of the save, so it is never
pinned from a previous run — see ``gameplan live`` for the fresh回执).  This
module cannot verify emptiness for you; it only declines to pretend it does.
:data:`FIELD_ORIGIN`, the origin baked into the checked-in plan file, is an
arbitrary documented example that carries the *same* obligation: re-verify it
empty before use, or regenerate the file at an origin you have verified.

Run it to print all three artefacts (still offline — nothing is sent)::

    PYTHONIOENCODING=utf-8 python -m tools.gameplan.demo.layout_field \
        --origin 0.0 0.0 0.0 --spacing 1.0
"""

from __future__ import annotations

from ..placement import TILE_FIELD, Placement, grid

#: The 3x3 field named in the M6b acceptance test (docs/MODULE-PLAN-6.md:151).
FIELD_ROWS = 3
FIELD_COLS = 3

#: Metres between neighbouring tiles.  **1 grid = 1 metre**; 1.0 tiles a row of
#: plots edge to edge.
DEFAULT_SPACING = 1.0

#: The origin and spacing baked into the checked-in example plan
#: (:data:`FIELD_PLAN_PATH`).  Arbitrary and deliberate: they are NOT the spawn
#: preset point, and they carry the emptiness obligation of the module docstring
#: — re-verify this origin empty in the current level, or regenerate the file.
FIELD_ORIGIN = (0.0, 0.0, 0.0)
FIELD_SPACING = DEFAULT_SPACING

#: In-repo, reviewable instance of :func:`field_plan`'s output.
FIELD_PLAN_PATH = "tools/gameplan/demo/field-grid-3x3.json"

#: The three values an offline planner cannot know, kept as ``<...>`` tokens so
#: nobody mistakes a placeholder for a real value.  Fill them from a *fresh*
#: live discovery — never copy the previous run's level id.
LEVEL_ID_PLACEHOLDER = "<LEVEL_ID>"
REVIEW_PLACEHOLDER = "<REVIEW.json>"
PLAN_PLACEHOLDER = "<plan.json>"
SESSION_PLACEHOLDER = "<SESSION.json>"
BASELINE_RUN_PLACEHOLDER = "<baseline-run-dir>"

#: Repo-relative paths the emitted commands name.  They are strings, not
#: resolved paths: the commands are meant to be read and run from the repo root.
SCENE_CLI = "tools/game-executor/scene_cli.py"
ORCHESTRATOR = "tools/game-executor/orchestrate_write_review.py"
DEFAULT_QUEUE_DIR = ".runtime/editor-bridge/elevated-queue"

#: Where the orchestrator may write the recovery copy of the formal save.  The
#: orchestrator refuses any directory outside ``.runtime``
#: (orchestrate_write_review.py:108 ``project_runtime_dir``), so the default is
#: the project's own recovery root, not a caller's arbitrary path.
DEFAULT_RECOVERY_DIR = ".runtime/game-executor/native-write-reviews/recovery"


def field_placements(
    *,
    origin: tuple[float, float, float],
    spacing: float = DEFAULT_SPACING,
    template_id: int = TILE_FIELD,
    rows: int = FIELD_ROWS,
    cols: int = FIELD_COLS,
) -> list[Placement]:
    """The nine 土田 plots as :class:`~tools.gameplan.placement.Placement` objects.

    ``origin`` is the far corner (row 0, col 0) and MUST be verified empty in the
    current level — see the module docstring.  Delegates the lattice arithmetic
    to :func:`~tools.gameplan.placement.grid` (row-major, XZ plane, all tiles at
    the origin's Y) so the geometry has exactly one authority in this repo.
    """
    return grid(
        template_id=template_id,
        origin=origin,
        rows=rows,
        cols=cols,
        spacing=spacing,
        label_prefix="plot",
    )


def _entry(placement: Placement) -> dict:
    """One placement in the closed plan shape ``scene_cli`` accepts.

    Four geometric keys, fresh lists (no entry shares a mutable vector), and no
    ``label``: scene_cli treats a label as inert and drops it from the queued
    request, so writing one here would be a field that never reaches the game.
    """
    return {
        "template_id": placement.template_id,
        "position": [placement.x, placement.y, placement.z],
        "rotation": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }


def field_plan(
    *,
    origin: tuple[float, float, float],
    spacing: float = DEFAULT_SPACING,
    template_id: int = TILE_FIELD,
    rows: int = FIELD_ROWS,
    cols: int = FIELD_COLS,
) -> dict:
    """The ``create-batch`` plan dict, ready to be written to the ``--plan`` file.

    Shape (see the module docstring for the authority)::

        {"placements": [{"template_id": 20001965,
                         "position": [x, y, z],
                         "rotation": [0.0, 0.0, 0.0],
                         "scale": [1.0, 1.0, 1.0]}, ...]}

    Order is **row-major**: row 0 left-to-right, then row 1, matching
    :func:`~tools.gameplan.placement.grid`.  ``origin`` and ``spacing`` carry the
    same meaning and the same warning as in :func:`field_placements`.
    """
    placements = field_placements(
        origin=origin,
        spacing=spacing,
        template_id=template_id,
        rows=rows,
        cols=cols,
    )
    return {"placements": [_entry(placement) for placement in placements]}


def demo_plan() -> dict:
    """The exact plan dict checked in at :data:`FIELD_PLAN_PATH`.

    A single source for the file so a test can prove the checked-in JSON has not
    drifted from the code: regenerate with :func:`field_plan` at
    ``FIELD_ORIGIN``/``FIELD_SPACING``, which is what this returns.
    """
    return field_plan(origin=FIELD_ORIGIN, spacing=FIELD_SPACING)


def orchestrator_command_line(
    *,
    plan_path: str = PLAN_PLACEHOLDER,
    level_id: str = LEVEL_ID_PLACEHOLDER,
    session: str = SESSION_PLACEHOLDER,
    baseline_run: str = BASELINE_RUN_PLACEHOLDER,
    baseline_kind: str = "readonly",
    recovery_dir: str = DEFAULT_RECOVERY_DIR,
    out: str = REVIEW_PLACEHOLDER,
    python: str = "python",
) -> str:
    """STEP ONE — the command that MINTS the review ``command_line`` will consume.

    A single-line STRING for ``tools/game-executor/orchestrate_write_review.py``
    with ``--action create-batch``: it reads ``--plan``, hashes the exact request
    the native wrapper will later compare itself against, checks it against an
    already executed ``--baseline-run`` (``--baseline-kind readonly`` for a
    read-only baseline) and the live session, copies the formal save into
    ``--recovery-dir``, and publishes the native-write-review record to ``--out``.
    It is a coordinator, not an author: there is no ``--reviewed`` flag, and this
    function does not run it.

    ``--session`` and ``--level-id`` are included because the coordinator requires
    them (``orchestrate_write_review.py:368``); like ``command_line``'s values
    they default to ``<...>`` placeholders.  ``--baseline-run`` is likewise a
    placeholder: it names a run that must already have been EXECUTED, which an
    offline planner cannot produce.  ``--out`` and :func:`command_line`'s
    ``--review`` are the *same* value — the file this step writes is the file
    that step reads.
    """
    return " ".join(
        [
            python,
            "-B",
            ORCHESTRATOR,
            "--action",
            "create-batch",
            "--session",
            session,
            "--level-id",
            level_id,
            "--plan",
            plan_path,
            "--baseline-run",
            baseline_run,
            "--baseline-kind",
            baseline_kind,
            "--recovery-dir",
            recovery_dir,
            "--out",
            out,
        ]
    )


def command_line(
    *,
    plan_path: str = PLAN_PLACEHOLDER,
    level_id: str = LEVEL_ID_PLACEHOLDER,
    review: str = REVIEW_PLACEHOLDER,
    session: str = SESSION_PLACEHOLDER,
    queue_dir: str = DEFAULT_QUEUE_DIR,
    python: str = "python",
) -> str:
    """STEP TWO — the ``scene_cli create-batch`` command that sends the field.

    Returns a single-line STRING, meant to be read by a human/agent, filled in
    and run — this function does not run it.  ``level_id``, ``review`` and
    ``plan_path`` default to the ``<...>`` placeholders because an offline
    planner cannot know them: the level id comes from a fresh live discovery, the
    review record is minted per request (step one, :func:`orchestrator_command_line`),
    and the plan path is wherever the caller wrote :func:`field_plan`'s output.
    ``--review`` here must be the ``--out`` of step one.  The elevated queue is
    the project's only write channel, so it is the transport the command uses.
    """
    return " ".join(
        [
            python,
            SCENE_CLI,
            "create-batch",
            "--elevated-queue",
            queue_dir,
            "--session",
            session,
            "--level-id",
            level_id,
            "--review",
            review,
            "--plan",
            plan_path,
        ]
    )


def command_sequence(
    *,
    plan_path: str = PLAN_PLACEHOLDER,
    level_id: str = LEVEL_ID_PLACEHOLDER,
    session: str = SESSION_PLACEHOLDER,
    review: str = REVIEW_PLACEHOLDER,
    baseline_run: str = BASELINE_RUN_PLACEHOLDER,
    baseline_kind: str = "readonly",
    recovery_dir: str = DEFAULT_RECOVERY_DIR,
    queue_dir: str = DEFAULT_QUEUE_DIR,
    python: str = "python",
) -> list[str]:
    """The two commands a run executes, in order: mint the review, then queue.

    ``review`` is threaded into both steps so the file step one writes is what
    step two reads — the caller cannot accidentally point them at different
    records without breaking the pairing visibly.
    """
    return [
        orchestrator_command_line(
            plan_path=plan_path,
            level_id=level_id,
            session=session,
            baseline_run=baseline_run,
            baseline_kind=baseline_kind,
            recovery_dir=recovery_dir,
            out=review,
            python=python,
        ),
        command_line(
            plan_path=plan_path,
            level_id=level_id,
            review=review,
            session=session,
            queue_dir=queue_dir,
            python=python,
        ),
    ]


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--origin", type=float, nargs=3, required=True,
                        help="far-corner (x y z); MUST be verified empty in the current level")
    parser.add_argument("--spacing", type=float, default=DEFAULT_SPACING,
                        help="metres between tiles (default %(default)s; 1 grid = 1 metre)")
    parser.add_argument("--template-id", type=int, default=TILE_FIELD)
    args = parser.parse_args(argv)

    plan = field_plan(origin=tuple(args.origin), spacing=args.spacing,
                      template_id=args.template_id)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print()
    print("# fill the placeholders from a fresh live discovery, then run in order:")
    print("# step 1 — mint the review:")
    print(orchestrator_command_line())
    print("# step 2 — queue the batch with that review:")
    print(command_line())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
