"""Explicit-session inspect/create/save with a single-request runtime-evidence gate.

--session supplies a freshly revalidated discovered session. --level-id is explicit;
MILIASTRA_LEVEL remains supported with no fallback. Mutations require --review, an
internal coordinator record binding a complete native baseline and recoverable save.
Missing review refuses before UAC. No operation auto-retries uncertain outcomes.

Three elevated transports, mutually exclusive per action:

* default -- standard UAC. This process builds the profile unprivileged and a fixed
  launcher starts the fixed probe through -Verb RunAs.
* --direct-elevated -- this process already holds an elevated token. The same fixed
  wrapper is executed in place, with no RunAs. The token is queried from Windows,
  never inferred from the flag or an environment variable.
* --elevated-queue -- nothing is compiled or claimed locally. A closed, data-only
  request is handed to the resident elevated runner through the fixed
  tools/editor-bridge/elevated-request.py client and its reply is reported verbatim.
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
import stat
import subprocess
import struct
import sys
import time

# --- isolated bootstrap -------------------------------------------------------------
# The runner invokes this file as `python -I -S scene_cli.py ...`. -I implies -P, so
# Python does not prepend the script directory and the sibling modules below would not
# resolve at all; without -S an unrelated same-named module elsewhere on the path could
# be imported instead. Insert exactly this file's own resolved directory, once, at the
# front: the fixed project modules always win, and neither CWD nor a user module is
# ever imported in their place.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from build_scene_profile import (ROOT, MAX_BATCH, NATIVE, is_template_id,  # noqa: E402
                                 build_profile, digest,
                                 ps_literal, vector, windows_api, write_json, resolve_level)
import build_readonly_profile as readonly  # noqa: E402
import native_profiles as profile_api  # noqa: E402
import native_write_review as native_write_review  # noqa: E402
from decode_context_snapshot import read_probe  # noqa: E402
decode_snapshot = readonly.load_decoder().decode_snapshot

RUNTIME = ROOT / '.runtime'
CURRENT_SESSION = RUNTIME / 'game-executor/current-native-session.json'
ELEVATED_REQUEST = ROOT / 'tools/editor-bridge/elevated-request.py'
SEND_TIMEOUT = 300.0
MAX_PLAN_BYTES = 256 * 1024
SESSION_FIELDS = ('schemaVersion', 'pid', 'tid', 'window', 'windowClass', 'processCreation',
                  'threadCreation', 'image')
# The queue transports data, never an executable. These key names would let a caller try
# to smuggle a command, a local plan path or a hash to compare against; the runner owns
# execution, so the client refuses them outright instead of forwarding them.
FORBIDDEN_PAYLOAD_KEYS = frozenset((
    'run', 'exe', 'executable', 'script', 'wrapper', 'hash', 'hashes', 'sha256', 'plan',
    'planpath', 'plan_path', 'command', 'cmd', 'argv', 'args', 'cwd', 'shell', 'powershell',
    'bat', 'cmdline', 'timeout', 'pid', 'tid'))


class SceneFailure(RuntimeError):
    def __init__(self, reason, *, uncertain=False, run=None):
        super().__init__(reason)
        self.uncertain, self.run = uncertain, str(run) if run else None


def json_file(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def is_admin_token() -> bool:
    """Whether this process's *actual* Windows token is elevated.

    A --direct-elevated flag is an assertion by the caller, not evidence, and an
    environment variable is weaker still. The fixed wrapper re-checks NOT_ELEVATED,
    but that happens after a compile and a review claim, so the effective token of
    the current process is queried directly here. TokenElevation reflects the token
    in use, including UAC-filtered admin tokens that are not actually elevated.
    """
    import ctypes as C
    from ctypes import wintypes as W

    advapi32 = C.WinDLL('advapi32', use_last_error=True)
    kernel32 = C.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentProcess.restype = W.HANDLE
    kernel32.CloseHandle.argtypes = [W.HANDLE]
    kernel32.CloseHandle.restype = W.BOOL
    advapi32.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi32.OpenProcessToken.restype = W.BOOL
    advapi32.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD,
                                             C.POINTER(W.DWORD)]
    advapi32.GetTokenInformation.restype = W.BOOL

    class TOKEN_ELEVATION(C.Structure):
        _fields_ = [('TokenIsElevated', W.DWORD)]

    token = W.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, C.byref(token)):
        raise OSError('OpenProcessToken failed: %d' % C.get_last_error())
    try:
        elevation, size = TOKEN_ELEVATION(), W.DWORD()
        if not advapi32.GetTokenInformation(token, 20, C.byref(elevation),
                                            C.sizeof(elevation), C.byref(size)):
            raise OSError('GetTokenInformation(TokenElevation) failed: %d' % C.get_last_error())
        return elevation.TokenIsElevated != 0
    finally:
        kernel32.CloseHandle(token)


def guarded_runtime_file(raw, label) -> Path:
    """Resolve an existing plain file inside this project's .runtime tree.

    This is the sender's own scope check, not a replacement for the helper's: the
    resident runner re-rejects reparse points and re-derives identity from the
    original builders. Check the lexically visible path before normalising it,
    because Windows abspath folds away trailing spaces/dots that name an alias.
    """
    lexical = Path(raw)
    if getattr(os.path, 'isreserved', lambda _: False)(lexical):
        raise ValueError(label + '_UNSAFE_PATH_COMPONENT')
    for part in lexical.parts:
        if part in (lexical.anchor, '.', '..'):
            continue
        if part.rstrip(' .') != part or ':' in part or part.split('.', 1)[0].upper() in {
                'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
                    '%s%d' % (p, n) for p in ('COM', 'LPT') for n in range(1, 10)}:
            raise ValueError(label + '_UNSAFE_PATH_COMPONENT')
    target = Path(os.path.abspath(lexical))
    if not target.is_relative_to(Path(os.path.abspath(RUNTIME))):
        raise ValueError(label + '_OUTSIDE_PROJECT_RUNTIME')
    current = Path(target.anchor)
    for index, part in enumerate(target.parts[1:]):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            raise ValueError(label + '_MISSING') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(label + '_REPARSE_POINT')
        if index == len(target.parts[1:]) - 1 and not stat.S_ISREG(info.st_mode):
            raise ValueError(label + '_NOT_A_FILE')
    return target


def strict_vector3(value, *, positive=False, label='vector') -> list[float]:
    """Three finite float32 components, rejecting booleans and non-numeric types.

    vector() would happily read True as 1.0; a JSON batch placement must not be
    able to pass a bool where a coordinate is expected.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(label + ' must be exactly three numeric components')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ValueError(label + ' components must be numbers, not booleans or strings')
    # The production queue client validates Python types before JSON encoding.
    # Emit JSON arrays now; relying on json.dumps to convert tuples is too late.
    return list(vector(value, positive=positive))


def normalize_placement(spec, index: int) -> dict:
    """One closed batch placement: exact keys, permitted template, finite float3."""
    if not isinstance(spec, dict):
        raise ValueError('Batch placement %d must be an object' % index)
    # Existing project plans carry an inert label. It is intentionally omitted
    # from the closed helper request and from the reviewed native request hash.
    if 'label' in spec and (not isinstance(spec['label'], str) or len(spec['label']) > 256):
        raise ValueError('Batch placement %d label must be a bounded string' % index)
    unexpected = sorted(set(spec) - {'template_id', 'position', 'rotation', 'scale', 'label'})
    if unexpected:
        raise ValueError('Batch placement %d has unexpected fields: %s' % (index, ', '.join(unexpected)))
    missing = sorted({'template_id', 'position', 'scale'} - set(spec))
    if missing:
        raise ValueError('Batch placement %d is missing fields: %s' % (index, ', '.join(missing)))
    template_id = spec['template_id']
    if isinstance(template_id, bool) or type(template_id) is not int or not is_template_id(template_id):
        raise ValueError('Batch placement %d template_id is not a uint32' % index)
    return dict(template_id=template_id,
                position=strict_vector3(spec['position'], label='placement %d position' % index),
                rotation=strict_vector3(spec.get('rotation', (0, 0, 0)),
                                        label='placement %d rotation' % index),
                scale=strict_vector3(spec['scale'], positive=True,
                                     label='placement %d scale' % index))


def normalize_placements(raw) -> list:
    """1..MAX_BATCH placements, normalised, before anything can be built or queued."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_BATCH:
        raise ValueError('Batch placements must be a list of 1..%d entries' % MAX_BATCH)
    return [normalize_placement(spec, index) for index, spec in enumerate(raw)]


def read_plan_spec(path) -> dict:
    """Bounded read of a plan file. A plan is input data, never a queued command."""
    source = Path(path)
    size = source.stat().st_size
    if size > MAX_PLAN_BYTES:
        raise ValueError('Batch plan exceeds the %d-byte bound' % MAX_PLAN_BYTES)
    data = source.read_bytes()
    if len(data) > MAX_PLAN_BYTES:
        raise ValueError('Batch plan exceeds the %d-byte bound' % MAX_PLAN_BYTES)
    try:
        spec = json.loads(data.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError('Batch plan is not valid UTF-8 JSON: %s' % error)
    if not isinstance(spec, dict) or not isinstance(spec.get('placements'), list):
        raise ValueError('Batch plan must be an object with a "placements" list')
    return spec


def assert_queue_data_only(value, where='request') -> None:
    """Refuse anything in a queued request that is not plain JSON data."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or key.casefold() in FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError('Elevated queue accepts data only; rejected key %r in %s'
                                 % (key, where))
            assert_queue_data_only(item, where + '.' + key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_queue_data_only(item, '%s[%d]' % (where, index))
    elif isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Elevated queue rejects non-finite numbers in ' + where)
    else:
        raise ValueError('Elevated queue rejects %s in %s' % (type(value).__name__, where))


def queue_request(args) -> dict:
    """The closed, normalised request handed to the resident elevated runner.

    Normalisation finishes here, before any build_profile, review claim, GIL
    snapshot or UAC step -- those only exist on the local transports, and the
    queue sender performs none of them. No running game is queried: the session
    and review records are checked as project .runtime files and the helper
    revalidates them against the original builders.
    """
    level_id = resolve_level(args.level_id)
    session_path = guarded_runtime_file(args.session if args.session is not None else CURRENT_SESSION,
                                        'SESSION')
    request = dict(kind='native-scene', action=args.action,
                   sessionPath=str(session_path), levelId=level_id)
    option = getattr(args, 'reopen_prerequisites', False)
    if type(option) is not bool or (option and args.action != 'inspect'):
        raise ValueError('REOPEN_PREREQUISITES_INSPECT_TRUE_ONLY')
    if option: request['reopenPrerequisites'] = True
    large = getattr(args, 'large_scene', False)
    if type(large) is not bool or (large and args.action != 'inspect'):
        raise ValueError('LARGE_SCENE_INSPECT_TRUE_ONLY')
    if large: request['largeScene'] = True
    if args.action in ('create', 'creature-create'):
        template_id = args.template_id
        # 2026-10-09: no whitelist. Both actions accept any uint32 templateId.
        if isinstance(template_id, bool) or type(template_id) is not int or not is_template_id(template_id):
            raise ValueError('Template id is not a uint32')
        request.update(templateId=template_id,
                       position=strict_vector3(args.position, label='position'),
                       rotation=strict_vector3(args.rotation, label='rotation'),
                       scale=strict_vector3(args.scale, positive=True, label='scale'))
    elif args.action == 'create-batch':
        request['placements'] = normalize_placements(read_plan_spec(args.plan)['placements'])
    if args.action != 'inspect':
        if args.review is None:
            raise ValueError('NATIVE_WRITE_REVIEW_REQUIRED: a coordinator evidence record is '
                             'required for a queued write')
        request['reviewPath'] = str(guarded_runtime_file(args.review, 'REVIEW'))
    assert_queue_data_only(request)
    return request


def load_native_sender():
    """Load the fixed bridge client and take its native-scene sender.

    Imported by path from the project root so the resident runner's contract is the
    only thing used here; the module is never copied, patched or given a local plan.
    """
    if not ELEVATED_REQUEST.is_file():
        raise SceneFailure('Fixed elevated queue client is missing: ' + str(ELEVATED_REQUEST))
    spec = importlib.util.spec_from_file_location('_fixed_elevated_request', ELEVATED_REQUEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sender = getattr(module, 'send_native_scene', None)
    if not callable(sender):
        raise SceneFailure('Fixed elevated queue client has no send_native_scene; '
                           'refusing to fall back to a local build')
    return sender


def send_queued_scene(request: dict, action: str, queue_dir: Path) -> dict:
    """Send once and report the helper's own reply. Never resubmits."""
    sender = load_native_sender()
    try:
        reply = sender(request, queue_dir=queue_dir, timeout=SEND_TIMEOUT)
    except (Exception, SystemExit) as error:
        # The request may already be queued or in flight; the runner owns the sticky
        # inflight lock, so this is reported as uncertain and never re-sent.
        raise SceneFailure('Elevated queue send failed: %s' % error, uncertain=True)
    if not isinstance(reply, dict):
        raise SceneFailure('Elevated helper reply was not a JSON object', uncertain=True)
    result = dict(reply)
    result.update(ok=reply.get('ok') is True, action=action,
                  outcomeUncertain=reply.get('outcomeUncertain') is True, retryAttempted=False)
    if reply.get('action', action) != action:
        result.update(ok=False, error='Elevated helper action mismatch', outcomeUncertain=True)
    return result


def preserve_gils(run: Path, phase: str, profile: dict) -> dict:
    result = {}
    for item in [profile['targetGil'], *profile.get('protectedGils', [])]:
        source = Path(item)
        level = source.stem
        deadline = time.monotonic()+3
        previous = None
        while True:
            before = source.stat()
            if before.st_size > 32*1024*1024:
                raise ValueError('Formal GIL exceeds bounded snapshot size')
            data = source.read_bytes()
            after = source.stat()
            stamp = (after.st_size, after.st_mtime_ns)
            if ((before.st_size, before.st_mtime_ns) == stamp and len(data) == after.st_size and
                    previous is not None and previous[0] == stamp and previous[1] == data):
                break
            previous = (stamp, data) if (before.st_size, before.st_mtime_ns) == stamp else None
            if time.monotonic() >= deadline:
                raise SceneFailure('Formal GIL did not stabilize in 3 seconds', uncertain=phase=='after', run=run)
            time.sleep(.1)
        destination = run/f'{phase}-{level}.gil'
        with destination.open('xb') as stream:
            stream.write(data)
        result[str(level)] = dict(source=str(source), snapshot=str(destination), sha256=hashlib.sha256(data).hexdigest(),
                                  bytes=len(data), mtimeNs=after.st_mtime_ns)
    write_json(run/f'{phase}-gils.json', result)
    return result


def validate_direct_profile(profile: dict) -> None:
    """Re-prove the whole direct contract immediately before the launch.

    Everything here is checked against the artifacts this run actually built and
    against freshly re-derived state; nothing trusts a value the caller supplied
    on the command line. No second review claim is made -- the review gate is
    re-validated, not re-consumed.
    """
    run = Path(profile['run'])
    if not is_admin_token():
        raise SceneFailure('--direct-elevated token is not elevated immediately before launch',
                           run=run)
    for name, expected in profile['hashes'].items():
        if digest(run/name) != expected:
            raise SceneFailure('Built artifact changed before launch', run=run)
    k, _ = windows_api()
    if k.GetTickCount64() >= profile['deadlineTick']:
        raise SceneFailure('Profile deadline elapsed before launch', run=run)
    session = profile_api.validate_session(profile['session'])
    prepared = json_file(run/'prepared.json')
    sources = prepared.get('sources')
    expected_sources = set(readonly.SOURCES)
    if profile.get('reopenPrerequisites') is True:
        if (profile['action'] != 'inspect' or prepared.get('allowWrites') is not False or
                prepared.get('compileOnly') is not False or prepared.get('launchable') is not True or
                prepared.get('profileSha256') != readonly.profiles.PROFILE_SHA256 or
                prepared.get('nativeDefinitions', {}).get('HR_ACTION') != 0 or
                prepared.get('nativeDefinitions', {}).get('GS_BOOTSTRAP_READONLY') != 1):
            raise SceneFailure('Reopen prerequisites require the fixed readonly profile', run=run)
        if set(profile['hashes']) != {'hook_receipt.dll','hook_receipt_probe.exe','target_config.h',
                                      'prepared.json','invoke-readonly-probe.ps1'}:
            raise SceneFailure('Reopen prerequisites artifact set differs from fixed readonly build', run=run)
        bindings = (
            ('levelCatalog', readonly.catalog_api), ('lifecycleType', readonly.lifecycle_api),
            ('schedulerCoroutines', readonly.scheduler_api), ('reopenGuards', readonly.reopen_api))
        for key, api in bindings:
            api.load_profile()  # Recheck the real profile file against its fixed hash.
            if prepared.get(key+'ProfileSha256') != api.PROFILE_SHA256:
                raise SceneFailure('Reopen prerequisites profile binding changed: '+key, run=run)
        if (prepared.get('schedulerCoroutinesDecoderSha256') != digest(Path(readonly.scheduler_api.__file__)) or
                prepared.get('reopenGuardsDecoderSha256') != digest(Path(readonly.reopen_api.__file__)) or
                prepared.get('reopenGuardsHeaderSha256') != readonly.reopen_api.HEADER_SHA256 or
                digest(NATIVE/'guard_profile.generated.h') != readonly.reopen_api.HEADER_SHA256):
            raise SceneFailure('Reopen prerequisites decoder/header binding changed', run=run)
        from native_reopen_baseline import REQUIRED_SOURCES as reopen_sources
        expected_sources = set(reopen_sources)
    elif 'reopenPrerequisites' in profile:
        raise SceneFailure('Reopen prerequisites selector must be literal true or absent', run=run)
    if profile['action'] != 'inspect':
        expected_sources.update(('game_scene_action.cpp', 'game_scene_action.h', 'scene_calls.cpp', 'scene_calls.h'))
    if not isinstance(sources, dict) or set(sources) != expected_sources:
        raise SceneFailure('Prepared native source record is incomplete or has unexpected entries', run=run)
    if any(prepared.get('session', {}).get(key) != session.get(key) for key in SESSION_FIELDS):
        raise SceneFailure('Prepared session differs from current verified session', run=run)
    for name, expected in sources.items():
        if digest(NATIVE/name) != expected:
            raise SceneFailure('Prepared native source changed before launch: '+str(name), run=run)
    if profile['action'] != 'inspect':
        reviewed = native_write_review.validate_review(Path(profile['reviewPath']), session,
                                                       profile['expectedLevelId'],
                                                       prepared['request'])
        if (reviewed['reviewSha256'] != prepared.get('reviewSha256') or
                reviewed['reviewId'] != profile['reviewId'] or
                reviewed['writeProfile']['profileId'] != profile['profileId'] or
                reviewed['reviewPath'] != str(Path(profile['reviewPath']).resolve()) or
                native_write_review.canonical_hash(reviewed['request']) != profile['requestSha256']):
            raise SceneFailure('Re-reviewed write evidence disagrees with the built profile', run=run)


def execute_profile(profile: dict, *, direct_elevated: bool = False) -> dict:
    run = Path(profile['run'])
    for name, expected in profile['hashes'].items():
        if digest(run/name) != expected:
            raise SceneFailure('Built artifact changed before launch', run=run)
    if direct_elevated:
        validate_direct_profile(profile)
    k, _ = windows_api()
    if k.GetTickCount64() >= profile['deadlineTick']:
        raise SceneFailure('Profile deadline elapsed before launch', run=run)
    wrapper_name = profile.get('wrapperName','invoke-fixed-probe.ps1')
    wrapper = run/wrapper_name
    host = profile_api.powershell_host()
    powershell = Path(host['path'])
    readonly.write_json(run/'powershell-host.json', host)
    # A caller running PowerShell 7 can supply a PSModulePath whose incompatible
    # modules shadow Windows PowerShell 5's built-ins. Scope this correction to
    # the launcher and its elevated child; never modify the user's environment.
    child_environment = os.environ.copy()
    child_environment['PSModulePath'] = str(powershell.parent/'Modules')
    if direct_elevated:
        # This token is already elevated, so the fixed wrapper runs in place. The
        # command is deliberately the same wrapper with no -Verb RunAs and no UAC
        # launcher: the wrapper still enforces its own launch.claim, artifact,
        # game-image, recovery-copy and review hashes, and the native probe still
        # enforces attempt.used, a fresh target identity and its own deadline.
        launcher_command = [str(powershell), '-NoProfile', '-File', str(wrapper)]
    else:
        # Standard UAC only. This small launcher is separate from the elevated fixed
        # wrapper and never asks the unrelated resident editor helper to run commands.
        launcher = run/'launch-uac.ps1'
        script = """$ErrorActionPreference = 'Stop'
$taskResult = [ordered]@{started=$false;cancelled=$false;pid=$null;error=$null}
try {
    if ((Get-FileHash -LiteralPath __WRAPPER__ -Algorithm SHA256).Hash -ine __HASH__) { throw 'WRAPPER_CHANGED' }
    $taskArgs = '-NoProfile -File "' + __WRAPPER__ + '"'
    $taskProcess = Start-Process -FilePath __POWERSHELL__ -Verb RunAs -WindowStyle Hidden -ArgumentList $taskArgs -PassThru
    $taskResult.started = $true
    $taskResult.pid = $taskProcess.Id
} catch {
    $taskResult.error = $_.Exception.Message
    $taskException = $_.Exception
    while ($null -ne $taskException) {
        if ($taskException -is [ComponentModel.Win32Exception] -and $taskException.NativeErrorCode -eq 1223) { $taskResult.cancelled = $true }
        $taskException = $taskException.InnerException
    }
} finally {
    $taskResult | ConvertTo-Json | Set-Content -LiteralPath __LAUNCH_RESULT__ -Encoding utf8
}
""".replace('__POWERSHELL__', ps_literal(host['path'])).replace('__WRAPPER__', ps_literal(str(wrapper))).replace('__HASH__', ps_literal(profile['hashes'][wrapper_name])).replace('__LAUNCH_RESULT__', ps_literal(str(run/'launch-result.json')))
        with launcher.open('x', encoding='utf-8-sig') as stream:
            stream.write(script)
        launcher_command = [str(powershell), '-NoProfile', '-File', str(launcher)]
    # Persist intent before creating a child: absence of launch.claim is not evidence
    # that a concurrently starting wrapper cannot later act. No automatic replay.
    if direct_elevated:
        write_json(run/'direct-launch-intent.json', dict(schema=1, action=profile['action'],
                   createdUtc=datetime.now(timezone.utc).isoformat(), nativeStarted=None))
    with (run/'launcher.stdout.txt').open('xb') as stdout, (run/'launcher.stderr.txt').open('xb') as stderr:
        process = subprocess.Popen(launcher_command, cwd=run, stdout=stdout, stderr=stderr,
                                   env=child_environment, creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic()+90
    while time.monotonic() < deadline:
        if (run/'exit.json').exists():
            try:
                exit_result = json_file(run/'exit.json')
            except (ValueError, OSError):
                time.sleep(.1)
                continue
            if exit_result.get('error') or (exit_result.get('exitCode') != 0 and not (run/'stdout.jsonl').exists()):
                raise SceneFailure('Fixed probe failed; inspect preserved exit/stdout evidence',
                                   uncertain=bool(exit_result.get('executed')), run=run)
            record, encoding = read_probe(run/'stdout.jsonl')
            if not ((record.get('transportOk') is True or record.get('ok') is True) and record.get('unhooked') is True and record.get('activeCallbacks') == 0 and
                    record.get('callbackCount') == 1 and record.get('pid') == profile['targetPid'] and
                    record.get('tid') == profile['targetTid']):
                raise SceneFailure('Probe cleanup/identity receipt is incomplete', uncertain=True, run=run)
            inspection_acceptance = None
            if profile.get('reopenPrerequisites') is True:
                inspection_acceptance = readonly.decode_run(run)
                before = json_file(run/'readonly-snapshot.json')
            else:
                before = decode_snapshot(record)
            before['source'] = dict(path=str(run/'stdout.jsonl'), encoding=encoding, snapshotField='snapshotHex')
            write_json(run/'before-context.json', before)
            after = None
            raw_after = record.get('afterSnapshotHex')
            if raw_after and set(raw_after) != {'0'}:
                after = decode_snapshot(dict(record, snapshotHex=raw_after))
                after['source'] = dict(path=str(run/'stdout.jsonl'), encoding=encoding, snapshotField='afterSnapshotHex')
                write_json(run/'after-context.json', after)
            return dict(record=record, before=before, after=after, readonlyAcceptance=inspection_acceptance)
        if (run/'launch-result.json').exists():
            try:
                launched = json_file(run/'launch-result.json')
            except (OSError, ValueError):
                time.sleep(.1)
                continue
            if not launched.get('started'):
                raise SceneFailure('UAC cancelled' if launched.get('cancelled') else 'UAC launcher refused execution', run=run)
        elif process.poll() is not None:
            raise SceneFailure('Direct elevated wrapper exited without a receipt' if direct_elevated
                               else 'UAC launcher exited without a receipt', uncertain=True, run=run)
        time.sleep(.1)
    # Do not terminate any target/helper or retry. A delayed callback/approval can
    # still finish before its native deadline; preserve that uncertainty explicitly.
    raise SceneFailure('90-second wait elapsed; outcome uncertain, no automatic retry', uncertain=True, run=run)


def run_profile(profile: dict, *, direct_elevated: bool = False) -> dict:
    run = Path(profile['run'])
    before_gils = preserve_gils(run, 'before', profile) if profile['action'] != 'inspect' else None
    try:
        outcome = execute_profile(profile, direct_elevated=direct_elevated)
    finally:
        # Even a failed callback can have produced an effect. Preserve readable
        # disk evidence; failure here must never turn into a second game call.
        if profile['action'] != 'inspect':
            after_gils = preserve_gils(run, 'after', profile)
    record, before, after = outcome['record'], outcome['before'], outcome['after']
    if profile['action'] == 'reopen-current':
        # The new fixed native decoder (owned by the action implementation) must populate
        # this only after validating ABI, request/nonce, identity and hook cleanup.
        from native_reopen_result import dispatch_result
        dispatch = outcome['reopenDispatch']
        result = dispatch_result(request_id=profile['reopenRequestId'],
            native_receipt_sha256=digest(run/'stdout.jsonl'),
            preflight_passed=dispatch['preflightPassed'], call_attempted=dispatch['nativeCallAttempted'],
            call_returned=dispatch['nativeCallReturned'], call_exception_code=dispatch['callExceptionCode'],
            hook_cleanup_verified=dispatch['hookCleanupVerified'])
        result.update(run=str(run), receipt=str(run/'stdout.jsonl'), beforeGils=before_gils, afterGils=after_gils)
        write_json(run/'result.json', result)
        return result
    action = record.get('action')
    result = dict(ok=True, action=profile['action'], run=str(run), profile=str(run/('target-profile.json' if (run/'target-profile.json').exists() else 'prepared.json')),
                  beforeSnapshot=str(run/'before-context.json'),
                  afterSnapshot=str(run/'after-context.json') if after is not None else None,
                  receipt=str(run/'stdout.jsonl'), entityId=action.get('entityId') if action else None,
                  owner=action.get('owner') if action else None, levelId=action.get('levelId') if action else None,
                  nativeStatus=action.get('nativeSaveStatus') if action and profile['action']=='save' else None,
                  snapshotStatus=before['status'], entities=before['counts']['entityValidEntries'],
                  called=action.get('called') if action else 0, actionStatus=action.get('status') if action else None,
                  placedCount=action.get('placedCount') if action else None,
                  placedIds=action.get('placedIds') if action else None,
                  retryAttempted=False, cleanupVerified=True, nativeStarted=True)
    # A batch reports one id per requested placement, in request order. If the count does
    # not match the request, the receipt is not evidence of a complete batch.
    if profile['action'] == 'create-batch' and result['ok']:
        if result['placedCount'] != profile['placementCount'] or                 len(result['placedIds'] or []) != profile['placementCount']:
            result.update(ok=False, error='Batch receipt did not resolve every placement',
                          outcomeUncertain=True)
    if before['status']['value'] != 0 or record.get('ok') is not True:
        result['ok'] = False
        result['error'] = 'Inspection snapshot is incomplete'
    if profile['action'] == 'inspect':
        accepted=outcome.get('readonlyAcceptance') if profile.get('reopenPrerequisites') is True else readonly.validate_receipt(record,before,readonly.read_json(run/'prepared.json'),readonly.profiles.load_profile())
        if profile.get('reopenPrerequisites') is True:
            if not isinstance(accepted,dict): raise SceneFailure('REOPEN_PREREQUISITES_DECODER_MISSING', run=run)
            result['reopenPrerequisites'] = True
        observed=before.get('levelObservation',{})
        result.update(levelId=observed.get('levelId'),mutationAttempted=False,readonlyAcceptance=accepted)
        if not accepted['ok']:
            result.update(ok=False,error='Readonly receipt validation failed: '+','.join(accepted['reasons']))
        if observed.get('verified') is not True or observed.get('levelId') != profile['expectedLevelId']:
            result.update(ok=False,error='Observed current editing level is unverified or differs from requested level')
    if profile['action'] != 'inspect':
        result.update(beforeGils=before_gils, afterGils=after_gils,
                      gilChanged={level: before_gils[level]['sha256'] != after_gils[level]['sha256'] for level in before_gils},
                      persistenceVerified=False)
        if not action or action.get('status') != 0 or action.get('levelId') != profile['expectedLevelId'] or action.get('called') != 1:
            result.update(ok=False, error='Native action rejected or did not complete', outcomeUncertain=bool(action and action.get('called')))
        if action and action.get('called') and (after is None or after['status']['value'] != 0):
            result.update(ok=False, error='Post-action snapshot unavailable', outcomeUncertain=True)
        if profile['action']=='save' and action and action.get('nativeSaveStatus') != 0:
            result.update(ok=False, error='Native save status was not success', outcomeUncertain=bool(action.get('called')))
        if any(changed for key,changed in result['gilChanged'].items() if key != str(profile['expectedLevelId'])):
            result.update(ok=False, error='Protected non-target GIL changed', outcomeUncertain=True)
    write_json(run/'result.json', result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('inspect','create','creature-create','create-batch','save','reopen-current'):
        child = sub.add_parser(name)
        child.add_argument('--prepare-only', action='store_true')
        if name == 'inspect':
            child.add_argument('--reopen-prerequisites', action='store_true', help='Read-only catalog, lifecycle, scheduler and reopen guards together')
            child.add_argument('--large-scene', action='store_true', help='Explicit v2 complete snapshot, up to 4096 observed entities; not a game quota override')
        transport = child.add_mutually_exclusive_group()
        transport.add_argument('--elevated-queue', type=Path, metavar='QUEUE_DIR',
                               help='Hand a closed data-only request to the resident elevated runner; nothing is built or claimed locally')
        transport.add_argument('--direct-elevated', action='store_true',
                               help='Run the fixed wrapper in place; requires a genuinely elevated Windows token')
        child.add_argument('--session', type=Path, help='Freshly discovered native session; optional project-local current-native-session reference is always revalidated')
        child.add_argument('--level-id', type=int, help='Explicit level; MILIASTRA_LEVEL remains accepted with no fallback')
        if name != 'inspect':
            child.add_argument('--review', type=Path, help='Coordinator evidence record bound to this request and complete runtime baseline')
            child.add_argument('--baseline', type=Path, help='Optional consistency check against the reviewed, independently decoded baseline')
        if name == 'create':
            child.add_argument('--template-id', type=int, required=True)
            child.add_argument('--position', type=float, nargs=3, required=True)
            child.add_argument('--rotation', type=float, nargs=3, default=(0,0,0))
            child.add_argument('--scale', type=float, nargs=3, default=(1,1,1))
        if name == 'creature-create':
            child.add_argument('--template-id', type=int, required=True)
            child.add_argument('--position', type=float, nargs=3, required=True)
            child.add_argument('--rotation', type=float, nargs=3, default=(0,0,0))
            child.add_argument('--scale', type=float, nargs=3, default=(1,1,1))
            # The layout factory's 3rd argument. 1 reproduces the observed drag caller and is what
            # every create so far has sent; the probe varies it to answer whether a 3xxxxxxx
            # template needs a different value. See native/scene_calls.h:15-19.
            child.add_argument('--place-builtin', type=int, choices=range(0, 256), default=1)
        if name == 'create-batch':
            # One callback, N placements. The plan is a JSON file with a "placements" list
            # of {template_id, position, scale, rotation?}.
            child.add_argument('--plan', type=Path, required=True)
        if name == 'reopen-current':
            child.add_argument('--reopen-request-id', help=argparse.SUPPRESS)
            child.add_argument('--reopen-lease-sha256', help=argparse.SUPPRESS)
    return parser


def main() -> int:
    # JSON consumers read UTF-8 even when Windows redirects this process to a pipe.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    args = build_parser().parse_args()
    current = None
    try:
        queue_mode, direct_mode = bool(args.elevated_queue), bool(args.direct_elevated)
        if queue_mode or direct_mode:
            # --prepare-only means "stop after local preparation", which neither
            # transport performs. Refuse before any build, queue write or claim.
            if args.prepare_only:
                raise SceneFailure('--prepare-only cannot be combined with --elevated-queue or '
                                   '--direct-elevated; neither path prepares locally')
            # The reviewed baseline is decoded by the helper for a queued write.
            # Silently dropping it would dispatch a different request than the one
            # the caller asked for, so an unsupported combination is refused.
            if queue_mode and getattr(args, 'baseline', None) is not None:
                raise SceneFailure('--baseline is not supported with --elevated-queue; refusing '
                                   'rather than ignoring the requested consistency check')
            if direct_mode and not is_admin_token():
                raise SceneFailure('--direct-elevated requires an actually elevated Windows token; '
                                   'refusing before build and review claim')
        if queue_mode:
            request = queue_request(args)
            result = send_queued_scene(request, args.action, args.elevated_queue)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['ok'] else 2
        if args.action == 'reopen-current':
            if not direct_mode or args.prepare_only or args.baseline is not None:
                raise SceneFailure('REOPEN_REQUIRES_FIXED_HELPER_TRANSPORT')
            if resolve_level(args.level_id) != 1073741840 or args.review is None:
                raise SceneFailure('REOPEN_REVIEW_AND_FIXED_LEVEL_REQUIRED')
            from reopen_dispatch import run as dispatch_reopen
            result = dispatch_reopen(guarded_runtime_file(args.session, 'SESSION'),
                guarded_runtime_file(args.review, 'REVIEW'),args.reopen_request_id,args.reopen_lease_sha256)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result['ok'] else 2
        inputs = {}
        if args.action == 'create':
            inputs = dict(template_id=args.template_id, position=vector(args.position), rotation=vector(args.rotation),
                          scale=vector(args.scale, positive=True))
        if args.action == 'creature-create':
            inputs = dict(template_id=args.template_id, position=vector(args.position), rotation=vector(args.rotation),
                          scale=vector(args.scale, positive=True), place_builtin=args.place_builtin)
        if args.action == 'create-batch':
            inputs = dict(placements=read_plan_spec(args.plan)['placements'])
        baseline = json_file(args.baseline) if args.action != 'inspect' and args.baseline else None
        current = build_profile(args.action, baseline=baseline, session_path=args.session,
                                level_id=resolve_level(args.level_id),
                                review_path=args.review if args.action != 'inspect' else None,
                                reopen_prerequisites=getattr(args,'reopen_prerequisites',False),
                                large_scene=getattr(args,'large_scene',False), **inputs)
        if args.prepare_only:
            print(json.dumps(dict(current, preparedOnly=True), ensure_ascii=False))
            return 0
        result = run_profile(current, direct_elevated=direct_mode)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['ok'] else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, OverflowError, struct.error) as error:
        run_path = getattr(error,'run',None) or (current['run'] if current else None)
        possibly_started = bool(run_path and any((Path(run_path)/name).exists() for name in
                                ('direct-launch-intent.json', 'launch.claim', 'attempt.used')))
        result = dict(ok=False, error=str(error), outcomeUncertain=getattr(error,'uncertain',False),
                      run=run_path, retryAttempted=False,
                      finishedUtc=datetime.now(timezone.utc).isoformat())
        result['outcomeUncertain'] |= possibly_started
        # This says only that our code never crossed a launch boundary. A missing
        # child receipt after launch cannot release the resident helper's lock.
        result.update(safeToRelease=not result['outcomeUncertain'],
                      nativeStarted=None if result['outcomeUncertain'] else False)
        if args.action == 'reopen-current':
            result.update(safeToRelease=False, businessPending=True, businessVerified=False,
                          reopenVerified=False, hookCleanupVerified=False, retryAttempted=False)
        if result['run']:
            path = Path(result['run'])/'cli-failure.json'
            if not path.exists():
                write_json(path, result)
        print(json.dumps(result, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
