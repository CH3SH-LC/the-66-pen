"""M3 — items (道具).

Like currency, the item *template* (ID type 8 ``普通道具、装备道具``, chapter
``mhbgx0rspbqu``) is an editor asset this project cannot create — bridge, CLI and
MCP have no writer for it.  The runtime half is a full set of server nodes.

Node ids (server kind 20000, verified against ``data/node-contracts``):

* ``686`` 增加背包道具数量 — give/take items from a holder
* ``690`` 获取背包道具数量 — read how many of one item a holder has
* ``681`` 背包道具新增时 / ``682`` 背包道具失去时 — gain/lose events
* ``683`` 背包道具数量变化时 — any change, with before/after/reason
* ``733`` 背包内道具被使用时 — the "use" event (the crafting hook)

``item_id`` is a ``道具配置ID`` (contract type 20); its write slot is passed in
explicitly for the same reason as M2 — see
:data:`graphplan.paramtypes.CONFIG_ID_SLOT`.
"""

from __future__ import annotations

from .. import compare as compare_mod
from ..nodes import (
    BAG_ITEM_ADDED,
    BAG_ITEM_CHANGED,
    BAG_ITEM_LOST,
    BAG_ITEM_USED,
    GET_BAG_ITEM,
    ADD_BAG_ITEM,
    Graph,
    Handle,
)

HolderRef = tuple[Handle, str]


def grant(
    g: Graph,
    src: Handle,
    *,
    holder: HolderRef,
    item_id: int,
    count: int,
    item_slot: str,
    alias: str = "m3_grant",
    from_role: str = "then",
) -> Handle:
    """给/扣道具：``amount`` 可为负。返回节点，可续接 ``then``。"""
    node = g.place(ADD_BAG_ITEM, alias)
    src.flow_to(node, from_role)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    node.const("item", int(item_id), item_slot)
    node.const("delta", int(count), "int")
    return node


def read(
    g: Graph,
    *,
    holder: HolderRef,
    item_id: int,
    item_slot: str,
    alias: str = "m3_read",
) -> Handle:
    """查道具数量：返回数据节点，``amount`` 输出是背包里该道具的数量。"""
    node = g.place(GET_BAG_ITEM, alias)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    node.const("item", int(item_id), item_slot)
    return node


def has_enough(
    g: Graph,
    *,
    holder: HolderRef,
    item_id: int,
    threshold: int,
    item_slot: str,
    alias: str = "m3_enough",
    compare: str = "gte",
) -> Handle:
    """材料够不够：查背包数量(690) 再和 ``threshold`` 比较，返回**比较节点**。

    组装：``获取背包道具数量(690)`` 的数量输出接到比较节点的 ``left``（3:0），
    ``threshold`` 作为常量写在比较节点的 ``right``（3:1），``item_id`` 写在 690
    的 ``item``（3:1）。  ``compare`` 默认 ``"gte"``（``数值大于等于(233)``，即
    「数量 ≥ 阈值」算够），可选 ``gt`` / ``lte`` / ``lt`` / ``eq``。

    返回比较节点；它的 ``result``（bool）直接驱动 ``双分支(2)`` 的条件——够走
    真分支，不够走假分支。
    """
    # One shared lookup, so an unknown key fails exactly as it does in currency
    # (graphplan.compare.resolve raises the single named UnknownCompareError).
    cmp_type = compare_mod.resolve(compare)

    read_node = read(
        g,
        holder=holder,
        item_id=item_id,
        item_slot=item_slot,
        alias=f"{alias}_read",
    )
    cmp_node = g.place(cmp_type, alias)
    cmp_node.data_from(read_node, "amount", "left")
    cmp_node.const("right", int(threshold), "int")
    return cmp_node


def on_added(g: Graph, alias: str = "m3_added") -> Handle:
    """背包道具新增时（事件入口）。"""
    return g.place(BAG_ITEM_ADDED, alias)


def on_lost(g: Graph, alias: str = "m3_lost") -> Handle:
    """背包道具失去时（事件入口）。"""
    return g.place(BAG_ITEM_LOST, alias)


def on_changed(g: Graph, alias: str = "m3_changed") -> Handle:
    """背包道具数量变化时（事件入口）；出参含变化前/变化后/变化原因。"""
    return g.place(BAG_ITEM_CHANGED, alias)


def on_used(g: Graph, alias: str = "m3_used") -> Handle:
    """背包内道具被使用时（事件入口）——合成/消耗玩法的挂点。"""
    return g.place(BAG_ITEM_USED, alias)
