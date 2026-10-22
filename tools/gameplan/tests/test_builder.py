"""Offline tests for the graph builder — a fake bridge, no editor, no game.

The fake is :class:`tools.gameplan.testing.FakeBridge`, the one reusable model of
the bridge's documented semantics (status strings, journal replay/conflict, lease
expiry).  Sequence/lease/read-back failures live in ``test_testing.py``; this file
keeps the original per-step and batched-path assertions.
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.builder import (
    PRIOR_ATTEMPT_INCOMPLETE,
    BuildResult,
    GraphBuilder,
    _tagged,
    prior_build_plan_attempts,
    request_id,
)
from tools.gameplan.testing import (
    REFUSAL_NODE_COUNT_CONFLICT,
    FakeBridge,
)

_run = lambda argv: FakeBridge.action_of(argv)  # noqa: E731 - reads a recorded argv


def small_plan(name="MW_API_test_build"):
    g = Graph(name)
    a = g.place(N.ON_CREATE, "a")
    b = g.place(N.ADD_BAG_CURRENCY, "b")
    a.flow_to(b)
    b.data_from(a, "entity", "holder")
    b.const("currency", 1115684864, "int")
    b.const("delta", 10, "int")
    return g.plan


def write_attempt(root, request_id_, name, *, result=None, action="build-plan"):
    """A journal entry as ``author.py`` writes it: a claim, then (maybe) a result.

    ``claim.json`` is written before the dispatch (``author.py:376-378``) and
    ``result.json`` after it (``author.py:396``); leaving ``result`` as ``None``
    models a process that died mid-dispatch.
    """
    import json
    from pathlib import Path

    entry = Path(root) / request_id_
    entry.mkdir(parents=True)
    (entry / "claim.json").write_text(json.dumps({
        "sha256": "0" * 64,
        "command": {"backend": "graph", "mutating": True,
                    "payload": {"action": action, "name": name, "graphId": 1073741900}},
        "startedUtc": "2026-01-01T00:00:00+00:00",
    }), encoding="utf-8")
    if result is not None:
        (entry / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return entry


class TestRequestId(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(request_id("a", 1), request_id("a", 1))

    def test_changes_with_request(self):
        self.assertNotEqual(request_id("a", 1), request_id("a", 2))

    def test_shape(self):
        value = request_id("x")
        self.assertEqual(len(value), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in value))


class TestTagged(unittest.TestCase):
    def test_slots(self):
        self.assertEqual(_tagged("int", 3), '{"int": 3}')
        self.assertEqual(_tagged("uint", 3), '{"uint": 3}')
        self.assertEqual(_tagged("enum", 3), '{"uint": 3}')
        self.assertEqual(_tagged("bool", True), '{"bool": true}')
        self.assertEqual(_tagged("float", 1.5), '{"float": 1.5}')
        self.assertEqual(_tagged("string", "x"), '{"string": "x"}')

    def test_auto_infers(self):
        self.assertEqual(_tagged("auto", True), '{"bool": true}')
        self.assertEqual(_tagged("auto", 5), '{"int": 5}')
        self.assertEqual(_tagged("auto", 1.0), '{"float": 1.0}')

    def test_unknown_slot_rejected(self):
        with self.assertRaises(ValueError):
            _tagged("nope", 1)


class TestBuildSequence(unittest.TestCase):
    def _build(self, runner, **kwargs):
        plan = small_plan()
        builder = GraphBuilder(plan, runner, run_id="7588c713-fb80-433a-afce-c0f89cf13d96", **kwargs)
        return builder.build()

    def test_happy_path(self):
        runner = FakeBridge()
        result = self._build(runner)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.graph_id, 1073741900)
        self.assertEqual(result.node_ids, {"a": 1, "b": 2})
        actions = [_run(c) for c in runner.calls]
        self.assertEqual(actions, ["create", "lookup", "add", "add", "value", "value",
                                   "wire", "wire", "export"])

    def test_elevated_queue_precedes_graph(self):
        runner = FakeBridge()
        self._build(runner)
        for argv in runner.calls:
            self.assertEqual(argv[argv.index("graph") - 2], "--elevated-queue")

    def test_add_expected_counts_are_cumulative(self):
        runner = FakeBridge()
        self._build(runner)
        adds = [c for c in runner.calls if _run(c) == "add"]
        self.assertEqual([c[c.index("--expected-node-count") + 1] for c in adds], ["0", "1"])
        self.assertEqual([c[c.index("--definition-id") + 1] for c in adds], ["71", "688"])

    def test_edges_wired_by_instance_id(self):
        runner = FakeBridge()
        self._build(runner)
        wires = [c for c in runner.calls if _run(c) == "wire"]
        self.assertEqual(len(wires), 2)  # one execution edge, one data edge
        get = lambda argv, flag: argv[argv.index(flag) + 1]
        exec_wire, data_wire = wires
        for wire in wires:
            self.assertEqual(get(wire, "--from-node-id"), "1")   # node a
            self.assertEqual(get(wire, "--to-node-id"), "2")     # node b
        # execution edge: 2:0 -> 1:0
        self.assertEqual((get(exec_wire, "--from-port-kind"), get(exec_wire, "--to-port-kind")), ("2", "1"))
        self.assertEqual((get(exec_wire, "--from-port-index"), get(exec_wire, "--to-port-index")), ("0", "0"))
        # data edge: 4:0 -> 3:0
        self.assertEqual((get(data_wire, "--from-port-kind"), get(data_wire, "--to-port-kind")), ("4", "3"))

    def test_expect_derived_from_contract(self):
        runner = FakeBridge()
        self._build(runner)
        value = [c for c in runner.calls if _run(c) == "value"][0]
        get = lambda flag: value[value.index(flag) + 1]
        # 688 3:1 is 货币配置ID: contract serverParamType 20, genericId 20.
        self.assertEqual(get("--port-index"), "1")
        self.assertEqual(get("--expect-server-param-type"), "20")
        self.assertEqual(get("--expect-generic-id"), "20")

    def test_request_ids_are_functions_of_the_request(self):
        first = FakeBridge()
        self._build(first)
        second = FakeBridge()
        self._build(second)
        ids1 = [c[c.index("--request-id") + 1] for c in first.calls]
        ids2 = [c[c.index("--request-id") + 1] for c in second.calls]
        self.assertEqual(ids1, ids2)
        self.assertEqual(len(set(ids1)), len(ids1))

    def test_bind_when_entity_supplied(self):
        runner = FakeBridge()
        result = self._build(runner, entity_id=1077936216)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(_run(runner.calls[-1]), "bind")
        bind = runner.calls[-1]
        self.assertEqual(bind[bind.index("--entity-id") + 1], "1077936216")
        self.assertEqual(bind[bind.index("--expected-node-count") + 1], "2")

    def test_no_bind_without_entity(self):
        runner = FakeBridge()
        self._build(runner)
        self.assertNotIn("bind", [_run(c) for c in runner.calls])

    def test_failure_stops_the_build(self):
        # An add refused by the adapter (its real code is AUTHOR_NODE_COUNT_CONFLICT).
        runner = FakeBridge(refuse={"add": REFUSAL_NODE_COUNT_CONFLICT})
        result = self._build(runner)
        self.assertFalse(result.ok)
        self.assertIn("add", result.error)
        # Nothing past the failing add is attempted.
        self.assertNotIn("wire", [_run(c) for c in runner.calls])

    def test_invalid_plan_never_dispatches(self):
        runner = FakeBridge()
        plan = small_plan()
        plan.name = "bad name"
        result = GraphBuilder(plan, runner, run_id="x").build()
        self.assertFalse(result.ok)
        self.assertEqual(runner.calls, [])

    def test_evidence_shape(self):
        runner = FakeBridge()
        result = self._build(runner)
        evidence = result.evidence()
        self.assertEqual(evidence["graphId"], 1073741900)
        self.assertEqual(evidence["nodeIds"], {"a": 1, "b": 2})
        self.assertTrue(all("requestId" in s for s in evidence["steps"]))


class TestOpBudget(unittest.TestCase):
    """The bridge scope's lease caps a run; the budget makes a run resumable."""

    def test_stops_cleanly_after_max_ops(self):
        runner = FakeBridge()
        builder = GraphBuilder(small_plan(), runner, run_id="r", max_ops=3)
        result = builder.build()
        self.assertFalse(result.ok)
        self.assertTrue(result.partial)
        self.assertEqual([_run(c) for c in runner.calls], ["create", "lookup", "add"])
        self.assertIn("op budget", result.error)

    def test_replays_do_not_consume_budget(self):
        # Prime the journal with a full run, then a budgeted rerun is all replays.
        runner = FakeBridge()
        self.assertTrue(GraphBuilder(small_plan(), runner, run_id="r").build().ok)
        result = GraphBuilder(small_plan(), runner, run_id="r", max_ops=2).build()
        self.assertTrue(result.ok, result.error)  # replays are free, so it finishes
        self.assertFalse(result.partial)

    def test_no_budget_runs_to_completion(self):
        result = GraphBuilder(small_plan(), FakeBridge(), run_id="r").build()
        self.assertTrue(result.ok)
        self.assertFalse(result.partial)


class TestBatchBuild(unittest.TestCase):
    def test_batch_plan_json_shape(self):
        builder = GraphBuilder(small_plan(), FakeBridge(), run_id="r")
        plan = builder.batch_plan_json()
        self.assertEqual([n["definitionId"] for n in plan["nodes"]], [71, 688])
        # node references are indices, not aliases
        self.assertEqual(plan["edges"][0]["from"], 0)
        self.assertEqual(plan["edges"][0]["to"], 1)
        self.assertEqual(plan["values"][0], {"node": 1, "portIndex": 1, "slot": "int", "value": {"int": 1115684864}})

    def test_batch_build_dispatches_create_lookup_build_inspect_export(self):
        runner = FakeBridge()
        result = GraphBuilder(small_plan(), runner, run_id="r").build_batch()
        self.assertTrue(result.ok, result.error)
        self.assertEqual([_run(c) for c in runner.calls],
                         ["create", "lookup", "build-plan", "inspect", "export"])
        self.assertEqual(len(result.node_ids), 2)

    def test_batch_detects_a_readback_mismatch(self):
        # The editor came back with a different node than the plan asked for.
        runner = FakeBridge(readback_definitions=[71, 1])
        result = GraphBuilder(small_plan(), runner, run_id="r").build_batch()
        self.assertFalse(result.ok)
        self.assertIn("readback mismatch", result.error)

    def test_batch_invalid_plan_never_dispatches(self):
        runner = FakeBridge()
        plan = small_plan()
        plan.name = "bad"
        result = GraphBuilder(plan, runner, run_id="r").build_batch()
        self.assertFalse(result.ok)
        self.assertEqual(runner.calls, [])

    def test_batch_writes_the_plan_file(self):
        import json
        import tempfile
        from pathlib import Path
        runner = FakeBridge()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "p.json"
            builder = GraphBuilder(small_plan(), runner, run_id="r")
            builder.build_batch(plan_path=out)
            self.assertTrue(out.is_file())
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(written["nodes"]), 2)


class TestBatchCrashSafety(unittest.TestCase):
    """A half-built graph must be DETECTABLE, not silently rebuilt.

    The adapter spends its attempt before the first native mutation
    (``AuthoringGraph.cs:756``) and only records ``author-plan-ready`` once every
    node/edge/value has landed (``AuthoringGraph.cs:819``).  A process that dies in
    between leaves the request journal with a claim and no successful result -- the
    only durable trace.  ``build_batch`` reads it and REFUSES (there is no working
    graph delete); a prior SUCCESS is merely reported as replay-safe.
    """

    def _batch(self, runner, journal, **kwargs):
        builder = GraphBuilder(small_plan(), runner, run_id="r", journal_dir=journal, **kwargs)
        return builder.build_batch()

    def test_first_attempt_proceeds(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeBridge()
            result = self._batch(runner, Path(tmp))
            self.assertTrue(result.ok, result.error)
            self.assertFalse(result.replay_safe)
            self.assertEqual(result.prior_attempts, [])
            self.assertIn("build-plan", [_run(c) for c in runner.calls])

    def test_spoiled_previous_attempt_refuses_before_dispatching(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)
            write_attempt(journal, "a" * 32, small_plan().name,
                          result={"ok": False, "error": "AUTHOR_PLAN_LINK_REJECTED"})
            runner = FakeBridge()
            result = self._batch(runner, journal)
            self.assertFalse(result.ok)
            self.assertIn(PRIOR_ATTEMPT_INCOMPLETE, result.error)
            self.assertEqual(runner.calls, [])              # refused BEFORE any dispatch
            self.assertEqual(len(result.prior_attempts), 1)
            self.assertFalse(result.prior_attempts[0]["ok"])
            self.assertIn(PRIOR_ATTEMPT_INCOMPLETE, result.evidence()["error"])

    def test_claim_without_a_result_is_spoiled_too(self):
        # The claim is written before the dispatch (author.py:376-378); a crash after
        # it leaves no result.json -- outcome UNKNOWN (author.py:380).
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)
            write_attempt(journal, "b" * 32, small_plan().name, result=None)
            runner = FakeBridge()
            result = self._batch(runner, journal)
            self.assertFalse(result.ok)
            self.assertIn(PRIOR_ATTEMPT_INCOMPLETE, result.error)
            self.assertEqual(runner.calls, [])
            self.assertFalse(result.prior_attempts[0]["outcomeKnown"])

    def test_clean_previous_attempt_is_reported_replay_safe(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)
            write_attempt(journal, "c" * 32, small_plan().name, result={"ok": True})
            runner = FakeBridge()
            result = self._batch(runner, journal)
            self.assertTrue(result.ok, result.error)
            self.assertTrue(result.replay_safe)
            self.assertTrue(result.evidence()["replaySafe"])
            self.assertEqual(len(result.prior_attempts), 1)
            self.assertTrue(result.prior_attempts[0]["ok"])

    def test_a_different_graph_name_is_ignored(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)
            write_attempt(journal, "d" * 32, "MW_API_other_graph", result={"ok": False})
            runner = FakeBridge()
            result = self._batch(runner, journal)
            self.assertTrue(result.ok, result.error)
            self.assertFalse(result.replay_safe)
            self.assertEqual(result.prior_attempts, [])

    def test_a_non_build_plan_action_is_ignored(self):
        # Only the build-plan step records the attempt the adapter spends before the
        # first native mutation; a create/export for the same name is not that step.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)
            write_attempt(journal, "e" * 32, small_plan().name, action="create",
                          result={"ok": False})
            runner = FakeBridge()
            result = self._batch(runner, journal)
            self.assertTrue(result.ok, result.error)
            self.assertFalse(result.replay_safe)

    def test_helper_reads_only_matching_names(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)
            write_attempt(journal, "f" * 32, small_plan().name, result={"ok": True})
            write_attempt(journal, "0" * 32, "MW_API_elsewhere", result={"ok": False})
            attempts = prior_build_plan_attempts(journal, small_plan().name)
            self.assertEqual([a["requestId"] for a in attempts], ["f" * 32])


if __name__ == "__main__":
    unittest.main()
