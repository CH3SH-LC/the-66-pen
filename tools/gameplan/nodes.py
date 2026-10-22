"""Named handles for the official nodes we compose, with verified pin roles.

A :class:`NodeType` names the pins of one ``definitionId`` by *role* so module
code never writes a raw pin index.  ``tests/test_nodes.py`` re-derives every role
from ``data/node-contracts`` and fails if a declared index drifts from the
contract — so the table below is checked, not trusted.

Only server-side nodes (graph kind 20000) appear here: those are the ones the
editor proves it can place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .plan import ConstSpec, EdgeSpec, GraphPlan, NodeSpec
from .contracts import DATA_INPUT, DATA_OUTPUT, EXEC_INPUT, EXEC_OUTPUT


@dataclass(frozen=True)
class NodeType:
    definition_id: int
    label: str
    exec_in: int | None = None
    exec_outs: dict[str, int] = field(default_factory=dict)
    ins: dict[str, int] = field(default_factory=dict)
    outs: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Event nodes (only a single execution output; no execution input)
# ---------------------------------------------------------------------------
ON_CREATE = NodeType(71, "实体创建时", exec_outs={"then": 0}, outs={"entity": 0, "guid": 1})
SELF = NodeType(73, "获取自身实体", outs={"self": 0})
TIMER_TICK = NodeType(
    83,
    "定时器触发时",
    exec_outs={"then": 0},
    outs={"entity": 0, "guid": 1, "name": 2, "sequence_index": 3, "loop_count": 4, "context_guid": 5},
)
BAG_ITEM_ADDED = NodeType(
    681, "背包道具新增时", exec_outs={"then": 0}, outs={"holder": 0, "holder_guid": 1, "item": 2, "count": 3}
)
BAG_ITEM_LOST = NodeType(
    682, "背包道具失去时", exec_outs={"then": 0}, outs={"holder": 0, "holder_guid": 1, "item": 2, "count": 3}
)
BAG_ITEM_CHANGED = NodeType(
    683,
    "背包道具数量变化时",
    exec_outs={"then": 0},
    outs={"holder": 0, "holder_guid": 1, "item": 2, "before": 3, "after": 4, "reason": 5},
)
BAG_CURRENCY_CHANGED = NodeType(
    684,
    "背包货币数量变化时",
    exec_outs={"then": 0},
    outs={"holder": 0, "holder_guid": 1, "currency": 2, "delta": 3},
)
BAG_ITEM_USED = NodeType(
    733, "背包内道具被使用时", exec_outs={"then": 0}, outs={"holder": 0, "holder_guid": 1, "item": 2, "count": 3}
)
# Interaction entry points (M1).
PROXIMITY_ENTER = NodeType(
    92,
    "进入碰撞触发器时",
    exec_outs={"then": 0},
    outs={"entrant": 0, "entrant_guid": 1, "trigger": 2, "trigger_guid": 3, "trigger_index": 4},
)
PROXIMITY_LEAVE = NodeType(
    91,
    "离开碰撞触发器时",
    exec_outs={"then": 0},
    outs={"leaver": 0, "leaver_guid": 1, "trigger": 2, "trigger_guid": 3, "trigger_index": 4},
)
UI_CONTROL_TRIGGERED = NodeType(
    316, "界面控件组触发时", exec_outs={"then": 0}, outs={"entity": 0, "guid": 1, "group_combo_index": 2, "group_index": 3}
)
FLOATING_PAGE_TRIGGERED = NodeType(
    826,
    "悬浮交互页操作触发时",
    exec_outs={"then": 0},
    outs={"player": 0, "player_guid": 1, "page_index": 2, "item_index": 3, "list_index": 4, "list_selected": 5},
)
# Interaction *action* node (not an event).  90 is the one M1 node in the
# NODE-CENSUS-BY-MODULE interaction bucket whose inputs are ALL satisfiable by
# the entry entity plus literals (target entity type 1, trigger index int type 3,
# activate bool type 4) — no component and no dict.  Roles re-derived from
# ``data/node-contracts`` by ``tests/test_plan.py``.  Its *effect* still needs a
# 碰撞触发器 component on ``target`` (which this project cannot add); see
# ``modules/interaction.py`` — the node PLACES and EXECUTES, the interaction does
# not fire.
ACTIVATE_COLLISION_TRIGGER = NodeType(
    90,
    "激活/关闭碰撞触发器",
    exec_in=0,
    exec_outs={"then": 0},
    ins={"target": 0, "trigger_index": 1, "activate": 2},
)
# Variable-change events (F1 entry points; writing variables has no tool yet).
CUSTOM_VARIABLE_CHANGED = NodeType(
    36, "自定义变量变化时", exec_outs={"then": 0}, outs={"entity": 0, "guid": 1, "name": 2, "before": 3, "after": 4}
)
GRAPH_VARIABLE_CHANGED = NodeType(
    351, "节点图变量变化时", exec_outs={"then": 0}, outs={"entity": 0, "guid": 1, "name": 2, "before": 3, "after": 4}
)
SHOP_SOLD_BAG_ITEM = NodeType(
    701,
    "商店出售背包物品时",
    exec_outs={"then": 0},
    outs={"shop_owner": 0, "shop_owner_guid": 1, "buyer": 2, "shop_index": 3, "item": 4, "count": 5},
)
SHOP_BOUGHT_ITEM = NodeType(
    705,
    "商店收购道具时",
    exec_outs={"then": 0},
    outs={"shop_owner": 0, "shop_owner_guid": 1, "seller": 2, "shop_index": 3, "items": 4},
)

# ---------------------------------------------------------------------------
# Flow control / execution nodes
# ---------------------------------------------------------------------------
BRANCH = NodeType(
    2, "双分支", exec_in=0, exec_outs={"true": 0, "false": 1}, ins={"condition": 0}
)
PRINT = NodeType(1, "打印字符串", exec_in=0, exec_outs={"then": 0}, ins={"text": 0})
START_TIMER = NodeType(
    79,
    "启动定时器",
    exec_in=0,
    exec_outs={"then": 0},
    ins={"target": 0, "name": 1, "loop": 2, "sequence": 3, "context_guid": 4},
)
STOP_TIMER = NodeType(82, "终止定时器", exec_in=0, exec_outs={"then": 0}, ins={"target": 0, "name": 1})
ADD_BAG_CURRENCY = NodeType(
    688, "增加背包货币数量", exec_in=0, exec_outs={"then": 0}, ins={"holder": 0, "currency": 1, "delta": 2}
)
ADD_BAG_ITEM = NodeType(
    686, "增加背包道具数量", exec_in=0, exec_outs={"then": 0}, ins={"holder": 0, "item": 1, "delta": 2}
)
ADD_BAG_CAPACITY = NodeType(
    685, "增加背包最大容量", exec_in=0, exec_outs={"then": 0}, ins={"holder": 0, "delta": 1}
)
OPEN_SHOP = NodeType(
    702, "打开商店", exec_in=0, exec_outs={"then": 0}, ins={"player": 0, "shop_owner": 1, "shop_index": 2}
)
CLOSE_SHOP = NodeType(
    703, "关闭商店", exec_in=0, exec_outs={"then": 0}, ins={"player": 0}
)

# ---------------------------------------------------------------------------
# Query nodes (data only)
# ---------------------------------------------------------------------------
GET_BAG_CURRENCY = NodeType(691, "获取背包货币数量", ins={"holder": 0, "currency": 1}, outs={"amount": 0})
GET_BAG_ITEM = NodeType(690, "获取背包道具数量", ins={"holder": 0, "item": 1}, outs={"amount": 0})
GET_BAG_CAPACITY = NodeType(689, "获取背包容量", ins={"holder": 0}, outs={"capacity": 0})
GET_ALL_BAG_ITEMS = NodeType(721, "获取背包所有基础道具", ins={"holder": 0}, outs={"items": 0})
GET_ALL_BAG_CURRENCIES = NodeType(722, "获取背包所有货币", ins={"holder": 0}, outs={"currencies": 0})

# ---------------------------------------------------------------------------
# Dictionary node (data only).  1158 以键查询字典值 IS in the server store -- the
# 2026-10-12 correction (``DICT-WRITE-PROBE.md``) retired the false "the family is
# absent" negative.  Its three pins are declared **generic** (``serverParamType 0``
# on 3:0 dict / 3:1 key / 4:0 value), which is what makes it only a *candidate*
# consumer of a concrete type-27 dict output: whether the editor materialises the
# generic pins from the concrete 27 has never been observed.  ``tests/test_plan.py``
# re-derives the three indices from the contract like every other row here.
# ---------------------------------------------------------------------------
DICT_LOOKUP = NodeType(1158, "以键查询字典值", ins={"dict": 0, "key": 1}, outs={"value": 0})

# ---------------------------------------------------------------------------
# Pure arithmetic / comparison nodes (data only; "op" is the operand-kind enum)
# ---------------------------------------------------------------------------
ADD = NodeType(200, "加法运算", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
SUB = NodeType(202, "减法运算", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
MUL = NodeType(204, "乘法运算", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
DIV = NodeType(206, "除法运算", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
EQ = NodeType(14, "是否相等", ins={"left": 0, "right": 1}, outs={"result": 0})
LT = NodeType(230, "数值小于", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
LE = NodeType(231, "数值小于等于", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
GT = NodeType(232, "数值大于", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})
GE = NodeType(233, "数值大于等于", ins={"left": 0, "right": 1, "op": 2}, outs={"result": 0})


ALL_NODE_TYPES: tuple[NodeType, ...] = (
    ON_CREATE, SELF, TIMER_TICK, BAG_ITEM_ADDED, BAG_ITEM_LOST, BAG_ITEM_CHANGED,
    BAG_CURRENCY_CHANGED, BAG_ITEM_USED, SHOP_SOLD_BAG_ITEM, SHOP_BOUGHT_ITEM,
    PROXIMITY_ENTER, PROXIMITY_LEAVE, UI_CONTROL_TRIGGERED, FLOATING_PAGE_TRIGGERED,
    ACTIVATE_COLLISION_TRIGGER,
    CUSTOM_VARIABLE_CHANGED, GRAPH_VARIABLE_CHANGED,
    BRANCH, PRINT, START_TIMER, STOP_TIMER, ADD_BAG_CURRENCY, ADD_BAG_ITEM,
    ADD_BAG_CAPACITY, OPEN_SHOP, CLOSE_SHOP,
    GET_BAG_CURRENCY, GET_BAG_ITEM, GET_BAG_CAPACITY, GET_ALL_BAG_ITEMS, GET_ALL_BAG_CURRENCIES,
    DICT_LOOKUP,
    ADD, SUB, MUL, DIV, EQ, LT, LE, GT, GE,
)


class Handle:
    """A placed node within a :class:`Graph`; resolves roles to pin indices."""

    def __init__(self, graph: "Graph", spec: NodeSpec, ntype: NodeType):
        self.graph = graph
        self.spec = spec
        self.ntype = ntype

    @property
    def alias(self) -> str:
        return self.spec.alias

    def _out_index(self, role: str) -> int:
        if role not in self.ntype.outs:
            raise KeyError(
                f"node {self.ntype.label} has no output role {role!r}; "
                f"known: {sorted(self.ntype.outs)}"
            )
        return self.ntype.outs[role]

    def _in_index(self, role: str) -> int:
        if role not in self.ntype.ins:
            raise KeyError(
                f"node {self.ntype.label} has no input role {role!r}; "
                f"known: {sorted(self.ntype.ins)}"
            )
        return self.ntype.ins[role]

    def out(self, role: str = "result") -> tuple[str, int, int]:
        """A data-output reference: ``(alias, DATA_OUTPUT, index)``."""
        return (self.alias, DATA_OUTPUT, self._out_index(role))

    def flow_to(self, other: "Handle", from_role: str = "then") -> EdgeSpec:
        """Wire an execution edge from ``from_role`` to ``other``'s exec input."""
        if from_role not in self.ntype.exec_outs:
            raise KeyError(
                f"node {self.ntype.label} has no execution output {from_role!r}; "
                f"known: {sorted(self.ntype.exec_outs)}"
            )
        if other.ntype.exec_in is None:
            raise KeyError(f"node {other.ntype.label} has no execution input")
        return self.graph.plan.wire(
            self.alias, EXEC_OUTPUT, self.ntype.exec_outs[from_role],
            other.alias, EXEC_INPUT, other.ntype.exec_in,
        )

    def data_from(self, src: "Handle", src_role: str, dst_role: str) -> EdgeSpec:
        """Wire a data edge ``src.src_role -> self.dst_role``."""
        if dst_role not in self.ntype.ins:
            raise KeyError(
                f"node {self.ntype.label} has no input role {dst_role!r}; "
                f"known: {sorted(self.ntype.ins)}"
            )
        return self.graph.plan.wire(
            src.alias, DATA_OUTPUT, src._out_index(src_role),
            self.alias, DATA_INPUT, self.ntype.ins[dst_role],
        )

    def const(self, role: str, value: object, slot: str, **expect) -> ConstSpec:
        """Write a typed constant into one of this node's data inputs."""
        return self.graph.plan.const(
            self.alias, self._in_index(role), value, slot, **expect
        )


class Graph:
    """A thin, role-aware facade over :class:`GraphPlan`."""

    def __init__(self, name: str, graph_kind: int = 20000):
        self.plan = GraphPlan(name=name, graph_kind=graph_kind)
        self._handles: dict[str, Handle] = {}

    @property
    def name(self) -> str:
        return self.plan.name

    def place(self, ntype: NodeType, alias: str, x: int = 0, y: int = 0) -> Handle:
        if alias in self._handles:
            raise ValueError(f"alias {alias!r} is already used in this graph")
        spec = self.plan.add(alias, ntype.definition_id, x=x, y=y)
        handle = Handle(self, spec, ntype)
        self._handles[alias] = handle
        return handle

    def handle(self, alias: str) -> Handle:
        return self._handles[alias]

    def validate(self, store=None) -> None:
        self.plan.validate(store)
