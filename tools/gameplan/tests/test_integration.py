"""Offline integration test: ONE server graph that runs all six module fragments.

Where ``test_modules`` checks each fragment in isolation and ``test_farming_full``
checks one realistic assembly, this test is the *whole-part* contract: a single
server graph (kind ``20000``) that exercises **every** public helper of the five
fragments (M1..M5), in a realistic order, and that actually ``validate()``s.

Realistic order (收 → 合成 → 卖 → 反馈 → 界面 → 容量 → 覆盖), and the named legs:

1. ``进入碰撞触发器时`` (92) fans out **three execution edges** — the one event
   drives three modules at once:
     * ``增加背包道具数量`` (686) — M3 收作物,
     * ``增加背包货币数量`` (688) — M2 收钱,
     * the **M4 leg** ``获取背包容量`` (689) → ``数值小于`` (230) → ``双分支`` (2)
       → ``打印字符串`` (1) ``"快满了"``.
   The M4 branch hangs off the *same* 92 execution output (index 0, ``then``); it
   is a fan-out, not a steal — the M3/M2 edges stay exactly where they were.
2. ``背包内道具被使用时`` (733) → ``获取背包道具数量`` (690) → ``数值大于等于`` (233)
   → ``双分支`` (2): **真** consumes (686, ``-2``) *then* bakes (686, ``+1``);
   **假** prints (1).
3. ``进入碰撞触发器时`` (92, a second one) → ``打开商店`` (702) (M1+M5), plus
   ``向背包商店出售表中新增商品`` (709) (M5 上架).
4. ``商店出售背包物品时`` (701) → ``增加背包货币数量`` (688) (M5+M2 结账).
5. ``背包货币数量变化时`` (684) → ``打印字符串`` (1) (M2 反馈).
6. ``界面控件组触发时`` (316) → ``打印字符串`` (1) (M1 界面腿).

The remaining helpers (``proximity_leave``/``floating_page_triggered``;
``currency.read``; ``item.on_added``/``on_lost``/``on_changed``;
``inventory.grow``/``all_items``/``all_currencies``;
``shop.close``/``on_sold_bag_item``/``on_shop_bought``) are exercised by a
coverage tail — every helper must appear at least once.

The test asserts the node count, that ``validate()`` passes, that the M1..M5
definition-ids cover the module tables, that the 92 event output fans out to
*exactly three* named targets, that every ``双分支`` TRUE output (execution output
index 0) goes where it was wired, and that no *event* node is used as a flow
**target** (they have no execution input).  Three deliberate breakages then prove
``validate()`` actually rejects a bad graph.

Run::

    python -B -m unittest tools.gameplan.tests.test_integration
"""

from __future__ import annotations

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
from tools.gameplan.modules import currency as m2
from tools.gameplan.modules import interaction as m1
from tools.gameplan.modules import inventory as m4
from tools.gameplan.modules import item as m3
from tools.gameplan.modules import shop as m5
from tools.gameplan.plan import PlanError
from tools.gameplan.tests.test_modules import MODULE_NODE_TYPES

# ---------------------------------------------------------------------------
# Parameters the scene supplies (editor assets this project cannot create).
# ---------------------------------------------------------------------------
DEFAULT_NAME = "MW_API_test_integration"
CROP_ID = 1120000001      # 作物道具配置ID (type 20)
FOOD_ID = 1120000002      # 加工食物道具配置ID (type 20)
CURRENCY_ID = 1115684864  # 货币配置ID (type 20)
ITEM_SLOT = "int"         # `--slot` for a configID (see paramtypes.CONFIG_ID_SLOT)
CURRENCY_SLOT = "int"
RECIPE_COST = 2           # crops consumed per cook (686 delta = -2)
CAPACITY_WARN = 20        # 230 right operand
PRINT = N.PRINT           # 1 打印字符串

#: The five modules in their canonical M-number order, keyed to the node table in
#: :mod:`tools.gameplan.tests.test_modules`.  ``MODULE_NODE_TYPES`` is the
#: authoritative "which definitionIds is this module allowed to place" table, so
#: the coverage assertion below re-uses it rather than re-spelling it here.
MODULE_TABLE_BY_MNUMBER = {
    "M1": "interaction",
    "M2": "currency",
    "M3": "item",
    "M4": "inventory",
    "M5": "shop",
}

#: Every public helper across M1..M5 that this graph must exercise at least once.
EXPECTED_HELPERS = frozenset({
    "interaction.proximity_enter",
    "interaction.proximity_leave",
    "interaction.ui_control_triggered",
    "interaction.floating_page_triggered",
    "currency.grant",
    "currency.read",
    "currency.on_changed",
    "item.grant",
    "item.read",
    "item.on_added",
    "item.on_lost",
    "item.on_changed",
    "item.on_used",
    "inventory.capacity",
    "inventory.grow",
    "inventory.all_items",
    "inventory.all_currencies",
    "shop.open_",
    "shop.close",
    "shop.on_sold_bag_item",
    "shop.on_shop_bought",
    "shop.list_item_for_sale",
    "shop.on_bag_item_sold",
})

#: The exact nodes, in placement order.
EXPECTED_NODES = (
    ("plot_enter", 92),      # 1  进入碰撞触发器时 (M1)
    ("harvest", 686),        # 2  增加背包道具数量 (M3)  +1 crop
    ("bonus", 688),          # 3  增加背包货币数量 (M2)  +5 coin
    ("capacity", 689),       # 4  获取背包容量 (M4)  — the M4 leg, same 92 event
    ("near_full", 230),      # 5  数值小于 (M4 leg)
    ("cap_gate", 2),         # 6  双分支 (M4 leg)
    ("full_note", 1),        # 7  打印字符串 (M4 leg)  "快满了"
    ("crop_used", 733),      # 8  背包内道具被使用时 (M3)
    ("crop_count", 690),     # 9  获取背包道具数量 (M3)
    ("enough", 233),         # 10 数值大于等于
    ("gate", 2),             # 11 双分支
    ("consume", 686),        # 12 增加背包道具数量 (M3)  -2 crop
    ("bake", 686),           # 13 增加背包道具数量 (M3)  +1 food
    ("short", 1),            # 14 打印字符串
    ("stall_enter", 92),     # 15 进入碰撞触发器时 (M1)
    ("open_shop", 702),      # 16 打开商店 (M5)
    ("list_crop", 709),      # 17 向背包商店出售表中新增商品 (M5)
    ("sold", 701),           # 18 商店出售背包物品时 (M5)
    ("sold_note", 1),       # 19 增加背包货币数量 (M2)
    ("money_changed", 684),  # 20 背包货币数量变化时 (M2)
    ("money_note", 1),       # 21 打印字符串
    ("ui_panel", 316),       # 22 界面控件组触发时 (M1)
    ("ui_note", 1),          # 23 打印字符串 (M1 界面腿)
    ("leave", 91),           # 24 离开碰撞触发器时 (M1)
    ("leave_note", 1),       # 25 打印字符串
    ("close_shop", 703),     # 26 关闭商店 (M5)
    ("page", 826),           # 27 悬浮交互页操作触发时 (M1)
    ("page_note", 1),        # 28 打印字符串
    ("grow", 685),           # 29 增加背包最大容量 (M4)
    ("pickup", 681),         # 30 背包道具新增时 (M3)
    ("pickup_note", 1),      # 31 打印字符串
    ("drop", 682),           # 32 背包道具失去时 (M3)
    ("drop_note", 1),        # 33 打印字符串
    ("stock", 683),          # 34 背包道具数量变化时 (M3)
    ("stock_note", 1),       # 35 打印字符串
    ("item_scan", 721),      # 36 获取背包所有基础道具 (M4)
    ("cur_scan", 722),       # 37 获取背包所有货币 (M4)
    ("wallet", 691),         # 38 获取背包货币数量 (M2)
    ("sold_evt", 701),       # 39 商店出售背包物品时 (M5, event-only)
    ("bought", 705),         # 40 商店收购道具时 (M5)
)
EXPECTED_NODE_COUNT = len(EXPECTED_NODES)

#: The M4 leg head — the branch node the plot-enter event drives as its third
#: execution fan-out.
M4_BRANCH = "cap_gate"

#: The three execution targets off the single 92 ``then`` output, in wiring order.
PLOT_ENTER_EXEC_TARGETS = ("harvest", "bonus", M4_BRANCH)

#: The event entry points.  Each is an event node, so it must never be a flow
#: *target* (the contract gives it no execution input).
EVENT_ALIASES = frozenset({
    "plot_enter", "crop_used", "stall_enter", "sold", "money_changed",
    "ui_panel", "leave", "page", "pickup", "drop", "stock", "sold_evt",
    "bought",
})


def build(name: str = DEFAULT_NAME):
    """Build the whole integration graph.  Returns ``(graph, used)``.

    ``used`` maps ``"<module>.<helper>"`` -> the alias(es) that helper placed,
    so a test can prove every helper was actually *called*, not merely that its
    definitionId happens to be present for some other reason.
    """
    g = Graph(name)
    used: dict[str, list[str]] = {}

    def note(helper: str, alias: str) -> None:
        used.setdefault(helper, []).append(alias)

    # --- 1. 收：走进地块 → 扇出三条执行 ---
    # One 92 event, three modules: M3 收作物, M2 加钱, M4 容量告警.
    plot_enter = m1.proximity_enter(g, "plot_enter")
    note("interaction.proximity_enter", "plot_enter")
    m3.grant(
        g, plot_enter, holder=(plot_enter, "entrant"), item_id=CROP_ID,
        count=1, item_slot=ITEM_SLOT, alias="harvest",
    )
    note("item.grant", "harvest")
    m2.grant(
        g, plot_enter, holder=(plot_enter, "entrant"), currency_id=CURRENCY_ID,
        amount=5, currency_slot=CURRENCY_SLOT, alias="bonus",
    )
    note("currency.grant", "bonus")

    # --- 1b. M4 支线：同一 plot-enter 事件的第三条扇出 —— 容量告警 ---
    # 689 获取背包容量 → 230 数值小于 → 双分支 2 → 真 prints "快满了".
    capacity = m4.capacity(g, holder=(plot_enter, "entrant"), alias="capacity")
    note("inventory.capacity", "capacity")

    near_full = g.place(N.LT, "near_full")              # 数值小于 (230)
    near_full.data_from(capacity, "capacity", "left")
    near_full.const("right", CAPACITY_WARN, "int")

    cap_gate = g.place(N.BRANCH, M4_BRANCH)             # 双分支 (2)
    plot_enter.flow_to(cap_gate)                        # the SAME 92 `then` output
    cap_gate.data_from(near_full, "result", "condition")

    full_note = g.place(PRINT, "full_note")             # 打印字符串 (1)
    cap_gate.flow_to(full_note, "true")
    full_note.const("text", "快满了", "string")

    # --- 2. 合成：用作物 → 查 690 → 比较 233 → 双分支 2 ---
    crop_used = m3.on_used(g, "crop_used")
    note("item.on_used", "crop_used")
    crop_count = m3.read(
        g, holder=(crop_used, "holder"), item_id=CROP_ID,
        item_slot=ITEM_SLOT, alias="crop_count",
    )
    note("item.read", "crop_count")

    enough = g.place(N.GE, "enough")                    # 数值大于等于 (233)
    enough.data_from(crop_count, "amount", "left")
    enough.const("right", RECIPE_COST, "int")

    gate = g.place(N.BRANCH, "gate")                    # 双分支 (2)
    crop_used.flow_to(gate)
    gate.data_from(enough, "result", "condition")

    consume = m3.grant(
        g, gate, holder=(crop_used, "holder"), item_id=CROP_ID,
        count=-RECIPE_COST, item_slot=ITEM_SLOT, alias="consume", from_role="true",
    )
    note("item.grant", "consume")
    bake = m3.grant(
        g, consume, holder=(crop_used, "holder"), item_id=FOOD_ID,
        count=1, item_slot=ITEM_SLOT, alias="bake",
    )
    note("item.grant", "bake")

    short = g.place(PRINT, "short")                     # 打印字符串 (1)
    gate.flow_to(short, "false")
    short.const("text", "材料不足", "string")

    # --- 3. 卖：走进摊位 → 打开商店 702 + 上架 709 ---
    stall_enter = m1.proximity_enter(g, "stall_enter")
    note("interaction.proximity_enter", "stall_enter")
    m5.open_(
        g, stall_enter, player=(stall_enter, "entrant"),
        shop_owner=(stall_enter, "trigger"), shop_index=0, alias="open_shop",
    )
    note("shop.open_", "open_shop")
    m5.list_item_for_sale(
        g, stall_enter, shop_owner=(stall_enter, "trigger"), shop_index=0,
        item_id=CROP_ID, item_slot=ITEM_SLOT, alias="list_crop",
    )
    note("shop.list_item_for_sale", "list_crop")

    # --- 4. Observe the already settled native transaction. ---
    sold = m5.on_bag_item_sold(g, alias="sold")
    note("shop.on_bag_item_sold", "sold")
    sold_note = g.place(PRINT, "sold_note")
    sold.flow_to(sold_note)
    sold_note.const("text", "商店交易完成", "string")

    # --- 5. 反馈：684 货币变化 → 1 打印 ---
    money_changed = m2.on_changed(g, "money_changed")
    note("currency.on_changed", "money_changed")
    money_note = g.place(PRINT, "money_note")
    money_changed.flow_to(money_note)
    money_note.const("text", "货币发生变化", "string")

    # --- 6. 界面：316 界面控件 → 1 打印 ---
    ui_panel = m1.ui_control_triggered(g, "ui_panel")
    note("interaction.ui_control_triggered", "ui_panel")
    ui_note = g.place(PRINT, "ui_note")
    ui_panel.flow_to(ui_note)
    ui_note.const("text", "界面控件触发", "string")

    # --- 7. 覆盖面：每个剩余 helper 至少出现一次 ---
    leave = m1.proximity_leave(g, "leave")              # 91
    note("interaction.proximity_leave", "leave")
    leave_note = g.place(PRINT, "leave_note")
    leave.flow_to(leave_note)
    leave_note.const("text", "离开地块", "string")
    m5.close(g, leave, player=(leave, "leaver"), alias="close_shop")   # 703
    note("shop.close", "close_shop")

    page = m1.floating_page_triggered(g, "page")        # 826
    note("interaction.floating_page_triggered", "page")
    page_note = g.place(PRINT, "page_note")
    page.flow_to(page_note)
    page_note.const("text", "悬浮页操作", "string")
    m4.grow(g, page, holder=(page, "player"), amount=10, alias="grow")  # 685
    note("inventory.grow", "grow")

    pickup = m3.on_added(g, "pickup")                   # 681
    note("item.on_added", "pickup")
    pickup_note = g.place(PRINT, "pickup_note")
    pickup.flow_to(pickup_note)
    pickup_note.const("text", "获得道具", "string")

    drop = m3.on_lost(g, "drop")                        # 682
    note("item.on_lost", "drop")
    drop_note = g.place(PRINT, "drop_note")
    drop.flow_to(drop_note)
    drop_note.const("text", "失去道具", "string")

    stock = m3.on_changed(g, "stock")                   # 683
    note("item.on_changed", "stock")
    stock_note = g.place(PRINT, "stock_note")
    stock.flow_to(stock_note)
    stock_note.const("text", "道具数量变化", "string")

    m4.all_items(g, holder=(money_changed, "holder"), alias="item_scan")       # 721
    note("inventory.all_items", "item_scan")
    m4.all_currencies(g, holder=(money_changed, "holder"), alias="cur_scan")   # 722
    note("inventory.all_currencies", "cur_scan")
    m2.read(
        g, holder=(money_changed, "holder"), currency_id=CURRENCY_ID,
        currency_slot=CURRENCY_SLOT, alias="wallet",
    )                                                                          # 691
    note("currency.read", "wallet")

    m5.on_sold_bag_item(g, "sold_evt")                  # 701 (event-only)
    note("shop.on_sold_bag_item", "sold_evt")
    m5.on_shop_bought(g, "bought")                      # 705
    note("shop.on_shop_bought", "bought")

    return g, used


def build_plan(name: str = DEFAULT_NAME):
    """Build and validate the integration graph, returning the plan + the coverage map."""
    graph, used = build(name)
    graph.validate()
    return graph.plan, used


# ---------------------------------------------------------------------------
# plan-inspection helpers (pure reads)
# ---------------------------------------------------------------------------
def _nodes_with_id(plan, definition_id):
    return [n for n in plan.nodes if n.definition_id == definition_id]


def _const_map(plan):
    return {(c.alias, c.port_index): c.value for c in plan.consts}


def _exec_targets(plan, src_alias, src_index):
    """Aliases reached from ``src_alias``'s execution output ``src_index``."""
    return [
        e.dst for e in plan.edges
        if e.src == src_alias
        and e.src_kind == EXEC_OUTPUT
        and e.src_index == src_index
    ]


def _exec_out_edges(plan, src_alias):
    """Every execution edge leaving ``src_alias`` (any output index)."""
    return [
        e for e in plan.edges
        if e.src == src_alias and e.src_kind == EXEC_OUTPUT
    ]


def _exec_in_edges(plan, dst_alias):
    """Every execution edge landing on ``dst_alias`` (any driver)."""
    return [
        e for e in plan.edges
        if e.dst == dst_alias and e.dst_kind == EXEC_INPUT
    ]


def _has_edge(plan, src, src_kind, src_index, dst, dst_kind, dst_index):
    return any(
        e.src == src and e.src_kind == src_kind and e.src_index == src_index
        and e.dst == dst and e.dst_kind == dst_kind and e.dst_index == dst_index
        for e in plan.edges
    )


def _holder_source(plan, alias):
    """The data edge that fills a node's ``holder`` input (port 0)."""
    return next(
        e for e in plan.edges
        if e.dst == alias and e.dst_kind == DATA_INPUT and e.dst_index == 0
    )


# ---------------------------------------------------------------------------
# The plan itself
# ---------------------------------------------------------------------------
class TestIntegrationGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.used = build_plan()

    def test_validates_and_is_a_server_graph(self):
        self.assertIsNone(self.plan.validate())   # idempotent; build_plan already ran it
        self.assertEqual(self.plan.graph_kind, 20000)
        self.assertEqual(self.plan.name, DEFAULT_NAME)

    def test_node_count(self):
        self.assertEqual(len(self.plan.nodes), EXPECTED_NODE_COUNT)
        self.assertEqual(EXPECTED_NODE_COUNT, 40)

    def test_exact_node_list_in_order(self):
        got = tuple((n.alias, n.definition_id) for n in self.plan.nodes)
        self.assertEqual(got, EXPECTED_NODES)

    def test_every_definition_is_a_real_contract_node(self):
        store = default_store()
        for node in self.plan.nodes:
            with self.subTest(alias=node.alias):
                self.assertIn(node.definition_id, store)
                self.assertEqual(
                    store.require(node.definition_id).graph_kind, 20000
                )

    # -- every module helper is exercised -------------------------------------

    def test_every_module_helper_is_exercised(self):
        self.assertEqual(set(self.used), set(EXPECTED_HELPERS))
        nodes = {n.alias for n in self.plan.nodes}
        for helper, aliases in self.used.items():
            with self.subTest(helper=helper):
                self.assertTrue(aliases, f"{helper} recorded no alias")
                for alias in aliases:
                    self.assertIn(alias, nodes, f"{helper} -> {alias} not placed")

    # -- every module TABLE is covered by the definition-id set ---------------

    def test_definition_id_set_covers_every_module_table(self):
        # M1..M5 must each appear at least once: every definitionId in that
        # module's node table (test_modules.MODULE_NODE_TYPES) is placed.
        self.assertEqual(set(MODULE_TABLE_BY_MNUMBER), {"M1", "M2", "M3", "M4", "M5"})
        used = {n.definition_id for n in self.plan.nodes}
        for mnumber, table_key in MODULE_TABLE_BY_MNUMBER.items():
            table = MODULE_NODE_TYPES[table_key]
            ids = [t.definition_id for t in table]
            with self.subTest(module=mnumber, table=table_key):
                self.assertTrue(table, f"{table_key} node table is empty")
                self.assertEqual(
                    sorted(i for i in ids if i not in used), [],
                    f"{mnumber} ({table_key}) legs missing from the graph",
                )

    def test_the_m4_leg_is_present_and_driven_by_the_m4_module(self):
        # The leg is exactly 689 -> 230 -> 2 -> 1, and 689/721/722/685 are the M4
        # module's whole table (so the M4 module is genuinely exercised).
        by_alias = {n.alias: n.definition_id for n in self.plan.nodes}
        self.assertEqual(
            [by_alias[a] for a in ("capacity", "near_full", M4_BRANCH, "full_note")],
            [689, 230, 2, 1],
        )
        m4_ids = {t.definition_id for t in MODULE_NODE_TYPES["inventory"]}
        placed = {n.definition_id for n in self.plan.nodes}
        self.assertTrue(m4_ids <= placed, m4_ids - placed)

    # -- leg 1: one event, three execution fan-outs ---------------------------

    def test_plot_enter_fans_out_to_gather_coin_and_the_m4_branch(self):
        # 92 has exactly ONE execution output (``then``, index 0).
        store = default_store()
        exec_outs = [
            p.index for p in store.require(N.PROXIMITY_ENTER.definition_id).ports
            if p.kind == EXEC_OUTPUT
        ]
        self.assertEqual(exec_outs, [0])

        # Exactly three execution edges leave that single output, in wiring order.
        edges = _exec_out_edges(self.plan, "plot_enter")
        self.assertEqual(len(edges), 3)
        self.assertEqual(
            [e.dst for e in edges], list(PLOT_ENTER_EXEC_TARGETS)
        )
        for e in edges:
            with self.subTest(dst=e.dst):
                self.assertEqual(e.src_index, 0)     # the one `then` output
                self.assertEqual(e.dst_kind, EXEC_INPUT)
                self.assertEqual(e.dst_index, 0)

        # The M4 branch did NOT steal the M1/M3 legs: both pre-existing edges
        # are still present, unchanged, plus the new one.
        self.assertTrue(
            _has_edge(self.plan, "plot_enter", EXEC_OUTPUT, 0, "harvest", EXEC_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "plot_enter", EXEC_OUTPUT, 0, "bonus", EXEC_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(
                self.plan, "plot_enter", EXEC_OUTPUT, 0, M4_BRANCH, EXEC_INPUT, 0
            )
        )
        # The crop grant carries +1 of the crop; the coin grant carries +5.
        consts = _const_map(self.plan)
        self.assertEqual(consts[("harvest", 1)], CROP_ID)   # 686 item (3:1)
        self.assertEqual(consts[("harvest", 2)], 1)         # 686 delta (3:2)
        self.assertEqual(consts[("bonus", 1)], CURRENCY_ID) # 688 currency (3:1)
        self.assertEqual(consts[("bonus", 2)], 5)           # 688 delta (3:2)

    def test_m4_branch_has_exactly_one_execution_driver_the_plot_event(self):
        drivers = _exec_in_edges(self.plan, M4_BRANCH)
        self.assertEqual(len(drivers), 1)
        (driver,) = drivers
        self.assertEqual(
            (driver.src, driver.src_kind, driver.src_index, driver.dst_index),
            ("plot_enter", EXEC_OUTPUT, 0, 0),
        )
        # The old UI-button driver is gone; 316 drives its own print instead.
        self.assertEqual(_exec_targets(self.plan, "ui_panel", 0), ["ui_note"])

    def test_m4_chain_wiring(self):
        # 92.entrant -> 689.holder; 689.capacity -> 230.left;
        # 230.result -> 双分支.condition; 双分支.真 -> 1 打印.
        self.assertTrue(
            _has_edge(self.plan, "plot_enter", DATA_OUTPUT, 0, "capacity", DATA_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "capacity", DATA_OUTPUT, 0, "near_full", DATA_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "near_full", DATA_OUTPUT, 0, M4_BRANCH, DATA_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, M4_BRANCH, EXEC_OUTPUT, 0, "full_note", EXEC_INPUT, 0)
        )
        consts = _const_map(self.plan)
        self.assertEqual(consts[("near_full", 1)], CAPACITY_WARN)   # 230 right
        self.assertEqual(consts[("full_note", 0)], "快满了")

    # -- leg 2: item-use → read → compare → branch ---------------------------

    def test_craft_chain_wiring(self):
        # 733 then -> 双分支; 690.amount -> 233.left; 233.result -> 双分支.condition
        self.assertTrue(
            _has_edge(self.plan, "crop_used", EXEC_OUTPUT, 0, "gate", EXEC_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "crop_count", DATA_OUTPUT, 0, "enough", DATA_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "enough", DATA_OUTPUT, 0, "gate", DATA_INPUT, 0)
        )
        # The comparison threshold and the consume/bake deltas.
        consts = _const_map(self.plan)
        self.assertEqual(consts[("enough", 1)], RECIPE_COST)
        self.assertEqual(consts[("consume", 2)], -RECIPE_COST)
        self.assertEqual(consts[("bake", 2)], 1)
        self.assertEqual(consts[("bake", 1)], FOOD_ID)
        # true consumes first, then bakes (686 --then--> 686).
        self.assertTrue(
            _has_edge(self.plan, "consume", EXEC_OUTPUT, 0, "bake", EXEC_INPUT, 0)
        )

    # -- leg 3/4/5/6 anchors -------------------------------------------------

    def test_shop_leg_wiring(self):
        self.assertTrue(
            _has_edge(self.plan, "stall_enter", EXEC_OUTPUT, 0, "open_shop", EXEC_INPUT, 0)
        )
        # player = entrant (0), shop_owner = trigger (2)
        self.assertTrue(
            _has_edge(self.plan, "stall_enter", DATA_OUTPUT, 0, "open_shop", DATA_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "stall_enter", DATA_OUTPUT, 2, "open_shop", DATA_INPUT, 1)
        )
        # The native event only emits a notification; the engine owns payment.
        self.assertTrue(
            _has_edge(self.plan, "sold", EXEC_OUTPUT, 0, "sold_note", EXEC_INPUT, 0)
        )
        payment_aliases = {n.alias for n in self.plan.nodes if n.definition_id == 688}
        self.assertEqual(payment_aliases, {"bonus"})
        self.assertFalse(any(e.src == "sold" and e.dst in payment_aliases for e in self.plan.edges))

    def test_feedback_and_ui_legs(self):
        self.assertTrue(
            _has_edge(self.plan, "money_changed", EXEC_OUTPUT, 0, "money_note", EXEC_INPUT, 0)
        )
        self.assertTrue(
            _has_edge(self.plan, "ui_panel", EXEC_OUTPUT, 0, "ui_note", EXEC_INPUT, 0)
        )
        consts = _const_map(self.plan)
        self.assertEqual(consts[("money_note", 0)], "货币发生变化")
        self.assertEqual(consts[("ui_note", 0)], "界面控件触发")

    def test_holder_entities_come_from_events(self):
        # Every 686/688/689 holder is a data edge off an event's entity output —
        # never a guessed constant.
        for alias in ("harvest", "bonus", "capacity", "consume", "bake"):
            edge = _holder_source(self.plan, alias)
            with self.subTest(alias=alias):
                self.assertEqual(edge.src_kind, DATA_OUTPUT)
                self.assertIn(edge.src, EVENT_ALIASES)
                self.assertEqual(edge.src_index, 0)

    # -- the two 双分支 TRUE outputs -----------------------------------------

    def test_branch_true_outputs_go_where_wired(self):
        # 双分支 TRUE is execution output index 0 (nodes.BRANCH).
        self.assertEqual(_exec_targets(self.plan, "gate", 0), ["consume"])
        self.assertEqual(_exec_targets(self.plan, M4_BRANCH, 0), ["full_note"])

    def test_branch_false_outputs_are_distinct(self):
        # Negative control: FALSE (index 1) must be a *different* target than
        # TRUE, otherwise the index-based assertions above prove nothing.
        self.assertEqual(_exec_targets(self.plan, "gate", 1), ["short"])
        self.assertEqual(_exec_targets(self.plan, M4_BRANCH, 1), [])
        self.assertNotEqual(
            _exec_targets(self.plan, "gate", 0), _exec_targets(self.plan, "gate", 1)
        )

    # -- event nodes are never flow targets ----------------------------------

    def test_no_event_node_is_a_flow_target(self):
        store = default_store()
        # 1) the named event aliases really are event nodes (no exec input).
        for alias in EVENT_ALIASES:
            node = next(n for n in self.plan.nodes if n.alias == alias)
            with self.subTest(alias=alias):
                self.assertEqual(
                    store.require(node.definition_id).exec_inputs, (),
                    f"{alias} was expected to have no execution input",
                )
        # 2) no execution edge lands on an event node.
        for edge in self.plan.edges:
            if edge.dst_kind == EXEC_INPUT:
                with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                    self.assertNotIn(edge.dst, EVENT_ALIASES)

    def test_no_node_without_an_exec_input_is_a_flow_target(self):
        # Stronger, contract-derived form of the rule above: *any* definition
        # with no execution input (events and pure queries) must be unwired as a
        # target.
        store = default_store()
        inputless = {
            n.alias for n in self.plan.nodes
            if not store.require(n.definition_id).exec_inputs
        }
        self.assertTrue(EVENT_ALIASES <= inputless)
        for edge in self.plan.edges:
            if edge.dst_kind == EXEC_INPUT:
                with self.subTest(edge=f"{edge.src}->{edge.dst}"):
                    self.assertNotIn(edge.dst, inputless)


# ---------------------------------------------------------------------------
# Negative controls: three different ways to break the graph must raise PlanError
# ---------------------------------------------------------------------------
class TestIntegrationRejectsBadGraphs(unittest.TestCase):
    def test_break_one_event_node_as_flow_target(self):
        # Way 1 (structural, target side): drive an execution edge *into* an
        # event node (92 has no execution input).  This is exactly what the
        # positive assertions forbid, so validate() must catch it.
        graph, _ = build()
        self.assertIsNone(graph.validate())          # the good plan is clean
        graph.plan.wire("harvest", EXEC_OUTPUT, 0, "plot_enter", EXEC_INPUT, 0)
        with self.assertRaises(PlanError) as ctx:
            graph.validate()
        self.assertTrue(
            any("no execution input" in p for p in ctx.exception.problems),
            ctx.exception.problems,
        )

    def test_break_two_data_type_mismatch(self):
        # Way 2 (type): feed the M4 leg's raw capacity (689, an int, type 3) into
        # the 双分支 condition pin (bool, type 4) — two concrete ends that
        # disagree.  This is the exact wiring the M4 leg's comparison node exists
        # to prevent.
        graph, _ = build()
        self.assertIsNone(graph.validate())
        graph.plan.wire(
            "capacity", DATA_OUTPUT, N.GET_BAG_CAPACITY.outs["capacity"],
            M4_BRANCH, DATA_INPUT, N.BRANCH.ins["condition"],
        )
        with self.assertRaises(PlanError) as ctx:
            graph.validate()
        self.assertTrue(
            any("data type mismatch" in p for p in ctx.exception.problems),
            ctx.exception.problems,
        )

    def test_break_three_execution_source_without_an_execution_output(self):
        # Way 3 (structural, source side): make the pure comparison node 230 the
        # *driver* of the M4 print.  A data-only node has no execution output, so
        # validate() must reject the edge — proving the "230 is data, 双分支 is
        # the flow node" split is load-bearing.
        graph, _ = build()
        self.assertIsNone(graph.validate())
        graph.plan.wire("near_full", EXEC_OUTPUT, 0, "full_note", EXEC_INPUT, 0)
        with self.assertRaises(PlanError) as ctx:
            graph.validate()
        self.assertTrue(
            any("has no execution output" in p for p in ctx.exception.problems),
            ctx.exception.problems,
        )


if __name__ == "__main__":
    unittest.main()
