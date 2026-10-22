#!/usr/bin/env python3
"""The missing ownership legs for the cleanup route (F-011).

THE GAP THIS CLOSES
-------------------
``backend/entity_server.py`` ``mw_scene_cleanup_owned`` proves ownership with ONE leg:

    the id appears as ``entityId`` in a ``result.json`` of a create this run performed,
    and the id exists in the live level right now.

``docs/ds-handoff/07-ENTITY-CREATE-FULL-RUN.md`` section 9 step 1 requires the three-way
intersection -- this round's create receipt, **new relative to the pre-create baseline**,
and present now with the same template.  The **baseline-difference leg is entirely
absent** from the server route, so an id that already existed before the round is
accepted.  That is not hypothetical: ``backend/cleanup_service.py`` solves the same
problem with ``prove_ownership``, but ``prove_ownership`` folds the three legs into one
function, and the *baselines it is handed are arbitrary caller-supplied paths* with no
guarantee that the "current" one is a complete read-back taken immediately before the
cleanup, and no notion at all of a round time window or of receipt provenance.

WHAT THIS MODULE ADDS (each leg is independently falsifiable)
-------------------------------------------------------------
    A  the id is carried by a create receipt of THIS round          (receipt leg)
    B  the id is in the difference  fresh_readback - pre_baseline   (baseline diff leg)
    C  the id is present in the fresh read-back with the SAME template
    D  the fresh read-back is USABLE: accepted, complete, not truncated, for this
       level, timestamped, and inside the round window  ("清理前完整读回")
    E  the receipt's own create timestamp is inside the round window ("time window")
    F  the receipt file still hashes to what the round recorded     (tamper leg)
    G  the id is not one of the unattributable frozen ids

    owned = A & B & C & D & E & F & G

REFUSAL IS PER-ID OR PER-RUN, NEVER A SILENT PASS
-------------------------------------------------
Legs B/C/E/F/G refuse ONE id by name and drop it; the rest of the list still runs.
Leg D and a malformed window refuse the WHOLE round, because an unusable read-back means
"what is present now" is unknown, and an unknown present-set cannot own anything.

NO DISPATCH, EVER
-----------------
This module has no bridge, no queue, no helper and no subprocess.  It answers one
question -- "which of these ids does this round own?" -- and returns.  It never deletes,
never saves and never starts or stops the game or the editor.  ``dispatchPerformed`` and
``deletionPerformed`` are pinned false in every report.

REUSE, NOT A WEAKER SECOND COPY
-------------------------------
``tools/game-executor/cleanup_owned_entities.py`` is loaded by path and its primitives are
used directly: ``Refusal``, ``as_uint``, ``load_json_document``, ``prove_ownership``,
``MAX_IDS_PER_CALL``.  ``prove_ownership`` is additionally used as an EQUALITY ORACLE in
the test suite: the owned set computed here must equal the owned set it computes for the
same inputs.  Keeping the legs separable is what makes them testable; keeping the equality
check is what proves separability did not weaken the verdict.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MODULE_VERSION = 1
LEG_VERSION = "1"

HASH_CHUNK = 1 << 20

#: The three ids 2026-09-30 could not attribute: present in the live level, no create
#: receipt of any round, possibly original level content.
#:
#: SCOPED BY LEVEL, 2026-10-08.  These three were observed in ONE level.  The flat form
#: protected the same NUMBERS in every level, and an entity id is not a property of an
#: object -- the project has already recorded 1077936135 appearing in two levels with
#: two different templates.  MEASURED consequence of the flat form: the live parameter
#: driver created entity 1077936130 in level 1073741842 and then could not delete it,
#: because ``cleanup_ownership_gate`` refused an id that this round had just created and
#: held its own create receipt for.  A run could not clean up after itself.
PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL = {
    1073741839: frozenset({1077936129, 1077936130, 1077936131}),
}


def protected_ids_for(level_id) -> frozenset:
    """The unattributable ids OF THAT LEVEL, and only of that level.

    An unknown or absent level resolves to the EMPTY set.  Protection that is not known
    to apply is not invented: every candidate still has to pass the ownership legs --
    carried by this round's own create receipt, new against the pre-create baseline, and
    present now with the same templateId -- before it can be deleted at all, so an id
    belonging to anything else can never enter the candidate set in the first place.
    """
    try:
        return frozenset(PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL.get(int(level_id), ()))
    except (TypeError, ValueError):
        return frozenset()

#: An unusable read-back or a malformed window blocks the WHOLE round: with the present
#: set unknown, no id can be shown to be this round's.
RUN_BLOCKING_CODES = frozenset({
    "READBACK_UNAVAILABLE", "READBACK_SHAPE_UNKNOWN", "READBACK_NOT_ACCEPTED",
    "READBACK_INCOMPLETE", "READBACK_TRUNCATED", "READBACK_LEVEL_UNKNOWN",
    "READBACK_LEVEL_MISMATCH", "READBACK_TIMESTAMP_UNKNOWN", "READBACK_NOT_FRESH",
    # A materials document whose bytes are not the bytes the round recorded is not this
    # round's evidence at all, so nothing can be attributed from it -- blocking the whole
    # round is the only honest verdict.  MEASURED 2026-10-04: the manifest HAS carried
    # ``freshReadback.sha256`` / ``preBaseline.sha256`` all along (tools/game-executor/
    # round_materials.py:615,658) and its own docstring calls them "checkable against the
    # copy and against the original journal" -- but nothing here ever checked them.
    "READBACK_HASH_MISMATCH", "READBACK_TIME_NOT_BOUND",
    "PRE_BASELINE_HASH_MISMATCH", "PRE_BASELINE_EMPTY",
    "PRE_BASELINE_UNAVAILABLE", "PRE_BASELINE_SHAPE_UNKNOWN",
    "RECEIPTS_REQUIRED",
    "WINDOW_INVALID", "LEVEL_ID_INVALID",
})

RECEIPT_LEVEL_KEYS = ("levelId", "expectedLevelId", "level_id")
RECEIPT_TEMPLATE_KEYS = ("templateId", "template_id")
RECEIPT_ENTITY_KEYS = ("entityId", "createdEntityId", "entity_id")
READBACK_ID_KEYS = ("id", "Id", "entityId")
READBACK_TEMPLATE_KEYS = ("templateId", "template_id", "configId", "config_id")
RUN_DIR_STAMP = re.compile(r"^(\d{8})-(\d{6})-")


# --------------------------------------------------------------------------- #
# Where the reused producer lives (robust to being run from a worker directory
# or from backend/, so the same file can be merged without being edited)
# --------------------------------------------------------------------------- #

def find_repo_root(start: Path | None = None) -> Path:
    here = Path(start or __file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "tools/game-executor/cleanup_owned_entities.py").is_file():
            return candidate
    raise RuntimeError("REPO_ROOT_NOT_FOUND from %s" % here)


ROOT = find_repo_root()
OWNERSHIP_PRODUCER_PATH = ROOT / "tools/game-executor/cleanup_owned_entities.py"


def _load_producer(path: Path = OWNERSHIP_PRODUCER_PATH):
    """Load ``cleanup_owned_entities.py`` by path (its directory name has a hyphen).

    Import failure is fatal on purpose: a module that cannot load the shared ownership
    primitives must not be able to publish an ownership verdict.
    """
    if not path.is_file():
        raise RuntimeError("OWNERSHIP_PRODUCER_MISSING: %s" % path)
    spec = importlib.util.spec_from_file_location("_cleanup_owned_entities_for_legs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("OWNERSHIP_PRODUCER_UNLOADABLE: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


co = _load_producer()
MAX_IDS_PER_CALL = co.MAX_IDS_PER_CALL


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def utc(value) -> datetime | None:
    """A tz-aware UTC datetime, or None.

    A naive stamp is refused (None) rather than assumed to be UTC: an assumption here
    would silently move an id in or out of the round window.  ``Z`` and offset forms are
    both accepted, as are sub-microsecond fractions.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso(stamp: datetime | None) -> str | None:
    if stamp is None:
        return None
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _stamp_from_run_dir(path: Path) -> datetime | None:
    """The read time encoded in a native run directory name (YYYYMMDD-HHMMSS-hex)."""
    match = RUN_DIR_STAMP.match(Path(path).parent.name)
    if not match:
        return None
    try:
        naive = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    # The native runner writes the directory name with the UTC clock it started on.
    return naive.replace(tzinfo=timezone.utc)


def refusal_for(refusals, entity_id):
    for item in refusals:
        if isinstance(item, co.Refusal) and item.entity_id == entity_id:
            return item
    return None


def codes(refusals):
    return [item["code"] if isinstance(item, dict) else item.code for item in refusals]


def _deep_scalar(node, path):
    """Follow ``path`` through nested dicts; None when any step is missing/not a dict."""
    current = node
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, (str, int, float)) and not isinstance(current, bool) \
        else None


# --------------------------------------------------------------------------- #
# Leg D -- the pre-cleanup complete read-back
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class FreshReadback:
    """A read-back of the level taken immediately before the cleanup.

    ``entries`` is ``id -> templateId`` (``None`` when the record carries no template).
    ``complete`` is not a guess: it is True only when the document itself says so -- the
    native snapshot says it with the ``entities_complete`` flag plus a zero rejected count
    plus ``entityCaptured == entityValidEntries == len(entities)`` plus a stable
    ``entityVersionBefore == entityVersionAfter`` (the two normative checks in
    ``tools/game-executor/build_readonly_profile.py``, folded into this boolean);
    a generic baseline says it explicitly.
    A document that cannot show completeness is not usable as "清理前完整读回".
    """

    path: Path | None
    sha256: str | None
    levelId: int | None
    readAtUtc: str | None
    entityCount: int | None
    complete: bool
    accepted: bool
    entries: dict = field(default_factory=dict)
    shape: str = "unknown"
    acceptance: dict = field(default_factory=dict)

    def ids(self):
        return set(self.entries)


def _readback_entries(document):
    """(entries, shape, entityCount, complete, levelId, readAtUtc) for one document."""
    if not isinstance(document, dict):
        if isinstance(document, list):
            return None, "bare-list", None, False, None, None
        return None, "unrecognised", None, False, None, None

    entities = document.get("entities")
    if not isinstance(entities, list):
        baseline = document.get("baseline")
        if isinstance(baseline, dict) and isinstance(baseline.get("entities"), list):
            entities = baseline["entities"]
            document = dict(document, entities=entities)
    if not isinstance(entities, list):
        return None, "unrecognised", None, False, None, None

    entries = {}
    for entry in entities:
        if not isinstance(entry, dict):
            continue
        entity_id = None
        for key in READBACK_ID_KEYS:
            entity_id = co.as_uint(entry.get(key))
            if entity_id is not None:
                break
        if entity_id is None:
            continue
        template_id = None
        for key in READBACK_TEMPLATE_KEYS:
            template_id = co.as_uint(entry.get(key))
            if template_id is not None:
                break
        entries[entity_id] = template_id

    counts = document.get("counts") if isinstance(document.get("counts"), dict) else {}
    flags = document.get("flags") if isinstance(document.get("flags"), dict) else {}
    flag_names = flags.get("names") if isinstance(flags.get("names"), list) else []
    status = document.get("status") if isinstance(document.get("status"), dict) else {}
    observation = (document.get("levelObservation")
                   if isinstance(document.get("levelObservation"), dict) else {})

    entity_count = co.as_uint(counts.get("entityCaptured"))
    if entity_count is None:
        entity_count = co.as_uint(document.get("entityCount"))
    if entity_count is None:
        entity_count = len(entries)

    if "entities_complete" in flag_names:
        # A-44: mirror COMPLETE_ENTITY_SET + ENTITY_VERSION_CHANGED
        # (tools/game-executor/build_readonly_profile.py:277-278).  The prior line compared a
        # row count against the monotone world-version counter and never consulted
        # entityValidEntries, len(entities), or version stability.
        #
        # Counts are compared raw.  ``co.as_uint`` must NOT be used here: it is a strict
        # 32-bit *id* parser that returns None for 0, so ``as_uint(entityRejected) == 0``
        # would be False for the common zero-rejected case.  ``type(...) is int`` keeps a
        # missing/string count from passing by accident.
        captured = counts.get("entityCaptured")
        valid_entries = counts.get("entityValidEntries")
        version_before = counts.get("entityVersionBefore")
        version_after = counts.get("entityVersionAfter")
        complete = (counts.get("entityRejected") == 0
                    and type(captured) is int
                    and captured == valid_entries == len(entities)
                    and type(version_before) is int
                    and version_before == version_after)
        shape = "native-before-context"
    else:
        complete = document.get("complete") is True
        shape = "explicit-readback" if document.get("complete") is not None else "generic-baseline"

    level_id = co.as_uint(observation.get("levelId")) if observation.get("verified") is True else None
    if level_id is None:
        level_id = co.as_uint(document.get("levelId"))
        if level_id is not None and observation and observation.get("verified") is not True:
            level_id = co.as_uint(document.get("levelId"))

    read_at = document.get("readAtUtc")
    details = {"status": status.get("name"), "flags": list(flag_names),
               "counts": dict(counts)}
    return entries, shape, entity_count, complete, level_id, read_at, details


def load_fresh_readback(path, *, read_at_utc=None, level_id=None, complete=None,
                        entity_count=None, sha256=None) -> tuple:
    """(FreshReadback | None, refusals) for one candidate read-back document.

    Sibling run files are read as part of the same evidence, not as decoration:
    ``exit.json`` supplies the read timestamp and the exit code, and a sibling
    ``readonly-acceptance.json`` (when present) must say ``ok: true``.  A read-back whose
    own acceptance record refused it is NOT a usable "present now" claim.
    """
    refusals = []
    target = Path(path)
    if not target.is_file():
        return None, [co.Refusal("READBACK_UNAVAILABLE", "%s does not exist" % target,
                                 source=str(target))]
    # The manifest records the read-back's sha256 as it was at round time.  A document
    # whose bytes no longer match is not the evidence the round certified, so it cannot
    # be read as "what is present now" -- and the whole round is blocked, because the
    # present set is the thing every other leg is measured against.
    if sha256 is not None:
        actual = sha256_file(target)
        if actual != sha256:
            return None, [co.Refusal(
                "READBACK_HASH_MISMATCH",
                "%s hashes %s, the round recorded %s; this is not the read-back the round "
                "certified" % (target, actual, sha256), source=str(target))]
    try:
        document = co.load_json_document(target)
    except (OSError, json.JSONDecodeError) as error:
        return None, [co.Refusal("READBACK_SHAPE_UNKNOWN",
                                 "%s: %s" % (type(error).__name__, error), source=str(target))]
    parsed = _readback_entries(document)
    if parsed[0] is None:
        return None, [co.Refusal(
            "READBACK_SHAPE_UNKNOWN",
            "the document carries no usable entity list, so it cannot say what is present "
            "in the level", source=str(target))]
    entries, shape, count, doc_complete, doc_level, doc_read_at, details = parsed

    parent = target.parent
    exit_doc = {}
    exit_path = parent / "exit.json"
    if exit_path.is_file():
        try:
            exit_doc = read_json(exit_path)
        except (OSError, json.JSONDecodeError):
            exit_doc = {}
    acceptance_doc = {}
    acceptance_path = parent / "readonly-acceptance.json"
    if acceptance_path.is_file():
        try:
            acceptance_doc = read_json(acceptance_path)
        except (OSError, json.JSONDecodeError):
            acceptance_doc = {}

    accepted = True
    if acceptance_doc:
        accepted = acceptance_doc.get("ok") is True
    if accepted and exit_doc and exit_doc.get("exitCode") not in (None, 0):
        accepted = False
    if accepted and details.get("status") not in (None, "ok"):
        accepted = False

    # A DECLARED read time must not silently outrank the artifact's own record.
    #
    # ``read_at_utc`` comes from the manifest, i.e. from the round's own paperwork; the
    # other three come from the artifact and its siblings.  Letting the declaration win
    # means a round can ASSERT when it read the level and every leg will believe it -- the
    # read-back is then no longer "the complete read-back taken immediately before the
    # cleanup", it is whatever the paperwork says it was.  MEASURED 2026-10-04: the real
    # round's declared time and its exit.json startedUtc are IDENTICAL to the microsecond,
    # so requiring agreement costs the honest case nothing; the guard suite's named
    # deviation `d-readback-time-bound-to-artifact` asserts a time two days off.
    own_stamp = (doc_read_at or exit_doc.get("startedUtc")
                 or iso(_stamp_from_run_dir(target)))
    if read_at_utc is not None and own_stamp is not None:
        declared, observed = utc(read_at_utc), utc(own_stamp)
        if declared is not None and observed is not None and \
                abs((declared - observed).total_seconds()) > 2:
            return None, [co.Refusal(
                "READBACK_TIME_NOT_BOUND",
                "the manifest declares the read happened at %s but the read-back's own "
                "record says %s; a merely asserted time is not an observation"
                % (read_at_utc, own_stamp), source=str(target))]

    stamp = (read_at_utc or doc_read_at
             or exit_doc.get("startedUtc")
             or iso(_stamp_from_run_dir(target)))
    if entity_count is not None:
        count = entity_count
    readback = FreshReadback(
        path=target, sha256=sha256_file(target),
        levelId=level_id if level_id is not None else doc_level,
        readAtUtc=stamp, entityCount=count,
        complete=doc_complete if complete is None else bool(complete),
        accepted=accepted, entries=entries, shape=shape,
        acceptance={"exitCode": exit_doc.get("exitCode"),
                    "readonlyAcceptanceOk": (acceptance_doc.get("ok")
                                             if acceptance_doc else None),
                    "status": details.get("status"),
                    "exitStartedUtc": exit_doc.get("startedUtc"),
                    "flags": details.get("flags")})
    return readback, refusals


# --------------------------------------------------------------------------- #
# The round window
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RoundWindow:
    roundId: str | None
    levelId: int
    startUtc: str
    stopUtc: str

    def bounds(self):
        return utc(self.startUtc), utc(self.stopUtc)

    def contains(self, stamp: datetime | None) -> bool:
        start, stop = self.bounds()
        if stamp is None or start is None or stop is None:
            return False
        return start <= stamp <= stop


# --------------------------------------------------------------------------- #
# Receipt provenance (leg F) and the receipt index
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ReceiptProvenance:
    """One create receipt as THIS ROUND recorded it.

    ``recordedSha256`` is the hash the round wrote down when the create finished -- it is
    what makes the file's current bytes checkable.  ``createdAtUtc`` is the round's own
    clock for the create, and it is what the time-window leg reads.  Neither is taken from
    the receipt body: a receipt that could set its own timestamp could walk itself into
    the window.
    """

    requestId: str
    path: Path
    recordedSha256: str
    createdAtUtc: str
    entityId: int | None = None
    levelId: int | None = None
    templateId: int | None = None
    resultPath: Path | None = None
    recordedResultSha256: str | None = None


def load_provenance_receipts(entries, *, verify=True) -> tuple:
    """(claims, meta, refusals) for a round's receipt index.

    ``claims`` is ``entityId -> co.Claim`` shaped for the reused primitives; ``meta`` is
    ``entityId -> {requestId, createdAtUtc, levelId, templateId, sha256Verified,
    fileSha256}`` and is what the time-window and provenance legs read.

    A receipt whose file no longer hashes to the recorded value is REFUSED BY NAME
    (``RECEIPT_TAMPERED``) -- it never becomes a claim at all.
    """
    claims = {}
    meta = {}
    refusals = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            refusals.append(co.Refusal("RECEIPT_PROVENANCE_MISSING",
                                       "a receipt index entry is not an object"))
            continue
        request_id = entry.get("requestId")
        raw_path = entry.get("path")
        recorded = entry.get("recordedSha256")
        if not request_id or not raw_path:
            refusals.append(co.Refusal("RECEIPT_PROVENANCE_MISSING",
                                       "a receipt index entry names no requestId/path",
                                       source=str(raw_path)))
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if not isinstance(recorded, str) or not recorded:
            refusals.append(co.Refusal(
                "RECEIPT_PROVENANCE_MISSING",
                "the round recorded no sha256 for requestId %r, so the receipt's bytes "
                "cannot be shown to be the ones it created" % request_id,
                source=str(path)))
            continue
        if not path.is_file():
            refusals.append(co.Refusal("RECEIPT_MISSING",
                                       "the receipt of requestId %r is not on disk"
                                       % request_id,
                                       entity_id=co.as_uint(entry.get("entityId")),
                                       source=str(path)))
            continue
        actual = sha256_file(path)
        verified = (actual == recorded) or not verify
        result_path = entry.get("resultPath")
        if result_path:
            result_path = Path(result_path)
            if not result_path.is_absolute():
                result_path = ROOT / result_path
            recorded_result = entry.get("recordedResultSha256")
            result_ok = (bool(result_path.is_file()) and bool(recorded_result)
                         and sha256_file(result_path) == recorded_result)
            verified = verified and (result_ok or not verify)
        # The hash verdict is DATA here, not a refusal: leg F is the single place that
        # refuses a receipt whose bytes no longer match the round's record, so the check
        # stays falsifiable in one place instead of being duplicated into silence.

        entity_id = co.as_uint(entry.get("entityId"))
        level_id = co.as_uint(entry.get("levelId"))
        template_id = co.as_uint(entry.get("templateId"))
        if entity_id is None or level_id is None or template_id is None:
            # Fall back to the receipt's own envelope for whatever the index omitted.
            try:
                document = co.load_json_document(path)
            except (OSError, json.JSONDecodeError):
                document = None
            found, problems = co.extract_claims(document, str(path))
            refusals.extend(problems)
            candidates = [claim for key, claim in found.items()]
            if entity_id is not None:
                candidates = [claim for claim in candidates if claim.entity_id == entity_id]
            for claim in candidates:
                if template_id is None and claim.template_id is not None:
                    template_id = claim.template_id
                if level_id is None and claim.level_id is not None:
                    level_id = claim.level_id
            if entity_id is None and len(candidates) == 1:
                entity_id = candidates[0].entity_id
            if entity_id is None:
                refusals.append(co.Refusal(
                    "RECEIPT_ENTITY_ID_MISSING",
                    "receipt requestId %r names no usable entity id" % request_id,
                    source=str(path)))
                continue
        created = entry.get("createdAtUtc") or entry.get("startedUtc")

        # The index's own declaration must agree with the receipt body.  Without this, a
        # record could re-label someone else's receipt as this round's by editing the
        # index alone -- the very thing a "receipt leg" is supposed to prevent.
        body = None
        try:
            body = co.load_json_document(path)
        except (OSError, json.JSONDecodeError):
            body = None
        body_action = _deep_scalar(body, ("backend", "action")) or _deep_scalar(body, ("action",))
        # The action must be DECLARED as a create.  This used to read
        # `if body_action is not None and body_action != "create"`, which skipped the
        # whole check whenever the document carried no `action` field at all -- so any
        # readable document whose sha256 agreed with the index satisfied the receipt
        # leg.  MEASURED (2026-10-02): repointing one receipt at a read-only snapshot
        # (`scene-cli/inspect/.../before-context.json`, no `action` key) left the entity
        # owned, with zero refusals -- a wrong object could have been deleted.  Absence
        # of a declaration is not a declaration; all 51 real create receipts carry
        # `backend.action == "create"`, so requiring it costs nothing legitimate.
        if body_action != "create":
            refusals.append(co.Refusal(
                "RECEIPT_NOT_A_CREATE",
                "receipt requestId %r does not declare action 'create' (found %r)"
                % (request_id, body_action), entity_id=entity_id, source=str(path)))
            continue
        declared = {"entityId": entity_id, "levelId": level_id, "templateId": template_id}
        observed = {
            "entityId": (_deep_scalar(body, ("backend", "entityId"))
                         or _deep_scalar(body, ("action", "entityId"))),
            "levelId": (_deep_scalar(body, ("backend", "levelId"))
                        or _deep_scalar(body, ("action", "levelId"))
                        or _deep_scalar(body, ("command", "levelId"))),
            "templateId": (_deep_scalar(body, ("command", "templateId"))
                           or _deep_scalar(body, ("backend", "templateId"))),
        }
        mismatch = {key: (co.as_uint(observed[key]), declared[key])
                    for key in declared
                    if observed[key] is not None
                    and co.as_uint(observed[key]) != declared[key]}
        if mismatch:
            refusals.append(co.Refusal(
                "RECEIPT_BODY_MISMATCH",
                "receipt requestId %r is declared as %r but its body says %r; the record and "
                "the receipt do not describe the same create"
                % (request_id, declared, mismatch),
                entity_id=entity_id, source=str(path)))
            continue
        body_stamp = entry.get("bodyCreatedAtUtc") or _deep_scalar(body, ("startedUtc",))
        if body_stamp and created and utc(body_stamp) != utc(created):
            refusals.append(co.Refusal(
                "RECEIPT_TIMESTAMP_MISMATCH",
                "receipt requestId %r is dated %s by the round but %s inside its own body"
                % (request_id, created, body_stamp), entity_id=entity_id, source=str(path)))
            continue
        claim = co.Claim(entity_id, template_id, level_id, ["%s#%s" % (path, request_id)])
        existing = claims.get(entity_id)
        if existing is None:
            claims[entity_id] = claim
            meta[entity_id] = {"requestId": request_id, "createdAtUtc": created,
                               "levelId": level_id, "templateId": template_id,
                               "sha256Verified": verified, "fileSha256": actual,
                               "path": str(path)}
            continue
        # One entity id, two receipts.  Only "same round, same everything" collapses; a
        # differing level or template is ambiguity about WHICH object this is.
        existing.sources.extend(claim.sources)
        previous = meta[entity_id]
        if previous.get("levelId") != level_id or previous.get("templateId") != template_id:
            existing.ambiguous = True
            refusals.append(co.Refusal(
                "RECEIPT_AMBIGUOUS_CLAIM",
                "id %d is bound to (level %s, template %s) and (level %s, template %s)"
                % (entity_id, previous.get("levelId"), previous.get("templateId"),
                   level_id, template_id), entity_id=entity_id, source=str(path)))
    return claims, meta, refusals


# --------------------------------------------------------------------------- #
# The judgement
# --------------------------------------------------------------------------- #

def _resolve(raw):
    path = Path(str(raw))
    return path if path.is_absolute() else (ROOT / path)


def load_pre_baseline(spec) -> tuple:
    """(ids set, refusals) for the pre-create baseline.

    Accepts ``{"path": ...}`` or ``{"ids": [...]}``.  The id set is all that is read --
    the pre-create baseline is a "what existed before" statement, not a template source.
    """
    if spec is None:
        return None, [co.Refusal("PRE_BASELINE_UNAVAILABLE",
                                 "no pre-create baseline was supplied, so 'new this round' "
                                 "cannot be shown")]
    if isinstance(spec, dict) and isinstance(spec.get("ids"), list):
        ids = set()
        for value in spec["ids"]:
            parsed = co.as_uint(value)
            if parsed is None:
                return None, [co.Refusal("PRE_BASELINE_SHAPE_UNKNOWN",
                                         "%r is not a uint32 id" % (value,))]
            ids.add(parsed)
        # An EMPTY inline set is refused.  Leg B asks "was this id new relative to the
        # pre-create baseline?", and against an empty baseline every id is new -- the leg
        # becomes a rubber stamp that grants ownership to anything.  An empty set is also
        # indistinguishable from a document that failed to load, and "I could not read
        # the baseline" must never be read as "the level was empty".  MEASURED
        # 2026-10-04: the project's own guard suite carries this as the named known
        # deviation `c-pre-baseline-empty-inline-refused`.
        if not ids:
            return None, [co.Refusal(
                "PRE_BASELINE_EMPTY",
                "an empty pre-create baseline makes every id look new this round, so leg B "
                "would grant ownership to anything; supply the pre-create id set or drop "
                "leg B entirely", source="inline ids")]
        return ids, []
    raw = spec.get("path") if isinstance(spec, dict) else spec
    declared_sha = spec.get("sha256") if isinstance(spec, dict) else None
    path = _resolve(raw)
    if not path.is_file():
        return None, [co.Refusal("PRE_BASELINE_UNAVAILABLE",
                                 "%s does not exist" % path, source=str(path))]
    # Same rule as the read-back: a pre-create baseline whose bytes are not the ones the
    # round recorded cannot be the "before" that leg B compares against, and a leg B that
    # silently compares against the wrong document would mark ids as new this round.
    if declared_sha is not None:
        actual = sha256_file(path)
        if actual != declared_sha:
            return None, [co.Refusal(
                "PRE_BASELINE_HASH_MISMATCH",
                "%s hashes %s, the round recorded %s" % (path, actual, declared_sha),
                source=str(path))]
    try:
        document = co.load_json_document(path)
        entries = co.baseline_entries(document)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return None, [co.Refusal("PRE_BASELINE_SHAPE_UNKNOWN",
                                 "%s: %s" % (type(error).__name__, error),
                                 source=str(path))]
    ids = set()
    for entry in entries:
        entity_id, _template = co.entry_identity(entry)
        if entity_id is not None:
            ids.add(entity_id)
    # 2026-10-06: the SAME refusal the inline branch above makes, applied to the file form.
    #
    # It was missing here, and the asymmetry was load-bearing: the inline branch refuses an
    # empty set ("an empty pre-create baseline makes every id look new this round, so leg B
    # would grant ownership to anything"), but the file branch returned an empty set happily.
    # A document that exists, parses, has the right shape and simply lists nothing is exactly
    # as much of a rubber stamp as an inline empty list -- leg B asks "is this id new against
    # the pre-create baseline", and against nothing every id is new.
    #
    # MEASURED 2026-10-06 over the 1185 native context documents on this machine: 1174 carry
    # a non-empty entity list and 11 carry an empty one. Those 11 would have become a
    # rubber stamp the moment a round pointed leg B at one -- which is what moving the live
    # writer's preBaseline from inline ids to a file path would have done, had this check not
    # been added in the same change.
    if not ids:
        return None, [co.Refusal(
            "PRE_BASELINE_EMPTY",
            "the pre-create baseline document %s lists no entity ids, so every id would "
            "look new this round and leg B would grant ownership to anything" % path,
            source=str(path))]
    return ids, []


def judge(manifest, protected_ids=None) -> dict:
    """The whole decision for one round.  Returns the report; never dispatches.

    ``protected_ids`` is the caller's own view of the unattributable set.  The effective
    set is the UNION of this module's constant and the caller's, so a caller can only
    ever TIGHTEN protection -- passing a smaller set cannot un-protect an id.  The
    docstring above PROTECTED_UNATTRIBUTABLE_IDS_BY_LEVEL has always claimed "the wiring passes
    ``cleanup_service``'s constant and a test asserts the two are equal"; MEASURED
    2026-10-04 that claim was false on both halves (no parameter, no such test), so this
    parameter and the test beside it are that wiring, finally present.
    """
    level_id = co.as_uint(manifest.get("levelId"))
    # Protection is resolved FOR THIS ROUND'S LEVEL.  The caller's own view is still
    # unioned in, so a caller can only ever TIGHTEN (its set is level-resolved by the
    # caller at the same call site); it cannot un-protect an id.
    protected = protected_ids_for(level_id) | frozenset(protected_ids or ())
    report = {
        "tool": "cleanup_ownership_legs",
        "schemaVersion": MODULE_VERSION,
        "legVersion": LEG_VERSION,
        "roundId": (manifest.get("window") or {}).get("roundId"),
        "levelId": level_id,
        "legs": {
            "A-receipt": "id is carried by a create receipt of this round",
            "B-baseline-difference": "id is in (fresh read-back - pre-create baseline)",
            "C-present-now": "id is in the fresh read-back with the same templateId",
            "D-fresh-readback": "the read-back is accepted, complete, untruncated, for this "
                                "level, timestamped and inside the round window",
            "E-time-window": "the receipt's own create timestamp is inside the round window",
            "F-receipt-provenance": "the receipt file still hashes to what the round recorded",
            "G-frozen-ids": "the id is not one of the unattributable frozen ids",
        },
        "window": None,
        "readback": None,
        "preBaseline": None,
        "difference": None,
        "candidates": [],
        "perId": {},
        "ownedIds": [],
        "refusedIds": [],
        "runRefusals": [],
        "dispatchPerformed": False,
        "deletionPerformed": False,
        "note": "read-only ownership decision; this module cannot reach a delete route",
        "exitCode": 1,
    }
    refusals = []

    if level_id is None:
        report["runRefusals"] = [co.Refusal("LEVEL_ID_INVALID",
                                            "manifest.levelId must be a nonzero uint32").as_json()]
        report["status"] = "refused"
        report["statusBasis"] = "LEVEL_ID_INVALID"
        return report

    window_doc = manifest.get("window") or {}
    window = RoundWindow(roundId=window_doc.get("roundId"), levelId=level_id,
                         startUtc=window_doc.get("startUtc"), stopUtc=window_doc.get("stopUtc"))
    report["window"] = {"roundId": window.roundId, "startUtc": window.startUtc,
                        "stopUtc": window.stopUtc}
    start, stop = window.bounds()
    if start is None or stop is None or start >= stop:
        refusals.append(co.Refusal(
            "WINDOW_INVALID",
            "the round window must be two tz-aware stamps with start < stop; got %r..%r"
            % (window.startUtc, window.stopUtc)))
    if level_id is not None and window.levelId != level_id:
        refusals.append(co.Refusal("LEVEL_ID_INVALID",
                                   "the window names level %s, the round is %s"
                                   % (window.levelId, level_id)))

    # -- Leg D: the pre-cleanup complete read-back -------------------------- #
    readback_spec = manifest.get("freshReadback") or {}
    fresh, readback_refusals = load_fresh_readback(
        _resolve(readback_spec.get("path")) if readback_spec.get("path") else Path("__missing__"),
        read_at_utc=readback_spec.get("readAtUtc"),
        level_id=co.as_uint(readback_spec.get("levelId")),
        complete=readback_spec.get("complete"),
        entity_count=co.as_uint(readback_spec.get("entityCount")),
        sha256=readback_spec.get("sha256"))
    if fresh is None:
        refusals.extend(readback_refusals)
        report["readback"] = {"state": "unavailable",
                              "refusal": readback_refusals[0].as_json()}
    else:
        read_stamp = utc(fresh.readAtUtc)
        if not fresh.accepted:
            refusals.append(co.Refusal(
                "READBACK_NOT_ACCEPTED",
                "the read-back's own acceptance record refused it (%s), so it is not a "
                "usable statement of what is present" % fresh.acceptance))
        if not fresh.complete:
            refusals.append(co.Refusal(
                "READBACK_INCOMPLETE",
                "the read-back cannot show that it captured every entity; an incomplete "
                "read-back is not 'what is present now'"))
        if fresh.entityCount is None or fresh.entityCount != len(fresh.entries):
            refusals.append(co.Refusal(
                "READBACK_TRUNCATED",
                "the read-back claims %r entities but carries %d; a truncated snapshot "
                "cannot certify the presence set"
                % (fresh.entityCount, len(fresh.entries))))
        if fresh.levelId is None:
            refusals.append(co.Refusal(
                "READBACK_LEVEL_UNKNOWN",
                "the read-back does not state which level it observed"))
        elif fresh.levelId != level_id:
            refusals.append(co.Refusal(
                "READBACK_LEVEL_MISMATCH",
                "the read-back observed level %s, the round is level %s"
                % (fresh.levelId, level_id)))
        read_stamp = utc(fresh.readAtUtc)
        if read_stamp is None:
            refusals.append(co.Refusal(
                "READBACK_TIMESTAMP_UNKNOWN",
                "the read-back carries no usable tz-aware read time, so it cannot be placed "
                "inside the round window"))
        elif start is not None and stop is not None and start < stop:
            if not window.contains(read_stamp):
                refusals.append(co.Refusal(
                    "READBACK_NOT_FRESH",
                    "the read-back is dated %s, outside this round's window %s..%s; a "
                    "read-back from before the round is not 'the level as it is now'"
                    % (fresh.readAtUtc, window.startUtc, window.stopUtc)))
        report["readback"] = {
            "path": str(fresh.path), "sha256": fresh.sha256, "shape": fresh.shape,
            "levelId": fresh.levelId, "readAtUtc": fresh.readAtUtc,
            "entityCount": fresh.entityCount, "capturedCount": len(fresh.entries),
            "complete": fresh.complete, "accepted": fresh.accepted,
            "acceptance": fresh.acceptance,
            "state": "usable" if (fresh.accepted and fresh.complete and fresh.levelId == level_id
                                  and fresh.entityCount == len(fresh.entries)
                                  and window.contains(read_stamp))
                     else "refused",
        }

    # -- the pre-create baseline -------------------------------------------- #
    pre_ids, pre_refusals = load_pre_baseline(manifest.get("preBaseline"))
    refusals.extend(pre_refusals)
    if pre_ids is not None:
        report["preBaseline"] = {"entityCount": len(pre_ids),
                                 "ids": sorted(pre_ids) if len(pre_ids) <= 200 else None,
                                 "idsSha256": hashlib.sha256(
                                     ",".join(str(v) for v in sorted(pre_ids))
                                     .encode("utf-8")).hexdigest()}

    # -- the receipts -------------------------------------------------------- #
    supplied_receipts = manifest.get("receipts") or []
    if not supplied_receipts:
        refusals.append(co.Refusal(
            "RECEIPTS_REQUIRED",
            "this round supplied no create receipt at all, so no id can be shown to be its "
            "own; that is not the same statement as 'nothing is owned'"))
    claims, meta, receipt_refusals = load_provenance_receipts(supplied_receipts)
    refusals.extend(receipt_refusals)

    candidates = []
    for value in manifest.get("candidates") or []:
        parsed = co.as_uint(value)
        if parsed is None:
            refusals.append(co.Refusal("CLEANUP_IDS_NOT_UINT32",
                                       "%r is not a nonzero uint32 id" % (value,)))
            continue
        if parsed not in candidates:
            candidates.append(parsed)
    report["candidates"] = candidates

    blocking = [item for item in refusals if item.code in RUN_BLOCKING_CODES]
    if blocking or pre_ids is None:
        # An unusable read-back, an unusable baseline or no receipts at all makes the
        # round undecidable: with the present set unknown, nothing may be owned.
        reason = blocking[0].code if blocking else "ROUND_NOT_DECIDABLE"
        report["runRefusals"] = [item.as_json() for item in refusals]
        report["perId"] = {("%d:%d" % (level_id, entity_id)): {
            "levelId": level_id, "entityId": entity_id, "state": "refused",
            "subState": reason,
            "reason": "the round could not be decided, so nothing is owned"}
            for entity_id in candidates}
        report["refusedIds"] = list(candidates)
        report["difference"] = None
        report["status"] = "refused"
        report["statusBasis"] = ("run-level refusal: %s"
                                 % ",".join(dict.fromkeys(codes(refusals))))
        return report

    # -- Leg B: the evidenced difference ------------------------------------- #
    added = set(fresh.ids()) - set(pre_ids)
    report["difference"] = {
        "addedCount": len(added),
        "addedIds": sorted(added) if len(added) <= 200 else None,
        "addedIdsSha256": hashlib.sha256(",".join(str(v) for v in sorted(added))
                                         .encode("utf-8")).hexdigest(),
        "lostFromReadback": sorted(set(pre_ids) - set(fresh.ids())),
        "note": "fresh read-back minus pre-create baseline; this is the only set a cleanup "
                "may draw from",
    }

    owned = []
    per_id = {}
    for entity_id in sorted(claims):
        key = "%d:%d" % (level_id, entity_id)
        info = meta.get(entity_id) or {}
        claim = claims[entity_id]
        record = {"levelId": level_id, "entityId": entity_id,
                  "receipt": {"requestId": info.get("requestId"),
                              "createdAtUtc": info.get("createdAtUtc"),
                              "fileSha256": info.get("fileSha256"),
                              "sha256Verified": info.get("sha256Verified")}}
        named = (lambda code, detail: (co.Refusal(code, detail, entity_id).as_json(), record))

        def refuse(code, detail, _record=record, _named=None):
            item = co.Refusal(code, detail, entity_id)
            refusals.append(item)
            _record.update(state="refused", subState=code, reason=detail)
            per_id[key] = _record

        # Leg F -- the receipt is the one the round recorded.
        if not info.get("sha256Verified"):
            refuse("RECEIPT_TAMPERED",
                   "receipt %r does not hash to the value the round recorded"
                   % info.get("requestId"))
            continue
        if info.get("requestId") is None:
            refuse("RECEIPT_PROVENANCE_MISSING",
                   "id %d has no receipt provenance, so its create cannot be dated or "
                   "verified" % entity_id)
            continue
        # Leg A / the receipt's own level.  Ambiguity is reported before the level
        # comparison: "which object is this?" precedes "is it in this level?".
        if claim.ambiguous:
            refuse("RECEIPT_AMBIGUOUS_CLAIM",
                   "id %d is bound to more than one template/level" % entity_id)
            continue
        if claim.level_id is None:
            refuse("RECEIPT_LEVEL_ID_MISSING",
                   "id %d: the create receipt carries no levelId" % entity_id)
            continue
        if claim.level_id != level_id:
            refuse("LEVEL_MISMATCH",
                   "id %d was created in level %d, this round is level %d; an id is not an "
                   "ownership credential" % (entity_id, claim.level_id, level_id))
            continue
        # Leg B -- the evidenced baseline difference.
        if entity_id not in added:
            refuse("NOT_NEWLY_ADDED_FROM_BASELINE_DIFFERENCE",
                   "id %d is not in (pre-cleanup read-back minus pre-create baseline): it "
                   "already existed before this round, so this round did not add it"
                   % entity_id)
            continue
        # Leg C -- present now, same template.
        if entity_id not in fresh.entries:
            refuse("ID_NOT_IN_FRESH_READBACK",
                   "id %d is absent from the pre-cleanup complete read-back" % entity_id)
            continue
        fresh_template = fresh.entries[entity_id]
        if claim.template_id is None:
            refuse("RECEIPT_TEMPLATE_ID_MISSING",
                   "id %d: the create receipt carries no templateId, so the third leg "
                   "cannot be checked" % entity_id)
            continue
        if fresh_template is None:
            refuse("BASELINE_TEMPLATE_ID_MISSING",
                   "id %d: the read-back record carries no templateId" % entity_id)
            continue
        if fresh_template != claim.template_id:
            refuse("TEMPLATE_ID_MISMATCH",
                   "id %d: read-back templateId %d != receipt templateId %d"
                   % (entity_id, fresh_template, claim.template_id))
            continue
        # Leg E -- the receipt's own create time is inside this round's window.
        created = utc(info.get("createdAtUtc"))
        if created is None:
            refuse("RECEIPT_TIMESTAMP_UNKNOWN",
                   "receipt %r carries no usable tz-aware create time"
                   % info.get("requestId"))
            continue
        if not window.contains(created):
            refuse("RECEIPT_OUTSIDE_ROUND_WINDOW",
                   "receipt %r is dated %s, outside this round's window %s..%s; a receipt "
                   "from another round is not this round's create"
                   % (info.get("requestId"), info.get("createdAtUtc"),
                      window.startUtc, window.stopUtc))
            continue
        read_stamp = utc(fresh.readAtUtc)
        if read_stamp is not None and created > read_stamp:
            refuse("READBACK_PREDATES_CREATE",
                   "receipt %r is dated %s, after the read-back %s: the object could not be "
                   "in a read-back taken before it existed"
                   % (info.get("requestId"), info.get("createdAtUtc"), fresh.readAtUtc))
            continue
        # Leg G -- the unattributable ids stay frozen.
        if entity_id in protected:
            refuse("CLEANUP_TARGET_UNATTRIBUTABLE",
                   "id %d is one of the ids 2026-09-30 could not attribute; it is removed "
                   "from the owned set even when every other leg holds" % entity_id)
            continue
        record.update(state="owned", subState=None, reason=None)
        owned.append(entity_id)
        per_id[key] = record

    requested = candidates
    for entity_id in requested:
        key = "%d:%d" % (level_id, entity_id)
        if key in per_id:
            continue
        named = refusal_for(refusals, entity_id)
        per_id[key] = {"levelId": level_id, "entityId": entity_id, "state": "refused",
                       "subState": (named.code if named else
                                    ("CLEANUP_TARGET_UNATTRIBUTABLE"
                                     if entity_id in protected
                                     else "CLEANUP_ID_NOT_OWNED_BY_THIS_RUN")),
                       "reason": (named.detail if named else
                                  "no create receipt of this round produced this id")}
        if not named:
            refusals.append(co.Refusal(
                per_id[key]["subState"],
                "id %d did not pass this round's ownership legs" % entity_id,
                entity_id=entity_id))

    report["perId"] = per_id
    # ``ownedIds`` is scoped to what the caller ASKED FOR.  An empty candidate list must
    # never be reported as "everything is owned".
    report["ownedIds"] = sorted(entity_id for entity_id in requested
                                if per_id["%d:%d" % (level_id, entity_id)]["state"] == "owned")
    report["claimedOwnedIds"] = sorted(owned)
    report["refusedIds"] = sorted(entity_id for entity_id in requested
                                  if per_id["%d:%d" % (level_id, entity_id)]["state"] != "owned")
    report["runRefusals"] = [item.as_json() for item in refusals]
    report["status"] = "judged"
    report["statusBasis"] = ("ownership decided by legs A-G; %d owned, %d refused; no "
                            "delete was dispatched" % (len(report["ownedIds"]),
                                                       len(report["refusedIds"])))
    report["exitCode"] = 0
    return report


def as_id(value):
    """A uint32 id from an int or a decimal string (JSON object keys are strings)."""
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("+").isdigit():
            value = int(text)
    return co.as_uint(value)


def check_expectations(report, expect) -> list:
    """Compare a report against an ``expect`` block.  Returns the unmet expectations."""
    unmet = []
    expect = expect or {}
    level = report.get("levelId")
    for entity_id in expect.get("owned") or []:
        parsed = as_id(entity_id)
        row = report["perId"].get("%d:%d" % (level, parsed)) if level else None
        if not row or row.get("state") != "owned":
            unmet.append({"entityId": parsed, "expected": "owned",
                          "observed": (row or {}).get("subState") or "absent"})
    for entity_id, code in (expect.get("refused") or {}).items():
        parsed = as_id(entity_id)
        row = report["perId"].get("%d:%d" % (level, parsed)) if level else None
        if not row or row.get("state") != "refused":
            unmet.append({"entityId": parsed, "expected": "refused",
                          "observed": (row or {}).get("state") or "absent"})
        elif code and row.get("subState") != code:
            unmet.append({"entityId": parsed, "expected": code,
                          "observed": row.get("subState")})
    for entity_id in expect.get("notListed") or []:
        parsed = as_id(entity_id)
        if parsed in (report.get("ownedIds") or []):
            unmet.append({"entityId": parsed, "expected": "not-in-owned-list",
                          "observed": "owned"})
    if "ownedExactly" in expect:
        wanted = sorted(as_id(value) for value in expect["ownedExactly"] or [])
        if sorted(report.get("ownedIds") or []) != wanted:
            unmet.append({"expected": "owned-set-equals", "wanted": wanted,
                          "observed": sorted(report.get("ownedIds") or [])})
    if "runRefusal" in expect:
        wanted = expect["runRefusal"]
        observed = sorted(dict.fromkeys(legs_codes(report.get("runRefusals"))))
        if wanted is None and observed:
            unmet.append({"expected": "no-run-refusal", "observed": observed})
        elif wanted is not None and wanted not in observed:
            unmet.append({"expected": wanted, "observed": observed or "no run refusal"})
    return unmet


def legs_codes(entries):
    return [entry.get("code") if isinstance(entry, dict) else getattr(entry, "code", None)
            for entry in entries or []]


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cli(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, required=True,
                        help="A scenario manifest: one round, or a dict of named scenarios")
    parser.add_argument("--scenario", default=None,
                        help="Only this named scenario (a manifest with no names runs whole)")
    parser.add_argument("--dump", action="store_true", help="Print the full report")
    args = parser.parse_args(argv)
    try:
        document = read_json(args.manifest)
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"code": "MANIFEST_UNREADABLE",
                          "detail": "%s: %s" % (type(error).__name__, error)}))
        return 2
    named = document.get("scenarios") if isinstance(document, dict) else None
    if isinstance(named, dict):
        selected = ([args.scenario] if args.scenario else sorted(named))
        if args.scenario and args.scenario not in named:
            print(json.dumps({"code": "SCENARIO_UNKNOWN", "detail": args.scenario}))
            return 2
        rounds = [(name, named[name]) for name in selected]
    else:
        rounds = [(args.scenario or "round", document)]

    failed = []
    for name, spec in rounds:
        report = judge(spec)
        unmet = check_expectations(report, spec.get("expect"))
        summary = {
            "scenario": name,
            "levelId": report["levelId"],
            "status": report["status"],
            "result": "PASS" if not unmet else "FAIL",
            "ownedIds": report.get("ownedIds"),
            "refusedIds": report.get("refusedIds"),
            "perIdVerdicts": sorted({"%d=%s/%s" % (row["entityId"], row["state"],
                                                   row.get("subState"))
                                     for row in report["perId"].values()}),
            "unmetExpectations": unmet,
            "dispatchPerformed": report["dispatchPerformed"],
            "deletionPerformed": report["deletionPerformed"],
            "exitCode": 0 if not unmet else 1,
        }
        if args.dump:
            summary["report"] = report
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        if unmet:
            failed.append(name)
    print(json.dumps({"scenarios": [name for name, _ in rounds], "failed": failed},
                     ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(cli())
