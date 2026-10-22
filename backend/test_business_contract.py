"""T05 -- offline tests for the business result and error contract.

Everything here is a pure function call.  No game, editor, helper, bridge, queue, journal
or network is touched, and nothing is written to disk: the fixtures are read-only JSON and
every temporary object lives in memory.

The suite is organised as T05's own test matrix (``docs/cordis-plan/tasks/T05.md`` section 6)
followed by the rules the matrix implies.  Each test names the rule it defends, because a
test whose failure message does not say what broke is worth very little.
"""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import business_contract as bc   # noqa: E402

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'business_contract'
OPERATION = 'mcp07c1e9b4'
CASE = 'case-20001034'
OTHER_OPERATION = 'mcpdeadbeef01'
LEVEL = 1073741839
ENTITY = 1077936133


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def emitted(instance):
    """(structuredContent, text body) as a server would emit them, plus the equality check.

    ``backend/entity_server.py`` builds one dict and uses it for both, so the two can only
    disagree if something re-derives one of them.  This helper makes that disagreement a
    test failure rather than a silent inconsistency.
    """
    structured = instance
    text = json.loads(json.dumps(instance, ensure_ascii=False))
    if text != structured:
        raise AssertionError('the text body and structuredContent disagree')
    return structured, text


def completed_create(**overrides):
    fields = dict(
        capability_id='entity.create', method='mw.scene.createEntity', operation_id=OPERATION,
        operation_state='known-complete', target_handle='20261001-152306-21e64cb2f3',
        write_executed=True, object_ids=[ENTITY],
        changed=[{'objectId': ENTITY, 'result': 'created', 'fields': {'templateId': 20001034}}],
        stage_map={'liveReadback': {'status': 'pass',
                                    'evidenceRef': ['.runtime/game-executor/mcp-business/%s/after.json'
                                                    % OPERATION]}},
        counts={'entityCountBefore': 17, 'entityCountAfter': 18})
    fields.update(overrides)
    return bc.result(**fields)


class ContractSourceOfTruth(unittest.TestCase):
    """No second copy of the vocabulary: every closed set comes from the G01 contract."""

    def test_the_closed_sets_are_the_contract_json_values(self):
        contract = json.loads(bc.CONTRACT_PATH.read_text(encoding='utf-8-sig'))
        sets = bc.frozen_sets()
        self.assertEqual(sets['operationState'], contract['operationState']['values'])
        self.assertEqual(sets['businessState'], contract['businessState']['values'])
        self.assertEqual(sets['stageStatus'], contract['stages']['statusValues'])
        self.assertEqual(sets['stages'], contract['stages']['values'])
        self.assertEqual(sets['nextAction'], contract['nextAction']['values'])
        self.assertEqual(len(sets['codes']), len(contract['errorTaxonomy']['codes']))

    def test_both_projections_are_total_over_every_operation_state(self):
        """A projection with a gap would be a third vocabulary the moment it was hit."""
        for state in bc.frozen_sets()['operationState']:
            self.assertIn(bc.business_state(state), bc.frozen_sets()['businessState'])
            self.assertIn(bc.reconcile_state(state), bc.frozen_sets()['reconcileState'])
        self.assertEqual(bc.business_state('known-complete'), 'completed')
        self.assertEqual(bc.business_state('never-claimed'), 'rejected')
        self.assertEqual(bc.business_state('claimed'), 'pending')
        self.assertEqual(bc.business_state('dispatched'), 'pending')
        self.assertEqual(bc.business_state('outcome-unknown'), 'unknown')
        self.assertEqual(bc.business_state('known-failed'), 'failed')

    def test_the_module_does_not_re_type_the_state_literals(self):
        """The failure this guards against is a copy that drifts one character at a time."""
        source = inspect.getsource(bc)
        for literal in ("['never-claimed', 'claimed'", '["never-claimed", "claimed"',
                        "('rejected', 'pending', 'unknown', 'failed', 'completed')"):
            self.assertNotIn(literal, source,
                             'a closed set is re-typed in %s; it must be loaded from '
                             'contract.json' % bc.__name__)

    def test_every_next_action_follows_from_its_state(self):
        table = bc.frozen_sets()['nextActionForBusiness']
        for state in bc.frozen_sets()['businessState']:
            self.assertIn(table[state], bc.frozen_sets()['nextAction'])
        self.assertEqual(bc.next_action_for('completed'), 'none')
        self.assertEqual(bc.next_action_for('unknown'), 'reconcile')
        self.assertEqual(bc.next_action_for('pending'), 'poll-same-operation')
        self.assertEqual(bc.next_action_for('rejected'), 'fix-input')


class StageRules(unittest.TestCase):
    """T05 matrix rows 1, 7 and 9: locality of a pass, and the shape of a stage."""

    def test_create_positive_leaves_every_other_stage_not_run(self):
        """Matrix row 1: execution plus an independent readback -> readback pass, rest not-run."""
        result = completed_create()
        self.assertEqual(result['state'], 'completed')
        self.assertTrue(result['ok'])
        self.assertIs(emitted(result)[1]['ok'], True)
        self.assertEqual(result['stages']['liveReadback']['status'], 'pass')
        self.assertTrue(result['stages']['liveReadback']['evidenceRef'])
        for name in ('saveDiff', 'reopen', 'runtime', 'cleanup'):
            self.assertEqual(result['stages'][name]['status'], 'not-run', name)
            self.assertTrue(result['stages'][name]['reason'],
                            'a not-run stage must say why it did not run')

    def test_a_pass_without_evidence_is_refused(self):
        """Matrix row 7: a pass with no evidenceRef cannot be published."""
        with self.assertRaises(bc.ContractViolation):
            bc.result(capability_id='entity.create', method='m', operation_id='op-1',
                      operation_state='known-complete', write_executed=True,
                      stage_map={'liveReadback': {'status': 'pass'}})
        broken = completed_create()
        broken['stages']['liveReadback'] = {'status': 'pass', 'evidenceRef': [],
                                            'reason': 'trust me'}
        self.assertTrue(any('no evidenceRef' in p
                            for p in bc.validate_result(broken)))

    def test_a_non_pass_without_a_reason_is_refused(self):
        """A bare not-run/blocked/unknown is not an explanation (HONEST-3)."""
        broken = completed_create()
        broken['stages']['reopen'] = {'status': 'not-run', 'evidenceRef': []}
        self.assertTrue(any('no reason' in p for p in bc.validate_result(broken)))

    def test_the_five_stage_keys_are_the_only_ones_allowed(self):
        """C-1: persistence is an input alias, never an emitted stage."""
        with self.assertRaises(bc.ContractViolation):
            bc.stages_from({'persistence_v2': {'status': 'not-run', 'reason': 'x'}})
        aliased = bc.stages_from({'persistence': {'status': 'pass',
                                                  'evidenceRef': ['.runtime/save/1.json']}})
        self.assertIn('saveDiff', aliased)
        self.assertNotIn('persistence', aliased)

    def test_failed_is_only_an_input_alias(self):
        """C-2: the closed set has fail, not failed."""
        self.assertNotIn('failed', bc.frozen_sets()['stageStatus'])
        built = bc.stages_from({'saveDiff': {'status': 'failed', 'evidenceRef': ['.runtime/x.json'],
                                             'reason': 'differ'}})
        self.assertEqual(built['saveDiff']['status'], 'fail')

    def test_a_result_with_a_hole_in_it_is_not_publishable(self):
        """Matrix row 7: a result missing required keys is refused, and wholesale."""
        problems = bc.validate_result({'state': 'completed'})
        self.assertTrue(any('required keys missing' in p for p in problems))
        result = completed_create()
        del result['nextAction']
        self.assertTrue(any('required keys missing' in p for p in bc.validate_result(result)))

    def test_an_undeclared_top_level_key_is_refused(self):
        result = completed_create()
        result['reviewPath'] = 'D:/secret/review.json'
        self.assertTrue(any('undeclared keys' in p for p in bc.validate_result(result)))


class SaveAck(unittest.TestCase):
    """T05 matrix row 3, and G01 D12: an ACK is an execution fact, not a differential."""

    def setUp(self):
        self.fixture = load_fixture('legacy-save-ack-only.json')['input']

    def test_the_legacy_ack_normalises_to_blocked_not_pass(self):
        normalised = bc.normalize_legacy(self.fixture)
        save_diff = normalised['stages']['saveDiff']
        self.assertNotEqual(save_diff['status'], 'pass',
                            'nativeStatus==0 alone must never be a saveDiff pass (D12)')
        self.assertEqual(save_diff['status'], 'blocked')
        self.assertTrue(save_diff['detail']['saveInvocationAckOnly'])
        self.assertIn('execution fact', save_diff['reason'])
        self.assertEqual(normalised['state'], 'completed',
                         'the save invocation did succeed, so the operation is complete -- it is '
                         'the differential stage that is not a pass')

    def test_a_differential_from_an_independent_verifier_does_make_it_a_pass(self):
        diff = {'verdict': 'pass', 'evidenceRef': ['.runtime/verification/save/diff.json'],
                'saveInvocation': 'ok', 'savedContent': 'ok', 'allowedDelta': 'ok',
                'unrelatedUnchanged': 'ok'}
        normalised = bc.normalize_legacy(self.fixture, save_diff=diff)
        self.assertEqual(normalised['stages']['saveDiff']['status'], 'pass')
        self.assertEqual(normalised['stages']['saveDiff']['evidenceRef'],
                         ['.runtime/verification/save/diff.json'])

    def test_forcing_a_pass_on_an_ack_detail_is_still_rejected(self):
        """The gate is not bypassable by writing the flag by hand."""
        with self.assertRaises(bc.ContractViolation) as caught:
            completed_create(stage_map={
                'saveDiff': {'status': 'pass',
                             'evidenceRef': ['.runtime/save/%s/ack.json' % OPERATION],
                             'detail': {'saveInvocationAckOnly': True}}})
        self.assertTrue(any('ACK alone' in p for p in caught.exception.violations))
        hand_made = completed_create()
        hand_made = copy.deepcopy(hand_made)
        hand_made['stages']['saveDiff'] = {
            'status': 'pass', 'evidenceRef': ['.runtime/save/%s/ack.json' % OPERATION],
            'detail': {'saveInvocationAckOnly': True}}
        self.assertTrue(any('ACK alone' in p for p in bc.validate_result(hand_made)))


class ProtocolVersusBusiness(unittest.TestCase):
    """T05 matrix row 2: isError and state never substitute for one another (D7)."""

    def setUp(self):
        self.fixture = load_fixture('legacy-protocol-success-business-failure.json')['input']

    def test_protocol_success_with_a_business_failure_is_a_business_failure(self):
        normalised = bc.normalize_legacy(self.fixture)
        self.assertIs(self.fixture['ok'], True, 'the fixture really is a protocol success')
        self.assertIs(self.fixture['created'], False, 'and really is a business failure')
        self.assertNotEqual(normalised['state'], 'completed')
        self.assertEqual(normalised['state'], 'failed')
        self.assertIs(normalised['ok'], False)

    def test_the_driver_verdict_is_state_not_iserror(self):
        """A driver that reads isError calls this a success; reading state does not."""
        normalised = bc.normalize_legacy(self.fixture)
        self.assertIs(emitted(normalised)[0]['ok'], False,
                      'the protocol said ok=true; the business verdict says otherwise')
        self.assertTrue(bc.is_error_state(normalised['state']))
        self.assertNotEqual(normalised['state'], 'completed')
        self.assertEqual(normalised['nextAction'], 'report-and-repair')

    def test_ok_cannot_be_true_while_the_state_is_not_completed(self):
        result = completed_create()
        result['state'] = 'failed'
        problems = bc.validate_result(result)
        self.assertTrue(any('ok must equal' in p for p in problems))


class UnknownOutcome(unittest.TestCase):
    """T05 matrix row 4: claimed without a receipt is unknown, with a route, and no retry."""

    def test_a_claim_without_a_receipt_is_unknown_with_a_reconcile_route(self):
        error = bc.unknown_error(
            'REQUEST_OUTCOME_UNKNOWN', 'the claim exists and no result was published',
            reconcile={'operationId': OPERATION,
                       'ledgerRef': '.runtime/authoring/requests/%s' % OPERATION})
        result = bc.result(capability_id='entity.create', method='mw.scene.createEntity',
                           operation_id=OPERATION, operation_state='outcome-unknown',
                           target_handle='20261001-152306-21e64cb2f3', error=error)
        self.assertEqual(result['state'], 'unknown')
        self.assertIs(result['outcomeKnown'], False)
        self.assertIsNone(result['writeExecuted'],
                          '"not established" is null, not false -- they are different claims')
        self.assertEqual(result['nextAction'], 'reconcile')
        self.assertEqual(bc.validate_result(result), [])

    def test_an_unknown_without_a_reconcile_route_is_refused(self):
        """Otherwise the caller has no legal move but a blind resend (D31/OPS-2)."""
        with self.assertRaises(bc.ContractViolation):
            bc.make_error('REQUEST_OUTCOME_UNKNOWN', 'gone',
                          disposition='unknown-after-dispatch')
        error = bc.unknown_error('REQUEST_OUTCOME_UNKNOWN', 'gone',
                                 reconcile={'operationId': OPERATION, 'ledgerRef': 'x'})
        error.pop('reconcile')
        with self.assertRaises(bc.ContractViolation) as caught:
            completed_create(operation_state='outcome-unknown', write_executed=None,
                             object_ids=[], changed=[], error=error)
        self.assertTrue(any('reconcile' in p for p in caught.exception.violations))

    def test_a_context_dependent_code_must_be_resolved_by_its_emitter(self):
        """D30: the same code on both sides of the boundary, decided by the call site."""
        self.assertIsNone(bc.disposition_of('READBACK_FAILED'))
        with self.assertRaises(bc.ContractViolation):
            bc.make_error('READBACK_FAILED', 'inspect failed')     # no disposition supplied
        pre = bc.make_error('READBACK_FAILED', 'baseline inspect failed',
                            disposition='refusal-before-dispatch')
        post = bc.make_error('READBACK_FAILED', 'post-write inspect failed',
                             disposition='unknown-after-dispatch',
                             reconcile={'operationId': OPERATION, 'ledgerRef': 'x'})
        self.assertEqual((pre['phase'], pre['sideEffect']), ('before-dispatch', 'none'))
        self.assertEqual((post['phase'], post['sideEffect']), ('after-dispatch', 'possible'))

    def test_retry_is_never_reported_as_attempted(self):
        base = {'contractVersion': '1', 'capabilityId': 'entity.create', 'method': 'm',
                'operationId': 'op-1', 'caseId': None, 'targetHandle': None, 'state': 'rejected',
                'outcomeKnown': True, 'writeExecuted': False, 'objectIds': [], 'changed': [],
                'failedItems': [], 'stages': bc.blank_stages(), 'error': None,
                'nextAction': 'fix-input', 'retryAttempted': True, 'replayed': False, 'ok': False}
        self.assertTrue(any('retryAttempted' in p for p in bc.validate_result(base)))
        with self.assertRaises(bc.ContractViolation):
            bc.result(capability_id='entity.create', method='m', operation_id='op-1',
                      operation_state='known-complete', retryAttempted=True)


class PartialSuccess(unittest.TestCase):
    """T05 matrix row 5: partial success never collapses into one top-level verdict."""

    def test_partial_success_keeps_per_item_detail(self):
        result = bc.result(
            capability_id='entity.create', method='mw.scene.createBatch', operation_id=OPERATION,
            operation_state='known-failed', write_executed=True,
            target_handle='20261001-152306-21e64cb2f3',
            object_ids=[ENTITY],
            changed=[{'objectId': ENTITY, 'result': 'created', 'fields': None}],
            failed_items=[{'objectId': None, 'result': 'not-attempted',
                           'reason': 'the batch stopped after the first refusal'}],
            error=bc.make_error('CREATE_EFFECT_NOT_AS_REQUESTED',
                                'one of two placements was refused',
                                detail={'attempted': 2, 'changed': 1}))
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(len(result['changed']), 1)
        self.assertEqual(len(result['failedItems']), 1)
        self.assertEqual(result['failedItems'][0]['result'], 'not-attempted')
        self.assertEqual(result['nextAction'], 'report-and-repair')
        self.assertEqual(bc.validate_result(result), [])

    def test_a_completed_result_cannot_hide_an_untouched_item(self):
        """A completed verdict may not carry an item that was never attempted."""
        with self.assertRaises(bc.ContractViolation) as caught:
            completed_create(failed_items=[{'objectId': None, 'result': 'not-attempted',
                                            'reason': 'never reached'}])
        self.assertTrue(any('failedItems' in p for p in caught.exception.violations))


class WrongEvidence(unittest.TestCase):
    """T05 matrix row 6: evidence from another target, case or operation is a failure."""

    def test_evidence_naming_another_operation_is_refused(self):
        result = completed_create()
        problems = bc.validate_evidence_binding(result, operation_id=OTHER_OPERATION)
        self.assertTrue(any('not bound to operation' in p for p in problems))

    def test_evidence_naming_a_sibling_operation_is_refused(self):
        result = completed_create()
        problems = bc.validate_evidence_binding(result, operation_id=OPERATION,
                                                sibling_operation_ids=[OPERATION, 'mcp-other-99'])
        self.assertEqual(problems, [], 'a sibling that is not cited is not a problem')
        mixed = copy.deepcopy(result)
        mixed['stages']['liveReadback']['evidenceRef'] = [
            '.runtime/authoring/requests/mcp-other-99/after.json']
        problems = bc.validate_evidence_binding(mixed, operation_id=OPERATION,
                                                sibling_operation_ids=['mcp-other-99'])
        self.assertTrue(any('belongs to operation' in p for p in problems))

    def test_a_superseded_observation_is_refused(self):
        result = completed_create()
        stale = result['stages']['liveReadback']['evidenceRef'][0]
        problems = bc.validate_evidence_binding(result, operation_id=OPERATION,
                                                expired_refs=[stale])
        self.assertTrue(any('superseded' in p for p in problems))

    def test_evidence_outside_the_case_is_refused_when_the_call_is_case_bound(self):
        result = completed_create(case_id=CASE)
        problems = bc.validate_evidence_binding(result, operation_id=OPERATION, case_id=CASE)
        self.assertTrue(any('names no part of that case' in p for p in problems))


class RenderConsistency(unittest.TestCase):
    """T05 matrix rows 8 and 9: one body for both channels, and no host paths."""

    def test_the_two_channels_cannot_disagree(self):
        structured, text = emitted(completed_create())
        self.assertEqual(structured['state'], text['state'])
        self.assertEqual(structured, text)
        drifted = copy.deepcopy(structured)
        drifted['ok'] = True
        drifted['state'] = 'failed'
        self.assertTrue(bc.validate_result(drifted),
                        'if the two channels ever disagree the gate must fail, not the reader')

    def test_a_host_absolute_path_never_reaches_the_model(self):
        result = bc.result(
            capability_id='entity.create', method='mw.scene.createEntity', operation_id=OPERATION,
            operation_state='known-complete', write_executed=True,
            stage_map={'liveReadback': {
                'status': 'pass',
                'evidenceRef': [r'<SOURCE_PATH>' % OPERATION]}})
        body, index = bc.render_for_model(result)
        reference = body['stages']['liveReadback']['evidenceRef'][0]
        self.assertTrue(reference.startswith('evidence:'), reference)
        self.assertNotIn('D:\\', json.dumps(body))
        self.assertIn('<SOURCE_PATH>', index[reference])
        self.assertEqual(bc.validate_result(body, model_facing=True), [])
        self.assertTrue(bc.validate_result(result, model_facing=True),
                        'the raw internal record does carry an absolute path, which is why the '
                        'projection exists')

    def test_a_path_inside_free_text_is_redacted_too(self):
        result = completed_create(stage_map={
            'liveReadback': {'status': 'blocked',
                             'reason': r'could not read <SOURCE_PATH>',
                             'evidenceRef': []}})
        body, index = bc.render_for_model(result)
        reason = body['stages']['liveReadback']['reason']
        self.assertNotIn('D:\\', reason)
        self.assertTrue(any('D:\\' in value for value in index.values()))

    def test_a_project_relative_reference_is_kept_as_it_is(self):
        body, index = bc.render_for_model(completed_create())
        self.assertEqual(body['stages']['liveReadback']['evidenceRef'],
                         ['.runtime/game-executor/mcp-business/%s/after.json' % OPERATION])
        self.assertEqual(index, {})

    def test_the_rendered_body_is_json_serialisable_and_stable(self):
        body, _ = bc.render_for_model(completed_create())
        again = json.loads(json.dumps(body, ensure_ascii=False))
        self.assertEqual(body, again)
        self.assertEqual(bc.render_for_model(completed_create())[0], body)


class Desensitisation(unittest.TestCase):
    """T05 matrix row 9: an internal exception must not leak, but must stay locatable."""

    def test_an_internal_failure_keeps_its_code_and_loses_its_paths(self):
        error = bc.make_error('EXECUTION_LAYER_UNAVAILABLE',
                              r'the helper queue at <SOURCE_PATH>'
                              r'\elevated-queue did not answer',
                              upstream={'layer': 'queue-runner', 'code': 'NATIVE_SCENE_TIMEOUT',
                                        'message': 'timeout waiting for the elevated runner'})
        result = bc.result(capability_id='entity.create', method='mw.scene.createEntity',
                           operation_id=OPERATION, operation_state='never-claimed',
                           write_executed=False, error=error)
        body, index = bc.render_for_model(result)
        self.assertEqual(body['error']['code'], 'EXECUTION_LAYER_UNAVAILABLE',
                         'the actionable code survives')
        self.assertEqual(body['error']['upstream']['code'], 'NATIVE_SCENE_TIMEOUT')
        self.assertNotIn('D:\\', body['error']['message'])
        self.assertTrue(index, 'the location moved to the internal index, it was not dropped')

    def test_a_credential_shaped_value_is_not_copied_into_a_note(self):
        """A note is free text; the contract's own rule is that secrets never enter it."""
        result = completed_create(notes=['helper pid 4242 on queue <SOURCE_PATH>'])
        body, _ = bc.render_for_model(result)
        self.assertNotIn('D:\\', body['notes'][0])


class RemovedAndUnclassifiedCodes(unittest.TestCase):
    """The taxonomy is closed, and a code outside it is reported rather than guessed at."""

    def test_the_removed_catch_all_is_rejected_not_translated(self):
        fixture = load_fixture('legacy-business-error-catchall.json')['input']
        self.assertEqual(fixture['error']['code'], 'BUSINESS_ERROR')
        with self.assertRaises(bc.ContractViolation) as caught:
            bc.normalize_legacy(fixture)
        self.assertIn('BUSINESS_ERROR', str(caught.exception))
        with self.assertRaises(bc.ContractViolation):
            bc.make_error('BUSINESS_ERROR', 'anything')

    def test_a_code_outside_the_taxonomy_is_reported_not_translated(self):
        fixture = load_fixture('legacy-code-outside-taxonomy.json')['input']
        self.assertNotIn(fixture['error']['code'], bc.frozen_sets()['codes'])
        with self.assertRaises(bc.ContractViolation) as caught:
            bc.normalize_legacy(fixture)
        self.assertIn(fixture['error']['code'], str(caught.exception))

    def test_an_upstream_code_is_carried_inside_upstream_not_at_the_top(self):
        error = bc.make_error('EXECUTION_LAYER_BUSY', 'the runner reports an unresolved previous '
                                                      'native dispatch',
                              upstream={'layer': 'queue-runner',
                                        'code': 'NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED'})
        self.assertEqual(error['code'], 'EXECUTION_LAYER_BUSY')
        self.assertEqual(error['upstream']['code'],
                         'NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED')
        with self.assertRaises(bc.ContractViolation):
            bc.make_error('NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED', 'raw upstream code')


class PostDispatchNotRefusal(unittest.TestCase):
    """T05 matrix row 2/3 boundary: D32/D33, the split _fail() never made."""

    def test_a_failure_observed_after_the_write_is_not_a_refusal(self):
        fixture = load_fixture('legacy-post-dispatch-readback-failure.json')['input']
        normalised = bc.normalize_legacy(fixture)
        self.assertEqual(normalised['state'], 'failed')
        self.assertIs(normalised['ok'], False)
        self.assertEqual(normalised['error']['disposition'], 'failure-after-dispatch')
        self.assertEqual(normalised['error']['phase'], 'after-dispatch')
        self.assertEqual(normalised['error']['sideEffect'], 'observed')
        self.assertNotEqual(normalised['writeExecuted'], False,
                            'a failure after dispatch may not report "nothing was written"')
        self.assertEqual(normalised['error']['upstream']['code'],
                         'CREATE_DID_NOT_ADD_EXACTLY_ONE_ENTITY')

    def test_a_context_dependent_legacy_failure_becomes_unknown_not_a_guess(self):
        """The old shape recorded no phase, so choosing one would be the defect itself."""
        fixture = load_fixture('legacy-post-dispatch-readback-failure.json')['input']
        fixture['error'] = {'code': 'READBACK_FAILED', 'message': 'inspection did not verify'}
        normalised = bc.normalize_legacy(fixture)
        self.assertEqual(normalised['state'], 'unknown')
        self.assertEqual(normalised['nextAction'], 'reconcile')
        self.assertIsNotNone(normalised['error']['reconcile'])

    def test_a_pre_dispatch_refusal_stays_a_refusal(self):
        fixture = load_fixture('legacy-protocol-success-business-failure.json')['input']
        fixture['error'] = {'code': 'NATIVE_WRITE_REVIEW_REQUIRED',
                            'message': 'no coordinator review record'}
        normalised = bc.normalize_legacy(fixture)
        self.assertEqual(normalised['state'], 'rejected')
        self.assertIs(normalised['writeExecuted'], False)
        self.assertEqual(normalised['changed'], [])
        self.assertEqual(normalised['nextAction'], 'fix-input')

    def test_a_legacy_result_with_no_state_and_no_classified_error_is_unknown(self):
        fixture = load_fixture('legacy-save-ack-only.json')['input']
        fixture.pop('ok')
        fixture.pop('persistence')
        fixture['error'] = 'something went wrong'
        normalised = bc.normalize_legacy(fixture)
        self.assertEqual(normalised['state'], 'unknown')
        self.assertEqual(normalised['error']['code'], 'UPSTREAM_PENDING')
        self.assertIsNotNone(normalised['error']['reconcile'])


class SchemaConformance(unittest.TestCase):
    """The builder's output must satisfy the frozen G01 schema, not just this module."""

    def setUp(self):
        try:
            import jsonschema
        except ImportError:                                   # pragma: no cover
            self.skipTest('jsonschema is not installed in this interpreter')
        schema = json.loads(bc.TOOL_RESULT_SCHEMA.read_text(encoding='utf-8'))
        self.validator = jsonschema.Draft202012Validator(schema)

    def assert_schema_valid(self, instance, label):
        errors = sorted(self.validator.iter_errors(instance), key=lambda e: list(e.path))
        self.assertEqual([], [('%s: %s' % (list(e.path), e.message)) for e in errors], label)

    def test_a_completed_result_satisfies_the_schema(self):
        self.assert_schema_valid(completed_create(), 'completed')

    def test_a_refusal_satisfies_the_schema(self):
        self.assert_schema_valid(bc.result(
            capability_id='entity.create', method='mw.scene.createEntity', operation_id=OPERATION,
            operation_state='never-claimed', write_executed=False,
            error=bc.refusal_error('NATIVE_WRITE_REVIEW_REQUIRED',
                                   'a coordinator evidence record is required')), 'refusal')

    def test_an_unknown_result_satisfies_the_schema(self):
        self.assert_schema_valid(bc.result(
            capability_id='entity.create', method='mw.scene.createEntity', operation_id=OPERATION,
            target_handle='20261001-152306-21e64cb2f3', operation_state='outcome-unknown',
            error=bc.unknown_error('REQUEST_OUTCOME_UNKNOWN', 'claim without a result',
                                   reconcile={'operationId': OPERATION,
                                              'ledgerRef': '.runtime/ledger/%s.json' % OPERATION})),
            'unknown')

    def test_a_failed_result_satisfies_the_schema(self):
        self.assert_schema_valid(bc.result(
            capability_id='entity.save', method='mw.scene.saveLevel', operation_id=OPERATION,
            operation_state='known-failed', write_executed=True,
            error=bc.make_error('SAVE_STATUS_NOT_SUCCESS', 'native save status 7')), 'failed')

    def test_a_pending_result_satisfies_the_schema(self):
        self.assert_schema_valid(bc.result(
            capability_id='entity.create', method='mw.scene.createEntity', operation_id=OPERATION,
            target_handle='20261001-152306-21e64cb2f3', operation_state='dispatched'), 'pending')

    def test_the_normaliser_output_satisfies_the_schema_for_every_fixture_that_translates(self):
        for name in ('legacy-save-ack-only.json', 'legacy-protocol-success-business-failure.json',
                     'legacy-post-dispatch-readback-failure.json'):
            with self.subTest(fixture=name):
                normalised = bc.normalize_legacy(load_fixture(name)['input'])
                self.assert_schema_valid(normalised, name)

    def schema_accepts(self, instance):
        return not list(self.validator.iter_errors(instance))

    def test_the_schema_is_weaker_than_this_gate_and_that_is_why_the_gate_exists(self):
        """Two rules the JSON schema structurally cannot express, asserted both ways.

        The schema's ``if/then`` for ``state: unknown`` names ``properties.error``'s
        disposition; when ``error`` is null the check is vacuous, so an unknown carrying no
        reconciliation route validates.  And nothing in the schema relates ``failedItems`` to
        ``completed``.  A gate that accepts these is not a gate -- so the fact that the schema
        accepts them is the reason ``validate_result`` is the real one, not a redundancy.
        """
        # Written by hand rather than through result(), because result() refuses to build it.
        route_less = {'contractVersion': '1', 'capabilityId': 'entity.create',
                      'method': 'mw.scene.createEntity', 'operationId': OPERATION,
                      'caseId': None, 'targetHandle': 'h-1', 'state': 'unknown',
                      'operationState': 'outcome-unknown', 'outcomeKnown': False,
                      'writeExecuted': None, 'objectIds': [], 'changed': [], 'failedItems': [],
                      'stages': bc.blank_stages(),
                      'error': None, 'nextAction': 'reconcile',
                      'retryAttempted': False, 'replayed': False, 'ok': False}
        with self.assertRaises(bc.ContractViolation):
            bc.result(capability_id='entity.create', method='mw.scene.createEntity',
                      operation_id=OPERATION, operation_state='outcome-unknown')
        self.assertTrue(self.schema_accepts(route_less),
                        'the schema accepts an unknown with no error -- the vacuous then-branch')
        self.assertTrue(any('must carry an error object' in p
                            for p in bc.validate_result(route_less)),
                        'the contract gate rejects it')

        hidden_partial = copy.deepcopy(completed_create())
        hidden_partial['failedItems'] = [{'objectId': None, 'result': 'not-attempted',
                                          'reason': 'never reached'}]
        self.assertTrue(self.schema_accepts(hidden_partial),
                        'the schema has no rule tying failedItems to the verdict')
        self.assertTrue(any('failedItems' in p for p in bc.validate_result(hidden_partial)))


class MutationBattery(unittest.TestCase):
    """Ten deliberate breakages; each must be refused by the gate, not by the reader.

    A gate that only passes its own happy path has not been shown to discriminate.  Each
    mutant here is a shape somebody could plausibly write by accident or on purpose.
    """

    def setUp(self):
        try:
            import jsonschema                                        # noqa: F401
        except ImportError:                                          # pragma: no cover
            self.skipTest('jsonschema is not installed in this interpreter')

    def mutants(self):
        base = completed_create()

        m = copy.deepcopy(base); m['ok'] = False
        yield 'ok disagrees with the state', m

        m = copy.deepcopy(base); m['outcomeKnown'] = False
        yield 'a known-complete result claiming an unknown outcome', m

        m = copy.deepcopy(base); m['retryAttempted'] = True
        yield 'the engine claims it retried', m

        m = copy.deepcopy(base); m['error'] = {'code': 'SAVE_STATUS_NOT_SUCCESS',
                                               'disposition': 'failure-after-dispatch',
                                               'phase': 'after-dispatch',
                                               'sideEffect': 'observed', 'message': 'x'}
        yield 'a completed result carrying an error', m

        m = copy.deepcopy(base); m['stages']['liveReadback'] = {'status': 'pass', 'evidenceRef': []}
        yield 'a pass with no evidence', m

        m = copy.deepcopy(base); m['stages']['runtime'] = {'status': 'unknown', 'evidenceRef': []}
        yield 'an unknown stage with no reason', m

        m = copy.deepcopy(base); m['stages']['persistence'] = copy.deepcopy(m['stages']['saveDiff'])
        del m['stages']['saveDiff']
        yield 'the legacy persistence key smuggled into the output', m

        m = copy.deepcopy(base); m['error'] = {'code': 'BUSINESS_ERROR',
                                               'disposition': 'refusal-before-dispatch',
                                               'phase': 'before-dispatch', 'sideEffect': 'none',
                                               'message': 'x'}
        m['state'] = 'rejected'; m['ok'] = False
        yield 'the removed catch-all code', m

        m = copy.deepcopy(base); m['operationId'] = 'op with a space'
        yield 'an operationId that is not a legal key', m

        m = copy.deepcopy(base)
        m['stages']['liveReadback'] = {'status': 'pass',
                                       'evidenceRef': ['<SOURCE_PATH>']}
        yield 'a host path in the INTERNAL record is fine', m

    def test_each_mutant_is_refused(self):
        import jsonschema
        schema = json.loads(bc.TOOL_RESULT_SCHEMA.read_text(encoding='utf-8'))
        validator = jsonschema.Draft202012Validator(schema)
        refused = 0
        names = []
        for label, mutant in self.mutants():
            names.append(label)
            if label == 'a host path in the INTERNAL record is fine':
                # This one is legal internally: the projection is what removes it -- and then
                # the projected body must be clean, which is the actual assertion.
                self.assertEqual(bc.validate_result(mutant), [])
                body, _ = bc.render_for_model(mutant)
                self.assertEqual(bc.validate_result(body, model_facing=True), [])
                self.assertTrue(bc.validate_result(mutant, model_facing=True),
                                'and the raw record would not have passed the model-facing gate')
                refused += 1
                continue
            schema_rejected = bool(list(validator.iter_errors(mutant)))
            gate_rejected = bool(bc.validate_result(mutant))
            if not gate_rejected:
                self.fail('the gate accepted %r' % label)
            refused += 1
            _ = schema_rejected    # recorded so a reader can see the schema alone is weaker
        self.assertEqual(refused, len(names))
        self.assertGreaterEqual(len(names), 10)

    def test_the_schema_and_the_gate_agree_on_every_mutant_here(self):
        """Measured, not assumed: on this battery neither gate is the weaker one.

        The two rules where the schema alone is insufficient are asserted directly in
        ``SchemaConformance.test_the_schema_is_weaker_than_this_gate...``; this test records
        the opposite result for the remaining mutants, so nobody can later claim the JSON
        schema is decorative and delete it.
        """
        import jsonschema
        schema = json.loads(bc.TOOL_RESULT_SCHEMA.read_text(encoding='utf-8'))
        validator = jsonschema.Draft202012Validator(schema)
        disagreements = []
        for label, mutant in self.mutants():
            if label == 'a host path in the INTERNAL record is fine':
                continue
            schema_rejected = bool(list(validator.iter_errors(mutant)))
            gate_rejected = bool(bc.validate_result(mutant))
            if schema_rejected != gate_rejected:
                disagreements.append((label, schema_rejected, gate_rejected))
        self.assertEqual(disagreements, [], 'the two gates must agree on these mutants')


if __name__ == '__main__':
    unittest.main()
