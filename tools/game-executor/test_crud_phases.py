"""Isolated staged CRUD orchestration tests. No game/editor calls are permitted."""
from __future__ import annotations
import contextlib
import copy
import datetime as dt
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("crud_phases_under_test", HERE / "run_live_crud_acceptance.py")
crud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crud)
REAL_DATETIME = dt.datetime
LEVEL = 1073741834
EDITOR = 24680
ENTITY = 777
BASELINE = (10, 20)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def identity(entity_id):
    return dict(Category0=0, Category1=0, Category2=0, Category3=0, Id=entity_id)


class StagedCrudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.now = REAL_DATETIME(2030, 1, 1, tzinfo=dt.timezone.utc)
        owner = self
        class Clock(REAL_DATETIME):
            @classmethod
            def now(cls, tz=None):
                return owner.now.astimezone(tz) if tz else owner.now.replace(tzinfo=None)
        self.stack.enter_context(mock.patch.object(crud.datetime, "datetime", Clock))
        self.stack.enter_context(mock.patch.object(crud, "ROOT", self.root))
        self.guard = self.stack.enter_context(mock.patch.object(crud, "require_compatible", return_value={}))
        self.stack.enter_context(mock.patch.object(crud.profiles, "validate_session", side_effect=lambda s: dict(s)))
        self.stack.enter_context(mock.patch.object(crud.review_api, "validate_review", side_effect=self.review))
        self.stack.enter_context(mock.patch.object(crud, "query_editor", side_effect=lambda pid: copy.deepcopy(self.editor)))
        self.stack.enter_context(mock.patch.object(crud, "run_child", side_effect=self.child))
        self.stack.enter_context(mock.patch.object(crud.subprocess, "run", side_effect=AssertionError("UNMOCKED PROCESS CALL")))
        self.editor = dict(pid=EDITOR, startUtcTicks=123456789, expectedExe="D:/fixture/BeyondEditor.exe", processName="BeyondEditor")
        self.session = dict(schemaVersion=1, pid=12345, tid=12346, window=12347, windowClass="UnityWndClass",
                            processCreation=111, threadCreation=222, image="D:/fixture/YuanShen.exe")
        self.session_path = write(self.root / ".runtime/session.json", self.session)
        self.run = self.root / ".runtime/game-executor/crud-fixture"
        self.queue = self.root / ".runtime/editor-bridge/queue"
        self.queue.mkdir(parents=True)
        write(self.root / ".runtime/editor-bridge/current-elevated-session.json", {"queueDir": str(self.queue)})
        self.scope = str(uuid.uuid4())
        self.scope_dir = self.root / ".runtime/editor-bridge/runs" / self.scope
        self.probe_id = uuid.uuid4().hex
        self.calls = []
        self.effects = []
        self.faults = {}
        self.observed_id = ENTITY
        self.template_id = crud.CREATE_TEMPLATE_ID
        self.prefab_id = 0
        self.name = "Original Cube"
        self.created = False
        self.deleted = False
        self.probe_expires = None
        self.before = self.root / ".runtime/game-executor/native-fixtures/before.gil"
        self.before.parent.mkdir(parents=True)
        self.before.write_bytes(b"fixture-before")
        self.review_calls = []

    def fresh_review(self, phase):
        baseline = self.root / ".runtime/reviews" / (phase + "-" + uuid.uuid4().hex)
        write(baseline / "exit.json", dict(executed=True, exitCode=0,
              startedUtc=(self.now-dt.timedelta(seconds=3)).isoformat(),
              finishedUtc=(self.now-dt.timedelta(seconds=2)).isoformat()))
        return write(baseline / "review.json", {
            "reviewId": str(uuid.uuid4()), "phase": phase, "levelId": LEVEL, "session": self.session,
            "baselineRun": str(baseline), "reviewedAtUtc": (self.now-dt.timedelta(seconds=1)).isoformat()})

    def review(self, path, session, level, request):
        self.review_calls.append((str(path), copy.deepcopy(request), copy.deepcopy(session)))
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if doc["levelId"] != level or doc["session"] != session:
            raise RuntimeError("review identity mismatch")
        expected = crud.create_request(level) if doc["phase"] == "start" else crud.save_request(level)
        if expected != request:
            raise RuntimeError("review request mismatch")
        ids = list(BASELINE) + ([ENTITY] if doc["phase"] == "save-renamed" else [])
        return {"reviewId": doc["reviewId"], "reviewSha256": crud.sha256_file(path),
                "baselineRun": doc["baselineRun"], "review": doc,
                "baseline": {"entities": [{"id": i} for i in ids]}}

    def child(self, argv, *, label, run_dir, environment, timeout):
        self.assertEqual(environment["MILIASTRA_LEVEL"], str(LEVEL))
        self.calls.append({"label": label, "argv": list(argv), "timeout": timeout})
        if label == "load-editor":
            self.effects.append(label)
            write(self.scope_dir / "bridge-settings.json", dict(pid=EDITOR, startUtcTicks="123456789",
                expectedExe=self.editor["expectedExe"], nonce="temporary-test-nonce",
                pipeName="fixture-" + self.scope, expiresUtc=(self.now+dt.timedelta(seconds=300)).isoformat()))
            reply = {"accepted": True, "runId": self.scope}
        elif label == "transport-before-create":
            reply = dict(ok=True, transportSocket=dict(observed=True, connectedFlag=True,
                loopbackEndpoints=True, localPort=50001, remotePort=50002, selfConnection=False))
        elif label == "begin-entity-crud-probe":
            self.probe_expires = (self.now+dt.timedelta(seconds=180)).isoformat()
            reply = dict(ok=True, probeId=self.probe_id, expiresUtc=self.probe_expires,
                         observedUtc=self.now.isoformat(), levelIdentityVerified=False,
                         baseline=[{"identity": identity(i)} for i in BASELINE])
        elif label == "create":
            self.effects.append(label)
            self.created = True
            reply = dict(ok=True, levelId=LEVEL, entityId=ENTITY,
                         beforeGils={str(LEVEL): {"snapshot": str(self.before)}})
        elif label.startswith("inspect"):
            if self.deleted:
                reply = dict(ok=True, probeId=self.probe_id, targetAbsentFromAuxiliaryRegistry=True, newEntityCount=0)
            else:
                reply = dict(ok=True, probeId=self.probe_id, expiresUtc=self.probe_expires,
                    originalName="Original Cube", frontendMaterialized=True,
                    entity=dict(identity=identity(self.observed_id), name=self.name, templateId=self.template_id,
                                prefabId=self.prefab_id,
                                nativeEntityType=1402, nativeInstanceKind=0))
        elif label == "rename-entity-crud-probe":
            self.effects.append(label)
            self.name = crud.PROBE_NAME
            reply = dict(ok=True, probeId=self.probe_id, identity=identity(self.observed_id),
                         requestedName=self.name, invokedUtc=self.now.isoformat())
        elif label == "delete-entity-crud-probe":
            self.effects.append(label)
            self.deleted = True
            reply = dict(ok=True, probeId=self.probe_id, identity=identity(self.observed_id),
                         nativeResult=True, invokedUtc=self.now.isoformat())
        elif label in ("save-renamed", "save-deleted"):
            self.effects.append(label)
            path = self.before.parent / (label + ".gil")
            path.write_bytes(label.encode())
            reply = dict(ok=True, levelId=LEVEL, nativeStatus=0,
                         afterGils={str(LEVEL): {"snapshot": str(path)}}, gilChanged={str(LEVEL): True})
        elif label.startswith("verify"):
            output = Path(argv[argv.index("--out")+1])
            write(output, {"ok": True, "fixture": True})
            reply = {"ok": True}
        elif label == "stop-owned-editor-scope":
            self.effects.append(label)
            self.assertEqual(argv[argv.index("--run-id")+1], self.scope)
            reply = dict(ok=True, stopped=True, cleanupComplete=False, status="listener-stop-requested")
        else:
            raise AssertionError("Unexpected dispatch " + label)
        fault = self.faults.get(label)
        if fault == "timeout":
            raise subprocess.TimeoutExpired(argv, timeout, output=b"partial receipt")
        if fault == "malformed":
            return subprocess.CompletedProcess(argv, 0, "{bad-json", "")
        if fault == "false":
            reply = {"ok": False}
        if callable(fault):
            reply = fault(reply)
        return subprocess.CompletedProcess(argv, 0, json.dumps(reply), "")

    def invoke(self, phase, *, review="auto", extra=()):
        self.now += dt.timedelta(seconds=10)
        args = ["--phase", phase, "--run-dir", str(self.run), "--run", "--session", str(self.session_path),
                "--editor-pid", str(EDITOR), "--level-id", str(LEVEL)]
        if review == "auto" and phase in crud.REVIEW_PHASES:
            review = self.fresh_review(phase)
        if review not in ("auto", None):
            args += ["--review", str(review)]
        args += list(extra)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = crud.main(args)
            except SystemExit as e:
                code = e.code
        text = out.getvalue()
        try: result = json.loads(text)
        except ValueError: result = {"text": text, "stderr": err.getvalue()}
        return code, result

    def advance(self, through):
        for phase in crud.PHASES:
            code, result = self.invoke(phase)
            self.assertEqual(code, 0, (phase, result))
            if phase == through:
                break

    def test_six_phase_flow_forwards_explicit_inputs_and_stops_only_owned_scope(self):
        self.advance("verify")
        target = json.loads((self.run/"probe.json").read_text(encoding="utf-8"))["target"]
        self.assertEqual(target["templateId"], crud.CREATE_TEMPLATE_ID)
        self.assertEqual(target["prefabId"], 0)
        self.assertEqual(self.effects, ["load-editor", "create", "rename-entity-crud-probe",
                          "save-renamed", "delete-entity-crud-probe", "save-deleted", "stop-owned-editor-scope"])
        self.assertEqual([c.args[0] for c in self.guard.call_args_list],
                         ["native-scene", "editor"] * 6)
        for call in self.calls:
            if call["label"] in ("create", "save-renamed", "save-deleted"):
                argv = call["argv"]
                self.assertEqual(argv[argv.index("--session")+1], str(self.session_path))
                self.assertEqual(argv[argv.index("--level-id")+1], str(LEVEL))
                self.assertTrue(Path(argv[argv.index("--review")+1]).is_file())
                self.assertEqual(argv.count("--elevated-queue"), 1)
                self.assertEqual(argv[argv.index("--elevated-queue")+1], str(self.queue))
        self.assertEqual(len(self.review_calls), 3)
        final = json.loads((self.run/"phases/verify.result.json").read_text())
        self.assertFalse(final["evidence"]["scopeStop"]["cleanupComplete"])

    def test_legacy_command_and_missing_review_refuse_before_children(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                crud.main(["--run", "--editor-pid", str(EDITOR), "--level-id", str(LEVEL)])
        code, _ = self.invoke("start", review=None)
        self.assertEqual(code, 2)
        self.assertFalse(self.run.exists())
        self.assertEqual(self.calls, [])
        self.advance("rename")
        before = len(self.calls)
        self.assertEqual(self.invoke("save-renamed", review=None)[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_duplicate_phase_does_not_dispatch(self):
        self.advance("rename")
        before = len(self.calls)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_wrong_level_or_editor_pid_refuses_before_dispatch(self):
        self.advance("start")
        before = len(self.calls)
        for extra in [("--level-id", str(LEVEL+1)), ("--editor-pid", str(EDITOR+1))]:
            with self.subTest(extra=extra):
                self.assertEqual(self.invoke("rename", extra=extra)[0], 2)
                self.assertEqual(len(self.calls), before)

    def test_changed_session_file_refuses(self):
        self.advance("start")
        write(self.session_path, dict(self.session, processCreation=999))
        before = len(self.calls)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_actual_editor_creation_change_refuses(self):
        self.advance("start")
        self.editor["startUtcTicks"] += 1
        before = len(self.calls)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_closed_scope_refuses(self):
        self.advance("start")
        write(self.scope_dir/"lease-closed.json", {"closed": True})
        before = len(self.calls)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_probe_and_scope_expiry_refuse_without_renewal(self):
        self.advance("start")
        before = len(self.calls)
        self.now += dt.timedelta(seconds=181)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.now += dt.timedelta(seconds=300)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_offline_verify_after_owned_scope_expired(self):
        self.advance("save-deleted")
        self.now += dt.timedelta(seconds=400)
        write(self.scope_dir/"lease-closed.json", {"cleanupSucceeded": True})
        before = len(self.effects)
        self.assertEqual(self.invoke("verify")[0], 0)
        self.assertEqual(len(self.effects), before)

    def test_confirmed_delete_can_persist_with_new_review_after_expiry(self):
        self.advance("delete")
        self.now += dt.timedelta(seconds=400)
        write(self.scope_dir/"lease-closed.json", {"cleanupSucceeded": True})
        before = len(self.calls)
        code, result = self.invoke("save-deleted")
        self.assertEqual(code, 0, result)
        self.assertEqual([c['label'] for c in self.calls[before:]], ['save-deleted'])

    def test_post_delete_review_rejects_other_entity_set_changes(self):
        self.advance("delete")
        original = self.review
        def changed(*args):
            result = original(*args)
            result['baseline']['entities'].append({'id': 999})
            return result
        with mock.patch.object(crud.review_api, 'validate_review', side_effect=changed):
            code, result = self.invoke('save-deleted')
        self.assertEqual(code, 2, result)
        self.assertIn('complete original entity set', result['error'])
        self.assertNotIn('save-deleted', self.effects)

    def test_mutation_unknown_blocks_later_phases_and_never_stops_foreign_scope(self):
        self.advance("start")
        self.faults["rename-entity-crud-probe"] = "timeout"
        code, result = self.invoke("rename")
        self.assertEqual(code, 1, result)
        self.assertTrue(result["result"]["outcomeUncertain"])
        before = len(self.calls)
        self.assertEqual(self.invoke("save-renamed")[0], 2)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)
        self.assertNotIn("stop-owned-editor-scope", self.effects)

    def test_malformed_and_false_mutation_replies_are_uncertain(self):
        for fault in ("malformed", "false"):
            with self.subTest(fault=fault):
                self.run = self.root / ".runtime/game-executor" / ("case-" + fault)
                self.scope = str(uuid.uuid4())
                self.scope_dir = self.root / ".runtime/editor-bridge/runs" / self.scope
                self.name, self.deleted = "Original Cube", False
                self.advance("start")
                self.faults["rename-entity-crud-probe"] = fault
                code, result = self.invoke("rename")
                self.assertEqual(code, 1, result)
                self.assertTrue(result["result"]["outcomeUncertain"])
                self.faults.clear()

    def test_editor_entity_id_must_equal_native_receipt(self):
        self.observed_id = ENTITY+1
        code, result = self.invoke("start")
        self.assertEqual(code, 1, result)
        self.assertTrue(result["result"]["outcomeUncertain"])
        self.assertFalse((self.run/"probe.json").exists())

    def test_baseline_entity_can_never_become_target(self):
        self.observed_id = BASELINE[0]
        self.assertEqual(self.invoke("start")[0], 1)
        self.assertNotIn("rename-entity-crud-probe", self.effects)

    def test_identity_drift_prevents_rename_and_delete(self):
        self.advance("start")
        self.observed_id += 1
        before = len(self.effects)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.effects), before)
        self.observed_id = ENTITY
        self.assertEqual(self.invoke("rename")[0], 0)
        self.assertEqual(self.invoke("save-renamed")[0], 0)
        self.observed_id += 1
        before = len(self.effects)
        self.assertEqual(self.invoke("delete")[0], 2)
        self.assertEqual(len(self.effects), before)

    def test_missing_template_at_create_is_unknown_and_cannot_resume(self):
        def remove_template(reply):
            reply["entity"].pop("templateId")
            return reply
        self.faults["inspect-created"] = remove_template
        code, result = self.invoke("start")
        self.assertEqual(code, 1, result)
        self.assertIn("template id", result["result"]["error"])
        self.assertTrue(result["result"]["outcomeUncertain"])
        self.assertFalse((self.run/"probe.json").exists())
        effects = list(self.effects)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(self.effects, effects)

    def test_wrong_template_at_create_is_rejected_even_with_matching_prefab(self):
        self.template_id = crud.CREATE_TEMPLATE_ID + 1
        self.prefab_id = crud.CREATE_TEMPLATE_ID
        code, result = self.invoke("start")
        self.assertEqual(code, 1, result)
        self.assertIn("template id", result["result"]["error"])
        self.assertFalse((self.run/"probe.json").exists())

    def test_template_drift_prevents_rename_and_delete(self):
        self.advance("start")
        self.template_id += 1
        before = len(self.effects)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.effects), before)
        self.assertFalse((self.run/"phases/rename.claim.json").exists())
        self.template_id = crud.CREATE_TEMPLATE_ID
        self.assertEqual(self.invoke("rename")[0], 0)
        self.assertEqual(self.invoke("save-renamed")[0], 0)
        self.template_id += 1
        before = len(self.effects)
        self.assertEqual(self.invoke("delete")[0], 2)
        self.assertEqual(len(self.effects), before)
        self.assertFalse((self.run/"phases/delete.claim.json").exists())

    def test_prefab_cache_drift_prevents_rename_and_delete(self):
        self.advance("start")
        self.prefab_id = 1
        before = len(self.effects)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.effects), before)
        self.assertFalse((self.run/"phases/rename.claim.json").exists())
        self.prefab_id = 0
        self.assertEqual(self.invoke("rename")[0], 0)
        self.assertEqual(self.invoke("save-renamed")[0], 0)
        self.prefab_id = 1
        before = len(self.effects)
        self.assertEqual(self.invoke("delete")[0], 2)
        self.assertEqual(len(self.effects), before)
        self.assertFalse((self.run/"phases/delete.claim.json").exists())

    def test_template_and_prefab_contract_rejects_missing_or_ambiguous_values(self):
        self.advance("start")
        probe = json.loads((self.run/"probe.json").read_text(encoding="utf-8"))
        observation = dict(ok=True, probeId=self.probe_id, expiresUtc=self.probe_expires,
                           originalName="Original Cube",
                           entity=dict(identity=identity(ENTITY), name=self.name,
                                       templateId=crud.CREATE_TEMPLATE_ID, prefabId=0,
                                       nativeEntityType=1402, nativeInstanceKind=0))
        crud.require_target_entity(observation, probe, (self.name,), ENTITY)
        for key, bad_values in (
            ("templateId", (None, True, str(crud.CREATE_TEMPLATE_ID),
                             float(crud.CREATE_TEMPLATE_ID), 0, crud.CREATE_TEMPLATE_ID+1)),
            ("prefabId", (None, False, "0", 0.0, -1, 2**32))):
            for value in bad_values:
                for side in ("observation", "target", "both"):
                    with self.subTest(key=key, value=value, side=side):
                        observed, bound = copy.deepcopy(observation), copy.deepcopy(probe)
                        if side in ("observation", "both"):
                            observed["entity"][key] = value
                        if side in ("target", "both"):
                            bound["target"][key] = value
                        with self.assertRaises(crud.CrudRefusal):
                            crud.require_target_entity(observed, bound, (self.name,), ENTITY)
        for side in ("observation", "target"):
            for key in ("templateId", "prefabId"):
                observed, bound = copy.deepcopy(observation), copy.deepcopy(probe)
                (observed["entity"] if side == "observation" else bound["target"]).pop(key)
                with self.subTest(missing=key, side=side), self.assertRaises(crud.CrudRefusal):
                    crud.require_target_entity(observed, bound, (self.name,), ENTITY)

    def test_delete_requires_saved_rename(self):
        self.advance("rename")
        before = len(self.calls)
        self.assertEqual(self.invoke("delete")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_predelete_review_is_not_valid_for_postdelete_save(self):
        self.advance("save-renamed")
        old = self.fresh_review("save-deleted")
        self.assertEqual(self.invoke("delete")[0], 0)
        before = len(self.calls)
        self.assertEqual(self.invoke("save-deleted", review=old)[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_baseline_started_before_delete_cannot_approve_later_save(self):
        self.advance("delete")
        previous = json.loads((self.run/"phases/delete.result.json").read_text())
        self.now += dt.timedelta(seconds=10)
        review = self.fresh_review("save-deleted")
        doc = json.loads(review.read_text())
        exit_path = Path(doc["baselineRun"])/"exit.json"
        evidence = json.loads(exit_path.read_text())
        evidence["startedUtc"] = (REAL_DATETIME.fromisoformat(previous["finishedUtc"])-dt.timedelta(seconds=1)).isoformat()
        write(exit_path, evidence)
        before = len(self.calls)
        self.assertEqual(self.invoke("save-deleted", review=review)[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_review_changed_after_preflight_never_dispatches_native_save(self):
        self.advance("rename")
        def alter_review(reply):
            claim_review = self.review_calls[-1][0]
            path = Path(claim_review)
            path.write_bytes(path.read_bytes()+b" ")
            return reply
        self.faults["inspect-before-save-renamed"] = alter_review
        code, result = self.invoke("save-renamed")
        self.assertEqual(code, 1, result)
        self.assertTrue(result["result"]["outcomeUncertain"])
        self.assertNotIn("save-renamed", self.effects)

    def test_queue_pointer_change_after_preflight_never_dispatches_native_save(self):
        self.advance("rename")
        moved = self.root / ".runtime/editor-bridge/moved-queue"
        moved.mkdir(parents=True)
        pointer = self.root / ".runtime/editor-bridge/current-elevated-session.json"
        def move_pointer(reply):
            write(pointer, {"queueDir": str(moved)})
            return reply
        self.faults["inspect-before-save-renamed"] = move_pointer
        code, result = self.invoke("save-renamed")
        self.assertEqual(code, 1, result)
        self.assertTrue(result["result"]["outcomeUncertain"])
        self.assertNotIn("save-renamed", self.effects)

    def test_queue_pointer_change_during_begin_never_dispatches_native_create(self):
        moved = self.root / ".runtime/editor-bridge/moved-queue"
        moved.mkdir(parents=True)
        pointer = self.root / ".runtime/editor-bridge/current-elevated-session.json"
        def move_pointer(reply):
            write(pointer, {"queueDir": str(moved)})
            return reply
        self.faults["begin-entity-crud-probe"] = move_pointer
        code, result = self.invoke("start")
        self.assertEqual(code, 1, result)
        self.assertTrue(result["result"]["outcomeUncertain"])
        self.assertNotIn("create", self.effects)

    def test_state_scope_probe_and_prior_result_tampering_refuse(self):
        self.advance("start")
        for name in ("state.json", "scope.json", "probe.json", "phases/start.result.json"):
            with self.subTest(name=name):
                path = self.run/name
                raw = path.read_bytes()
                path.write_bytes(raw+b" ")
                before = len(self.calls)
                self.assertEqual(self.invoke("rename")[0], 2)
                self.assertEqual(len(self.calls), before)
                path.write_bytes(raw)

    def test_preexisting_scope_is_not_adopted(self):
        self.scope_dir.mkdir(parents=True)
        code, result = self.invoke("start")
        self.assertEqual(code, 1, result)
        self.assertEqual([c["label"] for c in self.calls], ["load-editor"])
        self.assertNotIn("stop-owned-editor-scope", self.effects)

    def test_claim_without_result_blocks_future(self):
        self.advance("start")
        write(self.run/"phases/rename.claim.json", {"interrupted": True})
        before = len(self.calls)
        self.assertEqual(self.invoke("save-renamed")[0], 2)
        self.assertEqual(self.invoke("rename")[0], 2)
        self.assertEqual(len(self.calls), before)

    def test_already_claimed_native_review_refuses_before_load(self):
        self.now += dt.timedelta(seconds=10)
        review = self.fresh_review("start")
        review_id = json.loads(review.read_text())["reviewId"]
        write(self.root/".runtime/game-executor/native-write-review-claims"/(review_id+".json"), {"spent": True})
        self.assertEqual(self.invoke("start", review=review)[0], 2)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.run.exists())

    def test_claimed_phase_result_write_failure_is_reported_uncertain(self):
        original = crud.finish_phase
        with mock.patch.object(crud, "finish_phase", side_effect=OSError("fixture result write failure")):
            code, result = self.invoke("start")
        self.assertEqual(code, 2, result)
        self.assertTrue(result["outcomeUncertain"])
        self.assertTrue((self.run/"phases/start.claim.json").exists())
        self.assertFalse((self.run/"phases/start.result.json").exists())
        self.assertIs(crud.finish_phase, original)


    def test_self_connection_refuses_before_native_create(self):
        def self_connected(reply):
            reply['transportSocket'].update(remotePort=50001, selfConnection=True)
            return reply
        self.faults['transport-before-create'] = self_connected
        code, result = self.invoke('start')
        self.assertEqual(code, 1, result)
        self.assertIn('self-connected', result['result']['error'])
        self.assertNotIn('create', self.effects)
        self.assertFalse(any(c['label']=='begin-entity-crud-probe' for c in self.calls))

    def test_unknown_transport_refuses_before_native_create(self):
        self.faults['transport-before-create'] = lambda reply: {'ok': True}
        code, result = self.invoke('start')
        self.assertEqual(code, 1, result)
        self.assertIn('observation missing', result['result']['error'])
        self.assertNotIn('create', self.effects)


if __name__ == "__main__":
    unittest.main()
