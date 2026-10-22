"""M4 — inventory (背包).

The inventory *template* (ID type 11 ``道具背包``, chapters ``mhogfq9bf86q`` /
``mh5y5001vqd4``) is again editor-only for this project.  What the node graph
gets is *query* access to whatever a holder is carrying.

Node ids (server kind 20000, verified against ``data/node-contracts``):

* ``689`` 获取背包容量 — current capacity of a holder's bag
* ``685`` 增加背包最大容量 — grow the capacity
* ``721`` 获取背包所有基础道具 — the whole item table (contract type 27 dict)
* ``722`` 获取背包所有货币 — the whole currency table (type 27 dict)

:func:`capacity_gate` combines ``689`` with a comparison node (default ``230``
数值小于) to answer "is this holder's bag capacity below a threshold"; the
comparison's ``result`` is a bool that feeds ``双分支``.

The two ``获取…所有…`` nodes return dictionaries.  A dict-access node *does*
exist — ``1158 以键查询字典值`` is in the server store, together with the rest of
the family (``1298`` / ``1368`` / ``1438`` / ``1508`` / ``1578`` / ``1648`` /
``1718`` / ``1928`` / ``1938``) — so the earlier claim that a dict-access node was
absent was a **false negative** (``DICT-WRITE-PROBE.md``, 2026-10-10).  What is
*not* proven is whether it runs: none of these has ever been placed in a real
graph.  So they are exposed here for completeness and for the export-time shape
check, but a demo that needs "the Nth item" must use ``item.read`` (``690``) with a
known ``道具配置ID`` instead.
"""

from __future__ import annotations

from ..nodes import (
    ADD_BAG_CAPACITY,
    GE,
    GET_ALL_BAG_CURRENCIES,
    GET_ALL_BAG_ITEMS,
    GET_BAG_CAPACITY,
    GT,
    LE,
    LT,
    Graph,
    Handle,
)

HolderRef = tuple[Handle, str]

#: ``compare`` selector -> the official comparison node (server kind 20000).
#:
#: All four are pure data nodes (no execution pins) whose ``left`` / ``right``
#: pins are *generic* (``serverParamType == 0``) and whose ``result`` is a
#: concrete bool (type 4), so their result feeds ``双分支``'s ``condition``.
COMPARE_NODES = {
    "lt": LT,  # 230 数值小于
    "le": LE,  # 231 数值小于等于
    "gt": GT,  # 232 数值大于
    "ge": GE,  # 233 数值大于等于
}


def capacity(
    g: Graph, *, holder: HolderRef, alias: str = "m4_capacity"
) -> Handle:
    """查背包容量：返回数据节点，``capacity`` 输出是容量（整数）。"""
    node = g.place(GET_BAG_CAPACITY, alias)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    return node


def capacity_gate(
    g: Graph,
    *,
    holder: HolderRef,
    threshold: int,
    alias: str = "m4_gate",
    compare: str = "lt",
) -> Handle:
    """容量门：``获取背包容量`` (689) 比 ``threshold``，返回**比较节点**。

    放两个数据节点、连一条数据边、写一个常量：

    * ``689`` 获取背包容量 —— ``holder`` 实体输出接到它的 ``holder`` 入参（``3:0``）；
    * 比较节点（默认 ``230`` 数值小于）—— ``689`` 的 ``capacity`` 出参接到
      ``left``（``3:0``），``threshold`` 作为常量写进 ``right``（``3:1``, slot ``int``）。

    返回值是**比较节点**，它的 ``result`` 出参是 bool（type 4），可直接接
    ``双分支`` 的 ``condition``。语义：默认 ``lt`` 时 ``容量 < threshold`` 为真
    （即"背包将满"这一越界提示的判据）。``compare`` 取 :data:`COMPARE_NODES`
    的键之一（``lt`` / ``le`` / ``gt`` / ``ge``）；未知取值抛 ``KeyError``。
    """
    node_type = COMPARE_NODES.get(compare)
    if node_type is None:
        raise KeyError(
            f"unknown compare {compare!r}; known: {sorted(COMPARE_NODES)}"
        )
    cap = capacity(g, holder=holder, alias=f"{alias}_cap")
    node = g.place(node_type, alias)
    node.data_from(cap, "capacity", "left")
    node.const("right", int(threshold), "int")
    return node


def grow(
    g: Graph,
    src: Handle,
    *,
    holder: HolderRef,
    amount: int,
    alias: str = "m4_grow",
    from_role: str = "then",
) -> Handle:
    """扩容：``src`` 触发时把背包容量加 ``amount``。"""
    node = g.place(ADD_BAG_CAPACITY, alias)
    src.flow_to(node, from_role)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    node.const("delta", int(amount), "int")
    return node


def grow_then(
    g: Graph,
    src: Handle,
    *,
    holder: HolderRef,
    amount: int,
    alias: str = "m4_grow_then",
    from_role: str = "then",
) -> Handle:
    """扩容（执行流形态）：``src`` 的 ``then`` 触发时把背包容量加 ``amount``。

    与 :func:`grow` 是同一个 ``685`` 增加背包最大容量 片段——``holder`` 接
    ``3:0``，``amount`` 作为常量写进 ``delta``（``3:1``, slot ``int``），返回
    节点以便续接 ``then``。命名把"由执行边驱动"这件事显式化，调用方在
    "先扩建、后放货"这类序列里读起来更清楚。
    """
    return grow(
        g, src, holder=holder, amount=amount, alias=alias, from_role=from_role
    )


def all_items(g: Graph, *, holder: HolderRef, alias: str = "m4_all_items") -> Handle:
    """获取背包所有基础道具：``items`` 输出是一个字典（type 27）。

    见模块文档：取字典元素的节点（``1158 以键查询字典值``）在合同里**存在**，但从未上过
    真机；拿单个数量请用 :func:`graphplan.modules.item.read`。
    """
    node = g.place(GET_ALL_BAG_ITEMS, alias)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    return node


def all_currencies(
    g: Graph, *, holder: HolderRef, alias: str = "m4_all_currencies"
) -> Handle:
    """获取背包所有货币：``currencies`` 输出是一个字典（type 27）。"""
    node = g.place(GET_ALL_BAG_CURRENCIES, alias)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    return node
