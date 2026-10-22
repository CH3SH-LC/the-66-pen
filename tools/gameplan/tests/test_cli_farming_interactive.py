"""Offline CLI tests. Asset/entity ids here are synthetic; no native call runs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.gameplan import cli
from tools.gameplan.testing import FakeBridge

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = ROOT / ".runtime" / "scratch" / "overnight-features-20261013" / "task-g"
RUN = "a8288474-a158-452e-b0c8-7b626b36b6dd"
BASE = ["farming-interactive", "--seed-id", "101", "--crop-id", "102",
        "--currency-id", "201", "--item-slot", "int", "--currency-slot", "int",
        "--variable-flag-slot", "enum", "--name", "MW_API_CLI_INTERACTIVE_TEST"]


def invoke(argv, runner=None):
    args = cli.build_parser().parse_args(argv)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.cmd_farming_interactive(args, runner=runner)
    return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()


class FarmingInteractiveCli(unittest.TestCase):
    def test_default_compiles_real_batch_payload_without_any_runner(self):
        with patch.object(cli, "subprocess_runner", side_effect=AssertionError("no runner in compile mode")), \
             patch.object(cli.GraphBuilder, "build_batch", side_effect=AssertionError("no build in compile mode")):
            code, report, err = invoke(BASE + ["--growth-seconds", "3.5",
                "--farm-trigger-index", "2", "--sell-trigger-index", "3"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual((report["mode"], report["buildMode"]), ("compile", "batch"))
        self.assertFalse(report["editorDispatchAttempted"])
        self.assertFalse(report["gameRuntimeVerified"])
        self.assertFalse(report["persistentSaveVerified"])
        self.assertEqual(report["inventoryHolder"], "entrant")
        self.assertFalse(report["starterResources"]["enabled"])
        self.assertEqual(report["starterResources"]["guardName"], "MW_FARM_STARTER_V1")
        nodes = report["plan"]["nodes"]
        self.assertEqual(sum(n["definitionId"] == 92 for n in nodes), 1)
        self.assertEqual(sum(n["definitionId"] == 259 for n in nodes), 0)
        timer = next(i for i, n in enumerate(nodes) if n["definitionId"] == 79)
        value = next(v for v in report["plan"]["values"] if v["node"] == timer and v["portIndex"] == 3)
        self.assertEqual(value["value"], {"list": [{"float": 3.5}]})
        self.assertEqual(report["prerequisites"]["triggers"]["farmIndex"], 2)
        self.assertEqual(report["prerequisites"]["templates"]["status"], "requires-independent-readback")

    def test_ids_and_all_storage_slots_are_required(self):
        for option in ("--seed-id", "--crop-id", "--currency-id", "--item-slot",
                       "--currency-slot", "--variable-flag-slot"):
            args = BASE.copy()
            index = args.index(option)
            del args[index:index + 2]
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    cli.build_parser().parse_args(args)
                self.assertEqual(failure.exception.code, 2)

    def test_native_shop_compiles_catalog_and_opening_without_second_payment(self):
        code, report, err = invoke(BASE + ["--sale-mode", "native_shop", "--shop-flag-slot", "enum",
            "--seed-price", "2", "--sale-price", "10", "--shop-index", "3"])
        self.assertEqual((code, err), (0, ""))
        plan = report["plan"]
        ids = [n["definitionId"] for n in plan["nodes"]]
        for definition in (708, 710, 702, 259):
            self.assertEqual(ids.count(definition), 1)
        self.assertNotIn(688, ids)
        for definition, expected in ((708, 2), (710, 10)):
            index = ids.index(definition)
            price = next(v for v in plan["values"] if v["node"] == index and v["portIndex"] == 3)
            self.assertEqual(price["value"], {"dict": [{"key": {"uint": 201}, "value": {"int": expected}}]})
        self.assertEqual(report["prerequisites"]["shopComponent"]["shopIndex"], 3)
        self.assertEqual(report["prerequisites"]["startingResources"]["oneOf"],
                         [{"seedCount": 1}, {"currencyAmount": 2}])
        self.assertFalse(report["editorDispatchAttempted"])

    def test_native_shop_requires_explicit_boolean_descriptor_slot(self):
        fake = FakeBridge()
        code, report, error = invoke(BASE + ["--sale-mode", "native_shop"], runner=fake)
        self.assertEqual(code, 2)
        self.assertIsNone(report)
        self.assertIn("shop_flag_slot", error)
        self.assertEqual(fake.calls, [])

    def test_skill_entry_has_explicit_target_and_no_trigger_prerequisite(self):
        code, report, err = invoke(BASE + ["--interaction-mode", "skill", "--skill-target", "plot-a",
            "--sale-mode", "native_shop", "--shop-flag-slot", "enum"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(report["interactionMode"], "skill")
        ids = [n["definitionId"] for n in report["plan"]["nodes"]]
        self.assertEqual(ids.count(392), 1)
        self.assertNotIn(92, ids)
        self.assertNotIn(688, ids)
        self.assertNotIn("triggers", report["prerequisites"])
        callback = report["prerequisites"]["skillNotification"]
        self.assertEqual(callback["parameter2"], "plot-a")
        self.assertFalse(callback["templateCreated"])
        self.assertFalse(report["gameRuntimeVerified"])
        self.assertFalse(report["editorDispatchAttempted"])

    def test_skill_entry_requires_target_before_dispatch(self):
        fake = FakeBridge()
        code, report, error = invoke(BASE + ["--interaction-mode", "skill"], runner=fake)
        self.assertEqual(code, 2)
        self.assertIsNone(report)
        self.assertIn("skill_target", error)
        self.assertEqual(fake.calls, [])

    def test_execute_rejects_missing_invalid_scope_target_and_bad_gameplay_before_dispatch(self):
        cases = [
            ["--execute"],
            ["--execute", "--run-id", "not-a-uuid", "--entity-id", "10"],
            ["--execute", "--run-id", "0" * 32, "--entity-id", "10"],
            ["--execute", "--run-id", RUN],
            ["--execute", "--run-id", RUN, "--entity-id", "0"],
            ["--execute", "--run-id", RUN, "--entity-id", "4294967296"],
            ["--seed-id", "0"], ["--growth-seconds", "nan"],
            ["--growth-seconds", "-1"], ["--sale-count", "0"],
            ["--farm-trigger-index", "2"], ["--farm-trigger-index", "0"], ["--name", "bad-name"],
            ["--out", "GOAL.md"],
            ["--starter-seeds", "-1"], ["--starter-currency", "2147483648"],
            ["--starter-guard", " "],
        ]
        for extra in cases:
            fake = FakeBridge()
            with self.subTest(extra=extra), patch.object(cli, "subprocess_runner",
                    side_effect=AssertionError("no subprocess runner for invalid requests")):
                code, report, error = invoke(BASE + extra, runner=fake)
                self.assertEqual(code, 2)
                self.assertIsNone(report)
                self.assertIn("nothing was dispatched", error)
                self.assertEqual(fake.calls, [])

    def test_enabled_starter_options_report_character_scope_and_compile_each_mode(self):
        for interaction in ("proximity", "skill"):
            for sale in ("direct", "native_shop"):
                extra = ["--starter-seeds", "3", "--starter-currency", "20",
                         "--starter-guard", "SHARED_STARTER", "--interaction-mode", interaction,
                         "--sale-mode", sale]
                if interaction == "skill":
                    extra += ["--skill-target", "field-one"]
                if sale == "native_shop":
                    extra += ["--shop-flag-slot", "enum"]
                with self.subTest(interaction=interaction,sale=sale), patch.object(
                        cli,"subprocess_runner",side_effect=AssertionError("compile must stay offline")):
                    code, report, error = invoke(BASE+extra)
                self.assertEqual((code,error),(0,""))
                starter = report["starterResources"]
                self.assertTrue(starter["enabled"])
                self.assertEqual((starter["seedCount"],starter["currencyAmount"]),(3,20))
                self.assertEqual(starter["guardName"],"SHARED_STARTER")
                self.assertEqual(starter["guardScope"],"character-lifetime-shared-across-plots")
                self.assertEqual(starter["recipient"],"skill-caster-character" if interaction=="skill" else "entrant-character")
                self.assertIn("not-automatically-retried",starter["failurePolicy"])
                self.assertIn("new-character-can-claim-again",starter["lifecycleBoundary"])
                self.assertFalse(starter["nativeDeliveryVerified"])
                self.assertFalse(report["editorDispatchAttempted"])
                prerequisite = "startingResources" if sale=="native_shop" else "startingSeeds"
                self.assertEqual(report["prerequisites"][prerequisite]["status"],
                                 "starter-grant-configured-runtime-unverified")
                definitions = [n["definitionId"] for n in report["plan"]["nodes"]]
                values = report["plan"]["values"]
                self.assertEqual(sum(definitions[v["node"]]==22 and v["portIndex"]==1
                                     and v["value"]=={"string":"SHARED_STARTER"} for v in values),1)
                self.assertEqual(sum(definitions[v["node"]]==686 and v["portIndex"]==2
                                     and v["value"]=={"int":3} for v in values),1)
                self.assertEqual(sum(definitions[v["node"]]==688 and v["portIndex"]==2
                                     and v["value"]=={"int":20} for v in values),1)

    def test_starter_rejects_inconsistent_player_holder_before_dispatch(self):
        for option in ("--starter-seeds","--starter-currency"):
            fake = FakeBridge()
            code, report, error = invoke(BASE+["--inventory-holder","character_owner",option,"3"],
                                         runner=fake)
            self.assertEqual(code,2)
            self.assertIsNone(report)
            self.assertIn("STARTER_REQUIRES_CHARACTER_INVENTORY",error)
            self.assertEqual(fake.calls,[])

    def test_execute_uses_one_batch_build_then_independent_readback_and_binding(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            scratch = Path(temporary)
            fake = FakeBridge()
            with patch.object(cli, "_repo_default_scratch", return_value=scratch), \
                 patch("tools.gameplan.builder.DEFAULT_JOURNAL_DIR", scratch / "empty-journal"):
                code, report, err = invoke(BASE + ["--execute", "--run-id", RUN,
                    "--entity-id", "1077936215"], runner=fake)
            self.assertEqual((code, err), (0, ""))
            actions = [FakeBridge.action_of(call) for call in fake.calls]
            self.assertEqual(actions, ["create", "lookup", "build-plan", "inspect", "export", "bind"])
            self.assertEqual(actions.count("build-plan"), 1)
            self.assertEqual(fake.calls[-1][fake.calls[-1].index("--entity-id") + 1], "1077936215")
            self.assertTrue(report["build"]["ok"])
            self.assertTrue(report["editorDispatchAttempted"])
            self.assertFalse(report["persistentSaveVerified"])
            self.assertFalse(report["gameRuntimeVerified"])
            written = json.loads((scratch / "MW_API_CLI_INTERACTIVE_TEST-plan.json").read_text(encoding="utf-8"))
            self.assertEqual(len(written["nodes"]), report["summary"]["nodes"])

    def test_optional_compile_output_is_project_runtime_artifact(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SCRATCH) as temporary:
            destination = Path(temporary) / "compiled.json"
            relative = str(destination.relative_to(ROOT))
            code, report, err = invoke(BASE + ["--out", relative])
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), report)
            self.assertEqual(cli._interactive_output_path(relative), destination.resolve())


if __name__ == "__main__":
    unittest.main()
