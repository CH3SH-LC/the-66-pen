"""Offline contracts for tools/editor-bridge/sync-elevated-pointer.py.

Everything here runs against a synthetic queue directory + a stub status receipt
under a temporary root.  No helper, no game, no bridge, no elevation, no write to
the real tree.  The registrar is copied into the temp root first so its
``ROOT = parents[2]`` resolves inside the sandbox.

Run:  python -B test-sync-elevated-pointer.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRAR = HERE.parent / "sync-elevated-pointer.py"

NATIVE_ACTIONS = ["inspect", "create", "save", "create-batch", "reopen-current", "creature-create"]
NOW = datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class Sandbox:
    """A temp root shaped like the repo, with a queue, a heartbeat and a receipt."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tools/editor-bridge/tests").mkdir(parents=True)
        self.script = self.root / "tools/editor-bridge/sync-elevated-pointer.py"
        shutil.copyfile(REGISTRAR, self.script)
        self.queue = self.root / ".runtime/editor-bridge/elevated-queue"
        self.queue.mkdir(parents=True)
        self.pointer = self.root / ".runtime/editor-bridge/current-elevated-session.json"
        self.heartbeat(pid=4242, age_seconds=0.0)

    def heartbeat(self, *, pid: int, age_seconds: float, handled: int = 0, raw: str | None = None):
        text = raw if raw is not None else "%s pid=%d handled=%d" % (
            iso(NOW - timedelta(seconds=age_seconds)), pid, handled)
        (self.queue / "runner.heartbeat").write_text(text, encoding="utf-8")

    def receipt(self, **over):
        lifetime = 1440
        r = {
            "kind": "status",
            "elevated": True,
            "pid": 4242,
            "startedUtc": iso(NOW - timedelta(minutes=5)),
            "deadlineUtc": iso(NOW - timedelta(minutes=5) + timedelta(minutes=lifetime)),
            "lifetimeMinutes": lifetime,
            "handled": 1,
            "nativeScene": {
                "schema": 1, "enabled": True, "blocked": False,
                "actions": list(NATIVE_ACTIONS),
                "projectRoot": str(self.root),
                "pinsDigest": "a" * 64,
                "pinCount": 2078,
            },
        }
        for key, value in over.items():
            if key == "nativeScene" and isinstance(value, dict):
                r["nativeScene"].update(value)
            else:
                r[key] = value
        return r

    def _refresh_valid_heartbeat(self, pid):
        """Rewrite a sane, still-fresh heartbeat for ``pid``; otherwise do nothing."""
        if type(pid) is not int:
            return
        path = self.queue / "runner.heartbeat"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        import re as _re
        m = _re.match(r"([^ ]+) pid=([0-9]+) handled=([0-9]+)$", text)
        if not m or int(m.group(2)) != pid:
            return
        try:
            stamp = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        except ValueError:
            return
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        if 0 <= age < 300:  # a heartbeat a test deliberately made stale is left alone
            self.heartbeat(pid=pid, age_seconds=0.0, handled=int(m.group(3)))

    def write_receipt(self, receipt) -> Path:
        path = self.root / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        return path

    def run(self, *args, receipt=None):
        if not args:
            args = ("register",)
        chosen = receipt if receipt is not None else self.receipt()
        # Keep a *still-valid* heartbeat fresh so a slow/loaded machine cannot turn
        # a positive case into a spurious HEARTBEAT_STALE.  A heartbeat that is
        # already stale, broken, missing, or for another pid is left exactly as the
        # test set it up, so all the negative cases still bite.
        self._refresh_valid_heartbeat(chosen.get("pid"))
        receipt_path = self.write_receipt(chosen)
        argv = [sys.executable, "-B", str(self.script), *args,
                "--queue-dir", str(self.queue), "--pointer", str(self.pointer),
                "--receipt-file", str(receipt_path)]
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = json.loads(proc.stdout) if (proc.stdout or "").strip() else {}
        return proc.returncode, out

    def cleanup(self):
        self.tmp.cleanup()


class RegisterPositive(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def test_fresh_complete_receipt_registers(self):
        code, out = self.sb.run("register")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["ok"])
        doc = json.loads(self.sb.pointer.read_text(encoding="utf-8"))
        # every identity field is copied from the receipt, never invented
        receipt = json.loads((self.sb.root / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["helperPid"], receipt["pid"])
        self.assertEqual(doc["helperStartedUtc"], receipt["startedUtc"])
        self.assertEqual(doc["deadlineUtc"], receipt["deadlineUtc"])
        self.assertEqual(doc["nativeScene"]["pinsDigest"], receipt["nativeScene"]["pinsDigest"])
        self.assertEqual(doc["queueDir"], str(self.sb.queue.resolve()))
        self.assertEqual(doc["status"], "active")
        self.assertEqual(len(doc["registrationDigest"]), 64)
        # the queue directory itself was never written to except the heartbeat we made
        leftovers = sorted(p.name for p in self.sb.pointer.parent.glob("*.tmp-*"))
        self.assertEqual(leftovers, [], "atomic write left a temp file behind")

    def test_backup_of_previous_pointer_is_taken(self):
        self.sb.pointer.write_text('{"helperPid": 1, "status": "retired"}', encoding="utf-8")
        code, out = self.sb.run("register")
        self.assertEqual(code, 0, out)
        backups = list(self.sb.pointer.parent.glob("current-elevated-session.before-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertIn("retired", backups[0].read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing(self):
        code, out = self.sb.run("register", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.sb.pointer.exists())
        self.assertEqual(out["wouldWrite"], str(self.sb.pointer))

    def test_verify_agrees_with_freshly_written_pointer(self):
        self.assertEqual(self.sb.run("register")[0], 0)
        code, out = self.sb.run("verify")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["consistent"])

    def test_supersede_replaces_a_live_conflicting_helper(self):
        self.sb.pointer.write_text(json.dumps({
            "helperPid": 999, "status": "active",
            "deadlineUtc": iso(NOW + timedelta(hours=3)),
            "queueDir": str(self.sb.queue),
        }), encoding="utf-8")
        # without --supersede the live conflict is refused
        code, out = self.sb.run("register")
        self.assertEqual(code, 3)
        self.assertEqual(out["refused"], "POINTER_CONFLICT_LIVE_HELPER")
        # and with it, the new helper wins
        code, out = self.sb.run("register", "--supersede")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(self.sb.pointer.read_text(encoding="utf-8"))["helperPid"], 4242)

    def test_expired_conflicting_helper_does_not_block(self):
        self.sb.pointer.write_text(json.dumps({
            "helperPid": 999, "status": "active",
            "deadlineUtc": iso(NOW - timedelta(hours=3)),
        }), encoding="utf-8")
        code, out = self.sb.run("register")
        self.assertEqual(code, 0, out)


class RegisterRefuses(unittest.TestCase):
    """Every refusal keeps the pointer untouched."""

    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def assertRefused(self, code_expected, *args, receipt=None, setup=None):
        if setup:
            setup()
        code, out = self.sb.run(*args, receipt=receipt)
        self.assertEqual(code, 3, out)
        self.assertEqual(out["refused"], code_expected, out)
        self.assertFalse(self.sb.pointer.exists(), "a refused registration must not write")

    # --- stale ------------------------------------------------------------
    def test_heartbeat_missing(self):
        self.assertRefused("HEARTBEAT_MISSING",
                           setup=lambda: (self.sb.queue / "runner.heartbeat").unlink())

    def test_heartbeat_stale(self):
        self.assertRefused("HEARTBEAT_STALE",
                           setup=lambda: self.sb.heartbeat(pid=4242, age_seconds=3600))

    def test_receipt_expired(self):
        self.assertRefused("RECEIPT_EXPIRED",
                           receipt=self.sb.receipt(
                               startedUtc=iso(NOW - timedelta(hours=25)),
                               deadlineUtc=iso(NOW - timedelta(hours=1))))

    # --- conflicting ------------------------------------------------------
    def test_heartbeat_pid_conflict(self):
        self.assertRefused("HEARTBEAT_PID_CONFLICT",
                           setup=lambda: self.sb.heartbeat(pid=777, age_seconds=0))

    def test_lifetime_inconsistent_deadline(self):
        # the exact shape the real pointer carried: deadline minus start is not
        # the advertised lifetime.  Here deadline is still in the future.
        self.assertRefused("RECEIPT_LIFETIME_INCONSISTENT",
                           receipt=self.sb.receipt(deadlineUtc=iso(NOW + timedelta(minutes=30))))

    def test_project_root_conflict(self):
        self.assertRefused("CAPABILITY_PROJECT_ROOT_CONFLICT",
                           receipt=self.sb.receipt(nativeScene={"projectRoot": "D:\\elsewhere"}))

    def test_started_in_future(self):
        self.assertRefused("RECEIPT_STARTED_IN_FUTURE",
                           receipt=self.sb.receipt(startedUtc=iso(NOW + timedelta(hours=6))))

    def test_queue_outside_project(self):
        outside = self.sb.root.parent
        code, out = self.sb.run("register", receipt=self.sb.receipt())
        self.assertEqual(code, 0, out)  # sanity: normal queue works
        self.sb.pointer.unlink()
        # now point --queue-dir at a directory outside .runtime/editor-bridge
        (self.sb.root / "not-a-queue").mkdir()
        proc = subprocess.run(
            [sys.executable, "-B", str(self.sb.script), "register",
             "--queue-dir", str(self.sb.root / "not-a-queue"),
             "--pointer", str(self.sb.pointer),
             "--receipt-file", str(self.sb.root / "receipt.json")],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 3, proc.stdout)
        self.assertEqual(json.loads(proc.stdout)["refused"], "QUEUE_OUTSIDE_PROJECT")

    # --- incomplete -------------------------------------------------------
    def test_not_a_status_reply(self):
        self.assertRefused("RECEIPT_NOT_A_STATUS_REPLY", receipt=self.sb.receipt(kind="native-scene"))

    def test_not_elevated(self):
        self.assertRefused("RECEIPT_NOT_ELEVATED", receipt=self.sb.receipt(elevated=False))

    def test_pid_invalid(self):
        for bad in (None, "4242", 0, -1, True):
            self.assertRefused("RECEIPT_HELPER_PID_INVALID", receipt=self.sb.receipt(pid=bad))

    def test_capability_missing(self):
        r = self.sb.receipt(); del r["nativeScene"]
        self.assertRefused("CAPABILITY_MISSING", receipt=r)

    def test_capability_incomplete_schema(self):
        self.assertRefused("CAPABILITY_INCOMPLETE", receipt=self.sb.receipt(nativeScene={"schema": 2}))

    def test_capability_incomplete_enabled(self):
        self.assertRefused("CAPABILITY_INCOMPLETE", receipt=self.sb.receipt(nativeScene={"enabled": False}))

    def test_capability_incomplete_actions(self):
        self.assertRefused("CAPABILITY_INCOMPLETE",
                           receipt=self.sb.receipt(nativeScene={"actions": ["inspect"]}))

    def test_capability_incomplete_pinsdigest(self):
        for bad in ("", "xyz", "A" * 64, None, 123):
            self.assertRefused("CAPABILITY_INCOMPLETE",
                               receipt=self.sb.receipt(nativeScene={"pinsDigest": bad}))

    def test_heartbeat_invalid(self):
        self.assertRefused("HEARTBEAT_INVALID",
                           setup=lambda: self.sb.heartbeat(pid=4242, age_seconds=0, raw="not a heartbeat"))


class VerifyReaderConsistency(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def test_stale_cached_deadline_is_flagged_over_stated(self):
        self.assertEqual(self.sb.run("register")[0], 0)
        doc = json.loads(self.sb.pointer.read_text(encoding="utf-8"))
        # simulate the rot: a hand edit pushes the cached deadline PAST the real
        # one (receipt deadline is about NOW+24h, so +48h over-states the window)
        doc["deadlineUtc"] = iso(NOW + timedelta(hours=48))
        self.sb.pointer.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.sb.run("verify")
        self.assertEqual(code, 2, out)
        self.assertEqual(out["refused"], "POINTER_DIVERGENT_FROM_RECEIPT")
        fields = {d["field"]: d for d in out["divergences"]}
        self.assertIn("deadlineUtc", fields)
        self.assertEqual(fields["deadlineUtc"].get("severity"), "over-stated")

    def test_tampered_pin_digest_is_flagged(self):
        self.assertEqual(self.sb.run("register")[0], 0)
        doc = json.loads(self.sb.pointer.read_text(encoding="utf-8"))
        doc["nativeScene"]["pinsDigest"] = "b" * 64
        self.sb.pointer.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.sb.run("verify")
        self.assertEqual(code, 2, out)
        self.assertIn("pinsDigest", {d["field"] for d in out["divergences"]})

    def test_pid_conflict_is_flagged(self):
        self.assertEqual(self.sb.run("register")[0], 0)
        doc = json.loads(self.sb.pointer.read_text(encoding="utf-8"))
        doc["helperPid"] = 1
        self.sb.pointer.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.sb.run("verify")
        self.assertEqual(code, 2, out)
        self.assertIn("helperPid", {d["field"] for d in out["divergences"]})


class StatusQueryRefusals(unittest.TestCase):
    """The LIVE acquisition path must refuse BY NAME too, not traceback.

    Every other test in this file supplies ``--receipt-file``, so the path that actually
    talks to the helper -- ``fetch_receipt`` -- had NO coverage at all.  MEASURED
    2026-10-06 on the real tree with the helper absent: ``register`` with no receipt file
    hung 30 s and then printed ``subprocess.TimeoutExpired`` as a Python traceback, exit 1,
    instead of the named ``Refused`` every other failure in that file produces.

    WHICH OF THE TWO HAS TEETH, measured rather than assumed: only the TIMEOUT one.  Run
    against the pre-fix script, ``test_hanging_status_query_times_out_by_name`` errors
    (TimeoutExpired escapes), which is the defect.  ``..._missing_status_query_script_...``
    passes both before and after, because a missing script makes ``sys.executable`` exit
    non-zero -- a case the old code already turned into ``RECEIPT_QUERY_FAILED``.  It is
    kept as a contract test for a branch nothing covered, NOT claimed as a regression test.
    Both call ``fetch_receipt`` directly with a short timeout so they stay fast.
    """

    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def load_registrar(self):
        spec = importlib.util.spec_from_file_location("sep_sandbox", self.sb.script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_missing_status_query_script_is_refused_by_name(self):
        # The sandbox has no tools/editor-bridge/elevated-request.py, so the query cannot
        # even be run.  Before the fix this raised FileNotFoundError out of main().
        module = self.load_registrar()
        with self.assertRaises(module.Refused) as caught:
            module.fetch_receipt(self.sb.queue, timeout=2.0)
        self.assertEqual(caught.exception.code, "RECEIPT_QUERY_FAILED")

    def test_hanging_status_query_times_out_by_name(self):
        stub = self.sb.root / "tools/editor-bridge/elevated-request.py"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
        module = self.load_registrar()
        with self.assertRaises(module.Refused) as caught:
            module.fetch_receipt(self.sb.queue, timeout=0.5)
        self.assertEqual(caught.exception.code, "RECEIPT_QUERY_TIMEOUT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
