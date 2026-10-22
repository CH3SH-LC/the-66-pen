#!/usr/bin/env python3
"""Project-local post-write account backup + T09 save-manifest producer (W08).

This module is the *producer* half of the DS-05 save-verification contract.
``backend/save_verification.py`` (DS-05) consumes a ``manifest.schema.json``-shaped
file and judges it in four independent stages; before this module, nothing in the
tree produced such a file.  DS-05's own handoff named the two missing pieces as
``post_write_account_backup(label)`` and ``build_save_manifest(...)`` and left them
to the mainline.  This module implements both.

What it is
----------
* ``take_account_backup`` / ``post_write_account_backup``: take a SECOND account
  snapshot after the native write returned.  The pre-write snapshot already exists
  as ``entity_server.fresh_account_backup``; ``save_verification`` needs a *pair*
  of account snapshots (before and after) to judge ``unrelatedUnchanged`` and the
  ``.gip`` rule.  The wrapper runs the same project tool
  (``tools/editor-bridge/backup-account-saves.py``) and, like the pre-write helper,
  independently re-hashes the copy -- a ``create`` that reports ``ok`` is not
  accepted on its own.
* ``build_save_manifest``: assemble the manifest from the run's own materials --
  the two account snapshots, the native save reply, and the caller-declared intent.
  Every ``path`` it emits points at a project-local copy, never at the live
  ``LocalLow`` account.  Every ``sha256`` is recomputed from the bytes on disk at
  build time, so a stale manifest hash can never be carried forward.
* ``producer_preflight``: a producer-side sanity pass (complete account set,
  before/after digests bound, target level present, unrelated files unchanged, and
  -- importantly -- that the manifest carries no field that would *suppress* an
  unexplained root).  This is NOT a verdict.  The verdict belongs to
  ``backend.save_verification``.

What it deliberately does not do
--------------------------------
* It computes no verdict and names no root.  In particular it never relaxes root46
  (field 46) into an ignorable range: ``declaredChangedRoots`` is carried through
  verbatim, the G02 gate is pinned by sha256, and a manifest that carries a
  suppression key such as ``ignoredRoots`` is refused outright.  An unexplained
  delta therefore stays a *named, blocked* delta downstream.
* It does not read the live game account.  Both snapshots are project-local copies
  under ``.runtime/editor-bridge/backups``; the manifest paths point there.
* It does not decide the ``saveWallClock``: a copy carries its own mtime, so the
  caller-supplied value wins and, when absent, the value recorded *inside* the
  account manifest (``mtimeNs`` of the target level, preserved by ``shutil.copy2``)
  is used.  A manifest with no wall clock is still emitted -- the gate then records
  ``gip-timestamp-no-clock-supplied`` and stays ``blocked`` rather than passing.

Interface for consumers (W09/W10)
---------------------------------
``take_account_backup(label, *, root=None, runner=None, timeout=900, python=None)``
    -> ``{'backup', 'manifest', 'fileCount', 'verified', 'label', 'createdUtc',
           'source', 'skippedNumericDirs'}``; raises ``ManifestProducerError`` on
    any refusal.
``post_write_account_backup``  -- alias of ``take_account_backup`` (the wiring name).
``build_save_manifest(level, baseline, before_backup, after_backup, sent, requestId,
     **options)`` -> the manifest dict, augmented with ``'manifestPath'``.  Writes
    ``manifest.json`` (and ``receipt.json``) into ``out_dir``.  The caller MUST supply
    the save's own declaration: ``intent`` (complete -- ``entityId``, ``templateId``,
    ``name``, and the three transform triples -- whenever ``entity_delta.addedIds`` is
    non-empty), ``entity_delta`` and ``declared_changed_roots``.  The producer carries
    them verbatim; it cannot invent them, and an empty declaration is honest but will
    make the verifier report a defect (not a pass) for a root that in fact moved.
``producer_preflight(manifest)`` -> ``{'ok', 'findings'}``; producer-side only.
``write_manifest`` / ``load_backup_manifest`` / ``discover_sibling_levels`` -- helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BACKUP_TOOL_REL = 'tools/editor-bridge/backup-account-saves.py'
VENDOR_GATE_REL = 'tools/game-executor/vendor/g02_savediff_gate.py'

#: The G02 save-delta gate's sha256, pinned exactly as
#: ``backend/save_verification.py`` requires.  A different gate can only degrade
#: the ``allowedDelta`` stage to ``evidence-insufficient``, never to a ``pass``.
PINNED_GATE_SHA256 = '9075c4d68a6b049fe760c98c58aa96701f58d99744b69f72cf6e5091d2b536cd'

SCHEMA_VERSION = 1
OPERATION = 'save'

LEVEL_DIR = 'Beyond_Local_Save_Level'
PROFILE_NAME = 'Beyond_Local_Save_Player.gip'
TEMP_DIR = 'Temp'

#: The account file set a single save may change -- identical to
#: ``backend/save_verification.SAVE_ALLOWED_FILES`` (G02 section 2.1).  Kept as a
#: literal here so the producer does not import the verifier; a drift guard test is
#: expected to assert the two tuples are equal.
ALLOWED_ACCOUNT_FILES = (
    'Beyond_Local_Save_Level/{level}/{level}.gil',
    'Temp/{level}.gil',
    'Beyond_Local_Save_Player.gip',
    'Temp/Beyond_Local_Save_Player.gip',
)
NEVER_CHANGE_PREFIXES = ('UpgradeBackup/', 'Beyond_Debug_Log/')

#: Keys that would let a downstream consumer *suppress* an unexplained root.  The
#: producer never emits one, and refuses a manifest that carries one: relaxing a
#: whole root into a blanket ignore is not an available move.
FORBIDDEN_SUPPRESSION_KEYS = ('ignoredRoots', 'skipRoots', 'allowedRoots', 'exemptRoots')


class ManifestProducerError(ValueError):
    """Every refusal path raises this, so no caller can read a refusal as success."""


def require(ok, reason):
    if not ok:
        raise ManifestProducerError(reason)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def sha256_file(path) -> str:
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def level_gil_relpath(level_id) -> str:
    """The formal container of one level, in the directory form the tool records."""
    return '%s/%s/%s.gil' % (LEVEL_DIR, level_id, level_id)


def temp_mirror_relpath(level_id) -> str:
    return '%s/%s.gil' % (TEMP_DIR, level_id)


def profile_relpath() -> str:
    return PROFILE_NAME


def _entry(path) -> dict:
    """A {path, sha256} pair with the hash recomputed now, never inherited."""
    resolved = Path(path).resolve()
    require(resolved.is_file(), 'ENTRY_MISSING: %s' % resolved)
    return {'path': str(resolved), 'sha256': sha256_file(resolved)}


def _write_text(path, text, overwrite=False):
    """Write text with LF endings, so the bytes are reproducible across platforms.

    ``Path.write_text`` opens in text mode and would translate ``\\n`` to the
    platform separator (CRLF on Windows), which changes every hash computed over the
    file.  Evidence hashes must describe the same bytes everywhere.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise ManifestProducerError('REFUSING_TO_OVERWRITE: %s' % path)
    with path.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    return path


def _find_keys(obj, names, trail=''):
    """Every dotted path in `obj` whose key is one of `names` (recursive)."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = '%s.%s' % (trail, key) if trail else key
            if key in names:
                found.append(here)
            found.extend(_find_keys(value, names, here))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            found.extend(_find_keys(value, names, '%s[%d]' % (trail, index)))
    return found


# --------------------------------------------------------------------------- #
# account snapshots
# --------------------------------------------------------------------------- #

def load_backup_manifest(backup) -> dict:
    """Load and structurally validate one ``backup-account-saves.py`` manifest."""
    path = Path(backup) / 'manifest.json'
    require(path.is_file(), 'BACKUP_MANIFEST_MISSING: %s' % path)
    data = json.loads(path.read_text(encoding='utf-8'))
    require(data.get('schemaVersion') == SCHEMA_VERSION,
            'BACKUP_MANIFEST_SCHEMA: %r' % (data.get('schemaVersion'),))
    files = data.get('files')
    require(isinstance(files, list) and files, 'BACKUP_MANIFEST_FILES: %s' % path)
    seen = set()
    for item in files:
        relpath = item.get('relpath')
        require(isinstance(relpath, str) and relpath, 'BACKUP_MANIFEST_RELPATH: %s' % path)
        require(isinstance(item.get('sha256'), str) and item['sha256'],
                'BACKUP_MANIFEST_SHA: %s' % relpath)
        require(relpath not in seen, 'BACKUP_MANIFEST_DUPLICATE_RELPATH: %s' % relpath)
        seen.add(relpath)
    return data


def files_map(manifest) -> dict:
    """relpath -> the manifest entry, for one loaded account snapshot."""
    return {item['relpath']: item for item in manifest['files']}


class _Snapshot:
    """One account snapshot, addressed by the backup directory that holds it."""

    def __init__(self, backup, side):
        self.backup = Path(backup)
        self.side = side
        self.manifest = load_backup_manifest(self.backup)
        self.files = files_map(self.manifest)

    def copy_of(self, relpath) -> Path:
        """The project-local copy of one account file, in the backup's ``files/``."""
        path = self.backup / 'files' / relpath
        require(path.is_file(),
                'BACKUP_COPY_MISSING(%s): %s' % (self.side, path))
        return path

    def digest_of(self, relpath):
        entry = self.files.get(relpath)
        return entry.get('sha256') if entry else None

    def wall_clock_of(self, relpath):
        """The recorded mtime, in whole Unix seconds, or None.

        ``backup-account-saves.py`` copies with ``shutil.copy2`` and records
        ``st_mtime_ns`` before copying, so the value describes the *source* file even
        though the copy has its own mtime.  That is exactly what ``saveWallClock``
        needs and why a copy's own mtime must not be used instead.
        """
        entry = self.files.get(relpath) or {}
        nanos = entry.get('mtimeNs')
        return int(nanos // 1_000_000_000) if nanos is not None else None


def _as_snapshot(backup, side) -> _Snapshot:
    """Accept either a backup dict (from the backup helpers) or a backup directory."""
    if isinstance(backup, dict):
        directory = backup.get('backup')
        require(bool(directory), 'BACKUP_DICT_WITHOUT_DIR(%s)' % side)
        return _Snapshot(directory, side)
    return _Snapshot(backup, side)


def _subprocess_runner(argv, timeout):
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    stdout = proc.stdout.decode('utf-8', 'replace')
    try:
        parsed = json.loads(stdout)
    except ValueError:
        parsed = None
    return {'returncode': proc.returncode, 'stdout': stdout,
            'stderr': proc.stderr.decode('utf-8', 'replace'), 'json': parsed}


def take_account_backup(label, *, root=None, runner=None, timeout=900, python=None) -> dict:
    """Take one project-local account snapshot and prove the copy.

    Same shape and same refusals as ``entity_server.fresh_account_backup``: run the
    project tool's ``create``, then run its ``verify`` and require the independent
    re-hash to agree.  ``create`` reporting ``ok`` is not sufficient.

    ``runner`` is the process seam: ``runner(argv, timeout) -> {'returncode',
    'stdout', 'stderr', 'json'}``.  It exists so this wrapper can be exercised
    offline without touching the live account.
    """
    root = Path(root) if root else ROOT
    runner = runner or _subprocess_runner
    python = python or sys.executable
    tool = root / BACKUP_TOOL_REL
    require(tool.is_file(), 'BACKUP_TOOL_MISSING: %s' % tool)

    created = runner([python, '-B', str(tool), 'create', '--label', label], timeout)
    reply = created.get('json')
    require(isinstance(reply, dict) and reply.get('ok') is True,
            'ACCOUNT_BACKUP_CREATE_FAILED: %s'
            % ((created.get('stderr') or created.get('stdout') or '')[-400:],))
    backup = reply.get('backup')
    require(bool(backup) and Path(backup).is_dir(),
            'ACCOUNT_BACKUP_CREATE_NO_DIR: %r' % (backup,))

    readback = runner([python, '-B', str(tool), 'verify', '--backup', str(backup)], timeout)
    verified = readback.get('json') or {}
    require(verified.get('ok') is True and not verified.get('missing')
            and not verified.get('changed'),
            'ACCOUNT_BACKUP_NOT_VERIFIED: %r' % (verified,))

    manifest = load_backup_manifest(backup)
    return {'backup': str(backup),
            'manifest': str(Path(backup) / 'manifest.json'),
            'fileCount': len(manifest['files']),
            'verified': verified.get('verified'),
            'label': manifest.get('label'),
            'createdUtc': manifest.get('createdUtc'),
            'source': manifest.get('source'),
            'skippedNumericDirs': manifest.get('skippedNumericDirs') or []}


def post_write_account_backup(label, **kwargs) -> dict:
    """A second account snapshot, taken AFTER the native write returned.

    Same contract as ``take_account_backup``.  Named for the wiring point in
    DS-05's candidate patch; the pre-write snapshot stays
    ``entity_server.fresh_account_backup``.
    """
    return take_account_backup(label, **kwargs)


# --------------------------------------------------------------------------- #
# level discovery
# --------------------------------------------------------------------------- #

def discover_sibling_levels(before, after, target_level_id) -> list:
    """Other levels whose container appears in the directory form in BOTH snapshots.

    A save must leave every sibling byte-identical, formal file and Temp mirror
    alike.  The directory form (``Beyond_Local_Save_Level/<id>/<id>.gil``) is the one
    a level *currently edited* uses; the flat form is a retired layout and is not
    reported as a protected sibling.  Levels present on only one side are not
    siblings: they are a shape change and are left for the verifier's account-set
    stage to name rather than silently dropped here.
    """
    target = str(target_level_id)

    def levels_of(snapshot):
        out = set()
        for relpath in snapshot.files:
            parts = relpath.split('/')
            if len(parts) == 3 and parts[0] == LEVEL_DIR and parts[1] == parts[2][:-4] \
                    and parts[2].endswith('.gil') and parts[1].isdigit():
                out.add(parts[1])
        return out

    common = levels_of(before) & levels_of(after)
    return sorted(level for level in common if level != target)


# --------------------------------------------------------------------------- #
# the manifest producer
# --------------------------------------------------------------------------- #

def _default_gate() -> dict:
    """The pinned G02 gate, by path (discovered) and by contract sha256 (fixed)."""
    vendored = ROOT / VENDOR_GATE_REL
    if vendored.is_file():
        return {'path': str(vendored), 'sha256': PINNED_GATE_SHA256}
    return {'sha256': PINNED_GATE_SHA256}


def build_save_manifest(level, baseline, before_backup, after_backup, sent, requestId, *,
                        intent=None, entity_delta=None, declared_changed_roots=None,
                        declared_changed_gip_entries=None, level_name=None,
                        save_wall_clock=None, g02_gate=None, content_python=None,
                        out_dir=None, case_id=None, overwrite=False, python=None):
    """Assemble the DS-05 manifest from the run's own materials.

    Paths only point at project-local copies: the two account snapshots under
    ``.runtime/editor-bridge/backups`` and the manifest/receipt written into
    ``out_dir``.  Every ``sha256`` is recomputed from disk now.

    ``declared_changed_roots`` / ``entity_delta`` / ``intent`` describe *what this
    save was supposed to do*.  The producer cannot invent them: it carries the
    caller's declaration verbatim (default empty).  An empty declaration is honest,
    and a save that in fact moved a root5 record will then be caught by the
    verifier's attribution as a defect rather than waved through -- that is the
    intended direction of failure.
    """
    backend = (sent or {}).get('backend') or {}
    level_id = (level or {}).get('levelId')
    require(isinstance(level_id, int) and not isinstance(level_id, bool), 'LEVEL_ID_REQUIRED')
    require(isinstance(requestId, str) and requestId, 'REQUEST_ID_REQUIRED')
    lv = str(level_id)

    before = _as_snapshot(before_backup, 'before')
    after = _as_snapshot(after_backup, 'after')

    # --- target level: the four files the verifier re-decodes and mirrors -----
    files = {
        'gilBefore': _entry(before.copy_of(level_gil_relpath(lv))),
        'gilAfter': _entry(after.copy_of(level_gil_relpath(lv))),
        'gipBefore': _entry(before.copy_of(profile_relpath())),
        'gipAfter': _entry(after.copy_of(profile_relpath())),
    }
    target = {
        'tempMirrorBefore': _entry(before.copy_of(temp_mirror_relpath(lv))),
        'tempMirrorAfter': _entry(after.copy_of(temp_mirror_relpath(lv))),
    }

    # --- protected siblings: nothing else may move ---------------------------
    protected = {}
    for sibling in discover_sibling_levels(before, after, lv):
        protected[sibling] = {
            'gilBefore': _entry(before.copy_of(level_gil_relpath(sibling))),
            'gilAfter': _entry(after.copy_of(level_gil_relpath(sibling))),
            'tempMirrorBefore': _entry(before.copy_of(temp_mirror_relpath(sibling))),
            'tempMirrorAfter': _entry(after.copy_of(temp_mirror_relpath(sibling))),
        }

    run_dir = backend.get('run') or (baseline or {}).get('run')
    run_id = Path(run_dir).name if run_dir else 'unknown'

    wall_clock = save_wall_clock
    if wall_clock is None:
        wall_clock = after.wall_clock_of(level_gil_relpath(lv))
    if wall_clock is None:
        recorded = (backend.get('afterGils') or {}).get(lv) or {}
        if recorded.get('mtimeNs') is not None:
            wall_clock = int(recorded['mtimeNs'] // 1_000_000_000)

    resolved_out = Path(out_dir) if out_dir else (ROOT / '.runtime/save-manifests' / requestId)
    resolved_out.mkdir(parents=True, exist_ok=True)

    # The native reply is written next to the manifest and referenced by hash, so
    # the saveInvocation stage pins the exact bytes this case is about.
    receipt_path = _write_text(resolved_out / 'receipt.json',
                               json.dumps(sent, ensure_ascii=False, indent=2) + '\n',
                               overwrite=overwrite)

    manifest = {
        'schemaVersion': SCHEMA_VERSION,
        'caseId': case_id or requestId,
        'runId': run_id,
        'operation': OPERATION,
        'levelId': level_id,
        'levelName': level_name if level_name is not None else backend.get('levelName'),
        'requestId': requestId,
        'saveWallClock': wall_clock,
        'files': files,
        'targetLevel': target,
        'protectedLevels': protected,
        'accountSet': {
            'before': _entry(before.backup / 'manifest.json'),
            'after': _entry(after.backup / 'manifest.json'),
        },
        'receiptPath': _entry(receipt_path),
        'intent': dict(intent or {}),
        'entityDelta': dict(entity_delta or {'addedIds': [], 'removedIds': []}),
        'declaredChangedRoots': list(declared_changed_roots or []),
        'declaredChangedGipEntries': list(declared_changed_gip_entries or []),
        'g02Gate': g02_gate or _default_gate(),
    }
    chosen_python = content_python or os.environ.get('DS_SAVE_CONTENT_PYTHON')
    if chosen_python:
        manifest['contentPython'] = chosen_python

    manifest_path = resolved_out / 'manifest.json'
    manifest['manifestPath'] = str(manifest_path)
    _write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                overwrite=overwrite)
    return manifest


def write_manifest(manifest, out_dir, *, overwrite=False) -> dict:
    """Write an already-built manifest (re-pins every hash first)."""
    out = Path(out_dir)
    for key in ('files', 'targetLevel'):
        for entry in (manifest.get(key) or {}).values():
            if isinstance(entry, dict) and 'path' in entry:
                entry['sha256'] = sha256_file(entry['path'])
    for pair in (manifest.get('protectedLevels') or {}).values():
        for entry in pair.values():
            entry['sha256'] = sha256_file(entry['path'])
    for key in ('accountSet', 'receiptPath'):
        entry = manifest.get(key)
        if isinstance(entry, dict) and 'path' in entry:
            entry['sha256'] = sha256_file(entry['path'])
        elif isinstance(entry, dict):
            for sub in entry.values():
                sub['sha256'] = sha256_file(sub['path'])
    path = _write_text(out / 'manifest.json',
                       json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                       overwrite=overwrite)
    return {'manifestPath': str(path), 'manifest': manifest}


# --------------------------------------------------------------------------- #
# producer-side preflight (NOT a verdict)
# --------------------------------------------------------------------------- #

def producer_preflight(manifest) -> dict:
    """Producer-side sanity: did we describe the whole, honest account set?

    Returns ``{'ok': bool, 'findings': [{'id', 'status', 'detail'}]}``.  A ``fail``
    here means the producer emitted a manifest it should not have -- it never means
    the save was good.  The authoritative verdict remains
    ``backend.save_verification.verify_saved_case``.
    """
    findings = []

    def check(check_id, ok, detail=None):
        findings.append({'id': check_id, 'status': 'pass' if ok else 'fail', 'detail': detail})

    suppressed = _find_keys(manifest, FORBIDDEN_SUPPRESSION_KEYS)
    check('producer.noRootSuppression', not suppressed, {'found': suppressed})

    account = manifest.get('accountSet') or {}
    try:
        before_blob = json.loads(Path(account['before']['path']).read_text(encoding='utf-8'))
        after_blob = json.loads(Path(account['after']['path']).read_text(encoding='utf-8'))
        before_map = {item['relpath']: item['sha256'] for item in before_blob['files']}
        after_map = {item['relpath']: item['sha256'] for item in after_blob['files']}
    except (KeyError, OSError, ValueError, TypeError) as exc:
        check('producer.accountSetComplete', False, {'error': str(exc)})
        return {'ok': False, 'findings': findings}

    check('producer.accountSetComplete',
          bool(before_map) and set(before_map) == set(after_map),
          {'before': len(before_map), 'after': len(after_map),
           'onlyBefore': sorted(set(before_map) - set(after_map)),
           'onlyAfter': sorted(set(after_map) - set(before_map))})

    changed = sorted(k for k in before_map if before_map[k] != after_map.get(k))
    level = str(manifest.get('levelId'))
    allowed = {pattern.format(level=level) for pattern in ALLOWED_ACCOUNT_FILES}
    unexpected = [k for k in changed if k not in allowed]
    forbidden = [k for k in changed if k.startswith(NEVER_CHANGE_PREFIXES)]
    check('producer.unrelatedFilesUnchanged', not unexpected and not forbidden,
          {'changed': changed, 'allowed': sorted(allowed), 'unexpected': unexpected,
           'neverChangePrefixesHit': forbidden})

    digests = {}
    bound = True
    for key in ('gilBefore', 'gilAfter', 'gipBefore', 'gipAfter'):
        entry = (manifest.get('files') or {}).get(key) or {}
        path = Path(entry.get('path', ''))
        live = sha256_file(path) if path.is_file() else None
        digests[key] = {'recorded': entry.get('sha256'), 'onDisk': live}
        bound = bound and live is not None and live == entry.get('sha256')
    check('producer.beforeAfterDigestsBound', bound, digests)

    target = manifest.get('targetLevel') or {}
    check('producer.targetLevelPresent',
          manifest.get('levelId') is not None
          and bool((manifest.get('files') or {}).get('gilBefore'))
          and bool(target.get('tempMirrorBefore')) and bool(target.get('tempMirrorAfter')),
          {'levelId': manifest.get('levelId'), 'levelName': manifest.get('levelName')})

    check('producer.declaredRootsCarried',
          isinstance(manifest.get('declaredChangedRoots'), list),
          {'declaredChangedRoots': manifest.get('declaredChangedRoots')})

    # A save with a declared entity delta is handed to the create-shaped decoder,
    # which needs the entity's full identity and transform.  A half-filled intent
    # does not fail loudly downstream -- it lands on evidence-insufficient with a
    # decoder usage error -- so the producer surfaces it here instead.
    added = list((manifest.get('entityDelta') or {}).get('addedIds') or [])
    intent = manifest.get('intent') or {}
    required = ('entityId', 'templateId', 'name')
    missing = [key for key in required if intent.get(key) is None]
    for axis in ('position', 'rotation', 'scale'):
        if not intent.get(axis):
            missing.append(axis)
    check('producer.intentCompleteForContent',
          (not added) or not missing,
          {'declaredAddedIds': added, 'missingIntentFields': missing,
           'rule': 'a declared entity delta is decoded by the create-shaped verifier, '
                   'which requires entityId/templateId/name/position/rotation/scale; an '
                   'incomplete intent is reported here rather than as an obscure '
                   'evidence-insufficient downstream'})

    return {'ok': all(item['status'] == 'pass' for item in findings), 'findings': findings}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--before', required=True, help='pre-write account backup directory')
    parser.add_argument('--after', required=True, help='post-write account backup directory')
    parser.add_argument('--receipt', required=True, help='native save reply (JSON)')
    parser.add_argument('--level-id', type=int, required=True)
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--level-name')
    parser.add_argument('--case-id')
    parser.add_argument('--entity-id', type=int, help='declared added entity of this save, if any')
    parser.add_argument('--intent-json', help='file or inline JSON with the full entity intent')
    parser.add_argument('--declared-changed-roots', default='', help='comma separated')
    parser.add_argument('--save-wall-clock', type=int)
    parser.add_argument('--content-python')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args(argv)

    sent = json.loads(Path(args.receipt).read_text(encoding='utf-8'))
    roots = [int(part) for part in args.declared_changed_roots.split(',') if part.strip()]
    intent = {}
    if args.intent_json:
        candidate = Path(args.intent_json)
        intent = json.loads(candidate.read_text(encoding='utf-8') if candidate.is_file()
                            else args.intent_json)
    elif args.entity_id is not None:
        intent = {'entityId': args.entity_id}
    entity_delta = ({'addedIds': [args.entity_id], 'removedIds': []}
                    if args.entity_id is not None else {'addedIds': [], 'removedIds': []})
    manifest = build_save_manifest(
        {'levelId': args.level_id}, {}, args.before, args.after, sent, args.request_id,
        intent=intent,
        entity_delta=entity_delta, declared_changed_roots=roots,
        level_name=args.level_name, save_wall_clock=args.save_wall_clock,
        content_python=args.content_python, out_dir=args.out, case_id=args.case_id,
        overwrite=args.overwrite)
    preflight = producer_preflight(manifest)
    print(json.dumps({'manifestPath': manifest['manifestPath'],
                      'preflightOk': preflight['ok'],
                      'preflight': preflight['findings']}, ensure_ascii=False, indent=2))
    return 0 if preflight['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
