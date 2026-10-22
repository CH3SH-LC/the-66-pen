"""Offline contract and compiler tests; fixture IDs are not live assets."""
import json
import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.builder import GraphBuilder
from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_OUTPUT, default_store
from tools.gameplan.economy_catalog import (
    CATALOG_NODE_TYPES, PurchaseProduct, SaleProduct, add_purchase, add_sale,
    build_catalog_plan, install_catalog, price_entries,
)

# Explicit OFFLINE fixtures, never presented as assets from a user's level.
SEED, CROP, COIN, GEM = 1107296257, 1107296258, 1115684865, 1115684866


class EconomyCatalogTests(unittest.TestCase):
    def graph(self):
        graph = Graph("MW_API_catalog_test")
        created = graph.place(N.ON_CREATE, "created")
        return graph, created

    def test_contract_roles_and_types(self):
        for nt in CATALOG_NODE_TYPES:
            with self.subTest(node=nt.definition_id):
                definition = default_store().require(nt.definition_id)
                self.assertEqual([p.index for p in definition.exec_inputs], [nt.exec_in])
                self.assertEqual([p.index for p in definition.exec_outputs], [0])
                self.assertEqual(set(nt.ins.values()),
                                 {p.index for p in definition.ports if p.kind == DATA_INPUT})
                self.assertEqual(set(nt.outs.values()),
                                 {p.index for p in definition.ports if p.kind == DATA_OUTPUT})
                self.assertEqual(definition.port(DATA_INPUT, nt.ins["price"]).server_param_type, 27)
                self.assertEqual(definition.port(DATA_INPUT, nt.ins["item"]).server_param_type, 20)
                for role in ("limited", "sellable", "purchasable"):
                    if role in nt.ins:
                        self.assertEqual(definition.port(DATA_INPUT, nt.ins[role]).server_param_type, 4)

    def test_prices_are_sorted_and_explicitly_tagged(self):
        self.assertEqual(price_entries({GEM: 3, COIN: 5}), [
            {"key": {"uint": COIN}, "value": {"int": 5}},
            {"key": {"uint": GEM}, "value": {"int": 3}},
        ])

    def test_price_refuses_bad_ids_amounts_and_tags(self):
        for price in ({}, {True: 1}, {COIN: True}, {COIN: 0}, {COIN: -1},
                      {0: 1}, {COIN: 2**31}, {2**32: 1},
                      {i: 1 for i in range(1, 66)}):
            with self.subTest(price=price), self.assertRaises(ValueError):
                price_entries(price)
        for tag in ("string", "float", "dict"):
            with self.assertRaises(ValueError):
                price_entries({COIN: 1}, key_tag=tag)
        self.assertEqual(price_entries({2**32 - 1: 2**32 - 1}, key_tag="uint", value_tag="uint")
                         [0]["value"], {"uint": 2**32 - 1})
        with self.assertRaises(ValueError):
            price_entries({2**31: 1}, key_tag="int")
        self.assertEqual(price_entries({COIN: 1}, key_tag="int")[0]["key"], {"int": COIN})

    def test_append_sale_sets_every_pin_and_exposes_index(self):
        g, created = self.graph()
        node = add_sale(g, created, shop_owner=(created, "entity"), shop_index=2,
                        product=SaleProduct(SEED, {COIN: 5}, limit_count=3))
        constants = {c.port_index: (c.value, c.slot) for c in g.plan.consts}
        self.assertEqual(node.ntype.definition_id, 708)
        self.assertEqual(node.out("item_index"), (node.alias, DATA_OUTPUT, 0))
        self.assertEqual(set(constants), set(range(1, 9)))
        self.assertEqual(constants[3], ({"dict": price_entries({COIN: 5})}, "auto"))
        self.assertEqual(constants[5], (1, "enum"))
        self.assertEqual(constants[6], (3, "int"))
        self.assertEqual([(e.src, e.src_index) for e in g.plan.edges
                          if e.dst == node.alias and e.dst_kind == DATA_INPUT], [("created", 0)])
        g.validate()

    def test_purchase_and_sale_install_serially_without_double_payment(self):
        g, created = self.graph()
        result = install_catalog(g, created, shop_owner=(created, "entity"), shop_index=0,
                                 sales=[SaleProduct(SEED, {COIN: 5})],
                                 purchases=[PurchaseProduct(CROP, {COIN: 10})])
        self.assertEqual([n.definition_id for n in g.plan.nodes], [71, 708, 710])
        self.assertEqual([(e.src, e.dst) for e in g.plan.edges if e.src_kind == EXEC_OUTPUT],
                         [("created", "catalog_sale_0"), ("catalog_sale_0", "catalog_purchase_0")])
        self.assertIs(result.last, result.purchases[0])
        self.assertEqual({e.src for e in g.plan.edges if e.dst_kind == DATA_INPUT}, {"created"})
        self.assertNotIn(688, [n.definition_id for n in g.plan.nodes])
        g.validate()

    def test_complete_startup_plan_and_batch_payload(self):
        plan = build_catalog_plan("MW_API_catalog_ready", shop_index=1,
                                  sales=[SaleProduct(SEED, {COIN: 5})],
                                  purchases=[PurchaseProduct(CROP, {COIN: 10, GEM: 2})])
        self.assertEqual([n.definition_id for n in plan.nodes], [71, 708, 710, 1])
        plan.validate()
        builder = GraphBuilder(plan, lambda _: self.fail("offline compiler dispatched"), run_id="offline")
        payload = builder.batch_plan_json()
        encoded = json.dumps(payload)
        self.assertIn('"dict": [', encoded)
        # The compiler preserves a container object, rather than printing its repr.
        prices = [v["value"] for v in payload["values"] if "dict" in v["value"]]
        self.assertEqual(prices, [{"dict": price_entries({COIN: 5})},
                                  {"dict": price_entries({COIN: 10, GEM: 2})}])
        flags = [v["value"] for v in payload["values"]
                 if v["node"] in (1, 2) and
                 v["portIndex"] in ((5, 8) if v["node"] == 1 else (4,))]
        self.assertEqual(flags, [{"uint": 0}, {"uint": 1}, {"uint": 1}])

    def test_invalid_late_product_leaves_graph_unchanged(self):
        g, created = self.graph()
        with self.assertRaises(ValueError):
            install_catalog(g, created, shop_owner=(created, "entity"), shop_index=0,
                            sales=[SaleProduct(SEED, {COIN: 5})],
                            purchases=[PurchaseProduct(CROP, {COIN: 0})])
        self.assertEqual((len(g.plan.nodes), len(g.plan.edges), len(g.plan.consts)), (1, 0, 0))

    def test_duplicate_side_is_rejected_but_cross_side_is_valid(self):
        g, created = self.graph()
        with self.assertRaises(ValueError):
            install_catalog(g, created, shop_owner=(created, "entity"), shop_index=0,
                            sales=[SaleProduct(SEED, {COIN: 5})] * 2)
        self.assertEqual(len(g.plan.nodes), 1)
        install_catalog(g, created, shop_owner=(created, "entity"), shop_index=0,
                        sales=[SaleProduct(SEED, {COIN: 5})],
                        purchases=[PurchaseProduct(SEED, {COIN: 2})])
        g.validate()

    def test_wrong_owner_graph_and_alias_collision_are_atomic(self):
        for foreign in (True, False):
            with self.subTest(foreign=foreign):
                g, created = self.graph()
                other, other_created = self.graph()
                if not foreign:
                    g.place(N.PRINT, "catalog_sale_0")
                before = (len(g.plan.nodes), len(g.plan.edges), len(g.plan.consts))
                with self.assertRaises(ValueError):
                    install_catalog(g, created,
                                    shop_owner=(other_created if foreign else created, "entity"),
                                    shop_index=0, sales=[SaleProduct(SEED, {COIN: 1})])
                self.assertEqual(before, (len(g.plan.nodes), len(g.plan.edges), len(g.plan.consts)))

    def test_invalid_product_scalars_do_not_mutate_graph(self):
        for product in (SaleProduct(True, {COIN: 1}), SaleProduct(SEED, {COIN: 1}, tab_index=0),
                        SaleProduct(SEED, {COIN: 1}, limit_count=0),
                        SaleProduct(SEED, {COIN: 1}, sellable=1),
                        SaleProduct(SEED, {COIN: 1}, sort_priority=-1)):
            with self.subTest(product=product):
                g, created = self.graph()
                with self.assertRaises(ValueError):
                    add_sale(g, created, shop_owner=(created, "entity"), shop_index=0, product=product)
                self.assertEqual(len(g.plan.nodes), 1)

    def test_purchase_can_be_disabled_with_explicit_uint_price(self):
        g, created = self.graph()
        node = add_purchase(g, created, shop_owner=(created, "entity"), shop_index=0,
                            product=PurchaseProduct(CROP, {COIN: 7}, purchasable=False),
                            key_tag="uint", value_tag="uint", flag_slot="bool")
        constants = {c.port_index: c.value for c in g.plan.consts if c.alias == node.alias}
        self.assertIs(constants[4], False)
        self.assertEqual(constants[3], {"dict": price_entries({COIN: 7}, key_tag="uint", value_tag="uint")})
        g.validate()

    def test_flag_slot_override_is_validated_before_mutation(self):
        g, created = self.graph()
        with self.assertRaisesRegex(ValueError, "flag_slot"):
            install_catalog(g, created, shop_owner=(created, "entity"), shop_index=0,
                            sales=[SaleProduct(SEED, {COIN: 1})], flag_slot="auto")
        self.assertEqual((len(g.plan.nodes), len(g.plan.edges), len(g.plan.consts)), (1, 0, 0))
        plan = build_catalog_plan("MW_API_catalog_bool", shop_index=0,
                                  sales=[SaleProduct(SEED, {COIN: 1}, sellable=False)],
                                  purchases=[PurchaseProduct(CROP, {COIN: 1})], flag_slot="bool")
        flags = [c for c in plan.consts if c.slot == "bool"]
        self.assertEqual([c.value for c in flags], [False, False, True])


if __name__ == "__main__":
    unittest.main()
