"""Offline sale-table compilation and automatic-trade event tests."""
import unittest

from tools.gameplan.builder import GraphBuilder

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    default_store,
)
from tools.gameplan.modules import shop
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


def _edges_to(plan, dst, dst_kind=None, dst_index=None):
    return [
        e
        for e in plan.edges
        if e.dst == dst
        and (dst_kind is None or e.dst_kind == dst_kind)
        and (dst_index is None or e.dst_index == dst_index)
    ]


# ---------------------------------------------------------------------------
# The role tables in shop.py must agree with data/node-contracts exactly.
# ---------------------------------------------------------------------------

class TestShopTableNodeTypesMatchContracts(unittest.TestCase):
    def test_every_shop_table_definition_exists(self):
        store = default_store()
        for nt in shop.SHOP_TABLE_NODE_TYPES:
            with self.subTest(node=nt.label):
                self.assertIsNotNone(
                    store.get(nt.definition_id),
                    f"{nt.label} ({nt.definition_id}) is not in the contract store",
                )

    def test_shop_table_ids_are_the_documented_ones(self):
        self.assertEqual(shop.ADD_BAG_SHOP_ITEM.definition_id, 709)
        self.assertEqual(shop.SET_BAG_SHOP_ITEM.definition_id, 706)
        self.assertEqual(shop.SET_CUSTOM_SHOP_ITEM.definition_id, 704)

    def test_declared_roles_match_contract_ports_exactly(self):
        store = default_store()
        for nt in shop.SHOP_TABLE_NODE_TYPES:
            definition = store.require(nt.definition_id)
            with self.subTest(node=nt.label):
                self.assertEqual(
                    sorted(p.index for p in definition.exec_inputs), [nt.exec_in]
                )
                self.assertEqual(
                    sorted(nt.exec_outs.values()),
                    sorted(p.index for p in definition.exec_outputs),
                )
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

    def test_price_role_points_at_the_type_27_dict_pin(self):
        # The refusal target must be the dictionary pin, verified against the
        # contract (type 27), not a guess.
        store = default_store()
        for nt in shop.SHOP_TABLE_NODE_TYPES:
            with self.subTest(node=nt.label):
                pin = store.require(nt.definition_id).port(
                    DATA_INPUT, nt.ins["price"]
                )
                self.assertIsNotNone(pin)
                self.assertEqual(pin.server_param_type, 27)


# ---------------------------------------------------------------------------
# 创建商品 — list_item_for_sale
# ---------------------------------------------------------------------------

class TestListItemForSale(unittest.TestCase):
    def build(self, **kwargs):
        g = Graph("MW_API_test_shop_list")
        src = _source(g)
        node = shop.list_item_for_sale(g, src, shop_owner=(src, "entity"),
                                      shop_index=2, item_id=24001, item_slot="uint", **kwargs)
        g.validate()
        return g, node

    def test_bag_default_keeps_template_price(self):
        for store, definition in (("bag-add", 709), ("bag-set", 706)):
            with self.subTest(store=store):
                g, node = self.build(store=store)
                self.assertEqual(node.ntype.definition_id, definition)
                self.assertIsNone(_const_at(g.plan, node.alias, 3))
                self.assertEqual(_edges_to(g.plan, node.alias, DATA_INPUT, 3), [])
                self.assertTrue(_has_edge(g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0))
                self.assertTrue(_has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0))
                self.assertEqual(_const_at(g.plan, node.alias, 1).value, 2)
                self.assertEqual((_const_at(g.plan, node.alias, 2).value,
                                  _const_at(g.plan, node.alias, 2).slot), (24001, "uint"))
                self.assertEqual((_const_at(g.plan, node.alias, 6).value,
                                  _const_at(g.plan, node.alias, 6).slot), (1, "enum"))

    def test_all_three_price_writers_compile_tagged_pairs(self):
        for store, definition, price_port in (("bag-add", 709, 3), ("bag-set", 706, 3),
                                               ("custom", 704, 4)):
            with self.subTest(store=store):
                custom = {"item_index": 0, "limit_count": 4} if store == "custom" else {}
                g, node = self.build(store=store, price={1002: 3, 1001: 25}, **custom)
                self.assertEqual(node.ntype.definition_id, definition)
                builder = GraphBuilder(g.plan, lambda _: self.fail("offline dispatch"), run_id="offline")
                payload = builder.batch_plan_json()
                value = next(v for v in payload["values"] if v["portIndex"] == price_port)
                self.assertEqual(value["slot"], "auto")
                self.assertEqual(value["value"], {"dict": [
                    {"key": {"uint": 1001}, "value": {"int": 25}},
                    {"key": {"uint": 1002}, "value": {"int": 3}}]})
                if store == "custom":
                    self.assertEqual({c.port_index for c in g.plan.consts}, set(range(1, 10)))
                    self.assertEqual(_const_at(g.plan, node.alias, 2).value, 0)
                    self.assertEqual((_const_at(g.plan, node.alias, 6).value,
                                      _const_at(g.plan, node.alias, 6).slot), (1, "enum"))
                    self.assertEqual(_const_at(g.plan, node.alias, 7).value, 4)

    def test_custom_unlimited_and_bool_override(self):
        g, node = self.build(store="custom", item_index=7, price={1001: 1},
                             flag_slot="bool", sellable=False)
        self.assertEqual((_const_at(g.plan, node.alias, 6).value,
                          _const_at(g.plan, node.alias, 6).slot), (False, "bool"))
        self.assertEqual(_const_at(g.plan, node.alias, 7).value, 0)
        self.assertIs(_const_at(g.plan, node.alias, 9).value, False)

    def test_explicit_price_leaf_tags_are_preserved(self):
        g, node = self.build(price={1001: 5}, key_tag="int", value_tag="uint")
        self.assertEqual(_const_at(g.plan, node.alias, 3).value,
                         {"dict": [{"key": {"int": 1001}, "value": {"uint": 5}}]})

    def test_invalid_input_is_atomic(self):
        bad = [{"store": "custom", "price": {1001: 1}},
               {"store": "custom", "item_index": 0},
               {"store": "custom", "item_index": -1, "price": {1001: 1}},
               {"store": "custom", "item_index": 0, "price": {1001: 1}, "limit_count": 0},
               {"price": {}}, {"price": {1001: 0}}, {"price": {True: 1}},
               {"price": {1001: True}}, {"flag_slot": "int"}, {"sellable": 1},
               {"tab_index": 5}, {"sort_priority": -1}, {"limit_count": 1}, {"item_index": 0}]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                g = Graph("MW_API_bad_shop")
                src = _source(g)
                with self.assertRaises(ValueError):
                    shop.list_item_for_sale(g, src, shop_owner=(src, "entity"),
                                            shop_index=0, item_id=1, item_slot="uint", **kwargs)
                self.assertEqual((len(g.plan.nodes), len(g.plan.edges), len(g.plan.consts)), (1, 0, 0))

    def test_unknown_store_is_rejected(self):
        with self.assertRaises(KeyError):
            self.build(store="unknown")

    def test_wrong_owner_graph_is_rejected_before_placement(self):
        g = Graph("MW_API_shop_owner")
        other = Graph("MW_API_other_owner")
        src, foreign = _source(g), _source(other)
        with self.assertRaises(ValueError):
            shop.list_item_for_sale(g, src, shop_owner=(foreign, "entity"),
                                    shop_index=0, item_id=1, item_slot="uint", price={1001: 1})
        self.assertEqual(len(g.plan.nodes), 1)


class TestPurchaseHandling(unittest.TestCase):
    def test_native_trade_event_never_repeats_settlement_by_default(self):
        g = Graph("MW_API_native_shop_settlement")
        event = shop.on_bag_item_sold(g)
        self.assertEqual(event.ntype.definition_id, 701)
        self.assertEqual([n.definition_id for n in g.plan.nodes], [701])
        self.assertEqual(g.plan.edges, [])
        self.assertEqual(g.plan.consts, [])
        g.validate()

    def test_explicit_bonus_credits_exactly_one_known_holder(self):
        for payee in ("shop_owner", "buyer"):
            with self.subTest(payee=payee):
                g = Graph("MW_API_shop_bonus")
                event = shop.on_bag_item_sold(g, currency_id=1001, bonus_amount=7, payee=payee)
                bonus = g.handle("m5_sold_bonus")
                self.assertEqual([n.definition_id for n in g.plan.nodes], [701, 688])
                self.assertTrue(_has_edge(g.plan, event.alias, EXEC_OUTPUT, 0,
                                          bonus.alias, EXEC_INPUT, 0))
                self.assertTrue(_has_edge(g.plan, event.alias, DATA_OUTPUT, event.ntype.outs[payee],
                                          bonus.alias, DATA_INPUT, 0))
                self.assertEqual((_const_at(g.plan, bonus.alias, 1).value,
                                  _const_at(g.plan, bonus.alias, 1).slot), (1001, "uint"))
                self.assertEqual(_const_at(g.plan, bonus.alias, 2).value, 7)
                g.validate()

    def test_legacy_unit_price_is_named_failure_without_mutation(self):
        g = Graph("MW_API_shop_old_price")
        with self.assertRaisesRegex(ValueError, "NATIVE_SHOP_AUTO_SETTLEMENT"):
            shop.on_bag_item_sold(g, currency_id=1001, unit_price=25, currency_slot="int")
        self.assertEqual(g.plan.nodes, [])

    def test_invalid_bonus_and_unknown_recipient_place_nothing(self):
        for kwargs in ({"bonus_amount": -1}, {"bonus_amount": True},
                       {"bonus_amount": 1}, {"bonus_amount": 1, "currency_id": 0},
                       {"bonus_amount": 1, "currency_id": 1, "currency_slot": "bool"}):
            g = Graph("MW_API_bad_bonus")
            with self.assertRaises(ValueError):
                shop.on_bag_item_sold(g, **kwargs)
            self.assertEqual(g.plan.nodes, [])
        g = Graph("MW_API_bad_payee")
        with self.assertRaises(KeyError):
            shop.on_bag_item_sold(g, payee="unknown")
        self.assertEqual(g.plan.nodes, [])

    def test_bonus_alias_collision_does_not_leave_event(self):
        g = Graph("MW_API_bonus_alias")
        g.place(N.PRINT, "reward")
        with self.assertRaises(ValueError):
            shop.on_bag_item_sold(g, currency_id=1, bonus_amount=1, pay_alias="reward")
        self.assertEqual([n.definition_id for n in g.plan.nodes], [1])

    def test_raw_event_helper_remains_event_only(self):
        g = Graph("MW_API_shop_event")
        shop.on_sold_bag_item(g)
        self.assertEqual([n.definition_id for n in g.plan.nodes], [701])
        g.validate()


if __name__ == "__main__":
    unittest.main()
