"""Six explicit phases for one reviewed live entity CRUD experiment.

The coordinator runs each phase as a separate command and supplies, for every
native write, its own ``native_write_review`` record for exactly that request,
current runtime baseline and recovery copy.  Nothing in this file manufactures a
review: a missing or mismatched record refuses before the phase's mutation.
Read-only identity queries may run during preflight; this tool never authors
a native write approval.

Phases, in strict order, each executed exactly once:

    start         guard -> session -> create review -> editor identity -> queue
                  pointer -> load scope -> begin probe -> native create -> one
                  inspect; records the owned scope, probe lease and target entity
    rename        inspect the same probe, rename the owned target once, inspect once
    save-renamed  native save under a review whose baseline postdates rename
    delete        inspect the renamed target, delete once, inspect once
    save-deleted  native save after confirmed delete, with a fresh exact-baseline review
    verify        strict snapshot checks; stop the owned scope only if still live

An interruption cannot be replayed.  The initial run state is written once, each
phase takes an exclusive claim file *before* its mutation, and every outcome gets
an exclusive result file.  A claim without a result, or a failed/uncertain
result, blocks every later mutating phase.  Errors before a claim refuse without
consuming the phase; errors after a claim are recorded as uncertain and are never
retried, even when they arguably had no effect.
"""
from pathlib import Path
from ctypes import wintypes
import argparse
import ctypes
import datetime
import hashlib
import json
import os
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/compatibility'))
sys.path.insert(0, str(ROOT / 'tools/game-executor'))
from version_guard import IncompatibleVersion, require_compatible  # noqa: E402
import native_profiles as profiles  # noqa: E402
import native_write_review as review_api  # noqa: E402

PHASES = ('start', 'rename', 'save-renamed', 'delete', 'save-deleted', 'verify')
MUTATING_PHASES = frozenset(PHASES[:-1])
REVIEW_PHASES = frozenset(('start', 'save-renamed', 'save-deleted'))
PROBE_PHASES = frozenset(('rename', 'save-renamed', 'delete'))
SESSION_FIELDS = review_api.SESSION_FIELDS
PROBE_NAME = 'MW_CRUD_Probe'
CRUD_ENTITY_TYPE = 1402
CRUD_INSTANCE_KIND = 0
CREATE_TEMPLATE_ID = 20001034
CREATE_POSITION = (-10.0, 0.0, -20.0)
CREATE_ROTATION = (0.0, 0.0, 0.0)
CREATE_SCALE = (1.25, 1.0, 1.0)


def runtime_root():
    return ROOT / '.runtime'


def editor_bridge_root():
    return runtime_root() / 'editor-bridge'


def runs_root():
    return editor_bridge_root() / 'runs'


def elevated_pointer():
    return editor_bridge_root() / 'current-elevated-session.json'


def gil_snapshot(result: dict, phase: str, level_key: str) -> str:
    """Snapshot path for the explicitly requested level, or refuse.

    A missing key must never fall back to another level's bytes, so this raises
    instead of comparing whatever snapshot the receipt happens to carry.
    """
    entry = (result.get(phase) or {}).get(level_key)
    if not isinstance(entry, dict) or not entry.get('snapshot'):
        raise RuntimeError('%s carries no snapshot for level %s; refusing to compare another level'
                           % (phase, level_key))
    return entry['snapshot']


class CrudRefusal(RuntimeError):
    """A pre-claim refusal: nothing was mutated and the phase is not consumed."""


def require(condition, reason):
    if not condition:
        raise CrudRefusal(reason)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_utc(text):
    require(isinstance(text, str) and text.strip(), 'missing UTC timestamp')
    value = datetime.datetime.fromisoformat(text.replace('Z', '+00:00'))
    require(value.tzinfo is not None, 'timestamp without timezone: ' + text)
    return value.astimezone(datetime.timezone.utc)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json_new(path, value):
    """Exclusive create.  Run state is never overwritten or reset."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    except FileExistsError:
        raise CrudRefusal('refusing to overwrite existing run state: ' + str(path))
    return path


def canonical_uuid(value, reason):
    require(isinstance(value, str), reason)
    try:
        identifier = str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise CrudRefusal(reason)
    require(identifier == value, reason)
    return identifier


def child_environment(level_id):
    environment = os.environ.copy()
    environment['MILIASTRA_LEVEL'] = str(level_id)
    return environment


def create_request(level_id):
    return {'action': 'create', 'levelId': level_id, 'templateId': CREATE_TEMPLATE_ID,
            'position': list(CREATE_POSITION), 'rotation': list(CREATE_ROTATION),
            'scale': list(CREATE_SCALE)}


def save_request(level_id):
    return {'action': 'save', 'levelId': level_id}


# --------------------------------------------------------------------------- #
# Read-only preflight: compatibility, session identity, editor identity, queue
# --------------------------------------------------------------------------- #

def guard_mutation():
    """Disk-only refusal before a write path; never widened to 'game' or 'all'."""
    for component in ('native-scene', 'editor'):
        require_compatible(component)


def load_session(session_path):
    """Re-read the explicit session file and re-query its actual identity.

    Uses ``native_profiles.validate_session``: the file alone is never trusted and
    the project-local current-session pointer is never substituted.
    """
    path = Path(session_path)
    require(path.is_file(), 'explicit --session file is missing: ' + str(path))
    session = read_json(path)
    observed = profiles.validate_session(session)
    return path.resolve(), observed


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# .NET UTC ticks count from 0001-01-01 while FILETIME counts from 1601-01-01.
DOTNET_EPOCH_OFFSET_TICKS = 504911232000000000
MAX_IMAGE_CHARS = 32768


def last_win32_error():
    """Best-effort text for the last Win32 error; never masks the refusal itself."""
    try:
        code = ctypes.get_last_error()
    except Exception:
        code = 0
    try:
        return str(ctypes.WinError(code))
    except Exception:
        return 'win32 error %d' % code


def query_editor(pid):
    """Read-only identity of the explicitly named editor process.

    ``OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`` can query an elevated
    editor under an ordinary token, where ``Get-Process`` leaves ``Path`` empty.
    The handle is opened for query only: nothing is launched,
    signalled or attached, and a refusal is never answered by elevating or by
    substituting the owned scope.
    """
    require(type(pid) is int and 0 < pid < 2 ** 32,
            'editor pid must be a positive uint32, not %r' % (pid,))
    try:
        kernel32, _ = profiles.windows_api()
    except Exception as error:
        raise CrudRefusal('editor identity query is unavailable: %s: %s'
                          % (type(error).__name__, error))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        raise CrudRefusal('OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) failed for pid %d: %s'
                          % (pid, last_win32_error()))
    creation = 0
    image = None
    try:
        image = ctypes.create_unicode_buffer(MAX_IMAGE_CHARS)
        length = wintypes.DWORD(MAX_IMAGE_CHARS)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            raise CrudRefusal('QueryFullProcessImageNameW failed for pid %d: %s'
                              % (pid, last_win32_error()))
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise CrudRefusal('GetProcessTimes failed for pid %d: %s' % (pid, last_win32_error()))
        creation = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)
    require(creation > 0, 'editor process creation FILETIME is zero for pid %d' % pid)
    path = image.value if image is not None else ''
    require(isinstance(path, str) and path.strip(), 'editor process image path missing for pid %d' % pid)
    process_name = Path(path).stem
    require(process_name.strip(), 'editor process image name missing for pid %d' % pid)
    return {'pid': pid, 'startUtcTicks': creation + DOTNET_EPOCH_OFFSET_TICKS,
            'expectedExe': path, 'processName': process_name}


def read_queue_pointer():
    """Resolve the elevated helper's current pointer, bound under the project."""
    pointer = elevated_pointer()
    require(pointer.is_file(), 'elevated session pointer is missing: ' + str(pointer))
    state = read_json(pointer)
    queue = state.get('queueDir')
    require(isinstance(queue, str) and queue.strip(), 'elevated session pointer has no queueDir')
    resolved = Path(queue).resolve()
    root = editor_bridge_root().resolve()
    require(resolved.is_relative_to(root), 'queue directory is outside ' + str(root))
    require(resolved.is_dir(), 'queue directory does not exist: ' + str(resolved))
    return {'pointerPath': str(pointer.resolve()), 'pointerSha256': sha256_file(pointer),
            'queueDir': str(resolved)}


def recheck_queue(state):
    """Never implicitly follow a pointer or queue that changed after start."""
    pointer_path = Path(state['queuePointerPath'])
    require(pointer_path.is_file(), 'elevated session pointer disappeared since start')
    require(str(pointer_path.resolve()) == state['queuePointerPath'], 'elevated session pointer path changed')
    require(sha256_file(pointer_path) == state['queuePointerSha256'],
            'elevated session pointer changed since start')
    current = read_queue_pointer()
    require(current['pointerPath'] == state['queuePointerPath'], 'elevated session pointer path changed')
    require(current['pointerSha256'] == state['queuePointerSha256'],
            'elevated session pointer changed since start')
    require(current['queueDir'] == state['queueDir'], 'elevated session queue changed since start')
    return state['queueDir']


def list_scopes():
    root = runs_root()
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir() if entry.is_dir())


def load_scope(run_dir):
    path = run_dir / 'scope.json'
    require(path.is_file(), 'owned editor scope was never recorded; a scope is never recreated')
    scope = read_json(path)
    for key in ('scope', 'scopeDir', 'settingsPath', 'settingsSha256', 'pid', 'startUtcTicks',
                'expectedExe', 'expiresUtc'):
        require(scope.get(key) not in (None, ''), 'incomplete owned scope binding: ' + key)
    return scope


def check_scope(state, scope, editor_identity, *, require_live=True):
    """Compare actual pid/ticks/path against both the state and the owned scope."""
    identity = state['editorIdentity']
    require(identity == editor_identity, 'editor process identity changed since start')
    require(scope['pid'] == state['editorPid'], 'owned scope belongs to another process')
    require(int(scope['startUtcTicks']) == identity['startUtcTicks'],
            'owned scope start ticks do not match the editor process')
    require(str(scope['expectedExe']).casefold() == str(identity['expectedExe']).casefold(),
            'owned scope image path does not match the editor process')
    scope_dir = Path(scope['scopeDir']).resolve()
    require(scope_dir.is_relative_to(runs_root().resolve()), 'owned scope is outside the project runs root')
    require(canonical_uuid(scope['scope'], 'owned scope id is not canonical') == scope['scope'],
            'owned scope id is not canonical')
    require(scope_dir == runs_root().resolve() / scope['scope'], 'owned scope directory does not match its id')
    settings = Path(scope['settingsPath'])
    require(settings.resolve() == scope_dir / 'bridge-settings.json', 'owned scope settings path changed')
    require(settings.is_file(), 'owned scope settings disappeared')
    require(sha256_file(settings) == scope['settingsSha256'], 'owned scope settings changed since binding')
    if require_live:
        require(not (scope_dir / 'lease-closed.json').exists(), 'owned scope lease is closed')
        require(datetime.datetime.now(datetime.timezone.utc) < parse_utc(scope['expiresUtc']),
                'owned scope lease expired')
    return scope


def load_probe(run_dir):
    path = run_dir / 'probe.json'
    require(path.is_file(), 'probe binding is missing; the shared probe is never begun again')
    probe = read_json(path)
    for key in ('probeId', 'expiresUtc', 'baselineIds', 'target'):
        require(probe.get(key) not in (None, '', []), 'incomplete probe binding: ' + key)
    return probe


def check_probe_lease(probe):
    require(datetime.datetime.now(datetime.timezone.utc) < parse_utc(probe['expiresUtc']),
            'probe lease expired; it is never extended and never begun again')


# --------------------------------------------------------------------------- #
# Child processes
# --------------------------------------------------------------------------- #

def run_child(argv, *, label, run_dir, environment, timeout):
    try:
        process = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=timeout, env=environment)
    except subprocess.TimeoutExpired as error:
        for stream, content in [('stdout', error.stdout), ('stderr', error.stderr)]:
            text = content.decode('utf-8', errors='replace') if isinstance(content, bytes) else (content or '')
            (Path(run_dir) / (label + '.' + stream + '.txt')).write_text(text, encoding='utf-8')
        raise
    (Path(run_dir) / (label + '.stdout.txt')).write_text(process.stdout or '', encoding='utf-8')
    (Path(run_dir) / (label + '.stderr.txt')).write_text(process.stderr or '', encoding='utf-8')
    return process


def parse_reply(process, label, *, success_key):
    require(process.returncode == 0, '%s exited %d; no automatic retry' % (label, process.returncode))
    try:
        reply = json.loads(process.stdout)
    except (ValueError, TypeError):
        raise CrudRefusal('%s did not return one JSON object' % label)
    require(isinstance(reply, dict), '%s reply is not an object' % label)
    require(reply.get(success_key) is True,
            '%s did not report literal %s=true' % (label, success_key))
    return reply


def scene_call(ctx, label, argv, timeout=150):
    require(sha256_file(ctx['reviewPath']) == ctx['reviewSha256'],
            'review changed after phase preflight')
    # Re-verified immediately before dispatch: the owned queue recorded at start is
    # still the elevated session's queue.  A pointer that moved is refused, never
    # followed to whichever queue is current now.
    current_queue = recheck_queue(ctx['state'])
    require(current_queue == ctx['queueDir'],
            'elevated queue changed since start (%s is no longer %s); refusing to follow '
            'a migrated current-elevated-session pointer' % (current_queue, ctx['queueDir']))
    require('--elevated-queue' not in argv, 'scene arguments already contain an elevated queue')
    process = run_child([sys.executable, 'tools/game-executor/scene_cli.py', *argv,
                         '--elevated-queue', str(ctx['queueDir'])], label=label,
                        run_dir=ctx['runDir'], environment=ctx['environment'], timeout=timeout)
    reply = parse_reply(process, label, success_key='ok')
    require(reply.get('levelId') == ctx['levelId'],
            '%s reported levelId %r instead of %d' % (label, reply.get('levelId'), ctx['levelId']))
    return reply


def scene_create(ctx):
    argv = ['create', '--session', str(ctx['sessionPath']), '--level-id', str(ctx['levelId']),
            '--review', str(ctx['reviewPath']), '--template-id', str(CREATE_TEMPLATE_ID),
            '--position', *[str(value) for value in CREATE_POSITION],
            '--rotation', *[str(value) for value in CREATE_ROTATION],
            '--scale', *[str(value) for value in CREATE_SCALE]]
    reply = scene_call(ctx, 'create', argv)
    entity_id = reply.get('entityId')
    require(type(entity_id) is int and 0 < entity_id < 2 ** 32,
            'create receipt carries no positive entityId')
    return reply


def scene_save(ctx, label):
    argv = ['save', '--session', str(ctx['sessionPath']), '--level-id', str(ctx['levelId']),
            '--review', str(ctx['reviewPath'])]
    return scene_call(ctx, label, argv)


def editor_call(ctx, label, op, timeout=150):
    argv = [sys.executable, 'tools/editor-bridge/elevated-request.py', '--queue-dir', str(ctx['queueDir']),
            'call', '--run-id', ctx['scope'], '--op', op]
    process = run_child(argv, label=label, run_dir=ctx['runDir'], environment=ctx['environment'],
                        timeout=timeout)
    return parse_reply(process, label, success_key='ok')


def editor_load(ctx):
    argv = [sys.executable, 'tools/editor-bridge/elevated-request.py', '--queue-dir', str(ctx['queueDir']),
            'load', '--target-pid', str(ctx['editorPid'])]
    process = run_child(argv, label='load-editor', run_dir=ctx['runDir'],
                        environment=ctx['environment'], timeout=60)
    return parse_reply(process, 'load-editor', success_key='accepted')


# --------------------------------------------------------------------------- #
# Probe observations and the bound target entity
# --------------------------------------------------------------------------- #

def require_probe_reply(reply, probe):
    require(reply.get('probeId') == probe['probeId'], 'reply came from another probe; never begin a second')
    if 'expiresUtc' in reply:
        require(reply.get('expiresUtc') == probe['expiresUtc'], 'probe lease was extended or changed')
    check_probe_lease(probe)


def require_target_entity(observation, probe, expected_names, expected_entity_id=None):
    """Compare the bound identity, template, prefab cache, kind, name and lease."""
    require_probe_reply(observation, probe)
    target = probe['target']
    entity = observation.get('entity')
    require(isinstance(entity, dict), 'probe observation carries no entity')
    identity = entity.get('identity')
    require(isinstance(identity, dict), 'probe entity carries no identity')
    require(identity == target['identity'], 'probe target identity changed')
    require(set(identity) == {'Category0', 'Category1', 'Category2', 'Category3', 'Id'} and
            all(type(v) is int and 0 <= v < 2**32 for v in identity.values()),
            'probe target identity is malformed')
    require(identity['Id'] == target['entityId'] and target['entityId'] > 0,
            'editor target id does not match the native create receipt')
    require(target['identity'].get('Id') not in probe['baselineIds'],
            'the bound target was already part of the probe baseline')
    # templateId is the native template/config identity. prefabId is a separate
    # editor association cache, which may legitimately be zero but must be stable.
    require(type(entity.get('templateId')) is int and type(target.get('templateId')) is int
            and entity['templateId'] == target['templateId'] == CREATE_TEMPLATE_ID,
            'probe target template id missing or changed')
    require(type(entity.get('prefabId')) is int and type(target.get('prefabId')) is int
            and 0 <= entity['prefabId'] < 2**32
            and entity['prefabId'] == target['prefabId'],
            'probe target prefab cache id missing or changed')
    require(entity.get('nativeEntityType') == target['nativeEntityType'] == CRUD_ENTITY_TYPE,
            'probe target native entity type changed')
    require(entity.get('nativeInstanceKind') == target['nativeInstanceKind'] == CRUD_INSTANCE_KIND,
            'probe target native instance kind changed')
    require(observation.get('originalName') == target['originalName'], 'probe original name changed')
    require(entity.get('name') in expected_names,
            'probe target name %r is not one of %r' % (entity.get('name'), expected_names))
    if expected_entity_id is not None:
        require(target['entityId'] == expected_entity_id, 'bound entity id changed')
    return target


# --------------------------------------------------------------------------- #
# Phase claims, results and ordering
# --------------------------------------------------------------------------- #

def claim_payload(ctx, phase, previous, request=None):
    return {
        'phase': phase,
        'previousPhase': previous['phase'] if previous else None,
        'previousResultSha256': previous['sha256'] if previous else None,
        'stateSha256': sha256_file(ctx['runDir'] / 'state.json'),
        'sessionPath': str(ctx['sessionPath']),
        'sessionSha256': sha256_file(ctx['sessionPath']),
        'levelId': ctx['levelId'],
        'editorPid': ctx['editorPid'],
        'scope': ctx.get('scope'),
        'probeId': (ctx.get('probe') or {}).get('probeId'),
        'reviewId': ctx.get('reviewId'),
        'reviewPath': str(ctx['reviewPath']) if ctx.get('reviewPath') else None,
        'reviewSha256': sha256_file(ctx['reviewPath']) if ctx.get('reviewPath') else None,
        'request': request,
        'requestSha256': review_api.canonical_hash(request) if request else None,
    }


def begin_phase(run_dir, phase, payload):
    claim = dict(payload, schemaVersion=1, kind='live-crud-phase-claim-v1',
                 claimedUtc=now_iso(), attempt=1, mutationConsumed=True)
    write_json_new(Path(run_dir) / 'phases' / (phase + '.claim.json'), claim)
    return claim


def finish_phase(run_dir, phase, claim, ok, uncertain, evidence):
    claim_path = Path(run_dir) / 'phases' / (phase + '.claim.json')
    result = {'schemaVersion': 1, 'kind': 'live-crud-phase-result-v1', 'phase': phase,
              'ok': bool(ok) and not uncertain, 'outcomeUncertain': bool(uncertain),
              'claimedUtc': claim['claimedUtc'], 'finishedUtc': now_iso(),
              'claimSha256': sha256_file(claim_path),
              'previousResultSha256': claim.get('previousResultSha256'),
              'evidence': evidence}
    if not result['ok']:
        result['error'] = evidence.get('error') or 'phase failed'
    result['bindings'] = {name: sha256_file(Path(run_dir) / name)
                          for name in ('state.json', 'scope.json', 'probe.json', 'probe-start.json')
                          if (Path(run_dir) / name).is_file()}
    result_path = Path(run_dir) / 'phases' / (phase + '.result.json')
    write_json_new(result_path, result)
    write_json_new(Path(str(result_path) + '.sha256.json'), {'sha256': sha256_file(result_path)})
    return result


def run_claimed(ctx, phase, claim, work):
    """Any error after the claim is uncertain and is never retried."""
    try:
        evidence, ok = work(), True
    except Exception as error:
        evidence, ok = {'error': '%s: %s' % (type(error).__name__, error)}, False
    return finish_phase(ctx['runDir'], phase, claim, ok, not ok, evidence)


def require_unused(run_dir, phase):
    phases = Path(run_dir) / 'phases'
    require(not (phases / (phase + '.claim.json')).exists(),
            'phase %s was already claimed; run state cannot be reset or replayed' % phase)
    require(not (phases / (phase + '.result.json')).exists(),
            'phase %s already has a result; duplicate phases are refused' % phase)


def require_previous(run_dir, phase):
    """Validate all completed predecessors and their original input bindings."""
    previous = None
    for name in PHASES[:PHASES.index(phase)]:
        claim_path = Path(run_dir) / 'phases' / (name + '.claim.json')
        result_path = Path(run_dir) / 'phases' / (name + '.result.json')
        require(result_path.is_file(), 'previous phase %s has no result; a claim without a result blocks later phases' % name)
        require(claim_path.is_file(), 'previous phase %s has no claim file' % name)
        result, claim = read_json(result_path), read_json(claim_path)
        require(result.get('phase') == claim.get('phase') == name, 'previous phase record is malformed')
        require(result.get('ok') is True and result.get('outcomeUncertain') is False,
                'previous phase %s did not complete cleanly; later phases are blocked' % name)
        require(result.get('claimSha256') == sha256_file(claim_path),
                'previous phase claim does not match its result; run state was altered')
        digest = sha256_file(result_path)
        require(read_json(Path(str(result_path) + '.sha256.json')).get('sha256') == digest,
                'phase result changed since completion')
        previous_hash = previous['sha256'] if previous else None
        require(claim.get('previousResultSha256') == previous_hash and result.get('previousResultSha256') == previous_hash,
                'phase history hash chain changed')
        require(claim.get('stateSha256') == sha256_file(Path(run_dir) / 'state.json'), 'initial run state changed')
        bindings = result.get('bindings') or {}
        require({'state.json', 'scope.json', 'probe.json'} <= set(bindings),
                'completed phase lacks owned scope/probe bindings')
        for artifact, expected in bindings.items():
            require(artifact in ('state.json', 'scope.json', 'probe.json', 'probe-start.json'),
                    'unrecognized checkpoint binding')
            require(sha256_file(Path(run_dir) / artifact) == expected,
                    'bound %s changed since start' % artifact)
        previous = {'phase': name, 'result': result, 'path': str(result_path), 'sha256': digest}
    return previous


def resume_common(args, run_dir, session_path, *, require_live_scope=True):
    """Validate the checkpoint, session binding, queue, editor identity and scope."""
    state_path = Path(run_dir) / 'state.json'
    require(state_path.is_file(), 'run state is missing; start must run first')
    state = read_json(state_path)
    require(state.get('kind') == 'live-crud-run-state-v1' and state.get('schemaVersion') == 1,
            'unsupported run state schema')
    canonical_uuid(state.get('runId'), 'run state has no canonical run id')
    require(Path(state['sessionPath']) == Path(session_path),
            'the explicit --session differs from the session bound at start')
    require(sha256_file(session_path) == state['sessionSha256'], 'session file changed since start')
    _, session = load_session(session_path)
    observed_fields = {name: session[name] for name in SESSION_FIELDS}
    require(observed_fields == state['sessionFields'], 'session identity changed since start')
    require(state['editorPid'] == args.editor_pid, '--editor-pid differs from the editor bound at start')
    require(state['levelId'] == args.level_id, '--level-id differs from the level bound at start')
    recheck_queue(state)
    editor_identity = query_editor(state['editorPid'])
    scope = load_scope(run_dir)
    check_scope(state, scope, editor_identity, require_live=require_live_scope)
    ctx = {'runDir': Path(run_dir), 'phase': None, 'levelId': state['levelId'],
           'editorPid': state['editorPid'], 'editorIdentity': editor_identity,
           'sessionPath': Path(session_path), 'queueDir': state['queueDir'],
           'scope': scope['scope'], 'state': state,
           'environment': child_environment(state['levelId']),
           'reviewPath': Path(args.review).resolve() if args.review is not None else None}
    return ctx, state, scope


def prepare_resume(args, run_dir, session_path, phase):
    require(Path(run_dir).is_dir(), 'run directory does not exist: ' + str(run_dir))
    require_unused(run_dir, phase)
    previous = require_previous(run_dir, phase)
    guard_mutation()
    ctx, state, scope = resume_common(args, run_dir, session_path,
                                      require_live_scope=phase not in ('save-deleted', 'verify'))
    ctx['phase'] = phase
    probe = None
    if phase in PROBE_PHASES:
        probe = load_probe(run_dir)
        check_probe_lease(probe)
        ctx['probe'] = probe
    return {'ctx': ctx, 'state': state, 'scope': scope, 'previous': previous, 'probe': probe}


# --------------------------------------------------------------------------- #
# Reviewed-baseline timing
# --------------------------------------------------------------------------- #

def require_review_after(previous, reviewed, target_id, *, must_contain):
    """A save review must postdate the phase it approves, baseline included.

    delete changes the entity set, so a review built before delete can never
    approve the post-delete save: both the review and its executed runtime
    baseline must be newer than the preceding phase, and the baseline entity set
    must already contain (rename) or no longer contain (delete) the owned target.
    """
    finished = parse_utc(previous['result']['finishedUtc'])
    reviewed_at = parse_utc(reviewed['review']['reviewedAtUtc'])
    require(reviewed_at > finished,
            'review was written before phase %s finished; a future baseline cannot approve it'
            % previous['phase'])
    baseline_run = Path(reviewed['baselineRun'])
    exit_path = baseline_run / 'exit.json'
    require(exit_path.is_file(), 'reviewed baseline has no execution evidence')
    executed = read_json(exit_path)
    require(executed.get('executed') is True and executed.get('exitCode') == 0,
            'reviewed baseline did not execute cleanly')
    started_at = parse_utc(executed.get('startedUtc'))
    executed_at = parse_utc(executed.get('finishedUtc'))
    require(started_at > finished and started_at <= executed_at <= reviewed_at,
            'review baseline must begin after the preceding phase and finish before review')
    require(executed_at > finished,
            'reviewed baseline predates phase %s; it cannot approve this save' % previous['phase'])
    ids = [entry['id'] for entry in reviewed['baseline']['entities']]
    if must_contain:
        require(target_id in ids, 'reviewed baseline does not contain the owned target entity')
    else:
        require(target_id not in ids, 'reviewed baseline still contains the owned target entity')



def require_unused_review(reviewed):
    # Availability check only: scene_cli retains the sole atomic native claim.
    claim = ROOT / '.runtime/game-executor/native-write-review-claims' / (reviewed['reviewId'] + '.json')
    require(not claim.exists(), 'native write review was already claimed; no replay')


def bind_gil(result, phase, level_id, label):
    path = gil_snapshot(result, phase, str(level_id))
    require(Path(path).is_file(), '%s snapshot for level %s is missing' % (phase, level_id))
    return {'snapshot': str(path), 'sha256': sha256_file(path), 'label': label}


# --------------------------------------------------------------------------- #
# start
# --------------------------------------------------------------------------- #

def phase_start(args, run_dir, session_path):
    require(not Path(run_dir).exists(),
            'start refuses an existing run directory; run state is never reset')
    guard_mutation()
    session_path, session = load_session(session_path)
    review_path = Path(args.review).resolve()
    request = create_request(args.level_id)
    reviewed = review_api.validate_review(review_path, session, args.level_id, request)
    require_unused_review(reviewed)
    editor_identity = query_editor(args.editor_pid)
    queue = read_queue_pointer()
    pre_existing = list_scopes()
    Path(run_dir).mkdir(parents=True, exist_ok=False)
    state = {
        'schemaVersion': 1, 'kind': 'live-crud-run-state-v1', 'runId': str(uuid.uuid4()),
        'createdUtc': now_iso(), 'phase': 'start',
        'editorPid': args.editor_pid, 'editorIdentity': editor_identity,
        'levelId': args.level_id,
        'sessionPath': str(session_path), 'sessionSha256': sha256_file(session_path),
        'sessionFields': {name: session[name] for name in SESSION_FIELDS},
        'queuePointerPath': queue['pointerPath'], 'queuePointerSha256': queue['pointerSha256'],
        'queueDir': queue['queueDir'], 'preExistingScopes': pre_existing,
        'reviewPath': str(review_path), 'reviewSha256': sha256_file(review_path),
        'reviewId': reviewed['reviewId'], 'request': request,
        'requestSha256': review_api.canonical_hash(request),
    }
    write_json_new(Path(run_dir) / 'state.json', state)
    ctx = {'runDir': Path(run_dir), 'phase': 'start', 'levelId': args.level_id,
           'editorPid': args.editor_pid, 'editorIdentity': editor_identity,
           'sessionPath': session_path, 'queueDir': queue['queueDir'],
           'environment': child_environment(args.level_id), 'reviewPath': review_path,
           'state': state, 'scope': None, 'reviewId': reviewed['reviewId'],
           'reviewSha256': reviewed.get('reviewSha256') or sha256_file(review_path)}
    claim = begin_phase(run_dir, 'start', claim_payload(ctx, 'start', None, request))
    return run_claimed(ctx, 'start', claim, lambda: start_work(ctx, state))


def reject_unusable_editor_transport(catalog):
    """Reject unavailable/self-connected transport; this is not a handshake proof."""
    socket = catalog.get('transportSocket') if isinstance(catalog, dict) else None
    require(isinstance(socket, dict), 'editor transport observation missing')
    require(socket.get('observed') is True and socket.get('connectedFlag') is True
            and socket.get('loopbackEndpoints') is True,
            'editor transport is unavailable or is not the expected loopback transport')
    local, remote = socket.get('localPort'), socket.get('remotePort')
    require(type(local) is int and type(remote) is int
            and 1 <= local <= 65535 and 1 <= remote <= 65535,
            'editor transport endpoints are unavailable')
    require(socket.get('selfConnection') is False and local != remote,
            'editor transport is self-connected; refusing before native creation')


def start_work(ctx, state):
    run_dir = ctx['runDir']
    loaded = editor_load(ctx)
    scope_id = canonical_uuid(loaded.get('runId'), 'editor load did not return a canonical runId')
    require(scope_id not in state['preExistingScopes'],
            'editor load returned a scope that already existed; never adopt another run')
    scope_dir = (runs_root() / scope_id).resolve()
    require(scope_dir.is_relative_to(runs_root().resolve()) and scope_dir.is_dir(),
            'editor load scope directory is missing or outside the project runs root')
    settings = scope_dir / 'bridge-settings.json'
    require(settings.is_file(), 'owned editor scope has no bridge-settings.json')
    settings_value = read_json(settings)
    identity = state['editorIdentity']
    require(int(settings_value.get('pid', 0)) == ctx['editorPid'],
            'scope pid is not the requested editor pid')
    require(int(settings_value.get('startUtcTicks', 0)) == identity['startUtcTicks'],
            'scope start ticks do not match the queried editor process')
    require(str(settings_value.get('expectedExe', '')).casefold() == identity['expectedExe'].casefold(),
            'scope image path does not match the queried editor process')
    require(isinstance(settings_value.get('nonce'), str) and settings_value['nonce'],
            'owned editor scope has no nonce')
    require(isinstance(settings_value.get('pipeName'), str) and settings_value['pipeName'],
            'owned editor scope has no pipe name')
    require(isinstance(settings_value.get('expiresUtc'), str) and settings_value['expiresUtc'],
            'owned editor scope has no lease deadline')
    binding = {'scope': scope_id, 'scopeDir': str(scope_dir), 'settingsPath': str(settings.resolve()),
               'settingsSha256': sha256_file(settings), 'pid': ctx['editorPid'],
               'startUtcTicks': int(settings_value['startUtcTicks']),
               'expectedExe': str(settings_value['expectedExe']), 'nonce': settings_value['nonce'],
               'pipeName': settings_value['pipeName'], 'expiresUtc': settings_value['expiresUtc'],
               'boundUtc': now_iso()}
    require(parse_utc(binding['expiresUtc']) > datetime.datetime.now(datetime.timezone.utc),
            'owned scope lease already expired at binding time')
    # Recorded immediately, before the next editor call, so an interruption between
    # the load and the probe is reviewable instead of silently orphaned.
    write_json_new(run_dir / 'scope.json', binding)
    ctx['scope'] = scope_id

    catalog = editor_call(ctx, 'transport-before-create', 'catalog')
    reject_unusable_editor_transport(catalog)

    begin = editor_call(ctx, 'begin-entity-crud-probe', 'begin-entity-crud-probe')
    probe_id = begin.get('probeId')
    require(isinstance(probe_id, str) and probe_id, 'probe begin returned no probeId')
    expires = begin.get('expiresUtc')
    require(isinstance(expires, str) and expires, 'probe begin returned no expiresUtc')
    require(begin.get('levelIdentityVerified') is False,
            'the probe must not claim a verified level identity')
    baseline = begin.get('baseline')
    require(isinstance(baseline, list) and baseline, 'probe begin returned an empty baseline')
    baseline_ids = []
    for entry in baseline:
        entry_identity = entry.get('identity') if isinstance(entry, dict) else None
        require(isinstance(entry_identity, dict) and type(entry_identity.get('Id')) is int
                and entry_identity['Id'] > 0, 'probe baseline entry has no positive entity id')
        baseline_ids.append(entry_identity['Id'])
    require(len(set(baseline_ids)) == len(baseline_ids), 'probe baseline has duplicate entity ids')
    span = (parse_utc(expires) - parse_utc(begin.get('observedUtc'))).total_seconds()
    require(0 < span <= 180, 'probe lease is not the fixed 180-second window')
    probe_start = {'probeId': probe_id, 'expiresUtc': expires, 'baselineIds': baseline_ids,
                   'baselineCount': len(baseline_ids), 'beganUtc': begin['observedUtc']}
    write_json_new(run_dir / 'probe-start.json', probe_start)
    check_probe_lease(probe_start)
    check_scope(state, binding, query_editor(ctx['editorPid']))
    created = scene_create(ctx)
    entity_id = created['entityId']
    require(entity_id not in baseline_ids, 'the created entity id was already in the probe baseline')
    before_gil = bind_gil(created, 'beforeGils', ctx['levelId'], 'before-create')

    observation = editor_call(ctx, 'inspect-created', 'inspect-entity-crud-probe')
    probe_value = {'probeId': probe_id, 'expiresUtc': expires, 'baselineIds': baseline_ids,
                   'baselineCount': len(baseline_ids), 'beganUtc': begin.get('observedUtc')}
    target = {
        'identity': (observation.get('entity') or {}).get('identity'),
        'templateId': (observation.get('entity') or {}).get('templateId'),
        'prefabId': (observation.get('entity') or {}).get('prefabId'),
        'nativeEntityType': (observation.get('entity') or {}).get('nativeEntityType'),
        'nativeInstanceKind': (observation.get('entity') or {}).get('nativeInstanceKind'),
        'originalName': observation.get('originalName'),
        'entityId': entity_id,
    }
    probe_value['target'] = target
    require_target_entity(observation, probe_value, (target['originalName'],), entity_id)
    require(isinstance(target['originalName'], str) and target['originalName'].strip()
            and target['originalName'] != PROBE_NAME,
            'the probe registered an unusable original name')
    require(observation.get('frontendMaterialized') is True,
            'the new entity has no materialized editor resource; failing closed instead of '
            'opening the scene folder automatically')
    write_json_new(run_dir / 'probe.json', probe_value)
    return {'editorRunId': scope_id, 'probeId': probe_id, 'probeExpiresUtc': expires,
            'entityId': entity_id, 'target': target, 'beforeGil': before_gil,
            'frontendMaterialized': True, 'baselineCount': len(baseline_ids)}


# --------------------------------------------------------------------------- #
# rename / delete (owned-target safety, no native review)
# --------------------------------------------------------------------------- #

def phase_rename(args, run_dir, session_path):
    prepared = prepare_resume(args, run_dir, session_path, 'rename')
    ctx, probe, previous = prepared['ctx'], prepared['probe'], prepared['previous']
    target = probe['target']
    observed = editor_call(ctx, 'inspect-before-rename', 'inspect-entity-crud-probe')
    require_target_entity(observed, probe, (target['originalName'],), target['entityId'])
    require(observed['entity']['name'] == target['originalName'],
            'the owned target is not in its original-name state')
    claim = begin_phase(run_dir, 'rename', claim_payload(ctx, 'rename', previous))
    return run_claimed(ctx, 'rename', claim, lambda: rename_work(ctx, probe))


def rename_work(ctx, probe):
    target = probe['target']
    reply = editor_call(ctx, 'rename-entity-crud-probe', 'rename-entity-crud-probe')
    require_probe_reply(reply, probe)
    require(reply.get('identity') == target['identity'], 'rename reply identity changed')
    require(reply.get('requestedName') == PROBE_NAME, 'rename did not request the probe name')
    # Exactly one observation.  No loops, retries or sleeps for a mutation result.
    observed = editor_call(ctx, 'inspect-renamed', 'inspect-entity-crud-probe')
    require_target_entity(observed, probe, (PROBE_NAME,), target['entityId'])
    return {'requestedName': PROBE_NAME, 'observedName': observed['entity']['name'],
            'originalName': observed['originalName'], 'entityId': target['entityId'],
            'invokedUtc': reply.get('invokedUtc')}


def phase_delete(args, run_dir, session_path):
    prepared = prepare_resume(args, run_dir, session_path, 'delete')
    ctx, probe, previous = prepared['ctx'], prepared['probe'], prepared['previous']
    target = probe['target']
    observed = editor_call(ctx, 'inspect-before-delete', 'inspect-entity-crud-probe')
    require_target_entity(observed, probe, (PROBE_NAME,), target['entityId'])
    claim = begin_phase(run_dir, 'delete', claim_payload(ctx, 'delete', previous))
    return run_claimed(ctx, 'delete', claim, lambda: delete_work(ctx, probe))


def delete_work(ctx, probe):
    target = probe['target']
    reply = editor_call(ctx, 'delete-entity-crud-probe', 'delete-entity-crud-probe')
    require_probe_reply(reply, probe)
    require(reply.get('identity') == target['identity'], 'delete reply identity changed')
    # Exactly one observation of the spent probe state.
    observed = editor_call(ctx, 'inspect-deleted', 'inspect-entity-crud-probe')
    require_probe_reply(observed, probe)
    require(observed.get('targetAbsentFromAuxiliaryRegistry') is True,
            'the owned target is still present in the auxiliary registry after delete')
    require(observed.get('newEntityCount') == 0,
            'the auxiliary registry still holds non-baseline entities after delete')
    return {'entityId': target['entityId'], 'targetAbsentFromAuxiliaryRegistry': True,
            'newEntityCount': 0, 'nativeResult': reply.get('nativeResult'),
            'invokedUtc': reply.get('invokedUtc')}


# --------------------------------------------------------------------------- #
# save-renamed / save-deleted (coordinator review required)
# --------------------------------------------------------------------------- #

def phase_save_renamed(args, run_dir, session_path):
    prepared = prepare_resume(args, run_dir, session_path, 'save-renamed')
    ctx, probe, previous = prepared['ctx'], prepared['probe'], prepared['previous']
    request = save_request(ctx['levelId'])
    reviewed = review_api.validate_review(ctx['reviewPath'], prepared['state']['sessionFields'],
                                          ctx['levelId'], request)
    require_unused_review(reviewed)
    ctx.update(reviewId=reviewed['reviewId'], reviewSha256=reviewed.get('reviewSha256') or sha256_file(ctx['reviewPath']))
    require_review_after(previous, reviewed, probe['target']['entityId'], must_contain=True)
    target = probe['target']
    observed = editor_call(ctx, 'inspect-before-save-renamed', 'inspect-entity-crud-probe')
    require_target_entity(observed, probe, (PROBE_NAME,), target['entityId'])
    claim = begin_phase(run_dir, 'save-renamed', claim_payload(ctx, 'save-renamed', previous, request))
    return run_claimed(ctx, 'save-renamed', claim, lambda: save_work(ctx, probe, request))


def phase_save_deleted(args, run_dir, session_path):
    # The entity lease still gates rename/delete. Once delete completed with an
    # absence observation, final persistence uses a NEW native review and the
    # original complete baseline ID set, without reviving a spent editor probe.
    prepared = prepare_resume(args, run_dir, session_path, 'save-deleted')
    ctx, previous = prepared['ctx'], prepared['previous']
    probe = load_probe(run_dir)
    ctx['probe'] = probe
    target_id = probe['target']['entityId']
    deleted = previous['result'].get('evidence') or {}
    require(previous['phase'] == 'delete' and deleted.get('entityId') == target_id
            and deleted.get('targetAbsentFromAuxiliaryRegistry') is True
            and deleted.get('newEntityCount') == 0,
            'post-delete persistence requires a successful bound deletion and absence observation')
    request = save_request(ctx['levelId'])
    reviewed = review_api.validate_review(ctx['reviewPath'], prepared['state']['sessionFields'],
                                          ctx['levelId'], request)
    require_unused_review(reviewed)
    ctx.update(reviewId=reviewed['reviewId'], reviewSha256=reviewed.get('reviewSha256') or sha256_file(ctx['reviewPath']))
    require_review_after(previous, reviewed, target_id, must_contain=False)
    current_ids = [entry['id'] for entry in reviewed['baseline']['entities']]
    require(len(current_ids) == len(set(current_ids)) and sorted(current_ids) == sorted(probe['baselineIds']),
            'post-delete native baseline differs from the complete original entity set')
    claim = begin_phase(run_dir, 'save-deleted', claim_payload(ctx, 'save-deleted', previous, request))
    return run_claimed(ctx, 'save-deleted', claim, lambda: save_work(ctx, probe, request))


def save_work(ctx, probe, request):
    reply = scene_save(ctx, ctx['phase'])
    gil = bind_gil(reply, 'afterGils', ctx['levelId'], ctx['phase'])
    return {'request': request, 'reviewId': ctx['reviewId'], 'entityId': probe['target']['entityId'],
            'nativeStatus': reply.get('nativeStatus'), 'gil': gil,
            'gilChanged': reply.get('gilChanged')}


# --------------------------------------------------------------------------- #
# verify (offline only, then the owned scope is the only thing stopped)
# --------------------------------------------------------------------------- #

def phase_verify(args, run_dir, session_path):
    prepared = prepare_resume(args, run_dir, session_path, 'verify')
    ctx, previous = prepared['ctx'], prepared['previous']
    probe = load_probe(run_dir)
    # Immutable snapshot validation does not mutate the expired entity probe.
    ctx['probe'] = probe
    claim = begin_phase(run_dir, 'verify', claim_payload(ctx, 'verify', previous))
    return run_claimed(ctx, 'verify', claim, lambda: verify_work(ctx, probe))


def phase_gil(run_dir, phase, key):
    result = read_json(Path(run_dir) / 'phases' / (phase + '.result.json'))
    require(result.get('ok') is True and result.get('outcomeUncertain') is False,
            'phase %s did not complete cleanly' % phase)
    evidence = result.get('evidence') or {}
    binding = evidence.get(key)
    require(isinstance(binding, dict) and binding.get('snapshot'), 'phase %s recorded no %s' % (phase, key))
    path = Path(binding['snapshot'])
    require(path.is_file(), 'recorded snapshot is missing: ' + str(path))
    require(sha256_file(path) == binding['sha256'], 'recorded snapshot changed: ' + str(path))
    return path


def verify_work(ctx, probe):
    run_dir = ctx['runDir']
    target = probe['target']
    before = phase_gil(run_dir, 'start', 'beforeGil')
    renamed = phase_gil(run_dir, 'save-renamed', 'gil')
    deleted = phase_gil(run_dir, 'save-deleted', 'gil')
    verify_dir = runtime_root() / 'game-executor' / 'crud-verify' / ctx['state']['runId']
    verify_dir.mkdir(parents=True, exist_ok=True)
    created_out = verify_dir / 'verify-created-renamed.json'
    crud_out = verify_dir / 'verify-crud-saves.json'
    require(not created_out.exists() and not crud_out.exists(),
            'offline verification output already exists; refusing to overwrite evidence')
    created_reply = run_child([sys.executable, 'tools/game-executor/verify-created-save.py',
                               str(before), str(renamed), '--entity-id', str(target['entityId']),
                               '--template-id', str(CREATE_TEMPLATE_ID), '--name', PROBE_NAME,
                               '--position', *[str(v) for v in CREATE_POSITION],
                               '--rotation', *[str(v) for v in CREATE_ROTATION],
                               '--scale', *[str(v) for v in CREATE_SCALE],
                               '--out', str(created_out)],
                              label='verify-created-renamed', run_dir=run_dir,
                              environment=ctx['environment'], timeout=120)
    parse_reply(created_reply, 'verify-created-renamed', success_key='ok')
    crud_reply = run_child([sys.executable, 'tools/editor-bridge/verify-entity-crud-saves.py',
                            str(before), str(renamed), str(deleted),
                            '--entity-id', str(target['entityId']), '--name', PROBE_NAME,
                            '--out', str(crud_out)],
                           label='verify-crud-saves', run_dir=run_dir,
                           environment=ctx['environment'], timeout=120)
    parse_reply(crud_reply, 'verify-crud-saves', success_key='ok')
    stop = {'dispatched': False, 'runId': ctx['scope'],
            'fallback': 'owned lease expires naturally; no other scope or process is touched'}
    try:
        check_scope(ctx['state'], load_scope(run_dir), query_editor(ctx['editorPid']))
        reply = editor_call(ctx, 'stop-owned-editor-scope', 'stop')
        stop.update(dispatched=True, stopped=reply.get('stopped'), status=reply.get('status'),
                    cleanupComplete=reply.get('cleanupComplete', False))
    except Exception as error:
        stop['error'] = '%s: %s' % (type(error).__name__, error)
    return {'beforeGil': str(before), 'renamedGil': str(renamed), 'deletedGil': str(deleted),
            'createdRenamedVerification': str(created_out), 'crudVerification': str(crud_out),
            'scopeStop': stop}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

PHASE_HANDLERS = {
    'rename': phase_rename, 'save-renamed': phase_save_renamed, 'delete': phase_delete,
    'save-deleted': phase_save_deleted, 'verify': phase_verify,
}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--phase', choices=PHASES, required=True,
                        help='Exactly one phase, executed as its own command')
    parser.add_argument('--run-dir', type=Path, required=True,
                        help='Run directory under .runtime; start creates it and every later phase resumes it')
    parser.add_argument('--run', action='store_true', help='Execute the explicitly requested phase')
    parser.add_argument('--session', type=Path, required=True,
                        help='Explicit freshly discovered native session; never substituted')
    parser.add_argument('--editor-pid', type=int, required=True,
                        help='PID of the explicitly authorized editor process')
    parser.add_argument('--level-id', type=int, required=True,
                        help='Explicit level this run may create in and save; never guessed')
    parser.add_argument('--review', type=Path, default=None,
                        help='Coordinator native-write review; required only for start and the two save phases')
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.run:
        parser.error('--run is required; every phase changes or verifies the experimental scene')
    if args.editor_pid <= 0:
        parser.error('--editor-pid must be a positive PID of the authorized editor process')
    if not 0 < args.level_id < 2 ** 32:
        parser.error('--level-id must be a nonzero uint32; the target level is never guessed')
    if args.phase in REVIEW_PHASES:
        if args.review is None:
            parser.error('--review is required for phase %s; a native write needs a coordinator review'
                         % args.phase)
    elif args.review is not None:
        parser.error('--review is only accepted for %s; phase %s takes no native review'
                     % (sorted(REVIEW_PHASES), args.phase))
    run_dir = Path(args.run_dir).resolve()
    root = runtime_root().resolve()
    if not run_dir.is_relative_to(root):
        parser.error('--run-dir must stay under ' + str(root))
    session_path = Path(args.session).resolve()
    prior_claim = (run_dir / 'phases' / (args.phase + '.claim.json')).exists()

    try:
        if args.phase == 'start':
            result = phase_start(args, run_dir, session_path)
        else:
            result = PHASE_HANDLERS[args.phase](args, run_dir, session_path)
    except IncompatibleVersion as error:
        print(json.dumps({'ok': False, 'phase': args.phase, 'refused': True, 'outcomeUncertain': False,
                          'runDir': str(run_dir), 'guard': error.report}, ensure_ascii=True))
        return 2
    except Exception as error:
        spent = (run_dir / 'phases' / (args.phase + '.claim.json')).exists()
        attempted = spent and not prior_claim
        unknown = attempted
        if prior_claim:
            try:
                old_result = read_json(run_dir / 'phases' / (args.phase + '.result.json'))
                unknown = old_result.get('outcomeUncertain') is not False or old_result.get('ok') is not True
            except (OSError, ValueError, TypeError):
                unknown = True
        print(json.dumps({'ok': False, 'phase': args.phase, 'refused': not attempted, 'outcomeUncertain': unknown,
                          'error': '%s: %s' % (type(error).__name__, error),
                          'runDir': str(run_dir)}, ensure_ascii=True))
        return 2
    print(json.dumps({'ok': result.get('ok', False), 'phase': args.phase, 'runDir': str(run_dir),
                      'result': result}, ensure_ascii=True))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())




