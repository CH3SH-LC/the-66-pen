"""Compact secure-expectation predicates, shared by the test suite and the mutation
matrix.  Each probe returns True when the PRODUCTION protection holds; the mutation
matrix asserts that the corresponding mutation flips it to False.

No probe dispatches: the route probes go through ``harness.DispatchSentinel``.
"""
from __future__ import annotations

import shutil

import threading
import time
import uuid

import harness as H


# --------------------------------------------------------------------------- #
# manifest builders (all rooted in the real round materials)
# --------------------------------------------------------------------------- #

def _m(**overrides):
    manifest = H.base_manifest()
    for key, value in overrides.items():
        manifest[key] = value
    return manifest


def owned_ids(legs_module, manifest):
    report = legs_module.judge(manifest)
    return report, set(report.get("ownedIds") or [])


def _one_receipt_manifest(entity_id=None, level=None, template=None, entry_overrides=None):
    """A manifest with exactly ONE receipt taken from the real index."""
    manifest = H.base_manifest()
    entry = dict(manifest["receipts"][0])
    if entity_id is not None:
        entry["entityId"] = entity_id
    if level is not None:
        entry["levelId"] = level
    if template is not None:
        entry["templateId"] = template
    entry.update(entry_overrides or {})
    manifest["receipts"] = [entry]
    manifest["roundRequestIds"] = [entry["requestId"]]
    manifest["candidates"] = [entry["entityId"]]
    return manifest


def _bad_exit_readback():
    """A copy of the real complete read-back whose sibling exit.json says exitCode 1."""
    source = H.manifest_paths()["freshReadback"]
    target = H.HERE / "fixtures" / "readback-bad-exit"
    target.mkdir(parents=True, exist_ok=True)
    document = H.read_json(source)
    H.write_json(target / "before-context.json", document)
    H.write_json(target / "exit.json", {"startedUtc": "2026-10-02T09:00:37.8870273Z",
                                        "executed": True, "exitCode": 1,
                                        "error": "stub refusal"})
    return str(target / "before-context.json")


# --------------------------------------------------------------------------- #
# Legs-module probes
# --------------------------------------------------------------------------- #

def p_frozen(legs):
    """(a) 1077936129/130/131 are refused even when asked for by name."""
    report, owned = owned_ids(legs, _m(candidates=list(H.FROZEN)))
    return owned == set() and all(
        report["perId"]["%d:%d" % (H.LEVEL, i)]["state"] == "refused" for i in H.FROZEN)


def p_frozen_with_receipt(legs):
    """(a/G) a frozen id that satisfies EVERY other leg is still refused by leg G.

    Built because in the real round leg B already refuses the frozen ids (they sit in the
    pre-create baseline), so leg G is otherwise unreachable and un-mutation-provable.
    """
    entry = dict(H.base_manifest()["receipts"][0])
    mutated = H.write_extra_receipt(
        "frozen-129-receipt.json", entry["path"],
        lambda body: body["backend"].update({"entityId": 1077936129}))
    baseline = H.write_baseline_with_extra([])
    document = H.read_json(baseline)
    document = dict(document, entities=[e for e in document["entities"]
                                        if e.get("id") != 1077936129])
    H.write_json(baseline, document)
    manifest = _one_receipt_manifest(
        entity_id=1077936129, level=H.LEVEL, template=20001034,
        entry_overrides={"path": mutated["path"],
                         "recordedSha256": mutated["recordedSha256"]})
    manifest["preBaseline"] = {"path": str(baseline)}
    report, owned = owned_ids(legs, manifest)
    row = report["perId"]["%d:%d" % (H.LEVEL, 1077936129)]
    return owned == set() and row["subState"] == "CLEANUP_TARGET_UNATTRIBUTABLE"


def p_pre_baseline_member(legs):
    """(b) an id that already existed before the round is refused."""
    baseline = H.write_baseline_with_extra([1077936138])
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["preBaseline"] = {"path": str(baseline)}
    _report, owned = owned_ids(legs, manifest)
    return owned == set()


def p_pre_baseline_absent(legs):
    """(c) no baseline at all -> run refused."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest.pop("preBaseline")
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_pre_baseline_missing_file(legs):
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["preBaseline"] = {"path": str(H.HERE / "fixtures" / "no-such-baseline.json")}
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_pre_baseline_empty_inline(legs):
    """(c') an EMPTY inline baseline must not be usable as 'what existed before'."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["preBaseline"] = {"ids": []}
    _report, owned = owned_ids(legs, manifest)
    return owned == set()


def p_pre_baseline_undeclared_extra(legs):
    """(c'') the manifest declares a baseline sha256; a swapped file must be refused.

    The declared hash is present in the real materials (``preBaseline.sha256``) and is
    never read by the judge.
    """
    baseline = H.write_baseline_with_extra([1077936138])
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["preBaseline"] = {"path": str(baseline),
                               "sha256": "0" * 64, "shape": "native-before-context",
                               "entityCount": 999}
    _report, owned = owned_ids(legs, manifest)
    return owned == set()


def p_readback_absent(legs):
    """(d) no readback -> run refused."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest.pop("freshReadback")
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_readback_truncated(legs):
    """(d) a readback that claims fewer entities than it carries -> refused."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["freshReadback"] = dict(manifest["freshReadback"], entityCount=70)
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_readback_incomplete(legs):
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["freshReadback"] = dict(manifest["freshReadback"], complete=False)
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_readback_unaccepted(legs):
    """(d) a readback its own run record refused is not a statement of what is present."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["freshReadback"] = dict(manifest["freshReadback"], path=_bad_exit_readback())
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_readback_level_mismatch(legs):
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["freshReadback"] = dict(manifest["freshReadback"], levelId=H.OTHER_LEVEL)
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_readback_stale(legs):
    """(g) a readback dated before the round window is not 'the level as it is now'."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["window"] = {"roundId": "stale", "startUtc": "2026-10-02T10:00:00Z",
                          "stopUtc": "2026-10-02T11:00:00Z"}
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_receipt_outside_window(legs):
    """(g) a receipt dated outside the round window is not this round's create.

    The window is chosen to CONTAIN the read-back (09:00:37Z) and EXCLUDE the receipt
    (2026-09-30T02:12:18Z), so the only refusal at play is leg E -- not a stale read-back.
    """
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["window"] = {"roundId": "narrow", "startUtc": "2026-10-02T09:00:00Z",
                          "stopUtc": "2026-10-02T09:01:00Z"}
    report, owned = owned_ids(legs, manifest)
    row = report["perId"]["%d:%d" % (H.LEVEL, 1077936138)]
    return owned == set() and report["status"] == "judged" \
        and row["subState"] == "RECEIPT_OUTSIDE_ROUND_WINDOW"


def p_window_invalid(legs):
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["window"] = {"roundId": "bad", "startUtc": "2026-10-02T09:00:00Z",
                          "stopUtc": "2026-10-01T09:00:00Z"}
    report, owned = owned_ids(legs, manifest)
    return owned == set() and report["status"] == "refused"


def p_cross_level(legs):
    """(f) the same ids created in ANOTHER level are not this round's."""
    manifest = _m(candidates=H.real_receipt_ids(H.base_manifest()))
    manifest["levelId"] = H.OTHER_LEVEL
    manifest["freshReadback"] = dict(manifest["freshReadback"], levelId=H.OTHER_LEVEL)
    _report, owned = owned_ids(legs, manifest)
    return owned == set()


def p_cross_level_dual_id(legs):
    """(f) 1077936135 carries a REAL create receipt -- for the OTHER level.

    The receipt body is mutated so its own backend.levelId agrees with the index (no
    body-mismatch shortcut), so the only leg that can refuse it is the level comparison.
    """
    entry = H.base_manifest()["receipts"][0]
    mutated = H.write_extra_receipt(
        "dual-level-1077936135.json", entry["path"],
        lambda body: body["backend"].update({"entityId": H.DUAL_LEVEL_ID,
                                             "levelId": H.OTHER_LEVEL}))
    manifest = _one_receipt_manifest(
        entity_id=H.DUAL_LEVEL_ID, level=H.OTHER_LEVEL, template=20001002,
        entry_overrides={"path": mutated["path"],
                         "recordedSha256": mutated["recordedSha256"]})
    report, owned = owned_ids(legs, manifest)
    row = report["perId"]["%d:%d" % (H.LEVEL, H.DUAL_LEVEL_ID)]
    return owned == set() and row["subState"] == "LEVEL_MISMATCH"


def p_receipt_tampered(legs):
    """(F) a receipt whose bytes no longer hash to the recorded value is refused."""
    entry = dict(H.base_manifest()["receipts"][0])
    mutated = H.write_extra_receipt("tampered-receipt.json", entry["path"],
                                    lambda body: body.update({"injected": True}))
    manifest = _one_receipt_manifest(entity_id=entry["entityId"])
    manifest["receipts"] = [dict(entry, path=mutated["path"],
                                 recordedSha256=entry["recordedSha256"])]
    report, owned = owned_ids(legs, manifest)
    row = report["perId"]["%d:%d" % (H.LEVEL, entry["entityId"])]
    return owned == set() and row["subState"] == "RECEIPT_TAMPERED"


def p_receipt_not_a_create(legs):
    """(A) a snapshot re-labelled as this round's receipt is refused.

    The mutated file's hash is recorded as the round's, so leg F PASSES and the only leg
    that can refuse the id is the create-declaration check.
    """
    entry = dict(H.base_manifest()["receipts"][0])
    mutated = H.write_extra_receipt(
        "not-a-create.json", entry["path"],
        lambda body: body["backend"].update({"action": "inspect"}))
    manifest = _one_receipt_manifest(entity_id=entry["entityId"])
    manifest["receipts"] = [dict(entry, path=mutated["path"],
                                 recordedSha256=mutated["recordedSha256"])]
    report, owned = owned_ids(legs, manifest)
    row = report["perId"]["%d:%d" % (H.LEVEL, entry["entityId"])]
    return owned == set() and row["subState"] == "RECEIPT_NOT_A_CREATE"


def p_readback_hash_verified(legs):
    """(D) the manifest declares the read-back's sha256; a mismatch must be refused."""
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["freshReadback"] = dict(manifest["freshReadback"], sha256="0" * 64)
    _report, owned = owned_ids(legs, manifest)
    return owned == set()


def p_readback_time_bound_to_artifact(legs):
    """(D) the declared read time must not contradict the read-back's own run record.

    The artifact's sibling exit.json says 2026-10-02T09:00:37.8870273Z.  The manifest
    declares 2026-09-30T02:12:20Z -- still inside the window and after the receipt, so
    every current leg passes.  A read time that is merely ASSERTED (and silently wins over
    the artifact's own record) is not the "当前完整读回" the discipline asks for.
    """
    manifest = _one_receipt_manifest(entity_id=1077936138)
    manifest["freshReadback"] = dict(manifest["freshReadback"],
                                     readAtUtc="2026-09-30T02:12:20Z")
    _report, owned = owned_ids(legs, manifest)
    return owned == set()


def p_legit(legs):
    """(h) the real round's 51 real creates are owned; the 3 frozen ids are not."""
    manifest = _m(candidates=H.real_receipt_ids(H.base_manifest()) + list(H.FROZEN))
    report, owned = owned_ids(legs, manifest)
    frozen_ok = all(report["perId"]["%d:%d" % (H.LEVEL, i)]["state"] == "refused"
                    for i in H.FROZEN)
    return owned == set(H.real_receipt_ids(H.base_manifest())) and frozen_ok \
        and report["dispatchPerformed"] is False and report["deletionPerformed"] is False


# --------------------------------------------------------------------------- #
# Route probes (production tool function, stubbed transport)
# --------------------------------------------------------------------------- #

def _route(server, sentinel, entity_ids, request_ids, run_id="stub-run", dry_run=True,
           cleanup_request_id='auto'):
    """One stubbed route call.

    ``cleanup_request_id`` defaults to a FRESH name per call.  The route's journal is now
    per request, so two probes that happen to share a round and a command would otherwise
    interfere across probe runs in one process (the second would legitimately replay and
    report zero dispatches, which is a fact about the journal, not about the guard under
    test).  A probe that MEANS to repeat a request passes the same name twice; a probe
    that means to exercise the unnamed path passes ``None``.
    """
    manifest = _m(candidates=sorted(entity_ids))
    H.install_route_evidence(server, request_ids, manifest)
    sentinel.bind(server)
    if cleanup_request_id == 'auto':
        cleanup_request_id = 'auto-' + uuid.uuid4().hex[:12]
    return server.mw_scene_cleanup_owned("handle-1", list(entity_ids), list(request_ids),
                                         run_id, dryRun=dry_run,
                                         cleanupRequestId=cleanup_request_id)


def _route_no_dispatch(server, sentinel, entity_ids, request_ids, **kwargs):
    result = _route(server, sentinel, entity_ids, request_ids, **kwargs)
    return (not sentinel.dispatched()) and H.tool_error(result) is not None


def p_route_frozen_no_dispatch(server, sentinel):
    manifest = H.base_manifest()
    return _route_no_dispatch(server, sentinel, list(H.FROZEN), manifest["roundRequestIds"])


def p_route_unowned_no_dispatch(server, sentinel):
    manifest = H.base_manifest()
    return _route_no_dispatch(server, sentinel, [1077936138, 1077999999],
                              manifest["roundRequestIds"])


def p_route_run_refused_no_dispatch(server, sentinel):
    """A run whose read-back is unusable must refuse the WHOLE round before the queue."""
    manifest = H.base_manifest()
    manifest["freshReadback"] = dict(manifest["freshReadback"], entityCount=70)
    H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    sentinel.bind(server)
    result = server.mw_scene_cleanup_owned("handle-1", H.real_receipt_ids(manifest),
                                           manifest["roundRequestIds"], "stub-run")
    error = H.tool_error(result) or {}
    return (not sentinel.dispatched()
            and error.get("code") == "CLEANUP_OWNERSHIP_UNDECIDABLE")


def p_route_no_materials_no_dispatch(server, sentinel):
    sentinel.bind(server)
    server.EVIDENCE_ROOT = H.HERE / "fixtures" / "definitely-empty"
    result = server.mw_scene_cleanup_owned("handle-1", [1077936138], ["req-1"], "stub-run")
    return (not sentinel.dispatched()) and \
        (H.tool_error(result) or {}).get("code") == "CLEANUP_ROUND_MATERIALS_UNAVAILABLE"


def p_route_unknown_bridge_no_dispatch(server, sentinel):
    manifest = H.base_manifest()
    sentinel.bind(server, known_runs=("some-other-run",))
    H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    result = server.mw_scene_cleanup_owned(
        "handle-1", H.real_receipt_ids(manifest), manifest["roundRequestIds"], "made-up-run")
    return (not sentinel.dispatched()) and \
        (H.tool_error(result) or {}).get("code") == "CLEANUP_BRIDGE_RUN_UNKNOWN"


def p_route_shape_invalid_run_id(server, sentinel):
    """A non-existent/absent bridge run id never reaches the delete dispatch."""
    manifest = H.base_manifest()
    sentinel.bind(server, known_runs=())
    H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    out = []
    for bad in ("", "not-a-32-hex", "../../etc/passwd", "z" * 32):
        result = server.mw_scene_cleanup_owned(
            "handle-1", H.real_receipt_ids(manifest), manifest["roundRequestIds"], bad)
        out.append((H.tool_error(result) or {}).get("code"))
    return all(code in ("CLEANUP_BRIDGE_RUN_REQUIRED", "CLEANUP_BRIDGE_RUN_UNKNOWN")
               for code in out) and not sentinel.dispatched()


def p_route_round_selector_unvalidated_no_dispatch(server, sentinel):
    """(new) The round selector must be validated by NAME before it is hashed.

    ``createdByRequestIds`` is the round selector and was the one argument this route never
    checked: it went straight into ``_cleanup_round_id``. The sibling route refuses the same
    shapes by name (CLEANUP_RESIDUE_ROUND_IDS_INVALID). None of these reaches a dispatch.
    """
    manifest = H.base_manifest()
    sentinel.bind(server)
    codes = []
    for bad in ([], "not-a-list", [""], [None], [12345]):
        result = server.mw_scene_cleanup_owned("handle-1", [1077936138], bad, "stub-run")
        codes.append((H.tool_error(result) or {}).get("code"))
    return all(code == "CLEANUP_ROUND_IDS_INVALID" for code in codes) \
        and not sentinel.dispatched()


def p_route_overlapping_unknown_outcome_no_dispatch(server, sentinel):
    """(new) An id attempted by an EARLIER request with no outcome must not be re-sent.

    The journal is scoped to one (roundId, cleanupRequestId), and a different id set is a
    different request by design. Together that let an id whose dispatch was attempted and
    never resolved be re-cited in a smaller batch and sent to the native delete twice --
    against this route's own rule that an unobserved write is never re-sent.

    This probe plants one such earlier request (claim, no result, dryRun false, one id of
    this round) and then calls the route with a DIFFERENT cleanupRequestId whose id set
    includes that id. Asserted: refused by name, nothing dispatched.

    The planted claim is REMOVED again before returning. ``_ROUTE_EVIDENCE_ROOT`` is a
    single root shared by every probe in one run (deliberately -- the re-entry probe calls
    the route twice and needs both calls to find the same record), so a claim left behind
    here would block the next probe that dispatches the same id. Measured 2026-10-06: it
    did, and ``test_the_transport_stub_is_the_only_thing_that_ran`` went red.
    """
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    materials = H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    round_dir = materials.parent
    journal_root = round_dir / "dispatch-journal"
    try:
        journal = journal_root / "earlier-request"
        journal.mkdir(parents=True, exist_ok=True)
        H.write_json(journal / "claim.json", {
            "kind": "cleanup-dispatch-claim", "schemaVersion": 1,
            "requestId": "earlier-request", "roundId": round_dir.name,
            "levelId": H.LEVEL, "outcomeKnown": False,
            "claimedAtUtc": "2026-10-02T00:00:00Z",
            "command": {"ids": sorted(ids)[:1], "dryRun": False, "bridgeRunId": "stub-run"},
        })
        sentinel.bind(server)
        # a DIFFERENT request id, and an id set that overlaps the earlier one
        result = server.mw_scene_cleanup_owned(
            "handle-1", ids, manifest["roundRequestIds"], "stub-run",
            cleanupRequestId="a-fresh-request")
        code = (H.tool_error(result) or {}).get("code")
        return (not sentinel.dispatched()) and \
            code == "CLEANUP_ID_OUTCOME_UNKNOWN_FROM_EARLIER_REQUEST"
    finally:
        shutil.rmtree(journal_root, ignore_errors=True)


def p_route_material_path_outside_runtime_no_dispatch(server, sentinel):
    """(new) A materials document naming a path outside .runtime must be refused.

    The legs resolve a material path with ``path if path.is_absolute() else (ROOT / path)``
    and contain it nowhere, so an uncontained path makes an arbitrary file into "what is
    present now" or "what existed before" -- the two inputs ownership is decided from. The
    independent service refuses this (MATERIAL_PATH_NOT_ALLOWED); the entry did not.

    The file below lives in this suite's own fixtures tree, which is inside the repository
    but OUTSIDE .runtime -- i.e. exactly the shape the boundary exists to reject.
    """
    manifest = H.base_manifest()
    outside = H.write_json(H.HERE / "fixtures" / "outside-runtime-baseline.json",
                           {"entities": []})
    manifest["preBaseline"] = {"path": str(outside)}
    H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    sentinel.bind(server)
    result = server.mw_scene_cleanup_owned("handle-1", H.real_receipt_ids(manifest),
                                           manifest["roundRequestIds"], "stub-run")
    return (not sentinel.dispatched()) and \
        (H.tool_error(result) or {}).get("code") == "CLEANUP_MATERIAL_PATH_NOT_ALLOWED"


def p_route_materials_wrong_level_no_dispatch(server, sentinel):
    """(new) The round's ownership evidence was written for ANOTHER level than the handle.

    Why this case exists: entity ids are reused across levels -- the legs suite itself
    encodes 1077936135 living in two of them -- so ownership evidence granted on level A
    must never authorise a delete against level B. Before 2026-10-06 this route compared
    nothing: the legs judge the MANIFEST, and the handle's own level was read only to fill
    the journal. The sibling residue tool and the independent cleanup service both compared
    it; this entry was the one that did not.

    The materials stay the real ones (level 1073741839); only the handle moves to
    OTHER_LEVEL. Asserted: refusal by name AND nothing dispatched.
    """
    manifest = H.base_manifest()
    sentinel.handle = lambda handle: {"handle": handle, "run": "stub",
                                      "levelId": H.OTHER_LEVEL, "entities": 1,
                                      "verifiedAtUtc": "2026-10-02T00:00:00Z",
                                      "sessionPath": "stub"}
    sentinel.bind(server, known_runs=("stub-run",))
    H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    result = server.mw_scene_cleanup_owned("handle-1", H.real_receipt_ids(manifest),
                                           manifest["roundRequestIds"], "stub-run")
    return (not sentinel.dispatched()) and \
        (H.tool_error(result) or {}).get("code") == "CLEANUP_MATERIALS_LEVEL_MISMATCH"


def p_route_legit_dispatches_once(server, sentinel):
    """(h) the legit round DOES reach the delete route -- but only the stubbed one."""
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    result = _route(server, sentinel, ids, manifest["roundRequestIds"])
    body = H.tool_body(result)
    return (sentinel.summary()["runCalls"] == 1
            and body.get("ok") is True
            and sorted(body.get("ownedIds") or []) == sorted(ids)
            and sentinel.deleted_ids_payloads == [sorted(ids)]
            and sentinel.summary()["ops"] == ["delete-owned-entity-ids-dry-run"])


def p_route_reentry_does_not_replay(server, sentinel):
    """A repeated call with the same requestIds must not re-dispatch the same delete.

    create and save answer a replay from the author journal; this route has no such
    branch.  The secure expectation is "at most one dispatch per round/requestId set".
    """
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    _route(server, sentinel, ids, request_ids, dry_run=False,
           cleanup_request_id="reentry-probe-1")
    _route(server, sentinel, ids, request_ids, dry_run=False,
           cleanup_request_id="reentry-probe-1")
    return sentinel.summary()["runCalls"] <= 1


# --------------------------------------------------------------------------- #
# Route probes -- the cleanup dispatch journal (W05)
#
# The four protections, each with a probe that a mutation can turn red:
#   (1) same request, same command      -> replay, nothing re-sent
#   (2) same request, different command -> refused, nothing sent
#   (3) claim recorded, no outcome      -> refused and reconcilable, nothing sent
#   (4) two racing calls, same request  -> exactly one dispatch
# --------------------------------------------------------------------------- #

def _journal_directory(server, request_ids, cleanup_request_id):
    journal = server._CLEANUP_DISPATCH_JOURNAL
    return journal.journal_directory(server.EVIDENCE_ROOT,
                                     server._cleanup_round_id(request_ids),
                                     cleanup_request_id)


def _mint(prefix):
    """A request name minted per probe INVOCATION.

    The journal remembers an outcome for the life of its evidence root, and that root
    lives for the life of the process, so a probe that reused a fixed name would find its
    own previous run's entry and report a replay instead of measuring the guard.
    """
    return prefix + "-" + uuid.uuid4().hex[:8]


def p_route_journal_same_request_replays(server, sentinel):
    """(1) the same request and the same command replay the recorded outcome."""
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    request_id = _mint("journal-replay")
    first = H.tool_body(_route(server, sentinel, ids, request_ids, dry_run=False,
                               cleanup_request_id=request_id))
    after_first = sentinel.summary()["runCalls"]
    second = H.tool_body(_route(server, sentinel, ids, request_ids, dry_run=False,
                                cleanup_request_id=request_id))
    return (after_first == 1 and sentinel.summary()["runCalls"] == 1
            and first.get("replayed") is False and second.get("replayed") is True
            and second.get("ok") is True
            and second.get("nativeReply") == first.get("nativeReply")
            and second.get("cleanupRequestId") == request_id)


def p_route_journal_different_command_refused(server, sentinel):
    """(2) the same request with a different command is refused, not re-bound."""
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    request_id = _mint("journal-conflict")
    _route(server, sentinel, ids, request_ids, dry_run=True,
           cleanup_request_id=request_id)
    after_first = sentinel.summary()["runCalls"]
    result = _route(server, sentinel, ids, request_ids, dry_run=False,
                    cleanup_request_id=request_id)
    error = H.tool_error(result) or {}
    return (after_first == 1 and sentinel.summary()["runCalls"] == 1
            and error.get("code") == "CLEANUP_REQUEST_ID_CONFLICT"
            and error.get("cleanupRequestId") == request_id
            and error.get("recordedCommand", {}).get("dryRun") is True
            and error.get("suppliedCommand", {}).get("dryRun") is False)


def p_route_journal_different_request_dispatches(server, sentinel):
    """The complement of (2): a DIFFERENT request with a different command dispatches.

    Without this, "refuse a different command" would be indistinguishable from "refuse
    everything after the first call", which would break the documented dry-run-then-delete
    flow and multi-batch cleanup.
    """
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    first = H.tool_body(_route(server, sentinel, ids, request_ids, dry_run=True,
                               cleanup_request_id=_mint("journal-flow-dry")))
    second = H.tool_body(_route(server, sentinel, ids, request_ids, dry_run=False,
                                cleanup_request_id=_mint("journal-flow-del")))
    return (sentinel.summary()["runCalls"] == 2
            and first.get("replayed") is False and second.get("replayed") is False
            and sentinel.summary()["ops"] == ["delete-owned-entity-ids-dry-run",
                                             "delete-owned-entity-ids"])


def p_route_journal_claim_without_outcome_refused(server, sentinel):
    """(3) a claim whose outcome was never recorded is refused and RECONCILABLE."""
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    request_id = _mint("journal-unknown")
    _route(server, sentinel, ids, request_ids, cleanup_request_id=request_id)
    after_first = sentinel.summary()["runCalls"]
    directory = _journal_directory(server, request_ids, request_id)
    (directory / "result.json").unlink()                      # the crash-between case
    result = _route(server, sentinel, ids, request_ids, cleanup_request_id=request_id)
    error = H.tool_error(result) or {}
    reconciled = server._CLEANUP_DISPATCH_JOURNAL.status(
        server.EVIDENCE_ROOT, server._cleanup_round_id(request_ids), request_id,
        server._cleanup_dispatch_key(sorted(ids), True, "stub-run"))
    return (after_first == 1 and sentinel.summary()["runCalls"] == 1
            and error.get("code") == "CLEANUP_DISPATCH_OUTCOME_UNKNOWN"
            and error.get("journalDirectory") == str(directory)
            and error.get("claimedAtUtc")
            and reconciled.get("state") == "claimed-without-result"
            and reconciled.get("outcomeKnown") is False)


def p_route_journal_unnamed_request_never_resent(server, sentinel):
    """No request name: the derived identity still refuses to send the same command twice.

    The bridge run id is minted per invocation so the DERIVED command is fresh for this
    run; a fixed run id would make the first call replay a previous run's entry and the
    probe would measure the journal's age instead of the guard.
    """
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    run_id = "stub-" + uuid.uuid4().hex[:8]
    H.install_route_evidence(server, request_ids, _m(candidates=sorted(ids)))
    sentinel.bind(server, known_runs=(run_id,))
    first = server.mw_scene_cleanup_owned("handle-1", list(ids), list(request_ids), run_id,
                                          dryRun=False, cleanupRequestId=None)
    after_first = sentinel.summary()["runCalls"]
    second = server.mw_scene_cleanup_owned("handle-1", list(ids), list(request_ids), run_id,
                                           dryRun=False, cleanupRequestId=None)
    return (after_first == 1 and sentinel.summary()["runCalls"] == 1
            and H.tool_body(first).get("replayed") is False
            and H.tool_body(second).get("replayed") is True
            and str(H.tool_body(first).get("cleanupRequestId") or "").startswith("cmd-"))


def p_route_journal_bad_request_id_refused(server, sentinel):
    """A request name that is not a safe path component never reaches the transport."""
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    codes = []
    for bad in ("", "../etc/passwd", "a/b", "x" * 81, " leading-space"):
        result = _route(server, sentinel, ids, request_ids, cleanup_request_id=bad)
        codes.append((H.tool_error(result) or {}).get("code"))
    return (not sentinel.dispatched()
            and all(code == "CLEANUP_REQUEST_ID_INVALID" for code in codes))


class _SlowSentinel(H.DispatchSentinel):
    """A sentinel whose dispatch takes long enough for a second caller to arrive."""

    def run(self, argv, timeout=None, expect_json=True):
        time.sleep(0.3)
        return H.DispatchSentinel.run(self, argv, timeout, expect_json)


def p_route_journal_race_one_dispatch(server, sentinel):
    """(4) two concurrent calls with the same request produce exactly one dispatch.

    The loser must not send a second delete.  HOW it refuses depends on how far the winner
    got when the loser looked -- the request directory exists but its claim is not written
    yet, the claim is there with no outcome, or the outcome is there and replays.  All
    three are correct, and all three are refusals; a second dispatch is not.  MEASURED
    2026-10-05: all three were observed across repeated runs, so the probe accepts all
    three rather than the one the author happened to see first.
    """
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    request_ids = manifest["roundRequestIds"]
    request_id = _mint("journal-race")
    H.install_route_evidence(server, request_ids, _m(candidates=sorted(ids)))
    slow = _SlowSentinel()
    slow.bind(server)
    out = []

    def call():
        out.append(server.mw_scene_cleanup_owned(
            "handle-1", list(ids), list(request_ids), "stub-run", dryRun=False,
            cleanupRequestId=request_id))

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    loser_ok = ("replay", "CLEANUP_DISPATCH_OUTCOME_UNKNOWN", "CLEANUP_REQUEST_INCOMPLETE_CLAIM")
    outcomes = ["replay" if H.tool_body(r).get("replayed") is True else
                (H.tool_error(r) or {}).get("code") or "dispatched"
                for r in out]
    return (len(slow.run_calls) == 1
            and outcomes.count("dispatched") == 1
            and all(o == "dispatched" or o in loser_ok for o in outcomes))


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #

LEG_PROBES = {name: (lambda p: (lambda module, sentinel=None: p(module)))(probe)
              for name, probe in {
    "a-frozen-ids-refused": p_frozen,
    "a-frozen-id-with-full-receipt-refused": p_frozen_with_receipt,
    "b-pre-baseline-member-refused": p_pre_baseline_member,
    "c-pre-baseline-absent-refused": p_pre_baseline_absent,
    "c-pre-baseline-missing-file-refused": p_pre_baseline_missing_file,
    "c-pre-baseline-empty-inline-refused": p_pre_baseline_empty_inline,
    "c-pre-baseline-undeclared-extra-refused": p_pre_baseline_undeclared_extra,
    "d-readback-absent-refused": p_readback_absent,
    "d-readback-truncated-refused": p_readback_truncated,
    "d-readback-incomplete-refused": p_readback_incomplete,
    "d-readback-unaccepted-refused": p_readback_unaccepted,
    "d-readback-level-mismatch-refused": p_readback_level_mismatch,
    "d-readback-sha256-verified": p_readback_hash_verified,
    "d-readback-time-bound-to-artifact": p_readback_time_bound_to_artifact,
    "d-readback-not-fresh-refused": p_readback_stale,
    "e-receipt-outside-window-refused": p_receipt_outside_window,
    "e-window-invalid-refused": p_window_invalid,
    "f-cross-level-refused": p_cross_level,
    "f-cross-level-dual-id-refused": p_cross_level_dual_id,
    "f-receipt-tampered-refused": p_receipt_tampered,
    "a-receipt-not-a-create-refused": p_receipt_not_a_create,
    "h-legit-round-owned-51": p_legit,
}.items()}

ROUTE_PROBES = {
    "a-route-frozen-no-dispatch": p_route_frozen_no_dispatch,
    "route-unowned-no-dispatch": p_route_unowned_no_dispatch,
    "route-run-refused-no-dispatch": p_route_run_refused_no_dispatch,
    "route-no-materials-no-dispatch": p_route_no_materials_no_dispatch,
    # Registered 2026-10-06 together with the check it watches. Registering the probe in
    # ROUTE_PROBES is what puts it in the mutation matrix's roster; without this line the
    # matrix ran its 15 other probes, never evaluated this one, and reported NO_EFFECT for
    # the mutation that removes the very guard the probe exists to catch.
    "route-materials-wrong-level-no-dispatch": p_route_materials_wrong_level_no_dispatch,
    "route-material-path-outside-runtime-no-dispatch": p_route_material_path_outside_runtime_no_dispatch,
    "route-overlapping-unknown-outcome-no-dispatch": p_route_overlapping_unknown_outcome_no_dispatch,
    "route-round-selector-unvalidated-no-dispatch": p_route_round_selector_unvalidated_no_dispatch,
    "e-route-unknown-bridge-no-dispatch": p_route_unknown_bridge_no_dispatch,
    "e-route-shape-invalid-run-id-no-dispatch": p_route_shape_invalid_run_id,
    "h-route-legit-dispatches-once": p_route_legit_dispatches_once,
    "reentry-no-replay": p_route_reentry_does_not_replay,
    "journal-same-request-replays": p_route_journal_same_request_replays,
    "journal-different-command-refused": p_route_journal_different_command_refused,
    "journal-different-request-dispatches": p_route_journal_different_request_dispatches,
    "journal-claim-without-outcome-refused": p_route_journal_claim_without_outcome_refused,
    "journal-unnamed-request-never-resent": p_route_journal_unnamed_request_never_resent,
    "journal-bad-request-id-refused": p_route_journal_bad_request_id_refused,
    "journal-race-one-dispatch": p_route_journal_race_one_dispatch,
}


def _sentinel_blind(probe):
    """Adapt a one-argument (legs) probe to the two-argument call shape."""
    return lambda module, sentinel=None: probe(module)


def run(probes, loader, sentinel_factory=None):
    """Run one probe set against a freshly loaded module.  Returns {name: bool|str}.

    ``loader`` returns the module under test; a FRESH dispatch sentinel is built per probe
    so no probe can inherit another's recorded dispatches.
    """
    factory = sentinel_factory or H.DispatchSentinel
    results = {}
    for name, probe in probes.items():
        try:
            results[name] = bool(probe(loader(), factory()))
        except Exception as exc:                                  # noqa: BLE001
            results[name] = "%s: %s" % (type(exc).__name__, exc)
    return results
