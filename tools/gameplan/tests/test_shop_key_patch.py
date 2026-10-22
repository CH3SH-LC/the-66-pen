"""Real R7 export/save are baseline evidence, never a synthetic deployment."""
import json
import unittest
from tools.gameplan.demo import shop_key_patch as patch


class ShopKeyPatchTests(unittest.TestCase):
    def test_real_r7_export_and_saved_graph_agree_and_patch_is_exact(self):
        before = patch._baseline()
        after = patch.expected_patched_graph()
        request = patch.prepare_patch()
        self.assertEqual(request['beforeShape'], [62, 82, 63])
        self.assertEqual(request['afterShape'], [62, 80, 63])
        self.assertFalse(request['dispatchable'])
        self.assertFalse(patch.verify_patch_export(patch.BASE_GIA)['ok'])
        self.assertTrue(patch.verify_patch_graph(after)['ok'])
        nodes = {n.index: n for n in after.nodes}
        for source, output, target in patch.DISCONNECT:
            self.assertEqual(len(patch._pin(nodes[source], 2, output).connections), 0)
            original = next(n for n in before.nodes if n.index == source)
            patch._pin(nodes[source], 2, output).CopyFrom(patch._pin(original, 2, output))
        self.assertEqual(after.SerializeToString(), before.SerializeToString())

    def test_prices_counts_starter_and_other_nodes_byte_preserved(self):
        before = patch._baseline()
        after = patch.expected_patched_graph()
        for a, b in zip(before.nodes, after.nodes):
            if a.index not in (41, 44):
                self.assertEqual(a.SerializeToString(), b.SerializeToString())
        for index in (61, 62):
            self.assertEqual(patch._pin(after.nodes[index-1], 3, 0).value.val_int.int, 2)
        for index in (5, 6):
            self.assertFalse(patch._pin(after.nodes[index-1], 3, 3).HasField('value'))
        # A changed price must fail the full-byte acceptance, even after correct disconnections.
        price = patch._pin(after.nodes[60], 3, 2).value.val_poly.actual_value
        price.val_int.int = 3
        self.assertFalse(patch.verify_patch_graph(after)['ok'])

    def test_player_candidate_compiles_offline_and_is_below_request_limit(self):
        compiled = patch.compile_player_plan(101)
        self.assertLess(len(json.dumps(compiled, separators=(',', ':')).encode()), 16000)
        definitions = [n['definitionId'] for n in compiled['nodes']]
        self.assertEqual(definitions.count(316), 1)
        self.assertEqual(definitions.count(702), 1)
        self.assertNotIn(688, definitions)
        self.assertNotIn(708, definitions)
        self.assertNotIn(710, definitions)
        self.assertTrue(any(v['value'] == {'uint': patch.SHOP_ENTITY_ID} for v in compiled['values']))


if __name__ == '__main__':
    unittest.main()
