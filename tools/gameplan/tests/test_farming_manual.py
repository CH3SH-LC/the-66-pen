"""Drive the complete emitted player graph; no live game or injection."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools.gameplan.builder import GraphBuilder
from tools.gameplan.contracts import DATA_INPUT, default_store
from tools.gameplan.demo.farming_manual import (
    ROOT, DEFAULT_NAME, MAX_REQUEST_BYTES, FarmManualConfig, build_plan,
    package, request_line_bytes, write_package)
from tools.gameplan.demo.farming_manual import verify_export, _export_loader, _type_contract
from tools.gameplan.modules.farm_interaction import EMPTY, GROWING, RIPE
from tools.gameplan.plan import ConstSpec
from tools.gameplan.tests.test_farm_interaction import FarmEvaluator

CONFIG = FarmManualConfig(group_index=101)


class ManualEvaluator(FarmEvaluator):
    def __init__(self, plan, config=CONFIG):
        super().__init__(plan)
        self.config = config
        self.characters = {"player": ["character"], "other-player": ["other-character"]}
        self.positions = {"character": config.farm_center, "other-character": config.farm_center}

    def press(self, player="player", group=None, combo=None):
        self.fire("interact", {0: player, 1: "unused-player-guid",
            2: self.config.group_combo_index if combo is None else combo,
            3: self.config.group_index if group is None else group})


class FarmingManualBehavior(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(CONFIG)
        self.m = ManualEvaluator(self.plan)
        self.m.inventory[("character", CONFIG.seed_id)] = 2

    def test_one_press_entry_plant_mature_harvest_then_open_same_shop(self):
        m = self.m
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.seed_id)), (GROWING, 1))
        self.assertEqual(m.quantity(CONFIG.crop_id), 0)
        self.assertEqual(m.timers[0][0], "player")
        self.assertEqual(m.timers[0][3:], ({"list": [{"float": 10.0}]}, CONFIG.plot_id))
        m.press()
        self.assertEqual(len(m.attempts), 1)
        m.mature()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (RIPE, 0))
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (EMPTY, 1))
        self.assertFalse(m.opened_shops)
        m.positions["character"] = CONFIG.shop_center
        m.press()
        self.assertEqual(m.opened_shops, [("player", "shop", 1)])
        self.assertEqual(m.quantity(CONFIG.crop_id), 1)
        self.assertEqual(m.inventory[("player", CONFIG.crop_id)], 0)

    def test_wrong_control_foreign_player_or_outside_has_no_mutation(self):
        m = self.m
        m.press(group=102)
        m.press(player="other-player")
        m.positions["character"] = (20, 0, 0)
        m.press()
        self.assertEqual(m.notes, ["INTERACT_MOVE_CLOSER"])
        self.assertFalse(m.attempts)
        self.assertFalse(m.opened_shops)
        self.assertFalse(m.timers)

    def test_zero_or_multiple_characters_never_select_arbitrary_bag(self):
        for characters in ([], ["character", "other-character"]):
            self.m.characters["player"] = characters
            self.m.press()
        self.assertFalse(self.m.attempts)
        self.assertFalse(self.m.opened_shops)
        self.assertFalse(self.m.notes)

    def test_nearby_boundary_is_inclusive_and_motion_alone_is_not_an_action(self):
        m = self.m
        m.positions["character"] = (5.5, 0, 0)
        self.assertFalse(m.attempts)
        m.press()
        self.assertEqual(m.stage, GROWING)
        m.mature()
        m.positions["character"] = (5.50001, 0, 0)
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (RIPE, 0))

    def test_full_bag_keeps_crop_for_a_later_new_press(self):
        m = self.m
        m.press()
        m.mature()
        m.zero_delta.add(CONFIG.crop_id)
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (RIPE, 0))
        m.zero_delta.clear()
        m.press()
        m.press()
        self.assertEqual((m.stage, m.quantity(CONFIG.crop_id)), (GROWING, 1))
        self.assertEqual(m.quantity(CONFIG.seed_id), 0)

    def test_reentrant_control_dispatch_during_686_cannot_duplicate_item_change(self):
        m = self.m
        m.on_change = lambda: m._execute(list(m.flow[("interact", 0)]))
        m.press()
        self.assertEqual(len(m.attempts), 1)
        m.mature()
        m.on_change = lambda: m._execute(list(m.flow[("interact", 0)]))
        m.press()
        self.assertEqual((len(m.attempts), m.quantity(CONFIG.crop_id)), (2, 1))

    def test_combo_filter_and_missing_seed(self):
        config = replace(CONFIG, group_combo_index=7)
        m = ManualEvaluator(build_plan(config), config)
        m.press(combo=6)
        self.assertFalse(m.notes)
        m.press(combo=7)
        self.assertEqual(m.notes, ["FARM_NO_SEEDS"])
        self.assertFalse(m.attempts)

    def test_all_bag_nodes_use_direct_258_128_character_and_timer_uses_self(self):
        data = {(e.dst, e.dst_index): (e.src, e.src_index) for e in self.plan.edges if e.src_kind == 4}
        nodes = self.plan.aliases()
        for node in self.plan.nodes:
            if node.definition_id in (686, 690):
                self.assertEqual(data[(node.alias, 0)], ("key_character", 0))
        self.assertEqual(nodes["key_character"].definition_id, 128)
        self.assertEqual(nodes["key_character_list"].definition_id, 258)
        self.assertEqual(data[("farm_growth_timer", 0)], ("owner", 0))
        self.assertEqual(data[("plot_guid", 0)], ("plot", 0))
        self.assertEqual(sum(n.definition_id == 76 for n in self.plan.nodes), 1)
        self.assertEqual(sum(n.definition_id == 316 for n in self.plan.nodes), 1)
        self.assertFalse(any(n.definition_id in (71, 248, 259, 689) for n in self.plan.nodes))


class FarmingManualPackage(unittest.TestCase):
    def test_complete_plan_is_reconstructed_exactly_from_batch_and_typed_values(self):
        plan = build_plan(CONFIG)
        result = package(CONFIG, plan)
        whole = GraphBuilder(plan, lambda _: self.fail("dispatch"), run_id="offline").batch_plan_json()
        self.assertEqual(result["batchPlan"], dict(whole, values=[]))
        rebuilt = []
        for row in result["followups"]:
            base = {k: row[k] for k in ("node", "portIndex", "slot", "value")}
            if row["nodeAlias"] == "farm_growth_timer" and row["portIndex"] == 3:
                self.assertEqual(row["slot"], "float")
                self.assertEqual(row["value"], {"list": [{"float": 10.0}]})
                base["slot"] = "auto"  # logical plan versus proven physical element writer
            rebuilt.append(base)
            # Generic comparison inputs legitimately declare type 0. Their
            # concrete source is connected before this write materializes it.
            port = default_store().require(plan.nodes[row["node"]].definition_id).port(DATA_INPUT, row["portIndex"])
            self.assertEqual(row["expect"], {"serverParamType": port.server_param_type,
                                            "genericId": port.generic_id})
        self.assertEqual(rebuilt, whole["values"])
        self.assertEqual(len(rebuilt), 102)
        json.dumps(result, allow_nan=False)

    def test_both_filter_variants_fit_real_bridge_line_limit_with_nonce_envelope(self):
        for config in (CONFIG, replace(CONFIG, group_combo_index=2147483647, group_index=2147483647)):
            result = package(config)
            self.assertLessEqual(len(result["plan"]["nodes"]), 128)
            self.assertLess(request_line_bytes({"action": "build-plan", "plan": result["batchPlan"]}), MAX_REQUEST_BYTES)
            for value in result["followups"]:
                self.assertLess(request_line_bytes(value), MAX_REQUEST_BYTES)
            self.assertFalse(result["manifest"]["runtimeVerified"])
            self.assertFalse(result["manifest"]["dispatchable"])

    def test_supplied_plan_cannot_silently_drop_requirement(self):
        plan = build_plan(CONFIG)
        plan.consts = [ConstSpec(c.alias, c.port_index, 999 if c.alias == "open_shop" else c.value,
                                c.slot) for c in plan.consts]
        with self.assertRaisesRegex(ValueError, "CONFIG_MISMATCH"):
            package(CONFIG, plan)

    def test_write_only_project_runtime_and_json_roundtrip(self):
        scratch = ROOT / ".runtime/scratch/offline-farming-20261014/farm"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="package-test-", dir=scratch) as tmp:
            paths = write_package(CONFIG, tmp)
            self.assertEqual(set(paths), {"plan", "batchPlan", "followups", "manifest"})
            loaded = {name: json.loads(Path(path).read_text(encoding="utf-8")) for name, path in paths.items()}
            self.assertEqual(loaded["plan"]["name"], DEFAULT_NAME)
            self.assertEqual(loaded["manifest"]["config"]["group_index"], 101)
        with self.assertRaisesRegex(ValueError, "PROJECT_RUNTIME"):
            write_package(CONFIG, ROOT / "tools")

    def test_invalid_config_refused(self):
        for change in ({"group_index": 0}, {"group_combo_index": True}, {"radius": 0},
                       {"shop_center": (4, 0, 0)}, {"plot_id": CONFIG.shop_id},
                       {"farm_center": (float("nan"), 0, 0)}, {"entity_guid_slot": "auto"},
                       {"growth_seconds": -1}, {"shop_index": 0}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(CONFIG, **change)


class FarmingManualBinaryVerification(unittest.TestCase):
    """Synthetic protobuf fixtures test the reader, not actual game creation."""
    def setUp(self):
        scratch = ROOT / ".runtime/scratch/offline-farming-20261014/farm"
        scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="export-fixture-", dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.gia"
        self.plan = build_plan(CONFIG)
        self.mapping = {n.alias: 9000 - i * 7 for i, n in enumerate(self.plan.nodes)}
        self.receipt = {"ok": True, "graphId": 1073741888, "nodeIds": self.mapping}
        pb = _export_loader().pb
        self.bundle = pb.AssetBundle()
        self.bundle.primary_resource.resource_class = pb.ResourceEntry.ENTITY_NODE_GRAPH
        self.graph = self.bundle.primary_resource.graph_data.inner.graph
        self.graph.identity.runtime_id = self.receipt["graphId"]
        self.graph.identity.source_domain = 10000
        self.graph.identity.service_domain = 20000
        self.graph.identity.kind = 21001
        self.graph.display_name = DEFAULT_NAME
        self.types, choices, kernels, _, _ = _type_contract(self.plan)
        self.nodes = {}
        self.pins = {}
        for spec in self.plan.nodes:
            node = self.graph.nodes.add()
            node.index = self.mapping[spec.alias]
            node.shell_ref.runtime_id = spec.definition_id
            node.kernel_ref.runtime_id = kernels[spec.alias]
            for identity in (node.shell_ref, node.kernel_ref):
                identity.source_domain = 10001
                identity.service_domain = 20000
                identity.kind = 22000
            self.nodes[spec.alias] = node
        def pin(address):
            if address in self.pins:
                return self.pins[address]
            alias, kind, index = address
            result = self.nodes[alias].pins.add()
            for signature in (result.shell_sig, result.kernel_sig):
                signature.kind, signature.index = kind, index
            if kind in (3, 4):
                result.type = self.types[address]
            if address in choices:
                result.value.widget = 10000
                result.value.is_value_set = 1
                result.value.val_poly.chosen_type_index = choices[address]
                result.value.val_poly.actual_value.type_def.backend = 1
                result.value.val_poly.actual_value.type_def.server_side.type_tag = self.types[address]
            self.pins[address] = result
            return result
        for address in choices:
            pin(address)
        for edge in self.plan.edges:
            source = (edge.src, edge.src_kind, edge.src_index)
            target = (edge.dst, edge.dst_kind, edge.dst_index)
            host, remote = (target, source) if edge.src_kind == 4 else (source, target)
            link = pin(host).connections.add()
            link.target_node_index = self.mapping[remote[0]]
            for signature in (link.target_pin_shell, link.target_pin_kernel):
                signature.kind, signature.index = remote[1:]
        for row in package(CONFIG)["followups"]:
            address = (row["nodeAlias"], 3, row["portIndex"])
            value = pin(address).value
            if address in choices:
                value = value.val_poly.actual_value
            self.set_value(value, row["value"], row["slot"], self.types[address])

    def set_value(self, value, expected, slot, typ):
        value.is_value_set = 1
        value.type_def.backend = 1
        value.type_def.server_side.type_tag = typ
        tag, wanted = next(iter(expected.items()))
        if tag == "list":
            value.widget = 10002
            for child in wanted:
                self.set_value(value.val_list.elements.add(), child, "float", 5)
            return
        branch, widget, field = {"uint": ("val_id", 1, "id"), "int": ("val_int", 2, "int"),
            "float": ("val_float", 4, "float"), "string": ("val_string", 5, "str"),
            "enum": ("val_enum", 6, "enum")}["enum" if slot == "enum" else tag]
        value.widget = widget
        setattr(getattr(value, branch), field, wanted)

    def write_fixture(self):
        payload = self.bundle.SerializeToString()
        self.path.write_bytes(struct.pack(">5I", len(payload) + 20, 1, 0x326, 3, len(payload)) +
                              payload + struct.pack(">I", 0x679))
        return self.path

    def verify(self):
        return verify_export(self.write_fixture(), CONFIG, build_receipt=self.receipt)

    def test_binary_fixture_uses_actual_sparse_ids_and_complete_types(self):
        result = self.verify()
        self.assertTrue(result["serializedContentVerified"])
        self.assertEqual(result["actualNodeIds"], self.mapping)
        self.assertEqual((result["kernelsChecked"], result["genericChoicesChecked"],
                          result["plannedConstantsChecked"]), (93, 60, 102))
        self.assertFalse(result["saveVerified"])
        self.assertFalse(result["playtestVerified"])
        # These specializations were independently seen in the saved R7 graph.
        self.assertEqual(self.nodes["key_character"].kernel_ref.runtime_id, 130)
        self.assertEqual(self.nodes["near_farm_compare"].kernel_ref.runtime_id, 236)
        self.assertEqual(self.nodes["farm_empty_equal"].kernel_ref.runtime_id, 370)

    def test_missing_receipt_mapping_is_not_replaced_by_index_plus_one(self):
        self.receipt["nodeIds"] = {}
        with self.assertRaisesRegex(ValueError, "ALIAS_MAPPING"):
            self.verify()

    def test_kernel_or_type_or_generic_choice_mutation_fails(self):
        node = self.nodes["near_farm_compare"]
        node.kernel_ref.runtime_id = 231
        with self.assertRaisesRegex(ValueError, "ACTUAL_KERNEL"):
            self.verify()
        node.kernel_ref.runtime_id = 236
        pin = self.pins[("key_character", 4, 0)]
        pin.type = 2
        with self.assertRaisesRegex(ValueError, "ACTUAL_PIN_TYPE"):
            self.verify()
        pin.type = 1
        pin.value.val_poly.chosen_type_index = 0
        with self.assertRaisesRegex(ValueError, "GENERIC_CHOICE"):
            self.verify()

    def test_wrong_crop_count_and_timer_element_type_fail(self):
        pin = self.pins[("farm_harvest_change", 3, 2)]
        setattr(pin.value.val_int, "int", 2)
        with self.assertRaisesRegex(ValueError, "VALUE_MISMATCH"):
            self.verify()
        setattr(pin.value.val_int, "int", 1)
        timer = self.pins[("farm_growth_timer", 3, 3)].value
        timer.val_list.elements[0].type_def.server_side.type_tag = 3
        with self.assertRaisesRegex(ValueError, "VALUE_TYPE"):
            self.verify()

    def test_bypassing_manual_entry_or_injecting_extra_constant_fails(self):
        flow = next(p for p in self.nodes["interact_group"].pins if p.shell_sig.kind == 2)
        original = flow.connections[0].target_node_index
        flow.connections[0].target_node_index = self.mapping["farm_harvest_change"]
        with self.assertRaisesRegex(ValueError, "EDGES_NOT_EXACT"):
            self.verify()
        flow.connections[0].target_node_index = original
        connected = self.pins[("farm_plant_change", 3, 0)]
        self.set_value(connected.value, {"uint": 999}, "uint", 1)
        with self.assertRaisesRegex(ValueError, "UNPLANNED_CONSTANT"):
            self.verify()

    def test_json_plan_is_not_accepted_as_a_game_export(self):
        self.path.write_text(json.dumps(package(CONFIG)["plan"]), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "container"):
            verify_export(self.path, CONFIG, build_receipt=self.receipt)

    def test_real_preserved_shop_export_is_a_negative_control(self):
        from tools.gameplan.demo.shop_key_patch import BASE_GIA
        self.receipt["graphId"] = 1073741834
        with self.assertRaisesRegex(ValueError, "ACTUAL_GRAPH_NAME"):
            verify_export(BASE_GIA, CONFIG, build_receipt=self.receipt)


if __name__ == "__main__":
    unittest.main()
