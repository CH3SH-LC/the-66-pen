"""Manual farm graph fragment with observed inventory deltas.

The caller routes a deliberate interaction to ``install``; proximity and growth
never grant items.  State and before/after counts live on the real plot entity.
686 has no result, so 690 is captured with 22 both before and after each change.
Only an exact -1/+1 confirms planting/harvesting. An unchanged bag restores the
previous stage; any other delta remains locked for inspection, with no replay.
This is graph composition, not an engine transaction or proof of synchronous
native readback. That ordering, full-bag rejection and timer delivery require
runtime acceptance. No capacity node is treated as a remaining-space query.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from ..nodes import ADD, BRANCH, GE, PRINT, TIMER_TICK, Graph, Handle
from . import item, player_abilities as a

EMPTY, GROWING, RIPE, MUTATING, UNCERTAIN = range(5)
Ref = tuple[Handle, str]


@dataclass(frozen=True)
class FarmConfig:
    plot_id: int
    seed_id: int
    crop_id: int
    item_slot: str
    variable_flag_slot: str
    growth_seconds: float = 10.0

    def __post_init__(self):
        for name in ("plot_id", "seed_id", "crop_id"):
            a.config_id(getattr(self, name), name)
        if self.seed_id == self.crop_id:
            raise ValueError("seed_id and crop_id must differ")
        if self.item_slot not in ("uint", "int"):
            raise ValueError("item_slot must explicitly be uint or int")
        if self.variable_flag_slot not in ("bool", "enum"):
            raise ValueError("variable_flag_slot must explicitly be bool or enum")
        if (type(self.growth_seconds) not in (int, float)
                or not math.isfinite(self.growth_seconds) or self.growth_seconds <= 0):
            raise ValueError("growth_seconds must be positive and finite")

    @property
    def state_name(self):
        return f"MW_MANUAL_FARM_STAGE_{self.plot_id}"

    @property
    def timer_name(self):
        return f"MW_MANUAL_FARM_GROW_{self.plot_id}"


@dataclass(frozen=True)
class FarmFragment:
    action: Handle
    timer_event: Handle
    planted: Handle
    ripe: Handle
    harvested: Handle
    no_seed: Handle
    bag_unchanged: Handle
    uncertain: tuple[Handle, Handle]


def install(g: Graph, src: Handle, *, character: Ref, plot: Ref,
            timer_owner: Ref, plot_guid: Ref, config: FarmConfig,
            alias: str = "farm", from_role: str = "true") -> FarmFragment:
    """Compose one plot's manual action and growth event in the owner's graph.

    ``character`` must be the actual character entity, e.g. 258 -> 128 directly.
    ``timer_owner`` must receive 83 in this graph (SELF of the player graph for
    a UI316 entry). ``plot_guid`` is the scene plot GUID, never a character GUID.
    The caller supplies one event per press and an in-range action branch.
    No creation event resets an existing plot. Missing integer variables are
    zero per official mh1w3z96rpne; dynamic creation is allowed by mhso1b9wjica.
    """
    anchors = {value: a.integer_source(g, value, alias=f"{alias}_int_{value if value >= 0 else 'neg1'}")
               for value in (-1, EMPTY, GROWING, RIPE, MUTATING, UNCERTAIN)}
    def ref(value):
        return anchors[value], "value"

    def read(name, label):
        return a.read_state(g, target=plot, name=name,
                            flag_slot=config.variable_flag_slot, alias=f"{alias}_{label}")

    def write(source, name, value, label, role="then"):
        node = g.place(a.SET_STATE, f"{alias}_{label}")
        source.flow_to(node, role)
        node.data_from(*plot, "target")
        node.const("name", name, "string")
        node.data_from(*value, "value")
        for flag in ("is_bp_var", "emit_event"):
            a._flag(node, flag, False, config.variable_flag_slot)
        return node

    def stage(source, value, label, role="then"):
        return write(source, config.state_name, ref(value), label, role)

    def equal(source, left, right, label, role="then"):
        return a.route_refs(g, source, left=left, right=right,
                            alias=f"{alias}_{label}", from_role=role)

    def note(source, text, label, role="then"):
        node = g.place(PRINT, f"{alias}_{label}")
        source.flow_to(node, role)
        node.const("text", text, "string")
        return node

    state = read(config.state_name, "stage")
    empty = equal(src, ref(EMPTY), (state, "value"), "empty", from_role)
    ripe = equal(empty, ref(RIPE), (state, "value"), "ripe_action", "false")
    note(ripe, "FARM_BUSY_OR_GROWING", "busy", "false")

    seeds = item.read(g, holder=character, item_id=config.seed_id,
                      item_slot=config.item_slot, alias=f"{alias}_seeds")
    enough = g.place(GE, f"{alias}_enough")
    enough.data_from(seeds, "amount", "left")
    enough.data_from(*ref(1), "right")
    seed_gate = g.place(BRANCH, f"{alias}_seed_gate")
    empty.flow_to(seed_gate, "true")
    seed_gate.data_from(enough, "result", "condition")
    no_seed = note(seed_gate, "FARM_NO_SEEDS", "no_seed", "false")

    def change(source, *, item_id, delta, previous_stage, label):
        # The lock is set before both snapshots and 686. Nested calls see a busy
        # stage, including reentrant callbacks raised by the native bag update.
        claimed = stage(source, MUTATING, f"{label}_claim", "true")
        before_name = f"MW_MANUAL_FARM_BEFORE_{config.plot_id}"
        after_name = f"MW_MANUAL_FARM_AFTER_{config.plot_id}"
        before = item.read(g, holder=character, item_id=item_id,
                           item_slot=config.item_slot, alias=f"{alias}_{label}_before")
        captured = write(claimed, before_name, (before, "amount"), f"{label}_capture_before")
        changed = item.grant(g, captured, holder=character, item_id=item_id,
                            count=delta, item_slot=config.item_slot, alias=f"{alias}_{label}_change")
        after = item.read(g, holder=character, item_id=item_id,
                          item_slot=config.item_slot, alias=f"{alias}_{label}_after")
        observed = write(changed, after_name, (after, "amount"), f"{label}_capture_after")
        saved_before = read(before_name, f"{label}_saved_before")
        saved_after = read(after_name, f"{label}_saved_after")
        expected = g.place(ADD, f"{alias}_{label}_expected")
        # Concrete side first. Native 200's source descriptor fixes op enum 300
        # (decoded 7.1 6768728512522034581.mihoyobin f102[index2].f4.f2.f106.f1).
        expected.data_from(*ref(delta), "right")
        expected.data_from(saved_before, "value", "left")
        expected.const("op", 300, "enum")
        success = equal(observed, (expected, "result"), (saved_after, "value"), f"{label}_confirmed")
        unchanged = equal(success, (saved_before, "value"), (saved_after, "value"),
                          f"{label}_unchanged", "false")
        restored = stage(unchanged, previous_stage, f"{label}_restore", "true")
        failed = note(restored, "FARM_BAG_UNCHANGED" if delta > 0 else "FARM_SEED_NOT_CONSUMED",
                      f"{label}_failed")
        locked = stage(unchanged, UNCERTAIN, f"{label}_uncertain", "false")
        uncertain = note(locked, "FARM_INVENTORY_DELTA_UNCERTAIN", f"{label}_uncertain_note")
        return success, failed, uncertain

    planted_gate, _, plant_uncertain = change(seed_gate, item_id=config.seed_id,
                                              delta=-1, previous_stage=EMPTY, label="plant")
    growing = stage(planted_gate, GROWING, "mark_growing", "true")
    clock = a.start_once(g, growing, target=timer_owner, context_guid=plot_guid,
                         name=config.timer_name, seconds=config.growth_seconds,
                         alias=f"{alias}_growth_timer")
    planted = note(clock, "FARM_PLANTED", "planted")

    harvest_gate, bag_unchanged, harvest_uncertain = change(
        ripe, item_id=config.crop_id, delta=1, previous_stage=RIPE, label="harvest")
    cleared = stage(harvest_gate, EMPTY, "mark_empty", "true")
    harvested = note(cleared, "FARM_HARVESTED", "harvested")

    tick = g.place(TIMER_TICK, f"{alias}_tick")
    owner = equal(tick, timer_owner, (tick, "entity"), "timer_owner")
    timer = a.route_equal(g, owner, selector=(tick, "name"), expected=config.timer_name,
                         value_slot="string", alias=f"{alias}_timer_name", from_role="true")
    context = equal(timer, plot_guid, (tick, "context_guid"), "timer_plot", "true")
    tick_state = read(config.state_name, "tick_stage")
    pending = equal(context, ref(GROWING), (tick_state, "value"), "timer_growing", "true")
    matured = stage(pending, RIPE, "mark_ripe", "true")
    ready = note(matured, "FARM_RIPE_PRESS_INTERACT", "ready")
    return FarmFragment(empty, tick, planted, ready, harvested, no_seed,
                        bag_unchanged, (plant_uncertain, harvest_uncertain))
