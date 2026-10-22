"""Offline tests for the live-sandbox reader — fake runner, no bridge, no game."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.gameplan import live
from tools.gameplan.live import LiveState, current_level, helper_status, read_live, read_scene

STATUS_JSON = """
{"pid": 176324, "elevated": true, "deadlineUtc": "2026-10-10T15:28:41Z", "handled": 6,
 "nativeScene": {"blocked": false, "actions": ["inspect","create","save"],
                 "pinsDigest": "ab162618", "pinCount": 2082}}
"""

LEVEL_JSON = """
{"ok": true, "kind": "current-level-observation", "levelId": 1073741842,
 "levelObservation": {"verified": true, "levelId": 1073741842},
 "entities": 11, "handle": "20261009-233002-eee2beb544", "run": "X:/run"}
"""


class Fake:
    def __init__(self, status_out=STATUS_JSON, level_out=LEVEL_JSON, status_code=0):
        self.status_out, self.level_out, self.status_code = status_out, level_out, status_code
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(argv)
        if "discover_current_level.py" in " ".join(argv):
            return (0, self.level_out)
        return (self.status_code, self.status_out)


class TestReadLive(unittest.TestCase):
    def test_happy_path(self):
        state = read_live("Q", runner=Fake())
        self.assertTrue(state.ok)
        self.assertEqual(state.source, "native-read")
        self.assertEqual(state.level_id, 1073741842)
        self.assertEqual(state.entities, 11)
        self.assertTrue(state.level_verified)
        self.assertEqual(state.helper_pid, 176324)
        self.assertEqual(state.helper_actions, ("inspect", "create", "save"))
        self.assertEqual(state.pins_digest, "ab162618")

    def test_helper_not_elevated_refuses(self):
        state = read_live("Q", runner=Fake(status_out='{"pid": 1, "elevated": false}'))
        self.assertFalse(state.ok)
        self.assertEqual(state.reason, "helper-not-elevated")
        self.assertEqual(state.source, "native-read")

    def test_helper_status_unavailable_refuses(self):
        state = read_live("Q", runner=Fake(status_out="not json at all", status_code=1))
        self.assertFalse(state.ok)
        self.assertEqual(state.reason, "helper-status-unavailable")

    def test_refused_discovery_refuses(self):
        state = read_live("Q", runner=Fake(level_out='{"ok": false, "error": "UNAVAILABLE"}'))
        self.assertFalse(state.ok)
        self.assertEqual(state.reason, "live-level-read-failed")

    def test_unverified_level_refuses(self):
        state = read_live("Q", runner=Fake(
            level_out='{"ok": true, "levelId": 5, "levelObservation": {"verified": false}, "entities": 1}'))
        self.assertFalse(state.ok)
        self.assertEqual(state.reason, "level-identity-unverified")

    def test_summary_shape(self):
        summary = read_live("Q", runner=Fake()).summary()
        self.assertEqual(set(summary), {"ok", "source", "reason", "helper", "level", "errors"})
        self.assertEqual(summary["level"]["levelId"], 1073741842)

    def test_no_disk_read_is_used(self):
        # The live reader must never shell out to the disk-only current-save.py.
        runner = Fake()
        read_live("Q", runner=runner)
        joined = " ".join(" ".join(c) for c in runner.calls)
        self.assertNotIn("current-save.py", joined)

    def test_it_reads_status_then_level(self):
        runner = Fake()
        read_live("Q", runner=runner)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("elevated-request.py", runner.calls[0][2] or runner.calls[0][3])
        self.assertTrue(any("discover_current_level.py" in c[2] for c in runner.calls))


class TestParsers(unittest.TestCase):
    def test_status_tolerates_leading_noise(self):
        receipt, errors = helper_status("Q", Fake(status_out="log line\n" + STATUS_JSON))
        self.assertEqual(errors, [])
        self.assertEqual(receipt["pid"], 176324)

    def test_current_level_rejects_no_json(self):
        observation, errors = current_level("Q", Fake(level_out="boom"))
        self.assertIsNone(observation)
        self.assertTrue(errors)


# --------------------------------------------------------------------------- #
# read_scene -- the whole scene in one call, and its named degraded states
# --------------------------------------------------------------------------- #

RUN = "7588c713-fb80-433a-afce-c0f89cf13d96"
NAME = "MW_API_FARM_DEMO"
GRAPH_ID = 1073741900

BRIDGE_LOADED = lambda run_id: (True, "")            # noqa: E731 - tiny test probe
BRIDGE_DOWN = lambda run_id: (False, "no bridge-ready.json for this run")  # noqa: E731


class FakeGraph:
    """Answers ``graph inspect`` like the adapter would; records every argv."""

    def __init__(self, defs=(71, 688), *, bound=(1077936215,), ok=True, error=None, raises=False):
        self.defs, self.bound, self.ok, self.error, self.raises = defs, list(bound), ok, error, raises
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.raises:
            raise RuntimeError("bridge connection dropped")
        if not self.ok:
            return {"ok": False, "error": self.error or "AUTHOR_GRAPH_IDENTITY_MISMATCH"}
        return {"ok": True, "backend": {
            "status": "editor-model-readback",
            "nodeCount": len(self.defs),
            "nodes": [{"nodeId": i + 1, "definitionId": d} for i, d in enumerate(self.defs)],
            "boundEntityIds": list(self.bound),
        }}


def scene(*, live_runner=None, graph_runner=None, bridge_probe=BRIDGE_LOADED,
          directory_reader=None, graph_name=NAME, graph_id=GRAPH_ID, run_id=RUN,
          gil_path=None):
    return read_scene("Q", runner=live_runner or Fake(), graph_runner=graph_runner or FakeGraph(),
                      bridge_probe=bridge_probe, directory_reader=directory_reader,
                      graph_name=graph_name, graph_id=graph_id, run_id=run_id, gil_path=gil_path)


class TestSceneHappyPath(unittest.TestCase):
    def test_composed_happy_path_is_complete(self):
        summary = scene().summary()
        self.assertTrue(summary["ok"])
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["degraded"], [])
        self.assertEqual(summary["helper"]["state"], live.HELPER_ACTIVE)
        self.assertEqual(summary["level"]["state"], live.LEVEL_VERIFIED)
        self.assertEqual(summary["level"]["data"]["entities"], 11)
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_LOADED)
        self.assertEqual(summary["graph"]["state"], live.GRAPH_PRESENT)
        self.assertEqual(summary["graph"]["data"]["nodeDefinitionIds"], [71, 688])
        self.assertEqual(summary["graph"]["data"]["boundEntityIds"], [1077936215])
        self.assertEqual(summary["directory"]["state"], live.DIRECTORY_NOT_CHECKED)
        self.assertFalse(summary["directory"]["requested"])

    def test_summary_shape_is_stable(self):
        summary = scene().summary()
        self.assertEqual(set(summary), {"ok", "source", "complete", "degraded",
                                        "helper", "level", "bridge", "graph",
                                        "directory", "errors"})
        self.assertEqual(summary["source"], "native-read")
        self.assertEqual(summary["graph"]["data"]["graphId"], GRAPH_ID)
        self.assertIn(summary["bridge"]["state"],
                      (live.BRIDGE_LOADED, live.BRIDGE_NOT_LOADED))


class TestSceneDegrades(unittest.TestCase):
    def test_helper_down_degrades_the_whole_scene(self):
        summary = scene(live_runner=Fake(status_out="not json", status_code=1)).summary()
        self.assertFalse(summary["ok"])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["helper"]["state"], live.HELPER_DOWN)
        self.assertEqual(summary["level"]["state"], live.LEVEL_UNAVAILABLE)
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_NOT_LOADED)
        self.assertEqual(summary["graph"]["state"], live.GRAPH_NOT_CHECKED)
        self.assertIn("bridge", summary["degraded"])

    def test_helper_not_elevated_is_its_own_state(self):
        summary = scene(live_runner=Fake(status_out='{"pid": 1, "elevated": false}')).summary()
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["helper"]["state"], live.HELPER_NOT_ELEVATED)
        self.assertEqual(summary["level"]["state"], live.LEVEL_UNAVAILABLE)

    def test_level_read_failure_is_named(self):
        summary = scene(live_runner=Fake(level_out='{"ok": false, "error": "UNAVAILABLE"}')).summary()
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["helper"]["state"], live.HELPER_ACTIVE)
        self.assertEqual(summary["level"]["state"], live.LEVEL_UNAVAILABLE)

    def test_unverified_level_is_named(self):
        summary = scene(live_runner=Fake(
            level_out='{"ok": true, "levelId": 5, "levelObservation": {"verified": false}, "entities": 1}')).summary()
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["level"]["state"], live.LEVEL_UNVERIFIED)

    def test_bridge_not_loaded_leaves_the_graph_unchecked(self):
        summary = scene(bridge_probe=BRIDGE_DOWN).summary()
        self.assertTrue(summary["ok"])              # the level WAS read
        self.assertFalse(summary["complete"])       # but the scene is not whole
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_NOT_LOADED)
        self.assertEqual(summary["graph"]["state"], live.GRAPH_NOT_CHECKED)
        self.assertEqual(summary["degraded"], ["bridge", "graph"])

    def test_graph_absent_is_its_own_state(self):
        summary = scene(graph_runner=FakeGraph(ok=False)).summary()
        self.assertTrue(summary["ok"])
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_LOADED)
        self.assertEqual(summary["graph"]["state"], live.GRAPH_ABSENT)
        self.assertIn("AUTHOR_GRAPH_IDENTITY_MISMATCH", summary["graph"]["reason"])

    def test_graph_runner_that_raises_is_reported_not_crashed(self):
        summary = scene(graph_runner=FakeGraph(raises=True)).summary()
        self.assertEqual(summary["graph"]["state"], live.GRAPH_ABSENT)
        self.assertIn("RuntimeError", summary["graph"]["reason"])

    def test_missing_graph_identity_leaves_it_unchecked(self):
        summary = scene(graph_name=None, graph_id=None).summary()
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_LOADED)
        self.assertEqual(summary["graph"]["state"], live.GRAPH_NOT_CHECKED)

    def test_no_run_id_is_bridge_not_loaded(self):
        summary = scene(bridge_probe=None, run_id=None).summary()   # default probe
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_NOT_LOADED)
        self.assertIn("run id", summary["bridge"]["reason"])

    def test_directory_defective_is_named(self):
        defect = type("D", (), {"code": "missing-entry-id", "index": 3, "detail": "field 1 absent"})()
        summary = scene(gil_path="X.gil", directory_reader=lambda p: [defect]).summary()
        self.assertEqual(summary["directory"]["state"], live.DIRECTORY_DEFECTIVE)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["directory"]["data"]["defectCount"], 1)
        self.assertEqual(summary["directory"]["data"]["defects"][0]["code"], "missing-entry-id")

    def test_directory_clean_with_a_reader(self):
        summary = scene(gil_path="X.gil", directory_reader=lambda p: []).summary()
        self.assertEqual(summary["directory"]["state"], live.DIRECTORY_CLEAN)
        self.assertTrue(summary["complete"])

    def test_directory_reader_that_raises_is_named(self):
        def boom(_path):
            raise ValueError("not a container")
        summary = scene(gil_path="X.gil", directory_reader=boom).summary()
        self.assertEqual(summary["directory"]["state"], live.DIRECTORY_NOT_CHECKED)
        self.assertIn("ValueError", summary["directory"]["reason"])

    def test_every_combination_is_a_named_state_not_a_crash(self):
        runner = Fake()
        for probe in (BRIDGE_LOADED, BRIDGE_DOWN):
            for graph_runner in (FakeGraph(), FakeGraph(ok=False), FakeGraph(raises=True)):
                for live_runner in (runner,
                                    Fake(status_out="not json", status_code=1),
                                    Fake(status_out='{"pid":1,"elevated":false}'),
                                    Fake(level_out='{"ok": false, "error": "UNAVAILABLE"}')):
                    summary = scene(live_runner=live_runner, graph_runner=graph_runner,
                                    bridge_probe=probe).summary()
                    for name in ("helper", "level", "bridge", "graph", "directory"):
                        self.assertIn("state", summary[name], name)


class TestDefaultBridgeProbe(unittest.TestCase):
    def _tree(self, tmp, run_id, receipt):
        runs = Path(tmp) / "editor-bridge" / "runs" / run_id
        runs.mkdir(parents=True, exist_ok=True)
        (runs / "bridge-ready.json").write_text(json.dumps(receipt), encoding="utf-8")
        return Path(tmp) / "editor-bridge" / "elevated-queue"

    def test_accepted_true_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = self._tree(tmp, RUN, {"accepted": True})
            loaded, reason = live.default_bridge_probe(queue)(RUN)
        self.assertTrue(loaded)
        self.assertEqual(reason, "")

    def test_accepted_false_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = self._tree(tmp, RUN, {"accepted": False, "code": 7})
            loaded, reason = live.default_bridge_probe(queue)(RUN)
        self.assertFalse(loaded)
        self.assertIn("not true", reason)

    def test_missing_ready_file_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "editor-bridge" / "elevated-queue"
            loaded, reason = live.default_bridge_probe(queue)(RUN)
        self.assertFalse(loaded)
        self.assertIn("no bridge-ready.json", reason)

    def test_no_run_id_is_not_loaded(self):
        loaded, reason = live.default_bridge_probe("Q")(None)
        self.assertFalse(loaded)

    def test_malformed_run_id_is_not_loaded(self):
        loaded, reason = live.default_bridge_probe("Q")("not-a-uuid")
        self.assertFalse(loaded)
        self.assertIn("UUID", reason)


class TestReadOnly(unittest.TestCase):
    """The scene read must be read-only: no path it touches is ever opened for write."""

    def test_graph_argv_matches_cli_graph_status(self):
        from tools.gameplan import cli

        captured = []
        args = cli.build_parser().parse_args([
            "graph-status", "--graph-id", str(GRAPH_ID), "--run-id", RUN, "--name", NAME,
            "--scratch-dir", "X", "--queue-dir", "Q"])
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_graph_status(args, runner=lambda argv: (captured.append(list(argv)) or
                                                            {"ok": True, "backend": {"nodes": []}}))
        own_argv, _ = live._graph_status_argv(python="python", queue_dir=Path("Q"), name=NAME,
                                              graph_id=GRAPH_ID, run_id=RUN)
        self.assertEqual(own_argv, captured[0])

    def test_it_only_ever_dispatches_read_ops(self):
        live_runner, graph_runner = Fake(), FakeGraph()
        scene(live_runner=live_runner, graph_runner=graph_runner)
        dispatched = " ".join(" ".join(c) for c in live_runner.calls + graph_runner.calls)
        for forbidden in ("create", "add-node", "wire", "value", "bind", "save",
                          "delete", "build-plan", "export", "reopen"):
            self.assertNotIn(forbidden, dispatched)
        # The one graph dispatch it makes is an inspect.
        self.assertEqual(graph_runner.calls[0][graph_runner.calls[0].index("graph") + 1], "inspect")

    def test_scene_read_opens_no_path_for_writing(self):
        writes: list[str] = []
        real_open = Path.open

        def guard(self, mode="r", *args, **kwargs):
            if any(ch in mode for ch in "wax+"):
                writes.append(str(self))
                raise AssertionError(f"open for write: {self} ({mode})")
            return real_open(self, mode, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "editor-bridge" / "runs" / RUN
            runs.mkdir(parents=True, exist_ok=True)
            (runs / "bridge-ready.json").write_text('{"accepted": true}', encoding="utf-8")
            gil = Path(tmp) / "level.gil"
            gil.write_bytes(b"not a container, but a real read")

            with mock.patch.object(Path, "open", guard), \
                 mock.patch.object(Path, "write_text",
                                   lambda *a, **k: (_ for _ in ()).throw(AssertionError("write_text"))), \
                 mock.patch.object(Path, "write_bytes",
                                   lambda *a, **k: (_ for _ in ()).throw(AssertionError("write_bytes"))), \
                 mock.patch.object(Path, "mkdir",
                                   lambda *a, **k: (_ for _ in ()).throw(AssertionError("mkdir"))):
                # Only the two shell-out runners are injected; the bridge probe and the
                # directory reader use their real (read-only) defaults.
                summary = read_scene(
                    Path(tmp) / "editor-bridge" / "elevated-queue",
                    runner=Fake(), graph_runner=FakeGraph(), graph_name=NAME,
                    graph_id=GRAPH_ID, run_id=RUN, gil_path=gil).summary()

        self.assertEqual(writes, [])
        self.assertEqual(summary["bridge"]["state"], live.BRIDGE_LOADED)
        self.assertIn(summary["directory"]["state"],
                      (live.DIRECTORY_CLEAN, live.DIRECTORY_DEFECTIVE, live.DIRECTORY_NOT_CHECKED))


class TestSceneCli(unittest.TestCase):
    """``live --scene`` wires the flags through to :func:`read_scene` and exits on ``ok``."""

    def _run(self, scene_obj, argv):
        captured = {}

        def fake_read_scene(queue_dir, **kwargs):
            captured["queue_dir"] = queue_dir
            captured.update(kwargs)
            return scene_obj

        buf = io.StringIO()
        with mock.patch.object(live, "read_scene", fake_read_scene), \
             contextlib.redirect_stdout(buf):
            code = live.main(argv)
        return code, json.loads(buf.getvalue()), captured

    def test_scene_flag_passes_every_knob(self):
        code, payload, captured = self._run(scene(), [
            "--scene", "--queue-dir", "QQ", "--run-id", RUN, "--graph-name", NAME,
            "--graph-id", str(GRAPH_ID), "--gil", "X.gil", "--python", "py"])
        self.assertEqual(code, 0)
        self.assertTrue(payload["complete"])
        self.assertEqual(captured["queue_dir"], "QQ")
        self.assertEqual(captured["run_id"], RUN)
        self.assertEqual(captured["graph_name"], NAME)
        self.assertEqual(captured["graph_id"], GRAPH_ID)
        self.assertEqual(captured["gil_path"], "X.gil")
        self.assertEqual(captured["python"], "py")

    def test_scene_exit_code_follows_ok(self):
        down = scene(live_runner=Fake(status_out="not json", status_code=1))
        code, payload, _ = self._run(down, ["--scene"])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
