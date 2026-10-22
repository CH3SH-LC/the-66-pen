"""End-to-end OFFLINE proof of the BATCHED build flow for the canonical demo.

The canonical demo (``tools/gameplan/demo/farming_full.py``) is built on the
machine through the *batched* ``build-plan`` op, not the one-op-at-a-time path.
There are already tests for the builder in isolation (``test_builder.py``),
for the fake bridge (``test_testing.py``) and for the demo's plan *shape*
(``test_demo_contract.py``) -- what was missing is the one place that proves the
WHOLE batched flow is well-formed *for the canonical demo*: the JSON the builder
hands the adapter, the index bookkeeping between plan and payload, the exact
dispatch order, and the two ways a batch must *refuse* rather than lie.

Everything here is offline: the runner is :class:`tools.gameplan.testing.FakeBridge`
(a model of the bridge's documented semantics -- status strings, journal, lease),
so nothing touches a process, the queue, the game or the editor.

The shape claims are anchored to the adapter, not invented
----------------------------------------------------------
The values this file reads are the fields ``AuthoringGraph.cs`` *actually*
consumes for the ``build-plan`` action:

* the action's field whitelist is ``{graphId, expectedNodeCount, plan}``
  (``AuthoringGraph.cs:103``); the plan is a **nested object** and its ``nodes``
  array must be non-empty and at most 128 (``AuthoringGraph.cs:145-149``).  The
  CLI wraps the on-disk plan file into that nested ``plan`` key
  (``author.py:591-602``).
* a node spec is ``{definitionId, x?, y?}``: ``definitionId`` is a uint32
  (``AuthoringGraph.cs:751-753``), ``x``/``y`` are optional numbers defaulting
  to 0 (``AuthoringGraph.cs:777-778``).
* an edge spec is ``{from, to, fromKind, fromIndex, toKind, toIndex}``, with
  ``from``/``to`` the node *indices* into the plan's node array, each in range
  and never equal (``AuthoringGraph.cs:784-789``).
* a value spec is ``{node, portIndex, slot, value}``: ``node`` is an in-range
  index (``AuthoringGraph.cs:794``), ``slot`` a string and ``value`` an object
  (``AuthoringGraph.cs:796-800``) whose payload is named by its FIRST key
  (``AuthoringGraph.cs:803``); a ``string`` slot must carry a ``string`` payload
  (``AuthoringGraph.cs:804-810``).

The builder that produces this payload is ``GraphBuilder.batch_plan_json``
(``builder.py:350-366``); the flow that dispatches it is ``build_batch``
(``builder.py:368-436``).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan.builder import GraphBuilder, request_id
from tools.gameplan.demo.farming_full import (
    DEFAULT_NAME,
    FarmFullConfig,
    build_plan,
)
from tools.gameplan.testing import (
    ERROR_LEASE_REFUSED,
    FakeBridge,
)

RUN_ID = "7588c713-fb80-433a-afce-c0f89cf13d96"

#: The canonical editor-asset ids the committed goldens freeze (identical to
#: ``test_farming_full.CONFIG`` / ``test_demo_contract.CONFIG``).
CONFIG = FarmFullConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

#: The exact plan envelope and per-row keys ``AuthoringGraph.cs`` reads.
_PLAN_KEYS = {"nodes", "edges", "values"}
_NODE_KEYS = {"definitionId", "x", "y"}
_EDGE_KEYS = {"from", "to", "fromKind", "fromIndex", "toKind", "toIndex"}
_VALUE_KEYS = {"node", "portIndex", "slot", "value"}

#: The legal payload tag names ``builder._tagged`` emits (``builder.py:60-81``);
#: each is a key of the one-key ``value`` object the adapter carries.
_PAYLOAD_NAMES = {"int", "uint", "float", "bool", "string"}

#: The slot names a ConstSpec may carry (``plan.py:341``), the same closed set the
#: adapter's own ``--slot`` accepts.
_SLOTS = {"auto", "int", "uint", "enum", "float", "bool", "string"}


def _batch_json(plan) -> dict:
    """The demo plan in the builder's ``build-plan`` shape (pure, no dispatch)."""

    def _never(argv):  # pragma: no cover - only runs if batch_plan_json dispatches
        raise AssertionError(f"batch_plan_json must not dispatch, got {argv!r}")

    return GraphBuilder(plan, _never, run_id=RUN_ID).batch_plan_json()


def _run_batch(plan, bridge: FakeBridge):
    """Run the whole batched flow for ``plan`` against ``bridge``, writing the plan
    file under a scratch temp dir so the test is hermetic (never the repo tree)."""
    with tempfile.TemporaryDirectory() as tmp:
        plan_path = Path(tmp) / f"{plan.name}-plan.json"
        builder = GraphBuilder(plan, bridge, run_id=RUN_ID)
        result = builder.build_batch(plan_path=plan_path)
        # The bridge read exactly the bytes the builder wrote -- capture them before
        # the temp dir is torn down.
        written = json.loads(plan_path.read_text(encoding="utf-8"))
    return builder, result, written


class TestBatchPlanEnvelopeMatchesTheAdapter(unittest.TestCase):
    """(a) -- the batch JSON is exactly the shape ``AuthoringGraph.cs`` reads."""

    def test_top_level_envelope_keys(self):
        # The adapter requires the nested plan object to carry a non-empty `nodes`
        # array (AuthoringGraph.cs:145-149); `edges`/`values` are the two it then
        # walks (AuthoringGraph.cs:782, :792).
        batch = _batch_json(build_plan(CONFIG))
        self.assertEqual(set(batch), _PLAN_KEYS)
        self.assertIsInstance(batch["nodes"], list)
        self.assertIsInstance(batch["edges"], list)
        self.assertIsInstance(batch["values"], list)

    def test_node_spec_keys_and_types(self):
        batch = _batch_json(build_plan(CONFIG))
        self.assertTrue(1 <= len(batch["nodes"]) <= 128,
                        "the adapter refuses an empty or >128-node plan (AuthoringGraph.cs:147-149)")
        for node in batch["nodes"]:
            with self.subTest(node=node):
                self.assertEqual(set(node), _NODE_KEYS)
                # definitionId is read as a uint32 (AuthoringGraph.cs:751-753).
                self.assertIsInstance(node["definitionId"], int)
                self.assertFalse(isinstance(node["definitionId"], bool))
                self.assertTrue(0 <= node["definitionId"] <= 0xFFFFFFFF)
                # x/y are numbers (AuthoringGraph.cs:777-778).
                self.assertIsInstance(node["x"], (int, float))
                self.assertIsInstance(node["y"], (int, float))

    def test_edge_spec_keys(self):
        batch = _batch_json(build_plan(CONFIG))
        self.assertTrue(batch["edges"], "the demo has execution and data edges")
        for edge in batch["edges"]:
            with self.subTest(edge=edge):
                self.assertEqual(set(edge), _EDGE_KEYS)

    def test_value_spec_keys_and_payload(self):
        batch = _batch_json(build_plan(CONFIG))
        self.assertTrue(batch["values"], "the demo has constants")
        for value in batch["values"]:
            with self.subTest(value=value):
                self.assertEqual(set(value), _VALUE_KEYS)
                self.assertIsInstance(value["slot"], str)
                self.assertIn(value["slot"], _SLOTS)
                # `value` is an object whose FIRST key names the payload
                # (AuthoringGraph.cs:803); the builder always emits exactly one.
                payload = value["value"]
                self.assertIsInstance(payload, dict)
                self.assertEqual(len(payload), 1)
                name = next(iter(payload))
                self.assertIn(name, _PAYLOAD_NAMES)
                # A string slot must carry a string payload (AuthoringGraph.cs:804-810).
                if value["slot"] == "string":
                    self.assertEqual(name, "string")
                    self.assertIsInstance(payload["string"], str)

    def test_the_plan_file_the_bridge_read_is_batch_plan_json(self):
        # build_batch writes batch_plan_json to the plan file (builder.py:382-384) and
        # the bridge reads it back (author.py:597) -- so the file IS the payload.
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        _, result, written = _run_batch(plan, FakeBridge())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(written, batch)


class TestNodeRefIndicesAreInRange(unittest.TestCase):
    """(b) -- every index in ``edges``/``values`` addresses a real plan node."""

    def test_edge_indices_address_the_right_nodes(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        index = {n.alias: i for i, n in enumerate(plan.nodes)}
        n = len(plan.nodes)
        # The adapter refuses from/to outside [0, N) or equal to each other
        # (AuthoringGraph.cs:787-788, AUTHOR_PLAN_EDGE_INDEX).
        for raw, edge in zip(batch["edges"], plan.edges):
            with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                self.assertTrue(0 <= raw["from"] < n)
                self.assertTrue(0 <= raw["to"] < n)
                self.assertNotEqual(raw["from"], raw["to"])
                # the index must denote the SAME alias, not merely some node
                self.assertEqual(raw["from"], index[edge.src])
                self.assertEqual(raw["to"], index[edge.dst])
                self.assertEqual(
                    (raw["fromKind"], raw["fromIndex"], raw["toKind"], raw["toIndex"]),
                    (edge.src_kind, edge.src_index, edge.dst_kind, edge.dst_index),
                )
                # kinds are the two the adapter links: 2->1 execution, 4->3 data
                # (AuthoringGraph.cs:398-400).
                self.assertIn(raw["fromKind"], (2, 4))
                self.assertIn(raw["toKind"], (1, 3))

    def test_edge_count_matches_the_plan(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        self.assertEqual(len(batch["edges"]), len(plan.edges))

    def test_value_indices_address_the_right_nodes(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        index = {n.alias: i for i, n in enumerate(plan.nodes)}
        n = len(plan.nodes)
        # The adapter refuses a value node index outside [0, N) (AuthoringGraph.cs:794).
        for raw, const in zip(batch["values"], plan.consts):
            with self.subTest(const=const.alias):
                self.assertTrue(0 <= raw["node"] < n)
                self.assertEqual(raw["node"], index[const.alias])
                self.assertEqual(raw["portIndex"], const.port_index)
                self.assertEqual(raw["slot"], const.slot)

    def test_value_count_matches_the_plan(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        self.assertEqual(len(batch["values"]), len(plan.consts))
        self.assertEqual(len(batch["nodes"]), len(plan.nodes))


class TestBatchedStepOrder(unittest.TestCase):
    """(c) -- the flow dispatches create -> lookup -> build-plan -> inspect -> export."""

    def test_exact_dispatch_order(self):
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        _, result, _ = _run_batch(plan, bridge)
        self.assertTrue(result.ok, result.error)
        actions = [FakeBridge.action_of(argv) for argv in bridge.calls]
        self.assertEqual(
            actions, ["create", "lookup", "build-plan", "inspect", "export"]
        )
        # inspect is the INDEPENDENT read-back: a second, read-only dispatch after
        # the build (builder.py:407-416), not folded into the build's own reply.
        self.assertEqual(bridge.dispatched, actions)

    def test_global_queue_flag_precedes_each_graph_subcommand(self):
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        _run_batch(plan, bridge)
        for argv in bridge.calls:
            self.assertEqual(argv[argv.index("graph") - 2], "--elevated-queue")

    def test_build_plan_dispatch_is_the_empty_graph_request(self):
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        _run_batch(plan, bridge)
        build = next(a for a in bridge.calls if FakeBridge.action_of(a) == "build-plan")
        # The adapter refuses build-plan on a non-empty graph -- expectedNodeCount
        # must be 0 (AuthoringGraph.cs:144; author.py:624-629).
        self.assertEqual(build[build.index("--expected-node-count") + 1], "0")
        self.assertEqual(build[build.index("--graph-id") + 1], str(bridge.graph_id))

    def test_every_request_id_is_a_function_of_its_request(self):
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        _run_batch(plan, bridge)
        ids = [argv[argv.index("--request-id") + 1] for argv in bridge.calls]
        self.assertEqual(len(set(ids)), len(ids), "request ids must be unique")
        by_action = {FakeBridge.action_of(a): a for a in bridge.calls}
        # The build-plan id is derived from (name, "build-plan", graphId) -- exactly
        # the fields that make it a different request from any other (builder.py:398).
        build = by_action["build-plan"]
        self.assertEqual(
            build[build.index("--request-id") + 1],
            request_id(DEFAULT_NAME, "build-plan", bridge.graph_id),
        )
        # create/lookup are resolved from the name alone (builder.py:387, :391).
        create = by_action["create"]
        self.assertEqual(
            create[create.index("--request-id") + 1],
            request_id(DEFAULT_NAME, "create"),
        )

    def test_batched_build_returns_one_node_id_per_planned_node(self):
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        _, result, _ = _run_batch(plan, bridge)
        self.assertEqual(len(result.node_ids), len(plan.nodes))
        self.assertEqual(set(result.node_ids), {f"node{i}" for i in range(1, len(plan.nodes) + 1)})


class TestBatchedReadbackMismatchIsDetected(unittest.TestCase):
    """(d) -- a read-back that disagrees with the plan aborts the batch."""

    def _mismatched_definitions(self, plan):
        defs = [n.definition_id for n in plan.nodes]
        # Change the last node to a definition the plan never asked for.
        defs[-1] = 1 if defs[-1] != 1 else 2
        return defs

    def test_mismatch_is_reported_and_export_is_not_dispatched(self):
        plan = build_plan(CONFIG)
        broken = self._mismatched_definitions(plan)
        bridge = FakeBridge(readback_definitions=broken)
        _, result, _ = _run_batch(plan, bridge)
        self.assertFalse(result.ok, "a readback that disagrees must not report success")
        self.assertIn("readback mismatch", result.error)
        # It names BOTH sides -- the wrong list and the expected one (builder.py:415-416).
        self.assertIn(str(broken), result.error)
        self.assertIn(str([n.definition_id for n in plan.nodes]), result.error)
        # The flow stops at the failed read-back: no export is attempted (builder.py:418).
        actions = [FakeBridge.action_of(argv) for argv in bridge.calls]
        self.assertEqual(actions, ["create", "lookup", "build-plan", "inspect"])
        self.assertNotIn("export", actions)

    def test_agreeing_readback_is_the_control(self):
        # The negative control: the very same flow with an agreeing read-back is ok,
        # so the mismatch test above proves the guard, not an always-failing path.
        plan = build_plan(CONFIG)
        agreeing = [n.definition_id for n in plan.nodes]
        bridge = FakeBridge(readback_definitions=agreeing)
        _, result, _ = _run_batch(plan, bridge)
        self.assertTrue(result.ok, result.error)


class TestLeaseFailureStopsCleanlyWithoutClaimingSuccess(unittest.TestCase):
    """(e) -- a lease that dies mid-sequence must stop, not claim success.

    Two representations are asserted, because the builder has two of them:

    * the **batched** flow (``build_batch``) has no partial/resume concept -- a
      dead lease at the single ``build-plan`` dispatch is a failure of that op, so
      it returns ``ok=False`` and stops (``builder.py:402-403``).  The assertion
      here is that it never claims success and dispatches nothing after the death;
      ``partial`` is deliberately NOT pinned, so a future fix that widens the
      batched path to a resumable one is a visible, allowed change.
    * the **op budget** is the builder's documented model of the five-minute
      lease cap (``builder.py:161-164``): the run stops early with
      ``partial=True`` -- a resumable stop, NOT a failure (``builder.py:119``,
      ``:245``).  This is the flow that must stop "cleanly with partial=True".
    """

    def test_batched_lease_death_never_claims_success(self):
        plan = build_plan(CONFIG)
        # create + lookup succeed; the single build-plan dispatch is refused.
        bridge = FakeBridge(lease_ops=2)
        _, result, _ = _run_batch(plan, bridge)
        self.assertFalse(result.ok, "a dead lease must not report ok")
        actions = [FakeBridge.action_of(argv) for argv in bridge.calls]
        self.assertEqual(actions, ["create", "lookup", "build-plan"])
        # The refusal survives on the failing step, named, not swallowed.
        self.assertIn(ERROR_LEASE_REFUSED, result.steps[-1].result["backend"]["error"])
        # Nothing past the death was attempted: no inspect, no export.
        self.assertEqual(bridge.dispatched, ["create", "lookup"])
        self.assertNotIn("export", actions)

    def test_batched_lease_death_before_lookup_is_also_detected(self):
        plan = build_plan(CONFIG)
        bridge = FakeBridge(lease_ops=0)  # even create is refused
        _, result, _ = _run_batch(plan, bridge)
        self.assertFalse(result.ok)
        # With no graphId there is nothing to build against -- reported honestly.
        self.assertIn("no graphId", result.error)
        self.assertEqual(bridge.dispatched, [])

    def test_op_budget_exhaustion_stops_cleanly_with_partial(self):
        # The op budget IS the lease cap model (builder.py:161-164 / test_builder.py
        # TestOpBudget): the run halts after max_ops dispatches with partial=True,
        # never ok=True, and issues no further call.
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        builder = GraphBuilder(plan, bridge, run_id=RUN_ID, max_ops=3)
        result = builder.build()
        self.assertFalse(result.ok, "a partial run must not claim success")
        self.assertTrue(result.partial, "an early stop is partial, not a failure")
        self.assertIn("op budget", result.error)
        self.assertEqual(
            [FakeBridge.action_of(argv) for argv in bridge.calls],
            ["create", "lookup", "add"],
        )

    def test_op_budget_rerun_after_reload_resumes_without_redispatch(self):
        # The resumable half of the contract: the completed requests replay from the
        # journal, so a second budgeted run dispatches only the still-missing ops and
        # this time finishes (builder.py:161-164; test_builder.py:182-188).
        plan = build_plan(CONFIG)
        bridge = FakeBridge()
        first = GraphBuilder(plan, bridge, run_id=RUN_ID, max_ops=3).build()
        self.assertTrue(first.partial)
        dispatched_after_first = len(bridge.dispatched)
        second = GraphBuilder(plan, bridge, run_id=RUN_ID).build()
        self.assertTrue(second.ok, second.error)
        self.assertFalse(second.partial)
        # The rerun must not re-issue the ops the first run already completed.
        replayed = [s for s in second.steps if s.result.get("replayed") is True]
        self.assertTrue(replayed, "completed ops must replay from the journal")
        self.assertGreater(len(bridge.dispatched), dispatched_after_first)


if __name__ == "__main__":
    unittest.main()
