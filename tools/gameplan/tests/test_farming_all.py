"""Offline tests for the canonical all-module demo graph (``farming_all``).

No bridge, no game, no editor.  What is proven here:

1. the graph **validates** against ``data/node-contracts`` and its node list is
   exactly the 21 nodes declared, in build order;
2. **every module M1–M5 is represented** — the plan's ``definitionId`` set
   intersects each module's own node table (M6 has no node half, so it is
   correctly absent);
3. **no event node is a flow target** (an event has no execution input);
4. the M4 **capacity gate** leg and the M5 **sell/pay** leg are wired as the
   module docstrings describe, not merely present;
5. **deliberate mutations raise ``PlanError``** (unknown ``definitionId``, an
   execution edge off a pin that does not exist, a constant with a bogus slot);
6. the committed golden ``tools/gameplan/golden/farming_all.json`` matches a
   fresh build exactly, and a drifted build's failure **names the exact alias**
   that changed (a negative control proves the message discriminates).

Negative controls throughout prove the assertions bite rather than pass on an
empty set — a graph with an event as a flow target is detected, and removing the
M4 nodes empties M4's coverage.
"""

import unittest

from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    default_store,
)
from tools.gameplan.demo.farming_all import (
    BAG_FULL_TEXT,
    EVENT_NODE_IDS,
    MODULE_NODE_IDS,
    FarmAllConfig,
    build,
    covered_modules,
    definition_ids,
    module_coverage,
    plan_of,
)
from tools.gameplan.golden import COMMITTED_DIR, compare, dumps, freeze, read_golden
from tools.gameplan.plan import ConstSpec, EdgeSpec, NodeSpec, PlanError

#: The canonical config the committed golden was frozen with (matches
#: ``golden._DEMO_IDS``).
CONFIG = FarmAllConfig(currency_id=1115684864, crop_id=1120000001, food_id=1120000002)

#: The exact build order of the 21 nodes: the 15-node ``farming_full`` body first
#: (收 → 合成 → 卖 → 反馈), then the M4 capacity leg, then the M5 product writer.
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
    ("bag_cap", 689),
    ("bag", 230),
    ("bag_gate", 2),
    ("bag_full", 1),
    ("grow", 685),
    ("list_crop", 709),
)

#: The counts a reader quotes; asserted as facts against both the fresh build and
#: the committed snapshot.
EXPECTED_NODE_COUNT = 21
EXPECTED_EDGE_COUNT = 25
EXPECTED_CONST_COUNT = 20

#: The golden snapshot this module guards.
GOLDEN_NAME = "farming_all"

#: The five modules this graph must exercise.  M6 is placement/terrain, not a
#: node graph, so it has no node table and is deliberately not in this list.
EXPRESSIBLE_MODULES = (
    "M1-interaction",
    "M2-currency",
    "M3-item",
    "M4-inventory",
    "M5-shop",
)


def _node_list(plan):
    return tuple((n.alias, n.definition_id) for n in plan.nodes)


def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _exec_targets(plan, src, src_index=0):
    return [
        e.dst for e in plan.edges
        if e.src == src and e.src_kind == EXEC_OUTPUT and e.src_index == src_index
    ]


def _holder_source(plan, alias):
    """The data edge that fills a node's ``holder`` input (port 0)."""
    return next(
        e for e in plan.edges
        if e.dst == alias and e.dst_kind == DATA_INPUT and e.dst_index == 0
    )


def _event_aliases(plan):
    """Aliases of nodes whose ``definitionId`` is an event entry point."""
    return [n.alias for n in plan.nodes if n.definition_id in EVENT_NODE_IDS]


def _event_flow_targets(plan):
    """Every edge that points *into* an event node (there must be none)."""
    events = set(_event_aliases(plan))
    return [(e.src, e.dst) for e in plan.edges if e.dst in events]


def _golden():
    return read_golden(GOLDEN_NAME, directory=COMMITTED_DIR)


def _diff_message(report):
    """Render a :class:`~tools.gameplan.golden.DiffReport`, alias-first."""
    lines = [f"farming_all drifted from {GOLDEN_NAME}.json:"]
    for change in report.changes:
        if change.alias is not None:
            lines.append(f"  NODE {change.alias!r}: {change.summary}")
        else:
            lines.append(f"  {change.summary}")
    return "\n".join(lines)


def _assert_matches(plan):
    report = compare(plan, _golden())
    if not report.ok:
        raise AssertionError(_diff_message(report))


class TestGraphShape(unittest.TestCase):
    def test_builds_and_validates(self):
        plan = plan_of(CONFIG)
        self.assertEqual(plan.name, "MW_API_FARM_ALL")
        self.assertEqual(plan.graph_kind, 20000)
        self.assertIsNone(plan.validate())  # idempotent; already validated

    def test_exact_node_list_in_order(self):
        got = _node_list(plan_of(CONFIG))
        self.assertEqual(got, EXPECTED_NODES)

    def test_counts(self):
        plan = plan_of(CONFIG)
        self.assertEqual(
            (len(plan.nodes), len(plan.edges), len(plan.consts)),
            (EXPECTED_NODE_COUNT, EXPECTED_EDGE_COUNT, EXPECTED_CONST_COUNT),
        )

    def test_every_node_is_a_real_server_contract_node(self):
        store = default_store()
        for node in plan_of(CONFIG).nodes:
            self.assertIn(node.definition_id, store, f"{node.alias} unknown")
            self.assertEqual(store.require(node.definition_id).graph_kind, 20000)

    def test_invalid_name_rejected(self):
        with self.assertRaises(PlanError):
            build(CONFIG, name="farm_all").validate()


class TestEveryModuleIsRepresented(unittest.TestCase):
    def test_definition_set_covers_each_module_table(self):
        plan = plan_of(CONFIG)
        present = definition_ids(plan)
        coverage = module_coverage(plan)
        for module in EXPRESSIBLE_MODULES:
            with self.subTest(module=module):
                self.assertTrue(
                    coverage[module],
                    f"{module} is not represented: none of "
                    f"{sorted(MODULE_NODE_IDS[module])} is in the plan",
                )
                # Cross-check the membership is a real intersection of the plan.
                self.assertEqual(coverage[module], present & MODULE_NODE_IDS[module])

    def test_covered_modules_is_exactly_the_five_node_modules(self):
        self.assertEqual(covered_modules(plan_of(CONFIG)), EXPRESSIBLE_MODULES)

    def test_no_other_module_is_represented(self):
        # The registry has exactly the five module tables; nothing else sneaks in.
        self.assertEqual(set(MODULE_NODE_IDS), set(EXPRESSIBLE_MODULES))

    def test_coverage_negative_control_m4_empties_without_its_nodes(self):
        # Removing the two M4 nodes from a copy must empty M4's coverage — proves
        # the coverage check is a real membership test, not a constant.
        plan = plan_of(CONFIG)
        plan.nodes[:] = [
            n for n in plan.nodes if n.definition_id not in MODULE_NODE_IDS["M4-inventory"]
        ]
        coverage = module_coverage(plan)
        self.assertEqual(coverage["M4-inventory"], frozenset())
        self.assertNotIn("M4-inventory", covered_modules(plan))
        # and the other four are untouched.
        for module in EXPRESSIBLE_MODULES:
            if module != "M4-inventory":
                self.assertTrue(coverage[module])


class TestNoEventNodeIsAFlowTarget(unittest.TestCase):
    def test_no_edge_points_into_an_event(self):
        plan = plan_of(CONFIG)
        self.assertEqual(_event_flow_targets(plan), [])

    def test_the_event_set_is_non_empty(self):
        # If the event set were empty the assertion above would pass vacuously.
        plan = plan_of(CONFIG)
        self.assertTrue(_event_aliases(plan))
        self.assertEqual(
            set(_event_aliases(plan)),
            {"plot_enter", "stall_enter", "crop_used", "sold", "money_changed"},
        )

    def test_negative_control_an_event_target_is_detected(self):
        # Forge an edge into the 684 event and prove the detector reports it.
        plan = plan_of(CONFIG)
        plan.edges.append(
            EdgeSpec("harvest", EXEC_OUTPUT, 0, "money_changed", EXEC_INPUT, 0)
        )
        targets = _event_flow_targets(plan)
        self.assertIn(("harvest", "money_changed"), targets)

    def test_event_nodes_have_no_execution_input_at_all(self):
        # The structural reason: every event role table declares no exec input.
        from tools.gameplan.nodes import ALL_NODE_TYPES

        for ntype in ALL_NODE_TYPES:
            if ntype.definition_id in EVENT_NODE_IDS:
                with self.subTest(node=ntype.label):
                    self.assertIsNone(ntype.exec_in)


class TestM4CapacityLeg(unittest.TestCase):
    """The capacity gate (689 → 230 → 2 → 1) and the grow primitive (685)."""

    def test_m4_nodes_present_in_order(self):
        plan = plan_of(CONFIG)
        got = [(n.alias, n.definition_id) for n in plan.nodes
               if n.definition_id in MODULE_NODE_IDS["M4-inventory"]]
        self.assertEqual(got, [("bag_cap", 689), ("grow", 685)])

    def test_capacity_feeds_the_comparison_left_operand(self):
        plan = plan_of(CONFIG)
        edge = next(e for e in plan.edges if e.src == "bag_cap" and e.dst == "bag")
        self.assertEqual((edge.src_kind, edge.dst_kind), (DATA_OUTPUT, DATA_INPUT))
        self.assertEqual((edge.src_index, edge.dst_index), (0, 0))  # capacity -> left
        self.assertEqual(_const_map(plan)[("bag", 1)], CONFIG.capacity_threshold)

    def test_comparison_result_gates_the_branch(self):
        plan = plan_of(CONFIG)
        edge = next(e for e in plan.edges if e.src == "bag" and e.dst == "bag_gate")
        self.assertEqual((edge.src_kind, edge.dst_kind), (DATA_OUTPUT, DATA_INPUT))
        self.assertEqual((edge.src_index, edge.dst_index), (0, 0))  # result -> condition

    def test_true_branch_prints_and_false_is_unwired(self):
        plan = plan_of(CONFIG)
        self.assertEqual(_exec_targets(plan, "bag_gate", 0), ["bag_full"])   # 是
        self.assertEqual(_exec_targets(plan, "bag_gate", 1), [])             # 否
        self.assertEqual(_const_map(plan)[("bag_full", 0)], BAG_FULL_TEXT)

    def test_grow_hangs_off_the_plot_enter_event(self):
        plan = plan_of(CONFIG)
        # exec: plot_enter ----then----> grow (fan-out alongside harvest)
        self.assertIn("grow", _exec_targets(plan, "plot_enter", 0))
        # holder comes from the event entity, never a constant.
        edge = _holder_source(plan, "grow")
        self.assertEqual(edge.src, "plot_enter")
        self.assertEqual((edge.src_kind, edge.src_index), (DATA_OUTPUT, 0))
        self.assertEqual(_const_map(plan)[("grow", 1)], CONFIG.grow_amount)


class TestM5SellPayAndProductLeg(unittest.TestCase):
    """The sell/pay leg (701 → 688) and the bag-store product writer (709)."""

    def test_sale_event_reports_completion_without_an_extra_wallet_change(self):
        plan = plan_of(CONFIG)
        self.assertEqual(_exec_targets(plan, "sold", 0), ["sold_note"])
        self.assertNotIn(688, [n.definition_id for n in plan.nodes])
        self.assertEqual(_const_map(plan)[("sold_note", 0)], "商店交易完成")

    def test_product_writer_lists_the_crop_on_the_bag_store(self):
        plan = plan_of(CONFIG)
        # exec: stall_enter ----then----> list_crop
        self.assertIn("list_crop", _exec_targets(plan, "stall_enter", 0))
        edge = _holder_source(plan, "list_crop")
        self.assertEqual(edge.src, "stall_enter")
        self.assertEqual((edge.src_kind, edge.src_index), (DATA_OUTPUT, 2))  # trigger
        consts = _const_map(plan)
        self.assertEqual(consts[("list_crop", 1)], 0)                # shop_index
        self.assertEqual(consts[("list_crop", 2)], CONFIG.crop_id)   # item
        self.assertEqual(consts[("list_crop", 4)], CONFIG.sale_tab)  # tab_index

    def test_product_writer_leaves_the_dict_pin_unwired(self):
        # The 出售货币字典 (3:3, type 27) pin is deliberately unconnected — the
        # bag-store price is anchored to the item template.  No dict constant.
        plan = plan_of(CONFIG)
        self.assertEqual(
            [c for c in plan.consts if c.alias == "list_crop" and c.port_index == 3],
            [],
        )
        self.assertEqual(
            [e for e in plan.edges if e.dst == "list_crop" and e.dst_index == 3],
            [],
        )


class TestDeliberateMutationsRaisePlanError(unittest.TestCase):
    """At least two independent mutations must be rejected by ``validate()``."""

    def test_a_clean_build_is_not_rejected(self):
        self.assertIsNone(build(CONFIG).validate())

    def test_duplicate_alias_is_rejected(self):
        graph = build(CONFIG)
        graph.plan.add("grow", 685)  # `grow` already exists
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertTrue(
            any("duplicate node alias" in p for p in caught.exception.problems),
            caught.exception.problems,
        )

    def test_illegal_edge_kind_pair_is_rejected(self):
        # An execution output wired into a *data* input is neither (2->1) nor (4->3).
        graph = build(CONFIG)
        graph.plan.wire("harvest", EXEC_OUTPUT, 0, "bake", DATA_INPUT, 0)
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertTrue(
            any("kind pair" in p for p in caught.exception.problems),
            caught.exception.problems,
        )

    def test_execution_edge_off_a_missing_pin_is_rejected(self):
        graph = build(CONFIG)
        # 双分支 (2) has execution outputs only at index 0/1; index 5 does not exist.
        graph.plan.wire("gate", EXEC_OUTPUT, 5, "short", EXEC_INPUT, 0)
        with self.assertRaises(PlanError):
            graph.validate()

    def test_constant_with_a_bogus_slot_is_rejected(self):
        graph = build(CONFIG)
        # `grow`'s holder (3:0) is a real input with no constant yet; a "dict" slot
        # is not one of the writable slots.
        graph.plan.consts.append(ConstSpec(alias="grow", port_index=0, value=1, slot="dict"))
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertTrue(any("slot" in p for p in caught.exception.problems))

    def test_data_type_mismatch_is_rejected(self):
        # Wire the comparison's bool result into 打开商店's int 商店序号 input: two
        # concrete ends of different serverParamType — a mismatch validate() names.
        graph = build(CONFIG)
        graph.plan.wire("bag", DATA_OUTPUT, 0, "open_shop", DATA_INPUT, 2)  # bool -> int
        with self.assertRaises(PlanError) as caught:
            graph.validate()
        self.assertTrue(
            any("mismatch" in p for p in caught.exception.problems),
            caught.exception.problems,
        )


class TestGoldenSnapshot(unittest.TestCase):
    def test_file_holds_exactly_the_expected_graph(self):
        data = _golden()
        self.assertEqual(data["name"], "MW_API_FARM_ALL")
        self.assertEqual(data["graphKind"], 20000)
        self.assertEqual(len(data["nodes"]), EXPECTED_NODE_COUNT)
        self.assertEqual(len(data["edges"]), EXPECTED_EDGE_COUNT)
        self.assertEqual(len(data["consts"]), EXPECTED_CONST_COUNT)

    def test_live_plan_matches_the_committed_golden(self):
        _assert_matches(plan_of(CONFIG))

    def test_compare_reports_no_changes(self):
        report = compare(plan_of(CONFIG), _golden())
        self.assertTrue(report.ok, _diff_message(report))
        self.assertEqual(report.changes, ())

    def test_committed_bytes_are_the_canonical_serialisation(self):
        text = (COMMITTED_DIR / f"{GOLDEN_NAME}.json").read_text(encoding="utf-8")
        self.assertEqual(text, dumps(_golden()))
        self.assertTrue(text.endswith("\n"))

    def test_golden_plans_helper_matches_the_committed_snapshot(self):
        from tools.gameplan.demo.farming_all import golden_plans

        self.assertEqual(freeze(golden_plans()["farming_all"]), _golden())


class TestDriftNamesTheExactAlias(unittest.TestCase):
    """Negative control: a mutated build must fail, naming the exact node alias."""

    @staticmethod
    def _replace_node(plan, alias, *, definition_id=None):
        for i, node in enumerate(plan.nodes):
            if node.alias == alias:
                plan.nodes[i] = NodeSpec(
                    alias=node.alias,
                    definition_id=node.definition_id if definition_id is None else definition_id,
                    x=node.x,
                    y=node.y,
                )
                return
        raise KeyError(alias)

    def test_retyped_node_names_the_alias(self):
        plan = plan_of(CONFIG)
        self._replace_node(plan, "bag_gate", definition_id=999)  # 双分支 2 -> 999
        with self.assertRaises(AssertionError) as caught:
            _assert_matches(plan)
        message = str(caught.exception)
        self.assertIn("bag_gate", message)
        self.assertIn("999", message)
        change = next(
            c for c in compare(plan, _golden()).changes if c.kind == "node_definition_changed"
        )
        self.assertEqual(change.alias, "bag_gate")
        self.assertEqual(change.was_definition_id, 2)

    def test_removed_node_names_the_alias(self):
        plan = plan_of(CONFIG)
        plan.nodes[:] = [n for n in plan.nodes if n.alias != "list_crop"]
        with self.assertRaises(AssertionError) as caught:
            _assert_matches(plan)
        self.assertIn("list_crop", str(caught.exception))

    def test_added_node_names_the_alias(self):
        plan = plan_of(CONFIG)
        plan.nodes.append(NodeSpec(alias="extra_print", definition_id=1))
        with self.assertRaises(AssertionError) as caught:
            _assert_matches(plan)
        self.assertIn("extra_print", str(caught.exception))

    def test_an_identical_plan_is_ok(self):
        self.assertTrue(compare(plan_of(CONFIG), _golden()).ok)


if __name__ == "__main__":
    unittest.main()
