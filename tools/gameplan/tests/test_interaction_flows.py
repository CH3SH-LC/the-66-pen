"""Cross-module interaction flows: one M1 event, two execution sinks.

This is a *composition* test, not a module test.  M1 (``interaction``) is the
shared trigger source every other module hangs off; M2 (``currency``) and M3
(``item``) are the two "grant something to the entrant" sinks.  The flow we
build and validate here is the minimal statement of "when the player steps into
the trigger, they gain both an item and some currency":

    进入碰撞触发器时 (92) --then--> 增加背包道具数量 (686)
                          \\--then--> 增加背包货币数量 (688)

One event node fans out to two execution sinks (both ``then`` edges leave the
*same* ``92`` execution output, kind 2 at index 0), and each sink draws its
``holder`` from the *same* ``92`` entrant-entity output (data kind 4 at index 0,
into the sink's holder input, data kind 3 at index 0).

``92`` also exposes its entrant **GUID** at 4:1 (a type-2 value).  Handing a GUID
to a holder input (type 1) is the mistake this test exists to lock out: the
compiler must reject it as a concrete/concrete type mismatch, and the negative
case asserts exactly that.

The whole file is offline.  It builds ``Graph`` plans, calls ``validate()`` and
inspects the resulting ``plan`` -- it never talks to the bridge or the game.

Run::

    python -B -m unittest tools.gameplan.tests.test_interaction_flows
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
from tools.gameplan.modules import currency, interaction, item
from tools.gameplan.plan import PlanError

# The entrant-entity output of an interaction event and the holder input of a
# grant sink, by pin index.  Read from the contracts in the tests below rather
# than trusted blindly here.
ENTRANT_DATA_OUT = 0     # 92 4:0 进入者实体 (type 1) / 316 4:0 事件源实体 (type 1)
ENTRANT_GUID_OUT = 1     # 92 4:1 进入者实体GUID (type 2)
HOLDER_DATA_IN = 0       # 686/688 3:0 背包持有者实体 (type 1)
THEN_EXEC_OUT = 0        # 92/316 2:0 execution output
SINK_EXEC_IN = 0         # 686/688 1:0 execution input


# ---------------------------------------------------------------------------
# plan-inspection helpers (pure reads; nothing here mutates the graph)
# ---------------------------------------------------------------------------

def _edges_from(plan, src, src_kind):
    return [e for e in plan.edges if e.src == src and e.src_kind == src_kind]


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


def _fan_out(g: Graph, source_alias: str):
    """Wire one interaction event to BOTH grant sinks; return (event, 686, 688).

    Both sinks take ``holder`` from the event's entrant-entity output and both
    are driven by the event's single ``then`` execution output.
    """
    if source_alias == "ui":
        event = interaction.ui_control_triggered(g, source_alias)
        holder_role = "entity"
    else:
        event = interaction.proximity_enter(g, source_alias)
        holder_role = "entrant"

    give_item = item.grant(
        g,
        event,
        holder=(event, holder_role),
        item_id=2001,
        count=3,
        item_slot="int",
        alias="give_item",
    )
    give_currency = currency.grant(
        g,
        event,
        holder=(event, holder_role),
        currency_id=1001,
        amount=5,
        currency_slot="int",
        alias="give_currency",
    )
    return event, give_item, give_currency


# ---------------------------------------------------------------------------
# The fan-out: 92 (进入碰撞触发器时) -> {686, 688}
# ---------------------------------------------------------------------------

class TestProximityFanOut(unittest.TestCase):
    def test_one_event_fans_out_to_both_sinks(self):
        g = Graph("MW_API_test_flow_fanout")
        event, give_item, give_currency = _fan_out(g, "enter")

        self.assertEqual(event.ntype.definition_id, 92)
        self.assertEqual(give_item.ntype.definition_id, 686)
        self.assertEqual(give_currency.ntype.definition_id, 688)

        # Validated before any native call -- no bridge involved.
        g.validate()

    def test_both_exec_edges_leave_the_same_92_output(self):
        g = Graph("MW_API_test_flow_exec")
        event, give_item, give_currency = _fan_out(g, "enter")

        # Exactly two execution edges, and BOTH leave 92 kind 2 index 0.
        exec_edges = _edges_from(g.plan, event.alias, EXEC_OUTPUT)
        self.assertEqual(len(exec_edges), 2, "the event must drive two sinks")
        self.assertEqual({e.src_index for e in exec_edges}, {THEN_EXEC_OUT})

        # One lands on each sink's execution input (kind 1, index 0).
        self.assertTrue(
            _has_edge(
                g.plan, event.alias, EXEC_OUTPUT, THEN_EXEC_OUT,
                give_item.alias, EXEC_INPUT, SINK_EXEC_IN,
            )
        )
        self.assertTrue(
            _has_edge(
                g.plan, event.alias, EXEC_OUTPUT, THEN_EXEC_OUT,
                give_currency.alias, EXEC_INPUT, SINK_EXEC_IN,
            )
        )
        g.validate()

    def test_each_sink_holder_comes_from_92_entrant_entity_output(self):
        g = Graph("MW_API_test_flow_holder")
        event, give_item, give_currency = _fan_out(g, "enter")

        # entrant (4:0) -> holder (3:0) on BOTH sinks, from the same source pin.
        for sink in (give_item, give_currency):
            with self.subTest(sink=sink.alias):
                self.assertTrue(
                    _has_edge(
                        g.plan, event.alias, DATA_OUTPUT, ENTRANT_DATA_OUT,
                        sink.alias, DATA_INPUT, HOLDER_DATA_IN,
                    )
                )
        g.validate()

    def test_entrant_pin_is_an_entity_and_guid_pin_is_not(self):
        # The claim "4:0 is the entity, 4:1 is the GUID" is checked against the
        # contract, not asserted from memory.
        store = default_store()
        event_def = store.require(92)
        sink_def = store.require(688)
        entrant = event_def.port(DATA_OUTPUT, ENTRANT_DATA_OUT)
        guid = event_def.port(DATA_OUTPUT, ENTRANT_GUID_OUT)
        holder = sink_def.port(DATA_INPUT, HOLDER_DATA_IN)
        self.assertIsNotNone(entrant)
        self.assertIsNotNone(guid)
        self.assertIsNotNone(holder)
        # 4:0 and the holder input share the entity type; 4:1 does not.
        self.assertEqual(entrant.server_param_type, holder.server_param_type)
        self.assertNotEqual(guid.server_param_type, holder.server_param_type)


# ---------------------------------------------------------------------------
# Negative: 92 GUID output (4:1, type 2) must NOT feed an entity input (type 1)
# ---------------------------------------------------------------------------

class TestGuidIntoEntityRejected(unittest.TestCase):
    def test_guid_output_into_holder_is_a_type_mismatch(self):
        g = Graph("MW_API_test_flow_guid_neg")
        event, _give_item, give_currency = _fan_out(g, "enter")

        # Rewire 688.holder from the entrant GUID (4:1) instead of the entity.
        g.plan.wire(
            event.alias, DATA_OUTPUT, ENTRANT_GUID_OUT,   # 92 4:1, type 2
            give_currency.alias, DATA_INPUT, HOLDER_DATA_IN,  # 688 3:0, type 1
        )

        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems),
            f"expected a type mismatch, got {ctx.exception.problems}",
        )

    def test_the_mismatch_is_concrete_not_generic(self):
        # A generic end would be filled by the editor and would NOT be an error;
        # both pins here are concrete, which is what makes the wiring invalid.
        store = default_store()
        guid = store.require(92).port(DATA_OUTPUT, ENTRANT_GUID_OUT)
        holder = store.require(688).port(DATA_INPUT, HOLDER_DATA_IN)
        self.assertFalse(guid.is_generic)
        self.assertFalse(holder.is_generic)
        self.assertEqual(guid.server_param_type, 2)
        self.assertEqual(holder.server_param_type, 1)


# ---------------------------------------------------------------------------
# Variant: 316 (界面控件组触发时) as the source instead of 92
# ---------------------------------------------------------------------------

class TestUiControlFanOut(unittest.TestCase):
    def test_same_fan_out_from_ui_control_triggered(self):
        g = Graph("MW_API_test_flow_ui")
        event, give_item, give_currency = _fan_out(g, "ui")

        self.assertEqual(event.ntype.definition_id, 316)
        self.assertEqual(give_item.ntype.definition_id, 686)
        self.assertEqual(give_currency.ntype.definition_id, 688)
        g.validate()

        # 316 has the same shape: one exec output (kind 2, index 0) fanning to
        # two sinks, and its entity output is 4:0 (type 1).
        exec_edges = _edges_from(g.plan, event.alias, EXEC_OUTPUT)
        self.assertEqual(len(exec_edges), 2)
        self.assertEqual({e.src_index for e in exec_edges}, {THEN_EXEC_OUT})

        for sink in (give_item, give_currency):
            with self.subTest(sink=sink.alias):
                self.assertTrue(
                    _has_edge(
                        g.plan, event.alias, EXEC_OUTPUT, THEN_EXEC_OUT,
                        sink.alias, EXEC_INPUT, SINK_EXEC_IN,
                    )
                )
                self.assertTrue(
                    _has_edge(
                        g.plan, event.alias, DATA_OUTPUT, ENTRANT_DATA_OUT,
                        sink.alias, DATA_INPUT, HOLDER_DATA_IN,
                    )
                )

    def test_ui_entity_output_is_4_0(self):
        # 316's entity out sits at index 0 (same as 92's entrant), by contract.
        entity = default_store().require(316).port(DATA_OUTPUT, 0)
        self.assertIsNotNone(entity)
        self.assertEqual(entity.server_param_type, 1)


if __name__ == "__main__":
    unittest.main()
