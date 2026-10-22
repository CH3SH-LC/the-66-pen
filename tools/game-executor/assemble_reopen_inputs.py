"""Assemble the missing `<work>/reopen-inputs.json` index for one fixed reopen roundtrip.

The two downstream consumers already exist and neither one writes this file:

  * ``tools/game-executor/native_reopen_acceptance.py`` reads it as the one and
    only evidence index (``acceptance_candidate`` -> ``work / 'reopen-inputs.json'``).
  * ``tools/editor-bridge/reopen-lifecycle.ps1`` binds its sha256 through the
    acceptance artifact's ``inputsSha256`` and re-hashes the four proof files.

This module fills that gap. It reuses the *shape* of the historical artifacts
(``schemaVersion``/``requestId``/``editorPid``/``files``/``runs``) but never
reuses their identity: the request id, every path and every digest are derived
from the live lease, review and account evidence for the work directory that is
being assembled, and a stale/hand-copied index is refused by binding.

Design rules enforced here (fail closed, named reason, no partial output):

  * Five identities must all agree or the whole assembly is refused:
    session, level, review, lease, save-original.
  * The dispatch must still be in the *pending* state. A dispatch that already
    claims ``businessVerified``/``reopenVerified`` is refused rather than
    re-indexed, and this assembler never writes a verification boolean at all.
  * Output is create-once. An existing differing file is a conflict, never an
    overwrite, so a request id cannot silently change meaning.

It does not run the verifier, does not touch the game, the editor bridge or the
elevated queue, and never claims a reopen happened.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_profiles as profiles  # noqa: E402  (ROOT / require / sha256 only)


#: NO FIXED LEVEL (2026-10-08).  This module used to carry ``LEVEL = 1073741840`` and build
#: the formal-GIL path from it.  That literal is a property of ONE SAVE LOAD: it had to be
#: hand-edited whenever the save changed, and MEASURED 2026-10-08 it took the whole reopen
#: lane down (the open level was 1073741842, and every entry point refused it) -- a
#: capability that had worked on 2026-09-28.  The level is now the LEASE's own and every
#: other document must AGREE with it, so the checks compare two observations instead of
#: each document against a constant.
LEVEL_PLACEHOLDER = 0xFFFFFFFF


def formal_relative(level_id):
    """The formal GIL's path inside an account backup, for the level being reopened.

    Derived, never a module constant: the path is what ties a validated lease to the bytes
    on disk, so it has to follow the lease rather than a literal.
    """
    return f"Beyond_Local_Save_Level/{level_id}/{level_id}.gil"
NATIVE_DISPATCH = ".runtime/editor-bridge/native-dispatch"
ACCEPTANCE_SOURCE = "tools/game-executor/native_reopen_acceptance.py"
MAX_JSON = 32 * 1024 * 1024

FILES_ORDER = ("lease", "claim", "dispatch", "session", "review", "beforeEditor",
               "afterEditor", "beforeObserver", "afterObserver", "beforeIpc",
               "afterIpc", "beforeAccount", "afterAccount", "formalGil")
RUNS_ORDER = ("before", "action", "after")
RUN_FILES = ("prepared.json", "build-result.json", "stdout.jsonl", "exit.json")
LEASE_KEYS = {"schema", "action", "requestId", "levelId", "sessionPath", "sessionSha256",
              "bridgeRunId", "reviewSha256", "accountBaselineSha256",
              "acceptanceVerifierSha256", "pinsDigest", "createdUtc"}
DISPATCH_KEYS = {"schema", "requestId", "leaseSha256", "nativeReceiptSha256", "preflightPassed",
                 "nativeCallAttempted", "nativeCallReturned", "callExceptionCode",
                 "hookCleanupVerified", "status", "businessPending", "businessVerified",
                 "reopenVerified", "retryAttempted"}
POLICY_KEYS = {"bridgeRunId", "accountBaselineSha256", "acceptanceVerifierSha256"}
SESSION_FIELDS = ("schemaVersion", "pid", "tid", "window", "windowClass",
                  "processCreation", "threadCreation", "image")
DISPATCH_STATUS = {"dispatch-returned-business-pending", "dispatch-uncertain-business-pending",
                   "dispatch-refused-no-call"}
SHA256 = re.compile("[0-9a-f]{64}")
REQUEST_ID = re.compile("[0-9a-f]{32}")
GUID = re.compile("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SCOPE = "reopen-inputs-assembly-only"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_read(path):
    data = Path(path).read_bytes()
    require(0 < len(data) <= MAX_JSON, "REOPEN_JSON_SIZE")

    def pairs(rows):
        out = {}
        for key, value in rows:
            require(key not in out, "REOPEN_DUPLICATE_JSON_KEY:" + key)
            out[key] = value
        return out
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("REOPEN_NONFINITE_JSON")))


def canonical_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def reference(path, *, runtime=True):
    p = Path(path).resolve()
    require(p.is_file(), "INPUT_MISSING:" + p.name)
    if runtime:
        require(p.is_relative_to(profiles.ROOT / ".runtime"), "EVIDENCE_OUTSIDE_RUNTIME:" + p.name)
    return {"path": str(p), "sha256": sha(p)}


def run_reference(path):
    run = Path(path).resolve()
    require(run.is_dir(), "INPUT_MISSING:" + run.name)
    require(run.is_relative_to(profiles.ROOT / ".runtime"), "RUN_OUTSIDE_RUNTIME:" + run.name)
    hashes = {}
    for name in RUN_FILES:
        item = run / name
        require(item.is_file(), "INPUT_MISSING:" + name)
        hashes[name] = sha(item)
    return {"path": str(run), "hashes": hashes}


def check_lease(claim_path, request_id, dispatch_root):
    require(claim_path.is_file(), "INPUT_MISSING:reopen-claim.json")
    claim = json_read(claim_path)
    require(set(claim) == LEASE_KEYS, "LEASE_FIELDS")
    require(claim["schema"] == 1 and claim["action"] == "reopen-current", "LEASE_CONTRACT")
    require(claim["requestId"] == request_id, "LEASE_REPLAY_IDENTITY")
    require(claim["levelId"] != LEVEL_PLACEHOLDER, "LEVEL_BINDING:lease_placeholder")
    require(REQUEST_ID.fullmatch(str(claim["requestId"])) is not None, "LEASE_ID")
    require(GUID.fullmatch(str(claim["bridgeRunId"])) is not None, "LEASE_BRIDGE_RUN_ID")
    require(all(SHA256.fullmatch(str(claim[k])) is not None for k in
                ("sessionSha256", "reviewSha256", "accountBaselineSha256",
                 "acceptanceVerifierSha256", "pinsDigest")), "LEASE_HASH")
    require(Path(claim["sessionPath"]).is_absolute(), "LEASE_SESSION_PATH")
    active = dispatch_root / "native-active.json"
    if active.exists():
        require(active.read_bytes() == claim_path.read_bytes(), "LEASE_ACTIVE_CLAIM_MISMATCH")
    return claim


def check_dispatch(dispatch_path, request_id, lease_sha256):
    require(dispatch_path.is_file(), "INPUT_MISSING:reopen-dispatch.json")
    dispatch = json_read(dispatch_path)
    require(set(dispatch) == DISPATCH_KEYS, "DISPATCH_FIELDS")
    require(dispatch["schema"] == 1 and dispatch["requestId"] == request_id, "DISPATCH_BINDING")
    require(dispatch["leaseSha256"] == lease_sha256, "DISPATCH_LEASE_BINDING")
    require(SHA256.fullmatch(str(dispatch["nativeReceiptSha256"])) is not None, "DISPATCH_RECEIPT_HASH")
    for key in ("preflightPassed", "nativeCallAttempted", "nativeCallReturned",
                "hookCleanupVerified", "businessPending", "businessVerified",
                "reopenVerified", "retryAttempted"):
        require(type(dispatch[key]) is bool, "DISPATCH_BOOLEAN:" + key)
    # Pending-only barrier: this assembler refuses already-adjudicated dispatches
    # and never writes a success boolean of its own.
    require(dispatch["businessPending"] is True, "DISPATCH_NOT_PENDING")
    require(dispatch["businessVerified"] is False, "DISPATCH_NOT_PENDING:businessVerified")
    require(dispatch["reopenVerified"] is False, "DISPATCH_NOT_PENDING:reopenVerified")
    require(dispatch["retryAttempted"] is False, "DISPATCH_NOT_PENDING:retryAttempted")
    require(dispatch["status"] in DISPATCH_STATUS, "DISPATCH_STATUS")
    require(type(dispatch["callExceptionCode"]) is int, "DISPATCH_EXCEPTION_CODE")
    if dispatch["nativeCallReturned"]:
        require(dispatch["nativeCallAttempted"] and dispatch["callExceptionCode"] == 0,
                "DISPATCH_RETURN_INVALID")
    if dispatch["nativeCallAttempted"]:
        require(dispatch["preflightPassed"], "DISPATCH_CALL_INVALID")
    return dispatch


def check_review(review_ref, claim):
    review_path = Path(review_ref["path"])
    require(sha(review_path) == claim["reviewSha256"], "REVIEW_BINDING:reviewSha256")
    review = json_read(review_path)
    require(review.get("schemaVersion") == 1 and review.get("operation") == "level.reopen-current",
            "REVIEW_CONTRACT")
    require(review.get("allowedCalls") == 1, "REVIEW_ALLOWED_CALLS")
    # Two DOCUMENTS must agree: the review the helper will act on and the lease it was
    # issued for.  This is a stronger statement than "each equals 1073741840" -- it holds
    # for any level, so it survives the next save change.
    require(review.get("levelId") == claim["levelId"], "LEVEL_BINDING:review")
    require(review.get("requestId") == claim["requestId"], "REVIEW_BINDING:requestId")
    require(review.get("bridgeRunId") == claim["bridgeRunId"], "REVIEW_BINDING:bridgeRunId")
    require(SHA256.fullmatch(str(review.get("accountBaselineSha256", ""))) is not None,
            "REVIEW_BINDING:accountBaselineSha256")
    require(review["accountBaselineSha256"] == claim["accountBaselineSha256"],
            "SAVE_ORIGINAL_BINDING:claim_review")
    policy = review.get("reopenLifecycle")
    require(type(policy) is dict and set(policy) == POLICY_KEYS, "REVIEW_POLICY_FIELDS")
    require(policy["bridgeRunId"] == claim["bridgeRunId"], "REVIEW_POLICY_BRIDGE")
    require(policy["accountBaselineSha256"] == claim["accountBaselineSha256"],
            "SAVE_ORIGINAL_BINDING:policy")
    verifier = (profiles.ROOT / ACCEPTANCE_SOURCE).resolve()
    require(verifier.is_file() and sha(verifier) == claim["acceptanceVerifierSha256"],
            "REVIEW_VERIFIER_SOURCE_CHANGED")
    require(policy["acceptanceVerifierSha256"] == claim["acceptanceVerifierSha256"],
            "REVIEW_POLICY_VERIFIER")
    for key in ("editorBaseline", "observerBaseline"):
        value = review.get(key)
        require(type(value) is dict and set(value) == {"path", "sha256"}, "REVIEW_BASELINE_REF:" + key)
    return review


def check_session(session_ref, claim, review, runs):
    session_path = Path(claim["sessionPath"]).resolve()
    require(session_path.is_file(), "INPUT_MISSING:session.json")
    require(Path(session_ref["path"]) == session_path, "REVIEW_SESSION_PATH")
    require(sha(session_path) == claim["sessionSha256"], "SESSION_BINDING:lease")
    session = json_read(session_path)
    require(session.get("schemaVersion") == 1, "SESSION_SCHEMA")
    for key in SESSION_FIELDS:
        require(review["session"].get(key) == session.get(key), "SESSION_BINDING:review:" + key)
    for name, path in runs.items():
        prepared = json_read(Path(path) / "prepared.json")
        for key in SESSION_FIELDS:
            require(prepared.get("session", {}).get(key) == session.get(key),
                    f"SESSION_BINDING:run-{name}:" + key)
    return session


def check_save_original(before_account_ref, review, level_id):
    manifest_path = Path(before_account_ref["path"])
    require(Path(review["accountBackupManifest"]).resolve() == manifest_path,
            "SAVE_ORIGINAL_BINDING:manifest_path")
    manifest = json_read(manifest_path)
    require(manifest.get("createdUtc") is not None, "SAVE_ORIGINAL_BINDING:createdUtc")
    backup = Path(manifest["backup"]).resolve()
    require(backup.is_dir() and backup.is_relative_to(profiles.ROOT / ".runtime"),
            "SAVE_ORIGINAL_BINDING:backup_root")
    rows = {}
    for row in manifest["files"]:
        rel = row["relativePath"]
        require("\\" not in rel and ".." not in Path(rel).parts and rel.casefold() not in rows,
                "SAVE_ORIGINAL_BINDING:path")
        item = (backup / rel).resolve()
        require(item.is_relative_to(backup) and item.is_file() and sha(item) == row["sha256"],
                "SAVE_ORIGINAL_BINDING:file:" + rel)
        rows[rel.casefold()] = row["sha256"]
    actual = {p.relative_to(backup).as_posix().casefold() for p in backup.rglob("*") if p.is_file()}
    require(actual == set(rows), "SAVE_ORIGINAL_BINDING:enumeration")
    rel = formal_relative(level_id)
    require(rel.casefold() in rows, "SAVE_ORIGINAL_BINDING:formal_gil")
    source = Path(manifest["source"]).resolve()
    formal = (source / rel).resolve()
    require(formal.is_file(), "SAVE_ORIGINAL_BINDING:formal_missing")
    require(sha(formal) == rows[rel.casefold()], "SAVE_ORIGINAL_BINDING:formal_changed")
    return manifest, formal, rows


def workspace(work):
    path = Path(work).resolve()
    root = (profiles.ROOT / NATIVE_DISPATCH).resolve()
    require(path.parent == root and REQUEST_ID.fullmatch(path.name) is not None,
            "REOPEN_FIXED_WORK_PATH")
    require(path.is_dir(), "INPUT_MISSING:work")
    return path


def assemble(work, *, review, before_run, action_run, after_run, before_ipc,
             after_editor, after_observer, after_ipc, after_account, editor_pid):
    """Return the canonical index and the evidence digests it was built from."""
    work = workspace(work)
    request_id = work.name
    claim_path = work / "reopen-claim.json"
    dispatch_path = work / "reopen-dispatch.json"
    claim = check_lease(claim_path, request_id, work.parent)
    # The lease is the authority for WHICH level this round reopens; everything else is
    # checked against it rather than against a constant.
    level_id = claim["levelId"]
    lease_sha = sha(claim_path)
    dispatch = check_dispatch(dispatch_path, request_id, lease_sha)
    review_ref = reference(review)
    review_doc = check_review(review_ref, claim)
    runs = {"before": Path(before_run).resolve(), "action": Path(action_run).resolve(),
            "after": Path(after_run).resolve()}
    for name, path in runs.items():
        require(path.is_dir(), f"INPUT_MISSING:run-{name}")
        for raw in RUN_FILES:
            require((path / raw).is_file(), "INPUT_MISSING:" + raw)
    require(runs["before"] == Path(review_doc["baselineRun"]).resolve(),
            "REVIEW_BINDING:baselineRun")
    action_prepared = json_read(runs["action"] / "prepared.json")
    require(action_prepared.get("requestId") == request_id, "ACTION_BINDING:requestId")
    require(action_prepared.get("reviewSha256") == claim["reviewSha256"], "ACTION_BINDING:reviewSha256")
    require(Path(action_prepared["reviewPath"]).resolve() == Path(review_ref["path"]),
            "ACTION_BINDING:reviewPath")
    require(sha(runs["action"] / "stdout.jsonl") == dispatch["nativeReceiptSha256"],
            "DISPATCH_RAW_RECEIPT")
    for name, path in runs.items():
        exit_record = json_read(path / "exit.json")
        require(exit_record.get("executed") is True and exit_record.get("exitCode") == 0
                and exit_record.get("error") is None, f"RUN_EXECUTION_FAILED:{name}")
    check_session(reference(claim["sessionPath"]), claim, review_doc, runs)
    before_account_ref = reference(review_doc["accountBackupManifest"])
    require(before_account_ref["sha256"] == claim["accountBaselineSha256"],
            "SAVE_ORIGINAL_BINDING:before_account")
    manifest, formal, before_rows = check_save_original(before_account_ref, review_doc, level_id)
    # The after manifest is a separate capture of the same account. Both the
    # save-original backup and the after capture must enumerate the identical
    # file set and digests, and both must agree with the live formal GIL.
    after_account_ref = reference(after_account)
    after_manifest = json_read(Path(after_account_ref["path"]))
    require(type(after_manifest.get("files")) is list, "SAVE_ORIGINAL_BINDING:after_files")
    after_rows = {}
    for row in after_manifest["files"]:
        rel = row["relativePath"]
        require(rel.casefold() not in after_rows, "SAVE_ORIGINAL_BINDING:after_duplicate")
        after_rows[rel.casefold()] = row["sha256"]
    require(after_rows == before_rows, "SAVE_ORIGINAL_BINDING:account_changed")
    require(sha(formal) == after_rows[formal_relative(level_id).casefold()],
            "SAVE_ORIGINAL_BINDING:after_formal")
    require(type(editor_pid) is int and editor_pid > 0, "EDITOR_PID")
    bridge_process = (review_doc.get("bridgeEvidence") or {}).get("editorProcess") or {}
    if type(bridge_process.get("pid")) is int:
        require(bridge_process["pid"] == editor_pid, "EDITOR_PID_BINDING")

    refs = {
        "lease": {"path": str(claim_path), "sha256": lease_sha},
        "claim": {"path": str(claim_path), "sha256": lease_sha},
        "dispatch": {"path": str(dispatch_path), "sha256": sha(dispatch_path)},
        "session": reference(claim["sessionPath"]),
        "review": review_ref,
        "beforeEditor": reference(review_doc["editorBaseline"]["path"]),
        "afterEditor": reference(after_editor),
        "beforeObserver": reference(review_doc["observerBaseline"]["path"]),
        "afterObserver": reference(after_observer),
        "beforeIpc": reference(before_ipc),
        "afterIpc": reference(after_ipc),
        "beforeAccount": before_account_ref,
        "afterAccount": after_account_ref,
        "formalGil": {"path": str(formal), "sha256": sha(formal)},
    }
    require(review_doc["editorBaseline"]["sha256"] == refs["beforeEditor"]["sha256"],
            "REVIEW_BINDING:editorBaseline")
    require(review_doc["observerBaseline"]["sha256"] == refs["beforeObserver"]["sha256"],
            "REVIEW_BINDING:observerBaseline")
    require(set(refs) == set(FILES_ORDER), "ASSEMBLER_FILE_SET")
    index = {
        "schemaVersion": 1,
        "requestId": request_id,
        "editorPid": editor_pid,
        "files": {name: refs[name] for name in FILES_ORDER},
        "runs": {name: run_reference(runs[name]) for name in RUNS_ORDER},
    }
    require(set(index) == {"schemaVersion", "requestId", "editorPid", "files", "runs"},
            "ASSEMBLER_INDEX_SHAPE")
    meta = {"ok": True, "schemaVersion": 1, "scope": SCOPE, "requestId": request_id,
            "levelId": level_id, "work": str(work), "inputsSha256": None,
            "reopenInvoked": False, "reopenVerified": False, "businessVerified": False,
            "pending": True, "retryAttempted": False,
            "limits": "This is the verifier's input index only. It is not evidence that a "
                      "reopen happened and it authorises no release."}
    return index, meta


def emit(work, index, meta):
    work = workspace(work)
    target = work / "reopen-inputs.json"
    payload = canonical_bytes(index)
    if target.exists():
        require(target.read_bytes() == payload, "REOPEN_IMMUTABLE_ARTIFACT_CONFLICT:reopen-inputs.json")
    else:
        with target.open("xb") as stream:
            stream.write(payload)
            stream.flush()
    result = dict(meta, inputsSha256=sha(target), emitted=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--before-run", required=True)
    parser.add_argument("--action-run", required=True)
    parser.add_argument("--after-run", required=True)
    parser.add_argument("--before-ipc", required=True)
    parser.add_argument("--after-editor", required=True)
    parser.add_argument("--after-observer", required=True)
    parser.add_argument("--after-ipc", required=True)
    parser.add_argument("--after-account", required=True)
    parser.add_argument("--editor-pid", required=True, type=int)
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args(argv)
    try:
        index, meta = assemble(args.work, review=args.review, before_run=args.before_run,
                               action_run=args.action_run, after_run=args.after_run,
                               before_ipc=args.before_ipc, after_editor=args.after_editor,
                               after_observer=args.after_observer, after_ipc=args.after_ipc,
                               after_account=args.after_account, editor_pid=args.editor_pid)
        if args.emit:
            result = emit(args.work, index, meta)
        else:
            result = dict(meta, emitted=False,
                          inputsSha256=hashlib.sha256(canonical_bytes(index)).hexdigest())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        print(json.dumps(dict(ok=False, error=str(exc), scope=SCOPE, emitted=False,
                              reopenInvoked=False, businessVerified=False,
                              reopenVerified=False, pending=True), ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
