"""T06 -- offline tests for idempotency, target binding and the ownership ledger.

The dispatcher and the material deriver are fakes that count their own calls.  That is the
whole point: "a duplicate request generates no second review" and "at most one dispatch"
are asserted by counting, not by reading the code and believing it.  No game, editor,
helper, bridge, queue or real journal is touched; every path is a TemporaryDirectory.

The suite follows T06's own test matrix (``docs/cordis-plan/tasks/T06.md`` section 6) and
adds the rules the matrix implies.  Specific answers are exact: a plan decision, a state
token, a count, or an exception type.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import operation_state as ops    # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'operation_state'
LEVEL = 1073741839
OTHER_LEVEL = 1073741834
ENTITY = 1077936133
NOW = datetime(2026, 10, 2, 3, 0, 0, tzinfo=timezone.utc)


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def intent(operation_id, *, position=(-12.0, 0.0, 6.0), template=20001034, level=LEVEL,
           capability='entity.create', revision='rev-1', payload=None):
    target = {'handle': 'h-' + operation_id, 'levelId': level,
              'sessionProcessCreation': 133700000000000000,
              'sessionThreadCreation': 133700000000000001}
    body = payload if payload is not None else {'templateId': template,
                                                'position': list(position),
                                                'rotation': [0.0, 0.0, 0.0],
                                                'scale': [1.0, 1.0, 1.0]}
    return {'operationId': operation_id, 'capability_id': capability, 'target': target,
            'payload': body, 'expected_revision': revision}


class Recorder:
    """Fake execution layer.  Everything a test asserts on is one of these counters."""

    def __init__(self, *, ok=True, entity=ENTITY, level=LEVEL, raise_on_dispatch=False):
        self.derived = 0
        self.dispatched = 0
        self.derivations = []
        self.dispatches = []
        self.ok = ok
        self.entity = entity
        self.level = level
        self.raise_on_dispatch = raise_on_dispatch

    def derive_material(self, operation_id, binding):
        """A FRESH material set every call, exactly like orchestrate_write_review does."""
        self.derived += 1
        self.derivations.append(operation_id)
        return {'requestId': operation_id, 'reviewPath': 'review-%s.json' % uuid.uuid4().hex[:12],
                'session': 'session.json', 'baseline': 'baseline-run-%d' % self.derived,
                'journalRef': '.runtime/authoring/requests/%s' % operation_id}

    def dispatch(self, command):
        self.dispatched += 1
        self.dispatches.append(command)
        if self.raise_on_dispatch:
            raise TimeoutError('the native call did not answer')
        return {'ok': self.ok, 'requestId': command['requestId'],
                'backend': {'ok': self.ok, 'action': 'create', 'levelId': self.level,
                            'entityId': self.entity, 'run': 'run-1'}}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'ledger'
        self.ledger = ops.OperationLedger(self.root, clock=lambda: NOW)
        self.recorder = Recorder()

    def run_operation(self, operation_id, recorder=None, **overrides):
        recorder = recorder or self.recorder
        return self.ledger.run(intent(operation_id, **overrides), owner='worker-1',
                               derive_material=recorder.derive_material,
                               dispatch=recorder.dispatch)


# --------------------------------------------------------------------------- #
# Step 02 -- canonicalisation, before the claim
# --------------------------------------------------------------------------- #

class InputRules(unittest.TestCase):
    def test_a_json_bool_is_not_an_integer_id(self):
        with self.assertRaises(ops.InputInvalid):
            ops.uint32(True, field='entityId')
        with self.assertRaises(ops.InputInvalid):
            ops.uint32(False, field='entityId')

    def test_a_non_finite_number_is_refused_before_anything_else(self):
        for bad in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(value=bad):
                with self.assertRaises(ops.InputInvalid):
                    ops.canonicalize({'position': [bad, 0.0, 0.0]})

    def test_an_out_of_range_id_is_refused_not_truncated(self):
        for bad in (0, -1, 2 ** 32):
            with self.subTest(value=bad):
                with self.assertRaises(ops.InputInvalid):
                    ops.uint32(bad, field='entityId')

    def test_a_signed_zero_is_one_placement_not_two_commands(self):
        one = ops.binding_digest(ops.binding_for(capability_id='entity.create', target={'levelId': 1},
                                                 payload={'position': [0.0, 0.0, 0.0]}))
        two = ops.binding_digest(ops.binding_for(capability_id='entity.create', target={'levelId': 1},
                                                 payload={'position': [-0.0, -0.0, 0.0]}))
        self.assertEqual(one, two)

    def test_the_binding_digest_is_stable_across_key_order(self):
        left = ops.binding_digest(ops.binding_for(capability_id='entity.create',
                                                  target={'levelId': 1, 'handle': 'h'},
                                                  payload={'a': 1, 'b': [1, 2, 3]}))
        right = ops.binding_digest(ops.binding_for(capability_id='entity.create',
                                                   target={'handle': 'h', 'levelId': 1},
                                                   payload={'b': [1, 2, 3], 'a': 1}))
        self.assertEqual(left, right)

    def test_bad_input_leaves_no_trace_and_dispatches_nothing(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / 'ledger'
            ledger = ops.OperationLedger(root, clock=lambda: NOW)
            recorder = Recorder()
            bad = intent('op-bad-input')
            bad['payload']['position'] = [float('nan'), 0.0, 0.0]
            with self.assertRaises(ops.InputInvalid):
                ledger.run(bad, owner='w', derive_material=recorder.derive_material,
                           dispatch=recorder.dispatch)
            self.assertEqual(recorder.derived, 0)
            self.assertEqual(recorder.dispatched, 0)
            self.assertFalse((root / 'op-bad-input').exists(),
                             'a refusal before the claim leaves no trace to reconcile')


# --------------------------------------------------------------------------- #
# Matrix row 1 -- same parameter replay
# --------------------------------------------------------------------------- #

class ReplayIsIdempotent(LedgerCase):
    def test_the_same_operation_twice_dispatches_once_and_replays_the_receipt(self):
        first = self.run_operation('op-replay-1')
        self.assertEqual(first['decision'], 'completed')
        self.assertTrue(first['dispatched'])
        self.assertEqual(self.recorder.derived, 1)
        self.assertEqual(self.recorder.dispatched, 1)

        second = self.run_operation('op-replay-1')
        self.assertEqual(second['decision'], 'replay')
        self.assertFalse(second['dispatched'], 'a replay dispatches nothing')
        self.assertEqual(second['receipt'], first['receipt'], 'the ORIGINAL receipt is returned')
        self.assertEqual(self.recorder.derived, 1)
        self.assertEqual(self.recorder.dispatched, 1)

    def test_a_replay_derives_no_material_at_all(self):
        """The bug G01 D19 describes: deriving first turns a replay into a conflict."""
        self.run_operation('op-replay-2')
        before = (self.recorder.derived, len(self.recorder.derivations))
        self.run_operation('op-replay-2')
        self.assertEqual((self.recorder.derived, len(self.recorder.derivations)), before)

    def test_the_material_is_fixed_after_the_first_attempt(self):
        """Step 05: material is bound once; a second, different set is a conflict."""
        self.run_operation('op-replay-3')
        with self.assertRaises(ops.OperationConflict):
            self.ledger.bind_material('op-replay-3', request_id='op-replay-3',
                                      material={'reviewPath': 'a-different-review.json'},
                                      journal_ref='x')
        bound = json.loads((self.root / 'op-replay-3' / ops.MATERIAL_NAME).read_text())
        self.assertEqual(bound['requestId'], 'op-replay-3')
        self.assertTrue(bound['materialDigest'])


# --------------------------------------------------------------------------- #
# Matrix rows 2 and 3 -- parameter and target conflict, concurrency
# --------------------------------------------------------------------------- #

class Conflicts(LedgerCase):
    def test_a_different_position_is_refused_before_any_material(self):
        self.run_operation('op-conflict-1')
        recorder = Recorder()
        outcome = self.run_operation('op-conflict-1', recorder=recorder, position=(1.0, 2.0, 3.0))
        self.assertEqual(outcome['decision'], 'conflict')
        self.assertEqual(outcome['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(recorder.derived, 0)
        self.assertEqual(recorder.dispatched, 0)

    def test_a_different_template_is_refused(self):
        self.run_operation('op-conflict-2')
        outcome = self.run_operation('op-conflict-2', template=20001002)
        self.assertEqual(outcome['decision'], 'conflict')

    def test_a_different_target_is_refused(self):
        self.run_operation('op-conflict-3')
        outcome = self.run_operation('op-conflict-3', level=OTHER_LEVEL)
        self.assertEqual(outcome['decision'], 'conflict')

    def test_a_different_capability_is_refused(self):
        self.run_operation('op-conflict-4')
        outcome = self.run_operation('op-conflict-4', capability='entity.save',
                                     payload={'action': 'save'})
        self.assertEqual(outcome['decision'], 'conflict')

    def test_two_threads_racing_the_same_operation_produce_one_claim_and_one_dispatch(self):
        """Matrix row 3.  Sequential tests cannot show this; a barrier can."""
        recorder = Recorder()
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)
                outcomes.append(self.ledger.run(intent('op-race-1'), owner='worker-%d'
                                                % threading.get_ident(),
                                                derive_material=recorder.derive_material,
                                                dispatch=recorder.dispatch))
            except Exception as exc:                       # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [], 'a race must be resolved by the claim, not by an exception')
        self.assertEqual(recorder.dispatched, 1,
                         'at most one side effect: %d dispatches' % recorder.dispatched)
        self.assertEqual(recorder.derived, 1,
                         'the loser must not derive a second review: %d derivations'
                         % recorder.derived)
        decisions = sorted(outcome['decision'] for outcome in outcomes)
        self.assertIn('completed', decisions)
        self.assertIn(decisions[1], ('replay', 'pending'))
        owner_claim = json.loads((self.root / 'op-race-1' / ops.CLAIM_NAME).read_text())
        self.assertTrue(owner_claim['owner'])
        self.assertEqual(owner_claim['bindingDigest'], ops.binding_digest(owner_claim['binding']),
                         'the stored digest really is the digest of the stored binding')

    def test_the_claim_file_is_the_only_mutual_exclusion(self):
        self.ledger.claim('op-claim-1', {'binding': ops.binding_for(
            capability_id='entity.create', target={'levelId': LEVEL}, payload={})}, owner='a')
        second = self.ledger.claim('op-claim-1', {'binding': ops.binding_for(
            capability_id='entity.create', target={'levelId': LEVEL}, payload={})}, owner='b')
        self.assertFalse(second['claimed'])
        self.assertEqual(second['owner'], 'a', 'the first claim holder keeps the operation')


# --------------------------------------------------------------------------- #
# Matrix row 5 -- crash windows
# --------------------------------------------------------------------------- #

class CrashWindows(LedgerCase):
    def test_a_claim_with_no_material_is_pending_and_never_resent(self):
        self.ledger.claim('op-crash-1', intent('op-crash-1'), owner='w')
        recorder = Recorder()
        outcome = self.ledger.run(intent('op-crash-1'), owner='w',
                                  derive_material=recorder.derive_material,
                                  dispatch=recorder.dispatch)
        self.assertEqual(outcome['decision'], 'pending')
        self.assertEqual(self.ledger.state_of('op-crash-1'), 'claimed')
        self.assertEqual(recorder.dispatched, 0, 'a claim without a result is never resent')
        self.assertEqual(recorder.derived, 0)

    def test_dispatch_evidence_without_a_receipt_is_pending_not_a_failure(self):
        self.ledger.claim('op-crash-2', intent('op-crash-2'), owner='w')
        (self.root / 'op-crash-2' / 'helper-request.json').write_text('{}', encoding='utf-8')
        self.assertEqual(self.ledger.state_of('op-crash-2'), 'dispatched')
        outcome = self.ledger.run(intent('op-crash-2'), owner='w',
                                  derive_material=Recorder().derive_material,
                                  dispatch=Recorder().dispatch)
        self.assertEqual(outcome['decision'], 'pending')
        reconcile = self.ledger.reconcile('op-crash-2')
        self.assertEqual(reconcile['reconcileState'], 'unknown')
        self.assertEqual(reconcile['dispatchEvidence'], ['helper-request.json'])

    def test_a_directory_without_its_claim_is_unknown_not_never_claimed(self):
        (self.root / 'op-crash-3').mkdir(parents=True)
        self.assertEqual(self.ledger.state_of('op-crash-3'), 'outcome-unknown')
        outcome = self.ledger.plan('op-crash-3', intent('op-crash-3'))
        self.assertEqual(outcome['decision'], 'unknown')
        self.assertEqual(outcome['code'], 'REQUEST_INCOMPLETE_CLAIM')

    def test_a_dispatch_that_raises_becomes_unknown_and_is_never_retried(self):
        recorder = Recorder(raise_on_dispatch=True)
        outcome = self.run_operation('op-crash-4', recorder=recorder)
        self.assertEqual(outcome['decision'], 'unknown')
        self.assertEqual(outcome['state'], 'outcome-unknown')
        self.assertEqual(self.ledger.state_of('op-crash-4'), 'outcome-unknown')
        self.assertEqual(recorder.dispatched, 1)
        second = self.run_operation('op-crash-4', recorder=recorder)
        self.assertEqual(second['decision'], 'unknown')
        self.assertEqual(recorder.dispatched, 1, 'an unknown outcome is never resent')
        self.assertEqual(self.ledger.reconcile('op-crash-4')['reconcileState'], 'unknown')

    def test_absence_of_an_object_is_never_read_as_absence_of_a_write(self):
        """Step 07: the unknown stays unknown until the original receipt is read."""
        self.ledger.claim('op-crash-5', intent('op-crash-5'), owner='w')
        self.assertEqual(self.ledger.reconcile('op-crash-5')['reconcileState'], 'unknown')
        self.assertIn('do not resend', self.ledger.reconcile('op-crash-5')['note'])

    def test_a_reload_sees_the_in_flight_operation_and_only_queries_it(self):
        """T03 / DS-07: a reloaded instance was told nothing, so it must be able to LOOK."""
        self.ledger.claim('op-reload-1', intent('op-reload-1'), owner='previous-instance')
        (self.root / 'op-reload-1' / 'helper-request.json').write_text('{}', encoding='utf-8')
        fresh = ops.OperationLedger(self.root, clock=lambda: NOW)
        open_operations = fresh.list_open_operations()
        self.assertEqual([row['operationId'] for row in open_operations], ['op-reload-1'])
        row = open_operations[0]
        self.assertEqual(row['operationState'], 'dispatched')
        self.assertEqual(row['reconcileState'], 'unknown')
        self.assertEqual(row['owner'], 'previous-instance')
        self.assertEqual(row['capabilityId'], 'entity.create')
        self.assertEqual(row['dispatchEvidence'], ['helper-request.json'])
        self.assertEqual(row['nextAction'], 'poll-same-operation')
        # The old name still works, and returns the same thing.
        self.assertEqual(fresh.pending(), open_operations)
        recorder = Recorder()
        outcome = fresh.run(intent('op-reload-1'), owner='new-instance',
                            derive_material=recorder.derive_material, dispatch=recorder.dispatch)
        self.assertEqual(outcome['decision'], 'pending')
        self.assertEqual(recorder.dispatched, 0)
        self.assertEqual(recorder.derived, 0)

    def test_a_reloaded_instance_does_not_see_terminal_operations(self):
        recorder = Recorder()
        self.ledger.run(intent('op-reload-2'), owner='w',
                        derive_material=recorder.derive_material, dispatch=recorder.dispatch)
        self.assertEqual(self.ledger.list_open_operations(), [])

    def test_listing_open_operations_has_no_side_effect(self):
        self.ledger.claim('op-reload-3', intent('op-reload-3'), owner='w')
        before = sorted(p.name for p in (self.root / 'op-reload-3').iterdir())
        self.ledger.list_open_operations()
        after = sorted(p.name for p in (self.root / 'op-reload-3').iterdir())
        self.assertEqual(before, after, 'a listing writes nothing at all')


# --------------------------------------------------------------------------- #
# Matrix row 6 -- late receipts
# --------------------------------------------------------------------------- #

class LateReceipts(LedgerCase):
    def setUp(self):
        super().setUp()
        self.ledger.claim('op-late-1', intent('op-late-1'), owner='w')
        self.ledger.bind_material('op-late-1', request_id='op-late-1',
                                  material={'reviewPath': 'r.json'}, journal_ref='j')

    def receipt(self, *, request_id='op-late-1', level=LEVEL, ok=True):
        return {'ok': ok, 'requestId': request_id,
                'backend': {'ok': ok, 'action': 'create', 'levelId': level, 'entityId': ENTITY}}

    def test_a_late_receipt_is_attributed_to_the_original_operation(self):
        outcome = self.ledger.late_receipt('op-late-1', self.receipt())
        self.assertTrue(outcome['attributed'])
        self.assertEqual(outcome['state'], 'known-complete')
        self.assertEqual(self.ledger.state_of('op-late-1'), 'known-complete')

    def test_a_late_receipt_for_another_request_is_refused(self):
        outcome = self.ledger.late_receipt('op-late-1', self.receipt(request_id='somebody-else'))
        self.assertFalse(outcome['attributed'])
        self.assertEqual(outcome['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.ledger.state_of('op-late-1'), 'claimed',
                         'the original operation is untouched by a stranger\'s receipt')

    def test_a_late_receipt_for_another_level_is_refused(self):
        outcome = self.ledger.late_receipt('op-late-1', self.receipt(level=OTHER_LEVEL))
        self.assertFalse(outcome['attributed'])
        self.assertEqual(outcome['code'], 'TARGET_HANDLE_RECEIPT_CHANGED')
        self.assertEqual(self.ledger.state_of('op-late-1'), 'claimed')

    def test_a_second_differing_receipt_does_not_overwrite_the_first_answer(self):
        self.assertTrue(self.ledger.late_receipt('op-late-1', self.receipt())['attributed'])
        with self.assertRaises(ops.OperationConflict):
            self.ledger.publish('op-late-1', self.receipt(ok=False))
        self.assertEqual(self.ledger.state_of('op-late-1'), 'known-complete')

    def test_an_identical_receipt_arriving_twice_is_accepted(self):
        self.assertTrue(self.ledger.late_receipt('op-late-1', self.receipt())['attributed'])
        again = self.ledger.late_receipt('op-late-1', self.receipt())
        self.assertTrue(again['attributed'])

    def test_a_receipt_for_an_operation_that_was_never_claimed_is_refused(self):
        outcome = self.ledger.late_receipt('op-never-claimed', self.receipt())
        self.assertFalse(outcome['attributed'])


# --------------------------------------------------------------------------- #
# Matrix row 7 -- target identity
# --------------------------------------------------------------------------- #

class TargetIdentity(unittest.TestCase):
    def setUp(self):
        self.good = load('handle-good.json')
        self.restarted = load('handle-same-pid-different-creation.json')

    def test_a_fresh_matching_handle_is_accepted(self):
        self.assertEqual(ops.validate_target(self.good, expected_level_id=LEVEL, now=NOW), [])

    def test_the_same_pid_with_a_different_creation_time_is_a_different_target(self):
        self.assertEqual(self.good['sessionPid'], self.restarted['sessionPid'],
                         'the fixture really does reuse the pid')
        problems = ops.validate_target(self.restarted, previous=self.good, now=NOW)
        self.assertTrue(any('TARGET_HANDLE_RECEIPT_CHANGED' in p for p in problems))
        self.assertNotEqual(ops.target_key(self.good), ops.target_key(self.restarted))

    def test_a_changed_level_is_refused(self):
        problems = ops.validate_target(self.restarted, expected_level_id=LEVEL, now=NOW)
        self.assertTrue(any('not the expected' in p for p in problems))

    def test_a_handle_with_no_session_identity_is_unverified(self):
        bare = dict(self.good)
        bare.pop('sessionProcessCreation')
        problems = ops.validate_target(bare, now=NOW)
        self.assertTrue(any('TARGET_HANDLE_UNVERIFIED' in p for p in problems))

    def test_a_stale_handle_is_refused_when_a_freshness_window_is_given(self):
        self.assertEqual(ops.validate_target(self.good, now=NOW, max_age_seconds=3600), [],
                         'minted at 02:15Z, seen at 03:00Z: well inside an hour')
        problems = ops.validate_target(self.good, now=NOW, max_age_seconds=600)
        self.assertTrue(any('older than' in p for p in problems),
                        '45 minutes old is stale against a ten-minute window')

    def test_a_refused_target_prevents_the_claim_entirely(self):
        with tempfile.TemporaryDirectory() as name:
            ledger = ops.OperationLedger(Path(name), clock=lambda: NOW)
            recorder = Recorder()
            outcome = ledger.run(intent('op-badtarget-1', level=LEVEL), owner='w',
                                 derive_material=recorder.derive_material,
                                 dispatch=recorder.dispatch,
                                 verify_target=lambda handle: ops.validate_target(
                                     self.restarted, previous=handle))
            self.assertEqual(outcome['decision'], 'refused')
            self.assertEqual(recorder.dispatched, 0)
            self.assertEqual(recorder.derived, 0)
            self.assertFalse((Path(name) / 'op-badtarget-1').exists(),
                             'a refused target leaves nothing to reconcile')


# --------------------------------------------------------------------------- #
# Matrix rows 8 and 9 -- ownership
# --------------------------------------------------------------------------- #

class Ownership(LedgerCase):
    def publish_create(self, operation_id, *, entity=ENTITY, level=LEVEL):
        self.ledger.claim(operation_id, intent(operation_id, level=level), owner='w')
        self.ledger.bind_material(operation_id, request_id=operation_id, material={'r': 'r.json'},
                                  journal_ref='j')
        self.ledger.publish(operation_id, {'ok': True, 'requestId': operation_id,
                                           'backend': {'ok': True, 'action': 'create',
                                                       'levelId': level, 'entityId': entity}})

    def test_an_entity_created_this_run_in_this_level_is_owned(self):
        self.publish_create('op-own-1')
        result = self.ledger.ownership(LEVEL)
        self.assertEqual([row['entityId'] for row in result['owned']], [ENTITY])
        self.assertEqual(result['owned'][0]['operationId'], 'op-own-1')
        self.assertEqual(result['owned'][0]['levelId'], LEVEL)
        self.assertTrue(result['owned'][0]['receiptSha256'])

    def test_an_existing_entity_with_no_create_receipt_is_not_owned(self):
        """Matrix row 8: presence is not ownership."""
        result = self.ledger.ownership(LEVEL, candidate_ids=[ENTITY])
        self.assertEqual(result['owned'], [])
        self.assertEqual(len(result['refused']), 1)
        self.assertEqual(result['refused'][0]['code'], 'CLEANUP_ID_NOT_OWNED_BY_THIS_RUN')
        self.assertIn('not proof of ownership', result['refused'][0]['reason'])

    def test_the_same_id_in_another_level_is_not_owned_here(self):
        """The measured cross-level trap: an id-only query returns the wrong operation."""
        trap = load('bottom-receipt-create.json')
        self.assertEqual(trap['_crossLevelTrap']['receipt']['backend']['entityId'], ENTITY)
        self.publish_create('op-own-2', level=OTHER_LEVEL)
        here = self.ledger.ownership(LEVEL, candidate_ids=[ENTITY])
        self.assertEqual(here['owned'], [])
        self.assertEqual(len(here['refused']), 1)
        there = self.ledger.ownership(OTHER_LEVEL, candidate_ids=[ENTITY])
        self.assertEqual(len(there['owned']), 1)
        self.assertEqual(there['owned'][0]['operationId'], 'op-own-2')

    def test_a_receipt_that_names_no_level_is_unknown_not_owned(self):
        self.ledger.claim('op-own-3', intent('op-own-3'), owner='w')
        self.ledger.bind_material('op-own-3', request_id='op-own-3', material={'r': 'r'},
                                  journal_ref='j')
        self.ledger.publish('op-own-3', {'ok': True, 'requestId': 'op-own-3',
                                         'backend': {'ok': True, 'action': 'create',
                                                     'entityId': ENTITY}})
        result = self.ledger.ownership(LEVEL, candidate_ids=[ENTITY])
        self.assertEqual(result['owned'], [])
        self.assertEqual(len(result['unknown']), 1)
        self.assertEqual(result['unknown'][0]['code'], 'TARGET_HANDLE_UNVERIFIED')

    def test_a_failed_create_receipt_confers_no_ownership(self):
        self.ledger.claim('op-own-4', intent('op-own-4'), owner='w')
        self.ledger.bind_material('op-own-4', request_id='op-own-4', material={'r': 'r'},
                                  journal_ref='j')
        self.ledger.publish('op-own-4', {'ok': False, 'requestId': 'op-own-4',
                                         'backend': {'ok': False, 'action': 'create',
                                                     'levelId': LEVEL, 'entityId': ENTITY}})
        self.assertEqual(self.ledger.ownership(LEVEL, candidate_ids=[ENTITY])['owned'], [])

    def test_ownership_can_be_restricted_to_this_runs_operation_ids(self):
        self.publish_create('op-own-5')
        self.publish_create('op-own-6', entity=ENTITY + 1)
        only_five = self.ledger.ownership(LEVEL, operation_ids=['op-own-5'])
        self.assertEqual([row['entityId'] for row in only_five['owned']], [ENTITY])
        all_rows = self.ledger.ownership(LEVEL)
        self.assertEqual(sorted(row['entityId'] for row in all_rows['owned']),
                         [ENTITY, ENTITY + 1])

    def test_ownership_can_be_restricted_to_a_time_window(self):
        self.publish_create('op-own-7')
        after = (NOW + timedelta(hours=1)).isoformat()
        self.assertEqual(self.ledger.ownership(LEVEL, since_utc=after)['owned'], [])
        before = (NOW - timedelta(hours=1)).isoformat()
        self.assertEqual(len(self.ledger.ownership(LEVEL, since_utc=before)['owned']), 1)

    def test_a_candidate_id_is_a_question_not_an_assertion(self):
        """There is no code path where a caller-supplied id becomes owned by declaration."""
        self.publish_create('op-own-8')
        for candidate in (1, 999, 2 ** 31):
            with self.subTest(candidate=candidate):
                result = self.ledger.ownership(LEVEL, candidate_ids=[candidate])
                self.assertEqual(result['owned'], [])
                self.assertEqual(len(result['refused']), 1)


# --------------------------------------------------------------------------- #
# Persistence failure
# --------------------------------------------------------------------------- #

class PersistenceFailure(LedgerCase):
    def test_a_failed_ledger_write_stops_the_dispatch(self):
        """If the row cannot be written, the operation cannot be reconciled -- so no dispatch."""
        original = self.ledger._atomic_write

        def broken(operation_id, name, payload):
            if name == ops.RECORD_NAME:
                raise ops.PersistenceFailed('the ledger volume went away')
            return original(operation_id, name, payload)

        self.ledger._atomic_write = broken
        recorder = Recorder()
        with self.assertRaises(ops.PersistenceFailed):
            self.ledger.run(intent('op-persist-1'), owner='w',
                            derive_material=recorder.derive_material, dispatch=recorder.dispatch)
        self.assertEqual(recorder.derived, 0)
        self.assertEqual(recorder.dispatched, 0,
                         'a claim whose row could not be written must not reach the game')
        self.assertEqual(recorder.dispatched, 0)
        # The claim exists, so the operation is not "never claimed" -- it is unresolved, and
        # that is exactly what a reconciler must be told.
        self.assertEqual(self.ledger.state_of('op-persist-1'), 'claimed')

    def test_a_dispatch_whose_receipt_cannot_be_published_is_unknown_not_success(self):
        original = self.ledger._atomic_write

        def broken(operation_id, name, payload):
            if name == ops.RECEIPT_NAME:
                raise ops.PersistenceFailed('the ledger volume went away')
            return original(operation_id, name, payload)

        self.ledger._atomic_write = broken
        recorder = Recorder()
        with self.assertRaises(ops.PersistenceFailed):
            self.ledger.run(intent('op-persist-2'), owner='w',
                            derive_material=recorder.derive_material, dispatch=recorder.dispatch)
        self.assertEqual(recorder.dispatched, 1, 'the write really was dispatched')
        self.assertNotEqual(self.ledger.state_of('op-persist-2'), 'known-complete',
                            'a receipt that could not be recorded is not a success')

    def test_a_dispatch_that_returns_nothing_is_unknown(self):
        recorder = Recorder()
        outcome = self.ledger.run(
            intent('op-persist-3'), owner='w', derive_material=recorder.derive_material,
            dispatch=lambda command: None)
        self.assertEqual(outcome['decision'], 'unknown')
        self.assertEqual(self.ledger.state_of('op-persist-3'), 'outcome-unknown')
        self.assertEqual(self.ledger.reconcile('op-persist-3')['reconcileState'], 'unknown')


# --------------------------------------------------------------------------- #
# plan() has no side effect -- the property the whole ordering rests on
# --------------------------------------------------------------------------- #

class PlanIsPure(unittest.TestCase):
    def test_planning_a_new_operation_creates_nothing(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / 'ledger'
            ledger = ops.OperationLedger(root, clock=lambda: NOW)
            decision = ledger.plan('op-pure-1', intent('op-pure-1'))
            self.assertEqual(decision['decision'], 'new')
            self.assertFalse(root.exists(), 'plan() must not create the ledger root')
            self.assertFalse((root / 'op-pure-1').exists())

    def test_planning_twice_does_not_claim_twice(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / 'ledger'
            ledger = ops.OperationLedger(root, clock=lambda: NOW)
            self.assertEqual(ledger.plan('op-pure-2', intent('op-pure-2'))['decision'], 'new')
            self.assertEqual(ledger.plan('op-pure-2', intent('op-pure-2'))['decision'], 'new')
            ledger.claim('op-pure-2', intent('op-pure-2'), owner='w')
            self.assertEqual(ledger.plan('op-pure-2', intent('op-pure-2'))['decision'], 'pending')


class RevisionGate(LedgerCase):
    """T06 step 04: a NEW operation is gated on the revision; a REPLAY is not."""

    def test_a_stale_revision_refuses_a_new_operation_before_it_claims(self):
        recorder = Recorder()
        outcome = self.ledger.run(intent('op-rev-1', revision='rev-stale'), owner='w',
                                  derive_material=recorder.derive_material,
                                  dispatch=recorder.dispatch,
                                  current_revision=lambda target: 'rev-current')
        self.assertEqual(outcome['decision'], 'refused')
        self.assertEqual(outcome['code'], 'TARGET_STALE_REVISION')
        self.assertEqual(outcome['actualRevision'], 'rev-current')
        self.assertEqual(recorder.derived, 0)
        self.assertEqual(recorder.dispatched, 0)
        self.assertFalse((self.root / 'op-rev-1').exists(),
                         'a version-gate refusal leaves nothing to reconcile')

    def test_a_matching_revision_proceeds(self):
        recorder = Recorder()
        outcome = self.ledger.run(intent('op-rev-2', revision='rev-current'), owner='w',
                                  derive_material=recorder.derive_material,
                                  dispatch=recorder.dispatch,
                                  current_revision=lambda target: 'rev-current')
        self.assertEqual(outcome['decision'], 'completed')
        self.assertEqual(recorder.dispatched, 1)

    def test_a_replay_is_not_re_gated_on_the_revision(self):
        """Step 04 verbatim: an existing same-semantics request returns the original record,
        and does NOT require the revision it was created against to still be current."""
        recorder = Recorder()
        self.ledger.run(intent('op-rev-3', revision='rev-current'), owner='w',
                        derive_material=recorder.derive_material, dispatch=recorder.dispatch,
                        current_revision=lambda target: 'rev-current')
        replay = self.ledger.run(intent('op-rev-3', revision='rev-current'), owner='w',
                                 derive_material=recorder.derive_material,
                                 dispatch=recorder.dispatch,
                                 current_revision=lambda target: 'rev-MOVED-ON')
        self.assertEqual(replay['decision'], 'replay',
                         'the target moving on does not invalidate an already-answered operation')
        self.assertEqual(recorder.dispatched, 1)

    def test_the_revision_is_not_part_of_the_command_identity(self):
        digest_plain = ops.binding_digest(ops.binding_for(
            capability_id='entity.create', target={'levelId': LEVEL}, payload={'a': 1}))
        claim = {'binding': ops.binding_for(capability_id='entity.create',
                                            target={'levelId': LEVEL}, payload={'a': 1})}
        self.assertNotIn('expectedRevision', claim['binding'])
        self.assertEqual(digest_plain, ops.binding_digest(claim['binding']))


class LedgerDoesNotTouchTheRealJournal(unittest.TestCase):
    """The bottom layer is the truth; this layer must never write into it."""

    def test_the_module_has_no_path_of_its_own(self):
        """The strongest available form of "it cannot write where it should not".

        There is no ROOT and no default ledger path, so every write target is a directory the
        caller supplied.  That is a structural property, not a promise -- which is why it is
        asserted against the module object rather than against a code review.
        """
        self.assertFalse(hasattr(ops, 'ROOT'),
                         'a module-level project root would let this ledger reach the real '
                         'journal without anybody passing it')
        import inspect
        source = inspect.getsource(ops)
        self.assertNotIn('JOURNAL_ROOT', source)
        self.assertNotIn('Path(__file__)', source)
        self.assertIn("self.root = Path(root)", source)

    def test_a_run_reports_the_journal_reference_rather_than_copying_a_verdict(self):
        with tempfile.TemporaryDirectory() as name:
            ledger = ops.OperationLedger(Path(name), clock=lambda: NOW)
            recorder = Recorder()
            ledger.run(intent('op-ref-1'), owner='w', derive_material=recorder.derive_material,
                       dispatch=recorder.dispatch)
            record = json.loads((Path(name) / 'op-ref-1' / ops.RECORD_NAME).read_text())
            self.assertEqual(record['journalRef'], '.runtime/authoring/requests/op-ref-1')
            self.assertEqual(record['requestId'], 'op-ref-1')


if __name__ == '__main__':
    unittest.main()
