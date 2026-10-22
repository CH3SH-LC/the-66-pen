"""Offline tests for M1's two finished entries — text bubble (679) and loot pickup.

Wave 29AU.  A census (`.runtime/scratch/INTERACTION-SERVER-HALF.md` §1) found the
interaction module has five official event entries; the first three (proximity /
UI control group / floating page) were already blocks, the last two were not.
These tests lock in the resolution, all of it derived from ``data/node-contracts``:

* **text bubble (``679 文本气泡完成时``)** — a real event (exec output, no exec
  input), so it IS a block entry; its action sibling ``631 切换生效的文本气泡``
  gives the entry the action half ``90`` gives the proximity entry;
* **loot pickup (掉落物拾取)** — a same-instrument census of the whole 500-def
  store finds **no** loot-pickup event, so there is no entry to build from and the
  block layer records a **named** impossibility
  (:class:`~tools.gameplan.blocks.LootPickupHasNoEventNode`), not a fabricated one.

No bridge, no game, no editor, no save — pure reads of the contract store and the
in-memory graph plan.

Run::

    python -B -m unittest tools.gameplan.tests.test_interaction_entries
"""

import unittest

from tools.gameplan import Graph
from tools.gameplan import blocks as B
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    default_store,
)
from tools.gameplan.modules import interaction
from tools.gameplan.paramtypes import CONFIG_ID, ENTITY, INT

#: ``(role, index, serverParamType)`` for the text-bubble event's data outputs.
TEXT_BUBBLE_OUTS = (
    ("owner", 0, ENTITY),
    ("character", 1, ENTITY),
    ("bubble_id", 2, CONFIG_ID),
    ("count", 3, INT),
)

#: ``(role, index, serverParamType)`` for the switch-bubble action's data inputs.
SWITCH_BUBBLE_INS = (
    ("target", 0, ENTITY),
    ("bubble_id", 1, CONFIG_ID),
)

#: The loot-pickup family: every 掉落/拾取/战利品 node the store carries for a
#: dropped-item entity (a same-instrument name scan, positive-controlled below).
LOOT_FAMILY = (687, 720, 724, 725, 726, 727, 728, 729, 730, 731, 732)


def _is_event(definition) -> bool:
    """An event: a contract with an execution output and no execution input."""
    return bool(definition.exec_outputs) and not definition.exec_inputs


class TestTextBubbleNodeRolesMatchTheContract(unittest.TestCase):
    """679 / 631's declared roles are re-derived, not trusted."""

    def test_both_nodes_exist_with_the_expected_names(self):
        store = default_store()
        self.assertEqual(store.require(679).name, "文本气泡完成时")
        self.assertEqual(store.require(631).name, "切换生效的文本气泡")

    def test_text_bubble_completed_is_an_event_with_the_declared_roles(self):
        store = default_store()
        definition = store.require(679)
        with self.subTest(node="679"):
            self.assertTrue(_is_event(definition), "679 must be an event")
            self.assertEqual(
                [p.index for p in definition.exec_outputs],
                sorted(interaction.TEXT_BUBBLE_COMPLETED.exec_outs.values()),
            )
            self.assertEqual(interaction.TEXT_BUBBLE_COMPLETED.exec_outs, {"then": 0})
            self.assertIsNone(interaction.TEXT_BUBBLE_COMPLETED.exec_in)
            self.assertEqual([p.index for p in definition.exec_inputs], [])

    def test_text_bubble_completed_output_roles_match_the_contract(self):
        store = default_store()
        definition = store.require(679)
        node_type = interaction.TEXT_BUBBLE_COMPLETED
        contract_indices = {
            p.index for p in definition.ports if p.kind == DATA_OUTPUT
        }
        self.assertEqual(contract_indices, {i for _, i, _ in TEXT_BUBBLE_OUTS})
        for role, index, param_type in TEXT_BUBBLE_OUTS:
            self.assertEqual(node_type.outs[role], index)
            port = definition.port(DATA_OUTPUT, index)
            self.assertIsNotNone(port, f"no data output {index} on 679")
            self.assertFalse(port.is_generic)
            self.assertEqual(port.server_param_type, param_type)

    def test_switch_bubble_is_an_action_with_the_declared_roles(self):
        store = default_store()
        definition = store.require(631)
        node_type = interaction.SWITCH_TEXT_BUBBLE
        with self.subTest(node="631"):
            self.assertFalse(_is_event(definition), "631 is an action, not an event")
            self.assertEqual(node_type.exec_in, 0)
            self.assertEqual(
                [p.index for p in definition.exec_inputs], [node_type.exec_in]
            )
            self.assertEqual(node_type.exec_outs, {"then": 0})
            contract_ins = {p.index for p in definition.ports if p.kind == DATA_INPUT}
            self.assertEqual(contract_ins, {i for _, i, _ in SWITCH_BUBBLE_INS})
            for role, index, param_type in SWITCH_BUBBLE_INS:
                self.assertEqual(node_type.ins[role], index)
                port = definition.port(DATA_INPUT, index)
                self.assertIsNotNone(port, f"no data input {index} on 631")
                self.assertEqual(port.server_param_type, param_type)


class TestTextBubbleEntryIsAKind(unittest.TestCase):
    """679 is registered as the fifth ``InteractionKind`` and is an entry."""

    def test_text_bubble_is_a_registered_kind(self):
        self.assertIn("text-bubble", interaction.KINDS)
        self.assertIs(interaction.KINDS["text-bubble"], interaction.TEXT_BUBBLE)
        self.assertEqual(interaction.TEXT_BUBBLE.event_definition_id, 679)
        self.assertTrue(interaction.TEXT_BUBBLE.scene_half.strip())

    def test_every_kind_event_is_an_event_in_the_store(self):
        store = default_store()
        for kind in interaction.KINDS.values():
            with self.subTest(kind=kind.key):
                self.assertTrue(
                    _is_event(store.require(kind.event_definition_id)),
                    f"{kind.key} ({kind.event_definition_id}) is not an event",
                )

    def test_event_dispatch_and_wrapper_place_679(self):
        g = Graph("MW_API_test_m1_bubble")
        via_kind = interaction.event(g, interaction.TEXT_BUBBLE, "k")
        wrapper = interaction.text_bubble_completed(g, "w")
        for node in (via_kind, wrapper):
            self.assertEqual(node.ntype.definition_id, 679)
        self.assertEqual(
            [n.definition_id for n in g.plan.nodes], [679, 679]
        )
        g.validate()

    def test_switch_text_bubble_places_631_and_validates(self):
        from tools.gameplan.nodes import ON_CREATE

        g = Graph("MW_API_test_m1_switch_bubble")
        create = g.place(ON_CREATE, "on_create")
        node = interaction.switch_text_bubble(
            g, create, target=(create, "entity"), bubble_id=3001,
            bubble_id_slot="int", alias="switch",
        )
        self.assertEqual(node.ntype.definition_id, 631)
        self.assertEqual(
            sorted(n.definition_id for n in g.plan.nodes), [71, 631]
        )
        g.validate()


class TestSwitchTextBubbleAction(unittest.TestCase):
    def test_switch_text_bubble_wires_target_and_bubble_id(self):
        from tools.gameplan.nodes import ON_CREATE

        g = Graph("MW_API_test_m1_switch")
        create = g.place(ON_CREATE, "on_create")
        node = interaction.switch_text_bubble(
            g, create, target=(create, "entity"), bubble_id=3001,
            bubble_id_slot="int", alias="switch",
        )
        self.assertEqual(node.ntype.definition_id, 631)
        g.validate()
        node_ids = {n.definition_id for n in g.plan.nodes}
        self.assertEqual(node_ids, {71, 631})


class TestTextBubbleBlocksBuild(unittest.TestCase):
    """The two new ModuleBlocks are well-formed entry→exit blocks."""

    def _block(self, function: str) -> B.ModuleBlock:
        for block in B.MODULE_BLOCKS:
            if block.function == function:
                return block
        self.fail(f"no ModuleBlock {function!r} in the registry")

    def test_text_bubble_event_block_is_complete(self):
        block = self._block("interaction.event[text-bubble]")
        graph = block.build()
        graph.validate()
        self.assertTrue(B.block_shape(graph.plan).well_formed)
        self.assertEqual(
            sorted(n.definition_id for n in graph.plan.nodes), [1, 679]
        )

    def test_switch_bubble_block_is_complete(self):
        block = self._block("interaction.switch_bubble_block")
        graph = block.build()
        graph.validate()
        self.assertTrue(B.block_shape(graph.plan).well_formed)
        self.assertEqual(
            sorted(n.definition_id for n in graph.plan.nodes), [1, 71, 631]
        )

    def test_every_new_block_defid_is_in_the_store(self):
        store = default_store()
        for function in ("interaction.event[text-bubble]",
                         "interaction.switch_bubble_block"):
            graph = self._block(function).build()
            for node in graph.plan.nodes:
                with self.subTest(block=function, defid=node.definition_id):
                    self.assertIsNotNone(store.get(node.definition_id))


class TestLootPickupHasNoEventNode(unittest.TestCase):
    """The loot-pickup entry cannot be a block: no event node exists for it."""

    def test_the_loot_family_nodes_all_resolve_in_the_store(self):
        store = default_store()
        self.assertTrue(LOOT_FAMILY, "the loot-family walk is empty")
        for definition_id in LOOT_FAMILY:
            with self.subTest(definition_id=definition_id):
                self.assertIsNotNone(
                    store.get(definition_id),
                    f"loot-family defId {definition_id} is not in the store",
                )
        self.assertEqual(set(B.LootPickupHasNoEventNode.nodes), set(LOOT_FAMILY))

    def test_no_loot_family_node_is_an_event_positive_controlled(self):
        """Same instrument, same run: the predicate DOES find an event (679)."""
        store = default_store()
        for definition_id in LOOT_FAMILY:
            with self.subTest(definition_id=definition_id):
                self.assertFalse(
                    _is_event(store.require(definition_id)),
                    f"{definition_id} is an event — a block could be built",
                )
        # Positive control: the very same predicate reports 679 IS an event, so
        # the walk above is not vacuously all-False.
        self.assertTrue(_is_event(store.require(679)))

    def test_loot_pickup_block_refuses_with_the_named_error(self):
        with self.assertRaises(B.LootPickupHasNoEventNode) as ctx:
            B.loot_pickup_block()
        self.assertEqual(ctx.exception.code, "LOOT_PICKUP_HAS_NO_EVENT_NODE")

    def test_the_refusal_names_the_missing_thing(self):
        with self.assertRaises(B.LootPickupHasNoEventNode) as ctx:
            B.loot_pickup_block()
        message = str(ctx.exception)
        self.assertIn("681", message)  # the generic event that observes it
        self.assertIn("event node", message)

    def test_the_refusal_class_has_a_source_location(self):
        self.assertRegex(
            B.refusal_location(B.LootPickupHasNoEventNode), r".+\.py:\d+$"
        )

    def test_loot_pickup_is_not_a_kind(self):
        # A kind requires an event_definition_id; loot has no event to point at.
        for kind in interaction.KINDS.values():
            self.assertNotIn(kind.label, "掉落物拾取")


if __name__ == "__main__":
    unittest.main()
