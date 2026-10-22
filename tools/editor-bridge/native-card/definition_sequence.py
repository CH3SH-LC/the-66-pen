"""Serial native item/currency registration using the existing fixed pipelines.

The caller owns the fresh-baseline callback, target selection and source review.
No process is queried on import or plan validation. ``register`` is an explicit
live operation. It never saves, edits a GIL, assigns requested native IDs, writes
item properties, or substitutes registration evidence for gameplay acceptance.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = ROOT / '.runtime'
OUTPUT = RUNTIME / 'native-definition-sequences'
TA = ROOT / 'tools/game-executor/template-authoring'
LEVEL = 1073741843
# Explicit level whitelist (2026-10-22, lead-authorized): the sequence was hard-coded to
# the 1843 reference level. life W3-B must register the same four definitions on the
# live 1844 level. Only these two levels may ever run this chain; anything else is
# refused before any request/review/dispatch. Non-legacy levels must pass an
# ``authorization_source`` string, recorded in operation.json.
AUTHORIZED_LEVELS = {
    1073741843: 'legacy-m2-1843-reference',
    1073741844: 'lead-authorized-20261022-life-w3b',
}
# tools whose `sources` digest must be coordinator-reviewed, mapped to builder/acceptor
TOOLS = {'item': ('template-item', 'prepare_item.py', 'accept_item.py'),
         'currency': ('template-currency', 'prepare_currency.py', 'accept_currency.py')}


class SequenceError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise SequenceError(code)


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'DUPLICATE_JSON_KEY:' + key)
        result[key] = value
    return result


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def write(path, value):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def project_path(value, *, directory=False, boundary=RUNTIME):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    absolute = Path(os.path.abspath(path))
    # Follow neither junctions nor symlinks in evidence/queue locations.
    require(absolute.resolve() == absolute, 'PATH_REDIRECTION_FORBIDDEN')
    require(absolute.is_relative_to(boundary.resolve()) and absolute != boundary.resolve(),
            'PATH_OUTSIDE_BOUNDARY')
    for part in (absolute, *absolute.parents):
        if part.exists():
            require(not part.is_symlink() and not getattr(part, 'is_junction', lambda: False)(),
                    'PATH_REDIRECTION_FORBIDDEN')
        if part == boundary.resolve():
            break
    require(absolute.is_dir() if directory else absolute.is_file(), 'INPUT_PATH_MISSING')
    return absolute


def validate_plan(document, *, expected_level: int | None = None):
    require(type(document) is dict and set(document) == {'schemaVersion', 'levelId', 'definitions'},
            'DEFINITION_PLAN_FIELDS')
    require(type(document['schemaVersion']) is int and document['schemaVersion'] == 1,
            'DEFINITION_PLAN_VERSION')
    level = document['levelId']
    require(type(level) is int and level in AUTHORIZED_LEVELS,
            'ONLY_AUTHORIZED_LEVEL_1843_OR_1844')
    if expected_level is not None:
        require(type(expected_level) is int and expected_level in AUTHORIZED_LEVELS and level == expected_level,
                'DEFINITION_PLAN_LEVEL_MISMATCH')
    definitions = document['definitions']
    require(type(definitions) is list and 1 <= len(definitions) <= 64, 'DEFINITION_PLAN_COUNT')
    keys, names = set(), set()
    for row in definitions:
        require(type(row) is dict and set(row) == {'key', 'kind', 'name'}, 'DEFINITION_ROW_FIELDS')
        require(type(row['key']) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,95}', row['key']),
                'DEFINITION_KEY')
        require(type(row['kind']) is str and row['kind'] in TOOLS, 'DEFINITION_KIND')
        require(type(row['name']) is str and '\0' not in row['name'], 'DEFINITION_NAME')
        try:
            encoded = row['name'].encode('utf-8', errors='strict')
        except UnicodeError:
            raise SequenceError('DEFINITION_NAME_ENCODING') from None
        require(1 <= len(encoded) <= 128, 'DEFINITION_NAME_LENGTH')
        require(row['key'] not in keys and row['name'] not in names, 'DUPLICATE_DEFINITION')
        keys.add(row['key']); names.add(row['name'])
    return json.loads(canonical(document))


class Commands:
    """Only this module constructs commands; no arbitrary command input exists."""
    def call(self, script, args, stage, *, timeout=900):
        script = Path(script).resolve()
        allowed = {TA / 'request.py', TA / 'prepare_item.py', TA / 'prepare_currency.py',
                   TA / 'accept_item.py', TA / 'accept_currency.py', HERE / 'issue_template_review.py',
                   HERE / 'dispatch.py'}
        require(script in allowed, 'NON_FIXED_COMMAND')
        argv = [sys.executable, '-B', str(script), *map(str, args)]
        write(stage / 'command.json', {'argv': argv, 'startedUtc': now(), 'timeoutSeconds': timeout})
        try:
            with (stage / 'stdout.json').open('xb') as stdout, (stage / 'stderr.txt').open('xb') as stderr:
                result = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                        timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            write(stage / 'exit.json', {'exitCode': result.returncode, 'finishedUtc': now()})
            require((stage / 'stdout.json').stat().st_size <= 16 * 1024 * 1024, 'COMMAND_OUTPUT_LIMIT')
            data = read(stage / 'stdout.json')
            require(result.returncode == 0 and type(data) is dict and data.get('ok') is True,
                    'FIXED_COMMAND_REFUSED:' + stage.name)
            return data
        except BaseException as error:
            # Especially after dispatch, a timeout/parse error never licenses replay.
            write(stage / 'failure.json', {'errorType': type(error).__name__, 'error': str(error),
                                          'finishedUtc': now(), 'replayForbidden': True})
            raise


def _proof_matches(outer, native, row, request_hash, source, card_run):
    kind = row['kind']; tool = TOOLS[kind][0]
    require(type(outer) is dict and outer.get('ok') is True and outer.get('tool') == tool,
            'DISPATCH_RESULT_TYPE')
    require(outer.get('levelId') == LEVEL and outer.get('catalogRegisteredVerified') is True and
            outer.get('cleanupVerified') is True and outer.get('safeToRelease') is True and
            outer.get('outcomeUncertain') is False and outer.get('nativeStarted') is True,
            'DISPATCH_RESULT_UNCERTAIN')
    require(outer.get('rawSha256') == sha(source / 'stdout.jsonl'), 'DISPATCH_RAW_HASH_MISMATCH')
    require(Path(outer.get('sourceRun', '')).resolve() == source and
            Path(outer.get('run', '')).resolve() == card_run, 'DISPATCH_RUN_MISMATCH')
    require(type(native) is dict and native.get('ok') is True and
            native.get('action') == 'create-' + kind and native.get('levelId') == LEVEL and
            native.get('catalogRegisteredVerified') is True and native.get('requestSha256') == request_hash and
            Path(native.get('run', '')).resolve() == source, 'NATIVE_ACCEPTANCE_MISMATCH')
    resource_id = native.get('createdId')
    require(type(resource_id) is int and 0 < resource_id < 2**32 and
            type(outer.get('createdId')) is int and outer['createdId'] == resource_id,
            'CATALOG_DELTA_ID_MISMATCH')
    # The independent acceptor verifies the request, native ABI and before/after
    # catalog bytes. Its legacy outcomeUncertain is retained as an attempted-write
    # marker; only the outer complete-cleanup result resolves that uncertainty.
    return resource_id


def register(document, *, operation_id: str, session_file, target_gil, backup,
             queue, reviewed_source_sets: dict, fresh_baseline: Callable[[str], dict],
             level_id: int | None = None, authorization_source: str | None = None,
             _commands=None):
    """Register a complete typed list, stopping on the first failed/unknown step.

    ``fresh_baseline(key)`` must perform a new complete native readonly capture
    and return ``{'ok': True, 'run': path}``; no invented entity/catalog rows.
    ``reviewed_source_sets`` maps each used tool to the coordinator-reviewed SHA
    from ``issue_template_review.py sources``. This function never approves an
    arbitrary current source set automatically. A consumed operation cannot run
    twice; partial/unknown results need inspection, never an automatic restart.

    ``level_id`` selects the target level from the explicit AUTHORIZED_LEVELS
    whitelist (default: legacy 1843). For any non-legacy level, a non-empty
    ``authorization_source`` string is required and recorded in operation.json.
    """
    plan = validate_plan(document, expected_level=level_id)
    level = plan['levelId']
    require(level in AUTHORIZED_LEVELS, 'LEVEL_NOT_AUTHORIZED')
    if level != LEVEL:
        require(type(authorization_source) is str and len(authorization_source.strip()) >= 8,
                'LEVEL_AUTHORIZATION_SOURCE_REQUIRED')
    require(type(operation_id) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', operation_id),
            'OPERATION_ID')
    require(callable(fresh_baseline), 'FRESH_BASELINE_CALLBACK_REQUIRED')
    session = project_path(session_file)
    recovery = project_path(backup)
    transport = project_path(queue, directory=True, boundary=RUNTIME / 'editor-bridge')
    # The existing formal review validates the precise BeyondLocal path/level.
    require(Path(target_gil).is_absolute(), 'ABSOLUTE_FORMAL_TARGET_REQUIRED')
    target = Path(target_gil).resolve(strict=True)
    require(target.is_file(), 'TARGET_GIL_REQUIRED')
    needed = {TOOLS[row['kind']][0] for row in plan['definitions']}
    require(type(reviewed_source_sets) is dict and set(reviewed_source_sets) == needed and
            all(type(v) is str and re.fullmatch('[0-9a-f]{64}', v) for v in reviewed_source_sets.values()),
            'REVIEWED_SOURCE_SETS_REQUIRED')
    require(sha(target) == sha(recovery), 'BACKUP_BYTES_CHANGED')
    fingerprints = {str(p): sha(p) for p in (session, recovery, target)}
    # Freeze this adapter and all directly called command sources as well. Native
    # transitive sources are independently frozen by each original review/card.
    scripts = {Path(__file__), TA / 'request.py', HERE / 'issue_template_review.py', HERE / 'dispatch.py'}
    for row in plan['definitions']:
        scripts.update(TA / name for name in TOOLS[row['kind']][1:])
    fingerprints.update({str(p): sha(p) for p in scripts})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    project_path(OUTPUT, directory=True)
    # Keep fixed tool paths below Windows MAX_PATH even for long semantic keys.
    # The exact caller ID remains in operation.json; a hash collision fails mkdir.
    operation = OUTPUT / hashlib.sha256(operation_id.encode('utf-8')).hexdigest()[:32]
    operation.mkdir()  # Exclusive and permanent, even when preparation later fails.
    write(operation / 'operation.json', {'schemaVersion': 1, 'kind': 'native-definition-sequence-v1',
          'operationId': operation_id, 'startedUtc': now(), 'plan': plan,
          'planSha256': hashlib.sha256(canonical(plan)).hexdigest(), 'inputs': fingerprints,
          'reviewedSourceSets': reviewed_source_sets, 'queue': str(transport),
          'levelId': level, 'levelAuthorization': {
              'source': authorization_source, 'whitelistReason': AUTHORIZED_LEVELS[level]}})
    commands = _commands or Commands()
    completed, baseline_paths, seen_ids = [], set(), set()
    dispatch_started = False
    current_key = None

    def unchanged():
        require(all(sha(path) == digest for path, digest in fingerprints.items()),
                'SEQUENCE_INPUT_OR_SOURCE_CHANGED')

    def call(step, script, args, directory):
        unchanged()
        stage = directory / step
        stage.mkdir()
        return commands.call(script, args, stage)

    try:
        for index, row in enumerate(plan['definitions']):
            current_key = row['key']
            dispatch_started = False
            directory = operation / f'{index:03d}'
            directory.mkdir()
            unchanged()
            started = now()
            write(directory / 'baseline-intent.json', {'key': current_key, 'startedUtc': started})
            observed = fresh_baseline(current_key)
            write(directory / 'baseline-return.json', observed)
            require(type(observed) is dict and observed.get('ok') is True and observed.get('run'),
                    'FRESH_BASELINE_FAILED')
            baseline = project_path(observed['run'], directory=True)
            require(baseline not in baseline_paths, 'BASELINE_REUSED_ACROSS_DEFINITIONS')
            baseline_paths.add(baseline)
            ended = datetime.fromisoformat(read(baseline / 'exit.json')['finishedUtc'].replace('Z', '+00:00'))
            require(ended.tzinfo is not None and datetime.fromisoformat(started) <= ended <= datetime.now(timezone.utc),
                    'BASELINE_NOT_CAPTURED_FOR_THIS_DEFINITION')
            tool, builder, acceptor = TOOLS[row['kind']]
            request = call('01-request', TA / 'request.py', ['create-' + row['kind'],
                '--run-id', baseline.name, '--level-id', str(level), '--session', session,
                '--baseline-run', baseline, '--request-id', str(uuid.uuid4()), '--name', row['name']], directory)
            request_path = project_path(request['requestPath'])
            request_hash = sha(request_path)
            require(request.get('requestSha256') == request_hash, 'REQUEST_HASH_MISMATCH')
            review = call('02-review', HERE / 'issue_template_review.py', ['issue', '--tool', tool,
                '--request', request_path, '--baseline', baseline, '--target-gil', target,
                '--backup', recovery, '--out', directory / 'review.json',
                '--reviewed-source-set-sha256', reviewed_source_sets[tool]], directory)
            built = call('03-build', TA / builder, ['--review', review['reviewPath']], directory)
            require(built.get('launchable') is True and built.get('compileOnly') is False and
                    built.get('action') == 'create-' + row['kind'], 'WRONG_TEMPLATE_BUILDER')
            source = project_path(built['run'], directory=True)
            card = call('04-card', HERE / 'dispatch.py', ['prepare', '--tool', tool, '--source-run', source], directory)
            card_run = project_path(card['run'], directory=True)
            write(directory / 'dispatch-intent.json', {'tool': tool, 'run': str(card_run),
                  'sourceRun': str(source), 'requestSha256': request_hash, 'startedUtc': now(),
                  'replayForbidden': True})
            dispatch_started = True
            outer = call('05-dispatch', HERE / 'dispatch.py', [tool, '--run', card_run,
                         '--elevated-queue', transport], directory)
            # Recompute from original source bytes through the original acceptor,
            # independently of the transport's cached nativeAcceptance object.
            native = call('06-accept', TA / acceptor, ['--run', source], directory)
            allocated = _proof_matches(outer, native, row, request_hash, source, card_run)
            require(allocated not in seen_ids, 'DUPLICATE_ALLOCATED_ID')
            seen_ids.add(allocated)
            unchanged()
            record = dict(row, configId=allocated, sourceRun=str(source), cardRun=str(card_run),
                          requestSha256=request_hash, nativeAcceptance=native,
                          rawSha256=sha(source / 'stdout.jsonl'), catalogRegisteredVerified=True,
                          nameVerified=False, propertiesVerified=False, persistentSaveVerified=False,
                          gameplayVerified=False)
            write(directory / 'registered.json', record)
            completed.append(record)
            dispatch_started = False
        result = {'ok': True, 'state': 'catalog-registered-only', 'operationId': operation_id,
                  'run': str(operation), 'levelId': level, 'finishedUtc': now(),
                  'semanticIds': {row['key']: row['configId'] for row in completed},
                  'registeredDefinitions': completed, 'outcomeUncertain': False,
                  'propertiesVerified': False, 'persistentSaveVerified': False, 'gameplayVerified': False}
    except BaseException as error:
        result = {'ok': False, 'state': 'stopped', 'operationId': operation_id, 'run': str(operation),
                  'levelId': level, 'finishedUtc': now(), 'stoppedAtKey': current_key,
                  'errorType': type(error).__name__, 'error': str(error),
                  'registeredDefinitions': completed, 'outcomeUncertain': dispatch_started,
                  'replayForbidden': True, 'propertiesVerified': False,
                  'persistentSaveVerified': False, 'gameplayVerified': False}
        write(operation / 'result.json', result)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        return result
    write(operation / 'result.json', result)
    return result
