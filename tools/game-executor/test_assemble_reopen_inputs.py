"""Offline, fixture-driven tests for the reopen-inputs assembler.

Every case builds a throwaway sandbox tree that mirrors the real
``ROOT/.runtime`` layout, then patches ``assembler.profiles.ROOT`` at the sandbox
so nothing outside the sandbox is ever read or written. No game, editor bridge or
elevated queue is contacted; no run is dispatched.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import assemble_reopen_inputs as assembler  # noqa: E402

def _find_repo_root():
    """Locate the tree that owns ``tools/game-executor/native_reopen_acceptance.py``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "tools/game-executor/native_reopen_acceptance.py").is_file():
            return parent
    return None


REAL_ROOT = _find_repo_root()
REQUEST_ID = "0123456789abcdef0123456789abcdef"
#: The synthetic index is validated by ``native_reopen_acceptance.validate``, so it
#: must bind the *same* reviewed level pin that module enforces -- a hardcoded copy of
#: the id here is what the 1839->1840 re-pin silently desynced (LEASE_IDENTITY).
import native_reopen_acceptance as _acceptance  # noqa: E402
LEVEL = _acceptance.LEVEL
FORMAL_RELATIVE = _acceptance.FORMAL_RELATIVE
SESSION = {"schemaVersion": 1, "pid": 47028, "tid": 44532, "window": 2167274,
           "windowClass": "UnityWndClass", "processCreation": 134347847364953761,
           "threadCreation": 134347847364953785,
           "image": "C:\\Games\\Genshin Impact Game\\YuanShen.exe"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_bytes(value)
    return path


def write_raw(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Sandbox:
    """One synthetic ROOT whose .runtime holds a complete, self-consistent attempt."""

    def __init__(self, base):
        self.root = Path(base)
        self.runtime = self.root / ".runtime"
        self.dispatch = self.runtime / "editor-bridge/native-dispatch"
        self.work = self.dispatch / REQUEST_ID
        self.attempt = self.runtime / "verification/attempt"
        self.source = self.root / "account"           # stands in for LocalLow/miHoYo
        self.before_files = self.runtime / "backup/before"
        self.after_files = self.runtime / "backup/after"
        self.before_run = self.runtime / "game-executor/scene-cli/inspect/run-before"
        self.action_run = self.runtime / "game-executor/reopen-current/run-action"
        self.after_run = self.runtime / "game-executor/scene-cli/inspect/run-after"

    def build(self):
        self.work.mkdir(parents=True, exist_ok=True)
        # Use the real verifier source bytes so that the lease/review binding on
        # `acceptanceVerifierSha256` matches what the imported module hashes.
        source_verifier = (REAL_ROOT / assembler.ACCEPTANCE_SOURCE) if REAL_ROOT else None
        body = source_verifier.read_bytes() if source_verifier and source_verifier.is_file() \
            else b"# stub verifier\n"
        verifier = write(self.root / assembler.ACCEPTANCE_SOURCE, body)
        formal = write(self.source / FORMAL_RELATIVE, b"GIL-FORMAL-PAYLOAD")
        player = write(self.source / "Beyond_Local_Save_Player.gip", b"PLAYER")
        rows = []
        for path in (formal, player):
            rel = path.relative_to(self.source).as_posix()
            rows.append({"relativePath": rel, "bytes": path.stat().st_size, "sha256": sha(path)})
        for backup in (self.before_files, self.after_files):
            for row in rows:
                write(backup / row["relativePath"], (self.source / row["relativePath"]).read_bytes())

        account_before = write(self.attempt / "account-before.json", {
            "createdUtc": "2026-09-27T16:10:00+00:00", "source": str(self.source),
            "backup": str(self.before_files), "fileCount": len(rows),
            "totalBytes": sum(r["bytes"] for r in rows), "files": copy.deepcopy(rows)})
        account_after = write(self.attempt / "account-after.json", {
            "createdUtc": "2026-09-27T16:20:00+00:00", "source": str(self.source),
            "backup": str(self.after_files), "fileCount": len(rows),
            "totalBytes": sum(r["bytes"] for r in rows), "files": copy.deepcopy(rows)})
        self.account_before, self.account_after, self.formal = account_before, account_after, formal

        session = write(self.attempt / "session.json", copy.deepcopy(SESSION))
        self.editor_before = write(self.attempt / "editor-before.json", {"observedUtc": "2026-09-27T16:11:00+00:00"})
        self.editor_after = write(self.attempt / "editor-after.json", {"observedUtc": "2026-09-27T16:19:00+00:00"})
        self.observer_before = write(self.attempt / "observer-before.json", {"ok": True})
        self.observer_after = write(self.attempt / "observer-after.json", {"ok": True})
        self.ipc_before = write(self.attempt / "ipc-before.json", {"processes": []})
        self.ipc_after = write(self.attempt / "ipc-after.json", {"processes": []})

        for run in (self.before_run, self.action_run, self.after_run):
            write(run / "build-result.json", {"hashes": {"prepared.json": "x"}})
            write(run / "stdout.jsonl", "{}\n")
            write(run / "exit.json", {"executed": True, "exitCode": 0, "error": None,
                                      "startedUtc": "2026-09-27T16:12:00+00:00",
                                      "finishedUtc": "2026-09-27T16:12:10+00:00"})
            write(run / "prepared.json", {"launchable": True, "session": copy.deepcopy(SESSION)})

        review = write(self.attempt / "review.json", {
            "schemaVersion": 1, "operation": "level.reopen-current", "allowedCalls": 1,
            "levelId": LEVEL, "requestId": REQUEST_ID,
            "createdUtc": "2026-09-27T16:14:39+00:00", "expiresUtc": "2026-09-27T16:19:39+00:00",
            "session": copy.deepcopy(SESSION), "baselineRun": str(self.before_run),
            "baselineHashes": {}, "accountBackupManifest": str(account_before),
            "accountBaselineSha256": sha(account_before),
            "editorBaseline": {"path": str(self.editor_before), "sha256": sha(self.editor_before)},
            "observerBaseline": {"path": str(self.observer_before), "sha256": sha(self.observer_before)},
            "bridgeRunId": "e117c900-0956-4ec4-8930-9ba0a179eaed",
            "reopenLifecycle": {"bridgeRunId": "e117c900-0956-4ec4-8930-9ba0a179eaed",
                                "accountBaselineSha256": sha(account_before),
                                "acceptanceVerifierSha256": sha(verifier)}})
        self.review = review
        # Action prepared.json must be self-identifying.
        write(self.action_run / "prepared.json", {"launchable": True, "requestId": REQUEST_ID,
                                                  "reviewSha256": sha(review), "reviewPath": str(review),
                                                  "session": copy.deepcopy(SESSION)})

        claim = write(self.work / "reopen-claim.json", {
            "schema": 1, "action": "reopen-current", "requestId": REQUEST_ID, "levelId": LEVEL,
            "sessionPath": str(session), "sessionSha256": sha(session),
            "bridgeRunId": "e117c900-0956-4ec4-8930-9ba0a179eaed",
            "reviewSha256": sha(review), "accountBaselineSha256": sha(account_before),
            "acceptanceVerifierSha256": sha(verifier),
            "pinsDigest": "3b" * 32, "createdUtc": "2026-09-27T16:14:54+00:00"})
        self.claim = claim
        self.dispatch_doc = write(self.work / "reopen-dispatch.json", {
            "schema": 1, "requestId": REQUEST_ID, "leaseSha256": sha(claim),
            "nativeReceiptSha256": sha(self.action_run / "stdout.jsonl"),
            "preflightPassed": True, "nativeCallAttempted": True, "nativeCallReturned": True,
            "callExceptionCode": 0, "hookCleanupVerified": True,
            "status": "dispatch-returned-business-pending", "businessPending": True,
            "businessVerified": False, "reopenVerified": False, "retryAttempted": False})
        return self

    def edit(self, path, mutate):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        mutate(value)
        write(Path(path), value)
        return path

    def edit_review(self, mutate):
        """Edit the review and re-bind every place that pins its digest."""
        self.edit(self.review, mutate)
        digest = sha(self.review)
        self.edit(self.work / "reopen-claim.json", lambda v: v.update(reviewSha256=digest))
        self.edit(self.action_run / "prepared.json", lambda v: v.update(reviewSha256=digest))
        self.edit(self.work / "reopen-dispatch.json",
                  lambda v: v.update(leaseSha256=sha(self.work / "reopen-claim.json")))
        return self.review

    def args(self, **over):
        values = dict(work=self.work, review=self.review, before_run=self.before_run,
                      action_run=self.action_run, after_run=self.after_run,
                      before_ipc=self.ipc_before, after_editor=self.editor_after,
                      after_observer=self.observer_after, after_ipc=self.ipc_after,
                      after_account=self.account_after, editor_pid=9340)
        values.update(over)
        return values

    def assemble(self, **over):
        return assembler.assemble(**self.args(**over))


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="w13-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.box = Sandbox(self.tmp).build()
        self._saved = assembler.profiles.ROOT
        assembler.profiles.ROOT = self.box.root
        self.addCleanup(setattr, assembler.profiles, "ROOT", self._saved)

    def refusal(self, reason, **over):
        with self.assertRaisesRegex(ValueError, reason):
            self.box.assemble(**over)

    # --- happy path -----------------------------------------------------
    def test_happy_path_reuses_shape_with_new_identity(self):
        index, meta = self.box.assemble()
        self.assertEqual(set(index), {"schemaVersion", "requestId", "editorPid", "files", "runs"})
        self.assertEqual(index["requestId"], REQUEST_ID)
        self.assertEqual(set(index["files"]), set(assembler.FILES_ORDER))
        self.assertEqual(set(index["runs"]), {"before", "action", "after"})
        for entry in index["files"].values():
            self.assertEqual(set(entry), {"path", "sha256"})
            self.assertEqual(sha(entry["path"]), entry["sha256"])
        for run in index["runs"].values():
            self.assertEqual(set(run), {"path", "hashes"})
            self.assertEqual(set(run["hashes"]), set(assembler.RUN_FILES))
            for name, digest in run["hashes"].items():
                self.assertEqual(sha(Path(run["path"]) / name), digest)
        self.assertEqual(index["files"]["lease"]["sha256"], index["files"]["claim"]["sha256"])
        self.assertEqual(index["files"]["formalGil"]["path"], str(self.box.formal))
        self.assertEqual(index["files"]["formalGil"]["sha256"], sha(self.box.formal))
        self.assertTrue(meta["pending"])

    def test_emit_is_create_once_and_idempotent(self):
        index, meta = self.box.assemble()
        first = assembler.emit(self.box.work, index, meta)
        self.assertTrue(first["emitted"])
        self.assertEqual(first["inputsSha256"], sha(self.box.work / "reopen-inputs.json"))
        again = assembler.emit(self.box.work, index, meta)
        self.assertTrue(again["emitted"])
        # A different payload at the same request id is a conflict, not an overwrite.
        tampered = copy.deepcopy(index)
        tampered["editorPid"] = 1
        with self.assertRaisesRegex(ValueError, "IMMUTABLE_ARTIFACT_CONFLICT"):
            assembler.emit(self.box.work, tampered, meta)

    # --- missing-input counterexamples (缺件被拒) ------------------------
    def test_missing_lease_refused(self):
        (self.box.work / "reopen-claim.json").unlink()
        self.refusal("INPUT_MISSING:reopen-claim.json")

    def test_missing_dispatch_refused(self):
        (self.box.work / "reopen-dispatch.json").unlink()
        self.refusal("INPUT_MISSING:reopen-dispatch.json")

    def test_missing_session_refused(self):
        (self.box.attempt / "session.json").unlink()
        self.refusal("INPUT_MISSING:session.json")

    def test_missing_review_refused(self):
        (self.box.review).unlink()
        self.refusal("INPUT_MISSING:review.json")

    def test_missing_save_original_refused(self):
        (self.box.account_before).unlink()
        self.refusal("INPUT_MISSING:account-before.json")

    def test_missing_run_refused(self):
        (self.box.action_run / "exit.json").unlink()
        self.refusal("INPUT_MISSING:exit.json")

    def test_missing_after_evidence_refused(self):
        (self.box.ipc_after).unlink()
        self.refusal("INPUT_MISSING:ipc-after.json")

    def test_missing_formal_gil_refused(self):
        self.box.formal.unlink()
        self.refusal("SAVE_ORIGINAL_BINDING:formal_missing")

    # --- identity-drift counterexamples ---------------------------------
    def test_lease_placeholder_level_refused(self):
        # RE-POINTED 2026-10-08.  This used to set levelId=1 and expect "LEVEL_BINDING:lease",
        # which fired because the module demanded the ONE level 1073741840 -- a literal that
        # is a property of a single save load and had to be hand-edited whenever the save
        # changed.  The lane now takes the level FROM the lease and refuses only a level that
        # names nothing real, so the case that must be refused is the discovery placeholder.
        self.box.edit(self.box.claim, lambda v: v.update(levelId=0xFFFFFFFF))
        self.refusal("LEVEL_BINDING:lease_placeholder")

    def test_lease_replay_identity_refused(self):
        self.box.edit(self.box.claim, lambda v: v.update(requestId="f" * 32))
        self.refusal("LEASE_REPLAY_IDENTITY")

    def test_review_sha_drift_refused(self):
        self.box.edit(self.box.review, lambda v: v.update(allowedCalls=2))
        self.refusal("REVIEW_BINDING:reviewSha256")

    def test_session_sha_drift_refused(self):
        self.box.edit(self.box.attempt / "session.json", lambda v: v.update(pid=1))
        self.refusal("SESSION_BINDING:lease")

    def test_session_review_field_mismatch_refused(self):
        self.box.edit_review(lambda v: v["session"].update(pid=999))
        self.refusal("SESSION_BINDING:review:pid")

    def test_save_original_mismatch_refused(self):
        self.box.edit(self.box.attempt / "account-before.json",
                      lambda v: v.update(source=str(self.box.runtime)))
        self.refusal("SAVE_ORIGINAL_BINDING:before_account")

    def test_save_original_account_changed_refused(self):
        self.box.edit(self.box.attempt / "account-after.json",
                      lambda v: v["files"][0].update(sha256="a" * 64))
        self.refusal("SAVE_ORIGINAL_BINDING:account_changed")

    def test_verifier_source_drift_refused(self):
        write_raw(self.box.root / assembler.ACCEPTANCE_SOURCE, "# drifted\n")
        self.refusal("REVIEW_VERIFIER_SOURCE_CHANGED")

    def test_action_run_not_bound_to_review_refused(self):
        self.box.edit(self.box.action_run / "prepared.json", lambda v: v.update(reviewSha256="b" * 64))
        self.refusal("ACTION_BINDING:reviewSha256")

    def test_dispatch_receipt_mismatch_refused(self):
        self.box.edit(self.box.work / "reopen-dispatch.json",
                      lambda v: v.update(nativeReceiptSha256="c" * 64))
        self.refusal("DISPATCH_RAW_RECEIPT")

    def test_editor_pid_mismatch_refused(self):
        self.box.edit_review(lambda v: v.update(
            bridgeEvidence={"editorProcess": {"pid": 88, "creationFileTime": 66}}))
        self.refusal("EDITOR_PID_BINDING", editor_pid=1)

    def test_editor_pid_matching_bridge_process_accepted(self):
        self.box.edit_review(lambda v: v.update(
            bridgeEvidence={"editorProcess": {"pid": 88, "creationFileTime": 66}}))
        index, meta = self.box.assemble(editor_pid=88)
        self.assertEqual(index["editorPid"], 88)

    def test_active_claim_mismatch_refused(self):
        write(self.box.dispatch / "native-active.json", {"schema": 1})
        self.refusal("LEASE_ACTIVE_CLAIM_MISMATCH")

    # --- pending-only barrier ------------------------------------------
    def test_dispatch_already_verified_refused(self):
        for key in ("businessVerified", "reopenVerified", "retryAttempted"):
            with self.subTest(key=key):
                self.box.edit(self.box.work / "reopen-dispatch.json", lambda v, k=key: v.update({k: True}))
                self.refusal("DISPATCH_NOT_PENDING")
                self.box.edit(self.box.work / "reopen-dispatch.json", lambda v, k=key: v.update({k: False}))

    def test_dispatch_not_pending_flag_refused(self):
        self.box.edit(self.box.work / "reopen-dispatch.json", lambda v: v.update(businessPending=False))
        self.refusal("DISPATCH_NOT_PENDING")

    def test_output_never_claims_a_reopen(self):
        index, meta = self.box.assemble()
        self.assertNotIn("reopenVerified", index)
        self.assertNotIn("businessVerified", index)
        self.assertFalse(meta["reopenVerified"])
        self.assertFalse(meta["businessVerified"])
        self.assertFalse(meta["reopenInvoked"])
        self.assertTrue(meta["pending"])

    def test_work_path_outside_fixed_root_refused(self):
        stray = self.box.runtime / "elsewhere" / REQUEST_ID
        shutil.copytree(self.box.work, stray)
        self.refusal("REOPEN_FIXED_WORK_PATH", work=stray)


class ConsumerShapeTests(unittest.TestCase):
    """Prove the emitted index clears the real verifier's structural prelude."""

    STRUCTURAL = ("INDEX_SCHEMA", "INDEX_INPUT_SET", "ARTIFACT_REFERENCE", "ARTIFACT_HASH",
                  "EVIDENCE_OUTSIDE_RUNTIME", "LEASE_CLAIM_MISMATCH", "LEASE_IDENTITY",
                  "LEASE_SOURCE_BINDINGS", "LEASE_SESSION_PATH", "DISPATCH_BINDING")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="w13c-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.box = Sandbox(self.tmp).build()
        self._saved = assembler.profiles.ROOT
        assembler.profiles.ROOT = self.box.root
        self.addCleanup(setattr, assembler.profiles, "ROOT", self._saved)
        if REAL_ROOT is None:
            self.skipTest("no tools/game-executor/native_reopen_acceptance.py on any ancestor")
        try:
            sys.path.insert(0, str(REAL_ROOT / "tools/game-executor"))
            import native_reopen_acceptance as acceptance  # noqa: E402
        except Exception as exc:  # pragma: no cover - dependency probe
            self.skipTest("real verifier not importable offline: %r" % (exc,))
        self.acceptance = acceptance
        self._verifier_root = acceptance.ROOT
        acceptance.ROOT = self.box.root
        self.addCleanup(setattr, acceptance, "ROOT", self._verifier_root)

    def test_emitted_index_passes_structural_prelude(self):
        index, meta = self.box.assemble()
        result = self.acceptance.validate(index)
        reasons = list(result.get("reasons", []))
        # Business checks are expected to fail (the runs are synthetic); the point
        # is that no *structural* precondition the two consumers impose trips.
        offenders = [r for r in reasons if r.split(":")[0] in self.STRUCTURAL]
        self.assertEqual(offenders, [], f"structural reasons: {offenders} (all: {reasons})")
        self.assertFalse(result.get("reopenRoundtripVerified"))
        self.assertFalse(result.get("businessVerified"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
