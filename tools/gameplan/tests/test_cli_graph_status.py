"""Offline tests for ``cli.py graph-status`` — a fake runner, no bridge, no game.

Two layers are tested:

* :func:`tools.gameplan.cli.diff_node_lists` — the pure diff, on its own.
* :func:`tools.gameplan.cli.cmd_graph_status` — the command, driven through a
  fake runner injected exactly the way ``test_builder.py`` injects one into
  :class:`GraphBuilder`.  Every test asserts that the command dispatched
  ``graph inspect`` and **nothing else**; it is read-only by contract.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan import cli
from tools.gameplan.cli import diff_node_lists

RUN = "7588c713-fb80-433a-afce-c0f89cf13d96"
NAME = "MW_API_TEST_STATUS"
GRAPH_ID = 1073741900


class FakeRunner:
    """Answers ``graph inspect`` like the adapter would; records every argv."""

    def __init__(self, defs, *, bound=None, ok=True, error=None):
        self.defs = list(defs)
        self.bound = list(bound or [])
        self.ok = ok
        self.error = error
        self.calls: list[list[str]] = []

    @staticmethod
    def _action(argv):
        return argv[argv.index("graph") + 1]

    def __call__(self, argv):
        self.calls.append(list(argv))
        if not self.ok:
            return {"ok": False, "error": self.error or "synthetic inspect failure"}
        return {"ok": True, "backend": {
            "status": "editor-model-readback",
            "nodeCount": len(self.defs),
            "nodes": [{"nodeId": i + 1, "definitionId": d} for i, d in enumerate(self.defs)],
            "boundEntityIds": list(self.bound),
        }}


def write_plan(scratch: Path, name: str, defs, *, edges=0, values=0) -> Path:
    scratch.mkdir(parents=True, exist_ok=True)
    plan = {
        "nodes": [{"definitionId": d, "x": 0, "y": 0} for d in defs],
        "edges": [{"from": 0, "to": 1, "fromKind": 2, "fromIndex": 0,
                   "toKind": 1, "toIndex": 0} for _ in range(edges)],
        "values": [{"node": 0, "portIndex": 1, "slot": "int", "value": {"int": 1}}
                   for _ in range(values)],
    }
    path = scratch / f"{name}-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def run_status(argv, runner=None):
    """Parse argv, run the command, and return (exit code, parsed stdout JSON)."""
    args = cli.build_parser().parse_args(argv)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.cmd_graph_status(args, runner=runner)
    text = buf.getvalue().strip()
    return code, (json.loads(text) if text else None)


def status_argv(scratch, *, graph_id=GRAPH_ID, run_id=RUN, name=NAME, extra=()):
    return ["graph-status", "--graph-id", str(graph_id), "--run-id", run_id,
            "--name", name, "--scratch-dir", str(scratch),
            "--queue-dir", str(Path(scratch) / "queue"), *extra]


class TestDiffNodeLists(unittest.TestCase):
    def test_clean_when_identical(self):
        diff = diff_node_lists([71, 688], [71, 688])
        self.assertTrue(diff["clean"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertFalse(diff["reordered"])

    def test_reports_a_missing_node(self):
        diff = diff_node_lists([71, 688, 79], [71, 79])
        self.assertFalse(diff["clean"])
        self.assertEqual(diff["removed"], [688])
        self.assertEqual(diff["added"], [])
        self.assertFalse(diff["reordered"])

    def test_reports_an_added_node(self):
        diff = diff_node_lists([71], [71, 688])
        self.assertFalse(diff["clean"])
        self.assertEqual(diff["added"], [688])
        self.assertEqual(diff["removed"], [])

    def test_reports_a_reordering(self):
        diff = diff_node_lists([71, 688], [688, 71])
        self.assertFalse(diff["clean"])
        self.assertTrue(diff["reordered"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["orderMismatches"],
                         [{"index": 0, "planned": 71, "inspected": 688},
                          {"index": 1, "planned": 688, "inspected": 71}])

    def test_reordering_is_reported_even_with_a_change(self):
        diff = diff_node_lists([71, 688], [688, 71, 79])
        self.assertTrue(diff["reordered"])
        self.assertEqual(diff["added"], [79])

    def test_duplicates_use_multiset_not_set_arithmetic(self):
        # Two identical nodes must not read as clean when the editor holds one.
        diff = diff_node_lists([71, 71], [71])
        self.assertFalse(diff["clean"])
        self.assertEqual(diff["removed"], [71])

    def test_duplicate_reorder_is_detected(self):
        diff = diff_node_lists([71, 688, 71], [71, 71, 688])
        self.assertTrue(diff["reordered"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])


class TestGraphStatusCli(unittest.TestCase):
    def test_reports_clean_against_a_matching_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            write_plan(scratch, NAME, [71, 688], edges=2, values=2)
            runner = FakeRunner([71, 688], bound=[1077936215])
            code, payload = run_status(status_argv(scratch), runner)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["readOnly"])
        self.assertTrue(payload["diff"]["clean"])
        self.assertEqual(payload["diff"]["added"], [])
        self.assertEqual(payload["diff"]["removed"], [])
        self.assertFalse(payload["diff"]["reordered"])
        self.assertEqual(payload["inspect"]["nodeDefinitionIds"], [71, 688])
        self.assertEqual(payload["inspect"]["boundEntityIds"], [1077936215])
        self.assertTrue(payload["plan"]["found"])
        self.assertEqual(payload["plan"]["edges"], 2)
        self.assertEqual(payload["plan"]["values"], 2)

    def test_reordered_graph_exits_nonzero_with_a_reordering(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            write_plan(scratch, NAME, [71, 688])
            runner = FakeRunner([688, 71])
            code, payload = run_status(status_argv(scratch), runner)
        self.assertEqual(code, 4)
        self.assertTrue(payload["diff"]["reordered"])
        self.assertEqual(payload["diff"]["added"], [])
        self.assertEqual(payload["diff"]["removed"], [])

    def test_missing_node_is_reported_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            write_plan(scratch, NAME, [71, 688, 79])
            runner = FakeRunner([71, 79])
            code, payload = run_status(status_argv(scratch), runner)
        self.assertEqual(code, 4)
        self.assertEqual(payload["diff"]["removed"], [688])
        self.assertFalse(payload["diff"]["reordered"])

    def test_without_a_plan_the_inspect_still_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)          # no <name>-plan.json written
            runner = FakeRunner([71, 688])
            code, payload = run_status(status_argv(scratch), runner)
        self.assertEqual(code, 0)
        self.assertIsNone(payload["diff"])
        self.assertFalse(payload["plan"]["found"])
        self.assertEqual(len(runner.calls), 1)          # read-only, but it did read

    def test_unreadable_plan_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            scratch.mkdir(parents=True, exist_ok=True)
            (scratch / f"{NAME}-plan.json").write_text("{ not json", encoding="utf-8")
            runner = FakeRunner([71])
            code, payload = run_status(status_argv(scratch), runner)
        self.assertEqual(code, 0)
        self.assertTrue(payload["plan"]["found"])
        self.assertIn("error", payload["plan"])
        self.assertIsNone(payload["diff"])

    def test_dispatches_inspect_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            write_plan(scratch, NAME, [71])
            runner = FakeRunner([71])
            run_status(status_argv(scratch), runner)
        self.assertEqual(len(runner.calls), 1)
        argv = runner.calls[0]
        self.assertEqual(argv[argv.index("graph") + 1], "inspect")
        for forbidden in ("create", "add", "wire", "value", "bind", "build-plan", "export"):
            self.assertNotIn(forbidden, argv)
        # --elevated-queue is global and must precede the `graph` subcommand.
        self.assertEqual(argv[argv.index("graph") - 2], "--elevated-queue")

    def test_request_id_is_a_function_of_the_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            first = FakeRunner([71])
            _, a = run_status(status_argv(scratch), first)
            second = FakeRunner([71])
            _, b = run_status(status_argv(scratch), second)
            third = FakeRunner([71])
            _, c = run_status(status_argv(scratch, graph_id=GRAPH_ID + 1), third)
        self.assertEqual(a["requestId"], b["requestId"])
        self.assertNotEqual(a["requestId"], c["requestId"])

    def test_requires_an_explicit_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["graph-status", "--graph-id", str(GRAPH_ID), "--name", NAME,
                    "--scratch-dir", tmp]
            with self.assertRaises(SystemExit) as raised:
                cli.build_parser().parse_args(argv)
        self.assertEqual(raised.exception.code, 2)

    def test_invalid_run_id_is_refused_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner([71])
            code, payload = run_status(
                status_argv(Path(tmp), run_id="not-a-uuid"), runner)
        self.assertEqual(code, 2)
        self.assertIsNone(payload)
        self.assertEqual(runner.calls, [])

    def test_refuses_without_a_name_and_never_dispatches(self):
        # author.py graph inspect is keyed by name; a bare graph id cannot read it.
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["graph-status", "--graph-id", str(GRAPH_ID), "--run-id", RUN,
                    "--scratch-dir", tmp]
            args = cli.build_parser().parse_args(argv)
            runner = FakeRunner([71])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.cmd_graph_status(args, runner=runner)
        self.assertEqual(code, 2)
        self.assertEqual(runner.calls, [])

    def test_rejects_a_malformed_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner([71])
            code, payload = run_status(
                status_argv(Path(tmp), name="bad name"), runner)
        self.assertEqual(code, 2)
        self.assertIsNone(payload)
        self.assertEqual(runner.calls, [])

    def test_inspect_failure_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            write_plan(scratch, NAME, [71])
            runner = FakeRunner([], ok=False, error="AUTHOR_GRAPH_IDENTITY_MISMATCH")
            code, payload = run_status(status_argv(scratch), runner)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("AUTHOR_GRAPH_IDENTITY_MISMATCH", payload["error"])
        self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
