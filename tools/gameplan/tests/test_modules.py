"""Offline tests for the six gameplay modules (M1..M5).  No bridge, no game.

Every module is a thin wrapper over :mod:`tools.gameplan.nodes` that places an
official node and wires it to a caller-supplied execution source.  These tests
build a :class:`~tools.gameplan.nodes.Graph`, call the module function, then
assert on the resulting ``graph.plan`` (nodes / edges / consts) *and* call
``graph.validate()`` so a wrong pin, a bad const slot or a data-type mismatch is
caught exactly the way the compiler would catch it before spending a native call.

Run::

    python -B -m unittest tools.gameplan.tests.test_modules
"""

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
from tools.gameplan.modules import currency, interaction, inventory, item, shop
from tools.gameplan.paramtypes import CONFIG_ID
from tools.gameplan.plan import PlanError

# The only node kinds every module is allowed to have used.  Kept here so one
# test can re-derive "every definitionId a module places is a declared NodeType
# and therefore present in the contract store" without re-reading the sources.
MODULE_NODE_TYPES = {
    "currency": (
        N.ADD_BAG_CURRENCY,
        N.GET_BAG_CURRENCY,
        N.BAG_CURRENCY_CHANGED,
    ),
    "item": (
        N.ADD_BAG_ITEM,
        N.GET_BAG_ITEM,
        N.BAG_ITEM_ADDED,
        N.BAG_ITEM_LOST,
        N.BAG_ITEM_CHANGED,
        N.BAG_ITEM_USED,
    ),
    "inventory": (
        N.ADD_BAG_CAPACITY,
        N.GET_BAG_CAPACITY,
        N.GET_ALL_BAG_ITEMS,
        N.GET_ALL_BAG_CURRENCIES,
    ),
    "shop": (
        N.OPEN_SHOP,
        N.CLOSE_SHOP,
        N.SHOP_SOLD_BAG_ITEM,
        N.SHOP_BOUGHT_ITEM,
    ),
    "interaction": (
        N.PROXIMITY_ENTER,
        N.PROXIMITY_LEAVE,
        N.UI_CONTROL_TRIGGERED,
        N.FLOATING_PAGE_TRIGGERED,
    ),
}


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


def _edges_to(plan, dst, dst_kind=None, dst_index=None):
    return [
        e
        for e in plan.edges
        if e.dst == dst
        and (dst_kind is None or e.dst_kind == dst_kind)
        and (dst_index is None or e.dst_index == dst_index)
    ]


# ---------------------------------------------------------------------------
# currency (M2) — 688 / 691 / 684
# ---------------------------------------------------------------------------

class TestCurrencyModule(unittest.TestCase):
    def test_grant_places_one_688_and_wires_it(self):
        g = Graph("MW_API_test_currency_grant")
        src = _source(g)
        node = currency.grant(
            g,
            src,
            holder=(src, "entity"),
            currency_id=1001,
            amount=-5,
            currency_slot="int",
        )
        self.assertEqual(node.ntype.definition_id, 688)
        self.assertEqual(len(_nodes_with_id(g.plan, 688)), 1)
        self.assertEqual(node.alias, "m2_grant")

        # Execution edge source -> node.
        self.assertTrue(
            _has_edge(
                g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0
            )
        )
        # Data edge: holder (entity output) -> pin 3:0.
        self.assertTrue(
            _has_edge(
                g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0
            )
        )
        # Consts: 3:1 currency (config-id), 3:2 delta (int).
        cur = _const_at(g.plan, node.alias, 1)
        self.assertIsNotNone(cur)
        self.assertEqual(cur.value, 1001)
        self.assertEqual(cur.slot, "int")  # caller-supplied slot
        # The module deliberately leaves `expect` unset: the BUILDER derives it from
        # the contract (688 3:1 -> serverParamType 20, genericId 20).  Hardcoding it
        # here is what produced the genericId=0 bug this assertion replaced.
        self.assertIsNone(cur.expect_server_param_type)
        self.assertIsNone(cur.expect_generic_id)

        delta = _const_at(g.plan, node.alias, 2)
        self.assertIsNotNone(delta)
        self.assertEqual(delta.value, -5)
        self.assertEqual(delta.slot, "int")

        g.validate()  # must not raise

    def test_read_is_a_data_node_with_no_execution(self):
        g = Graph("MW_API_test_currency_read")
        src = _source(g)
        node = currency.read(
            g, holder=(src, "entity"), currency_id=7, currency_slot="int"
        )
        self.assertEqual(node.ntype.definition_id, 691)
        self.assertEqual(len(_nodes_with_id(g.plan, 691)), 1)
        self.assertTrue(
            _has_edge(
                g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0
            )
        )
        # A query node has no execution input, so no execution edge is present.
        self.assertEqual(
            [e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], []
        )
        cur = _const_at(g.plan, node.alias, 1)
        self.assertEqual(cur.value, 7)
        g.validate()

    def test_on_changed_is_the_event_node(self):
        g = Graph("MW_API_test_currency_changed")
        node = currency.on_changed(g)
        self.assertEqual(node.ntype.definition_id, 684)
        self.assertIn("delta", node.ntype.outs)
        self.assertIn("currency", node.ntype.outs)
        g.validate()

    def test_negative_int_output_into_bool_input_rejected(self):
        # 691.amount is a concrete int (type 3); 双分支的条件 is a concrete
        # bool (type 4).  validate() must reject the wiring.
        g = Graph("MW_API_test_currency_neg")
        src = _source(g)
        read = currency.read(
            g, holder=(src, "entity"), currency_id=1, currency_slot="int"
        )
        branch = g.place(N.BRANCH, "br")
        g.plan.wire(
            read.alias, DATA_OUTPUT, read.ntype.outs["amount"],
            branch.alias, DATA_INPUT, branch.ntype.ins["condition"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )


# ---------------------------------------------------------------------------
# item (M3) — 686 / 690 / 681 / 682 / 683 / 733
# ---------------------------------------------------------------------------

class TestItemModule(unittest.TestCase):
    def test_grant_places_one_686_and_wires_it(self):
        g = Graph("MW_API_test_item_grant")
        src = _source(g)
        node = item.grant(
            g,
            src,
            holder=(src, "entity"),
            item_id=2002,
            count=3,
            item_slot="int",
        )
        self.assertEqual(node.ntype.definition_id, 686)
        self.assertEqual(len(_nodes_with_id(g.plan, 686)), 1)

        self.assertTrue(
            _has_edge(g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0)
        )

        iid = _const_at(g.plan, node.alias, 1)
        self.assertEqual(iid.value, 2002)
        self.assertEqual(iid.slot, "int")
        # Derived by the builder from the contract, not hardcoded here.
        self.assertIsNone(iid.expect_server_param_type)
        self.assertIsNone(iid.expect_generic_id)

        delta = _const_at(g.plan, node.alias, 2)
        self.assertEqual(delta.value, 3)
        self.assertEqual(delta.slot, "int")

        g.validate()

    def test_read_places_690_as_a_query(self):
        g = Graph("MW_API_test_item_read")
        src = _source(g)
        node = item.read(
            g, holder=(src, "entity"), item_id=9, item_slot="int"
        )
        self.assertEqual(node.ntype.definition_id, 690)
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0)
        )
        self.assertEqual(
            [e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], []
        )
        self.assertEqual(_const_at(g.plan, node.alias, 1).value, 9)
        g.validate()

    def test_event_wrappers_place_their_nodes(self):
        cases = (
            (item.on_added, 681),
            (item.on_lost, 682),
            (item.on_changed, 683),
            (item.on_used, 733),
        )
        for func, expected in cases:
            with self.subTest(event=func.__name__):
                g = Graph("MW_API_test_item_evt")
                node = func(g)
                self.assertEqual(node.ntype.definition_id, expected)
                g.validate()

    def test_negative_int_output_into_bool_input_rejected(self):
        # 690.amount is a concrete int (type 3); 双分支的条件 is a concrete
        # bool (type 4).  validate() must reject the wiring.
        g = Graph("MW_API_test_item_neg")
        src = _source(g)
        read = item.read(g, holder=(src, "entity"), item_id=1, item_slot="int")
        br = g.place(N.BRANCH, "br")
        g.plan.wire(
            read.alias, DATA_OUTPUT, read.ntype.outs["amount"],
            br.alias, DATA_INPUT, br.ntype.ins["condition"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )


# ---------------------------------------------------------------------------
# inventory (M4) — 689 / 685 / 721 / 722
# ---------------------------------------------------------------------------

class TestInventoryModule(unittest.TestCase):
    def test_capacity_places_689(self):
        g = Graph("MW_API_test_inv_capacity")
        src = _source(g)
        node = inventory.capacity(g, holder=(src, "entity"))
        self.assertEqual(node.ntype.definition_id, 689)
        self.assertEqual(len(_nodes_with_id(g.plan, 689)), 1)
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0)
        )
        self.assertEqual(
            [e for e in g.plan.edges if e.dst_kind == EXEC_INPUT], []
        )
        g.validate()

    def test_grow_places_685_with_delta_const(self):
        g = Graph("MW_API_test_inv_grow")
        src = _source(g)
        node = inventory.grow(g, src, holder=(src, "entity"), amount=50)
        self.assertEqual(node.ntype.definition_id, 685)
        self.assertTrue(
            _has_edge(g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0)
        )
        delta = _const_at(g.plan, node.alias, 1)
        self.assertEqual(delta.value, 50)
        self.assertEqual(delta.slot, "int")
        g.validate()

    def test_all_items_and_currencies_are_data_queries(self):
        g_items = Graph("MW_API_test_inv_all_items")
        src = _source(g_items)
        node = inventory.all_items(g_items, holder=(src, "entity"))
        self.assertEqual(node.ntype.definition_id, 721)
        self.assertTrue(
            _has_edge(
                g_items.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0
            )
        )
        g_items.validate()

        g_cur = Graph("MW_API_test_inv_all_cur")
        src2 = _source(g_cur)
        node2 = inventory.all_currencies(g_cur, holder=(src2, "entity"))
        self.assertEqual(node2.ntype.definition_id, 722)
        self.assertTrue(
            _has_edge(
                g_cur.plan, "src", DATA_OUTPUT, 0, node2.alias, DATA_INPUT, 0
            )
        )
        g_cur.validate()

    def test_negative_capacity_into_bool_input_rejected(self):
        # 689.capacity (int, type 3) into 双分支.condition (bool, type 4).
        g = Graph("MW_API_test_inv_neg")
        src = _source(g)
        cap = inventory.capacity(g, holder=(src, "entity"))
        br = g.place(N.BRANCH, "br")
        g.plan.wire(
            cap.alias, DATA_OUTPUT, cap.ntype.outs["capacity"],
            br.alias, DATA_INPUT, br.ntype.ins["condition"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )


# ---------------------------------------------------------------------------
# shop (M5) — 702 / 703 / 701 / 705
# ---------------------------------------------------------------------------

class TestShopModule(unittest.TestCase):
    def test_open_places_702_with_player_owner_index(self):
        g = Graph("MW_API_test_shop_open")
        src = _source(g)
        node = shop.open_(
            g,
            src,
            player=(src, "entity"),
            shop_owner=(src, "entity"),
            shop_index=2,
        )
        self.assertEqual(node.ntype.definition_id, 702)
        self.assertEqual(len(_nodes_with_id(g.plan, 702)), 1)

        self.assertTrue(
            _has_edge(g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0)
        )
        # player -> 3:0, shop_owner -> 3:1
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(g.plan, "src", DATA_OUTPUT, 0, node.alias, DATA_INPUT, 1)
        )
        idx = _const_at(g.plan, node.alias, 2)
        self.assertEqual(idx.value, 2)
        self.assertEqual(idx.slot, "int")
        g.validate()

    def test_close_places_703_with_player_only(self):
        g = Graph("MW_API_test_shop_close")
        src = _source(g)
        node = shop.close(g, src, player=(src, "entity"))
        self.assertEqual(node.ntype.definition_id, 703)
        self.assertTrue(
            _has_edge(g.plan, "src", EXEC_OUTPUT, 0, node.alias, EXEC_INPUT, 0)
        )
        # Only the player pin (3:0) is wired; 703 has no owner/index pins.
        edges = _edges_to(g.plan, node.alias, DATA_INPUT)
        self.assertEqual([e.dst_index for e in edges], [0])
        self.assertEqual(_const_at(g.plan, node.alias, 1), None)
        self.assertEqual(_const_at(g.plan, node.alias, 2), None)
        g.validate()

    def test_event_wrappers_place_701_and_705(self):
        g = Graph("MW_API_test_shop_evt")
        sold = shop.on_sold_bag_item(g)
        self.assertEqual(sold.ntype.definition_id, 701)
        bought = shop.on_shop_bought(g)
        self.assertEqual(bought.ntype.definition_id, 705)
        g.validate()

    def test_negative_entity_into_shop_index_rejected(self):
        # The owner entity output (type 1) must not feed the int shop index
        # pin (type 3) — a concrete concrete mismatch.
        g = Graph("MW_API_test_shop_neg")
        src = _source(g)
        node = shop.open_(
            g,
            src,
            player=(src, "entity"),
            shop_owner=(src, "entity"),
            shop_index=0,
        )
        g.plan.wire(
            src.alias, DATA_OUTPUT, 0,
            node.alias, DATA_INPUT, 2,  # shop_index
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )


# ---------------------------------------------------------------------------
# interaction (M1) — 92 / 91 / 316 / 826 / 679
# ---------------------------------------------------------------------------

class TestInteractionModule(unittest.TestCase):
    def test_kinds_registry_is_complete(self):
        self.assertEqual(
            set(interaction.KINDS),
            {"proximity", "proximity-exit", "ui-button", "floating-page",
             "text-bubble"},
        )
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                self.assertIsInstance(kind.scene_half, str)
                self.assertTrue(
                    kind.scene_half.strip(),
                    "scene_half documents the mandatory manual editor step",
                )

    def test_event_places_the_kind_definition(self):
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                g = Graph("MW_API_test_interaction")
                node = interaction.event(g, kind, "evt")
                self.assertEqual(node.ntype.definition_id, kind.event_definition_id)
                self.assertEqual(len(_nodes_with_id(g.plan, kind.event_definition_id)), 1)
                g.validate()

    def test_event_definition_ids_are_the_documented_ones(self):
        self.assertEqual(interaction.PROXIMITY.event_definition_id, 92)
        self.assertEqual(interaction.PROXIMITY_EXIT.event_definition_id, 91)
        self.assertEqual(interaction.UI_BUTTON.event_definition_id, 316)
        self.assertEqual(interaction.FLOATING_PAGE.event_definition_id, 826)

    def test_convenience_wrappers_place_their_nodes(self):
        cases = (
            (interaction.proximity_enter, 92),
            (interaction.proximity_leave, 91),
            (interaction.ui_control_triggered, 316),
            (interaction.floating_page_triggered, 826),
        )
        for func, expected in cases:
            with self.subTest(wrapper=func.__name__):
                g = Graph("MW_API_test_interaction_wrap")
                node = func(g)
                self.assertEqual(node.ntype.definition_id, expected)
                g.validate()

    def test_event_used_as_an_execution_source(self):
        # M1 is the shared trigger source: its "then" output drives a module.
        g = Graph("MW_API_test_interaction_flow")
        enter = interaction.proximity_enter(g)
        give = currency.grant(
            g,
            enter,
            holder=(enter, "entrant"),
            currency_id=1,
            amount=1,
            currency_slot="int",
        )
        self.assertTrue(
            _has_edge(
                g.plan, enter.alias, EXEC_OUTPUT, 0, give.alias, EXEC_INPUT, 0
            )
        )
        self.assertTrue(
            _has_edge(
                g.plan, enter.alias, DATA_OUTPUT, 0, give.alias, DATA_INPUT, 0
            )
        )
        g.validate()

    def test_unknown_kind_raises_keyerror(self):
        g = Graph("MW_API_test_interaction_bad")
        bogus = interaction.InteractionKind("bogus", "?", 999999, "x")
        with self.assertRaises(KeyError):
            interaction.event(g, bogus, "evt")

    def test_negative_entrant_into_bool_input_rejected(self):
        # 92.entrant (entity, type 1) into 双分支.condition (bool, type 4).
        g = Graph("MW_API_test_interaction_neg")
        enter = interaction.proximity_enter(g)
        br = g.place(N.BRANCH, "br")
        g.plan.wire(
            enter.alias, DATA_OUTPUT, enter.ntype.outs["entrant"],
            br.alias, DATA_INPUT, br.ntype.ins["condition"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )


# ---------------------------------------------------------------------------
# Every definitionId the modules use must be a declared NodeType -> in the store
# ---------------------------------------------------------------------------

class TestModuleDefinitionsAreContractBacked(unittest.TestCase):
    def test_all_module_node_types_are_declared_and_in_store(self):
        declared = {nt.definition_id for nt in N.ALL_NODE_TYPES}
        store = default_store()
        for module_name, ntypes in MODULE_NODE_TYPES.items():
            for nt in ntypes:
                with self.subTest(module=module_name, node=nt.label):
                    self.assertIn(
                        nt.definition_id,
                        declared,
                        f"{module_name}: {nt.label} ({nt.definition_id}) "
                        f"is not in nodes.ALL_NODE_TYPES",
                    )
                    self.assertIsNotNone(
                        store.get(nt.definition_id),
                        f"{module_name}: definitionId {nt.definition_id} "
                        f"is not in the contract store",
                    )

    def test_every_entity_returning_module_builds_a_valid_graph(self):
        """A smoke graph exercising all five modules validates as one plan."""
        g = Graph("MW_API_test_all_modules")
        src = _source(g)

        currency.grant(
            g, src, holder=(src, "entity"), currency_id=1, amount=1,
            currency_slot="int",
        )
        item.grant(
            g, src, holder=(src, "entity"), item_id=1, count=1, item_slot="int"
        )
        inventory.grow(g, src, holder=(src, "entity"), amount=10)
        shop.open_(
            g, src, player=(src, "entity"), shop_owner=(src, "entity"),
            shop_index=0,
        )
        shop.close(g, src, player=(src, "entity"))
        g.validate()


if __name__ == "__main__":
    unittest.main()
