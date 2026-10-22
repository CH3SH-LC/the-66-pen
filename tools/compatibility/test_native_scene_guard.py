"""Focused offline tests for the native-scene guard and the author scene gate.

Everything here is ``unittest`` plus mocks: no test opens the installed game
image or the editor assembly, queries a session, reads memory, starts a process,
imports a bridge or asks for UAC.  The author-side tests live in this file
because the bounded integration that added them owns only this new file; the
existing ``tools/authoring/test_author.py`` is deliberately not edited.

Covered here:
  * ``native-scene`` calls exactly ``load_profile`` + ``verify_disk`` and reports
    disk-only evidence: no session query, no process access, no write permission
  * unknown, unimportable or mismatched verification fails closed
  * ``game`` / ``editor`` / ``all`` keep their legacy meaning; a verified 7.1
    disk profile does not widen them and they never reach the native module
  * author argv and the journal fingerprint carry session / review / level
  * a mutating scene command without ``--review`` refuses with
    ``NATIVE_WRITE_REVIEW_REQUIRED`` and leaves no journal entry and no transport
  * the graph route still uses the editor assembly baseline
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "authoring"))

import author  # noqa: E402
import version_guard as guard  # noqa: E402

COMPATIBLE = {"ok": True, "code": "compatible", "component": "all"}
IMAGE = Path("D:/fixture/YuanShen.exe")


class FakeNativeProfileModule:
    """Stand-in for ``tools/game-executor/native_profiles.py``.

    It records every call, so a test can assert that nothing beyond
    ``load_profile`` and ``verify_disk`` was reached.  The session/process
    entry points of the real module exist here only to fail the test if the
    guard ever touches them.
    """

    PROFILE_SHA256 = "ff" * 32
    ANCHOR_NAMES = ("CONTEXT", "LEVEL", "PLACE", "SAVE")

    def __init__(self, *, observed=None, load_error=None, verify_error=None):
        self.calls = []
        self.profile = {
            "profileId": "genshin-cn-7.1.0-readonly",
            "allowWrites": False,
            "image": {"fileBytes": 445_000_000, "sha256": "ab" * 32,
                      "timestamp": 1788945104, "sizeOfImage": 0x1A2B3C4D},
        }
        self.observed = observed if observed is not None else {
            "profileId": "genshin-cn-7.1.0-readonly", "sha256": "ab" * 32,
            "timestamp": 1788945104, "sizeOfImage": 0x1A2B3C4D,
            "anchorNames": list(self.ANCHOR_NAMES), "allowWrites": False}
        self.load_error, self.verify_error = load_error, verify_error

    @staticmethod
    def _forbidden(*args, **kwargs):
        raise AssertionError("native-scene must not reach a session or process API")

    def load_profile(self, path=None):
        self.calls.append(("load_profile", path))
        if self.load_error:
            raise self.load_error
        return self.profile

    def verify_disk(self, profile, image=None):
        self.calls.append(("verify_disk", profile, image))
        if self.verify_error:
            raise self.verify_error
        return self.observed

    # Present in the real module; touching any of them is a failure here.
    query_identity = _forbidden
    discover_session = _forbidden
    validate_session = _forbidden
    windows_api = _forbidden
    require_action = _forbidden


class NativeSceneDiskOnlyTests(unittest.TestCase):
    """The native-scene component is disk evidence and nothing more."""

    def test_reports_disk_only_evidence_and_calls_only_the_disk_verifier(self):
        fake = FakeNativeProfileModule()
        with patch.object(guard, "native_profiles_module", return_value=fake):
            report = guard.check_native_scene(image=IMAGE)
        self.assertTrue(report["matched"], report["reasons"])
        self.assertFalse(report["runtimeCompatible"])
        self.assertFalse(report["runtimeVerified"])
        self.assertTrue(report["diskEvidenceOnly"])
        self.assertFalse(report["writePermission"])
        self.assertFalse(report["sessionQueried"])
        self.assertFalse(report["processAccess"])
        self.assertEqual(report["path"], str(IMAGE))
        for word in ("review", "session", "snapshot", "level"):
            self.assertIn(word, report["downstreamChecks"])
        self.assertEqual([call[0] for call in fake.calls], ["load_profile", "verify_disk"])
        self.assertIsNone(fake.calls[0][1])  # default pinned profile
        self.assertIs(fake.calls[1][1], fake.profile)
        self.assertEqual(fake.calls[1][2], IMAGE)

    def test_checks_echo_the_enforced_profile_values(self):
        fake = FakeNativeProfileModule()
        with patch.object(guard, "native_profiles_module", return_value=fake):
            report = guard.check_native_scene(image=IMAGE)
        self.assertTrue(all(check["match"] for check in report["checks"]), report["checks"])
        checks = {check["check"]: check for check in report["checks"]}
        self.assertEqual(checks["profileSourceHash"]["expected"], fake.PROFILE_SHA256)
        self.assertEqual(checks["imageSha256"]["expected"], fake.profile["image"]["sha256"])
        self.assertEqual(checks["imageSha256"]["actual"], fake.observed["sha256"])
        self.assertEqual(checks["imageFileBytes"]["expected"], fake.profile["image"]["fileBytes"])
        self.assertEqual(checks["anchors"]["actual"], sorted(fake.ANCHOR_NAMES))
        self.assertEqual(checks["allowWrites"]["actual"], False)

    def test_profile_path_selects_what_is_read_not_what_is_accepted(self):
        fake = FakeNativeProfileModule()
        supplied = Path("D:/profiles/other-readonly.json")
        with patch.object(guard, "native_profiles_module", return_value=fake):
            report = guard.check_native_scene(profile_path=supplied, image=IMAGE)
        self.assertEqual(fake.calls[0][1], supplied)
        self.assertEqual(report["profilePath"], str(supplied))
        # The source is still hash-pinned by load_profile(), and the pin is what
        # the report echoes -- a supplied path cannot change what is accepted.
        self.assertEqual(report["profileSha256Pin"], fake.PROFILE_SHA256)
        checks = {check["check"]: check for check in report["checks"]}
        self.assertEqual(checks["profileSourceHash"]["expected"], fake.PROFILE_SHA256)

    def test_unknown_mismatch_or_unimportable_fails_closed(self):
        cases = {
            "profile-source-hash": FakeNativeProfileModule(
                load_error=ValueError("PROFILE_SOURCE_HASH_MISMATCH")),
            "game-source-hash": FakeNativeProfileModule(
                verify_error=ValueError("GAME_SOURCE_HASH_MISMATCH")),
            "missing-image": FakeNativeProfileModule(verify_error=OSError("no such file")),
            "truncated-image": FakeNativeProfileModule(
                verify_error=RuntimeError("GAME_ANCHOR_MISMATCH:SAVE")),
        }
        for label, fake in cases.items():
            with self.subTest(case=label):
                with patch.object(guard, "native_profiles_module", return_value=fake):
                    report = guard.check_native_scene(image=IMAGE)
                self.assertFalse(report["matched"])
                self.assertTrue(report["reasons"])
                self.assertEqual(report["checks"], [])
                self.assertFalse(report["runtimeCompatible"])
                self.assertFalse(report["runtimeVerified"])
                self.assertTrue(report["diskEvidenceOnly"])
                self.assertFalse(report["writePermission"])
        with patch.object(guard, "native_profiles_module", side_effect=ImportError("no module")):
            report = guard.check_native_scene(image=IMAGE)
        self.assertFalse(report["matched"])
        self.assertTrue(any("ImportError" in reason for reason in report["reasons"]), report["reasons"])

    def test_a_profile_that_allows_writes_is_never_a_match(self):
        fake = FakeNativeProfileModule(observed={
            "profileId": "genshin-cn-7.1.0-readonly", "sha256": "ab" * 32, "timestamp": 1788945104,
            "sizeOfImage": 0x1A2B3C4D, "anchorNames": list(FakeNativeProfileModule.ANCHOR_NAMES),
            "allowWrites": True})
        with patch.object(guard, "native_profiles_module", return_value=fake):
            report = guard.check_native_scene(image=IMAGE)
        self.assertFalse(report["matched"])
        self.assertTrue(any("allowWrites" in reason for reason in report["reasons"]), report["reasons"])


class LegacyGateIsNotBroadenedTests(unittest.TestCase):
    """game / editor / all keep refusing independently of the native profile."""

    def setUp(self):
        context = tempfile.TemporaryDirectory()
        self.addCleanup(context.cleanup)
        self.dir = Path(context.name)
        self.enter = [
            patch.object(guard, "GAME_IMAGE", self.dir / "absent-YuanShen.exe"),
            patch.object(guard, "EDITOR_DLL", self.dir / "absent-BeyondEditor.dll"),
            patch.object(guard, "GAME_CONFIG", self.dir / "absent-config.ini"),
        ]
        for patcher in self.enter:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_legacy_components_never_reach_the_native_module(self):
        with patch.object(guard, "native_profiles_module",
                          side_effect=AssertionError("legacy components must not import the native profile")):
            for component in ("game", "editor", "all"):
                with self.subTest(component=component):
                    report = guard.check_compatibility(component)
                    self.assertEqual(report["code"], "incompatible-version")
                    self.assertNotIn("native-scene", report["components"])
        with self.assertRaises(ValueError):
            guard.check_compatibility("native-scene-all")

    def test_a_verified_native_disk_profile_does_not_widen_all(self):
        fake = FakeNativeProfileModule()
        with patch.object(guard, "native_profiles_module", return_value=fake):
            native = guard.check_compatibility("native-scene")
            self.assertTrue(native["ok"], native["reasons"])
            self.assertEqual(native["code"], "compatible")
            self.assertEqual(set(native["components"]), {"native-scene"})
            fake.calls.clear()
            legacy = guard.check_compatibility("all")
            self.assertEqual(fake.calls, [])
        self.assertFalse(legacy["ok"])
        self.assertEqual(legacy["code"], "incompatible-version")
        self.assertEqual(set(legacy["components"]), {"game", "editor"})
        self.assertFalse(legacy["runtimeCompatible"])

    def test_cli_exit_codes_and_component_choices(self):
        with patch.object(guard, "native_profiles_module", return_value=FakeNativeProfileModule()):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(guard.main(["--component", "native-scene"]), 0)
        payload = json.loads(stream.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["components"]["native-scene"]["component"], "native-scene")
        self.assertFalse(payload["components"]["native-scene"]["runtimeCompatible"])
        self.assertTrue(payload["components"]["native-scene"]["diskEvidenceOnly"])

        with patch.object(guard, "native_profiles_module", side_effect=ImportError("missing")):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(guard.main(["--component", "native-scene"]), 2)
        payload = json.loads(stream.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "incompatible-version")
        self.assertNotIn("Traceback", stream.getvalue())

        with self.assertRaises(SystemExit):
            guard.main(["--component", "everything"])


class AuthorSceneGateTests(unittest.TestCase):
    """author.py: native-scene for scene, editor for graph, review for writes."""

    def setUp(self):
        # No test may reach the real installation or the real guard.
        self.gate = patch.object(author, "require_compatible", return_value=COMPATIBLE)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def command(self, *extra, action="save", level=1073741834, request_id="bound"):
        argv = ["entity-create" if action == "create" else action, "--request-id", request_id,
                "--level-id", str(level), *extra]
        if action == "create":
            argv += ["--template-id", "20001034", "--position", "1", "2", "-2"]
        return author.command_from_args(author.parser().parse_args(argv))

    def test_component_selection_matches_the_new_routing(self):
        self.assertEqual(author.guard_component({"backend": "scene"}), "native-scene")
        self.assertEqual(author.guard_component({"backend": "graph"}), "editor")
        self.assertEqual(author.guard_component({}), "all")
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(author, "require_compatible", return_value=COMPATIBLE) as gate:
                author.execute({"backend": "scene", "action": "inspect", "mutating": False},
                               "scene-1", journal=Path(folder), transport=lambda _: {"ok": True})
                author.execute({"backend": "graph", "mutating": False},
                               "graph-1", journal=Path(folder), transport=lambda _: {"ok": True})
        self.assertEqual([call.args[0] for call in gate.call_args_list], ["native-scene", "editor"])

    def test_argv_carries_session_review_level_and_baseline(self):
        supplied = self.command("--session", "D:/sessions/current-native-session.json",
                               "--review", "D:/reviews/req.json",
                               "--baseline", str(Path("D:/reviews/baseline.json")))
        self.assertEqual(supplied["levelId"], 1073741834)
        self.assertEqual(supplied["session"], str(Path("D:/sessions/current-native-session.json")))
        self.assertEqual(supplied["review"], str(Path("D:/reviews/req.json")))
        self.assertEqual(supplied["baseline"], str(Path("D:/reviews/baseline.json")))
        with patch.object(author, "process_json", return_value={"ok": True}) as dispatch:
            author.scene_call(supplied)
        sent = dispatch.call_args.args[0]
        self.assertEqual(sent[1], str(author.ROOT / "tools/game-executor/scene_cli.py"))
        for flag, value in (("--level-id", "1073741834"),
                            ("--session", str(Path("D:/sessions/current-native-session.json"))),
                            ("--review", str(Path("D:/reviews/req.json"))),
                            ("--baseline", str(Path("D:/reviews/baseline.json")))):
            self.assertIn(flag, sent)
            self.assertEqual(sent[sent.index(flag) + 1], value if flag == "--level-id" else str(Path(value)))
        self.assertEqual(dispatch.call_args.kwargs["environment"]["MILIASTRA_LEVEL"], "1073741834")

    def test_omitted_session_and_baseline_stay_optional(self):
        command = self.command("--review", str(Path("D:/reviews/req.json")))
        self.assertNotIn("session", command)
        self.assertNotIn("baseline", command)
        with patch.object(author, "process_json", return_value={"ok": True}) as dispatch:
            author.scene_call(command)
        sent = dispatch.call_args.args[0]
        self.assertNotIn("--session", sent)
        self.assertNotIn("--baseline", sent)
        self.assertEqual(sent[sent.index("--level-id") + 1], "1073741834")

    def test_supplied_paths_are_bound_into_the_fingerprint(self):
        first = self.command("--session", "D:/sessions/a.json", "--review", str(Path("D:/reviews/req.json")))
        second = self.command("--session", "D:/sessions/b.json", "--review", str(Path("D:/reviews/req.json")))
        digest = lambda command: author.hashlib.sha256(author.encoded(command).encode("utf-8")).hexdigest()
        self.assertNotEqual(digest(first), digest(second))
        with tempfile.TemporaryDirectory() as folder:
            dispatched = []
            result = author.execute(first, "bound", journal=Path(folder),
                                    transport=lambda command: dispatched.append(command) or {"ok": True})
            self.assertTrue(result["ok"])
            claim = json.loads((Path(folder) / "bound" / "claim.json").read_text(encoding="utf-8"))
            self.assertEqual(claim["sha256"], digest(first))
            self.assertEqual(claim["command"]["session"], str(Path("D:/sessions/a.json")))
            self.assertEqual(claim["command"]["review"], str(Path("D:/reviews/req.json")))
            self.assertEqual(claim["command"]["levelId"], 1073741834)
            with self.assertRaisesRegex(ValueError, "CONFLICT"):
                author.execute(second, "bound", journal=Path(folder),
                               transport=lambda command: dispatched.append(command) or {"ok": True})
            self.assertEqual(len(dispatched), 1)

    def test_mutating_scene_without_review_refuses_before_journal_or_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            dispatched = []
            for action in ("create", "save", "create-batch"):
                with self.subTest(action=action):
                    result = author.execute({"backend": "scene", "action": action, "mutating": True},
                                            "no-review", journal=Path(folder), transport=dispatched.append)
                    self.assertEqual(result["code"], "NATIVE_WRITE_REVIEW_REQUIRED")
                    self.assertEqual(result["error"], "NATIVE_WRITE_REVIEW_REQUIRED")
                    self.assertFalse(result["ok"])
                    self.assertFalse(result["outcomeUncertain"])
                    self.assertFalse(result["retryAttempted"])
                    self.assertIsNone(result["journal"])
            self.assertEqual(dispatched, [])
            self.assertEqual(list(Path(folder).iterdir()), [])
        # A read-only inspection is not a write and needs no review.
        with tempfile.TemporaryDirectory() as folder:
            inspected = author.execute({"backend": "scene", "action": "inspect", "mutating": False},
                                       "inspect-1", journal=Path(folder), transport=lambda _: {"ok": True})
        self.assertTrue(inspected["ok"])

    def test_cli_write_without_review_is_a_structured_refusal(self):
        argv = ["author.py", "entity-create", "--request-id", "cli-no-review",
                "--level-id", "1073741834", "--template-id", "20001034",
                "--position", "0", "0", "0", "--session", "D:/sessions/a.json"]
        with tempfile.TemporaryDirectory() as folder:
            stream = io.StringIO()
            with patch.object(author, "require_compatible",
                              side_effect=AssertionError("gate must not be reached")), \
                 patch.object(author, "JOURNAL", Path(folder)), \
                 patch.object(sys, "argv", argv), contextlib.redirect_stdout(stream):
                self.assertEqual(author.main(), 2)
            self.assertEqual(list(Path(folder).iterdir()), [])
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["code"], "NATIVE_WRITE_REVIEW_REQUIRED")
        self.assertFalse(payload["outcomeUncertain"])

    def test_cli_write_with_review_reaches_scene_cli_with_every_explicit_path(self):
        argv = ["author.py", "save", "--request-id", "cli-with-review", "--level-id", "1073741834",
                "--review", "D:/reviews/req.json", "--session", "D:/sessions/a.json"]
        with tempfile.TemporaryDirectory() as folder:
            stream = io.StringIO()
            with patch.object(author, "require_compatible", return_value=COMPATIBLE) as gate, \
                 patch.object(author, "JOURNAL", Path(folder)), \
                 patch.object(author, "process_json", return_value={"ok": True}) as dispatch, \
                 patch.object(sys, "argv", argv), contextlib.redirect_stdout(stream):
                self.assertEqual(author.main(), 0)
            sent = dispatch.call_args.args[0]
            self.assertIn("save", sent)
        self.assertTrue(gate.call_args_list)
        self.assertEqual({call.args[0] for call in gate.call_args_list}, {"native-scene"})
        self.assertEqual(sent[sent.index("--review") + 1], str(Path("D:/reviews/req.json")))
        self.assertEqual(sent[sent.index("--session") + 1], str(Path("D:/sessions/a.json")))
        self.assertEqual(sent[sent.index("--level-id") + 1], "1073741834")
        self.assertTrue(json.loads(stream.getvalue())["ok"])

    def test_graph_route_is_unchanged(self):
        argv = ["author.py", "graph", "add", "--request-id", "graph-1",
                "--run-id", str(author.uuid.uuid4()), "--name", "MW_API_test", "--graph-id", "3",
                "--definition-id", "71", "--expected-node-count", "0"]
        command = author.command_from_args(author.parser().parse_args(argv[1:]))
        self.assertEqual(command["backend"], "graph")
        for field in ("session", "review", "baseline"):
            self.assertNotIn(field, command)
        self.assertFalse(author.missing_review(command))  # review is a scene-write rule only
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(author, "require_compatible", return_value=COMPATIBLE) as gate:
                author.execute(command, "graph-1", journal=Path(folder),
                               transport=lambda _: {"ok": True})
        self.assertEqual([call.args[0] for call in gate.call_args_list], ["editor"])

    def test_capabilities_state_the_requirements_without_claiming_live_writes(self):
        payload = author.capabilities()
        self.assertIn("session", payload["sceneSession"])
        self.assertIn("level", payload["sceneLevel"])
        self.assertIn("review", payload["sceneReview"])
        self.assertFalse(payload["officialPlaytestVerified"])
        self.assertFalse(payload["liveWriteVerified"])
        self.assertFalse(payload["nativeWriteVerified"])
        self.assertNotIn("7.1 is not adapted", payload["liveGate"])
        self.assertIn("legacy", payload["liveGate"])


if __name__ == "__main__":
    unittest.main()
