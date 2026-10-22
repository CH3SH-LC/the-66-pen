#!/usr/bin/env python3
"""Offline tests for tools/editor-bridge/playtest_one_click.py.

No machine contact at all: the transport is a fake session and time is a fake clock, so
the timing arithmetic, the outcome classifier and the "nobody clicked" path are all
exercised deterministically. Synthetic evidence documents are labelled as such; the one
recorded fixture used (the empty negative case) is real bytes already on disk and is used
ONLY to pin the NO_LOG_TRAFFIC shape.

Run:  python tools/editor-bridge/tests/test_playtest_one_click.py
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import re
import shlex
import tempfile
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools/editor-bridge/playtest_one_click.py"
REAL_EMPTY = (ROOT / ".runtime/editor-bridge/runs/"
              "e8aa539c-a1d1-4ca2-853a-07d841cca58a/log-observer-evidence-response.json")

spec = importlib.util.spec_from_file_location("playtest_one_click", MODULE_PATH)
oc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oc)


def synthetic(records=0, rows=(), active=True):
    """Synthetic evidence doc built from the documented shape. NOT recorded evidence."""
    return {
        "ok": True,
        "active": active,
        "observedPackets": 20,
        "observedLogPackets": records,
        "runLogSample": {
            "recordsSeen": records,
            "sampleLimit": 64,
            "sampleLimited": False,
            "sample": [
                {"observedUtc": "2026-10-11T00:00:00.0000000Z",
                 "graphName": "47504-100000001-1789551663-117851",
                 "bodyType": "T.Text", "bodyText": text}
                for text in rows
            ],
            "runtimeSemanticsVerified": False,
        },
    }


class FakeClock:
    """Monotonic clock that only advances when sleep() is called."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += max(0.0, float(dt))


class FakeSession:
    """Records the op sequence; returns canned replies. Never touches a queue."""

    RUN_ID = "10f68791-3a17-4cc9-ae11-e47ed9e81633"

    def __init__(self, evidence=None, load=None, arm=None, enable=None):
        self.ops = []
        self.run_id = ""
        self._evidence = evidence if evidence is not None else synthetic(records=0)
        self._load = load if load is not None else {
            "kind": "load", "accepted": True, "readyFilePresent": True, "runId": self.RUN_ID}
        self._arm = arm if arm is not None else {
            "ok": True, "active": True, "observerRegistered": True}
        self._enable = enable if enable is not None else {
            "ok": True, "status": "native-log-enable-requested",
            "selection": {"Identity": "own-graphs-live:name-prefix=MW_",
                          "Ids": [1073741831],
                          "Graphs": [{"id": 1073741831, "name": "MW_API_DEMO_RUN2",
                                      "category": [10000, 20000, 21001, 0], "nodeCount": 17}]}}

    def load(self):
        self.ops.append("load")
        if self._load.get("accepted") is True:
            self.run_id = self._load.get("runId", "")
        return self._load

    def call(self, op):
        self.ops.append(op)
        if op == oc.OP_ARM:
            return self._arm
        if op == oc.OP_ENABLE:
            return self._enable
        if op == oc.OP_EVIDENCE:
            return self._evidence
        return {"ok": True}


def cfg(window=120.0, interval=5.0, name="MW_API_DEMO_RUN2", gid=None):
    return {"window": window, "interval": interval, "graph_name": name, "graph_id": gid}


def run_orchestration(session, **kwargs):
    clock = FakeClock()
    return oc.orchestrate(session, cfg(**kwargs), sleep=clock.sleep, now=clock.now), clock


# ---------------------------------------------------------------------------
class TimingArithmeticTests(unittest.TestCase):
    """arm -> poll ... -> stop, as pure arithmetic."""

    def test_offsets_span_the_window_and_end_on_the_edge(self):
        for window, interval, expected_len in ((120.0, 5.0, 25), (120.0, 3.0, 41)):
            offs = oc.plan_poll_offsets(window, interval)
            self.assertEqual(len(offs), expected_len)
            self.assertEqual(offs[0], 0.0)
            self.assertEqual(offs[-1], window)          # a poll AT the lease edge
            self.assertEqual(offs, sorted(offs))
            self.assertTrue(all(o <= window for o in offs))
            self.assertEqual(len(offs), len(set(offs)))  # strictly increasing

    def test_interval_not_below_window_gives_two_polls(self):
        self.assertEqual(oc.plan_poll_offsets(5.0, 5.0), [0.0, 5.0])
        self.assertEqual(oc.plan_poll_offsets(5.0, 60.0), [0.0, 5.0])

    def test_bad_arithmetic_is_refused_by_name(self):
        with self.assertRaises(ValueError) as cm:
            oc.plan_poll_offsets(0.0, 5.0)
        self.assertIn("WINDOW_INVALID", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            oc.plan_poll_offsets(120.0, 0.0)
        self.assertIn("INTERVAL_INVALID", str(cm.exception))

    def test_window_cannot_exceed_the_observer_lease(self):
        with self.assertRaises(ValueError) as cm:
            oc.validate_window(121.0, 5.0)
        self.assertIn("WINDOW_OUT_OF_RANGE", str(cm.exception))
        self.assertEqual(oc.validate_window(120.0, 5.0)["window"], 120.0)

    def test_interval_above_window_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            oc.validate_window(10.0, 11.0)
        self.assertIn("INTERVAL_ABOVE_WINDOW", str(cm.exception))

    def test_polling_fills_the_window_then_stops(self):
        session = FakeSession()
        result, clock = run_orchestration(session)
        offsets = oc.plan_poll_offsets(120.0, 5.0)
        self.assertEqual(clock.t, 120.0)                       # exactly the window
        self.assertEqual(session.ops.count(oc.OP_EVIDENCE), len(offsets))
        self.assertEqual(session.ops[0], "load")
        self.assertEqual(session.ops[1], oc.OP_ARM)
        self.assertEqual(session.ops[2], oc.OP_ENABLE)
        self.assertEqual(session.ops[-1], oc.OP_STOP)          # stop is last, after polls
        self.assertEqual(session.ops.index(oc.OP_STOP),
                         session.ops.index(oc.OP_EVIDENCE) + len(offsets))
        self.assertEqual(result["outcome"], oc.OUT_NO_TRAFFIC)


# ---------------------------------------------------------------------------
class ClassifierTests(unittest.TestCase):
    """The three outcomes of PLAYTEST-ONE-CLICK.md §3, plus the honest edge cases."""

    def test_a_default_literal_is_the_default_outcome(self):
        self.assertEqual(oc.classify_outcome(synthetic(records=1, rows=["作物不足"])),
                         oc.OUT_CAPTURED_DEFAULT)
        self.assertEqual(oc.captured_literals(synthetic(records=1, rows=["作物不足"])),
                         ["作物不足"])

    def test_b_other_demo_literal_is_the_other_branch(self):
        for literal in ("背包容量偏低", "收获完成", "作物不足但货币充足"):
            self.assertEqual(oc.classify_outcome(synthetic(records=1, rows=[literal])),
                             oc.OUT_CAPTURED_OTHER)

    def test_default_wins_when_several_demo_literals_are_buffered(self):
        ev = synthetic(records=2, rows=["收获完成", "作物不足"])
        self.assertEqual(oc.classify_outcome(ev), oc.OUT_CAPTURED_DEFAULT)

    def test_c_no_records_at_all_is_no_log_traffic(self):
        self.assertEqual(oc.classify_outcome(synthetic(records=0)), oc.OUT_NO_TRAFFIC)

    def test_records_without_text_is_distinct_from_no_traffic(self):
        self.assertEqual(oc.classify_outcome(synthetic(records=7)), oc.OUT_NO_PRINT)

    def test_text_that_is_not_ours_is_foreign(self):
        self.assertEqual(oc.classify_outcome(synthetic(records=1, rows=["HELLO_WORLD"])),
                         oc.OUT_FOREIGN)
        self.assertEqual(oc.captured_literals(synthetic(records=1, rows=["HELLO_WORLD"])), [])

    def test_missing_document_is_unusable(self):
        for bad in (None, {}, {"ok": True}, {"runLogSample": None}):
            self.assertEqual(oc.classify_outcome(bad), oc.OUT_UNUSABLE)

    def test_real_recorded_negative_fixture_is_no_traffic(self):
        if not REAL_EMPTY.exists():
            self.skipTest("recorded negative fixture not on disk")
        ev = json.loads(REAL_EMPTY.read_text(encoding="utf-8-sig"))
        self.assertEqual(oc.classify_outcome(ev), oc.OUT_NO_TRAFFIC)

    def test_no_traffic_explanation_never_claims_non_execution(self):
        text = oc.outcome_explanation(oc.OUT_NO_TRAFFIC, synthetic(records=0))
        self.assertIn("NOT proof", text)

    def test_refusal_explanations_name_the_remedy(self):
        self.assertIn("next-revision.ps1",
                      oc.outcome_explanation(oc.OUT_LOAD_REFUSED, None))
        self.assertIn("Do not click",
                      oc.outcome_explanation(oc.OUT_GRAPH_NOT_SELECTED, None))


# ---------------------------------------------------------------------------
class NobodyClickedTests(unittest.TestCase):
    """SAFE TO RUN with nobody there: full window, named NO_LOG_TRAFFIC, no hang."""

    def test_no_click_is_no_log_traffic_and_exit_one(self):
        session = FakeSession(evidence=synthetic(records=0))
        result, clock = run_orchestration(session)
        self.assertEqual(result["outcome"], oc.OUT_NO_TRAFFIC)
        self.assertEqual(oc.exit_code_for(result["outcome"]), 1)
        self.assertEqual(clock.t, 120.0)

    def test_no_click_prints_the_named_verdict_and_raw_path(self):
        session = FakeSession()
        result, _ = run_orchestration(session)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_result(result, ROOT)
        out = buf.getvalue()
        self.assertIn("verdict: NO_LOG_TRAFFIC", out)
        self.assertIn("RAW EVIDENCE:", out)
        self.assertIn("log-observer-evidence-response.json", out)
        self.assertIn("playtest_log.py render", out)

    def test_evidence_path_is_the_runners_response_file(self):
        path = oc.evidence_response_path(ROOT, FakeSession.RUN_ID)
        self.assertEqual(path.name, "log-observer-evidence-response.json")
        self.assertEqual(path.parent.name, FakeSession.RUN_ID)

    def test_scope_loss_ends_the_polling_early(self):
        session = FakeSession(evidence={"ok": False, "error": "SCOPE_EXPIRED_OR_CLOSED"})
        result, clock = run_orchestration(session)
        self.assertLess(clock.t, 120.0)                 # stopped early, no hang
        self.assertEqual(session.ops[-1], oc.OP_STOP)
        self.assertGreater(result["pollFailures"], 0)
        self.assertEqual(result["outcome"], oc.OUT_CALL_UNCERTAIN)
        self.assertEqual(oc.exit_code_for(result["outcome"]), 3)

    def test_failed_polls_keep_the_last_good_evidence(self):
        class Flaky(FakeSession):
            def __init__(self):
                super().__init__(evidence=synthetic(records=1, rows=["作物不足"]))
                self.n = 0

            def call(self, op):
                if op == oc.OP_EVIDENCE:
                    self.n += 1
                    if self.n > 1:
                        self.ops.append(op)
                        return {"ok": False, "error": "TRANSIENT"}
                return super().call(op)

        result, _ = run_orchestration(Flaky())
        self.assertEqual(result["outcome"], oc.OUT_CAPTURED_DEFAULT)
        self.assertEqual(oc.exit_code_for(result["outcome"]), 0)


# ---------------------------------------------------------------------------
class RefusalTests(unittest.TestCase):
    """Each precondition fails closed BY NAME, before the human is asked to click."""

    def test_load_refused_stops_before_arming(self):
        session = FakeSession(load={"kind": "load", "accepted": False,
                                    "readyFilePresent": False, "runId": "x"})
        result, clock = run_orchestration(session)
        self.assertEqual(result["outcome"], oc.OUT_LOAD_REFUSED)
        self.assertEqual(oc.exit_code_for(result["outcome"]), 2)
        self.assertEqual(session.ops, ["load"])               # nothing armed
        self.assertEqual(clock.t, 0.0)

    def test_arm_refused_stops_before_enable(self):
        session = FakeSession(arm={"ok": False, "error": "OBSERVER_ALREADY_ATTEMPTED"})
        result, clock = run_orchestration(session)
        self.assertEqual(result["outcome"], oc.OUT_ARM_REFUSED)
        self.assertEqual(session.ops, ["load", oc.OP_ARM])
        self.assertEqual(clock.t, 0.0)

    def test_enable_refused_stops_before_the_banner(self):
        banner_called = []
        session = FakeSession(enable={"ok": False, "error": "LOG_ENABLE_REFUSED"})
        oc.orchestrate(session, cfg(), on_banner=lambda *a: banner_called.append(1))
        self.assertEqual(banner_called, [])
        self.assertEqual(session.ops, ["load", oc.OP_ARM, oc.OP_ENABLE])

    def test_graph_not_in_selection_stops_before_the_banner(self):
        banner_called = []
        enable = {"ok": True, "selection": {"Graphs": [
            {"id": 42, "name": "SOME_OTHER_GRAPH", "nodeCount": 3}]}}
        session = FakeSession(enable=enable)
        result = oc.orchestrate(session, cfg(), on_banner=lambda *a: banner_called.append(1))
        self.assertEqual(result["outcome"], oc.OUT_GRAPH_NOT_SELECTED)
        self.assertEqual(banner_called, [])
        self.assertEqual(session.ops[-1], oc.OP_ENABLE)      # never armed... never polled

    def test_banner_fires_after_arm_and_enable_and_before_polling(self):
        order = []
        session = FakeSession()

        class Spy(FakeSession):
            def call(self, op):
                order.append(op)
                return super().call(op)

        spy = Spy()
        spy.ops = order  # share

        def banner(*a):
            order.append("BANNER")

        oc.orchestrate(spy, cfg(), on_banner=banner, sleep=lambda _s: None, now=lambda: 0.0)
        self.assertLess(order.index("load"), order.index(oc.OP_ARM))
        self.assertLess(order.index(oc.OP_ARM), order.index(oc.OP_ENABLE))
        self.assertLess(order.index(oc.OP_ENABLE), order.index("BANNER"))
        self.assertLess(order.index("BANNER"), order.index(oc.OP_EVIDENCE))


# ---------------------------------------------------------------------------
class SelectionTests(unittest.TestCase):
    def _enable(self, graphs):
        return {"ok": True, "selection": {"Graphs": graphs}}

    def test_match_by_name_and_by_id(self):
        graphs = [{"id": 1073741831, "name": "MW_API_DEMO_RUN2", "nodeCount": 17}]
        self.assertTrue(oc.selection_contains(self._enable(graphs), "MW_API_DEMO_RUN2", None))
        self.assertTrue(oc.selection_contains(self._enable(graphs), None, 1073741831))
        self.assertFalse(oc.selection_contains(self._enable(graphs), "NOPE", None))
        self.assertFalse(oc.selection_contains(self._enable(graphs), None, 7))

    def test_empty_or_missing_selection_is_not_a_match(self):
        self.assertFalse(oc.selection_contains({"ok": True}, "MW_API_DEMO_RUN2", None))
        self.assertFalse(oc.selection_contains(self._enable([]), "MW_API_DEMO_RUN2", None))

    def test_summary_names_every_graph(self):
        summary = oc.selection_summary(self._enable(
            [{"id": 1, "name": "A", "nodeCount": 4}, {"id": 2, "name": "B", "nodeCount": 17}]))
        self.assertIn("A=1(4n)", summary)
        self.assertIn("B=2(17n)", summary)


# ---------------------------------------------------------------------------
class CliTests(unittest.TestCase):
    @staticmethod
    def _run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = oc.main(argv)
        return rc, buf.getvalue()

    def test_dry_run_prints_the_plan_and_dispatches_nothing(self):
        rc, out = self._run(["run", "--dry-run", "--window", "10", "--interval", "5"])
        self.assertEqual(rc, 0)
        plan = json.loads(out)
        self.assertEqual(plan["plan"][:3], ["load", oc.OP_ARM, oc.OP_ENABLE])
        self.assertEqual(plan["plan"][-1], oc.OP_STOP)
        self.assertEqual(plan["plan"].count(oc.OP_EVIDENCE), 3)   # offsets 0, 5, 10
        self.assertEqual(plan["pollOffsets"], [0.0, 5.0, 10.0])
        self.assertEqual(plan["pollOffsets"], oc.plan_poll_offsets(10.0, 5.0))

    def test_dry_run_refuses_a_window_over_the_lease(self):
        with self.assertRaises(SystemExit) as cm:
            self._run(["run", "--dry-run", "--window", "999"])
        self.assertIn("WINDOW_OUT_OF_RANGE", str(cm.exception))

    def test_documented_invocations_parse_through_the_real_parser(self):
        text = (oc.__doc__ or "")
        cmds = re.findall(r"python\s+\S*playtest_one_click\.py\s+[^`\n]*", text)
        self.assertTrue(cmds, "no documented invocation found in the module docstring")
        parser = oc.build_parser()
        for cmd in cmds:
            cmd = cmd.split("  #")[0].strip()          # drop a trailing inline comment
            toks = shlex.split(cmd)
            i = next(j for j, t in enumerate(toks) if t.endswith("playtest_one_click.py"))
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(toks[i + 1:])         # SystemExit(2) => fail
            resolved = (ROOT / toks[i]).resolve()
            self.assertEqual(resolved, MODULE_PATH)

    def test_exit_codes_are_partitioned(self):
        self.assertEqual(oc.exit_code_for(oc.OUT_CAPTURED_DEFAULT), 0)
        self.assertEqual(oc.exit_code_for(oc.OUT_CAPTURED_OTHER), 0)
        self.assertEqual(oc.exit_code_for(oc.OUT_NO_TRAFFIC), 1)
        self.assertEqual(oc.exit_code_for(oc.OUT_LOAD_REFUSED), 2)
        self.assertEqual(oc.exit_code_for(oc.OUT_CALL_UNCERTAIN), 3)


# ---------------------------------------------------------------------------
class ChannelVerdictTests(unittest.TestCase):
    """Three-valued per-channel verdict: CHANGED / UNCHANGED / UNREADABLE."""

    def test_fewer_than_two_successful_reads_is_unreadable(self):
        self.assertEqual(oc.channel_verdict([]), oc.VERDICT_UNREADABLE)
        self.assertEqual(oc.channel_verdict([{"ok": True, "value": 1}]), oc.VERDICT_UNREADABLE)
        self.assertEqual(
            oc.channel_verdict([{"ok": False, "value": None}, {"ok": False, "value": None}]),
            oc.VERDICT_UNREADABLE)

    def test_two_equal_reads_is_unchanged(self):
        s = [{"offset": 0.0, "ok": True, "value": ("a",)},
             {"offset": 5.0, "ok": True, "value": ("a",)}]
        self.assertEqual(oc.channel_verdict(s), oc.VERDICT_UNCHANGED)
        self.assertIsNone(oc.first_change_offset(s))

    def test_a_moved_value_is_changed_and_reports_when(self):
        s = [{"offset": 0.0, "ok": True, "value": ()},
             {"offset": 15.0, "ok": True, "value": (("g", "作物不足"),)}]
        self.assertEqual(oc.channel_verdict(s), oc.VERDICT_CHANGED)
        self.assertEqual(oc.first_change_offset(s), 15.0)

    def test_failed_reads_are_skipped_not_treated_as_changes(self):
        s = [{"offset": 0.0, "ok": True, "value": ("a",)},
             {"offset": 5.0, "ok": False, "value": None},
             {"offset": 10.0, "ok": True, "value": ("a",)}]
        self.assertEqual(oc.channel_verdict(s), oc.VERDICT_UNCHANGED)
        self.assertEqual(oc.count_good(s), 2)

    def test_key_projection_decides_movement_not_the_raw_value(self):
        s = [{"offset": 0.0, "ok": True, "value": ((0, 9),)},
             {"offset": 5.0, "ok": True, "value": ((0, 120),)}]
        self.assertEqual(oc.channel_verdict(s), oc.VERDICT_CHANGED)              # raw moves
        self.assertEqual(oc.channel_verdict(s, oc.packet_kinds_key),
                         oc.VERDICT_UNCHANGED)                                   # meaning does not


# ---------------------------------------------------------------------------
class ChannelRoleVocabularyTests(unittest.TestCase):
    """The structural rule: ONLY the one diagnostic channel may ever print CHANGED."""

    def test_only_log_evidence_is_diagnostic(self):
        self.assertEqual(oc.diagnostic_channels(), ("log-evidence",))

    def test_context_channels_are_every_other_channel(self):
        for name in ("packet-kinds", "observer-liveness", "gil-hash", "native-entities"):
            self.assertNotIn(name, oc.diagnostic_channels())

    def test_the_context_vocabulary_can_never_say_changed(self):
        self.assertNotIn(oc.VERDICT_CHANGED, oc._CONTEXT_VERDICT.values())
        self.assertNotIn(oc.VERDICT_UNCHANGED, oc._CONTEXT_VERDICT.values())
        self.assertEqual(oc._CONTEXT_VERDICT[oc.VERDICT_CHANGED], oc.VERDICT_MOVED)
        self.assertEqual(oc._CONTEXT_VERDICT[oc.VERDICT_UNCHANGED], oc.VERDICT_STILL)

    def test_a_context_channel_renames_its_raw_movement(self):
        ch = oc.EvidenceChannel("packet-kinds", oc.value_packet_kinds, "x")
        ch._record(0.0, True, ((1022, 1),))
        ch._record(5.0, True, ((1022, 1), (3006, 2)))
        self.assertEqual(ch.verdict(), oc.VERDICT_CHANGED)          # raw movement...
        self.assertEqual(ch.report_verdict(), oc.VERDICT_MOVED)     # ...printed as context
        self.assertNotEqual(ch.report_verdict(), oc.VERDICT_CHANGED)

    def test_a_diagnostic_channel_keeps_the_changed_word(self):
        ch = oc.EvidenceChannel("log-evidence", oc.value_log_rows, "x", decisive=True)
        ch._record(0.0, True, ())
        ch._record(5.0, True, (("g", "作物不足"),))
        self.assertEqual(ch.verdict(), oc.VERDICT_CHANGED)
        self.assertEqual(ch.report_verdict(), oc.VERDICT_CHANGED)

    def test_channel_row_carries_the_role_and_both_verdicts(self):
        ch = oc.EvidenceChannel("observer-liveness", oc.value_observer_liveness, "x",
                                key=oc.observer_liveness_key)
        ch._record(0.0, True, (True, 1, 0))
        ch._record(5.0, True, (True, 120, 0))
        row = oc._channel_row(ch)
        self.assertEqual(row["role"], oc.ROLE_CONTEXT)
        self.assertEqual(row["verdict"], oc.VERDICT_STILL)
        self.assertEqual(row["keyVerdict"], oc.VERDICT_UNCHANGED)  # meaning did not move...
        self.assertTrue(row["valueMoved"])                         # ...but the raw value did

    def test_every_registry_channel_carries_its_means_and_not_means(self):
        for name, *_ in oc.CHANNEL_REGISTRY:
            self.assertIn(name, oc.CHANNEL_SEMANTICS, f"{name} has no meaning annotation")
            sem = oc.CHANNEL_SEMANTICS[name]
            self.assertTrue(sem.get("means") and sem.get("not_means"))


# ---------------------------------------------------------------------------
class ChannelMeaningKeyTests(unittest.TestCase):
    """A key projects the raw value to the part whose movement is meaningful."""

    def _pk(self):
        return oc.EvidenceChannel("packet-kinds", oc.value_packet_kinds, "x",
                                  render=oc.render_packet_kinds, key=oc.packet_kinds_key)

    def test_keepalive_only_packet_mix_is_not_scene_traffic(self):
        """DEFECT 2: {0:9} -> {0:120} used to read CHANGED. It is transport, not scene."""
        ch = self._pk()
        ch._record(0.0, True, ((0, 9),))
        ch._record(5.0, True, ((0, 120),))
        self.assertEqual(ch.verdict(), oc.VERDICT_UNCHANGED)
        self.assertEqual(ch.report_verdict(), oc.VERDICT_STILL)
        self.assertNotIn(ch.report_verdict(), (oc.VERDICT_CHANGED, oc.VERDICT_MOVED))

    def test_keepalive_arriving_late_is_still_not_scene_traffic(self):
        ch = self._pk()
        ch._record(0.0, True, ())                    # no packets yet
        ch._record(5.0, True, ((0, 120),))           # keepalive begins
        self.assertEqual(ch.report_verdict(), oc.VERDICT_STILL)

    def test_a_genuinely_new_packet_id_is_context_movement(self):
        ch = self._pk()
        ch._record(0.0, True, ((0, 9),))
        ch._record(5.0, True, ((0, 120), (1022, 1)))
        self.assertEqual(ch.report_verdict(), oc.VERDICT_MOVED)

    def test_packet_kinds_key_matches_the_documented_defect_pair(self):
        self.assertEqual(oc.packet_kinds_key(((0, 9),)), oc.packet_kinds_key(((0, 120),)))
        self.assertNotEqual(oc.packet_kinds_key(((0, 120),)),
                            oc.packet_kinds_key(((0, 120), (1022, 1))))

    def test_observer_liveness_key_ignores_the_counters(self):
        self.assertEqual(oc.observer_liveness_key((True, 9, 0)),
                         oc.observer_liveness_key((True, 120, 7)))
        self.assertNotEqual(oc.observer_liveness_key((True, 120, 0)),
                            oc.observer_liveness_key((False, 120, 0)))
        self.assertIsNone(oc.observer_liveness_key(None))

    def test_native_key_drops_the_per_read_helper_flag(self):
        self.assertEqual(oc.native_entities_key((7, 12, True)),
                         oc.native_entities_key((7, 12, False)))
        self.assertNotEqual(oc.native_entities_key((7, 12, True)),
                            oc.native_entities_key((7, 13, True)))

    def test_the_summary_admits_when_only_the_raw_value_moved(self):
        ch = self._pk()
        ch._record(0.0, True, ((0, 9),))
        ch._record(5.0, True, ((0, 120),))
        summary = ch.summary()
        self.assertIn("meaning key", summary)          # not the lie "identical"
        self.assertIn("not graph evidence", summary)


# ---------------------------------------------------------------------------
class NothingHappenedMustNotMisleadTests(unittest.TestCase):
    """DEFECT 1: a run where NOTHING ran must not print a misleading CHANGED anywhere.

    The old table showed ``observer-liveness`` CHANGED in exactly this run, because the
    sink's OWN counters climbed while the graph did nothing at all.
    """

    class Warming(FakeSession):
        """No click: records stay zero while the observer's counters and keepalive climb."""

        def __init__(self):
            super().__init__()
            self.n = 0

        def call(self, op):
            if op == oc.OP_EVIDENCE:
                self.n += 1
                self.ops.append(op)
                ev = synthetic(records=0)              # nothing was printed
                ev["observedPackets"] = 9 * self.n     # ...but the sink saw traffic grow
                ev["observedLogPackets"] = 0
                ev["packetKinds"] = {"0": 9 * self.n}  # keepalive only
                return ev
            return super().call(op)

    def _run(self):
        clock = FakeClock()
        samplers = oc.build_samplers(ROOT, "run-x", cfg(), native=False, gil_root=None)
        result = oc.orchestrate(self.Warming(), cfg(), samplers_for=lambda r: samplers,
                                sleep=clock.sleep, now=clock.now)
        return {c["name"]: c for c in result["channels"]}, result

    def test_no_channel_prints_changed(self):
        rows, result = self._run()
        self.assertEqual(result["outcome"], oc.OUT_NO_TRAFFIC)
        changed = [n for n, c in rows.items() if c["verdict"] == oc.VERDICT_CHANGED]
        self.assertEqual(changed, [], "no channel may print CHANGED when nothing ran")

    def test_only_log_evidence_is_diagnostic_and_it_is_unchanged(self):
        rows, _result = self._run()
        diag = [n for n, c in rows.items() if c["role"] == oc.ROLE_DIAGNOSTIC]
        self.assertEqual(diag, ["log-evidence"])
        self.assertEqual(rows["log-evidence"]["verdict"], oc.VERDICT_UNCHANGED)

    def test_observer_liveness_is_still_not_changed(self):
        rows, _result = self._run()
        self.assertEqual(rows["observer-liveness"]["verdict"], oc.VERDICT_STILL)
        self.assertEqual(rows["observer-liveness"]["keyVerdict"], oc.VERDICT_UNCHANGED)
        self.assertTrue(rows["observer-liveness"]["valueMoved"])   # counters climbed...

    def test_packet_kinds_raw_counts_moved_but_the_channel_is_still(self):
        rows, _result = self._run()
        self.assertEqual(rows["packet-kinds"]["verdict"], oc.VERDICT_STILL)
        self.assertTrue(rows["packet-kinds"]["valueMoved"])        # ...{0:9}->{0:120}...

    def test_packet_kinds_keepalive_growth_is_still(self):
        rows, _result = self._run()
        self.assertEqual(rows["packet-kinds"]["verdict"], oc.VERDICT_STILL)

    def test_the_printed_table_names_the_only_diagnostic_channel(self):
        _rows, result = self._run()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_result(result, ROOT)
        out = buf.getvalue()
        self.assertIn("DIAGNOSTIC CHANNEL", out)
        self.assertIn("log-evidence = UNCHANGED", out)
        self.assertIn("every other row is CONTEXT", out)


# ---------------------------------------------------------------------------
class ValueExtractorTests(unittest.TestCase):
    """Synthetic evidence documents; each extractor returns None when unreadable."""

    def test_log_rows_absent_without_a_run_log_sample(self):
        self.assertIsNone(oc.value_log_rows(None))
        self.assertIsNone(oc.value_log_rows({}))
        self.assertIsNone(oc.value_log_rows({"ok": True}))

    def test_log_rows_are_the_sorted_graph_text_pairs(self):
        ev = synthetic(records=1, rows=["作物不足"])
        self.assertEqual(oc.value_log_rows(ev),
                         (("47504-100000001-1789551663-117851", "作物不足"),))
        self.assertEqual(oc.value_log_rows(synthetic(records=0)), ())   # readable + empty

    def test_packet_kinds_sorted_pairs(self):
        ev = synthetic(records=0)
        ev["packetKinds"] = {"3006": 2, "1022": 1}
        self.assertEqual(oc.value_packet_kinds(ev), ((1022, 1), (3006, 2)))
        self.assertIsNone(oc.value_packet_kinds({"ok": True}))

    def test_liveness_needs_the_evidence_document(self):
        self.assertIsNone(oc.value_observer_liveness({"active": True}))
        self.assertEqual(oc.value_observer_liveness(synthetic(records=0, active=False)),
                         (False, 20, 0))


# ---------------------------------------------------------------------------
class GilValueTests(unittest.TestCase):
    """SYNTHETIC fixtures: a temp directory shaped like the live save root."""

    def test_absent_root_is_unreadable_not_empty(self):
        self.assertIsNone(oc.value_gil_state(pathlib.Path("no/such/dir/at/all")))

    def test_a_changed_gil_moves_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "BeyondLocal"
            level = root / "100000001" / "Beyond_Local_Save_Level" / "1073741842"
            level.mkdir(parents=True)
            gil = level / "1073741842.gil"
            gil.write_bytes(b"one")
            before = oc.value_gil_state(root)
            self.assertEqual(len(before), 1)
            self.assertEqual(before[0][1], 3)                       # byte size
            gil.write_bytes(b"two-longer")
            self.assertNotEqual(before, oc.value_gil_state(root))

    def test_an_empty_but_present_root_is_readable(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td) / "BeyondLocal"
            root.mkdir()
            self.assertEqual(oc.value_gil_state(root), ())


# ---------------------------------------------------------------------------
class NativeScheduleTests(unittest.TestCase):
    """A native read costs 5-8 s, so it is budgeted: first + last-before-the-margin."""

    def test_first_and_last_before_the_margin(self):
        offs = oc.plan_poll_offsets(120.0, 5.0)
        self.assertEqual(oc.pick_native_offsets(offs, 120.0), [0.0, 110.0])

    def test_tiny_window_yields_a_single_read(self):
        self.assertEqual(oc.pick_native_offsets(oc.plan_poll_offsets(10.0, 5.0), 10.0), [0.0])

    def test_no_offsets_is_no_reads(self):
        self.assertEqual(oc.pick_native_offsets([], 120.0), [])


class NativeChannelTests(unittest.TestCase):
    def test_ok_reply_records_a_readable_value(self):
        reader = oc.read_native(lambda: {"ok": True, "levelId": 1073741842, "entities": 12,
                                         "helperReplyOk": False})
        ch = oc.NativeChannel("native-entities", reader, [0.0], "x")
        ch.observe(0.0, {})
        self.assertTrue(ch.samples[0]["ok"])
        self.assertEqual(ch.samples[0]["value"], (1073741842, 12, False))

    def test_ok_false_reply_is_not_a_read(self):
        reader = oc.read_native(lambda: {"ok": False, "levelId": None,
                                         "error": "Observed current editing level is unverified"})
        ch = oc.NativeChannel("native-entities", reader, [0.0], "x")
        ch.observe(0.0, {})
        self.assertFalse(ch.samples[0]["ok"])
        self.assertIn("unverified", ch.samples[0]["note"])

    def test_a_raising_reader_is_recorded_not_propagated(self):
        def boom():
            raise RuntimeError("NATIVE_INSPECT_DRIVER_MISSING")
        ch = oc.NativeChannel("native-entities", oc.read_native(boom), [0.0], "x")
        ch.observe(0.0, {})                                    # must not raise
        self.assertFalse(ch.samples[0]["ok"])
        self.assertIn("NATIVE_INSPECT_DRIVER_MISSING", ch.samples[0]["note"])

    def test_only_scheduled_offsets_dispatch(self):
        calls = []

        def reader():
            calls.append(1)
            return True, (1, 2, 3), ""

        ch = oc.NativeChannel("native-entities", reader, [0.0, 100.0], "x")
        for off in (0.0, 5.0, 100.0, 115.0):
            ch.observe(off, {})
        self.assertEqual(len(calls), 2)


# ---------------------------------------------------------------------------
class NativePreflightLockTests(unittest.TestCase):
    """The playtest-exposed defect: the channel opened YuanShen.exe on disk.

    The driver re-validates the pinned profile against the ON-DISK image before it
    enqueues anything, so a locked image surfaces as a naked ``PermissionError`` on a
    channel whose job is to read the LIVE level. These pin the fix: the fault is named
    and placed, it is NOT a fake read, it is retried (bounded) because the lock is a
    property of the moment, and a fault that happened AFTER a dispatch is never retried.
    """

    #: The shape ``discover_current_level.main``'s handler produced on 2026-10-11 (run
    #: d78cc181): a driver fault carries failedAt/failedSource and NO run/reasons.
    LOCK = {
        "ok": False, "kind": "current-level-observation",
        "error": ("PermissionError: [Errno 13] Permission denied: "
                  "'C:\\Games\\Genshin Impact Game\\YuanShen.exe'"),
        "failedAt": ["discover_current_level.py:637 in discover_via_queue",
                     "native_profiles.py:106 in verify_disk"],
        "failedSource": ["profiles.verify_disk(profiles.load_profile())"],
        "retryAttempted": False,
    }

    def test_the_lock_is_recognised_only_from_a_driver_fault(self):
        self.assertTrue(oc.is_preflight_image_lock(self.LOCK))
        # a gate rejection is a verdict about a read that DID happen -> never this class
        gate = {"ok": False, "run": "r", "reasons": ["LEVEL_NOT_OBSERVED"]}
        self.assertFalse(oc.is_preflight_image_lock(gate))
        # a hash mismatch is also a failedAt fault, but it is not a lock: pins moved
        moved = dict(self.LOCK, error="GAME_SOURCE_HASH_MISMATCH")
        self.assertFalse(oc.is_preflight_image_lock(moved))
        # a message that merely mentions permission but not the image is not this class
        other = dict(self.LOCK, error="PermissionError: [Errno 13] Permission denied: 'x'")
        self.assertFalse(oc.is_preflight_image_lock(other))
        self.assertFalse(oc.is_preflight_image_lock(None))
        self.assertFalse(oc.is_preflight_image_lock("nope"))

    def test_the_note_names_the_class_and_places_it_in_the_chain(self):
        note = oc.native_failure_note(dict(self.LOCK, preflightAttempts=3))
        self.assertIn("PREFLIGHT_GAME_IMAGE_LOCK", note)
        self.assertIn("NOTHING about", note)          # never read as "the level was blank"
        self.assertIn("native_profiles.py:106 in verify_disk", note)  # innermost frame
        self.assertIn("discover_current_level.py:637", note)          # outermost frame
        self.assertIn("attempts=3", note)             # a retry is disclosed, not silent
        self.assertIn("PermissionError", note)        # the raw text is still quoted

    def test_a_gate_rejection_note_keeps_its_reasons(self):
        note = oc.native_failure_note({"ok": False, "reasons": ["LEVEL_NOT_OBSERVED"]})
        self.assertIn("LEVEL_NOT_OBSERVED", note)
        self.assertNotIn("PREFLIGHT_GAME_IMAGE_LOCK", note)

    def _inspect(self, replies, attempts=3):
        calls = []

        def fake(root, output_root, *, queue_rel=None, timeout=None):
            calls.append(1)
            return dict(replies[min(len(calls) - 1, len(replies) - 1)])

        with unittest.mock.patch.object(oc, "_inspect_once", fake):
            reply = oc.native_inspect(ROOT, ROOT / "x", attempts=attempts, retry_delay=0.0)
        return reply, calls

    def test_a_persistent_lock_is_retried_the_bounded_number_of_times(self):
        self.assertGreater(oc.PREFLIGHT_ATTEMPTS, 1)
        self.assertLessEqual(oc.PREFLIGHT_ATTEMPTS, 5)   # cheap: 2 reads per window
        reply, calls = self._inspect([self.LOCK], attempts=oc.PREFLIGHT_ATTEMPTS)
        self.assertEqual(len(calls), oc.PREFLIGHT_ATTEMPTS)
        self.assertEqual(reply["preflightAttempts"], oc.PREFLIGHT_ATTEMPTS)
        self.assertFalse(reply["ok"])

    def test_a_transient_lock_recovers_within_the_bound(self):
        good = {"ok": True, "levelId": 1073741842, "entities": 12, "helperReplyOk": True}
        reply, calls = self._inspect([self.LOCK, self.LOCK, good])
        self.assertEqual(len(calls), 3)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["levelId"], 1073741842)

    def test_a_gate_rejection_is_never_retried(self):
        gate = {"ok": False, "run": "r", "reasons": ["LEVEL_NOT_OBSERVED"],
                "helperReplyOk": False}
        reply, calls = self._inspect([gate])
        self.assertEqual(len(calls), 1)                  # a dispatch is never double-spent
        self.assertEqual(reply["reasons"], ["LEVEL_NOT_OBSERVED"])

    def test_a_hash_mismatch_fault_is_not_retried(self):
        moved = dict(self.LOCK, error="GAME_SOURCE_HASH_MISMATCH")
        _reply, calls = self._inspect([moved])
        self.assertEqual(len(calls), 1)                  # pins moved: refuse, do not hammer

    def test_the_channel_reports_a_named_lock_and_the_run_still_completes(self):
        def reader():
            return self.LOCK

        ch = oc.NativeChannel("native-entities", oc.read_native(reader), [0.0], "x")
        ch.observe(0.0, {})
        self.assertFalse(ch.samples[0]["ok"])            # ok=False, never a fake success
        self.assertEqual(ch.verdict(), oc.VERDICT_UNREADABLE)
        self.assertIn("PREFLIGHT_GAME_IMAGE_LOCK", ch.summary())

        clock = FakeClock()
        samplers = oc.build_samplers(ROOT, "run-x", cfg(), native=True, gil_root=None,
                                     native_reader=reader)
        result = oc.orchestrate(FakeSession(evidence=synthetic(records=1, rows=["作物不足"])),
                                cfg(), samplers_for=lambda r: samplers,
                                sleep=clock.sleep, now=clock.now)
        native = {c["name"]: c for c in result["channels"]}["native-entities"]
        self.assertEqual(native["verdict"], oc.VERDICT_UNREADABLE)
        self.assertEqual(native["readsOk"], 0)
        self.assertIn("PREFLIGHT_GAME_IMAGE_LOCK", native["summary"])
        self.assertEqual(result["outcome"], oc.OUT_CAPTURED_DEFAULT)   # capture not aborted
        self.assertEqual(clock.t, 120.0)                               # window unchanged

    def test_two_failed_reads_for_two_reasons_report_both(self):
        """The recorded run failed twice for TWO reasons: a gate rejection at T+0 and the
        image lock at T+110. Showing only the last note would erase the first."""
        def reader():
            return self.LOCK

        samples = [
            {"offset": 0.0, "ok": False, "value": None,
             "note": "at discover_current_level.py:583 in decode_receipt: ValueError: x"},
            {"offset": 110.0, "ok": False, "value": None,
             "note": oc.native_failure_note(dict(self.LOCK, preflightAttempts=1))},
        ]
        ch = oc.NativeChannel("native-entities", oc.read_native(reader), [0.0], "x")
        ch.samples = samples
        summary = ch.summary()
        self.assertIn("2 distinct reasons", summary)
        self.assertIn("PREFLIGHT_GAME_IMAGE_LOCK", summary)   # the last reason
        self.assertIn("decode_receipt", summary)              # ...and the earlier one

    def test_one_reason_repeated_is_not_counted_as_two(self):
        ch = oc.NativeChannel("native-entities", lambda: (False, None, "x"), [0.0], "x")
        for off in (0.0, 110.0):
            ch._record(off, False, None, "HELPER_CAPABILITY_MISMATCH")
        self.assertEqual(ch.summary(), "no successful read: HELPER_CAPABILITY_MISMATCH")

    def test_the_exe_path_is_absent_from_the_sampler_itself(self):
        """The sampler must not open the game image: only the pinned driver may."""
        src = MODULE_PATH.read_text(encoding="utf-8")
        # POSITIVE CONTROL through the SAME instrument, so the zeros below mean
        # something: this file DOES name the driver it delegates to.
        self.assertIn("discover_current_level.py", src)
        self.assertIn("native_profiles.py:104-119", src)  # ...and documents where the open is
        # The proof may be NAMED (it is explained above), but the pin machinery must not
        # be imported or invoked here: the open happens in the pinned driver, not here.
        self.assertNotIn("import native_profiles", src)
        self.assertNotIn("load_profile", src)
        self.assertNotIn("verify_disk(", src)


# ---------------------------------------------------------------------------
class ChannelTableTests(unittest.TestCase):
    def test_table_names_every_channel_and_marks_the_decisive_one(self):
        rows = [
            {"name": "log-evidence", "verdict": oc.VERDICT_CHANGED, "reads": 25, "readsOk": 25,
             "summary": "1 row(s): 作物不足", "decisive": True},
            {"name": "gil-hash", "verdict": oc.VERDICT_UNCHANGED, "reads": 2, "readsOk": 2,
             "summary": "9 file(s), 21872 B total", "decisive": False},
            {"name": "native-entities", "verdict": oc.VERDICT_UNREADABLE, "reads": 2, "readsOk": 0,
             "summary": "no successful read: ok=False", "decisive": False},
        ]
        text = "\n".join(oc.channel_table_lines(rows))
        self.assertIn("* log-evidence", text)
        self.assertIn("CHANGED", text)
        self.assertIn("UNCHANGED", text)
        self.assertIn("UNREADABLE", text)
        self.assertIn("9 file(s)", text)

    def test_no_channels_is_no_table(self):
        self.assertEqual(oc.channel_table_lines([]), [])

    def test_registry_names_are_the_channels_that_get_built(self):
        built = {s.name for s in oc.build_samplers(ROOT, "run-x", cfg(),
                                                   native=True, gil_root=None,
                                                   native_reader=lambda: {})}
        self.assertEqual(built, {n for n, *_ in oc.CHANNEL_REGISTRY if n != "gil-hash"})

    def test_only_log_evidence_is_decisive_for_our_graph(self):
        decisive = [n for n, *_rest, d in oc.CHANNEL_REGISTRY if d]
        self.assertEqual(decisive, ["log-evidence"])


# ---------------------------------------------------------------------------
class EffectiveWindowChannelTests(unittest.TestCase):
    """Channels ride the SAME window; a failed channel is UNREADABLE, never a fake read."""

    def _samplers(self, native=False, gil_root=None, native_reader=None):
        return oc.build_samplers(ROOT, "run-x", cfg(), native=native, gil_root=gil_root,
                                 native_reader=native_reader)

    def test_log_evidence_channel_changes_when_its_value_appears(self):
        class Growing(FakeSession):
            def __init__(self):
                super().__init__()
                self.n = 0

            def call(self, op):
                if op == oc.OP_EVIDENCE:
                    self.n += 1
                    self.ops.append(op)
                    return (synthetic(records=0) if self.n <= 2
                            else synthetic(records=1, rows=["作物不足"]))
                return super().call(op)

        clock = FakeClock()
        samplers = self._samplers()
        result = oc.orchestrate(Growing(), cfg(), samplers_for=lambda r: samplers,
                                sleep=clock.sleep, now=clock.now)
        rows = {c["name"]: c for c in result["channels"]}
        self.assertEqual(rows["log-evidence"]["verdict"], oc.VERDICT_CHANGED)
        self.assertEqual(rows["log-evidence"]["readsOk"], 25)
        self.assertEqual(rows["log-evidence"]["decisive"], True)
        self.assertEqual(result["outcome"], oc.OUT_CAPTURED_DEFAULT)   # classifier intact
        self.assertEqual(clock.t, 120.0)                               # window unchanged

    def test_an_evidence_channel_without_its_field_is_unreadable(self):
        ch = oc.EvidenceChannel("log-evidence", oc.value_log_rows, "x",
                                render=oc.render_log_rows, decisive=True)
        for off in (0.0, 5.0, 10.0):
            ch.observe(off, {"evidence": {"ok": True}})
        self.assertEqual(ch.verdict(), oc.VERDICT_UNREADABLE)
        self.assertEqual(oc.count_good(ch.samples), 0)
        self.assertIn("absent", ch.summary())

    def test_no_click_with_channels_still_names_no_log_traffic(self):
        clock = FakeClock()
        samplers = self._samplers()
        result = oc.orchestrate(FakeSession(evidence=synthetic(records=0)), cfg(),
                                samplers_for=lambda r: samplers,
                                sleep=clock.sleep, now=clock.now)
        self.assertEqual(result["outcome"], oc.OUT_NO_TRAFFIC)
        self.assertEqual(clock.t, 120.0)
        names = [c["name"] for c in result["channels"]]
        self.assertEqual(names, ["log-evidence", "packet-kinds", "observer-liveness"])

    def test_a_native_reader_is_driven_at_its_two_budgeted_offsets(self):
        calls = []

        def reader():
            calls.append(1)
            return {"ok": True, "levelId": 1073741842, "entities": 12, "helperReplyOk": True}

        clock = FakeClock()
        samplers = self._samplers(native=True, native_reader=reader)
        result = oc.orchestrate(FakeSession(evidence=synthetic(records=0)), cfg(),
                                samplers_for=lambda r: samplers,
                                sleep=clock.sleep, now=clock.now)
        native = {c["name"]: c for c in result["channels"]}["native-entities"]
        self.assertEqual(len(calls), 2)
        # same level both times: a CONTEXT channel says STILL, never UNCHANGED
        self.assertEqual(native["verdict"], oc.VERDICT_STILL)
        self.assertEqual(native["keyVerdict"], oc.VERDICT_UNCHANGED)
        self.assertEqual(native["readsOk"], 2)

    def test_an_unreadable_native_channel_does_not_break_the_run(self):
        def reader():
            return {"ok": False, "levelId": None, "error": "HELPER_CAPABILITY_MISMATCH"}

        clock = FakeClock()
        samplers = self._samplers(native=True, native_reader=reader)
        result = oc.orchestrate(FakeSession(evidence=synthetic(records=1, rows=["作物不足"])),
                                cfg(), samplers_for=lambda r: samplers,
                                sleep=clock.sleep, now=clock.now)
        native = {c["name"]: c for c in result["channels"]}["native-entities"]
        self.assertEqual(native["verdict"], oc.VERDICT_UNREADABLE)
        self.assertIn("HELPER_CAPABILITY_MISMATCH", native["summary"])
        self.assertEqual(result["outcome"], oc.OUT_CAPTURED_DEFAULT)   # classifier intact


# ---------------------------------------------------------------------------
class ChannelsCliTests(unittest.TestCase):
    @staticmethod
    def _run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = oc.main(argv)
        return rc, buf.getvalue()

    def test_channels_subcommand_lists_the_registry(self):
        rc, out = self._run(["channels"])
        self.assertEqual(rc, 0)
        for name, *_ in oc.CHANNEL_REGISTRY:
            self.assertIn(name, out)
        decisive_line = next(l for l in out.splitlines() if l.strip().startswith("log-evidence"))
        self.assertIn(oc.ROLE_DIAGNOSTIC, decisive_line)
        self.assertIn("only the diagnostic channel", out.lower())

    def test_dry_run_names_the_channels_and_native_offsets(self):
        rc, out = self._run(["run", "--dry-run", "--window", "120", "--interval", "5"])
        plan = json.loads(out)
        self.assertIn("log-evidence", plan["channels"])
        self.assertIn("native-entities", plan["channels"])
        self.assertEqual(plan["nativeOffsets"], [0.0, 110.0])

    def test_dry_run_no_native_drops_the_native_channel(self):
        rc, out = self._run(["run", "--dry-run", "--no-native"])
        plan = json.loads(out)
        self.assertNotIn("native-entities", plan["channels"])
        self.assertEqual(plan["nativeOffsets"], [])

    def test_dry_run_no_gil_drops_the_gil_channel(self):
        rc, out = self._run(["run", "--dry-run", "--no-gil"])
        self.assertNotIn("gil-hash", json.loads(out)["channels"])


# ---------------------------------------------------------------------------
class RealGilReadOnlyTests(unittest.TestCase):
    """REAL (read-only) probe of THIS machine's save root: reads a file, writes nothing."""

    def test_the_live_gil_sampler_reads_this_machine(self):
        root = oc.gil_save_root()
        if root is None:
            self.skipTest("no BeyondLocal save root on this machine")
        value = oc.value_gil_state(root)
        self.assertIsInstance(value, tuple)      # a present root -> a tuple (empty is legal)


# ---------------------------------------------------------------------------
class ModuleProbeProfileTests(unittest.TestCase):
    """The 2026-10-12 defect: the tool was hardwired to the OLD demo's literals.

    ``MW_API_MODPROBE`` prints a DIFFERENT seven-string set; a capture of it used to
    classify FOREIGN_PRINT with captured_literals == []. These pin the profile.
    """

    def _ev(self, rows, records=None):
        return synthetic(records=len(rows) if records is None else records, rows=rows)

    def test_a_probe_line_is_a_capture_not_foreign(self):
        ev = self._ev([oc.MODPROBE_PRINTS[0]])
        self.assertEqual(oc.classify_module_probe(ev), oc.OUT_MODPROBE)
        self.assertEqual(oc.exit_code_for(oc.OUT_MODPROBE), 0)
        # the OLD classifier is still blind to it -- that is why a profile exists
        self.assertEqual(oc.classify_outcome(ev), oc.OUT_FOREIGN)

    def test_probe_classifier_is_total(self):
        self.assertEqual(oc.classify_module_probe(self._ev([])), oc.OUT_NO_TRAFFIC)
        self.assertEqual(oc.classify_module_probe(self._ev([], records=3)), oc.OUT_NO_PRINT)
        self.assertEqual(oc.classify_module_probe(self._ev(["HELLO"])), oc.OUT_FOREIGN)
        self.assertEqual(oc.classify_module_probe(None), oc.OUT_UNUSABLE)
        self.assertEqual(oc.classify_module_probe({"ok": True}), oc.OUT_UNUSABLE)

    def test_a_prefix_attributes_the_modules_that_ran(self):
        ev = self._ev(list(oc.MODPROBE_PRINTS[:3]))          # entry, M4, M3
        cap = oc.module_probe_capture(ev)
        self.assertEqual(cap["capturedOrder"], list(oc.MODPROBE_PRINTS[:3]))
        self.assertEqual(cap["modulesRan"], ["entry", "M4-inventory", "M3-item"])
        self.assertEqual(cap["firstMissing"], oc.MODPROBE_PRINTS[3])
        self.assertFalse(cap["complete"])

    def test_the_full_set_is_complete_and_names_every_module(self):
        cap = oc.module_probe_capture(self._ev(list(oc.MODPROBE_PRINTS)))
        self.assertTrue(cap["complete"])
        self.assertEqual(cap["missing"], [])
        self.assertIsNone(cap["firstMissing"])
        self.assertEqual(cap["modulesRan"],
                         ["entry", "M4-inventory", "M3-item", "M2-currency",
                          "M1-interaction", "M5-shop", "end"])

    def test_foreign_lines_are_never_attributed(self):
        ev = self._ev([oc.MODPROBE_PRINTS[0], "SOME_OTHER_GRAPH"])
        cap = oc.module_probe_capture(ev)
        self.assertEqual(cap["capturedOrder"], [oc.MODPROBE_PRINTS[0]])
        self.assertEqual(cap["foreign"], ["SOME_OTHER_GRAPH"])

    def test_the_probe_string_set_is_unique_and_ordered(self):
        self.assertEqual(len(oc.MODPROBE_PRINTS), 7)
        self.assertEqual(len(set(oc.MODPROBE_PRINTS)), 7)
        self.assertEqual(oc.MODPROBE_PRINTS[0], "W29AI模块探针入口已触发")
        self.assertEqual(oc.MODPROBE_PRINTS[-1], "W29AI模块探针结束")
        self.assertEqual(oc.profile_expected_lines(oc.PROFILE_MODPROBE), oc.MODPROBE_PRINTS)
        self.assertEqual(oc.profile_expected_lines(oc.PROFILE_DEMO), ())

    def _probe_enable(self):
        return {"ok": True, "status": "native-log-enable-requested",
                "selection": {"Identity": "own-graphs-live:name-prefix=MW_",
                              "Ids": [1073741834],
                              "Graphs": [{"id": 1073741834, "name": oc.MODPROBE_GRAPH_NAME,
                                          "category": [10000, 20000, 21001, 0],
                                          "nodeCount": 13}]}}

    def test_orchestration_uses_the_profile_classifier(self):
        session = FakeSession(evidence=self._ev(list(oc.MODPROBE_PRINTS[:2])),
                              enable=self._probe_enable())
        cfgp = {"window": 120.0, "interval": 5.0,
                "graph_name": oc.MODPROBE_GRAPH_NAME, "graph_id": None,
                "profile": oc.PROFILE_MODPROBE}
        clock = FakeClock()
        result = oc.orchestrate(session, cfgp, sleep=clock.sleep, now=clock.now)
        self.assertEqual(result["profile"], oc.PROFILE_MODPROBE)
        self.assertEqual(result["outcome"], oc.OUT_MODPROBE)
        self.assertEqual(result["literals"], list(oc.MODPROBE_PRINTS[:2]))
        self.assertEqual(result["moduleCapture"]["modulesRan"], ["entry", "M4-inventory"])

    def test_the_result_block_prints_the_attribution(self):
        session = FakeSession(evidence=self._ev(list(oc.MODPROBE_PRINTS[:2])),
                              enable=self._probe_enable())
        cfgp = {"window": 120.0, "interval": 5.0,
                "graph_name": oc.MODPROBE_GRAPH_NAME, "graph_id": None,
                "profile": oc.PROFILE_MODPROBE}
        clock = FakeClock()
        result = oc.orchestrate(session, cfgp, sleep=clock.sleep, now=clock.now)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_result(result, ROOT)
        out = buf.getvalue()
        self.assertIn("MODULE PROBE ATTRIBUTION", out)
        self.assertIn("modules that RAN", out)
        self.assertIn("M4-inventory", out)
        self.assertIn("module lines captured", out)          # not the demo-literal label
        self.assertIn(oc.MODPROBE_PRINTS[0], out)

    def test_the_printed_line_set_survives_a_result_without_literals(self):
        """A hand-built result (no ``literals`` key) must not fall back to the DEMO literals."""
        result = {"runId": "x", "profile": oc.PROFILE_MODPROBE,
                  "outcome": oc.OUT_MODPROBE,
                  "evidence": self._ev(list(oc.MODPROBE_PRINTS[:2]))}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oc._print_result(result, ROOT)
        out = buf.getvalue()
        self.assertIn(oc.MODPROBE_PRINTS[0], out)
        self.assertNotIn("(none)", out.split("module lines captured:")[1].splitlines()[0])

    def test_the_demo_profile_still_defaults_when_no_profile_is_given(self):
        session = FakeSession(evidence=synthetic(records=1, rows=["作物不足"]))
        result, _ = run_orchestration(session)
        self.assertEqual(result["profile"], oc.PROFILE_DEMO)
        self.assertEqual(result["outcome"], oc.OUT_CAPTURED_DEFAULT)
        self.assertNotIn("moduleCapture", result)


class ProfileCliTests(unittest.TestCase):
    @staticmethod
    def _run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = oc.main(argv)
        return rc, buf.getvalue()

    def test_dry_run_defaults_to_the_module_probe_profile(self):
        rc, out = self._run(["run", "--dry-run"])
        self.assertEqual(rc, 0)
        plan = json.loads(out)
        self.assertEqual(plan["profile"], oc.PROFILE_MODPROBE)
        self.assertEqual(plan["graphName"], oc.MODPROBE_GRAPH_NAME)
        self.assertEqual(plan["expectedLines"], list(oc.MODPROBE_PRINTS))

    def test_dry_run_demo_profile_targets_the_old_graph(self):
        rc, out = self._run(["run", "--dry-run", "--expect", "demo"])
        plan = json.loads(out)
        self.assertEqual(plan["profile"], oc.PROFILE_DEMO)
        self.assertEqual(plan["graphName"], oc.DEFAULT_GRAPH_NAME)
        self.assertEqual(plan["expectedLines"], [])

    def test_an_explicit_empty_graph_name_still_disables_the_gate(self):
        rc, out = self._run(["run", "--dry-run", "--graph-name", ""])
        self.assertIsNone(json.loads(out)["graphName"])

    def test_an_explicit_graph_name_overrides_the_profile_default(self):
        rc, out = self._run(["run", "--dry-run", "--graph-name", "MW_API_OTHER"])
        self.assertEqual(json.loads(out)["graphName"], "MW_API_OTHER")

    def test_an_unknown_profile_is_refused_by_the_parser(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                oc.build_parser().parse_args(["run", "--expect", "nonsense"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
