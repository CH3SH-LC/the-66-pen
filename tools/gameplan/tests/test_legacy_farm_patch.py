import unittest
from tools.gameplan.demo import legacy_farm_patch as patch


class LegacyFarmPatchTests(unittest.TestCase):
    def test_actual_saved_graph_requires_the_detach(self):
        before = patch.baseline()
        with self.assertRaisesRegex(ValueError, 'EXACT_THREE_EDGE'):
            patch.verify_graph(before)
        after = patch.remove_exact_entries(before)
        self.assertTrue(patch.verify_graph(after)['ok'])
        self.assertEqual(len(before.nodes), len(after.nodes))
        for a, b in zip(before.nodes, after.nodes):
            self.assertEqual(a.shell_ref, b.shell_ref)
            self.assertEqual([p.value for p in a.pins], [p.value for p in b.pins])

    def test_changed_constant_and_replay_are_rejected(self):
        after = patch.remove_exact_entries(patch.baseline())
        with self.assertRaisesRegex(ValueError, 'EDGE_NOT_PRESENT'):
            patch.remove_exact_entries(after)
        after.display_name += '_changed'
        with self.assertRaisesRegex(ValueError, 'EXACT_THREE_EDGE'):
            patch.verify_graph(after)


if __name__ == '__main__':
    unittest.main()
