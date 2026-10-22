"""Recompute a run-scoped receipt from the producer artifacts it cites.

``verify_run_provenance.py`` answers "does an artifact outside the run mention
these tokens".  That is a question about *existence*, and it deliberately does not
parse the receipt -- so it cannot tell a receipt the producer wrote from a
receipt shaped like one.  This tool answers the second question: **is this
receipt reproducible from files another process actually wrote?**

It is read-only.  For each receipt it recomputes, from disk:

* ``journal.claimSha256`` / ``journal.resultSha256`` against the journal files,
* the journal ``result.json``'s own ``requestId`` and ``levelId`` against the
  receipt's, and the journal's recorded native run against ``producer.nativeRun``,
* ``producer.responseSha256`` against the elevated helper's reply at
  ``producer.responseFile``, and that reply's ``requestId`` / ``levelId`` /
  ``run`` against the receipt's ``producer`` block and ``runId``,
* that the runId recorded in the receipt matches the run directory the receipts
  are filed under,
* that both cited paths really sit inside the declared producer roots (a receipt
  pointing at the run under audit is refused).

Codes
-----
    RECEIPT_OK
    RECEIPT_UNREADABLE            not JSON / not an object
    RECEIPT_KIND_INVALID          wrong schemaVersion or kind --
                                  parsing of that file STOPS here
    RECEIPT_SHAPE_INVALID         kind is right but a nested field that must be
                                  an object (journal / producer) is not one --
                                  parsing of that file STOPS here
    RECEIPT_RUNID_MISMATCH        receipt.runId != the run directory it is filed under
    RECEIPT_JOURNAL_HASH_MISMATCH journal.claimSha256 / journal.resultSha256 stale
    RECEIPT_JOURNAL_MISSING       the cited journal files are gone
    RECEIPT_JOURNAL_DISAGREES     journal requestId / levelId / run != receipt
    RECEIPT_RESPONSE_HASH_MISMATCH responseSha256 stale
    RECEIPT_RESPONSE_MISSING      the cited helper reply is gone
    RECEIPT_RESPONSE_DISAGREES    helper reply requestId / levelId / run != receipt
    RECEIPT_OUTSIDE_PRODUCER_ROOTS a cited path escapes the declared producer roots

    python verify_receipts.py --roots roots.json --receipts <dir> [--run-id <32hex>] [--quiet]

Exit codes: 0 every receipt reproduced, 1 at least one did not, 2 unusable input.

Why the two "STOPS here" codes matter
-------------------------------------
A directory that is not a receipt directory is a *usage* error, not a receipt
failure, and the two must not be confused.  ``--receipts`` pointed at a run root
or at an authoring request directory globs in JSON files that are not receipts;
before this change the checker walked straight past ``RECEIPT_KIND_INVALID``
into the rest of the parser and died with ``AttributeError: 'str' object has no
attribute 'get'`` on ``journal.get('journalDir')`` -- a traceback, an exit code
of 1 that is indistinguishable from a genuine stale receipt, and no structured
verdict at all.  Now a file that is not a receipt is refused as a file and the
parser moves on; the run as a whole still fails, but it fails *legibly*.

Nothing here is loosened.  Stopping early on a file that is not a receipt cannot
make a real receipt pass: a real receipt carries the right ``kind`` and the right
``schemaVersion`` or it is not one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SCHEMA_VERSION = 1
KIND = 'entity-create-run-receipt'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def within(child: Path, parent: Path) -> bool:
    child_text = os.path.normcase(str(child.resolve()))
    parent_text = os.path.normcase(str(parent.resolve()))
    return child_text == parent_text or child_text.startswith(parent_text.rstrip('\\/') + os.sep)


def load(path: Path):
    try:
        document = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def check_receipt(path: Path, roots: dict) -> dict:
    failures = []

    def fail(code, detail):
        failures.append({'code': code, 'detail': detail})

    receipt = load(path)
    if receipt is None:
        return {'receipt': str(path), 'ok': False,
                'failures': [{'code': 'RECEIPT_UNREADABLE',
                              'detail': 'not readable UTF-8 JSON object'}]}
    if receipt.get('schemaVersion') != SCHEMA_VERSION or receipt.get('kind') != KIND:
        # STOP here.  This file is not a receipt, so every other field below is
        # meaningless: continuing used to traceback as soon as ``journal`` or
        # ``producer`` happened to be a string instead of an object.  A file
        # that is not a receipt is refused as a file, and the caller gets a
        # structured verdict rather than an AttributeError.
        return {'receipt': str(path), 'requestId': receipt.get('requestId'),
                'runId': receipt.get('runId'), 'ok': False,
                'failures': [{'code': 'RECEIPT_KIND_INVALID',
                              'detail': 'schemaVersion=%r kind=%r (not a %s)'
                                        % (receipt.get('schemaVersion'),
                                           receipt.get('kind'), KIND)}]}

    # Defence in depth: the kind is right, but a nested field the parser treats
    # as an object is not one.  Refuse the file instead of crashing on .get().
    for field in ('journal', 'producer'):
        if field in receipt and receipt[field] is not None \
                and not isinstance(receipt[field], dict):
            fail('RECEIPT_SHAPE_INVALID',
                 '%s is %s, not an object' % (field, type(receipt[field]).__name__))
            return {'receipt': str(path), 'requestId': receipt.get('requestId'),
                    'runId': receipt.get('runId'), 'ok': False, 'failures': failures}

    # The producer (backend/dispatch_receipt.py:283-291) refuses to emit a
    # receipt at all unless exactly one non-null levelId could be gathered from
    # the journal, the helper reply and the claim -- so a receipt that does not
    # state its own levelId is not one this producer wrote, and every
    # levelId cross-check below would otherwise compare None against None and
    # pass.  Anchor it here.
    if not isinstance(receipt.get('levelId'), int) or isinstance(receipt.get('levelId'), bool):
        fail('RECEIPT_JOURNAL_DISAGREES',
             'receipt.levelId is %r; the producer states one or writes no receipt'
             % (receipt.get('levelId'),))

    # The same reasoning anchors requestId.  The producer
    # (backend/dispatch_receipt.py:247-250) refuses a request whose journal
    # result does not record the very requestId it was asked for, so a receipt
    # that states no requestId -- or an empty one -- is not one this producer
    # wrote, and the journal cross-check below would otherwise compare None
    # against None and pass.
    if not isinstance(receipt.get('requestId'), str) or not receipt.get('requestId'):
        fail('RECEIPT_JOURNAL_DISAGREES',
             'receipt.requestId is %r; the producer states one or writes no receipt'
             % (receipt.get('requestId'),))

    run_id = receipt.get('runId')
    if path.parent.parent.name != run_id:
        fail('RECEIPT_RUNID_MISMATCH',
             'receipt.runId %r != the run directory %r it is filed under'
             % (run_id, path.parent.parent.name))

    journal_root = Path(roots['journalRoot']).resolve()
    queue_root = Path(roots['queueRoot']).resolve()

    # -- the author journal ------------------------------------------------- #
    journal = receipt.get('journal') or {}
    directory = journal.get('journalDir')
    if not isinstance(directory, str) or not directory:
        fail('RECEIPT_JOURNAL_MISSING', 'journal.journalDir is absent')
    else:
        journal_dir = Path(directory)
        if not within(journal_dir, journal_root):
            fail('RECEIPT_OUTSIDE_PRODUCER_ROOTS',
                 'journal.journalDir %s is outside journalRoot %s'
                 % (journal_dir, journal_root))
        claim = journal_dir / 'claim.json'
        result = journal_dir / 'result.json'
        if not claim.is_file() or not result.is_file():
            fail('RECEIPT_JOURNAL_MISSING', '%s has no claim.json+result.json' % journal_dir)
        else:
            for name, key, cited in (('claim.json', 'claimSha256', journal.get('claimSha256')),
                                     ('result.json', 'resultSha256', journal.get('resultSha256'))):
                actual = sha256_file(journal_dir / name)
                if actual != cited:
                    fail('RECEIPT_JOURNAL_HASH_MISMATCH',
                         'journal.%s recorded %r, actual %s' % (key, cited, actual))
            result_doc = load(result) or {}
            if result_doc.get('requestId') != receipt.get('requestId'):
                fail('RECEIPT_JOURNAL_DISAGREES',
                     'journal result requestId %r != receipt requestId %r'
                     % (result_doc.get('requestId'), receipt.get('requestId')))
            backend = result_doc.get('backend')
            backend = backend if isinstance(backend, dict) else {}
            # Strict: the journal is cited as the source of the level and the
            # native run.  A journal that is silent about either is a journal
            # this receipt cannot be reproduced from, so silence fails rather
            # than skipping the comparison.  (With no `backend` object at all
            # both values read None and both checks fire.)
            if backend.get('levelId') != receipt.get('levelId'):
                fail('RECEIPT_JOURNAL_DISAGREES',
                     'journal levelId %r != receipt levelId %r'
                     % (backend.get('levelId'), receipt.get('levelId')))
            if backend.get('run') != (receipt.get('producer') or {}).get('nativeRun'):
                fail('RECEIPT_JOURNAL_DISAGREES',
                     'journal native run %r != producer.nativeRun %r'
                     % (backend.get('run'), (receipt.get('producer') or {}).get('nativeRun')))

    # -- the elevated helper's own reply ------------------------------------ #
    producer = receipt.get('producer') or {}
    response_file = producer.get('responseFile')
    if not isinstance(response_file, str) or not response_file:
        fail('RECEIPT_RESPONSE_MISSING', 'producer.responseFile is absent')
    else:
        reply_path = Path(response_file)
        if not within(reply_path, queue_root):
            fail('RECEIPT_OUTSIDE_PRODUCER_ROOTS',
                 'producer.responseFile %s is outside queueRoot %s'
                 % (reply_path, queue_root))
        if not reply_path.is_file():
            fail('RECEIPT_RESPONSE_MISSING', '%s is not on disk' % reply_path)
        else:
            actual = sha256_file(reply_path)
            if actual != producer.get('responseSha256'):
                fail('RECEIPT_RESPONSE_HASH_MISMATCH',
                     'producer.responseSha256 recorded %r, actual %s'
                     % (producer.get('responseSha256'), actual))
            reply = load(reply_path) or {}
            if reply_path.name != '%s.response.json' % producer.get('helperRequestId'):
                fail('RECEIPT_RESPONSE_DISAGREES',
                     'the reply file %s does not carry the helper requestId %r'
                     % (reply_path.name, producer.get('helperRequestId')))
            # Strict, for the same reason as the journal side: the helper reply
            # is the second independent record the producer reconciled, and an
            # unreadable or silent reply must not read as agreement.
            if reply.get('levelId') != receipt.get('levelId'):
                fail('RECEIPT_RESPONSE_DISAGREES',
                     'helper reply levelId %r != receipt levelId %r'
                     % (reply.get('levelId'), receipt.get('levelId')))
            if reply.get('run') != producer.get('nativeRun'):
                fail('RECEIPT_RESPONSE_DISAGREES',
                     'helper reply run %r != producer.nativeRun %r'
                     % (reply.get('run'), producer.get('nativeRun')))

    native = producer.get('nativeRun')
    if not isinstance(native, str) or not Path(native).is_dir():
        fail('RECEIPT_JOURNAL_DISAGREES',
             'producer.nativeRun %r is not a directory on disk' % (native,))

    return {'receipt': str(path), 'requestId': receipt.get('requestId'),
            'runId': run_id, 'ok': not failures, 'failures': failures}


def resolve_receipts_dir(receipts: Path, run_id: str | None) -> tuple[Path, str]:
    """Return the directory the receipts live in, plus how it was chosen.

    Two accepted shapes, and no others:

    * ``--receipts <runs-root> --run-id <id>``  -> ``<runs-root>/<id>/receipts``
    * ``--receipts <...>/<id>/receipts``       -> used as given

    The second shape is what the real tree looks like
    (``.runtime/editor-bridge/runs/<runId>/receipts/*.json``), so a caller who
    already holds the concrete directory does not have to move anything to be
    audit-able.
    """
    if run_id:
        return receipts / run_id / 'receipts', 'run-id'
    return receipts, 'path'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--roots', type=Path, required=True)
    parser.add_argument('--receipts', type=Path, required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)

    if not args.roots.is_file():
        sys.stderr.write('unusable: no roots config at %s\n' % args.roots)
        return 2
    roots = load(args.roots)
    if roots is None:
        sys.stderr.write('unusable: roots config is not a JSON object\n')
        return 2

    base, how = resolve_receipts_dir(args.receipts, args.run_id)
    if not base.is_dir():
        if args.run_id:
            sys.stderr.write('unusable: no run directory for --run-id %s '
                             '(looked for %s)\n' % (args.run_id, base))
        else:
            sys.stderr.write('unusable: %s is not a directory; pass the '
                             'receipts/ directory itself, or pass its parent '
                             'with --run-id\n' % base)
        return 2
    paths = sorted(base.glob('*.json'))
    if not paths:
        sys.stderr.write('unusable: %s is a directory but holds no *.json '
                         'receipts -- refusing (an empty receipts directory is '
                         'not a passing run).  Pass the receipts/ directory '
                         'itself, or its parent with --run-id.\n' % base)
        return 2

    rows = [check_receipt(path, roots) for path in paths]
    bad = [row for row in rows if not row['ok']]
    for row in bad if not args.quiet else []:
        for failure in row['failures']:
            sys.stdout.write('FAIL %s %s: %s\n'
                             % (row.get('requestId'), failure['code'], failure['detail']))
    sys.stdout.write(json.dumps({'receipts': len(rows), 'ok': len(rows) - len(bad),
                                 'failed': len(bad),
                                 'receiptsDir': str(base),
                                 'receiptsDirResolvedBy': how,
                                 'runId': args.run_id,
                                 'failures': [{'requestId': row.get('requestId'),
                                               'codes': [f['code'] for f in row['failures']]}
                                              for row in bad]},
                                ensure_ascii=False, indent=2) + '\n')
    return 1 if bad else 0


if __name__ == '__main__':                                   # pragma: no cover
    raise SystemExit(main())
