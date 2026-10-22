"""Server graph movement entry using real positions and a character/host latch.

248/258/99/244 are from the server contract and official mhwbqlrw655q /
mhnd4l069tk0. 99 cannot locate a player entity; only a sole character returned
by 258 is used. No collision component, client callback, or inferred 804 mode.
The caller supplies world-space centers. Polling observes sampled movement,
not a continuous collision volume. A visit fires once, until the character
leaves both outer radii. The latch is written before downstream actions.
"""
from dataclasses import dataclass
import math
import re

from ..nodes import BRANCH, GT, LE, START_TIMER, TIMER_TICK, Graph, Handle, NodeType
from . import player_abilities as abilities

PLAYERS = NodeType(248, "获取在场玩家实体列表", outs={"players": 0})
EACH = NodeType(509, "列表迭代循环", exec_in=0,
    exec_outs={"body": 0, "done": 1}, ins={"list": 0}, outs={"value": 0})
CHARACTERS = NodeType(258, "获取指定玩家所有角色实体", ins={"player": 0}, outs={"characters": 0})
LENGTH = NodeType(142, "获取列表长度", ins={"list": 0}, outs={"length": 0})
AT = NodeType(128, "获取列表对应值", ins={"list": 0, "index": 1}, outs={"value": 0})
POSITION = NodeType(99, "获取实体位置与旋转", ins={"entity": 0}, outs={"position": 0})
VECTOR = NodeType(225, "创建三维向量", ins={"x": 0, "y": 1, "z": 2}, outs={"value": 0})
DISTANCE = NodeType(244, "两坐标点距离", ins={"a": 0, "b": 1}, outs={"distance": 0})
GUID = NodeType(76, "以实体查询GUID", ins={"entity": 0}, outs={"guid": 0})
ENTITY = NodeType(75, "以GUID查询实体", ins={"guid": 0}, outs={"entity": 0})


def validate(*, farm_center, sell_center, interaction_radius, exit_radius,
             poll_seconds, host_key):
    for label, point in (("farm_center", farm_center), ("sell_center", sell_center)):
        if (not isinstance(point, (tuple, list)) or len(point) != 3 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
            raise ValueError(f"distance mode requires an explicit finite {label} (x,y,z)")
    for label, value in (("interaction_radius", interaction_radius),
                         ("exit_radius", exit_radius), ("poll_seconds", poll_seconds)):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"distance mode requires positive finite {label}")
    if exit_radius <= interaction_radius:
        raise ValueError("exit_radius must exceed interaction_radius for re-entry hysteresis")
    if math.dist(farm_center, sell_center) <= 2 * exit_radius:
        raise ValueError("farm/sell outer spheres must be separated so walking between them rearms entry")
    if not isinstance(host_key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", host_key):
        raise ValueError("distance mode requires an explicit unique host_key (1..64 ASCII letters/digits/_/-)")


def state_name(host_key):
    return "MW_DISTANCE_INSIDE_" + host_key


def start(g, src, *, plot, context_guid, timer_name, seconds):
    timer = g.place(START_TIMER, "poll_timer")
    src.flow_to(timer)
    timer.data_from(*plot, "target")
    timer.data_from(*context_guid, "context_guid")
    timer.const("name", timer_name, "string")
    timer.const("loop", 1, "enum")  # Same source-proven 79 boolean slot as start_once.
    g.plan.list_const(timer.alias, 3, [{"float": float(seconds)}])
    return timer


@dataclass(frozen=True)
class Entry:
    character: tuple[Handle, str]
    guid: tuple[Handle, str]
    selector: tuple[Handle, str]
    farm: Handle
    sell: Handle


def build(g: Graph, *, plot, farm_center, sell_center, interaction_radius,
          exit_radius, host_key, timer_name, flag_slot) -> Entry:
    tick = g.place(TIMER_TICK, "interact")
    owner = abilities.route_refs(g, tick, left=(tick, "entity"), right=plot,
        alias="poll_owner")
    clock = abilities.route_equal(g, owner, selector=(tick, "name"),
        expected=timer_name, value_slot="string", alias="poll_clock", from_role="true")
    players = g.place(PLAYERS, "poll_players")
    each = g.place(EACH, "poll_each_player")
    each.data_from(players, "players", "list")
    clock.flow_to(each, "true")
    characters = g.place(CHARACTERS, "poll_characters")
    characters.data_from(each, "value", "player")
    count = g.place(LENGTH, "poll_character_count")
    count.data_from(characters, "characters", "list")
    single = abilities.route_integer(g, each, selector=(count, "length"),
        expected=1, alias="poll_single_character", from_role="body")
    character = g.place(AT, "poll_character")
    character.data_from(characters, "characters", "list")
    character.const("index", 0, "int")
    guid = g.place(GUID, "poll_character_guid")
    guid.data_from(character, "value", "entity")
    # 128 has a generic output. The identity-preserving 76 -> 75 pair supplies
    # a concrete entity pin to existing character-only fragments and their guards.
    resolved = g.place(ENTITY, "poll_character_entity")
    resolved.data_from(guid, "guid", "guid")
    who = (resolved, "entity")
    position = g.place(POSITION, "poll_character_position")
    position.data_from(*who, "entity")
    distances = []
    for label, center in (("farm", farm_center), ("sell", sell_center)):
        point = g.place(VECTOR, f"poll_{label}_center")
        for axis, value in zip(("x", "y", "z"), center):
            point.const(axis, float(value), "float")
        distance = g.place(DISTANCE, f"poll_{label}_distance")
        distance.data_from(position, "position", "a")
        distance.data_from(point, "value", "b")
        distances.append(distance)
    latch = abilities.read_state(g, target=who, name=state_name(host_key),
        flag_slot=flag_slot, alias="poll_inside")
    armed = abilities.route_integer(g, single, selector=(latch, "value"),
        expected=0, alias="poll_armed", from_role="true")

    def gate(src, role, distance, threshold, outside, alias):
        compare = g.place(GT if outside else LE, alias + "_compare")
        compare.data_from(distance, "distance", "left")
        compare.const("right", float(threshold), "float")
        branch = g.place(BRANCH, alias)
        src.flow_to(branch, role)
        branch.data_from(compare, "result", "condition")
        return branch

    # One latch belongs to this character and host. It remains set even if a
    # downstream operation fails; standing still cannot retry or double-pay.
    farm_near = gate(armed, "true", distances[0], interaction_radius, False, "poll_farm_near")
    sell_near = gate(farm_near, "false", distances[1], interaction_radius, False, "poll_sell_near")
    marked = []
    for alias, branch, value in (("farm", farm_near, 1), ("sell", sell_near, 2)):
        marked.append(abilities.set_state(g, branch, target=who, name=state_name(host_key),
            value=value, flag_slot=flag_slot, alias=f"poll_mark_{alias}", from_role="true"))
    # A separate read is first evaluated after the write. Do not depend on a
    # query node already used by poll_armed being refreshed within one flow.
    action = abilities.read_state(g, target=who, name=state_name(host_key),
        flag_slot=flag_slot, alias="poll_action")
    farm = abilities.route_integer(g, marked[0], selector=(action, "value"),
        expected=1, alias="farm_route")
    marked[1].flow_to(farm)
    sell = abilities.route_integer(g, farm, selector=(action, "value"),
        expected=2, alias="sell_route", from_role="false")
    farm_far = gate(armed, "false", distances[0], exit_radius, True, "poll_farm_far")
    sell_far = gate(farm_far, "true", distances[1], exit_radius, True, "poll_sell_far")
    abilities.set_state(g, sell_far, target=who, name=state_name(host_key), value=0,
        flag_slot=flag_slot, alias="poll_clear", from_role="true")
    return Entry(who, (guid, "guid"), (action, "value"), farm, sell)
