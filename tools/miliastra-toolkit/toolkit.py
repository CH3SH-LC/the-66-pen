"""AI tools for the real Miliastra CLI surface. JSON CLI and MCP stdio transport."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import compile_inputs
import knowledge
import contexts
import operations

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = ROOT / "data/miliastra-toolkit"
RUNTIME = ROOT / ".runtime/miliastra-toolkit"
PROTECTED = set(range(1073741835, 1073741845))
READ_PATH_NAMES = {
    "session", "baseline", "review", "plan", "plan_file", "values_file", "save", "gil", "edits",
    "spec", "batch", "inspection", "save_run", "after", "before_run", "after_run", "queries",
    "catalog_run", "points", "fixture", "compiled", "previous_run", "target_baseline",
    "input_baseline", "ui_baseline", "request", "inspection_run", "run", "catalog", "manifest",
    "ids", "definitions", "target_gil", "reviewed_source_sets", "backup", "ownership", "baseline_run",
}
WRITE_PATH_NAMES = {"out", "output", "output_dir", "out_dir", "queue_dir", "queue", "elevated_queue"}


class ToolError(ValueError):
    pass


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(value, schema, at="$"):
    if "allOf" in schema:
        for part in schema["allOf"]:
            validate(value, part, at)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            passed = 0
            for part in schema[keyword]:
                try:
                    validate(value, part, at)
                    passed += 1
                except ToolError:
                    pass
            if passed == 0 or (keyword == "oneOf" and passed != 1):
                raise ToolError(f"SCHEMA_{keyword}:{at}")
    if "not" in schema:
        try:
            validate(value, schema["not"], at)
        except ToolError:
            pass
        else:
            raise ToolError(f"SCHEMA_NOT:{at}")
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in types and type(value) is not types[kind]:
        raise ToolError(f"SCHEMA_TYPE:{at}:expected {kind}")
    if kind == "number" and (type(value) not in (int, float) or not math.isfinite(value)):
        raise ToolError(f"SCHEMA_FINITE_NUMBER:{at}")
    if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
        raise ToolError(f"SCHEMA_ENUM:{at}")
    if type(value) in (int, float):
        if not math.isfinite(value):
            raise ToolError(f"SCHEMA_NONFINITE:{at}")
        if "minimum" in schema and value < schema["minimum"]:
            raise ToolError(f"SCHEMA_MINIMUM:{at}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ToolError(f"SCHEMA_MAXIMUM:{at}")
    if isinstance(value, str):
        if "\0" in value:
            raise ToolError(f"SCHEMA_NUL:{at}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ToolError(f"SCHEMA_PATTERN:{at}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ToolError(f"SCHEMA_MIN_LENGTH:{at}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ToolError(f"SCHEMA_MAX_LENGTH:{at}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 100000):
            raise ToolError(f"SCHEMA_ARRAY_LENGTH:{at}")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{at}[{index}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ToolError(f"SCHEMA_REQUIRED:{at}.{key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise ToolError(f"SCHEMA_UNKNOWN_FIELDS:{at}:{','.join(sorted(set(value)-set(props)))}")
        for key, item in value.items():
            if key in props:
                validate(item, props[key], f"{at}.{key}")


def obj(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


STRING = {"type": "string"}
KIND = {"type": "string", "enum": ["entity", "node", "node_contract", "enum", "map",
        "map_document", "gameplay", "capability", "tool", "prefab_resource", "recipe"]}
BUILTINS = {
    "scene.plan": ("Validate structured placements through the production scene API and store a real immutable batch plan.",
                   compile_inputs.SCHEMAS["scene.plan"]),
    "graph.compile": ("Compile typed nodes, edges and tagged values against exact node variants into a real authoring batch.",
                      compile_inputs.SCHEMAS["graph.compile"]),
    "evidence.read": ("Read bounded JSON evidence under project runtime/data, optionally selecting a JSON Pointer.",
        obj({"path": STRING, "pointer": STRING, "offset": {"type": "integer", "minimum": 0},
             "limit": {"type": "integer", "minimum": 1, "maximum": 500},
             "max_chars": {"type": "integer", "minimum": 1000, "maximum": 262144}}, ("path",))),
    "catalog.stats": ("Read database counts, evidence boundaries, and source manifest.", obj()),
    "catalog.search": ("Search all imported evidence; exact IDs are never selected by name silently.",
        obj({"query": STRING, "kind": KIND, "category": STRING, "offset": {"type": "integer", "minimum": 0},
             "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, ("query",))),
    "catalog.get": ("Get a record and its source hash. A node numeric ID requires graph_kind.",
        obj({"kind": KIND, "id": STRING, "graph_kind": {"type": "integer"}}, ("kind", "id"))),
    "catalog.verify_sources": ("Hash every imported source to detect drift; never contacts the game.", obj()),
    "catalog.resolve_entity": ("Resolve an exact template ID or unique exact name; ambiguous names fail.",
        obj({"template_id": {"type": "integer", "minimum": 1}, "name": STRING})),
    "tool.describe": ("Read the exact executable tool schema and native evidence limits.",
        obj({"name": STRING}, ("name",))),
    "tool.call": ("Call one named tool using its exact schema from tool.describe. Same guards as direct CLI.",
        obj({"name": STRING, "arguments": {"type": "object"}}, ("name", "arguments"))),
    "recipe.plan": ("Resolve a reusable recipe against explicit inputs; never dispatch.",
        obj({"recipe": STRING, "inputs": {"type": "object"}}, ("recipe", "inputs"))),
    "recipe.dispatch": ("Execute recipe steps against real tools, stop at first failure; never fabricate receipts.",
        obj({"recipe": STRING, "inputs": {"type": "object"}, "operation_id": {
             "type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}}, ("recipe", "inputs", "operation_id"))),
}


BUILTINS.update(knowledge.schema(obj, STRING))
BUILTINS.update(contexts.schemas(obj, STRING))
BUILTINS.update(operations.schemas(obj, STRING))


def registry():
    data = read(DATA / "tools.json")
    return {item["name"]: item for item in data["tools"]}


def db():
    connection = sqlite3.connect((DATA / "catalog.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def catalog_call(name, args):
    with db() as connection:
        if name == "catalog.stats":
            return {"ok": True, **json.loads(connection.execute("SELECT value FROM metadata WHERE key='build'").fetchone()[0]),
                    "databaseSha256": sha(DATA / "catalog.sqlite")}
        if name == "catalog.verify_sources":
            checks = []
            for row in connection.execute("SELECT * FROM sources ORDER BY path"):
                path = ROOT / row["path"]
                actual = sha(path) if path.is_file() else None
                checks.append({"path": row["path"], "expected": row["sha256"], "actual": actual, "matches": actual == row["sha256"]})
            return {"ok": all(x["matches"] for x in checks), "checked": len(checks),
                    "mismatches": [x for x in checks if not x["matches"]], "nativeCalled": False}
        if name == "catalog.resolve_entity":
            if ("template_id" in args) == ("name" in args):
                raise ToolError("RESOLVE_EXACTLY_ONE_ID_OR_NAME")
            column, value = ("template_id", args["template_id"]) if "template_id" in args else ("name", args["name"])
            rows = list(connection.execute(f"SELECT template_id,name,payload FROM entities WHERE {column}=?", (value,)))
            if len(rows) != 1:
                return {"ok": False, "error": "AMBIGUOUS_TEMPLATE_UNRESOLVED" if rows else "ENTITY_NOT_FOUND",
                        "matches": [{"templateId": r["template_id"], "name": r["name"]} for r in rows]}
            return {"ok": True, "entity": json.loads(rows[0]["payload"])}
        if name == "catalog.get":
            kind, identity = args["kind"], args["id"]
            if kind == "node" and identity.isdigit():
                if "graph_kind" not in args:
                    raise ToolError("NODE_GRAPH_KIND_REQUIRED")
                rows = list(connection.execute("SELECT stable_key FROM nodes WHERE definition_id=? AND graph_kind=?",
                                               (int(identity), args["graph_kind"])))
                if len(rows) != 1:
                    raise ToolError("NODE_IDENTITY_AMBIGUOUS_OR_MISSING")
                identity = rows[0][0]
            row = connection.execute("SELECT r.*,s.sha256 FROM records r JOIN sources s ON r.source=s.path WHERE kind=? AND id=?",
                                     (kind, identity)).fetchone()
            if row is None:
                raise ToolError("RECORD_NOT_FOUND")
            return {"ok": True, "kind": kind, "id": identity, "record": json.loads(row["payload"]),
                    "source": {"path": row["source"], "sha256": row["sha256"]}}
        where, values = ["search_text LIKE ? ESCAPE '\\'"], ["%" + args["query"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"]
        for key in ("kind", "category"):
            if key in args:
                where.append(key + "=?")
                values.append(args[key])
        condition = " AND ".join(where)
        total = connection.execute("SELECT count(*) FROM records WHERE " + condition, values).fetchone()[0]
        rows = connection.execute("SELECT kind,id,name,category,source FROM records WHERE " + condition +
                                  " ORDER BY kind,id LIMIT ? OFFSET ?", values + [args.get("limit", 20), args.get("offset", 0)])
        return {"ok": True, "total": total, "offset": args.get("offset", 0), "results": [dict(row) for row in rows]}


def project_path(value, *, write=False):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if write and not path.is_relative_to(ROOT):
        raise ToolError("OUTPUT_OUTSIDE_PROJECT:" + str(path))
    if write and (path == ROOT or any(x in {".git", ".codex", ".agents"} for x in path.relative_to(ROOT).parts)):
        raise ToolError("PROTECTED_OUTPUT_PATH:" + str(path))
    if write and not any(path.is_relative_to(ROOT / directory) for directory in (".runtime", "data")):
        raise ToolError("OUTPUT_MUST_BE_PROJECT_RUNTIME_OR_DATA:" + str(path))
    return str(path)


def evidence_read(args):
    path = Path(project_path(args["path"]))
    if not any(path.is_relative_to(ROOT / directory) for directory in (".runtime", "data")):
        raise ToolError("EVIDENCE_OUTSIDE_PROJECT_RUNTIME_OR_DATA")
    if path.suffix.lower() != ".json" or path.stat().st_size > 64 * 1024 * 1024:
        raise ToolError("EVIDENCE_REQUIRES_JSON_UNDER_64_MIB")
    before = sha(path)
    value = read(path)
    pointer = args.get("pointer", "")
    if pointer:
        if not pointer.startswith("/"):
            raise ToolError("JSON_POINTER_MUST_START_WITH_SLASH")
        for token in pointer[1:].split("/"):
            if re.search(r"~(?![01])", token):
                raise ToolError("INVALID_JSON_POINTER_ESCAPE")
            key = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and int(key) < len(value):
                value = value[int(key)]
            else:
                raise ToolError("EVIDENCE_POINTER_NOT_FOUND")
    total = len(value) if isinstance(value, list) else None
    if isinstance(value, list):
        offset = args.get("offset", 0)
        value = value[offset:offset + args.get("limit", 100)]
    elif "offset" in args or "limit" in args:
        raise ToolError("EVIDENCE_PAGING_REQUIRES_ARRAY")
    encoded = compact(value)
    if len(encoded) > args.get("max_chars", 64000):
        raise ToolError("EVIDENCE_TOO_LARGE_SELECT_POINTER_OR_SMALLER_PAGE")
    if sha(path) != before:
        raise ToolError("EVIDENCE_CHANGED_DURING_READ")
    return {"ok": True, "path": str(path), "sha256": before, "pointer": pointer, "value": value,
            "arrayTotal": total, "offset": args.get("offset", 0) if total is not None else None,
            "nativeCalled": False, "runtimeVerified": False}


def argv_for(tool, args):
    validate(args, tool["inputSchema"])
    options = {option["name"]: option for option in tool["options"]}
    for group in tool["mutuallyExclusive"]:
        active = []
        for name in group["names"]:
            if name not in args:
                continue
            mode = options[name]["mode"]
            if (mode == "true" and args[name] is False) or (mode == "false" and args[name] is True):
                continue
            active.append(name)
        if len(active) > 1 or (group["required"] and len(active) != 1):
            raise ToolError("ARGUMENT_GROUP_ACTIVE_CHOICE_REQUIRED:" + ",".join(group["names"]))
    source = verify_tool_code(tool)
    if args.get("direct_elevated"):
        raise ToolError("USE_EXISTING_ELEVATED_QUEUE")
    # Do not expose caller-selected interpreters / arbitrary executable injection.
    if "python" in args and Path(args["python"]).resolve() != Path(sys.executable).resolve():
        raise ToolError("INTERPRETER_OVERRIDE_REFUSED")
    if tool["mutating"]:
        for key in ("level_id", "target_level"):
            if args.get(key) in PROTECTED:
                raise ToolError("PROTECTED_LEVEL:" + str(args[key]))
    if tool["invocation"].startswith("module:"):
        argv = [sys.executable, "-X", "utf8", "-B", "-m", tool["invocation"][7:]]
    else:
        argv = [sys.executable, "-X", "utf8", "-B", str(source)]
    for depth in range(len(tool["command"]) + 1):
        for option in tool["options"]:
            key = option["name"]
            if option["depth"] != depth or key not in args:
                continue
            value = args[key]
            if option["mode"] == "true":
                if value:
                    argv.append(option["flag"])
                continue
            if option["mode"] == "false":
                if value is False:
                    argv.append(option["flag"])
                continue
            is_path = option["path"] or key in READ_PATH_NAMES or key in WRITE_PATH_NAMES
            def render(v):
                if isinstance(v, list):
                    return [render(x)[0] for x in v]
                return [project_path(v, write=key in WRITE_PATH_NAMES) if is_path else str(v)]
            if option["mode"] == "append":
                for item in value:
                    if option["flag"]:
                        argv.append(option["flag"])
                    argv.extend(render(item))
            else:
                if option["flag"]:
                    argv.append(option["flag"])
                argv.extend(render(value))
        if depth < len(tool["command"]):
            argv.append(tool["command"][depth])
    return argv


def verify_tool_code(tool):
    source = ROOT / tool["source"]
    if not source.is_file() or sha(source) != tool["sourceSha256"]:
        raise ToolError("TOOL_SOURCE_DRIFT_REBUILD_REGISTRY:" + tool["source"])
    for dependency in tool.get("codeDependencies", []):
        dep_path = ROOT / dependency["path"]
        if not dep_path.is_file() or sha(dep_path) != dependency["sha256"]:
            raise ToolError("TOOL_DEPENDENCY_DRIFT_REBUILD_REGISTRY:" + dependency["path"])
    return source


def parse_stdout(text):
    try:
        return json.loads(text)
    except ValueError:
        for line in reversed(text.splitlines()):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def execute_tool(tool, args, *, plan=False):
    args = {**tool.get("forcedDefaults", {}), **args}
    argv = argv_for(tool, args)
    if plan:
        return {"ok": True, "mode": "plan", "tool": tool["name"], "argv": argv,
                "nativeCalled": False, "runtimeVerified": False}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    fingerprint_args = {k: v for k, v in args.items() if k not in ("_operation_id", "_timeout_seconds")}
    fingerprint = hashlib.sha256(compact({"tool": tool["name"], "arguments": fingerprint_args,
                                         "sourceSha256": tool["sourceSha256"]}).encode()).hexdigest()
    operation = args.get("_operation_id")
    folder = None
    if tool["mutating"]:
        folder = RUNTIME / "operations" / operation
        folder.parent.mkdir(exist_ok=True)
        try:
            folder.mkdir()
        except FileExistsError:
            claim = read(folder / "claim.json") if (folder / "claim.json").is_file() else {}
            if claim.get("fingerprint") != fingerprint:
                raise ToolError("OPERATION_ID_CONFLICT")
            if (folder / "result.json").is_file():
                return dict(read(folder / "result.json"), replayedReceipt=True, redispatched=False)
            return {"ok": False, "error": "OPERATION_ALREADY_CLAIMED_OUTCOME_UNKNOWN",
                    "outcomeUncertain": True, "replayForbidden": True, "operationId": operation}
        claim = {"tool": tool["name"], "fingerprint": fingerprint, "argv": argv,
                 "atUtc": datetime.now(timezone.utc).isoformat(), "operationId": operation}
        (folder / "claim.json").write_text(compact(claim), encoding="utf-8")
        # Identical writes under a new identity must not silently retry uncertain work.
        dedup = RUNTIME / "fingerprints"
        dedup.mkdir(exist_ok=True)
        try:
            with (dedup / (fingerprint + ".json")).open("x", encoding="utf-8") as handle:
                handle.write(compact({"operationId": operation}))
        except FileExistsError:
            prior = read(dedup / (fingerprint + ".json"))
            result = {"ok": False, "error": "IDENTICAL_WRITE_ALREADY_CLAIMED", "previousOperation": prior["operationId"],
                      "outcomeUncertain": True, "replayForbidden": True, "nativeCalled": False}
            (folder / "result.json").write_text(compact(result), encoding="utf-8")
            return result
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        process = subprocess.run(argv, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace",
                                 env=env, timeout=args.get("_timeout_seconds", 300),
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        parsed = parse_stdout(process.stdout)
        ok = process.returncode == 0 and not (isinstance(parsed, dict) and parsed.get("ok") is False)
        called = parsed.get("called", parsed.get("nativeCalled", "unknown")) if isinstance(parsed, dict) else "unknown"
        uncertain = parsed.get("outcomeUncertain") if isinstance(parsed, dict) else None
        if uncertain is None:
            uncertain = bool(not ok and tool["nativePossible"] and called is not False)
        result = {"ok": ok, "tool": tool["name"], "exitCode": process.returncode,
                  "commandExecuted": True, "result": parsed,
                  "nativeCalled": called,
                  "runtimeVerified": False,
                  "stdout": process.stdout if parsed is None else None,
                  "stderr": process.stderr or None,
                  "outcomeUncertain": uncertain,
                  "operationId": operation, "replayForbidden": bool(tool["mutating"])}
    except subprocess.TimeoutExpired as exc:
        result = {"ok": False, "error": "TOOL_TIMEOUT", "tool": tool["name"],
                  "commandExecuted": True, "nativeCalled": "unknown",
                  "outcomeUncertain": tool["nativePossible"], "replayForbidden": True,
                  "operationId": operation}
    except OSError as exc:
        result = {"ok": False, "error": str(exc), "tool": tool["name"], "commandExecuted": False,
                  "nativeCalled": False, "outcomeUncertain": False, "operationId": operation}
    if folder:
        (folder / "result.json").write_text(compact(result), encoding="utf-8")
        result["receipt"] = str(folder / "result.json")
    return result


def resolve_refs(value, inputs, steps, *, planning=False):
    if isinstance(value, list):
        return [resolve_refs(v, inputs, steps, planning=planning) for v in value]
    if isinstance(value, dict):
        if set(value) == {"$path"}:
            parts = resolve_refs(value["$path"], inputs, steps, planning=planning)
            if not isinstance(parts, list) or not all(isinstance(part, str) for part in parts):
                raise ToolError("RECIPE_PATH_PARTS_MUST_BE_STRINGS")
            return str(Path(*parts))
        if set(value) == {"$input"}:
            if value["$input"] not in inputs:
                raise ToolError("RECIPE_INPUT_MISSING:" + value["$input"])
            return inputs[value["$input"]]
        if set(value) == {"$step"}:
            keys = value["$step"].split(".")
            if planning and keys[0] not in steps:
                return {"unresolvedResultReference": value["$step"]}
            current = steps
            for key in keys:
                if not isinstance(current, dict) or key not in current:
                    if planning:
                        return {"unresolvedResultReference": value["$step"]}
                    raise ToolError("RECIPE_RESULT_REFERENCE_MISSING:" + value["$step"])
                current = current[key]
            return current
        return {k: resolve_refs(v, inputs, steps, planning=planning) for k, v in value.items()}
    return value


def recipe_call(args, *, plan):
    recipe_path = Path(project_path(args["recipe"]))
    recipe = read(recipe_path)
    validate(args["inputs"], recipe["inputSchema"])
    tools = registry()
    identifiers = [step.get("id") for step in recipe["steps"]]
    if len(set(identifiers)) != len(identifiers) or not all(
            isinstance(s, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", s) for s in identifiers):
        raise ToolError("RECIPE_INVALID_OR_DUPLICATE_STEP_ID")
    for step in recipe["steps"]:
        if step["tool"].startswith("recipe."):
            raise ToolError("NESTED_RECIPES_REQUIRE_EXPLICIT_FLATTENING")
        if step["tool"] not in tools and step["tool"] not in BUILTINS:
            raise ToolError("RECIPE_UNKNOWN_TOOL:" + step["tool"])
    folder = None
    if not plan:
        folder = RUNTIME / "recipes" / args["operation_id"]
        fingerprint = hashlib.sha256(compact({"recipeSha256": sha(recipe_path), "inputs": args["inputs"]}).encode()).hexdigest()
        folder.parent.mkdir(parents=True, exist_ok=True)
        try:
            folder.mkdir()
        except FileExistsError:
            claim = read(folder / "claim.json") if (folder / "claim.json").is_file() else {}
            if claim.get("fingerprint") != fingerprint:
                raise ToolError("RECIPE_OPERATION_ID_CONFLICT")
            if (folder / "result.json").is_file():
                return dict(read(folder / "result.json"), replayedReceipt=True, redispatched=False)
            return {"ok": False, "error": "RECIPE_ALREADY_CLAIMED_OUTCOME_UNKNOWN",
                    "outcomeUncertain": True, "replayForbidden": True}
        (folder / "claim.json").write_text(compact({"fingerprint": fingerprint, "recipe": str(recipe_path)}), encoding="utf-8")
    def finish(result):
        if folder:
            (folder / "result.json").write_text(compact(result), encoding="utf-8")
            result["receipt"] = str(folder / "result.json")
        return result
    completed, results = {}, []
    seen = set()
    for item in recipe["steps"]:
        if item["id"] in seen:
            raise ToolError("RECIPE_DUPLICATE_STEP_ID")
        seen.add(item["id"])
        tool = tools.get(item["tool"])
        if tool is None and item["tool"] not in BUILTINS:
            raise ToolError("RECIPE_UNKNOWN_TOOL:" + item["tool"])
        try:
            resolved = resolve_refs(item["arguments"], args["inputs"], completed, planning=plan)
            if tool and tool["mutating"]:
                operation_prefix = args.get("operation_id", "plan")
                operation_suffix = hashlib.sha256((operation_prefix + ":" + item["id"]).encode()).hexdigest()[:16]
                resolved.setdefault("_operation_id", operation_prefix[:40] + "_" + item["id"][:20] + "_" + operation_suffix)
            if plan and "unresolvedResultReference" in compact(resolved):
                result = {"ok": True, "mode": "plan", "arguments": resolved, "unresolved": True, "nativeCalled": False}
            else:
                result = invoke(item["tool"], resolved, plan=plan)
        except ToolError as exc:
            result = {"ok": False, "error": str(exc), "nativeCalled": False, "commandExecuted": False}
        except (OSError, ValueError, KeyError) as exc:
            result = {"ok": False, "error": str(exc), "nativeCalled": "unknown",
                      "outcomeUncertain": bool(tool and tool["nativePossible"]), "replayForbidden": True}
        results.append({"id": item["id"], "tool": item["tool"], "output": result})
        completed[item["id"]] = result
        if not result.get("ok"):
            return finish({"ok": False, "mode": "plan" if plan else "execute", "stoppedAt": item["id"],
                           "steps": results, "remainingStepsExecuted": False, "runtimeVerified": False})
    return finish({"ok": True, "mode": "plan" if plan else "execute", "steps": results,
                   "runtimeVerified": False, "recipeSha256": sha(recipe_path)})


def invoke(name, args, *, plan=False):
    if name in BUILTINS:
        validate(args, BUILTINS[name][1])
        if name == "tool.call":
            if args["name"] == "tool.call":
                raise ToolError("RECURSIVE_TOOL_CALL")
            return invoke(args["name"], args["arguments"], plan=plan)
        if name.startswith("knowledge."):
            return knowledge.invoke(sys.modules[__name__], name, args, plan=plan)
        if name.startswith("context."):
            return contexts.invoke(sys.modules[__name__], name, args, plan=plan)
        if name in operations.schemas(obj, STRING):
            return operations.invoke(sys.modules[__name__], name, args, plan=plan)
        if name in compile_inputs.SCHEMAS:
            return compile_inputs.invoke(sys.modules[__name__], name, args, plan=plan)
        if name == "evidence.read":
            return evidence_read(args)
        if name.startswith("catalog."):
            return catalog_call(name, args)
        if name == "tool.describe":
            tools = registry()
            if args["name"] in BUILTINS:
                d, schema = BUILTINS[args["name"]]
                return {"ok": True, "tool": {"name": args["name"], "description": d, "inputSchema": schema}}
            if args["name"] not in tools:
                raise ToolError("UNKNOWN_TOOL")
            return {"ok": True, "tool": tools[args["name"]]}
        return recipe_call(args, plan=plan or name == "recipe.plan")
    tools = registry()
    if name not in tools:
        raise ToolError("UNKNOWN_TOOL:" + name)
    return execute_tool(tools[name], args, plan=plan)


def tool_list():
    tools = [{"name": name, "description": text, "inputSchema": schema,
              "annotations": {"readOnlyHint": name not in ("recipe.dispatch", "scene.plan", "graph.compile",
                  "context.open", "context.ownership", "context.call", "context.readback", "scene.apply", "tool.call"), "openWorldHint": False}}
             for name, (text, schema) in BUILTINS.items()]
    tools.extend({"name": t["name"], "description": t["description"],
                  "inputSchema": t["inputSchema"],
                  "annotations": {"readOnlyHint": not t["mutating"], "destructiveHint": t["mutating"],
                                  "idempotentHint": False, "openWorldHint": False}}
                 for t in registry().values())
    return tools


def serve(compact_tools=False):
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            method = request.get("method")
            if "id" not in request:
                continue
            if method == "initialize":
                result = {"protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "miliastra-toolkit", "version": "1.0.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t for t in tool_list() if not compact_tools or t["name"] in BUILTINS]}
            elif method == "tools/call":
                p = request["params"]
                try:
                    value = invoke(p["name"], p.get("arguments", {}))
                except ToolError as exc:
                    value = {"ok": False, "error": str(exc), "nativeCalled": False}
                except Exception as exc:
                    value = {"ok": False, "error": str(exc), "nativeCalled": "unknown",
                             "outcomeUncertain": True, "replayForbidden": True}
                result = {"content": [{"type": "text", "text": compact(value)}], "isError": not value.get("ok", False)}
            else:
                raise ToolError("METHOD_NOT_FOUND")
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(locals().get("request"), dict) else None,
                        "error": {"code": -32602, "message": str(exc)}}
        print(compact(response), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve").add_argument("--compact", action="store_true",
        help="Expose a small routing surface; tool.describe/tool.call retain the complete registry")
    sub.add_parser("list")
    for name in ("dispatch", "plan"):
        p = sub.add_parser(name)
        p.add_argument("tool")
        q = p.add_mutually_exclusive_group()
        q.add_argument("--json")
        q.add_argument("--file")
    p = sub.add_parser("describe")
    p.add_argument("tool")
    args = parser.parse_args()
    try:
        if args.command == "serve":
            serve(args.compact)
            return 0
        if args.command == "list":
            result = {"ok": True, "tools": tool_list()}
        elif args.command == "describe":
            result = invoke("tool.describe", {"name": args.tool})
        else:
            payload = read(project_path(args.file)) if args.file else json.loads(args.json or "{}")
            result = invoke(args.tool, payload, plan=args.command == "plan")
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if result.get("ok") else 1
    except ToolError as exc:
        print(compact({"ok": False, "error": str(exc), "nativeCalled": False}))
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(compact({"ok": False, "error": str(exc), "nativeCalled": "unknown",
                       "outcomeUncertain": True, "replayForbidden": True}))
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
