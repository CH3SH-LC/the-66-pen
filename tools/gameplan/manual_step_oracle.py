"""``manual_step_oracle`` -- turn a component READ reply into a MANUAL-STEP oracle.

The question this module answers
--------------------------------
The project can *delete* a component (``DeleteComponentForEditObj``) but has **no
command to add one** (``CLAUDE.md`` §六(a); ``ADD-COMPONENT-TRACE.md`` §0/§3/§5: the
two builds' ``*Component*`` commands are both deletes).  So a component that exists on
an entity is, by construction, something **the project could not have put there
itself** -- it is evidence of a step a *human* took in the editor UI.  The read-only
``inspect-entity-components`` op (``EditorAdapter.EntityComponentProbe`` in
``tools/editor-bridge/Adapter/EntityComponentProbe.cs``) is the only way to see it.

Given that op's reply, this oracle returns exactly one of three answers:

* :data:`PRESENT`       -- the entity-local component set is non-empty, so a human
  configured at least one component this project has no command to create;
* :data:`ABSENT`        -- the reply is well-formed and the entity-local set is empty:
  no human-added component **here** (see the two caveats below);
* :data:`INDETERMINATE` -- the reply was a refusal or a malformed/broken reply: we do
  not know, and a broken reply is **never** read as :data:`ABSENT`.

The reply shape is the REAL adapter's, not a guess
--------------------------------------------------
``EntityComponentProbe.cs:158-173`` returns::

    { ok, status:"entity-components-editor-model-read-only", entityId, entityName,
      componentType, componentCount, components:[{id, enabled, x, y}, ...],
      componentIdSpace, nativeMutationInvoked, localModelWritten, sentToGame,
      gameEffectVerified, persistentSaveVerified }

The bridge's refusal envelope (``{"ok": false, "error": "<CODE>"}``) and a reply that
merely fails the shape check are both :data:`INDETERMINATE`.  Shape validation is not
re-implemented here -- it is delegated to :mod:`tools.gameplan.editor_steps` (its
:func:`~tools.gameplan.editor_steps.check_component_by_predicate`), so the reply-shape
contract lives in exactly ONE place; this module adds only the three-way judgment and
the refusal-code capture.

A refusal is not a negative
---------------------------
A refusal, a malformed reply, a missing ``components`` list, or a ``componentCount``
that disagrees with the list all mean **we could not read the answer** -- they carry a
named ``code`` and return :data:`INDETERMINATE`, never :data:`ABSENT`.  This is the
same discipline as :mod:`tools.gameplan.component_sweep` and
:mod:`tools.gameplan.editor_steps`: "empty" and "unreadable" are different facts with
different remedies, and a broken read must not masquerade as "the human did nothing".

A template-carried baseline component is INVISIBLE to this oracle
-----------------------------------------------------------------
This is the sharpest limit, and it is why :data:`ABSENT` is *not* evidence that no
human step happened.  ``EntityComponentProbe`` reads ONE collection: the component
list held on the **entity instance itself** (7.1 field ``EDuXiXtiyvl``,
``EntityComponentProbe.cs:24-26,82-83,137-146``).  But the editor shows a component
panel built from that set **union the entity's prefab's set**
(``docs/research/reverse-eng-20261010/ZERO-COMPONENTS.md`` §3.2, §4): for a
"component-instance" entity the components default to its **prefab (template)**, and
this probe is blind to them.  So a component carried by the entity's template is
**invisible** here -- it can never make this oracle say :data:`PRESENT`, and its
absence from the read never makes :data:`ABSENT` a proof that no component exists.
For an entity whose components live on the template, the read is ``componentCount:0``
**regardless** of what a human configured (`ZERO-COMPONENTS.md` §4).

What :data:`ABSENT` does and does not prove
-------------------------------------------
``ZERO-COMPONENTS.md`` §2 proves the entity-local collection is a naive, eagerly
``new``-ed ``List`` with no lazy-fill path (``…WupssAXLwY5NGCQQMQWk_1.cs:68``; the
accessor ``DNLXOkiAvDI`` just ``return P_0``), so a ``componentCount:0`` is a faithful
"this entity instance holds zero local components", not "not filled yet".  Still,
:data:`ABSENT` says only **"no human-added component on THIS entity's local set"** --
it does not say the entity has no components (template-carried ones are invisible) and
it does not say a human did nothing elsewhere.  :data:`PRESENT`, by contrast, is a
positive sighting and needs no such caveat.

No writes.  No bridge.  No native call.  Pure function over a parsed reply.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from . import editor_steps
from .editor_steps import Status

# --------------------------------------------------------------------------- #
# the three outcomes -- distinct by name, and the only answers this module gives
# --------------------------------------------------------------------------- #

#: A well-formed reply whose entity-local component set is non-empty: a human
#: configured something this project has no command to add.
PRESENT = "PRESENT"
#: A well-formed reply whose entity-local component set is empty: no human-added
#: component on THIS entity's local set (template-carried components are invisible).
ABSENT = "ABSENT"
#: The reply could not be read (a refusal or a malformed reply): the manual step is
#: neither confirmed nor denied.  Carries a named ``code``.
INDETERMINATE = "INDETERMINATE"

#: Every outcome, in the order the module documents them.
OUTCOMES = (PRESENT, ABSENT, INDETERMINATE)


@dataclass(frozen=True)
class ComponentReadVerdict:
    """The oracle's answer for one component read reply.

    ``outcome`` is one of :data:`PRESENT` / :data:`ABSENT` / :data:`INDETERMINATE`.
    ``reason`` is always a non-empty human sentence.  ``code`` is a named machine
    string on :data:`INDETERMINATE` only (the bridge's ``error`` code, or the
    shape-refusal code from :mod:`~tools.gameplan.editor_steps`) and ``None`` on the
    two determinate outcomes.  ``entity_id`` / ``component_count`` / ``present_ids``
    are echoed for the caller's convenience; ``component_count`` and ``present_ids``
    are meaningful only on a well-formed reply.
    """

    outcome: str
    reason: str
    code: "str | None"
    entity_id: "int | None"
    component_count: "int | None"
    present_ids: "tuple[int, ...]"

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError("unknown outcome: " + repr(self.outcome))
        if not self.reason:
            raise ValueError("a verdict requires a non-empty reason")
        if self.outcome == INDETERMINATE:
            if not self.code:
                # A refusal or malformed reply must name WHY it could not be read.
                raise ValueError("an INDETERMINATE verdict requires a named code")
        elif self.code is not None:
            # A determinate answer is not a refusal; carrying a code would let a
            # caller mistake it for one.
            raise ValueError("only an INDETERMINATE verdict carries a code")

    @property
    def present(self) -> bool:
        """True iff a human-added, entity-local component was sighted."""
        return self.outcome == PRESENT

    @property
    def absent(self) -> bool:
        """True iff the reply was well-formed and the entity-local set was empty."""
        return self.outcome == ABSENT

    @property
    def indeterminate(self) -> bool:
        """True iff the reply could not be read (a refusal or a malformed reply)."""
        return self.outcome == INDETERMINATE

    def as_document(self) -> dict:
        """A JSON-serializable form of the verdict."""
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "code": self.code,
            "entityId": self.entity_id,
            "componentCount": self.component_count,
            "presentIds": list(self.present_ids),
        }


# --------------------------------------------------------------------------- #
# reading the reply
# --------------------------------------------------------------------------- #

def _entity_hint(reply: Mapping) -> "int | None":
    """The reply's ``entityId`` if it is a positive int, else ``None``.  Never raises."""
    value = reply.get("entityId")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _extract_object(text: str):
    """The first JSON object in ``text``, tolerating leading log noise.  ``None`` if none."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except ValueError:
        return None
    return value if isinstance(value, Mapping) else None


def _indeterminate(reply: object, code: str, reason: str) -> ComponentReadVerdict:
    hint = _entity_hint(reply) if isinstance(reply, Mapping) else None
    return ComponentReadVerdict(
        outcome=INDETERMINATE,
        reason=reason,
        code=code,
        entity_id=hint,
        component_count=None,
        present_ids=(),
    )


def judge_component_read(reply: object) -> ComponentReadVerdict:
    """Judge one ``inspect-entity-components`` reply as a manual-step oracle.

    ``reply`` may be the parsed reply (a mapping) or the raw reply text (a JSON object,
    possibly surrounded by log noise).  Returns a :class:`ComponentReadVerdict`:

    * a well-formed reply with one or more components -> :data:`PRESENT`;
    * a well-formed reply with zero components -> :data:`ABSENT`;
    * the bridge refusal envelope ``{"ok": false, "error": "<CODE>"}`` ->
      :data:`INDETERMINATE` with ``code == "<CODE>"``;
    * any reply that does not match the probe's shape, or that is not a JSON object ->
      :data:`INDETERMINATE` with a named shape code.

    A refusal or a malformed reply is **never** :data:`ABSENT`.  Shape validation is
    delegated to :func:`tools.gameplan.editor_steps.check_component_by_predicate`
    (any row matches), so the reply contract is not duplicated here.
    """
    if isinstance(reply, str):
        extracted = _extract_object(reply)
        if extracted is None:
            return _indeterminate(
                None, "REPLY_NOT_JSON",
                "reply text carried no JSON object; cannot read the component set",
            )
        reply = extracted

    if not isinstance(reply, Mapping):
        return _indeterminate(
            None, "REPLY_NOT_AN_OBJECT",
            "reply is not a JSON object; cannot read the component set",
        )

    # The bridge's error envelope.  Handle it BEFORE delegating so the actual bridge
    # error code survives into the verdict (editor_steps reports only its own
    # "ok not true" code, which would lose why the bridge refused).
    if reply.get("ok") is False:
        raw_code = reply.get("error")
        code = str(raw_code) if raw_code else "UNNAMED"
        return _indeterminate(
            reply, code,
            f"REFUSED:{code}; a refusal is not evidence of absence",
        )

    # A well-formed reply: delegate the shape check and the emptiness decision.
    verdict = editor_steps.check_component_by_predicate(
        reply, lambda _row: True, meaning_proven=True
    )

    if verdict.status is Status.PRESENT:
        return ComponentReadVerdict(
            outcome=PRESENT,
            reason=(
                f"componentCount={verdict.component_count}: entity-local component set "
                f"is non-empty (the project has no add-component command; a human "
                f"configured this)"
            ),
            code=None,
            entity_id=verdict.entity_id,
            component_count=verdict.component_count,
            present_ids=verdict.present_ids,
        )

    if verdict.status is Status.ABSENT:
        return ComponentReadVerdict(
            outcome=ABSENT,
            reason=(
                "componentCount=0: entity-local component set is empty (no human-added "
                "component HERE; template-carried components are invisible to this read)"
            ),
            code=None,
            entity_id=verdict.entity_id,
            component_count=verdict.component_count,
            present_ids=(),
        )

    # Status.REFUSED (malformed shape) -- or, in principle, INDETERMINATE; both mean
    # the reply could not be read, which is never an absence.
    code = verdict.refusal or verdict.indeterminate_reason or "UNREADABLE_REPLY"
    return _indeterminate(
        reply, code,
        f"MALFORMED:{code}; the reply could not be read as a component set, so the "
        f"manual step is neither confirmed nor denied",
    )


__all__ = [
    "ABSENT",
    "ComponentReadVerdict",
    "INDETERMINATE",
    "OUTCOMES",
    "PRESENT",
    "judge_component_read",
]
