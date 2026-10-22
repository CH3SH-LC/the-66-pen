"""Player-side UI interaction, not a raw keyboard event.

Official mhwkfsitckrw: an interaction-event button emits 316 only to the
triggering player's graph. Its keyboard mapping is a separate UI asset.
316 provides group/combo indices, not a key code or button ID. A caller must
bind one UI control to Z and attach this graph to the player before deployment.
No Unity/WPF/ASCII key value is substituted for the UI configuration enum.
"""
from dataclasses import dataclass
import math

from ..nodes import BRANCH, LE, UI_CONTROL_TRIGGERED, Graph, Handle
from . import player_abilities as abilities
from .distance_interaction import AT, CHARACTERS, DISTANCE, LENGTH, POSITION, VECTOR

Ref = tuple[Handle, str]


@dataclass(frozen=True)
class ControlEntry:
    event: Handle
    gate: Handle
    player: Ref


@dataclass(frozen=True)
class CharacterEntry:
    gate: Handle
    character: Ref


def on_control(g: Graph, *, group_index: int, group_combo_index: int | None = None,
               alias: str = "interact") -> ControlEntry:
    """Filter 316 by actual UI indices; gate.true is the requested interaction.

    For a single-control group, pass its actual group_index and leave combo None.
    Composite layouts require the explicit observed combo index. This API does
    not resolve UI indices, create the control, or bind a keyboard key.
    """
    abilities.integer(group_index, "group_index", minimum=1)
    if group_combo_index is not None:
        abilities.integer(group_combo_index, "group_combo_index", minimum=1)
    event = g.place(UI_CONTROL_TRIGGERED, alias)
    gate = abilities.route_equal(g, event, selector=(event, "group_index"),
        expected=group_index, value_slot="int", alias=alias + "_group")
    if group_combo_index is not None:
        gate = abilities.route_equal(g, gate, selector=(event, "group_combo_index"),
            expected=group_combo_index, value_slot="int", alias=alias + "_combo",
            from_role="true")
    return ControlEntry(event, gate, (event, "entity"))


def character_for_player(g: Graph, src: Handle, *, player: Ref,
                         alias: str = "key_character", from_role: str = "true") -> CharacterEntry:
    """Resolve exactly one character; never use a player as a bag holder.

    258 returns character entities. Its 128 output goes directly to entity
    consumers. Zero/multiple characters stop at gate.false; no character GUID
    round trip is valid or necessary.
    """
    characters = g.place(CHARACTERS, alias + "_list")
    characters.data_from(*player, "player")
    count = g.place(LENGTH, alias + "_count")
    count.data_from(characters, "characters", "list")
    gate = abilities.route_equal(g, src, selector=(count, "length"), expected=1,
        value_slot="int", alias=alias + "_single", from_role=from_role)
    character = g.place(AT, alias)
    character.data_from(characters, "characters", "list")
    character.const("index", 0, "int")
    return CharacterEntry(gate, (character, "value"))


def near(g: Graph, src: Handle, *, character: Ref, center, radius: float,
         alias: str, from_role: str = "true") -> Handle:
    """Sample character position when an explicit action fires; no entry timer."""
    if (not isinstance(center, (list, tuple)) or len(center) != 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in center)):
        raise ValueError("center must contain three finite coordinates")
    if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
        raise ValueError("radius must be finite and positive")
    position = g.place(POSITION, alias + "_position")
    position.data_from(*character, "entity")
    point = g.place(VECTOR, alias + "_center")
    for axis, value in zip(("x", "y", "z"), center):
        point.const(axis, float(value), "float")
    distance = g.place(DISTANCE, alias + "_distance")
    distance.data_from(position, "position", "a")
    distance.data_from(point, "value", "b")
    compare = g.place(LE, alias + "_compare")
    compare.data_from(distance, "distance", "left")
    compare.const("right", float(radius), "float")
    gate = g.place(BRANCH, alias)
    src.flow_to(gate, from_role)
    gate.data_from(compare, "result", "condition")
    return gate
