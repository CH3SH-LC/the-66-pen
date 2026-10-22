"""Offline acquire-event tests: native settlement plus explicit bonuses."""
import unittest

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
# The 705 role table in nodes.py must agree with data/node-contracts.
# ---------------------------------------------------------------------------

class TestAcquireEventMatchesContract(unittest.TestCase):
    def test_705_exists_and_is_the_acquire_event(self):
        definition = default_store().require(705)
        self.assertEqual(definition.name, "商店收购道具时")
        self.assertEqual(definition.graph_kind, 20000)

    def test_declared_outs_match_contract_ports_exactly(self):
        nt = N.SHOP_BOUGHT_ITEM
        definition = default_store().require(nt.definition_id)
        self.assertEqual(
            sorted(nt.outs.values()),
            sorted(p.index for p in definition.ports if p.kind == DATA_OUTPUT),
        )
        self.assertEqual(len(set(nt.outs.values())), len(nt.outs))

    def test_the_five_documented_indices_and_types(self):
        # shop_owner 4:0 / shop_owner_guid 4:1 / seller 4:2 / shop_index 4:3 /
        # items 4:4 — verified against the contract, not trusted from prose.
        d = default_store().require(705)
        expected = {
            "shop_owner": (0, 1),        # entity
            "shop_owner_guid": (1, 2),   # guid
            "seller": (2, 1),            # entity
            "shop_index": (3, 3),        # int
            "items": (4, 27),            # dict (收购物品字典)
        }
        for role, (index, ptype) in expected.items():
            with self.subTest(role=role):
                self.assertEqual(N.SHOP_BOUGHT_ITEM.outs[role], index)
                pin = d.port(DATA_OUTPUT, index)
                self.assertIsNotNone(pin)
                self.assertEqual(pin.server_param_type, ptype)

    def test_688_holder_is_the_entity_pin(self):
        # A bonus can only land on 688's holder (type 1, entity).
        d = default_store().require(688)
        holder = d.port(DATA_INPUT, N.ADD_BAG_CURRENCY.ins["holder"])
        self.assertEqual(holder.server_param_type, 1)
        self.assertEqual(N.ADD_BAG_CURRENCY.ins["delta"], 2)


# ---------------------------------------------------------------------------
# 收购/付款 — acquire_and_pay
# ---------------------------------------------------------------------------

class TestAcquireAndPay(unittest.TestCase):
    def test_default_is_705_only(self):
        g = Graph("MW_API_acquire_native")
        event = shop.acquire_and_pay(g)
        self.assertEqual(event.ntype.definition_id, 705)
        self.assertEqual([n.definition_id for n in g.plan.nodes], [705])
        self.assertEqual(g.plan.edges, [])
        self.assertEqual(g.plan.consts, [])
        g.validate()

    def test_explicit_bonus_never_debits_seller_or_shop_owner(self):
        for recipient in ("seller", "shop_owner"):
            with self.subTest(recipient=recipient):
                g = Graph("MW_API_acquire_bonus")
                event = shop.acquire_and_pay(g, seller=recipient, currency_id=1001,
                                             bonus_amount=25, alias="acq")
                bonus = g.handle("acq_bonus")
                self.assertEqual([n.definition_id for n in g.plan.nodes], [705, 688])
                self.assertTrue(_has_edge(g.plan, event.alias, EXEC_OUTPUT, 0,
                                          bonus.alias, EXEC_INPUT, 0))
                self.assertTrue(_has_edge(g.plan, event.alias, DATA_OUTPUT, event.ntype.outs[recipient],
                                          bonus.alias, DATA_INPUT, 0))
                self.assertEqual(_const_at(g.plan, bonus.alias, 2).value, 25)
                g.validate()

    def test_old_payment_argument_is_rejected_before_placement(self):
        g = Graph("MW_API_acquire_old")
        with self.assertRaisesRegex(ValueError, "NATIVE_SHOP_AUTO_SETTLEMENT"):
            shop.acquire_and_pay(g, currency_id=1001, unit_price=25, currency_slot="int")
        self.assertEqual(g.plan.nodes, [])

    def test_bad_reward_and_selector_are_rejected(self):
        for kwargs in ({"bonus_amount": -25}, {"bonus_amount": 1}, {"bonus_amount": True}):
            g = Graph("MW_API_acquire_invalid")
            with self.assertRaises(ValueError):
                shop.acquire_and_pay(g, **kwargs)
            self.assertEqual(g.plan.nodes, [])
        g = Graph("MW_API_acquire_role")
        with self.assertRaises(KeyError):
            shop.acquire_and_pay(g, seller="buyer")
        self.assertEqual(g.plan.nodes, [])

    def test_guid_cannot_be_used_as_bonus_holder(self):
        g = Graph("MW_API_acquire_guid")
        event = shop.acquire_and_pay(g, currency_id=1001, bonus_amount=1)
        bonus = g.handle("m5_bought_bonus")
        g.plan.wire(event.alias, DATA_OUTPUT, event.ntype.outs["shop_owner_guid"],
                    bonus.alias, DATA_INPUT, 0)
        with self.assertRaises(PlanError):
            g.validate()

    def test_sale_and_acquire_compose_without_a_second_settlement(self):
        g = Graph("MW_API_shop_roundtrip_events")
        src = _source(g)
        shop.list_item_for_sale(g, src, shop_owner=(src, "entity"), shop_index=0,
                                item_id=24001, item_slot="uint", price={1001: 10})
        shop.on_bag_item_sold(g)
        shop.acquire_and_pay(g)
        self.assertNotIn(688, [n.definition_id for n in g.plan.nodes])
        g.validate()


if __name__ == "__main__":
    unittest.main()
