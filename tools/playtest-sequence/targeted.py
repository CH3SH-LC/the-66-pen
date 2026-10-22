"""Native target-bound Chinese option sequences; no desktop or business setters.

Each action consumes a fresh v9 source-directory observation and a v10 atomic
native callback. Optional inventory effects are independently decoded. This is
not a scheduler for short-lived fishing options or proof of a dialogue's text.
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
OUTPUT = ROOT / '.runtime/playtest-targeted-sequences'
require = b.require


def target(row):
    require(type(row) is dict and set(row) == {'editorGuid', 'runtimeId', 'label'}, 'TARGET_FIELDS')
    for key in ('editorGuid', 'runtimeId'):
        require(type(row[key]) is int and 0 < row[key] <= 0xffffffff, 'TARGET_IDENTITIES')
    g.label(row['label'])
    return row


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == {
        'schemaVersion', 'levelId', 'start', 'actions', 'effects', 'finalOptions', 'captureFrames'},
        'TARGETED_SEQUENCE_FIELDS')
    require(type(plan['schemaVersion']) is int and plan['schemaVersion'] == 1 and
            type(plan['levelId']) is int and plan['levelId'] == b.LEVEL, 'TARGETED_SEQUENCE_LEVEL')
    start = plan['start']
    require(type(start) is dict and set(start) == {'worldPosition', 'radius'}, 'TARGETED_START')
    require(type(start['worldPosition']) is list and len(start['worldPosition']) == 3, 'TARGETED_START')
    for value in start['worldPosition']:
        g.number(value, -1e6, 1e6, 'TARGETED_START')
    g.number(start['radius'], .1, 20, 'TARGETED_START_RADIUS')
    require(type(plan['captureFrames']) is bool, 'TARGETED_CAPTURE_FLAG')
    require(type(plan['actions']) is list and 1 <= len(plan['actions']) <= 12, 'TARGETED_ACTION_COUNT')
    ids = set()
    for row in plan['actions']:
        require(type(row) is dict and set(row) == {'id', 'target'}, 'TARGETED_ACTION_FIELDS')
        require(type(row['id']) is str and b.IDENT.fullmatch(row['id']) and row['id'] not in ids,
                'TARGETED_ACTION_ID')
        ids.add(row['id'])
        target(row['target'])
    require(type(plan['finalOptions']) is list and len(plan['finalOptions']) <= 16, 'TARGETED_FINAL_OPTIONS')
    final = [tuple(target(row)[k] for k in ('editorGuid', 'runtimeId', 'label')) for row in plan['finalOptions']]
    require(len(set(final)) == len(final), 'TARGETED_DUPLICATE_FINAL_OPTION')
    require(type(plan['effects']) is list and len(plan['effects']) <= 16, 'TARGETED_EFFECTS')
    seen = set()
    for row in plan['effects']:
        require(type(row) is dict and set(row) == {'source', 'configId', 'resourceType', 'delta'},
                'TARGETED_EFFECT_FIELDS')
        require(row['source'] in ('slots', 'payment-resources'), 'TARGETED_EFFECT_SOURCE')
        require(type(row['configId']) is int and 0 < row['configId'] <= 0xffffffff and
                type(row['resourceType']) is int and 0 <= row['resourceType'] <= 0xffffffff,
                'TARGETED_EFFECT_ID')
        require(type(row['delta']) is int and 0 < abs(row['delta']) <= 10**9, 'TARGETED_EFFECT_DELTA')
        key = tuple(row[k] for k in ('source', 'configId', 'resourceType'))
        require(key not in seen, 'TARGETED_DUPLICATE_EFFECT')
        seen.add(key)
    return b.json.loads(b.json.dumps(plan, allow_nan=False))


def select_option(result, expected):
    require(result.get('sourceDirectoryKnown') is True and result.get('interactionOptionsKnown') is True and
            type(result.get('interactionOptions')) is list, 'TARGETED_DIRECTORY_UNKNOWN')
    rows = []
    for index, row in enumerate(result['interactionOptions']):
        host = row.get('host') or {}
        if row.get('text') != expected['label'] or row.get('active') != 1 or row.get('enabled') != 1:
            continue
        if host.get('editorEntityGuid') != expected['editorGuid'] or host.get('runtimeId') != expected['runtimeId']:
            continue
        require(row.get('hostRuntimeIdentityVerified') is True and row.get('hostIdentityVerified') is True and
                row.get('hostTrialMembershipVerified') is True and host.get('identityMappingVerified') is True and
                host.get('targetLevelSpawnMembershipVerified') is True and host.get('belongsToBoundTrial') is True and
                row.get('ownerRuntimeId') == expected['runtimeId'] and
                (host.get('sourceInstance') or {}).get('editorGuid') == expected['editorGuid'],
                'TARGETED_HOST_NOT_PROVEN')
        rows.append((index, row))
    require(len(rows) == 1, 'TARGETED_OPTION_MISSING_OR_AMBIGUOUS')
    return rows[0]


class TargetedSequence(g.Interaction):
    card_versions = dict(g.KINDS, **{'trial-entities': 9, 'targeted-interact': 10})

    def validate_prepared(self, operation, prepared):
        if operation == 'targeted-interact':
            require(prepared.get('targetPlan') == self.pending_target and
                    (prepared.get('targetBaseline') or {}).get('run') == self.pending_baseline,
                    'TARGETED_PREPARED_TARGET_CHANGED')

    def card(self, operation, extra=()):
        run, decoded = super().card(operation, extra)
        if operation == 'input-state':
            avatar = decoded.get('avatarId')
            require(type(avatar) is int and avatar > 0, 'TARGETED_AVATAR_UNKNOWN')
            require(avatar == getattr(self, 'avatar_id', avatar) and decoded.get('inputSourceIdle') is True,
                    'TARGETED_AVATAR_OR_INPUT_CHANGED')
            self.avatar_id = avatar
        elif operation in ('trial-entities', 'targeted-interact'):
            native = decoded.get('nativeReceipt') or {}
            contact = native.get('contact') if operation == 'trial-entities' else (native.get('directory') or {}).get('contact')
            actual = (((contact or {}).get('control') or {}).get('observation') or {}).get('after') or {}
            require(actual.get('avatarId') == self.avatar_id, 'TARGETED_AVATAR_OR_INPUT_CHANGED')
        return run, decoded

    def invoke(self, action):
        baseline, state = self.card('trial-entities')
        ordinal, _ = select_option(state, action['target'])
        expected = action['target']
        ident = self.directory.name + '-' + str(len(self.actions))
        self.pending_target = dict(targetId=ident, editorGuid=expected['editorGuid'],
            runtimeId=expected['runtimeId'], optionIndex=ordinal, label=expected['label'])
        self.pending_baseline = str(baseline)
        run, result = self.card('targeted-interact', ['--target-baseline', str(baseline), '--target-id', ident,
            '--expected-editor-guid', str(expected['editorGuid']), '--expected-runtime-id', str(expected['runtimeId']),
            '--option-index', str(ordinal), '--label', expected['label']])
        require(result.get('atomicTargetIdentityVerified') is True and result.get('actionAttempted') is True and
                result.get('actionReturned') is True and result.get('invokedEditorEntityGuid') == expected['editorGuid'] and
                result.get('invokedRuntimeId') == expected['runtimeId'] and result.get('invokedLabel') == expected['label'],
                'TARGETED_ATOMIC_CALLBACK_NOT_PROVEN')
        self.actions.append(dict(id=action['id'], target=expected, baseline=str(baseline), run=str(run),
                                 atomicTargetIdentityVerified=True))
        self.frame(action['id'])

    def execute(self):
        _, state = self.card('input-state')
        pos = state.get('worldPosition')
        require(type(pos) is list and len(pos) == 3 and
                all(type(v) in (int, float) and math.isfinite(v) for v in pos), 'TARGETED_START_UNKNOWN')
        require(math.dist(pos, self.plan['start']['worldPosition']) <= self.plan['start']['radius'],
                'TARGETED_OUTSIDE_START')
        self.frame('before')
        effects = self.plan['effects']
        if effects:
            before, inventory = self.card('inventory-state')
            require(inventory.get('inventoryComplete') is True and inventory.get('inventoryQuantitiesVerified') is True,
                    'INVENTORY_NOT_COMPLETE')
            queries = [{k: row[k] for k in ('source', 'configId', 'resourceType')} for row in effects]
            for row in effects:
                field = 'physicalItemCounts' if row['source'] == 'slots' else 'paymentResourceCounts'
                found = [r for r in inventory[field] if all(r.get(k) == row[k] for k in ('configId', 'resourceType'))]
                require(len(found) <= 1, 'STARTING_RESOURCE_BALANCE_AMBIGUOUS')
                quantity = int(found[0]['quantity']) if found else 0
                require(quantity + min(0, row['delta']) >= 0, 'STARTING_BALANCE_INSUFFICIENT')
            query_path = self.directory / 'queries.json'
            b.write(query_path, queries)
            self.sources[query_path] = b.digest(query_path)
        for action in self.plan['actions']:
            self.invoke(action)
        if self.plan['finalOptions']:
            _, state = self.card('trial-entities')
            for expected in self.plan['finalOptions']:
                select_option(state, expected)
        result = dict(ok=True, targetCallbacksVerified=True, expectedQuantityDeltasObserved=False,
                      businessEffectVerified=False, comparisons=[], finalTargetOptionsObserved=self.plan['finalOptions'])
        if not effects:
            return result
        expected = [r['delta'] for r in effects]
        for _ in range(4):
            after, _ = self.card('inventory-state')
            difference = self.call(['inventory-diff', '--before-run', str(before), '--after-run', str(after),
                                    '--queries', str(query_path)])
            b.Transaction.clean(difference)
            require(difference.get('operation') == 'inventory-diff' and difference.get('targetLevelId') == b.LEVEL,
                    'TARGETED_DIFF_TARGET')
            changes = difference.get('changes')
            require(type(changes) is list and len(changes) == len(queries), 'TARGETED_DIFF_ROWS')
            for row, query in zip(changes, queries):
                require(all(row.get(k) == value for k, value in query.items()), 'TARGETED_DIFF_RESOURCE')
            delta = [int(r['delta']) for r in changes]
            result['comparisons'].append(dict(afterRun=str(after), delta=delta, evidence=difference))
            if delta == expected:
                result.update(expectedQuantityDeltasObserved=True, businessEffectVerified=True)
                return result
            require(all(min(0, want) <= got <= max(0, want) for got, want in zip(delta, expected)),
                    'UNEXPECTED_INVENTORY_DELTA')
        result.update(ok=False, code='EXPECTED_DELTAS_NOT_OBSERVED')
        return result


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
        trialAnchor=str(anchor), queue=str(queue), sources={str(k): v for k, v in sources.items()},
        privateFixture=commands.private_fixture, replayAllowed=False))
    sources[directory / 'request.json'] = b.digest(directory / 'request.json')
    seq = TargetedSequence(plan, directory, session, anchor, queue, sources, commands, time.sleep)
    try:
        result = seq.execute()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = dict(ok=False, code=str(error), targetCallbacksVerified=False, businessEffectVerified=False,
                      expectedQuantityDeltasObserved=False)
    result.update(operationId=operation_id, directory=str(directory), lastStage=seq.stage, cards=seq.cards,
        actions=seq.actions, steps=seq.steps, frames=seq.frames, dispatchAttempts=seq.dispatch_attempts,
        privateFixture=commands.private_fixture, replayAllowed=False, wholeGameAccepted=False,
        visualAccepted=False, collisionVerified=False, targetNpcIdentityVerified=False,
        independentLevelTravelVerified=False, timedFishingVerified=False, dialogueContentVerified=False,
        attribution='Native v9 target membership followed by v10 atomic exact-host callback. Optional quantity '
                    'effects use independent inventory diffs. No appearance, dialogue content or timed-window claim.')
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
