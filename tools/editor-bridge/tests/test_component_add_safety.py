#!/usr/bin/env python3
"""Pin the ADD safety gate in front of ``add-entity-component``.

WHY THIS FILE EXISTS

``EntityComponentAdd.EntityComponentAdd`` is a MUTATION of the editor: it appends a component
row to ONE entity's live component collection (the same collection the editor's own loader
fills at ``Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587``). Doctrine sec.6(a): the
*add* half of the component op has no native command, so this op writes the editor's LOCAL
model instead -- and an over-broad gate would let a request write a component onto a USER's
entity, not just onto the self-owned CRUD probe.

The property that makes it safe is asymmetric and load-bearing: the ONLY entity this op
will ever touch is the single entity that (1) did not exist at the CRUD-probe baseline,
(2) is exactly one such entity, (3) is the probe's registered target, matching it by key
AND by model reference, (4) has native type 1402 / instance kind 0, (5) carries no graph
bindings, and (6) is named as the probe recorded it -- inside a live, 180-second,
un-expired probe whose baseline entities are all still present and identical -- AND (7) the
op's own spend bit ``AddSpent`` is still false.

THE PREDICATE CHAIN (exact, this checkout)

``ComponentAddOwnedTarget`` -- tools/editor-bridge/Adapter/EntityComponentAdd.cs
  ``var current = CheckCrudTarget();`` then the five-clause guard, throwing
  ``COMPONENT_ADD_OWNED_UNBOUND_TARGET_REQUIRED`` (clause 1 is ``current.Probe.AddSpent``).

``CheckCrudTarget`` / ``CheckCrudBaseline`` -- tools/editor-bridge/Adapter/EntityCrudProbe.cs
  :102 / :88 -- identical to the delete op's chain; ``CrudProbeSeconds`` is 180
  (EntityCrudProbe.cs:16) and ``CrudProbeName`` is ``"MW_CRUD_Probe"`` (:15).

HOW THIS FILE TESTS IT (no request is ever sent)

  * SOURCE FIDELITY -- each guard is bound to the EXACT source spelling of its clauses and
    its named refusal. Weakening or dropping a clause, re-ordering a guard, or dropping a
    name makes a test fail. The ADD gate's spend bit ``AddSpent`` must exist on
    ``CrudExperiment`` (EntityCrudProbe.cs) and be the FIRST clause of the guard.
  * DECISION MODEL -- the chain is extracted into a runnable Python transcription of the
    three C# functions and driven with synthetic probe/baseline/registry objects. Every
    case asserts the exact named code (or ACCEPTED); a bare "it did not throw" is not a test.
  * NEGATIVE CONTROL -- each guard is removed from the extracted copy one at a time and the
    case it pins is shown to FLIP. If a guard were load-bearing only by testimony, its
    removal would leave the verdict unchanged; it does not.

Nothing here starts, contacts, or injects into the game, editor, bridge or helper; it reads
two ``.cs`` files and runs pure Python.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_component_add_safety
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
ADD_SRC = ROOT / "tools/editor-bridge/Adapter/EntityComponentAdd.cs"
PROBE_SRC = ROOT / "tools/editor-bridge/Adapter/EntityCrudProbe.cs"

PROBE_NAME = "MW_CRUD_Probe"     # EntityCrudProbe.cs:15
CRUD_PROBE_SECONDS = 180         # EntityCrudProbe.cs:16
ENTITY_TYPE_TARGET = 1402        # the CRUD probe's own native entity type
INSTANCE_KIND_TARGET = 0
ACCEPTED = "ACCEPTED"
ADD_GUARD_CODE = "COMPONENT_ADD_OWNED_UNBOUND_TARGET_REQUIRED"

# Refusal codes this chain can produce. A verdict outside this set plus ACCEPTED would be
# an unnamed failure path, which is itself a bug -- test_refusals_are_all_named pins it.
REFUSAL_CODES = {
    "CRUD_PROBE_NOT_BEGUN",
    "CRUD_PROBE_EXPIRED",
    "CRUD_CONTEXT_CHANGED",
    "CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED",
    "CRUD_TARGET_NOT_REGISTERED",
    "CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED",
    "CRUD_PROBE_NAME_CONFLICT",
    "CRUD_TARGET_NAME_CHANGED_EXTERNALLY",
    ADD_GUARD_CODE,
}


# ---------------------------------------------------------------------------------------
# The extracted decision model: a runnable transcription of the three C# functions.
# ---------------------------------------------------------------------------------------

class Refusal(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclasses.dataclass(frozen=True)
class CrudKey:
    """CrudKey(Category0, Category1, Category2, Category3, Id) -- only Id is compared here
    because the other four categories are equal across every synthetic fixture."""
    id: int


@dataclasses.dataclass(frozen=True)
class CrudEntity:
    """CrudEntity(Key, Model, Name, PrefabId, TemplateId, EntityType, InstanceKind).
    ``model`` stands in for the editor-model object; equality of two models is REFERENCE
    equality, exactly as SameCrudIdentity requires."""
    key: CrudKey
    model: object
    name: str
    prefab_id: int = 1
    template_id: int = 2
    entity_type: int = ENTITY_TYPE_TARGET
    instance_kind: int = INSTANCE_KIND_TARGET


@dataclasses.dataclass
class CrudExperiment:
    """The subset of CrudExperiment (EntityCrudProbe.cs:19-30) the gate reads. ``add_spent``
    is the ADD lease -- an independent bit from the delete op's ``delete_spent``."""
    target: CrudEntity | None
    baseline: dict[int, CrudEntity]
    add_spent: bool = False
    delete_spent: bool = False   # the DELETE op's bit: present so independence can be shown
    elapsed_s: float = 0.0


@dataclasses.dataclass
class State:
    """Everything the chain reads for one add request."""
    probe: CrudExperiment | None
    current: dict[int, CrudEntity]      # a fresh ReadCrudEntities() snapshot
    context_same: bool = True           # ReferenceEquals(context.Context, probe.Context) && State ==
    bindings_len: int = 0               # EntityBindings(target.Model).Length
    entity_id: int = 0                  # the requested entityId


def same_identity(a: CrudEntity, b: CrudEntity) -> bool:
    """SameCrudIdentity (EntityCrudProbe.cs:83-86): key AND model reference AND prefab AND
    template AND type AND kind -- NAME IS NOT PART OF IDENTITY."""
    return (a.key == b.key and a.model is b.model and a.prefab_id == b.prefab_id
            and a.template_id == b.template_id and a.entity_type == b.entity_type
            and a.instance_kind == b.instance_kind)


def added_since_baseline(state: State) -> list[CrudEntity]:
    """current.Values.Where(e => !probe.Baseline.ContainsKey(e.Key.Id)) (EntityCrudProbe.cs:106)."""
    return [e for k, e in state.current.items() if k not in state.probe.baseline]


@dataclasses.dataclass(frozen=True)
class Guard:
    name: str
    code: str
    check: object   # Callable[[State], None]; raises Refusal(code) on violation


def _g_not_begun(s: State) -> None:
    if s.probe is None:                                          # :90
        raise Refusal("CRUD_PROBE_NOT_BEGUN")


def _g_expired(s: State) -> None:
    if s.probe.elapsed_s >= CRUD_PROBE_SECONDS:                  # :91
        raise Refusal("CRUD_PROBE_EXPIRED")


def _g_context(s: State) -> None:
    if not s.context_same:                                       # :93-94
        raise Refusal("CRUD_CONTEXT_CHANGED")


def _g_baseline(s: State) -> None:
    for k, old in s.probe.baseline.items():                      # :96-98
        now = s.current.get(k)
        if now is None or not same_identity(old, now):
            raise Refusal("CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED")


def _g_target_registered(s: State) -> None:
    if s.probe.target is None:                                   # :105
        raise Refusal("CRUD_TARGET_NOT_REGISTERED")


def _g_added_set(s: State) -> None:
    added = added_since_baseline(s)                              # :107-108
    if (len(added) != 1 or not same_identity(s.probe.target, added[0])
            or added[0].entity_type != ENTITY_TYPE_TARGET
            or added[0].instance_kind != INSTANCE_KIND_TARGET):
        raise Refusal("CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED")


def _g_probe_name(s: State) -> None:
    if any(k != s.probe.target.key.id and e.name == PROBE_NAME    # :109-110
           for k, e in s.current.items()):
        raise Refusal("CRUD_PROBE_NAME_CONFLICT")


def _g_target_name(s: State) -> None:
    a0 = added_since_baseline(s)[0]                              # :111-112
    if a0.name != s.probe.target.name and a0.name != PROBE_NAME:
        raise Refusal("CRUD_TARGET_NAME_CHANGED_EXTERNALLY")


def _g_owned(s: State) -> None:
    p, t = s.probe, s.probe.target                               # ComponentAddOwnedTarget
    if (p.add_spent or t.key.id != s.entity_id
            or t.entity_type != ENTITY_TYPE_TARGET
            or t.instance_kind != INSTANCE_KIND_TARGET
            or s.bindings_len != 0):
        raise Refusal(ADD_GUARD_CODE)


#: The chain, in the order the C# evaluates it: CheckCrudBaseline's four guards, then the
#: top of CheckCrudTarget's three, then ComponentAddOwnedTarget's one five-clause guard.
GUARDS: list[Guard] = [
    Guard("probe-not-begun", "CRUD_PROBE_NOT_BEGUN", _g_not_begun),
    Guard("probe-expired", "CRUD_PROBE_EXPIRED", _g_expired),
    Guard("context-changed", "CRUD_CONTEXT_CHANGED", _g_context),
    Guard("baseline-entity-lost", "CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED", _g_baseline),
    Guard("target-not-registered", "CRUD_TARGET_NOT_REGISTERED", _g_target_registered),
    Guard("added-set-changed", "CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED", _g_added_set),
    Guard("probe-name-conflict", "CRUD_PROBE_NAME_CONFLICT", _g_probe_name),
    Guard("target-name-changed", "CRUD_TARGET_NAME_CHANGED_EXTERNALLY", _g_target_name),
    Guard("owned-target-unbound", ADD_GUARD_CODE, _g_owned),
]


def verdict(state: State, guards: list[Guard] | None = None) -> str:
    """Run the chain; return the refusal code, ACCEPTED, or ERR:<Type> (a mutant that
    removed a guard may index an absent collection -- that is a flip, not a pass)."""
    try:
        for guard in (GUARDS if guards is None else guards):
            guard.check(state)
    except Refusal as refusal:
        return refusal.code
    except Exception as exc:  # noqa: BLE001 -- a removed guard can leave a dangling index
        return "ERR:" + type(exc).__name__
    return ACCEPTED


# ---------------------------------------------------------------------------------------
# Synthetic fixtures (probe / baseline / fresh registry). No editor, no request.
# ---------------------------------------------------------------------------------------

MODEL_BASE = object()
MODEL_TARGET = object()
MODEL_OTHER = object()
MODEL_MOVED = object()


def entity(eid: int, name: str, model: object, *, type_: int = ENTITY_TYPE_TARGET,
           kind: int = INSTANCE_KIND_TARGET) -> CrudEntity:
    return CrudEntity(CrudKey(eid), model, name, entity_type=type_, instance_kind=kind)


def healthy_state() -> State:
    """The ONE accepted shape: one new 1402/kind0 entity named as the probe recorded it,
    matching the probe target by key+model, in a live baseline, unbound, un-spent."""
    base = entity(1, "BaseCube", MODEL_BASE)
    target = entity(999, "UserCube", MODEL_TARGET)
    probe = CrudExperiment(target=target, baseline={1: base})
    return State(probe=probe, current={1: base, 999: target}, entity_id=999)


def _replace(state: State, **kw) -> State:
    return dataclasses.replace(state, **kw)


def _replace_probe(state: State, **kw) -> State:
    assert state.probe is not None
    return dataclasses.replace(state, probe=dataclasses.replace(state.probe, **kw))


def case_no_probe() -> State:
    return _replace(healthy_state(), probe=None)


def case_expired() -> State:
    return _replace_probe(healthy_state(), elapsed_s=CRUD_PROBE_SECONDS)


def case_context_changed() -> State:
    return _replace(healthy_state(), context_same=False)


def case_baseline_lost() -> State:
    s = healthy_state()
    return _replace(s, current={999: s.current[999]})           # baseline id 1 vanished


def case_target_not_registered() -> State:
    return _replace_probe(healthy_state(), target=None)


def case_two_candidates() -> State:
    s = healthy_state()
    cur = dict(s.current)
    # A second new entity with the SAME name as the target, so the ONLY clause that refuses
    # is added.Length != 1 (the ambiguity clause) -- and a mutant that drops it is clean.
    cur[1000] = entity(1000, "UserCube", MODEL_OTHER)
    return _replace(s, current=cur)


def case_identity_changed() -> State:
    s = healthy_state()
    cur = dict(s.current)
    cur[999] = entity(999, "UserCube", MODEL_MOVED)             # same key, different model
    return _replace(s, current=cur)


def case_foreign_probe_name() -> State:
    s = healthy_state()
    cur = dict(s.current)
    cur[1] = entity(1, PROBE_NAME, MODEL_BASE)                  # a NON-target wears the name
    return _replace(s, current=cur)


def case_target_name_changed() -> State:
    s = healthy_state()
    cur = dict(s.current)
    cur[999] = entity(999, "Renamed", MODEL_TARGET)             # identity intact, name not
    return _replace(s, current=cur)


def case_add_spent() -> State:
    return _replace_probe(healthy_state(), add_spent=True)


def case_id_mismatch() -> State:
    return _replace(healthy_state(), entity_id=555)            # requested != probe target


def case_bindings_present() -> State:
    return _replace(healthy_state(), bindings_len=1)


#: case name -> (builder, expected verdict). Each expected verdict is a NAMED code (or
#: ACCEPTED); the assertion is equality, never "it did not throw".
CASES: dict[str, tuple[object, str]] = {
    "single-matching-target": (healthy_state, ACCEPTED),
    "no-probe": (case_no_probe, "CRUD_PROBE_NOT_BEGUN"),
    "probe-expired": (case_expired, "CRUD_PROBE_EXPIRED"),
    "context-changed": (case_context_changed, "CRUD_CONTEXT_CHANGED"),
    "baseline-entity-lost": (case_baseline_lost, "CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED"),
    "target-not-registered": (case_target_not_registered, "CRUD_TARGET_NOT_REGISTERED"),
    "two-candidates": (case_two_candidates, "CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED"),
    "identity-changed": (case_identity_changed, "CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED"),
    "foreign-probe-name": (case_foreign_probe_name, "CRUD_PROBE_NAME_CONFLICT"),
    "target-name-changed": (case_target_name_changed, "CRUD_TARGET_NAME_CHANGED_EXTERNALLY"),
    "add-spent": (case_add_spent, ADD_GUARD_CODE),
    "id-mismatch": (case_id_mismatch, ADD_GUARD_CODE),
    "bindings-present": (case_bindings_present, ADD_GUARD_CODE),
}

#: guard name -> the representative case its removal must flip (negative control).
PINNED = {
    "probe-not-begun": "no-probe",
    "probe-expired": "probe-expired",
    "context-changed": "context-changed",
    "baseline-entity-lost": "baseline-entity-lost",
    "target-not-registered": "target-not-registered",
    "added-set-changed": "two-candidates",
    "probe-name-conflict": "foreign-probe-name",
    "target-name-changed": "target-name-changed",
    "owned-target-unbound": "id-mismatch",
}


# ---------------------------------------------------------------------------------------
# Source fidelity: bind every guard to the exact C# spelling, and pin the cited lines.
# ---------------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


ADD_N = _norm(ADD_SRC.read_text(encoding="utf-8"))
PROBE_N = _norm(PROBE_SRC.read_text(encoding="utf-8"))

#: guard name -> (normalised source, the exact guard clause + named throw). Presence proves
#: the guard exists AND is spelled with every clause the Python model encodes.
GUARD_SOURCE: dict[str, tuple[str, str]] = {
    "probe-not-begun": (PROBE_N,
        'var probe = crudExperiment ?? throw new InvalidOperationException("CRUD_PROBE_NOT_BEGUN");'),
    "probe-expired": (PROBE_N,
        'if (probe.Clock.Elapsed.TotalSeconds >= CrudProbeSeconds) '
        'throw new InvalidOperationException("CRUD_PROBE_EXPIRED");'),
    "context-changed": (PROBE_N,
        'if (!ReferenceEquals(context.Context, probe.Context) || context.State != probe.ContextState) '
        'throw new InvalidOperationException("CRUD_CONTEXT_CHANGED");'),
    "baseline-entity-lost": (PROBE_N,
        'if (!current.TryGetValue(old.Key.Id, out var now) || !SameCrudIdentity(old, now)) '
        'throw new InvalidOperationException("CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED");'),
    "target-not-registered": (PROBE_N,
        'var target = probe.Target ?? throw new InvalidOperationException("CRUD_TARGET_NOT_REGISTERED");'),
    "added-set-changed": (PROBE_N,
        'if (added.Length != 1 || !SameCrudIdentity(target, added[0]) || added[0].EntityType != 1402 '
        '|| added[0].InstanceKind != 0) '
        'throw new InvalidOperationException("CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED");'),
    "probe-name-conflict": (PROBE_N,
        'if (current.Values.Any(e => e.Key.Id != target.Key.Id && e.Name == CrudProbeName)) '
        'throw new InvalidOperationException("CRUD_PROBE_NAME_CONFLICT");'),
    "target-name-changed": (PROBE_N,
        'if (added[0].Name != target.Name && added[0].Name != CrudProbeName) '
        'throw new InvalidOperationException("CRUD_TARGET_NAME_CHANGED_EXTERNALLY");'),
    "owned-target-unbound": (ADD_N,
        'if (current.Probe.AddSpent || current.Target.Key.Id != entityId '
        '|| current.Target.EntityType != 1402 || current.Target.InstanceKind != 0 '
        '|| EntityBindings(current.Target.Model).Length != 0) '
        'throw new InvalidOperationException("COMPONENT_ADD_OWNED_UNBOUND_TARGET_REQUIRED");'),
}


class DecisionChainBehaviour(unittest.TestCase):
    """Drive the extracted model with synthetic objects and pin every named verdict."""

    def test_every_case_yields_its_named_verdict(self) -> None:
        for name, (builder, expected) in CASES.items():
            with self.subTest(case=name):
                self.assertEqual(
                    verdict(builder()), expected,
                    f"{name}: expected the named verdict {expected}")

    def test_single_matching_target_is_accepted(self) -> None:
        self.assertEqual(verdict(healthy_state()), ACCEPTED,
                         "the one self-owned target must be ACCEPTED, not refused")

    def test_ambiguity_of_two_candidates_is_refused(self) -> None:
        """Two new entities -- the target plus a clone -- is an AMBIGUITY refusal, not a
        silent pick of one of them."""
        self.assertEqual(verdict(case_two_candidates()),
                         "CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED")

    def test_add_lease_is_independent_of_the_delete_lease(self) -> None:
        """The ADD spend bit gates the add op; the DELETE spend bit must NOT (the two
        directions carry separate budgets)."""
        s = healthy_state()
        s.probe.delete_spent = True          # not read by the ADD gate
        self.assertEqual(verdict(s), ACCEPTED,
                         "the delete lease must not lock the add direction")

    def test_refusals_are_all_named(self) -> None:
        """Every non-accepted verdict is one of the chain's named codes -- no unnamed path."""
        for name, (builder, expected) in CASES.items():
            if expected is ACCEPTED:
                continue
            with self.subTest(case=name):
                got = verdict(builder())
                self.assertIn(got, REFUSAL_CODES, f"{name}: unnamed refusal `{got}`")

    def test_the_guard_order_is_the_source_order(self) -> None:
        """The model's guard order equals the C# evaluation order (baseline -> target ->
        owned). A re-ordered guard would change WHICH code fires for a multi-violation
        state, so order is part of the contract."""
        self.assertEqual([g.name for g in GUARDS], list(PINNED))
        first_eight = [g.code for g in GUARDS[:8]]
        positions = [PROBE_N.index(code) for code in first_eight]
        self.assertEqual(positions, sorted(positions),
                         "the CheckCrud guard order must match the source throw order")


class SourceFidelity(unittest.TestCase):
    """Bind the Python model to the C# it transcribes; weaken the C#, fail the test."""

    def test_sources_are_present(self) -> None:
        self.assertIn("sealed partial class EditorAdapter", ADD_N)
        self.assertIn("sealed partial class EditorAdapter", PROBE_N)

    def test_add_spent_field_still_exists_on_crud_experiment(self) -> None:
        self.assertIn("public bool RenameSpent, RestoreSpent, DeleteSpent, AddSpent;", PROBE_N,
                      "the ADD lease bit AddSpent must remain on CrudExperiment")

    def test_component_add_owned_target_is_defined_and_delegates_to_check_crud_target(self) -> None:
        lines = ADD_SRC.read_text(encoding="utf-8").splitlines()
        def_idx = next(i for i, l in enumerate(lines)
                       if l.strip().startswith("(CrudExperiment Probe, CrudEntity Target) ComponentAddOwnedTarget(uint entityId)"))
        window = "\n".join(lines[def_idx:def_idx + 8])
        self.assertIn("var current = CheckCrudTarget();", window,
                      "the ADD gate must START from CheckCrudTarget")
        self.assertIn("COMPONENT_ADD_OWNED_UNBOUND_TARGET_REQUIRED", window,
                      "the ADD gate must refuse with its named code")
        self.assertLess(window.index("CheckCrudTarget()"),
                        window.index("COMPONENT_ADD_OWNED_UNBOUND_TARGET_REQUIRED"),
                        "CheckCrudTarget must be called before the refusal")

    def test_add_spent_is_the_first_clause_of_the_guard(self) -> None:
        """The spend bit must be evaluated FIRST in the guard's disjunction: an already-spent
        probe must refuse even if every later clause would pass."""
        snippet = GUARD_SOURCE["owned-target-unbound"][1]
        self.assertTrue(snippet.startswith(
            'if (current.Probe.AddSpent || current.Target.Key.Id != entityId'),
            "AddSpent must remain the first disjunct of the ADD owned-target guard")

    def test_every_guard_is_wired_in_the_source(self) -> None:
        for name, (source, snippet) in GUARD_SOURCE.items():
            with self.subTest(guard=name):
                self.assertIn(snippet, source,
                              f"guard `{name}` no longer matches its source clause+throw")

    def test_every_model_guard_has_a_source_clause_and_vice_versa(self) -> None:
        self.assertEqual(set(GUARD_SOURCE), {g.name for g in GUARDS},
                         "the guard list and the source-clause table must be the same set")
        self.assertEqual(set(PINNED), {g.name for g in GUARDS},
                         "every guard must have a pinned negative-control case")


class NegativeControl(unittest.TestCase):
    """Remove ONE guard from the extracted copy; the case it pins must FLIP.

    A guard whose removal leaves the verdict unchanged is decorative, not load-bearing.
    """

    def test_removing_each_guard_flips_its_pinned_case(self) -> None:
        for guard_name, case_name in PINNED.items():
            with self.subTest(guard=guard_name, case=case_name):
                builder, expected = CASES[case_name]
                state = builder()
                self.assertEqual(verdict(state), expected,
                                 f"{case_name} must be refused/accepted as {expected}")
                mutant = [g for g in GUARDS if g.name != guard_name]
                flipped = verdict(state, mutant)
                self.assertNotEqual(
                    flipped, expected,
                    f"removing guard `{guard_name}` left {case_name} == {expected}: "
                    f"the guard is not load-bearing for this case")

    def test_the_negative_control_is_not_vacuous(self) -> None:
        """Sanity: with ALL guards removed the accepted shape is still accepted, so the
        flip in the test above comes from the removal and not from the harness."""
        self.assertEqual(verdict(healthy_state(), []), ACCEPTED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
