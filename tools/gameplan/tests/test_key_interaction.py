"""Execute generated graph edges; button-to-key delivery remains a runtime gate."""
import unittest
from tools.gameplan.contracts import default_store
from tools.gameplan.demo.shop_key_patch import build_player_plan
from tools.gameplan.modules import key_interaction as key
from tools.gameplan.nodes import Graph, PRINT
from tools.gameplan.tests.test_farming_interactive import GraphEvaluator


class KeyInteractionTests(unittest.TestCase):
    def fixture(self):
        plan = build_player_plan(101)
        machine = GraphEvaluator(plan, own='player-a')
        machine.characters = {'player-a': ['character-a'], 'player-b': ['character-b']}
        machine.positions = {'character-a': (1, 0, 0), 'character-b': (0, 0, 1)}
        # The evaluator models a scene GUID as a string; native graph keeps uint.
        machine.constants[('shop_owner', 0)] = 'guid-shop'
        return plan, machine

    def test_current_316_contract_has_group_indices_not_keyboard_id(self):
        definition = default_store().require(316)
        self.assertFalse(definition.exec_inputs)
        self.assertEqual([(p.kind, p.index, p.server_param_type) for p in definition.ports],
                         [(2, 0, 0), (4, 0, 1), (4, 1, 2), (4, 2, 3), (4, 3, 3)])

    def test_matching_control_uses_same_player_and_character(self):
        plan, machine = self.fixture()
        for player in ('player-a', 'player-b', 'player-a'):
            machine.fire('interact', {0: player, 1: 'unused-guid', 2: 0, 3: 101})
        self.assertEqual(machine.opened_shops,
                         [('player-a', 'shop', 1), ('player-b', 'shop', 1), ('player-a', 'shop', 1)])
        self.assertEqual(sum(n.definition_id == 316 for n in plan.nodes), 1)
        self.assertFalse(any(n.definition_id in (71, 79, 83, 76, 259, 686, 688) for n in plan.nodes))

    def test_wrong_control_far_or_ambiguous_character_does_not_open(self):
        _, machine = self.fixture()
        machine.fire('interact', {0: 'player-a', 1: 'unused', 2: 0, 3: 999})
        machine.positions['character-a'] = (4, 0, 0)
        machine.fire('interact', {0: 'player-a', 1: 'unused', 2: 0, 3: 101})
        for characters in ([], ['character-a', 'character-b']):
            machine.characters['player-a'] = characters
            machine.fire('interact', {0: 'player-a', 1: 'unused', 2: 0, 3: 101})
        self.assertEqual(machine.opened_shops, [])

    def test_explicit_combo_filter_and_invalid_indices(self):
        g = Graph('MW_API_KEY_COMBO')
        entry = key.on_control(g, group_index=7, group_combo_index=8)
        note = g.place(PRINT, 'accepted')
        note.const('text', 'OK', 'string')
        entry.gate.flow_to(note, 'true')
        g.validate()
        machine = GraphEvaluator(g.plan)
        machine.fire('interact', {0: 'player', 2: 9, 3: 7})
        self.assertEqual(machine.notes, [])
        machine.fire('interact', {0: 'player', 2: 8, 3: 7})
        self.assertEqual(machine.notes, ['OK'])
        for value in (0, -1, True, 1.5):
            empty = Graph('MW_API_BAD_KEY')
            with self.assertRaises(ValueError):
                key.on_control(empty, group_index=value)
            self.assertEqual(empty.plan.nodes, [])


if __name__ == '__main__':
    unittest.main()
