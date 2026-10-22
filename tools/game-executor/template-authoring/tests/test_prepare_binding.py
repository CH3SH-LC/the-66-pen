"""Exercise the fixed binding preparation with synthetic compiler/session only."""
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tests'))
import binding_review as reviews
import prepare_binding as prepare_api
from test_template_review import ReviewFixture


class BindingPreparationTests(unittest.TestCase):
    def setUp(self):
        self.data = ReviewFixture()
        self.data.initialize(self)
        self.enterContext(patch.object(reviews, 'CLAIMS', self.data.base / 'binding-claims'))
        self.enterContext(patch.object(prepare_api, 'OUTPUT', self.data.base / 'binding-builds'))
        self.select('bind-shop')

    def select(self, action):
        self.data.request = self.data.fixture.request(action, entityId=123,
            templateId=1136656385 if action == 'bind-shop' else 1119879169)
        prepared = reviews.requests.prepare(self.data.request, baseline_run=self.data.baseline)
        self.data.request_path = Path(prepared['requestPath'])
        self.data.runtime = {'functions': [{'rva': hex(rva), 'head32': '00' * 32}
                                         for rva in prepare_api.candidate.FUNCTIONS]}
        self.data.runtime['referenceFactory'] = {
            **prepare_api.candidate.REFERENCE_CONTRACT,
            'functions': [{'rva': hex(rva), 'head32': '00' * 32} for rva in prepare_api.candidate.REFERENCE_FUNCTIONS],
            'hotfixGuards': [{'flagRva': hex(rva), 'requiredRuntimeByte': 0} for rva in prepare_api.candidate.REFERENCE_HOTFIX],
        }
        self.data.write(self.data.runtime_path, self.data.runtime)
        self.data.review.update(kind='template-binding-review-v1', action=action,
            reviewId=str(uuid.uuid4()), requestPath=str(self.data.request_path),
            requestSha256=reviews.profiles.sha256(self.data.request_path),
            runtimeProfileSha256=reviews.profiles.sha256(self.data.runtime_path),
            sourceHashes=reviews.source_hashes())
        self.data.save()

    def mocks(self):
        raw = bytes.fromhex(reviews.requests.read_json(self.data.baseline / 'stdout.jsonl')['snapshotHex'])
        self.loader = self.enterContext(patch.object(prepare_api.candidate, 'load_inputs', return_value=(
            self.data.request, raw, self.data.runtime, reviews.profiles.load_profile(),
            {'syntheticFixture': True}, {'syntheticFixture': True})))
        self.identity = self.enterContext(patch.object(prepare_api.profiles, 'validate_session', return_value=self.data.session))
        kernel, user = Mock(), Mock()
        kernel.GetTickCount64.return_value = 1000
        user.RegisterWindowMessageW.return_value = 0xc456
        self.enterContext(patch.object(prepare_api.profiles, 'windows_api', return_value=(kernel, user)))
        def compile_fixture(run):
            for name in ('hook_receipt.dll', 'hook_receipt_probe.exe'):
                (run / name).write_bytes(b'SYNTHETIC COMPILER OUTPUT; NEVER EXECUTE')
            return 'synthetic compiler'
        self.compiler = self.enterContext(patch.object(prepare_api.candidate, 'compile_sources', side_effect=compile_fixture))

    def test_both_bindings_keep_fixed_kind_target_and_action(self):
        for action, kind, template in [('bind-shop', 35, 1136656385), ('bind-bag', 33, 1119879169)]:
            with self.subTest(action=action):
                self.select(action)
                self.mocks()
                result = prepare_api.prepare(self.data.review_path)
                run = Path(result['run'])
                contract = reviews.requests.read_json(run / 'build-contract.json')
                self.assertEqual((result['action'], result['actionCode'], contract['receiptVersion']), (action, 7, 11))
                header = (run / 'target_config.h').read_text(encoding='utf-8')
                for token in ('#define HR_ACTION 7ULL', '#define TA_BINDING_REVIEWED 1',
                              '#define HR_TARGET_PID 9ULL', '#define HR_DEADLINE 181000ULL',
                              '#define TA_REFERENCE_ANCHOR_RVAS 0x95f6410,0x1013f9f0,0x1013f8e0,0x110e2f00',
                              '#define TA_REFERENCE_USAGE_GROUPS 0xd49f,0x2bacd',
                              f'#define TA_BINDING_KIND {kind}', '#define TA_BINDING_ENTITY_ID 123U',
                              f'#define TA_BINDING_TEMPLATE_ID {template}U'):
                    self.assertIn(token, header)
                self.assertTrue(result['launchable'])
                self.assertFalse(result['nativeCalled'] or result['probeExecuted'])
                self.assertFalse((run / 'stdout.jsonl').exists())
                for name, digest in result['hashes'].items():
                    self.assertEqual(reviews.profiles.sha256(run / name), digest)
                wrapper = (run / 'invoke-binding-probe.ps1').read_text(encoding='utf-8-sig')
                for token in ('FIXED_TEMPLATE_BINDING_ACTION', 'NOT_ELEVATED', 'CreateNew', 'CopyToAsync', 'WRAPPER_CHANGED'):
                    self.assertIn(token, wrapper)
                self.assertNotIn('elevated-runner', wrapper)

    def test_review_action_cannot_switch_request_kind(self):
        self.data.review['action'] = 'bind-bag'
        self.data.save()
        with self.assertRaisesRegex(ValueError, 'REVIEW_REQUEST_IDENTITY_MISMATCH'):
            reviews.validate_review(self.data.review_path)

    def test_currency_review_or_unreviewed_state_never_reaches_compiler(self):
        self.mocks()
        for change in ({'action': 'create-currency'}, {'state': 'unreviewed'}):
            self.select('bind-shop')
            self.data.review.update(change)
            self.data.save()
            with self.assertRaisesRegex(ValueError, 'BINDING_COORDINATOR_REVIEW_REQUIRED'):
                prepare_api.prepare(self.data.review_path)
        self.identity.assert_not_called()
        self.compiler.assert_not_called()

    def test_failed_compilation_consumes_review_and_never_emits_launcher(self):
        self.mocks()
        self.compiler.side_effect = ValueError('synthetic compile failure')
        with self.assertRaisesRegex(ValueError, 'synthetic compile failure'):
            prepare_api.prepare(self.data.review_path)
        with self.assertRaisesRegex(ValueError, 'BINDING_REVIEW_ALREADY_CLAIMED'):
            prepare_api.prepare(self.data.review_path)
        self.assertEqual(self.compiler.call_count, 1)
        self.assertFalse(list((self.data.base / 'binding-builds').rglob('invoke-binding-probe.ps1')))

    def test_changed_binding_source_is_not_accepted_as_prior_review(self):
        self.data.review['sourceHashes'].pop('tools/game-executor/template-authoring/binding_action.cpp')
        self.data.save()
        with self.assertRaisesRegex(ValueError, 'REVIEW_SOURCE_CHANGED_OR_INCOMPLETE'):
            reviews.validate_review(self.data.review_path)


if __name__ == '__main__':
    unittest.main()
