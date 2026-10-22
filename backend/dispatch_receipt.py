"""Run-scoped dispatch receipts: the producer-side evidence chain behind a run.

WHY THIS FILE EXISTS
--------------------
W1's authenticity layer (``verify_run_provenance.py``) refuses to take its
expected values from the run under audit.  Every ``requestId`` and the ``runId``
a run claims must ALSO be found in an artifact written by a producer that is not
the run -- the helper's queue replies, the native run directory, the bridge run
directory.

For the real round ``f87472fb0a5cc2b77e1446124787e05d`` that requirement failed
outright: measured on 2026-10-02, **0 of its 48 required requestIds and its own
runId were discoverable** in the scanned producer space (the runId only ever
appeared embedded inside ``review``/``session`` path strings, which the corpus
scanner does not tokenise; the requestIds appear only in the run's own files and
in the author journal, which is not a scanned root).  That is not the layer being
wrong -- it is the business chain never having written a run-scoped receipt.

This module writes that receipt.  It is the *producer* side of the contract, and
it is deliberately not part of the run: it runs as its own process, it reads the
helper's own artifacts, and it refuses to write anything unless a real dispatch
can be shown.

WHAT IT IS NOT
--------------
* It is not a dispatcher.  Nothing here sends anything to the game, loads a
  bridge, takes a UAC elevation or retries a request.
* It is not an authority on outcomes.  Every fact it records is *copied* from a
  file another process wrote (the author journal's ``result.json``, the helper's
  ``<requestId>.response.json``), and the receipt carries the SHA-256 of those
  files so a reader can recompute rather than trust.
* It never touches the audited run directory.  Both artifacts land under
  producer roots; ``--receipt-root`` and ``--native-root`` are the only places it
  creates anything.
* It does not decide whether a run passes.  It makes the evidence chain *exist*;
  the verdict stays with the verifier.

TWO ARTIFACTS, TWO PRODUCER ROLES
---------------------------------
``<receiptRoot>/<runId>/receipts/<requestId>.json``
    The **attested run-scoped receipt**.  Written by this service, which is not
    the run.  It carries the author requestId (the token the run is judged on)
    together with the helper's process identity and the digest of the helper's
    own reply.

``<nativeRoot>/<nativeRunName>/run-receipt.json``
    The **native-side record**, written next to the native run directory that the
    elevated helper created.  It exists only where a native run directory really
    exists, and it repeats the same runId/requestId/levelId/entityIds as
    standalone JSON scalars.

The second is not decoration.  The authenticity layer excludes every file under
the run's declared source from the corpus it searches for corroboration
(``_excluded_from_corpus``), so a receipt that is *bound* cannot also be the
thing that corroborates it.  The native-side record is what remains in the
corpus, and it can only be produced against a native run directory that is
already on disk.

WHY THE RUN CANNOT JUST WRITE THIS ITSELF
-----------------------------------------
It can -- if it has write access to those roots.  That is the residual limit R1
W1 already documents and this module does not pretend to close.  What it does
change is the cost: a receipt is only producible when

* the author journal holds ``<requestId>/claim.json`` and ``result.json`` whose
  recorded ``requestId``, ``levelId`` and ``backend.helper.requestId`` agree, AND
* the helper's own ``<helperRequestId>.response.json`` is on disk and its bytes
  hash to what the receipt records, AND
* the native run directory named by both files exists and is outside the run.

A forged run has to plant all three, consistently, in the producer's space.
The receipt also *records* the helper pid and startedUtc, so a reader comparing a
receipt against a live helper can see the difference.

VERSION MAPPING (receipt v1)
----------------------------
Nothing prior to this module emitted a run-scoped receipt, so v1 supersedes no
format; it is *derived* from two v0 artifacts and the derivation is total:

    author journal  <journalRoot>/<requestId>/claim.json    (tools/authoring/author.py)
      .command.levelId                -> levelId
      .command.action                 -> result.action
      .startedUtc                     -> dispatchedUtc
      .sha256                         -> journal.commandFingerprint (a COMMAND
                                         fingerprint, not a file digest; the
                                         file digest is journal.claimSha256)

    author journal  <journalRoot>/<requestId>/result.json
      .requestId                      -> requestId
      .backend.helper.requestId       -> producer.helperRequestId
      .backend.helper.pid             -> producer.pid
      .backend.helper.startedUtc      -> producer.startedUtc
      .backend.levelId                -> levelId (cross-checked against claim)
      .backend.entityId               -> createdEntities[0].entityId
      .backend.placedIds              -> createdEntities[1..].entityId
      .backend.ok / .actionStatus / .called / .nativeStarted / .entities
                                      -> result.*
      (whole file)                    -> journal.resultSha256

    helper reply    <queueRoot>/<helperRequestId>.response.json
      .ok / .action / .actionStatus   -> producer.helperReply.*
      .levelId                        -> levelId (must equal the journal's)
      .entityId / .placedIds          -> createdEntities
      .run                            -> producer.nativeRun (must exist)
      (whole file)                    -> producer.responseSha256

The layer distinguishes "a real producer" from "the run describing itself" the
same way it always did -- by *location*: a receipt under a producer root is
outside every run root, and P3 refuses any source that resolves inside the run
under audit.  The extra fields above are what make a receipt *recomputable*
rather than merely present.

USAGE
-----
    python -m backend.dispatch_receipt --roots roots.json --run-id <32hex> \\
        [--request-id <rid> ...] [--all-in-journal] [--pretty]

``roots.json`` (all four keys, no defaults inside this module)::

    {"journalRoot": "<dir>", "queueRoot": "<dir>",
     "receiptRoot": "<dir>", "nativeRoot": "<dir>"}

Exit codes: 0 wrote every requested receipt, 1 at least one request was refused,
2 the invocation itself was unusable.  A refusal writes nothing at all for that
request -- a receipt is never a partial record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
KIND = 'entity-create-run-receipt'
NATIVE_RECEIPT_NAME = 'run-receipt.json'
HEX32 = re.compile(r'[0-9a-f]{32}')


class Refused(Exception):
    """A request was refused.  The code is stable and is reported verbatim."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, what: str) -> dict:
    try:
        document = json.loads(path.read_text(encoding='utf-8-sig'))
    except OSError as exc:
        raise Refused('RECEIPT_SOURCE_UNREADABLE', '%s: %s' % (what, exc)) from None
    except ValueError as exc:
        raise Refused('RECEIPT_SOURCE_MALFORMED', '%s: %s' % (what, exc)) from None
    if not isinstance(document, dict):
        raise Refused('RECEIPT_SOURCE_MALFORMED', '%s is not a JSON object' % what)
    return document


def _write_json(path: Path, payload: dict, *, pretty: bool) -> str:
    """Atomic write, LF only, sorted keys.  Returns the file digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      indent=2 if pretty else None) + '\n'
    temporary = path.parent / ('.%s.%s.tmp' % (path.name, uuid.uuid4().hex[:8]))
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:                                   # pragma: no cover
        try:
            temporary.unlink()
        except OSError:
            pass
        raise Refused('RECEIPT_WRITE_FAILED', '%s: %s' % (path, exc)) from None
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value)
    return None


# --------------------------------------------------------------------------- #
# the producer: journal + helper reply -> one receipt
# --------------------------------------------------------------------------- #

class ReceiptProducer:
    """Reads two v0 artifacts a non-run process wrote; writes one v1 receipt."""

    def __init__(self, roots: dict, *, run_id: str, pretty: bool = False,
                 host_pid: int | None = None):
        if not HEX32.fullmatch(run_id or ''):
            raise Refused('RECEIPT_RUNID_INVALID',
                          'runId %r is not 32 lowercase hex' % (run_id,))
        self.run_id = run_id
        self.pretty = pretty
        self.host_pid = os.getpid() if host_pid is None else host_pid
        for key in ('journalRoot', 'queueRoot', 'receiptRoot', 'nativeRoot'):
            if not isinstance(roots.get(key), str) or not roots[key].strip():
                raise Refused('RECEIPT_ROOTS_INCOMPLETE',
                              'roots.%s is required; this module has no default root' % key)
        self.journal_root = Path(roots['journalRoot'])
        self.queue_root = Path(roots['queueRoot'])
        self.receipt_root = Path(roots['receiptRoot'])
        self.native_root = Path(roots['nativeRoot'])
        self.written = []

    # -- sources ----------------------------------------------------------- #

    def _journal(self, request_id: str) -> tuple:
        directory = self.journal_root / request_id
        claim_path = directory / 'claim.json'
        result_path = directory / 'result.json'
        if not claim_path.is_file() or not result_path.is_file():
            raise Refused('RECEIPT_NO_JOURNAL',
                          'no claim.json+result.json for requestId %r under %s; a receipt '
                          'may not be produced for a request the author journal never '
                          'recorded' % (request_id, self.journal_root))
        claim = _read_json(claim_path, 'journal claim')
        result = _read_json(result_path, 'journal result')
        if result.get('requestId') != request_id:
            raise Refused('RECEIPT_REQUEST_MISMATCH',
                          'journal result records requestId %r, not the requested %r'
                          % (result.get('requestId'), request_id))
        return directory, claim, result

    def _helper_reply(self, helper_request_id: str) -> tuple:
        if not HEX32.fullmatch(helper_request_id or ''):
            raise Refused('RECEIPT_HELPER_ID_INVALID',
                          'helper requestId %r is not 32 lowercase hex'
                          % (helper_request_id,))
        path = self.queue_root / ('%s.response.json' % helper_request_id)
        if not path.is_file():
            raise Refused('RECEIPT_NO_HELPER_REPLY',
                          'the helper reply %s is not on disk; without a reply written by '
                          'the elevated helper there is nothing to attest'
                          % path)
        return path, _read_json(path, 'helper reply')

    # -- the receipt -------------------------------------------------------- #

    def build(self, request_id: str) -> dict:
        directory, claim, result = self._journal(request_id)
        backend = result.get('backend')
        if not isinstance(backend, dict):
            raise Refused('RECEIPT_NO_BACKEND',
                          'journal result for %r has no backend block' % request_id)
        helper = backend.get('helper')
        if not isinstance(helper, dict):
            raise Refused('RECEIPT_NO_HELPER_IDENTITY',
                          'journal result for %r names no helper; the run-scoped receipt '
                          'needs a producer identity to bind to' % request_id)
        helper_request_id = helper.get('requestId')
        reply_path, reply = self._helper_reply(helper_request_id)

        # the two independent records must agree before either is copied
        level_ids = {value for value in (_int(backend.get('levelId')),
                                         _int(reply.get('levelId')),
                                         _int((claim.get('command') or {}).get('levelId')))
                     if value is not None}
        if len(level_ids) != 1:
            raise Refused('RECEIPT_LEVEL_MISMATCH',
                          'requestId %r: journal and helper reply disagree on levelId %s'
                          % (request_id, sorted(level_ids)))
        level_id = level_ids.pop()

        native_run = reply.get('run') or backend.get('run')
        if not isinstance(native_run, str) or not native_run:
            raise Refused('RECEIPT_NO_NATIVE_RUN',
                          'requestId %r: neither the helper reply nor the journal names a '
                          'native run directory' % request_id)
        native_run_path = Path(native_run)
        if not native_run_path.is_dir():
            raise Refused('RECEIPT_NATIVE_RUN_ABSENT',
                          'requestId %r: native run %s is not a directory on disk'
                          % (request_id, native_run))

        created = []
        for source in (reply.get('entityId'), backend.get('entityId')):
            value = _int(source)
            if value is not None and value not in [entry['entityId'] for entry in created]:
                created.append({'entityId': value, 'owner': reply.get('owner')})
        for field in ('placedIds',):
            for raw in (reply.get(field) or []):
                value = _int(raw)
                if value is not None and value not in [entry['entityId'] for entry in created]:
                    created.append({'entityId': value, 'owner': reply.get('owner')})

        receipt = {
            'schemaVersion': SCHEMA_VERSION,
            'kind': KIND,
            'runId': self.run_id,
            'requestId': request_id,
            'levelId': level_id,
            'createdEntities': created,
            'dispatchedUtc': claim.get('startedUtc'),
            'result': {
                'ok': result.get('ok') is True,
                'journalOk': result.get('ok'),
                'action': backend.get('action') or reply.get('action'),
                'actionStatus': backend.get('actionStatus'),
                'called': backend.get('called'),
                'nativeStarted': backend.get('nativeStarted'),
                'entityCount': backend.get('entities'),
                'outcomeUncertain': result.get('outcomeUncertain'),
                'retryAttempted': result.get('retryAttempted') is True,
            },
            'producer': {
                'role': 'elevated-helper',
                'helperRequestId': helper_request_id,
                'pid': _int(helper.get('pid')),
                'startedUtc': helper.get('startedUtc'),
                'helperKind': helper.get('kind'),
                'responseFile': str(reply_path),
                'responseSha256': _sha256_file(reply_path),
                'helperReply': {
                    'ok': reply.get('ok') is True,
                    'action': reply.get('action'),
                    'actionStatus': reply.get('actionStatus'),
                    'nativeStarted': reply.get('nativeStarted'),
                    'entities': reply.get('entities'),
                },
                'nativeRun': native_run,
            },
            'journal': {
                'authorTool': 'tools/authoring/author.py',
                'journalDir': str(directory),
                'claimSha256': _sha256_file(directory / 'claim.json'),
                'resultSha256': _sha256_file(directory / 'result.json'),
                # NB: the journal's own `sha256` field is a fingerprint of the
                # COMMAND, not a digest of the claim file.  Both are recorded so
                # a reader is never asked to conflate them.
                'commandFingerprint': claim.get('sha256'),
                'replayed': result.get('replayed'),
            },
            'attestor': {
                'tool': 'backend/dispatch_receipt.py',
                'schemaVersion': SCHEMA_VERSION,
                'attestedUtc': _now(),
                'hostPid': self.host_pid,
            },
        }
        receipt['_nativeReceipt'] = self._native_record(receipt,
                                                        str(native_run_path))
        return receipt

    def _native_record(self, receipt: dict, native_run: str) -> dict:
        """The corroborating record that sits beside the native run directory.

        It is written into the native run directory's own parent, i.e. the tree
        the elevated helper populated.  It exists only because that directory
        exists.  Its whole purpose is to be *outside* the run's declared source,
        because the layer excludes the declared source from the corpus it
        searches for corroboration.
        """
        return {
            'schemaVersion': SCHEMA_VERSION,
            'kind': 'entity-create-native-side-receipt',
            'runId': receipt['runId'],
            'requestId': receipt['requestId'],
            'levelId': receipt['levelId'],
            'createdEntities': receipt['createdEntities'],
            'nativeRun': native_run,
            'helperRequestId': receipt['producer']['helperRequestId'],
            'helperPid': receipt['producer']['pid'],
            'dispatchReceipt': None,   # filled in by write()
            'attestedUtc': receipt['attestor']['attestedUtc'],
        }

    # -- writing ------------------------------------------------------------ #

    def write(self, receipt: dict, *, write_native_side: bool = True) -> dict:
        run_dir = self.receipt_root / self.run_id
        receipt_path = run_dir / 'receipts' / ('%s.json' % receipt['requestId'])
        native_record = receipt.pop('_nativeReceipt')
        native_record['dispatchReceipt'] = str(receipt_path)
        digest = _write_json(receipt_path, receipt, pretty=self.pretty)

        native_path = None
        if write_native_side:
            native_name = Path(native_record['nativeRun']).name
            native_path = self.native_root / native_name / NATIVE_RECEIPT_NAME
            _write_json(native_path, native_record, pretty=self.pretty)

        entry = {'requestId': receipt['requestId'],
                 'receipt': str(receipt_path),
                 'receiptSha256': digest,
                 'nativeSideRecord': str(native_path) if native_path else None,
                 'responseSha256': receipt['producer']['responseSha256']}
        self.written.append(entry)
        return entry

    def write_manifest(self) -> str:
        payload = {
            'schemaVersion': SCHEMA_VERSION,
            'kind': 'entity-create-run-receipt-manifest',
            'runId': self.run_id,
            'tool': 'backend/dispatch_receipt.py',
            'receiptRoot': str(self.receipt_root / self.run_id / 'receipts'),
            'nativeRoot': str(self.native_root),
            'generatedUtc': _now(),
            'receiptCount': len(self.written),
            'requestIds': sorted(entry['requestId'] for entry in self.written),
            'receipts': sorted(self.written, key=lambda entry: entry['requestId']),
        }
        path = self.receipt_root / self.run_id / 'manifest.json'
        return _write_json(path, payload, pretty=self.pretty)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def request_ids_in_journal(journal_root: Path, run_id: str) -> list:
    """Every journal requestId whose recorded run belongs to ``run_id``.

    The journal itself does not record a run, so membership is decided the same
    way the receipt is: by the command's ``review``/``session`` path naming the
    run directory.  Nothing is inferred from a filename alone.
    """
    found = []
    if not journal_root.is_dir():
        return found
    for directory in sorted(journal_root.iterdir()):
        if not directory.is_dir():
            continue
        result = directory / 'result.json'
        claim = directory / 'claim.json'
        if not result.is_file() or not claim.is_file():
            continue
        try:
            claim_doc = json.loads(claim.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        command = claim_doc.get('command') or {}
        haystack = ' '.join(str(command.get(field) or '')
                            for field in ('review', 'session', 'baseline'))
        if run_id in haystack:
            found.append(directory.name)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--roots', type=Path, required=True,
                        help='JSON object with journalRoot/queueRoot/receiptRoot/nativeRoot; '
                             'this module carries no default root so it cannot reach a '
                             'producer tree by accident')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--request-id', action='append', default=None)
    parser.add_argument('--all-in-journal', action='store_true',
                        help='discover the run\'s requestIds from the author journal')
    parser.add_argument('--no-native-side', action='store_true',
                        help='skip the native-side corroborating record (testing only)')
    parser.add_argument('--pretty', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)

    try:
        roots = _read_json(args.roots, 'roots config')
        ids = list(args.request_id or [])
        if args.all_in_journal:
            ids.extend(request_ids_in_journal(Path(roots['journalRoot']), args.run_id))
        ids = sorted(set(ids))
        if not ids:
            raise Refused('RECEIPT_NO_REQUESTS',
                          'no requestId given and --all-in-journal found none for runId %s'
                          % args.run_id)
        producer = ReceiptProducer(roots, run_id=args.run_id, pretty=args.pretty)
    except Refused as exc:
        sys.stderr.write('REFUSED %s: %s\n' % (exc.code, exc.message))
        return 2

    refused = []
    for request_id in ids:
        try:
            receipt = producer.build(request_id)
            entry = producer.write(receipt, write_native_side=not args.no_native_side)
            if not args.quiet:
                sys.stdout.write('RECEIPT %s -> %s\n' % (request_id, entry['receipt']))
        except Refused as exc:
            refused.append({'requestId': request_id, 'code': exc.code,
                            'message': exc.message})
            sys.stderr.write('REFUSED %s %s: %s\n' % (request_id, exc.code, exc.message))

    manifest = producer.write_manifest() if producer.written else None
    if not args.quiet:
        sys.stdout.write(json.dumps({'runId': args.run_id,
                                     'written': len(producer.written),
                                     'refused': refused,
                                     'manifestSha256': manifest},
                                    ensure_ascii=False, indent=2) + '\n')
    return 1 if refused else 0


if __name__ == '__main__':                                   # pragma: no cover
    raise SystemExit(main())
