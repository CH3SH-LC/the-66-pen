"""Synthetic coordinator fixtures only; production code cannot issue reviews."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / 'tests'))
import skill_review as review_api
import test_request as request_fixtures


class ReviewFixture:
    """Deleted after every test; never a real authorization or executable target."""
    def initialize(self, testcase):
        self.fixture = request_fixtures.RequestTests()
        self.fixture.setUp()
        testcase.addCleanup(self.fixture.doCleanups)
        self.base, self.baseline, self.session = self.fixture.base, self.fixture.run, self.fixture.session
        self.request = self.fixture.request('create-skill')
        prepared = request_fixtures.request_api.prepare(self.request, baseline_run=self.baseline)
        self.request_path = Path(prepared['requestPath'])
        self.runtime_path = self.base / 'synthetic-runtime-profile.json'
        self.runtime = {'functions': [{'rva': hex(rva), 'headBytes': '00' * 32, 'headLength': 32}
                                    for rva in review_api.candidate.FUNCTIONS]}
        self.write(self.runtime_path, self.runtime)
        self.service_path = self.base / 'synthetic-transitive-currency-profile.json'
        self.write(self.service_path, {'functions': [{'rva': '0xb0a90c0', 'head32': '00' * 32}]})
        testcase.enterContext(patch.object(review_api.candidate, 'DEFAULT_RUNTIME_PROFILE', self.runtime_path))
        testcase.enterContext(patch.object(review_api.candidate, 'DEFAULT_SERVICE_PROFILE', self.service_path))
        self.user = self.base / 'synthetic-user'
        self.source = self.user / 'AppData/LocalLow/miHoYo/原神/BeyondLocal/123/Beyond_Local_Save_Level/99/99.gil'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'synthetic recovery bytes; not a game save')
        self.backup = self.base / 'synthetic-backup.gil'
        self.backup.write_bytes(self.source.read_bytes())
        testcase.enterContext(patch.dict('os.environ', {'USERPROFILE': str(self.user)}))
        testcase.enterContext(patch.object(review_api, 'CLAIMS', self.base / 'claims'))
        self.now = datetime.now(timezone.utc)
        testcase.enterContext(patch.object(review_api, 'utc_now', return_value=self.now))
        self.review = {'schemaVersion': 1, 'kind': 'template-skill-review-v1', 'state': 'reviewed',
            'reviewedBy': 'coordinator', 'reviewId': str(uuid.uuid4()),
            'reviewedAtUtc': (self.now - timedelta(seconds=5)).isoformat(),
            'expiresUtc': (self.now + timedelta(minutes=10)).isoformat(), 'action': 'create-skill',
            'requestPath': str(self.request_path), 'requestSha256': review_api.profiles.sha256(self.request_path),
            'levelId': 99, 'session': self.session, 'baselineRun': str(self.baseline), 'baselineKind': 'readonly',
            'evidenceHashes': review_api.requests._baseline_hashes(self.baseline, 'readonly'),
            'recovery': {'source': str(self.source), 'backup': str(self.backup),
                         'sha256': review_api.profiles.sha256(self.source)},
            'readonlyProfileSha256': review_api.profiles.PROFILE_SHA256,
            'runtimeProfilePath': str(self.runtime_path), 'runtimeProfileSha256': review_api.profiles.sha256(self.runtime_path),
            'transitiveCurrencyProfile': {'path': str(self.service_path), 'sha256': review_api.profiles.sha256(self.service_path)},
            'sourceHashes': review_api.source_hashes()}
        self.review_path = self.base / 'synthetic-review.json'
        self.save()

    @staticmethod
    def write(path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def save(self):
        self.write(self.review_path, self.review)


class SkillReviewTests(unittest.TestCase):
    def setUp(self):
        self.data = ReviewFixture()
        self.data.initialize(self)

    def test_complete_review_validates_raw_baseline_and_exact_backup_without_live_query(self):
        with patch.object(review_api.profiles, 'query_identity', side_effect=AssertionError('no live query')):
            result = review_api.validate_review(self.data.review_path, now=self.data.now, minimum_remaining=180)
        self.assertEqual(result['request'], self.data.request)
        self.assertEqual(result['baseline']['entities'][0]['id'], 123)
        self.assertEqual(result['targetGil'], str(self.data.source))
        self.assertFalse(review_api.CLAIMS.exists())

    def test_review_state_action_unknown_fields_and_missing_source_refused(self):
        original = copy.deepcopy(self.data.review)
        changes = [('state', 'prepared'), ('action', 'create-currency'), ('reviewedBy', 'program'),
                   ('execute', True), ('sourceHashes', {}), ('reviewId', str(uuid.UUID(int=0))),
                   ('readonlyProfileSha256', '0' * 64)]
        for key, value in changes:
            with self.subTest(key=key):
                self.data.review = copy.deepcopy(original)
                self.data.review[key] = value
                self.data.save()
                with self.assertRaises(ValueError):
                    review_api.validate_review(self.data.review_path, now=self.data.now)

    def test_short_expired_future_and_excessive_windows_refused(self):
        original = copy.deepcopy(self.data.review)
        for start, end in ((-10, -1), (1, 300), (-1, 179), (-1, 3601)):
            with self.subTest(start=start, end=end):
                self.data.review = copy.deepcopy(original)
                self.data.review['reviewedAtUtc'] = (self.data.now + timedelta(seconds=start)).isoformat()
                self.data.review['expiresUtc'] = (self.data.now + timedelta(seconds=end)).isoformat()
                self.data.save()
                with self.assertRaisesRegex(ValueError, 'REVIEW_EXPIRED_OR_WINDOW_TOO_SHORT'):
                    review_api.validate_review(self.data.review_path, now=self.data.now, minimum_remaining=180)

    def test_request_baseline_runtime_and_recovery_changes_refused(self):
        for path in (self.data.request_path, self.data.baseline / 'stdout.jsonl', self.data.runtime_path,
                     self.data.service_path, self.data.source, self.data.backup):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                try:
                    with self.assertRaises(ValueError):
                        review_api.validate_review(self.data.review_path, now=self.data.now)
                finally:
                    path.write_bytes(original)

    def test_level_session_incomplete_baseline_hashes_and_wrong_formal_path_refused(self):
        original = copy.deepcopy(self.data.review)
        for mutation in ('level', 'session', 'evidence', 'formal'):
            with self.subTest(mutation=mutation):
                self.data.review = copy.deepcopy(original)
                if mutation == 'level': self.data.review['levelId'] = 100
                elif mutation == 'session': self.data.review['session']['tid'] = 77
                elif mutation == 'evidence': self.data.review['evidenceHashes'].pop('stdout.jsonl')
                else: self.data.review['recovery']['source'] = str(self.data.backup)
                self.data.save()
                with self.assertRaises(ValueError):
                    review_api.validate_review(self.data.review_path, now=self.data.now)

    def test_one_review_is_consumed_once_without_overwriting_claim(self):
        validated = review_api.validate_review(self.data.review_path, now=self.data.now)
        path = review_api.claim_review(validated, self.data.base / 'compiled-one')
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'SKILL_REVIEW_ALREADY_CLAIMED'):
            review_api.claim_review(validated, self.data.base / 'compiled-two')
        self.assertEqual(path.read_bytes(), original)

    def test_both_runtime_profiles_are_mandatory_source_hash_inputs(self):
        original = copy.deepcopy(self.data.review)
        for profile in (self.data.runtime_path, self.data.service_path):
            key = str(profile.relative_to(review_api.ROOT)).replace('\\', '/')
            self.assertEqual(original['sourceHashes'][key], review_api.profiles.sha256(profile))
            self.data.review = copy.deepcopy(original)
            self.data.review['sourceHashes'].pop(key)
            self.data.save()
            with self.assertRaisesRegex(ValueError, 'REVIEW_SOURCE_CHANGED_OR_INCOMPLETE'):
                review_api.validate_review(self.data.review_path)

    def test_transitive_profile_path_digest_and_closed_schema_are_bound(self):
        original = copy.deepcopy(self.data.review)
        for mutation in ('missing', 'digest', 'path', 'extra'):
            with self.subTest(mutation=mutation):
                self.data.review = copy.deepcopy(original)
                if mutation == 'missing': self.data.review.pop('transitiveCurrencyProfile')
                elif mutation == 'digest': self.data.review['transitiveCurrencyProfile']['sha256'] = '0' * 64
                elif mutation == 'path': self.data.review['transitiveCurrencyProfile']['path'] = str(self.data.runtime_path)
                else: self.data.review['transitiveCurrencyProfile']['allowOverride'] = True
                self.data.save()
                with self.assertRaises(ValueError):
                    review_api.validate_review(self.data.review_path)


if __name__ == '__main__':
    unittest.main()
