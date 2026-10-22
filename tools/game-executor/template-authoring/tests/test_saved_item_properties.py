"""Synthetic save fixtures, not native execution or persistence evidence."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import saved_item_properties as reader
import saved_farming_bindings as saved

g = saved.gil
LEVEL, SEED, CROP = 1073741842, 1107296257, 1107296258
NAMES = {SEED: "田园种子", CROP: "新鲜作物"}


def integer(number, value):
    return g.Field(number, g.WIRE_VARINT, value=value)


def message(number, fields):
    return g.Field(number, g.WIRE_LENGTH, data=g.encode_fields(fields))


def record(item_id, name, *, data=None, subtype=9):
    if data is None:
        data = [message(1, [integer(1, 9999)]), message(3, [integer(2, 1)])]
    return [integer(1, item_id), integer(2, subtype),
            message(4, [integer(1, 1), message(11, [g.Field(1, g.WIRE_LENGTH, data=name.encode())])]),
            message(4, [integer(1, 39), message(49, [message(1, data)])])]


class SavedItemPropertiesTests(unittest.TestCase):
    def setUp(self):
        folder = saved.ROOT / '.runtime/scratch/overnight-features-20261013/task-saved-items/tests'
        folder.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=folder, prefix='synthetic-')
        self.addCleanup(temp.cleanup)
        self.file = Path(temp.name) / 'synthetic.gil'

    def write(self, records=None, level=LEVEL):
        if records is None:
            records = [record(item_id, name) for item_id, name in NAMES.items()]
        root = [integer(1, level), message(15, [message(1, r) for r in records])]
        self.file.write_bytes(g.encode_container(g.Container(g.SUBTYPE_LEVEL, g.encode_fields(root))))

    def read(self):
        return reader.read_saved_item_properties(self.file, level_id=LEVEL, expected_items=NAMES)

    def test_two_items_exact_names_trade_and_stack_read_only(self):
        self.write()
        before = self.file.read_bytes()
        result = self.read()
        self.assertTrue(result['savedPropertiesVerified'])
        self.assertEqual([r['name'] for r in result['items']], list(NAMES.values()))
        for item in result['items']:
            self.assertTrue(item['isTradeable'])
            self.assertEqual(item['stackLimit'], 9999)
        for key in ('nativeSaveExecutionVerified', 'reopenVerified', 'runtimeEffectiveVerified', 'gameplayVerified'):
            self.assertFalse(result[key])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])

    def test_omitted_scalars_are_zero_not_editor_defaults(self):
        self.write([record(SEED, NAMES[SEED], data=[message(1, []), message(3, [])])])
        item = self.read()['items'][0]
        self.assertTrue(item['propertiesRead'])
        self.assertFalse(item['isTradeable'])
        self.assertEqual(item['stackLimit'], 0)
        self.assertFalse(item['isTradeableFieldPresent'])
        self.assertFalse(item['savedPropertiesVerified'])

    def test_runtime_export_fields_are_not_saved_editor_fields(self):
        # Runtime normal.f2 stack and common.f9 trade must not pass this checker.
        self.write([record(SEED, NAMES[SEED], data=[message(1, [integer(9, 1)]), integer(2, 9999)])])
        item = self.read()['items'][0]
        self.assertFalse(item['propertiesRead'])
        self.assertEqual(item['status'], 'basic_or_inter_info_absent')

    def test_absent_wrong_kind_or_name_do_not_match(self):
        for rows, status in (([], 'template_absent'),
                             ([record(SEED, NAMES[SEED], subtype=11)], 'wrong_template_subtype'),
                             ([record(SEED, '别的名称')], 'saved_properties_mismatch'),
                             ([record(SEED, NAMES[SEED])[:-1]], 'property_absent')):
            self.write(rows)
            result = self.read()
            self.assertFalse(result['savedPropertiesVerified'])
            self.assertEqual(result['items'][0]['status'], status)

    def test_duplicate_record_property_and_scalar_refuse(self):
        good = record(SEED, NAMES[SEED])
        for rows in ([good, good], [good + [good[-1]]],
                     [record(SEED, NAMES[SEED], data=[message(1, [integer(1, 9999), integer(1, 4)]),
                                                    message(3, [integer(2, 1)])])]):
            self.write(rows)
            with self.assertRaises(saved.SavedBindingError):
                self.read()

    def test_malformed_trade_or_stack_refuse(self):
        for basic, inter in (([integer(1, 9999)], [integer(2, 2)]),
                             ([integer(1, 0x100000000)], [integer(2, 1)]),
                             ([message(1, [])], [integer(2, 1)])):
            self.write([record(SEED, NAMES[SEED], data=[message(1, basic), message(3, inter)])])
            with self.assertRaises(saved.SavedBindingError):
                self.read()

    def test_mismatched_level_and_concurrent_save_refuse(self):
        self.write(level=LEVEL + 1)
        with self.assertRaisesRegex(saved.SavedBindingError, 'embedded level'):
            self.read()
        self.write()
        raw = self.file.read_bytes()
        with patch.object(Path, 'read_bytes', side_effect=[raw, raw + b'x']):
            with self.assertRaisesRegex(saved.SavedBindingError, 'changed while'):
                self.read()

    def test_cli_success_and_mismatch_exit_status(self):
        self.write()
        args = ['--gil', str(self.file), '--level-id', str(LEVEL),
                '--item', str(SEED), NAMES[SEED], '--item', str(CROP), NAMES[CROP]]
        for suffix, expected in (([], 0), (['--stack-limit', '10'], 2)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = reader.main(args + suffix)
            self.assertEqual(code, expected)
            self.assertEqual(json.loads(out.getvalue())['savedPropertiesVerified'], expected == 0)


if __name__ == '__main__':
    unittest.main()
