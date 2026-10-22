"""Bounded large-scene creation with complete per-batch evidence and no replay.

prepare is offline. run explicitly dispatches through the existing reviewed native
route. An interrupted/partial/unknown batch is a sticky stop, never a retry list.
The 3000 default is a conservative planning budget from historical official docs,
not a claim about current game quota accounting or a bypass of the native limit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import build_scene_profile as builder
import build_readonly_profile as readonly
import native_write_review as review_api
import orchestrate_write_review as reviewer
import scene_cli

OUTPUT = ROOT / '.runtime/game-executor/scene-scale'
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_PLAN_ENTITIES = 3000
DEFAULT_BATCH = 64
IDENTITY_FIELDS = ('owner', 'config', 'context', 'dictionaryKey', 'id', 'configId')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    """Immutable, flushed publication. Existing evidence is never overwritten."""
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def digest(path):
    return builder.digest(Path(path))


def canonical(value):
    return review_api.canonical_hash(value)


def now():
    return datetime.now(timezone.utc).isoformat()


def runtime_dir(raw):
    path = Path(raw).absolute()
    # Same explicit no-reparse scope as the production queue. Check an existing
    # immutable operation marker, not an arbitrary caller-selected executable.
    scene_cli.guarded_runtime_file(path / 'operation.json', 'OPERATION')
    return path


def normalize_plan(value, *, entity_budget=3000, batch_size=DEFAULT_BATCH):
    require(type(entity_budget) is int and 1 <= entity_budget <= MAX_PLAN_ENTITIES,
            'ENTITY_BUDGET_MUST_BE_1_TO_3000')
    require(type(batch_size) is int and 1 <= batch_size <= builder.MAX_BATCH,
            'BATCH_SIZE_MUST_BE_1_TO_256')
    require(isinstance(value, dict) and set(value) <= {'placements', 'coordinateSpace', 'description'},
            'PLAN_FIELDS_INVALID')
    require(value.get('coordinateSpace', 'world') == 'world', 'WORLD_COORDINATES_REQUIRED')
    rows = value.get('placements')
    require(isinstance(rows, list) and 1 <= len(rows) <= entity_budget,
            'PLAN_EXCEEDS_ENTITY_BUDGET_OR_EMPTY')
    placements = []
    for index, row in enumerate(rows):
        placement = scene_cli.normalize_placement(row, index)
        if row.get('label'):
            placement['label'] = row['label']
        placements.append(placement)
    return dict(schemaVersion=1, placements=placements, coordinateSpace='world',
                entityBudget=entity_budget, batchSize=batch_size,
                budgetEvidence='Conservative planning ceiling from historical official docs; native quotas remain authoritative')


def prepare(plan, operation_id, level_id, *, entity_budget=3000, batch_size=DEFAULT_BATCH):
    require(isinstance(operation_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', operation_id),
            'INVALID_OPERATION_ID')
    level_id = builder.resolve_level(level_id)
    source = Path(plan)
    with source.open('rb') as stream:
        raw = stream.read(MAX_PLAN_BYTES + 1)
    require(len(raw) <= MAX_PLAN_BYTES, 'PLAN_TOO_LARGE')
    normalized = normalize_plan(json.loads(raw.decode('utf-8-sig')), entity_budget=entity_budget, batch_size=batch_size)
    operation = OUTPUT / operation_id
    operation.mkdir(parents=True, exist_ok=False)
    write(operation / 'plan.json', normalized)
    write(operation / 'operation.json', dict(schemaVersion=1, operationId=operation_id, levelId=level_id,
          planSha256=digest(operation / 'plan.json'), sourceSha256=hashlib.sha256(raw).hexdigest(),
          createdUtc=now(), mutationAttempted=False))
    return dict(ok=True, operation=str(operation), state='prepared', placements=len(normalized['placements']),
                batchCount=math.ceil(len(normalized['placements']) / batch_size), mutationAttempted=False)


def load(operation):
    operation = runtime_dir(operation)
    manifest = read(operation / 'operation.json')
    require(manifest.get('schemaVersion') == 1, 'OPERATION_VERSION')
    require(digest(operation / 'plan.json') == manifest.get('planSha256'), 'PLAN_CHANGED')
    plan = read(operation / 'plan.json')
    normalized = normalize_plan({'placements': plan['placements'], 'coordinateSpace': plan['coordinateSpace']},
                                entity_budget=plan['entityBudget'], batch_size=plan['batchSize'])
    require(plan == normalized, 'PLAN_NOT_CANONICAL')
    return operation, manifest, plan


def identities(snapshot):
    rows = snapshot['entities']
    result = {row['id']: tuple(row[name] for name in IDENTITY_FIELDS) for row in rows}
    require(len(result) == len(rows), 'DUPLICATE_ENTITY_IDS')
    return result


def same_scene(previous, current):
    require(previous['pointers']['currentContext'] == current['pointers']['currentContext'], 'CONTEXT_CHANGED')
    require(previous['origin'] == current['origin'], 'WORLD_ORIGIN_CHANGED')
    require(identities(previous) == identities(current), 'SCENE_CHANGED_BETWEEN_BATCHES')


def reconcile_batch(before, after, placements, placed_ids):
    """Full-set reconciliation, never a count-only or prefix check."""
    builder.validate_baseline(before, 'save')
    builder.validate_baseline(after, 'save')
    require(before['pointers']['currentContext'] == after['pointers']['currentContext'], 'CONTEXT_CHANGED')
    require(before['origin'] == after['origin'], 'WORLD_ORIGIN_CHANGED')
    old, new = identities(before), identities(after)
    require(all(new.get(entity_id) == row for entity_id, row in old.items()), 'EXISTING_ENTITY_CHANGED')
    require(isinstance(placed_ids, list) and len(placed_ids) == len(placements), 'PLACEMENT_COUNT_MISMATCH')
    require(all(type(entity_id) is int and 0 < entity_id < 2 ** 32 for entity_id in placed_ids), 'PLACEMENT_ID_INVALID')
    require(len(set(placed_ids)) == len(placed_ids) and not set(placed_ids) & old.keys(), 'PLACEMENT_IDS_REUSED')
    require(set(new) - set(old) == set(placed_ids), 'ADDED_ENTITY_SET_MISMATCH')
    by_id = {row['id']: row for row in after['entities']}
    require(all(by_id[entity_id]['configId'] == row['template_id'] for row, entity_id in zip(placements, placed_ids)),
            'PLACEMENT_TEMPLATE_MISMATCH')
    return dict(ok=True, entityIds=placed_ids, beforeCount=len(old), afterCount=len(new),
                allPreviousIdentitiesPreserved=True, completeIdReconciliation=True,
                liveTransformVerified=False)


def send(action, session, level_id, *, queue=None, direct=False, review=None, placements=None):
    if queue:
        request = dict(kind='native-scene', action=action, sessionPath=str(session), levelId=level_id)
        if action == 'inspect':
            request['largeScene'] = True
        else:
            request['reviewPath'] = str(review)
        if placements is not None:
            request['placements'] = scene_cli.normalize_placements(placements)
        return scene_cli.send_queued_scene(request, action, Path(queue))
    require(not direct or scene_cli.is_admin_token(), 'DIRECT_ELEVATED_TOKEN_REQUIRED')
    profile = builder.build_profile(action, session_path=session, level_id=level_id,
                                    review_path=review, placements=placements, large_scene=action == 'inspect')
    return scene_cli.run_profile(profile, direct_elevated=direct)


def verified_run(reply, level_id, kind):
    require(isinstance(reply, dict) and reply.get('ok') is True and not reply.get('outcomeUncertain'),
            'NATIVE_RUN_NOT_COMPLETE')
    run = Path(reply['run'])
    snapshot, prepared = review_api.load_baseline(run, kind, level_id)
    require(snapshot['version'] == 2, 'LARGE_SCENE_V2_REQUIRED')
    record, _ = readonly.load_decoder().read_probe(run / 'stdout.jsonl')
    return run, snapshot, prepared, record


def same_session(expected, actual):
    require(all(expected.get(key) == actual.get(key) for key in review_api.SESSION_FIELDS), 'SESSION_CHANGED')


def raw_evidence_hashes(run):
    names = ('prepared.json', 'build-result.json', 'stdout.jsonl', 'exit.json', 'result.json')
    return {name: digest(run / name) for name in names}


def validate_commit(path, level_id, placements, expected_before=None):
    commit = read(path)
    run = Path(commit['run'])
    require(raw_evidence_hashes(run) == commit['evidenceHashes'], 'COMMITTED_EVIDENCE_CHANGED')
    _, after, prepared, record = verified_run(read(run / 'result.json'), level_id, 'action-after')
    expected_request = dict(action='create-batch', levelId=level_id, placements=placements)
    require(canonical(prepared.get('request')) == canonical(expected_request), 'COMMIT_REQUEST_MISMATCH')
    claim = read(Path(path).parent / 'claim.json')
    require(claim['requestSha256'] == canonical(expected_request), 'CLAIM_REQUEST_MISMATCH')
    require(prepared.get('reviewSha256') == claim['reviewSha256'], 'COMMIT_REVIEW_MISMATCH')
    before = readonly.load_decoder().decode_snapshot(record)
    if expected_before is not None:
        same_scene(expected_before, before)
    check = reconcile_batch(before, after, placements, record.get('action', {}).get('placedIds'))
    require(check == commit['reconciliation'], 'COMMIT_RECONCILIATION_CHANGED')
    return after, check['entityIds']


def known_partial(reply):
    """Diagnostics only: reported IDs remain untrusted until full reconciliation."""
    result = dict(entityIds=[], outcomeUncertain=True, rawReceipt=None)
    try:
        if isinstance(reply, dict) and reply.get('run'):
            run = Path(reply['run'])
            record, _ = readonly.load_decoder().read_probe(run / 'stdout.jsonl')
            action = record.get('action', {})
            result.update(entityIds=[v for v in action.get('placedIds', []) if type(v) is int and v > 0],
                          reportedPlacedCount=action.get('placedCount'), actionStatus=action.get('status'),
                          rawReceipt=str(run / 'stdout.jsonl'), rawSha256=digest(run / 'stdout.jsonl'))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def run(operation, session, *, queue=None, direct=False, max_seconds=1800, max_batches=64, save=False):
    require(type(max_seconds) is int and 30 <= max_seconds <= 7200, 'RUN_TIME_BOUND_30_TO_7200')
    require(type(max_batches) is int and 1 <= max_batches <= 128, 'RUN_BATCH_BOUND_1_TO_128')
    require(not (queue and direct), 'TRANSPORT_CONFLICT')
    operation, manifest, plan = load(operation)
    session = scene_cli.guarded_runtime_file(session, 'SESSION')
    session_identity = read(session)
    level_id = manifest['levelId']
    lock = operation / 'running.lock'
    # A lock left by a killed process is not automatically deleted: some native
    # action may still be in flight. Read-only status is always available.
    write(lock, dict(startedUtc=now(), pid=os.getpid()))
    start, dispatched = time.monotonic(), 0
    previous, all_ids = None, []
    try:
        rows, batch_size = plan['placements'], plan['batchSize']
        for batch_index, offset in enumerate(range(0, len(rows), batch_size)):
            batch = [scene_cli.normalize_placement(row, i) for i, row in enumerate(rows[offset:offset + batch_size])]
            folder = operation / ('batch-%04d' % batch_index)
            commit_file = folder / 'commit.json'
            if commit_file.exists():
                previous, ids = validate_commit(commit_file, level_id, batch, previous)
                committed_prepared = read(Path(read(commit_file)['run']) / 'prepared.json')
                same_session(session_identity, committed_prepared['session'])
                all_ids.extend(ids)
                continue
            if folder.exists() and (folder / 'claim.json').exists():
                raise ValueError('BATCH_ALREADY_ATTEMPTED_WITHOUT_VERIFIED_COMMIT: ' + str(folder))
            if dispatched >= max_batches or time.monotonic() - start >= max_seconds:
                return dict(ok=True, state='bounded-stop', operation=str(operation), committed=len(all_ids),
                            complete=False, retryAttempted=False, nextPlacement=offset)
            folder.mkdir(exist_ok=True)
            # Every batch gets a fresh observation; previous action receipts are
            # used only for continuity, not as a substitute for this observation.
            observed = send('inspect', session, level_id, queue=queue, direct=direct)
            baseline_run, baseline, baseline_prepared, _ = verified_run(observed, level_id, 'readonly')
            same_session(session_identity, baseline_prepared['session'])
            if previous is not None:
                same_scene(previous, baseline)
            remaining = len(rows) - offset
            require(len(baseline['entities']) + remaining <= plan['entityBudget'], 'SCENE_PLUS_PLAN_EXCEEDS_BUDGET')
            builder.validate_baseline(baseline, 'create-batch', templates=tuple(row['template_id'] for row in batch))
            request = dict(action='create-batch', levelId=level_id, placements=batch)
            # Review creation validates all raw baseline artifacts and makes a
            # byte-identical formal-save recovery copy before any claim/dispatch.
            review = reviewer.orchestrate(session_path=session, level_id=level_id, request=request,
                baseline_run=baseline_run, baseline_kind='readonly', recovery_dir=folder / 'recovery')
            write(folder / 'claim.json', dict(requestSha256=canonical(request), offset=offset, count=len(batch),
                  baselineRun=str(baseline_run), baselineReceiptSha256=digest(baseline_run / 'stdout.jsonl'),
                  reviewPath=review['reviewPath'], reviewSha256=review['reviewSha256'], claimedUtc=now()))
            reply = None
            try:
                reply = send('create-batch', session, level_id, queue=queue, direct=direct,
                             review=review['reviewPath'], placements=batch)
                write(folder / 'reply.json', reply)
                run_path, after, prepared, record = verified_run(reply, level_id, 'action-after')
                require(canonical(prepared.get('request')) == canonical(request), 'NATIVE_REQUEST_MISMATCH')
                require(prepared.get('reviewSha256') == review['reviewSha256'], 'NATIVE_REVIEW_MISMATCH')
                raw_before = readonly.load_decoder().decode_snapshot(record)
                same_scene(baseline, raw_before)
                check = reconcile_batch(raw_before, after, batch, record.get('action', {}).get('placedIds'))
                write(commit_file, dict(run=str(run_path), evidenceHashes=raw_evidence_hashes(run_path),
                      reconciliation=check, committedUtc=now()))
                previous = after
                all_ids.extend(check['entityIds'])
                dispatched += 1
            except Exception as error:
                write(folder / 'blocked.json', dict(error=str(error), **known_partial(reply), retryAttempted=False))
                raise
        summary = dict(ok=True, state='created', operation=str(operation), committed=len(all_ids),
                       complete=True, retryAttempted=False, persistentSaveVerified=False,
                       liveTransformVerified=False, entityIdsPath=str(operation / 'created.json'))
        if not (operation / 'created.json').exists():
            write(operation / 'created.json', dict(entityIds=all_ids, completedUtc=now()))
        else:
            require(read(operation / 'created.json')['entityIds'] == all_ids, 'CREATED_ID_MAP_CHANGED')
        if save:
            summary['save'] = save_operation(operation, manifest, session, previous, queue=queue, direct=direct)
            summary['persistentSaveVerified'] = summary['save'].get('persistentSaveVerified') is True
        return summary
    finally:
        # Only this process's own in-flight lock; claims remain permanently.
        lock.unlink()


def save_operation(operation, manifest, session, previous, *, queue=None, direct=False):
    if (operation / 'save-claim.json').exists():
        if (operation / 'save-reply.json').exists():
            reply = read(operation / 'save-reply.json')
            return verify_save(operation, reply['run'])
        raise ValueError('SAVE_ALREADY_ATTEMPTED_WITHOUT_RECEIPT')
    level_id = manifest['levelId']
    observed = send('inspect', session, level_id, queue=queue, direct=direct)
    baseline_run, baseline, _, _ = verified_run(observed, level_id, 'readonly')
    same_scene(previous, baseline)
    request = dict(action='save', levelId=level_id)
    review = reviewer.orchestrate(session_path=session, level_id=level_id, request=request,
        baseline_run=baseline_run, baseline_kind='readonly', recovery_dir=operation / 'save-recovery')
    write(operation / 'save-claim.json', dict(requestSha256=canonical(request), reviewPath=review['reviewPath'],
          baselineRun=str(baseline_run), claimedUtc=now()))
    reply = send('save', session, level_id, queue=queue, direct=direct, review=review['reviewPath'])
    write(operation / 'save-reply.json', reply)
    verified_run(reply, level_id, 'action-after')
    return verify_save(operation, reply['run'])


def status(operation, *, offset=0, limit=128):
    operation, manifest, plan = load(operation)
    require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 256, 'PAGE_BOUNDS')
    ids, previous, blocked, prior_session = [], None, [], None
    for index, start in enumerate(range(0, len(plan['placements']), plan['batchSize'])):
        folder = operation / ('batch-%04d' % index)
        if (folder / 'commit.json').exists():
            batch = [scene_cli.normalize_placement(row, i) for i, row in enumerate(plan['placements'][start:start + plan['batchSize']])]
            previous, found = validate_commit(folder / 'commit.json', manifest['levelId'], batch, previous)
            commit_session = read(Path(read(folder / 'commit.json')['run']) / 'prepared.json')['session']
            if prior_session is not None: same_session(prior_session, commit_session)
            prior_session = commit_session
            ids.extend(found)
        elif (folder / 'claim.json').exists():
            blocked.append(dict(batch=index, claim=str(folder / 'claim.json'),
                diagnostic=read(folder / 'blocked.json') if (folder / 'blocked.json').exists() else None))
            break
        else:
            break
    complete = len(ids) == len(plan['placements']) and not blocked
    if complete and (operation / 'created.json').exists():
        require(read(operation / 'created.json')['entityIds'] == ids, 'CREATED_ID_MAP_CHANGED')
    return dict(ok=not blocked, operation=str(operation), state='blocked' if blocked else 'created' if complete else 'prepared-or-bounded-stop',
        complete=complete, running=(operation / 'running.lock').exists(), levelId=manifest['levelId'],
        planned=len(plan['placements']), committed=len(ids), offset=offset, limit=limit,
        rows=[dict(placementIndex=i, entityId=ids[i], label=plan['placements'][i].get('label'))
              for i in range(offset, min(offset + limit, len(ids)))],
        nextOffset=offset + limit if offset + limit < len(ids) else None, blocked=blocked,
        persistentSaveVerified=False, note='Pages are display projections; every commit is validated against full raw snapshots.')


def bind_save_card(run, prepared, record, level_id):
    """Bind the raw receipt to this compiled save card, not just its session.

    Legacy probes did not emit these fields. Their identity snapshots remain
    readable, but they cannot establish this stronger saved-verification result.
    """
    fields = ('receiptNonce', 'receiptDeadline', 'receiptProtocol')
    require(all(name in record for name in fields), 'SAVE_RECEIPT_CARD_BINDING_UNVERIFIED_LEGACY')
    run = Path(run)
    header = scene_cli.guarded_runtime_file(run / 'target_config.h', 'SAVE_HEADER')
    built = read(run / 'build-result.json')
    require(built.get('hashes', {}).get('target_config.h') == digest(header), 'SAVE_COMPILED_HEADER_CHANGED')
    text = header.read_text(encoding='utf-8-sig')

    def constant(name):
        definitions = re.findall(r'^\s*#define\s+' + re.escape(name) + r'\s+([^\r\n]+)', text, re.MULTILINE)
        require(len(definitions) == 1 and re.fullmatch(r'[0-9]+ULL\s*', definitions[0]) is not None,
                'SAVE_COMPILED_CONSTANT_REQUIRED:' + name)
        return int(definitions[0].strip()[:-3])

    require(prepared.get('request') == dict(action='save', levelId=level_id) and
            constant('HR_ACTION') == 2 and constant('HR_EXPECTED_LEVEL') == level_id,
            'SAVE_COMPILED_ACTION_MISMATCH')
    session = prepared['session']
    for name, key in (('HR_TARGET_PID', 'pid'), ('HR_TARGET_TID', 'tid'),
                      ('HR_TARGET_CREATION', 'processCreation'), ('HR_TARGET_THREAD_CREATION', 'threadCreation')):
        require(type(session.get(key)) is int and constant(name) == session[key], 'SAVE_COMPILED_SESSION_MISMATCH:' + key)
    nonce, deadline = constant('HR_NONCE'), constant('HR_DEADLINE')
    require(0 < nonce < 2 ** 64 and 0 < deadline < 2 ** 64, 'SAVE_COMPILED_CARD_RANGE')
    # Ordinary scene actions use receipt protocol 3, independently of whether
    # their nested entity snapshot is the legacy v1 or explicit large-scene v2.
    require(type(record['receiptNonce']) is str and record['receiptNonce'] == str(nonce) and
            type(record['receiptDeadline']) is str and record['receiptDeadline'] == str(deadline) and
            type(record['receiptProtocol']) is int and record['receiptProtocol'] == 3,
            'SAVE_RAW_RECEIPT_CARD_MISMATCH')
    return dict(verified=True, nonce=str(nonce), deadline=str(deadline), protocol=3,
                headerSha256=digest(header))


def verify_save(operation, save_run):
    """Independent saved geometry/identity checks; never edits a GIL."""
    operation, manifest, plan = load(operation)
    checked = status(operation)
    require(checked['complete'], 'ALL_BATCHES_MUST_BE_COMMITTED')
    saved_run = Path(save_run).resolve()
    scene_cli.guarded_runtime_file(saved_run / 'result.json', 'SAVE_RESULT')
    reply = read(saved_run / 'result.json')
    _, snapshot, save_prepared, record = verified_run(reply, manifest['levelId'], 'action-after')
    require(reply.get('action') == 'save' and record['action'].get('kind') == 2 and
            record['action'].get('nativeSaveStatus') == 0, 'NATIVE_SAVE_NOT_VERIFIED')
    native_card = bind_save_card(saved_run, save_prepared, record, manifest['levelId'])
    last_index = math.ceil(len(plan['placements']) / plan['batchSize']) - 1
    last_commit = read(operation / ('batch-%04d' % last_index) / 'commit.json')
    _, last_after, last_prepared, _ = verified_run(read(Path(last_commit['run']) / 'result.json'), manifest['levelId'], 'action-after')
    same_session(last_prepared['session'], save_prepared['session'])
    same_scene(last_after, snapshot)
    initial_claim = read(operation / 'batch-0000/claim.json')
    initial_review = read(initial_claim['reviewPath'])
    require(digest(initial_claim['reviewPath']) == initial_claim['reviewSha256'], 'INITIAL_REVIEW_CHANGED')
    before_path = Path(initial_review['recovery']['backup'])
    require(digest(before_path) == initial_review['recovery']['sha256'], 'INITIAL_RECOVERY_CHANGED')
    target_key = str(manifest['levelId'])
    after_info = reply['afterGils'][target_key]
    after_path = Path(after_info['snapshot'])
    require(digest(after_path) == after_info['sha256'], 'SAVED_FILE_CHANGED')
    require(all(reply['beforeGils'][key]['sha256'] == row['sha256'] for key, row in reply['afterGils'].items()
                if key != target_key), 'PROTECTED_GIL_CHANGED')
    # Import the established raw-preserving parser only for saved verification.
    spec = importlib.util.spec_from_file_location('_scale_saved_reader', HERE / 'verify-created-save.py')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    payloads = []
    for path in (before_path, after_path):
        data = path.read_bytes()
        h = reader.builder.read_header(data)
        require(h.file_type == 2 and h.version == 1 and h.file_size == 20 + h.content_length and len(data) == h.file_size + 4,
                'GIL_CONTAINER_INVALID')
        payloads.append(data[20:-4])
    before, after = payloads
    old, new = reader.entity_records(before), reader.entity_records(after)
    ids = read(operation / 'created.json')['entityIds']
    require(len(ids) == len(plan['placements']) and len(set(ids)) == len(ids), 'CREATED_IDS_INVALID')
    require(set(new) - set(old) == set(ids) and set(old) <= set(new), 'SAVED_ENTITY_SET_MISMATCH')
    require(all(new[key] == row for key, row in old.items()), 'EXISTING_SAVED_ENTITY_CHANGED')
    # Preserve every non-entity field within root5 as well.
    stripped_root = b''.join(raw for number, wire, item, raw in reader.builder.raw.spans(reader.one(after, 5))
                            if not (number == 1 and wire == 2 and reader.scalar(item, 1) in set(ids)))
    require(stripped_root == reader.one(before, 5), 'OTHER_ROOT5_BYTES_CHANGED')
    initial_dir, _, _, _ = reader.directory(before, ids[0])
    final_dir, category, node, _ = reader.directory(after, ids[0])
    target_ids = set(ids)
    registered, remaining_directory = [], []
    for number, wire, item, raw in reader.builder.raw.spans(node):
        if number == 5 and wire == 2 and reader.scalar(item, 1) == 200 and reader.scalar(item, 2) in target_ids:
            registered.append(reader.scalar(item, 2))
        else:
            remaining_directory.append(raw)
    require(len(registered) == len(ids) and set(registered) == target_ids, 'SAVED_DIRECTORY_REGISTRATION_MISMATCH')
    stripped_directory = reader.builder.replace_category(final_dir,
        reader.builder.replace(category, 3, b''.join(remaining_directory)))
    require(stripped_directory == initial_dir, 'OTHER_DIRECTORY_BYTES_CHANGED')
    for entity_id, requested in zip(ids, plan['placements']):
        item = new[entity_id][0]
        refs, direct_id = reader.fields(item, 2), reader.fields(item, 8)
        require(len(refs) <= 1 and len(direct_id) <= 1 and bool(refs or direct_id), 'AMBIGUOUS_TEMPLATE')
        if refs: require(reader.scalar(reader.one(item, 2), 1) == requested['template_id'], 'SAVED_TEMPLATE_MISMATCH')
        if direct_id: require(reader.scalar(item, 8) == requested['template_id'], 'SAVED_TEMPLATE_MISMATCH')
        actual = reader.target_geometry(item)
        # The native factory subtracts the context origin; stored GIL geometry is
        # local. Reproduce the two float32 operands and the float32 subtraction.
        expected = dict(requested)
        origin = snapshot['origin']
        expected['position'] = builder.vector(tuple(requested['position'][i] - origin[i] for i in range(3)))
        for key in ('position', 'rotation', 'scale'):
            reader.quantized_check(actual[key], expected[key], 1e-6)
    changed = sorted({field for payload in payloads for field, _, _, _ in reader.builder.raw.spans(payload)
                      if reader.fields(before, field) != reader.fields(after, field)})
    require(reader.fields(before, 10) == reader.fields(after, 10), 'NODE_GRAPHS_CHANGED')
    require(reader.fields(before, 27) == reader.fields(after, 27), 'OTHER_PLACEMENT_SECTION_CHANGED')
    result = dict(ok=True, scope='full-plan-native-and-saved-geometry', operation=str(operation), saveRun=str(saved_run),
        entityCount=len(ids), persistentSaveVerified=True, allRequestedGeometryVerified=True,
        nativeSaveCardBinding=native_card,
        originalEntityBytesPreserved=True, allDirectoryRegistrationsVerified=True,
        otherDirectoryBytesPreserved=True, nodeGraphsPreserved=True, protectedGilsPreserved=True,
        changedRootFields=changed, unclassifiedChangedRoots=[v for v in changed if v not in (5, 6)],
        allSaveDomainsVerified=False, reopenVerified=False, playerExperienceVerified=False,
        sourceHashes=dict(before=digest(before_path), after=digest(after_path), native=digest(saved_run / 'stdout.jsonl')))
    output = operation / ('saved-verification-' + result['sourceHashes']['native'][:16] + '.json')
    if output.exists(): require(read(output) == result, 'SAVE_VERIFICATION_CHANGED')
    else: write(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--operation-id', required=True)
    p.add_argument('--level-id', type=int, required=True)
    p.add_argument('--entity-budget', type=int, default=3000)
    p.add_argument('--batch-size', type=int, default=DEFAULT_BATCH)
    for name in ('run', 'status', 'verify-save'):
        p = commands.add_parser(name)
        p.add_argument('--operation', type=Path, required=True)
        if name == 'run':
            p.add_argument('--session', type=Path, required=True)
            transport = p.add_mutually_exclusive_group()
            transport.add_argument('--elevated-queue', type=Path)
            transport.add_argument('--direct-elevated', action='store_true')
            p.add_argument('--max-seconds', type=int, default=1800)
            p.add_argument('--max-batches', type=int, default=64)
            p.add_argument('--save', action='store_true')
        elif name == 'status':
            p.add_argument('--offset', type=int, default=0)
            p.add_argument('--limit', type=int, default=128)
        else:
            p.add_argument('--save-run', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare': result = prepare(args.plan, args.operation_id, args.level_id, entity_budget=args.entity_budget, batch_size=args.batch_size)
        elif args.command == 'run': result = run(args.operation, args.session, queue=args.elevated_queue, direct=args.direct_elevated, max_seconds=args.max_seconds, max_batches=args.max_batches, save=args.save)
        elif args.command == 'status': result = status(args.operation, offset=args.offset, limit=args.limit)
        else: result = verify_save(args.operation, args.save_run)
    except Exception as error:
        result = dict(ok=False, error=str(error), retryAttempted=False, persistentSaveVerified=False)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
