"""Project-local MCP stdio entry point for the bounded scene business operations.

This is the business contract the creation AI is allowed to see.  It reuses the SAME
execution layer the CLI uses -- it does not re-implement validation and it never
widens it:

    author.py            one reviewed native request per requestId, journaled
    scene_cli.py         the closed queue request and the single claim
    orchestrate_write_review.py
                         DERIVES the coordinator review from raw materials
    discover_current_level.py
                         the only way an opaque level handle is minted

WHAT THE MODEL SUPPLIES: only business parameters -- a level handle, a template id,
a transform, a requestId, and for cleanup a list of entity ids.  WHAT STAYS IN THE
EXECUTION LAYER: the elevated queue directory, the helper PID, the reviewed baseline
run, the recovered formal-save copy, the derived review record, process identity and
every raw native receipt.  The queue is resolved from this project's own pointer and
re-validated (heartbeat age, deadline, elevated flag, native-scene enabled/blocked,
pin digest) before any dispatch; it is never a tool argument.

EVERY TOOL RESOLVES ITS STAGE INDEPENDENTLY.  ``liveReadback``, ``persistence``,
``reopen``, ``runtime`` and ``cleanup`` are separate fields with separate statuses,
because saving successfully says nothing about whether the level will reload, and a
clean readback says nothing about what reached the disk.  A stage this server does not
perform is reported ``not-run`` with a reason -- never as ``pass``.

THIS IS AN APPLICATION CAPABILITY BOUNDARY, NOT OPERATING-SYSTEM ISOLATION, and one
level of it is only as strong as the launcher: a client that can start other processes
can start other servers.  See docs/entity-create/MCP-BUSINESS-CONTRACT.md.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import uuid

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / '.runtime/mcp-venv/Scripts/python.exe')
#: The interpreter that can deserialise the save format (google.protobuf).  The MCP
#: venv cannot, so verifier subprocesses are launched with this one when present.
PROTOBUF_PYTHON = str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Python/Python313/python.exe')
DISCOVERY_ROOT = ROOT / '.runtime/game-executor/current-level-discovery'
EVIDENCE_ROOT = ROOT / '.runtime/game-executor/mcp-business'
POINTER = ROOT / '.runtime/editor-bridge/current-elevated-session.json'
BACKUP_ROOT = ROOT / '.runtime/editor-bridge/backups'
#: The bottom-layer ledger written by ``tools/authoring/author.py``: one directory per
#: requestId, holding ``claim.json`` (the fingerprint and the whole bound command) and,
#: once the dispatch has been recorded, ``result.json`` (the receipt).  It -- not this
#: server's own memory -- is the authority for "has this requestId already been sent".
JOURNAL_ROOT = ROOT / '.runtime/authoring/requests'
#: The T06 / DS-08 business ledger this server writes its business rows into.
#:
#: Deliberately the SAME directory the Cordis lifecycle port reads:
#: ``plugins/miliastra/src/ledger-port.ts``'s ``defaultLedgerRoot(projectRoot)`` returns
#: ``<projectRoot>/.runtime/business-ledger``, and ``plugins/miliastra/src/index.ts``
#: hands exactly that to the port.  One row set, two readers -- this server writes it,
#: the T03 permit (``beginOperation``) reads it.  If the two ever named different
#: directories the permit would read an empty ledger and grant every dispatch, which is
#: precisely the silent bypass this constant exists to close.  Keep them in step.
LEDGER_ROOT = ROOT / '.runtime/business-ledger'
#: Bound on any single cleanup request, matching the native route's own limit.
MAX_CLEANUP_IDS = 64
#: Native snapshot capacity; a create is refused when the level already holds this many.
MAX_ENTITIES = 4096

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def _repair_inherited_environment():
    """Restore the Windows variables the pinned toolchain needs but MCP clients drop.

    MEASURED 2026-09-29: the MCP Python SDK's stdio client starts a server with a
    WHITELIST of inherited variables --
    APPDATA, HOMEDRIVE, HOMEPATH, LOCALAPPDATA, PATH, PATHEXT, PROCESSOR_ARCHITECTURE,
    SYSTEMDRIVE, SYSTEMROOT, TEMP, USERNAME, USERPROFILE -- and nothing else.
    ``ProgramFiles(x86)`` is not on it.  ``build_readonly_profile.compile_probe`` reads
    ``os.environ['ProgramFiles(x86)']`` to locate vswhere/MSVC, so the discovery step
    died with a bare KeyError('ProgramFiles(x86)') even though the launching shell had
    the variable.  Reading it back from the registry keeps the server working no matter
    which client started it; a client cannot be trusted to pass the right environment.
    """
    missing = [name for name in ('ProgramFiles(x86)', 'ProgramFiles', 'ProgramData')
               if name not in os.environ]
    if not missing:
        return {}
    repaired = {}
    try:
        import winreg
        locations = {
            'ProgramFiles(x86)': (r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion',
                                  'ProgramFilesDir (x86)'),
            'ProgramFiles': (r'SOFTWARE\Microsoft\Windows\CurrentVersion', 'ProgramFilesDir'),
            'ProgramData': (r'SOFTWARE\Microsoft\Windows\CurrentVersion', 'CommonFilesDir'),
        }
        for name in missing:
            subkey, value = locations[name]
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as handle:
                found, _ = winreg.QueryValueEx(handle, value)
            if name == 'ProgramData':
                continue          # CommonFilesDir is not ProgramData; leave it alone.
            os.environ[name] = found
            repaired[name] = found
    except Exception as exc:      # noqa: BLE001 - report, never crash the server on start
        repaired['error'] = '%s: %s' % (type(exc).__name__, exc)
    return repaired


ENVIRONMENT_REPAIRS = _repair_inherited_environment()

mcp = FastMCP('miliastra-entity-create', instructions=(
    'Bounded scene business tools for the running Genshin editor. Discover the current level to get an '
    'opaque handle; read entities; create one entity from a supported template; save the level; reconcile '
    'an operation by requestId; clean up entities this run created. Every create and save is independently '
    'reviewed and journaled before dispatch. Stage statuses are separate: a successful readback does not '
    'mean the disk persisted, and a successful save does not mean the level reloads.'))


# --------------------------------------------------------------------------- #
# Execution layer -- none of this is reachable from a tool argument
# --------------------------------------------------------------------------- #

class BusinessError(RuntimeError):
    """A refusal with a stable code.  Raised before any dispatch or not at all."""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def _stage(status, **fields):
    payload = {'status': status}
    payload.update(fields)
    return payload


def persistence_from_save_diff(save_diff):
    """``persistence`` as a T05 COMPATIBILITY MAPPING of ``saveDiff`` -- never its own truth.

    TOOL-CONTRACT.md:55: the unified stage is ``stages.saveDiff``; ``persistence`` is an input
    alias for it and must not carry a second success story.  Deriving it from the differential
    is what stops a native status 0 from being read as "the disk persisted".

    W09, re-derived by the main line 2026-10-05 onto the W08 text: W09's own patch replaced the
    ``mw_scene_save_level`` return block, but W08 had already rewritten that region to source
    ``saveDiff`` from the post-write manifest (``verify_saved_case_for_save``).  The fold below
    is W09's intent applied to W08's differential.  W09's parallel ``verify_save_diff`` was
    deliberately NOT brought across: it computed the same differential by a second route, and
    two routes to one truth is the split this fold exists to close.
    """
    fields = {'detail': {'saveDiff': (save_diff or {}).get('detail')}}
    if (save_diff or {}).get('status') != 'pass':
        fields['reason'] = (save_diff or {}).get('reason')
    return _stage((save_diff or {}).get('status', 'unknown'), **fields)

def saved_from_save_diff(save_diff):
    """``saved`` as a statement about the DISK -- R19 / contract STATE-2.

    ``saved`` is a success-shaped boolean: contract.json STATE-2 says such a boolean is
    derived from counted evidence, never computed independently.  ``nativeStatus == 0`` is
    a DISPATCH fact -- it says the write call was accepted -- so it is reported under
    ``nativeDispatched`` and is NEVER turned into ``saved``.  This is the same fold the
    ``persistence`` compatibility mapping uses, so the two can no longer disagree:

        saveDiff pass  -> True   (the disk holds the content)
        saveDiff fail  -> False  (the differential proves it does not)
        anything else  -> None   (not established -- never a silent False)
    """
    status = (save_diff or {}).get('status')
    if status == 'pass':
        return True
    if status == 'fail':
        return False
    return None


def _cleanup_material_paths_outside_runtime(manifest):
    """The material paths this manifest names that do NOT resolve inside .runtime.

    R211.  ``backend/cleanup_ownership_legs.py`` resolves a material path with
    ``path if path.is_absolute() else (ROOT / path)`` -- there is no containment anywhere
    on that path, so a ``round-materials.json`` whose ``freshReadback.path`` or
    ``preBaseline.path`` names any readable file makes THAT file "what is present now" or
    "what existed before", which are the two inputs ownership is decided from.  The
    independent service already refuses this (``cleanup_service._material_path_problem`` ->
    ``MATERIAL_PATH_NOT_ALLOWED``, ``cleanup_service.py:1761``); the business entry, which
    is the route that actually deletes, did not.

    The boundary is the project's own, and it is spelled the same way ``load_handle``
    spells it: absolute, inside ``ROOT/.runtime``, and inside it again after ``resolve()``
    so a symlink cannot move the file out from under the check.

    Returns a list of ``{field, path, reason}``; empty means every named path is inside.
    """
    runtime = ROOT / '.runtime'
    try:
        runtime_resolved = runtime.resolve()
    except OSError:
        return [{'field': '<runtime>', 'path': str(runtime), 'reason': 'RUNTIME_UNRESOLVABLE'}]

    named = []

    def take(field, value):
        if isinstance(value, str) and value.strip():
            named.append((field, value))
        elif isinstance(value, dict) and isinstance(value.get('path'), str) and value['path'].strip():
            named.append((field, value['path']))

    take('preBaseline', manifest.get('preBaseline'))
    take('freshReadback', manifest.get('freshReadback'))
    for index, receipt in enumerate(manifest.get('receipts') or []):
        take('receipts[%d]' % index, receipt)

    problems = []
    for field, raw in named:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        reason = None
        if not candidate.is_relative_to(runtime):
            reason = 'OUTSIDE_PROJECT_RUNTIME'
        else:
            try:
                if not candidate.resolve().is_relative_to(runtime_resolved):
                    reason = 'RESOLVES_OUTSIDE_PROJECT_RUNTIME'
            except OSError:
                reason = 'UNRESOLVABLE'
            if reason is None and not candidate.is_file():
                reason = 'MATERIAL_PATH_MISSING'
        if reason is not None:
            problems.append({'field': field, 'path': str(candidate), 'reason': reason})
    return problems


def _cleanup_ids_attempted_with_unknown_outcome(evidence_root, round_id, level_id, ids, request_id):
    """Ids in ``ids`` that an EARLIER request of THIS round dispatched and never resolved.

    R212.  ``cleanup_dispatch_journal.consult`` is scoped to one ``(round_id, requestId)``
    directory, and ``_cleanup_dispatch_key`` deliberately treats a different id set as a
    different request (that is what makes batching work).  Both are right in isolation and
    wrong together: an id whose dispatch was ATTEMPTED with no outcome recorded -- the state
    ``CLEANUP_DISPATCH_OUTCOME_UNKNOWN`` exists to refuse -- can be re-cited in a smaller
    batch, or under a fresh ``cleanupRequestId``, and then lands on a request directory the
    journal has never seen.  It is claimed, it is dispatched, and the id is sent to the
    native delete a second time.

    That contradicts this route's own stated principle, which its OUTCOME_UNKNOWN refusal
    spells out: an unobserved write is never re-sent.  The principle is about the ID, not
    about the request that happened to carry it, so it is enforced here across requests.

    Only claims with ``dryRun: false`` count: a dry run deletes nothing, so an unobserved
    dry run is not an unobserved write.  Claims naming another level are skipped -- ids are
    reused across levels, and a level's ids are not evidence about another level's.

    Returns ``[{requestId, ids}]``, most recent first; empty means every id is safe to send.
    """
    journal_root = Path(evidence_root) / 'cleanup' / round_id / 'dispatch-journal'
    if not journal_root.is_dir():
        return []
    wanted = {int(value) for value in ids}
    hits = []
    for entry in sorted(journal_root.iterdir()):
        if not entry.is_dir() or entry.name == request_id:
            continue
        if (entry / 'result.json').is_file():
            continue                      # an outcome exists; the journal has reconciled it
        claim_path = entry / 'claim.json'
        if not claim_path.is_file():
            continue                      # no claim: consult() refuses this by name already
        try:
            claim = _read_json(claim_path)
        except (OSError, ValueError, KeyError):
            continue
        command = claim.get('command') or {}
        if command.get('dryRun'):
            continue                      # a dry run dispatched nothing to reconcile
        claim_level = claim.get('levelId')
        if claim_level is not None and level_id is not None and claim_level != level_id:
            continue
        dispatched = {int(value) for value in (command.get('ids') or [])}
        overlap = sorted(wanted & dispatched)
        if overlap:
            hits.append({'requestId': entry.name, 'ids': overlap,
                         'claimedAtUtc': claim.get('claimedAtUtc')})
    return hits


def _cleanup_verdict_stage(reply, dry_run):
    """The ``cleanup`` stage for ``mw.scene.cleanupOwned``, judged by the delete's EFFECT.

    R20-A13.  The delete route answers with a DISPATCH ACK and says so itself: the adapter
    returns ``status="delete-requested-readback-pending"`` with ``gameEffectVerified=false``
    and the notice "Native true is dispatch only and false may mean no request. Observe the
    model and the formal file before any further action."
    (``tools/editor-bridge/Adapter/OwnedEntityDelete.cs:135-139``; the same shape is on
    every real receipt under
    ``.runtime/verification/entity-create-full-run/<runId>/cases/<case>/<attempt>/cleanup-receipt.json``
    -- measured: 12 of 12 carry ``ok=true``, ``gameEffectVerified=false`` and NO
    ``residualEntityIds`` key at all.)

    ``reply['ok']`` is therefore a fact about the dispatch and never about the level, so a
    ``pass`` derived from ``reply['ok'] is True`` alone claimed an effect nothing observed.
    That is the same defect the parameter driver carried until R19-A10, where it laundered
    twelve cleanup passes out of dispatch acks.

    So this stage may pass only on an independent post-delete observation: the reply must
    state the effect was verified AND carry the residual id list.  Anything less is
    ``blocked``, with the reason naming what is missing.  A missing key is never a pass, and
    a dry run deletes nothing, so its stage is ``not-run`` rather than ``pass``.
    """
    if dry_run:
        return _stage('not-run',
                      reason='dry-run mapping only; nothing was deleted, so there is no '
                             'cleanup effect to observe')
    if not isinstance(reply, dict) or reply.get('ok') is not True:
        return _stage('fail', reason='the delete dispatch was not accepted')
    if reply.get('gameEffectVerified') is not True:
        stated = reply.get('gameEffectVerified') if 'gameEffectVerified' in reply else 'absent'
        return _stage('blocked', reason=(
            'the delete was requested but its effect is UNVERIFIED: the reply is a dispatch '
            'ack (status=%r, gameEffectVerified=%r), so no id is shown to be gone. An '
            'independent post-delete entity-inspect must show the removed ids absent and the '
            'unrelated ids still present before this stage may pass.'
            % (reply.get('status'), stated)))
    if not isinstance(reply.get('residualEntityIds'), list):
        return _stage('blocked', reason=(
            'the reply states that the effect was verified but carries no residual id list, '
            'so no id is shown to be gone'))
    if reply['residualEntityIds']:
        return _stage('fail', reason='the level still holds %r after the delete'
                                     % (reply['residualEntityIds'],))
    return _stage('pass', detail='the delete reply states gameEffectVerified=true and an '
                                 'empty residual id list')


def _replayed_persistence(receipt, run, native_status):
    """``persistence`` for a REPLAYED save -- fold from the recorded differential, or say it is
    not verified.  NEVER mint a pass from the native dispatch ack (R04, 2026-10-05).

    The live path folds ``persistence`` from ``saveDiff``.  This path used to do the opposite:
    ``receipt['ok'] is True and native_status == 0`` is a DISPATCH fact -- it says the write was
    accepted -- and turning it into ``pass`` made the same save read differently depending on
    whether it was the first call or a replay.  A replay also cannot repair the gap by looking
    at the level again: that is a later observation of a level that has since moved on, which is
    the very thing ``_replayed_readback`` refuses to do.

    So if the original receipt carries a differential, fold from it; otherwise the honest
    stage is ``blocked`` with the reason naming why.  A native status 0 on its own is never a
    persistence verdict on this path.
    """
    recorded = receipt.get('saveDiff') if isinstance(receipt, dict) else None
    if isinstance(recorded, dict) and recorded.get('status'):
        return _stage(recorded['status'],
                      detail={'saveDiff': recorded.get('detail'), 'replayed': True},
                      evidenceRef=[run] if run else [])
    return _stage('blocked',
                  reason=('the original call recorded no save differential, and a replay cannot '
                          're-derive one without inspecting the level again -- which would be a '
                          'later observation of a level that has since moved on. The native ack '
                          '(nativeStatus=%r) says only that the write was dispatched.' % native_status),
                  evidenceRef=[run] if run else [])


def _ok(method, **fields):
    body = {'ok': True, 'method': method, 'backendKind': 'project-native-scene',
            'internalBridge': 'project-built, not an official API'}
    body.update(fields)
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(body, ensure_ascii=False))],
                          structuredContent=body)


def _fail(method, exc):
    if isinstance(exc, BusinessError):
        code, message, extra = exc.code, exc.message, exc.extra
    else:
        code, message, extra = 'BUSINESS_ERROR', '%s: %s' % (type(exc).__name__, exc), {}
    body = {'ok': False, 'method': method, 'backendKind': 'project-native-scene',
            'error': dict(extra, code=code, message=message),
            'liveReadback': _stage('not-run'), 'persistence': _stage('not-run'),
            'reopen': _stage('not-run'), 'runtime': _stage('not-run'),
            'cleanup': _stage('not-run'), 'retryAttempted': False}
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(body, ensure_ascii=False))],
                          structuredContent=body, isError=True)


def _read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _request_id_ok(value):
    return isinstance(value, str) and 1 <= len(value) <= 80 and \
        value[0].isalnum() and all(c.isalnum() or c in '_-' for c in value)


def _require_request_id(value):
    if not _request_id_ok(value):
        raise BusinessError('REQUEST_ID_INVALID',
                            'requestId must be 1..80 letters, digits, underscore or hyphen')
    return value


#: The parts of a scene command that are the CALLER's business identity: the target and
#: the parameters.  Everything else in ``author.py``'s bound command -- the session,
#: review and baseline paths, and the elevated queue directory -- is execution-layer
#: material this server mints or resolves afresh on every attempt, so it can never be
#: part of a replay comparison and must never turn a replay into a conflict.  The bottom
#: layer still fingerprints all of it; that is precisely why the ledger has to be
#: consulted here, before any of it is derived (G01 D19).
BOUND_BUSINESS_FIELDS = ('backend', 'action', 'levelId', 'templateId',
                         'position', 'rotation', 'scale')


def business_binding(command):
    """The model-visible identity of a scene command, normalized for comparison.

    ``levelId`` is compared as text so an int and its string form cannot look like two
    different targets; the vectors are compared numerically, so ``-0.0`` and ``0.0`` are
    one placement rather than two commands.
    """
    binding = {}
    for field in BOUND_BUSINESS_FIELDS:
        value = command.get(field)
        if field == 'levelId' and value is not None:
            value = str(value)
        elif isinstance(value, list):
            value = [float(v) for v in value]
        binding[field] = value
    return binding


def consult_journal(request_id, binding):
    """Consult the ledger BEFORE any execution material is derived.

    Returns the journaled receipt when this requestId was already answered, or ``None``
    when it was never claimed and this attempt may build and dispatch.  Refusals are
    raised rather than returned, so no caller can mistake one for a receipt.

    The caller's handle is resolved before this runs because the conflict check compares
    target identity; a handle whose own evidence no longer verifies fails closed there.
    """
    directory = JOURNAL_ROOT / request_id
    if not directory.is_dir():
        return None                       # never claimed: there is nothing to replay
    claim_path = directory / 'claim.json'
    if not claim_path.is_file():
        raise BusinessError('REQUEST_INCOMPLETE_CLAIM',
                            'a journal directory exists without its claim, so there is no evidence '
                            'of what was requested and nothing may be resent',
                            requestId=request_id, journal=str(directory))
    recorded = business_binding(_read_json(claim_path).get('command') or {})
    if recorded != binding:
        raise BusinessError('REQUEST_ID_CONFLICT',
                            'requestId %r is already bound to a different target or parameters'
                            % request_id, requestId=request_id, journal=str(directory),
                            recordedBinding=recorded, suppliedBinding=binding)
    receipt_path = directory / 'result.json'
    if not receipt_path.is_file():
        raise BusinessError('REQUEST_OUTCOME_UNKNOWN',
                            'this requestId was claimed but no receipt was written: the outcome is '
                            'unknown, so reconcile from the evidence instead of resending it',
                            requestId=request_id, journal=str(directory))
    return _read_json(receipt_path)


def _replayed_readback(receipt, backend, *, detail):
    """A liveReadback stage for a replayed receipt, with the recorded run as evidence.

    The level is NOT inspected again on this path: a second inspection would be a later
    observation of a level that has since moved on, which is exactly what "replay the
    original receipt" must not silently substitute for.  With no run to cite there is no
    evidence, and an evidence-free ``pass`` would be a false claim, so it is ``unknown``.
    """
    run = backend.get('run')
    if receipt.get('ok') is not True:
        return _stage('fail', reason='the original dispatch was not accepted',
                      evidenceRef=[run] if run else [])
    if not run:
        return _stage('unknown', reason='the recorded receipt names no run, so no evidence can be '
                                        'cited for the original readback')
    return _stage('pass', evidenceRef=[run], detail=detail)


def replay_create_result(level, request, request_id, receipt):
    """The ORIGINAL receipt for a create whose requestId was already dispatched.

    Nothing is derived, resolved, inspected or dispatched here, so this path works with
    no helper running and cannot produce a second side effect.  The entity counts of the
    first attempt are deliberately absent rather than defaulted: the receipt does not
    carry them and this call did not measure them.
    """
    backend = receipt.get('backend') or {}
    ok = receipt.get('ok') is True
    return _ok('mw.scene.createEntity', created=ok, levelId=level['levelId'], replayed=True,
               entityId=backend.get('entityId'), requestId=request_id,
               templateId=request['templateId'],
               transform={'position': request['position'], 'rotation': request['rotation'],
                          'scale': request['scale']},
               liveReadback=_replayed_readback(
                   receipt, backend,
                   detail='replayed from the journaled receipt of the original dispatch; the level '
                          'was not inspected again and nothing was derived or dispatched'),
               persistence=_stage('not-run', reason='nothing was saved; the new entity lives in '
                                                   'the editor only'),
               reopen=_stage('not-run'), runtime=_stage('not-run'), cleanup=_stage('not-run'),
               journal=receipt.get('journal') or str(JOURNAL_ROOT / request_id),
               note='this requestId was already dispatched; its original receipt is the answer and '
                    'this call created, derived, inspected and dispatched nothing')


def replay_save_result(level, request_id, receipt):
    """The ORIGINAL receipt for a save whose requestId was already dispatched.

    The protected-save verdict is recomputed from the recorded ``gilChanged`` map: the
    original call failed this operation for touching another level, and a replay must
    reproduce that rather than hide it behind a "the replay itself succeeded" frame.
    """
    backend = receipt.get('backend') or {}
    run = backend.get('run')
    native_status = backend.get('nativeStatus')
    # R19: the ack is a DISPATCH fact and is reported under that name.  ``saved`` is a
    # statement about the disk and is folded from the RECORDED differential, exactly as
    # the live path folds it from the fresh one, so the two paths are one predicate.
    dispatched = bool(receipt.get('ok') is True and native_status == 0)
    recorded_diff = receipt.get('saveDiff') if isinstance(receipt, dict) else None
    changed = backend.get('gilChanged') or {}
    others = sorted(k for k, v in changed.items() if v and str(k) != str(level['levelId']))
    if others:
        raise BusinessError('SAVE_TOUCHED_ANOTHER_LEVEL',
                            'the original dispatch changed protected saves: ' + ','.join(others),
                            gilChanged=changed, replayed=True)
    return _ok('mw.scene.saveLevel', saved=saved_from_save_diff(recorded_diff),
               levelId=level['levelId'], replayed=True,
               requestId=request_id, nativeSaveStatus=native_status,
               nativeDispatched=dispatched,
               targetGilChanged=bool(changed.get(str(level['levelId']))),
               protectedGilsChanged=others,
               liveReadback=_replayed_readback(
                   receipt, backend,
                   detail='replayed from the journaled receipt of the original dispatch; the '
                          'reviewed baseline was not re-inspected after the fact'),
               # R04: a replay may not upgrade the verdict, and this one no longer can.  See
               # _replayed_persistence -- the native ack is a dispatch fact, and if the original
               # receipt carried no differential the stage is blocked rather than pass.
               persistence=_replayed_persistence(receipt, run, native_status),
               reopen=_stage('not-run', reason='this server does not reopen the level'),
               runtime=_stage('not-run'), cleanup=_stage('not-run'),
               domainCoverage=_replayed_domain_coverage(receipt, request_id),
               journal=receipt.get('journal') or str(JOURNAL_ROOT / request_id),
               note='this requestId was already dispatched; its original receipt is the answer and '
                    'this call derived, inspected and dispatched nothing')


def _run(argv, *, timeout=420, expect_json=True):
    """Run one fixed project entry point.  The caller's argv is never shell-evaluated.

    ``stdin`` is explicitly DEVNULL.  This server's own stdin is the MCP transport pipe,
    and a child that inherits it can block on it -- measured: the current-level
    discovery step hung with CPU at 0 for minutes when launched from inside this server,
    while the identical command completed in 13 seconds from a shell.  Handing a child
    that pipe would also let it corrupt the protocol by writing to it.
    """
    process = subprocess.run(argv, cwd=str(ROOT), stdin=subprocess.DEVNULL,
                             capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=timeout)
    if expect_json:
        try:
            return json.loads(process.stdout)
        except (ValueError, TypeError):
            raise BusinessError('BACKEND_NO_JSON_RECEIPT',
                                'entry point did not return one JSON object; inspect its evidence, '
                                'do not retry', exitCode=process.returncode,
                                stdoutTail=(process.stdout or '')[-600:],
                                stderrTail=(process.stderr or '')[-600:])
    return process


def is_supported_template(template_id) -> bool:
    """2026-10-09: the template whitelist is REMOVED by user directive.

    This used to return the hand-maintained set held in build_scene_profile.TEMPLATES, and
    the callers below refused any id outside it. Any uint32 is now a valid template id; the
    native layer is the authority on whether the catalog actually holds one. The refusal is
    therefore a RANGE check, not a membership test.
    """
    sys.path.insert(0, str(ROOT / 'tools/game-executor'))
    from build_scene_profile import is_template_id
    return is_template_id(template_id)


def validate_transform(request):
    """Refuse a bad transform here, before a baseline, a copy or a review is made.

    The layers below validate all of this again -- scene_cli, build_scene_profile and
    the native factory each do.  Checking here as well is what turns a late, messy
    failure into a structured pre-dispatch refusal with no side effect: the model gets
    a code it can act on, and nothing was written, claimed or queued.
    """
    import math
    for name in ('position', 'rotation', 'scale'):
        value = request[name]
        if not isinstance(value, list) or len(value) != 3:
            raise BusinessError('TRANSFORM_INVALID',
                                '%s must be exactly three numbers' % name, field=name)
        for index, component in enumerate(value):
            if isinstance(component, bool) or not isinstance(component, (int, float)) \
                    or not math.isfinite(component):
                raise BusinessError('TRANSFORM_INVALID',
                                    '%s[%d] must be a finite number' % (name, index),
                                    field=name, index=index)
        if name == 'scale' and any(component <= 0 for component in value):
            raise BusinessError('SCALE_NOT_POSITIVE',
                                'every scale component must be strictly positive', field='scale')
    return request


def resolve_elevated_queue():
    """The resident helper's queue, proven against the helper's OWN status reply.

    The pointer file supplies the queue PATH only.  Its cached ``deadlineUtc`` is not
    the authority, and MEASURED 2026-09-29 it was stale: the helper had been restarted
    into the same queue directory while the pointer still carried the previous helper's
    expiry, so trusting the cache refused a perfectly live helper.  The authority is the
    helper's reply to a status request -- its own pid, elevated flag, deadline, action
    set and pin digest.  Nothing is dispatched on the strength of the file alone.

    A stale pointer (absent queue, unreadable, or outside this project) still refuses,
    and there is deliberately no fallback to a local UAC path: the whole point of the
    queue transport is that no unattended step raises a prompt of its own.
    """
    if not POINTER.is_file():
        raise BusinessError('ELEVATED_POINTER_MISSING', str(POINTER))
    state = _read_json(POINTER)
    queue = Path(state.get('queueDir') or '')
    allowed = (ROOT / '.runtime/editor-bridge').resolve()
    if not queue.is_dir() or not queue.resolve().is_relative_to(allowed) or queue.resolve() == allowed:
        raise BusinessError('ELEVATED_QUEUE_OUTSIDE_PROJECT_OR_MISSING', str(queue))
    if not (queue / 'runner.heartbeat').is_file():
        raise BusinessError('ELEVATED_HEARTBEAT_ABSENT',
                            'the helper is not running; a human must start it',
                            queueDir=str(queue))
    reply = _run([PYTHON, '-B', str(ROOT / 'tools/editor-bridge/elevated-request.py'),
                  '--queue-dir', str(queue), 'status'], timeout=120)
    from datetime import datetime, timezone
    native = reply.get('nativeScene') or {}
    deadline = reply.get('deadlineUtc')
    if reply.get('elevated') is not True or native.get('enabled') is not True:
        raise BusinessError('ELEVATED_HELPER_NOT_USABLE', 'helper status is not usable',
                            helperStatus={k: reply.get(k) for k in ('elevated', 'pid', 'handled')})
    if native.get('blocked'):
        raise BusinessError('ELEVATED_HELPER_BLOCKED',
                            'the helper reports an unresolved previous native dispatch',
                            actions=native.get('actions'))
    if not isinstance(deadline, str) or \
            datetime.now(timezone.utc) >= datetime.fromisoformat(deadline.replace('Z', '+00:00')):
        raise BusinessError('ELEVATED_HELPER_DEADLINE_PASSED',
                            'the helper own deadline has passed; a human must start a new one',
                            deadlineUtc=deadline)
    # Reader consistency.  This function already refuses to trust the pointer's
    # cached deadline, but the pointer is read directly by other tools --
    # build_reopen_profile.py:149 uses its ``deadlineUtc`` as the reopen cutoff --
    # so a cache that disagrees with the live helper must be a loud refusal, not a
    # silent one.  Two divergences are dangerous and are the exact rot the
    # hand-maintained pointer produced:
    #   * a cached pid that names a different helper, and
    #   * a cached deadline LATER than the helper's own, which over-states the
    #     window and could let a run outlive its authorization.
    # A pointer written by tools/editor-bridge/sync-elevated-pointer.py always
    # agrees, because every identity field it stores comes from this same reply.
    cached_pid = state.get('helperPid')
    if isinstance(cached_pid, int) and cached_pid != reply.get('pid'):
        raise BusinessError('ELEVATED_POINTER_HELPER_PID_CONFLICT',
                            'the pointer names a different helper than the live one',
                            pointerHelperPid=cached_pid, liveHelperPid=reply.get('pid'))
    cached_deadline = state.get('deadlineUtc')
    if isinstance(cached_deadline, str):
        try:
            cached_stamp = datetime.fromisoformat(cached_deadline.replace('Z', '+00:00'))
            if cached_stamp.tzinfo is None:
                cached_stamp = cached_stamp.replace(tzinfo=timezone.utc)
        except ValueError:
            cached_stamp = None
        if cached_stamp is not None and \
                cached_stamp > datetime.fromisoformat(deadline.replace('Z', '+00:00')):
            raise BusinessError('ELEVATED_POINTER_DEADLINE_OVERSTATED',
                                'the pointer caches a deadline later than the helper own; '
                                'a reader that trusts it could outlive the helper',
                                pointerCachedDeadline=cached_deadline, helperDeadlineUtc=deadline)
    return queue, {'pointer': str(POINTER), 'pinsDigest': native.get('pinsDigest'),
                   'helperPid': reply.get('pid'), 'actions': native.get('actions'),
                   'deadlineUtc': deadline,
                   'deadlineSource': 'helper status reply, not the cached pointer',
                   'pointerCachedDeadline': state.get('deadlineUtc'),
                   'pointerCachedHelperPid': cached_pid}


def load_handle(handle):
    """Recheck a previously minted opaque observation, on either readonly transport.

    This launches nothing and does not make old evidence fresh. The caller still
    checks the live helper and obtains a new inspect before any new native write.
    """
    import re
    import stat
    if not isinstance(handle, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', handle):
        raise BusinessError('LEVEL_HANDLE_INVALID', 'handle must be one opaque run name')
    sys.path.insert(0, str(ROOT / 'tools/game-executor'))
    import discover_current_level as discovery

    def original_path(path):
        # Resolving alone would accept a junction/symlink that changes ownership.
        path = Path(path)
        if (not path.is_absolute() or not path.is_relative_to(ROOT / '.runtime')
                or not path.resolve().is_relative_to((ROOT / '.runtime').resolve())):
            raise ValueError('HANDLE_EVIDENCE_OUTSIDE_PROJECT_RUNTIME')
        for part in (path, *path.parents):
            if part.exists() or part.is_symlink():
                info = part.lstat()
                if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError('HANDLE_EVIDENCE_REPARSE_POINT')
            if part == ROOT:
                break
        return path

    try:
        for root in (discovery.DEFAULT_OUTPUT_ROOT / 'runs',
                     discovery.profiles.ROOT / discovery.QUEUE_RUN_ROOT_NAME):
            original_path(root / handle)
        run = discovery.parse_any_handle(handle)
        for name in ('current-level-observation.json', 'stdout.jsonl', 'prepared.json',
                     'build-result.json', 'exit.json'):
            original_path(run / name)
        record = discovery.show(handle)  # Existing original receipt hash gate.
        if (record.get('ok') is not True or record.get('kind') != 'current-level-observation'
                or record.get('handle') != handle or Path(record.get('run') or '') != run):
            raise ValueError('HANDLE_OBSERVATION_BINDING')
        built = _read_json(run / 'build-result.json')
        required = {'hook_receipt.dll', 'hook_receipt_probe.exe', 'target_config.h',
                    'prepared.json', 'invoke-readonly-probe.ps1'}
        if not required <= set(built.get('hashes') or {}):
            raise ValueError('HANDLE_ARTIFACT_BINDINGS_MISSING')
        for name in built.get('hashes') or {}:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
                raise ValueError('HANDLE_ARTIFACT_NAME_INVALID')
            original_path(run / name)
        evidence = discovery.decode_receipt(run)  # Pinned compiled artifacts/profile/decoder.
        prepared = evidence['prepared']
        observed = evidence['snapshot'].get('levelObservation') or {}
        level_id = observed.get('levelId')
        definitions = prepared.get('nativeDefinitions') or {}
        exit_result = evidence['exit']
        if (evidence['acceptance'].get('ok') is not True or observed.get('verified') is not True
                or type(level_id) is not int or not 0 < level_id < discovery.QUEUE_CLAIM_LEVEL_ID
                or record.get('levelId') != level_id
                or record.get('entities') != evidence['acceptance'].get('entityCount')
                or prepared.get('allowWrites') is not False
                or definitions.get('HR_ACTION') != 0 or definitions.get('GS_BOOTSTRAP_READONLY') != 1
                or exit_result.get('executed') is not True or exit_result.get('exitCode') != 0
                or exit_result.get('error')):
            raise ValueError('HANDLE_READONLY_OBSERVATION_UNVERIFIED')
        session_path = original_path(Path(record.get('sessionPath') or ''))
        if discovery.sha256_file(session_path) != record.get('sessionSha256'):
            raise ValueError('HANDLE_SESSION_RECEIPT_CHANGED')
        session = _read_json(session_path)
        if any(session.get(name) != prepared['session'].get(name) for name in discovery.SESSION_FIELDS):
            raise ValueError('HANDLE_SESSION_BINDING')
    except Exception as exc:
        message = str(exc)
        code = 'LEVEL_HANDLE_UNVERIFIED'
        if message.startswith('HANDLE_AMBIGUOUS_OR_UNKNOWN:') and message.endswith(':matches=0'):
            code = 'LEVEL_HANDLE_UNKNOWN'
        elif message.startswith('OBSERVATION_RECEIPT_CHANGED:'):
            code = 'LEVEL_HANDLE_RECEIPT_CHANGED'
        raise BusinessError(code, message) from exc
    return {'handle': handle, 'run': str(run), 'levelId': level_id,
            'entities': evidence['acceptance']['entityCount'], 'verifiedAtUtc': record.get('createdUtc'),
            'sessionPath': str(session_path)}

def fresh_account_backup(label):
    """Copy the whole account save set and prove the copy.

    Run before every write so the review's recovery evidence predates it.  This is a
    project-local read of the formal files plus a copy under .runtime; it never writes
    to the LocalLow directory.
    """
    reply = _run([PYTHON, '-B', str(ROOT / 'tools/editor-bridge/backup-account-saves.py'),
                  'create', '--label', label])
    if reply.get('ok') is not True:
        raise BusinessError('ACCOUNT_BACKUP_FAILED', 'account backup did not report ok',
                            detail=reply)
    verified = _run([PYTHON, '-B', str(ROOT / 'tools/editor-bridge/backup-account-saves.py'),
                     'verify', '--backup', reply['backup']])
    if verified.get('ok') is not True or verified.get('missing') or verified.get('changed'):
        raise BusinessError('ACCOUNT_BACKUP_NOT_VERIFIED', 're-hash of the copy disagreed',
                            verify=verified)
    return {'backup': reply['backup'], 'manifest': str(Path(reply['backup']) / 'manifest.json'),
            'fileCount': reply.get('fileCount'), 'verified': verified.get('verified')}


def save_manifest_module():
    """``backend.save_manifest`` (W08), imported on the FIRST save.

    Late, for the same reason as ``ledger_module``: a checkout missing it still
    starts this server, and the refusal lands on the write.
    """
    try:
        from backend import save_manifest as module
    except ImportError:                       # pragma: no cover - bare-script invocation
        sys.path.insert(0, str(ROOT))
        from backend import save_manifest as module
    return module


def save_verification_module():
    """``backend.save_verification`` (DS-05), imported on the FIRST save."""
    try:
        from backend import save_verification as module
    except ImportError:                       # pragma: no cover - bare-script invocation
        sys.path.insert(0, str(ROOT))
        from backend import save_verification as module
    return module


def save_domain_coverage_module():
    """``backend.save_domain_coverage`` (D23.01.01), imported on the FIRST save.

    Late, for the same reason as ``save_manifest_module``: a checkout missing it still
    starts this server, and the per-domain coverage degrades to an
    ``evidence-insufficient`` stage rather than blocking the save itself.
    """
    try:
        from backend import save_domain_coverage as module
    except ImportError:                       # pragma: no cover - bare-script invocation
        sys.path.insert(0, str(ROOT))
        from backend import save_domain_coverage as module
    return module


def post_write_account_backup(label):
    """A SECOND account snapshot, taken after the native write returned.

    The pre-write snapshot is ``fresh_account_backup``; T09's verifier needs a PAIR
    of account snapshots to judge ``unrelatedUnchanged`` and the ``.gip`` rule, so a
    save now takes one before AND one after.  The wrapper re-hashes the copy instead
    of trusting ``create`` reporting ok, exactly like the pre-write helper.
    """
    return save_manifest_module().take_account_backup(label, root=ROOT, python=PYTHON)


def build_save_manifest(level, baseline, before_backup, after_backup, sent, requestId):
    """Assemble the T09 manifest for this save from the run's own materials.

    Only project-local copies are referenced -- the two account snapshots and the
    manifest/receipt written under ``EVIDENCE_ROOT/<requestId>`` -- and the G02 gate
    is pinned by its contract sha256.  The producer computes no verdict and names no
    root: root46 is carried as a named, unresolved delta, never as an ignorable range.

    A plain ``saveLevel`` has no mechanism to declare an entity delta or changed
    roots, so ``declaredChangedRoots`` / ``entityDelta`` / ``intent`` are left empty
    here.  That is honest, and it is not free: if this save in fact moved a root the
    declaration did not name, the verifier reports a DEFECT (never a pass).  Wiring a
    real declaration from the ledger is a follow-on, not something to fake here.
    """
    module = save_manifest_module()
    return module.build_save_manifest(level, baseline, before_backup, after_backup, sent,
                                      requestId, out_dir=EVIDENCE_ROOT / requestId)


def verify_saved_case_for_save(manifest):
    """Run the T09 verifier, degrading a failure to a stage rather than raising.

    ``saveDiff`` is a *report*, not a precondition: the save already landed, so a
    verifier that cannot run is reported as ``evidence-insufficient`` on that stage
    instead of turning a successful save into a failed call.
    """
    try:
        report = save_verification_module().verify_saved_case(manifest)
    except Exception as exc:                  # noqa: BLE001 - degrade, never erase the save
        return {'stages': {'saveDiff': _stage(
            'evidence-insufficient',
            reason='the T09 verifier could not run: %s: %s' % (type(exc).__name__, exc),
            stageStatuses={})}}
    return report


def build_domain_coverage(level, sent, manifest, declaredDomains, requestId):
    """Per-object-domain coverage for THIS save (D23.01.01).

    The readback is the project-local copy of the level file the W08 manifest already
    pinned (``files.gilAfter``) -- a file other than the reply's own receipt, so it is
    independent of it -- decoded by ``tools/game-executor/read_saved_domains.py`` under the
    pinned content interpreter.  ``declaredDomains`` is the S1-S3 roster the caller
    supplies; a domain it does not name is reported ``not-participated`` and can never
    pass, which is the leaf's own negative rule ("无该域对象则该域不得通过").

    A failure here must not erase a save that already happened, so every refusal degrades
    to an ``evidence-insufficient`` stage, exactly as ``verify_saved_case_for_save`` does.
    """
    try:
        module = save_domain_coverage_module()
        gil = (manifest.get('files') or {}).get('gilAfter') or {}
        built = module.build_save_domain_coverage(
            level['levelId'], requestId, sent,
            {'path': gil.get('path'), 'sha256': gil.get('sha256')},
            declaredDomains,
            receipt_path=(manifest.get('receiptPath') or {}).get('path'),
            out_dir=EVIDENCE_ROOT / requestId)
    except Exception as exc:                  # noqa: BLE001 - the save already happened
        return _stage('evidence-insufficient',
                      reason='per-domain coverage could not be taken: %s: %s'
                             % (type(exc).__name__, exc))
    verdict = built['verdict']
    return _stage('pass' if verdict['overall'] == 'pass' else 'fail',
                  detail={'passedDomains': verdict['passedDomains'],
                          'failedDomains': verdict['failedDomains'],
                          'notParticipatedDomains': verdict['notParticipatedDomains'],
                          'unreadableDomains': verdict['unreadableDomains'],
                          'reasons': verdict['reasons']},
                  coveragePath=built['coveragePath'])


def _replayed_domain_coverage(receipt, request_id):
    """The coverage stage for a REPLAYED save, read from the receipt this run kept.

    The original call's coverage receipt is the answer; a replay must not re-read the level,
    which has since moved on.  With no receipt on disk there is nothing to cite, so the
    stage is ``not-run`` rather than a pass.
    """
    path = EVIDENCE_ROOT / request_id / 'domain-coverage.json'
    if not path.is_file():
        return _stage('not-run', reason='this requestId was already dispatched and no '
                                       'per-domain coverage receipt was kept for it')
    try:
        document = _read_json(path)
    except (OSError, ValueError) as exc:
        return _stage('evidence-insufficient',
                      reason='the kept per-domain coverage receipt could not be read: %s' % exc)
    verdict = document.get('verdict') or {}
    return _stage('pass' if verdict.get('overall') == 'pass' else 'fail',
                  detail={'passedDomains': verdict.get('passedDomains'),
                          'failedDomains': verdict.get('failedDomains'),
                          'notParticipatedDomains': verdict.get('notParticipatedDomains'),
                          'unreadableDomains': verdict.get('unreadableDomains'),
                          'reasons': verdict.get('reasons')},
                  coveragePath=str(path), replayed=True)


def inspection_acceptance_reference(backend, acceptance):
    """Reference the native CLI's existing result; never amend a historic run."""
    run = Path(backend['run'])
    allowed = ROOT / '.runtime/game-executor/scene-cli'
    if not run.is_absolute() or '..' in run.parts or not run.is_relative_to(allowed):
        raise BusinessError('READBACK_ACCEPTANCE_EVIDENCE_INVALID', 'inspection run is outside scene evidence')
    path = run / 'result.json'
    try:
        for item in (path, *path.parents):
            if item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 0x400:
                raise ValueError('reparse evidence path')
            if item == ROOT:
                break
        raw = path.read_bytes()
        original = json.loads(raw.decode('utf-8-sig'))
        if (original.get('readonlyAcceptance') != acceptance or
                original.get('ok') is not True or backend.get('ok') is not True or
                original.get('action') != 'inspect' or backend.get('action') != 'inspect' or
                original.get('levelId') != backend.get('levelId') or
                original.get('entities') != backend.get('entities') or
                original.get('run') != backend.get('run')):
            raise ValueError('original result disagrees with inspection reply')
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise BusinessError('READBACK_ACCEPTANCE_EVIDENCE_INVALID', str(exc), run=str(run)) from exc
    return {'acceptancePath': str(path), 'acceptancePointer': '/readonlyAcceptance',
            'acceptanceSha256': hashlib.sha256(raw).hexdigest()}


def inspect_level(level, request_id):
    """One read-only native inspection through the public CLI.  Never mutates."""
    reply = _run([PYTHON, '-B', str(ROOT / 'tools/authoring/author.py'),
                  '--elevated-queue', str(level['queue']), 'entity-inspect',
                  '--session', level['sessionPath'], '--level-id', str(level['levelId']),
                  '--large-scene',
                  '--request-id', request_id])
    backend = reply.get('backend') or {}
    if reply.get('ok') is not True or backend.get('ok') is not True:
        raise BusinessError('READBACK_FAILED', 'native inspection did not verify',
                            receipt=reply, run=backend.get('run'))
    if backend.get('levelId') != level['levelId']:
        raise BusinessError('READBACK_WRONG_LEVEL',
                            'observed level %r is not the handle level %r'
                            % (backend.get('levelId'), level['levelId']))
    acceptance = backend.get('readonlyAcceptance') or {}
    if acceptance.get('ok') is not True:
        raise BusinessError('READBACK_NOT_ACCEPTED', 'read-only receipt was rejected',
                            reasons=acceptance.get('reasons'), run=backend.get('run'))
    return {'run': backend.get('run'), 'entities': backend.get('entities'),
            **inspection_acceptance_reference(backend, acceptance),
            'snapshotPath': str(Path(backend['run']) / 'before-context.json'),
            'receipt': backend.get('receipt'), 'requestId': request_id}


#: Absolute tolerance for the LIVE readback's placement comparison.  The native entity
#: record carries float32 coordinates, so a request of 0.1 reads back at 0.100000001;
#: 1e-3 is the declared bound here.  (The save-diff verifier compares the FORMAL FILE's
#: geometry at 1e-6, which is quantised by a different path and is a different stage.)
#: A read position further than this from the request is a read-confirmed wrong
#: placement; an UNREAD position is reported ``unknown`` -- never a pass, and never
#: filled from the request.
LIVE_POSITION_ABS_TOLERANCE = 1e-3


def scene_projection_module():
    """``backend.scene_observation``, imported on FIRST write.

    The read-only query surface (``mw_scene_entity_detail`` / ``mw_scene_diff_level``)
    already serves this projection.  The create readback reuses it rather than counting
    rows, so ONE closed attribute vocabulary answers for both: entityId / templateId /
    configId / position are read; rotation / scale / name are declared unsourced and are
    reported unknown for every entity.  Late import so a checkout missing the module
    still starts this server -- the refusal then lands on the create's verification,
    which is the only place it matters.
    """
    try:
        from backend import scene_observation as module
    except ImportError:                       # pragma: no cover - bare-script invocation
        sys.path.insert(0, str(ROOT))
        from backend import scene_observation as module
    return module


def project_relative(path):
    """A project-relative evidence reference, or the raw string for a fixture path."""
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except Exception:                         # noqa: BLE001 - a fixture path is still a ref
        return str(path)


def project_readback(level, inspection):
    """Project one inspection run's OWN decoded observation document.

    Returns ``(projection, failure)`` -- exactly one of the two is not None.  The
    document is the execution layer's ``before-context.json`` for that run; it is never
    a tool argument and never a request echo, which is the whole reason a create's
    template and placement can be judged at all.
    """
    path = inspection.get('snapshotPath')
    try:
        document = _read_json(path)
    except Exception as exc:                  # noqa: BLE001 - report, never crash the tool
        return None, ('the observation document %r of run %r could not be read: %s: %s'
                      % (path, inspection.get('run'), type(exc).__name__, exc))
    try:
        projection = scene_projection_module().project_snapshot(document, identity={
            'targetHandle': level['handle'], 'levelId': level['levelId'],
            'observedAt': None,
            'receiptPath': project_relative(inspection.get('run') or ''),
            'receiptSha256': None})
    except Exception as exc:                  # noqa: BLE001
        return None, ('the observation document %r could not be projected: %s: %s'
                      % (path, getattr(exc, 'code', type(exc).__name__), exc))
    return projection, None


def verify_create_effect(level, before, after, entity_id, request):
    """Judge one create by the level's OWN readback -- identity, template, placement.

    THE DEFECT THIS CLOSES.  This server used to compare one number,
    ``after['entities'] == before['entities'] + 1``.  A level that lost one entity and
    gained a DIFFERENT one answers that test with "yes"; nothing tied the created row to
    the template that was asked for, and the check was pushed to a save-differential
    stage this server does not perform -- so in this server the template was never
    checked at all.  Measured 2026-10-05: the only post-create assertion in the whole
    tool was the count.

    WHAT REPLACES IT.  Both readings are projected with ``backend.scene_observation``
    (the same projection the read-only tools serve) and compared with its own
    ``diff_snapshots``:
      * both sides must be complete, readable, identity-trustworthy sets.  A TRUNCATED
        read may show "one more row" while a row was simply never captured, so it
        refuses instead of passing on a count;
      * the id set must change by EXACTLY the one id the native create reported -- so a
        same-count replacement, or a level that changed by more than the one addition,
        refuses;
      * the created row's own templateId / configId must be the requested template;
      * a READ position must agree with the request within ``LIVE_POSITION_ABS_TOLERANCE``.
    rotation and scale have no reader: they stay ``unknown``, are never filled from the
    request, and their absence is reported rather than passed.

    The save-differential (the formal file's own before/after) is a SEPARATE stage and is
    not judged here; ``persistence`` stays ``not-run`` for a create.
    """
    if entity_id is None:
        raise BusinessError(
            'CREATE_EFFECT_NOT_AS_REQUESTED',
            "the native create reply carried no entityId, so nothing ties the level's "
            'readback to a created entity', reason='entity-id-absent',
            beforeRun=before['run'], afterRun=after['run'])
    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError):
        raise BusinessError(
            'CREATE_EFFECT_NOT_AS_REQUESTED',
            'the native create reply carried a non-integer entityId %r' % (entity_id,),
            reason='entity-id-not-an-integer', beforeRun=before['run'], afterRun=after['run'])

    before_projection, before_failure = project_readback(level, before)
    after_projection, after_failure = project_readback(level, after)
    if before_failure or after_failure:
        raise BusinessError(
            'READBACK_FAILED',
            'the level readback could not be projected, so the create effect is '
            'UNVERIFIED rather than confirmed -- a count alone cannot stand in for it',
            reason='readback-unprojectable', beforeFailure=before_failure,
            afterFailure=after_failure, beforeRun=before['run'], afterRun=after['run'])

    # R17: a reading that never observed WHICH level it was is not evidence about this
    # level.  ``diff_snapshots`` compares levelId to levelId, so two readings that both
    # failed their level observation carry ``None`` on both sides and satisfy that check
    # as "the same level"; ``complete`` does not require ``levelObservation.verified``
    # either, so such a pair can be ``authoritative`` and confirm a create on the wrong
    # (or an unknown) level.  Today the caller's ``inspect_level`` refuses those readings
    # first, but a create's confirmation must not rest on a guard in another function.
    for side, projection in (('before', before_projection), ('after', after_projection)):
        if (projection.get('levelObservation') or {}).get('verified') is not True:
            raise BusinessError(
                'READBACK_WRONG_LEVEL',
                "the %s reading did not verify which level it observed, so the create "
                'effect cannot be tied to the level that was asked for' % side,
                reason='readback-level-unverified', side=side,
                observedLevelId=projection.get('levelId'),
                handleLevelId=level['levelId'],
                beforeRun=before['run'], afterRun=after['run'])

    module = scene_projection_module()
    diff = module.diff_snapshots(before_projection, after_projection)
    if diff['state'] != 'observed':
        code = ('READBACK_WRONG_LEVEL' if diff['code'] == 'SNAPSHOT_LEVEL_MISMATCH'
                else 'READBACK_FAILED')
        raise BusinessError(code, 'the two readings cannot be compared: %s' % diff['reason'],
                            reason='readback-not-comparable', diffState=diff['state'],
                            diffCode=diff['code'], beforeRun=before['run'],
                            afterRun=after['run'])
    if diff['authoritative'] is not True:
        raise BusinessError(
            'READBACK_FAILED',
            'the create effect is UNVERIFIED: at least one reading is not a complete '
            'entity set, so an addition or a removal here may be an artifact of the '
            'capture', reason='readback-not-complete', diffState=diff['state'],
            caveats=diff['caveats'], counts=diff['counts'],
            beforeRun=before['run'], afterRun=after['run'])

    added = [row for row in (diff['added'] or [])]
    removed = [row for row in (diff['removed'] or [])]
    if entity_id not in added:
        raise BusinessError(
            'CREATE_EFFECT_NOT_AS_REQUESTED',
            'the entity id the native create reported is not among the ids the readback '
            'shows as new, so the level did not gain the entity that was asked for',
            reason='created-entity-id-not-observed', entityId=entity_id,
            added=added, removed=removed,
            sameCountDifferentObjects=diff['sameCountDifferentObjects'],
            beforeRun=before['run'], afterRun=after['run'])
    if removed or added != [entity_id]:
        raise BusinessError(
            'CREATE_EFFECT_NOT_AS_REQUESTED',
            'the level changed by more than the one requested addition: %d new, %d gone'
            % (len(added), len(removed)), reason='entity-set-changed-differently',
            entityId=entity_id, added=added, removed=removed,
            sameCountDifferentObjects=diff['sameCountDifferentObjects'],
            beforeRun=before['run'], afterRun=after['run'])

    entity = module.get_entity(after_projection, entity_id)
    row = entity['entity']
    known = row['knownAttributes']
    provenance = row['fieldProvenance']
    unsourced = after_projection.get('unsupportedAttributes') or {}
    template_id = known.get('templateId')
    config_id = known.get('configId')
    if template_id is None:
        raise BusinessError(
            'CREATE_EFFECT_NOT_AS_REQUESTED',
            'the readback did not read a templateId for the new entity, so the requested '
            'template could not be confirmed; an unread template is not a match',
            reason='template-not-read', entityId=entity_id,
            requestedTemplateId=int(request['templateId']),
            templateUnknownReason=(provenance.get('templateId') or {}).get('source'),
            beforeRun=before['run'], afterRun=after['run'])
    if int(template_id) != int(request['templateId']):
        raise BusinessError(
            'CREATE_EFFECT_NOT_AS_REQUESTED',
            'the readback reports templateId %r for the new entity, not the requested %r'
            % (template_id, int(request['templateId'])), reason='template-mismatch',
            entityId=entity_id, requestedTemplateId=int(request['templateId']),
            observedTemplateId=template_id, observedConfigId=config_id,
            beforeRun=before['run'], afterRun=after['run'])

    position = known.get('position')
    position_provenance = provenance.get('position') or {}
    position_error = None
    if position is None:
        position_verdict = 'unknown'
        position_note = ('the position was not read for this entity (%s), so the '
                         'placement is UNKNOWN, not confirmed' % (position_provenance
                                                                  .get('sourceKind', 'none'),))
    else:
        requested_position = [float(v) for v in request['position']]
        position_error = max(abs(float(p) - q)
                             for p, q in zip(position, requested_position))
        if position_error > LIVE_POSITION_ABS_TOLERANCE:
            raise BusinessError(
                'CREATE_EFFECT_NOT_AS_REQUESTED',
                'the readback places the new entity at %r, not the requested %r '
                '(largest axis error %r)' % (position, requested_position, position_error),
                reason='position-mismatch', entityId=entity_id,
                observedPosition=list(position), requestedPosition=requested_position,
                largestAxisError=position_error, tolerance=LIVE_POSITION_ABS_TOLERANCE,
                positionSource=position_provenance.get('sourceKind'),
                beforeRun=before['run'], afterRun=after['run'])
        position_verdict = 'match'
        position_note = ('the read position agrees with the request within %r'
                         % (LIVE_POSITION_ABS_TOLERANCE,))

    observed_transform = {
        'position': list(position) if position is not None else None,
        'positionVerdict': position_verdict,
        'positionSource': position_provenance.get('sourceKind'),
        'positionLargestAxisError': position_error,
        'positionNote': position_note,
        'rotation': None,
        'rotationVerdict': 'unknown',
        'rotationReason': unsourced.get('rotation'),
        'scale': None,
        'scaleVerdict': 'unknown',
        'scaleReason': unsourced.get('scale'),
    }
    verified_entity = {
        'entityId': entity_id,
        'entityIdSource': (provenance.get('entityId') or {}).get('sourceKind'),
        'templateId': template_id,
        'templateIdSource': (provenance.get('templateId') or {}).get('sourceKind'),
        'configId': config_id,
        'configIdSource': (provenance.get('configId') or {}).get('sourceKind'),
        'dictionaryKey': known.get('dictionaryKey'),
        'identityTrusted': row.get('identityTrusted'),
    }
    effect_check = {
        'authoritative': diff['authoritative'],
        'diffState': diff['state'],
        'added': added, 'removed': removed,
        'sameCountDifferentObjects': diff['sameCountDifferentObjects'],
        'beforeComplete': before_projection['complete'],
        'afterComplete': after_projection['complete'],
        'beforeSnapshotId': before_projection['snapshotId'],
        'afterSnapshotId': after_projection['snapshotId'],
        'contract': after_projection.get('contract'),
        'positionVerdict': position_verdict,
    }
    evidence = [project_relative(before.get('acceptancePath') or ''),
                project_relative(before.get('snapshotPath') or ''),
                project_relative(after.get('acceptancePath') or ''),
                project_relative(after.get('snapshotPath') or '')]
    return {'observedTransform': observed_transform, 'verifiedEntity': verified_entity,
            'effectCheck': effect_check,
            'evidenceRef': [ref for ref in evidence if ref]}


def derive_review(level, action, request, baseline_run, backup, workspace):
    """Ask the orchestration entry point to DERIVE a review; it never accepts a verdict."""
    workspace.mkdir(parents=True, exist_ok=True)
    out = workspace / ('%s-review-%s.json' % (action, uuid.uuid4().hex[:12]))
    argv = [PYTHON, '-B', str(ROOT / 'tools/game-executor/orchestrate_write_review.py'),
            '--session', level['sessionPath'], '--level-id', str(level['levelId']),
            '--action', action, '--baseline-run', baseline_run, '--baseline-kind', 'readonly',
            '--account-backup-manifest', backup['manifest'], '--recovery-dir', str(workspace / 'recovery'),
            '--out', str(out)]
    if action == 'create':
        argv += ['--template-id', str(request['templateId'])]
        for key in ('position', 'rotation', 'scale'):
            argv += ['--' + key] + [repr(float(v)) for v in request[key]]
    reply = _run(argv)
    if reply.get('ok') is not True:
        raise BusinessError('REVIEW_ORCHESTRATION_REFUSED',
                            'the coordinator review could not be derived', detail=reply)
    if reply.get('validatedBy') != 'native_write_review.validate_review':
        raise BusinessError('REVIEW_NOT_VALIDATED_BY_PRODUCTION_GATE',
                            'publication did not go through the production validator')
    return reply


def ledger_capability(action):
    """The MCP tool name of one write action.

    The Cordis permit is asked about a ``capabilityId``; the same string is stored in
    the ledger, so one capability has one name on both sides of the port.
    """
    return 'mw_scene_create_entity' if action == 'create' else 'mw_scene_save_level'


def ledger_module():
    """``backend.operation_state`` (T06 / DS-08), imported on the FIRST write.

    Late rather than at module import so a checkout that is missing it still starts this
    server: the refusal then lands on the write, which is the only place it matters,
    instead of breaking every reader at import time.
    """
    try:
        from backend import operation_state as ops
    except ImportError:                       # pragma: no cover - bare-script invocation
        sys.path.insert(0, str(ROOT))
        from backend import operation_state as ops
    return ops


def ledger_binding(action, level, request):
    """The business identity of one write, in ``operation_state``'s own terms.

    Only the caller's business parameters.  The execution material (session, review,
    baseline, elevated queue) is minted afresh on every attempt and is deliberately NOT
    part of what the operation IS -- ``operation_state.binding_for`` says the same and
    for the same reason: including it would turn a legitimate replay into a conflict.
    """
    payload = ({key: request[key] for key in ('templateId', 'position', 'rotation', 'scale')}
               if action == 'create' else {})
    return {'capability_id': ledger_capability(action),
            'target': {'levelId': level['levelId']},
            'payload': payload, 'case_id': None}


def ledger_open_write(action, level, request, review_path, request_id):
    """Claim the operation and bind this attempt's material BEFORE any dispatch.

    The order is the point, and every step is delegated to the ledger -- nothing here
    computes a state, a digest or a verdict:

    * ``plan`` has no side effect at all and refuses a requestId already bound to a
      different command, so the refusal happens before a directory exists;
    * ``claim`` is one ``O_EXCL`` create: exactly one owner;
    * ``bind_material`` fixes the material THIS attempt derived, so re-deriving it later
      cannot turn a replay into a conflict;
    * ``mark_dispatched`` records ``writeExecuted = None`` rather than ``False``, because
      from here the native write may or may not have reached the game.  Its
      ``dispatchEvidence`` is left empty on purpose: the files that name a dispatch
      (``helper-request.json`` / ``bridge-request.json``) belong to ``author.py``'s
      journal, they do not exist yet, and asserting them here would be a claim with no
      evidence behind it.  ``journal_ref`` is the pointer to where they will be.

    A ledger that cannot be written RAISES and the caller dispatches nothing: an
    operation whose row does not exist cannot be reconciled afterwards, and the T03
    permit reads that same row.  Failing open here would reintroduce the silent bypass.
    """
    ops = ledger_module()
    intent = {'operationId': request_id,
              'binding': ops.binding_for(**ledger_binding(action, level, request))}
    ledger = ops.OperationLedger(LEDGER_ROOT)
    try:
        decision = ledger.plan(request_id, intent)
        if decision['decision'] != 'new':
            raise BusinessError(
                decision.get('code') or 'REQUEST_ALREADY_CLAIMED',
                'the business ledger already carries requestId %r as %r, so nothing was '
                'dispatched; report the recorded state instead of resending it'
                % (request_id, decision['decision']),
                requestId=request_id, ledgerRoot=str(LEDGER_ROOT),
                ledgerDecision=decision['decision'])
        claimed = ledger.claim(request_id, intent, owner='entity_server:%d' % os.getpid())
        if not claimed.get('claimed'):
            raise BusinessError(
                'REQUEST_ALREADY_CLAIMED',
                'another attempt owns requestId %r in the business ledger, so nothing was '
                'dispatched' % request_id,
                requestId=request_id, ledgerRoot=str(LEDGER_ROOT))
        ledger.bind_material(
            request_id, request_id=request_id,
            material={'action': action, 'levelId': level['levelId'], 'reviewPath': review_path},
            journal_ref=str(JOURNAL_ROOT / request_id))
        ledger.mark_dispatched(request_id, evidence=[], request_id=request_id)
    except BusinessError:
        raise
    except Exception as exc:                  # noqa: BLE001 - reported as the refusal
        raise BusinessError(
            'BUSINESS_LEDGER_UNAVAILABLE',
            'the T06 business ledger could not record this operation, so nothing was '
            'dispatched: %s: %s' % (type(exc).__name__, exc),
            requestId=request_id, ledgerRoot=str(LEDGER_ROOT)) from None
    return ledger


def ledger_publish(ledger, level, request_id, reply):
    """Publish the original receipt, or record the outcome unknown.  Never guesses.

    ``publish`` accepts a receipt only when it names this requestId and this level; the
    receipt passing through here is the one ``author.py`` just wrote for ``request_id``,
    so a failure to attribute it is a defect worth reporting rather than a verdict to
    soften.  It is recorded as ``outcome-unknown`` and never as a success.
    """
    try:
        ledger.publish(request_id, reply, expected_request_id=request_id,
                       expected_target={'levelId': level['levelId']})
    except Exception as exc:                  # noqa: BLE001 - recorded, never swallowed
        try:
            ledger.mark_unknown(request_id, reason='the receipt could not be published: '
                                                  '%s: %s' % (type(exc).__name__, exc))
        except Exception:                     # noqa: BLE001 - the publish failure is the news
            pass


def dispatch_write(level, action, request, review_path, request_id):
    """One reviewed native write, journaled under request_id.  Never resubmitted.

    The write is ALSO recorded in the T06 / DS-08 business ledger under
    :data:`LEDGER_ROOT` -- the directory the Cordis lifecycle port reads.  Until that row
    existed the T03 permit's ``existing`` and ``refused`` outcomes were unreachable on
    the production path: ``beginOperation`` read an empty ledger, answered
    ``never-claimed`` and granted every dispatch, so the permit was bypassed without a
    single red light.  :func:`ledger_open_write` runs before the native call and
    :func:`ledger_publish` after it.
    """
    ledger = ledger_open_write(action, level, request, review_path, request_id)
    argv = [PYTHON, '-B', str(ROOT / 'tools/authoring/author.py'),
            '--elevated-queue', str(level['queue']), 'entity-create' if action == 'create' else 'save',
            '--session', level['sessionPath'], '--review', review_path,
            '--level-id', str(level['levelId']), '--request-id', request_id]
    if action == 'create':
        argv += ['--template-id', str(request['templateId'])]
        for key in ('position', 'rotation', 'scale'):
            argv += ['--' + key] + [repr(float(v)) for v in request[key]]
    reply = _run(argv)
    ledger_publish(ledger, level, request_id, reply)
    backend = reply.get('backend') or {}
    return {'reply': reply, 'backend': backend, 'ok': reply.get('ok') is True,
            'outcomeUncertain': backend.get('outcomeUncertain') is True,
            'error': reply.get('error'), 'journal': reply.get('journal'),
            'ledgerRoot': str(LEDGER_ROOT)}


# --------------------------------------------------------------------------- #
# Tools -- the whole visible surface
# --------------------------------------------------------------------------- #

@mcp.tool(description='Static capability contract: which templates may be requested, the closed '
                      'transform rules, the snapshot capacity, and which stages this server does and '
                      'does not perform. No game call.')
def mw_scene_capabilities() -> Any:
    try:
        sys.path.insert(0, str(ROOT / 'tools/game-executor'))
        from build_scene_profile import TEMPLATE_ID_MAX, LARGE_MAX_ENTITIES as CAP, MAX_BATCH
        return _ok('mw.scene.capabilities',
                   supportedTemplateIds=None,
                   supportedTemplateCount=None,
                   templateIdRule={'minimum': 1, 'maximum': TEMPLATE_ID_MAX,
                                   'type': 'integer', 'booleansAllowed': False,
                                   'whitelistEnforced': False},
                   templateLookup='tools/game-executor/entity_name_rule.py search <name>',
                   allowedActions=['create', 'create-many', 'save'],
                   transformRules={
                       'position': 'three finite float32; no range check exists in the project source, '
                                   'so scene bounds are unknown -- a finite coordinate is not proof of '
                                   'a legal one',
                       'rotation': 'three finite float32, degrees',
                       'scale': 'three finite float32, each strictly positive'},
                   snapshotCapacity=CAP, batchLimit=MAX_BATCH,
                   largeScene={'snapshotVersion': 2, 'legacySnapshotCapacity': 512,
                               'planLimit': 3000, 'defaultBatchSize': 64,
                               'budgetMeaning': 'planning ceiling, native quotas still authoritative',
                               'partialFailure': 'sticky stop; full known ID map retained; no replay'},
                   environmentRepairs=ENVIRONMENT_REPAIRS,
                   stages={'liveReadback': 'performed', 'persistence': 'performed',
                           'reopen': 'not performed by this server',
                           'runtime': 'not performed by this server',
                           'cleanup': 'performed for entity ids this run created'},
                   membershipMeans='permitted to be requested under a reviewed create, NOT proven '
                                   'to place, save and reload',
                   note='No template allowlist. Null count is not zero or universal verification; '
                        'look up an id, then independently verify native placement and persistence.')
    except Exception as exc:
        return _fail('mw.scene.capabilities', exc)


def scene_scale_module():
    sys.path.insert(0, str(ROOT / 'tools/game-executor'))
    import scene_scale
    return scene_scale


@mcp.tool(description='Prepare a large world-coordinate placement plan offline. No game access. '
                      'The plan supports up to 3000 placements within a conservative total scene budget. '
                      'Use create_many to dispatch bounded batches; operationId must be unique.')
def mw_scene_prepare_many(levelId: int, operationId: str, placements: list[dict[str, Any]],
                          entityBudget: int = 3000, batchSize: int = 64) -> Any:
    try:
        module = scene_scale_module()
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', operationId):
            raise ValueError('INVALID_OPERATION_ID')
        normalized = module.normalize_plan({'placements': placements}, entity_budget=entityBudget, batch_size=batchSize)
        path = module.OUTPUT / operationId
        if (path / 'operation.json').exists():
            _, manifest, existing = module.load(path)
            if existing != normalized or manifest['levelId'] != levelId:
                raise ValueError('OPERATION_ID_CONFLICT')
            result = module.status(path)
        else:
            inputs = module.OUTPUT / 'inputs'
            inputs.mkdir(parents=True, exist_ok=True)
            source = inputs / (operationId + '-' + uuid.uuid4().hex + '.json')
            module.write(source, {'placements': placements})
            result = module.prepare(source, operationId, levelId, entity_budget=entityBudget, batch_size=batchSize)
        return _ok('mw.scene.prepareMany', **result)
    except Exception as exc:
        return _fail('mw.scene.prepareMany', exc)


@mcp.tool(description='Execute a prepared large placement plan with a fresh complete observation '
                      'and reviewed native request before each batch. Stops on partial/unknown outcome '
                      'and never replays an attempted batch. Does not save; inspect status for exact IDs.')
def mw_scene_create_many(levelHandle: str, operationId: str, maxBatches: int = 8,
                         maxSeconds: int = 1800) -> Any:
    try:
        module = scene_scale_module()
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', operationId):
            raise ValueError('INVALID_OPERATION_ID')
        level = load_handle(levelHandle)
        operation, manifest, _ = module.load(module.OUTPUT / operationId)
        if manifest['levelId'] != level['levelId']:
            raise ValueError('OPERATION_LEVEL_MISMATCH')
        level['queue'], _ = resolve_elevated_queue()
        # In-process dispatch avoids an outer subprocess timeout terminating a
        # still-running multi-batch coordinator. Each native request is bounded.
        result = module.run(operation, level['sessionPath'], queue=level['queue'],
                            max_batches=maxBatches, max_seconds=maxSeconds)
        return _ok('mw.scene.createMany', **result)
    except Exception as exc:
        return _fail('mw.scene.createMany', exc)


@mcp.tool(description='Read and independently verify a prepared placement operation, with a paged '
                      'placement-index to created-entity-ID mapping. No game access or retry.')
def mw_scene_many_status(operationId: str, offset: int = 0, limit: int = 128) -> Any:
    try:
        module = scene_scale_module()
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', operationId):
            raise ValueError('INVALID_OPERATION_ID')
        return _ok('mw.scene.manyStatus', **module.status(module.OUTPUT / operationId, offset=offset, limit=limit))
    except Exception as exc:
        return _fail('mw.scene.manyStatus', exc)


@mcp.tool(description='Discover the level currently open in the editor. Returns an opaque handle and '
                      'the level id read from the native receipt. Compiles and runs one read-only '
                      'probe; it writes nothing to the level.')
def mw_scene_discover_level() -> Any:
    try:
        if not PROTOBUF_PYTHON or not Path(PROTOBUF_PYTHON).is_file():
            raise BusinessError('DISCOVERY_INTERPRETER_MISSING', 'no project interpreter found')
        reply = _run([PYTHON, '-B', str(ROOT / 'tools/game-executor/discover_current_level.py'),
                      '--large-scene',
                      '--output-root', str(DISCOVERY_ROOT)], timeout=600)
        if reply.get('ok') is not True:
            raise BusinessError('LEVEL_DISCOVERY_FAILED', 'current level did not verify', detail=reply)
        return _ok('mw.scene.discoverLevel', levelHandle=reply['handle'],
                   levelId=reply['levelId'], entities=reply.get('entities'),
                   evidence=reply.get('run'), receiptSha256=reply.get('receiptSha256'),
                   liveReadback=_stage('pass', detail='level observation verified from the native '
                                                      'receipt; id came from no caller and no config'),
                   note='pass here covers level identity only; it says nothing about the entities')
    except Exception as exc:
        return _fail('mw.scene.discoverLevel', exc)


@mcp.tool(description='Read every entity of the level behind a handle, through one read-only native '
                      'inspection. Never mutates and never reuses a past inspection.')
def mw_scene_read_entities(levelHandle: str) -> Any:
    try:
        _require_handle = levelHandle
        level = load_handle(_require_handle)
        level['queue'], _ = resolve_elevated_queue()
        read = inspect_level(level, 'mcpinspect' + uuid.uuid4().hex[:16])
        return _ok('mw.scene.readEntities', levelId=level['levelId'], entityCount=read['entities'],
                   run=read['run'], snapshotPath=read['snapshotPath'],
                   acceptancePath=read['acceptancePath'],
                   acceptancePointer=read['acceptancePointer'],
                   acceptanceSha256=read['acceptanceSha256'],
                   liveReadback=_stage('pass', entityCount=read['entities']),
                   persistence=_stage('not-run', reason='a read does not establish persistence'),
                   reopen=_stage('not-run'), runtime=_stage('not-run'), cleanup=_stage('not-run'))
    except Exception as exc:
        return _fail('mw.scene.readEntities', exc)


# --------------------------------------------------------------------------- #
# Scene query surface (W7): the T04 projection over the REAL backend port
# --------------------------------------------------------------------------- #
#
# backend/scene_query_wiring.py is the model-facing query layer.  Its execution layer is the
# port built here, and the port dispatches through THIS module's own read functions --
# load_handle -> resolve_elevated_queue -> inspect_level, the same three calls
# mw_scene_read_entities already makes -- so a query reaches the level by no route the
# existing read tool could not, and adds no execution path of its own.
#
# The port is bound to ``sys.modules[__name__]`` rather than re-imported as
# ``backend.entity_server``: under a script-mode start the latter would execute this module a
# SECOND time, creating a second FastMCP instance and re-running the environment repair.
#
# WHAT THESE TOOLS CANNOT DO, and report instead of guessing: they do not decode the raw
# probe hex (the pinned decoder owns that), they do not read or write the formal save
# (T08/T09 own that), and they never set saveDiff/reopen/runtime/cleanup -- a clean read
# says nothing about what reached the disk.

if str(ROOT) not in sys.path:                      # importable when started as a script
    sys.path.insert(0, str(ROOT))

from backend.scene_query_wiring import (           # noqa: E402  (path fixed just above)
    EntityServerReadPort, SceneQueryTools, build_service)

_QUERY_TOOLS = None


def query_tools():
    """The process-wide scene query surface, built once.  Never a tool argument."""
    global _QUERY_TOOLS
    if _QUERY_TOOLS is None:
        _QUERY_TOOLS = SceneQueryTools(
            service=build_service(EntityServerReadPort(server=sys.modules[__name__])))
    return _QUERY_TOOLS


def _query_result(body):
    """A query result as an MCP CallToolResult.

    ``isError`` is read from the envelope's own state projection, never recomputed here: the
    query layer already decided whether the call completed, and a second opinion in the
    transport is how a business failure comes to look like a success.
    """
    return CallToolResult(content=[TextContent(type='text',
                                               text=json.dumps(body, ensure_ascii=False))],
                          structuredContent=body, isError=body['isError'] is True)


@mcp.tool(description='Observe the level behind a handle as a PROJECTION: ordered entity rows '
                      'with per-attribute source and observation time, and separate '
                      'complete/truncated/trusted verdicts. One read-only native inspection. '
                      'Rows are reachable through the page and detail tools. This is not a '
                      'count.')
def mw_scene_observe_level(levelHandle: str, operationId: str | None = None,
                           caseId: str | None = None) -> Any:
    return _query_result(query_tools().observe(levelHandle, operationId=operationId,
                                               caseId=caseId))


@mcp.tool(description='One bounded page of the observation this server currently holds for the '
                      'handle. Pass the cursor from the previous page; a cursor minted for an '
                      'older snapshot is refused rather than spliced onto the new one. A page '
                      'is never the whole level when the set is truncated.')
def mw_scene_page_entities(levelHandle: str, cursor: str | None = None,
                           maxItems: int | None = None, maxBytes: int | None = None,
                           operationId: str | None = None) -> Any:
    return _query_result(query_tools().page(levelHandle, cursor=cursor, maxItems=maxItems,
                                            maxBytes=maxBytes, operationId=operationId))


@mcp.tool(description='One entity of the held observation, keyed by the id the native read '
                      'returned. unknownFields lists every declared attribute that was NOT '
                      'read, with a reason; an entity missing from an incomplete set is '
                      'reported as unknown, never as absent.')
def mw_scene_entity_detail(levelHandle: str, entityId: int,
                           operationId: str | None = None) -> Any:
    return _query_result(query_tools().detail(levelHandle, entityId, operationId=operationId))


@mcp.tool(description='Difference between two observations this server holds for the handle, '
                      'addressed by snapshotId (default: the previous one against the current '
                      'one). Fewer than two held is refused, never reported as "no change".')
def mw_scene_diff_level(levelHandle: str, beforeSnapshotId: str | None = None,
                        afterSnapshotId: str | None = None,
                        operationId: str | None = None) -> Any:
    return _query_result(query_tools().diff(levelHandle, beforeSnapshotId=beforeSnapshotId,
                                            afterSnapshotId=afterSnapshotId,
                                            operationId=operationId))


@mcp.tool(description='Create one entity from a supported template at a position, then read the level '
                      'back and verify that the level gained exactly the entity the native create '
                      'reported, carrying the requested template at the requested placement. A '
                      'same-count replacement, a different template or a truncated readback is '
                      'refused, never reported as created; rotation and scale have no reader and stay '
                      'unknown. The review is derived from raw materials by the execution layer; the '
                      'caller cannot supply or approve one.')
def mw_scene_create_entity(levelHandle: str, templateId: int, position: list[float],
                           requestId: str, rotation: list[float] | None = None,
                           scale: list[float] | None = None) -> Any:
    try:
        _require_request_id(requestId)
        if isinstance(templateId, bool) or type(templateId) is not int:
            raise BusinessError('TEMPLATE_ID_NOT_AN_INTEGER', 'templateId must be an integer')
        if not is_supported_template(templateId):
            raise BusinessError('TEMPLATE_NOT_SUPPORTED',
                                'templateId %r is not a uint32' % (templateId,))
        # Every cheap input check happens before the handle is resolved, so a malformed
        # request is refused on its own merits rather than behind an unrelated error.
        request = {'templateId': int(templateId),
                   'position': [float(v) for v in position],
                   'rotation': [float(v) for v in (rotation or [0.0, 0.0, 0.0])],
                   'scale': [float(v) for v in (scale or [1.0, 1.0, 1.0])]}
        validate_transform(request)
        level = load_handle(levelHandle)
        # G01 D19: settle against the ledger BEFORE any execution material exists.  The
        # bottom layer fingerprints the whole bound command, review path included, and
        # derive_review mints a fresh review file name on every attempt -- so deriving
        # first turns a replay into a REQUEST_ID_CONFLICT instead of the original receipt.
        receipt = consult_journal(requestId, business_binding(
            dict(backend='scene', action='create', levelId=level['levelId'], **request)))
        if receipt is not None:
            return replay_create_result(level, request, requestId, receipt)
        level['queue'], helper = resolve_elevated_queue()
        workspace = EVIDENCE_ROOT / requestId
        before = inspect_level(level, 'mcpbefore' + uuid.uuid4().hex[:16])
        if before['entities'] >= MAX_ENTITIES:
            raise BusinessError('LEVEL_AT_CAPACITY', 'the level already holds the snapshot capacity')
        backup = fresh_account_backup('mcp-' + requestId[:40])
        review = derive_review(level, 'create', request, before['run'], backup, workspace)
        sent = dispatch_write(level, 'create', request, review['reviewPath'], requestId)
        if not sent['ok']:
            return _ok('mw.scene.createEntity', created=False, levelId=level['levelId'],
                       entityId=None, requestId=requestId,
                       liveReadback=_stage('fail', reason=sent['error'] or 'native create was refused',
                                           outcomeUncertain=sent['outcomeUncertain']),
                       persistence=_stage('not-run'), reopen=_stage('not-run'),
                       runtime=_stage('not-run'), cleanup=_stage('not-run'),
                       journal=sent['journal'], error=sent['error'],
                       note='no retry was attempted and the requestId is now spent')
        entity_id = sent['backend'].get('entityId')
        after = inspect_level(level, 'mcpafter' + uuid.uuid4().hex[:16])
        # The level's OWN readback decides the create (W18).  Identity, set delta,
        # template and placement are verified against the projection of the two native
        # observations -- not against a row count, and not against the request.  A
        # refusal here happens AFTER the write, so it reports the effect as not-as-
        # requested rather than pretending nothing was dispatched.
        effect = verify_create_effect(level, before, after, entity_id, request)
        # Legacy cross-check, kept because the contract pins the literal: an independent
        # native count that disagrees with the projected set means one of the two
        # readings is wrong, which the projection alone cannot see.
        if after['entities'] != before['entities'] + 1:
            raise BusinessError('CREATE_DID_NOT_ADD_EXACTLY_ONE_ENTITY',
                                'entity count went %d -> %d' % (before['entities'], after['entities']),
                                entityId=entity_id, beforeRun=before['run'], afterRun=after['run'])
        return _ok('mw.scene.createEntity', created=True, levelId=level['levelId'],
                   entityId=entity_id, requestId=requestId, templateId=request['templateId'],
                   requestedTransform={'position': request['position'],
                                       'rotation': request['rotation'],
                                       'scale': request['scale']},
                   observedTransform=effect['observedTransform'],
                   verifiedEntity=effect['verifiedEntity'],
                   effectCheck=effect['effectCheck'],
                   entityCountBefore=before['entities'], entityCountAfter=after['entities'],
                   liveReadback=_stage(
                       'pass',
                       detail='a second, independent inspection was projected with the '
                              'read-only scene observation contract: the entity the create '
                              'reported is the only id the level gained, its templateId is '
                              'the requested template, and its placement was %s. rotation '
                              'and scale have no reader and stay unknown; the formal save '
                              'is a separate stage'
                              % effect['observedTransform']['positionVerdict'],
                       evidenceRef=effect['evidenceRef']),
                   persistence=_stage('not-run', reason='nothing was saved; the new entity lives in '
                                                       'the editor only'),
                   reopen=_stage('not-run'), runtime=_stage('not-run'), cleanup=_stage('not-run'),
                   reviewPath=review['reviewPath'], reviewId=review['reviewId'],
                   beforeRun=before['run'], afterRun=after['run'],
                   journal=sent['journal'], helperPid=helper['helperPid'])
    except Exception as exc:
        return _fail('mw.scene.createEntity', exc)


@mcp.tool(description='Save the level through one reviewed native write. Reports persistence as a '
                      'separate stage from the readback, and never claims the level will reload.')
def mw_scene_save_level(levelHandle: str, requestId: str,
                       declaredDomains: dict | None = None) -> Any:
    try:
        _require_request_id(requestId)
        level = load_handle(levelHandle)
        # Same rule as create: the ledger is consulted before the baseline, the backup
        # and the review exist, so a replay is answered rather than re-derived (G01 D19).
        receipt = consult_journal(requestId, business_binding(
            {'backend': 'scene', 'action': 'save', 'levelId': level['levelId']}))
        if receipt is not None:
            return replay_save_result(level, requestId, receipt)
        level['queue'], helper = resolve_elevated_queue()
        baseline = inspect_level(level, 'mcpsavebase' + uuid.uuid4().hex[:16])
        backup = fresh_account_backup('mcp-' + requestId[:40])
        review = derive_review(level, 'save', {}, baseline['run'], backup, EVIDENCE_ROOT / requestId)
        sent = dispatch_write(level, 'save', {}, review['reviewPath'], requestId)
        backend = sent['backend']
        native_status = backend.get('nativeStatus')
        # W09 (re-derived onto the W08 text 2026-10-05): this predicate is a DISPATCH fact --
        # the native call was accepted -- and never a persistence fact.  It used to be named
        # ``persisted`` and fed straight into ``saved=`` and ``persistence=``, which is exactly
        # how "native returned 0" got read as "the disk wrote".  It now names what it is, and
        # ``persistence`` below is folded from the differential instead.
        dispatched = bool(sent['ok'] and native_status == 0)
        # A save that touched another level's save is a failure of this operation even if
        # the target write itself succeeded, so it is reported as such rather than ignored.
        changed = backend.get('gilChanged') or {}
        others = sorted(k for k, v in changed.items() if v and str(k) != str(level['levelId']))
        if others:
            raise BusinessError('SAVE_TOUCHED_ANOTHER_LEVEL',
                                'protected saves changed: ' + ','.join(others),
                                gilChanged=changed)
        # The post-write account snapshot and the T09 manifest bracket THIS save:
        # the evidence pair must straddle the write.  A failure here must not erase a
        # save that already happened, so the block degrades to saveDiff=insufficient.
        manifest_path = None
        manifest = None
        try:
            after_backup = post_write_account_backup('mcp-save-post-' + requestId[:32])
            manifest = build_save_manifest(level, baseline, backup, after_backup, sent, requestId)
            manifest_path = manifest.get('manifestPath')
            save_diff = verify_saved_case_for_save(manifest)['stages']['saveDiff']
        except Exception as exc:              # noqa: BLE001 - the save already happened
            save_diff = _stage('evidence-insufficient',
                               reason='post-write evidence could not be taken: %s: %s'
                                      % (type(exc).__name__, exc), stageStatuses={})
        domain_coverage = _stage('not-run',
                                 reason='no W08 manifest was built for this save, so there is no '
                                        'independent readback for the participating domains')
        if manifest is not None:
            domain_coverage = build_domain_coverage(level, sent, manifest, declaredDomains,
                                                    requestId)
        return _ok('mw.scene.saveLevel', saved=saved_from_save_diff(save_diff),
                   levelId=level['levelId'],
                   requestId=requestId, nativeSaveStatus=native_status,
                   nativeDispatched=dispatched,
                   targetGilChanged=bool(changed.get(str(level['levelId']))),
                   protectedGilsChanged=others, entityCountAtSave=baseline['entities'],
                   liveReadback=_stage('pass', entityCount=baseline['entities'],
                                       detail='the reviewed baseline was re-decoded from its own '
                                              'executed run before the write'),
                   # T05 COMPATIBILITY MAPPING ONLY (W09, re-derived onto W08's differential).
                   # ``persistence`` mints no success truth of its own: it is the SAME fold as
                   # ``saveDiff``, so a native status 0 can no longer make it a pass.  Before
                   # this, the two fields could disagree -- saveDiff blocked on a named delta
                   # while persistence said pass off the dispatch ack alone.
                   persistence=persistence_from_save_diff(save_diff),
                   saveDiff=_stage(save_diff['status'], stageStatuses=save_diff.get('stageStatuses'),
                                   manifestPath=manifest_path,
                                   detail='saveInvocation/savedContent/allowedDelta/'
                                          'unrelatedUnchanged; root46 stays a named blocked delta'),
                   reopen=_stage('not-run', reason='this server does not reopen the level'),
                   runtime=_stage('not-run'), cleanup=_stage('not-run'),
                   domainCoverage=domain_coverage,
                   reviewPath=review['reviewPath'], reviewId=review['reviewId'],
                   baselineRun=baseline['run'], journal=sent['journal'],
                   helperPid=helper['helperPid'])
    except Exception as exc:
        return _fail('mw.scene.saveLevel', exc)


# --------------------------------------------------------------------------- #
# D04.01.03 -- batch create: per-item real ids, repair only the failed item
# --------------------------------------------------------------------------- #
#
# ``mw_scene_capabilities`` advertises ``batchLimit = MAX_BATCH`` and, until now, the surface
# had no batch create behind that number (INTERFACE-INVENTORY.md:94-97 records the drift as
# ``backendHasBatch=true, unifiedHasBatch=false``).  The native ``create-batch`` verb cannot
# fill it: it validates the WHOLE batch before any dispatch (build_scene_profile.py:165-166
# refuses the batch when one template is outside the permitted set) and reports ONE receipt
# (scene_cli.py:549-562 marks the whole batch uncertain when one placement is missing), so
# the minimum sample -- 3 placements, 1 illegal template -- would answer 0 created instead
# of 2 created + 1 refused.  That is the opposite of what this leaf requires.
#
# So the batch is orchestrated HERE, one reviewed native ``create`` per placement, and the
# coordinator is ``backend/batch_create.py``.  There is exactly one reviewed create path in
# this server -- ``mw_scene_create_entity`` -- and the batch adds the per-item requestId
# namespace and the repair round, and nothing else.
#
# contract.json:290 is exact about the entry: "The tool surface must offer batch placements
# as inline structured parameters, or not at all" -- there is NO plan-file path here.


def _batch_request(item):
    """One placement as the single-create request shape, as the caller supplied it.

    The values are NOT coerced here: ``validate_transform`` is the one place that decides what
    a legal transform is, and it must see the raw components so that a string or a NaN is
    refused by name (TRANSFORM_INVALID) instead of raising out of ``float()``.
    """
    return {'templateId': item['templateId'],
            'position': item['position'],
            'rotation': item.get('rotation') or [0.0, 0.0, 0.0],
            'scale': item.get('scale') or [1.0, 1.0, 1.0]}


def _batch_validate_item(item):
    """The per-ITEM domain check: the same checks, in the same order, as the single create.

    Deliberately the identical checks rather than a second set of rules.  A placement this
    refuses would have been refused by ``mw_scene_create_entity`` anyway, so refusing it here
    moves the refusal IN FRONT of the dispatch -- which is what makes "非法输入不派发" true
    per item while the REST of the batch still runs.
    """
    from backend import batch_create
    try:
        template_id = item.get('templateId')
        if isinstance(template_id, bool) or type(template_id) is not int:
            raise BusinessError('TEMPLATE_ID_NOT_AN_INTEGER', 'templateId must be an integer')
        if not is_supported_template(template_id):
            raise BusinessError('TEMPLATE_NOT_SUPPORTED',
                                'templateId %r is not a uint32' % (template_id,))
        validate_transform(_batch_request(item))
    except BusinessError as exc:
        raise batch_create.ItemRefusal(exc.code, exc.message) from None
    return None


def _batch_dispatch_one(level_handle, request_id, item):
    """One placement through the EXISTING single-create entry -- no second create path.

    ``mw_scene_create_entity`` is where the review is derived from raw materials, the journal
    is consulted, the native write is dispatched and the level is read back and projected.
    The batch reuses all of it, so the two entries cannot drift apart.
    """
    from backend import batch_create
    reply = mw_scene_create_entity(levelHandle=level_handle, templateId=item['templateId'],
                                   position=list(item['position']), requestId=request_id,
                                   rotation=list(item.get('rotation') or [0.0, 0.0, 0.0]),
                                   scale=list(item.get('scale') or [1.0, 1.0, 1.0]))
    # ``reply.structuredContent`` is the single create's own body, and ``normalize_create_reply``
    # is the only place that reads it: its ``ok`` is a transport fact and NOT the create's
    # verdict (STATE-1), so the normaliser reads ``created`` and ``replayed`` instead.
    return batch_create.normalize_create_reply(reply.structuredContent, reply.isError is True)


def _batch_prior_lookup(level, request_id, item):
    """The journal read for one carried placement, in ``consult_journal``'s own terms.

    The binding is built from the item's spec EXACTLY as ``mw_scene_create_entity`` builds it,
    so if the caller silently changed a carried placement between attempts the binding no
    longer matches its claim and ``consult_journal`` refuses with REQUEST_ID_CONFLICT.  That is
    the point: a carried placement is carried from its own RECORDED command, never from the
    caller's memory of it.
    """
    try:
        binding = business_binding(dict(backend='scene', action='create',
                                        levelId=level['levelId'], **_batch_request(item)))
    except (TypeError, ValueError):
        raise BusinessError('BATCH_ITEM_TRANSFORM_INVALID',
                            'placement %r cannot be bound to a journal command because its '
                            'transform is not numeric' % item.get('itemKey')) from None
    try:
        receipt = consult_journal(request_id, binding)
    except BusinessError as exc:
        if exc.code == 'REQUEST_OUTCOME_UNKNOWN':
            # A claim without a receipt is an UNKNOWN, not a refusal: it must be reconciled
            # from its requestId, never resent (OPS-2).
            return 'unknown', None
        raise
    return ('receipt', receipt) if receipt is not None else ('none', None)


def _batch_tool_result(envelope, receipts, repairable_keys, dispatched_keys):
    """The batch wrapper: the frozen v1 envelope, plus what the envelope has no field for.

    The same seam ``reopen_contract_adapter._wrap`` uses: the contract-valid envelope is
    published UNTOUCHED under ``result`` and the per-placement receipts stay outside it, so the
    published v1 result never gains an undeclared key.  ``isError`` is the transport fact and is
    read from the envelope's own state projection (STATE-1), never recomputed by hand.
    """
    body = {'adapted': envelope['state'] != 'rejected',
            'result': envelope,
            'batchReceipt': list(receipts),
            'repairableKeys': list(repairable_keys),
            'dispatchedItemKeys': list(dispatched_keys),
            'nextAction': envelope['nextAction']}
    return CallToolResult(content=[TextContent(type='text',
                                               text=json.dumps(body, ensure_ascii=False))],
                          structuredContent=body, isError=envelope['state'] != 'completed')


@mcp.tool(description='Create several entities from supported templates as ONE reviewed batch, '
                      'keeping each placement\'s OWN real entity id and, on a later attempt, '
                      're-dispatching ONLY the placements the caller names -- the ones already '
                      'created are carried forward from their own receipts, never created twice. '
                      'Each placement is validated and dispatched on its own, so one illegal '
                      'template refuses that item and leaves the others created: the round is '
                      'partial (state=failed, nextAction=report-and-repair) with changed[] '
                      'holding the ids that really exist and failedItems[] holding what did not. '
                      'Placements are INLINE STRUCTURED PARAMETERS -- there is no plan file. An '
                      'item whose dispatch already left the process is reconciled from its '
                      'receipt, never resent.')
def mw_scene_create_batch(levelHandle: str, batchId: str, items: list[dict[str, Any]],
                          attempt: int = 1, repairKeys: list[str] | None = None) -> Any:
    from backend import batch_create
    try:
        _require_request_id(batchId)
        sys.path.insert(0, str(ROOT / 'tools/game-executor'))
        from build_scene_profile import MAX_BATCH
        # The batch's own shape is refused as a whole, before any placement runs.
        batch_create.check_batch_call(items, max_items=MAX_BATCH, attempt=attempt,
                                      repair_keys=repairKeys)
        level = load_handle(levelHandle)
        report = batch_create.run_batch(
            batch_id=batchId, items=items, attempt=attempt, repair_keys=repairKeys,
            max_items=MAX_BATCH, validate_item=_batch_validate_item,
            dispatch_one=lambda request_id, item: _batch_dispatch_one(levelHandle, request_id,
                                                                      item),
            prior_lookup=lambda request_id, item: _batch_prior_lookup(level, request_id, item))
        envelope = batch_create.contract_result(report, level_handle=levelHandle)
        return _batch_tool_result(envelope, report['receipts'], report['repairableKeys'],
                                  report['dispatchedItemKeys'])
    except batch_create.BatchInputError as exc:
        # A malformed batch call is refused as a whole: no placement was dispatched.
        return _fail('mw.scene.createBatch', BusinessError(exc.code, exc.message))
    except Exception as exc:
        return _fail('mw.scene.createBatch', exc)


@mcp.tool(description='Reconcile one operation by requestId: replay the journaled result or report that '
                      'the outcome is still unknown. Never dispatches anything.')
def mw_scene_operation_status(requestId: str) -> Any:
    try:
        _require_request_id(requestId)
        journal = JOURNAL_ROOT / requestId
        if not journal.is_dir():
            return _ok('mw.scene.operationStatus', requestId=requestId, state='never-claimed',
                       outcomeKnown=True, note='no claim was ever written for this requestId')
        claim = journal / 'claim.json'
        result = journal / 'result.json'
        record = _read_json(result) if result.is_file() else None
        return _ok('mw.scene.operationStatus', requestId=requestId,
                   state='complete' if record else 'claimed-without-result',
                   outcomeKnown=record is not None,
                   result=record,
                   journal=str(journal),
                   note='a claim without a result is an unknown outcome: reconcile, never resend')
    except Exception as exc:
        return _fail('mw.scene.operationStatus', exc)


@mcp.tool(description='Remove entities this run created, proving ownership first. The native '
                      'route is named "owned" but does NOT verify ownership and is NOT atomic, so '
                      'this tool requires the full ownership contract: this run\'s create '
                      'receipt, NEW relative to the pre-create baseline, present in a complete '
                      'read-back taken before the cleanup, inside this round\'s time window, and '
                      'unchanged since the round recorded it. The receipt leg alone is NOT '
                      'ownership: it accepts an id that already existed before the round. '
                      'Dry-run first, then batches of at most 64, then a fresh read-back. '
                      'Pass cleanupRequestId to name one dispatch: the same name with the same '
                      'command replays its recorded outcome and sends nothing, the same name with '
                      'a different command is refused, and a name whose outcome was never '
                      'recorded is reconciled, never re-sent. Use a distinct name per dispatch '
                      '(the dry run and the delete are two).')
def mw_scene_cleanup_owned(levelHandle: str, entityIds: list[int], createdByRequestIds: list[str],
                           runId: str, dryRun: bool = True,
                           cleanupRequestId: str | None = None) -> Any:
    try:
        if not entityIds:
            raise BusinessError('CLEANUP_IDS_EMPTY', 'at least one entity id is required')
        if len(entityIds) > MAX_CLEANUP_IDS:
            raise BusinessError('CLEANUP_IDS_OVER_LIMIT',
                                'at most %d ids per request' % MAX_CLEANUP_IDS)
        if len(set(entityIds)) != len(entityIds):
            raise BusinessError('CLEANUP_IDS_DUPLICATED', 'ids must be unique')
        if any(type(v) is not int or not 0 < v < 2 ** 32 for v in entityIds):
            raise BusinessError('CLEANUP_IDS_NOT_UINT32', 'ids must be positive uint32')
        # 2026-10-06 (R213): the round selector is caller-supplied and was the one argument
        # this route never validated -- it went straight into `_cleanup_round_id`, which hashes
        # whatever it is handed. The sibling route already refuses this shape by name
        # (`mw_scene_cleanup_residue` -> CLEANUP_RESIDUE_ROUND_IDS_INVALID), so the omission
        # here was an asymmetry, not a decision.
        #
        # Scope, stated honestly: this does NOT close a reachable wrong-round path. The round
        # directory is a digest of the cited list and the producer writes to the digest its own
        # receipts imply, so a caller cannot point the lookup at a round whose materials were
        # written for a different list. What was missing is the NAMED REFUSAL: an empty list
        # hashed to the fixed digest of the empty string, and a non-string element raised a
        # bare TypeError that surfaced as a generic failure rather than a defect named for
        # what it is.
        if (not isinstance(createdByRequestIds, list) or not createdByRequestIds
                or any(not isinstance(v, str) or not v for v in createdByRequestIds)):
            raise BusinessError(
                'CLEANUP_ROUND_IDS_INVALID',
                'createdByRequestIds must be the non-empty list of create request ids whose '
                'round is being cleaned up; it is the round selector, and an empty or '
                'non-string list names no round at all')
        if _CLEANUP_LEGS is None:
            raise BusinessError('CLEANUP_OWNERSHIP_LEGS_UNLOADABLE', _CLEANUP_LEGS_ERROR)

        # OWNERSHIP -- legs A..G, and the whole reason this is not a receipt lookup.
        #   1. the id is carried by a create receipt of THIS round, and the receipt still
        #      hashes to what the round recorded;
        #   2. the id is NEW relative to this round's pre-create baseline, computed as the
        #      difference between the complete read-back taken immediately before the
        #      cleanup and that baseline;
        #   3. the id is present in that read-back with the same templateId;
        #   4. the receipt's own create time is inside this round's window;
        #   5. the id is not one of the ids the round could not attribute.
        # Legs 2 and 4 are execution-layer materials, NOT tool arguments: the model must
        # not be able to hand this route the baseline that suits it.  When they are
        # missing the tool REFUSES.  It does not fall back to the receipt-only check it
        # used to perform, because that check cannot tell this round's objects from
        # objects that were already in the level -- which is exactly the failure the
        # frozen ids 1077936129/130/131 demonstrate.
        round_id = _cleanup_round_id(createdByRequestIds)
        materials_path = EVIDENCE_ROOT / 'cleanup' / round_id / 'round-materials.json'
        if not materials_path.is_file():
            raise BusinessError(
                'CLEANUP_ROUND_MATERIALS_UNAVAILABLE',
                'this round has no round-materials.json under %s. It must carry the window, '
                'the pre-create baseline, the pre-cleanup complete read-back and the '
                'receipt provenance; all four are produced by the execution layer, never '
                'by the caller. Until it exists, no id can be shown to be this round\'s own.'
                % materials_path.parent, materialsPath=str(materials_path))
        manifest = _read_json(materials_path)
        # 2026-10-06: the manifest's own paths must stay inside the project runtime before any
        # of them is read as evidence. The legs have no containment check at all, so without
        # this a materials document could name any file on disk as "what exists now" or "what
        # existed before". Checked here, before judge(), so nothing is derived from a path
        # that escaped.
        escaped_material_paths = _cleanup_material_paths_outside_runtime(manifest)
        if escaped_material_paths:
            raise BusinessError(
                'CLEANUP_MATERIAL_PATH_NOT_ALLOWED',
                'the round materials name paths outside the project runtime, so they cannot '
                'be the evidence this round measured', roundId=round_id,
                materialsPath=str(materials_path), paths=escaped_material_paths)
        manifest['candidates'] = sorted(entityIds)
        legs = _CLEANUP_LEGS.judge(manifest,
                                   protected_ids=_load_protected_ids(manifest.get('levelId')))
        if legs.get('status') != 'judged':
            raise BusinessError(
                'CLEANUP_OWNERSHIP_UNDECIDABLE',
                'the round\'s own ownership legs refused it, so nothing is owned and '
                'nothing is dispatched', runRefusals=legs.get('runRefusals'))
        allowed = set(legs['ownedIds'])
        unowned = sorted(set(entityIds) - allowed)
        if unowned:
            raise BusinessError('CLEANUP_ID_NOT_OWNED_BY_THIS_RUN',
                                'the ownership legs of this round did not grant these ids',
                                unowned=unowned, ownedIds=sorted(allowed),
                                perId={key: row for key, row in legs['perId'].items()
                                       if row['entityId'] in unowned})
        # Only now, with the owned set proven, is the live queue resolved at all.
        level = load_handle(levelHandle)
        # 2026-10-06: the round's materials must name the SAME level as the handle the delete
        # will run against. Without this the route had a cross-level hole: entity ids are
        # reused across levels (1077936135 exists in two of them on this machine, and the legs
        # suite encodes that case), so a caller could pass a round whose materials were granted
        # on level A together with a handle for level B, and the legs -- which judge the
        # materials, not the handle -- would grant ids that B does not own.
        #
        # This is the same comparison the sibling residue tool already performs
        # (CLEANUP_RESIDUE_LEVEL_MISMATCH, below) and the independent service performs
        # (cleanup_service.py _resolve_ownership -> OWNERSHIP_MATERIALS_WRONG_LEVEL). The
        # entry was the one of the three that did not; its absence there was an asymmetry,
        # not a design decision. Checked BEFORE the queue is resolved, so a mismatched call
        # cannot reach the dispatch even in principle.
        #
        # Residual, stated rather than implied: the bridge RUN named by `runId` is still
        # checked by name membership only (_known_bridge_runs), because bridge-ready.json
        # carries no level field. The handle is the level authority on this path.
        materials_level = manifest.get('levelId')
        if materials_level is not None and materials_level != level['levelId']:
            raise BusinessError(
                'CLEANUP_MATERIALS_LEVEL_MISMATCH',
                'the round\'s materials were written for level %s but the handle is level %s; '
                'a delete must not be granted by another level\'s ownership evidence'
                % (materials_level, level['levelId']),
                roundId=round_id, handleLevelId=level['levelId'],
                materialsLevelId=materials_level)
        level['queue'], helper = resolve_elevated_queue()
        if not isinstance(runId, str) or not runId:
            raise BusinessError('CLEANUP_BRIDGE_RUN_REQUIRED',
                                'the delete route is a bridge operation and needs an existing bridge '
                                'run under .runtime/editor-bridge/runs; the native-scene queue does '
                                'not serve it', knownRuns=_known_bridge_runs())
        # MEASURED 2026-10-02: this line used to read
        #     _known_bridge_runs()  # validates the shape and existence of runId
        # -- a bare call whose return value was discarded, i.e. NO validation at all.
        # The comment claimed a check that was never performed, so any non-empty
        # string reached the delete dispatch and the only thing standing between a
        # made-up run id and the bridge was the transport's own opinion.
        known_runs = _known_bridge_runs()
        if runId not in known_runs:
            raise BusinessError(
                'CLEANUP_BRIDGE_RUN_UNKNOWN',
                'the delete route needs the run id of a READY bridge run: no such run '
                'under .runtime/editor-bridge/runs has a bridge-ready.json. A name that '
                'is merely well-formed proves nothing about the bridge behind it.',
                knownRuns=known_runs, refusedRunId=runId)
        ownership_legs = {
            'legVersion': legs['legVersion'],
            'readback': legs['readback'],
            'difference': {key: value
                           for key, value in (legs['difference'] or {}).items()
                           if key != 'addedIds'},
        }

        # RE-ENTRY / RECONCILIATION.  create and save settle against the author journal
        # because their requestId names exactly one dispatch.  MEASURED 2026-10-05 by the
        # F-011 guard suite's own probe (``reentry-no-replay``, which stood as an
        # expectedFailure): a repeated identical cleanup call re-dispatched the whole
        # delete table.  The first fix gave this route a claim/outcome PAIR keyed on
        # (owned ids, dryRun, bridgeRunId) -- but ONE slot per round, so an earlier batch
        # was forgotten the moment a later one was recorded, and a plain read-then-write
        # let two concurrent identical calls both see "no claim" and both send.
        #
        # ``cleanupRequestId`` is the request identity: the same shape create/save take,
        # and the identity the cleanup provenance chain names (request, run, payload).  One
        # name is AT MOST one dispatch.  Same name + same command replays the recorded
        # outcome and sends nothing; same name + different command is a CONFLICT; a name
        # whose outcome was never recorded is UNKNOWN and is reconciled, never re-sent.
        # The request directory is created EXCLUSIVELY before the dispatch, which is what
        # makes a concurrent second call refuse instead of sending a second delete.  With
        # no name supplied the identity is derived from the command, so a repeat is still
        # never re-sent -- but a derived identity cannot express a conflict, which is the
        # whole reason the model is offered the name.  dry-run-then-delete and multi-batch
        # cleanup are unaffected: they are different commands, i.e. different requests.
        if _CLEANUP_DISPATCH_JOURNAL is None:
            raise BusinessError('CLEANUP_DISPATCH_JOURNAL_UNLOADABLE',
                                'the cleanup dispatch journal could not be loaded, so a repeat of '
                                'this call could not be told apart from a first one; nothing was '
                                'dispatched.', error=_CLEANUP_DISPATCH_JOURNAL_ERROR)
        dispatch_key = _cleanup_dispatch_key(allowed, dryRun, runId)
        try:
            consult = _CLEANUP_DISPATCH_JOURNAL.consult(
                EVIDENCE_ROOT, round_id, cleanupRequestId, dispatch_key,
                level_id=level.get('levelId'))
        except _CLEANUP_DISPATCH_JOURNAL.DispatchJournalError as refusal:
            raise BusinessError(refusal.code, refusal.message, **refusal.extra)
        # R05: the queue identity this dispatch will carry.  Derived from the request
        # identity the journal just resolved (which is the caller's cleanupRequestId, or the
        # command-derived one when none was supplied), so the same request always names the
        # same queue file and a reader can recompute it.
        transport_request_id = _cleanup_transport_request_id(round_id, consult['requestId'])
        if consult['state'] == 'replayed':
            recorded = consult['receipt']
            return _ok('mw.scene.cleanupOwned', dryRun=dryRun,
                       requestedIds=sorted(entityIds), ownedIds=sorted(allowed),
                       bridgeRunId=runId, nativeReply=recorded, roundId=round_id,
                       replayed=True, replayedFrom=consult['directory'],
                       cleanupRequestId=consult['requestId'],
                       transportRequestId=transport_request_id,
                       transportRequestIdSource='sha256("cleanup-transport\0"+roundId+"\0"+cleanup identity)[:32]',
                       ownershipLegs=ownership_legs,
                       cleanup=_cleanup_verdict_stage(recorded, dryRun),
                       liveReadback=_stage('not-run', reason='run a read-back after the cleanup'),
                       persistence=_stage('not-run'), reopen=_stage('not-run'),
                       runtime=_stage('not-run'),
                       note='replayed from the journaled outcome of the earlier identical call. '
                            'The delete was NOT sent again: a second identical delete is not a '
                            'new operation, and the route cannot tell a replay from a request '
                            'to delete the same ids twice.')

        # R212.  The re-entry guard above is scoped to ONE (round_id, cleanupRequestId)
        # directory and `_cleanup_dispatch_key` makes a different id set a DIFFERENT request
        # by design -- correct for batching, wrong for reconciliation. Before this check an
        # id whose dispatch was attempted with no outcome recorded could be re-cited in a
        # smaller batch (or under a new cleanupRequestId), land on a request the journal had
        # never seen, and be sent to the native delete a second time. This route's own
        # OUTCOME_UNKNOWN refusal already states the rule: an unobserved write is never
        # re-sent. The rule is about the ID, so it is enforced across requests here.
        _unknown_overlap = _cleanup_ids_attempted_with_unknown_outcome(
            EVIDENCE_ROOT, round_id, level.get('levelId'), allowed, consult['requestId'])
        if _unknown_overlap:
            raise BusinessError(
                'CLEANUP_ID_OUTCOME_UNKNOWN_FROM_EARLIER_REQUEST',
                'these ids were dispatched by an earlier request of this round and no outcome '
                'was ever recorded, so whether the level still holds them is UNKNOWN; '
                'reconcile from the earlier claim and a fresh read-back of the level, and do '
                'not send these ids again',
                roundId=round_id, ids=_unknown_overlap)

        op = 'delete-owned-entity-ids-dry-run' if dryRun else 'delete-owned-entity-ids'
        reply = _run([PYTHON, '-B', str(ROOT / 'tools/editor-bridge/elevated-request.py'),
                      '--queue-dir', str(level['queue']), 'call', '--run-id', runId, '--op', op,
                      '--request-id', transport_request_id,
                      '--ids'] + [str(v) for v in sorted(allowed)])

        # The outcome write must not be able to turn a real delete into a reported failure.
        # If it fails the CLAIM still stands, so a repeat is refused as an unknown outcome
        # rather than re-sent -- fail closed, and say so in the reply.
        dispatch_record_warning = None
        outcome_recorded = False
        try:
            _CLEANUP_DISPATCH_JOURNAL.record_outcome(
                consult['directory'], consult['requestId'], round_id, dispatch_key, reply)
            outcome_recorded = True
        except OSError as exc:
            dispatch_record_warning = (
                'the delete was dispatched but its outcome could not be recorded (%s); a repeat '
                'of this call will be refused as an unknown outcome rather than re-sent' % exc)

        # Compatibility mirror of the pre-journal record.  Written best-effort and never
        # read back: the journal above is the authority.  Its failure is reported, not
        # swallowed, because a reader that trusts it would otherwise be reading stale bytes.
        # It says outcomeKnown only when the journal outcome really was recorded, so the
        # mirror can never claim an outcome the journal does not have.
        try:
            _write_json_atomic(_cleanup_dispatch_record_path(round_id), {
                'schemaVersion': 1, 'kind': 'cleanup-dispatch-record', 'roundId': round_id,
                'key': dispatch_key, 'claimedAtUtc': consult.get('claimedAtUtc'),
                'recordedAtUtc': _utc_now(), 'outcomeKnown': outcome_recorded, 'reply': reply,
                'cleanupRequestId': consult['requestId'],
                'journalDirectory': consult['directory'],
                'authority': 'mirror',
                'note': 'compatibility mirror of the authoritative per-request journal entry; '
                        'it is never consulted to decide whether a call is a replay'})
        except OSError as exc:
            mirror_warning = ('the compatibility mirror %s could not be written (%s); the '
                              'journal entry stands and is authoritative'
                              % (_cleanup_dispatch_record_path(round_id), exc))
            dispatch_record_warning = '%s %s' % (dispatch_record_warning, mirror_warning) \
                if dispatch_record_warning else mirror_warning

        body = _ok('mw.scene.cleanupOwned', dryRun=dryRun, requestedIds=sorted(entityIds),
                   ownedIds=sorted(allowed), bridgeRunId=runId, nativeReply=reply,
                   roundId=round_id, replayed=False,
                   cleanupRequestId=consult['requestId'],
                   transportRequestId=transport_request_id,
                   transportRequestIdSource='sha256("cleanup-transport\0"+roundId+"\0"+cleanup identity)[:32]',
                   journalDirectory=consult['directory'],
                   ownershipLegs=ownership_legs,
                   # R20-A13: judged by the delete's EFFECT, never by the dispatch ack.
                   # `reply['ok'] is True` is a fact about the dispatch; a `cleanup` pass
                   # from it alone was an unobserved claim (see _cleanup_verdict_stage).
                   cleanup=_cleanup_verdict_stage(reply, dryRun),
                   liveReadback=_stage('not-run', reason='run a read-back after the cleanup'),
                   persistence=_stage('not-run'), reopen=_stage('not-run'), runtime=_stage('not-run'),
                   note='the route can complete partially; a per-id result of not-attempted is not '
                        'a failure and must not be re-sent as part of the same list')
        if dispatch_record_warning:
            body.structuredContent['dispatchRecordWarning'] = dispatch_record_warning
        return body
    except Exception as exc:
        return _fail('mw.scene.cleanupOwned', exc)


def _cleanup_round_removed_ids(round_id, *, round_dir=None):
    """The ids a round's REAL deletes removed, read from the journal -- never the caller.

    ``mw_scene_cleanup_owned`` records one claim per cleanup request under
    ``<round>/dispatch-journal/<requestId>/`` (``backend/cleanup_dispatch_journal.py``),
    and the claim's ``command`` is exactly ``_cleanup_dispatch_key(owned ids, dryRun,
    bridgeRunId)``.  So the authoritative statement of "which ids this round removed" is
    the union of those commands' ``ids`` where ``dryRun`` is false AND an outcome was
    recorded.  A dry run deletes nothing and is skipped; a real delete with no recorded
    outcome is UNKNOWN and is returned separately so the verdict BLOCKS rather than
    guessing.  The compatibility mirror (``cleanup-dispatch.json``) is a fallback only,
    and the returned ``source`` says which one answered, so a reader is never told "the
    journal" when the journal was not there.
    """
    base = Path(round_dir) if round_dir is not None else (EVIDENCE_ROOT / 'cleanup' / round_id)
    journal_root = base / 'dispatch-journal'
    if journal_root.is_dir():
        removed, unknown = set(), []
        for entry in sorted(journal_root.iterdir()):
            if not entry.is_dir():
                continue
            claim_path = entry / 'claim.json'
            if not claim_path.is_file():
                unknown.append(entry.name)
                continue
            try:
                claim = _read_json(claim_path)
            except (OSError, ValueError):
                unknown.append(entry.name)
                continue
            command = claim.get('command') if isinstance(claim.get('command'), dict) else {}
            if command.get('dryRun') is not False:
                continue
            if not (entry / 'result.json').is_file():
                unknown.append(entry.name)
                continue
            removed.update(v for v in (command.get('ids') or [])
                           if type(v) is int and 0 < v < 2 ** 32)
        return sorted(removed), sorted(set(unknown)), 'dispatch-journal'
    mirror = base / 'cleanup-dispatch.json'
    if mirror.is_file():
        try:
            record = _read_json(mirror)
        except (OSError, ValueError):
            record = {}
        key = record.get('key') if isinstance(record.get('key'), dict) else {}
        if key.get('dryRun') is False:
            if record.get('outcomeKnown') is not True:
                return ([], ['cleanup-dispatch mirror records a real delete whose outcome was '
                             'never recorded'], 'cleanup-dispatch-mirror')
            return (sorted(v for v in (key.get('ids') or [])
                           if type(v) is int and 0 < v < 2 ** 32),
                    [], 'cleanup-dispatch-mirror')
    return [], [], 'none'


@mcp.tool(description='Confirm, from ONE independent native read-back, that a run\'s own cleanup '
                      'left no residue: every id the cleanup removed is gone, and every object '
                      'that could not be attributed to this round is still present. The removed ids '
                      'come from the round\'s own dispatch journal and the must-survive set from the '
                      'round\'s pre-create baseline -- never from the caller. This performs a '
                      'read-only inspection and deletes/saves/reopens NOTHING, so run it after the '
                      'cleanup and, for the full loop, after the save and reopen. It reports '
                      'blocked, never pass, when the read-back or the round\'s paperwork is not '
                      'usable.')
def mw_scene_cleanup_residue(levelHandle: str, createdByRequestIds: list[str]) -> Any:
    try:
        if (not isinstance(createdByRequestIds, list) or not createdByRequestIds
                or any(not isinstance(v, str) or not v for v in createdByRequestIds)):
            raise BusinessError('CLEANUP_RESIDUE_ROUND_IDS_INVALID',
                                'createdByRequestIds must be the non-empty list of create '
                                'request ids whose round is being confirmed')
        if _CLEANUP_RESIDUE is None:
            raise BusinessError('CLEANUP_RESIDUE_MODULE_UNLOADABLE', _CLEANUP_RESIDUE_ERROR)
        if _CLEANUP_LEGS is None:
            raise BusinessError('CLEANUP_OWNERSHIP_LEGS_UNLOADABLE', _CLEANUP_LEGS_ERROR)
        round_id = _cleanup_round_id(createdByRequestIds)
        round_dir = EVIDENCE_ROOT / 'cleanup' / round_id
        materials_path = round_dir / 'round-materials.json'
        if not materials_path.is_file():
            raise BusinessError(
                'CLEANUP_RESIDUE_ROUND_UNAVAILABLE',
                'this round has no round-materials.json under %s, so its pre-create baseline (the '
                'set of objects that must survive) cannot be read: a residue verdict would have no '
                'survive set to check against.' % round_dir, roundId=round_id,
                materialsPath=str(materials_path))
        materials = _read_json(materials_path)
        level = load_handle(levelHandle)
        materials_level = materials.get('levelId')
        if materials_level is not None and materials_level != level['levelId']:
            raise BusinessError('CLEANUP_RESIDUE_LEVEL_MISMATCH',
                                'the round ran on level %s but the handle is level %s'
                                % (materials_level, level['levelId']),
                                roundId=round_id, handleLevelId=level['levelId'])

        preflight = []
        removed, unknown_requests, removed_source = _cleanup_round_removed_ids(
            round_id, round_dir=round_dir)
        for request_id in unknown_requests:
            preflight.append({'code': 'CLEANUP_JOURNAL_OUTCOME_UNKNOWN',
                              'message': 'the cleanup request %r was attempted and no outcome was '
                                         'recorded, so whether its ids are gone is UNKNOWN -- an '
                                         'unobserved delete is never "no residue".'
                                         % (request_id,)})
        protected = set(_CLEANUP_LEGS.protected_ids_for(level['levelId']))
        extra_protected = _load_protected_ids(level['levelId'])
        if extra_protected:
            protected |= set(extra_protected)
        pre_ids, pre_refusals = _CLEANUP_LEGS.load_pre_baseline(materials.get('preBaseline'))
        for refusal in pre_refusals:
            row = refusal.as_json() if hasattr(refusal, 'as_json') else dict(refusal)
            preflight.append({'code': row.get('code'), 'message': row.get('message')})

        # ONE independent read-only native inspection.  The cleanup route's own not-run
        # reason for this stage is literally 'run a read-back after the cleanup'; this is
        # that read-back, and it is the level's own observation, not a caller's echo.
        level['queue'], helper = resolve_elevated_queue()
        after = inspect_level(level, 'mcpresidue' + uuid.uuid4().hex[:16])

        manifest = {
            'levelId': level['levelId'],
            'removedOwnedIds': removed,
            'unauthorizedIds': sorted(protected | (pre_ids or set())),
            'preflightRefusals': preflight,
            'afterReadback': {'path': after['snapshotPath'], 'levelId': level['levelId']},
        }
        verdict = _CLEANUP_RESIDUE.verify_cleanup_residue(manifest, legs=_CLEANUP_LEGS)
        stage = _stage(verdict['status'] if verdict['status'] in ('pass', 'fail') else 'blocked',
                       reason=verdict.get('reason'))
        return _ok('mw.scene.cleanupResidue', levelId=level['levelId'], roundId=round_id,
                   removedIdsSource=removed_source,
                   removedOwnedIds=verdict['removedOwnedIds'],
                   unauthorizedCount=len(manifest['unauthorizedIds']),
                   residualRemovedIds=verdict['residualRemovedIds'],
                   missingUnauthorizedIds=verdict['missingUnauthorizedIds'],
                   afterEntityCount=verdict['afterEntityCount'],
                   evidence=verdict['evidence'],
                   residue=verdict,
                   liveReadback=_stage('pass', entityCount=after['entities'], run=after['run']),
                   cleanup=stage,
                   persistence=_stage('not-run', reason='this tool does not save'),
                   reopen=_stage('not-run', reason='this tool does not reopen; it judges the level '
                                                   'as it is NOW, so run it after the save and '
                                                   'reopen to mean the after-reopen read-back'),
                   runtime=_stage('not-run'),
                   note="the verdict is the independent read-back's; a delete, save or reopen ack "
                        'is never consulted here')
    except Exception as exc:
        return _fail('mw.scene.cleanupResidue', exc)

#: The F-011 ownership legs: the baseline difference, the round time window and the
#: receipt provenance.  Loaded by path, and FATAL when absent: a route whose ownership
#: check cannot be loaded must not reach the delete route at all.
def _load_cleanup_legs():
    path = ROOT / 'backend/cleanup_ownership_legs.py'
    if not path.is_file():
        return None, 'CLEANUP_LEGS_MODULE_MISSING: %s' % path
    spec = importlib.util.spec_from_file_location('_backend_cleanup_ownership_legs', path)
    if spec is None or spec.loader is None:
        return None, 'CLEANUP_LEGS_MODULE_UNLOADABLE: %s' % path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as error:                          # noqa: BLE001
        sys.modules.pop(spec.name, None)
        return None, 'CLEANUP_LEGS_MODULE_RAISED: %s: %s' % (type(error).__name__, error)
    return module, None


_CLEANUP_LEGS, _CLEANUP_LEGS_ERROR = _load_cleanup_legs()


#: The claim/outcome journal for cleanup dispatches -- the create/save author-journal
#: protocol, keyed on the cleanup request identity instead of a create requestId.
#: Loaded by path and FATAL when absent: a route that cannot record whether a call has
#: already been dispatched must not reach the delete route at all, because the second
#: identical call could not be told from a first one.
def _load_cleanup_journal():
    path = ROOT / 'backend/cleanup_dispatch_journal.py'
    if not path.is_file():
        return None, 'CLEANUP_DISPATCH_JOURNAL_MODULE_MISSING: %s' % path
    spec = importlib.util.spec_from_file_location('_backend_cleanup_dispatch_journal', path)
    if spec is None or spec.loader is None:
        return None, 'CLEANUP_DISPATCH_JOURNAL_MODULE_UNLOADABLE: %s' % path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as error:                          # noqa: BLE001
        sys.modules.pop(spec.name, None)
        return None, 'CLEANUP_DISPATCH_JOURNAL_MODULE_RAISED: %s: %s' % (type(error).__name__, error)
    return module, None


_CLEANUP_DISPATCH_JOURNAL, _CLEANUP_DISPATCH_JOURNAL_ERROR = _load_cleanup_journal()


def _load_cleanup_residue_module():
    path = ROOT / 'backend/cleanup_residue_verification.py'
    if not path.is_file():
        return None, 'CLEANUP_RESIDUE_MODULE_MISSING: %s' % path
    spec = importlib.util.spec_from_file_location('_backend_cleanup_residue_verification', path)
    if spec is None or spec.loader is None:
        return None, 'CLEANUP_RESIDUE_MODULE_UNLOADABLE: %s' % path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as error:                          # noqa: BLE001
        sys.modules.pop(spec.name, None)
        return None, 'CLEANUP_RESIDUE_MODULE_RAISED: %s: %s' % (type(error).__name__, error)
    return module, None


#: D04.03.03: the missing "no residue" comparison, loaded exactly like the legs and the
#: dispatch journal beside it.  A route that cannot load it must not be able to publish a
#: residue verdict, so absence is fatal to the tool, not a silent not-run.
_CLEANUP_RESIDUE, _CLEANUP_RESIDUE_ERROR = _load_cleanup_residue_module()


def _load_protected_ids(level_id):
    """``cleanup_service`` 的 protected_ids_for(level_id)，按路径加载，失败返回 None。

    Why this exists: the legs module's own docstring has always claimed "the wiring
    passes ``cleanup_service``'s constant and a test asserts the two are equal".
    MEASURED 2026-10-04 that claim was false on both halves -- ``judge()`` had no such
    parameter and no test compared them.  This loader is the first half; the test beside
    the legs module is the second.

    Failing to load is NOT fatal here: ``judge()`` resolves this round's own level
    against its own copy of the mapping, so a missing service module still leaves that
    level's ids frozen.  Removing protection is the only thing this can never do.

    RETURNS THE SET FOR ``level_id``, not a flat union (2026-10-08).  The ids are
    (level, id) facts, so a caller must say which level it is asking about; the loading
    contract is otherwise unchanged.
    """
    path = ROOT / 'backend/cleanup_service.py'
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location('_backend_cleanup_service', path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:                                   # noqa: BLE001
        sys.modules.pop(spec.name, None)
        return None
    resolver = getattr(module, 'protected_ids_for', None)
    if resolver is None:
        return None
    try:
        return resolver(level_id)
    except BaseException:                                   # noqa: BLE001
        return None


def _cleanup_round_id(request_ids):
    """A stable id for the round these create requestIds belong to.

    Derived from the requestIds themselves, so the model never supplies it and cannot
    point the lookup at another round's materials.
    """
    digest = hashlib.sha256('\n'.join(sorted(request_ids)).encode('utf-8')).hexdigest()
    return digest[:32]


def _cleanup_dispatch_record_path(round_id):
    """Where the per-round cleanup dispatch MIRROR lives.

    A sibling of the ``round-materials.json`` the route already refuses to proceed
    without, so it is written into a directory this route has already proven exists.

    Kept because it is the shape the re-entry record first landed in, and a reader that
    already looks for it keeps finding it.  It is NOT the authority any more: the
    authoritative record is one claim/outcome pair per REQUEST, under
    ``<round>/dispatch-journal/<requestId>/`` (see ``backend/cleanup_dispatch_journal.py``),
    because a single slot per round could hold only the last command -- an earlier batch
    was forgotten and a repeat of it re-dispatched, and a plain read-then-write let two
    concurrent identical calls both send.  This file is written best-effort for
    compatibility and is never consulted to decide whether a call is a replay.
    """
    return EVIDENCE_ROOT / 'cleanup' / round_id / 'cleanup-dispatch.json'


def _cleanup_transport_request_id(round_id, request_identity):
    """The 32-hex QUEUE identity this cleanup dispatch carries (R05, 2026-10-05).

    Omitted ``--request-id`` makes the transport mint a FRESH uuid per call, so the queue
    file naming a delete had no relation to the request this route had already claimed.  The
    provenance association chain identifies a deletion by that file name
    (``<queueRoot>/<requestId>.submission.json`` -- see ``provenance_association.py``), so
    there was nothing for it to join on, and ``case:P12/cleanup`` could only be witnessed by
    a union of halves.

    The mapping is a DIGEST of the request identity, not a truncation of the business name:
    the same cleanup request always yields the same transport id, and any reader can
    recompute it from the identity the route reports as ``cleanupRequestId``.  That is what
    makes it auditable rather than merely stable -- and it is never re-minted per attempt.

    THE ROUND IS PART OF THE DIGEST (added 2026-10-05 after the R05 review, MEASURED).  The
    journal already scopes a request by round -- ``journal_directory`` is
    ``cleanup/<round_id>/dispatch-journal/<request_id>`` -- but the queue names its files by
    request id ALONE.  A derivation over the identity only therefore collided across rounds:
    the same ``cleanupRequestId`` used in two rounds produced one queue file, so the second
    round's delete was read by the transport as a POLL of the first (or, with a different
    payload, poisoned the request to an unknown outcome once its claim existed).  That
    contradicts the route's own "one name is AT MOST one dispatch" promise, which is scoped
    per round.  Including the round keeps the mapping one-to-one with the journal's own
    notion of a request.
    """
    return hashlib.sha256(
        ('cleanup-transport\0' + str(round_id) + '\0' + str(request_identity))
        .encode('utf-8')).hexdigest()[:32]


def _cleanup_dispatch_key(ids, dry_run, bridge_run_id):
    """What makes two cleanup calls "the same call".

    Narrow on purpose.  A different id set is a different batch (the route is explicitly
    batching, at most ``MAX_CLEANUP_IDS`` at a time), and ``dryRun`` is part of the key so
    that the documented dry-run-then-delete flow still dispatches twice.
    """
    return {'ids': sorted(int(v) for v in ids), 'dryRun': bool(dry_run),
            'bridgeRunId': bridge_run_id}


def _utc_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_json_atomic(path, payload):
    """Write JSON so no reader ever sees a half-written record.

    The scratch file is a sibling of the target, so ``os.replace`` stays on one
    filesystem and is atomic.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + '.part-' + uuid.uuid4().hex[:8])
    scratch.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n',
                       encoding='utf-8', newline='\n')
    os.replace(scratch, path)
    return path


def _known_bridge_runs():
    """The run ids of bridge runs that are actually READY, not merely directories.

    MEASURED 2026-10-02: this used to return every directory under
    ``.runtime/editor-bridge/runs``.  That tree also collects unrelated run
    directories -- the parameter driver files one per run there, holding nothing
    but a ``receipts/`` folder -- and those were reported as "known bridge runs"
    even though no bridge exists behind them.  There were 311 directories and only
    288 carried a ``bridge-ready.json``.

    A ready run is identified by ``bridge-ready.json``, which the loader writes
    only after a successful injection.  Requiring it means the id handed to the
    delete route names a bridge that actually came up.
    """
    root = ROOT / '.runtime/editor-bridge/runs'
    if not root.is_dir():
        return []
    return sorted(entry.name for entry in root.iterdir()
                  if entry.is_dir() and (entry / 'bridge-ready.json').is_file())


@mcp.tool(description='Read one operator-scoped MW_API graph through existing author lookup then inspect. The graph id comes from editor readback; no mutations, bridge loading, or retry. Reports editor fields only, never runtime or persistence acceptance.')
def mw_graph_observe(graphName: str) -> Any:
    try:
        from backend.graph_business import observe
        return _ok('mw.graph.observe', **observe(sys.modules[__name__], graphName))
    except Exception as exc:
        failed = _fail('mw.graph.observe', exc)
        failed.structuredContent['backendKind'] = 'project-editor-graph'
        failed.content = [TextContent(type='text', text=json.dumps(failed.structuredContent, ensure_ascii=False))]
        return failed

def main():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
