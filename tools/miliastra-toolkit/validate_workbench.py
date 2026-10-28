"""Consolidated offline verification. No native dispatch, helper startup or game changes."""
from datetime import datetime, timezone
import dataclasses
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import toolkit as api
import contexts
import operations
import saved

ROOT = api.ROOT
DATA = ROOT / "data/ai-workbench"


def main():
    checks = []
    def check(name, condition, detail=None):
        checks.append({"name": name, "ok": bool(condition), "detail": detail})
    def refuses(name, fn, contains):
        try:
            fn()
            check(name, False, "did not refuse")
        except Exception as exc:
            check(name, contains in str(exc), str(exc))
    def call(name, args, plan=False):
        return api.invoke(name, args, plan=plan)

    start = time.monotonic()
    registry = api.registry()
    for path in ("knowledge.sqlite",):
        with sqlite3.connect(DATA / path) as db:
            check("knowledge_sqlite_integrity", db.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
            expected = json.loads((ROOT / "data/node-workbench/catalog.json").read_text(encoding="utf-8"))["nodes"]
            keys = {r[0].removeprefix("node:") for r in db.execute("SELECT id FROM node_keys")}
            check("every_recorded_node_variant_indexed", keys == {n["key"] for n in expected}, len(keys))
    coverage = api.read(DATA / "coverage.json")
    expected = set(api.read(DATA / "distribution.json")["omittedLibraries"])
    check("public_library_omissions_are_explicit", set(coverage["missingLibraries"]) == expected,
          coverage["missingLibraries"])
    check("every_recorded_node_has_recipe_and_contract",
          coverage["nodes"]["variants"] == coverage["nodes"]["recipes"] == coverage["nodes"]["uniqueContracts"],
          coverage["nodes"])
    check("unknown_node_fields_are_not_marked_verified", coverage["nodes"]["unknownFields"] > 0
          and coverage["nodes"]["runtimeVerified"] < coverage["nodes"]["variants"])
    check("production_schema_capture_complete", not api.read(api.DATA / "tools.json")["captureFailures"])
    for name in ("transform.reparent_prepare", "transform.semantic_assembly_prepare"):
        check(name + "_portable_schema", "ownership" in registry[name]["inputSchema"]["properties"])
    check("new_workflow_primitives_registered", all(n in registry for n in
          ("scene.review", "live.discover", "visual.window")))
    search = call("knowledge.search", {"query": "拼接", "limit": 3})
    check("paged_chinese_search", len(search["results"]) <= 3 and search["total"] > 0, search["total"])
    first = search["results"][0]
    check("exact_record_retrieval", call("knowledge.get", {"id": first["id"]})["ok"])
    node = call("knowledge.node", {"definition_id": 1, "graph_kind": 20000})
    check("node_recipe_full", node["ok"] and node["record"]["recipe"] is not None)
    refuses("node_without_graph_kind_refused", lambda: call("knowledge.node", {"definition_id": 1}),
            "NODE_GRAPH_KIND")
    check("failure_recovery_route", call("knowledge.errors", {"code": "REPARENT_FORMAL_STATE_DRIFT"})["recovery"][0]["retry"]
          == "never-automatically")
    check("workflow_routes_exist", len(call("knowledge.route", {"task": "拼接"})["routes"]) > 0)
    for tool, file in (("scene.plan","scene-plan.json"), ("graph.compile","graph-plan.json")):
        compiled = call(tool, api.read(DATA / "examples" / file))
        check("executable_example_" + tool, compiled["ok"] and Path(compiled["plan_file"]).is_file())
    refuses("schema_unknown_field", lambda: call("context.open", {"save": "x", "level_id": 42, "pid": 1}),
            "SCHEMA_UNKNOWN_FIELDS")
    refuses("bool_is_not_integer", lambda: call("knowledge.node", {"definition_id": True, "graph_kind": 20000}),
            "SCHEMA_TYPE")
    refuses("recursive_call", lambda: call("tool.call", {"name": "tool.call", "arguments": {}}),
            "RECURSIVE_TOOL_CALL")

    # Real project GIL records, cloned ONLY into a disposable test directory.
    original = ROOT / "data/codex-main-street/knights-rebuild/upper-stair-wall-repair/backups/1073741846.gil"
    if not original.exists():
        # Portable package excludes personal saves. Empty container fixtures still test identity contracts.
        original = None
    test_root = ROOT / ".runtime/ai-workbench-validation"
    test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="case-", dir=test_root) as tmp:
        folder = Path(tmp)
        assert folder.resolve().is_relative_to(test_root.resolve())
        if original:
            container = saved.gc.decode_container(original.read_bytes())
            original_sha = api.sha(original)
            fields = [f for f in saved.gc.parse_fields(container.payload) if f.number != saved.gc.LEVEL_FIELD_ID]
            payload = saved.gc.encode_fields(fields)
        else:
            payload = b"\x12\x07fixture"  # field 2: level name
            container = saved.gc.Container(subtype=2, payload=payload)
        handles = []
        for level in (1073741901, 1073741902):
            path = folder / f"save{level}.gil"
            path.write_bytes(saved.gc.encode_container(dataclasses.replace(container, payload=payload)))
            opened = call("context.open", {"save": str(path), "level_id": level})
            handles.append(opened["context"])
            check("context_actual_save_" + str(level), opened["ok"] and opened["levelId"] == level
                  and opened["identityEvidence"] == "formal-filename-no-embedded-id")
            check("context_instances_" + str(level), call("context.instances", {"context": opened["context"], "limit": 2})["ok"])
            check("context_independent_readback_" + str(level),
                  call("context.readback", {"context": opened["context"]})["saveChanged"] is False)
        check("cross_save_contexts_distinct", len(set(handles)) == 2)
        refuses("wrong_save_level_refused", lambda: call("context.open", {
            "save": str(folder / "save1073741901.gil"), "level_id": 1073741902}), "FORMAL_FILENAME")
        ctxdir, ctx = contexts.load(api, handles[0])
        read_only = contexts.bound_arguments(api, ctx, registry["saved.inspect"], {}, "sample")
        check("portable_arguments_use_current_level", read_only["level_id"] == 1073741901
              and read_only["gil"].endswith("save1073741901.gil"))
        refuses("foreign_level_argument_refused", lambda: contexts.bound_arguments(
            api, ctx, registry["saved.inspect"], {"level_id": 1073741902}, "sample"), "CONTEXT_ARGUMENT_CONFLICT")
        refuses("native_off_by_default", lambda: call("context.call", {
            "context": handles[0], "tool": "scene.inspect", "arguments": {}, "operation_id": "blocked"}),
            "NATIVE_REQUIRES")
        selected = [e["entityId"] for e in saved.snapshot(ctx["save"], ctx["levelId"])["entities"][:2]]
        owner = call("context.ownership", {"context": handles[0], "entity_ids": selected})
        check("ownership_bound_to_actual_file", owner["document"]["saveSha256"] == api.sha(ctx["save"])
              and owner["document"]["levelId"] == ctx["levelId"])
        if selected:
            refuses("foreign_entity_selection", lambda: call("context.ownership", {
                "context": handles[0], "entity_ids": [4294967295]}), "OWNERSHIP_ENTITY")
        Path(ctx["save"]).write_bytes(Path(ctx["save"]).read_bytes() + b"x")
        refuses("external_save_drift_blocks_writes", lambda: contexts.load(api, handles[0]), "CONTEXT_SAVE_DRIFT")
        # Tests use their own contexts. Keep evidence, mark expired so fixtures cannot ever be used natively.
        for handle in handles:
            d = contexts.HOME / handle
            value = api.read(d / "context.json")
            value["expiresUtc"] = "2000-01-01T00:00:00+00:00"
            contexts.write(d / "context.json", value)
        refuses("expired_context_refused", lambda: contexts.load(api, handles[1]), "CONTEXT_EXPIRED")
        if original:
            check("original_save_unchanged", api.sha(original) == original_sha)
    # Simulated failure transport tests control flow, never substitutes for a game receipt.
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(prefix="workflow-", dir=test_root) as tmp:
        assert Path(tmp).resolve().is_relative_to(test_root.resolve())
        fake_save = Path(tmp) / "state.gil"
        fake_save.write_bytes(b"explicit offline failure fixture")
        fake_session = Path(tmp) / "session.json"
        fake_session.write_text('{"pid":999999999}', encoding="utf-8")
        identity = "f"*32
        fixture_home = Path(tmp) / "contexts"
        context_dir = fixture_home / identity
        from datetime import timedelta
        context = {"save":str(fake_save),"saveSha256":api.sha(fake_save),"levelId":1073741901,
                   "session":str(fake_session),"sessionSha256":api.sha(fake_session),
                   "queue":str(Path(tmp)/"queue"),"nativeEnabled":True,
                   "expiresUtc":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        contexts.write(context_dir / "context.json",context)
        used = []
        def failing_transport(tool,args,**kwargs):
            used.append(tool["name"])
            return {"ok":False,"outcomeUncertain":True,"error":"simulated transport timeout"}
        args = {"context":identity,"operation_id":"failure_case",
                "placements":api.read(DATA / "examples/scene-plan.json")["placements"]}
        with patch.object(contexts,"HOME",fixture_home), patch.object(api,"RUNTIME",Path(tmp)/"runtime"), \
                patch.object(api,"execute_tool",failing_transport):
            first = operations.invoke(api,"scene.apply",args)
            again = operations.invoke(api,"scene.apply",args)
            check("simulated_timeout_stops_before_any_write", used == ["scene.inspect"] and not first["ok"])
            check("simulated_unknown_outcome_keeps_lock",operations.writer_path(api,context).exists())
            check("simulated_same_operation_returns_receipt", again.get("redispatched") is False and len(used)==1)
    own = subprocess.run([sys.executable,"-B","-X","utf8",str(ROOT/"tools/entity-transform/validate_ownership_contract.py")],
                          cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=60)
    own_report = json.loads(own.stdout) if own.stdout.strip().startswith("{") else {}
    check("portable_ownership_positive_and_negative_cases",own.returncode==0 and own_report.get("ok"),
          own_report or own.stderr[-1200:])
    import helper_cli
    refuses("helper_deadline_not_extended",lambda:helper_cli.remaining_minutes("2000-01-01T00:00:00Z"),"DEADLINE")
    check("implicit_transport_classified_native",registry["transform.prepare"]["nativePossible"] and
          registry["asset.sequence_run"]["nativePossible"])
    # MCP uses the actual executable, from outside the repo working directory.
    requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "knowledge.search", "arguments": {"query": "拼接", "limit": 1}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "context.open", "arguments": {"level_id": True}}}]
    command = [sys.executable, "-B", "-X", "utf8", str(ROOT / "ai.py"), "serve"]
    process = subprocess.run(command, input="\n".join(json.dumps(x) for x in requests)+"\n",
                             text=True, capture_output=True, encoding="utf-8", cwd=test_root, timeout=60)
    replies = [json.loads(x) for x in process.stdout.splitlines()]
    check("mcp_stdio_real_process", process.returncode == 0 and len(replies) == 4, process.stderr[-1000:])
    check("compact_discovery_no_giant_registry", len(replies[1]["result"]["tools"]) == len(api.BUILTINS)
          and len(api.BUILTINS) < 40)
    check("mcp_query_and_error", not replies[2]["result"]["isError"] and replies[3]["result"]["isError"])
    report = {"ok": all(c["ok"] for c in checks), "atUtc": datetime.now(timezone.utc).isoformat(),
              "checks": checks, "passed": sum(c["ok"] for c in checks), "total": len(checks),
              "command": "python -B -X utf8 tools/miliastra-toolkit/validate_workbench.py",
              "exitCode": 0 if all(c["ok"] for c in checks) else 1,
              "nativeCalled": False, "scope": "offline-context-index-schema-and-MCP",
              "runtimeVerified": False, "seconds": round(time.monotonic()-start, 3)}
    (DATA / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report["exitCode"]


if __name__ == "__main__":
    raise SystemExit(main())
