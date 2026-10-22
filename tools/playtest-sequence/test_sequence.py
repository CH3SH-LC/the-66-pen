"""Private command fixtures only; never invokes native/game/queue processes."""
import copy
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("playtest_transaction", Path(__file__).with_name("sequence.py"))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
EVIDENCE = s.ROOT / ".runtime/ptsq-tests" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
EVIDENCE.mkdir(parents=True, exist_ok=False)
PLAN = dict(schemaVersion=1, levelId=s.LEVEL, operation="buy",
            item=dict(configId=100, resourceType=3), currency=dict(configId=200, resourceType=8),
            unitPrice=12, shopId=5, shopOwnerId=6)


class Fixture:
    private_fixture = True

    def __init__(self, case):
        self.case, self.calls, self.cards, self.replies = case, [], {}, {}
        self.screen, self.quantity, self.item, self.currency = "inventory-page", 5, 10, 50
        self.confirmed, self.actions, self.delay = False, [], 0
        self.duplicate, self.wrong_owner, self.wrong_delta = False, False, False
        self.unknown_action, self.mutate_session, self.wrong_card = None, False, False

    def inventory(self):
        item, currency = self.item, self.currency
        if self.confirmed:
            if self.delay:
                self.delay -= 1
            else:
                buy = self.case.plan["operation"] == "buy"
                item += 1 if buy else -1
                currency += (-1 if buy else 1) * (12 + int(self.wrong_delta))
        return dict(inventoryComplete=True, inventoryQuantitiesVerified=True,
                    physicalItemCounts=[dict(configId=100, resourceType=3, quantity=str(item))],
                    paymentResourceCounts=[dict(configId=200, resourceType=8, quantity=str(currency))])

    def ui(self):
        rows = [dict(role=role, configId=100, resourceType=3, active=1, enabled=1,
                     handlerVerified=1, text="12" if role == 1 else "苹果") for role in (1, 2)]
        if self.duplicate:
            rows.extend(copy.deepcopy(rows))
        return dict(complete=1, status=0, shopId=5, ownerId=99 if self.wrong_owner else 6,
                    screen=self.screen, configId=100, resourceType=3, rows=rows, text="苹果",
                    quantity=self.quantity)

    def call(self, args, log):
        self.calls.append(list(args))
        command = args[0]
        flags = dict(zip(args[1::2], args[2::2]))
        if self.mutate_session:
            self.case.session.write_text("changed", encoding="utf-8")
            self.mutate_session = False
        if command == "prepare":
            run = self.case.cards / str(len(self.cards))
            run.mkdir()
            op = flags["--operation"]
            prepared = dict(kind="playtest-control-prepared-v6" if op == "inventory-state" else "playtest-control-prepared-v7",
                            mode=op, targetLevelId=42 if self.wrong_card else s.LEVEL,
                            anchorRun=str(self.case.anchor), launchable=True, compileOnly=False,
                            action=19, receiptVersion=24, explicitPrivateFixture=True)
            s.write(run / "prepared.json", prepared)
            self.cards[str(run)] = (op, flags)
            return dict(ok=True, mode=op, run=str(run), launchable=True,
                        preparedSha256=s.digest(run / "prepared.json"))
        if command == "dispatch":
            run = Path(flags["--run"])
            op, prepared_flags = self.cards[str(run)]
            result = dict(ok=True, cleanupVerified=True, safeToRelease=True, outcomeUncertain=False,
                          mode="play", trialIdentityBound=True, playerBelongsToTargetLevel=True,
                          operation=op, run=str(run), targetLevelId=s.LEVEL, nativeStarted=True)
            if op == "inventory-state":
                result.update(self.inventory())
            elif op == "shop-state":
                result["uiState"] = self.ui()
            else:
                action = prepared_flags["--ui-action"]
                self.actions.append(action)
                result.update(uiAction=action, uiActionReturned=True)
                if action == "goods":
                    self.screen = "buy-confirmation"
                elif action == "bag-item":
                    self.screen = "item-details"
                elif action == "sell-open":
                    self.screen = "sell-confirmation"
                elif action == "quantity-one":
                    self.quantity = 1
                elif action in ("buy", "sell"):
                    self.confirmed = True
                if action == self.unknown_action:
                    result["outcomeUncertain"] = True
            (run / "acceptance.bin").write_bytes(b"explicit-private-fixture")
            s.write(run / "stdout.jsonl", dict(explicitPrivateFixture=True, operation=op))
            s.write(run / "exit.json", dict(explicitPrivateFixture=True))
            result.update(binaryReceiptSha256=s.digest(run / "acceptance.bin"),
                          rawReceiptSha256=s.digest(run / "stdout.jsonl"))
            self.replies[str(run)] = result
            return result
        if command == "decode":
            return copy.deepcopy(self.replies[flags["--run"]])
        if command == "inventory-diff":
            before, after = [self.replies[flags[key]] for key in ("--before-run", "--after-run")]
            queries = s.read(flags["--queries"])
            changes = []
            for query, field in zip(queries, ("physicalItemCounts", "paymentResourceCounts")):
                a, z = [int(doc[field][0]["quantity"]) for doc in (before, after)]
                changes.append(dict(query, before=str(a), after=str(z), delta=str(z-a)))
            return dict(ok=True, cleanupVerified=True, safeToRelease=True, outcomeUncertain=False,
                        operation="inventory-diff", targetLevelId=s.LEVEL, changes=changes)
        raise AssertionError(command)


class Cases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=EVIDENCE, prefix="c-")
        # Keep fixture evidence rather than deleting files during test teardown.
        self.tmp._finalizer.detach()
        self.base = Path(self.tmp.name)
        self.cards = self.base / "cards"
        self.cards.mkdir()
        self.anchor = self.cards / "anchor"
        self.anchor.mkdir()
        s.write(self.anchor / "prepared.json", dict(explicitPrivateFixture=True))
        self.session = self.base / "session.json"
        s.write(self.session, dict(explicitPrivateFixture=True))
        self.queue = s.ROOT / ".runtime/editor-bridge" / ("ptsq-" + self.base.name)
        self.queue.mkdir(exist_ok=False)
        self.freeze = self.base / "freeze.json"
        own = dict(path=str(s.CLI), sha256=s.digest(s.CLI))
        s.write(self.freeze, dict(status="offline-verified-live-unverified",
                route="native-map/playtest-control", owned=[own], sharedDependencies=[own],
                graphVectorValuesTree=[own]))
        self.patchers = [patch.object(s, "CARDS", self.cards), patch.object(s, "OUTPUT", self.base / "out")]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)
        self.plan = copy.deepcopy(PLAN)
        self.fixture = Fixture(self)

    def run_case(self, ident="once", **override):
        kwargs = dict(operation_id=ident, session_file=self.session, trial_anchor=self.anchor,
                      queue=self.queue, freeze_path=self.freeze, freeze_sha256=s.digest(self.freeze),
                      _commands=self.fixture)
        kwargs.update(override)
        return s.run(self.plan, **kwargs)

    def test_buy_full_sequence_and_independent_delta(self):
        result = self.run_case()
        self.assertTrue(result["ok"])
        self.assertTrue(result["privateFixture"])
        self.assertFalse(result["wholeGameAccepted"])
        self.assertEqual(self.fixture.actions, ["goods", "quantity-one", "buy"])
        self.assertEqual(result["comparisons"][-1]["delta"], [1, -12])
        self.assertEqual(sum(c[0] == "inventory-diff" for c in self.fixture.calls), 1)

    def test_sell_full_sequence(self):
        self.plan["operation"] = "sell"
        result = self.run_case()
        self.assertTrue(result["ok"])
        self.assertEqual(self.fixture.actions, ["bag-item", "sell-open", "quantity-one", "sell"])
        self.assertEqual(result["comparisons"][-1]["delta"], [-1, 12])

    def test_quantity_one_skips_slider(self):
        self.fixture.quantity = 1
        self.assertTrue(self.run_case()["ok"])
        self.assertEqual(self.fixture.actions, ["goods", "buy"])

    def test_delayed_settlement_only_reobserves(self):
        self.fixture.delay = 2
        result = self.run_case()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["comparisons"]), 3)
        self.assertEqual(self.fixture.actions.count("buy"), 1)

    def test_wrong_delta_stops_without_reconfirm(self):
        self.fixture.wrong_delta = True
        result = self.run_case()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "UNEXPECTED_INVENTORY_DELTA")
        self.assertEqual(self.fixture.actions.count("buy"), 1)

    def test_no_settlement_is_not_success(self):
        self.fixture.delay = 20
        result = self.run_case()
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "EXPECTED_DELTAS_NOT_OBSERVED")
        self.assertEqual(len(result["comparisons"]), 4)

    def test_unknown_confirmation_stops_and_cannot_replay_operation(self):
        self.fixture.unknown_action = "buy"
        result = self.run_case()
        self.assertFalse(result["ok"])
        count = len(self.fixture.calls)
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.assertEqual(len(self.fixture.calls), count)
        self.assertEqual(self.fixture.actions.count("buy"), 1)

    def test_other_shop_refused_before_ui_action(self):
        self.fixture.wrong_owner = True
        result = self.run_case()
        self.assertEqual(result["code"], "SHOP_IDENTITY_CHANGED")
        self.assertEqual(self.fixture.actions, [])

    def test_multiple_matching_rows_refused(self):
        self.fixture.duplicate = True
        self.assertEqual(self.run_case()["code"], "VISIBLE_ITEM_NOT_UNIQUE")
        self.assertEqual(self.fixture.actions, [])

    def test_bad_card_identity_never_dispatches(self):
        self.fixture.wrong_card = True
        self.assertEqual(self.run_case()["code"], "PREPARED_TARGET_OR_PROTOCOL_MISMATCH")
        self.assertFalse(any(c[0] == "dispatch" for c in self.fixture.calls))

    def test_identity_change_between_calls_never_dispatches(self):
        self.fixture.mutate_session = True
        self.assertEqual(self.run_case()["code"], "TRANSACTION_SOURCE_OR_IDENTITY_CHANGED")
        self.assertFalse(any(c[0] == "dispatch" for c in self.fixture.calls))

    def test_balance_checked_before_ui(self):
        self.fixture.currency = 0
        self.assertEqual(self.run_case()["code"], "STARTING_BALANCE_INSUFFICIENT")
        self.assertEqual(self.fixture.actions, [])

    def test_invalid_plan_never_calls_commands(self):
        for key, value in (("levelId", 1073741842), ("unitPrice", True), ("operation", "arbitrary")):
            plan = copy.deepcopy(PLAN)
            plan[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                s.validate_plan(plan)
        self.assertEqual(self.fixture.calls, [])

    def test_wrong_reviewed_freeze_rejected(self):
        with self.assertRaisesRegex(ValueError, "FREEZE_CHANGED"):
            self.run_case(freeze_sha256="0" * 64)
        self.assertEqual(self.fixture.calls, [])

    def test_default_command_uses_only_fixed_cli_no_shell(self):
        log = self.base / "fixed-command"
        log.mkdir()
        fake = subprocess.CompletedProcess([], 0, '{"ok":true}', '')
        with patch.object(s.subprocess, "run", return_value=fake) as call:
            self.assertTrue(s.Commands().call(["decode", "--run", str(self.anchor)], log)["ok"])
        argv = call.call_args.args[0]
        self.assertEqual(argv[1:5], ["-B", "-I", "-S", str(s.CLI)])
        self.assertNotIn("shell", call.call_args.kwargs)


if __name__ == "__main__":
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Cases))
    (EVIDENCE / "tests.txt").write_text(stream.getvalue(), encoding="utf-8")
    summary = dict(ok=result.wasSuccessful(), tests=result.testsRun, failures=len(result.failures),
                   errors=len(result.errors), gameAccess=False, queueAccess=False, desktopAccess=False,
                   explicitPrivateCommandFixtures=True, directory=str(EVIDENCE))
    s.write(EVIDENCE / "summary.json", summary)
    print(stream.getvalue())
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() else 1)
