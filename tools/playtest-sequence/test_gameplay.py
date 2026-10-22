"""Complete interaction module batch. All commands are explicit private fixtures."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import gameplay as g

EVIDENCE = g.ROOT / '.runtime/ptgame-tests' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
EVIDENCE.mkdir(parents=True, exist_ok=False)
PLAN = {'schemaVersion': 1, 'levelId': g.base.LEVEL,
        'start': {'worldPosition': [1, 100, 3], 'radius': 2},
        'actions': [{'id': 'cook', 'kind': 'option', 'label': '烹饪鱼', 'observations': 3}],
        'effects': [{'source': 'slots', 'configId': 100, 'resourceType': 3, 'delta': -1},
                    {'source': 'slots', 'configId': 101, 'resourceType': 3, 'delta': 1}],
        'finalOptions': ['烹饪鱼'], 'captureFrames': True}


class Fixture:
    private_fixture = True

    def __init__(self, case):
        self.c, self.calls, self.cards, self.replies = case, [], {}, {}
        self.input_count, self.action_count, self.after_count = 0, 0, 0
        self.duplicate, self.incomplete, self.unknown, self.wrong_kind = False, False, False, False
        self.missing, self.delay, self.delta_adjust, self.insufficient = 0, 0, 0, False
        self.far, self.mutate, self.bad_frame, self.bad_resource = False, False, False, False
        self.no_effect, self.no_callback, self.no_attack, self.wrong_binding = False, False, False, False
        self.wrong_frame_ancestor = False

    def call(self, args, log):
        self.calls.append(list(args))
        command = args[0]
        flags = dict(zip(args[1::2], args[2::2]))
        if self.mutate:
            self.c.session.write_text('mutated fixture', encoding='utf8')
            self.mutate = False
        if command == 'prepare':
            run = self.c.cards / str(len(self.cards))
            run.mkdir()
            op = flags['--operation']
            p = dict(kind='playtest-control-prepared-v' + str(99 if self.wrong_kind else g.KINDS[op]),
                     mode=op, targetLevelId=g.base.LEVEL, anchorRun=str(self.c.anchor),
                     compileOnly=False, launchable=True, action=19, receiptVersion=24,
                     explicitPrivateFixture=True)
            if op == 'trial-frame':
                p.pop('anchorRun')
                p['lineage'] = {'ancestors': [{'run': 'wrong' if self.wrong_frame_ancestor else str(self.c.anchor)}]}
            g.write(run / 'prepared.json', p)
            self.cards[str(run)] = (op, flags)
            return dict(ok=True, run=str(run), launchable=True, mode=op,
                        preparedSha256=g.digest(run / 'prepared.json'))
        if command == 'dispatch':
            run = Path(flags['--run'])
            op, plan = self.cards[str(run)]
            r = dict(ok=True, cleanupVerified=True, safeToRelease=True, outcomeUncertain=False,
                     mode='play', trialIdentityBound=not self.wrong_binding,
                     playerBelongsToTargetLevel=True, operation=op, run=str(run),
                     targetLevelId=g.base.LEVEL, nativeStarted=True)
            if op == 'input-state':
                self.input_count += 1
                rows = [dict(index=0, text='烹饪鱼', active=True, enabled=True)]
                if self.duplicate:
                    rows.append(dict(rows[0], index=1))
                if 1 < self.input_count <= 1 + self.missing:
                    rows = []
                r.update(optionsComplete=not self.incomplete, options=rows,
                         worldPosition=[100 if self.far else 1, 100, 3],
                         attackAvailable=not self.no_attack, inputSourceIdle=True)
            elif op == 'inventory-state':
                settled = False
                if self.action_count:
                    self.after_count += 1
                    settled = self.after_count > self.delay and not self.no_effect
                quantities = {100: 0 if self.insufficient else 4, 101: 0}
                if settled:
                    for effect in self.c.plan['effects']:
                        quantities[effect['configId']] = quantities.get(effect['configId'], 0) + effect['delta']
                    quantities[101] += self.delta_adjust
                r.update(inventoryComplete=True, inventoryQuantitiesVerified=True,
                         physicalItemCounts=[dict(configId=k, resourceType=3, quantity=str(v))
                                             for k, v in quantities.items()], paymentResourceCounts=[])
            elif op == 'trial-frame':
                (run / 'frame.png').write_bytes(b'explicit-private-frame-fixture')
                r.update(renderFrameCaptured=True, framePath=str(run / 'frame.png'),
                         png={'sha256': '0' * 64 if self.bad_frame else g.digest(run / 'frame.png')})
            else:
                self.action_count += 1
                r.update(nativeInputSubmitted=True, inputReleased=True,
                         interactionCallbackSubmitted=not self.no_callback,
                         trajectory=[{'world': [1, 100, 3]}, {'world': [1.2, 100, 3]}],
                         displacement=[0.2, 0, 0])
                if self.unknown:
                    r['outcomeUncertain'] = True
            (run / 'acceptance.bin').write_bytes(b'explicit-private-native-card')
            g.write(run / 'stdout.jsonl', dict(explicitPrivateFixture=True, operation=op))
            g.write(run / 'exit.json', dict(explicitPrivateFixture=True))
            r.update(binaryReceiptSha256=g.digest(run / 'acceptance.bin'),
                     rawReceiptSha256=g.digest(run / 'stdout.jsonl'))
            self.replies[str(run)] = r
            return r
        if command == 'decode':
            return copy.deepcopy(self.replies[flags['--run']])
        if command == 'inventory-diff':
            before, after = [self.replies[flags[k]] for k in ('--before-run', '--after-run')]
            changes = []
            for q in g.read(flags['--queries']):
                vals = []
                for state in (before, after):
                    field = 'physicalItemCounts' if q['source'] == 'slots' else 'paymentResourceCounts'
                    rows = [r for r in state[field] if r['configId'] == q['configId'] and r['resourceType'] == q['resourceType']]
                    vals.append(int(rows[0]['quantity']) if rows else 0)
                changes.append(dict(q, before=str(vals[0]), after=str(vals[1]), delta=str(vals[1] - vals[0])))
            if self.bad_resource:
                changes[0]['configId'] = 999
            return dict(ok=True, cleanupVerified=True, safeToRelease=True, outcomeUncertain=False,
                        operation='inventory-diff', targetLevelId=g.base.LEVEL, changes=changes)
        raise AssertionError(command)


class Cases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=EVIDENCE, prefix='case-')
        self.tmp._finalizer.detach()  # preserve failure and success raw fixtures
        self.dir = Path(self.tmp.name)
        self.cards = self.dir / 'cards'
        self.cards.mkdir()
        self.anchor = self.cards / 'anchor'
        self.anchor.mkdir()
        g.write(self.anchor / 'prepared.json', {'explicitPrivateFixture': True})
        self.session = self.dir / 'session.json'
        g.write(self.session, {'explicitPrivateFixture': True})
        self.queue = g.ROOT / '.runtime/editor-bridge' / ('ptgame-' + self.dir.name)
        self.queue.mkdir(exist_ok=False)
        self.freeze = self.dir / 'freeze.json'
        row = {'path': str(g.base.CLI), 'sha256': g.digest(g.base.CLI)}
        g.write(self.freeze, dict(status='offline-verified-live-unverified', route='native-map/playtest-control',
                                 owned=[row], sharedDependencies=[row], graphVectorValuesTree=[row]))
        for name, value in [('CARDS', self.cards), ('OUTPUT', self.dir / 'out')]:
            p = patch.object(g, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.plan = copy.deepcopy(PLAN)
        self.fixture = Fixture(self)
        self.waits = []

    def run_case(self, **overrides):
        kwargs = dict(operation_id='one', session_file=self.session, trial_anchor=self.anchor,
                      queue=self.queue, freeze_path=self.freeze, freeze_sha256=g.digest(self.freeze),
                      gate_open=True, _commands=self.fixture, _sleep=self.waits.append)
        kwargs.update(overrides)
        return g.run(self.plan, **kwargs)

    def test_complete_option_inventory_and_frames(self):
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertTrue(r['privateFixture'])
        self.assertEqual(r['comparisons'][-1]['delta'], [-1, 1])
        self.assertEqual(len(r['frames']), 2)
        self.assertEqual(self.fixture.action_count, 1)
        for key in ('wholeGameAccepted', 'visualAccepted', 'collisionVerified',
                    'targetNpcIdentityVerified', 'independentLevelTravelVerified'):
            self.assertFalse(r[key])

    def test_delayed_option_only_reobserves(self):
        self.fixture.missing = 2
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertEqual(self.fixture.action_count, 1)

    def test_delayed_settlement_no_action_replay(self):
        self.fixture.delay = 2
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertEqual(len(r['comparisons']), 3)
        self.assertEqual(self.fixture.action_count, 1)

    def test_unknown_action_stops_and_preserves_intent(self):
        self.fixture.unknown = True
        r = self.run_case()
        self.assertFalse(r['ok'])
        self.assertEqual(r['code'], 'CARD_UNKNOWN_OR_NOT_RELEASED')
        self.assertEqual(self.fixture.action_count, 1)
        self.assertEqual(self.fixture.after_count, 0)
        self.assertFalse(r['replayAllowed'])

    def test_different_start_blocks_all_input(self):
        self.fixture.far = True
        r = self.run_case()
        self.assertFalse(r['ok'])
        self.assertEqual(r['code'], 'PLAYER_OUTSIDE_REVIEWED_START')
        self.assertEqual(self.fixture.action_count, 0)

    def test_duplicate_chinese_label_blocks_input(self):
        self.fixture.duplicate = True
        self.assertEqual(self.run_case()['code'], 'OPTION_LABEL_AMBIGUOUS')
        self.assertEqual(self.fixture.action_count, 0)

    def test_missing_option_exhaustion_is_failure(self):
        self.fixture.missing = 9
        self.assertEqual(self.run_case()['code'], 'EXACT_OPTION_NOT_AVAILABLE')
        self.assertEqual(self.fixture.action_count, 0)

    def test_partial_option_list_is_failure(self):
        self.fixture.incomplete = True
        self.assertEqual(self.run_case()['code'], 'OPTION_LIST_INCOMPLETE')

    def test_material_shortage_blocks_input(self):
        self.fixture.insufficient = True
        self.assertEqual(self.run_case()['code'], 'STARTING_BALANCE_INSUFFICIENT')
        self.assertEqual(self.fixture.action_count, 0)

    def test_inventory_without_expected_effect_is_not_success(self):
        self.fixture.no_effect = True
        self.assertEqual(self.run_case()['code'], 'EXPECTED_DELTAS_NOT_OBSERVED')
        self.assertEqual(self.fixture.action_count, 1)

    def test_excess_product_is_failure(self):
        self.fixture.delta_adjust = 1
        self.assertEqual(self.run_case()['code'], 'UNEXPECTED_INVENTORY_DELTA')
        self.assertEqual(self.fixture.after_count, 1)

    def test_changed_resource_identity_is_failure(self):
        self.fixture.bad_resource = True
        self.assertEqual(self.run_case()['code'], 'DIFF_RESOURCE_MISMATCH')

    def test_unproven_callback_is_failure(self):
        self.fixture.no_callback = True
        self.assertEqual(self.run_case()['code'], 'INTERACTION_CALLBACK_UNPROVEN')

    def test_stale_session_stops_before_dispatch(self):
        self.fixture.mutate = True
        self.assertEqual(self.run_case()['code'], 'GAMEPLAY_SOURCE_OR_IDENTITY_CHANGED')
        self.assertFalse(any(c[0] == 'dispatch' for c in self.fixture.calls))

    def test_wrong_native_card_version_stops_before_dispatch(self):
        self.fixture.wrong_kind = True
        self.assertEqual(self.run_case()['code'], 'PREPARED_TARGET_OR_PROTOCOL_MISMATCH')
        self.assertFalse(any(c[0] == 'dispatch' for c in self.fixture.calls))

    def test_wrong_trial_is_rejected(self):
        self.fixture.wrong_binding = True
        self.assertEqual(self.run_case()['code'], 'DECODED_TRIAL_NOT_PROVEN')

    def test_frame_hash_mismatch_stops_before_input(self):
        self.fixture.bad_frame = True
        self.assertEqual(self.run_case()['code'], 'NATIVE_FRAME_HASH_MISMATCH')
        self.assertEqual(self.fixture.action_count, 0)

    def test_v3_frame_uses_real_lineage_schema(self):
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        frames = [g.read(Path(c['run']) / 'prepared.json') for c in r['cards'] if c['operation'] == 'trial-frame']
        self.assertEqual(len(frames), 2)
        self.assertTrue(all('anchorRun' not in c and c['lineage']['ancestors'][-1]['run'] == str(self.anchor) for c in frames))

    def test_wrong_frame_ancestor_refuses_before_frame_dispatch(self):
        self.fixture.wrong_frame_ancestor = True
        r = self.run_case()
        self.assertEqual(r['code'], 'PREPARED_TARGET_OR_PROTOCOL_MISMATCH')
        self.assertEqual(r['dispatchAttempts'], 1)

    def test_attack_move_wait_are_native_operations(self):
        self.plan['actions'] = [dict(id='hit', kind='attack'), dict(id='settle', kind='wait', seconds=2),
              dict(id='walk', kind='move', angle=20, strength=0.3, durationMs=100, maxDistance=1)]
        self.plan['finalOptions'] = []
        self.plan['captureFrames'] = False
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertEqual(self.waits, [2])
        ops = [c[c.index('--operation') + 1] for c in self.fixture.calls if c[0] == 'prepare']
        self.assertIn('attack-tap', ops)
        self.assertIn('move-pulse', ops)
        self.assertNotIn('trial-frame', ops)
        self.assertFalse(r['collisionVerified'])

    def test_missing_attack_mapping_stops(self):
        self.plan['actions'] = [dict(id='hit', kind='attack')]
        self.fixture.no_attack = True
        self.assertEqual(self.run_case()['code'], 'ATTACK_MAPPING_UNAVAILABLE')

    def test_reused_operation_never_replays(self):
        self.assertTrue(self.run_case()['ok'])
        before = len(self.fixture.calls)
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.assertEqual(len(self.fixture.calls), before)

    def test_closed_gate_does_not_touch_paths(self):
        with self.assertRaisesRegex(ValueError, 'UNIFIED_ACCEPTANCE_GATE_CLOSED'):
            self.run_case(gate_open=False, session_file=Path('invalid'))
        self.assertEqual(self.fixture.calls, [])

    def test_whole_validation_rejects_invalid_plans(self):
        mutations = [lambda p: p.update(levelId=1073741842),
                     lambda p: p.update(schemaVersion=True),
                     lambda p: p.update(effects=[]),
                     lambda p: p['effects'].append(copy.deepcopy(p['effects'][0])),
                     lambda p: p['effects'][0].update(delta=True),
                     lambda p: p['start'].update(radius=float('nan')),
                     lambda p: p['actions'][0].update(kind='cross-level'),
                     lambda p: p['actions'][0].update(label=''),
                     lambda p: p['actions'][0].update(observations=100),
                     lambda p: p['actions'].append(copy.deepcopy(p['actions'][0])),
                     lambda p: p['actions'][0].update(command='arbitrary'),
                     lambda p: p.update(captureFrames=1)]
        for change in mutations:
            with self.subTest(change=change):
                plan = copy.deepcopy(PLAN)
                change(plan)
                with self.assertRaises(ValueError):
                    g.validate_plan(plan)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   success=result.wasSuccessful(), privateFixturesOnly=True,
                   gameAccess=False, formalQueueAccess=False, desktopAccess=False,
                   evidence=str(EVIDENCE))
    g.write(EVIDENCE / 'summary.json', summary)
    print(json.dumps(summary))
    raise SystemExit(0 if result.wasSuccessful() else 1)
