"""A pre-dispatch guard: is a whole layout inside the level's effective range?

Why this module exists
----------------------
:mod:`tools.gameplan.placement` computes where N tiles *should* go
(``tools/gameplan/placement.py:68`` :func:`grid`) and hands the caller
``entity.create`` args (``tools/gameplan/placement.py:118``
:func:`to_scene_requests`).  Nothing there asks whether those coordinates are
*inside the level*.  :mod:`tools.gameplan.bounds` supplies the two ingredients
for that question -- an axis-aligned :class:`~tools.gameplan.bounds.Bounds`
(``tools/gameplan/bounds.py:98``) and a one-point check
(``tools/gameplan/bounds.py:229`` :func:`check_position`) -- but leaves the
per-layout decision to the caller.

This module is that decision, made once, in one place, **before** any request is
minted or dispatched.  Nothing here creates anything, reads a bridge, or sends a
message; it is a pure function of a layout and a box.

The three-way answer (and the collapse it exists to prevent)
------------------------------------------------------------
A guard that returned a boolean would be a bug.  There are **three** distinct
situations, and two of them are both "not ok" for opposite reasons:

===============  ===========  ============  ============  ==================================
code             ``ok``       ``certified`` ``blocking``   meaning
===============  ===========  ============  ============  ==================================
``CERTIFIED``    ``True``     ``True``      ``False``      every placement is inside the box --
                                                            a human certified the layout
``OUT_OF_BOUNDS````False``    ``True``      ``True``       the box is known and the layout
                                                            violates it -- the guard BLOCKS
``BOUNDS_UNKNOWN````False``   ``False``     ``False``      no box is known, so the guard
                                                            cannot certify -- it REFUSES but
                                                            does NOT block
===============  ===========  ============  ============  ==================================

The distinction that must never collapse is **OUT_OF_BOUNDS vs BOUNDS_UNKNOWN**
(the same point ``tools/gameplan/bounds.py:48-52`` makes: "the check could
not be made" must never read as "the position is fine" -- *and*, added here, must
never read as "the position is bad" either).  The normal case *today* is
``BOUNDS_UNKNOWN``: ``tools/gameplan/bounds.py:330`` :func:`load_bounds` returns
``None`` for every real level, because the level's ``.gil`` exposes no usable box
(``tools/gameplan/bounds.py:17-46``).  A caller in that case must be able to say
"the guard could not certify this, but it is not blocking me -- I proceed
knowingly", which is exactly what ``BOUNDS_UNKNOWN`` means and what a bare
``False`` would destroy.

Decide with ``.blocking`` / ``.may_proceed`` -- **not** with ``bool()``
---------------------------------------------------------------------
``bool(verdict)`` is ``verdict.ok`` (mirroring
``tools/gameplan/bounds.py:175-177``).  Therefore ``OUT_OF_BOUNDS`` and
``BOUNDS_UNKNOWN`` are *both* falsy -- which is precisely why truthiness must
not be the call.  Read :attr:`GuardVerdict.blocking` (or its inverse
:attr:`GuardVerdict.may_proceed`) to decide, and :attr:`GuardVerdict.code` to
tell *which* answer you got.

This is the same asymmetry the project's doctrine names
(``CLAUDE.md`` 第六节「边界是不对称的」): a guard that only knows the "reject"
direction must still be honest about the direction it *cannot* judge.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

from .bounds import Bounds, UNKNOWN_BOUNDS_TAIL, load_bounds

Vec3 = tuple[float, float, float]

# --------------------------------------------------------------------------- #
# the verdict codes -- three strings a caller can branch on, never merged
# --------------------------------------------------------------------------- #

CODE_CERTIFIED = "CERTIFIED"
CODE_OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
CODE_BOUNDS_UNKNOWN = "BOUNDS_UNKNOWN"

#: Printed at the head of every refusal, so a log line reads the same wherever
#: a caller surfaces it.  The words "refusing to certify" and "NOT blocking" are
#: load-bearing: the first says the guard did not pass the layout, the second
#: says it is not standing in the caller's way.
REFUSAL_PREFIX = (
    "bounds unknown -- refusing to certify, but NOT blocking (the caller may "
    "proceed knowingly).  "
)


# --------------------------------------------------------------------------- #
# what a guard answers
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GuardVerdict:
    """Base of every :func:`guard` result -- a *three-way*, not a boolean.

    ``ok`` mirrors ``tools/gameplan/bounds.py:172`` -- true only for the pass, and
    supplied so ``bool()`` means the same thing here as there.  But the decision a
    caller actually makes is :attr:`blocking`; see the module docstring for why
    truthiness alone cannot distinguish an out-of-bounds rejection from an
    unknown-bounds refusal (both are ``ok=False``).
    """

    code: str = "UNKNOWN"
    reason: str = ""
    ok: bool = False
    certified: bool = False
    blocking: bool = False

    def __bool__(self) -> bool:  # == ``ok``; NOT the block decision (see class doc)
        return self.ok

    @property
    def may_proceed(self) -> bool:
        """True unless the guard is actively blocking (``OUT_OF_BOUNDS``).

        This is the single bit a caller gates dispatch on.  It is ``True`` for
        both ``CERTIFIED`` and ``BOUNDS_UNKNOWN`` -- the difference between those
        two is :attr:`certified`, not proceedability.
        """
        return not self.blocking


@dataclass(frozen=True)
class Certified(GuardVerdict):
    """Every placement is inside the box -- the layout is certified.

    Only reachable when a box was supplied *and* every point fell inside it.  A
    caller that reaches this has a human-certified layout.
    """

    code: str = CODE_CERTIFIED
    ok: bool = True
    certified: bool = True
    blocking: bool = False
    bounds: Optional[Bounds] = None
    count: int = 0


@dataclass(frozen=True)
class OutOfBounds(GuardVerdict):
    """The box is known and at least one placement violates it -- BLOCKING.

    Both halves are certain: the box exists (or this verdict could not name the
    axes) and the offending points are outside it.  ``offenders`` carries one
    record per failing placement, in layout order.
    """

    code: str = CODE_OUT_OF_BOUNDS
    ok: bool = False
    certified: bool = True
    blocking: bool = True
    bounds: Optional[Bounds] = None
    count: int = 0
    offenders: tuple["Offender", ...] = ()


@dataclass(frozen=True)
class Uncertified(GuardVerdict):
    """REFUSAL: no box is known, so the guard cannot judge -- and does NOT block.

    This is *not* a pass (``ok`` is ``False``, ``certified`` is ``False``) and it
    is *not* a rejection (``blocking`` is ``False``).  It is the answer
    :func:`guard` gives when ``bounds is None`` -- the common case today
    (``tools/gameplan/bounds.py:330``).  A caller that proceeds here proceeds
    knowingly, without a certificate.
    """

    code: str = CODE_BOUNDS_UNKNOWN
    ok: bool = False
    certified: bool = False
    blocking: bool = False
    count: int = 0


@dataclass(frozen=True)
class Offender:
    """One placement that fell outside the box: which, where, and on which axes."""

    label: str
    position: Vec3
    outside_axes: tuple[str, ...]


# --------------------------------------------------------------------------- #
# reading a placement's position (Placement, or a bare (x, y, z))
# --------------------------------------------------------------------------- #

def _position_of(item) -> Vec3:
    """The ``(x, y, z)`` of a placement.

    Accepts a :class:`tools.gameplan.placement.Placement` (its ``.position``
    property, ``tools/gameplan/placement.py:62``) or any bare 3-sequence — so a
    caller may guard a hand-written layout as easily as a :func:`grid` output.
    Raises :class:`ValueError` otherwise; a placement whose position cannot be
    read is a fault, not a pass.
    """
    pos = getattr(item, "position", None)
    if pos is None:
        pos = item
    try:
        x, y, z = pos
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"placement must be a Placement or a 3-sequence (x, y, z), got {item!r}"
        ) from exc
    return (float(x), float(y), float(z))


def _label_of(item, index: int) -> str:
    label = getattr(item, "label", None)
    return str(label) if label is not None else f"#{index}"


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #

def guard(
    placements: Iterable,
    *,
    bounds: Optional[Bounds],
) -> GuardVerdict:
    """Judge every placement against *bounds*, before anything is dispatched.

    Returns one of three verdicts (module docstring), keyed by ``.code``:

      * :class:`Certified` (``CERTIFIED``) -- *bounds* is a box and every
        placement is inside it (closed box: a point on a face counts as inside).
      * :class:`OutOfBounds` (``OUT_OF_BOUNDS``, ``blocking=True``) -- *bounds* is
        a box and at least one placement is outside it; ``offenders`` lists them.
      * :class:`Uncertified` (``BOUNDS_UNKNOWN``, ``blocking=False``) --
        ``bounds is None``: no box is known, so the guard refuses to certify but
        does **not** block.

    *bounds* is used **exactly as given** -- this function never derives a box
    (``tools/gameplan/bounds.py:330`` cannot derive one from any level) and never
    defaults one in.  It must be either ``None`` or a
    :class:`~tools.gameplan.bounds.Bounds`; **any other object is refused** with
    :class:`ValueError`, because a malformed box silently treated as "no box"
    would turn a caller's bug into a benign-looking refusal, and treated as a box
    would be worse still.  ``None`` is the one legitimate "no box" spelling.

    Empty *placements* with a known box is vacuously :class:`Certified` (nothing
    to violate the box); with no box it is still an :class:`Uncertified` refusal.

    Raises :class:`ValueError` for a malformed box or an unreadable placement
    position.
    """
    items = list(placements)

    if bounds is None:
        return Uncertified(
            reason=(
                REFUSAL_PREFIX + UNKNOWN_BOUNDS_TAIL
            ),
            count=len(items),
        )
    if not isinstance(bounds, Bounds):
        raise ValueError(
            "bounds must be a tools.gameplan.bounds.Bounds or None, got "
            f"{type(bounds).__name__} {bounds!r} -- a malformed box cannot be "
            "judged, so the guard refuses rather than guess"
        )

    offenders: list[Offender] = []
    for index, item in enumerate(items):
        point = _position_of(item)
        axes = bounds.outside_axes(point)
        if axes:
            offenders.append(
                Offender(label=_label_of(item, index), position=point, outside_axes=axes)
            )

    if offenders:
        shown = offenders[:5]
        detail = "; ".join(
            f"{o.label} at ({o.position[0]:g}, {o.position[1]:g}, {o.position[2]:g}) "
            f"outside {','.join(o.outside_axes)}"
            for o in shown
        )
        more = f" (+{len(offenders) - len(shown)} more)" if len(offenders) > len(shown) else ""
        return OutOfBounds(
            reason=(
                f"{len(offenders)} of {len(items)} placements fall outside the supplied "
                f"bounds box ({bounds}): {detail}{more}"
            ),
            bounds=bounds,
            count=len(items),
            offenders=tuple(offenders),
        )

    return Certified(
        reason=f"all {len(items)} placements are inside the supplied bounds box ({bounds})",
        bounds=bounds,
        count=len(items),
    )


def guard_default(
    placements: Iterable,
    *,
    level_gil_path: Optional[Union[str, Path]] = None,
) -> GuardVerdict:
    """Guard *placements* against the bounds of a level -- ``None`` today.

    Reads the box with :func:`tools.gameplan.bounds.load_bounds` (``level_gil_path``
    when given) and feeds the result to :func:`guard`.  Because ``load_bounds``
    returns ``None`` for every real level (``tools/gameplan/bounds.py:330``), the
    **normal answer today is :class:`Uncertified`**: *bounds unknown -- refusing to
    certify, but NOT blocking*.  The caller may then choose to proceed knowingly;
    the guard has told the truth about what it could and could not establish.

    ``level_gil_path`` is optional.  Supplied, the level is read READ-ONLY and its
    (absent) box decides the verdict; reading errors from ``load_bounds`` propagate
    (``tools/gameplan/bounds.py:338``: "cannot read the level" is a fault, distinct
    from "the level has no known bounds").  Omitted, no level is read at all and the
    verdict is the same refusal -- the guard does not invent a box from the absence
    of a path any more than from the absence of a field.

    A caller who *knows* the box should call :func:`guard` directly with an explicit
    :class:`~tools.gameplan.bounds.Bounds`; that is the path by which a human
    certifies a layout.
    """
    items = list(placements)

    if level_gil_path is None:
        return Uncertified(
            reason=(
                REFUSAL_PREFIX
                + "no level .gil path was supplied, so load_bounds could not be "
                "consulted at all, and no box is invented from its absence.  "
                + UNKNOWN_BOUNDS_TAIL
            ),
            count=len(items),
        )

    bounds = load_bounds(level_gil_path)  # READ-ONLY; raises on a real read fault
    if bounds is None:
        return Uncertified(
            reason=(
                REFUSAL_PREFIX
                + f"load_bounds({str(Path(level_gil_path))!r}) returned None: the "
                "level's bytes expose no box on which to certify this layout.  "
                + UNKNOWN_BOUNDS_TAIL
            ),
            count=len(items),
        )
    return guard(items, bounds=bounds)


__all__ = [
    "CODE_BOUNDS_UNKNOWN",
    "CODE_CERTIFIED",
    "CODE_OUT_OF_BOUNDS",
    "Certified",
    "GuardVerdict",
    "Offender",
    "OutOfBounds",
    "REFUSAL_PREFIX",
    "Uncertified",
    "guard",
    "guard_default",
]
