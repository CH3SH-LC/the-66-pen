"""Two-sided control for F-010: the forged-run corpus, kept in the tree.

WHY THIS EXISTS
===============
The forgery corpus is the only thing in this project that shows the FROZEN gate can be
satisfied by a run containing **zero live operations**.  Doc 14 line 111 requires it to be
preserved: "单层冻结门仍有空壳假阳性负控必须保留".  Until this file, the corpus and its
generator lived entirely under ``.runtime/verification/ds-parallel-resume-20261002/ds10/
forgery/`` -- and ``/.runtime/`` is in ``.gitignore``.  A ``.runtime`` clean would have
deleted the negative control that the project's own rule says must survive.

So the generator is VENDORED into ``tools/game-executor/tests/forgery/`` (two path-depth
constants adjusted, and the driver's interpreter changed from
``.runtime/mcp-venv/Scripts/python.exe`` to ``sys.executable`` so the control does not
depend on the tree it protects).  This test regenerates a forgery from that vendored
generator and checks BOTH sides:

  FROZEN GATE  refuses it   -- since 2026-10-06.  This side used to assert the OPPOSITE:
                               the gate ACCEPTED the forgery, deliberately, as the recorded
                               false positive of doc 14:111.  The gate was then hardened --
                               the `runId` binding in `hash_matches` became fail-closed (an
                               indexed JSON evidence file carrying no `runId` is now a
                               defect rather than a skipped comparison) -- which turned that
                               assertion red.  That is the response this very note
                               prescribed: UPDATE the control to record the new behaviour,
                               never delete it.  What it records now is that a
                               no-producer forgery is refused by the gate itself, so the
                               two-layer refusal (gate + provenance) is what stands.
  F-010 LAYER  refuses it   -- PROVENANCE_ABSENT: the run carries no provenance anchor, so
                               no outside source is bound to any gate or case.

What the second half does and does not cover: it establishes that a fabricated tree with
no anchor is refused.  It does NOT re-measure the full-corpus rejection of all four
gate-accepted variants (solid, empty-shell, wrong-ids, mut-oldlog-stripped) -- that was
measured separately, on the original corpus at full corpus, in round 115 (4/4 refused,
78-86 s per run), and is recorded at
``.runtime/verification/ds-live-goal-20261002/round115/provenance-over-forgeries.json``.
This test is the fast, always-runnable half.

Run:
    python -m unittest discover -s tools/game-executor/tests -p "test_f010_forgery_control.py"
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
GENERATOR = HERE / "forgery" / "make_forged_run.py"
GATE = HERE.parent / "verify_entity_create_run.py"
LAYER = HERE.parent / "verify_run_provenance.py"


def _run(argv, **kwargs):
    return subprocess.run([sys.executable, "-B", *argv], capture_output=True, text=True, **kwargs)


class ForgeryControlTests(unittest.TestCase):
    """A forged run: refused by the hardened gate AND by the added F-010 layer."""

    def test_a_generated_forgery_is_refused_by_both_the_gate_and_the_layer(self):
        self.assertTrue(GENERATOR.is_file(),
                        "the vendored forgery generator is missing from the tree -- the "
                        "negative control doc 14:111 requires has been deleted")
        tmp = Path(tempfile.mkdtemp(prefix="f010-forgery-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        # 1. generate a run with ZERO live operations
        gen = _run([str(GENERATOR), str(tmp), "--variant", "empty-shell"])
        self.assertEqual(gen.returncode, 0, gen.stdout + gen.stderr)
        variant = tmp / "empty-shell"
        run_roots = [p for p in variant.iterdir() if p.is_dir()]
        self.assertEqual(len(run_roots), 1, "the generator did not produce exactly one run root")
        run_root = run_roots[0]

        # 2. the FROZEN GATE refuses it -- the hardened behaviour (since 2026-10-06).
        #    This side previously asserted the opposite (acceptance, as the recorded false
        #    positive).  See the module docstring: the change was made deliberately, by
        #    updating THIS control, and a green here now means the gate held.
        gate_out = tmp / "gate-verdict.json"
        gate = _run([str(GATE), str(run_root), "--output", str(gate_out)])
        self.assertEqual(
            gate.returncode, 1,
            "The frozen gate ACCEPTED a no-producer forgery again. Either the fail-closed "
            "runId binding in hash_matches was reverted, or a new acceptance hole was "
            "opened. That is a REGRESSION, not a control update. "
            "stderr=%r" % (gate.stderr or "")[-400:])
        verdict = json.loads(gate_out.read_text(encoding="utf-8"))
        self.assertFalse(verdict.get("fullRunAccepted"))
        gate_codes = {d.get("code") for d in verdict.get("defects") or []}
        self.assertTrue(
            any("RUNID_MISMATCH" in (c or "") for c in gate_codes),
            "the gate's refusal must name the missing runId binding, got %r"
            % sorted(c for c in gate_codes if c)[:10])

        # 3. the added F-010 layer refuses the same tree
        empty_corpus = tmp / "empty-corpus"
        empty_corpus.mkdir()
        layer = _run([str(LAYER), str(run_root), "--corpus-roots", str(empty_corpus), "--quiet"])
        self.assertEqual(layer.returncode, 1,
                         "the layer accepted a run with no provenance anchor: %r"
                         % (layer.stdout or "")[:400])
        layer_verdict = json.loads(layer.stdout)
        codes = {d["code"] for d in layer_verdict["provenanceDefects"]}
        self.assertIn("PROVENANCE_ABSENT", codes,
                      "the refusal must name the missing outside source, got %r" % sorted(codes))


if __name__ == "__main__":
    unittest.main()
