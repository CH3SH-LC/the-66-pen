"""Claim/outcome journal for the cleanup dispatch route (``mw_scene_cleanup_owned``).

WHY THIS EXISTS
===============
``mw_scene_cleanup_owned`` is the one business route whose native operation is not
idempotent at the transport.  The delete travels as an elevated-queue request that
carries no requestId -- the model supplies none -- so a repeated call is byte-for-byte
indistinguishable from a request to delete the same ids a second time.  Create and save
solved exactly this with the author journal (``tools/authoring/author.py``,
``backend/entity_server.py`` ``consult_journal``): one DIRECTORY per request, created
exclusively BEFORE the dispatch, holding ``claim.json`` (what was requested) and, once
recorded, ``result.json`` (what came back).  A repeat reads the outcome; a claim with no
outcome is refused, never re-sent.

The cleanup route cannot use ``JOURNAL_ROOT`` as-is: it has no requestId in its
signature, and its identity is the ROUND (a digest of the create requestIds whose
materials the route must prove ownership against), not a single create.  So this module
is the same protocol, with the identity spelled out:

    request   who is asking, for which round and which batch.
              * if the caller names it (``cleanupRequestId``), that name IS the request
                identity: one name, at most one dispatch, exactly like create/save;
              * if the caller names none, the identity is derived from the command
                itself (``cmd-<fingerprint>``).  A repeat is still recognised and the
                transport is still never reached twice, but two DIFFERENT commands can
                never be told apart as "the same request", because nothing else is
                available to compare -- see ``request_identity``.
    command   the dispatch key the route already computes:
              ``_cleanup_dispatch_key(owned ids, dryRun, bridgeRunId)``.

THE FOUR PROTECTIONS, AND WHERE EACH IS ENFORCED
================================================
    (1) same request, same command        -> the recorded outcome is REPLAYED, and
                                             nothing is dispatched again.
    (2) same request, different command   -> DispatchJournalError(REQUEST_ID_CONFLICT);
                                             the earlier dispatch stands.
    (3) claim recorded, outcome unknown   -> DispatchJournalError(OUTCOME_UNKNOWN);
                                             reconcile only, never re-send.
    (4) two racing calls, same request    -> ``Path.mkdir`` without ``exist_ok`` is the
                                             mutex: exactly one wins, writes the claim
                                             and dispatches.  Every loser refuses, in one
                                             of the three legitimate ways -- the claim is
                                             not there yet (INCOMPLETE_CLAIM), it is there
                                             with no outcome (OUTCOME_UNKNOWN), or the
                                             outcome is there and is replayed (1).  Which
                                             one it is depends on how far the winner got;
                                             what is invariant is that a loser NEVER sends.

(2) and (4) are the two the single-slot per-round record could not give: one slot could
hold only the LAST command, so an earlier batch was forgotten and re-dispatched, and a
plain read-then-write let two concurrent calls both observe "no claim" and both send.
The claim is therefore an exclusive ``mkdir`` of the request directory, and the record
is per request, not per round -- the round is only the parent directory that the route
has already proven exists (it holds ``round-materials.json``).

WHAT THIS MODULE DOES NOT DO
============================
It dispatches nothing, resolves no queue, reads no game state and imports nothing from
the MCP layer.  It reads and writes JSON beside the round materials, under the
``EVIDENCE_ROOT`` the caller passes -- a directory that is a *tool argument* only in the
tests.  Every write fails closed: an unwritable claim refuses the dispatch rather than
permitting a blind repeat.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

#: The same shape ``author.py`` requires of a requestId: 1..80 characters, starting
#: alphanumeric, then letters/digits/underscore/hyphen.  Two identities that share one
#: directory on a case-insensitive filesystem would be one identity; this set has no such
#: collisions and no path separators, so the name is a single, safe path component.
REQUEST_ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}')

#: The prefix of a DERIVED request identity.  A caller-supplied name is never rewritten,
#: so a directory whose name starts with this can only have come from a caller that
#: supplied no name -- the two sources can never be confused for one another.
DERIVED_REQUEST_PREFIX = 'cmd-'


class DispatchJournalError(RuntimeError):
    """A refusal with a stable code.  Raised before any dispatch or not at all."""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def canonical(value):
    """The one encoding a fingerprint may be taken over: sorted keys, no NaN.

    Sorted keys is what makes ``{'a': 1, 'b': 2}`` and ``{'b': 2, 'a': 1}`` one command;
    ``allow_nan=False`` is what stops a NaN transform from hashing as if it were equal to
    itself in a way a reader could not reproduce.
    """
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def fingerprint(binding):
    return hashlib.sha256(canonical(binding).encode('utf-8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _atomic_json(path, payload):
    """Write JSON so a concurrent reader never sees it half-written.

    The scratch file is a sibling of the target, so ``os.replace`` stays on one
    filesystem and is atomic.  The exclusive create of the request DIRECTORY, not this
    write, is the mutex: only one writer ever reaches here for a given request, so this
    only has to keep the loser's read from landing mid-write.  MEASURED 2026-10-05 by the
    six-process control in ``backend/tests/f011guard/test_cleanup_journal.py``: an
    in-place ``open('x')`` create let a racing reader see a claim.json that existed but was
    still EMPTY, which is a refusal (fail closed) but a needlessly illegible one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + '.part-' + uuid.uuid4().hex[:8])
    try:
        with scratch.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(canonical(payload) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
    except OSError:
        # A failed write must not leave a scratch sibling behind.  It is not evidence, and
        # a leftover one keeps the request directory non-empty -- which would defeat the
        # caller's attempt to reclaim that directory (see consult()).  Best effort: if the
        # unlink fails too, the original error is still the one that matters.
        try:
            scratch.unlink()
        except OSError:
            pass
        raise
    return path


def request_identity(request_id, binding):
    """The request this dispatch belongs to, as a single safe path component.

    A caller-supplied ``cleanupRequestId`` is validated and used verbatim: it is the
    caller's statement that "this is one request", which is the only thing that can make
    two commands comparable as "the same request, a different command" (protection 2).

    With no name supplied the identity is derived from the command.  That keeps a repeat
    recognisable -- the same command derives the same name, so protection 1 still holds
    and the transport is still never reached twice for one command -- but a derived
    identity CANNOT express protection 2, because two different commands derive two
    different names and nothing in the call says they were meant to be one request.  That
    asymmetry is the reason the caller is offered the name at all, and it is reported
    rather than hidden.
    """
    if request_id is None:
        return DERIVED_REQUEST_PREFIX + fingerprint(binding)[:32]
    if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise DispatchJournalError(
            'CLEANUP_REQUEST_ID_INVALID',
            'cleanupRequestId must be 1..80 characters, starting with a letter or digit, '
            'then letters, digits, underscore or hyphen; it names one cleanup dispatch and '
            'becomes a directory name, so it may not contain a path separator.',
            cleanupRequestId=repr(request_id))
    return request_id


def journal_directory(evidence_root, round_id, request_id):
    """Where one request's claim and outcome live.

    A child of the round directory, which the route has already proven exists by reading
    ``round-materials.json`` out of it -- the same reason the earlier single record was
    placed there.  Per request, so an outcome can never overwrite another request's.
    """
    return Path(evidence_root) / 'cleanup' / round_id / 'dispatch-journal' / request_id


def consult(evidence_root, round_id, request_id, binding, *, level_id=None):
    """Consult the journal BEFORE the dispatch.  Returns the terminal state.

    ``{'state': 'claimed',  'requestId', 'directory', 'claimedAtUtc'}``
        This call created the request directory exclusively and wrote the claim: it is
        the one writer allowed to dispatch.
    ``{'state': 'replayed', 'requestId', 'directory', 'receipt', 'record'}``
        The same request, the same command, and a recorded outcome: replay it.
        ``receipt`` is the recorded REPLY (what the transport answered); ``record`` is the
        whole journal document, for a caller that wants to cite the claim too.

    Raises ``DispatchJournalError`` for protection (2) (REQUEST_ID_CONFLICT), protection
    (3) (OUTCOME_UNKNOWN), a request directory with no claim (INCOMPLETE_CLAIM) and an
    unwritable claim (RECORD_UNWRITABLE).  Every one of those is a refusal BEFORE any
    dispatch.
    """
    request_id = request_identity(request_id, binding)
    directory = journal_directory(evidence_root, round_id, request_id)
    digest = fingerprint(binding)
    try:
        directory.mkdir(parents=True)
    except FileExistsError:
        pass
    else:
        # THE mutex.  Only the process that created this directory can be here, so only
        # it may dispatch; every concurrent caller took the branch above and will find
        # this claim (or its absence, which is also a refusal) rather than an empty slot.
        claimed_at = utc_now()
        try:
            _atomic_json(directory / 'claim.json', {
                'schemaVersion': 1, 'kind': 'cleanup-dispatch-claim',
                'requestId': request_id, 'roundId': round_id, 'levelId': level_id,
                'fingerprint': digest, 'command': binding, 'claimedAtUtc': claimed_at,
                'outcomeKnown': False})
        except OSError as exc:
            # Fail closed, before anything is sent.  Without the claim a repeat of this
            # very call is indistinguishable from a first one.
            #
            # But the directory this call created must NOT outlive the failed claim.  A
            # later retry would find it, look for claim.json, find none, and be refused as
            # CLEANUP_REQUEST_INCOMPLETE_CLAIM for ever -- including after the transient
            # error that caused this has cleared.  MEASURED 2026-10-05 (round 124, R2's
            # F2).  So remove what we created and let the name be claimed again.  Best
            # effort: if the removal fails, the refusal below is still correct, just less
            # recoverable, and this error says so rather than pretending.
            cleanup_error = None
            try:
                directory.rmdir()
            except OSError as cleanup_exc:
                cleanup_error = str(cleanup_exc)
            raise DispatchJournalError(
                'CLEANUP_DISPATCH_RECORD_UNWRITABLE',
                'the re-entry claim could not be written, so a repeat of this call could '
                'not be told apart from a first one; nothing was dispatched.',
                roundId=round_id, journalDirectory=str(directory), error=str(exc),
                **({'directoryNotRemoved': cleanup_error} if cleanup_error else {}))
        return {'state': 'claimed', 'requestId': request_id, 'directory': str(directory),
                'claimedAtUtc': claimed_at}

    claim_path = directory / 'claim.json'
    if not claim_path.is_file():
        # A directory with no claim is not "never claimed": it is a request whose own
        # evidence is missing, and there is nothing to compare a command against.  It is
        # also what a concurrent LOSER sees when it arrives between the winner's exclusive
        # mkdir and the winner's claim write -- another refusal, and equally never a send.
        raise DispatchJournalError(
            'CLEANUP_REQUEST_INCOMPLETE_CLAIM',
            'a cleanup request directory exists without its claim: either a concurrent call '
            'holds this request right now, or its evidence is missing. In both cases what was '
            'requested cannot be shown, so nothing may be dispatched.',
            roundId=round_id, journalDirectory=str(directory))
    recorded = read_json(claim_path)
    if recorded.get('fingerprint') != digest:
        raise DispatchJournalError(
            'CLEANUP_REQUEST_ID_CONFLICT',
            'this cleanupRequestId is already bound to a different command (a different id '
            'set, dryRun or bridge run). One request is one dispatch; a different command '
            'needs a different cleanupRequestId.',
            roundId=round_id, journalDirectory=str(directory),
            cleanupRequestId=request_id,
            recordedCommand=recorded.get('command'), suppliedCommand=binding,
            recordedAtUtc=recorded.get('claimedAtUtc'))
    result_path = directory / 'result.json'
    if not result_path.is_file():
        raise DispatchJournalError(
            'CLEANUP_DISPATCH_OUTCOME_UNKNOWN',
            # "already dispatched" would be a claim this function cannot support.  The CLAIM
            # is written BEFORE the call to the transport, so a claim with no result means a
            # dispatch was ATTEMPTED and no outcome was observed -- the request may never have
            # reached the queue at all (a timeout, a missing interpreter, or a transport that
            # died before writing anything).  MEASURED 2026-10-05 (round 124): with the
            # transport raising, this refusal fired for a call whose dispatch raised, so
            # nothing reached the queue -- and the same request identity could never be
            # retried afterwards.  The round-116 version of this route carried the same
            # wording.  What is true, and what the caller must act on, is narrower: nothing
            # was observed, so the effect is UNKNOWN.  The refusal itself is correct and
            # stays -- an unobserved write is never re-sent.
            'a cleanup with this request identity was ATTEMPTED and no outcome was ever '
            'recorded, so whether the level still holds these ids is UNKNOWN -- the request may '
            'not have reached the queue at all. Reconcile from the claim and a fresh read-back '
            'of the level; do not send the delete again.',
            roundId=round_id, journalDirectory=str(directory),
            cleanupRequestId=request_id,
            dispatchedIds=list(binding.get('ids') or []),
            dispatchedDryRun=binding.get('dryRun'),
            claimedAtUtc=recorded.get('claimedAtUtc'))
    record = read_json(result_path)
    return {'state': 'replayed', 'requestId': request_id, 'directory': str(directory),
            'receipt': record.get('reply'), 'record': record}


def record_outcome(directory, request_id, round_id, binding, reply):
    """Write the outcome of the dispatch this call was allowed to make.

    Written with the same exclusive create as the claim.  If it fails the CLAIM still
    stands, so a repeat is refused as an unknown outcome rather than re-sent -- fail
    closed, and let the caller say so in its own reply.
    """
    return _atomic_json(Path(directory) / 'result.json', {
        'schemaVersion': 1, 'kind': 'cleanup-dispatch-record',
        'requestId': request_id, 'roundId': round_id,
        'fingerprint': fingerprint(binding), 'command': binding,
        'recordedAtUtc': utc_now(), 'outcomeKnown': True, 'reply': reply})


def status(evidence_root, round_id, request_id, binding):
    """Reconcile one request WITHOUT dispatching anything.  Protection (3)'s other half.

    ``never-claimed`` / ``claimed-without-result`` (``outcomeKnown`` False) / ``complete``
    (the recorded receipt).  This is the read-only answer a caller uses after an unknown
    outcome; it never dispatches and never re-sends.
    """
    request_id = request_identity(request_id, binding)
    directory = journal_directory(evidence_root, round_id, request_id)
    if not directory.is_dir():
        return {'state': 'never-claimed', 'outcomeKnown': True, 'requestId': request_id,
                'journalDirectory': str(directory),
                'note': 'no claim was ever written for this request'}
    claim_path = directory / 'claim.json'
    result_path = directory / 'result.json'
    record = read_json(result_path) if result_path.is_file() else None
    return {'state': 'complete' if record else 'claimed-without-result',
            'outcomeKnown': record is not None,
            'requestId': request_id, 'journalDirectory': str(directory),
            'claim': read_json(claim_path) if claim_path.is_file() else None,
            'record': record,
            'note': 'a claim without a result is an unknown outcome: reconcile, never resend'}
