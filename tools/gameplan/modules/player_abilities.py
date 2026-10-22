"""Reusable player skills, interaction routing and entity state graph fragments.

All node ids and roles come from the server contract store. These functions
author graphs; they do not create skill templates, dispatch, save, or establish
native runtime success. Config-id and boolean storage slots are explicit because
declared types alone do not identify the editor's physical value storage.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ..nodes import BRANCH, EQ, START_TIMER, Graph, Handle, NodeType
from . import currency, item

Ref = tuple[Handle, str]
SKILL_CALLED = NodeType(392, "技能节点调用时", exec_outs={"then": 0},
    outs={"caster": 0, "caster_guid": 1, "parameter1": 2, "parameter2": 3, "parameter3": 4})
CREATE_SKILL = NodeType(809, "创建自定义技能实例", exec_in=0, exec_outs={"then": 0},
    ins={"character": 0, "skill": 1}, outs={"instance_id": 0})
BIND_SKILL = NodeType(806, "绑定自定义技能实例到指定槽位", exec_in=0, exec_outs={"then": 0},
    ins={"character": 0, "instance_id": 1, "skill_slot": 2, "replace_policy": 3},
    outs={"previous_instance_id": 0})
CAST_SKILL = NodeType(817, "施放指定技能实例", exec_in=0, exec_outs={"then": 0},
    ins={"character": 0, "instance_id": 1, "check_conditions": 2})
DESTROY_SKILL = NodeType(810, "销毁自定义技能实例", exec_in=0, exec_outs={"then": 0},
    ins={"character": 0, "instance_id": 1})
QUERY_SKILL = NodeType(811, "以技能实例ID查询技能配置ID",
    ins={"character": 0, "instance_id": 1}, outs={"skill": 0})
SET_STATE = NodeType(22, "设置自定义变量", exec_in=0, exec_outs={"then": 0},
    ins={"target": 0, "name": 1, "value": 2, "is_bp_var": 3, "emit_event": 4})
GET_STATE = NodeType(50, "获取自定义变量",
    ins={"target": 0, "name": 1, "is_bp_var": 2}, outs={"value": 0})
INTEGER = NodeType(257, "获取随机整数", ins={"minimum": 0, "maximum": 1}, outs={"value": 0})
CHARACTER_PLAYER = NodeType(259, "获取角色归属的玩家实体",
    ins={"character": 0}, outs={"player": 0})


def integer(value: int, name: str, *, minimum: int = 0, maximum: int = 2147483647) -> int:
    """Validate native integer ranges without accepting bools or truncating floats."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def config_id(value: int, name: str = "config_id") -> int:
    return integer(value, name, minimum=1, maximum=4294967295)


def config_slot(slot: str) -> str:
    if slot not in ("int", "uint", "enum"):
        raise ValueError("config id slot must be explicit: int, uint or enum")
    return slot


def _flag(node: Handle, role: str, value: bool, slot: str) -> None:
    if type(value) is not bool or slot not in ("bool", "enum"):
        raise ValueError("boolean value and explicit bool/enum storage slot required")
    node.const(role, int(value) if slot == "enum" else value, slot)


def _name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("state/timer name must be nonempty")
    return value


def on_called(g: Graph, alias: str = "ability_called") -> Handle:
    return g.place(SKILL_CALLED, alias)


def owning_player(g: Graph, *, character: Ref, alias: str = "owning_player") -> Handle:
    """Resolve a known character to its player; do not guess an entrant's type."""
    node = g.place(CHARACTER_PLAYER, alias)
    node.data_from(*character, "character")
    return node


def create_instance(g: Graph, src: Handle, *, character: Ref, skill_id: int,
                    skill_id_slot: str, alias: str = "ability_create",
                    from_role: str = "then") -> Handle:
    config_id(skill_id, "skill_id")
    config_slot(skill_id_slot)
    node = g.place(CREATE_SKILL, alias)
    src.flow_to(node, from_role)
    node.data_from(*character, "character")
    node.const("skill", skill_id, skill_id_slot)
    return node


def bind_instance(g: Graph, src: Handle, *, character: Ref, instance: Ref,
                  skill_slot: int, replace_policy: int, alias: str = "ability_bind",
                  from_role: str = "then") -> Handle:
    integer(skill_slot, "skill_slot")
    integer(replace_policy, "replace_policy")
    node = g.place(BIND_SKILL, alias)
    src.flow_to(node, from_role)
    node.data_from(*character, "character")
    node.data_from(*instance, "instance_id")
    node.const("skill_slot", skill_slot, "enum")
    node.const("replace_policy", replace_policy, "enum")
    return node


@dataclass(frozen=True)
class CreatedAbility:
    created: Handle
    bound: Handle


def create_and_bind(g: Graph, src: Handle, *, character: Ref, skill_id: int,
                    skill_id_slot: str, skill_slot: int, replace_policy: int,
                    alias: str = "ability", from_role: str = "then") -> CreatedAbility:
    """Create a runtime instance from an existing skill template and bind it."""
    integer(skill_slot, "skill_slot")
    integer(replace_policy, "replace_policy")
    made = create_instance(g, src, character=character, skill_id=skill_id,
        skill_id_slot=skill_id_slot, alias=f"{alias}_create", from_role=from_role)
    bound = bind_instance(g, made, character=character, instance=(made, "instance_id"),
        skill_slot=skill_slot, replace_policy=replace_policy, alias=f"{alias}_bind")
    return CreatedAbility(made, bound)


def cast_instance(g: Graph, src: Handle, *, character: Ref, instance: Ref,
                  check_conditions: bool, check_slot: str,
                  alias: str = "ability_cast", from_role: str = "then") -> Handle:
    if type(check_conditions) is not bool or check_slot not in ("bool", "enum"):
        raise ValueError("check_conditions and check_slot must be explicit")
    node = g.place(CAST_SKILL, alias)
    src.flow_to(node, from_role)
    node.data_from(*character, "character")
    node.data_from(*instance, "instance_id")
    _flag(node, "check_conditions", check_conditions, check_slot)
    return node


def destroy_instance(g: Graph, src: Handle, *, character: Ref, instance: Ref,
                     alias: str = "ability_destroy", from_role: str = "then") -> Handle:
    node = g.place(DESTROY_SKILL, alias)
    src.flow_to(node, from_role)
    node.data_from(*character, "character")
    node.data_from(*instance, "instance_id")
    return node


def query_instance(g: Graph, *, character: Ref, instance: Ref,
                   alias: str = "ability_query") -> Handle:
    node = g.place(QUERY_SKILL, alias)
    node.data_from(*character, "character")
    node.data_from(*instance, "instance_id")
    return node


def route_refs(g: Graph, src: Handle, *, left: Ref, right: Ref,
               alias: str, from_role: str = "then") -> Handle:
    comparison = g.place(EQ, f"{alias}_equal")
    comparison.data_from(*left, "left")
    comparison.data_from(*right, "right")
    gate = g.place(BRANCH, alias)
    src.flow_to(gate, from_role)
    gate.data_from(comparison, "result", "condition")
    return gate


def route_equal(g: Graph, src: Handle, *, selector: Ref, expected: int | str,
                value_slot: str, alias: str, from_role: str = "then") -> Handle:
    """Route one event without a second competing event entry.

    The selector must have a concrete type (event index or string parameter).
    For a generic integer variable use route_integer, which supplies an anchor.
    """
    if value_slot == "int":
        integer(expected, "expected", minimum=-2147483647)
    elif value_slot != "string" or not isinstance(expected, str):
        raise ValueError("route_equal requires an integer or string with matching slot")
    comparison = g.place(EQ, f"{alias}_equal")
    comparison.data_from(*selector, "left")
    comparison.const("right", expected, value_slot)
    gate = g.place(BRANCH, alias)
    src.flow_to(gate, from_role)
    gate.data_from(comparison, "result", "condition")
    return gate


def integer_source(g: Graph, value: int, *, alias: str) -> Handle:
    """Concrete int output; inclusive equal random bounds give exactly value.

    Official query chapter mhwbqlrw655q explicitly includes both bounds. This
    avoids trying to write an unmaterialized generic custom-variable value.
    """
    integer(value, "value", minimum=-2147483647)
    node = g.place(INTEGER, alias)
    node.const("minimum", value, "int")
    node.const("maximum", value, "int")
    return node


def route_integer(g: Graph, src: Handle, *, selector: Ref, expected: int,
                  alias: str, from_role: str = "then") -> Handle:
    value = integer_source(g, expected, alias=f"{alias}_value")
    # Wire the concrete side first so the native editor has an integer anchor.
    return route_refs(g, src, left=(value, "value"), right=selector,
        alias=alias, from_role=from_role)


def read_state(g: Graph, *, target: Ref, name: str, flag_slot: str,
               alias: str) -> Handle:
    _name(name)
    if flag_slot not in ("bool", "enum"):
        raise ValueError("flag_slot must be bool or enum")
    node = g.place(GET_STATE, alias)
    node.data_from(*target, "target")
    node.const("name", name, "string")
    _flag(node, "is_bp_var", False, flag_slot)
    return node


def set_state(g: Graph, src: Handle, *, target: Ref, name: str, value: int,
              flag_slot: str, alias: str, from_role: str = "then") -> Handle:
    _name(name)
    if flag_slot not in ("bool", "enum"):
        raise ValueError("flag_slot must be bool or enum")
    anchor = integer_source(g, value, alias=f"{alias}_value")
    node = g.place(SET_STATE, alias)
    src.flow_to(node, from_role)
    node.data_from(*target, "target")
    node.data_from(anchor, "value", "value")
    node.const("name", name, "string")
    _flag(node, "is_bp_var", False, flag_slot)
    _flag(node, "emit_event", False, flag_slot)
    return node


def start_once(g: Graph, src: Handle, *, target: Ref, context_guid: Ref,
               name: str, seconds: float, alias: str,
               from_role: str = "then") -> Handle:
    """Arm one real timer point. The sequence is an explicit float container."""
    _name(name)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds must be positive and finite")
    node = g.place(START_TIMER, alias)
    src.flow_to(node, from_role)
    node.data_from(*target, "target")
    node.data_from(*context_guid, "context_guid")
    node.const("name", name, "string")
    _flag(node, "loop", False, "enum")  # 79's enum-backed bool is source-proven.
    g.plan.list_const(node.alias, node.ntype.ins["sequence"], [{"float": float(seconds)}])
    return node


@dataclass(frozen=True)
class Exchange:
    gate: Handle  # false means insufficient source inventory
    consumed: Handle
    granted: Handle


def guarded_item_exchange(g: Graph, src: Handle, *, holder: Ref, source_id: int,
                          cost: int, reward_id: int, reward_count: int,
                          item_slot: str, reward_slot: str, reward_currency: bool,
                          alias: str, from_role: str = "then") -> Exchange:
    """Check inventory, then consume and grant serially.

    This is not an engine transaction: 686 has no success output, and capacity,
    unknown templates, or concurrent engine activity still need live validation.
    """
    config_id(source_id, "source_id")
    config_id(reward_id, "reward_id")
    integer(cost, "cost", minimum=1)
    integer(reward_count, "reward_count", minimum=1)
    config_slot(item_slot)
    config_slot(reward_slot)
    if type(reward_currency) is not bool:
        raise ValueError("reward_currency must be bool")
    enough = item.has_enough(g, holder=holder, item_id=source_id, threshold=cost,
        item_slot=item_slot, alias=f"{alias}_enough")
    gate = g.place(BRANCH, f"{alias}_gate")
    src.flow_to(gate, from_role)
    gate.data_from(enough, "result", "condition")
    consumed = item.grant(g, gate, holder=holder, item_id=source_id, count=-cost,
        item_slot=item_slot, alias=f"{alias}_consume", from_role="true")
    if reward_currency:
        granted = currency.grant(g, consumed, holder=holder, currency_id=reward_id,
            amount=reward_count, currency_slot=reward_slot, alias=f"{alias}_reward")
    else:
        granted = item.grant(g, consumed, holder=holder, item_id=reward_id,
            count=reward_count, item_slot=reward_slot, alias=f"{alias}_reward")
    return Exchange(gate, consumed, granted)
