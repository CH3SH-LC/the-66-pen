"""Offline regression for skipped dependent reads; never accesses a game process."""
from pathlib import Path
import copy
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_scheduler_coroutines as api
import native_lifecycle_type as lifecycle_api
import native_profiles as profiles
import test_native_scheduler_coroutines as scheduler_fixture
import test_native_lifecycle_type as lifecycle_fixture


class PrerequisiteDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = scheduler_fixture.SchedulerTests()
        self.fixture.setUp()
        self.context = copy.deepcopy(self.fixture.ctx)
        self.context['counts'] = {'peImageSize': 453693440}
        self.profile = self.fixture.p

    def refused(self):
        raw = bytearray(api.SCHEDULER_COROUTINES_BYTES)
        struct.pack_into('<4I', raw, 0, len(raw), 1, 1, 0)
        return raw

    def lifecycle_not_ready(self, initialized=0):
        raw = bytearray(lifecycle_api.LIFECYCLE_TYPE_BYTES)
        base = self.fixture.base
        level = self.fixture.level
        struct.pack_into('<4I', raw, 0, len(raw), 1, 8, 7)
        struct.pack_into('<6Q', raw, 16, base, base + 0x5826620, 0, 0, 0, base + 0x9037840)
        struct.pack_into('<12I', raw, 64, 453693440, level, initialized, 0, 0, 0, 0, 0xffffffff, 4085, 24, 0, 0)
        return raw

    def record(self, scheduler=None, lifecycle=None):
        scheduler = self.refused() if scheduler is None else scheduler
        lifecycle = self.lifecycle_not_ready() if lifecycle is None else lifecycle
        return {'schedulerCoroutinesHex': scheduler.hex(), 'schedulerCoroutinesBytes': len(scheduler),
                'schedulerCoroutinesStatus': struct.unpack_from('<I', scheduler, 8)[0],
                'lifecycleTypeHex': lifecycle.hex(), 'lifecycleTypeBytes': len(lifecycle),
                'lifecycleTypeStatus': struct.unpack_from('<I', lifecycle, 8)[0]}

    def test_lifecycle_failure_blocks_scheduler_without_observing_null(self):
        result = api.diagnose_prerequisites(self.record(), self.context, self.profile)
        scheduler = result['schedulerCoroutines']
        self.assertEqual((scheduler['state'], scheduler['measurement']), ('blocked', 'not_observed'))
        self.assertEqual(scheduler['readCalls'], 0)
        self.assertEqual(scheduler['schedulerPointer'], {'observed': False, 'value': None})
        self.assertEqual(scheduler['initializationState'], 'unknown')
        self.assertEqual(scheduler['blockingDependencies'][0]['component'], 'lifecycleType')
        lifecycle = result['lifecycleType']
        self.assertEqual(lifecycle['initializationFlag'], {'observed': True, 'value': 0})
        self.assertEqual(lifecycle['classPointer'], {'observed': False, 'value': None})
        self.assertEqual(result['rootCauses'], [{'component': 'lifecycleType', 'reason': 'wrapper_metadata_flag_not_set', 'observedValue': 0}])
        self.assertFalse(result['reopenAllowed'])
        self.assertFalse(result['reopenVerified'])
        self.assertFalse(result['currentSessionVerified'])
        self.assertFalse(result['checks']['schedulerAccepted'])
        self.assertIn('SCHEDULER_ROOT_POINTERS', result['reasons'])

    def test_non_ready_byte_is_not_assumed_to_be_zero(self):
        result = api.diagnose_prerequisites(self.record(lifecycle=self.lifecycle_not_ready(2)), self.context, self.profile)
        self.assertEqual(result['lifecycleType']['initializationFlag'], {'observed': True, 'value': 2})

    def test_scheduler_status_mismatch_is_invalid(self):
        record = self.record()
        record['schedulerCoroutinesStatus'] = 8
        result = api.decode(record, self.context, self.profile)
        self.assertFalse(result['ok'])
        self.assertEqual(result['observation']['state'], 'invalid')
        self.assertFalse(result['observation']['schedulerPointer']['observed'])

    def test_nonzero_refusal_fields_are_not_accepted_as_skipped(self):
        for offset, width in ((12, '<I'), (32, '<Q'), (144, '<I'), (160, '<Q')):
            raw = self.refused()
            struct.pack_into(width, raw, offset, 1)
            result = api.decode(self.record(scheduler=raw), self.context, self.profile)
            self.assertFalse(result['ok'])
            self.assertEqual(result['observation']['state'], 'invalid')
            self.assertFalse(result['observation']['schedulerPointer']['observed'])

    def test_lifecycle_outer_status_mismatch_never_claims_read(self):
        record = self.record()
        record['lifecycleTypeStatus'] = 0
        result = api.diagnose_prerequisites(record, self.context, self.profile)
        self.assertFalse(result['lifecycleType']['initializationFlag']['observed'])
        self.assertEqual(result['rootCauses'][0]['reason'], 'type_binding_not_verified')

    def test_lifecycle_initialization_needs_credible_prefix(self):
        for offset, value in ((12, 0), (72, 1), (72, 256), (100, 0), (80, 1), (112, 1)):
            raw = self.lifecycle_not_ready()
            struct.pack_into('<I', raw, offset, value)
            result = api.diagnose_prerequisites(self.record(lifecycle=raw), self.context, self.profile)
            self.assertFalse(result['lifecycleType']['initializationFlag']['observed'])

    def test_lifecycle_initialization_needs_matching_context(self):
        for section, key, value in (('status', 'value', 1), ('levelObservation', 'levelId', 1),
                                    ('pointers', 'moduleBase', '0x10000'), ('counts', 'peImageSize', 1)):
            context = copy.deepcopy(self.context)
            context[section][key] = value
            result = api.diagnose_prerequisites(self.record(), context, self.profile)
            self.assertFalse(result['lifecycleType']['initializationFlag']['observed'])

    def test_positive_reads_do_not_prove_scheduler_pointer_read(self):
        raw = self.refused()
        struct.pack_into('<II', raw, 8, 8, 7)
        struct.pack_into('<II', raw, 140, 4085, 24)
        result = api.decode(self.record(scheduler=raw), self.context, self.profile)
        self.assertEqual(result['observation']['measurement'], 'partial_or_unverified')
        self.assertEqual(result['observation']['schedulerPointer'], {'observed': False, 'value': None})
        self.assertEqual(result['observation']['initializationState'], 'unknown')

    def test_successful_scheduler_sample_still_does_not_authorize_reopen(self):
        raw = self.fixture.fixture()
        result = api.decode(self.record(scheduler=raw), self.context, self.profile)
        self.assertTrue(result['ok'])
        self.assertEqual(result['observation']['state'], 'accepted')
        self.assertEqual(result['observation']['schedulerPointer'], {'observed': True, 'value': '0x30000'})
        self.assertFalse(result['observation']['reopenAllowed'])
        self.assertFalse(result['observation']['absenceProven'])

    def test_readonly_diagnostic_can_observe_null_slot_without_acceptance(self):
        raw = self.lifecycle_not_ready()
        struct.pack_into('<I', raw, 12, 263)
        result = api.diagnose_prerequisites(self.record(lifecycle=raw), self.context, self.profile)
        lifecycle = result['lifecycleType']
        self.assertTrue(lifecycle['typeSlotRead'])
        self.assertEqual(lifecycle['classPointer'], {'observed': True, 'value': '0x0'})
        self.assertFalse(lifecycle['typeBindingObservedOnly'])
        self.assertFalse(result['checks']['lifecycleAccepted'])
        self.assertFalse(result['reopenAllowed'])
        self.assertEqual(result['schedulerCoroutines']['measurement'], 'not_observed')

    def test_readonly_type_binding_remains_diagnostic_only(self):
        fixture = lifecycle_fixture.LifecycleTests()
        fixture.setUp()
        raw = fixture.fixture()
        struct.pack_into('<II', raw, 8, 8, 503)
        struct.pack_into('<II', raw, 72, 0, 0)
        result = api.diagnose_prerequisites(self.record(lifecycle=raw), self.context, self.profile)
        lifecycle = result['lifecycleType']
        self.assertTrue(lifecycle['typeBindingObservedOnly'])
        self.assertTrue(lifecycle['stableReadback'])
        self.assertEqual(lifecycle['classPointer'], {'observed': True, 'value': hex(fixture.cls)})
        self.assertFalse(result['checks']['lifecycleAccepted'])
        self.assertFalse(result['checks']['schedulerAccepted'])
        self.assertFalse(result['reopenAllowed'])
        self.assertEqual(result['rootCauses'][0]['reason'], 'wrapper_metadata_flag_not_set')
        for offset, value in ((84, 5), (92, 0), (12, 511), (72, 1)):
            corrupt = bytearray(raw)
            struct.pack_into('<I', corrupt, offset, value)
            diagnosed = api.diagnose_prerequisites(self.record(lifecycle=corrupt), self.context, self.profile)
            self.assertFalse(diagnosed['lifecycleType']['typeBindingObservedOnly'])

    def test_pure_diagnosis_does_not_mutate_inputs(self):
        record = self.record()
        originals = copy.deepcopy((record, self.context, self.profile))
        api.diagnose_prerequisites(record, self.context, self.profile)
        self.assertEqual((record, self.context, self.profile), originals)

    def test_missing_or_bad_raw_extension_remains_refused(self):
        for field, value in (('schedulerCoroutinesHex', ''), ('lifecycleTypeHex', '00'),
                             ('schedulerCoroutinesBytes', 1), ('lifecycleTypeBytes', 1)):
            record = self.record()
            record[field] = value
            with self.assertRaises(profiles.ProfileError):
                api.diagnose_prerequisites(record, self.context, self.profile)


if __name__ == '__main__':
    unittest.main(verbosity=2)
