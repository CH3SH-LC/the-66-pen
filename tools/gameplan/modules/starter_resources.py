"""One starter-package attempt per character custom-variable lifetime.

The host supplies an execution source and a known *character* entity reference
after that character's bag is ready. This fragment installs no event: server 71
is generic entity creation, and 281 is character revival, not first admission.
Official local chapters mh3ecor1x5cm / mhctmgi51lpo distinguish the character's
bag from the logical player; mh796lr44x0e documents revival. mh1w3z96rpne says a
missing custom variable returns the selected type's default (integer zero).
Official mhso1b9wjica allows server setters to create custom variables dynamically;
these guard names therefore need no additional preset variable declaration.

guard_name is an explicit, shared package key on the character, never global or
on the plot. Zero permits one attempt; every other value skips. Mark one BEFORE
issuing 686/688, suppressing repeated entry and later revival of that same
character. The host must not reset it on death or entry. A destroyed/recreated
character has a new variable lifetime and is eligible again: this is NOT a
per-player, reconnect-persistent reward system. Only invoke for the intended
initial character lifetime if the game replaces characters on respawn.

Bag templates and capacity must already be valid. Grant nodes expose no success
output, so a failed/partial grant leaves the guard claimed and is not retried.
This avoids duplicate currency; it is not an atomic transaction or a receipt.
Native spawning, variable persistence and successful delivery remain unverified.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts import DATA_OUTPUT, default_store
from ..nodes import Graph, Handle
from . import currency, item, player_abilities as abilities

PortRef = tuple[Handle, str]


@dataclass(frozen=True)
class StarterResources:
    gate: Handle  # false: already claimed; caller may continue without rewards
    claimed: Handle  # marks the character before either grant
    last: Handle  # then: completed the first attempt, including an empty package
    seed_grant: Handle | None
    currency_grant: Handle | None


def grant_once(g: Graph, src: Handle, *, character: PortRef,
               seed_id: int, currency_id: int, item_slot: str, currency_slot: str,
               variable_flag_slot: str, guard_name: str,
               seed_count: int = 3, currency_amount: int = 20,
               alias: str = "starter", from_role: str = "then") -> StarterResources:
    """Compose guard -> mark -> seed -> currency, with zero grants omitted.

    Connect ``result.last.then`` and ``result.gate.false`` to the same subsequent
    action when both first and repeat interactions should continue. Use the same
    guard_name for the same package across all plot/interaction graphs. Counts
    are additive one-time grants, not inventory minimums that refill after use.
    Explicit config slots must match live descriptors at dispatch time.
    """
    abilities.config_id(seed_id, "seed_id")
    abilities.config_id(currency_id, "currency_id")
    abilities.config_slot(item_slot)
    abilities.config_slot(currency_slot)
    abilities.integer(seed_count, "seed_count")
    abilities.integer(currency_amount, "currency_amount")
    if variable_flag_slot not in ("bool", "enum"):
        raise ValueError("variable_flag_slot must be explicit bool or enum")
    if not isinstance(guard_name, str) or not guard_name.strip() or "\0" in guard_name:
        raise ValueError("guard_name must be an explicit nonempty character variable name")
    if not isinstance(src, Handle) or src.graph is not g or from_role not in src.ntype.exec_outs:
        raise ValueError("src must have the requested execution output in this graph")
    if (not isinstance(character, tuple) or len(character) != 2
            or not isinstance(character[0], Handle) or character[0].graph is not g
            or character[1] not in character[0].ntype.outs):
        raise ValueError("character must be a data output reference in this graph")
    target, role = character
    port = default_store().require(target.ntype.definition_id).port(
        DATA_OUTPUT, target.ntype.outs[role])
    if port is None or port.server_param_type != 1:
        raise ValueError("character reference must output an entity, not a GUID or player ID")

    state = abilities.read_state(g, target=character, name=guard_name,
        flag_slot=variable_flag_slot, alias=f"{alias}_state")
    gate = abilities.route_integer(g, src, selector=(state, "value"), expected=0,
        alias=f"{alias}_unclaimed", from_role=from_role)
    claimed = abilities.set_state(g, gate, target=character, name=guard_name, value=1,
        flag_slot=variable_flag_slot, alias=f"{alias}_claim", from_role="true")
    last = claimed
    seeds = money = None
    if seed_count:
        seeds = item.grant(g, last, holder=character, item_id=seed_id, count=seed_count,
            item_slot=item_slot, alias=f"{alias}_seeds")
        last = seeds
    if currency_amount:
        money = currency.grant(g, last, holder=character, currency_id=currency_id,
            amount=currency_amount, currency_slot=currency_slot, alias=f"{alias}_currency")
        last = money
    return StarterResources(gate, claimed, last, seeds, money)
