"""Full private-fixture batch for target-bound sequences; never calls a game."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import targeted as t
import test_gameplay as old

g, b = t.g, t.b
EVIDENCE = t.ROOT / '.runtime/pttargeted-tests' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
EVIDENCE.mkdir(parents=True, exist_ok=False)
TARGET = dict(editorGuid=1002, runtimeId=10, label='烹饪鱼')
PLAN = dict(schemaVersion=1, levelId=b.LEVEL, start=dict(worldPosition=[1, 100, 3], radius=2),
            actions=[dict(id='cook', target=TARGET)], effects=old.PLAN['effects'],
            finalOptions=[TARGET], captureFrames=True)


class Fixture(old.Fixture):
    def __init__(self, case):
        super().__init__(case)
        self.bad_host, self.bad_member, self.bad_avatar, self.bad_target = False, False, False, False
        self.bad_baseline, self.bad_atomic, self.bad_return, self.bad_invoked = False, False, False, False
        self.unknown_directory, self.second_host, self.bad_source, self.final_missing = False, False, False, False

    def call(self, args, log):
        command, flags = args[0], dict(zip(args[1::2], args[2::2]))
        with patch.object(g, 'KINDS', t.TargetedSequence.card_versions):
            result = super().call(args, log)
        if command == 'prepare' and flags['--operation'] == 'targeted-interact':
            run = Path(result['run'])
            doc = b.read(run / 'prepared.json')
            doc['targetPlan'] = dict(targetId=flags['--target-id'], editorGuid=int(flags['--expected-editor-guid']),
                runtimeId=int(flags['--expected-runtime-id']), optionIndex=int(flags['--option-index']), label=flags['--label'])
            if self.bad_target:
                doc['targetPlan']['editorGuid'] += 1
            doc['targetBaseline'] = dict(run='wrong' if self.bad_baseline else flags['--target-baseline'])
            (run / 'prepared.json').write_text(b.json.dumps(doc), encoding='utf8')
            result['preparedSha256'] = b.digest(run / 'prepared.json')
        if command == 'dispatch':
            op, card_flags = self.cards[flags['--run']]
            if op == 'input-state':
                result.update(avatarId=100)
            if op in ('trial-entities', 'targeted-interact'):
                contact = dict(control=dict(observation=dict(after=dict(avatarId=101 if self.bad_avatar else 100))))
                host = dict(editorEntityGuid=999 if self.bad_host else 1002, runtimeId=10,
                            identityMappingVerified=True, targetLevelSpawnMembershipVerified=not self.bad_member,
                            belongsToBoundTrial=True if not self.bad_member else None,
                            sourceInstance=dict(editorGuid=999 if self.bad_source else 1002))
                row = dict(text='烹饪鱼', active=1, enabled=1, host=host, ownerRuntimeId=10,
                           hostRuntimeIdentityVerified=True, hostIdentityVerified=True,
                           hostTrialMembershipVerified=not self.bad_member)
                rows = [row]
                if self.duplicate:
                    rows.append(copy.deepcopy(row))
                if self.second_host:
                    other = copy.deepcopy(row)
                    other['host'].update(editorEntityGuid=1003, runtimeId=11, sourceInstance=dict(editorGuid=1003))
                    other['ownerRuntimeId'] = 11
                    rows.append(other)
                if self.final_missing and self.action_count > 1:
                    rows = []
                result.update(interactionOptions=rows, interactionOptionsKnown=True,
                              sourceDirectoryKnown=not self.unknown_directory,
                              targetLevelSpawnMembershipVerified=False)
                if op == 'trial-entities':
                    self.action_count -= 1
                    result['nativeReceipt'] = dict(contact=contact)
                    result['outcomeUncertain'] = False
                else:
                    result['nativeReceipt'] = dict(directory=dict(contact=contact))
                    result.update(atomicTargetIdentityVerified=not self.bad_atomic, actionAttempted=True,
                        actionReturned=not self.bad_return, invokedEditorEntityGuid=999 if self.bad_invoked else 1002,
                        invokedRuntimeId=10, invokedLabel='烹饪鱼')
            self.replies[flags['--run']] = result
        return result


class Cases(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=EVIDENCE, prefix='case-')
        temp._finalizer.detach()
        self.dir = Path(temp.name)
        self.cards = self.dir / 'cards'
        self.cards.mkdir()
        self.anchor = self.cards / 'anchor'
        self.anchor.mkdir()
        b.write(self.anchor / 'prepared.json', dict(explicitPrivateFixture=True))
        self.session = self.dir / 'session.json'
        b.write(self.session, dict(explicitPrivateFixture=True))
        self.queue = t.ROOT / '.runtime/editor-bridge' / ('pttargeted-' + self.dir.name)
        self.queue.mkdir(exist_ok=False)
        self.freeze = self.dir / 'freeze.json'
        row = dict(path=str(b.CLI), sha256=b.digest(b.CLI))
        b.write(self.freeze, dict(status='offline-verified-live-unverified', route='native-map/playtest-control',
                owned=[row], sharedDependencies=[row], graphVectorValuesTree=[row]))
        for module, key, value in [(g, 'CARDS', self.cards), (t, 'OUTPUT', self.dir / 'out')]:
            p = patch.object(module, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.plan = copy.deepcopy(PLAN)
        self.fixture = Fixture(self)

    def run_case(self, **changes):
        arguments = dict(operation_id='one', session_file=self.session, trial_anchor=self.anchor,
            queue=self.queue, freeze_path=self.freeze, freeze_sha256=b.digest(self.freeze),
            gate_open=True, _commands=self.fixture)
        arguments.update(changes)
        return t.run(self.plan, **arguments)

    def refused(self, flag, code, expected_actions=0):
        setattr(self.fixture, flag, True)
        result = self.run_case()
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], code)
        self.assertEqual(self.fixture.action_count, expected_actions)

    def test_native_target_and_exact_inventory_effects(self):
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertTrue(r['targetCallbacksVerified'])
        self.assertTrue(r['businessEffectVerified'])
        self.assertEqual(r['comparisons'][-1]['delta'], [-1, 1])
        self.assertEqual(len(r['frames']), 2)
        self.assertEqual(self.fixture.action_count, 1)
        for k in ('wholeGameAccepted', 'visualAccepted', 'collisionVerified', 'targetNpcIdentityVerified',
                  'timedFishingVerified', 'independentLevelTravelVerified', 'dialogueContentVerified'):
            self.assertFalse(r[k])

    def test_same_text_other_host_does_not_invalidate_exact_target(self):
        self.fixture.second_host = True
        self.assertTrue(self.run_case()['ok'])

    def test_callback_only_does_not_claim_dialogue_or_business(self):
        self.plan['effects'] = []
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertFalse(r['businessEffectVerified'])
        self.assertFalse(r['expectedQuantityDeltasObserved'])
        self.assertFalse(any('--operation' in a and a[a.index('--operation') + 1] == 'inventory-state'
                             for a in self.fixture.calls))

    def test_wrong_host_refused(self):
        self.refused('bad_host', 'TARGETED_OPTION_MISSING_OR_AMBIGUOUS')

    def test_unknown_membership_refused(self):
        self.refused('bad_member', 'TARGETED_HOST_NOT_PROVEN')

    def test_wrong_source_record_refused(self):
        self.refused('bad_source', 'TARGETED_HOST_NOT_PROVEN')

    def test_duplicate_same_host_option_refused(self):
        self.refused('duplicate', 'TARGETED_OPTION_MISSING_OR_AMBIGUOUS')

    def test_unknown_directory_refused(self):
        self.refused('unknown_directory', 'TARGETED_DIRECTORY_UNKNOWN')

    def test_avatar_switch_refused(self):
        self.refused('bad_avatar', 'TARGETED_AVATAR_OR_INPUT_CHANGED')

    def test_changed_prepared_target_refused_before_dispatch(self):
        self.refused('bad_target', 'TARGETED_PREPARED_TARGET_CHANGED')

    def test_wrong_prepared_baseline_refused_before_dispatch(self):
        self.refused('bad_baseline', 'TARGETED_PREPARED_TARGET_CHANGED')

    def test_atomic_proof_required(self):
        self.refused('bad_atomic', 'TARGETED_ATOMIC_CALLBACK_NOT_PROVEN', 1)

    def test_action_return_required(self):
        self.refused('bad_return', 'TARGETED_ATOMIC_CALLBACK_NOT_PROVEN', 1)

    def test_invoked_host_must_match(self):
        self.refused('bad_invoked', 'TARGETED_ATOMIC_CALLBACK_NOT_PROVEN', 1)

    def test_unknown_callback_no_replay(self):
        self.refused('unknown', 'CARD_UNKNOWN_OR_NOT_RELEASED', 1)

    def test_insufficient_resources_before_action(self):
        self.refused('insufficient', 'STARTING_BALANCE_INSUFFICIENT')

    def test_no_inventory_effect_is_failure(self):
        self.refused('no_effect', 'EXPECTED_DELTAS_NOT_OBSERVED', 1)

    def test_wrong_resource_is_failure(self):
        self.refused('bad_resource', 'TARGETED_DIFF_RESOURCE', 1)

    def test_delayed_settlement_never_replays_input(self):
        self.fixture.delay = 2
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertEqual(len(r['comparisons']), 3)
        self.assertEqual(self.fixture.action_count, 1)

    def test_fresh_final_option_required(self):
        self.refused('final_missing', 'TARGETED_OPTION_MISSING_OR_AMBIGUOUS', 1)

    def test_native_frame_hash_mismatch(self):
        self.refused('bad_frame', 'NATIVE_FRAME_HASH_MISMATCH')

    def test_native_card_version_mismatch(self):
        self.refused('wrong_kind', 'PREPARED_TARGET_OR_PROTOCOL_MISMATCH')

    def test_session_changes_refused_before_dispatch(self):
        self.refused('mutate', 'GAMEPLAY_SOURCE_OR_IDENTITY_CHANGED')

    def test_gate_closed_before_command(self):
        with self.assertRaisesRegex(ValueError, 'GATE_CLOSED'):
            self.run_case(gate_open=False)
        self.assertEqual(self.fixture.calls, [])

    def test_replay_id_is_refused(self):
        self.assertTrue(self.run_case()['ok'])
        with self.assertRaises(FileExistsError):
            self.run_case()

    def test_invalid_plan_batch(self):
        mutations = [lambda p: p['actions'][0]['target'].update(editorGuid=True),
                     lambda p: p['actions'][0]['target'].update(runtimeId=0),
                     lambda p: p['actions'][0]['target'].update(label=''),
                     lambda p: p['actions'].append(copy.deepcopy(p['actions'][0])),
                     lambda p: p['effects'].append(copy.deepcopy(p['effects'][0])),
                     lambda p: p['finalOptions'].append(copy.deepcopy(p['finalOptions'][0])),
                     lambda p: p['start']['worldPosition'].__setitem__(0, float('nan')),
                     lambda p: p.update(levelId=1073741842),
                     lambda p: p.update(captureFrames=1)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                plan = copy.deepcopy(PLAN)
                mutate(plan)
                with self.assertRaises(ValueError):
                    t.validate_plan(plan)


if __name__ == '__main__':
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(x) for x in (Cases,))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    b.write(EVIDENCE / 'summary.json', dict(tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), passed=result.wasSuccessful(), gameAccess=False,
        desktopAccess=False, formalQueueAccess=False, evidence=str(EVIDENCE)))
    raise SystemExit(0 if result.wasSuccessful() else 1)
