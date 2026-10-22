"""M1 — interaction points (交互点).

An interaction point is the *event entry* every other module hangs off: M3/M5
run "when the player interacts", so this module is the shared trigger source.

**Five** official interaction entries exist (`.runtime/scratch/INTERACTION-SERVER-HALF.md`
§1 — a census over the official corpus plus the 500-def contract store — and
``docs/research/game-b-systems-20261009/M1-interaction.md``): four have an event node,
the fifth (loot pickup) does not:

===================  ==========================================================
family               event node
===================  ==========================================================
proximity            进入碰撞触发器时 ``92`` / 离开碰撞触发器时 ``91``
UI button group      界面控件组触发时 ``316``
floating page        悬浮交互页操作触发时 ``826``
text bubble (NPC)    文本气泡完成时 ``679``
loot pickup          掉落物拾取 — **no dedicated event node** (see below)
===================  ==========================================================

**The honest limit.** The event *node* can be added to a graph, but the thing
that makes it fire lives elsewhere and this project cannot write it:

* proximity needs a ``碰撞触发器`` component **configured on an entity** — and
  the bridge has no component/property writer at all;
* UI controls need a UI layout authored in the editor;
* the floating page needs a 悬浮交互页 configured in the editor;
* the text bubble needs a ``文本气泡`` component on the entity that speaks.

So :func:`proximity_enter` etc. give you the graph half.  The scene half is a
manual editor step, and ``PENDING-EDITOR-STEP`` is recorded so no caller mistakes
"the node exists" for "the interaction works".

**Loot pickup has no event node of its own.**  A same-instrument census of every
event node in the 500-def contract store (an execution output, no execution input)
finds **no** loot-pickup event: the 拾取规则 (交互拾取 / 自动拾取 / …) is a property
of the ``掉落物内容组件`` on a dropped-item entity, and the pickup is only *observed*
through the generic ``681 背包道具新增时`` event — which the item module already wraps
(:func:`modules.item.on_added`).  So there is no ``InteractionKind`` for it and no
block can be assembled; :class:`blocks.LootPickupHasNoEventNode` (raised by
:func:`blocks.loot_pickup_block`) records that as a named impossibility.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import (
    FLOATING_PAGE_TRIGGERED,
    PROXIMITY_ENTER,
    PROXIMITY_LEAVE,
    UI_CONTROL_TRIGGERED,
    Graph,
    Handle,
    NodeType,
)

# ---------------------------------------------------------------------------
# Node types for the text-bubble entry (679) and its action sibling (631).
#
# They live here, not in ``nodes.py``, because this wave owns only the two M1
# files; the roles are re-derived from ``data/node-contracts`` exactly like
# every ``nodes.py`` row by ``tests/test_interaction_entries.py`` (which asserts
# the declared roles equal the contract's own port indices and param types).
# ---------------------------------------------------------------------------

#: ``679 文本气泡完成时`` — an **event** (exec out, no exec in): the text-bubble
#: entry.  Its ``bubble_id`` output is a config-id (contract type 20) and
#: ``count`` the completion tally.
TEXT_BUBBLE_COMPLETED = NodeType(
    679,
    "文本气泡完成时",
    exec_outs={"then": 0},
    outs={"owner": 0, "character": 1, "bubble_id": 2, "count": 3},
)

#: ``631 切换生效的文本气泡`` — the text-bubble entry's **action** node (exec in
#: AND out), the sibling ``679`` chains to.  ``bubble_id`` is a config-id
#: (contract type 20) whose write *slot* is still unproven
#: (``paramtypes.CONFIG_ID_SLOT is None``), so callers pass the slot explicitly.
SWITCH_TEXT_BUBBLE = NodeType(
    631,
    "切换生效的文本气泡",
    exec_in=0,
    exec_outs={"then": 0},
    ins={"target": 0, "bubble_id": 1},
)


@dataclass(frozen=True)
class InteractionKind:
    key: str
    label: str
    event_definition_id: int
    scene_half: str  # the manual editor step this kind requires


PROXIMITY = InteractionKind(
    "proximity",
    "进入碰撞触发器时",
    92,
    "在目标实体上添加并配置一个「碰撞触发器」组件（本工程无组件写入入口，须在编辑器手工完成）",
)
PROXIMITY_EXIT = InteractionKind(
    "proximity-exit",
    "离开碰撞触发器时",
    91,
    "同 proximity：需要实体上的碰撞触发器组件",
)
UI_BUTTON = InteractionKind(
    "ui-button",
    "界面控件组触发时",
    316,
    "在编辑器里搭好界面控件组（本工程无 UI 写入入口）",
)
FLOATING_PAGE = InteractionKind(
    "floating-page",
    "悬浮交互页操作触发时",
    826,
    "在编辑器里配置悬浮交互页",
)
TEXT_BUBBLE = InteractionKind(
    "text-bubble",
    "文本气泡完成时",
    679,
    "在目标实体上添加并配置一个「文本气泡」组件（本工程无组件写入入口，须在编辑器手工完成）",
)

KINDS = {
    k.key: k
    for k in (PROXIMITY, PROXIMITY_EXIT, UI_BUTTON, FLOATING_PAGE, TEXT_BUBBLE)
}


def event(g: Graph, kind: InteractionKind, alias: str) -> Handle:
    """Place the interaction event node for ``kind`` under ``alias``."""
    if kind.key == "proximity":
        return g.place(PROXIMITY_ENTER, alias)
    if kind.key == "proximity-exit":
        return g.place(PROXIMITY_LEAVE, alias)
    if kind.key == "ui-button":
        return g.place(UI_CONTROL_TRIGGERED, alias)
    if kind.key == "floating-page":
        return g.place(FLOATING_PAGE_TRIGGERED, alias)
    if kind.key == "text-bubble":
        return g.place(TEXT_BUBBLE_COMPLETED, alias)
    raise KeyError(f"unknown interaction kind {kind.key!r}")


def proximity_enter(g: Graph, alias: str = "m1_enter") -> Handle:
    """进入碰撞触发器时。``entrant`` 出参是进入的玩家/单位实体。"""
    return g.place(PROXIMITY_ENTER, alias)


def proximity_leave(g: Graph, alias: str = "m1_leave") -> Handle:
    """离开碰撞触发器时。"""
    return g.place(PROXIMITY_LEAVE, alias)


def ui_control_triggered(g: Graph, alias: str = "m1_ui") -> Handle:
    """界面控件组触发时。``entity`` 出参是事件源实体。"""
    return g.place(UI_CONTROL_TRIGGERED, alias)


def floating_page_triggered(g: Graph, alias: str = "m1_page") -> Handle:
    """悬浮交互页操作触发时。"""
    return g.place(FLOATING_PAGE_TRIGGERED, alias)


def text_bubble_completed(g: Graph, alias: str = "m1_bubble") -> Handle:
    """文本气泡完成时。

    Event entry (``679``): ``owner`` 出参是气泡归属者实体、``character`` 是角色实体、
    ``bubble_id`` 是文本气泡配置ID、``count`` 是完成次数。  ``then`` 是执行输出。
    """
    return g.place(TEXT_BUBBLE_COMPLETED, alias)


def switch_text_bubble(
    g: Graph,
    src: Handle,
    *,
    target: tuple[Handle, str],
    bubble_id: int,
    bubble_id_slot: str,
    alias: str = "m1_switch_bubble",
    from_role: str = "then",
) -> Handle:
    """切换生效的文本气泡（``631``）：``src`` 的执行流触发时，切换 ``target`` 上生效的气泡。

    ``target`` is a ``(handle, role)`` pair whose data output yields an entity (the
    entity that carries the 文本气泡 component).  ``bubble_id_slot`` names the slot
    used for the ``文本气泡配置ID`` config-id (contract type 20); that slot is
    **unproven on the machine** (``paramtypes.CONFIG_ID_SLOT is None``), so the
    caller must pass it explicitly — the module never guesses it.
    """
    node = g.place(SWITCH_TEXT_BUBBLE, alias)
    src.flow_to(node, from_role)
    target_handle, target_role = target
    node.data_from(target_handle, target_role, "target")
    node.const("bubble_id", int(bubble_id), bubble_id_slot)
    return node
