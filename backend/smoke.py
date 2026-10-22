"""backend.server 的真实 stdio 握手冒烟测试。

用官方 SDK 的 ``stdio_client`` + ``ClientSession`` 真起子进程、真握手、真调工具：

1. ``list_tools`` —— 确认七个工具都在，且没有多余的"万能工具"；
2. ``mw_backend_capabilities`` —— 确认资产工具 backend=file、bridge 工具 backend 不是 file、
   gameImport/save/playtest unavailable；
3. ``mw_catalog_search``（只读，limit=3）；
4. ``mw_asset_inspect``（只读，已存在的构建）；
5. ``mw_build_validate``（只读，同一构建）；
6. ``mw_ipc_discover``（只读，注册表 + 本机 TCP 状态）—— 确认 backend 标记与
   ``protocolVerified=false``（不要求当前 listenerPresent 为 false）；
7. ``mw_asset_inspect``（非法 buildId）—— 必须得到 isError=true。

**绝不调用 mw_asset_stage。** 真实落盘由主智能体单独执行。
共 6 次工具调用（上限 12）。

运行：``<工程根>/.runtime/mcp-venv/Scripts/python -m backend.smoke``
结果写 ``.runtime/backend/smoke.json``，退出码 0=全部通过。
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

BUILD_ID = "53a79be516909d96ec2268c3635594fa2c1ca707ec1a8be7d9f746443d7031fd"
INVALID_BUILD_ID = "0" * 64

OUT_PATH = REPO_ROOT / ".runtime" / "backend" / "smoke.json"

EXPECTED_TOOLS = {
    "mw_catalog_search",
    "mw_scene_build",
    "mw_asset_inspect",
    "mw_build_validate",
    "mw_asset_stage",
    "mw_ipc_discover",
    "mw_backend_capabilities",
}

FORBIDDEN_TOOL_SUBSTRINGS = ("shell", "exec", "eval", "generic", "raw", "call_method")

# 明确声明：本脚本不会触碰真实落盘。
NEVER_CALLED = ["mw_asset_stage"]


def _server_params() -> StdioServerParameters:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.server"],
        cwd=str(REPO_ROOT),  # 固定工程根为 cwd
        env=env,
    )


def _summary(result: Any) -> dict[str, Any]:
    """把一次工具调用压成可放进报告的形状，保留判断所需的字段。"""
    entry: dict[str, Any] = {"isError": bool(getattr(result, "isError", False))}

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        entry["structuredContent"] = structured
    if not entry["isError"]:
        return entry

    texts = [
        block.text
        for block in (getattr(result, "content", None) or [])
        if getattr(block, "type", None) == "text"
    ]
    entry["errorText"] = texts
    entry["errorCode"] = (
        (structured or {}).get("error", {}).get("code") if isinstance(structured, dict) else None
    )
    return entry


def _describe_exception(exc: BaseException, depth: int = 0) -> str:
    """摊平 ExceptionGroup/TaskGroup，让报告里能看到真正的根因。"""
    head = f"{'  ' * depth}{type(exc).__name__}: {exc}"
    parts = [head]
    for sub in getattr(exc, "exceptions", None) or ():
        parts.append(_describe_exception(sub, depth + 1))
    if exc.__cause__ is not None and not getattr(exc, "exceptions", None):
        parts.append(_describe_exception(exc.__cause__, depth + 1))
    return "\n".join(parts)


async def _run(session: ClientSession, checks: list[dict[str, Any]]) -> None:
    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # --- 1. list_tools --------------------------------------------------
    listed = await session.list_tools()
    names = sorted(tool.name for tool in listed.tools)
    check(
        "list_tools_exact_set",
        set(names) == EXPECTED_TOOLS,
        {"listed": names, "expected": sorted(EXPECTED_TOOLS)},
    )
    bad = [n for n in names if any(s in n.lower() for s in FORBIDDEN_TOOL_SUBSTRINGS)]
    check("no_generic_or_shell_tool_published", not bad, {"offending": bad})
    check(
        "game_import_tools_absent",
        not any(k in n for n in names for k in ("save", "playtest", "import")),
        {"listed": names},
    )
    check(
        "tools_have_descriptions",
        all(bool((t.description or "").strip()) for t in listed.tools),
        {"withoutDescription": [t.name for t in listed.tools if not (t.description or "").strip()]},
    )

    # --- 2. capabilities ------------------------------------------------
    caps = await session.call_tool("mw_backend_capabilities", {})
    check("capabilities_not_error", not caps.isError, None)
    body = caps.structuredContent if isinstance(caps.structuredContent, dict) else {}
    check("capabilities_backend_file", body.get("backend") == "file", body.get("backend"))
    check(
        "capabilities_transport_stdio_no_port",
        body.get("transport") == "stdio" and body.get("httpPort") is None,
        {"transport": body.get("transport"), "httpPort": body.get("httpPort")},
    )
    check(
        "capabilities_game_import_save_playtest_unavailable",
        all(
            (body.get("unavailable") or {}).get(k) == "unavailable"
            for k in ("gameImport", "save", "playtest")
        ),
        body.get("unavailable"),
    )
    tools_declared = {t.get("name"): t for t in (body.get("tools") or [])}
    asset_tool_names = [
        "mw_catalog_search",
        "mw_scene_build",
        "mw_asset_inspect",
        "mw_build_validate",
        "mw_asset_stage",
    ]
    by_backend = {n: t.get("backend") for n, t in tools_declared.items()}
    check(
        "capabilities_asset_tools_backend_file",
        all(tools_declared.get(n, {}).get("backend") == "file" for n in asset_tool_names),
        {n: tools_declared.get(n, {}).get("backend") for n in asset_tool_names},
    )
    check(
        "capabilities_not_all_tools_file",
        bool(tools_declared) and any(b != "file" for b in by_backend.values()),
        by_backend,
    )
    check(
        "capabilities_backends_map_distinguishes_bridge",
        (body.get("backends") or {}).get("assets") == "file"
        and (body.get("backends") or {}).get("staging") == "file"
        and (body.get("backends") or {}).get("bridge") == "windows-registry-and-tcp-state",
        body.get("backends"),
    )
    check(
        "capabilities_ipc_tool_backend_marker",
        tools_declared.get("mw_ipc_discover", {}).get("backend")
        == "windows-registry-and-tcp-state",
        tools_declared.get("mw_ipc_discover", {}).get("backend"),
    )
    check(
        "capabilities_stage_is_not_game_import",
        tools_declared.get("mw_asset_stage", {}).get("isGameImport") is False,
        tools_declared.get("mw_asset_stage", {}).get("isGameImport"),
    )

    # --- 3. catalog.search (只读) ---------------------------------------
    catalog = await session.call_tool("mw_catalog_search", {"limit": 3})
    check("catalog_search_not_error", not catalog.isError, _summary(catalog).get("errorCode"))
    cat_body = catalog.structuredContent if isinstance(catalog.structuredContent, dict) else {}
    check("catalog_search_backend_file", cat_body.get("backend") == "file", cat_body.get("backend"))
    check(
        "catalog_search_returns_blocks",
        isinstance(cat_body.get("blocks"), list) and cat_body.get("returned") == len(cat_body["blocks"]),
        {"returned": cat_body.get("returned"), "matched": cat_body.get("matched")},
    )
    checks.append({"check": "catalog_search_payload", "ok": True, "detail": _summary(catalog)})

    # --- 4. asset.inspect 现有构建 (只读) --------------------------------
    inspect_ok = await session.call_tool("mw_asset_inspect", {"buildId": BUILD_ID})
    check("asset_inspect_existing_not_error", not inspect_ok.isError, _summary(inspect_ok).get("errorCode"))
    ins_body = inspect_ok.structuredContent if isinstance(inspect_ok.structuredContent, dict) else {}
    check("asset_inspect_backend_file", ins_body.get("backend") == "file", ins_body.get("backend"))
    check(
        "asset_inspect_reports_entities",
        isinstance(ins_body.get("entities"), list) and len(ins_body["entities"]) > 0,
        {"entityCount": len(ins_body.get("entities") or [])},
    )
    checks.append({"check": "asset_inspect_payload", "ok": True, "detail": _summary(inspect_ok)})

    # --- 5. build.validate 现有构建 (只读) -------------------------------
    validate = await session.call_tool("mw_build_validate", {"buildId": BUILD_ID})
    check("build_validate_not_error", not validate.isError, _summary(validate).get("errorCode"))
    val_body = validate.structuredContent if isinstance(validate.structuredContent, dict) else {}
    check("build_validate_valid_true", val_body.get("valid") is True, val_body.get("valid"))
    checks.append({"check": "build_validate_payload", "ok": True, "detail": _summary(validate)})

    # --- 6. ipc.discover 只读探测（注册表 + 本机 TCP 状态） ---------------
    ipc = await session.call_tool("mw_ipc_discover", {})
    check("ipc_discover_not_error", not ipc.isError, _summary(ipc).get("errorCode"))
    ipc_body = ipc.structuredContent if isinstance(ipc.structuredContent, dict) else {}
    check(
        "ipc_discover_backend_marker",
        ipc_body.get("backend") == "windows-registry-and-tcp-state",
        ipc_body.get("backend"),
    )
    check(
        "ipc_discover_protocol_not_verified",
        ipc_body.get("protocolVerified") is False,
        ipc_body.get("protocolVerified"),
    )
    check(
        "ipc_discover_shape",
        isinstance(ipc_body.get("listeners"), list)
        and isinstance(ipc_body.get("connections"), list)
        and isinstance(ipc_body.get("listenerPresent"), bool)
        and ipc_body.get("gameControlAvailable") == "unknown",
        {
            "port": ipc_body.get("port"),
            "listenerPresent": ipc_body.get("listenerPresent"),
            "listeners": len(ipc_body.get("listeners") or []),
            "connections": len(ipc_body.get("connections") or []),
            "gameControlAvailable": ipc_body.get("gameControlAvailable"),
        },
    )
    check(
        "ipc_discover_port_in_range_or_absent",
        ipc_body.get("port") is None
        or (isinstance(ipc_body.get("port"), int) and 1 <= ipc_body["port"] <= 65535),
        ipc_body.get("port"),
    )
    checks.append({"check": "ipc_discover_payload", "ok": True, "detail": _summary(ipc)})

    # --- 7. 非法 buildId 必须 isError ------------------------------------
    invalid = await session.call_tool("mw_asset_inspect", {"buildId": INVALID_BUILD_ID})
    check("invalid_build_reports_isError", invalid.isError is True, _summary(invalid))
    inv_body = invalid.structuredContent if isinstance(invalid.structuredContent, dict) else {}
    check(
        "invalid_build_error_structured",
        isinstance(inv_body.get("error"), dict)
        and isinstance(inv_body["error"].get("code"), str)
        and inv_body.get("ok") is False,
        inv_body.get("error"),
    )

    # --- 7. 确认没有产生落盘副作用 ---------------------------------------
    check(
        "stage_never_invoked",
        True,
        {"neverCalled": NEVER_CALLED, "note": "smoke 全程只读，未调用 mw_asset_stage"},
    )


async def main() -> int:
    started = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    checks: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "startedAt": started,
        "projectRoot": str(REPO_ROOT),
        "serverCommand": f"{sys.executable} -m backend.server",
        "python": sys.version,
        "buildIdUsed": BUILD_ID,
        "invalidBuildIdUsed": INVALID_BUILD_ID,
        "stageInvoked": False,
    }

    try:
        async with stdio_client(_server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()  # 真实 MCP 握手
                server_info = getattr(init, "serverInfo", None)
                report["protocolVersion"] = getattr(init, "protocolVersion", None)
                report["serverInfo"] = (
                    server_info.model_dump(mode="json") if server_info is not None else None
                )
                checks.append(
                    {
                        "check": "stdio_handshake",
                        "ok": True,
                        "detail": {
                            "protocolVersion": report["protocolVersion"],
                            "serverInfo": report["serverInfo"],
                        },
                    }
                )
                await _run(session, checks)
    except BaseException as exc:  # 握手/传输层失败也要如实记录
        checks.append(
            {
                "check": "stdio_transport",
                "ok": False,
                "detail": _describe_exception(exc),
            }
        )

    failed = [c["check"] for c in checks if not c["ok"]]
    report["toolCallCount"] = 6
    report["checks"] = checks
    report["failed"] = failed
    report["passed"] = not failed
    report["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[smoke] checks={len(checks)} failed={len(failed)} -> {OUT_PATH}")
    for name in failed:
        print(f"[smoke] FAIL {name}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
