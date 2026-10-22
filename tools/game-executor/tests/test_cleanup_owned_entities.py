"""Offline tests for the round-ownership wrapper around delete-owned-entity-ids.

No queue, no process launch, no editor and no game access.  Every live path is
replaced by a fixture transport, and the embedded --self-test suite is run again
from here so one command covers both artefacts.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("cleanup_owned_under_test",
                                              HERE.parent / "cleanup_owned_entities.py")
cleanup = importlib.util.module_from_spec(spec)
sys.modules["cleanup_owned_under_test"] = cleanup
spec.loader.exec_module(cleanup)


def dry_reply(ids, **extra):
    body = {"ok": True, "status": "dry-run-mapping-only", "dryRun": True,
            "requested": len(ids), "resolvedCount": len(ids),
            "mapping": [{"id": value, "frontendPath": "/root/%d" % value} for value in ids],
            "invoked": False}
    body.update(extra)
    return body


def result(reply, exit_code=0):
    return cleanup.DispatchResult(exit_code, ["call"], json.dumps(reply), "", reply)


class IdentifierTests(unittest.TestCase):
    def test_uint32_boundaries(self):
        self.assertEqual(cleanup.as_uint(1), 1)
        self.assertEqual(cleanup.as_uint(4294967295), 4294967295)
        for bad in (0, -1, 4294967296, True, False, 1.0, "7", None, [7]):
            with self.subTest(bad=bad):
                self.assertIsNone(cleanup.as_uint(bad))

    def test_argv_shape_matches_the_cli_parser(self):
        argv = cleanup.build_call_argv("py", "Q", "GUID", cleanup.DELETE_OP, [7, 9], 300.0)
        # --queue-dir is a top-level option; anything after "call" is rejected by
        # argparse, so this ordering is the contract, not a preference.
        self.assertLess(argv.index("--queue-dir"), argv.index("call"))
        self.assertEqual(argv[argv.index("--op") + 1], cleanup.DELETE_OP)
        self.assertEqual(argv[argv.index("--run-id") + 1], "GUID")
        self.assertEqual(argv[argv.index("--ids") + 1:argv.index("--ids") + 3], ["7", "9"])
        self.assertTrue(argv[2].endswith("elevated-request.py"))

    def test_queue_dir_containment(self):
        self.assertIsNotNone(cleanup.check_queue_dir(cleanup.ROOT / ".runtime"))
        self.assertIsNotNone(cleanup.check_queue_dir(cleanup.ROOT / ".runtime/editor-bridge"))

    def test_the_queue_path_must_be_a_directory(self):
        """A plain FILE under the bridge tree is lexically inside it, and used to
        pass: the refusal only happened later, as an uncaught traceback inside
        elevated-request.py's send()."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "editor-bridge"
            (root / "queue").mkdir(parents=True)
            (root / "plain-file.txt").write_text("not a queue", encoding="utf-8")
            self.assertIsNone(cleanup.queue_dir_problem(root / "queue", root))
            self.assertEqual(cleanup.queue_dir_problem(root / "plain-file.txt", root).code,
                             "QUEUE_DIR_NOT_A_DIRECTORY")
            self.assertEqual(cleanup.queue_dir_problem(root / "gone", root).code,
                             "QUEUE_DIR_MISSING")
            self.assertIsNotNone(cleanup.queue_dir_problem(root, root))


class BatchTests(unittest.TestCase):
    def test_ceiling_and_duplicates(self):
        batches, refusals = cleanup.build_batches(list(range(1, 130)))
        self.assertEqual([len(batch) for batch in batches], [64, 64, 1])
        self.assertEqual(refusals, [])
        batches, refusals = cleanup.build_batches([5, 5])
        self.assertEqual(batches, [])
        self.assertEqual([item.code for item in refusals], ["ID_DUPLICATE"])
        batches, refusals = cleanup.build_batches([])
        self.assertEqual([item.code for item in refusals], ["NO_OWNED_TARGETS"])


class DryRunTests(unittest.TestCase):
    def test_unique_mapping_required(self):
        mapping, refusal = cleanup.classify_dry_run(result(dry_reply([1, 2])), [1, 2])
        self.assertIsNone(refusal)
        self.assertEqual(mapping, {1: "/root/1", 2: "/root/2"})

    def test_duplicate_id_in_mapping_is_ambiguous(self):
        reply = dry_reply([1, 2], mapping=[{"id": 1, "frontendPath": "/a"},
                                           {"id": 1, "frontendPath": "/b"}])
        _, refusal = cleanup.classify_dry_run(result(reply), [1, 2])
        self.assertEqual(refusal.code, "DRY_RUN_AMBIGUOUS_RESOLUTION")

    def test_a_mapping_that_claims_to_have_invoked_is_refused(self):
        _, refusal = cleanup.classify_dry_run(result(dry_reply([1], invoked=True)), [1])
        self.assertEqual(refusal.code, "DRY_RUN_INVOKED_UNEXPECTED")

    def test_zero_match_refusal_is_not_treated_as_ambiguity(self):
        reply = {"ok": False, "status": "refused-unresolved-ids", "invoked": False,
                 "unresolved": [{"id": 4, "matches": 0, "frontendPath": "<none>"}]}
        _, refusal = cleanup.classify_dry_run(result(reply, 1), [4])
        self.assertEqual(refusal.code, "DRY_RUN_REFUSED_UNRESOLVED")


class ExecuteTests(unittest.TestCase):
    def test_partial_rows_and_untouched_tail(self):
        reply = {"ok": True, "status": "delete-requested-readback-pending", "requested": 4,
                 "invokedCount": 1, "retryAllowed": False,
                 "results": [{"id": 1, "frontendPath": "/1", "invoked": True, "nativeResult": True},
                             {"id": 2, "frontendPath": "/2", "invoked": False,
                              "error": "OWNED_DELETE_TARGET_CHANGED_DURING_PREPARATION"}]}
        ledger, refusal, unknown, warnings = cleanup.classify_execute(result(reply), [1, 2, 3, 4])
        self.assertIsNone(refusal)
        self.assertIsNone(unknown)
        self.assertEqual(ledger[1], "dispatched")
        self.assertEqual(ledger[2], "not-dispatched:target-changed")
        self.assertEqual(ledger[3], "not-attempted")
        self.assertEqual(ledger[4], "not-attempted")
        self.assertEqual(warnings, [])

    def test_a_moved_node_is_cross_checked_against_the_dry_run(self):
        """The delete row's frontendPath used to be dropped on the floor."""
        reply = {"ok": True, "status": "delete-requested-readback-pending", "requested": 1,
                 "invokedCount": 1, "retryAllowed": False,
                 "results": [{"id": 1, "frontendPath": "/moved/1", "invoked": True,
                              "nativeResult": True}]}
        detail = {}
        ledger, _, _, warnings = cleanup.classify_execute(result(reply), [1], {1: "/1"}, detail)
        self.assertEqual(ledger[1], "dispatched:path-mismatch")
        self.assertTrue(any("frontendPath" in line for line in warnings))
        self.assertEqual(detail["rows"][0]["frontendPath"], "/moved/1")
        self.assertEqual(detail["pathMismatches"][0]["expected"], "/1")
        matched = {"ok": True, "status": "delete-requested-readback-pending", "requested": 1,
                   "invokedCount": 1, "retryAllowed": False,
                   "results": [{"id": 1, "frontendPath": "/1", "invoked": True,
                                "nativeResult": True}]}
        ledger, _, _, warnings = cleanup.classify_execute(result(matched), [1], {1: "/1"})
        self.assertEqual(ledger[1], "dispatched")
        self.assertEqual(warnings, [])

    def test_a_foreign_id_in_the_results_is_unknown(self):
        reply = {"ok": True, "status": "delete-requested-readback-pending", "requested": 1,
                 "invokedCount": 1, "results": [{"id": 99, "invoked": True, "nativeResult": True}]}
        ledger, _, unknown, _ = cleanup.classify_execute(result(reply), [1])
        self.assertEqual(ledger, {})
        self.assertIn("was not requested", unknown)

    def test_a_clean_refusal_invokes_nothing(self):
        reply = {"ok": False, "status": "refused-unresolved-ids", "invoked": False,
                 "unresolved": [{"id": 1, "matches": 2}]}
        ledger, refusal, unknown, _ = cleanup.classify_execute(result(reply, 1), [1, 2])
        self.assertIsNone(unknown)
        self.assertEqual(refusal.code, "EXECUTE_REFUSED_UNRESOLVED")
        self.assertEqual(set(ledger.values()), {"not-dispatched:list-refused"})

    def test_an_unreadable_reply_is_unknown(self):
        _, _, unknown, _ = cleanup.classify_execute(
            cleanup.DispatchResult(1, [], "no json here", "", None), [1])
        self.assertIn("no readable JSON reply", unknown)


class ReadbackEvidenceTests(unittest.TestCase):
    """Supplied --readback evidence: shape, trust, and the ownership intersection."""

    def test_an_unrecognised_document_is_not_an_empty_set(self):
        for document in ({"entities": [{"id": 1}]},                       # a baseline
                         {"tool": "cleanup_owned_entities", "code": "X"},  # an envelope
                         None, "text", 7):
            with self.subTest(document=document):
                parsed = cleanup.parse_readback(document)
                self.assertEqual(parsed, {})
                self.assertFalse(parsed.trusted)
                self.assertIsNotNone(parsed.problem)

    def test_a_recognised_but_empty_document_stays_empty_and_flagged(self):
        # This tool's own report is the self-approval trap: "residual": [] reads
        # as "nothing remains" if an empty parse is allowed to mean CLEAN.
        parsed = cleanup.parse_readback({"residual": [], "ownedIds": [1]})
        self.assertEqual(parsed.shape, "residual")
        self.assertEqual(parsed, {})
        self.assertTrue(parsed.trusted)

    def test_one_bad_entry_untrusts_the_document(self):
        parsed = cleanup.parse_readback({"stillExisting": [1, "abc"]})
        self.assertFalse(parsed.trusted)
        self.assertEqual(parsed.problem.code, "READBACK_ENTRY_UNPARSEABLE")

    def test_cli_readback_guards(self):
        with tempfile.TemporaryDirectory(dir=cleanup.ROOT / ".runtime") as tmp:
            tmp = Path(tmp)
            good = tmp / "good.json"
            good.write_text(json.dumps({"stillExisting": [7]}), encoding="utf-8")
            evidence, problem = cleanup.load_readback_argument(good)
            self.assertIsNone(problem)
            self.assertEqual(set(evidence), {7})
            self.assertEqual(evidence.shape, "stillExisting")

            empty = tmp / "empty.json"
            empty.write_text(json.dumps([]), encoding="utf-8")
            _, problem = cleanup.load_readback_argument(empty)
            self.assertEqual(problem.code, "READBACK_EMPTY_UNVERIFIABLE")

            baseline = tmp / "baseline.json"
            baseline.write_text(json.dumps({"entities": [{"id": 7}]}), encoding="utf-8")
            _, problem = cleanup.load_readback_argument(baseline)
            self.assertEqual(problem.code, "READBACK_SHAPE_UNKNOWN")

            _, problem = cleanup.load_readback_argument(cleanup.ROOT / "GOAL.md")
            self.assertEqual(problem.code, "READBACK_OUTSIDE_RUNTIME")

    def test_a_supplied_foreign_id_is_dropped_and_distrusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            receipts = tmp / "r.jsonl"
            receipts.write_text("\n".join(json.dumps(
                {"action": {"levelId": 7, "entityId": value}, "templateId": 500})
                for value in (1, 2)), encoding="utf-8")
            baseline = tmp / "b.json"
            baseline.write_text(json.dumps({"entities": [
                {"id": 1, "templateId": 500}, {"id": 2, "templateId": 500}]}), encoding="utf-8")
            pre = tmp / "p.json"
            pre.write_text(json.dumps({"entities": []}), encoding="utf-8")

            def dry(op, ids):
                return cleanup.DispatchResult(0, ["call"], "", "", dry_reply(ids))

            def delete(op, ids):
                return cleanup.DispatchResult(0, ["call"], "", "", {
                    "ok": True, "status": "delete-requested-readback-pending", "retryAllowed": False,
                    "invokedCount": len(ids), "results": [{"id": v, "invoked": True,
                                                           "nativeResult": True,
                                                           "frontendPath": "/root/%d" % v}
                                                          for v in ids]})

            run = cleanup.CleanupRun(receipts=[receipts], baseline=baseline, pre_baseline=pre,
                                     level_id=7, mode="execute",
                                     dispatch=lambda op, ids: dry(op, ids) if op == cleanup.DRY_OP
                                     else delete(op, ids),
                                     readback={1: "s", 424242: "s"})
            report = run.execute()
            self.assertEqual(report["residual"], [1])
            self.assertIsNone(report["newCleanupOperation"])
            self.assertEqual(report["exitCode"], cleanup.EXIT_UNKNOWN)
            self.assertEqual(report["readback"]["foreignIds"], [424242])
            self.assertFalse(report["readback"]["trusted"])
            self.assertIn("READBACK_NOT_OWNED",
                          [item["code"] for item in report["refusals"]])


class ReportPreflightTests(unittest.TestCase):
    """--report is decided before the first dispatch, and a failed write is not 3."""

    def test_path_is_checked_for_collision_and_writability(self):
        with tempfile.TemporaryDirectory(dir=cleanup.ROOT / ".runtime") as tmp:
            tmp = Path(tmp)
            target, problem = cleanup.resolve_report_path(tmp / "new.json")
            self.assertIsNone(problem)
            self.assertEqual(target, tmp / "new.json")

            existing = tmp / "there.json"
            existing.write_text("{}", encoding="utf-8")
            _, problem = cleanup.resolve_report_path(existing)
            self.assertEqual(problem.code, "REPORT_ALREADY_EXISTS")

            blocker = tmp / "a-file.json"
            blocker.write_text("{}", encoding="utf-8")
            _, problem = cleanup.resolve_report_path(blocker / "report.json")
            self.assertEqual(problem.code, "REPORT_UNWRITABLE")

            _, problem = cleanup.resolve_report_path(cleanup.ROOT / "GOAL.md")
            self.assertEqual(problem.code, "REPORT_OUTSIDE_RUNTIME")

    def test_a_failed_write_prints_the_report_and_uses_its_own_code(self):
        with tempfile.TemporaryDirectory(dir=cleanup.ROOT / ".runtime") as tmp:
            target = Path(tmp) / "unwritten.json"
            report = {"exitCode": cleanup.EXIT_PARTIAL, "ledger": {1: "dispatched"}}
            real_write = cleanup.exclusive_write_json
            cleanup.exclusive_write_json = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    code = cleanup.persist_report(report, target)
            finally:
                cleanup.exclusive_write_json = real_write
            self.assertEqual(code, cleanup.EXIT_EVIDENCE_UNWRITTEN)
            self.assertNotEqual(code, cleanup.EXIT_USAGE)
            printed = [line for line in buffer.getvalue().splitlines() if line.strip()]
            self.assertEqual(json.loads("\n".join(printed[:-1]))["ledger"], {"1": "dispatched"})
            self.assertIn("REPORT_WRITE_FAILED", printed[-1])
            self.assertFalse(target.exists())

    def test_a_successful_write_returns_no_code(self):
        with tempfile.TemporaryDirectory(dir=cleanup.ROOT / ".runtime") as tmp:
            target = Path(tmp) / "written.json"
            self.assertIsNone(cleanup.persist_report({"exitCode": cleanup.EXIT_CLEAN}, target))
            self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["reportPersisted"])


class OwnershipTests(unittest.TestCase):
    LEVEL = 1073741839

    def test_each_leg_is_enforced(self):
        claims = {
            1: cleanup.Claim(1, 500, self.LEVEL, ["a"]),          # fully owned
            2: cleanup.Claim(2, 500, self.LEVEL, ["b"]),          # template differs
            3: cleanup.Claim(3, 500, self.LEVEL, ["c"]),          # absent from baseline
            4: cleanup.Claim(4, 500, self.LEVEL, ["d"]),          # existed before
            5: cleanup.Claim(5, None, self.LEVEL, ["e"]),         # receipt has no template
            6: cleanup.Claim(6, 500, self.LEVEL + 1, ["f"]),      # other level
        }
        current = {1: 500, 2: 501, 4: 500, 5: 500, 6: 500}
        previous = {4}
        sources: dict = {}
        owned, refusals = cleanup.prove_ownership(claims, current, previous, self.LEVEL,
                                                  template_sources=sources)
        # 5 IS owned, on the template the current BASELINE observed for it.  Its receipt
        # names the id and states no template, which is the shape the engine's own create
        # reply actually has (MEASURED 2026-10-08: create-receipt.json is {reply, backend}
        # and carries only the id).  The proof is unchanged in strength: the id must still
        # come from a receipt, it must still be absent from the pre-create baseline, and it
        # must still be present now with a template the native snapshot states -- and the
        # report names which leg supplied that template.
        self.assertEqual(owned, [1, 5])
        self.assertEqual(sources, {1: "receipt", 5: "baseline-observation"})
        self.assertEqual(sorted(item.code for item in refusals),
                         ["ID_NOT_IN_BASELINE", "LEVEL_MISMATCH", "NOT_NEWLY_ADDED",
                          "TEMPLATE_ID_MISMATCH"])

    def test_a_missing_pre_baseline_owns_nothing(self):
        claims = {1: cleanup.Claim(1, 500, self.LEVEL, ["a"])}
        owned, refusals = cleanup.prove_ownership(claims, {1: 500}, None, self.LEVEL)
        self.assertEqual(owned, [])
        self.assertEqual([item.code for item in refusals], ["NO_UNIQUE_ADDITION_PROOF"])

    def test_ambiguous_claim_is_refused_by_name(self):
        claim = cleanup.Claim(7, 500, self.LEVEL, ["a", "b"], ambiguous=True)
        owned, refusals = cleanup.prove_ownership({7: claim}, {7: 500}, set(), self.LEVEL)
        self.assertEqual(owned, [])
        self.assertEqual([item.code for item in refusals], ["RECEIPT_AMBIGUOUS_CLAIM"])

    def test_a_pre_existing_id_is_named_as_such(self):
        """The order of the checks is diagnosis, not verdict: an id that existed
        before this round used to be reported as TEMPLATE_ID_MISMATCH whenever its
        baseline template differed, which sends the reader hunting a template bug
        that does not exist."""
        claims = {1: cleanup.Claim(1, 500, self.LEVEL, ["a"])}
        _, refusals = cleanup.prove_ownership(claims, {1: 501}, {1}, self.LEVEL)
        self.assertEqual([item.code for item in refusals], ["NOT_NEWLY_ADDED"])
        # ...while a genuinely new id with the wrong template still says so.
        _, refusals = cleanup.prove_ownership(claims, {1: 501}, set(), self.LEVEL)
        self.assertEqual([item.code for item in refusals], ["TEMPLATE_ID_MISMATCH"])


class SelfTestTests(unittest.TestCase):
    def test_embedded_fixture_suite(self):
        self.assertEqual(cleanup.self_test(), 0)


class GuardTests(unittest.TestCase):
    def test_execute_without_a_transport_cannot_run(self):
        run = cleanup.CleanupRun(receipts=[], baseline=None, pre_baseline=None,
                                 level_id=1073741839, mode="execute", dispatch=None)
        report = run.execute()
        self.assertEqual(report["exitCode"], cleanup.EXIT_USAGE)
        self.assertEqual([item["code"] for item in report["refusals"]], ["QUEUE_DIR_REQUIRED"])

    def test_readback_document_shapes(self):
        self.assertEqual(set(cleanup.parse_readback([1, 2])), {1, 2})
        self.assertEqual(set(cleanup.parse_readback({"stillExisting": [3]})), {3})
        self.assertEqual(set(cleanup.parse_readback({"7": "x"})), {7})
        self.assertEqual(cleanup.parse_readback("nonsense"), {})

    def test_report_must_be_a_new_file_under_runtime(self):
        _, refusal = cleanup.resolve_report_path(cleanup.ROOT / "outside.json")
        self.assertEqual(refusal.code, "REPORT_OUTSIDE_RUNTIME")
        _, refusal = cleanup.resolve_report_path(cleanup.ROOT / "GOAL.md")
        self.assertEqual(refusal.code, "REPORT_OUTSIDE_RUNTIME")


if __name__ == "__main__":
    unittest.main(verbosity=2)
