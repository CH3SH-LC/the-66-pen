"""Offline tests for the M4 bag-capacity gate.  No bridge, no game.

Covers the two fragments this task named in
:mod:`tools.gameplan.modules.inventory`:

* **容量门** — :func:`~tools.gameplan.modules.inventory.capacity_gate` placing
  ``获取背包容量`` (689) then a comparison node (default ``数值小于`` 230), wired
  ``689.capacity`` -> comparison ``left`` with ``threshold`` as an ``int`` const on
  ``right``.  The comparison's ``result`` (bool) is what drives a ``双分支``.
* **扩容** — :func:`~tools.gameplan.modules.inventory.grow_then` placing
  ``增加背包最大容量`` (685) on an execution source, with its ``delta`` const on
  pin ``3:1``.

Every test builds a :class:`Graph`, calls the module, asserts on ``graph.plan``
(nodes / edges / consts) **and** calls ``graph.validate()`` so a wrong pin index,
a bad const slot or a data-type mismatch is caught exactly the way the compiler
would catch it before a native call.  The pin indices asserted here are the ones
declared in ``data/node-contracts/variants/server`` (689 3:0 entity / 4:0 int;
230 3:0 左值 / 3:1 右值 / 4:0 bool; 685 3:0 entity / 3:1 int).

Run::

    python -B -m unittest tools.gameplan.tests.test_inventory_gate
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
)
from tools.gameplan.modules import inventory
from tools.gameplan.plan import PlanError


# ---------------------------------------------------------------------------
# plan-inspection helpers (pure reads)
# ---------------------------------------------------------------------------

def _source(g: Graph, alias: str = "src"):
    """A concrete execution source whose data output 0 is an entity."""
    return g.place(N.ON_CREATE, alias)


def _nodes_with_id(plan, definition_id):
    return [n for n in plan.nodes if n.definition_id == definition_id]


def _const_at(plan, alias, port_index):
    for c in plan.consts:
        if c.alias == alias and c.port_index == port_index:
            return c
    return None


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


# ---------------------------------------------------------------------------
# 容量门 — capacity_gate
# ---------------------------------------------------------------------------

class TestCapacityGate(unittest.TestCase):
    def test_gate_places_689_then_230(self):
        g = Graph("MW_API_test_inv_gate_ids")
        src = _source(g)
        gate = inventory.capacity_gate(g, holder=(src, "entity"), threshold=10)

        # Comparison node is returned; capacity node is the `<alias>_cap` sibling.
        self.assertEqual(gate.ntype.definition_id, 230)
        self.assertEqual(gate.alias, "m4_gate")
        self.assertEqual(len(_nodes_with_id(g.plan, 230)), 1)
        self.assertEqual(len(_nodes_with_id(g.plan, 689)), 1)

        cap = g.handle(gate.alias + "_cap")
        self.assertEqual(cap.ntype.definition_id, 689)
        self.assertEqual(cap.alias, "m4_gate_cap")

    def test_holder_entity_wires_689_3_0(self):
        g = Graph("MW_API_test_inv_gate_holder")
        src = _source(g)
        gate = inventory.capacity_gate(g, holder=(src, "entity"), threshold=5)
        cap = g.handle(gate.alias + "_cap")

        # src entity (ON_CREATE 4:0) -> 689 holder input (3:0).
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, cap.alias, DATA_INPUT, 0)
        )
        # 689 is a pure query: no execution input anywhere in the graph.
        self.assertEqual(
            [e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], []
        )

    def test_capacity_feeds_left_and_threshold_is_const_on_right(self):
        g = Graph("MW_API_test_inv_gate_leftright")
        src = _source(g)
        gate = inventory.capacity_gate(g, holder=(src, "entity"), threshold=42)
        cap = g.handle(gate.alias + "_cap")

        # 689.capacity (4:0) -> 230 左值 (3:0).
        self.assertTrue(
            _has_edge(
                g.plan,
                cap.alias, DATA_OUTPUT, cap.ntype.outs["capacity"],
                gate.alias, DATA_INPUT, gate.ntype.ins["left"],
            )
        )
        # threshold is a constant on 230 右值 (3:1), slot int.
        right = _const_at(g.plan, gate.alias, 1)
        self.assertIsNotNone(right)
        self.assertEqual(right.value, 42)
        self.assertEqual(right.slot, "int")

    def test_result_is_bool_and_feeds_branch_condition(self):
        g = Graph("MW_API_test_inv_gate_branch")
        src = _source(g)
        gate = inventory.capacity_gate(g, holder=(src, "entity"), threshold=20)
        br = g.place(N.BRANCH, "br")
        br.data_from(gate, "result", "condition")

        self.assertTrue(
            _has_edge(
                g.plan,
                gate.alias, DATA_OUTPUT, gate.ntype.outs["result"],
                "br", DATA_INPUT, br.ntype.ins["condition"],
            )
        )
        g.validate()  # bool result -> bool condition must not raise

    def test_compare_selector_picks_the_named_node(self):
        for key, expected in (
            ("lt", 230),
            ("le", 231),
            ("gt", 232),
            ("ge", 233),
        ):
            with self.subTest(compare=key):
                g = Graph("MW_API_test_inv_gate_cmp")
                src = _source(g)
                gate = inventory.capacity_gate(
                    g, holder=(src, "entity"), threshold=1, compare=key
                )
                self.assertEqual(gate.ntype.definition_id, expected)
                g.validate()

    def test_unknown_compare_raises_keyerror(self):
        g = Graph("MW_API_test_inv_gate_bad")
        src = _source(g)
        with self.assertRaises(KeyError):
            inventory.capacity_gate(
                g, holder=(src, "entity"), threshold=1, compare="nope"
            )
        # Refusal happens before anything is placed: only the source exists.
        self.assertEqual(len(g.plan.nodes), 1)

    def test_negative_capacity_int_into_entity_input_rejected(self):
        # 689.capacity is a concrete int (type 3); 685's holder input is a
        # concrete entity (type 1).  validate() must reject the wiring.
        g = Graph("MW_API_test_inv_gate_neg")
        src = _source(g)
        gate = inventory.capacity_gate(g, holder=(src, "entity"), threshold=10)
        cap = g.handle(gate.alias + "_cap")
        sink = g.place(N.ADD_BAG_CAPACITY, "cap685")
        g.plan.wire(
            cap.alias, DATA_OUTPUT, cap.ntype.outs["capacity"],
            sink.alias, DATA_INPUT, sink.ntype.ins["holder"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )


# ---------------------------------------------------------------------------
# 扩容 — grow_then
# ---------------------------------------------------------------------------

class TestGrowThen(unittest.TestCase):
    def test_grow_then_places_685_and_wires_the_exec_source(self):
        g = Graph("MW_API_test_inv_grow_then")
        src = _source(g)
        node = inventory.grow_then(g, src, holder=(src, "entity"), amount=50)

        self.assertEqual(node.ntype.definition_id, 685)
        self.assertEqual(len(_nodes_with_id(g.plan, 685)), 1)
        self.assertEqual(node.alias, "m4_grow_then")

        # Execution: source `then` -> 685.
        self.assertTrue(
            _has_edge(g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0)
        )
        # Data: holder entity -> 3:0.
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0)
        )

    def test_grow_then_delta_const_is_on_3_1(self):
        g = Graph("MW_API_test_inv_grow_then_delta")
        src = _source(g)
        node = inventory.grow_then(g, src, holder=(src, "entity"), amount=50)

        delta = _const_at(g.plan, node.alias, 1)
        self.assertIsNotNone(delta)
        self.assertEqual(delta.value, 50)
        self.assertEqual(delta.slot, "int")
        # Nothing else was written into 685's pins.
        self.assertEqual(
            [c.port_index for c in g.plan.consts if c.alias == node.alias], [1]
        )
        g.validate()


if __name__ == "__main__":
    unittest.main()
