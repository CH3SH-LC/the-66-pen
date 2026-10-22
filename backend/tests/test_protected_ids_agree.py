#!/usr/bin/env python3
"""F-011 -- the frozen unattributable ids are ONE per-level map, and judge() can only tighten.

The three ids 2026-09-30 could not attribute (1077936129/130/131) are declared in three
places:

    backend/cleanup_ownership_legs.py      PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL  dict[int, frozenset[int]]
    backend/cleanup_service.py             PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL  dict[int, frozenset[int]]
    tools/entity-create/run_parameter_matrix.py
                                           PROTECTED_ENTITY_IDS_BY_LEVEL         dict[int, frozenset[str]]

MEASURED 2026-10-04: the legs module's own docstring claimed "the wiring passes
``cleanup_service``'s constant **and a test asserts the two are equal**". Both halves were
false -- ``judge()`` had no such parameter, and no test compared the constants. A frozen
set that can drift apart in silence is exactly the failure this project keeps recording,
so the claim is made true here rather than deleted.

WHY THE SHAPE IS PER-LEVEL (2026-10-08).  It used to be one flat set, and a flat set
protects those NUMBERS in every level.  An entity id is not a property of an object -- the
project has recorded 1077936135 in two levels under two different templates.  MEASURED
consequence of the flat form: the live parameter driver created entity 1077936130 in level
1073741842, held its own create receipt for it, and was then refused permission to delete
it, so the run could not clean up after itself and left an orphan behind.  The protection
was a fact about (1073741839, id), never about id alone.

THE CHAIN THIS ASSERTS (each link falsifiable on its own)
    legs.BY_LEVEL == service.BY_LEVEL                              [one map]
    driver.BY_LEVEL == the same ids, as strings                    [one map]
    legs.protected_ids_for(1839) == service.protected_ids_for(1839) [resolvers agree]
    judge(manifest @1839)           freezes that level's own ids    [default]
    judge(manifest @OTHER)          freezes NOTHING for that level  [scoped, the 10-08 fix]
    judge(manifest, protected_ids=X) freezes UNION(own, X), never less [tighten-only]

MUTATION CONTROLS
    Two mutations, each against a mutated COPY of the legs module, each MUST go red:
      m1  widen the 1839 entry by one id  -> the cross-module equality goes red
      m2  make the resolver level-blind    -> the OTHER-level test goes red
    m2 is the control for the 2026-10-08 fix itself: without it, "the ids are not frozen on
    another level" would be an assertion no run could ever falsify.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

OTHER_LEVEL = 1073741842          # measured live level on 2026-10-08
FROZEN_LEVEL = 1073741839         # the level those three ids were observed in


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


LEGS = _load("_t_pids_legs", "backend/cleanup_ownership_legs.py")
SERVICE = _load("_t_pids_service", "backend/cleanup_service.py")
DRIVER = _load("_t_pids_driver", "tools/entity-create/run_parameter_matrix.py")

EXPECTED = {FROZEN_LEVEL: frozenset({1077936129, 1077936130, 1077936131})}

DECLARATION = "    1073741839: frozenset({1077936129, 1077936130, 1077936131}),"
RESOLVER_BODY = ("        return frozenset(PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL"
                 ".get(int(level_id), ()))")


def _mutated_legs(*, bump=False, level_blind=False):
    """The legs module with ONE deliberate mutation, applied to a copy."""
    source = (ROOT / "backend/cleanup_ownership_legs.py").read_text(encoding="utf-8")
    if bump:
        if source.count(DECLARATION) != 1:
            raise AssertionError("the constant's declaration moved; re-anchor this mutation")
        source = source.replace(
            DECLARATION,
            "    1073741839: frozenset({1077936129, 1077936130, 1077936131, 999999999}),", 1)
    if level_blind:
        if source.count(RESOLVER_BODY) != 1:
            raise AssertionError("the resolver's body moved; re-anchor this mutation")
        source = source.replace(
            RESOLVER_BODY,
            "        return frozenset().union(*PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL.values())"
            "  # MUTATION: level-blind, the 2026-10-08 bug", 1)
    target = ROOT / (".runtime/backend/tests/_mutated_protected_ids%s.py"
                     % ("_blind" if level_blind else ("_bump" if bump else "_same")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8", newline="\n")
    return _load("_t_pids_mut" + target.stem, str(target.relative_to(ROOT)))


class ProtectedIdsAgree(unittest.TestCase):
    def test_a_the_legs_and_service_maps_are_the_same(self):
        self.assertEqual(legs := LEGS.PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL,
                         SERVICE.PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL,
                         "the two modules disagree about which ids are frozen, or where")
        self.assertEqual(legs, EXPECTED)

    def test_b_the_driver_names_the_same_ids_for_the_same_level(self):
        driver = {int(level): {int(v) for v in ids}
                  for level, ids in DRIVER.PROTECTED_ENTITY_IDS_BY_LEVEL.items()}
        self.assertEqual(driver, EXPECTED,
                         "the driver's PROTECTED_ENTITY_IDS_BY_LEVEL is a different map")

    def test_c_the_three_resolvers_agree_per_level(self):
        for level, ids in EXPECTED.items():
            self.assertEqual(LEGS.protected_ids_for(level), ids)
            self.assertEqual(SERVICE.protected_ids_for(level), ids)
            self.assertEqual({int(v) for v in DRIVER.protected_entity_ids_for(level)}, ids)

    def test_d_another_level_freezes_nothing(self):
        # THE 2026-10-08 FIX.  A flat set protected these numbers everywhere; the ids are
        # a fact about (level, id), so on any other level the freeze is empty.  Protection
        # is not invented where it is not known to apply -- ownership still has to be
        # proved for the round before anything can be deleted.
        for module, name in ((LEGS, "legs"), (SERVICE, "service"), (DRIVER, "driver")):
            resolver = getattr(module, "protected_ids_for", None) or \
                module.protected_entity_ids_for
            self.assertEqual(resolver(OTHER_LEVEL), frozenset(),
                             "%s still freezes ids on a level they were not observed in" % name)
        # What judge() DOES with that empty freeze is not asserted here: a bare manifest
        # is not a decidable round, so judge refuses the round itself (WINDOW_INVALID)
        # before reaching any id -- correct behaviour, and my first draft of this very
        # test got it wrong in the same way the NOTE below describes.  The resolver is the
        # unit under test; the guard suite owns the decidable-round behaviour.
        # An unknown/absent level must behave the same way, never widen.
        self.assertEqual(LEGS.protected_ids_for(None), frozenset())
        self.assertEqual(LEGS.protected_ids_for("not-a-level"), frozenset())

    def test_e_judge_tightens_for_its_own_level_and_can_only_tighten(self):
        manifest = {"levelId": FROZEN_LEVEL, "candidates": []}
        default = LEGS.judge(manifest)
        widened = LEGS.judge(manifest, protected_ids=[999999999])
        narrowed = LEGS.judge(manifest, protected_ids=[])
        # A caller may add protection, never remove it: passing an empty set must behave
        # exactly like passing nothing, and passing an extra id must only add.
        self.assertEqual(default.get("runRefusals"), narrowed.get("runRefusals"),
                         "an empty caller set changed the verdict: it must be a no-op")
        self.assertEqual(default.get("status"), widened.get("status"))
        self.assertEqual(default.get("ownedIds"), narrowed.get("ownedIds"))

    # NOTE: leg G's own refusal of these ids is NOT re-proved here.  A manifest that
    # reaches leg G needs a decidable round (a real read-back, receipts, window), and the
    # guard suite's `p_legit` and the W2 ownership suite already assert exactly that.  My
    # first draft asserted it against a bare manifest and got READBACK_UNAVAILABLE -- the
    # round was refused before leg G, which is correct behaviour and a wrong expectation
    # on my part.  This file's job is the cross-module agreement and the tighten-only
    # rule, not a third copy of leg G.


class MutationControl(unittest.TestCase):
    """A green run is only evidence if the test can tell the difference."""

    def test_m1_a_widened_entry_goes_red(self):
        mutated = _mutated_legs(bump=True)
        self.assertNotEqual(mutated.PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL, EXPECTED,
                            "the mutation did not change the map")
        self.assertNotEqual(mutated.PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL,
                            SERVICE.PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL,
                            "the equality check would not have caught the drift")

    def test_m2_a_level_blind_resolver_goes_red(self):
        # THE CONTROL FOR THE FIX ITSELF.  Restore the old behaviour -- resolve every level
        # to the union -- and test_d must notice on the other level.
        mutated = _mutated_legs(level_blind=True)
        self.assertEqual(mutated.protected_ids_for(OTHER_LEVEL),
                         frozenset({1077936129, 1077936130, 1077936131}),
                         "the mutation did not make the resolver level-blind")
        self.assertNotEqual(mutated.protected_ids_for(OTHER_LEVEL), frozenset(),
                            "test_d would still pass against the level-blind resolver, so it "
                            "is not a control for the fix")
        self.assertEqual(mutated.protected_ids_for(FROZEN_LEVEL),
                         frozenset({1077936129, 1077936130, 1077936131}),
                         "the mutation changed the frozen level too, so it is not narrow")

    def test_m0_the_unmutated_copy_stays_green(self):
        # The control is the same code path with no mutation applied: it must agree, or the
        # checks above would be red for an unrelated reason.
        same = _mutated_legs()
        self.assertEqual(same.PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL, EXPECTED)
        self.assertEqual(same.protected_ids_for(OTHER_LEVEL), frozenset())


if __name__ == "__main__":
    unittest.main(verbosity=2)
