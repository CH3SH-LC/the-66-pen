"""Tests for the full six-direction farming demo plan (offline; graph, not machine).

Covers both the graph's *shape* (exact nodes, edges and constants) and the
*meaning* of the wires (which branch output drives the recipe; where the holder
entities come from).  A negative control proves the branch-output assertions
actually discriminate.
"""

import unittest

from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, EXEC_OUTPUT
from tools.gameplan.demo.farming_full import (
    DEFAULT_NAME,
    FarmFullConfig,
    build,
    build_plan,
    plan_shape,
)
from tools.gameplan.golden import COMMITTED_DIR, compare_file, dumps, freeze
from tools.gameplan.plan import EdgeSpec, PlanError


CONFIG = FarmFullConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

# A config that turns on the #13 "收菜直接给钱" leg.  Same ids as CONFIG, only
# harvest_bonus differs, so the two node lists are directly comparable.
BONUS_CONFIG = FarmFullConfig(
    currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
    food_id=CONFIG.food_id, harvest_bonus=7,
)

# Node aliases that are *event* entry points: an entity read off one of these is
# the real runtime entity, never a guessed constant.
EVENT_ALIASES = frozenset({"plot_enter", "crop_used", "stall_enter", "money_changed"})

EXPECTED_NODES = (
    ("plot_enter", 92),
    ("harvest", 686),
    ("crop_used", 733),
    ("crop_count", 690),
    ("enough", 233),
    ("gate", 2),
    ("consume", 686),
    ("bake", 686),
    ("short", 1),
    ("stall_enter", 92),
    ("open_shop", 702),
    ("sold", 701),
    ("sold_note", 1),
    ("money_changed", 684),
    ("money_note", 1),
)


def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _edge_tuples(plan):
    """Every edge as a plain 6-tuple, in the plan's own (build) order."""
    return [
        (e.src, e.src_kind, e.src_index, e.dst, e.dst_kind, e.dst_index)
        for e in plan.edges
    ]


def _holder_source(plan, alias):
    """The data edge that fills a node's ``holder`` input (port 0)."""
    return next(
        e for e in plan.edges
        if e.dst == alias and e.dst_kind == DATA_INPUT and e.dst_index == 0
    )


def _branch_targets(plan):
    """(true-targets, false-targets) wired off the 双分支 node 'gate'.

    TRUE is execution output index 0, FALSE is index 1 (nodes.BRANCH).  Raising
    on a reversed wiring is exactly the negative control's job.
    """
    true_targets = [
        e.dst for e in plan.edges
        if e.src == "gate" and e.src_kind == EXEC_OUTPUT and e.src_index == 0
    ]
    false_targets = [
        e.dst for e in plan.edges
        if e.src == "gate" and e.src_kind == EXEC_OUTPUT and e.src_index == 1
    ]
    return true_targets, false_targets


def _swap_branch_outputs(plan):
    """Return a copy of ``plan.edges`` with the 双分支 outputs reversed."""
    swapped = []
    for e in plan.edges:
        if e.src == "gate" and e.src_kind == EXEC_OUTPUT:
            e = EdgeSpec(e.src, e.src_kind, 1 - e.src_index, e.dst, e.dst_kind, e.dst_index)
        swapped.append(e)
    return swapped


class TestFarmingFullPlan(unittest.TestCase):
    def test_builds_and_validates(self):
        plan = build_plan(CONFIG)
        self.assertEqual(plan.name, DEFAULT_NAME)
        self.assertIsNone(plan.validate())  # idempotent; already validated in build_plan

    def test_exact_node_list_in_order(self):
        plan = build_plan(CONFIG)
        got = tuple((n.alias, n.definition_id) for n in plan.nodes)
        self.assertEqual(got, EXPECTED_NODES)

    def test_plan_shape_helper_matches_the_plan(self):
        graph = build(CONFIG)
        shape = plan_shape(graph.plan)
        self.assertEqual(shape.node_count, len(EXPECTED_NODES))
        self.assertEqual(shape.node_count, len(graph.plan.nodes))
        self.assertEqual(shape.edge_count, len(graph.plan.edges))
        self.assertEqual(shape.const_count, len(graph.plan.consts))
        self.assertEqual(shape.ordered_nodes, EXPECTED_NODES)

    def test_recipe_numbers(self):
        consts = _const_map(build_plan(CONFIG))
        self.assertEqual(consts[("enough", 1)], CONFIG.recipe_cost)   # 233 right operand
        self.assertEqual(consts[("consume", 2)], -CONFIG.recipe_cost)  # 686 delta
        self.assertEqual(consts[("bake", 2)], CONFIG.cook_gain)        # 686 delta
        self.assertEqual(consts[("harvest", 2)], CONFIG.harvest_gain)
        self.assertEqual(consts[("consume", 1)], CONFIG.crop_id)
        self.assertEqual(consts[("bake", 1)], CONFIG.food_id)
        self.assertEqual(consts[("harvest", 1)], CONFIG.crop_id)

    def test_recipe_numbers_are_parameterised(self):
        cfg = FarmFullConfig(
            currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
            food_id=CONFIG.food_id, recipe_cost=5, harvest_gain=3, cook_gain=2,
        )
        consts = _const_map(build_plan(cfg))
        self.assertEqual(consts[("enough", 1)], 5)
        self.assertEqual(consts[("consume", 2)], -5)
        self.assertEqual(consts[("bake", 2)], 2)
        self.assertEqual(consts[("harvest", 2)], 3)

    def test_branch_true_drives_the_recipe(self):
        true_targets, false_targets = _branch_targets(build_plan(CONFIG))
        # 是 (index 0) leads into the consume step, which chains to bake.
        self.assertEqual(true_targets, ["consume"])
        # 否 (index 1) prints the shortage message.
        self.assertEqual(false_targets, ["short"])
        # and exactly two execution edges leave the gate.
        self.assertEqual(len(true_targets) + len(false_targets), 2)

    def test_branch_true_edge_shape(self):
        plan = build_plan(CONFIG)
        edge = next(e for e in plan.edges if e.src == "gate" and e.dst == "consume")
        self.assertEqual((edge.src_kind, edge.src_index), (EXEC_OUTPUT, 0))
        self.assertEqual((edge.dst_kind, edge.dst_index), (EXEC_INPUT, 0))

    def test_branch_false_edge_shape(self):
        plan = build_plan(CONFIG)
        edge = next(e for e in plan.edges if e.src == "gate" and e.dst == "short")
        self.assertEqual((edge.src_kind, edge.src_index), (EXEC_OUTPUT, 1))  # 否
        self.assertEqual((edge.dst_kind, edge.dst_index), (EXEC_INPUT, 0))

    def test_swapped_branch_outputs_are_detectable(self):
        # Negative control: the index-based assertions above must change when the
        # 双分支 outputs are reversed — otherwise they prove nothing.
        good = build_plan(CONFIG)
        broken_plan = build(CONFIG).plan
        broken_plan.edges = _swap_branch_outputs(broken_plan)

        self.assertEqual(_branch_targets(good), (["consume"], ["short"]))
        self.assertNotEqual(_branch_targets(good), _branch_targets(broken_plan))
        self.assertEqual(_branch_targets(broken_plan), (["short"], ["consume"]))

    def test_every_686_holder_comes_from_an_event_entity(self):
        plan = build_plan(CONFIG)
        grant_aliases = [n.alias for n in plan.nodes if n.definition_id == 686]
        self.assertEqual(grant_aliases, ["harvest", "consume", "bake"])
        for alias in grant_aliases:
            edge = _holder_source(plan, alias)
            # holder is data, comes from an event node, off its entity output.
            self.assertEqual(edge.src_kind, DATA_OUTPUT)
            self.assertIn(edge.src, EVENT_ALIASES, f"{alias} holder not an event")
            self.assertEqual(edge.src_index, 0, f"{alias} holder not the entity output")
        # holder must never be written as a constant.
        for const in plan.consts:
            if const.alias in grant_aliases:
                self.assertNotEqual(const.port_index, 0,
                                    f"{const.alias} has a constant holder")

    def test_crop_count_feeds_the_comparison_left_operand(self):
        plan = build_plan(CONFIG)
        edge = next(e for e in plan.edges if e.src == "crop_count" and e.dst == "enough")
        self.assertEqual((edge.src_kind, edge.dst_kind), (DATA_OUTPUT, DATA_INPUT))
        self.assertEqual((edge.src_index, edge.dst_index), (0, 0))  # amount -> left

    def test_comparison_result_gates_the_branch(self):
        plan = build_plan(CONFIG)
        edge = next(e for e in plan.edges if e.src == "enough" and e.dst == "gate")
        self.assertEqual((edge.src_kind, edge.dst_kind), (DATA_OUTPUT, DATA_INPUT))
        self.assertEqual((edge.src_index, edge.dst_index), (0, 0))  # result -> condition

    def test_shop_opens_on_stall_entry(self):
        plan = build_plan(CONFIG)
        # exec: stall_enter ----then----> open_shop
        exec_edge = next(
            e for e in plan.edges
            if e.src == "stall_enter" and e.dst == "open_shop" and e.src_kind == EXEC_OUTPUT
        )
        self.assertEqual(exec_edge.src_index, 0)
        # data: stall_enter.entrant -> player ; stall_enter.trigger -> shop_owner
        player_edge = next(
            e for e in plan.edges
            if e.src == "stall_enter" and e.dst == "open_shop" and e.dst_index == 0
        )
        owner_edge = next(
            e for e in plan.edges
            if e.src == "stall_enter" and e.dst == "open_shop" and e.dst_index == 1
        )
        self.assertEqual(player_edge.src_index, 0)  # entrant
        self.assertEqual(owner_edge.src_index, 2)   # trigger
        self.assertEqual(_const_map(plan)[("open_shop", 2)], 0)  # shop_index

    def test_currency_change_is_a_single_execution_edge_to_print(self):
        plan = build_plan(CONFIG)
        exec_out = [
            e for e in plan.edges
            if e.src == "money_changed" and e.src_kind == EXEC_OUTPUT
        ]
        self.assertEqual(len(exec_out), 1)
        self.assertEqual(exec_out[0].dst, "money_note")
        self.assertEqual((exec_out[0].src_kind, exec_out[0].src_index), (EXEC_OUTPUT, 0))
        self.assertEqual((exec_out[0].dst_kind, exec_out[0].dst_index), (EXEC_INPUT, 0))
        # and the print carries the feedback text.
        self.assertEqual(_const_map(plan)[("money_note", 0)], "货币发生变化")

    def test_short_path_text(self):
        self.assertEqual(_const_map(build_plan(CONFIG))[("short", 0)], "材料不足")

    def test_name_is_parameterised(self):
        plan = build_plan(CONFIG, name="MW_API_FARM_FULL_ALT")
        self.assertEqual(plan.name, "MW_API_FARM_FULL_ALT")

    def test_invalid_name_rejected(self):
        with self.assertRaises(PlanError):
            build(CONFIG, name="farm_full").validate()

    def test_broken_variant_raises_plan_error(self):
        graph = build(CONFIG)
        self.assertIsNone(graph.validate())          # good plan is clean
        # A deliberately broken variant: an execution edge off a pin the 双分支
        # definition does not have (exec output index 5).
        graph.plan.wire("gate", EXEC_OUTPUT, 5, "short", EXEC_INPUT, 0)
        with self.assertRaises(PlanError):
            graph.validate()

    def test_every_node_definition_is_a_real_contract_node(self):
        from tools.gameplan.contracts import default_store
        store = default_store()
        for node in build_plan(CONFIG).nodes:
            self.assertIn(node.definition_id, store, f"{node.alias} unknown")
            self.assertEqual(store.require(node.definition_id).graph_kind, 20000)


class TestHarvestBonusBranch(unittest.TestCase):
    """#13 — 收菜直接给钱支线: an optional 688 coin sink on the plot-enter event.

    The branch must be *inert* at the default ``harvest_bonus=0`` (the legacy
    node list is unchanged) and must add exactly one 688 node driven by the very
    same 92 execution output the crop sink uses when it is switched on.
    """

    def test_default_harvest_bonus_is_zero(self):
        # The default is what keeps the zero-bonus build byte-identical.
        self.assertEqual(FarmFullConfig.__dataclass_fields__["harvest_bonus"].default, 0)

    def test_zero_bonus_keeps_the_legacy_node_list_unchanged(self):
        # Spell the config out with harvest_bonus=0 (not just relying on the
        # default) and assert the node list is *today's* list, verbatim.
        cfg = FarmFullConfig(
            currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
            food_id=CONFIG.food_id, harvest_bonus=0,
        )
        got = tuple((n.alias, n.definition_id) for n in build_plan(cfg).nodes)
        self.assertEqual(got, EXPECTED_NODES)
        # Engine settlement must not emit a second 688 payment.
        self.assertEqual(
            [n.alias for n in build_plan(cfg).nodes if n.definition_id == 688],
            [],
        )
        # And the vanilla CONFIG (which also leaves the bonus at 0) is identical.
        self.assertEqual(
            tuple((n.alias, n.definition_id) for n in build_plan(CONFIG).nodes),
            got,
        )

    def test_positive_bonus_adds_one_688_coin_node(self):
        plan = build_plan(BONUS_CONFIG)
        node = next((n for n in plan.nodes if n.alias == "harvest_bonus"), None)
        self.assertIsNotNone(node, "harvest_bonus node missing")
        self.assertEqual(node.definition_id, 688)  # 增加背包货币数量
        consts = _const_map(plan)
        self.assertEqual(consts[("harvest_bonus", 1)], BONUS_CONFIG.currency_id)   # currency
        self.assertEqual(consts[("harvest_bonus", 2)], BONUS_CONFIG.harvest_bonus)  # +delta

    def test_positive_bonus_node_list_is_legacy_plus_one(self):
        # The whole list is exactly the old list with one node spliced in right
        # after `harvest` — nothing else moved.
        expected = list(EXPECTED_NODES)
        expected.insert(2, ("harvest_bonus", 688))
        got = [(n.alias, n.definition_id) for n in build_plan(BONUS_CONFIG).nodes]
        self.assertEqual(got, expected)

    def test_both_sinks_hang_off_the_same_92_execution_output(self):
        plan = build_plan(BONUS_CONFIG)
        exec_edges = [
            e for e in plan.edges
            if e.src == "plot_enter" and e.src_kind == EXEC_OUTPUT
        ]
        # The plot-enter event fans out to exactly two sinks: crops and coins.
        self.assertEqual(sorted(e.dst for e in exec_edges), ["harvest", "harvest_bonus"])
        for e in exec_edges:
            self.assertEqual((e.src_kind, e.src_index), (EXEC_OUTPUT, 0))  # then
            self.assertEqual((e.dst_kind, e.dst_index), (EXEC_INPUT, 0))

    def test_bonus_holder_comes_from_the_event_entity(self):
        plan = build_plan(BONUS_CONFIG)
        edge = _holder_source(plan, "harvest_bonus")
        self.assertEqual(edge.src, "plot_enter")
        self.assertEqual((edge.src_kind, edge.src_index), (DATA_OUTPUT, 0))  # entrant

    def test_bonus_branch_validates_as_a_real_contract_node(self):
        plan = build_plan(BONUS_CONFIG)
        self.assertIsNone(plan.validate())
        from tools.gameplan.contracts import default_store
        store = default_store()
        for node in plan.nodes:
            self.assertEqual(store.require(node.definition_id).graph_kind, 20000)

    def test_zero_bonus_matches_the_committed_golden(self):
        # #9 guard: the =0 build IS the main graph.  Pin it to the reviewed
        # golden snapshot (tools/gameplan/golden/farming_full.json) so a future
        # change to the bonus leg that leaks into the default build shows up as
        # a visible diff, never as a silent drift.
        cfg = FarmFullConfig(
            currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
            food_id=CONFIG.food_id, harvest_bonus=0,
        )
        plan = build_plan(cfg)
        report = compare_file(plan, "farming_full", directory=COMMITTED_DIR)
        self.assertTrue(report.ok, f"harvest_bonus=0 drifted from the golden:\n{report}")
        self.assertEqual(report.changes, ())
        # Byte-identical, not merely structurally equal.
        self.assertEqual(
            (COMMITTED_DIR / "farming_full.json").read_text(encoding="utf-8"),
            dumps(freeze(plan)),
        )

    def test_positive_bonus_exact_edge_list_is_legacy_plus_two(self):
        # The whole >0 edge list is exactly the =0 list with two edges spliced
        # in after the crop legs: the fan-out from the one 92 execution output
        # (then) to the coin sink, plus its entrant->holder data edge.
        zero = _edge_tuples(build_plan(CONFIG))
        bonus = _edge_tuples(build_plan(BONUS_CONFIG))
        spliced = [
            ("plot_enter", EXEC_OUTPUT, 0, "harvest_bonus", EXEC_INPUT, 0),
            ("plot_enter", DATA_OUTPUT, 0, "harvest_bonus", DATA_INPUT, 0),
        ]
        self.assertEqual(bonus, zero[:2] + spliced + zero[2:])
        self.assertEqual(len(bonus), len(zero) + 2)

    def test_fan_out_from_the_one_92_execution_output_is_exact(self):
        # Both sinks hang off 进入碰撞触发器时.then (92 exec-out 0) — exact order.
        plan = build_plan(BONUS_CONFIG)
        fan = [
            e for e in _edge_tuples(plan)
            if e[0] == "plot_enter" and e[1] == EXEC_OUTPUT
        ]
        self.assertEqual(fan, [
            ("plot_enter", EXEC_OUTPUT, 0, "harvest", EXEC_INPUT, 0),
            ("plot_enter", EXEC_OUTPUT, 0, "harvest_bonus", EXEC_INPUT, 0),
        ])


if __name__ == "__main__":
    unittest.main()
