"""``asset.measure`` -- a template's world size, for computing grid spacing.

What this module is for
-----------------------
Laying out a grid of props needs one number the planner cannot invent: **how
wide a template is**, so ``spacing`` can tile tiles edge to edge instead of
being a guess.  The planning ID for that number is ``asset.measure``
(``tools/authoring/INTERFACE-INVENTORY.md:22``, P1 "模板尺寸、碰撞及落点测量");
its acceptance shape (``docs/NEW-FEATURE-PLAN.md:53``) is "given a template id,
get its size, to compute placement spacing".

Two entry points:

  * :func:`grid_spacing_for` -- the edge-to-edge spacing for a template, or
    ``None`` when the size is unknown.
  * :func:`describe_unknown` -- a reason string that names *where* the size would
    have to come from, so a caller logs why it got ``None``.

THE TEMPLATE SIZE IS UNKNOWN -- and this module does not invent one
-------------------------------------------------------------------
``grid_spacing_for`` returns ``None`` for **every** template today.  That is a
deliberate NEGATIVE, not a stub.  ``tools/authoring/INTERFACE-INVENTORY.md:22``
records the field-vs-semantics gap ("字段调查不等于尺寸/碰撞语义已证"), and the
offline investigation under ``docs/research/reverse-eng-20261010/`` closes each
candidate source:

1. **The editor prefab model carries no bounds/dimension field.**  A deep read of
   194 prefabs (``prefab-fields-page``) reported *every* float/double leaf ==
   ``0.0`` -- ``2310`` of them, with ``readSummary.complete=true`` (not a
   truncation) -- ``docs/research/reverse-eng-20261010/PREFAB-FIELDS-MINE.md``
   §0 and §4.3.  The materialized model type
   (``nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp``) holds key/name/icon/nativeKind/
   components, and no size or box.  The shallow ``prefab-fields`` op stops at
   depth 3 (``tools/editor-bridge/Adapter/PrefabFieldRead.cs:13``) and never even
   reaches the component list.
2. **No prefab asset bounds reader exists in the 7.1 editor.**  The P03 probe
   closed this by name:
   ``.runtime/verification/interface-experiments-20260927/p03/geometry-candidate/
   size-entry.json`` -- "no-confirmed-prefab-asset-bounds-reader-in-local-7.1-editor"
   -- and ``size-entry-lowercase.json`` found no ``UnityEngine``
   Renderer/Collider/Mesh accessor and no resource-id -> Unity-object join.
3. **The three geometry channels give per-INSTANCE transforms, never a template
   size.**  ``docs/research/reverse-eng-20261010/GEOMETRY-THREE-WAYS.md`` §0: the
   offline ``.gil`` reader gives an entity's ``position``/``rotation``/``scale``
   plus the template id (entry field 8); the native probe reads *no* geometry at
   all (``position=null``; ``GE_POSITION_READ`` is never set); the editor-registry
   transform cache is ``authoritative=false`` and reads all-zero.  A shape at
   scale 1 would take a **live** place-and-read-back, which is a write, not an
   offline read.
4. **The one "double x/y pair" that was just decoded is not a world extent.**  The
   component model ``taSWDWiCN5Tmi73usl0j.LudM06iCRNk4iFkwqKIW`` has
   ``xPos``/``yPos`` as ``double`` (``docs/research/reverse-eng-20261010/
   COMPONENT-WRITER-MINE.md`` §7), but they belong to a 2D **editor UI / tree**
   item family -- the same P03 probe classifies that ``get_Bounds`` ->
   ``System.Windows.Rect`` shape as "2D editor tree/UI item rectangle, not prefab
   3D bounds" (``size-entry.json``).  A component's x/y is where the editor draws
   the component, not how big the template is in the world.

The only size numbers that exist anywhere in this repo -- ``1.0`` for the cubes
(``20001875``/``20001224``/``20001876``/``20001877``/``20001878``) and ``5.0`` for
``20001034`` -- are **documented, UNMEASURED design assumptions** from a community
config (``size_units`` in
``.runtime/research-sources/file-formats/UGC-File-Generate-Utils/config/
block_config.py``), and ``mvp/calibration/README.md:24`` says so in plain words
("scene.json 中的 size_units 和坐标/碰撞关系是历史设计假设，**未测量**").  They live
in :data:`RECORDED_SIZE_ASSUMPTIONS` for reference and :func:`describe_unknown`
will name them, but :func:`grid_spacing_for` **does not return them** -- an
unmeasured assumption is exactly the "default like 1.0" this module must never
hand back as if it were a measurement.

Where a real size would have to come from
-----------------------------------------
Because none of the four sources above can supply one, a value could only arrive
by NEW reverse-engineering: a not-yet-found **bounds field** on the editor prefab
model (read through a bridge prefab-field op), a not-yet-found **native/game API**
that exposes asset bounds, or a **live place-at-scale-1 measurement** read back
out of a ``.gil``.  Each of those is a new capability, not a lookup this module
can perform offline, so the honest answer to "how wide is this template?" is
"cannot say" -- and a caller must treat ``None`` as a problem, not as permission
to substitute a number.

Units and axes
--------------
World space, the same one :mod:`tools.gameplan.placement` lays tiles out in: the
ground plane is XZ and +Y is up.  A returned spacing would be the face length of
the template's square footprint in world units, i.e. the ``spacing`` at which a
row of that template tiles edge to edge at ``scale = 1``.
"""

from __future__ import annotations

from typing import Optional

# --------------------------------------------------------------------------- #
# the (empty) table of measured sizes
# --------------------------------------------------------------------------- #

#: Template id -> world-unit edge length, for sizes that have been **measured** on
#: the real machine.  It is **empty today**: the offline investigation above found
#: no field, op or file that yields a template's intrinsic size, so nothing has
#: been measured to put here.  This is the single seam where a future measured
#: size lands -- :func:`grid_spacing_for` reads only this table, so adding an entry
#: is the one deliberate act that would let the function return a number, and it
#: must come with its own citation.  See the module docstring for why it is empty.
MEASURED_TILE_SIZES: dict[int, float] = {}


#: Size values that are **recorded** in the repo but are **assumptions, not
#: measurements** -- the community ``block_config.py`` ``size_units``, carried via
#: ``mvp/scene.json`` templates.  ``{id: (size_units, source)}``.  These are kept
#: *only* so :func:`describe_unknown` can name the specific documented number for a
#: caller; :func:`grid_spacing_for` deliberately ignores this table, because a
#: "历史设计假设，未测量" value (``mvp/calibration/README.md:24``) is not a size.
RECORDED_SIZE_ASSUMPTIONS: dict[int, tuple[float, str]] = {
    20001875: (
        1.0,
        "block_config.py size_units via mvp/scene.json; declared, NOT measured "
        "(mvp/calibration/README.md:24)",
    ),
    20001224: (
        1.0,
        "block_config.py size_units via mvp/scene.json; declared, NOT measured "
        "(mvp/calibration/README.md:24)",
    ),
    20001876: (
        1.0,
        "block_config.py size_units via mvp/scene.json; declared, NOT measured "
        "(mvp/calibration/README.md:24)",
    ),
    20001877: (
        1.0,
        "block_config.py size_units via mvp/scene.json; declared, NOT measured "
        "(mvp/calibration/README.md:24)",
    ),
    20001878: (
        1.0,
        "block_config.py size_units via mvp/scene.json; declared, NOT measured "
        "(mvp/calibration/README.md:24)",
    ),
    20001034: (
        5.0,
        "block_config.py size_units via mvp/scene.json; declared, NOT measured "
        "(mvp/calibration/README.md:24)",
    ),
}


#: The tail of every "no size" reason: NAMES where the size would have to come
#: from.  One string, quoted by tests, so the negative reads the same wherever a
#: caller surfaces it.  It never states a size.
UNKNOWN_SIZE_TAIL = (
    "no template size is obtainable today, so grid_spacing_for returns None and "
    "must not be given a default.  The size would have to come from NEW "
    "reverse-engineering, because each offline source is closed: (1) the editor "
    "prefab model carries no bounds/dimension field -- a deep read of 194 prefabs "
    "returned 0.0 for every one of 2310 float/double leaves "
    "(docs/research/reverse-eng-20261010/PREFAB-FIELDS-MINE.md §0,§4.3); (2) the "
    "7.1 editor exposes no prefab asset bounds reader and no resource-id -> Unity "
    "Renderer/Collider/Mesh mapping "
    "(.runtime/verification/interface-experiments-20260927/p03/geometry-candidate/"
    "size-entry.json, size-entry-lowercase.json); (3) the three geometry channels "
    "(.gil offline / native probe / editor cache) yield only a per-INSTANCE "
    "position/rotation/scale and the template id, never a template's intrinsic "
    "size (docs/research/reverse-eng-20261010/GEOMETRY-THREE-WAYS.md §0); and (4) "
    "the component xPos/yPos double pair is 2D editor UI/tree geometry, not a "
    "world extent (size-entry.json; COMPONENT-WRITER-MINE.md §7).  A real value "
    "could only arrive via a not-yet-found bounds field on the editor prefab "
    "model (read through a bridge prefab-field op), a not-yet-found native/game "
    "API that exposes asset bounds, or a live place-at-scale-1 measurement read "
    "back through .gil.  See tools/authoring/INTERFACE-INVENTORY.md:22 "
    "(asset.measure is MISSING; \"字段调查不等于尺寸/碰撞语义已证\")."
)


def _key(template_id) -> int:
    """Coerce *template_id* to an ``int``; raise :class:`TypeError` otherwise."""
    try:
        return int(template_id)
    except (TypeError, ValueError):
        raise TypeError(f"template_id must be an integer id, got {template_id!r}") from None


# --------------------------------------------------------------------------- #
# the two public entry points
# --------------------------------------------------------------------------- #

def grid_spacing_for(template_id) -> Optional[float]:
    """Edge-to-edge grid spacing in world units for *template_id*, or ``None``.

    Returns the template's square-footprint face length at ``scale = 1`` -- the
    ``spacing`` :func:`tools.gameplan.placement.grid` should use to tile that
    template without gaps -- **when that size has been measured** (i.e. it is in
    :data:`MEASURED_TILE_SIZES`).  That table is empty today, so this returns
    ``None`` for every template: the size is unknown (module docstring), and the
    one honest answer to an unknown size is ``None``.

    ``None`` is a **refusal, not zero and not one**: a caller must treat it as
    "cannot compute a spacing", never as a licence to substitute ``1.0`` or any
    other "looks about right" value.  The recorded-but-unmeasured
    ``size_units`` assumptions (:data:`RECORDED_SIZE_ASSUMPTIONS`) are
    deliberately **not** consulted here -- returning one would be reporting an
    assumption as a measurement.  Use :func:`describe_unknown` to log why.

    Raises :class:`TypeError` if *template_id* is not integer-like.
    """
    return MEASURED_TILE_SIZES.get(_key(template_id))


def describe_unknown(template_id) -> str:
    """Why *template_id*'s size is unknown, and where it would have to come from.

    Always returns a non-empty reason string.  It names every closed offline
    source and the new capability a real value would require (see
    :data:`UNKNOWN_SIZE_TAIL`).  When *template_id* happens to have a recorded
    *assumption* in :data:`RECORDED_SIZE_ASSUMPTIONS`, the reason says so and
    names that number explicitly -- while stating that it is unmeasured and
    therefore **not** what :func:`grid_spacing_for` returns, so a logged reason
    can never be misread as a size.

    Raises :class:`TypeError` if *template_id* is not integer-like.
    """
    key = _key(template_id)
    recorded = RECORDED_SIZE_ASSUMPTIONS.get(key)
    if recorded is None:
        return f"template {key}: size UNKNOWN.  " + UNKNOWN_SIZE_TAIL
    size, source = recorded
    return (
        f"template {key}: size UNKNOWN (grid_spacing_for returns None).  A value "
        f"of {size:g} is RECORDED but is an UNMEASURED design assumption, not a "
        f"measurement -- source: {source} -- so it is not returned.  "
        + UNKNOWN_SIZE_TAIL
    )
