"""Execute the composed farm edges offline; these are not native-play proofs."""
from dataclasses import replace
import unittest

from tools.gameplan.modules import distance_interaction as d, player_abilities as a
from tools.gameplan.modules.farm_interaction import (
    EMPTY, GROWING, RIPE, MUTATING, UNCERTAIN, FarmConfig, install)
from tools.gameplan.nodes import Graph, SELF
from tools.gameplan.tests.test_farming_interactive import GraphEvaluator

CONFIG = FarmConfig(1077936130, 1107296257, 1107296258, "uint", "enum")


class FarmEvaluator(GraphEvaluator):
    """Extend the existing graph interpreter with observed bag outcomes.

    zero_delta models 686 making no change (e.g. bag full). Overrides model an
    unexpected delta or exception; they do not pretend to model native limits.
    """
    def __init__(self, plan):
        super().__init__(plan, own="player")
        self.entity_by_guid = {1077936130: "plot", 1077936129: "shop"}
        self.zero_delta = set()
        self.delta_override = {}
        self.raise_on_change = False
        self.attempts = []
        self.on_change = None

    def value(self, alias, index):
        definition = self.nodes[alias].definition_id
        if definition == 75:
            return self.entity_by_guid[self.input(alias, 0)]
        if definition == 76:
            return next(guid for guid, entity in self.entity_by_guid.items()
                        if entity == self.input(alias, 0))
        if definition == 200:
            assert self.input(alias, 2) == 300
            return self.input(alias, 0) + self.input(alias, 1)
        return super().value(alias, index)

    def input(self, alias, index):
        result = super().input(alias, index)
        if self.nodes[alias].definition_id == 686 and index == 2:
            item_id = super().input(alias, 1)
            self.attempts.append((super().input(alias, 0), item_id, result))
            if self.on_change:
                callback, self.on_change = self.on_change, None
                callback()
            if self.raise_on_change:
                raise RuntimeError("simulated native bag failure")
            if item_id in self.zero_delta:
                return 0
            return self.delta_override.get(item_id, result)
        return result

    def press(self, character="character"):
        self.fire("action", {0: character, 1: "unused-character-guid", 2: "", 3: "", 4: ""})

    def mature(self, *, owner="player", name=None, context=1077936130):
        self.fire("farm_tick", {0: owner, 1: "unused-owner-guid",
            2: name or CONFIG.timer_name, 3: 0, 4: 0, 5: context})

    @property
    def stage(self):
        return self.state.get(("plot", CONFIG.state_name), EMPTY)

    def quantity(self, item_id, character="character"):
        return self.inventory[(character, item_id)]


def core_plan():
    g = Graph("MW_API_MANUAL_FARM_TEST")
    owner = g.place(SELF, "owner")
    action = a.on_called(g, "action")
    plot = g.place(d.ENTITY, "plot")
    plot.const("guid", CONFIG.plot_id, "uint")
    guid = g.place(d.GUID, "plot_guid")
    guid.data_from(plot, "entity", "entity")
    install(g, action, character=(action, "caster"), plot=(plot, "entity"),
            timer_owner=(owner, "self"), plot_guid=(guid, "guid"),
            config=CONFIG, from_role="then")
    g.validate()
    return g.plan


class FarmInteractionTests(unittest.TestCase):
    def setUp(self):
        self.plan = core_plan()
        self.m = FarmEvaluator(self.plan)
        self.m.inventory[("character", CONFIG.seed_id)] = 2

    def test_press_plant_wait_press_harvest_and_repeat(self):
        m = self.m
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.seed_id)), (GROWING, 1))
        self.assertEqual(m.timers, [("player", CONFIG.timer_name, 0,
            {"list": [{"float": 10.0}]}, CONFIG.plot_id)])
        for _ in range(5):
            m.press()
        self.assertEqual(len(m.attempts), 1)
        m.mature()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (RIPE, 0))
        # Maturity and standing/leaving have no harvest entry. Only a new press.
        m.mature()
        self.assertEqual(m.quantity(CONFIG.crop_id), 0)
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (EMPTY, 1))
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.seed_id)), (GROWING, 0))
        m.mature()
        m.press()
        for _ in range(5):
            m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (EMPTY, 2))

    def test_no_seeds_never_calls_mutation_or_starts_timer(self):
        self.m.inventory[("character", CONFIG.seed_id)] = 0
        self.m.press()
        self.assertEqual(self.m.stage, EMPTY)
        self.assertFalse(self.m.attempts)
        self.assertFalse(self.m.timers)
        self.assertIn("FARM_NO_SEEDS", self.m.notes)

    def test_full_bag_keeps_ripe_and_new_press_can_collect_after_space_freed(self):
        m = self.m
        m.press()
        m.mature()
        m.zero_delta.add(CONFIG.crop_id)
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (RIPE, 0))
        self.assertIn("FARM_BAG_UNCHANGED", m.notes)
        m.zero_delta.clear()
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (EMPTY, 1))

    def test_failed_seed_decrement_does_not_start_growth(self):
        self.m.zero_delta.add(CONFIG.seed_id)
        self.m.press()
        self.assertEqual((self.m.stage, self.m.quantity(CONFIG.seed_id)), (EMPTY, 2))
        self.assertFalse(self.m.timers)

    def test_unexpected_delta_locks_without_replaying_or_clearing_crop(self):
        m = self.m
        m.press()
        m.mature()
        m.delta_override[CONFIG.crop_id] = 2
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (UNCERTAIN, 2))
        attempts = len(m.attempts)
        m.press()
        m.mature()
        self.assertEqual(len(m.attempts), attempts)
        self.assertEqual(m.stage, UNCERTAIN)

    def test_mutation_exception_leaves_lock_without_retry(self):
        self.m.raise_on_change = True
        with self.assertRaisesRegex(RuntimeError, "bag failure"):
            self.m.press()
        self.assertEqual(self.m.stage, MUTATING)
        self.m.raise_on_change = False
        self.m.press()
        self.assertEqual(len(self.m.attempts), 1)

    def test_nested_press_during_bag_change_sees_lock(self):
        m = self.m
        # Re-enter the exact action edge with the current event outputs intact.
        m.on_change = lambda: m._execute(list(m.flow[("action", 0)]))
        m.press()
        self.assertEqual((len(m.attempts), m.quantity(CONFIG.seed_id)), (1, 1))
        m.mature()
        m.on_change = lambda: m._execute(list(m.flow[("action", 0)]))
        m.press()
        self.assertEqual((len(m.attempts), m.quantity(CONFIG.crop_id)), (2, 1))

    def test_unrelated_timers_cannot_mature_or_harvest(self):
        self.m.press()
        self.m.mature(owner="other")
        self.m.mature(name="poll")
        self.m.mature(context=1077936129)
        self.assertEqual(self.m.stage, GROWING)
        self.assertEqual(self.m.quantity(CONFIG.crop_id), 0)

    def test_count_snapshots_are_written_before_and_after_686(self):
        self.m.inventory[("character", CONFIG.seed_id)] = 9
        self.m.press()
        self.assertEqual(self.m.state[("plot", f"MW_MANUAL_FARM_BEFORE_{CONFIG.plot_id}")], 9)
        self.assertEqual(self.m.state[("plot", f"MW_MANUAL_FARM_AFTER_{CONFIG.plot_id}")], 8)
        self.assertEqual(self.m.stage, GROWING)

    def test_invalid_config_rejected(self):
        for changes in ({"seed_id": CONFIG.crop_id}, {"growth_seconds": 0},
                        {"item_slot": "auto"}, {"variable_flag_slot": "int"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CONFIG, **changes)


if __name__ == "__main__":
    unittest.main()
