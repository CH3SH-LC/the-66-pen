"""Tests for the game-B farming demo plan (offline; the graph, not the machine)."""

import unittest

from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, EXEC_OUTPUT
from tools.gameplan.demo.farming import FarmConfig, build, build_plan
from tools.gameplan.plan import PlanError


CONFIG = FarmConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)


class TestFarmingPlan(unittest.TestCase):
    def test_builds_and_validates(self):
        plan = build_plan(CONFIG)
        self.assertEqual(plan.name, "MW_API_FARM_V0")
        plan.validate()  # idempotent; already validated inside build_plan

    def test_expected_nodes_and_order(self):
        plan = build_plan(CONFIG)
        got = [(n.alias, n.definition_id) for n in plan.nodes]
        self.assertEqual(got, [
            ("plot_enter", 92), ("harvest", 686), ("crop_used", 733), ("crop_count", 690),
            ("enough", 233), ("gate", 2), ("consume", 686), ("bake", 686), ("short", 1),
            ("stall_enter", 92), ("open_shop", 702), ("money_changed", 684), ("money_note", 1),
        ])

    def test_recipe_consumes_two_and_produces_one(self):
        graph = build(CONFIG)
        consts = {(c.alias, c.port_index): c.value for c in graph.plan.consts}
        self.assertEqual(consts[("consume", 2)], -CONFIG.recipe_cost)   # delta
        self.assertEqual(consts[("bake", 2)], 1)                        # delta
        self.assertEqual(consts[("enough", 1)], CONFIG.recipe_cost)     # comparison right-hand side
        self.assertEqual(consts[("consume", 1)], CONFIG.crop_id)
        self.assertEqual(consts[("bake", 1)], CONFIG.food_id)

    def test_gate_true_drives_the_recipe(self):
        graph = build(CONFIG)
        ids = graph.plan.aliases()
        # gate (双分支) -> consume on its TRUE execution output (index 0), not the default.
        edge = next(e for e in graph.plan.edges
                    if e.src == "gate" and e.dst == "consume")
        self.assertEqual((edge.src_kind, edge.src_index), (EXEC_OUTPUT, 0))
        self.assertEqual((edge.dst_kind, edge.dst_index), (EXEC_INPUT, 0))

    def test_gate_false_prints_shortage(self):
        graph = build(CONFIG)
        edge = next(e for e in graph.plan.edges if e.src == "gate" and e.dst == "short")
        self.assertEqual((edge.src_kind, edge.src_index), (EXEC_OUTPUT, 1))  # 否

    def test_holder_comes_from_the_event_not_a_guess(self):
        graph = build(CONFIG)
        # harvest: 92.entrant -> 686.holder
        edge = next(e for e in graph.plan.edges if e.src == "plot_enter" and e.dst == "harvest"
                    and e.src_kind == DATA_OUTPUT)
        self.assertEqual(edge.src_index, 0)  # 进入者实体
        self.assertEqual(edge.dst_index, 0)  # 背包持有者实体

    def test_count_feeds_the_comparison(self):
        graph = build(CONFIG)
        edge = next(e for e in graph.plan.edges if e.src == "crop_count" and e.dst == "enough")
        self.assertEqual((edge.src_kind, edge.dst_kind), (DATA_OUTPUT, DATA_INPUT))
        # 690.amount -> 233.left (a generic pin; native materialises it as int)
        self.assertEqual((edge.src_index, edge.dst_index), (0, 0))

    def test_comparison_result_gates_the_branch(self):
        graph = build(CONFIG)
        edge = next(e for e in graph.plan.edges if e.src == "enough" and e.dst == "gate")
        self.assertEqual((edge.src_kind, edge.dst_kind), (DATA_OUTPUT, DATA_INPUT))
        self.assertEqual((edge.src_index, edge.dst_index), (0, 0))  # result -> condition

    def test_shop_uses_the_stall_entity_as_owner(self):
        graph = build(CONFIG)
        edge = next(e for e in graph.plan.edges if e.src == "stall_enter" and e.dst == "open_shop"
                    and e.dst_index == 1)
        self.assertEqual(edge.src_index, 2)  # 触发器实体

    def test_name_is_parameterised(self):
        plan = build_plan(CONFIG, name="MW_API_FARM_ALT")
        self.assertEqual(plan.name, "MW_API_FARM_ALT")

    def test_invalid_name_rejected(self):
        graph = build(CONFIG, name="farm")  # not MW_API_*
        with self.assertRaises(PlanError):
            graph.validate()

    def test_every_node_definition_is_a_real_contract_node(self):
        from tools.gameplan.contracts import default_store
        store = default_store()
        for node in build_plan(CONFIG).nodes:
            self.assertIn(node.definition_id, store, f"{node.alias} unknown")


if __name__ == "__main__":
    unittest.main()
