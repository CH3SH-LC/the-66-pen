"""Execute the generated graph in a small deterministic, non-native evaluator.

Only contracted primitives used by this graph are interpreted. Tests drive the
actual graph edges and constants, rather than a second hand-written farm state
machine. They prove composition, not game execution or engine transactionality.
"""
from collections import defaultdict
from dataclasses import asdict, replace
import math
import unittest

from tools.gameplan.demo.farming_interactive import FarmInteractiveConfig, build_plan
from tools.gameplan.modules import player_abilities as abilities
from tools.gameplan.nodes import ON_CREATE, PRINT, Graph


CONFIG = FarmInteractiveConfig(seed_id=101, crop_id=102, currency_id=201,
    item_slot="int", currency_slot="int", variable_flag_slot="bool", growth_seconds=5,
    harvest_gain=2, sale_count=2, sale_price=7, inventory_holder="entrant")


class GraphEvaluator:
    def __init__(self, plan, own="plot"):
        self.nodes = plan.aliases()
        self.constants = {(c.alias, c.port_index): c.value for c in plan.consts}
        self.data = {(e.dst, e.dst_index): (e.src, e.src_index)
                     for e in plan.edges if e.src_kind == 4}
        self.flow = defaultdict(list)
        for edge in plan.edges:
            if edge.src_kind == 2:
                self.flow[(edge.src, edge.src_index)].append(edge.dst)
        self.own = own
        self.inventory = defaultdict(int)
        self.currency = defaultdict(int)
        self.state = {}
        self.timers = []
        self.notes = []
        self.events = {}
        self.character_owners = {}
        self.catalog_sales = []
        self.catalog_purchases = []
        self.opened_shops = []
        self.live_players = []
        self.characters = {}
        self.positions = {}

    def input(self, alias, index):
        if (alias, index) in self.data:
            return self.value(*self.data[(alias, index)])
        return self.constants[(alias, index)]

    def value(self, alias, index):
        if alias in self.events:
            return self.events[alias][index]
        definition = self.nodes[alias].definition_id
        if definition == 73:
            return self.own
        if definition == 259:
            return self.character_owners[self.input(alias, 0)]
        if definition == 248:
            return self.live_players
        if definition == 258:
            return self.characters.get(self.input(alias, 0), [])
        if definition == 142:
            return len(self.input(alias, 0))
        if definition == 128:
            return self.input(alias, 0)[self.input(alias, 1)]
        if definition == 76:
            return "guid-" + self.input(alias, 0)
        if definition == 75:
            return self.input(alias, 0).removeprefix("guid-")
        if definition == 99:
            return self.positions[self.input(alias, 0)]
        if definition == 225:
            return tuple(self.input(alias, i) for i in range(3))
        if definition == 244:
            return math.dist(self.input(alias, 0), self.input(alias, 1))
        if definition == 257:
            low, high = self.input(alias, 0), self.input(alias, 1)
            assert low == high, "only deterministic equal bounds used here"
            return low
        if definition == 50:
            # Official query: a missing custom variable returns its type default.
            # These plans concretize generic variables with an integer anchor.
            return self.state.get((self.input(alias, 0), self.input(alias, 1)), 0)
        if definition == 690:
            return self.inventory[(self.input(alias, 0), self.input(alias, 1))]
        if definition in (14, 231, 232, 233):
            left, right = self.input(alias, 0), self.input(alias, 1)
            if definition == 14:
                return left == right
            if definition == 231:
                return left <= right
            return left > right if definition == 232 else left >= right
        raise AssertionError(f"unsupported data node {definition}:{index}")

    def fire(self, alias, outputs):
        self.events = {alias: outputs}
        queue = list(self.flow[(alias, 0)])
        self.budget = 1500
        self._execute(queue)

    def _execute(self, queue):
        while queue:
            self.budget -= 1
            assert self.budget > 0, "execution did not terminate"
            current = queue.pop(0)
            definition = self.nodes[current].definition_id
            branch = 0
            if definition == 509:
                for value in list(self.input(current, 0)):
                    self.events[current] = {0: value}
                    self._execute(list(self.flow[(current, 0)]))
                self.events.pop(current, None)
                branch = 1
            elif definition == 2:
                branch = 0 if self.input(current, 0) else 1
            elif definition == 22:
                self.state[(self.input(current, 0), self.input(current, 1))] = self.input(current, 2)
            elif definition in (686, 688):
                bag = self.inventory if definition == 686 else self.currency
                key = (self.input(current, 0), self.input(current, 1))
                bag[key] += self.input(current, 2)
                assert bag[key] >= 0, "graph over-consumed inventory"
            elif definition == 79:
                self.timers.append(tuple(self.input(current, i) for i in range(5)))
            elif definition == 708:
                self.catalog_sales.append(tuple(self.input(current, i) for i in range(9)))
            elif definition == 710:
                self.catalog_purchases.append(tuple(self.input(current, i) for i in range(5)))
            elif definition == 702:
                self.opened_shops.append(tuple(self.input(current, i) for i in range(3)))
            elif definition == 306:
                if not hasattr(self, 'option_cards'):
                    self.option_cards = {}
                self.option_cards[(self.input(current, 0), self.input(current, 1))] = bool(self.input(current, 2))
            elif definition == 1:
                self.notes.append(self.input(current, 0))
            else:
                raise AssertionError(f"unsupported execution node {definition}")
            queue.extend(self.flow[(current, branch)])

    def enter(self, index=1, player="player", target="plot"):
        self.fire("interact", {0: player, 1: f"guid-{player}", 2: target,
                               3: f"guid-{target}", 4: index})

    def skill(self, action="plant", character="character", target="field-one"):
        self.fire("interact", {0: character, 1: f"guid-{character}", 2: action,
                               3: target, 4: ""})

    def tick(self, name=CONFIG.timer_name, target="plot"):
        self.fire("growth_tick", {0: target, 1: f"guid-{target}", 2: name,
                                  3: 0, 4: 0, 5: "guid-player"})

    def poll(self, name=CONFIG.timer_name + "_poll", target="plot"):
        self.fire("interact", {0: target, 1: f"guid-{target}", 2: name,
                               3: 0, 4: 0, 5: "guid-plot"})


class FarmBehavior(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(CONFIG)
        self.machine = GraphEvaluator(self.plan)
        self.machine.fire("created", {0: "plot", 1: "guid-plot"})

    def stage(self):
        return self.machine.state[("plot", CONFIG.state_name)]

    def test_plant_wait_grow_harvest_sell_complete_generated_chain(self):
        machine = self.machine
        machine.inventory[("player", 101)] = 2
        machine.enter()
        self.assertEqual((self.stage(), machine.inventory[("player", 101)]), (1, 1))
        self.assertEqual(machine.timers, [("plot", CONFIG.timer_name, 0,
                                          {"list": [{"float": 5.0}]}, "guid-player")])
        machine.enter()  # while growing, do not charge another seed or harvest
        self.assertEqual((self.stage(), machine.inventory[("player", 101)],
                          machine.inventory[("player", 102)]), (1, 1, 0))
        self.assertEqual(len(machine.timers), 1)
        machine.tick()
        self.assertEqual(self.stage(), 2)
        machine.enter()
        self.assertEqual((self.stage(), machine.inventory[("player", 102)]), (0, 2))
        machine.enter(index=2)
        self.assertEqual((machine.inventory[("player", 102)], machine.currency[("player", 201)]), (0, 7))
        self.assertIn("FARM_PLANTED", machine.notes)
        self.assertIn("FARM_RIPE", machine.notes)
        self.assertIn("FARM_HARVESTED", machine.notes)
        self.assertIn("FARM_SOLD", machine.notes)

    def test_no_seeds_no_crop_no_reward(self):
        machine = self.machine
        machine.enter()
        machine.enter(index=2)
        machine.tick()  # stale timer when empty must not create a ripe plot
        self.assertEqual(self.stage(), 0)
        self.assertFalse(machine.timers)
        self.assertEqual(sum(machine.inventory.values()), 0)
        self.assertEqual(sum(machine.currency.values()), 0)
        self.assertIn("FARM_NO_SEEDS", machine.notes)
        self.assertIn("FARM_NO_CROPS", machine.notes)

    def test_foreign_entity_events_and_unrelated_timer_do_not_change_plot(self):
        machine = self.machine
        machine.inventory[("player", 101)] = 2
        machine.enter(target="other")
        machine.enter(index=99)
        self.assertEqual(machine.inventory[("player", 101)], 2)
        self.assertFalse(machine.timers)
        machine.enter()
        machine.fire("created", {0: "other", 1: "guid-other"})
        machine.tick(name="other-clock")
        machine.tick(target="other")
        self.assertEqual(self.stage(), 1)
        machine.tick()
        machine.enter()
        machine.tick()  # no duplicate harvest from stale tick after clearing
        self.assertEqual(self.stage(), 0)
        self.assertEqual(machine.inventory[("player", 102)], 2)

    def test_shared_plot_rewards_the_interacting_player_not_the_plot(self):
        machine = self.machine
        machine.inventory[("alice", 101)] = 1
        machine.enter(player="alice")
        machine.tick()
        machine.enter(player="bob")
        machine.enter(index=2, player="bob")
        self.assertEqual(machine.inventory[("alice", 101)], 0)
        self.assertEqual(machine.currency[("bob", 201)], 7)
        self.assertEqual(machine.currency[("alice", 201)], 0)
        self.assertEqual(machine.currency[("plot", 201)], 0)

    def test_sale_consumes_exact_count_and_cannot_repeat_without_inventory(self):
        machine = self.machine
        machine.inventory[("player", 102)] = 3
        machine.enter(index=2)
        machine.enter(index=2)
        self.assertEqual(machine.inventory[("player", 102)], 1)
        self.assertEqual(machine.currency[("player", 201)], 7)

    def test_default_uses_character_bag_without_touching_owning_player(self):
        parameters = asdict(CONFIG)
        del parameters["inventory_holder"]
        config = FarmInteractiveConfig(**parameters)
        self.assertEqual(config.inventory_holder, "entrant")
        plan = build_plan(config)
        self.assertFalse(any(n.definition_id == 259 for n in plan.nodes))
        machine = GraphEvaluator(plan)
        machine.character_owners["character"] = "player"
        machine.inventory[("character", 101)] = 1
        machine.inventory[("player", 101)] = 99
        machine.fire("created", {0: "plot", 1: "guid-plot"})
        machine.enter(player="character")
        machine.tick()
        machine.enter(player="character")
        machine.enter(index=2, player="character")
        self.assertEqual(machine.inventory[("character", 101)], 0)
        self.assertEqual(machine.currency[("character", 201)], 7)
        self.assertEqual(machine.inventory[("player", 101)], 99)
        self.assertEqual(machine.currency[("player", 201)], 0)

    def test_explicit_owner_policy_only_changes_selected_data_source(self):
        # Wiring compatibility only: this fake evaluator does not establish that
        # a native player entity supports bags. Default gameplay uses characters.
        config = replace(CONFIG, inventory_holder="character_owner")
        plan = build_plan(config)
        machine = GraphEvaluator(plan)
        machine.character_owners["character"] = "player"
        machine.inventory[("player", 101)] = 1
        machine.fire("created", {0: "plot", 1: "guid-plot"})
        machine.enter(player="character")
        machine.tick()
        machine.enter(player="character")
        machine.enter(index=2, player="character")
        self.assertEqual(machine.inventory[("player", 101)], 0)
        self.assertEqual(machine.currency[("player", 201)], 7)
        self.assertEqual(machine.currency[("character", 201)], 0)

    def test_single_interaction_entry_and_contract_valid_timer_container(self):
        self.assertEqual(sum(n.definition_id == 92 for n in self.plan.nodes), 1)
        self.assertLessEqual(len(self.plan.nodes), 128)
        timer_const = next(c for c in self.plan.consts if c.alias == "growth_timer" and c.port_index == 3)
        self.assertEqual((timer_const.slot, timer_const.value), ("auto", {"list": [{"float": 5.0}]}))
        self.assertFalse(any(c.alias.startswith("mark_") and c.port_index == 2 for c in self.plan.consts))

    def test_native_shop_initializes_owner_catalog_and_opens_for_player_without_payout(self):
        config = replace(CONFIG, sale_mode="native_shop", seed_price=2, shop_index=3,
                         shop_flag_slot="enum")
        plan = build_plan(config)
        machine = GraphEvaluator(plan)
        machine.character_owners["character"] = "player"
        machine.inventory[("character", 101)] = 1
        machine.fire("created", {0: "foreign", 1: "guid-foreign"})
        self.assertFalse(machine.catalog_sales or machine.catalog_purchases)
        machine.fire("created", {0: "plot", 1: "guid-plot"})
        self.assertEqual(len(machine.catalog_sales), 1)
        self.assertEqual(len(machine.catalog_purchases), 1)
        self.assertEqual(machine.catalog_sales[0][:4], ("plot", 3, 101,
            {"dict": [{"key": {"uint": 201}, "value": {"int": 2}}]}))
        self.assertEqual(machine.catalog_purchases[0], ("plot", 3, 102,
            {"dict": [{"key": {"uint": 201}, "value": {"int": 7}}]}, 1))
        machine.enter(player="character")
        machine.tick()
        machine.enter(player="character")
        self.assertEqual(machine.inventory[("character", 102)], 2)
        before = dict(machine.inventory), dict(machine.currency)
        machine.enter(index=2, player="character", target="foreign")
        self.assertFalse(machine.opened_shops)
        machine.enter(index=2, player="character")
        machine.enter(index=2, player="character")
        self.assertEqual(machine.opened_shops, [("player", "plot", 3)] * 2)
        self.assertEqual((dict(machine.inventory), dict(machine.currency)), before)
        self.assertEqual(len(machine.catalog_sales), 1)  # Opening never reinstalls rows.
        self.assertEqual(len(machine.catalog_purchases), 1)
        self.assertNotIn("FARM_SOLD", machine.notes)
        self.assertFalse(any(n.definition_id == 688 for n in plan.nodes))
        self.assertFalse(any(n.alias.startswith("sell_") and n.definition_id in (686, 690)
                             for n in plan.nodes))

    def test_native_shop_boolean_slot_remains_explicit(self):
        plan = build_plan(replace(CONFIG, sale_mode="native_shop", shop_flag_slot="bool"))
        flags = {(c.alias, c.port_index): (c.slot, c.value) for c in plan.consts
                 if c.alias.startswith("farm_catalog") and c.slot == "bool"}
        self.assertEqual(flags[("farm_catalog_sale_0", 5)], ("bool", False))
        self.assertEqual(flags[("farm_catalog_sale_0", 8)], ("bool", True))
        self.assertEqual(flags[("farm_catalog_purchase_0", 4)], ("bool", True))

    def test_skill_target_action_routes_character_plant_timer_harvest_and_sale(self):
        plan = build_plan(replace(CONFIG, interaction_mode="skill", skill_target="field-one"))
        self.assertEqual(sum(n.definition_id == 392 for n in plan.nodes), 1)
        self.assertFalse(any(n.definition_id in (92, 259) for n in plan.nodes))
        machine = GraphEvaluator(plan)
        machine.inventory[("character", 101)] = 2
        machine.inventory[("player", 101)] = 99
        machine.fire("created", {0: "plot", 1: "guid-plot"})
        baseline = dict(machine.state), dict(machine.inventory), list(machine.notes)
        for action, target in (("plant", "other-field"), ("sell", "other-field"),
                               ("harvest", "field-one"), ("PLANT", "field-one"),
                               ("", "field-one"), ("plant", "")):
            machine.skill(action=action, target=target)
        self.assertEqual((dict(machine.state), dict(machine.inventory), machine.notes), baseline)
        self.assertFalse(machine.timers)
        machine.skill()
        machine.skill()  # Still growing: neither a second seed nor a second timer.
        self.assertEqual(machine.inventory[("character", 101)], 1)
        self.assertEqual(machine.timers, [("plot", CONFIG.timer_name, 0,
                                          {"list": [{"float": 5.0}]}, "guid-character")])
        machine.tick()
        machine.skill()  # The same plant action harvests a ripe plot.
        self.assertEqual(machine.state[("plot", CONFIG.state_name)], 0)
        self.assertEqual(machine.inventory[("character", 102)], 2)
        machine.skill(action="sell")
        machine.skill(action="sell")  # Cannot sell the same harvest twice.
        self.assertEqual(machine.inventory[("character", 102)], 0)
        self.assertEqual(machine.currency[("character", 201)], 7)
        self.assertEqual(machine.inventory[("player", 101)], 99)
        self.assertEqual(machine.currency[("player", 201)], 0)

    def test_skill_native_shop_opens_for_owner_without_repeating_payment(self):
        plan = build_plan(replace(CONFIG, interaction_mode="skill", skill_target="field-one",
                                 sale_mode="native_shop", shop_index=3, shop_flag_slot="bool"))
        machine = GraphEvaluator(plan)
        machine.character_owners["character"] = "player"
        machine.inventory[("character", 101)] = 1
        machine.fire("created", {0: "plot", 1: "guid-plot"})
        machine.skill()
        machine.tick()
        machine.skill()
        before = dict(machine.inventory), dict(machine.currency)
        machine.skill(action="sell", target="other-field")
        machine.skill(action="unknown")
        self.assertFalse(machine.opened_shops)
        machine.skill(action="sell")
        machine.skill(action="sell")
        self.assertEqual(machine.opened_shops, [("player", "plot", 3)] * 2)
        self.assertEqual((dict(machine.inventory), dict(machine.currency)), before)
        self.assertEqual(machine.inventory[("character", 102)], 2)
        self.assertEqual((len(machine.catalog_sales), len(machine.catalog_purchases)), (1, 1))
        self.assertNotIn("FARM_SOLD", machine.notes)

    def test_config_rejects_colliding_indices_and_invalid_economy(self):
        bad_configs = [dict(sell_trigger_index=1), dict(farm_trigger_index=0),
            dict(sell_trigger_index=0), dict(shop_index=0), dict(seed_id=True), dict(seed_cost=0),
            dict(sale_price=-1), dict(harvest_gain=1.5), dict(growth_seconds=float("inf")),
            dict(growth_seconds=True), dict(growth_seconds=0), dict(seed_id=102),
            dict(variable_flag_slot="auto"), dict(item_slot="string"), dict(state_name=""),
            dict(sale_mode="unknown"), dict(seed_price=0), dict(shop_index=-1),
            dict(shop_flag_slot="auto"), dict(sale_mode="native_shop"),
            dict(sale_mode="native_shop", shop_flag_slot="enum", item_slot="enum"),
            dict(interaction_mode="unknown"), dict(interaction_mode="skill"),
            dict(interaction_mode="skill", skill_target=""),
            dict(interaction_mode="skill", skill_target=" "), dict(skill_target=123),
            dict(interaction_mode="skill", skill_target="field-one", inventory_holder="character_owner"),
            dict(starter_seed_count=-1), dict(starter_seed_count=True),
            dict(starter_currency_amount=1.5), dict(starter_currency_amount=2147483648),
            dict(starter_guard=""), dict(starter_guard="x\0y")]
        for changes in bad_configs:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CONFIG, **changes)

    def test_generic_item_exchange_runs_generated_reward_and_reject_paths(self):
        g = Graph("MW_API_EXCHANGE_TEST")
        event = g.place(ON_CREATE, "created")
        exchange = abilities.guarded_item_exchange(g, event, holder=(event, "entity"),
            source_id=101, cost=2, reward_id=102, reward_count=3,
            item_slot="int", reward_slot="int", reward_currency=False, alias="trade")
        rejected = g.place(PRINT, "rejected")
        exchange.gate.flow_to(rejected, "false")
        rejected.const("text", "rejected", "string")
        g.validate()
        machine = GraphEvaluator(g.plan)
        machine.inventory[("player", 101)] = 2
        machine.fire("created", {0: "player"})
        machine.fire("created", {0: "player"})
        self.assertEqual(machine.inventory[("player", 101)], 0)
        self.assertEqual(machine.inventory[("player", 102)], 3)
        self.assertEqual(machine.notes, ["rejected"])


class FarmStarterBehavior(unittest.TestCase):
    def test_first_valid_action_bootstraps_then_never_pays_twice_in_all_modes(self):
        for interaction in ("proximity", "skill"):
            for sale in ("direct", "native_shop"):
                with self.subTest(interaction=interaction, sale=sale):
                    config = replace(CONFIG, interaction_mode=interaction,
                        skill_target="field-one" if interaction == "skill" else None,
                        sale_mode=sale, shop_flag_slot="enum" if sale == "native_shop" else None,
                        starter_seed_count=3, starter_currency_amount=20)
                    plan = build_plan(config)
                    machine = GraphEvaluator(plan)
                    machine.character_owners.update({"alice": "alice-player", "bob": "bob-player"})
                    machine.fire("created", {0:"plot", 1:"plot-guid"})

                    def act(action="plant", character="alice", valid_target=True):
                        if interaction == "skill":
                            machine.skill(action=action, character=character,
                                          target="field-one" if valid_target else "foreign")
                        else:
                            machine.enter(index={"plant":1,"sell":2}.get(action,99),
                                          player=character, target="plot" if valid_target else "foreign")

                    before = dict(machine.state), dict(machine.inventory), dict(machine.currency)
                    act(valid_target=False)
                    act("sell",valid_target=False)
                    act("unknown")
                    self.assertEqual((dict(machine.state),dict(machine.inventory),dict(machine.currency)),before)
                    self.assertFalse(machine.timers or machine.opened_shops)

                    act()  # A previously empty bag receives seeds, then plants immediately.
                    self.assertEqual(machine.inventory[("alice",101)],2)
                    self.assertEqual(machine.currency[("alice",201)],20)
                    self.assertEqual(machine.state[("alice",config.starter_guard)],1)
                    self.assertEqual(machine.state[("plot",config.state_name)],1)
                    act()
                    self.assertEqual(machine.inventory[("alice",101)],2)
                    self.assertEqual(machine.currency[("alice",201)],20)
                    self.assertEqual(len(machine.timers),1)
                    machine.tick()
                    act()  # Harvest without another starter payment.
                    self.assertEqual(machine.inventory[("alice",102)],2)
                    act("sell")
                    act("sell")
                    if sale == "direct":
                        self.assertEqual(machine.inventory[("alice",102)],0)
                        self.assertEqual(machine.currency[("alice",201)],27)
                    else:
                        # The evaluator does not fake native transactions: opening only.
                        self.assertEqual(machine.inventory[("alice",102)],2)
                        self.assertEqual(machine.currency[("alice",201)],20)
                        self.assertEqual(machine.opened_shops,[("alice-player","plot",1)]*2)
                        self.assertEqual(sum(n.definition_id==688 for n in plan.nodes),1)
                    act("sell",character="bob")  # Sell-area first contact is also eligible.
                    self.assertEqual(machine.inventory[("bob",101)],3)
                    self.assertEqual(machine.currency[("bob",201)],20)
                    self.assertEqual(machine.currency[("alice-player",201)],0)
                    self.assertEqual(machine.currency[("bob-player",201)],0)
                    self.assertEqual(sum(n.alias=="starter_claim" for n in plan.nodes),1)

    def test_distinct_plots_and_graph_names_share_the_default_character_guard(self):
        config = replace(CONFIG, starter_seed_count=3, starter_currency_amount=20)
        self.assertEqual(config.starter_guard,"MW_FARM_STARTER_V1")
        machines = []
        for suffix in ("A","B"):
            machine = GraphEvaluator(build_plan(config,name=f"MW_API_FARM_{suffix}"),own=f"plot-{suffix}")
            if machines:
                machine.state, machine.inventory, machine.currency = (
                    machines[0].state,machines[0].inventory,machines[0].currency)
            machine.fire("created",{0:f"plot-{suffix}",1:f"guid-{suffix}"})
            machines.append(machine)
        machines[0].enter(player="character",target="plot-A")
        machines[1].enter(player="character",target="plot-B")
        self.assertEqual(machines[1].inventory[("character",101)],1)
        self.assertEqual(machines[1].currency[("character",201)],20)
        self.assertEqual(machines[1].state[("character",config.starter_guard)],1)

    def test_enabled_starter_rejects_legacy_player_bag_policy_with_named_error(self):
        for seeds,money in ((3,20),(3,0),(0,20)):
            with self.subTest(seeds=seeds,money=money), self.assertRaisesRegex(
                    ValueError,"STARTER_REQUIRES_CHARACTER_INVENTORY"):
                replace(CONFIG,inventory_holder="character_owner",
                        starter_seed_count=seeds,starter_currency_amount=money)
        # Existing non-default graph remains available when starter is disabled.
        plan = build_plan(replace(CONFIG,inventory_holder="character_owner"))
        self.assertTrue(any(n.definition_id==259 for n in plan.nodes))
        self.assertFalse(any(n.alias.startswith("starter_") for n in plan.nodes))

    def test_disabled_counts_preserve_plan_and_zero_currency_has_no_starter_money_node(self):
        before = build_plan(CONFIG)
        after = build_plan(replace(CONFIG,starter_seed_count=0,starter_currency_amount=0))
        self.assertEqual((before.nodes,before.edges,before.consts),(after.nodes,after.edges,after.consts))
        self.assertFalse(any(n.alias.startswith("starter_") for n in after.nodes))
        seeds_only = build_plan(replace(CONFIG,starter_seed_count=3,starter_currency_amount=0))
        self.assertFalse(any(n.alias=="starter_currency" for n in seeds_only.nodes))
        currency_only = build_plan(replace(CONFIG,starter_seed_count=0,starter_currency_amount=20))
        self.assertFalse(any(n.alias=="starter_seeds" for n in currency_only.nodes))


if __name__ == "__main__":
    unittest.main()
