"""Offline tests for the fewest-manual-step **self-arming** farming loop (#4).

No bridge, no game, no editor, no native request.  What is proven here:

1. the graph **validates** against ``data/node-contracts`` and its node list is exactly
   the 18 nodes declared (``GraphPlan.validate`` — offline, not a run);
2. every node's ``definitionId`` is a real server (kind 20000) contract node;
3. **no event in the graph requires an editor-authored component or asset** — every
   event node's id is a member of the encoded allowed set :data:`ALLOWED_EVENT_IDS`
   (``{71, 83, 386}``), and the interaction/shop/item events that *do* need a hand-built
   scene half (``92``/``733``/``701``/``316``/``826`` …) are absent;
4. the chosen clock is self-armed: the arm ``71`` drives ``79 启动定时器`` off its own
   execution output, and no execution edge points *into* an event (events have no
   execution input — ``data/node-contracts``);
5. the one unwritable constant is not fabricated: ``79`` is placed but its
   ``定时器序列`` pin (``3:3``, contract type 10 = float list) is left unwritten, and no
   constant in the plan targets any list-typed pin;
6. the manual-step count is a **number**: the chosen events cost 0, the graph's residual
   asset cost is 3, the clock's period (the unwritable ``定时器序列``) is 1 more — the total
   is 4 — strictly fewer than ``farming_full``'s 7;
7. the steps this design **removes** are named, not implied (``AVOIDED_MANUAL_STEPS``:
   the 商店 template, the two ``碰撞触发器`` components, the 商店 component), and they
   reconcile exactly with ``farming_full`` (3 kept + 4 removed = 7);
8. the clock's period is a **real** manual step, not a cosmetic caveat: the official node
   reference says an illegal sequence means 定时器不会运行, so the loop stays inert until a
   human (or a future list slot) supplies it — cited and asserted.

Negative controls prove the assertions discriminate: the allowed-membership predicate
rejects ``92`` (a real event needing a component), an unknown event key raises rather
than defaulting to zero, and a container-armoured plan that *added* a forbidden event
would fail the membership check.
"""

import unittest

from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    default_store,
)
from tools.gameplan.demo.farming_autoloop import (
    ALLOWED_EVENT_IDS,
    AVOIDED_MANUAL_STEPS,
    CLOCK_SEQUENCE_REQUIREMENT_CITATION,
    CLOCK_SEQUENCE_STEPS,
    CRAFT_SHORT_TEXT,
    DEFAULT_NAME,
    EVENT_SOURCES,
    FARMING_FULL_MANUAL_STEP_COUNT,
    FEEDBACK_TEXT,
    RESIDUAL_TEMPLATE_STEPS,
    SELL_EMPTY_TEXT,
    SELL_OK_TEXT,
    UNWRITABLE_TIMER_SEQUENCE_PIN,
    AutoLoopConfig,
    CHOSEN_EVENT_KEYS,
    COST_TIE_SOURCES,
    avoided_step_count,
    clock_sequence_step_count,
    event_source,
    event_step_count,
    fewer_than_farming_full,
    is_allowed_event,
    manual_step_count,
    manual_steps,
    plan_of,
    residual_step_count,
    total_manual_step_count,
)
from tools.gameplan.plan import GraphPlan, PlanError

CONFIG = AutoLoopConfig(
    currency_id=1115684864,
    crop_id=1120000001,
    food_id=1120000002,
    item_slot="int",
    currency_slot="int",
)

#: The graph in build order: (alias, definitionId).  Frozen so any shape drift is caught.
EXPECTED_NODES = (
    ("arm", 71),
    ("start_clock", 79),
    ("tick", 83),
    ("harvest", 686),
    ("craft_enough_read", 690),
    ("craft_enough", 233),
    ("craft_gate", 2),
    ("craft_take", 686),
    ("craft_bake", 686),
    ("craft_short", 1),
    ("sell_enough_read", 690),
    ("sell_enough", 233),
    ("sell_gate", 2),
    ("sell_take", 686),
    ("sell_pay", 688),
    ("sell_ok", 1),
    ("sell_empty", 1),
    ("feedback", 1),
)

EXPECTED_NODE_COUNT = len(EXPECTED_NODES)
EXPECTED_EDGE_COUNT = 24  # 12 execution + 12 data (holder source included per grant)
EXPECTED_CONST_COUNT = 20

#: The two event sources the loop is built from, and the id each must place.
CHOSEN_EVENT_IDS = frozenset(
    event_source(key).definition_id for key in CHOSEN_EVENT_KEYS
)

#: Event ids that require an editor-authored component/asset to fire — the exact ids a
#: regression would reach for.  None may appear in the graph.
FORBIDDEN_EVENT_IDS = frozenset({92, 91, 733, 701, 705, 316, 826})


def _plan() -> GraphPlan:
    return plan_of(CONFIG)


def _event_nodes(plan: GraphPlan) -> tuple[int, ...]:
    """definitionIds of the plan's nodes that are event nodes per the contract.

    An event node is a contract record with an execution output and **no** execution
    input — the same predicate ``data/node-contracts`` encodes, re-derived here so the
    test does not trust a hand-typed list.
    """
    store = default_store()
    found = []
    for node in plan.nodes:
        definition = store.require(node.definition_id)
        if definition.exec_outputs and not definition.exec_inputs:
            found.append(node.definition_id)
    return tuple(sorted(set(found)))


class TestGraphValidates(unittest.TestCase):
    """The plan is internally consistent against the port contracts."""

    def test_plan_of_returns_a_validated_plan(self):
        plan = _plan()  # raises PlanError if inconsistent
        self.assertEqual(plan.name, DEFAULT_NAME)
        self.assertEqual(plan.graph_kind, 20000)

    def test_node_list_is_exactly_the_declared_nodes(self):
        plan = _plan()
        self.assertEqual(
            tuple((n.alias, n.definition_id) for n in plan.nodes), EXPECTED_NODES
        )

    def test_counts(self):
        plan = _plan()
        self.assertEqual(len(plan.nodes), EXPECTED_NODE_COUNT)
        self.assertEqual(len(plan.edges), EXPECTED_EDGE_COUNT)
        self.assertEqual(len(plan.consts), EXPECTED_CONST_COUNT)

    def test_every_node_is_a_real_server_contract_node(self):
        store = default_store()
        for node in _plan().nodes:
            definition = store.require(node.definition_id)
            self.assertEqual(
                definition.graph_kind, 20000,
                f"{node.alias} ({node.definition_id}) is not a server node",
            )


class TestEventsAreSelfArming(unittest.TestCase):
    """No event in the graph requires an editor-authored component or asset."""

    def test_every_event_node_is_in_the_allowed_set(self):
        for definition_id in _event_nodes(_plan()):
            self.assertIn(
                definition_id, ALLOWED_EVENT_IDS,
                f"event {definition_id} is not a self-arming, asset-free event",
            )

    def test_the_allowed_set_is_exactly_the_self_arming_asset_free_sources(self):
        expected = frozenset(
            source.definition_id
            for source in EVENT_SOURCES.values()
            if source.graph_self_arms and not source.manual_steps
        )
        self.assertEqual(ALLOWED_EVENT_IDS, expected)

    def test_the_graph_uses_exactly_the_two_chosen_events(self):
        self.assertEqual(set(_event_nodes(_plan())), set(CHOSEN_EVENT_IDS))
        self.assertEqual(set(CHOSEN_EVENT_IDS), {71, 83})

    def test_no_forbidden_event_appears(self):
        present = set(_event_nodes(_plan()))
        self.assertEqual(present & FORBIDDEN_EVENT_IDS, set())

    def test_no_execution_edge_points_into_an_event(self):
        """An event has no execution input, so nothing may target one."""
        store = default_store()
        by_alias = {n.alias: n for n in _plan().nodes}
        for edge in _plan().edges:
            if (edge.src_kind, edge.dst_kind) != (EXEC_OUTPUT, EXEC_INPUT):
                continue
            dst = by_alias[edge.dst]
            dst_def = store.require(dst.definition_id)
            self.assertTrue(
                dst_def.exec_inputs,
                f"execution edge {edge.src}->{edge.dst} targets an event (no exec input)",
            )

    def test_arm_starts_the_clock_from_its_own_exec_output(self):
        plan = _plan()
        by_alias = {n.alias: n for n in plan.nodes}
        self.assertEqual(by_alias["arm"].definition_id, 71)
        self.assertEqual(by_alias["start_clock"].definition_id, 79)
        self.assertEqual(by_alias["tick"].definition_id, 83)
        edges = {(e.src, e.dst) for e in plan.edges}
        self.assertIn(("arm", "start_clock"), edges)
        # The arm's entity feeds the timer's target — a data edge, not a constant.
        data_edges = {(e.src, e.dst) for e in plan.edges if e.dst_kind == DATA_INPUT}
        self.assertIn(("arm", "start_clock"), data_edges)


class TestNoFabricatedTimerSequence(unittest.TestCase):
    """``79`` is placed, but its unwritable float-list input is never faked."""

    def test_pin_is_the_known_unwritable_one(self):
        self.assertEqual(UNWRITABLE_TIMER_SEQUENCE_PIN, 3)

    def test_the_contract_types_that_pin_as_a_list(self):
        definition = default_store().require(79)
        port = definition.port(DATA_INPUT, UNWRITABLE_TIMER_SEQUENCE_PIN)
        self.assertIsNotNone(port)
        self.assertEqual(port.name, "定时器序列")
        self.assertEqual(port.server_param_type, 10)  # the list code

    def test_no_constant_targets_the_timer_sequence_pin(self):
        for const in _plan().consts:
            self.assertFalse(
                const.alias == "start_clock"
                and const.port_index == UNWRITABLE_TIMER_SEQUENCE_PIN,
                "the timer sequence pin must not be fabricated",
            )

    def test_no_constant_targets_any_list_typed_pin(self):
        """A general guard: no constant is written onto a pin whose type is a list."""
        plan = _plan()
        store = default_store()
        by_alias = {n.alias: n for n in plan.nodes}
        for const in plan.consts:
            definition = store.require(by_alias[const.alias].definition_id)
            port = definition.port(DATA_INPUT, const.port_index)
            self.assertIsNotNone(port)
            self.assertNotEqual(
                port.server_param_type, 10,
                f"constant on {const.alias} pin 3:{const.port_index} is a list; "
                f"no slot can express a list today",
            )

    def test_the_other_timer_inputs_are_written(self):
        """Only the sequence is left out; name and loop *are* written."""
        written = {
            (c.alias, c.port_index) for c in _plan().consts if c.alias == "start_clock"
        }
        self.assertIn(("start_clock", 1), written)  # 定时器名称
        self.assertIn(("start_clock", 2), written)  # 是否循环
        self.assertNotIn(("start_clock", 3), written)  # 定时器序列 — deliberate


class TestManualStepAccounting(unittest.TestCase):
    """The design goal, as a number: fewer manual steps than ``farming_full``."""

    def test_chosen_events_cost_zero_editor_steps(self):
        self.assertEqual(event_step_count(), 0)
        for key in CHOSEN_EVENT_KEYS:
            self.assertEqual(manual_step_count(key), 0)
            self.assertTrue(event_source(key).graph_self_arms)

    def test_residual_is_the_three_templates(self):
        self.assertEqual(residual_step_count(), 3)
        self.assertEqual(len(RESIDUAL_TEMPLATE_STEPS), 3)

    def test_total_is_four_and_strictly_under_farming_full(self):
        # 0 event steps + 3 templates + 1 timer sequence = 4 (the sequence is a real
        # manual step until a list-slot exists — see CLOCK_SEQUENCE_REQUIREMENT_CITATION).
        self.assertEqual(total_manual_step_count(), 4)
        self.assertEqual(event_step_count(), 0)
        self.assertEqual(residual_step_count() + clock_sequence_step_count(), 4)
        self.assertEqual(FARMING_FULL_MANUAL_STEP_COUNT, 7)
        self.assertLess(total_manual_step_count(), FARMING_FULL_MANUAL_STEP_COUNT)
        self.assertTrue(fewer_than_farming_full())

    def test_no_rejected_source_is_cheaper_than_the_chosen(self):
        """Every source outside the chosen set is costlier, unbuildable, or a named tie."""
        for key in EVENT_SOURCES:
            if key in CHOSEN_EVENT_KEYS or key in COST_TIE_SOURCES:
                continue
            source = event_source(key)
            self.assertTrue(
                len(source.manual_steps) > 0 or not source.buildable,
                f"{key} is cheaper than the chosen pair and not a named tie",
            )

    def test_the_named_cost_ties_are_the_other_asset_free_self_arming_sources(self):
        """The only sources that tie the chosen pair are the self-arming, asset-free ones."""
        tied = frozenset(
            key
            for key, source in EVENT_SOURCES.items()
            if source.graph_self_arms and not source.manual_steps
        ) - set(CHOSEN_EVENT_KEYS)
        self.assertEqual(tied, COST_TIE_SOURCES)
        self.assertEqual(tied, {"class-level"})


class TestEventSourceModel(unittest.TestCase):
    """The candidate table is complete and its per-key counts are the cited ones."""

    def test_expected_keys_are_present(self):
        self.assertEqual(
            set(EVENT_SOURCES),
            {
                "on-create", "timer", "global-timer", "class-level", "item-used",
                "proximity", "shop-sold", "ui-button", "floating-page",
            },
        )

    def test_global_timer_costs_one_step(self):
        self.assertEqual(manual_step_count("global-timer"), 1)
        self.assertNotIn(315, ALLOWED_EVENT_IDS)

    def test_proximity_costs_two_steps_and_is_forbidden(self):
        self.assertEqual(manual_step_count("proximity"), 2)
        self.assertNotIn(92, ALLOWED_EVENT_IDS)
        self.assertFalse(event_source("proximity").graph_self_arms)

    def test_item_used_costs_one_step(self):
        self.assertEqual(manual_step_count("item-used"), 1)

    def test_citations_are_non_empty_for_every_step(self):
        for source in EVENT_SOURCES.values():
            for step in source.manual_steps:
                self.assertTrue(step.action)
                self.assertTrue(step.citation)

    def test_unknown_event_key_is_refused(self):
        with self.assertRaises(KeyError):
            event_source("does-not-exist")
        with self.assertRaises(KeyError):
            manual_steps("does-not-exist")

    def test_is_allowed_event_discriminates(self):
        self.assertTrue(is_allowed_event(71))
        self.assertTrue(is_allowed_event(83))
        self.assertFalse(is_allowed_event(92))
        self.assertFalse(is_allowed_event(733))


class TestFeedbackLines(unittest.TestCase):
    """The observable strings are the ones the graph writes."""

    def test_printed_texts_are_written_as_strings(self):
        texts = {c.value for c in _plan().consts if c.slot == "string"}
        self.assertIn(CRAFT_SHORT_TEXT, texts)
        self.assertIn(SELL_OK_TEXT, texts)
        self.assertIn(SELL_EMPTY_TEXT, texts)
        self.assertIn(FEEDBACK_TEXT, texts)
        self.assertIn(CONFIG.timer_name, texts)


class TestAvoidedManualSteps(unittest.TestCase):
    """Requirement #3: name the editor steps this design does NOT need (farming_full's)."""

    def test_the_four_avoided_steps_are_named(self):
        self.assertEqual(avoided_step_count(), 4)
        self.assertEqual(len(AVOIDED_MANUAL_STEPS), 4)

    def test_every_avoided_step_is_cited(self):
        for step in AVOIDED_MANUAL_STEPS:
            self.assertTrue(step.action)
            self.assertTrue(step.citation)

    def test_avoided_steps_name_the_shop_and_both_components(self):
        blob = " ".join(s.action for s in AVOIDED_MANUAL_STEPS)
        self.assertIn("商店模板", blob)                    # the shop template
        self.assertEqual(blob.count("碰撞触发器"), 2)      # plot trigger + stall trigger
        self.assertIn("商店组件", blob)                    # the stall's shop component

    def test_kept_plus_avoided_reconcile_with_farming_full(self):
        # farming_full's 7 = this demo's 3 kept templates + the 4 removed steps.
        self.assertEqual(
            residual_step_count() + avoided_step_count(),
            FARMING_FULL_MANUAL_STEP_COUNT,
        )

    def test_the_removed_trigger_is_the_manual_half_farming_full_keeps(self):
        # The trigger is *not* among the kept steps: the event source itself costs 0.
        self.assertEqual(event_step_count(), 0)
        self.assertEqual(manual_step_count("proximity"), 2)  # the component trigger
        self.assertNotIn(92, ALLOWED_EVENT_IDS)


class TestClockSequenceBlocksRunUntilWritten(unittest.TestCase):
    """The unwritten ``定时器序列`` is fatal to running — and is counted, not hidden."""

    def test_the_citation_states_the_timer_will_not_run(self):
        self.assertIn("mhw66orrrfkm", CLOCK_SEQUENCE_REQUIREMENT_CITATION)
        self.assertIn("定时器不会运行", CLOCK_SEQUENCE_REQUIREMENT_CITATION)

    def test_the_sequence_is_a_real_named_manual_step(self):
        self.assertEqual(clock_sequence_step_count(), 1)
        step = CLOCK_SEQUENCE_STEPS[0]
        self.assertIn("定时器序列", step.action)
        self.assertTrue(step.citation)

    def test_the_plan_leaves_the_sequence_absent(self):
        # Restates the fabricate-guard as the *consequence*: an absent sequence means an
        # inert clock, so it can never be silently assumed present.
        written = {
            (c.alias, c.port_index) for c in _plan().consts if c.alias == "start_clock"
        }
        self.assertNotIn(("start_clock", UNWRITABLE_TIMER_SEQUENCE_PIN), written)


class TestNegativeControls(unittest.TestCase):
    """The guards fail when they should — a green run is not a tautology."""

    def test_a_plan_that_adds_a_forbidden_event_fails_the_membership_rule(self):
        plan = _plan()
        plan.add("sneaky", 92)  # 进入碰撞触发器时 — needs a component
        # The same predicate the allowed-membership test uses now fails.
        event_ids = _event_nodes(plan)
        self.assertIn(92, event_ids)
        self.assertNotIn(92, ALLOWED_EVENT_IDS)

    def test_validate_rejects_an_unknown_definition(self):
        plan = _plan()
        plan.add("bogus", 999999999)
        with self.assertRaises(PlanError):
            plan.validate()


if __name__ == "__main__":
    unittest.main()
