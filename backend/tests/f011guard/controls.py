"""Recorded controls: the measured behaviour behind each claim in the hand-off.

Writes ``controls.json``.  Nothing here dispatches for real -- see ``harness``.

Run:  .runtime/mcp-venv/Scripts/python.exe -B controls.py
"""
from __future__ import annotations

import json
import re
import sys

import harness as H
import probes as P


def _route_call(server, sentinel, entity_ids, request_ids, run_id="stub-run", dry_run=True):
    manifest = H.base_manifest()
    manifest["candidates"] = sorted(entity_ids)
    H.install_route_evidence(server, request_ids, manifest)
    sentinel.bind(server)
    result = server.mw_scene_cleanup_owned("handle-1", list(entity_ids), list(request_ids),
                                           run_id, dryRun=dry_run)
    return manifest, result


def control_a_frozen(server, legs):
    manifest = H.base_manifest()
    sentinel = H.DispatchSentinel()
    _manifest, result = _route_call(server, sentinel, list(H.FROZEN),
                                    manifest["roundRequestIds"])
    error = H.tool_error(result) or {}
    per_id = error.get("perId") or {}
    return {"dispatch": sentinel.summary(),
            "errorCode": error.get("code"),
            "frozenSubStates": {str(i): (per_id.get("%d:%d" % (H.LEVEL, i)) or {})
                                .get("subState") for i in H.FROZEN},
            "idsSentToTransport": sentinel.deleted_ids_payloads}


def control_b_unowned(server):
    manifest = H.base_manifest()
    sentinel = H.DispatchSentinel()
    _manifest, result = _route_call(server, sentinel, [1077936138, 1077999999],
                                    manifest["roundRequestIds"])
    return {"dispatch": sentinel.summary(),
            "errorCode": (H.tool_error(result) or {}).get("code"),
            "unowned": (H.tool_error(result) or {}).get("unowned")}


def control_c_run_refused(server=None, mutated=None):
    target = mutated or server
    manifest = H.base_manifest()
    manifest["freshReadback"] = dict(manifest["freshReadback"], entityCount=70)
    sentinel = H.DispatchSentinel()
    H.install_route_evidence(target, manifest["roundRequestIds"], manifest)
    sentinel.bind(target)
    result = target.mw_scene_cleanup_owned(
        "handle-1", H.real_receipt_ids(manifest), manifest["roundRequestIds"], "stub-run")
    error = H.tool_error(result) or {}
    return {"dispatch": sentinel.summary(), "errorCode": error.get("code"),
            "runRefusalCodes": [entry.get("code") for entry in (error.get("runRefusals") or [])]}


def control_d_unknown_bridge(server):
    manifest = H.base_manifest()
    sentinel = H.DispatchSentinel()
    sentinel.bind(server, known_runs=("a-ready-run",))
    H.install_route_evidence(server, manifest["roundRequestIds"], manifest)
    result = server.mw_scene_cleanup_owned(
        "handle-1", H.real_receipt_ids(manifest), manifest["roundRequestIds"], "made-up-run")
    return {"dispatch": sentinel.summary(),
            "errorCode": (H.tool_error(result) or {}).get("code")}


def control_e_legit(server):
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    sentinel = H.DispatchSentinel()
    _manifest, result = _route_call(server, sentinel, ids, manifest["roundRequestIds"])
    body = H.tool_body(result)
    return {"dispatch": sentinel.summary(),
            "ownedCount": len(body.get("ownedIds") or []),
            "ownedIdsMatchReceipts": sorted(body.get("ownedIds") or []) == sorted(ids),
            "nativeReply": body.get("nativeReply")}


def control_f_reentry(server):
    """DEFECT-2 evidence: two identical cleanup calls -> two dispatches."""
    manifest = H.base_manifest()
    ids = H.real_receipt_ids(manifest)
    sentinel = H.DispatchSentinel()
    first = _route_call(server, sentinel, ids, manifest["roundRequestIds"], dry_run=False)[1]
    second = _route_call(server, sentinel, ids, manifest["roundRequestIds"], dry_run=False)[1]
    return {"dispatch": sentinel.summary(),
            "firstOk": H.tool_body(first).get("ok"),
            "secondOk": H.tool_body(second).get("ok"),
            "payloadsIdentical": sentinel.deleted_ids_payloads[0] ==
                                 sentinel.deleted_ids_payloads[-1],
            "journalConsulted": "no consult_journal branch exists in the cleanup route"}


def control_g_run_guard_is_redundant_for_dispatch(legs):
    """Drop the run-level status guard: does a refused round reach the transport?"""
    mutated = H.load_server(rename=("if legs.get('status') != 'judged':", "if False:"),
                            legs=legs)
    return control_c_run_refused(mutated=mutated)


def control_h_unowned_guard_is_the_operative_one(legs):
    """Drop the per-id guard: the transport is reached with an EMPTY id list."""
    mutated = H.load_server(rename=("unowned = sorted(set(entityIds) - allowed)",
                                    "unowned = []"), legs=legs)
    return control_a_frozen(mutated, legs)


def control_i_defect1_differential(legs):
    """DEFECT-1: only the FORM of the pre-baseline changes the verdict."""
    real = H.base_manifest()
    # The real baseline does NOT contain 1077936138 (it is this round's create), so for the
    # differential we use the real baseline document with that id added: an honest
    # "the id already existed" statement.
    baseline = H.write_baseline_with_extra([1077936138])
    manifest_real = P._one_receipt_manifest(entity_id=1077936138)
    manifest_real["preBaseline"] = {"path": str(baseline)}
    report_real, owned_real = P.owned_ids(legs, manifest_real)

    manifest_empty = P._one_receipt_manifest(entity_id=1077936138)
    manifest_empty["preBaseline"] = {"ids": []}
    report_empty, owned_empty = P.owned_ids(legs, manifest_empty)

    baseline_ids = P.H.read_json(real["preBaseline"]["path"])["entities"]
    return {"withRealBaselinePath": {"ownedIds": sorted(owned_real),
                                     "subState": report_real["perId"]
                                     ["%d:%d" % (H.LEVEL, 1077936138)]["subState"]},
            "withEmptyInlineIds": {"ownedIds": sorted(owned_empty),
                                   "differenceAddedCount":
                                       (report_empty["difference"] or {}).get("addedCount")},
            "realBaselineEntityCount": len(baseline_ids),
            "baselineWithIdEntityCount": len(H.read_json(baseline)["entities"]),
            "readbackEntityCount": real["freshReadback"]["entityCount"],
            "note": "the ONLY changed field is preBaseline; the id becomes deletable"}


def control_j_defect2_static(server_module_path=H.SERVER_PATH):
    """DEFECT-2 evidence: create/save consult the author journal; cleanup does not."""
    source = H.SERVER_PATH.read_text(encoding="utf-8")
    findings = {}
    for tool in ("mw_scene_create_entity", "mw_scene_save_level", "mw_scene_cleanup_owned"):
        match = re.search(r"\ndef %s\(.*?\n(?=@mcp\.tool|\ndef |\n#:|\Z)" % tool,
                          source, re.DOTALL)
        body = match.group(0) if match else ""
        findings[tool] = {"consultJournalCalls": body.count("consult_journal"),
                          "journalRootReferences": body.count("JOURNAL_ROOT"),
                          "lines": body.count("\n")}
    return findings


def control_k_defect3_differential(legs):
    """DEFECT-3: the manifest's declared digests/times are never checked."""
    artifact = H.read_json(H.manifest_paths()["freshReadback"])
    sibling_exit = H.read_json(H.REPO / ".runtime/game-executor/scene-cli/inspect"
                               / "20261002-170034-e893fcc657/exit.json")
    manifest_hash = P._one_receipt_manifest(entity_id=1077936138)
    manifest_hash["freshReadback"] = dict(manifest_hash["freshReadback"], sha256="0" * 64)
    _r1, owned_hash = P.owned_ids(legs, manifest_hash)

    manifest_time = P._one_receipt_manifest(entity_id=1077936138)
    manifest_time["freshReadback"] = dict(manifest_time["freshReadback"],
                                          readAtUtc="2026-09-30T02:12:20Z")
    report_time, owned_time = P.owned_ids(legs, manifest_time)

    return {"declaredSha256ReplacedWithZeros": {"ownedIds": sorted(owned_hash)},
            "declaredReadAtUtcContradictingArtifact": {
                "ownedIds": sorted(owned_time),
                "readbackReportedReadAtUtc":
                    (report_time.get("readback") or {}).get("readAtUtc"),
                "artifactExitStartedUtc": sibling_exit.get("startedUtc"),
                "artifactReadAtUtcInDocument": artifact.get("readAtUtc")},
            "note": "the artifact's own record is overridden by the manifest; neither "
                    "digest is verified"}


def main():
    legs = H.load_legs()
    server = H.load_server(legs=legs)
    report = {
        "units": {"legsSha256": H.sha256_file(H.LEGS_PATH),
                  "serverSha256": H.sha256_file(H.SERVER_PATH)},
        "A-frozen-ids": control_a_frozen(server, legs),
        "B-unowned-id": control_b_unowned(server),
        "C-run-level-refusal": control_c_run_refused(server),
        "D-unknown-bridge-run": control_d_unknown_bridge(server),
        "E-legit-round": control_e_legit(server),
        "F-reentry": control_f_reentry(server),
        "G-run-guard-redundant": control_g_run_guard_is_redundant_for_dispatch(legs),
        "H-unowned-guard-operative": control_h_unowned_guard_is_the_operative_one(legs),
        "I-defect1-differential": control_i_defect1_differential(legs),
        "J-defect2-static": control_j_defect2_static(),
        "K-defect3-differential": control_k_defect3_differential(legs),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    H.write_json(H.HERE / "controls.json", report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
