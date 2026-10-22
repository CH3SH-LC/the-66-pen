"""M2 — currency (货币).

The official system is a first-class editor template (ID type 10 ``资源货币``,
chapter ``mh2cr30yeak0``) and a set of runtime nodes.  The template itself
**cannot be created by this project's tools** — that half lives only in the
editor UI (system menu → 货币与背包 → 货币).  What these nodes do is *drive* an
already-existing currency at runtime.

Node ids used here (all server kind 20000, verified against
``data/node-contracts``):

* ``688`` 增加背包货币数量 — add/subtract on a holder's wallet
* ``691`` 获取背包货币数量 — read the current amount
* ``684`` 背包货币数量变化时 — event fired when a wallet changes

The *comparison* half of "钱够不够" is a read (691) fed into one of the shared
comparison nodes (:data:`graphplan.compare.COMPARE_NODES` — the same map items
use), whose bool result drives 双分支 (2):

* ``233`` 数值大于等于 / ``232`` 数值大于 / ``231`` 数值小于等于 / ``230`` 数值小于 /
  ``14`` 是否相等 — two generic operands (3:0 左值, 3:1 右值) and a bool result (4:0 结果)

The one open question is the *slot* used to write a ``货币配置ID`` (the contract
type is ``20`` config-id): :data:`graphplan.paramtypes.CONFIG_ID_SLOT` is
``None`` until a run observes it, so callers pass ``currency_slot`` explicitly.
"""

from __future__ import annotations

from .. import compare as compare_mod
from ..nodes import (
    ADD_BAG_CURRENCY,
    BAG_CURRENCY_CHANGED,
    GET_BAG_CURRENCY,
    Graph,
    Handle,
)

HolderRef = tuple[Handle, str]
"""A wallet holder: ``(handle, role)`` whose data output yields an entity."""


def grant(
    g: Graph,
    src: Handle,
    *,
    holder: HolderRef,
    currency_id: int,
    amount: int,
    currency_slot: str,
    alias: str = "m2_grant",
    from_role: str = "then",
) -> Handle:
    """加钱：``src`` 的执行流触发时，给 ``holder`` 的钱包加 ``amount``。

    ``amount`` may be negative to subtract (the official node takes a signed
    int).  Returns the placed node so the caller can chain its ``then`` output.
    """
    node = g.place(ADD_BAG_CURRENCY, alias)
    src.flow_to(node, from_role)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    node.const("currency", int(currency_id), currency_slot)
    node.const("delta", int(amount), "int")
    return node


def read(
    g: Graph,
    *,
    holder: HolderRef,
    currency_id: int,
    currency_slot: str,
    alias: str = "m2_read",
) -> Handle:
    """查钱：返回一个数据节点，其 ``amount`` 输出是当前货币数量（整数）。"""
    node = g.place(GET_BAG_CURRENCY, alias)
    holder_handle, holder_role = holder
    node.data_from(holder_handle, holder_role, "holder")
    node.const("currency", int(currency_id), currency_slot)
    return node


def on_changed(g: Graph, alias: str = "m2_changed") -> Handle:
    """货币变化事件入口。

    The returned handle is an event node: use ``.flow_to(...)`` to run logic and
    ``.out("delta")`` / ``.out("currency")`` to read what changed.
    """
    return g.place(BAG_CURRENCY_CHANGED, alias)


def read_and_compare(
    g: Graph,
    *,
    holder: HolderRef,
    currency_id: int,
    threshold: int,
    currency_slot: str,
    alias: str,
    compare: str = "gte",
) -> Handle:
    """钱够不够：读 ``holder`` 的 ``currency_id``，再和 ``threshold`` 比。

    Places 获取背包货币数量 (691) and one of the shared comparison nodes
    (``compare``: a key of :data:`graphplan.compare.COMPARE_NODES` — ``"gte"``
    233 / ``"gt"`` 232 / ``"lte"`` 231 / ``"lt"`` 230 / ``"eq"`` 14), wires
    ``691.amount`` (4:0) into the comparator's 左值 (3:0, generic), and
    writes both constants: the currency-id config const on the read, and the
    integer ``threshold`` on the comparator's 右值 (3:1).

    Returns the *comparison* node, whose bool 结果 output (4:0) drives 双分支
    (2)::

        h = currency.read_and_compare(
            g, holder=(src, "entity"), currency_id=1001, threshold=50,
            currency_slot="int", alias="m2_enough",
        )
        branch.data_from(h, "result", "condition")   # bool -> bool, carries

    ``alias`` names the comparator (the returned node); the 691 read is placed
    under ``f"{alias}_read"``.

    The comparator's ``op`` operand-kind enum (3:2) is deliberately left
    unwritten — like the config-id *slot*, its wire value has not been observed
    on the machine, so we do not guess it.
    """
    ntype = compare_mod.resolve(compare)
    read_node = read(
        g,
        holder=holder,
        currency_id=currency_id,
        currency_slot=currency_slot,
        alias=f"{alias}_read",
    )
    cmp_node = g.place(ntype, alias)
    cmp_node.data_from(read_node, "amount", "left")
    cmp_node.const("right", int(threshold), "int")
    return cmp_node


def at_least(
    g: Graph,
    *,
    holder: HolderRef,
    currency_id: int,
    threshold: int,
    currency_slot: str,
    alias: str = "m2_at_least",
) -> Handle:
    """够不够：:func:`read_and_compare` 的 ``gte``（``>=``）便利用法。"""
    return read_and_compare(
        g,
        holder=holder,
        currency_id=currency_id,
        threshold=threshold,
        currency_slot=currency_slot,
        alias=alias,
        compare="gte",
    )
