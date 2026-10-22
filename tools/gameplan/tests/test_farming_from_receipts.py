"""Offline composition and actual raw-acceptor checks; all receipts are synthetic."""
from __future__ import annotations

import contextlib
import copy
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.gameplan import cli
from tools.gameplan.demo import farming_from_receipts as farm

SCRATCH = farm.ROOT / ".runtime/scratch/overnight-features-20261013/task-bf/tests"
SESSION = {"schemaVersion": 1, "pid": 9009, "tid": 8008, "window": 7007,
    "windowClass": "UnityWndClass", "processCreation": 12345, "threadCreation": 23456,
    "image": "D:/games/Genshin Impact Game/YuanShen.exe"}
CHARACTER, PLOT = 1090519041, 1075838999


class FarmingFromReceiptsTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.assertTrue(self.base.is_relative_to(SCRATCH.resolve()))
        self.reports = {}
        self.runs = {}
        self.args = dict(character_entity_id=CHARACTER, plot_entity_id=PLOT,
            farm_trigger_index=1, sell_trigger_index=2, item_slot="uint", currency_slot="uint",
            variable_flag_slot="enum", shop_flag_slot="enum")
        real = farm._acceptors()
        for key, action, resource in (
            ("currency", "create-currency", 0x42800001), ("seed", "create-item", 0x42000001),
            ("crop", "create-item", 0x42000002), ("bag", "bind-bag", 1119879169),
            ("shop", "bind-shop", 1136656385)):
            run = self.base / key; run.mkdir(); self.runs[key] = run
            self.args[key + "_run"] = run
            (run / "prepared.json").write_text(json.dumps({"levelId": 1073741842, "session": SESSION}), encoding="utf-8")
            (run / "stdout.jsonl").write_text("synthetic raw dependency fixture " + key, encoding="utf-8")
            result = dict(ok=True, action=action, run=str(run), levelId=1073741842,
                requestSha256="a" * 64, reviewSha256="b" * 64, acceptorSha256="c" * 64,
                inputHashes={name: farm._hash(run / name) for name in ("prepared.json", "stdout.jsonl")})
            if key in ("currency", "seed", "crop"):
                result.update(createdId=resource, catalogRegisteredVerified=True)
            else:
                result.update(entityId=CHARACTER if key == "bag" else PLOT,
                    templateId=resource, componentId=1001 if key == "bag" else 1002,
                    shopIndex=0 if key == "bag" else 7, bindingVerified=True,
                    playerCharacterVerified=False, persistentSaveVerified=False)
            self.reports[run] = result
            # Deliberately wrong cache; the production entry must never consult it.
            (run / (key + "-acceptance.json")).write_text(json.dumps({"ok": True, "createdId": 999}), encoding="utf-8")
        def validated(run):
            return copy.deepcopy(self.reports[Path(run)])
        self.modules = {key: SimpleNamespace(validate_run=Mock(side_effect=validated), requests=real[key].requests)
                        for key in ("currency", "item", "binding")}
        self.enterContext(patch.object(farm, "_acceptors", return_value=self.modules))

    def result(self, **changes):
        return farm.compile_from_receipts(**dict(self.args, **changes))

    def prepared(self, key, **changes):
        run = self.runs[key]
        value = json.loads((run / "prepared.json").read_text())
        value.update(changes)
        (run / "prepared.json").write_text(json.dumps(value), encoding="utf-8")
        self.reports[run]["inputHashes"]["prepared.json"] = farm._hash(run / "prepared.json")

    def test_five_raw_validation_calls_produce_real_native_shop_graph_and_compile_cli(self):
        with patch.object(farm.GraphBuilder, "build_batch", side_effect=AssertionError("no dispatch")):
            result = self.result(starter_seed_count=3)
        self.assertEqual([self.modules[k].validate_run.call_count for k in ("currency", "item", "binding")], [1, 2, 2])
        self.assertEqual((result["config"]["seed_id"], result["config"]["crop_id"], result["config"]["currency_id"]),
                         (0x42000001, 0x42000002, 0x42800001))
        self.assertEqual(result["bindings"]["shopIndex"], 7)  # native index, never list position/default1
        definitions = [node["definitionId"] for node in result["plan"]["nodes"]]
        for definition in (92, 708, 710, 702, 259): self.assertEqual(definitions.count(definition), 1)
        for definition in (686, 688): self.assertIn(definition, definitions)
        self.assertEqual((result['config']['starter_seed_count'], result['config']['starter_currency_amount']), (3, 20))
        self.assertNotIn("--execute", result["cliArgs"])
        self.assertNotIn("--run-id", result["cliArgs"])
        args = cli.build_parser().parse_args(result["cliArgs"])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), patch.object(cli, "subprocess_runner", side_effect=AssertionError("no runner")):
            self.assertEqual(cli.cmd_farming_interactive(args), 0)
        self.assertEqual(json.loads(stream.getvalue())["plan"], result["plan"])
        self.assertFalse(result["deploymentReady"] or result["editorDispatchAttempted"] or result["persistentSaveVerified"])
        self.assertFalse(result["prerequisites"]["event92Delivery"]["verified"])
        self.assertFalse(result["prerequisites"]["characterBackpack"]["playableAssignmentVerified"])

    def test_cross_level_and_process_creation_refused(self):
        self.reports[self.runs["crop"]]["levelId"] += 1
        self.prepared("crop", levelId=1073741843)
        with self.assertRaisesRegex(ValueError, "FARM_CROSS_LEVEL:crop"): self.result()
        self.reports[self.runs["crop"]]["levelId"] = 1073741842
        self.prepared("crop", levelId=1073741842, session=dict(SESSION, processCreation=12346))
        with self.assertRaisesRegex(ValueError, "FARM_CROSS_SESSION:crop"): self.result()

    def test_explicit_character_and_plot_binding_constraints(self):
        with self.assertRaisesRegex(ValueError, "FARM_BAG_OWNER_NOT_EXPECTED_CHARACTER"):
            self.result(character_entity_id=CHARACTER + 1)
        with self.assertRaisesRegex(ValueError, "FARM_SHOP_OWNER_NOT_EXPECTED_PLOT"):
            self.result(plot_entity_id=PLOT + 1)
        with self.assertRaisesRegex(ValueError, "FARM_CHARACTER_AND_PLOT_MUST_DIFFER"):
            self.result(character_entity_id=PLOT)

    def test_different_seed_crop_and_actual_positive_shop_index_required(self):
        self.reports[self.runs["crop"]]["createdId"] = 0x42000001
        with self.assertRaisesRegex(ValueError, "seed and crop item ids must differ"): self.result()
        self.reports[self.runs["crop"]]["createdId"] = 0x42000002
        self.reports[self.runs["shop"]]["shopIndex"] = 0
        with self.assertRaises(ValueError): self.result()

    def test_raw_validator_failure_cannot_be_overridden_by_cached_success(self):
        self.modules["item"].validate_run.side_effect = ValueError("ITEM_CREATED_ID_MISMATCH")
        with self.assertRaisesRegex(ValueError, "ITEM_CREATED_ID_MISMATCH"): self.result()

    def test_receipt_change_during_other_validation_is_refused(self):
        original = self.modules["binding"].validate_run.side_effect
        def change(run):
            (self.runs["currency"] / "stdout.jsonl").write_text("changed", encoding="utf-8")
            return original(run)
        self.modules["binding"].validate_run.side_effect = change
        with self.assertRaisesRegex(ValueError, "FARM_RECEIPT_CHANGED"): self.result()

    def test_region_indices_required_and_not_claimed_verified(self):
        with self.assertRaisesRegex(ValueError, "trigger indices must differ"):
            self.result(sell_trigger_index=1)
        self.assertFalse(self.result()["prerequisites"]["triggerRegions"]["verified"])
        args = dict(self.args); del args["farm_trigger_index"]
        with self.assertRaises(TypeError): farm.compile_from_receipts(**args)

    def test_runtime_bounds_duplicate_runs_and_wrong_action(self):
        with self.assertRaisesRegex(ValueError, "OUTSIDE_PROJECT_RUNTIME"):
            self.result(currency_run=farm.ROOT / "GOAL.md")
        with self.assertRaisesRegex(ValueError, "DISTINCT_ACTION_RUNS"):
            self.result(crop_run=self.runs["seed"])
        self.reports[self.runs["shop"]]["action"] = "bind-bag"
        with self.assertRaisesRegex(ValueError, "WRONG_VALIDATED_ACTION"): self.result()

    def test_public_entry_has_no_execute_and_rejects_output_inside_evidence(self):
        argv = []
        for name, value in self.args.items(): argv.extend(("--" + name.replace("_", "-"), str(value)))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            farm.build_parser().parse_args(argv + ["--execute"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = farm.main(argv + ["--out", str(self.runs["bag"] / "new-output.json")])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "FARM_OUTPUT_OVERLAPS_EVIDENCE")
        self.assertFalse((self.runs["bag"] / "new-output.json").exists())


class ActualRawReceiptDependencyTests(unittest.TestCase):
    def test_actual_currency_raw_validation_is_called_and_detects_tampering(self):
        # Reuse the existing full raw ABI/envelope fixture. Its compiler/session
        # producers are mocked; the real validate_run is used here, disk-only.
        real = farm._acceptors()
        sys.path.insert(0, str(farm.AUTHORING / "tests"))
        fixture_module = importlib.import_module("test_accept_currency")
        fixture = fixture_module.AcceptCurrencyTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        run = fixture.run.resolve()
        (run / "currency-acceptance.json").write_text('{"ok":true,"createdId":999}', encoding="utf-8")
        with patch.object(real["currency"].profiles, "windows_api", side_effect=AssertionError("no Windows API")):
            validated = farm._validated(real["currency"], run, "create-currency")
        self.assertEqual(validated["accepted"]["createdId"], 0x42800001)
        fixture.record["templateResult"]["createdId"] = 999
        fixture.save_record()
        with self.assertRaisesRegex(ValueError, "CURRENCY_RAW_SUMMARY_MISMATCH:createdId"):
            farm._validated(real["currency"], run, "create-currency")


if __name__ == "__main__":
    unittest.main()
