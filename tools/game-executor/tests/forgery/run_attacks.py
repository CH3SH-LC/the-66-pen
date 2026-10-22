#!/usr/bin/env python3
"""DS-10 attack driver: generate each forged-run variant, run the independent
verifier on it, and record the verdict.

Fully isolated: writes only under <base-dir>; opens no game/editor/helper; the
verifier is invoked as a subprocess (its own exit code is recorded verbatim).

    python run_attacks.py <base-dir>

Writes <base-dir>/attack-results.json.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
# VENDORED: was the .runtime mcp-venv interpreter, which does not exist after a
# .runtime clean.  The control must not depend on the tree it is protecting.
PY = Path(sys.executable)
VERIFIER = REPO_ROOT / "tools" / "game-executor" / "verify_entity_create_run.py"
GENERATOR = HERE / "make_forged_run.py"

VARIANTS = ["solid", "empty-shell", "wrong-ids", "old-log", "no-live-claim", "wrong-runid"]

# Surgical mutations, each applied to a fresh copy of the `solid` run.
MUTATIONS = [
    "mut-file-missing",
    "mut-gate-runid",
    "mut-tamper",
    "mut-empty-case",
    "mut-oldlog-stripped",
]

#: Which variant a mutation is applied to (default: the solid run).
MUTATION_SRC = {"mut-oldlog-stripped": "old-log"}

ATTACK_LEGEND = {
    "solid": "D: every stage claims live=true, no live producer exists anywhere",
    "empty-shell": "A: every gate-evidence file is the empty object {}",
    "wrong-ids": "B: gate evidence names a wrong levelId and a wrong requestId",
    "old-log": "C: gate evidence is a byte copy of a historical artifact",
    "no-live-claim": "control: same run but stages declare live=false",
    "wrong-runid": "control: stage files carry another run's runId",
    "mut-file-missing": "control: a required gate evidence file is deleted",
    "mut-gate-runid": "control: gate evidence carries a wrong runId",
    "mut-tamper": "control: gate evidence changed after the index was written",
    "mut-empty-case": "control: a case stage file is the empty object {}",
    "mut-oldlog-stripped": "C': the same historical artifact with its one carry-over "
                           "field (runId) removed",
}


def run(cmd, cwd=None):
    proc = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def generate(base: Path, variant: str):
    code, out, err = run([PY, "-B", GENERATOR, base / "runs", "--variant", variant])
    if code != 0:
        raise SystemExit(f"generator failed for {variant}: {err}")
    # the runId is deterministic in the generator; read it from its stdout
    for line in out.splitlines():
        if line.startswith("run root"):
            return Path(line.split(None, 2)[2].strip())
    raise SystemExit(f"could not read run root for {variant}")


def apply_mutation(base: Path, name: str) -> Path:
    source_variant = MUTATION_SRC.get(name, "solid")
    srcs = [p for p in (base / "runs" / source_variant).iterdir() if p.is_dir()]
    if len(srcs) != 1:
        raise SystemExit(f"expected exactly one run dir under {source_variant}: {srcs}")
    src = srcs[0]
    dst = base / "runs" / name / src.name
    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(src, dst)

    target = dst / "gate-evidence" / "S01" / "build-and-related-tests.json"
    index_path = dst / "evidence-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))

    def reindex(relative):
        import hashlib
        digest = hashlib.sha256((dst / relative).read_bytes()).hexdigest()
        changed = False
        for gate in index["gates"]:
            for item in gate["evidence"]:
                if item["path"] == relative:
                    item["sha256"] = digest
                    changed = True
        if changed:
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2,
                                             sort_keys=True) + "\n",
                                  encoding="utf-8", newline="\n")

    if name == "mut-file-missing":
        target.unlink()
    elif name == "mut-gate-runid":
        target.write_text(json.dumps({"gate": "S01",
                                      "runId": "00000000000000000000000000000000"},
                                     indent=2) + "\n", encoding="utf-8", newline="\n")
        reindex("gate-evidence/S01/build-and-related-tests.json")
    elif name == "mut-tamper":
        with target.open("ab") as stream:
            stream.write(b"\n")
    elif name == "mut-empty-case":
        stage = dst / "cases" / "T-10005018" / "after.json"
        stage.write_text("{}\n", encoding="utf-8", newline="\n")
        reindex("cases/T-10005018/after.json")
    elif name == "mut-oldlog-stripped":
        # the same historical bytes, minus the single field the verifier reads.
        for path in sorted((dst / "gate-evidence").rglob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and "runId" in doc:
                doc.pop("runId")
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2,
                                           sort_keys=True) + "\n",
                                encoding="utf-8", newline="\n")
            reindex(str(path.relative_to(dst)).replace("\\", "/"))
    else:
        raise SystemExit(f"unknown mutation {name}")
    return dst


def verdict_of(base: Path, label: str, run_root: Path, kind: str):
    out_path = base / "verdicts" / f"{label}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = run([PY, "-B", VERIFIER, run_root, "--output", out_path])
    doc = json.loads(out_path.read_text(encoding="utf-8")) if out_path.is_file() else {}
    codes = sorted({d["code"] for d in doc.get("defects", [])})
    return {
        "label": label,
        "kind": kind,
        "attack": ATTACK_LEGEND.get(label, ""),
        "runRoot": str(run_root),
        "command": f'{PY} -B {VERIFIER} "{run_root}" --output "{out_path}"',
        "exitCode": code,
        "accepted": code == 0,
        "rejected": code == 1,
        "inputUnusable": code == 2,
        "fullRunAccepted": doc.get("fullRunAccepted"),
        "defectCount": doc.get("defectCount"),
        "checkedFiles": doc.get("checkedFiles"),
        "acceptedTemplateCount": doc.get("acceptedTemplateCount"),
        "acceptedParameterCaseCount": doc.get("acceptedParameterCaseCount"),
        "defectCodes": codes,
        "defectDetails": [d["detail"] for d in doc.get("defects", [])][:6],
        "stderr": err.strip()[:400],
        "verdictOutput": str(out_path),
    }


def main(argv=None):
    base = Path(argv[0] if argv else (HERE / "runs-base")).resolve()
    records = []
    for variant in VARIANTS:
        run_root = generate(base, variant)
        records.append(verdict_of(base, variant, run_root, "variant"))
    for mutation in MUTATIONS:
        run_root = apply_mutation(base, mutation)
        records.append(verdict_of(base, mutation, run_root, "mutation"))

    accepted = [r["label"] for r in records if r["accepted"]]
    rejected = [r["label"] for r in records if r["rejected"]]
    summary = {
        "schemaVersion": 1,
        "kind": "ds10-gate-semantics-attack-results",
        "generator": str(GENERATOR),
        "verifier": str(VERIFIER),
        "isolation": ("no game, editor, helper, journal, native run or formal save is "
                      "touched; every run is a text-generated directory tree"),
        "acceptedByVerifier": accepted,
        "rejectedByVerifier": rejected,
        "records": records,
    }
    out = base / "attack-results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"accepted (exit 0): {accepted}")
    print(f"rejected (exit 1): {rejected}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
