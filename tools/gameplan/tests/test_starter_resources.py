"""Execute actual generated nodes/edges with the existing offline evaluator.

No mirrored reward algorithm and no native success claim. The evaluator's state
map uses integer zero for missing variables, matching the local official query
description and this fragment's concrete integer anchor.
"""
from collections import defaultdict
import unittest

from tools.gameplan.modules import starter_resources
from tools.gameplan.nodes import ON_CREATE, PRINT, Graph
from tools.gameplan.tests.test_farming_interactive import GraphEvaluator


GUARD = "mw_farm_starter_v1"
OPTIONS = dict(seed_id=101, currency_id=201, item_slot="uint", currency_slot="uint",
               variable_flag_slot="enum", guard_name=GUARD)


def fixture(**overrides):
    graph = Graph("MW_API_STARTER_TEST")
    source = graph.place(ON_CREATE, "host_character_ready")
    result = starter_resources.grant_once(graph, source, character=(source, "entity"),
                                          **(OPTIONS | overrides))
    granted = graph.place(PRINT, "first_attempt")
    granted.const("text", "FIRST_ATTEMPT", "string")
    result.last.flow_to(granted)
    ready = graph.place(PRINT, "continue")
    ready.const("text", "CONTINUE", "string")
    granted.flow_to(ready)
    result.gate.flow_to(ready, "false")
    graph.validate()
    machine = GraphEvaluator(graph.plan)
    machine.state = defaultdict(int)
    return graph, result, machine


def activate(machine, character="character-a"):
    machine.fire("host_character_ready", {0: character, 1: f"guid-{character}"})


class StarterBehavior(unittest.TestCase):
    def test_first_then_repeat_character_gets_one_package_and_both_continue(self):
        _, _, machine = fixture()
        machine.character_owners["character-a"] = "player-a"
        activate(machine)
        self.assertEqual(machine.inventory[("character-a", 101)], 3)
        self.assertEqual(machine.currency[("character-a", 201)], 20)
        self.assertEqual(machine.state[("character-a", GUARD)], 1)
        self.assertEqual(machine.notes, ["FIRST_ATTEMPT", "CONTINUE"])
        activate(machine)
        activate(machine)
        self.assertEqual(machine.inventory[("character-a", 101)], 3)
        self.assertEqual(machine.currency[("character-a", 201)], 20)
        self.assertEqual(machine.notes.count("FIRST_ATTEMPT"), 1)
        self.assertEqual(machine.notes.count("CONTINUE"), 3)
        self.assertEqual(machine.inventory[("player-a", 101)], 0)
        self.assertEqual(machine.currency[("player-a", 201)], 0)
        self.assertEqual(machine.currency[("plot", 201)], 0)

    def test_consumed_resources_do_not_refill_on_reentry_or_same_character_revival(self):
        _, _, machine = fixture()
        activate(machine)
        machine.inventory[("character-a", 101)] = 0
        machine.currency[("character-a", 201)] = 0
        activate(machine)  # host presents same entity after leaving/revival
        self.assertEqual(machine.inventory[("character-a", 101)], 0)
        self.assertEqual(machine.currency[("character-a", 201)], 0)
        self.assertEqual(machine.state[("character-a", GUARD)], 1)

    def test_characters_independent_and_new_lifetime_explicitly_eligible(self):
        _, _, machine = fixture()
        activate(machine, "alice-character")
        activate(machine, "bob-character")
        activate(machine, "alice-character")
        for name in ("alice-character", "bob-character"):
            self.assertEqual(machine.inventory[(name, 101)], 3)
            self.assertEqual(machine.currency[(name, 201)], 20)
        # There is deliberately no unproved per-player reconnect persistence.
        activate(machine, "alice-replacement-character")
        self.assertEqual(machine.currency[("alice-replacement-character", 201)], 20)

    def test_shared_character_guard_blocks_other_plot_graph_from_rewarding_again(self):
        _, _, first = fixture()
        _, _, second = fixture()
        second.state, second.inventory, second.currency = first.state, first.inventory, first.currency
        activate(first)
        activate(second)
        self.assertEqual(second.currency[("character-a", 201)], 20)
        self.assertEqual(second.inventory[("character-a", 101)], 3)
        self.assertEqual(second.notes, ["CONTINUE"])

    def test_nonzero_guard_skips_without_reset_or_overwriting_existing_balances(self):
        _, _, machine = fixture()
        machine.state[("character-a", GUARD)] = 7
        machine.inventory[("character-a", 101)] = 8
        machine.currency[("character-a", 201)] = 50
        activate(machine)
        self.assertEqual(machine.state[("character-a", GUARD)], 7)
        self.assertEqual(machine.inventory[("character-a", 101)], 8)
        self.assertEqual(machine.currency[("character-a", 201)], 50)
        self.assertEqual(machine.notes, ["CONTINUE"])

    def test_adds_to_existing_inventory_and_custom_nonzero_quantities(self):
        _, _, machine = fixture(seed_count=5, currency_amount=11)
        machine.inventory[("character-a", 101)] = 2
        machine.currency[("character-a", 201)] = 9
        activate(machine)
        activate(machine)
        self.assertEqual(machine.inventory[("character-a", 101)], 7)
        self.assertEqual(machine.currency[("character-a", 201)], 20)

    def test_zero_grants_are_absent_and_empty_package_still_marks_once(self):
        for seeds, money in ((0, 20), (3, 0), (0, 0)):
            with self.subTest(seeds=seeds, money=money):
                graph, result, machine = fixture(seed_count=seeds, currency_amount=money)
                definitions = [node.definition_id for node in graph.plan.nodes]
                self.assertEqual(definitions.count(686), bool(seeds))
                self.assertEqual(definitions.count(688), bool(money))
                self.assertEqual(result.seed_grant is None, not seeds)
                self.assertEqual(result.currency_grant is None, not money)
                activate(machine)
                activate(machine)
                self.assertEqual(machine.inventory[("character-a", 101)], seeds)
                self.assertEqual(machine.currency[("character-a", 201)], money)
                self.assertEqual(machine.state[("character-a", GUARD)], 1)
                self.assertEqual(machine.notes.count("FIRST_ATTEMPT"), 1)

    def test_guard_precedes_effects_and_failed_grant_is_not_retried(self):
        class UnavailableBag(defaultdict):
            def __setitem__(self, key, value):
                raise RuntimeError("bag unavailable")
        _, _, machine = fixture()
        machine.inventory = UnavailableBag(int)
        with self.assertRaisesRegex(RuntimeError, "bag unavailable"):
            activate(machine)
        self.assertEqual(machine.state[("character-a", GUARD)], 1)
        self.assertFalse(machine.currency)
        machine.inventory = defaultdict(int)
        activate(machine)
        self.assertEqual(machine.inventory[("character-a", 101)], 0)
        self.assertEqual(machine.currency[("character-a", 201)], 0)
        self.assertEqual(machine.notes, ["CONTINUE"])

    def test_flags_and_holder_contracts_do_not_insert_owning_player_or_an_event(self):
        for slot in ("enum", "bool"):
            graph, _, machine = fixture(variable_flag_slot=slot)
            self.assertEqual(sum(n.definition_id == 71 for n in graph.plan.nodes), 1)
            self.assertFalse(any(n.definition_id in (259, 281, 286) for n in graph.plan.nodes))
            for constant in graph.plan.consts:
                if constant.alias == "starter_state" and constant.port_index == 2:
                    self.assertEqual((constant.slot, constant.value), (slot, 0 if slot == "enum" else False))
            activate(machine)
            self.assertEqual(machine.currency[("character-a", 201)], 20)

    def test_invalid_inputs_reject_before_adding_nodes(self):
        invalid = [("seed_id", 0), ("currency_id", True), ("seed_count", -1),
                   ("seed_count", 1.5), ("currency_amount", True),
                   ("currency_amount", 2147483648), ("guard_name", " "),
                   ("guard_name", "a\0b"), ("variable_flag_slot", "int"),
                   ("item_slot", "string")]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                graph = Graph("MW_API_BAD_STARTER")
                source = graph.place(ON_CREATE, "source")
                with self.assertRaises(ValueError):
                    starter_resources.grant_once(graph, source, character=(source,"entity"),
                                                 **(OPTIONS | {field:value}))
                self.assertEqual(len(graph.plan.nodes), 1)
        graph = Graph("MW_API_BAD_HOLDER")
        source = graph.place(ON_CREATE, "source")
        with self.assertRaisesRegex(ValueError, "must output an entity"):
            starter_resources.grant_once(graph, source, character=(source,"guid"), **OPTIONS)
        self.assertEqual(len(graph.plan.nodes), 1)


if __name__ == "__main__":
    unittest.main()
