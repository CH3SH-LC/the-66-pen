"""Interpret the generated distance graph; no native/runtime success is implied."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from tools.gameplan import cli
from tools.gameplan.builder import GraphBuilder
from tools.gameplan.contracts import load_store
from tools.gameplan.demo.farming_interactive import build_plan
from tools.gameplan.modules import distance_interaction as distance
from tools.gameplan.nodes import NodeType
from tools.gameplan.tests.test_farming_interactive import CONFIG, GraphEvaluator
from tools.gameplan.tests.test_cli_farming_interactive import BASE, invoke


DISTANCE = replace(CONFIG, interaction_mode="distance", farm_center=(0, 0, 0),
    sell_center=(8, 0, 0), interaction_radius=1.5, exit_radius=2.0,
    poll_seconds=0.25, host_key="plot-A", sale_mode="native_shop", shop_flag_slot="enum",
    starter_seed_count=3, starter_currency_amount=20)


def machine(config=DISTANCE, own="plot"):
    result = GraphEvaluator(build_plan(config), own=own)
    result.live_players = ["alice-player"]
    result.characters = {"alice-player": ["alice"]}
    result.character_owners = {"alice": "alice-player"}
    result.positions = {"alice": (4, 0, 0)}
    result.fire("created", {0: own, 1: "guid-" + own})
    return result


class DistanceBehavior(unittest.TestCase):
    def test_all_new_roles_are_real_server_contracts_and_batch_fits(self):
        store = load_store()
        for node in vars(distance).values():
            if not isinstance(node, NodeType):
                continue
            contract = store.require(node.definition_id)
            for kind, roles in ((3, node.ins), (4, node.outs), (2, node.exec_outs)):
                for index in roles.values():
                    self.assertIsNotNone(contract.port(kind, index))
        plan = build_plan(DISTANCE)
        payload = GraphBuilder(plan, lambda _: self.fail("must not dispatch"),
            run_id="compile-only").batch_plan_json()
        self.assertEqual(len(payload["nodes"]), len(plan.nodes))
        self.assertLessEqual(len(plan.nodes), 128)
        self.assertFalse({92, 392, 804} & {n.definition_id for n in plan.nodes})
        clocks = {c.alias: c.value for c in plan.consts if c.alias in
                  ("poll_timer", "growth_timer") and c.port_index == 1}
        self.assertEqual(clocks, {"poll_timer": CONFIG.timer_name + "_poll", "growth_timer": CONFIG.timer_name})

    def test_enter_stand_grow_leave_reenter_harvest_then_native_shop_once(self):
        m = machine()
        m.positions["alice"] = (0, 0, 0)
        m.poll()
        self.assertEqual(m.state[("alice", distance.state_name("plot-A"))], 1)
        self.assertEqual(m.inventory[("alice", 101)], 2)
        self.assertEqual(m.currency[("alice", 201)], 20)
        self.assertEqual(m.state[("plot", CONFIG.state_name)], 1)
        self.assertEqual(m.timers, [("plot", CONFIG.timer_name + "_poll", 1,
            {"list": [{"float": .25}]}, "guid-plot"),
            ("plot", CONFIG.timer_name, 0, {"list": [{"float": 5.0}]}, "guid-alice")])
        m.poll(); m.tick(); m.poll(); m.poll()
        self.assertEqual(m.state[("plot", CONFIG.state_name)], 2)
        self.assertEqual(m.inventory[("alice", 101)], 2)
        self.assertEqual(m.inventory[("alice", 102)], 0)
        m.positions["alice"] = (4, 0, 0); m.poll()
        m.positions["alice"] = (0, 0, 0); m.poll(); m.poll()
        self.assertEqual(m.inventory[("alice", 102)], 2)
        self.assertEqual(m.state[("plot", CONFIG.state_name)], 0)
        m.positions["alice"] = (4, 0, 0); m.poll()
        m.positions["alice"] = (8, 0, 0); m.poll(); m.poll()
        self.assertEqual(m.opened_shops, [("alice-player", "plot", 1)])
        self.assertEqual((m.inventory[("alice", 102)], m.currency[("alice", 201)]), (2, 20))
        self.assertEqual((len(m.catalog_sales), len(m.catalog_purchases)), (1, 1))
        m.positions["alice"] = (4, 0, 0); m.poll()
        m.positions["alice"] = (8, 0, 0); m.poll()
        self.assertEqual(len(m.opened_shops), 2)
        self.assertEqual(m.notes.count("FARM_HARVESTED"), 1)

    def test_two_players_have_separate_inside_flags_bags_and_shop_owner(self):
        m = machine()
        m.live_players.append("bob-player")
        m.characters["bob-player"] = ["bob"]
        m.character_owners["bob"] = "bob-player"
        m.positions.update(alice=(0, 0, 0), bob=(8, 0, 0))
        m.poll(); m.poll()
        self.assertEqual(m.state[("alice", distance.state_name("plot-A"))], 1)
        self.assertEqual(m.state[("bob", distance.state_name("plot-A"))], 2)
        self.assertEqual(m.inventory[("alice", 101)], 2)
        self.assertEqual(m.inventory[("bob", 101)], 3)
        self.assertEqual(m.currency[("alice", 201)], 20)
        self.assertEqual(m.currency[("bob", 201)], 20)
        self.assertEqual(m.opened_shops, [("bob-player", "plot", 1)])
        m.positions["alice"] = (4, 0, 0); m.poll()
        self.assertEqual(m.state[("alice", distance.state_name("plot-A"))], 0)
        self.assertEqual(m.state[("bob", distance.state_name("plot-A"))], 2)

    def test_host_keys_separate_latches_while_starter_stays_shared(self):
        a, b = machine(own="plot-A"), machine(replace(DISTANCE, host_key="plot-B"), own="plot-B")
        b.state, b.inventory, b.currency = a.state, a.inventory, a.currency
        for m, host in ((a, "plot-A"), (b, "plot-B")):
            m.positions["alice"] = (8, 0, 0)
            m.poll(target=host); m.poll(target=host)
        self.assertEqual(a.state[("alice", distance.state_name("plot-A"))], 2)
        self.assertEqual(a.state[("alice", distance.state_name("plot-B"))], 2)
        self.assertEqual(a.currency[("alice", 201)], 20)
        self.assertEqual(a.inventory[("alice", 101)], 3)
        self.assertEqual(a.opened_shops, [("alice-player", "plot-A", 1)])
        self.assertEqual(b.opened_shops, [("alice-player", "plot-B", 1)])

    def test_timer_host_filter_and_zero_or_multiple_characters_are_ignored(self):
        m = machine()
        m.positions["alice"] = (0, 0, 0)
        m.poll(target="foreign"); m.poll(name=CONFIG.timer_name)
        m.tick(name=CONFIG.timer_name + "_poll")
        self.assertEqual(m.state[("plot", CONFIG.state_name)], 0)
        self.assertFalse(m.inventory)
        # No positions for these characters: wrongly evaluating them would fail.
        for characters in ([], ["one", "two"]):
            m.characters["alice-player"] = characters
            m.poll()
        self.assertFalse(m.inventory)
        self.assertFalse(m.opened_shops)
        m.characters["alice-player"] = ["alice"]; m.poll()
        self.assertEqual(m.state[("plot", CONFIG.state_name)], 1)
        m.tick(target="foreign"); m.tick(name=CONFIG.timer_name + "_poll")
        self.assertEqual(m.state[("plot", CONFIG.state_name)], 1)

    def test_exact_enter_boundary_and_outer_hysteresis(self):
        m = machine()
        latch = ("alice", distance.state_name("plot-A"))
        m.positions["alice"] = (1.5001, 0, 0); m.poll()
        self.assertNotIn(latch, m.state)
        m.positions["alice"] = (1.5, 0, 0); m.poll()
        self.assertEqual(m.state[latch], 1)
        m.positions["alice"] = (2.0, 0, 0); m.poll()
        self.assertEqual(m.state[latch], 1)
        m.positions["alice"] = (2.0001, 0, 0); m.poll()
        self.assertEqual(m.state[latch], 0)
        m.tick(); m.positions["alice"] = (1.5, 0, 0); m.poll()
        self.assertEqual(m.inventory[("alice", 102)], 2)

    def test_required_inputs_refuse_and_old_modes_keep_their_entry(self):
        for changes in ({"farm_center": None}, {"sell_center": (1, 0, 0)},
                        {"farm_center": (True, 0, 0)}, {"interaction_radius": None},
                        {"exit_radius": 1.5}, {"poll_seconds": float("nan")},
                        {"host_key": None}, {"inventory_holder": "character_owner"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(DISTANCE, **changes)
        native = build_plan(replace(CONFIG, sale_mode="native_shop", shop_flag_slot="enum",
            starter_seed_count=3, starter_currency_amount=20))
        self.assertEqual(len(native.nodes), 63)
        self.assertFalse(any(n.alias.startswith("poll_") for n in native.nodes))
        self.assertEqual(sum(n.definition_id == 92 for n in native.nodes), 1)


class DistanceCli(unittest.TestCase):
    extra = ["--interaction-mode", "distance", "--entity-id", "1077936129",
        "--farm-center", "0", "0", "0", "--sell-center", "8", "0", "0",
        "--interaction-radius", "1.5", "--exit-radius", "2",
        "--sale-mode", "native_shop", "--shop-flag-slot", "enum",
        "--starter-seeds", "3", "--starter-currency", "20"]

    def test_compiles_default_only_without_collision_prerequisite(self):
        with patch.object(cli, "subprocess_runner", side_effect=AssertionError("offline only")):
            code, report, error = invoke(BASE + self.extra)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(report["mode"], "compile")
        self.assertFalse(report["editorDispatchAttempted"])
        self.assertNotIn("triggers", report["prerequisites"])
        route = report["prerequisites"]["distanceInteraction"]
        self.assertEqual(route["hostKey"], "1077936129")
        self.assertEqual(route["farmCenter"], [0, 0, 0])
        self.assertFalse(route["collisionComponentRequired"])
        self.assertFalse(report["gameRuntimeVerified"])
        self.assertLessEqual(report["summary"]["nodes"], 128)

    def test_distance_missing_center_or_host_refuses_before_runner(self):
        for option, count in (("--farm-center", 4), ("--entity-id", 2)):
            extra = self.extra.copy(); at = extra.index(option); del extra[at:at + count]
            with self.subTest(option=option):
                code, report, error = invoke(BASE + extra, runner=lambda _: self.fail("must not dispatch"))
                self.assertEqual(code, 2)
                self.assertIsNone(report)
                self.assertIn("nothing was dispatched", error)


if __name__ == "__main__":
    unittest.main()
