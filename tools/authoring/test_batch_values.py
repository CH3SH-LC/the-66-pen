"""Offline batch contract and journal checks; no lease or live transport."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import author


class BatchValuesTests(unittest.TestCase):
    def setUp(self):
        scratch = author.ROOT / '.runtime/scratch/offline-farming-20261014/batch-values-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.source = self.folder / 'values.json'
        self.item = dict(nodeId=9017, definitionId=22, portKind=3, portIndex=1,
                         expect=dict(serverParamType=6, genericId=6), slot='string',
                         value={'string': 'MW_SEED_BEFORE'})
        self.argv = ['graph', 'values', '--request-id', 'batch-test', '--run-id',
                     '12345678-1234-1234-1234-123456789abc', '--name', 'MW_API_test',
                     '--graph-id', '1073741836', '--expected-node-count', '93',
                     '--values-file', str(self.source)]

    def command(self, values=None):
        self.source.write_text(json.dumps(values or [self.item]), encoding='utf-8')
        return author.command_from_args(author.parser().parse_args(self.argv))

    def test_native_identity_and_mutation_payload(self):
        command = self.command()
        self.assertTrue(command['mutating'])
        self.assertEqual(command['payload'], dict(action='set-values', name='MW_API_test',
                         graphId=1073741836, expectedNodeCount=93, values=[self.item]))

    def test_all_32_allowed(self):
        values = [dict(self.item, nodeId=1000+i) for i in range(32)]
        self.assertEqual(len(self.command(values)['payload']['values']), 32)

    def test_count_duplicate_and_closed_shapes(self):
        invalid = [[], [self.item]*33, [self.item, self.item], [dict(self.item, node=0)],
                   [dict(self.item, definitionId=0)], [dict(self.item, nodeId=True)],
                   [dict(self.item, portKind=4)], [dict(self.item, portIndex=2**31)],
                   [dict(self.item, expect={'serverParamType': 6})],
                   [dict(self.item, expect=dict(self.item['expect'], ignored=4))],
                   [dict(self.item, slot='auto-guess')]]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                author.validate_value_batch(values)

    def test_nested_bounds_and_slot_mismatch(self):
        bad = [('int', {'int': 2**31}), ('float', {'list': [{'float': 1e10}]}),
               ('string', {'string': '\U0001f600'*513}), ('enum', {'bool': True}),
               ('uint', {'list': [{'float': 10.0}]}),
               ('auto', {'dict': [{'key': {'int': 1}, 'value': {'int': -(2**31)-1}}]})]
        for slot, value in bad:
            with self.subTest(slot=slot, value=value), self.assertRaises(ValueError):
                author.validate_value_batch([dict(self.item, slot=slot, value=value)])

    def test_timer_float_list_and_mixed_auto_dict_valid(self):
        author.validate_value_batch([dict(self.item, slot='float', value={'list': [{'float': 10.0}]})])
        author.validate_value_batch([dict(self.item, slot='auto', value={'dict': [
            {'key': {'uint': 1107296257}, 'value': {'int': -1}}]})])

    def test_duplicate_json_keys_refused(self):
        self.source.write_text(json.dumps([self.item]).replace('"nodeId": 9017', '"nodeId": 9017, "nodeId": 3'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_JSON_FIELD'):
            author.command_from_args(author.parser().parse_args(self.argv))

    def test_size_bound_rejects_32_large_strings(self):
        values = [dict(self.item, nodeId=1000+i, value={'string': 'x'*1024}) for i in range(32)]
        with self.assertRaisesRegex(ValueError, 'REQUEST_TOO_LARGE'):
            self.command(values)

    def test_expected_node_count_required(self):
        self.source.write_text(json.dumps([self.item]), encoding='utf-8')
        for count in (0, 129):
            args = copy.copy(self.argv)
            args[args.index('--expected-node-count')+1] = str(count)
            with self.assertRaisesRegex(ValueError, 'Expected node count'):
                author.command_from_args(author.parser().parse_args(args))

    def test_partial_failure_is_cached_and_not_replayed(self):
        command = self.command()
        calls = []
        def transport(cmd):
            calls.append(cmd)
            return dict(ok=False, completedIndices=[0], failedIndex=1, outcomeUncertain=True,
                        completed=[{'index': 0, 'readback': 'MW_SEED_BEFORE'}])
        with patch.object(author, 'require_compatible', return_value={'ok': True}), \
             patch.object(author, 'emit_run_receipt', return_value=None):
            first = author.execute(command, 'batch-test', journal=self.folder/'journal', transport=transport)
            second = author.execute(command, 'batch-test', journal=self.folder/'journal', transport=transport)
        self.assertEqual(len(calls), 1)
        self.assertEqual(first['backend']['completedIndices'], [0])
        self.assertTrue(first['outcomeUncertain'])
        self.assertFalse(first['retryAttempted'])
        self.assertTrue(second['replayed'])

    def test_preflight_refusal_is_known_no_write(self):
        with patch.object(author, 'require_compatible', return_value={'ok': True}), \
             patch.object(author, 'emit_run_receipt', return_value=None):
            result = author.execute(self.command(), 'refused', journal=self.folder/'journal', transport=lambda _: dict(
                ok=False, completedIndices=[], failedIndex=3, outcomeUncertain=False))
        self.assertFalse(result['outcomeUncertain'])
        self.assertEqual(result['backend']['completedIndices'], [])


if __name__ == '__main__':
    unittest.main()
