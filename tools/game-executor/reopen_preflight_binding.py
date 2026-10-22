"""The MEASURED seam between helper registration, the reopen-inputs index, and pre-dispatch.

WHY THIS EXISTS
===============
W15 wrote a placeholder seam called ``normalize_inputs`` in
``backend/reopen_contract_adapter.py`` and said so in its own docstring: "the static shape W13
must produce ... kept here so the seam is written down rather than assumed."  W13
(``tools/game-executor/assemble_reopen_inputs.py``) and W14
(``tools/editor-bridge/sync-elevated-pointer.py``) have now landed, so the seam can be
measured instead of assumed.  Two things fall out of measuring it:

  1. ``normalize_inputs`` reads ``index.get('levelId')``.  The index
     ``assemble_reopen_inputs.assemble`` actually emits has exactly five keys --
     ``schemaVersion / requestId / editorPid / files / runs`` (``ASSEMBLER_INDEX_SHAPE``).  It
     carries **no** ``levelId``.  So on a REAL index ``levelId is None`` and ``check_bindings``
     refuses every well-formed request with ``READBACK_WRONG_LEVEL`` ("levelId must be an
     integer").  The authoritative level lives in the lease (``reopen-claim.json``, a file the
     index *does* carry), which ``assemble_reopen_inputs.check_lease`` already pins to the fixed
     level.  ``normalize_index`` below takes it from there.

  2. ``normalize_inputs`` also falls back to ``lease['levelId']`` for ``handleLevelId``.  That
     *fabricates* the observed handle level out of the lease -- the very document the handle is
     supposed to be checked against -- so a handle observed on another level cannot be caught.
     ``normalize_index`` takes the handle level from an explicit observation document and
     reports ``HANDLE_LEVEL_MISSING`` rather than inventing one.

  3. Neither W13 nor W14 binds the elevated-session pointer
     (``.runtime/editor-bridge/current-elevated-session.json``) to the reopen inputs at all.  The
     lease carries its own ``pinsDigest`` copy, but nothing compares it with the pointer's
     ``nativeScene.pinsDigest``; the pointer's ``helperPid`` / ``helperStartedUtc`` /
     ``deadlineUtc`` are read by ``build_reopen_profile.py`` as the authorization cutoff and by
     the business tools as liveness, but never cross-checked before a dispatch.  ``bind_pointer``
     closes that: a helper relaunched between review and dispatch (new pinsDigest), a recycled
     pid, a drifted creation stamp and an over-stated deadline are all refused *before*
     dispatch, not discovered afterwards.

PURITY
======
Pure.  No socket, no subprocess, no helper, no game, no elevated queue, no write.  Every input
is an already-parsed document (or, for ``load_pointer``, one path the caller nominates).  It
never dispatches, never writes the pointer, and never claims a reopen.

CROSS-CHECKED AGAINST THE REAL TOOLS
====================================
``canonical_pointer_identity`` reproduces ``sync-elevated-pointer.canonical_identity`` and
``compare_pointer_to_launch`` reproduces ``compare_pointer_to_receipt``; the test suite asserts
both are byte-identical to the imported originals rather than trusting the copy.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = (
    'LEVEL_PLACEHOLDER', 'POINTER_SCHEMA', 'POINTER_IDENTITY_FIELDS', 'INDEX_KEYS',
    'INDEX_FILE_NAMES', 'RUN_NAMES', 'CLOCK_SKEW',
    'BindingRefused', 'canonical_pointer_identity', 'load_pointer', 'normalize_index',
    'compare_pointer_to_launch', 'bind_pointer', 'preflight',
)

#: The discovery placeholder, which is NEVER a real target.
#:
#: This replaces the old ``FIXED_LEVEL = 1073741840``.  That literal was hand-maintained in
#: about twenty places across the reopen lane and is a property of ONE SAVE LOAD, so it
#: went stale the moment the save changed -- MEASURED 2026-10-08, when the open level was
#: 1073741842 and every reopen entry point refused it, taking away a capability that had
#: worked on 2026-09-28.  What the lane actually needs from a level id is that it be REAL;
#: the checks that carry the weight (the lease against the native observation, and against
#: the caller's own inputs) are below, and they compare two OBSERVATIONS with each other
#: rather than an observation with a constant -- which is what makes them survive the next
#: save change.
LEVEL_PLACEHOLDER = 0xFFFFFFFF

#: The pointer document this seam reads.  Must match ``sync-elevated-pointer.POINTER_SCHEMA``.
POINTER_SCHEMA = 'elevated-session-pointer/1'

#: The identity fields ``sync-elevated-pointer.canonical_identity`` hashes, in its order.
POINTER_IDENTITY_FIELDS = ('queueDir', 'helperPid', 'helperStartedUtc', 'deadlineUtc',
                           'pinsDigest', 'projectRoot', 'actions')

#: The index shape ``assemble_reopen_inputs.assemble`` emits -- exactly these five keys, and
#: deliberately no ``levelId``/``handleLevelId``.
INDEX_KEYS = frozenset({'schemaVersion', 'requestId', 'editorPid', 'files', 'runs'})

#: ``assemble_reopen_inputs.FILES_ORDER``, copied and asserted against the original by the test.
INDEX_FILE_NAMES = ('lease', 'claim', 'dispatch', 'session', 'review', 'beforeEditor',
                    'afterEditor', 'beforeObserver', 'afterObserver', 'beforeIpc', 'afterIpc',
                    'beforeAccount', 'afterAccount', 'formalGil')

#: ``assemble_reopen_inputs.RUNS_ORDER``.
RUN_NAMES = ('before', 'action', 'after')

#: Same tolerance ``sync-elevated-pointer`` uses for helper-vs-host clock disagreement.
CLOCK_SKEW_SECONDS = 120

_HEX32 = re.compile(r'[0-9a-f]{32}\Z')
_HEX64 = re.compile(r'[0-9a-f]{64}\Z')


class BindingRefused(Exception):
    """A pre-dispatch refusal.  Carries a stable code so a caller can branch on it."""

    def __init__(self, code: str, message: str, **detail):
        super().__init__('%s: %s' % (code, message))
        self.code = code
        self.message = message
        self.detail = detail

    def as_json(self) -> dict:
        return {'ok': False, 'refused': self.code, 'message': self.message, 'detail': self.detail}


def _require(ok, code, message, **detail):
    if not ok:
        raise BindingRefused(code, message, **detail)


def _parse_utc(value, code, field):
    if not isinstance(value, str) or not value.strip():
        raise BindingRefused(code, '%s is missing' % field, field=field, value=value)
    try:
        stamp = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        raise BindingRefused(code, '%s is not an ISO-8601 instant: %r' % (field, value),
                             field=field) from None
    if stamp.tzinfo is None:
        raise BindingRefused(code, '%s carries no timezone: %r' % (field, value), field=field)
    return stamp.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# The pointer (W14 registration) -- read, and prove it is whole
# --------------------------------------------------------------------------- #

def canonical_pointer_identity(record: dict) -> str:
    """sha256 over the pointer's identity fields only.  Mirror of W14's ``canonical_identity``.

    W14 *writes* ``registrationDigest`` with this exact function but never re-reads it, so a
    hand-edited or half-merged pointer keeps a digest that no longer describes it and no reader
    notices.  ``load_pointer`` recomputes it.
    """
    payload = {k: record.get(k) for k in POINTER_IDENTITY_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def load_pointer(path, *, now: datetime | None = None) -> dict:
    """Read and prove one pointer document, failing closed.

    Refuses (never returns a partial document):

      * ``POINTER_UNREADABLE``          -- missing / unreadable / not UTF-8.
      * ``POINTER_TORN``                -- not JSON, a duplicate key, or not an object: the
                                           shape a truncated or half-flushed write leaves.
      * ``POINTER_SCHEMA``              -- a document that is not ``elevated-session-pointer/1``.
      * ``POINTER_IDENTITY_TAMPERED``   -- ``registrationDigest`` does not describe the identity
                                           fields it sits next to (hand edit / torn merge).
      * ``POINTER_CAPABILITY_TORN``     -- the two copies of the capability the document keeps
                                           (``nativeScene`` and ``statusEvidence.authoritativeStatus
                                           .nativeScene``) disagree.
      * ``POINTER_EXPIRED``             -- its own ``deadlineUtc`` has passed.
      * ``POINTER_CREATION_IN_FUTURE``  -- ``helperStartedUtc`` is beyond clock skew.
    """
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BindingRefused('POINTER_UNREADABLE', 'the pointer could not be read',
                             pointer=str(path), error=str(exc)) from None
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise BindingRefused('POINTER_UNREADABLE', 'the pointer is not UTF-8',
                             pointer=str(path), error=str(exc)) from None

    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise BindingRefused('POINTER_TORN', 'the pointer repeats a JSON key: %r' % key,
                                     pointer=str(path))
            out[key] = value
        return out

    try:
        document = json.loads(text, object_pairs_hook=pairs)
    except ValueError as exc:
        raise BindingRefused('POINTER_TORN', 'the pointer is not whole JSON',
                             pointer=str(path), error=str(exc), bytes=len(raw)) from None
    _require(isinstance(document, dict), 'POINTER_TORN',
             'the pointer is not a JSON object', pointer=str(path))
    _require(document.get('schema') == POINTER_SCHEMA, 'POINTER_SCHEMA',
             'not an elevated-session-pointer/1 document', pointer=str(path),
             schema=document.get('schema'))

    stored = document.get('registrationDigest')
    _require(isinstance(stored, str) and _HEX64.fullmatch(stored) is not None,
             'POINTER_IDENTITY_TAMPERED', 'registrationDigest is missing or not a sha256',
             pointer=str(path), digest=stored)
    actual = canonical_pointer_identity(document)
    _require(stored == actual, 'POINTER_IDENTITY_TAMPERED',
             'registrationDigest does not describe this pointer\'s identity fields; the '
             'document was edited or half-merged after registration',
             pointer=str(path), stored=stored, recomputed=actual)

    native = document.get('nativeScene')
    _require(isinstance(native, dict), 'POINTER_CAPABILITY_TORN',
             'nativeScene is missing or not an object', pointer=str(path))
    evidence_native = ((document.get('statusEvidence') or {}).get('authoritativeStatus')
                       or {}).get('nativeScene')
    if isinstance(evidence_native, dict):
        for field in ('pinsDigest', 'projectRoot', 'schema', 'enabled'):
            _require(native.get(field) == evidence_native.get(field), 'POINTER_CAPABILITY_TORN',
                     'the pointer keeps two copies of the capability and they disagree on %r: '
                     'a half-merged document' % field,
                     pointer=str(path), field=field, nativeScene=native.get(field),
                     statusEvidence=evidence_native.get(field))

    started = _parse_utc(document.get('helperStartedUtc'), 'POINTER_CREATION_TORN',
                         'helperStartedUtc')
    deadline = _parse_utc(document.get('deadlineUtc'), 'POINTER_DEADLINE_TORN', 'deadlineUtc')
    if started > now + timedelta(seconds=CLOCK_SKEW_SECONDS):
        raise BindingRefused('POINTER_CREATION_IN_FUTURE',
                             'helperStartedUtc is in the future; the clock or the pointer is '
                             'wrong', pointer=str(path), helperStartedUtc=document.get(
                                 'helperStartedUtc'), nowUtc=now.isoformat())
    if deadline <= now:
        raise BindingRefused('POINTER_EXPIRED',
                             'the helper\'s own deadline has passed; re-register from a fresh '
                             'launch receipt before dispatching',
                             pointer=str(path), deadlineUtc=document.get('deadlineUtc'),
                             nowUtc=now.isoformat())
    return document


# --------------------------------------------------------------------------- #
# The index (W13 review input) -- the measured replacement for normalize_inputs
# --------------------------------------------------------------------------- #

def normalize_index(index: dict, documents: dict, *, handle: dict | None = None) -> dict:
    """Lift a REAL ``reopen-inputs.json`` index into the adapter's input object.

    This is the measured seam.  Differences from W15's ``normalize_inputs``, each of which is a
    refusal here rather than a silent ``None``:

      * the index must have exactly ``INDEX_KEYS``.  A top-level ``levelId`` is *refused*: the
        real index has none, and a caller-supplied one could only be a second, disagreeing
        source of truth.
      * the request id and level id come from the **lease** (``reopen-claim.json``), which the
        assembler has already bound to the level the round observed (no longer a constant).
      * the handle level comes from the caller's **observation** document, never from the lease.
    """
    _require(isinstance(index, dict), 'INDEX_SHAPE', 'the index is not an object')
    keys = set(index)
    _require('levelId' not in keys and 'handleLevelId' not in keys, 'INDEX_SHAPE',
             'the reopen-inputs index carries no level; the lease is the level source. '
             'A top-level levelId would be a second, unchecked truth.',
             keys=sorted(keys))
    _require(keys == set(INDEX_KEYS), 'INDEX_SHAPE',
             'the index is not the shape assemble_reopen_inputs emits',
             keys=sorted(keys), expected=sorted(INDEX_KEYS))
    _require(index.get('schemaVersion') == 1, 'INDEX_SHAPE', 'index.schemaVersion must be 1',
             schemaVersion=index.get('schemaVersion'))
    request_id = index.get('requestId')
    _require(isinstance(request_id, str) and _HEX32.match(request_id) is not None,
             'INDEX_SHAPE', 'index.requestId must be 32 lowercase hex characters',
             requestId=request_id)

    files = index.get('files')
    _require(isinstance(files, dict), 'INDEX_SHAPE', 'index.files must be an object')
    _require(set(files) == set(INDEX_FILE_NAMES), 'INDEX_SHAPE',
             'index.files is missing an original', files=sorted(files))
    runs = index.get('runs')
    _require(isinstance(runs, dict) and set(runs) == set(RUN_NAMES), 'INDEX_SHAPE',
             'index.runs must name before/action/after', runs=sorted(runs or ()))

    def digest_of(name):
        row = files.get(name)
        _require(isinstance(row, dict) and isinstance(row.get('sha256'), str),
                 'INDEX_SHAPE', 'index.files.%s has no sha256' % name)
        return row['sha256']

    def doc_of(name):
        return (documents or {}).get(name)

    lease = doc_of('lease')
    _require(isinstance(lease, dict), 'INDEX_SHAPE',
             'the parsed lease (reopen-claim.json) must be supplied with the index')
    level_id = lease.get('levelId')
    _require(level_id is not None, 'WRONG_LEVEL',
             'the lease carries no levelId; the index cannot supply one',
             leaseLevelId=level_id)
    _require(type(level_id) is int and not isinstance(level_id, bool), 'WRONG_LEVEL',
             'lease.levelId must be an integer', leaseLevelId=level_id)
    _require(level_id != LEVEL_PLACEHOLDER, 'WRONG_LEVEL',
             'the lease carries the discovery placeholder level id 0x%X, which names no '
             'real level' % LEVEL_PLACEHOLDER, leaseLevelId=level_id)

    handle_level = None
    if handle is not None:
        _require(isinstance(handle, dict), 'INDEX_SHAPE', 'the handle observation is not an object')
        handle_level = handle.get('levelId')
        _require(type(handle_level) is int and not isinstance(handle_level, bool),
                 'HANDLE_LEVEL_MISSING',
                 'the handle observation carries no integer levelId', handle=handle)
        _require(handle_level == level_id, 'HANDLE_WRONG_LEVEL',
                 'the observed handle is on level %r but the lease targets %r'
                 % (handle_level, level_id), handleLevelId=handle_level, levelId=level_id)

    return {
        'requestId': request_id,
        'levelId': level_id,
        'handleLevelId': handle_level,
        'session': doc_of('session'),
        'review': doc_of('review'),
        'lease': lease,
        'claim': doc_of('claim'),
        'dispatch': doc_of('dispatch'),
        'dispatchSha256': digest_of('dispatch'),
        'acceptance': doc_of('acceptance'),
        'sessionSha256': digest_of('session'),
        'reviewSha256': digest_of('review'),
        'leaseSha256': digest_of('lease'),
        'claimSha256': digest_of('claim'),
        'accountBaselineSha256': digest_of('beforeAccount'),
    }


# --------------------------------------------------------------------------- #
# Pointer x lease -- the binding neither W13 nor W14 performs
# --------------------------------------------------------------------------- #

def compare_pointer_to_launch(pointer_doc: dict, fresh: dict) -> list[dict]:
    """Divergences between a stored pointer and a freshly built registration document.

    The same fields ``sync-elevated-pointer.compare_pointer_to_receipt`` compares, with the two
    classifications that tool leaves implicit made explicit:

      * equal ``helperPid`` + unequal ``helperStartedUtc`` -> ``pid-recycled``: the number was
        reused by a different process, so the *pid* is not the identity.
      * a pointer ``deadlineUtc`` later than the launch's -> ``over-stated``: this is the one
        divergence that lets a run outlive its authorization, because
        ``build_reopen_profile.py`` reads the pointer's deadline as the cutoff.
    """
    wanted = {
        'helperPid': fresh.get('helperPid'),
        'helperStartedUtc': fresh.get('helperStartedUtc'),
        'deadlineUtc': fresh.get('deadlineUtc'),
        'queueDir': fresh.get('queueDir'),
        'pinsDigest': (fresh.get('nativeScene') or {}).get('pinsDigest'),
    }
    got = {k: pointer_doc.get(k) for k in ('helperPid', 'helperStartedUtc', 'deadlineUtc',
                                          'queueDir')}
    got['pinsDigest'] = (pointer_doc.get('nativeScene') or {}).get('pinsDigest')

    problems = []
    for field, expected in wanted.items():
        if got.get(field) != expected:
            row = {'field': field, 'pointer': got.get(field), 'launch': expected}
            if field == 'helperStartedUtc' and got.get('helperPid') == wanted['helperPid']:
                row['kind'] = 'pid-recycled'
            problems.append(row)
    p_deadline = _try_time(pointer_doc.get('deadlineUtc'))
    l_deadline = _try_time(fresh.get('deadlineUtc'))
    if p_deadline and l_deadline and p_deadline > l_deadline:
        problems.append({'field': 'deadlineUtc', 'kind': 'over-stated',
                         'pointer': pointer_doc.get('deadlineUtc'),
                         'launch': fresh.get('deadlineUtc')})
    return problems


def _try_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return stamp.astimezone(timezone.utc) if stamp.tzinfo else None


def bind_pointer(pointer: dict, lease: dict, *, fresh_launch: dict | None = None,
                 now: datetime | None = None) -> dict:
    """Bind the pointer to the lease under review, and optionally to a fresh launch.

    Refuses on:

      * ``POINTER_PIN_DRIFT``          -- the pointer's ``nativeScene.pinsDigest`` is not the
                                          digest the lease pinned.  The helper was relaunched (or
                                          its scene re-pinned) between review and dispatch, so
                                          the reviewed scene is not the scene that would run.
      * ``POINTER_LEVEL_UNBOUND``      -- pointer and lease disagree on the level.
      * ``POINTER_CREATION_DRIFT``     -- a fresh launch reports a different creation stamp.
      * ``POINTER_PID_RECYCLED``       -- a fresh launch reports the same pid with a different
                                          creation: the pid was reused.
      * ``POINTER_DEADLINE_OVERSTATED``-- the pointer claims a later deadline than the launch.
      * ``POINTER_QUEUE_DRIFT``        -- the pointer names a different queue directory.
    """
    now = now or datetime.now(timezone.utc)
    _require(isinstance(lease, dict), 'INDEX_SHAPE', 'the lease is not an object')
    lease_level = lease.get('levelId')
    native = pointer.get('nativeScene') or {}
    pins = native.get('pinsDigest')
    _require(isinstance(pins, str) and _HEX64.fullmatch(pins) is not None,
             'POINTER_PIN_DRIFT', 'the pointer carries no usable pinsDigest', pinsDigest=pins)
    lease_pins = lease.get('pinsDigest')
    _require(isinstance(lease_pins, str) and _HEX64.fullmatch(lease_pins) is not None,
             'POINTER_PIN_DRIFT', 'the lease carries no usable pinsDigest', pinsDigest=lease_pins)
    _require(pins == lease_pins, 'POINTER_PIN_DRIFT',
             'the helper\'s live scene pins (%s...) are not the pins the review lease pinned '
             '(%s...); the helper was relaunched or the scene re-pinned after review, so the '
             'review does not authorise the scene that would run'
             % (pins[:16], lease_pins[:16]), pointerPinsDigest=pins, leasePinsDigest=lease_pins)

    if lease_level is not None:
        _require(lease_level != LEVEL_PLACEHOLDER, 'WRONG_LEVEL',
                 'the lease targets the discovery placeholder 0x%X, which names no real '
                 'level' % LEVEL_PLACEHOLDER, leaseLevelId=lease_level)
    _require(native.get('enabled') is True, 'POINTER_PIN_DRIFT',
             'the registered helper does not advertise an enabled native scene',
             enabled=native.get('enabled'))

    report = {'pinBound': True, 'pointerPinsDigest': pins, 'leasePinsDigest': lease_pins}
    if fresh_launch is not None:
        divergences = compare_pointer_to_launch(pointer, fresh_launch)
        fields = {d['field'] for d in divergences}
        kinds = {d.get('kind') for d in divergences}
        # A recycled pid is reported before the plain creation drift: an equal pid with a
        # different creation stamp is a *different process*, not a stale timestamp.
        if 'pid-recycled' in kinds:
            raise BindingRefused('POINTER_PID_RECYCLED',
                                 'the pointer and the live helper share pid %r but their '
                                 'creation stamps differ; the pid was recycled and the pointer '
                                 'no longer names the live process'
                                 % (pointer.get('helperPid'),), divergences=divergences)
        if 'over-stated' in kinds:
            raise BindingRefused('POINTER_DEADLINE_OVERSTATED',
                                 'the stored pointer claims a later deadline than the live '
                                 'helper; a reader that uses it as its cutoff would run past '
                                 'the real expiry', divergences=divergences)
        if 'helperStartedUtc' in fields:
            raise BindingRefused('POINTER_CREATION_DRIFT',
                                 'the stored pointer\'s creation stamp is not the live '
                                 'helper\'s', divergences=divergences)
        if 'queueDir' in fields:
            raise BindingRefused('POINTER_QUEUE_DRIFT',
                                 'the pointer names a different queue than the live helper',
                                 divergences=divergences)
        if divergences:
            raise BindingRefused('POINTER_PIN_DRIFT',
                                 'the stored pointer disagrees with the live helper',
                                 divergences=divergences)
        report['launchConsistent'] = True
    return report


# --------------------------------------------------------------------------- #
# The combination entry point
# --------------------------------------------------------------------------- #

def preflight(index: dict, documents: dict, *, handle: dict | None = None,
              pointer: dict | None = None, fresh_launch: dict | None = None,
              now: datetime | None = None) -> dict:
    """Registration -> review input -> pre-dispatch: one object, or a classified refusal.

    Returns ``{'inputs', 'binding', 'checked'}``.  ``inputs`` is exactly the object
    ``reopen_contract_adapter.check_bindings`` takes.  The caller then runs
    ``check_bindings`` (consistency) and ``adapt_reopen`` (v1 envelope); this function never
    dispatches and never writes.
    """
    now = now or datetime.now(timezone.utc)
    inputs = normalize_index(index, documents, handle=handle)
    binding = {}
    if pointer is not None:
        binding = bind_pointer(pointer, inputs['lease'], fresh_launch=fresh_launch, now=now)
        binding['pointerPid'] = pointer.get('helperPid')
        binding['pointerCreation'] = pointer.get('helperStartedUtc')
        binding['pointerDeadline'] = pointer.get('deadlineUtc')
        # A helper whose own lifetime is already over cannot be the one dispatched to.  This is
        # a second, independent read of the same fact the pointer's loader already checked, from
        # the caller's ``now`` rather than the loader's.
        deadline = _try_time(pointer.get('deadlineUtc'))
        _require(deadline is not None and deadline > now, 'POINTER_EXPIRED',
                 'the registered helper\'s deadline has passed',
                 deadlineUtc=pointer.get('deadlineUtc'), nowUtc=now.isoformat())
    # ``levelBound`` now means "the level is a real observed value that the handle agrees
    # with", not "it equals a constant".  The handle agreement is enforced above
    # (HANDLE_WRONG_LEVEL); it is restated here because this dict is what a reader sees.
    checked = {'levelBound': (isinstance(inputs.get('levelId'), int)
                              and not isinstance(inputs.get('levelId'), bool)
                              and inputs['levelId'] != LEVEL_PLACEHOLDER
                              and inputs.get('handleLevelId') == inputs.get('levelId')),
               'levelId': inputs.get('levelId'),
               'requestId': inputs['requestId'],
               'pointerBound': pointer is not None,
               'handleBound': inputs['handleLevelId'] is not None}
    return {'inputs': inputs, 'binding': binding, 'checked': checked}
