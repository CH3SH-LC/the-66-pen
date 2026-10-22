"""Offline tests for the M5 sale-table *query* fragments (shop #6).  No bridge, no game.

Covers the two query nodes the task named:

* ``715`` 查询背包商店物品出售列表 — :func:`tools.gameplan.modules.shop.query_bag_sales`
* ``714`` 查询自定义商店商品出售列表 — :func:`tools.gameplan.modules.shop.query_custom_sales`

Both are **pure query** nodes: the contract store gives them *no execution pins*
at all (no ``1:`` input, no ``2:`` output) and two data inputs —
``3:0`` 商店归属者实体 (entity, type 1) and ``3:1`` 商店序号 (int, type 3) —
returning one aggregate on ``4:0``.

A note on the output type (a documented NEGATIVE result)
--------------------------------------------------------
The task brief that asked for these helpers called the output "a dictionary
(contract type 27)".  The contract store says otherwise, and the contract store
is authoritative (``data/node-contracts/variants/server``):

* ``714`` ``4:0`` is **serverParamType 8** (``valueType`` ``List``), named
  商品序号列表;
* ``715`` ``4:0`` is **serverParamType 22**, named 道具配置ID列表.

So the assertions below pin the *true* contract types (8 / 22), not 27, and one
test records explicitly that **neither output is type 27**.  The type-27 dict
belongs to the *inventory* table reads ``721`` / ``722`` (see
``tools/gameplan/modules/inventory.py``), which is almost certainly where the
brief's "type 27" came from.  This project still cannot write or decompose the
aggregate either way, so the same "cannot be consumed downstream" caveat holds —
but it is a type 8 / 22 aggregate, not a type 27 dict, and the test suite says so.

Every test builds a :class:`Graph`, calls the module, asserts on ``graph.plan``
**and** calls ``graph.validate()`` so a wrong pin index or a data-type mismatch
is caught exactly the way the compiler would catch it before a native call.  The
role tables in ``shop.py`` are re-derived from ``data/node-contracts`` here.

Run::

    python -B -m unittest tools.gameplan.tests.test_shop_query
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
from tools.gameplan.modules import shop
from tools.gameplan.paramtypes import DICT, SLOT_FOR_TYPE, name_of
from tools.gameplan.plan import PlanError


# The contract's serverParamType for each query node's 4:0 output.  These are
# the TRUE types (see the module docstring); the brief's "type 27" is wrong.
OUTPUT_TYPE = {714: 8, 715: 22}


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
# The role tables in shop.py must agree with data/node-contracts exactly.
# ---------------------------------------------------------------------------

class TestQueryNodeTypesMatchContracts(unittest.TestCase):
    def test_ids_are_the_documented_ones(self):
        self.assertEqual(shop.QUERY_BAG_SHOP_SALES.definition_id, 715)
        self.assertEqual(shop.QUERY_CUSTOM_SHOP_SALES.definition_id, 714)

    def test_both_definitions_exist_in_the_contract_store(self):
        store = default_store()
        for nt in shop.SHOP_QUERY_NODE_TYPES:
            with self.subTest(node=nt.label):
                self.assertIsNotNone(store.get(nt.definition_id))

    def test_declared_roles_match_contract_ports_exactly(self):
        store = default_store()
        for nt in shop.SHOP_QUERY_NODE_TYPES:
            definition = store.require(nt.definition_id)
            with self.subTest(node=nt.label):
                self.assertEqual(
                    sorted(nt.ins.values()),
                    sorted(p.index for p in definition.ports if p.kind == DATA_INPUT),
                )
                self.assertEqual(
                    sorted(nt.outs.values()),
                    sorted(p.index for p in definition.ports if p.kind == DATA_OUTPUT),
                )
                self.assertEqual(len(set(nt.ins.values())), len(nt.ins))
                self.assertEqual(len(set(nt.outs.values())), len(nt.outs))

    def test_both_declare_no_execution_input(self):
        # A query node has no execution input: the NodeType says so (exec_in is
        # None, no exec outs) *and* the contract store has no 1:/2: pins.
        store = default_store()
        for nt in shop.SHOP_QUERY_NODE_TYPES:
            with self.subTest(node=nt.label):
                self.assertIsNone(nt.exec_in)
                self.assertEqual(nt.exec_outs, {})
                definition = store.require(nt.definition_id)
                self.assertEqual(definition.exec_inputs, ())
                self.assertEqual(definition.exec_outputs, ())

    def test_holder_and_index_roles_point_at_the_right_pins(self):
        store = default_store()
        for nt in shop.SHOP_QUERY_NODE_TYPES:
            definition = store.require(nt.definition_id)
            with self.subTest(node=nt.label):
                owner = definition.port(DATA_INPUT, nt.ins["shop_owner"])
                self.assertIsNotNone(owner)
                self.assertEqual(owner.server_param_type, 1)  # entity
                idx = definition.port(DATA_INPUT, nt.ins["shop_index"])
                self.assertIsNotNone(idx)
                self.assertEqual(idx.server_param_type, 3)  # int


# ---------------------------------------------------------------------------
# Output type: the TRUE contract type, documented to be NOT the type-27 dict.
# ---------------------------------------------------------------------------

class TestQueryOutputType(unittest.TestCase):
    def test_output_type_is_the_true_contract_type(self):
        store = default_store()
        for nt in shop.SHOP_QUERY_NODE_TYPES:
            with self.subTest(node=nt.label):
                pin = store.require(nt.definition_id).port(
                    DATA_OUTPUT, nt.outs[next(iter(nt.outs))]
                )
                self.assertIsNotNone(pin)
                self.assertEqual(pin.server_param_type, OUTPUT_TYPE[nt.definition_id])

    def test_output_is_not_the_type_27_dict_the_brief_claimed(self):
        # Documented NEGATIVE result: the brief said the output is a
        # dictionary (type 27).  The contract store says 714 -> 8 (List) and
        # 715 -> 22, and NONE of them is 27.  This test fails loudly if a future
        # contract read ever moves them to 27 (which would then be good news).
        store = default_store()
        for nt in shop.SHOP_QUERY_NODE_TYPES:
            with self.subTest(node=nt.label):
                pin = store.require(nt.definition_id).port(
                    DATA_OUTPUT, nt.outs[next(iter(nt.outs))]
                )
                self.assertNotEqual(
                    pin.server_param_type, DICT,
                    f"{nt.label}: brief said type {DICT} ({name_of(DICT)}) but "
                    f"the contract moved it to {pin.server_param_type} - "
                    f"update OUTPUT_TYPE and the module docstring",
                )

    def test_no_slot_can_write_the_output_type(self):
        # Neither type 8 nor 22 has a `--slot`, so the aggregate can never be
        # *written* as a constant -- part of why it cannot be consumed.
        for code in set(OUTPUT_TYPE.values()):
            with self.subTest(code=code):
                self.assertIsNone(SLOT_FOR_TYPE.get(code))


# ---------------------------------------------------------------------------
# query_bag_sales (715)
# ---------------------------------------------------------------------------

class TestQueryBagSales(unittest.TestCase):
    def test_places_one_715_with_holder_edge_and_no_execution(self):
        g = Graph("MW_API_test_shop_qbag")
        src = _source(g)
        node = shop.query_bag_sales(g, holder=(src, "entity"), alias="q")
        self.assertEqual(node.ntype.definition_id, 715)
        self.assertEqual(len(_nodes_with_id(g.plan, 715)), 1)

        # Holder entity output -> 商店归属者实体 (3:0).
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, "q", DATA_INPUT, 0)
        )
        # A query node wires no execution edge at all.
        self.assertEqual(
            [e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], []
        )
        # No shop_index const unless one is supplied.
        self.assertIsNone(_const_at(g.plan, "q", 1))
        g.validate()

    def test_optional_shop_index_is_written_as_int_const(self):
        g = Graph("MW_API_test_shop_qbag_idx")
        src = _source(g)
        node = shop.query_bag_sales(
            g, holder=(src, "entity"), alias="q", shop_index=3
        )
        idx = _const_at(g.plan, node.alias, 1)
        self.assertIsNotNone(idx)
        self.assertEqual((idx.value, idx.slot), (3, "int"))
        g.validate()

    def test_output_role_maps_to_the_data_output(self):
        g = Graph("MW_API_test_shop_qbag_out")
        src = _source(g)
        node = shop.query_bag_sales(g, holder=(src, "entity"), alias="q")
        self.assertEqual(node.out("item_config_ids"), ("q", DATA_OUTPUT, 0))


# ---------------------------------------------------------------------------
# query_custom_sales (714)
# ---------------------------------------------------------------------------

class TestQueryCustomSales(unittest.TestCase):
    def test_places_one_714_with_holder_edge_and_no_execution(self):
        g = Graph("MW_API_test_shop_qcustom")
        src = _source(g)
        node = shop.query_custom_sales(g, holder=(src, "entity"), alias="q")
        self.assertEqual(node.ntype.definition_id, 714)
        self.assertEqual(len(_nodes_with_id(g.plan, 714)), 1)
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, "q", DATA_INPUT, 0)
        )
        self.assertEqual(
            [e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], []
        )
        self.assertIsNone(_const_at(g.plan, "q", 1))
        g.validate()

    def test_optional_shop_index_is_written_as_int_const(self):
        g = Graph("MW_API_test_shop_qcustom_idx")
        src = _source(g)
        node = shop.query_custom_sales(
            g, holder=(src, "entity"), alias="q", shop_index=0
        )
        idx = _const_at(g.plan, node.alias, 1)
        self.assertEqual((idx.value, idx.slot), (0, "int"))
        g.validate()

    def test_output_role_maps_to_the_data_output(self):
        g = Graph("MW_API_test_shop_qcustom_out")
        src = _source(g)
        node = shop.query_custom_sales(g, holder=(src, "entity"), alias="q")
        self.assertEqual(node.out("item_indices"), ("q", DATA_OUTPUT, 0))


# ---------------------------------------------------------------------------
# The aggregate output cannot be fed into an int input.
# ---------------------------------------------------------------------------

class TestQueryOutputCannotFeedAnIntInput(unittest.TestCase):
    def test_bag_output_into_an_int_input_is_rejected(self):
        # 715's aggregate output (concrete type 22) into 714's 商店序号 pin
        # (concrete int, type 3) -- validate() must reject the mismatch, which is
        # the machine-checked reason the output has no downstream int consumer.
        g = Graph("MW_API_test_shop_qbag_neg")
        src = _source(g)
        bag = shop.query_bag_sales(g, holder=(src, "entity"), alias="bag")
        custom = shop.query_custom_sales(g, holder=(src, "entity"), alias="custom")
        g.plan.wire(
            bag.alias, DATA_OUTPUT, bag.ntype.outs["item_config_ids"],
            custom.alias, DATA_INPUT, custom.ntype.ins["shop_index"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )

    def test_custom_output_into_an_int_input_is_rejected(self):
        # 714's aggregate output (concrete type 8) into 715's 商店序号 pin (int).
        g = Graph("MW_API_test_shop_qcustom_neg")
        src = _source(g)
        custom = shop.query_custom_sales(g, holder=(src, "entity"), alias="custom")
        bag = shop.query_bag_sales(g, holder=(src, "entity"), alias="bag")
        g.plan.wire(
            custom.alias, DATA_OUTPUT, custom.ntype.outs["item_indices"],
            bag.alias, DATA_INPUT, bag.ntype.ins["shop_index"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )

    def test_a_clean_query_pair_still_validates(self):
        # The same two nodes with the output left dangling (the only honest use
        # today) validate cleanly.
        g = Graph("MW_API_test_shop_qpair")
        src = _source(g)
        shop.query_bag_sales(g, holder=(src, "entity"), alias="bag", shop_index=0)
        shop.query_custom_sales(
            g, holder=(src, "entity"), alias="custom", shop_index=0
        )
        g.validate()


if __name__ == "__main__":
    unittest.main()
