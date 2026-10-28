"""Short native workflows with immutable intent, one writer and saved readback."""
import hashlib
import contexts
import compile_inputs


def schemas(obj, string):
    return {"scene.apply": (
        "Create one structured batch, native-save and verify every new saved entity; requires enabled "
        "context and existing helper. No helper startup or retries.",
        obj({"context": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
             "operation_id": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$"},
             "placements": {"type": "array", "items": compile_inputs.PLACEMENT,
                            "minItems": 1, "maxItems": 256}, "large_scene": {"type": "boolean"}},
            ("context", "operation_id", "placements")))}


def writer_path(api, ctx):
    # Session identity spans levels and contexts. Different session-file paths with the
    # same actual PID must share a lock; never use an old PID to initiate game calls.
    session = api.read(ctx["session"]) if ctx.get("session") else {}
    identity = str(session.get("pid", session.get("processId", ctx.get("sessionSha256") or ctx["save"])))
    return api.RUNTIME / "active-writers" / (hashlib.sha256(identity.encode()).hexdigest() + ".json")


def invoke(api, name, args, *, plan=False):
    directory, ctx = contexts.load(api, args["context"])
    if not plan and (not ctx["nativeEnabled"] or not ctx.get("session") or not ctx.get("queue")):
        raise api.ToolError("CONTEXT_NATIVE_REQUIRES_ENABLED_SESSION_AND_QUEUE")
    tools = api.registry()
    for required in ("scene.inspect", "scene.review", "scene.create_batch", "scene.save"):
        if required not in tools:
            raise api.ToolError("WORKFLOW_TOOL_NOT_REGISTERED:" + required)
        api.verify_tool_code(tools[required])
    compiled = compile_inputs.scene_plan(api, {"placements": args["placements"]})
    if plan:
        return {"ok": True, "mode": "plan", "plan": compiled,
                "steps": ["scene.inspect", "scene.review", "scene.create_batch",
                          "scene.inspect", "scene.review", "scene.save", "context.readback"],
                "levelId": ctx["levelId"], "nativeCalled": False, "runtimeVerified": False}
    from datetime import datetime, timezone
    if (datetime.fromisoformat(ctx["expiresUtc"]) - datetime.now(timezone.utc)).total_seconds() < 15*60:
        raise api.ToolError("WORKFLOW_DEADLINE_REQUIRES_15_MINUTES")
    folder = directory / ("workflow-" + args["operation_id"])
    fingerprint = hashlib.sha256(api.compact(args).encode()).hexdigest()
    try:
        folder.mkdir()
    except FileExistsError:
        claim = api.read(folder / "intent.json") if (folder / "intent.json").exists() else {}
        if claim.get("fingerprint") != fingerprint:
            raise api.ToolError("WORKFLOW_ID_CONFLICT")
        if (folder / "result.json").exists():
            return dict(api.read(folder / "result.json"), redispatched=False)
        raise api.ToolError("WORKFLOW_ALREADY_CLAIMED_OUTCOME_UNKNOWN")
    contexts.write(folder / "intent.json", {"fingerprint": fingerprint, "arguments": args,
                   "saveSha256": ctx["saveSha256"], "compiledPlan": compiled})
    lock = writer_path(api, ctx)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock.open("x", encoding="utf-8") as f:
            f.write(api.compact({"context": args["context"], "operationId": args["operation_id"]}))
    except FileExistsError:
        raise api.ToolError("NATIVE_WRITER_ACTIVE_OR_UNCERTAIN")
    steps, changed, uncertain = [], False, False
    def call(label, toolname, supplied):
        nonlocal changed, uncertain
        contexts.load(api, args["context"])
        tool = tools[toolname]
        bound = contexts.bound_arguments(api, ctx, tool, supplied, args["operation_id"] + "_" + label)
        contexts.write(folder / (label + "-intent.json"), {"tool": toolname, "arguments": bound})
        uncertain = bool(tool["nativePossible"])
        result = api.execute_tool(tool, bound)
        contexts.write(folder / (label + "-receipt.json"), result)
        uncertain = result.get("outcomeUncertain", uncertain)
        steps.append({"id": label, "tool": toolname, "ok": result.get("ok"),
                      "receipt": str(folder / (label + "-receipt.json"))})
        if not result.get("ok") or not isinstance(result.get("result"), dict):
            raise api.ToolError("WORKFLOW_STEP_FAILED:" + label)
        if toolname == "scene.create_batch":
            changed = True
        return result["result"]
    result = None
    try:
        plan_path = compiled["plan_file"]
        before = call("inspect", "scene.inspect", {"large_scene": args.get("large_scene", True)})
        review = call("review_create", "scene.review", {
            "action": "create-batch", "plan": plan_path, "baseline_run": before["run"],
            "baseline_kind": "readonly", "recovery_dir": str(folder / "recovery-create")})
        created = call("create", "scene.create_batch", {"plan": plan_path, "review": review["reviewPath"]})
        fresh = call("inspect_save", "scene.inspect", {"large_scene": args.get("large_scene", True)})
        review_save = call("review_save", "scene.review", {
            "action": "save", "baseline_run": fresh["run"], "baseline_kind": "readonly",
            "recovery_dir": str(folder / "recovery-save")})
        call("save", "scene.save", {"review": review_save["reviewPath"]})
        readback = contexts.invoke(api, "context.readback", {"context": args["context"]})
        import saved as save_reader
        snapshot = save_reader.snapshot(ctx["save"], ctx["levelId"])
        entities = {e["entityId"]: e for e in snapshot["entities"]}
        ids, mismatches = created.get("placedIds") or [], []
        if len(ids) != len(args["placements"]) or len(set(ids)) != len(ids):
            mismatches.append("CREATE_RECEIPT_ID_COUNT")
        for eid, desired in zip(ids, args["placements"]):
            actual = entities.get(eid)
            if not actual or actual["templateId"] != desired["template_id"]:
                mismatches.append({"entityId": eid, "field": "template"})
                continue
            for field in ("position", "scale", "rotation"):
                want = desired.get(field, [0., 0., 0.] if field == "rotation" else None)
                got = actual.get(field)
                if not got or not want or len(got) != 3 or any(abs(float(a)-float(b)) > .001 for a, b in zip(got, want)):
                    mismatches.append({"entityId": eid, "field": field})
        ok = not mismatches and readback["saveChanged"] and set(ids) <= set(readback["addedIds"])
        result = {"ok": ok, "levelId": ctx["levelId"], "steps": steps, "savedIds": ids if ok else [],
                  "mismatches": mismatches, "readback": readback, "nativeSaveVerified": ok,
                  "runtimeVerified": False, "visualVerified": False, "passageVerified": False,
                  "replayForbidden": True, "outcomeUncertain": False,
                  "receipt": str(folder / "result.json")}
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "steps": steps, "sceneMayHaveChanges": changed or uncertain,
                  "outcomeUncertain": uncertain, "replayForbidden": True, "nativeSaveVerified": False,
                  "next": "Read the preserved receipts and context.readback; never replay this operation.",
                  "receipt": str(folder / "result.json")}
    finally:
        if result is not None:
            contexts.write(folder / "result.json", result)
        if not uncertain:
            lock.unlink()
    return result
