"""Offline tests for the M4 demo plan (``demo/farming_m4.py``).  No bridge, no game.

Three things are pinned here, per the task that created this demo:

* **the exact node list** — six nodes, in build order, with their definitionIds;
* **the holder wiring** — both ``689`` (容量门) and ``685`` (扩容) take their
  ``holder`` from the event entity (``92`` data output ``4:0``), never a constant;
* **the branch true/false targets** — ``双分支`` 是(``0``) -> ``1`` 打印,
  否(``1``) 空（故意不接线），with a negative control proving the index-based
  assertions actually discriminate.

Plus the constants (``230`` 右值 = threshold int, ``1`` 字符串 = 文本, ``685``
``3:1`` = delta int).  Every test calls ``graph.validate()`` so a wrong pin index,
a bad const slot or a data-type mismatch fails here exactly as it would at compile,
before any native call.

The pin indices asserted are the ones declared in
``data/node-contracts/variants/server`` (92 exec ``2:0`` / entrant ``4:0``;
689 in ``3:0`` entity / out ``4:0`` int; 230 ``3:0`` 左值 / ``3:1`` 右值 /
``3:2`` op / ``4:0`` bool; 2 exec in ``1:0`` / 是 ``2:0`` / 否 ``2:1`` /
condition ``3:0``; 1 exec ``2:0`` / 字符串 ``3:0``; 685 in ``3:0`` entity /
``3:1`` int).

Run::

    python -B -m unittest tools.gameplan.tests.test_farming_m4
"""

import unittest

from tools.gameplan import nodes as N
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    default_store,
)
from tools.gameplan.demo.farming_m4 import (
    COMPARE,
    DEFAULT_NAME,
    WARN_TEXT,
    FarmM4Config,
    build,
    build_plan,
)
from tools.gameplan.plan import EdgeSpec, PlanError


CFG = FarmM4Config(capacity_threshold=20, grow_amount=10)

#: (alias, definitionId) in build order — the whole graph, nothing more.
EXPECTED_NODES = (
    ("enter", 92),      # 进入碰撞触发器时
    ("gate_cap", 689),  # 获取背包容量         (capacity_gate 的兄弟节点)
    ("gate", 230),      # 数值小于             (capacity_gate 返回的比较节点)
    ("branch", 2),      # 双分支
    ("warn", 1),        # 打印字符串
    ("grow", 685),      # 增加背包最大容量
)

BRANCH = "branch"


# ---------------------------------------------------------------------------
# plan-inspection helpers (pure reads) — mirror demo/farming_full's test helpers
# ---------------------------------------------------------------------------

def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _const_at(plan, alias, port_index):
    for c in plan.consts:
        if c.alias == alias and c.port_index == port_index:
            return c
    return None


def _nodes_with_id(plan, definition_id):
    return [n for n in plan.nodes if n.definition_id == definition_id]


def _holder_source(plan, alias):
    """The data edge that fills a node's ``holder`` input (port 0)."""
    return next(
        e for e in plan.edges
        if e.dst == alias and e.dst_kind == DATA_INPUT and e.dst_index == 0
    )


def _has_edge(plan, src, src_kind, src_index, dst, dst_kind, dst_index):
    return any(
        e.src == src
        and e.src_kind == src_kind
        and e.src_index == src_index
        and e.dst == dst
        and e.dst_kind == dst_kind
        and e.dst_index == dst_index
        for e in plan.edges
    )


def _exec_out_edges(plan, src):
    return [
        e for e in plan.edges
        if e.src == src and e.src_kind == EXEC_OUTPUT
    ]


def _branch_targets(plan):
    """(true-targets, false-targets) wired off ``双分支`` 'branch'.

    TRUE is execution output index 0, FALSE is index 1 (``nodes.BRANCH``).
    """
    true_targets = [
        e.dst for e in plan.edges
        if e.src == BRANCH and e.src_kind == EXEC_OUTPUT and e.src_index == 0
    ]
    false_targets = [
        e.dst for e in plan.edges
        if e.src == BRANCH and e.src_kind == EXEC_OUTPUT and e.src_index == 1
    ]
    return true_targets, false_targets


def _swap_branch_outputs(plan):
    """Return a copy of ``plan.edges`` with the 双分支 outputs reversed."""
    swapped = []
    for e in plan.edges:
        if e.src == BRANCH and e.src_kind == EXEC_OUTPUT:
            e = EdgeSpec(e.src, e.src_kind, 1 - e.src_index, e.dst, e.dst_kind, e.dst_index)
        swapped.append(e)
    return swapped


class TestFarmingM4Plan(unittest.TestCase):
    # -- shape ----------------------------------------------------------------

    def test_builds_and_validates(self):
        plan = build_plan(CFG)
        self.assertEqual(plan.name, DEFAULT_NAME)
        self.assertIsNone(plan.validate())  # idempotent; already validated

    def test_exact_node_list_in_order(self):
        plan = build_plan(CFG)
        got = tuple((n.alias, n.definition_id) for n in plan.nodes)
        self.assertEqual(got, EXPECTED_NODES)

    def test_each_node_id_appears_exactly_once(self):
        plan = build_plan(CFG)
        self.assertEqual(len(_nodes_with_id(plan, 92)), 1)   # one event
        self.assertEqual(len(_nodes_with_id(plan, 689)), 1)  # one capacity read
        self.assertEqual(len(_nodes_with_id(plan, 230)), 1)  # one comparison
        self.assertEqual(len(_nodes_with_id(plan, 2)), 1)    # one branch
        self.assertEqual(len(_nodes_with_id(plan, 1)), 1)    # one print
        self.assertEqual(len(_nodes_with_id(plan, 685)), 1)  # one grow

    def test_event_node_is_92(self):
        plan = build_plan(CFG)
        enter = next(n for n in plan.nodes if n.alias == "enter")
        self.assertEqual(enter.definition_id, 92)

    def test_compare_selector_is_lt(self):
        self.assertEqual(COMPARE, "lt")  # 230 数值小于
        self.assertEqual(_nodes_with_id(build_plan(CFG), 230)[0].alias, "gate")

    # -- holder wiring --------------------------------------------------------

    def test_capacity_689_holder_comes_from_the_event_entity(self):
        plan = build_plan(CFG)
        edge = _holder_source(plan, "gate_cap")
        self.assertEqual(edge.src, "enter")
        self.assertEqual((edge.src_kind, edge.src_index), (DATA_OUTPUT, 0))  # entrant
        self.assertEqual((edge.dst_kind, edge.dst_index), (DATA_INPUT, 0))

    def test_grow_685_holder_comes_from_the_event_entity(self):
        plan = build_plan(CFG)
        edge = _holder_source(plan, "grow")
        self.assertEqual(edge.src, "enter")
        self.assertEqual((edge.src_kind, edge.src_index), (DATA_OUTPUT, 0))  # entrant
        self.assertEqual((edge.dst_kind, edge.dst_index), (DATA_INPUT, 0))

    def test_holders_are_never_written_as_constants(self):
        plan = build_plan(CFG)
        for alias in ("gate_cap", "grow"):
            for c in plan.consts:
                if c.alias == alias:
                    self.assertNotEqual(c.port_index, 0, f"{alias} has a const holder")

    def test_capacity_node_has_no_constants_at_all(self):
        # 689 获取背包容量 is a pure query: holder comes from the event, nothing
        # else is written.  A const here would mean we smuggled in an entity id.
        plan = build_plan(CFG)
        self.assertEqual([c for c in plan.consts if c.alias == "gate_cap"], [])

    # -- 689 -> 230 -> 2 chain -----------------------------------------------

    def test_capacity_feeds_the_comparison_left_operand(self):
        plan = build_plan(CFG)
        # 689.capacity (4:0) -> 230.左值 (3:0).
        self.assertTrue(
            _has_edge(plan, "gate_cap", DATA_OUTPUT, 0, "gate", DATA_INPUT, 0)
        )

    def test_threshold_is_a_const_on_the_comparison_right_operand(self):
        plan = build_plan(CFG)
        right = _const_at(plan, "gate", 1)
        self.assertIsNotNone(right)
        self.assertEqual(right.value, CFG.capacity_threshold)
        self.assertEqual(right.slot, "int")

    def test_comparison_op_pin_is_left_to_the_editor(self):
        # 230's op (3:2) is a generic operand-kind enum; the project never guesses
        # its wire value (modules/currency.py:135-137, inventory.py:74-75).
        plan = build_plan(CFG)
        self.assertIsNone(_const_at(plan, "gate", 2))
        self.assertEqual(
            [c.port_index for c in plan.consts if c.alias == "gate"], [1]
        )

    def test_comparison_result_drives_the_branch_condition(self):
        plan = build_plan(CFG)
        # 230.结果 (4:0) -> 2.条件 (3:0).
        self.assertTrue(
            _has_edge(plan, "gate", DATA_OUTPUT, 0, BRANCH, DATA_INPUT, 0)
        )

    def test_event_then_drives_the_branch(self):
        plan = build_plan(CFG)
        # 92.then (2:0) -> 2.exec-in (1:0).
        self.assertTrue(
            _has_edge(plan, "enter", EXEC_OUTPUT, 0, BRANCH, EXEC_INPUT, 0)
        )

    def test_event_then_fans_out_to_exactly_two_sinks(self):
        # The one 92 execution output drives both legs: the capacity gate's branch
        # and the grow node.  Exactly two, so nothing else was silently wired.
        plan = build_plan(CFG)
        edges = _exec_out_edges(plan, "enter")
        self.assertEqual(sorted(e.dst for e in edges), [BRANCH, "grow"])
        for e in edges:
            self.assertEqual((e.src_kind, e.src_index), (EXEC_OUTPUT, 0))  # then
            self.assertEqual((e.dst_kind, e.dst_index), (EXEC_INPUT, 0))

    # -- branch targets -------------------------------------------------------

    def test_branch_true_targets_the_print(self):
        true_targets, false_targets = _branch_targets(build_plan(CFG))
        # 是 (index 0) leads into the 打印字符串 node.
        self.assertEqual(true_targets, ["warn"])
        self.assertEqual(false_targets, [])  # 否 is deliberately unwired

    def test_branch_true_edge_shape(self):
        plan = build_plan(CFG)
        edge = next(e for e in plan.edges if e.src == BRANCH and e.dst == "warn")
        self.assertEqual((edge.src_kind, edge.src_index), (EXEC_OUTPUT, 0))  # 是
        self.assertEqual((edge.dst_kind, edge.dst_index), (EXEC_INPUT, 0))

    def test_branch_false_has_no_execution_edge(self):
        plan = build_plan(CFG)
        false_edges = [
            e for e in plan.edges
            if e.src == BRANCH and e.src_kind == EXEC_OUTPUT and e.src_index == 1
        ]
        self.assertEqual(false_edges, [])

    def test_swapped_branch_outputs_are_detectable(self):
        # Negative control: the index-based assertions must change when the 双分支
        # outputs are reversed — otherwise they prove nothing.
        good = build_plan(CFG)
        broken_plan = build(CFG).plan
        broken_plan.edges = _swap_branch_outputs(broken_plan)

        self.assertEqual(_branch_targets(good), (["warn"], []))
        self.assertNotEqual(_branch_targets(good), _branch_targets(broken_plan))
        self.assertEqual(_branch_targets(broken_plan), ([], ["warn"]))

    # -- constants ------------------------------------------------------------

    def test_print_text_constant(self):
        plan = build_plan(CFG)
        self.assertEqual(_const_map(plan)[("warn", 0)], WARN_TEXT)
        self.assertEqual(WARN_TEXT, "背包快满了")
        self.assertEqual(_const_at(plan, "warn", 0).slot, "string")

    def test_grow_delta_constant_is_on_3_1(self):
        plan = build_plan(CFG)
        delta = _const_at(plan, "grow", 1)
        self.assertIsNotNone(delta)
        self.assertEqual(delta.value, CFG.grow_amount)
        self.assertEqual(delta.slot, "int")
        # Nothing else was written into 685's pins.
        self.assertEqual(
            [c.port_index for c in plan.consts if c.alias == "grow"], [1]
        )

    def test_exactly_three_constants(self):
        plan = build_plan(CFG)
        self.assertEqual(
            sorted((c.alias, c.port_index) for c in plan.consts),
            [("gate", 1), ("grow", 1), ("warn", 0)],
        )

    # -- parameterisation -----------------------------------------------------

    def test_threshold_is_parameterised(self):
        consts = _const_map(build_plan(FarmM4Config(capacity_threshold=7, grow_amount=10)))
        self.assertEqual(consts[("gate", 1)], 7)

    def test_grow_amount_is_parameterised(self):
        consts = _const_map(build_plan(FarmM4Config(capacity_threshold=20, grow_amount=99)))
        self.assertEqual(consts[("grow", 1)], 99)

    def test_name_is_parameterised(self):
        plan = build_plan(CFG, name="MW_API_FARM_M4_ALT")
        self.assertEqual(plan.name, "MW_API_FARM_M4_ALT")

    def test_invalid_name_rejected(self):
        with self.assertRaises(PlanError):
            build(CFG, name="farm_m4").validate()

    # -- honesty / contract checks -------------------------------------------

    def test_no_execution_input_on_the_pure_query_nodes(self):
        # 689 and 230 are data-only: no execution-input edge may target them.
        plan = build_plan(CFG)
        exec_dsts = {e.dst for e in plan.edges if e.dst_kind == EXEC_INPUT}
        self.assertNotIn("gate_cap", exec_dsts)
        self.assertNotIn("gate", exec_dsts)

    def test_dict_nodes_721_722_are_deliberately_absent(self):
        # 721/722 (获取背包所有基础道具 / 获取背包所有货币) emit a dict (type 27)
        # and this project has no "read a dictionary element" primitive
        # (modules/inventory.py:14-18).  Feeding 货币字典 into one of the 10 dict
        # *inputs* would be a schema mismatch that plan.validate() does NOT catch
        # (all dict pins are serverParamType 27 / genericId 27), so they stay out.
        plan = build_plan(CFG)
        self.assertEqual(_nodes_with_id(plan, 721), [])
        self.assertEqual(_nodes_with_id(plan, 722), [])

    def test_every_node_definition_is_a_real_contract_node(self):
        store = default_store()
        for node in build_plan(CFG).nodes:
            self.assertIn(node.definition_id, store, f"{node.alias} unknown")
            self.assertEqual(store.require(node.definition_id).graph_kind, 20000)

    def test_broken_variant_raises_plan_error(self):
        graph = build(CFG)
        self.assertIsNone(graph.validate())          # good plan is clean
        # An execution edge off a pin the 双分支 definition does not have.
        graph.plan.wire(BRANCH, EXEC_OUTPUT, 5, "warn", EXEC_INPUT, 0)
        with self.assertRaises(PlanError):
            graph.validate()


if __name__ == "__main__":
    unittest.main()
