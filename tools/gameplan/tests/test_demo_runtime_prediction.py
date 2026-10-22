"""Offline test of *what the runnable demo should do* — the playtest's control.

:mod:`tools.gameplan.runtime_prediction` walks ``demo/farming_runnable.py`` from
its entry node and predicts the exact print set and firing order.  This test pins
that prediction and, more importantly, proves it is **derived from the plan** and
not a hardcoded guess:

  (a) the prediction is the sharp, falsifiable statement — for the committed
      config exactly **one** line fires, ``作物不足``, because both gates go 否;
  (b) it is **robust** to the one thing we cannot observe (whether the bag write
      landed or the config-id dangled): the branch model evaluates both ends of
      that uncertainty and requires them to agree;
  (c) it **changes when the plan changes** — raise ``harvest_gain`` above
      ``recipe_cost`` and a *different* line becomes the prediction, so the test
      cannot be satisfied by a constant;
  (d) the family / predicate tables the model rests on are re-derived from
      ``data/node-contracts`` port names, so a contract rename fails here.

All of it is read-only and offline: no bridge, no native call, no save.

Run::

    python -B -m unittest tools.gameplan.tests.test_demo_runtime_prediction
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.gameplan import contracts, runtime_prediction as rp
from tools.gameplan.demo import farming_runnable as fr
from tools.gameplan.nodes import PRINT
from tools.gameplan.runtime_prediction import (
    COMPARE_PREDICATE,
    READ_FAMILY,
    WRITE_FAMILY,
    predict,
)

REPO = Path(__file__).resolve().parents[3]
ARTIFACT = REPO / ".runtime" / "scratch" / "DEMO-RUNNABLE-plan.json"

#: Chinese markers the tables must agree with, keyed by family / predicate.
FAMILY_MARKER = {"capacity": "容量", "item": "道具", "currency": "货币"}
PREDICATE_MARKER = {"lt": "小于", "le": "小于等于", "gt": "大于", "ge": "大于等于",
                    "eq": "相等"}


class PredictionIsSharp(unittest.TestCase):
    """(a) the exact statement a playtest is checked against."""

    def test_entry_is_the_create_event(self):
        pred = predict(fr.demo_plan())
        self.assertEqual(pred.entry.definition_id, 71)
        self.assertEqual(pred.entry.alias, "on_create")

    def test_exactly_two_lines_are_printed(self):
        pred = predict(fr.demo_plan())
        self.assertEqual(
            pred.prints, (fr.ENTRY_PROBE_TEXT, "作物不足"),
            "the committed config must fire the entry probe (WAVE-29AA) then exactly "
            "one leaf print — 作物不足 — because crop=+1 < recipe_cost=2 and "
            "coin=+10 < coin_threshold=100. Any other print set means the graph "
            "(or this model) changed.")

    def test_the_fired_print_node_is_print_short(self):
        pred = predict(fr.demo_plan())
        fired = [v for v in pred.executed if v.definition_id == PRINT.definition_id]
        self.assertEqual([v.alias for v in fired], ["print_entry", "print_short"])
        self.assertEqual(fired[0].index, 1)
        self.assertEqual(fired[1].index, 17)

    def test_execution_order(self):
        pred = predict(fr.demo_plan())
        self.assertEqual(
            [(v.definition_id, v.alias) for v in pred.executed],
            [(71, "on_create"), (1, "print_entry"), (685, "grow"), (686, "harvest"),
             (688, "bonus"), (2, "gate_item"), (2, "gate_money"), (1, "print_short")],
            "the exec-pin walk order drifted; this is the order a playtest's log "
            "should show the effects and the prints in.")

    def test_data_nodes_evaluated_are_only_item_and_currency(self):
        pred = predict(fr.demo_plan())
        self.assertEqual(
            [d.alias for d in pred.evaluated_data],
            ["craft_enough", "craft_enough_read", "coin_enough", "coin_enough_read"],
            "the capacity gate (689/230/cap_gate) must NOT be evaluated — its arm "
            "is dead under this config; only the item and currency reads run.")


class BranchArms(unittest.TestCase):
    """(a) both arms of both reached branches, and what selects them."""

    def test_gate_item_goes_false(self):
        pred = predict(fr.demo_plan())
        b = pred.branches[0]
        self.assertEqual((b.alias, b.family, b.predicate, b.threshold),
                         ("gate_item", "item", "ge", 2))
        self.assertEqual(b.taken, "false")
        self.assertTrue(b.decided)

    def test_gate_money_goes_false(self):
        pred = predict(fr.demo_plan())
        b = pred.branches[1]
        self.assertEqual((b.alias, b.family, b.predicate, b.threshold),
                         ("gate_money", "currency", "ge", 100))
        self.assertEqual(b.taken, "false")
        self.assertTrue(b.decided)

    def test_both_gates_are_decided_not_guessy(self):
        pred = predict(fr.demo_plan())
        self.assertTrue(all(b.decided for b in pred.branches),
                        "a branch the model could not decide (both bag states differ) "
                        "must fail loudly, not be printed as a prediction.")

    def test_capacity_gate_is_never_reached(self):
        pred = predict(fr.demo_plan())
        unexercised = {v.alias for v in pred.unexercised}
        for alias in ("cap_gate", "cap_gate_cap", "print_low_cap", "print_ok"):
            self.assertIn(alias, unexercised,
                          f"{alias} was exercised; under this config the capacity "
                          "arm is dead, so the unknown default capacity is moot.")


class RobustToTheUnknownBag(unittest.TestCase):
    """(b) the prediction does not depend on the write having landed."""

    def test_gate_item_is_stable_across_the_bag_uncertainty(self):
        pred = predict(fr.demo_plan())
        b = pred.branches[0]
        self.assertEqual(b.observed, (0, 1),
                         "the item gate must be evaluated at bag = 0 (dangling id) "
                         "and bag = 1 (grant landed); both => 否.")
        self.assertEqual(b.read_alias, "craft_enough_read")

    def test_gate_money_is_stable_across_the_bag_uncertainty(self):
        pred = predict(fr.demo_plan())
        b = pred.branches[1]
        self.assertEqual(b.observed, (0, 10),
                         "the currency gate must be evaluated at both ends: 0 and "
                         "coin_bonus=10; both => 否.")
        self.assertEqual(b.read_alias, "coin_enough_read")


class FalsifiedByAPlanChange(unittest.TestCase):
    """(c) the prediction is a function of the plan, not a constant."""

    def test_a_decided_change_flips_the_predicted_line(self):
        """Drop ``recipe_cost`` to 0 and the *reached leaf* changes, decided."""
        # crop = {0,1} >= 0 in both bag states -> 是, decided; then the capacity
        # gate (lt 20 over {0,10}) is decided 是 too.
        pred = predict(fr.plan_of(fr.RunnableConfig(currency_id=1115684864,
                                                    crop_id=1120000001,
                                                    recipe_cost=0)))
        self.assertEqual(pred.prints, (fr.ENTRY_PROBE_TEXT, fr.LOW_CAPACITY_TEXT),
                         "with recipe_cost=0 the crop gate must go 是 and the run "
                         "must reach the capacity arm — an unchanged prediction "
                         "would mean it was hardcoded. The entry probe (WAVE-29AA) "
                         "always precedes the reached leaf.")
        self.assertTrue(all(b.decided for b in pred.branches))

    def test_lowering_the_currency_threshold_flips_the_second_gate(self):
        rich = fr.plan_of(fr.RunnableConfig(currency_id=1115684864, crop_id=1120000001,
                                            coin_threshold=0))
        pred = predict(rich)
        # crop still short; coin={0,10} >= 0 -> 是, decided
        self.assertEqual(pred.prints, (fr.ENTRY_PROBE_TEXT, fr.SHORT_ITEM_RICH_TEXT))

    def test_raising_harvest_gain_makes_a_gate_undecided(self):
        """Honesty: past the threshold the crop gate is no longer decidable —
        the answer depends on whether the dangling id still carried the grant."""
        pred = predict(fr.plan_of(fr.RunnableConfig(currency_id=1115684864,
                                                    crop_id=1120000001,
                                                    harvest_gain=5)))
        b = pred.branches[0]
        self.assertEqual(b.observed, (0, 5))
        self.assertFalse(b.decided,
                         "crop={0,5} vs threshold 2 straddles the gate, so the model "
                         "must report it undecided, not silently pick an arm.")

    def test_the_four_lines_are_all_reachable(self):
        """The alphabet is complete: each of the four prints is reachable."""
        base = predict(fr.demo_plan())
        low = predict(fr.plan_of(fr.RunnableConfig(currency_id=1, crop_id=2,
                                                   recipe_cost=0)))
        ok = predict(fr.plan_of(fr.RunnableConfig(currency_id=1, crop_id=2,
                                                  recipe_cost=0,
                                                  capacity_threshold=0)))
        rich = predict(fr.plan_of(fr.RunnableConfig(currency_id=1, crop_id=2,
                                                    coin_threshold=0)))
        self.assertEqual(
            {base.prints[-1], low.prints[-1], ok.prints[-1], rich.prints[-1]},
            {fr.SHORT_ALL_TEXT, fr.LOW_CAPACITY_TEXT, fr.HARVEST_OK_TEXT,
             fr.SHORT_ITEM_RICH_TEXT},
            "the four branch leaves must each be reachable, so the prediction can "
            "distinguish all four outcomes rather than always naming one line.")


class TablesAgreeWithContracts(unittest.TestCase):
    """(d) the model's family/predicate tables are re-derived from the corpus."""

    def test_read_family_names_match_the_contract(self):
        store = contracts.default_store()
        for definition_id, family in READ_FAMILY.items():
            name = store.require(definition_id).name
            self.assertIn(FAMILY_MARKER[family], name,
                          f"defId {definition_id} ({name}) is filed under {family!r} "
                          f"but its name lacks {FAMILY_MARKER[family]!r}")

    def test_write_family_names_match_the_contract(self):
        store = contracts.default_store()
        for definition_id, family in WRITE_FAMILY.items():
            name = store.require(definition_id).name
            self.assertIn(FAMILY_MARKER[family], name,
                          f"defId {definition_id} ({name}) is filed under {family!r} "
                          f"but its name lacks {FAMILY_MARKER[family]!r}")

    def test_every_read_has_exactly_one_writer_family(self):
        reads = {fam: d for d, fam in READ_FAMILY.items()}
        writes = {fam: d for d, fam in WRITE_FAMILY.items()}
        self.assertEqual(sorted(reads), sorted(writes),
                         "a query family with no writer (or vice versa) would make "
                         "the branch model silently read a fixed 0.")

    def test_compare_predicates_match_the_contract(self):
        store = contracts.default_store()
        for definition_id, predicate in COMPARE_PREDICATE.items():
            name = store.require(definition_id).name
            self.assertIn(PREDICATE_MARKER[predicate], name,
                          f"defId {definition_id} ({name}) filed as {predicate!r}")


class DerivedFromTheCommittedArtifact(unittest.TestCase):
    """The prediction is reproducible from the on-disk plan, not just live code."""

    def test_artifact_print_texts_include_the_prediction(self):
        if not ARTIFACT.exists():
            self.skipTest(
                f"{ARTIFACT.relative_to(REPO).as_posix()} is absent (.runtime/ is "
                "git-ignored). Regenerate with the command in "
                "tools/gameplan/tests/test_demo_runnable.py::CommittedArtifact.")
        data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        printed = {c["value"] for c in data["constants"] if c["slot"] == "string"}
        pred = predict(fr.demo_plan())
        self.assertTrue(set(pred.prints) <= printed,
                        "the predicted line is not among the artifact's string "
                        "constants — the plan and the prediction have diverged.")
        self.assertEqual(data["entryDefinitionId"], 71)


if __name__ == "__main__":
    unittest.main()
