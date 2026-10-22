from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('vector_values', Path(__file__).with_name('vector_values.py'))
vv = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vv
spec.loader.exec_module(vv)
from tools.authoring import author
from tools.gameplan import paramtypes
from tools.gameplan.builder import GraphBuilder, _tagged
from tools.gameplan.plan import GraphPlan, PlanError


class VectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT / '.runtime/graph-vector-values/tests'
        base.mkdir(parents=True, exist_ok=True)
        cls.directory = tempfile.TemporaryDirectory(dir=base)
        cls.work = Path(cls.directory.name)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def expected(self):
        return {'name': 'MW_API_vector_test', 'graphId': 1073741900,
                'values': [{'nodeId': 17, 'definitionId': 244, 'portIndex': 1, 'vector3': [1.125, -2.75, 0.0]}]}

    def setUp(self):
        self.out_patch = patch.object(vv, 'OUT', self.work / self._testMethodName)
        self.out_patch.start()
        self.addCleanup(self.out_patch.stop)

    def gia(self, *, storage=7, server=12, node=17, definition=244, graph=1073741900,
            axes=None, duplicate_axis=False, connected=False, is_set=1, extra_storage=False,
            name='MW_API_vector_test'):
        c = vv.codec()
        def var(n, v): return c.Field(n, 0, value=v)
        def msg(n, fs): return c.Field(n, 2, data=c.encode_fields(fs))
        def txt(n, s): return c.Field(n, 2, data=s.encode())
        coords = [1.125, -2.75, 0] if axes is None else axes
        vec = [c.Field(i+1, 5, value=vv.bits(x)) for i, x in enumerate(coords) if x != 0 or vv.bits(x)]
        if duplicate_axis: vec.append(c.Field(1, 5, value=vv.bits(coords[0])))
        value = [var(1, storage), var(2, is_set), msg(4, [var(1, 1), msg(100, [var(1, server)])]), msg(107, [msg(1, vec)])]
        if extra_storage: value.append(msg(104, [c.Field(1, 5, value=0)]))
        pin = [msg(1, [var(1, 3), var(2, 1)]), msg(3, value), var(4, server)]
        if connected: pin.append(msg(5, [var(1, 18)]))
        graph_fields = [msg(1, [var(2, 20000), var(5, graph)]),
                        msg(3, [var(1, node), msg(2, [var(5, definition)]), msg(4, pin)])]
        resource = [txt(3, name), var(5, 9), msg(13, [msg(1, [msg(1, graph_fields)])])]
        payload = c.encode_fields([msg(1, resource)])
        blob = struct.pack('>5I', len(payload)+20, 1, 0x326, 3, len(payload))+payload+struct.pack('>I', 0x679)
        p = self.work / 'export.gia'
        p.write_bytes(blob)
        return p

    def test_type_domains(self):
        self.assertEqual(paramtypes.VECTOR3, 12)
        self.assertEqual(paramtypes.POSITION, 12)
        self.assertEqual(paramtypes.VECTOR3_STORAGE, 7)
        self.assertEqual(paramtypes.slot_for(12), 'vector3')
        self.assertIsNone(paramtypes.slot_for(7))

    def test_payload_valid(self):
        for xyz in ([1, 2, 3], [-1e9, 0, 1e9], [0.1, -0.0, -1e-10]):
            author.validate_scalar_payload({'vector3': xyz})
            self.assertEqual(json.loads(_tagged('vector3', xyz)), {'vector3': xyz})
            self.assertEqual(json.loads(_tagged('auto', {'vector3': xyz})), {'vector3': xyz})

    def test_payload_rejections(self):
        for xyz in ([], [1, 2], [1, 2, 3, 4], [True, 2, 3], [None, 2, 3], ['1', 2, 3],
                    [float('nan'), 1, 2], [float('inf'), 1, 2], [1e10, 1, 2], {'x': 1, 'y': 2, 'z': 3}):
            with self.subTest(xyz=xyz), self.assertRaises(ValueError):
                author.validate_scalar_payload({'vector3': xyz})

    def test_batch_preflight(self):
        row = dict(nodeId=17, definitionId=244, portKind=3, portIndex=1,
                   expect=dict(serverParamType=12, genericId=12), slot='vector3', value={'vector3': [1, 2, 3]})
        author.validate_value_batch([row])
        for update in ({'expect': dict(serverParamType=7, genericId=7)}, {'slot': 'float'}, {'value': {'float': 4}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                author.validate_value_batch([dict(row, **update)])

    def test_vector_dispatch_requires_loaded_revision_before_request_write(self):
        command = dict(runId='00000000-0000-4000-8000-000000000001',
                       payload={'value': {'vector3': [1, 2, 3]}})
        with patch.object(author, 'require_compatible'), patch.object(author, 'powershell_host'), \
                patch.object(author, 'lease', return_value=self.work), \
                patch.object(author, 'exclusive_json', side_effect=AssertionError('Must not write request')), \
                patch.object(author, 'process_json', side_effect=AssertionError('Must not dispatch')):
            with self.assertRaisesRegex(ValueError, 'VECTOR_RUN_PATH_INVALID'):
                author.graph_call(command, 'request', self.work)

    def test_plan_and_batched_real_contract(self):
        plan = GraphPlan('MW_API_vector_test')
        plan.add('distance', 244)
        plan.vector3_const('distance', 1, [1.125, -2.75, 0])
        plan.validate()
        builder = GraphBuilder(plan, lambda argv: self.fail('offline preparation must not dispatch'), run_id='00000000-0000-4000-8000-000000000001')
        self.assertEqual(builder.batch_plan_json()['values'][0]['value'], {'vector3': [1.125, -2.75, 0]})

    def test_wrong_port_and_slot(self):
        for definition, port, slot in ((225, 0, 'vector3'), (244, 1, 'float')):
            p = GraphPlan('MW_API_vector_test')
            p.add('n', definition)
            p.const('n', port, {'vector3': [1, 2, 3]}, slot)
            with self.assertRaises(PlanError): p.validate()

    def test_writer_does_not_enable_vector_containers(self):
        for value in ({'list': [{'vector3': [1, 2, 3]}]}, {'dict': [{'key': {'int': 1}, 'value': {'vector3': [1, 2, 3]}}]}):
            with self.assertRaises(ValueError): author.validate_scalar_payload(value)

    def test_raw_export_all_axes(self):
        result = vv.verify_export(self.gia(), self.expected())
        self.assertTrue(result['ok'])
        self.assertEqual(result['verifiedValues'][0]['float32Bits'], [vv.bits(1.125), vv.bits(-2.75), 0])
        self.assertFalse(result['runtimeVerified'])
        self.assertFalse(result['persistentSaveVerified'])

    def test_export_identity_and_structure_rejections(self):
        mutations = [dict(storage=12), dict(server=7), dict(node=18), dict(definition=99), dict(graph=99),
                     dict(axes=[1.125, -2.7501, 0]), dict(duplicate_axis=True), dict(connected=True),
                     dict(is_set=0), dict(extra_storage=True), dict(name='MW_API_wrong')]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                vv.verify_export(self.gia(**change), self.expected())

    def test_export_negative_zero_is_bit_exact(self):
        expected = self.expected()
        expected['values'][0]['vector3'][2] = -0.0
        with self.assertRaises(ValueError): vv.verify_export(self.gia(), expected)
        self.assertTrue(vv.verify_export(self.gia(axes=[1.125, -2.75, -0.0]), expected)['ok'])

    def test_duplicate_expected_rejected(self):
        value = self.expected()
        value['values'] *= 2
        with self.assertRaises(ValueError): vv.expectation(value)

    def test_prepare_no_dispatch_and_card_tamper(self):
        args = type('Args', (), dict(run_id='00000000-0000-4000-8000-000000000001',
            name='MW_API_vector_test', graph_id=1073741900, node_id=17, definition_id=244,
            port_index=1, xyz=[1.125, -2.75, 0], elevated_queue=None))()
        with patch.object(vv.subprocess, 'run', side_effect=AssertionError('must not dispatch')):
            result = vv.prepare(args)
        path, card = vv.load_card(result['prepared'])
        self.assertFalse(result['executed'])
        self.assertFalse((path.parent / 'attempt.used').exists())
        card['expected']['values'][0]['vector3'][0] = 999
        vv.dump(path, card)
        with self.assertRaises(ValueError): vv.load_card(path)

    def test_single_attempt_unknown_never_replayed(self):
        args = type('Args', (), dict(run_id='00000000-0000-4000-8000-000000000001',
            name='MW_API_vector_test', graph_id=1073741900, node_id=17, definition_id=244,
            port_index=1, xyz=[1, 2, 3], elevated_queue=None))()
        result = vv.prepare(args)
        with patch.object(vv.subprocess, 'run', side_effect=vv.subprocess.TimeoutExpired('fixture-only', 180)) as runner:
            self.assertTrue(vv.dispatch(result['prepared'])['outcomeUncertain'])
            with self.assertRaises(FileExistsError): vv.dispatch(result['prepared'])
            self.assertEqual(runner.call_count, 1)


if __name__ == '__main__':
    unittest.main()
