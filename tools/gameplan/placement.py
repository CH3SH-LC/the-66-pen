"""M6b — scene placement (地图上的摆放设计).

M6b is the "lay objects out on the map" half of the M6 milestone pair (see
``docs/MODULE-PLAN-6.md:150``).  Its acceptance test is concrete: *place a 3x3
grid of nine plots in a level, save, read back — all nine present, positions
right.*

Why a planner and not a transform
---------------------------------
The natural tool for laying out a grid would be ``entity.transform`` (move an
existing entity).  **This project does not have it** — ``entity.transform`` is
entirely missing (``docs/MODULE-PLAN-6.md``, "M6b … 没有 ``entity.transform``
就摆不出布局").  But ``entity.create`` *already takes a position*, so a regular
layout needs no transform at all: we simply create N entities, each at its own
computed coordinate.  This module is the offline planner that produces that
list — a pure function of geometry, with no bridge contact and no native calls.

The tiles
---------
The two official farm-plot tiles (地块) named in ``docs/MODULE-PLAN-6.md:150``
are :data:`TILE_FIELD` ``20001965 土田`` and :data:`TILE_SINGLE_FIELD`
``20001966 单块土田``.  There are only these two; everything else in the object
catalogue is ordinary prop (2722 options).  A caller passes one of these as
``template_id``.

What this module is *not*
-------------------------
It never creates anything.  :func:`to_scene_requests` returns plain dicts
shaped exactly like the ``entity.create`` CLI args, so a caller (or a future
``builder``) decides *if and when* any native call is made.  Request ids are
**minted by the caller** via ``request_id_for`` — this layer must not invent ids,
because a request id is a function of the request, not of the layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

#: The two official farm-plot tiles (地块).  There is no third.
TILE_FIELD = 20001965  # 土田（成块的大田）
TILE_SINGLE_FIELD = 20001966  # 单块土田（单格）

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Placement:
    """One entity to create: which template, where, and what to call it.

    ``label`` is the human/accounting name for this placement and the input to
    the caller's request-id minter.  It must be unique within a grid — :func:`grid`
    guarantees that by appending the flat row-major index to ``label_prefix``.
    """

    template_id: int
    x: float
    y: float
    z: float
    label: str

    @property
    def position(self) -> list[float]:
        """``[x, y, z]`` — the list form ``entity.create --position`` wants."""
        return [self.x, self.y, self.z]


def grid(
    *,
    template_id: int,
    origin: Vec3 = (0.0, 0.0, 0.0),
    rows: int,
    cols: int,
    spacing: float,
    label_prefix: str = "plot",
) -> list[Placement]:
    """Lay out ``rows x cols`` placements in a flat, row-major grid.

    Each placement sits at ``origin + (col*spacing, 0, row*spacing)`` — i.e. the
    grid is axis-aligned in the XZ plane (the game's ground plane), with every
    tile at the origin's Y.  Ordering is **row-major**: row 0 left-to-right,
    then row 1, and so on, so index ``i`` maps to ``row = i // cols``,
    ``col = i % cols``.

    ``origin`` is the far corner (row 0, col 0).  A 3x3 grid at ``spacing=s``
    therefore spans ``x`` in ``[origin.x, origin.x + 2s]`` and ``z`` in
    ``[origin.z, origin.z + 2s]`` — nine tiles, one per lattice point.

    Raises :class:`ValueError` if ``rows < 1``, ``cols < 1``, or
    ``spacing <= 0`` (a non-positive spacing cannot tile a grid).
    """
    if rows < 1:
        raise ValueError(f"rows must be >= 1, got {rows}")
    if cols < 1:
        raise ValueError(f"cols must be >= 1, got {cols}")
    if not spacing > 0:
        raise ValueError(f"spacing must be > 0, got {spacing}")

    ox, oy, oz = (float(origin[0]), float(origin[1]), float(origin[2]))
    step = float(spacing)

    placements: list[Placement] = []
    for row in range(rows):
        for col in range(cols):
            index = row * cols + col  # flat row-major index
            placements.append(
                Placement(
                    template_id=int(template_id),
                    x=ox + col * step,
                    y=oy,
                    z=oz + row * step,
                    label=f"{label_prefix}_{index}",
                )
            )
    return placements


def to_scene_requests(
    placements: Iterable[Placement],
    *,
    request_id_for: Callable[[str], str],
) -> list[dict]:
    """Turn placements into ``entity.create`` CLI argument dicts, one per tile.

    Each dict has exactly the keys the ``entity.create`` CLI takes::

        {'template_id': ..., 'position': [x, y, z], 'label': ..., 'request_id': ...}

    ``request_id_for`` is called once per placement with its ``label`` and must
    return the request id to use.  The id is deliberately *not* computed here:
    request ids belong to the request (a caller minting ids from a counter,
    journal, or run name owns that decision), and re-deriving them offline is
    how two different requests silently collide.
    """
    requests: list[dict] = []
    for placement in placements:
        requests.append(
            {
                "template_id": placement.template_id,
                "position": placement.position,
                "label": placement.label,
                "request_id": request_id_for(placement.label),
            }
        )
    return requests


def to_batch_plan(placements: Iterable[Placement]) -> dict:
    """Turn placements into the ``create-batch`` plan object ``scene_cli`` reads.

    The shape is not invented here — it is the one
    ``tools/game-executor/scene_cli.py:202`` (:func:`read_plan_spec`) and
    ``scene_cli.py:195`` (:func:`normalize_placements`) accept exactly::

        {"placements": [{"template_id": N,
                         "position": [x, y, z],
                         "rotation": [0, 0, 0],
                         "scale": [1, 1, 1]}, ...]}

    ``scene_cli.normalize_placement`` (line 170) allows the keys
    ``template_id``/``position``/``rotation``/``scale``/``label`` and requires
    ``template_id``, ``position`` and ``scale``.  We always emit the four
    geometric keys so the file is self-describing, and we omit ``label``: the
    same function treats a label as inert and drops it from the queued request
    (its comment at line 174), so a label written here would be a field that
    never reaches the game.

    ``rotation`` is the identity and ``scale`` is unity — this planner places
    axis-aligned tiles at a stated size, so a rotated or scaled tile would be a
    lie about the geometry :func:`grid` computed.

    Each entry's ``position``/``rotation``/``scale`` is a fresh list, so no two
    entries share a mutable object.
    """
    return {
        "placements": [
            {
                "template_id": placement.template_id,
                "position": [placement.x, placement.y, placement.z],
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
            for placement in placements
        ]
    }


def describe(placements: Sequence[Placement]) -> str:
    """A one-line human summary: how many, and the axis-aligned extent.

    The extent is the bounding box over the XZ span (the plane the grid tiles),
    which is what a human checks first when a layout "looks wrong".
    """
    count = len(placements)
    if count == 0:
        return "0 placements"

    xs = [p.x for p in placements]
    zs = [p.z for p in placements]
    ys = {p.y for p in placements}
    y_note = f", y={next(iter(ys)):g}" if len(ys) == 1 else ""
    return (
        f"{count} placements: x=[{min(xs):g}, {max(xs):g}] "
        f"z=[{min(zs):g}, {max(zs):g}]{y_note}"
    )
