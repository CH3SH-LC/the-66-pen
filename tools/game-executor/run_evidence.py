#!/usr/bin/env python3
"""Producer for the run's own save+reopen evidence (the P15 entry gate's source).

WHY THIS FILE EXISTS
--------------------
``tools/entity-create/run_parameter_matrix.py`` grew a CASE-ENTRY gate
(``precondition_gate`` / ``_has_save_and_reopen_evidence``, :2258-2370) that decides
whether P15 -- the ownership-bounded cleanup -- may be ENTERED at all.  The token the
gate enforces is P15's own declared precondition

    "save-and-reopen-evidence-exists-first"

and the document it reads is ``<run root>/run-evidence.json``.  That driver's own
comment says the quiet part out loud (:2338-2339):

    "Wiring a real producer (a verified save plus an accepted reopen) is the
     mainline's call, not something this gate can manufacture."

Until this module, NOBODY produced that file.  The only writer in the tree was a test
fixture writing ``{"save": True, "reopen": True}`` by hand -- two booleans, typed.  A
gate that reads hand-typed booleans is not a gate: P15's whole point is that the sample
being deleted must ALREADY have its own persistence and reopen proof, and "somebody
typed true" is exactly the assertion that must not satisfy it.

This module is that producer.  It is a MEASURING INSTRUMENT, not an author (the same
posture as ``tools/entity-create/write_run_provenance_input.py``):

* ``save`` is derived ONLY from this run's own save originals -- the per-case
  ``save-receipt.json`` a real native save wrote, bound to a create this run's own
  ``raw-call.json`` recorded, and required to name THIS run, THIS level and to have
  actually moved THIS level's formal file.
* ``reopen`` is derived ONLY from a reopen acceptance original
  (``native_reopen_acceptance.py``'s ``reopen-acceptance.json``) whose own
  ``businessVerified``/``reopenRoundtripVerified`` are true, whose level matches, and which
  is BOUND to its sibling ``reopen-dispatch.json`` by ``dispatchSha256`` -- so a stale
  acceptance minted for an earlier dispatch cannot set ``reopen`` true.
* when no reopen original exists -- which is today's state: the reopen is C4-blocked on
  a user action -- the document is written with ``"reopen": false`` and a named
  ``reopenRefusal``.  The gate therefore stays BLOCKED.  There is no code path here that
  writes ``"reopen": true`` without having read an accepted reopen original off the disk.

Every original's bytes are hashed into the document, and the document carries a
``digest`` over its own core.  ``verify_document()`` re-reads the originals and re-checks
every hash, so an edit to a boolean, a swapped level id or a doctored receipt is
detected rather than believed.

WHERE THE FILE GOES (and why the producer refuses to write anywhere else)
----------------------------------------------------------------------
The consumer DERIVES the path: ``run_parameter_matrix.run_evidence_from(out_root)`` is
``Path(out_root) / "run-evidence.json"``.  A producer that wrote anywhere else would be
writing evidence the gate can never read -- the same failure mode
``tools/game-executor/round_materials.py`` documents for the MCP cleanup directory.  So
``--out``'s parent must BE the run root, or the write is refused with
``OUTPUT_DIRECTORY_MISMATCH``.

THE ROUND MATERIALS LEG (why this file also names the MCP directory)
------------------------------------------------------------------
P15's cleanup is the MCP route ``mw_scene_cleanup_owned`` (``backend/entity_server.py``
:1065-1070), which does not search for its materials: it derives

    EVIDENCE_ROOT / 'cleanup' / _cleanup_round_id(createdByRequestIds)
                  / 'round-materials.json'

with ``EVIDENCE_ROOT = <repo>/.runtime/game-executor/mcp-business``.  The derivation is
therefore published into the run-evidence document, and it is computed by CALLING
``round_materials.round_id_digest`` -- the producer's own function, the one a test
already asserts identical to the consumer's.  The document records, for the round its
samples form, ``roundRequestIds`` / ``roundIdDigest`` / ``mcpDirectory`` /
``materialsPath``, so the caller knows exactly which ids to hand ``createdByRequestIds``
and exactly which directory the route will look in.  Deriving that name a second time by
hand would be a third copy of a security-relevant function; this module refuses rather
than guess.

THE W08 SAVE-MANIFEST LEG (R09: the save half is DS-05's judged artifact)
-----------------------------------------------------------------------
P15's precondition names a *save*.  Since W08, the save a run makes is DESCRIBED by a
manifest (``backend/save_manifest.py``) that the DS-05 verifier
(``backend/save_verification.py``) actually judges -- not by a bare native receipt.  A
gate that reads the raw receipt while the judged artifact sits unread is reading the
wrong document, so the save leg now requires BOTH, cross-bound:

* the sample's own ``save-receipt.json`` must record a save of THIS level that moved it
  (W06's rule, unchanged), AND
* a W08 manifest (``--save-manifest``, or ``<attempt dir>/save-manifest.json``) must be
  about this run, this level, this request and this SAMPLE, every ``{path, sha256}`` it
  pins must still hash on disk, the receipt it pins must agree with its file hashes in
  both senses, and ``backend.save_manifest.producer_preflight`` (the producer's own,
  never a copy here) must be ``ok``.

A manifest that is simply NOT THERE is "no save evidence" -- ``save`` stays false and
the gate keeps P15 blocked.  A manifest that IS there and contradicts the run (another
run / another level / another request / another entity / moved bytes) is a named refusal.

REFUSAL, NEVER A GUESS (the named refusals this module raises)
-----------------------------------------------------------
    RUN_ID_INVALID / LEVEL_ID_INVALID / RUN_ROOT_INVALID
    RUN_MISMATCH               a consumed original names a different run
    LEVEL_MISMATCH             a consumed original observed a different level
    REQUEST_NOT_OWNED_BY_RUN   a create in the run names a request the caller did not
    EXPECTED_REQUEST_NOT_IN_RUN a request the caller named has no create in the run
    SAVE_NOT_A_SAVE            the receipt records some other action
    SAVE_MANIFEST_NOT_A_SAVE               the manifest is not the DS-05 save shape
    SAVE_MANIFEST_NOT_ABOUT_SAMPLE         it declares another entity
    SAVE_MANIFEST_ORIGINAL_MISSING / SAVE_MANIFEST_ORIGINAL_CHANGED
    SAVE_MANIFEST_RECEIPT_MISBOUND         manifest and its receipt describe other bytes
    SAVE_MANIFEST_PATH_IN_LIVE_ACCOUNT     it pins the real account, not a copy
    SAVE_MANIFEST_PRODUCER_UNLOADABLE      backend/save_manifest.py cannot judge it
    (no refusal, save stays false) SAVE_MANIFEST_ABSENT /
                                   SAVE_MANIFEST_WITHOUT_A_SAVE /
                                   SAVE_MANIFEST_PREFLIGHT_FAILED
    SAVE_MANIFEST_UNREADABLE   the manifest exists but cannot be parsed
    REOPEN_EVIDENCE_UNAVAILABLE / REOPEN_EVIDENCE_NOT_ACCEPTED
    ROUND_MATERIALS_PRODUCER_UNLOADABLE / ROUND_DIGEST_MISMATCH
    OUTPUT_DIRECTORY_MISMATCH
    (verify mode) RUN_EVIDENCE_SHAPE_UNKNOWN / RUN_EVIDENCE_DIGEST_MISMATCH /
                  RUN_EVIDENCE_ORIGINAL_CHANGED / RUN_EVIDENCE_RUN_MISMATCH /
                  RUN_EVIDENCE_LEVEL_MISMATCH

This module never dispatches, never deletes and never touches the game, the editor, the
elevated helper or the queue.  It reads documents and writes one file inside a run root.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
KIND = "run-evidence"
PRODUCER_ID = "tools/game-executor/run_evidence.py"

#: The filename the gate derives: ``run_parameter_matrix.RUN_EVIDENCE_NAME``.
EVIDENCE_FILENAME = "run-evidence.json"

#: The per-case originals this producer reads.  Names, not paths the caller picks.
RAW_CALL_NAME = "raw-call.json"
CREATED_IDS_NAME = "created-ids.json"
SAVE_RECEIPT_NAME = "save-receipt.json"
SAVE_DIFF_NAME = "save-diff.json"

#: The W08 save-manifest (``backend/save_manifest.py``), dropped beside the attempt's
#: own originals by whatever wires the save.  This is the document the DS-05 verifier
#: (``backend/save_verification.py``) actually judges, so it -- not a bare receipt -- is
#: the save original P15's precondition must point at.
SAVE_MANIFEST_NAME = "save-manifest.json"

#: The save-manifest's own contract (``backend/save_manifest.py`` :423-427).
SAVE_MANIFEST_OPERATION = "save"

#: The marker that says a path points at the REAL game save directory.  Mirrors
#: ``backend/save_verification.py``'s ``_is_inside_live_account``: a manifest whose
#: files live in the live account is refused outright, because reading the live account
#: is the one thing this chain may never be talked into.
LIVE_ACCOUNT_MARKERS = ("beyondlocal", "locallow")

#: The MCP materials root, relative to the repository root.  Deliberately the same
#: directory ``backend/entity_server.py`` calls ``EVIDENCE_ROOT / 'cleanup'``
#: (``EVIDENCE_ROOT = ROOT/.runtime/game-executor/mcp-business``, :54).
MCP_CLEANUP_ROOT = ".runtime/game-executor/mcp-business/cleanup"
MATERIALS_FILENAME = "round-materials.json"

#: The reopen acceptance original's own contract
#: (``native_reopen_acceptance.py`` :659-666).
REOPEN_ACCEPTANCE_OPERATION = "level.reopen-current"

#: The dispatch original the acceptance must be bound to.  ``native_reopen_acceptance``
#: refuses any other location (its ``work_path``/``REOPEN_FIXED_INPUT`` check) and stamps
#: the acceptance's ``dispatchSha256`` from exactly this sibling, so a packet whose digest
#: disagrees with it is an old response packet, not evidence of this reopen.
REOPEN_DISPATCH_NAME = "reopen-dispatch.json"

#: The keys the digest covers.  Everything a reader would act on, and nothing else --
#: a note or a timestamp added later must not invalidate an already-issued document.
CORE_KEYS = ("kind", "schemaVersion", "runId", "levelId", "save", "reopen",
             "samples", "round", "reopenEvidence", "saveManifests")

#: Where ``round_materials.py`` lives, relative to this file.  Kept as a module-level
#: constant so a test can point the loader at another copy; the DEFAULT is the sibling
#: producer, i.e. the one the MCP route's directory contract belongs to.
ROUND_MATERIALS_PATH = Path(__file__).resolve().parent / "round_materials.py"

#: Where the W08 manifest producer lives, relative to this file: the producer half of
#: the DS-05 save contract, ``backend/save_manifest.py``.  Same by-path loading rule as
#: ``round_materials.py`` above -- the save half is judged by ITS producer's own
#: preflight, never by a second copy of it written here.  Missing/unloadable is a named
#: refusal, not a silent "no manifest": without the producer, a manifest cannot be shown
#: to be the DS-05 shape at all.
SAVE_MANIFEST_PRODUCER_PATH = (Path(__file__).resolve().parents[2]
                               / "backend" / "save_manifest.py")


class Refusal(Exception):
    """A named refusal.  The producer writes nothing when one of these is raised."""

    def __init__(self, code, detail, source=None):
        super().__init__("%s: %s" % (code, detail))
        self.code = code
        self.detail = detail
        self.source = str(source) if source is not None else None

    def as_json(self):
        return {"code": self.code, "detail": self.detail, "source": self.source}


# --------------------------------------------------------------------------- #
# primitives -- deliberately independent of backend/ and of the driver
# --------------------------------------------------------------------------- #

def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def as_uint(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= 0xFFFFFFFF else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip(), 10)
        except (TypeError, ValueError):
            return None
        return parsed if 0 < parsed <= 0xFFFFFFFF else None
    return None


def utc(value):
    """A tz-aware datetime, or None.  A naive stamp is NOT a time."""
    import datetime as _dt
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso(stamp):
    return None if stamp is None else \
        stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value) -> bytes:
    """One canonical byte form, shared by the digest and its verifier."""
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def core(document) -> dict:
    return {key: document.get(key) for key in CORE_KEYS}


def compute_digest(document) -> str:
    return hashlib.sha256(canonical(core(document))).hexdigest()


# --------------------------------------------------------------------------- #
# the round-materials leg: the producer's own directory derivation
# --------------------------------------------------------------------------- #

def load_round_materials(path=None):
    """Import ``round_materials.py`` by path, or raise a NAMED refusal.

    The cleanup directory's name is a security-relevant derivation the producer and the
    MCP consumer must agree on (``backend/tests/test_round_materials_round_id_consistency.py``).
    This module CALLS that function; it does not re-derive the name.
    """
    target = Path(path or ROUND_MATERIALS_PATH)
    if not target.is_file():
        raise Refusal("ROUND_MATERIALS_PRODUCER_UNLOADABLE",
                      "the round-materials producer %s is not on disk, so the MCP "
                      "cleanup directory this run's ids derive cannot be published "
                      "without re-deriving a security-relevant name by hand"
                      % target, target)
    name = "w06_round_materials"
    spec = importlib.util.spec_from_file_location(name, str(target))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as error:                          # noqa: BLE001
        sys.modules.pop(name, None)
        raise Refusal("ROUND_MATERIALS_PRODUCER_UNLOADABLE",
                      "%s could not be loaded: %s: %s"
                      % (target, type(error).__name__, error), target)
    if not hasattr(module, "round_id_digest"):
        raise Refusal("ROUND_MATERIALS_PRODUCER_UNLOADABLE",
                      "%s carries no round_id_digest" % target, target)
    return module


def round_projection(request_ids, repo_root, module=None):
    """The round's own cleanup coordinates, derived by ``round_materials`` itself."""
    ids = sorted(str(value) for value in request_ids)
    if not ids:
        return None
    module = module if module is not None else load_round_materials()
    digest = module.round_id_digest(ids)
    directory = Path(MCP_CLEANUP_ROOT) / digest
    return {
        "roundRequestIds": ids,
        "roundIdDigest": digest,
        "mcpCleanupRoot": MCP_CLEANUP_ROOT,
        "mcpDirectory": str((Path(repo_root) / directory) if repo_root else directory),
        "materialsPath": str((Path(repo_root) / directory / MATERIALS_FILENAME)
                             if repo_root else (directory / MATERIALS_FILENAME)),
        "derivedBy": "round_materials.round_id_digest (identical by construction to "
                     "backend/entity_server._cleanup_round_id)",
    }


# --------------------------------------------------------------------------- #
# readers -- one per original, each returning facts or raising a named refusal
# --------------------------------------------------------------------------- #

def read_case_creates(run_root, run_id, expected_requests):
    """Every create THIS run recorded under its own ``cases/`` tree.

    Returns ``(samples, excluded)`` in a stable order.  A create whose owning stage
    document names a different run refuses (``RUN_MISMATCH``) -- it is not this run's
    sample at all.  A create the caller did not DECLARE as one of this run's samples is
    dropped BY NAME into ``excluded`` rather than refused: a real run root holds every
    case's create (P00..P16), while the samples P15's precondition is about are the
    ones the caller names, so "the run created something else too" must not be a
    refusal.  A request the caller DID declare with no create behind it IS a refusal
    (``EXPECTED_REQUEST_NOT_IN_RUN``) -- that is the wrong-request direction.
    """
    cases_root = Path(run_root) / "cases"
    if not cases_root.is_dir():
        return [], []
    found = []
    excluded = []
    seen_requests = set()
    for case_dir in sorted(p for p in cases_root.iterdir() if p.is_dir()):
        for attempt_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
            raw_path = attempt_dir / RAW_CALL_NAME
            if not raw_path.is_file():
                continue
            try:
                raw = read_json(raw_path)
            except (OSError, json.JSONDecodeError) as error:
                raise Refusal("RUN_EVIDENCE_SHAPE_UNKNOWN",
                              "%s is unreadable: %s" % (raw_path, error), raw_path)
            if not isinstance(raw, dict):
                raise Refusal("RUN_EVIDENCE_SHAPE_UNKNOWN",
                              "%s is not an object" % raw_path, raw_path)
            observed_run = raw.get("runId")
            if observed_run != run_id:
                raise Refusal(
                    "RUN_MISMATCH",
                    "the create stage %s names run %r, but this run is %r; a create from "
                    "another run is not this run's sample"
                    % (raw_path, observed_run, run_id), raw_path)
            request_id = raw.get("requestId")
            if not isinstance(request_id, str) or not request_id.strip():
                raise Refusal("REQUEST_NOT_OWNED_BY_RUN",
                              "the create stage %s carries no requestId" % raw_path,
                              raw_path)
            request_id = request_id.strip()
            if expected_requests is not None and request_id not in expected_requests:
                excluded.append({
                    "caseId": str(raw.get("caseId") or case_dir.name),
                    "requestId": request_id,
                    "code": "SAMPLE_NOT_DECLARED",
                    "detail": ("the caller did not declare this create requestId as one "
                               "of the run's samples, so it is not part of this round"),
                    "source": str(raw_path),
                })
                continue
            seen_requests.add(request_id)
            found.append({
                "caseId": str(raw.get("caseId") or case_dir.name),
                "attempt": as_uint(raw.get("attempt")),
                "requestId": request_id,
                "entityId": as_uint(raw.get("entityId")),
                "templateId": as_uint(raw.get("templateId")),
                "dir": attempt_dir,
                "rawCall": {"path": str(raw_path), "sha256": sha256_file(raw_path)},
            })
    if expected_requests:
        missing = sorted(set(expected_requests) - seen_requests)
        if missing:
            raise Refusal(
                "EXPECTED_REQUEST_NOT_IN_RUN",
                "the caller declared %s as this run's own samples, but the run records "
                "no create under those requestIds; a sample that was never created here "
                "cannot be the sample this run's delete is bounded to"
                % ", ".join(missing))
    return found, excluded


def read_created_ids(attempt_dir, run_id):
    """The case's own create record, or None when the case never wrote one."""
    path = Path(attempt_dir) / CREATED_IDS_NAME
    if not path.is_file():
        return None
    try:
        record = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    observed_run = record.get("runId")
    if observed_run is not None and observed_run != run_id:
        raise Refusal("RUN_MISMATCH",
                      "%s names run %r, but this run is %r"
                      % (path, observed_run, run_id), path)
    return {"path": str(path), "sha256": sha256_file(path),
            "requestId": record.get("requestId"),
            "entityId": as_uint(record.get("entityId")),
            "recordedUtc": record.get("recordedUtc")}


def read_save_evidence(attempt_dir, level_id, sample):
    """Derive this sample's SAVE evidence from the run's own ``save-receipt.json``.

    Returns ``(facts | None, reason | None)``.  A save whose own backend names a
    DIFFERENT level is a hard refusal (``LEVEL_MISMATCH``): that receipt is not about
    this level, so it cannot stand behind a delete in this level.  A save that simply
    did not succeed is recorded as "no save evidence" -- the honest reading -- and is
    never upgraded to a yes.
    """
    path = Path(attempt_dir) / SAVE_RECEIPT_NAME
    if not path.is_file():
        return None, "no %s under %s" % (SAVE_RECEIPT_NAME, attempt_dir)
    try:
        document = read_json(path)
    except (OSError, json.JSONDecodeError) as error:
        return None, "%s is unreadable: %s" % (path, error)
    reply = document.get("reply") if isinstance(document, dict) else None
    backend = reply.get("backend") if isinstance(reply, dict) else None
    if not isinstance(backend, dict):
        return None, "%s carries no reply.backend" % path

    action = backend.get("action")
    if action is not None and action != "save":
        raise Refusal("SAVE_NOT_A_SAVE",
                      "%s records action %r, not a save" % (path, action), path)

    observed_level = as_uint(backend.get("levelId"))
    if observed_level is None:
        return None, "%s names no level, so it cannot be shown to be this level's" % path
    if observed_level != level_id:
        raise Refusal(
            "LEVEL_MISMATCH",
            "%s is the save of level %s, but this run is level %s; a save in another "
            "level is not evidence that this level persisted"
            % (path, observed_level, level_id), path)

    native_status = backend.get("nativeStatus")
    ok = backend.get("ok")
    gil_changed = backend.get("gilChanged")
    moved = None
    if isinstance(gil_changed, dict):
        moved = gil_changed.get(str(level_id))
    succeeded = (ok is True and native_status == 0 and moved is True)
    reason = None
    if not succeeded:
        reason = ("the native save did not persist this level's formal file "
                  "(ok=%r nativeStatus=%r gilChanged[%s]=%r)"
                  % (ok, native_status, level_id, moved))

    facts = {
        "path": str(path),
        "sha256": sha256_file(path),
        "action": action,
        "ok": bool(ok),
        "nativeStatus": native_status,
        "levelId": observed_level,
        "gilChangedThisLevel": moved if isinstance(moved, bool) else None,
        "saveRequestId": (reply.get("requestId")
                          if isinstance(reply.get("requestId"), str) else None),
        "run": backend.get("run"),
        "succeeded": bool(succeeded),
        "sampleRequestId": sample["requestId"],
        "sampleEntityId": sample["entityId"],
    }
    return facts, reason


def read_save_diff(attempt_dir):
    """The formal-file diff's own verdict, when the run wrote one. Informational."""
    path = Path(attempt_dir) / SAVE_DIFF_NAME
    if not path.is_file():
        return None
    try:
        document = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    return {"path": str(path), "sha256": sha256_file(path),
            "ok": document.get("ok"), "entityId": as_uint(document.get("entity_id")),
            "exactlyOneNewEntity": document.get("exactly_one_new_entity")}


# --------------------------------------------------------------------------- #
# the save leg's other half: the W08 save-manifest (DS-05's judged artifact)
# --------------------------------------------------------------------------- #

def manifest_entries(document, label="manifest"):
    """Every ``{path, sha256}`` entry the manifest pins, with a readable label.

    The DS-05 verifier reads a manifest by pulling bound ``{path, sha256}`` entries and
    re-hashing them (``_load_bound_bytes``); this walks the SAME shape so a manifest that
    has been edited under one of its files is caught here for the same reason.  An entry
    whose path is not a file, or whose bytes no longer hash to the recorded value, is a
    named refusal at the caller -- never a silent pass.
    """
    found = []

    def walk(node, trail):
        if isinstance(node, dict):
            path = node.get("path")
            digest = node.get("sha256")
            if isinstance(path, str) and isinstance(digest, str):
                found.append({"label": trail, "path": path, "sha256": digest.lower()})
                return
            for key, value in node.items():
                walk(value, "%s.%s" % (trail, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, "%s[%d]" % (trail, index))

    walk(document, label)
    return found


def load_save_manifest_producer(path=None):
    """(module | None, error | None): the W08 manifest producer, loaded by path.

    Mirror of ``load_round_materials``: the save-manifest's shape and its preflight belong
    to ``backend/save_manifest.py``, and this producer refuses to re-implement either.
    """
    target = Path(path or SAVE_MANIFEST_PRODUCER_PATH)
    if not target.is_file():
        return None, ("SAVE_MANIFEST_PRODUCER_UNLOADABLE: %s is not on disk, so a manifest "
                      "cannot be shown to be the DS-05 shape at all" % target)
    spec = importlib.util.spec_from_file_location("w06_save_manifest", str(target))
    if spec is None or spec.loader is None:
        return None, ("SAVE_MANIFEST_PRODUCER_UNLOADABLE: %s has no importable spec"
                      % target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as error:                          # noqa: BLE001
        sys.modules.pop(spec.name, None)
        return None, ("SAVE_MANIFEST_PRODUCER_UNLOADABLE: %s raised %s: %s"
                      % (target, type(error).__name__, error))
    for name in ("producer_preflight", "ALLOWED_ACCOUNT_FILES"):
        if not hasattr(module, name):
            return None, ("SAVE_MANIFEST_PRODUCER_UNLOADABLE: %s carries no %s"
                          % (target, name))
    return module, None


def _looks_live(path_text):
    lowered = str(path_text).replace("\\", "/").lower()
    return any(marker in lowered for marker in LIVE_ACCOUNT_MARKERS)


def read_save_manifest_evidence(manifest_path, level_id, sample, receipt_facts=None,
                                module=None, repo_root=None):
    """Derive one sample's SAVE evidence from the W08 manifest (and the receipt it pins).

    ``(facts | None, reason | None)``.  Registered like ``read_save_evidence``: a manifest
    that is simply NOT THERE is "no save evidence" (the honest reading, ``save`` stays
    false and P15 stays blocked); a manifest that IS there but is about another run,
    another level, another request, another sample, or whose pinned bytes have moved, is
    a HARD refusal -- a contradictory artifact must never be quietly ignored.

    Everything is checked in the two senses the DS-05 verifier checks it:

      IDENTITY   ``operation``/``levelId``/``requestId``/``runId``, and the manifest must
                 be about THIS sample (its entity delta or intent names the run's entity);
      CONTENT    every ``{path, sha256}`` the manifest pins is re-hashed on disk;
      RECEIPT    the pinned native receipt must itself record a save of THIS level with
                 ``nativeStatus == 0`` and ``gilChanged[level] is True``, and its
                 ``beforeGils/afterGils[level]`` hashes must be the manifest's file
                 hashes -- the same two-sense binding ``invocation.receiptHashesBound``
                 makes, so "swap in an old successful receipt" cannot pass;
      PREFLIGHT  ``backend.save_manifest.producer_preflight`` (the producer's own, never
                 a copy here) must report ``ok``.
    """
    target = Path(manifest_path)
    if not target.is_file():
        return None, ("SAVE_MANIFEST_ABSENT: %s is not on disk, so this sample has no "
                      "DS-05 save manifest to stand behind a delete" % target)
    try:
        document = read_json(target)
    except (OSError, json.JSONDecodeError) as error:
        return None, "SAVE_MANIFEST_UNREADABLE: %s: %s" % (target, error)
    if not isinstance(document, dict):
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s is not an object" % target, target)
    if document.get("schemaVersion") is None:
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s carries no schemaVersion, so it is not the DS-05 manifest shape"
                      % target, target)
    if document.get("operation") != SAVE_MANIFEST_OPERATION:
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s records operation %r, not %r"
                      % (target, document.get("operation"), SAVE_MANIFEST_OPERATION),
                      target)

    def _bad_entry(entry):
        """The live-account sense, checked before any bytes are read."""
        if _looks_live(entry["path"]):
            raise Refusal(
                "SAVE_MANIFEST_PATH_IN_LIVE_ACCOUNT",
                "%s pins %s at the LIVE game save directory (%s); a manifest must point "
                "at copies, so reading it would read the account itself"
                % (target, entry["label"], entry["path"]), target)

    entries = manifest_entries(document)
    if not entries:
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s pins no {path, sha256} entry, so it binds nothing" % target,
                      target)
    for entry in entries:
        _bad_entry(entry)

    observed_level = as_uint(document.get("levelId"))
    if observed_level is None:
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s names no levelId, so it cannot be shown to be this level's"
                      % target, target)
    if observed_level != level_id:
        raise Refusal(
            "LEVEL_MISMATCH",
            "%s is the save manifest of level %s, but this run is level %s; a manifest in "
            "another level is not evidence that this level persisted"
            % (target, observed_level, level_id), target)

    manifest_request = document.get("requestId")
    if not isinstance(manifest_request, str) or not manifest_request.strip():
        raise Refusal("REQUEST_NOT_OWNED_BY_RUN",
                      "%s names no requestId" % target, target)
    manifest_request = manifest_request.strip()

    receipt_reason = "no save receipt was read for this sample"
    receipt_run_id = None
    if receipt_facts is not None:
        if receipt_facts.get("succeeded") is not True:
            return None, ("SAVE_MANIFEST_WITHOUT_A_SAVE: the sample's own receipt did not "
                          "persist this level (%s), so its manifest cannot stand behind a "
                          "delete" % (receipt_facts.get("ok"),))
        run_text = receipt_facts.get("run")
        receipt_run_id = Path(str(run_text)).name if run_text else None
        sample_receipt_request = receipt_facts.get("saveRequestId")
        if sample_receipt_request and sample_receipt_request != manifest_request:
            raise Refusal(
                "REQUEST_NOT_OWNED_BY_RUN",
                "%s is the manifest of save request %s, but this sample's own save receipt "
                "answers %s; the manifest is not about the save this run made"
                % (target, manifest_request, sample_receipt_request), target)

    # RUN -- made symmetric with level and request above (main-line fix, round 134, from the
    # R09 independent review's counterexample A).  Both of those refuse when their identity
    # field is ABSENT; this one used to skip its comparison when the RECEIPT carried no run
    # (`if receipt_run_id is not None and ...`), so a manifest naming ANY run -- including a
    # run from an entirely different save invocation -- was accepted as soon as the sample's
    # receipt happened to omit `backend.run`.  A missing identity field is a refusal, never a
    # skipped check.  MEASURED: all 22 real receipts in this tree DO carry `backend.run`, so
    # this refusal cannot fire on honest data; it closes the fail-open only.
    observed_run = document.get("runId")
    if not isinstance(observed_run, str) or not observed_run.strip():
        raise Refusal(
            "SAVE_MANIFEST_NAMES_NO_RUN",
            "%s names no runId, so it cannot be shown to belong to the save invocation this "
            "sample's receipt answers" % target, target)
    observed_run = observed_run.strip()
    if receipt_run_id is None:
        raise Refusal(
            "SAVE_RECEIPT_NAMES_NO_RUN",
            "%s cannot be tied to this sample's save invocation: the sample's own receipt "
            "names no run (`backend.run` is absent), so nothing shows which save produced "
            "this manifest" % target, target)
    if observed_run != receipt_run_id:
        raise Refusal(
            "RUN_MISMATCH",
            "%s names run %r, but this sample's own save receipt names run %r; a manifest "
            "from another save invocation is not this run's sample"
            % (target, observed_run, receipt_run_id), target)

    # The manifest must be about THIS sample: the entity delta it declares (or its intent)
    # has to name the entity this run created under this request.
    sample_entity = sample.get("entityId")
    delta = document.get("entityDelta") if isinstance(document.get("entityDelta"), dict) \
        else {}
    intent = document.get("intent") if isinstance(document.get("intent"), dict) else {}
    named_entities = {as_uint(v) for v in (delta.get("addedIds") or [])}
    named_entities.add(as_uint(intent.get("entityId")))
    if sample_entity is not None and sample_entity not in named_entities:
        raise Refusal(
            "SAVE_MANIFEST_NOT_ABOUT_SAMPLE",
            "%s declares entityDelta.addedIds=%r and intent.entityId=%r, none of which is "
            "this sample's entityId %r; a save of another entity is not this sample's "
            "persistence proof"
            % (target, delta.get("addedIds"), intent.get("entityId"), sample_entity),
            target)

    # CONTENT: every pinned entry re-hashed, in the manifest's own shape.
    pinned = []
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_file():
            raise Refusal(
                "SAVE_MANIFEST_ORIGINAL_MISSING",
                "%s pins %s at %s, which is gone from disk; the manifest describes "
                "evidence that is no longer inspectable"
                % (target, entry["label"], path), target)
        live = sha256_file(path)
        if live != entry["sha256"]:
            raise Refusal(
                "SAVE_MANIFEST_ORIGINAL_CHANGED",
                "%s pins %s at %s with sha256 %s, but the file on disk hashes to %s; the "
                "manifest's own evidence moved under it"
                % (target, entry["label"], path, entry["sha256"], live), target)
        pinned.append(entry)

    # The manifest's own pinned receipt, and the two-sense binding to its file hashes.
    receipt_path = document.get("receiptPath")
    if not isinstance(receipt_path, dict) or not isinstance(receipt_path.get("path"), str):
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s pins no receiptPath, so the native invocation behind it cannot "
                      "be re-read" % target, target)
    try:
        receipt = read_json(receipt_path["path"])
    except (OSError, json.JSONDecodeError) as error:
        raise Refusal("SAVE_MANIFEST_ORIGINAL_MISSING",
                      "%s pins a receipt at %s which cannot be read: %s"
                      % (target, receipt_path["path"], error), target)
    backend = receipt.get("backend") if isinstance(receipt, dict) else None
    if not isinstance(backend, dict):
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s pins a receipt with no reply.backend" % target, target)
    if receipt.get("requestId") != manifest_request:
        raise Refusal(
            "REQUEST_NOT_OWNED_BY_RUN",
            "%s names request %s but its pinned receipt answers %s"
            % (target, manifest_request, receipt.get("requestId")), target)
    if backend.get("action") not in (None, SAVE_MANIFEST_OPERATION):
        raise Refusal("SAVE_MANIFEST_NOT_A_SAVE",
                      "%s pins a receipt recording action %r, not a save"
                      % (target, backend.get("action")), target)
    receipt_level = as_uint(backend.get("levelId"))
    if receipt_level != level_id:
        raise Refusal("LEVEL_MISMATCH",
                      "%s's pinned receipt is the save of level %r, but this run is level %s"
                      % (target, receipt_level, level_id), target)
    changed = backend.get("gilChanged") if isinstance(backend.get("gilChanged"), dict) \
        else {}
    native_ok = backend.get("nativeStatus") == 0 and changed.get(str(level_id)) is True
    if not native_ok:
        return None, ("SAVE_MANIFEST_WITHOUT_A_SAVE: the pinned receipt records "
                      "nativeStatus=%r gilChanged[%s]=%r, so this level's formal file did "
                      "not move under this save"
                      % (backend.get("nativeStatus"), level_id, changed.get(str(level_id))))

    files = document.get("files") if isinstance(document.get("files"), dict) else {}
    for key, side in (("gilBefore", "beforeGils"), ("gilAfter", "afterGils")):
        entry = files.get(key) if isinstance(files.get(key), dict) else {}
        recorded = (backend.get(side) or {}).get(str(level_id), {}).get("sha256")
        if not entry.get("sha256") or recorded != entry.get("sha256"):
            raise Refusal(
                "SAVE_MANIFEST_RECEIPT_MISBOUND",
                "%s's %s hash (%s) is not the hash the pinned receipt records for level %s "
                "in %s (%s); the manifest and its receipt describe different bytes"
                % (target, key, entry.get("sha256"), level_id, side, recorded), target)

    preflight = {"ok": None, "findings": [], "note": "not run"}
    preflight_module = module
    if preflight_module is None:
        loaded, error = load_save_manifest_producer()
        if loaded is None:
            raise Refusal("SAVE_MANIFEST_PRODUCER_UNLOADABLE", error, target)
        preflight_module = loaded
    preflight = preflight_module.producer_preflight(document)
    if not isinstance(preflight, dict) or preflight.get("ok") is not True:
        return None, ("SAVE_MANIFEST_PREFLIGHT_FAILED: the W08 producer's own preflight "
                      "refused this manifest: %s"
                      % json.dumps((preflight or {}).get("findings"), ensure_ascii=False)[:600])

    facts = {
        "path": str(target),
        "sha256": sha256_file(target),
        "caseId": document.get("caseId"),
        "runId": observed_run,
        "levelId": observed_level,
        "requestId": manifest_request,
        "saveWallClock": document.get("saveWallClock"),
        "declaredChangedRoots": document.get("declaredChangedRoots"),
        "entityDelta": delta,
        "intent": intent,
        "receipt": {"path": receipt_path["path"], "sha256": sha256_file(receipt_path["path"])},
        "pinnedOriginals": pinned,
        "preflight": preflight,
        "sampleRequestId": sample["requestId"],
        "sampleEntityId": sample_entity,
        "verified": True,
        "note": ("read from the W08 manifest and the receipt it pins; identity, every "
                 "pinned hash and the producer's own preflight were re-checked here"),
    }
    return facts, None


def read_reopen_evidence(path, level_id):
    """Derive ``reopen`` from a reopen acceptance original, or raise.

    An acceptance document is the ONLY thing that may set ``reopen`` true.  Its own
    business verdicts are re-read here (never a boolean the run typed), its level must
    be this level, and its bytes are hashed into the run-evidence document.
    """
    target = Path(path)
    if not target.is_file():
        raise Refusal("REOPEN_EVIDENCE_UNAVAILABLE",
                      "the reopen acceptance original %s is not on disk" % target, target)
    try:
        document = read_json(target)
    except (OSError, json.JSONDecodeError) as error:
        raise Refusal("REOPEN_EVIDENCE_UNAVAILABLE",
                      "%s is unreadable: %s" % (target, error), target)
    if not isinstance(document, dict):
        raise Refusal("REOPEN_EVIDENCE_UNAVAILABLE",
                      "%s is not an object" % target, target)
    operation = document.get("operation")
    if operation != REOPEN_ACCEPTANCE_OPERATION:
        raise Refusal("REOPEN_EVIDENCE_NOT_ACCEPTED",
                      "%s records operation %r, not %r"
                      % (target, operation, REOPEN_ACCEPTANCE_OPERATION), target)
    observed_level = as_uint(document.get("levelId"))
    if observed_level is None or observed_level != level_id:
        raise Refusal("LEVEL_MISMATCH",
                      "the reopen acceptance %s is for level %r, but this run is level %s"
                      % (target, document.get("levelId"), level_id), target)
    business = document.get("businessVerified")
    roundtrip = document.get("reopenRoundtripVerified")
    if business is not True or roundtrip is not True:
        raise Refusal(
            "REOPEN_EVIDENCE_NOT_ACCEPTED",
            "%s does not assert businessVerified/reopenRoundtripVerified (got %r/%r); "
            "the run must not delete a sample on a reopen nobody accepted"
            % (target, business, roundtrip), target)
    request_id = document.get("requestId")
    if not isinstance(request_id, str) or len(request_id) != 32:
        raise Refusal("REOPEN_EVIDENCE_NOT_ACCEPTED",
                      "%s names no 32-hex requestId" % target, target)
    # -- bind the packet to the dispatch it judges ------------------------------- #
    # An accepted verdict proves something only about the dispatch it was minted for.
    # ``native_reopen_acceptance`` stamps ``dispatchSha256`` = the hash of the sibling
    # reopen-dispatch.json and refuses any other location, so a packet that names a
    # different dispatch -- or no dispatch at all -- is a STALE response packet.  Fail
    # closed: an absent or malformed digest is refused, never defaulted.
    dispatch_sha = document.get("dispatchSha256")
    if not isinstance(dispatch_sha, str) or len(dispatch_sha) != 64 \
            or any(ch not in "0123456789abcdef" for ch in dispatch_sha):
        raise Refusal(
            "REOPEN_EVIDENCE_NOT_ACCEPTED",
            "%s carries no 64-hex dispatchSha256, so the packet cannot be bound to the "
            "dispatch it must judge" % target, target)
    dispatch_path = target.with_name(REOPEN_DISPATCH_NAME)
    if not dispatch_path.is_file():
        raise Refusal(
            "REOPEN_EVIDENCE_NOT_ACCEPTED",
            "the dispatch original %s the acceptance must be bound to is not on disk"
            % dispatch_path, dispatch_path)
    observed_dispatch_sha = sha256_file(dispatch_path)
    if observed_dispatch_sha != dispatch_sha:
        raise Refusal(
            "REOPEN_EVIDENCE_NOT_ACCEPTED",
            "%s was minted for dispatch %s, but the dispatch original beside it hashes to "
            "%s; an old response packet is not evidence of this reopen"
            % (target, dispatch_sha, observed_dispatch_sha), target)
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "schema": document.get("schema"),
        "operation": operation,
        "scope": document.get("scope"),
        "requestId": request_id,
        "levelId": observed_level,
        "dispatchSha256": dispatch_sha,
        "nativeReceiptSha256": document.get("nativeReceiptSha256"),
        "businessVerified": True,
        "reopenRoundtripVerified": True,
        "checks": document.get("checks"),
        "note": "read from the acceptance original; never a boolean this run typed, and "
                "bound to the dispatch original it was minted for",
    }


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

def resolve_save_manifest(spec, sample):
    """``(path | None, reason | None)``: the W08 manifest that belongs to this sample.

    Two ways a caller offers one, in priority order:

      * an explicit map, ``spec['saveManifests']``, keyed by THIS sample's create
        requestId (a list is also accepted; entries are indexed by the manifest's own
        save ``requestId`` against the sample's receipt);
      * the default drop beside the attempt's own originals,
        ``<attempt dir>/save-manifest.json``, so a wiring that writes the manifest where
        it wrote the receipt needs no extra argument.

    No manifest offered anywhere is NOT a refusal: it is "this run has no save manifest",
    so ``save`` stays false and P15 stays blocked -- the conservative direction.
    """
    offered = spec.get("saveManifests")
    if isinstance(offered, dict):
        candidate = offered.get(sample["requestId"])
        if candidate:
            return Path(candidate), None
    elif isinstance(offered, (list, tuple)):
        wanted = None
        receipt = Path(sample["dir"]) / SAVE_RECEIPT_NAME
        if receipt.is_file():
            try:
                reply = read_json(receipt).get("reply") or {}
                wanted = reply.get("requestId")
            except (OSError, json.JSONDecodeError, AttributeError):
                wanted = None
        for candidate in offered:
            try:
                document = read_json(candidate)
            except (OSError, json.JSONDecodeError):
                continue
            if wanted and document.get("requestId") == wanted:
                return Path(candidate), None
            if len(offered) == 1:
                return Path(candidate), None
    default = Path(sample["dir"]) / SAVE_MANIFEST_NAME
    if default.is_file():
        return default, None
    return None, ("SAVE_MANIFEST_ABSENT: no W08 save manifest was offered for sample %s "
                  "(looked for an explicit mapping and %s). The save leg needs BOTH the "
                  "run's own receipt AND the DS-05 manifest the verifier judges, so "
                  "`save` stays false and the entry gate keeps P15 blocked"
                  % (sample["requestId"], default))


def build(spec) -> dict:
    """Assemble the run-evidence document.  Raises a Refusal; never guesses."""
    run_root = Path(spec.get("runRoot") or "").resolve() if spec.get("runRoot") else None
    if run_root is None or not run_root.is_dir():
        raise Refusal("RUN_ROOT_INVALID", "spec.runRoot must be an existing directory")
    run_id = run_root.name
    if not run_id:
        raise Refusal("RUN_ID_INVALID", "the run root %s has no directory name" % run_root)

    level_id = as_uint(spec.get("levelId"))
    if level_id is None:
        raise Refusal("LEVEL_ID_INVALID", "spec.levelId must be a nonzero uint32")

    expected = spec.get("expectedRequests")
    expected_requests = None
    if expected is not None:
        if not isinstance(expected, (list, tuple)):
            raise Refusal("REQUEST_NOT_OWNED_BY_RUN",
                          "spec.expectedRequests must be a list of requestIds")
        expected_requests = {str(value).strip() for value in expected if str(value).strip()}

    samples_out = []
    excluded_samples = []
    creates, excluded_samples = read_case_creates(run_root, run_id, expected_requests)
    for sample in creates:
        created = read_created_ids(sample["dir"], run_id)
        entity_id = sample["entityId"]
        if entity_id is None and created is not None:
            entity_id = created.get("entityId")
        if created is not None and created.get("requestId") not in (None, sample["requestId"]):
            raise Refusal(
                "REQUEST_NOT_OWNED_BY_RUN",
                "the create stage %s names requestId %s but its own created-ids record "
                "names %s; the run cannot say which request created the sample"
                % (sample["dir"], sample["requestId"], created.get("requestId")),
                sample["dir"])
        if entity_id is None:
            raise Refusal(
                "REQUEST_NOT_OWNED_BY_RUN",
                "the create under %s names no entityId, so nothing this run created can "
                "be pointed at" % sample["dir"], sample["dir"])
        save, save_reason = read_save_evidence(sample["dir"], level_id, sample)
        sample["entityId"] = entity_id
        # The save leg's OTHER half: the W08 manifest (DS-05's judged artifact) must be
        # there TOO, and must be about this run, this level, this request and this sample.
        # Absent -> save stays false (blocked); contradictory -> a named refusal.
        manifest_path, manifest_reason = resolve_save_manifest(spec, sample)
        manifest_facts = None
        if manifest_path is not None:
            manifest_facts, manifest_reason = read_save_manifest_evidence(
                manifest_path, level_id, sample, save,
                module=spec.get("saveManifestModule"),
                repo_root=spec.get("repoRoot"))
        samples_out.append({
            "caseId": sample["caseId"],
            "attempt": sample["attempt"],
            "requestId": sample["requestId"],
            "entityId": entity_id,
            "templateId": sample["templateId"],
            "caseDir": str(sample["dir"]),
            "rawCall": sample["rawCall"],
            "createdIds": created,
            "saveEvidence": save,
            "saveRefusal": save_reason,
            "saveManifestEvidence": manifest_facts,
            "saveManifestRefusal": manifest_reason,
            "saveManifestPath": str(manifest_path) if manifest_path is not None else None,
            "saveDiff": read_save_diff(sample["dir"]),
            # BOTH halves are standing obligations: the run's own receipt AND the DS-05
            # manifest.  Either one missing leaves this sample unproven, and the gate's
            # `save` stays false -- "save and reopen" is not "half of save and reopen".
            "saveVerified": bool(save and save.get("succeeded")
                                 and manifest_facts and manifest_facts.get("verified")),
        })

    save_verified = bool(samples_out) and all(s["saveVerified"] for s in samples_out)

    reopen = None
    reopen_refusal = None
    if spec.get("reopenAcceptance"):
        reopen = read_reopen_evidence(spec["reopenAcceptance"], level_id)
    else:
        reopen_refusal = (
            "REOPEN_EVIDENCE_ABSENT: no reopen acceptance original was offered. The "
            "reopen is the C4-blocked half of P15's precondition, so `reopen` stays "
            "false and the entry gate keeps P15 blocked -- a save alone is not the "
            "'save AND reopen' the criterion names")

    request_ids = [sample["requestId"] for sample in samples_out]
    module = spec.get("roundMaterials") or load_round_materials()
    projection = (round_projection(request_ids, spec.get("repoRoot"), module)
                  if request_ids else None)

    document = {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "producer": PRODUCER_ID,
        "runId": run_id,
        "levelId": level_id,
        # -- the two booleans the gate reads, each DERIVED above -------------- #
        "save": save_verified,
        "reopen": bool(reopen),
        # -- and the originals that produced them ----------------------------- #
        "samples": samples_out,
        "excludedSamples": excluded_samples,
        "saveManifests": [s["saveManifestEvidence"] for s in samples_out],
        "round": projection,
        "reopenEvidence": reopen,
        "reopenRefusal": reopen_refusal,
        "capturedAtUtc": iso(datetime.now(timezone.utc)),
        "note": "each boolean above was derived from an original on disk, hashed in "
                "place; nothing here was typed by a caller, and no path in this "
                "producer writes `reopen: true` without an accepted reopen original",
        "limits": [
            "R1 a writer with access to the run root can replace an original and "
            "re-run the producer; this document binds hashes, it does not authenticate "
            "the writer",
            "R2 the save evidence proves THIS level's formal file moved under a native "
            "save of this run; it is not a persistence proof of any individual entity",
            "R3 the reopen acceptance original carries no entity id, so it is bound to "
            "this run by level and by its own accepted verdicts, not per sample",
        ],
    }
    document["digest"] = compute_digest(document)
    return document


def require_out_directory(document, target) -> Path:
    """The file must land at ``<run root>/run-evidence.json`` or nothing is written.

    The consumer derives the path from its own out-root; a document placed anywhere
    else is evidence the gate can never read while appearing to have been written.
    """
    target = Path(target)
    run_id = str(document.get("runId"))
    if target.name != EVIDENCE_FILENAME:
        raise Refusal("OUTPUT_DIRECTORY_MISMATCH",
                      "the gate reads %r; this write is named %r"
                      % (EVIDENCE_FILENAME, target.name), target)
    if target.parent.resolve().name != run_id:
        raise Refusal(
            "OUTPUT_DIRECTORY_MISMATCH",
            "run_parameter_matrix.run_evidence_from(out_root) reads "
            "<out_root>/%s, i.e. the document must land in the run root %r; this write "
            "is destined for %r. The gate never searches for the file, so a document "
            "written elsewhere would leave P15 blocked while looking written"
            % (EVIDENCE_FILENAME, run_id, target.parent), target)
    return target


def write_document(document, target) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=False)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.write("\n")
    return target


# --------------------------------------------------------------------------- #
# verification -- the half the gate calls
# --------------------------------------------------------------------------- #

def re_derive_sample_save_identity(index, sample, top_holder, document_level,
                                   document_run):
    """Re-derive one sample's SAVE identity from the ORIGINALS alone; raise ``Refusal``.

    ``verify_document`` must not believe a single thing the document asserts about
    its own save: not ``saveManifests[i].verified`` (a boolean any writer sets) and
    not its re-computable ``digest`` (a non-secret checksum any writer recomputes).
    The only facts this function trusts are *which files the document cites*; the
    run, level, request and ENTITY attribution are then recomputed from those files
    on disk:

      * the sample's ``requestId``/``entityId``/``runId`` are re-read from its own
        cited ``created-ids.json`` and/or ``raw-call.json`` -- the entity and the RUN
        the ORIGINALS attest, never the numbers the document recorded beside the
        sample, and never the caller-chosen directory NAME of the run root (round 141);
      * the level is the document's ``levelId``, re-checked against the sample's own
        ``save-receipt.json`` (which also re-derives its run and save request);
      * ``read_save_manifest_evidence`` re-runs the producer's own producer over the
        manifest the holders point at, binding run/level/request/entity and re-hashing
        every pinned original and the pinned receipt's GIL files.

    Returns ``None`` when the identity the originals support IS the one recorded;
    raises ``Refusal(code, detail)`` -- always named -- otherwise.  Every path that
    cannot be re-derived refuses; nothing is skipped.
    """
    if not isinstance(sample, dict):
        raise Refusal("SAMPLE_NOT_AN_OBJECT", "sample %d is not an object" % index,
                      sample)
    sample_request = sample.get("requestId")
    if not isinstance(sample_request, str) or not sample_request.strip():
        raise Refusal(
            "SAMPLE_IDENTITY_NOT_DERIVABLE",
            "sample %d names no requestId, so the originals it cites cannot be tied to "
            "one create" % index, None)
    sample_request = sample_request.strip()

    # -- ENTITY and RUN ATTRIBUTION from the sample's OWN cited originals --------- #
    attested_entity = None
    attested_run = None
    cited = 0
    for key in ("createdIds", "rawCall"):
        record = sample.get(key)
        if not isinstance(record, dict):
            continue
        path = record.get("path")
        if not isinstance(path, str) or not path:
            raise Refusal(
                "SAMPLE_IDENTITY_NOT_DERIVABLE",
                "sample %r's %s cites no path, so the entity it created cannot be "
                "re-derived" % (sample_request, key), None)
        if not Path(path).is_file():
            raise Refusal(
                "SAMPLE_IDENTITY_NOT_DERIVABLE",
                "sample %r's %s is gone from disk (%s)" % (sample_request, key, path),
                path)
        try:
            original = read_json(path)
        except (OSError, json.JSONDecodeError) as error:
            raise Refusal(
                "SAMPLE_IDENTITY_NOT_DERIVABLE",
                "sample %r's %s is unreadable: %s" % (sample_request, key, error), path)
        if not isinstance(original, dict):
            continue
        cited += 1
        seen_request = original.get("requestId")
        if isinstance(seen_request, str) and seen_request.strip() \
                and seen_request.strip() != sample_request:
            raise Refusal(
                "REQUEST_NOT_OWNED_BY_RUN",
                "the document names this sample's create request as %s, but its own %s "
                "original answers %s" % (sample_request, key, seen_request), path)
        # RUN -- the run each cited create original itself answers.  A create stage
        # that names a different run is not this sample's at all (the producer refuses
        # it in ``read_case_creates``; the consumer re-derives it here rather than
        # trusting ``document["runId"]`` or the run root's directory name).
        seen_run = original.get("runId")
        if isinstance(seen_run, str) and seen_run.strip():
            seen_run = seen_run.strip()
            if attested_run is not None and seen_run != attested_run:
                raise Refusal(
                    "RUN_NOT_OWNED_BY_RUN",
                    "sample %r's cited originals disagree on the run they attest (%s vs "
                    "%s); neither is shown to be this sample's run"
                    % (sample_request, attested_run, seen_run), path)
            attested_run = seen_run
        seen_entity = as_uint(original.get("entityId"))
        if seen_entity is not None:
            if attested_entity is not None and seen_entity != attested_entity:
                raise Refusal(
                    "SAMPLE_IDENTITY_NOT_DERIVABLE",
                    "sample %r's cited originals disagree on the entity they attest (%s "
                    "vs %s)" % (sample_request, attested_entity, seen_entity), path)
            attested_entity = seen_entity
    if cited == 0 or attested_entity is None:
        raise Refusal(
            "SAMPLE_IDENTITY_NOT_DERIVABLE",
            "sample %r cites no original that names the entity it created, so the "
            "manifest's entity attribution cannot be re-derived from the originals"
            % sample_request, None)
    recorded_entity = as_uint(sample.get("entityId"))
    if recorded_entity != attested_entity:
        raise Refusal(
            "SAVE_MANIFEST_NOT_ABOUT_SAMPLE",
            "the document records this sample's entity as %r, but its own cited originals "
            "attest entity %r; the manifest is bound to an entity the document merely "
            "claims" % (recorded_entity, attested_entity), None)
    # The identity the ORIGINALS support: hand this -- not the document's own sample
    # dict -- to the producer's re-derivation below.
    derived_sample = {"requestId": sample_request, "entityId": attested_entity}

    # -- both holders must exist and agree --------------------------------------- #
    named_holders = (("saveManifestEvidence", sample.get("saveManifestEvidence")),
                     ("saveManifests[%d]" % index, top_holder))
    for holder_label, holder in named_holders:
        if not isinstance(holder, dict):
            raise Refusal(
                "SAVE_MANIFEST_HOLDER_ABSENT",
                "sample %r's %s carries no save manifest holder, so its identity cannot "
                "be re-derived from the originals" % (sample_request, holder_label), None)
    recorded_holder = named_holders[0][1]
    for field in ("path", "sha256", "levelId"):
        if recorded_holder.get(field) != top_holder.get(field):
            raise Refusal(
                "SAVE_MANIFEST_HOLDERS_DISAGREE",
                "sample %r's two recorded holders of its save manifest disagree on %s "
                "(%r vs %r); a document whose holders contradict each other proves neither"
                % (sample_request, field, recorded_holder.get(field),
                   top_holder.get(field)), None)
    effective_level = as_uint(document_level)
    if effective_level is None:
        raise Refusal(
            "LEVEL_ID_INVALID",
            "the document asserts a save but names no levelId, so the save manifest's "
            "identity cannot be re-derived against a level", None)
    manifest_path = recorded_holder.get("path")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise Refusal(
            "SAVE_MANIFEST_HOLDER_ABSENT",
            "sample %r's save manifest carries no path, so its identity cannot be "
            "re-derived from the originals" % sample_request, None)

    # -- the sample's OWN receipt re-read from disk (RUN + LEVEL + REQUEST) ------- #
    receipt_record = sample.get("saveEvidence")
    receipt_path = (receipt_record.get("path")
                    if isinstance(receipt_record, dict) else None)
    receipt_facts = None
    if isinstance(receipt_path, str) and receipt_path:
        receipt_facts, _receipt_reason = read_save_evidence(
            str(Path(receipt_path).parent), effective_level, derived_sample)

    # -- RUN ATTRIBUTION must be the one the ORIGINALS support ------------------- #
    # Symmetric with request/level/entity above.  The document's ``runId`` is a CLAIM:
    # it is compared against (a) the run the sample's own cited create originals answer
    # and (b) the run the sample's own save receipt names.  It is NEVER rested on the
    # run root's directory NAME -- the caller chooses that -- so a document that keeps
    # every cited original byte-for-byte on the real run, re-stamps only its own
    # ``runId`` (and the recomputable digest) and points ``run_root`` at a directory
    # named like the claim still refuses here (round 141 review, probe_run_attrib RR1).
    receipt_run = None
    if isinstance(receipt_facts, dict):
        run_text = receipt_facts.get("run")
        if run_text:
            receipt_run = Path(str(run_text)).name
    derived_run = attested_run
    if receipt_run is not None:
        if derived_run is not None and receipt_run != derived_run:
            raise Refusal(
                "RUN_NOT_OWNED_BY_RUN",
                "sample %r's cited create originals attest run %r, but its own save "
                "receipt names run %r; the sample does not belong to one run"
                % (sample_request, derived_run, receipt_run), receipt_path)
        if derived_run is None:
            derived_run = receipt_run
    if derived_run is None:
        raise Refusal(
            "RUN_NOT_OWNED_BY_RUN",
            "sample %r cites no original that names the run it belongs to, so its run "
            "attribution cannot be re-derived from the originals (only from the caller's "
            "run-root directory name)" % sample_request, None)
    if not isinstance(document_run, str) or not document_run.strip():
        raise Refusal(
            "RUN_NOT_OWNED_BY_RUN",
            "the document asserts a save but names no runId, so the run its originals "
            "attest cannot be tied to the document", None)
    if document_run.strip() != derived_run:
        raise Refusal(
            "RUN_NOT_OWNED_BY_RUN",
            "the document names run %r, but its own cited originals attest run %r; the run "
            "is the document's own claim, not the one the originals support"
            % (document_run, derived_run), None)

    # -- the producer's own derivation over the manifest (never a copy here) ------ #
    derived, derived_reason = read_save_manifest_evidence(
        manifest_path, effective_level, derived_sample, receipt_facts)
    if derived is None:
        raise Refusal(
            "SAVE_MANIFEST_NOT_A_SAVE",
            "the save manifest the document points at no longer derives as this sample's "
            "save evidence: %s" % derived_reason, manifest_path)
    if derived.get("verified") is not True:
        raise Refusal(
            "SAVE_MANIFEST_NOT_A_SAVE",
            "the save manifest the document points at re-derives WITHOUT a verified save "
            "for this sample", manifest_path)
    # The identity the originals support must be the identity the document RECORDED;
    # `verified` above was DERIVED, never read from the document.
    for field, expected, label in (
            ("levelId", effective_level, "levelId"),
            ("levelId", recorded_holder.get("levelId"), "recorded levelId"),
            ("sha256", recorded_holder.get("sha256"), "recorded sha256")):
        if derived.get(field) != expected:
            raise Refusal(
                "SAVE_MANIFEST_IDENTITY_MISMATCH",
                "the save manifest the document points at re-derives with %s=%r, but the "
                "document recorded %r; the recorded identity is not the one the originals "
                "support" % (label, derived.get(field), expected), manifest_path)
    return None


def verify_document(document, *, run_root=None, level_id=None, recheck_originals=True):
    """``(ok, reason)`` for an already-written run-evidence document.

    Four independent obligations, each of which is a real failure mode:

      * SHAPE       it is the producer's document at all (kind/schema/samples/round);
      * DIGEST      its own ``digest`` recomputes over its own core, so an edited
                    boolean is detected;
      * IDENTITY    it names this run, and (when the caller knows it) this level;
      * ORIGINALS   every original it cites is still on disk and still hashes to the
                    value recorded beside it, so a swapped receipt is detected.

    ``{}`` -- the shape ``run_evidence_from`` returns for an absent or unreadable file
    -- fails on SHAPE, i.e. "nobody said" is never "the run is proven".
    """
    if not isinstance(document, dict) or document.get("kind") != KIND:
        return False, ("not a %r document, so it carries no verified evidence" % KIND)
    if document.get("schemaVersion") != SCHEMA_VERSION:
        return False, ("schemaVersion %r is not the version this verifier knows (%s)"
                       % (document.get("schemaVersion"), SCHEMA_VERSION))
    recorded = document.get("digest")
    if not isinstance(recorded, str) or recorded != compute_digest(document):
        return False, ("the document's own digest does not recompute over its core: it "
                       "was edited after it was written, or it was not written by %s"
                       % PRODUCER_ID)
    if run_root is not None and document.get("runId") != Path(run_root).name:
        return False, ("the document names run %r, the run root is %r"
                       % (document.get("runId"), Path(run_root).name))
    if level_id is not None and as_uint(document.get("levelId")) != as_uint(level_id):
        return False, ("the document names level %r, the caller says %r"
                       % (document.get("levelId"), level_id))
    samples = document.get("samples")
    if not isinstance(samples, list) or not samples:
        return False, "the document carries no samples, so it proves nothing about one"
    if document.get("save") is not True:
        return False, "the document does not assert a verified save"
    # `save` now stands on TWO originals per sample -- the run's own receipt and the W08
    # manifest -- so a document that asserts it without carrying the manifests is not the
    # shape this verifier knows.  (A hand-edited `"save": true` also fails DIGEST above.)
    manifests = document.get("saveManifests")
    if not isinstance(manifests, list) or len(manifests) != len(samples) \
            or not all(isinstance(item, dict) and item.get("verified") is True
                       for item in manifests):
        return False, ("the document asserts a save but does not carry one verified W08 "
                       "save manifest per sample")
    if document.get("reopen") is True and not isinstance(document.get("reopenEvidence"), dict):
        return False, "reopen is true but no reopen original was recorded"
    if recheck_originals:
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                return False, "sample %d is not an object" % index
            for key in ("rawCall", "saveEvidence", "createdIds"):
                record = sample.get(key)
                if not isinstance(record, dict):
                    continue
                path, expected = record.get("path"), record.get("sha256")
                if not path or not expected:
                    return False, ("sample %r's %s carries no path/sha256"
                                   % (sample.get("requestId"), key))
                if not Path(path).is_file():
                    return False, ("sample %r's %s is gone from disk (%s)"
                                   % (sample.get("requestId"), key, path))
                if sha256_file(path) != expected:
                    return False, ("sample %r's %s no longer hashes to the value the "
                                   "document recorded (%s)"
                                   % (sample.get("requestId"), key, path))
            # The save-manifest half: its own bytes, and the receipt it pins, are re-read
            # here too -- editing either one after the document was written is caught.
            manifest = sample.get("saveManifestEvidence")
            if isinstance(manifest, dict):
                for key, label in ((None, "manifest"), ("receipt", "receipt")):
                    record = manifest if key is None else manifest.get(key)
                    if not isinstance(record, dict):
                        continue
                    path, expected = record.get("path"), record.get("sha256")
                    if not path or not expected:
                        return False, ("sample %r's save %s carries no path/sha256"
                                       % (sample.get("requestId"), label))
                    if not Path(path).is_file():
                        return False, ("sample %r's save %s is gone from disk (%s)"
                                       % (sample.get("requestId"), label, path))
                    if sha256_file(path) != expected:
                        return False, ("sample %r's save %s no longer hashes to the value "
                                       "the document recorded (%s)"
                                       % (sample.get("requestId"), label, path))
                for entry in manifest.get("pinnedOriginals") or []:
                    if not isinstance(entry, dict):
                        continue
                    path, expected = entry.get("path"), entry.get("sha256")
                    if not path or not expected or not Path(path).is_file():
                        return False, ("sample %r's save manifest pins %s, gone from disk"
                                       % (sample.get("requestId"), path))
                    if sha256_file(path) != expected:
                        return False, ("sample %r's save manifest pins %s no longer at the "
                                       "hash it recorded" % (sample.get("requestId"), path))
        reopen = document.get("reopenEvidence")
        if isinstance(reopen, dict):
            path, expected = reopen.get("path"), reopen.get("sha256")
            if not path or not expected or not Path(path).is_file():
                return False, "the reopen original is gone from disk (%s)" % path
            if sha256_file(path) != expected:
                return False, ("the reopen original no longer hashes to the value the "
                               "document recorded (%s)" % path)
    # -- CONSUMER-SIDE IDENTITY RE-DERIVATION (R09 rev-3, round 140) ------------- #
    # Run for EVERY sample, ALWAYS -- deliberately OUTSIDE the ``recheck_originals``
    # gate.  Two ways the rev-1/rev-2 consumers still trusted a claim: (a) an
    # adversarial document whose sample carried no ``requestId`` crashed the verifier
    # with an uncaught ``KeyError`` instead of naming a refusal; (b) with
    # ``recheck_originals=False`` -- a flag the caller controls -- the whole identity
    # derivation was SKIPPED, so the other-level forgery verified True again.  So the
    # identity is re-derived unconditionally, and every failure mode -- a named
    # ``Refusal`` OR an unreadable document -- becomes a NAMED refusal, never a crash.
    for index, sample in enumerate(samples):
        sample_request = sample.get("requestId") if isinstance(sample, dict) else None
        try:
            re_derive_sample_save_identity(
                index, sample, manifests[index], document.get("levelId"),
                document.get("runId"))
        except Refusal as refusal:
            return False, ("sample %r's save identity does not re-derive from the "
                           "originals: %s: %s"
                           % (sample_request, refusal.code, refusal.detail))
        except Exception as error:                      # noqa: BLE001 -- a consumer must
            # never crash on a document it cannot read; an unreadable document is a
            # named refusal, not a traceback a caller might swallow as success.
            return False, ("MALFORMED_DOCUMENT: the document is unreadable where sample "
                           "%r's save identity would be re-derived from the originals "
                           "(%s: %s); a document this verifier cannot read is not evidence"
                           % (sample_request, type(error).__name__, error))
    return True, ""


def load_producer(path=None):
    """Import this producer by path, for a consumer that must not reimplement it."""
    target = Path(path or (Path(__file__).resolve()))
    name = "w06_run_evidence"
    spec = importlib.util.spec_from_file_location(name, str(target))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _summary(document, target, wrote) -> dict:
    return {
        "status": ("written" if wrote else "assembled"),
        "wrote": str(wrote) if wrote else None,
        "runId": document["runId"],
        "levelId": document["levelId"],
        "save": document["save"],
        "reopen": document["reopen"],
        "samples": len(document["samples"]),
        "saveManifests": sum(1 for item in (document.get("saveManifests") or [])
                             if isinstance(item, dict) and item.get("verified") is True),
        "saveManifestRefusals": sorted({
            str(sample.get("saveManifestRefusal"))
            for sample in document.get("samples") or []
            if sample.get("saveManifestRefusal")}),
        "roundIdDigest": (document.get("round") or {}).get("roundIdDigest"),
        "materialsPath": (document.get("round") or {}).get("materialsPath"),
        "digest": document["digest"],
        "reopenRefusal": document.get("reopenRefusal"),
    }


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-root", type=Path, default=None,
                        help="the run root the gate reads: <run-root>/run-evidence.json")
    parser.add_argument("--level-id", type=int, default=None)
    parser.add_argument("--expect-request", action="append", default=None,
                        metavar="REQUEST_ID",
                        help="repeatable; the create requestIds the caller declares are "
                             "this run's own samples. A create in the run naming any "
                             "other request, and a declared request with no create, are "
                             "both refused")
    parser.add_argument("--reopen-acceptance", type=Path, default=None,
                        help="the reopen acceptance original; when absent, `reopen` is "
                             "written false and P15 stays blocked")
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="the tree the MCP cleanup directory is relative to; used "
                             "only to render the published path")
    parser.add_argument("--out", type=Path, default=None,
                        help="defaults to <run root>/run-evidence.json; any other "
                             "directory name is refused")
    parser.add_argument("--round-materials", type=Path, default=None,
                        help="the round-materials producer whose round_id_digest names "
                             "the MCP cleanup directory (default: the sibling)")
    parser.add_argument("--save-manifest", action="append", default=None, type=Path,
                        metavar="PATH",
                        help="repeatable; the W08 save manifest (backend/save_manifest.py "
                             "output) that stands behind a sample's save. Each is bound to "
                             "its sample by the manifest's own identity and the sample's "
                             "receipt. Absent everywhere -> `save` stays false and P15 "
                             "stays blocked")
    parser.add_argument("--save-manifest-module", type=Path, default=None,
                        help="backend/save_manifest.py whose producer_preflight judges "
                             "the manifests (default: the repo's own)")
    parser.add_argument("--verify", type=Path, default=None,
                        help="verify an already-written document instead of building one")
    parser.add_argument("--dry-run", action="store_true",
                        help="assemble and validate; write nothing")
    args = parser.parse_args(argv)

    if args.verify is not None:
        try:
            document = read_json(args.verify)
        except (OSError, json.JSONDecodeError) as error:
            print(json.dumps({"status": "refused",
                              "refusal": {"code": "RUN_EVIDENCE_SHAPE_UNKNOWN",
                                          "detail": "%s: %s" % (type(error).__name__,
                                                                error),
                                          "source": str(args.verify)}}))
            return 2
        ok, reason = verify_document(document, run_root=args.run_root,
                                     level_id=args.level_id)
        print(json.dumps({"status": "verified" if ok else "refused", "ok": ok,
                          "reason": reason or None, "verified": str(args.verify)},
                         ensure_ascii=False, indent=1))
        return 0 if ok else 1

    if args.run_root is None or args.level_id is None:
        parser.error("--run-root and --level-id are required to build")

    # Resolve the round-materials producer ONCE, so a missing producer is a named
    # refusal before anything is measured.
    try:
        round_module = load_round_materials(args.round_materials)
    except Refusal as refusal:
        print(json.dumps({"status": "refused", "refusal": refusal.as_json(),
                          "wrote": None}, ensure_ascii=False))
        return 1

    try:
        document = build({
            "runRoot": args.run_root,
            "levelId": args.level_id,
            "expectedRequests": args.expect_request,
            "reopenAcceptance": args.reopen_acceptance,
            "repoRoot": args.repo_root,
            "roundMaterials": round_module,
            "saveManifests": args.save_manifest,
            "saveManifestModule": (load_save_manifest_producer(args.save_manifest_module)[0]
                                   if args.save_manifest is not None else None),
        })
    except Refusal as refusal:
        print(json.dumps({"status": "refused", "refusal": refusal.as_json(),
                          "wrote": None}, ensure_ascii=False))
        return 1

    # The projection is computed with the module resolved above, so the published
    # directory and the MCP consumer's derivation come from the same function.
    target = args.out or (Path(args.run_root) / EVIDENCE_FILENAME)
    try:
        require_out_directory(document, target)
        if args.dry_run:
            print(json.dumps(_summary(document, target, None),
                             ensure_ascii=False, indent=1))
            return 0
        wrote = write_document(document, target)
        require_out_directory(document, wrote)
        ok, reason = verify_document(document, run_root=args.run_root,
                                     level_id=args.level_id)
        if not ok:
            raise Refusal("RUN_EVIDENCE_NOT_SELF_CONSISTENT", reason, wrote)
    except Refusal as refusal:
        print(json.dumps({"status": "refused", "refusal": refusal.as_json(),
                          "wrote": None}, ensure_ascii=False))
        return 1

    print(json.dumps(_summary(document, target, wrote), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
