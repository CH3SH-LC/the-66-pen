"""Business entry: find the CURRENT editing level without being told its id.

Why this file exists
--------------------
``build_readonly_profile.py discover`` reports process/thread/window identity only.
Every other entry -- ``author.py entity-inspect``, ``scene_cli.py inspect`` -- takes an
explicit ``--level-id`` and then *verifies* what it observes against it.  So the project
had no way to answer "which level is open right now?" from zero, and the documented rule
is that a historical id must never be used to fill that hole.

This wraps the already-existing observation chain into one bounded business step; the
observation itself (a readonly native snapshot whose level identity is read twice and
compared inside the probe, game_context_snapshot.cpp:455-461) is identical on both
transports:

    session (discover or explicit) -> readonly prepare (compiles the fixed probe)
      -> run the ONE generated wrapper through a standard UAC launch
      -> decode --run, which validates the receipt and reports levelObservation

    --queue-dir QUEUE: the same fixed readonly probe, but compiled and run by the
      already-elevated resident helper through its data-only queue.  No UAC prompt is
      raised, and this mode has NO fallback to the launcher: an unusable queue is a
      refusal.  See "Two transports" below.

The level id returned here comes from the native receipt, never from a caller and never
from a config file.  The opaque handle is the run directory name plus the session and
snapshot digests; callers pass the handle around and re-resolve it here.

Two transports
--------------
* default: ``Start-Process -Verb RunAs``.  The operator answers one Windows elevation
  prompt.  MEASURED (2026-10-02): this is a real external blocker -- a declined or
  unanswered prompt raised ``UAC prompt declined or left unanswered; the probe was
  never launched``, and a driver must not retry it (UAC is the operator's to answer, and
  a second request would be stacked behind the pending one).
* ``--queue-dir``: the resident elevated helper (tools/editor-bridge/elevated-runner.ps1)
  is ALREADY elevated, so a request dropped in its queue needs no new UAC prompt.  It
  reaches the same probe through ``scene_cli.py inspect --direct-elevated``.  The
  transport is the project's existing queue client
  (tools/editor-bridge/elevated-request.py) and the existing readonly receipt decoders;
  nothing new is invented here.
  MEASURED (2026-10-02, S08 live preflight): a queued readonly inspect returned
  ``levelId 1073741839`` with 69 entities from a real in-process read.

  WHICH LEVEL IS CLAIMED, AND WHY THE CLAIM IS NOT THE ANSWER
  The helper's closed request schema requires a uint32 ``levelId`` on every native-scene
  action, and the readonly probe does not use it as a read input at all
  (``build_scene_profile.build_profile`` calls ``readonly.prepare`` with no level for
  ``action='inspect'``; the requested id is only an expectation recorded as
  ``expectedLevelId``).  A discovery therefore has to put SOMETHING in that field, and
  the value used is ``QUEUE_CLAIM_LEVEL_ID`` -- a legal uint32 that is not, and cannot
  be, a project level id.  It is a wire placeholder: it is never reported as the answer,
  and a run whose OBSERVED id equals it is refused.  The reported id is read by the
  pinned level-observation decoder out of the receipt's snapshot, exactly as on the
  default transport.

What this is not
----------------
* It does not write anything to a level, does not save, does not reopen, does not run
  the game.  The probe links ``HR_ACTION=0`` and ``GS_BOOTSTRAP_READONLY=1``.
* ``verified`` is what the native decoder reported, not a claim by this program.
* On the default transport it launches exactly one child through
  ``Start-Process -Verb RunAs``.  If the UAC prompt is declined it reports that and
  exits non-zero.  It never retries, and a second discovery is a new run with a new
  probe.  On ``--queue-dir`` it raises no prompt at all, and a queue failure is
  reported instead of falling back to the prompt.
* ``--analyze-run`` reads an EXISTING run directory and never claims a current level:
  a stored receipt can be diagnosed, never promoted into today's answer.  Its ``ok``
  is therefore always false; ``analysisOk`` says whether the receipt decoded.

Usage
-----
    python -B tools/game-executor/discover_current_level.py --output-root <dir-under-.runtime>
    python -B tools/game-executor/discover_current_level.py --session <fresh session.json> \
        --output-root <dir-under-.runtime>
    python -B tools/game-executor/discover_current_level.py --queue-dir <queue-under-editor-bridge> \
        --output-root <dir-under-.runtime>
    python -B tools/game-executor/discover_current_level.py --analyze-run <existing run dir>

Exit code 0 only when the native receipt decoded, the callback drained cleanly and
``levelObservation.verified`` is true with a non-zero level id.  Any other outcome is
reported with the preserved run directory so it can be inspected rather than re-run.
``--analyze-run`` exits 0 when the stored receipt decoded, whatever the verdict on it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import build_readonly_profile as readonly  # noqa: E402
import native_profiles as profiles  # noqa: E402

#: The one place new discovery evidence is allowed to land.  ``profiles.require`` in
#: build_readonly_profile.output_directory enforces this again from the inside.
DEFAULT_OUTPUT_ROOT = profiles.ROOT / '.runtime/game-executor/current-level-discovery'
#: The fixed launcher is separate from the elevated wrapper and never executes a
#: caller-supplied script: it re-hashes the wrapper, then asks for elevation once.
LAUNCHER = 'launch-uac.ps1'
#: How long to wait for the launched probe to write its own exit receipt.
#:
#: MEASURED (2026-09-30): this was 90 s and it raced the operating system. A declined or
#: unanswered elevation prompt is held on screen by Windows for roughly two minutes; the
#: launcher's own `Start-Process -Verb RunAs` was observed blocking **126.6 s** before it
#: returned, by which time this program had already given up and reported an uncertain
#: outcome. So a user who answers the prompt late had their acceptance thrown away.
WAIT_SECONDS = 270
#: The resident helper's default queue.  ``--queue-dir`` may name any queue under
#: ``.runtime/editor-bridge`` (the client re-checks that containment from the inside).
QUEUE_DEFAULT_DIR = profiles.ROOT / '.runtime/editor-bridge/elevated-queue'
#: Where the helper's ``scene_cli.py inspect`` runs land.  A queued discovery is one of
#: these, and the handle it returns is that directory's name.
QUEUE_RUN_ROOT_NAME = '.runtime/game-executor/scene-cli/inspect'
#: How long ``send_native_scene`` waits for the helper's reply before reporting the
#: request as pending.  The same bound the S08 live preflight used.
QUEUE_SEND_TIMEOUT = 120.0
#: The uint32 the wire schema forces a discovery to carry in ``levelId``.
#:
#: It is a PLACEHOLDER, not a claim: the readonly probe never reads it (it is only
#: recorded as ``expectedLevelId`` and compared against the observed id afterwards), so
#: it cannot influence what is observed.  It has to be a legal wire value
#: (``elevated-request.validate_native_scene_request`` and the runner's
#: ``ConvertTo-NativeId`` both refuse 0) and it must not be a level id this project can
#: see: every level id ever observed here is 1073741839 = 0x4000000F
#: (``native_reopen_baseline.LEVEL``), in the 0x4000000x range.  0xFFFFFFFF is neither.
#: A run whose OBSERVED id is this value is refused
#: (LEVEL_IDENTITY_IS_CLAIM_PLACEHOLDER): the answer may never be the placeholder.
QUEUE_CLAIM_LEVEL_ID = 0xFFFFFFFF
#: How long after submission a run directory may have been created and still count as
#: the run this call caused.  Anything older is a previous observation: it is refused
#: rather than adopted, because "the level was 1073741839 at some point" is not an
#: answer to "which level is open now".
QUEUE_RUN_AGE_GRACE_SECONDS = 2.0
#: Session fields that bind a run to the identity it observed.  The same set
#: ``scene_cli`` itself compares (scene_cli.py:59 SESSION_FIELDS).
SESSION_FIELDS = ('schemaVersion', 'pid', 'tid', 'window', 'windowClass',
                  'processCreation', 'threadCreation', 'image')

#: How long the generated one-shot probe remains launchable after preparation.
#:
#: This is a HUMAN-IN-THE-LOOP step: the operator has to notice and answer an elevation
#: prompt. MEASURED (2026-09-30, second attempt): the default 180 s expired **50 s before**
#: the operator answered, so the run was already dead when the prompt was still on screen --
#: a prompt that is still waiting is not a prompt that failed. The TTL must therefore be
#: strictly longer than WE are willing to wait, so the only thing that can invalidate the
#: run is the operator declining, never our own clock.
#:
#: It sits at 300 because that is the CEILING the pinned validator imposes
#: (`build_readonly_profile.py:168`: `30<=ttl_seconds<=300`). MEASURED: asking for 360 is
#: refused outright with TTL_OUT_OF_RANGE. The margin over WAIT_SECONDS is therefore at most
#: 30 s and cannot be widened here. Raising a pinned validation bound so that a run of mine
#: fits is the same move as loosening an acceptance criterion, and it is not done.
PREPARATION_TTL_SECONDS = 300


def write_json(path: Path, value) -> None:
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha256_file(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def discover_session(output: Path) -> Path:
    """Write a fresh process/thread/window identity record.  Never elevates."""
    profiles.verify_disk(profiles.load_profile())
    result = profiles.discover_session()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError('refusing to overwrite an existing session record: %s' % output)
    readonly.write_json(output, result)
    return output


def ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def pending_elevation_prompts(list_processes=None) -> int:
    """How many Windows elevation prompts are on screen right now.

    A pending prompt JAMS the elevation queue: `Start-Process -Verb RunAs` blocks until the
    prompt in front of it is answered, so a second request cannot even be shown, let alone
    answered. MEASURED (2026-09-30): after one attempt left its prompt unanswered, the next
    two attempts produced **no launch receipt at all** within 150 s and 270 s respectively,
    while attempt 1's launcher had returned after 126.6 s. Each timeout then left one more
    blocked launcher behind, so the jam fed itself. Checking first is the difference between
    "the operator has to answer a prompt" and "the operator has to answer an unknown number
    of stacked prompts".
    """
    if list_processes is None:
        def list_processes():
            import subprocess as _sp
            powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            completed = _sp.run(
                [str(powershell), '-NoProfile', '-Command',
                 '(Get-Process consent -ErrorAction SilentlyContinue | Measure-Object).Count'],
                capture_output=True, text=True, timeout=60)
            text = (completed.stdout or '').strip()
            return int(text) if text.isdigit() else 0
    try:
        return int(list_processes())
    except Exception:
        # An unreadable answer must not be turned into "no prompts" and must not block a
        # legitimate run: report unknown as -1, which callers treat as "cannot tell".
        return -1


def emit_launcher(run: Path, wrapper: Path, wrapper_sha256: str, *, host=None) -> Path:
    """The standard-UAC launcher, same shape the fixed scene wrapper already uses."""
    host = host or profiles.powershell_host()
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
    # MEASURED: a declined elevation prompt surfaces as an InvalidOperationException whose
    # message WRAPS the OS text for ERROR_CANCELLED -- "由于出现以下错误，无法运行此命令: 操作已被用户取消。"
    # Walking the inner-exception chain for NativeErrorCode 1223 alone missed it and
    # reported cancelled=false for a prompt the user had in fact dismissed, which told the
    # caller "the launcher refused" instead of "you were not asked successfully". Compare
    # against the operating system's own localized text for that code as well.
    $cancelText = (New-Object ComponentModel.Win32Exception 1223).Message
    if ($taskResult.error -and $cancelText -and $taskResult.error.Contains($cancelText)) { $taskResult.cancelled = $true }
    $taskException = $_.Exception
    while ($null -ne $taskException) {
        if ($taskException -is [ComponentModel.Win32Exception] -and $taskException.NativeErrorCode -eq 1223) { $taskResult.cancelled = $true }
        $taskException = $taskException.InnerException
    }
} finally {
    $taskResult | ConvertTo-Json | Set-Content -LiteralPath __LAUNCH_RESULT__ -Encoding utf8
}
""".replace('__POWERSHELL__', readonly.ps_literal(host['path'])).replace('__WRAPPER__', ps_literal(str(wrapper))).replace(
        '__HASH__', ps_literal(wrapper_sha256)).replace(
        '__LAUNCH_RESULT__', ps_literal(str(run / 'launch-result.json')))
    path = run / LAUNCHER
    with path.open('x', encoding='utf-8-sig') as stream:
        stream.write(script)
    return path


def run_wrapper(run: Path, wrapper: Path, wrapper_sha256: str) -> dict:
    """Launch the fixed probe once through UAC and wait for its own exit receipt."""
    host = profiles.powershell_host()
    launcher = emit_launcher(run, wrapper, wrapper_sha256, host=host)
    powershell = Path(host['path'])
    readonly.write_json(run/'powershell-host.json', host)
    environment = os.environ.copy()
    environment['PSModulePath'] = str(powershell.parent / 'Modules')
    command = [str(powershell), '-NoProfile', '-File', str(launcher)]
    with (run / 'launcher.stdout.txt').open('xb') as stdout, \
            (run / 'launcher.stderr.txt').open('xb') as stderr:
        process = subprocess.Popen(command, cwd=run, stdout=stdout, stderr=stderr,
                                   env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        exit_path = run / 'exit.json'
        if exit_path.exists():
            try:
                exit_result = read_json(exit_path)
            except (OSError, ValueError):
                time.sleep(.1)
                continue
            return exit_result
        launch_path = run / 'launch-result.json'
        if launch_path.exists():
            try:
                launched = read_json(launch_path)
            except (OSError, ValueError):
                time.sleep(.1)
                continue
            if not launched.get('started'):
                raise RuntimeError('UAC prompt declined or left unanswered; the probe was '
                                   'never launched, so no level was read'
                                   if launched.get('cancelled')
                                   else 'UAC launcher did not start the probe: %s'
                                        % launched.get('error'))
        elif process.poll() is not None and not exit_path.exists():
            raise RuntimeError('UAC launcher exited without a receipt')
        time.sleep(.1)
    raise RuntimeError('%d-second wait elapsed; outcome uncertain, no automatic retry'
                       % WAIT_SECONDS)


def parse_handle(text: str) -> Path:
    """Resolve an opaque handle back to its run directory, inside this project only.

    A handle is the NAME of a directory under ``<output-root>/runs`` -- that is what
    ``discover`` returns.  MEASURED: joining it to the output root instead of the runs
    subdirectory made every ``--show`` fail with HANDLE_OUTSIDE_..., including handles
    this program had just minted.
    """
    run = Path(text)
    runs_root = (DEFAULT_OUTPUT_ROOT / 'runs').resolve()
    if not run.is_absolute():
        run = runs_root / run
    run = run.resolve()
    if not run.is_dir() or not run.is_relative_to(runs_root):
        raise ValueError('HANDLE_OUTSIDE_CURRENT_LEVEL_DISCOVERY: %s' % text)
    return run


# --------------------------------------------------------------------------- #
# The queued transport.  The resident helper is ALREADY elevated, so this path
# raises no prompt; nothing below compiles, launches or schedules an elevation.
# Everything it uses is an existing project component: the fixed queue client
# (tools/editor-bridge/elevated-request.py), the pinned readonly readers and the
# pinned readonly acceptance validator.  No second protocol is defined here.
# --------------------------------------------------------------------------- #

def queue_run_root() -> Path:
    """Where the helper's own ``scene_cli.py inspect`` runs land."""
    return (profiles.ROOT / QUEUE_RUN_ROOT_NAME).resolve()


class QueueRefused(RuntimeError):
    """A queue-transport refusal.

    Deliberately its own type: the only correct answer to it is to report it.  It must
    never be answered by escalating to the UAC launcher -- that would put an elevation
    prompt on somebody's screen as a side effect of a failure.
    """


def parse_utc(text):
    """An aware UTC timestamp, or None.  A naive stamp is refused, not assumed."""
    if not isinstance(text, str) or not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def queue_client_module():
    """The fixed queue client, imported by path and never copied or patched.

    Same idiom ``scene_cli.load_native_sender`` uses (spec_from_file_location on the
    fixed file, private module name), so the helper's contract stays the only contract
    and a differently-named module elsewhere cannot be imported in its place.
    """
    path = profiles.ROOT / 'tools/editor-bridge/elevated-request.py'
    profiles.require(path.is_file(), 'QUEUE_CLIENT_MISSING:' + str(path))
    spec = importlib.util.spec_from_file_location('_current_level_queue_client', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profiles.require(callable(getattr(module, 'send_native_scene', None)),
                     'QUEUE_CLIENT_HAS_NO_SEND_NATIVE_SCENE')
    return module


def build_queue_request(session_path, *, large_scene=False) -> dict:
    """The closed request for a discovery: one plain readonly ``inspect``.

    Plain on purpose.  ``--reopen-prerequisites`` would also compile the catalog,
    lifecycle, scheduler and guard extensions, and their verdicts are folded into the
    receipt's own aggregate ``ok`` (native/hook_receipt_probe.cpp:177-189) -- such a run
    is judged by criteria the discovery neither needs nor can satisfy today (MEASURED
    2026-10-02: ``LIFECYCLE_STATUS_not_initialized``).  The plain probe reports the level
    identity and the entity set from the SAME doubly-read snapshot
    (native/game_context_snapshot.cpp:455-461 reads the level before and after the walk
    and requires them equal), and its acceptance is exactly the one
    ``readonly.decode_run``/``readonly.validate_receipt`` already define.

    ``levelId`` is required by the wire schema and is NOT a read input: see
    ``QUEUE_CLAIM_LEVEL_ID``.
    """
    request = dict(kind='native-scene', action='inspect',
                   sessionPath=str(Path(session_path).resolve()),
                   levelId=QUEUE_CLAIM_LEVEL_ID)
    if set(request) != {'kind', 'action', 'sessionPath', 'levelId'}:
        raise ValueError('QUEUE_REQUEST_SHAPE_CHANGED')
    profiles.require(type(large_scene) is bool, 'LARGE_SCENE_BOOL_REQUIRED')
    if large_scene: request['largeScene'] = True
    return request


def queue_send(request, *, queue_dir, timeout) -> dict:
    """Enqueue once through the fixed client.  Never re-sends, never elevates.

    Both failure routes end as a refusal.  ``send_native_scene`` refuses before it
    enqueues anything when the queue is not under this project's bridge tree, when the
    helper's heartbeat is missing or older than 30 s, or when the helper's identity,
    capability set, pins digest or project root does not match -- so a dead or foreign
    helper never receives a request and never leaves a half-sent one behind.
    """
    try:
        module = queue_client_module()
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as error:
        raise QueueRefused(
            'QUEUE_CLIENT_UNUSABLE: %s: %s. The fixed queue client is the only transport '
            'this mode uses; no UAC prompt was raised and none will be.'
            % (type(error).__name__, error)) from None
    try:
        reply = module.send_native_scene(request, timeout=timeout, queue_dir=Path(queue_dir))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError, SystemExit) as error:
        raise QueueRefused(
            'QUEUE_UNAVAILABLE: %s: %s. The resident helper queue is the only transport '
            'this mode uses; no UAC prompt was raised and none will be -- bring the helper '
            'up and re-run, or ask for the default transport explicitly.'
            % (type(error).__name__, error)) from None
    if not isinstance(reply, dict):
        raise QueueRefused('QUEUE_REPLY_NOT_OBJECT: %r' % (reply,))
    return reply


def resolve_queue_run(raw) -> Path:
    """The run directory the helper named, inside the scene-cli inspect root only."""
    if not isinstance(raw, str) or not raw:
        raise QueueRefused('QUEUE_REPLY_HAS_NO_RUN: %r' % (raw,))
    run = Path(raw)
    profiles.require(run.is_absolute(), 'QUEUE_RUN_NOT_ABSOLUTE:' + raw)
    run = run.resolve()
    root = queue_run_root()
    profiles.require(run.is_dir() and run.is_relative_to(root),
                     'QUEUE_RUN_OUTSIDE_SCENE_CLI_INSPECT:' + raw)
    return run


def resolve_any_run(raw) -> Path:
    """An existing run directory under one of this program's two evidence roots.

    Relative paths are read against the project root so an operator can paste a path
    from a log; anything outside both roots is refused, because a run directory this
    program did not create is not evidence it may interpret.
    """
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = profiles.ROOT / candidate
    run = candidate.resolve()
    roots = [(DEFAULT_OUTPUT_ROOT / 'runs').resolve(), queue_run_root()]
    profiles.require(run.is_dir() and any(run.is_relative_to(root) for root in roots),
                     'RUN_OUTSIDE_PROJECT_EVIDENCE_ROOTS:' + str(raw))
    return run


def decode_receipt(run: Path) -> dict:
    """Re-derive a run's receipt evidence with the pinned readers only.  Never writes.

    The reader/decoder pair is the one ``check_reopen_prerequisites.analyze_run`` uses
    (``readonly.load_decoder().read_probe`` -> ``decode_snapshot``) and the acceptance is
    the one ``build_readonly_profile.decode_run`` itself uses
    (``readonly.validate_receipt``).  The digests the run recorded for its own compiled
    artifacts are re-checked first, so a receipt or probe that changed after the run is
    refused here instead of being decoded as if it were the original.
    """
    run = Path(run)
    prepared = read_json(run / 'prepared.json')
    built = read_json(run / 'build-result.json')
    for name, digest in (built.get('hashes') or {}).items():
        profiles.require(profiles.sha256(run / name) == digest, 'RUN_ARTIFACT_CHANGED:' + name)
    exit_result = read_json(run / 'exit.json')
    decoder = readonly.load_decoder()
    record, encoding = decoder.read_probe(run / 'stdout.jsonl')
    snapshot = decoder.decode_snapshot(record)
    acceptance = readonly.validate_receipt(record, snapshot, prepared, profiles.load_profile())
    return dict(run=run, prepared=prepared, built=built, exit=exit_result, record=record,
                encoding=encoding, snapshot=snapshot, acceptance=acceptance)


def evaluate_queue_observation(run, evidence, reply, *, session_path, session,
                              submitted_at) -> dict:
    """The one place a queued discovery may become a current-level observation.

    ``session_path``, ``session`` and ``submitted_at`` are keyword-only and have no
    default, and a missing one is an error rather than a skipped check: the checks that
    make this run THIS observation must not be switchable off by calling the gate
    differently.  A policy failure returns ``ok=False`` with named reasons; it never
    raises, and it never falls back to the launcher.
    """
    if session_path is None or session is None or submitted_at is None:
        raise ValueError('QUEUE_OBSERVATION_GATE_REQUIRES_SUBMISSION_BINDING')

    prepared = evidence['prepared']
    snapshot = evidence['snapshot']
    acceptance = evidence['acceptance']
    record = evidence['record']
    exit_result = evidence['exit']
    reasons = []

    # (1) The run must be a plain readonly inspect.  Anything else is a different
    #     operation whose receipt this gate is not entitled to interpret.
    extension_keys = sorted(key for key in prepared
                            if key.endswith('ProfileSha256')
                            and key != 'levelObservationProfileSha256')
    if extension_keys:
        reasons.append('NOT_A_PLAIN_READONLY_INSPECT:' + ','.join(extension_keys))
    if prepared.get('launchable') is not True or prepared.get('compileOnly') is not False:
        reasons.append('NONLAUNCHABLE_BUILD')
    if prepared.get('allowWrites') is not False:
        reasons.append('ALLOW_WRITES_NOT_FALSE')
    definitions = prepared.get('nativeDefinitions') or {}
    if definitions.get('HR_ACTION') != 0 or definitions.get('GS_BOOTSTRAP_READONLY') != 1:
        reasons.append('NOT_THE_READONLY_PROBE')

    # (2) It must be the run THIS submission caused.  A stored receipt is a previous
    #     observation: "the level was X earlier" is not an answer to "which level is
    #     open now", which is the rule this whole file exists to keep.
    if (run / 'readonly-acceptance.json').exists():
        reasons.append('RUN_ALREADY_DECODED')
    if (run / 'current-level-observation.json').exists():
        reasons.append('RUN_ALREADY_RECORDED')
    created = parse_utc(prepared.get('createdUtc'))
    if created is None:
        reasons.append('RUN_CREATED_UTC_UNREADABLE:%r' % (prepared.get('createdUtc'),))
    elif not (submitted_at - timedelta(seconds=QUEUE_RUN_AGE_GRACE_SECONDS) <= created
              <= submitted_at + timedelta(seconds=QUEUE_SEND_TIMEOUT + 120)):
        reasons.append('RUN_NOT_THIS_OBSERVATION:createdUtc=%s' % prepared.get('createdUtc'))

    # (3) It must have observed the identity THIS call submitted and revalidated.
    prepared_session = prepared.get('session') or {}
    mismatched = [name for name in SESSION_FIELDS
                  if prepared_session.get(name) != session.get(name)]
    if mismatched:
        reasons.append('SESSION_BINDING_MISMATCH:' + ','.join(mismatched))

    # (4) The helper's reply must be about this request and this run.
    if reply.get('action') != 'inspect':
        reasons.append('QUEUE_REPLY_ACTION_MISMATCH:%r' % (reply.get('action'),))
    if reply.get('outcomeUncertain') is True:
        reasons.append('QUEUE_OUTCOME_UNCERTAIN')
    if reply.get('pending') is True:
        reasons.append('QUEUE_REQUEST_PENDING')
    if reply.get('observedDuringReopenRequestId'):
        # The helper marks a read it served while another request held the dispatch
        # claim.  That observation belongs to that request; adopting it here would be
        # answering with somebody else's read.
        reasons.append('OBSERVED_DURING_ANOTHER_REQUEST:%s'
                       % reply['observedDuringReopenRequestId'])

    # (5) The receipt must have executed and drained.
    if (exit_result.get('executed') is not True or exit_result.get('exitCode') != 0
            or exit_result.get('error')):
        reasons.append('WRAPPER_OR_NATIVE_EXIT_REJECTED:%r'
                       % (exit_result.get('error') or exit_result.get('exitCode'),))
    if (record.get('scope') != 'READ_ONLY_CONTEXT_RECEIPT'
            or record.get('selfTestOnly') is not False
            or record.get('unhooked') is not True
            or record.get('activeCallbacks') != 0
            or record.get('callbackCount') != 1
            or record.get('pid') != session.get('pid')
            or record.get('tid') != session.get('tid')):
        reasons.append('CALLBACK_DRAIN_OR_IDENTITY')

    # (6) The level identity, out of THIS receipt and the pinned decoder.  There is no
    #     default and no fallback value: an unread identity is a refusal.
    observed = snapshot.get('levelObservation')
    level_id = observed.get('levelId') if isinstance(observed, dict) else None
    if not isinstance(observed, dict) or observed.get('verified') is not True:
        reasons.append('LEVEL_NOT_OBSERVED')
    if type(level_id) is not int or not 0 < level_id < 2 ** 32:
        reasons.append('LEVEL_IDENTITY_NOT_A_UINT32:%r' % (level_id,))
    elif level_id == QUEUE_CLAIM_LEVEL_ID:
        reasons.append('LEVEL_IDENTITY_IS_CLAIM_PLACEHOLDER')
    if type(level_id) is int and reply.get('levelId') != level_id:
        reasons.append('QUEUE_REPLY_LEVEL_DISAGREES:%r' % (reply.get('levelId'),))

    # (7) The SAME acceptance the default transport demands, unmodified.
    if acceptance.get('ok') is not True:
        reasons.extend(acceptance.get('reasons') or ['READONLY_ACCEPTANCE_REJECTED'])

    verified = not reasons
    helper = reply.get('helper') or {}
    result = dict(ok=verified, kind='current-level-observation', transport='elevated-queue',
                  handle=run.name, run=str(run),
                  levelId=level_id if verified else None,
                  levelObservation=observed,
                  entities=acceptance.get('entityCount'),
                  acceptancePath=str(run / 'readonly-acceptance.json'),
                  snapshotPath=str(run / 'readonly-snapshot.json'),
                  receiptPath=str(run / 'stdout.jsonl'),
                  receiptSha256=sha256_file(run / 'stdout.jsonl'),
                  sessionPath=str(session_path), sessionSha256=sha256_file(session_path),
                  queueRequestId=helper.get('requestId'), queueHelperPid=helper.get('pid'),
                  probeClaimLevelId=QUEUE_CLAIM_LEVEL_ID, probeClaimIsAuthoritative=False,
                  # MEASURED (2026-10-02): the helper's own reply carries ok=false and
                  # 'Observed current editing level is unverified or differs from requested
                  # level', because scene_cli compares the OBSERVED id against the claimed
                  # expectation (scene_cli.py:575) and the placeholder is not a level.  That
                  # reply is recorded verbatim and is not the verdict: the verdict is this
                  # run's own readonly acceptance below, which was ok=True with no reasons.
                  helperReplyOk=reply.get('ok'), helperReplyLevelId=reply.get('levelId'),
                  helperReplyError=reply.get('error'),
                  readonlyAcceptanceOk=acceptance.get('ok'),
                  artifactsMaterialised=False,
                  createdUtc=datetime.now(timezone.utc).isoformat(),
                  notes=('levelId comes from this run\'s own native receipt via the pinned '
                         'level-observation decoder, not from the caller, the config or the '
                         'wire placeholder; probeClaimLevelId is the placeholder the closed '
                         'helper schema requires and is never the answer; handle is the run '
                         'directory name and is re-resolved by this program only'))
    if not verified:
        result['reasons'] = reasons
    return result


def discover_via_queue(session_path=None, *, output_root=DEFAULT_OUTPUT_ROOT,
                       queue_dir=None, timeout=QUEUE_SEND_TIMEOUT, large_scene=False) -> dict:
    """Find the current level through the resident helper.  Raises no prompt.

    There is deliberately no branch in this function that can reach
    ``emit_launcher``/``run_wrapper``: if the queue cannot be used, the run is refused
    with the reason, because a discovery that quietly falls back to UAC would put an
    elevation prompt on screen during an unattended run.
    """
    out_root = Path(output_root).resolve()
    profiles.require(out_root.is_relative_to(profiles.ROOT / '.runtime'),
                     'OUTPUT_ROOT_MUST_BE_PROJECT_RUNTIME')
    profiles.require(type(timeout) in (int, float) and 0 < timeout <= 1800,
                     'QUEUE_TIMEOUT_OUT_OF_RANGE')
    queue = Path(QUEUE_DEFAULT_DIR if queue_dir is None else queue_dir).resolve()
    profiles.require(queue.is_relative_to(profiles.ROOT / '.runtime/editor-bridge'),
                     'QUEUE_DIR_MUST_BE_PROJECT_BRIDGE')
    # Reads the pinned executable from disk only; no process, no injection, no elevation.
    profiles.verify_disk(profiles.load_profile())

    if session_path is None:
        fresh = out_root / 'sessions' / ('session-%s.json'
                                         % datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        session_path = discover_session(fresh)
        session_source = 'discovered-this-run'
    else:
        session_path = Path(session_path).resolve()
        profiles.require(session_path.is_relative_to(profiles.ROOT / '.runtime'),
                         'SESSION_MUST_BE_PROJECT_RUNTIME')
        session_source = 'explicit'
    # The identity is re-derived from Windows immediately before the request: the run
    # being judged below is the one the helper compiles against THIS identity.
    session = profiles.validate_session(read_json(session_path))
    session_checked_utc = datetime.now(timezone.utc).isoformat()

    request = build_queue_request(session_path, large_scene=large_scene)
    submitted_at = datetime.now(timezone.utc)
    reply = queue_send(request, queue_dir=queue, timeout=timeout)
    run = resolve_queue_run(reply.get('run'))
    evidence = decode_receipt(run)
    result = evaluate_queue_observation(run, evidence, reply, session_path=session_path,
                                       session=session, submitted_at=submitted_at)
    result.update(sessionSource=session_source, sessionRevalidatedUtc=session_checked_utc,
                  queuePath=str(queue))
    if result['ok']:
        # Leave behind the same two artifacts the default transport leaves, using the
        # pinned writer.  It re-decodes independently; a disagreement is a refusal, not
        # something to patch up.
        materialised = readonly.decode_run(run)
        if (materialised.get('ok') is not True
                or (materialised.get('levelObservation') or {}).get('levelId') != result['levelId']):
            result.update(ok=False, levelId=None,
                          reasons=['MATERIALISED_ACCEPTANCE_DISAGREES']
                          + (materialised.get('reasons') or []))
        else:
            result['artifactsMaterialised'] = True
    record_path = run / 'current-level-observation.json'
    if record_path.exists():
        result['recordNotRewritten'] = str(record_path)
    else:
        write_json(record_path, result)
    return result


def analyze_receipt(run_path) -> dict:
    """Diagnose an EXISTING run directory.  Read-only; never an observation.

    A stored receipt can be diagnosed and can never be promoted into "the level that is
    open now" -- that is precisely the hole a historical id must not fill.  So ``ok`` is
    always false here, and ``analysisOk`` reports only whether the receipt decoded.
    """
    run = resolve_any_run(run_path)
    try:
        evidence = decode_receipt(run)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        return dict(ok=False, kind='queued-receipt-analysis', analysisOk=False,
                    notACurrentLevelObservation=True, run=str(run),
                    error='%s: %s' % (type(error).__name__, error),
                    retryAttempted=False)
    prepared, snapshot = evidence['prepared'], evidence['snapshot']
    acceptance = evidence['acceptance']
    observed = snapshot.get('levelObservation')
    level_id = observed.get('levelId') if isinstance(observed, dict) else None
    extensions = sorted(key for key in prepared if key.endswith('ProfileSha256')
                        and key != 'levelObservationProfileSha256')
    session = prepared.get('session') or {}
    recorded = None
    recorded_path = run / 'readonly-acceptance.json'
    if recorded_path.is_file():
        # The run's own record, written by decode_run while that run was current.  It is
        # quoted, never re-derived: this mode does not write, and the extension verdicts
        # it carries cannot be reproduced without decode_run's writers.
        try:
            stored = read_json(recorded_path)
            recorded = dict(path=str(recorded_path), ok=stored.get('ok'),
                            reasons=stored.get('reasons'),
                            entityCount=stored.get('entityCount'))
        except (OSError, ValueError) as error:
            recorded = dict(path=str(recorded_path), unreadable=str(error))
    return dict(ok=False, kind='queued-receipt-analysis', analysisOk=True,
                notACurrentLevelObservation=True, run=str(run), handle=run.name,
                recordedAcceptance=recorded,
                levelObservation=observed, observedLevelId=level_id,
                observedLevelIdIsUint32=bool(type(level_id) is int and 0 < level_id < 2 ** 32),
                entityCount=acceptance.get('entityCount'),
                readonlyAcceptanceOk=acceptance.get('ok'),
                readonlyAcceptanceReasons=acceptance.get('reasons'),
                readonlyAcceptanceScope=('base-receipt-only: this mode never writes, so the '
                                        'extension verdicts a --reopen-prerequisites receipt '
                                        'also carries are not re-derived here'
                                        if extensions else 'base-receipt'),
                extensionBindings=extensions,
                receiptPath=str(run / 'stdout.jsonl'),
                receiptSha256=sha256_file(run / 'stdout.jsonl'),
                sessionPid=session.get('pid'), sessionTid=session.get('tid'),
                exitExecuted=evidence['exit'].get('executed'),
                exitCode=evidence['exit'].get('exitCode'),
                notes=('analysis only: a stored receipt is never promoted to a current-level '
                       'observation; run without --analyze-run to observe the live level'))


def parse_any_handle(text: str) -> Path:
    """Resolve a handle in EITHER run root, requiring exactly one match.

    A handle is a run DIRECTORY NAME.  Both roots keep their own containment check --
    this only decides which one the name refers to, and refuses an ambiguity instead of
    silently preferring one, which is how a handle would otherwise resolve to a run the
    caller did not mean.
    """
    candidate = Path(text)
    roots = [(DEFAULT_OUTPUT_ROOT / 'runs').resolve(), queue_run_root()]
    matches = []
    if candidate.is_absolute():
        run = candidate.resolve()
        matches = [run for root in roots if run.is_dir() and run.is_relative_to(root)]
    else:
        for root in roots:
            run = (root / candidate).resolve()
            if run.is_dir() and run.is_relative_to(root):
                matches.append(run)
    if len(matches) != 1:
        raise ValueError('HANDLE_AMBIGUOUS_OR_UNKNOWN:%s:matches=%d' % (text, len(matches)))
    return matches[0]


def discover(session_path=None, *, output_root=DEFAULT_OUTPUT_ROOT, queue_dir=None,
             queue_timeout=QUEUE_SEND_TIMEOUT, large_scene=False) -> dict:
    # The transport is chosen before anything else happens.  With --queue-dir there is no
    # elevation anywhere on this path; without it nothing below changes.
    if queue_dir is not None:
        return discover_via_queue(session_path, output_root=output_root,
                                 queue_dir=queue_dir, timeout=queue_timeout, large_scene=large_scene)
    out_root = Path(output_root).resolve()
    profiles.require(out_root.is_relative_to(profiles.ROOT / '.runtime'),
                     'OUTPUT_ROOT_MUST_BE_PROJECT_RUNTIME')

    if session_path is None:
        fresh = out_root / 'sessions' / ('session-%s.json' % datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        session_path = discover_session(fresh)
        session_source = 'discovered-this-run'
    else:
        session_path = Path(session_path).resolve()
        session_source = 'explicit'

    # Builds the one-shot probe.  This compiles; it does not elevate, inject or call a
    # game method.  The generated wrapper is the only thing that is ever launched.
    prepared = readonly.prepare(session_path, output_root=out_root / 'runs',
                                ttl_seconds=PREPARATION_TTL_SECONDS, large_scene=large_scene)
    run = Path(prepared['run']).resolve()
    # Refuse BEFORE spending an elevation request while a prompt is already on screen.
    # MEASURED (2026-09-30): three attempts produced two stacked prompts and two blocked
    # launchers, and none of the later requests could proceed because Start-Process blocks
    # behind the pending prompt. A run that cannot be shown is worse than no run: it burns
    # an operator's attention and leaves another blocked launcher behind.
    pending = pending_elevation_prompts()
    if pending > 0:
        raise RuntimeError(
            'ELEVATION_ALREADY_PENDING: %d Windows elevation prompt(s) are already on '
            'screen, so a new request cannot be shown. No prompt was raised by this run and '
            'the generated probe was not launched. Dismiss the pending prompt(s) first, then '
            're-run. Preserved run: %s' % (pending, run))
    # The read-only bootstrap always emits this exact name (build_readonly_profile.emit_wrapper).
    wrapper = run / 'invoke-readonly-probe.ps1'
    profiles.require(wrapper.is_file(), 'READONLY_WRAPPER_MISSING:' + str(wrapper))
    wrapper_sha256 = prepared['hashes'][wrapper.name]

    exit_result = run_wrapper(run, wrapper, wrapper_sha256)
    if exit_result.get('executed') is not True or exit_result.get('exitCode') != 0 or exit_result.get('error'):
        raise RuntimeError('probe did not execute cleanly; preserved run: %s' % run)

    acceptance = readonly.decode_run(run)
    snapshot = read_json(run / 'readonly-snapshot.json')
    observed = snapshot.get('levelObservation') or {}

    verified = bool(acceptance.get('ok')) and observed.get('verified') is True and \
        type(observed.get('levelId')) is int and observed.get('levelId') > 0

    handle = run.name
    result = dict(ok=verified, kind='current-level-observation',
                  handle=handle, run=str(run),
                  levelId=observed.get('levelId') if verified else None,
                  levelObservation=observed,
                  entities=acceptance.get('entityCount'),
                  acceptancePath=str(run / 'readonly-acceptance.json'),
                  snapshotPath=str(run / 'readonly-snapshot.json'),
                  receiptPath=str(run / 'stdout.jsonl'),
                  receiptSha256=sha256_file(run / 'stdout.jsonl'),
                  sessionPath=str(session_path), sessionSource=session_source,
                  sessionSha256=sha256_file(session_path),
                  wrapperName=wrapper.name, wrapperSha256=wrapper_sha256,
                  createdUtc=datetime.now(timezone.utc).isoformat(),
                  notes=('levelId comes from the native receipt, not from any caller or config; '
                         'handle is the run directory name and is re-resolved by this program only'))
    if not verified:
        result['reasons'] = acceptance.get('reasons')
    write_json(run / 'current-level-observation.json', result)
    return result


def show(handle: str) -> dict:
    """Re-read a previous observation.  Launches nothing, on either transport."""
    run = parse_any_handle(handle)
    record = read_json(run / 'current-level-observation.json')
    if not (run / 'stdout.jsonl').is_file() or sha256_file(run / 'stdout.jsonl') != record.get('receiptSha256'):
        raise ValueError('OBSERVATION_RECEIPT_CHANGED: %s' % run)
    record['handleRechecked'] = True
    return record


def main(argv=None) -> int:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path,
                        help='Fresh session record; omit to discover process identity first')
    parser.add_argument('--output-root', type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument('--large-scene', action='store_true', help='Observe a complete v2 large scene')
    parser.add_argument('--show', metavar='HANDLE',
                        help='Re-read a previous observation by handle; launches nothing')
    parser.add_argument('--queue-dir', type=Path,
                        help='Discover through the already-elevated resident helper queue '
                             'instead of a UAC launch.  This mode raises no prompt and an '
                             'unusable queue is a refusal, never a fallback to UAC')
    parser.add_argument('--queue-timeout', type=float, default=QUEUE_SEND_TIMEOUT,
                        help='seconds to wait for the helper reply (default %d)'
                             % QUEUE_SEND_TIMEOUT)
    parser.add_argument('--analyze-run', type=Path, metavar='RUN',
                        help='Decode an existing run directory read-only.  Never an '
                             'observation: ok is always false and analysisOk reports '
                             'whether the receipt decoded')
    args = parser.parse_args(argv)
    try:
        if args.analyze_run is not None:
            if args.show or args.queue_dir is not None:
                raise ValueError('ANALYZE_RUN_IS_OFFLINE_ONLY: it neither re-reads a handle '
                                 'nor queues a request')
            result = analyze_receipt(args.analyze_run)
        elif args.show:
            if args.queue_dir is not None:
                raise ValueError('SHOW_LAUNCHES_NOTHING: --show re-reads a recorded '
                                 'observation and does not queue a request')
            result = show(args.show)
        else:
            result = discover(args.session, output_root=args.output_root,
                              queue_dir=args.queue_dir, queue_timeout=args.queue_timeout, large_scene=args.large_scene)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # A bare message is not enough to place a fault in this chain: the caller only
        # sees the outermost entry point, and the same text can come from several
        # stages.  The innermost frames are included -- file name, line and the source
        # text of the failing statement -- so a failure names both the stage and the
        # operation.  Measured need: a TypeError in this chain was reported only as
        # "can only concatenate str (not NoneType) to str", with no way to tell which
        # of a dozen concatenations it was.
        import traceback
        frames = traceback.extract_tb(error.__traceback__)
        where = ['%s:%d in %s' % (Path(frame.filename).name, frame.lineno, frame.name)
                 for frame in frames[-3:]]
        source = [frame.line for frame in frames[-3:] if frame.line]
        result = dict(ok=False, kind='current-level-observation',
                      error='%s: %s' % (type(error).__name__, error),
                      failedAt=where, failedSource=source, retryAttempted=False)
    print(json.dumps(result, ensure_ascii=False))
    if args.analyze_run is not None:
        # --analyze-run never claims an observation, so its exit code reports the
        # analysis while `ok` in the document stays false to say so.
        return 0 if result.get('analysisOk') else 2
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
