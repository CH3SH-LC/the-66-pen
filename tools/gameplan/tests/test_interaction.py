"""Offline tests for the M1 interaction module.  No bridge, no game, no editor.

``tools/gameplan/modules/interaction.py`` is the *event entry* every other module
hangs off, so it is small but load-bearing: five official event entries, each a
``definitionId`` plus a block of data-output roles, plus a ``scene_half`` string
that records the manual editor step this project cannot perform (there is no
component / UI / floating-page / text-bubble writer in the bridge).

Everything asserted here is re-derived from ``data/node-contracts`` so a drifted
role index or a wrong ``event_definition_id`` fails the test instead of silently
producing a graph that only the editor would reject.

Run::

    python -B -m unittest tools.gameplan.tests.test_interaction
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import nodes as N
from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, default_store
from tools.gameplan.modules import interaction
from tools.gameplan.paramtypes import CONFIG_ID, ENTITY, GUID, INT
from tools.gameplan.plan import PlanError

# ``serverParamType`` code 8 is observed on 826's list pins but has no confident
# name in ``paramtypes.NAMES`` ("unknown-8"), so the role table below carries the
# raw contract type for those two rows and a named constant where one exists.
UNKNOWN_8 = 8

#: The documented data-output roles per kind: ``(role, index, serverParamType)``.
#: Checked both ways against the contract store (see
#: :meth:`TestInteractionDataOutputs.test_role_indices_match_the_contract`).
EXPECTED_DATA_OUTS = {
    "proximity": (
        ("entrant", 0, ENTITY),
        ("entrant_guid", 1, GUID),
        ("trigger", 2, ENTITY),
        ("trigger_guid", 3, GUID),
        ("trigger_index", 4, INT),
    ),
    "proximity-exit": (
        ("leaver", 0, ENTITY),
        ("leaver_guid", 1, GUID),
        ("trigger", 2, ENTITY),
        ("trigger_guid", 3, GUID),
        ("trigger_index", 4, INT),
    ),
    "ui-button": (
        ("entity", 0, ENTITY),
        ("guid", 1, GUID),
        ("group_combo_index", 2, INT),
        ("group_index", 3, INT),
    ),
    "floating-page": (
        ("player", 0, ENTITY),
        ("player_guid", 1, GUID),
        ("page_index", 2, INT),
        ("item_index", 3, INT),
        ("list_index", 4, UNKNOWN_8),
        ("list_selected", 5, UNKNOWN_8),
    ),
    "text-bubble": (
        ("owner", 0, ENTITY),
        ("character", 1, ENTITY),
        ("bubble_id", 2, CONFIG_ID),
        ("count", 3, INT),
    ),
}


def _nodes_with_id(plan, definition_id):
    return [n for n in plan.nodes if n.definition_id == definition_id]


def _data_out_indices(definition):
    return {
        p.index for p in definition.ports if p.kind == DATA_OUTPUT
    }


class TestInteractionKinds(unittest.TestCase):
    """The KINDS registry and the documented definitionId per family."""

    def test_kinds_keys_are_the_five_documented_entries(self):
        # Five official event entries (census, INTERACTION-SERVER-HALF.md §1).
        # Kept in step with EXPECTED_DATA_OUTS below so the two tables cannot drift.
        self.assertEqual(
            set(interaction.KINDS),
            {"proximity", "proximity-exit", "ui-button", "floating-page",
             "text-bubble"},
        )
        self.assertEqual(set(interaction.KINDS), set(EXPECTED_DATA_OUTS))

    def test_kinds_keys_match_each_kinds_own_key_field(self):
        for key, kind in interaction.KINDS.items():
            with self.subTest(key=key):
                self.assertEqual(kind.key, key)
                self.assertIsInstance(kind, interaction.InteractionKind)
                self.assertIsInstance(kind.label, str)
                self.assertTrue(kind.label)

    def test_event_definition_ids_are_the_documented_ones(self):
        self.assertEqual(interaction.KINDS["proximity"].event_definition_id, 92)
        self.assertEqual(interaction.KINDS["proximity-exit"].event_definition_id, 91)
        self.assertEqual(interaction.KINDS["ui-button"].event_definition_id, 316)
        self.assertEqual(interaction.KINDS["floating-page"].event_definition_id, 826)
        self.assertEqual(interaction.KINDS["text-bubble"].event_definition_id, 679)
        # The named singletons are the same objects the registry hands out.
        self.assertIs(interaction.KINDS["proximity"], interaction.PROXIMITY)
        self.assertIs(interaction.KINDS["proximity-exit"], interaction.PROXIMITY_EXIT)
        self.assertIs(interaction.KINDS["ui-button"], interaction.UI_BUTTON)
        self.assertIs(interaction.KINDS["floating-page"], interaction.FLOATING_PAGE)
        self.assertIs(interaction.KINDS["text-bubble"], interaction.TEXT_BUBBLE)

    def test_scene_half_is_a_non_empty_string_for_every_kind(self):
        # The whole honest-limit point of the module: every kind carries the
        # manual editor step it needs, so no caller mistakes "the node exists"
        # for "the interaction works".
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                self.assertIsInstance(kind.scene_half, str)
                self.assertGreater(len(kind.scene_half), 0)
                self.assertTrue(kind.scene_half.strip())


class TestInteractionEventPlacement(unittest.TestCase):
    """``event`` and the four convenience wrappers place the right node."""

    def test_event_places_the_kind_definition_under_the_alias(self):
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                g = Graph("MW_API_test_interaction_event")
                node = interaction.event(g, kind, "evt")
                self.assertEqual(node.ntype.definition_id, kind.event_definition_id)
                self.assertEqual(node.alias, "evt")
                placed = _nodes_with_id(g.plan, kind.event_definition_id)
                self.assertEqual(len(placed), 1)
                self.assertEqual(placed[0].alias, "evt")
                g.validate()

    def test_event_places_exactly_one_node(self):
        g = Graph("MW_API_test_interaction_one")
        interaction.event(g, interaction.UI_BUTTON, "only")
        self.assertEqual(len(g.plan.nodes), 1)
        self.assertEqual(len(g.plan.edges), 0)

    def test_wrappers_place_their_nodes_with_default_aliases(self):
        cases = (
            (interaction.proximity_enter, 92, "m1_enter"),
            (interaction.proximity_leave, 91, "m1_leave"),
            (interaction.ui_control_triggered, 316, "m1_ui"),
            (interaction.floating_page_triggered, 826, "m1_page"),
            (interaction.text_bubble_completed, 679, "m1_bubble"),
        )
        for func, expected, default_alias in cases:
            with self.subTest(wrapper=func.__name__):
                g = Graph("MW_API_test_interaction_wrap")
                node = func(g)
                self.assertEqual(node.ntype.definition_id, expected)
                self.assertEqual(node.alias, default_alias)
                self.assertEqual(len(_nodes_with_id(g.plan, expected)), 1)
                g.validate()

    def test_wrappers_accept_an_explicit_alias(self):
        cases = (
            (interaction.proximity_enter, 92),
            (interaction.proximity_leave, 91),
            (interaction.ui_control_triggered, 316),
            (interaction.floating_page_triggered, 826),
            (interaction.text_bubble_completed, 679),
        )
        for func, expected in cases:
            with self.subTest(wrapper=func.__name__):
                g = Graph("MW_API_test_interaction_alias")
                node = func(g, "custom")
                self.assertEqual(node.alias, "custom")
                self.assertEqual(node.ntype.definition_id, expected)
                g.validate()

    def test_every_kind_node_exposes_a_single_execution_source(self):
        # M1 is the shared trigger source: exactly one "then" exec output and no
        # execution input (an event cannot be driven by another event).
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                g = Graph("MW_API_test_interaction_exec")
                node = interaction.event(g, kind, "evt")
                self.assertEqual(node.ntype.exec_outs, {"then": 0})
                self.assertIsNone(node.ntype.exec_in)

    def test_event_node_can_drive_a_downstream_module(self):
        # The event's "then" output is a real execution source (2->1) and its
        # entrant output is a real entity source for a module data input.
        g = Graph("MW_API_test_interaction_flow")
        enter = interaction.proximity_enter(g)
        sink = g.place(N.ADD_BAG_CURRENCY, "sink")
        enter.flow_to(sink)
        sink.data_from(enter, "entrant", "holder")
        g.validate()


class TestInteractionDataOutputs(unittest.TestCase):
    """Every kind's declared output roles agree with the contract store."""

    def test_role_indices_match_the_contract(self):
        store = default_store()
        for kind in interaction.KINDS.values():
            expected = EXPECTED_DATA_OUTS[kind.key]
            definition = store.require(kind.event_definition_id)
            with self.subTest(kind=kind.key):
                # 1. The role table declares exactly the contract's data outputs:
                #    no missing pin and no invented one.
                self.assertEqual(
                    _data_out_indices(definition),
                    {index for _, index, _ in expected},
                )
                # 2. Each named role resolves to the documented pin ...
                node_type = _node_type_for(kind)
                for role, index, param_type in expected:
                    self.assertEqual(node_type.outs[role], index)
                    port = definition.port(DATA_OUTPUT, index)
                    self.assertIsNotNone(port, f"{kind.key}: no data out {index}")
                    # ... and that pin's concrete type is what we recorded.
                    self.assertFalse(port.is_generic)
                    self.assertEqual(port.server_param_type, param_type)

    def test_proximity_enter_outs_roles(self):
        self.assertEqual(
            N.PROXIMITY_ENTER.outs,
            {
                "entrant": 0,
                "entrant_guid": 1,
                "trigger": 2,
                "trigger_guid": 3,
                "trigger_index": 4,
            },
        )

    def test_proximity_leave_outs_roles(self):
        self.assertEqual(
            N.PROXIMITY_LEAVE.outs,
            {
                "leaver": 0,
                "leaver_guid": 1,
                "trigger": 2,
                "trigger_guid": 3,
                "trigger_index": 4,
            },
        )

    def test_ui_button_outs_roles(self):
        self.assertEqual(
            N.UI_CONTROL_TRIGGERED.outs,
            {
                "entity": 0,
                "guid": 1,
                "group_combo_index": 2,
                "group_index": 3,
            },
        )

    def test_floating_page_outs_roles(self):
        self.assertEqual(
            N.FLOATING_PAGE_TRIGGERED.outs,
            {
                "player": 0,
                "player_guid": 1,
                "page_index": 2,
                "item_index": 3,
                "list_index": 4,
                "list_selected": 5,
            },
        )


def _node_type_for(kind):
    """The :class:`~tools.gameplan.nodes.NodeType` a kind places."""
    return {
        "proximity": N.PROXIMITY_ENTER,
        "proximity-exit": N.PROXIMITY_LEAVE,
        "ui-button": N.UI_CONTROL_TRIGGERED,
        "floating-page": N.FLOATING_PAGE_TRIGGERED,
        "text-bubble": interaction.TEXT_BUBBLE_COMPLETED,
    }[kind.key]


class TestInteractionNegativeControls(unittest.TestCase):
    """Ways the module must refuse to build a bad graph."""

    def test_unknown_kind_raises_keyerror(self):
        g = Graph("MW_API_test_interaction_bad_kind")
        bogus = interaction.InteractionKind("bogus", "?", 999999, "x")
        with self.assertRaises(KeyError):
            interaction.event(g, bogus, "evt")
        # Nothing was placed before the dispatch failed.
        self.assertEqual(len(g.plan.nodes), 0)

    def test_negative_92_entity_output_into_bool_input_rejected(self):
        # 92.entrant is a concrete entity (serverParamType 1); 双分支的条件 is a
        # concrete bool (serverParamType 4).  validate() must reject the edge.
        g = Graph("MW_API_test_interaction_neg_bool")
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

    def test_negative_316_int_output_into_entity_input_rejected(self):
        # 316.group_combo_index is a concrete int (serverParamType 3); a node
        # whose data input is a concrete entity (serverParamType 1) must not
        # accept it.  688's holder pin (3:0) is exactly such a concrete entity.
        g = Graph("MW_API_test_interaction_neg_mismatch")
        ui = interaction.ui_control_triggered(g)
        bag = g.place(N.ADD_BAG_CURRENCY, "bag")
        g.plan.wire(
            ui.alias, DATA_OUTPUT, ui.ntype.outs["group_combo_index"],
            bag.alias, DATA_INPUT, bag.ntype.ins["holder"],
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems)
        )

    def test_negative_edge_into_92_is_rejected_it_has_no_data_inputs(self):
        # Documented caveat: definition 92 (an event node) declares ZERO data
        # inputs, so an edge "into 92" can never be a type mismatch -- it is
        # rejected earlier, as a non-existent pin.  This pins that behaviour so
        # the distinction is not lost.
        store = default_store()
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                definition = store.require(kind.event_definition_id)
                self.assertEqual(
                    [p for p in definition.ports if p.kind == 3], []
                )
        g = Graph("MW_API_test_interaction_neg_noinput")
        ui = interaction.ui_control_triggered(g)
        enter = interaction.proximity_enter(g)
        g.plan.wire(
            ui.alias, DATA_OUTPUT, ui.ntype.outs["group_combo_index"],
            enter.alias, DATA_INPUT, 0,
        )
        with self.assertRaises(PlanError) as ctx:
            g.validate()
        self.assertTrue(
            any("no data input index" in p for p in ctx.exception.problems)
        )


class TestInteractionSmoke(unittest.TestCase):
    """One graph holding all five event entry points validates clean."""

    def test_all_five_events_in_one_graph_validate(self):
        g = Graph("MW_API_test_interaction_smoke")
        enter = interaction.proximity_enter(g)
        leave = interaction.proximity_leave(g)
        ui = interaction.ui_control_triggered(g)
        page = interaction.floating_page_triggered(g)
        bubble = interaction.text_bubble_completed(g)

        for node, definition_id in (
            (enter, 92),
            (leave, 91),
            (ui, 316),
            (page, 826),
            (bubble, 679),
        ):
            with self.subTest(definition_id=definition_id):
                self.assertEqual(node.ntype.definition_id, definition_id)

        self.assertEqual(
            sorted(n.definition_id for n in g.plan.nodes),
            [91, 92, 316, 679, 826],
        )
        g.validate()  # must not raise

    def test_event_dispatch_matches_wrappers(self):
        # event(g, kind, alias) must place the same definitionId as the wrapper.
        g = Graph("MW_API_test_interaction_dispatch")
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                via_event = interaction.event(g, kind, f"e_{kind.key}")
                self.assertEqual(
                    via_event.ntype.definition_id, kind.event_definition_id
                )
        g.validate()


if __name__ == "__main__":
    unittest.main()
