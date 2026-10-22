"""Tests for the offline fake bridge itself, and that builder.py detects its failures.

`FakeBridge` is only useful if it is faithful AND if the builder reacts to the
states it can produce.  So this file checks both:

* the fake answers with the documented status strings / envelopes (direct calls);
* a lease that dies mid-sequence, a read-back that disagrees with the plan, and a
  request-id conflict are all DETECTED by ``builder.py`` -- not swallowed;
* a clean run returns ``ok``.

No bridge, no game, no queue.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.builder import GraphBuilder
from tools.gameplan.testing import (
    ERROR_LEASE_REFUSED,
    ERROR_REQUEST_ID_CONFLICT,
    REFUSAL_BOUND_GRAPH_EDIT_REFUSED,
    REFUSAL_GRAPH_IDENTITY_MISMATCH,
    REFUSAL_NODE_COUNT_CONFLICT,
    REFUSAL_VALUE_TYPE_MISMATCH,
    STATUS_ADDED,
    STATUS_BINDING_PENDING,
    STATUS_CREATE_PENDING,
    STATUS_EDITOR_MODEL_READBACK,
    STATUS_EXPORT_INVOKED,
    STATUS_LOOKUP_PENDING,
    STATUS_PLAN_BUILT,
    FakeBridge,
)

RUN_ID = "7588c713-fb80-433a-afce-c0f89cf13d96"


def small_plan(name="MW_API_test_build", bx=0):
    """The same two-node plan test_builder.py uses: 71 -> 688 with two int consts."""
    g = Graph(name)
    a = g.place(N.ON_CREATE, "a")
    b = g.place(N.ADD_BAG_CURRENCY, "b", x=bx)
    a.flow_to(b)
    b.data_from(a, "entity", "holder")
    b.const("currency", 1115684864, "int")
    b.const("delta", 10, "int")
    return g.plan


def argv(action, **flags):
    """A builder-shaped argv: global flags, then ``graph <action>`` and pairs."""
    parts = ["python", "-B", "author.py", "--elevated-queue", "Q", "graph", action]
    for key, value in flags.items():
        parts += ["--" + key.replace("_", "-"), str(value)]
    return parts


class TestStatusStringsAreFaithful(unittest.TestCase):
    """The fake must answer with the exact strings the adapter documents."""

    def test_create_is_pending(self):
        reply = FakeBridge()(argv("create", request_id="c1", run_id=RUN_ID,
                                  name="MW_API_x", graph_kind=20000))
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["backend"]["status"], STATUS_CREATE_PENDING)

    def test_lookup_before_create_is_pending(self):
        reply = FakeBridge()(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
        self.assertEqual(reply["backend"]["status"], STATUS_LOOKUP_PENDING)
        self.assertNotIn("graphId", reply["backend"])

    def test_lookup_after_create_is_a_model_readback(self):
        bridge = FakeBridge()
        bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        reply = bridge(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
        self.assertEqual(reply["backend"]["status"], STATUS_EDITOR_MODEL_READBACK)
        self.assertEqual(reply["backend"]["graphId"], bridge.graph_id)

    def test_add_returns_the_added_readback(self):
        bridge = FakeBridge()
        bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        reply = bridge(argv("add", request_id="a1", run_id=RUN_ID, name="MW_API_x",
                            graph_id=bridge.graph_id, definition_id=71, expected_node_count=0, x=0, y=0))
        self.assertEqual(reply["backend"]["status"], STATUS_ADDED)
        self.assertEqual(reply["backend"]["nodes"], [{"nodeId": 1, "definitionId": 71}])

    def test_build_plan_returns_the_plan_built_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_file = Path(tmp) / "p.json"
            plan_file.write_text(json.dumps({"nodes": [{"definitionId": 71, "x": 0, "y": 0},
                                                       {"definitionId": 688, "x": 1, "y": 1}]}), encoding="utf-8")
            bridge = FakeBridge()
            bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
            bridge(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
            reply = bridge(argv("build-plan", request_id="b1", run_id=RUN_ID, name="MW_API_x",
                                graph_id=bridge.graph_id, expected_node_count=0, plan_file=str(plan_file)))
            self.assertEqual(reply["backend"]["status"], STATUS_PLAN_BUILT)
            self.assertEqual([n["definitionId"] for n in reply["backend"]["nodes"]], [71, 688])

    def test_bind_returns_the_binding_pending_readback(self):
        bridge = FakeBridge()
        bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        bridge(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
        reply = bridge(argv("bind", request_id="bd1", run_id=RUN_ID, name="MW_API_x",
                            graph_id=bridge.graph_id, expected_node_count=0, entity_id=1077936216))
        self.assertEqual(reply["backend"]["status"], STATUS_BINDING_PENDING)
        self.assertEqual(reply["backend"]["entityId"], 1077936216)

    def test_export_is_invoked_not_confirmed_and_not_a_failure(self):
        bridge = FakeBridge()
        bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        bridge(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
        reply = bridge(argv("export", request_id="e1", run_id=RUN_ID, name="MW_API_x",
                            graph_id=bridge.graph_id))
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["backend"]["status"], STATUS_EXPORT_INVOKED)


class TestJournalReplayAndConflict(unittest.TestCase):
    """The request journal: identical -> cached receipt, changed -> conflict."""

    def test_same_request_id_and_params_replays(self):
        bridge = FakeBridge()
        first = bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        self.assertFalse(first["replayed"])
        second = bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        self.assertTrue(second["replayed"])
        self.assertEqual(first["backend"], second["backend"])
        # A replay is not a second dispatch.
        self.assertEqual(len(bridge.dispatched), 1)

    def test_changed_params_under_the_same_id_conflicts(self):
        bridge = FakeBridge()
        bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        bridge(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
        bridge(argv("add", request_id="a1", run_id=RUN_ID, name="MW_API_x",
                    graph_id=bridge.graph_id, definition_id=71, expected_node_count=0, x=0, y=0))
        # Same id, different x -> conflict, and nothing new is dispatched.
        before = len(bridge.dispatched)
        reply = bridge(argv("add", request_id="a1", run_id=RUN_ID, name="MW_API_x",
                            graph_id=bridge.graph_id, definition_id=71, expected_node_count=0, x=999, y=0))
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], ERROR_REQUEST_ID_CONFLICT)
        self.assertEqual(len(bridge.dispatched), before)
        # The id was already journaled, so a conflict is a top-level error, not a backend one.
        self.assertNotIn("backend", reply)


class TestLease(unittest.TestCase):
    def test_dispatch_past_the_lease_is_refused(self):
        bridge = FakeBridge(lease_ops=2)
        bridge(argv("create", request_id="c1", run_id=RUN_ID, name="MW_API_x", graph_kind=20000))
        bridge(argv("lookup", request_id="l1", run_id=RUN_ID, name="MW_API_x"))
        reply = bridge(argv("add", request_id="a1", run_id=RUN_ID, name="MW_API_x",
                            graph_id=bridge.graph_id, definition_id=71, expected_node_count=0, x=0, y=0))
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["backend"]["error"], ERROR_LEASE_REFUSED)


class TestBuilderDetectsFailures(unittest.TestCase):
    """Each simulated failure must abort the builder, never be swallowed."""

    def test_clean_per_op_run_is_ok(self):
        bridge = FakeBridge()
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.graph_id, bridge.graph_id)
        self.assertEqual(result.node_ids, {"a": 1, "b": 2})

    def test_clean_batch_run_is_ok(self):
        bridge = FakeBridge()
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build_batch()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(result.node_ids), 2)

    def test_lease_expiry_mid_sequence_is_detected(self):
        bridge = FakeBridge(lease_ops=2)  # create + lookup succeed; the first add is refused
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertFalse(result.ok)
        self.assertIn("add", result.error)
        # the code survives on the failing step, and no later op was attempted
        self.assertIn(ERROR_LEASE_REFUSED, result.steps[-1].result["backend"]["error"])
        self.assertEqual(bridge.dispatched, ["create", "lookup"])
        self.assertNotIn("wire", [FakeBridge.action_of(c) for c in bridge.calls])

    def test_per_op_readback_disagreement_is_detected(self):
        bridge = FakeBridge(readback_definitions=[71, 1])  # node b comes back as definition 1
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertFalse(result.ok)
        self.assertIn("read back as definitionId 1, expected 688", result.error)

    def test_batch_readback_disagreement_is_detected(self):
        bridge = FakeBridge(readback_definitions=[71, 1])
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build_batch()
        self.assertFalse(result.ok)
        self.assertIn("readback mismatch", result.error)

    def test_replay_lets_a_rerun_reproduce_without_dispatching(self):
        bridge = FakeBridge()
        first = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertTrue(first.ok, first.error)
        dispatched_after_first = len(bridge.dispatched)
        second = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertTrue(second.ok, second.error)
        self.assertTrue(all(step.result.get("replayed") is True for step in second.steps))
        self.assertEqual(len(bridge.dispatched), dispatched_after_first)

    def test_changed_plan_under_an_unchanged_request_id_conflicts(self):
        # Same name and aliases, but node b moves.  --x is part of the request but not
        # of the derived request id, so the second run reuses the id with new params.
        bridge = FakeBridge()
        self.assertTrue(GraphBuilder(small_plan(bx=0), bridge, run_id=RUN_ID).build().ok)
        result = GraphBuilder(small_plan(bx=999), bridge, run_id=RUN_ID).build()
        self.assertFalse(result.ok)
        self.assertIn("add b", result.error)
        self.assertEqual(result.steps[-1].result["error"], ERROR_REQUEST_ID_CONFLICT)

    def test_bound_graph_edit_refusal_is_detected(self):
        bridge = FakeBridge(bound_entity_id=1077936216)
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertFalse(result.ok)
        self.assertIn(REFUSAL_BOUND_GRAPH_EDIT_REFUSED,
                      result.steps[-1].result["backend"]["error"])

    def test_forced_refusal_codes_are_detected_and_named(self):
        cases = {
            "add": REFUSAL_NODE_COUNT_CONFLICT,
            "wire": REFUSAL_GRAPH_IDENTITY_MISMATCH,
            "value": REFUSAL_VALUE_TYPE_MISMATCH,
            "export": REFUSAL_BOUND_GRAPH_EDIT_REFUSED,
        }
        for action, code in cases.items():
            with self.subTest(action=action):
                bridge = FakeBridge(refuse={action: code})
                result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
                self.assertFalse(result.ok)
                failing = result.steps[-1]
                self.assertEqual(FakeBridge.action_of(failing.argv), action)
                self.assertIn(code, failing.result["backend"]["error"])

    def test_value_type_mismatch_is_detected_from_a_declared_signature(self):
        # 688 3:1 is declared (20, 20); the fake declares (7, 7), so the write is refused.
        bridge = FakeBridge(declared_value_type=(7, 7))
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build()
        self.assertFalse(result.ok)
        self.assertIn(REFUSAL_VALUE_TYPE_MISMATCH, result.steps[-1].result["backend"]["error"])


class TestKnownGap(unittest.TestCase):
    """A failing ``inspect`` in the batched path is NOT currently checked.

    ``builder.build_batch`` guards only on the read-back *value*
    (``if inspect.ok and readback != expected``); when ``inspect`` itself fails,
    ``inspect.ok`` is false so the guard is skipped and the build still returns
    ``ok``.  This test pins that behaviour so a fix is visible.  If it starts
    failing, ``builder.py`` now checks ``inspect.ok`` -- delete this test.
    """

    def test_batch_inspect_refusal_is_swallowed_today(self):
        bridge = FakeBridge(refuse={"inspect": REFUSAL_GRAPH_IDENTITY_MISMATCH})
        result = GraphBuilder(small_plan(), bridge, run_id=RUN_ID).build_batch()
        self.assertTrue(result.ok, "builder.py began checking inspect.ok; remove this test")
        inspect_step = [s for s in result.steps if s.name == "inspect"][0]
        self.assertFalse(inspect_step.ok)


if __name__ == "__main__":
    unittest.main()
