"""The LIVE round writer must hash-bind the two artifacts leg B/C and leg D compare against.

WHY THIS EXISTS
===============
``cleanup_ownership_legs`` has two legs whose whole job is to notice that the document a
round names is not the document it measured:

  * leg D -- ``READBACK_HASH_MISMATCH``   (load_fresh_readback, :360)
  * leg B/C -- ``PRE_BASELINE_HASH_MISMATCH`` (load_pre_baseline, :698)

Both are guarded by ``if sha256 is not None``.  The validated producer
(``tools/game-executor/round_materials.py``) always emits the hash, so on the rounds that
writer produces the legs are live.

The LIVE writer -- ``tools/entity-create/run_parameter_matrix.py``'s
``cleanup_ownership_manifest`` -- did not.  It emitted ``freshReadback: {"path": ...}``
with no ``sha256``, and ``preBaseline: {"ids": [...]}``.  The inline form is worse than a
missing hash: ``load_pre_baseline`` returns from its inline branch BEFORE it ever looks
for a ``sha256``, so ``PRE_BASELINE_HASH_MISMATCH`` was not merely dormant for a live
round, it was structurally unreachable.  A real round could therefore have its read-back
or its "what existed before" swapped underneath it and both legs would still have said
nothing.

This test pins the fix by RUNNING the production writer over a synthetic-but-real round
directory tree and then handing its output to the production legs.  It asserts both
directions:

  * untouched artifacts -> neither leg refuses (the fix did not break the happy path)
  * one extra byte appended -> the matching leg names its mismatch code

Measured 2026-10-06: before the fix both tampered cases returned NO refusal.

Run:
    python -m unittest discover -s backend/tests/f011guard -p "test_*.py" -v
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE
while not (REPO / "backend/cleanup_ownership_legs.py").is_file():
    if REPO.parent == REPO:
        raise SystemExit("REPO_ROOT_NOT_FOUND from %s" % HERE)
    REPO = REPO.parent

PRODUCER = REPO / "tools/entity-create/run_parameter_matrix.py"
LEVEL = 1073741839


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LiveProducerHashBinding(unittest.TestCase):
    """A round written by the live driver must be tamper-detectable by both legs."""

    @classmethod
    def setUpClass(cls):
        if str(REPO / "backend") not in sys.path:
            sys.path.insert(0, str(REPO / "backend"))
        cls.producer = _load("_f011_live_producer", PRODUCER)
        cls.legs = _load("_f011_live_legs", REPO / "backend/cleanup_ownership_legs.py")

    def _round(self):
        """A minimal round tree with everything cleanup_ownership_manifest reads."""
        tmp = Path(tempfile.mkdtemp(prefix="f011-liveproducer-"))
        self.addCleanup(lambda: None)

        def write(path, payload):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            return path

        before, readback = tmp / "before", tmp / "readback"
        write(before / "readonly-snapshot.json",
              {"entities": [{"id": 1, "templateId": 100}, {"id": 2, "templateId": 100}]})
        write(before / "exit.json",
              {"startedUtc": "2026-10-06T01:00:00Z", "finishedUtc": "2026-10-06T01:00:10Z"})
        write(readback / "readonly-snapshot.json",
              {"entities": [{"id": 1, "templateId": 100}, {"id": 2, "templateId": 100},
                            {"id": 3, "templateId": 100}]})
        write(readback / "exit.json",
              {"startedUtc": "2026-10-06T01:05:00Z", "finishedUtc": "2026-10-06T01:05:10Z"})

        case = tmp / "case"
        receipt = write(case / "receipt.json", {"ok": True, "backend": {"levelId": LEVEL}})
        write(case / "created-ids.json",
              {"receiptPath": str(receipt),
               "receiptSha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
               "requestId": "r1", "entityId": 3,
               "recordedUtc": "2026-10-06T01:02:00Z", "templateId": 100})

        manifest, reason = self.producer.cleanup_ownership_manifest(
            {"levelId": LEVEL, "caseDir": str(case), "caseId": "c1", "attempt": 1,
             "beforeRun": str(before), "readbackRun": str(readback),
             "beforeIds": [1, 2], "entityIds": [3]})
        # Success is an EMPTY STRING, not None -- the writer's contract is
        # "(manifest | None, reason)" where a refusal carries text. Asserting
        # `is None` here would fail on every well-formed round.
        self.assertFalse(reason, "the writer refused a well-formed round: %r" % (reason,))
        self.assertIsInstance(manifest, dict)
        return manifest

    def _sha(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    # -- the fix --------------------------------------------------------- #

    def test_both_artifacts_carry_a_sha256_that_binds_their_bytes(self):
        manifest = self._round()
        for key in ("preBaseline", "freshReadback"):
            spec = manifest[key]
            with self.subTest(artifact=key):
                self.assertIn("sha256", spec,
                              "%s carries no sha256, so the leg that exists to notice a "
                              "swapped document cannot fire" % key)
                self.assertEqual(spec["sha256"], self._sha(spec["path"]),
                                 "%s records a hash that is not the bytes it names" % key)

    def test_the_pre_baseline_is_a_file_form_not_an_inline_id_list(self):
        """An inline {"ids": [...]} returns before load_pre_baseline reads any sha256."""
        spec = self._round()["preBaseline"]
        self.assertNotIn("ids", spec,
                         "an inline id list makes PRE_BASELINE_HASH_MISMATCH structurally "
                         "unreachable -- the inline branch returns before the hash check")
        self.assertIn("path", spec)

    # -- the legs are actually watching ---------------------------------- #

    def test_untouched_artifacts_are_accepted(self):
        manifest = self._round()
        _readback, refusals = self.legs.load_fresh_readback(
            manifest["freshReadback"]["path"], level_id=LEVEL,
            sha256=manifest["freshReadback"]["sha256"])
        self.assertEqual([r.code for r in refusals], [], "the happy path now refuses")
        _ids, refusals = self.legs.load_pre_baseline(manifest["preBaseline"])
        self.assertEqual([r.code for r in refusals], [], "the happy path now refuses")

    def test_one_extra_byte_in_the_readback_is_caught_by_leg_d(self):
        manifest = self._round()
        target = Path(manifest["freshReadback"]["path"])
        target.write_bytes(target.read_bytes() + b" ")
        _readback, refusals = self.legs.load_fresh_readback(
            manifest["freshReadback"]["path"], level_id=LEVEL,
            sha256=manifest["freshReadback"]["sha256"])
        self.assertIn("READBACK_HASH_MISMATCH", [r.code for r in refusals])

    def test_one_extra_byte_in_the_baseline_is_caught_by_leg_b(self):
        manifest = self._round()
        target = Path(manifest["preBaseline"]["path"])
        target.write_bytes(target.read_bytes() + b" ")
        _ids, refusals = self.legs.load_pre_baseline(manifest["preBaseline"])
        self.assertIn("PRE_BASELINE_HASH_MISMATCH", [r.code for r in refusals])


if __name__ == "__main__":
    unittest.main()
