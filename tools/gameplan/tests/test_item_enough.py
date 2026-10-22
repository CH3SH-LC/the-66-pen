"""Offline tests for the M3 "材料够不够" fragment (``item.has_enough``).

The fragment is ``获取背包道具数量(690)`` → ``数值大于等于(233)`` → (its bool
``result``) → ``双分支(2)``.  These tests assert the exact node ids, the holder
wiring into 690, the two constants (``item_id`` on 690 3:1, ``threshold`` on the
compare 3:1), and that the compare's ``result`` is a bool that drives the branch.
A NEGATIVE control shows a wrong comparator (``是否相等(14)``) is detectable.

Run::

    python -B -m unittest tools.gameplan.tests.test_item_enough
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    default_store,
)
from tools.gameplan.modules import item


# ---------------------------------------------------------------------------
# plan-inspection helpers (pure reads; nothing here mutates the graph)
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


class TestHasEnough(unittest.TestCase):
    def test_places_690_then_233_and_returns_the_compare(self):
        g = Graph("MW_API_test_item_enough")
        src = _source(g)
        cmp_node = item.has_enough(
            g,
            holder=(src, "entity"),
            item_id=2002,
            threshold=3,
            item_slot="int",
        )

        # The returned handle *is* the comparison node: 数值大于等于(233).
        self.assertEqual(cmp_node.ntype.definition_id, 233)
        self.assertEqual(cmp_node.alias, "m3_enough")
        # Exactly one 690 and one 233 were placed.
        self.assertEqual(len(_nodes_with_id(g.plan, 690)), 1)
        self.assertEqual(len(_nodes_with_id(g.plan, 233)), 1)

        # The 690 read node is the derived alias and its holder is wired (3:0).
        read_alias = "m3_enough_read"
        self.assertIsNotNone(_const_at(g.plan, read_alias, 1))  # exists
        self.assertTrue(
            _has_edge(
                g.plan, "src", DATA_OUTPUT, 0, read_alias, DATA_INPUT, 0
            )
        )

        g.validate()  # must not raise

    def test_consts_are_item_id_on_690_3_1_and_threshold_on_233_3_1(self):
        g = Graph("MW_API_test_item_enough_consts")
        src = _source(g)
        cmp_node = item.has_enough(
            g,
            holder=(src, "entity"),
            item_id=2002,
            threshold=3,
            item_slot="int",
        )

        # item_id (道具配置ID) on 690's pin 3:1.
        item_id_const = _const_at(g.plan, "m3_enough_read", 1)
        self.assertIsNotNone(item_id_const)
        self.assertEqual(item_id_const.value, 2002)
        self.assertEqual(item_id_const.slot, "int")
        # The builder derives the config-id generic id from the contract, not here.
        self.assertIsNone(item_id_const.expect_server_param_type)
        self.assertIsNone(item_id_const.expect_generic_id)

        # threshold on the compare's pin 3:1 (the right-hand operand).
        threshold_const = _const_at(g.plan, cmp_node.alias, 1)
        self.assertIsNotNone(threshold_const)
        self.assertEqual(threshold_const.value, 3)
        self.assertEqual(threshold_const.slot, "int")

        # Nothing was written into the compare's left pin (3:0) as a const — it is
        # an edge from the 690 result.
        self.assertIsNone(_const_at(g.plan, cmp_node.alias, 0))

        g.validate()

    def test_amount_feeds_the_left_operand(self):
        g = Graph("MW_API_test_item_enough_wire")
        src = _source(g)
        cmp_node = item.has_enough(
            g,
            holder=(src, "entity"),
            item_id=9,
            threshold=5,
            item_slot="int",
        )
        # 690.amount (4:0) -> 233.left (3:0).
        self.assertTrue(
            _has_edge(
                g.plan,
                "m3_enough_read",
                DATA_OUTPUT,
                0,
                cmp_node.alias,
                DATA_INPUT,
                0,
            )
        )
        g.validate()

    def test_result_drives_the_branch(self):
        g = Graph("MW_API_test_item_enough_branch")
        src = _source(g)
        cmp_node = item.has_enough(
            g,
            holder=(src, "entity"),
            item_id=9,
            threshold=5,
            item_slot="int",
        )
        branch = g.place(N.BRANCH, "gate")
        branch.data_from(cmp_node, "result", "condition")

        self.assertTrue(
            _has_edge(
                g.plan,
                cmp_node.alias,
                DATA_OUTPUT,
                cmp_node.ntype.outs["result"],
                "gate",
                DATA_INPUT,
                branch.ntype.ins["condition"],
            )
        )
        # 双分支 used in the intended way: it consumes the bool, has no bad edges.
        g.validate()

    def test_negative_eq_instead_of_gte_is_detectable(self):
        """NEGATIVE control: if the comparator were ``是否相等(14)`` rather than
        ``数值大于等于(233)`` the id assertion must catch it."""
        g = Graph("MW_API_test_item_enough_neg")
        src = _source(g)
        cmp_node = item.has_enough(
            g,
            holder=(src, "entity"),
            item_id=1,
            threshold=1,
            item_slot="int",
            compare="eq",
        )

        # The placed node really is 是否相等(14) ...
        self.assertEqual(cmp_node.ntype.definition_id, N.EQ.definition_id)
        self.assertEqual(cmp_node.ntype.definition_id, 14)
        # ... and NOT the 数值大于等于(233) a `gte` build would use.
        self.assertNotEqual(cmp_node.ntype.definition_id, N.GE.definition_id)
        self.assertNotEqual(cmp_node.ntype.definition_id, 233)
        # i.e. the positive assertion `definition_id == 233` would have failed.
        with self.assertRaises(AssertionError):
            self.assertEqual(cmp_node.ntype.definition_id, 233)

        # Both ids resolve to *different* names in the contract store.
        store = default_store()
        self.assertEqual(store.require(14).name, "是否相等")
        self.assertEqual(store.require(233).name, "数值大于等于")

        g.validate()

    def test_default_compare_is_gte(self):
        # No `compare=` -> 数值大于等于(233), the documented default.
        g = Graph("MW_API_test_item_enough_default")
        src = _source(g)
        cmp_node = item.has_enough(
            g, holder=(src, "entity"), item_id=1, threshold=1, item_slot="int"
        )
        self.assertEqual(cmp_node.ntype.definition_id, 233)
        g.validate()

    def test_unknown_compare_raises_keyerror(self):
        g = Graph("MW_API_test_item_enough_bad")
        src = _source(g)
        with self.assertRaises(KeyError):
            item.has_enough(
                g,
                holder=(src, "entity"),
                item_id=1,
                threshold=1,
                item_slot="int",
                compare="approximately",
            )


if __name__ == "__main__":
    unittest.main()
