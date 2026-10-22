"""Visible crop stages for the existing manual farm, without changing commerce.

The field watches the plot's authoritative stage. It changes models only;
inventory mutations and the growth timer remain in the player's manual graph.
"""
from ..nodes import Graph, NodeType, SELF, ON_CREATE, TIMER_TICK, START_TIMER
from ..modules import player_abilities as a
from ..modules.distance_interaction import ENTITY, GUID

MODEL = NodeType(308, "激活/关闭模型显示", exec_in=0, exec_outs={"then": 0},
                 ins={"entity": 0, "show": 1})


def build_plan():
    g = Graph("MW_API_FARM_VISIBLE_STAGES")
    owner = g.place(SELF, "owner")
    created = g.place(ON_CREATE, "created")
    refs = {}
    for label, ident in (("plot", 1077936130), ("shop", 1077936129),
                         ("seedling", 1077936134), ("ripe", 1077936135)):
        node = g.place(ENTITY, label)
        node.const("guid", ident, "uint")
        refs[label] = (node, "entity")

    def show(src, label, enabled, alias, role="then"):
        node = g.place(MODEL, alias)
        src.flow_to(node, role)
        node.data_from(*refs[label], "entity")
        node.const("show", int(enabled), "enum")
        return node

    tail = created
    for label in ("plot", "shop", "seedling", "ripe"):
        tail = show(tail, label, False, "initial_hide_" + label)
    guid = g.place(GUID, "owner_guid")
    guid.data_from(owner, "self", "entity")
    clock = g.place(START_TIMER, "watch_clock")
    tail.flow_to(clock)
    clock.data_from(owner, "self", "target")
    clock.data_from(guid, "guid", "context_guid")
    clock.const("name", "MW_FARM_VISUALS", "string")
    clock.const("loop", 1, "enum")
    g.plan.list_const(clock.alias, clock.ntype.ins["sequence"], [{"float": 0.25}])
    tick = g.place(TIMER_TICK, "tick")
    gate = a.route_equal(g, tick, selector=(tick, "name"), expected="MW_FARM_VISUALS",
                         value_slot="string", alias="our_clock")
    stage = a.read_state(g, target=refs["plot"], name="MW_MANUAL_FARM_STAGE_1077936130",
                         flag_slot="enum", alias="stage")
    # During an inventory write (3) or unresolved result (4), leave the last
    # confirmed stage visible. Only confirmed states 0, 1 and 2 change models.
    previous = gate
    for value, label in ((0, "empty"), (1, "growing"), (2, "mature")):
        branch = a.route_integer(g, previous, selector=(stage, "value"), expected=value,
                               alias=label,
                               from_role="true" if value == 0 else "false")
        end = show(branch, "seedling", value == 1, label + "_seedling", "true")
        show(end, "ripe", value == 2, label + "_crop")
        previous = branch
    return g.plan
