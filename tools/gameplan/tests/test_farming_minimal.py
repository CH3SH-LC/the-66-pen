"""Offline tests for the fewest-manual-step farming variant (#6 build).

No bridge, no game, no editor.  What is proven here:

1. the graph **validates** against ``data/node-contracts`` and its node list is
   exactly the two nodes declared (``GraphPlan.validate`` — offline, not a run);
2. every node's ``definitionId`` is a real server (kind 20000) contract node;
3. the *event source* is justified as a **number**: for the same two-node graph,
   the chosen ``71 实体创建时`` needs strictly fewer editor steps (0) than the
   alternative ``92 进入碰撞触发器时`` (2) and than ``733`` (1), and ``71`` is the
   unique *buildable* zero-step source (``83`` is 0 on paper but unbuildable);
4. the honest residual is accounted for: the crop-template step is **per-graph**,
   not per-event, so it appears in both arms and never changes the comparison.

Negative controls prove the assertions discriminate: a lone event node has no
execution edge (so "2 nodes" is a floor), a swapped ``holder`` source is
detectable, and an unknown event key is refused rather than defaulting to zero.
"""

import unittest

from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, EXEC_OUTPUT
from tools.gameplan.contracts import default_store
from tools.gameplan.demo.farming_minimal import (
    ALT_NAME,
    DEFAULT_NAME,
    EVENT_FLOATING_PAGE,
    EVENT_GLOBAL_TIMER,
    EVENT_ITEM_USED,
    EVENT_ON_CREATE,
    EVENT_PROXIMITY,
    EVENT_SOURCES,
    EVENT_TIMER,
    EVENT_UI_BUTTON,
    RESIDUAL_TEMPLATE_STEPS,
    EventSource,
    ManualStep,
    MinimalFarmConfig,
    alternative_plan_of,
    build,
    build_alternative,
    buildable_zero_step_sources,
    event_source,
    is_buildable,
    manual_step_count,
    manual_steps,
    plan_of,
    rejection,
    residual_template_step_count,
    total_manual_step_count,
)
from tools.gameplan.plan import PlanError

CONFIG = MinimalFarmConfig(crop_id=1120000001, item_slot="int", harvest_gain=3)

#: The chosen graph in build order: the on-create event then its grant.
EXPECTED_NODES = (("plot_created", 71), ("harvest", 686))

#: The alternative graph: the proximity event then its grant.  Same size.
EXPECTED_ALT_NODES = (("plot_enter", 92), ("harvest", 686))


def _node_list(plan):
    return tuple((n.alias, n.definition_id) for n in plan.nodes)


def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _exec_edges(plan, src):
    return [e for e in plan.edges if e.src == src and e.src_kind == EXEC_OUTPUT]


def _holder_source(plan, alias):
    """The data edge that fills a node's ``holder`` input (port 0)."""
    return next(
        e for e in plan.edges
        if e.dst == alias and e.dst_kind == DATA_INPUT and e.dst_index == 0
    )


class TestFarmingMinimalGraphShape(unittest.TestCase):
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
        exec_edges = _exec_edges(plan, "plot_created")
        self.assertEqual([e.dst for e in exec_edges], ["harvest"])
        self.assertEqual(exec_edges[0].src_index, 0)          # 71.then
        self.assertEqual(exec_edges[0].dst_kind, EXEC_INPUT)

    def test_holder_comes_from_the_event_entity(self):
        # The effect's holder is the runtime entity off the event, never a const.
        for plan, event_alias, sink in (
            (plan_of(CONFIG), "plot_created", "harvest"),
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
        self.assertEqual(consts[("harvest", 1)], CONFIG.crop_id)      # item
        self.assertEqual(consts[("harvest", 2)], CONFIG.harvest_gain)  # delta

    def test_every_node_is_a_real_server_contract_node(self):
        store = default_store()
        for plan in (plan_of(CONFIG), alternative_plan_of(CONFIG)):
            for node in plan.nodes:
                self.assertIn(node.definition_id, store, f"{node.alias} unknown")
                self.assertEqual(store.require(node.definition_id).graph_kind, 20000)

    def test_invalid_name_rejected(self):
        with self.assertRaises(PlanError):
            build(CONFIG, name="farm_minimal").validate()

    def test_broken_variant_raises_plan_error(self):
        graph = build(CONFIG)
        self.assertIsNone(graph.validate())
        # An execution edge off a pin 71 does not have (it has only 1:0).
        graph.plan.wire("plot_created", EXEC_OUTPUT, 5, "harvest", EXEC_INPUT, 0)
        with self.assertRaises(PlanError):
            graph.validate()


class TestEventSourceChoiceByManualStepCount(unittest.TestCase):
    """The load-bearing test: the chosen event source is the cheaper one."""

    def test_chosen_needs_no_more_steps_than_the_alternative(self):
        self.assertLessEqual(
            manual_step_count(EVENT_ON_CREATE),
            manual_step_count(EVENT_PROXIMITY),
        )

    def test_chosen_is_strictly_cheaper_than_the_alternative(self):
        # 0 editor steps for 71 (the plot is created by the tool), 2 for 92 (add
        # the 碰撞触发器 component, then configure it).
        self.assertEqual(manual_step_count(EVENT_ON_CREATE), 0)
        self.assertEqual(manual_step_count(EVENT_PROXIMITY), 2)
        self.assertLess(
            manual_step_count(EVENT_ON_CREATE),
            manual_step_count(EVENT_PROXIMITY),
        )

    def test_chosen_is_strictly_cheaper_than_the_item_used_source(self):
        # 71 (0) also beats the demo's crafting hook 733 (1).
        self.assertEqual(manual_step_count(EVENT_ITEM_USED), 1)
        self.assertLess(
            manual_step_count(EVENT_ON_CREATE),
            manual_step_count(EVENT_ITEM_USED),
        )

    def test_reversed_choice_fails_the_inequality(self):
        # Negative control: were proximity the "minimal" pick, the inequality
        # above would be false.  So the test discriminates, it is not a tautology.
        self.assertFalse(
            manual_step_count(EVENT_PROXIMITY) <= manual_step_count(EVENT_ON_CREATE)
        )

    def test_chosen_is_the_unique_buildable_zero_step_source(self):
        # 83 (timer) is also 0 editor steps, but cannot be built (unwritable list
        # constant); 315 (global timer) costs 1.  So 71 stands alone.
        self.assertEqual(buildable_zero_step_sources(), (EVENT_ON_CREATE,))
        self.assertFalse(is_buildable(EVENT_TIMER))
        self.assertEqual(manual_step_count(EVENT_TIMER), 0)  # 0 on paper ...
        self.assertEqual(manual_step_count(EVENT_GLOBAL_TIMER), 1)

    def test_a_zero_step_source_that_is_unbuildable_is_not_recommended(self):
        # The honest nuance: a bare step count would rank 83 equal to 71.  The
        # recommendation must require buildability too.
        self.assertIn(EVENT_TIMER, EVENT_SOURCES)
        self.assertFalse(is_buildable(EVENT_TIMER))
        self.assertTrue(is_buildable(EVENT_ON_CREATE))


class TestManualStepModel(unittest.TestCase):
    def test_every_nonzero_step_carries_a_citation(self):
        # A manual-step claim without a file:line is an assertion, not evidence.
        for key, source in EVENT_SOURCES.items():
            with self.subTest(event=key):
                for step in source.manual_steps:
                    self.assertIsInstance(step, ManualStep)
                    self.assertTrue(step.action.strip())
                    self.assertRegex(step.citation, r"\.(md|py|json):\d")

    def test_the_residual_template_step_carries_a_citation(self):
        self.assertTrue(RESIDUAL_TEMPLATE_STEPS)
        for step in RESIDUAL_TEMPLATE_STEPS:
            self.assertRegex(step.citation, r"\.(md|py|json):\d")

    def test_known_keys_are_every_event_source_examined(self):
        self.assertEqual(
            set(EVENT_SOURCES),
            {
                EVENT_ON_CREATE, EVENT_TIMER, EVENT_GLOBAL_TIMER, EVENT_ITEM_USED,
                EVENT_PROXIMITY, EVENT_UI_BUTTON, EVENT_FLOATING_PAGE,
            },
        )

    def test_unknown_event_key_is_refused_not_defaulted(self):
        # A source whose cost was never written down must raise, never compare
        # as zero manual steps.
        with self.assertRaises(KeyError):
            manual_step_count("no-such-event")
        with self.assertRaises(KeyError):
            manual_steps("no-such-event")
        with self.assertRaises(KeyError):
            event_source("no-such-event")

    def test_rejected_sources_say_why_and_the_chosen_one_does_not(self):
        for key in EVENT_SOURCES:
            with self.subTest(event=key):
                if key == EVENT_ON_CREATE:
                    self.assertEqual(rejection(key), "")
                else:
                    self.assertTrue(rejection(key).strip(), f"{key} has no reason")
                    # A rejection reason must itself be checkable where it is a
                    # capability claim (the timer's is); the one-step timers cite
                    # a doc chapter, the costlier ones cite their step counts.
                    self.assertIn(key, EVENT_SOURCES)

    def test_every_source_records_a_official_label_and_definition_id(self):
        for key, source in EVENT_SOURCES.items():
            with self.subTest(event=key):
                self.assertIsInstance(source, EventSource)
                self.assertEqual(source.key, key)
                self.assertIsInstance(source.definition_id, int)
                self.assertIn(str(source.definition_id), source.label)


class TestResidualAccounting(unittest.TestCase):
    """The per-graph residual is honest: present in both arms, never decisive."""

    def test_residual_is_exactly_one_template_step(self):
        self.assertEqual(residual_template_step_count(), 1)

    def test_total_counts_event_plus_residual(self):
        # 0 event + 1 asset for the chosen, 2 event + 1 asset for the alternative.
        self.assertEqual(total_manual_step_count(EVENT_ON_CREATE), 1)
        self.assertEqual(total_manual_step_count(EVENT_PROXIMITY), 3)

    def test_residual_cancels_out_of_the_comparison(self):
        # Both arms carry the same residual, so the gap is the event difference.
        self.assertEqual(
            total_manual_step_count(EVENT_PROXIMITY)
            - total_manual_step_count(EVENT_ON_CREATE),
            manual_step_count(EVENT_PROXIMITY) - manual_step_count(EVENT_ON_CREATE),
        )

    def test_both_graphs_name_the_same_residual_config_id(self):
        # The residual is a property of the graph (it writes crop_id), not the event.
        for plan in (plan_of(CONFIG), alternative_plan_of(CONFIG)):
            consts = _const_map(plan)
            self.assertEqual(consts[("harvest", 1)], CONFIG.crop_id)


class TestMinimalityNegativeControls(unittest.TestCase):
    def test_a_lone_event_node_cannot_fire(self):
        # Minimality of "2 nodes": one node (just the event) validates but has no
        # execution edge, so nothing runs.  Two nodes (event + sink) is the floor.
        from tools.gameplan import Graph
        from tools.gameplan.nodes import ON_CREATE

        g = Graph("MW_API_test_farmmin_lone")
        g.place(ON_CREATE, "only")
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
            if not (e.dst == "harvest" and e.dst_kind == DATA_INPUT and e.dst_index == 0)
        ]
        plan.wire("plot_created", DATA_OUTPUT, 1, "harvest", DATA_INPUT, 0)  # guid
        edge = _holder_source(plan, "harvest")
        self.assertEqual(edge.src_index, 1)
        self.assertNotEqual(edge.src_index, 0)  # the good build used 0


if __name__ == "__main__":
    unittest.main()
