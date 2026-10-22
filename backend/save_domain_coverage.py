#!/usr/bin/env python3
"""Per-object-domain native-save coverage and its independent receipt (D23.01.01).

LEAF D23.01.01 -- "各对象域生成真实保存请求和独立回执"

    basicBehavior  对 S1-S3 每个实际参与对象域发出原生保存并保留独立回执
    minimumSample  每个已使用域至少 1 对象，可合并一次关卡保存
    positiveCheck  请求ID关联真实保存回包，各域对象在落盘语义中存在；
                   无该域对象则该域不得通过

WHAT THE TREE ALREADY DID, AND WHAT IT DID NOT
----------------------------------------------
The save half was implemented and wired before this module: ``entity_server
.mw_scene_save_level`` (and ``author.py save``) issues ONE reviewed native level save --
which is what ``minimumSample`` permits -- binds the caller's ``requestId`` to a real
native reply, and builds a W08 manifest that ``backend.save_verification`` judges.

The per-DOMAIN half was the gap, and ``backend/entity_server.build_save_manifest`` says so
itself (:725-741): a plain ``saveLevel`` carries an EMPTY ``intent`` / ``entityDelta`` /
``declaredChangedRoots``, because "wiring a real declaration from the ledger is a follow-on,
not something to fake here".  Nothing in the tree said, for one save's ``requestId``, WHICH
object domains participated (an entity? a graph? an entity->graph binding?) nor whether each
one's objects are actually IN the bytes that save wrote.  The only per-domain saved-content
readback was ``tools/authoring/verify_saved.py`` -- a manual CLI with no product caller,
hard-wired to one entity and one two-node graph, whose own inventory row
(``tools/authoring/INTERFACE-INVENTORY.md:49``) is marked ``partial``.

WHAT THIS MODULE IS
-------------------
The missing contract, wired to the real save entry.  Given

  * the save's own native reply (``requestId``, ``nativeSaveStatus``, ``levelId``, the
    ``afterGils`` digests it recorded),
  * the participation roster S1-S3 declared (which domains produced objects, and which),
  * an INDEPENDENT on-disk readback of the bytes that save wrote -- the project-local copy
    of the just-written level file the W08 manifest already pins, read by
    ``tools/game-executor/read_saved_domains.py`` under the pinned content interpreter,

it decides, per domain, whether that domain may pass, and it writes that decision as its own
receipt (``domain-coverage.json``) beside the manifest, under the save's ``requestId``.

Verdict rules (each one is a positiveCheck clause, not an invention)
-------------------------------------------------------------------
* ``replyBound``          the reply names THIS ``requestId``, is ``ok``, records
                          ``nativeSaveStatus == 0`` and a ``levelId`` equal to the case's.
                          "请求ID关联真实保存回包".  If it does not hold, NO domain passes.
* ``readbackIndependent`` the readback names a source with a 64-hex sha256, and that source
                          is not the reply's own receipt file.  An independent receipt is
                          a different file from the reply.
* ``readbackHashesBound`` the digest the reply recorded for this level in ``afterGils``
                          equals the readback's digest.  This is what makes the readback
                          the bytes of THIS save rather than of some other run.
* per domain              ``not-participated`` when the roster declared no object
                          ("无该域对象则该域不得通过" -- such a domain NEVER passes);
                          ``unreadable`` when the tree has no saved-GIL reader for it
                          (component / resource -- also never a pass); ``pass`` only when
                          it declared at least one object AND every declared id is present
                          in the independent readback; otherwise ``fail`` naming the ids
                          that are missing.
* overall                 ``pass`` only when the reply gate is open, the readback is
                          independent and hash-bound, at least one domain participated, and
                          no participated domain failed or was unreadable.  Zero
                          participation is a FAIL, never a vacuous pass.
* an id declared by two domains at once is ambiguous ownership and fails the whole case.

WHAT IT DOES NOT DO
-------------------
It computes no truth about the game: it consumes a native reply and a readback and names
what they support.  Its offline verdict is NOT native evidence (frozen rules:
offlineMayCountAsNative=false, selfReportedPassIsEvidence=false).  It never writes outside
the caller-supplied ``out_dir`` and never opens the live account: the readback path is
checked against the ``BeyondLocal`` marker the same way ``save_verification`` refuses one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

try:
    from backend import content_interpreter_pin as content_pin
except ImportError:                                     # pragma: no cover - plain script
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        'content_interpreter_pin', Path(__file__).resolve().parent / 'content_interpreter_pin.py')
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    content_pin = _mod

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = 1
KIND = 'save-domain-coverage'
PRODUCER_ID = 'backend/save_domain_coverage.py'
LEAF_ID = 'D23.01.01'

#: The object domains, exactly as the leaf names them ("对象、图、组件和资源引用").  Kept as
#: a literal, in a fixed order, so a domain nobody declared is VISIBLE as not-participated
#: rather than silently absent.
OBJECT_DOMAINS = ('entity', 'graph', 'binding', 'component', 'resource')
#: The domains the tree can read back out of a saved GIL.  A domain outside this tuple has
#: no reader anywhere in the repository and is therefore never a pass.
READABLE_DOMAINS = ('entity', 'graph', 'binding')
UNREADABLE_DOMAINS = ('component', 'resource')

#: The read-only saved-GIL reader, run under the pinned content interpreter.
READER_REL = 'tools/game-executor/read_saved_domains.py'

#: Files under a receipt directory that are the REPLY itself and therefore cannot double as
#: the independent readback.
REPLY_FILE_NAMES = ('receipt.json', 'result.json')


class DomainCoverageError(ValueError):
    """A named refusal.  Raised before a receipt is written; never a silent skip."""

    def __init__(self, code, detail, **extra):
        super().__init__('%s: %s' % (code, detail))
        self.code, self.detail, self.extra = code, detail, extra

    def as_json(self):
        return {'code': self.code, 'detail': self.detail, **self.extra}


def _hex64(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in '0123456789abcdef' for c in value.lower())


# --------------------------------------------------------------------------- #
# participation roster
# --------------------------------------------------------------------------- #

def binding_key(pair):
    """One canonical binding id, identical to the reader's own derivation."""
    if isinstance(pair, str):
        return pair.strip()
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        return '%s->%s' % (int(pair[0]), int(pair[1]))
    raise DomainCoverageError('PARTICIPATION_INVALID',
                              'a binding must be "<entityId>-><graphId>" or a [entity, graph] '
                              'pair, not %r' % (pair,))


def _id_list(items, domain):
    if items is None:                                   # an undeclared domain is empty
        return []
    if isinstance(items, (str, bytes)) or not isinstance(items, (list, tuple)):
        raise DomainCoverageError('PARTICIPATION_INVALID',
                                  'declaredDomains.%s must be a list' % domain)
    seen, out = set(), []
    for item in items:
        key = binding_key(item) if domain == 'binding' else str(item)
        if not key:
            raise DomainCoverageError('PARTICIPATION_INVALID',
                                      'declaredDomains.%s carries an empty id' % domain)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def normalize_participation(declared) -> dict:
    """Validate a roster and return one canonical ``{domain: [id, ...]}`` for all domains.

    An unknown domain name is refused rather than dropped: a roster that names a domain
    this contract does not know would otherwise look like "that domain did not participate"
    -- the exact mis-read the leaf's negative rule forbids.
    """
    if declared is None:
        declared = {}
    if not isinstance(declared, dict):
        raise DomainCoverageError('PARTICIPATION_INVALID',
                                  'declaredDomains must be an object of domain -> [ids]')
    unknown = sorted(set(declared) - set(OBJECT_DOMAINS))
    if unknown:
        raise DomainCoverageError(
            'PARTICIPATION_UNKNOWN_DOMAIN',
            'declaredDomains names %s, which is not one of %s' % (unknown, list(OBJECT_DOMAINS)))
    return {domain: _id_list(declared.get(domain), domain) for domain in OBJECT_DOMAINS}


def ownership_conflicts(participation) -> list:
    """Object ids declared by more than one domain at once (ambiguous ownership)."""
    owner, conflicts = {}, []
    for domain in OBJECT_DOMAINS:
        for key in participation.get(domain, []):
            if key in owner and owner[key] != domain:
                conflicts.append({'id': key, 'domains': [owner[key], domain]})
            owner.setdefault(key, domain)
    return conflicts


# --------------------------------------------------------------------------- #
# the independent-readback reader (pinned subprocess)
# --------------------------------------------------------------------------- #

def _default_runner(argv, timeout):
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    return {'returncode': proc.returncode,
            'stdout': proc.stdout.decode('utf-8', 'replace'),
            'stderr': proc.stderr.decode('utf-8', 'replace')}


def _is_inside_live_account(path) -> bool:
    """Mirror of ``save_verification._is_inside_live_account`` -- never read the account."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    if 'BeyondLocal' in resolved.parts:
        return True
    try:
        return resolved.is_relative_to(Path.home() / 'AppData' / 'LocalLow' / 'miHoYo')
    except (OSError, ValueError):
        return False


def read_saved_domain_facts(gil_path, level_id, *, python=None, runner=None,
                            timeout=600) -> dict:
    """Run the read-only domain reader under the pinned content interpreter.

    The interpreter is PINNED, not guessed: ``content_interpreter_pin`` returns a path only
    when every recorded fact (path + sha256 + version + dependencies + decoder digest) still
    holds.  No pinned interpreter -> a named refusal, never a silent "no readback".
    """
    path = Path(gil_path)
    if not path.is_absolute():
        raise DomainCoverageError('READBACK_PATH_RELATIVE',
                                  'the readback path %r is not absolute' % (gil_path,))
    if _is_inside_live_account(path):
        raise DomainCoverageError('READBACK_PATH_IN_LIVE_ACCOUNT',
                                  '%s is inside the live game save directory; supply a copy' % path)
    if not path.is_file():
        raise DomainCoverageError('READBACK_MISSING', '%s is not on disk' % path)
    chosen = python or content_pin.resolved_interpreter(project_root=ROOT)
    if not chosen:
        raise DomainCoverageError(
            'READER_UNUSABLE',
            'no pinned content interpreter resolved (config/save-content-interpreter.lock.json); '
            'the saved bytes cannot be decoded here')
    reader = ROOT / READER_REL
    if not reader.is_file():
        raise DomainCoverageError('READER_MISSING', '%s is not on disk' % reader)
    result = (runner or _default_runner)(
        [chosen, '-B', str(reader), '--gil', str(path), '--level-id', str(int(level_id))], timeout)
    payload = None
    try:
        payload = json.loads(result.get('stdout') or '')
    except ValueError:
        payload = None
    if result.get('returncode') != 0 or not isinstance(payload, dict) or payload.get('ok') is not True:
        error = (payload or {}).get('error') or {}
        raise DomainCoverageError(
            'READBACK_FAILED',
            'the domain reader did not return a readback (rc=%r): %s'
            % (result.get('returncode'),
               error.get('detail') or (result.get('stderr') or result.get('stdout') or '')[-400:]),
            reader=str(reader))
    return payload


# --------------------------------------------------------------------------- #
# the verdict core (pure; drives no subprocess and writes nothing)
# --------------------------------------------------------------------------- #

def evaluate_save_domain_coverage(case) -> dict:
    """Judge one per-domain save-coverage case.  Never raises on a bad verdict.

    Raises :class:`DomainCoverageError` only when the case document itself is unusable, so
    an unusable input can never be read as a pass.
    """
    if not isinstance(case, dict):
        raise DomainCoverageError('CASE_NOT_AN_OBJECT', 'the case must be a JSON object')
    request_id = case.get('requestId')
    if not isinstance(request_id, str) or not request_id.strip():
        raise DomainCoverageError('REQUEST_ID_REQUIRED', 'requestId is required')
    level_id = case.get('levelId')
    if isinstance(level_id, bool) or not isinstance(level_id, int) or level_id <= 0:
        raise DomainCoverageError('LEVEL_ID_REQUIRED', 'levelId must be a positive integer')
    participation = normalize_participation(case.get('participated'))

    reply = case.get('saveReply')
    readback = case.get('savedReadback')
    reasons = []

    # --- the reply half: requestId bound to a real save reply ----------------- #
    reply_bound, reply_detail = _reply_bound(reply, request_id, level_id)
    if not reply_bound:
        reasons.append('saveReply: ' + reply_detail)

    # --- the readback half: independent file, same bytes the reply recorded --- #
    readback_ok, readback_detail = _readback_independent(readback, reply)
    if not readback_ok:
        reasons.append('savedReadback: ' + readback_detail)
    hashes_bound, bound_detail = _readback_hashes_bound(readback, reply, level_id)
    if not hashes_bound:
        reasons.append('savedReadback: ' + bound_detail)

    conflicts = ownership_conflicts(participation)
    if conflicts:
        reasons.append('ambiguous ownership (id declared by two domains): %s' % (conflicts,))

    gate_open = reply_bound and readback_ok and hashes_bound and not conflicts
    present = (readback or {}).get('present') if isinstance(readback, dict) else None
    present = present if isinstance(present, dict) else {}

    domains, passed, failed, not_participated, unreadable = {}, [], [], [], []
    for domain in OBJECT_DOMAINS:
        declared = list(participation.get(domain, []))
        observed = {str(x) for x in (present.get(domain) or [])}
        if not declared:
            domains[domain] = {
                'status': 'not-participated', 'participated': False,
                'declaredCount': 0, 'observedCount': len(observed), 'missingIds': [],
                'reason': 'S1-S3 declared no object in this domain; per positiveCheck a '
                          'domain with no object must not pass',
            }
            not_participated.append(domain)
            continue
        missing = [item for item in declared if item not in observed]
        if domain in UNREADABLE_DOMAINS:
            domains[domain] = {
                'status': 'unreadable', 'participated': True,
                'declaredCount': len(declared), 'observedCount': len(observed),
                'missingIds': missing,
                'reason': 'this tree carries no saved-GIL reader for the %r domain, so its '
                          'objects cannot be shown to exist on disk and the domain does not '
                          'pass' % domain,
            }
            unreadable.append(domain)
            continue
        if not gate_open:
            domains[domain] = {
                'status': 'fail', 'participated': True,
                'declaredCount': len(declared), 'observedCount': len(observed),
                'missingIds': missing,
                'reason': 'the save-reply / readback gate is closed; this domain cannot pass',
            }
            failed.append(domain)
            continue
        if missing:
            domains[domain] = {
                'status': 'fail', 'participated': True,
                'declaredCount': len(declared), 'observedCount': len(observed),
                'missingIds': missing,
                'reason': '%d declared object(s) are absent from the saved bytes; 无该域对象则'
                          '该域不得通过' % len(missing),
            }
            failed.append(domain)
            continue
        domains[domain] = {
            'status': 'pass', 'participated': True,
            'declaredCount': len(declared), 'observedCount': len(observed), 'missingIds': [],
            'reason': 'every declared object is present in the independent saved readback',
        }
        passed.append(domain)

    participated_any = any(domains[d]['participated'] for d in OBJECT_DOMAINS)
    if not participated_any:
        reasons.append('no domain participated in S1-S3; a save with no declared domain '
                       'object cannot pass this leaf')

    overall = 'pass' if (gate_open and passed and not failed and not unreadable
                         and participated_any) else 'fail'
    return {
        'ok': overall == 'pass',
        'leafId': LEAF_ID,
        'requestId': request_id,
        'levelId': level_id,
        'replyBound': reply_bound,
        'readbackIndependent': readback_ok,
        'readbackHashesBound': hashes_bound,
        'ownershipConflicts': conflicts,
        'domains': domains,
        'passedDomains': passed,
        'failedDomains': failed,
        'unreadableDomains': unreadable,
        'notParticipatedDomains': not_participated,
        'overall': overall,
        'reasons': reasons,
        'nativeRequired': True,
        'note': 'per-object-domain save-coverage verdict; it consumes a native save reply '
                'and an INDEPENDENT saved readback and does not itself constitute native '
                'evidence',
    }


def _reply_bound(reply, request_id, level_id):
    if not isinstance(reply, dict):
        return False, 'no saveReply object was supplied'
    if reply.get('requestId') != request_id:
        return False, 'the save reply names requestId %r, not %r' % (reply.get('requestId'), request_id)
    if reply.get('ok') is not True:
        return False, 'the save reply is not ok'
    action = reply.get('action')
    if action is not None and action != 'save':
        return False, 'the reply records action %r, not a save' % (action,)
    status = reply.get('nativeSaveStatus')
    if isinstance(status, bool) or status != 0:
        return False, 'nativeSaveStatus is %r, not 0' % (status,)
    observed = reply.get('levelId')
    if observed is not None and observed != level_id:
        return False, 'the save reply is about level %r, not %r' % (observed, level_id)
    return True, 'bound to requestId %s at level %s' % (request_id, level_id)


def _readback_independent(readback, reply):
    if not isinstance(readback, dict):
        return False, 'no savedReadback object was supplied'
    source = readback.get('sourcePath')
    if not isinstance(source, str) or not source.strip():
        return False, 'the readback names no source path'
    if not _hex64(readback.get('sha256')):
        return False, 'the readback carries no 64-hex sha256'
    source_name = Path(source).name.lower()
    if source_name in REPLY_FILE_NAMES:
        return False, 'the readback source %s has the name of a reply file; a readback must ' \
                      'not be the reply it is meant to be independent of' % source
    reply_source = (reply or {}).get('receiptPath')
    if isinstance(reply_source, str) and reply_source and \
            Path(reply_source).resolve() == Path(source).resolve():
        return False, 'the readback source IS the save reply (%s); it is not independent' % source
    return True, 'readback source %s is a file other than the reply' % source


def _readback_hashes_bound(readback, reply, level_id):
    """The reply's own recorded digest for this level must be the readback's digest."""
    if not isinstance(readback, dict) or not _hex64(readback.get('sha256')):
        return False, 'the readback carries no digest to bind'
    recorded = {}
    if isinstance(reply, dict):
        recorded = reply.get('afterGilSha256') or {}
    if not isinstance(recorded, dict):
        return False, 'the reply recorded the after-save digests in a shape this reader does ' \
                      'not know'
    expected = recorded.get(str(level_id))
    if expected is None:
        return False, ('the save reply recorded no after-save digest for level %s, so the '
                       'readback is not shown to be the bytes THIS save wrote' % level_id)
    if str(expected).lower() != str(readback['sha256']).lower():
        return False, ('the readback digest %s is not the digest the reply recorded for level '
                       '%s (%s)' % (readback['sha256'], level_id, expected))
    return True, 'the readback digest is the after-save digest the reply recorded for this level'


# --------------------------------------------------------------------------- #
# the producer -- assemble the case, judge it, and keep the receipt
# --------------------------------------------------------------------------- #

def _reply_view(sent, level_id, receipt_path):
    """Reduce the author/entity_server save reply to the coverage reply shape."""
    if not isinstance(sent, dict):
        raise DomainCoverageError('SAVE_REPLY_INVALID', 'the save reply must be an object')
    backend = sent.get('backend') if isinstance(sent.get('backend'), dict) else sent
    after = {}
    for side in ('afterGils',):
        recorded = backend.get(side)
        if isinstance(recorded, dict):
            for key, entry in recorded.items():
                if isinstance(entry, dict) and _hex64(entry.get('sha256')):
                    after[str(key)] = entry['sha256']
    return {
        'ok': sent.get('ok') is True,
        'requestId': sent.get('requestId'),
        'action': backend.get('action'),
        'levelId': backend.get('levelId'),
        'nativeSaveStatus': backend.get('nativeStatus'),
        'afterGilSha256': after,
        'receiptPath': str(receipt_path) if receipt_path else None,
    }


def build_save_domain_coverage(level_id, request_id, sent, readback, declared_domains, *,
                               receipt_path=None, out_dir=None, python=None, runner=None,
                               timeout=600, overwrite=False) -> dict:
    """Assemble one coverage case, read the saved bytes, judge it, and write the receipt.

    ``readback`` names the INDEPENDENT on-disk file: ``{'path', 'sha256'}`` -- the
    project-local copy of the just-written level file the W08 manifest pins.  The readback
    digest is re-hashed here, not trusted, so a manifest entry that has drifted is caught.

    The receipt is written to ``out_dir`` (default ``EVIDENCE_ROOT/<requestId>``) and its
    path is returned alongside the verdict.  Every refusal is a ``DomainCoverageError``; no
    partial receipt is written.
    """
    if not isinstance(request_id, str) or not request_id.strip():
        raise DomainCoverageError('REQUEST_ID_REQUIRED', 'requestId is required')
    if isinstance(level_id, bool) or not isinstance(level_id, int) or level_id <= 0:
        raise DomainCoverageError('LEVEL_ID_REQUIRED', 'levelId must be a positive integer')
    if not isinstance(readback, dict) or not isinstance(readback.get('path'), str):
        raise DomainCoverageError('READBACK_INVALID',
                                  'readback must be {"path": <abs path>, "sha256": <hex>}')
    source = Path(readback['path'])
    recorded = readback.get('sha256')
    blob_digest = None
    if source.is_file():
        blob_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if recorded and blob_digest and str(recorded).lower() != blob_digest:
        raise DomainCoverageError(
            'READBACK_DIGEST_DRIFT',
            'the readback file %s is %s, but %s was recorded for it -- the bytes moved under '
            'the manifest' % (source, blob_digest, recorded), path=str(source))

    facts = read_saved_domain_facts(source, level_id, python=python, runner=runner,
                                    timeout=timeout)
    if str(facts.get('sha256', '')).lower() != (blob_digest or '').lower():
        raise DomainCoverageError(
            'READBACK_CHANGED',
            'the readback changed between the manifest hash and the domain read (%s vs %s)'
            % (blob_digest, facts.get('sha256')), path=str(source))

    case = {
        'requestId': request_id,
        'levelId': level_id,
        'participated': normalize_participation(declared_domains),
        'saveReply': _reply_view(sent, level_id, receipt_path),
        'savedReadback': {
            'sourcePath': str(source),
            'sha256': facts['sha256'],
            'present': facts['domains'],
            'unreadableDomains': facts.get('unreadableDomains') or list(UNREADABLE_DOMAINS),
        },
    }
    verdict = evaluate_save_domain_coverage(case)
    document = {
        'kind': KIND,
        'schemaVersion': SCHEMA_VERSION,
        'producer': PRODUCER_ID,
        'leafId': LEAF_ID,
        'levelId': level_id,
        'requestId': request_id,
        'case': case,
        'verdict': verdict,
        'readback': {'path': str(source), 'sha256': facts['sha256'],
                     'bytes': facts.get('bytes'), 'levelId': facts.get('levelId'),
                     'readers': facts.get('readers'), 'readerDetail': facts.get('detail')},
        'note': '每个实际参与对象域一票；该回执由 requestId 绑定，其读回文件独立于保存回包。'
                'This receipt is a claim about the SAME save the reply answers; it is not a '
                'second save and it never re-derives the native steps.',
    }
    written = None
    if out_dir is not None:
        directory = Path(out_dir)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'domain-coverage.json'
        if target.exists() and not overwrite:
            raise DomainCoverageError('REFUSING_TO_OVERWRITE',
                                      '%s already exists; a coverage receipt is never '
                                      'overwritten' % target, path=str(target))
        with target.open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
        written = str(target)
    return {'coveragePath': written, 'coverage': document, 'verdict': verdict,
            'overall': verdict['overall']}


# --------------------------------------------------------------------------- #
# CLI -- offline cross-check of a case, or a direct readback
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--case', type=Path, help='a coverage case JSON to judge offline')
    parser.add_argument('--readback', type=Path, help='a saved GIL to read back directly')
    parser.add_argument('--level-id', type=int, help='required with --readback')
    parser.add_argument('--pretty', action='store_true')
    args = parser.parse_args(argv)
    indent = 2 if args.pretty else None
    if args.case is not None:
        try:
            verdict = evaluate_save_domain_coverage(json.loads(args.case.read_text('utf-8')))
        except (OSError, ValueError, DomainCoverageError) as exc:
            sys.stderr.write('CASE_UNUSABLE: %s\n' % exc)
            return 3
    elif args.readback is not None:
        if args.level_id is None:
            parser.error('--readback requires --level-id')
        try:
            verdict = read_saved_domain_facts(args.readback, args.level_id)
        except DomainCoverageError as exc:
            sys.stderr.write('READBACK_REFUSED: %s\n' % exc)
            return 3
    else:
        parser.error('one of --case or --readback is required')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.stdout.write(json.dumps(verdict, ensure_ascii=False, indent=indent) + '\n')
    return 0 if verdict.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
