#!/usr/bin/env python3
"""Authenticity layer for the entity.create run (provenance contract v1).

READ THIS BEFORE TRUSTING IT
============================
This is a READ-ONLY verifier.  It CANNOT make a run unforgeable against an
adversary who has the same write access to this repository.  Everything it reads
-- the run, and the "outside" producer directories -- is a file on this disk.
An adversary who can write into ``.runtime/editor-bridge/elevated-queue/`` can
fabricate corroborating receipts there exactly as easily as they can fabricate
the run.  **F-010 is not "closed" by this file.**  What it does is raise the cost
from "write one directory" to "write one directory AND plant mutually
corroborating records in the real producer spaces, with ids that line up"; and it
refuses the specific forgeries that were demonstrated.

Residual forgeries this file still does NOT stop:
  R1 an adversary with write access to a producer root can plant a corroborating
     record there (the check is existence, not the provenance of the writer);
  R2 an adversary who can edit ``--corpus-roots`` (only when the operator passes
     it explicitly) can point corroboration at their own directory -- the default
     roots are hard-coded and are not chosen by the run;
  R3 a real, correctly produced run from another round whose ids this run copies
     could, in principle, corroborate -- not demonstrated, but not excluded.

They are emitted verbatim in every verdict under ``residualLimits``.

WHAT IT ADDS OVER verify_entity_create_run.py
---------------------------------------------
The frozen gate recomputes a run's *internal* consistency.  Two independent
review rounds (DS-10, W8) showed that a run built entirely from text passes it:
empty gate bodies, wrong ids, a historical log with its ``runId`` key deleted, and
a run whose evidence merely asserts ``status: pass`` all reached exit 0.

This layer never lets the run define what counts as proof:

  1. INDEPENDENT DISCOVERY -- expected values come from a corpus built by
     scanning fixed producer directories (helper receipts under
     ``editor-bridge/elevated-queue``, native activity under
     ``game-executor/scene-cli``, bridge runs under ``editor-bridge/runs``).
     The run under audit supplies only the *question* ("does anyone outside know
     this requestId?"), never the answer.  An invented id is in no receipt.
  2. BODY SEMANTICS -- the run's own evidence is parsed.  A body that declares
     ``ok: false``, ``status: fail/failed/blocked/not-run``, ``live: false`` or
     ``simulated: true`` is a defect; so is an evidence body that is literally
     empty (``{}``), which is how DS-10's ``empty-shell`` forges 55 gate files.
  3. ECHO DETECTION -- every token the anchor is required to name must ALSO be
     found in the independent corpus.  An anchor that merely echoes the run
     corroborates nothing.
  4. EXTERNAL EXISTENCE -- a live-mode body that names a ``nativeRun`` directory
     must name one that exists on disk, outside the run.
  5. SOURCE SCOPE -- a source locator is run-supplied, so it must resolve inside a
     REAL producer directory: the roots the producer itself DECLARES (``author.py``
     ``PRODUCER_ROOTS``) or RECORDS (``.runtime/entity-create/provenance-roots.json``).
     A locator that names the repository root, a parent, or an absolute path
     elsewhere is refused by name (``PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE`` /
     ``_COVERS_RUN``) rather than honoured: honouring it lets the run's own text
     witness the run, and walking it costs a whole-repository rglob.  A producer
     EXPLICITLY REDIRECTED to a real production directory elsewhere is still
     honoured, because the allowed roots are DERIVED from the producer's
     configuration instead of being a hard-coded list of the default paths.

A run is accepted only when the frozen gate exits 0 AND this layer reports no
defect.  There is no relaxation switch: every obligation in
``provenance-contract-v1.md`` is always enforced.  Mutation controls live in the
test suite, not in this interface.

Exit codes: 0 accept, 1 reject, 2 could not judge (unusable invocation).

    python -B verify_run_provenance.py <run-root> [--base <verifier>]
                                       [--corpus-roots DIR ...] [--output PATH]
                                       [--quiet]

Read-only contract: the ONLY file this program writes is ``--output`` (and it
refuses a path inside the run under audit).  Everything else goes to stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_ID_RE = re.compile(r"[0-9a-f]{32}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
HEX32_RE = re.compile(r"^[0-9a-f]{32}$")

PROVENANCE_NAME = "provenance.input.json"
PROVENANCE_KIND = "entity-create-run-provenance"
PROVENANCE_SCHEMA = 1

FROZEN_CHECKLIST_RELATIVE = "docs/ds-handoff/07-ENTITY-CREATE-CHECKLIST.json"
FROZEN_CHECKLIST_SHA256 = "84540680083c07df2413116bb212633eac80137cf29f1dc8b30c5862344abc83"

#: Where real producers leave their own artifacts.  Hard-coded: the run under
#: audit does not get to choose where corroboration is looked for.
DEFAULT_CORPUS_ROOTS = (
    ".runtime/editor-bridge/elevated-queue",
    ".runtime/game-executor/scene-cli",
    ".runtime/editor-bridge/runs",
)

#: R03 -- the ALLOWED SCOPE of a source locator must be DERIVED from the producer's
#: own configuration, not restated here as a list of the default paths.  The producer
#: that writes ``provenance.input.json`` (``tools/entity-create/write_run_provenance_input.py``)
#: is TOLD its roots (``--roots``) and refuses any root its own ``SOURCE_ROOT_KEYS``
#: does not name; the values are ``tools/authoring/author.py``'s ``PRODUCER_ROOTS``,
#: materialised (on this machine) at ``.runtime/entity-create/provenance-roots.json``.
#: A producer that was EXPLICITLY REDIRECTED (a staging tree, a different drive) thus
#: writes a source locator under a real production directory that is NOT
#: ``<repo>/.runtime/...``.  A hard-coded whitelist of the DEFAULTS would refuse that
#: legitimate source -- the exact false positive this rework removes.  So the layer
#: reads the two producer-side documents below (both outside the audited run) and
#: allows whatever they name.
PRODUCER_ROOTS_MODULE_RELATIVE = "tools/authoring/author.py"
PRODUCER_ROOTS_CONFIG_RELATIVE = ".runtime/entity-create/provenance-roots.json"
SOURCE_ROOT_KEYS = ("receiptRoot", "nativeRoot", "queueRoot", "journalRoot")

#: Floor, not the source of truth: with NO producer configuration on disk (a bare
#: checkout, or a unit test that supplies ``allowed_source_roots`` explicitly) the
#: standard roots stay allowed.  Never the ONLY allowed roots on a configured tree.
FALLBACK_ALLOWED_SOURCE_ROOTS = DEFAULT_CORPUS_ROOTS + (".runtime/authoring/requests",)

LIVE_PRODUCER_KINDS = frozenset({"author-journal", "helper-receipt", "native-run-dir"})
NON_LIVE_KINDS = frozenset({"formal-file-copy"})
ALLOWED_KINDS = LIVE_PRODUCER_KINDS | NON_LIVE_KINDS

FAILURE_WORDS = frozenset({"fail", "failed", "failure", "error", "errored", "not-run",
                           "not_run", "notrun", "blocked", "not-applicable",
                           "not_applicable", "aborted", "rejected", "refused"})

TEXT_SUFFIXES = (".json", ".jsonl", ".txt", ".log", ".meta", ".ndjson")
SKIP_SUFFIXES = (".gil", ".gip", ".exe", ".dll", ".obj", ".lib", ".exp", ".pkl",
                 ".png", ".jpg", ".pyc", ".zip", ".7z", ".bin")
MAX_FILE_BYTES = 8 << 20


class InputError(Exception):
    """The layer could not judge at all."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, what: str):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"{what}: cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InputError(f"{what}: {path} is not valid UTF-8 JSON: {exc}") from exc


def repo_root_from(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / FROZEN_CHECKLIST_RELATIVE).is_file():
            return candidate
    raise InputError(f"cannot locate repository root above {start}")


def is_within(child: Path, parent: Path) -> bool:
    child_text = os.path.normcase(str(child.resolve()))
    parent_text = os.path.normcase(str(parent.resolve()))
    if child_text == parent_text:
        return True
    return child_text.startswith(parent_text.rstrip("\\/") + os.sep)


def parse_utc(value):
    if not isinstance(value, str) or len(value) < 16:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# the independent corpus: what the world outside the run actually recorded
# --------------------------------------------------------------------------- #

class ExternalCorpus:
    """Harvest every requestId/entityId/levelId/pid/time a real producer emitted.

    The scan is expensive (the real producer spaces hold ~10k files), so the
    result is collected in memory only -- no cache file is written, because the
    honest path must always re-read the world.
    """

    def __init__(self, roots, exclude: frozenset):
        self.roots = list(roots)
        self.exclude = exclude
        self.tokens = set()
        self.request_ids = set()
        self.entity_ids = set()
        self.level_ids = set()
        self.pids = set()
        self.time_min = None
        self.time_max = None
        self.files_scanned = 0
        self.bytes_scanned = 0
        self.corroborators = {}      # token -> set of file names

    def _note(self, token, where):
        self.tokens.add(token)
        self.corroborators.setdefault(token, set()).add(where)

    def _absorb(self, key, value, where):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            text = str(value)
        elif isinstance(value, str):
            text = value
        else:
            return
        lowered = key.lower()
        if "requestid" in lowered or lowered == "request":
            if HEX32_RE.fullmatch(text):
                self.request_ids.add(text)
        if "entityid" in lowered:
            try:
                self.entity_ids.add(int(value))
            except (TypeError, ValueError):
                pass
        if "levelid" in lowered or lowered == "level":
            try:
                self.level_ids.add(int(value))
            except (TypeError, ValueError):
                pass
        if lowered in ("pid", "host_pid", "hostpid", "gamepid", "game_pid"):
            try:
                self.pids.add(int(value))
            except (TypeError, ValueError):
                pass
        if "utc" in lowered or "time" in lowered or "date" in lowered:
            stamp = parse_utc(text)
            if stamp is not None:
                if self.time_min is None or stamp < self.time_min:
                    self.time_min = stamp
                if self.time_max is None or stamp > self.time_max:
                    self.time_max = stamp
        self._note(text, where)

    def _walk(self, value, where, key=""):
        if isinstance(value, dict):
            for sub_key, item in value.items():
                self._absorb(sub_key, item, where)
                self._walk(item, where, str(sub_key))
        elif isinstance(value, list):
            for item in value:
                self._walk(item, where, key)
        elif isinstance(value, str):
            if HEX32_RE.fullmatch(value):
                self._note(value, where)

    def _absorb_text(self, text: str, where: str):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line[0] in "{[":
                try:
                    self._walk(json.loads(line), where)
                    continue
                except ValueError:
                    pass
            for token in re.split(r"[^0-9A-Za-z]+", line):
                if token and HEX32_RE.fullmatch(token):
                    self._note(token, where)

    def scan(self) -> None:
        for root in self.roots:
            if not root.exists():
                continue
            for item in sorted(root.rglob("*")):
                if not item.is_file():
                    continue
                if item.suffix.lower() in SKIP_SUFFIXES:
                    continue
                if item.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                try:
                    if item.stat().st_size > MAX_FILE_BYTES:
                        continue
                    if item.resolve() in self.exclude:
                        continue
                    raw = item.read_bytes()
                except OSError:
                    continue
                where = str(item)
                self.files_scanned += 1
                self.bytes_scanned += len(raw)
                text = raw.decode("utf-8", "replace")
                try:
                    self._walk(json.loads(text), where)
                except ValueError:
                    self._absorb_text(text, where)

    def has(self, token) -> bool:
        return str(token) in self.tokens

    def corroborated_by(self, token):
        return sorted(self.corroborators.get(str(token), ()))


# --------------------------------------------------------------------------- #
# the layer
# --------------------------------------------------------------------------- #

class ProvenanceLayer:
    def __init__(self, run_root: Path, base_verdict: dict, base_exit, repo_root: Path,
                 corpus_roots=None, corpus_explicit: bool = False,
                 base_skipped: bool = False, allowed_source_roots=None):
        self.run_root = run_root.resolve()
        self.base_verdict = base_verdict
        self.base_exit = base_exit
        self.base_skipped = base_skipped
        self.repo_root = repo_root
        self.corpus_roots = (list(corpus_roots) if corpus_roots is not None
                             else [repo_root / r for r in DEFAULT_CORPUS_ROOTS])
        #: R03 -- the allowed scope of a source locator, DERIVED (see below) from the
        #: producer's own configuration rather than restated here.  Unlike
        #: ``corpus_roots`` it is NOT the ``--corpus-roots`` test seam: an operator may
        #: widen the corroboration space (R2) but must not widen the set of directories
        #: a run may name as its own outside witness.  ``allowed_source_roots`` is an
        #: explicit override for unit tests; the production path leaves it None.
        self.allowed_source_roots = (
            self._normalise_allowed_roots(allowed_source_roots)
            if allowed_source_roots is not None
            else self._derive_allowed_source_roots())
        self.corpus_explicit = corpus_explicit
        self.defects = []
        self.checks = 0
        self.notes = []
        self.sources_checked = 0
        self.bindings_checked = 0
        # A47 degeneracy accounting (observation only; see verdict()).
        self.targets_with_visible_body = 0
        self.degenerate_bindings = 0
        self.degenerate_no_visible_body = 0
        self.degenerate_body_without_ids = 0
        self.distinct_binding_predicates = set()
        #: R02 -- one diagnosis record per bound target (observation only; it
        #: is rendered by ``degenerate_report()`` and changes no verdict field).
        self.degenerate_records = []
        self.binding_undiscriminating = False
        self.warnings = []
        self.required_gate_targets = []
        self.required_case_targets = {}
        self.frozen_sha256 = None
        self.corpus = None
        self.index = {}

    def defect(self, code, detail):
        self.defects.append({"code": code, "detail": detail})

    # -- denominators (frozen checklist, never the run's own copy) ---------- #

    def load_frozen(self):
        path = self.repo_root / FROZEN_CHECKLIST_RELATIVE
        actual = sha256_file(path)
        if actual != FROZEN_CHECKLIST_SHA256:
            raise InputError(
                f"frozen checklist {path} sha256 {actual} != pinned {FROZEN_CHECKLIST_SHA256}")
        self.frozen_sha256 = actual
        frozen = read_json(path, "frozen checklist")
        self.frozen_gates = {}
        for gate in frozen.get("gates") or []:
            if isinstance(gate, dict) and gate.get("required", True) and isinstance(gate.get("id"), str):
                self.frozen_gates[gate["id"]] = gate
        self.frozen_cases = {}
        for key in ("templateCases", "parameterCases"):
            for entry in frozen.get(key) or []:
                if isinstance(entry, dict) and entry.get("required", True):
                    self.frozen_cases[str(entry.get("caseId"))] = entry
        for gate_id, gate in self.frozen_gates.items():
            for name in (gate.get("evidenceRequired") or []):
                self.required_gate_targets.append(f"gate:{gate_id}/{name}")
        layout = (frozen.get("evidenceLayout") or {}).get("perCase")
        stages = layout if isinstance(layout, list) and layout else [
            "intent", "before", "raw-call", "after", "verification", "cleanup"]
        for case_id in self.frozen_cases:
            self.required_case_targets[case_id] = [f"case:{case_id}/{s}" for s in stages]

    def target_requires_live(self, target: str) -> bool:
        tokens = lambda m: {t for t in re.split(r"[^A-Za-z]+", m or "") if t}
        if target.startswith("gate:"):
            gate_id = target.split(":", 1)[1].split("/", 1)[0]
            return "live" in tokens((self.frozen_gates.get(gate_id) or {}).get("evidenceMode"))
        case_id = target.split(":", 1)[1].split("/", 1)[0]
        return "live" in tokens((self.frozen_cases.get(case_id) or {}).get("evidenceMode"))

    # -- the run's own body for a target (used ONLY as a question, never proof) #

    def body_path(self, target: str):
        """Where the run keeps its own evidence for this target, or None."""
        kind, rest = target.split(":", 1)
        if kind == "gate":
            gate_id, name = rest.split("/", 1)
            for item in (self.index.get("gates") or []):
                if not isinstance(item, dict) or item.get("id") != gate_id:
                    continue
                for entry in (item.get("evidence") or []):
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("name") == name or f"{name}.json" == entry.get("name"):
                        rel = entry.get("path")
                        if isinstance(rel, str):
                            candidate = (self.run_root / rel)
                            if candidate.is_file():
                                return candidate
            # S02's evidence name is "session.json" and its file is "session.json.json".
            #
            # R02 (2026-10-05): this fallback must NOT be gated by evidence-index.json.  It
            # used to live INSIDE the ``for item in self.index.get("gates")`` loop above, so a
            # run that carries ``gate-evidence/<gateId>/<name>.json`` in the documented layout
            # but no index had EVERY gate target invisible: with ``self.index == {}`` the loop
            # body never ran and this returned None for all of them.  An invisible body collapses
            # that target's expected tokens to ``{runId}``, so the layer under-witnesses -- it
            # can only make the layer WEAKER, never stricter, and MEASURED 2026-10-05 by the R02
            # worker's M6/F1 mutation controls (write the gate body but no index -> still
            # ``absent``; add a minimal index -> the same fixture becomes visible).
            #
            # Hoisting it out of the loop makes the fallback unconditional, i.e. a strict
            # superset of the bodies that were visible before.  Reading the layout the producer
            # actually writes can only TIGHTEN expected_tokens; it never loosens a verdict.
            for suffix in (f"{name}.json", f"{name}"):
                candidate = self.run_root / "gate-evidence" / gate_id / suffix
                if candidate.is_file():
                    return candidate
            return None
        case_id, stage = rest.split("/", 1)
        for base in ("cases", "adapter-evidence"):
            candidate = self.run_root / base / case_id / f"{stage}.json"
            if candidate.is_file():
                return candidate
        # The parameter driver writes ``<run>/cases/<caseId>/a<attempt>/<stage>.json``
        # -- ONE directory deeper than the layout above.  MEASURED 2026-10-03 across the
        # whole corpus: the flat ``cases/<caseId>/<stage>.json`` has ZERO files and no
        # producer writes it, so this branch never fired and EVERY case body was
        # invisible.  That is what collapsed every expected-token set to the single token
        # ``[runId]`` (A46/A47: 469 bindings, distinctBindingPredicates=1).  Reading the
        # layout the producer actually writes makes more of the run's own evidence
        # visible, which can only TIGHTEN expected_tokens -- it never loosens a verdict.
        # Deterministic pick when a case ran more than one attempt: the greatest attempt.
        attempts = []
        for path in (self.run_root / "cases" / case_id).glob(f"a*/{stage}.json"):
            match = re.fullmatch(r"a(\d+)", path.parent.name)
            if match and path.is_file():
                attempts.append((int(match.group(1)), path))
        if attempts:
            return sorted(attempts)[-1][1]
        return None

    def run_body(self, target: str):
        path = self.body_path(target)
        return None if path is None else self._load(path)

    @staticmethod
    def _load(path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # -- expected tokens: what the outside world must already know ---------- #

    def expected_tokens(self, target: str, run_id: str) -> list:
        tokens = [run_id]
        body = self.run_body(target)
        if isinstance(body, dict):
            for key in ("levelId", "requestId"):
                value = body.get(key)
                if isinstance(value, (int, str)) and not isinstance(value, bool):
                    tokens.append(str(value))
        if target.startswith("case:"):
            case_id = target.split(":", 1)[1].split("/", 1)[0]
            after = self._load(self.run_root / "cases" / case_id / "after.json") or \
                self._load(self.run_root / "adapter-evidence" / case_id / "after.json")
            if isinstance(after, dict):
                for entity_id in (after.get("createdEntityIds") or []):
                    if isinstance(entity_id, (int, str)) and not isinstance(entity_id, bool):
                        tokens.append(str(entity_id))
        return tokens

    # -- body semantics ----------------------------------------------------- #

    #: Only these evidence files are expected to carry a JSON body.  The frozen
    #: checklist also asks for ``report.md``; a markdown artifact is the gate's
    #: business, not this layer's.
    JSON_BODY_SUFFIXES = (".json", ".jsonl", ".ndjson")

    def check_body(self, target: str) -> None:
        path = self.body_path(target)
        if path is None:
            return  # the frozen gate already reports absent evidence
        if path.suffix.lower() not in self.JSON_BODY_SUFFIXES:
            return
        try:
            raw = path.read_bytes()
        except OSError as exc:
            self.defect("PROVENANCE_EVIDENCE_BODY_UNREADABLE",
                        f"{target}: cannot read {path}: {exc}")
            return
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.defect("PROVENANCE_EVIDENCE_BODY_UNREADABLE",
                        f"{target}: {path.name} exists but is not readable UTF-8 JSON "
                        f"({len(raw)} bytes); an unparseable body proves nothing")
            return
        if isinstance(body, dict) and not body:
            self.defect("PROVENANCE_EVIDENCE_BODY_EMPTY",
                        f"{target}: the run's own evidence body is an empty JSON object; "
                        "an empty body asserts nothing and cannot stand in for a producer")
            return
        if not isinstance(body, dict):
            self.defect("PROVENANCE_EVIDENCE_BODY_NOT_OBJECT",
                        f"{target}: the run's own evidence for this target is not a JSON object")
            return
        requires_live = self.target_requires_live(target)
        if body.get("ok") is False:
            self.defect("PROVENANCE_EVIDENCE_SELF_DECLARED_FAIL",
                        f"{target}: the run's own evidence declares ok=false")
        status = body.get("status")
        if isinstance(status, str) and status.strip().lower() in FAILURE_WORDS:
            self.defect("PROVENANCE_EVIDENCE_SELF_DECLARED_FAIL",
                        f"{target}: the run's own evidence declares status={status!r}")
        if requires_live:
            if body.get("live") is False:
                self.defect("PROVENANCE_EVIDENCE_SELF_DECLARED_FAIL",
                            f"{target}: live-mode evidence declares live=false")
            if body.get("simulated") is True:
                self.defect("PROVENANCE_EVIDENCE_SELF_DECLARED_FAIL",
                            f"{target}: live-mode evidence declares simulated=true")
            native_run = body.get("nativeRun")
            if isinstance(native_run, str) and native_run:
                resolved = Path(native_run)
                if resolved.is_absolute():
                    if not resolved.exists():
                        self.defect("PROVENANCE_NATIVE_RUN_ABSENT",
                                    f"{target}: evidence names native run {native_run!r}, which "
                                    "does not exist on disk")
                    elif is_within(resolved, self.run_root):
                        self.defect("PROVENANCE_NATIVE_RUN_INSIDE_RUN",
                                    f"{target}: native run {native_run!r} is inside the audited "
                                    "run; a run cannot be its own native producer")

    # -- main --------------------------------------------------------------- #

    def run(self) -> dict:
        self.load_frozen()
        idx_path = self.run_root / "evidence-index.json"
        if idx_path.is_file():
            try:
                self.index = json.loads(idx_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.index = {}
            if not isinstance(self.index, dict):
                # A26-S1: same shape as A26-C1.  body_path():365 calls
                # self.index.get(), so a run-supplied [] / "x" / null index
                # crashes the layer with AttributeError before run() can return.
                self.index = {}
        self.corpus = ExternalCorpus(self.corpus_roots, self._excluded_from_corpus())
        self.corpus.scan()
        if self.corpus.files_scanned == 0:
            self.defect("PROVENANCE_CORPUS_EMPTY",
                        "the independent corpus is empty: no producer artifact exists under "
                        f"{[str(r) for r in self.corpus_roots]}, so nothing can corroborate "
                        "this run")
        if self.corpus_explicit:
            self.notes.append(
                "corpus roots were supplied explicitly rather than discovered; the strength of "
                "this verdict depends on the operator's choice of roots")

        run_id = self.run_root.name
        path = self.run_root / PROVENANCE_NAME
        if not path.is_file():
            self.defect("PROVENANCE_ABSENT",
                        f"{PROVENANCE_NAME} is absent from the run root; no outside source is "
                        "bound to any gate or case, so nothing here can show a real producer "
                        "ever existed")
            return self.verdict()

        doc = read_json(path, PROVENANCE_NAME)
        if not isinstance(doc, dict):
            self.defect("PROVENANCE_NOT_OBJECT", f"{PROVENANCE_NAME} is not a JSON object")
            return self.verdict()
        if doc.get("kind") != PROVENANCE_KIND:
            self.defect("PROVENANCE_KIND_MISMATCH", f"kind={doc.get('kind')!r} != {PROVENANCE_KIND!r}")
        if doc.get("schemaVersion") != PROVENANCE_SCHEMA:
            self.defect("PROVENANCE_SCHEMA_MISMATCH",
                        f"schemaVersion={doc.get('schemaVersion')!r} != {PROVENANCE_SCHEMA}")
        if doc.get("runId") != run_id:
            self.defect("PROVENANCE_RUNID_MISMATCH",
                        f"runId={doc.get('runId')!r} != run root {run_id!r}")
        pin = doc.get("contractPin")
        if not isinstance(pin, dict) or pin.get("sha256") != self.frozen_sha256:
            self.defect("PROVENANCE_PIN_MISMATCH",
                        "contractPin.sha256 must equal the frozen checklist digest this layer "
                        "already pins; a provenance contract may not redefine the denominators")

        sources = self.load_sources(doc)
        self.check_bindings(doc, sources, run_id)
        return self.verdict()

    # -- R03: the allowed scope of a source locator, DERIVED from the producer --- #

    def _normalise_allowed_roots(self, roots) -> tuple:
        """Resolve, de-duplicate and freeze a sequence of root paths."""
        normalised = []
        seen = set()
        for root in roots:
            path = Path(root)
            try:
                resolved = (path.resolve() if path.is_absolute()
                            else (self.repo_root / path).resolve())
            except OSError:
                continue
            key = os.path.normcase(str(resolved))
            if key not in seen:
                seen.add(key)
                normalised.append(resolved)
        return tuple(normalised)

    def _declared_producer_roots(self) -> list:
        """``author.py``'s own ``PRODUCER_ROOTS``, READ rather than restated.

        Restating the four paths here is exactly the defect this rework fixes: a
        producer redirected by configuration would be refused by a stale copy of the
        defaults.  ``author.py`` imports only the standard library, so loading it by
        path is free of side effects -- the same read ``run_parameter_matrix.py``'s
        ``producer_roots_document`` already performs.  A missing or unreadable module
        yields no roots (the caller falls back); it never crashes the verdict.
        """
        module_path = self.repo_root / PRODUCER_ROOTS_MODULE_RELATIVE
        if not module_path.is_file():
            return []
        try:
            spec = importlib.util.spec_from_file_location(
                "_vrp_author_producer_roots", module_path)
            if spec is None or spec.loader is None:
                return []
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:                       # noqa: BLE001 - never fatal to a verdict
            return []
        return self._roots_from_mapping(getattr(module, "PRODUCER_ROOTS", None))

    def _configured_producer_roots(self) -> list:
        """The producer ROOTS CONFIG actually used, if it is on disk.

        ``write_run_provenance_input.py`` is TOLD its roots via ``--roots`` and
        ``run_parameter_matrix.py`` materialises ``author.py``'s ``PRODUCER_ROOTS`` at
        ``.runtime/entity-create/provenance-roots.json``.  That file is where an
        explicit REDIRECT is recorded.  It is read from that FIXED path -- never from
        anything inside the audited run -- and a copy that landed inside the run is
        refused rather than honoured (a run may not configure its own scope).
        """
        path = self.repo_root / PRODUCER_ROOTS_CONFIG_RELATIVE
        if not path.is_file():
            return []
        try:
            if is_within(path.resolve(), self.run_root):
                return []
        except OSError:
            return []
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        return self._roots_from_mapping(document)

    def _roots_from_mapping(self, mapping) -> list:
        """The four declared root values, resolved against the repository root."""
        if not isinstance(mapping, dict):
            return []
        roots = []
        for key in SOURCE_ROOT_KEYS:
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                path = Path(value)
                roots.append(path if path.is_absolute() else (self.repo_root / value))
        return roots

    def _derive_allowed_source_roots(self) -> tuple:
        """Union of what the producers declare and record, plus the floor."""
        roots = []
        roots.extend(self._declared_producer_roots())
        roots.extend(self._configured_producer_roots())
        roots.extend(self.repo_root / rel for rel in FALLBACK_ALLOWED_SOURCE_ROOTS)
        return self._normalise_allowed_roots(roots)

    def _source_scope_defect(self, resolved: Path) -> str | None:
        """``None`` when the resolved source locator is in scope, else the defect code.

        In scope means: inside a real producer directory, one the producer itself
        declared or recorded.  Anything else -- the repository root, a parent, an
        ancestor of the producer roots, an absolute path elsewhere -- is a locator the
        run picked, so it is refused by name.  A locator that IS inside a producer
        directory may still not COVER the audited run: in the shipped layout the run
        lives under ``.runtime/verification`` and no producer root contains it, but the
        obligation is stated here so a future layout cannot quietly make the run its
        own witness.
        """
        for root in self.allowed_source_roots:
            if is_within(resolved, root):
                if resolved != self.run_root and is_within(self.run_root, resolved):
                    return "PROVENANCE_SOURCE_LOCATOR_COVERS_RUN"
                return None
        return "PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE"

    def _excluded_from_corpus(self) -> frozenset:
        """The anchor may not corroborate itself: exclude it from the corpus scan."""
        doc_path = self.run_root / PROVENANCE_NAME
        excluded = set()
        if not doc_path.is_file():
            return frozenset()
        try:
            doc = json.loads(doc_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return frozenset()
        if not isinstance(doc, dict):
            # A26-C1: a non-object provenance document is rejected in run() with
            # PROVENANCE_NOT_OBJECT, but this call runs FIRST (:494 before :515),
            # so without this guard the AttributeError on doc.get() below escapes
            # run() and that branch is dead / no structured verdict is emitted.
            return frozenset()
        # A26-C3 (the sibling of A26-C1, found by the W20 independent verifier
        # 2026-10-05 and reproduced by the main line): a non-object ANCHOR is guarded
        # above, but ``sources`` itself can also be a truthy non-iterable (5, true),
        # which ``or []`` does NOT rescue -- ``for entry in 5`` raises TypeError out of
        # run(), so no verdict body is emitted and the refusal branch is unreachable.
        # MEASURED: {"sources": 5} used to exit 1 with a traceback and no JSON.
        # Only a list is a list.  This loses NO refusal: load_sources already refuses a
        # non-list ``sources`` with PROVENANCE_SOURCES_ABSENT, so skipping the scan here
        # is the same "not scanning must not mean not rejecting" rule as A26-C2.
        raw_sources = doc.get("sources")
        for entry in (raw_sources if isinstance(raw_sources, list) else []):
            if (isinstance(entry, dict) and isinstance(entry.get("locator"), str)
                    and entry["locator"].strip()):
                # A26-C2: Path("") is Path("."), so repo_root / "" is repo_root
                # and the rglob below walks the ENTIRE repository.  An empty or
                # whitespace-only locator is not a locator: skip it.
                candidate = Path(entry["locator"])
                if not candidate.is_absolute():
                    candidate = self.repo_root / candidate
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                # R03: the ORIGINAL verdict on '.'/'..' ("the separate, user-owned S2
                # decision") is preserved here as a record; the decision itself is now
                # discharged by the authenticity contract instead of by leaving the
                # locator unbounded.  Only an OUT-OF-SCOPE locator is skipped here,
                # because only that walk is unbounded -- it rglobs whatever the run
                # names (the repo root is 493,426 files, ~13 min, measured in the
                # shipped suite's D2 note) and empties the corpus as a side effect, so
                # a run would be refused for the wrong reason.  A locator that is IN a
                # producer directory but COVERS the run still bounds the corpus (the
                # walk is bounded and excluding the run is the point); load_sources
                # refuses it with _COVERS_RUN and an unbound target still refuses.
                if self._source_scope_defect(resolved) == \
                        "PROVENANCE_SOURCE_LOCATOR_OUT_OF_SCOPE":
                    continue
                try:
                    if resolved.is_file():
                        excluded.add(resolved)
                    elif resolved.is_dir():
                        for item in resolved.rglob("*"):
                            if item.is_file():
                                excluded.add(item.resolve())
                except OSError:
                    continue
        return frozenset(excluded)

    def load_sources(self, doc: dict) -> dict:
        raw = doc.get("sources")
        if not isinstance(raw, list) or not raw:
            self.defect("PROVENANCE_SOURCES_ABSENT",
                        "sources must be a non-empty list of outside-source declarations")
            return {}
        sources = {}
        for entry in raw:
            if not isinstance(entry, dict):
                self.defect("PROVENANCE_SOURCE_INVALID", f"source entry not an object: {entry!r}")
                continue
            source_id = entry.get("sourceId")
            if not isinstance(source_id, str) or not source_id:
                self.defect("PROVENANCE_SOURCE_INVALID", f"source has no sourceId: {entry!r}")
                continue
            if source_id in sources:
                self.defect("PROVENANCE_SOURCE_DUPLICATE", f"sourceId {source_id!r} repeated")
                continue
            kind = entry.get("kind")
            if kind not in ALLOWED_KINDS:
                self.defect("PROVENANCE_SOURCE_KIND_INVALID",
                            f"{source_id}: kind={kind!r} not in {sorted(ALLOWED_KINDS)}")
            record = {"declared": entry, "scalars": set(), "path": None, "kind": kind}
            sources[source_id] = record
            locator = entry.get("locator")
            if not isinstance(locator, str) or not locator:
                self.defect("PROVENANCE_SOURCE_LOCATOR_INVALID",
                            f"{source_id}: locator is empty or not a string")
                continue
            candidate = Path(locator)
            if not candidate.is_absolute():
                candidate = (self.repo_root / locator)
            try:
                resolved = candidate.resolve()
            except OSError as exc:
                self.defect("PROVENANCE_SOURCE_LOCATOR_INVALID", f"{source_id}: {locator}: {exc}")
                continue
            record["path"] = resolved
            self.sources_checked += 1

            # R03: an outside source must BE an outside source.  A locator that
            # resolves outside every real producer directory -- the repo root, a
            # parent, an absolute path elsewhere -- is refused here, not merely
            # flagged: computing its scalars would walk the whole repository a second
            # time AND let the run's own text (the repo contains the run) name every
            # token, making P6 vacuous.  ``continue`` leaves the record in ``sources``
            # with an EMPTY scalar set, so every binding to it still fails
            # (PROVENANCE_CROSSCHECK_FAILED) on top of the scope defect -- the refusal
            # is not traded for a cheaper one.
            scope_code = self._source_scope_defect(resolved)
            if scope_code is not None:
                self.defect(scope_code,
                            f"{source_id}: locator {locator!r} resolves to {resolved}, which "
                            "is not inside a producer directory this layer derives from the "
                            "producer's own configuration "
                            f"({[str(p) for p in self.allowed_source_roots]})")
                continue

            if is_within(resolved, self.run_root):
                self.defect("PROVENANCE_SOURCE_INSIDE_RUN",
                            f"{source_id}: locator {locator!r} resolves inside the audited run "
                            f"({resolved}); a run cannot be its own outside witness")
            if not resolved.exists():
                self.defect("PROVENANCE_SOURCE_MISSING",
                            f"{source_id}: {locator!r} does not exist on disk")
                continue
            if resolved.is_dir():
                expected_manifest = entry.get("directoryManifestSha256")
                if not isinstance(expected_manifest, str) or not SHA256_RE.fullmatch(expected_manifest):
                    self.defect("PROVENANCE_SOURCE_MANIFEST_ABSENT",
                                f"{source_id}: directory source has no directoryManifestSha256")
                else:
                    self.checks += 1
                    actual_manifest = self._manifest(resolved)
                    if actual_manifest != expected_manifest:
                        self.defect("PROVENANCE_SOURCE_MANIFEST_MISMATCH",
                                    f"{source_id}: recorded manifest {expected_manifest} != "
                                    f"actual {actual_manifest}")
            else:
                recorded = entry.get("sha256")
                if not isinstance(recorded, str) or not SHA256_RE.fullmatch(recorded):
                    self.defect("PROVENANCE_SOURCE_HASH_INVALID",
                                f"{source_id}: missing/ill-formed sha256 for a file source")
                else:
                    self.checks += 1
                    actual = sha256_file(resolved)
                    if actual != recorded:
                        self.defect("PROVENANCE_SOURCE_HASH_MISMATCH",
                                    f"{source_id}: recorded {recorded} actual {actual}")
            record["scalars"] = self._scalars(resolved)
        return sources

    @staticmethod
    def _manifest(root: Path) -> str:
        rows = []
        for item in sorted(root.rglob("*")):
            if item.is_file():
                rel = str(item.relative_to(root)).replace("\\", "/")
                rows.append(f"{rel}\t{sha256_file(item)}")
        return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()

    @staticmethod
    def _scalars(path: Path) -> set:
        found = set()
        items = [path] if path.is_file() else [
            p for p in sorted(path.rglob("*"))
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES
            and p.stat().st_size <= MAX_FILE_BYTES]
        for item in items:
            try:
                text = item.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # The name AS WRITTEN, plus its progressively stripped stems.
            #
            # A producer may record the identity it dispatched in the FILE NAME rather
            # than in the body: elevated-request.py writes
            # ``<requestId>.submission.json`` / ``<requestId>.response.json`` and puts no
            # requestId in the content.  Adding only the full name left the bare token
            # matching nothing, so the target it was supposed to witness never bound.
            # MEASURED 2026-10-04: every unbound provenance target on three real runs was
            # a ``case:*/cleanup``, and each needed exactly such a name-only token.
            #
            # This widens what counts as a name-side witness; it does NOT widen
            # independence -- the file must still sit under a corpus root the run did not
            # choose (the corpus check is separate, on the caller's side).
            found.add(item.name)
            stem = item.name
            for suffix in Path(item.name).suffixes:
                stem = stem[: -len(suffix)]
                if stem:
                    found.add(stem)
            try:
                _collect(json.loads(text), found)
                continue
            except ValueError:
                pass
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if line[0] in "{[":
                    try:
                        _collect(json.loads(line), found)
                        continue
                    except ValueError:
                        pass
                for token in re.split(r"[^0-9A-Za-z]+", line):
                    if token:
                        found.add(token)
        return found

    def check_bindings(self, doc: dict, sources: dict, run_id: str) -> None:
        raw = doc.get("bindings")
        if not isinstance(raw, list):
            self.defect("PROVENANCE_BINDINGS_ABSENT",
                        "bindings must be a list of {target, sourceId} objects")
            return
        seen = {}
        for entry in raw:
            if not isinstance(entry, dict):
                self.defect("PROVENANCE_BINDING_INVALID", f"binding not an object: {entry!r}")
                continue
            target, source_id = entry.get("target"), entry.get("sourceId")
            if not isinstance(target, str):
                self.defect("PROVENANCE_BINDING_INVALID", f"binding has no target: {entry!r}")
                continue
            if target in seen:
                self.defect("PROVENANCE_BINDING_DUPLICATE", f"target {target!r} bound more than once")
                continue
            seen[target] = source_id

        required = list(self.required_gate_targets)
        for targets in self.required_case_targets.values():
            required.extend(targets)
        for target in required:
            if target not in seen:
                self.defect("PROVENANCE_BINDING_MISSING",
                            f"{target}: no outside source is bound to this required gate-evidence "
                            "item / case stage")
                continue
            self.bind_one(target, seen[target], sources, run_id)
        for target in sorted(set(seen) - set(required)):
            self.defect("PROVENANCE_BINDING_EXTRA",
                        f"{target}: bound to a source but is not a required target of the frozen "
                        "checklist")

    def bind_one(self, target: str, source_id, sources: dict, run_id: str) -> None:
        self.bindings_checked += 1
        # the run's own body must not affirmatively declare failure, and must not
        # be empty
        self.check_body(target)

        # A47 (1)(2) -- degeneracy accounting.  A binding is DEGENERATE when its
        # expected token set is exactly {runId}: it asserts nothing specific to
        # this target.  The two causes are counted separately: the layer could not
        # SEE the run's body at all (blindness -- the alarming cause) versus a body
        # that is visible but legitimately carries neither levelId nor requestId.
        # Observation only; it never changes acceptance here (see verdict()).
        tokens = self.expected_tokens(target, run_id)
        has_visible_body = self.body_path(target) is not None
        if has_visible_body:
            self.targets_with_visible_body += 1
        if not [t for t in tokens if t != run_id]:
            self.degenerate_bindings += 1
            if has_visible_body:
                self.degenerate_body_without_ids += 1
            else:
                self.degenerate_no_visible_body += 1
        # R02: record why this target is (or is not) degenerate.  Observation
        # only -- ``verdict()`` is untouched by this line.
        self.degenerate_records.append(
            self.classify_target(target, tokens, has_visible_body, run_id))
        self.distinct_binding_predicates.add(
            (source_id if isinstance(source_id, str) else repr(source_id), frozenset(tokens)))

        record = sources.get(source_id) if isinstance(source_id, str) else None
        if record is None:
            self.defect("PROVENANCE_BINDING_SOURCE_UNKNOWN",
                        f"{target}: bound to unknown sourceId {source_id!r}")
            return
        kind = record.get("kind")
        if self.target_requires_live(target) and kind not in LIVE_PRODUCER_KINDS:
            self.defect("PROVENANCE_SOURCE_NOT_LIVE",
                        f"{target}: frozen evidenceMode requires a live producer, but the bound "
                        f"source kind is {kind!r}")

        # the anchor must actually name them
        missing = [t for t in tokens if t not in record["scalars"]]
        if missing:
            self.defect("PROVENANCE_CROSSCHECK_FAILED",
                        f"{target}: source {source_id!r} does not name {missing!r}; the "
                        "outside document was not produced by this run")

        # ECHO DETECTION -- and they must exist in the corpus the run did not choose
        for token in tokens:
            if self.corpus.has(token):
                continue
            self.defect("PROVENANCE_TOKEN_NOT_INDEPENDENT",
                        f"{target}: token {token!r} appears in the anchor but in no "
                        "independent producer artifact under the corpus roots "
                        f"{[str(r) for r in self.corpus_roots]}; an anchor that merely "
                        "echoes the run corroborates nothing")

    # -- R02: finer classification of degenerate bindings -------------------- #

    #: identity fields ``expected_tokens`` can tighten a binding with
    IDENTITY_KEYS = ("levelId", "requestId")
    DEGENERATE_CLASSES = ("TARGET_BODY_MISSING", "IDENTITY_FIELDS_MISSING",
                          "RUNID_ONLY_PREDICATE")

    @staticmethod
    def _target_family(target: str) -> str:
        """Map a frozen target id onto the 14/51/17 taxonomy.

        ``gate:Sxx/<name>`` -> "gate" (14 gates S00..S13);
        ``case:T-*/<stage>`` -> "template" (51); ``case:P*/<stage>`` ->
        "parameter" (17).
        """
        if target.startswith("gate:"):
            return "gate"
        if target.startswith("case:"):
            case_id = target.split(":", 1)[1].split("/", 1)[0]
            if case_id.startswith("T-"):
                return "template"
            if case_id[:1] == "P" and case_id[1:].isdigit():
                return "parameter"
        return "unknown"

    def classify_target(self, target: str, tokens, has_visible_body: bool,
                        run_id: str) -> dict:
        """Why a target's expected-token set is (or is not) degenerate.

        Three frozen classes.  A target whose original body is missing can only
        land in TARGET_BODY_MISSING; it is never upgraded to a later class by
        inventing a body, and the runId is never copied in as an identity.
        """
        record = {
            "target": target,
            "family": self._target_family(target),
            "bodyVisible": bool(has_visible_body),
            "expectedTokens": [str(t) for t in tokens],
            "nonRunIdTokens": [str(t) for t in tokens if t != run_id],
            "requiresLive": self.target_requires_live(target),
        }
        if record["nonRunIdTokens"]:
            record.update(klass="STRONG", subReason="has_non_runid_token",
                          identityDescribed=[], identityUsable=[])
            return record
        if not has_visible_body:
            record.update(klass="TARGET_BODY_MISSING", subReason="absent",
                          identityDescribed=[], identityUsable=[])
            return record
        path = self.body_path(target)
        try:
            parsed = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record.update(klass="TARGET_BODY_MISSING", subReason="unreadable",
                          identityDescribed=[], identityUsable=[])
            return record
        if not isinstance(parsed, dict):
            record.update(klass="TARGET_BODY_MISSING", subReason="not_object",
                          identityDescribed=[], identityUsable=[])
            return record
        if not parsed:
            record.update(klass="TARGET_BODY_MISSING", subReason="empty_object",
                          identityDescribed=[], identityUsable=[])
            return record
        described = [key for key in self.IDENTITY_KEYS if key in parsed]
        if target.startswith("case:"):
            case_id = target.split(":", 1)[1].split("/", 1)[0]
            after = self._load(self.run_root / "cases" / case_id / "after.json") or \
                self._load(self.run_root / "adapter-evidence" / case_id / "after.json")
            if isinstance(after, dict) and after.get("createdEntityIds"):
                described.append("createdEntityIds")
        if not described:
            record.update(klass="IDENTITY_FIELDS_MISSING",
                          subReason="no_identity_field",
                          identityDescribed=[], identityUsable=[])
            return record
        # identity material is present yet the predicate still collapsed to runId
        record.update(klass="RUNID_ONLY_PREDICATE", subReason="identity_ill_typed",
                      identityDescribed=described, identityUsable=[])
        return record

    def degenerate_report(self) -> dict:
        """The R02 report: three-class counts plus the per-target list.

        A pure read of the records gathered in ``bind_one``; it emits only when
        ``--degenerate-report`` is given and changes no verdict field.
        """
        rows = list(self.degenerate_records)
        counts = {name: 0 for name in self.DEGENERATE_CLASSES}
        sub = {}
        fam = {}
        family_totals = {}
        for row in rows:
            family_totals[row["family"]] = family_totals.get(row["family"], 0) + 1
            klass = row["klass"]
            if klass == "STRONG":
                continue
            counts[klass] = counts.get(klass, 0) + 1
            key = f"{klass}/{row['subReason']}"
            sub[key] = sub.get(key, 0) + 1
            bucket = fam.setdefault(row["family"],
                                    {name: 0 for name in self.DEGENERATE_CLASSES})
            bucket[klass] = bucket.get(klass, 0) + 1
        return {
            "kind": "r02-degenerate-binding-classification",
            "runId": self.run_root.name,
            "frozenChecklistSha256": self.frozen_sha256,
            "bindingsChecked": self.bindings_checked,
            "degenerateBindings": self.degenerate_bindings,
            "targetsWithVisibleBody": self.targets_with_visible_body,
            "classCounts": counts,
            "subReasonCounts": sub,
            "familyTotals": family_totals,
            "familyByClass": fam,
            "perTarget": rows,
        }

    # -- verdict ------------------------------------------------------------ #

    def verdict(self) -> dict:
        # A47 (3): when EVERY binding is degenerate and the layer saw none of the
        # run's own bodies, the binding check has collapsed to a single fact
        # ("the bound source names the runId"), so the count 'bindingsChecked'
        # overstates the evidence -- the verdict attests the runId, not the run.
        #
        # A47 first raised this as a WARNING and named the one reason to hold it back:
        # promoting it "also rejects honest runs whose evidence sits one directory
        # deeper than the hard-coded cases/<caseId>/<stage>.json".  THAT REASON IS GONE.
        # body_path() now reads the layout the parameter driver actually writes
        # (cases/<caseId>/a<attempt>/<stage>.json), so targetsWithVisibleBody==0 now
        # means the run genuinely carries no case evidence -- not that the layer is
        # looking in the wrong place.  MEASURED on the real P12 run 95a7c840d...: once
        # the path fix landed, targetsWithVisibleBody went 0 -> 5 and this condition
        # stopped firing on a real run.  It is therefore a DEFECT: a layer that goes
        # green on a run whose every binding says only "the source names the runId" is
        # attesting the runId, not the run.
        if (self.bindings_checked > 0
                and self.degenerate_bindings == self.bindings_checked
                and self.targets_with_visible_body == 0):
            self.binding_undiscriminating = True
            self.defects.append({
                "code": "PROVENANCE_BINDING_UNDISCRIMINATING",
                "detail": (
                    f"all {self.bindings_checked} bindings are degenerate (expected-token set is "
                    "exactly {runId}) and the layer could see none of the run's evidence bodies "
                    "(targetsWithVisibleBody=0); every binding reduces to the same one-bit fact "
                    "'the bound source names the runId', so this verdict attests the runId, not "
                    "the run."),
            })
        base_ok = True if self.base_skipped else self.base_exit == 0
        passing = base_ok and not self.defects
        corpus = self.corpus
        return {
            "ok": passing,
            "schemaVersion": 2,
            "kind": "entity-create-run-authenticity-layer",
            "runId": self.run_root.name,
            "runRoot": str(self.run_root),
            "baseExitCode": None if self.base_skipped else self.base_exit,
            "baseSkipped": self.base_skipped,
            "baseAccepted": None if self.base_skipped else base_ok,
            "baseDefectCount": (self.base_verdict or {}).get("defectCount"),
            "corpusRoots": [str(r) for r in (corpus.roots if corpus else [])],
            "corpusRootsExplicit": self.corpus_explicit,
            "allowedSourceRoots": [str(p) for p in self.allowed_source_roots],
            "corpusFilesScanned": corpus.files_scanned if corpus else 0,
            "corpusRequestIds": len(corpus.request_ids) if corpus else 0,
            "corpusEntityIds": len(corpus.entity_ids) if corpus else 0,
            "corpusLevelIds": len(corpus.level_ids) if corpus else 0,
            "sourcesChecked": self.sources_checked,
            "bindingsChecked": self.bindings_checked,
            "targetsWithVisibleBody": self.targets_with_visible_body,
            "degenerateBindings": self.degenerate_bindings,
            "degenerateNoVisibleBody": self.degenerate_no_visible_body,
            "degenerateBodyWithoutIds": self.degenerate_body_without_ids,
            "distinctBindingPredicates": len(self.distinct_binding_predicates),
            "bindingUndiscriminating": self.binding_undiscriminating,
            "provenanceWarnings": self.warnings,
            "requiredGateEvidenceTargets": len(self.required_gate_targets),
            "requiredCaseStageTargets": sum(len(v) for v in self.required_case_targets.values()),
            "provenanceDefectCount": len(self.defects),
            "provenanceDefects": self.defects,
            "provenanceChecks": self.checks,
            "notes": self.notes[:40],
            "fullRunAccepted": passing,
            "authenticityAccepted": not self.defects,
            "residualLimits": [
                "R1 an adversary with write access to a producer root can plant a corroborating "
                "record there; this check verifies existence, not the writer's identity",
                "R2 an explicitly supplied --corpus-roots redirects corroboration; the default "
                "roots are hard-coded and not attacker-chosen.  --corpus-roots does NOT "
                "widen the SOURCE scope: a source locator must still resolve inside a "
                "producer directory derived from the producer's own configuration",
                "R4 the allowed SOURCE scope is derived from producer-side configuration "
                "(author.py PRODUCER_ROOTS and .runtime/entity-create/provenance-roots.json), "
                "so a producer explicitly redirected to a real directory elsewhere is "
                "honoured; an adversary with write access to that configuration can name a "
                "directory of its own -- the same trust level as R1",
                "R3 a real run from another round whose ids this run copies is not excluded",
                "F-010 is NOT closed: a read-only verifier cannot defeat an equal-write-access "
                "adversary",
            ],
        }


def _collect(value, out: set) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(str(key))
            _collect(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, out)
    elif isinstance(value, bool):
        out.add(str(value))
    elif isinstance(value, (int, float, str)):
        out.add(str(value))
    elif value is None:
        out.add("null")


def run_base_verifier(base: Path, run_root: Path) -> tuple:
    """Run the frozen gate as a subprocess and read its verdict from stdout.

    ``--quiet`` makes the gate print exactly the JSON verdict, so no temporary
    file is needed -- this layer writes nothing to disk.
    """
    cmd = [sys.executable, "-B", str(base), str(run_root), "--quiet"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    verdict = {}
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                verdict = json.loads(line)
                break
            except ValueError:
                continue
    if not verdict:
        try:
            verdict = json.loads(proc.stdout or "{}")
        except ValueError:
            verdict = {}
    return proc.returncode, verdict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--base", type=Path, default=None,
                        help="the frozen gate to fold in (default: tools/game-executor/"
                             "verify_entity_create_run.py); resolution seam, not a relaxation")
    parser.add_argument("--corpus-roots", type=Path, action="append", default=None,
                        help="TEST SEAM. Override the producer directories scanned for "
                             "corroboration. The production path must NOT pass this: the "
                             "default roots are hard-coded and are not chosen by the run.")
    parser.add_argument("--output", type=Path, default=None,
                        help="write the JSON verdict here (refused inside the audited run)")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--degenerate-report", type=Path, default=None,
                        help="R02: write a finer three-class breakdown of the degenerate "
                             "bindings here. Observation only: the verdict body and exit "
                             "code are unchanged. Refused inside the audited run.")
    args = parser.parse_args(argv)

    run_root = args.run_root
    if not run_root.is_dir():
        print(f"DEFECT INPUT_UNUSABLE: run root is not a directory: {run_root}", file=sys.stderr)
        print(json.dumps({"ok": False, "inputUnusable": True, "error": "no run root"}))
        return 2
    if not RUN_ID_RE.fullmatch(run_root.name):
        print(f"DEFECT INPUT_UNUSABLE: run root name is not a 32-hex runId: {run_root.name!r}",
              file=sys.stderr)
        print(json.dumps({"ok": False, "inputUnusable": True, "error": "bad run id"}))
        return 2

    try:
        repo_root = repo_root_from(Path(__file__))
    except InputError as exc:
        print(f"DEFECT INPUT_UNUSABLE: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "inputUnusable": True, "error": str(exc)}))
        return 2
    base = args.base or (repo_root / "tools" / "game-executor" / "verify_entity_create_run.py")
    if not base.is_file():
        print(f"DEFECT INPUT_UNUSABLE: base verifier not found: {base}", file=sys.stderr)
        print(json.dumps({"ok": False, "inputUnusable": True, "error": "no base verifier"}))
        return 2

    if args.output is not None:
        try:
            resolved_out = args.output.resolve()
        except OSError as exc:
            print(f"DEFECT INPUT_UNUSABLE: --output {args.output}: {exc}", file=sys.stderr)
            print(json.dumps({"ok": False, "inputUnusable": True, "error": "bad output path"}))
            return 2
        if is_within(resolved_out, run_root.resolve()):
            print(f"DEFECT INPUT_UNUSABLE: --output {resolved_out} lands inside the audited run",
                  file=sys.stderr)
            print(json.dumps({"ok": False, "inputUnusable": True,
                              "error": "output inside run"}))
            return 2

    base_exit, base_verdict = run_base_verifier(base, run_root)

    try:
        layer = ProvenanceLayer(run_root, base_verdict, base_exit, repo_root,
                                corpus_roots=args.corpus_roots,
                                corpus_explicit=args.corpus_roots is not None)
        verdict = layer.run()
    except InputError as exc:
        print(f"DEFECT INPUT_UNUSABLE: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "inputUnusable": True, "error": str(exc)}))
        return 2

    if not args.quiet:
        if base_exit != 0:
            print(f"# base verifier exit {base_exit}, "
                  f"{(base_verdict or {}).get('defectCount')} internal defects")
        for defect in verdict["provenanceDefects"]:
            print(f"DEFECT {defect['code']}: {defect['detail']}")
        for warning in verdict.get("provenanceWarnings") or []:
            print(f"WARNING {warning['code']}: {warning['detail']}")

    if args.degenerate_report is not None:
        resolved_report = args.degenerate_report.resolve()
        if is_within(resolved_report, run_root.resolve()):
            print(f"DEFECT INPUT_UNUSABLE: --degenerate-report {resolved_report} lands "
                  "inside the audited run", file=sys.stderr)
            print(json.dumps({"ok": False, "inputUnusable": True,
                              "error": "degenerate report inside run"}))
            return 2
        args.degenerate_report.parent.mkdir(parents=True, exist_ok=True)
        args.degenerate_report.write_text(
            json.dumps(layer.degenerate_report(), ensure_ascii=False, indent=1,
                       allow_nan=False) + "\n",
            encoding="utf-8", newline="\n")
    rendered = json.dumps(verdict, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
