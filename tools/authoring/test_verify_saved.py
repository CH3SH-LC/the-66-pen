"""Serialized offline fixtures for saved entity + graph acceptance; no game access."""
import importlib.util
import struct
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.gi_file import wrap_payload
from miliastra_agent.core.proto_gen import gia_graph_pb2 as pb

spec = importlib.util.spec_from_file_location('verify_saved_under_test', Path(__file__).with_name('verify_saved.py'))
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
OUT = ROOT / '.runtime/verification/authoring-api-20260923/saved-fixtures'


def varint(n):
    result = bytearray()
    while n > 127:
        result.append((n & 127) | 128)
        n >>= 7
    result.append(n)
    return bytes(result)


def scalar(field, value):
    return varint(field << 3) + varint(value)


def message(field, value):
    return varint((field << 3) | 2) + varint(len(value)) + value


def vector(values):
    return b''.join(varint((axis << 3) | 5) + struct.pack('<f', value)
                    for axis, value in enumerate(values, 1))


def fixture(*, binding=100, text='OFFLINE_ACCEPTANCE', position=(0, 2, 0), edge=True,
            string_pin_kind=3, string_pin_index=0, duplicate_binding=False, version=1):
    graph = pb.NodeGraph()
    graph.identity.runtime_id = 100
    graph.display_name = 'MW_API_fixture'
    event = graph.nodes.add(index=1)
    event.shell_ref.runtime_id = 71
    printer = graph.nodes.add(index=2)
    printer.shell_ref.runtime_id = 1
    pin = printer.pins.add()
    pin.shell_sig.kind = string_pin_kind
    pin.shell_sig.index = string_pin_index
    pin.value.val_string.str = text
    if edge:
        output = event.pins.add()
        output.shell_sig.kind = 2
        output.shell_sig.index = 0
        connection = output.connections.add(target_node_index=2)
        connection.target_pin_shell.kind = 1
        connection.target_pin_shell.index = 0
    transform = b''.join(message(index, vector(values)) for index, values in enumerate(
        (position, (0, 0, 0), (1, 1, 1)), 1))
    component = scalar(1, 1) + message(11, transform)
    refs = message(1, scalar(1, 1) + scalar(2, binding))
    if duplicate_binding:
        refs += refs
    attachment = scalar(1, 3) + message(13, message(1, refs))
    entity = scalar(1, 200) + scalar(8, 300) + message(6, component) + message(6, attachment)
    payload = message(2, b'FixtureOnly') + message(5, message(1, entity))
    payload += message(10, message(1, message(1, graph.SerializeToString())))
    return wrap_payload(payload, file_type=2, version=version)


class SavedReadbackTests(unittest.TestCase):
    def check_fixture(self, label, **options):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / (label + '.gil')
        data = fixture(**options)
        path.write_bytes(data)  # Project-only deterministic test artifacts, never game saves.
        args = SimpleNamespace(gil=path, graph_id=100, name='MW_API_fixture', event_node=1,
            print_node=2, text='OFFLINE_ACCEPTANCE', entity_id=200, template_id=300,
            position=[0, 2, 0], rotation=[0, 0, 0], scale=[1, 1, 1])
        try:
            return verifier.verify(args)
        finally:
            self.assertEqual(path.read_bytes(), data, 'Verifier modified its source fixture')

    def test_accepts_complete_serialized_fixture(self):
        result = self.check_fixture('valid')
        self.assertTrue(result['ok'])
        self.assertEqual(result['edgeCount'], 1)
        self.assertFalse(result['officialPlaytestVerified'])

    def test_rejects_wrong_binding(self):
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.check_fixture('wrong-binding', binding=101)

    def test_rejects_duplicate_binding(self):
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.check_fixture('duplicate-binding', duplicate_binding=True)

    def test_rejects_wrong_text(self):
        with self.assertRaisesRegex(ValueError, 'Print content'):
            self.check_fixture('wrong-text', text='DIFFERENT')

    def test_rejects_wrong_geometry(self):
        with self.assertRaisesRegex(ValueError, 'Geometry mismatch'):
            self.check_fixture('wrong-geometry', position=(0, 2, -50))

    def test_rejects_wrong_string_pin(self):
        with self.assertRaises(ValueError):
            self.check_fixture('wrong-string-pin', string_pin_kind=2, string_pin_index=7)

    def test_rejects_unsupported_version(self):
        with self.assertRaises(ValueError):
            self.check_fixture('unsupported-version', version=99)

    def test_rejects_missing_edge(self):
        with self.assertRaisesRegex(ValueError, 'edge'):
            self.check_fixture('missing-edge', edge=False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
