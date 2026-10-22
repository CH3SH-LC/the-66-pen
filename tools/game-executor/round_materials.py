#!/usr/bin/env python3
"""Producer for one cleanup round's materials (F-011 ``roundMaterials``).

WHY THIS FILE EXISTS
--------------------
``backend/cleanup_service.py`` refuses a cleanup unless the ownership materials carry
``OwnershipMaterials.roundMaterials`` (``CLEANUP_LEGS_MATERIALS_REQUIRED``), and
``backend/cleanup_ownership_legs.py`` ``judge()`` reads exactly four things out of it:

    window        the round's own time window (roundId, startUtc, stopUtc)
    preBaseline   the pre-create baseline (an id set, or a document to read one from)
    freshReadback the complete read-back taken immediately before the cleanup
    receipts      the create receipts, with the round's recorded sha256 for each

All four are EXECUTION-LAYER material: they are statements about what the machine saw
and when.  A model cannot supply them, because a model that could name its own round
window and its own baseline could walk any id into the owned set.  This producer is the
piece that assembles them from artifacts the execution layer already wrote down, and
records where every one of them came from.

WHAT IT WRITES
--------------
A single document, by default

    .runtime/game-executor/mcp-business/cleanup/<roundIdDigest>/round-materials.json

whose top level is a valid ``judge()`` manifest (``levelId`` / ``window`` /
``preBaseline`` / ``freshReadback`` / ``receipts`` / ``candidates``) plus a
``provenance`` block that names the source, the sha256 and the anchor of every part.
The receipt bodies are copied verbatim next to it under ``receipts/<requestId>.json``,
so the round's provenance is self-contained and each ``recordedSha256`` is checkable
against the copy and against the original journal.

THE DIRECTORY NAME IS THE INTERFACE, NOT ``spec.roundId``
---------------------------------------------------------
``backend/entity_server.py`` ``mw_scene_cleanup_owned`` (F-011) does not search for
these materials: it DERIVES the path from the requestIds the caller hands it,

    EVIDENCE_ROOT / 'cleanup' / _cleanup_round_id(createdByRequestIds)
                  / 'round-materials.json'

with ``_cleanup_round_id`` = ``sha256('\\n'.join(sorted(requestIds))).hexdigest()[:32]``
and ``EVIDENCE_ROOT = ROOT/.runtime/game-executor/mcp-business``.  That derivation is a
SECURITY property -- the model never supplies the directory, so it cannot aim the
lookup at another round's materials.  The producer is the other half of the same
contract: it must land the file in exactly the directory the consumer will derive, or
the round's materials exist on disk and are still invisible to the route
(``CLEANUP_ROUND_MATERIALS_UNAVAILABLE``).

``round_id_digest()`` below is that derivation, kept literally identical to
``entity_server.py:1098-1105``; ``require_consumer_directory_name()`` re-derives the
name from the finished document and REFUSES the write when the two disagree, so the
two halves cannot drift apart silently.  ``spec.roundId`` survives as human-readable
METADATA (it is still copied into ``window.roundId`` and ``roundId``) but it is never
used to name a directory.  The document also carries the derived name and the exact
requestId list (``roundIdDigest`` / ``roundRequestIds``) so the caller knows which ids
to pass to ``createdByRequestIds``.

REFUSAL, NEVER A GUESS
----------------------
Every missing, incomplete, truncated, mis-levelled or mis-timestamped material refuses
by name and the output file is NOT written.  A round with no baseline or no complete
read-back must refuse, because "the present set is unknown" is not "nothing is owned".

This module never dispatches, never deletes and never touches the game or the editor.
It reads documents and writes one directory.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
KIND = "cleanup-round-materials"
PRODUCER_ID = "tools/game-executor/round_materials.py"

READBACK_ID_KEYS = ("id", "Id", "entityId")
READBACK_TEMPLATE_KEYS = ("templateId", "template_id", "configId", "config_id")
WINDOW_FIELDS = {"start": "startedUtc", "stop": "finishedUtc"}

#: Ids that no round may ever own: present in the level, no create receipt of any round.
DEFAULT_PROTECTED_IDS = (1077936129, 1077936130, 1077936131)

#: The cleanup materials root, relative to the repository root.  Deliberately the same
#: directory ``backend/entity_server.py`` calls ``EVIDENCE_ROOT / 'cleanup'``
#: (``EVIDENCE_ROOT = ROOT/.runtime/game-executor/mcp-business``, :54).  A producer that
#: wrote anywhere else would be writing materials the route can never find.
CLEANUP_ROOT = Path(".runtime/game-executor/mcp-business/cleanup")
MATERIALS_FILENAME = "round-materials.json"


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
# primitives (kept deliberately independent of backend/ -- this is the lower layer)
# --------------------------------------------------------------------------- #

def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def as_uint(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= 0xFFFFFFFF else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if 0 < parsed <= 0xFFFFFFFF else None
    return None


def as_count(value):
    """A non-negative counter (0 is a legal count, unlike a legal entity id)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def utc(value):
    """A tz-aware UTC datetime or None.  A naive stamp is refused, never assumed."""
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


def iso(stamp):
    return None if stamp is None else \
        stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def find_repo_root(start=None):
    here = Path(start or __file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "backend" / "cleanup_ownership_legs.py").is_file():
            return candidate
    raise Refusal("REPO_ROOT_NOT_FOUND", "no backend/cleanup_ownership_legs.py above %s"
                  % here)


ROOT = find_repo_root()


def resolve(raw):
    if raw is None:
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else (ROOT / path)


def round_id_digest(request_ids) -> str:
    """The cleanup directory the CONSUMER derives for a round's materials.

    IDENTICAL BY CONSTRUCTION to ``_cleanup_round_id`` in ``backend/entity_server.py``
    (:1098-1105): the same ``sorted``, the same ``'\\n'.join``, the same ``sha256`` and
    the same 32-hex truncation.  **The two must be kept in step.**  The consumer's
    version is a security property (the model never supplies the directory, so it cannot
    point the lookup at another round's materials); this one names the directory the
    producer writes.  If they ever disagree, the round's materials are on disk and the
    route still refuses them with ``CLEANUP_ROUND_MATERIALS_UNAVAILABLE`` -- a silent,
    total break of the chain.  A test asserts the two agree by importing and calling the
    real consumer function, with a mutation control (slug in place of the digest) that
    must turn it red.

    The input is the round's create requestIds, as strings -- exactly the list the caller
    must hand ``mw_scene_cleanup_owned``'s ``createdByRequestIds``.
    """
    digest = hashlib.sha256("\n".join(sorted(request_ids)).encode("utf-8")).hexdigest()
    return digest[:32]


# --------------------------------------------------------------------------- #
# the four material readers
# --------------------------------------------------------------------------- #

def readback_facts(path) -> dict:
    """Everything a read-back must say to be usable, read from the document itself.

    ``complete`` is not taken on trust: the native snapshot proves it with the
    ``entities_complete`` flag, a zero rejected count, ``entityCaptured ==
    entityValidEntries == len(entities)`` and a stable ``entityVersionBefore ==
    entityVersionAfter`` -- the two normative checks in
    ``tools/game-executor/build_readonly_profile.py`` (COMPLETE_ENTITY_SET and
    ENTITY_VERSION_CHANGED), folded into the single boolean this reader exposes.  A
    generic read-back must say ``complete: true`` outright.
    """
    target = resolve(path)
    if target is None or not target.is_file():
        raise Refusal("READBACK_UNAVAILABLE", "%s does not exist" % target, target)
    try:
        document = read_json(target)
    except (OSError, json.JSONDecodeError) as error:
        raise Refusal("READBACK_SHAPE_UNKNOWN", "%s: %s" % (type(error).__name__, error),
                      target)
    if not isinstance(document, dict) or not isinstance(document.get("entities"), list):
        raise Refusal("READBACK_SHAPE_UNKNOWN",
                      "the document carries no entity list, so it cannot say what is "
                      "present in the level", target)

    entries = {}
    for entry in document["entities"]:
        if not isinstance(entry, dict):
            continue
        entity_id = None
        for key in READBACK_ID_KEYS:
            entity_id = as_uint(entry.get(key))
            if entity_id is not None:
                break
        if entity_id is None:
            continue
        template = None
        for key in READBACK_TEMPLATE_KEYS:
            template = as_uint(entry.get(key))
            if template is not None:
                break
        entries[entity_id] = template

    counts = document.get("counts") if isinstance(document.get("counts"), dict) else {}
    flags = document.get("flags") if isinstance(document.get("flags"), dict) else {}
    names = flags.get("names") if isinstance(flags.get("names"), list) else []
    observation = (document.get("levelObservation")
                   if isinstance(document.get("levelObservation"), dict) else {})

    if "entities_complete" in names:
        # A-44: mirror COMPLETE_ENTITY_SET + ENTITY_VERSION_CHANGED
        # (tools/game-executor/build_readonly_profile.py:277-278).  The prior transcription
        # compared entityCaptured against entityVersionAfter -- a row count against the
        # monotone world-version counter -- and never consulted entityValidEntries or
        # len(entities), and it dropped the version-stability check entirely.
        captured = as_count(counts.get("entityCaptured"))
        valid_entries = as_count(counts.get("entityValidEntries"))
        version_before = as_count(counts.get("entityVersionBefore"))
        version_after = as_count(counts.get("entityVersionAfter"))
        complete = (as_count(counts.get("entityRejected")) == 0
                    and captured is not None
                    and captured == valid_entries == len(document["entities"])
                    and version_before is not None
                    and version_before == version_after)
        count = as_count(counts.get("entityCaptured"))
        shape = "native-before-context"
    else:
        complete = document.get("complete") is True
        count = as_count(document.get("entityCount"))
        shape = "explicit-readback" if "complete" in document else "generic-baseline"
    if count is None:
        count = len(entries)

    level = as_uint(observation.get("levelId")) if observation.get("verified") is True else None
    if level is None:
        level = as_uint(document.get("levelId"))

    read_at = document.get("readAtUtc")
    exit_doc = {}
    sibling = target.parent / "exit.json"
    if sibling.is_file():
        try:
            exit_doc = read_json(sibling)
        except (OSError, json.JSONDecodeError):
            exit_doc = {}
    acceptance_doc = {}
    acceptance_path = target.parent / "readonly-acceptance.json"
    if acceptance_path.is_file():
        try:
            acceptance_doc = read_json(acceptance_path)
        except (OSError, json.JSONDecodeError):
            acceptance_doc = {}
    if read_at is None:
        read_at = exit_doc.get("startedUtc")

    accepted = True
    if acceptance_doc:
        accepted = acceptance_doc.get("ok") is True
    if accepted and exit_doc.get("exitCode") not in (None, 0):
        accepted = False

    return {
        "path": target, "sha256": sha256_file(target), "shape": shape,
        "levelId": level, "readAtUtc": read_at, "entityCount": count,
        "complete": bool(complete), "accepted": bool(accepted),
        "entries": entries,
        "exitCode": exit_doc.get("exitCode"), "exitStartedUtc": exit_doc.get("startedUtc"),
        "exitFinishedUtc": exit_doc.get("finishedUtc"),
        "readonlyAcceptanceOk": (acceptance_doc.get("ok") if acceptance_doc else None),
    }


def require_usable_readback(facts, level_id, what):
    if not facts["accepted"]:
        raise Refusal("READBACK_NOT_ACCEPTED",
                      "%s: its own acceptance record refused it (exitCode=%r, accepted=%r)"
                      % (what, facts["exitCode"], facts["readonlyAcceptanceOk"]),
                      facts["path"])
    if not facts["complete"]:
        raise Refusal("READBACK_INCOMPLETE",
                      "%s cannot show it captured every entity" % what, facts["path"])
    if facts["entityCount"] != len(facts["entries"]):
        raise Refusal("READBACK_TRUNCATED",
                      "%s claims %r entities but carries %d"
                      % (what, facts["entityCount"], len(facts["entries"])), facts["path"])
    if facts["levelId"] is None:
        raise Refusal("READBACK_LEVEL_UNKNOWN", "%s states no level" % what, facts["path"])
    if facts["levelId"] != level_id:
        raise Refusal("READBACK_LEVEL_MISMATCH",
                      "%s observed level %s, the round is %s"
                      % (what, facts["levelId"], level_id), facts["path"])
    if utc(facts["readAtUtc"]) is None:
        raise Refusal("READBACK_TIMESTAMP_UNKNOWN",
                      "%s carries no usable tz-aware read time" % what, facts["path"])


def window_anchor(run_dir, which) -> dict:
    """(stamp, evidence) taken from a native run directory's own ``exit.json``."""
    field = WINDOW_FIELDS[which]
    directory = resolve(run_dir)
    exit_path = (directory / "exit.json") if directory else None
    if exit_path is None or not exit_path.is_file():
        raise Refusal("WINDOW_ANCHOR_UNAVAILABLE",
                      "no exit.json under %s, so the round window %s cannot be anchored"
                      % (directory, which), exit_path)
    try:
        document = read_json(exit_path)
    except (OSError, json.JSONDecodeError) as error:
        raise Refusal("WINDOW_ANCHOR_UNAVAILABLE", "%s: %s" % (type(error).__name__, error),
                      exit_path)
    stamp = document.get(field)
    if utc(stamp) is None:
        raise Refusal("WINDOW_ANCHOR_UNAVAILABLE",
                      "%s carries no usable %s" % (exit_path, field), exit_path)
    return {"which": which, "field": field, "stamp": stamp, "path": exit_path,
            "sha256": sha256_file(exit_path), "exitCode": document.get("exitCode")}


def receipt_body_matches(body, declared) -> None:
    """The index's declaration must agree with the receipt body it points at."""
    backend = body.get("backend") if isinstance(body, dict) else None
    action = backend.get("action") if isinstance(backend, dict) else \
        (body.get("action") if isinstance(body, dict) else None)
    if action is not None and action != "create":
        raise Refusal("RECEIPT_NOT_A_CREATE",
                      "the receipt records action %r, not a create" % (action,))
    observed = {
        "entityId": backend.get("entityId") if isinstance(backend, dict) else None,
        "levelId": backend.get("levelId") if isinstance(backend, dict) else None,
    }
    command = body.get("command") if isinstance(body, dict) else None
    observed["templateId"] = (command.get("templateId") if isinstance(command, dict)
                              else None) or (backend.get("templateId")
                                             if isinstance(backend, dict) else None)
    for key, declared_value in declared.items():
        seen = as_uint(observed.get(key))
        if seen is not None and declared_value is not None and seen != declared_value:
            raise Refusal("RECEIPT_BODY_MISMATCH",
                          "declared %s=%s but the body says %s"
                          % (key, declared_value, seen))


def capture_receipt(source, dest_dir, request_id) -> dict:
    """Copy one receipt into the round directory, LF-normalised.

    The copy is the round's own artifact (this tree is written with LF only); the
    original's bytes are untouched and its sha256 is recorded next to the copy's, so
    the normalisation is visible rather than silent.
    """
    src = resolve(source)
    if src is None or not src.is_file():
        raise Refusal("RECEIPT_SOURCE_MISSING",
                      "the receipt of requestId %r is not on disk" % request_id, src)
    dest = Path(dest_dir) / ("%s.json" % request_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = src.read_bytes().replace(b"\r\n", b"\n")
    with dest.open("wb") as stream:
        stream.write(raw)
    return {"path": dest, "recordedSha256": sha256_file(dest),
            "sourcePath": src, "sourceSha256": sha256_file(src),
            "lfNormalised": dest.read_bytes() != src.read_bytes()}


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

def build(spec, out_dir) -> dict:
    level_id = as_uint(spec.get("levelId"))
    if level_id is None:
        raise Refusal("LEVEL_ID_INVALID", "spec.levelId must be a nonzero uint32")
    round_id = spec.get("roundId")
    if not isinstance(round_id, str) or not round_id.strip():
        raise Refusal("ROUND_ID_MISSING", "spec.roundId is required to name the round")
    out_dir = Path(out_dir)

    baseline = readback_facts(spec.get("preBaseline"))
    require_usable_readback(baseline, level_id, "the pre-create baseline")
    fresh = readback_facts(spec.get("freshReadback"))
    require_usable_readback(fresh, level_id, "the pre-cleanup read-back")

    window_spec = spec.get("window") or {}
    start = window_anchor(window_spec.get("startFrom"), "start")
    stop = window_anchor(window_spec.get("stopFrom"), "stop")
    start_at, stop_at = utc(start["stamp"]), utc(stop["stamp"])
    if start_at >= stop_at:
        raise Refusal("WINDOW_INVALID",
                      "the window anchors must be start < stop; got %s..%s"
                      % (start["stamp"], stop["stamp"]))
    read_at = utc(fresh["readAtUtc"])
    if not (start_at <= read_at <= stop_at):
        raise Refusal("WINDOW_INVALID",
                      "the read-back %s is outside the window %s..%s"
                      % (fresh["readAtUtc"], start["stamp"], stop["stamp"]))

    # -- receipts ----------------------------------------------------------- #
    index_path = resolve(spec.get("receiptIndex"))
    index_sha = None
    index_entries = []
    if index_path is not None:
        if not index_path.is_file():
            raise Refusal("RECEIPT_INDEX_UNAVAILABLE",
                          "%s does not exist" % index_path, index_path)
        index_sha = sha256_file(index_path)
        document = read_json(index_path)
        raw = document.get("entries") if isinstance(document, dict) else None
        if not isinstance(raw, list):
            raise Refusal("RECEIPT_INDEX_SHAPE_UNKNOWN",
                          "%s carries no entries list" % index_path, index_path)
        index_entries = raw

    declared_index = []
    for entry in index_entries:
        if not isinstance(entry, dict):
            raise Refusal("RECEIPT_INDEX_SHAPE_UNKNOWN", "an index entry is not an object",
                          index_path)
        entity_id = as_uint(entry.get("entityId"))
        request_id = entry.get("requestId")
        level = as_uint(entry.get("levelId"))
        template = as_uint(entry.get("templateId"))
        created = entry.get("createdAtUtc") or entry.get("startedUtc")
        if entity_id is None or not request_id:
            raise Refusal("RECEIPT_FIELD_MISSING",
                          "an index entry names no entityId/requestId", index_path)
        if level is None or template is None:
            raise Refusal("RECEIPT_FIELD_MISSING",
                          "index entry %r names no levelId/templateId" % request_id,
                          index_path)
        if utc(created) is None:
            raise Refusal("RECEIPT_TIMESTAMP_UNKNOWN",
                          "index entry %r carries no usable create time" % request_id,
                          index_path)
        source = entry.get("sourcePath") or entry.get("path")
        declared_index.append({
            "requestId": request_id, "entityId": entity_id, "levelId": level,
            "templateId": template, "createdAtUtc": created, "source": source,
            "indexRecordedSha256": entry.get("recordedSha256"),
            "indexSourceSha256": entry.get("sourceSha256"),
            "claimPath": entry.get("claimPath"),
        })

    declared_extra = []
    for entry in spec.get("extraReceipts") or []:
        entity_id = as_uint(entry.get("entityId"))
        request_id = entry.get("requestId")
        template = as_uint(entry.get("templateId"))
        if entity_id is None or not request_id or template is None:
            raise Refusal("RECEIPT_FIELD_MISSING",
                          "an extra receipt names no entityId/requestId/templateId")
        source = entry.get("sourcePath")
        created = entry.get("createdAtUtc")
        claim_path = resolve(entry.get("claimPath")) if entry.get("claimPath") else None
        if created is None and claim_path is not None and claim_path.is_file():
            # The round's own clock for the create lives in the journal's claim.
            created = read_json(claim_path).get("startedUtc")
        if utc(created) is None:
            raise Refusal("RECEIPT_TIMESTAMP_UNKNOWN",
                          "extra receipt %r has no usable create time" % request_id)
        declared_extra.append({
            "requestId": request_id, "entityId": entity_id, "levelId": level_id,
            "templateId": template, "createdAtUtc": created, "source": source,
            "claimPath": claim_path,
            "createdAtEvidence": entry.get("createdAtEvidence"),
        })

    receipts = []
    excluded = []
    seen = {}

    def exclude(declared, code, detail):
        """A receipt that is real but is not THIS round's create is dropped BY NAME.

        Dropping it from the material set is the same statement leg E/B/C makes
        per id -- and it is recorded in ``excludedReceipts`` so nothing vanishes
        silently.
        """
        excluded.append({"requestId": declared["requestId"],
                         "entityId": declared["entityId"], "code": code,
                         "detail": detail, "source": str(resolve(declared["source"]))})

    for declared in declared_index + declared_extra:
        request_id = declared["requestId"]
        if declared["levelId"] != level_id:
            raise Refusal("RECEIPT_LEVEL_MISMATCH",
                          "receipt %r was created in level %s, this round is %s"
                          % (request_id, declared["levelId"], level_id))
        try:
            body = read_json(resolve(declared["source"]))
        except (OSError, json.JSONDecodeError):
            body = None
        receipt_body_matches(body, {"entityId": declared["entityId"],
                                    "levelId": declared["levelId"],
                                    "templateId": declared["templateId"]})
        entity_id = declared["entityId"]
        in_readback = fresh["entries"].get(entity_id)
        created = utc(declared["createdAtUtc"])
        if in_readback is None:
            exclude(declared, "ID_NOT_IN_FRESH_READBACK",
                    "id %d has a receipt but is absent from the pre-cleanup read-back"
                    % entity_id)
            continue
        if in_readback != declared["templateId"]:
            exclude(declared, "RECEIPT_TEMPLATE_MISMATCH",
                    "id %d: read-back templateId %s != receipt templateId %s"
                    % (entity_id, in_readback, declared["templateId"]))
            continue
        if not (start_at <= created <= stop_at):
            exclude(declared, "RECEIPT_OUTSIDE_ROUND_WINDOW",
                    "receipt %r is dated %s, outside the window %s..%s"
                    % (request_id, declared["createdAtUtc"], start["stamp"], stop["stamp"]))
            continue
        if created > read_at:
            exclude(declared, "READBACK_PREDATES_CREATE",
                    "receipt %r is dated %s, after the read-back %s"
                    % (request_id, declared["createdAtUtc"], fresh["readAtUtc"]))
            continue
        captured = capture_receipt(declared["source"], out_dir / "receipts", request_id)
        record = {
            "requestId": request_id, "entityId": entity_id, "levelId": level_id,
            "templateId": declared["templateId"],
            "createdAtUtc": declared["createdAtUtc"],
            "path": str(captured["path"]),
            "recordedSha256": captured["recordedSha256"],
            "sourcePath": str(captured["sourcePath"]),
            "sourceSha256": captured["sourceSha256"],
            "lfNormalised": bool(captured.get("lfNormalised")),
        }
        for key in ("indexRecordedSha256", "indexSourceSha256", "claimPath",
                    "createdAtEvidence"):
            if declared.get(key) is not None:
                record[key] = str(declared[key])
        if entity_id in seen:
            raise Refusal("RECEIPT_DUPLICATE_ENTITY",
                          "id %d is bound to two receipts (%r and %r)"
                          % (entity_id, seen[entity_id], request_id),
                          declared["source"])
        seen[entity_id] = request_id
        receipts.append(record)

    # -- the difference (the same set the legs will compute) ----------------- #
    added = sorted(set(fresh["entries"]) - set(baseline["entries"]))
    lost = sorted(set(baseline["entries"]) - set(fresh["entries"]))
    difference = {
        "addedCount": len(added), "addedIds": added,
        "addedIdsSha256": hashlib.sha256(
            ",".join(str(v) for v in added).encode("utf-8")).hexdigest(),
        "lostFromReadback": lost,
        "note": "fresh read-back minus pre-create baseline; the only set a cleanup may "
                "draw from",
    }

    candidates = spec.get("candidates")
    if candidates is None:
        candidates = added
    candidates = sorted({as_uint(value) for value in candidates
                         if as_uint(value) is not None})

    provenance_sources = {
        "preBaseline": {"path": str(baseline["path"]), "sha256": baseline["sha256"],
                        "sha256SourcePath": None},
        "freshReadback": {"path": str(fresh["path"]), "sha256": fresh["sha256"],
                          "sha256SourcePath": None},
        "windowStartAnchor": {k: str(v) if isinstance(v, Path) else v
                              for k, v in start.items()},
        "windowStopAnchor": {k: str(v) if isinstance(v, Path) else v
                             for k, v in stop.items()},
        "receiptIndex": ({"path": str(index_path), "sha256": index_sha,
                          "entries": len(index_entries)}
                         if index_path is not None else None),
        "extraReceipts": [{"requestId": item["requestId"],
                           "sourcePath": str(resolve(item["source"])),
                           "createdAtEvidence": item.get("createdAtEvidence")}
                          for item in declared_extra],
    }
    digest = hashlib.sha256(json.dumps({
        "levelId": level_id,
        "window": {"startUtc": start["stamp"], "stopUtc": stop["stamp"]},
        "preBaseline": baseline["sha256"], "freshReadback": fresh["sha256"],
        "receipts": [[r["requestId"], r["recordedSha256"]] for r in receipts],
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    # The round's identity for the CONSUMER is derived from the requestIds of the
    # receipts that survived (the ones that are this round's own creates), not from
    # spec.roundId.  Publishing both the name and the id list is what lets the caller
    # hand ``createdByRequestIds`` exactly the set the directory was derived from.
    round_request_ids = sorted(record["requestId"] for record in receipts)
    round_digest = round_id_digest(round_request_ids)

    document = {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "producer": PRODUCER_ID,
        # spec.roundId is METADATA only; it never names a directory (see the module doc).
        "roundId": round_id,
        "roundIdDigest": round_digest,
        "roundRequestIds": round_request_ids,
        "levelId": level_id,
        # -- the manifest judge() reads ------------------------------------- #
        "window": {"roundId": round_id, "startUtc": start["stamp"],
                   "stopUtc": stop["stamp"]},
        "preBaseline": {"path": str(baseline["path"]), "sha256": baseline["sha256"],
                        "shape": baseline["shape"],
                        "entityCount": len(baseline["entries"])},
        "freshReadback": {"path": str(fresh["path"]), "sha256": fresh["sha256"],
                          "shape": fresh["shape"], "levelId": fresh["levelId"],
                          "readAtUtc": fresh["readAtUtc"],
                          "entityCount": fresh["entityCount"],
                          "complete": fresh["complete"], "accepted": fresh["accepted"]},
        "receipts": receipts,
        "excludedReceipts": excluded,
        "candidates": candidates,
        # -- the round's own record of where all four came from ------------- #
        "difference": difference,
        "provenance": {
            "capturedAtUtc": iso(datetime.now(timezone.utc)),
            "capturedBy": PRODUCER_ID,
            "note": "execution-layer material: the window, the baseline, the read-back and "
                    "the receipt hashes were read from artifacts on disk, not supplied by "
                    "a model; the model may not widen any of them",
            "sources": provenance_sources,
            "digest": digest,
            "protectedIds": sorted(as_uint(v) for v in
                                   (spec.get("protectedIds") or DEFAULT_PROTECTED_IDS)),
        },
    }
    return document


def write_document(document, out_path) -> Path:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, ensure_ascii=False, indent=1, sort_keys=False)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.write("\n")
    return target


def require_consumer_directory_name(document, target_dir) -> str:
    """The directory name must be what the consumer will DERIVE, or nothing is written.

    Re-derives the name from the finished document's own receipt requestIds and compares
    it with the directory the file is about to be placed in.  A mismatch is not a warning:
    the consumer would compute the derived name and look there, so the materials would be
    invisible (``CLEANUP_ROUND_MATERIALS_UNAVAILABLE``) while appearing to have been
    written.  Refusing -- and naming both directories -- is the only way this stays
    impossible to break silently.
    """
    expected = round_id_digest([record["requestId"]
                                for record in document.get("receipts") or []])
    observed = Path(target_dir).name
    if observed != expected:
        raise Refusal(
            "ROUND_DIRECTORY_NAME_MISMATCH",
            "backend/entity_server.py derives this round's directory from its requestIds "
            "and would look in cleanup/%s/, but the materials are being placed in "
            "cleanup/%s/; the route would refuse them with "
            "CLEANUP_ROUND_MATERIALS_UNAVAILABLE, so this write is refused instead"
            % (expected, observed),
            target_dir)
    return expected


def relocate_materials(document, staging_dir, final_dir) -> Path:
    """Move a staged build to the directory the CONSUMER will look in.

    The build needs an ``out_dir`` up front (the receipt copies go under
    ``<out_dir>/receipts/``), but the directory's name is only known once the document
    is assembled -- it is a digest of the surviving receipts' requestIds.  So the build
    runs in a staging directory and is relocated here.

    The receipt copies travel with the document, and the document's own record of where
    each copy lives is REWRITTEN to the final location: a ``path`` still pointing at the
    staging directory would make every receipt ``RECEIPT_MISSING`` (leg F) the moment
    staging is cleaned up.  Each relocated copy is re-hashed and must still equal the
    ``recordedSha256`` the document carries, so the move cannot silently alter evidence.
    """
    staging_dir = Path(staging_dir)
    final_dir = Path(final_dir)
    staging_receipts = staging_dir / "receipts"
    final_receipts = final_dir / "receipts"
    for record in document.get("receipts") or []:
        request_id = record["requestId"]
        source = Path(record["path"])
        if source.parent != staging_receipts:
            raise Refusal("STAGING_SHAPE_UNEXPECTED",
                          "a staged receipt path %s is not under %s"
                          % (source, staging_receipts), source)
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["recordedSha256"]:
            raise Refusal("STAGED_RECEIPT_CHANGED",
                          "the staged copy of receipt %r no longer hashes to the value "
                          "the round recorded" % request_id, source)
        final_receipts.mkdir(parents=True, exist_ok=True)
        dest = final_receipts / ("%s.json" % request_id)
        dest.write_bytes(raw)
        record["path"] = str(dest)
    target = final_dir / MATERIALS_FILENAME
    write_document(document, target)
    return target


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _summary(document, target_dir, wrote) -> dict:
    return {
        "status": "written" if wrote else "assembled",
        "wrote": str(wrote) if wrote else None,
        "targetDir": str(target_dir),
        "roundId": document["roundId"],
        "roundIdDigest": document["roundIdDigest"],
        # Hand EXACTLY this list to mw_scene_cleanup_owned's createdByRequestIds: the
        # directory above is round_id_digest() of it, and the consumer derives the same
        # name from the same ids.
        "createdByRequestIds": document["roundRequestIds"],
        "levelId": document["levelId"],
        "window": document["window"],
        "addedCount": document["difference"]["addedCount"],
        "receipts": len(document["receipts"]),
        "digest": document["provenance"]["digest"],
    }


def cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, required=True,
                        help="the execution-layer round spec (see spec in the tree)")
    parser.add_argument("--out", type=Path, default=None,
                        help="round-materials.json to write; defaults to "
                             ".runtime/game-executor/mcp-business/cleanup/"
                             "<roundIdDigest>/round-materials.json, where <roundIdDigest> "
                             "is sha256 of the round's requestIds.  Even when --out is "
                             "given its parent directory name must BE that digest: "
                             "backend/entity_server.py derives the path and never searches "
                             "for it, so a name the route would not derive is refused")
    parser.add_argument("--dry-run", action="store_true",
                        help="assemble and validate, report the resolved target directory, "
                             "and write nothing (staging happens outside the tree)")
    args = parser.parse_args(argv)

    try:
        spec = read_json(args.spec)
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({"code": "MATERIAL_SPEC_UNREADABLE",
                          "detail": "%s: %s" % (type(error).__name__, error)}))
        return 2
    if not isinstance(spec, dict):
        print(json.dumps({"code": "MATERIAL_SPEC_UNREADABLE",
                          "detail": "the spec is not an object"}))
        return 2

    # The directory name is a digest of the surviving receipts' requestIds, so it is only
    # knowable AFTER the build -- but the build needs an out_dir to copy the receipts
    # into.  Build in a staging directory outside the tree, then relocate (see
    # relocate_materials) once the derived name is known.
    staging = Path(tempfile.mkdtemp(prefix="round-materials-staging-"))
    try:
        try:
            document = build(spec, staging)
        except Refusal as refusal:
            print(json.dumps({"status": "refused", "refusal": refusal.as_json(),
                              "wrote": None}, ensure_ascii=False))
            return 1

        target_dir = (Path(args.out).parent if args.out is not None
                      else ROOT / CLEANUP_ROOT / document["roundIdDigest"])
        try:
            # Refuse before writing anything if the destination is not the directory the
            # consumer will derive from this document's own requestIds.
            require_consumer_directory_name(document, target_dir)
            if args.dry_run:
                print(json.dumps(_summary(document, target_dir, None),
                                 ensure_ascii=False, indent=1))
                return 0
            target = relocate_materials(document, staging, target_dir)
            # Re-check where it actually landed, not where it was meant to go.
            require_consumer_directory_name(document, Path(target).parent)
        except Refusal as refusal:
            print(json.dumps({"status": "refused", "refusal": refusal.as_json(),
                              "wrote": None}, ensure_ascii=False))
            return 1

        print(json.dumps(_summary(document, target_dir, target),
                         ensure_ascii=False, indent=1))
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(cli())
