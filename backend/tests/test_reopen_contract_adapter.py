"""W15 -- offline tests for the reopen <-> business-contract adapter.

Pure function calls against a fake backend: no game, editor, helper, bridge, queue, journal or
network is touched, and nothing is written to disk.  Every document is an in-memory dict built
by ``bound_inputs``; the tests are the refusal counterexamples the work package asks for.

Run:  python -m unittest backend.tests.test_reopen_contract_adapter -v
"""
from __future__ import annotations

import copy
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import business_contract as bc                              # noqa: E402
from backend import reopen_contract_adapter as ra                        # noqa: E402

NOW = datetime(2026, 10, 5, 3, 0, 0, tzinfo=timezone.utc)
# The reopen track's fixed level.  scene_cli.py:670, elevated-request.py:517,
# reopen_dispatch.py, native_reopen_acceptance/result/baseline and
# runtime_observation.py all pin 1073741840; the old 1073741839 was the level of an
# earlier save and is no longer what the fixed-level gate authorizes.
LEVEL = 1073741840
RID = '0123456789abcdef0123456789abcdef'
SSHA = '11' * 32
RSHA = '22' * 32
ASHA = '33' * 32
LCSHA = 'ab' * 32
DSHA = '44' * 32

SESSION = {
    'schemaVersion': 1, 'pid': 4242, 'tid': 99, 'window': 1, 'windowClass': 'x',
    'processCreation': 123456, 'threadCreation': 7, 'image': 'D:/game/game.exe',
}


def bound_inputs(**overrides):
    review = {
        'schemaVersion': 1, 'operation': 'level.reopen-current', 'allowedCalls': 1,
        'levelId': LEVEL, 'requestId': RID,
        'createdUtc': (NOW - timedelta(seconds=60)).isoformat(),
        'expiresUtc': (NOW + timedelta(seconds=60)).isoformat(),
        'session': copy.deepcopy(SESSION),
    }
    lease = {
        'schema': 1, 'action': 'reopen-current', 'requestId': RID, 'levelId': LEVEL,
        'sessionPath': 'D:/R/.runtime/native-session.json',
        'sessionSha256': SSHA, 'reviewSha256': RSHA, 'accountBaselineSha256': ASHA,
    }
    base = {
        'requestId': RID, 'levelId': LEVEL, 'handleLevelId': LEVEL,
        'session': copy.deepcopy(SESSION), 'review': review, 'lease': lease,
        'claim': copy.deepcopy(lease),
        'sessionSha256': SSHA, 'reviewSha256': RSHA,
        'leaseSha256': LCSHA, 'claimSha256': LCSHA, 'accountBaselineSha256': ASHA,
        'dispatchSha256': DSHA,
        'dispatch': None, 'acceptance': None, 'preflight': None,
    }
    base.update(overrides)
    return base


def returned_dispatch():
    return {'ok': True, 'action': 'reopen-current', 'requestId': RID,
            'status': 'dispatch-returned-business-pending', 'nativeCallAttempted': True,
            'nativeCallReturned': True, 'callExceptionCode': 0, 'hookCleanupVerified': True,
            'businessPending': True, 'businessVerified': False, 'reopenVerified': False,
            'outcomeUncertain': False, 'retryAttempted': False, 'safeToRelease': False}


def valid_acceptance():
    return {'schema': 2, 'operation': 'level.reopen-current',
            'scope': 'fixed-1839-reopen-roundtrip', 'requestId': RID, 'levelId': LEVEL,
            'leaseSha256': LCSHA, 'dispatchSha256': DSHA,
            'businessVerified': True, 'reopenRoundtripVerified': True}


def refused(report):
    return {r['code'] for r in report['refusals']}


class ConsistencyGate(unittest.TestCase):
    def test_consistent_bindings_produce_no_refusal(self):
        self.assertEqual(ra.check_bindings(bound_inputs(), now=NOW), [])

    def test_every_emitted_result_is_contract_valid(self):
        scenarios = [
            bound_inputs(),
            bound_inputs(levelId=1073741834, handleLevelId=1073741834),
            bound_inputs(handleLevelId=1073741834),
            bound_inputs(review=dict(bound_inputs()['review'],
                                     expiresUtc=(NOW - timedelta(seconds=1)).isoformat())),
            bound_inputs(claimSha256='cd' * 32),
            bound_inputs(dispatch=returned_dispatch()),
            bound_inputs(dispatch=returned_dispatch(), acceptance=valid_acceptance()),
            bound_inputs(dispatch={'status': 'dispatch-refused-no-call'}),
        ]
        for inputs in scenarios:
            report = ra.adapt_reopen(inputs, now=NOW)
            self.assertEqual(bc.validate_result(report['result']), [],
                             'v1 result must be contract-valid for %r' % (report['nextAction'],))
            self.assertEqual(report['initializationWritten'], False)
            # ok is never true unless the operation completed.
            self.assertEqual(report['result']['ok'],
                             report['result']['state'] == 'completed')

    def test_refuses_wrong_level(self):
        report = ra.adapt_reopen(bound_inputs(levelId=1073741834, handleLevelId=1073741834),
                                 now=NOW)
        self.assertIn('READBACK_WRONG_LEVEL', refused(report))
        self.assertEqual(report['result']['state'], 'rejected')
        self.assertEqual(report['nextAction'], 'fix-input')
        self.assertFalse(report['reopenVerified'])

    def test_refuses_handle_level_mismatch(self):
        report = ra.adapt_reopen(bound_inputs(handleLevelId=1073741834), now=NOW)
        self.assertIn('READBACK_WRONG_LEVEL', refused(report))
        self.assertEqual(report['result']['state'], 'rejected')

    def test_refuses_expired_review(self):
        expired = dict(bound_inputs()['review'],
                       createdUtc=(NOW - timedelta(seconds=600)).isoformat(),
                       expiresUtc=(NOW - timedelta(seconds=30)).isoformat())
        report = ra.adapt_reopen(bound_inputs(review=expired), now=NOW)
        self.assertIn('TARGET_STALE_REVISION', refused(report))
        self.assertEqual(report['result']['state'], 'rejected')

    def test_refuses_review_for_another_request(self):
        other = dict(bound_inputs()['review'], requestId='f' * 32)
        report = ra.adapt_reopen(bound_inputs(review=other), now=NOW)
        self.assertIn('REQUEST_ID_CONFLICT', refused(report))

    def test_refuses_review_for_another_level(self):
        other = dict(bound_inputs()['review'], levelId=1073741834)
        report = ra.adapt_reopen(bound_inputs(review=other), now=NOW)
        self.assertIn('READBACK_WRONG_LEVEL', refused(report))

    def test_refuses_lease_and_claim_bytes_differing(self):
        report = ra.adapt_reopen(bound_inputs(claimSha256='cd' * 32), now=NOW)
        self.assertIn('EVIDENCE_INTEGRITY_FAILED', refused(report))

    def test_refuses_lease_review_pin_mismatch(self):
        lease = dict(bound_inputs()['lease'], reviewSha256='ee' * 32)
        report = ra.adapt_reopen(bound_inputs(lease=lease, claim=copy.deepcopy(lease)), now=NOW)
        self.assertIn('EVIDENCE_INTEGRITY_FAILED', refused(report))

    def test_refuses_lease_session_pin_mismatch(self):
        lease = dict(bound_inputs()['lease'], sessionSha256='ee' * 32)
        report = ra.adapt_reopen(bound_inputs(lease=lease, claim=copy.deepcopy(lease)), now=NOW)
        self.assertIn('EVIDENCE_INTEGRITY_FAILED', refused(report))

    def test_refuses_lease_save_baseline_mismatch(self):
        lease = dict(bound_inputs()['lease'], accountBaselineSha256='ee' * 32)
        report = ra.adapt_reopen(bound_inputs(lease=lease, claim=copy.deepcopy(lease)), now=NOW)
        self.assertIn('EVIDENCE_INTEGRITY_FAILED', refused(report))

    def test_refuses_session_identity_mismatch(self):
        session = dict(SESSION, pid=9999)
        report = ra.adapt_reopen(bound_inputs(session=session), now=NOW)
        self.assertIn('EVIDENCE_INTEGRITY_FAILED', refused(report))

    def test_refuses_missing_original(self):
        report = ra.adapt_reopen(bound_inputs(session=None), now=NOW)
        self.assertIn('REQUEST_INCOMPLETE_CLAIM', refused(report))

    def test_refuses_bad_request_id(self):
        report = ra.adapt_reopen(bound_inputs(requestId='NOT-HEX'), now=NOW)
        self.assertIn('REQUEST_ID_INVALID', refused(report))


class RangeGate(unittest.TestCase):
    def test_default_scope_is_exactly_the_fixed_level(self):
        self.assertEqual(ra.effective_level_scope(None), frozenset({LEVEL}))
        gate = ra.level_scope_gate()
        self.assertEqual(gate['levelId'], LEVEL)
        self.assertTrue(gate['dynamicLevelsRequireAuthorizedScope'])

    def test_dynamic_level_refused_without_authorized_scope(self):
        report = ra.adapt_reopen(bound_inputs(levelId=1073741834, handleLevelId=1073741834),
                                 now=NOW)
        self.assertIn('TOOL_UNAVAILABLE_IN_PROFILE', refused(report))
        self.assertEqual(report['result']['state'], 'rejected')

    def test_dynamic_level_allowed_with_reviewed_scope(self):
        scope = {'kind': 'reviewed-profile-scope', 'authorizedBy': 'coordinator',
                 'reviewId': 'reviewed-profile-20261005', 'levels': [1073741834],
                 'fixedLevelIncluded': True}
        lease = dict(bound_inputs()['lease'], levelId=1073741834)
        review = dict(bound_inputs()['review'], levelId=1073741834)
        report = ra.adapt_reopen(
            bound_inputs(levelId=1073741834, handleLevelId=1073741834, review=review,
                         lease=lease, claim=copy.deepcopy(lease)),
            now=NOW, authorized_scope=scope)
        self.assertNotIn('TOOL_UNAVAILABLE_IN_PROFILE', refused(report))
        self.assertNotIn('READBACK_WRONG_LEVEL', refused(report))
        self.assertEqual(report['result']['state'], 'pending')
        self.assertIn(LEVEL, ra.effective_level_scope(scope))

    def test_unreviewed_scope_is_rejected(self):
        for scope in ({'kind': 'reviewed-profile-scope', 'authorizedBy': 'anyone',
                       'reviewId': 'r', 'levels': [1073741834], 'fixedLevelIncluded': True},
                      {'kind': 'reviewed-profile-scope', 'authorizedBy': 'coordinator',
                       'reviewId': '', 'levels': [1073741834], 'fixedLevelIncluded': True},
                      {'kind': 'reviewed-profile-scope', 'authorizedBy': 'coordinator',
                       'reviewId': 'r', 'levels': [1073741834]}):
            with self.assertRaises(bc.ContractViolation):
                ra.effective_level_scope(scope)

    def test_authorized_level_with_wrong_handle_is_still_refused(self):
        scope = {'kind': 'reviewed-profile-scope', 'authorizedBy': 'coordinator',
                 'reviewId': 'reviewed-profile-20261005', 'levels': [1073741834],
                 'fixedLevelIncluded': True}
        lease = dict(bound_inputs()['lease'], levelId=1073741834)
        review = dict(bound_inputs()['review'], levelId=1073741834)
        report = ra.adapt_reopen(
            bound_inputs(levelId=1073741834, handleLevelId=LEVEL,
                         review=review, lease=lease, claim=copy.deepcopy(lease)),
            now=NOW, authorized_scope=scope)
        self.assertEqual(refused(report), {'READBACK_WRONG_LEVEL'})
        self.assertEqual(report['result']['state'], 'rejected')

    def test_a_request_cannot_authorize_its_own_level(self):
        # The gate is a set membership test against an EXTERNAL grant, never against the
        # requested level.  Passing the requested level as the scope is not a grant.
        report = ra.adapt_reopen(bound_inputs(levelId=1073741834, handleLevelId=1073741834),
                                 now=NOW, authorized_scope=None)
        self.assertIn('TOOL_UNAVAILABLE_IN_PROFILE', refused(report))


class ReadyIsNotReopened(unittest.TestCase):
    def test_claimed_without_dispatch_polls_the_same_request(self):
        report = ra.adapt_reopen(bound_inputs(), now=NOW)
        self.assertEqual(report['result']['state'], 'pending')
        self.assertEqual(report['result']['operationState'], 'claimed')
        self.assertEqual(report['nextAction'], 'poll-same-operation')
        self.assertEqual(report['pollOperationId'], RID)
        self.assertFalse(report['reopenVerified'])
        self.assertEqual(report['result']['stages']['reopen']['status'], 'not-run')

    def test_returned_dispatch_is_pending_not_completed(self):
        report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch()), now=NOW)
        self.assertEqual(report['result']['state'], 'pending')
        self.assertEqual(report['result']['operationState'], 'dispatched')
        self.assertEqual(report['nextAction'], 'poll-same-operation')
        self.assertFalse(report['reopenVerified'])
        self.assertEqual(report['result']['stages']['reopen']['status'], 'blocked')
        self.assertFalse(report['result']['ok'])

    def test_preflight_ready_and_playtest_click_never_pass(self):
        ready = {'status': 'ready', 'preflightPassed': True, 'reopenVerified': False}
        report = ra.adapt_reopen(bound_inputs(preflight=ready, dispatch=None,
                                              playtestClickObserved=True), now=NOW)
        self.assertNotEqual(report['result']['stages']['reopen']['status'], 'pass')
        self.assertFalse(report['reopenVerified'])
        self.assertEqual(report['result']['state'], 'pending')

    def test_a_boolean_acceptance_never_passes(self):
        for bad in (True, {'schema': 2}, {'schema': 2, 'businessVerified': True}):
            report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch(),
                                                  acceptance=bad), now=NOW)
            self.assertNotEqual(report['result']['stages']['reopen']['status'], 'pass')
            self.assertFalse(report['reopenVerified'])

    def test_acceptance_for_another_request_never_passes(self):
        other = dict(valid_acceptance(), requestId='f' * 32)
        report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch(), acceptance=other),
                                 now=NOW)
        self.assertEqual(report['result']['state'], 'pending')
        self.assertNotEqual(report['result']['stages']['reopen']['status'], 'pass')

    def test_independent_acceptance_completes(self):
        report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch(),
                                              acceptance=valid_acceptance()), now=NOW)
        self.assertEqual(report['result']['state'], 'completed')
        self.assertTrue(report['result']['ok'])
        self.assertTrue(report['reopenVerified'])
        self.assertEqual(report['result']['stages']['reopen']['status'], 'pass')
        self.assertTrue(report['result']['stages']['reopen']['evidenceRef'])

    def test_native_preflight_refusal_is_a_rejection(self):
        report = ra.adapt_reopen(bound_inputs(dispatch={'status':
                                                        'dispatch-refused-no-call'}), now=NOW)
        self.assertEqual(report['result']['state'], 'rejected')
        self.assertFalse(report['reopenVerified'])


class StalePacketIsNotEvidence(unittest.TestCase):
    """D23.02.03: an acceptance minted for another dispatch is an old response packet.

    The producer stamps ``dispatchSha256``, so the verdict binds the packet to THIS
    dispatch.  Replacing the acceptance with an earlier one -- or with a packet that names
    no dispatch at all -- must flip ``reopenVerified`` to false; it must never pass.
    """

    def test_acceptance_for_a_different_dispatch_never_passes(self):
        stale = dict(valid_acceptance(), dispatchSha256='55' * 32)
        report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch(), acceptance=stale),
                                 now=NOW)
        self.assertEqual(report['result']['state'], 'pending')
        self.assertNotEqual(report['result']['stages']['reopen']['status'], 'pass')
        self.assertFalse(report['reopenVerified'])
        self.assertFalse(report['result']['ok'])

    def test_acceptance_that_names_no_dispatch_never_passes(self):
        unbound = dict(valid_acceptance())
        unbound.pop('dispatchSha256')
        report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch(),
                                              acceptance=unbound), now=NOW)
        self.assertEqual(report['result']['state'], 'pending')
        self.assertFalse(report['reopenVerified'])

    def test_no_dispatch_digest_on_the_binding_fails_closed(self):
        report = ra.adapt_reopen(bound_inputs(dispatch=returned_dispatch(),
                                              acceptance=valid_acceptance(),
                                              dispatchSha256=None), now=NOW)
        self.assertEqual(report['result']['state'], 'pending')
        self.assertFalse(report['reopenVerified'])
        self.assertNotEqual(report['result']['stages']['reopen']['status'], 'pass')


class PendingBranch(unittest.TestCase):
    def test_poll_same_request_keeps_the_id(self):
        plan = ra.poll_same_request(bound_inputs())
        self.assertTrue(plan['ok'])
        self.assertEqual(plan['operationId'], RID)
        self.assertFalse(plan['dispatch'])
        self.assertFalse(plan['dispatchAttempted'])
        self.assertFalse(plan['retryAttempted'])
        self.assertTrue(plan['mustNotMintNewOperationId'])

    def test_poll_with_a_new_id_is_refused(self):
        plan = ra.poll_same_request(bound_inputs(), requested_operation_id='f' * 32)
        self.assertFalse(plan['ok'])
        self.assertEqual(plan['error']['code'], 'REQUEST_ID_CONFLICT')
        self.assertFalse(plan['dispatch'])
        self.assertFalse(plan['retryAttempted'])


class Purity(unittest.TestCase):
    def test_module_has_no_write_or_process_calls(self):
        import ast
        tree = ast.parse(inspect.getsource(ra))
        called = set()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called.add(func.attr if isinstance(func, ast.Attribute)
                           else getattr(func, 'id', None))
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertEqual(sorted(imported & {'os', 'subprocess', 'pathlib', 'shutil', 'socket',
                                            'io', 'tempfile'}),
                         [], 'the adapter must import no filesystem/process/network module')
        forbidden = {'open', 'write_text', 'write_bytes', 'unlink', 'mkdir', 'makedirs',
                     'system', 'popen', 'Popen', 'remove', 'rename', 'send', 'connect', 'run'}
        self.assertEqual(sorted(called & forbidden), [],
                         'the adapter must make no write/process/network call')

    def test_adapter_writes_no_initialization_flag(self):
        import ast
        tree = ast.parse(inspect.getsource(ra))
        assigned = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = getattr(target, 'id', None) or getattr(target, 'attr', None)
                    assigned.add(name)
        self.assertEqual([n for n in assigned if n and 'initializ' in n.lower()], [],
                         'the adapter must never assign an initialization flag')
        report = ra.adapt_reopen(bound_inputs(), now=NOW)
        self.assertIs(report['initializationWritten'], False)
        self.assertIs(report['result']['targetBinding']['initializationWritten'], False)

    def test_session_fields_match_the_cli_review(self):
        # Quoted from the CLI's review gate rather than re-typed by hand.
        cli = Path(ROOT, 'tools/game-executor/native_write_review.py')
        if cli.exists():
            text = cli.read_text(encoding='utf-8')
            match = re.search(r'^SESSION_FIELDS=\(([^)]*)\)', text, re.M)
            self.assertIsNotNone(match)
            fields = tuple(part.strip().strip("'\"") for part in match.group(1).split(',') if part.strip())
            self.assertEqual(fields, ra.SESSION_FIELDS)


if __name__ == '__main__':
    unittest.main()
