"""Find an empty patch of ground to place something on (the "落点" question).

Why this exists
---------------
Memory records a trap: the spawn preset point ``(-547.5, -2.5, -547.5)`` is a
GLOBAL constant shared by six different saves, yet it is **not** a safe drop
point — it is where the player template spawns, so it says nothing about whether
the ground there is empty.  Dropping a creation onto a cell that already holds a
prop, a farm plot, or the spawn point itself produces an overlap the editor will
not warn about.

So before placing anything we answer one question offline: *given where the
entities already in this level sit, where is an axis-aligned patch of the
requested footprint that contains none of them, as close to the level origin as
possible?*  :func:`find_gap` is that answer.  It touches no bridge, no game, and
no file — it is a pure function of geometry, exactly like
:mod:`tools.gameplan.placement`.

Where the positions come from
-----------------------------
``existing_positions`` is the set of entity positions **as read live from the
open level** — the same read-only native path that
:func:`tools.gameplan.live.read_live` drives (``tools/gameplan/live.py``).  That
path never trusts a recorded id; the per-entity ``[x, y, z]`` values themselves
are what the native context snapshot reports (its ``"position": [x, y, z]``
field, ``tools/game-executor/decode_context_snapshot.py``).  This module never
reads them itself: it is *handed* them, so it stays testable with a plain list
and never guesses.  Entries may be bare ``[x, y, z]`` triples or snapshot rows
``{"position": [x, y, z]}``; a row whose ``position`` is ``None`` (the snapshot's
marker for an entity with no valid position) is skipped.

The geometry
------------
* 1 grid cell = 1 metre, so ``spacing`` is the metre step between candidate
  origins and a 3x3-metre footprint is ``size_x=3, size_z=3``.
* The ground plane is XZ; ``y`` is ignored when deciding occupancy (a tile on the
  ground and a prop floating above it still fight over the same cell of ground),
  and the returned origin carries ``y = 0.0``.  A caller that needs a specific
  ground height sets it; this function only solves the horizontal question.
* A candidate origin is the patch's **minimum corner**: the patch covers
  ``x in [ox, ox + size_x]`` and ``z in [oz, oz + size_z]``.  A point exactly on
  an edge counts as **inside** (the occupancy test is a *closed* rectangle),
  because a creature standing on the seam is still an overlap.

Determinism
-----------
Candidate origins sit on the ``spacing`` lattice, restricted to points within
``search_radius`` metres of the level origin ``(0, 0, 0)``.  Among the patches
that contain no entity, the one whose origin is nearest ``(0, 0)`` in the XZ
plane wins.  **Ties are broken by the smaller ``x``, then the smaller ``z``.**
The result is therefore a pure, order-independent function of the inputs: feeding
the same positions in a different order cannot change the answer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

#: A 3-D point as this package uses it elsewhere (``tools/gameplan/placement.py``).
Vec3 = tuple[float, float, float]


class NoGapError(RuntimeError):
    """No candidate patch anywhere in the searched area is free of entities.

    Raised by :func:`find_gap` when every lattice origin within ``search_radius``
    is already covered by an existing entity.  It is a *named* error on purpose:
    a caller must be able to distinguish "the area is genuinely full" from a bad
    argument, and must never fall back to dumping the new entity at the origin.
    """


def _position_xz(entry) -> tuple[float, float] | None:
    """The ``(x, z)`` of one entity entry, or ``None`` if it has no position.

    Accepts a bare sequence (``[x, y, z]``) or a mapping with a ``"position"``
    key (a native context-snapshot row).  A mapping whose position is ``None`` is
    the snapshot's "no valid position" marker and is skipped, not raised on.
    """
    if isinstance(entry, Mapping):
        entry = entry.get("position")
        if entry is None:
            return None
    if entry is None:
        return None
    try:
        return float(entry[0]), float(entry[2])
    except (TypeError, IndexError, ValueError) as error:
        raise ValueError(
            f"entity position must be a (x, y, z) sequence, got {entry!r}"
        ) from error


def patch_covers(
    origin: Sequence[float], position: Sequence[float], *, size_x: float, size_z: float
) -> bool:
    """Whether ``position`` lies inside the patch rooted at ``origin``.

    The patch is the closed rectangle ``x in [ox, ox+size_x]``,
    ``z in [oz, oz+size_z]`` — edges included.  Exposed so a caller can re-check
    :func:`find_gap`'s answer against the very positions it was given.
    """
    ox, oz = float(origin[0]), float(origin[2])
    px, pz = float(position[0]), float(position[2])
    return ox <= px <= ox + size_x and oz <= pz <= oz + size_z


def _occupied(ox: float, oz: float, size_x: float, size_z: float,
              occupied: list[tuple[float, float]]) -> bool:
    x_hi = ox + size_x
    z_hi = oz + size_z
    for px, pz in occupied:
        if ox <= px <= x_hi and oz <= pz <= z_hi:
            return True
    return False


def find_gap(
    existing_positions: Iterable,
    *,
    size_x: float,
    size_z: float,
    spacing: float = 1.0,
    search_radius: float = 50.0,
) -> Vec3:
    """The nearest-to-origin empty patch of footprint ``size_x`` x ``size_z``.

    Returns the patch's minimum corner as ``(ox, 0.0, oz)`` (see the module
    docstring: ``y`` is not solved here).  ``existing_positions`` are the
    positions read live from the open level — see the module docstring for where
    they come from and what shapes are accepted.

    ``spacing`` is the metre step between candidate origins (default 1.0 — one
    grid cell), and ``search_radius`` bounds how far from the level origin the
    search reaches.  Among all free candidates the nearest to ``(0, 0)`` wins;
    ties go to the smaller ``x``, then the smaller ``z`` (documented tie-break,
    so the answer never depends on input order).

    Raises :class:`NoGapError` when no candidate patch within ``search_radius``
    is free.  Raises :class:`ValueError` for a non-positive footprint, a
    non-positive ``spacing``, a negative ``search_radius``, or a malformed
    position entry.
    """
    if not size_x > 0:
        raise ValueError(f"size_x must be > 0, got {size_x}")
    if not size_z > 0:
        raise ValueError(f"size_z must be > 0, got {size_z}")
    if not spacing > 0:
        raise ValueError(f"spacing must be > 0, got {spacing}")
    if search_radius < 0:
        raise ValueError(f"search_radius must be >= 0, got {search_radius}")

    occupied: list[tuple[float, float]] = []
    for entry in existing_positions:
        xz = _position_xz(entry)
        if xz is not None:
            occupied.append(xz)

    # Lattice points within `search_radius` of the origin.  A small epsilon keeps
    # an exactly-on-radius point (e.g. spacing=1, radius=5) from dropping out to
    # floating-point error.
    span = int(math.floor(search_radius / spacing + 1e-9))
    limit = search_radius + 1e-9

    best: tuple[float, float] | None = None
    best_key: tuple[float, float, float] | None = None
    for i in range(-span, span + 1):
        ox = i * spacing
        for j in range(-span, span + 1):
            oz = j * spacing
            distance = math.hypot(ox, oz)
            if distance > limit:
                continue
            if _occupied(ox, oz, size_x, size_z, occupied):
                continue
            key = (distance, ox, oz)
            if best_key is None or key < best_key:
                best_key, best = key, (ox, oz)

    if best is None:
        raise NoGapError(
            f"no free {size_x}x{size_z} patch within {search_radius}m of the origin "
            f"({len(occupied)} entities considered, spacing {spacing})"
        )
    return (float(best[0]), 0.0, float(best[1]))
