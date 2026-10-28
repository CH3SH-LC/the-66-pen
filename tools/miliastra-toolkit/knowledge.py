"""Indexed AI knowledge, complete recipes and source inventories; no native calls."""
from pathlib import Path
import json
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/ai-workbench"


def schema(obj, string):
    page = {"offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100}}
    return {
        "knowledge.status": ("Read coverage, omissions and evidence limits without rescanning files.", obj()),
        "knowledge.search": ("Search assets, methods, tools, nodes, evidence and errors; default 20 results.",
            obj(dict(query=string, kind={"type": "string", "enum": [
                "file", "script", "method", "asset", "node", "error", "tool", "library"]}, **page), ("query",))),
        "knowledge.get": ("Get one indexed record by the exact id returned by search.",
            obj({"id": string}, ("id",))),
        "knowledge.read": ("Read bounded source lines from an indexed text file; detect source drift.",
            obj({"path": string, "start_line": {"type": "integer", "minimum": 1},
                 "line_count": {"type": "integer", "minimum": 1, "maximum": 200}}, ("path",))),
        "knowledge.node": ("Get the exact node variant and complete creation/port/value recipe.",
            obj({"definition_id": {"type": "integer"}, "graph_kind": {"type": "integer"},
                 "key": string})),
        "knowledge.route": ("Return a short executable route and required inputs for a task.",
            obj({"task": string}, ("task",))),
        "knowledge.errors": ("Look up an exact failure code and recovery steps; never auto-retry.",
            obj({"code": string}, ("code",))),
    }


def invoke(api, name, args, **_):
    if not (DATA / "knowledge.sqlite").is_file():
        raise api.ToolError("KNOWLEDGE_NOT_BUILT:python -B tools/miliastra-toolkit/build_knowledge.py")
    if name == "knowledge.status":
        return dict(api.read(DATA / "coverage.json"), ok=True, nativeCalled=False)
    if name == "knowledge.route":
        routes = api.read(DATA / "workflows.json")["routes"]
        query = args["task"].casefold()
        hits = [r for r in routes if query == r["id"] or
                any(s.casefold() in query or query in s.casefold() for s in r["keywords"])]
        return {"ok": bool(hits), "routes": hits,
                "available": [] if hits else [{"id": r["id"], "keywords": r["keywords"]} for r in routes],
                "nativeCalled": False}
    if name == "knowledge.errors":
        rules = api.read(DATA / "errors.json")
        hits = [x for x in rules if any(p in args["code"] for p in x["contains"])]
        return {"ok": True, "code": args["code"], "recovery": hits or [{
            "action": "保留原回执和操作 ID，使用 knowledge.search 查错误原文；结果不明时先读正式存档，不重新派发。",
            "retry": "never-automatically"}], "nativeCalled": False}
    with sqlite3.connect((DATA / "knowledge.sqlite").as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        if name == "knowledge.read":
            row = con.execute("SELECT payload FROM entries WHERE id=?", ("file:"+args["path"],)).fetchone()
            if row is None:
                raise api.ToolError("KNOWLEDGE_SOURCE_NOT_INDEXED")
            record = json.loads(row[0])
            path = (ROOT / record["path"]).resolve()
            if not path.is_relative_to(ROOT) or path.suffix not in {".py", ".ps1", ".cs", ".cpp", ".h", ".md", ".txt", ".json", ".jsonl", ".yaml", ".toml", ".csv"}:
                raise api.ToolError("KNOWLEDGE_TEXT_SOURCE_REQUIRED")
            if path.stat().st_size > 32*1024*1024:
                raise api.ToolError("KNOWLEDGE_USE_STRUCTURED_QUERY_FOR_LARGE_SOURCE")
            if record.get("sha256") and api.sha(path) != record["sha256"]:
                raise api.ToolError("KNOWLEDGE_SOURCE_DRIFT_REBUILD_INCREMENTAL")
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            start, count = args.get("start_line", 1), args.get("line_count", 80)
            return {"ok": True, "path": record["path"], "startLine": start,
                    "lines": lines[start-1:start-1+count], "totalLines": len(lines),
                    "nextLine": start+count if start+count <= len(lines) else None, "nativeCalled": False}
        if name == "knowledge.get":
            rows = list(con.execute("SELECT * FROM entries WHERE id=?", (args["id"],)))
        elif name == "knowledge.node":
            if args.get("key"):
                rows = list(con.execute("SELECT * FROM entries WHERE id=?", ("node:" + args["key"],)))
            else:
                if "definition_id" not in args or "graph_kind" not in args:
                    raise api.ToolError("NODE_GRAPH_KIND_AND_DEFINITION_REQUIRED")
                rows = list(con.execute("SELECT e.* FROM entries e JOIN node_keys n ON n.id=e.id "
                    "WHERE definition_id=? AND graph_kind=?", (args["definition_id"], args["graph_kind"])))
            if len(rows) != 1:
                return {"ok": False, "error": "NODE_VARIANT_AMBIGUOUS_OR_MISSING",
                        "matches": [{"id": r["id"], "name": r["name"]} for r in rows]}
        else:
            query = args["query"].strip()
            # Parameterized and literal substring search. Chinese requires no tokenizer.
            if not query or len(query) > 240:
                raise api.ToolError("SEARCH_QUERY_1_TO_240")
            terms = query.split()[:8]
            conditions = ["search LIKE ? ESCAPE '\\'" for _ in terms]
            parameters = ["%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                          for t in terms]
            if args.get("kind"):
                conditions.append("kind=?")
                parameters.append(args["kind"])
            where = " AND ".join(conditions)
            count = con.execute("SELECT count(*) FROM entries WHERE " + where, parameters).fetchone()[0]
            offset, limit = args.get("offset", 0), args.get("limit", 20)
            rows = con.execute("SELECT id,kind,name,source,summary FROM entries WHERE " + where +
                               " ORDER BY kind,id LIMIT ? OFFSET ?", parameters + [limit, offset]).fetchall()
            return {"ok": True, "total": count, "offset": offset, "results": [dict(r) for r in rows],
                    "nextOffset": offset + limit if offset + limit < count else None, "nativeCalled": False}
        if not rows:
            raise api.ToolError("KNOWLEDGE_RECORD_NOT_FOUND")
        return {"ok": True, "record": json.loads(rows[0]["payload"]), "source": rows[0]["source"],
                "nativeCalled": False}
