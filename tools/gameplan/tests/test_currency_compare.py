"""Offline tests for the M2 ``read_and_compare`` / ``at_least`` fragment.  No bridge.

The fragment answers "钱够不够": place 获取背包货币数量 (691), feed its int
``amount`` (4:0) into one of the four numeric comparators (233/232/230/231) whose
左值 (3:0) is a *generic* pin, and write the integer ``threshold`` into 右值
(3:1).  The comparator's bool ``result`` (4:0) is what drives 双分支 (2).

Every assertion is a pure read of ``graph.plan`` plus a ``graph.validate()`` so a
wrong pin index or a bad const slot fails here exactly as it would at compile.

Run::

    python -B -m unittest tools.gameplan.tests.test_currency_compare
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, default_store
from tools.gameplan.modules import currency
from tools.gameplan.plan import PlanError


def _source(g: Graph, alias: str = "src"):
    """A concrete execution source whose data output 0 is an entity."""
    return g.place(N.ON_CREATE, alias)


def _nodes_with_id(plan, definition_id):
    return [n for n in plan.nodes if n.definition_id == definition_id]


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


def _const_at(plan, alias, port_index):
    for c in plan.consts:
        if c.alias == alias and c.port_index == port_index:
            return c
    return None


class TestReadAndCompare(unittest.TestCase):
    def test_gte_places_691_then_233_and_wires_the_fragment(self):
        g = Graph("MW_API_test_currency_cmp_gte")
        src = _source(g)
        cmp_node = currency.read_and_compare(
            g,
            holder=(src, "entity"),
            currency_id=1001,
            threshold=50,
            currency_slot="int",
            alias="m2_enough",
        )

        # Exactly one read (691) and one comparator (233 for gte).
        self.assertEqual(cmp_node.ntype.definition_id, 233)
        self.assertEqual(cmp_node.alias, "m2_enough")
        self.assertEqual(len(_nodes_with_id(g.plan, 691)), 1)
        self.assertEqual(len(_nodes_with_id(g.plan, 233)), 1)

        read_alias = "m2_enough_read"
        # The read is a query: no execution input edge at all.
        self.assertEqual([e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], [])

        # Holder data edge: src.entity (4:0) -> 691.holder (3:0).
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, read_alias, DATA_INPUT, 0)
        )

        # The core data edge: 691.amount (4:0) -> comparator.左值 (3:0, generic).
        self.assertTrue(
            _has_edge(
                g.plan, read_alias, DATA_OUTPUT, 0, cmp_node.alias, DATA_INPUT, 0
            )
        )

        # Currency-id const on the read's 3:1, with the caller-supplied slot.
        cur = _const_at(g.plan, read_alias, 1)
        self.assertIsNotNone(cur)
        self.assertEqual(cur.value, 1001)
        self.assertEqual(cur.slot, "int")

        # Threshold const on the comparator's 3:1 右值, an int.
        thr = _const_at(g.plan, cmp_node.alias, 1)
        self.assertIsNotNone(thr)
        self.assertEqual(thr.value, 50)
        self.assertEqual(thr.slot, "int")

        # The op enum (3:2) is deliberately not written.
        self.assertIsNone(_const_at(g.plan, cmp_node.alias, 2))

        g.validate()  # must not raise

    def test_compare_keyword_selects_the_official_node(self):
        cases = (("gte", 233), ("gt", 232), ("lt", 230), ("lte", 231))
        for compare, expected in cases:
            with self.subTest(compare=compare):
                g = Graph("MW_API_test_currency_cmp_kind")
                src = _source(g)
                cmp_node = currency.read_and_compare(
                    g,
                    holder=(src, "entity"),
                    currency_id=7,
                    threshold=3,
                    currency_slot="int",
                    alias="m2_cmp",
                    compare=compare,
                )
                self.assertEqual(cmp_node.ntype.definition_id, expected)
                self.assertEqual(len(_nodes_with_id(g.plan, expected)), 1)
                g.validate()

    def test_result_drives_branch_condition(self):
        # 233.结果 is a concrete bool (type 4); 双分支.条件 is a concrete bool
        # (type 4), so the edge is legal and the whole graph validates.
        g = Graph("MW_API_test_currency_cmp_branch")
        src = _source(g)
        cmp_node = currency.read_and_compare(
            g,
            holder=(src, "entity"),
            currency_id=1,
            threshold=1,
            currency_slot="int",
            alias="m2_enough",
        )
        branch = g.place(N.BRANCH, "br")
        branch.data_from(cmp_node, "result", "condition")
        self.assertTrue(
            _has_edge(
                g.plan, cmp_node.alias, DATA_OUTPUT, 0, "br", DATA_INPUT, 0
            )
        )
        g.validate()

    def test_result_cannot_drive_an_int_input(self):
        # The bool result (type 4) must be rejected by a concrete int input
        # (688.增加值, type 3).
        g = Graph("MW_API_test_currency_cmp_neg")
        src = _source(g)
        cmp_node = currency.read_and_compare(
            g,
            holder=(src, "entity"),
            currency_id=1,
            threshold=1,
            currency_slot="int",
            alias="m2_enough",
        )
        add = g.place(N.ADD_BAG_CURRENCY, "add")
        g.plan.wire(
            cmp_node.alias, DATA_OUTPUT, cmp_node.ntype.outs["result"],
            add.alias, DATA_INPUT, add.ntype.ins["delta"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )

    def test_unknown_compare_raises(self):
        g = Graph("MW_API_test_currency_cmp_unknown")
        src = _source(g)
        with self.assertRaises(ValueError):
            currency.read_and_compare(
                g,
                holder=(src, "entity"),
                currency_id=1,
                threshold=1,
                currency_slot="int",
                alias="m2_enough",
                compare="approximately",
            )


class TestAtLeast(unittest.TestCase):
    def test_at_least_is_gte(self):
        g = Graph("MW_API_test_currency_at_least")
        src = _source(g)
        cmp_node = currency.at_least(
            g,
            holder=(src, "entity"),
            currency_id=1001,
            threshold=50,
            currency_slot="int",
        )
        self.assertEqual(cmp_node.ntype.definition_id, 233)
        self.assertEqual(cmp_node.alias, "m2_at_least")
        self.assertEqual(_const_at(g.plan, "m2_at_least", 1).value, 50)
        self.assertEqual(
            _const_at(g.plan, "m2_at_least_read", 1).value, 1001
        )
        g.validate()

    def test_fragment_nodes_are_contract_backed(self):
        store = default_store()
        for ntype in (N.GE, N.GT, N.LT, N.LE):
            with self.subTest(node=ntype.label):
                self.assertIsNotNone(store.get(ntype.definition_id))


if __name__ == "__main__":
    unittest.main()
