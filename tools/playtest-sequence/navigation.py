"""Review-bound native walking survey with raw trajectories and optional game frames.

This checks actual route traversal. It never infers blocking from immobility,
and cannot certify a physics contact manifold or visual fidelity.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import subprocess
import time

import gameplay as g

b = g.base
ROOT = b.ROOT
OUTPUT = ROOT / '.runtime/playtest-navigation-sequences'
require = b.require


def vector(value):
    require(type(value) is list and len(value) == 3, 'NAVIGATION_WORLD_VECTOR')
    for x in value:
        g.number(x, -1e6, 1e6, 'NAVIGATION_WORLD_VECTOR')
    return value


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == {'schemaVersion', 'levelId', 'start', 'legs', 'captureFrames'},
            'NAVIGATION_PLAN_FIELDS')
    require(type(plan['schemaVersion']) is int and plan['schemaVersion'] == 1 and
            type(plan['levelId']) is int and plan['levelId'] == b.LEVEL, 'NAVIGATION_LEVEL')
    start = plan['start']
    require(type(start) is dict and set(start) == {'worldPosition', 'radius'}, 'NAVIGATION_START')
    previous = vector(start['worldPosition'])
    g.number(start['radius'], .05, 2, 'NAVIGATION_START_RADIUS')
    require(type(plan['captureFrames']) is bool, 'NAVIGATION_CAPTURE_FLAG')
    require(type(plan['legs']) is list and 1 <= len(plan['legs']) <= 16, 'NAVIGATION_LEG_COUNT')
    ids = set()
    for leg in plan['legs']:
        require(type(leg) is dict and set(leg) == {
            'id', 'angle', 'strength', 'durationMs', 'maxDistance', 'endpoint', 'radius', 'corridorRadius'},
            'NAVIGATION_LEG_FIELDS')
        ident = leg['id']
        require(type(ident) is str and b.IDENT.fullmatch(ident) and ident not in ids, 'NAVIGATION_LEG_ID')
        ids.add(ident)
        g.number(leg['angle'], -180, 180, 'NAVIGATION_ANGLE')
        g.number(leg['strength'], .1, 1, 'NAVIGATION_STRENGTH')
        require(type(leg['durationMs']) is int and 16 <= leg['durationMs'] <= 3000, 'NAVIGATION_DURATION')
        g.number(leg['maxDistance'], .1, 8, 'NAVIGATION_DISTANCE')
        g.number(leg['radius'], .05, 2, 'NAVIGATION_ENDPOINT_RADIUS')
        g.number(leg['corridorRadius'], leg['radius'], 3, 'NAVIGATION_CORRIDOR_RADIUS')
        end = vector(leg['endpoint'])
        length = math.dist(previous, end)
        # A stationary player must never satisfy a walking leg.
        require(length > 2 * max(leg['radius'], start['radius']) + .05 and
                length <= leg['maxDistance'], 'NAVIGATION_LEG_LENGTH')
        previous = end
    return b.json.loads(b.json.dumps(plan, allow_nan=False))


def segment_distance(point, start, end):
    direction = [end[i] - start[i] for i in range(3)]
    length2 = sum(x*x for x in direction)
    require(length2 > 0, 'NAVIGATION_ZERO_SEGMENT')
    t = min(1., max(0., sum((point[i]-start[i])*direction[i] for i in range(3)) / length2))
    return math.dist(point, [start[i]+t*direction[i] for i in range(3)])


def assess_trajectory(rows, start, leg, after_position):
    require(type(rows) is list and 2 <= len(rows) <= 192, 'NAVIGATION_TRAJECTORY_MISSING')
    ticks, frames, positions, driven = [], [], [], False
    for row in rows:
        require(type(row) is dict, 'NAVIGATION_TRAJECTORY_ROW')
        require(type(row.get('tick')) is int and row['tick'] >= 0 and
                type(row.get('frame')) is int and 0 <= row['frame'] <= 0xffffffff,
                'NAVIGATION_TRAJECTORY_CLOCK')
        require(row.get('flags') in (0, 1) and type(row.get('flags')) is int,
                'NAVIGATION_TRAJECTORY_FLAGS')
        g.number(row.get('strength'), 0, 1, 'NAVIGATION_TRAJECTORY_STRENGTH')
        g.number(row.get('angle'), -180, 180, 'NAVIGATION_TRAJECTORY_ANGLE')
        ticks.append(row['tick']); frames.append(row['frame'])
        point = vector(row.get('world'))
        positions.append(point)
        require(segment_distance(point, start, leg['endpoint']) <= leg['corridorRadius'],
                'PLAYER_LEFT_REVIEWED_CORRIDOR')
        driven |= bool(row['flags'] == 1 and row['strength'] >= .1)
    require(all(y >= x for x, y in zip(ticks, ticks[1:])) and ticks[-1] > ticks[0] and
            len(set(frames)) >= 2, 'NAVIGATION_NO_TEMPORAL_MOTION_EVIDENCE')
    require(driven, 'NAVIGATION_NO_DRIVEN_SAMPLES')
    require(math.dist(positions[0], start) <= leg['corridorRadius'], 'NAVIGATION_TRAJECTORY_START_CHANGED')
    require(math.dist(positions[-1], positions[0]) > .1, 'NAVIGATION_NO_PLAYER_DISPLACEMENT')
    end = vector(after_position)
    require(math.dist(end, positions[-1]) <= leg['radius'], 'NAVIGATION_AFTER_STATE_DISAGREES')
    require(math.dist(end, leg['endpoint']) <= leg['radius'], 'PLAYER_DID_NOT_REACH_CHECKPOINT')
    return dict(id=leg['id'], sampledPoints=len(rows), durationMs=ticks[-1]-ticks[0],
                displacement=[positions[-1][i]-positions[0][i] for i in range(3)],
                finalPosition=end, maxCorridorDeviation=max(segment_distance(p, start, leg['endpoint'])
                                                            for p in positions),
                checkpointReached=True, actualPlayerMotionObserved=True)


class Survey(g.Interaction):
    def card(self, operation, extra=()):
        run, decoded = super().card(operation, extra)
        if operation in ('input-state', 'move-pulse'):
            avatar = decoded.get('avatarId')
            require(type(avatar) is int and avatar > 0, 'NAVIGATION_AVATAR_ID_MISSING')
            expected = getattr(self, 'navigation_avatar', None)
            require(expected is None or avatar == expected, 'NAVIGATION_AVATAR_OR_INPUT_CHANGED')
            require(decoded.get('inputSourceIdle') is True, 'NAVIGATION_AVATAR_OR_INPUT_CHANGED')
            self.navigation_avatar = avatar
        return run, decoded

    def execute(self):
        _, state = self.card('input-state')
        avatar = state.get('avatarId')
        require(type(avatar) is int and avatar > 0, 'NAVIGATION_AVATAR_ID_MISSING')
        position = vector(state.get('worldPosition'))
        require(math.dist(position, self.plan['start']['worldPosition']) <= self.plan['start']['radius'],
                'PLAYER_OUTSIDE_REVIEWED_START')
        self.frame('before')
        checkpoints = []
        reviewed_start = self.plan['start']['worldPosition']
        for leg in self.plan['legs']:
            _, before = self.card('input-state')
            require(before.get('avatarId') == avatar and before.get('inputSourceIdle') is True,
                    'NAVIGATION_AVATAR_OR_INPUT_CHANGED')
            actual_start = vector(before.get('worldPosition'))
            require(math.dist(actual_start, position) <= self.plan['start']['radius'],
                    'NAVIGATION_UNCOMMANDED_DISPLACEMENT')
            action = {k: leg[k] for k in ('id', 'angle', 'strength', 'durationMs', 'maxDistance')}
            action['kind'] = 'move'
            self.perform(action)
            _, after = self.card('input-state')
            require(after.get('avatarId') == avatar and after.get('inputSourceIdle') is True,
                    'NAVIGATION_AVATAR_OR_INPUT_CHANGED')
            evidence = assess_trajectory(self.actions[-1]['trajectory'], reviewed_start, leg,
                                         after.get('worldPosition'))
            checkpoints.append(evidence)
            position = evidence['finalPosition']
            reviewed_start = leg['endpoint']
        return dict(ok=True, routeTraversed=True, checkpoints=checkpoints,
                    actualPlayerMotionObserved=all(x['actualPlayerMotionObserved'] for x in checkpoints))


def run(plan, *, operation_id, session_file, trial_anchor, queue, freeze_path, freeze_sha256,
        gate_open=False, _commands=None):
    require(gate_open is True, 'UNIFIED_ACCEPTANCE_GATE_CLOSED')
    plan = validate_plan(plan)
    require(type(operation_id) is str and b.IDENT.fullmatch(operation_id), 'UNIQUE_OPERATION_ID_REQUIRED')
    session = b.project_path(session_file)
    anchor = b.project_path(trial_anchor, directory=True, boundary=g.CARDS)
    queue = b.project_path(queue, directory=True, boundary=ROOT / '.runtime/editor-bridge')
    freeze = b.project_path(freeze_path)
    sources = b.freeze_sources(freeze, freeze_sha256)
    for source in (Path(__file__).resolve(), Path(g.__file__).resolve(), session,
                   anchor / 'prepared.json', ROOT / 'tools/editor-bridge/elevated-request.py'):
        sources[b.project_path(source)] = b.digest(source)
    commands = _commands or b.Commands()
    if _commands is not None:
        require(getattr(commands, 'private_fixture', False) is True, 'PRIVATE_TEST_SEAM_ONLY')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    directory = OUTPUT / hashlib.sha256(operation_id.encode()).hexdigest()[:32]
    directory.mkdir(exist_ok=False)
    b.write(directory / 'request.json', dict(plan=plan, operationId=operation_id, session=str(session),
        trialAnchor=str(anchor), queue=str(queue), sources={str(k):v for k,v in sources.items()},
        privateFixture=commands.private_fixture, replayAllowed=False))
    sources[directory / 'request.json'] = b.digest(directory / 'request.json')
    seq = Survey(plan, directory, session, anchor, queue, sources, commands, time.sleep)
    try:
        result = seq.execute()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = dict(ok=False, code=str(error), routeTraversed=False, actualPlayerMotionObserved=False)
    result.update(operationId=operation_id, directory=str(directory), lastStage=seq.stage,
        cards=seq.cards, actions=seq.actions, steps=seq.steps, frames=seq.frames,
        dispatchAttempts=seq.dispatch_attempts, replayAllowed=False, privateFixture=commands.private_fixture,
        wholeGameAccepted=False, visualAccepted=False, collisionVerified=False, blockingVerified=False,
        attribution='Native joystick input, actual timed player trajectories and fresh checkpoint observations. '
                    'Walking does not establish solver contacts; immobility is never interpreted as a wall collision.')
    b.write(directory / 'result.json', result)
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'session', 'trial-anchor', 'queue', 'freeze'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--freeze-sha256', required=True)
    parser.add_argument('--gate-open', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = run(b.read(args.plan), operation_id=args.operation_id, session_file=args.session,
            trial_anchor=args.trial_anchor, queue=args.queue, freeze_path=args.freeze,
            freeze_sha256=args.freeze_sha256, gate_open=args.gate_open)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = dict(ok=False, code=str(error), replayAllowed=False)
    print(b.json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
