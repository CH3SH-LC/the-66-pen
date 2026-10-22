"""Fixed reference route gates; no game discovery or execution."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_binding_candidate as candidate


class ReferenceProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = json.loads(candidate.DEFAULT_RUNTIME_PROFILE.read_text(encoding='utf-8'))

    def test_fixed_native_route_and_unchanged_legacy_anchors(self):
        route = candidate.validate_reference_contract(self.profile)
        self.assertEqual(route['typeName'], 'ClientBeyondConfigReferenceEditData')
        old = json.loads((candidate.ROOT / '.runtime/scratch/overnight-features-20261013/task-ba/binding-edit-runtime-profile.json').read_text(encoding='utf-8'))
        for field in ('functions', 'hotfixGuards', 'metadataInitialization', 'editTransaction'):
            self.assertEqual(self.profile[field], old[field])
        self.assertEqual(len(candidate.FUNCTIONS), 25)

    def test_legacy_profile_missing_typed_route_rejected(self):
        del self.profile['referenceFactory']
        with self.assertRaisesRegex(ValueError, 'BINDING_TYPED_REFERENCE_CONTRACT'):
            candidate.validate_reference_contract(self.profile)

    def test_wrong_type_initializer_and_hotfix_are_rejected(self):
        for field, value in [('typeNameSlot', '0x0'), ('classDefinition', 34146),
                             ('setIdRva', '0x1013f680'), ('usageGroups', [])]:
            with self.subTest(field=field):
                changed = deepcopy(self.profile)
                changed['referenceFactory'][field] = value
                with self.assertRaisesRegex(ValueError, 'BINDING_TYPED_REFERENCE_CONTRACT'):
                    candidate.validate_reference_contract(changed)
        self.profile['referenceFactory']['hotfixGuards'][0]['requiredRuntimeByte'] = 1
        with self.assertRaisesRegex(ValueError, 'BINDING_REFERENCE_HOTFIX_SET'):
            candidate.validate_reference_contract(self.profile)


if __name__ == '__main__':
    unittest.main()
