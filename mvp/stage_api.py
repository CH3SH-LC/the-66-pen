#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产落盘领域接口（纯标准库）：把构建区里**验证通过**的 GIA 复制到固定导出目录。

入口
----
* ``dispatch(method, params, backend=...)``  — 与 ``mvp.asset_api`` 同形的业务函数。
* ``handle_request(request, backend=...)``   — 单次请求/响应信封（stdin 协议用）。
* ``main(argv)``                             — 单次 JSON stdin → stdout，供 bridge
  或主智能体以子进程方式调用。

单次协议::

    stdin : {"method": "mw.asset.stage",
             "params": {"buildId": "<64位小写hex>", "idempotencyKey": "<1..128 可打印ASCII>"}}
    stdout: {"ok": true,  "method": "mw.asset.stage", "result": {...}}
            或
            {"ok": false, "method": "mw.asset.stage", "error": {...}}

参数表**只有** ``buildId`` 与 ``idempotencyKey``。没有路径参数、没有程序路径、
没有命令行字符串：源由 ``buildId`` 在 ``.runtime/mvp/builds/`` 内解析，目标由本模块
的常量推导。调用方无法指定任意路径。

落盘语义
--------
1. 源校验：复用 ``asset_api.dispatch`` 的 ``mw.build.validate`` 与 ``mw.asset.inspect``，
   两者都必须 ``valid``；任一不过即拒绝。
2. 目标名：``MVP_Platformer_<源GIA sha256 前12位>.gia``，因此同名即同内容。
3. 目标已存在且 hash 相同 → 返回 ``status="reused"``，不重写、不覆盖。
   同名但 hash 不同 → 拒绝（``VALIDATION_FAILED``），**绝不覆盖**。
4. 新写入：先在目标目录内 ``O_CREAT|O_EXCL`` 独占创建临时文件，写满 fsync 后
   用 ``os.link`` 原子无覆盖落位；文件系统不支持硬链接时退回 ``O_EXCL`` 独占创建，
   并在结果里如实标注 ``commitMode``。
5. 落位后重新读回目标文件并核对 hash，两个 journal 条目（计划 / 落盘）在任何写入
   之前与之后分别 fsync 到磁盘。

范围声明
--------
导出目录固定为 ``Path.home()/AppData/LocalLow/miHoYo/原神/BeyondLocal/Beyond_Local_Export``。
结果固定带 ``gameImported=unknown`` 与 ``sceneVisible=unknown``：**文件落盘不等于
游戏已导入、更不等于场景可见**。本模块不启动游戏、不操作 UI、不看结算，也不改动
目录里任何其他文件。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent  # .../mvp
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mvp import asset_api  # noqa: E402
from mvp.asset_api import AssetApiError  # noqa: E402

# --------------------------------------------------------------------------
# 常量：路径全部硬编码，不接受调用方输入
# --------------------------------------------------------------------------
METHOD_STAGE = "mw.asset.stage"

#: 官方外部资产目录。这是**唯一**允许写入的目标目录。
DEFAULT_EXPORT_DIR = (
    Path.home()
    / "AppData"
    / "LocalLow"
    / "miHoYo"
    / "原神"
    / "BeyondLocal"
    / "Beyond_Local_Export"
)
#: 落盘 journal（在仓库 .runtime 内，不污染游戏目录）。
DEFAULT_JOURNAL_PATH = REPO_ROOT / ".runtime" / "mvp" / "stage-journal.jsonl"

FILE_PREFIX = "MVP_Platformer_"
FILE_SUFFIX = ".gia"
HASH_PREFIX_LEN = 12
MAX_KEY_LEN = 128

BACKEND = "file"
EVIDENCE_LEVEL = "offline-tested"
GAME_ACCEPTED = "unknown"
#: 落盘之后的两个业务事实：本模块无法观测，只能如实标 unknown。
GAME_IMPORTED = "unknown"
SCENE_VISIBLE = "unknown"

PARAMS_BY_METHOD: dict[str, frozenset[str]] = {
    METHOD_STAGE: frozenset({"buildId", "idempotencyKey"}),
}
KNOWN_METHODS = tuple(sorted(PARAMS_BY_METHOD))

NOTE = (
    "文件已落到固定导出目录。落盘(staged)只说明磁盘上有一份与构建区逐字节相同的"
    "GIA；游戏是否导入、场景是否可见本模块无法观测，故标 unknown。"
)


# --------------------------------------------------------------------------
# 后端（可注入，便于离线测试）
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class StageBackend:
    """落盘后端：一个导出目录 + 一个 journal 文件。

    生产用 :func:`default_backend`；测试注入临时目录，从而**不碰真实游戏目录**。
    """

    export_dir: Path
    journal_path: Path


def default_backend() -> StageBackend:
    return StageBackend(export_dir=DEFAULT_EXPORT_DIR, journal_path=DEFAULT_JOURNAL_PATH)


# --------------------------------------------------------------------------
# 参数校验
# --------------------------------------------------------------------------
def _require(condition: bool, message: str, **details: Any) -> None:
    if not condition:
        raise AssetApiError("VALIDATION_FAILED", message, details=details)


def _build_id(value: Any) -> str:
    _require(
        isinstance(value, str) and asset_api.BUILD_ID_RE.match(value) is not None,
        "buildId 必须是 64 位小写十六进制构建键",
        field="buildId",
        received=value if isinstance(value, str) else type(value).__name__,
    )
    return value


def _idempotency_key(value: Any) -> str:
    _require(isinstance(value, str), "idempotencyKey 必须是字符串", field="idempotencyKey")
    _require(
        0 < len(value) <= MAX_KEY_LEN,
        f"idempotencyKey 长度必须在 1..{MAX_KEY_LEN} 个字符之间",
        field="idempotencyKey",
    )
    _require(
        value.isascii() and all(0x20 <= ord(ch) < 0x7F for ch in value),
        "idempotencyKey 必须是可打印 ASCII（不得含控制字符）",
        field="idempotencyKey",
    )
    return value


def _reject_unknown_params(method: str, params: dict[str, Any]) -> None:
    unknown = sorted(set(params) - PARAMS_BY_METHOD[method])
    if unknown:
        raise AssetApiError(
            "PARAM_FORBIDDEN",
            f"{method} 不接受参数: {', '.join(unknown)}",
            details={
                "method": method,
                "unknownParams": unknown,
                "allowedParams": sorted(PARAMS_BY_METHOD[method]),
                "note": (
                    "本接口使用封闭参数表：没有路径参数，导出目录由模块常量固定，"
                    "调用方无法指定任意路径、程序或命令行字符串。"
                ),
            },
        )


# --------------------------------------------------------------------------
# journal
# --------------------------------------------------------------------------
def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def _append_journal(backend: StageBackend, entry: dict[str, Any]) -> dict[str, Any]:
    """追加一条 JSONL 并 fsync。写失败即视为能力的缺失，不静默吞掉。"""
    path = backend.journal_path
    record = {"ts": _utc_now(), "gameImported": GAME_IMPORTED, "sceneVisible": SCENE_VISIBLE}
    record.update(entry)
    line = (json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
    except OSError as exc:
        raise AssetApiError(
            "BACKEND_UNAVAILABLE",
            f"无法写入落盘 journal: {exc.__class__.__name__}: {exc}",
            phase="preflight",
            details={"journal": str(path)},
        ) from exc
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return record


def _journal_entries(backend: StageBackend) -> list[dict[str, Any]]:
    path = backend.journal_path
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _check_key_not_reused_for_another_build(
    backend: StageBackend, key: str, build_id: str
) -> None:
    """同一个幂等键不得指向另一次已落盘的构建，否则幂等语义自相矛盾。"""
    for entry in _journal_entries(backend):
        if entry.get("idempotencyKey") != key:
            continue
        if entry.get("status") not in ("staged", "reused"):
            continue
        if entry.get("buildId") != build_id:
            raise AssetApiError(
                "VALIDATION_FAILED",
                "该 idempotencyKey 已用于另一个 buildId 的落盘",
                details={
                    "idempotencyKey": key,
                    "requestedBuildId": build_id,
                    "journalBuildId": entry.get("buildId"),
                    "journal": str(backend.journal_path),
                },
            )


# --------------------------------------------------------------------------
# 文件落位
# --------------------------------------------------------------------------
def _exclusive_create(path: Path, blob: bytes) -> None:
    """``O_CREAT|O_EXCL`` 独占创建并写满 fsync；同名文件已存在则 FileExistsError。"""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o644)
    try:
        written = 0
        while written < len(blob):
            written += os.write(fd, blob[written:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _commit_no_clobber(temp_path: Path, target_path: Path, blob: bytes) -> str:
    """原子且不覆盖地把临时文件落位。返回落位方式，或 ``"exists"`` 表示目标已存在。

    首选 ``os.link``（同目录同卷，原子且同名必失败）；文件系统不支持硬链接时退回
    ``O_EXCL`` 独占创建（原子创建；内容写入不是原子的，结果里如实标注）。
    """
    try:
        os.link(temp_path, target_path)
    except FileExistsError:
        return "exists"
    except OSError:
        try:
            _exclusive_create(target_path, blob)
        except FileExistsError:
            return "exists"
        return "exclusive-create"
    return "link"


# --------------------------------------------------------------------------
# mw.asset.stage
# --------------------------------------------------------------------------
def stage_asset(params: dict[str, Any], *, backend: StageBackend) -> dict[str, Any]:
    build_id = _build_id(params.get("buildId"))
    idem_key = _idempotency_key(params.get("idempotencyKey"))

    # --- 源必须是构建区内、校验通过的 GIA -------------------------------
    validation = asset_api.dispatch("mw.build.validate", {"buildId": build_id})
    if not validation["valid"]:
        raise AssetApiError(
            "VALIDATION_FAILED",
            "构建区校验未通过，拒绝落盘",
            phase="preflight",
            details={
                "buildId": build_id,
                "failedChecks": [c["check"] for c in validation["checks"] if not c["ok"]],
            },
        )
    inspection = asset_api.dispatch("mw.asset.inspect", {"buildId": build_id})
    if not inspection["valid"]:
        raise AssetApiError(
            "VALIDATION_FAILED",
            "容器/解码检查未通过，拒绝落盘",
            phase="preflight",
            details={
                "buildId": build_id,
                "failedChecks": [c["check"] for c in inspection["checks"] if not c["ok"]],
            },
        )

    build_dir = asset_api.BUILDS_DIR / build_id
    record = json.loads((build_dir / "build-record.json").read_text(encoding="utf-8"))
    artifact_name = record["artifacts"]["gia"]["path"]
    source_path = build_dir / artifact_name
    try:
        blob = source_path.read_bytes()
    except OSError as exc:
        raise AssetApiError(
            "BACKEND_UNAVAILABLE",
            f"无法读取构建区 GIA: {exc.__class__.__name__}: {exc}",
            phase="preflight",
            details={"sourcePath": asset_api._rel(source_path)},
        ) from exc

    source_sha = asset_api.sha256_bytes(blob)
    if source_sha != inspection["artifact"]["sha256"]:
        raise AssetApiError(
            "LOSSY_ROUNDTRIP",
            "读取到的 GIA 与 inspect 报告的哈希不一致（读盘期间被改动？）",
            phase="observe",
            details={
                "readSha256": source_sha,
                "inspectedSha256": inspection["artifact"]["sha256"],
            },
        )

    # --- 目标：目录固定，文件名由源哈希推导 -----------------------------
    export_dir = Path(backend.export_dir).resolve()
    if not export_dir.is_dir():
        raise AssetApiError(
            "CAPABILITY_UNAVAILABLE",
            "固定导出目录不存在；本接口不会创建它，也不会改用别的路径",
            phase="preflight",
            details={"exportDir": str(export_dir)},
        )

    file_name = f"{FILE_PREFIX}{source_sha[:HASH_PREFIX_LEN]}{FILE_SUFFIX}"
    target_path = export_dir / file_name
    _require(
        target_path.parent == export_dir and Path(file_name).name == file_name,
        "推导出的目标路径越出了固定导出目录",
        exportDir=str(export_dir),
        fileName=file_name,
    )

    source_block = {
        "buildId": build_id,
        "buildDir": asset_api._rel(build_dir),
        "artifact": artifact_name,
        "path": str(source_path),
        "bytes": len(blob),
        "sha256": source_sha,
        "validated": True,
        "validateChecks": validation["checks"],
        "inspectChecks": inspection["checks"],
    }
    target_block = {
        "exportDir": str(export_dir),
        "fileName": file_name,
        "path": str(target_path),
    }

    _check_key_not_reused_for_another_build(backend, idem_key, build_id)

    def _result(status: str, *, commit_mode: str, re_read_sha: str | None, extra: dict) -> dict:
        return {
            "buildId": build_id,
            "idempotencyKey": idem_key,
            "status": status,
            "reused": status == "reused",
            "staged": status == "staged",
            "source": source_block,
            "target": dict(target_block, bytes=len(blob), sha256=source_sha, **extra),
            "verification": {
                "reReadSha256": re_read_sha,
                "matchesSource": re_read_sha == source_sha,
                "method": "落位后重新读取目标文件并整文件哈希",
            },
            "commitMode": commit_mode,
            "gameImported": GAME_IMPORTED,
            "sceneVisible": SCENE_VISIBLE,
            "note": NOTE,
        }

    # --- 已存在：同 hash 复用，异 hash 拒绝（绝不覆盖） ------------------
    if target_path.exists():
        existing_sha = asset_api.sha256_file(target_path)
        if existing_sha == source_sha:
            entry = _append_journal(
                backend,
                {
                    "event": "reused",
                    "status": "reused",
                    "idempotencyKey": idem_key,
                    "buildId": build_id,
                    "sourceSha256": source_sha,
                    "target": target_block,
                    "reReadSha256": existing_sha,
                },
            )
            result = _result(
                "reused",
                commit_mode="none",
                re_read_sha=existing_sha,
                extra={"existedBefore": True},
            )
            result["journal"] = {"path": str(backend.journal_path), "entries": [entry]}
            return result

        entry = _append_journal(
            backend,
            {
                "event": "refused",
                "status": "refused",
                "idempotencyKey": idem_key,
                "buildId": build_id,
                "sourceSha256": source_sha,
                "target": target_block,
                "existingSha256": existing_sha,
            },
        )
        raise AssetApiError(
            "VALIDATION_FAILED",
            "目标同名文件内容不同，拒绝覆盖",
            phase="preflight",
            details={
                "target": str(target_path),
                "existingSha256": existing_sha,
                "wantedSha256": source_sha,
                "journal": str(backend.journal_path),
                "journalEntry": entry,
            },
        )

    # --- 写入前：持久记录计划 ------------------------------------------
    temp_name = f".{file_name}.{os.getpid()}.tmp"
    temp_path = export_dir / temp_name
    journal = [
        _append_journal(
            backend,
            {
                "event": "plan",
                "status": "planned",
                "idempotencyKey": idem_key,
                "buildId": build_id,
                "sourceSha256": source_sha,
                "sourcePath": str(source_path),
                "target": target_block,
                "tempPath": str(temp_path),
                "commitPlan": "O_EXCL 独占创建临时文件 → os.link 原子无覆盖落位 → 重读校验",
            },
        )
    ]

    try:
        _exclusive_create(temp_path, blob)
    except FileExistsError as exc:
        _append_journal(
            backend,
            {"event": "failed", "status": "failed", "idempotencyKey": idem_key,
             "buildId": build_id, "errorCode": "BACKEND_UNAVAILABLE", "tempPath": str(temp_path)},
        )
        raise AssetApiError(
            "BACKEND_UNAVAILABLE",
            "临时文件已存在（独占创建失败），未写入任何内容",
            phase="effect",
            details={"tempPath": str(temp_path)},
        ) from exc
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        _append_journal(
            backend,
            {"event": "failed", "status": "failed", "idempotencyKey": idem_key,
             "buildId": build_id, "errorCode": "BACKEND_UNAVAILABLE", "tempPath": str(temp_path)},
        )
        raise AssetApiError(
            "BACKEND_UNAVAILABLE",
            f"无法写入临时文件: {exc.__class__.__name__}: {exc}",
            phase="effect",
            details={"tempPath": str(temp_path)},
        ) from exc

    # 临时文件必须与源逐字节一致，否则不落位
    temp_sha = asset_api.sha256_file(temp_path)
    if temp_sha != source_sha:
        temp_path.unlink(missing_ok=True)
        _append_journal(
            backend,
            {"event": "failed", "status": "failed", "idempotencyKey": idem_key,
             "buildId": build_id, "errorCode": "LOSSY_ROUNDTRIP", "tempPath": str(temp_path)},
        )
        raise AssetApiError(
            "LOSSY_ROUNDTRIP",
            "临时文件哈希与源不一致，已删除且未落位",
            phase="effect",
            details={"tempSha256": temp_sha, "sourceSha256": source_sha},
        )

    commit_mode = _commit_no_clobber(temp_path, target_path, blob)
    temp_path.unlink(missing_ok=True)

    if commit_mode == "exists":
        existing_sha = asset_api.sha256_file(target_path)
        if existing_sha == source_sha:
            entry = _append_journal(
                backend,
                {"event": "reused", "status": "reused", "idempotencyKey": idem_key,
                 "buildId": build_id, "sourceSha256": source_sha, "target": target_block,
                 "reReadSha256": existing_sha, "note": "落位瞬间被并发创建，内容相同"},
            )
            result = _result("reused", commit_mode="none", re_read_sha=existing_sha,
                             extra={"existedBefore": True})
            result["journal"] = {"path": str(backend.journal_path), "entries": journal + [entry]}
            return result

        _append_journal(
            backend,
            {"event": "refused", "status": "refused", "idempotencyKey": idem_key,
             "buildId": build_id, "sourceSha256": source_sha, "target": target_block,
             "existingSha256": existing_sha},
        )
        raise AssetApiError(
            "VALIDATION_FAILED",
            "目标同名文件内容不同（并发写入），拒绝覆盖",
            phase="effect",
            details={"target": str(target_path), "existingSha256": existing_sha,
                     "wantedSha256": source_sha},
        )

    # --- 落位后：重读目标文件再确认 ------------------------------------
    try:
        re_read_sha = asset_api.sha256_file(target_path)
    except OSError as exc:
        re_read_sha = None
        _append_journal(
            backend,
            {"event": "failed", "status": "failed", "idempotencyKey": idem_key,
             "buildId": build_id, "errorCode": "BACKEND_UNAVAILABLE", "target": target_block},
        )
        raise AssetApiError(
            "BACKEND_UNAVAILABLE",
            f"落位后无法重读目标文件: {exc.__class__.__name__}: {exc}",
            phase="observe",
            details={"target": str(target_path)},
        ) from exc

    if re_read_sha != source_sha:
        _append_journal(
            backend,
            {"event": "failed", "status": "failed", "idempotencyKey": idem_key,
             "buildId": build_id, "errorCode": "LOSSY_ROUNDTRIP", "target": target_block,
             "reReadSha256": re_read_sha},
        )
        raise AssetApiError(
            "LOSSY_ROUNDTRIP",
            "落位后重读的哈希与源不一致",
            phase="observe",
            details={"reReadSha256": re_read_sha, "sourceSha256": source_sha,
                     "target": str(target_path)},
        )

    journal.append(
        _append_journal(
            backend,
            {"event": "staged", "status": "staged", "idempotencyKey": idem_key,
             "buildId": build_id, "sourceSha256": source_sha, "target": target_block,
             "reReadSha256": re_read_sha, "commitMode": commit_mode,
             "note": "文件已落盘并重读校验一致；游戏导入与场景可见性未观测。"},
        )
    )

    result = _result("staged", commit_mode=commit_mode, re_read_sha=re_read_sha,
                     extra={"existedBefore": False})
    result["journal"] = {"path": str(backend.journal_path), "entries": journal}
    return result


# --------------------------------------------------------------------------
# dispatch / 单次请求协议
# --------------------------------------------------------------------------
_HANDLERS = {METHOD_STAGE: stage_asset}


def dispatch(
    method: str, params: dict[str, Any] | None = None, *, backend: StageBackend | None = None
) -> dict[str, Any]:
    """执行一个落盘领域方法；失败抛 :class:`AssetApiError`。"""
    if not isinstance(method, str) or method not in _HANDLERS:
        raise AssetApiError(
            "METHOD_UNKNOWN",
            f"method {method!r} is not implemented by the stage api",
            details={"knownMethods": list(KNOWN_METHODS)},
        )
    if params is None:
        params = {}
    _require(isinstance(params, dict), "params must be a JSON object")
    _reject_unknown_params(method, params)

    payload = dict(_HANDLERS[method](params, backend=backend or default_backend()))
    warnings = list(payload.pop("warnings", []))
    result: dict[str, Any] = {"method": method}
    result.update(payload)
    result.update(
        {
            "backend": BACKEND,
            "evidenceLevel": EVIDENCE_LEVEL,
            "gameAccepted": GAME_ACCEPTED,
            "warnings": warnings,
        }
    )
    return result


def handle_request(request: Any, *, backend: StageBackend | None = None) -> dict[str, Any]:
    """单次请求 → 单次响应。任何失败都变成 ``ok=false`` 的信封，不抛栈。"""
    if not isinstance(request, dict):
        return {
            "ok": False,
            "method": None,
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "request must be a JSON object with method/params",
                "phase": "validate",
                "effectState": "none",
                "details": {"received": type(request).__name__},
                "codeOrigin": "contract",
            },
        }
    method = request.get("method")
    try:
        result = dispatch(method, request.get("params", {}), backend=backend)
    except AssetApiError as exc:
        return {"ok": False, "method": method, "error": exc.to_dict()}
    except Exception as exc:  # 未预期异常也不让协议层崩掉
        return {
            "ok": False,
            "method": method,
            "error": {
                "code": "BACKEND_UNAVAILABLE",
                "message": f"unexpected {exc.__class__.__name__}: {exc}",
                "phase": "effect",
                "effectState": "unknown",
                "details": {},
                "codeOrigin": "bridge-extension",
            },
        }
    return {"ok": True, "method": method, "result": result}


def describe() -> dict[str, Any]:
    return {
        "module": "mvp.stage_api",
        "methods": {m: sorted(PARAMS_BY_METHOD[m]) for m in KNOWN_METHODS},
        "exportDir": str(DEFAULT_EXPORT_DIR),
        "journal": str(DEFAULT_JOURNAL_PATH),
        "filePattern": f"{FILE_PREFIX}<源GIA sha256 前{HASH_PREFIX_LEN}位>{FILE_SUFFIX}",
        "backend": BACKEND,
        "evidenceLevel": EVIDENCE_LEVEL,
        "gameAccepted": GAME_ACCEPTED,
        "gameImported": GAME_IMPORTED,
        "sceneVisible": SCENE_VISIBLE,
    }


# --------------------------------------------------------------------------
# CLI：单次 JSON stdin → stdout（或 --build-id/--idempotency-key 便捷形式）
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mvp/stage_api.py",
        description=(
            "单次调用 mw.asset.stage：把构建区里验证通过的 GIA 落到固定导出目录。"
            "不接受路径参数。"
        ),
    )
    parser.add_argument("--build-id", help="构建键（64 位小写 hex），省略则从 stdin 读 JSON")
    parser.add_argument("--idempotency-key", help="幂等键（1..128 可打印 ASCII）")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # pragma: no cover - 非常规 stdout
        pass

    if args.build_id or args.idempotency_key:
        if not (args.build_id and args.idempotency_key):
            response = {
                "ok": False,
                "method": METHOD_STAGE,
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": "--build-id 与 --idempotency-key 必须同时提供",
                    "phase": "validate",
                    "effectState": "none",
                    "details": {},
                    "codeOrigin": "contract",
                },
            }
        else:
            response = handle_request(
                {
                    "method": METHOD_STAGE,
                    "params": {
                        "buildId": args.build_id,
                        "idempotencyKey": args.idempotency_key,
                    },
                }
            )
    else:
        raw = sys.stdin.read()
        try:
            request = json.loads(raw)
        except ValueError as exc:
            response = {
                "ok": False,
                "method": None,
                "error": {
                    "code": "VALIDATION_FAILED",
                    "message": f"stdin 不是合法 JSON: {exc}",
                    "phase": "validate",
                    "effectState": "none",
                    "details": {},
                    "codeOrigin": "contract",
                },
            }
        else:
            response = handle_request(request)

    sys.stdout.write(json.dumps(response, ensure_ascii=False, indent=2) + "\n")
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
