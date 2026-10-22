"""``editor_steps`` -- judge a component READ reply offline: did the human do the step?

Why this module exists
----------------------
Some editor steps will be done **by hand** in the editor.  The component read op
exists precisely because there is no "add component" primitive to call
(``CLAUDE.md`` §六(a): the *delete* direction exists, the *add* direction does
not), so a required interactive step can only be *confirmed* by reading back what
the editor now holds.  This module turns that confirmation into a function: given
the reply we already got, does it contain the component we required, in the state
we required?  It answers that with **zero** bridge contact -- no request is sent,
no native call is made, no file is touched.

The reply shape is the REAL adapter's, not a guess
--------------------------------------------------
The reply this module reads is the one produced by the ``inspect-entity-components``
op -- ``EditorAdapter.EntityComponentProbe`` in
``tools/editor-bridge/Adapter/EntityComponentProbe.cs``.  That method returns, at
``EntityComponentProbe.cs:158-173``::

    { ok, status:"entity-components-editor-model-read-only", entityId, entityName,
      componentType, componentCount, components:[{id, enabled, x, y}, ...],
      componentIdSpace, nativeMutationInvoked, localModelWritten, sentToGame,
      gameEffectVerified, persistentSaveVerified }

and each row is built at ``EntityComponentProbe.cs:150-156`` as ``id:(uint)``,
``enabled:(bool)``, ``x:(double)``, ``y:(double)``.  This module mirrors exactly
those fields: ``ok`` must be literally ``True``; ``entityId`` a positive int;
``componentCount`` an int equal to ``len(components)``; every row an object whose
``id`` is a non-negative int, ``enabled`` a bool, ``x``/``y`` numbers.

A broken reply is REFUSED by name -- never read as "absent"
-----------------------------------------------------------
The whole point of the module is this distinction.  "The component is not in the
reply" and "the reply could not be read as the probe's output" are *different
facts with different remedies*: the first means the human step is missing, the
second means we do not know and must re-read.  So a reply whose shape does not
match -- or a non-positive/error reply (``ok`` not ``True``) -- yields
:data:`Status.REFUSED` carrying a named code, and **never** :data:`Status.ABSENT`.
``describe`` prints the code, so a refusal can never be mistaken for a clean
negative.

The component-id -> meaning mapping is UNPROVEN, so absence is not asserted
--------------------------------------------------------------------------
The probe labels its own id space ``"editor-enum-value-or-native-index-UNVERIFIED"``
(``EntityComponentProbe.cs:167``).  ``docs/research/reverse-eng-20261010/
COLLISION-COMPONENT-ID.md`` reads the front-end corpus and **argues** (§2,
``:94-160``) that a row's ``id`` **is** the component-*kind* enum value
(``jaUof90C3Ncl5BAJri4x``) carried as a uint -- an assignment-direction proof, not
merely a shape that looks like an enum.  So the *shape* is defensible: an id in a
row is a kind, not an instance index.

But the same file is explicit that **which** id means **which** human component is
**not** established:

* the id-to-*name* binding table is **not in this repo** (§3.2, ``:174-181``);
* "collision trigger == 8" is labelled an explicit **HYPOTHESIS** pending a device
  read (§3.1, ``:166-172``; falsification criteria §3.3), resting on a name/semantic
  inference whose only soft spot is exactly the missing table;
* the actual<->legacy symbol mapping the probe relies on cannot be re-checked
  offline (§1.3, ``:76-90``; §2.3, ``:146``); and
* the cross-layer claim (front-end enum value == native ``componentId``) is
  unverified (§2.5, ``:155-160``).

Verdict therefore: the id **is** the enum value (static, §2), but the **id-to-meaning
mapping is UNPROVEN** (§3).  This module encodes that honestly: it never claims any
id means anything, and -- new here -- it refuses to let an *unproven* id produce a
clean negative.  A check whose mapping is not ``meaning_proven`` returns
:data:`Status.INDETERMINATE` (carrying the reason) when the required row is missing,
**never** :data:`Status.ABSENT`: "no row with id 8" is not evidence that the
collision trigger is absent, because 8 is only a hypothesis for it.  Pass
``meaning_proven=True`` only when the caller holds device evidence (e.g. the §3.3
read-back) binding the id to the meaning it asked about.

The three checkers
------------------
:func:`check_component_by_id` (the exact id), :func:`check_any_of` (a candidate id
set), and :func:`check_component_by_predicate` (a caller-supplied predicate over
rows) each return a :class:`Verdict` that distinguishes ``PRESENT`` / ``ABSENT`` /
``INDETERMINATE`` (plus ``PRESENT_DISABLED`` / ``REFUSED``).  A **positive** sighting
of the required id is determinate regardless of the mapping -- the id is literally in
the reply.  A **negative** is determinate only when ``meaning_proven``; otherwise it
degrades to ``INDETERMINATE`` with a named reason.

No writes.  No bridge.  Pure function over a parsed reply dict.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from enum import Enum


#: Why an absent row is not read as an absence of the *meaning* the caller asked
#: about: "collision trigger == 8" is a hypothesis, not a repo fact
#: (``COLLISION-COMPONENT-ID.md`` §3.1/§3.2).  Carried on every INDETERMINATE that
#: came from an id-based check.
ID_MEANING_UNPROVEN = "id-to-meaning unproven"
#: The same for a caller-supplied predicate: a predicate that matches no row is only
#: evidence of absence if the predicate is the right discriminator, which this module
#: cannot establish.
PREDICATE_MEANING_UNPROVEN = "predicate-to-meaning unproven"


class Status(str, Enum):
    """The five, and only five, answers this module gives.

    ``str`` + ``Enum`` so a caller may compare against the literal (``"present"``)
    while tests still address the member.
    """

    #: A row with a required id (or matching the required predicate) is present, in
    #: the required enabled state.
    PRESENT = "present"
    #: Well-formed reply, no row carries any required id -- **and** the id-to-meaning
    #: mapping is proven, so a negative really is a negative.  Under the default
    #: (unproven) mapping this is never returned by the id/predicate checkers; they
    #: return :data:`INDETERMINATE` instead.
    ABSENT = "absent"
    #: A row with a required id is present, but its ``enabled`` disagrees with the
    #: requirement (the "present-but-disabled" case).  Distinct from ABSENT because
    #: the remedy differs: the component exists, it is just switched off.
    PRESENT_DISABLED = "present-disabled"
    #: The reply could not be read as a positive probe reply -- malformed shape, or
    #: ``ok`` not ``True``.  A refusal, NEVER a claim of absence.
    REFUSED = "refused"
    #: The reply is readable but the required row is missing and the mapping that
    #: would turn "missing" into "absent" is not proven (:attr:`Verdict
    #: .indeterminate_reason` names why).  Never a clean negative; the caller must
    #: re-read or establish the id-to-meaning binding.
    INDETERMINATE = "indeterminate"


class _Refused(Exception):
    """Internal: carries the named refusal code for a reply that cannot be read."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Verdict:
    """The answer for one reply, plus the fields :func:`describe` needs.

    Everything is read from the reply (or the request); the verdict never invents
    a component meaning.  ``required_ids`` is the set the caller asked about (one
    id for :func:`check_component`, a candidate set for :func:`check_any_of`; empty
    for a predicate check, where ``requirement_label`` describes the requirement).
    On :data:`Status.REFUSED`, ``refusal`` names the code and every read-out field
    is ``None``/empty -- the reply told us nothing trustworthy.  On
    :data:`Status.INDETERMINATE`, ``indeterminate_reason`` names why a missing row
    could not be read as an absence.
    """

    status: Status
    #: The ids the caller required (a 1-tuple, or the any-of candidate set).
    required_ids: tuple[int, ...]
    #: Echoed from the reply; ``None`` when the reply did not carry a usable one.
    entity_id: int | None
    entity_name: str | None
    #: ``len(components)`` of a well-formed reply; ``None`` on a refusal.
    component_count: int | None
    #: Every id the reply's rows carried, in row order (for naming what *was* there).
    present_ids: tuple[int, ...]
    #: The id (among ``required_ids``) that decided the verdict, else ``None``.
    matched_id: int | None
    #: The ``enabled`` of the deciding row, else ``None``.
    matched_enabled: bool | None
    #: What the caller required of ``enabled`` (``None`` == presence only).
    required_enabled: bool | None
    #: The named refusal code, on :data:`Status.REFUSED` only.
    refusal: str | None = None
    #: The reply's ``componentIdSpace`` verbatim, so the caller sees the UNVERIFIED
    #: label the probe itself stamped.
    id_space: str | None = None
    #: Why a missing row was not read as an absence, on :data:`Status.INDETERMINATE`
    #: only (e.g. :data:`ID_MEANING_UNPROVEN`).
    indeterminate_reason: str | None = None
    #: A human label for what was required, when ``required_ids`` cannot express it
    #: (the predicate check).  ``None`` -> :func:`describe` derives it from ids.
    requirement_label: str | None = None

    @property
    def satisfied(self) -> bool:
        """True iff the required step is present in the required state."""
        return self.status is Status.PRESENT

    @property
    def is_refusal(self) -> bool:
        """True iff the reply could not be judged (a broken reply, not an absence)."""
        return self.status is Status.REFUSED

    @property
    def is_indeterminate(self) -> bool:
        """True iff the reply was readable but the mapping makes a negative unprovable."""
        return self.status is Status.INDETERMINATE


# --------------------------------------------------------------------------- #
# shape readers -- every failure raises _Refused with a named code
# --------------------------------------------------------------------------- #

def _is_int(value: object) -> bool:
    """A JSON integer -- ``bool`` is excluded (``isinstance(True, int)`` is True)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    """A JSON number, int or float, bool excluded."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _entity_hint(reply: object) -> tuple[int | None, str | None, str | None]:
    """Best-effort ``(entityId, entityName, componentIdSpace)`` for a refusal message.

    Runs *before* strict validation so :func:`describe` can still name the entity
    on a reply that is otherwise unreadable.  Never raises.
    """
    if not isinstance(reply, Mapping):
        return (None, None, None)
    entity_id = reply.get("entityId")
    name = reply.get("entityName")
    space = reply.get("componentIdSpace")
    return (
        entity_id if _is_int(entity_id) else None,
        name if isinstance(name, str) else None,
        space if isinstance(space, str) else None,
    )


@dataclass(frozen=True)
class _Row:
    """One validated component row: what the module reads, plus the raw row for a
    caller-supplied predicate to inspect."""

    id: int
    enabled: bool
    #: The row exactly as the reply carried it (a Mapping), so a predicate can read
    #: any field -- the module invents nothing.
    raw: Mapping


@dataclass(frozen=True)
class _Parsed:
    entity_id: int
    entity_name: str | None
    rows: tuple[_Row, ...]
    id_space: str | None


def _parse(reply: object) -> _Parsed:
    """Validate ``reply`` against the probe's exact shape, or raise :class:`_Refused`."""
    if not isinstance(reply, Mapping):
        raise _Refused("REPLY_NOT_AN_OBJECT")
    # ``EntityComponentProbe.cs:159`` sets ``ok = true``; a ``false``/absent ``ok``
    # is the bridge's error envelope, not a component read -- refuse, do not guess.
    if reply.get("ok") is not True:
        raise _Refused("REPLY_OK_NOT_TRUE")
    entity_id = reply.get("entityId")
    if not _is_int(entity_id) or entity_id <= 0:
        # ``EntityComponentProbe.cs:57`` requires a nonzero uint; a bad echo means
        # we cannot even say which entity the rows belong to.
        raise _Refused("REPLY_ENTITY_ID_INVALID")
    if "components" not in reply:
        raise _Refused("REPLY_COMPONENTS_MISSING")
    raw = reply["components"]
    if not isinstance(raw, list):
        raise _Refused("REPLY_COMPONENTS_NOT_A_LIST")

    rows: list[_Row] = []
    for index, row in enumerate(raw):
        if not isinstance(row, Mapping):
            raise _Refused(f"REPLY_ROW_NOT_AN_OBJECT:{index}")
        row_id = row.get("id")
        if not _is_int(row_id) or row_id < 0:
            # uint at ``EntityComponentProbe.cs:152`` -- a string/bool/negative id
            # is not a component id.
            raise _Refused(f"REPLY_ROW_ID_INVALID:{index}")
        enabled = row.get("enabled")
        if not isinstance(enabled, bool):
            raise _Refused(f"REPLY_ROW_ENABLED_INVALID:{index}")
        if not _is_number(row.get("x")):
            raise _Refused(f"REPLY_ROW_X_INVALID:{index}")
        if not _is_number(row.get("y")):
            raise _Refused(f"REPLY_ROW_Y_INVALID:{index}")
        rows.append(_Row(id=row_id, enabled=enabled, raw=row))

    # ``componentCount`` is set to ``rows.Count`` at ``EntityComponentProbe.cs:165``;
    # a reply whose count disagrees with its rows is internally inconsistent.
    count = reply.get("componentCount")
    if not _is_int(count) or count != len(rows):
        raise _Refused("REPLY_COMPONENT_COUNT_INVALID")

    name = reply.get("entityName")
    space = reply.get("componentIdSpace")
    return _Parsed(
        entity_id=entity_id,
        entity_name=name if isinstance(name, str) else None,
        rows=tuple(rows),
        id_space=space if isinstance(space, str) else None,
    )


# --------------------------------------------------------------------------- #
# the check
# --------------------------------------------------------------------------- #

def _refused_verdict(
    reply: object,
    required_ids: tuple[int, ...],
    required_enabled: bool | None,
    code: str,
    *,
    requirement_label: str | None = None,
) -> Verdict:
    """Build a :data:`Status.REFUSED` verdict, keeping whatever the reply still lets
    :func:`describe` name (best-effort entity/space hint)."""
    hint_id, hint_name, hint_space = _entity_hint(reply)
    return Verdict(
        status=Status.REFUSED,
        required_ids=required_ids,
        entity_id=hint_id,
        entity_name=hint_name,
        component_count=None,
        present_ids=(),
        matched_id=None,
        matched_enabled=None,
        required_enabled=required_enabled,
        refusal=code,
        id_space=hint_space,
        requirement_label=requirement_label,
    )


def _apply_uncertainty(verdict: Verdict, *, proven: bool, reason: str) -> Verdict:
    """Downgrade a clean :data:`Status.ABSENT` to :data:`Status.INDETERMINATE`.

    Only ABSENT degrades: a **positive** sighting (PRESENT / PRESENT_DISABLED) needs
    no mapping -- the row is literally in the reply -- and REFUSED is not an absence
    at all.  With ``proven`` the absence stands.
    """
    if verdict.status is Status.ABSENT and not proven:
        return replace(verdict, status=Status.INDETERMINATE, indeterminate_reason=reason)
    return verdict


def _judge(reply: object, required_ids: tuple[int, ...], required_enabled: bool | None) -> Verdict:
    try:
        parsed = _parse(reply)
    except _Refused as refused:
        return _refused_verdict(reply, required_ids, required_enabled, refused.code)

    present_ids = tuple(row.id for row in parsed.rows)
    wanted = set(required_ids)
    matches = [(row.id, row.enabled) for row in parsed.rows if row.id in wanted]

    matched_id: int | None = None
    matched_enabled: bool | None = None
    if not matches:
        status = Status.ABSENT
    elif required_enabled is None:
        # Presence only: any row with a required id satisfies the step.
        status = Status.PRESENT
        matched_id, matched_enabled = matches[0]
    else:
        hit = next((m for m in matches if m[1] == required_enabled), None)
        if hit is not None:
            status = Status.PRESENT
            matched_id, matched_enabled = hit
        else:
            status = Status.PRESENT_DISABLED
            matched_id, matched_enabled = matches[0]

    return Verdict(
        status=status,
        required_ids=required_ids,
        entity_id=parsed.entity_id,
        entity_name=parsed.entity_name,
        component_count=len(parsed.rows),
        present_ids=present_ids,
        matched_id=matched_id,
        matched_enabled=matched_enabled,
        required_enabled=required_enabled,
        refusal=None,
        id_space=parsed.id_space,
    )


def _judge_predicate(
    reply: object,
    predicate: Callable[[Mapping], object],
    label: str,
) -> Verdict:
    """Judge a reply against a caller-supplied predicate over rows.

    Positive: the first row for which ``predicate(row)`` is truthy decides the
    verdict (PRESENT; ``enabled`` is not part of this check, so no disabled case).
    Negative: ABSENT -- the caller downgrades to INDETERMINATE upstream when the
    predicate-to-meaning link is unproven.  A predicate that *raises* on a row is a
    caller error, refused by name (never read as absence).  A malformed reply refuses
    exactly as :func:`_judge` does.
    """
    try:
        parsed = _parse(reply)
    except _Refused as refused:
        return _refused_verdict(reply, (), None, refused.code, requirement_label=label)

    matched_row: _Row | None = None
    for index, row in enumerate(parsed.rows):
        try:
            hit = predicate(row.raw)
        except Exception:  # noqa: BLE001 -- caller predicate contract; refuse, don't guess
            return _refused_verdict(
                reply, (), None, f"REPLY_PREDICATE_RAISED:{index}", requirement_label=label
            )
        if hit:
            matched_row = row
            break

    return Verdict(
        status=Status.PRESENT if matched_row is not None else Status.ABSENT,
        required_ids=(),
        entity_id=parsed.entity_id,
        entity_name=parsed.entity_name,
        component_count=len(parsed.rows),
        present_ids=tuple(r.id for r in parsed.rows),
        matched_id=matched_row.id if matched_row is not None else None,
        matched_enabled=matched_row.enabled if matched_row is not None else None,
        required_enabled=None,
        refusal=None,
        id_space=parsed.id_space,
        requirement_label=label,
    )


def _require_int_ids(ids: Iterable[int], *, what: str) -> tuple[int, ...]:
    out = tuple(ids)
    if not out:
        raise ValueError(f"{what}: at least one component id is required")
    for candidate in out:
        if not _is_int(candidate) or candidate < 0:
            raise ValueError(f"{what}: component id must be a non-negative int, got {candidate!r}")
    return out


def check_component(
    reply: object,
    *,
    required_id: int,
    required_enabled: bool | None = None,
) -> Verdict:
    """Did the read ``reply`` contain component ``required_id`` in the required state?

    The **determinate** raw-id check: it assumes the caller's ``required_id`` is
    authoritative (i.e. the id-to-meaning mapping is proven for this caller), so a
    missing row is reported as :data:`Status.ABSENT`.  Equivalent to
    ``check_component_by_id(reply, required_id=..., meaning_proven=True)``; prefer
    :func:`check_component_by_id` when the mapping is *not* proven -- there an absent
    row degrades to :data:`Status.INDETERMINATE` rather than pretending.

    ``reply`` is a parsed ``inspect-entity-components`` reply (the object the op
    returns, e.g. ``json.loads`` of the response JSON); its shape is the real
    adapter's, cited at the module docstring (``EntityComponentProbe.cs:150-156,
    158-173``).  ``required_id`` is supplied by the caller -- this module assigns
    it no meaning (see the docstring: the id-to-meaning mapping is UNPROVEN).
    ``required_enabled``: ``None`` (default) checks presence only; ``True``/``False``
    additionally requires the matched row's ``enabled`` to equal it, yielding
    :data:`Status.PRESENT_DISABLED` on a mismatch.

    A reply that does not match the probe's shape -- or whose ``ok`` is not
    ``True`` -- returns :data:`Status.REFUSED` with a named code; it is **never**
    reported as :data:`Status.ABSENT`.
    """
    ids = _require_int_ids((required_id,), what="check_component")
    return _judge(reply, ids, required_enabled)


def check_component_by_id(
    reply: object,
    *,
    required_id: int,
    required_enabled: bool | None = None,
    meaning_proven: bool = False,
) -> Verdict:
    """Presence check for ``required_id`` that **does not pretend** the id means it.

    Because the id-to-meaning mapping is UNPROVEN (module docstring:
    ``COLLISION-COMPONENT-ID.md`` §3), a missing row is only a real absence if the
    caller has established that this id *is* the component it asked about:

    * a row with ``required_id`` is in the reply -> :data:`Status.PRESENT` (or
      :data:`Status.PRESENT_DISABLED` when ``required_enabled`` disagrees) -- a
      positive sighting needs no mapping;
    * no such row and ``meaning_proven=False`` (default) -> :data:`Status
      .INDETERMINATE`, carrying :data:`ID_MEANING_UNPROVEN` -- "no row with id 8" is
      not evidence the collision trigger is absent, because 8 is a hypothesis;
    * no such row and ``meaning_proven=True`` -> :data:`Status.ABSENT`;
    * an unreadable reply -> :data:`Status.REFUSED` (never ABSENT / INDETERMINATE).

    Pass ``meaning_proven=True`` only with device evidence binding the id to the
    meaning (e.g. the read-back criterion at ``COLLISION-COMPONENT-ID.md`` §3.3).
    """
    ids = _require_int_ids((required_id,), what="check_component_by_id")
    return _apply_uncertainty(
        _judge(reply, ids, required_enabled),
        proven=meaning_proven,
        reason=ID_MEANING_UNPROVEN,
    )


def check_any_of(
    reply: object,
    required_ids: Iterable[int],
    *,
    meaning_proven: bool = False,
) -> Verdict:
    """Presence check for **any** of ``required_ids`` -- for when the exact id is uncertain.

    Same reply handling and refusals as :func:`check_component_by_id`.  The step
    counts as present if a row carries *any* candidate id; the verdict's
    ``matched_id`` names which one did.  ``required_ids`` is an iterable of candidate
    ids (at least one); ``enabled`` is not part of this check, so a matched row is
    present regardless of its enabled state.

    The candidate set is itself an admission of uncertainty, so a **negative** is
    never a clean absence unless ``meaning_proven=True``: with the default
    (``False``) a no-match returns :data:`Status.INDETERMINATE` carrying
    :data:`ID_MEANING_UNPROVEN` -- the true id may simply lie *outside* the set.
    """
    ids = _require_int_ids(required_ids, what="check_any_of")
    return _apply_uncertainty(
        _judge(reply, ids, None),
        proven=meaning_proven,
        reason=ID_MEANING_UNPROVEN,
    )


def check_component_by_predicate(
    reply: object,
    predicate: Callable[[Mapping], object],
    *,
    label: str = "a row matching the caller predicate",
    meaning_proven: bool = False,
) -> Verdict:
    """Presence check driven by a caller-supplied ``predicate`` over the reply's rows.

    For when the caller can *decide* a row on sight (any field it likes -- e.g.
    ``lambda r: r["id"] in {5, 8}``) but cannot name a single authoritative id.
    ``predicate`` receives each row exactly as the reply carried it (a Mapping) and
    is truthy/falsey.  The first matching row decides the verdict (:data:`Status
    .PRESENT`, with ``matched_id`` / ``matched_enabled`` naming it); ``enabled`` is
    not part of this check.

    A predicate that returns falsey for every row yields :data:`Status.INDETERMINATE`
    (carrying :data:`PREDICATE_MEANING_UNPROVEN`) unless ``meaning_proven=True``, in
    which case it is :data:`Status.ABSENT`: this module cannot prove the predicate is
    the right discriminator, only that no row satisfied it.  A predicate that
    *raises* is a caller error and refuses by name
    (``REPLY_PREDICATE_RAISED:<index>``); a malformed reply refuses as elsewhere.  A
    non-callable ``predicate`` raises :class:`ValueError`.
    """
    if not callable(predicate):
        raise ValueError("check_component_by_predicate: predicate must be callable")
    return _apply_uncertainty(
        _judge_predicate(reply, predicate, label),
        proven=meaning_proven,
        reason=PREDICATE_MEANING_UNPROVEN,
    )


# --------------------------------------------------------------------------- #
# describing the verdict in words
# --------------------------------------------------------------------------- #

def _who(verdict: Verdict) -> str:
    if verdict.entity_id is None:
        return "entity <unknown>"
    if verdict.entity_name:
        return f'entity {verdict.entity_id} "{verdict.entity_name}"'
    return f"entity {verdict.entity_id}"


def _wanted(verdict: Verdict) -> str:
    if verdict.requirement_label:
        return verdict.requirement_label
    ids = verdict.required_ids
    if len(ids) == 1:
        return f"component {ids[0]}"
    if not ids:
        return "the required component"
    return "one of {" + ", ".join(str(i) for i in ids) + "}"


def describe(verdict: Verdict) -> str:
    """A one-line, human-readable statement naming what is missing and on which entity.

    Never raises; every :class:`Status` has a line.  For a refusal the line states
    the named code and that a broken reply is not proof of absence -- so a refusal
    can never be read as a clean negative.  For an indeterminate verdict the line
    states the reason and that an unproven mapping is likewise not proof of absence
    -- so it can never be read as a clean negative either.
    """
    who = _who(verdict)

    if verdict.status is Status.REFUSED:
        return (
            f"{who}: cannot judge -- reply REFUSED as {verdict.refusal}; "
            f"a broken reply is not evidence of absence"
        )

    wanted = _wanted(verdict)

    if verdict.status is Status.PRESENT:
        return (
            f"{who}: {wanted} present "
            f"(id={verdict.matched_id}, enabled={verdict.matched_enabled})"
        )

    if verdict.status is Status.PRESENT_DISABLED:
        return (
            f"{who}: {wanted} present but DISABLED "
            f"(id={verdict.matched_id}, enabled={verdict.matched_enabled}, "
            f"required enabled={verdict.required_enabled})"
        )

    have = ", ".join(str(i) for i in verdict.present_ids) or "none"

    if verdict.status is Status.INDETERMINATE:
        return (
            f"{who}: {wanted} INDETERMINATE -- {verdict.indeterminate_reason}; "
            f"not evidence of absence "
            f"(rows read: {verdict.component_count}, ids present: {have})"
        )

    return (
        f"{who}: {wanted} MISSING "
        f"(rows read: {verdict.component_count}, ids present: {have})"
    )
