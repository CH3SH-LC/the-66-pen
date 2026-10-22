"""End-to-end OFFLINE contract proof for the canonical demo graph.

Every other test in this package checks *one* slice of the demo: a module's pin
roles, the builder's argv, the golden snapshot, the branch's true/false legs.
What was missing is the single place that asserts the demo's **whole contract at
once** — the artefact that says "the demo is built *through tests*, not only by
hand":

a) the graph validates against the real ``data/node-contracts`` store (no PlanError);
b) its exact ordered node list (alias, definitionId);
c) every execution edge leaves a legal output pin and lands on a legal input pin,
   and **no event node is ever a flow target** (events only *emit*);
d) every data edge is type-legal (two concrete ends must agree; a generic end is
   filled in by the native editor, so it is always legal);
e) the six-direction demo covers M1..M5, with the M4 bag leg reported *if present*;
f) the plan serialises to the builder's ``build-plan`` JSON shape and round-trips
   (node/edge/value counts survive a full serialise -> reconstruct cycle);
g) three deliberate mutations each raise :class:`PlanError`.

Everything here is offline: it reads JSON contracts and builds Python objects.
It never touches the bridge, the editor, the game, or a queue file.
"""

from __future__ import annotations

import unittest

from tools.gameplan.builder import GraphBuilder
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    default_store,
)
from tools.gameplan.demo.farming_full import (
    DEFAULT_NAME,
    FarmFullConfig,
    build,
    build_plan,
)
from tools.gameplan.plan import GraphPlan, PlanError

# The canonical editor-asset ids (the same ones the committed goldens freeze).
CONFIG = FarmFullConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

#: (b) The demo's exact nodes, in build order.  This is the contract.
EXPECTED_NODES: tuple[tuple[str, int], ...] = (
    ("plot_enter", 92),    # M1 进入碰撞触发器时
    ("harvest", 686),      # M3 增加背包道具数量 (+harvest_gain crop)
    ("crop_used", 733),    # M3 背包内道具被使用时
    ("crop_count", 690),   # M3 获取背包道具数量
    ("enough", 233),       # 数值大于等于 (shared compare)
    ("gate", 2),           # 双分支
    ("consume", 686),      # M3 -recipe_cost crop
    ("bake", 686),         # M3 +cook_gain food
    ("short", 1),          # 打印字符串 "材料不足"
    ("stall_enter", 92),   # M1 进入碰撞触发器时
    ("open_shop", 702),    # M5 打开商店
    ("sold", 701),         # M5 商店出售背包物品时
    ("sold_note", 1),     # Native trade notification; no extra wallet settlement
    ("money_changed", 684),  # M2 背包货币数量变化时
    ("money_note", 1),     # 打印字符串 "货币发生变化"
)

#: (e) Each module's own postable node ids, so coverage is checked by membership
#: rather than by "every node must belong to a module" (双分支 2 / 打印字符串 1 /
#: the shared comparators are cross-module primitives, not module fingerprints).
MODULE_IDS: dict[str, frozenset[int]] = {
    "M1": frozenset({92, 91, 316, 826}),                 # interaction
    "M2": frozenset({688, 691, 684}),                    # currency
    "M3": frozenset({686, 690, 681, 682, 683, 733}),     # item
    "M4": frozenset({685, 689, 721, 722}),               # inventory (bag)
    "M5": frozenset({702, 703, 701, 705, 704, 706, 709, 714, 715}),  # shop
}

#: The modules the six-direction demo *must* wire.  M4 is the optional bag leg:
#: today it is absent, and the task treats it as "if present".
REQUIRED_MODULES = ("M1", "M2", "M3", "M5")

_EXEC_PAIR = (EXEC_OUTPUT, EXEC_INPUT)  # 2 -> 1
_DATA_PAIR = (DATA_OUTPUT, DATA_INPUT)  # 4 -> 3

#: Keys the adapter's ``build-plan`` action consumes (builder.batch_plan_json).
_BATCH_KEYS = {"nodes", "edges", "values"}
_BATCH_NODE_KEYS = {"definitionId", "x", "y"}
_BATCH_EDGE_KEYS = {"from", "to", "fromKind", "fromIndex", "toKind", "toIndex"}
_BATCH_VALUE_KEYS = {"node", "portIndex", "slot", "value"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _defs(plan: GraphPlan) -> dict[str, int]:
    """alias -> definitionId for every node in the plan."""
    return {n.alias: n.definition_id for n in plan.nodes}


def _is_event(definition) -> bool:
    """An event node emits execution and can never be driven by an execution edge."""
    return bool(definition.exec_outputs) and not definition.exec_inputs


def _batch_json(plan: GraphPlan) -> dict:
    """The plan in the builder's ``build-plan`` shape (node refs are indices).

    A runner that raises if called proves ``batch_plan_json`` is pure: it must
    never dispatch anything.
    """
    def _never(argv):  # pragma: no cover - only runs if batch_plan_json dispatches
        raise AssertionError(f"batch_plan_json must not dispatch, got {argv!r}")

    return GraphBuilder(plan, _never, run_id="demo-contract").batch_plan_json()


def _untag(tagged: dict):
    """Invert ``builder._tagged``: ``{"int": 5}`` -> ``5``."""
    if not isinstance(tagged, dict) or len(tagged) != 1:
        raise AssertionError(f"not a tagged scalar: {tagged!r}")
    return next(iter(tagged.values()))


def _plan_from_batch(batch: dict, name: str, graph_kind: int = 20000) -> GraphPlan:
    """Reconstruct a :class:`GraphPlan` from ``build-plan`` JSON (indices -> aliases)."""
    plan = GraphPlan(name=name, graph_kind=graph_kind)
    alias = {i: f"node{i}" for i in range(len(batch["nodes"]))}
    for i, node in enumerate(batch["nodes"]):
        plan.add(alias[i], node["definitionId"], x=node["x"], y=node["y"])
    for edge in batch["edges"]:
        plan.wire(
            alias[edge["from"]], edge["fromKind"], edge["fromIndex"],
            alias[edge["to"]], edge["toKind"], edge["toIndex"],
        )
    for value in batch["values"]:
        plan.const(alias[value["node"]], value["portIndex"],
                   _untag(value["value"]), value["slot"])
    return plan


def _solution(plan: GraphPlan, store) -> dict[str, dict]:
    """alias -> {"def": NodeDefinition, "id": definitionId} for the plan."""
    return {
        n.alias: {"def": store.require(n.definition_id), "id": n.definition_id}
        for n in plan.nodes
    }


# ---------------------------------------------------------------------------
# (a) validates against the contract store
# ---------------------------------------------------------------------------

class TestDemoValidatesAgainstTheContract(unittest.TestCase):
    def test_build_plan_validates_clean_against_the_default_store(self):
        plan = build_plan(CONFIG)
        # build_plan itself validates; an explicit re-validate must also be clean.
        self.assertIsNone(plan.validate())  # (a) no PlanError
        self.assertEqual(plan.name, DEFAULT_NAME)
        self.assertEqual(plan.graph_kind, 20000)

    def test_every_node_is_a_real_server_contract_node(self):
        store = default_store()
        for node in build_plan(CONFIG).nodes:
            with self.subTest(alias=node.alias):
                self.assertIn(node.definition_id, store)
                self.assertEqual(store.require(node.definition_id).graph_kind, 20000)


# ---------------------------------------------------------------------------
# (b) the exact ordered node list
# ---------------------------------------------------------------------------

class TestExactOrderedNodeList(unittest.TestCase):
    def test_exact_node_list_in_build_order(self):
        got = tuple((n.alias, n.definition_id) for n in build_plan(CONFIG).nodes)
        self.assertEqual(got, EXPECTED_NODES)

    def test_node_count(self):
        self.assertEqual(len(build_plan(CONFIG).nodes), len(EXPECTED_NODES))


# ---------------------------------------------------------------------------
# (c) execution edges leave a legal output index and land on a legal input, and
#     no event node is a flow target
# ---------------------------------------------------------------------------

class TestExecutionEdgesAreLegal(unittest.TestCase):
    def _exec_edges(self, plan):
        return [e for e in plan.edges if (e.src_kind, e.dst_kind) == _EXEC_PAIR]

    def test_every_exec_edge_pairs_an_exec_output_with_an_exec_input(self):
        plan = build_plan(CONFIG)
        edges = self._exec_edges(plan)
        self.assertTrue(edges, "the demo must have execution edges")
        for edge in edges:
            with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                self.assertEqual((edge.src_kind, edge.dst_kind), _EXEC_PAIR)

    def test_output_index_is_a_real_exec_pin_on_the_source(self):
        store = default_store()
        plan = build_plan(CONFIG)
        nodes = _solution(plan, store)
        for edge in self._exec_edges(plan):
            with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                self.assertIn(edge.src_index, (0, 1))  # 双分支 是/否 live at 0/1
                self.assertIsNotNone(
                    nodes[edge.src]["def"].port(EXEC_OUTPUT, edge.src_index),
                    f"{edge.src} has no execution output pin {edge.src_index}",
                )

    def test_input_index_zero_is_a_real_exec_pin_on_the_target(self):
        store = default_store()
        plan = build_plan(CONFIG)
        nodes = _solution(plan, store)
        for edge in self._exec_edges(plan):
            with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                self.assertEqual(edge.dst_index, 0)
                self.assertIsNotNone(
                    nodes[edge.dst]["def"].port(EXEC_INPUT, edge.dst_index),
                    f"{edge.dst} has no execution input pin {edge.dst_index}",
                )

    def test_no_event_node_is_a_flow_target(self):
        store = default_store()
        plan = build_plan(CONFIG)
        nodes = _solution(plan, store)
        events = {
            alias for alias, node in nodes.items() if _is_event(node["def"])
        }
        # The five event entry points the demo hangs its logic off.
        self.assertEqual(
            events,
            {"plot_enter", "crop_used", "stall_enter", "sold", "money_changed"},
        )
        for edge in self._exec_edges(plan):
            with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                self.assertNotIn(edge.dst, events, "an event node was used as a flow target")


# ---------------------------------------------------------------------------
# (d) data edges are type-legal
# ---------------------------------------------------------------------------

class TestDataEdgesAreTypeLegal(unittest.TestCase):
    def _data_edges(self, plan):
        return [e for e in plan.edges if (e.src_kind, e.dst_kind) == _DATA_PAIR]

    def test_every_data_edge_pairs_a_data_output_with_a_data_input(self):
        plan = build_plan(CONFIG)
        edges = self._data_edges(plan)
        self.assertTrue(edges, "the demo must have data edges")
        for edge in edges:
            with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                self.assertEqual((edge.src_kind, edge.dst_kind), _DATA_PAIR)

    def test_every_data_edge_is_type_legal(self):
        store = default_store()
        plan = build_plan(CONFIG)
        nodes = _solution(plan, store)
        concrete_pairs = 0
        generic_edges = 0
        for edge in self._data_edges(plan):
            with self.subTest(edge=f"{edge.src}:{edge.src_index}->{edge.dst}:{edge.dst_index}"):
                src_def = nodes[edge.src]["def"]
                dst_def = nodes[edge.dst]["def"]
                src_port = src_def.port(DATA_OUTPUT, edge.src_index)
                dst_port = dst_def.port(DATA_INPUT, edge.dst_index)
                self.assertIsNotNone(src_port, f"{edge.src} has no data out {edge.src_index}")
                self.assertIsNotNone(dst_port, f"{edge.dst} has no data in {edge.dst_index}")
                if src_port.is_generic or dst_port.is_generic:
                    generic_edges += 1  # the native editor fills the generic end
                else:
                    concrete_pairs += 1
                    self.assertEqual(
                        src_port.server_param_type, dst_port.server_param_type,
                        "two concrete ends must agree",
                    )
        # Every data edge fell into exactly one legal bucket: none was uncategorised.
        self.assertEqual(concrete_pairs + generic_edges, len(self._data_edges(plan)))
        # This demo really exercises the generic rule (crop_count.amount -> 233.left).
        self.assertGreaterEqual(generic_edges, 1)


# ---------------------------------------------------------------------------
# (e) the six modules are represented
# ---------------------------------------------------------------------------

class TestModulesAreRepresented(unittest.TestCase):
    @staticmethod
    def _represented(definition_ids) -> set[str]:
        present = set(definition_ids)
        return {name for name, ids in MODULE_IDS.items() if ids & present}

    def test_required_modules_are_all_represented(self):
        ids = [n.definition_id for n in build_plan(CONFIG).nodes]
        represented = self._represented(ids)
        for module in REQUIRED_MODULES:
            with self.subTest(module=module):
                self.assertIn(module, represented)

    def test_module_fingerprints_are_the_expected_nodes(self):
        plan = build_plan(CONFIG)
        ids = [n.definition_id for n in plan.nodes]
        for module, idset in MODULE_IDS.items():
            with self.subTest(module=module):
                hits = [n.alias for n in plan.nodes if n.definition_id in idset]
                if module in REQUIRED_MODULES:
                    self.assertTrue(hits, f"{module} has no node in the demo")
        # M1 (92) and M5 (702/701) are unambiguous; M2 (688/684) and M3 (686/690/733).
        self.assertEqual(
            sorted(n.alias for n in plan.nodes if n.definition_id in MODULE_IDS["M1"]),
            ["plot_enter", "stall_enter"],
        )
        self.assertEqual(
            sorted(n.alias for n in plan.nodes if n.definition_id in MODULE_IDS["M5"]),
            ["open_shop", "sold"],
        )

    def test_m4_is_the_optional_leg_and_is_absent_today(self):
        # "plus the M4 leg if present": for farming_full it is NOT present, and we
        # say so out loud rather than leave the claim untested.
        ids = {n.definition_id for n in build_plan(CONFIG).nodes}
        self.assertEqual(ids & MODULE_IDS["M4"], set())

    def test_the_m4_classifier_reports_it_when_it_is_present(self):
        # Exercise the "if present" branch: a synthetic set that carries an M4
        # node (689 获取背包容量) must be classified as covering M4.
        synthetic = {92, 686, 684, 701, 689}
        self.assertIn("M4", self._represented(synthetic))
        self.assertEqual(self._represented(synthetic), {"M1", "M2", "M3", "M5", "M4"})


# ---------------------------------------------------------------------------
# (f) build-plan JSON shape and round-trip
# ---------------------------------------------------------------------------

class TestBatchPlanJsonRoundTrips(unittest.TestCase):
    def test_shape_is_the_adapter_build_plan_envelope(self):
        batch = _batch_json(build_plan(CONFIG))
        self.assertEqual(set(batch), _BATCH_KEYS)
        for node in batch["nodes"]:
            self.assertEqual(set(node), _BATCH_NODE_KEYS)
        for edge in batch["edges"]:
            self.assertEqual(set(edge), _BATCH_EDGE_KEYS)
        for value in batch["values"]:
            self.assertEqual(set(value), _BATCH_VALUE_KEYS)

    def test_counts_match_the_plan(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)
        self.assertEqual(len(batch["nodes"]), len(plan.nodes))
        self.assertEqual(len(batch["edges"]), len(plan.edges))
        self.assertEqual(len(batch["values"]), len(plan.consts))

    def test_round_trip_preserves_every_count_and_reserialises_identically(self):
        plan = build_plan(CONFIG)
        batch = _batch_json(plan)

        restored = _plan_from_batch(batch, plan.name, plan.graph_kind)

        # Counts survive the full serialise -> reconstruct cycle.
        self.assertEqual(len(restored.nodes), len(plan.nodes))
        self.assertEqual(len(restored.edges), len(plan.edges))
        self.assertEqual(len(restored.consts), len(plan.consts))
        # The node list survives in order, by definitionId.
        self.assertEqual(
            [n.definition_id for n in restored.nodes],
            [n.definition_id for n in plan.nodes],
        )
        # And the reconstruction is itself a valid demo-shaped plan.
        self.assertIsNone(restored.validate())
        # Re-serialising the reconstruction reproduces the same build-plan JSON
        # (index-based refs, so alias names are irrelevant to the round-trip).
        self.assertEqual(_batch_json(restored), batch)


# ---------------------------------------------------------------------------
# (g) three deliberate mutations each raise PlanError
# ---------------------------------------------------------------------------

class TestDeliberateMutationsRaisePlanError(unittest.TestCase):
    def test_pristine_plan_is_the_control(self):
        # Without this, the three mutations below would prove nothing.
        self.assertIsNone(build(CONFIG).plan.validate())

    def test_wrong_direction_pair_raises(self):
        # An execution output wired into a data input (2 -> 3) is not a legal pair.
        plan = build(CONFIG).plan
        plan.wire("plot_enter", EXEC_OUTPUT, 0, "harvest", DATA_INPUT, 0)
        with self.assertRaises(PlanError) as caught:
            plan.validate()
        self.assertTrue(
            any("kind pair" in problem for problem in caught.exception.problems),
            caught.exception.problems,
        )

    def test_event_as_flow_target_raises(self):
        # Driving an event node (92 进入碰撞触发器时 has no exec input) is illegal.
        plan = build(CONFIG).plan
        plan.wire("gate", EXEC_OUTPUT, 0, "plot_enter", EXEC_INPUT, 0)
        with self.assertRaises(PlanError) as caught:
            plan.validate()
        self.assertTrue(
            any(
                "plot_enter" in problem and "no execution input" in problem
                for problem in caught.exception.problems
            ),
            caught.exception.problems,
        )

    def test_duplicate_const_raises(self):
        # Two constants on the same (alias, port) is a double-write, not a no-op.
        plan = build(CONFIG).plan
        plan.const("short", 0, "second text", "string")
        with self.assertRaises(PlanError) as caught:
            plan.validate()
        self.assertTrue(
            any("set twice" in problem for problem in caught.exception.problems),
            caught.exception.problems,
        )


if __name__ == "__main__":
    unittest.main()
