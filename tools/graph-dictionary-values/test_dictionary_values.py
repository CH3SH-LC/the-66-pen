"""Offline boundary checks. Positive GIA fixtures are synthetic, never live proof."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import dictionary_values as d

W = d.codec()
HISTORICAL = d.ROOT / '.runtime/editor-bridge/exports/miliastra-bridge-552dc8ed-2648-4922-98e5-5bf233ad22a1/bridge-export-5684064648b944c9b4373e7e3d34f378.gia'
HISTORICAL_SHA = '8472a61f0e9c1b7cb0ffa7904a27393d39d3776d3a73585d77456545c6e00dc7'


def n(index, value):
    return W.Field(index, 0, value=value & ((1 << 64) - 1))


def m(index, fields):
    return W.Field(index, 2, data=W.encode_fields(fields))


def s(index, value):
    return W.Field(index, 2, data=value.encode())


def td(server, pair=False, key=20, value=3):
    fields = [n(1, server)]
    if pair:
        fields += [n(2, 2), m(101, [n(1, key), n(2, value), n(4, 1), n(5, 1)])]
    return m(4, [n(1, 1), m(100, fields)])


def scalar(storage, server, value, *, is_set=True, duplicate=False):
    payload = [] if value == 0 else [n(1, value)]
    if duplicate:
        payload += [n(1, value)]
    return [n(1, storage), n(2, int(is_set)), td(server), m(101 if storage == 1 else 102, payload)]


def fixture(*, pairs=None, connection=False, key_binding=20, pair_binding=20,
            key_server=20, value_server=3, entry_set=True, leaf_set=True,
            entry_storage=10007, duplicate_scalar=False, duplicate_node=False,
            duplicate_pin=False, extra_oneof=False, kernel_def=708, kernel_port=3,
            dictionary_set=True, graph_id=1073741900, graph_name='synthetic-price-dict'):
    if pairs is None:
        pairs = [(1115684865, 12)]
    entries = []
    for key, value in pairs:
        entries.append(m(1, [n(1, entry_storage), n(2, int(entry_set)),
            td(25, True, pair_binding), m(111, [
                m(1, scalar(1, key_server, key, is_set=leaf_set, duplicate=duplicate_scalar)),
                m(2, scalar(2, value_server, value, is_set=leaf_set))])]))
    typed = [n(1, 10003), n(2, int(dictionary_set)), td(27, True, key_binding), m(112, entries)]
    if extra_oneof:
        typed += [m(101, [n(1, 5)])]
    pin = [m(1, [n(1, 3), n(2, 3)]), m(2, [n(1, 3), n(2, kernel_port)]), m(3, typed), n(4, 27)]
    if connection:
        pin += [m(5, [n(1, 2)])]
    node = [n(1, 7), m(2, [n(5, 708)]), m(3, [n(5, kernel_def)]), m(4, pin)]
    if duplicate_pin:
        node += [m(4, pin)]
    graph = [m(1, [n(1, 10000), n(2, 20000), n(5, graph_id)]), s(2, graph_name), m(3, node)]
    if duplicate_node:
        graph += [m(3, node)]
    resource = [s(3, graph_name), n(5, 9), m(13, [m(1, [m(1, graph)])])]
    return W.encode_container(W.Container(3, W.encode_fields([m(1, resource)])))


def expected(pairs=None):
    if pairs is None:
        pairs = [(1115684865, 12)]
    return {'graphId': 1073741900, 'name': 'synthetic-price-dict', 'values': [
        {'nodeId': 7, 'definitionId': 708, 'portIndex': 3,
         'keyServerType': 20, 'valueServerType': 3,
         'dict': [{'key': {'uint': k}, 'value': {'int': v}} for k, v in pairs]}]}


class DictionaryExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = d.ROOT / '.runtime/gdt'
        root.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='check-', dir=root)
        cls.directory = Path(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def write(self, payload):
        path = self.directory / 'synthetic.gia'
        path.write_bytes(payload)
        return path

    def test_exact_price_constant(self):
        result = d.verify_export(self.write(fixture()), expected())
        self.assertTrue(result['constantValuesVerified'])
        for key in ('runtimeVerified', 'persistentSaveVerified', 'levelIdentityVerified', 'genericIdVerifiedFromExport'):
            self.assertFalse(result[key])

    def test_scalar_boundaries_and_omitted_protobuf_zero(self):
        values = [(0, 0), (0xFFFFFFFF, -(1 << 31)), (1, (1 << 31) - 1)]
        result = d.verify_export(self.write(fixture(pairs=values)), expected(values))
        self.assertEqual(result['verifiedValues'][0]['dict'], expected(values)['values'][0]['dict'])

    def test_full_64_entry_capacity(self):
        pairs = [(i, -i) for i in range(64)]
        self.assertTrue(d.verify_export(self.write(fixture(pairs=pairs)), expected(pairs))['ok'])

    def test_historical_original_is_observation_not_clean_acceptance(self):
        self.assertEqual(hashlib.sha256(HISTORICAL.read_bytes()).hexdigest(), HISTORICAL_SHA)
        actual = d.inspect_export(HISTORICAL)
        pin = actual['dictionaries'][0]
        self.assertEqual((pin['storageKind'], pin['serverParamType'], pin['keyServerType'], pin['valueServerType']), (10003, 27, 20, 3))
        self.assertEqual(pin['inputConnectionCount'], 1)
        self.assertEqual(len(pin['pairs']), 2)
        self.assertEqual(pin['pairs'][0]['isValueSet'], 0)
        self.assertEqual(pin['pairs'][1]['key']['tagged'], {'uint': 1})
        self.assertEqual(pin['pairs'][1]['value']['tagged'], {'int': 10})
        want = expected([(1, 10)])
        want.update(graphId=1073741834, name='MW_API_DICTKIND_PROBE')
        want['values'][0].update(nodeId=1, definitionId=704, portIndex=4)
        with self.assertRaisesRegex(ValueError, 'INPUT_CONNECTION'):
            d.verify_export(HISTORICAL, want)

    def test_native_bad_states_are_rejected(self):
        cases = [
            ({'connection': True}, 'INPUT_CONNECTION'),
            ({'pairs': [(0, 0), (1115684865, 12)]}, 'CARDINALITY'),
            ({'pairs': []}, 'CARDINALITY'),
            ({'key_binding': 3}, 'KEY_VALUE_BINDING'),
            ({'pair_binding': 3}, 'ENTRY_DESCRIPTOR'),
            ({'key_server': 3}, 'LEAF_DESCRIPTOR'),
            ({'value_server': 20}, 'LEAF_DESCRIPTOR'),
            ({'entry_set': False}, 'ENTRY_DESCRIPTOR'),
            ({'leaf_set': False}, 'LEAF_DESCRIPTOR'),
            ({'dictionary_set': False}, 'TYPE_OR_UNSET'),
            ({'entry_storage': 10002}, 'ENTRY_DESCRIPTOR'),
            ({'duplicate_scalar': True}, 'FIELD_INVALID'),
            ({'duplicate_node': True}, 'DUPLICATE_NODE'),
            ({'duplicate_pin': True}, 'DUPLICATE_PIN'),
            ({'extra_oneof': True}, 'UNKNOWN_FIELD'),
            ({'kernel_def': 710}, 'NODE_OR_PIN_IDENTITY'),
            ({'kernel_port': 4}, 'NODE_OR_PIN_IDENTITY'),
            ({'graph_id': 1073741901}, 'GRAPH_IDENTITY'),
            ({'graph_name': 'wrong'}, 'GRAPH_IDENTITY'),
            ({'pairs': [(1115684865, 13)]}, 'EXACT_PAIRS_MISMATCH'),
            ({'pairs': [(1115684865, 1 << 31)]}, 'INT32_RANGE'),
            ({'pairs': [(1 << 32, 12)]}, 'UINT32_RANGE'),
        ]
        for options, error in cases:
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, error):
                d.verify_export(self.write(fixture(**options)), expected())

    def test_duplicate_keys_are_not_a_dictionary_match(self):
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_KEY'):
            d.verify_export(self.write(fixture(pairs=[(2, 12), (2, 12)])), expected([(2, 12), (3, 12)]))

    def test_pair_order_is_exact(self):
        with self.assertRaisesRegex(ValueError, 'EXACT_PAIRS_MISMATCH'):
            d.verify_export(self.write(fixture(pairs=[(2, 12), (1, 12)])), expected([(1, 12), (2, 12)]))

    def test_expectations_reject_guessing_and_untyped_keys(self):
        mutations = [
            lambda x: x['values'][0].update(keyServerType=3),
            lambda x: x['values'][0].update(valueServerType=5),
            lambda x: x['values'][0].update(genericId=27),
            lambda x: x['values'][0].update(dict=[]),
            lambda x: x['values'][0].update(dict=expected([(1, 1)] * 65)['values'][0]['dict']),
            lambda x: x['values'][0]['dict'][0].update(key={'int': 1}),
            lambda x: x['values'][0]['dict'][0].update(key={'uint': True}),
            lambda x: x['values'][0]['dict'][0].update(value={'int': 1 << 31}),
            lambda x: x['values'][0].update(dict=expected([(1, 1), (1, 2)])['values'][0]['dict']),
            lambda x: x['values'].append(copy.deepcopy(x['values'][0])),
        ]
        for mutation in mutations:
            value = expected()
            mutation(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                d.expectation(value)

    def test_cli_paths_are_root_relative_and_output_cannot_overwrite(self):
        gia = self.write(fixture())
        expect = self.directory / 'expect.json'
        expect.write_text(json.dumps(expected()), encoding='utf-8')
        output = self.directory / 'receipt.json'
        argv = [sys.executable, '-B', str(Path(d.__file__)), 'verify-export',
                '--gia', str(gia.relative_to(d.ROOT)), '--expect-file', str(expect.relative_to(d.ROOT)),
                '--output', str(output.relative_to(d.ROOT))]
        result = subprocess.run(argv, cwd=self.directory, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = output.read_bytes()
        result = subprocess.run(argv, cwd=self.directory, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(output.read_bytes(), receipt)


if __name__ == '__main__':
    unittest.main()
