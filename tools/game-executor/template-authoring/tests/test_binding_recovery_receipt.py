"""Synthetic bytes only; no executable, process, native call or game access."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import binding_recovery_receipt as api
import binding_receipt as prior_api
from test_component_receipt import encode as component_bytes
from test_currency_receipt import encode as catalog_hex


def fixture():
    prior = bytearray(prior_api.RECEIPT_BYTES)
    classes = tuple(0x21000 + i * 0x1000 for i in range(8))
    owner, wrapper, config, empty, token = 0x10000, 0x30000, 0x31000, 0x33000, 0x45000
    struct.pack_into('<9I', prior, 0, len(prior), 2, 0, 0, 1, 0, 0, 17, 17)
    struct.pack_into('<8Q3B', prior, 40, *classes, 1, 1, 1)
    at = prior_api.ACTION_AT
    struct.pack_into('<5I', prior, at, 19, 4, 123, 1119879169, 17)
    struct.pack_into('<5Qi', prior, at + 24, owner, 0x34000, wrapper, config, 0, 0)
    struct.pack_into('<I', prior, at + 72, 1)
    row = (wrapper, classes[2], config, classes[0], 33, 0)
    struct.pack_into('<4QiB3x', prior, at + 80, *row)
    struct.pack_into('<Q4B', prior, at + 120, wrapper, 1, 1, 1, 1)
    struct.pack_into('<2I2Qi11B', prior, at + 136, 3, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('<8B', prior, at + 176, 1, 1, 1, 0, 0, 0, 0, 1)
    edit = prior_api.EDIT_AT
    struct.pack_into('<2IQ10B', prior, edit, 8, 0, token, 1, 1, 0, 0, 1, 0, 0, 1, 1, 1)
    struct.pack_into('<5QiB', prior, edit + 32, 0x140000000, 0x10000, owner, wrapper, config, 33, 1)
    def state(data, offset, count, depth, dirty):
        struct.pack_into('<4I2i', data, offset, 0, count, 4 + count, count, 20, depth)
        struct.pack_into('<6Q', data, offset + 32, 0x40000, 0x41000, 0x42000, classes[6], 0x44000, 10)
        if count:
            record = (0x46000, classes[6], wrapper, 0, 0x47000, dirty)
            for where in (80, 128): struct.pack_into('<5QB7x', data, offset + where, *record)
    state(prior, edit + 80, 0, 20, 0)
    state(prior, edit + 12496, 1, 21, 0)
    catalog = bytes.fromhex(catalog_hex([(1119879169, 12, 0x34000, classes[3])], [], level=99))
    for offset in (prior_api.BEFORE_CATALOG_AT, prior_api.AFTER_CATALOG_AT): prior[offset:offset + len(catalog)] = catalog
    for offset, rows in ((prior_api.BEFORE_COMPONENTS_AT, []), (prior_api.AFTER_ATTACH_AT, [row]), (prior_api.FINAL_COMPONENTS_AT, [row])):
        block = component_bytes(rows); prior[offset:offset + len(block)] = block
    struct.pack_into('<2Q2Ii', prior, prior_api.BEFORE_BINDING_AT, empty, 0, 0, 0, 0)
    raw = bytearray(api.RECEIPT_BYTES)
    struct.pack_into('<6I', raw, 0, len(raw), 2, 0, 1, 1, 1)
    struct.pack_into('<I6B', raw, api.RESULT_AT, 8, 1, 1, 0, 1, 1, 1)
    struct.pack_into('<3Qi2B2x2I', raw, api.RESULT_AT + 16, empty, 0, 0, 0, 0, 0, 0, 0)
    struct.pack_into('<I4B', raw, api.LEGACY_RECEIPT_BYTES, 2, 1, 1, 1, 1)
    raw[api.EDIT_AT:api.EDIT_AT + prior_api.EDIT_BYTES] = prior[edit:edit + prior_api.EDIT_BYTES]
    struct.pack_into('<2IQ10B', raw, api.EDIT_AT, 13, 0, token, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1)
    state(raw, api.EDIT_AT + 24912, 1, 21, 1)
    struct.pack_into('<I', raw, api.EDIT_AT + 24912 + 4, 2)
    struct.pack_into('<I', raw, api.EDIT_AT + 24912 + 8, 6)
    struct.pack_into('<5QB7x', raw, api.EDIT_AT + 24912 + 128 + 48, 0x66000, 0x67000, 0, 0, 0, 0)
    state(raw, api.EDIT_AT + 37328, 0, 20, 0)
    for offset, rows in ((api.BEFORE_COMPONENTS_AT, [row]), (api.AFTER_COMPONENTS_AT, [(*row[:5], 1)])):
        block = component_bytes(rows); raw[offset:offset + len(block)] = block
    return bytes(prior), raw


def refusal_fixture(prior):
    raw = bytearray(api.LEGACY_RECEIPT_BYTES)
    struct.pack_into('<6I', raw, 0, len(raw), 1, 0, 1, 1, 0)
    struct.pack_into('<I6B', raw, api.RESULT_AT, 5, 1, 1, 0, 0, 1, 1)
    struct.pack_into('<Q', raw, api.RESULT_AT + 16, 0x33000)
    raw[api.EDIT_AT:api.EDIT_AT + prior_api.EDIT_BYTES] = prior[prior_api.EDIT_AT:prior_api.EDIT_AT + prior_api.EDIT_BYTES]
    return bytes(raw)


def pending_fixture(prior):
    raw = bytearray(api.RECEIPT_BYTES)
    struct.pack_into('<6I', raw, 0, len(raw), 2, 0, 1, 1, 1)
    struct.pack_into('<I6B', raw, api.RESULT_AT, 10, 1, 1, 0, 0, 1, 1)
    struct.pack_into('<Q', raw, api.RESULT_AT + 16, 0x33000)
    struct.pack_into('<I4B', raw, api.LEGACY_RECEIPT_BYTES, 2, 0, 0, 0, 1)
    raw[api.EDIT_AT:api.EDIT_AT + prior_api.EDIT_BYTES] = prior[prior_api.EDIT_AT:prior_api.EDIT_AT + prior_api.EDIT_BYTES]
    struct.pack_into('<I', raw, api.EDIT_AT, 3)
    state = bytearray(prior[prior_api.EDIT_AT + 12496:prior_api.EDIT_AT + 12496 + prior_api.STATE_BYTES])
    struct.pack_into('<2I', state, 4, 2, 6)
    struct.pack_into('<5QB7x', state, 128 + 48, 0x66000, 0x67000, 0, 0, 0, 0)
    raw[api.EDIT_AT + 24912:api.EDIT_AT + 24912 + prior_api.STATE_BYTES] = state
    return bytes(raw)


class BindingRecoveryReceiptTests(unittest.TestCase):
    def test_empty_attachment_closes_without_binding_claim(self):
        prior, raw = fixture()
        result = api.verify(bytes(raw), prior, refusal_fixture(prior), pending_fixture(prior))
        self.assertTrue(result['editTransactionClosed'] and result['needsBinding'])
        self.assertFalse(result['bindingVerified'] or result['persistentSaveVerified'] or result['gameplayVerified'])

    def test_changed_token_pending_default_or_component_rejected(self):
        for offset, fmt, value in ((api.EDIT_AT + 8, '<Q', 0x99900),
                (api.EDIT_AT + 37328 + 20, '<i', 21),
                (api.EDIT_AT + 24912 + 80 + 40, '<B', 0),
                (api.RESULT_AT + 52, '<I', 0xffffffff),
                (api.RESULT_AT + 48, '<I', 1),
                (api.AFTER_COMPONENTS_AT + 1136 + 16, '<Q', 0x88800)):
            with self.subTest(offset=offset):
                prior, raw = fixture(); struct.pack_into(fmt, raw, offset, value)
                with self.assertRaises(ValueError): api.verify(bytes(raw), prior, refusal_fixture(prior), pending_fixture(prior))

    def test_prior_must_be_definite_null_before_any_setter(self):
        for offset in (prior_api.ACTION_AT + 164 + 4, prior_api.EDIT_AT + 18):
            prior, raw = fixture(); bad = bytearray(prior); bad[offset] = 1
            with self.assertRaises(ValueError): api.verify(bytes(raw), bytes(bad), refusal_fixture(prior), pending_fixture(prior))

    def test_copied_prior_states_cannot_be_reconstructed(self):
        prior, raw = fixture(); struct.pack_into('<I', raw, api.EDIT_AT + 12496 + 8, 11)
        with self.assertRaisesRegex(ValueError, 'RECOVERY_PRIOR_STATE_CHANGED'): api.verify(bytes(raw), prior, refusal_fixture(prior), pending_fixture(prior))

    def test_v2_requires_core_progress_and_does_not_fake_token_verification(self):
        for offset, value in ((api.LEGACY_RECEIPT_BYTES + 5, 0), (api.RESULT_AT + 6, 1)):
            prior, raw = fixture(); raw[offset] = value
            with self.assertRaisesRegex(ValueError, 'RECOVERY_RESULT_INCOMPLETE'):
                api.verify(bytes(raw), prior, refusal_fixture(prior), pending_fixture(prior))
        prior, raw = fixture(); refused = bytearray(refusal_fixture(prior)); refused[api.EDIT_AT + 18] = 1
        with self.assertRaisesRegex(ValueError, 'RECOVERY_REFUSAL_SHAPE'): api.verify(bytes(raw), prior, bytes(refused), pending_fixture(prior))

    def test_second_captured_record_must_match_reviewed_diagnostic(self):
        prior, raw = fixture()
        struct.pack_into('<Q', raw, api.EDIT_AT + 24912 + 128 + 48, 0x88000)
        with self.assertRaisesRegex(ValueError, 'RECOVERY_NOTIFY_RECORD_DELTA'):
            api.verify(bytes(raw), prior, refusal_fixture(prior), pending_fixture(prior))

    def test_prior_uses_original_seventeen_metadata_groups(self):
        prior, _ = fixture(); bad = bytearray(prior)
        struct.pack_into('<2I', bad, 28, 19, 19)
        with self.assertRaisesRegex(ValueError, 'RECOVERY_PRIOR_NATIVE'): api.verify_prior(bytes(bad))

    def test_real_failed_prior_is_decodable_when_evidence_available(self):
        # Optional current-run control: the synthetic suite remains standalone.
        import json
        root = Path(__file__).resolve().parents[4]
        path = root / '.runtime/template-authoring/prepared-binding/20261013-102256-7dc1ea2e2b/stdout.jsonl'
        if not path.exists(): self.skipTest('current failed-run evidence absent')
        raw = bytes.fromhex(json.loads(path.read_text())['bindingResultHex'])
        self.assertEqual(api.verify_prior(raw)['edit']['transaction'], 7697449044768)


if __name__ == '__main__': unittest.main()
