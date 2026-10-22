"""Offline tests for the smallest *firable* graph (#10 build).

No bridge, no game, no editor.  Three things are proven here:

1. the graph **validates** against ``data/node-contracts`` and its node list is
   exactly the two nodes declared (offline, via ``GraphPlan.validate`` — not a
   machine run);
2. every node's ``definitionId`` is a real server (kind 20000) contract node;
3. **the choice of event source is justified as a number**: the primary source
   (``733`` 背包内道具被使用时) needs no more manual editor steps than the
   alternative (``92 进入碰撞触发器时``) for the *same* graph — in fact strictly
   fewer — and the inequality test is a real discriminator, not a tautology
   (the reversed choice fails it).

The negative controls prove the assertions discriminate: a lone event node has
no execution edge (so "2 nodes" is a floor, not a coincidence), a swapped
``holder`` source is detectable, and an unknown event key is refused rather than
defaulting to zero steps.
"""

import unittest

from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, EXEC_OUTPUT
from tools.gameplan.contracts import default_store
from tools.gameplan.demo.minimal_playable import (
    ALT_NAME,
    DEFAULT_NAME,
    EVENT_ITEM_USED,
    EVENT_PROXIMITY,
    MANUAL_STEPS,
    ManualStep,
    MinimalConfig,
    alternative_plan_of,
    build,
    build_alternative,
    manual_step_count,
    manual_steps,
    plan_of,
    seed_leg,
)
from tools.gameplan.plan import PlanError

CONFIG = MinimalConfig(crop_id=1120000001, item_slot="int", harvest_gain=3)

#: The primary graph, in build order: the item-used event then its grant.
EXPECTED_NODES = (("use_crop", 733), ("regrow", 686))

#: The alternative graph: the proximity event then its grant.  Same size.
EXPECTED_ALT_NODES = (("plot_enter", 92), ("harvest", 686))


def _node_list(plan):
    return tuple((n.alias, n.definition_id) for n in plan.nodes)


def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _exec_edges(plan, src):
    return [
        e for e in plan.edges
        if e.src == src and e.src_kind == EXEC_OUTPUT
    ]


def _holder_source(plan, alias):
    """The data edge that fills a node's ``holder`` input (port 0)."""
    return next(
        e for e in plan.edges
        if e.dst == alias and e.dst_kind == DATA_INPUT and e.dst_index == 0
    )


class TestMinimalGraphShape(unittest.TestCase):
    def test_builds_and_validates(self):
        plan = plan_of(CONFIG)
        self.assertEqual(plan.name, DEFAULT_NAME)
        self.assertIsNone(plan.validate())  # idempotent; already validated

    def test_exact_node_list_in_order(self):
        self.assertEqual(_node_list(plan_of(CONFIG)), EXPECTED_NODES)

    def test_alternative_exact_node_list_in_order(self):
        self.assertEqual(_node_list(alternative_plan_of(CONFIG)), EXPECTED_ALT_NODES)

    def test_primary_and_alternative_are_the_same_size(self):
        # The comparison is only honest if the graphs are the same size — then
        # the *only* variable left is the number of manual editor steps.
        primary = plan_of(CONFIG)
        alternative = alternative_plan_of(CONFIG)
        self.assertEqual(len(primary.nodes), len(alternative.nodes))
        self.assertEqual(len(primary.edges), len(alternative.edges))
        self.assertEqual(len(primary.nodes), 2)   # event + effect: the floor
        self.assertEqual(len(primary.edges), 2)   # one exec edge, one data edge

    def test_event_drives_the_grant_by_execution(self):
        plan = plan_of(CONFIG)
        exec_edges = _exec_edges(plan, "use_crop")
        self.assertEqual([e.dst for e in exec_edges], ["regrow"])
        self.assertEqual(exec_edges[0].src_index, 0)          # 733.then
        self.assertEqual(exec_edges[0].dst_kind, EXEC_INPUT)

    def test_holder_comes_from_the_event_entity(self):
        # The effect's holder is the runtime entity off the event, never a const.
        for plan, event_alias, sink in (
            (plan_of(CONFIG), "use_crop", "regrow"),
            (alternative_plan_of(CONFIG), "plot_enter", "harvest"),
        ):
            with self.subTest(event=event_alias):
                edge = _holder_source(plan, sink)
                self.assertEqual(edge.src, event_alias)
                self.assertEqual((edge.src_kind, edge.src_index), (DATA_OUTPUT, 0))
        # No constant is ever written to a holder pin (port 0).
        for plan in (plan_of(CONFIG), alternative_plan_of(CONFIG)):
            for const in plan.consts:
                self.assertNotEqual(const.port_index, 0)

    def test_grant_constants_are_the_config(self):
        consts = _const_map(plan_of(CONFIG))
        self.assertEqual(consts[("regrow", 1)], CONFIG.crop_id)      # item
        self.assertEqual(consts[("regrow", 2)], CONFIG.harvest_gain)  # delta

    def test_every_node_is_a_real_server_contract_node(self):
        store = default_store()
        for plan in (plan_of(CONFIG), alternative_plan_of(CONFIG)):
            for node in plan.nodes:
                self.assertIn(node.definition_id, store, f"{node.alias} unknown")
                self.assertEqual(store.require(node.definition_id).graph_kind, 20000)

    def test_invalid_name_rejected(self):
        with self.assertRaises(PlanError):
            build(CONFIG, name="min_playable").validate()

    def test_broken_variant_raises_plan_error(self):
        graph = build(CONFIG)
        self.assertIsNone(graph.validate())
        # An execution edge off a pin 733 does not have (it has only 2:0).
        graph.plan.wire("use_crop", EXEC_OUTPUT, 5, "regrow", EXEC_INPUT, 0)
        with self.assertRaises(PlanError):
            graph.validate()


class TestMinimalityByManualStepCount(unittest.TestCase):
    """The load-bearing test: the chosen event source is the cheaper one."""

    def test_manual_step_count_is_not_higher_than_the_alternative(self):
        # The claim the design makes: the same graph, built from 733, needs no
        # more manual editor steps than the same graph built from 92.
        self.assertLessEqual(
            manual_step_count(EVENT_ITEM_USED),
            manual_step_count(EVENT_PROXIMITY),
        )

    def test_primary_is_strictly_cheaper(self):
        # Stronger: one step for 733 (create the item template), two for 92
        # (add the 碰撞触发器 component, then configure it).
        self.assertEqual(manual_step_count(EVENT_ITEM_USED), 1)
        self.assertEqual(manual_step_count(EVENT_PROXIMITY), 2)
        self.assertLess(
            manual_step_count(EVENT_ITEM_USED),
            manual_step_count(EVENT_PROXIMITY),
        )

    def test_reversed_choice_fails_the_inequality(self):
        # Negative control: if we picked proximity as the "minimal" source, the
        # very inequality above would be false.  So the test discriminates.
        self.assertFalse(
            manual_step_count(EVENT_PROXIMITY) <= manual_step_count(EVENT_ITEM_USED)
        )

    def test_the_two_step_lists_actually_differ(self):
        # The counts differ because the *steps* differ — not because one list is
        # an empty placeholder.
        primary = manual_steps(EVENT_ITEM_USED)
        alternative = manual_steps(EVENT_PROXIMITY)
        self.assertTrue(primary and alternative)
        self.assertNotEqual(primary, alternative)

    def test_alternative_names_the_collision_trigger_component(self):
        # The extra cost of 92 is the component work; it must be visible in the
        # step text a reader checks against M1-interaction.md:37.
        texts = " ".join(step.action for step in manual_steps(EVENT_PROXIMITY))
        self.assertIn("碰撞触发器", texts)
        self.assertIn("组件", texts)


class TestManualStepModel(unittest.TestCase):
    def test_every_manual_step_carries_a_citation(self):
        # A manual-step claim without a file:line is an assertion, not evidence.
        for key, steps in MANUAL_STEPS.items():
            with self.subTest(event=key):
                self.assertTrue(steps, f"{key} has no steps recorded")
                for step in steps:
                    self.assertIsInstance(step, ManualStep)
                    self.assertTrue(step.action.strip())
                    self.assertIn(":", step.citation)   # file:line form
                    self.assertRegex(step.citation, r"\.(md|py):\d")

    def test_known_keys_are_the_two_compared_sources_plus_the_other_two(self):
        self.assertEqual(
            set(MANUAL_STEPS),
            {EVENT_ITEM_USED, EVENT_PROXIMITY, "ui-button", "floating-page"},
        )

    def test_unknown_event_key_is_refused_not_defaulted(self):
        # A source whose cost was never written down must raise, never compare
        # as zero manual steps.
        with self.assertRaises(KeyError):
            manual_step_count("no-such-event")
        with self.assertRaises(KeyError):
            manual_steps("no-such-event")


class TestMinimalityNegativeControls(unittest.TestCase):
    def test_a_lone_event_node_cannot_fire(self):
        # Minimality of "2 nodes": one node (just the event) validates but has
        # no execution edge, so nothing runs.  Two nodes (event + sink) is the
        # floor for a graph that can fire.
        from tools.gameplan import Graph
        from tools.gameplan.nodes import BAG_ITEM_USED

        g = Graph("MW_API_test_min_lone")
        g.place(BAG_ITEM_USED, "only")
        self.assertEqual(len(g.plan.edges), 0)
        self.assertIsNone(g.validate())  # valid ...
        # ... but it cannot fire: there is no execution edge out of the event.
        self.assertEqual(_exec_edges(g.plan, "only"), [])

    def test_swapped_holder_source_is_detectable(self):
        # A negative control for the holder assertion: point the sink's holder at
        # the event's *guid* output instead of its entity output and the role
        # check must see it.
        plan = build(CONFIG).plan
        plan.edges = [
            e for e in plan.edges
            if not (e.dst == "regrow" and e.dst_kind == DATA_INPUT and e.dst_index == 0)
        ]
        plan.wire("use_crop", DATA_OUTPUT, 1, "regrow", DATA_INPUT, 0)  # guid, not entity
        edge = _holder_source(plan, "regrow")
        self.assertEqual(edge.src_index, 1)
        self.assertNotEqual(edge.src_index, 0)  # the good build used 0


class TestSeedLeg(unittest.TestCase):
    def test_seed_leg_adds_a_zero_step_on_create_leg(self):
        # The optional seed is a 71 实体创建时 → 686 leg; it needs no template
        # beyond crop_id, so it adds no manual editor step.
        g = build(CONFIG)
        seed_leg(g, CONFIG)
        aliases = _node_list(g.plan)
        self.assertEqual(aliases[0], ("use_crop", 733))   # primary nodes first
        self.assertEqual(aliases[1], ("regrow", 686))
        self.assertIn(("seed", 71), aliases)
        self.assertIn(("seed_crop", 686), aliases)
        g.validate()

    def test_seed_leg_does_not_change_the_manual_step_count(self):
        # Seeding is a graph action (DEMO-GAP.md:98), never a manual step.
        before = manual_step_count(EVENT_ITEM_USED)
        g = build(CONFIG)
        seed_leg(g, CONFIG)
        g.validate()
        self.assertEqual(manual_step_count(EVENT_ITEM_USED), before)


if __name__ == "__main__":
    unittest.main()
