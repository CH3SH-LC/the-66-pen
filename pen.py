#!/usr/bin/env python3
"""千星奇域接口目录与工具入口。Python 3.11+，基础功能只用标准库。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VERSION = "0.2.0"
sys.path.insert(0, str(ROOT))
TOOLS = {
    "author": ("tools/authoring/author.py", "图创建、连线、常量、导出、绑定；需本机桥"),
    "scene": ("tools/game-executor/scene_cli.py", "实体创建、读取、保存；需匹配原生版本"),
    "bridge": ("tools/editor-bridge/elevated-request.py", "固定请求队列客户端；需已启动的提权 helper"),
    "terrain": ("tools/map-terrain/terrain_cli.py", "地形规划、准备和原生动作"),
    "transform": ("tools/entity-transform/cli.py", "已有实体位置、旋转、缩放"),
    "material": ("tools/entity-material/cli.py", "实体材质适配"),
    "properties": ("tools/template-properties/cli.py", "模板属性适配"),
    "properties-v2": ("tools/template-properties/v2/cli.py", "模板属性扩展"),
    "playtest": ("tools/playtest-control/cli.py", "试玩观测与受限控制"),
    "world-frame": ("tools/world-frame/cli.py", "坐标帧和地形量化"),
    "placement": ("tools/world-frame/placement_cli.py", "离线实体摆放坐标"),
    "version": ("tools/compatibility/version_guard.py", "磁盘版本身份检查"),
    "resource-decode": ("tools/editor-catalog/decode-mihoyobin.py", "解析用户提供的本地资源"),
}


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8-sig"))


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def catalog(query="", family=None, offset=0, limit=30, static=False):
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError("分页要求 offset >= 0，1 <= limit <= 200")
    rows = load("catalog/interfaces.json")["interfaces"]
    if static:
        rows += [dict(x, id="static." + x["name"], family="native-command")
                 for x in load("catalog/native-commands.json")["commands"]]
        rows += [dict(x, id="ui." + x["op_id"], name=x["name_zh"], family="user-operation")
                 for x in load("catalog/user-operations.json")["operations"]]
    rows = [x for x in rows if (not family or x["family"] == family)
            and query.casefold() in json.dumps(x, ensure_ascii=False).casefold()]
    return {"total": len(rows), "offset": offset, "limit": limit,
            "nextOffset": offset + limit if offset + limit < len(rows) else None,
            "items": rows[offset:offset + limit], "runtimeVerifiedThisRelease": False}


def codecs():
    sys.path.insert(0, str(ROOT / "tools/beyond-save"))
    return importlib.import_module("gil_container"), importlib.import_module("gia")


def inspect_file(path):
    p = Path(path).expanduser().resolve()
    if p.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("FILE_TOO_LARGE: 本入口最大 128 MiB")
    data = p.read_bytes()
    gc, gia = codecs()
    result = {"file": p.name, "bytes": len(data), "sha256": digest(data),
              "runtimeVerified": False, "writesPerformed": False}
    if p.suffix.lower() == ".gia":
        model = gia.decode_gia(data)
        result.update(kind=model.kind, subtype=model.subtype, name=model.name,
                      modelKind=model.model_kind, nodeCount=model.node_count,
                      entityCount=len(model.entities))
    else:
        container = gc.decode_container(data)
        fields = gc.parse_fields(container.payload)
        result.update(subtype=container.subtype, payloadBytes=len(container.payload),
                      fieldCounts=dict(sorted(Counter(x.number for x in fields).items())),
                      byteRoundtrip=gc.encode_container(container) == data,
                      protobufCanonicalRoundtrip=gc.encode_fields(fields) == container.payload)
        if container.subtype == gc.SUBTYPE_LEVEL:
            name_field = next((f for f in fields if f.number == 2 and f.wire_type == gc.WIRE_LENGTH), None)
            result.update(name=name_field.text() if name_field else None)
    return result


def file_diff(before, after):
    gc, _ = codecs()
    a, b = Path(before).read_bytes(), Path(after).read_bytes()
    ca, cb = gc.decode_container(a), gc.decode_container(b)
    def groups(c):
        result = {}
        for f in gc.parse_fields(c.payload):
            result.setdefault(f.number, []).append(gc.encode_fields([f]))
        return result
    ga, gb = groups(ca), groups(cb)
    return {"beforeSha256": digest(a), "afterSha256": digest(b), "changed": a != b,
            "subtypeChanged": ca.subtype != cb.subtype,
            "changedFields": [k for k in sorted(ga.keys() | gb.keys()) if ga.get(k) != gb.get(k)],
            "gameAccepted": False, "note": "字节变化证明文件变化；不能独自证明游戏已保存或接受。"}


def demo(out_dir):
    gc, _ = codecs()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Original synthetic example; no account/save material from any game.
    base = [gc.Field(2, gc.WIRE_LENGTH, data="the-66-pen 离线样本".encode()),
            gc.Field(100, gc.WIRE_VARINT, value=42),
            gc.Field(101, gc.WIRE_LENGTH, data=b"unknown-fields-preserved")]
    created = []
    for name, fields in [("before.gil", base), ("after.gil", base + [gc.Field(102, gc.WIRE_VARINT, value=7)])]:
        dest = out / name
        data = gc.encode_container(gc.Container(gc.SUBTYPE_LEVEL, gc.encode_fields(fields)))
        # Never overwrite an existing sample that could be user data.
        with dest.open("xb") as f:
            f.write(data)
        created.append(dest)
    return {"synthetic": True, "files": [inspect_file(p) for p in created],
            "diff": file_diff(*created), "gameContacted": False}


def doctor():
    required = ["catalog/interfaces.json", "data/node-workbench/catalog.json",
                "tools/beyond-save/gil_container.py", "tools/game-executor/native_profiles.py"]
    deps = {x: bool(shutil.which(x)) for x in ["dotnet", "powershell", "pwsh", "git"]}
    stats = load("data/node-workbench/catalog.json")["stats"]
    return {"version": VERSION, "python": platform.python_version(), "os": platform.system(),
            "offlineReady": sys.version_info >= (3, 11) and all((ROOT / p).is_file() for p in required),
            "missingFiles": [p for p in required if not (ROOT / p).is_file()],
            "optionalBuildTools": deps, "nodeCounts": {k: stats[k] for k in ["definitions", "variants", "ports", "enumGroups"]},
            "configuredGameDirectory": bool(os.environ.get("MILIASTRA_GAME_DIR")),
            "liveRuntimeChecked": False, "liveRuntimeReady": "unknown",
            "note": "doctor 不连接游戏；构建与实机环境配置见 docs/BUILD.md。"}


def node_call(arguments):
    return subprocess.call([sys.executable, "-X", "utf8", "-B", "-m", "tools.node_workbench", *arguments],
                           cwd=ROOT)


MCP_TOOLS = [
    {"name": "pen_catalog", "description": "检索当前接口实现及静态候选，返回源码和使用入口。",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"},
       "family": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"},
       "static": {"type": "boolean"}}, "additionalProperties": False}},
    {"name": "pen_nodes", "description": "按 graphKind 和 definitionId 读取真实节点类型、端口和调用配方；不调用游戏。",
     "inputSchema": {"type": "object", "properties": {"definition_id": {"type": "integer"},
       "graph_kind": {"type": "integer"}}, "required": ["definition_id", "graph_kind"], "additionalProperties": False}},
    {"name": "pen_inspect", "description": "只读解析用户指定的本地 GIL/GIP/GIA 文件。",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}},
       "required": ["path"], "additionalProperties": False}},
    {"name": "pen_doctor", "description": "离线检查发行包与可选编译依赖。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


def mcp_dispatch(req):
    method, params = req.get("method"), req.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "the-66-pen", "version": VERSION}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": MCP_TOOLS}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            if name == "pen_catalog":
                value = catalog(**args)
            elif name == "pen_inspect":
                value = inspect_file(**args)
            elif name == "pen_doctor":
                if args:
                    raise ValueError("不接受参数")
                value = doctor()
            elif name == "pen_nodes":
                from tools.node_workbench.catalog import Catalog
                from tools.node_workbench.recipes import recipe
                value = recipe(Catalog(), **args)
            else:
                raise ValueError("UNKNOWN_TOOL")
            return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}], "isError": False}
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    raise ValueError("METHOD_NOT_FOUND")


def serve():
    """MCP stdio JSON lines. stdout contains protocol messages only."""
    for line in sys.stdin:
        request = {}
        try:
            if len(line) > 1024 * 1024:
                raise ValueError("REQUEST_TOO_LARGE")
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("INVALID_REQUEST")
            if "id" not in request:
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": mcp_dispatch(request)}
        except (ValueError, TypeError, KeyError) as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32601 if str(exc) == "METHOD_NOT_FOUND" else -32602, "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "ai":
        return subprocess.call([sys.executable, "-B", "-X", "utf8", str(ROOT / "ai.py"), *arguments[1:]], cwd=ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    subs = parser.add_subparsers(dest="command", required=True)
    ai = subs.add_parser("ai", help="AI 工作台：status/search/route/describe/call/serve/build/verify")
    ai.add_argument("args", nargs=argparse.REMAINDER)
    c = subs.add_parser("catalog"); c.add_argument("query", nargs="?", default="")
    c.add_argument("--family"); c.add_argument("--static", action="store_true")
    c.add_argument("--offset", type=int, default=0); c.add_argument("--limit", type=int, default=30)
    subs.add_parser("doctor"); subs.add_parser("tools"); subs.add_parser("mcp")
    n = subs.add_parser("nodes"); n.add_argument("args", nargs=argparse.REMAINDER)
    t = subs.add_parser("tool"); t.add_argument("name", choices=list(TOOLS))
    t.add_argument("args", nargs=argparse.REMAINDER)
    f = subs.add_parser("inspect"); f.add_argument("path")
    d = subs.add_parser("diff"); d.add_argument("before"); d.add_argument("after")
    d = subs.add_parser("demo"); d.add_argument("--out", default=str(ROOT / ".runtime/demo"))
    a = parser.parse_args(argv)
    if a.command == "catalog":
        output(catalog(a.query, a.family, a.offset, a.limit, a.static))
    elif a.command == "doctor":
        output(doctor())
    elif a.command == "tools":
        output([{"name": k, "entry": v[0], "purpose": v[1]} for k, v in TOOLS.items()])
    elif a.command == "nodes":
        return node_call(a.args)
    elif a.command == "tool":
        script = ROOT / TOOLS[a.name][0]
        return subprocess.call([sys.executable, "-X", "utf8", "-B", str(script), *(a.args or ["--help"])], cwd=ROOT)
    elif a.command == "inspect":
        output(inspect_file(a.path))
    elif a.command == "diff":
        output(file_diff(a.before, a.after))
    elif a.command == "demo":
        output(demo(a.out))
    elif a.command == "mcp":
        serve()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        output({"ok": False, "error": str(exc)})
        raise SystemExit(2)
