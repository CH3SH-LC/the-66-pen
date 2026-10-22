#!/usr/bin/env python3
"""Offline tests for tools/editor-bridge/playtest_log.py.

WHAT IS REAL vs SYNTHETIC HERE
------------------------------
* REAL recorded fixtures (no machine contact, bytes already on disk):
    .runtime/editor-bridge/runs/10f68791-.../log-observer-evidence-response.json
        -> 5x packet 3006, recordsSeen=83, sample=64 (limited), 12 readable rows,
           5 distinct graph names. Captured 2026-09-28.
    .runtime/editor-bridge/runs/e8aa539c-.../log-observer-evidence-response.json
        -> zero packets, zero records. The negative case.
* SYNTHETIC documents, built from the documented payload shape
  (RunLogSample.cs: ``runLogSample.sample[].{observedUtc,graphName,bodyType,
  bodyTextReadable,bodyText}``). They are labelled ``synthetic`` in the docstring of
  each test that uses them so a green run is never mistaken for live evidence.

Run:  python tools/editor-bridge/tests/test_playtest_log.py
"""
import contextlib
import importlib.util
import io
import json
import pathlib
import re
import shlex
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "tools/editor-bridge/playtest_log.py"
DOC_PATH = ROOT / "tools/editor-bridge/PLAYTEST-LOG.md"
REAL_PRINTS = ROOT / ".runtime/editor-bridge/runs/10f68791-3a17-4cc9-ae11-e47ed9e81633/log-observer-evidence-response.json"
REAL_EMPTY = ROOT / ".runtime/editor-bridge/runs/e8aa539c-a1d1-4ca2-853a-07d841cca58a/log-observer-evidence-response.json"

spec = importlib.util.spec_from_file_location("playtest_log", MODULE_PATH)
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))


def synthetic(records, active=True, log_packets=None):
    """Synthetic evidence doc built from the documented shape. NOT recorded."""
    return {
        "ok": True,
        "active": active,
        "observedPackets": 16,
        "observedLogPackets": records if log_packets is None else log_packets,
        "runLogSample": {
            "recordsSeen": records,
            "recordsWithNoGraphName": 0,
            "sampleLimit": 64,
            "sampleLimited": False,
            "sample": [],
            "runtimeSemanticsVerified": False,
        },
    }


class RealFixtureTests(unittest.TestCase):
    """REAL recorded bytes already on disk - no machine involved."""

    def setUp(self):
        self.assertTrue(REAL_PRINTS.exists(), f"recorded fixture missing: {REAL_PRINTS}")
        self.ev = load(REAL_PRINTS)

    def test_verdict_is_prints_captured(self):
        self.assertEqual(pl.classify(self.ev), pl.VERDICT_PRINTS)

    def test_every_printed_string_is_rendered(self):
        rows = pl.iter_rows(self.ev)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({r["graph"] for r in rows}), 5)
        self.assertEqual(
            sorted({r["text"] for r in rows}),
            [
                "MW_CALIBRATION_PLATFORM_CREATED_20260916",
                "MW_CHARACTER_POSITION_NEXT_20260916",
                "MW_FINISH_MONITOR_STARTED_20260916",
                "MW_ROUTE_TILED_CREATED_20260916",
                "{0.0,1.0,0.0}",
            ],
        )

    def test_records_seen_counts_opaque_rows_too(self):
        # 83 records arrived; only 12 carried text. The gap is the whole point of
        # separating NO_PRINT from DID_NOT_RUN.
        self.assertEqual(pl.records_seen(self.ev), 83)
        self.assertGreater(pl.records_seen(self.ev), len(pl.iter_rows(self.ev)))

    def test_every_row_carries_timestamp_and_graph(self):
        for r in pl.iter_rows(self.ev):
            self.assertTrue(r["utc"].endswith("Z"))
            self.assertTrue(r["graph"])

    def test_never_claims_verification(self):
        rendered = pl.format_evidence(self.ev, as_json=True)
        doc = json.loads(rendered)
        self.assertFalse(doc["runtimeSemanticsVerified"])
        self.assertFalse(doc["playtestVerified"])
        self.assertFalse(doc["persistentSaveVerified"])


class RealNegativeFixtureTests(unittest.TestCase):
    """REAL recorded negative bytes: zero packets, zero records."""

    def setUp(self):
        self.assertTrue(REAL_EMPTY.exists(), f"recorded fixture missing: {REAL_EMPTY}")
        self.ev = load(REAL_EMPTY)

    def test_verdict_is_no_traffic(self):
        self.assertEqual(pl.classify(self.ev), pl.VERDICT_NO_TRAFFIC)
        self.assertEqual(pl.iter_rows(self.ev), [])

    def test_no_traffic_is_not_read_as_non_execution(self):
        text = pl.verdict_explanation(pl.VERDICT_NO_TRAFFIC, self.ev)
        self.assertIn("NOT proof", text)
        self.assertIn("logging was not enabled", text)


class SyntheticClassificationTests(unittest.TestCase):
    """SYNTHETIC docs built from the documented shape. Not recorded evidence."""

    def test_records_without_text_is_no_print(self):
        ev = synthetic(records=5)
        self.assertEqual(pl.classify(ev), pl.VERDICT_NO_PRINT)
        self.assertIn("none carried readable text", pl.verdict_explanation(pl.VERDICT_NO_PRINT, ev))

    def test_zero_records_is_no_traffic(self):
        self.assertEqual(pl.classify(synthetic(records=0)), pl.VERDICT_NO_TRAFFIC)

    def test_synthetic_text_renders(self):
        ev = synthetic(records=1)
        ev["runLogSample"]["sample"] = [{
            "observedUtc": "2026-10-11T00:00:00.0000000Z",
            "graphName": "graph-A",
            "bodyType": "T.Text",
            "bodyTextReadable": True,
            "bodyText": "HELLO_FROM_GRAPH",
            "runtimeSemanticsVerified": False,
        }]
        self.assertEqual(pl.classify(ev), pl.VERDICT_PRINTS)
        rendered = pl.format_evidence(ev, source="synthetic")
        self.assertIn("2026-10-11T00:00:00.0000000Z", rendered)
        self.assertIn("graph-A", rendered)
        self.assertIn("HELLO_FROM_GRAPH", rendered)

    def test_missing_fields_are_unusable(self):
        for bad in (None, {}, {"ok": True}, {"runLogSample": None}):
            self.assertEqual(pl.classify(bad), pl.VERDICT_UNUSABLE)

    def test_blank_body_text_is_not_a_print(self):
        ev = synthetic(records=1)
        ev["runLogSample"]["sample"] = [{"observedUtc": "Z", "graphName": "g",
                                         "bodyText": "", "bodyTextReadable": True}]
        self.assertEqual(pl.classify(ev), pl.VERDICT_NO_PRINT)


class FormatTests(unittest.TestCase):
    def test_header_and_columns(self):
        ev = synthetic(records=1)
        ev["runLogSample"]["sample"] = [{"observedUtc": "2026-10-11T01:02:03Z",
                                         "graphName": "G1", "bodyText": "X"}]
        lines = pl.format_evidence(ev, source="s").splitlines()
        self.assertIn("verdict: PRINTS_CAPTURED", lines)
        self.assertTrue(any("timestamp (UTC)" in ln and "graph" in ln for ln in lines))
        self.assertTrue(any(ln.startswith("2026-10-11T01:02:03Z") for ln in lines))

    def test_json_is_machine_readable(self):
        ev = synthetic(records=0)
        doc = json.loads(pl.format_evidence(ev, as_json=True))
        self.assertEqual(doc["verdict"], pl.VERDICT_NO_TRAFFIC)
        self.assertEqual(doc["rows"], [])
        self.assertIn("explanation", doc)


class ValidationTests(unittest.TestCase):
    def test_lease_refused_by_name(self):
        with self.assertRaises(ValueError) as cm:
            pl.validate_watch_args("bogus-lease", 3.0)
        self.assertIn("LEASE_NOT_ALLOWED", str(cm.exception))

    def test_interval_range(self):
        with self.assertRaises(ValueError):
            pl.validate_watch_args(pl.OP_START_LONG, 0.1)
        with self.assertRaises(ValueError):
            pl.validate_watch_args(pl.OP_START_LONG, 120.0)

    def test_window_capped_by_lease(self):
        cfg = pl.validate_watch_args(pl.OP_START_SHORT, 3.0, seconds=999)
        self.assertEqual(cfg["window"], 25.0)
        cfg = pl.validate_watch_args(pl.OP_START_LONG, 3.0, seconds=10)
        self.assertEqual(cfg["window"], 10.0)

    def test_run_id_shape(self):
        self.assertEqual(pl.validate_run_id(None), "")
        self.assertEqual(pl.validate_run_id("10f68791-3a17-4cc9-ae11-e47ed9e81633"),
                         "10f68791-3a17-4cc9-ae11-e47ed9e81633")
        with self.assertRaises(ValueError):
            pl.validate_run_id("not-a-guid")

    def test_request_id_is_function_of_request_and_seq_distinct(self):
        a = pl.request_id_for(pl.OP_EVIDENCE, "10f68791-3a17-4cc9-ae11-e47ed9e81633", 1)
        b = pl.request_id_for(pl.OP_EVIDENCE, "10f68791-3a17-4cc9-ae11-e47ed9e81633", 1)
        c = pl.request_id_for(pl.OP_EVIDENCE, "10f68791-3a17-4cc9-ae11-e47ed9e81633", 2)
        self.assertEqual(a, b)            # same request -> same id
        self.assertNotEqual(a, c)         # different poll -> different id
        # Exactly 32 hex: the runner's _request_id refuses any other length.
        self.assertRegex(a, r"^[0-9a-f]{32}$")


class WatchSequenceTests(unittest.TestCase):
    """Drive the sequence with a fake runner. No queue, no machine."""

    class FakeRunner:
        def __init__(self, evidence):
            self.ops = []
            self.run_id = "10f68791-3a17-4cc9-ae11-e47ed9e81633"
            self.evidence = evidence

        def call(self, op, dry_run=False):
            self.ops.append(op)
            if op == pl.OP_EVIDENCE:
                return self.evidence
            return {"ok": True, "op": op}

    @staticmethod
    def _clock():
        """Monotonic fake clock that advances 5 s per read, so the poll loop ends."""
        state = {"t": 0.0}

        def now():
            state["t"] += 5.0
            return state["t"]
        return now

    def _cfg(self):
        # seconds=1 caps the window to 1 s, so the second clock read always breaks.
        return pl.validate_watch_args(pl.OP_START_LONG, 1.0, seconds=1)

    def test_op_order_start_enable_evidence_stop(self):
        runner = self.FakeRunner(synthetic(records=0))
        pl.watch(runner, self._cfg(), enable=True, dry_run=False,
                 sleep=lambda _s: None, now=self._clock())
        self.assertEqual(runner.ops[0], pl.OP_START_LONG)
        self.assertEqual(runner.ops[1], pl.OP_ENABLE)
        self.assertEqual(runner.ops[-1], pl.OP_STOP)
        self.assertIn(pl.OP_EVIDENCE, runner.ops)

    def test_no_enable_skips_enable(self):
        runner = self.FakeRunner(synthetic(records=0))
        pl.watch(runner, self._cfg(), enable=False, dry_run=False,
                 sleep=lambda _s: None, now=self._clock())
        self.assertNotIn(pl.OP_ENABLE, runner.ops)

    def test_real_fixture_flows_through_watch(self):
        runner = self.FakeRunner(load(REAL_PRINTS))
        ev = pl.watch(runner, self._cfg(), enable=True, dry_run=False,
                      sleep=lambda _s: None, now=self._clock())
        self.assertEqual(pl.classify(ev), pl.VERDICT_PRINTS)
        self.assertEqual(len(pl.iter_rows(ev)), 12)


class DocumentedInvocationTests(unittest.TestCase):
    """Stops the recurring bug where the runbook names a flag argparse does not have.

    This is not a unit test of a helper: it reads the invocation lines *out of the real
    doc file and the real module docstring* and pushes each through the REAL parser
    (``pl.build_parser()``). A doc edit that invents a flag makes this class fail. The
    placeholder ``<...>`` in the offline example is replaced by a concrete token -- only
    the placeholder is substituted; the flags are exercised verbatim.
    """
    INVOCATION_RE = re.compile(r"python\s+\S*playtest_log\.py\s+[^`\n]*")

    @classmethod
    def _invocations(cls):
        self = cls
        text = DOC_PATH.read_text(encoding="utf-8") + "\n" + (pl.__doc__ or "")
        out = []
        for m in self.INVOCATION_RE.finditer(text):
            out.append(re.sub(r"<[^>]*>", "PLACEHOLDER", m.group(0)).strip())
        return out

    @staticmethod
    def _argv_after_script(cmd):
        toks = shlex.split(cmd)
        i = next(j for j, t in enumerate(toks) if t.endswith("playtest_log.py"))
        return toks[i + 1:]

    @staticmethod
    def _script_token(cmd):
        """The path token that names the script -- the part _argv_after_script drops."""
        return next(t for t in shlex.split(cmd) if t.endswith("playtest_log.py"))

    def test_documented_script_path_resolves_from_the_project_root(self):
        # The bare-path defect this class could not see: `python playtest_log.py watch`
        # parses perfectly through the real parser (the path prefix is stripped before
        # parse_args) yet exits 2 with "can't open file" when run from the project root.
        # The parser test above therefore can never catch it. What DOES catch it is
        # resolving the documented path token against the project root and requiring it
        # to be the real module file. Before the fix the docstring's two bare-path lines
        # resolved to <root>/playtest_log.py, which does not exist -> this fails.
        inv = self._invocations()
        self.assertTrue(inv, "no documented invocations found")
        for cmd in inv:
            token = self._script_token(cmd)
            resolved = (ROOT / token).resolve()
            self.assertTrue(
                resolved.is_file(),
                f"documented script path does not resolve from the project root: "
                f"{token!r} in {cmd!r} -> {resolved}")
            self.assertEqual(resolved, MODULE_PATH,
                             f"documented invocation names the wrong script: {cmd!r}")

    def test_doc_keeps_both_a_live_and_an_offline_invocation(self):
        inv = self._invocations()
        self.assertTrue(any(" watch" in c for c in inv), f"no live command found in {inv}")
        self.assertTrue(any(" render" in c for c in inv), f"no offline command found in {inv}")

    def test_every_documented_invocation_parses_through_the_real_parser(self):
        parser = pl.build_parser()
        parsed = []
        for cmd in self._invocations():
            with contextlib.redirect_stderr(io.StringIO()):
                ns = parser.parse_args(self._argv_after_script(cmd))  # SystemExit(2) => fail
            parsed.append(ns)
        self.assertTrue(parsed)

    def test_documented_watch_command_enables_by_default(self):
        # The live doc command carries no enable/disable flag on purpose: `watch`
        # enables own-graph logging by default, which is what makes the documented
        # line correct. If someone documents `--no-enable` as the live command, this
        # fails -- that would silently ship a capture that sees nothing.
        parser = pl.build_parser()
        watches = [c for c in self._invocations() if " watch" in c]
        self.assertTrue(watches, "documented `watch` command disappeared")
        for cmd in watches:
            with contextlib.redirect_stderr(io.StringIO()):
                ns = parser.parse_args(self._argv_after_script(cmd))
            self.assertFalse(ns.no_enable, f"live command disables logging: {cmd}")

    def test_no_documented_invocation_uses_the_nonexistent_enable_flag(self):
        for cmd in self._invocations():
            self.assertNotRegex(cmd, r"(?<!-)-{2}enable\b", cmd)

    def test_enable_flag_is_refused_by_the_parser(self):
        # Closes the bug: the flag simply does not exist; enable is the default.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                pl.build_parser().parse_args(["watch", "--enable"])


class CliExitCodeTests(unittest.TestCase):
    """The exit-code contract, driven through main() with real recorded bytes."""

    @staticmethod
    def _run(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = pl.main(argv)
        return rc, buf.getvalue()

    def test_render_real_prints_is_exit_zero(self):
        rc, out = self._run(["render", "--evidence", str(REAL_PRINTS)])
        self.assertEqual(rc, 0)
        self.assertIn("verdict: PRINTS_CAPTURED", out)

    def test_render_real_negative_is_exit_one(self):
        rc, out = self._run(["render", "--evidence", str(REAL_EMPTY)])
        self.assertEqual(rc, 1)
        self.assertIn("verdict: NO_LOG_TRAFFIC", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
