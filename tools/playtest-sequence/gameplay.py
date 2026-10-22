"""Bounded native interaction sequences with independent inventory evidence.

Development is offline. The CLI refuses execution unless --gate-open is given.
Actions use the existing native input card, never OS input or state setters.
This module does not certify map appearance, contact, NPC identity or travel.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import subprocess
import time

import sequence as base

ROOT = base.ROOT
CARDS = base.CARDS
OUTPUT = ROOT / '.runtime/playtest-gameplay-sequences'
KINDS = {'input-state': 4, 'interact-option': 4, 'attack-tap': 4,
         'move-pulse': 4, 'inventory-state': 6, 'trial-frame': 3}
require, read, write, digest = base.require, base.read, base.write, base.digest


def number(value, lo, hi, code):
    require(type(value) in (int, float) and math.isfinite(value) and lo <= value <= hi, code)


def label(value):
    require(type(value) is str and value and '\0' not in value and
            len(value.encode('utf-16-le')) <= 254, 'OPTION_LABEL_INVALID')


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == {
        'schemaVersion', 'levelId', 'start', 'actions', 'effects', 'finalOptions', 'captureFrames'},
        'GAMEPLAY_PLAN_FIELDS')
    require(type(plan['schemaVersion']) is int and plan['schemaVersion'] == 1 and
            type(plan['levelId']) is int and plan['levelId'] == base.LEVEL, 'GAMEPLAY_LEVEL')
    start = plan['start']
    require(type(start) is dict and set(start) == {'worldPosition', 'radius'}, 'START_FIELDS')
    require(type(start['worldPosition']) is list and len(start['worldPosition']) == 3, 'START_POSITION')
    for value in start['worldPosition']:
        number(value, -1e6, 1e6, 'START_POSITION')
    number(start['radius'], 0.1, 20, 'START_RADIUS')
    require(type(plan['captureFrames']) is bool, 'CAPTURE_FRAMES_BOOLEAN')
    require(type(plan['actions']) is list and 1 <= len(plan['actions']) <= 12, 'ACTION_COUNT')
    ids, wait_total = set(), 0
    for row in plan['actions']:
        require(type(row) is dict and type(row.get('id')) is str and base.IDENT.fullmatch(row['id']) and
                row['id'] not in ids, 'ACTION_ID_INVALID_OR_DUPLICATE')
        ids.add(row['id'])
        kind = row.get('kind')
        fields = {'id', 'kind'}
        if kind == 'option':
            fields |= {'label', 'observations'}
            label(row.get('label'))
            require(type(row.get('observations')) is int and 1 <= row['observations'] <= 4,
                    'OPTION_OBSERVATION_LIMIT')
        elif kind == 'attack':
            pass
        elif kind == 'move':
            fields |= {'angle', 'strength', 'durationMs', 'maxDistance'}
            number(row.get('angle'), -180, 180, 'MOVE_ANGLE')
            number(row.get('strength'), 0.1, 1, 'MOVE_STRENGTH')
            require(type(row.get('durationMs')) is int and 16 <= row['durationMs'] <= 3000, 'MOVE_DURATION')
            number(row.get('maxDistance'), 0.1, 8, 'MOVE_DISTANCE')
        elif kind == 'wait':
            fields |= {'seconds'}
            number(row.get('seconds'), 0.1, 30, 'WAIT_SECONDS')
            wait_total += row['seconds']
        else:
            raise ValueError('ACTION_KIND_UNSUPPORTED')
        require(set(row) == fields, 'ACTION_FIELDS')
    require(wait_total <= 60, 'TOTAL_WAIT_LIMIT')
    effects = plan['effects']
    require(type(effects) is list and 1 <= len(effects) <= 16, 'EFFECT_COUNT')
    resources = set()
    for row in effects:
        require(type(row) is dict and set(row) == {'source', 'configId', 'resourceType', 'delta'},
                'EFFECT_FIELDS')
        require(row['source'] in ('slots', 'payment-resources'), 'EFFECT_SOURCE')
        require(type(row['configId']) is int and 0 < row['configId'] <= 0xffffffff, 'EFFECT_ID')
        require(type(row['resourceType']) is int and 0 <= row['resourceType'] <= 0xffffffff, 'EFFECT_TYPE')
        require(type(row['delta']) is int and 0 < abs(row['delta']) <= 10**9, 'EFFECT_DELTA')
        key = (row['source'], row['configId'], row['resourceType'])
        require(key not in resources, 'DUPLICATE_EFFECT')
        resources.add(key)
    require(type(plan['finalOptions']) is list and len(plan['finalOptions']) <= 16, 'FINAL_OPTIONS')
    for text in plan['finalOptions']:
        label(text)
    require(len(set(plan['finalOptions'])) == len(plan['finalOptions']), 'DUPLICATE_FINAL_OPTION')
    return base.json.loads(base.json.dumps(plan, allow_nan=False))


class Interaction:
    card_versions = KINDS
    def __init__(self, plan, directory, session, anchor, queue, sources, commands, sleeper):
        self.plan, self.directory = plan, directory
        self.session, self.anchor, self.queue = session, anchor, queue
        self.sources, self.commands, self.sleeper = sources, commands, sleeper
        self.started = time.monotonic()
        self.stage, self.sequence, self.dispatch_attempts = 'created', 0, 0
        self.cards, self.actions, self.steps, self.frames = [], [], [], []
        self.card_paths = set()

    def check(self):
        require(time.monotonic() - self.started < 2700, 'GAMEPLAY_TIME_LIMIT')
        for path, sha in self.sources.items():
            require(digest(path) == sha, 'GAMEPLAY_SOURCE_OR_IDENTITY_CHANGED')

    def call(self, arguments):
        self.check()
        require(self.sequence < 300, 'GAMEPLAY_COMMAND_LIMIT')
        log = self.directory / f'{self.sequence:03d}'
        log.mkdir(exist_ok=False)
        self.sequence += 1
        write(log / 'intent.json', {'arguments': list(map(str, arguments)), 'stage': self.stage,
                                    'at': datetime.now(timezone.utc).isoformat()})
        result = self.commands.call(arguments, log)
        require(type(result) is dict and result.get('ok') is True, 'COMMAND_DID_NOT_SUCCEED')
        write(log / 'result.json', result)
        self.steps.append({'path': str(log), 'stage': self.stage, 'command': arguments[0]})
        self.check()
        return result

    def card(self, operation, extra=()):
        require(operation in self.card_versions and len(self.cards) < 90, 'GAMEPLAY_CARD_LIMIT_OR_OPERATION')
        self.stage = operation
        built = self.call(['prepare', '--operation', operation, '--session', str(self.session),
                           '--target-level', str(base.LEVEL), '--previous-run', str(self.anchor), *extra])
        require(built.get('launchable') is True and built.get('mode') == operation, 'NONLAUNCHABLE_OR_WRONG_CARD')
        run = base.project_path(built['run'], directory=True, boundary=CARDS)
        require(run not in self.card_paths, 'PREPARE_REUSED_CARD')
        self.card_paths.add(run)
        sha = digest(run / 'prepared.json')
        require(built.get('preparedSha256') == sha, 'PREPARED_HASH_MISMATCH')
        prepared = read(run / 'prepared.json')
        # v3 control cards bind the predecessor through lineage, not anchorRun.
        # v4/v6 cards additionally name anchorRun. Keep their actual schemas distinct.
        if operation == 'trial-frame':
            ancestors = (prepared.get('lineage') or {}).get('ancestors')
            anchor_bound = (type(ancestors) is list and bool(ancestors) and
                            type(ancestors[-1]) is dict and ancestors[-1].get('run') == str(self.anchor))
        else:
            anchor_bound = prepared.get('anchorRun') == str(self.anchor)
        require(prepared.get('kind') == f'playtest-control-prepared-v{self.card_versions[operation]}' and
                prepared.get('mode') == operation and prepared.get('targetLevelId') == base.LEVEL and
                anchor_bound and prepared.get('compileOnly') is False and
                prepared.get('launchable') is True and prepared.get('action') == 19 and
                prepared.get('receiptVersion') == 24, 'PREPARED_TARGET_OR_PROTOCOL_MISMATCH')
        self.validate_prepared(operation, prepared)
        self.sources[run / 'prepared.json'] = sha
        self.dispatch_attempts += 1
        reply = self.call(['dispatch', '--run', str(run), '--elevated-queue', str(self.queue)])
        base.Transaction.clean(reply)
        decoded = self.call(['decode', '--run', str(run)])
        base.Transaction.clean(decoded)
        require(decoded.get('mode') == 'play' and decoded.get('trialIdentityBound') is True and
                decoded.get('playerBelongsToTargetLevel') is True, 'DECODED_TRIAL_NOT_PROVEN')
        require(decoded.get('operation') == operation and decoded.get('run') == str(run) and
                decoded.get('targetLevelId') == base.LEVEL and decoded.get('nativeStarted') is True,
                'DECODED_CARD_MISMATCH')
        require(decoded.get('binaryReceiptSha256') == digest(run / 'acceptance.bin') and
                decoded.get('rawReceiptSha256') == digest(run / 'stdout.jsonl'), 'RAW_RECEIPT_CHANGED')
        for name in ('acceptance.bin', 'stdout.jsonl', 'exit.json'):
            self.sources[run / name] = digest(run / name)
        self.cards.append({'operation': operation, 'run': str(run), 'preparedSha256': sha})
        return run, decoded

    def validate_prepared(self, operation, prepared):
        """A stricter consumer may check its plan before any native dispatch."""

    @staticmethod
    def option(state, text, *, missing_allowed=False):
        require(state.get('optionsComplete') is True and type(state.get('options')) is list,
                'OPTION_LIST_INCOMPLETE')
        rows = [r for r in state['options'] if r.get('text') == text and
                r.get('active') is True and r.get('enabled') is True]
        require(len(rows) <= 1, 'OPTION_LABEL_AMBIGUOUS')
        if missing_allowed and not rows:
            return None
        require(len(rows) == 1, 'EXACT_OPTION_NOT_AVAILABLE')
        row = rows[0]
        require(type(row.get('index')) is int and 0 <= row['index'] < len(state['options']) and
                state['options'][row['index']] == row, 'OPTION_INDEX_MISMATCH')
        return row

    def frame(self, after):
        if not self.plan['captureFrames']:
            return
        run, result = self.card('trial-frame')
        require(result.get('renderFrameCaptured') is True, 'NATIVE_FRAME_NOT_CAPTURED')
        path = base.project_path(result['framePath'], boundary=run)
        require(path.name == 'frame.png' and result.get('png', {}).get('sha256') == digest(path),
                'NATIVE_FRAME_HASH_MISMATCH')
        self.sources[path] = digest(path)
        self.frames.append({'after': after, 'path': str(path), 'sha256': digest(path),
                            'visualReviewComplete': False})

    def perform(self, action):
        kind = action['kind']
        if kind == 'wait':
            self.stage = 'wait'
            self.check()
            self.sleeper(action['seconds'])
            self.check()
            self.actions.append({'id': action['id'], 'kind': kind, 'seconds': action['seconds']})
            return
        option = None
        for _ in range(action.get('observations', 1)):
            baseline, state = self.card('input-state')
            if kind != 'option':
                break
            option = self.option(state, action['label'], missing_allowed=True)
            if option is not None:
                break
        require(kind != 'option' or option is not None, 'EXACT_OPTION_NOT_AVAILABLE')
        ident = self.directory.name[:20] + '-' + str(len(self.actions))
        extra = ['--input-baseline', str(baseline), '--input-id', ident]
        operation = {'option': 'interact-option', 'attack': 'attack-tap', 'move': 'move-pulse'}[kind]
        if kind == 'option':
            extra += ['--option-index', str(option['index']), '--label', action['label']]
        elif kind == 'attack':
            require(state.get('attackAvailable') is True, 'ATTACK_MAPPING_UNAVAILABLE')
        elif kind == 'move':
            require(state.get('inputSourceIdle') is True, 'EXISTING_INPUT_SOURCE_ACTIVE')
            for flag, key in [('angle', 'angle'), ('strength', 'strength'), ('duration-ms', 'durationMs'),
                              ('max-distance', 'maxDistance')]:
                extra += ['--' + flag, str(action[key])]
        run, result = self.card(operation, extra)
        require(result.get('nativeInputSubmitted') is True and result.get('inputReleased') is True,
                'INPUT_NOT_SUBMITTED_AND_RELEASED')
        if kind == 'option':
            require(result.get('interactionCallbackSubmitted') is True, 'INTERACTION_CALLBACK_UNPROVEN')
        self.actions.append({'id': action['id'], 'kind': kind, 'run': str(run), 'baseline': str(baseline),
                             'inputId': ident, 'trajectory': result.get('trajectory', []),
                             'displacement': result.get('displacement'), 'label': action.get('label')})
        self.frame(action['id'])

    def execute(self):
        _, state = self.card('input-state')
        pos = state.get('worldPosition')
        require(type(pos) is list and len(pos) == 3 and
                all(type(v) in (int, float) and math.isfinite(v) for v in pos), 'PLAYER_POSITION_MISSING')
        require(math.dist(pos, self.plan['start']['worldPosition']) <= self.plan['start']['radius'],
                'PLAYER_OUTSIDE_REVIEWED_START')
        self.frame('before')
        before, inventory = self.card('inventory-state')
        require(inventory.get('inventoryComplete') is True and
                inventory.get('inventoryQuantitiesVerified') is True, 'INVENTORY_NOT_COMPLETE')
        queries = [{k: r[k] for k in ('source', 'configId', 'resourceType')} for r in self.plan['effects']]
        for row in self.plan['effects']:
            field = 'physicalItemCounts' if row['source'] == 'slots' else 'paymentResourceCounts'
            matches = [r for r in inventory[field] if
                       all(r.get(k) == row[k] for k in ('configId', 'resourceType'))]
            require(len(matches) <= 1, 'STARTING_RESOURCE_BALANCE_AMBIGUOUS')
            quantity = int(matches[0]['quantity']) if matches else 0
            require(quantity + min(0, row['delta']) >= 0, 'STARTING_BALANCE_INSUFFICIENT')
        path = self.directory / 'queries.json'
        write(path, queries)
        self.sources[path] = digest(path)
        for action in self.plan['actions']:
            self.perform(action)
        if self.plan['finalOptions']:
            _, state = self.card('input-state')
            for text in self.plan['finalOptions']:
                self.option(state, text)
        comparisons, expected = [], [r['delta'] for r in self.plan['effects']]
        for _ in range(4):
            after, _ = self.card('inventory-state')
            result = self.call(['inventory-diff', '--before-run', str(before), '--after-run', str(after),
                                '--queries', str(path)])
            base.Transaction.clean(result)
            require(result.get('operation') == 'inventory-diff' and result.get('targetLevelId') == base.LEVEL,
                    'DIFF_TARGET_MISMATCH')
            changes = result.get('changes')
            require(type(changes) is list and len(changes) == len(queries), 'DIFF_ROWS_INVALID')
            for row, query in zip(changes, queries):
                require(all(row.get(k) == value for k, value in query.items()), 'DIFF_RESOURCE_MISMATCH')
            delta = [int(r['delta']) for r in changes]
            comparisons.append({'afterRun': str(after), 'delta': delta, 'evidence': result})
            if delta == expected:
                return {'ok': True, 'expectedQuantityDeltasObserved': True, 'expectedDeltas': expected,
                        'comparisons': comparisons, 'finalOptionsObserved': self.plan['finalOptions']}
            require(all(min(0, want) <= got <= max(0, want) for got, want in zip(delta, expected)),
                    'UNEXPECTED_INVENTORY_DELTA')
        return {'ok': False, 'code': 'EXPECTED_DELTAS_NOT_OBSERVED', 'expectedQuantityDeltasObserved': False,
                'expectedDeltas': expected, 'comparisons': comparisons}


def run(plan, *, operation_id, session_file, trial_anchor, queue, freeze_path, freeze_sha256,
        gate_open=False, _commands=None, _sleep=None):
    require(gate_open is True, 'UNIFIED_ACCEPTANCE_GATE_CLOSED')
    plan = validate_plan(plan)
    require(type(operation_id) is str and base.IDENT.fullmatch(operation_id), 'UNIQUE_OPERATION_ID_REQUIRED')
    session = base.project_path(session_file)
    anchor = base.project_path(trial_anchor, directory=True, boundary=CARDS)
    queue = base.project_path(queue, directory=True, boundary=ROOT / '.runtime/editor-bridge')
    freeze = base.project_path(freeze_path)
    sources = base.freeze_sources(freeze, freeze_sha256)
    for source in (Path(__file__).resolve(), Path(base.__file__).resolve(), session,
                   anchor / 'prepared.json', ROOT / 'tools/editor-bridge/elevated-request.py'):
        sources[base.project_path(source)] = digest(source)
    commands = _commands or base.Commands()
    if _commands is not None or _sleep is not None:
        require(_commands is not None and getattr(commands, 'private_fixture', False) is True,
                'PRIVATE_TEST_SEAM_ONLY')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    directory = OUTPUT / hashlib.sha256(operation_id.encode()).hexdigest()[:32]
    directory.mkdir(exist_ok=False)
    write(directory / 'request.json', {'plan': plan, 'operationId': operation_id, 'session': str(session),
          'trialAnchor': str(anchor), 'queue': str(queue), 'sources': {str(k): v for k, v in sources.items()},
          'privateFixture': commands.private_fixture, 'replayAllowed': False})
    sources[directory / 'request.json'] = digest(directory / 'request.json')
    seq = Interaction(plan, directory, session, anchor, queue, sources, commands, _sleep or time.sleep)
    try:
        result = seq.execute()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {'ok': False, 'code': str(error), 'expectedQuantityDeltasObserved': False}
    result.update(operationId=operation_id, directory=str(directory), lastStage=seq.stage,
                  cards=seq.cards, actions=seq.actions, steps=seq.steps, frames=seq.frames,
                  dispatchAttempts=seq.dispatch_attempts, replayAllowed=False,
                  privateFixture=commands.private_fixture, wholeGameAccepted=False,
                  visualAccepted=False, collisionVerified=False, targetNpcIdentityVerified=False,
                  independentLevelTravelVerified=False,
                  attribution='Native input and exact labels followed by independently decoded inventory deltas. '
                              'Captured frames require separate visual review; start radius is not NPC identity.')
    write(directory / 'result.json', result)
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
        result = run(read(args.plan), operation_id=args.operation_id, session_file=args.session,
                     trial_anchor=args.trial_anchor, queue=args.queue, freeze_path=args.freeze,
                     freeze_sha256=args.freeze_sha256, gate_open=args.gate_open)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'ok': False, 'code': str(error), 'replayAllowed': False}
    print(base.json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
