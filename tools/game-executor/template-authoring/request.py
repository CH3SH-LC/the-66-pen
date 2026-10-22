"""Prepare closed template-authoring requests and unreviewed evidence, offline.

No compiler, helper, hook, process query, native function, save or dispatch runs.
Existing native_write_review.load_baseline supplies its disk-only receipt checks;
this does not authorize these new actions under an existing write profile.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
EXECUTOR = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".runtime" / "template-authoring"
sys.path.insert(0, str(EXECUTOR))
import native_write_review as review_api

ACTIONS = ("create-currency", "create-item", "create-skill", "bind-shop", "bind-bag")
SESSION_FIELDS = review_api.SESSION_FIELDS
REQUEST_FIELDS = {"schemaVersion", "kind", "requestId", "runId", "levelId", "session", "action", "parameters"}


class RequestError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise RequestError(reason)


def exact_fields(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), "CLOSED_SCHEMA:" + label)


def uint(value, name, bits=32):
    require(type(value) is int and 0 < value < 2**bits, "INVALID_UINT:" + name)
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def runtime_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    require(path.is_relative_to(ROOT / ".runtime") and path != ROOT / ".runtime",
            "EVIDENCE_OUTSIDE_PROJECT_RUNTIME")
    return path


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_request(value):
    """Validate closed intent only; never label caller IDs as runtime verified."""
    exact_fields(value, REQUEST_FIELDS, "request")
    require(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1
            and value["kind"] == "template-authoring-request-v1", "REQUEST_VERSION")
    try:
        identifier = uuid.UUID(value["requestId"])
    except (ValueError, TypeError, AttributeError):
        raise RequestError("REQUEST_ID_MUST_BE_NONZERO_CANONICAL_UUID") from None
    require(identifier.int != 0 and str(identifier) == value["requestId"],
            "REQUEST_ID_MUST_BE_NONZERO_CANONICAL_UUID")
    require(isinstance(value["runId"], str) and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value["runId"]) is not None,
            "INVALID_BASELINE_RUN_ID")
    uint(value["levelId"], "levelId")
    session = value["session"]
    exact_fields(session, SESSION_FIELDS, "session")
    require(type(session["schemaVersion"]) is int and session["schemaVersion"] == 1,
            "SESSION_VERSION")
    for name in ("pid", "tid"):
        uint(session[name], "session." + name)
    for name in ("window", "processCreation", "threadCreation"):
        uint(session[name], "session." + name, bits=64)
    require(session["windowClass"] == "UnityWndClass", "SESSION_WINDOW_CLASS")
    require(isinstance(session["image"], str) and bool(session["image"]) and
            "\0" not in session["image"], "SESSION_IMAGE_REQUIRED")
    action = value["action"]
    require(action in ACTIONS, "UNSUPPORTED_ACTION")
    parameters = value["parameters"]
    if action.startswith("create-"):
        # No requested resource ID, source pointer, kind, RVA or callback input.
        exact_fields(parameters, {"name"}, "create-parameters")
        name = parameters["name"]
        require(isinstance(name, str) and bool(name) and "\0" not in name, "INVALID_UTF8_NAME")
        try:
            encoded = name.encode("utf-8", errors="strict")
        except UnicodeError:
            raise RequestError("INVALID_UTF8_NAME") from None
        require(1 <= len(encoded) <= 128, "UTF8_NAME_TOO_LONG")
    else:
        exact_fields(parameters, {"entityId", "templateId"}, "bind-parameters")
        uint(parameters["entityId"], "entityId")
        uint(parameters["templateId"], "templateId")
    # A detached plain JSON copy prevents later caller mutation of the evidence.
    return json.loads(canonical_bytes(value))


def session_from_file(path):
    source = runtime_path(path)
    session = read_json(source)
    require(type(session) is dict and set(SESSION_FIELDS) <= set(session), "SESSION_FIELDS_MISSING")
    return {key: session[key] for key in SESSION_FIELDS}


def make_request(*, action, run_id, level_id, session, parameters, request_id=None):
    return validate_request({
        "schemaVersion": 1, "kind": "template-authoring-request-v1",
        "requestId": request_id or str(uuid.uuid4()), "runId": run_id,
        "levelId": level_id, "session": session, "action": action, "parameters": parameters,
    })


def _baseline_hashes(run, baseline_kind):
    names = ["prepared.json", "build-result.json", "stdout.jsonl", "exit.json"]
    if baseline_kind == "action-after":
        names.append("result.json")
    built = read_json(run / "build-result.json")
    require(type(built.get("hashes")) is dict, "BASELINE_BUILD_HASHES_REQUIRED")
    for name in built["hashes"]:
        require(isinstance(name, str) and (run / name).resolve().parent == run,
                "BASELINE_ARTIFACT_PATH")
        names.append(name)
    return {name: sha256(run / name) for name in sorted(set(names))}


def prepare(value, *, baseline_run, baseline_kind="readonly"):
    request = validate_request(value)
    require(baseline_kind in ("readonly", "action-after"), "BASELINE_KIND_UNSUPPORTED")
    run = runtime_path(baseline_run)
    require(run.is_dir() and run.name == request["runId"], "BASELINE_RUN_ID_MISMATCH")
    hashes = _baseline_hashes(run, baseline_kind)
    # Pure file/receipt checks only. validate_session would query the live process
    # and intentionally remains the future dispatcher's separate responsibility.
    snapshot, prepared = review_api.load_baseline(run, baseline_kind, request["levelId"])
    for key in SESSION_FIELDS:
        require(prepared["session"].get(key) == request["session"][key],
                "BASELINE_SESSION_MISMATCH:" + key)
    ids = [entity["id"] for entity in snapshot["entities"]]
    parameters = request["parameters"]
    target = None
    if request["action"].startswith("bind-"):
        require(parameters["entityId"] in ids, "TARGET_ENTITY_NOT_IN_BASELINE")
        target = next(entity for entity in snapshot["entities"] if entity["id"] == parameters["entityId"])
    require(hashes == _baseline_hashes(run, baseline_kind), "BASELINE_CHANGED_DURING_PREPARE")
    content = canonical_bytes(request)
    request_hash = hashlib.sha256(content).hexdigest()
    checks = ["fresh-game-thread-session-and-level-identity", "current-disk-and-handler-profile-binding",
              "fresh-complete-native-context-baseline", "coordinator-review-and-recoverable-save-evidence"]
    if request["action"].startswith("create-"):
        checks += ["native-managed-name-construction",
                   "native-default-initialization", "exact-template-catalog-delta-and-allocated-id"]
        if request["action"] == "create-skill":
            checks += ["skill-full-helper-and-default-table-readiness", "skill-companion-registration",
                       "local-full-catalog-capture-capacity-not-official-limit"]
        else:
            checks += ["native-template-count-below-ui-limit"]
        if request["action"] == "create-item":
            checks += ["normal-item-controller-and-source-empty", "item-companion-registration"]
    else:
        checks += ["template-exists-and-requested-kind-confirmed-by-native-readback",
                   "target-owner-and-component-config-identity", "current-binding-and-dependency-refresh",
                   "bound-reference-id-and-owner-notification-readback"]
    evidence = {
        "schemaVersion": 1, "kind": "template-authoring-review-input-v1", "state": "unreviewed",
        "reviewed": False, "dispatchable": False, "requestSha256": request_hash,
        "preparedAtUtc": datetime.now(timezone.utc).isoformat(),
        "baselineRun": str(run), "baselineKind": baseline_kind, "baselineEvidenceHashes": hashes,
        "readonlyProfileSha256": review_api.profiles.PROFILE_SHA256,
        "baselineFileValidation": "native_write_review.load_baseline",
        "baselineLevelId": request["levelId"], "baselineEntityCount": len(ids),
        "baselineSessionFieldsMatched": list(SESSION_FIELDS), "liveSessionRevalidated": False,
        "targetEntityFromBaseline": target,
        "templateIdentity": None if target is None else {
            "templateId": parameters["templateId"],
            "requestedKind": "shop" if request["action"] == "bind-shop" else "bag",
            "source": "caller-supplied-existing-id", "existenceVerified": False, "kindVerified": False,
        },
        "requiredRuntimeChecks": checks, "compiled": False, "nativeCalled": False,
        "registeredVerified": False, "persistentSaveVerified": False,
        "note": "Prepared intent and previously recorded baseline only; not reviewed, compiled, "
                "dispatched or a permission to call an existing helper action.",
    }
    output_root = OUTPUT.resolve()
    require(output_root.is_relative_to((ROOT / ".runtime" / "template-authoring").resolve()),
            "OUTPUT_OUTSIDE_TEMPLATE_RUNTIME")
    destination = output_root / request["runId"] / request["requestId"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.mkdir()  # Exclusive directory: repeated request IDs never overwrite.
    except FileExistsError:
        raise RequestError("REQUEST_ALREADY_PREPARED") from None
    canonical_path, evidence_path = destination / "request.json", destination / "review-evidence.json"
    with canonical_path.open("xb") as stream:
        stream.write(content)
    result = {"ok": True, "state": "prepared-not-dispatchable", "reviewed": False,
              "dispatchable": False, "compiled": False, "nativeCalled": False,
              "requestId": request["requestId"], "runId": request["runId"],
              "levelId": request["levelId"], "action": request["action"],
              "requestSha256": request_hash, "requestPath": str(canonical_path),
              "reviewEvidencePath": str(evidence_path)}
    for path, data in ((evidence_path, evidence), (destination / "prepared.json", result)):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    return result


def parser():
    result = argparse.ArgumentParser(description="Prepare-only template authoring; no dispatch or compile.")
    actions = result.add_subparsers(dest="action", required=True)
    for action in ACTIONS:
        item = actions.add_parser(action)
        item.add_argument("--run-id", required=True, help="Exact native baseline run directory name")
        item.add_argument("--level-id", type=int, required=True)
        item.add_argument("--session", required=True, help="Explicit session JSON under this repository .runtime")
        item.add_argument("--baseline-run", required=True)
        item.add_argument("--baseline-kind", choices=("readonly", "action-after"), default="readonly")
        item.add_argument("--request-id", help="Optional canonical UUID; defaults to a fresh UUID")
        if action.startswith("create-"):
            if action == "create-skill":
                item.add_argument("--name", default="MW_FARM_PLANT")
            else:
                item.add_argument("--name", required=True)
        else:
            item.add_argument("--entity-id", type=int, required=True)
            item.add_argument("--template-id", type=int, required=True,
                              help="Existing ID; existence/kind must still be read back by the future executor")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        parameters = {"name": args.name} if args.action.startswith("create-") else {
            "entityId": args.entity_id, "templateId": args.template_id}
        request = make_request(action=args.action, run_id=args.run_id, level_id=args.level_id,
                               session=session_from_file(args.session), parameters=parameters,
                               request_id=args.request_id)
        result = prepare(request, baseline_run=args.baseline_run, baseline_kind=args.baseline_kind)
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"ok": False, "state": "refused", "error": str(error),
                          "reviewed": False, "dispatchable": False, "compiled": False,
                          "nativeCalled": False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
