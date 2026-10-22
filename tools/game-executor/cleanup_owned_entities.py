#!/usr/bin/env python3
"""Bound the "owned" in delete-owned-entity-ids to THIS round's creations.

Why this file exists
--------------------
The two native routes are

    delete-owned-entity-ids-dry-run   (read-only: id -> frontend path mapping)
    delete-owned-entity-ids           (mutating: per-id native delete)

and the word "owned" in their names is a claim about the CALLER's intent, not a
property the server checks.  Nothing in the runner, the bridge or the adapter
compares the ids against "what this run created" -- the adapter's own contract
(Adapter/OwnedEntityDelete.cs) says so in as many words: "the boundary is the ID
LIST and nothing else".  The route is also explicitly NOT atomic: the per-id
re-check can stop the loop early, so a call may delete some ids and never reach
the rest (Adapter/OwnedEntityDelete.cs:112-134).

This module supplies the missing half: the ownership contract for one round.
It never invents a new transport, never talks to the helper directly and never
skips tools/editor-bridge/elevated-request.py -- every live call is that CLI,
with the queue dir passed before the ``call`` subcommand (the only position its
argparse accepts; see elevated-request.py:447-484).

Ownership proof is the three-way intersection required by
docs/ds-handoff/07-ENTITY-CREATE-FULL-RUN.md section 9 step 1:

    A. ids carried by THIS ROUND's create receipts         (--receipts)
    B. ids that are new relative to the pre-create baseline (--pre-baseline)
    C. ids present in the CURRENT full baseline, whose
       templateId equals the receipt's templateId           (--baseline)

  owned = A & B & C

Anything that is not in all three is refused by name and never dispatched.  A
missing leg is a refusal, not a silent pass: no --pre-baseline means leg B is
unavailable, so nothing is owned and nothing is deleted.

Flow (mode=execute)
-------------------
1. normalise receipts + baselines, compute the owned set; refusals stop the run
   before any dispatch;
2. dry-run the owned set (<=64 per call) and require a unique id -> path mapping
   for every id; a refused/ambiguous/mismatched dry-run stops the run -- execute
   is never reached;
3. dispatch the real route in batches of <=64, ONCE per batch, and judge the
   reply per id: dispatched / not-dispatched / never-reached.  A mutation reply
   that cannot be read is an UNKNOWN outcome: the batch is never resent and the
   remaining batches are not dispatched either;
4. re-read (dry-run again, read-only) and, for every id that still exists AND is
   still owned, emit a NEW explicit cleanup operation with a fresh request id.
   This module does not dispatch that operation -- it hands it back to the
   operator.

Nothing here claims atomicity, game effect or persistence.  Those fields are
pinned to false in the report because this layer cannot verify them.

Evidence, and when it is written
-------------------------------
Both output paths are preflighted BEFORE the first dispatch, not after the run:
``--report`` (containment, collision, writability) and ``--readback`` (under
.runtime, recognised shape, non-empty, every entry parseable).  A run that
cannot record or cannot trust its own evidence refuses while nothing has been
sent, so exit 3 keeps its meaning: nothing reached the queue.  If the report
still cannot be written after the run (a race, a full disk), the complete report
is printed on stdout and the exit code is 5 -- deliberately not 3, because the
run did happen.

A supplied ``--readback`` is evidence from outside this layer, so it is held to
the same ownership contract as the live path: the ids it names are intersected
with this round's owned set.  Ids that this round does not own are dropped and
reported as anomalies; they are never called "still owned" and never reach a
generated cleanup operation.  An empty or unreadable readback is not "clean" --
it is unusable evidence, and unusable evidence is never a pass.

Exit codes
----------
0  clean: plan validated (mode=plan) or no owned id remains (mode=execute)
1  refused before any dispatch: nothing was sent to the queue
2  partial: something was dispatched and an owned id still exists, or an id was
   never attempted
3  usage / environment error (bad arguments, unreadable files, bad queue dir,
   unusable --readback).  Every 3 is decided before the first dispatch, so it
   always means "nothing was sent to the queue".
4  outcome unknown: a mutating call returned a reply that could not be read, or
   the re-read evidence cannot be trusted (unrecognised shape, empty, or ids
   this round does not own).  Nothing was retried; stop and reconcile from
   evidence.
5  evidence not persisted: the run reached the verdict carried in the report
   printed on stdout, but --report could not be written.  Never read as
   "nothing was sent"; read the printed report's own exitCode field.

No network, no queue access happens at import time or under --self-test.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ELEVATED_REQUEST = ROOT / "tools/editor-bridge/elevated-request.py"
DEFAULT_PYTHON = ROOT / ".runtime/mcp-venv/Scripts/python.exe"

DRY_OP = "delete-owned-entity-ids-dry-run"
DELETE_OP = "delete-owned-entity-ids"
# 64 is the single shared ceiling: elevated-request.validate_call_ids (1..64),
# elevated-runner (1..64) and OwnedEntityDelete.cs (`ids.Length > 64` throws
# OWNED_DELETE_TOO_MANY_IDS) all agree on it.
MAX_IDS_PER_CALL = 64

ENTITY_ID_KEYS = ("entityId", "createdEntityId", "entity_id")
PLACED_IDS_KEYS = ("placedIds", "placed_ids")
TEMPLATE_ID_KEYS = ("templateId", "template_id")
LEVEL_ID_KEYS = ("levelId", "expectedLevelId", "level_id")
BASELINE_ID_KEYS = ("id", "Id", "entityId")
# ``configId`` is the key the native snapshot actually writes for the template id --
# there is no ``templateId`` in a baseline-context.json or an inspect before-context.json
# at all (MEASURED 2026-10-03 on the live level: configId present on 79/79 entities,
# templateId on 0/79).  Without it ``require_template=True`` refuses EVERY real
# read-back, which is what this tool did: 79 x BASELINE_TEMPLATE_ID_MISSING.
# The four sibling modules already read this key family --
# run_parameter_matrix.ENTITY_TEMPLATE_KEYS, round_materials.READBACK_TEMPLATE_KEYS,
# backend/cleanup_ownership_legs.READBACK_TEMPLATE_KEYS and
# backend/cleanup_service.py:1214-1223 (which documents this exact refusal) -- so this
# is that same key family, not a new leniency: ``templateId`` still wins when present,
# and the value is still compared for equality against the receipt.
BASELINE_TEMPLATE_KEYS = ("templateId", "template_id", "configId", "config_id")

# Exit codes, named so tests and callers do not repeat the numbers.
EXIT_CLEAN = 0
EXIT_REFUSED = 1
EXIT_PARTIAL = 2
EXIT_USAGE = 3
EXIT_UNKNOWN = 4
# The run happened but its --report could not be written.  Distinct from 3 on
# purpose: 3 promises nothing reached the queue, 5 promises nothing else.
EXIT_EVIDENCE_UNWRITTEN = 5

# A refusal blocks the RUN only when the evidence itself is unusable: an
# unreadable receipt/baseline file, a file that is not a set of unique ids, or an
# attempt to dispatch a duplicated list.  Every other refusal is per-id -- the
# named id is dropped and never dispatched, the remaining owned ids still are.
RUN_BLOCKING_CODES = frozenset((
    "RECEIPTS_REQUIRED", "BASELINE_REQUIRED",
    "RECEIPTS_PARSE_ERROR", "RECEIPTS_EMPTY", "RECEIPT_ENTITY_ID_INVALID",
    "BASELINE_PARSE_ERROR", "BASELINE_DUPLICATE_ID", "BASELINE_ENTRY_UNPARSEABLE",
    "ID_DUPLICATE",
))


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def as_uint(value):
    """A JSON integer that is a legal uint32 id, or None.

    Deliberately strict: ``True`` is an int in Python and a float 1.0 is not an
    id.  The runner applies the same test on the CLR type before coercing
    (elevated-runner.ps1, Get-ValidatedCallArguments).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 < value < 2 ** 32 else None


def iter_dicts(node, depth=4):
    """Yield every dict in ``node`` down to ``depth`` levels, innermost included.

    Receipts arrive wrapped differently depending on which layer produced them
    (native action reply, scene_cli envelope, author.py ``backend`` envelope), so
    the extraction walks the envelope instead of betting on one shape.
    """
    if depth < 0:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from iter_dicts(value, depth - 1)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                yield from iter_dicts(value, depth - 1)


def exclusive_write_json(path, payload):
    """Create ``path`` new; never overwrite evidence from an earlier attempt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1, sort_keys=False)
        stream.write("\n")


def load_json_document(path):
    """Read one JSON or JSONL file; a JSONL file becomes a list of records."""
    text = Path(path).read_text(encoding="utf-8-sig")
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        records = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
        return records


# --------------------------------------------------------------------------- #
# Receipts
# --------------------------------------------------------------------------- #

@dataclass
class Claim:
    entity_id: int
    template_id: int | None = None
    level_id: int | None = None
    sources: list = field(default_factory=list)
    ambiguous: bool = False

    def key(self):
        return (self.template_id, self.level_id)


@dataclass
class Refusal:
    code: str
    detail: str
    entity_id: int | None = None
    source: str | None = None

    def as_json(self):
        return {"code": self.code, "detail": self.detail,
                "entityId": self.entity_id, "source": self.source}


def extract_claims(document, source):
    """Pull (entityId, templateId, levelId) triples out of one receipt file.

    Real receipts state the id and its template at DIFFERENT levels of the same
    envelope: the native action record carries levelId/entityId/placedIds
    (native/hook_receipt_probe.cpp:238) while the create command that caused it
    carries templateId, and layer envelopes (scene_cli, author.py ``backend``)
    wrap both.  So template and level are inherited down the envelope: an id
    record takes the nearest enclosing statement of each, and its own if it has
    one.

    A record that states two different templates or levels, or two different
    entity-id keys, is "not uniquely parseable": the id is dropped from the claim
    set and reported, so the caller refuses instead of guessing which object
    this round created.
    """
    claims: dict[int, Claim] = {}
    refusals: list[Refusal] = []

    def record(entity_id, template_id, level_id, where):
        existing = claims.get(entity_id)
        if existing is None:
            claims[entity_id] = Claim(entity_id, template_id, level_id, [where])
            return
        existing.sources.append(where)
        if existing.key() != (template_id, level_id):
            existing.ambiguous = True

    def walk(node, template_id, level_id, depth):
        if depth < 0:
            return
        if isinstance(node, list):
            for value in node:
                walk(value, template_id, level_id, depth - 1)
            return
        if not isinstance(node, dict):
            return
        templates = {as_uint(node[key]) for key in TEMPLATE_ID_KEYS if key in node}
        levels = {as_uint(node[key]) for key in LEVEL_ID_KEYS if key in node}
        ids = [(key, node[key]) for key in ENTITY_ID_KEYS if key in node]
        placed = []
        for key in PLACED_IDS_KEYS:
            value = node.get(key)
            if isinstance(value, list):
                placed.extend((key, item) for item in value)
        conflicting = len(templates) > 1 or len(levels) > 1
        if conflicting and (ids or placed):
            refusals.append(Refusal(
                "RECEIPT_AMBIGUOUS_CLAIM",
                "one envelope states %d templates and %d levels; cannot bind an id to one"
                % (len(templates), len(levels)), source=source))
            # Do not descend: nothing below this node can be attributed safely.
            return
        if ids or placed:
            if len(ids) > 1:
                refusals.append(Refusal(
                    "RECEIPT_AMBIGUOUS_CLAIM",
                    "envelope carries more than one entity-id key: %s"
                    % ",".join(key for key, _ in ids), source=source))
                return
            effective_template = next(iter(templates)) if templates else template_id
            effective_level = next(iter(levels)) if levels else level_id
            for key, raw in ids + placed:
                entity_id = as_uint(raw)
                if entity_id is None and isinstance(raw, str) and raw.strip().isdigit():
                    # The driver records the id as a decimal STRING:
                    # run_parameter_matrix.record_created_id writes
                    # ``"entityId": str(entity_id)`` into created-ids.json, so the one
                    # artifact that states id + templateId together was refused outright
                    # (RECEIPT_ENTITY_ID_INVALID) before the ownership legs ever ran.
                    # This mirrors parse_readback's own precedent -- a digit string is
                    # accepted there for the same reason -- instead of loosening
                    # ``as_uint``, which the live reply path also relies on for CLR
                    # parity.  The value still has to land in 1..2**32-1 to be accepted,
                    # so a padded, signed or over-range string is still refused.
                    entity_id = as_uint(int(raw))
                if entity_id is None:
                    refusals.append(Refusal(
                        "RECEIPT_ENTITY_ID_INVALID",
                        "%s is not a nonzero uint32" % key, source=source))
                    continue
                record(entity_id, effective_template, effective_level,
                       "%s:%s" % (source, key))
        next_template = next(iter(templates)) if templates else template_id
        next_level = next(iter(levels)) if levels else level_id
        for value in node.values():
            if isinstance(value, (dict, list)):
                walk(value, next_template, next_level, depth - 1)

    walk(document, None, None, 4)
    return claims, refusals


def load_receipts(paths):
    claims: dict[int, Claim] = {}
    refusals: list[Refusal] = []
    for path in paths:
        source = str(path)
        try:
            document = load_json_document(path)
        except (OSError, json.JSONDecodeError) as error:
            refusals.append(Refusal("RECEIPTS_PARSE_ERROR",
                                    "%s: %s" % (type(error).__name__, error), source=source))
            continue
        if document is None:
            refusals.append(Refusal("RECEIPTS_EMPTY", "no receipt records", source=source))
            continue
        found, problems = extract_claims(document, source)
        refusals.extend(problems)
        for entity_id, claim in found.items():
            current = claims.get(entity_id)
            if current is None:
                claims[entity_id] = claim
                continue
            current.sources.extend(claim.sources)
            if current.key() != claim.key():
                current.ambiguous = True
    return claims, refusals


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #

def baseline_entries(document):
    """The list of entity records inside a baseline document.

    Accepts a bare list, ``{"entities": [...]}`` (native baseline-context.json)
    and ``{"baseline": {"entities": [...]}}`` (reviewed baseline envelopes).
    """
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        entities = document.get("entities")
        if isinstance(entities, list):
            return entities
        baseline = document.get("baseline")
        if isinstance(baseline, dict) and isinstance(baseline.get("entities"), list):
            return baseline["entities"]
        if baseline is None and any(key in document for key in BASELINE_ID_KEYS):
            return [document]
    raise ValueError("BASELINE_SHAPE_UNSUPPORTED")


def entry_identity(entry):
    """(id, templateId) for one baseline record; either may be None."""
    if not isinstance(entry, dict):
        return None, None
    entity_id = None
    template_id = None
    for node in iter_dicts(entry, depth=3):
        if entity_id is None:
            for key in BASELINE_ID_KEYS:
                if key in node:
                    entity_id = as_uint(node[key])
                    if entity_id is not None:
                        break
        if template_id is None:
            for key in BASELINE_TEMPLATE_KEYS:
                if key in node:
                    template_id = as_uint(node[key])
                    if template_id is not None:
                        break
    return entity_id, template_id


def load_baseline(path, require_template):
    """id -> templateId map plus refusals.

    A duplicate id makes the whole document unparseable: a baseline that names
    the same object twice cannot certify what is present.  ``require_template``
    is False for the pre-create baseline, which is only read for its id set.
    """
    source = str(path)
    refusals: list[Refusal] = []
    try:
        document = load_json_document(path)
        entries = baseline_entries(document)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return {}, [Refusal("BASELINE_PARSE_ERROR",
                            "%s: %s" % (type(error).__name__, error), source=source)]
    by_id: dict[int, int | None] = {}
    for index, entry in enumerate(entries):
        entity_id, template_id = entry_identity(entry)
        if entity_id is None:
            refusals.append(Refusal("BASELINE_ENTRY_UNPARSEABLE",
                                    "entry %d carries no usable id" % index, source=source))
            continue
        if entity_id in by_id:
            refusals.append(Refusal("BASELINE_DUPLICATE_ID",
                                    "id %d appears more than once; the record is not a set"
                                    % entity_id, entity_id=entity_id, source=source))
            continue
        if require_template and template_id is None:
            refusals.append(Refusal("BASELINE_TEMPLATE_ID_MISSING",
                                    "id %d has no templateId in the baseline record"
                                    % entity_id, entity_id=entity_id, source=source))
        by_id[entity_id] = template_id
    return by_id, refusals


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #

def prove_ownership(claims, current, previous, level_id, template_sources=None):
    """Three-way intersection.  Returns (owned_ids, refusals).

    ``previous`` of None means leg B is unavailable, and every id is refused
    with NO_UNIQUE_ADDITION_PROOF rather than passing on two legs.

    Refusal order matters for diagnosis, not for the verdict (all of these are
    fail-closed): an id that was already present before this round is reported
    as NOT_NEWLY_ADDED before its baseline template is compared, because "you
    did not create this" is the useful reason and TEMPLATE_ID_MISMATCH would
    send the operator looking for a template bug that does not exist.

    WHERE THE TEMPLATE COMES FROM (changed 2026-10-08).  The engine's own
    create reply names the entity id but **carries no templateId at all** --
    MEASURED on the live parameter run of 2026-10-08, whose
    ``create-receipt.json`` is ``{reply, backend}`` and states only the id.  So
    this function used to refuse EVERY object that round really created, with
    ``RECEIPT_TEMPLATE_ID_MISSING``, and a run could not delete its own work
    through the supported path.  The template is now resolved from the CURRENT
    BASELINE's own observation of the same id (the native snapshot records
    ``configId``, which is the template: id 1077936130 -> configId 20001002),
    and ``template_sources`` -- when the caller passes a dict -- records which
    leg supplied it, per id, so a reader can see it was an observation and not
    the round's own word.

    This does NOT loosen the proof.  Leg A still requires the id to be named by
    a create receipt of this round; leg B still requires the id to be ABSENT
    from the pre-create baseline; leg C still requires it to be present now
    with a template the native snapshot actually states.  What changed is only
    that a missing receipt template is no longer treated as a missing OBJECT:
    when the receipt DOES state one it is still compared, and a disagreement is
    still TEMPLATE_ID_MISMATCH.
    """
    owned: list[int] = []
    refusals: list[Refusal] = []
    for entity_id in sorted(claims):
        claim = claims[entity_id]
        source = ",".join(claim.sources) if claim.sources else None
        if claim.ambiguous:
            refusals.append(Refusal("RECEIPT_AMBIGUOUS_CLAIM",
                                    "id %d is bound to more than one template/level" % entity_id,
                                    entity_id, source))
            continue
        if claim.level_id is None:
            refusals.append(Refusal("RECEIPT_LEVEL_ID_MISSING",
                                    "id %d: the create receipt carries no levelId" % entity_id,
                                    entity_id, source))
            continue
        if claim.level_id != level_id:
            refusals.append(Refusal("LEVEL_MISMATCH",
                                    "id %d was created in level %d, target is %d"
                                    % (entity_id, claim.level_id, level_id), entity_id, source))
            continue
        if previous is not None and entity_id in previous:
            refusals.append(Refusal("NOT_NEWLY_ADDED",
                                    "id %d already existed in the pre-create baseline" % entity_id,
                                    entity_id, source))
            continue
        if entity_id not in current:
            refusals.append(Refusal("ID_NOT_IN_BASELINE",
                                    "id %d is not present in the current baseline" % entity_id,
                                    entity_id, source))
            continue
        baseline_template = current[entity_id]
        if baseline_template is None:
            refusals.append(Refusal("BASELINE_TEMPLATE_ID_MISSING",
                                    "id %d: the current baseline record carries no templateId"
                                    % entity_id, entity_id, source))
            continue
        if claim.template_id is None:
            # The engine's reply names the id but not its template.  The template is the
            # one the CURRENT BASELINE observed for this same id, and which leg supplied
            # it is recorded rather than left for a reader to guess.
            template_source = "baseline-observation"
        elif baseline_template != claim.template_id:
            refusals.append(Refusal("TEMPLATE_ID_MISMATCH",
                                    "id %d: baseline templateId %d != receipt templateId %d"
                                    % (entity_id, baseline_template, claim.template_id),
                                    entity_id, source))
            continue
        else:
            template_source = "receipt"
        if previous is None:
            refusals.append(Refusal("NO_UNIQUE_ADDITION_PROOF",
                                    "id %d: no pre-create baseline was supplied, so 'new this "
                                    "round' cannot be shown" % entity_id, entity_id, source))
            continue
        owned.append(entity_id)
        if template_sources is not None:
            template_sources[entity_id] = template_source
    return owned, refusals


def build_batches(ids):
    """Split into <=64 chunks, refusing a duplicate or oversized input.

    Returns (batches, refusals).  The duplicate check is defensive: a list that
    names one id twice would make the adapter refuse the whole call
    (OWNED_DELETE_DUPLICATE_ID), so this layer refuses it first.
    """
    refusals: list[Refusal] = []
    if len(set(ids)) != len(ids):
        refusals.append(Refusal("ID_DUPLICATE",
                                "the cleanup list names at least one id more than once"))
        return [], refusals
    if not ids:
        refusals.append(Refusal("NO_OWNED_TARGETS", "the cleanup list is empty"))
        return [], refusals
    return [ids[i:i + MAX_IDS_PER_CALL] for i in range(0, len(ids), MAX_IDS_PER_CALL)], refusals


# --------------------------------------------------------------------------- #
# Dispatch - always through tools/editor-bridge/elevated-request.py
# --------------------------------------------------------------------------- #

@dataclass
class DispatchResult:
    exit_code: int
    argv_tail: list
    stdout: str
    stderr: str
    reply: dict | None
    launch_error: str | None = None


def build_call_argv(python_exe, queue_dir, run_id, op, ids, timeout):
    """The exact CLI shape the source accepts.

    ``--queue-dir`` is a global option on elevated-request.py's top-level parser
    (line 448) while ``--op``/``--run-id``/``--ids`` belong to the ``call``
    subparser, so the queue dir MUST come before the subcommand.  Placing it
    after ``call`` is an argparse error, not a working variant.  The expected
    shape in docs/ds-handoff/07-ENTITY-CREATE-FULL-RUN.md section 9 step 2
    matches this order.
    """
    argv = [str(python_exe), "-B", str(ELEVATED_REQUEST),
            "--queue-dir", str(queue_dir),
            "call", "--op", op, "--run-id", str(run_id),
            "--ids", *[str(int(value)) for value in ids]]
    if timeout is not None:
        argv += ["--timeout", str(float(timeout))]
    return argv


def live_transport(python_exe, queue_dir, run_id, timeout, runner=subprocess.run):
    """One call = one elevated-request.py process.  No other path to the helper."""
    def dispatch(op, ids):
        argv = build_call_argv(python_exe, queue_dir, run_id, op, ids, timeout)
        # Evidence records the shape, not the local paths: the queue directory is
        # environment, and nothing downstream needs it repeated in a report.
        tail = argv[argv.index("call"):]
        try:
            completed = runner(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=float(timeout) + 30.0)
        except Exception as error:  # including subprocess.TimeoutExpired
            return DispatchResult(-1, tail, "", "", None,
                                  launch_error="%s: %s" % (type(error).__name__, error))
        reply = None
        try:
            reply = json.loads(completed.stdout.strip())
        except (json.JSONDecodeError, AttributeError):
            reply = None
        if not isinstance(reply, dict):
            reply = None
        return DispatchResult(completed.returncode, tail, completed.stdout or "",
                              completed.stderr or "", reply)
    return dispatch


def queue_dir_problem(queue_dir, allowed):
    """Containment + type rule for one queue directory, as a path problem.

    A LEXICAL containment test is not enough: a plain file that happens to sit
    under the bridge tree passes it and then dies inside elevated-request.py,
    whose send() calls ``QUEUE.mkdir(parents=True, exist_ok=True)`` -- a
    FileExistsError traceback instead of a usable refusal.  The path must be an
    existing directory, because a queue is created by the load step that
    establishes the helper, never by the caller that is about to use it.
    """
    allowed = Path(allowed).resolve()
    candidate = Path(queue_dir).resolve()
    try:
        candidate.relative_to(allowed)
    except ValueError:
        return Refusal("QUEUE_DIR_NOT_ALLOWED",
                       "queue dir must live under %s" % allowed, source=str(candidate))
    if candidate == allowed:
        return Refusal("QUEUE_DIR_NOT_ALLOWED",
                       "queue dir must be a named queue under %s, not the bridge root" % allowed,
                       source=str(candidate))
    if not candidate.is_dir():
        if candidate.exists():
            return Refusal("QUEUE_DIR_NOT_A_DIRECTORY",
                           "%s exists but is not a directory" % candidate, source=str(candidate))
        return Refusal("QUEUE_DIR_MISSING",
                       "%s does not exist; a queue directory is created by the load step, so a "
                       "missing one means this call has nothing to talk to" % candidate,
                       source=str(candidate))
    return None


def check_queue_dir(queue_dir):
    """queue_dir_problem pinned to this project's bridge tree."""
    return queue_dir_problem(queue_dir, ROOT / ".runtime/editor-bridge")


# --------------------------------------------------------------------------- #
# Reply judgement
# --------------------------------------------------------------------------- #

def classify_dry_run(result, ids):
    """(mapping, refusal) for one dry-run call.

    A dry-run reply is only usable when it confirms a UNIQUE id -> frontend path
    mapping for exactly the ids asked for.  ``matches == 2`` in the adapter's
    refusal means one id resolved to two nodes, which is the ambiguity that must
    block the delete rather than be averaged away.
    """
    if result.launch_error is not None:
        return None, Refusal("DRY_RUN_LAUNCH_ERROR", result.launch_error)
    if result.reply is None:
        return None, Refusal("DRY_RUN_REPLY_UNREADABLE",
                             "exit %d, no JSON object on stdout" % result.exit_code)
    reply = result.reply
    if reply.get("ok") is not True:
        status = reply.get("status")
        if status == "refused-unresolved-ids":
            ambiguous = [row for row in reply.get("unresolved", [])
                         if isinstance(row, dict) and row.get("matches") == 2]
            if ambiguous:
                return None, Refusal(
                    "DRY_RUN_AMBIGUOUS_RESOLUTION",
                    "id(s) %s resolve to more than one node"
                    % ",".join(str(row.get("id")) for row in ambiguous))
            return None, Refusal("DRY_RUN_REFUSED_UNRESOLVED",
                                 "id(s) %s resolve to no node"
                                 % ",".join(str(row.get("id"))
                                            for row in reply.get("unresolved", [])
                                            if isinstance(row, dict)))
        return None, Refusal("DRY_RUN_REFUSED",
                             "ok is not true; status=%r error=%r"
                             % (status, reply.get("error", "")))
    if reply.get("status") != "dry-run-mapping-only":
        return None, Refusal("DRY_RUN_STATUS_UNEXPECTED",
                             "status %r is not dry-run-mapping-only" % reply.get("status"))
    if reply.get("invoked") is not False:
        return None, Refusal("DRY_RUN_INVOKED_UNEXPECTED",
                             "a mapping-only reply reports invoked=%r" % reply.get("invoked"))
    mapping = reply.get("mapping")
    if not isinstance(mapping, list):
        return None, Refusal("DRY_RUN_MAPPING_MISSING", "reply carries no mapping list")
    if reply.get("requested") != len(ids) or reply.get("resolvedCount") != len(ids):
        return None, Refusal("DRY_RUN_MAPPING_MISMATCH",
                             "requested=%r resolvedCount=%r for %d ids"
                             % (reply.get("requested"), reply.get("resolvedCount"), len(ids)))
    paths: dict[int, str] = {}
    for row in mapping:
        if not isinstance(row, dict):
            return None, Refusal("DRY_RUN_MAPPING_MISMATCH", "mapping row is not an object")
        entity_id = as_uint(row.get("id"))
        path = row.get("frontendPath")
        if entity_id is None or not isinstance(path, str):
            return None, Refusal("DRY_RUN_MAPPING_MISMATCH", "mapping row has no id/path")
        if entity_id in paths:
            return None, Refusal("DRY_RUN_AMBIGUOUS_RESOLUTION",
                                 "id %d appears twice in the mapping" % entity_id)
        paths[entity_id] = path
    if set(paths) != set(ids):
        return None, Refusal("DRY_RUN_MAPPING_MISMATCH",
                             "mapping covers %s, expected %s"
                             % (sorted(paths), sorted(ids)))
    return paths, None


def classify_execute(result, ids, dry_mapping=None, detail=None):
    """(ledger, refusal, unknown, warnings) for one delete call.

    The ledger is id -> one of ``dispatched``, ``dispatched:threw-native``,
    ``dispatched:path-mismatch``, ``not-dispatched:target-changed``,
    ``not-attempted``.

    ``unknown`` means the reply itself could not be read: the batch must not be
    resent and no further batch may be dispatched.  It is deliberately NOT raised
    for a per-id oddity: the adapter hardcodes ``invoked: true`` on every row that
    reached the native delete even when that call threw (only the ``invokedCount``
    sum omits the throw, OwnedEntityDelete.cs:128-133), so a thrown native call is
    recorded as a dispatched id with an uncertain result and settled by the
    re-read -- not by declaring the whole batch unknown.

    ``dry_mapping`` is the VERIFIED dry-run mapping for these ids.  The adapter
    re-resolves the node path on every call (OwnedEntityDelete.cs:96,124,133), so
    a delete row whose ``frontendPath`` differs from the one this run validated
    means the object moved between the two calls: the row is still dispatched,
    but it is marked ``dispatched:path-mismatch`` and warned about instead of
    being averaged into a plain ``dispatched``.  ``frontendPath`` is also the
    field the adapter uses to name the node, so it is kept verbatim in
    ``detail["rows"]`` when a caller passes a dict for it.
    """
    if result.launch_error is not None:
        return {}, None, "launch error: " + result.launch_error, []
    if result.reply is None:
        return {}, None, "exit %d with no readable JSON reply" % result.exit_code, []
    reply = result.reply
    if reply.get("ok") is not True:
        if reply.get("status") == "refused-unresolved-ids" and reply.get("invoked") is False:
            # The adapter returns this BEFORE invoking any delete, so this is a
            # clean refusal, not a partial run.
            return {entity_id: "not-dispatched:list-refused" for entity_id in ids}, Refusal(
                "EXECUTE_REFUSED_UNRESOLVED",
                "the adapter refused the whole batch and invoked nothing"), None, []
        return {}, None, "ok is not true; status=%r error=%r" % (reply.get("status"),
                                                                 reply.get("error", "")), []
    if reply.get("status") != "delete-requested-readback-pending":
        return {}, None, "status %r is not delete-requested-readback-pending" % reply.get("status"), []
    results = reply.get("results")
    if not isinstance(results, list):
        return {}, None, "reply carries no results list", []
    ledger = {entity_id: "not-attempted" for entity_id in ids}
    invoked_rows = 0
    threw_rows = 0
    rows_seen = []
    path_mismatches = []
    for row in results:
        if not isinstance(row, dict):
            return {}, None, "results row is not an object", []
        entity_id = as_uint(row.get("id"))
        if entity_id is None or entity_id not in ledger:
            return {}, None, "results name id %r, which was not requested" % row.get("id"), []
        frontend_path = row.get("frontendPath")
        rows_seen.append({"id": entity_id,
                          "frontendPath": frontend_path if isinstance(frontend_path, str) else None,
                          "invoked": row.get("invoked"),
                          "nativeResult": row.get("nativeResult") if "nativeResult" in row else None,
                          "error": row.get("error") if "error" in row else None})
        if row.get("invoked") is True:
            invoked_rows += 1
            native = row.get("nativeResult")
            if isinstance(native, str) and native.startswith("threw:"):
                threw_rows += 1
                status = "dispatched:threw-native"
            else:
                status = "dispatched"
            expected = (dry_mapping or {}).get(entity_id)
            if dry_mapping is not None and expected is not None and frontend_path != expected:
                status = "dispatched:path-mismatch"
                path_mismatches.append({"id": entity_id, "expected": expected,
                                        "observed": frontend_path})
            ledger[entity_id] = status
        elif "error" in row:
            # The pre-delete re-check found the target changed; the adapter
            # breaks out of the loop here, so every later id was never reached
            # (Adapter/OwnedEntityDelete.cs:124-127) and stays not-attempted.
            ledger[entity_id] = "not-dispatched:target-changed"
        else:
            return {}, None, "results row for id %d has invoked=%r" % (entity_id, row.get("invoked")), []
    if detail is not None:
        detail["rows"] = rows_seen
        detail["pathMismatches"] = path_mismatches
    warnings = []
    if path_mismatches:
        warnings.append(
            "delete row frontendPath does not match the dry-run mapping this run verified for "
            "id(s) %s; the adapter re-resolves the path on every call, so the object moved "
            "between the two calls"
            % ",".join(str(item["id"]) for item in path_mismatches))
    counted = reply.get("invokedCount")
    if counted is not None and counted != invoked_rows - threw_rows:
        # A cross-check, not the primary evidence: the rows above are what is
        # read back, and a changed counter must not turn a readable reply into an
        # unknown outcome.
        warnings.append("invokedCount=%r does not match %d invoked rows (%d threw)"
                        % (counted, invoked_rows, threw_rows))
    if reply.get("retryAllowed") is not False:
        warnings.append("reply does not pin retryAllowed=false; a retry is still refused here")
    return ledger, None, None, warnings


# --------------------------------------------------------------------------- #
# Supplied re-read evidence
# --------------------------------------------------------------------------- #

READBACK_KEYS = ("ids", "stillExisting", "residual")


class ReadbackIds(dict):
    """Ids read from a re-read document, plus HOW the document was read.

    A plain ``dict`` so ``set(evidence)`` and ``== {}`` keep working, but it
    also carries the recognised shape and whether the evidence is usable.
    "I could not read this document" is never represented as "the set is
    empty": those are different claims, and only the second can ever mean clean.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shape = "in-process-mapping"
        self.trusted = True
        self.problem = None


def parse_readback(document):
    """Read one re-read document into a :class:`ReadbackIds`.

    Recognised: a bare list of ids; ``{"ids": [...]}`` / ``{"stillExisting":
    [...]}`` / ``{"residual": [...]}``; or a non-empty mapping whose keys are ALL
    id strings (the values are ignored, so a mapping of id -> status is read the
    same as a mapping of id -> path).  Anything else -- a baseline document, an
    envelope, this tool's own report -- is ``shape="unrecognized"`` with
    ``trusted`` false, NOT an empty set.  A recognised document is only trusted
    when every entry parses as an id: one unreadable entry means the document
    cannot be read as a set at all.
    """
    found = ReadbackIds()
    candidates = None
    if isinstance(document, list):
        candidates = document
        found.shape = "bare-list"
    elif isinstance(document, dict):
        for key in READBACK_KEYS:
            if isinstance(document.get(key), list):
                candidates = document[key]
                found.shape = key
                break
        if candidates is None and document and all(
                isinstance(key, str) and key.strip().isdigit() for key in document):
            candidates = list(document)
            found.shape = "keyed-mapping"
    if candidates is None:
        found.shape = "unrecognized"
        found.trusted = False
        found.problem = Refusal(
            "READBACK_SHAPE_UNKNOWN",
            "the supplied re-read is not a bare id list, an ids/stillExisting/residual "
            "list, or a mapping keyed by id, so it cannot be read as 'what still exists'")
        return found
    unusable = []
    for item in candidates:
        entity_id = as_uint(item)
        if entity_id is None and isinstance(item, str) and item.strip().isdigit():
            entity_id = as_uint(int(item))
        if entity_id is None:
            unusable.append(item)
            continue
        found[entity_id] = "supplied"
    if unusable:
        found.trusted = False
        found.problem = Refusal(
            "READBACK_ENTRY_UNPARSEABLE",
            "the supplied re-read carries %d entry/entries that are not uint32 ids: %r"
            % (len(unusable), unusable[:5]))
    return found


def as_readback_evidence(readback):
    """Normalise the in-process argument: None stays None, a mapping is trusted."""
    if readback is None:
        return None
    if isinstance(readback, ReadbackIds):
        return readback
    evidence = ReadbackIds(readback)
    evidence.shape = "in-process-mapping"
    evidence.trusted = True
    return evidence


def load_readback_argument(raw):
    """(ReadbackIds, refusal) for a --readback path, decided BEFORE any dispatch.

    Same containment rule as --report, for the same reason: evidence lives under
    .runtime.  Shape and emptiness are checked here rather than after the delete
    loop, so an unusable document refuses while nothing has been sent instead of
    producing a run whose terminal state cannot be shown.  An empty document is
    refused because this layer cannot tell it apart from a mis-read document,
    and "no ids" must never be read as "nothing remains".
    """
    target = Path(os.path.abspath(raw))
    allowed = Path(os.path.abspath(ROOT / ".runtime"))
    try:
        target.relative_to(allowed)
    except ValueError:
        return None, Refusal("READBACK_OUTSIDE_RUNTIME",
                             "the re-read evidence must live under %s" % allowed,
                             source=str(target))
    try:
        document = load_json_document(target)
    except (OSError, json.JSONDecodeError) as error:
        return None, Refusal("READBACK_PARSE_ERROR",
                             "%s: %s" % (type(error).__name__, error), source=str(target))
    evidence = parse_readback(document)
    if evidence.problem is not None:
        evidence.problem.source = str(target)
        return None, evidence.problem
    if not evidence:
        return None, Refusal(
            "READBACK_EMPTY_UNVERIFIABLE",
            "the supplied re-read parses to zero ids, which this layer cannot tell apart "
            "from a mis-read document, so it is never reported as clean; supply the ids "
            "that still exist or drop --readback and let the run dry-run the re-read itself",
            source=str(target))
    return evidence, None


# --------------------------------------------------------------------------- #
# The cleanup run
# --------------------------------------------------------------------------- #

class CleanupRun:
    """One round's cleanup.  Construct, then call plan() and optionally execute()."""

    def __init__(self, *, receipts, baseline, pre_baseline, level_id, mode,
                 dispatch=None, readback=None, run_id=None, queue_dir=None):
        self.receipts = [Path(path) for path in receipts]
        self.baseline = Path(baseline) if baseline else None
        self.pre_baseline = Path(pre_baseline) if pre_baseline else None
        self.level_id = level_id
        self.mode = mode
        self.dispatch = dispatch
        self.readback = as_readback_evidence(readback)
        self.run_id = run_id
        self.queue_dir = queue_dir
        # id -> frontendPath from the dry-run plan() verified in THIS object.  A
        # delete row is cross-checked against it (classify_execute).
        self.dry_mapping: dict[int, str] = {}
        self.report = {
            "tool": "cleanup_owned_entities",
            "toolVersion": 1,
            "mode": mode,
            "levelId": level_id,
            "runId": run_id,
            "ownedIds": [],
            "batches": [],
            "refusals": [],
            "dryRun": None,
            "dispatches": [],
            "ledger": {},
            "readback": None,
            "residual": [],
            "newCleanupOperation": None,
            "exitCode": EXIT_REFUSED,
            # This layer cannot see the editor model or the formal save, so it
            # never asserts either.  Pinned rather than omitted: an absent field
            # reads as "not applicable", a false one reads as "not proven".
            "gameEffectVerified": False,
            "persistenceVerified": False,
            "atomicity": "none; the route may stop early, so only the per-id ledger is evidence",
        }

    # -- phases ------------------------------------------------------------ #

    def _load(self):
        claims, refusals = load_receipts(self.receipts) if self.receipts else ({}, [])
        if not self.receipts:
            refusals.append(Refusal("RECEIPTS_REQUIRED", "no receipt file was supplied"))
        current, baseline_refusals = ({}, [])
        if self.baseline is None:
            refusals.append(Refusal("BASELINE_REQUIRED", "no current baseline was supplied"))
        else:
            current, baseline_refusals = load_baseline(self.baseline, require_template=True)
        refusals.extend(baseline_refusals)
        previous = None
        if self.pre_baseline is not None:
            loaded, pre_refusals = load_baseline(self.pre_baseline, require_template=False)
            previous = set(loaded)
            refusals.extend(pre_refusals)
        template_sources: dict = {}
        owned, ownership_refusals = prove_ownership(claims, current, previous, self.level_id,
                                                    template_sources=template_sources)
        refusals.extend(ownership_refusals)
        batches, batch_refusals = build_batches(owned) if owned else ([], [])
        refusals.extend(batch_refusals)
        self.report["refusals"] = [item.as_json() for item in refusals]
        self.report["ownedIds"] = owned
        # Per id: which leg supplied the template ("receipt" or "baseline-observation").
        # Published so a reader is never left guessing whether the round's own word or an
        # independent native observation backed the third check.
        self.report["templateSources"] = {str(key): template_sources[key]
                                          for key in sorted(template_sources)}
        self.report["batches"] = batches
        self.report["preBaselineSupplied"] = self.pre_baseline is not None
        return owned, batches, refusals

    def plan(self):
        """Validate, then dry-run every batch.  Never dispatches a delete."""
        self.dry_mapping = {}
        owned, batches, refusals = self._load()
        hard = [item for item in refusals if item.code in RUN_BLOCKING_CODES]
        self.report["runBlocked"] = bool(hard) or not owned
        if hard or not owned:
            if not owned and not hard:
                refusals.append(Refusal("NO_OWNED_TARGETS",
                                        "no id passed the three-way ownership proof"))
                self.report["refusals"] = [item.as_json() for item in refusals]
            self.report["exitCode"] = EXIT_REFUSED
            return self.report
        if self.dispatch is None:
            # Offline ownership audit.  The plan is real; the mapping is not
            # verified, so this run is reported as non-dispatchable rather than
            # as a verified plan.
            self.report["dryRun"] = {
                "performed": False, "mappingVerified": False,
                "note": "no queue supplied; id -> frontend path uniqueness was NOT verified "
                        "and this plan must not be dispatched as-is"}
            self.report["exitCode"] = EXIT_CLEAN
            return self.report

        mappings = []
        for index, batch in enumerate(batches):
            result = self.dispatch(DRY_OP, batch)
            paths, refusal = classify_dry_run(result, batch)
            entry = {"batchIndex": index, "ids": batch, "argvTail": result.argv_tail,
                     "exitCode": result.exit_code,
                     "status": (result.reply or {}).get("status")}
            if refusal is not None:
                entry["refusal"] = refusal.as_json()
                self.report["dryRun"] = {"performed": True, "batches": mappings + [entry],
                                         "mappingVerified": False}
                self.report["refusals"] = self.report["refusals"] + [refusal.as_json()]
                self.report["exitCode"] = EXIT_REFUSED
                return self.report
            entry["mapping"] = [{"id": key, "frontendPath": paths[key]} for key in sorted(paths)]
            mappings.append(entry)
        self.report["dryRun"] = {"performed": True, "batches": mappings, "mappingVerified": True}
        self.dry_mapping = {row["id"]: row["frontendPath"]
                            for entry in mappings for row in entry["mapping"]}
        self.report["exitCode"] = EXIT_CLEAN
        return self.report

    def execute(self):
        """plan(), then dispatch the real route once per batch, then re-read."""
        if self.dispatch is None:
            # execute without a transport could only pretend to have run.
            self.report["exitCode"] = EXIT_USAGE
            self.report["refusals"].append(
                Refusal("QUEUE_DIR_REQUIRED", "execute needs a transport").as_json())
            return self.report
        report = self.plan()
        if report["exitCode"] != EXIT_CLEAN or not (report.get("dryRun") or {}).get("mappingVerified"):
            # No verified dry-run, no delete: the uniqueness of the mapping is the
            # precondition for touching the route at all.
            return report
        batches = report["batches"]
        ledger = {}
        dispatched_batches = set()
        for index, batch in enumerate(batches):
            key = tuple(batch)
            if key in dispatched_batches:
                # Belt and braces: the same id list is never sent twice in one run.
                report["refusals"].append(Refusal(
                    "EXECUTE_BATCH_ALREADY_DISPATCHED",
                    "batch %d was already dispatched" % index).as_json())
                break
            dispatched_batches.add(key)
            result = self.dispatch(DELETE_OP, batch)
            entry = {"batchIndex": index, "ids": batch, "argvTail": result.argv_tail,
                     "exitCode": result.exit_code,
                     "status": (result.reply or {}).get("status")}
            detail = {}
            rows, refusal, unknown, warnings = classify_execute(result, batch,
                                                               self.dry_mapping, detail)
            if detail.get("rows"):
                # frontendPath is kept verbatim: it is the field the adapter uses
                # to name the node, and it is what the cross-check below compared.
                entry["results"] = detail["rows"]
            if detail.get("pathMismatches"):
                entry["frontendPathMismatches"] = detail["pathMismatches"]
            if refusal is not None:
                entry["refusal"] = refusal.as_json()
            if warnings:
                entry["warnings"] = warnings
            if isinstance(result.reply, dict) and "notice" in result.reply:
                # The route's own caveat, kept verbatim in the evidence.
                entry["notice"] = result.reply["notice"]
            if rows:
                entry["ledger"] = rows
                ledger.update(rows)
            report["dispatches"].append(entry)
            if unknown is not None:
                entry["outcomeUnknown"] = unknown
                for entity_id in batch:
                    ledger.setdefault(entity_id, "not-attempted:prior-unknown-outcome")
                for later in batches[index + 1:]:
                    for entity_id in later:
                        ledger.setdefault(entity_id, "not-attempted:prior-unknown-outcome")
                report["exitCode"] = EXIT_UNKNOWN
                report["ledger"] = ledger
                return report
            if refusal is not None:
                report["exitCode"] = EXIT_REFUSED
                report["ledger"] = ledger
                return report
        report["ledger"] = ledger
        return self._readback(ledger)

    def _readback(self, ledger):
        """Re-read the ids, and describe (never dispatch) a fresh cleanup op.

        Every candidate is intersected with THIS round's owned set before it is
        kept.  Supplied evidence can name ids this round never created -- those
        are reported as anomalies and reach neither the residual nor the
        generated operation, and because such evidence is not coherent with the
        round the terminal state is reported as unknown rather than partial.
        """
        owned = set(self.report.get("ownedIds") or [])
        candidates = sorted(set(ledger))
        owned_check = "ids intersected with this round's owned set (report.ownedIds)"
        if self.readback is not None:
            supplied = self.readback
            foreign = sorted(set(supplied) - owned)
            existing = {entity_id: "supplied" for entity_id in sorted(supplied)
                        if entity_id in owned}
            self.report["readback"] = {
                "performed": True, "source": "supplied-evidence",
                "shape": supplied.shape, "trusted": bool(supplied.trusted) and not foreign,
                "ownershipCheck": owned_check,
                "stillExisting": sorted(supplied),
                "ownedStillExisting": sorted(existing),
                "foreignIds": foreign,
            }
            if foreign:
                self.report["refusals"] = self.report["refusals"] + [Refusal(
                    "READBACK_NOT_OWNED",
                    "the supplied re-read names id(s) %s that this round does not own; they are "
                    "dropped from the residual and from any generated operation, and the "
                    "terminal state is unknown because the evidence is not coherent with this "
                    "round" % ",".join(str(value) for value in foreign),
                    entity_id=foreign[0], source="--readback").as_json()]
                self.report["residual"] = sorted(existing)
                self.report["residualOwnershipChecked"] = True
                self.report["ledger"] = ledger
                self.report["newCleanupOperation"] = None
                self.report["exitCode"] = EXIT_UNKNOWN
                return self.report
            if not supplied:
                # Defence in depth for the in-process API: the CLI refuses an
                # empty document earlier, and an empty result must never be read
                # as "nothing remains" here either.
                self.report["readback"]["trusted"] = False
                self.report["refusals"] = self.report["refusals"] + [Refusal(
                    "READBACK_EMPTY_UNVERIFIABLE",
                    "the supplied re-read carries no ids, which cannot be told apart from an "
                    "unreadable document; nothing is declared clean from it").as_json()]
                self.report["residual"] = []
                self.report["residualOwnershipChecked"] = True
                self.report["ledger"] = ledger
                self.report["exitCode"] = EXIT_UNKNOWN
                return self.report
        elif self.dispatch is not None and candidates:
            still = []
            for start in range(0, len(candidates), MAX_IDS_PER_CALL):
                batch = candidates[start:start + MAX_IDS_PER_CALL]
                result = self.dispatch(DRY_OP, batch)
                paths, refusal = classify_dry_run(result, batch)
                if refusal is not None:
                    self.report["readback"] = {"performed": False,
                                               "refusal": refusal.as_json(),
                                               "shape": "dry-run-re-read",
                                               "trusted": False,
                                               "note": "re-read inconclusive; nothing resent"}
                    self.report["exitCode"] = EXIT_UNKNOWN
                    return self.report
                still.extend(paths)
            foreign = sorted(set(still) - owned)
            existing = {entity_id: "resolved" for entity_id in still if entity_id in owned}
            self.report["readback"] = {"performed": True, "source": "dry-run re-read",
                                       "shape": "dry-run-re-read",
                                       "trusted": not foreign,
                                       "ownershipCheck": owned_check,
                                       "stillExisting": sorted(still),
                                       "ownedStillExisting": sorted(existing),
                                       "foreignIds": foreign}
            if foreign:
                self.report["refusals"] = self.report["refusals"] + [Refusal(
                    "READBACK_NOT_OWNED",
                    "the re-read resolved id(s) %s that this round does not own; the residual "
                    "cannot be stated from evidence that leaves the owned set"
                    % ",".join(str(value) for value in foreign)).as_json()]
                self.report["residual"] = sorted(existing)
                self.report["residualOwnershipChecked"] = True
                self.report["ledger"] = ledger
                self.report["newCleanupOperation"] = None
                self.report["exitCode"] = EXIT_UNKNOWN
                return self.report
        else:
            self.report["readback"] = {"performed": False,
                                       "note": "no re-read evidence; residual is unknown"}
            self.report["exitCode"] = EXIT_UNKNOWN
            return self.report

        residual = sorted(existing)
        self.report["residual"] = residual
        self.report["residualOwnershipChecked"] = True
        self.report["ledger"] = ledger
        if not residual:
            self.report["exitCode"] = EXIT_CLEAN
            return self.report
        # Still present AND still owned: the next step is a NEW explicit
        # operation, not a re-send of the list this run already used.
        self.report["newCleanupOperation"] = {
            "requestId": uuid.uuid4().hex,
            "op": DELETE_OP,
            "dryRunOp": DRY_OP,
            "ids": residual,
            "batches": [residual[i:i + MAX_IDS_PER_CALL]
                        for i in range(0, len(residual), MAX_IDS_PER_CALL)],
            "automaticDispatch": False,
            "requiresOperatorDispatch": True,
            "ownershipCheck": owned_check,
            "note": "every residual id was intersected with this round's owned set and is still "
                    "present in the re-read, so it still exists and is still owned; dispatch "
                    "this as a new request, never by resending the old list",
        }
        self.report["exitCode"] = EXIT_PARTIAL
        return self.report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipts", type=Path, nargs="+", required=False, default=None,
                    help="This round's create receipt file(s): JSON or JSONL")
    ap.add_argument("--baseline", type=Path, default=None,
                    help="Current complete entity baseline (id + templateId per record)")
    ap.add_argument("--pre-baseline", type=Path, default=None,
                    help="Pre-create baseline; required to prove 'new this round'")
    ap.add_argument("--level-id", type=int, default=None, help="Target level id (uint32)")
    ap.add_argument("--mode", choices=("plan", "execute"), default="plan",
                    help="plan = validate + dry-run only; execute also dispatches")
    ap.add_argument("--queue-dir", type=Path, default=None,
                    help="Explicit live queue under .runtime/editor-bridge")
    ap.add_argument("--run-id", default=None, help="Bridge run id from the load step")
    ap.add_argument("--python", type=Path, default=DEFAULT_PYTHON,
                    help="Interpreter used to run elevated-request.py")
    ap.add_argument("--call-timeout", type=float, default=300.0,
                    help="Timeout handed to elevated-request.py (its own default is 300)")
    ap.add_argument("--readback", type=Path, default=None,
                    help="Supplied re-read evidence (offline); the live path dry-runs again. "
                         "Must live under .runtime and be a bare id list, an "
                         "ids/stillExisting/residual list, or a mapping keyed by id; ids this "
                         "round does not own, an empty set and an unrecognised shape are refused "
                         "before anything is dispatched")
    ap.add_argument("--report", type=Path, default=None,
                    help="Write the JSON report to this new file under .runtime; the path is "
                         "checked for containment, collision and writability before the first "
                         "dispatch")
    ap.add_argument("--self-test", action="store_true",
                    help="Run the offline fixture suite; never touches a queue")
    return ap


def validate_arguments(args):
    refusals = []
    if as_uint(args.level_id) is None:
        refusals.append(Refusal("LEVEL_ID_INVALID", "--level-id must be a nonzero uint32"))
    if args.mode == "execute":
        if args.queue_dir is None:
            refusals.append(Refusal("QUEUE_DIR_REQUIRED", "execute needs --queue-dir"))
        try:
            # The runner parses runId as a GUID (elevated-runner.ps1 BAD_RUN_ID),
            # so a non-GUID must not reach the queue at all.
            parsed = uuid.UUID(str(args.run_id))
            if str(parsed) != str(args.run_id).lower():
                raise ValueError("not canonical")
        except (ValueError, TypeError, AttributeError):
            refusals.append(Refusal("RUN_ID_INVALID",
                                    "execute needs --run-id as the GUID from the load step"))
    if args.queue_dir is not None:
        problem = check_queue_dir(args.queue_dir)
        if problem is not None:
            refusals.append(problem)
    return refusals


def resolve_report_path(raw):
    """(target, refusal) for --report, decided BEFORE anything is dispatched.

    The path is not just checked for containment and for not already existing:
    the nearest existing ancestor must be a writable directory.  Discovering
    that only after the run is what makes a delete with no evidence possible.
    This is a best-effort preflight -- the write itself can still fail (a race,
    a full disk), which is why the write call has its own exit code.
    """
    target = Path(os.path.abspath(raw))
    allowed = Path(os.path.abspath(ROOT / ".runtime"))
    try:
        target.relative_to(allowed)
    except ValueError:
        return None, Refusal("REPORT_OUTSIDE_RUNTIME",
                             "the report must live under %s" % allowed)
    if target.exists():
        return None, Refusal("REPORT_ALREADY_EXISTS", "refusing to overwrite evidence")
    ancestor = target.parent
    while not ancestor.exists():
        parent = ancestor.parent
        if parent == ancestor:
            break
        ancestor = parent
    if not ancestor.is_dir():
        return None, Refusal("REPORT_UNWRITABLE",
                             "%s is not a directory, so %s cannot be created"
                             % (ancestor, target))
    if not os.access(ancestor, os.W_OK):
        return None, Refusal("REPORT_UNWRITABLE",
                             "%s is not writable, so the report cannot be created there"
                             % ancestor)
    return target, None


def persist_report(report, target):
    """Write the report to ``target``; returns an exit code or None.

    On failure the COMPLETE report is printed to stdout before the refusal, so
    a run that did reach the queue is never left with a verdict nobody can read,
    and the returned code (EXIT_EVIDENCE_UNWRITTEN) is deliberately not the
    usage code: "nothing was sent" and "the evidence did not land" are different
    facts.
    """
    # The two fields describe the write, and they are set before it so the
    # persisted document and the printed one say the same thing -- the failure
    # path corrects them instead of the success path.
    report["reportPath"] = str(target)
    report["reportPersisted"] = True
    try:
        exclusive_write_json(target, report)
    except OSError as error:
        report["reportPersisted"] = False
        report["reportWriteError"] = "%s: %s" % (type(error).__name__, error)
        print(json.dumps(report, ensure_ascii=False, indent=1))
        print(json.dumps(Refusal(
            "REPORT_WRITE_FAILED",
            "the report could not be written to %s; the complete report is printed above and "
            "this exit code says the run happened without its evidence landing" % target
        ).as_json(), ensure_ascii=False))
        return EXIT_EVIDENCE_UNWRITTEN
    return None


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()

    # Every one of these checks runs before the first dispatch: a run that
    # cannot record its evidence, or cannot trust the evidence it was handed,
    # must refuse while nothing has been sent rather than after the fact.
    refusals = validate_arguments(args)
    report_target = None
    if args.report is not None:
        report_target, problem = resolve_report_path(args.report)
        if problem is not None:
            refusals.append(problem)
    readback = None
    if args.readback is not None:
        evidence, problem = load_readback_argument(args.readback)
        if problem is not None:
            refusals.append(problem)
        else:
            readback = evidence
    if refusals:
        for item in refusals:
            print(json.dumps(item.as_json(), ensure_ascii=False))
        return EXIT_USAGE

    dispatch = None
    if args.queue_dir is not None:
        dispatch = live_transport(args.python, args.queue_dir, args.run_id, args.call_timeout)

    run = CleanupRun(receipts=args.receipts or [], baseline=args.baseline,
                     pre_baseline=args.pre_baseline, level_id=args.level_id,
                     mode=args.mode, dispatch=dispatch, readback=readback,
                     run_id=args.run_id, queue_dir=args.queue_dir)
    report = run.execute() if args.mode == "execute" else run.plan()

    if report_target is not None:
        evidence_code = persist_report(report, report_target)
        if evidence_code is not None:
            return evidence_code
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return report["exitCode"]


# --------------------------------------------------------------------------- #
# Offline self-test: fixtures only, no queue, no process, no game
# --------------------------------------------------------------------------- #

def self_test():
    """Fixture suite.  Returns 0 when every assertion holds."""
    failures = []
    checks = 0

    def check(label, condition, detail=""):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append("%s %s" % (label, detail))

    def codes(refusals):
        return [item["code"] if isinstance(item, dict) else item.code for item in refusals]

    LEVEL = 1073741839
    T_A, T_B = 20001034, 20001035

    # --- S1 ownership: three legs, every refusal named -------------------- #
    receipts = [
        {"action": {"levelId": LEVEL, "entityId": 9001}, "templateId": T_A,
         "requestId": "r1"},
        {"action": {"levelId": LEVEL, "entityId": 9002}, "templateId": T_A,
         "requestId": "r2"},
        {"action": {"levelId": LEVEL, "entityId": 9003}, "templateId": T_A,
         "requestId": "r3"},
        {"action": {"levelId": LEVEL, "entityId": 9004}, "templateId": T_A,
         "requestId": "r4"},   # template differs in the baseline
        {"action": {"levelId": LEVEL, "entityId": 9005}, "templateId": T_A,
         "requestId": "r5"},   # not in the current baseline
        {"action": {"levelId": LEVEL, "entityId": 9006}, "templateId": T_A,
         "requestId": "r6"},   # already existed before this round
        {"action": {"levelId": LEVEL, "entityId": 9007}, "requestId": "r7"},
        # no templateId -> leg C impossible
        {"action": {"entityId": 9008}, "templateId": T_A, "requestId": "r8"},
        # no levelId
        {"action": {"levelId": LEVEL + 1, "entityId": 9009}, "templateId": T_A,
         "requestId": "r9"},   # created in another level
        {"action": {"levelId": LEVEL, "entityId": 9010}, "templateId": T_A,
         "requestId": "r10a"},
        {"action": {"levelId": LEVEL, "entityId": 9010}, "templateId": T_B,
         "requestId": "r10b"},  # same id, two templates -> ambiguous
    ]
    pre_baseline = {"entities": [{"id": 8000, "templateId": T_A},
                                 {"id": 9006, "templateId": T_A},
                                 {"id": 9010, "templateId": T_A}]}
    baseline = {"entities": [{"identity": {"Id": 8000}, "templateId": T_A},
                             {"identity": {"Id": 9001}, "templateId": T_A},
                             {"identity": {"Id": 9002}, "templateId": T_A},
                             {"identity": {"Id": 9003}, "templateId": T_A},
                             {"identity": {"Id": 9004}, "templateId": T_B},
                             {"identity": {"Id": 9006}, "templateId": T_A},
                             {"identity": {"Id": 9007}, "templateId": T_A},
                             {"identity": {"Id": 9008}, "templateId": T_A},
                             {"identity": {"Id": 9009}, "templateId": T_A},
                             {"identity": {"Id": 9010}, "templateId": T_A}]}

    claims, receipt_refusals = load_receipts([])
    check("S1 no receipts", receipt_refusals == [])
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        receipts_path = tmp / "receipts.jsonl"
        receipts_path.write_text("\n".join(json.dumps(row) for row in receipts), encoding="utf-8")
        baseline_path = tmp / "baseline.json"
        baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
        pre_path = tmp / "pre.json"
        pre_path.write_text(json.dumps(pre_baseline), encoding="utf-8")

        claims, receipt_refusals = load_receipts([receipts_path])
        current, _ = load_baseline(baseline_path, require_template=True)
        previous, _ = load_baseline(pre_path, require_template=False)
        template_sources: dict = {}
        owned, ownership_refusals = prove_ownership(claims, current, set(previous), LEVEL,
                                                    template_sources=template_sources)
        seen = codes(receipt_refusals) + codes(ownership_refusals)
        # 9007 is now OWNED: its receipt names the id and states no template, which is
        # exactly what the engine's own create reply looks like (MEASURED 2026-10-08 --
        # create-receipt.json is {reply, backend} and carries only the id).  It is owned
        # on the template the CURRENT BASELINE observed for that id, and the report names
        # which leg supplied it, so "the round's own word" is still never the basis.
        check("S1 owned", owned == [9001, 9002, 9003, 9007], str(owned))
        check("S1 a receipt without a template is owned on the OBSERVED template",
              template_sources.get(9007) == "baseline-observation"
              and template_sources.get(9001) == "receipt", str(template_sources))
        for code in ("RECEIPT_LEVEL_ID_MISSING",
                     "LEVEL_MISMATCH", "ID_NOT_IN_BASELINE", "TEMPLATE_ID_MISMATCH",
                     "NOT_NEWLY_ADDED", "RECEIPT_AMBIGUOUS_CLAIM"):
            check("S1 refusal %s" % code, code in seen, str(seen))

        # A missing pre-baseline removes leg B for everything.
        owned_none, refusals_none = prove_ownership(claims, current, None, LEVEL)
        check("S1 no pre-baseline owns nothing", owned_none == [])
        check("S1 NO_UNIQUE_ADDITION_PROOF",
              "NO_UNIQUE_ADDITION_PROOF" in codes(refusals_none))

        # A duplicate id in the baseline is not a set; the document is refused.
        dup_path = tmp / "dup.json"
        dup_path.write_text(json.dumps({"entities": [{"id": 1}, {"id": 1}]}), encoding="utf-8")
        _, dup_refusals = load_baseline(dup_path, require_template=True)
        check("S1 baseline duplicate", "BASELINE_DUPLICATE_ID" in codes(dup_refusals))

        # --- transport fixtures ------------------------------------------- #
        calls = []

        def fake_transport(replies):
            def dispatch(op, ids):
                calls.append((op, list(ids)))
                reply = replies.get(op) if not callable(replies.get(op)) else replies[op](op, ids)
                if isinstance(reply, DispatchResult):
                    return reply
                return DispatchResult(0, ["call", "--op", op], json.dumps(reply), "", reply)
            return dispatch

        def dry_reply(ids, **extra):
            body = {"ok": True, "status": "dry-run-mapping-only", "dryRun": True,
                    "requested": len(ids), "resolvedCount": len(ids),
                    "mapping": [{"id": value, "frontendPath": "/root/%d" % value} for value in ids],
                    "invoked": False, "gameEffectVerified": False,
                    "persistentSaveVerified": False}
            body.update(extra)
            return body

        def delete_reply(ids, invoked_ids, broken_at=None):
            rows = []
            for value in ids:
                if broken_at is not None and value == broken_at:
                    rows.append({"id": value, "frontendPath": "/root/%d" % value,
                                 "invoked": False,
                                 "error": "OWNED_DELETE_TARGET_CHANGED_DURING_PREPARATION"})
                    break
                if value in invoked_ids:
                    rows.append({"id": value, "frontendPath": "/root/%d" % value,
                                 "invoked": True, "nativeResult": True})
            return {"ok": True, "status": "delete-requested-readback-pending", "dryRun": False,
                    "requested": len(ids), "invokedCount": len(rows) - (1 if broken_at is not None else 0),
                    "results": rows, "retryAllowed": False, "gameEffectVerified": False,
                    "persistentSaveVerified": False}

        # --- S2 dry-run refuses an ambiguous id --------------------------- #
        calls.clear()
        run = CleanupRun(receipts=[receipts_path], baseline=baseline_path,
                         pre_baseline=pre_path, level_id=LEVEL, mode="plan",
                         dispatch=fake_transport({DRY_OP: {"ok": False,
                                                          "status": "refused-unresolved-ids",
                                                          "invoked": False,
                                                          "unresolved": [{"id": 9002, "matches": 2}]}}))
        report = run.plan()
        check("S2 exit refused", report["exitCode"] == EXIT_REFUSED, str(report["exitCode"]))
        check("S2 ambiguous code",
              "DRY_RUN_AMBIGUOUS_RESOLUTION" in codes(report["refusals"]))
        check("S2 exactly one dry call", [op for op, _ in calls] == [DRY_OP], str(calls))

        # --- S3 dry-run mapping must cover every id ----------------------- #
        calls.clear()
        partial = {"ok": True, "status": "dry-run-mapping-only", "dryRun": True,
                   "requested": 3, "resolvedCount": 2,
                   "mapping": [{"id": 9001, "frontendPath": "/root/9001"},
                               {"id": 9002, "frontendPath": "/root/9002"}],
                   "invoked": False}
        run = CleanupRun(receipts=[receipts_path], baseline=baseline_path,
                         pre_baseline=pre_path, level_id=LEVEL, mode="execute",
                         dispatch=fake_transport({DRY_OP: partial,
                                                  DELETE_OP: lambda op, ids: AssertionError("MUST NOT DELETE")}))
        report = run.execute()
        check("S3 mapping mismatch", "DRY_RUN_MAPPING_MISMATCH" in codes(report["refusals"]))
        check("S3 no delete dispatched", all(op == DRY_OP for op, _ in calls), str(calls))
        check("S3 no dispatch record", report["dispatches"] == [])

        # --- S4 partial success, residual, new operation ------------------ #
        calls.clear()
        one_batch = receipts_path
        run = CleanupRun(receipts=[one_batch], baseline=baseline_path, pre_baseline=pre_path,
                         level_id=LEVEL, mode="execute",
                         dispatch=fake_transport({
                             DRY_OP: lambda op, ids: dry_reply(ids),
                             DELETE_OP: lambda op, ids: delete_reply(ids, invoked_ids={9001, 9002},
                                                                     broken_at=9003)}),
                         readback={9001: "s", 9002: "s",
                                   9003: "s"})
        report = run.execute()
        ledger = report["ledger"]
        check("S4 ledger dispatched", ledger[9001] == "dispatched" and ledger[9002] == "dispatched",
              str(ledger))
        check("S4 ledger target changed", ledger[9003] == "not-dispatched:target-changed", str(ledger))
        check("S4 exit partial", report["exitCode"] == EXIT_PARTIAL, str(report["exitCode"]))
        check("S4 residual", report["residual"] == [9001, 9002, 9003], str(report["residual"]))
        op = report["newCleanupOperation"]
        check("S4 new operation not dispatched", op["automaticDispatch"] is False)
        check("S4 new operation requestId", re.fullmatch(r"[0-9a-f]{32}", op["requestId"]) is not None)
        check("S4 one dry call and one delete call",
              [o for o, _ in calls] == [DRY_OP, DELETE_OP], str(calls))
        check("S4 delete called once per batch", len(calls) == 2, str(calls))
        check("S4 no atomicity claim", "atomicity" in report)

        # --- S5 unknown outcome stops the rest --------------------------- #
        calls.clear()
        big_receipts = tmp / "many.jsonl"
        rows = [{"action": {"levelId": LEVEL, "entityId": 9001 + index}, "templateId": T_A}
                for index in range(130)]
        big_receipts.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        big_baseline = {"entities": [{"id": 9001 + index, "templateId": T_A}
                                     for index in range(130)]}
        big_baseline_path = tmp / "big-baseline.json"
        big_baseline_path.write_text(json.dumps(big_baseline), encoding="utf-8")
        empty_pre = tmp / "empty-pre.json"
        empty_pre.write_text(json.dumps({"entities": []}), encoding="utf-8")
        run = CleanupRun(receipts=[big_receipts], baseline=big_baseline_path,
                         pre_baseline=empty_pre, level_id=LEVEL, mode="execute",
                         dispatch=fake_transport({
                             DRY_OP: lambda op, ids: dry_reply(ids),
                             DELETE_OP: lambda op, ids: DispatchResult(1, ["call"], "not json", "",
                                                                       None)}))
        report = run.execute()
        check("S5 exit unknown", report["exitCode"] == EXIT_UNKNOWN, str(report["exitCode"]))
        check("S5 batches are 64/64/2",
              [len(b) for b in report["batches"]] == [64, 64, 2], str(report["batches"]))
        check("S5 unknown stops after one delete",
              [o for o, _ in calls] == [DRY_OP, DRY_OP, DRY_OP, DELETE_OP], str(calls))
        check("S5 tracked ledger",
              report["ledger"][9001] == "not-attempted:prior-unknown-outcome")

        # --- S6 batch guard: duplicates and the 64 ceiling ---------------- #
        batches, refusals = build_batches([1, 2, 2])
        check("S6 duplicate refused", batches == [] and "ID_DUPLICATE" in codes(refusals))
        batches, refusals = build_batches(list(range(1, 131)))
        check("S6 three batches", [len(b) for b in batches] == [64, 64, 2], str(batches))
        check("S6 no batch over the ceiling",
              all(len(b) <= MAX_IDS_PER_CALL for b in batches))
        _, refusals = build_batches([])
        check("S6 empty refused", "NO_OWNED_TARGETS" in codes(refusals))

        # --- S7 argv shape ------------------------------------------------ #
        argv = build_call_argv(DEFAULT_PYTHON, "Q", "11111111-2222-3333-4444-555555555555",
                               DELETE_OP, [1, 2], 300.0)
        check("S7 queue dir precedes the subcommand", argv.index("--queue-dir") < argv.index("call"),
              str(argv))
        check("S7 op is the real route", argv[argv.index("--op") + 1] == DELETE_OP)
        check("S7 ids are strings",
              argv[argv.index("--ids") + 1:argv.index("--ids") + 3] == ["1", "2"])
        check("S7 no other script", str(ELEVATED_REQUEST) in argv and argv[2] == str(ELEVATED_REQUEST))

        # A live transport that is handed a fake runner must call only that argv.
        captured = []

        def fake_runner(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(command, 0, json.dumps(dry_reply([1, 2])), "")

        transport = live_transport(DEFAULT_PYTHON, "Q", "11111111-2222-3333-4444-555555555555",
                                  300.0, runner=fake_runner)
        result = transport(DRY_OP, [1, 2])
        check("S7 single process launch", len(captured) == 1, str(captured))
        check("S7 reply parsed", result.reply is not None and result.reply["status"] ==
              "dry-run-mapping-only")
        check("S7 dry classification",
              classify_dry_run(result, [1, 2])[0] == {1: "/root/1", 2: "/root/2"})

        # --- S8 queue dir containment mirror ------------------------------ #
        check("S8 rejects an outside dir",
              check_queue_dir(tmp) is not None)
        check("S8 rejects the bridge root",
              check_queue_dir(ROOT / ".runtime/editor-bridge") is not None)

        # --- S9 receipts: an unreadable file is a refusal, not a pass ------ #
        bad = tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        claims, refusals = load_receipts([bad])
        check("S9 parse error", claims == {} and "RECEIPTS_PARSE_ERROR" in codes(refusals))

        # --- S10 a batch that stops early keeps the untouched ids --------- #
        calls.clear()
        five_receipts = tmp / "five.jsonl"
        five_receipts.write_text("\n".join(
            json.dumps({"action": {"levelId": LEVEL, "entityId": 9001 + index},
                        "templateId": T_A}) for index in range(5)), encoding="utf-8")
        five_baseline = tmp / "five-baseline.json"
        five_baseline.write_text(json.dumps(
            {"entities": [{"id": 9001 + index, "templateId": T_A} for index in range(5)]}),
            encoding="utf-8")
        run = CleanupRun(receipts=[five_receipts], baseline=five_baseline,
                         pre_baseline=empty_pre, level_id=LEVEL, mode="execute",
                         dispatch=fake_transport({
                             DRY_OP: lambda op, ids: dry_reply(ids),
                             DELETE_OP: lambda op, ids: delete_reply(ids, invoked_ids={9001, 9002},
                                                                     broken_at=9003)}),
                         readback={9003: "s", 9004: "s", 9005: "s"})
        report = run.execute()
        check("S10 single delete call", [o for o, _ in calls] == [DRY_OP, DELETE_OP], str(calls))
        check("S10 dispatched rows",
              report["ledger"][9001] == "dispatched" and report["ledger"][9002] == "dispatched",
              str(report["ledger"]))
        check("S10 break row", report["ledger"][9003] == "not-dispatched:target-changed",
              str(report["ledger"]))
        check("S10 unreached rows stay not-attempted",
              report["ledger"][9004] == "not-attempted"
              and report["ledger"][9005] == "not-attempted", str(report["ledger"]))
        check("S10 residual is only what the re-read shows",
              report["residual"] == [9003, 9004, 9005], str(report["residual"]))
        check("S10 partial exit", report["exitCode"] == EXIT_PARTIAL)

        # --- S11 a native call that threw is dispatched, not unknown ------- #
        threw = {"ok": True, "status": "delete-requested-readback-pending", "dryRun": False,
                 "requested": 2, "invokedCount": 1, "retryAllowed": False,
                 "results": [{"id": 9001, "frontendPath": "/root/9001", "invoked": True,
                              "nativeResult": True},
                             {"id": 9002, "frontendPath": "/root/9002", "invoked": True,
                              "nativeResult": "threw:NullReferenceException:boom"}],
                 "notice": "Native true is dispatch only and false may mean no request."}
        ledger, refusal, unknown, warnings = classify_execute(
            DispatchResult(0, [], json.dumps(threw), "", threw), [9001, 9002])
        check("S11 no unknown for a readable reply", unknown is None and refusal is None)
        check("S11 threw row is dispatched:threw-native",
              ledger[9002] == "dispatched:threw-native", str(ledger))
        check("S11 counter cross-check is silent when it matches the adapter",
              warnings == [], str(warnings))
        broken_contract = dict(threw, invokedCount=3)
        _, _, unknown_two, broken_warnings = classify_execute(
            DispatchResult(0, [], json.dumps(broken_contract), "", broken_contract), [9001, 9002])
        check("S11 a mismatched counter is a warning, not a stop",
              unknown_two is None and any("invokedCount" in line for line in broken_warnings),
              str(broken_warnings))

        # --- S12 CLI guards run before anything is launched ---------------- #
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet):
            exit_code = main(["--receipts", str(five_receipts), "--baseline", str(five_baseline),
                              "--pre-baseline", str(empty_pre), "--level-id", str(LEVEL),
                              "--mode", "execute"])
            check("S12 execute without a queue is a usage error", exit_code == EXIT_USAGE,
                  str(exit_code))
            exit_code = main(["--receipts", str(five_receipts), "--baseline", str(five_baseline),
                              "--pre-baseline", str(empty_pre), "--level-id", str(LEVEL),
                              "--mode", "execute", "--queue-dir", str(tmp),
                              "--run-id", "11111111-2222-3333-4444-555555555555"])
            check("S12 queue outside the bridge tree is a usage error", exit_code == EXIT_USAGE,
                  str(exit_code))
            exit_code = main(["--receipts", str(five_receipts), "--baseline", str(five_baseline),
                              "--pre-baseline", str(empty_pre), "--level-id", str(LEVEL),
                              "--mode", "plan"])
            check("S12 offline ownership audit succeeds without a queue", exit_code == EXIT_CLEAN,
                  str(exit_code))
        check("S12 nothing was launched by the CLI guards",
              "RECEIPTS_PARSE_ERROR" not in quiet.getvalue() and
              "QUEUE_DIR_NOT_ALLOWED" in quiet.getvalue())

        # --- S8b the queue path must be a directory, not a file ------------ #
        probe_root = tmp / "bridge"
        (probe_root / "queue").mkdir(parents=True)
        (probe_root / "plain-file.txt").write_text("not a queue", encoding="utf-8")
        check("S8 accepts a real queue dir",
              queue_dir_problem(probe_root / "queue", probe_root) is None)
        check("S8 rejects a plain file under the bridge tree",
              queue_dir_problem(probe_root / "plain-file.txt", probe_root) is not None)
        check("S8 rejects a missing queue dir",
              queue_dir_problem(probe_root / "gone", probe_root) is not None)

    # Everything below needs paths under .runtime, because that is where the
    # report and the re-read evidence must live.  The temporary directory is
    # removed again; nothing else under .runtime is touched.
    runtime_root = ROOT / ".runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=runtime_root) as evidence_tmp:
        evidence_tmp = Path(evidence_tmp)

        # --- S13 supplied re-read: shape, trust, ownership ----------------- #
        unrecognised = parse_readback({"entities": [{"id": 9001}]})
        check("S13 a baseline document is not read as an empty set",
              not unrecognised and not unrecognised.trusted
              and unrecognised.problem is not None, str(unrecognised.problem))
        own_report = parse_readback({"ownedIds": [9001], "residual": [],
                                     "exitCode": 0, "tool": "cleanup_owned_entities"})
        check("S13 this tool's own report is recognised but empty",
              own_report.shape == "residual" and own_report.trusted and not own_report)  # empty
        check("S13 a bare list is read", set(parse_readback([9001, "9002"])) == {9001, 9002},
              str(parse_readback([9001, "9002"])))
        check("S13 a garbage entry untrusts the whole document",
              not parse_readback([9001, "abc"]).trusted)
        check("S13 a scalar mapping is read by key",
              set(parse_readback({"9003": "x"})) == {9003})

        baseline_readback = evidence_tmp / "baseline-as-readback.json"
        baseline_readback.write_text(json.dumps(baseline), encoding="utf-8")
        _, problem = load_readback_argument(baseline_readback)
        check("S13 a baseline as --readback is refused",
              problem is not None and problem.code == "READBACK_SHAPE_UNKNOWN",
              str(problem))
        empty_readback = evidence_tmp / "empty-readback.json"
        empty_readback.write_text(json.dumps({"stillExisting": []}), encoding="utf-8")
        _, problem = load_readback_argument(empty_readback)
        check("S13 an empty --readback is refused, never clean",
              problem is not None and problem.code == "READBACK_EMPTY_UNVERIFIABLE", str(problem))
        _, problem = load_readback_argument(tmp / "outside-runtime.json")
        check("S13 --readback outside .runtime is refused",
              problem is not None and problem.code == "READBACK_OUTSIDE_RUNTIME", str(problem))
        good_readback = evidence_tmp / "good-readback.json"
        good_readback.write_text(json.dumps({"stillExisting": [9003]}), encoding="utf-8")
        evidence, problem = load_readback_argument(good_readback)
        check("S13 a usable --readback is accepted",
              problem is None and set(evidence) == {9003} and evidence.shape == "stillExisting",
              str(problem))

        # A supplied re-read that names an id this round does not own: the id is
        # dropped here, and the CLI refuses before dispatch (S13).
        calls.clear()
        rb_receipts = evidence_tmp / "readback-receipts.jsonl"
        rb_receipts.write_text("\n".join(json.dumps(
            {"action": {"levelId": LEVEL, "entityId": value}, "templateId": T_A})
            for value in (9001, 9002)), encoding="utf-8")
        rb_baseline = evidence_tmp / "readback-baseline.json"
        rb_baseline.write_text(json.dumps({"entities": [
            {"id": 9001, "templateId": T_A}, {"id": 9002, "templateId": T_A}]}),
            encoding="utf-8")
        rb_pre = evidence_tmp / "readback-pre.json"
        rb_pre.write_text(json.dumps({"entities": []}), encoding="utf-8")
        run = CleanupRun(receipts=[rb_receipts], baseline=rb_baseline,
                         pre_baseline=rb_pre, level_id=LEVEL, mode="execute",
                         dispatch=fake_transport({DRY_OP: lambda op, ids: dry_reply(ids),
                                                  DELETE_OP: lambda op, ids: delete_reply(ids, invoked_ids=set(ids))}),
                         readback={9001: "s", 424242: "s"})
        report = run.execute()
        check("S13b a foreign readback id is refused by name",
              "READBACK_NOT_OWNED" in codes(report["refusals"]), str(report["refusals"]))
        check("S13b the foreign id reaches neither residual nor the new operation",
              report["residual"] == [9001] and report["newCleanupOperation"] is None
              and 424242 not in report["residual"], str(report["residual"]))
        check("S13b an incoherent re-read is an unknown outcome",
              report["exitCode"] == EXIT_UNKNOWN, str(report["exitCode"]))
        check("S13b the report says what was checked and what it distrusted",
              report["readback"]["shape"] == "in-process-mapping"
              and report["readback"]["trusted"] is False
              and report["readback"]["foreignIds"] == [424242], str(report["readback"]))

        # --- S14 --report is preflighted, and a failed write is not exit 3 -- #
        new_report = evidence_tmp / "fresh-report.json"
        target, problem = resolve_report_path(new_report)
        check("S14 a fresh path under .runtime is accepted", problem is None and
              target == new_report, str(problem))
        existing_report = evidence_tmp / "collision.json"
        existing_report.write_text("{}", encoding="utf-8")
        _, problem = resolve_report_path(existing_report)
        check("S14 an existing report is refused before any dispatch",
              problem is not None and problem.code == "REPORT_ALREADY_EXISTS", str(problem))
        _, problem = resolve_report_path(ROOT / "outside.json")
        check("S14 a report outside .runtime is refused",
              problem is not None and problem.code == "REPORT_OUTSIDE_RUNTIME", str(problem))
        unwritable = evidence_tmp / "a-file.json" / "report.json"
        (evidence_tmp / "a-file.json").write_text("{}", encoding="utf-8")
        _, problem = resolve_report_path(unwritable)
        check("S14 a report under a plain file is refused",
              problem is not None and problem.code == "REPORT_UNWRITABLE", str(problem))

        written = evidence_tmp / "written.json"
        code = persist_report({"exitCode": EXIT_PARTIAL, "ledger": {9001: "dispatched"}}, written)
        check("S14 a successful write returns no code", code is None)
        check("S14 the persisted document names itself",
              json.loads(written.read_text(encoding="utf-8"))["reportPersisted"] is True)
        broken_target = evidence_tmp / "unwritten.json"
        real_write = globals()["exclusive_write_json"]
        quiet = io.StringIO()
        try:
            globals()["exclusive_write_json"] = lambda *a, **k: (_ for _ in ()).throw(
                OSError("simulated"))
            with contextlib.redirect_stdout(quiet):
                code = persist_report({"exitCode": EXIT_PARTIAL, "ledger": {9001: "dispatched"}},
                                      broken_target)
        finally:
            globals()["exclusive_write_json"] = real_write
        printed = [line for line in quiet.getvalue().splitlines() if line.strip()]
        check("S14 a failed write is not the usage code", code == EXIT_EVIDENCE_UNWRITTEN,
              str(code))
        check("S14 a failed write still prints the complete report",
              len(printed) >= 2 and json.loads(
                  "\n".join(printed[:-1]))["ledger"] == {"9001": "dispatched"},
              str(printed[:2]))
        check("S14 a failed write says why",
              "REPORT_WRITE_FAILED" in printed[-1])
        check("S14 the failed write left no report file", not broken_target.exists())

        # --- S15 the delete reply is cross-checked against the dry-run ----- #
        moved = {"ok": True, "status": "delete-requested-readback-pending", "dryRun": False,
                 "requested": 1, "invokedCount": 1, "retryAllowed": False,
                 "results": [{"id": 9001, "frontendPath": "/root/MOVED/9001",
                              "invoked": True, "nativeResult": True}]}
        detail = {}
        ledger, refusal, unknown, warnings = classify_execute(
            DispatchResult(0, [], json.dumps(moved), "", moved), [9001],
            {9001: "/root/9001"}, detail)
        check("S15 a moved node is not a plain dispatched",
              ledger[9001] == "dispatched:path-mismatch", str(ledger))
        check("S15 the mismatch is warned about, not silent",
              any("frontendPath" in line for line in warnings), str(warnings))
        check("S15 the row keeps frontendPath verbatim",
              detail["rows"][0]["frontendPath"] == "/root/MOVED/9001", str(detail))
        check("S15 the mismatch is recorded as a mismatch",
              detail["pathMismatches"] == [{"id": 9001, "expected": "/root/9001",
                                            "observed": "/root/MOVED/9001"}],
              str(detail["pathMismatches"]))
        same = dict(moved, results=[dict(moved["results"][0], frontendPath="/root/9001")])
        ledger, _, _, warnings = classify_execute(
            DispatchResult(0, [], json.dumps(same), "", same), [9001], {9001: "/root/9001"}, {})
        check("S15 an unchanged path stays dispatched",
              ledger[9001] == "dispatched" and warnings == [], str((ledger, warnings)))

        # --- S16 a pre-existing id is refused for the right reason --------- #
        pre_claims = {9006: Claim(9006, 500, LEVEL, ["r"])}
        _, order_refusals = prove_ownership(pre_claims, {9006: 501}, {9006}, LEVEL)
        check("S16 an id from before this round says NOT_NEWLY_ADDED, not a template clash",
              codes(order_refusals) == ["NOT_NEWLY_ADDED"], str(codes(order_refusals)))
        _, order_refusals = prove_ownership({9004: Claim(9004, 500, LEVEL, ["r"])},
                                            {9004: 501}, set(), LEVEL)
        check("S16 a genuinely new id with the wrong template still says TEMPLATE_ID_MISMATCH",
              codes(order_refusals) == ["TEMPLATE_ID_MISMATCH"], str(codes(order_refusals)))

    print("self-test: %d checks, %d failures" % (checks, len(failures)))
    for line in failures:
        print("FAIL " + line)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
