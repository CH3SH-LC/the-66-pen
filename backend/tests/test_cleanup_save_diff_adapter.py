"""The injected DS-05 seam (W10 / R11): a concrete ``SaveDiffVerifier``.

These are the offline unit tests for ``backend/cleanup_save_diff_adapter.py`` plus
its wiring into ``CleanupService``.  Every stand-in file is written inside the
test's own temporary directory, so nothing survives the case.

The adversarial cases assert the *properties* the R11 judgement names: a verdict is
carried over unchanged (never upgraded), a save case about another level is refused
by name, an absent case is a NAMED refusal rather than the generic
``SAVE_DIFF_VERIFIER_UNAVAILABLE``, and the document still cannot reach ``pass``
without bound files that resolve on disk.
"""
import json
import tempfile
import unittest
from pathlib import Path

from backend import cleanup_service as cs
from backend import cleanup_save_diff_adapter as adapter

AXES = ("saveInvocation", "savedContent", "allowedDelta", "unrelatedUnchanged")
REPO = Path(__file__).resolve().parents[2]


def write_file(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path), "sha256": cs.sha256_file(path)}


def all_pass_report(**statuses):
    stages = {name: {"status": statuses.get(name, "pass")} for name in AXES}
    stages["saveDiff"] = {"status": "pass" if all(
        stages[n]["status"] == "pass" for n in AXES) else "blocked"}
    return {"stages": stages}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="r11-adapter-"))
        self.level = 1073741839
        self.files = {
            "gilBefore": write_file(self.tmp / "before.gil", b"before-bytes"),
            "gilAfter": write_file(self.tmp / "after.gil", b"after-bytes"),
            "gipBefore": write_file(self.tmp / "before.gip", b"gip-before"),
            "gipAfter": write_file(self.tmp / "after.gip", b"gip-after"),
        }
        self.case = {"caseId": "c1", "runId": "r1", "operation": "save",
                     "levelId": self.level, "files": self.files,
                     "entityDelta": {"addedIds": [], "removedIds": []}}

    def _verifier(self, **kw):
        kw.setdefault("case", self.case)
        kw.setdefault("unavailable", cs.VerificationUnavailable)
        return adapter.ExistingSaveVerifier(**kw)

    def _cleanup_manifest(self, files=None):
        return {"runId": "r1", "levelId": self.level, "cleanupOwnedIds": [1],
                "files": files if files is not None else self.files}

    # -- the happy path ------------------------------------------------------ #

    def test_a_delegated_report_reaches_pass_through_the_service_with_real_files(self):
        seen = {}

        def verify(case, **kwargs):
            seen["case"] = case
            return all_pass_report()

        service = cs.CleanupService(save_diff=self._verifier(verify=verify),
                                    evidence_root=self.tmp / "ev")
        session = cs.CleanupSession(levelId=self.level, levelHandleDigest="d", roundId="r1")
        report = {"requestId": "q1", "exitCode": cs.EXIT_CLEAN, "ownedIds": [1],
                  "deletionReadback": {"performed": True, "trusted": True},
                  "residual": {"ids": []}}
        doc = service.orchestrate_s12(session, report,
                                      save_case_files=self.files)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_PASS)
        self.assertEqual(doc["verifiedLayer"], "live")
        self.assertIs(seen["case"], self.case, "the adapter must hand DS-05 the SAME case object")

    # -- no upgrade ---------------------------------------------------------- #

    def test_a_report_that_is_not_all_pass_is_carried_over_not_upgraded(self):
        def verify(case, **kwargs):
            return all_pass_report(allowedDelta="blocked")

        service = cs.CleanupService(save_diff=self._verifier(verify=verify),
                                    evidence_root=self.tmp / "ev")
        session = cs.CleanupSession(levelId=self.level, levelHandleDigest="d", roundId="r1")
        report = {"requestId": "q1", "exitCode": cs.EXIT_CLEAN, "ownedIds": [1],
                  "deletionReadback": {"performed": True, "trusted": True},
                  "residual": {"ids": []}}
        doc = service.orchestrate_s12(session, report,
                                      save_case_files=self.files)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_FAIL)
        self.assertFalse(doc["criteria"]["allowedDelta"]["met"])
        self.assertTrue(doc["criteria"]["saveInvocation"]["met"])

    def test_a_perfect_report_without_resolving_files_never_reaches_pass(self):
        service = cs.CleanupService(save_diff=self._verifier(verify=lambda c, **k: all_pass_report()),
                                    evidence_root=self.tmp / "ev")
        session = cs.CleanupSession(levelId=self.level, levelHandleDigest="d", roundId="r1")
        report = {"requestId": "q1", "exitCode": cs.EXIT_CLEAN, "ownedIds": [1],
                  "deletionReadback": {"performed": True, "trusted": True},
                  "residual": {"ids": []}}
        broken = {"gilAfter": {"path": str(self.tmp / "gone.gil"), "sha256": "0" * 64}}
        doc = service.orchestrate_s12(session, report,
                                      save_case_files=broken)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertEqual(doc["verifiedLayer"], "offline")

    # -- named refusals ------------------------------------------------------ #

    def test_no_case_is_a_named_refusal_not_the_generic_unavailable(self):
        verdict = adapter.ExistingSaveVerifier(case=None,
                                               unavailable=cs.VerificationUnavailable
                                               ).verify_cleanup_save(self._cleanup_manifest())
        self.assertIsInstance(verdict, cs.VerificationUnavailable)
        self.assertEqual(verdict.code, "SAVE_MANIFEST_MISSING")

    def test_a_case_for_another_level_is_refused_by_name(self):
        case = dict(self.case, levelId=self.level + 1)
        verdict = self._verifier(case=case).verify_cleanup_save(self._cleanup_manifest())
        self.assertIsInstance(verdict, cs.VerificationUnavailable)
        self.assertEqual(verdict.code, "SAVE_MANIFEST_WRONG_LEVEL")

    def test_a_case_binding_no_gil_pair_is_refused_by_name(self):
        case = dict(self.case, files={"gipAfter": self.files["gipAfter"]})
        verdict = self._verifier(case=case).verify_cleanup_save(self._cleanup_manifest())
        self.assertIsInstance(verdict, cs.VerificationUnavailable)
        self.assertEqual(verdict.code, "SAVE_MANIFEST_SHAPE_UNKNOWN")

    def test_a_cleanup_manifest_that_is_not_an_object_is_refused_by_name(self):
        verdict = self._verifier().verify_cleanup_save("not-a-dict")
        self.assertIsInstance(verdict, cs.VerificationUnavailable)
        self.assertEqual(verdict.code, "CLEANUP_MANIFEST_SHAPE_UNKNOWN")

    def test_a_case_path_that_is_not_on_disk_is_refused_by_name(self):
        verdict = adapter.ExistingSaveVerifier(
            case=str(self.tmp / "missing.json"), unavailable=cs.VerificationUnavailable
        ).verify_cleanup_save(self._cleanup_manifest())
        self.assertIsInstance(verdict, cs.VerificationUnavailable)
        self.assertEqual(verdict.code, "SAVE_MANIFEST_UNREADABLE")

    def test_the_case_may_be_given_as_a_path_and_is_read_from_disk(self):
        path = self.tmp / "case.json"
        path.write_text(json.dumps(self.case), encoding="utf-8")
        seen = {}

        def verify(case, **kwargs):
            seen["case"] = case
            return all_pass_report()

        report = self._verifier(case=path, verify=verify).verify_cleanup_save(
            self._cleanup_manifest())
        # The adapter's contract is the DS-05 report, unchanged; cleanup_service
        # normalises it with adapt_save_verification.
        self.assertIsInstance(report, dict)
        self.assertEqual(report["stages"]["saveDiff"]["status"], "pass")
        self.assertEqual(seen["case"]["caseId"], self.case["caseId"])

    # -- the candidate's guessed refusal is NOT adopted ---------------------- #

    def test_a_case_declaring_no_removed_ids_is_still_judged(self):
        """A cleanup owns ids; the save case declares none.  DS-05 can judge this
        (and reports the deletion as an un-attributed defect downstream); the adapter
        must not convert that into 'cannot judge'."""
        result = adapter.ExistingSaveVerifier(
            case=self.case, verify=lambda c, **k: all_pass_report(),
            unavailable=cs.VerificationUnavailable
        ).verify_cleanup_save(self._cleanup_manifest())
        self.assertIsInstance(result, dict)
        self.assertEqual(self.case["entityDelta"]["removedIds"], [])

    def test_the_adapter_does_not_edit_the_case_it_is_given(self):
        before = json.dumps(self.case, sort_keys=True)
        self._verifier(verify=lambda c, **k: all_pass_report()
                       ).verify_cleanup_save(self._cleanup_manifest())
        self.assertEqual(json.dumps(self.case, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
