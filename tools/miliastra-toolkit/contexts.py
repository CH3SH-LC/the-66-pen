"""Portable save contexts, explicit ownership and bounded invocation journals."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / ".runtime/miliastra-toolkit/contexts"


def schemas(obj, string):
    ident = {"type": "string", "pattern": "^[a-f0-9]{32}$"}
    operation = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}
    ints = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 4294967295},
            "maxItems": 50000}
    call = obj({"context": ident, "tool": string, "arguments": {"type": "object"},
                "operation_id": operation}, ("context", "tool", "arguments", "operation_id"))
    return {
        "context.open": ("Bind an actual .gil, explicit level and optional current session; no game access.",
            obj({"save": string, "level_id": {"type": "integer", "minimum": 1, "maximum": 4294967295},
                 "session": string, "queue": string, "native_enabled": {"type": "boolean"},
                 "valid_minutes": {"type": "integer", "minimum": 1, "maximum": 1440}},
                ("save", "level_id"))),
        "context.status": ("Inspect context, save drift, expiry and session-file drift once.",
            obj({"context": ident}, ("context",))),
        "context.instances": ("Read saved entities/graphs in this exact save without scanning every library.",
            obj({"context": ident, "kind": {"type": "string", "enum": ["entities", "graphs"]},
                 "offset": {"type": "integer", "minimum": 0},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, ("context",))),
        "context.ownership": ("Create explicit save-bound assembly selection; does not grant native permission.",
            obj({"context": ident, "entity_ids": ints, "accessory_ids": ints,
                 "reparent": {"type": "array", "items": obj({
                     "accessoryId": {"type": "integer", "minimum": 1},
                     "oldHostId": {"type": "integer", "minimum": 1},
                     "hostId": {"type": "integer", "minimum": 1}}, ("accessoryId", "oldHostId", "hostId"))},
                 "convert": {"type": "array", "items": obj({
                     "sourceId": {"type": "integer", "minimum": 1},
                     "hostId": {"type": "integer", "minimum": 1}}, ("sourceId", "hostId"))}},
                ("context", "entity_ids"))),
        "context.plan": ("Bind context into a registered generic tool and validate argv without execution.", call),
        "context.call": ("Dispatch one bound tool once; scoped journal, no automatic retry or helper startup.", call),
        "context.readback": ("Independently parse the current formal save and compare to the bound snapshot.",
            obj({"context": ident}, ("context",))),
    }


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def load(api, identity, *, drift=True):
    if not re.fullmatch("[a-f0-9]{32}", identity):
        raise api.ToolError("CONTEXT_ID")
    directory = HOME / identity
    value = api.read(directory / "context.json")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(value["expiresUtc"]):
        raise api.ToolError("CONTEXT_EXPIRED")
    if drift and api.sha(value["save"]) != value["saveSha256"]:
        raise api.ToolError("CONTEXT_SAVE_DRIFT:use context.readback; do not rebase automatically")
    if value.get("session") and api.sha(value["session"]) != value["sessionSha256"]:
        raise api.ToolError("CONTEXT_SESSION_FILE_DRIFT")
    return directory, value


def save_identity(path, expected):
    import saved
    raw = path.read_bytes()
    container = saved.gc.decode_container(raw)
    declared = next((f.value for f in saved.gc.parse_fields(container.payload)
                     if f.number == saved.gc.LEVEL_FIELD_ID), None)
    if declared is not None:
        if declared != expected:
            raise ValueError("CONTEXT_EMBEDDED_LEVEL_MISMATCH")
        return "embedded-field"
    match = re.fullmatch(r"(?:save)?(\d+)\.gil", path.name, re.I)
    if not match or int(match[1]) != expected:
        raise ValueError("CONTEXT_MISSING_EMBEDDED_ID_REQUIRES_FORMAL_FILENAME")
    return "formal-filename-no-embedded-id"


def bound_arguments(api, ctx, tool, supplied, operation):
    if tool["name"].startswith(("map.", "mondstadt.", "demo.", "activities.")):
        raise api.ToolError("CONTEXT_FIXED_SCENE_TOOL:use generic scene/transform/material tools")
    props = tool["inputSchema"]["properties"]
    args = dict(supplied)
    mapping = {"level_id": ctx["levelId"], "target_level": ctx["levelId"],
               "save": ctx["save"], "gil": ctx["save"], "target_gil": ctx["save"]}
    if ctx.get("session"):
        mapping["session"] = ctx["session"]
    if ctx.get("queue"):
        mapping.update(elevated_queue=ctx["queue"], queue_dir=ctx["queue"])
    for key, value in mapping.items():
        if key in props:
            if key in args and str(args[key]) != str(value):
                raise api.ToolError("CONTEXT_ARGUMENT_CONFLICT:" + key)
            args[key] = value
    if "direct_elevated" in args and args["direct_elevated"]:
        raise api.ToolError("CONTEXT_DIRECT_ELEVATION_DISABLED")
    if tool["nativePossible"]:
        if not ctx["nativeEnabled"] or not ctx.get("session") or not ctx.get("queue"):
            raise api.ToolError("CONTEXT_NATIVE_REQUIRES_ENABLED_SESSION_AND_QUEUE")
        if not any(k in props for k in ("level_id", "target_level", "baseline", "run")):
            raise api.ToolError("CONTEXT_TOOL_NEEDS_EXPLICIT_BRIDGE_BINDING")
        remaining = (datetime.fromisoformat(ctx["expiresUtc"]) - datetime.now(timezone.utc)).total_seconds()
        requested = args.get("_timeout_seconds", 300)
        if requested + 30 > remaining:
            raise api.ToolError("CONTEXT_DEADLINE_INSUFFICIENT_FOR_OPERATION")
    for key in ("request", "ownership"):
        if args.get(key):
            value = api.read(api.project_path(args[key]))
            if value.get("levelId") != ctx["levelId"]:
                raise api.ToolError("CONTEXT_INPUT_LEVEL_MISMATCH:" + key)
    if tool["mutating"]:
        args["_operation_id"] = operation
    return args


def invoke(api, name, args, *, plan=False):
    import saved
    if name == "context.open":
        path = Path(api.project_path(args["save"]))
        identity_source = save_identity(path, args["level_id"])
        report = saved.snapshot(path, args["level_id"])
        if args.get("native_enabled") and args["level_id"] in api.PROTECTED:
            raise api.ToolError("CONTEXT_PROTECTED_LEVEL")
        identity = uuid.uuid4().hex
        directory = HOME / identity
        value = {"schemaVersion": 1, "id": identity, "save": str(path), "levelId": args["level_id"],
                 "saveSha256": report["sha256"], "identityEvidence": identity_source,
                 "session": str(Path(api.project_path(args["session"]))) if args.get("session") else None,
                 "queue": api.project_path(args["queue"], write=True) if args.get("queue") else None,
                 "nativeEnabled": args.get("native_enabled", False),
                 "expiresUtc": (datetime.now(timezone.utc) + timedelta(minutes=args.get("valid_minutes", 60))).isoformat()}
        value["sessionSha256"] = api.sha(value["session"]) if value["session"] else None
        if plan:
            return {"ok": True, "contextPreview": value, "nativeCalled": False}
        write(directory / "snapshot.json", report)
        write(directory / "context.json", value)
        return {"ok": True, "context": identity, "levelId": value["levelId"],
                "entityCount": report["entityCount"], "graphCount": report["graphCount"],
                "saveSha256": report["sha256"], "identityEvidence": identity_source,
                "nativeEnabled": value["nativeEnabled"], "nativeCalled": False,
                "next": "context.instances"}
    if name == "context.status":
        directory, ctx = load(api, args["context"], drift=False)
        actual = api.sha(ctx["save"])
        return {"ok": True, "context": ctx, "saveUnchanged": actual == ctx["saveSha256"],
                "actualSaveSha256": actual, "nativeCalled": False,
                "currentProcessVerified": False}
    if name == "context.readback":
        # Readback must remain available after expiry or a native operation; never refresh the context silently.
        directory = HOME / args["context"]
        ctx = api.read(directory / "context.json")
        current = saved.snapshot(ctx["save"], ctx["levelId"])
        before = api.read(directory / "snapshot.json")
        old = {e["entityId"]: e for e in before["entities"]}
        new = {e["entityId"]: e for e in current["entities"]}
        result = {"ok": True, "beforeSha256": before["sha256"], "afterSha256": current["sha256"],
                  "saveChanged": before["sha256"] != current["sha256"],
                  "addedIds": sorted(new.keys()-old.keys()), "removedIds": sorted(old.keys()-new.keys()),
                  "changedIds": [i for i in old.keys() & new.keys() if old[i] != new[i]],
                  "graphsChanged": before["graphs"] != current["graphs"],
                  "rootFieldsChanged": before["rootFields"] != current["rootFields"],
                  "nativeCalled": False, "nativeSaveVerified": False, "runtimeVerified": False}
        if not plan:
            write(directory / ("readback-" + current["sha256"][:16] + ".json"), result)
        return result
    directory, ctx = load(api, args["context"])
    if name == "context.instances":
        records = api.read(directory / "snapshot.json")[args.get("kind", "entities")]
        start, limit = args.get("offset", 0), args.get("limit", 50)
        return {"ok": True, "total": len(records), "items": records[start:start+limit],
                "nextOffset": start+limit if start+limit < len(records) else None, "nativeCalled": False}
    if name == "context.ownership":
        entities = {e["entityId"] for e in api.read(directory / "snapshot.json")["entities"]}
        selected = args["entity_ids"]
        if len(selected) != len(set(selected)) or not set(selected) <= entities:
            raise api.ToolError("OWNERSHIP_ENTITY_NOT_IN_SAVE_OR_DUPLICATE")
        value = {"schemaVersion": 1, "kind": "miliastra-ownership-v1", "levelId": ctx["levelId"],
                 "saveSha256": ctx["saveSha256"], "entityIds": selected,
                 "accessoryIds": args.get("accessory_ids", []),
                 "operations": {"reparent": args.get("reparent", []), "convert": args.get("convert", [])}}
        for pair in value["operations"]["reparent"]:
            if pair["accessoryId"] not in value["accessoryIds"] or not {pair["oldHostId"], pair["hostId"]} <= set(selected):
                raise api.ToolError("OWNERSHIP_PAIR_SELECTION")
        for pair in value["operations"]["convert"]:
            if not set(pair.values()) <= set(selected):
                raise api.ToolError("OWNERSHIP_PAIR_SELECTION")
        digest = hashlib.sha256(api.compact(value).encode()).hexdigest()
        output = directory / ("ownership-" + digest[:20] + ".json")
        if not plan:
            write(output, value)
        return {"ok": True, "ownership": str(output), "document": value,
                "accessoryRelationshipsVerified": False, "nativeCalled": False,
                "next": "transform.reparent_prepare / transform.semantic_assembly_prepare; preparation checks every relationship"}
    tools = api.registry()
    if args["tool"] not in tools:
        raise api.ToolError("CONTEXT_REGISTERED_PRODUCTION_TOOL_REQUIRED")
    tool = tools[args["tool"]]
    bound = bound_arguments(api, ctx, tool, args["arguments"], args["operation_id"])
    if plan or name == "context.plan":
        return api.execute_tool(tool, bound, plan=True)
    # One context-level writer. Unknown outcomes deliberately retain the lock.
    import operations
    lock = operations.writer_path(api, ctx)
    lock.parent.mkdir(parents=True, exist_ok=True)
    native = tool["nativePossible"]
    if native:
        try:
            with lock.open("x", encoding="utf-8") as f:
                json.dump({"operationId": args["operation_id"], "tool": tool["name"]}, f)
        except FileExistsError:
            raise api.ToolError("CONTEXT_WRITER_ACTIVE_OR_UNCERTAIN:inspect receipt; do not delete lock")
    try:
        result = api.execute_tool(tool, bound)
        write(directory / ("operation-" + args["operation_id"] + ".json"), result)
        if native and not result.get("outcomeUncertain"):
            lock.unlink()
        return result
    except Exception:
        # Dispatch may have started; never clear this based on an exception.
        raise
