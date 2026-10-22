"""Independent post-save verification (T09).

This module answers one question -- *given a save that claims to have happened,
does the evidence on disk actually support the claim?* -- and it answers it in
four parts that are judged separately, because they fail for different reasons
and can be true independently of one another:

  ``saveInvocation``      the native save was actually invoked for *this* case
  ``savedContent``        the content that was supposed to be written did land
  ``allowedDelta``        every byte that changed is inside the allowed set *and* carries a
                          semantic source (``backend/save_delta_attribution.py``); a changed
                          root with no attested source is a defect, a named but unexplained
                          change is blocked, and the save-history root 46 stays blocked
  ``unrelatedUnchanged``  nothing else in the account was touched

Only when all four pass does ``stages.saveDiff.status`` become ``pass``.

What this module deliberately does *not* do
-------------------------------------------
* It does not re-implement any decoder.  Content is decoded by
  ``tools/game-executor/verify-created-save.py`` and the save-delta rules are
  evaluated by the G02 gate (``g02_savediff_gate.py``, the executable form of
  ``docs/cordis-plan/decisions/G02-save-delta.md`` section 5).  Both are run as
  pinned subprocesses; the gate's sha256 is checked against the manifest so a
  looser gate cannot be substituted.  If neither is available the relevant
  stage is ``evidence-insufficient`` -- never ``pass``.
* It does not accept "the file exists", a worker's self-report, a receipt's
  ``ok: true``, or a previous run's verdict as evidence.  Every stage is
  recomputed from bytes now, and the receipt is only accepted when the hashes
  it recorded for the target level equal the hashes of the files this case is
  about.
* It does not treat the unknown root46 (field 46) as an ignorable range.  The
  G02 contract requires its shape to be checked record-by-record and its
  *change* to be carried as a named, unresolved delta, so ``allowedDelta`` can
  never be ``pass`` while root46 moved.  That is the machine-checkable form of
  "an unexplained delta is a findable defect, not an inherited exemption".

Status vocabulary (one vocabulary, used everywhere):

  ``pass``                 the evidence supports the claim
  ``fail``                 the evidence contradicts the claim
  ``blocked``              the evidence is consistent, but a named unknown stands
  ``evidence-insufficient``  the stage cannot be judged from what was supplied

Exit codes for the CLI: 0 = saveDiff pass, 1 = judged non-pass, 2 = cannot judge
(any stage ``evidence-insufficient``) or bad usage.  The per-stage reasons are
always written into the report; the exit code never replaces them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from backend.save_delta_attribution import (attribute_save_delta, level_content_digest,
                                                level_content_view)
except ImportError:  # pragma: no cover - when run as a plain script
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        'save_delta_attribution', Path(__file__).resolve().parent / 'save_delta_attribution.py')
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    attribute_save_delta = _mod.attribute_save_delta
    level_content_view = _mod.level_content_view
    level_content_digest = _mod.level_content_digest

try:
    from backend import content_interpreter_pin as content_pin
except ImportError:  # pragma: no cover - when run as a plain script
    import importlib.util as _ilu_pin
    _spec_pin = _ilu_pin.spec_from_file_location(
        'content_interpreter_pin', Path(__file__).resolve().parent / 'content_interpreter_pin.py')
    _mod_pin = _ilu_pin.module_from_spec(_spec_pin)
    _spec_pin.loader.exec_module(_mod_pin)
    content_pin = _mod_pin

PASS = 'pass'
FAIL = 'fail'
BLOCKED = 'blocked'
INSUFFICIENT = 'evidence-insufficient'

#: Stage name -> the four independent judgements, in report order.
STAGES = ('saveInvocation', 'savedContent', 'allowedDelta', 'unrelatedUnchanged')

#: The account file set a single save is allowed to change (G02 section 2.1).
SAVE_ALLOWED_FILES = (
    'Beyond_Local_Save_Level/{level}/{level}.gil',
    'Temp/{level}.gil',
    'Beyond_Local_Save_Player.gip',
    'Temp/Beyond_Local_Save_Player.gip',
)
#: Prefixes that must never change, whatever the operation (G02 section 2.1).
NEVER_CHANGE_PREFIXES = ('UpgradeBackup/', 'Beyond_Debug_Log/')

CONTENT_VERIFIER_REL = 'tools/game-executor/verify-created-save.py'
GATE_REL = 'g02_savediff_gate.py'
#: Where a freshly run content verifier may write.  verify-created-save.py
#: refuses any --out outside .runtime/game-executor, so this is the one place a
#: T09 run may drop a new file there (T09.md, "文件所有权").
CONTENT_OUT_ROOT = Path('.runtime/game-executor/cordis-plan')

ROOT = Path(__file__).resolve().parents[1]


class ManifestError(ValueError):
    """The manifest itself is unusable (missing/ill-typed fields)."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _live_account_root() -> Path:
    return Path.home() / 'AppData' / 'LocalLow' / 'miHoYo'


def _is_inside_live_account(path: Path) -> bool:
    """True when `path` looks like it lives in the real game save directory.

    Manifest paths must point at *copies*.  Reading the live account is the one
    thing this module must never be talked into, so the check is by resolved
    path and by the ``BeyondLocal`` marker, not by string prefix alone.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if 'BeyondLocal' in resolved.parts:
        return True
    live = _live_account_root()
    try:
        return resolved.is_relative_to(live)
    except (OSError, ValueError):
        return False


def _stable_read(path: Path, reader=None) -> bytes:
    """Read a file twice and require both reads to be identical.

    A file that changes between the two reads cannot be the subject of a
    verdict: the before/after pair would no longer describe one snapshot.  The
    ``reader`` seam exists so a test can make the instability deterministic.
    """
    read = reader or (lambda p: Path(p).read_bytes())
    first = read(path)
    second = read(path)
    if first != second:
        raise UnstableSnapshot(f'{path} changed between two reads of the same file')
    return first


class UnstableSnapshot(RuntimeError):
    """A source file did not hold still long enough to be judged."""


def _entry(manifest, key, *, required=True):
    """Pull one sub-object out of a manifest.  Shape is checked where it is used."""
    section = manifest.get(key)
    if section is None:
        if required:
            raise ManifestError(f'manifest is missing {key}')
        return None
    if not isinstance(section, dict):
        raise ManifestError(f'{key} must be an object')
    return section


def _load_bound_bytes(entry, reader=None):
    """Return the bytes of a {path, sha256} entry, after checking both senses.

    The path must not be the live account, the file must hold still, and the
    on-disk sha256 must equal the recorded one.  All three failures are
    ``UnstableSnapshot``/``ValueError`` rather than silent fallbacks.
    """
    path = Path(entry['path'])
    if not path.is_absolute():
        raise ManifestError(f'{path} is not absolute')
    if _is_inside_live_account(path):
        raise ManifestError(f'{path} is inside the live game save directory; supply a copy')
    blob = _stable_read(path, reader)
    digest = _sha256(blob)
    recorded = entry.get('sha256')
    if recorded and recorded.lower() != digest:
        raise HashMismatch(f'{path} is {digest}, the manifest records {recorded}')
    return blob, digest


class HashMismatch(RuntimeError):
    """A file on disk no longer matches the hash the manifest pinned."""


def _fold(statuses):
    """One vocabulary, one precedence, used for stages and for the aggregate.

    A contradiction outranks an inability to judge, which outranks a named
    unknown, which outranks success.  Nothing at all reads as
    ``evidence-insufficient`` -- an empty check list must never be success.
    """
    if not statuses:
        return INSUFFICIENT
    if FAIL in statuses:
        return FAIL
    if INSUFFICIENT in statuses:
        return INSUFFICIENT
    if BLOCKED in statuses:
        return BLOCKED
    return PASS if all(s == PASS for s in statuses) else INSUFFICIENT


def _stage(findings):
    return {'status': _fold([f['status'] for f in findings]), 'findings': findings}


def _f(check_id, ok, detail=None, status=None):
    return {'id': check_id, 'status': status or (PASS if ok else FAIL), 'detail': detail}


# --------------------------------------------------------------------------- #
# discovery of the two reused decoders
# --------------------------------------------------------------------------- #

def _discover_gate(manifest):
    """Locate the G02 gate.  Never guesses a substitute implementation.

    Order: the manifest's own pinned path, then this repo's vendored copy, then the
    runtime workstream directory.

    WHY A VENDORED COPY EXISTS (added 2026-10-04): until then the gate lived ONLY under
    ``.runtime/cordis-plan-work/G02/*/checks/`` -- gitignored, untracked space.  A
    ``git clean -xdf``, a disk wipe or a tidy-up of that workstream directory would leave
    ``_discover_gate`` returning None, and the ``allowedDelta`` stage would degrade to
    evidence-insufficient PERMANENTLY, silently taking the persistence chain with it.
    ``tools/game-executor/vendor/g02_savediff_gate.py`` is a BYTE-IDENTICAL copy
    (sha256 9075c4d68a6b049fe760c98c58aa96701f58d99744b69f72cf6e5091d2b536cd); the
    manifest's own ``g02Gate.sha256`` is still checked downstream, so a vendored gate that
    is not the pinned gate is refused exactly as before -- this changes WHERE the bytes are
    found, never WHICH bytes are required.
    """
    pinned = manifest.get('g02Gate') or {}
    candidates = []
    if pinned.get('path'):
        candidates.append(Path(pinned['path']))
    candidates.append(ROOT / 'tools' / 'game-executor' / 'vendor' / GATE_REL)
    base = ROOT / '.runtime' / 'cordis-plan-work' / 'G02'
    if base.is_dir():
        candidates.extend(sorted(base.glob(f'*/checks/{GATE_REL}')))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _discover_content_python(manifest, runner=None, timeout=60):
    """Locate the one interpreter that can deserialise the save format.

    PINNED, NOT GUESSED (W12, 2026-10-05).  This function used to fall back to
    ``%LOCALAPPDATA%/Programs/Python/Python313/python.exe``.  That guess is right
    on exactly one machine, which is precisely its danger: it degrades silently
    everywhere else, and it accepts a substituted interpreter at the same path
    without a murmur.  Discovery now reads the committed pin
    (``config/save-content-interpreter.lock.json``, see
    ``backend/content_interpreter_pin.py``) and returns a path only when every
    recorded fact still holds; the named reason for any refusal is produced by
    :func:`_resolve_content_python`.
    """
    return _resolve_content_python(manifest, runner=runner, timeout=timeout)['python']


def _resolve_content_python(manifest, runner=None, timeout=60):
    """Resolve the pinned interpreter and turn every fact into a named finding.

    The old discovery path also honoured ``manifest['contentPython']`` and
    ``DS_SAVE_CONTENT_PYTHON`` -- an explicit interpreter *path* carrying no
    digest, which is the same silent hole in a different coat: point it anywhere
    and the decoder runs there unreviewed.  Those two sources are now refused by
    name (``BLOCKED``), and the pin is the only way in.  Relocating the *pin* is
    still possible: name another pin file with ``manifest['contentPythonPin']``
    or ``DS_SAVE_CONTENT_PYTHON_PIN``.
    """
    pin_path = content_pin.pin_file_path(ROOT, override=manifest.get('contentPythonPin'))
    facts = content_pin.verify(pin_path=pin_path, project_root=ROOT, run=runner, timeout=timeout)
    findings = []
    findings.append(_f('content.interpreterPinned', facts['pinLoaded'],
                       {'pinPath': facts['pinPath'], 'error': facts['pinError'],
                        'reason': facts.get('reason'),
                        'rule': 'the content interpreter is pinned (path + sha256 + version); an '
                                'absent, ill-typed, or drifted pin is refused, never replaced by '
                                'a guess of %LOCALAPPDATA%\\Programs\\Python'},
                       None if facts['pinLoaded'] else INSUFFICIENT))
    if not facts['pinLoaded']:
        return {'python': None, 'findings': findings, 'facts': facts}
    findings.append(_f('content.interpreterPath', facts['pathExists'],
                       {'path': facts['interpreterPath'], 'reason': facts.get('reason')},
                       PASS if facts['pathExists'] else INSUFFICIENT))
    findings.append(_f('content.interpreterDigest', facts['sha256Matches'],
                       {'expected': facts['sha256Expected'], 'actual': facts['sha256Actual'],
                        'reason': facts.get('reason'),
                        'rule': 'an interpreter whose bytes differ from the pin is a different '
                                'interpreter and is refused BEFORE it is executed'},
                       PASS if facts['sha256Matches'] else FAIL))
    findings.append(_f('content.interpreterVersion', facts['versionMatches'],
                       {'expected': facts['versionExpected'], 'actual': facts['versionActual'],
                        'reason': facts.get('reason')},
                       PASS if facts['versionMatches'] else FAIL))
    findings.append(_f('content.dependenciesImportable',
                       bool(facts['protobufImportable']) and facts['decoderDeps'] is True,
                       {'protobuf': facts['protobufActual'], 'protobufError': facts['protobufError'],
                        'decoderDeps': facts['decoderDeps'],
                        'decoderDepsError': facts['decoderDepsError'],
                        'dependencySource': facts['dependencySourceRel'],
                        'dependencySourceExists': facts['dependencySourceExists'],
                        'reason': facts.get('reason'),
                        'rule': 'a missing dependency is named here, not discovered as an '
                                'unparseable verifier subprocess'},
                       PASS if (facts['protobufImportable'] and facts['decoderDeps'] is True)
                       else INSUFFICIENT))
    findings.append(_f('content.dependencyVersions', facts['protobufMatches'],
                       {'protobufExpected': facts['protobufExpected'],
                        'protobufActual': facts['protobufActual'],
                        'reason': facts.get('reason')},
                       PASS if facts['protobufMatches'] else FAIL))
    findings.append(_f('content.decoderDigest', facts['decoderShaMatches'],
                       {'decoderPath': facts['decoderPath'],
                        'expected': facts['decoderShaExpected'], 'actual': facts['decoderShaActual'],
                        'reason': facts.get('reason'),
                        'rule': 'a different content verifier must not be substituted for the '
                                'pinned one, exactly as _discover_gate refuses a different gate'},
                       PASS if facts['decoderShaMatches'] else
                       (FAIL if facts['decoderShaActual'] else INSUFFICIENT)))
    # The requirement is not only to refuse drift but to RECORD what was actually
    # used, so a report can be read without re-deriving it from the machine.
    findings.append(_f('content.interpreterRecorded', True, facts.get('recorded') or {}))
    # An unpinned explicit override is a named unknown, not a silent success.
    if manifest.get('contentPython') or os.environ.get('DS_SAVE_CONTENT_PYTHON'):
        findings.append(_f('content.unpinnedOverrideRefused', False,
                           {'manifestContentPython': manifest.get('contentPython'),
                            'envDsSaveContentPython': bool(os.environ.get('DS_SAVE_CONTENT_PYTHON')),
                            'rule': 'an interpreter path with no digest is not a pin; set '
                                    'DS_SAVE_CONTENT_PYTHON_PIN / manifest.contentPythonPin to '
                                    'relocate the PIN instead'},
                           BLOCKED))
    resolved = facts['interpreterPath'] if all(f['status'] == PASS for f in findings) else None
    return {'python': resolved, 'findings': findings, 'facts': facts}


def _run(argv, timeout):
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    return {
        'argv': argv,
        'returncode': proc.returncode,
        'stdout': proc.stdout.decode('utf-8', 'replace'),
        'stderr': proc.stderr.decode('utf-8', 'replace'),
    }


def _json_of(result):
    try:
        return json.loads(result['stdout'])
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# stage 1 -- saveInvocation
# --------------------------------------------------------------------------- #

def _receipt(manifest):
    """Return (receipt, finding-status) for the case's native save receipt."""
    inline = manifest.get('receipt')
    entry = manifest.get('receiptPath')
    if inline is not None:
        return inline, None
    if entry is not None:
        blob, _ = _load_bound_bytes(entry)
        return json.loads(blob.decode('utf-8')), None
    return None, 'no receipt or receiptPath in the manifest'


def _stage_save_invocation(manifest, reader=None):
    findings = []
    try:
        receipt, missing = _receipt(manifest)
    except (ManifestError, HashMismatch, UnstableSnapshot, OSError, ValueError) as exc:
        receipt, missing = None, str(exc)
    if receipt is None:
        findings.append(_f('invocation.receiptPresent', False, missing, INSUFFICIENT))
        return _stage(findings)

    backend = receipt.get('backend') or {}
    case_request = manifest.get('requestId')
    level = str(manifest.get('levelId'))

    findings.append(_f('invocation.requestBound',
                       bool(case_request) and receipt.get('requestId') == case_request,
                       {'caseRequestId': case_request, 'receiptRequestId': receipt.get('requestId'),
                        'rule': 'a receipt for another request must not be re-used for this case'}))
    # A replayed receipt answers a request that was already answered.  The
    # project derives "live" from a non-replay plus a recorded native call; a
    # replay is a named unknown here, not a pass.
    findings.append(_f('invocation.notReplayed', receipt.get('replayed') is not True,
                       {'replayed': receipt.get('replayed'),
                        'rule': 'a replayed receipt is reconciled against its original run, '
                                'it does not evidence a fresh invocation'},
                       BLOCKED if receipt.get('replayed') is True else PASS))
    findings.append(_f('invocation.nativeStarted', backend.get('nativeStarted') is True,
                       {'nativeStarted': backend.get('nativeStarted')}))
    findings.append(_f('invocation.nativeCalled', bool(backend.get('called')),
                       {'called': backend.get('called')}))
    findings.append(_f('invocation.nativeStatus',
                       backend.get('actionStatus') == 0 and backend.get('nativeStatus') == 0,
                       {'actionStatus': backend.get('actionStatus'),
                        'nativeStatus': backend.get('nativeStatus')}))
    findings.append(_f('invocation.targetLevel', str(backend.get('levelId')) == level,
                       {'receiptLevelId': backend.get('levelId'), 'caseLevelId': manifest.get('levelId')}))
    changed = backend.get('gilChanged') or {}
    findings.append(_f('invocation.targetGilChanged', changed.get(level) is True,
                       {'gilChanged': changed, 'target': level,
                        'rule': 'the receipt must itself claim the target level changed'}))

    # The binding that makes "swap an old successful receipt in" fail: the
    # receipt's own hashes for the target level must be the hashes of the files
    # this case is about.  Reading the case's own files and comparing the
    # receipt against them are two different failures: an unreadable or
    # repinned case cannot be judged (insufficient), a readable case whose
    # receipt describes other bytes is a contradiction (fail).
    try:
        gil_before = _entry(manifest, 'files')['gilBefore']
        gil_after = _entry(manifest, 'files')['gilAfter']
        _, digest_before = _load_bound_bytes(gil_before, reader)
        _, digest_after = _load_bound_bytes(gil_after, reader)
    except (ManifestError, HashMismatch, UnstableSnapshot, OSError, KeyError, TypeError) as exc:
        findings.append(_f('invocation.caseFilesReadable', False, str(exc), INSUFFICIENT))
    else:
        findings.append(_f('invocation.caseFilesReadable', True,
                           {'gilBefore': digest_before, 'gilAfter': digest_after}))
        recorded_before = (backend.get('beforeGils') or {}).get(level, {}).get('sha256')
        recorded_after = (backend.get('afterGils') or {}).get(level, {}).get('sha256')
        findings.append(_f('invocation.receiptHashesBound',
                           recorded_before == digest_before and recorded_after == digest_after,
                           {'recordedBefore': recorded_before, 'caseBefore': digest_before,
                            'recordedAfter': recorded_after, 'caseAfter': digest_after}))

    # The native run directory the receipt names must still be on disk; a
    # receipt whose run directory is gone describes a workspace we cannot
    # inspect any more.
    run_dir = backend.get('run')
    run_present = bool(run_dir) and os.path.isdir(run_dir)
    findings.append(_f('invocation.nativeRunPresent', run_present,
                       {'run': run_dir},
                       PASS if run_present else INSUFFICIENT))
    return _stage(findings)


# --------------------------------------------------------------------------- #
# stage 2 -- savedContent
# --------------------------------------------------------------------------- #

def _content_report_from_file(manifest, findings, reader=None):
    entry = manifest.get('contentReport')
    if entry is None:
        return None
    try:
        blob, _ = _load_bound_bytes(entry, reader)
        return json.loads(blob.decode('utf-8'))
    except (ManifestError, HashMismatch, UnstableSnapshot, OSError, ValueError) as exc:
        findings.append(_f('content.reportBinding', False, str(exc), INSUFFICIENT))
        return None


def _content_report_from_run(manifest, findings, timeout, runner):
    resolution = _resolve_content_python(manifest, runner=runner, timeout=timeout)
    findings.extend(resolution['findings'])
    python = resolution['python']
    if not python:
        return None
    verifier = ROOT / CONTENT_VERIFIER_REL
    if not verifier.is_file():
        findings.append(_f('content.verifierPresent', False, str(verifier), INSUFFICIENT))
        return None
    files = _entry(manifest, 'files')
    intent = manifest.get('intent') or {}
    run_id = str(manifest.get('runId') or 'unknown')
    out = (ROOT / CONTENT_OUT_ROOT / f'{run_id}-{manifest.get("caseId", "case")}' /
           'DS-05' / f'content-{manifest.get("caseId", "case")}.json')
    if out.exists():
        findings.append(_f('content.outputFresh', False,
                           f'{out} already exists; a verifier output is never overwritten, so this '
                           f'case cannot be judged here', INSUFFICIENT))
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [python, '-B', str(verifier), files['gilBefore']['path'], files['gilAfter']['path'],
            '--entity-id', str(intent.get('entityId')), '--template-id', str(intent.get('templateId')),
            '--name', str(intent.get('name')),
            '--position'] + [repr(v) for v in intent.get('position', [])] + \
           ['--rotation'] + [repr(v) for v in intent.get('rotation', [])] + \
           ['--scale'] + [repr(v) for v in intent.get('scale', [])] + ['--out', str(out)]
    result = runner(argv, timeout)
    if result['returncode'] not in (0, 1):
        findings.append(_f('content.verifierRan', False,
                           {'returncode': result['returncode'], 'stderr': result['stderr'][-400:]},
                           INSUFFICIENT))
        return None
    report = _json_of(result)
    if report is None:
        findings.append(_f('content.verifierRan', False,
                           {'returncode': result['returncode'],
                            'stdout': result['stdout'][-400:]}, INSUFFICIENT))
        return None
    report['_verifierReturncode'] = result['returncode']
    return report


def _stage_noop_content(manifest, findings, reader=None):
    """Judge a save that declares no entity delta as a legal no-op.

    The reused content decoder is create-shaped: it needs exactly one newly added
    root5 entity, so it can say nothing about a save that declares nothing.  The
    one judgement that needs no decoder is whether the level container's SEMANTIC
    content moved at all -- its root5 entity records and its root6 registry tree
    (``save_delta_attribution.level_content_view``).  root46 (the save-history
    head) is deliberately NOT part of that view: its meaning is unestablished and
    its movement is carried by the ``allowedDelta`` stage as a named blocked
    delta, exactly as it is for every other save.

    A declared-empty save whose content is unchanged is a LEGAL NO-OP -> ``pass``.
    A declared-empty save whose content moved is not judged here (there is no
    decoder for an undeclared change) -> ``evidence-insufficient``, never a pass;
    the ``allowedDelta`` stage names it as the defect it is.
    """
    try:
        files = _entry(manifest, 'files')
        before_blob, digest_before = _load_bound_bytes(files['gilBefore'], reader)
        after_blob, digest_after = _load_bound_bytes(files['gilAfter'], reader)
    except (ManifestError, HashMismatch, UnstableSnapshot, OSError, KeyError, TypeError) as exc:
        findings.append(_f('content.noOpSnapshotStable', False, str(exc), INSUFFICIENT))
        return _stage(findings)
    findings.append(_f('content.noOpSnapshotStable', True,
                       {'gilBefore': digest_before, 'gilAfter': digest_after}))
    try:
        view_before = level_content_view(before_blob)
        view_after = level_content_view(after_blob)
    except (ValueError, IndexError) as exc:
        findings.append(_f('content.noOpJudgeable', False,
                           {'error': str(exc),
                            'rule': 'a container that does not read as this level format cannot be '
                                    'compared, so the case is not judged rather than passed'},
                           INSUFFICIENT))
        return _stage(findings)
    unchanged = view_before == view_after
    detail = {'contentBefore': level_content_digest(view_before),
              'contentAfter': level_content_digest(view_after),
              'entityRecords': len(view_after['entityRecords']),
              'registryRefs': len(view_after['registryRefs']),
              'declaredDelta': manifest.get('entityDelta') or {},
              'rule': 'a save that declares no entity delta is admitted as a LEGAL NO-OP only when '
                      'the level content (root5 records + root6 registry) is unchanged; root46 is '
                      'carried by the allowedDelta stage and is not judged as content here'}
    findings.append(_f('content.noOpAdmitted', unchanged, detail,
                       None if unchanged else INSUFFICIENT))
    findings.append(_f('content.decoderLimitationsCarried', True,
                       {'limitations': ['no create-shaped decoder is run for a declared-empty save; '
                                        'the judgement is level-content equality, not a decode']}))
    return _stage(findings)


def _stage_saved_content(manifest, reader=None, runner=None, timeout=300):
    findings = []
    runner = runner or _run
    # ``manifest.get('operation', 'save')`` -- WITH the default, as every other lookup in
    # this module uses (:490, :645, :693, :720).  Without it an ABSENT operation key reads
    # as "not a save", so the guard below does not fire and the stage walks into the
    # decoder path it exists to refuse.  MEASURED 2026-10-04: this was the only site in
    # the file omitting the default, so omitting the key was a one-token bypass of a
    # guard whose whole purpose is to refuse an unjudgeable case rather than pass it.
    #
    # The guard used to refuse the WHOLE stage (``evidence-insufficient``) whenever no
    # entity delta was declared.  That is right for the create-shaped decoder and wrong
    # for the one case the tree does have evidence about: a LEGAL NO-OP (leaf D23.01.02)
    # -- a save that declares nothing because nothing changed.  Such a save needs no
    # decoder, only the before/after content comparison in _stage_noop_content.  A
    # declared-empty save whose content DID change still has no decoder here and stays
    # ``evidence-insufficient`` -- and is named a defect by the allowedDelta stage.
    if manifest.get('operation', 'save') == 'save' and not (manifest.get('entityDelta') or {}).get('addedIds'):
        return _stage_noop_content(manifest, findings, reader)
    try:
        files = _entry(manifest, 'files')
        _, digest_before = _load_bound_bytes(files['gilBefore'], reader)
        _, digest_after = _load_bound_bytes(files['gilAfter'], reader)
        findings.append(_f('content.snapshotStable', True,
                           {'gilBefore': digest_before, 'gilAfter': digest_after}))
    except (ManifestError, HashMismatch, UnstableSnapshot, OSError, KeyError, TypeError) as exc:
        findings.append(_f('content.snapshotStable', False, str(exc), INSUFFICIENT))
        return _stage(findings)

    report = _content_report_from_file(manifest, findings, reader)
    if report is None and not any(f['status'] == INSUFFICIENT for f in findings):
        report = _content_report_from_run(manifest, findings, timeout, runner)
    if report is None:
        return _stage(findings)

    intent = manifest.get('intent') or {}
    recorded = {i.get('sha256') for i in report.get('inputs') or []}
    findings.append(_f('content.decoderInputsBound',
                       recorded == {digest_before, digest_after},
                       {'decoderInputs': sorted(x for x in recorded if x),
                        'caseInputs': sorted({digest_before, digest_after}),
                        'rule': 'a decoder report about other files is not evidence about these'}))
    findings.append(_f('content.decoderAccepted', report.get('ok') is True,
                       {'ok': report.get('ok'), 'error': report.get('error'),
                        'verifierReturncode': report.get('_verifierReturncode')}))
    findings.append(_f('content.exactlyOneNewEntity',
                       report.get('exactly_one_new_entity') is True
                       and report.get('entity_id') == intent.get('entityId'),
                       {'reported': report.get('entity_id'), 'intent': intent.get('entityId')}))
    findings.append(_f('content.identity',
                       report.get('template_id') == intent.get('templateId')
                       and report.get('name') == intent.get('name'),
                       {'reportedTemplate': report.get('template_id'),
                        'intentTemplate': intent.get('templateId'),
                        'reportedName': report.get('name'), 'intentName': intent.get('name')}))
    findings.append(_f('content.levelIdentity',
                       bool(manifest.get('levelName'))
                       and report.get('level_name') == manifest.get('levelName'),
                       {'reported': report.get('level_name'), 'expected': manifest.get('levelName')},
                       BLOCKED if not manifest.get('levelName') else None))
    findings.append(_f('content.otherRecordsPreserved',
                       report.get('other_entity_raw_records_preserved') is True
                       and report.get('old_node_graph_section_bytes_preserved') is True,
                       {'entityRecords': report.get('other_entity_raw_records_preserved'),
                        'oldGraphBytes': report.get('old_node_graph_section_bytes_preserved')}))
    findings.append(_f('content.decoderLimitationsCarried',
                       True, {'limitations': report.get('limitations')}))
    return _stage(findings)


# --------------------------------------------------------------------------- #
# stage 3 -- allowedDelta (delegated to the pinned G02 gate)
# --------------------------------------------------------------------------- #

def build_gate_case(manifest):
    """Translate a T09 manifest into the G02 gate's case shape.

    Paths only; no verdicts.  Kept separate so it can be asserted on directly.
    """
    files = _entry(manifest, 'files')
    case = {
        'caseId': manifest.get('caseId'),
        'operation': manifest.get('operation', 'save'),
        'levelId': str(manifest.get('levelId')),
        'gilBefore': files['gilBefore']['path'], 'gilAfter': files['gilAfter']['path'],
        'gipBefore': files['gipBefore']['path'], 'gipAfter': files['gipAfter']['path'],
        'declaredChangedRoots': manifest.get('declaredChangedRoots') or [],
        'declaredChangedGipEntries': manifest.get('declaredChangedGipEntries') or [],
        'entityDelta': manifest.get('entityDelta') or {},
    }
    target = manifest.get('targetLevel') or {}
    if target.get('tempMirrorBefore') and target.get('tempMirrorAfter'):
        case['targetLevel'] = {'tempMirrorBefore': target['tempMirrorBefore']['path'],
                               'tempMirrorAfter': target['tempMirrorAfter']['path']}
    if manifest.get('saveWallClock') is not None:
        case['saveWallClock'] = manifest['saveWallClock']
    protected = manifest.get('protectedLevels') or {}
    if protected:
        case['protectedLevels'] = {
            str(level): {'gilBefore': pair['gilBefore']['path'],
                         'gilAfter': pair['gilAfter']['path'],
                         'tempMirrorBefore': pair['tempMirrorBefore']['path'],
                         'tempMirrorAfter': pair['tempMirrorAfter']['path']}
            for level, pair in protected.items()}
    return case


def build_attribution_case(manifest):
    """The gate case shape plus the fields only the attribution layer needs.

    The attribution layer re-reads the same bytes the gate read and asks a
    different question -- *why* each changed root is allowed -- so it must see
    the declared intent, the account snapshots and the mirror paths.
    """
    case = build_gate_case(manifest)
    case['intent'] = manifest.get('intent') or {}
    target = case.get('targetLevel') or {}
    if target:
        case['targetTempMirrorBefore'] = target['tempMirrorBefore']
        case['targetTempMirrorAfter'] = target['tempMirrorAfter']
    account = manifest.get('accountSet')
    if account:
        case['accountSet'] = {'before': account['before']['path'],
                              'after': account['after']['path']}
    return case


def _stage_allowed_delta(manifest, runner=None, timeout=300, out_dir=None):
    findings = []
    runner = runner or _run
    gate = _discover_gate(manifest)
    if gate is None:
        findings.append(_f('delta.gatePresent', False,
                           'the G02 save-delta gate was not found; the delta must not be judged by a '
                           'substitute implementation', INSUFFICIENT))
        return _stage(findings)
    pinned = (manifest.get('g02Gate') or {}).get('sha256')
    gate_digest = _sha256(gate.read_bytes())
    if pinned and pinned.lower() != gate_digest:
        findings.append(_f('delta.gatePinned', False,
                           {'onDisk': gate_digest, 'pinned': pinned},
                           INSUFFICIENT))
        return _stage(findings)
    findings.append(_f('delta.gatePinned', True, {'gate': str(gate), 'sha256': gate_digest}))

    try:
        case = build_gate_case(manifest)
    except (ManifestError, KeyError, TypeError) as exc:
        findings.append(_f('delta.caseBuilt', False, str(exc), INSUFFICIENT))
        return _stage(findings)
    scratch = (out_dir or (ROOT / '.runtime' / 'cordis-plan-work' / 'DS-05-parallel-20261002' / 'cases'
                           / str(manifest.get('caseId') or 'case')))
    scratch.mkdir(parents=True, exist_ok=True)
    case_path = scratch / 'gate-case.json'
    findings_path = scratch / 'gate-findings.json'
    if findings_path.exists():
        findings_path.unlink()
    case_path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding='utf-8')
    python = sys.executable
    result = runner([python, '-B', str(gate), '--case', str(case_path), '--out', str(findings_path)],
                    timeout)
    # The authoritative verdict is the artifact the gate writes, not the one-line
    # summary it prints -- the summary names the blocked list `blocked` while the
    # artifact names it `blockedNamedDeltas`, and reading the wrong one turns a
    # blocked save into a pass.
    if not findings_path.is_file():
        findings.append(_f('delta.gateRan', False,
                           {'returncode': result['returncode'], 'stderr': result['stderr'][-400:]},
                           INSUFFICIENT))
        return _stage(findings)
    verdict = json.loads(findings_path.read_text(encoding='utf-8'))
    summary = _json_of(result) or {}
    findings.append(_f('delta.gateSummaryAgrees', summary.get('verdict') == verdict.get('verdict'),
                       {'summary': summary.get('verdict'), 'artifact': verdict.get('verdict'),
                        'rule': 'the gate printed a verdict that disagrees with the verdict it wrote'},
                       INSUFFICIENT if summary.get('verdict') != verdict.get('verdict') else PASS))
    raw = verdict.get('verdict')
    mapped = {PASS: PASS, BLOCKED: BLOCKED, FAIL: FAIL}.get(raw)
    findings.append(_f('delta.gateVerdict', mapped is not None,
                       {'verdict': raw, 'gateReturncode': result['returncode'],
                        'defects': [x['id'] for x in verdict.get('findings', [])
                                    if x.get('status') != PASS],
                        'blockedNamedDeltas': verdict.get('blockedNamedDeltas')},
                       mapped if mapped != PASS else None))
    findings.append({'id': 'delta.gateFindings', 'status': PASS,
                     'detail': verdict.get('findings')})
    if verdict.get('blockedNamedDeltas'):
        findings.append(_f('delta.noInheritedExemption', False,
                           {'blocked': verdict['blockedNamedDeltas'],
                            'rule': 'a named unexplained delta keeps this stage short of pass; root46 '
                                    '(field 46) has no established meaning, so a save that moved it '
                                    'cannot be a pass here'},
                           BLOCKED))

    # The gate judges the *shape* of the delta and never asks why it is allowed.
    # Its ``allowed_shape = {5, 6, 46}`` in particular lets root 5 and root 6
    # change without any declaration, so an in-place rewrite of an existing
    # entity record passes every gate check.  Attribute every changed root to a
    # semantic source before this stage is folded.
    try:
        attribution = attribute_save_delta(build_attribution_case(manifest))
    except (ManifestError, KeyError, TypeError, ValueError, OSError) as exc:
        findings.append(_f('delta.attributionRan', False, str(exc), INSUFFICIENT))
    else:
        findings.append(_f('delta.attributionRan', True,
                           {'verdict': attribution['verdict'],
                            'attestedChangedRoots': attribution['attestedChangedRoots']}))
        for item in attribution['findings']:
            findings.append({'id': item['id'], 'status': item['status'],
                             'detail': {'semanticSource': item['semanticSource'],
                                        'detail': item['detail']}})
        if attribution['verdict'] != PASS:
            findings.append(_f('delta.deltaAttribution', False,
                               {'verdict': attribution['verdict'],
                                'blocked': [b['name'] for b in attribution['blockedNamedDeltas']],
                                'rule': 'every allowed delta must name a semantic source; an '
                                        'unattested change is a defect, a named but unexplained '
                                        'change is blocked, and ignoring a whole root is never '
                                        'available'},
                               FAIL if attribution['verdict'] == FAIL else BLOCKED))
    return _stage(findings)


# --------------------------------------------------------------------------- #
# stage 4 -- unrelatedUnchanged
# --------------------------------------------------------------------------- #

def _account_set(manifest):
    section = manifest.get('accountSet')
    if section is None:
        return None
    return _entry(section, 'before'), _entry(section, 'after')


def _stage_unrelated_unchanged(manifest, reader=None):
    findings = []
    level = str(manifest.get('levelId'))
    operation = manifest.get('operation', 'save')

    protected = manifest.get('protectedLevels') or {}
    if not protected:
        findings.append(_f('unrelated.protectedLevelsDeclared', False,
                           'no protectedLevels in the manifest: "nothing else changed" was not '
                           'given anything to be checked against', INSUFFICIENT))
    same_levels = True
    unreadable = []
    detail = {}
    for name, pair in protected.items():
        try:
            before_gil = _stable_read(Path(pair['gilBefore']['path']), reader)
            after_gil = _stable_read(Path(pair['gilAfter']['path']), reader)
            before_mirror = _stable_read(Path(pair['tempMirrorBefore']['path']), reader)
            after_mirror = _stable_read(Path(pair['tempMirrorAfter']['path']), reader)
        except (KeyError, TypeError, OSError, UnstableSnapshot) as exc:
            # A file that moved, or that cannot be read, is not evidence of a
            # change: it is the absence of evidence, and it is reported as such.
            detail[name] = {'error': str(exc)}
            unreadable.append(name)
            continue
        detail[name] = {'gilUnchanged': before_gil == after_gil,
                        'mirrorUnchanged': before_mirror == after_mirror}
        same_levels = same_levels and before_gil == after_gil and before_mirror == after_mirror
    if protected:
        findings.append(_f('unrelated.protectedLevels', same_levels, detail,
                           INSUFFICIENT if unreadable else None))
        if unreadable:
            findings.append(_f('unrelated.protectedLevelsReadable', False,
                               {'unreadable': sorted(unreadable)}, INSUFFICIENT))

    sets = _account_set(manifest)
    if sets is None:
        findings.append(_f('unrelated.accountSetDeclared', False,
                           'no accountSet in the manifest: the account-level statement "only the four '
                           'allowed files changed" was not supplied', INSUFFICIENT))
    else:
        try:
            before_entry, after_entry = sets
            before_blob, _ = _load_bound_bytes(before_entry, reader)
            after_blob, _ = _load_bound_bytes(after_entry, reader)
            before_files = {f['relpath']: f['sha256'] for f in json.loads(before_blob)['files']}
            after_files = {f['relpath']: f['sha256'] for f in json.loads(after_blob)['files']}
            findings.append(_f('unrelated.accountSetSameShape',
                               set(before_files) == set(after_files),
                               {'before': len(before_files), 'after': len(after_files)}))
            changed = sorted(k for k in before_files if before_files[k] != after_files.get(k))
            allowed = {p.format(level=level) for p in SAVE_ALLOWED_FILES} if operation in ('save', 'delete') else set()
            extra = [k for k in changed if k not in allowed]
            forbidden = [k for k in changed if k.startswith(NEVER_CHANGE_PREFIXES)]
            findings.append(_f('unrelated.accountChangedSet', not extra and not forbidden,
                               {'changed': changed, 'allowed': sorted(allowed),
                                'unexpected': extra, 'neverChangePrefixesHit': forbidden,
                                'rule': 'a single save may change exactly the target gil, its Temp '
                                        'mirror, and the profile and its Temp mirror'}))
        except (ManifestError, HashMismatch, UnstableSnapshot, OSError, KeyError, TypeError) as exc:
            findings.append(_f('unrelated.accountSetReadable', False, str(exc), INSUFFICIENT))
    return _stage(findings)


# --------------------------------------------------------------------------- #
# aggregate
# --------------------------------------------------------------------------- #

def verify_saved_case(manifest, *, reader=None, runner=None, timeout=300, out_dir=None):
    """Judge a save case.  Returns the report dict; never raises for bad evidence.

    ``reader`` and ``runner`` are test seams: ``reader(path)->bytes`` and
    ``runner(argv, timeout)->{'returncode','stdout','stderr'}``.
    """
    report = {
        'scope': 'save_verification',
        'caseId': manifest.get('caseId'),
        'runId': manifest.get('runId'),
        'operation': manifest.get('operation', 'save'),
        'levelId': manifest.get('levelId'),
        'requestId': manifest.get('requestId'),
        'ok': False,
        'stages': {},
        'limitations': [
            'saveInvocation proves a native call was recorded for this request and bound to these '
            'files; it does not prove the game displayed the result.',
            'savedContent is produced by the reused create-shaped decoder, or -- for a save that '
            'declares no entity delta -- by comparing the level content before/after (a legal no-op '
            'is admitted on content equality, never on a byte match alone); either way it is '
            'evidence about the level container bytes, not about the running scene.',
            'allowedDelta is the pinned G02 gate verdict; root46 (field 46) has no established '
            'meaning, so a save that moved it can never reach pass here.',
            'Nothing in this module proves a reopen, a playtest, or cleanup; those are separate '
            'stages of T05/T11/T10 and are not inferred from a saveDiff pass.',
        ],
    }
    report['stages']['saveInvocation'] = _stage_save_invocation(manifest, reader)
    report['stages']['savedContent'] = _stage_saved_content(manifest, reader, runner, timeout)
    report['stages']['allowedDelta'] = _stage_allowed_delta(manifest, runner, timeout, out_dir)
    report['stages']['unrelatedUnchanged'] = _stage_unrelated_unchanged(manifest, reader)

    statuses = {name: report['stages'][name]['status'] for name in STAGES}
    overall = _fold(list(statuses.values()))
    report['stages']['saveDiff'] = {
        'status': overall,
        'requiredStages': list(STAGES),
        'stageStatuses': statuses,
        'rule': 'saveDiff is pass only when all four stages pass; a blocked or unjudged stage is not '
                'pass, and no stage may inherit the previous run\'s verdict',
    }
    report['ok'] = overall == PASS
    report['exitCode'] = 0 if overall == PASS else (2 if overall == INSUFFICIENT else 1)
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--case-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=float, default=300.0)
    parser.add_argument('--dry-run', action='store_true',
                        help='judge and print, write nothing')
    args = parser.parse_args(argv)

    manifest = json.loads(args.case_manifest.read_text(encoding='utf-8'))
    report = verify_saved_case(manifest, timeout=args.timeout)

    if args.output and not args.dry_run:
        out = args.output.resolve()
        if _is_inside_live_account(out):
            parser.error('refusing to write inside the live game save directory')
        if out.exists():
            parser.error(f'refusing to overwrite {out}')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'caseId': report['caseId'],
                      'saveDiff': report['stages']['saveDiff']['status'],
                      'stageStatuses': report['stages']['saveDiff']['stageStatuses']},
                     ensure_ascii=False))
    return report['exitCode']


if __name__ == '__main__':
    raise SystemExit(main())
