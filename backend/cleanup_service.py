"""Business cleanup closure for ONE round's own entities, plus the S12 orchestration contract.

WHAT THIS IS
------------
The layer between "the caller has a level handle and a list of ids" and the two native
routes

    delete-owned-entity-ids-dry-run    (read-only: id -> frontend path mapping)
    delete-owned-entity-ids            (mutating: bounded, NOT atomic, NOT ownership-checked)

The word "owned" in those route names is a claim about the CALLER's intent.  The adapter
says so itself (``tools/editor-bridge/Adapter/OwnedEntityDelete.cs``: "the boundary is the
ID LIST and nothing else"), and it may stop early, so a call can delete some ids and never
reach the rest.  This module does not re-implement any of that and does not weaken it.

WHAT IT REUSES (never a second, weaker copy)
--------------------------------------------
``tools/game-executor/cleanup_owned_entities.py`` is loaded by path and used directly:

* ``prove_ownership``   -- the three-way intersection of 07 section 9 step 1
* ``load_receipts`` / ``load_baseline``  -- receipt and baseline normalisation
* ``build_batches``     -- the single 64-id ceiling
* ``classify_dry_run`` / ``classify_execute`` -- per-id judging of one reply
* ``Refusal`` / ``DispatchResult`` / ``MAX_IDS_PER_CALL``

If that module is missing or cannot be loaded, this service refuses to start: a service
that cannot prove ownership must not be able to dispatch a delete.

OWNERSHIP IS (levelId, entityId), NOT entityId
----------------------------------------------
Entity ids are reused across levels: ``1077936135`` exists in level ``1073741834``
(2026-09-23) and in level ``1073741839`` (2026-09-29).  An id therefore is NOT an
attribution proof, and a lookup by id alone can hit the wrong request in another level.
Every id this module handles is keyed ``"<levelId>:<entityId>"``; a receipt whose levelId
is not the session's level is refused (``LEVEL_MISMATCH``), and a receipt set that binds
one id to two levels/templates is refused as ambiguous.  This is the documented fact from
2026-09-30, not a hypothetical.

THE THREE HISTORICAL IDS ARE FROZEN
-----------------------------------
``1077936129`` / ``1077936130`` / ``1077936131`` are present in the live level but have NO
create receipt of any round, so they cannot be attributed and may be pre-existing content.
They are refused by name (``CLEANUP_TARGET_UNATTRIBUTABLE``) even if a caller asks for them
and even if some document lists them as owned.  The historical "55 candidate ids" is a work
list, not a delete list.  See ``PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL``.

NO IDS -> REFUSAL, NEVER AN EMPTY LIST
--------------------------------------
Three different situations must never collapse into "nothing to delete, done":

1. the caller supplied no ids                     -> ``CLEANUP_IDS_EMPTY``
2. the ownership materials could not be obtained  -> ``OWNERSHIP_MATERIALS_UNAVAILABLE``
3. the materials were read but nothing passed the proof -> per-id refusals

None of the three dispatches anything.  An empty list is never sent to the route.

PER-ID STATES (closed set of four)
----------------------------------
``deleted`` | ``refused`` | ``not-attempted`` | ``unknown``

The mapping from the transport-level ledger is deliberate and fail-closed:

    not-dispatched:list-refused / :target-changed   -> refused
    not-attempted / :prior-unknown-outcome          -> not-attempted
    dispatched / :threw-native / :path-mismatch     -> judged by a FRESH read-back:
        absent from a trusted read-back             -> deleted
        present in a trusted read-back              -> unknown  (subState
                                                       "dispatched:still-present")
        no trustworthy read-back at all             -> unknown
    unreadable reply / launch error (batch-level)   -> unknown for the whole batch

``dispatched:still-present`` is ``unknown`` and not a success on purpose: the adapter's own
notice says ``nativeResult: true`` is dispatch-only, and because ids are reused across
levels the object observed after the delete may not be the one that was dispatched.  The
precise transport classification is never lost -- it is kept in ``subState``.

The four states are the closed vocabulary; nothing is reported as "probably fine".

RESUMING (断点续收)
-------------------
A checkpoint (new file, under the caller's task run root) records the per-id state, the
request ids already used and the ids whose outcome is unknown.  Resuming:

* ids already ``deleted`` are skipped -- a completed run resumed is a no-op;
* ids ``unknown`` are NEVER re-sent (``RESUME_UNKNOWN_NOT_RESENT``); reconcile from
  evidence first;
* ids ``not-attempted`` may be dispatched under a NEW request id, because they were only
  ever in batches that were not sent;
* ids ``refused`` stay refused for the same reason and are not retried silently.

WHAT THIS MODULE DOES NOT DO
----------------------------
No queue path, helper pid, journal path, review path or save copy is ever a caller-facing
argument: the bridge, the ownership materials and the resource ledger all arrive through
injected execution-layer seams (see ``CleanupBridge`` / ``OwnershipProvider`` / ... below).
The two peer interfaces this module consumes were frozen first and then checked against the
delivered code:

* DS-08 -- ``backend/operation_state.py``'s ``OperationLedger.ownership(level_id, ...)``
  answers in ``(levelId, entityId)`` terms and refuses a caller-declared id.  It does not
  carry the pre-create baseline difference or the template comparison, so
  ``materials_from_ownership_query`` uses it to decide WHICH receipts are this round's and
  still runs the full three-way proof over them.  Its ``refused``/``unknown`` rows are
  carried over as refusals, never widened.
* DS-05 -- ``backend/save_verification.py``'s ``verify_saved_case(manifest)`` report is
  accepted directly and normalised by ``adapt_save_verification``, which carries each
  stage verdict over unchanged and derives the layer from whether the bound files really
  resolve.

Nothing here starts, stops or restarts the game or the editor; nothing here deletes
anything by itself.

S12 ORCHESTRATION
-----------------
``orchestrate_s12`` produces the three evidence documents S12 still lacks
(``cleanup-save-diff`` / ``cleanup-reopen`` / ``resource-cleanup``) from producers that
actually exist.  Two rules make them unfakeable:

* a document may only be ``pass`` when every one of its ``evidenceRef`` pointers resolves
  on disk with the recorded sha256 -- an empty body cannot pass; and
* ``cleanup-save-diff`` may only be ``pass`` when every file the save case is bound to
  resolves on disk with its recorded sha256 (that is what "live" is derived from), and when
  no axis of the verification is unproven.  An offline fixture therefore always yields
  ``blocked``, which is the point.

``cleanup-reopen`` is delegated to the mainline (T11): this module emits only the request
contract and the call site, with status ``not-run``, and never a verdict of its own.
``resource-cleanup`` releases OWN resources only; a resource whose ownership proof does not
resolve, or whose locator is outside the allowed roots, is refused and never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / ".runtime"
OWNERSHIP_PRODUCER_PATH = ROOT / "tools/game-executor/cleanup_owned_entities.py"
RUNTIME_ROOT = ROOT / ".runtime/cordis-plan-work"
#: The concrete DS-05 seam (W10).  Loaded by path like the ownership producer, because the
#: offline CLI is run as a script and ``backend`` is then not an importable package.
SAVE_DIFF_ADAPTER_PATH = ROOT / "backend/cleanup_save_diff_adapter.py"

MODULE_VERSION = 1
CONTRACT_VERSION = "1"

#: The three ids 2026-09-30 could not attribute (present in the live level, no create
#: receipt in any round, possibly pre-existing content).  They must not be deleted by a
#: cleanup that claims to be "this round's own".  A future round that genuinely owns one of
#: them must be able to show a create receipt for it, which means a reviewed change to this
#: constant -- not a caller-supplied list.
#:
#: SCOPED BY LEVEL, 2026-10-08, for the reason this module already states about ownership
#: itself at line 29 -- ownership is (levelId, entityId), not entityId.  These three were
#: observed in ONE level; the flat form protected the same numbers in every level, and an
#: entity id is not a property of an object (1077936135 has been recorded in two levels
#: under two templates).  MEASURED: the live parameter driver created 1077936130 in level
#: 1073741842 and was then refused permission to delete its own object.
PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL = {
    1073741839: frozenset({1077936129, 1077936130, 1077936131}),
}


def protected_ids_for(level_id) -> frozenset:
    """The unattributable ids OF THAT LEVEL.  An unknown level resolves to EMPTY.

    Protection that is not known to apply is not invented; nothing reaches a delete
    without first passing the ownership proof for THIS round and THIS level.
    """
    try:
        return frozenset(PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL.get(int(level_id), ()))
    except (TypeError, ValueError):
        return frozenset()

#: Per-id states.  Closed: this module never emits anything else.
STATE_DELETED = "deleted"
STATE_REFUSED = "refused"
STATE_NOT_ATTEMPTED = "not-attempted"
STATE_UNKNOWN = "unknown"
PER_ID_STATES = (STATE_DELETED, STATE_REFUSED, STATE_NOT_ATTEMPTED, STATE_UNKNOWN)

#: Stage statuses, from G01 / TOOL-CONTRACT (D9, D10).  ``persistence`` and ``failed`` are
#: input aliases only; they are never emitted by this module.
STAGE_NOT_RUN = "not-run"
STAGE_PASS = "pass"
STAGE_FAIL = "fail"
STAGE_BLOCKED = "blocked"
STAGE_UNKNOWN = "unknown"
STAGE_NOT_APPLICABLE = "not-applicable"

STAGE_NAMES = ("liveReadback", "saveDiff", "reopen", "runtime", "cleanup")

EXIT_CLEAN = 0
EXIT_REFUSED = 1
EXIT_PARTIAL = 2
EXIT_USAGE = 3
EXIT_UNKNOWN = 4
EXIT_EVIDENCE_UNWRITTEN = 5

EXECUTE_OFFLINE = "the offline CLI never dispatches a delete; the mainline runs execute"


# --------------------------------------------------------------------------- #
# The reused ownership producer
# --------------------------------------------------------------------------- #

def _load_ownership_producer(path: Path = OWNERSHIP_PRODUCER_PATH):
    """Load ``cleanup_owned_entities.py`` by path (the directory name has a hyphen).

    Import failure is fatal on purpose: every ownership decision below is delegated to
    this module, and a service that cannot load it has no proof to offer.
    """
    if not path.is_file():
        raise RuntimeError("OWNERSHIP_PRODUCER_MISSING: %s" % path)
    spec = importlib.util.spec_from_file_location("_cleanup_owned_entities_reused", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("OWNERSHIP_PRODUCER_UNLOADABLE: %s" % path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec_module: the producer uses ``from __future__ import
    # annotations``, and ``@dataclass`` resolves those strings through
    # ``sys.modules[cls.__module__]`` -- which does not exist for a by-path load.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


co = _load_ownership_producer()

#: The F-011 legs (baseline difference, round time window, receipt provenance).  Loaded
#: the same way and with the same fatal-on-failure rule as the producer above: a service
#: that cannot evaluate "what did this round add" must not be able to dispatch a delete.
LEGS_MODULE_PATH = ROOT / "backend/cleanup_ownership_legs.py"


def _load_ownership_legs(path: Path = LEGS_MODULE_PATH):
    return _load_ownership_producer(path)


ownership_legs = _load_ownership_legs()

MAX_IDS_PER_CALL = co.MAX_IDS_PER_CALL
Refusal = co.Refusal
DispatchResult = co.DispatchResult
DRY_OP = co.DRY_OP
DELETE_OP = co.DELETE_OP

HASH_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def producer_hashes() -> dict:
    """Hashes of the sources this service's verdicts rest on."""
    return {
        "backend/cleanup_service.py": sha256_file(Path(__file__)),
        "tools/game-executor/cleanup_owned_entities.py": sha256_file(OWNERSHIP_PRODUCER_PATH),
    }


def s12_output_layer(round_id, case_request_id=None) -> str:
    """The S12 layer directory name, derived ONLY from the run/case identity.

    The three S12 documents used to be written straight under the caller's
    ``--s12-output-root`` (``<root>/<name>/<name>.json``), so two different runs that were
    handed the same root collided on the same files, and nothing in the path said which
    run or which save case the bundle belonged to.  The layer is a digest of the identity,
    not the identity text, for two reasons: a caller cannot steer the destination through
    a crafted run id, and re-running the same identity lands on the same layer (so the
    exclusive write refuses the second write instead of silently duplicating).  The
    ``case-`` half is present only when a save-case requestId was supplied, so a bundle
    built without a case is a different layer from one built with it.
    """
    run = hashlib.sha256(("s12-run\0" + (round_id or "")).encode("utf-8")).hexdigest()[:16]
    if case_request_id:
        case = hashlib.sha256(("s12-case\0" + case_request_id).encode("utf-8")).hexdigest()[:16]
        return "run-%s-case-%s" % (run, case)
    return "run-%s" % run


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha256_canonical(value) -> str:
    return sha256_text(_canonical(value))


# --------------------------------------------------------------------------- #
# Frozen interfaces (DS-08 / DS-05 / bridge / resources / T11)
# --------------------------------------------------------------------------- #
#
# None of these is a guess about an interface that already exists.  Each one is written
# here because the producing task has NOT delivered yet (DS-08 ownership ledger, DS-05
# independent save verification), so the consumer side is frozen first and a conforming
# fixture is used in tests.  The mainline adapter is the wiring patch, not this module.

def materials_from_ownership_query(query, *, pre_baseline, current_baseline, source,
                                   digest=None, receipt_resolver=None):
    """Adapter for the DS-08 ownership query (``backend/operation_state.py``).

    ``OperationLedger.ownership(level_id, operation_ids=..., candidate_ids=...)`` already
    answers in ``(levelId, entityId)`` terms and already refuses a caller-declared id:
    "a caller-declared id is not proof of ownership".  Its ``owned`` rows carry a
    ``journalRef`` to this run's create receipt.  What it does NOT carry is the
    pre-create baseline difference and the template comparison, so this layer still runs
    the full three-way proof over the receipt files it points at -- the ledger decides
    WHICH receipts are this round's, the proof decides whether the ids are new and still
    the same object.

    The ledger's own ``refused``/``unknown`` rows are kept and re-emitted as refusals, so
    a query answer is never widened by passing through this module.
    """
    if not isinstance(query, dict):
        return OwnershipUnavailable("OWNERSHIP_QUERY_SHAPE_UNKNOWN",
                                    "the ownership query did not return an object")
    resolver = receipt_resolver or (lambda row: row.get("journalRef"))
    receipts = []
    for row in query.get("owned") or []:
        if not isinstance(row, dict):
            continue
        reference = resolver(row)
        if reference:
            receipts.append(Path(reference) if not isinstance(reference, Path) else reference)
    if not receipts:
        return OwnershipUnavailable(
            "OWNERSHIP_QUERY_EMPTY",
            "the ownership ledger returned no receipt for this round in level %r; that is not "
            "the same statement as 'nothing is owned', so it is refused"
            % query.get("levelId"))
    return OwnershipMaterials(
        levelId=query.get("levelId"), receipts=tuple(receipts),
        preBaseline=Path(pre_baseline) if pre_baseline else None,
        currentBaseline=Path(current_baseline), source=source or "operation-ledger",
        digest=digest, ledgerQuery=query)


def adapt_save_verification(report, *, manifest=None) -> Any:
    """Normalise a DS-05 ``verify_saved_case`` report into the shape used here.

    ``backend/save_verification.py`` returns a report whose ``stages`` hold
    ``saveInvocation``/``savedContent``/``allowedDelta``/``unrelatedUnchanged`` plus a
    folded ``stages.saveDiff`` with status in ``pass/fail/blocked/evidence-insufficient``.
    This adapter carries those verdicts over unchanged -- it never upgrades one.  The
    ``layer`` is derived, not declared: it is ``live`` only when every bound file in
    ``manifest['files']`` resolves on disk with the recorded sha256, so an offline
    fixture (whose paths are made up) can never reach ``pass``.
    """
    if not isinstance(report, dict):
        return VerificationUnavailable("SAVE_VERIFICATION_SHAPE_UNKNOWN",
                                       "the save verifier did not return a report object")
    stages = report.get("stages")
    if not isinstance(stages, dict):
        return VerificationUnavailable("SAVE_VERIFICATION_SHAPE_UNKNOWN",
                                       "the save report carries no stages block")
    names = ("saveInvocation", "savedContent", "allowedDelta", "unrelatedUnchanged")
    bound = ((manifest or {}).get("files") or {})
    refs = {key: entry for key, entry in bound.items()
            if isinstance(entry, dict) and "path" in entry and "sha256" in entry}
    resolved = {key: entry for key, entry in refs.items()
                if evidence_ref_resolves(entry)}
    layer = "live" if refs and len(resolved) == len(refs) else "offline"

    #: Which bound file backs which axis.  A stage's verdict is only citable when the file
    #: it is about is on disk with the recorded bytes; otherwise the axis keeps its verdict
    #: but has no pointer, which the caller turns into a non-pass.
    axis_files = {
        "saveInvocation": ("gilBefore", "gilAfter", "gipBefore", "gipAfter"),
        "savedContent": ("gilAfter", "gilBefore"),
        "allowedDelta": ("gilAfter", "gipAfter"),
        "unrelatedUnchanged": ("gipAfter", "gipBefore"),
    }
    fallback = next(iter(resolved.values())) if layer == "live" and resolved else None

    def ref_for(axis):
        for key in axis_files.get(axis, ()):
            if key in resolved:
                return resolved[key]
        return fallback

    judgments = {}
    for name in names:
        block = stages.get(name)
        if not isinstance(block, dict) or "status" not in block:
            return VerificationUnavailable(
                "SAVE_VERIFICATION_INCOMPLETE",
                "the save report has no usable %r stage" % name)
        judgments[name] = Judgment(proven=block.get("status") == STAGE_PASS,
                                   evidenceRef=ref_for(name),
                                   reason="status=%r" % block.get("status"))
    return SaveDiffVerdict(
        saveInvocation=judgments["saveInvocation"],
        savedContent=judgments["savedContent"],
        allowedDelta=judgments["allowedDelta"],
        unrelatedUnchanged=judgments["unrelatedUnchanged"],
        unrelatedObjectsPreserved=Judgment(
            proven=judgments["unrelatedUnchanged"].proven,
            evidenceRef=ref_for("unrelatedUnchanged"),
            reason=None if not refs else
                   ("%d of %d bound file(s) do not resolve" % (len(refs) - len(resolved),
                                                               len(refs)))
                   if len(resolved) != len(refs) else None),
        layer=layer,
        producerRef=evidence_ref(Path(ROOT / "backend/save_verification.py")),
        detail="adapted from a DS-05 verify_saved_case report")


@dataclass(frozen=True)
class CleanupSession:
    """The execution-layer view of where a cleanup may happen.  Never a model argument."""

    levelId: int
    levelHandleDigest: str
    bridgeRunId: str | None = None
    sessionIdentity: str | None = None
    roundId: str | None = None

    def key(self, entity_id: int) -> str:
        return "%d:%d" % (self.levelId, entity_id)


@dataclass(frozen=True)
class OwnershipMaterials:
    """This round's create receipts and the two baselines of the three-way proof.

    Paths -- not documents -- because that is exactly what the reused producer takes, and
    because the executon layer (not the model) owns where they live.  ``digest`` is the
    execution layer's own fingerprint of the material set; it is recorded, never trusted
    as a proof by itself.
    """

    levelId: int
    receipts: tuple
    preBaseline: Path | None
    currentBaseline: Path
    source: str
    digest: str | None = None
    #: The DS-08 ownership query this material set came from, when it came from one.  Its
    #: ``refused``/``unknown`` rows are honoured as refusals here too, so the ledger's own
    #: answer is never quietly widened by this layer.
    ledgerQuery: dict | None = None
    #: The F-011 round materials: the round window, the pre-create baseline, the complete
    #: read-back taken immediately before this cleanup, and the receipt provenance.  They
    #: are execution-layer material and are REQUIRED -- ``None`` makes this service refuse
    #: rather than fall back to the three-way proof alone, which cannot tell this round's
    #: objects from objects that were already present.
    roundMaterials: dict | None = None


@dataclass(frozen=True)
class OwnershipUnavailable:
    """The ownership ledger could not answer.  Never "nothing is owned"."""

    code: str
    detail: str


@dataclass(frozen=True)
class BridgeStatus:
    """What the execution layer knows about the live bridge for THIS operation."""

    available: bool
    levelId: int | None = None
    bridgeRunId: str | None = None
    deadlineUtc: str | None = None
    nativeSceneEnabled: bool | None = None
    reason: str | None = None
    evidenceRef: dict | None = None


@dataclass(frozen=True)
class BridgeUnavailable:
    code: str
    detail: str
    evidenceRef: dict | None = None


class OwnershipProvider(Protocol):
    """DS-08 seam.  Scoped to one round and one level; never a global journal scan."""

    def materials_for_round(self, session: CleanupSession,
                            request_ids: Iterable[str]) -> Any: ...


class CleanupBridge(Protocol):
    """Execution-layer seam.  The only way to reach the two native routes."""

    def status(self) -> Any: ...

    def dispatch(self, op: str, ids: list) -> DispatchResult: ...


@dataclass(frozen=True)
class Judgment:
    """One axis of an independent verification.  ``proven`` needs an evidenceRef."""

    proven: bool
    evidenceRef: dict | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SaveDiffVerdict:
    """DS-05 seam: the four axes of the save that follows a cleanup.

    ``layer`` is the producer's own statement of how it was obtained.  ``pass`` on
    ``cleanup-save-diff`` requires ``layer == "live"``; an offline fixture can therefore
    describe a perfect save and still only reach ``blocked``.
    """

    saveInvocation: Judgment
    savedContent: Judgment
    allowedDelta: Judgment
    unrelatedUnchanged: Judgment
    unrelatedObjectsPreserved: Judgment
    layer: str = "offline"
    producerRef: dict | None = None
    detail: str | None = None


@dataclass(frozen=True)
class VerificationUnavailable:
    code: str
    detail: str


class SaveDiffVerifier(Protocol):
    """DS-05 seam.  ``manifest`` is built by this module from the cleanup evidence."""

    def verify_cleanup_save(self, manifest: dict) -> Any: ...


@dataclass(frozen=True)
class OwnedResource:
    """One auxiliary resource a round created and must release.

    ``ownershipProof`` must resolve on disk (a path + sha256) and ``ownerRoundId`` must
    equal the session's round.  A resource that cannot show both is refused, never
    released "because it is in the list".
    """

    resourceId: str
    kind: str
    locator: str
    ownerRoundId: str | None
    ownershipProof: dict | None = None
    note: str | None = None


class ResourceLedger(Protocol):
    """Execution-layer seam: enumerate THIS round's own auxiliary resources."""

    def own_resources(self, session: CleanupSession) -> Iterable[OwnedResource]: ...


class ResourceReleaser(Protocol):
    """Execution-layer seam: release one resource.  Never reaches outside the roots."""

    def release(self, resource: OwnedResource) -> Any: ...


@dataclass(frozen=True)
class ReleaseOutcome:
    state: str            # released | refused | not-attempted | unknown
    reason: str | None = None
    evidenceRef: dict | None = None


# --------------------------------------------------------------------------- #
# Small evidence helpers
# --------------------------------------------------------------------------- #

def resolve_output_path(raw, root: Path) -> tuple:
    """(target, refusal) for an output file: inside ``root``, new, writable parent.

    The same shape as the reused producer's ``resolve_report_path``, scoped to the
    caller's task run root instead of all of ``.runtime``: a worker may only write inside
    its own task run root (mainline rule), and evidence is never overwritten.
    """
    target = Path(os.path.abspath(raw))
    allowed = Path(os.path.abspath(root))
    try:
        target.relative_to(allowed)
    except ValueError:
        return None, Refusal("OUTPUT_OUTSIDE_TASK_ROOT",
                             "output must live under %s" % allowed, source=str(target))
    if target.exists():
        return None, Refusal("OUTPUT_ALREADY_EXISTS",
                             "refusing to overwrite evidence", source=str(target))
    ancestor = target.parent
    while not ancestor.exists():
        parent = ancestor.parent
        if parent == ancestor:
            break
        ancestor = parent
    if not ancestor.is_dir():
        return None, Refusal("OUTPUT_UNWRITABLE",
                             "%s is not a directory" % ancestor, source=str(target))
    if not os.access(ancestor, os.W_OK):
        return None, Refusal("OUTPUT_UNWRITABLE", "%s is not writable" % ancestor,
                             source=str(target))
    return target, None


def exclusive_write_json(path: Path, payload) -> None:
    """Create ``path`` new; an earlier attempt's evidence is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1, sort_keys=False)
        stream.write("\n")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def refusal_for(refusals, entity_id):
    """The refusal that names this id, or None.  Run-level refusals have no id."""
    for item in refusals:
        if isinstance(item, Refusal) and item.entity_id == entity_id:
            return item
    return None


def evidence_ref(path: Path) -> dict | None:
    """{"path", "sha256"} for a file that exists; None when it does not.

    A verdict is only allowed to cite evidence through this function, so "the file was
    not there" turns into "no evidenceRef", which turns into a non-pass status.
    """
    path = Path(path)
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": sha256_file(path)}


def evidence_ref_resolves(ref) -> bool:
    """Re-hash one evidenceRef.  An unresolvable pointer is not evidence."""
    if not isinstance(ref, dict):
        return False
    path = ref.get("path")
    digest = ref.get("sha256")
    if not isinstance(path, str) or not isinstance(digest, str):
        return False
    candidate = Path(path)
    if not candidate.is_file():
        return False
    try:
        return sha256_file(candidate) == digest
    except OSError:
        return False


def classify_readback_result(result, ids):
    """(ReadbackIds|None, note) for ONE re-read dry-run reply.

    The adapter refuses the WHOLE call when any id fails to resolve
    (``OwnedEntityDelete.cs``: "A single unresolved id refuses the whole call"), so the
    reply to a re-read of a mixed list is that refusal -- and its ``unresolved`` rows ARE
    the read-back: a row with ``matches == 0`` is an id that is no longer in the graph,
    every other requested id still resolves.  ``matches == 2`` means one id resolved to
    two nodes, which is not usable evidence at all.

    This reads a documented field of a reply this project already parses; it does not
    invent a second read path, and it is strictly more information-preserving than
    treating the whole refusal as inconclusive.  It never turns an unreadable reply into
    an absence.
    """
    ids = list(ids)
    if result.launch_error is not None:
        return None, {"performed": True, "trusted": False, "shape": "launch-error",
                      "reason": "launch error: " + result.launch_error}
    if result.reply is None:
        return None, {"performed": True, "trusted": False, "shape": "unreadable",
                      "reason": "exit %d with no readable JSON reply" % result.exit_code}
    reply = result.reply
    if reply.get("ok") is True and reply.get("status") == "dry-run-mapping-only":
        mapping = reply.get("mapping")
        if not isinstance(mapping, list):
            return None, {"performed": True, "trusted": False, "shape": "dry-run-mapping",
                          "reason": "the mapping-only reply carries no mapping list"}
        present = []
        for row in mapping:
            entity_id = co.as_uint(row.get("id")) if isinstance(row, dict) else None
            if entity_id is None:
                return None, {"performed": True, "trusted": False, "shape": "dry-run-mapping",
                              "reason": "a mapping row does not carry a usable id"}
            present.append(entity_id)
        absent = [value for value in ids if value not in present]
        return co.ReadbackIds({value: "resolved" for value in present}), {
            "performed": True, "trusted": True, "shape": "dry-run-mapping",
            "stillExisting": sorted(present), "absent": sorted(absent)}
    if reply.get("ok") is False and reply.get("status") == "refused-unresolved-ids" and \
            reply.get("invoked") is False:
        rows = reply.get("unresolved")
        if not isinstance(rows, list):
            return None, {"performed": True, "trusted": False,
                          "shape": "refused-unresolved-ids",
                          "reason": "the refusal carries no unresolved list"}
        ambiguous, absent = [], []
        for row in rows:
            entity_id = co.as_uint(row.get("id")) if isinstance(row, dict) else None
            if entity_id is None:
                return None, {"performed": True, "trusted": False,
                              "shape": "refused-unresolved-ids",
                              "reason": "an unresolved row does not carry a usable id"}
            if row.get("matches") == 2:
                ambiguous.append(entity_id)
            else:
                absent.append(entity_id)
        if ambiguous:
            return None, {"performed": True, "trusted": False,
                          "shape": "refused-unresolved-ids",
                          "reason": "id(s) %s resolve to more than one node, so the read-back "
                                    "cannot say what is present"
                                    % ",".join(str(value) for value in ambiguous),
                          "ambiguousIds": sorted(ambiguous)}
        present = [value for value in ids if value not in absent]
        return co.ReadbackIds({value: "resolved" for value in present}), {
            "performed": True, "trusted": True, "shape": "refused-unresolved-ids",
            "stillExisting": sorted(present), "absent": sorted(absent),
            "notice": "the refusal lists the ids that no longer resolve; that list is the "
                      "read-back"}
    return None, {"performed": True, "trusted": False, "shape": "unrecognised",
                  "reason": "the reply is neither a mapping nor a resolved/unresolved "
                            "read-back (status=%r)" % reply.get("status")}


def _stage(status: str, *, evidenceRefs=None, reason=None, **fields) -> dict:
    """One stage object in the contract's vocabulary (D9/D10/D11)."""
    payload = {"status": status}
    if status != STAGE_NOT_RUN:
        payload["evidenceRef"] = list(evidenceRefs or [])
        if status != STAGE_PASS:
            payload["reason"] = reason or "no reason recorded"
    else:
        payload["reason"] = reason or "this capability does not perform this stage"
    payload.update(fields)
    return payload


# --------------------------------------------------------------------------- #
# Checkpoint (breakpoint resume / 断点续收)
# --------------------------------------------------------------------------- #

@dataclass
class Checkpoint:
    """Per-id state carried across attempts.  Own file, under the task run root."""

    runId: str
    levelId: int
    requestId: str
    perId: dict = field(default_factory=dict)      # "<levelId>:<entityId>" -> record
    dispatchedBatches: list = field(default_factory=list)
    usedRequestIds: list = field(default_factory=list)
    unknownIds: list = field(default_factory=list)

    SCHEMA = 1

    def to_json(self) -> dict:
        return {"schemaVersion": self.SCHEMA, "tool": "cleanup_service_checkpoint",
                "runId": self.runId, "levelId": self.levelId, "requestId": self.requestId,
                "perId": self.perId, "dispatchedBatches": self.dispatchedBatches,
                "usedRequestIds": self.usedRequestIds, "unknownIds": self.unknownIds}

    @classmethod
    def load(cls, path: Path) -> "Checkpoint":
        document = read_json(path)
        if not isinstance(document, dict) or document.get("schemaVersion") != cls.SCHEMA:
            raise ValueError("CHECKPOINT_SHAPE_UNSUPPORTED")
        return cls(runId=document.get("runId"), levelId=document.get("levelId"),
                   requestId=document.get("requestId"),
                   perId=document.get("perId") or {},
                   dispatchedBatches=document.get("dispatchedBatches") or [],
                   usedRequestIds=document.get("usedRequestIds") or [],
                   unknownIds=document.get("unknownIds") or [])

    def state_of(self, key: str):
        record = self.perId.get(key)
        return record.get("state") if isinstance(record, dict) else None


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #

class CleanupService:
    """One round's cleanup, with the S12 orchestration attached.

    ``bridge`` and ``ownership`` are execution-layer objects.  ``None`` means the caller
    did not supply one, which is a refusal with a named code -- never a silent pass.
    """

    def __init__(self, *, ownership: OwnershipProvider | None = None,
                 bridge: CleanupBridge | None = None,
                 save_diff: SaveDiffVerifier | None = None,
                 resources: ResourceLedger | None = None,
                 releaser: ResourceReleaser | None = None,
                 allowed_material_roots: Iterable[Path] = (EVIDENCE_ROOT,),
                 protected_ids: Iterable[int] = (),
                 evidence_root: Path | None = None):
        self.ownership = ownership
        self.bridge = bridge
        self.save_diff = save_diff
        self.resources = resources
        self.releaser = releaser
        self.allowed_material_roots = tuple(Path(p).resolve() for p in allowed_material_roots)
        self.protected_ids = frozenset(protected_ids)
        # Where this service may write its own evidence.  None means "nowhere": a stage
        # that cannot cite a resolvable evidenceRef is never allowed to report ``pass``
        # (enforced in _finish), so an unconfigured service cannot fake a pass.
        self.evidence_root = Path(evidence_root).resolve() if evidence_root else None

    def _protected_for(self, level_id) -> frozenset:
        """This level's unattributable ids, united with any caller-supplied extra set.

        Resolved PER LEVEL and per call rather than frozen at construction: the service
        is constructed once and then used for a round whose level is only known from the
        session.  The caller's set can only add; it can never remove one of the level's.
        """
        return frozenset(self.protected_ids) | protected_ids_for(level_id)

    # -- entry points ------------------------------------------------------- #

    def cleanup_owned(self, session: CleanupSession, entity_ids, request_id: str,
                      dry_run: bool = True, *, readback=None,
                      checkpoint_path: Path | None = None,
                      resume_from: Path | None = None,
                      output_path: Path | None = None,
                      task_root: Path | None = None) -> dict:
        """The T10 contract: ``cleanup_owned(session, entityIds, requestId, dryRun)``.

        ``dry_run=True`` is the plan: ownership is proven, the mapping is verified, and no
        delete is dispatched.  ``dry_run=False`` is the bounded execution.  Every refusal
        that precedes the first dispatch leaves the queue untouched.
        """
        report = self._blank_report(session, request_id, dry_run, output_path)
        report_target = None
        if output_path is not None:
            report_target, problem = resolve_output_path(
                output_path, Path(task_root) if task_root else RUNTIME_ROOT)
            if problem is not None:
                return self._refuse(report, problem.code, problem.detail)
            report["outputPath"] = str(report_target)
            report["outputRoot"] = str(Path(task_root) if task_root else RUNTIME_ROOT)
        try:
            self._require_request_id(request_id)
        except ValueError as error:
            return self._refuse(report, "REQUEST_ID_INVALID", str(error),
                                target=report_target)
        if checkpoint_path is not None and Path(checkpoint_path).exists():
            problem = self._material_path_problem(Path(checkpoint_path))
            if problem is not None:
                report["checkpoint"] = {"path": str(checkpoint_path), "written": False}
                return self._refuse(report, "CHECKPOINT_PATH_REFUSED", problem.detail,
                                    target=report_target)

        requested = self._normalise_targets(entity_ids)
        if isinstance(requested, Refusal):
            return self._refuse(report, requested.code, requested.detail,
                                target=report_target)
        report["requestedIds"] = requested

        checkpoint = None
        if resume_from is not None:
            try:
                checkpoint = Checkpoint.load(Path(resume_from))
            except (OSError, ValueError) as error:
                return self._refuse(report, "CHECKPOINT_UNREADABLE",
                                    "%s: %s" % (type(error).__name__, error),
                                    target=report_target)
            if checkpoint.levelId != session.levelId:
                return self._refuse(
                    report, "CHECKPOINT_WRONG_LEVEL",
                    "the checkpoint belongs to level %s, this session is level %s"
                    % (checkpoint.levelId, session.levelId), target=report_target)
            report["resumedFrom"] = str(resume_from)

        # The bridge gate.  Executing without one is a refusal; planning without one is a
        # real ownership audit whose mapping is explicitly NOT verified (the same shape
        # cleanup_owned_entities.plan() uses for an offline audit).
        bridge_absent = self.bridge is None
        block = self._bridge_refusal(session)
        # A plan with NO bridge at all degrades to a real ownership audit whose mapping is
        # explicitly unverified.  Anything else -- an execute attempt, or a bridge that is
        # present but unusable or bound elsewhere -- refuses.
        if block is not None and not (dry_run and bridge_absent):
            report["perId"] = self._per_id_all_refused(session, requested, block.code,
                                                       block.detail)
            report["stateCounts"] = _count_states(report["perId"])
            report["stages"]["liveReadback"] = _stage(STAGE_BLOCKED, reason=block.detail,
                                                      refusalCode=block.code)
            return self._refuse(report, block.code, block.detail, target=report_target)
        bridge_ready = block is None
        if block is not None:
            report["bridge"] = {"available": False, "reason": block.detail,
                                "code": block.code}
        else:
            report["bridge"] = {"available": True,
                                "bridgeRunId": getattr(self.bridge.status(), "bridgeRunId", None)}

        owned, refusals = self._resolve_ownership(session, requested, block_report=report)
        if owned is None:
            # Ownership could not be established (not "nothing is owned"): refuse, and do
            # NOT build batches, so no list -- empty or otherwise -- can reach the route.
            report["stateCounts"] = _count_states(report["perId"])
            report["stages"]["cleanup"] = _stage(
                STAGE_BLOCKED, reason="ownership materials unavailable",
                refusalCode=report["refusals"][-1]["code"] if report["refusals"] else None)
            return self._finish(report, EXIT_REFUSED,
                                "ownership could not be established; nothing dispatched",
                                target=report_target)
        report["ownedIds"] = owned
        report["refusals"].extend(item.as_json() for item in refusals)

        if not owned:
            report["batches"] = []
            report["perId"] = self._per_id_settled(session, requested, owned, {}, None,
                                                       report["refusals"])
            report["stateCounts"] = _count_states(report["perId"])
            report["stages"]["cleanup"] = _stage(
                STAGE_BLOCKED, reason="no id passed the three-way ownership proof; "
                                     "nothing was dispatched")
            return self._finish(report, EXIT_REFUSED, "nothing was owned; nothing dispatched",
                                target=report_target)

        # Resume plan BEFORE any dispatch: unknown ids are never re-sent.
        resumable, resumed_notes = self._plan_resume(session, owned, checkpoint)
        report["resume"] = resumed_notes
        if resumed_notes.get("refusal"):
            report["refusals"].append(resumed_notes["refusal"])
        if not resumable:
            report["batches"] = []
            report["perId"] = self._per_id_settled(session, requested, owned, {}, None,
                                                       report["refusals"])
            report["stateCounts"] = _count_states(report["perId"])
            still_unknown = bool(resumed_notes.get("unknownNotResent"))
            if still_unknown:
                report["stages"]["cleanup"] = _stage(
                    STAGE_UNKNOWN, reason="every owned id is already settled or unknown; "
                                          "unknown ids are never re-sent")
                return self._finish(report, EXIT_UNKNOWN,
                                    "unknown outcomes must be reconciled, not re-sent",
                                    target=report_target)
            report["stages"]["cleanup"] = _stage(
                STAGE_NOT_RUN, reason="every owned id was already confirmed deleted in an "
                                      "earlier attempt; nothing was re-sent")
            return self._finish(report, EXIT_CLEAN,
                                "already complete: nothing to do, zero dispatch",
                                target=report_target)

        if not bridge_ready:
            # Offline ownership audit: the proof is real, the mapping is not verified, so
            # this is not a dispatchable plan and it says so.
            report["batches"] = co.build_batches(resumable)[0]
            report["perId"] = self._per_id_settled(session, requested, owned, {}, None,
                                                       report["refusals"])
            report["stateCounts"] = _count_states(report["perId"])
            report["dryRunDetail"] = {
                "performed": False, "mappingVerified": False,
                "note": "no bridge: id -> frontend path uniqueness was NOT verified and this "
                        "plan must not be dispatched as-is"}
            report["deletionReadback"] = {"performed": False,
                                          "reason": "no bridge; nothing was deleted"}
            report["stages"]["liveReadback"] = _stage(
                STAGE_BLOCKED, reason="no bridge, so the live mapping was not verified")
            report["stages"]["cleanup"] = _stage(
                STAGE_NOT_RUN, reason="offline ownership audit only; no delete was dispatched",
                mappingVerified=False)
            report = self._write_checkpoint(report, checkpoint_path, session, request_id,
                                            report["perId"], [], checkpoint)
            return self._finish(report, EXIT_CLEAN,
                                "ownership proven offline; mapping NOT verified and nothing "
                                "was deleted", target=report_target)

        blocks = co.build_batches(resumable)[0]
        report["batches"] = blocks
        mapping, dry_report = self._dry_run(session, blocks, run=not dry_run)
        report["dryRunDetail"] = dry_report
        if mapping is None:
            report["refusals"].append(Refusal(
                dry_report.get("code", "DRY_RUN_REFUSED"),
                dry_report.get("reason", "the dry-run mapping was refused")).as_json())
            report["perId"] = self._per_id_settled(session, requested, owned, {}, None,
                                                       report["refusals"])
            report["stateCounts"] = _count_states(report["perId"])
            report["stages"]["liveReadback"] = _stage(
                STAGE_FAIL, reason=dry_report.get("reason", "dry-run refused"),
                evidenceRefs=_refs(dry_report))
            report["stages"]["cleanup"] = _stage(
                STAGE_NOT_RUN, reason="the mapping was not verified, so no delete was sent")
            return self._finish(report, EXIT_REFUSED,
                                dry_report.get("reason", "dry-run refused"),
                                target=report_target)

        if dry_run:
            report["perId"] = self._per_id_settled(session, requested, owned, {}, None,
                                                       report["refusals"])
            report["stateCounts"] = _count_states(report["perId"])
            report["stages"]["liveReadback"] = _stage(
                STAGE_PASS, evidenceRefs=_refs(dry_report),
                detail="dry-run mapping resolved every owned id to one frontend path")
            report["stages"]["cleanup"] = _stage(
                STAGE_NOT_RUN, reason="dry-run only: no delete was dispatched",
                mappingVerified=True, deleteDispatched=False)
            report["deletionReadback"] = {
                "performed": False,
                "reason": "dry-run only; a verified mapping is not a deletion read-back",
                "mappingVerified": True}
            report = self._write_checkpoint(report, checkpoint_path, session, request_id,
                                            report["perId"], [], checkpoint)
            return self._finish(report, EXIT_CLEAN,
                                "dry-run verified; nothing was deleted", target=report_target)

        ledger, calls, terminal = self._dispatch(session, blocks, mapping, report)
        readback, readback_note = self._readback(session, requested, owned, ledger,
                                                 readback=readback, run=True)
        report["deletionReadback"] = readback_note
        per_id = self._per_id_settled(session, requested, owned, ledger, readback,
                                      report["refusals"])
        report["perId"] = per_id
        report["stateCounts"] = _count_states(per_id)
        ref = self._write_readback_evidence(session, per_id, readback_note)
        if ref is not None:
            readback_note["evidenceRef"] = ref
        report["deletionReadback"] = readback_note
        report["residual"] = {
            "ids": sorted(row["entityId"] for row in per_id.values()
                          if row["state"] != STATE_DELETED and row["owned"]),
            "ownershipChecked": True,
            "note": "ids that are owned AND not confirmed deleted; each was intersected "
                    "with this round's owned set",
        }
        pending_unknown = sorted(row["entityId"] for row in per_id.values()
                                 if row["state"] == STATE_UNKNOWN and row["owned"])
        report["pending"] = {
            "unknownIds": pending_unknown,
            "openRequestIds": [request_id] if pending_unknown else [],
            "note": "an unknown outcome is reconciled from evidence, never re-sent",
        }
        if report["residual"]["ids"]:
            residual_ids = report["residual"]["ids"]
            report["newOperation"] = {
                "requestId": uuid.uuid4().hex,
                "op": DELETE_OP, "dryRunOp": DRY_OP,
                "ids": residual_ids,
                "batches": [residual_ids[i:i + MAX_IDS_PER_CALL]
                            for i in range(0, len(residual_ids), MAX_IDS_PER_CALL)],
                "automaticDispatch": False,
                "requiresOperatorDispatch": True,
                "ownershipCheck": "intersected with this round's owned set",
                "note": "a NEW request, never a resend of the list this run already used",
            }
        report = self._write_checkpoint(report, checkpoint_path, session, request_id,
                                        per_id, calls, checkpoint)

        if terminal == EXIT_UNKNOWN or not readback_note.get("trusted") or pending_unknown:
            # An unknown outcome stops the run's own verdict: it is reconciled from
            # evidence, never reported as an ordinary partial success.
            report["stages"]["cleanup"] = _stage(
                STAGE_UNKNOWN, evidenceRefs=_refs(readback_note),
                reason="the outcome of at least one dispatched id could not be established")
            return self._finish(report, EXIT_UNKNOWN,
                                "outcome unknown; stop and reconcile", target=report_target)
        if report["residual"]["ids"]:
            report["stages"]["cleanup"] = _stage(
                STAGE_FAIL, evidenceRefs=_refs(readback_note),
                reason="owned ids remain after the dispatch and a fresh read-back")
            return self._finish(report, EXIT_PARTIAL, "partial: owned ids remain",
                                target=report_target)
        report["stages"]["cleanup"] = _stage(
            STAGE_PASS, evidenceRefs=_refs(readback_note),
            reason=None, detail="every owned id is absent from a trusted fresh read-back")
        return self._finish(report, EXIT_CLEAN, "all owned ids are gone", target=report_target)

    # -- pre-dispatch refusals --------------------------------------------- #

    def _bridge_refusal(self, session) -> Refusal | None:
        """Everything about the live bridge that must be decided while NOTHING is sent."""
        if self.bridge is None:
            return Refusal("CLEANUP_BRIDGE_UNAVAILABLE",
                           "no execution-layer bridge was supplied, so neither the "
                           "read-only mapping nor the delete route can be reached")
        try:
            status = self.bridge.status()
        except Exception as error:                                # noqa: BLE001
            return Refusal("CLEANUP_BRIDGE_UNAVAILABLE",
                           "the bridge status could not be read: %s: %s"
                           % (type(error).__name__, error))
        if isinstance(status, BridgeUnavailable):
            return Refusal(status.code or "CLEANUP_BRIDGE_UNAVAILABLE", status.detail)
        if not isinstance(status, BridgeStatus):
            return Refusal("CLEANUP_BRIDGE_UNAVAILABLE",
                           "the bridge status has an unrecognised shape")
        if not status.available:
            return Refusal("CLEANUP_BRIDGE_UNAVAILABLE",
                           status.reason or "the bridge reports itself unavailable")
        if status.levelId is not None and status.levelId != session.levelId:
            return Refusal("CLEANUP_BRIDGE_WRONG_LEVEL",
                           "the live bridge is bound to level %s, the session is %s"
                           % (status.levelId, session.levelId))
        if session.bridgeRunId and status.bridgeRunId and \
                session.bridgeRunId != status.bridgeRunId:
            return Refusal("CLEANUP_BRIDGE_RUN_MISMATCH",
                           "the session names bridge run %s but the live bridge is %s"
                           % (session.bridgeRunId, status.bridgeRunId))
        return None

    def _normalise_targets(self, entity_ids):
        if entity_ids is None:
            return Refusal("CLEANUP_IDS_EMPTY", "no entity id list was supplied")
        try:
            values = list(entity_ids)
        except TypeError:
            return Refusal("CLEANUP_IDS_NOT_UINT32", "the id list is not iterable")
        if not values:
            return Refusal("CLEANUP_IDS_EMPTY",
                           "an empty id list is refused, never dispatched: it cannot be told "
                           "apart from a list that failed to be obtained")
        normalised = []
        for value in values:
            parsed = co.as_uint(value)
            if parsed is None:
                return Refusal("CLEANUP_IDS_NOT_UINT32",
                               "%r is not a nonzero uint32 id" % (value,))
            if parsed not in normalised:
                normalised.append(parsed)
        return normalised

    # -- ownership ---------------------------------------------------------- #

    def _resolve_ownership(self, session, requested, *, block_report):
        """(owned, refusals) or (None, refusals) when the materials are unavailable."""
        if self.ownership is None:
            block_report["refusals"].append(Refusal(
                "OWNERSHIP_MATERIALS_UNAVAILABLE",
                "no ownership provider is wired, so this round's create receipts and "
                "baselines cannot be obtained; refusing rather than treating 'no ids "
                "obtained' as 'nothing is owned'").as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "OWNERSHIP_MATERIALS_UNAVAILABLE",
                "ownership materials could not be obtained")
            return None, []
        try:
            materials = self.ownership.materials_for_round(session, [])
        except Exception as error:                                # noqa: BLE001
            block_report["refusals"].append(Refusal(
                "OWNERSHIP_MATERIALS_UNAVAILABLE",
                "the ownership provider raised: %s: %s" % (type(error).__name__, error)).as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "OWNERSHIP_MATERIALS_UNAVAILABLE",
                "ownership materials could not be obtained")
            return None, []
        if isinstance(materials, OwnershipUnavailable):
            block_report["refusals"].append(Refusal(
                materials.code, materials.detail).as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, materials.code, materials.detail)
            return None, []
        if not isinstance(materials, OwnershipMaterials):
            block_report["refusals"].append(Refusal(
                "OWNERSHIP_MATERIALS_UNAVAILABLE",
                "the ownership provider returned an unrecognised shape").as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "OWNERSHIP_MATERIALS_UNAVAILABLE",
                "ownership materials could not be obtained")
            return None, []
        if materials.levelId != session.levelId:
            block_report["refusals"].append(Refusal(
                "OWNERSHIP_MATERIALS_WRONG_LEVEL",
                "the ownership materials are for level %s, the session is %s"
                % (materials.levelId, session.levelId)).as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "OWNERSHIP_MATERIALS_WRONG_LEVEL",
                "ownership materials are for another level")
            return None, []
        for path in list(materials.receipts) + \
                [p for p in (materials.preBaseline, materials.currentBaseline) if p]:
            problem = self._material_path_problem(path)
            if problem is not None:
                block_report["refusals"].append(problem.as_json())
                block_report["perId"] = self._per_id_all_refused(
                    session, requested, problem.code, problem.detail)
                return None, []
        block_report["ownershipMaterials"] = {
            "levelId": materials.levelId,
            "receipts": [str(p) for p in materials.receipts],
            "preBaseline": str(materials.preBaseline) if materials.preBaseline else None,
            "currentBaseline": str(materials.currentBaseline),
            "source": materials.source,
            "digest": materials.digest,
            "receiptSha256": [_safe_hash(p) for p in materials.receipts],
            "currentBaselineSha256": _safe_hash(materials.currentBaseline),
        }
        # F-011 LEGS.  The three-way proof below proves CONSISTENCY of the materials it is
        # handed; it cannot show "this round added this object", and its receipt reader
        # cannot see the templateId at all -- the real create receipt keeps the entityId in
        # the author journal's result.json and the template in the sibling claim.json, so
        # `co.load_receipts` alone yields RECEIPT_TEMPLATE_ID_MISSING for every real id.
        # The legs own the receipt normalisation, the baseline difference, the round window
        # and the receipt provenance, and they are REQUIRED: without them this method
        # refuses rather than falling back to the proof alone.
        if materials.roundMaterials is None:
            block_report["refusals"].append(Refusal(
                "CLEANUP_LEGS_MATERIALS_REQUIRED",
                "the ownership materials carry no round materials (round window, pre-create "
                "baseline, pre-cleanup complete read-back, receipt provenance), so 'new this "
                "round' cannot be shown; refusing rather than using the three-way proof "
                "alone").as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "CLEANUP_LEGS_MATERIALS_REQUIRED",
                "the round materials are required to show what this round added")
            return None, []
        legs_manifest = dict(materials.roundMaterials)
        legs_manifest["candidates"] = list(requested)
        legs_report = ownership_legs.judge(legs_manifest)
        if legs_report.get("status") != "judged":
            undecidable = sorted({row.get("code")
                                  for row in legs_report.get("runRefusals") or []
                                  if row.get("code")})
            block_report["refusals"].append(Refusal(
                "CLEANUP_OWNERSHIP_UNDECIDABLE",
                "the round's own ownership legs refused it (%s), so what is present now is "
                "unknown and nothing may be owned" % ",".join(undecidable)).as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "CLEANUP_OWNERSHIP_UNDECIDABLE",
                "the pre-cleanup read-back, baseline or window could not be used")
            return None, []
        normalised, normalised_refusals = ownership_legs.load_fresh_readback(
            Path(materials.currentBaseline))
        if normalised is None:
            block_report["refusals"].append(Refusal(
                "CLEANUP_READBACK_NOT_UNDERSTOOD",
                "the pre-cleanup read-back could not be read as an entity set: %s"
                % ",".join(sorted({item.code for item in normalised_refusals}))).as_json())
            block_report["perId"] = self._per_id_all_refused(
                session, requested, "CLEANUP_READBACK_NOT_UNDERSTOOD",
                "the read-back could not be read as an entity set")
            return None, []
        claims, _legs_meta, claim_refusals = ownership_legs.load_provenance_receipts(
            materials.roundMaterials.get("receipts") or [])
        if not materials.receipts:
            claim_refusals = list(claim_refusals) + [Refusal(
                "RECEIPTS_REQUIRED", "this round supplied no create receipt at all")]
        # The template key the native snapshot actually writes is ``configId``; the proof
        # below compares against this normalised map, not against a re-read of the file.
        current = dict(normalised.entries)
        # The normaliser is keyed by id, so a read-back that names the same object twice
        # would COLLAPSE silently -- a tamperer can hide a duplicate by writing the distinct
        # count as ``entityCount``, which keeps the truncation check satisfied.  Keep the
        # reused producer's duplicate / unparseable-entry refusal alive for it (recorded,
        # not round-blocking, exactly as the pre-F-011 ``co.load_baseline`` call behaved).
        # Templates are deliberately NOT required: the native snapshot carries them as
        # ``configId``, so ``require_template=True`` would refuse every real read-back.
        _current_ids, current_refusals = co.load_baseline(materials.currentBaseline,
                                                          require_template=False)
        block_report["ownershipLegs"] = {
            "legVersion": legs_report.get("legVersion"),
            "readback": legs_report.get("readback"),
            "difference": {key: value
                           for key, value in (legs_report.get("difference") or {}).items()
                           if key != "addedIds"},
            "normalisedTemplates": sum(1 for value in current.values() if value is not None),
        }
        previous = None
        previous_refusals = []
        if materials.preBaseline is not None:
            loaded, previous_refusals = co.load_baseline(materials.preBaseline,
                                                         require_template=False)
            previous = set(loaded)
        owned, ownership_refusals = co.prove_ownership(claims, current, previous,
                                                       session.levelId)
        refusals = list(claim_refusals) + list(current_refusals) + \
            list(previous_refusals) + list(ownership_refusals)
        # F-011: the legs are the authority; the three-way proof stays as a consistency
        # check and can only NARROW the owned set, never widen it.  An id that any leg
        # refused is dropped even if the proof would have granted it, and the leg's own
        # reason is carried into the per-id refusal.  This runs AFTER the DS-08 ledger
        # carry-over below so the ledger's own, more specific reason for an id it already
        # refused is not shadowed by the legs' generic "not owned by this run".
        owned_set = set(owned)
        # The requested list is the caller's; the owned set is the proof's.  What the
        # caller asked for and the proof did not grant is refused BY NAME.
        owned_set = set(owned)
        # The three unattributable ids are removed from the owned set UNCONDITIONALLY.  A
        # forged-but-self-consistent receipt set can satisfy the three-way proof (that is
        # exactly what the proof checks), so the freeze cannot be a by-product of the
        # proof -- it has to be an explicit subtraction.
        protected = self._protected_for(session.levelId)
        protected_hits = [entity_id for entity_id in owned_set
                          if entity_id in protected]
        owned_set -= protected
        for entity_id in protected_hits:
            refusals.append(Refusal(
                "CLEANUP_TARGET_UNATTRIBUTABLE",
                "id %d is one of the ids 2026-09-30 could not attribute; it has no create "
                "receipt and may be pre-existing content, so it is removed from the owned set "
                "even when a supplied receipt set would satisfy the three-way proof"
                % entity_id, entity_id=entity_id))
        if isinstance(materials.ledgerQuery, dict):
            # The DS-08 ledger already answered for some ids; its answer is carried, not
            # re-derived, and its refusals are never widened here.
            for key in ("refused", "unknown"):
                for row in materials.ledgerQuery.get(key) or []:
                    if not isinstance(row, dict):
                        continue
                    entity_id = co.as_uint(row.get("entityId"))
                    if entity_id is None or entity_id in owned_set:
                        continue
                    if refusal_for(refusals, entity_id) is None:
                        refusals.append(Refusal(
                            row.get("code") or "OWNERSHIP_LEDGER_UNKNOWN",
                            row.get("reason") or "the ownership ledger could not attribute this id",
                            entity_id=entity_id))
            block_report["ownershipQuery"] = {
                "levelId": materials.ledgerQuery.get("levelId"),
                "ownedCount": len(materials.ledgerQuery.get("owned") or []),
                "refusedIds": [row.get("entityId")
                               for row in materials.ledgerQuery.get("refused") or []
                               if isinstance(row, dict)],
                "unknownIds": [row.get("entityId")
                               for row in materials.ledgerQuery.get("unknown") or []
                               if isinstance(row, dict)],
            }
        # F-011: the legs narrow the proof's owned set, after the ledger's own refusals
        # have had their say (see the note above).
        narrowed = set(owned) & set(legs_report["ownedIds"])
        for row in legs_report["perId"].values():
            entity_id = row["entityId"]
            if entity_id in narrowed or refusal_for(refusals, entity_id) is not None:
                continue
            refusals.append(Refusal(
                row.get("subState") or "CLEANUP_LEG_REFUSED",
                row.get("reason") or "a cleanup ownership leg refused this id",
                entity_id=entity_id))
        owned = sorted(narrowed)
        owned_set = set(owned)
        for entity_id in requested:
            if entity_id in owned_set:
                continue
            if entity_id in protected:
                if refusal_for(refusals, entity_id) is None:
                    refusals.append(Refusal(
                        "CLEANUP_TARGET_UNATTRIBUTABLE",
                        "id %d is one of the ids 2026-09-30 could not attribute; it has no "
                        "create receipt and may be pre-existing content, so it stays untouched"
                        % entity_id, entity_id=entity_id))
                continue
            named = refusal_for(refusals, entity_id)
            if named is None:
                refusals.append(Refusal(
                    "CLEANUP_ID_NOT_OWNED_BY_THIS_RUN",
                    "id %d did not pass the three-way ownership proof (this round's receipt "
                    "/ new since the pre-create baseline / present now with the same "
                    "template)" % entity_id, entity_id=entity_id))
        return sorted(owned_set), refusals

    # -- dry-run / dispatch ------------------------------------------------- #

    def _dry_run(self, session, blocks, *, run: bool):
        """Mapping per batch.  Returns (mapping|None, detail).

        The identity of the mapping is verified on EVERY run, including the mutating one:
        the delete route re-resolves each node path, so a mapping that was not checked
        against this exact call would let a moved object be deleted under an old name.
        """
        mapping = {}
        entries = []
        for index, batch in enumerate(blocks):
            result = self.bridge.dispatch(DRY_OP, list(batch))
            paths, refusal = co.classify_dry_run(result, list(batch))
            entry = {"batchIndex": index, "ids": list(batch), "exitCode": result.exit_code,
                     "argvTail": result.argv_tail,
                     "status": (result.reply or {}).get("status")}
            if refusal is not None:
                entry["refusal"] = refusal.as_json()
                entries.append(entry)
                return None, {"performed": True, "batches": entries, "mappingVerified": False,
                              "code": refusal.code,
                              "reason": "%s: %s" % (refusal.code, refusal.detail)}
            entry["mapping"] = [{"id": key, "frontendPath": paths[key]}
                                for key in sorted(paths)]
            entries.append(entry)
            mapping.update(paths)
        path = self._write_dry_run_evidence(session, entries)
        ref = evidence_ref(path) if path else None
        return mapping, {"performed": True, "batches": entries, "mappingVerified": True,
                         "dispatchKind": "execute" if run else "plan",
                         "evidenceRef": ref}

    def _dispatch(self, session, blocks, mapping, report):
        """One delete per batch, once.  Returns (ledger, calls, terminal_exit|None)."""
        ledger = {}
        calls = []
        dispatched = set()
        for index, batch in enumerate(blocks):
            key = tuple(batch)
            if key in dispatched:
                report["refusals"].append(Refusal(
                    "EXECUTE_BATCH_ALREADY_DISPATCHED",
                    "batch %d was already dispatched" % index).as_json())
                break
            dispatched.add(key)
            result = self.bridge.dispatch(DELETE_OP, list(batch))
            entry = {"op": DELETE_OP, "batchIndex": index, "ids": list(batch),
                     "exitCode": result.exit_code, "argvTail": result.argv_tail,
                     "status": (result.reply or {}).get("status")}
            detail = {}
            rows, refusal, unknown, warnings = co.classify_execute(result, list(batch),
                                                                   mapping, detail)
            if detail.get("rows"):
                entry["results"] = detail["rows"]
            if detail.get("pathMismatches"):
                entry["frontendPathMismatches"] = detail["pathMismatches"]
            if refusal is not None:
                entry["refusal"] = refusal.as_json()
            if warnings:
                entry["warnings"] = warnings
            if isinstance(result.reply, dict) and "notice" in result.reply:
                entry["notice"] = result.reply["notice"]
            if rows:
                entry["ledger"] = rows
                ledger.update(rows)
            calls.append(entry)
            report["dispatch"] = {"performed": True, "calls": calls}
            if unknown is not None:
                entry["outcomeUnknown"] = unknown
                # The batch that WAS dispatched is unknown, not "not attempted".  The
                # reused producer marks the whole list not-attempted here; that reads as
                # "nothing was sent for these ids", which would make a resume re-send a
                # batch whose outcome is unreadable.  Stricter on purpose.
                for entity_id in batch:
                    ledger.setdefault(entity_id, "dispatched:reply-unreadable")
                for later in blocks[index + 1:]:
                    for entity_id in later:
                        ledger.setdefault(entity_id, "not-attempted:prior-unknown-outcome")
                return ledger, calls, EXIT_UNKNOWN
            if refusal is not None:
                return ledger, calls, EXIT_REFUSED
        return ledger, calls, None

    def _readback(self, session, requested, owned, ledger, *, readback, run: bool):
        """(ReadbackIds|None, note).  Trusted-and-performed is what "deleted" needs."""
        owned_set = set(owned)
        if readback is not None:
            evidence = co.as_readback_evidence(readback)
            foreign = sorted(set(evidence) - owned_set)
            note = {"performed": True, "source": "supplied-evidence",
                    "shape": evidence.shape, "trusted": bool(evidence.trusted) and not foreign,
                    "stillExisting": sorted(evidence),
                    "foreignIds": foreign,
                    "ownershipCheck": "intersected with this round's owned set"}
            if foreign:
                note["reason"] = ("the supplied re-read names ids this round does not own; "
                                  "they are dropped and the read-back is not treated as "
                                  "trusted")
            return evidence, note
        if not run or self.bridge is None:
            return None, {"performed": False, "trusted": False,
                          "reason": "no fresh read-back evidence"}
        candidates = sorted(set(ledger))
        if not candidates:
            return None, {"performed": False, "trusted": False,
                          "reason": "no id reached the dispatch stage"}
        still = []
        absent = []
        for start in range(0, len(candidates), MAX_IDS_PER_CALL):
            batch = candidates[start:start + MAX_IDS_PER_CALL]
            result = self.bridge.dispatch(DRY_OP, list(batch))
            evidence, note = classify_readback_result(result, list(batch))
            if evidence is None:
                note.update({"performed": True, "source": "dry-run re-read",
                             "trusted": False})
                return None, note
            still.extend(evidence)
            absent.extend(note.get("absent") or [])
        foreign = sorted(set(still) - owned_set)
        note = {"performed": True, "source": "dry-run re-read", "shape": "dry-run re-read",
                "trusted": not foreign, "stillExisting": sorted(still),
                "absent": sorted(set(absent)), "foreignIds": foreign,
                "ownershipCheck": "intersected with this round's owned set"}
        if foreign:
            note["reason"] = ("the re-read resolved ids this round does not own, so the "
                              "residual cannot be stated from this evidence")
            return None, note
        return co.ReadbackIds({value: "resolved" for value in still}), note

    # -- per-id projection -------------------------------------------------- #

    def _per_id_settled(self, session, requested, owned, ledger, readback,
                        refusals=None) -> dict:
        """Per-id projection.  ``owned`` is the proof's set; the caller's list is not."""
        per_id = {}
        owned_set = set(owned)
        by_id = {}
        for row in refusals or []:
            if isinstance(row, dict) and row.get("entityId") is not None:
                by_id.setdefault(row["entityId"], row)
        for entity_id in requested:
            key = session.key(entity_id)
            is_owned = entity_id in owned_set
            if not is_owned:
                named = by_id.get(entity_id) or {}
                per_id[key] = {"levelId": session.levelId, "entityId": entity_id,
                               "owned": False, "state": STATE_REFUSED,
                               "subState": named.get("code") or "not-owned",
                               "reason": named.get("detail")
                                         or "did not pass the three-way ownership proof"}
                continue
            transport = ledger.get(entity_id)
            per_id[key] = self._project_owned(session, entity_id, transport, readback)
        return per_id

    @staticmethod
    def _project_owned(session, entity_id, transport, readback) -> dict:
        row = {"levelId": session.levelId, "entityId": entity_id, "owned": True,
               "transport": transport}
        if transport is None:
            row.update(state=STATE_NOT_ATTEMPTED, subState="not-dispatched",
                       reason="no delete was dispatched for this id")
            return row
        if transport == "not-dispatched:list-refused":
            row.update(state=STATE_REFUSED, subState=transport,
                       reason="the adapter refused the whole batch before invoking anything")
            return row
        if transport == "not-dispatched:target-changed":
            row.update(state=STATE_REFUSED, subState=transport,
                       reason="the adapter's pre-delete re-check found the target changed")
            return row
        if transport.startswith("not-attempted"):
            row.update(state=STATE_NOT_ATTEMPTED, subState=transport,
                       reason="the batch was never sent")
            return row
        # dispatched / dispatched:threw-native / dispatched:path-mismatch
        performed = bool(readback is not None and getattr(readback, "trusted", False))
        if not performed:
            row.update(state=STATE_UNKNOWN, subState=transport,
                       reason="dispatched, but no trusted fresh read-back establishes "
                              "whether the object is gone")
            return row
        if entity_id in readback:
            row.update(state=STATE_UNKNOWN, subState="dispatched:still-present",
                       reason="dispatched, but a fresh independent read-back still resolves "
                              "the id; the adapter reports dispatch only, and ids are reused "
                              "across levels, so this is not a resend candidate")
            return row
        row.update(state=STATE_DELETED, subState="%s+readback-absent" % transport,
                   reason=None)
        return row

    def _per_id_all_refused(self, session, requested, code, detail) -> dict:
        return {session.key(entity_id): {
            "levelId": session.levelId, "entityId": entity_id, "owned": False,
            "state": STATE_REFUSED, "subState": code, "reason": detail}
            for entity_id in requested}

    # -- resume ------------------------------------------------------------- #

    def _plan_resume(self, session, owned, checkpoint) -> tuple:
        if checkpoint is None:
            return list(owned), {"resumed": False, "unknownNotResent": [],
                                 "settledSkipped": [], "note": "no checkpoint supplied"}
        resumable = []
        settled = []
        unknown = []
        held_back = []
        for entity_id in owned:
            key = session.key(entity_id)
            state = checkpoint.state_of(key)
            if state == STATE_DELETED:
                settled.append(entity_id)
            elif state == STATE_UNKNOWN:
                unknown.append(entity_id)
            elif state == STATE_REFUSED:
                held_back.append(entity_id)
            else:
                # never recorded, or not-attempted: only these are re-dispatched
                resumable.append(entity_id)
        note = {
            "resumed": True,
            "settledSkipped": settled,
            "unknownNotResent": unknown,
            "refusedHeldBack": held_back,
            "newRequestId": checkpoint.requestId is not None,
            "note": "ids already deleted are skipped; ids whose outcome is unknown or refused "
                    "are never re-sent automatically; only ids that were never dispatched may "
                    "be dispatched again, under a new request id",
        }
        if unknown:
            note["refusal"] = Refusal(
                "RESUME_UNKNOWN_NOT_RESENT",
                "id(s) %s already have an unknown outcome and must be reconciled from "
                "evidence before any further dispatch"
                % ",".join(str(v) for v in unknown)).as_json()
        return resumable, note

    # -- evidence bookkeeping ---------------------------------------------- #

    def _blank_report(self, session, request_id, dry_run, output_path) -> dict:
        return {
            "tool": "cleanup_service",
            "schemaVersion": MODULE_VERSION,
            "contractVersion": CONTRACT_VERSION,
            "runId": session.roundId,
            "requestId": request_id,
            "levelId": session.levelId,
            "levelHandleDigest": session.levelHandleDigest,
            "session": {"levelId": session.levelId, "bridgeRunId": session.bridgeRunId,
                        "sessionIdentity": session.sessionIdentity,
                        "roundId": session.roundId},
            "mode": "plan" if dry_run else "execute",
            "dryRun": bool(dry_run),
            "requestedIds": [],
            "ownedIds": [],
            "perId": {},
            "stateCounts": {state: 0 for state in PER_ID_STATES},
            "refusals": [],
            "batches": [],
            "dispatch": {"performed": False, "calls": []},
            "deletionReadback": {"performed": False, "reason": "not reached"},
            "residual": {"ids": [], "ownershipChecked": False},
            "pending": {"unknownIds": [], "openRequestIds": []},
            "newOperation": None,
            "stages": {name: _stage(STAGE_NOT_RUN) for name in STAGE_NAMES},
            "outputPath": str(output_path) if output_path else None,
            "outputPersisted": False,
            "producerHashes": producer_hashes(),
            "verifiedLayer": "offline",
            "gameEffectVerified": False,
            "persistenceVerified": False,
            "atomicity": "none; the native route can stop early, so only the per-id states "
                         "are evidence",
            "exitCode": EXIT_REFUSED,
        }

    def _finish(self, report, exit_code, note, *, target: Path | None = None) -> dict:
        """Set the terminal verdict; persist it when an output path was preflighted.

        A write that fails AFTER a dispatch is deliberately not the usage code: the run
        happened, so the complete report is printed and ``EXIT_EVIDENCE_UNWRITTEN`` says
        exactly that.  A failure before the dispatch never reaches here -- the output path
        is preflighted first, so exit 3 keeps meaning "nothing was sent".
        """
        report["exitCode"] = exit_code
        report["statusBasis"] = note
        report["stages"].setdefault("saveDiff", _stage(
            STAGE_NOT_RUN, reason="the save that follows a cleanup is verified by DS-05, not here"))
        report["stages"]["reopen"] = _stage(
            STAGE_NOT_RUN, reason="a reopen is executed by the mainline T11 entry point")
        report["stages"]["runtime"] = _stage(
            STAGE_NOT_RUN, reason="this capability does not observe a playtest run")
        # STAGE-1 enforcement (G01): a pass must be backed by a resolvable evidenceRef.
        # A claim that cannot cite evidence is downgraded, never published as a pass.
        for name, stage in report["stages"].items():
            if stage.get("status") != STAGE_PASS:
                continue
            refs = stage.get("evidenceRef") or []
            if not refs or any(not evidence_ref_resolves(ref) for ref in refs):
                stage["status"] = STAGE_BLOCKED
                stage["reason"] = ("this stage claimed pass without a resolvable evidence "
                                   "pointer (%s)"
                                   % ("none cited" if not refs else "some did not resolve"))
        for name, stage in report["stages"].items():
            if stage.get("status") in (STAGE_FAIL, STAGE_UNKNOWN) and \
                    not (stage.get("evidenceRef") or []):
                # The stage ran; the report itself is the evidence, but no pointer could be
                # written (no evidence root configured, or the evidence write failed).  That
                # is recorded rather than dressed up as a cited verdict.
                stage["evidenceIncomplete"] = True
        if target is None:
            return report
        report["outputPersisted"] = True
        try:
            exclusive_write_json(Path(target), report)
        except OSError as error:
            report["outputPersisted"] = False
            report["outputError"] = "%s: %s" % (type(error).__name__, error)
            print(json.dumps(report, ensure_ascii=False, indent=1))
            print(json.dumps(Refusal(
                "OUTPUT_WRITE_FAILED",
                "the run reached its verdict but the report could not be written to %s"
                % target).as_json(), ensure_ascii=False))
            report["exitCode"] = EXIT_EVIDENCE_UNWRITTEN
        return report

    def _refuse(self, report, code, detail, *, target: Path | None = None) -> dict:
        """A refusal decided before the first dispatch: the cleanup stage never ran.

        ``blocked`` (not ``fail``) is the contract's word for "cannot proceed for a named
        external reason": ``fail`` would claim the stage ran and did not meet its criterion.
        """
        report["refusals"].append(Refusal(code, detail).as_json())
        report["stateCounts"] = _count_states(report["perId"])
        report["stages"]["cleanup"] = _stage(STAGE_BLOCKED, reason=detail, refusalCode=code)
        return self._finish(report, EXIT_REFUSED,
                            "refused before any dispatch: %s" % code, target=target)

    def _write_dry_run_evidence(self, session, entries) -> Path | None:
        """The mapping is evidence, so it is written before the delete can use it.

        Written under the caller's own evidence root; when none was configured the mapping
        stays unverified-by-evidence, which the stage guard turns into a non-pass instead of
        an unsupported claim.
        """
        if self.evidence_root is None:
            return None
        try:
            root = self.evidence_root / "dry-run" / (session.roundId or "no-round")
            root.mkdir(parents=True, exist_ok=True)
            path = root / ("mapping-%s-%s.json" % (session.levelId, uuid.uuid4().hex[:12]))
            exclusive_write_json(path, {"kind": "cleanup-dry-run-mapping", "schemaVersion": 1,
                                        "levelId": session.levelId,
                                        "roundId": session.roundId, "batches": entries})
            return path
        except OSError:
            return None

    def _write_readback_evidence(self, session, per_id, readback_note):
        """Persist the per-id outcome + the read-back so a pass can cite real bytes."""
        if self.evidence_root is None:
            return None
        try:
            root = self.evidence_root / "deletion-readback" / (session.roundId or "no-round")
            root.mkdir(parents=True, exist_ok=True)
            path = root / ("readback-%s.json" % uuid.uuid4().hex[:12])
            exclusive_write_json(path, {
                "kind": "cleanup-deletion-readback", "schemaVersion": 1,
                "levelId": session.levelId, "roundId": session.roundId,
                "perId": per_id,
                "readback": {key: value for key, value in readback_note.items()
                             if key != "evidenceRef"},
                "note": "this document is the evidence a cleanup stage pass cites; it holds "
                        "the per-id transport outcome and the fresh read-back",
            })
            return evidence_ref(path)
        except OSError:
            return None

    def _write_checkpoint(self, report, path, session, request_id, per_id, calls,
                          previous) -> dict:
        if path is None:
            return report
        used = list(previous.usedRequestIds) if previous else []
        if request_id not in used:
            used.append(request_id)
        unknown = sorted(row["entityId"] for row in per_id.values()
                         if row["state"] == STATE_UNKNOWN and row["owned"])
        checkpoint = Checkpoint(
            runId=session.roundId, levelId=session.levelId, requestId=request_id,
            perId={key: {"state": row["state"], "subState": row["subState"],
                         "entityId": row["entityId"], "owned": row["owned"]}
                   for key, row in per_id.items()},
            dispatchedBatches=[entry["ids"] for entry in calls if entry.get("op") == DELETE_OP],
            usedRequestIds=used, unknownIds=unknown)
        entry = {"path": str(path), "written": False}
        report["checkpoint"] = entry
        try:
            exclusive_write_json(Path(path), checkpoint.to_json())
        except OSError as error:
            entry["error"] = "%s: %s" % (type(error).__name__, error)
            entry["refusal"] = Refusal(
                "CHECKPOINT_WRITE_FAILED",
                "the run reached its verdict but the checkpoint could not be written").as_json()
            return report
        entry["written"] = True
        return report

    # -- path guards -------------------------------------------------------- #

    def _material_path_problem(self, path) -> Refusal | None:
        """Receipts and baselines must come from an allowed root, and must be files."""
        candidate = Path(os.path.abspath(path))
        for root in self.allowed_material_roots:
            try:
                candidate.relative_to(root)
                break
            except ValueError:
                continue
        else:
            return Refusal("MATERIAL_PATH_NOT_ALLOWED",
                           "%s is outside the execution layer's allowed roots" % candidate,
                           source=str(candidate))
        if not candidate.is_file():
            return Refusal("MATERIAL_PATH_MISSING",
                           "%s does not exist" % candidate, source=str(candidate))
        return None

    def _checkpoint_path_problem(self, path) -> Refusal | None:
        return self._material_path_problem(path) if Path(path).exists() else None

    @staticmethod
    def _require_request_id(value):
        if not isinstance(value, str) or not value or len(value) > 80 or \
                not value[0].isalnum() or \
                not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError("requestId must be 1..80 letters, digits, underscore or hyphen")

    # -- S12 orchestration -------------------------------------------------- #

    def orchestrate_s12(self, session, report: dict, *, resources_report=None,
                        output_root: Path | None = None, save_case_files=None,
                        case_request_id: str | None = None) -> dict:
        """Build the three S12 evidence documents that have no producer yet.

        ``save_case_files`` is the caller's binding of the save case (the same
        ``{name: {path, sha256}}`` map DS-05's manifest uses).  It is what lets the
        save-diff document derive its layer from real bytes instead of from a declaration.

        ``case_request_id`` is the save case's own request identity, threaded in so the
        bundle's three documents and the directory they are written under carry the SAME
        run/case identity the projection checks.  It is not a verdict: it is a name.  The
        documents are written under ``<output_root>/<layer>/<name>/<name>.json`` where
        ``<layer>`` comes from :func:`s12_output_layer`, so a real old run cannot be
        overwritten by (or mistaken for) a new one that was handed the same root.
        """
        docs = {
            "cleanup-save-diff": self._cleanup_save_diff(session, report,
                                                         save_case_files=save_case_files),
            "cleanup-reopen": self._cleanup_reopen(session, report),
            "resource-cleanup": self._resource_cleanup(session, resources_report),
        }
        layer = s12_output_layer(session.roundId, case_request_id)
        result = {"gateId": "S12", "kind": "s12-cleanup-evidence-set",
                  "schemaVersion": 1, "runId": session.roundId,
                  "levelId": session.levelId, "caseRequestId": case_request_id,
                  "outputLayer": layer,
                  "documents": docs,
                  "statuses": {name: doc["status"] for name, doc in docs.items()},
                  "gateStatus": STAGE_PASS if all(
                      doc["status"] == STAGE_PASS for doc in docs.values()) else STAGE_BLOCKED,
                  "gateStatusBasis": "S12 is pass only when all three documents are pass; a "
                                     "document may only be pass when every evidenceRef it "
                                     "cites resolves on disk",
                  "sourceHashes": producer_hashes()}
        if output_root is not None:
            written = self._write_gate_documents(Path(output_root) / layer, docs)
            result["written"] = written
        return result

    def _cleanup_save_diff(self, session, report, *, save_case_files=None) -> dict:
        """The save that follows the cleanup, bound to this round's cleanup evidence."""
        doc = {"gateId": "S12", "kind": "entity-create-gate-evidence",
               "name": "cleanup-save-diff", "runId": session.roundId, "schemaVersion": 1,
               "synthetic": False, "status": STAGE_BLOCKED,
               "producer": "backend/cleanup_service.py:orchestrate_s12",
               "verifiedLayer": "offline",
               "cleanupRequestId": report.get("requestId"),
               "cleanupExitCode": report.get("exitCode"),
               "criteria": {}, "evidenceRefs": [], "statusBasis": None}
        readback = report.get("deletionReadback") or {}
        residual = (report.get("residual") or {}).get("ids") or []
        all_gone = bool(readback.get("performed")) and bool(readback.get("trusted")) \
            and not residual
        doc["criteria"]["allOwnedIdsGone"] = {
            "met": all_gone,
            "residualIds": residual,
            "reason": None if all_gone else
                      "the cleanup's own fresh read-back is not a trusted, complete absence",
        }
        if report.get("exitCode") not in (EXIT_CLEAN,):
            doc["statusBasis"] = ("the cleanup did not reach a clean terminal state "
                                  "(exitCode=%s), so there is nothing to bind a save to"
                                  % report.get("exitCode"))
            return doc
        if not all_gone:
            doc["statusBasis"] = "owned ids remain after the cleanup read-back"
            return doc
        if self.save_diff is None:
            doc["statusBasis"] = ("no independent save verifier is wired (DS-05 seam), so the "
                                  "save that follows this cleanup cannot be judged here")
            doc["criteria"]["saveDiff"] = {"met": False,
                                           "reason": "SAVE_DIFF_VERIFIER_UNAVAILABLE"}
            return doc
        manifest = {
            "runId": session.roundId, "levelId": session.levelId,
            "cleanupRequestId": report.get("requestId"),
            "cleanupOwnedIds": report.get("ownedIds") or [],
            "cleanupResidualIds": residual,
            "cleanupReadback": readback,
            "files": dict(save_case_files or {}),
        }
        try:
            verdict = self.save_diff.verify_cleanup_save(manifest)
        except Exception as error:                                # noqa: BLE001
            doc["statusBasis"] = ("the save verifier raised: %s: %s"
                                  % (type(error).__name__, error))
            return doc
        if isinstance(verdict, VerificationUnavailable):
            doc["criteria"]["saveDiff"] = {"met": False, "reason": verdict.detail,
                                           "code": verdict.code}
            doc["statusBasis"] = "the save verifier could not answer: %s" % verdict.code
            return doc
        if isinstance(verdict, dict):
            # DS-05's own report shape, normalised rather than reinterpreted.  Its verdicts
            # are carried over unchanged; the layer is derived from whether the bound files
            # really resolve.
            verdict = adapt_save_verification(verdict, manifest=manifest)
        if isinstance(verdict, VerificationUnavailable):
            doc["criteria"]["saveDiff"] = {"met": False, "reason": verdict.detail,
                                           "code": verdict.code}
            doc["statusBasis"] = "the save verifier could not answer: %s" % verdict.code
            return doc
        if not isinstance(verdict, SaveDiffVerdict):
            doc["statusBasis"] = "the save verifier returned an unrecognised shape"
            return doc
        axes = {"saveInvocation": verdict.saveInvocation,
                "savedContent": verdict.savedContent,
                "allowedDelta": verdict.allowedDelta,
                "unrelatedUnchanged": verdict.unrelatedUnchanged,
                "unrelatedObjectsPreserved": verdict.unrelatedObjectsPreserved}
        refs = []
        for name, judgment in axes.items():
            entry = {"met": bool(judgment.proven),
                     "reason": judgment.reason,
                     "evidenceRef": judgment.evidenceRef}
            if judgment.evidenceRef:
                entry["evidenceRefResolves"] = evidence_ref_resolves(judgment.evidenceRef)
                refs.append(judgment.evidenceRef)
            doc["criteria"][name] = entry
        if verdict.producerRef:
            doc["producerRef"] = verdict.producerRef
            doc["producerRefResolves"] = evidence_ref_resolves(verdict.producerRef)
        doc["verifiedLayer"] = verdict.layer
        doc["evidenceRefs"] = refs
        unmet = [name for name, entry in doc["criteria"].items() if not entry.get("met")]
        if unmet:
            doc["status"] = STAGE_FAIL
            doc["statusBasis"] = "the save verification did not prove: %s" % ",".join(sorted(unmet))
            return doc
        unresolved = [ref for ref in refs if not evidence_ref_resolves(ref)]
        if not refs or unresolved:
            doc["status"] = STAGE_BLOCKED
            doc["statusBasis"] = ("every axis claims to be proven, but %d evidence pointer(s) "
                                  "do not resolve on disk, so the claim is not evidence"
                                  % (len(unresolved) or 1))
            return doc
        if doc.get("producerRef") and not doc.get("producerRefResolves"):
            doc["status"] = STAGE_BLOCKED
            doc["statusBasis"] = "the verifier's own identity pointer does not resolve"
            return doc
        if verdict.layer != "live":
            doc["status"] = STAGE_BLOCKED
            doc["statusBasis"] = ("the save verification was produced by the %r layer; an "
                                  "offline fixture is not live evidence and never yields pass"
                                  % verdict.layer)
            return doc
        doc["status"] = STAGE_PASS
        doc["statusBasis"] = "cleanup read-back is empty and the live save verification proved " \
                             "all five axes with resolvable evidence"
        return doc

    def _cleanup_reopen(self, session, report) -> dict:
        """Request contract + call site only.  The mainline (T11) owns the verdict."""
        residual = (report.get("residual") or {}).get("ids") or []
        return {
            "gateId": "S12", "kind": "entity-create-gate-evidence",
            "name": "cleanup-reopen", "runId": session.roundId, "schemaVersion": 1,
            "synthetic": False, "status": STAGE_NOT_RUN,
            "producer": "mainline T11 (tools/game-executor/REOPEN-VERIFICATION.md)",
            "delegatedTo": "T11",
            "emittedBy": "backend/cleanup_service.py:orchestrate_s12",
            "statusBasis": "this module emits only the request contract and the call site; a "
                           "reopen verdict must come from the mainline entry point",
            "request": {
                "requestId": None,
                "reason": "reopen after a cleanup: confirm the removal persisted",
                "prerequisites": [
                    "the cleanup reached a clean terminal state before the reopen",
                    "a fresh complete baseline of the level after the cleanup save",
                    "the scope / hooks / observers this round created and their final state",
                    "no pending or unknown cleanup request for this round",
                ],
                "expectedObservation": {
                    "residualIds": residual,
                    "expectOwnedIdsAbsent": report.get("ownedIds") or [],
                },
                "callSite": [
                    "check_reopen_prerequisites.py live --output-root <a work directory>",
                    "prepare_reopen_review.py --out <a new review under .runtime>",
                    "scene_cli.py reopen-current (single claim + single dispatch)",
                    "native_reopen_acceptance.py --produce",
                    "author.py entity-inspect under a NEW requestId",
                ],
                "note": "07 section 11.3 fixes the six S08 evidence names; S12's reopen is the "
                        "same evidence collected after a cleanup, not a second mechanism",
            },
        }

    def _resource_cleanup(self, session, resources_report) -> dict:
        """Own resources only.  Foreign or unproven resources are refused, never touched."""
        doc = {"gateId": "S12", "kind": "entity-create-gate-evidence",
               "name": "resource-cleanup", "runId": session.roundId, "schemaVersion": 1,
               "synthetic": False, "status": STAGE_BLOCKED,
               "producer": "backend/cleanup_service.py:orchestrate_s12",
               "verifiedLayer": "offline",
               "scope": "resources this round created; nothing else",
               "perResource": {}, "stateCounts": {}, "evidenceRefs": [],
               "statusBasis": None}
        if not isinstance(resources_report, dict):
            doc["statusBasis"] = (
                "no resource releaser is wired, so no auxiliary resource was released"
                if self.releaser is None else
                "the resource releaser produced no report, so there is nothing to cite")
            return doc
        per_resource = resources_report.get("perResource") or {}
        doc["perResource"] = per_resource
        doc["stateCounts"] = resources_report.get("stateCounts") or {}
        doc["evidenceRefs"] = resources_report.get("evidenceRefs") or []
        refused = resources_report.get("refusedResourceIds") or []
        if resources_report.get("error"):
            doc["statusBasis"] = resources_report["error"]
            return doc
        if (doc["stateCounts"] or {}).get("unknown", 0):
            doc["status"] = STAGE_UNKNOWN
            doc["statusBasis"] = "at least one resource release outcome is unknown"
            return doc
        if resources_report.get("unreleased"):
            doc["status"] = STAGE_FAIL
            doc["statusBasis"] = "owned resources remain unreleased: %s" \
                                 % ",".join(map(str, resources_report["unreleased"]))
            return doc
        if refused:
            doc["status"] = STAGE_BLOCKED
            doc["statusBasis"] = ("resource(s) could not be shown to be this round's own: %s"
                                  % ",".join(map(str, refused)))
            return doc
        if not per_resource:
            doc["statusBasis"] = "the resource ledger is empty: an empty ledger is not evidence " \
                                 "that nothing was created"
            return doc
        unresolved = [ref for ref in doc["evidenceRefs"]
                      if not evidence_ref_resolves(ref)]
        if not doc["evidenceRefs"] or unresolved:
            doc["status"] = STAGE_BLOCKED
            doc["statusBasis"] = "the release evidence pointer(s) do not resolve on disk"
            return doc
        doc["status"] = STAGE_PASS
        doc["statusBasis"] = "every resource this round owned was released, with resolvable " \
                             "evidence, and no foreign resource was touched"
        return doc

    def release_own_resources(self, session, *, output_root: Path | None = None) -> dict:
        """Enumerate, prove and release THIS round's own auxiliary resources.

        A resource is released only when its owner round matches, its ownership proof
        resolves on disk, and its locator is inside an allowed root.  Everything else is
        refused by name.  The releaser is never called for a refused resource.
        """
        report = {"tool": "cleanup_service_resource_cleanup", "schemaVersion": MODULE_VERSION,
                  "runId": session.roundId, "levelId": session.levelId,
                  "scope": "own resources only", "perResource": {},
                  "stateCounts": {"released": 0, "refused": 0, "not-attempted": 0,
                                  "unknown": 0},
                  "refusedResourceIds": [], "unreleased": [], "evidenceRefs": [],
                  "error": None, "verifiedLayer": "offline"}
        if self.resources is None:
            report["error"] = "no resource ledger is wired"
            return report
        try:
            candidates = list(self.resources.own_resources(session))
        except Exception as error:                                # noqa: BLE001
            report["error"] = "the resource ledger raised: %s: %s" % (type(error).__name__, error)
            return report
        for resource in candidates:
            state, detail = self._release_one(session, resource)
            report["perResource"][resource.resourceId] = detail
            report["stateCounts"][state] = report["stateCounts"].get(state, 0) + 1
            if state == "refused":
                report["refusedResourceIds"].append(resource.resourceId)
            if state in ("not-attempted", "unknown"):
                report["unreleased"].append(resource.resourceId)
            if detail.get("evidenceRef"):
                report["evidenceRefs"].append(detail["evidenceRef"])
        doc = self._resource_cleanup(session, report)
        report["gateDocument"] = doc
        if output_root is not None:
            report["written"] = self._write_gate_documents(Path(output_root),
                                                           {"resource-cleanup": doc})
        return report

    def _release_one(self, session, resource: OwnedResource) -> tuple:
        base = {"resourceId": resource.resourceId, "kind": resource.kind,
                "locator": resource.locator, "ownerRoundId": resource.ownerRoundId}
        if not resource.ownerRoundId or resource.ownerRoundId != session.roundId:
            return "refused", dict(base, state="refused", subState="not-this-round",
                                   reason="the resource's owner round is %r, this round is %r"
                                          % (resource.ownerRoundId, session.roundId))
        if not evidence_ref_resolves(resource.ownershipProof):
            return "refused", dict(base, state="refused",
                                   subState="ownership-proof-unresolved",
                                   reason="the ownership proof does not resolve on disk")
        if not self._locator_allowed(resource.locator):
            return "refused", dict(base, state="refused", subState="locator-not-allowed",
                                   reason="the locator is outside the allowed roots")
        try:
            outcome = self.releaser.release(resource)
        except Exception as error:                                # noqa: BLE001
            return "unknown", dict(base, state="unknown", subState="release-raised",
                                   reason="%s: %s" % (type(error).__name__, error))
        if not isinstance(outcome, ReleaseOutcome) or outcome.state not in (
                "released", "refused", "not-attempted", "unknown"):
            return "unknown", dict(base, state="unknown", subState="unrecognised-outcome",
                                   reason="the releaser returned an unrecognised outcome")
        detail = dict(base, state=outcome.state, subState="released" if outcome.state ==
                      "released" else None, reason=outcome.reason)
        if outcome.evidenceRef:
            detail["evidenceRef"] = outcome.evidenceRef
            detail["evidenceRefResolves"] = evidence_ref_resolves(outcome.evidenceRef)
            if outcome.state == "released" and not detail["evidenceRefResolves"]:
                # A release with an unresolvable pointer is not a proven release.
                detail["state"] = "unknown"
                detail["reason"] = "the release evidence pointer does not resolve"
                return "unknown", detail
        elif outcome.state == "released":
            detail["state"] = "unknown"
            detail["reason"] = "a release without an evidence pointer is not proven"
            return "unknown", detail
        return outcome.state, detail

    def _locator_allowed(self, locator) -> bool:
        if not isinstance(locator, str) or not locator:
            return False
        candidate = Path(os.path.abspath(locator))
        for root in self.allowed_material_roots:
            try:
                candidate.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _write_gate_documents(root: Path, docs: dict) -> dict:
        written = {}
        for name, doc in docs.items():
            path = root / name / (name + ".json")
            try:
                exclusive_write_json(path, doc)
                written[name] = {"path": str(path), "written": True,
                                 "sha256": sha256_file(path)}
            except OSError as error:
                written[name] = {"path": str(path), "written": False,
                                 "error": "%s: %s" % (type(error).__name__, error)}
        return written


def _safe_hash(path) -> str | None:
    try:
        return sha256_file(Path(path))
    except OSError:
        return None


def _refs(note) -> list:
    ref = (note or {}).get("evidenceRef")
    return [ref] if ref else []


def _count_states(per_id: dict) -> dict:
    counts = {state: 0 for state in PER_ID_STATES}
    for row in (per_id or {}).values():
        state = row.get("state")
        if state in counts:
            counts[state] += 1
    return counts


def cleanup_owned(service: CleanupService, session: CleanupSession, entity_ids,
                  request_id: str, dry_run: bool = True, **kwargs) -> dict:
    """The T10-named entry point: ``cleanup_owned(session, entityIds, requestId, dryRun)``.

    ``service`` carries the injected execution layer; the caller supplies only business
    parameters.  An empty ``entity_ids`` is refused inside ``CleanupService`` -- never
    turned into an empty dispatch.
    """
    return service.cleanup_owned(session, entity_ids, request_id, dry_run, **kwargs)


# --------------------------------------------------------------------------- #
# The injected DS-05 seam (W10)
# --------------------------------------------------------------------------- #

def _load_save_diff_adapter(path: Path = SAVE_DIFF_ADAPTER_PATH):
    """Load ``backend/cleanup_save_diff_adapter.py`` by path, like the ownership producer.

    An already-imported module is preferred so a caller that imported the adapter as
    a package member shares one instance with this construction site.
    """
    for name in ("backend.cleanup_save_diff_adapter", "cleanup_save_diff_adapter"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "ExistingSaveVerifier"):
            return module
    try:
        from backend import cleanup_save_diff_adapter as module
        return module
    except ImportError:
        pass
    spec = importlib.util.spec_from_file_location("_cleanup_save_diff_adapter_reused", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("SAVE_DIFF_ADAPTER_UNLOADABLE: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _save_diff_for(case) -> "SaveDiffVerifier":
    """The DS-05 seam the CLI injects, built from the save path's OWN manifest.

    ``case`` is that document (``backend/save_manifest.py`` output): an object, or a
    path to the file.  It is consumed verbatim -- the adapter adds no key to it and
    reads nothing of its own off the cleanup manifest but the level identity.  A CLI
    run with no save case still gets a verifier; it refuses by name
    (``SAVE_MANIFEST_MISSING``) rather than reporting ``SAVE_DIFF_VERIFIER_UNAVAILABLE``,
    so "the seam is wired but the case is missing" is distinguishable from "nothing is
    wired".  The unavailability class is passed explicitly because this module may be
    ``__main__`` rather than ``backend.cleanup_service``.
    """
    module = _load_save_diff_adapter()
    return module.ExistingSaveVerifier(case=case, unavailable=VerificationUnavailable)


# --------------------------------------------------------------------------- #
# Offline CLI -- plan only, never a queue or a bridge
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan-manifest", type=Path, default=None,
                    help="JSON manifest: levelId, runId, requestId, targets, ownership, output")
    ap.add_argument("--save-case-manifest", type=Path, default=None,
                    help="The save path's own manifest (backend/save_manifest.py output) that "
                         "brackets the save following this cleanup.  Consumed verbatim by the "
                         "injected DS-05 verifier (backend/save_verification.py::verify_saved_case); "
                         "without it the verifier refuses by name (SAVE_MANIFEST_MISSING)")
    ap.add_argument("--s12-output-root", "--output-root", dest="s12_output_root",
                    type=Path, default=None,
                    help="Also build the three S12 documents (cleanup-save-diff / cleanup-reopen "
                         "/ resource-cleanup) and write them under this NEW directory "
                         "(<root>/<run-case layer>/<name>/<name>.json).  They are written "
                         "exclusively and are never overwritten; the save diff is judged by the "
                         "injected DS-05 verifier, so an offline plan can describe a perfect save "
                         "and still only reach blocked.  `--output-root` is the historical "
                         "spelling of the same switch and is accepted as a compatibility alias")
    ap.add_argument("--s12-case-request-id", dest="s12_case_request_id", default=None,
                    help="The save case's own requestId.  It is recorded in the S12 bundle and "
                         "folded into the on-disk layer name so the run/case identity the "
                         "projection checks is the one the documents were written under")
    ap.add_argument("--output", type=Path, default=None,
                    help="Write the plan report to this NEW file under the task run root")
    ap.add_argument("--task-root", type=Path, default=None,
                    help="The caller's own task run root.  --output must live under it, and "
                         "it is where this CLI may write its own dry-run evidence; without "
                         "it the plan is produced in memory only and claims no verified "
                         "mapping evidence")
    return ap


def load_manifest(path: Path) -> dict:
    document = read_json(path)
    if not isinstance(document, dict):
        raise ValueError("MANIFEST_SHAPE_UNSUPPORTED")
    return document


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = build_parser().parse_args(argv)
    if args.plan_manifest is None:
        print(json.dumps({"code": "PLAN_MANIFEST_REQUIRED",
                          "detail": EXECUTE_OFFLINE}))
        return EXIT_USAGE
    try:
        manifest = load_manifest(args.plan_manifest)
    except (OSError, ValueError) as error:
        print(json.dumps(Refusal("MANIFEST_UNREADABLE",
                                 "%s: %s" % (type(error).__name__, error)).as_json()))
        return EXIT_USAGE
    if manifest.get("execute"):
        print(json.dumps(Refusal(
            "EXECUTE_REQUIRES_MAINLINE",
            "this offline CLI never dispatches a delete; the mainline runs execute through "
            "the injected bridge").as_json()))
        return EXIT_USAGE
    level_id = co.as_uint(manifest.get("levelId"))
    if level_id is None:
        print(json.dumps(Refusal("LEVEL_ID_INVALID",
                                 "manifest.levelId must be a nonzero uint32").as_json()))
        return EXIT_USAGE
    session = CleanupSession(
        levelId=level_id,
        levelHandleDigest=manifest.get("levelHandleDigest") or "manifest",
        bridgeRunId=manifest.get("bridgeRunId"),
        sessionIdentity=manifest.get("sessionIdentity"),
        roundId=manifest.get("runId"))
    ownership = manifest.get("ownership") or {}
    materials = OwnershipMaterials(
        levelId=level_id,
        receipts=tuple(Path(p) for p in (ownership.get("receipts") or [])),
        preBaseline=Path(ownership["preBaseline"]) if ownership.get("preBaseline") else None,
        currentBaseline=Path(ownership["currentBaseline"]) if ownership.get("currentBaseline")
        else Path("__missing__"),
        source=ownership.get("source") or "manifest",
        digest=ownership.get("digest"),
        roundMaterials=ownership.get("roundMaterials"))

    class _ManifestOwnership:
        def materials_for_round(self, session, request_ids):
            return materials

    output_root = args.task_root or RUNTIME_ROOT
    # The save path's own manifest is consumed verbatim: it is the DS-05 case document,
    # and its ``files`` binding is what --s12-output-root derives the layer from.
    case = None
    if args.save_case_manifest is not None:
        try:
            case = load_manifest(args.save_case_manifest)
        except (OSError, ValueError) as error:
            print(json.dumps(Refusal("SAVE_CASE_MANIFEST_UNREADABLE",
                                     "%s: %s" % (type(error).__name__, error)).as_json()))
            return EXIT_USAGE
    # The DS-05 seam is ALWAYS injected: without it ``cleanup-save-diff`` can never leave
    # ``blocked``, because the service refuses to judge a save it has no verifier for.
    service = CleanupService(ownership=_ManifestOwnership(),
                             save_diff=_save_diff_for(case),
                             allowed_material_roots=(EVIDENCE_ROOT,),
                             evidence_root=args.task_root)
    output = args.output or manifest.get("output")
    report = service.cleanup_owned(session, manifest.get("targets") or [],
                                   manifest.get("requestId") or "", dry_run=True,
                                   output_path=output, task_root=output_root)
    if args.s12_output_root is not None:
        # The three S12 documents, judged by the injected verifier.  The bound files come
        # from the save case's own ``files`` map, so the save-diff layer is derived from
        # files that really resolve -- a fabricated binding stays offline.  The case's own
        # requestId (when the case carries one) is the identity the layer is named after,
        # so a bundle and its directory agree on which run/case produced them.
        report["s12"] = service.orchestrate_s12(
            session, report, save_case_files=(case or {}).get("files"),
            output_root=args.s12_output_root,
            case_request_id=args.s12_case_request_id or (case or {}).get("requestId"))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report["exitCode"]


if __name__ == "__main__":
    raise SystemExit(main())
