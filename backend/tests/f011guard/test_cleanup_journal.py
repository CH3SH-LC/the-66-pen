"""W05 -- the cleanup dispatch journal: replay, conflict, interrupted-outcome
reconciliation, and the concurrent-claim mutex.

WHAT THIS COVERS, AND WHY IT IS HERE
====================================
``mw_scene_cleanup_owned`` deletes through the elevated queue, which carries no
requestId, so a repeated call is byte-for-byte indistinguishable from a second delete of
the same ids.  ``backend/cleanup_dispatch_journal.py`` is the claim/outcome journal that
makes one request at most one dispatch, and ``backend/entity_server.py`` consults it
before anything is sent.  The four protections it must give, each with a probe and a
mutation that turns that probe red:

    (1) same request + same command       -> the recorded outcome is replayed, nothing sent
    (2) same request + different command  -> refused, nothing sent
    (3) claim recorded, outcome unknown   -> refused and reconcilable, nothing sent
    (4) two racing calls, same request    -> exactly one dispatch

``harness`` is reused so the route half runs with ``subprocess.run`` replaced by a
recording stub and the dispatch sentinel as the only possible transport.  Nothing here
touches a queue, a helper, a bridge, the game or the editor; the protocol half is pure
filesystem work under a per-test temporary root, and the concurrency control uses real
child processes that do nothing but race for one directory.

Run:
    python -m unittest discover -s backend/tests/f011guard -p "test_*.py" -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import harness as H                                                     # noqa: E402
import probes as P                                                      # noqa: E402


LEGS = H.load_legs()
SERVER = H.load_server(legs=LEGS)
JOURNAL_PATH = H.REPO / "backend/cleanup_dispatch_journal.py"

BINDING = {"ids": [7, 8, 9], "dryRun": False, "bridgeRunId": "bridge-run-1"}
OTHER_BINDING = {"ids": [7, 8, 9], "dryRun": True, "bridgeRunId": "bridge-run-1"}


def _raise(error):
    raise error


def _runner_source():
    """The child program the concurrency control runs: it only races for one directory."""
    return textwrap.dedent('''
        import json, os, sys, time
        backend, root, round_id, request_id, binding_json, barrier, index = sys.argv[1:8]
        sys.path.insert(0, backend)
        import cleanup_dispatch_journal as J
        binding = json.loads(binding_json)
        open(os.path.join(barrier, "ready-" + index), "w").close()
        deadline = time.time() + 30
        while not os.path.exists(os.path.join(barrier, "go")):
            if time.time() > deadline:
                print(json.dumps({"index": index, "state": "TIMEOUT"}))
                sys.exit(2)
            time.sleep(0.005)
        state = None
        try:
            out = J.consult(root, round_id, request_id, binding)
            state = out["state"]
            if state == "claimed":
                time.sleep(0.2)                     # widen the window the claim must close
                J.record_outcome(out["directory"], out["requestId"], round_id, binding,
                                 {"ok": True, "dryRun": binding["dryRun"]})
        except Exception as error:                  # noqa: BLE001 - reported verbatim
            state = "REFUSED:%s:%s" % (type(error).__name__, getattr(error, "code", ""))
        print(json.dumps({"index": index, "state": state}))
        ''')


class _TempRootCase(unittest.TestCase):
    """Every case gets its own disposable journal root, so no case can pre-empt another."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="w05-journal-"))
        self.addCleanup(shutil.rmtree, str(self.root), True)


# --------------------------------------------------------------------------- #
# 1. the protocol module, directly
# --------------------------------------------------------------------------- #

class JournalProtocol(_TempRootCase):

    def consult(self, request_id, binding=None, round_id="round-1"):
        return SERVER._CLEANUP_DISPATCH_JOURNAL.consult(
            self.root, round_id, request_id, binding or BINDING)

    def test_same_request_same_command_replays(self):
        """(1) the second consult returns the recorded outcome and dispatches nothing."""
        first = self.consult("req-1")
        self.assertEqual(first["state"], "claimed")
        self.assertTrue(first["claimedAtUtc"])
        SERVER._CLEANUP_DISPATCH_JOURNAL.record_outcome(
            first["directory"], first["requestId"], "round-1", BINDING, {"ok": True})
        second = self.consult("req-1")
        self.assertEqual(second["state"], "replayed")
        self.assertEqual(second["receipt"], {"ok": True})
        self.assertEqual(second["record"]["fingerprint"],
                         SERVER._CLEANUP_DISPATCH_JOURNAL.fingerprint(BINDING))
        self.assertEqual(second["directory"], first["directory"])

    def test_same_request_different_command_refused(self):
        """(2) one request is one command; a different command is a conflict."""
        first = self.consult("req-2")
        SERVER._CLEANUP_DISPATCH_JOURNAL.record_outcome(
            first["directory"], first["requestId"], "round-1", BINDING, {"ok": True})
        with self.assertRaises(SERVER._CLEANUP_DISPATCH_JOURNAL.DispatchJournalError) as caught:
            self.consult("req-2", OTHER_BINDING)
        self.assertEqual(caught.exception.code, "CLEANUP_REQUEST_ID_CONFLICT")
        self.assertEqual(caught.exception.extra["recordedCommand"], BINDING)
        self.assertEqual(caught.exception.extra["suppliedCommand"], OTHER_BINDING)

    def test_claim_without_outcome_refused_and_reconcilable(self):
        """(3) a claim with no outcome is unknown: refuse, and be readable about it."""
        claimed = self.consult("req-3")
        with self.assertRaises(SERVER._CLEANUP_DISPATCH_JOURNAL.DispatchJournalError) as caught:
            self.consult("req-3")
        self.assertEqual(caught.exception.code, "CLEANUP_DISPATCH_OUTCOME_UNKNOWN")
        self.assertEqual(caught.exception.extra["journalDirectory"], claimed["directory"])
        self.assertEqual(caught.exception.extra["dispatchedIds"], BINDING["ids"])
        self.assertTrue(caught.exception.extra["claimedAtUtc"])
        reconciled = SERVER._CLEANUP_DISPATCH_JOURNAL.status(
            self.root, "round-1", "req-3", BINDING)
        self.assertEqual(reconciled["state"], "claimed-without-result")
        self.assertIs(reconciled["outcomeKnown"], False)
        self.assertEqual(reconciled["claim"]["command"], BINDING)

    def test_never_claimed_status_is_not_an_unknown_outcome(self):
        reconciled = SERVER._CLEANUP_DISPATCH_JOURNAL.status(
            self.root, "round-1", "never", BINDING)
        self.assertEqual(reconciled["state"], "never-claimed")
        self.assertIs(reconciled["outcomeKnown"], True)

    def test_directory_without_a_claim_is_not_a_first_call(self):
        """A request directory with no claim has no evidence of what was asked."""
        directory = SERVER._CLEANUP_DISPATCH_JOURNAL.journal_directory(
            self.root, "round-1", "req-4")
        directory.mkdir(parents=True)
        with self.assertRaises(SERVER._CLEANUP_DISPATCH_JOURNAL.DispatchJournalError) as caught:
            self.consult("req-4")
        self.assertEqual(caught.exception.code, "CLEANUP_REQUEST_INCOMPLETE_CLAIM")

    def test_unwritable_claim_refuses_before_any_dispatch(self):
        """A claim that cannot be written must refuse, not dispatch blindly."""
        module = SERVER._CLEANUP_DISPATCH_JOURNAL
        original = module._atomic_json
        module._atomic_json = lambda path, payload: _raise(OSError("stub: unwritable"))
        self.addCleanup(setattr, module, "_atomic_json", original)
        with self.assertRaises(module.DispatchJournalError) as caught:
            self.consult("req-5")
        self.assertEqual(caught.exception.code, "CLEANUP_DISPATCH_RECORD_UNWRITABLE")
        self.assertFalse((module.journal_directory(self.root, "round-1", "req-5")
                          / "result.json").exists())

    def test_request_id_must_be_one_safe_path_component(self):
        for bad in ("", "../etc/passwd", "a/b", "a\\b", "x" * 81, " leading", None):
            if bad is None:
                continue
            with self.assertRaises(SERVER._CLEANUP_DISPATCH_JOURNAL.DispatchJournalError) as c:
                self.consult(bad)
            self.assertEqual(c.exception.code, "CLEANUP_REQUEST_ID_INVALID")

    def test_derived_identity_is_command_scoped(self):
        """With no name, the identity follows the command: same command replays, others do not."""
        module = SERVER._CLEANUP_DISPATCH_JOURNAL
        first = self.consult(None)
        self.assertEqual(first["state"], "claimed")
        self.assertTrue(first["requestId"].startswith("cmd-"))
        module.record_outcome(first["directory"], first["requestId"], "round-1", BINDING,
                              {"ok": True})
        self.assertEqual(self.consult(None)["state"], "replayed")
        other = self.consult(None, OTHER_BINDING)
        self.assertEqual(other["state"], "claimed")             # a different command is a
        self.assertNotEqual(other["requestId"], first["requestId"])   # different request

    # -- (4) the concurrency control, at the filesystem ---------------------- #

    def test_concurrent_claim_is_exclusive_across_processes(self):
        """Real racing processes: exactly one claims, and every loser refuses.

        A thread test cannot see a TOCTOU window that the GIL happens to close; this runs
        six independent interpreters that all wait on the same filesystem barrier and then
        call ``consult`` with the same request.  One dispatch is what the route is allowed
        to make, so one claim is what this must produce.
        """
        racers = 6
        barrier = self.root / "barrier"
        barrier.mkdir(parents=True, exist_ok=True)
        runner = self.root / "runner.py"
        runner.write_text(_runner_source(), encoding="utf-8", newline="\n")
        binding_json = json.dumps(BINDING, sort_keys=True)
        children = [
            subprocess.Popen(
                [sys.executable, "-B", str(runner), str(JOURNAL_PATH.parent), str(self.root),
                 "round-1", "req-race", binding_json, str(barrier), str(index)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for index in range(racers)]
        deadline = time.time() + 30
        while time.time() < deadline:
            if len(list(barrier.glob("ready-*"))) == racers:
                break
            time.sleep(0.01)
        (barrier / "go").write_text("go", encoding="utf-8")
        states = []
        for child in children:
            out, err = child.communicate(timeout=60)
            line = (out or "").strip().splitlines()[-1] if (out or "").strip() else ""
            self.assertTrue(line, "a racer produced no state: %s" % err)
            states.append(json.loads(line)["state"])
        claimed = [s for s in states if s == "claimed"]
        self.assertEqual(len(claimed), 1, "states: %s" % states)
        for state in states:
            self.assertTrue(state == "claimed" or state.startswith("REFUSED"), states)
        result = SERVER._CLEANUP_DISPATCH_JOURNAL.status(
            self.root, "round-1", "req-race", BINDING)
        self.assertEqual(result["state"], "complete")


# --------------------------------------------------------------------------- #
# 2. the route, through the shared harness
# --------------------------------------------------------------------------- #

class JournalRouteProtection(unittest.TestCase):
    """The four protections as the tool reports them, with the dispatch sentinel counting."""

    def _probe(self, name):
        sentinel = H.DispatchSentinel()
        return P.ROUTE_PROBES[name](SERVER, sentinel), sentinel

    def test_1_same_request_and_command_replays_without_a_second_dispatch(self):
        held, sentinel = self._probe("journal-same-request-replays")
        self.assertTrue(held, "runCalls=%d" % sentinel.summary()["runCalls"])

    def test_2_same_request_different_command_is_refused(self):
        held, sentinel = self._probe("journal-different-command-refused")
        self.assertTrue(held, "runCalls=%d" % sentinel.summary()["runCalls"])

    def test_2b_different_request_different_command_still_dispatches(self):
        """The dry-run-then-delete (and multi-batch) flow must not be refused away."""
        held, sentinel = self._probe("journal-different-request-dispatches")
        self.assertTrue(held, "ops=%s" % sentinel.summary()["ops"])

    def test_3_claim_without_outcome_refuses_and_reports_the_reconciliation(self):
        held, sentinel = self._probe("journal-claim-without-outcome-refused")
        self.assertTrue(held, "runCalls=%d" % sentinel.summary()["runCalls"])

    def test_4_two_racing_requests_dispatch_at_most_once(self):
        held, sentinel = self._probe("journal-race-one-dispatch")
        self.assertTrue(held, "runCalls=%d" % sentinel.summary()["runCalls"])

    def test_unnamed_request_is_still_never_resent(self):
        held, sentinel = self._probe("journal-unnamed-request-never-resent")
        self.assertTrue(held, "runCalls=%d" % sentinel.summary()["runCalls"])

    def test_an_unsafe_request_name_never_reaches_the_transport(self):
        held, sentinel = self._probe("journal-bad-request-id-refused")
        self.assertTrue(held, "runCalls=%d" % sentinel.summary()["runCalls"])

    def test_a_missing_journal_refuses_instead_of_dispatching_blind(self):
        """Fail closed: no journal means a repeat cannot be told from a first call."""
        server = H.load_server(legs=H.load_legs())
        server._CLEANUP_DISPATCH_JOURNAL = None
        server._CLEANUP_DISPATCH_JOURNAL_ERROR = "stub: module removed"
        sentinel = H.DispatchSentinel()
        manifest = H.base_manifest()
        result = P._route(server, sentinel, H.real_receipt_ids(manifest),
                          manifest["roundRequestIds"])
        self.assertFalse(sentinel.dispatched(), sentinel.summary())
        self.assertEqual((H.tool_error(result) or {}).get("code"),
                         "CLEANUP_DISPATCH_JOURNAL_UNLOADABLE")

    def test_the_mirror_record_is_written_but_is_not_the_authority(self):
        """The pre-journal file survives as a mirror; deleting it changes no verdict."""
        manifest = H.base_manifest()
        ids = H.real_receipt_ids(manifest)
        sentinel = H.DispatchSentinel()
        first = _route_body(SERVER, sentinel, ids, manifest["roundRequestIds"], "mirror-1")
        mirror = SERVER._cleanup_dispatch_record_path(
            SERVER._cleanup_round_id(manifest["roundRequestIds"]))
        self.assertTrue(mirror.is_file(), "the compatibility mirror was not written")
        recorded = H.read_json(mirror)
        self.assertEqual(recorded.get("kind"), "cleanup-dispatch-record")
        self.assertEqual(recorded.get("authority"), "mirror")
        mirror.unlink()                                  # the journal is the authority
        second = _route_body(SERVER, sentinel, ids, manifest["roundRequestIds"], "mirror-1")
        self.assertTrue(second.get("replayed") is True)
        self.assertEqual(first.get("nativeReply"), second.get("nativeReply"))
        self.assertEqual(sentinel.summary()["runCalls"], 1)

    def test_a_lost_outcome_write_is_reported_and_never_mirrored_as_known(self):
        """The delete already happened when the outcome write fails; say so, and do not let
        the compatibility mirror assert an outcome the journal does not have."""
        server = H.load_server(legs=H.load_legs())
        sentinel = H.DispatchSentinel()
        manifest = H.base_manifest()
        ids = H.real_receipt_ids(manifest)
        module = server._CLEANUP_DISPATCH_JOURNAL
        module.record_outcome = lambda *args, **kwargs: _raise(OSError("stub: outcome lost"))
        body = H.tool_body(P._route(server, sentinel, ids, manifest["roundRequestIds"],
                                    cleanup_request_id="lost-" + uuid.uuid4().hex[:8]))
        self.assertIs(body.get("ok"), True)
        self.assertTrue(body.get("dispatchRecordWarning"),
                        "a dispatched delete with no recorded outcome was reported as clean")
        mirror = H.read_json(server._cleanup_dispatch_record_path(
            server._cleanup_round_id(manifest["roundRequestIds"])))
        self.assertEqual(mirror.get("authority"), "mirror")
        self.assertIs(mirror.get("outcomeKnown"), False)
        self.assertEqual(len(sentinel.run_calls), 1)


def _route_body(server, sentinel, ids, request_ids, cleanup_request_id, dry_run=False):
    body = H.tool_body(P._route(server, sentinel, ids, request_ids, dry_run=dry_run,
                               cleanup_request_id=cleanup_request_id))
    return body


# --------------------------------------------------------------------------- #
# 3. negative controls -- does each protection have discriminating power?
# --------------------------------------------------------------------------- #

class JournalMutationControls(unittest.TestCase):
    """Each mutation re-loads the journal from mutated SOURCE TEXT (never the file on
    disk) and re-runs the probes.  A probe that was green and goes red is the evidence
    that the protection -- not some other guard -- is what the probe measures."""

    MUTATIONS = [
        ("M1-drop-fingerprint-conflict",
         ("if recorded.get('fingerprint') != digest:", "if False:"),
         ("journal-different-command-refused",)),
        ("M2-drop-outcome-presence-check",
         ("if not result_path.is_file():", "if False:"),
         ("journal-claim-without-outcome-refused",)),
        ("M3-drop-the-exclusive-claim-mkdir",
         ("directory.mkdir(parents=True)", "directory.mkdir(parents=True, exist_ok=True)"),
         ("journal-same-request-replays", "journal-race-one-dispatch")),
        ("M4-drop-request-id-shape-check",
         ("if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):",
          "if False:"),
         ("journal-bad-request-id-refused",)),
    ]

    @staticmethod
    def _load_mutated(rename):
        return H.load_module_from_source(JOURNAL_PATH, "_w05_journal_mutated", rename=rename)

    @staticmethod
    def _anchors(rename):
        pairs = [rename] if isinstance(rename, tuple) else list(rename)
        return [old for old, _new in pairs]

    def _probe_results(self, server, names):
        results = {}
        for name in names:
            sentinel = H.DispatchSentinel()
            try:
                results[name] = P.ROUTE_PROBES[name](server, sentinel)
            except Exception as exc:                                  # noqa: BLE001
                results[name] = "%s: %s" % (type(exc).__name__, exc)
        return results

    def test_the_unmutated_baseline_is_green(self):
        server = H.load_server(legs=H.load_legs())
        names = [name for _id, _rename, targets in self.MUTATIONS for name in targets]
        for name, value in self._probe_results(server, sorted(set(names))).items():
            self.assertIs(value, True, "baseline probe %s was not green: %r" % (name, value))

    def test_every_protection_has_a_mutation_that_turns_its_probe_red(self):
        report = {"units": {"journal": str(JOURNAL_PATH),
                            "journalSha256": H.sha256_file(JOURNAL_PATH),
                            "server": str(H.SERVER_PATH),
                            "serverSha256": H.sha256_file(H.SERVER_PATH)},
                  "mutations": []}
        failures = []
        for mutation_id, rename, targets in self.MUTATIONS:
            server = H.load_server(legs=H.load_legs())
            server._CLEANUP_DISPATCH_JOURNAL = self._load_mutated(rename)
            observed = self._probe_results(server, targets)
            flipped = sorted(name for name, value in observed.items() if value is not True)
            report["mutations"].append({
                "id": mutation_id, "module": "backend/cleanup_dispatch_journal.py",
                "anchor": self._anchors(rename),
                "expectedFlips": list(targets), "flipped": flipped,
                "observed": {name: (value if isinstance(value, str) else bool(value))
                             for name, value in observed.items()},
                "verdict": "TURNS_RED" if flipped else "NO_EFFECT"})
            for name in targets:
                if name not in flipped:
                    failures.append("%s did not turn %s red: %r" % (mutation_id, name,
                                                                    observed[name]))
        H.write_json(HERE / "w05-journal-mutations.json", report)
        self.assertEqual(failures, [], "toothless probes: %s" % failures)


if __name__ == "__main__":
    unittest.main(verbosity=2)
