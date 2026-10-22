"""Exact saved Shop field tests, with no game or native invocation."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import saved_shop_source as source
import saved_farming_bindings as saved

g = saved.gil
LEVEL, SHOP = 1073741842, 1136656385


def integer(number, value):
    return g.Field(number, g.WIRE_VARINT, value=value)


def message(number, fields):
    return g.Field(number, g.WIRE_LENGTH, data=g.encode_fields(fields))


def record(config=None, *, subtype=17, property_kind=48, template_id=SHOP):
    config = [integer(1, 1)] if config is None else config
    return [integer(1, template_id), integer(2, subtype),
            message(4, [integer(1, property_kind), message(58, [message(1, config)])])]


class SavedShopSourceTests(unittest.TestCase):
    def setUp(self):
        parent = saved.ROOT / '.runtime/scratch/overnight-features-20261013/task-bh/tests'
        parent.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=parent, prefix='shop-source-')
        self.addCleanup(temp.cleanup)
        self.file = Path(temp.name) / 'synthetic.gil'

    def write(self, records=None, *, level=LEVEL):
        records = [record()] if records is None else records
        root = [integer(1, level), message(15, [message(1, r) for r in records])]
        self.file.write_bytes(g.encode_container(g.Container(g.SUBTYPE_LEVEL, g.encode_fields(root))))

    def read(self):
        return source.read_saved_shop_source(self.file, level_id=LEVEL, shop_template_id=SHOP)

    def test_value_one_is_custom_list_without_claiming_runtime_trade(self):
        self.write()
        before = self.file.read_bytes()
        result = self.read()
        self.assertTrue(result['sourceRead'])
        self.assertTrue(result['sourceFieldPresent'])
        self.assertEqual(result['sourceValue'], 1)
        self.assertEqual(result['sourcePath'], f'root15.f1[id={SHOP}].f4[kind=48].f58.f1.f1')
        self.assertEqual(result['sourceLabel'], 'CustomList')
        self.assertTrue(result['sourceLabelVerified'])
        self.assertTrue(result['customListVerified'])
        self.assertEqual(result['status'], 'custom_list_source_verified')
        for key in ('runtimeTradeVerified', 'runtimeEffectiveVerified',
                    'deploymentReady', 'nativeSaveExecutionVerified', 'gameplayVerified'):
            self.assertFalse(result[key])
        self.assertEqual(self.file.read_bytes(), before)

    def test_omitted_source_is_numeric_zero_not_native_constructor_one(self):
        self.write([record(config=[])])
        result = self.read()
        self.assertEqual(result['sourceValue'], 0)
        self.assertFalse(result['sourceFieldPresent'])
        self.assertTrue(result['sourceRead'])
        self.assertFalse(result['customListVerified'])
        self.assertFalse(result['sourceLabelVerified'])
        self.assertEqual(result['sourceLabel'], 'unknown')

    def test_other_record_property_or_payload_is_not_a_source(self):
        for rows, status in (([record(template_id=SHOP+1)], 'template_absent'),
                             ([record(property_kind=47)], 'property_absent'),
                             ([record(subtype=12)], 'wrong_template_subtype'),
                             ([[integer(1, SHOP), integer(2, 17), message(4, [integer(1, 48),
                                message(57, [message(1, [integer(1, 1)])])])]], 'payload_absent')):
            self.write(rows)
            result = self.read()
            self.assertFalse(result['sourceRead'])
            self.assertEqual(result['status'], status)

    def test_duplicate_record_property_or_source_refuse(self):
        good = record()
        for rows in ([record(), record()], [good + [good[-1]]],
                     [record(config=[integer(1, 1), integer(1, 0)])]):
            self.write(rows)
            with self.assertRaises(saved.SavedBindingError):
                self.read()

    def test_unknown_numeric_value_stays_unknown_and_wrong_wire_refuses(self):
        for raw, expected in ((0, 0), (2, 2), (99, 99), (0xFFFFFFFFFFFFFFFF, -1)):
            self.write([record(config=[integer(1, raw)])])
            result = self.read()
            self.assertEqual(result['sourceValue'], expected)
            self.assertEqual(result['sourceLabel'], 'unknown')
            self.assertFalse(result['customListVerified'])
            self.assertFalse(result['sourceLabelVerified'])
        for fields in ([message(1, [integer(1, 1)])], [integer(1, 0x100000000)]):
            self.write([record(config=fields)])
            with self.assertRaises(saved.SavedBindingError):
                self.read()

    def test_mismatched_level_and_changed_file_refuse(self):
        self.write(level=LEVEL + 1)
        with self.assertRaisesRegex(saved.SavedBindingError, 'embedded level'):
            self.read()
        self.write()
        raw = self.file.read_bytes()
        with patch.object(Path, 'read_bytes', side_effect=[raw, raw + b'x']):
            with self.assertRaisesRegex(saved.SavedBindingError, 'changed while'):
                self.read()

    def test_cli_reports_proven_configuration_only_and_writes_no_files(self):
        self.write()
        before = self.file.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = source.main(['--gil', str(self.file), '--level-id', str(LEVEL),
                                '--shop-template-id', str(SHOP)])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(result['sourceRead'])
        self.assertTrue(result['sourceLabelVerified'])
        self.assertTrue(result['customListVerified'])
        self.assertFalse(result['runtimeTradeVerified'])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])


if __name__ == '__main__':
    unittest.main()
