#!/usr/bin/env python3
"""DS-10 independent counterexample generator.

Builds a *forged* run root -- one that contains ZERO live operations (no game,
no editor, no helper, no native run directory, no request journal, no saved
file) -- and asks `tools/game-executor/verify_entity_create_run.py` to judge it.

This program is fully isolated:
  * it writes only under the directory given on the command line;
  * it opens no game process, sends nothing to the helper, touches no journal,
    no formal save and no historical evidence;
  * it reads exactly one outside file -- the frozen checklist, byte-copied so
    the run can "pin" a contract -- plus, for one variant, a single historical
    artifact used as an *attack input* (never modified, never moved).

It is deliberately an INDEPENDENT implementation: it does not import, copy or
call `fixtures/make_fixture_run.py`. The point is that an outside actor with no
access to that generator can still produce a run the verifier accepts.

Usage:
    python make_forged_run.py <base-dir> --variant <name>

Variants (each is written to <base-dir>/<variant>/<runId>/):
    solid          complete, self-consistent, plausible bodies, NO live producer
    empty-shell    every gate-evidence file is the empty object {}      (attack A)
    wrong-ids      gate evidence names a wrong levelId/requestId        (attack B)
    old-log        gate evidence is a byte copy of a historical artifact(attack C)
    no-live-claim  identical to solid but stages carry live:false       (control)
    wrong-runid    stage files carry another run's runId                (control)

Exit code is the generator's own: 0 written, 2 refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

# VENDORED into the tree (was .runtime/.../ds10/forgery/): one level shallower,
# so the depth changes by exactly one.
REPO_ROOT = Path(__file__).resolve().parents[4]
FROZEN_CHECKLIST = REPO_ROOT / "docs" / "ds-handoff" / "07-ENTITY-CREATE-CHECKLIST.json"
FROZEN_SHA256 = "84540680083c07df2413116bb212633eac80137cf29f1dc8b30c5862344abc83"

# A single real, historical artifact (recorded 2026-09-29) used ONLY as an
# attack input for the `old-log` variant. It is read, never written or moved.
HISTORICAL_ARTIFACT = (REPO_ROOT / ".runtime" / "verification" / "entity-create-full-run"
                       / "f87472fb0a5cc2b77e1446124787e05d"
                       / "blocker-helper-unavailable-20260929T1610Z.json")

# The forged run ids are valid 32-hex on purpose: the verifier treats
# "directory name == runId" as an invariant, and a forgery must not be rejected
# for the wrong reason.
RUN_IDS = {
    "solid": "deadbeefdeadbeefdeadbeefdead0001",
    "empty-shell": "deadbeefdeadbeefdeadbeefdead0002",
    "wrong-ids": "deadbeefdeadbeefdeadbeefdead0003",
    "old-log": "deadbeefdeadbeefdeadbeefdead0004",
    "no-live-claim": "deadbeefdeadbeefdeadbeefdead0005",
    "wrong-runid": "deadbeefdeadbeefdeadbeefdead0006",
}

GATE_EVIDENCE_NAMES = {
    "S00": ["support-contract.json", "source-hashes.json"],
    "S01": ["source-files", "build-and-related-tests", "capability-contract"],
    "S02": ["session.json", "level-observation", "complete-baseline",
            "coordinate-contract", "recovery-manifest"],
    "S03": ["intent.json", "cli-request", "native-create-receipt", "created-id"],
    "S04": ["before", "fresh-after", "independent-readback"],
    "S05": ["fresh-save-review", "save-receipt", "before-gil", "after-gil",
            "disk-diff", "allowed-delta-audit"],
    "S06": ["initialize", "tools-list", "schema-hash", "business-call-trace",
            "independent-effects"],
    "S07": ["creation-profile", "exposed-tools", "model-tool-call-trace",
            "recoverable-pre-dispatch-error", "independent-effects"],
    "S08": ["fresh-preflight", "reopen-review", "original-request",
            "complete-observation", "reopen-acceptance", "fresh-content-readback"],
    "S09": ["current-run-identity", "start-and-stop", "runtime-object-correlation",
            "runtime-observation", "return-to-editor"],
    "S10": ["template-case-matrix", "parameter-case-matrix", "per-case-evidence"],
    "S11": ["negative-cases", "journal-and-dispatch-count",
            "pending-reconciliation-tests"],
    "S12": ["ownership-proof", "dry-run", "per-id-delete-result", "fresh-inspect",
            "cleanup-save-diff", "cleanup-reopen", "resource-cleanup"],
    "S13": ["acceptance-report", "adversarial-fixture-results", "result.json",
            "report.md"],
}

# Gate evidence items whose producer is a run-root file: point the index at the
# root file, the way the real adapter binds them.
ROOT_BOUND = {
    "support-contract.json": "support-contract.json",
    "source-hashes.json": "source-hashes.json",
    "template-case-matrix": "template-case-matrix.json",
    "parameter-case-matrix": "parameter-case-matrix.json",
    "result.json": "result.json",
    "report.md": "report.md",
}

STAGES = ("intent", "before", "raw-call", "after", "verification", "cleanup")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(obj) -> str:
    return sha256_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False).encode("utf-8"))


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                      allow_nan=False) + "\n"


def write_json(path: Path, value) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(value)
    path.write_text(text, encoding="utf-8", newline="\n")
    return sha256_bytes(text.encode("utf-8"))


def request_id_for(case_id: str) -> str:
    return hashlib.sha256(("ds10-forgery|" + case_id).encode()).hexdigest()[:32]


def entity_id_for(case_id: str) -> int:
    return 800000000 + (int(hashlib.sha256(case_id.encode()).hexdigest()[:6], 16) % 1000000)


def mode_requires_live(mode: str) -> bool:
    return "live" in {t for t in re.split(r"[^A-Za-z]+", mode or "") if t}


class Forge:
    def __init__(self, run_root: Path, variant: str):
        self.run_root = run_root
        self.variant = variant
        self.run_id = run_root.name
        self.contract = json.loads(FROZEN_CHECKLIST.read_text(encoding="utf-8"))
        self.written = []

    # -- helpers ---------------------------------------------------------- #
    def rel(self, *parts) -> str:
        return "/".join(parts)

    def note(self, relative: str):
        self.written.append(relative)

    # -- evidence bodies --------------------------------------------------- #
    def gate_body(self, gate_id: str, name: str):
        """A plausible-looking gate-evidence body, or the attack payload."""
        if self.variant == "empty-shell":
            return {}
        if self.variant == "wrong-ids":
            # A wrong level id and a wrong request id in the body. The verifier
            # only ever compares a `runId` field, so these should be ignored.
            return {
                "gate": gate_id, "evidenceItem": name,
                "levelId": 999999999,
                "requestId": "ffffffffffffffffffffffffffffffff",
                "gamePid": 1, "editorPid": 2,
                "claimedProducer": "none",
            }
        if self.variant == "old-log":
            return None  # filled in by the caller with historical bytes
        # "solid"/"no-live-claim"/"wrong-runid": plausible shape, no runId field
        return {
            "gate": gate_id, "evidenceItem": name,
            "ok": True, "status": "pass",
            "note": ("placeholder evidence produced by DS-10's isolated forgery; "
                     "no live operation backs this file"),
        }

    def stage_body(self, case_id: str, stage: str, live: bool, template_id: int,
                   run_id_for_stage: str):
        request_id = request_id_for(case_id)
        created = entity_id_for(case_id)
        transform = {"position": [1.0, 2.0, 3.0],
                     "rotation": [0.0, 0.0, 0.0],
                     "scale": [1.0, 1.0, 1.0]}
        base = {"schemaVersion": 1, "stage": stage, "caseId": case_id,
                "runId": run_id_for_stage, "live": live,
                "forgedBy": "ds10 isolated generator; no live producer exists"}
        if stage == "intent":
            base.update({"requestId": request_id, "templateId": template_id,
                         "expectCreate": True, "expectedTransform": transform})
        elif stage == "before":
            base.update({"snapshotComplete": True, "snapshotTruncated": False,
                         "entityIds": [1000], "entityCount": 1,
                         "levelId": 1073741839})
        elif stage == "raw-call":
            base.update({"requestId": request_id, "templateId": template_id,
                         "dispatched": True, "dispatchCount": 1,
                         "exitCode": 0, "errorCode": None, "transform": transform,
                         "nativeRun": "R:/does/not/exist", "nativeStarted": True,
                         "nativeCalled": "entity.create"})
        elif stage == "after":
            entities = [{"entityId": created, "templateId": template_id,
                         "transform": transform}]
            base.update({"entityIds": [1000, created], "entityCount": 2,
                         "createdEntityIds": [created], "entities": entities,
                         "contentSha256": canonical_sha256(entities),
                         "levelId": 1073741839})
        elif stage == "verification":
            base.update({"status": "pass", "independent": True,
                         "transformMatches": True, "unrelatedUnchanged": True,
                         "createdEntityIds": [created]})
        elif stage == "cleanup":
            base.update({"status": "pass", "removedEntityIds": [created],
                         "residualEntityIds": []})
        return base

    # -- build ------------------------------------------------------------- #
    def build(self):
        v = self.variant
        run_root = self.run_root
        root_run_id = self.run_id
        # Only the `wrong-runid` variant lies about the runId inside stage files.
        stage_run_id = ("00000000000000000000000000000000" if v == "wrong-runid"
                        else root_run_id)
        stages_live = (v != "no-live-claim")

        # 0. the pin: a byte-identical copy of the frozen checklist
        (run_root / "checklist.input.json").write_bytes(FROZEN_CHECKLIST.read_bytes())
        self.note("checklist.input.json")

        # 1. root gate evidence files that the index binds at the root
        write_json(run_root / "support-contract.json",
                   {"kind": "ds10-forgery-support-contract", "ok": True})
        write_json(run_root / "source-hashes.json",
                   {"kind": "ds10-forgery-source-hashes", "ok": True, "files": {}})
        self.note("support-contract.json")
        self.note("source-hashes.json")

        # 2. per-gate evidence files
        gate_evidence = {}   # gate -> [(name, relative)]
        for gate_id, names in GATE_EVIDENCE_NAMES.items():
            gate_evidence[gate_id] = []
            for name in names:
                if name in ROOT_BOUND:
                    gate_evidence[gate_id].append((name, ROOT_BOUND[name]))
                    continue
                relative = self.rel("gate-evidence", gate_id, f"{name}.json")
                target = run_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if v == "old-log":
                    # attack C: the bytes are a REAL historical artifact from a
                    # previous round, presented as this run's gate evidence.
                    target.write_bytes(HISTORICAL_ARTIFACT.read_bytes())
                else:
                    write_json(target, self.gate_body(gate_id, name))
                gate_evidence[gate_id].append((name, relative))
                self.note(relative)

        # 3. per-case stage files
        cases = []           # index case entries
        matrix_templates = []
        matrix_parameters = []
        created_all = []
        unrelated_all = []
        template_ids_all = []

        for case in self.contract["templateCases"]:
            case_id = case["caseId"]
            template_id = case["templateId"]
            template_ids_all.append(template_id)
            created = entity_id_for(case_id)
            created_all.append(str(created))
            unrelated_all.append(case_id)
            evidence_dir = self.rel("cases", case_id)
            stages = {}
            for stage in STAGES:
                body = self.stage_body(case_id, stage, stages_live, template_id,
                                       stage_run_id)
                relative = self.rel(evidence_dir, f"{stage}.json")
                digest = write_json(run_root / relative, body)
                stages[stage] = {"path": relative, "sha256": digest}
                self.note(relative)
            entities = [{"entityId": created, "templateId": template_id,
                         "transform": {"position": [1.0, 2.0, 3.0],
                                       "rotation": [0.0, 0.0, 0.0],
                                       "scale": [1.0, 1.0, 1.0]}}]
            cases.append({"caseId": case_id, "kind": "template",
                          "templateId": template_id, "stages": stages,
                          "identity": {"entityIds": [created],
                                       "contentSha256": canonical_sha256(entities)}})
            matrix_templates.append({"caseId": case_id, "templateId": template_id,
                                     "required": True, "status": "pass",
                                     "evidenceDir": evidence_dir})

        for case in self.contract["parameterCases"]:
            case_id = case["caseId"]
            mode = case.get("evidenceMode")
            live = mode_requires_live(mode) and stages_live
            created = entity_id_for(case_id)
            created_all.append(str(created))
            unrelated_all.append(case_id)
            evidence_dir = self.rel("cases", case_id)
            stages = {}
            for stage in STAGES:
                body = self.stage_body(case_id, stage, live, 20000000,
                                       stage_run_id)
                relative = self.rel(evidence_dir, f"{stage}.json")
                digest = write_json(run_root / relative, body)
                stages[stage] = {"path": relative, "sha256": digest}
                self.note(relative)
            entities = [{"entityId": created, "templateId": 20000000,
                         "transform": {"position": [1.0, 2.0, 3.0],
                                       "rotation": [0.0, 0.0, 0.0],
                                       "scale": [1.0, 1.0, 1.0]}}]
            cases.append({"caseId": case_id, "kind": "parameter", "stages": stages,
                          "identity": {"entityIds": [created],
                                       "contentSha256": canonical_sha256(entities)}})
            matrix_parameters.append({"caseId": case_id, "required": True,
                                      "status": "pass", "evidenceDir": evidence_dir,
                                      "evidenceMode": mode})

        # 4. the two matrices
        template_matrix = {
            "schemaVersion": 1, "kind": "entity-create-template-case-matrix",
            "runId": root_run_id, "requiredTemplateCount": len(matrix_templates),
            "acceptedTemplateCount": len(matrix_templates),
            "templateIds": sorted(template_ids_all),
            "templates": matrix_templates,
        }
        parameter_matrix = {
            "schemaVersion": 1, "kind": "entity-create-parameter-case-matrix",
            "runId": root_run_id, "requiredParameterCaseCount": len(matrix_parameters),
            "acceptedParameterCaseCount": len(matrix_parameters),
            "cases": matrix_parameters,
        }
        write_json(run_root / "template-case-matrix.json", template_matrix)
        write_json(run_root / "parameter-case-matrix.json", parameter_matrix)
        self.note("template-case-matrix.json")
        self.note("parameter-case-matrix.json")

        # 5. result.json -- its claims must agree with the recomputed verdict
        result = {
            "schemaVersion": 1, "kind": "ds10-forgery-result", "runId": root_run_id,
            "ok": True, "fullRunAccepted": True, "groupFullyClosed": True,
            "templatesCovered": sorted(template_ids_all),
            "parameterCasesCovered": [c["caseId"] for c in self.contract["parameterCases"]],
            "createdEntityIds": sorted(created_all),
            "cleanedEntityIds": sorted(created_all),
            "unrelatedUnchangedCaseIds": sorted(unrelated_all),
            "pendingRequestIds": [],
            "note": "DS-10 isolated forgery: no live operation produced any of this",
        }
        write_json(run_root / "result.json", result)
        self.note("result.json")

        # 6. report.md with the machine-readable conclusion block
        block = {"fullRunAccepted": True, "defectCount": 0,
                 "requiredTemplateCount": len(matrix_templates),
                 "acceptedTemplateCount": len(matrix_templates)}
        report = ("# FORGED RUN -- DS-10 isolated counterexample\n\n"
                  "This directory was produced by `ds10/forgery/make_forged_run.py`.\n"
                  "It contains NO live game/editor call, NO helper dispatch, NO native\n"
                  "run, NO request journal and NO saved file. Every byte below was\n"
                  "written by a text generator.\n\n"
                  "```conclusion\n" + json.dumps(block, sort_keys=True) + "\n```\n")
        (run_root / "report.md").write_text(report, encoding="utf-8", newline="\n")
        self.note("report.md")

        # 7. evidence-index.json (written last: it hashes every file above)
        gates = []
        for gate in self.contract["gates"]:
            gate_id = gate["id"]
            evidence = []
            for name, relative in gate_evidence[gate_id]:
                evidence.append({"name": name, "path": relative,
                                 "sha256": sha256_file(run_root / relative),
                                 "basis": "ds10 forgery"})
            gates.append({"id": gate_id, "status": "pass", "evidence": evidence,
                          "required": True})
        index = {"schemaVersion": 1, "kind": "entity-create-full-run-evidence-index",
                 "runId": root_run_id, "gates": gates, "cases": cases}
        write_json(run_root / "evidence-index.json", index)
        self.note("evidence-index.json")

        return len(self.written)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base_dir", type=Path)
    parser.add_argument("--variant", required=True, choices=sorted(RUN_IDS))
    args = parser.parse_args(argv)

    actual = sha256_file(FROZEN_CHECKLIST)
    if actual != FROZEN_SHA256:
        print(f"REFUSED: frozen checklist sha256 {actual} != {FROZEN_SHA256}",
              file=sys.stderr)
        return 2

    run_root = args.base_dir.resolve() / args.variant / RUN_IDS[args.variant]
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True)

    forge = Forge(run_root, args.variant)
    count = forge.build()
    print(f"variant   {args.variant}")
    print(f"run root  {run_root}")
    print(f"runId     {run_root.name}")
    print(f"files     {count} (+ checklist.input.json copied)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
