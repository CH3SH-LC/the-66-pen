"""Tests for the closed farming *loop* plan (offline; graph, not machine).

:mod:`tools.gameplan.demo.farming_loop` reuses the 15-node ``farming_full`` body
verbatim and appends a 终局 (terminal) leg.  These tests pin:

* the **full node list in order** (the 15 reused body, then the 5 terminal nodes);
* that the loop body *is* ``farming_full``'s graph — not a re-typed copy that can
  drift;
* that **every 双分支 true/false target is exactly as wired** — for both the
  recipe gate and the terminal gate;
* that the **terminal comparison reads the live 691 output**, not a constant;
* the golden snapshot (``tools/gameplan/golden/farming_loop.json``); and
* at least two **negative controls that raise** :class:`PlanError`.

A swapped-output control (no error raised, but the assertions must fire) proves
the index-based branch assertions actually discriminate.
"""

import unittest

from tools.gameplan import golden
from tools.gameplan.contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, EXEC_OUTPUT
from tools.gameplan.demo import farming_full
from tools.gameplan.demo.farming_loop import (
    DEFAULT_NAME,
    FEEDBACK_TEXT,
    LOOP_BODY,
    LoopConfig,
    TERMINAL_KEEP_TEXT,
    TERMINAL_NODES,
    TERMINAL_WIN_TEXT,
    build,
    build_plan,
    golden_plans,
)
from tools.gameplan.plan import EdgeSpec, PlanError

CONFIG = LoopConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

#: The full loop, in build order: the reused body then the terminal leg.
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
    ("ter_read", 691),
    ("ter_cmp", 233),
    ("ter_gate", 2),
    ("win", 1),
    ("keep", 1),
)


def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _branch_targets(plan, gate_alias):
    """(true-targets, false-targets) wired off the 双分支 node ``gate_alias``.

    TRUE is execution output index 0, FALSE is index 1 (``nodes.BRANCH``).
    """
    true_targets = [
        e.dst for e in plan.edges
        if e.src == gate_alias and e.src_kind == EXEC_OUTPUT and e.src_index == 0
    ]
    false_targets = [
        e.dst for e in plan.edges
        if e.src == gate_alias and e.src_kind == EXEC_OUTPUT and e.src_index == 1
    ]
    return true_targets, false_targets


def _swap_branch_outputs(plan, gate_alias):
    """A copy of ``plan.edges`` with ``gate_alias``'s 双分支 outputs reversed."""
    swapped = []
    for e in plan.edges:
        if e.src == gate_alias and e.src_kind == EXEC_OUTPUT:
            e = EdgeSpec(e.src, e.src_kind, 1 - e.src_index, e.dst, e.dst_kind, e.dst_index)
        swapped.append(e)
    return swapped


class TestFarmingLoopPlan(unittest.TestCase):
    def test_builds_and_validates(self):
        plan = build_plan(CONFIG)
        self.assertEqual(plan.name, DEFAULT_NAME)
        self.assertIsNone(plan.validate())  # idempotent; already validated

    def test_exact_node_list_in_order(self):
        plan = build_plan(CONFIG)
        got = tuple((n.alias, n.definition_id) for n in plan.nodes)
        self.assertEqual(got, EXPECTED_NODES)

    def test_loop_body_is_farming_full_verbatim(self):
        # The loop body is not a hand-copy: every body node (alias + id) equals
        # farming_full's, in the same order, so the two graphs cannot drift.
        loop = build_plan(CONFIG)
        base = farming_full.build_plan(
            farming_full.FarmFullConfig(
                currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
                food_id=CONFIG.food_id,
            )
        )
        body = tuple((n.alias, n.definition_id) for n in loop.nodes)[: len(base.nodes)]
        self.assertEqual(body, tuple((n.alias, n.definition_id) for n in base.nodes))
        self.assertEqual(body, EXPECTED_NODES[: len(base.nodes)])

    def test_loop_body_and_terminal_aliases(self):
        plan = build_plan(CONFIG)
        aliases = tuple(n.alias for n in plan.nodes)
        self.assertEqual(aliases, LOOP_BODY + TERMINAL_NODES)
        self.assertEqual(aliases[15:], TERMINAL_NODES)

    # -- 双分支 wiring, both gates ------------------------------------------

    def test_recipe_gate_true_false_targets(self):
        true_targets, false_targets = _branch_targets(build_plan(CONFIG), "gate")
        self.assertEqual(true_targets, ["consume"])
        self.assertEqual(false_targets, ["short"])
        self.assertEqual(len(true_targets) + len(false_targets), 2)

    def test_terminal_gate_true_false_targets(self):
        true_targets, false_targets = _branch_targets(build_plan(CONFIG), "ter_gate")
        self.assertEqual(true_targets, ["win"])
        self.assertEqual(false_targets, ["keep"])
        self.assertEqual(len(true_targets) + len(false_targets), 2)

    def test_terminal_branch_edge_shapes(self):
        plan = build_plan(CONFIG)
        win_edge = next(e for e in plan.edges if e.src == "ter_gate" and e.dst == "win")
        self.assertEqual((win_edge.src_kind, win_edge.src_index), (EXEC_OUTPUT, 0))  # 是
        self.assertEqual((win_edge.dst_kind, win_edge.dst_index), (EXEC_INPUT, 0))
        keep_edge = next(e for e in plan.edges if e.src == "ter_gate" and e.dst == "keep")
        self.assertEqual((keep_edge.src_kind, keep_edge.src_index), (EXEC_OUTPUT, 1))  # 否
        self.assertEqual((keep_edge.dst_kind, keep_edge.dst_index), (EXEC_INPUT, 0))

    def test_swapped_branch_outputs_are_detectable(self):
        # Negative control on the *assertions* (not on validate): reversing the
        # 双分支 outputs must change what the index-based helpers report.
        good = build_plan(CONFIG)
        broken = build(CONFIG).plan
        broken.edges = _swap_branch_outputs(broken, "ter_gate")

        self.assertEqual(_branch_targets(good, "ter_gate"), (["win"], ["keep"]))
        self.assertNotEqual(
            _branch_targets(good, "ter_gate"), _branch_targets(broken, "ter_gate")
        )
        self.assertEqual(_branch_targets(broken, "ter_gate"), (["keep"], ["win"]))

    # -- the terminal comparison reads the live wallet (691) ----------------

    def test_terminal_comparison_reads_691_not_a_constant(self):
        plan = build_plan(CONFIG)
        read = next(n for n in plan.nodes if n.alias == "ter_read")
        self.assertEqual(read.definition_id, 691)  # 获取背包货币数量

        cmp = next(n for n in plan.nodes if n.alias == "ter_cmp")
        self.assertEqual(cmp.definition_id, 233)   # 数值大于等于

        # Its left operand is wired from the 691 read, data output -> data input.
        left = next(
            e for e in plan.edges
            if e.dst == "ter_cmp" and e.dst_kind == DATA_INPUT and e.dst_index == 0
        )
        self.assertEqual(left.src, "ter_read")
        self.assertEqual((left.src_kind, left.src_index), (DATA_OUTPUT, 0))  # amount
        # ... and there is NO constant written into the left operand.
        self.assertNotIn(("ter_cmp", 0), _const_map(plan))

    def test_terminal_threshold_is_the_only_constant_on_the_comparison(self):
        consts = _const_map(build_plan(CONFIG))
        self.assertEqual(consts[("ter_cmp", 1)], CONFIG.target_coins)  # right operand
        cmp_consts = {p for (a, p) in consts if a == "ter_cmp"}
        self.assertEqual(cmp_consts, {1})

    def test_terminal_read_holder_comes_from_the_event(self):
        # holder must be the runtime entity off 684, never a constant.
        plan = build_plan(CONFIG)
        holder = next(
            e for e in plan.edges
            if e.dst == "ter_read" and e.dst_kind == DATA_INPUT and e.dst_index == 0
        )
        self.assertEqual(holder.src, "money_changed")
        self.assertEqual((holder.src_kind, holder.src_index), (DATA_OUTPUT, 0))  # holder
        self.assertNotIn(("ter_read", 0), _const_map(plan))

    def test_terminal_gate_is_triggered_by_the_wallet_change_event(self):
        plan = build_plan(CONFIG)
        exec_edge = next(
            e for e in plan.edges
            if e.src == "money_changed" and e.dst == "ter_gate"
        )
        self.assertEqual((exec_edge.src_kind, exec_edge.src_index), (EXEC_OUTPUT, 0))
        self.assertEqual((exec_edge.dst_kind, exec_edge.dst_index), (EXEC_INPUT, 0))
        cond = next(
            e for e in plan.edges
            if e.src == "ter_cmp" and e.dst == "ter_gate"
        )
        self.assertEqual((cond.src_kind, cond.src_index), (DATA_OUTPUT, 0))  # result
        self.assertEqual((cond.dst_kind, cond.dst_index), (DATA_INPUT, 0))

    def test_the_wallet_event_fans_out_to_feedback_and_terminal(self):
        plan = build_plan(CONFIG)
        sinks = sorted(
            e.dst for e in plan.edges
            if e.src == "money_changed" and e.src_kind == EXEC_OUTPUT
        )
        self.assertEqual(sinks, ["money_note", "ter_gate"])

    # -- texts and parameters ----------------------------------------------

    def test_terminal_texts_are_distinct_and_named(self):
        consts = _const_map(build_plan(CONFIG))
        self.assertEqual(consts[("win", 0)], TERMINAL_WIN_TEXT)    # "通关"
        self.assertEqual(consts[("keep", 0)], TERMINAL_KEEP_TEXT)  # "继续加油"
        self.assertEqual(consts[("money_note", 0)], FEEDBACK_TEXT)  # 反馈 unchanged
        self.assertNotEqual(TERMINAL_WIN_TEXT, TERMINAL_KEEP_TEXT)
        self.assertNotEqual(TERMINAL_WIN_TEXT, FEEDBACK_TEXT)

    def test_target_coins_defaults_and_is_parameterised(self):
        self.assertEqual(LoopConfig.__dataclass_fields__["target_coins"].default, 100)
        cfg = LoopConfig(
            currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
            food_id=CONFIG.food_id, target_coins=999,
        )
        self.assertEqual(_const_map(build_plan(cfg))[("ter_cmp", 1)], 999)

    def test_loop_body_config_is_inherited(self):
        # LoopConfig is a FarmFullConfig: the recipe knobs still bite.
        cfg = LoopConfig(
            currency_id=CONFIG.currency_id, crop_id=CONFIG.crop_id,
            food_id=CONFIG.food_id, recipe_cost=5, harvest_gain=3, target_coins=42,
        )
        consts = _const_map(build_plan(cfg))
        self.assertEqual(consts[("consume", 2)], -5)
        self.assertEqual(consts[("harvest", 2)], 3)
        self.assertEqual(consts[("ter_cmp", 1)], 42)

    def test_name_is_parameterised(self):
        plan = build_plan(CONFIG, name="MW_API_FARM_LOOP_ALT")
        self.assertEqual(plan.name, "MW_API_FARM_LOOP_ALT")

    def test_every_node_definition_is_a_real_contract_node(self):
        from tools.gameplan.contracts import default_store
        store = default_store()
        for node in build_plan(CONFIG).nodes:
            self.assertIn(node.definition_id, store, f"{node.alias} unknown")
            self.assertEqual(store.require(node.definition_id).graph_kind, 20000)


class TestNegativeControlsRaisePlanError(unittest.TestCase):
    """Deliberately broken variants must be *refused* by validate(), not slip through."""

    def test_good_plan_is_clean_first(self):
        # Every control below mutates this same good graph; prove it starts clean.
        graph = build(CONFIG)
        self.assertIsNone(graph.validate())

    def test_execution_output_index_off_the_branch_is_rejected(self):
        graph = build(CONFIG)
        # 双分支 (2) has execution outputs 0 and 1 only; index 5 does not exist.
        graph.plan.wire("ter_gate", EXEC_OUTPUT, 5, "win", EXEC_INPUT, 0)
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertIn("ter_gate", str(caught.exception))

    def test_duplicate_constant_on_one_pin_is_rejected(self):
        graph = build(CONFIG)
        # (ter_cmp, 1) is the right operand and is already set; setting it twice
        # is exactly the kind of silent overwrite validate() must catch.
        graph.plan.const("ter_cmp", 1, 5, "int")
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertIn("set twice", str(caught.exception))

    def test_unknown_slot_is_rejected(self):
        graph = build(CONFIG)
        # 数值大于等于's op pin (3:2) has no constant yet, so this isolates the
        # *slot* check rather than tripping the "set twice" rule.
        graph.plan.const("enough", 2, 0, "not_a_slot")
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertIn("not_a_slot", str(caught.exception))

    def test_unknown_definition_is_rejected(self):
        graph = build(CONFIG)
        graph.plan.add("ghost", 999999)
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertIn("ghost", str(caught.exception))


class TestCommittedGolden(unittest.TestCase):
    """The loop's shape is frozen: a drift is a visible committed diff."""

    def test_committed_snapshot_matches_a_fresh_build(self):
        for name, plan in golden_plans().items():
            with self.subTest(plan=name):
                report = golden.compare_file(plan, name, directory=golden.COMMITTED_DIR)
                self.assertTrue(
                    report.ok,
                    f"plan {name!r} drifted from tools/gameplan/golden/{name}.json:\n{report}",
                )

    def test_committed_file_is_canonical_bytes(self):
        plan = golden_plans()["farming_loop"]
        path = golden.COMMITTED_DIR / "farming_loop.json"
        self.assertEqual(path.read_text(encoding="utf-8"), golden.dumps(golden.freeze(plan)))
        self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_snapshot_records_the_terminal_nodes(self):
        data = golden.read_golden("farming_loop", directory=golden.COMMITTED_DIR)
        aliases = [n["alias"] for n in data["nodes"]]
        self.assertEqual(aliases, list(LOOP_BODY) + list(TERMINAL_NODES))

    def test_snapshot_nodes_are_all_zero_positioned(self):
        # The loop is a logic graph; no node has been laid out on the canvas.
        data = golden.read_golden("farming_loop", directory=golden.COMMITTED_DIR)
        for node in data["nodes"]:
            self.assertEqual((node["x"], node["y"]), (0, 0), node["alias"])


if __name__ == "__main__":
    unittest.main()
