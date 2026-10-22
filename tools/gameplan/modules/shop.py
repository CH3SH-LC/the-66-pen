"""M5 shop graphs: open/close, sale tables, and automatic-trade events.

704 updates custom goods; 706 updates bag goods; 709 appends bag goods. Prices
use the concrete type-27 dictionary writer with uint currency IDs/int amounts,
as read back from native 704. Each operation still requires its live descriptor
and configured shop component; this module does not create asset templates.

The engine settles shop trades automatically (official chapters mhi9s7isvp50 /
mho6gviqhsqs). Events 701/705 therefore add no wallet mutation by default.
Explicit bonuses are a separate, fixed reward per event, never sale settlement.
Only bag-store trades trigger 701 (mhn7ko01v3yw); custom shops do not.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..economy_catalog import price_entries
from ..plan import NODE_LIMIT
from ..nodes import (
    CLOSE_SHOP,
    OPEN_SHOP,
    SHOP_BOUGHT_ITEM,
    SHOP_SOLD_BAG_ITEM,
    Graph,
    Handle,
    NodeType,
)
from . import currency as _currency

ShopRef = tuple[Handle, str]
"""The shop *owner* entity reference: ``(handle, role)`` yielding an entity."""


# ---------------------------------------------------------------------------
# Table-writer node definitions (server kind 20000).
#
# Roles are named here, re-derived from ``data/node-contracts`` by
# ``tests/test_shop.py`` (mirroring tests/test_plan.py), so a drifted index
# fails the suite instead of a native call.  ``price`` is the type-27 dict pin,
# compiled through the adapter's descriptor-checked container writer.
# ---------------------------------------------------------------------------

SET_CUSTOM_SHOP_ITEM = NodeType(
    704,
    "设置自定义商店商品出售信息",
    exec_in=0,
    exec_outs={"then": 0},
    ins={
        "shop_owner": 0,   # 商店归属者实体 (entity)
        "shop_index": 1,   # 商店序号 (int)
        "item_index": 2,   # 商品序号 (int) — 自定义商店 only
        "item": 3,         # 道具配置ID (config-id)
        "price": 4,        # 出售货币字典 (dict, type 27)
        "tab_index": 5,    # 所属页签序号 (int)
        "limited": 6,      # 是否限购 (bool) — 自定义商店 only
        "limit_count": 7,  # 限购数量 (int) — 自定义商店 only
        "sort_priority": 8,
        "sellable": 9,
    },
)
ADD_BAG_SHOP_ITEM = NodeType(
    709,
    "向背包商店出售表中新增商品",
    exec_in=0,
    exec_outs={"then": 0},
    ins={
        "shop_owner": 0,   # 商店归属者实体 (entity)
        "shop_index": 1,   # 商店序号 (int)
        "item": 2,         # 商品道具配置ID (config-id)
        "price": 3,        # 出售货币字典 (dict, type 27)
        "tab_index": 4,    # 所属页签序号 (int)
        "sort_priority": 5,
        "sellable": 6,
    },
)
SET_BAG_SHOP_ITEM = NodeType(
    706,
    "设置背包商店商品出售信息",
    exec_in=0,
    exec_outs={"then": 0},
    ins={
        "shop_owner": 0,   # 商店归属者实体 (entity)
        "shop_index": 1,   # 商店序号 (int)
        "item": 2,         # 道具配置ID (config-id)
        "price": 3,        # 出售货币字典 (dict, type 27)
        "tab_index": 4,    # 所属页签序号 (int)
        "sort_priority": 5,
        "sellable": 6,
    },
)

#: Every table-writer definition this module can place, for tests/registration.
SHOP_TABLE_NODE_TYPES: tuple[NodeType, ...] = (
    SET_CUSTOM_SHOP_ITEM,
    ADD_BAG_SHOP_ITEM,
    SET_BAG_SHOP_ITEM,
)

#: Store selectors accepted by :func:`list_item_for_sale`.
STORE_BAG_ADD = "bag-add"   # 709 — add a product to a bag store's sale table
STORE_BAG_SET = "bag-set"   # 706 — edit an existing bag-store product's info
STORE_CUSTOM = "custom"     # 704 — update a custom product by its runtime index

_TABLE_NODES: dict[str, NodeType] = {
    STORE_BAG_ADD: ADD_BAG_SHOP_ITEM,
    STORE_BAG_SET: SET_BAG_SHOP_ITEM,
    STORE_CUSTOM: SET_CUSTOM_SHOP_ITEM,
}

#: 所属页签序号 enum, verbatim from ``mhw66orrrfkm`` (数字后直接接中文):
#: ``1装备、2消耗品、3材料、4贵重物品``.
TAB_INDEX_ENUM = {1: "装备", 2: "消耗品", 3: "材料", 4: "贵重物品"}


class DictPinUnsupported(ValueError):
    """Legacy exception retained for imports; supported sale writers no longer raise it."""

    def __init__(self, node_id: int, pin_index: int, *, detail: str = ""):
        self.node_id = int(node_id)
        self.pin_index = int(pin_index)
        message = (
            f"node {self.node_id} pin 3:{self.pin_index} 出售货币字典 has "
            f"serverParamType 27 (字典); the caller's requested operation is unsupported"
        )
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


# ---------------------------------------------------------------------------
# Open / close / events (unchanged)
# ---------------------------------------------------------------------------

def open_(
    g: Graph,
    src: Handle,
    *,
    player: ShopRef,
    shop_owner: ShopRef,
    shop_index: int,
    alias: str = "m5_open",
    from_role: str = "then",
) -> Handle:
    """打开商店：``src`` 触发时给 ``player`` 打开 ``shop_owner`` 的第 ``shop_index`` 号商店。"""
    node = g.place(OPEN_SHOP, alias)
    src.flow_to(node, from_role)
    player_handle, player_role = player
    owner_handle, owner_role = shop_owner
    node.data_from(player_handle, player_role, "player")
    node.data_from(owner_handle, owner_role, "shop_owner")
    node.const("shop_index", int(shop_index), "int")
    return node


def close(
    g: Graph,
    src: Handle,
    *,
    player: ShopRef,
    alias: str = "m5_close",
    from_role: str = "then",
) -> Handle:
    """关闭商店：``src`` 触发时关掉 ``player`` 当前打开的商店。"""
    node = g.place(CLOSE_SHOP, alias)
    src.flow_to(node, from_role)
    player_handle, player_role = player
    node.data_from(player_handle, player_role, "player")
    return node


def on_sold_bag_item(g: Graph, alias: str = "m5_sold") -> Handle:
    """商店出售背包物品时（事件入口）。

    出参：``shop_owner`` / ``buyer`` / ``shop_index`` / ``item`` / ``count``。
    只有**背包商店**的交易会触发它。原生交易已结算，不再修改钱包。
    """
    return g.place(SHOP_SOLD_BAG_ITEM, alias)


def on_shop_bought(g: Graph, alias: str = "m5_bought") -> Handle:
    """商店收购道具时（事件入口）。出参：``shop_owner`` / ``seller`` / ``items``。"""
    return g.place(SHOP_BOUGHT_ITEM, alias)


# ---------------------------------------------------------------------------
# 商品出售表 (M5) — bag and custom store writers
# ---------------------------------------------------------------------------

def _integer(value, name, minimum=1, maximum=2**31 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def list_item_for_sale(
    g: Graph,
    src: Handle,
    *,
    shop_owner: ShopRef,
    shop_index: int,
    item_id: int,
    item_slot: str,
    store: str = STORE_BAG_ADD,
    tab_index: int = 1,
    sort_priority: int = 0,
    sellable: bool = True,
    price: Mapping[int, int] | None = None,
    item_index: int | None = None,
    limit_count: int | None = None,
    flag_slot: str = "enum",
    key_tag: str = "uint",
    value_tag: str = "int",
    alias: str | None = None,
    from_role: str = "then",
) -> Handle:
    """添加/更新出售表：bag-add→709，bag-set→706，custom→704。

    ``price`` 是货币配置 ID 到正整数金额的映射。背包商店省略价格时保留
    道具模板的货币价值；自定义商店必须给出价格和已有 ``item_index``。
    ``limit_count=None`` 表示不限购，正数表示限购数量，仅用于自定义商品。
    704 更新已有商品；新建自定义商品请用 economy_catalog.add_sale (708)。
    ``flag_slot`` 默认 enum (uint 0/1)，可按已验证的原生描述显式选择 bool。
    """
    node_type = _TABLE_NODES.get(store)
    if node_type is None:
        raise KeyError(
            f"unknown shop store {store!r}; known: {sorted(_TABLE_NODES)}"
        )
    if item_slot not in ("int", "uint"):
        raise ValueError("item_slot must be 'int' or 'uint'")
    if flag_slot not in ("enum", "bool"):
        raise ValueError("flag_slot must be 'enum' or 'bool'")
    _integer(shop_index, "shop_index", minimum=0)
    _integer(item_id, "item_id", maximum=2**32 - 1 if item_slot == "uint" else 2**31 - 1)
    _integer(tab_index, "tab_index", maximum=4)
    _integer(sort_priority, "sort_priority", minimum=0)
    if type(sellable) is not bool:
        raise ValueError("sellable must be bool")
    encoded_price = None if price is None else {"dict": price_entries(
        price, key_tag=key_tag, value_tag=value_tag)}
    if store == STORE_CUSTOM:
        _integer(item_index, "item_index", minimum=0)
        if encoded_price is None:
            raise ValueError("custom shop updates require price")
        if limit_count is not None:
            _integer(limit_count, "limit_count")
    elif item_index is not None or limit_count is not None:
        raise ValueError("item_index and limit_count are only for custom shops")
    owner_handle, owner_role = shop_owner
    if src.graph is not g or owner_handle.graph is not g:
        raise ValueError("source and shop_owner must belong to this graph")
    if from_role not in src.ntype.exec_outs or owner_role not in owner_handle.ntype.outs:
        raise ValueError("source or shop_owner role is absent")
    node_alias = alias or f"m5_list_{store}"
    if node_alias in g.plan.aliases() or len(g.plan.nodes) >= NODE_LIMIT:
        raise ValueError("shop node alias is already used or graph node limit reached")

    node = g.place(node_type, node_alias)
    src.flow_to(node, from_role)
    node.data_from(owner_handle, owner_role, "shop_owner")
    node.const("shop_index", shop_index, "int")
    node.const("item", item_id, item_slot)
    node.const("tab_index", tab_index, "int")
    node.const("sort_priority", sort_priority, "int")
    node.const("sellable", int(sellable) if flag_slot == "enum" else sellable, flag_slot)
    if encoded_price is not None:
        node.const("price", encoded_price, "auto")
    if store == STORE_CUSTOM:
        node.const("item_index", item_index, "int")
        limited = limit_count is not None
        node.const("limited", int(limited) if flag_slot == "enum" else limited, flag_slot)
        node.const("limit_count", limit_count or 0, "int")
    return node


# ---------------------------------------------------------------------------
# 商店交易事件 (M5) — native settlement, with optional explicit bonuses
# ---------------------------------------------------------------------------

def acquire_and_pay(
    g: Graph,
    *,
    seller: str = "seller",
    currency_id: int | None = None,
    unit_price: int | None = None,
    currency_slot: str = "uint",
    alias: str = "m5_bought",
    bonus_amount: int = 0,
) -> Handle:
    """接收 705 收购事件；原生交易已付款，默认不改任何钱包。

    保留旧函数名。unit_price 已拒绝，避免原来的重复扣款。
    只有 bonus_amount>0 才给 seller 角色指定的实体追加一次正奖励。
    奖励按事件计，不乘物品数量；调用方必须确认该实体有配置好的背包。
    返回事件句柄，供继续读取 items / shop_index。
    """
    if seller not in ("seller", "shop_owner"):
        raise KeyError(f"unknown seller {seller!r}; known: ['seller', 'shop_owner']")
    return _trade_event(g, SHOP_BOUGHT_ITEM, alias=alias, recipient=seller,
                        currency_id=currency_id, currency_slot=currency_slot,
                        unit_price=unit_price, bonus_amount=bonus_amount,
                        bonus_alias=f"{alias}_bonus")


def on_bag_item_sold(
    g: Graph,
    *,
    currency_id: int | None = None,
    unit_price: int | None = None,
    currency_slot: str = "uint",
    payee: str = "shop_owner",
    alias: str = "m5_sold",
    pay_alias: str | None = None,
    bonus_amount: int = 0,
) -> Handle:
    """接收 701 背包商店售出事件；默认不重复结算或增加货币。

    bonus_amount>0 才给 payee（shop_owner/buyer）一次固定额外奖励。
    调用方必须确认接收实体有背包；奖励不等于单价、不乘 count。
    unit_price 传值会明确拒绝，防止旧调用默默重复结算。
    pay_alias 仅作为显式奖励节点的兼容别名。返回 701 事件句柄。
    """
    if payee not in ("shop_owner", "buyer"):
        raise KeyError(f"unknown payee {payee!r}; known: ['shop_owner', 'buyer']")
    return _trade_event(g, SHOP_SOLD_BAG_ITEM, alias=alias, recipient=payee,
                        currency_id=currency_id, currency_slot=currency_slot,
                        unit_price=unit_price, bonus_amount=bonus_amount,
                        bonus_alias=pay_alias or f"{alias}_bonus")


def _trade_event(g, node_type, *, alias, recipient, currency_id, currency_slot,
                 unit_price, bonus_amount, bonus_alias):
    if unit_price is not None:
        raise ValueError("NATIVE_SHOP_AUTO_SETTLEMENT: unit_price is no longer accepted; "
                         "use explicit bonus_amount only for an additional reward")
    _integer(bonus_amount, "bonus_amount", minimum=0)
    aliases = [alias]
    if bonus_amount:
        if currency_slot not in ("int", "uint"):
            raise ValueError("currency_slot must be 'int' or 'uint'")
        _integer(currency_id, "currency_id",
                 maximum=2**32 - 1 if currency_slot == "uint" else 2**31 - 1)
        aliases.append(bonus_alias)
    if len(set(aliases)) != len(aliases) or any(not a or a in g.plan.aliases() for a in aliases):
        raise ValueError("trade event aliases must be non-empty and unused")
    if len(g.plan.nodes) + len(aliases) > NODE_LIMIT:
        raise ValueError("trade event exceeds graph node limit")
    event = g.place(node_type, alias)
    if bonus_amount:
        _currency.grant(g, event, holder=(event, recipient), currency_id=currency_id,
                        amount=bonus_amount, currency_slot=currency_slot, alias=bonus_alias)
    return event


# ---------------------------------------------------------------------------
# 查询出售表 (M5 #6) — read a store's sale table
# ---------------------------------------------------------------------------
#
# Two *query* nodes (server kind 20000) that read a store's sale table.  Both
# have **no execution pins at all** — no execution input, no execution output —
# and exactly two data inputs: ``3:0`` 商店归属者实体 (entity, type 1) and
# ``3:1`` 商店序号 (int, type 3).  Both return one aggregate on ``4:0``.
#
# That aggregate is NOT a type-27 dictionary.  The brief that asked for these
# helpers called the output "a dictionary (contract type 27)", but the contract
# store says otherwise and the contract store is authoritative:
#
#   * ``714`` 查询自定义商店商品出售列表 — ``4:0`` is **serverParamType 8**
#     (``valueType`` ``List``), named 商品序号列表;
#   * ``715`` 查询背包商店物品出售列表 — ``4:0`` is **serverParamType 22**,
#     named 道具配置ID列表.
#
# (The type-27 dict claim is true of the *inventory* table reads ``721``/``722``
# 获取背包所有… — see ``modules/inventory.py`` — but not of these two nodes.)
#
# Either way the output is an opaque aggregate this project cannot consume:
#
#   * ``paramtypes.SLOT_FOR_TYPE`` has no slot for type 8 or 22 (both ``None``),
#     so the value cannot be *written*;
#   * the server contract store declares no generic list/dict **accessor** — the
#     only nodes whose data input is type 8 or 22 are unrelated (632 唤起卡牌
#     选择器, 743 随机卡牌选择器选择列表, 617 设置实体生效铭牌 …), never a
#     shop-table reader.
#
# So the output is exposed for completeness and for the export-time shape check,
# but a caller that wants "the Nth item on sale" must drive the table itself
# (:func:`list_item_for_sale`) and read single quantities with ``690``.  This
# module never fabricates a downstream reader.

QUERY_CUSTOM_SHOP_SALES = NodeType(
    714,
    "查询自定义商店商品出售列表",
    ins={
        "shop_owner": 0,  # 商店归属者实体 (entity, type 1)
        "shop_index": 1,  # 商店序号 (int, type 3)
    },
    outs={"item_indices": 0},  # 商品序号列表 (serverParamType 8, valueType List)
)
QUERY_BAG_SHOP_SALES = NodeType(
    715,
    "查询背包商店物品出售列表",
    ins={
        "shop_owner": 0,  # 商店归属者实体 (entity, type 1)
        "shop_index": 1,  # 商店序号 (int, type 3)
    },
    outs={"item_config_ids": 0},  # 道具配置ID列表 (serverParamType 22)
)

#: Every query definition this module can place, for tests/registration.
SHOP_QUERY_NODE_TYPES: tuple[NodeType, ...] = (
    QUERY_CUSTOM_SHOP_SALES,
    QUERY_BAG_SHOP_SALES,
)


def _query_sales(
    g: Graph,
    ntype: NodeType,
    *,
    holder: ShopRef,
    alias: str,
    shop_index: int | None,
) -> Handle:
    """Place a sale-table query node: wire the holder, optionally the index."""
    node = g.place(ntype, alias)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "shop_owner")
    if shop_index is not None:
        node.const("shop_index", int(shop_index), "int")
    return node


def query_bag_sales(
    g: Graph,
    *,
    holder: ShopRef,
    alias: str,
    shop_index: int | None = None,
) -> Handle:
    """查询背包商店物品出售列表 (``715``)：读 ``holder`` 的背包商店出售表。

    纯查询节点（无执行输入，也无执行输出）：``holder`` 的实体输出接到 ``3:0``
    商店归属者实体；``shop_index`` 若给则写进 ``3:1`` 商店序号（slot ``int``），
    不给则留空。

    返回节点的 ``item_config_ids`` 出参是**一个不透明聚合**（serverParamType
    22，名为 道具配置ID列表）——本工程既写不出也拆不开，**不可接下游读取器**；
    详见本节上方说明。**不伪造读取器。**
    """
    return _query_sales(
        g, QUERY_BAG_SHOP_SALES, holder=holder, alias=alias, shop_index=shop_index
    )


def query_custom_sales(
    g: Graph,
    *,
    holder: ShopRef,
    alias: str,
    shop_index: int | None = None,
) -> Handle:
    """查询自定义商店商品出售列表 (``714``)：读 ``holder`` 的自定义商店出售表。

    与 :func:`query_bag_sales` 同形状（无执行输入、无执行输出，``3:0`` 接
    ``holder``，``3:1`` 写 ``shop_index``）。返回节点的 ``item_indices`` 出参是
    不透明聚合（serverParamType 8，valueType ``List``，名为 商品序号列表），
    **同样不可下游消费**——只作导出期形状检查/占位。
    """
    return _query_sales(
        g, QUERY_CUSTOM_SHOP_SALES, holder=holder, alias=alias, shop_index=shop_index
    )
