"""Behavioural contracts for the reader-consistency guard in
``resolve_elevated_queue`` (backend/entity_server.py).

The guard is exercised by *extracting the real function body* from the target
module with :mod:`ast` and running it against stubbed module globals, rather than
by retyping a copy of the logic.  That way the test cannot drift from the code:
if the guard is absent the extraction still succeeds but the ``ELEVATED_POINTER_*``
checks have nothing to fire, and the test fails.

Everything is offline: a temporary queue with a synthetic heartbeat, a stubbed
``_run`` that returns a chosen status reply, and a pointer file we write by hand.
No helper, no game, no bridge.

Run:
    python -B test_elevated_pointer_consistency.py [path/to/entity_server.py]
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_TARGET = Path(__file__).resolve().parents[2] / "backend/entity_server.py"
TARGET = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and sys.argv[1].endswith(".py") \
    else DEFAULT_TARGET
NOW = datetime.now(timezone.utc)
NATIVE_ACTIONS = ["inspect", "create", "save", "create-batch", "reopen-current"]


class BusinessError(RuntimeError):
    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def load_resolver(target: Path):
    """Extract resolve_elevated_queue() from the target module's source."""
    source = target.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_elevated_queue":
            namespace = {"BusinessError": BusinessError, "Path": Path}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(target), "exec"), namespace)
            return namespace["resolve_elevated_queue"]
    raise AssertionError("resolve_elevated_queue not found in %s" % target)


class Consistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolve = load_resolver(TARGET)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.queue = self.root / ".runtime/editor-bridge/elevated-queue"
        self.queue.mkdir(parents=True)
        self.pointer = self.root / ".runtime/editor-bridge/current-elevated-session.json"
        # a live heartbeat, because resolve_elevated_queue checks for one
        self.heartbeat = NOW.isoformat().replace("+00:00", "Z") + " pid=4242 handled=1"
        (self.queue / "runner.heartbeat").write_text(self.heartbeat, encoding="utf-8")
        # the helper's own reply -- the authority
        self.deadline = (NOW + timedelta(hours=20)).isoformat().replace("+00:00", "Z")
        self.reply = {
            "kind": "status", "elevated": True, "pid": 4242,
            "deadlineUtc": self.deadline,
            "nativeScene": {"schema": 1, "enabled": True, "blocked": False,
                            "actions": list(NATIVE_ACTIONS), "pinsDigest": "a" * 64,
                            "projectRoot": str(self.root)},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def write_pointer(self, **over):
        doc = {"queueDir": str(self.queue), "helperPid": 4242, "deadlineUtc": self.deadline}
        doc.update(over)
        self.pointer.write_text(json.dumps(doc), encoding="utf-8")

    def call(self):
        namespace = {
            "BusinessError": BusinessError, "Path": Path,
            "POINTER": self.pointer, "ROOT": self.root, "PYTHON": "python",
            "_read_json": lambda p: json.loads(Path(p).read_text(encoding="utf-8-sig")),
            "_run": lambda argv, timeout=120: self.reply,
        }
        # re-extract with these globals bound
        source = TARGET.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "resolve_elevated_queue")
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(TARGET), "exec"), namespace)
        return namespace["resolve_elevated_queue"]()

    # --- the guard must not fire on agreement -----------------------------
    def test_consistent_pointer_passes(self):
        self.write_pointer()
        queue, info = self.call()
        self.assertEqual(str(queue), str(self.queue))
        self.assertEqual(info["helperPid"], 4242)

    def test_absent_cached_pid_is_tolerated(self):
        self.write_pointer(helperPid=None)
        queue, info = self.call()
        self.assertIsNone(info["pointerCachedHelperPid"])

    def test_earlier_cached_deadline_is_tolerated(self):
        # a stale pointer that under-states the window is not over-authorizing
        self.write_pointer(deadlineUtc=(NOW + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
        self.call()

    # --- and must fire on the two dangerous divergences --------------------
    def test_cached_pid_conflict_refused(self):
        self.write_pointer(helperPid=999)
        with self.assertRaises(BusinessError) as caught:
            self.call()
        self.assertEqual(caught.exception.code, "ELEVATED_POINTER_HELPER_PID_CONFLICT")

    def test_cached_deadline_overstated_refused(self):
        self.write_pointer(deadlineUtc=(NOW + timedelta(hours=48)).isoformat().replace("+00:00", "Z"))
        with self.assertRaises(BusinessError) as caught:
            self.call()
        self.assertEqual(caught.exception.code, "ELEVATED_POINTER_DEADLINE_OVERSTATED")

    # --- sanity: the extracted function is really the guarded one ----------
    def test_target_carries_the_guard(self):
        source = TARGET.read_text(encoding="utf-8-sig")
        self.assertIn("ELEVATED_POINTER_HELPER_PID_CONFLICT", source)
        self.assertIn("ELEVATED_POINTER_DEADLINE_OVERSTATED", source)


if __name__ == "__main__":
    # argv[1] is the target module; keep it out of unittest's own arg parsing.
    unittest.main(argv=[sys.argv[0]], verbosity=2)
