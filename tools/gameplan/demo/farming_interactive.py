"""Entity-backed farming: empty -> growing -> ripe -> harvest; sell crops.

Bind this graph to an entity with its default custom-variable component and two
configured collision trigger indices: farm and sell. One proximity event routes
by index, and each event is filtered to the graph's own entity. Plot state is on
the entity, so it is shared by players. The physical entrant is the default bag
holder: official nodes 686/688/690 address the entity owning the bag component,
and the character component list includes a bag while the player list does not.
The explicit ``character_owner`` policy remains available for independently
verified integrations; converting with node 259 does not give a player a bag.
No item is used as a proxy for plot state. The timer supplies growth.

``interaction_mode='skill'`` replaces the proximity event with skill callback
392. Configure a character skill's notification with parameter1 exactly
``plant`` (also harvests when ripe) or ``sell``, and parameter2 equal to this
plot's unique, explicit ``skill_target``. Other actions/targets are ignored.
The caller character owns the bag; its GUID supplies timer context. The target
string filters a received event, not the engine's event delivery. Which entity
graphs receive 392 still requires native verification. No skill template is
created or bound here; an existing configured notification is a prerequisite.

``interaction_mode='distance'`` polls actual character positions, using explicit
world-space farm/sell centers. Each player must have exactly one character in
258's result; zero/multiple characters are ignored. A per-character variable
with the explicit host_key allows one interaction per visit, until the player
leaves both exit spheres. Standing still cannot repeat, including after growth.
The polling timer is independent of the crop timer. No collision component or
skill notification is required; native movement/runtime still needs acceptance.

Existing seed/crop/currency templates, a configured bag on the entering character,
and, for proximity mode, scene triggers filtered to those characters are prerequisites.
``sale_mode='direct'`` exchanges the configured crop batch for currency.
``native_shop`` installs seed sales and crop buyback rows once on owner creation,
then opens the existing native shop for the entrant's owning player. It requires
a shop component on this graph's entity, referencing a custom-list shop template
at ``shop_index``; it creates neither that component nor the template. Seed and
crop prices in this mode are per item; ``sale_count`` applies only to direct mode.
The engine handles native transactions; the graph adds no second payment.
Optional starter counts add one package attempt on the first valid farm/sell
interaction. It requires the entrant inventory policy so both starter delivery
and farming use the same character bag. All plots use the same character
guard by default. Re-entry and revival of that same character do not refill it;
a replaced character has a new variable lifetime. The guard is set before grants
and remains set after partial failure, with no automatic retry. It is not a
per-player persistent entitlement. Both counts default to zero (no added nodes).
This file authors real contracted nodes but does not prove native play, save/reopen or
cross-player transaction atomicity. Boolean/config storage slots must be chosen
from live descriptors by the dispatching caller. No game operation runs here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .. import economy_catalog
from ..modules import distance_interaction, item, player_abilities as abilities, shop, starter_resources
from ..nodes import BRANCH, ON_CREATE, PRINT, PROXIMITY_ENTER, SELF, TIMER_TICK, Graph, Handle
from ..plan import GraphPlan

EMPTY, GROWING, RIPE = 0, 1, 2


@dataclass(frozen=True)
class FarmInteractiveConfig:
    seed_id: int
    crop_id: int
    currency_id: int
    item_slot: str
    currency_slot: str
    variable_flag_slot: str
    growth_seconds: float = 10.0
    seed_cost: int = 1
    harvest_gain: int = 1
    sale_count: int = 1
    sale_price: int = 10
    farm_trigger_index: int = 1
    sell_trigger_index: int = 2
    state_name: str = "mw_farm_stage"
    timer_name: str = "mw_farm_growth"
    inventory_holder: str = "entrant"
    sale_mode: str = "direct"
    seed_price: int = 2
    shop_index: int = 1
    shop_flag_slot: str | None = None
    interaction_mode: str = "proximity"
    skill_target: str | None = None
    starter_seed_count: int = 0
    starter_currency_amount: int = 0
    starter_guard: str = "MW_FARM_STARTER_V1"
    farm_center: tuple[float, float, float] | None = None
    sell_center: tuple[float, float, float] | None = None
    interaction_radius: float | None = None
    exit_radius: float | None = None
    poll_seconds: float = 0.25
    host_key: str | None = None

    def __post_init__(self) -> None:
        for name in ("seed_id", "crop_id", "currency_id"):
            abilities.config_id(getattr(self, name), name)
        if self.seed_id == self.crop_id:
            raise ValueError("seed and crop item ids must differ")
        for name in ("seed_cost", "harvest_gain", "sale_count", "sale_price", "seed_price"):
            abilities.integer(getattr(self, name), name, minimum=1)
        for name in ("farm_trigger_index", "sell_trigger_index", "shop_index"):
            # Native authoring allocates these identifiers from 1, not from
            # the entry's zero-based list position. Use actual readback IDs
            # when configuring a scene that already contains entries.
            abilities.integer(getattr(self, name), name, minimum=1)
        for name in ("starter_seed_count", "starter_currency_amount"):
            abilities.integer(getattr(self, name), name)
        if (not isinstance(self.starter_guard, str) or not self.starter_guard.strip()
                or "\0" in self.starter_guard):
            raise ValueError("starter_guard must be a nonempty character variable name")
        if self.farm_trigger_index == self.sell_trigger_index:
            raise ValueError("farm and sell trigger indices must differ")
        for slot in (self.item_slot, self.currency_slot):
            abilities.config_slot(slot)
        if self.variable_flag_slot not in ("bool", "enum"):
            raise ValueError("variable_flag_slot must be explicit bool or enum")
        if self.inventory_holder not in ("entrant", "character_owner"):
            raise ValueError("inventory_holder must be entrant or character_owner")
        if ((self.starter_seed_count or self.starter_currency_amount)
                and self.inventory_holder != "entrant"):
            raise ValueError("STARTER_REQUIRES_CHARACTER_INVENTORY: enabled starter resources "
                             "require inventory_holder='entrant' so grants and farming use the same bag")
        if self.interaction_mode not in ("proximity", "skill", "distance"):
            raise ValueError("interaction_mode must be proximity, skill or distance")
        if self.interaction_mode == "distance":
            distance_interaction.validate(farm_center=self.farm_center, sell_center=self.sell_center,
                interaction_radius=self.interaction_radius, exit_radius=self.exit_radius,
                poll_seconds=self.poll_seconds, host_key=self.host_key)
            if self.inventory_holder != "entrant":
                raise ValueError("distance mode requires the located character as inventory_holder")
        if self.skill_target is not None and (not isinstance(self.skill_target, str)
                                             or not self.skill_target.strip()):
            raise ValueError("skill_target must be a nonempty string when supplied")
        if self.interaction_mode == "skill":
            if self.skill_target is None:
                raise ValueError("skill mode requires an explicit unique skill_target")
            if self.inventory_holder != "entrant":
                raise ValueError("skill mode requires the caller character as inventory_holder")
        if self.sale_mode not in ("direct", "native_shop"):
            raise ValueError("sale_mode must be direct or native_shop")
        if self.shop_flag_slot not in (None, "bool", "enum"):
            raise ValueError("shop_flag_slot must be bool or enum when supplied")
        if self.sale_mode == "native_shop":
            if self.shop_flag_slot is None:
                raise ValueError("native_shop requires an explicit shop_flag_slot")
            if self.item_slot not in ("int", "uint"):
                raise ValueError("native_shop catalog item_slot must be int or uint")
        if (type(self.growth_seconds) not in (float, int)
                or not math.isfinite(self.growth_seconds) or self.growth_seconds <= 0):
            raise ValueError("growth_seconds must be positive and finite")
        for name in (self.state_name, self.timer_name):
            if not isinstance(name, str) or not name.strip():
                raise ValueError("state and timer names must be nonempty")


def _note(g: Graph, src: Handle, alias: str, text: str, role: str = "then") -> Handle:
    node = g.place(PRINT, alias)
    src.flow_to(node, role)
    node.const("text", text, "string")
    return node


def build(config: FarmInteractiveConfig, name: str = "MW_API_FARM_INTERACTIVE") -> Graph:
    g = Graph(name)
    own = g.place(SELF, "self")
    plot = (own, "self")

    # Initialize only this graph's entity. Runtime state deliberately resets on
    # entity creation; no persistence across a new play session is claimed.
    created = g.place(ON_CREATE, "created")
    init_owner = abilities.route_refs(g, created, left=(created, "entity"),
        right=plot, alias="init_owner")
    initialized = abilities.set_state(g, init_owner, target=plot, name=config.state_name,
        value=EMPTY, flag_slot=config.variable_flag_slot, alias="initialize", from_role="true")
    if config.sale_mode == "native_shop":
        catalog = economy_catalog.install_catalog(g, initialized, shop_owner=plot,
            shop_index=config.shop_index,
            sales=[economy_catalog.SaleProduct(config.seed_id,
                {config.currency_id: config.seed_price})],
            purchases=[economy_catalog.PurchaseProduct(config.crop_id,
                {config.currency_id: config.sale_price})],
            item_slot=config.item_slot, flag_slot=config.shop_flag_slot,
            alias="farm_catalog")
        initialized = catalog.last
    if config.interaction_mode == "distance":
        initialized = distance_interaction.start(g, initialized, plot=plot,
            context_guid=(created, "guid"), timer_name=config.timer_name + "_poll",
            seconds=config.poll_seconds)
    _note(g, initialized, "initialized_note", "FARM_READY")

    if config.interaction_mode == "distance":
        distance = distance_interaction.build(g, plot=plot, farm_center=config.farm_center,
            sell_center=config.sell_center, interaction_radius=config.interaction_radius,
            exit_radius=config.exit_radius, host_key=config.host_key,
            timer_name=config.timer_name + "_poll", flag_slot=config.variable_flag_slot)
        holder, context_guid = distance.character, distance.guid
    elif config.interaction_mode == "skill":
        entered = abilities.on_called(g, "interact")
        holder = (entered, "caster")
        context_guid = (entered, "caster_guid")
    else:
        entered = g.place(PROXIMITY_ENTER, "interact")
        holder = (entered, "entrant")
        context_guid = (entered, "entrant_guid")
    starter_character = holder
    if config.inventory_holder == "character_owner" or config.sale_mode == "native_shop":
        player = abilities.owning_player(g, character=holder, alias="interacting_player")
    if config.inventory_holder == "character_owner":
        holder = (player, "player")
    if config.interaction_mode == "distance":
        farm, sell = distance.farm, distance.sell
    elif config.interaction_mode == "skill":
        owns = abilities.route_equal(g, entered, selector=(entered, "parameter2"),
            expected=config.skill_target, value_slot="string", alias="interaction_owner")
        farm = abilities.route_equal(g, owns, selector=(entered, "parameter1"),
            expected="plant", value_slot="string", alias="farm_route", from_role="true")
        sell = abilities.route_equal(g, farm, selector=(entered, "parameter1"),
            expected="sell", value_slot="string", alias="sell_route", from_role="false")
    else:
        owns = abilities.route_refs(g, entered, left=(entered, "trigger"), right=plot,
            alias="interaction_owner")
        farm = abilities.route_equal(g, owns, selector=(entered, "trigger_index"),
            expected=config.farm_trigger_index, value_slot="int", alias="farm_route", from_role="true")
        sell = abilities.route_equal(g, farm, selector=(entered, "trigger_index"),
            expected=config.sell_trigger_index, value_slot="int", alias="sell_route", from_role="false")

    if config.starter_seed_count or config.starter_currency_amount:
        # Only the two validated actions reach this single character guard.
        # Never initialize/reset it from the plot's creation or revival events.
        starter = starter_resources.grant_once(g, farm, character=starter_character,
            seed_id=config.seed_id, currency_id=config.currency_id,
            item_slot=config.item_slot, currency_slot=config.currency_slot,
            variable_flag_slot=config.variable_flag_slot, guard_name=config.starter_guard,
            seed_count=config.starter_seed_count, currency_amount=config.starter_currency_amount,
            alias="starter", from_role="true")
        sell.flow_to(starter.gate, "true")
        selector = (distance.selector if config.interaction_mode == "distance" else
                    (entered, "parameter1" if config.interaction_mode == "skill" else "trigger_index"))
        value_slot = "string" if config.interaction_mode == "skill" else "int"
        farm = abilities.route_equal(g, starter.last, selector=selector,
            expected=("plant" if config.interaction_mode == "skill" else
                      1 if config.interaction_mode == "distance" else config.farm_trigger_index),
            value_slot=value_slot, alias="starter_resume_farm")
        starter.gate.flow_to(farm, "false")
        sell = abilities.route_equal(g, farm, selector=selector,
            expected=("sell" if config.interaction_mode == "skill" else
                      2 if config.interaction_mode == "distance" else config.sell_trigger_index),
            value_slot=value_slot, alias="starter_resume_sell", from_role="false")

    state = abilities.read_state(g, target=plot, name=config.state_name,
        flag_slot=config.variable_flag_slot, alias="plot_state")
    empty = abilities.route_integer(g, farm, selector=(state, "value"), expected=EMPTY,
        alias="is_empty", from_role="true")
    seeds = item.has_enough(g, holder=holder, item_id=config.seed_id,
        threshold=config.seed_cost, item_slot=config.item_slot, alias="have_seeds")
    can_plant = g.place(BRANCH, "can_plant")
    empty.flow_to(can_plant, "true")
    can_plant.data_from(seeds, "result", "condition")
    consumed = item.grant(g, can_plant, holder=holder, item_id=config.seed_id,
        count=-config.seed_cost, item_slot=config.item_slot, alias="consume_seeds", from_role="true")
    growing = abilities.set_state(g, consumed, target=plot, name=config.state_name,
        value=GROWING, flag_slot=config.variable_flag_slot, alias="mark_growing")
    timer = abilities.start_once(g, growing, target=plot, context_guid=context_guid,
        name=config.timer_name, seconds=config.growth_seconds, alias="growth_timer")
    _note(g, timer, "planted_note", "FARM_PLANTED")
    _note(g, can_plant, "no_seed_note", "FARM_NO_SEEDS", "false")

    ripe = abilities.route_integer(g, empty, selector=(state, "value"), expected=RIPE,
        alias="is_ripe", from_role="false")
    cleared = abilities.set_state(g, ripe, target=plot, name=config.state_name,
        value=EMPTY, flag_slot=config.variable_flag_slot, alias="mark_empty", from_role="true")
    harvest = item.grant(g, cleared, holder=holder, item_id=config.crop_id,
        count=config.harvest_gain, item_slot=config.item_slot, alias="harvest")
    _note(g, harvest, "harvest_note", "FARM_HARVESTED")
    _note(g, ripe, "growing_note", "FARM_NOT_RIPE", "false")

    tick = g.place(TIMER_TICK, "growth_tick")
    tick_owner = abilities.route_refs(g, tick, left=(tick, "entity"), right=plot,
        alias="timer_owner")
    clock = abilities.route_equal(g, tick_owner, selector=(tick, "name"),
        expected=config.timer_name, value_slot="string", alias="timer_name", from_role="true")
    tick_state = abilities.read_state(g, target=plot, name=config.state_name,
        flag_slot=config.variable_flag_slot, alias="tick_state")
    pending = abilities.route_integer(g, clock, selector=(tick_state, "value"), expected=GROWING,
        alias="timer_is_growing", from_role="true")
    matured = abilities.set_state(g, pending, target=plot, name=config.state_name,
        value=RIPE, flag_slot=config.variable_flag_slot, alias="mark_ripe", from_role="true")
    _note(g, matured, "ripe_note", "FARM_RIPE")

    if config.sale_mode == "native_shop":
        shop.open_(g, sell, player=(player, "player"), shop_owner=plot,
            shop_index=config.shop_index, alias="open_farm_shop", from_role="true")
    else:
        trade = abilities.guarded_item_exchange(g, sell, holder=holder, source_id=config.crop_id,
            cost=config.sale_count, reward_id=config.currency_id, reward_count=config.sale_price,
            item_slot=config.item_slot, reward_slot=config.currency_slot, reward_currency=True,
            alias="sell", from_role="true")
        _note(g, trade.granted, "sold_note", "FARM_SOLD")
        _note(g, trade.gate, "no_crop_note", "FARM_NO_CROPS", "false")
    return g


def build_plan(config: FarmInteractiveConfig, name: str = "MW_API_FARM_INTERACTIVE") -> GraphPlan:
    graph = build(config, name)
    graph.validate()
    return graph.plan
