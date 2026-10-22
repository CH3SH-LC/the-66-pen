"""Replay the verified shop plan and reject the two observed failure classes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from tools.gameplan.modules.runtime_prices import compile_new_graph_prices

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT/'.runtime/scratch/overnight-features-20261013/task-min-shop/runtime-direct-character-reference-plan.json'
R7 = ROOT/'.runtime/scratch/playtest-stall-20261013-2254/validation-schema/r7-reference-plan.json'


class RuntimePriceTests(unittest.TestCase):
    def setUp(self):
        raw = BASE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '9a27273135a835ce4824b069c2f0255766d8884eff16c54885441e45570d286e')
        self.batch = json.loads(raw)

    def test_reproduces_actual_r7_reference(self):
        before = deepcopy(self.batch)
        result = compile_new_graph_prices(self.batch)
        self.assertEqual(result['batch'], json.loads(R7.read_text(encoding='utf-8')))
        self.assertEqual(self.batch, before)
        self.assertFalse(result['runtimeVerified'])
        self.assertFalse(result['existingGraphMigrationSupported'])
        self.assertEqual(result['requiredReadback']['parameterSlotCount'], 2)

    def test_old_residual_and_ambiguous_price_inputs_rejected(self):
        for case in ('connected', 'duplicate', 'wrong_key_type', 'float', 'zero', 'multiple'):
            batch = deepcopy(self.batch)
            row = next(r for r in batch['values'] if (r['node'], r['portIndex']) == (4, 3))
            if case == 'connected':
                batch['edges'].append({'from': 0, 'fromKind': 4, 'fromIndex': 0,
                                      'to': 4, 'toKind': 3, 'toIndex': 3})
            elif case == 'duplicate':
                batch['values'].append(deepcopy(row))
            elif case == 'wrong_key_type':
                row['value']['dict'][0]['key'] = {'int': 1115684865}
            elif case in ('float', 'zero'):
                row['value']['dict'][0]['value']['int'] = 2.5 if case == 'float' else 0
            else:
                row['value']['dict'].append(deepcopy(row['value']['dict'][0]))
            unchanged = deepcopy(batch)
            with self.subTest(case=case), self.assertRaises(ValueError):
                compile_new_graph_prices(batch)
            self.assertEqual(batch, unchanged)

    def test_recompiling_runtime_graph_is_not_a_replay(self):
        compiled = compile_new_graph_prices(self.batch)['batch']
        with self.assertRaisesRegex(ValueError, 'no static shop prices'):
            compile_new_graph_prices(compiled)

    def test_node_limit_preserves_original_on_rejection(self):
        self.batch['nodes'].extend([{'definitionId': 1, 'x': 0, 'y': 0}] * 67)
        before = deepcopy(self.batch)
        with self.assertRaisesRegex(ValueError, 'node limit'):
            compile_new_graph_prices(self.batch)
        self.assertEqual(self.batch, before)


if __name__ == '__main__':
    unittest.main()
