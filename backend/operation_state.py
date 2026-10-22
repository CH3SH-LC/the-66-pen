"""T06 -- idempotency, target binding and the ownership ledger.  Offline; no dispatch.

THE ONE THING THIS MODULE MUST NOT DO
-------------------------------------
Build a second "what succeeded" ledger.  ``tools/authoring/author.py`` already writes the
truth: one directory per requestId holding ``claim.json`` (the fingerprint plus the whole
bound command) and, once dispatched, ``result.json``.  This module writes a *business row*
that POINTS at it.  The row records the lifecycle state (G01 D1) and the binding; the
verdict and the receipts are read back out of the bottom-layer journal.  If the two ever
disagreed, the journal would win, and this module would be the bug.

WHY THE ORDER MATTERS (G01 D19, and the bug that proved it)
-----------------------------------------------------------
``author.py`` fingerprints the WHOLE bound command, ``session``/``review``/``baseline``
paths included, and ``derive_review`` mints a fresh review filename on every call.  So
"derive a review, then look at the ledger" makes a replay look, at the bottom layer, like
the SAME requestId carrying a DIFFERENT command -- ``REQUEST_ID_CONFLICT`` instead of the
original receipt.  Every path here is therefore: canonicalise -> validate -> **consult the
ledger** -> only then claim, derive and dispatch.

THE INTERFACE OTHER WORKERS BUILD ON
------------------------------------
For DS-04 / T10 (cleanup ownership) and the main line:

    canonicalize(payload) -> dict                    # NaN/Inf/bool-as-int refused
    binding_for(*, capability_id, target, payload, expected_revision, case_id) -> dict
    binding_digest(binding) -> str                   # sha256 of the canonical encoding
    session_key(handle) -> (processCreation, threadCreation)
    validate_target(handle, *, expected_level_id=None, previous=None, now=None) -> list[str]
    OperationLedger(root, *, clock=None)
        .plan(operation_id, intent) -> {'decision': ..., ...}   # NO side effect
        .claim(...)                                             # atomic; one owner
        .run(intent, *, derive_material, dispatch) -> dict      # the whole ordered flow
        .state_of(operation_id) -> operationState
        .reconcile(operation_id) -> {state, operationState, requestId, journalRef, ...}
        .list_open_operations() -> [row]     # T03 / DS-07: read-only, for a reloaded instance
        .pending()                           # alias of list_open_operations
        .late_receipt(operation_id, receipt) -> {'attributed': bool, ...}
        .ownership(level_id, *, operation_ids=None, candidate_ids=None, since_utc=None)
        .dispatch_evidence(operation_id, native_run=None)

``plan()`` decisions are a closed set:
    'new'       never claimed; the caller may claim, derive and dispatch
    'replay'    a terminal receipt exists for the SAME binding; return it, dispatch nothing
    'pending'   claimed/dispatched with no verified receipt yet; query, never re-dispatch
    'unknown'   the outcome cannot be established; reconcile, never re-dispatch
    'conflict'  the operationId is bound to a DIFFERENT command; refuse before any material
    'refused'   the input or the target is invalid; refuse before any material

WHAT THIS MODULE PROMISES, AND WHAT IT DOES NOT
-----------------------------------------------
It promises: at most one claim per operationId, at most one dispatch per claim, a replay
that derives nothing, an ownership query that cannot be satisfied by a caller-declared id,
and an unknown that is never silently upgraded to a success.

It does NOT promise real exactly-once at the game.  A crash between the native write and
the receipt leaves ``outcome-unknown`` here, and the honest answer stays "go and reconcile"
until somebody reads the original receipt.  ``T06.md`` section 7 says the same.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# NOTE: this module deliberately has no ROOT constant and no default ledger path.  Every
# path it writes is a directory its caller handed it, so it cannot reach the real author
# journal -- or anything else -- by accident.  A test asserts the absence of that constant.

CONTRACT_VERSION = '1'
SCHEMA_VERSION = 1

#: G01 D3: the files whose presence separates ``claimed`` from ``dispatched``.  The first
#: three are quoted verbatim from tools/game-executor/scene_cli.py:685-694, which already
#: implements this discriminator natively; the last two are journal-level.
DISPATCH_EVIDENCE_FILES = ('direct-launch-intent.json', 'launch.claim', 'attempt.used',
                           'helper-request.json', 'bridge-request.json')

#: The lifecycle vocabulary, kept in step with plugins/miliastra/contracts/contract.json.
OPERATION_STATES = ('never-claimed', 'claimed', 'dispatched', 'known-complete',
                    'known-failed', 'outcome-unknown')

#: The claim directory is the mutual exclusion primitive.  One mkdir, one owner.
RECORD_NAME = 'record.json'
CLAIM_NAME = 'claim.json'
RECEIPT_NAME = 'receipt.json'
MATERIAL_NAME = 'material.json'
OWNER_TOKEN = 'owner'

_OPERATION_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class InputInvalid(ValueError):
    """Malformed input.  Refused before the claim, so it leaves no trace to reconcile."""


class OperationConflict(ValueError):
    """The operationId is already bound to a different command (G01 D16)."""

    code = 'REQUEST_ID_CONFLICT'


class TargetRefused(ValueError):
    """The target handle is not a valid, fresh, unchanged target (G01 D26)."""

    code = 'TARGET_HANDLE_INVALID'


class PersistenceFailed(RuntimeError):
    """The ledger could not be written.  Callers must not treat the operation as claimed."""


# --------------------------------------------------------------------------- #
# Canonicalisation -- the input rules of T06 step 02
# --------------------------------------------------------------------------- #

def _canonical_scalar(value: Any, *, path: str) -> Any:
    if isinstance(value, bool):
        return value                      # a bool stays a bool; it is never an integer here
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InputInvalid('%s is not finite; a non-finite number cannot even be '
                               'fingerprinted (author.py encodes with allow_nan=False)' % path)
        return 0.0 if value == 0 else value          # fold -0.0 into 0.0: one placement
    if value is None or isinstance(value, str):
        return value
    raise InputInvalid('%s has the unsupported type %s' % (path, type(value).__name__))


def canonicalize(payload: Any, *, path: str = 'payload') -> Any:
    """The canonical form the binding digest is computed over.

    Rules, each with a test: integers and floats are distinct (a JSON ``true`` is not ``1``);
    ``-0.0`` folds to ``0.0`` so one placement is one command; a non-finite number is refused
    here, before the claim, because the bottom layer's encoder cannot represent it at all;
    an out-of-bounds integer is refused rather than truncated.
    """
    if isinstance(payload, dict):
        return {key: canonicalize(value, path='%s.%s' % (path, key))
                for key, value in sorted(payload.items())}
    if isinstance(payload, (list, tuple)):
        return [canonicalize(value, path='%s[%d]' % (path, index))
                for index, value in enumerate(payload)]
    return _canonical_scalar(payload, path=path)


def uint32(value: Any, *, field: str) -> int:
    """A positive uint32.  ``True`` is rejected: in JSON it is a bool, not a 1."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputInvalid('%s must be an integer' % field)
    if not 0 < value < 2 ** 32:
        raise InputInvalid('%s must be a positive uint32, not %r' % (field, value))
    return value


def finite_vector(value: Any, *, field: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise InputInvalid('%s must be exactly three numbers' % field)
    out = []
    for index, component in enumerate(value):
        if isinstance(component, bool) or not isinstance(component, (int, float)) \
                or not math.isfinite(component):
            raise InputInvalid('%s[%d] must be a finite number' % (field, index))
        out.append(0.0 if component == 0 else float(component))
    return out


def validate_operation_id(operation_id: Any) -> str:
    if not isinstance(operation_id, str) or not _OPERATION_ID.match(operation_id):
        raise InputInvalid('operationId must be 1..80 safe letters, digits, underscore or '
                           'hyphen, starting with a letter or digit')
    return operation_id


def _binding_from(intent: dict) -> dict:
    """Accept either a ready binding or the named intent fields.  ``operationId`` is the
    ledger key, not part of the command identity, so it is ignored here on purpose."""
    if 'binding' in intent and intent['binding'] is not None:
        return intent['binding']
    return binding_for(capability_id=intent['capability_id'], target=intent.get('target'),
                       payload=intent.get('payload') or {}, case_id=intent.get('case_id'))


def binding_digest(binding: dict) -> str:
    import hashlib
    encoded = json.dumps(canonicalize(binding), ensure_ascii=False, sort_keys=True,
                         allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def binding_for(*, capability_id: str, target: Any, payload: dict, case_id: str | None = None) -> dict:
    """The command identity a replay is compared against.

    It covers the capability, the target and the business payload, and deliberately NOT:

    * the execution material (session, review, baseline, queue) -- minted afresh on every
      attempt, so including it would turn every replay into a conflict.  The bottom layer
      DOES include it, on purpose, which is exactly why the ledger must be consulted first;
    * ``expectedRevision`` -- it is a pre-dispatch gate for a NEW operation (T06 step 04),
      not part of what the operation IS.  A replay must return the original record without
      requiring the revision it was created against to still be current.
    """
    if not isinstance(capability_id, str) or not capability_id:
        raise InputInvalid('capabilityId must be a non-empty string')
    if case_id is not None and (not isinstance(case_id, str) or not _OPERATION_ID.match(case_id)):
        raise InputInvalid('caseId must match the operationId shape when present')
    return {'contractVersion': CONTRACT_VERSION, 'capabilityId': capability_id,
            'caseId': case_id, 'target': canonicalize(target, path='target'),
            'payload': canonicalize(payload, path='payload')}


# --------------------------------------------------------------------------- #
# Target identity -- T06 step 08
# --------------------------------------------------------------------------- #

def session_key(handle: dict) -> tuple:
    """The identity of the SESSION behind a handle.  A pid is deliberately not in it.

    MEASURED on this project: a restarted game keeps nothing stable except the image name,
    and pids are reused.  Two handles that share a pid but differ in process creation are
    different sessions, and treating them as one is how a write lands in the wrong level.
    """
    return (handle.get('sessionProcessCreation'), handle.get('sessionThreadCreation'))


def target_key(handle: dict) -> tuple:
    return (handle.get('levelId'),) + session_key(handle)


def validate_target(handle: Any, *, expected_level_id: int | None = None,
                    previous: dict | None = None, now: datetime | None = None,
                    max_age_seconds: int | None = None) -> list[str]:
    """Every reason this handle must not be used, as a list.  [] means usable.

    Refusals, in the order they are checked: not an object; no level; a level that is not the
    one expected; no session identity at all; the same session as ``previous`` but a different
    level; a different session from ``previous`` (a restart is not the same target); no
    receipt digest (the observation is not provable); a superseded handle when a freshness
    window is given.
    """
    problems: list[str] = []
    if not isinstance(handle, dict):
        return ['the handle is not an observation record']
    level = handle.get('levelId')
    if isinstance(level, bool) or not isinstance(level, int) or not 0 < level < 2 ** 32:
        problems.append('TARGET_HANDLE_INVALID: levelId %r is not a uint32' % (level,))
    if expected_level_id is not None and level != expected_level_id:
        problems.append('TARGET_HANDLE_INVALID: the handle names level %r, not the expected %r'
                        % (level, expected_level_id))
    process_creation = handle.get('sessionProcessCreation')
    if isinstance(process_creation, bool) or not isinstance(process_creation, int) \
            or process_creation <= 0:
        problems.append('TARGET_HANDLE_UNVERIFIED: the handle carries no session process '
                        'creation, so there is no identity to hold it to')
    if not handle.get('receiptSha256'):
        problems.append('TARGET_HANDLE_UNVERIFIED: the handle cites no observation receipt, so '
                        'the observation cannot be re-checked')
    if previous is not None:
        if session_key(handle) != session_key(previous) or level != previous.get('levelId'):
            problems.append('TARGET_HANDLE_RECEIPT_CHANGED: the session or the level behind this '
                            'handle is not the one that was bound (handle key %r, bound key %r)'
                            % (target_key(handle), target_key(previous)))
    if max_age_seconds is not None:
        minted = _parse_utc(handle.get('mintedUtc'))
        reference = now or datetime.now(timezone.utc)
        if minted is None:
            problems.append('TARGET_HANDLE_UNVERIFIED: the handle has no mint time, so its age '
                            'cannot be established')
        elif reference - minted > timedelta(seconds=max_age_seconds):
            problems.append('TARGET_HANDLE_UNVERIFIED: the handle was minted at %s and is older '
                            'than %d seconds; re-observe the target' % (handle['mintedUtc'],
                                                                       max_age_seconds))
    return problems


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #

class OperationLedger:
    """A business ledger that points at the bottom-layer journal instead of copying it.

    Layout under ``root``::

        <operationId>/claim.json     written with O_EXCL -- the atomic claim
        <operationId>/record.json    the business row (state + binding + pointers)
        <operationId>/material.json  the execution material THIS attempt derived, hashed
        <operationId>/receipt.json   the verified bottom-layer receipt, published once

    Nothing here ever writes into ``.runtime/authoring/requests``.  Tests point ``root`` at a
    temporary directory; production points it at a directory this project owns.
    """

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None):
        self.root = Path(root)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()

    # -- filesystem primitives ------------------------------------------------ #

    def directory(self, operation_id: str) -> Path:
        return self.root / validate_operation_id(operation_id)

    def _read(self, operation_id: str, name: str) -> dict | None:
        path = self.directory(operation_id) / name
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding='utf-8-sig'))

    def _atomic_write(self, operation_id: str, name: str, payload: dict) -> None:
        """Write via a temporary file and a rename, so a torn write is never a record."""
        directory = self.directory(operation_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / ('.%s.%s.tmp' % (name, uuid.uuid4().hex[:8]))
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                        allow_nan=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / name)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise PersistenceFailed('%s could not be written: %s' % (name, exc)) from None

    def _exclusive_write(self, operation_id: str, name: str, payload: dict) -> bool:
        """True when this call created the file.  ``O_EXCL`` is the mutual exclusion."""
        directory = self.directory(operation_id)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        return True

    # -- state ---------------------------------------------------------------- #

    def dispatch_evidence(self, operation_id: str, native_run: str | Path | None = None) -> list:
        """The named files that moved the state from ``claimed`` to ``dispatched``.

        The journal-level two are always checked.  The native-run three are checked when the
        caller can name the run -- ``scene_cli.py`` names them at :685-694 and this list is
        quoted from there, not re-invented.
        """
        found = []
        directory = self.directory(operation_id)
        for name in ('helper-request.json', 'bridge-request.json'):
            if (directory / name).is_file():
                found.append(name)
        if native_run:
            run = Path(native_run)
            for name in DISPATCH_EVIDENCE_FILES[:3]:
                if (run / name).exists():
                    found.append(name)
        return found

    def state_of(self, operation_id: str, *, native_run: str | Path | None = None) -> str:
        """The authoritative lifecycle state (G01 D1/D2/D4).

        ``claimed`` means *explicitly* that the evidence was looked for and not found -- never
        that nobody looked.  That is why an unreadable ledger is not silently ``claimed``: an
        unreadable ledger raises.
        """
        directory = self.directory(operation_id)
        if not directory.is_dir():
            return 'never-claimed'
        claim = self._read(operation_id, CLAIM_NAME)
        if claim is None:
            # A directory with no claim: G01 records this as REQUEST_INCOMPLETE_CLAIM.  It is
            # not "never claimed" (something was attempted) and it is certainly not a success.
            return 'outcome-unknown'
        receipt = self._read(operation_id, RECEIPT_NAME)
        if receipt is not None:
            return 'known-complete' if receipt.get('ok') is True else 'known-failed'
        record = self._read(operation_id, RECORD_NAME) or {}
        if record.get('state') in ('known-complete', 'known-failed') \
                and record.get('verifiedReceiptSha256'):
            return record['state']
        if record.get('state') == 'outcome-unknown':
            # A dispatch whose outcome was never established.  Reporting it as `claimed`
            # would erase the very fact that something may have reached the game.
            return 'outcome-unknown'
        if self.dispatch_evidence(operation_id, native_run):
            return 'dispatched'
        return 'claimed'

    def reconcile(self, operation_id: str, *, native_run: str | Path | None = None) -> dict:
        """T06 step 07 / G01 D5.  Read the original evidence; never infer from absence.

        The rule this enforces: "I did not see the object" proves nothing about whether a
        write happened.  Only the original receipt, or its absence alongside dispatch
        evidence, decides the verdict.
        """
        state = self.state_of(operation_id, native_run=native_run)
        table = {'never-claimed': 'never-claimed', 'claimed': 'unknown', 'dispatched': 'unknown',
                 'outcome-unknown': 'unknown', 'known-complete': 'known-success',
                 'known-failed': 'known-failure'}
        record = self._read(operation_id, RECORD_NAME) or {}
        receipt = self._read(operation_id, RECEIPT_NAME)
        evidence = self.dispatch_evidence(operation_id, native_run)
        return {'operationId': operation_id, 'operationState': state,
                'reconcileState': table[state],
                'requestId': record.get('requestId'),
                'journalRef': record.get('journalRef'),
                'dispatchEvidence': evidence,
                'receipt': receipt,
                'note': ('a claim without a verified receipt is an unknown outcome: read the '
                         'original evidence, do not resend') if state in ('claimed', 'dispatched',
                                                                           'outcome-unknown')
                        else None}

    def list_open_operations(self) -> list:
        """Every operation that is not terminal, for an instance that was TOLD NOTHING.

        T03 section 4 step 08 / DS-07: a reloaded plugin has no memory of what the previous
        instance was doing, so it must be able to SEE the in-flight operations rather than
        guess.  This function only reads.  Nothing here claims, dispatches, derives or
        repairs -- the entry point exists so that "I did not know about it" stops being a
        reason to re-send a write.

        Each row carries enough to act without opening the ledger by hand: the state, the
        reconcile verdict, the bound requestId, the journal pointer and the owner.  A row is
        never a licence to dispatch; ``operationsNeedingReconcile`` names the ones that must
        be read before anything else happens.
        """
        if not self.root.is_dir():
            return []
        out = []
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and entry.name != OWNER_TOKEN and _OPERATION_ID.match(entry.name):
                state = self.state_of(entry.name)
                if state in ('claimed', 'dispatched', 'outcome-unknown'):
                    record = self._read(entry.name, RECORD_NAME) or {}
                    claim = self._read(entry.name, CLAIM_NAME) or {}
                    out.append({'operationId': entry.name, 'operationState': state,
                                'reconcileState': self.reconcile(entry.name)['reconcileState'],
                                'capabilityId': record.get('capabilityId') or
                                                (claim.get('binding') or {}).get('capabilityId'),
                                'targetHandle': record.get('targetHandle'),
                                'requestId': record.get('requestId'),
                                'journalRef': record.get('journalRef'),
                                'owner': claim.get('owner'),
                                'claimedUtc': claim.get('claimedUtc'),
                                'dispatchEvidence': self.dispatch_evidence(entry.name),
                                'nextAction': ('reconcile' if state == 'outcome-unknown'
                                               else 'poll-same-operation')})
        return out

    #: Kept under the older name as well so neither caller has to change at once.
    pending = list_open_operations

    # -- the claim and the plan ----------------------------------------------- #

    def plan(self, operation_id: str, intent: dict) -> dict:
        """Decide what to do, with NO side effect of any kind.

        This is the function the whole module exists for, and it must be called BEFORE any
        review, baseline, backup or session path is derived (G01 D19).  It creates no
        directory, writes no file and calls nothing.
        """
        validate_operation_id(operation_id)
        binding = _binding_from(intent)
        directory = self.directory(operation_id)
        if not directory.is_dir():
            return {'decision': 'new', 'operationId': operation_id, 'binding': binding,
                    'bindingDigest': binding_digest(binding), 'state': 'never-claimed'}
        claim = self._read(operation_id, CLAIM_NAME)
        if claim is None:
            return {'decision': 'unknown', 'operationId': operation_id,
                    'code': 'REQUEST_INCOMPLETE_CLAIM', 'state': 'outcome-unknown',
                    'reason': 'a claim directory exists without its claim: there is no evidence '
                              'of what was requested, and nothing may be resent'}
        recorded = claim.get('binding') or {}
        if binding_digest(recorded) != binding_digest(binding):
            return {'decision': 'conflict', 'operationId': operation_id,
                    'code': 'REQUEST_ID_CONFLICT', 'state': 'outcome-unknown',
                    'recordedBinding': recorded, 'suppliedBinding': binding,
                    'reason': 'this operationId is already bound to a different capability, '
                              'target or payload'}
        state = self.state_of(operation_id)
        if state == 'known-complete' or state == 'known-failed':
            return {'decision': 'replay', 'operationId': operation_id, 'state': state,
                    'binding': binding, 'receipt': self._read(operation_id, RECEIPT_NAME),
                    'reason': 'the same operationId and the same bound command already have a '
                              'verified receipt; return it and dispatch nothing'}
        if state == 'outcome-unknown':
            return {'decision': 'unknown', 'operationId': operation_id, 'state': state,
                    'code': 'REQUEST_OUTCOME_UNKNOWN', 'reconcile': self.reconcile(operation_id),
                    'reason': 'claimed with no verified receipt: reconcile, never resend'}
        return {'decision': 'pending', 'operationId': operation_id, 'state': state,
                'code': 'UPSTREAM_PENDING', 'reconcile': self.reconcile(operation_id),
                'reason': 'the operation is in flight; query the same operation'}

    def claim(self, operation_id: str, intent: dict, *, owner: str) -> dict:
        """Atomically take ownership.  The loser of a race gets the winner's row, not a claim.

        ``os.open(..., O_CREAT | O_EXCL)`` is the whole mutual exclusion: one process creates
        the claim file, everyone else finds it.  No lock file, no timeout, no stale-lock
        recovery to get wrong.
        """
        validate_operation_id(operation_id)
        if not isinstance(owner, str) or not owner:
            raise InputInvalid('an owner token is required; the claim has exactly one holder')
        binding = _binding_from(intent)
        digest = binding_digest(binding)
        now = self._clock().isoformat()
        created = self._exclusive_write(operation_id, CLAIM_NAME,
                                        {'schemaVersion': SCHEMA_VERSION,
                                         'contractVersion': CONTRACT_VERSION,
                                         'operationId': operation_id, 'owner': owner,
                                         'binding': binding, 'bindingDigest': digest,
                                         'expectedRevision': intent.get('expected_revision'),
                                         'claimedUtc': now})
        if not created:
            existing = self._read(operation_id, CLAIM_NAME) or {}
            if existing.get('bindingDigest') != digest:
                raise OperationConflict('operationId %r is already claimed by %r for a different '
                                        'command' % (operation_id, existing.get('owner')))
            return {'claimed': False, 'owner': existing.get('owner'), 'bindingDigest': digest,
                    'plan': self.plan(operation_id, {'binding': binding}), 'claimedUtc':
                    existing.get('claimedUtc')}
        try:
            self._atomic_write(operation_id, RECORD_NAME,
                               {'schemaVersion': SCHEMA_VERSION,
                                'contractVersion': CONTRACT_VERSION,
                                'operationId': operation_id,
                                'capabilityId': binding.get('capabilityId'),
                                'caseId': binding.get('caseId'),
                                'targetHandle': (binding.get('target') or {}).get('handle'),
                                'target': binding.get('target'),
                                'expectedRevision': intent.get('expected_revision'),
                                'payloadDigest': binding_digest(binding.get('payload') or {}),
                                'state': 'claimed', 'writeExecuted': False,
                                'dispatchEvidence': [], 'requestId': None,
                                'owner': owner, 'createdUtc': now, 'updatedUtc': now,
                                'retryAttempted': False})
        except PersistenceFailed:
            # The claim exists but the row does not.  The caller must NOT dispatch: an
            # operation whose ledger row could not be written cannot be reconciled later.
            raise
        return {'claimed': True, 'owner': owner, 'bindingDigest': digest, 'claimedUtc': now}

    # -- binding execution material ------------------------------------------- #

    def bind_material(self, operation_id: str, *, request_id: str, material: dict,
                      journal_ref: str) -> dict:
        """Record the ONE set of execution material this operation derived (T06 step 05).

        Written once.  A later call with different material is a conflict rather than an
        overwrite, because the bottom layer's fingerprint includes this material and
        re-deriving it would make a replay look like a different command.
        """
        validate_operation_id(request_id)
        digest = binding_digest(material)
        payload = {'requestId': request_id, 'materialDigest': digest, 'material': material,
                   'journalRef': journal_ref, 'boundUtc': self._clock().isoformat()}
        existing = self._read(operation_id, MATERIAL_NAME)
        if existing is not None:
            if existing.get('requestId') != request_id or existing.get('materialDigest') != digest:
                raise OperationConflict('operationId %r already bound its execution material to '
                                        'requestId %r; deriving a second set would change the '
                                        'bottom-layer fingerprint and turn a replay into a '
                                        'conflict' % (operation_id, existing.get('requestId')))
            return dict(existing, alreadyBound=True)
        self._atomic_write(operation_id, MATERIAL_NAME, payload)
        row = self._read(operation_id, RECORD_NAME) or {}
        row.update(requestId=request_id, journalRef=journal_ref, materialDigest=digest,
                   updatedUtc=self._clock().isoformat())
        self._atomic_write(operation_id, RECORD_NAME, row)
        return payload

    def mark_dispatched(self, operation_id: str, *, evidence: Sequence[str], request_id: str) -> dict:
        row = self._read(operation_id, RECORD_NAME) or {}
        row.update(state='dispatched', dispatchEvidence=list(evidence), requestId=request_id,
                   writeExecuted=None, updatedUtc=self._clock().isoformat())
        self._atomic_write(operation_id, RECORD_NAME, row)
        return row

    def publish(self, operation_id: str, receipt: dict, *, expected_request_id: str | None = None,
                expected_target: dict | None = None) -> dict:
        """Publish the verified bottom-layer receipt (T06 step 06).

        A receipt is published only if it can be attributed: it must name the requestId this
        operation bound, and, when the target is known, the same (levelId, session) key.  A
        receipt that fails attribution is refused rather than written -- a late receipt from
        another instance must not become this operation's answer.
        """
        if not isinstance(receipt, dict):
            raise InputInvalid('a receipt must be an object')
        recorded = (self._read(operation_id, MATERIAL_NAME) or {}).get('requestId')
        request_id = receipt.get('requestId') or (receipt.get('backend') or {}).get('requestId')
        bound = expected_request_id or recorded
        if bound and request_id and request_id != bound:
            raise OperationConflict('receipt names requestId %r but this operation bound %r; a '
                                    'receipt for another request never becomes this answer'
                                    % (request_id, bound))
        if expected_target is not None:
            level = (receipt.get('backend') or {}).get('levelId')
            if level is not None and level != expected_target.get('levelId'):
                raise TargetRefused('receipt reports level %r, not the bound %r'
                                    % (level, expected_target.get('levelId')))
        existing = self._read(operation_id, RECEIPT_NAME)
        if existing is not None and binding_digest(existing) != binding_digest(receipt):
            raise OperationConflict('a receipt is already published for operationId %r and this '
                                    'one differs; the first verified answer is the answer, and a '
                                    'later arrival does not overwrite it' % operation_id)
        state = 'known-complete' if receipt.get('ok') is True else 'known-failed'
        self._atomic_write(operation_id, RECEIPT_NAME, receipt)
        row = self._read(operation_id, RECORD_NAME) or {}
        row.update(state=state, writeExecuted=True if receipt.get('ok') is True else row.get(
            'writeExecuted'), updatedUtc=self._clock().isoformat(),
            verifiedReceiptSha256=binding_digest(receipt))
        self._atomic_write(operation_id, RECORD_NAME, row)
        return row

    def mark_unknown(self, operation_id: str, *, reason: str) -> dict:
        """The dispatch happened (or may have) and no verified receipt was obtained."""
        row = self._read(operation_id, RECORD_NAME) or {}
        row.update(state='outcome-unknown', writeExecuted=True, terminalReason=reason,
                   updatedUtc=self._clock().isoformat())
        self._atomic_write(operation_id, RECORD_NAME, row)
        return row

    def late_receipt(self, operation_id: str, receipt: dict) -> dict:
        """Attribute a receipt that arrived after the attempt had already given up.

        It belongs to the original operation -- and to nobody else.  If the receipt names a
        different requestId or a different level than the operation bound, it is refused; a
        late arrival is never a licence to overwrite a newer case.
        """
        claim = self._read(operation_id, CLAIM_NAME)
        if claim is None:
            return {'operationId': operation_id, 'attributed': False,
                    'code': 'REQUEST_OUTCOME_UNKNOWN',
                    'reason': 'no claim exists for this operationId, so this receipt cannot be '
                              'attributed to it'}
        material = self._read(operation_id, MATERIAL_NAME) or {}
        bound_request = material.get('requestId')
        incoming = receipt.get('requestId') or (receipt.get('backend') or {}).get('requestId')
        if bound_request and incoming and incoming != bound_request:
            return {'operationId': operation_id, 'attributed': False,
                    'code': 'REQUEST_ID_CONFLICT', 'boundRequestId': bound_request,
                    'incomingRequestId': incoming,
                    'reason': 'the receipt belongs to another request; it is not this '
                              'operation\'s answer'}
        bound_target = (claim.get('binding') or {}).get('target') or {}
        incoming_level = (receipt.get('backend') or {}).get('levelId')
        if bound_target.get('levelId') is not None and incoming_level is not None \
                and incoming_level != bound_target.get('levelId'):
            return {'operationId': operation_id, 'attributed': False,
                    'code': 'TARGET_HANDLE_RECEIPT_CHANGED', 'boundLevelId':
                    bound_target.get('levelId'), 'incomingLevelId': incoming_level,
                    'reason': 'the receipt reports another level; it does not describe this '
                              'operation\'s target'}
        published = self.publish(operation_id, receipt, expected_request_id=bound_request)
        return {'operationId': operation_id, 'attributed': True, 'state': published['state'],
                'receipt': receipt}

    # -- the ordered flow ------------------------------------------------------ #

    def run(self, intent: dict, *, derive_material: Callable[[str, dict], dict],
            dispatch: Callable[[dict], dict], owner: str | None = None,
            verify_target: Callable[[dict], list] | None = None,
            current_revision: Callable[[dict], str | None] | None = None) -> dict:
        """Canonicalise -> validate -> consult -> claim -> bind -> dispatch -> publish.

        The order is the point.  ``derive_material`` is called ONLY when the ledger says this
        is a genuinely new operation, which is what makes "a duplicate never generates a
        second review" a structural fact rather than a promise.  ``dispatch`` is called at
        most once per operationId.

        ``current_revision`` is the pre-dispatch version gate (G01 D26 / T06 step 04).  It is
        consulted ONLY for a genuinely new operation: a replay returns the original record
        without requiring the revision it was created against to still be current.
        """
        operation_id = validate_operation_id(intent['operationId'])
        if verify_target is not None:
            problems = verify_target(intent.get('target') or {})
            if problems:
                return {'decision': 'refused', 'operationId': operation_id, 'state': 'never-claimed',
                        'problems': problems, 'dispatched': False, 'derivedMaterial': False}
        binding = _binding_from(intent)
        decision = self.plan(operation_id, {'binding': binding})
        if decision['decision'] != 'new':
            return dict(decision, dispatched=False, derivedMaterial=False)

        expected = intent.get('expected_revision')
        if expected is not None and current_revision is not None:
            actual = current_revision(intent.get('target') or {})
            if actual != expected:
                return {'decision': 'refused', 'operationId': operation_id,
                        'state': 'never-claimed', 'code': 'TARGET_STALE_REVISION',
                        'expectedRevision': expected, 'actualRevision': actual,
                        'dispatched': False, 'derivedMaterial': False,
                        'reason': 'the target has moved since this revision was observed; nothing '
                                  'was claimed and nothing was dispatched'}

        claimed = self.claim(operation_id, {'binding': binding},
                             owner=owner or ('owner-' + uuid.uuid4().hex[:8]))
        if not claimed['claimed']:
            # Lost the race between plan() and claim().  The winner owns the operation, so this
            # attempt derives nothing and dispatches nothing; it reports what the winner has.
            return dict(claimed['plan'], dispatched=False, derivedMaterial=False, lostRace=True)
        material = derive_material(operation_id, binding)
        self.bind_material(operation_id, request_id=material['requestId'],
                           material={k: v for k, v in material.items() if k != 'requestId'},
                           journal_ref=material.get('journalRef') or '')
        self.mark_dispatched(operation_id, evidence=['helper-request.json'],
                             request_id=material['requestId'])
        try:
            receipt = dispatch({**binding, **material})
        except Exception as exc:                      # noqa: BLE001 - reported, never swallowed
            self.mark_unknown(operation_id, reason='%s: the dispatch raised, so the outcome is '
                                                   'not established' % type(exc).__name__)
            return {'decision': 'unknown', 'operationId': operation_id,
                    'state': 'outcome-unknown', 'code': 'REQUEST_OUTCOME_UNKNOWN',
                    'reconcile': self.reconcile(operation_id), 'dispatched': True,
                    'derivedMaterial': True}
        if receipt is None:
            self.mark_unknown(operation_id, reason='the dispatch returned no receipt; the '
                                                   'outcome is not established')
            return {'decision': 'unknown', 'operationId': operation_id,
                    'state': 'outcome-unknown', 'code': 'REQUEST_OUTCOME_UNKNOWN',
                    'reconcile': self.reconcile(operation_id), 'dispatched': True,
                    'derivedMaterial': True}
        row = self.publish(operation_id, receipt, expected_request_id=material['requestId'],
                           expected_target=binding.get('target'))
        return {'decision': 'completed' if row['state'] == 'known-complete' else 'failed',
                'operationId': operation_id, 'state': row['state'], 'receipt': receipt,
                'dispatched': True, 'derivedMaterial': True}

    # -- ownership (DS-04 / T10) ---------------------------------------------- #

    def ownership(self, level_id: int, *, operation_ids: Iterable[str] | None = None,
                  candidate_ids: Sequence[int] | None = None,
                  since_utc: str | None = None) -> dict:
        """Which entity ids this ledger can prove were created IN THIS LEVEL by this run.

        THE KEY IS ``(levelId, entityId)`` PLUS THIS RUN'S OWN RECEIPT -- never the id alone.
        MEASURED on this project: entity id 1077936133 exists on level 1073741834 and on level
        1073741839.  An id-only query returns the wrong operation, and an id-only delete list
        deletes the wrong object.

        A caller-declared id is never accepted as proof: ``candidate_ids`` is a question, not
        an assertion.  Each candidate comes back owned, refused, or unknown -- never absent,
        so a caller cannot read silence as a yes.
        """
        wanted = set(operation_ids) if operation_ids is not None else None
        since = _parse_utc(since_utc)
        owned: list = []
        refused: list = []
        unknown: list = []
        seen: dict = {}
        if self.root.is_dir():
            for entry in sorted(self.root.iterdir()):
                if not entry.is_dir() or not _OPERATION_ID.match(entry.name):
                    continue
                if wanted is not None and entry.name not in wanted:
                    continue
                record = self._read(entry.name, RECORD_NAME) or {}
                bound_level = (record.get('target') or {}).get('levelId')
                if bound_level is not None and bound_level != level_id:
                    continue        # bound to another level: not this level's owned set
                if since is not None:
                    claimed = _parse_utc(self._read(entry.name, CLAIM_NAME).get('claimedUtc')
                                         if self._read(entry.name, CLAIM_NAME) else None)
                    if claimed is not None and claimed < since:
                        continue
                receipt = self._read(entry.name, RECEIPT_NAME)
                if receipt is None:
                    continue
                backend = receipt.get('backend') or {}
                if backend.get('action') != 'create' or receipt.get('ok') is not True:
                    continue
                entity_id = backend.get('entityId')
                receipt_level = backend.get('levelId')
                if not isinstance(entity_id, int) or isinstance(entity_id, bool):
                    continue
                if receipt_level is None:
                    unknown.append({'entityId': entity_id, 'operationId': entry.name,
                                    'code': 'TARGET_HANDLE_UNVERIFIED',
                                    'reason': 'the create receipt names no level, so this id '
                                              'cannot be attributed to a level'})
                    continue
                if receipt_level != level_id:
                    continue        # a create in another level; not owned here
                seen[entity_id] = {'entityId': entity_id, 'operationId': entry.name,
                                   'requestId': record.get('requestId'),
                                   'levelId': receipt_level,
                                   'journalRef': record.get('journalRef'),
                                   'receiptSha256': binding_digest(receipt),
                                   'claimedUtc': (self._read(entry.name, CLAIM_NAME) or {}).get(
                                       'claimedUtc')}
        owned = sorted(seen.values(), key=lambda row: row['entityId'])
        result = {'levelId': level_id, 'owned': owned, 'refused': refused, 'unknown': unknown,
                  'basis': 'a create receipt bound to this run\'s operation, whose target is this '
                           'level and whose receipt names the same level; the id alone is not '
                           'evidence'}
        if candidate_ids is not None:
            owned_by_id = {row['entityId']: row for row in owned}
            known_unknown = {row['entityId']: row for row in unknown}
            asked_owned, asked_refused, asked_unknown = [], [], []
            for entity_id in candidate_ids:
                if entity_id in owned_by_id:
                    asked_owned.append(owned_by_id[entity_id])
                elif entity_id in known_unknown:
                    asked_unknown.append(known_unknown[entity_id])
                else:
                    asked_refused.append({
                        'entityId': entity_id, 'code': 'CLEANUP_ID_NOT_OWNED_BY_THIS_RUN',
                        'reason': 'no create receipt of this run produced this id in level %r; a '
                                  'caller-declared id is not proof of ownership' % level_id})
            result.update(owned=asked_owned, refused=asked_refused, unknown=asked_unknown)
            result['requestedIds'] = list(candidate_ids)
        return result


__all__ = ['CLAIM_NAME', 'CONTRACT_VERSION', 'DISPATCH_EVIDENCE_FILES', 'InputInvalid',
           'MATERIAL_NAME', 'OPERATION_STATES', 'OperationConflict', 'OperationLedger',
           'PersistenceFailed', 'RECEIPT_NAME', 'RECORD_NAME', 'SCHEMA_VERSION', 'TargetRefused',
           'binding_digest', 'binding_for', 'canonicalize', 'finite_vector', 'session_key',
           'target_key', 'uint32', 'validate_operation_id', 'validate_target']
