"""One bounded native shop transaction, with independent inventory receipts.

The caller must already have entered the reviewed trial and opened its shop.
No game access occurs at import or validation. Only run() executes fixed CLIs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools/playtest-control/cli.py"
CARDS = ROOT / ".runtime/playtest-control-20261016/prepared"
OUTPUT = ROOT / ".runtime/playtest-sequences"
LEVEL = 1073741843
SHA = re.compile(r"[0-9a-f]{64}")
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def require(value, code):
    if not value:
        raise ValueError(code)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def project_path(value, *, directory=False, boundary=ROOT):
    p = Path(value)
    require(p.is_absolute(), "ABSOLUTE_PATH_REQUIRED")
    require(p.is_relative_to(boundary) and p != boundary, "PATH_OUTSIDE_BOUNDARY")
    for node in (p, *p.parents):
        if node.exists():
            require(not node.is_symlink() and not (getattr(node.stat(), "st_file_attributes", 0) & 0x400),
                    "REPARSE_PATH_REFUSED")
        if node == ROOT:
            break
    p = p.resolve()
    require(p.is_relative_to(boundary.resolve()), "PATH_RESOLVES_OUTSIDE_BOUNDARY")
    require(p.is_dir() if directory else p.is_file(), "PATH_MISSING_OR_WRONG_KIND")
    return p


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == {
        "schemaVersion", "levelId", "operation", "item", "currency", "unitPrice", "shopId", "shopOwnerId"},
        "TRANSACTION_PLAN_FIELDS")
    require(type(plan["schemaVersion"]) is int and plan["schemaVersion"] == 1 and
            type(plan["levelId"]) is int and plan["levelId"] == LEVEL, "TRANSACTION_LEVEL")
    require(plan["operation"] in ("buy", "sell"), "TRANSACTION_OPERATION")
    for key in ("item", "currency"):
        row = plan[key]
        require(type(row) is dict and set(row) == {"configId", "resourceType"}, "RESOURCE_FIELDS")
        require(type(row["configId"]) is int and 0 < row["configId"] <= 0xffffffff, "RESOURCE_ID")
        require(type(row["resourceType"]) is int and 0 <= row["resourceType"] <= 0xffffffff,
                "RESOURCE_TYPE")
    require(plan["item"]["configId"] != plan["currency"]["configId"], "ITEM_CURRENCY_ID_COLLISION")
    for key in ("unitPrice", "shopId", "shopOwnerId"):
        require(type(plan[key]) is int and 0 < plan[key] <= 0xffffffff, "POSITIVE_INTEGER_REQUIRED")
    return json.loads(json.dumps(plan))


def freeze_sources(freeze, expected):
    require(type(expected) is str and SHA.fullmatch(expected), "REVIEWED_FREEZE_SHA_REQUIRED")
    require(digest(freeze) == expected, "FREEZE_CHANGED")
    doc = read(freeze)
    require(doc.get("status") == "offline-verified-live-unverified" and
            doc.get("route") == "native-map/playtest-control", "SHOP_MODULE_FREEZE_REQUIRED")
    rows = []
    for key in ("owned", "sharedDependencies", "graphVectorValuesTree"):
        require(type(doc.get(key)) is list and doc[key], "FREEZE_SOURCE_GROUP_MISSING")
        rows.extend(doc[key])
    sources = {}
    for row in rows:
        require(type(row) is dict and type(row.get("sha256")) is str and SHA.fullmatch(row["sha256"]),
                "FREEZE_SOURCE_INVALID")
        raw = Path(row["path"])
        path = project_path(raw if raw.is_absolute() else ROOT / raw)
        if path in sources:
            require(sources[path] == row["sha256"], "FREEZE_SOURCE_CONFLICT")
        sources[path] = row["sha256"]
        require(digest(path) == row["sha256"], "FROZEN_SOURCE_CHANGED")
    require(CLI in sources, "FIXED_CLI_NOT_IN_FREEZE")
    sources[freeze] = expected
    sources[Path(__file__).resolve()] = digest(__file__)
    return sources


class Commands:
    """Fixed executable and script; no shell or caller-selected command."""
    private_fixture = False

    def call(self, arguments, log):
        require(arguments and arguments[0] in ("prepare", "dispatch", "decode", "inventory-diff"),
                "COMMAND_NOT_ALLOWED")
        argv = [sys.executable, "-B", "-I", "-S", str(CLI), *map(str, arguments)]
        write(log / "command.json", {"argv": argv, "shell": False})
        result = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", errors="strict", timeout=360,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (log / "stdout.txt").write_text(result.stdout, encoding="utf-8")
        (log / "stderr.txt").write_text(result.stderr, encoding="utf-8")
        write(log / "exit.json", {"returnCode": result.returncode})
        payload = json.loads(result.stdout)
        require(type(payload) is dict, "CLI_RESPONSE_NOT_OBJECT")
        require(result.returncode == 0 and payload.get("ok") is True, "FIXED_CLI_FAILED")
        return payload


class Transaction:
    def __init__(self, plan, directory, session, anchor, queue, sources, commands):
        self.plan, self.directory = plan, directory
        self.session, self.anchor, self.queue = session, anchor, queue
        self.sources, self.commands = sources, commands
        self.started = time.monotonic()
        self.steps, self.cards, self.actions = [], [], []
        self.sequence = 0
        self.dispatch_attempts = 0
        self.card_paths = set()
        self.stage = "created"

    def check(self):
        require(time.monotonic() - self.started < 900, "TRANSACTION_TIME_LIMIT")
        for path, sha in self.sources.items():
            require(digest(path) == sha, "TRANSACTION_SOURCE_OR_IDENTITY_CHANGED")

    def call(self, arguments):
        self.check()
        require(self.sequence < 100, "TRANSACTION_COMMAND_LIMIT")
        log = self.directory / f"{self.sequence:03d}"
        log.mkdir(exist_ok=False)
        self.sequence += 1
        write(log / "intent.json", {"arguments": list(map(str, arguments)), "stage": self.stage,
                                    "at": datetime.now(timezone.utc).isoformat()})
        result = self.commands.call(arguments, log)
        require(type(result) is dict and result.get("ok") is True, "COMMAND_DID_NOT_SUCCEED")
        write(log / "result.json", result)
        self.steps.append({"path": str(log), "stage": self.stage, "command": arguments[0]})
        self.check()
        return result

    def card(self, operation, extra=()):
        require(len(self.cards) < 28, "TRANSACTION_CARD_LIMIT")
        self.stage = operation
        built = self.call(["prepare", "--operation", operation, "--session", str(self.session),
                           "--target-level", str(LEVEL), "--previous-run", str(self.anchor), *extra])
        require(built.get("launchable") is True and built.get("mode") == operation,
                "NONLAUNCHABLE_OR_WRONG_CARD")
        run = project_path(built["run"], directory=True, boundary=CARDS)
        require(run not in self.card_paths, "PREPARE_REUSED_CARD")
        self.card_paths.add(run)
        card_sha = digest(run / "prepared.json")
        require(built.get("preparedSha256") == card_sha, "PREPARED_HASH_MISMATCH")
        prepared = read(run / "prepared.json")
        expected_kind = "playtest-control-prepared-v6" if operation == "inventory-state" else "playtest-control-prepared-v7"
        require(prepared.get("kind") == expected_kind and prepared.get("mode") == operation and
                prepared.get("targetLevelId") == LEVEL and prepared.get("anchorRun") == str(self.anchor) and
                prepared.get("compileOnly") is False and prepared.get("launchable") is True and
                prepared.get("action") == 19 and prepared.get("receiptVersion") == 24,
                "PREPARED_TARGET_OR_PROTOCOL_MISMATCH")
        self.sources[run / "prepared.json"] = card_sha
        self.dispatch_attempts += 1
        reply = self.call(["dispatch", "--run", str(run), "--elevated-queue", str(self.queue)])
        self.clean(reply)
        decoded = self.call(["decode", "--run", str(run)])
        self.clean(decoded)
        require(decoded.get("mode") == "play" and decoded.get("trialIdentityBound") is True and
                decoded.get("playerBelongsToTargetLevel") is True, "DECODED_TRIAL_NOT_PROVEN")
        require(decoded.get("operation") == operation, "DECODED_OPERATION_MISMATCH")
        require(decoded.get("run") == str(run) and decoded.get("targetLevelId") == LEVEL and
                decoded.get("nativeStarted") is True, "DECODED_CARD_MISMATCH")
        require(decoded.get("binaryReceiptSha256") == digest(run / "acceptance.bin") and
                decoded.get("rawReceiptSha256") == digest(run / "stdout.jsonl"), "RAW_RECEIPT_CHANGED")
        for name in ("acceptance.bin", "stdout.jsonl", "exit.json"):
            self.sources[run / name] = digest(run / name)
        self.cards.append({"operation": operation, "run": str(run), "preparedSha256": card_sha})
        return run, decoded

    @staticmethod
    def clean(result):
        require(result.get("ok") is True and result.get("cleanupVerified") is True and
                result.get("safeToRelease") is True and result.get("outcomeUncertain") is False,
                "CARD_UNKNOWN_OR_NOT_RELEASED")

    def state(self, expected_screen, *, selected=False, attempts=4):
        for _ in range(attempts):
            run, result = self.card("shop-state")
            ui = result["uiState"]
            require(ui.get("complete") == 1 and ui.get("status") == 0, "SHOP_STATE_INCOMPLETE")
            require(ui.get("shopId") == self.plan["shopId"] and
                    ui.get("ownerId") == self.plan["shopOwnerId"], "SHOP_IDENTITY_CHANGED")
            if ui.get("screen") != expected_screen:
                continue
            if selected:
                require(ui.get("configId") == self.plan["item"]["configId"] and
                        ui.get("resourceType") == self.plan["item"]["resourceType"], "SELECTED_ITEM_CHANGED")
            return run, result
        raise ValueError("EXPECTED_UI_STATE_NOT_REACHED")

    def action(self, baseline, state, action, row=None):
        ui = state["uiState"]
        label = ui["text"] if row is None else ui["rows"][row]["text"]
        ident = self.directory.name[:20] + "-" + str(len(self.actions)) + "-" + action
        extra = ["--ui-baseline", str(baseline), "--ui-action", action, "--ui-id", ident,
                 "--config-id", str(self.plan["item"]["configId"]), "--label", label]
        if row is not None:
            extra.extend(["--ui-row", str(row)])
        run, result = self.card("shop-ui", extra)
        require(result.get("uiAction") == action and result.get("uiActionReturned") is True,
                "NATIVE_UI_ACTION_NOT_RETURNED")
        self.actions.append({"action": action, "run": str(run), "baseline": str(baseline), "id": ident})
        return result

    def execute(self):
        before, inventory = self.card("inventory-state")
        require(inventory.get("inventoryComplete") is True and
                inventory.get("inventoryQuantitiesVerified") is True, "INVENTORY_NOT_COMPLETE")
        resource = self.plan["currency"] if self.plan["operation"] == "buy" else self.plan["item"]
        field = "paymentResourceCounts" if self.plan["operation"] == "buy" else "physicalItemCounts"
        balances = [row for row in inventory[field] if
                    all(row.get(key) == value for key, value in resource.items())]
        require(len(balances) == 1, "STARTING_RESOURCE_BALANCE_NOT_UNIQUE")
        need = self.plan["unitPrice"] if self.plan["operation"] == "buy" else 1
        require(int(balances[0]["quantity"]) >= need, "STARTING_BALANCE_INSUFFICIENT")
        baseline, state = self.state("inventory-page")
        role = 1 if self.plan["operation"] == "buy" else 2
        item = self.plan["item"]
        matches = [i for i, row in enumerate(state["uiState"]["rows"])
                   if row.get("role") == role and row.get("configId") == item["configId"] and
                   row.get("resourceType") == item["resourceType"] and
                   all(row.get(k) == 1 for k in ("active", "enabled", "handlerVerified"))]
        require(len(matches) == 1, "VISIBLE_ITEM_NOT_UNIQUE")
        self.action(baseline, state, "goods" if role == 1 else "bag-item", matches[0])
        if role == 2:
            baseline, state = self.state("item-details", selected=True)
            self.action(baseline, state, "sell-open")
        screen = "buy-confirmation" if role == 1 else "sell-confirmation"
        baseline, state = self.state(screen, selected=True)
        if state["uiState"]["quantity"] != 1:
            self.action(baseline, state, "quantity-one")
            baseline, state = self.state(screen, selected=True)
        require(state["uiState"]["quantity"] == 1, "QUANTITY_ONE_NOT_OBSERVED")
        self.action(baseline, state, self.plan["operation"])
        queries = [{"source": "slots", **item},
                   {"source": "payment-resources", **self.plan["currency"]}]
        query_path = self.directory / "queries.json"
        write(query_path, queries)
        self.sources[query_path] = digest(query_path)
        expected = [1, -self.plan["unitPrice"]] if role == 1 else [-1, self.plan["unitPrice"]]
        comparisons = []
        # Only observations are repeated after confirmation, never the UI action.
        for _ in range(4):
            after, _ = self.card("inventory-state")
            self.stage = "inventory-diff"
            result = self.call(["inventory-diff", "--before-run", str(before), "--after-run", str(after),
                                "--queries", str(query_path)])
            self.clean(result)
            require(result.get("operation") == "inventory-diff" and
                    result.get("targetLevelId") == LEVEL, "DIFF_TARGET_MISMATCH")
            changes = result.get("changes")
            require(type(changes) is list and len(changes) == 2, "DIFF_ROWS_INVALID")
            for row, query in zip(changes, queries):
                require(all(row.get(k) == v for k, v in query.items()), "DIFF_RESOURCE_MISMATCH")
            delta = [int(row["delta"]) for row in changes]
            comparisons.append({"afterRun": str(after), "delta": delta, "evidence": result})
            if delta == expected:
                return {"ok": True, "expectedQuantityDeltasObserved": True,
                        "expectedDeltas": expected, "comparisons": comparisons}
            require(all(value in (0, want) for value, want in zip(delta, expected)),
                    "UNEXPECTED_INVENTORY_DELTA")
        return {"ok": False, "code": "EXPECTED_DELTAS_NOT_OBSERVED",
                "expectedQuantityDeltasObserved": False, "expectedDeltas": expected,
                "comparisons": comparisons}


def run(plan, *, operation_id, session_file, trial_anchor, queue,
        freeze_path, freeze_sha256, _commands=None):
    plan = validate_plan(plan)
    require(type(operation_id) is str and IDENT.fullmatch(operation_id), "UNIQUE_OPERATION_ID_REQUIRED")
    session = project_path(session_file)
    anchor = project_path(trial_anchor, directory=True, boundary=CARDS)
    queue = project_path(queue, directory=True, boundary=ROOT / ".runtime/editor-bridge")
    freeze = project_path(freeze_path)
    sources = freeze_sources(freeze, freeze_sha256)
    transport = project_path(ROOT / "tools/editor-bridge/elevated-request.py")
    sources[transport] = digest(transport)
    sources[session] = digest(session)
    # Existing production builders independently validate full trial ancestry.
    anchor_card = project_path(anchor / "prepared.json")
    sources[anchor_card] = digest(anchor_card)
    commands = _commands or Commands()
    if _commands is not None:
        require(getattr(commands, "private_fixture", False) is True, "PRIVATE_TEST_SEAM_ONLY")
    directory = OUTPUT / hashlib.sha256(operation_id.encode()).hexdigest()[:32]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    directory.mkdir(exist_ok=False)
    frozen = {"plan": plan, "operationId": operation_id, "session": str(session),
              "trialAnchor": str(anchor), "queue": str(queue), "sources": {str(k): v for k, v in sources.items()},
              "privateFixture": commands.private_fixture, "replayAllowed": False}
    write(directory / "request.json", frozen)
    sources[directory / "request.json"] = digest(directory / "request.json")
    transaction = Transaction(plan, directory, session, anchor, queue, sources, commands)
    try:
        result = transaction.execute()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result = {"ok": False, "code": str(error), "expectedQuantityDeltasObserved": False}
    result.update(operationId=operation_id, directory=str(directory), lastStage=transaction.stage,
                  cards=transaction.cards, actions=transaction.actions, steps=transaction.steps,
                  dispatchAttempts=transaction.dispatch_attempts, replayAllowed=False,
                  privateFixture=commands.private_fixture, wholeGameAccepted=False,
                  visualAccepted=False, naturalShopEntryVerified=False,
                  attribution="Exact native UI actions followed by independently decoded inventory deltas; no direct settlement calls.")
    write(directory / "result.json", result)
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--trial-anchor", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(read(args.plan), operation_id=args.operation_id, session_file=args.session,
                     trial_anchor=args.trial_anchor, queue=args.queue, freeze_path=args.freeze,
                     freeze_sha256=args.freeze_sha256)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"ok": False, "code": str(error), "replayAllowed": False}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
