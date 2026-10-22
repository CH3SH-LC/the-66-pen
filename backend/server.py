"""最小标准 MCP stdio server —— 把 mvp 的资产/落盘接口暴露为 MCP 工具。

运行：``python -m backend.server``（工程根为 cwd）。

设计约束
--------
* 只走 **stdio**。不监听任何 HTTP 端口，因此不需要改动 dsh 现有配置。
* 工具参数与 ``mvp.asset_api`` / ``mvp.stage_api`` 源码里的封闭参数表**逐字一致**，
  不新增路径、程序、命令行、shell 等参数，也不提供"万能 JSON"透传工具。
* 成功 → 返回真实 ``dispatch`` 结果（已自带 backend / evidenceLevel /
  gameAccepted / warnings）。失败 → 标准 MCP ``isError`` 结果，绝不假成功。
* stdout 只承载 MCP 报文；日志一律 stderr。

能力边界
--------
资产与落盘工具的 ``backend`` 是 ``file``：只做工程内文件读写。``mw_asset_stage``
是把已校验的 GIA **复制到游戏官方外部资产目录**，它**不是** game import ——
落盘不触发游戏导入、不保存、不试玩，``gameImported`` / ``sceneVisible`` 恒为
``unknown``。

``mw_ipc_discover`` 是唯一的例外：``backend=windows-registry-and-tcp-state``，
只读一次 HKCU 注册表值并查询本机内核 TCP 状态，不发报文、不写注册表、不开窗口、
不启动游戏。它证明端口存在与被连接，**不证明协议可用**。

本服务**不发布**任何 game import / save / playtest 工具。
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.types import CallToolResult, TextContent  # noqa: E402

from bridge import ipc_discovery  # noqa: E402
from mvp import asset_api, stage_api  # noqa: E402
from mvp.asset_api import AssetApiError  # noqa: E402

SERVER_NAME = "miliastra-wonderland-backend"

# 资产/落盘工具的后端：工程内文件层
FILE_BACKEND = asset_api.BACKEND
# IPC 发现工具的后端：一次 HKCU 注册表读取 + 本机内核 TCP 状态查询（不是文件层）
IPC_BACKEND = "windows-registry-and-tcp-state"
IPC_EVIDENCE_LEVEL = "live-host-observation"

# 先占住 root logger，保证任何库日志都落在 stderr，不污染 stdout 的 MCP 报文。
logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(SERVER_NAME)

_INSTRUCTIONS = (
    "资产/落盘工具的后端是工程内文件（backend=file）：mvp.asset_api 的四个方法"
    "（catalog.search / scene.build / asset.inspect / build.validate）与 mvp.stage_api 的 "
    "mw.asset.stage。参数名与源码一致：buildId、idempotencyKey、query、templateId、limit、"
    "scene、overwrite。这些结果都是离线证据（evidenceLevel=offline-tested, "
    "gameAccepted=unknown）：不启动游戏、不导入、不保存、不试玩。mw_asset_stage 只是把已校验 "
    "GIA 复制到游戏官方外部资产目录，不构成 game import。另有 mw_ipc_discover，后端是 "
    "windows-registry-and-tcp-state：只读注册表端口值 + 本机内核 TCP 状态，不发报文、不开窗口、"
    "不启动游戏，且 listenerPresent 不代表协议可用（protocolVerified 恒为 false）。"
)

mcp = FastMCP(SERVER_NAME, instructions=_INSTRUCTIONS)


# --------------------------------------------------------------------------
# 调用与错误封装
# --------------------------------------------------------------------------
def _error_body(
    method: str, exc: BaseException, backend: str = FILE_BACKEND
) -> dict[str, Any]:
    if isinstance(exc, AssetApiError):
        error = exc.to_dict()
    else:  # 未预期异常也如实上报，不伪装成成功
        error = {
            "code": "BACKEND_UNAVAILABLE",
            "message": f"unexpected {type(exc).__name__}: {exc}",
            "phase": "effect",
            "effectState": "unknown",
            "details": {},
            "codeOrigin": "bridge-extension",
        }
    return {
        "ok": False,
        "method": method,
        "error": error,
        "backend": backend,
        "evidenceLevel": asset_api.EVIDENCE_LEVEL,
        "gameAccepted": asset_api.GAME_ACCEPTED,
    }


def _fail(
    method: str, exc: BaseException, backend: str = FILE_BACKEND
) -> CallToolResult:
    body = _error_body(method, exc, backend)
    log.warning("tool %s failed: %s", method, body["error"]["code"])
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(body, ensure_ascii=False, indent=2))
        ],
        structuredContent=body,
        isError=True,
    )


def _call_asset(method: str, params: dict[str, Any]) -> Any:
    try:
        return asset_api.dispatch(method, params)
    except Exception as exc:  # 边界：任何失败都变成 isError，不抛栈给协议层
        return _fail(method, exc)


def _call_stage(method: str, params: dict[str, Any]) -> Any:
    try:
        return stage_api.dispatch(method, params)
    except Exception as exc:
        return _fail(method, exc)


def _present(mapping: dict[str, Any]) -> dict[str, Any]:
    """丢掉值为 None 的可选参数，避免把 None 传给封闭参数表。"""
    return {k: v for k, v in mapping.items() if v is not None}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
@mcp.tool(
    name="mw_catalog_search",
    title="查询可用方块目录（只读）",
    description=(
        "mw.catalog.search：从上游配置 AST 中按字面量读取资源声明并过滤，不执行上游代码，"
        "不访问网络。参数与源码一致，全部可选：query（名称/模板 ID 子串，1..64 字符）、"
        "templateId（1..2^31-1 的整数）、category（工程侧派生分类，1..64 字符，精确匹配）、"
        "limit（1..200，默认 50）、offset（>=0，默认 0）。结果带 offset/nextOffset/hasMore "
        "与 categories 分类计数，可逐页读回、跨页 ID 不重复。category 是工程侧派生分组，"
        "不是原生资源类型。结果 backend=file，仅是工程内声明，未在游戏里验证。"
    ),
)
def mw_catalog_search(
    query: str | None = None,
    templateId: int | None = None,
    category: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    return _call_asset(
        "mw.catalog.search",
        _present(
            {
                "query": query,
                "templateId": templateId,
                "category": category,
                "limit": limit,
                "offset": offset,
            }
        ),
    )


@mcp.tool(
    name="mw_scene_build",
    title="运行固定生成器构建场景（写工程内构建区）",
    description=(
        "mw.scene.build：用工程内固定的 mvp/generate_mvp.py 与固定参数字表（只有 --scene / --out，"
        "均由模块推导）生成 GIA 与清单，写入内容寻址目录 .runtime/mvp/builds/<buildId>。"
        "参数与源码一致：scene（可选，mvp/ 内相对 .json 路径，默认 scene.json；"
        "不接受绝对路径、反斜杠、'..'）、overwrite（可选布尔，默认 false；false 时命中已有构建直接复用）。"
        "只写工程内构建区，不碰游戏目录。"
    ),
)
def mw_scene_build(scene: str | None = None, overwrite: bool | None = None) -> dict[str, Any]:
    return _call_asset("mw.scene.build", _present({"scene": scene, "overwrite": overwrite}))


@mcp.tool(
    name="mw_asset_inspect",
    title="检视构建产物（只读）",
    description=(
        "mw.asset.inspect：解码构建区里某次构建的 GIA，回报容器格式、哈希、实体名、模板 ID 与变换。"
        "参数与源码一致：buildId（必填，64 位小写十六进制构建键；省略在源码层表示取最新构建，"
        "本工具要求显式给出以免误判）。纯只读，不写任何文件。"
    ),
)
def mw_asset_inspect(buildId: str) -> dict[str, Any]:
    return _call_asset("mw.asset.inspect", {"buildId": buildId})


@mcp.tool(
    name="mw_build_validate",
    title="逐实体比对构建与源场景（只读）",
    description=(
        "mw.build.validate：把 buildId 指向的构建与源场景逐实体比对，回报源哈希与每项检查结果。"
        "参数与源码一致：buildId（必填，64 位小写十六进制构建键）、scene（可选，mvp/ 内相对 .json 路径）。"
        "纯只读。这是 mw_asset_stage 的前置校验，通过不代表游戏接受了该资产。"
    ),
)
def mw_build_validate(buildId: str, scene: str | None = None) -> dict[str, Any]:
    return _call_asset("mw.build.validate", _present({"buildId": buildId, "scene": scene}))


@mcp.tool(
    name="mw_asset_stage",
    title="把已校验 GIA 落盘到游戏外部资产目录（真实写入，非 game import）",
    description=(
        "mw.asset.stage：把构建区里**已通过 validate 与 inspect** 的 GIA 复制到游戏官方外部资产目录"
        "（固定目录、固定文件名 MVP_Platformer_<源哈希前12位>.gia）。**这是真实写入磁盘的操作。**"
        "参数与源码一致：buildId（必填，64 位小写十六进制）、idempotencyKey（必填，1..128 个可打印 ASCII）。"
        "没有路径/程序/命令行参数，目标目录由模块常量固定，目录不存在时不创建。"
        "目标同名同哈希 → reused 不重写；同名异哈希 → 拒绝且绝不覆盖。"
        "**落盘不等于导入**：不启动游戏、不保存、不试玩，gameImported / sceneVisible 恒为 unknown。"
        "只在用户明确要求真实落盘时调用。"
    ),
)
def mw_asset_stage(buildId: str, idempotencyKey: str) -> dict[str, Any]:
    return _call_stage(
        stage_api.METHOD_STAGE, {"buildId": buildId, "idempotencyKey": idempotencyKey}
    )


@mcp.tool(
    name="mw_ipc_discover",
    title="发现千星编辑器 IPC 端点（只读注册表 + 本机 TCP 状态）",
    description=(
        "mw.ipc.discover：读取 HKCU\\Software\\miHoYo\\BeyondAssistEditor 下的单个端口 DWORD"
        "（键名由 djb2-xor 推导，端口在运行时读取，本模块不写死任何端口号），"
        "再问 Windows 这个端口上有没有绑定或连接。"
        "纯只读：不写注册表、不发任何报文、不开窗口、不聚焦窗口、不启动游戏。"
        "backend=windows-registry-and-tcp-state（不是 file）。"
        "listenerPresent=true 只说明有进程绑着这个端口，不说明协议可用："
        "在真正有东西跟它通信之前 protocolVerified 恒为 false，gameControlAvailable 恒为 unknown。"
        "探测失败时 listenerPresent 报 unknown，绝不把失败谎报成没有监听。无参数。"
    ),
)
def mw_ipc_discover() -> dict[str, Any]:
    try:
        result = dict(ipc_discovery.discover())
    except Exception as exc:
        return _fail(ipc_discovery.METHOD, exc, IPC_BACKEND)
    result["backend"] = IPC_BACKEND
    result["evidenceLevel"] = IPC_EVIDENCE_LEVEL
    result["warnings"] = [
        "这是本机注册表 + 内核 TCP 状态的一次实时快照，不是游戏或编辑器可用性的证据。",
        "protocolVerified=false 与 gameControlAvailable=unknown 是当前的真实结论，不要当成可用。",
    ]
    return result


@mcp.tool(
    name="mw_backend_capabilities",
    title="本后端的真实能力与不可用边界（只读）",
    description=(
        "返回本 MCP 服务每个工具的真实后端、参数表、副作用与**不可用能力清单**。"
        "不用来替代真实调用，只用来确认边界：所有工具 backend=file；"
        "mw_asset_stage 不是 game import；gameImport / save / playtest 一律 unavailable。"
    ),
)
def mw_backend_capabilities() -> dict[str, Any]:
    asset_params = {
        method: sorted(asset_api.PARAMS_BY_METHOD[method]) for method in asset_api.KNOWN_METHODS
    }
    stage_params = {
        method: sorted(stage_api.PARAMS_BY_METHOD[method]) for method in stage_api.KNOWN_METHODS
    }
    return {
        "server": SERVER_NAME,
        "transport": "stdio",
        "httpPort": None,
        "projectCwdRequired": str(REPO_ROOT),
        # 不是所有工具都走文件层：资产/落盘走 file，IPC 发现走注册表 + 内核 TCP 状态。
        "backends": {
            "assets": FILE_BACKEND,
            "staging": FILE_BACKEND,
            "bridge": IPC_BACKEND,
        },
        "backend": FILE_BACKEND,
        "evidenceLevel": asset_api.EVIDENCE_LEVEL,
        "gameAccepted": asset_api.GAME_ACCEPTED,
        "gameImported": stage_api.GAME_IMPORTED,
        "sceneVisible": stage_api.SCENE_VISIBLE,
        "tools": [
            {
                "name": "mw_catalog_search",
                "domain": "assets",
                "calls": "mvp.asset_api.dispatch('mw.catalog.search', ...)",
                "params": asset_params["mw.catalog.search"],
                "backend": FILE_BACKEND,
                "effect": "read-only",
                "idempotent": True,
            },
            {
                "name": "mw_scene_build",
                "domain": "assets",
                "calls": "mvp.asset_api.dispatch('mw.scene.build', ...)",
                "params": asset_params["mw.scene.build"],
                "backend": FILE_BACKEND,
                "effect": "writes .runtime/mvp/builds/ only",
                "idempotent": True,
            },
            {
                "name": "mw_asset_inspect",
                "domain": "assets",
                "calls": "mvp.asset_api.dispatch('mw.asset.inspect', ...)",
                "params": asset_params["mw.asset.inspect"],
                "backend": FILE_BACKEND,
                "effect": "read-only",
                "idempotent": True,
            },
            {
                "name": "mw_build_validate",
                "domain": "assets",
                "calls": "mvp.asset_api.dispatch('mw.build.validate', ...)",
                "params": asset_params["mw.build.validate"],
                "backend": FILE_BACKEND,
                "effect": "read-only",
                "idempotent": True,
            },
            {
                "name": "mw_asset_stage",
                "domain": "staging",
                "calls": "mvp.stage_api.dispatch('mw.asset.stage', ...)",
                "params": stage_params[stage_api.METHOD_STAGE],
                "backend": FILE_BACKEND,
                "effect": (
                    "real disk write: copies validated GIA into the game's official external "
                    "asset directory (fixed dir, fixed name, no-overwrite)"
                ),
                "isGameImport": False,
                "idempotent": True,
                "note": (
                    "落盘 != 导入 != 场景可见。本工具不启动游戏、不保存、不试玩；"
                    "gameImported 与 sceneVisible 恒为 unknown。"
                ),
            },
            {
                "name": "mw_ipc_discover",
                "domain": "bridge",
                "calls": "bridge.ipc_discovery.discover()",
                "params": [],
                "backend": IPC_BACKEND,
                "evidenceLevel": IPC_EVIDENCE_LEVEL,
                "effect": (
                    "read-only: one HKCU registry value read + one local kernel TCP state query"
                ),
                "idempotent": True,
                "networkRequests": False,
                "writesRegistry": False,
                "startsProcesses": False,
                "opensWindows": False,
                "note": (
                    "listenerPresent=true 只说明端口上有进程绑定，不是协议可用；"
                    "protocolVerified 恒为 false，gameControlAvailable 恒为 unknown。"
                ),
            },
        ],
        "unavailable": {
            "gameImport": "unavailable",
            "save": "unavailable",
            "playtest": "unavailable",
            "sceneVisible": "unavailable",
            "loadIntoEditor": "unavailable",
        },
        "notes": [
            "资产工具（catalog/search、scene/build、asset/inspect、build/validate）与 mw_asset_stage "
            "的 backend 是 file；只有 mw_ipc_discover 的 backend 是 windows-registry-and-tcp-state。",
            "没有任何窗口/进程启动/shell 包装工具。mw_ipc_discover 也不发报文、不写注册表、不开窗口、不启动游戏。",
            "没有泛型 JSON 透传工具：每个工具的参数表都是源码里的封闭参数表。",
            "失败的调用以 MCP isError=true 返回结构化错误（code/phase/effectState/details），不假成功。",
            "未在本服务中发布任何 game import / save / playtest 工具，因为工程当前不具备该能力。",
            "mw_ipc_discover 只证明端口存在与被连接，不证明协议可用；不要据此认为可以控制编辑器。",
        ],
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
