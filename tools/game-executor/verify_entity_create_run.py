"""Independent read-only acceptance verifier for the entity.create full run (S13).

Recomputes the verdict from raw evidence files. It never imports the code under
acceptance, never trusts a "pass"/"ok" boolean found in a report, and never
writes into the run it reads.

Contract provenance (round-1 finding C1/C2)
-------------------------------------------
The obligations this verifier enforces - the required gate list, the 51 required
template cases and the required parameter cases - are the denominators of the
frozen engineering checklist `docs/ds-handoff/07-ENTITY-CREATE-CHECKLIST.json`,
whose sha256 is pinned in this file as `FROZEN_CHECKLIST_SHA256` and recomputed
at run time. If the file on disk no longer carries that digest the verifier
refuses to judge anything (exit 2): its own denominator would be stale.

`<run-root>/checklist.input.json` is treated only as an OBJECT UNDER TEST. It is
never a source of denominators. It is compared bidirectionally against the
frozen checklist, and any missing entry, extra entry, changed `required` flag,
changed caseId/templateId or changed evidenceMode is a defect. A run therefore
cannot shrink its own contract to "one gate, one template, no parameter cases".

What it recomputes
------------------
1. sha256 of every referenced file, compared with the recorded digest.
2. closure of the frozen required gates / 51 templates / parameter cases between
   the run-pinned checklist.input.json, the two case matrices, evidence-index.json
   and result.json (missing AND unexpected entries are both defects).
3. status of every required gate and of every required case (frozen gates are all
   required; `requiredGatesAllowNotApplicable` is false, so "not-run", "blocked",
   "failed", "not-applicable" and a missing gate all reject).
4. per-case result properties, not "I ran this step":
   - the evidence actually accepted for a stage is the stage file that sits under
     that case's own evidenceDir (finding C3): an index that redirects a stage to
     some other file is a defect, and so is any same-stage-named file left under
     the case dir that disagrees with the accepted bytes;
   - a stage payload that carries a `status` field must carry "pass";
   - every stage file carries this run's runId and its own caseId;
   - requestId and templateId agree across intent / raw-call / after;
   - transform agrees across intent / raw-call / after entity (float32 quantised);
   - entity-count and identity sets agree across after / verification / cleanup
     and with the identity recorded in evidence-index.json;
   - contentSha256 recorded in after.json equals a digest recomputed here over
     the entity list in that same file;
   - created entity ids are disjoint from the before-snapshot id set;
   - a case that expects a creation has exactly one dispatch and a clean cleanup;
   - a case that creates also declares that unrelated objects stayed unchanged.
5. result.json's own claims against the recomputed verdict, including
   templatesCovered, parameterCasesCovered, created/cleaned id unions,
   `unrelatedUnchangedCaseIds` and `pendingRequestIds` (set equality both ways).
6. report.md's machine-readable conclusion block (finding C5): a fenced JSON
   object carrying `fullRunAccepted`, `defectCount`, `requiredTemplateCount` and
   `acceptedTemplateCount`, each of which must equal the value recomputed here.
   Prose that contradicts the machine verdict without a block is a defect.

What it does NOT recompute: the gate-evidence bodies
----------------------------------------------------
A required gate passes here when the index says `status: "pass"`, every required
evidence NAME has an index entry, that entry's own recorded sha256 matches the
file on disk, and that file's `runId` equals this run. A JSON evidence file that
carries no `runId` at all is a defect, never a skip (fail-closed). The BODY of a
gate-evidence file is still not parsed for meaning:
`levelId`, `requestId`, a pid and a timestamp in it are never read. The same is
true of `build_run_evidence_index.py`, whose gate scoring is `path.is_file()`.

MEASURED (2026-10-02, DS-10, reproduced by the main line): a run root built
entirely from text -- no journal entry, no native run directory, no helper
receipt, no save, no game contact of any kind -- is accepted with exit 0,
`fullRunAccepted: true`, `defectCount: 0`, checkedFiles 605, 14 gates pass and
51 templates / 17 parameter cases accepted, in two variants: one whose gate
evidence files are `{}`, and one whose bodies carry wrong ids; and making a
historical run's real bytes pass as this run's evidence took only deleting its
`runId` key. All of these are now refused by the fail-closed `runId` binding in
`hash_matches`, which requires every indexed JSON file to carry this run's
`runId`.

This is the documented limit of a pure read-only verifier, not a bug that was
missed: §"已知边界" of the fixture README records that a run whose after.json /
verification.json / index.identity / result.json are all consistently rewritten
cannot be falsified without an external anchor, and says real delivery needs the
native-side receipts and the original GIL copy cross-checked separately. Exit 0
here therefore means "this run's own evidence is internally consistent", NOT
"entity.create worked". The missing anchor is an open design item (raise the
gate from `{path, sha256}` to a receipt whose digest can be recomputed from
outside the run root); until it lands, do not read a green verdict as delivery.

Capability honesty
------------------
Exit 0 has been demonstrated only on the synthetic fixture run
(`.runtime/verification/entity-create-full-run/<fixture>/fixtures/`), which
contains no live observation, no game/editor call and no native save. As of this
round there is NO recorded exit-0 verdict on any real owner run; an exit-0 on the
fixture is not evidence that entity.create works.

Exit codes
----------
0  every required gate and case passes, recomputed from raw evidence
1  at least one defect; each defect is printed as `DEFECT <CODE>: <detail>`.
   A missing or corrupt artifact of an existing run is a defect, not an error.
2  the verifier could not judge at all: bad arguments, run root absent, run
   directory name not a runId, `--output` inside the audited run, no contract
   under test, or the frozen checklist no longer matching its pinned digest

Usage
-----
    python verify_entity_create_run.py <run-root> [--output <path>] [--quiet]
                                       [--checklist <path>]

`<run-root>` is `.runtime/verification/entity-create-full-run/<runId>` and must
contain its own `checklist.input.json` copy. That copy is never trusted: it is
compared against the frozen checklist. `--checklist` is an inspection escape
hatch for a run that pinned nothing; the supplied file is likewise only compared
against the frozen checklist, it records a defect and can never produce exit 0.

`--output` is refused (exit 2) when it resolves inside `<run-root>`: this tool
must never overwrite the evidence it is auditing (finding C4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

RUN_ID_RE = re.compile(r"[0-9a-f]{32}")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
PASSING = "pass"
DEFAULT_STAGES = ("intent", "before", "raw-call", "after", "verification", "cleanup")

# The run's obligations come from this one file, pinned here by digest. It is the
# only denominator the verifier trusts; a run may not shrink it (finding C1/C2).
FROZEN_CHECKLIST_RELATIVE = "docs/ds-handoff/07-ENTITY-CREATE-CHECKLIST.json"
FROZEN_CHECKLIST_SHA256 = "84540680083c07df2413116bb212633eac80137cf29f1dc8b30c5862344abc83"
REPORT_MD_NAME = "report.md"
CONCLUSION_KEYS = ("fullRunAccepted", "defectCount",
                   "requiredTemplateCount", "acceptedTemplateCount")
FENCE_RE = re.compile(r"^[ \t]*```[ \t]*([A-Za-z0-9_-]*)[ \t]*$(.*?)^[ \t]*```[ \t]*$",
                      re.MULTILINE | re.DOTALL)


class InputError(Exception):
    """Verifier input is unusable; the run gets no verdict."""


def is_within(child, parent):
    """True when `child` resolves to `parent` or under it (Windows-case aware)."""
    try:
        child_text = os.path.normcase(str(Path(child).resolve()))
        parent_text = os.path.normcase(str(Path(parent).resolve()))
    except OSError:
        return False
    if child_text == parent_text:
        return True
    return child_text.startswith(parent_text.rstrip("\\/") + os.sep)


def locate_frozen_checklist():
    """Walk up from this file to the repository root holding the frozen checklist."""
    for candidate in Path(__file__).resolve().parents:
        path = candidate / FROZEN_CHECKLIST_RELATIVE
        if path.is_file():
            return path
    raise InputError(f"cannot locate {FROZEN_CHECKLIST_RELATIVE} above {__file__}")


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #

def read_json(path, what):
    """Parse a JSON file. Records the *failure* as an input error, never a pass."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError(f"{what}: cannot read {path}: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise InputError(f"{what}: {path} is not valid UTF-8 JSON: {exc}") from exc


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(obj):
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def f32(value):
    """Quantise to float32 so a game-side float32 round trip is not a mismatch."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def vec3(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        try:
            out.append(f32(item))
        except (OverflowError, struct.error):
            return None
    return tuple(out)


def transform_of(record):
    if not isinstance(record, dict):
        return None
    transform = {}
    for key in ("position", "rotation", "scale"):
        parsed = vec3(record.get(key))
        if parsed is None:
            return None
        transform[key] = parsed
    return transform


def id_set(value):
    """Normalise an identifier list to a comparable set of strings."""
    if not isinstance(value, list):
        return None
    out = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            return None
        out.add(str(item))
    return out


def stage_files(case_dir, stage):
    """A stage is `<stage>.json` or any single file whose stem is the stage name."""
    if not case_dir.is_dir():
        return []
    return sorted(p for p in case_dir.iterdir()
                  if p.is_file() and p.stem == stage and p.name != stage)


# --------------------------------------------------------------------------- #
# verifier
# --------------------------------------------------------------------------- #

class Verifier:
    def __init__(self, run_root, checklist_override=None):
        self.run_root = run_root.resolve()
        self.checklist_override = checklist_override
        self.pinned_contract = True
        self.checklist_source = None
        self.frozen_source = None
        self.frozen_sha256 = None
        self.defects = []
        self.run_id = run_root.name
        self.checks = 0
        self.notes = []
        self.created_ids = set()
        self.cleaned_ids = set()
        self.unrelated_ok_ids = set()
        self.observed_request_ids = set()
        self.pending_request_ids = set()
        self.required_gate_ids = []
        self.gate_spec = {}
        self.required_templates = {}
        self.required_parameters = {}
        self.accepted_templates = set()
        self.accepted_parameters = set()

    # -- bookkeeping ------------------------------------------------------- #

    def defect(self, code, detail):
        self.defects.append({"code": code, "detail": detail})

    def resolve(self, relative, what):
        """Resolve a referenced path, refusing anything outside the run root."""
        if not isinstance(relative, str) or not relative:
            self.defect(f"{what}_PATH_INVALID", f"empty/non-string path {relative!r}")
            return None
        candidate = (self.run_root / relative)
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            self.defect(f"{what}_PATH_INVALID", f"{relative}: {exc}")
            return None
        if resolved != self.run_root and self.run_root not in resolved.parents:
            self.defect(f"{what}_PATH_ESCAPES_RUN", f"{relative} resolves outside the run")
            return None
        return resolved

    def hash_matches(self, record, what, expected_run_id=None):
        """Assert {path, sha256} against the bytes on disk. Returns parsed JSON or None."""
        if not isinstance(record, dict):
            self.defect(f"{what}_REF_INVALID", f"reference is not an object: {record!r}")
            return None
        path = record.get("path")
        target = self.resolve(path, what)
        if target is None:
            return None
        if not target.is_file():
            self.defect(f"{what}_FILE_MISSING", f"{path} does not exist")
            return None
        recorded = record.get("sha256")
        if not isinstance(recorded, str) or not SHA256_RE.fullmatch(recorded):
            self.defect(f"{what}_HASH_INVALID", f"{path}: bad sha256 field {recorded!r}")
            return None
        self.checks += 1
        actual = sha256_file(target)
        if actual != recorded:
            self.defect(f"{what}_HASH_MISMATCH",
                        f"{path}: recorded {recorded} actual {actual}")
            return None
        payload = None
        if target.suffix == ".json":
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                self.defect(f"{what}_JSON_INVALID", f"{path}: {exc}")
                return None
            if isinstance(payload, dict):
                found = payload.get("runId")
                if found != (expected_run_id or self.run_id):
                    self.defect(f"{what}_RUNID_MISMATCH",
                                f"{path}: runId {found!r} != {expected_run_id or self.run_id!r}")
        return payload

    # -- stage verification ------------------------------------------------- #

    def check_stage(self, case_id, case_dir, stage, ref, expect_live):
        what = f"CASE_STAGE[{case_id}/{stage}]"
        if not isinstance(ref, dict):
            self.defect(f"{what}_REF_MISSING",
                        "evidence-index.json has no hash-referenced file for this stage")
            return None
        payload = self.hash_matches(ref, what)
        if payload is None:
            return None
        if not isinstance(payload, dict):
            self.defect(f"{what}_NOT_OBJECT", "stage evidence is not a JSON object")
            return None
        for field, expected in (("stage", stage), ("caseId", case_id), ("runId", self.run_id)):
            if payload.get(field) != expected:
                self.defect(f"{what}_FIELD_MISMATCH",
                            f"{field}={payload.get(field)!r} != {expected!r}")
        live = payload.get("live")
        if not isinstance(live, bool):
            self.defect(f"{what}_LIVE_FLAG_ABSENT", "live must be a literal boolean")
        elif expect_live is True and live is not True:
            self.defect(f"{what}_NOT_LIVE",
                        "case evidenceMode requires live evidence but live=false")
        elif expect_live is False and live is not False:
            self.defect(f"{what}_NOT_OFFLINE",
                        "case evidenceMode allows only isolated/offline evidence but live=true")
        if payload.get("offline") is True and payload.get("live") is True:
            self.defect(f"{what}_MODE_CONTRADICTION", "live=true together with offline=true")
        # The stage's own verdict word is read, not merely the file's existence.
        if "status" in payload and payload.get("status") != PASSING:
            self.defect(f"{what}_STATUS_NOT_PASS",
                        f"{stage} evidence carries status={payload.get('status')!r}")
        return payload

    def bind_stage_file(self, case_id, case_dir, stage, ref, evidence_dir):
        """The accepted bytes must be the stage file inside this case's own dir.

        Finding C3: filename existence in evidenceDir is not enough. Whatever
        `evidence-index.json` points at for this stage has to *be* the stage file
        that sits under the case directory, and no other same-stage-named file
        under that directory may disagree with it.
        """
        what = f"CASE_STAGE[{case_id}/{stage}]"
        files = stage_files(case_dir, stage)
        if not files:
            self.defect("CASE_STAGE_DIR_MISSING",
                        f"{case_id}: no {stage} file under {evidence_dir}")
            return None
        if not isinstance(ref, dict):
            return None  # check_stage reports the missing reference
        resolved = self.resolve(ref.get("path"), what)
        if resolved is None or not resolved.is_file():
            return None  # check_stage reports missing/invalid/path-escape
        matched = [f for f in files if f.resolve() == resolved]
        if not matched:
            self.defect("CASE_STAGE_NOT_CASE_FILE",
                        f"{case_id}: evidence-index.json {stage} points at {ref.get('path')!r}, "
                        f"which is not the {stage} file under {evidence_dir} "
                        f"(found {[f.name for f in files]})")
        accepted_sha = sha256_file(resolved)
        for other in files:
            if other.resolve() == resolved:
                continue
            self.checks += 1
            if sha256_file(other) != accepted_sha:
                self.defect("CASE_STAGE_DECOY_FILE",
                            f"{case_id}: {other.name} sits under {evidence_dir} as a {stage} "
                            f"file but disagrees with the evidence actually accepted "
                            f"({ref.get('path')!r})")
        return resolved

    def check_case(self, case_id, kind, entry, expect_live, template_id=None):
        if not isinstance(entry, dict):
            self.defect("MATRIX_CASE_ENTRY_INVALID", f"{case_id}: entry is not an object")
            return False
        if entry.get("status") != PASSING:
            self.defect("CASE_STATUS_NOT_PASS", f"{case_id}: status={entry.get('status')!r}")
        if entry.get("required") is False:
            self.defect("CASE_NOT_REQUIRED_IN_MATRIX",
                        f"{case_id}: matrix drops a checklist-required case to required=false")
        evidence_dir = entry.get("evidenceDir")
        case_dir = self.resolve(evidence_dir, f"CASE[{case_id}]") if evidence_dir else None
        if case_dir is None:
            self.defect("CASE_DIR_INVALID", f"{case_id}: missing evidenceDir")
            return False
        if not case_dir.is_dir():
            self.defect("CASE_DIR_MISSING", f"{case_id}: {evidence_dir} is not a directory")
            return False

        if kind == "template":
            declared = entry.get("templateId")
            if declared != template_id:
                self.defect("CASE_TEMPLATEID_MISMATCH",
                            f"{case_id}: matrix templateId={declared!r} checklist={template_id!r}")

        index_entry = self.index_case(case_id)
        if index_entry is None:
            self.defect("MATRIX_CASE_NOT_IN_INDEX", f"{case_id}: no evidence-index.json entry")
            return False

        stages_ref = index_entry.get("stages")
        if not isinstance(stages_ref, dict):
            self.defect("INDEX_CASE_STAGES_INVALID", f"{case_id}: stages is not an object")
            return False

        stages = {}
        for stage in self.required_stages():
            files = stage_files(case_dir, stage)
            if not files:
                self.defect("CASE_STAGE_DIR_MISSING",
                            f"{case_id}: no {stage} file under {evidence_dir}")
                continue
            self.bind_stage_file(case_id, case_dir, stage,
                                 stages_ref.get(stage), evidence_dir)
            stages[stage] = self.check_stage(case_id, case_dir, stage,
                                             stages_ref.get(stage), expect_live)

        intent = stages.get("intent")
        raw = stages.get("raw-call")
        before = stages.get("before")
        after = stages.get("after")
        verif = stages.get("verification")
        cleanup = stages.get("cleanup")
        if not all(isinstance(x, dict) for x in (intent, raw, before, after, verif, cleanup)):
            return False

        self.assert_case_semantics(case_id, kind, intent, raw, before, after, verif, cleanup,
                                   index_entry)
        return True

    def assert_case_semantics(self, case_id, kind, intent, raw, before, after, verif, cleanup,
                              index_entry):
        # intent <-> raw-call binding
        request_id = intent.get("requestId")
        if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
            self.defect("CASE_REQUESTID_INVALID", f"{case_id}: intent requestId {request_id!r}")
        else:
            self.observed_request_ids.add(request_id)
        if raw.get("requestId") != request_id:
            self.defect("CASE_REQUESTID_MISMATCH",
                        f"{case_id}: raw-call {raw.get('requestId')!r} != intent {request_id!r}")

        template_id = intent.get("templateId")
        if kind == "template" and not isinstance(template_id, int):
            self.defect("CASE_TEMPLATEID_INVALID", f"{case_id}: intent templateId {template_id!r}")
        if raw.get("templateId") != template_id:
            self.defect("CASE_TEMPLATEID_MISMATCH",
                        f"{case_id}: raw-call {raw.get('templateId')!r} != intent {template_id!r}")

        expect_create = intent.get("expectCreate")
        if not isinstance(expect_create, bool):
            self.defect("CASE_EXPECT_CREATE_INVALID", f"{case_id}: expectCreate {expect_create!r}")
            return
        # dispatch count: the guide requires exactly one real dispatch per creation
        count = raw.get("dispatchCount")
        dispatched = raw.get("dispatched")
        if expect_create:
            if dispatched is not True or count != 1:
                self.defect("CASE_DISPATCH_COUNT",
                            f"{case_id}: expectCreate=true needs dispatched=true and "
                            f"dispatchCount=1, got {dispatched!r}/{count!r}")
            if raw.get("exitCode") != 0 or raw.get("errorCode"):
                self.defect("CASE_UNEXPECTED_CALL_ERROR",
                            f"{case_id}: successful creation reports exitCode="
                            f"{raw.get('exitCode')!r} errorCode={raw.get('errorCode')!r}")
        else:
            if not raw.get("errorCode"):
                self.defect("CASE_MISSING_ERROR_CODE",
                            f"{case_id}: refusal case has no structured errorCode")
            if after.get("createdEntityIds"):
                self.defect("CASE_UNEXPECTED_CREATE",
                            f"{case_id}: refusal case evidence claims created entities")

        # transform binding intent -> raw-call -> after entity
        expected = transform_of(intent.get("expectedTransform")) if intent.get("expectedTransform") else None
        if expect_create:
            requested = transform_of(raw.get("transform"))
            if expected is not None and requested != expected:
                self.defect("CASE_TRANSFORM_MISMATCH",
                            f"{case_id}: raw-call transform {requested} != intent {expected}")
        elif intent.get("expectedTransform") not in (None, False) and expected is None:
            self.defect("CASE_TRANSFORM_INVALID", f"{case_id}: unparsable expectedTransform")

        # before snapshot must be complete, and the creation must be a new object
        if before.get("snapshotComplete") is not True or before.get("snapshotTruncated") is not False:
            self.defect("CASE_BASELINE_INCOMPLETE",
                        f"{case_id}: before snapshot complete={before.get('snapshotComplete')!r} "
                        f"truncated={before.get('snapshotTruncated')!r}")
        before_ids = id_set(before.get("entityIds"))
        if before_ids is None:
            self.defect("CASE_BASELINE_IDS_INVALID", f"{case_id}: before entityIds unparsable")
            before_ids = set()
        if isinstance(before.get("entityCount"), int) and before["entityCount"] != len(before_ids):
            self.defect("CASE_BASELINE_COUNT_MISMATCH",
                        f"{case_id}: before entityCount={before['entityCount']} ids={len(before_ids)}")

        # after snapshot integrity and recomputed content digest
        after_ids = id_set(after.get("entityIds"))
        created_ids = id_set(after.get("createdEntityIds"))
        if after_ids is None or created_ids is None:
            self.defect("CASE_AFTER_IDS_INVALID", f"{case_id}: after id lists unparsable")
            return
        self.created_ids |= created_ids
        self.cleaned_ids |= (id_set(cleanup.get("removedEntityIds")) or set())
        entities = after.get("entities")
        if not isinstance(entities, list):
            self.defect("CASE_AFTER_ENTITIES_INVALID", f"{case_id}: entities is not a list")
            entities = []
        recorded_content = after.get("contentSha256")
        if not isinstance(recorded_content, str) or not SHA256_RE.fullmatch(recorded_content):
            self.defect("CASE_CONTENT_HASH_INVALID", f"{case_id}: contentSha256 {recorded_content!r}")
        else:
            self.checks += 1
            recomputed = canonical_sha256(entities)
            if recomputed != recorded_content:
                self.defect("CASE_ENTITY_CONTENT_HASH_MISMATCH",
                            f"{case_id}: recorded {recorded_content} recomputed {recomputed} "
                            "(entity list content changed under a stable count)")
        if isinstance(after.get("entityCount"), int) and after["entityCount"] != len(after_ids):
            self.defect("CASE_AFTER_COUNT_MISMATCH",
                        f"{case_id}: after entityCount={after['entityCount']} ids={len(after_ids)}")

        new_ids = created_ids - before_ids
        if expect_create:
            if len(created_ids) != 1:
                self.defect("CASE_CREATED_COUNT_MISMATCH",
                            f"{case_id}: expected exactly 1 created entity, got {len(created_ids)}")
            if new_ids != created_ids:
                self.defect("CASE_CREATED_ID_NOT_NEW",
                            f"{case_id}: created ids also present in the before snapshot: "
                            f"{sorted(created_ids & before_ids)}")
            if created_ids and not created_ids <= after_ids:
                self.defect("CASE_CREATED_ID_ABSENT_FROM_AFTER",
                            f"{case_id}: created ids not visible in the after snapshot")
            for entity in entities:
                if not isinstance(entity, dict):
                    self.defect("CASE_ENTITY_INVALID", f"{case_id}: entity record not an object")
                    continue
                got = transform_of(entity.get("transform"))
                if expected is not None and got is not None and got != expected:
                    self.defect("CASE_TRANSFORM_MISMATCH",
                                f"{case_id}: after entity transform {got} != intent {expected}")
                if entity.get("templateId") != template_id:
                    self.defect("CASE_TEMPLATEID_MISMATCH",
                                f"{case_id}: after entity templateId "
                                f"{entity.get('templateId')!r} != intent {template_id!r}")

        # verification / cleanup identity closure (count-equal but identity-different fails here)
        verif_ids = id_set(verif.get("createdEntityIds"))
        if verif_ids is None:
            self.defect("CASE_VERIFICATION_IDS_INVALID",
                        f"{case_id}: verification createdEntityIds unparsable")
        elif verif_ids != created_ids:
            self.defect("CASE_IDENTITY_MISMATCH",
                        f"{case_id}: verification ids {sorted(verif_ids)} != after ids "
                        f"{sorted(created_ids)}")
        if verif.get("status") != PASSING:
            self.defect("CASE_VERIFICATION_STATUS_NOT_PASS",
                        f"{case_id}: verification.json status={verif.get('status')!r}")
        if verif.get("independent") is not True:
            self.defect("CASE_VERIFICATION_NOT_INDEPENDENT",
                        f"{case_id}: independent={verif.get('independent')!r}")
        if verif.get("transformMatches") is not True:
            self.defect("CASE_VERIFICATION_TRANSFORM_FLAG",
                        f"{case_id}: transformMatches={verif.get('transformMatches')!r}")
        # "unrelated objects/files stayed unchanged" must be declared per creation,
        # and a dispatch that never reached a passing verification is a pending request.
        if verif.get("unrelatedUnchanged") is True:
            self.unrelated_ok_ids.add(case_id)
        elif expect_create:
            self.defect("CASE_UNRELATED_UNDECLARED",
                        f"{case_id}: creation case does not declare "
                        f"unrelatedUnchanged=true in verification.json")
        if raw.get("dispatched") is True and verif.get("status") != PASSING \
                and isinstance(request_id, str):
            self.pending_request_ids.add(request_id)

        removed = id_set(cleanup.get("removedEntityIds"))
        residual = id_set(cleanup.get("residualEntityIds"))
        if cleanup.get("status") != PASSING:
            self.defect("CASE_CLEANUP_STATUS_NOT_PASS",
                        f"{case_id}: cleanup.json status={cleanup.get('status')!r}")
        if removed is None or residual is None:
            self.defect("CASE_CLEANUP_IDS_INVALID", f"{case_id}: cleanup id lists unparsable")
        else:
            if removed != created_ids:
                self.defect("CASE_CLEANUP_IDENTITY_MISMATCH",
                            f"{case_id}: cleanup removed {sorted(removed)} != created "
                            f"{sorted(created_ids)}")
            if residual:
                self.defect("CASE_RESIDUAL_NOT_EMPTY",
                            f"{case_id}: residual entity ids {sorted(residual)}")

        # identity recorded in evidence-index.json must equal the recomputed one
        identity = index_entry.get("identity")
        if not isinstance(identity, dict):
            self.defect("INDEX_CASE_IDENTITY_MISSING", f"{case_id}: no identity block")
            return
        index_ids = id_set(identity.get("entityIds"))
        if index_ids != created_ids:
            self.defect("INDEX_CASE_IDENTITY_MISMATCH",
                        f"{case_id}: index ids {sorted(index_ids or [])} != recomputed "
                        f"{sorted(created_ids)}")
        index_digest = identity.get("contentSha256")
        self.checks += 1
        if index_digest != canonical_sha256(entities):
            self.defect("INDEX_CASE_CONTENT_MISMATCH",
                        f"{case_id}: index contentSha256 {index_digest!r} != recomputed "
                        f"{canonical_sha256(entities)}")

    # -- run-level checks --------------------------------------------------- #

    def required_stages(self):
        layout = self.frozen_contract.get("evidenceLayout")
        stages = layout.get("perCase") if isinstance(layout, dict) else None
        if isinstance(stages, list) and stages and all(isinstance(s, str) for s in stages):
            return tuple(stages)
        return DEFAULT_STAGES

    def index_case(self, case_id):
        return self.index_cases.get(case_id)

    def load_run_file(self, name, missing_code):
        """Load a required run-root artifact. Absent or corrupt is a defect (exit 1),
        not an input error: the run exists, its evidence does not hold up."""
        path = self.run_root / name
        if not path.is_file():
            self.defect(missing_code, f"{name} is absent")
            return {}
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.defect(missing_code + "_UNREADABLE", f"{name}: {exc}")
            return {}
        if not isinstance(doc, dict):
            self.defect(missing_code + "_UNREADABLE", f"{name}: not a JSON object")
            return {}
        return doc

    def mode_tokens(self, mode):
        return {t for t in re.split(r"[^A-Za-z]+", mode or "") if t}

    def mode_requires_live(self, mode):
        return "live" in self.mode_tokens(mode)

    def verify(self):
        if not self.run_root.is_dir():
            raise InputError(f"run root is not a directory: {self.run_root}")
        if not RUN_ID_RE.fullmatch(self.run_id):
            raise InputError(f"run root name is not a 32-hex runId: {self.run_id!r}")

        self.load_frozen_contract()

        checklist_path = self.run_root / "checklist.input.json"
        if not checklist_path.is_file():
            if self.checklist_override is None:
                self.defect("MISSING_CHECKLIST_INPUT", "checklist.input.json is absent")
                raise InputError("checklist.input.json missing; the run pinned no contract of "
                                 "its own (the frozen checklist is not a substitute for the "
                                 "run's pinned copy)")
            # An operator may supply the contract explicitly to look at a run that
            # never pinned one. The verdict is then not a pass and says so.
            checklist_path = self.checklist_override
            self.pinned_contract = False
            self.notes.append(f"contract supplied externally: {checklist_path}")
        self.checklist = read_json(checklist_path, "checklist.input.json")
        self.checklist_source = str(checklist_path)
        if not self.pinned_contract:
            self.defect("CONTRACT_NOT_PINNED_IN_RUN",
                        "the run root has no checklist.input.json; a read-only verifier cannot "
                        "certify a contract that lives outside the run it is checking")
        # The run's copy is an object under test, never a source of denominators.
        self.check_contract_pin()

        self.index = self.load_run_file("evidence-index.json", "MISSING_EVIDENCE_INDEX")
        self.template_matrix = self.load_run_file("template-case-matrix.json",
                                                  "MISSING_TEMPLATE_MATRIX")
        self.parameter_matrix = self.load_run_file("parameter-case-matrix.json",
                                                   "MISSING_PARAMETER_MATRIX")

        for name, doc in (("evidence-index.json", self.index),
                          ("template-case-matrix.json", self.template_matrix),
                          ("parameter-case-matrix.json", self.parameter_matrix)):
            if not doc:
                continue
            found = doc.get("runId")
            if found != self.run_id:
                self.defect("RUNID_MISMATCH",
                            f"{name}: runId {found!r} != run root {self.run_id!r}")

        self.check_contract_closure()
        self.check_gates()
        self.check_cases()
        self.check_result()
        self.check_report_conclusion()
        return self.verdict()

    # -- contract provenance ------------------------------------------------ #

    def load_frozen_contract(self):
        """Read the frozen engineering checklist and verify its pinned digest.

        A stale or edited denominator makes every downstream comparison
        meaningless, so this is an input error (exit 2), not a run defect.
        """
        path = locate_frozen_checklist()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise InputError(f"cannot read the frozen checklist {path}: {exc}") from exc
        actual = hashlib.sha256(raw).hexdigest()
        if actual != FROZEN_CHECKLIST_SHA256:
            raise InputError(
                f"frozen checklist {path} sha256 {actual} != pinned "
                f"{FROZEN_CHECKLIST_SHA256}; the verifier's own denominator changed, "
                "no verdict is possible until the pin is re-established deliberately")
        try:
            frozen = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InputError(f"frozen checklist {path} is not valid UTF-8 JSON: {exc}") from exc
        if not isinstance(frozen, dict):
            raise InputError(f"frozen checklist {path} is not a JSON object")
        self.frozen_contract = frozen
        self.frozen_source = str(path)
        self.frozen_sha256 = actual

    def check_contract_pin(self):
        """Compare the run-pinned checklist against the frozen one, both ways."""
        run_contract = self.checklist
        frozen = self.frozen_contract
        if not isinstance(run_contract, dict):
            self.defect("RUN_CONTRACT_NOT_OBJECT",
                        "the run-pinned checklist.input.json is not a JSON object")
            return
        if canonical_sha256(run_contract) == canonical_sha256(frozen):
            return
        before = len(self.defects)
        self.diff_contract_list(frozen, run_contract, "gates", "id",
                                ("required", "evidenceMode", "evidenceRequired"))
        self.diff_contract_list(frozen, run_contract, "templateCases", "caseId",
                                ("required", "templateId"))
        self.diff_contract_list(frozen, run_contract, "parameterCases", "caseId",
                                ("required", "evidenceMode"))
        frozen_layout = (frozen.get("evidenceLayout") or {}).get("perCase")
        run_layout = (run_contract.get("evidenceLayout") or {}).get("perCase")
        if frozen_layout != run_layout:
            self.defect("RUN_CONTRACT_LAYOUT_MISMATCH",
                        f"run-pinned evidenceLayout.perCase {run_layout!r} != frozen "
                        f"{frozen_layout!r}")
        if len(self.defects) == before:
            self.defect("RUN_CONTRACT_UNEXPECTED_DRIFT",
                        "the run-pinned checklist.input.json differs from the frozen checklist "
                        "in a field this verifier does not enumerate")

    def diff_contract_list(self, frozen, run_contract, key, id_field, fields):
        frozen_entries = {}
        for entry in frozen.get(key) or []:
            if isinstance(entry, dict):
                frozen_entries[str(entry.get(id_field))] = entry
        run_entries = {}
        for entry in run_contract.get(key) or []:
            if isinstance(entry, dict):
                run_entries[str(entry.get(id_field))] = entry
        label = f"RUN_CONTRACT_{key.upper()}"
        for entry_id in sorted(set(frozen_entries) - set(run_entries)):
            self.defect(label + "_MISSING",
                        f"{key} entry {entry_id!r} is frozen-required but absent from the "
                        "run-pinned checklist.input.json")
        for entry_id in sorted(set(run_entries) - set(frozen_entries)):
            self.defect(label + "_EXTRA",
                        f"{key} entry {entry_id!r} is in the run-pinned checklist.input.json "
                        "but not in the frozen checklist")
        for entry_id in sorted(set(frozen_entries) & set(run_entries)):
            expected = frozen_entries[entry_id]
            got = run_entries[entry_id]
            for field in fields:
                if expected.get(field) != got.get(field):
                    self.defect(label + "_FIELD_MISMATCH",
                                f"{key}[{entry_id}].{field}: run-pinned "
                                f"{got.get(field)!r} != frozen {expected.get(field)!r}")

    def check_contract_closure(self):
        # Denominators come from the FROZEN checklist only. The run-pinned copy was
        # already compared against it and can never widen or narrow these sets.
        required_gates = self.frozen_contract.get("gates")
        if not isinstance(required_gates, list):
            raise InputError("frozen checklist has no gates list")
        required_templates = {}
        for entry in self.frozen_contract.get("templateCases") or []:
            if isinstance(entry, dict) and entry.get("required", True):
                required_templates[str(entry.get("caseId"))] = entry.get("templateId")
        required_parameters = {}
        for entry in self.frozen_contract.get("parameterCases") or []:
            if isinstance(entry, dict) and entry.get("required", True):
                required_parameters[str(entry.get("caseId"))] = entry.get("evidenceMode")

        self.required_gate_ids = [g.get("id") for g in required_gates
                                  if isinstance(g, dict) and g.get("required", True)]
        self.gate_spec = {g["id"]: g for g in required_gates
                          if isinstance(g, dict) and isinstance(g.get("id"), str)}
        self.required_templates = required_templates
        self.required_parameters = required_parameters

        self.index_gate_map = {}
        for gate in (self.index.get("gates") or []):
            if isinstance(gate, dict) and isinstance(gate.get("id"), str):
                if gate["id"] in self.index_gate_map:
                    self.defect("GATE_DUPLICATE", f"{gate['id']} appears twice in the index")
                self.index_gate_map[gate["id"]] = gate

        self.index_cases = {}
        self.index_case_kinds = {}
        for case in (self.index.get("cases") or []):
            if not isinstance(case, dict) or not isinstance(case.get("caseId"), str):
                self.defect("INDEX_CASE_INVALID", f"case entry invalid: {case!r}")
                continue
            if case["caseId"] in self.index_cases:
                self.defect("INDEX_CASE_DUPLICATE", f"{case['caseId']} appears twice")
            self.index_cases[case["caseId"]] = case
            self.index_case_kinds[case["caseId"]] = case.get("kind")

    def check_gates(self):
        for gate_id in self.required_gate_ids:
            gate = self.index_gate_map.get(gate_id)
            if gate is None:
                self.defect("GATE_MISSING", f"required gate {gate_id} absent from the index")
                continue
            if gate.get("status") != PASSING:
                self.defect("GATE_STATUS_NOT_PASS",
                            f"{gate_id}: status={gate.get('status')!r}")
            spec = self.gate_spec.get(gate_id) or {}
            needed = spec.get("evidenceRequired") or []
            backed = {}
            for item in (gate.get("evidence") or []):
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    backed[item["name"]] = item
            for name in needed:
                if name not in backed:
                    self.defect("GATE_EVIDENCE_MISSING",
                                f"{gate_id}: required evidence {name!r} has no index entry")
                    continue
                self.hash_matches(backed[name],
                                  f"GATE_EVIDENCE[{gate_id}/{name}]")

    def matrix_cases(self, matrix, key, what):
        cases = matrix.get(key) if isinstance(matrix, dict) else None
        if not isinstance(cases, list):
            self.defect("MATRIX_CASES_MISSING", f"{what}: no usable {key} list")
            return {}
        out = {}
        for entry in cases:
            if not isinstance(entry, dict) or not isinstance(entry.get("caseId"), str):
                self.defect("MATRIX_CASE_ENTRY_INVALID", f"{what}: bad entry {entry!r}")
                continue
            if entry["caseId"] in out:
                self.defect("MATRIX_CASE_DUPLICATE", f"{what}: {entry['caseId']} duplicated")
            out[entry["caseId"]] = entry
        return out

    def check_cases(self):
        template_cases = self.matrix_cases(self.template_matrix, "templates",
                                           "template-case-matrix.json")
        parameter_cases = self.matrix_cases(self.parameter_matrix, "cases",
                                            "parameter-case-matrix.json")

        # declared id lists must agree with the per-case entries (set closure, both ways)
        declared = self.template_matrix.get("templateIds")
        declared_ids = set(declared) if isinstance(declared, list) else None
        entry_ids = {e.get("templateId") for e in template_cases.values()}
        if declared_ids is not None and declared_ids != entry_ids:
            self.defect("MATRIX_TEMPLATE_IDS_INCONSISTENT",
                        f"templateIds list and per-case templateId disagree: "
                        f"only-in-list={sorted(declared_ids - entry_ids)} "
                        f"only-in-cases={sorted(entry_ids - declared_ids)}")
        if len(entry_ids) != len(template_cases):
            self.defect("MATRIX_TEMPLATEID_DUPLICATE",
                        "two template cases share a templateId")

        for case_id, expected_id in sorted(self.required_templates.items()):
            if case_id not in template_cases:
                self.defect("MISSING_REQUIRED_TEMPLATE",
                            f"{case_id} (templateId={expected_id}) is required by "
                            f"the frozen checklist but absent from template-case-matrix.json")
        for case_id in sorted(set(template_cases) - set(self.required_templates)):
            self.defect("UNEXPECTED_TEMPLATE",
                        f"{case_id} is in the matrix but not required by the frozen checklist")

        for case_id, mode in sorted(self.required_parameters.items()):
            if case_id not in parameter_cases:
                self.defect("MISSING_REQUIRED_PARAMETER_CASE",
                            f"{case_id} is required by the frozen checklist but absent from "
                            f"parameter-case-matrix.json")
        for case_id in sorted(set(parameter_cases) - set(self.required_parameters)):
            self.defect("UNEXPECTED_PARAMETER_CASE",
                        f"{case_id} is not required by the frozen checklist")

        if isinstance(self.template_matrix.get("requiredTemplateCount"), int) and \
                self.template_matrix["requiredTemplateCount"] != len(self.required_templates):
            self.defect("TEMPLATE_COUNT_MISMATCH",
                        f"requiredTemplateCount="
                        f"{self.template_matrix['requiredTemplateCount']} != "
                        f"{len(self.required_templates)} required by the frozen checklist")

        accepted_templates = set()
        accepted_parameters = set()
        for case_id, expected_id in sorted(self.required_templates.items()):
            entry = template_cases.get(case_id)
            if entry is None:
                continue
            ok = self.check_case(case_id, "template", entry, True, template_id=expected_id)
            if ok and entry.get("status") == PASSING:
                accepted_templates.add(expected_id)
        for case_id, mode in sorted(self.required_parameters.items()):
            entry = parameter_cases.get(case_id)
            if entry is None:
                continue
            ok = self.check_case(case_id, "parameter", entry, self.mode_requires_live(mode))
            if ok and entry.get("status") == PASSING:
                accepted_parameters.add(case_id)

        for case_id in sorted(set(self.index_cases) -
                              set(self.required_templates) - set(self.required_parameters)):
            self.defect("INDEX_CASE_NOT_IN_MATRIX",
                        f"{case_id} has index evidence but no checklist case")
        self.accepted_templates = accepted_templates
        self.accepted_parameters = accepted_parameters

    def check_result(self):
        self.result = self.load_run_file("result.json", "MISSING_RESULT_JSON")
        if not self.result:
            return
        found = self.result.get("runId")
        if found != self.run_id:
            self.defect("RESULT_RUNID_MISMATCH",
                        f"result.json runId {found!r} != {self.run_id!r}")
        claimed = self.recomputed_passing()
        for key in ("ok", "fullRunAccepted", "groupFullyClosed"):
            value = self.result.get(key)
            if not isinstance(value, bool):
                self.defect("RESULT_CLAIM_ABSENT", f"result.json has no boolean {key}")
            elif value != claimed:
                self.defect("TOP_LEVEL_CLAIM_MISMATCH",
                            f"result.json {key}={value} but evidence recomputes to {claimed}")
        covered = self.result.get("templatesCovered")
        if isinstance(covered, list):
            claimed_ids = {c for c in covered if isinstance(c, int)}
            if claimed_ids != self.accepted_templates:
                self.defect("RESULT_COVERAGE_MISMATCH",
                            "result.json templatesCovered does not equal the union of "
                            "independently accepted template ids: "
                            f"only-claimed={sorted(claimed_ids - self.accepted_templates)} "
                            f"only-accepted={sorted(self.accepted_templates - claimed_ids)}")
        else:
            self.defect("RESULT_COVERAGE_ABSENT", "result.json has no templatesCovered list")
        declared_created = id_set(self.result.get("createdEntityIds"))
        if declared_created is None:
            self.defect("RESULT_CREATED_IDS_ABSENT",
                        "result.json has no createdEntityIds list")
        elif declared_created != self.created_ids:
            self.defect("RESULT_CREATED_IDS_MISMATCH",
                        "result.json createdEntityIds is not the union of the ids recomputed "
                        "from per-case after.json: "
                        f"only-claimed={sorted(declared_created - self.created_ids)} "
                        f"only-recomputed={sorted(self.created_ids - declared_created)}")
        declared_cleaned = id_set(self.result.get("cleanedEntityIds"))
        if declared_cleaned is not None and declared_cleaned != self.cleaned_ids:
            self.defect("RESULT_CLEANED_IDS_MISMATCH",
                        "result.json cleanedEntityIds is not the union recomputed from per-case "
                        "cleanup.json: "
                        f"only-claimed={sorted(declared_cleaned - self.cleaned_ids)} "
                        f"only-recomputed={sorted(self.cleaned_ids - declared_cleaned)}")

        # parameter-case coverage is a denominator too, not decoration
        covered_params = self.result.get("parameterCasesCovered")
        if isinstance(covered_params, list):
            claimed_params = {c for c in covered_params if isinstance(c, str)}
            if len(claimed_params) != len(covered_params):
                self.defect("RESULT_PARAMETER_COVERAGE_INVALID",
                            "result.json parameterCasesCovered holds non-string entries")
            if claimed_params != self.accepted_parameters:
                self.defect("RESULT_PARAMETER_COVERAGE_MISMATCH",
                            "result.json parameterCasesCovered does not equal the set of "
                            "independently accepted parameter cases: "
                            f"only-claimed={sorted(claimed_params - self.accepted_parameters)} "
                            f"only-accepted={sorted(self.accepted_parameters - claimed_params)}")
        else:
            self.defect("RESULT_PARAMETER_COVERAGE_ABSENT",
                        "result.json has no parameterCasesCovered list")

        # top-level "unrelated objects/files stayed unchanged" and "no pending
        # requests" must agree with the per-case evidence, both ways.
        declared_unrelated = self.string_set(self.result.get("unrelatedUnchangedCaseIds"),
                                             "unrelatedUnchangedCaseIds")
        if declared_unrelated is None:
            self.defect("RESULT_UNRELATED_CLAIM_ABSENT",
                        "result.json has no unrelatedUnchangedCaseIds list")
        elif declared_unrelated != self.unrelated_ok_ids:
            self.defect("RESULT_UNRELATED_CLAIM_MISMATCH",
                        "result.json unrelatedUnchangedCaseIds is not the set of cases whose "
                        "verification.json declares unrelatedUnchanged=true: "
                        f"only-claimed={sorted(declared_unrelated - self.unrelated_ok_ids)} "
                        f"only-evidenced={sorted(self.unrelated_ok_ids - declared_unrelated)}")
        declared_pending = self.string_set(self.result.get("pendingRequestIds"),
                                           "pendingRequestIds")
        if declared_pending is None:
            self.defect("RESULT_PENDING_CLAIM_ABSENT",
                        "result.json has no pendingRequestIds list")
        else:
            if declared_pending != self.pending_request_ids:
                self.defect("RESULT_PENDING_CLAIM_MISMATCH",
                            "result.json pendingRequestIds is not the set of requestIds "
                            "recomputed from the dispatch/verification evidence: "
                            f"only-claimed={sorted(declared_pending - self.pending_request_ids)} "
                            f"only-recomputed="
                            f"{sorted(self.pending_request_ids - declared_pending)}")
            phantom = declared_pending - self.observed_request_ids
            if phantom:
                self.defect("RESULT_PENDING_PHANTOM",
                            f"result.json names pending requestIds that appear in no case "
                            f"intent: {sorted(phantom)}")

    def string_set(self, value, what):
        """Normalise a JSON list of strings to a set; None when unusable."""
        if value is None:
            return None
        if not isinstance(value, list):
            self.defect("RESULT_CLAIM_NOT_LIST", f"result.json {what} is not a list")
            return None
        out = set()
        for item in value:
            if not isinstance(item, str):
                self.defect("RESULT_CLAIM_NOT_LIST",
                            f"result.json {what} holds a non-string entry {item!r}")
                return None
            out.add(item)
        return out

    # -- report prose vs machine verdict (finding C5) ------------------------ #

    def check_report_conclusion(self):
        """report.md must carry a fenced JSON conclusion the verifier can recheck.

        Existence plus a matching sha256 proves only that the bytes are the ones
        the index names. This block makes the prose answerable to the machine
        verdict: its fields must equal what was recomputed here.
        """
        report = self.run_root / REPORT_MD_NAME
        if not report.is_file():
            self.defect("REPORT_MD_ABSENT", f"{REPORT_MD_NAME} is absent from the run root")
            return
        try:
            text = report.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.defect("REPORT_MD_UNREADABLE", f"{REPORT_MD_NAME}: {exc}")
            return
        block = None
        for _info, body in FENCE_RE.findall(text):
            try:
                parsed = json.loads(body)
            except ValueError:
                continue
            if isinstance(parsed, dict) and "fullRunAccepted" in parsed:
                block = parsed
                break
        if block is None:
            self.defect("REPORT_CONCLUSION_BLOCK_ABSENT",
                        "report.md has no fenced JSON block carrying fullRunAccepted; a "
                        "machine verdict that the prose need not match is not verifiable")
            return
        expected = {
            "fullRunAccepted": self.recomputed_passing(),
            "defectCount": len(self.defects),
            "requiredTemplateCount": len(self.required_templates),
            "acceptedTemplateCount": len(self.accepted_templates),
        }
        for key in CONCLUSION_KEYS:
            if key not in block:
                self.defect("REPORT_CONCLUSION_KEY_ABSENT",
                            f"report.md conclusion block has no {key!r}")
            elif block[key] != expected[key]:
                self.defect("REPORT_CONCLUSION_MISMATCH",
                            f"report.md {key}={block[key]!r} but the verifier recomputes "
                            f"{expected[key]!r}")

    # -- verdict ------------------------------------------------------------ #

    def recomputed_passing(self):
        """Honest verdict: every required gate and every required case passes."""
        if not self.required_gate_ids:
            return False
        if any(self.index_gate_map.get(g, {}).get("status") != PASSING
               for g in self.required_gate_ids):
            return False
        if self.accepted_templates != {v for v in self.required_templates.values()}:
            return False
        if self.accepted_parameters != set(self.required_parameters):
            return False
        return not self.defects

    def verdict(self):
        passing = self.recomputed_passing()
        return {
            "ok": passing,
            "schemaVersion": 1,
            "kind": "entity-create-full-run-independent-acceptance",
            "runId": self.run_id,
            "runRoot": str(self.run_root),
            "checklistSource": self.checklist_source,
            "contractPinnedInRun": self.pinned_contract,
            "frozenChecklistSource": self.frozen_source,
            "frozenChecklistSha256": self.frozen_sha256,
            "notes": self.notes,
            "checkedFiles": self.checks,
            "requiredGateCount": len(self.required_gate_ids),
            "requiredTemplateCount": len(self.required_templates),
            "requiredParameterCaseCount": len(self.required_parameters),
            "acceptedTemplateCount": len(getattr(self, "accepted_templates", ())),
            "acceptedParameterCaseCount": len(getattr(self, "accepted_parameters", ())),
            "unrelatedUnchangedCaseCount": len(self.unrelated_ok_ids),
            "pendingRequestCount": len(self.pending_request_ids),
            "fullRunAccepted": passing,
            "groupFullyClosed": passing,
            "defectCount": len(self.defects),
            "defects": self.defects,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_root", type=Path,
                        help=".runtime/verification/entity-create-full-run/<runId>")
    parser.add_argument("--output", type=Path, help="write the JSON verdict here")
    parser.add_argument("--quiet", action="store_true", help="print only the JSON verdict")
    parser.add_argument("--checklist", type=Path, default=None,
                        help="inspect a run that never pinned its own checklist.input.json by "
                             "supplying the contract explicitly; this is recorded as a defect "
                             "and can never produce exit 0")
    args = parser.parse_args(argv)

    # Finding C4: a "read-only" tool must not be able to overwrite the evidence it
    # is auditing. Refuse an --output that lands anywhere inside the run root.
    if args.output is not None and is_within(args.output, args.run_root):
        message = (f"--output {args.output} resolves inside the audited run "
                   f"{args.run_root}; refusing to write into the evidence under test")
        print(f"DEFECT OUTPUT_INSIDE_RUN: {message}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": message, "inputUnusable": True},
                         ensure_ascii=False))
        return 2

    try:
        verifier = Verifier(args.run_root, args.checklist)
        verdict = verifier.verify()
    except InputError as exc:
        print(f"DEFECT INPUT_UNUSABLE: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": str(exc), "inputUnusable": True},
                         ensure_ascii=False))
        return 2
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"DEFECT INPUT_UNUSABLE: {exc}", file=sys.stderr)
        print(json.dumps({"ok": False, "error": str(exc), "inputUnusable": True},
                         ensure_ascii=False))
        return 2

    if not args.quiet:
        for defect in verdict["defects"]:
            print(f"DEFECT {defect['code']}: {defect['detail']}")
    text = json.dumps(verdict, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
