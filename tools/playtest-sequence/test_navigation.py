"""Full navigation module batch; every dispatch is an explicit private fixture."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import navigation as n

b, g = n.b, n.g
EVIDENCE = n.ROOT / '.runtime/ptnav-tests' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
EVIDENCE.mkdir(parents=True, exist_ok=False)
PLAN = dict(schemaVersion=1, levelId=b.LEVEL, captureFrames=True,
            start=dict(worldPosition=[1, 100, 3], radius=.25),
            legs=[dict(id='bridge-entry', angle=90, strength=.7, durationMs=900,
                       maxDistance=3, endpoint=[3, 100, 3], radius=.25, corridorRadius=.5),
                  dict(id='bridge-exit', angle=90, strength=.7, durationMs=900,
                       maxDistance=3, endpoint=[5, 100, 3], radius=.25, corridorRadius=.5)])


class Fixture:
    private_fixture = True

    def __init__(self, case):
        self.c = case
        self.calls, self.cards, self.replies = [], {}, {}
        self.position = [1, 100, 3]
        self.actions, self.inputs = 0, 0
        self.mode = None

    def call(self, args, log):
        self.calls.append(list(args))
        command, flags = args[0], dict(zip(args[1::2], args[2::2]))
        if self.mode == 'mutated-source':
            self.c.session.write_text('changed fixture', encoding='utf8')
            self.mode = None
        if command == 'prepare':
            run = self.c.cards / str(len(self.cards))
            run.mkdir()
            op = flags['--operation']
            p = dict(kind='playtest-control-prepared-v' + str(g.KINDS[op]), mode=op,
                     targetLevelId=b.LEVEL, anchorRun=str(self.c.anchor), compileOnly=False,
                     launchable=True, action=19, receiptVersion=24, explicitPrivateFixture=True)
            if op == 'trial-frame':
                p.pop('anchorRun')
                p['lineage'] = {'ancestors': [{'run': str(self.c.anchor)}]}
            b.write(run / 'prepared.json', p)
            self.cards[str(run)] = (op, flags)
            return dict(ok=True, run=str(run), launchable=True, mode=op,
                        preparedSha256=b.digest(run / 'prepared.json'))
        if command == 'dispatch':
            run = Path(flags['--run'])
            op, flags = self.cards[str(run)]
            r = dict(ok=True, cleanupVerified=True, safeToRelease=True, outcomeUncertain=False,
                     mode='play', trialIdentityBound=True, playerBelongsToTargetLevel=True,
                     operation=op, run=str(run), targetLevelId=b.LEVEL, nativeStarted=True)
            if op == 'input-state':
                self.inputs += 1
                position = list(self.position)
                if self.mode == 'wrong-start' and not self.actions:
                    position[0] += 30
                if self.mode == 'contradict-after' and self.actions:
                    position[0] -= 1
                r.update(avatarId=99 if self.mode == 'changed-baseline-avatar' and self.inputs == 3 else 7,
                         inputSourceIdle=not (self.mode == 'busy-input' and self.inputs == 3),
                         worldPosition=position)
            elif op == 'trial-frame':
                (run / 'frame.png').write_bytes(b'explicit-private-frame')
                r.update(renderFrameCaptured=True, framePath=str(run / 'frame.png'),
                         png={'sha256': b.digest(run / 'frame.png')})
            elif op == 'move-pulse':
                start = list(self.position)
                end = list(self.c.plan['legs'][self.actions]['endpoint'])
                if self.mode == 'immobile':
                    end = list(start)
                if self.mode == 'short-move':
                    end[0] -= 1
                midpoint = [(a+c)/2 for a,c in zip(start, end)]
                rows = [dict(tick=100+i*100, frame=20+i, flags=int(i > 0), world=point,
                             angle=float(flags['--angle']), strength=0. if i == 0 else float(flags['--strength']))
                        for i, point in enumerate((start, midpoint, end))]
                if self.mode == 'missing-trajectory': rows = []
                if self.mode == 'no-time':
                    for row in rows: row['tick'] = 100
                if self.mode == 'backward-time': rows[1]['tick'] = 0
                if self.mode == 'one-frame':
                    for row in rows: row['frame'] = 20
                if self.mode == 'no-driven-input':
                    for row in rows: row['flags'] = 0
                if self.mode == 'side-excursion': rows[1]['world'][2] += 2
                if self.mode == 'vertical-fall': rows[1]['world'][1] -= 3
                if self.mode == 'nan-point': rows[1]['world'][0] = float('nan')
                if self.mode == 'bad-clock': rows[1]['tick'] = True
                if self.mode == 'bad-flags': rows[1]['flags'] = True
                self.actions += 1
                self.position = end
                r.update(avatarId=99 if self.mode == 'changed-action-avatar' else 7,
                         inputSourceIdle=True, nativeInputSubmitted=True,
                         inputReleased=self.mode != 'not-released', trajectory=rows,
                         displacement=[c-a for a,c in zip(start, end)])
                if self.mode == 'unknown': r['outcomeUncertain'] = True
            else:
                raise AssertionError(op)
            (run / 'acceptance.bin').write_bytes(b'explicit-private-native-receipt')
            b.write(run / 'stdout.jsonl', dict(explicitPrivateFixture=True, operation=op))
            b.write(run / 'exit.json', dict(explicitPrivateFixture=True))
            r.update(binaryReceiptSha256=b.digest(run / 'acceptance.bin'),
                     rawReceiptSha256=b.digest(run / 'stdout.jsonl'))
            self.replies[str(run)] = r
            return r
        if command == 'decode':
            r = copy.deepcopy(self.replies[flags['--run']])
            if self.mode == 'wrong-trial': r['trialIdentityBound'] = False
            return r
        raise AssertionError(command)


class Cases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=EVIDENCE, prefix='case-')
        self.tmp._finalizer.detach()
        self.dir = Path(self.tmp.name)
        self.cards = self.dir / 'cards'
        self.cards.mkdir()
        self.anchor = self.cards / 'anchor'
        self.anchor.mkdir()
        b.write(self.anchor / 'prepared.json', {'explicitPrivateFixture': True})
        self.session = self.dir / 'session.json'
        b.write(self.session, {'explicitPrivateFixture': True})
        self.queue = n.ROOT / '.runtime/editor-bridge' / ('ptnav-' + self.dir.name)
        self.queue.mkdir(exist_ok=False)
        self.freeze = self.dir / 'freeze.json'
        row = dict(path=str(b.CLI), sha256=b.digest(b.CLI))
        b.write(self.freeze, dict(status='offline-verified-live-unverified', route='native-map/playtest-control',
                                 owned=[row], sharedDependencies=[row], graphVectorValuesTree=[row]))
        for module, name, value in [(g, 'CARDS', self.cards), (n, 'OUTPUT', self.dir / 'out')]:
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.plan = copy.deepcopy(PLAN)
        self.fixture = Fixture(self)

    def run_case(self, **overrides):
        kwargs = dict(operation_id='reviewed-route', session_file=self.session, trial_anchor=self.anchor,
                      queue=self.queue, freeze_path=self.freeze, freeze_sha256=b.digest(self.freeze),
                      gate_open=True, _commands=self.fixture)
        kwargs.update(overrides)
        return n.run(self.plan, **kwargs)

    def test_complete_two_leg_route_and_frames(self):
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertTrue(r['routeTraversed'])
        self.assertTrue(r['actualPlayerMotionObserved'])
        self.assertEqual(len(r['checkpoints']), 2)
        self.assertEqual(len(r['frames']), 3)
        self.assertEqual(self.fixture.actions, 2)
        self.assertTrue(all(x['durationMs'] == 200 for x in r['checkpoints']))
        for key in ('wholeGameAccepted', 'visualAccepted', 'collisionVerified', 'blockingVerified'):
            self.assertFalse(r[key])

    def test_frame_capture_is_optional(self):
        self.plan['captureFrames'] = False
        r = self.run_case()
        self.assertTrue(r['ok'], r)
        self.assertEqual(r['frames'], [])

    def test_closed_gate_has_zero_commands(self):
        with self.assertRaisesRegex(ValueError, 'UNIFIED_ACCEPTANCE_GATE_CLOSED'):
            self.run_case(gate_open=False, session_file=Path('does-not-exist'))
        self.assertEqual(self.fixture.calls, [])

    def test_repeated_operation_is_never_replayed(self):
        self.assertTrue(self.run_case()['ok'])
        count = len(self.fixture.calls)
        with self.assertRaises(FileExistsError): self.run_case()
        self.assertEqual(len(self.fixture.calls), count)

    def test_unreviewed_freeze_stops_before_commands(self):
        with self.assertRaisesRegex(ValueError, 'FREEZE_CHANGED'):
            self.run_case(freeze_sha256='0'*64)
        self.assertEqual(self.fixture.calls, [])

    def test_unknown_stops_without_second_action(self):
        self.fixture.mode = 'unknown'
        r = self.run_case()
        self.assertFalse(r['ok'])
        self.assertEqual(r['code'], 'CARD_UNKNOWN_OR_NOT_RELEASED')
        self.assertEqual(self.fixture.actions, 1)
        self.assertFalse(r['replayAllowed'])

    def test_mutated_source_stops(self):
        self.fixture.mode = 'mutated-source'
        self.assertEqual(self.run_case()['code'], 'GAMEPLAY_SOURCE_OR_IDENTITY_CHANGED')
        self.assertEqual(self.fixture.actions, 0)

    def test_whole_plan_validation(self):
        changes = [lambda p:p.update(levelId=1073741842), lambda p:p.update(schemaVersion=True),
                   lambda p:p.update(legs=[]), lambda p:p.update(captureFrames=1),
                   lambda p:p['start'].update(radius=float('nan')),
                   lambda p:p['start'].update(worldPosition=[1, 2, True]),
                   lambda p:p['legs'][0].update(durationMs=True),
                   lambda p:p['legs'][0].update(durationMs=3001),
                   lambda p:p['legs'][0].update(angle=float('inf')),
                   lambda p:p['legs'][0].update(maxDistance=9),
                   lambda p:p['legs'][0].update(endpoint=[1,100,3]),
                   lambda p:p['legs'][0].update(corridorRadius=.1),
                   lambda p:p['legs'][0].update(strength=0),
                   lambda p:p['legs'].append(copy.deepcopy(p['legs'][0])),
                   lambda p:p['legs'][0].update(teleport=True)]
        for change in changes:
            with self.subTest(change=change):
                plan = copy.deepcopy(PLAN)
                change(plan)
                with self.assertRaises(ValueError): n.validate_plan(plan)


def rejection_test(mode, code, maximum_actions):
    def check(self):
        self.fixture.mode = mode
        r = self.run_case()
        self.assertFalse(r['ok'], r)
        self.assertEqual(r['code'], code, r)
        self.assertLessEqual(self.fixture.actions, maximum_actions)
        self.assertFalse(r['routeTraversed'])
        self.assertFalse(r['blockingVerified'])
    return check


for mode, code, count in [
    ('wrong-start', 'PLAYER_OUTSIDE_REVIEWED_START', 0),
    ('immobile', 'NAVIGATION_NO_PLAYER_DISPLACEMENT', 1),
    ('short-move', 'PLAYER_DID_NOT_REACH_CHECKPOINT', 1),
    ('missing-trajectory', 'NAVIGATION_TRAJECTORY_MISSING', 1),
    ('no-time', 'NAVIGATION_NO_TEMPORAL_MOTION_EVIDENCE', 1),
    ('backward-time', 'NAVIGATION_NO_TEMPORAL_MOTION_EVIDENCE', 1),
    ('one-frame', 'NAVIGATION_NO_TEMPORAL_MOTION_EVIDENCE', 1),
    ('no-driven-input', 'NAVIGATION_NO_DRIVEN_SAMPLES', 1),
    ('side-excursion', 'PLAYER_LEFT_REVIEWED_CORRIDOR', 1),
    ('vertical-fall', 'PLAYER_LEFT_REVIEWED_CORRIDOR', 1),
    ('bad-clock', 'NAVIGATION_TRAJECTORY_CLOCK', 1),
    ('bad-flags', 'NAVIGATION_TRAJECTORY_FLAGS', 1),
    ('contradict-after', 'NAVIGATION_AFTER_STATE_DISAGREES', 1),
    ('changed-baseline-avatar', 'NAVIGATION_AVATAR_OR_INPUT_CHANGED', 0),
    ('changed-action-avatar', 'NAVIGATION_AVATAR_OR_INPUT_CHANGED', 1),
    ('busy-input', 'NAVIGATION_AVATAR_OR_INPUT_CHANGED', 0),
    ('not-released', 'INPUT_NOT_SUBMITTED_AND_RELEASED', 1),
    ('wrong-trial', 'DECODED_TRIAL_NOT_PROVEN', 0),
]:
    setattr(Cases, 'test_reject_' + mode.replace('-', '_'), rejection_test(mode, code, count))


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                   success=result.wasSuccessful(), privateFixturesOnly=True, gameAccess=False,
                   formalQueueAccess=False, desktopAccess=False, evidence=str(EVIDENCE))
    b.write(EVIDENCE / 'summary.json', summary)
    print(json.dumps(summary))
    raise SystemExit(0 if result.wasSuccessful() else 1)
