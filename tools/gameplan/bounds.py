"""``level.bounds`` -- an axis-aligned box, and a pre-dispatch position check.

What this module is for
-----------------------
``level.bounds`` (a planning ID, ``tools/authoring/INTERFACE-INVENTORY.md:20``)
is the "scene effective range" a placement must fall inside *before* anything is
created.  The interface is documented by name in the official 关卡设置 chapter as
**系统菜单 → 关卡设置 → 基础 → 运行后场景生效范围**, with an editable ``自定义范围``
form ("editable level 生效范围, and outside content 不生效"), recorded in
``docs/official-docs/LEVEL-SETTINGS-AND-BOUNDS.json:12-18``.

Two entry points:

  * :func:`load_bounds` -- try to read the box out of a ``.gil`` level file.
  * :func:`check_position` -- judge one ``(x, y, z)`` against a box.

THE LEVEL-DERIVED BOUNDS IS STILL UNKNOWN -- and this module does not invent one
-------------------------------------------------------------------------------
``tools/beyond-save/level_settings.py`` decodes ``.gil`` top-level field 11 (the
``LevelSettings`` payload).  Read against every ``.gil`` on this machine that
carries field 11 at all -- **29 of 37 files** -- the vector at ``field 11 > 1 >
1`` is the *same* triple ``(100, 100, 100)`` in all 29 of them.  That triple is
**NOT the only vector-shaped value in field 11**: ``field 11 > 5 > 1 > 2`` is a
preset-point field that is set on TWO levels here -- on 1073741840 it holds a
3-component *coordinate* ``(-0.29665565, 0.12, -10.40005016)`` beside the name
``新建预设点1``, and on 1073741835 the same field holds a single fixed32
(``0d0000c0c0`` = -6.0) beside the name ``新建预设点``.  Only the 3-component form
is unique to 840; the FIELD is not unique to one level.  A coordinate is a bare
POINT -- one position, no extent -- so it is not a box and cannot become one; it
is no scene range, and the negative below stands unchanged.  Evidence the
``(100, 100, 100)`` triple is NOT the editable 运行后场景生效范围:

  * it **never varies** across files, yet the files are different levels with
    different content -- an *editable* setting would differ; a derived constant
    would not;
  * it carries **no origin** -- a box needs one, and the bytes give none;
  * ``field 11 > 1 > 2`` (the ``自定义范围`` candidate) is **empty (0 bytes)** in
    all 29, so that candidate contributes nothing either.

So :func:`load_bounds` returns **None** for every real level file, with the
reason carried by :func:`bounds_status`.  This is a deliberate NEGATIVE, not a
stub: a check that guessed a box here -- e.g. treating ``(100, 100, 100)`` as a
size around an assumed origin -- is the exact invented boundary the project has
already been burned by (``tools/authoring/INTERFACE-INVENTORY.md:20``: "禁止从已有
坐标反推整个合法区域").  ``level_settings.describe`` states the same and this
module only *uses* it.

Because the level-derived box is unknown, :func:`check_position` judges against
an **explicitly supplied** :class:`Bounds` -- the caller passes a box from any
source (a human's reading, a future decode, a test).  A position checked with no
box is a **refusal** (:class:`BoundsUnknown`), never a silent pass: "the check
could not be made" must never read as "the position is fine".

Units and axes
--------------
World space, the same one ``tools/gameplan/placement.py`` lays tiles out in: the
ground plane is XZ and +Y is up.  ``origin`` is the min corner, ``size`` the side
lengths, and the box is CLOSED -- a point exactly on a face is inside.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ``level_settings`` lives beside ``gil_container`` under tools/beyond-save; make
# it importable without depending on the caller's sys.path, the same way
# ``level_settings`` itself reaches ``gil_container``.
_BEYOND_SAVE = Path(__file__).resolve().parents[1] / "beyond-save"
if str(_BEYOND_SAVE) not in sys.path:
    sys.path.insert(0, str(_BEYOND_SAVE))

from level_settings import read_level_settings  # noqa: E402

Vec3 = tuple[float, float, float]

#: The tail of every "no bounds" reason.  One string, quoted by tests, so the
#: negative reads the same wherever a caller surfaces it.
UNKNOWN_BOUNDS_TAIL = (
    "the level-derived bounds is still UNKNOWN: .gil field 11 exposes no usable "
    "box, because its basic-message vector (field 11 > 1 > 1) is the constant "
    "(100, 100, 100) in every readable .gil on this machine and never tracks an "
    "edit, it carries no origin, and the 自定义范围 candidate (field 11 > 1 > 2) is "
    "empty.  (Field 11 > 5 > 1 > 2 is a preset-point field set on more than one "
    "level -- a 3-component coordinate on 1073741840 and a single fixed32 on "
    "1073741835 -- but even the 3-component form is a bare POINT, not a box, so "
    "it is no scene range either.)  No box is invented here -- see "
    "docs/official-docs/LEVEL-SETTINGS-AND-BOUNDS.json for the documented field "
    "name (关卡设置 -> 基础 -> 运行后场景生效范围) whose SHAPE remains unproven."
)


# --------------------------------------------------------------------------- #
# the box
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Bounds:
    """An axis-aligned box in game world space.

    ``origin`` is the ``(x, y, z)`` MIN corner; ``size`` the ``(x, y, z)`` side
    lengths, each strictly positive.  The box is CLOSED: a point on any face is
    inside.  Constructing one with a non-positive size raises :class:`ValueError`
    -- a zero or negative extent is not a box, and silently accepting it would
    make every later check meaningless.

    Nothing here says where a box comes from.  This module cannot derive one from
    a level (see the module docstring); a caller supplies it explicitly.
    """

    origin: Vec3
    size: Vec3

    def __post_init__(self) -> None:
        try:
            origin = tuple(float(v) for v in self.origin)
            size = tuple(float(v) for v in self.size)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"origin/size must be 3 numbers: {exc}") from None
        if len(origin) != 3 or len(size) != 3:
            raise ValueError(
                f"origin and size must each be 3 numbers, got "
                f"{self.origin!r} / {self.size!r}"
            )
        for name, side in zip("xyz", size):
            if not side > 0:
                raise ValueError(f"size.{name} must be > 0, got {side}")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "size", size)

    @property
    def min_corner(self) -> Vec3:
        return self.origin

    @property
    def max_corner(self) -> Vec3:
        return tuple(o + s for o, s in zip(self.origin, self.size))  # type: ignore[return-value]

    def outside_axes(self, point) -> tuple[str, ...]:
        """Names of the axes (a subset of ``("x","y","z")``) on which *point* lies
        outside the closed box.  Empty tuple when the point is inside."""
        x, y, z = _as_point(point)
        out: list[str] = []
        for axis, coord, low, high in zip("xyz", (x, y, z), self.min_corner, self.max_corner):
            if coord < low or coord > high:
                out.append(axis)
        return tuple(out)

    def contains(self, point) -> bool:
        """True when *point* is inside the closed box."""
        return not self.outside_axes(point)

    def __str__(self) -> str:
        lo, hi = self.min_corner, self.max_corner
        return (f"x[{lo[0]:g}, {hi[0]:g}] "
                f"y[{lo[1]:g}, {hi[1]:g}] "
                f"z[{lo[2]:g}, {hi[2]:g}]")


# --------------------------------------------------------------------------- #
# the verdict
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PositionVerdict:
    """Base of every :func:`check_position` result.  Truthiness is ``ok``.

    ``reason`` is always populated for the non-ok halves, so a caller that logs
    the verdict logs *why*.
    """
    reason: str = ""
    ok: bool = False

    def __bool__(self) -> bool:  # so ``if not check_position(...): report`` works
        return self.ok


@dataclass(frozen=True)
class Inside(PositionVerdict):
    """The point is inside the box -- the only ``ok`` verdict."""
    ok: bool = True


@dataclass(frozen=True)
class OutOfBounds(PositionVerdict):
    """The point is outside the box.  Carries the axes that failed, for a report."""
    point: Optional[Vec3] = None
    outside_axes: tuple[str, ...] = ()
    bounds: Optional[Bounds] = None


@dataclass(frozen=True)
class BoundsUnknown(PositionVerdict):
    """REFUSAL: no box is known, so no position can be judged.

    This is *not* a pass.  It is the answer :func:`check_position` gives when
    ``bounds is None`` -- the common case today, since
    :func:`load_bounds` cannot derive a box from any level.
    """


#: The one ``ok`` value :func:`check_position` returns.  Frozen, so sharing it is safe.
OK = Inside()


def _as_point(point) -> Vec3:
    """Coerce *point* to a ``(float, float, float)``; raise ValueError otherwise."""
    try:
        x, y, z = point
    except (TypeError, ValueError) as exc:
        raise ValueError(f"point must be a 3-sequence (x, y, z), got {point!r}") from exc
    return (float(x), float(y), float(z))


def _outside_reason(point: Vec3, bounds: Bounds, axes: tuple[str, ...]) -> str:
    lows = dict(zip("xyz", bounds.min_corner))
    highs = dict(zip("xyz", bounds.max_corner))
    coords = dict(zip("xyz", point))
    detail = "; ".join(
        f"{axis}={coords[axis]:g} outside [{lows[axis]:g}, {highs[axis]:g}]" for axis in axes
    )
    return (
        f"position ({point[0]:g}, {point[1]:g}, {point[2]:g}) is outside the "
        f"supplied bounds box ({bounds}): {detail}"
    )


def check_position(bounds: Optional[Bounds], point) -> PositionVerdict:
    """Judge *point* against *bounds*.

    Returns:

      * :data:`OK` (an :class:`Inside`) when the point is inside the closed box;
      * :class:`OutOfBounds` (``ok=False``, with ``reason`` / ``outside_axes``)
        when it is outside;
      * :class:`BoundsUnknown` (``ok=False``) when ``bounds is None`` -- a
        REFUSAL, not a pass.  ``level.bounds`` is unknown (module docstring), so
        the honest answer to "is this position legal?" with no box is "cannot
        say", and a caller must treat that as a problem, not as permission.

    *bounds* is judged exactly as given -- this function never derives a box, and
    never defaults one in.  Raises :class:`ValueError` if *point* is not three
    numbers.
    """
    if bounds is None:
        return BoundsUnknown(reason=UNKNOWN_BOUNDS_TAIL)
    p = _as_point(point)
    axes = bounds.outside_axes(p)
    if axes:
        return OutOfBounds(
            reason=_outside_reason(p, bounds, axes),
            point=p,
            outside_axes=axes,
            bounds=bounds,
        )
    return OK


# --------------------------------------------------------------------------- #
# reading a box out of a level (which yields none -- on purpose)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BoundsStatus:
    """Why :func:`load_bounds` returned what it returned, with the evidence.

    ``bounds`` is the decoded box (always ``None`` today); ``reason`` is the
    human statement of why; ``field11_present`` records whether the level carried
    the ``LevelSettings`` payload at all, so a caller can tell "no settings" from
    "settings, but no usable box".
    """
    bounds: Optional[Bounds]
    reason: str
    level_id: int
    field11_present: bool


def _bounds_from_settings(settings) -> Optional[Bounds]:
    """The one place a box *could* be built from a decoded level -- and does not.

    ``settings.extent`` is the float vector of field 11's basic sub-message
    (``field 11 > 1 > 1``) -- this module's scene-range candidate.  It is not the
    only vector in field 11 (a preset-point coordinate lives at ``field 11 > 5 >
    1 > 2``), but that other one is a point, not a box.  The bytes justify reading
    *this* one as three floats (``level_settings.parse_vec3`` pins that), but NOT
    as a box: it is invariant across every file, has no origin, and its 自定义范围
    sibling is empty.  Returning ``None`` here is the deliberate negative; when a
    future decode finds a value that *varies* with an edit, this is where it turns
    into a :class:`Bounds`.
    """
    return None


def bounds_status(level_gil_path) -> BoundsStatus:
    """Decode *level_gil_path* READ-ONLY and report the (absent) bounds with its reason.

    Reading errors propagate (``FileNotFoundError`` for a missing file,
    ``ContainerError`` for bytes that are not a ``.gil`` container): "cannot read
    the level" is a different situation from "the level has no known bounds", and
    collapsing the two would hide a real fault behind a benign-looking ``None``.
    """
    settings = read_level_settings(Path(level_gil_path))

    if not settings.present:
        reason = (
            f"level {settings.level_id}: .gil field 11 (LevelSettings) is ABSENT, "
            f"so the level exposes no 运行后场景生效范围 at all.  " + UNKNOWN_BOUNDS_TAIL
        )
        return BoundsStatus(bounds=None, reason=reason,
                            level_id=settings.level_id, field11_present=False)

    box = _bounds_from_settings(settings)
    extent = settings.extent
    if box is None:
        observed = (
            f"field 11 > 1 > 1 decodes to the vector {extent}"
            if extent is not None
            else "field 11 > 1 > 1 does not decode as a 3-float vector"
        )
        reason = f"level {settings.level_id}: {observed}, but " + UNKNOWN_BOUNDS_TAIL
        return BoundsStatus(bounds=None, reason=reason,
                            level_id=settings.level_id, field11_present=True)

    return BoundsStatus(bounds=box,
                        reason=f"level {settings.level_id}: bounds decoded as {box}",
                        level_id=settings.level_id, field11_present=True)


def load_bounds(level_gil_path) -> Optional[Bounds]:
    """The bounds box of a ``.gil`` level -- ``None`` today for every real level.

    Returns ``None`` because the level's bytes do not support a box (see the
    module docstring and :func:`bounds_status` for the evidence).  The box that
    :func:`check_position` judges against must therefore be supplied explicitly
    by the caller; the level-derived bounds remains unknown.

    Reading errors propagate (see :func:`bounds_status`).
    """
    return bounds_status(level_gil_path).bounds
