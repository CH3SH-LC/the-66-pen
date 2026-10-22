#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产领域接口（纯标准库），供 bridge 集成调用。

对外只有一个入口::

    dispatch(method: str, params: dict) -> dict

成功返回业务结果 dict；失败抛 :class:`AssetApiError`（带机器可读 code）。
协议外壳、请求校验、幂等锁由 ``bridge/`` 提供，本模块**只实现业务函数**，
不生成响应信封。

实现的方法
----------
* ``mw.catalog.search``  — 用 ``ast`` 静态解析上游 ``block_config.py``，取出
  真实方块模板字段。**只解析、从不执行上游代码**（无 import / exec / eval）。
* ``mw.scene.build``     — 用固定的 ``mvp/generate_mvp.py`` 生成 GIA，参数受限
  （只允许 ``--scene`` / ``--out``，两路径都由本模块推导，调用方无法注入
  argv、命令行字符串或程序路径）。产物写到内容寻址目录
  ``.runtime/mvp/builds/<输入与生成器哈希>/``。
* ``mw.asset.inspect``   — 对构建区 GIA 做严格容器检查，并复用
  ``mvp/verify_mvp.py`` 的独立解码器读出实体，返回「名字 → 模板 ID」映射。
* ``mw.build.validate``  — 用构建记录里的源哈希核对当前 ``scene.json`` 与
  ``generate_mvp.py`` 是否被改动，并逐实体与 scene 比对。

范围声明
--------
所有结果固定带 ``backend=file``、``evidenceLevel=offline-tested``、
``gameAccepted=unknown``。本模块**不做**部署、导入、启动游戏、UI 或结算；
离线文件自洽不等于游戏接受了该资产。generator 是只读依赖，本模块不建也不改它。
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------
# 路径与常量
# --------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent           # .../mvp
REPO_ROOT = HERE.parent
BUILDS_DIR = REPO_ROOT / ".runtime" / "mvp" / "builds"

GENERATOR_PATH = HERE / "generate_mvp.py"
VERIFIER_PATH = HERE / "verify_mvp.py"
DEFAULT_SCENE = "scene.json"

#: 上游模板字段的唯一真源。注意：只读 + 只做 AST 解析，禁止执行。
BLOCK_CONFIG_PATH = (
    REPO_ROOT
    / "third_party/UGC-File-Generate-Utils/config/block_config.py"
)

BACKEND = "file"
EVIDENCE_LEVEL = "offline-tested"
GAME_ACCEPTED = "unknown"

#: 构建目录名 = 输入(scene)与生成器(generate_mvp.py)的内容哈希。
BUILD_ID_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
BUILD_TIMEOUT_S = 90
DEFAULT_TOLERANCE = 2e-5

# GIA 外壳常量（与 generate_mvp.py / verify_mvp.py 保持一致，独立复述）
# 外壳 5 个头部字段与尾魔数均为 **大端序**（>5I / >I），与上游 auto-miliastra
# core/gi_file.py、verify_formats.py 的读法一致；载荷内部仍是小端（varint + <f）。
HEAD_MAGIC = 0x00000326
TAIL_MAGIC = 0x00000679
FILE_VERSION = 1
FILE_TYPE_GIA = 3
HEADER_SIZE = 20
TAIL_SIZE = 4


# --------------------------------------------------------------------------
# 错误
# --------------------------------------------------------------------------
CONTRACT_CODES = frozenset(
    {
        "VALIDATION_FAILED",
        "CAPABILITY_UNAVAILABLE",
        "REFERENCE_UNRESOLVED",
        "LOSSY_ROUNDTRIP",
        "LIMIT_EXCEEDED",
        "COMPILER_FAILED",
    }
)

#: 与 bridge/errors.py 的扩展码同名，便于 bridge 直接透传。
BRIDGE_CODES = frozenset({"METHOD_UNKNOWN", "PARAM_FORBIDDEN", "BACKEND_UNAVAILABLE"})

ALL_CODES = CONTRACT_CODES | BRIDGE_CODES

PHASES = frozenset({"validate", "authorize", "preflight", "effect", "observe", "report"})


class AssetApiError(Exception):
    """带机器可读 code 的失败。bridge 可据此构造错误信封。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        phase: str = "validate",
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in ALL_CODES:
            raise AssertionError(f"undeclared asset-api error code: {code}")
        if phase not in PHASES:
            raise AssertionError(f"unknown phase: {phase}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.phase = phase
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "phase": self.phase,
            "effectState": "none",
            "details": self.details,
            "codeOrigin": "contract" if self.code in CONTRACT_CODES else "bridge-extension",
        }


def _require(condition: bool, message: str, **details: Any) -> None:
    if not condition:
        raise AssetApiError("VALIDATION_FAILED", message, details=details)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _rel(path: Path) -> str:
    """转成仓库相对路径（POSIX 风格）；不在仓库内则回退为文件名。"""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.name


def _rfc3339_now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 参数与路径安全
# --------------------------------------------------------------------------
def _unknown_params(method: str, params: dict[str, Any]) -> list[str]:
    allowed = PARAMS_BY_METHOD[method]
    return sorted(set(params) - allowed)


def _reject_unknown_params(method: str, params: dict[str, Any]) -> None:
    unknown = _unknown_params(method, params)
    if unknown:
        raise AssetApiError(
            "PARAM_FORBIDDEN",
            f"{method} does not accept parameter(s): {', '.join(unknown)}",
            details={
                "method": method,
                "unknownParams": unknown,
                "allowedParams": sorted(PARAMS_BY_METHOD[method]),
                "note": (
                    "本接口使用封闭参数表。它无法被传入可执行文件路径、命令行字符串、"
                    "shell 或任意参数。"
                ),
            },
        )


def _bounded_text(value: Any, field: str, *, max_len: int = 64) -> str:
    _require(isinstance(value, str), f"{field} must be a string", field=field)
    _require(0 < len(value) <= max_len, f"{field} must be 1..{max_len} characters", field=field)
    _require(
        not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value),
        f"{field} must not contain control characters",
        field=field,
    )
    return value


def _bounded_int(value: Any, field: str, *, lo: int, hi: int) -> int:
    _require(
        isinstance(value, int) and not isinstance(value, bool),
        f"{field} must be an integer",
        field=field,
    )
    _require(lo <= value <= hi, f"{field} must be within {lo}..{hi}", field=field)
    return value


def _bounded_bool(value: Any, field: str) -> bool:
    _require(isinstance(value, bool), f"{field} must be a boolean", field=field)
    return value


def _resolve_in_mvp(rel: Any, field: str) -> Path:
    """把 mvp/ 内的相对路径解析成绝对路径，越界一律拒绝。

    拒绝：绝对路径、盘符/UNC、任何 ``..`` 段、反斜杠、冒号、非 .json。
    解析后再用 ``resolve()``（跟随符号链接）确认仍在 ``mvp/`` 之内。
    """
    _require(isinstance(rel, str) and rel != "", f"{field} must be a non-empty string", field=field)
    _require(len(rel) <= 128, f"{field} is too long", field=field)
    _require(rel.isascii(), f"{field} must be ASCII", field=field)
    _require("\\" not in rel, f"{field} must use forward slashes", field=field)
    _require(":" not in rel, f"{field} must be a relative path without a drive", field=field)
    _require(
        not Path(rel).is_absolute(),
        f"{field} must not be an absolute path",
        field=field,
        received=rel,
    )

    parts = [p for p in rel.split("/") if p not in ("", ".")]
    _require(".." not in parts, f"{field} must not contain '..'", field=field, received=rel)
    _require(len(parts) > 0, f"{field} must name a file", field=field)

    candidate = HERE.joinpath(*parts)
    resolved = candidate.resolve()
    _require(
        resolved.is_relative_to(HERE),
        f"{field} must stay inside mvp/",
        field=field,
        received=rel,
        mvpDir=str(HERE),
    )
    _require(resolved.is_file(), f"{field} does not exist: {rel}", field=field, received=rel)
    _require(
        resolved.suffix == ".json",
        f"{field} must be a .json file",
        field=field,
        received=rel,
    )
    return resolved


def _resolve_build_dir(build_id: Any) -> Path:
    if build_id is None:
        return _latest_build_dir()
    _require(
        isinstance(build_id, str) and BUILD_ID_RE.match(build_id) is not None,
        "buildId must be a 64-character lowercase hex build key",
        field="buildId",
    )
    path = BUILDS_DIR / build_id
    _require(path.is_dir(), f"unknown buildId: {build_id}", field="buildId")
    return path


def _latest_build_dir() -> Path:
    if not BUILDS_DIR.is_dir():
        raise AssetApiError(
            "REFERENCE_UNRESOLVED",
            "no build区 exists yet; run mw.scene.build first",
            details={"buildsDir": _rel(BUILDS_DIR)},
        )
    candidates = sorted(
        (p for p in BUILDS_DIR.iterdir() if p.is_dir() and BUILD_ID_RE.match(p.name)),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    if not candidates:
        raise AssetApiError(
            "REFERENCE_UNRESOLVED",
            "no completed build found; run mw.scene.build first",
            details={"buildsDir": _rel(BUILDS_DIR)},
        )
    return candidates[-1]


def _read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AssetApiError(
            "REFERENCE_UNRESOLVED", f"{field} not found: {_rel(path)}", details={"path": _rel(path)}
        ) from exc
    except (OSError, ValueError) as exc:
        raise AssetApiError(
            "LOSSY_ROUNDTRIP",
            f"{field} is not readable JSON: {exc.__class__.__name__}: {exc}",
            details={"path": _rel(path)},
        ) from exc
    _require(isinstance(value, dict), f"{field} must be a JSON object", path=_rel(path))
    return value


_SCENE_REQUIRED_KEYS = ("scene_id", "entity_id_start", "templates", "entities", "constraints")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _load_scene_document(scene_path: Path) -> dict[str, Any]:
    """读 scene 文档并核对生成器会直接索引的字段。

    只检查**文档形状**（generate_mvp.py 会直接 KeyError/TypeError 的那些键），
    不重复它的布局语义校验：几何是否跳得过去仍旧由生成器判定，失败即
    COMPILER_FAILED。形状不对是调用方的错，用 VALIDATION_FAILED 提前挡住，
    免得为一个格式错误的输入白跑一次子进程、还把错误算在生成器头上。
    """
    scene = _read_json(scene_path, "scene")
    for key in _SCENE_REQUIRED_KEYS:
        _require(
            key in scene,
            f"scene is missing required key {key!r}",
            field="scene",
            missingKey=key,
        )
    _require(isinstance(scene["scene_id"], str), "scene.scene_id must be a string", field="scene_id")
    _require(
        isinstance(scene["entity_id_start"], int)
        and not isinstance(scene["entity_id_start"], bool),
        "scene.entity_id_start must be an integer",
        field="entity_id_start",
    )
    _require(
        isinstance(scene["templates"], dict) and bool(scene["templates"]),
        "scene.templates must be a non-empty object",
        field="templates",
    )
    _require(
        isinstance(scene["constraints"], dict),
        "scene.constraints must be an object",
        field="constraints",
    )
    _require(
        isinstance(scene["entities"], list) and bool(scene["entities"]),
        "scene.entities must be a non-empty array",
        field="entities",
    )
    for index, entity in enumerate(scene["entities"]):
        _require(
            isinstance(entity, dict),
            "each scene entity must be an object",
            field="entities",
            index=index,
        )
        _require(
            isinstance(entity.get("name"), str) and bool(entity["name"]),
            "each scene entity needs a non-empty string name",
            field="name",
            index=index,
        )
        _require(
            isinstance(entity.get("template_id"), int)
            and not isinstance(entity["template_id"], bool),
            "each scene entity needs an integer template_id",
            field="template_id",
            index=index,
        )
        for axis in ("position", "rotation", "scale"):
            vector = entity.get(axis)
            _require(
                isinstance(vector, list) and len(vector) == 3 and all(_is_number(v) for v in vector),
                f"each scene entity needs a {axis} of exactly 3 numbers",
                field=axis,
                index=index,
            )
    return scene


# --------------------------------------------------------------------------
# mw.catalog.search — AST 解析上游 block_config.py（不执行）
# --------------------------------------------------------------------------
def _literal(node: ast.AST) -> tuple[Any, bool]:
    """只接受字面量；不做任何求值。返回 (value, ok)。"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (bool, int, float, str)):
            return node.value, True
        return None, False
    if isinstance(node, ast.Tuple):
        values = []
        for element in node.elts:
            value, ok = _literal(element)
            if not ok:
                return None, False
            values.append(value)
        return tuple(values), True
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and not isinstance(node.operand.value, bool)
    ):
        return -node.operand.value, True
    return None, False


def _leading_comment(lines: list[str], lineno: int) -> str | None:
    """取 ``lineno``（1 起）上方最近的连续注释行作为人类可读名字。"""
    index = lineno - 2
    while index >= 0 and not lines[index].strip():
        index -= 1
    if index < 0:
        return None
    text = lines[index].strip()
    if text.startswith("#"):
        return text[1:].strip() or None
    return None


def _assigns_to(statement: ast.stmt, name: str) -> ast.AST | None:
    """取 ``x = ...`` / ``x: T = ...`` 的右值；目标名不是 ``name`` 时返回 None。"""
    if isinstance(statement, ast.Assign):
        targets = statement.targets
        value: ast.AST | None = statement.value
    elif isinstance(statement, ast.AnnAssign):
        targets = [statement.target]
        value = statement.value
    else:
        return None
    if value is None:
        return None
    for target in targets:
        if isinstance(target, ast.Name) and target.id == name:
            return value
        # 兼容 ``BlockConfig.AVAILABLE_BLOCKS = [...]`` 这类限定目标
        if isinstance(target, ast.Attribute) and target.attr == name:
            return value
    return None


def _find_block_list(tree: ast.AST) -> ast.List | None:
    """在 ``BlockConfig.AVAILABLE_BLOCKS`` 上找列表字面量。

    上游源码用的是带注解的赋值（``AVAILABLE_BLOCKS: List[BlockTemplate] = [...]``），
    对应 ``ast.AnnAssign`` 而非 ``ast.Assign``，两者都要认。
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "BlockConfig":
            continue
        for statement in node.body:
            value = _assigns_to(statement, "AVAILABLE_BLOCKS")
            if isinstance(value, ast.List):
                return value
    return None


#: 分类的派生规则：取名字中第一个成对括号之前的基名（``木质箱子（绿）`` -> ``木质箱子``）。
_CATEGORY_BRACKETS = (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]"))


def _derive_category(name: str | None) -> str | None:
    """从模板名字派生一个**工程侧分组键**。

    这是派生分组，不是原生资源类型：上游 ``block_config.py`` 不声明分类，编辑器原生
    ``prefab-catalog`` 的 ``nativeKind`` 也取不到可用分类（实测 2720/2722 恒为 0）。
    规则 = 名字里第一个成对括号之前的基名；没有括号则取整名。调用方必须把 ``category``
    当工程侧分组看待，不能当游戏原生分类的证据。
    """
    if not isinstance(name, str):
        return None
    text = name.strip()
    if not text:
        return None
    for open_ch, _close_ch in _CATEGORY_BRACKETS:
        index = text.find(open_ch)
        if 0 < index:
            base = text[:index].strip()
            if base:
                return base
    return text


def _parse_block_config() -> dict[str, Any]:
    if not BLOCK_CONFIG_PATH.is_file():
        raise AssetApiError(
            "CAPABILITY_UNAVAILABLE",
            "upstream block_config.py not found; the catalog source is missing",
            details={"expectedPath": _rel(BLOCK_CONFIG_PATH)},
        )
    raw = BLOCK_CONFIG_PATH.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssetApiError(
            "CAPABILITY_UNAVAILABLE",
            f"block_config.py is not valid UTF-8: {exc}",
            details={"path": _rel(BLOCK_CONFIG_PATH)},
        ) from exc

    try:
        tree = ast.parse(text, filename=str(BLOCK_CONFIG_PATH))
    except SyntaxError as exc:
        raise AssetApiError(
            "CAPABILITY_UNAVAILABLE",
            f"block_config.py failed to parse: {exc.__class__.__name__}: {exc}",
            details={"path": _rel(BLOCK_CONFIG_PATH), "line": exc.lineno},
        ) from exc

    block_list = _find_block_list(tree)
    if block_list is None:
        raise AssetApiError(
            "CAPABILITY_UNAVAILABLE",
            "BlockConfig.AVAILABLE_BLOCKS list literal not found by AST",
            details={"path": _rel(BLOCK_CONFIG_PATH)},
        )

    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    unparsed: list[dict[str, Any]] = []

    for element in block_list.elts:
        if not isinstance(element, ast.Call):
            unparsed.append({"line": getattr(element, "lineno", None), "reason": "not a call"})
            continue

        func = element.func
        func_name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if func_name != "BlockTemplate":
            unparsed.append(
                {"line": element.lineno, "reason": f"callee is not BlockTemplate: {func_name}"}
            )
            continue
        if element.args:
            unparsed.append(
                {"line": element.lineno, "reason": "positional arguments are not supported"}
            )
            continue

        values: dict[str, Any] = {}
        bad: str | None = None
        for keyword in element.keywords:
            if keyword.arg is None:
                bad = "**kwargs is not supported"
                break
            value, ok = _literal(keyword.value)
            if not ok:
                bad = f"non-literal value for argument {keyword.arg!r}; not evaluated"
                break
            values[keyword.arg] = value
        if bad is not None:
            unparsed.append({"line": element.lineno, "reason": bad})
            continue

        template_id = values.get("template_id")
        color = values.get("color_tuple", ())
        size_units = values.get("size_units")
        default_scale = values.get("default_scale_tuple", (1.0, 1.0, 1.0))

        if not isinstance(template_id, int) or isinstance(template_id, bool) or template_id <= 0:
            unparsed.append({"line": element.lineno, "reason": "template_id is not a positive int"})
            continue
        if not (
            isinstance(color, tuple)
            and len(color) == 3
            and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)
        ):
            unparsed.append({"line": element.lineno, "reason": "color_tuple is not 3 ints in 0..255"})
            continue
        if not isinstance(size_units, (int, float)) or isinstance(size_units, bool) or size_units <= 0:
            unparsed.append({"line": element.lineno, "reason": "size_units is not a positive number"})
            continue
        if not (
            isinstance(default_scale, tuple)
            and len(default_scale) == 3
            and all(
                isinstance(s, (int, float)) and not isinstance(s, bool) and s > 0
                for s in default_scale
            )
        ):
            unparsed.append(
                {"line": element.lineno, "reason": "default_scale_tuple is not 3 positive numbers"}
            )
            continue

        name = _leading_comment(lines, element.lineno)
        blocks.append(
            {
                "templateId": int(template_id),
                "name": name,
                "category": _derive_category(name),
                "colorRgb": [int(c) for c in color],
                "sizeUnits": float(size_units),
                "defaultScale": [float(s) for s in default_scale],
                "sourceLine": element.lineno,
            }
        )

    blocks.sort(key=lambda b: b["templateId"])
    return {
        "blocks": blocks,
        "unparsed": unparsed,
        "source": {
            "path": _rel(BLOCK_CONFIG_PATH),
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
            "language": "python-ast",
            "executed": False,
            "note": "仅 ast.parse 静态解析；未 import / exec / eval 上游代码。",
        },
    }


def _category_counts(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按派生分类统计条目数，按分类名排序 —— 供调用方枚举分类、驱动分页。"""
    tally: dict[str, int] = {}
    for block in blocks:
        key = block.get("category")
        if isinstance(key, str) and key:
            tally[key] = tally.get(key, 0) + 1
    return [{"category": k, "count": tally[k]} for k in sorted(tally)]


def catalog_search(params: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_block_config()
    blocks = parsed["blocks"]

    query = params.get("query")
    if query is not None:
        query = _bounded_text(query, "query")
    template_id = params.get("templateId")
    if template_id is not None:
        template_id = _bounded_int(template_id, "templateId", lo=1, hi=2**31 - 1)
    category = params.get("category")
    if category is not None:
        category = _bounded_text(category, "category")
    limit = _bounded_int(params.get("limit", 50), "limit", lo=1, hi=200)
    offset = _bounded_int(params.get("offset", 0), "offset", lo=0, hi=1_000_000)

    matched = blocks
    if template_id is not None:
        matched = [b for b in matched if b["templateId"] == template_id]
    if category is not None:
        needle_cat = category.casefold()
        matched = [
            b for b in matched if (b["category"] or "").casefold() == needle_cat
        ]
    if query is not None:
        needle = query.casefold()
        matched = [
            b
            for b in matched
            if needle in (b["name"] or "").casefold() or needle in str(b["templateId"])
        ]

    window = matched[offset : offset + limit]
    has_more = offset + len(window) < len(matched)
    return {
        "blocks": window,
        "categories": _category_counts(blocks),
        "query": query,
        "templateId": template_id,
        "category": category,
        "offset": offset,
        "limit": limit,
        "totalInSource": len(blocks),
        "matched": len(matched),
        "returned": len(window),
        "nextOffset": (offset + len(window)) if has_more else None,
        "hasMore": has_more,
        "unparsedEntries": parsed["unparsed"],
        "source": parsed["source"],
        "warnings": (
            [f"{len(parsed['unparsed'])} 条记录无法按字面量解析，已跳过而非求值"]
            if parsed["unparsed"]
            else []
        ),
    }


# --------------------------------------------------------------------------
# mw.scene.build — 运行固定生成器，产物写内容寻址目录
# --------------------------------------------------------------------------
def _build_id_for(scene_sha: str, generator_sha: str) -> str:
    material = f"scene.json={scene_sha}\ngenerate_mvp.py={generator_sha}\n"
    return sha256_bytes(material.encode("utf-8"))


def _commit_build(staging: Path, final: Path, *, overwrite: bool) -> None:
    """把暂存目录落位；同名目录已存在时按 overwrite 决定复用或替换。"""
    if final.exists():
        if not overwrite:
            shutil.rmtree(staging, ignore_errors=True)
            return
        old = final.with_name(f".old-{final.name}-{os.getpid()}")
        shutil.rmtree(old, ignore_errors=True)
        try:
            os.rename(final, old)
            os.rename(staging, final)
        except OSError as exc:
            raise AssetApiError(
                "BACKEND_UNAVAILABLE",
                f"could not replace build directory: {exc.__class__.__name__}: {exc}",
                phase="effect",
                details={"buildDir": _rel(final)},
            ) from exc
        shutil.rmtree(old, ignore_errors=True)
        return
    try:
        os.rename(staging, final)
    except OSError as exc:
        raise AssetApiError(
            "BACKEND_UNAVAILABLE",
            f"could not commit build directory: {exc.__class__.__name__}: {exc}",
            phase="effect",
            details={"buildDir": _rel(final)},
        ) from exc


def scene_build(params: dict[str, Any]) -> dict[str, Any]:
    scene_rel = params.get("scene", DEFAULT_SCENE)
    scene_path = _resolve_in_mvp(scene_rel, "scene")
    _load_scene_document(scene_path)  # 形状预检：调用方的错误不落到生成器头上
    overwrite = (
        _bounded_bool(params["overwrite"], "overwrite") if "overwrite" in params else False
    )

    if not GENERATOR_PATH.is_file():
        raise AssetApiError(
            "CAPABILITY_UNAVAILABLE",
            "mvp/generate_mvp.py is missing; the pinned generator is not available",
            details={"generator": _rel(GENERATOR_PATH)},
        )

    scene_sha = sha256_file(scene_path)
    generator_sha = sha256_file(GENERATOR_PATH)
    build_id = _build_id_for(scene_sha, generator_sha)
    final_dir = BUILDS_DIR / build_id
    record_path = final_dir / "build-record.json"

    BUILDS_DIR.mkdir(parents=True, exist_ok=True)

    if final_dir.is_dir() and record_path.is_file() and not overwrite:
        record = _read_json(record_path, "build record")
        record["reused"] = True
        record["buildDir"] = _rel(final_dir)
        record["note"] = "内容寻址命中：输入与生成器哈希未变，未重新运行生成器。"
        return record

    staging = BUILDS_DIR / f".staging-{build_id[:12]}-{os.getpid()}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    # 固定程序、固定参数字表：只有 --scene / --out 两项，且都由本模块推导。
    argv = [
        sys.executable,
        str(GENERATOR_PATH),
        "--scene",
        str(scene_path),
        "--out",
        str(staging),
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    try:
        try:
            phase_start = time.perf_counter()
            child = subprocess.Popen(
                argv,
                cwd=str(REPO_ROOT),
                env=env,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            spawn_seconds = time.perf_counter() - phase_start
            try:
                stdout_bytes, stderr_bytes = child.communicate(timeout=BUILD_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                raise
            elapsed_seconds = time.perf_counter() - phase_start
            completed = subprocess.CompletedProcess(argv, child.returncode, stdout_bytes, stderr_bytes)
        except subprocess.TimeoutExpired as exc:
            raise AssetApiError(
                "COMPILER_FAILED",
                f"generate_mvp.py timed out after {BUILD_TIMEOUT_S}s",
                phase="effect",
            details={"generator": _rel(GENERATOR_PATH), "timeoutSeconds": BUILD_TIMEOUT_S,
                     "phaseTimings": {"spawnSeconds": spawn_seconds,
                                      "totalSeconds": time.perf_counter() - phase_start},
                     "childReturncode": child.returncode},
            ) from exc
        except OSError as exc:
            raise AssetApiError(
                "CAPABILITY_UNAVAILABLE",
                f"could not run the generator: {exc.__class__.__name__}: {exc}",
                phase="effect",
                details={"generator": _rel(GENERATOR_PATH), "program": sys.executable},
            ) from exc

        stdout = completed.stdout.decode("utf-8", errors="replace")
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if completed.returncode != 0:
            raise AssetApiError(
                "COMPILER_FAILED",
                f"generate_mvp.py exited with code {completed.returncode}",
                phase="effect",
                details={
                    "generator": _rel(GENERATOR_PATH),
                    "returncode": completed.returncode,
                    "stdout": stdout[-4000:],
                    "stderr": stderr[-4000:],
                },
            )

        gia_path = staging / "platformer_min.gia"
        manifest_path = staging / "manifest.json"
        if not gia_path.is_file() or not manifest_path.is_file():
            raise AssetApiError(
                "COMPILER_FAILED",
                "generator reported success but did not produce platformer_min.gia + manifest.json",
                phase="effect",
                details={
                    "produced": sorted(p.name for p in staging.iterdir()),
                    "stdout": stdout[-2000:],
                    "stderr": stderr[-2000:],
                },
            )

        manifest = _read_json(manifest_path, "generated manifest")
        declared = manifest.get("sources", {})
        if declared.get("scene_json_sha256") != scene_sha or declared.get(
            "generator_sha256"
        ) != generator_sha:
            raise AssetApiError(
                "LOSSY_ROUNDTRIP",
                "generated manifest records different input hashes than the ones we supplied",
                phase="observe",
                details={
                    "expectedScene": scene_sha,
                    "recordedScene": declared.get("scene_json_sha256"),
                    "expectedGenerator": generator_sha,
                    "recordedGenerator": declared.get("generator_sha256"),
                },
            )

        gia_blob = gia_path.read_bytes()
        record = {
            "schema": "miliastra-asset-api-build/1",
            "buildId": build_id,
            "buildDir": _rel(final_dir),
            "inputs": {
                "scene": {
                    "path": _rel(scene_path),
                    "bytes": scene_path.stat().st_size,
                    "sha256": scene_sha,
                },
                "generator": {
                    "path": _rel(GENERATOR_PATH),
                    "bytes": GENERATOR_PATH.stat().st_size,
                    "sha256": generator_sha,
                },
            },
            "generatorRun": {
                "phaseTimings": {"spawnSeconds": spawn_seconds,
                                 "communicateSeconds": elapsed_seconds - spawn_seconds,
                                 "totalSeconds": elapsed_seconds},
                "timeoutSeconds": BUILD_TIMEOUT_S,
                "stdin": "DEVNULL",
                "program": sys.executable,
                "argv": argv,
                "shell": False,
                "cwd": _rel(REPO_ROOT),
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            "artifacts": {
                "gia": {
                    "path": gia_path.name,
                    "bytes": len(gia_blob),
                    "sha256": sha256_bytes(gia_blob),
                },
                "manifest": {
                    "path": manifest_path.name,
                    "bytes": manifest_path.stat().st_size,
                    "sha256": sha256_file(manifest_path),
                },
            },
            "manifest": manifest,
            "reused": False,
            "backend": BACKEND,
            "evidenceLevel": EVIDENCE_LEVEL,
            "gameAccepted": GAME_ACCEPTED,
            "createdAt": _rfc3339_now(),
            "note": (
                "离线产物记录。生成器由本工程固定提供，未接收任何调用方参数；"
                "本记录不表示游戏已接受该资产。"
            ),
        }
        (staging / "build-record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        _commit_build(staging, final_dir, overwrite=overwrite)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return record


# --------------------------------------------------------------------------
# 独立解码器（复用 mvp/verify_mvp.py，失败时退回内置实现并标注）
# --------------------------------------------------------------------------
_decoder_cache: dict[str, Any] = {}


def _load_verifier_decoder() -> dict[str, Any]:
    """按文件路径加载 verify_mvp.py 的独立解码器，不污染 sys.path / sys.modules。

    verify_mvp.py 的模块级代码只有定义与常量，没有副作用；本函数不执行它的 main()。
    """
    if _decoder_cache:
        return _decoder_cache

    info: dict[str, Any] = {
        "source": _rel(VERIFIER_PATH),
        "function": "decode_payload_independent",
        "sha256": None,
        "reused": False,
        "fallback": False,
        "reason": None,
        "decode": _decode_payload_builtin,
    }
    if VERIFIER_PATH.is_file():
        raw = VERIFIER_PATH.read_bytes()
        info["sha256"] = sha256_bytes(raw)
        previous = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec = importlib.util.spec_from_file_location("_mvp_verify_mvp_loaded", VERIFIER_PATH)
            module = importlib.util.module_from_spec(spec) if spec and spec.loader else None
            if module is not None and spec is not None and spec.loader is not None:
                spec.loader.exec_module(module)
                decode = getattr(module, "decode_payload_independent", None)
                if callable(decode):
                    info["reused"] = True
                    info["decode"] = decode
        except Exception as exc:  # pragma: no cover - 依赖另一 CC 的收尾状态
            info["reason"] = f"{exc.__class__.__name__}: {exc}"
        finally:
            sys.dont_write_bytecode = previous
    else:
        info["reason"] = "mvp/verify_mvp.py not found"

    if not info["reused"]:
        info["fallback"] = True
        info["reason"] = info["reason"] or "verifier decoder unavailable; used built-in decoder"

    _decoder_cache.update(info)
    return _decoder_cache


# --- 内置退回解码器：纯标准库，独立于生成器（仅在 verify_mvp.py 不可用时使用） ---
def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _iter_fields(buf: bytes):
    pos = 0
    while pos < len(buf):
        tag, pos = _read_varint(buf, pos)
        field, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, pos = _read_varint(buf, pos)
            yield field, wire_type, value
        elif wire_type == 2:
            length, pos = _read_varint(buf, pos)
            yield field, wire_type, buf[pos : pos + length]
            pos += length
        elif wire_type == 5:
            yield field, wire_type, buf[pos : pos + 4]
            pos += 4
        elif wire_type == 1:
            yield field, wire_type, buf[pos : pos + 8]
            pos += 8
        else:
            raise ValueError(f"unknown wire type {wire_type}")


def _first(buf: bytes, field: int, wire_type: int):
    for f, w, value in _iter_fields(buf):
        if f == field and w == wire_type:
            return value
    return None


def _all(buf: bytes, field: int, wire_type: int) -> list:
    return [v for f, w, v in _iter_fields(buf) if f == field and w == wire_type]


def _decode_vec3(buf: bytes) -> list[float]:
    out = [0.0, 0.0, 0.0]
    for f, w, value in _iter_fields(buf):
        if w == 5 and 1 <= f <= 3:
            out[f - 1] = struct.unpack("<f", value)[0]
    return out


def _decode_payload_builtin(payload: bytes) -> list[dict]:
    entities = []
    for asset in _all(payload, 1, 2):
        if _first(asset, 5, 0) != 3:  # Asset.type != ENTITY
            continue
        entity_msg = _first(asset, 12, 2)
        if entity_msg is None:
            continue
        data = _first(entity_msg, 1, 2)
        if data is None:
            continue
        asset_name = (_first(asset, 3, 2) or b"").decode("utf-8", errors="replace")

        prop_name = ""
        for prop in _all(data, 5, 2):
            if _first(prop, 1, 0) == 1:  # PropertyType.NAME
                name_prop = _first(prop, 11, 2)
                if name_prop is not None:
                    prop_name = (_first(name_prop, 1, 2) or b"").decode("utf-8", errors="replace")

        position = rotation = None
        scale = [1.0, 1.0, 1.0]
        for comp in _all(data, 6, 2):
            if _first(comp, 1, 0) != 1:  # ComponentType.TRANSFORM
                continue
            transform = _first(comp, 11, 2)
            if transform is None:
                continue
            pos_msg = _first(transform, 1, 2)
            rot_msg = _first(transform, 2, 2)
            scl_msg = _first(transform, 3, 2)
            position = _decode_vec3(pos_msg) if pos_msg is not None else [0.0, 0.0, 0.0]
            rotation = _decode_vec3(rot_msg) if rot_msg is not None else [0.0, 0.0, 0.0]
            scale = _decode_vec3(scl_msg) if scl_msg is not None else [1.0, 1.0, 1.0]
            break

        entities.append(
            {
                "name": asset_name or prop_name,
                "template_id": _first(entity_msg, 4, 0) or 0,
                "entity_id": _first(data, 1, 0) or 0,
                "position": position or [0.0, 0.0, 0.0],
                "rotation": rotation or [0.0, 0.0, 0.0],
                "scale": scale,
            }
        )
    return entities


# --------------------------------------------------------------------------
# 容器检查
# --------------------------------------------------------------------------
def _check(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"check": name, "ok": bool(ok), "detail": detail}


def _container_checks(blob: bytes) -> tuple[list[dict[str, Any]], bytes | None]:
    checks: list[dict[str, Any]] = []
    total = len(blob)
    checks.append(_check("长度至少 24 字节外壳", total >= HEADER_SIZE + TAIL_SIZE, f"total={total}"))
    if total < HEADER_SIZE + TAIL_SIZE:
        return checks, None

    file_size, version, head_magic, file_type, content_length = struct.unpack(">5I", blob[:20])
    tail_magic = struct.unpack(">I", blob[-4:])[0]

    checks.append(_check("头魔数 0x00000326", head_magic == HEAD_MAGIC, hex(head_magic)))
    checks.append(_check("尾魔数 0x00000679", tail_magic == TAIL_MAGIC, hex(tail_magic)))
    # 字节序自检：小端读法必须给出无意义值，否则说明外壳被写成了别的字节序。
    checks.append(
        _check(
            "外壳字节序为大端（小端读法无意义）",
            struct.unpack("<I", blob[:4])[0] != file_size,
            f"LE={struct.unpack('<I', blob[:4])[0]}",
        )
    )
    checks.append(_check("version = 1", version == FILE_VERSION, str(version)))
    checks.append(_check(f"file_type = {FILE_TYPE_GIA} (GIA)", file_type == FILE_TYPE_GIA, str(file_type)))
    checks.append(_check("file_size = 总长-4", file_size == total - 4, f"{file_size} vs {total - 4}"))
    checks.append(
        _check(
            "content_length = 总长-24",
            content_length == total - HEADER_SIZE - TAIL_SIZE,
            f"{content_length} vs {total - HEADER_SIZE - TAIL_SIZE}",
        )
    )
    payload = blob[HEADER_SIZE : total - TAIL_SIZE]
    checks.append(_check("载荷实长与声明一致", content_length == len(payload), f"{len(payload)}"))
    return checks, payload


def _decode_entities(payload: bytes) -> tuple[list[dict] | None, str | None]:
    decoder = _load_verifier_decoder()
    try:
        return decoder["decode"](payload), None
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"


# --------------------------------------------------------------------------
# mw.asset.inspect — 严格容器检查 + 独立解码 + 名字→模板ID
# --------------------------------------------------------------------------
def asset_inspect(params: dict[str, Any]) -> dict[str, Any]:
    build_dir = _resolve_build_dir(params.get("buildId"))
    record = _read_json(build_dir / "build-record.json", "build record")

    artifact_name = record.get("artifacts", {}).get("gia", {}).get("path")
    _require(
        isinstance(artifact_name, str)
        and artifact_name != ""
        and Path(artifact_name).name == artifact_name
        and artifact_name.endswith(".gia"),
        "build record does not name a plain .gia artifact",
        buildDir=_rel(build_dir),
        recorded=artifact_name,
    )
    artifact_path = build_dir / artifact_name
    _require(artifact_path.is_file(), "artifact file is missing", artifact=artifact_name)

    size = artifact_path.stat().st_size
    if size > MAX_ARTIFACT_BYTES:
        raise AssetApiError(
            "LIMIT_EXCEEDED",
            f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes",
            details={"artifact": artifact_name, "bytes": size},
        )
    blob = artifact_path.read_bytes()

    checks, payload = _container_checks(blob)
    entities: list[dict] = []
    decode_error: str | None = None
    if payload is not None:
        decoded, decode_error = _decode_entities(payload)
        if decoded is None:
            checks.append(_check("独立解码载荷", False, decode_error or "decode failed"))
        else:
            checks.append(_check("独立解码载荷", True, f"{len(decoded)} 个实体"))
            entities = decoded

    decoder = _load_verifier_decoder()
    expected = record.get("manifest", {}).get("entities", [])
    if payload is not None and entities:
        checks.append(
            _check("实体数量与生成清单一致", len(entities) == len(expected), f"{len(entities)} vs {len(expected)}")
        )

    artifact_sha = sha256_bytes(blob)
    recorded_sha = record.get("artifacts", {}).get("gia", {}).get("sha256")
    manifest_sha = record.get("manifest", {}).get("artifact", {}).get("sha256")
    checks.append(_check("文件 sha256 与构建记录一致", artifact_sha == recorded_sha, f"{artifact_sha[:16]}…"))
    checks.append(_check("文件 sha256 与生成清单一致", artifact_sha == manifest_sha, f"{artifact_sha[:16]}…"))

    warnings = list(record.get("warnings", []))
    if decoder["fallback"]:
        warnings.append(
            "DECODER_FALLBACK: mvp/verify_mvp.py 的独立解码器不可用，已改用内置解码器；"
            f"原因: {decoder['reason']}"
        )

    return {
        "buildId": build_dir.name,
        "buildDir": _rel(build_dir),
        "artifact": {
            "path": artifact_name,
            "bytes": len(blob),
            "sha256": artifact_sha,
            "expectedSha256": recorded_sha,
        },
        "container": {
            "headerBytes": HEADER_SIZE,
            "tailBytes": TAIL_SIZE,
            "invariant": "file_size = total-4; content_length = total-24",
        },
        "checks": checks,
        "valid": all(c["ok"] for c in checks),
        "entities": entities,
        "entityCount": len(entities),
        "nameTemplateMap": [
            {"name": e["name"], "templateId": e["template_id"]} for e in entities
        ],
        "decoder": {
            "source": decoder["source"],
            "function": decoder["function"],
            "sha256": decoder["sha256"],
            "reused": decoder["reused"],
            "fallback": decoder["fallback"],
            "reason": decoder["reason"],
        },
        "decodeError": decode_error,
        "inputsFromRecord": record.get("inputs"),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# mw.build.validate — 源哈希检查 + 逐实体比对
# --------------------------------------------------------------------------
def _close(a: Any, b: Any, tol: float) -> bool:
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def build_validate(params: dict[str, Any]) -> dict[str, Any]:
    scene_path = _resolve_in_mvp(params.get("scene", DEFAULT_SCENE), "scene")
    build_dir = _resolve_build_dir(params.get("buildId"))
    record = _read_json(build_dir / "build-record.json", "build record")
    scene = _load_scene_document(scene_path)

    checks: list[dict[str, Any]] = []

    # --- 源哈希检查：构建后 scene / generator 是否被改动 ---
    scene_sha = sha256_file(scene_path)
    recorded_scene_sha = record.get("inputs", {}).get("scene", {}).get("sha256")
    checks.append(
        _check(
            "scene.json 源哈希与构建时一致",
            scene_sha == recorded_scene_sha,
            f"now={scene_sha[:16]}… built={str(recorded_scene_sha)[:16]}…",
        )
    )

    generator_sha = sha256_file(GENERATOR_PATH) if GENERATOR_PATH.is_file() else None
    recorded_generator_sha = record.get("inputs", {}).get("generator", {}).get("sha256")
    checks.append(
        _check(
            "generate_mvp.py 哈希与构建时一致",
            generator_sha == recorded_generator_sha,
            f"now={str(generator_sha)[:16]}… built={str(recorded_generator_sha)[:16]}…",
        )
    )

    # --- 容器与解码：直接复用 inspect 的真结果，不重复实现 ---
    inspection = asset_inspect({"buildId": build_dir.name})
    container_failed = [c["check"] for c in inspection["checks"] if not c["ok"]]
    checks.append(
        _check("容器检查与独立解码全部通过", not container_failed, ", ".join(container_failed))
    )
    checks.append(
        _check(
            "实体数量与 scene 一致",
            inspection["entityCount"] == len(scene.get("entities", [])),
            f"{inspection['entityCount']} vs {len(scene.get('entities', []))}",
        )
    )

    # --- 逐实体比对 ---
    tolerance = float(scene.get("constraints", {}).get("tolerance", DEFAULT_TOLERANCE))
    start_id = int(scene.get("entity_id_start", 0))
    templates = scene.get("templates", {})
    decoded = inspection["entities"]
    expected_entities = scene.get("entities", [])

    comparison: list[dict[str, Any]] = []
    all_match = True
    if len(decoded) == len(expected_entities):
        for index, (got, want) in enumerate(zip(decoded, expected_entities)):
            template_ok = got["template_id"] == int(want["template_id"])
            name_ok = got["name"] == want["name"]
            entity_id_ok = got["entity_id"] == start_id + index
            transform_ok = (
                _close(got["position"], want["position"], tolerance)
                and _close(got["rotation"], want["rotation"], tolerance)
                and _close(got["scale"], want["scale"], tolerance)
            )
            registered = str(int(want["template_id"])) in templates
            row_ok = template_ok and name_ok and entity_id_ok and transform_ok and registered
            all_match &= row_ok
            comparison.append(
                {
                    "index": index,
                    "name": want["name"],
                    "templateIdMatch": template_ok,
                    "nameMatch": name_ok,
                    "entityIdMatch": entity_id_ok,
                    "transformMatch": transform_ok,
                    "templateRegisteredInScene": registered,
                    "ok": row_ok,
                }
            )
    else:
        all_match = False

    checks.append(_check("逐实体 名称/模板ID/唯一ID/变换 全部匹配", all_match))

    warnings: list[str] = []
    if not generator_sha:
        warnings.append("GENERATOR_MISSING: mvp/generate_mvp.py 不存在，无法核对生成器哈希。")
    if generator_sha is not None and generator_sha != recorded_generator_sha:
        warnings.append(
            "GENERATOR_CHANGED: 生成器在构建之后被改动，本构建的产物与当前生成器不再对应；"
            "请重跑 mw.scene.build。"
        )
    if scene_sha != recorded_scene_sha:
        warnings.append(
            "SCENE_CHANGED: scene.json 在构建之后被改动，本构建不再代表当前场景；请重跑 mw.scene.build。"
        )

    return {
        "buildId": build_dir.name,
        "buildDir": _rel(build_dir),
        "scene": _rel(scene_path),
        "checks": checks,
        "valid": all(c["ok"] for c in checks),
        "entityComparison": comparison,
        "tolerance": tolerance,
        "sourceHashes": {
            "scene": {"now": scene_sha, "atBuild": recorded_scene_sha},
            "generator": {"now": generator_sha, "atBuild": recorded_generator_sha},
        },
        "artifact": inspection["artifact"],
        "nameTemplateMap": inspection["nameTemplateMap"],
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
PARAMS_BY_METHOD: dict[str, frozenset[str]] = {
    "mw.catalog.search": frozenset(
        {"query", "templateId", "category", "limit", "offset"}
    ),
    "mw.scene.build": frozenset({"scene", "overwrite"}),
    "mw.asset.inspect": frozenset({"buildId"}),
    "mw.build.validate": frozenset({"buildId", "scene"}),
}

KNOWN_METHODS = tuple(sorted(PARAMS_BY_METHOD))

_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "mw.catalog.search": catalog_search,
    "mw.scene.build": scene_build,
    "mw.asset.inspect": asset_inspect,
    "mw.build.validate": build_validate,
}


def dispatch(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """执行一个资产领域方法。

    成功返回业务结果 dict（结尾固定带 backend / evidenceLevel / gameAccepted /
    warnings 四个范围字段）；失败抛 :class:`AssetApiError`。
    """
    if not isinstance(method, str) or method not in _HANDLERS:
        raise AssetApiError(
            "METHOD_UNKNOWN",
            f"method {method!r} is not implemented by the asset api",
            details={"knownMethods": list(KNOWN_METHODS)},
        )
    if params is None:
        params = {}
    _require(isinstance(params, dict), "params must be a JSON object")

    _reject_unknown_params(method, params)
    payload = dict(_HANDLERS[method](params))
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


def describe() -> dict[str, Any]:
    """给 bridge 用的自述：方法表、参数表、错误码与范围声明。"""
    return {
        "module": "mvp.asset_api",
        "methods": {m: sorted(PARAMS_BY_METHOD[m]) for m in KNOWN_METHODS},
        "errorCodes": sorted(ALL_CODES),
        "contractCodes": sorted(CONTRACT_CODES),
        "bridgeExtensionCodes": sorted(BRIDGE_CODES),
        "backend": BACKEND,
        "evidenceLevel": EVIDENCE_LEVEL,
        "gameAccepted": GAME_ACCEPTED,
    }
