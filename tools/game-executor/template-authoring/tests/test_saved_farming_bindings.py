"""Synthetic GIL structures, not native save or gameplay evidence."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import saved_farming_bindings as check

g = check.gil
LEVEL, ROLE, PLOT = 1073741842, 1090519041, 1077936129
BAG, SHOP = 1119879169, 1136656385
ARGS = dict(level_id=LEVEL, character_id=ROLE, plot_id=PLOT,
            bag_template_id=BAG, shop_template_id=SHOP)


def scalar(number, value):
    return g.Field(number, g.WIRE_VARINT, value=value)


def message(number, fields):
    return g.Field(number, g.WIRE_LENGTH, data=g.encode_fields(fields))


def reference(template_id, classification=1):
    return [scalar(1, classification), scalar(2, template_id)]


def bag(template_id=BAG, enabled=1, classification=1):
    return [scalar(1, 33), scalar(2, enabled),
            message(44, [message(1, reference(template_id, classification)),
                         message(3, [message(1, [scalar(2, 999)])])])]


def shop(template_id=SHOP, index=7, extra=None):
    entries = [message(1, [scalar(1, index), message(2, reference(template_id))])]
    if extra:
        entries.append(message(1, extra))
    return [scalar(1, 35), scalar(2, 1), message(46, entries)]


def fixture(template_bag=None, instance_bag=None, plot_shop=None):
    template_bag = bag() if template_bag is None else template_bag
    instance_bag = bag() if instance_bag is None else instance_bag
    plot_shop = shop() if plot_shop is None else plot_shop
    template = [scalar(1, ROLE), scalar(2, 1000001)]
    instance = [scalar(1, ROLE), message(2, [scalar(1, ROLE)]), scalar(8, 1000001)]
    plot = [scalar(1, PLOT), scalar(8, 20010005)]
    if template_bag:
        template.append(message(8, template_bag))
    if instance_bag:
        instance.append(message(7, instance_bag))
    if plot_shop:
        plot.append(message(7, plot_shop))
    return [scalar(1, LEVEL), message(2, []),
            message(4, [message(1, template)]),
            message(5, [message(1, instance), message(1, plot)])]


class SavedFarmingBindingsTests(unittest.TestCase):
    def setUp(self):
        parent = check.ROOT / '.runtime/scratch/overnight-features-20261013/task-bg/tests'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent, prefix='saved-')
        self.addCleanup(temporary.cleanup)
        self.file = Path(temporary.name) / 'synthetic.gil'

    def write(self, fields, subtype=g.SUBTYPE_LEVEL):
        self.file.write_bytes(g.encode_container(g.Container(subtype, g.encode_fields(fields))))

    def read(self, **changes):
        return check.validate_saved_bindings(self.file, **dict(ARGS, **changes))

    def test_structural_success_reports_native_index_and_unknown_runtime(self):
        self.write(fixture())
        original = self.file.read_bytes()
        result = self.read()
        self.assertTrue(result['savedBindingsVerified'])
        self.assertTrue(result['characterLink']['verified'])
        self.assertEqual(result['plotShop']['matchingShopIndices'], [7])
        self.assertEqual(result['characterTemplateBag']['reference']['templateId'], BAG)
        self.assertEqual(result['characterInstanceBag']['reference']['templateId'], BAG)
        self.assertEqual(result['file']['sha256'], hashlib.sha256(original).hexdigest())
        for key in ('runtimeEffectiveVerified', 'gameplayVerified', 'nativeSaveExecutionVerified',
                    'reopenVerified', 'triggerBindingsChecked', 'templateDefinitionsChecked'):
            self.assertFalse(result[key])
        self.assertEqual(self.file.read_bytes(), original)

    def test_instance_only_does_not_claim_template_sync(self):
        self.write(fixture(template_bag=[]))
        result = self.read()
        self.assertFalse(result['savedReferencesVerified'])
        self.assertEqual(result['characterTemplateBag']['status'], 'component_absent')
        self.assertTrue(result['characterInstanceBag']['referenceMatches'])
        self.assertTrue(result['plotShop']['referenceMatches'])

    def test_id_in_inline_contents_or_wrong_component_group_is_not_binding(self):
        wrong_bag = [scalar(1, 33), scalar(2, 1),
                     message(44, [message(3, [message(1, reference(BAG))])])]
        fields = fixture(template_bag=wrong_bag)
        # root4.f7 is the parameter list, not the component list.
        records = g.parse_fields(fields[2].data)
        role = g.parse_fields(records[0].data)
        role.append(message(7, bag()))
        fields[2] = message(4, [message(1, role)])
        fields.append(message(99, reference(BAG)))
        self.write(fields)
        result = self.read()
        self.assertFalse(result['savedBindingsVerified'])
        self.assertEqual(result['characterTemplateBag']['status'], 'reference_absent')

    def test_other_entity_shop_does_not_satisfy_requested_plot(self):
        fields = fixture(plot_shop=[])
        instances = g.parse_fields(fields[3].data)
        instances.append(message(1, [scalar(1, PLOT + 1), message(7, shop())]))
        fields[3] = message(5, instances)
        self.write(fields)
        result = self.read()
        self.assertEqual(result['plotShop']['status'], 'component_absent')
        self.assertFalse(result['savedBindingsVerified'])

    def test_wrong_template_or_classification_is_reported_as_mismatch(self):
        for candidate in (bag(BAG + 1), bag(classification=0)):
            with self.subTest(candidate=candidate):
                self.write(fixture(instance_bag=candidate))
                result = self.read()
                self.assertFalse(result['savedReferencesVerified'])
                self.assertEqual(result['characterInstanceBag']['status'], 'reference_mismatch')

    def test_disabled_reference_is_distinct_from_missing_reference(self):
        self.write(fixture(template_bag=bag(enabled=0)))
        result = self.read()
        self.assertTrue(result['savedReferencesVerified'])
        self.assertFalse(result['savedBindingsVerified'])
        self.assertFalse(result['allReferencedComponentsEnabled'])

    def test_character_link_must_be_actual_role_template_and_instance(self):
        for field_number, replacement in ((2, message(2, [scalar(1, ROLE + 1)])),
                                          (8, scalar(8, 20010005))):
            fields = fixture()
            instances = g.parse_fields(fields[3].data)
            role = g.parse_fields(instances[0].data)
            role = [replacement if f.number == field_number else f for f in role]
            instances[0] = message(1, role)
            fields[3] = message(5, instances)
            self.write(fields)
            result = self.read()
            self.assertFalse(result['characterLink']['verified'])
            self.assertFalse(result['savedBindingsVerified'])

    def test_duplicate_target_record_and_component_are_refused(self):
        fields = fixture()
        records = g.parse_fields(fields[2].data)
        fields[2] = message(4, records + copy.deepcopy(records))
        self.write(fields)
        with self.assertRaisesRegex(check.SavedBindingError, 'duplicate object ID'):
            self.read()
        fields = fixture()
        records = g.parse_fields(fields[2].data)
        role = g.parse_fields(records[0].data) + [message(8, bag())]
        fields[2] = message(4, [message(1, role)])
        self.write(fields)
        with self.assertRaisesRegex(check.SavedBindingError, 'duplicate component'):
            self.read()

    def test_invalid_or_ambiguous_shop_indices_are_refused(self):
        for candidate in (shop(index=0), shop(extra=[scalar(1, 7), message(2, reference(SHOP + 1))]),
                          shop(extra=[scalar(1, 8), message(2, reference(SHOP))])):
            with self.subTest(candidate=candidate):
                self.write(fixture(plot_shop=candidate))
                with self.assertRaises(check.SavedBindingError):
                    self.read()
        self.write(fixture(plot_shop=shop(extra=[scalar(1, 8), message(2, reference(SHOP + 1))])))
        result = self.read()
        self.assertTrue(result['savedBindingsVerified'])
        self.assertEqual(result['plotShop']['matchingShopIndices'], [7])
        self.assertEqual(len(result['plotShop']['entries']), 2)

    def test_wrong_wire_conflicting_payload_and_duplicate_reference_refuse(self):
        for candidate in ([scalar(1, 33), scalar(44, BAG)],
                          bag() + [message(46, [])],
                          [scalar(1, 33), message(44, [message(1, reference(BAG) + [scalar(2, BAG)])])]):
            self.write(fixture(template_bag=candidate))
            with self.assertRaises(check.SavedBindingError):
                self.read()

    def test_level_missing_mismatch_wrong_container_and_truncation_refuse(self):
        self.write(fixture())
        with self.assertRaisesRegex(check.SavedBindingError, 'embedded level ID'):
            self.read(level_id=LEVEL + 1)
        self.write(fixture()[1:])
        with self.assertRaisesRegex(check.SavedBindingError, 'missing required'):
            self.read()
        self.write(fixture(), subtype=g.SUBTYPE_PLAYER)
        with self.assertRaisesRegex(check.SavedBindingError, 'not a level container'):
            self.read()
        self.file.write_bytes(self.file.read_bytes()[:-1])
        with self.assertRaises(g.ContainerError):
            self.read()

    def test_changed_input_is_refused(self):
        self.write(fixture())
        raw = self.file.read_bytes()
        with patch.object(Path, 'read_bytes', side_effect=[raw, raw + b'x']):
            with self.assertRaisesRegex(check.SavedBindingError, 'changed while'):
                self.read()

    def test_cli_is_read_only_and_reports_missing_paths_with_exit_two(self):
        self.write(fixture(instance_bag=[]))
        before = self.file.read_bytes()
        args = ['--gil', str(self.file)]
        for name, value in ARGS.items():
            args.extend(['--' + name.replace('_', '-'), str(value)])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = check.main(args)
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(output.getvalue())['savedBindingsVerified'])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(list(self.file.parent.iterdir()), [self.file])


if __name__ == '__main__':
    unittest.main()
